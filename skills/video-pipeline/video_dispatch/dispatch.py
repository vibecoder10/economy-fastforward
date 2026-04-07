"""Video Dispatch Engine — orchestrates keyframe + bridge generation.

Usage:
    python -m video_dispatch.dispatch production_sheet.json [--output-dir ./output]
    python -m video_dispatch.dispatch production_sheet.json --dry-run

Flow:
    0. Generate character reference images (anchors for visual consistency)
    1. Generate all keyframe images (Nano Banana 2 via Kie.ai)
       - Each keyframe receives character refs + previous frame as image_input
    2. Generate video bridges between keyframes (Grok image-to-video)
    3. Write manifest with all URLs for assembly
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

import httpx

from video_dispatch.models import (
    Bridge,
    Keyframe,
    ProductionSheet,
    TaskStatus,
)
from orchestrator.pipeline_constants import Endpoints


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IMAGE_MODEL = "nano-banana-2"
VIDEO_MODEL = "grok-imagine/image-to-video"

# Polling tuning
IMAGE_INITIAL_WAIT = 5.0
IMAGE_POLL_INTERVAL = 2.0
IMAGE_POLL_MAX = 90

VIDEO_INITIAL_WAIT = 10.0
VIDEO_POLL_INTERVAL = 5.0
VIDEO_POLL_MAX = 120

# Concurrency — avoid hammering the API
MAX_CONCURRENT_IMAGES = 3
MAX_CONCURRENT_VIDEOS = 2


# ---------------------------------------------------------------------------
# Kie.ai API helpers (mirrors patterns from shared/clients/image_client.py)
# ---------------------------------------------------------------------------

class DispatchClient:
    """Lightweight async client for Kie.ai text-to-image and image-to-video."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("KIE_AI_API_KEY")
        if not self.api_key:
            raise ValueError("KIE_AI_API_KEY not found in environment")
        self.create_url = Endpoints.KIE_CREATE_TASK
        self.record_url = Endpoints.KIE_RECORD_INFO

    # -- low-level helpers --------------------------------------------------

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _create_task(self, payload: dict) -> Optional[str]:
        """Submit a task and return the taskId, or None on failure."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.create_url,
                headers=self._headers(),
                json=payload,
                timeout=60.0,
            )
            if resp.status_code != 200:
                print(f"  [dispatch] API error {resp.status_code}: {resp.text[:300]}")
                return None
            data = resp.json().get("data", {})
            return data.get("taskId")

    async def _poll(
        self,
        task_id: str,
        max_attempts: int,
        interval: float,
    ) -> Optional[list[str]]:
        """Poll until success/failure. Returns result URLs or None."""
        for attempt in range(max_attempts):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        self.record_url,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        params={"taskId": task_id},
                        timeout=30.0,
                    )
                    resp.raise_for_status()
                    data = resp.json().get("data", {})
            except Exception as e:
                print(f"  [poll] Error on attempt {attempt+1}: {e}")
                await asyncio.sleep(interval)
                continue

            status = data.get("status")
            state = str(data.get("state", "")).lower()

            # Failed
            if status == 3 or state in ("fail", "failed", "failure", "error"):
                err = data.get("errorMessage") or data.get("error") or "unknown"
                print(f"  [poll] Task {task_id} FAILED: {err}")
                return None

            # Success — extract URLs
            result_json = data.get("resultJson")
            if result_json:
                if isinstance(result_json, str):
                    result_json = json.loads(result_json)
                urls = result_json.get("resultUrls", [])
                if urls:
                    return urls

            await asyncio.sleep(interval)

        print(f"  [poll] Task {task_id} timed out after {max_attempts} attempts")
        return None

    # -- high-level operations -----------------------------------------------

    async def generate_character_ref(
        self, name: str, prompt: str, aspect_ratio: str = "16:9",
    ) -> Optional[str]:
        """Generate a character reference image. Returns the image URL."""
        print(f"  [char-ref] {name}: generating...")

        payload = {
            "model": IMAGE_MODEL,
            "input": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "output_format": "png",
            },
        }

        task_id = await self._create_task(payload)
        if not task_id:
            print(f"  [char-ref] {name}: FAILED to create task")
            return None

        print(f"  [char-ref] {name}: task {task_id}")
        await asyncio.sleep(IMAGE_INITIAL_WAIT)
        urls = await self._poll(task_id, IMAGE_POLL_MAX, IMAGE_POLL_INTERVAL)

        if urls:
            print(f"  [char-ref] {name}: DONE -> {urls[0][:80]}...")
            return urls[0]

        print(f"  [char-ref] {name}: FAILED (poll timeout)")
        return None

    async def generate_keyframe(
        self,
        kf: Keyframe,
        reference_url: Optional[str] = None,
        character_ref_urls: Optional[list] = None,
    ) -> Keyframe:
        """Generate a single keyframe image via text-to-image.

        Args:
            kf: The keyframe to generate.
            reference_url: URL of the previous keyframe (scene continuity).
            character_ref_urls: URLs of character reference images (identity anchor).

        image_input is assembled as: [char_refs..., previous_frame] so the
        model locks character identity first, then maintains scene flow.
        """
        kf.status = TaskStatus.IN_PROGRESS
        refs = character_ref_urls or []
        ref_count = len(refs) + (1 if reference_url else 0)
        ref_tag = f" ({ref_count} refs)" if ref_count else ""
        print(f"  [keyframe] {kf.keyframe_id}: generating ({kf.shot_type}){ref_tag}...")

        input_params = {
            "prompt": kf.prompt,
            "aspect_ratio": kf.aspect_ratio,
            "output_format": "png",
        }

        # Build image_input: character refs first (anchor), previous frame last (continuity)
        image_input = list(refs)
        if reference_url:
            image_input.append(reference_url)
        if image_input:
            input_params["image_input"] = image_input

        payload = {
            "model": IMAGE_MODEL,
            "input": input_params,
        }

        task_id = await self._create_task(payload)
        if not task_id:
            kf.status = TaskStatus.FAILED
            kf.error = "Failed to create task"
            return kf

        kf.task_id = task_id
        print(f"  [keyframe] {kf.keyframe_id}: task {task_id}")

        await asyncio.sleep(IMAGE_INITIAL_WAIT)
        urls = await self._poll(task_id, IMAGE_POLL_MAX, IMAGE_POLL_INTERVAL)

        if urls:
            kf.image_url = urls[0]
            kf.status = TaskStatus.COMPLETED
            print(f"  [keyframe] {kf.keyframe_id}: DONE -> {kf.image_url[:80]}...")
        else:
            kf.status = TaskStatus.FAILED
            kf.error = "Poll returned no results"
            print(f"  [keyframe] {kf.keyframe_id}: FAILED")

        return kf

    async def generate_bridge(
        self,
        bridge: Bridge,
        from_image_url: str,
        to_image_url: str,
        character_refs: Optional[dict] = None,
        location_refs: Optional[dict] = None,
        waypoint_urls: Optional[list] = None,
        bible_characters: Optional[list] = None,
    ) -> Bridge:
        """Generate a video bridge between two keyframe images.

        Args:
            bridge: Bridge definition with prompt, duration, mode, waypoints.
            from_image_url: Start keyframe image URL.
            to_image_url: End keyframe image URL.
            character_refs: Dict of {name: url} — filtered by bridge.characters.
            location_refs: Dict of {location_name: url} — filtered by bridge.location.
            waypoint_urls: List of intermediate keyframe image URLs (visual guides).

        image_urls ordering: [char_ref, start_frame, waypoints..., end_frame]
        For scene transitions (10s with waypoints), the model gets the full
        visual journey and animates it in one continuous pass.
        Max 7 images total (API limit).
        """
        bridge.status = TaskStatus.IN_PROGRESS

        # Filter character refs to only those in this bridge's scene
        scene_char_refs = {}
        if character_refs and bridge.characters:
            for name in bridge.characters:
                if name in character_refs:
                    scene_char_refs[name] = character_refs[name]

        waypoints = waypoint_urls or []
        has_waypoints = len(waypoints) > 0

        ref_count = len(scene_char_refs) + len(waypoints)
        ref_tag = f" ({len(scene_char_refs)} chars, {len(waypoints)} waypoints)" if ref_count else ""
        print(
            f"  [bridge] {bridge.bridge_id}: {bridge.from_keyframe} -> "
            f"{bridge.to_keyframe} ({bridge.duration}s){ref_tag}..."
        )

        # Clamp duration
        duration = max(6, min(30, bridge.duration))
        if duration > 10 and not has_waypoints:
            print(f"  [bridge] WARNING: {bridge.bridge_id} duration {duration}s > 10s without waypoints")

        # Build image_urls — dynamic allocation within 7-slot limit.
        # Fixed slots: start_frame (1) + end_frame (1) = 2
        # Remaining slots: fill with char refs first, then waypoints.
        # Priority: char refs > waypoints (chars need identity lock,
        # waypoints are nice-to-have visual guides).
        MAX_SLOTS = 7
        fixed_slots = 2  # start + end frames
        available = MAX_SLOTS - fixed_slots  # 5 slots for refs + waypoints

        # Fit as many character refs as possible, then fill rest with waypoints
        char_ref_names = []
        char_ref_urls_to_use = []
        for name, url in scene_char_refs.items():
            if len(char_ref_urls_to_use) < available:
                char_ref_urls_to_use.append(url)
                char_ref_names.append(name)

        remaining = available - len(char_ref_urls_to_use)
        waypoints_to_use = waypoints[:remaining] if remaining > 0 else []

        if len(waypoints_to_use) < len(waypoints):
            dropped = len(waypoints) - len(waypoints_to_use)
            print(f"  [bridge] NOTE: trimmed {dropped} waypoints to fit {len(char_ref_names)} char refs (7-slot limit)")

        # Assemble: [char_refs..., start_frame, waypoints..., end_frame]
        image_urls = char_ref_urls_to_use + [from_image_url] + waypoints_to_use + [to_image_url]

        # Inject character wardrobe descriptions into prompt
        wardrobe_block = _build_wardrobe_block(bridge.characters, bible_characters or [])
        if wardrobe_block:
            prompt = prompt + wardrobe_block

        # Build prompt with @image tags
        if "@image" not in prompt.lower():
            idx = 1
            tag_parts = []

            # Character ref tags — all that were included
            for name in char_ref_names:
                tag_parts.append(f"@image{idx} is the character reference for {name}.")
                idx += 1

            # Start frame tag
            start_idx = idx
            idx += 1

            # Waypoint tags
            waypoint_indices = []
            for _ in waypoints_to_use:
                waypoint_indices.append(idx)
                idx += 1

            # End frame tag
            end_idx = idx

            prefix = " ".join(tag_parts)
            if prefix:
                prefix += " "

            # For bridges with waypoints: describe the journey through each waypoint
            if waypoint_indices:
                prompt = (
                    f"{prefix}This is a continuous {duration}-second shot. "
                    f"@image{start_idx} {prompt} "
                    f"Transition smoothly to the composition shown in @image{end_idx}. "
                    f"Smooth continuous camera follow, no cuts."
                )
            else:
                prompt = (
                    f"{prefix}"
                    f"@image{start_idx} {prompt} "
                    f"Transition smoothly to the composition shown in @image{end_idx}"
                )

        payload = {
            "model": VIDEO_MODEL,
            "input": {
                "image_urls": image_urls,
                "prompt": prompt,
                "mode": bridge.mode,
                "duration": duration,
                "resolution": bridge.resolution,
                "aspect_ratio": bridge.aspect_ratio,
            },
        }

        max_retries = 3
        for attempt in range(max_retries):
            task_id = await self._create_task(payload)
            if not task_id:
                if attempt < max_retries - 1:
                    print(f"  [bridge] {bridge.bridge_id}: retry {attempt+2}/{max_retries}")
                    await asyncio.sleep(5)
                    continue
                bridge.status = TaskStatus.FAILED
                bridge.error = "Failed to create task after retries"
                return bridge

            bridge.task_id = task_id
            print(f"  [bridge] {bridge.bridge_id}: task {task_id}")

            await asyncio.sleep(VIDEO_INITIAL_WAIT)
            urls = await self._poll(task_id, VIDEO_POLL_MAX, VIDEO_POLL_INTERVAL)

            if urls:
                bridge.video_url = urls[0]
                bridge.status = TaskStatus.COMPLETED
                print(f"  [bridge] {bridge.bridge_id}: DONE -> {bridge.video_url[:80]}...")
                return bridge

            print(f"  [bridge] {bridge.bridge_id}: attempt {attempt+1} failed")
            if attempt < max_retries - 1:
                await asyncio.sleep(5)

        bridge.status = TaskStatus.FAILED
        bridge.error = "All retry attempts failed"
        print(f"  [bridge] {bridge.bridge_id}: FAILED")
        return bridge


# ---------------------------------------------------------------------------
# Dispatch orchestration
# ---------------------------------------------------------------------------

async def _download_and_upload(
    image_url: str,
    keyframe_id: str,
    drive_folder: Optional[str] = None,
    local_dir: Optional[Path] = None,
    filename: Optional[str] = None,
) -> Optional[str]:
    """Download an image and optionally upload to Google Drive.

    Returns the local file path, or None on failure.
    """
    if local_dir is None:
        local_dir = Path("/tmp/dispatch_assets/images")
    local_dir.mkdir(parents=True, exist_ok=True)
    fname = filename or f"{keyframe_id}.png"
    local_path = local_dir / fname

    try:
        async with httpx.AsyncClient(follow_redirects=True) as http:
            resp = await http.get(image_url, timeout=120)
            resp.raise_for_status()
            local_path.write_bytes(resp.content)
            size_kb = len(resp.content) / 1024
            print(f"  [download] {fname} ({size_kb:.0f} KB)")
    except Exception as e:
        print(f"  [download] {fname} FAILED: {e}")
        return None

    if drive_folder:
        proc = await asyncio.create_subprocess_exec(
            "rclone", "copy", str(local_path), f"gdrive:{drive_folder}",
            "--drive-root-folder-id=1zqsSvdyLWTRIt-Ri8VQELbYHhJihn6YD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode == 0:
            print(f"  [upload] {fname} -> Drive:/{drive_folder}/")
        else:
            print(f"  [upload] {fname} FAILED: {stderr.decode()[:200]}")

    return str(local_path)


async def dispatch_character_refs(
    client: DispatchClient,
    sheet: ProductionSheet,
    drive_folder: Optional[str] = None,
) -> list[str]:
    """Generate character reference images from bible entries.

    Characters with a 'ref_prompt' field get a reference image generated.
    Returns a list of image URLs for use as anchors in keyframe generation.
    """
    ref_urls = []
    characters_with_prompts = [
        c for c in sheet.bible.characters if c.get("ref_prompt")
    ]

    if not characters_with_prompts:
        return ref_urls

    for char in characters_with_prompts:
        name = char["name"]
        url = await client.generate_character_ref(
            name=name,
            prompt=char["ref_prompt"],
            aspect_ratio=sheet.aspect_ratio,
        )
        if url:
            ref_urls.append(url)
            # Save the URL back to the character dict for the manifest
            char["ref_image_url"] = url
            if drive_folder:
                safe_name = name.replace(" ", "_")
                await _download_and_upload(
                    url, safe_name, drive_folder,
                    filename=f"{safe_name}_ref.png",
                )
        else:
            print(f"  [char-ref] WARNING: {name} ref failed, continuing without")

    return ref_urls


async def dispatch_location_refs(
    client: DispatchClient,
    sheet: ProductionSheet,
    drive_folder: Optional[str] = None,
) -> dict:
    """Generate location reference images from bible entries.

    Locations with a 'ref_prompt' field get a reference image generated.
    Returns a dict of {location_name: image_url} for injection into
    keyframes and bridges.
    """
    ref_dict = {}
    locations_with_prompts = [
        loc for loc in sheet.bible.locations if loc.get("ref_prompt")
    ]

    if not locations_with_prompts:
        return ref_dict

    for loc in locations_with_prompts:
        name = loc["name"]
        url = await client.generate_character_ref(
            name=f"Location: {name}",
            prompt=loc["ref_prompt"],
            aspect_ratio=sheet.aspect_ratio,
        )
        if url:
            ref_dict[name] = url
            loc["ref_image_url"] = url
            if drive_folder:
                safe_name = name.replace(" ", "_")
                await _download_and_upload(
                    url, safe_name, drive_folder,
                    filename=f"LOC_{safe_name}_ref.png",
                )
        else:
            print(f"  [loc-ref] WARNING: {name} ref failed, continuing without")

    return ref_dict


def _build_wardrobe_block(characters: list, bible_characters: list) -> str:
    """Build a wardrobe description block for characters in a scene.

    Looks up each character's appearance and wardrobe from the bible
    and returns a string to inject into the prompt.
    """
    if not characters or not bible_characters:
        return ""

    bible_map = {c["name"]: c for c in bible_characters}
    parts = []
    for name in characters:
        char = bible_map.get(name)
        if not char:
            continue
        appearance = char.get("appearance", "")
        wardrobe = char.get("wardrobe", "")
        if appearance or wardrobe:
            desc = f"{name}: {appearance}"
            if wardrobe:
                desc += f", wearing {wardrobe}"
            parts.append(desc)

    if not parts:
        return ""
    return " CHARACTERS: " + ". ".join(parts) + "."


async def dispatch_keyframes(
    client: DispatchClient,
    keyframes: list[Keyframe],
    drive_folder: Optional[str] = None,
    character_refs: Optional[dict] = None,
    location_refs: Optional[dict] = None,
    bible_characters: Optional[list] = None,
) -> list[Keyframe]:
    """Generate keyframe images sequentially, chaining each as a reference.

    Each keyframe receives only the refs relevant to its scene:
      - character_refs filtered by kf.characters (or all if kf.characters is empty)
      - location_ref matched by kf.location
      - reference_url: previous frame's URL (scene continuity)
      - wardrobe descriptions auto-injected from bible into prompt

    image_input = [scene_char_refs..., location_ref, previous_frame]

    When drive_folder is set, each image is downloaded and uploaded to
    Google Drive immediately after generation (generate → upload → next).
    """
    reference_url = None
    prev_location = None
    for kf in keyframes:
        # Filter character refs to only those in this keyframe's scene
        scene_refs = []
        if character_refs:
            if kf.characters:
                scene_refs = [character_refs[name] for name in kf.characters if name in character_refs]
            else:
                scene_refs = list(character_refs.values())

        # Add location ref for this keyframe's scene
        if location_refs and kf.location and kf.location in location_refs:
            scene_refs.append(location_refs[kf.location])

        # Drop previous frame reference on location change to prevent
        # environment bleed (e.g., ACHIEVE poster leaking into open-plan).
        effective_ref = reference_url
        if kf.location and prev_location and kf.location != prev_location:
            print(f"  [keyframe] {kf.keyframe_id}: location change ({prev_location} -> {kf.location}), dropping prev frame ref")
            effective_ref = None

        # Inject character wardrobe descriptions into prompt so the model
        # never has to guess what characters are wearing.
        wardrobe_block = _build_wardrobe_block(kf.characters, bible_characters or [])
        original_prompt = kf.prompt
        if wardrobe_block:
            kf.prompt = kf.prompt + wardrobe_block

        await client.generate_keyframe(
            kf,
            reference_url=effective_ref,
            character_ref_urls=scene_refs if scene_refs else None,
        )
        kf.prompt = original_prompt  # Restore (don't persist injection into manifest)

        if kf.status == TaskStatus.COMPLETED and kf.image_url:
            reference_url = kf.image_url
            prev_location = kf.location
            if drive_folder:
                await _download_and_upload(kf.image_url, kf.keyframe_id, drive_folder)
        # If a keyframe fails, keep the last successful reference
    return keyframes


async def dispatch_bridges(
    client: DispatchClient,
    sheet: ProductionSheet,
    character_refs: Optional[dict] = None,
    location_refs: Optional[dict] = None,
    bible_characters: Optional[list] = None,
) -> list[Bridge]:
    """Generate all video bridges with bounded concurrency.

    Each bridge uses image_urls from BOTH its start and end keyframes.
    Bridges with waypoints pack intermediate keyframe images as visual
    guides for scene transitions (tested: 10s + waypoints > 3×6s).

    character_refs: dict of {name: url} — filtered per-bridge by bridge.characters
    location_refs: dict of {location_name: url} — filtered per-bridge by bridge.location
    """
    kf_map = {kf.keyframe_id: kf for kf in sheet.keyframes}
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_VIDEOS)

    async def _gen(br: Bridge) -> Bridge:
        from_kf = kf_map.get(br.from_keyframe)
        to_kf = kf_map.get(br.to_keyframe)
        if not from_kf or not from_kf.image_url:
            br.status = TaskStatus.FAILED
            br.error = f"Start keyframe {br.from_keyframe} has no image"
            print(f"  [bridge] {br.bridge_id}: SKIPPED (no start image)")
            return br
        if not to_kf or not to_kf.image_url:
            br.status = TaskStatus.FAILED
            br.error = f"End keyframe {br.to_keyframe} has no image"
            print(f"  [bridge] {br.bridge_id}: SKIPPED (no end image)")
            return br

        # Resolve waypoint keyframe IDs to image URLs
        waypoint_urls = []
        for wp_id in br.waypoints:
            wp_kf = kf_map.get(wp_id)
            if wp_kf and wp_kf.image_url:
                waypoint_urls.append(wp_kf.image_url)
            else:
                print(f"  [bridge] {br.bridge_id}: waypoint {wp_id} has no image, skipping")

        async with semaphore:
            return await client.generate_bridge(
                br, from_kf.image_url, to_kf.image_url,
                character_refs=character_refs,
                location_refs=location_refs,
                waypoint_urls=waypoint_urls if waypoint_urls else None,
                bible_characters=bible_characters,
            )

    return await asyncio.gather(*[_gen(br) for br in sheet.bridges])


async def run_dispatch(
    sheet: ProductionSheet,
    api_key: Optional[str] = None,
    dry_run: bool = False,
    images_only: bool = False,
    drive_folder: Optional[str] = None,
) -> dict:
    """Run the full dispatch pipeline.

    Returns a manifest dict with all URLs and statuses.
    """
    start = time.time()
    print(f"\n{'='*60}")
    print(f"VIDEO DISPATCH: {sheet.title}")
    print(f"Keyframes: {len(sheet.keyframes)} | Bridges: {len(sheet.bridges)}")
    print(f"Target duration: {sheet.total_duration_s}s | Style: {sheet.visual_style}")
    print(f"{'='*60}\n")

    # Check for character refs
    chars_with_refs = [c for c in sheet.bible.characters if c.get("ref_prompt")]

    if dry_run:
        print("[DRY RUN] Would generate:")
        if chars_with_refs:
            for c in chars_with_refs:
                print(f"  Char Ref: {c['name']} — {c['ref_prompt'][:60]}...")
        locs_with_refs_dry = [loc for loc in sheet.bible.locations if loc.get("ref_prompt")]
        if locs_with_refs_dry:
            for loc in locs_with_refs_dry:
                print(f"  Loc Ref: {loc['name']} — {loc['ref_prompt'][:60]}...")
        for kf in sheet.keyframes:
            print(f"  Image: {kf.keyframe_id} ({kf.shot_type}) — {kf.prompt[:60]}...")
        for br in sheet.bridges:
            print(
                f"  Video: {br.bridge_id} ({br.from_keyframe}->{br.to_keyframe}, "
                f"{br.duration}s) — {br.prompt[:60]}..."
            )
        return {"status": "dry_run", "keyframes": len(sheet.keyframes), "bridges": len(sheet.bridges)}

    client = DispatchClient(api_key=api_key)

    # Phase 0a: Generate character reference images
    character_ref_urls = []
    if chars_with_refs:
        print(f"--- PHASE 0a: Character References ({len(chars_with_refs)}) ---")
        character_ref_urls = await dispatch_character_refs(client, sheet, drive_folder)
        print(f"\nCharacter refs: {len(character_ref_urls)}/{len(chars_with_refs)} generated\n")
    else:
        print("--- PHASE 0a: No character refs defined, skipping ---\n")

    # Phase 0b: Generate location reference images
    locs_with_refs = [loc for loc in sheet.bible.locations if loc.get("ref_prompt")]
    location_ref_dict = {}
    if locs_with_refs:
        print(f"--- PHASE 0b: Location References ({len(locs_with_refs)}) ---")
        location_ref_dict = await dispatch_location_refs(client, sheet, drive_folder)
        print(f"\nLocation refs: {len(location_ref_dict)}/{len(locs_with_refs)} generated\n")
    else:
        print("--- PHASE 0b: No location refs defined, skipping ---\n")

    # Build character ref dict {name: url} for keyframe and bridge generation
    char_ref_dict = {
        c["name"]: c["ref_image_url"]
        for c in sheet.bible.characters
        if c.get("ref_image_url")
    } if chars_with_refs else None

    # Phase 1: Generate all keyframe images
    print("--- PHASE 1: Keyframe Images ---")
    await dispatch_keyframes(
        client, sheet.keyframes,
        drive_folder=drive_folder,
        character_refs=char_ref_dict,
        location_refs=location_ref_dict if location_ref_dict else None,
        bible_characters=sheet.bible.characters,
    )

    succeeded_kf = sum(1 for kf in sheet.keyframes if kf.status == TaskStatus.COMPLETED)
    failed_kf = sum(1 for kf in sheet.keyframes if kf.status == TaskStatus.FAILED)
    print(f"\nKeyframes: {succeeded_kf} succeeded, {failed_kf} failed\n")

    # Phase 2: Generate video bridges (needs keyframe images)
    if images_only:
        print("--- PHASE 2: Skipped (--images-only) ---\n")
        succeeded_br = 0
        failed_br = 0
    else:
        print("--- PHASE 2: Video Bridges ---")
        await dispatch_bridges(
            client, sheet,
            character_refs=char_ref_dict,
            location_refs=location_ref_dict if location_ref_dict else None,
            bible_characters=sheet.bible.characters,
        )
        succeeded_br = sum(1 for br in sheet.bridges if br.status == TaskStatus.COMPLETED)
        failed_br = sum(1 for br in sheet.bridges if br.status == TaskStatus.FAILED)
        print(f"\nBridges: {succeeded_br} succeeded, {failed_br} failed\n")

    elapsed = time.time() - start

    # Build manifest
    manifest = {
        "title": sheet.title,
        "total_duration_s": sheet.total_duration_s,
        "visual_style": sheet.visual_style,
        "aspect_ratio": sheet.aspect_ratio,
        "elapsed_s": round(elapsed, 1),
        "character_refs": [
            {
                "name": c["name"],
                "ref_image_url": c.get("ref_image_url"),
            }
            for c in sheet.bible.characters
            if c.get("ref_image_url")
        ],
        "location_refs": [
            {
                "name": loc["name"],
                "ref_image_url": loc.get("ref_image_url"),
            }
            for loc in sheet.bible.locations
            if loc.get("ref_image_url")
        ],
        "keyframes": [
            {
                "id": kf.keyframe_id,
                "shot_type": kf.shot_type,
                "status": kf.status.value,
                "image_url": kf.image_url,
                "task_id": kf.task_id,
                "error": kf.error,
            }
            for kf in sheet.keyframes
        ],
        "bridges": [
            {
                "id": br.bridge_id,
                "from": br.from_keyframe,
                "to": br.to_keyframe,
                "duration": br.duration,
                "status": br.status.value,
                "video_url": br.video_url,
                "task_id": br.task_id,
                "error": br.error,
            }
            for br in sheet.bridges
        ],
        "assembly_order": sheet.assembly_order,
        "summary": {
            "keyframes_total": len(sheet.keyframes),
            "keyframes_completed": succeeded_kf,
            "keyframes_failed": failed_kf,
            "bridges_total": len(sheet.bridges),
            "bridges_completed": succeeded_br,
            "bridges_failed": failed_br,
            "elapsed_s": round(elapsed, 1),
        },
    }

    print(f"{'='*60}")
    print(f"DISPATCH COMPLETE in {elapsed:.1f}s")
    print(f"  Keyframes: {succeeded_kf}/{len(sheet.keyframes)}")
    print(f"  Bridges:   {succeeded_br}/{len(sheet.bridges)}")
    print(f"{'='*60}")

    return manifest


# ---------------------------------------------------------------------------
# Upload assets to Google Drive
# ---------------------------------------------------------------------------

def upload_to_drive(manifest: dict, title: str) -> dict:
    """Upload all generated images and videos to a Google Drive folder.

    Creates a project folder named after the title, with subfolders:
        {title}/images/  — keyframe PNGs
        {title}/videos/  — bridge MP4s

    Updates manifest entries with 'drive_url' field.
    Returns the updated manifest.
    """
    from shared.clients.google_client import GoogleClient

    google = GoogleClient()

    # Create project folder
    project_folder = google.get_or_create_folder(title)
    project_id = project_folder["id"]
    print(f"  [drive] Project folder: {title} ({project_id})")

    images_folder = google.get_or_create_folder("images", parent_id=project_id)
    videos_folder = google.get_or_create_folder("videos", parent_id=project_id)

    uploaded = 0

    # Upload keyframe images
    for kf in manifest.get("keyframes", []):
        url = kf.get("image_url")
        if not url or kf.get("status") != "completed":
            continue
        filename = f"{kf['id']}.png"
        try:
            result = google.upload_file_from_url(
                url=url,
                name=filename,
                parent_id=images_folder["id"],
                mime_type="image/png",
            )
            drive_url = result.get("webViewLink", "")
            kf["drive_url"] = drive_url
            uploaded += 1
            print(f"  [drive] {filename} -> {drive_url}")
        except Exception as e:
            print(f"  [drive] FAILED {filename}: {e}")

    # Upload video bridges
    for br in manifest.get("bridges", []):
        url = br.get("video_url")
        if not url or br.get("status") != "completed":
            continue
        filename = f"{br['id']}.mp4"
        try:
            result = google.upload_file_from_url(
                url=url,
                name=filename,
                parent_id=videos_folder["id"],
                mime_type="video/mp4",
            )
            drive_url = result.get("webViewLink", "")
            br["drive_url"] = drive_url
            uploaded += 1
            print(f"  [drive] {filename} -> {drive_url}")
        except Exception as e:
            print(f"  [drive] FAILED {filename}: {e}")

    folder_link = f"https://drive.google.com/drive/folders/{project_id}"
    manifest["drive_folder"] = folder_link
    print(f"\n  [drive] {uploaded} files uploaded")
    print(f"  [drive] Folder: {folder_link}")

    return manifest


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Video Dispatch — generate keyframes and video bridges from a production sheet"
    )
    parser.add_argument(
        "production_sheet",
        help="Path to production sheet JSON file",
    )
    parser.add_argument(
        "--output-dir",
        default="./output",
        help="Directory to write the manifest (default: ./output)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be generated without calling APIs",
    )
    parser.add_argument(
        "--images-only",
        action="store_true",
        help="Generate keyframe images only, skip video bridges",
    )
    parser.add_argument(
        "--drive-folder",
        default=None,
        help="Upload each image to this Google Drive folder via rclone as it's generated",
    )
    args = parser.parse_args()

    # Load production sheet
    sheet_path = Path(args.production_sheet)
    if not sheet_path.exists():
        print(f"Error: {sheet_path} not found")
        return

    with open(sheet_path) as f:
        data = json.load(f)

    sheet = ProductionSheet.from_dict(data)

    # Run dispatch
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = asyncio.run(run_dispatch(
        sheet,
        dry_run=args.dry_run,
        images_only=args.images_only,
        drive_folder=args.drive_folder,
    ))

    # Write manifest BEFORE Drive upload (so it's saved even if upload fails)
    manifest_path = out_dir / f"{sheet.title.replace(' ', '_')}_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    # Upload to Google Drive (only if not already uploaded via --drive-folder rclone)
    if (not args.dry_run
            and not args.drive_folder
            and manifest.get("summary", {}).get("keyframes_completed", 0) > 0):
        print("\n--- PHASE 3: Upload to Google Drive ---")
        manifest = upload_to_drive(manifest, sheet.title)
        # Re-write manifest with drive URLs
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

    print(f"\nManifest written to: {manifest_path}")
    if manifest.get("drive_folder"):
        print(f"Google Drive: {manifest['drive_folder']}")


if __name__ == "__main__":
    main()
