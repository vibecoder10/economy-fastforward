"""Video Dispatch Engine — orchestrates keyframe + bridge generation.

Usage:
    python -m video_dispatch.dispatch production_sheet.json [--output-dir ./output]
    python -m video_dispatch.dispatch production_sheet.json --dry-run

Flow:
    1. Parse production sheet JSON
    2. Generate all keyframe images (Nano Banana Pro / Grok text-to-image)
    3. Generate video bridges between keyframes (Grok image-to-video)
    4. Write manifest with all URLs for assembly
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

IMAGE_MODEL = "grok-imagine/text-to-image"
VIDEO_MODEL = "grok-imagine/image-to-video"

# Polling tuning
IMAGE_INITIAL_WAIT = 5.0
IMAGE_POLL_INTERVAL = 2.0
IMAGE_POLL_MAX = 60

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

    async def generate_keyframe(self, kf: Keyframe) -> Keyframe:
        """Generate a single keyframe image via text-to-image."""
        kf.status = TaskStatus.IN_PROGRESS
        print(f"  [keyframe] {kf.keyframe_id}: generating ({kf.shot_type})...")

        payload = {
            "model": IMAGE_MODEL,
            "input": {
                "prompt": kf.prompt,
                "aspect_ratio": kf.aspect_ratio,
            },
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
    ) -> Bridge:
        """Generate a video bridge from a keyframe image."""
        bridge.status = TaskStatus.IN_PROGRESS
        print(
            f"  [bridge] {bridge.bridge_id}: {bridge.from_keyframe} -> "
            f"{bridge.to_keyframe} ({bridge.duration}s)..."
        )

        # Clamp duration to API limits (6-30s)
        duration = max(6, min(30, bridge.duration))

        payload = {
            "model": VIDEO_MODEL,
            "input": {
                "image_urls": [from_image_url],
                "prompt": bridge.prompt,
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

async def dispatch_keyframes(
    client: DispatchClient,
    keyframes: list[Keyframe],
) -> list[Keyframe]:
    """Generate all keyframe images with bounded concurrency."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_IMAGES)

    async def _gen(kf: Keyframe) -> Keyframe:
        async with semaphore:
            return await client.generate_keyframe(kf)

    return await asyncio.gather(*[_gen(kf) for kf in keyframes])


async def dispatch_bridges(
    client: DispatchClient,
    sheet: ProductionSheet,
) -> list[Bridge]:
    """Generate all video bridges with bounded concurrency.

    Each bridge uses the image_url from its source keyframe.
    Bridges whose source keyframe failed are skipped.
    """
    kf_map = {kf.keyframe_id: kf for kf in sheet.keyframes}
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_VIDEOS)

    async def _gen(br: Bridge) -> Bridge:
        source_kf = kf_map.get(br.from_keyframe)
        if not source_kf or not source_kf.image_url:
            br.status = TaskStatus.FAILED
            br.error = f"Source keyframe {br.from_keyframe} has no image"
            print(f"  [bridge] {br.bridge_id}: SKIPPED (no source image)")
            return br
        async with semaphore:
            return await client.generate_bridge(br, source_kf.image_url)

    return await asyncio.gather(*[_gen(br) for br in sheet.bridges])


async def run_dispatch(
    sheet: ProductionSheet,
    api_key: Optional[str] = None,
    dry_run: bool = False,
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

    if dry_run:
        print("[DRY RUN] Would generate:")
        for kf in sheet.keyframes:
            print(f"  Image: {kf.keyframe_id} ({kf.shot_type}) — {kf.prompt[:60]}...")
        for br in sheet.bridges:
            print(
                f"  Video: {br.bridge_id} ({br.from_keyframe}->{br.to_keyframe}, "
                f"{br.duration}s) — {br.prompt[:60]}..."
            )
        return {"status": "dry_run", "keyframes": len(sheet.keyframes), "bridges": len(sheet.bridges)}

    client = DispatchClient(api_key=api_key)

    # Phase 1: Generate all keyframe images
    print("--- PHASE 1: Keyframe Images ---")
    await dispatch_keyframes(client, sheet.keyframes)

    succeeded_kf = sum(1 for kf in sheet.keyframes if kf.status == TaskStatus.COMPLETED)
    failed_kf = sum(1 for kf in sheet.keyframes if kf.status == TaskStatus.FAILED)
    print(f"\nKeyframes: {succeeded_kf} succeeded, {failed_kf} failed\n")

    # Phase 2: Generate video bridges (needs keyframe images)
    print("--- PHASE 2: Video Bridges ---")
    await dispatch_bridges(client, sheet)

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
    manifest = asyncio.run(run_dispatch(sheet, dry_run=args.dry_run))

    # Write manifest
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / f"{sheet.title.replace(' ', '_')}_manifest.json"

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nManifest written to: {manifest_path}")


if __name__ == "__main__":
    main()
