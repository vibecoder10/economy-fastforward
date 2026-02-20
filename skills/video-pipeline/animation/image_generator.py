"""Image Prompt Generator for Animation Pipeline.

Generates detailed image prompts using the 3D mannequin render style
with protagonist glow tracking.
"""

import os
import json
from typing import Optional
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '.env'))

# 3D Mannequin Render Style Constants (v3 - smooth mannequin, NOT clay)
STYLE_ENGINE_PREFIX = (
    "3D editorial conceptual render, monochromatic smooth matte gray mannequin figures "
    "with no facial features, smooth continuous surfaces like a department store display mannequin, "
    "photorealistic materials and studio lighting."
)

# Negative prompt additions for image generation
NEGATIVE_PROMPT_ADDITIONS = (
    "clay texture, rough surface, stone, concrete, action figure, ball joints, "
    "mechanical joints, panel lines, robot, matte clay, rough matte, porous surface"
)

STYLE_ENGINE_SUFFIX = (
    "Clean studio lighting, shallow depth of field, matte and metallic material "
    "contrast, cinematic 16:9 composition"
)

# Protagonist glow descriptions by state
GLOW_DESCRIPTIONS = {
    (90, 100): "brilliant golden-amber light radiating outward, intense inner fire visible, warmth flooding the space around them",
    (70, 89): "steady warm amber glow emanating from within, soft light pooling at their feet, gentle warmth visible in the air",
    (50, 69): "moderate amber glow, light flickering slightly, warmth still present but wavering",
    (30, 49): "dim amber light, noticeably reduced, glow struggling to maintain intensity",
    (15, 29): "faint ember glow, barely visible, warmth nearly extinguished, cold encroaching",
    (0, 14): "glow nearly invisible, only faint ember deep within, surrounded by cold",
}

# Chrome entity description (the antagonist)
CHROME_ENTITY = (
    "sleek chrome robotic entity with reflective surfaces, no facial features, "
    "fluid mechanical joints, cold blue-white reflections"
)

IMAGE_PROMPT_SYSTEM = """You are a visual director creating 3D editorial mannequin render image prompts.

=== STYLE: 3D EDITORIAL CONCEPTUAL RENDER ===
Monochromatic smooth matte gray mannequin figures (faceless) in photorealistic material environments.
CRITICAL: The style engine prefix MUST go at the BEGINNING of every prompt.

=== PROTAGONIST ===
A smooth matte gray mannequin figure with no facial features.
Smooth continuous surfaces like a department store display mannequin.
NOT clay, NOT stone, NOT an action figure, NOT a robot.
UNIQUE TRAIT: Has an inner glow (described separately per scene).
This glow is their sense of purpose/meaning - it changes across the narrative.

=== CHROME ENTITY (antagonist) ===
Sleek chrome robotic entity with reflective surfaces, fluid mechanical joints.
Cold, efficient, reflecting distorted images of the world around it.

=== PROMPT STRUCTURE (120-150 words) ===
1. STYLE_ENGINE_PREFIX (always first)
2. SHOT TYPE: Based on camera_direction
3. SCENE COMPOSITION: Factory/workstation environment with materials
4. PROTAGONIST: Matte gray mannequin WITH GLOW DESCRIPTION
5. OTHER ELEMENTS: Chrome entities, gray droids, particles, etc.
6. LIGHTING: Based on color_temperature
7. STYLE_ENGINE_SUFFIX
8. "no text, no words, no labels"

=== MATERIAL VOCABULARY ===
Premium: polished chrome, brushed gold, glass, warm spotlight, copper
Industrial: brushed steel, concrete, matte black, industrial pipes
Cold: chrome, reflective metal, blue-white fluorescent, glass panels

=== DO NOT ===
- Include any facial expressions (mannequins are faceless)
- Use paper-cut or 2D illustration styles
- Add text to images
- Forget the protagonist's glow state"""


