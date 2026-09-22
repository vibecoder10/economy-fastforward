# HANDOFF - 2026-09-22 - dvsu_script_v2 driven live over the relay: 14/20 passed, 6 false-positive needs-review; three fixes deployed; rerun pending

## State
- Prod: `23b1dbe28` deployed 2026-09-22T05:34Z, healthy, idle (`active_work` 0, drain normal, no lock). Frontend deployed at 76717d466 (no frontend change since).
- Branch `main` = origin/main at `23b1dbe2`. Not mine, left alone: `../tasks/decisions.md` (Ryan's uncommitted Jev entry + two entries), untracked `jev-key-box.html`.
- Backend v2 suite: `tests/test_dvsu_script_v2.py` 42 passed (3 new tests). Full suite not rerun this session.
- Video `6ac28204-681c-4839-9d11-6c3ba57b7b6e` (Every US Submarine Class Ever Built, tenant Designed Vs Used `561b872d`): status still `ready_for_scripting`. Script tab (local UI, workspace switcher -> Designed vs Used) shows 14/20 "Script preview passed", 6 "Needs review": A-class, S-class, Barracuda, Porpoise, Gato, Barbel. All six failed ONLY the boat-terminology regex on "Electric Boat" / "U-boats" / "Diesel Boats Forever" - the paragraphs themselves are fine. Banner reads "Run All stopped at Script - Something went wrong" (misleading copy for a needs_review outcome; open thread).
- What shipped this session (all on prod):
  1. `6bed9432` + `23b1dbe2` `dvsu_script_v2.boat_terminology_slip()`: proper nouns (capitalised word + Boat(s), U-boat) stripped before the boat check.
  2. `35c541c2` `pipeline_executor.run_script` now calls `_install_cancel_support(video_id)` like every other stage entry - fixes BOTH the ignored cancel and relay requests parked with `video_id=None` (so `list_pending_llm_requests(video_id=...)` returned nothing; use no filter until a run on 23b1dbe2 proves it).
- How the run was driven (Ryan's rule: no Anthropic key, Sonnet where the API call would run): MCP `script` (quote ~$0.02 nominal, confirm) -> loop `list_pending_llm_requests(status=pending)` -> Sonnet subagent gets SYSTEM+USER prompt verbatim, returns raw JSON -> `answer_llm_request`. 20 write calls + 6 repairs. Repairs for the known false positive were answered with the unchanged draft (Sonnet's own answer to the first one). Each Sonnet call ~60-100 s.

## Next action (start here cold)
1. Rerun: MCP `script` on 6ac28204 (quote, then confirm). Bulk runs reuse the 14 passed blocks (brief-fingerprint "current"), rewrite the 6 needs-review machines. Their prompts now include the finished A-class paragraph so the relay cache will NOT replay - expect 6 fresh requests; answer each via a Sonnet subagent (prompt verbatim, raw JSON). With the fixed audit they pass; expect status -> `ready_for_voice` and a Drive export `02-script.md`.
2. Read all 20 paragraphs against `docs/gold-scripts/standards/DvsU_Script_Writing_System.md` with your eyes (MCP `get_script` or the Script tab). Two slips I noticed on the way: A-class says "gasoline fumes killed" where the source says explosion and fire; Holland says "made his victory untenable" vs source "fleet in an untenable position". Name-opener tally reads 1/5 though no paragraph opened with a name - check which one `opens_with_name` counted.
3. Then walk the Script tab on prod (`/se-smoke`), screenshot, and hand Ryan the script for review before voice (paid).

## Open threads
- "Run All stopped at Script - Something went wrong" banner for a needs_review outcome: wrong copy; the roster cards already say the truth.
- `[INIT] AgentRelayClient OK` logged every ~10 s during the run: something re-initialises the lightweight pipeline per request (roster-dashboard polling?). Perf smell, not a bug.
- Deploy-drain deadlock: a relay-parked run holds a generation claim and never finishes on its own; deploy waits up to 2 h. Cancel now works (fix 2), so the recipe is cancel -> wait for claim 0 -> deploy.
- Carried from last session: delete `_machine_story_plan` + `_script_starvation_*` + `repair_promote_excerpt` together; drop `dvsu_script_operations` table; `docs/gold-scripts/grammar/` judgment calls unreviewed; roster-size formula needs Ryan; VPS git remote PAT rotation (Ryan only).

## Gotchas learned this session
- Ryan's default dev token binds to "ryanayler's Workspace"; the DvsU video 404s until you pick "Designed vs Used" in the sidebar workspace switcher (X-Active-Tenant).
- `se deploy` drains and WAITS for active work; a run blocked on the relay counts as active work. Don't start a deploy under a relay run unless you can end the run.
- An audit regex false positive costs a paid repair call AND a needs_review per machine; watch the first repair request of any live run and read the violation text before answering.
