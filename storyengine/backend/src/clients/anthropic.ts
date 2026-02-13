/**
 * Anthropic Claude API Client for StoryEngine
 *
 * Ported from: skills/video-pipeline/clients/anthropic_client.py
 * All agent prompts read from ChannelProfile, not hardcoded strings.
 */

import Anthropic from "anthropic";
import type { ChannelProfile } from "../../shared/types";

const DEFAULT_MODEL = "claude-sonnet-4-5-20250929";

export class AnthropicClient {
  private client: Anthropic;

  constructor(apiKey?: string) {
    const key = apiKey || process.env.ANTHROPIC_API_KEY;
    if (!key) {
      throw new Error("ANTHROPIC_API_KEY not found");
    }
    this.client = new Anthropic({ apiKey: key });
  }

  async generate(
    prompt: string,
    systemPrompt: string = "",
    model: string = DEFAULT_MODEL,
    maxTokens: number = 4096,
    temperature: number = 1.0
  ): Promise<string> {
    const response = await this.client.messages.create({
      model,
      max_tokens: maxTokens,
      temperature,
      ...(systemPrompt ? { system: systemPrompt } : {}),
      messages: [{ role: "user", content: prompt }],
    });

    const block = response.content[0];
    if (block.type === "text") {
      return block.text;
    }
    throw new Error("Unexpected response type from Anthropic API");
  }

  /**
   * Generate a beat sheet from project inputs.
   * System prompt reads from Channel Profile — never hardcoded.
   */
  async generateBeatSheet(
    profile: ChannelProfile,
    inputs: {
      title: string;
      angle: string;
      thesis: string;
      pastContext?: string;
      futurePrediction?: string;
      openingHook?: string;
      sceneCount: number;
    }
  ): Promise<{ script_outline: { scene_number: number; beat: string }[] }> {
    const { narrativeConfig } = profile;

    const systemPrompt = `You are a Master Storyteller and Narrative Architect.
Your task is to create a ${inputs.sceneCount}-scene Beat Sheet for documentary videos.

NARRATIVE FRAMEWORK: ${narrativeConfig.narrativeFramework}
WRITER GUIDANCE: ${narrativeConfig.writerGuidance}

INSTRUCTIONS:
Create an outline for exactly ${inputs.sceneCount} scenes following this narrative arc:
1. INTRO: Introduce the hook, the stakes, and the main question.
2. BUILD-UP: Escalate tension. Reveal the Past Context and Modern Shift. Show cause-and-effect.
3. CONCLUSION: Resolve the conflict with the Future Prediction. Echo the intro hook.

CONSTRAINTS:
- Do NOT write the full script yet.
- Each beat should be a 1-sentence summary of what happens in that scene.
- Output raw JSON only. No markdown formatting.

REQUIRED OUTPUT FORMAT:
{
  "script_outline": [
    { "scene_number": 1, "beat": "Description of scene 1..." },
    { "scene_number": 2, "beat": "Description of scene 2..." }
  ]
}`;

    const userPrompt = `Create a ${inputs.sceneCount}-scene Beat Sheet for a documentary video titled: "${inputs.title}".

CONTEXT:
Here is the core Narrative DNA (Past/Present/Future):
Past Context: ${inputs.pastContext || "Derive from the angle below"}
Present Parallel: ${inputs.angle}
Future Prediction: ${inputs.futurePrediction || "Derive from the thesis below"}

Here is the REQUIRED Opening Hook (Use this for Scene 1):
"${inputs.openingHook || "Generate a compelling hook based on the angle"}"

Here is the Writer Guidance/Tone:
"${inputs.thesis}. Tone: ${narrativeConfig.defaultTone}"`;

    const response = await this.generate(
      userPrompt,
      systemPrompt,
      DEFAULT_MODEL // Always Sonnet for automated pipeline
    );

    const cleaned = response.replace(/```json/g, "").replace(/```/g, "").trim();
    return JSON.parse(cleaned);
  }

