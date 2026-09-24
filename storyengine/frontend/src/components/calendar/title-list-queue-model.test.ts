import { describe, expect, it } from "vitest";
import type { QueueItem } from "../../lib/api";
import {
  addToCalendarLabel,
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

  it("strips invisible/format characters and numbered list markers from pasted lines", () => {
    // Real operator paste: numbered with U+2060 WORD JOINER around the space
    // after the number, plus a leading plain space on some lines.
    const pasted = [
      " 6.⁠ ⁠Every US Battleship Class Ever Built (2026)",
      "10.⁠ ⁠Every Aircraft Carrier That Was Sunk in Combat (2026)",
      "11.⁠ ⁠Every US Destroyer Class Ever Built (1898–1945) (2026)",
    ].join("\n");
    expect(parseTitleLines(pasted)).toEqual([
      "Every US Battleship Class Ever Built (2026)",
      "Every Aircraft Carrier That Was Sunk in Combat (2026)",
      // En dash inside the title survives — only the leading marker is stripped.
      "Every US Destroyer Class Ever Built (1898–1945) (2026)",
    ]);
  });

  it("strips other leading list marker shapes without touching numbers inside the title", () => {
    expect(parseTitleLines("6) Every US Cruiser Class\n(6) Every US Frigate Class\n#6 Every US Corvette Class\n6 - Every US Submarine Class")).toEqual([
      "Every US Cruiser Class",
      "Every US Frigate Class",
      "Every US Corvette Class",
      "Every US Submarine Class",
    ]);
  });

  it("never strips a number that is part of the title itself", () => {
    expect(parseTitleLines("1940s Fighters That Never Saw Combat\nF-14 Tomcat Variants Explained")).toEqual([
      "1940s Fighters That Never Saw Combat",
      "F-14 Tomcat Variants Explained",
    ]);
  });

  it("normalizes non-breaking spaces and enforces the 300-char cap after marker stripping", () => {
    expect(parseTitleLines("1. Every US Icebreaker Class")).toEqual(["Every US Icebreaker Class"]);
    const longTitle = "A".repeat(320);
    expect(parseTitleLines(`3. ${longTitle}`)[0]).toHaveLength(300);
  });

  it("defaults delivery independently for DVSU and every other workspace", () => {
    expect(defaultQueueDeliveryMode({ name: "Designed vs Used", channel_name: null })).toBe("youtube_unlisted");
    expect(defaultQueueDeliveryMode({ name: "My Channel", channel_name: "Designed vs Used" })).toBe("youtube_unlisted");
    expect(defaultQueueDeliveryMode({ name: "Another Channel", channel_name: "Another Channel" })).toBe("render_only");
    expect(defaultQueueDeliveryMode(undefined)).toBe("render_only");
  });

  it("labels the two submit actions independently of pause state", () => {
    expect(addToCalendarLabel(false)).toBe("Add to calendar");
    expect(addToCalendarLabel(true)).toBe("Adding…");
    expect(queueSubmitLabel(false)).toBe("Run list continuously");
    expect(queueSubmitLabel(true)).toBe("Starting list…");
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
