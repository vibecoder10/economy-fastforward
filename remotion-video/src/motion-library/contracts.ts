export const MOTION_AUDIO_FILES = [
  "signal-pulse.wav",
  "silence-drop.wav",
  "data-click.wav",
  "transition-envelope.wav",
  "music-bed.wav",
] as const;

export const MOTION_AUDIO_SHA256: Readonly<Record<(typeof MOTION_AUDIO_FILES)[number], string>> = {
  "data-click.wav": "a613caf2f4991325ca47af5cbe2d0870629112040f8c5b290b29a00d1863e883",
  "music-bed.wav": "63570c59f6fc499c5d3cd991372e66bfeb85b316fe9c3058ac1d54fd10b073ea",
  "signal-pulse.wav": "69d66a6e55ba6f32888b6c392cd84e7ad77e9d73627c67dc63e329fa4118055d",
  "silence-drop.wav": "632ffe13ce979298edcd436902b080cc06933e81fd06ffadba14b635ecf432d4",
  "transition-envelope.wav": "8d5be3b4c9def2918d9e0967e480439e6086dcc08fcfbb7fb77149cc431d7e9b",
};

export const PREVIEW_PRIMITIVES = [
  "SignalPulse",
  "OutageMap",
  "EvidenceBoard",
  "IncidentTimeline",
  "RadioWaveform",
  "BilingualCaptions",
  "NetworkExplainer",
  "StoryEngineReveal",
  "MotionAudioSystem",
] as const;

export const PREVIEW_SECONDS_PER_PRIMITIVE = 4;
export const CENTER_CROP_BOUNDS = {
  x: 656,
  width: 608,
  criticalX: 680,
  criticalWidth: 560,
  criticalTop: 120,
  criticalBottom: 930,
} as const;

export const SILENCE_DROP_WINDOW_SECONDS = {
  start: 1.25,
  end: 1.85,
  pulseEntryEnd: 2.35,
} as const;

export const motionBedGain = (frame: number, fps: number): number => {
  const start = Math.round(SILENCE_DROP_WINDOW_SECONDS.start * fps);
  const end = Math.round(SILENCE_DROP_WINDOW_SECONDS.end * fps);
  const recoveryEnd = Math.round(SILENCE_DROP_WINDOW_SECONDS.pulseEntryEnd * fps);
  if (frame < start) return 1;
  if (frame < end) return 0;
  if (frame >= recoveryEnd) return 1;
  return (frame - end) / Math.max(1, recoveryEnd - end);
};

export const pulseEntryGain = (frame: number, fps: number): number => {
  const end = Math.round(SILENCE_DROP_WINDOW_SECONDS.end * fps);
  const recoveryEnd = Math.round(SILENCE_DROP_WINDOW_SECONDS.pulseEntryEnd * fps);
  if (frame < end || frame >= recoveryEnd) return 0;
  const progress = (frame - end) / Math.max(1, recoveryEnd - end);
  return Math.sin(progress * Math.PI);
};

export const motionMixGains = (frame: number, fps: number) => {
  const start = Math.round(SILENCE_DROP_WINDOW_SECONDS.start * fps);
  const end = Math.round(SILENCE_DROP_WINDOW_SECONDS.end * fps);
  const cueFrames = Math.max(1, Math.round(0.18 * fps));
  const inSilence = frame >= start && frame < end;
  return {
    bed: motionBedGain(frame, fps),
    silenceCue: frame >= start - cueFrames && frame < start ? 1 : 0,
    pulse: inSilence ? 0 : pulseEntryGain(frame, fps),
    clicks: inSilence ? 0 : (frame % 12 < 3 ? 0.9 : 0.15),
    transition: inSilence ? 0 : Math.max(0, 1 - Math.abs(frame - fps * 2) / fps),
  } as const;
};
export const SIGNAL_PULSE_CYCLE_SECONDS = 11;
export const SIGNAL_PULSE_BURST_OFFSETS_SECONDS = [
  0,
  1 / 3,
  2 / 3,
  2.25,
  2.625,
  5.3,
  8.5,
] as const;

export const signalPulseBurstFrames = (fps: number): ReadonlyArray<number> =>
  SIGNAL_PULSE_BURST_OFFSETS_SECONDS.map((seconds) => Math.round(seconds * fps));

export const signalPulseCycleFrame = (frame: number, fps: number): number => {
  const cycleFrames = SIGNAL_PULSE_CYCLE_SECONDS * fps;
  return ((frame % cycleFrames) + cycleFrames) % cycleFrames;
};

export const signalPulseEnergy = (frame: number, fps: number): number => {
  const cycle = signalPulseCycleFrame(frame, fps);
  const attack = Math.max(1, Math.round(fps * 0.08));
  const release = Math.max(attack + 1, Math.round(fps * 0.42));
  return signalPulseBurstFrames(fps).reduce((strongest, burst) => {
    const elapsed = cycle - burst;
    if (elapsed < 0 || elapsed > release) return strongest;
    const value = 1 - elapsed / release;
    return Math.max(strongest, value);
  }, 0);
};

export const previewSegments = (fps: number) =>
  PREVIEW_PRIMITIVES.map((name, index) => ({
    name,
    from: index * PREVIEW_SECONDS_PER_PRIMITIVE * fps,
    durationInFrames: PREVIEW_SECONDS_PER_PRIMITIVE * fps,
  }));

export type TimedWord = {
  readonly text: string;
  readonly startFrame: number;
  readonly endFrame: number;
};

export const activeWordIndex = (
  words: ReadonlyArray<TimedWord>,
  frame: number,
): number =>
  words.findIndex(
    (word) => frame >= word.startFrame && frame < word.endFrame,
  );

export const routeProgress = (
  frame: number,
  startFrame: number,
  durationFrames: number,
): number => {
  if (durationFrames <= 0) throw new Error("Route duration must be positive");
  return Math.max(0, Math.min(1, (frame - startFrame) / durationFrames));
};

export const assertLocalMotionSources = (
  values: ReadonlyArray<string>,
): void => {
  for (const value of values) {
    if (
      /^https?:\/\//i.test(value) ||
      /mapbox|token|access_token/i.test(value) ||
      value.includes("..")
    ) {
      throw new Error("Motion-library sources must be deterministic local assets");
    }
  }
};
