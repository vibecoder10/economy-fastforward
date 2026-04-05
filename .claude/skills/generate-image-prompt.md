# Generate Image Prompt

Skill for crafting optimized image and video generation prompts for Nano Banana Pro, Grok Imagine, and Kie.ai API.

## Platform-Specific Formats

### Nano Banana Pro (JSON structured)
Used for keyframe images. Structured JSON with nested objects.

```json
{
  "model": "grok-imagine/text-to-image",
  "input": {
    "prompt": "<scene description in natural language, max 5000 chars>",
    "aspect_ratio": "16:9"
  }
}
```

**Prompt formula:** `[Subject + Action] + [Environment + Lighting] + [Camera + Composition]`

- Lead with the subject and what they're doing (~30-50 words)
- Add environment, mood, and lighting (~14 words)
- End with camera angle and art style (~10 words)
- Total sweet spot: 62-84 words
- Use concrete details ("electric blue and hot pink") over vague ("colorful")
- Positive constraints only — FLUX-based models ignore negations

### Grok Imagine (natural language prose)
Used for video bridges between keyframes. Director-style language.

```json
{
  "model": "grok-imagine/image-to-video",
  "input": {
    "image_urls": ["<keyframe image URL>"],
    "prompt": "<motion prompt in natural language>",
    "mode": "normal",
    "duration": 6,
    "resolution": "720p",
    "aspect_ratio": "16:9"
  }
}
```

**Motion prompt rules:**
- Use strong action verbs in the first 20-30 words
- Describe camera movement explicitly ("slow dolly forward", "crane up")
- Include audio/atmosphere cues
- No tag stacking — write like a film director
- Max 5000 characters, English only

## Supported Aspect Ratios
`2:3`, `3:2`, `1:1`, `16:9`, `9:16`

## Image Categories (17 types)
3D miniatures, architectural visualization, character portraits, cinematic stills,
concept art, documentary photography, editorial illustration, fashion photography,
food photography, landscape photography, macro photography, product photography,
sci-fi environments, sports photography, street photography, surreal art, wildlife photography

## Workflow
1. Identify imagery category from the 17 types above
2. Reference proven prompt patterns from the project's visual profile
3. Craft platform-specific prompt (JSON for Nano Banana, prose for Grok)
4. Present with aspect ratio recommendation and generation tips

## Advanced: Multi-Keyframe Sequences
For video production, generate a series of keyframe prompts that:
- Maintain visual consistency (same character descriptions, color palette, lighting)
- Vary shot types cyclically: wide -> medium -> close-up -> environmental
- Include transition guidance between keyframes
- Lock a "Continuity Bible" before generating any prompts

## Cross-Platform Workflow
1. Generate keyframe images with Nano Banana Pro (text-to-image)
2. Generate video bridges with Grok Imagine (image-to-video)
3. Assemble clips in sequence order
