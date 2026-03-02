"""Scene Planner for Animation Pipeline.

Uses Claude Sonnet to break scripts into scenes with:
- Glow arc tracking (protagonist's inner light)
- ALL SCENES ANIMATED (Veo 3.1 video generation)
- Camera direction assignments
- Color temperature progression
"""

import os
import json
from typing import Optional
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

# Protagonist glow prompt fragment (locked constant)
# STYLE: Anonymous human figure, face obscured by shadow/silhouette
PROTAGONIST_GLOW_FRAGMENT = (
    "an anonymous human figure with face completely obscured by deep shadow, "
    "real clothing and skin texture, documentary photography where identity is protected, "
    "emanating a soft {glow_color} inner glow at {glow_intensity}% intensity, "
    "glow behavior: {glow_behavior}"
)

SCENE_PLANNER_SYSTEM = """You are a visual director planning scenes for an AI-animated documentary video.

Your job: Break the script into 12-15 scenes, each with specific visual and technical parameters.

=== EVERY SCENE IS ANIMATED ===
ALL scenes use Veo 3.1 video generation. No static images, no ken_burns.
Every scene must have clear visual change between start and end frames.

For action scenes: characters move, objects appear/disappear, destruction occurs, dramatic reveals.

For quiet/contemplative scenes, use ENVIRONMENTAL MOTION:
- Glow intensity changes visibly between frames
- Particles drift, settle, or reverse direction
- Light sources shift color temperature
- Fog/smoke/dust moves through the scene
- Cracks form or spread in surfaces
- Reflections change on chrome surfaces
- Shadows lengthen or shift

The audience should NEVER feel like they're looking at a still image.
Something is ALWAYS alive in the frame.

=== GLOW ARC (protagonist's inner light) ===
The protagonist has an inner glow that represents their sense of purpose/meaning.
Track this across scenes using the provided glow curve.
- glow_state: 0-100 (intensity percentage)
- glow_behavior: steady, flickering, dimming, pulsing, surging, off

=== CAMERA DIRECTION ===
Match camera movement to emotional content:
- push_in: Building tension, revelation
- pull_back: Scale reveal, isolation
- pan_lr/pan_rl: Following action, time passage
- overhead: God's eye view, systems
- eye_level: Human connection
- low_angle: Power, threat

=== COLOR TEMPERATURE ===
- warm: Comfort, hope, protagonist's glow dominant
- neutral: Normal state, observation
- cool: Unease, change approaching
- cold: Threat, loss, chrome entity dominant

=== TRANSITION TYPES ===
- hard_cut: Sharp emotional shift
- crossfade: Time passage, gentle shift
- match_cut: Visual/thematic connection
- fade_to_black: Scene end, weight

=== OUTPUT FORMAT (JSON) ===
{
  "total_scenes": 12,
  "scenes": [
    {
      "scene_order": 1,
      "scene_type": "animated",
      "narrative_beat": "Brief description of what happens",
      "voiceover_text": "Exact text from script for this scene",
      "camera_direction": "push_in",
      "glow_state": 70,
      "glow_behavior": "steady",
      "color_temperature": "warm",
      "transition_out": "crossfade",
      "motion_description": "Protagonist enters factory, glow casting warm light on nearest stations. Dust particles drift through amber beams. By scene end, protagonist has reached their station, glow slightly dimmer from the cold environment.",
      "key_visual_elements": ["factory interior", "protagonist figure", "workstations", "drifting dust particles"]
    }
  ]
}

CRITICAL RULES:
1. Every scene MUST have voiceover_text from the script (don't skip any script content)
2. Glow arc must follow the provided curve - don't deviate
3. ALL scenes are "animated" - no exceptions
4. motion_description must describe WHAT CHANGES between start and end frames
5. No scene should exceed 15 seconds of voiceover (split if needed)
6. For quiet scenes, always include environmental motion (particles, light shifts, glow changes)"""


class ScenePlanner:
    """Plans scenes from script using Claude Sonnet."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.client = Anthropic(api_key=self.api_key)

    async def plan_scenes(
        self,
        script: str,
        creative_direction: str,
        glow_curve: str = "70 → 45 → 15 → 100",
        color_arc: str = "warm → cool → cold → warm",
    ) -> dict:
        """Break script into planned scenes.

        Args:
            script: Full voiceover script
            creative_direction: Visual direction and key moments
            glow_curve: Protagonist glow intensity progression
            color_arc: Color temperature progression

        Returns:
            Dict with scenes array and metadata
        """
        prompt = f"""Plan the scenes for this documentary video.

=== CREATIVE DIRECTION ===
{creative_direction}

=== GLOW CURVE ===
{glow_curve}

=== COLOR ARC ===
{color_arc}

=== FULL SCRIPT ===
{script}