  /**
   * Write script narration for a single scene.
   * Uses Channel Profile for tone and word targets.
   */
  async writeScene(
    profile: ChannelProfile,
    sceneNumber: number,
    sceneBeat: string,
    videoTitle: string,
    wordsPerScene: number
  ): Promise<string> {
    const { narrativeConfig } = profile;

    const systemPrompt = `You are the Voiceover Scriptwriter for a high-retention YouTube documentary.

STYLE GUIDE:
- LENGTH: Strictly ${wordsPerScene - 10}-${wordsPerScene + 10} words.
- TONE: ${narrativeConfig.defaultTone}
- FORMAT: Spoken word only. No "Scene 1" labels. No "Camera pans".
- CONTINUITY: If this is Scene 1, start with a hook. End each scene with a transition hook to the next scene.

ADDITIONAL CONSTRAINTS:
- Write for spoken delivery — short sentences, natural rhythm
- Thread the thesis naturally — don't lecture
${narrativeConfig.writerGuidance}

INSTRUCTION:
Write the script for the scene provided. Return ONLY the narration text.`;

    const userPrompt = `Write the spoken narration for SCENE ${sceneNumber} ONLY.

CONTEXT:
Video Title: "${videoTitle}"
Current Scene Goal: "${sceneBeat}"`;

    return this.generate(userPrompt, systemPrompt, DEFAULT_MODEL);
  }

  /**
   * Generate image prompts for a scene.
   * Style engine reads from Channel Profile visual config.
   */
  async generateImagePrompts(
    profile: ChannelProfile,
    sceneNumber: number,
    sceneText: string,
    videoTitle: string
  ): Promise<{ scene_images: { image_number: number; shot_type: string; prompt: string }[] }> {
    const { visualConfig } = profile;

    const systemPrompt = `You are an expert image prompt creator for a video production platform.
Your task is to create 6 sequential, cohesive image prompts for each scene.

SHOT TYPE ROTATION (REQUIRED):
Every set of 6 images must cycle through visual scales:
1. ESTABLISHING — wide shot, environmental, sets the world
2. DETAIL — close-up on specific proof point or object
3. REACTION — character responding or environmental mood shift
4. DETAIL — different angle, different proof point
5. ESTABLISHING or TRANSITION — wider context or visual bridge
6. TRANSITION — visual handoff to the next scene's world

PROMPT ARCHITECTURE (5-layer, execute in order):
Layer 1 — STYLE PREFIX: ${visualConfig.stylePrefix}
Layer 2 — SHOT TYPE: From rotation above
Layer 3 — SCENE CONTEXT: From beat sheet + script narration
Layer 4 — CHARACTER BLOCK: If character provided, inject here
Layer 5 — TECHNICAL: aspect ratio, lighting, composition, material vocabulary

WORD BUDGET: ${visualConfig.wordBudget.min}-${visualConfig.wordBudget.max} words per image prompt.
ASPECT RATIO: 16:9 landscape always.
TEXT RULES: Maximum ${visualConfig.textRules.maxElements} text elements per image. Maximum ${visualConfig.textRules.maxWordsPerElement} words per element.
Every text element MUST specify a material surface.

STYLE SUFFIX: ${visualConfig.styleSuffix}

OUTPUT FORMAT — raw JSON only:
{
  "scene_images": [
    {
      "image_number": 1,
      "shot_type": "establishing",
      "prompt": "Full prompt text..."
    }
  ]
}`;

    const userPrompt = `Create 6 image prompts for Scene ${sceneNumber}:

Video Title: "${videoTitle}"

SCENE TEXT:
${sceneText}

Generate exactly 6 prompts, each ${visualConfig.wordBudget.min}-${visualConfig.wordBudget.max} words.
Every prompt MUST start with the style prefix.`;

    const response = await this.generate(
      userPrompt,
      systemPrompt,
      DEFAULT_MODEL,
      4000
    );

    const cleaned = response.replace(/```json/g, "").replace(/```/g, "").trim();
    return JSON.parse(cleaned);
  }
}
