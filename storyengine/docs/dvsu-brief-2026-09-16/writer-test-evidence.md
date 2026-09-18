# Writer focused test evidence

2026-09-16 local offline verification:

```text
backend/venv/bin/python -m pytest -q backend/tests/test_dvsu_script_writer.py backend/tests/test_factual_machine_summary.py
39 passed in 0.06s
```

The focused writer contracts cover no provider call for a missing compact brief,
the 80-word floor before referee invocation, factual-plus-editorial acceptance,
editorial rejection without sentence pruning, and missing editorial audit failure.
