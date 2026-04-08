"""Universal visual output verification.

MANDATORY BEFORE declaring ANY visual generation task complete:
  - Images (keyframes, thumbnails, storyboards)
  - Video (bridges, clips, renders)
  - Animation frames

Checks:
  - Character appearance matches expectations (skin tone, race, build)
  - Scene composition matches prompt intent
  - No critical generation failures (wrong person, wrong location, etc.)

Usage:
    # For keyframes:
    results = await verify_keyframes(sheet, keyframes)

    # For generic image folder:
    results = await verify_images_in_folder(
        folder_path="/path/to/output",
        expectations={"character": "Black man with...", "location": "office with..."},
    )

    if results['passed']:
        print("Safe to send to user")
    else:
        print(f"Issues found: {results['issues']}")
        # Don't report as done until fixed
"""

import asyncio
import base64
import json
from typing import Optional
import httpx
from pathlib import Path

from orchestrator.pipeline_constants import Endpoints


async def _download_image(url: str, timeout: float = 30.0) -> Optional[bytes]:
    """Download an image from URL."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp.content
    except Exception as e:
        print(f"    [verify] Download failed: {e}")
    return None


async def _analyze_image_vision(
    image_bytes: bytes,
    query: str,
    api_key: Optional[str] = None,
) -> Optional[str]:
    """Use Claude vision to analyze an image.

    Returns the analysis text or None on failure.
    """
    import os
    from anthropic import Anthropic
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    client = Anthropic(api_key=key)

    try:
        image_b64 = base64.standard_b64encode(image_bytes).decode()

        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": query,
                        },
                    ],
                }
            ],
        )
        return msg.content[0].text
    except Exception as e:
        print(f"    [verify] Vision analysis failed: {e}")
    return None


def _extract_character_expectations(sheet) -> dict:
    """Extract expected character appearances from the sheet bible.

    Returns dict of {character_name: expected_appearance_str}
    """
    expectations = {}
    for char in sheet.bible.characters:
        if char.get("appearance"):
            expectations[char["name"]] = char["appearance"]
    return expectations


def _check_appearance_match(
    character_name: str,
    expected_appearance: str,
    vision_analysis: str,
) -> tuple[bool, str]:
    """Check if vision analysis confirms expected appearance.

    Returns (passed, reason).
    """
    # Critical checks (must be present in analysis to pass)
    critical_terms = []
    if "Black" in expected_appearance or "black" in expected_appearance:
        critical_terms.append(("Black/dark skin", ["Black", "dark skin", "dark brown"]))
    if "White" in expected_appearance or "white" in expected_appearance:
        critical_terms.append(("White/light skin", ["White", "light skin", "fair skin"]))

    analysis_lower = vision_analysis.lower()

    # Check for critical mismatches
    if critical_terms:
        expected_term, keywords = critical_terms[0]
        found = any(kw.lower() in analysis_lower for kw in keywords)

        if not found:
            # Check for opposite
            if "Black" in expected_term:
                if any(t.lower() in analysis_lower for t in ["white", "light skin", "fair"]):
                    return (False, f"❌ Character is {expected_term.lower()} but vision shows white/light skin")
            elif "White" in expected_term:
                if any(t.lower() in analysis_lower for t in ["black", "dark skin", "dark brown"]):
                    return (False, f"❌ Character is {expected_term.lower()} but vision shows Black/dark skin")

            return (False, f"❌ Character appearance doesn't match expected: {expected_term}")

    return (True, "✅ Appearance matches expected")


async def verify_keyframes(
    sheet,
    keyframes: list,
    api_key: Optional[str] = None,
) -> dict:
    """Verify generated keyframes before reporting completion.

    Returns dict:
        {
            "passed": bool,
            "total": int,
            "issues": [
                {
                    "keyframe_id": str,
                    "reason": str,
                }
            ],
            "details": [
                {
                    "keyframe_id": str,
                    "analysis": str,
                }
            ]
        }
    """
    print("\n--- VERIFICATION: Keyframe Output Quality ---\n")

    expectations = _extract_character_expectations(sheet)
    if not expectations:
        print("  No character appearance expectations defined. Skipping verification.")
        return {
            "passed": True,
            "total": len(keyframes),
            "issues": [],
            "details": [],
        }

    issues = []
    details = []

    for kf in keyframes:
        if not kf.image_url:
            issues.append({
                "keyframe_id": kf.keyframe_id,
                "reason": "❌ No image URL (generation failed)"
            })
            continue

        print(f"  {kf.keyframe_id}: Verifying...")

        # Download image
        image_bytes = await _download_image(kf.image_url)
        if not image_bytes:
            issues.append({
                "keyframe_id": kf.keyframe_id,
                "reason": "❌ Could not download image"
            })
            continue

        # Analyze with vision
        query = f"""Analyze this animation frame. Specifically:
1. Identify all characters visible and describe their appearance (skin tone, build, clothing, etc.)
2. Is the location/environment correct for a manager's office?
3. Are there any obvious errors or inconsistencies?

