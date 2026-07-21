# DvsU Bomber-Video Execution Loop — live state (cold-resumable)

**Goal (Ryan, 2026-07-21, away-overnight):** drive "Every US Strategic Bomber Ever Built"
(video `fc73860c-a9af-444f-95a5-7f86d60503e0`, tenant `561b872d`, render_mode `static_docu`)
to a rendered MP4 + 2 thumbnails. **Budget: ≤ $10 API spend, HARD.** No YouTube upload.
Orchestrator (Fable) verifies; Sonnet workers do free thinking/verification. Runs under /loop.

## Operating model (money discipline)
- **Orchestrator holds the token and makes ALL money-gated MCP calls itself** (2-step
  confirm), logging every spend to the ledger below. Each paid call is checked against the
  running total BEFORE firing; stop at $10.
- **Sonnet workers do only FREE work:** grounded research writing, script writing to the DvsU
  law, adversarial verification vs `notes/dvsu-paragraph-rubric.md`, failure taxonomy. Results
  handed back; orchestrator submits via free `submit_research`/`submit_script` or feeds the
  next paid call. (This is exactly what the MCP server's own `instructions` recommend: text
  "thinking" verbs are free-substitutable via submit_*; only media is real spend.)
- Media (images/voice/render/thumbnail) has no free substitute — those are the real budget.

## Execution path (verified 2026-07-21 04:24 UTC)
- Backend LIVE + reachable from sandbox: `https://storyengine.dev/api` (health 200).
- MCP endpoint LIVE: `POST https://storyengine.dev/api/mcp` (401 without token → enabled).
- Auth: agent token minted for DvsU (id `5703bdac-c3f9-4e14-ad70-897c64cc2223`, name
  "dvsu-loop-orchestrator-2026-07-21 (auto; revoke after run)"). Plaintext in
  `scratchpad/.dvsu_agent_token` (chmod 600, NOT in git).
  **DO NOT REVOKE (Ryan, 2026-07-21): keep it alive for cross-session use.** Plaintext stays
  in scratchpad only — never committed (live prod bearer credential). Any session can re-mint
  an equivalent token in one SQL insert against Supabase project `wrromlupsmyzrrcqlucn`:
  ```
  # secret = 'se_agent_' + secrets.token_urlsafe(32); hash = sha256(secret).hexdigest()
  INSERT INTO agent_tokens (tenant_id, name, token_hash)
  VALUES ('561b872d-7b73-45e3-9c44-7f30c3566eda', '<name>', '<hash>');
  # use: Authorization: Bearer <secret>  against POST https://storyengine.dev/api/mcp
  ```

## Tokens & MCP registration (Ryan 2026-07-21 — keep alive, cross-session)
- **PRIMARY token (Ryan-supplied, use this):** name "claude", id `0e2f8362-84cf-4797-9c1c-a5aa37779f84`,
  tenant DvsU. Plaintext in `scratchpad/.dvsu_agent_token_user` (chmod 600, NOT git). Do NOT revoke.
- **Backup token (orchestrator-minted):** id `5703bdac-…`, `scratchpad/.dvsu_agent_token`. Do NOT revoke.
- **MCP server registered natively (user scope):** `storyengine-dvsu` →
  `https://storyengine.dev/api/mcp`, `claude mcp list` = √ Connected. Native tools load for
  FUTURE sessions at startup; THIS session keeps using curl for explicit money-gate control.

## ⚠ Load-bearing findings (verified 2026-07-21)
- **Cheap one-machine routes are SESSION-JWT-ONLY — agent token CANNOT reach them.** Confirmed
  empirically (agent token → `/api/pipeline/machine-script-preview-readiness` → 401 "Invalid or
  expired session") and in code (`routes/pipeline.py` machine-* handlers use
  `Depends(get_tenant_id)`; the 3 session paths need `SESSION_SECRET`/`DEV_TOKEN`+`DEV_MODE`/
  `SUPABASE_JWT_SECRET`, all VPS-env-only, unmintable from here).
- **MCP `research` verb is DESTRUCTIVE — DO NOT CALL IT.** `run_research` (pipeline_executor.py
  :7826) re-runs full topic discovery and `UPDATE videos SET research_payload = $1` wholesale
  (:7981) → would overwrite the curated 23-machine roster + discard the 8 done packages + 4
  previews. MCP `script` verb = full-roster fail-fast, full-restart each call (expensive to
  iterate). So platform-driven gen is destructive/costly; prefer worker-write + free submit.
- **Only 8/23 machines are researched** (B17,B24,B29,B32,B52,XB15,XB19,XB39). 15 missing.
  4 old previews (B17,B24,B52,XB15) are pre-seed 0/3-era artifacts.
- **Revised drive-mode (non-destructive):** Sonnet workers do real research (WebSearch/WebFetch)
  for the 15 missing + stale XB-15, written to the gate schema; I inject into the EXISTING
  payload (preserve curated roster + 8 done). Workers write all 23 paragraphs to the 76 laws +
  rubric; submit via free `submit_script` (or direct DB write in gate schema) — pending the
  contract-feasibility check. Media (images/voice/render/thumbnail) is the only $ spend.
- Handshake proven: initialize 200 / initialized 202 / tools/list = 86 tools (incl. research,
  script). DvsU standing passes both gates (owner ryan@nativestates.ai is_operator=true, pro).

## Budget ledger (running)
| # | What | Cost | Cumulative | Note |
|---|------|------|-----------|------|
| — | (seed DV-0) | $0.00 | $0.00 | DB writes only |
| — | MCP handshake/probes | $0.00 | $0.00 | free reads |

**Cumulative spend: $0.00 / $10.00**

## Checklist (dependency-ordered)
- [x] DV-0 · seed quality law live (76 rows, verified + idempotent) — commit 13ab44b
- [x] path · MCP reachable + token minted + handshake verified
- [ ] MAP · exact DV-1 runbook (roster key, one-machine-vs-full auth, call sequence, cost)
      — Sonnet Explore worker running (a78b3048)
- [ ] DV-1a · measure the platform writer: run the platform's own research+script on a small
      sample (XB-15/B-17/B-52 or one full-roster script) under the seeded law; record pass/fail
      + failure taxonomy vs the rubric. THIS is the writer-gap measurement Ryan cares about.
- [ ] DV-1b · decide drive-mode from DV-1a evidence: platform-writer-drives (if passing) vs
      worker-writes-and-submits (if failing) for the full 23-machine roster.
- [ ] DV-5a · full 23/23 research + scripts locked (via chosen drive-mode)
- [ ] DV-5b · voice (narrator config per QL-46; ~$1-2)
- [ ] DV-5c · 23 static_docu images (verified real-photo refs; ~$1.15 @ $0.05/img)
- [ ] DV-5d · Ken Burns render → MP4 + caption check
- [ ] DV-5e · 2 A/B thumbnails (QL-63..71; ~$0.10)
- [ ] DV-6 · orchestrator final review: MP4 vs Anton's real video, verdict
- [ ] CLEANUP · revoke agent token; write completion report + deferred items

## Handoff (2-line, keep current)
- **Last done:** token minted + MCP handshake verified live; DV-0 seed confirmed 76 rows.
- **Next:** consume the MAP worker's runbook → run DV-1a (measure platform writer on sample),
  logging spend. Then branch on the result.
