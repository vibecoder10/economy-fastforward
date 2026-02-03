#!/usr/bin/env python3
"""CLI for Thumbnail Generator Pipeline.

Usage:
    # Generate thumbnail for a specific video by Airtable record ID
    python run_thumbnail_pipeline.py --video-id recXXXXXXXXX

    # Process next video in queue (status = "Ready For Thumbnail")
    python run_thumbnail_pipeline.py --next

Examples:
    python run_thumbnail_pipeline.py --video-id recABC123xyz
    python run_thumbnail_pipeline.py -v recABC123xyz
    python run_thumbnail_pipeline.py --next
"""

import argparse
import asyncio
import sys
import traceback

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


async def main():
    """Run the thumbnail pipeline."""
    parser = argparse.ArgumentParser(
        description="Generate thumbnails for video production pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python run_thumbnail_pipeline.py --video-id recABC123xyz
    python run_thumbnail_pipeline.py -v recABC123xyz
    python run_thumbnail_pipeline.py --next
        """,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--video-id",
        "-v",
        type=str,
        help="Airtable record ID for the video idea",
    )
    group.add_argument(
        "--next",
        "-n",
        action="store_true",
        help="Process the next video with status 'Ready For Thumbnail'",
    )

    args = parser.parse_args()

    # Import pipeline after loading env vars
    from thumbnail_pipeline import ThumbnailPipeline

    pipeline = ThumbnailPipeline()

    try:
        if args.video_id:
            # Run for specific video ID
            result = await pipeline.run(args.video_id)
        else:
            # Run for next video in queue
            result = await pipeline.run_next()

        # Handle result
        if result is None:
            print("\n⚠️  No videos found to process.")
            sys.exit(0)

        if result.get("success"):
            print(f"\n✅ Thumbnail generated successfully!")
            print(f"   URL: {result.get('thumbnail_url')}")
            sys.exit(0)
        else:
            print(f"\n❌ Thumbnail generation failed!")
            print(f"   Error: {result.get('error')}")
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ Pipeline error: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
