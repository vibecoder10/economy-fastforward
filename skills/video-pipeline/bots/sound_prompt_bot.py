"""Sound Prompt Bot — generates per-scene sound maps using Claude.

Analyzes narration segments for each scene and outputs a structured JSON sound map
describing ambient beds, texture layers, punctuation hits, and transition sounds.
"""

import json
from typing import Optional

from clients.anthropic_client import AnthropicClient
from clients.airtable_client import AirtableClient

SOUND_DESIGN_SYSTEM_PROMPT = """\
You are a cinematic sound designer for documentary films about geopolitics, economics, and power dynamics. You design layered ambient soundscapes that play underneath narration.

You will receive all narration segments for one scene. Analyze the emotional arc and narrative content, then output a JSON sound map.

Sound types:
- "ambient": Background atmosphere that runs across multiple segments. Always looped. 10-22 seconds. Volume 0.08-0.15.
- "layer": Additional texture stacked on top of an ambient bed for specific segments. Not looped. 8-15 seconds. Volume 0.05-0.10.
- "punctuation": Short dramatic hit at a specific moment. Not looped. 1-3 seconds. Volume 0.15-0.30.
- "transition": Sound that bridges into the next scene. Not looped. 1-3 seconds. Volume 0.10-0.20.

Rules:
- Output 3-7 sounds per scene. Not every segment needs its own sound.
- Group consecutive segments that share the same mood under one ambient bed.
- Punctuation sounds are RARE — max 2 per scene, only for genuinely dramatic moments.
- Transition sounds only on act breaks or major tone shifts, not every scene.
- Sound prompts must be specific and concrete: "distant artillery rumble with crackling fire and faint radio chatter" NOT "war sounds"
- Include 2-3 layered elements in ambient descriptions: base + detail sounds
- ALL sounds are atmosphere and foley. NEVER music, instruments, melodies, or soundtrack.
- Keep each prompt under 450 characters.
- Volume guide: quiet analysis scenes = lower volumes (0.05-0.10), intense action scenes = higher volumes (0.15-0.25)
- Fade guide: ambients get 0.5-1.0s fades, punctuation gets 0-0.3s fades, transitions get 0.3-0.5s fades

Sound palette by content:
- Military/strike: distant explosions, drone buzz, fire crackle, radio static, boots on concrete, helicopter rotors
- Command center: electronic hum, keyboard clicks, radar ping, ventilation, quiet tension
- Historical: radio static, typewriter, vinyl crackle, crowd murmur, old phone rings, period-appropriate texture
- Markets/finance: ticker tape printing, phones ringing frantically, trading floor murmur, keyboard clatter
- Ocean/geographic: waves, ship horns, harbor ambience, wind, seabirds, metal hull creaking
- Power/political: echoing marble halls, heavy doors, clock ticking, hushed whispers, pen on paper
- Surveillance/data: server hum, electronic beeping, data stream, fluorescent buzz, security camera motor
- Desert/Middle East: dry wind, distant call to prayer, sand shifting, heat shimmer hum

Output ONLY valid JSON, no markdown, no explanation:
{
  "sounds": [
    {
      "segments": [1, 2],
      "type": "ambient",
      "prompt": "specific sound description here",
      "duration": 15,
      "volume": 0.12,
      "loop": true,
      "fade_in": 0.5,
      "fade_out": 0.5
    }
  ]
}"""


