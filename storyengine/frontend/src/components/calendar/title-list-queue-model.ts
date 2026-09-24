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

// Invisible/format characters that show up when titles are pasted from rich
// text or messaging apps: zero-width space/joiners, word joiner, BOM, soft
// hyphen. Stripped outright — never meaningful in a video title.
const INVISIBLE_CHARS = /[​-‍⁠﻿­]/g;
// Non-breaking space normalizes to a plain space before whitespace collapse.
const NBSP = / /g;
// A leading list marker: bullets (-, *, •) or numbering ("6.", "6)", "(6)",
// "6 -", "#6"). Deliberately narrow so it never eats a number that's part of
// the title itself — e.g. "1940s Fighters..." (no separator after the
// digits) or "(1898–1945)" mid-title survives untouched.
const LIST_MARKER = /^(?:[-*•]\s+|\(\d{1,3}\)\s*|\d{1,3}[.)]\s*|#\d{1,3}\s+|\d{1,3}\s+-\s+)/;

export function parseTitleLines(value: string): string[] {
  const seen = new Set<string>();
  const titles: string[] = [];
  for (const raw of value.split(/\r?\n/)) {
    const cleaned = raw
      .replace(INVISIBLE_CHARS, "")
      .replace(NBSP, " ")
      .replace(/\s+/g, " ")
      .trim();
    const title = cleaned.replace(LIST_MARKER, "").trim().slice(0, 300);
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

// "Add to calendar" (continuous: false) is a plain save — it behaves the
// same whether or not production is currently paused, so it takes no pause
// argument.
export function addToCalendarLabel(pending: boolean): string {
  return pending ? "Adding…" : "Add to calendar";
}

export function queueSubmitLabel(pending: boolean): string {
  return pending ? "Starting list…" : "Run list continuously";
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
