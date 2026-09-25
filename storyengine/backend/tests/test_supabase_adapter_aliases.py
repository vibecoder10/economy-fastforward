"""A videos column that two Airtable names share must reach both names.

"Drive Folder ID" and "Google Drive Folder ID" both map to drive_folder_id.
The reverse map kept only one, so the clip bot (which reads "Drive Folder ID")
uploaded to parent '' and the build died with a Drive 404.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase_adapter import _row_to_idea


def test_shared_column_fills_every_airtable_name():
    idea = _row_to_idea({
        "id": "v1",
        "drive_folder_id": "folder-123",
        "final_video_url": "https://example.com/v.mp4",
    })
    assert idea["Drive Folder ID"] == "folder-123"
    assert idea["Google Drive Folder ID"] == "folder-123"
    assert idea["Final Video"] == "https://example.com/v.mp4"
    assert idea["Final Video URL"] == "https://example.com/v.mp4"