class ImagePromptGenerator:
    """Generates image prompts for animation scenes."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.client = Anthropic(api_key=self.api_key)

    def get_glow_description(self, glow_state: int, glow_behavior: str) -> str:
        """Get the glow description for a given state."""
        for (low, high), desc in GLOW_DESCRIPTIONS.items():
            if low <= glow_state <= high:
                behavior_mod = ""
                if glow_behavior == "flickering":
                    behavior_mod = "flickering unpredictably, "
                elif glow_behavior == "dimming":
                    behavior_mod = "slowly fading, "
                elif glow_behavior == "pulsing":
                    behavior_mod = "pulsing with building intensity, "
                elif glow_behavior == "surging":
                    behavior_mod = "surging with explosive power, "
                return f"{behavior_mod}{desc}"
        return "faint glow barely visible"

    def get_lighting_description(self, color_temperature: str) -> str:
        """Get lighting description based on color temperature."""
        if color_temperature == "warm":
            return "warm amber studio lighting, golden highlights, soft shadows"
        elif color_temperature == "neutral":
            return "balanced white studio lighting, subtle warm-cool mix"
        elif color_temperature == "cool":
            return "cool blue-tinted lighting, steel reflections, distant warmth"
        elif color_temperature == "cold":
            return "cold blue-white fluorescent lighting, chrome reflections, no warmth"
        return "balanced studio lighting"

    def get_camera_shot_prefix(self, camera_direction: str) -> str:
        """Get shot type prefix based on camera direction."""
        prefixes = {
            "push_in": "Medium shot slowly pushing forward toward",
            "pull_back": "Wide shot pulling back to reveal",
            "pan_lr": "Wide tracking shot panning left to right across",
            "pan_rl": "Wide tracking shot panning right to left across",
            "overhead": "Overhead birds-eye view of",
            "eye_level": "Eye-level medium shot of",
            "low_angle": "Low angle shot looking up at",
            "static": "Static wide shot of",
        }
        return prefixes.get(camera_direction, "Medium shot of")

    async def generate_image_prompt(self, scene: dict, creative_direction: str) -> str:
        """Generate an image prompt for a scene.

        Args:
            scene: Scene dict with all parameters
            creative_direction: Overall creative direction for context

        Returns:
            Complete image generation prompt
        """
        glow_state = scene.get("glow_state", 70)
        glow_behavior = scene.get("glow_behavior", "steady")
        color_temp = scene.get("color_temperature", "neutral")
        camera = scene.get("camera_direction", "eye_level")

        glow_desc = self.get_glow_description(glow_state, glow_behavior)
        lighting_desc = self.get_lighting_description(color_temp)
        shot_prefix = self.get_camera_shot_prefix(camera)

        user_prompt = f"""Generate an image prompt for this scene.

=== SCENE {scene.get('scene_order')} ===
Narrative Beat: {scene.get('narrative_beat')}
Voiceover: "{scene.get('voiceover_text')}"
Motion Description: {scene.get('motion_description')}
Key Visual Elements: {', '.join(scene.get('key_visual_elements', []))}

=== PROTAGONIST GLOW STATE ===
Intensity: {glow_state}%
Behavior: {glow_behavior}
Description: {glow_desc}

=== TECHNICAL ===
Camera: {camera} → Use shot prefix: "{shot_prefix}..."
Lighting: {color_temp} → {lighting_desc}

=== CREATIVE DIRECTION (for context) ===
{creative_direction[:500]}...

