#!/usr/bin/env python3
"""Compile the locked Below the Forecast treatment without provider work."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from custom_film_scene_storyboards import compile_below_the_forecast_fixture


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=BACKEND.parent / "tasks/below-the-forecast-storyboard.md",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    fixture = compile_below_the_forecast_fixture(args.source)
    rendered = json.dumps(fixture, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
