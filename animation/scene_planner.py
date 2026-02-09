"""Scene planning via Sonnet — generates structured scene plans from scripts."""

import json
from typing import Optional
from anthropic import Anthropic

from animation.config import (
    ANTHROPIC_API_KEY,
    SCENE_PLANNER_MODEL,
    PROTAGONIST_PROMPT_FRAGMENT,
)


SCENE_PLANNER_SYSTEM_PROMPT = """You are a cinematic director for an animated finance/economics YouTube channel called Economy FastForward.

You create scene plans for videos featuring a recurring protagonist: a 3D clay render humanoid figure with a warm gold/amber glow emanating from their chest. The protagonist has average, relatable human proportions (not muscular or heroic). Background characters are neutral gray droids with no glow.

NARRATIVE FRAMEWORK:
- The voiceover uses second-person hybrid narration ("You walk into..." / "You feel it before you see it...")
- The protagonist IS the viewer — they experience economic forces rather than explaining them
- The gold glow represents awareness/consciousness/financial literacy
- Background gray droids represent the unaware masses

GLOW RULES:
- Track glow_state (0-100) across the entire video as an emotional arc
- Glow should respond to narrative tension: steady in comfort, flickering in unease, dimming in loss, surging in awakening
- Every prompt must specify the exact glow state

CAMERA RULES:
- Eye level = neutral
- Overhead = vulnerability (protagonist small in the machine)
- Low angle = power (looking up at protagonist)
- Push in = intimacy/tension
- Pull back = isolation/scale

COLOR TEMPERATURE RULES:
- Warm = comfort, safety, protagonist's influence
- Cool = corporate, mechanical, displacement
- Cold = isolation, loss
- The glow should be the primary warm element in cool/cold scenes

SCENE TYPE CLASSIFICATION:
- "animated": Protagonist takes action, emotional reactions, reveals, confrontations, motion essential
- "ken_burns": Establishing shots, data displays, atmospheric scenes, transitions
- "static": Title cards, text overlays, dramatic pauses, diagrams

PROTAGONIST PROMPT FRAGMENT (must appear in every start_image_prompt and end_image_prompt where protagonist is visible):
\"""" + PROTAGONIST_PROMPT_FRAGMENT + """\"

BACKGROUND CHARACTERS (when present):
"neutral gray matte droid figures with no glow, uniform featureless clay surface, no light emanation"

OUTPUT FORMAT:
Return a JSON object with:
{
  "video_title": "string",
  "total_scenes": number,
  "estimated_animation_cost": number,
  "glow_curve": [array of glow_state values],
  "scenes": [
    {
      "scene_order": number,
      "scene": "Scene N - Title",
      "scene_type": "animated|ken_burns|static",
      "narrative_beat": "string",
      "voiceover_text": "string",
      "camera_direction": "push_in|pull_back|pan_lr|pan_rl|overhead|eye_level|low_angle|static",
      "glow_state": number (0-100),
      "glow_behavior": "steady|flickering|dimming|pulsing|surging|off",
      "color_temperature": "warm|neutral|cool|cold",
      "transition_out": "hard_cut|crossfade|match_cut|fade_to_black",
      "start_image_prompt": "full image prompt with protagonist fragment and glow state embedded",
      "end_image_prompt": "full image prompt with protagonist fragment and glow state embedded",
      "motion_description": "Veo motion prompt describing movement between frames",
      "transition_prompt": "camera movement description",
      "negative_prompt": "no photorealistic, no flat 2D, no realistic skin, no anime, no cartoon"
    }
  ]
}

COST TARGETS:
- Aim for 50% animated, 35% ken_burns, 15% static scenes
- Target 50-75 total scenes for a 10-minute video
- Each animated scene = 8 seconds = $0.30
- Target total animation cost under $20 per video"""


