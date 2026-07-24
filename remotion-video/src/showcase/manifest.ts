import {canonicalJson, sha256Hex} from "../custom-film/canonical";
import {validateCustomFilmRemotionProps, type CustomFilmRemotionProps} from "../custom-film/schema";

export const SHOWCASE_MANIFEST_VERSION = "storyengine-showcase-cues-v1" as const;
export const SHOWCASE_REQUEST = "Make me a cinematic five-minute Custom Film about the day the internet went dark. Open like a thriller, investigate the mystery with visual evidence, give it a bilingual human witness, explain the technical reveal so anyone can understand it, and end by revealing that StoryEngine assembled the film. Keep the total provider spend below $15.";
export const SHOWCASE_QUOTE = {
  estimate: 5.57,
  hard_cap: 15,
  approval_required: true,
} as const;

const cue = (id: string, sectionIndex: number, from: number, to: number) => ({
  id,
  sectionIndex,
  from,
  to,
  durationInFrames: to - from + 1,
});

export const SHOWCASE_CUES = [
  cue("opening-clock", 0, 0, 95),
  cue("opening-failure-cascade", 0, 96, 383),
  cue("opening-hard-silence", 0, 384, 443),
  cue("opening-first-pulse", 0, 444, 527),
  cue("opening-frozen-city", 0, 528, 815),
  cue("opening-tower", 0, 816, 959),
  cue("opening-title", 0, 960, 1067),
  cue("opening-dip", 0, 1068, 1079),
  cue("evidence-fade", 1, 1080, 1091),
  cue("evidence-map", 1, 1092, 2111),
  cue("evidence-board", 1, 2112, 3071),
  cue("evidence-timeline", 1, 3072, 3431),
  cue("evidence-voice-packet", 1, 3432, 3587),
  cue("evidence-dip", 1, 3588, 3599),
  cue("witness-fade", 2, 3600, 3611),
  cue("witness-mara-intro", 2, 3612, 3839),
  cue("witness-measured-line", 2, 3840, 4199),
  cue("witness-reaction", 2, 4200, 4439),
  cue("witness-objection-response", 2, 4440, 4919),
  cue("witness-waveform-code", 2, 4920, 5399),
  cue("witness-recovery-key", 2, 5400, 5747),
  cue("witness-dip", 2, 5748, 5759),
  cue("reveal-fade", 3, 5760, 5771),
  cue("reveal-node-collapse", 3, 5772, 6047),
  cue("reveal-ordered-reconnect", 3, 6048, 6383),
  cue("reveal-city-return", 3, 6384, 6623),
  cue("reveal-pullback-timeline", 3, 6624, 6839),
  cue("reveal-four-tracks", 3, 6840, 6899),
  cue("reveal-tracks-lock", 3, 6900, 6959),
  cue("reveal-chat", 3, 6960, 7019),
  cue("reveal-approved-plan", 3, 7020, 7079),
  cue("reveal-convergence", 3, 7080, 7139),
  cue("reveal-promise", 3, 7140, 7175),
  cue("reveal-end-card", 3, 7176, 7199),
] as const;

const expectedSections = [
  {role: "opening", start: 0, duration: 1080},
  {role: "evidence", start: 1080, duration: 2520},
  {role: "case_study", start: 3600, duration: 2160},
  {role: "explanation", start: 5760, duration: 1440},
] as const;

export const validateStoryEngineShowcaseProps = (value: unknown): CustomFilmRemotionProps => {
  const props = validateCustomFilmRemotionProps(value);
  if (
    props.video.fps !== 24 ||
    props.video.width !== 1920 ||
    props.video.height !== 1080 ||
    props.video.total_duration_seconds !== 300 ||
    props.video.total_frames !== 7200 ||
    props.sections.length !== 4
  ) {
    throw new Error("StoryEngine showcase video identity changed");
  }
  expectedSections.forEach((expected, index) => {
    const section = props.sections[index];
    if (
      section.role !== expected.role ||
      section.order_index !== index ||
      section.start_frame !== expected.start ||
      section.duration_frames !== expected.duration ||
      section.transition_in.overlap_frames !== 0 ||
      section.transition_out.overlap_frames !== 0
    ) {
      throw new Error("StoryEngine showcase section identity changed");
    }
  });
  return props;
};

