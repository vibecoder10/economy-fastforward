"""Tests for D9-2 (migration 151 — Custom Film CharacterLock harvest).

video_characters gains three nullable columns (face_body_lock, wardrobe_lock,
forbidden_drift), mirroring Custom Film's CharacterLock (backend/
custom_film_director.py:147-161). This file covers:

  1. _parse_character_lock_reply (routes/characters.py): best-effort parse of
     the extended vision reply into {DESCRIPTION, FACE_BODY_LOCK,
     WARDROBE_LOCK, FORBIDDEN_DRIFT} — partial/legacy/malformed replies never
     raise.
  2. approve_cast's background task: a stubbed vision reply populates the
     three lock columns via ONE UPDATE (never a second paid vision call); a
     reply that ignores the labeled format falls back to today's
     whole-reply-as-description behavior and writes NO lock columns; a
     vision failure is fail-soft exactly like before (approval still
     completes, description/locks left untouched).
  3. scripts/coverage_to_app.py's consume side: load_character_bible's
     costume precedence (identity_tag > locks > description > "", byte-
     identical to before this migration when locks are NULL) and the shared
     _identity_tag_or_locks/_locks_text helpers redraw_asset_image also uses.
  4. Locks appear VERBATIM in the composed board-sheet CHARACTER line
     (_character_identity_line) once they flow through the bible.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_d9_2_character_locks.py -q
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

import routes.characters as ch_route  # noqa: E402
import scripts.coverage_to_app as coverage_to_app  # noqa: E402

TENANT = "tenant-1"
VIDEO_ID = "video-1"


# ---------------------------------------------------------------------------
# fixtures / fakes
# ---------------------------------------------------------------------------

class _FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *a, **kw):
        self.tasks.append((fn, a, kw))


def _video_row(**over):
    base = {
        "id": VIDEO_ID, "video_title": "Test Video", "script": "",
        "image_style_override": None, "original_dna": None, "story_bible": None,
        "characters_approved_at": None, "project_id": None, "total_cost": 0, "max_spend": None,
    }
    base.update(over)
    return base


def _character_row(**over):
    base = {
        "id": "char-1", "tenant_id": TENANT, "video_id": VIDEO_ID, "name": "Nyla",
        "description": "A woman in a blue coat.", "identity_tag": None,
        "reference_url": "https://example.com/nyla.png", "status": "draft",
        "source": "generated", "sort": 0, "face_body_lock": None, "wardrobe_lock": None,
        "forbidden_drift": None,
    }
    base.update(over)
    return base


LABELED_REPLY = (
    "DESCRIPTION: Nyla has a short black undercut, mid-20s, wearing a red leather jacket "
    "over a white tee and dark jeans.\n"
    "FACE_BODY_LOCK: Short black undercut, tan skin, athletic build, a small scar above the "
    "left eyebrow.\n"
    "WARDROBE_LOCK: Red leather jacket over a white crew-neck tee, dark indigo jeans, "
    "black boots.\n"
    "FORBIDDEN_DRIFT: hair changes color; jacket loses its collar; scar disappears"
)

UNLABELED_REPLY = (
    "Nyla has a short black undercut, mid-20s, wearing a red leather jacket over a white "
    "tee and dark jeans. She looks confident and focused."
)


# ---------------------------------------------------------------------------
# 1. _parse_character_lock_reply
# ---------------------------------------------------------------------------

class TestParseCharacterLockReply:
    def test_full_labeled_reply_parses_all_four(self):
        parsed = ch_route._parse_character_lock_reply(LABELED_REPLY)
        assert parsed["DESCRIPTION"].startswith("Nyla has a short black undercut")
        assert parsed["FACE_BODY_LOCK"] == (
            "Short black undercut, tan skin, athletic build, a small scar above the "
            "left eyebrow."
        )
        assert parsed["WARDROBE_LOCK"] == (
            "Red leather jacket over a white crew-neck tee, dark indigo jeans, black boots."
        )
        assert parsed["FORBIDDEN_DRIFT"] == (
            "hair changes color; jacket loses its collar; scar disappears"
        )

    def test_missing_label_is_simply_absent_not_an_error(self):
        reply = (
            "DESCRIPTION: Nyla, short black undercut, red jacket.\n"
            "FACE_BODY_LOCK: Short black undercut, tan skin.\n"
        )
        parsed = ch_route._parse_character_lock_reply(reply)
        assert "DESCRIPTION" in parsed
        assert "FACE_BODY_LOCK" in parsed
        assert "WARDROBE_LOCK" not in parsed
        assert "FORBIDDEN_DRIFT" not in parsed

    def test_unlabeled_legacy_style_reply_parses_to_empty_dict(self):
        """A reply that ignores the new format entirely (the pre-D9-2 shape)
        must parse to {} — never raise, never guess a label."""
        assert ch_route._parse_character_lock_reply(UNLABELED_REPLY) == {}

    def test_empty_and_none_input_are_safe(self):
        assert ch_route._parse_character_lock_reply("") == {}
        assert ch_route._parse_character_lock_reply(None) == {}

    def test_multiline_value_captured_whole_up_to_next_label(self):
        reply = (
            "DESCRIPTION: short line.\n"
            "WARDROBE_LOCK: A red jacket,\nover a white tee,\nand dark jeans.\n"
            "FORBIDDEN_DRIFT: color drift"
        )
        parsed = ch_route._parse_character_lock_reply(reply)
        assert parsed["WARDROBE_LOCK"] == "A red jacket,\nover a white tee,\nand dark jeans."
        assert parsed["FORBIDDEN_DRIFT"] == "color drift"

    def test_case_insensitive_labels(self):
        reply = "description: hi there\nface_body_lock: some facts"
        parsed = ch_route._parse_character_lock_reply(reply)
        assert parsed["DESCRIPTION"] == "hi there"
        assert parsed["FACE_BODY_LOCK"] == "some facts"


# ---------------------------------------------------------------------------
# 2. approve_cast background task — population + fail-soft
# ---------------------------------------------------------------------------

def _patch_approve_scaffolding(monkeypatch, char_rows, *, resolve_creds_returns):
    import routes.pipeline as pipeline_mod
    import routes.model_video as model_video_mod

    execute_calls = []

    async def fake_get_video(video_id, tenant_id):
        return _video_row()

    async def fake_fetch_all(query, *args):
        if "video_characters" in query:
            return char_rows
        if "scripts" in query:
            return []  # no script rows — story_laws sees an empty script
        return []

    async def fake_execute(query, *args):
        execute_calls.append((query, args))
        return "OK"

    async def fake_is_task_active(*a, **kw):
        return False

    def fake_set_task_status(*a, **kw):
        pass

    def fake_clear_task_status(*a, **kw):
        pass

    def fake_lane_begin(*a, **kw):
        pass

    def fake_lane_finish(*a, **kw):
        pass

    async def fake_build_cast_sheet(*a, **kw):
        return "https://example.com/sheet.png"

    async def fake_sync_bible(*a, **kw):
        return None

    async def fake_resolve_claude_creds(tenant_id):
        return resolve_creds_returns

    monkeypatch.setattr(ch_route, "_get_video", fake_get_video)
    monkeypatch.setattr(ch_route, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(ch_route, "execute", fake_execute)
    monkeypatch.setattr(ch_route, "_build_cast_sheet", fake_build_cast_sheet)
    monkeypatch.setattr(ch_route, "_sync_bible_to_cast", fake_sync_bible)
    monkeypatch.setattr(pipeline_mod, "_is_task_active", fake_is_task_active)
    monkeypatch.setattr(pipeline_mod, "_set_task_status", fake_set_task_status)
    monkeypatch.setattr(pipeline_mod, "_clear_task_status", fake_clear_task_status)
    monkeypatch.setattr(pipeline_mod, "_lane_begin", fake_lane_begin)
    monkeypatch.setattr(pipeline_mod, "_lane_finish", fake_lane_finish)
    monkeypatch.setattr(model_video_mod, "_resolve_claude_creds", fake_resolve_claude_creds)

    async def fast_sleep(*a, **kw):
        return None

    monkeypatch.setattr(ch_route.asyncio, "sleep", fast_sleep)

    return execute_calls


def _run_approve_background_task(monkeypatch, char_rows, *, vision_impl, resolve_creds_returns):
    execute_calls = _patch_approve_scaffolding(
        monkeypatch, char_rows, resolve_creds_returns=resolve_creds_returns)

    import shared.clients.vision_client as vision_client_mod
    monkeypatch.setattr(vision_client_mod, "vision_call", vision_impl)

    bg = _FakeBackgroundTasks()
    result = asyncio.run(ch_route.approve_cast(VIDEO_ID, bg, tenant_id=TENANT))
    assert result["status"] == "running"
    assert len(bg.tasks) == 1
    fn, args, kwargs = bg.tasks[0]
    asyncio.run(fn(*args, **kwargs))  # run the background body inline
    return execute_calls


class TestApproveCastLockPopulation:
    def test_happy_path_writes_all_three_locks_plus_description_in_one_update(self, monkeypatch):
        char = _character_row()

        calls = {"n": 0}

        async def fake_vision_call(prompt, images, **kw):
            calls["n"] += 1
            return LABELED_REPLY

        execute_calls = _run_approve_background_task(
            monkeypatch, [char], vision_impl=fake_vision_call,
            resolve_creds_returns={"provider": "anthropic", "key": "fake-key"},
        )

        # ONE paid vision call per character — never two.
        assert calls["n"] == 1

        lock_writes = [(q, a) for q, a in execute_calls if "face_body_lock" in q]
        assert len(lock_writes) == 1, "locks must be written in ONE UPDATE alongside description"
        q, a = lock_writes[0]
        assert "wardrobe_lock" in q and "forbidden_drift" in q and "description" in q
        assert "Short black undercut, tan skin, athletic build, a small scar above the " \
               "left eyebrow." in a
        assert "Red leather jacket over a white crew-neck tee, dark indigo jeans, black boots." in a
        assert "hair changes color; jacket loses its collar; scar disappears" in a

        approved = [q for q, a in execute_calls if "status = 'approved'" in q]
        stamped = [q for q, a in execute_calls
                   if "characters_approved_at = now()" in q and "UPDATE videos" in q]
        assert approved, "approve_cast must still flip every character to approved"
        assert stamped, "approve_cast must still stamp videos.characters_approved_at"

    def test_unlabeled_reply_falls_back_to_whole_text_as_description_no_lock_write(self, monkeypatch):
        """A parse failure (model ignored the labeled format) must never
        fail approval, and must never write a lock column — the exact
        pre-D9-2 'whole reply becomes description' behavior is preserved."""
        char = _character_row()

        async def fake_vision_call(prompt, images, **kw):
            return UNLABELED_REPLY

        execute_calls = _run_approve_background_task(
            monkeypatch, [char], vision_impl=fake_vision_call,
            resolve_creds_returns={"provider": "anthropic", "key": "fake-key"},
        )

        lock_writes = [(q, a) for q, a in execute_calls if "face_body_lock" in q]
        assert not lock_writes, "an unparseable reply must never write a lock column"

        desc_writes = [(q, a) for q, a in execute_calls
                       if "SET description" in q and "video_characters" in q]
        assert len(desc_writes) == 1
        assert desc_writes[0][1][0] == UNLABELED_REPLY

        approved = [q for q, a in execute_calls if "status = 'approved'" in q]
        assert approved, "approval must still complete on a parse failure"

    def test_partial_reply_writes_only_the_fields_that_parsed(self, monkeypatch):
        """The model supplies DESCRIPTION + FACE_BODY_LOCK but skips
        WARDROBE_LOCK/FORBIDDEN_DRIFT this pass -> only face_body_lock is
        SET; the other two columns are left untouched (not nulled out),
        so a prior good extraction on a re-approval survives a transient
        partial miss."""
        char = _character_row()
        partial_reply = (
            "DESCRIPTION: Nyla, short black undercut, red jacket.\n"
            "FACE_BODY_LOCK: Short black undercut, tan skin, athletic build."
        )

        async def fake_vision_call(prompt, images, **kw):
            return partial_reply

        execute_calls = _run_approve_background_task(
            monkeypatch, [char], vision_impl=fake_vision_call,
            resolve_creds_returns={"provider": "anthropic", "key": "fake-key"},
        )

        lock_writes = [(q, a) for q, a in execute_calls if "face_body_lock" in q]
        assert len(lock_writes) == 1
        q, a = lock_writes[0]
        assert "wardrobe_lock" not in q
        assert "forbidden_drift" not in q

    def test_vision_call_raising_is_fail_soft_like_before(self, monkeypatch):
        """A vision provider explosion must never block approval — same
        contract the pre-D9-2 description-refresh pass already had."""
        char = _character_row()

        async def boom_vision_call(prompt, images, **kw):
            raise RuntimeError("no network in tests")

        execute_calls = _run_approve_background_task(
            monkeypatch, [char], vision_impl=boom_vision_call,
            resolve_creds_returns={"provider": "anthropic", "key": "fake-key"},
        )

        lock_writes = [(q, a) for q, a in execute_calls if "face_body_lock" in q]
        assert not lock_writes
        approved = [q for q, a in execute_calls if "status = 'approved'" in q]
        assert approved

    def test_no_claude_creds_skips_vision_pass_entirely_approval_still_completes(self, monkeypatch):
        char = _character_row()
        calls = {"n": 0}

        async def counting_vision_call(prompt, images, **kw):
            calls["n"] += 1
            return LABELED_REPLY

        execute_calls = _run_approve_background_task(
            monkeypatch, [char], vision_impl=counting_vision_call, resolve_creds_returns=None,
        )

        assert calls["n"] == 0
        approved = [q for q, a in execute_calls if "status = 'approved'" in q]
        assert approved


# ---------------------------------------------------------------------------
# 3. coverage_to_app.py consume side — precedence helpers
# ---------------------------------------------------------------------------

class TestIdentityTagOrLocksHelpers:
    def test_locks_text_joins_both_when_present(self):
        row = {"face_body_lock": "face facts.", "wardrobe_lock": "outfit facts."}
        assert coverage_to_app._locks_text(row) == "face facts.; outfit facts."

    def test_locks_text_uses_whichever_one_is_present(self):
        assert coverage_to_app._locks_text({"face_body_lock": "face facts.", "wardrobe_lock": None}) == "face facts."
        assert coverage_to_app._locks_text({"face_body_lock": "", "wardrobe_lock": "outfit facts."}) == "outfit facts."

    def test_locks_text_empty_when_neither_present(self):
        assert coverage_to_app._locks_text({}) == ""
        assert coverage_to_app._locks_text({"face_body_lock": None, "wardrobe_lock": None}) == ""

    def test_identity_tag_wins_over_locks(self):
        row = {"identity_tag": "Nyla (red jacket, undercut)",
               "face_body_lock": "face facts.", "wardrobe_lock": "outfit facts."}
        assert coverage_to_app._identity_tag_or_locks(row) == "Nyla (red jacket, undercut)"

    def test_locks_used_when_no_identity_tag(self):
        row = {"identity_tag": None, "face_body_lock": "face facts.", "wardrobe_lock": "outfit facts."}
        assert coverage_to_app._identity_tag_or_locks(row) == "face facts.; outfit facts."

    def test_empty_when_neither_identity_tag_nor_locks(self):
        assert coverage_to_app._identity_tag_or_locks({}) == ""


class TestLoadCharacterBiblePrecedence:
    """load_character_bible's costume field: identity_tag > locks >
    description > "" — the KEY backward-compat requirement is the all-NULL-
    locks row producing byte-identical costume to before this migration."""

    def _bible_for(self, monkeypatch, row):
        seen = {}

        async def fake_fetch_all(query, *args):
            seen["query"] = query
            return [row]

        monkeypatch.setattr(coverage_to_app, "fetch_all", fake_fetch_all)
        bible = asyncio.run(coverage_to_app.load_character_bible(VIDEO_ID, TENANT))
        return bible, seen["query"]

    def test_select_includes_the_new_lock_columns(self, monkeypatch):
        row = {"name": "Nyla", "identity_tag": None, "description": "prose",
               "face_body_lock": None, "wardrobe_lock": None}
        _, query = self._bible_for(monkeypatch, row)
        assert "face_body_lock" in query and "wardrobe_lock" in query

    def test_null_locks_is_byte_identical_to_pre_migration_behavior(self, monkeypatch):
        """No identity_tag, no locks -> costume falls back to description,
        EXACTLY the pre-D9-2 fallback chain."""
        row = {"name": "Nyla", "identity_tag": None,
               "description": "A woman in a blue coat.",
               "face_body_lock": None, "wardrobe_lock": None}
        bible, _ = self._bible_for(monkeypatch, row)
        assert bible["characters"][0]["costume"] == "A woman in a blue coat."

    def test_null_locks_and_identity_tag_present_unaffected_by_this_migration(self, monkeypatch):
        row = {"name": "Nyla", "identity_tag": "Nyla (red jacket, undercut, mid-20s)",
               "description": "A woman in a blue coat.",
               "face_body_lock": None, "wardrobe_lock": None}
        bible, _ = self._bible_for(monkeypatch, row)
        assert bible["characters"][0]["costume"] == "Nyla (red jacket, undercut, mid-20s)"

    def test_populated_locks_appear_verbatim_when_no_identity_tag(self, monkeypatch):
        row = {"name": "Nyla", "identity_tag": None, "description": "A woman in a blue coat.",
               "face_body_lock": "Short black undercut, tan skin, athletic build.",
               "wardrobe_lock": "Red leather jacket over a white tee, dark jeans."}
        bible, _ = self._bible_for(monkeypatch, row)
        assert bible["characters"][0]["costume"] == (
            "Short black undercut, tan skin, athletic build.; "
            "Red leather jacket over a white tee, dark jeans."
        )
        # It must be the pixel-derived facts, never the free-prose description.
        assert "blue coat" not in bible["characters"][0]["costume"]

    def test_populated_locks_do_not_override_a_creator_set_identity_tag(self, monkeypatch):
        row = {"name": "Nyla", "identity_tag": "Nyla (red jacket, undercut, mid-20s)",
               "description": "A woman in a blue coat.",
               "face_body_lock": "Short black undercut, tan skin, athletic build.",
               "wardrobe_lock": "Red leather jacket over a white tee, dark jeans."}
        bible, _ = self._bible_for(monkeypatch, row)
        assert bible["characters"][0]["costume"] == "Nyla (red jacket, undercut, mid-20s)"


# ---------------------------------------------------------------------------
# 4. locks flow VERBATIM into the board-sheet CHARACTER line
# ---------------------------------------------------------------------------

class TestCharacterIdentityLineVerbatim:
    def test_locks_appear_verbatim_in_the_composed_character_block(self):
        bible = {"characters": [{
            "id": "Nyla",
            "costume": "Short black undercut, tan skin, athletic build.; Red leather jacket "
                       "over a white tee, dark jeans.",
            "scenes_present": [],
        }]}
        line = coverage_to_app._character_identity_line(bible, 1)
        assert line.startswith("Nyla (")
        assert "Short black undercut, tan skin, athletic build." in line

    def test_null_locks_line_is_byte_identical_to_before(self):
        """A character with only a description (no identity_tag, no locks)
        renders the exact same compact tag as before this migration."""
        bible_before = {"characters": [{"id": "Nyla", "costume": "A woman in a blue coat.",
                                        "scenes_present": []}]}
        bible_after = {"characters": [{"id": "Nyla", "costume": "A woman in a blue coat.",
                                       "scenes_present": []}]}
        assert (coverage_to_app._character_identity_line(bible_before, 1)
                == coverage_to_app._character_identity_line(bible_after, 1))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
