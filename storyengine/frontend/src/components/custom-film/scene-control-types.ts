export const SCENE_CONTROL_STATES = [
  "draft",
  "plan_approved",
  "storyboard_approved",
  "imagery_approved",
  "animation_approved",
  "audio_approved",
  "assembled",
  "accepted",
] as const;

export type SceneControlState = (typeof SCENE_CONTROL_STATES)[number];
export type SceneRailStatus =
  | "locked"
  | "current"
  | "accepted"
  | "invalidated";
export type ArtifactStatus =
  | "missing"
  | "ready_for_review"
  | "approved"
  | "rejected";
export interface SceneControlFilmLock {
  id: string;
  label: string;
  summary: string;
  status: "draft" | "locked" | "invalidated";
  revision_hash: string;
  reviewable?: boolean;
  payload?: unknown;
}

export interface SceneControlArtifact {
  id: string;
  label: string;
  kind: "storyboard" | "image" | "animation" | "audio" | "assembly";
  status: ArtifactStatus;
  deterministic: boolean;
  detail?: string;
}

export interface SceneControlDialogueTurn {
  id: string;
  speaker_id: string;
  speaker_label: string;
  text: string;
  performance_intent: string;
  start_seconds: number;
  end_seconds: number;
  timing_label?: string;
}

export interface SceneControlShot {
  id: string;
  shot_key: string;
  order: number;
  title: string;
  duration_seconds: number;
  narrative_function: string;
  advancement: string;
  opening_state: string;
  closing_state: string;
  character_action: string;
  camera_action: string;
  transition: string;
  continuity_inputs: string[];
  continuity_outputs: string[];
  performance_mode: "dialogue" | "exposition" | "silent_action";
  dialogue: SceneControlDialogueTurn[];
  artifacts: SceneControlArtifact[];
  preview?: {
    url: string;
    start_frame: number;
    end_frame: number;
    sha256: string;
  };
}

export interface SceneControlScene {
  id: string;
  number: number;
  title: string;
  purpose: string;
  target_duration_seconds: number;
  story_time: string;
  state: SceneControlState;
  rail_status: SceneRailStatus;
  revision_hash: string;
  invalidation_reason?: string;
  transition_evidence_hashes: Partial<Record<SceneControlState, string>>;
  environment_label: string;
  character_labels: string[];
  shots: SceneControlShot[];
  assembly_preview?: {
    url: string;
    duration_frames: number;
    sha256: string;
    current_for_acceptance: boolean;
  };
}

export interface SceneControlOperationQuote {
  quote_version: number;
  video_id: string;
  scene_id: string;
  scene_number: number;
  shot_ids: string[];
  operation_type:
    | "storyboard_images"
    | "final_imagery"
    | "animate_shot"
    | "dialogue_audio"
    | "assemble_scene";
  provider_operation:
    | "storyboard_image"
    | "final_picture"
    | "animation_clip"
    | "voice_line"
    | "remotion_assembly";
  deterministic: boolean;
  initial_calls: number;
  max_repair_calls: number;
  unit_max_cents: number;
  exact_incremental_max_cents: number;
  prior_completed_cumulative_spend_cents: number;
  new_exact_cumulative_ceiling_cents: number;
  included_media: string[];
  explicitly_unapproved: string[];
  approval_status: "not_approved";
  approval_card_hash: string;
  scene_revision_hash: string;
}

export interface SceneControlSnapshot {
  film_id: string;
  title: string;
  film_revision_hash: string;
  film_locks_approved: boolean;
  film_locks: SceneControlFilmLock[];
  scenes: SceneControlScene[];
  current_scene_id: string;
  next_operation?: SceneControlOperationQuote;
}

export interface SceneControlTransitionRequest {
  scene_id: string;
  from_state: SceneControlState;
  to_state: SceneControlState;
  expected_revision_hash: string;
  evidence_hash: string;
}

export interface SceneControlRejectRequest {
  scene_id: string;
  shot_id?: string;
  return_to: SceneControlState;
  expected_revision_hash: string;
}

export interface SceneControlQuoteRequest {
  scene_id: string;
  shot_id?: string;
  expected_revision_hash: string;
  operation_type: SceneControlOperationQuote["operation_type"];
}

export interface SceneControlCockpitProps {
  snapshot: SceneControlSnapshot;
  busy?: boolean;
  onReviewFilmLock?: (lockId: string, payload: unknown) => void;
  onTransition: (request: SceneControlTransitionRequest) => void;
  onReject: (request: SceneControlRejectRequest) => void;
  onRequestQuote?: (request: SceneControlQuoteRequest) => void;
}
