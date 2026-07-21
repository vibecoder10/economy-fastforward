# Loop checklist — bulletproof reference lookup for static_docu (no invented machines)

## Definition of Complete
1. Root cause named with code evidence (DONE — see tasks/ref-lookup-root-cause below).
2. Reference lookup finds a correct, servable reference for all 23 machines in the
   DvsU bomber roster, including XB-35, YB-49, YB-35, YB-60.
3. Fail-closed law: if no verified reference exists after all sources, the scene
   BLOCKS with a persisted status. Text-to-image generation of a machine with no
   reference is impossible (code path removed, not just discouraged).
4. Proof: dry-run of the new lookup across the full 23-machine roster, output saved.
5. Deploy held for Ryan's explicit yes (`se deploy`). Push to main is safe (no restart).

## Assumptions (stated per maestro escape hatch)
- Ryan's ask "pitch me solutions ... implement it" pre-authorizes implementing the
  recommended Option A without waiting for a reply. Options B (manual cache seeding)
  stays as the escape hatch; C (external image search) parked unless dry-run shows gaps.
- Work lands on local `main` (deploy repo pulls main; push ≠ deploy). No `se deploy`
  without Ryan.
- Small Anthropic vision-verify spend during the dry-run (pennies, tenant key, within
  the standing DvsU cap) is acceptable; all image GENERATION spend is out of scope here.

## Root cause (evidence)
- `_api_issued_thumb` (backend/static_docu.py:184) tries widths 1600 and original-1;
  MediaWiki echoes the raw URL (no /thumb/) for originals ~1300–2000px, function
  returns None, candidate silently dropped. Reproduced live for XB-35.jpg (1543px),
  YB49-2_300.jpg (1468px), The_Convair_YB-60.jpg (1800px); width 1000 → real /thumb/ works.
- Commons-search candidates hard-coded trusted=False (static_docu.py:665,668); untrusted
  acceptance requires the vision model to NAME the designation unprompted → correct
  photos rejected for obscure prototypes.
- No-ref branch (static_docu.py:734-740) generates text-to-image anyway and ships
  status='done' with only a transient log warning. This is the invented-machine line.

## Chunks
- [ ] C1 [B][V] Fix static_docu.py at all three seams:
      (a) `_api_issued_thumb` descending width ladder (1600/1280/1024/800/640, first
          genuine /thumb/ wins);
      (b) new trusted Layer 1.5: all photos on the machine's own Wikipedia article;
      (c) Commons trust upgrade: designation-token match in file title/categories →
          trusted; untrusted vision check becomes name-supplied consistency check
          (YES/NO), not blind naming;
      (d) FAIL CLOSED: no verified ref → no generation call, asset persisted as
          status='blocked_no_reference' with a clear operator message pointing at
          static_reference_cache seeding; delete the _STUDIO_PROMPT_NOREF generation
          path; clear stray drive_image_url when all candidates are rejected.
      [V] = stash-proof tests (stubbed HTTP) + local live lookup script proving
      XB-35/YB-49/YB-35/YB-60 now return servable /thumb/ URLs (no keys needed) +
      full backend suite vs known baseline (16 failed + 1 error are pre-existing).
- [ ] C2 [V] Full-roster dry-run: script (scp'd to VPS, run there — vision verify needs
      the tenant key) that runs the NEW lookup for all 23 roster machines of video
      fc73860c and prints found/verified/source per machine. Save output. Any machine
      still unfound → seed static_reference_cache manually (Option B escape hatch) and
      record it.
- [ ] C3 [decision] Ryan: approve `se deploy` (backend restart; honor deploy.lock, never
      during generations). Then re-render wrong scenes via `images(video_id, scene=N)`
      (~$0.03 each — quote first) — that re-render belongs to the separate video-finish
      task, not this loop.

## Lessons for worker briefs
- BSD tools on this Mac; python3; Read before Edit; no inline multi-line python over ssh.
- Backend tests: `cd backend && ./venv/bin/python -m pytest tests/ -q` (Python 3.11 venv).
