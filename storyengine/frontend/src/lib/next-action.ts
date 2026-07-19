import type { VideoDetail } from "@/lib/api";

/**
 * The grandma-proof brain: from the video's state, compute exactly ONE next
 * action, in plain English, with its cost. The guided banner renders it as
 * the only big filled button on the page — click, wait, click, wait, done.
 *
 * kind:
 *  - "run":    clicking triggers a pipeline stage directly
 *  - "design": clicking triggers character design
 *  - "review": a human decision — clicking navigates to the tab where the
 *              decision lives (approve / confirm-cost flows)
 *  - "lock":   clicking locks the story (confirm built into the banner)
 *  - "celebrate": nothing left to do
 */
export interface NextAction {
  key: string;
  /** Plain-English button label, max ~5 words */
  label: string;
  /** One supporting sentence shown under the button */
  description: string;
  /** Cost note shown beside the label, e.g. "≈ $0.70" — omit when free */
  cost?: string;
  /** Tab id on the video page this action belongs to */
  tab: string;
  kind: "run" | "design" | "review" | "lock" | "celebrate";
  /** Pipeline stage for runPipelineStage() when kind === "run" */
  stage?: string;
  /** 1-based step number for "Step X of 10" */
  step: number;
  /** When set, this step is optional: Skip jumps the video to `to` (a
   * forward status) and `note` says plainly what the video loses. */
  skip?: { to: string; note: string };
}

const TOTAL_STEPS = 10;

export interface NextActionInputs {
  video: VideoDetail & { id: string };
  /** video_characters rows (empty array = none designed yet) */
  characters: { reference_url?: string | null }[];
  charactersApprovedAt: string | null;
  /** Number of scenes that have at least one storyboard grid */
  scenesWithGrids: number;
  /** Total script scenes (0 = script not split yet) */
  totalScenes: number;
  /** Asset rows with a final picture (0 = nothing extracted yet) */
  extractedCount?: number;
  /** Total asset rows (picture slots) */
  totalSegments?: number;
  /** Asset rows that already have a motion clip */
  clipsDone?: number;
  /** Asset rows that can be animated (have a final picture) */
  clipsTotal?: number;
  /** Distinct scenes that already have pictures (coverage flow: missing scenes have no rows) */
  scenesWithPictures?: number;
  /** Live per-clip price by model — GET /api/pipeline/actions/{id}'s
   * `prices.clip` map, read reactively on the SAME render it arrives.
   * S9-2/C19a: without this, cost text below fell back to clipCost()'s
   * CLIP_COST_PER_MODEL mutable cache, which a later useEffect populates one
   * render too late (the exact anti-pattern ScenesWorkspaceTab's own
   * `priceForModel` already works around — see its comment). Omit/pass null
   * to keep the old cache+fallback behavior (other getNextAction callers,
   * if any get added, aren't forced onto this). */
  clipPriceByModel?: Record<string, number> | null;
}

/** Per-clip price for `model`, preferring the caller's live price map (this
 * render's fetched data) over the mutable CLIP_COST_PER_MODEL cache that
 * clipCost() reads — see NextActionInputs.clipPriceByModel above. */
function resolveClipCost(
  model: string | null | undefined,
  count: number,
  liveByModel: Record<string, number> | null | undefined,
): number {
  const live = liveByModel?.[model || "grok-imagine"];
  if (live != null) return live * count;
  return clipCost(model, count);
}

/** Per-clip price by model. NOT hardcoded — the single source of truth is
 * the backend (shared.channel_profile.CLIP_PRICE_BY_MODEL), reached two
 * ways: GET /api/models' `cost_per_clip` field (ScenesWorkspaceTab syncs
 * this on load) and GET /api/pipeline/actions/{id}'s `prices.clip` (the
 * video page syncs this). Both write into this same runtime cache — see
 * storyengine-wiring-fix-checklist.md §0.3c: the old version of this file
 * hardcoded the same 4 numbers by hand, which could silently drift from
 * the backend's actual registry prices. Starts empty; CLIP_COST_FALLBACK
 * covers the brief gap before either sync has run once. */
