# Script ↔ Google Drive Sync — Spec / Handoff

> Status: SCOPED, not started. Owner: next session. Created 2026-06-14.
> Queue item #5 in `todo.md` points here.

## Goal (Ryan, 2026-06-14)

Let the creator **edit a video's script inside their own Google Drive** — as an
editable Google Doc — using **any AI tool** they like, and have those edits **mirror
back into StoryEngine**. The vision: a creator can work entirely out of Drive,
AI-agnostic, and **owns their data**. The heavy media already lives on their Drive
(clips, images, audio — see the storage split); this extends that ownership to the
**script text**, which today lives only in our Postgres.

## Source-of-truth model (read this first — it's the whole design)

**Postgres stays the operational source of truth.** The pipeline constantly queries
`scripts.scene_text` / `videos.script` (script bot, voice, image prompts, render), so
the script text MUST stay queryable in Postgres. **Drive is an editable *mirror*** the
creator can work in between syncs. Sync is **explicit and directional** (buttons, not
magic) with a modifiedTime guard so neither side silently clobbers the other:

- **Push** (Postgres → Doc): on script generate/update + a manual "Open/Update in Drive".
- **Pull** (Doc → Postgres): a manual "Sync from Drive" (MVP). Drive-wins for the text on
  an explicit pull; warn if both sides changed since the last sync.

## What EXISTS (reuse — don't rebuild)

- **Per-tenant Drive OAuth.** `channel_profiles.google_drive_refresh_token`; flow in
  `routes/google_auth.py:472-567`; scope `drive.file` (app-owned files only — so WE must
  create the Doc; the user can't point us at an arbitrary file. Fine for our model).
- **Token refresh pattern.** `_maybe_upload_brief_to_drive` (`routes/model_video.py:637-693`)
  — refresh_token → access_token → Drive API. Copy this.
- **GoogleClient** (`skills/video-pipeline/shared/clients/google_client.py`):
  `get_or_create_folder` (168), `create_document(title, folder_id)` → **editable Google Doc**
  (652), `append_to_document(doc_id, text)` via Docs `batchUpdate` (693), `get_document_url`
  (734). It ALSO already calls `docs_service.documents().get(documentId=doc_id)` at line 710
  — i.e. reading a Doc back is half-built.
- **Per-video Drive folder.** `storage.py:_resolve_video_drive_folder(video_id)` (124-150) +
  `videos.drive_folder_id` / `drive_folder_link` columns. Drop the Script Doc here.
- **Script data model.** `scripts` table = one row per scene (`scene` INT, `scene_text` TEXT,
  `title`); `videos.script` = full text. Schema `schema.sql:230-273`.
- **In-app edit API.** `PATCH /api/videos/{id}/scenes/{scene}/text` (`routes/videos.py:743`).

## What's MISSING (build)

1. **Write the full script as a scene-delimited editable Doc** (Push). Reuse `create_document`
   + a new `replace_document_body(doc_id, text)` (Docs `batchUpdate`: delete range + insert —
   mirror `append_to_document`'s pattern).
2. **Read a Doc back to text** (Pull). New `read_document_text(doc_id)` — the `documents().get()`
   call already exists at line 710; walk `document.body.content[].paragraph.elements[].textRun`.
3. **Scene mapping contract.** Doc ↔ per-scene `scripts` rows. Cleanest: write each scene under a
   delimiter line the parser keys on — `### SCENE {n} — {title}` (or a fenced marker). On Pull,
   split on those headers → map to `scripts.scene`. Parse leniently; if markers are missing/edited,
   FAIL LOUD ("couldn't find the scene markers — keep the `### SCENE n` lines"), never silently
   mis-map.
4. **Change detection.** MVP: compare the Doc's `modifiedTime` (`drive_service.files().get(fileId,
   fields="modifiedTime")`) against a stored value on script-page load → show "Drive has newer
   edits — Sync?". Manual Pull button. (Watch/push channels = Phase 3, probably skip.)
5. **Per-video Doc cache + sync state.** Migration: `videos.drive_script_doc_id TEXT`,
   `videos.drive_script_synced_at TIMESTAMPTZ`, `videos.drive_script_doc_modified_at TIMESTAMPTZ`.
6. **Downstream-staleness on Pull.** A pulled scene-text change makes that scene's voice/images/
   clips stale. On import, for each CHANGED scene clear its downstream so it regenerates (mirror
   how fix-text clears `video_clip_url`): null `scripts.voice_over_url`/`voice_status` and the
   scene's `assets` image/clip urls — OR at minimum WARN "synced scenes need re-voicing/re-imaging".
7. **UI.** Script view: "Edit in Google Drive" (Push + open), "Sync from Drive" (Pull, shown when a
   Doc exists), and a "Drive edited since last sync" badge.

## Phased plan

**Phase 1 — Push (one-way, ships value immediately).**
- `GoogleClient.replace_document_body(doc_id, text)`.
- `POST /api/videos/{id}/script/push-to-drive`: build scene-delimited text from `scripts` rows →
  create (or `replace_document_body` if `drive_script_doc_id` set) the Doc in the video's Drive
  folder → store `drive_script_doc_id` + `drive_script_synced_at` → return Doc URL.
- Frontend "Edit in Google Drive" button → opens the Doc.
- Verify: Doc appears in the creator's Drive, editable, correctly scene-delimited.

**Phase 2 — Pull (the round-trip).**
- `GoogleClient.read_document_text(doc_id)`.
- `POST /api/videos/{id}/script/sync-from-drive`: read Doc → split by `### SCENE n` → diff vs
  `scripts.scene_text` → `UPDATE` changed scenes + rebuild `videos.script` → mark changed scenes'
  downstream stale (#6) → update sync state. Guard: if `modifiedTime <= drive_script_doc_modified_at`
  nothing changed; if BOTH app and Doc changed since last sync, return a conflict the UI surfaces.
- Frontend "Sync from Drive" + the "edited since last sync" badge.
- Verify: edit a scene in the Doc → Sync → that scene's text updates in-app and its clip/voice show stale.

**Phase 3 — Auto-detect (optional).** modifiedTime poll on page load is likely enough. Drive watch
channels (webhook, ~7-day expiry, signature verify) are high-effort — only if real-time is wanted.

## Landmines

- **Scene-marker contract is the fragile bit.** If the creator breaks the `### SCENE n` lines, Pull
  can't map. Keep markers dead-simple, parse leniently, FAIL LOUD with a fix hint — never guess.
- **`drive.file` scope** → the Doc must be app-created (it is). The app can't read files it didn't make.
- **Conflict/clobber.** Directional buttons + modifiedTime guard. No silent two-way auto-merge in v1.
- **Downstream staleness** (#6) — editing text post-voice/images silently desyncs the video unless we
  mark stale. Don't skip this.
- **Pipeline unaffected.** Postgres remains the only thing the pipeline queries; Drive is never the
  operational store. Sync only touches `scripts.scene_text` / `videos.script` (+ stale flags).

## Rough size

Phase 1 ≈ 1 GoogleClient method + 1 endpoint + 1 migration + 1 button (small, shippable alone).
Phase 2 ≈ 2 methods + 1 endpoint + scene parser + conflict/stale handling + 2 UI controls (medium).
Needs a Drive-connected tenant to test (Ryan's is connected — `channel_profiles.google_drive_refresh_token`).
