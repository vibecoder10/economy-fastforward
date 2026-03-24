"""Allow running osiris package directly: python -m osiris

Usage:
    python -m osiris                 # Run competitor scraper (default)
    python -m osiris analyze         # Run performance analyzer
    python -m osiris --dry-run       # Dry run competitor scraper
    python -m osiris analyze --dry-run  # Dry run performance analyzer
"""

import asyncio
import sys


if __name__ == "__main__":
    # Check if "analyze" subcommand is specified
    if len(sys.argv) > 1 and sys.argv[1] == "analyze":
        # Remove "analyze" from argv so argparse in performance_analyzer works correctly
        sys.argv.pop(1)
        from analytics.osiris.performance_analyzer import _cli_main as analyze_main
        asyncio.run(analyze_main())
    else:
        # Default: run competitor scraper
        from analytics.osiris.competitor_scraper import _cli_main as scraper_main
        asyncio.run(scraper_main())
