"""2026-09-24: `$4 IS NULL ... OR job_id = $4` is ambiguous to Postgres ("could not
determine data type of parameter $4"). Every durable-task write in task_store failed
silently from 2026-09-17, so the worker refused every Run All job as unknown. The
DB is mocked in unit tests, so pin the SQL shape: a bare `$N IS NULL` must carry a cast."""
import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "task_store.py").read_text()


def test_every_null_checked_parameter_is_typed():
    untyped = re.findall(r"\$\d+ IS NULL", SRC)
    assert untyped == [], f"untyped NULL-checked params in task_store.py: {untyped}"
    assert re.search(r"\$\d+::text IS NULL", SRC)
