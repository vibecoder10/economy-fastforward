import type {TimedWord} from "../motion-library/contracts";

export const MARA_MEASURED_WORDS: ReadonlyArray<TimedWord> = [
  {text: "Mara,", startFrame: 3840, endFrame: 3862},
  {text: "si", startFrame: 3862, endFrame: 3876},
  {text: "puedes", startFrame: 3876, endFrame: 3910},
  {text: "oírme,", startFrame: 3910, endFrame: 3953},
  {text: "no", startFrame: 3953, endFrame: 3972},
  {text: "reinicies", startFrame: 3972, endFrame: 4028},
  {text: "la", startFrame: 4028, endFrame: 4042},
  {text: "red.", startFrame: 4042, endFrame: 4084},
] as const;

export const MARA_RESPONSE_WORDS: ReadonlyArray<TimedWord> = [
  {text: "No.", startFrame: 4512, endFrame: 4541},
  {text: "He", startFrame: 4541, endFrame: 4558},
  {text: "always", startFrame: 4558, endFrame: 4599},
  {text: "swallowed", startFrame: 4599, endFrame: 4664},
  {text: "the", startFrame: 4664, endFrame: 4680},
  {text: "last", startFrame: 4680, endFrame: 4707},
  {text: "word", startFrame: 4707, endFrame: 4746},
  {text: "when", startFrame: 4746, endFrame: 4777},
  {text: "he", startFrame: 4777, endFrame: 4794},
  {text: "was", startFrame: 4794, endFrame: 4822},
  {text: "afraid.", startFrame: 4822, endFrame: 4877},
] as const;

export const activeAbsoluteWord = (
  words: ReadonlyArray<TimedWord>,
  absoluteFrame: number,
): number =>
  words.findIndex((word) => absoluteFrame >= word.startFrame && absoluteFrame < word.endFrame);

export const SHOWCASE_PULSE_ANCHOR_FRAME = 444;
export const showcasePulseFrame = (absoluteFrame: number): number =>
  absoluteFrame - SHOWCASE_PULSE_ANCHOR_FRAME;

export const showcaseSectionEnvelope = (frame: number): number => {
  const fadeRanges = [
    [1080, 1091],
    [3600, 3611],
    [5760, 5771],
  ] as const;
  const dipRanges = [
    [1068, 1079],
    [3588, 3599],
    [5748, 5759],
  ] as const;
  for (const [start, end] of fadeRanges) {
    if (frame >= start && frame <= end) return (frame - start + 1) / 12;
  }
  for (const [start, end] of dipRanges) {
    if (frame >= start && frame <= end) return 1 - (frame - start + 1) / 12;
  }
  return 1;
};

export const showcaseBedGain = (frame: number): number => {
  if (frame >= 384 && frame <= 443) return 0;
  const envelope = showcaseSectionEnvelope(frame);
  const dialogueDuck =
    (frame >= 3840 && frame <= 4199) ||
    (frame >= 4440 && frame <= 4919)
      ? 0.24
      : 1;
  return envelope * dialogueDuck;
};

export const SHOWCASE_AUDIO_CUES = [
  {id: "opening-pulse", role: "opening", from: 444, to: 527, path: "motion-audio/signal-pulse.wav", loop: true},
  {id: "opening-boundary-dip", role: "opening", from: 1068, to: 1079, path: "motion-audio/transition-envelope.wav", loop: false},
  {id: "evidence-boundary-fade", role: "evidence", from: 1080, to: 1091, path: "motion-audio/transition-envelope.wav", loop: false},
  {id: "evidence-clicks", role: "evidence", from: 1248, to: 1679, path: "motion-audio/data-click.wav", loop: true},
  {id: "evidence-boundary-dip", role: "evidence", from: 3588, to: 3599, path: "motion-audio/transition-envelope.wav", loop: false},
  {id: "witness-boundary-fade", role: "case_study", from: 3600, to: 3611, path: "motion-audio/transition-envelope.wav", loop: false},
  {id: "witness-radio", role: "case_study", from: 4920, to: 5399, path: "motion-audio/signal-pulse.wav", loop: true},
  {id: "witness-boundary-dip", role: "case_study", from: 5748, to: 5759, path: "motion-audio/transition-envelope.wav", loop: false},
  {id: "reveal-boundary-fade", role: "explanation", from: 5760, to: 5771, path: "motion-audio/transition-envelope.wav", loop: false},
  {id: "reconnect-grid", role: "explanation", from: 6048, to: 6071, path: "motion-audio/signal-pulse.wav", loop: false},
  {id: "reconnect-relay", role: "explanation", from: 6132, to: 6155, path: "motion-audio/signal-pulse.wav", loop: false},
  {id: "reconnect-radio", role: "explanation", from: 6216, to: 6239, path: "motion-audio/signal-pulse.wav", loop: false},
  {id: "reconnect-city", role: "explanation", from: 6300, to: 6323, path: "motion-audio/signal-pulse.wav", loop: false},
  {id: "brand-tone", role: "explanation", from: 7140, to: 7163, path: "motion-audio/transition-envelope.wav", loop: false},
] as const;
