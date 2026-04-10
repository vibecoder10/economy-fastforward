-- Google Drive folder selection for per-tenant asset storage
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS google_drive_folder_id TEXT;
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS google_drive_folder_name TEXT;
