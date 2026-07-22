# Chat Channel-Identity Rebuild — Phase 1 (2026-07-22)

Ryan's architecture (his words): channel identity is a POOL; the pipeline is the
main river; the flow reaches every channel — MCP, chat, any part of the UI.
One consciousness, different tools down the river.

Diagnosis source: two mapper reports 2026-07-22 (producer chat context assembly
+ model-video trace). Root causes: (1) reference-anchoring prompt instructions
with no channel-precedence rule, (2) _stamp_length_default forces competitor
median, (3) sticky pending_reference_url/video_dna never cleared, (4) channel
identity (channel_profiles.channel_identity, cast, System Prompts, script
profiles) never injected into chat; chat has no tool access.

## Definition of Complete
1. ONE shared identity-context builder (the pool) in the backend, used by the
   producer chat (injected FIRST), the in-video copilot, and exposed through
   the MCP/actions registry. No surface hand-rolls its own identity view.
2. Chat prompts carry the Discovery precedence law: our locked format leads;
   a reference's TOPIC survives, its format/runtime does not.
3. Recommended/default length comes from OUR channel (own-catalog median or
   channel target), competitor median only when we have no catalog.
4. Steering works: a reference can be cleared (explicit op + honored steer),
   and identity-level corrections persist durably.
5. Unit tests on pool content/fallbacks, prompt ordering/precedence, length
   backstop, clear-reference; zero new failures in backend suite.
6. Deployed + live-verified in the PocoAPoco workspace: re-run the same
   model-this-video conversation; chat must propose a PocoAPoco-shaped video
   (couple dialogue, A1-A2 titling, our runtime), not the reference verbatim.

## Chunks
- [x] P1 @ 10f4af85 (pool + get_channel_identity_context MCP verb, 34 tests) —
- [x] P2 @ cb53803d (identity brief FIRST at 3 sites incl. _seed_producer; 3 anchor instructions subordinated; source-lock tests) —
- FOLLOW-UP noted for Phase 2: channel identity should carry a declared
  "performance format vs narrated format" flag (Ryan 2026-07-22); every
  surface reads it instead of inferring from script shape.
- [ ] P1-orig (spec, done): backend/channel_identity_context.py (or extend
  channel_briefs.py) — canonical builder: channel_identity DNA, saved cast
  (projects.character_references/cast_locked), format lock, OWN catalog median
  length (channel_videos), confirmed channel_patterns, script profiles list,
  System Prompts script-slot summary. Graceful when any piece missing.
  Expose read verb through routes/mcp.py registry (extend get_channel_dna or
  add get_channel_identity_context). Unit tests incl. empty-tenant fallback.
- [ ] P2 [B][V] Chat wiring: inject pool brief FIRST at chat.py:4637-4652 and
  into _handle_copilot's assembly; precedence sentence (Discovery's
  discovery.py:852-858 wording adapted) in producer_prompt.py MODELING
  section + _reference_brief rewritten subordinate ("adapt the IDEA into OUR
  locked format; runtime from OUR channel"). Tests: assembly order, presence.
- [ ] P3 [B][V] Length + steering: _stamp_length_default uses own-catalog
  median (fallback competitor only if no catalog); add clear_reference
  profile_op (clears pending_reference_url + video_dna) + producer prompt
  teaches it; identity corrections persist (creator_brief write path callable
  outside onboarding). Tests for all three.
- [x] P3 @ 22031554; P4 sweep -> 1 BLOCKER + 3 fixes -> P5 @ e1740bad
  (bidirectional auto-skip w/ skip_voice_source provenance, migration 116;
  deterministic length-phrase guard; cast cap; lean chat pool). U3 @ e8680b04.
  DEPLOYED 2026-07-22 21:38 UTC (osiris-identity-voiceless, 5f3e87aa->e1740bad,
  migration 116 auto-applied). LIVE PROOF passed: prod producer chat, modeling
  ask -> channel-convention title, length "our anchor is our own channel
  norms, not that runtime", honest no-history fallback. PocoAPoco visual
  check of collapsed tab = Ryan refresh (tenant unreachable by devtoken).
- [x] P4 SWEEP (read-only) — original spec: adversarial review P1-P3 (prompt-size bloat,
  copilot regression, onboarding flows, cross-tenant leakage, cache staleness).
- [ ] P5 [V] Live proof (after deploy, Ryan-gated): replay the PocoAPoco
  model-this-video conversation; verify channel-shaped proposal + steer works.
