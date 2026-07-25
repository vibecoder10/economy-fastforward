import orchestrationPlan from "./orchestration-plan-v1.json";

export const ORCHESTRATION_CONTRACT_VERSION =
  "storyengine-layered-orchestration-v1" as const;
export const DECISION_RULES_VERSION =
  "storyengine-layered-recipe-rules-v1" as const;

export type MediaKind = "image" | "video" | "adaptive";
export type Energy = 0 | 1 | 2 | 3;
export type Handoff =
  | "pulse"
  | "silence"
  | "pulse_to_route"
  | "route"
  | "route_to_connector"
  | "connector"
  | "connector_to_waveform"
  | "waveform"
  | "waveform_to_key"
  | "key_to_network"
  | "network"
  | "network_to_master"
  | "master";

export type SceneSignals = {
  readonly media_kind: MediaKind;
  readonly dialogue: boolean;
  readonly captions: boolean;
  readonly intents: ReadonlyArray<string>;
  readonly energy: Energy;
  readonly handoff: Handoff;
};

export type SemanticCue = {
  readonly id: string;
  readonly section_index: number;
  readonly from: number;
  readonly to: number;
  readonly signals: SceneSignals;
  readonly narrative_function?: string | null;
  readonly requested_capability_ids?: ReadonlyArray<string>;
};

export type MotionLayer = {
  readonly primitive: string;
  readonly zIndex: number;
  readonly blend: "normal" | "screen" | "multiply";
  readonly intensity: number;
  readonly safeZone: "center-critical" | "full-title-safe";
};

export type LayeredSceneRecipe = {
  readonly id: string;
  readonly sectionIndex: number;
  readonly from: number;
  readonly to: number;
  readonly durationInFrames: number;
  readonly signals: SceneSignals;
  readonly narrativeFunction: string | null;
  readonly requestedCapabilities: ReadonlyArray<string>;
  readonly media: {
    readonly primary: "approved-overlap";
    readonly secondary: "approved-overlap-optional";
    readonly primaryZIndex: 10;
    readonly secondaryZIndex: 14;
    readonly secondaryBlend: "screen";
    readonly secondaryIntensity: number;
  };
  readonly motionLayers: ReadonlyArray<MotionLayer>;
  readonly presentation: string;
  readonly caption: {
    readonly mode: "none" | "approved" | "bilingual-word-emphasis";
    readonly zIndex: 90;
    readonly safeZone: "center-critical";
  };
  readonly camera: {
    readonly mode: "locked" | "slow-push" | "investigative-drift" | "reactive-push";
    readonly intensity: number;
  };
  readonly transition: {
    readonly mode: "none" | "dip" | "fade" | "transform-carry";
    readonly carry: Handoff;
    readonly overlapFrames: 0;
  };
  readonly audio: {
    readonly bedGain: number;
    readonly dialogueDuck: number;
    readonly pulse: boolean;
    readonly dataClicks: boolean;
    readonly silenceDrop: boolean;
    readonly transitionEnvelope: boolean;
  };
};

const MOTION_PRIORITY: ReadonlyArray<readonly [string, string]> = [
  ["cinematic", "CinematicOpening"],
  ["product", "StoryEngineReveal"],
  ["network", "NetworkExplainer"],
  ["code", "RadioWaveform"],
  ["radio", "RadioWaveform"],
  ["timeline", "IncidentTimeline"],
  ["documents", "EvidenceBoard"],
  ["evidence", "EvidenceBoard"],
  ["map", "OutageMap"],
  ["witness", "BilingualCaptions"],
] as const;

const presentationFor = (cue: SemanticCue): string => {
  if (cue.signals.intents.includes("transition")) return "Boundary";
  if (
    cue.signals.dialogue &&
    cue.signals.captions &&
    cue.signals.intents.includes("witness") &&
    !cue.signals.intents.includes("code")
  ) {
    return "BilingualCaptions";
  }
  for (const [intent, primitive] of MOTION_PRIORITY) {
    if (cue.signals.intents.includes(intent)) return primitive;
  }
  return "SignalPulse";
};

const motionPrimitivesFor = (cue: SemanticCue): ReadonlyArray<string> => {
  const primitives = new Set<string>([
    "SignalPulse",
    "MediaKinetics",
    "MotionAudioSystem",
  ]);
  for (const [intent, primitive] of MOTION_PRIORITY) {
    if (cue.signals.intents.includes(intent)) primitives.add(primitive);
  }
  if (cue.signals.dialogue || cue.signals.captions) {
    primitives.add("BilingualCaptions");
  }
  return [...primitives];
};