class ScenePlanner:
    """Generates structured scene plans from scripts using Sonnet."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or ANTHROPIC_API_KEY
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment")
        self.client = Anthropic(api_key=self.api_key)

    async def plan_scenes(
        self,
        script: str,
        creative_direction: str = "",
        core_elements: str = "",
        video_title: str = "",
    ) -> dict:
        """Generate a full scene plan from a script.

        Args:
            script: The video script/voiceover text
            creative_direction: Creative direction from the Project table
            core_elements: Core visual elements from the Project table
            video_title: Title of the video

        Returns:
            Parsed JSON scene plan with scenes array
        """
        prompt_parts = [
            f'Create a complete scene plan for this animated video.',
            f'',
            f'VIDEO TITLE: "{video_title}"',
            f'',
            f'SCRIPT:',
            script,
        ]

        if creative_direction:
            prompt_parts.extend([
                f'',
                f'CREATIVE DIRECTION:',
                creative_direction,
            ])

        if core_elements:
            prompt_parts.extend([
                f'',
                f'CORE VISUAL ELEMENTS:',
                core_elements,
            ])

        prompt_parts.extend([
            f'',
            f'Generate the full scene plan as JSON. Aim for 50% animated, 35% ken_burns, 15% static.',
            f'Every protagonist scene prompt MUST include the locked protagonist prompt fragment.',
            f'Track the glow_state across the entire video as an emotional arc.',
        ])

        user_prompt = '\n'.join(prompt_parts)

        print(f"    \U0001f3ac Generating scene plan via Sonnet...")

        response = self.client.messages.create(
            model=SCENE_PLANNER_MODEL,
            max_tokens=16000,
            temperature=1.0,
            system=SCENE_PLANNER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw_text = response.content[0].text
        clean_text = raw_text.replace("```json", "").replace("```", "").strip()
        scene_plan = json.loads(clean_text)

        # Validate the plan
        scenes = scene_plan.get("scenes", [])
        total = len(scenes)
        animated = sum(1 for s in scenes if s.get("scene_type") == "animated")
        ken_burns = sum(1 for s in scenes if s.get("scene_type") == "ken_burns")
        static = sum(1 for s in scenes if s.get("scene_type") == "static")

        print(f"    \u2705 Scene plan generated: {total} scenes")
        print(f"       Animated: {animated} | Ken Burns: {ken_burns} | Static: {static}")

        # Calculate estimated cost
        estimated_cost = (animated * 0.35) + ((ken_burns + static) * 0.025)
        scene_plan["estimated_animation_cost"] = round(estimated_cost, 2)

        return scene_plan

    def scenes_to_airtable_rows(self, scene_plan: dict, project_name: str) -> list[dict]:
        """Convert scene plan JSON into Airtable row dicts.

        Args:
            scene_plan: The parsed scene plan from plan_scenes()
            project_name: Project name for linking

        Returns:
            List of dicts ready for airtable create_scene()
        """
        rows = []
        glow_curve = scene_plan.get("glow_curve", [])

        for scene in scene_plan.get("scenes", []):
            row = {
                "Project Name": project_name,
                "scene": scene.get("scene", f"Scene {scene.get('scene_order', 0)}"),
                "scene_order": scene.get("scene_order", 0),
                "scene_type": scene.get("scene_type", "animated"),
                "narrative_beat": scene.get("narrative_beat", ""),
                "voiceover_text": scene.get("voiceover_text", ""),
                "camera_direction": scene.get("camera_direction", "eye_level"),
                "glow_state": scene.get("glow_state", 50),
                "glow_behavior": scene.get("glow_behavior", "steady"),
                "color_temperature": scene.get("color_temperature", "neutral"),
                "transition_out": scene.get("transition_out", "hard_cut"),
                "start_image_prompt": scene.get("start_image_prompt", ""),
                "end_image_prompt": scene.get("end_image_prompt", ""),
                "motion_description": scene.get("motion_description", ""),
                "transition_prompt": scene.get("transition_prompt", ""),
                "negative_prompt": scene.get("negative_prompt", ""),
                "prompt done": True,
                "regen_count": 0,
            }
            rows.append(row)

        return rows