export type ShowcaseMediaSlot =
  | {
      kind: "procedural";
      sourceKey: string;
      sourceSha256: string;
      provenanceHash: string;
      captionHash: string;
      role: string;
      sectionId: string;
      sectionOrder: number;
      startFrame: number;
      durationInFrames: number;
      timingMode: string;
    }
  | {
      kind: "visual";
      sourceKey: string;
      sourceSha256: string;
      provenanceHash: string;
      captionHash: string;
      role: string;
      sectionId: string;
      sectionOrder: number;
      startFrame: number;
      durationInFrames: number;
      timingMode: string;
      sourceDurationFrames: number | null;
      mediaType: "image" | "video";
      localPath: string;
      nativeAudioEnabled: boolean;
      nativeAudioPlaybackRate: number;
      nativeAudioGainDb: number;
      nativeAudioTimingMode: string | null;
    }
  | {
      kind: "audio";
      sourceKey: string;
      sourceSha256: string;
      role: string;
      sectionId: string;
      sectionOrder: number;
      startFrame: number;
      durationInFrames: number;
      gainDb: number;
      timingMode: string;
      sourceDurationMs: number;
      outputDurationInFrames: number;
      sourceIndex: number;
      playbackRate: number;
      atempoChain: ReadonlyArray<number>;
      endBehavior: "trim_or_silence_pad";
      localPath: string;
    };

export type ShowcaseMediaPathOverride = {
  readonly localPath: string;
};

const AUDIO_PATHS: Record<string, string> = {
  "synthetic:opening:audio": "motion-audio/music-bed.wav",
  "synthetic:evidence:audio": "motion-audio/data-click.wav",
  "synthetic:witness:audio": "motion-audio/signal-pulse.wav",
  "synthetic:explanation:audio": "motion-audio/transition-envelope.wav",
};

export const stagedLocalPathForSourceKey = (
  sourceKey: string,
  kind: "image" | "video" | "audio",
): string => {
  const digest = sha256Hex(sourceKey);
  const extension = kind === "image" ? "png" : kind === "video" ? "mp4" : "wav";
  return `custom-film-sources/${kind}/${digest}.${extension}`;
};

