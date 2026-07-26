import {canonicalJson, sha256Hex} from "../custom-film/canonical";
import {validateCustomFilmRemotionProps, type CustomFilmRemotionProps} from "../custom-film/schema";
import {
  ORCHESTRATION_CONTRACT_VERSION,
  SHOWCASE_ORCHESTRATION_PLAN,
  resolveShowcaseRecipes,
} from "./orchestration";
import type {LayeredSceneRecipe} from "./orchestration";

export const SHOWCASE_MANIFEST_VERSION = "storyengine-showcase-layered-v2" as const;
export const SHOWCASE_REQUEST = "Make me a cinematic five-minute Custom Film about the day the internet went dark. Open like a thriller, investigate the mystery with visual evidence, give it a bilingual human witness, explain the technical reveal so anyone can understand it, and end by revealing that StoryEngine assembled the film. Keep the total provider spend below $15.";
export const SHOWCASE_QUOTE = {
  estimate: 5.57,
  hard_cap: 15,
  approval_required: true,
} as const;

export const SHOWCASE_MOTION_PLAN = SHOWCASE_ORCHESTRATION_PLAN;
export const SHOWCASE_CUES = resolveShowcaseRecipes();

export const validateLayeredCustomFilmProps = (value: unknown): CustomFilmRemotionProps => {
  const props = validateCustomFilmRemotionProps(value);
  const resolved = props.orchestration?.resolved_plan;
  const recipes = resolved?.recipes as ReadonlyArray<LayeredSceneRecipe> | undefined;
  if (
    props.identity.assembly_version === "custom-film-assembly-v2" &&
    !props.orchestration
  ) {
    return props;
  }
  if (
    !resolved ||
    !recipes ||
    recipes.length === 0 ||
    resolved.fps !== props.video.fps ||
    resolved.total_frames !== props.video.total_frames ||
    props.orchestration?.resolved_plan_hash !== sha256Hex(canonicalJson(resolved)) ||
    props.orchestration.recipe_hash !== sha256Hex(canonicalJson(recipes))
  ) {
    throw new Error("Approved layered recipe identity changed");
  }
  let frame = 0;
  for (const item of recipes) {
    const section = props.sections[item.sectionIndex];
    const visualPrimitives = new Set(
      item.motionLayers
        .map(({primitive}) => primitive)
        .filter((primitive) =>
          primitive !== "MotionAudioSystem" &&
          primitive !== "BilingualCaptions"),
    );
    if (
      item.from !== frame ||
      item.to < item.from ||
      item.durationInFrames !== item.to - item.from + 1 ||
      !section ||
      item.from < section.start_frame ||
      item.to >= section.start_frame + section.duration_frames ||
      visualPrimitives.size < 2
    ) {
      throw new Error("Approved layered recipes changed their section layout");
    }
    frame = item.to + 1;
  }
  if (frame !== props.video.total_frames) {
    throw new Error("Approved layered recipes do not fill the film");
  }
  return props;
};

