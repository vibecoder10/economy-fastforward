"""Look up a production sheet by Drive folder name or fuzzy match.

Usage:
    python3 -m video_dispatch.lookup "midnight builder v6"
    python3 -m video_dispatch.lookup "midnight builder"
    python3 -m video_dispatch.lookup --list

Returns the production sheet path and manifest status.
"""

import json
import sys
from pathlib import Path

DISPATCH_DIR = Path(__file__).parent
OUTPUT_DIR = DISPATCH_DIR.parent / "output"


def find_sheet(query: str) -> dict:
    """Find a production sheet matching a fuzzy query."""
    query_lower = query.lower().strip()
    sheets = list(DISPATCH_DIR.glob("*.json"))

    results = []
    for sheet_path in sheets:
        try:
            with open(sheet_path) as f:
                data = json.load(f)
            title = data.get("title", "")
        except (json.JSONDecodeError, KeyError):
            continue

        # Check if query matches title or filename
        title_lower = title.lower()
        name_lower = sheet_path.stem.lower().replace("_", " ").replace("-", " ")

        if query_lower in title_lower or query_lower in name_lower:
            # Check for existing manifest
            manifest_name = f"{title.replace(' ', '_')}_manifest.json"
            manifest_path = OUTPUT_DIR / manifest_name
            has_manifest = manifest_path.exists()

            manifest_info = {}
            if has_manifest:
                try:
                    with open(manifest_path) as f:
                        manifest = json.load(f)
                    if manifest.get("status") != "dry_run":
                        kf_count = len([k for k in manifest.get("keyframes", []) if k.get("image_url")])
                        br_count = len([b for b in manifest.get("bridges", []) if b.get("video_url")])
                        manifest_info = {
                            "has_images": kf_count > 0,
                            "keyframes_ready": kf_count,
                            "bridges_ready": br_count,
                        }
                except (json.JSONDecodeError, KeyError):
                    pass

            results.append({
                "title": title,
                "sheet_path": str(sheet_path),
                "manifest_path": str(manifest_path) if has_manifest else None,
                "manifest": manifest_info,
            })

    return results


def list_sheets():
    """List all production sheets."""
    sheets = list(DISPATCH_DIR.glob("*.json"))
    for sheet_path in sorted(sheets):
        try:
            with open(sheet_path) as f:
                data = json.load(f)
            title = data.get("title", sheet_path.stem)
            kf_count = len(data.get("keyframes", []))
            br_count = len(data.get("bridges", []))
            print(f"  {sheet_path.name:45s} | {title:35s} | {kf_count} KFs, {br_count} bridges")
        except (json.JSONDecodeError, KeyError):
            continue


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] == "--list":
        print("Available production sheets:")
        list_sheets()
        sys.exit(0)

    query = " ".join(sys.argv[1:])
    results = find_sheet(query)

    if not results:
        print(f"No production sheet matching '{query}'")
        sys.exit(1)

    for r in results:
        print(f"Title: {r['title']}")
        print(f"Sheet: {r['sheet_path']}")
        if r['manifest']:
            m = r['manifest']
            print(f"Images: {'ready' if m.get('has_images') else 'not generated'} ({m.get('keyframes_ready', 0)} keyframes)")
            print(f"Videos: {m.get('bridges_ready', 0)} bridges")
            if m.get('has_images') and m.get('bridges_ready', 0) == 0:
                print(f"Action: run --bridges-only to generate videos")
        else:
            print(f"Status: not yet generated")
            print(f"Action: run --images-only first")
        print()