export const resolveShowcaseMediaSlots = (
  propsValue: unknown,
  overrides: Readonly<Record<string, ShowcaseMediaPathOverride>> = {},
): ReadonlyArray<ShowcaseMediaSlot> => {
  const props = validateStoryEngineShowcaseProps(propsValue);
  const approvedKeys = new Set(
    props.sections.flatMap((section) => [
      ...section.assets.map((asset) => asset.source_key),
      ...section.audio.sources.map((source) => source.source_key),
    ]),
  );
  for (const [sourceKey, override] of Object.entries(overrides)) {
    if (!approvedKeys.has(sourceKey)) throw new Error("Showcase override source_key is not approved");
    if (
      !override ||
      Object.keys(override).length !== 1 ||
      typeof override.localPath !== "string"
    ) {
      throw new Error("Showcase override may only supply localPath");
    }
  }
  return props.sections.flatMap((section) => {
    const audioTransform = section.audio.timing_transform;
    if (audioTransform.mode === "pending_source_probe") {
      throw new Error("Showcase audio cannot render pending source timing");
    }
    const sourceClip = section.audio.mode === "source_clip";
    if (sourceClip !== (audioTransform.mode === "source_clip")) {
      throw new Error("Showcase audio mode and timing transform disagree");
    }
    if (!sourceClip && audioTransform.mode !== "none" && audioTransform.mode !== "atempo") {
      throw new Error("Showcase narration timing mode is unsupported");
    }
    const sectionOutputMs = section.duration_frames * 1000 / props.video.fps;
    if (
      !Number.isInteger(sectionOutputMs) ||
      audioTransform.output_duration_ms !== sectionOutputMs
    ) {
      throw new Error("Showcase audio output duration changed");
    }
    const atempoChain = audioTransform.atempo_chain;
    if (atempoChain.some((factor) => factor < 0.5 || factor > 2)) {
      throw new Error("Showcase audio atempo factor is outside the approved range");
    }
    const playbackRate = atempoChain.reduce((product, factor) => product * factor, 1);
    const expectedRate = audioTransform.source_duration_ms / audioTransform.output_duration_ms;
    const approximately = (left: number, right: number) =>
      Math.abs(left - right) <= 1e-7 * Math.max(1, Math.abs(left), Math.abs(right));
    if (
      !approximately(playbackRate, expectedRate) ||
      !approximately(audioTransform.caption_scale, 1 / expectedRate)
    ) {
      throw new Error("Showcase audio timing transform is inconsistent");
    }
    if (
      audioTransform.mode === "none" &&
      (atempoChain.length !== 0 || audioTransform.source_duration_ms !== audioTransform.output_duration_ms)
    ) {
      throw new Error("Showcase untransformed audio timing changed");
    }
    if (audioTransform.mode === "atempo" && atempoChain.length === 0) {
      throw new Error("Showcase atempo timing has no playback transform");
    }
    if (sourceClip && section.audio.sources.length !== 0) {
      throw new Error("Showcase source_clip audio must come only from approved video");
    }
    if (!sourceClip) {
      const sourceDurationMs = section.audio.sources.reduce(
        (total, source) => total + source.source_duration_ms,
        0,
      );
      if (
        section.audio.sources.length === 0 ||
        sourceDurationMs !== audioTransform.source_duration_ms
      ) {
        throw new Error("Showcase narration source timing is incomplete");
      }
    }
    const visual = section.assets.map((asset) => {
      const stagedKind = asset.timing_transform.mode === "static_hold" ? "image" : "video";
      const override = overrides[asset.source_key];
      if (override && asset.source_key.startsWith("synthetic:")) {
        throw new Error("Synthetic showcase slots cannot be overridden");
      }
      const approvedStagedPath = stagedLocalPathForSourceKey(asset.source_key, stagedKind);
      if (override && override.localPath !== approvedStagedPath) {
        throw new Error("Showcase override path or media type changed");
      }
      const slot: ShowcaseMediaSlot = (
        asset.source_key.startsWith("synthetic:")
          ? {
              kind: "procedural" as const,
              sourceKey: asset.source_key,
              sourceSha256: asset.source_sha256,
              provenanceHash: asset.provenance_hash,
              captionHash: asset.caption_hash,
              role: section.role,
              sectionId: section.section_id,
              sectionOrder: section.order_index,
              startFrame: section.start_frame + asset.start_frame,
              durationInFrames: asset.duration_frames,
              timingMode: asset.timing_transform.mode,
            }
          : {
              kind: "visual" as const,
              sourceKey: asset.source_key,
              sourceSha256: asset.source_sha256,
              provenanceHash: asset.provenance_hash,
              captionHash: asset.caption_hash,
              role: section.role,
              sectionId: section.section_id,
              sectionOrder: section.order_index,
              startFrame: section.start_frame + asset.start_frame,
              durationInFrames: asset.duration_frames,
              timingMode: asset.timing_transform.mode,
              sourceDurationFrames:
                asset.timing_transform.source_duration_ms === null
                  ? null
                  : Math.max(1, Math.round(asset.timing_transform.source_duration_ms * props.video.fps / 1000)),
              mediaType: stagedKind,
              localPath: override?.localPath ?? approvedStagedPath,
              nativeAudioEnabled: sourceClip && stagedKind === "video",
              nativeAudioPlaybackRate: sourceClip ? playbackRate : 1,
              nativeAudioGainDb: section.audio.gain_db,
              nativeAudioTimingMode: sourceClip ? audioTransform.mode : null,
            }
      );
      if (
        slot.kind === "visual" &&
        (!slot.localPath || /^https?:/i.test(slot.localPath) || slot.localPath.includes("..") || /mapbox|token/i.test(slot.localPath))
      ) {
        throw new Error("Showcase media slots must resolve to local deterministic media");
      }
      return slot;
    });
    if (sourceClip) {
      let expectedStart = section.start_frame;
      for (const slot of visual) {
        if (
          slot.kind !== "visual" ||
          slot.mediaType !== "video" ||
          !slot.nativeAudioEnabled ||
          slot.startFrame !== expectedStart
        ) {
          throw new Error("Showcase source_clip must be contiguous approved video only");
        }
        expectedStart += slot.durationInFrames;
      }
      if (expectedStart !== section.start_frame + section.duration_frames) {
        throw new Error("Showcase source_clip must fill its section with approved video");
      }
    }
    let sourceElapsedMs = 0;
    const audio = sourceClip ? [] : section.audio.sources.map((source, sourceIndex) => {
      const override = overrides[source.source_key];
      if (override && source.source_key.startsWith("synthetic:")) {
        throw new Error("Synthetic showcase slots cannot be overridden");
      }
      const approvedStagedPath = stagedLocalPathForSourceKey(source.source_key, "audio");
      if (
        override &&
        override.localPath !== approvedStagedPath
      ) {
        throw new Error("Showcase override path or media type changed");
      }
      const startOffsetFrames = Math.floor(
        sourceElapsedMs * section.duration_frames / audioTransform.source_duration_ms,
      );
      sourceElapsedMs += source.source_duration_ms;
      const endOffsetFrames = sourceIndex === section.audio.sources.length - 1
        ? section.duration_frames
        : Math.floor(sourceElapsedMs * section.duration_frames / audioTransform.source_duration_ms);
      const slot: ShowcaseMediaSlot = {
        kind: "audio" as const,
        sourceKey: source.source_key,
        sourceSha256: source.source_sha256,
        role: section.role,
        sectionId: section.section_id,
        sectionOrder: section.order_index,
        startFrame: section.start_frame + startOffsetFrames,
        durationInFrames: endOffsetFrames - startOffsetFrames,
        gainDb: section.audio.gain_db,
        timingMode: audioTransform.mode,
        sourceDurationMs: source.source_duration_ms,
        outputDurationInFrames: endOffsetFrames - startOffsetFrames,
        sourceIndex,
        playbackRate,
        atempoChain: [...atempoChain],
        endBehavior: "trim_or_silence_pad",
        localPath: AUDIO_PATHS[source.source_key] ?? override?.localPath ?? approvedStagedPath,
      };
      if (
        slot.durationInFrames <= 0 ||
        !slot.localPath ||
        /^https?:/i.test(slot.localPath) ||
        slot.localPath.includes("..") ||
        /mapbox|token/i.test(slot.localPath)
      ) {
        throw new Error("Showcase media slots must resolve to local deterministic media");
      }
      return slot;
    });
    return [...visual, ...audio];
  });
};

export const compileShowcaseManifest = (propsValue: unknown) => {
  const props = validateStoryEngineShowcaseProps(propsValue);
  let frame = 0;
  for (const item of SHOWCASE_CUES) {
    if (item.from !== frame || item.to < item.from) throw new Error("Showcase cues are not contiguous");
    const section = props.sections[item.sectionIndex];
    if (item.from < section.start_frame || item.to >= section.start_frame + section.duration_frames) {
      throw new Error("Showcase cue crossed its approved section");
    }
    frame = item.to + 1;
  }
  if (frame !== 7200) throw new Error("Showcase cues do not fill exactly 7200 frames");
  const manifest = {
    schema_version: SHOWCASE_MANIFEST_VERSION,
    props_hash: props.props_hash,
    identity: {...props.identity},
    quote: SHOWCASE_QUOTE,
    request: SHOWCASE_REQUEST,
    media_slots: resolveShowcaseMediaSlots(props),
    cues: SHOWCASE_CUES,
  };
  const serialized = canonicalJson(manifest);
  if (/"(?:provider|model)[^"]*"\s*:/i.test(serialized)) {
    throw new Error("Showcase manifest exposed hidden generation internals");
  }
  return {...manifest, manifest_hash: sha256Hex(serialized)};
};
