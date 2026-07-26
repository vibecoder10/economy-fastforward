import {fetchApi} from "./api";

export const SCENE_CONTROL_LOCK_KINDS = [
  "story",
  "dialogue",
  "style",
  "cast",
  "environments",
  "techniques",
] as const;
export type SceneControlLockKind =
  (typeof SCENE_CONTROL_LOCK_KINDS)[number];

export const SCENE_CONTROL_API_STATES = [
  "draft",
  "plan_approved",
  "storyboard_approved",
  "imagery_approved",
  "animation_approved",
  "audio_approved",
  "assembled",
  "accepted",
] as const;
export type SceneControlApiState =
  (typeof SCENE_CONTROL_API_STATES)[number];

export type SceneControlChangedGate =
  | "plan"
  | "storyboard"
  | "imagery"
  | "animation"
  | "audio"
  | "assembly";

export type SceneControlOperationType =
  | "storyboard_images"
  | "final_imagery"
  | "animate_shot"
  | "dialogue_audio"
  | "assemble_scene";

export interface SceneControlApiDialogueTurn {
  speaker_id: string;
  text: string;
  performance_intent: string;
  timing: string;
}

export interface SceneControlApiSceneContract {
  scene_number: number;
  purpose: string;
  target_duration_frames: number;
  story_time: string;
  opening_state: string;
  state_change: string;
  character_ids: string[];
  environment_id: string;
  active_prop_ids: string[];
  continuity_in: string;
  continuity_out: string;
  dialogue_turns: SceneControlApiDialogueTurn[];
  silent_action_beats: string[];
  shot_ids: string[];
}

export interface SceneControlApiStoryState {
  story_facts: string[];
  character_positions: Record<string, string>;
  prop_states: Record<string, string>;
  emotional_state: Record<string, string>;
}

export interface SceneControlApiSpokenLine {
  speaker_id: string;
  kind: "dialogue" | "narration";
  text: string;
  language: string;
  delivery: string;
  addressee_id?: string | null;
}

export interface SceneControlApiShotContract {
  shot_key: string;
  section_id: string;
  duration_frames: number;
  technique:
    | "poco_dialogue"
    | "dvsu_documentary"
    | "power_doctrine_exposition"
    | "cinematic_action";
  performance_mode: "dialogue" | "exposition" | "silent_action";
  narrative_purpose: string;
  caused_by: string[];
  progression_kinds: Array<
    "story" | "action" | "information" | "emotion" | "spatial"
  >;
  story_value: string;
  opening_state: SceneControlApiStoryState;
  action_beats: string[];
  closing_state: SceneControlApiStoryState;
  transition_from_previous:
    | "opening"
    | "continuous"
    | "time_cut"
    | "location_cut"
    | "montage"
    | "memory";
  continuity_bridge?: string | null;
  environment_id: string;
  character_ids: string[];
  active_prop_ids: string[];
  screen_direction: string;
  shot_size: string;
  camera_move: string;
  spoken_lines: SceneControlApiSpokenLine[];
  storyboard_composition: string;
  final_picture_intent: string;
  motion_intent: string;
  ambient_sound: string;
  score_intent: string;
  sfx_cues: string[];
  caption_mode: "dialogue" | "narration" | "none";
}

export interface SceneControlApiShot {
  shot_id: string;
  order_index: number;
  duration_frames: number;
  shot_contract: SceneControlApiShotContract;
}

export interface SceneControlApiArtifactShot {
  shot_id: string;
  kind: "video";
  url: string;
  start_frame: number;
  end_frame: number;
  sha256: string;
}

export interface SceneControlApiArtifactAssembly {
  kind: "video";
  url: string;
  duration_frames: number;
  sha256: string;
}

export interface SceneControlApiArtifactManifest {
  version: 1;
  synthetic: true;
  shots: SceneControlApiArtifactShot[];
  assembly: SceneControlApiArtifactAssembly;
}

export interface SceneControlApiFilmLock {
  lock_kind: SceneControlLockKind;
  revision: number;
  payload: unknown;
  content_hash: string;
  approval_hash: string;
  synthetic: boolean;
  approved_at: string;
}

export interface SceneControlApiLockSet {
  lock_version: number;
  complete: boolean;
  missing: SceneControlLockKind[];
  locks: SceneControlApiFilmLock[];
  film_lock_set_hash: string;
}

