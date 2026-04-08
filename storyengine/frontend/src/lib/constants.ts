export const PIPELINE_STAGES = [
  { key: "idea_logged", label: "Idea", color: "slate", dot: 1 },
  { key: "ready_for_scripting", label: "Script", color: "teal", dot: 2 },
  { key: "ready_for_voice", label: "Voice", color: "teal", dot: 3 },
  { key: "ready_for_storyboards", label: "Storyboard", color: "teal", dot: 4 },
  { key: "ready_for_images", label: "Images", color: "teal", dot: 5 },
  { key: "ready_for_thumbnail", label: "Thumbnail", color: "teal", dot: 6 },
  { key: "ready_to_render", label: "Render", color: "teal", dot: 7 },
  { key: "rendered", label: "Rendered", color: "teal", dot: 8 },
  { key: "uploaded_draft", label: "Draft", color: "amber", dot: 9 },
  { key: "done", label: "Published", color: "green", dot: 10 },
] as const;

// Map sub-stages to their parent dot index and display label
const SUB_STAGE_MAP: Record<string, { dotIndex: number; label: string }> = {
  approved: { dotIndex: 1, label: "Approved" },
  researching: { dotIndex: 1, label: "Researching" },
  scripting: { dotIndex: 1, label: "Scripting" },
  needs_script_review: { dotIndex: 1, label: "Needs Review" },
  voice: { dotIndex: 2, label: "Voice" },
  ready_for_image_prompts: { dotIndex: 3, label: "Image Prompts" },
  ready_for_storyboard_images: { dotIndex: 3, label: "Storyboard Images" },
  ready_for_storyboard_extraction: { dotIndex: 3, label: "Storyboard Extract" },
  ready_for_sound_design: { dotIndex: 4, label: "Sound Design" },
  ready_for_sound_effects: { dotIndex: 4, label: "Sound Effects" },
  ready_for_video_scripts: { dotIndex: 5, label: "Video Scripts" },
  ready_for_video_generation: { dotIndex: 5, label: "Video Generation" },
  rendering: { dotIndex: 7, label: "Rendering" },
  uploaded: { dotIndex: 9, label: "Uploaded" },
  published: { dotIndex: 9, label: "Published" },
};

export type StageKey = (typeof PIPELINE_STAGES)[number]["key"];

export function getStageIndex(status: string): number {
  const idx = PIPELINE_STAGES.findIndex((s) => s.key === status);
  if (idx >= 0) return idx;
  const sub = SUB_STAGE_MAP[status];
  if (sub) return sub.dotIndex;
  return 0;
}

export function getStageLabel(status: string): string {
  const stage = PIPELINE_STAGES.find((s) => s.key === status);
  if (stage) return stage.label;
  const sub = SUB_STAGE_MAP[status];
  if (sub) return sub.label;
  // Fallback: convert snake_case to Title Case
  return status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function getStageColor(status: string): string {
  const stage = PIPELINE_STAGES.find((s) => s.key === status);
  if (stage) return stage.color;
  const sub = SUB_STAGE_MAP[status];
  if (sub) return "teal";
  return "slate";
}

export const FILTER_OPTIONS = [
  { key: "all", label: "All" },
  { key: "in_production", label: "In Production" },
  { key: "ready_for_scripting", label: "Scripting" },
  { key: "ready_for_voice", label: "Voice" },
  { key: "ready_for_storyboards", label: "Storyboard" },
  { key: "ready_for_images", label: "Images" },
  { key: "ready_to_render", label: "Render" },
  { key: "uploaded", label: "Uploaded" },
  { key: "done", label: "Published" },
] as const;

// Statuses that mean "done/uploaded" — used to separate from active production
export const COMPLETED_STATUSES = new Set([
  "uploaded_draft", "uploaded", "done",
]);
