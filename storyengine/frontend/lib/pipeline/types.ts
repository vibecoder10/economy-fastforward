export type PipelineRow = Record<string, unknown>;

export interface VideoRow extends PipelineRow {
  id?: string | number;
  tenant_id?: string;
  project_id?: string;
  video_title?: string;
  status?: string;
  drive_folder_id?: string;
  drive_folder_link?: string;
}

export interface ScriptRow extends PipelineRow {
  id?: string | number;
  tenant_id?: string;
  video_id?: string | number;
  scene?: number;
  title?: string;
  scene_text?: string;
  script_status?: string;
  voice_status?: string;
  voice_over_url?: string;
}

export interface AssetRow extends PipelineRow {
  id?: string | number;
  tenant_id?: string;
  video_id?: string | number;
  airtable_record_id?: string;
  video_title?: string;
  scene?: number;
  sentence_index?: number;
  sentence_text?: string;
  image_index?: number;
  image_prompt?: string;
  video_prompt?: string;
  shot_type?: string;
  image_url?: string;
  drive_image_url?: string;
  status?: string;
  content_type?: string;
  generation_method?: string;
  video_status?: string;
  video_clip_url?: string;
  animation_status?: string;
}

export interface StageTransitionRow extends PipelineRow {
  id?: string | number;
  tenant_id?: string;
  video_id?: string | number;
  from_status?: string;
  to_status?: string;
  triggered_by?: string;
  cost?: number;
  duration_seconds?: number;
  error_message?: string;
  created_at?: string;
}

export interface VideoSceneViewModel {
  id: string;
  sceneNumber: number;
  sceneText: string;
  scriptStatus: string;
  voiceStatus: string;
  voiceOverUrl?: string;
  assets: AssetRow[];
}

export interface VideoDetailViewModel {
  video: VideoRow;
  scenes: VideoSceneViewModel[];
  assets: AssetRow[];
  transitions: StageTransitionRow[];
}
