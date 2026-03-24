"""
Run the Performance Tracker to sync YouTube analytics to Airtable.

Called by: pipeline_control.py (Slack bot) via `analytics` command
Also runs daily via cron (setup_cron.sh, 7 AM PT)

Fetches lifetime stats and analytics for all uploaded videos,
writes metrics to Airtable, and captures time-bucketed snapshots.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from performance_tracker import main


if __name__ == "__main__":
    recent = "--recent" in sys.argv
    dry = "--dry-run" in sys.argv
    main(recent_only=recent, dry_run=dry)
