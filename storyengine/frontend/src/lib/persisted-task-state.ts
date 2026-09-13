export type PersistedPipelineTaskStatus = "idle" | "pending" | "running" | "completed" | "failed";

const RENDERING_VIDEO_STATUSES = new Set(["ready_to_render", "rendering"]);

/** Interpret the durable task poll independently of local button-click state. */
export function persistedTaskActivity(
  status: PersistedPipelineTaskStatus,
  taskType: string | null | undefined,
  videoStatus?: string | null,
): { active: boolean; runAllActive: boolean; renderActive: boolean } {
  const active = status === "pending" || status === "running";
  const runAllActive = active && taskType === "autobuild";
  return {
    active,
    runAllActive,
    renderActive: active && (
      taskType === "render"
      || (runAllActive && RENDERING_VIDEO_STATUSES.has(String(videoStatus || "")))
    ),
  };
}