Generate a 120-150 word image prompt.
Start with: "{STYLE_ENGINE_PREFIX}"
End with: "{STYLE_ENGINE_SUFFIX}, {lighting_desc}, no text, no words, no labels\""""

        response = self.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=500,
            temperature=0.7,
            system=IMAGE_PROMPT_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )

        return response.content[0].text.strip()

    async def generate_end_image_prompt(self, scene: dict, start_prompt: str) -> str:
        """Generate an end image prompt showing WHAT HAPPENED during the 8-second animation.

        CRITICAL FRAME SEPARATION RULE:
        The start_image and end_image must show VISUALLY DISTINCT moments separated
        by clear physical change. Veo interpolates between these frames over 8 seconds.
        If they look too similar, the animation will be static and boring.

        The difference must be answerable: "What HAPPENED in this 8 seconds?"
        If the answer is just a camera move, the frames are too similar.

        Args:
            scene: Scene dict with motion_description, narrative_beat, camera_direction
            start_prompt: The start image prompt for context

        Returns:
            End image prompt showing clear visual change from start
        """
        camera = scene.get("camera_direction", "static")
        motion = scene.get("motion_description", "")
        narrative_beat = scene.get("narrative_beat", "")
        glow_state = scene.get("glow_state", 70)
        glow_behavior = scene.get("glow_behavior", "steady")
        scene_type = scene.get("scene_type", "animated")

        glow_desc = self.get_glow_description(glow_state, glow_behavior)

        system = """You are creating an END FRAME for an 8-second animation.

=== THE 8-SECOND RULE (CRITICAL - ENFORCED) ===
START AND END FRAMES MUST SHOW TWO DIFFERENT MOMENTS IN TIME.

Think of it like this: if you paused a movie at second 0 and second 8,
you would see two DIFFERENT still photographs. Not the same photo from
a different angle. Not the same photo zoomed in. Two different moments
where the WORLD HAS CHANGED.

Before writing prompts, describe what physically happens in the scene
in ONE SENTENCE using an ACTION VERB. That action is what separates
the start frame from the end frame.

=== PROTAGONIST STYLE (MANDATORY) ===
Smooth matte gray mannequin figure — like a high-end department store display mannequin.
Featureless face with only subtle indentations. Smooth continuous body surfaces.
NOT clay, NOT stone, NOT an action figure, NOT a robot.
Golden amber glow emanates from cracked chest.

=== GOOD FRAME SEPARATION EXAMPLES ===
- Start: Protagonist standing at workstation, hands assembling components, glow steady at 70%
  End: Protagonist has stopped working, hands frozen mid-motion, head turned toward a white light flooding in from the right, glow flickering to 40%
  What happened: "The protagonist notices something and stops working"

- Start: Wide shot of factory floor, protagonist at center workstation, other mannequins at distant stations
  End: Same factory floor but the distant workstations are empty, protagonist is the only one left, glow brightened to 90%
  What happened: "The other workers disappeared, leaving the protagonist alone"

- Start: Chrome entity at doorway, silhouetted by white light
  End: Chrome entity now standing IN the room, protagonist's glow dimmer, floor reflecting chrome
  What happened: "The chrome entity entered the room"

- Start: Protagonist hunched, glow nearly extinguished, dark frame
  End: Protagonist standing tall, BLINDING amber light filling entire frame, arms raised
  What happened: "The protagonist's glow surges with refusal to dissolve"

=== BAD FRAME SEPARATION (produces dead animation - NEVER DO THESE) ===
- Same scene from different angle (this is a camera move, not story)
- Same scene zoomed in/out (REWRITE - nothing happened)
- Same characters with "different lighting" (REWRITE - too subtle)
- Same composition with "subtle changes" (REWRITE - Veo won't animate this)
- Start and End are nearly identical (CRITICAL FAILURE - zero animation)

=== VALIDATION TEST ===
After generating both prompts, answer: "What HAPPENED in these 8 seconds?"
If the answer is just a camera movement, REWRITE.
Something in the SCENE must physically change.

=== YOUR OUTPUT FORMAT ===
1. First line: "ACTION: [verb phrase describing what happens]"
2. Then: The complete end frame prompt in same smooth mannequin style

The end frame must be a DIFFERENT PHOTOGRAPH showing the RESULT of the action."""

        user_prompt = f"""Create the END frame for this 8-second animation.

=== START FRAME (second 0) ===
{start_prompt}

=== WHAT HAPPENS IN THIS SCENE ===
Narrative Beat: {narrative_beat}
Motion Description: {motion}

=== GLOW STATE ===
{glow_state}% ({glow_behavior}) - {glow_desc}

=== YOUR TASK ===
Step 1: Write ONE SENTENCE describing what ACTION happens in 8 seconds.
        Use a strong ACTION VERB (walks, dissolves, dims, erupts, turns, appears, etc.)

Step 2: Write the END frame prompt showing the RESULT of that action.
        This must look like a DIFFERENT PHOTOGRAPH, not the same scene.

=== OUTPUT FORMAT ===
ACTION: [your one-sentence action description]

[Complete end frame prompt in same 3D smooth mannequin render style]"""

        response = self.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=600,
            temperature=0.7,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )

        result = response.content[0].text.strip()

        # Parse out the ACTION line and return just the prompt
        lines = result.split("\n")
        action_line = None
        prompt_lines = []
        found_action = False

        for line in lines:
            if line.startswith("ACTION:"):
                action_line = line
                found_action = True
            elif found_action and line.strip():
                prompt_lines.append(line)

        # Store the action for logging
        if action_line:
            print(f"      ACTION: {action_line.replace('ACTION:', '').strip()}")

        # Return just the prompt part
        return "\n".join(prompt_lines).strip() if prompt_lines else result

    async def generate_prompts_for_scenes(
        self,
        scenes: list,
        creative_direction: str,
        include_end_prompts: bool = False,
    ) -> list:
        """Generate image prompts for all scenes.

        Args:
            scenes: List of scene dicts
            creative_direction: Overall creative direction
            include_end_prompts: If True, also generate end_image_prompt

        Returns:
            Scenes with added start_image_prompt (and optionally end_image_prompt)
        """
        for i, scene in enumerate(scenes):
            print(f"  Generating prompt for Scene {scene.get('scene_order')}...")
            prompt = await self.generate_image_prompt(scene, creative_direction)
            scene["start_image_prompt"] = prompt
            print(f"    ✅ Start: {len(prompt.split())} words")

            if include_end_prompts:
                end_prompt = await self.generate_end_image_prompt(scene, prompt)
                scene["end_image_prompt"] = end_prompt
                print(f"    ✅ End: {len(end_prompt.split())} words")

        return scenes


async def main():
    """Test the image prompt generator."""
    generator = ImagePromptGenerator()

    # Test scene
    test_scene = {
        "scene_order": 14,
        "narrative_beat": "The surge - refusal to dissolve",
        "voiceover_text": "You refuse to dissolve.",
        "camera_direction": "push_in",
        "glow_state": 100,
        "glow_behavior": "surging",
        "color_temperature": "warm",
        "motion_description": "Protagonist's glow explodes outward in amber surge, washing entire frame",
        "key_visual_elements": ["glow explosion", "amber light surge", "protagonist stepping forward"],
    }

    creative_direction = """A gold-glowing smooth gray mannequin protagonist walks into a factory where gray droids work identical stations. A sleek chrome entity arrives and begins silently replacing workers one by one. The droids dissolve into particles as they're displaced — no violence, just quiet erasure. Our protagonist watches, glow dimming as the wave approaches, until the moment of their own replacement arrives. Instead of dissolving, their glow surges — a refusal to disappear."""

    print("🎨 Generating test prompt...")
    prompt = await generator.generate_image_prompt(test_scene, creative_direction)
    print(f"\n{prompt}")
    print(f"\nWord count: {len(prompt.split())}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
