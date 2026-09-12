import { describe, expect, it } from "vitest";
import type { QueueItem } from "../../lib/api";
import {
  defaultQueueDeliveryMode,
  defaultQueueRunMode,
  parseTitleLines,
  queueLifecycle,
  queueSubmitLabel,
} from "./title-list-queue-model";

const queueItem = (patch: Partial<QueueItem> = {}): QueueItem => ({
  id: "queue-1",
  position: 10,
  title: "A title",
  status: "queued",
  created_at: "2026-09-12T00:00:00Z",
  continuous: true,
  attempt_count: 0,
  delivery_mode: "render_only",
  ...patch,
});

describe("title-list queue model", () => {
  it("normalizes pasted lines while preserving order and removing duplicates", () => {
    expect(parseTitleLines(" First title\n- Second title\nfirst   title\n\n* Third title ")).toEqual([
      "First title",
      "Second title",
      "Third title",
    ]);
  });

  it("defaults delivery independently for DVSU and every other workspace", () => {
    expect(defaultQueueDeliveryMode({ name: "Designed vs Used", channel_name: null })).toBe("youtube_unlisted");
    expect(defaultQueueDeliveryMode({ name: "My Channel", channel_name: "Designed vs Used" })).toBe("youtube_unlisted");
    expect(defaultQueueDeliveryMode({ name: "Another Channel", channel_name: "Another Channel" })).toBe("render_only");
    expect(defaultQueueDeliveryMode(undefined)).toBe("render_only");
  });

  it("keeps title intake truthful while provider production is paused", () => {
    expect(queueSubmitLabel(true, false)).toBe("Save titles");
    expect(queueSubmitLabel(true, true)).toBe("Saving titles…");
    expect(queueSubmitLabel(false, false)).toBe("Run list continuously");
  });

  it("defaults the known DVSU tenant profile and its existing queue to static documentary", () => {
    expect(defaultQueueRunMode({ name: "Designed vs Used", channel_name: "Designed vs Used" }, [])).toBe("static_docu");
    expect(defaultQueueRunMode({ name: "My Channel", channel_name: "Designed vs Used" }, [])).toBe("static_docu");
    expect(defaultQueueRunMode(undefined, [queueItem({ required_render_mode: "static_docu" })])).toBe("static_docu");
    expect(defaultQueueRunMode({ name: "Other channel", channel_name: null }, [])).toBe("channel_default");
  });

  it("distinguishes policy blocks, retries, failures, and completed work", () => {
    expect(queueLifecycle(queueItem({ status: "queued", attempt_count: 1 }))).toBe("retrying");
    expect(queueLifecycle(queueItem({ status: "failed", last_error: "Weekly budget cap reached" }))).toBe("blocked");
    expect(queueLifecycle(queueItem({ status: "failed", last_error: "Renderer crashed" }))).toBe("failed");
    expect(queueLifecycle(queueItem({ status: "completed", completed_at: "2026-09-12T01:00:00Z" }))).toBe("completed");
  });
});
