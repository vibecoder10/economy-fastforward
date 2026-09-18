# Terra round 1 receipt

- Applied the planned parser-only change in `backend/factual_machine_research.py`: a named submarine target now accepts whitespace, hyphen, en dash, or em dash between the hull number and `USS`.
- Extended `backend/tests/test_named_submarine_research_identity.py` with separator coverage for all 20 accepted submarines, canonical Holland roster/slot resolution, strict rejection cases, and async `run_machine_script_preview` entrypoint coverage using `SimpleNamespace` and `AsyncMock`.
- The async success case asserts the hold receives the canonical `SS-1 USS Holland` target and does not receive `save_target_script=True`; the wrong-name case asserts the hold is never called.
- Offline verification: `./venv/bin/python -m pytest tests/test_named_submarine_research_identity.py -q` from `backend/` — 10 passed in 0.14s.
- No provider, network, database, deploy, commit, or push action was performed.