class SoundPromptBot:
    """Generates sound design maps for each scene using Claude."""

    VALID_TYPES = {"ambient", "layer", "punctuation", "transition"}
    DURATION_RANGES = {
        "ambient": (10, 22),
        "layer": (8, 15),
        "punctuation": (1, 3),
        "transition": (1, 3),
    }
    VOLUME_RANGES = {
        "ambient": (0.05, 0.25),
        "layer": (0.03, 0.15),
        "punctuation": (0.10, 0.35),
        "transition": (0.05, 0.25),
    }

    def __init__(
        self,
        anthropic: Optional[AnthropicClient] = None,
        airtable: Optional[AirtableClient] = None,
    ):
        self.anthropic = anthropic or AnthropicClient()
        self.airtable = airtable or AirtableClient()

    def _build_user_prompt(
        self,
        scene_number: int,
        total_scenes: int,
        act_number: int,
        segments: list[dict],
        prev_scene_last_text: str,
        next_scene_first_text: str,
    ) -> str:
        """Build the user prompt for Claude with scene context."""
        lines = [f"Scene {scene_number} of {total_scenes}. Act {act_number}.", "", "Segments:"]
        for i, seg in enumerate(segments, 1):
            text = seg.get("text", "").strip()
            lines.append(f'{i}. "{text}"')

        lines.append("")
        if prev_scene_last_text:
            lines.append(f'Previous scene ended with: "{prev_scene_last_text}"')
        else:
            lines.append("This is the first scene.")
        if next_scene_first_text:
            lines.append(f'Next scene starts with: "{next_scene_first_text}"')
        else:
            lines.append("This is the last scene.")

        lines.append("")
        lines.append("Generate the sound map for this scene.")
        return "\n".join(lines)

    def _parse_and_validate_sound_map(
        self,
        raw_response: str,
        segment_count: int,
    ) -> Optional[dict]:
        """Parse Claude's JSON response and validate the sound map.

        Returns validated sound map dict, or None if parsing/validation fails.
        """
        # Try direct parse, then strip markdown fences
        sound_map = None
        for attempt_fn in [
            lambda r: json.loads(r),
            lambda r: json.loads(r.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()),
            lambda r: json.loads(r[r.index("{"):r.rindex("}") + 1]),
        ]:
            try:
                sound_map = attempt_fn(raw_response)
                break
            except (json.JSONDecodeError, ValueError):
                continue

        if not sound_map or "sounds" not in sound_map:
            print("    Failed to parse sound map JSON")
            return None

        sounds = sound_map["sounds"]
        if not isinstance(sounds, list) or not (1 <= len(sounds) <= 10):
            print(f"    Invalid sound count: {len(sounds) if isinstance(sounds, list) else 'not a list'}")
            return None

        validated = []
        for s in sounds:
            sound_type = s.get("type", "")
            if sound_type not in self.VALID_TYPES:
                print(f"    Skipping invalid type: {sound_type}")
                continue

            # Validate segments
            segs = s.get("segments", [])
            if not isinstance(segs, list) or not segs:
                continue
            # Clamp segment numbers to valid range
            segs = [seg for seg in segs if isinstance(seg, (int, float)) and 1 <= int(seg) <= segment_count]
            if not segs:
                continue

            # Validate and clamp duration
            dur_min, dur_max = self.DURATION_RANGES[sound_type]
            duration = s.get("duration", dur_min)
            duration = max(dur_min, min(dur_max, float(duration)))

            # Validate and clamp volume
            vol_min, vol_max = self.VOLUME_RANGES[sound_type]
            volume = s.get("volume", vol_min)
            volume = max(vol_min, min(vol_max, float(volume)))

            # Validate prompt
            prompt = s.get("prompt", "")
            if not prompt or len(prompt) < 10:
                continue
            if len(prompt) > 450:
                prompt = prompt[:450]

            # Loop: ambient always true, others respect value
            loop = True if sound_type == "ambient" else bool(s.get("loop", False))

            # Fades
            fade_in = max(0.0, min(2.0, float(s.get("fade_in", 0.5))))
            fade_out = max(0.0, min(2.0, float(s.get("fade_out", 0.5))))

            validated.append({
                "segments": [int(seg) for seg in segs],
                "type": sound_type,
                "prompt": prompt,
                "duration": round(duration, 1),
                "volume": round(volume, 2),
                "loop": loop,
                "fade_in": round(fade_in, 1),
                "fade_out": round(fade_out, 1),
            })

        if not validated:
            print("    No valid sounds after validation")
            return None

        return {"sounds": validated}

    async def generate_sound_map(
        self,
        scene_number: int,
        total_scenes: int,
        act_number: int,
        segments: list[dict],
        prev_scene_last_text: str = "",
        next_scene_first_text: str = "",
    ) -> Optional[dict]:
        """Generate a sound map for a single scene.

        Args:
            scene_number: Scene number (1-based)
            total_scenes: Total scenes in the video
            act_number: Act number for this scene
            segments: List of dicts with 'text' keys for each segment
            prev_scene_last_text: Last segment text of previous scene
            next_scene_first_text: First segment text of next scene

        Returns:
            Validated sound map dict, or None if generation failed
        """
        user_prompt = self._build_user_prompt(
            scene_number, total_scenes, act_number,
            segments, prev_scene_last_text, next_scene_first_text,
        )

        print(f"  Generating sound map for scene {scene_number} ({len(segments)} segments)...")

        response = await self.anthropic.generate(
            prompt=user_prompt,
            system_prompt=SOUND_DESIGN_SYSTEM_PROMPT,
            model="claude-sonnet-4-5-20250929",
            max_tokens=2048,
            temperature=0.7,
        )

        sound_map = self._parse_and_validate_sound_map(response, len(segments))
        if sound_map:
            print(f"    {len(sound_map['sounds'])} sounds generated")
        return sound_map

    async def process_video(self, video_title: str) -> dict:
        """Generate sound maps for all scenes of a video.

        Reads scripts from Airtable, generates sound maps via Claude,
        and writes back to the Script table.

        Args:
            video_title: Title of the video to process

        Returns:
            Dict with processing results
        """
        print(f"\n  SOUND PROMPT BOT: Processing '{video_title}'")

        scripts = self.airtable.get_scripts_by_title(video_title)
        if not scripts:
            return {"error": f"No scripts found for: {video_title}"}

        # Sort by scene number
        scripts = sorted(scripts, key=lambda s: s.get("scene", 0))
        total_scenes = len(scripts)

        # Build segment data for all scenes
        scene_data = []
        for script in scripts:
            scene_number = script.get("scene", 0)
            scene_text = script.get("Scene text", "")

            # Split scene text into segments (sentences)
            # Each "segment" here is a sentence from the narration
            sentences = [s.strip() for s in scene_text.replace("\n", " ").split(".") if s.strip()]
            segments = [{"text": s + "."} for s in sentences]

            # Determine act number (6 acts across ~20 scenes)
            act_number = min(6, max(1, (scene_number - 1) // (max(1, total_scenes // 6)) + 1))

            scene_data.append({
                "script": script,
                "scene_number": scene_number,
                "act_number": act_number,
                "segments": segments,
            })

        total_sounds = 0
        scenes_processed = 0

        for i, data in enumerate(scene_data):
            # Skip if sound map already exists
            existing_map = data["script"].get("Sound Map")
            if existing_map:
                print(f"  Scene {data['scene_number']}: Sound map already exists, skipping")
                try:
                    existing = json.loads(existing_map)
                    total_sounds += len(existing.get("sounds", []))
                except (json.JSONDecodeError, TypeError):
                    pass
                scenes_processed += 1
                continue

            # Context from adjacent scenes
            prev_text = ""
            if i > 0:
                prev_segs = scene_data[i - 1]["segments"]
                if prev_segs:
                    prev_text = prev_segs[-1]["text"]

            next_text = ""
            if i < len(scene_data) - 1:
                next_segs = scene_data[i + 1]["segments"]
                if next_segs:
                    next_text = next_segs[0]["text"]

            sound_map = await self.generate_sound_map(
                scene_number=data["scene_number"],
                total_scenes=total_scenes,
                act_number=data["act_number"],
                segments=data["segments"],
                prev_scene_last_text=prev_text,
                next_scene_first_text=next_text,
            )

            if sound_map:
                # Write sound map to Airtable
                sound_map_json = json.dumps(sound_map)
                try:
                    self.airtable.update_script_record(
                        data["script"]["id"],
                        {"Sound Map": sound_map_json, "SFX Status": "Prompts Ready"},
                    )
                except Exception as e:
                    # Graceful degradation — try fields individually
                    print(f"    Warning: batch update failed ({e}), trying individually...")
                    try:
                        self.airtable.update_script_record(data["script"]["id"], {"Sound Map": sound_map_json})
                    except Exception as e2:
                        print(f"    Failed to write Sound Map: {e2}")
                    try:
                        self.airtable.update_script_record(data["script"]["id"], {"SFX Status": "Prompts Ready"})
                    except Exception as e2:
                        print(f"    Failed to write SFX Status: {e2}")

                total_sounds += len(sound_map["sounds"])
                scenes_processed += 1
            else:
                print(f"    Scene {data['scene_number']}: Sound map generation failed")

        print(f"\n  Sound design complete: {total_sounds} sounds across {scenes_processed} scenes")

        return {
            "bot": "Sound Prompt Bot",
            "video_title": video_title,
            "scenes_processed": scenes_processed,
            "total_scenes": total_scenes,
            "total_sounds": total_sounds,
        }
