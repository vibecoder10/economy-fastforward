# HANDOFF - 2026-09-25 - helicopter relay rerun reached render; 3 pipeline bugs fixed; title-overwrite bug open

## State
- Prod: `03280fb5f` deployed 18:33Z (backend+worker only). Healthy. NO lock. Nothing running.
- Branch: main, clean, pushed. No feature worktrees left.
- What shipped this session:
  - Reaper no longer fails a Run All (autobuild) row at 3h; it waits for the 12h job limit + 1h.
  - supabase_adapter: a column shared by two Airtable names fills both ("Drive Folder ID" was always '').
  - Static docs never animate: hard clip guard in run_video_scripts / run_video_generation / run_next_step /
    run_clip_generation (keyed on render_path_needs_clips, before any init).
  - Queue launch stamps render_mode + static_stage_plan for static tenants (queue videos had NO plan).
  - Legacy clip bot writes each paid clip to generation_ledger.
- 9 calendar titles set to 20 min (`production_queue.video_length_minutes`).
- Test video 59fd34a4 "Most Hated Helicopters": roster (20 in-service types + 3 spares), 20/20 photos
  (no swap needed), research, script (20), voice, 59 pictures, thumbnail all DONE. Status restored to
  `ready_to_render`, title restored to the calendar title. Script readiness check: 0/20 stale.
- Customer money wasted this session: 59 Grok Imagine clips (~$5.31, 59 x $0.09) - not in the ledger
  (ran before the ledger fix). Ryan knows.

## Next action (start here cold)
Fix the title overwrite, then render. The thumbnail stage's title generator (relay stage `generate`,
thumbnail bot) wrote its YouTube title over `videos.video_title`. dvsu_script_v2.block_is_current compares
each block's `subject_context` to video_title, so all 20 paragraphs went stale and the resume bounced the
video to `ready_for_scripting` (would re-voice = paid). Find the writer
(`grep -rn "video_title" skills/video-pipeline/thumbnail storyengine/backend | grep -i update`), make it
write a separate field (or make script readiness key on `headline`), test, ask Ryan, deploy. Then relaunch:
reset queue item 3e6d4329 (status queued, attempt_count 0) and POST
`/api/queue/3e6d4329-8fa9-424f-9be6-df657cd6393a/launch` with `X-Active-Tenant: 561b872d-7b73-45e3-9c44-7f30c3566eda`
(token: `scripts/se.sh token`). Watch render + unlisted upload. Check upload doesn't re-title too.

## Open threads
- Queue item 3e6d4329 still says `running` with a failed task row; reconcile will flip it. Reset before relaunch.
- Script notes: scene 4 (H-43 Huskie, "well-liked") does not fit a "most hated" title - roster pick issue.
  Scene 5 (Huey) opens on the H-13. CH-46 answer used unsourced word "stopgap".
- Relay run cost: ~180 research slots, ~110 vision checks, ~70 motion prompts (now dead for static).
- Old: "Generate SEO" button calls Claude via Kie on relay tenants; vision-QA relay requests carry no video_id.

## Gotchas learned this session
- Queue-launched videos had pipeline_stages NULL -> ran every stage incl. clips. Normal create stamps the plan.
- Two Airtable names -> one column: IDEA_COLUMN_MAP keeps only the last name.
- A thumbnail-stage title rewrite invalidates every dvsu_script_v2 block (subject_context = video_title).
- asyncio.gather without cancel: when one clip upload raised, the other paid clips kept running.
- Relay helpers: loop helpers with a claim script (scratchpad claim.sh: lock + dispatched.txt) avoid double-answers.
- REST as the DvsU tenant: Ryan's token + header `X-Active-Tenant: 561b872d-...` (member check).
