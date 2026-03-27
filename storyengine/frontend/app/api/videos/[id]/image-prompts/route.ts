import { NextResponse } from "next/server";
import { getSupabaseVideoDetail } from "@/lib/pipeline/supabase-store";
import { logStageTransition, insertPromptAssets } from "@/lib/pipeline/write-store";

const MODEL = "claude-sonnet-4-5-20250929";

type SceneImage = {
  script_segment: string;
  shot_type: string;
  prompt: string;
  image_url?: string;
};

function buildSystemPrompt() {
  return `You are an expert visual director for AI-generated documentary videos.

YOUR TASK: Segment scene narration into distinct visual concepts and generate image prompts for each.

=== SEGMENTATION RULES ===
1. Each segment represents one distinct visual concept.
2. Break narration where the visual should change.
3. Aim for 4-8 segments per scene.
4. Each segment should cover roughly 6-10 seconds of narration.
5. Do not repeat the same script segment across multiple outputs.

=== OUTPUT FORMAT ===
Return raw JSON only:
{
  "scene_images": [
    {
      "script_segment": "Exact narration excerpt",
      "shot_type": "establishing",
      "prompt": "Full image prompt..."
    }
  ]
}`;
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
    const { sceneNumber } = body as { sceneNumber?: number };

    if (typeof sceneNumber !== "number") {
      return NextResponse.json(
        { error: "sceneNumber is required" },
        { status: 400 }
      );
    }

    const detail = await getSupabaseVideoDetail(id);
    if (!detail) {
      return NextResponse.json({ error: "Video not found" }, { status: 404 });
    }

    const videoId = detail.video.id ?? id;
    const tenantId =
      typeof detail.video.tenant_id === "string" ? detail.video.tenant_id : "";
    const title =
      typeof detail.video.video_title === "string" ? detail.video.video_title : "";
    const scene = detail.scenes.find((item) => item.sceneNumber === sceneNumber);

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

    if (!scene?.sceneText) {
      return NextResponse.json(
        { error: `No script scene found for scene ${sceneNumber}` },
        { status: 404 }
      );
    }

    await logStageTransition({
      tenantId,
      videoId,
      fromStatus: fromStatusForLogging,
      toStatus: "Generating Image Prompts",
      triggeredBy: "storyengine_ui",
    });

    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) {
      throw new Error("ANTHROPIC_API_KEY is not configured");
    }

    const response = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: 4096,
        temperature: 1.0,
        system: buildSystemPrompt(),
        messages: [
          {
            role: "user",
            content: `Segment this scene narration into visual concepts and generate image prompts.

VIDEO TITLE: "${title}"
SCENE NUMBER: ${scene.sceneNumber}

FULL NARRATION:
${scene.sceneText}

Create 4-8 segments.
Each segment must map to a different portion of the narration.
Return raw JSON only.`,
          },
        ],
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Anthropic API error: ${response.status} ${errorText}`);
    }

    const payload = (await response.json()) as {
      content?: Array<{ type: string; text?: string }>;
    };
    const textBlock = payload.content?.[0];
    if (!textBlock || textBlock.type !== "text" || !textBlock.text) {
      throw new Error("Unexpected response type from Anthropic API");
    }

    const cleaned = textBlock.text
      .replace(/```json\n?/g, "")
      .replace(/```\n?/g, "")
      .trim();

    const data = JSON.parse(cleaned) as { scene_images?: SceneImage[] };
    const sceneImages = Array.isArray(data.scene_images) ? data.scene_images : [];

    const insertResult = await insertPromptAssets(
      sceneImages.map((item, index) => ({
        tenantId,
        videoId,
        sceneNumber: scene.sceneNumber,
        videoTitle: title,
        sentenceIndex: index + 1,
        sentenceText: item.script_segment,
        imageIndex: index + 1,
        imagePrompt: item.prompt,
        shotType: item.shot_type,
        status: "Pending",
      }))
    );

    await logStageTransition({
      tenantId,
      videoId,
      fromStatus: fromStatusForLogging,
      toStatus: insertResult.error ? "Image Prompts Generated (Asset Insert Failed)" : "Ready For Images",
      triggeredBy: "storyengine_ui",
      errorMessage: insertResult.error ?? undefined,
    });

    return NextResponse.json({
      scene_images: sceneImages,
      inserted_assets: insertResult.inserted.length,
      asset_insert_error: insertResult.error,
    });
  } catch (error) {
    if (tenantIdForLogging) {
      await logStageTransition({
        tenantId: tenantIdForLogging,
        videoId: videoIdForLogging,
        fromStatus: fromStatusForLogging,
        toStatus: "Image Prompt Failure",
        triggeredBy: "storyengine_ui",
        errorMessage: error instanceof Error ? error.message : "Unknown error",
      });
    }

    console.error("Image prompt generation failed:", error);
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Image prompt generation failed",
      },
      { status: 500 }
    );
  }
}
