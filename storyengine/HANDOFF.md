# HANDOFF - 2026-09-25 - helicopter video RENDERED; upload blocked: DvsU YouTube login expired

## State
- Prod: `39feb0138` deployed 19:15Z (backend+worker). Healthy. NO lock.
- Branch: main, pushed.
- Shipped: static docs (DvsU) skip the thumbnail stage (status_map.static_stage_plan drops 'thumbnail').
  That also stops the title overwrite for this channel (writer: skills/video-pipeline/thumbnail/run.py:156).
- Prod data: 'thumbnail' removed from pipeline_stages on 7 unfinished DvsU videos; thumbnail_url cleared on 59fd34a4
  (Ryan: this channel needs no thumbnail; file still in Drive).
- Video 59fd34a4 "Most Hated Helicopters to Fly by Pilots Ever (2026)": status `rendered`.
  Drive file 1WbIdZ3fSnoCxe7EhQkW-wMaJiN28_IrR, 1080p, 17:39 long, audio mean -21 dB, no silences > 3s.
  7 sampled frames: right machine under each label (H-13, CH-37, Belvedere, CH-53, Mi-24, AH-64, NH90).
- Upload FAILED: "Could not verify the YouTube owner." Cause: DvsU channel_profiles.youtube_refresh_token ->
  Google `invalid_grant: Token has been expired or revoked` (token saved 2026-09-12).

## Next action (start here cold)
1. Ryan reconnects YouTube for the Designed Vs Used workspace (Settings page, connect channel UCO4gtSa3rpOutrZ45-OjYyA).
2. Reset queue item 3e6d4329 (status queued, attempt_count 0) and relaunch it (POST
   `/api/queue/3e6d4329-8fa9-424f-9be6-df657cd6393a/launch`, header `X-Active-Tenant: 561b872d-7b73-45e3-9c44-7f30c3566eda`;
   easiest from the VPS on 127.0.0.1:8001 with /tmp/se_token). It resumes at upload (rendered).
3. Watch the relay: the run parks model calls (e.g. `_select_music_beds`) and waits for an answer.

## Open threads
- AutoYTSync logged "sync complete" for tenant 561b872d at 19:15 with a dead token - it hides the failure. Nobody was warned.
- Stale relay request 9dd58f35 (script paragraph, wrong title "The Helicopters Every Pilot DREADED Flying") from the
  bounced run is still pending. Do NOT answer it.
- Burned-in captions end in "..." (truncated) on most frames.
- Runtime 17.6 min vs 20 min set length.
- Other channels: thumbnail stage still overwrites video_title (harmless there today; only dvsu_script_v2 keys on it).
- backend/tests/test_dvsu_saved_evidence_replay.py: 3 tests fail on main (before this session's change).
- Script notes from before: scene 4 (H-43 Huskie) does not fit "most hated"; CH-46 used unsourced "stopgap".

## Gotchas learned this session
- A queue relaunch COALESCEs pipeline_stages: an old plan stays. Fix old rows by hand when the plan changes.
- se db output order varies: grep for lines starting with `{`.
- Big Drive files: ffprobe on the uc?export=download URL fails (virus-scan page). Use the Drive API get_media.
