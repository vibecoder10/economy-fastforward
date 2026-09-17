import { describe, expect, it, vi } from "vitest";
import { pollMachinePreviewJob } from "./machine-preview-job";

describe("pollMachinePreviewJob", () => {
  it("keeps polling a single operation through transient reads", async () => {
    const get = vi.fn()
      .mockRejectedValueOnce(new Error("gateway"))
      .mockResolvedValueOnce({ id: "x", status: "running" as const })
      .mockResolvedValueOnce({ id: "x", status: "completed" as const, result: { preview: { passed: true } } });
    const sleep = vi.fn().mockResolvedValue(undefined);
    const result = await pollMachinePreviewJob({ requestId: "x", get, sleep, transient: () => true });
    expect(result.status).toBe("completed");
    expect(get).toHaveBeenCalledTimes(3);
    expect(sleep).toHaveBeenCalledTimes(2);
  });

  it("does not turn a deadline into a new request", async () => {
    let now = 0;
    const get = vi.fn().mockResolvedValue({ id: "x", status: "running" as const });
    const sleep = vi.fn(async () => { now += 3000; });
    await expect(pollMachinePreviewJob({
      requestId: "x", get, sleep, now: () => now, deadlineMs: 3000, transient: () => false,
    })).rejects.toThrow("still running");
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("fails immediately when a different operation is returned", async () => {
    const get = vi.fn().mockResolvedValue({ id: "wrong", status: "running" as const });
    const sleep = vi.fn();
    await expect(pollMachinePreviewJob({ requestId: "expected", get, sleep, transient: () => true }))
      .rejects.toThrow("identity mismatch");
    expect(sleep).not.toHaveBeenCalled();
  });
});
