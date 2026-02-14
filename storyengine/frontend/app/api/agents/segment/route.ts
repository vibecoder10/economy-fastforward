import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { decrypt } from "@/lib/crypto";

const MODEL = "claude-sonnet-4-5-20250929";

export async function POST(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;

  // Get the user's Anthropic key
  const keys = await prisma.apiKeys.findUnique({ where: { userId } });
  if (!keys?.anthropicKey) {
    return NextResponse.json(
      { error: "Anthropic API key not configured. Go to Settings > API Keys." },
      { status: 400 }
    );
  }

  const apiKey = decrypt(keys.anthropicKey);

  const { sceneText, maxSegmentDuration = 10 } = await request.json();
  if (!sceneText || typeof sceneText !== "string") {
    return NextResponse.json(
      { error: "sceneText is required" },
      { status: 400 }
    );
  }

  // --- STEP 1: Segment the narration into visual concepts ---
  const segmentSystemPrompt = `You are an expert video editor segmenting narration for AI-animated documentary videos.

YOUR TASK: Analyze the scene narration and group sentences into VISUAL SEGMENTS.

RULES FOR SEGMENTATION:
1. Group sentences that share the SAME visual concept (keep together)
2. Create a NEW segment when the visual needs to SHIFT (new concept, new metaphor, new subject)
3. Each segment MUST be <=${maxSegmentDuration} seconds (this is a hard technical limit for AI video generation)
4. Short rhetorical phrases ("Different decade. Different industry.") should stay TOGETHER if same concept
5. Aim for 4-8 segments per scene (not too few, not too many)

DURATION CALCULATION:
- Average speaking rate: 173 words per minute
- Formula: (word_count / 173) * 60 = seconds
- Minimum 2 seconds per segment

OUTPUT FORMAT (JSON only, no markdown):
{
  "segments": [
    {
      "sentences": ["First sentence.", "Second sentence that continues same idea."],
      "visual_concept": "Brief description of what visual this represents",
      "estimated_duration": 8.5
    },
    {
      "sentences": ["New concept starts here."],
      "visual_concept": "Description of new visual",
      "estimated_duration": 4.2
    }
  ]
}

CRITICAL: If a segment would exceed ${maxSegmentDuration}s, you MUST split it even if same concept.
Add "(continued)" to visual_concept for split segments.`;

  const segmentUserPrompt = `Segment this scene narration into visual segments (max ${maxSegmentDuration}s each):

SCENE TEXT:
${sceneText}

Return JSON with segments array. Each segment groups sentences by visual concept.`;

  // ========== DEBUG: Log the segmentation API call ==========
  console.log("\n" + "=".repeat(80));
  console.log("SEGMENTATION API CALL — STEP 1: Analyze Visual Segments");
  console.log("=".repeat(80));
  console.log("\n--- SYSTEM PROMPT ---");
  console.log(segmentSystemPrompt);
  console.log("\n--- USER PROMPT ---");
  console.log(segmentUserPrompt);
  console.log("=".repeat(80));

  let segmentResponseText: string;
  try {
    const segmentRes = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: 2000,
        temperature: 1.0,
        system: segmentSystemPrompt,
        messages: [{ role: "user", content: segmentUserPrompt }],
      }),
    });

    const segmentData = await segmentRes.json();

    console.log("\n--- RAW API RESPONSE ---");
    console.log(JSON.stringify(segmentData, null, 2));
    console.log("=".repeat(80) + "\n");

    if (!segmentRes.ok) {
      return NextResponse.json(
        {
          error: `Anthropic API error: ${segmentData.error?.message || "Unknown error"}`,
          debug: { systemPrompt: segmentSystemPrompt, userPrompt: segmentUserPrompt, response: segmentData },
        },
        { status: 502 }
      );
    }

    const block = segmentData.content?.[0];
    if (!block || block.type !== "text") {
      return NextResponse.json(
        { error: "Unexpected response format from Anthropic", debug: segmentData },
        { status: 502 }
      );
    }

    segmentResponseText = block.text;
  } catch (err) {
    console.error("Segmentation API call failed:", err);
    return NextResponse.json(
      { error: `API call failed: ${err instanceof Error ? err.message : String(err)}` },
      { status: 502 }
    );
  }

  // Parse the segmentation response
  let segments: { sentences: string[]; visual_concept: string; estimated_duration: number }[];
  try {
    const cleaned = segmentResponseText.replace(/```json/g, "").replace(/```/g, "").trim();
    const parsed = JSON.parse(cleaned);
    segments = parsed.segments;
    if (!Array.isArray(segments) || segments.length === 0) {
      throw new Error("Empty or invalid segments array");
    }
  } catch (err) {
    return NextResponse.json(
      {
        error: `Failed to parse segmentation response: ${err instanceof Error ? err.message : String(err)}`,
        debug: { rawResponse: segmentResponseText },
      },
      { status: 502 }
    );
  }

  // --- STEP 2: Generate image prompts for each segment ---
  const results = [];
  let previousPrompt = "";

  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    const segmentText = seg.sentences.join(" ");
    const wordCount = segmentText.split(/\s+/).length;
    const duration = Math.max(2, Math.min(maxSegmentDuration, (wordCount / 173) * 60));

    const shotTypes = ["establishing", "detail", "reaction", "detail", "establishing", "transition"];
    const shotType = shotTypes[i % shotTypes.length];

    const promptSystemPrompt = `You are a visual director creating 3D editorial mannequin render image prompts.

=== STYLE: 3D EDITORIAL CONCEPTUAL RENDER ===
Monochromatic smooth matte gray mannequin figures (faceless) in photorealistic material environments.
Smooth continuous surfaces like a department store display mannequin. NOT clay, NOT stone, NOT action figures.

=== 5-LAYER ARCHITECTURE (120-150 words) ===
CRITICAL: Style engine prefix goes FIRST.

1. STYLE_ENGINE_PREFIX (always first): "3D editorial conceptual render, monochromatic smooth matte gray mannequin figures with no facial features, smooth continuous surfaces like a department store display mannequin, photorealistic materials and studio lighting."
2. SHOT TYPE: "${shotType}" shot
3. SCENE COMPOSITION: Physical environment with MATERIALS
4. FOCAL SUBJECT: Matte gray mannequin with BODY LANGUAGE
5. ENVIRONMENTAL STORYTELLING: Symbolic objects in materials
6. STYLE_ENGINE_SUFFIX + LIGHTING: "Clean studio lighting, shallow depth of field, matte and metallic material contrast, cinematic 16:9 composition, [warm vs cool contrast]"
7. TEXT RULE: "no text, no words, no labels, no signs, no readable text"

=== DO NOT ===
- Use paper-cut, illustration, or 2D references
- Include facial expressions (mannequins are faceless)
- Use double quotes (use single quotes)

=== DO ===
- Material vocabulary: chrome, steel, concrete, glass, leather
- Mannequin body language: shoulders slumped, arms reaching, head bowed
- Every word describes something VISUAL

OUTPUT: Return ONLY the prompt string (no JSON, no explanation).`;

    let continuityNote = "";
    if (previousPrompt) {
      continuityNote = `\n\nPREVIOUS IMAGE (maintain visual continuity):\n${previousPrompt.slice(0, 150)}...`;
    }

    const promptUserPrompt = `Create ONE image prompt for this segment using 3D mannequin render style:

SHOT TYPE: ${shotType}
SEGMENT ${i + 1} of ${segments.length}

NARRATION TEXT:
"${segmentText}"

VISUAL CONCEPT: ${seg.visual_concept}${continuityNote}

Generate 120-150 word prompt.
Start with style engine prefix, end with style engine suffix + lighting + text rule.`;

    // ========== DEBUG: Log each prompt generation call ==========
    console.log("\n" + "-".repeat(60));
    console.log(`IMAGE PROMPT API CALL — Segment ${i + 1}/${segments.length}`);
    console.log("-".repeat(60));
    console.log("\n--- SYSTEM PROMPT ---");
    console.log(promptSystemPrompt);
    console.log("\n--- USER PROMPT ---");
    console.log(promptUserPrompt);
    console.log("-".repeat(60));

    try {
      const promptRes = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "x-api-key": apiKey,
          "anthropic-version": "2023-06-01",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: MODEL,
          max_tokens: 500,
          temperature: 1.0,
          system: promptSystemPrompt,
          messages: [{ role: "user", content: promptUserPrompt }],
        }),
      });

      const promptData = await promptRes.json();

      console.log("\n--- RAW API RESPONSE ---");
      console.log(JSON.stringify(promptData, null, 2));
      console.log("-".repeat(60) + "\n");

      if (!promptRes.ok) {
        results.push({
          segmentIndex: i + 1,
          segmentText,
          durationSeconds: Math.round(duration * 10) / 10,
          visualConcept: seg.visual_concept,
          shotType,
          imagePrompt: `[ERROR: ${promptData.error?.message || "API call failed"}]`,
        });
        continue;
      }

      const block = promptData.content?.[0];
      const imagePrompt = block?.type === "text" ? block.text.trim() : "[No response]";

      results.push({
        segmentIndex: i + 1,
        segmentText,
        durationSeconds: Math.round(duration * 10) / 10,
        visualConcept: seg.visual_concept,
        shotType,
        imagePrompt,
      });

      previousPrompt = imagePrompt;
    } catch (err) {
      console.error(`Image prompt API call failed for segment ${i + 1}:`, err);
      results.push({
        segmentIndex: i + 1,
        segmentText,
        durationSeconds: Math.round(duration * 10) / 10,
        visualConcept: seg.visual_concept,
        shotType,
        imagePrompt: `[ERROR: ${err instanceof Error ? err.message : String(err)}]`,
      });
    }
  }

  return NextResponse.json({ segments: results });
}
