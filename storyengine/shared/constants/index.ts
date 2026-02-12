/**
 * StoryEngine v3 — Shared Constants
 */

// =============================================================================
// ECONOMY FASTFORWARD DEFAULT CHANNEL PROFILE
// =============================================================================

import type { ChannelProfile } from "../types";

export const ECONOMY_FASTFORWARD_PROFILE: Omit<
  ChannelProfile,
  "id" | "userId" | "createdAt" | "updatedAt"
> = {
  name: "Economy FastForward",
  isDefault: true,
  narrativeConfig: {
    defaultTone: "Serious and data-driven with moments of dark humor",
    defaultSceneCount: 20,
    narrativeFramework: "past_present_future",
    writerGuidance:
      "Write for spoken delivery. Short punchy sentences. Use concrete numbers and specific examples over abstract claims. Thread the thesis naturally — don't lecture. End each scene with a transition hook.",
    exampleScripts: [],
  },
  visualConfig: {
    stylePrefix:
      "3D editorial clay render, matte ceramic surfaces, studio-lit diorama composition, faceless smooth-skinned mannequin figures with subtle anatomical indentations, mixed material contrasts — brushed steel, frosted glass, worn leather, polished chrome.",
    styleSuffix:
      "Dramatic directional studio lighting, shallow depth of field, volumetric atmosphere, cinematic 16:9 composition. Material surfaces: concrete, chrome, brushed steel, glass, leather, velvet. Color grade: desaturated with selective warm accent lighting.",
    materialVocabulary: {
      premium: [
        "Polished chrome",
        "brushed gold",
        "marble",
        "leather",
        "velvet",
      ],
      institutional: [
        "Concrete",
        "steel",
        "frosted glass",
        "matte ceramic",
      ],
      decay: [
        "Rusted metal",
        "cracked concrete",
        "peeling paint",
        "oxidized copper",
      ],
      data: [
        "Glowing neon",
        "holographic surfaces",
        "digital grids",
        "fiber optic",
      ],
    },
    defaultShotRotation: [
      "establishing",
      "detail",
      "reaction",
      "detail",
      "establishing",
      "transition",
    ],
    wordBudget: { min: 120, max: 150 },
    textRules: { maxElements: 3, maxWordsPerElement: 3 },
    thumbnailStyle:
      "Comic editorial illustration via Nano Banana Pro — expressive faces, bold outlines, high saturation. Optimized for click at small sizes.",
  },
  visualAnchors: [
    {
      name: "The Digital Void",
      description:
        "Elements floating in vast dark space with glowing neon grids, binary rain, or floating text",
    },
    {
      name: "The Urban Exterior",
      description:
        "Futuristic city street at twilight, rainy sidewalks, glowing billboards, glass skyscrapers reflecting data",
    },
    {
      name: "The Data Landscape",
      description:
        "Massive physical server towers rising like monoliths in a desert, or infinite warehouse of glowing files",
    },
  ],
};

// =============================================================================
// NICHE TEMPLATES
// =============================================================================

export const NICHE_TEMPLATES: Record<
  string,
  { label: string; description: string }
> = {
  finance: {
    label: "Finance / Economics",
    description: "Data-driven analysis of markets, policy, and economic trends",
  },
  tech: {
    label: "Tech Review",
    description: "Product reviews, industry analysis, and technology trends",
  },
  history: {
    label: "History Documentary",
    description: "Historical narratives with archival and dramatic recreations",
  },
  news: {
    label: "News Commentary",
    description: "Breaking down current events with analysis and context",
  },
  education: {
    label: "Educational",
    description: "Explanatory content that makes complex topics accessible",
  },
  custom: {
    label: "Custom",
    description: "Start from scratch with your own configuration",
  },
};

// =============================================================================
// SCENE COUNT SCALING
// =============================================================================

export const SCENE_COUNT_MAP: Record<
  number,
  { sceneCount: number; intro: number; buildup: string; conclusion: string }
> = {
  5: { sceneCount: 4, intro: 1, buildup: "2", conclusion: "1" },
  10: { sceneCount: 8, intro: 2, buildup: "4-5", conclusion: "1-2" },
  15: { sceneCount: 15, intro: 3, buildup: "8-9", conclusion: "3-4" },
  20: { sceneCount: 20, intro: 4, buildup: "12", conclusion: "4" },
};

// =============================================================================
// WORDS PER SCENE
// =============================================================================

export const WORDS_PER_SCENE_MAP: Record<
  number,
  { totalWords: number; wordsPerScene: number }
> = {
  5: { totalWords: 750, wordsPerScene: 190 },
  10: { totalWords: 1500, wordsPerScene: 190 },
  15: { totalWords: 2250, wordsPerScene: 150 },
  20: { totalWords: 3000, wordsPerScene: 150 },
};

// =============================================================================
// API COST TABLE
// =============================================================================

export const API_COSTS = {
  beatSheet: 0.01,
  scriptPerScene: 0.02,
  imagePromptsPerScene: 0.01,
  sceneImage: 0.02,
  thumbnail: 0.03,
  animationClip: 0.1,
} as const;

// =============================================================================
// SUBSCRIPTION TIERS
// =============================================================================

export const SUBSCRIPTION_TIERS = {
  taste: {
    label: "Taste",
    price: 0,
    videosPerMonth: 0,
    imagesPerVideo: 2,
    animationsPerMonth: 0,
    features: ["Beat sheet + script only", "2 preview images"],
  },
  starter: {
    label: "Starter",
    price: 29,
    videosPerMonth: 3,
    imagesPerVideo: 120,
    animationsPerMonth: 0,
    features: [
      "Full image generation (120 imgs/video)",
      "Default style",
      "3 videos/month",
    ],
  },
  creator: {
    label: "Creator",
    price: 79,
    videosPerMonth: 10,
    imagesPerVideo: 120,
    animationsPerMonth: 30,
    features: [
      "Everything in Starter",
      "Bring Your Own Character",
      "Prompt editing",
      "10 videos/month",
      "30 animations/month",
    ],
  },
  studio: {
    label: "Studio",
    price: 199,
    videosPerMonth: Infinity,
    imagesPerVideo: 120,
    animationsPerMonth: Infinity,
    features: [
      "Everything in Creator",
      "Custom environment",
      "Unlimited videos",
      "Unlimited animation",
      "Priority queue",
    ],
  },
  byok: {
    label: "BYOK",
    price: 19,
    videosPerMonth: Infinity,
    imagesPerVideo: 120,
    animationsPerMonth: Infinity,
    features: [
      "Full platform access",
      "User provides ALL API keys",
      "Zero generation cost",
    ],
  },
} as const;
