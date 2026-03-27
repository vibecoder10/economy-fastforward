import { NextResponse } from "next/server";
import { getSupabaseVideoDetail } from "@/lib/pipeline/supabase-store";
import {
  logStageTransition,
  updateAssetRow,
} from "@/lib/pipeline/write-store";
import { proxyGeneratedImage } from "@/lib/pipeline/asset-storage";

const CREATE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask";
const RECORD_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo";
const DEFAULT_IMAGE_MODEL = "nano-banana-2";

async function createImageTask(args: {
  apiKey: string;
  prompt: string;
  aspectRatio?: string;
  model?: string;
}): Promise<string> {
  const response = await fetch(CREATE_TASK_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${args.apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: args.model || DEFAULT_IMAGE_MODEL,
      input: {
        prompt: args.prompt,
        image_size: args.aspectRatio || "16:9",
        output_format: "png",
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
    throw new Error("Kie API did not return a taskId");
  }

  return taskId;
}

async function pollImageCompletion(args: {
  apiKey: string;
  taskId: string;
  maxAttempts?: number;
  pollIntervalMs?: number;
}): Promise<string> {
  const maxAttempts = args.maxAttempts ?? 45;
  const pollIntervalMs = args.pollIntervalMs ?? 2000;

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
      throw new Error("Kie image generation failed");
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

  throw new Error("Kie image generation timed out");
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

    if (!asset?.image_prompt) {
      return NextResponse.json(
        { error: "Asset not found or missing image_prompt" },
        { status: 404 }
      );
    }

    const existingImageUrl =
      typeof asset.drive_image_url === "string" && asset.drive_image_url
        ? asset.drive_image_url
        : typeof asset.image_url === "string" && asset.image_url
          ? asset.image_url
          : "";
    const normalizedStatus =
      typeof asset.status === "string" ? asset.status.toLowerCase() : "";

    if (!force && existingImageUrl) {
      return NextResponse.json({
        asset_id: assetId,
        image_url: existingImageUrl,
        skipped: true,
        reason: "image already exists",
      });
    }

    if (
      !force &&
      (normalizedStatus === "generating" || normalizedStatus === "pending")
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
      toStatus: "Generating Image",
      triggeredBy: "storyengine_ui",
    });

    await updateAssetRow({
      assetId,
      status: "Generating",
      generationMethod: "kie_ai",
      contentType: "image",
    });

    const apiKey = process.env.KIE_AI_API_KEY;
    if (!apiKey) {
      throw new Error("KIE_AI_API_KEY is not configured");
    }

    const taskId = await createImageTask({
      apiKey,
      prompt: asset.image_prompt,
    });
    const providerUrl = await pollImageCompletion({
      apiKey,
      taskId,
    });

    const fileName = `${detail.video.video_title || "video"} - Scene ${asset.scene || 0} - Image ${asset.image_index || 1}.png`;
    const driveResult = await proxyGeneratedImage({
      video: detail.video,
      fileName,
      sourceUrl: providerUrl,
      mimeType: "image/png",
    });

    const updateResult = await updateAssetRow({
      assetId,
      status: "Done",
      imageUrl: driveResult.url,
      driveImageUrl: driveResult.url,
      generationMethod: "kie_ai",
      contentType: "image",
    });

    await logStageTransition({
      tenantId,
      videoId,
      fromStatus: fromStatusForLogging,
      toStatus: updateResult.error ? "Image Generated (Asset Update Failed)" : "Image Ready",
      triggeredBy: "storyengine_ui",
      errorMessage: updateResult.error ?? undefined,
    });

    return NextResponse.json({
      asset_id: assetId,
      image_url: driveResult.url,
      asset_update_error: updateResult.error,
    });
  } catch (error) {
    if (tenantIdForLogging) {
      await logStageTransition({
        tenantId: tenantIdForLogging,
        videoId: videoIdForLogging,
        fromStatus: fromStatusForLogging,
        toStatus: "Image Failure",
        triggeredBy: "storyengine_ui",
        errorMessage: error instanceof Error ? error.message : "Unknown error",
      });
    }

    console.error("Image generation failed:", error);
    return NextResponse.json(
      {
        error: error instanceof Error ? error.message : "Image generation failed",
      },
      { status: 500 }
    );
  }
}
