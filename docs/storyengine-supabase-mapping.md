# StoryEngine -> Supabase Production Mapping

This repo currently contains two competing models:

1. A prototype `Project` model in `storyengine/frontend/prisma/schema.prisma`
2. A production-oriented Supabase schema already migrated from Airtable

The UI transition has been painful because Airtable was not just a database. It
was also the workflow engine, operator console, and pipeline contract.

The correct direction is:

- Treat Supabase production tables as the source of truth
- Treat StoryEngine UI as a control/view layer over those tables
- Stop deepening the local Prisma `Project` abstraction unless it becomes a
  pure view model instead of a persisted data model

## Production Tables Seen In Supabase

From the current Supabase workspace and screenshot:

- `videos`
- `scripts`
- `assets`
- `stage_transitions`
- `channel_profiles`
- `visual_styles`
- `style_characters`
- `users`
- `memberships`
- `tenants`

## Recommended Ownership

## Storage Rule

Use a strict split:

- Supabase stores text, metadata, statuses, references, and logs
- Google Drive stores generated binary assets

That means:

- `scripts.voice_over_url` should point to Google Drive
- `assets.image_url` should point to Google Drive
- `assets.video_url` / `assets.video_clip_url` should point to Google Drive
- sound effects and thumbnails should also resolve to Google Drive URLs

Pipeline contract for every generated file:

1. Generate through provider
2. Upload or proxy the binary into Google Drive
3. Save the Drive URL and file metadata into Supabase
4. Log the stage transition in Supabase

### `videos`

Top-level production record.

Suggested responsibility:

- title
- top-level status
- tenant / membership ownership
- selected profile / visual style
- upload / render metadata

### `scripts`

Scene-level narration and voiceover state.

Observed columns in the screenshot:

- `title`
- `scene_text`
- `script_status`
- `voice_status`
- `voice_over_url`

Likely or recommended columns:

- `id`
- `video_id`
- `scene_number`

Temporary fallback if `video_id` is not available everywhere:

- join by `title`

### `assets`

Prompt and media artifact table.

Suggested responsibility:

- prompt rows
- images
- video clips
- thumbnails
- audio derivatives
- provider task metadata
- Google Drive file URLs and IDs where available

Likely or recommended fields:

- `video_id`
- `script_id` or `scene_number`
- `asset_type`
- `status`
- `prompt_text`
- `asset_url`

### `stage_transitions`

Append-only workflow log.

Suggested responsibility:

- every pipeline step start / completion / error
- trigger source
- timestamps
- operator / automation provenance

## UI Mapping

### Dashboard

Should read from `videos`, not a local `projects` table.

### New Project

Should create a `videos` row.

### Detail Page

Should aggregate:

- `videos` -> header and overall status
- `scripts` -> scene cards and voice state
- `assets` -> prompts, images, clips
- `stage_transitions` -> activity log / progress timeline

### Image Prompt Generation

Should read:

- `videos`
- `scripts`
- selected style/profile tables

Should write:

- prompt rows to `assets`
- lifecycle rows to `stage_transitions`
- optional top-level status changes to `videos`

## Migration Strategy

1. Introduce Supabase-backed read services for `videos/scripts/assets/stage_transitions`
2. Add API routes that expose a `VideoDetailViewModel` to the frontend
3. Switch UI screens to those routes
4. Retire Prisma-backed `Project` persistence
5. Keep Prisma only if it remains necessary for auth during a transition period

## Logging Contract

Every pipeline stage should produce log rows in `stage_transitions`:

- `queued`
- `started`
- `completed`
- `failed`

Suggested payload:

- `video_id`
- `stage`
- `status`
- `source`
- `message`
- `metadata`
- `created_at`

## Current Risk

The repo does not yet contain the exact Supabase schema contract in code, so the
initial Supabase service layer must be resilient to small naming differences
while we finish swapping routes over.
