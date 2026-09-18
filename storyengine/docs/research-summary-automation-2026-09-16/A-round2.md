# Package A round 2 receipt — parenthetical class variants

Scope: generic local matcher correction only. No provider request, deployment, production mutation, or saved-source mutation was made.

`_matches_class_subject` and the lead-name-plus-hull matcher now use an alphanumeric-token separator, so punctuation such as parentheses is treated the same as hyphens and spaces between locked identity tokens. The change retains every normalized token: `Barracuda (V-1) class` matches, while `Barracuda (V-2)` does not match even when it carries an in-range hull.

Offline verification:

`backend/venv/bin/python -m pytest backend/tests/test_research_class_identity.py backend/tests/functional/test_kie_factual_source_search.py -q`

Result: `18 passed`.

The direct regression probe returned true for both parenthesized and unparenthesized `Barracuda V-1` class phrases, and false for `USS Barracuda (V-2) (SS-163)`. `backend/venv/bin/python -m py_compile backend/factual_machine_research.py` and `git diff --check` passed. The test adds those same positive and negative assertions; no identity special case was added.
