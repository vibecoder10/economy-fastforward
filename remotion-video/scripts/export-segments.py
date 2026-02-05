#!/usr/bin/env python3
"""
Export segment data from Airtable to TypeScript for Remotion.

This script fetches segment texts from Airtable and generates a TypeScript
file that maps scenes to their segment texts, enabling accurate word-to-image
alignment in Remotion videos.

Usage:
    python scripts/export-segments.py

Output:
    src/segmentData.ts - TypeScript file with segment text mappings
"""

import os
import sys
import json

# Add the video-pipeline to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'skills', 'video-pipeline'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from clients.airtable_client import AirtableClient


def export_segments_for_video(video_title: str) -> dict[int, list[str]]:
    """Fetch all segment texts for a video from Airtable.

    Returns:
        Dict mapping scene number to list of segment texts
    """
    client = AirtableClient()
    images = client.get_all_images_for_video(video_title)

    # Group by scene and sort by image index
    scenes: dict[int, list[dict]] = {}
    for img in images:
        scene = img.get("Scene", 0)
        if scene not in scenes:
            scenes[scene] = []
        scenes[scene].append(img)

    # Sort each scene by image index and extract texts
    result: dict[int, list[str]] = {}
    for scene_num, scene_images in scenes.items():
        sorted_images = sorted(scene_images, key=lambda x: x.get("Image Index", 0))
        texts = [img.get("Sentence Text", "") for img in sorted_images if img.get("Sentence Text")]
        if texts:
            result[scene_num] = texts

    return result


def generate_typescript(segments_by_scene: dict[int, list[str]]) -> str:
    """Generate TypeScript code for segment data."""

    lines = [
        "// Auto-generated segment data from Airtable",
        "// This file maps scenes to their segment texts for word-to-image alignment",
        "",
        "export const sceneSegmentTexts: Record<number, string[]> = {",
    ]

    for scene_num in sorted(segments_by_scene.keys()):
        texts = segments_by_scene[scene_num]
        # Escape quotes in text
        escaped_texts = [text.replace('"', '\\"').replace('\n', ' ') for text in texts]
        texts_str = ',\n        '.join([f'"{t}"' for t in escaped_texts])
        lines.append(f"    {scene_num}: [")
        lines.append(f"        {texts_str}")
        lines.append(f"    ],")

    lines.append("};")
    lines.append("")

    return "\n".join(lines)


def main():
    # Get video title from args or use default
    video_title = sys.argv[1] if len(sys.argv) > 1 else "The 2030 Currency Collapse: Which Assets Will YOU Still Own?"

    print(f"Exporting segments for: {video_title}")
    print("=" * 60)

    segments = export_segments_for_video(video_title)

    if not segments:
        print("No segments found! Make sure the video has been processed through the pipeline.")
        return

    print(f"Found {len(segments)} scenes with segments:")
    for scene, texts in sorted(segments.items()):
        print(f"  Scene {scene}: {len(texts)} segments")

    # Generate TypeScript
    ts_content = generate_typescript(segments)

    # Write to file
    output_path = os.path.join(os.path.dirname(__file__), '..', 'src', 'segmentData.ts')
    with open(output_path, 'w') as f:
        f.write(ts_content)

    print(f"\nGenerated: {output_path}")
    print("\nTo use this data, update src/segments.ts to import from segmentData.ts")


if __name__ == "__main__":
    main()