export interface SceneControlApiScene {
  scene_id: string;
  scene_number: number;
  scene_contract: SceneControlApiSceneContract;
  revision: number;
  revision_hash: string;
  film_lock_set_hash: string;
  artifact_hashes: Record<string, string>;
  state: SceneControlApiState;
  accepted_revision_hash: string | null;
  access: "accepted" | "current" | "locked";
  synthetic: boolean;
  shots: SceneControlApiShot[];
  artifact_manifest:
    | SceneControlApiArtifactManifest
    | Record<string, never>;
}

export interface SceneControlApiSnapshot {
  control_version: number;
  video_id: string;
  director_contract_id: string;
  director_contract_hash: string;
  film_locks: SceneControlApiLockSet;
  current_scene_id: string | null;
  scenes: SceneControlApiScene[];
}

export interface SceneControlApiQuote {
  quote_version: number;
  video_id: string;
  scene_id: string;
  scene_number: number;
  shot_ids: string[];
  scene_revision_hash: string;
  operation_type: SceneControlOperationType;
  provider_operation:
    | "storyboard_image"
    | "final_picture"
    | "animation_clip"
    | "voice_line"
    | "remotion_assembly";
  deterministic: boolean;
  initial_calls: number;
  max_repair_calls: 0;
  unit_max_cents: number;
  exact_incremental_max_cents: number;
  prior_completed_cumulative_spend_cents: number;
  new_exact_cumulative_ceiling_cents: number;
  included_media: string[];
  explicitly_unapproved: string[];
  approval_status: "not_approved";
  approval_card_hash: string;
}

export interface SceneControlLockMutation {
  id: string;
  lock_kind: SceneControlLockKind;
  revision: number;
  content_hash: string;
  approval_hash: string;
  film_lock_set_hash?: string;
  film_locks_complete?: boolean;
  created: boolean;
}

export interface SceneControlSceneMutation {
  scene_id: string;
  scene_number: number;
  state: "draft";
  revision: number;
  revision_hash: string;
  film_lock_set_hash: string;
  created: boolean;
  synthetic: boolean;
}

export interface SceneControlRevisionMutation {
  scene_id: string;
  state: SceneControlApiState;
  revision: number;
  revision_hash: string;
  invalidated_states: SceneControlApiState[];
}

export interface SceneControlTransitionMutation {
  scene_id: string;
  scene_number: number;
  state: Exclude<SceneControlApiState, "draft">;
  revision_hash: string;
  event_hash: string;
  next_scene_unlocked: boolean;
}

const basePath = (videoId: string): string =>
  `/api/custom-film/${encodeURIComponent(videoId)}/scene-control`;

export const getSceneControl = (videoId: string) =>
  fetchApi<SceneControlApiSnapshot>(basePath(videoId));

export const putSceneControlFilmLock = (
  videoId: string,
  lockKind: SceneControlLockKind,
  payload: unknown,
) =>
  fetchApi<SceneControlLockMutation>(
    `${basePath(videoId)}/film-locks/${lockKind}`,
    {
      method: "PUT",
      body: JSON.stringify({payload}),
    },
  );

export const createSceneControlScene = (
  videoId: string,
  sceneContract: SceneControlApiSceneContract,
) =>
  fetchApi<SceneControlSceneMutation>(`${basePath(videoId)}/scenes`, {
    method: "POST",
    body: JSON.stringify({scene_contract: sceneContract}),
  });

export const reviseSceneControlScene = (
  videoId: string,
  sceneId: string,
  body: {
    expected_revision_hash: string;
    changed_gate: SceneControlChangedGate;
    scene_contract?: SceneControlApiSceneContract | null;
    artifact_hash?: string | null;
  },
) =>
  fetchApi<SceneControlRevisionMutation>(
    `${basePath(videoId)}/scenes/${encodeURIComponent(sceneId)}/revision`,
    {method: "PUT", body: JSON.stringify(body)},
  );

export const transitionSceneControlScene = (
  videoId: string,
  sceneId: string,
  body: {
    expected_revision_hash: string;
    target_state: Exclude<SceneControlApiState, "draft">;
    evidence_hash: string;
  },
) =>
  fetchApi<SceneControlTransitionMutation>(
    `${basePath(videoId)}/scenes/${encodeURIComponent(sceneId)}/transition`,
    {method: "POST", body: JSON.stringify(body)},
  );

export const quoteSceneControlOperation = (
  videoId: string,
  sceneId: string,
  body: {
    expected_revision_hash: string;
    operation_type: SceneControlOperationType;
    shot_id?: string | null;
  },
) =>
  fetchApi<SceneControlApiQuote>(
    `${basePath(videoId)}/scenes/${encodeURIComponent(sceneId)}/operations/quote`,
    {method: "POST", body: JSON.stringify(body)},
  );
