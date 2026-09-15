# Drive organization

StoryEngine Assets contains one folder per channel. A private app property binds that folder to the channel tenant ID, so renames retain the same folder and identically named channels remain separate.

Each video keeps its persisted Drive folder ID and a readable title with an eight-character video ID suffix. Its asset folders are Research, Script, References, Images, Audio, Video, Thumbnails, and Other Assets. Roster and research documents live in Research; the script document lives in Script. Unknown asset categories are retained under Other Assets. Existing known legacy type folders are merged, and only empty superseded folders are trashed. Files retain their IDs and URLs.

Channel creation/profile updates provision the channel folder. Video creation and storage uploads resolve the canonical channel/video workspace. Per-channel database advisory locking serializes workspace creation. Shared non-video reference caches remain app-owned.

Give each channel owner access to their channel folder, not StoryEngine Assets. Organization does not grant permissions or send invitations. An explicit recipient and role are needed to grant access. Public individual media URLs required by rendering providers are preserved.

Existing registered videos can be inventoried with `backend/venv/bin/python scripts/organize_drive_channels.py`, and organized with `--apply`. Save stdout as the before/after receipt. The operation preserves existing video folder and file IDs, refuses shared persisted video-folder IDs, verifies folder parents, and can be rerun. Deleted video records and unrelated Drive folders are excluded.
