export type VideoPreviewSnapshot = {
  updated_at: string | null | undefined;
  research_payload: unknown;
};

export type RecoveredMachinePreview = Record<string, unknown> & {
  machine: string;
  paragraph: string;
  passed: boolean;
};

export type MachinePreviewBaseline = {
  updatedAt: string | null | undefined;
  matchingPreviewCanonicalJson: string | null;
  valid: boolean;
};

export type GatewayRecoveryOptions<TVideo extends VideoPreviewSnapshot> = {
  baseline: MachinePreviewBaseline;
  machine: string;
  readVideo: (timeoutMs?: number) => Promise<TVideo>;
  sleep: (milliseconds: number) => Promise<void>;
  maxReads?: number;
  intervalMs?: number;
  deadlineMs?: number;
  now?: () => number;
};

export type GatewayRecoveryResult<TVideo extends VideoPreviewSnapshot> = {
  video: TVideo;
  preview: RecoveredMachinePreview;
};

export type MachinePreviewGatewayRunOptions<TVideo extends VideoPreviewSnapshot, TResult> = {
  machine: string;
  readVideo: (timeoutMs?: number) => Promise<TVideo>;
  post: () => Promise<TResult>;
  isGatewayError: (error: unknown) => boolean;
  sleep: (milliseconds: number) => Promise<void>;
  recoveredResult: (recovered: GatewayRecoveryResult<TVideo>) => TResult;
  maxReads?: number;
  intervalMs?: number;
  deadlineMs?: number;
  now?: () => number;
};

const normalizeMachine = (value: string): string =>
  value.toLowerCase().replace(/[^a-z0-9]/g, "");

const parsePayload = (payload: unknown): Record<string, unknown> | null => {
  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    return payload as Record<string, unknown>;
  }
  if (typeof payload !== "string") return null;
  try {
    const parsed = JSON.parse(payload);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null;
  } catch {
    return null;
  }
};

const stableValue = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, stableValue(child)]),
    );
  }
  return value;
};

export const canonicalPreviewJson = (preview: unknown): string => JSON.stringify(stableValue(preview));

const matchingPreviews = (video: VideoPreviewSnapshot, machine: string): Array<Record<string, unknown>> => {
  const payload = parsePayload(video.research_payload);
  const previews = payload?.machine_script_previews;
  if (!previews || typeof previews !== "object" || Array.isArray(previews)) return [];
  const wanted = normalizeMachine(machine);
  if (!wanted) return [];
  return Object.values(previews as Record<string, unknown>).filter((preview): preview is Record<string, unknown> => (
    preview !== null
    && typeof preview === "object"
    && typeof (preview as Record<string, unknown>).machine === "string"
    && normalizeMachine((preview as Record<string, unknown>).machine as string) === wanted
  ));
};

export const snapshotMachinePreview = (video: VideoPreviewSnapshot, machine: string): MachinePreviewBaseline => {
  const matches = matchingPreviews(video, machine);
  return {
    updatedAt: video.updated_at,
    matchingPreviewCanonicalJson: matches.length === 1 ? canonicalPreviewJson(matches[0]) : null,
    valid: normalizeMachine(machine).length > 0 && matches.length <= 1,
  };
};

const validStrictlyNewerTimestamp = (current: string | null | undefined, baseline: string | null | undefined): boolean => {
  if (typeof current !== "string" || typeof baseline !== "string") return false;
  const currentMs = Date.parse(current);
  const baselineMs = Date.parse(baseline);
  return Number.isFinite(currentMs) && Number.isFinite(baselineMs) && currentMs > baselineMs;
};

const acceptablePreview = (preview: Record<string, unknown>): preview is RecoveredMachinePreview => (
  typeof preview.machine === "string"
  && typeof preview.paragraph === "string"
  && preview.paragraph.trim().length > 0
  && typeof preview.passed === "boolean"
);

export const recoveredPreviewForVideo = (
  video: VideoPreviewSnapshot,
  machine: string,
  baseline: MachinePreviewBaseline,
): RecoveredMachinePreview | null => {
  const matches = matchingPreviews(video, machine);
  if (!baseline.valid) return null;
  if (matches.length !== 1 || !acceptablePreview(matches[0])) return null;
  if (!validStrictlyNewerTimestamp(video.updated_at, baseline.updatedAt)) return null;
  const currentJson = canonicalPreviewJson(matches[0]);
  if (baseline.matchingPreviewCanonicalJson !== null && currentJson === baseline.matchingPreviewCanonicalJson) return null;
  return matches[0];
};

export const recoverGatewayMachinePreview = async <TVideo extends VideoPreviewSnapshot>(
  options: GatewayRecoveryOptions<TVideo>,
): Promise<GatewayRecoveryResult<TVideo> | null> => {
  const maxReads = options.maxReads ?? 30;
  const intervalMs = options.intervalMs ?? 3_000;
  const deadlineMs = options.deadlineMs ?? 90_000;
  const now = options.now ?? Date.now;
  const deadline = now() + deadlineMs;
  for (let read = 0; read < maxReads; read += 1) {
    const beforeSleep = deadline - now();
    if (beforeSleep <= 0) break;
    await options.sleep(Math.min(intervalMs, beforeSleep));
    const remaining = deadline - now();
    if (remaining <= 0) break;
    try {
      const video = await options.readVideo(Math.min(remaining, 30_000));
      if (now() > deadline) break;
      const preview = recoveredPreviewForVideo(video, options.machine, options.baseline);
      if (preview) return { video, preview };
    } catch {
      // A transient read failure must not turn into another paid POST.
    }
  }
  return null;
};

export const runMachinePreviewWithGatewayRecovery = async <TVideo extends VideoPreviewSnapshot, TResult>(
  options: MachinePreviewGatewayRunOptions<TVideo, TResult>,
): Promise<TResult> => {
  // This read deliberately precedes the paid POST. Its failure prevents the
  // POST, because a baseline is required to fail closed on stale previews.
  const baselineVideo = await options.readVideo();
  const baseline = snapshotMachinePreview(baselineVideo, options.machine);
  if (!baseline.valid) {
    throw new Error("Machine preview recovery baseline is ambiguous or invalid; paid preview was not started.");
  }
  try {
    return await options.post();
  } catch (error) {
    if (!options.isGatewayError(error)) throw error;
    const recovered = await recoverGatewayMachinePreview({
      baseline,
      machine: options.machine,
      readVideo: options.readVideo,
      sleep: options.sleep,
      maxReads: options.maxReads,
      intervalMs: options.intervalMs,
      deadlineMs: options.deadlineMs,
      now: options.now,
    });
    if (!recovered) throw error;
    return options.recoveredResult(recovered);
  }
};