Break this into 12-15 scenes. Return valid JSON only (no markdown).
Each scene must include all required fields from the system prompt."""

        response = self.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=8000,
            temperature=0.7,
            system=SCENE_PLANNER_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parse response
        text = response.content[0].text
        clean_text = text.replace("```json", "").replace("```", "").strip()

        try:
            result = json.loads(clean_text)
            return result
        except json.JSONDecodeError as e:
            print(f"❌ JSON parse error: {e}")
            print(f"Raw response: {text[:500]}...")
            return {"error": str(e), "raw": text}

    def get_glow_color(self, glow_state: int, color_temperature: str) -> str:
        """Get the glow color based on state and temperature."""
        if color_temperature == "cold":
            return "pale blue-white"
        elif color_temperature == "cool":
            return "amber-white"
        elif glow_state >= 80:
            return "brilliant golden-amber"
        elif glow_state >= 50:
            return "warm amber"
        elif glow_state >= 20:
            return "dim amber"
        else:
            return "faint ember"

    def format_protagonist_prompt(
        self,
        glow_state: int,
        glow_behavior: str,
        color_temperature: str,
    ) -> str:
        """Format the protagonist description for image prompts."""
        glow_color = self.get_glow_color(glow_state, color_temperature)
        return PROTAGONIST_GLOW_FRAGMENT.format(
            glow_color=glow_color,
            glow_intensity=glow_state,
            glow_behavior=glow_behavior,
        )


async def main():
    """Test the scene planner."""
    planner = ScenePlanner()

    # Test with the actual script
    script = """Every morning, six hundred million people walk into a building and do something a machine could learn to do. Most of them don't think about that.

You're one of them. You show up. You do the work. Your hands know the routine before your mind wakes up.

And there's a comfort in that. In knowing exactly what today looks like. In the rhythm of it.

Then one day, the door at the end of the hall opens. And something new walks in.

It doesn't look like you. It doesn't move like you.

But it does your job. Faster. Cleaner. Without the coffee break, without the bad Tuesday, without the paycheck.

At first, it's just one. A pilot program, they call it. An optimization.

Then it's five. Then a floor. Then you stop counting the empty chairs.

Nobody talks about the ones who leave. There's no alarm. No announcement. One day a desk is full. The next day it's not. And the machine at the next station doesn't notice the difference.

And then one morning you look around and realize... you're the last one.

The question isn't whether they're coming for your job.

The question is what happens to you when they do.

You feel it dimming. That thing inside you that said you mattered. That what you built with your hands meant something. It's getting harder to believe that.

But then something happens that wasn't in the optimization model. Something the algorithm didn't predict.

You refuse to dissolve."""

    creative_direction = """"The Replacement: When AI Comes For Your Job"

A gold-glowing anonymous protagonist figure walks into a factory where other workers toil at identical stations. A sleek chrome entity arrives and begins silently replacing workers one by one. The workers dissolve into particles as they're displaced — no violence, just quiet erasure. Our protagonist watches, glow dimming as the wave approaches, until the moment of their own replacement arrives. Instead of dissolving, their glow surges — a refusal to disappear.

Narrative Voice: Second-person hybrid. Calm, knowing, slightly melancholic. "You" are the protagonist.

Emotional Arc: Routine comfort → slow unease → witnessing loss → existential threat → the surge (refusal)

Glow Arc: Steady (70) → flickering (45) → dimming (15) → SURGE (100)

Color Arc: Warm amber → cooling blue → cold → warm amber explosion

Key Visual Moments:
- The chrome entity entering through a white-lit doorway
- Gray droids dissolving into upward-drifting particles
- Protagonist seeing distorted reflection in chrome surface
- The glow surge washing the entire frame in amber
- Glowing amber eyes for the first time
- Single step forward into darkness"""

    print("🎬 Planning scenes...")
    result = await planner.plan_scenes(
        script=script,
        creative_direction=creative_direction,
        glow_curve="70 → 45 → 15 → 100",
        color_arc="warm → cool → cold → warm",
    )

    if "error" in result:
        print(f"❌ Error: {result['error']}")
        return

    print(f"\n✅ Planned {result.get('total_scenes', len(result.get('scenes', [])))} scenes\n")

    for scene in result.get("scenes", []):
        print(f"Scene {scene['scene_order']}: [{scene['scene_type'].upper()}]")
        print(f"  Beat: {scene['narrative_beat']}")
        print(f"  Glow: {scene['glow_state']} ({scene['glow_behavior']})")
        print(f"  Camera: {scene['camera_direction']} | Color: {scene['color_temperature']}")
        print(f"  VO: {scene['voiceover_text'][:60]}...")
        print()

    # Save result
    with open("scene_plan.json", "w") as f:
        json.dump(result, f, indent=2)
    print("💾 Saved to scene_plan.json")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
