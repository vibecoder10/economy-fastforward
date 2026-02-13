/**
 * StoryEngine v3 — Shared Types
 *
 * All type definitions used across frontend and backend.
 */

// =============================================================================
// CHANNEL PROFILE
// =============================================================================

export type NarrativeFramework =
  | "past_present_future"
  | "problem_solution"
  | "chronological"
  | "custom";

export interface NarrativeConfig {
  defaultTone: string;
  defaultSceneCount: number;
  narrativeFramework: NarrativeFramework;
  customFrameworkPrompt?: string;
  writerGuidance: string;
  exampleScripts?: string[];
}

export interface VisualConfig {
  stylePrefix: string;
  styleSuffix: string;
  materialVocabulary: Record<string, string[]>;
  defaultShotRotation: string[];
  wordBudget: { min: number; max: number };
  textRules: { maxElements: number; maxWordsPerElement: number };
  thumbnailStyle: string;
}

export interface VisualAnchor {
  name: string;
  description: string;
}

export interface DefaultCharacter {
  characterBlock: string;
  referenceImageUrl?: string;
}

export interface DefaultEnvironment {
  environmentProfile: Record<string, unknown>;
  customStylePrefix?: string;
  customStyleSuffix?: string;
}

export interface ChannelProfile {
  id: string;
  userId: string;
  name: string;
  isDefault: boolean;
  narrativeConfig: NarrativeConfig;
  visualConfig: VisualConfig;
  visualAnchors: VisualAnchor[];
  defaultCharacter?: DefaultCharacter;
  defaultEnvironment?: DefaultEnvironment;
  createdAt: Date;
  updatedAt: Date;
}

// =============================================================================
// USER & AUTH
// =============================================================================

export type SubscriptionTier = "taste" | "starter" | "creator" | "studio" | "byok";

export interface User {
  id: string;
  email: string;
  name?: string;
  image?: string;
  subscriptionTier: SubscriptionTier;
  createdAt: Date;
  updatedAt: Date;
}

export interface ApiKeys {
  id: string;
  userId: string;
  anthropicKey?: string;
  kieAiKey?: string;
  elevenLabsKey?: string;
  updatedAt: Date;
}

// =============================================================================
// PROJECT
// =============================================================================

export type ProjectStatus =
  | "input"
  | "beat_sheet"
  | "script"
  | "visuals"
  | "animation"
  | "complete";

export interface BeatSheetScene {
  sceneNumber: number;
  beat: string;
  section: "intro" | "buildup" | "conclusion";
}

export interface ScriptScene {
  sceneNumber: number;
  beat: string;
  narration: string;
  wordCount: number;
  estimatedDuration: number;
}

export type ShotType =
  | "establishing"
  | "reaction"
  | "detail"
  | "transition";

export type ImageStatus = "generating" | "complete" | "failed";
export type AnimationStatus = "none" | "queued" | "generating" | "complete";

export interface GeneratedImage {
  id: string;
  prompt: string;
  imageUrl: string;
  seed?: number;
  shotType: ShotType;
  status: ImageStatus;
  animationStatus?: AnimationStatus;
  animationUrl?: string;
}

export interface VisualScene {
  sceneNumber: number;
  images: GeneratedImage[];
}

export interface AnimationClip {
  id: string;
  sourceImageId: string;
  motionPrompt: string;
  videoUrl: string;
  duration: number;
  status: AnimationStatus;
}

export interface Project {
  id: string;
  userId: string;
  channelProfileId: string;
  status: ProjectStatus;

  // Module 2 inputs
  title: string;
  angle: string;
  thesis: string;
  pastContext?: string;
  futurePrediction?: string;
  openingHook?: string;
  tone: string;
  targetLength: number;
  characterRef?: string;
  environmentProfile?: Record<string, unknown>;

  // Module 3 outputs
  beatSheet: BeatSheetScene[];
  script: ScriptScene[];

  // Module 4 outputs
  scenes: VisualScene[];

  // Module 7 outputs
  animations: AnimationClip[];

  createdAt: Date;
  updatedAt: Date;
}

// =============================================================================
// USAGE METERING
// =============================================================================

export type UsageEventType =
  | "image_gen"
  | "animation_gen"
  | "script_gen"
  | "thumbnail_gen";

export interface UsageEvent {
  userId: string;
  projectId: string;
  eventType: UsageEventType;
  model: string;
  cost: number;
  timestamp: Date;
}
