import type { QueueDeliveryMode, QueueItem, Workspace } from "../../lib/api";

export type QueueRunMode = "channel_default" | "static_docu";
export type QueueLifecycle =
  | "queued"
  | "running"
  | "retrying"
  | "completed"
  | "failed"
  | "blocked";

const BLOCKED_REASON = /(?:kill switch|budget|plan limit|worker.*unavailable|drain|approval|blocked)/i;

function isDvsuWorkspace(workspace: Pick<Workspace, "name" | "channel_name"> | undefined): boolean {
  return [workspace?.name, workspace?.channel_name]
    .filter(Boolean)
    .map((value) => String(value).trim().toLocaleLowerCase())
    .some((name) => name === "designed vs used" || name === "designedvsused" || name === "dvsu");
}

export function parseTitleLines(value: string): string[] {
  const seen = new Set<string>();
  const titles: string[] = [];
  for (const raw of value.split(/\r?\n/)) {
    const title = raw.trim().replace(/^[-*]\s+/, "").slice(0, 300);
    const key = title.toLocaleLowerCase().replace(/\s+/g, " ");
    if (!title || seen.has(key)) continue;
    seen.add(key);
    titles.push(title);
  }
  return titles;
}

export function defaultQueueRunMode(
  workspace: Pick<Workspace, "name" | "channel_name"> | undefined,
  items: Pick<QueueItem, "required_render_mode">[],
): QueueRunMode {
  if (items.some((item) => item.required_render_mode === "static_docu")) {
    return "static_docu";
  }
  return isDvsuWorkspace(workspace)
    ? "static_docu"
    : "channel_default";
}

export function defaultQueueDeliveryMode(
  workspace: Pick<Workspace, "name" | "channel_name"> | undefined,
): QueueDeliveryMode {
  return isDvsuWorkspace(workspace) ? "youtube_unlisted" : "render_only";
}

export function queueSubmitLabel(paused: boolean, pending: boolean): string {
  if (pending) return paused ? "Saving titles…" : "Starting list…";
  return paused ? "Save titles" : "Run list continuously";
}

export function queueLifecycle(item: QueueItem): QueueLifecycle {
  const reason = item.last_error || "";
  if (reason && BLOCKED_REASON.test(reason)) return "blocked";
  if (item.status === "completed") return "completed";
  if (item.status === "failed") return "failed";
  if (item.attempt_count > 0 && item.status === "queued") return "retrying";
  if (["dispatching", "running", "launched"].includes(item.status)) return "running";
  return "queued";
}