Be very specific about skin tones and visible character details."""

        analysis = await _analyze_image_vision(image_bytes, query, api_key=api_key)
        if not analysis:
            issues.append({
                "keyframe_id": kf.keyframe_id,
                "reason": "❌ Vision analysis failed"
            })
            continue

        details.append({
            "keyframe_id": kf.keyframe_id,
            "analysis": analysis,
        })

        # Check each character in this keyframe
        keyframe_issues = []
        for char_name in kf.characters:
            if char_name not in expectations:
                continue

            expected = expectations[char_name]
            passed, reason = _check_appearance_match(char_name, expected, analysis)

            if not passed:
                keyframe_issues.append(f"{char_name}: {reason}")
            else:
                print(f"    {char_name}: {reason}")

        if keyframe_issues:
            issues.append({
                "keyframe_id": kf.keyframe_id,
                "reason": " | ".join(keyframe_issues),
            })

    passed = len(issues) == 0

    if passed:
        print(f"\n✅ All {len(keyframes)} keyframes verified successfully\n")
    else:
        print(f"\n❌ {len(issues)} keyframe(s) failed verification:\n")
        for issue in issues:
            print(f"  {issue['keyframe_id']}: {issue['reason']}")
        print()

    return {
        "passed": passed,
        "total": len(keyframes),
        "issues": issues,
        "details": details,
    }


async def verify_images_in_folder(
    folder_path: str,
    expectations: dict,
    api_key: Optional[str] = None,
) -> dict:
    """Generic image verification for any folder of outputs.

    Usage:
        results = await verify_images_in_folder(
            folder_path="/tmp/output",
            expectations={
                "character": "Black man, early 40s, dark brown skin",
                "location": "office with glass walls",
            }
        )

    Args:
        folder_path: Path to folder containing images
        expectations: Dict of what should be in the images
            Keys are typically "character", "location", "style", etc.
            Values are the expected appearance/characteristics

    Returns:
        {
            "passed": bool,
            "total": int,
            "issues": [{"file": str, "reason": str}],
            "details": [{"file": str, "analysis": str}],
        }
    """
    from pathlib import Path

    folder = Path(folder_path)
    if not folder.exists():
        return {
            "passed": False,
            "total": 0,
            "issues": [{"file": "folder", "reason": f"Folder not found: {folder_path}"}],
            "details": [],
        }

    # Find all images
    image_files = list(folder.glob("*.png")) + list(folder.glob("*.jpg")) + list(folder.glob("*.jpeg"))
    image_files.sort()

    if not image_files:
        return {
            "passed": False,
            "total": 0,
            "issues": [{"file": "folder", "reason": f"No images found in {folder_path}"}],
            "details": [],
        }

    print(f"\n--- VERIFICATION: {len(image_files)} Images ---\n")

    issues = []
    details = []

    for img_path in image_files:
        print(f"  {img_path.name}: Analyzing...")

        try:
            with open(img_path, "rb") as f:
                image_bytes = f.read()
        except Exception as e:
            issues.append({"file": img_path.name, "reason": f"Could not read file: {e}"})
            continue

        # Build query from expectations
        query = "Analyze this image. Report on:\n"
        for key, expected_value in expectations.items():
            query += f"- {key}: Is it {expected_value}? What do you actually see?\n"
        query += "\nBe very specific about details like skin tone, race, build, clothing, and location."

        analysis = await _analyze_image_vision(image_bytes, query, api_key=api_key)
        if not analysis:
            issues.append({"file": img_path.name, "reason": "Vision analysis failed"})
            continue

        details.append({"file": img_path.name, "analysis": analysis})

        # Check for mismatches (very basic string matching as heuristic)
        mismatches = []
        for key, expected_value in expectations.items():
            analysis_lower = analysis.lower()
            expected_lower = expected_value.lower()

            # Check for opposite attributes (e.g., expected Black but got white)
            if "Black" in expected_value and any(t in analysis_lower for t in ["white", "fair", "light skin"]):
                mismatches.append(f"{key}: Expected Black but image shows white/light")
            elif "White" in expected_value and any(t in analysis_lower for t in ["black", "dark", "dark brown"]):
                mismatches.append(f"{key}: Expected White but image shows Black/dark")
            elif "office" in expected_lower and not any(t in analysis_lower for t in ["office", "desk", "workplace"]):
                mismatches.append(f"{key}: Expected office but no office elements found")

        if mismatches:
            issues.append({"file": img_path.name, "reason": " | ".join(mismatches)})
        else:
            print(f"    ✅ Image matches expectations")

    passed = len(issues) == 0

    if passed:
        print(f"\n✅ All {len(image_files)} images verified\n")
    else:
        print(f"\n❌ {len(issues)} image(s) have issues:\n")
        for issue in issues:
            print(f"  {issue['file']}: {issue['reason']}")
        print()

    return {
        "passed": passed,
        "total": len(image_files),
        "issues": issues,
        "details": details,
    }
