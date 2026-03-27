import { NextResponse } from "next/server";
import { getSupabaseVideoDetail } from "@/lib/pipeline/supabase-store";
import {
  logStageTransition,
  updateAssetRow,
} from "@/lib/pipeline/write-store";
import { proxyGeneratedVideo } from "@/lib/pipeline/asset-storage";

const CREATE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask";
const RECORD_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo";

async function createVideoTask(args: {
  apiKey: string;
  imageUrl: string;
  prompt: string;
  duration?: number;
}): Promise<string> {
  const response = await fetch(CREATE_TASK_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${args.apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "grok-imagine/image-to-video",
      input: {
        image_urls: [args.imageUrl],
        prompt: args.prompt,
        duration: args.duration === 10 ? "10" : "6",
        mode: "normal",
      },
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Kie createTask error: ${response.status} ${errorText}`);
  }

  const data = (await response.json()) as { data?: { taskId?: string } };
  const taskId = data?.data?.taskId;
  if (!taskId) {
    throw new Error("Kie video API did not return a taskId");
  }

  return taskId;
}

async function pollVideoCompletion(args: {
  apiKey: string;
  taskId: string;
  maxAttempts?: number;
  pollIntervalMs?: number;
}): Promise<string> {
  const maxAttempts = args.maxAttempts ?? 120;
  const pollIntervalMs = args.pollIntervalMs ?? 5000;

  for (let index = 0; index < maxAttempts; index += 1) {
    const response = await fetch(
      `${RECORD_INFO_URL}?taskId=${encodeURIComponent(args.taskId)}`,
      {
        headers: {
          Authorization: `Bearer ${args.apiKey}`,
        },
      }
    );

    if (!response.ok) {
      await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
      continue;
    }

    const statusPayload = (await response.json()) as {
      data?: { status?: number; resultJson?: unknown };
    };
    const status = statusPayload?.data?.status;
    if (status === 3) {
      throw new Error("Kie clip generation failed");
    }

    const resultJson = statusPayload?.data?.resultJson;
    if (resultJson) {
      const parsed =
        typeof resultJson === "string" ? JSON.parse(resultJson) : resultJson;
      const urls = (parsed as { resultUrls?: string[] })?.resultUrls;
      if (Array.isArray(urls) && urls.length > 0 && urls[0]) {
        return urls[0];
      }
    }

    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }

  throw new Error("Kie clip generation timed out");
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  let tenantIdForLogging: string | null = null;
  let videoIdForLogging: string | number = id;
  let fromStatusForLogging: string | undefined;

  try {
    const body = await request.json();
    const { assetId, force } = body as { assetId?: string; force?: boolean };

    if (!assetId) {
      return NextResponse.json({ error: "assetId is required" }, { status: 400 });
    }

    const detail = await getSupabaseVideoDetail(id);
    if (!detail) {
      return NextResponse.json({ error: "Video not found" }, { status: 404 });
    }

    const tenantId =
      typeof detail.video.tenant_id === "string" ? detail.video.tenant_id : "";
    const videoId = detail.video.id ?? id;
    const asset = detail.assets.find((item) => String(item.id) === String(assetId));

    tenantIdForLogging = tenantId || null;
    videoIdForLogging = videoId;
    fromStatusForLogging =
      typeof detail.video.status === "string" ? detail.video.status : undefined;

    if (!tenantId) {
      return NextResponse.json(
        { error: "Video is missing tenant_id" },
        { status: 500 }
      );
    }

    const sourceImageUrl =
      asset?.drive_image_url || asset?.image_url || undefined;
    const clipPrompt = asset?.video_prompt || asset?.image_prompt || undefined;

    if (!asset || !sourceImageUrl || !clipPrompt) {
      return NextResponse.json(
        { error: "Asset not found or missing source image/prompt for clip generation" },
        { status: 404 }
      );
    }

    const existingClipUrl =
      typeof asset.video_clip_url === "string" && asset.video_clip_url
        ? asset.video_clip_url
        : "";
    const normalizedStatus =
      typeof asset.status === "string" ? asset.status.toLowerCase() : "";

    if (!force && existingClipUrl) {
      return NextResponse.json({
        asset_id: assetId,
        video_clip_url: existingClipUrl,
        skipped: true,
        reason: "clip already exists",
      });
    }

    if (
      !force &&
      (normalizedStatus === "generating clip" || normalizedStatus === "generating")
    ) {
      return NextResponse.json({
        asset_id: assetId,
        skipped: true,
        reason: `asset already ${normalizedStatus}`,
      });
    }

    await logStageTransition({
      tenantId,
      videoId,
      fromStatus: fromStatusForLogging,
      toStatus: "Generating Clip",
      triggeredBy: "storyengine_ui",
    });

    await updateAssetRow({
      assetId,
      status: "Generating Clip",
      generationMethod: "kie_ai",
      contentType: "video",
      videoStatus: "Generating",
    });

    const apiKey = process.env.KIE_AI_API_KEY;
    if (!apiKey) {
      throw new Error("KIE_AI_API_KEY is not configured");
    }

    const taskId = await createVideoTask({
      apiKey,
      imageUrl: sourceImageUrl,
      prompt: clipPrompt,
    });
    const providerUrl = await pollVideoCompletion({
      apiKey,
      taskId,
    });

    const fileName = `${detail.video.video_title || "video"} - Scene ${asset.scene || 0} - Clip ${asset.image_index || 1}.mp4`;
    const driveResult = await proxyGeneratedVideo({
      video: detail.video,
      fileName,
      sourceUrl: providerUrl,
      mimeType: "video/mp4",
    });

    const updateResult = await updateAssetRow({
      assetId,
      status: "Done",
      videoClipUrl: driveResult.url,
      videoUrl: driveResult.url,
      generationMethod: "kie_ai",
      contentType: "video",
      videoStatus: "Done",
      animationStatus: "Done",
    });

    await logStageTransition({
      tenantId,
      videoId,
      fromStatus: fromStatusForLogging,
      toStatus: updateResult.error ? "Clip Generated (Asset Update Failed)" : "Clip Ready",
      triggeredBy: "storyengine_ui",
      errorMessage: updateResult.error ?? undefined,
    });

    return NextResponse.json({
      asset_id: assetId,
      video_clip_url: driveResult.url,
      asset_update_error: updateResult.error,
    });
  } catch (error) {
    if (tenantIdForLogging) {
      await logStageTransition({
        tenantId: tenantIdForLogging,
        videoId: videoIdForLogging,
        fromStatus: fromStatusForLogging,
        toStatus: "Clip Failure",
        triggeredBy: "storyengine_ui",
        errorMessage: error instanceof Error ? error.message : "Unknown error",
      });
    }

    console.error("Clip generation failed:", error);
    return NextResponse.json(
      {
        error: error instanceof Error ? error.message : "Clip generation failed",
      },
      { status: 500 }
    );
  }
}
