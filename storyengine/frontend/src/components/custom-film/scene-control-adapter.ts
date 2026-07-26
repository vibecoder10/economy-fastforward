import type {
  SceneControlApiFilmLock,
  SceneControlApiArtifactManifest,
  SceneControlApiQuote,
  SceneControlApiScene,
  SceneControlApiShot,
  SceneControlApiSnapshot,
  SceneControlLockKind,
} from "@/lib/scene-control-api";
import {SCENE_CONTROL_LOCK_KINDS} from "@/lib/scene-control-api";
import type {
  SceneControlArtifact,
  SceneControlOperationQuote,
  SceneControlScene,
  SceneControlShot,
  SceneControlSnapshot,
  SceneControlState,
} from "./scene-control-types";

const LOCK_LABELS: Record<SceneControlLockKind, string> = {
  story: "Story throughline",
  dialogue: "Dialogue ownership",
  style: "Visual grammar",
  cast: "Recurring cast",
  environments: "Recurring environment",
  techniques: "Technique boundaries",
};

const EVIDENCE_KEYS: Partial<Record<SceneControlState, string>> = {
  storyboard_approved: "storyboard",
  imagery_approved: "imagery",
  animation_approved: "animation",
  audio_approved: "audio",
  assembled: "assembly",
  accepted: "assembly",
};

const ARTIFACTS: Array<{
  key: string;
  label: string;
  kind: SceneControlArtifact["kind"];
  deterministic: boolean;
}> = [
  {key: "storyboard", label: "Storyboard", kind: "storyboard", deterministic: false},
  {key: "imagery", label: "Final image", kind: "image", deterministic: false},
  {key: "animation", label: "Motion", kind: "animation", deterministic: false},
  {key: "audio", label: "Dialogue audio", kind: "audio", deterministic: false},
  {key: "assembly", label: "Remotion assembly", kind: "assembly", deterministic: true},
];

const SHA256 = /^[0-9a-f]{64}$/;
const PROOF_VIDEO_URL = /^\/scene-control-proof\/[A-Za-z0-9._-]+\.mp4$/;
const ASSEMBLY_URL =
  "/scene-control-proof/director-scene-control-proof.mp4";

const words = (value: string): string =>
  value
    .replace(/^scene_control_(?:character|environment)_/, "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const stateText = (
  state: SceneControlApiShot["shot_contract"]["opening_state"],
): string => {
  const parts = [
    ...state.story_facts,
    ...Object.entries(state.character_positions).map(
      ([name, position]) => `${words(name)}: ${position}`,
    ),
    ...Object.entries(state.prop_states).map(
      ([name, value]) => `${words(name)}: ${value}`,
    ),
    ...Object.entries(state.emotional_state).map(
      ([name, value]) => `${words(name)}: ${value}`,
    ),
  ];
  return parts.join(" · ");
};

const dialogueTiming = (
  delivery: string,
  fallbackStart: number,
  fallbackEnd: number,
): {intent: string; start: number; end: number; label?: string} => {
  const match = delivery.match(/^(.*?)(?:;\s*frames\s+(\d+)-(\d+))$/i);
  if (!match) {
    return {intent: delivery, start: fallbackStart, end: fallbackEnd};
  }
  return {
    intent: match[1].trim(),
    start: Number(match[2]) / 24,
    end: Number(match[3]) / 24,
    label: `frames ${match[2]}–${match[3]}`,
  };
};

const summarizePayload = (payload: unknown): string => {
  if (typeof payload === "string") return payload;
  if (!payload || typeof payload !== "object") return "Approved server payload";
  const record = payload as Record<string, unknown>;
  for (const key of ["summary", "description", "logline", "rule", "title"]) {
    if (typeof record[key] === "string") return record[key] as string;
  }
  const firstString = Object.values(record).find(
    (value): value is string => typeof value === "string" && value.length > 0,
  );
  return firstString ?? `${Object.keys(record).length} canonical fields`;
};

const adaptArtifacts = (
  scene: SceneControlApiScene,
  shotId: string,
): SceneControlArtifact[] =>
  ARTIFACTS.map(({key, label, kind, deterministic}) => ({
    id: `${scene.scene_id}-${shotId}-${key}`,
    label,
    kind,
    deterministic,
    status: scene.artifact_hashes[key] ? "approved" : "missing",
    detail: scene.artifact_hashes[key]
      ? `Canonical evidence ${scene.artifact_hashes[key].slice(0, 12)}…`
      : deterministic
        ? "No deterministic artifact recorded"
        : "No paid artifact recorded",
  }));

