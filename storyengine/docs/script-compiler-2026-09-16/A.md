# Step A receipt — packet compiler

Implemented `backend/script_research_packet.py` with deterministic supported-fact selection, immutable evidence reconstruction, conservative request budgeting, and packet/cache fingerprints. The compiler rejects invalid assessment identity, unverified quotes, oversized metadata or whole facts, and unknown model fact IDs without mutating supplied inputs.

Round 2 repair reserves the final fingerprint during size admission, emits receipts for selection-limit and byte-limit omissions, backfills after oversized facts, and rejects unhashable malformed fact-ID values. Round 3 preserves one representative per category before fillers, deduplicates fact IDs by lexical assessment ID, and sorts the selected output deterministically.

Focused offline verification:

```text
/Users/ryanayler/AgentVault/Projects/story-engine/storyengine/backend/venv/bin/python -m pytest tests/test_script_research_packet.py -q
9 passed
```

No network, provider, repository, database, or production writes were made.
