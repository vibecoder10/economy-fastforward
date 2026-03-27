import { createServiceRoleSupabaseClient } from "@/lib/supabase/server";
import type { AssetRow, StageTransitionRow } from "./types";

type TransitionInput = {
  tenantId: string;
  videoId: string | number;
  fromStatus?: string;
  toStatus: string;
  triggeredBy: string;
  cost?: number;
  durationSeconds?: number;
  errorMessage?: string;
};

type PromptAssetInput = {
  tenantId: string;
  videoId: string | number;
  sceneNumber: number;
  videoTitle?: string;
  sentenceIndex?: number;
  sentenceText?: string;
  imageIndex?: number;
  imagePrompt: string;
  shotType?: string;
  status?: string;
};

type ScriptVoiceUpdateInput = {
  scriptId: string | number;
  voiceStatus?: string | null;
  voiceOverUrl?: string | null;
  voiceId?: string | null;
  voiceDurationSeconds?: number | null;
};

type VideoDriveFolderInput = {
  videoId: string | number;
  driveFolderId: string;
  driveFolderLink: string;
};

type AssetUpdateInput = {
  assetId: string | number;
  status?: string | null;
  imageUrl?: string | null;
  videoUrl?: string | null;
  videoClipUrl?: string | null;
  soundEffectUrl?: string | null;
  generationMethod?: string | null;
  contentType?: string | null;
  driveImageUrl?: string | null;
  animationStatus?: string | null;
  videoStatus?: string | null;
};

export async function logStageTransition(
  input: TransitionInput
): Promise<StageTransitionRow | null> {
  const supabase = createServiceRoleSupabaseClient();
  const row = {
    tenant_id: input.tenantId,
    video_id: input.videoId,
    from_status: input.fromStatus ?? null,
    to_status: input.toStatus,
    triggered_by: input.triggeredBy,
    cost: input.cost ?? 0,
    duration_seconds: input.durationSeconds ?? null,
    error_message: input.errorMessage ?? null,
  };

  const { data, error } = await supabase
    .from("stage_transitions")
    .insert(row)
    .select("*")
    .limit(1);

  if (error) {
    console.error("Failed to log stage transition:", error);
    return null;
  }

  return ((data || [])[0] || null) as StageTransitionRow | null;
}

export async function insertPromptAssets(
  rows: PromptAssetInput[]
): Promise<{ inserted: AssetRow[]; error: string | null }> {
  const supabase = createServiceRoleSupabaseClient();

  const payload = rows.map((row) => ({
    tenant_id: row.tenantId,
    video_id: row.videoId,
    video_title: row.videoTitle ?? null,
    scene: row.sceneNumber,
    sentence_index: row.sentenceIndex ?? null,
    sentence_text: row.sentenceText ?? null,
    image_index: row.imageIndex ?? null,
    status: row.status ?? "generated",
    image_prompt: row.imagePrompt,
    shot_type: row.shotType ?? null,
  }));

  const { data, error } = await supabase.from("assets").insert(payload).select("*");

  if (error) {
    console.error("Failed to insert prompt assets:", error);
    return { inserted: [], error: error.message };
  }

  return { inserted: (data || []) as AssetRow[], error: null };
}

export async function updateScriptVoice(
  input: ScriptVoiceUpdateInput
): Promise<{ success: boolean; error: string | null }> {
  const supabase = createServiceRoleSupabaseClient();
  const payload = {
    voice_status: input.voiceStatus ?? null,
    voice_over_url: input.voiceOverUrl ?? null,
    voice_id: input.voiceId ?? null,
    voice_duration_seconds: input.voiceDurationSeconds ?? null,
  };

  const { error } = await supabase
    .from("scripts")
    .update(payload)
    .eq("id", input.scriptId);

  if (error) {
    console.error("Failed to update script voice:", error);
    return { success: false, error: error.message };
  }

  return { success: true, error: null };
}

export async function updateVideoDriveFolder(
  input: VideoDriveFolderInput
): Promise<{ success: boolean; error: string | null }> {
  const supabase = createServiceRoleSupabaseClient();
  const { error } = await supabase
    .from("videos")
    .update({
      drive_folder_id: input.driveFolderId,
      drive_folder_link: input.driveFolderLink,
    })
    .eq("id", input.videoId);

  if (error) {
    console.error("Failed to update video drive folder:", error);
    return { success: false, error: error.message };
  }

  return { success: true, error: null };
}

export async function updateAssetRow(
  input: AssetUpdateInput
): Promise<{ success: boolean; error: string | null }> {
  const supabase = createServiceRoleSupabaseClient();
  const payload = {
    status: input.status ?? null,
    image_url: input.imageUrl ?? null,
    video_url: input.videoUrl ?? null,
    video_clip_url: input.videoClipUrl ?? null,
    sound_effect_url: input.soundEffectUrl ?? null,
    generation_method: input.generationMethod ?? null,
    content_type: input.contentType ?? null,
    drive_image_url: input.driveImageUrl ?? null,
    animation_status: input.animationStatus ?? null,
    video_status: input.videoStatus ?? null,
  };

  const { error } = await supabase
    .from("assets")
    .update(payload)
    .eq("id", input.assetId);

  if (error) {
    console.error("Failed to update asset row:", error);
    return { success: false, error: error.message };
  }

  return { success: true, error: null };
}
