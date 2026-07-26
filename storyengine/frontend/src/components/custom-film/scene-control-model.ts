import {
  SCENE_CONTROL_STATES,
  type SceneControlScene,
  type SceneControlSnapshot,
  type SceneControlState,
} from "./scene-control-types";

const STATE_LABELS: Record<SceneControlState, string> = {
  draft: "Draft",
  plan_approved: "Plan approved",
  storyboard_approved: "Storyboard approved",
  imagery_approved: "Imagery approved",
  animation_approved: "Animation approved",
  audio_approved: "Audio approved",
  assembled: "Assembled",
  accepted: "Accepted",
};

export function sceneStateLabel(state: SceneControlState): string {
  return STATE_LABELS[state];
}

export function nextSceneState(
  state: SceneControlState,
): SceneControlState | null {
  const index = SCENE_CONTROL_STATES.indexOf(state);
  return index < SCENE_CONTROL_STATES.length - 1
    ? SCENE_CONTROL_STATES[index + 1]
    : null;
}

export function transitionLabel(
  from: SceneControlState,
  to: SceneControlState,
): string {
  if (from === "draft" && to === "plan_approved") {
    return "Approve scene plan — no generation";
  }
  if (from === "audio_approved" && to === "assembled") {
    return "Assemble in Remotion — deterministic";
  }
  if (from === "assembled" && to === "accepted") {
    return "Accept completed scene and unlock next";
  }
  return `Approve ${sceneStateLabel(to).toLowerCase()}`;
}

export function previousReviewState(
  state: SceneControlState,
): SceneControlState {
  const index = SCENE_CONTROL_STATES.indexOf(state);
  return SCENE_CONTROL_STATES[Math.max(0, index - 1)];
}

export function currentScene(snapshot: SceneControlSnapshot): SceneControlScene {
  const scene = snapshot.scenes.find(
    ({id}) => id === snapshot.current_scene_id,
  );
  if (!scene) throw new Error("Scene Control current scene is missing");
  return scene;
}

export function validateSceneControlSnapshot(
  snapshot: SceneControlSnapshot,
): SceneControlSnapshot {
  if (!snapshot.film_id || !snapshot.title || snapshot.scenes.length === 0) {
    throw new Error("Scene Control snapshot identity is incomplete");
  }
  const ids = new Set<string>();
  let currentCount = 0;
  for (const [index, scene] of snapshot.scenes.entries()) {
    if (
      !scene.id ||
      ids.has(scene.id) ||
      scene.number !== index + 1 ||
      !scene.revision_hash ||
      scene.shots.length === 0
    ) {
      throw new Error("Scene Control scene order or identity is invalid");
    }
    ids.add(scene.id);
    if (scene.rail_status === "current") currentCount += 1;
    const shotOrders = scene.shots.map(({order}) => order);
    if (shotOrders.some((order, shotIndex) => order !== shotIndex + 1)) {
      throw new Error("Scene Control shot order is invalid");
    }
  }
  if (
    !ids.has(snapshot.current_scene_id) ||
    currentCount !== 1 ||
    currentScene(snapshot).rail_status !== "current"
  ) {
    throw new Error("Scene Control must expose exactly one current scene");
  }
  return snapshot;
}

export function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}
