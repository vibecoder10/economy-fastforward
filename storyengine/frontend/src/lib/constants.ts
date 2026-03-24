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

export type StageKey = (typeof PIPELINE_STAGES)[number]["key"];

export function getStageIndex(status: string): number {
  const idx = PIPELINE_STAGES.findIndex((s) => s.key === status);
  return idx >= 0 ? idx : 0;
}

export function getStageLabel(status: string): string {
  return PIPELINE_STAGES.find((s) => s.key === status)?.label ?? status;
}

export function getStageColor(status: string): string {
  return PIPELINE_STAGES.find((s) => s.key === status)?.color ?? "slate";
}

export const FILTER_OPTIONS = [
  { key: "all", label: "All" },
  { key: "ready_for_scripting", label: "Scripting" },
  { key: "ready_for_voice", label: "Voice" },
  { key: "ready_for_storyboards", label: "Storyboard" },
  { key: "ready_for_images", label: "Images" },
  { key: "ready_to_render", label: "Render" },
  { key: "done", label: "Published" },
] as const;
