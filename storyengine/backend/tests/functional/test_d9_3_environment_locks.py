"""Tests for D9-3 (migration 152 — Custom Film EnvironmentLock harvest).

video_environments gains three nullable columns (architecture_lock,
lighting_time_weather_lock, palette_lock), mirroring Custom Film's
EnvironmentLock (backend/custom_film_director.py:176-197) minus
geography_lock (the flagship's L3 LOCATION SCOPING law already covers that
ground — see migration 152's own comment). This file covers:

  1. _parse_environment_lock_reply (routes/environments.py): best-effort
     parse of the extended vision reply into {DESCRIPTION, ARCHITECTURE_LOCK,
     LIGHTING_TIME_WEATHER_LOCK, PALETTE_LOCK} — partial/legacy/malformed
     replies never raise. Mirrors D9-2's _parse_character_lock_reply tests.
  2. approve_environments' background task: a stubbed vision reply populates
     the three lock columns via ONE UPDATE (never a second paid vision call,
     and never touching the SEPARATE prop-manifest extraction call); a reply
     that ignores the labeled format falls back to today's
     whole-reply-as-description behavior and writes NO lock columns; a
     vision failure is fail-soft exactly like before (approval still
     completes, description/locks left untouched).
  3. scripts/coverage_to_app.py's consume side: _env_locks_text (join-skip-
     empty, mirrors _locks_text) and _canonical_environment_locks_line
     (single- and multi-location, mirrors _canonical_material_line) —
     including the KEY backward-compat case (NULL locks -> "", byte-
     identical to before this migration). _approved_envs' SELECT proven to
     include the new columns.
  4. Locks appear VERBATIM in the composed board-sheet ENVIRONMENT LOCKS
     block (_plan_sheet_prompts) once env_locks_line is populated, and the
     composed prompt is byte-identical to before this migration when
     env_locks_line is "" (the NULL-locks case).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_d9_3_environment_locks.py -q
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

import routes.environments as env_route  # noqa: E402
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
        "aspect_ratio": "16:9", "environments_approved_at": None, "project_id": None,
    }
    base.update(over)
    return base


def _env_row(**over):
    base = {
        "id": "env-1", "tenant_id": TENANT, "video_id": VIDEO_ID, "name": "Elite Viewing Hall",
        "description": "A private theatre high above the warren.",
        "reference_url": "https://example.com/hall.png",
        "status": "draft", "source": "generated", "sort": 0, "props": None,
        "architecture_lock": None, "lighting_time_weather_lock": None, "palette_lock": None,
    }
    base.update(over)
    return base


LABELED_REPLY = (
    "DESCRIPTION: A private theatre high above the warren, black ornamental walls, tiered "
    "seating facing a huge curved viewing screen, low ambient light.\n"
    "ARCHITECTURE_LOCK: Curved tiered seating facing one huge convex screen wall; black "
    "ornamental side walls with vertical fluting; no windows.\n"
    "LIGHTING_TIME_WEATHER_LOCK: Dim ambient blue up-lighting along the tiers, no visible "
    "daylight, permanently night-interior.\n"
    "PALETTE_LOCK: Black and charcoal with cold blue accent lighting."
)

UNLABELED_REPLY = (
    "A private theatre high above the warren, black ornamental walls, tiered seating facing "
    "a huge curved viewing screen, low ambient light."
)


# ---------------------------------------------------------------------------
# 1. _parse_environment_lock_reply
# ---------------------------------------------------------------------------

class TestParseEnvironmentLockReply:
    def test_full_labeled_reply_parses_all_four(self):
        parsed = env_route._parse_environment_lock_reply(LABELED_REPLY)
        assert parsed["DESCRIPTION"].startswith("A private theatre high above the warren")
        assert parsed["ARCHITECTURE_LOCK"] == (
            "Curved tiered seating facing one huge convex screen wall; black ornamental side "
            "walls with vertical fluting; no windows."
        )
        assert parsed["LIGHTING_TIME_WEATHER_LOCK"] == (
            "Dim ambient blue up-lighting along the tiers, no visible daylight, permanently "
            "night-interior."
        )
        assert parsed["PALETTE_LOCK"] == "Black and charcoal with cold blue accent lighting."

    def test_missing_label_is_simply_absent_not_an_error(self):
        reply = (
            "DESCRIPTION: A theatre with tiered seating.\n"
            "ARCHITECTURE_LOCK: Curved tiered seating, one screen wall.\n"
        )
        parsed = env_route._parse_environment_lock_reply(reply)
        assert "DESCRIPTION" in parsed
        assert "ARCHITECTURE_LOCK" in parsed
        assert "LIGHTING_TIME_WEATHER_LOCK" not in parsed
        assert "PALETTE_LOCK" not in parsed

    def test_unlabeled_legacy_style_reply_parses_to_empty_dict(self):
        """A reply that ignores the new format entirely (the pre-D9-3 shape)
        must parse to {} — never raise, never guess a label."""
        assert env_route._parse_environment_lock_reply(UNLABELED_REPLY) == {}

    def test_empty_and_none_input_are_safe(self):
        assert env_route._parse_environment_lock_reply("") == {}
        assert env_route._parse_environment_lock_reply(None) == {}

    def test_multiline_value_captured_whole_up_to_next_label(self):
        reply = (
            "DESCRIPTION: short line.\n"
            "ARCHITECTURE_LOCK: Curved tiered seating,\nfacing one screen wall,\nno windows.\n"
            "PALETTE_LOCK: black and blue"
        )
        parsed = env_route._parse_environment_lock_reply(reply)
        assert parsed["ARCHITECTURE_LOCK"] == "Curved tiered seating,\nfacing one screen wall,\nno windows."
        assert parsed["PALETTE_LOCK"] == "black and blue"

    def test_case_insensitive_labels(self):
        reply = "description: hi there\narchitecture_lock: some facts"
        parsed = env_route._parse_environment_lock_reply(reply)
        assert parsed["DESCRIPTION"] == "hi there"
        assert parsed["ARCHITECTURE_LOCK"] == "some facts"


# ---------------------------------------------------------------------------
# 2. approve_environments background task — population + fail-soft
# ---------------------------------------------------------------------------

def _patch_approve_scaffolding(monkeypatch, env_row, *, resolve_creds_returns, extract_props_impl):
    """Common monkeypatching for approve_environments tests: DB calls, the
    pipeline task-status/lane helpers, Claude-creds resolution, and the
    SEPARATE prop-manifest extraction call (stubbed to a no-op fail so it
    can never contaminate a lock-population assertion — mirrors test_c4_
    prop_manifest.py's own isolation of the two calls, the other direction).
    Returns the list `execute_calls` will be appended to (query, args)
    tuples."""
    import routes.pipeline as pipeline_mod
    import routes.model_video as model_video_mod

    execute_calls = []

    async def fake_get_video(video_id, tenant_id):
        return _video_row()

    async def fake_fetch_all(query, *args):
        return [env_row]

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

    async def fake_sync_bible(*a, **kw):
        return None

    async def fake_resolve_claude_creds(tenant_id):
        return resolve_creds_returns

    monkeypatch.setattr(env_route, "_get_video", fake_get_video)
    monkeypatch.setattr(env_route, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(env_route, "execute", fake_execute)
    monkeypatch.setattr(env_route, "_sync_bible_to_locations", fake_sync_bible)
    monkeypatch.setattr(env_route, "_extract_env_props", extract_props_impl)
    monkeypatch.setattr(pipeline_mod, "_is_task_active", fake_is_task_active)
    monkeypatch.setattr(pipeline_mod, "_set_task_status", fake_set_task_status)
    monkeypatch.setattr(pipeline_mod, "_clear_task_status", fake_clear_task_status)
    monkeypatch.setattr(pipeline_mod, "_lane_begin", fake_lane_begin)
    monkeypatch.setattr(pipeline_mod, "_lane_finish", fake_lane_finish)
    monkeypatch.setattr(model_video_mod, "_resolve_claude_creds", fake_resolve_claude_creds)

    async def fast_sleep(*a, **kw):
        return None

    monkeypatch.setattr(env_route.asyncio, "sleep", fast_sleep)

    return execute_calls


async def _boom_extract_props(*a, **kw):
    """The prop-manifest extraction is a SEPARATE paid call from the
    description/locks vision pass this file tests — stubbed to fail-soft
    (already proven fail-soft by test_c4_prop_manifest.py) so its own `SET
    props` write can never show up in a lock-population assertion here."""
    raise RuntimeError("prop extraction not under test here")


def _run_approve_background_task(monkeypatch, env_row, *, vision_impl, resolve_creds_returns):
    execute_calls = _patch_approve_scaffolding(
        monkeypatch, env_row, resolve_creds_returns=resolve_creds_returns,
        extract_props_impl=_boom_extract_props,
    )

    import shared.clients.vision_client as vision_client_mod
    monkeypatch.setattr(vision_client_mod, "vision_call", vision_impl)

    bg = _FakeBackgroundTasks()
    result = asyncio.run(env_route.approve_environments(VIDEO_ID, bg, tenant_id=TENANT))
    assert result["status"] == "running"
    assert len(bg.tasks) == 1
    fn, args, kwargs = bg.tasks[0]
    asyncio.run(fn(*args, **kwargs))  # run the background body inline
    return execute_calls


class TestApproveEnvironmentsLockPopulation:
    def test_happy_path_writes_all_three_locks_plus_description_in_one_update(self, monkeypatch):
        env = _env_row()

        calls = {"n": 0}

        async def fake_vision_call(prompt, images, **kw):
            calls["n"] += 1
            return LABELED_REPLY

        execute_calls = _run_approve_background_task(
            monkeypatch, env, vision_impl=fake_vision_call,
            resolve_creds_returns={"provider": "anthropic", "key": "fake-key"},
        )

        # ONE paid vision call per environment for description+locks — the
        # prop-manifest extraction is a separate, already fail-soft call.
        assert calls["n"] == 1

        lock_writes = [(q, a) for q, a in execute_calls if "architecture_lock" in q]
        assert len(lock_writes) == 1, "locks must be written in ONE UPDATE alongside description"
        q, a = lock_writes[0]
        assert "lighting_time_weather_lock" in q and "palette_lock" in q and "description" in q
        assert ("Curved tiered seating facing one huge convex screen wall; black ornamental "
                "side walls with vertical fluting; no windows.") in a
        assert ("Dim ambient blue up-lighting along the tiers, no visible daylight, "
                "permanently night-interior.") in a
        assert "Black and charcoal with cold blue accent lighting." in a

        approved = [q for q, a in execute_calls if "status = 'approved'" in q]
        stamped = [q for q, a in execute_calls
                   if "environments_approved_at = now()" in q and "UPDATE videos" in q]
        assert approved, "approve_environments must still flip every environment to approved"
        assert stamped, "approve_environments must still stamp videos.environments_approved_at"

    def test_unlabeled_reply_falls_back_to_whole_text_as_description_no_lock_write(self, monkeypatch):
        """A parse failure (model ignored the labeled format) must never
        fail approval, and must never write a lock column — the exact
        pre-D9-3 'whole reply becomes description' behavior is preserved."""
        env = _env_row()

        async def fake_vision_call(prompt, images, **kw):
            return UNLABELED_REPLY

        execute_calls = _run_approve_background_task(
            monkeypatch, env, vision_impl=fake_vision_call,
            resolve_creds_returns={"provider": "anthropic", "key": "fake-key"},
        )

        lock_writes = [(q, a) for q, a in execute_calls if "architecture_lock" in q]
        assert not lock_writes, "an unparseable reply must never write a lock column"

        desc_writes = [(q, a) for q, a in execute_calls
                       if "SET description" in q and "video_environments" in q]
        assert len(desc_writes) == 1
        assert desc_writes[0][1][0] == UNLABELED_REPLY

        approved = [q for q, a in execute_calls if "status = 'approved'" in q]
        assert approved, "approval must still complete on a parse failure"

    def test_partial_reply_writes_only_the_fields_that_parsed(self, monkeypatch):
        """The model supplies DESCRIPTION + ARCHITECTURE_LOCK but skips
        LIGHTING_TIME_WEATHER_LOCK/PALETTE_LOCK this pass -> only
        architecture_lock is SET; the other two columns are left untouched
        (not nulled out), so a prior good extraction on a re-approval
        survives a transient partial miss."""
        env = _env_row()
        partial_reply = (
            "DESCRIPTION: A theatre with tiered seating.\n"
            "ARCHITECTURE_LOCK: Curved tiered seating, one screen wall, no windows."
        )

        async def fake_vision_call(prompt, images, **kw):
            return partial_reply

        execute_calls = _run_approve_background_task(
            monkeypatch, env, vision_impl=fake_vision_call,
            resolve_creds_returns={"provider": "anthropic", "key": "fake-key"},
        )

        lock_writes = [(q, a) for q, a in execute_calls if "architecture_lock" in q]
        assert len(lock_writes) == 1
        q, a = lock_writes[0]
        assert "lighting_time_weather_lock" not in q
        assert "palette_lock" not in q

    def test_vision_call_raising_is_fail_soft_like_before(self, monkeypatch):
        """A vision provider explosion must never block approval — same
        contract the pre-D9-3 description-refresh pass already had."""
        env = _env_row()

        async def boom_vision_call(prompt, images, **kw):
            raise RuntimeError("no network in tests")

        execute_calls = _run_approve_background_task(
            monkeypatch, env, vision_impl=boom_vision_call,
            resolve_creds_returns={"provider": "anthropic", "key": "fake-key"},
        )

        lock_writes = [(q, a) for q, a in execute_calls if "architecture_lock" in q]
        assert not lock_writes
        approved = [q for q, a in execute_calls if "status = 'approved'" in q]
        assert approved

    def test_no_claude_creds_skips_vision_pass_entirely_approval_still_completes(self, monkeypatch):
        env = _env_row()
        calls = {"n": 0}

        async def counting_vision_call(prompt, images, **kw):
            calls["n"] += 1
            return LABELED_REPLY

        execute_calls = _run_approve_background_task(
            monkeypatch, env, vision_impl=counting_vision_call, resolve_creds_returns=None,
        )

        assert calls["n"] == 0
        approved = [q for q, a in execute_calls if "status = 'approved'" in q]
        assert approved


# ---------------------------------------------------------------------------
# 3. coverage_to_app.py consume side — precedence helpers
# ---------------------------------------------------------------------------

class TestEnvLocksTextHelper:
    def test_joins_all_three_when_present(self):
        row = {"architecture_lock": "structure facts.", "lighting_time_weather_lock": "light facts.",
               "palette_lock": "palette facts."}
        assert coverage_to_app._env_locks_text(row) == "structure facts.; light facts.; palette facts."

    def test_uses_whichever_are_present(self):
        assert coverage_to_app._env_locks_text(
            {"architecture_lock": "structure facts.", "lighting_time_weather_lock": None,
             "palette_lock": None}) == "structure facts."
        assert coverage_to_app._env_locks_text(
            {"architecture_lock": "", "lighting_time_weather_lock": "light facts.",
             "palette_lock": None}) == "light facts."

    def test_empty_when_none_present(self):
        assert coverage_to_app._env_locks_text({}) == ""
        assert coverage_to_app._env_locks_text(
            {"architecture_lock": None, "lighting_time_weather_lock": None, "palette_lock": None}) == ""


class TestCanonicalEnvironmentLocksLine:
    """Mirrors _canonical_material_line's own test shape (not present as a
    dedicated class in this file, but exercised implicitly via
    _sheet_kwargs in production) — single-location and multi-location
    (LOCSET) cases, plus the KEY backward-compat NULL case."""

    def test_single_location_no_location_sets_returns_matched_env_locks(self):
        envs = [{"name": "Elite Viewing Hall", "architecture_lock": "structure facts.",
                 "lighting_time_weather_lock": "light facts.", "palette_lock": "palette facts."}]
        matched = envs[0]
        line = coverage_to_app._canonical_environment_locks_line(envs, {}, matched)
        assert line == "structure facts.; light facts.; palette facts."

    def test_single_location_null_locks_is_empty_string(self):
        """THE key backward-compat case: an approved environment with no
        locks authored yet produces "" — every consumer's fallback
        (nothing stamped) is unchanged from before migration 152."""
        envs = [{"name": "Elite Viewing Hall", "architecture_lock": None,
                 "lighting_time_weather_lock": None, "palette_lock": None}]
        matched = envs[0]
        assert coverage_to_app._canonical_environment_locks_line(envs, {}, matched) == ""

    def test_no_matched_env_returns_empty_string(self):
        assert coverage_to_app._canonical_environment_locks_line([], {}, None) == ""

    def test_multi_location_one_clause_per_locset_with_locks(self):
        envs = [
            {"name": "Pod", "architecture_lock": "pod structure.", "lighting_time_weather_lock": None,
             "palette_lock": None},
            {"name": "Elite Viewing Hall", "architecture_lock": "hall structure.",
             "lighting_time_weather_lock": "hall light.", "palette_lock": None},
            {"name": "Corridor", "architecture_lock": None, "lighting_time_weather_lock": None,
             "palette_lock": None},
        ]
        location_sets = {"Pod": "pod set text", "Elite Viewing Hall": "hall set text",
                          "Corridor": "corridor set text"}
        line = coverage_to_app._canonical_environment_locks_line(envs, location_sets, None)
        assert "POD: pod structure." in line
        assert "ELITE VIEWING HALL: hall structure.; hall light." in line
        # Corridor has no locks authored -> simply omitted, never invented.
        assert "CORRIDOR" not in line

    def test_multi_location_all_null_returns_empty_string(self):
        envs = [{"name": "Pod", "architecture_lock": None, "lighting_time_weather_lock": None,
                 "palette_lock": None}]
        location_sets = {"Pod": "pod set text"}
        assert coverage_to_app._canonical_environment_locks_line(envs, location_sets, None) == ""


class TestApprovedEnvsSelectIncludesLockColumns:
    def test_select_includes_the_new_lock_columns(self, monkeypatch):
        seen = {}

        async def fake_fetch_all(query, *args):
            seen["query"] = query
            return []

        monkeypatch.setattr(coverage_to_app, "fetch_all", fake_fetch_all)
        asyncio.run(coverage_to_app._approved_envs(VIDEO_ID, TENANT))
        assert "architecture_lock" in seen["query"]
        assert "lighting_time_weather_lock" in seen["query"]
        assert "palette_lock" in seen["query"]

    def test_approved_envs_carries_the_lock_values_through(self, monkeypatch):
        raw_row = {
            "name": "Elite Viewing Hall", "description": "A theatre.",
            "reference_url": "https://example.com/hall.png", "props": None,
            "architecture_lock": "structure facts.", "lighting_time_weather_lock": "light facts.",
            "palette_lock": "palette facts.",
        }

        async def fake_fetch_all(query, *a):
            return [raw_row]

        monkeypatch.setattr(coverage_to_app, "fetch_all", fake_fetch_all)
        envs = asyncio.run(coverage_to_app._approved_envs(VIDEO_ID, TENANT))
        assert envs[0]["architecture_lock"] == "structure facts."
        assert envs[0]["lighting_time_weather_lock"] == "light facts."
        assert envs[0]["palette_lock"] == "palette facts."


# ---------------------------------------------------------------------------
# 4. locks flow VERBATIM into the board-sheet ENVIRONMENT LOCKS block, and
#    NULL locks produce a byte-identical prompt to before this migration.
# ---------------------------------------------------------------------------

_MOMENTS = [{
    "moment_number": 1,
    "master": {"shot_type": "WS", "description": "Wide shot of the hall, dim ambient light."},
    "angles": [],
}]


class TestPlanSheetPromptsEnvironmentLocksBlock:
    def test_env_locks_line_appears_verbatim_as_its_own_block(self):
        panels = coverage_to_app._plan_sheet_prompts(
            _MOMENTS, style_dir="Photoreal",
            env_locks_line="Curved tiered seating facing one screen wall.; Black and blue palette.",
        )
        joined = "\n".join(panels)
        assert "ENVIRONMENT LOCKS — fixed for this whole set:" in joined
        assert "Curved tiered seating facing one screen wall.; Black and blue palette." in joined

    def test_empty_env_locks_line_is_byte_identical_to_omitting_the_parameter(self):
        """THE key backward-compat test: a caller passing env_locks_line=""
        (the NULL-locks case, every video before migration 152) produces
        output byte-identical to never having added the parameter at all."""
        with_default = coverage_to_app._plan_sheet_prompts(_MOMENTS, style_dir="Photoreal")
        with_explicit_empty = coverage_to_app._plan_sheet_prompts(
            _MOMENTS, style_dir="Photoreal", env_locks_line="")
        assert with_default == with_explicit_empty
        assert "ENVIRONMENT LOCKS" not in "\n".join(with_default)

    def test_env_locks_block_sits_immediately_after_material_block(self):
        """Ordering check: ENVIRONMENT LOCKS follows MATERIAL MAP in the
        composed prompt, matching the concatenation order in
        _plan_sheet_prompts (material_block then env_locks_block)."""
        panels = coverage_to_app._plan_sheet_prompts(
            _MOMENTS, style_dir="Photoreal",
            material_line="glass upper walls, solid lower walls.",
            env_locks_line="Curved tiered seating.",
        )
        joined = "\n".join(panels)
        mat_idx = joined.index("MATERIAL MAP")
        lock_idx = joined.index("ENVIRONMENT LOCKS")
        assert mat_idx < lock_idx


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
