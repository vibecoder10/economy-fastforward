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
  `scratchpad/.dvsu_agent_token` (chmod 600, NOT in git). **REVOKE at loop end** (UPDATE
  agent_tokens SET revoked_at=now() WHERE id=…).
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
