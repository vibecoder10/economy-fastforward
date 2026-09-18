# Step C receipt — offline compiler integration coverage

Scope: `backend/tests/test_script_compiler_integration.py`, directly affected
functional pipeline expectations, and `replay_saved_research.py` only.

The tests use assessed synthetic source packages and queue-only fake clients.
They cover selected fact-ID materialization, exact locked citations, an
independent referee request, unknown-ID failure before a referee call,
writer/referee budget preflight with zero affected provider calls, and a
rejected section retaining its compiler receipt. Cache regressions cover a
legacy assessed saved block without a packet fingerprint, promotion and
repeat reuse of a matching passed preview, a current accepted saved block
remaining authoritative over a failed preview, a matching failed preview as
repair input over an older packet, and model-fingerprint invalidation.

`replay_saved_research.py SNAPSHOT RECEIPT` performs no network or provider
call. It compiles each usable saved card, records packet count/size and
determinism, validates the input hash did not change, tests a meaningful local
input mutation for fingerprint invalidation, and measures conservative writer
and saved-research-draft referee request bounds. The latter is size evidence
only: saved research prose is not treated as a mapped script draft or accepted
narration.

Run from `backend` with the canonical environment:

```sh
/Users/ryanayler/AgentVault/Projects/story-engine/storyengine/backend/venv/bin/python -m pytest tests/test_script_compiler_integration.py -q
/Users/ryanayler/AgentVault/Projects/story-engine/storyengine/backend/venv/bin/python ../docs/script-compiler-2026-09-16/replay_saved_research.py INPUT.json RECEIPT.json
```
