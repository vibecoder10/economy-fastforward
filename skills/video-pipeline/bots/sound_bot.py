"""Sound Bot — generates sound effect audio files from sound maps.

Reads the Sound Map JSON from each scene's Script record, generates audio
via Kie.ai ElevenLabs Sound Effect V2, uploads to Google Drive, and updates
Airtable with file URLs.
"""

import json
import asyncio
from typing import Optional

from clients.sound_client import SoundClient
from clients.airtable_client import AirtableClient
from clients.google_client import GoogleClient
from clients.slack_client import SlackClient


# Safety limit — max generations per video before pausing
MAX_GENERATIONS_PER_VIDEO = 100


class SoundBot:
    """Generates sound effect audio files from sound map prompts."""

    def __init__(
        self,
        sound_client: Optional[SoundClient] = None,
        airtable: Optional[AirtableClient] = None,
        google: Optional[GoogleClient] = None,
        slack: Optional[SlackClient] = None,
    ):
        self.sound_client = sound_client or SoundClient()
        self.airtable = airtable or AirtableClient()
        self.google = google or GoogleClient()
        self.slack = slack

    async def _generate_scene_sounds(
        self,
        script_record: dict,
        scene_number: int,
        folder_id: str,
        dry_run: bool = False,
    ) -> dict:
        """Generate all sound effects for a single scene.

        Args:
            script_record: Airtable script record with Sound Map
            scene_number: Scene number for naming files
            folder_id: Google Drive folder ID for uploads
            dry_run: If True, skip actual generation

        Returns:
            Dict with generation results
        """
        sound_map_raw = script_record.get("Sound Map", "")
        if not sound_map_raw:
            return {"scene": scene_number, "generated": 0, "error": "No sound map"}

        try:
            sound_map = json.loads(sound_map_raw)
        except (json.JSONDecodeError, TypeError) as e:
            return {"scene": scene_number, "generated": 0, "error": f"Invalid JSON: {e}"}

        sounds = sound_map.get("sounds", [])
        if not sounds:
            return {"scene": scene_number, "generated": 0, "error": "Empty sound map"}

        generated = 0
        for idx, sound in enumerate(sounds):
            prompt = sound.get("prompt", "")
            duration = sound.get("duration")
            loop = sound.get("loop", False)

            # Skip if already has a file URL (re-run safe)
            if sound.get("file_url"):
                print(f"    Scene {scene_number} sound {idx}: already generated, skipping")
                generated += 1
                continue

            if dry_run:
                print(f"    [DRY RUN] Scene {scene_number} sound {idx}: {prompt[:60]}...")
                continue

            # Check cost safety limit
            if self.sound_client.generation_count >= MAX_GENERATIONS_PER_VIDEO:
                msg = f"Hit {MAX_GENERATIONS_PER_VIDEO} generation limit for this video"
                print(f"    {msg}")
                if self.slack:
                    self.slack.notify(f"Warning: {msg}. Pausing sound generation.")
                return {
                    "scene": scene_number,
                    "generated": generated,
                    "error": msg,
                    "limit_reached": True,
                }

            print(f"    Scene {scene_number} sound {idx} ({sound.get('type', '?')}): {prompt[:60]}...")

            audio_url = await self.sound_client.generate_sound_effect(
                text=prompt,
                duration_seconds=duration,
                loop=loop,
            )

            if audio_url:
                # Download and upload to Google Drive
                try:
                    audio_content = await self.sound_client.download_audio(audio_url)
                    filename = f"sfx_scene_{scene_number}_{idx}.mp3"
                    drive_file = self.google.upload_audio(audio_content, filename, folder_id)
                    drive_url = self.google.make_file_public(drive_file["id"])

                    # Update sound map entry with file info
                    sound["file_url"] = drive_url
                    sound["filename"] = filename
                    generated += 1
                except Exception as e:
                    print(f"    Upload failed for scene {scene_number} sound {idx}: {e}")
                    # Store the raw URL as fallback
                    sound["file_url"] = audio_url
                    sound["filename"] = f"sfx_scene_{scene_number}_{idx}.mp3"
                    generated += 1
            else:
                print(f"    Generation failed for scene {scene_number} sound {idx}")

        # Write updated sound map (with file URLs) back to Airtable
        if not dry_run and generated > 0:
            updated_json = json.dumps(sound_map)
            try:
                self.airtable.update_script_record(
                    script_record["id"],
                    {"Sound Map": updated_json, "SFX Status": "Done"},
                )
            except Exception as e:
                print(f"    Warning: batch update failed ({e}), trying individually...")
                try:
                    self.airtable.update_script_record(script_record["id"], {"Sound Map": updated_json})
                except Exception:
                    pass
                try:
                    self.airtable.update_script_record(script_record["id"], {"SFX Status": "Done"})
                except Exception:
                    pass

        return {"scene": scene_number, "generated": generated}

    async def process_video(
        self,
        video_title: str,
        folder_id: Optional[str] = None,
        dry_run: bool = False,
        max_concurrent_scenes: int = 3,
    ) -> dict:
        """Generate sound effects for all scenes of a video.

        Args:
            video_title: Title of the video
            folder_id: Google Drive folder for uploads (auto-created if None)
            dry_run: If True, log prompts without generating audio
            max_concurrent_scenes: Max scenes to process in parallel

        Returns:
            Dict with processing results
        """
        print(f"\n  SOUND BOT: Processing '{video_title}' {'[DRY RUN]' if dry_run else ''}")

        scripts = self.airtable.get_scripts_by_title(video_title)
        if not scripts:
            return {"error": f"No scripts found for: {video_title}"}

        # Filter to scripts with sound maps (Prompts Ready or already Done)
        scripts_with_maps = [
            s for s in scripts
            if s.get("Sound Map") and s.get("SFX Status") in ("Prompts Ready", "Done", None)
        ]

        if not scripts_with_maps:
            return {"error": "No scripts with sound maps found. Run sound_prompt_bot first."}

        # Get Drive folder from Airtable idea record (same folder as voice/images)
        if not folder_id:
            idea = self.airtable.find_idea_by_title(video_title)
            if idea:
                folder_id = idea.get("Drive Folder ID")
            if not folder_id:
                return {"error": f"No Drive Folder ID found in Airtable for: {video_title}"}

        scripts_with_maps = sorted(scripts_with_maps, key=lambda s: s.get("scene", 0))

        total_generated = 0
        scene_count = 0
        limit_reached = False

        # Process scenes in batches for controlled concurrency
        for batch_start in range(0, len(scripts_with_maps), max_concurrent_scenes):
            if limit_reached:
                break

            batch = scripts_with_maps[batch_start:batch_start + max_concurrent_scenes]
            tasks = [
                self._generate_scene_sounds(
                    script_record=script,
                    scene_number=script.get("scene", 0),
                    folder_id=folder_id,
                    dry_run=dry_run,
                )
                for script in batch
            ]

            results = await asyncio.gather(*tasks)

            for result in results:
                total_generated += result.get("generated", 0)
                if result.get("generated", 0) > 0 or result.get("error") is None:
                    scene_count += 1
                if result.get("limit_reached"):
                    limit_reached = True

        estimated_cost = self.sound_client.estimated_total_cost

        print(f"\n  Sound generation complete: {total_generated} effects across {scene_count} scenes")
        print(f"  Estimated cost: ~${estimated_cost:.2f}")

        return {
            "bot": "Sound Bot",
            "video_title": video_title,
            "total_generated": total_generated,
            "scene_count": scene_count,
            "estimated_cost": round(estimated_cost, 2),
            "dry_run": dry_run,
            "limit_reached": limit_reached,
        }
