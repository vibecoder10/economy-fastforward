-- Store per-tenant Google Drive OAuth refresh token (encrypted at rest by Supabase)
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS google_drive_refresh_token TEXT;