export const validateStoryEngineShowcaseProps = (value: unknown): CustomFilmRemotionProps => {
  const props = validateLayeredCustomFilmProps(value);
  if (
    SHOWCASE_ORCHESTRATION_PLAN.version !== ORCHESTRATION_CONTRACT_VERSION ||
    SHOWCASE_ORCHESTRATION_PLAN.fps !== 24 ||
    SHOWCASE_ORCHESTRATION_PLAN.width !== 1920 ||
    SHOWCASE_ORCHESTRATION_PLAN.height !== 1080 ||
    SHOWCASE_ORCHESTRATION_PLAN.total_frames !== 7200 ||
    props.video.fps !== 24 ||
    props.video.width !== 1920 ||
    props.video.height !== 1080 ||
    props.video.total_duration_seconds !== 300 ||
    props.video.total_frames !== 7200 ||
    props.sections.length !== 4
  ) {
    throw new Error("StoryEngine showcase video identity changed");
  }
  SHOWCASE_ORCHESTRATION_PLAN.sections.forEach((expected, index) => {
    const section = props.sections[index];
    if (
      section.role !== expected.role ||
      section.order_index !== index ||
      section.start_frame !== SHOWCASE_ORCHESTRATION_PLAN.sections
        .slice(0, index)
        .reduce((total, item) => total + item.duration_frames, 0) ||
      section.duration_frames !== expected.duration_frames ||
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
      sourceTrimStartFrame: number | null;
      sourceTrimEndFrame: number | null;
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
  const props = validateCustomFilmRemotionProps(propsValue);
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
    if (
      !sourceClip &&
      audioTransform.mode !== "none" &&
      audioTransform.mode !== "atempo" &&
      audioTransform.mode !== "cue_schedule"
    ) {
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
    const approximately = (left: number, right: number) =>
      Math.abs(left - right) <= 1e-7 * Math.max(1, Math.abs(left), Math.abs(right));
    if (audioTransform.mode === "cue_schedule") {
      if (
        section.audio.sources.length !== 1 ||
        atempoChain.length !== 0 ||
        audioTransform.caption_scale !== 1
      ) {
        throw new Error("Showcase cue schedule source or rate changed");
      }
    } else {
      const expectedRate = audioTransform.source_duration_ms / audioTransform.output_duration_ms;
      if (
        !approximately(playbackRate, expectedRate) ||
        !approximately(audioTransform.caption_scale, 1 / expectedRate)
      ) {
        throw new Error("Showcase audio timing transform is inconsistent");
      }
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
    const scheduledAudio = audioTransform.mode === "cue_schedule"
      ? audioTransform.cues.map((cue) => ({
          source: section.audio.sources[0],
          sourceIndex: cue.segment_index,
          sourceStartMs: cue.source_start_ms,
          sourceEndMs: cue.source_end_ms,
          targetStartMs: cue.target_start_ms,
          targetEndMs: cue.target_end_ms,
        }))
      : section.audio.sources.map((source, sourceIndex) => {
          const sourceStartMs = sourceElapsedMs;
          sourceElapsedMs += source.source_duration_ms;
          return {
            source,
            sourceIndex,
            sourceStartMs: 0,
            sourceEndMs: source.source_duration_ms,
            targetStartMs: Math.floor(
              sourceStartMs * audioTransform.output_duration_ms
              / audioTransform.source_duration_ms,
            ),
            targetEndMs: Math.floor(
              sourceElapsedMs * audioTransform.output_duration_ms
              / audioTransform.source_duration_ms,
            ),
          };
        });
    const audio = sourceClip ? [] : scheduledAudio.map((scheduled) => {
      const {source, sourceIndex} = scheduled;
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
      const cueTimes = audioTransform.mode === "cue_schedule"
        ? [
            scheduled.sourceStartMs,
            scheduled.sourceEndMs,
            scheduled.targetStartMs,
            scheduled.targetEndMs,
          ]
        : [];
      if (cueTimes.some((milliseconds) => milliseconds * props.video.fps % 1000 !== 0)) {
        throw new Error("Showcase audio cue is not frame exact");
      }
      const startOffsetFrames = scheduled.targetStartMs * props.video.fps / 1000;
      const endOffsetFrames = scheduled.targetEndMs * props.video.fps / 1000;
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
        sourceTrimStartFrame: audioTransform.mode === "cue_schedule"
          ? scheduled.sourceStartMs * props.video.fps / 1000
          : null,
        sourceTrimEndFrame: audioTransform.mode === "cue_schedule"
          ? scheduled.sourceEndMs * props.video.fps / 1000
          : null,
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
  const props = validateLayeredCustomFilmProps(propsValue);
  const recipes = props.orchestration?.resolved_plan
    ? props.orchestration.resolved_plan.recipes as ReadonlyArray<LayeredSceneRecipe>
    : SHOWCASE_CUES;
  const reference = props.orchestration?.reference_compatible === true;
  const manifest = {
    schema_version: SHOWCASE_MANIFEST_VERSION,
    orchestration_contract_version: props.orchestration?.contract_version ?? SHOWCASE_ORCHESTRATION_PLAN.version,
    decision_rules_version: props.orchestration?.decision_rules_version ?? SHOWCASE_ORCHESTRATION_PLAN.decision_rules_version,
    story_identity: props.orchestration?.story_identity ?? SHOWCASE_ORCHESTRATION_PLAN.story_identity,
    semantic_plan: props.orchestration?.semantic_input ?? SHOWCASE_ORCHESTRATION_PLAN,
    props_hash: props.props_hash,
    identity: {...props.identity},
    quote: reference || !props.orchestration ? SHOWCASE_QUOTE : {hard_cap: props.identity.max_spend},
    request: reference || !props.orchestration ? SHOWCASE_REQUEST : null,
    reference_authored_timing: reference || !props.orchestration,
    media_slots: resolveShowcaseMediaSlots(props),
    recipes,
  };
  const serialized = canonicalJson(manifest);
  if (/"(?:provider|model)[^"]*"\s*:/i.test(serialized)) {
    throw new Error("Showcase manifest exposed hidden generation internals");
  }
  return {...manifest, manifest_hash: sha256Hex(serialized)};
};