export const CLIP_COST_PER_MODEL: Record<string, number> = {};

// Shown for a beat before the backend price loads — deliberately the
// priciest CURRENTLY wired model (Veo 3.1 Fast / Seedance 2.0), so a
// cost label never underquotes during that gap. Real prices always win
// once either sync above has run.
const CLIP_COST_FALLBACK = 0.30;

export function clipCost(model: string | null | undefined, count: number): number {
  const price = CLIP_COST_PER_MODEL[model || "grok-imagine"];
  return (price ?? CLIP_COST_FALLBACK) * count;
}

export function getNextAction(i: NextActionInputs): NextAction {
  const v = i.video;
  const status = v.status || "idea_logged";
  const order = [
    "idea_logged", "approved", "researching", "ready_for_scripting", "scripting",
    "needs_script_review", "ready_for_voice", "voice", "ready_for_image_prompts",
    "ready_for_storyboards", "ready_for_storyboard_images", "ready_for_storyboard_extraction",
    "ready_for_images", "ready_for_sound_design", "ready_for_sound_effects",
    "ready_for_video_scripts", "ready_for_video_generation", "ready_for_thumbnail",
    "ready_to_render", "rendering", "rendered", "uploaded_draft", "uploaded", "published", "done",
  ];
  const at = (s: string) => order.indexOf(status) >= order.indexOf(s);

  // 1. Research
  if (!at("ready_for_scripting") && !v.research_payload) {
    return { key: "research", label: "Research your topic", step: 1, tab: "research", kind: "run", stage: "research",
      description: "We gather the facts and angles your video will be built on.",
      skip: { to: "ready_for_scripting", note: "The script writes itself from the title alone — no research brief." } };
  }
  if (!at("ready_for_scripting")) {
    return { key: "approve-research", label: "Review the research", step: 1, tab: "research", kind: "review",
      description: "Read it over and approve to move on.",
      skip: { to: "ready_for_scripting", note: "Move on without reviewing the research." } };
  }

  // 2. Script
  if (!at("ready_for_voice")) {
    return { key: "script", label: "Write the script", step: 2, tab: "script-voice", kind: "run", stage: "script",
      description: "The full narration, scene by scene." };
  }

  // 3. Voice
  if (!at("ready_for_image_prompts")) {
    return { key: "voice", label: "Create the voiceover", step: 3, tab: "script-voice", kind: "run", stage: "voice",
      description: "Every scene gets narrated audio.", cost: "≈ $0.50",
      skip: { to: "ready_for_image_prompts", note: "No narrator track — your clips' own audio carries the video." } };
  }

  // 4. Characters (after voice, before any visuals)
  const hasCast = i.characters.length > 0;
  const castComplete = hasCast && i.characters.every((c) => c.reference_url);
  if (!at("ready_for_sound_design")) {
    if (!hasCast) {
      return { key: "design-characters", label: "Create your characters", step: 4, tab: "characters", kind: "design",
        description: "We read the script, find the cast, and draw each one so they look the same in every scene.", cost: "≈ $0.03 each" };
    }
    if (!castComplete) {
      return { key: "finish-characters", label: "Finish character pictures", step: 4, tab: "characters", kind: "review",
        description: "Some characters still need an image — regenerate or upload one." };
    }
    if (!i.charactersApprovedAt) {
      return { key: "approve-cast", label: "Approve your characters", step: 4, tab: "characters", kind: "review",
        description: "Happy with how everyone looks? Approve to continue." };
    }
  }

  // 5. Shot plan (image prompts)
  if (!at("ready_for_storyboards")) {
    return { key: "prompts", label: "Plan your shots", step: 5, tab: "scenes", kind: "run", stage: "prompts",
      description: "We describe every picture the video needs." };
  }

  // 6. Storyboard prompts + grids
  if (!at("ready_for_storyboard_images")) {
    return { key: "storyboard-prompts", label: "Describe your storyboard", step: 6, tab: "scenes", kind: "run", stage: "storyboards",
      description: "Scene-by-scene plans for the storyboard." };
  }
  if (!at("ready_for_storyboard_extraction") && i.scenesWithGrids === 0) {
    return { key: "grids", label: "Create your storyboard", step: 6, tab: "scenes", kind: "run", stage: "storyboard-images",
      description: "Cheap preview boards — redo any board until the story feels right.", cost: "≈ $0.08 per board" };
  }
  if (!at("ready_for_storyboard_extraction") && i.scenesWithGrids < i.totalScenes) {
    return { key: "finish-grids", label: "Finish your storyboard", step: 6, tab: "scenes", kind: "run", stage: "storyboard-images",
      description: `${i.totalScenes - i.scenesWithGrids} scene(s) still need boards — this only creates the missing ones.`, cost: "≈ $0.08 per board" };
  }

  // 7. Lock + finals. finalsMissing catches videos whose status was skipped
  // ahead (e.g. via Skip Stage) without final pictures — clips can't run on
  // nothing, so route back here no matter how far the status string got.
  const finalsMissing = (i.totalSegments ?? 0) > 0 && (i.extractedCount ?? 0) === 0;
  if (!v.story_locked_at && (!at("ready_for_sound_design") || finalsMissing)) {
    // You can't lock a story you haven't seen: if boards were skipped past or
    // deleted, route back to creating them — never offer a zero-board lock.
    if (i.scenesWithGrids === 0) {
      return { key: "grids", label: "Create your storyboard", step: 6, tab: "scenes", kind: "run", stage: "storyboard-images",
        description: "Cheap preview boards — redo any board until the story feels right.", cost: "≈ $0.08 per board" };
    }
    if (i.totalScenes > 0 && i.scenesWithGrids < i.totalScenes) {
      return { key: "finish-grids", label: "Finish your storyboard", step: 6, tab: "scenes", kind: "run", stage: "storyboard-images",
        description: `${i.totalScenes - i.scenesWithGrids} scene(s) still need boards — this only creates the missing ones.`, cost: "≈ $0.08 per board" };
    }
    return { key: "lock", label: "Lock the story", step: 7, tab: "scenes", kind: "lock",
      description: "Look at every board below — redo any you don't love. Locking means you're happy and ready for the final pictures." };
  }
  // Extraction normally runs AUTOMATICALLY right after locking — this branch
  // only surfaces as the recovery path when it failed or was interrupted.
  // A video whose finals are COMPLETE but whose status string lags behind
  // (e.g. ready_for_images with 86/86 extracted) falls through to clips.
  const extractionIncomplete = (i.totalSegments ?? 0) > 0 && (i.extractedCount ?? 0) < (i.totalSegments ?? 0);
  if (finalsMissing || (!at("ready_for_sound_design") && extractionIncomplete && (status === "ready_for_storyboard_extraction" || status === "ready_for_images"))) {
    return { key: "extract", label: "Finish making your pictures", step: 7, tab: "scenes", kind: "run", stage: "storyboard-extract",
      description: "Your pictures didn't all finish — this picks up where it left off and only makes the missing ones.", cost: "≈ $0.03 per picture" };
  }

  // 8. Clips — the trust ladder. Motion prompts are silent plumbing (the
  // clips tab auto-runs them on arrival); the banner walks the three rungs:
  // taste-test scene 1 → animate the rest → done.
  const inClipsRegion = ["ready_for_storyboard_extraction", "ready_for_images", "ready_for_sound_design", "ready_for_video_scripts", "ready_for_video_generation"].includes(status);
  if (inClipsRegion) {
    // Coverage flow: a scene with no pictures has NO asset rows, so a status that
    // jumped ahead can look "done" while scenes are still empty. Before offering
    // to animate, make sure every scene actually has its pictures.
    if (i.totalScenes > 0 && (i.scenesWithPictures ?? i.totalScenes) < i.totalScenes) {
      const left = i.totalScenes - (i.scenesWithPictures ?? 0);
      return { key: "pictures", label: "Create your pictures", step: 7, tab: "scenes", kind: "run", stage: "coverage-images",
        description: `${left} scene${left === 1 ? "" : "s"} still need${left === 1 ? "s" : ""} pictures — this draws the missing ones.`, cost: "≈ $0.08 per picture" };
    }
    const clipsTotal = i.clipsTotal ?? 0;
    const clipsDone = i.clipsDone ?? 0;
    const perClip = resolveClipCost(v.video_model, 1, i.clipPriceByModel);
    if (clipsTotal > 0 && clipsDone === 0) {
      return { key: "clips-taste", label: "Animate scene 1", step: 8, tab: "scenes", kind: "review",
        description: "Tap any picture on the Clips tab to bring it to life — start with scene 1 and make sure the motion feels right before animating everything.",
        cost: `≈ $${perClip.toFixed(2)} per clip`,
        skip: { to: "ready_for_thumbnail", note: "No motion clips — the video uses your still pictures with gentle zoom." } };
    }
    if (clipsTotal > 0 && clipsDone < clipsTotal) {
      const left = clipsTotal - clipsDone;
      return { key: "clips-rest", label: "Animate the rest", step: 8, tab: "scenes", kind: "review",
        description: `${left} picture${left === 1 ? "" : "s"} still need${left === 1 ? "s" : ""} motion. Happy with how it moves? Finish the set — you'll see the exact price and confirm first.`,
        cost: `≈ $${resolveClipCost(v.video_model, left, i.clipPriceByModel).toFixed(2)}`,
        skip: { to: "ready_for_thumbnail", note: "Keep the clips you have — pictures without one use gentle zoom." } };
    }
    if (clipsTotal > 0) {
      return { key: "thumbnail", label: "Create your thumbnail", step: 9, tab: "thumbnail", kind: "run", stage: "thumbnail",
        description: "Every picture is animated. Next: the cover image people click on.", cost: "≈ $0.08",
        skip: { to: "ready_to_render", note: "YouTube picks a frame automatically — you can add one later." } };
    }
    // No animatable pictures at all — recovery path back to finals.
    return { key: "extract", label: "Finish making your pictures", step: 7, tab: "scenes", kind: "run", stage: "storyboard-extract",
      description: "Clips animate your final pictures, but none exist yet — this creates them.", cost: "≈ $0.03 per picture" };
  }

  // 9. Sound + thumbnail
  if (status === "ready_for_sound_effects") {
    return { key: "sound", label: "Add sound effects", step: 9, tab: "sound", kind: "run", stage: "sound-effects",
      description: "Optional polish for extra depth.", cost: "< $1",
      skip: { to: "ready_for_thumbnail", note: "No extra sound effects." } };
  }
  if (status === "ready_for_thumbnail") {
    return { key: "thumbnail", label: "Create your thumbnail", step: 9, tab: "thumbnail", kind: "run", stage: "thumbnail",
      description: "The cover image people click on.", cost: "≈ $0.08",
      skip: { to: "ready_to_render", note: "YouTube picks a frame automatically — you can add one later." } };
  }

  // 10. Render + upload
  if (status === "ready_to_render" || status === "rendering") {
    return { key: "render", label: "Build the final video", step: 10, tab: "render", kind: "run", stage: "render",
      description: "Everything gets stitched together — takes 10–20 minutes." };
  }
  if (status === "rendered") {
    return { key: "upload", label: "Send to YouTube", step: 10, tab: "render", kind: "review",
      description: "Uploads as a private draft — nothing goes public without you." };
  }
  if (["uploaded_draft", "uploaded", "published", "done"].includes(status)) {
    return { key: "done", label: "See how it's doing", step: 10, tab: "performance", kind: "celebrate",
      description: "Your video is made. Watch the numbers roll in." };
  }

  // Fallback — shouldn't happen, but never strand the user
  return { key: "fallback", label: "Continue your video", step: Math.min(TOTAL_STEPS, 5), tab: "scenes", kind: "review",
    description: "Pick up where you left off." };
}

export const NEXT_ACTION_TOTAL_STEPS = TOTAL_STEPS;
