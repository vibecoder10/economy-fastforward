-- Brand Kit: add accent_color and logo_url to channel_profiles
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS accent_color TEXT DEFAULT '';
ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS logo_url TEXT DEFAULT '';
