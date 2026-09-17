export type MachinePreviewJob<T> = {
  id: string;
  status: "pending" | "running" | "completed" | "needs_review" | "failed" | "cancelled";
  result?: T | null;
  error?: string | null;
};

export const machinePreviewPendingKey = (tenant: string | null, videoId: string, machine: string) =>
  `machine-preview-job:${tenant || "default"}:${videoId}:${machine}`;

export async function pollMachinePreviewJob<T>(args: {
  requestId: string;
  get: () => Promise<MachinePreviewJob<T>>;
  sleep: (ms: number) => Promise<void>;
  now?: () => number;
  deadlineMs?: number;
  transient: (error: unknown) => boolean;
}): Promise<MachinePreviewJob<T>> {
  const now = args.now || Date.now;
  const deadline = now() + (args.deadlineMs ?? 30 * 60_000);
  let lastError: unknown;
  while (now() < deadline) {
    let job: MachinePreviewJob<T>;
    try {
      job = await args.get();
      lastError = undefined;
    } catch (error) {
      if (!args.transient(error)) throw error;
      lastError = error;
      await args.sleep(3000);
      continue;
    }
    if (job.id !== args.requestId) throw new Error("Preview job identity mismatch");
    if (["completed", "needs_review", "failed", "cancelled"].includes(job.status)) return job;
    await args.sleep(3000);
  }
  const suffix = lastError instanceof Error ? ` (${lastError.message})` : "";
  throw new Error(`Preview preparation is still running; resume the same request after reload${suffix}`);
}
