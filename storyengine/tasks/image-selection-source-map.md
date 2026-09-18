# Image selection source map (read-only, commit `57d6a829`)

## Current automatic chain

- `_prefetch_one_machine` gathers candidates, then calls `_rank_reference_views(candidates, tenant_id, machine)` before hosting candidates one at a time. [static_docu.py:4690-4691](../backend/static_docu.py#L4690-L4691)
- The ranker first moves known poor URL-name patterns to the end, then considers at most the first six candidates. [static_docu.py:972-974](../backend/static_docu.py#L972-L974) [static_docu.py:990-995](../backend/static_docu.py#L990-L995)
- Ranking downloads each candidate and sends base64 image pixels, plus numbered candidate labels and ranking instructions, to Anthropic Messages using `CLAUDE_MODELS["anthropic"]["smart"]`; it is not a URL-only rank. [static_docu.py:980-1005](../backend/static_docu.py#L980-L1005)
- A missing key, fewer than two downloadable images, invalid rank response, or ranker exception retains candidate order. [static_docu.py:976-979](../backend/static_docu.py#L976-L979) [static_docu.py:999-1016](../backend/static_docu.py#L999-L1016)
- After ranking, each candidate is self-hosted, then passed to `_vision_confirms` with the candidate filename as `source_label`; a passing candidate is stored as `reference_kind='photo'` with hosted and source URLs. [static_docu.py:4724-4742](../backend/static_docu.py#L4724-L4742)

## Vision decision and persisted reason

- `_vision_confirms` receives hosted-image URL, machine, aliases, trusted-source flag, roster facts, and source label. [static_docu.py:1818-1822](../backend/static_docu.py#L1818-L1822)
- It downloads the image and supplies base64 pixels to the vision request. [static_docu.py:1969-1985](../backend/static_docu.py#L1969-L1985)
- Direct Anthropic Messages is attempted first; the fallback branch obtains a Kie API key when no Anthropic key is configured. [static_docu.py:1987-2003](../backend/static_docu.py#L1987-L2003)
- The raw YES/NO reason text is not written to `static_reference_misses`. On failure, `_prefetch_one_machine` persists only the classified code: `no_candidates`, `vision_rejected` if any candidate hosted, otherwise `fetch_failed`. [static_docu.py:4743-4747](../backend/static_docu.py#L4743-L4747)
- The miss schema stores machine, machine key, reason code, reason detail, and check timestamp; `_record_reference_miss` supplies a configured label when no detail is passed. [static_docu.py:1212-1231](../backend/static_docu.py#L1212-L1231)

## Manual pasted URL

- `seed_reference_from_url` self-hosts the pasted URL first. If hosting fails it returns a rejected response; it does not convert a search page into a separate candidate selection flow. [static_docu.py:4750-4775](../backend/static_docu.py#L4750-L4775)
- It loads matching roster aliases/facts when available, then uses the full untrusted (`trusted_source=False`) vision gate with the pasted URL's final path segment as source label. [static_docu.py:4781-4801](../backend/static_docu.py#L4781-L4801)
- On pass it stores the hosted image and original pasted URL as the photo/source pair, clears that machine's miss, and returns verified. [static_docu.py:4802-4809](../backend/static_docu.py#L4802-L4809)

## Local run evidence

- The existing Barracuda record is `vision_rejected`; its stored reason says a candidate was found and hosted but did not match the vision check. [image-gather-barracuda-miss.log:1-2](image-gather-barracuda-miss.log#L1-L2)
- The local worker evidence records the roster-images job and ranker fallback messages only; it does not include a per-candidate URL or raw vision reply. [image-gather-barracuda-miss.log:4-6](image-gather-barracuda-miss.log#L4-L6)
