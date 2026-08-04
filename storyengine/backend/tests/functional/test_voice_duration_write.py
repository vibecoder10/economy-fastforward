"""Lock: SupabaseAdapter.mark_script_finished writes voice_duration_seconds
in the SAME UPDATE statement as voice_over_url.

Before this fix, the voice stage (skills/video-pipeline/voice/run.py)
downloaded the narration MP3 bytes, uploaded them to Google Drive, and
called mark_script_finished(id, url) — the method never accepted or wrote a
duration at all, so scripts.voice_duration_seconds stayed NULL forever even
though the real audio bytes were sitting in memory at generation time.
render_static.py and channel_identity_context.py both read this column
downstream (falling back to ffprobe, or silently excluding the video from a
duration total, when it's NULL).

This test captures the SQL + params mark_script_finished emits (same
capture pattern as test_adapter_tenant_isolation.py) and proves:
  1. voice_over_url and voice_duration_seconds land in ONE UPDATE call.
  2. The duration value passed through is the exact one the caller computed
     (rounded to 2 decimals — that rounding happens in voice/run.py's
     mp3_duration_seconds(), this test just proves the adapter doesn't
     mangle or drop it).
  3. A None duration (the caller couldn't parse the MP3) still writes
     voice_over_url — duration failure never blocks the URL write.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import supabase_adapter
from supabase_adapter import SupabaseAdapter


def _install_capture():
    """Replace the module-level DB helpers with recorders. Returns the call log."""
    calls = []

    def cap_execute(sql, params=None):
        calls.append((sql, params))
        return "UPDATE 1"

    supabase_adapter._execute = cap_execute
    return calls


def test_url_and_duration_written_in_same_update():
    adapter = SupabaseAdapter(tenant_id=None)
    calls = _install_capture()

    adapter.mark_script_finished(
        "script-1",
        "https://drive.google.com/uc?id=abc&export=download",
        voice_duration_seconds=12.34,
    )

    assert len(calls) == 1, (
        f"expected exactly ONE database update for the voice_over_url + "
        f"voice_duration_seconds write, got {len(calls)}: {calls}"
    )
    sql, params = calls[0]
    assert "voice_over_url" in sql and "voice_duration_seconds" in sql, (
        f"both columns must be set in the SAME UPDATE statement:\n{sql}"
    )
    assert "UPDATE scripts SET" in sql
    params = tuple(params)
    assert "https://drive.google.com/uc?id=abc&export=download" in params
    assert 12.34 in params, f"the exact duration value must reach the query params: {params}"
    assert "script-1" in params
    print("test_url_and_duration_written_in_same_update OK")


def test_duration_none_still_writes_url():
    """Duration computation failing (mutagen couldn't parse the MP3) must
    never block the voice_over_url write — this is the existing resumability
    contract (docs/failure-modes.md's per-scene 'already done' check), and
    this fix must not weaken it."""
    adapter = SupabaseAdapter(tenant_id=None)
    calls = _install_capture()

    adapter.mark_script_finished(
        "script-2",
        "https://drive.google.com/uc?id=def&export=download",
        voice_duration_seconds=None,
    )

    assert len(calls) == 1
    sql, params = calls[0]
    assert "voice_over_url" in sql and "voice_duration_seconds" in sql
    params = tuple(params)
    assert "https://drive.google.com/uc?id=def&export=download" in params
    assert None in params, "voice_duration_seconds should be written as NULL, not omitted"
    print("test_duration_none_still_writes_url OK")


def test_no_url_no_write_unchanged():
    """Legacy no-op path (called with no URL at all) is untouched by this
    fix — still just flips script_status, no voice columns touched."""
    adapter = SupabaseAdapter(tenant_id=None)
    calls = _install_capture()

    adapter.mark_script_finished("script-3")

    assert len(calls) == 1
    sql, params = calls[0]
    assert "voice_over_url" not in sql
    assert "voice_duration_seconds" not in sql
    assert tuple(params) == ("script-3",)
    print("test_no_url_no_write_unchanged OK")


TESTS = [
    test_url_and_duration_written_in_same_update,
    test_duration_none_still_writes_url,
    test_no_url_no_write_unchanged,
]


def main() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"FAIL {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
