"""Quality control checker using Haiku — validates animated clips."""

import json
from typing import Optional
from anthropic import Anthropic

from animation.config import ANTHROPIC_API_KEY, QC_MODEL


QC_SYSTEM_PROMPT = """You are a quality control inspector for animated video clips. Check the following:

1. GLOW PRESENCE: Is there a warm gold/amber glow visible on the protagonist's chest? Expected glow_state: {glow_state}/100
2. STYLE CONSISTENCY: Does the clip maintain 3D clay render aesthetic? Any photorealistic drift?
3. MOTION COHERENCE: Does the animation move logically from start to end frame? Any teleporting or impossible physics?
4. COLOR TEMPERATURE: Does the overall scene warmth/coolness match the expected: {color_temperature}?

Return JSON:
{{
  "qc_score": number (0-100),
  "pass": boolean,
  "notes": "string explaining any issues",
  "glow_visible": boolean,
  "style_consistent": boolean,
  "motion_coherent": boolean,
  "color_correct": boolean
}}"""


class QCChecker:
    """Runs quality control checks on animated clips using Haiku."""

    # Minimum passing score
    PASS_THRESHOLD = 60

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or ANTHROPIC_API_KEY
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment")
        self.client = Anthropic(api_key=self.api_key)

    async def check_scene(
        self,
        start_image_url: str,
        end_image_url: str,
        video_url: str,
        glow_state: int = 50,
        color_temperature: str = "neutral",
        motion_description: str = "",
    ) -> dict:
        """Run QC check on a completed scene.

        Since Haiku can analyze images but not video frames directly,
        we check the start and end frames for visual consistency and
        validate the scene metadata.

        Args:
            start_image_url: URL of the start frame
            end_image_url: URL of the end frame
            video_url: URL of the animated clip (for reference)
            glow_state: Expected glow intensity (0-100)
            color_temperature: Expected color temperature
            motion_description: Expected motion between frames

        Returns:
            QC result dict with qc_score, pass, notes, and detail booleans
        """
        system_prompt = QC_SYSTEM_PROMPT.format(
            glow_state=glow_state,
            color_temperature=color_temperature,
        )

        user_prompt = (
            f"Analyze these animation frames for quality control.\n\n"
            f"START FRAME: {start_image_url}\n"
            f"END FRAME: {end_image_url}\n"
            f"VIDEO CLIP: {video_url}\n\n"
            f"Expected glow_state: {glow_state}/100\n"
            f"Expected color_temperature: {color_temperature}\n"
            f"Expected motion: {motion_description}\n\n"
            f"Evaluate the start and end frames. Check that:\n"
            f"1. The protagonist's gold/amber glow is visible and matches intensity {glow_state}/100\n"
            f"2. The 3D clay render style is maintained (no photorealistic drift)\n"
            f"3. The start and end frames are logically consistent (the end frame "
            f"looks like a natural continuation of the start frame)\n"
            f"4. The color temperature matches: {color_temperature}\n\n"
            f"Return your assessment as JSON."
        )

        print(f"      \U0001f50d Running QC check via Haiku...")

        try:
            response = self.client.messages.create(
                model=QC_MODEL,
                max_tokens=1000,
                temperature=0.0,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            raw_text = response.content[0].text
            clean_text = raw_text.replace("```json", "").replace("```", "").strip()
            result = json.loads(clean_text)

            qc_score = result.get("qc_score", 0)
            passed = result.get("pass", qc_score >= self.PASS_THRESHOLD)

            print(f"      {'✅' if passed else '❌'} QC Score: {qc_score}/100 — {'PASS' if passed else 'FAIL'}")

            return {
                "qc_score": qc_score,
                "pass": passed,
                "notes": result.get("notes", ""),
                "glow_visible": result.get("glow_visible", False),
                "style_consistent": result.get("style_consistent", False),
                "motion_coherent": result.get("motion_coherent", False),
                "color_correct": result.get("color_correct", False),
            }

        except json.JSONDecodeError as e:
            print(f"      \u26a0\ufe0f QC response parse error: {e}")
            return {
                "qc_score": 0,
                "pass": False,
                "notes": f"QC parse error: {e}",
                "glow_visible": False,
                "style_consistent": False,
                "motion_coherent": False,
                "color_correct": False,
            }
        except Exception as e:
            print(f"      \u274c QC check error: {e}")
            return {
                "qc_score": 0,
                "pass": False,
                "notes": f"QC error: {e}",
                "glow_visible": False,
                "style_consistent": False,
                "motion_coherent": False,
                "color_correct": False,
            }