const validatedArtifactManifest = (
  scene: SceneControlApiScene,
): SceneControlApiArtifactManifest | null => {
  const raw = scene.artifact_manifest;
  if (!raw || Object.keys(raw).length === 0) return null;
  const manifest = raw as SceneControlApiArtifactManifest;
  const orderedShots = [...scene.shots].sort(
    (left, right) => left.order_index - right.order_index,
  );
  let startFrame = 0;
  const validShots =
    Array.isArray(manifest.shots) &&
    manifest.shots.length === orderedShots.length &&
    manifest.shots.every((artifact, index) => {
      const shot = orderedShots[index];
      const expectedEnd = startFrame + shot.duration_frames - 1;
      const valid =
        artifact.shot_id === shot.shot_id &&
        artifact.kind === "video" &&
        PROOF_VIDEO_URL.test(artifact.url) &&
        !artifact.url.includes("..") &&
        SHA256.test(artifact.sha256) &&
        artifact.start_frame === startFrame &&
        artifact.end_frame === expectedEnd;
      startFrame = expectedEnd + 1;
      return valid;
    });
  const assembly = manifest.assembly;
  if (
    !scene.synthetic ||
    manifest.version !== 1 ||
    manifest.synthetic !== true ||
    !validShots ||
    !assembly ||
    assembly.kind !== "video" ||
    assembly.url !== ASSEMBLY_URL ||
    !PROOF_VIDEO_URL.test(assembly.url) ||
    !SHA256.test(assembly.sha256) ||
    assembly.duration_frames !== scene.scene_contract.target_duration_frames ||
    startFrame !== scene.scene_contract.target_duration_frames
  ) {
    throw new Error(
      `Scene ${scene.scene_number} artifact manifest is malformed or unsafe`,
    );
  }
  return manifest;
};

const canonicalShots = (
  scene: SceneControlApiScene,
  manifest: SceneControlApiArtifactManifest | null,
): SceneControlShot[] => {
  if (!scene.shots?.length) {
    throw new Error(
      `Scene ${scene.scene_number} is missing its canonical shot read model`,
    );
  }
  const ordered = [...scene.shots].sort(
    (left, right) => left.order_index - right.order_index,
  );
  const observedIds = ordered.map(({shot_id}) => shot_id);
  const expectedIds = scene.scene_contract.shot_ids;
  if (
    observedIds.length !== expectedIds.length ||
    observedIds.some((shotId, index) => shotId !== expectedIds[index]) ||
    new Set(observedIds).size !== observedIds.length ||
    ordered.some(
      ({duration_frames, shot_contract}) =>
        duration_frames <= 0 ||
        duration_frames !== shot_contract.duration_frames,
    ) ||
    ordered.reduce((sum, {duration_frames}) => sum + duration_frames, 0) !==
      scene.scene_contract.target_duration_frames
  ) {
    throw new Error(
      `Scene ${scene.scene_number} canonical shot order or duration is invalid`,
    );
  }
  let elapsedFrames = 0;
  return ordered
    .map((row, index) => {
      const contract = row.shot_contract;
      const startSeconds = elapsedFrames / 24;
      elapsedFrames += row.duration_frames;
      const endSeconds = elapsedFrames / 24;
      return {
        id: row.shot_id,
        shot_key: contract.shot_key,
        order: index + 1,
        title: words(contract.shot_key),
        duration_seconds: Number((row.duration_frames / 24).toFixed(2)),
        narrative_function: contract.narrative_purpose,
        advancement: contract.story_value,
        opening_state: stateText(contract.opening_state),
        closing_state: stateText(contract.closing_state),
        character_action: contract.action_beats.join(" · "),
        camera_action: `${contract.shot_size} · ${contract.camera_move} · ${contract.screen_direction}`,
        transition: words(contract.transition_from_previous),
        continuity_inputs: [
          ...contract.caused_by,
          ...(contract.continuity_bridge ? [contract.continuity_bridge] : []),
          ...contract.opening_state.story_facts,
        ],
        continuity_outputs: contract.closing_state.story_facts,
        performance_mode: contract.performance_mode,
        dialogue: contract.spoken_lines.map((line, lineIndex) => {
          const timing = dialogueTiming(line.delivery, startSeconds, endSeconds);
          return {
            id: `${row.shot_id}-line-${lineIndex + 1}`,
            speaker_id: line.speaker_id,
            speaker_label: words(line.speaker_id),
            text: line.text,
            performance_intent: timing.intent,
            start_seconds: timing.start,
            end_seconds: timing.end,
            timing_label: timing.label,
          };
        }),
        artifacts: adaptArtifacts(scene, row.shot_id),
        preview: manifest
          ? {
              url: manifest.shots[index].url,
              start_frame: manifest.shots[index].start_frame,
              end_frame: manifest.shots[index].end_frame,
              sha256: manifest.shots[index].sha256,
            }
          : undefined,
      };
    });
};

