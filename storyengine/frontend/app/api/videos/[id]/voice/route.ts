import { NextResponse } from "next/server";
import { getSupabaseVideoDetail } from "@/lib/pipeline/supabase-store";
import {
  logStageTransition,
  updateScriptVoice,
} from "@/lib/pipeline/write-store";
import { uploadGeneratedAudio } from "@/lib/pipeline/asset-storage";

const ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech";
const DEFAULT_VOICE_ID = "G17SuINrv2H9FC6nvetn";
const DEFAULT_MODEL_ID = "eleven_multilingual_v2";

async function generateVoiceAudio(args: {
  apiKey: string;
  text: string;
  voiceId: string;
  modelId: string;
}): Promise<ArrayBuffer> {
  const response = await fetch(`${ELEVENLABS_API_URL}/${args.voiceId}`, {
    method: "POST",
    headers: {
      "xi-api-key": args.apiKey,
      Accept: "audio/mpeg",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      text: args.text,
      model_id: args.modelId,
      output_format: "mp3_44100_128",
      voice_settings: {
        stability: 0.5,
        similarity_boost: 1.0,
        use_speaker_boost: true,
      },
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Voice API error: ${response.status} ${errorText}`);
  }

  const audioBuffer = await response.arrayBuffer();
  if (audioBuffer.byteLength === 0) {
    throw new Error("Voice API returned empty audio");
  }

  return audioBuffer;
}

async function uploadVoiceToGoogleDrive(args: {
  audioBuffer: ArrayBuffer;
  video: { id?: string | number; video_title?: string };
  sceneNumber: number;
}): Promise<string> {
  const videoLabel =
    typeof args.video.video_title === "string" && args.video.video_title.trim()
      ? args.video.video_title.trim()
      : `video-${String(args.video.id ?? "untitled")}`;
  const result = await uploadGeneratedAudio({
    video: args.video,
    fileName: `${videoLabel} - Scene ${args.sceneNumber}.mp3`,
    content: Buffer.from(args.audioBuffer),
  });
  return result.url;
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
    const { sceneNumber, force } = body as {
      sceneNumber?: number;
      force?: boolean;
    };

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

    const tenantId =
      typeof detail.video.tenant_id === "string" ? detail.video.tenant_id : "";
    const videoId = detail.video.id ?? id;
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

    const existingVoiceUrl =
      typeof scene.voiceOverUrl === "string" ? scene.voiceOverUrl : "";
    const normalizedVoiceStatus =
      typeof scene.voiceStatus === "string" ? scene.voiceStatus.toLowerCase() : "";

    if (!force && existingVoiceUrl) {
      return NextResponse.json({
        sceneNumber,
        voice_over_url: existingVoiceUrl,
        skipped: true,
        reason: "voice already exists",
      });
    }

    if (
      !force &&
      (normalizedVoiceStatus === "generating" || normalizedVoiceStatus === "done")
    ) {
      return NextResponse.json({
        sceneNumber,
        voice_over_url: existingVoiceUrl || null,
        skipped: true,
        reason: `voice already ${normalizedVoiceStatus}`,
      });
    }

    await logStageTransition({
      tenantId,
      videoId,
      fromStatus: fromStatusForLogging,
      toStatus: "Generating Voice",
      triggeredBy: "storyengine_ui",
    });

    const scriptId = scene.id;
    await updateScriptVoice({
      scriptId,
      voiceStatus: "Generating",
    });

    const apiKey = process.env.ELEVENLABS_API_KEY;
    if (!apiKey) {
      throw new Error("ELEVENLABS_API_KEY is not configured");
    }

    const voiceId = process.env.ELEVENLABS_VOICE_ID || DEFAULT_VOICE_ID;
    const modelId = process.env.ELEVENLABS_MODEL_ID || DEFAULT_MODEL_ID;
    const startedAt = Date.now();
    const audioBuffer = await generateVoiceAudio({
      apiKey,
      text: scene.sceneText,
      voiceId,
      modelId,
    });
    const outputUrl = await uploadVoiceToGoogleDrive({
      audioBuffer,
      video: detail.video,
      sceneNumber: scene.sceneNumber,
    });
    const durationSeconds = Math.max(
      1,
      Math.round((Date.now() - startedAt) / 1000)
    );

    const updateResult = await updateScriptVoice({
      scriptId,
      voiceStatus: "Done",
      voiceOverUrl: outputUrl,
      voiceId,
      voiceDurationSeconds: durationSeconds,
    });

    await logStageTransition({
      tenantId,
      videoId,
      fromStatus: fromStatusForLogging,
      toStatus: updateResult.error ? "Voice Generated (Script Update Failed)" : "Voice Ready",
      triggeredBy: "storyengine_ui",
      durationSeconds,
      errorMessage: updateResult.error ?? undefined,
    });

    return NextResponse.json({
      sceneNumber,
      voice_over_url: outputUrl,
      script_update_error: updateResult.error,
    });
  } catch (error) {
    if (tenantIdForLogging) {
      await logStageTransition({
        tenantId: tenantIdForLogging,
        videoId: videoIdForLogging,
        fromStatus: fromStatusForLogging,
        toStatus: "Voice Failure",
        triggeredBy: "storyengine_ui",
        errorMessage: error instanceof Error ? error.message : "Unknown error",
      });
    }

    console.error("Voice generation failed:", error);
    return NextResponse.json(
      {
        error:
          error instanceof Error ? error.message : "Voice generation failed",
      },
      { status: 500 }
    );
  }
}