export const resolveLayeredSceneRecipe = (
  cue: SemanticCue,
): LayeredSceneRecipe => {
  const {signals} = cue;
  if (
    !cue.id ||
    !Number.isInteger(cue.section_index) ||
    !Number.isInteger(cue.from) ||
    !Number.isInteger(cue.to) ||
    cue.to < cue.from ||
    !Number.isInteger(signals.energy) ||
    signals.energy < 0 ||
    signals.energy > 3 ||
    signals.dialogue !== signals.captions && signals.handoff === "waveform"
  ) {
    throw new Error("Invalid approved orchestration signals");
  }
  const motionLayers = motionPrimitivesFor(cue).map((primitive, index) => ({
    primitive,
    zIndex: primitive === "SignalPulse" ? 60 : primitive === "MotionAudioSystem" ? 0 : 40 + index,
    blend: primitive === "SignalPulse" || primitive === "RadioWaveform" ? "screen" as const : "normal" as const,
    intensity: Number(Math.min(1, 0.28 + signals.energy * 0.22).toFixed(2)),
    safeZone: primitive === "SignalPulse" ? "full-title-safe" as const : "center-critical" as const,
  }));
  const boundary = signals.intents.includes("transition");
  const transformCarry = signals.handoff.includes("_to_");
  return {
    id: cue.id,
    sectionIndex: cue.section_index,
    from: cue.from,
    to: cue.to,
    durationInFrames: cue.to - cue.from + 1,
    signals,
    narrativeFunction: cue.narrative_function ?? null,
    requestedCapabilities: [...(cue.requested_capability_ids ?? [])],
    media: {
      primary: "approved-overlap",
      secondary: "approved-overlap-optional",
      primaryZIndex: 10,
      secondaryZIndex: 14,
      secondaryBlend: "screen",
      secondaryIntensity: Number((0.14 + signals.energy * 0.08).toFixed(2)),
    },
    motionLayers,
    presentation: presentationFor(cue),
    caption: {
      mode: signals.captions
        ? signals.dialogue ? "bilingual-word-emphasis" : "approved"
        : "none",
      zIndex: 90,
      safeZone: "center-critical",
    },
    camera: {
      mode: signals.energy === 0
        ? "locked"
        : signals.dialogue
          ? "reactive-push"
          : signals.intents.some((intent) => ["map", "evidence", "timeline"].includes(intent))
            ? "investigative-drift"
            : "slow-push",
      intensity: Number((signals.energy / 3).toFixed(3)),
    },
    transition: {
      mode: boundary ? (signals.energy === 0 ? "dip" : "fade") : transformCarry ? "transform-carry" : "none",
      carry: signals.handoff,
      overlapFrames: 0,
    },
    audio: {
      bedGain: signals.handoff === "silence" ? 0 : 0.22,
      dialogueDuck: signals.dialogue ? 0.24 : 1,
      pulse: signals.handoff !== "silence",
      dataClicks: signals.intents.some((intent) => ["map", "evidence", "timeline", "code"].includes(intent)),
      silenceDrop: signals.handoff === "silence",
      transitionEnvelope: boundary || transformCarry,
    },
  };
};

export const SHOWCASE_ORCHESTRATION_PLAN = orchestrationPlan;

export const resolveShowcaseRecipes = (): ReadonlyArray<LayeredSceneRecipe> => {
  if (
    orchestrationPlan.version !== ORCHESTRATION_CONTRACT_VERSION ||
    orchestrationPlan.decision_rules_version !== DECISION_RULES_VERSION ||
    orchestrationPlan.fps !== 24 ||
    orchestrationPlan.width !== 1920 ||
    orchestrationPlan.height !== 1080 ||
    orchestrationPlan.total_frames !== 7200
  ) {
    throw new Error("StoryEngine layered orchestration identity changed");
  }
  let expectedFrame = 0;
  return orchestrationPlan.cues.map((raw) => {
    const cue = raw as SemanticCue;
    if (cue.from !== expectedFrame) {
      throw new Error("StoryEngine layered cues are not contiguous");
    }
    expectedFrame = cue.to + 1;
    const recipe = resolveLayeredSceneRecipe(cue);
    if (recipe.motionLayers.length < 2) {
      throw new Error("StoryEngine scene recipe is not layered");
    }
    return recipe;
  }).map((recipe, index, all) => {
    if (index === all.length - 1 && recipe.to !== 7199) {
      throw new Error("StoryEngine layered cues do not fill the film");
    }
    return recipe;
  });
};
