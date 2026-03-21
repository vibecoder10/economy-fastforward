# skills/video-pipeline/tests/test_ctr_12h_tracking.py
"""Tests for CTR 12h/24h/48h snapshot tracking."""

import pytest
from datetime import datetime, timedelta, timezone
from performance_tracker import calculate_snapshots
from pipeline_constants import IdeaFields


class TestCTRMilestoneTracking:
    """Test CTR milestone snapshot writing."""

    def test_12h_ctr_snapshot_written_at_12_hours(self):
        """CTR 12h should be written when video is 12+ hours old."""
        published = datetime.now(timezone.utc) - timedelta(hours=13)
        upload_date = published.isoformat()

        stats = {"views": 1000, "likes": 50, "comments": 10}
        analytics = None
        existing_fields = {}
        reporting = {"impressions": 500, "ctr": 4.5}

        snapshots = calculate_snapshots(
            stats=stats,
            analytics=analytics,
            upload_date=upload_date,
            existing_fields=existing_fields,
            reporting=reporting,
        )

        assert IdeaFields.CTR_12H in snapshots
        assert snapshots[IdeaFields.CTR_12H] == 4.5

    def test_12h_ctr_snapshot_not_written_if_exists(self):
        """CTR 12h should NOT be overwritten if already set."""
        published = datetime.now(timezone.utc) - timedelta(hours=15)
        upload_date = published.isoformat()

        stats = {"views": 1000, "likes": 50, "comments": 10}
        existing_fields = {IdeaFields.CTR_12H: 3.8}  # Already has value
        reporting = {"impressions": 500, "ctr": 4.5}

        snapshots = calculate_snapshots(
            stats=stats,
            analytics=None,
            upload_date=upload_date,
            existing_fields=existing_fields,
            reporting=reporting,
        )

        assert IdeaFields.CTR_12H not in snapshots

    def test_12h_ctr_not_written_if_too_young(self):
        """CTR 12h should NOT be written if video < 12 hours old."""
        published = datetime.now(timezone.utc) - timedelta(hours=8)
        upload_date = published.isoformat()

        stats = {"views": 500, "likes": 20, "comments": 5}
        reporting = {"impressions": 200, "ctr": 5.0}

        snapshots = calculate_snapshots(
            stats=stats,
            analytics=None,
            upload_date=upload_date,
            existing_fields={},
            reporting=reporting,
        )

        assert IdeaFields.CTR_12H not in snapshots

    def test_24h_ctr_snapshot_written_at_24_hours(self):
        """CTR 24h should be written when video is 24+ hours old."""
        published = datetime.now(timezone.utc) - timedelta(hours=25)
        upload_date = published.isoformat()

        stats = {"views": 2000, "likes": 100, "comments": 20}
        existing_fields = {IdeaFields.CTR_12H: 3.5}  # 12h already set
        reporting = {"impressions": 1000, "ctr": 4.8}

        snapshots = calculate_snapshots(
            stats=stats,
            analytics=None,
            upload_date=upload_date,
            existing_fields=existing_fields,
            reporting=reporting,
        )

        assert IdeaFields.CTR_24H in snapshots
        assert snapshots[IdeaFields.CTR_24H] == 4.8

    def test_ctr_12h_not_written_without_reporting_data(self):
        """CTR snapshots should not be written if no reporting data available."""
        published = datetime.now(timezone.utc) - timedelta(hours=15)
        upload_date = published.isoformat()

        stats = {"views": 1000, "likes": 50, "comments": 10}

        snapshots = calculate_snapshots(
            stats=stats,
            analytics=None,
            upload_date=upload_date,
            existing_fields={},
            reporting=None,  # No reporting data
        )

        assert IdeaFields.CTR_12H not in snapshots
        assert IdeaFields.CTR_24H not in snapshots

    def test_all_ctr_snapshots_at_48_hours(self):
        """At 48+ hours, all CTR snapshots should be written if not already set."""
        published = datetime.now(timezone.utc) - timedelta(hours=50)
        upload_date = published.isoformat()

        stats = {"views": 5000, "likes": 250, "comments": 50}
        analytics = {"avg_retention": 45.0, "avg_view_duration": 180, "watch_time_hours": 25, "subscribers_gained": 10, "views": 5000}
        reporting = {"impressions": 3000, "ctr": 5.2}

        snapshots = calculate_snapshots(
            stats=stats,
            analytics=analytics,
            upload_date=upload_date,
            existing_fields={},
            reporting=reporting,
        )

        assert IdeaFields.CTR_12H in snapshots
        assert IdeaFields.CTR_24H in snapshots
        assert IdeaFields.CTR_48H in snapshots