const transitionEvidence = (
  scene: SceneControlApiScene,
): SceneControlScene["transition_evidence_hashes"] => {
  const evidence: SceneControlScene["transition_evidence_hashes"] = {
    plan_approved: scene.revision_hash,
  };
  for (const [state, key] of Object.entries(EVIDENCE_KEYS)) {
    const hash =
      scene.artifact_hashes[key] ??
      (state === "accepted" ? scene.accepted_revision_hash : null);
    if (hash) evidence[state as SceneControlState] = hash;
  }
  return evidence;
};

const adaptScene = (scene: SceneControlApiScene): SceneControlScene => {
  const manifest = validatedArtifactManifest(scene);
  return {
    id: scene.scene_id,
    number: scene.scene_number,
    title:
      scene.synthetic && scene.scene_number === 1
        ? "The internal signal"
        : `Scene ${scene.scene_number}`,
    purpose: scene.scene_contract.purpose,
    target_duration_seconds: Number(
      (scene.scene_contract.target_duration_frames / 24).toFixed(2),
    ),
    story_time: scene.scene_contract.story_time,
    state: scene.state,
    rail_status: scene.access,
    revision_hash: scene.revision_hash,
    transition_evidence_hashes: transitionEvidence(scene),
    environment_label: words(scene.scene_contract.environment_id),
    character_labels: scene.scene_contract.character_ids.map(words),
    shots: canonicalShots(scene, manifest),
    assembly_preview: manifest
      ? {
          url: manifest.assembly.url,
          duration_frames: manifest.assembly.duration_frames,
          sha256: manifest.assembly.sha256,
          current_for_acceptance:
            (scene.state === "assembled" || scene.state === "accepted") &&
            scene.artifact_hashes.assembly === manifest.assembly.sha256,
        }
      : undefined,
  };
};

const adaptLock = (
  kind: SceneControlLockKind,
  lock: SceneControlApiFilmLock | undefined,
) => ({
  id: kind,
  label: LOCK_LABELS[kind],
  summary: lock
    ? summarizePayload(lock.payload)
    : "Missing. Establish this film foundation before creating or advancing scenes.",
  status: lock ? ("locked" as const) : ("draft" as const),
  revision_hash: lock?.content_hash ?? "",
  reviewable: true,
  payload: lock?.payload ?? {},
});

export const adaptSceneControlQuote = (
  quote: SceneControlApiQuote,
): SceneControlOperationQuote => ({...quote});

export function adaptSceneControlSnapshot(
  snapshot: SceneControlApiSnapshot,
  quote?: SceneControlApiQuote,
): SceneControlSnapshot | null {
  if (!snapshot.current_scene_id || snapshot.scenes.length === 0) return null;
  const lockMap = new Map(
    snapshot.film_locks.locks.map((lock) => [lock.lock_kind, lock]),
  );
  return {
    film_id: snapshot.video_id,
    title: "Custom Film Scene Control",
    film_revision_hash: snapshot.director_contract_hash,
    film_locks_approved: snapshot.film_locks.complete,
    film_locks: SCENE_CONTROL_LOCK_KINDS.map((kind) =>
      adaptLock(kind, lockMap.get(kind)),
    ),
    scenes: snapshot.scenes.map(adaptScene),
    current_scene_id: snapshot.current_scene_id,
    next_operation: quote ? adaptSceneControlQuote(quote) : undefined,
  };
}
