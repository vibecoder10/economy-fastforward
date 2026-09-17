import { describe, expect, it, vi } from "vitest";

import {
  runMachinePreviewWithGatewayRecovery,
  type VideoPreviewSnapshot,
} from "./machine-preview-recovery";

type Video = VideoPreviewSnapshot & { id: string };

const machine = "SS-1 — USS Holland";
const beforeTime = "2026-09-17T14:03:00.000Z";
const afterTime = "2026-09-17T14:04:29.000Z";

const preview = (paragraph = "A supported current preview.") => ({
  machine,
  paragraph,
  passed: true,
  warnings: [],
});

const video = (updated_at: string | null, previews: Record<string, unknown>): Video => ({
  id: "video-1",
  updated_at,
  research_payload: { machine_script_previews: previews },
});

const run = async (
  reads: Video[],
  post: () => Promise<string>,
  options: { maxReads?: number; gateway?: unknown; machine?: string } = {},
) => {
  let index = 0;
  const readVideo = vi.fn(async () => reads[Math.min(index++, reads.length - 1)]);
  const sleep = vi.fn(async () => undefined);
  const gateway = options.gateway ?? new Error("gateway");
  const result = await runMachinePreviewWithGatewayRecovery({
    machine: options.machine ?? machine,
    readVideo,
    post,
    isGatewayError: (error) => error === gateway,
    sleep,
    maxReads: options.maxReads,
    recoveredResult: ({ preview: recovered }) => `recovered:${recovered.paragraph}`,
  });
  return { result, readVideo, sleep, gateway };
};

describe("machine preview gateway recovery", () => {
  it("keeps the normal path to one POST", async () => {
    const post = vi.fn(async () => "normal");
    const result = await run([video(beforeTime, { SS1: preview() })], post);

    expect(result.result).toBe("normal");
    expect(post).toHaveBeenCalledTimes(1);
    expect(result.readVideo).toHaveBeenCalledTimes(1);
    expect(result.sleep).not.toHaveBeenCalled();
  });

  it("recovers a 504 only after a later matching preview is persisted", async () => {
    const gateway = new Error("504");
    const post = vi.fn(async () => { throw gateway; });
    const result = await run([
      video(beforeTime, { SS1: preview("old") }),
      video(beforeTime, { SS1: preview("old") }),
      video(afterTime, { SS1: preview("new") }),
    ], post, { gateway });

    expect(result.result).toBe("recovered:new");
    expect(post).toHaveBeenCalledTimes(1);
    expect(result.readVideo).toHaveBeenCalledTimes(3);
    expect(result.sleep).toHaveBeenCalledTimes(2);
  });

  it("does not accept an unchanged preview when some other video write bumps updated_at", async () => {
    const gateway = new Error("504");
    const post = vi.fn(async () => { throw gateway; });
    await expect(run([
      video(beforeTime, { SS1: preview("old") }),
      video(afterTime, { SS1: preview("old") }),
    ], post, { gateway, maxReads: 1 })).rejects.toBe(gateway);
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("does not accept a newly persisted preview for a different machine", async () => {
    const gateway = new Error("502");
    const post = vi.fn(async () => { throw gateway; });
    await expect(run([
      video(beforeTime, {}),
      video(afterTime, { SS2: { ...preview("wrong"), machine: "SS-2 USS Plunger" } }),
    ], post, { gateway, maxReads: 1 })).rejects.toBe(gateway);
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("accepts a matching preview that was absent before the POST", async () => {
    const gateway = new Error("504");
    const post = vi.fn(async () => { throw gateway; });
    const result = await run([
      video(beforeTime, {}),
      video(afterTime, { SS1: preview("new") }),
    ], post, { gateway });

    expect(result.result).toBe("recovered:new");
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("fails closed on an invalid updated_at timestamp", async () => {
    const gateway = new Error("504");
    const post = vi.fn(async () => { throw gateway; });
    await expect(run([
      video(beforeTime, {}),
      video("not-a-timestamp", { SS1: preview("new") }),
    ], post, { gateway, maxReads: 1 })).rejects.toBe(gateway);
  });

  it("does not accept a read that finishes after the real 90-second deadline", async () => {
    const gateway = new Error("504");
    const post = vi.fn(async () => { throw gateway; });
    let now = 0;
    let readNumber = 0;
    const observedTimeouts: Array<number | undefined> = [];
    const readVideo = vi.fn(async (timeoutMs?: number) => {
      readNumber += 1;
      if (readNumber === 1) return video(beforeTime, {});
      observedTimeouts.push(timeoutMs);
      now += 88_000;
      return video(afterTime, { SS1: preview("new") });
    });
    const sleep = vi.fn(async (milliseconds: number) => { now += milliseconds; });

    await expect(runMachinePreviewWithGatewayRecovery({
      machine,
      readVideo,
      post,
      isGatewayError: (error) => error === gateway,
      sleep,
      recoveredResult: () => "recovered",
      now: () => now,
    })).rejects.toBe(gateway);
    expect(post).toHaveBeenCalledTimes(1);
    expect(observedTimeouts).toEqual([30_000]);
  });

  it("fails before the paid POST for an ambiguous baseline", async () => {
    const post = vi.fn(async () => "should-not-run");
    await expect(runMachinePreviewWithGatewayRecovery({
      machine,
      readVideo: async () => video(beforeTime, {
        SS1: preview("first"),
        SS1Alias: { ...preview("second"), machine: "SS1 USS Holland" },
      }),
      post,
      isGatewayError: () => false,
      sleep: async () => undefined,
      recoveredResult: () => "recovered",
    })).rejects.toThrow("baseline is ambiguous or invalid");
    expect(post).not.toHaveBeenCalled();
  });

  it("fails before the paid POST for an empty normalized machine", async () => {
    const post = vi.fn(async () => "should-not-run");
    await expect(runMachinePreviewWithGatewayRecovery({
      machine: "——",
      readVideo: async () => video(beforeTime, {}),
      post,
      isGatewayError: () => false,
      sleep: async () => undefined,
      recoveredResult: () => "recovered",
    })).rejects.toThrow("baseline is ambiguous or invalid");
    expect(post).not.toHaveBeenCalled();
  });

  it("does not poll for a non-gateway error", async () => {
    const providerError = new Error("provider failed");
    const post = vi.fn(async () => { throw providerError; });
    await expect(run([video(beforeTime, {})], post, { gateway: new Error("gateway") })).rejects.toBe(providerError);
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("rethrows the original gateway error after the bounded reads without a POST retry", async () => {
    const gateway = new Error("504");
    const post = vi.fn(async () => { throw gateway; });
    await expect(run([
      video(beforeTime, { SS1: preview("old") }),
      video(afterTime, { SS1: preview("old") }),
      video(afterTime, { SS1: preview("old") }),
    ], post, { gateway, maxReads: 2 })).rejects.toBe(gateway);
    expect(post).toHaveBeenCalledTimes(1);
  });
});
