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
      description: "We gather the facts and angles your video will be built on." };
  }
  if (!at("ready_for_scripting")) {
    return { key: "approve-research", label: "Review the research", step: 1, tab: "research", kind: "review",
      description: "Read it over and approve to move on." };
  }

  // 2. Script
  if (!at("ready_for_voice")) {
    return { key: "script", label: "Write the script", step: 2, tab: "script-voice", kind: "run", stage: "script",
      description: "The full narration, scene by scene." };
  }

  // 3. Voice
  if (!at("ready_for_image_prompts")) {
    return { key: "voice", label: "Create the voiceover", step: 3, tab: "script-voice", kind: "run", stage: "voice",
      description: "Every scene gets narrated audio.", cost: "≈ $0.50" };
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
    return { key: "prompts", label: "Plan your shots", step: 5, tab: "storyboard-visuals", kind: "run", stage: "prompts",
      description: "We describe every picture the video needs." };
  }

  // 6. Storyboard prompts + grids
  if (!at("ready_for_storyboard_images")) {
    return { key: "storyboard-prompts", label: "Describe your storyboard", step: 6, tab: "storyboard-visuals", kind: "run", stage: "storyboards",
      description: "Scene-by-scene plans for the storyboard." };
  }
  if (!at("ready_for_storyboard_extraction") && i.scenesWithGrids === 0) {
    return { key: "grids", label: "Create your storyboard", step: 6, tab: "storyboard-visuals", kind: "run", stage: "storyboard-images",
      description: "Cheap preview boards — redo any board until the story feels right.", cost: "≈ $0.08 per board" };
  }
  if (!at("ready_for_storyboard_extraction") && i.scenesWithGrids < i.totalScenes) {
    return { key: "finish-grids", label: "Finish your storyboard", step: 6, tab: "storyboard-visuals", kind: "run", stage: "storyboard-images",
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
      return { key: "grids", label: "Create your storyboard", step: 6, tab: "storyboard-visuals", kind: "run", stage: "storyboard-images",
        description: "Cheap preview boards — redo any board until the story feels right.", cost: "≈ $0.08 per board" };
    }
    if (i.totalScenes > 0 && i.scenesWithGrids < i.totalScenes) {
      return { key: "finish-grids", label: "Finish your storyboard", step: 6, tab: "storyboard-visuals", kind: "run", stage: "storyboard-images",
        description: `${i.totalScenes - i.scenesWithGrids} scene(s) still need boards — this only creates the missing ones.`, cost: "≈ $0.08 per board" };
    }
    return { key: "lock", label: "Lock the story", step: 7, tab: "storyboard-visuals", kind: "lock",
      description: "Look at every board below — redo any you don't love. Locking means you're happy and ready for the final pictures." };
  }
  // Extraction normally runs AUTOMATICALLY right after locking — this branch
  // only surfaces as the recovery path when it failed or was interrupted.
  if (finalsMissing || (!at("ready_for_sound_design") && (status === "ready_for_storyboard_extraction" || status === "ready_for_images"))) {
    return { key: "extract", label: "Finish making your pictures", step: 7, tab: "storyboard-visuals", kind: "run", stage: "storyboard-extract",
      description: "Your pictures didn't all finish — this picks up where it left off and only makes the missing ones.", cost: "≈ $0.03 per picture" };
  }

  // 8. Clips
  if (!at("ready_for_video_generation") && (status === "ready_for_sound_design" || status === "ready_for_video_scripts")) {
    return { key: "clip-prompts", label: "Plan your video clips", step: 8, tab: "clips", kind: "run", stage: "video-scripts",
      description: "We write motion directions for every picture." };
  }
  if (status === "ready_for_video_generation") {
    return { key: "clips", label: "Create your video clips", step: 8, tab: "clips", kind: "review",
      description: "This is the big spend — you'll see the exact price and confirm before anything runs.", cost: "$6–12" };
  }

  // 9. Sound + thumbnail
  if (status === "ready_for_sound_effects") {
    return { key: "sound", label: "Add sound effects", step: 9, tab: "sound", kind: "run", stage: "sound-effects",
      description: "Optional polish — you can skip it from the Sound tab.", cost: "< $1" };
  }
  if (status === "ready_for_thumbnail") {
    return { key: "thumbnail", label: "Create your thumbnail", step: 9, tab: "thumbnail", kind: "run", stage: "thumbnail",
      description: "The cover image people click on.", cost: "≈ $0.08" };
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
  return { key: "fallback", label: "Continue your video", step: Math.min(TOTAL_STEPS, 5), tab: "storyboard-visuals", kind: "review",
    description: "Pick up where you left off." };
}

export const NEXT_ACTION_TOTAL_STEPS = TOTAL_STEPS;
