"""Tests for D9-4 (storyengine/tasks/loop-checklist.md, D9 HARVEST chunks):
video_characters.forbidden_drift (migration 151, harvested by D9-2's
approve_cast vision pass but STORED ONLY until this chunk — see that
migration's own column comment) is finally consumed, at two live points:

  1. PROMPTS (scripts/coverage_to_app.py) — load_character_bible carries
     forbidden_drift onto each bible character; _character_identity_line
     (board-sheet CHARACTER lines) and redraw_asset_image's inline
     CHARACTER-block composer both append it as a verbatim " NEVER: ..."
     clause via the new shared _never_clause/_character_tag helpers.
  2. JUDGE RUBRIC (frame_arbiter.py + frame_arbiter_hook.py) —
     _board_rubric_prompt (the board station judge_board_sheet uses, the
     ONE thing frame_arbiter_hook.run_after_storyboard_sheet actually
     calls in production per that module's own docstring) gains an
     optional CHARACTER DRIFT CONSTRAINTS section + a 5th judge
     instruction, sourced by frame_arbiter_hook.py's own DB read
     (_fetch_character_drift_text) and composed by frame_arbiter.
     compose_character_drift_text — read straight off an OPTIONAL
     sheet["character_drift_text"] key (the SAME dict spec_text/image_url
     already ride in on), never a new judge_fn parameter, so the DI seam
     every test_d5_a6_arbiter_hook.py fake judge_fn already uses is
     untouched.

Both surfaces are additive-only: every "byte-identical" test below proves
NULL/absent forbidden_drift reproduces the EXACT pre-chunk output, not just
"no exception".

$0 suite — same DB/network-injection conventions test_d9_2_character_locks.py
(monkeypatch coverage_to_app's module attributes directly) and
test_d5_a3b_eval_harness.py (DI'd download_image/call_vision on
judge_board_sheet) already use. NO live DB, NO network, NO vision spend.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_d9_4_forbidden_drift.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import frame_arbiter as fa  # noqa: E402
import frame_arbiter_hook as hook  # noqa: E402
import scripts.coverage_to_app as coverage_to_app  # noqa: E402

TENANT = "tenant-d94"
VIDEO_ID = "video-d94"


def _run(coro):
    return asyncio.run(coro)


# =============================================================================
# 1a. PROMPTS — shared helpers (_never_clause, _character_tag)
# =============================================================================

class TestNeverClause:
    def test_none_and_empty_and_blank_are_empty(self):
        assert coverage_to_app._never_clause(None) == ""
        assert coverage_to_app._never_clause("") == ""
        assert coverage_to_app._never_clause("   ") == ""

    def test_populated_renders_leading_space_never_prefix_verbatim(self):
        assert (coverage_to_app._never_clause("hair changes color; suit gains a tie")
                == " NEVER: hair changes color; suit gains a tie")

    def test_strips_surrounding_whitespace_only(self):
        assert coverage_to_app._never_clause("  hair changes color  ") == " NEVER: hair changes color"


class TestCharacterTag:
    def test_name_only_when_no_descriptor_no_drift(self):
        assert coverage_to_app._character_tag("Nyla", "", None) == "Nyla"

    def test_name_and_descriptor_unchanged_when_no_drift(self):
        assert coverage_to_app._character_tag("Nyla", "red jacket", None) == "Nyla (red jacket)"

    def test_never_clause_appended_after_descriptor(self):
        assert (coverage_to_app._character_tag("Nyla", "red jacket", "hair changes color")
                == "Nyla (red jacket) NEVER: hair changes color")

    def test_never_clause_appended_to_bare_name_when_no_descriptor(self):
        assert (coverage_to_app._character_tag("Nyla", "", "hair changes color")
                == "Nyla NEVER: hair changes color")


# =============================================================================
# 1b. PROMPTS — load_character_bible carries forbidden_drift
# =============================================================================

class TestLoadCharacterBibleForbiddenDrift:
    def _bible_for(self, monkeypatch, row):
        seen = {}

        async def fake_fetch_all(query, *args):
            seen["query"] = query
            return [row]

        monkeypatch.setattr(coverage_to_app, "fetch_all", fake_fetch_all)
        bible = asyncio.run(coverage_to_app.load_character_bible(VIDEO_ID, TENANT))
        return bible, seen["query"]

    def test_select_includes_forbidden_drift(self, monkeypatch):
        row = {"name": "Nyla", "identity_tag": None, "description": "prose",
               "face_body_lock": None, "wardrobe_lock": None, "forbidden_drift": None}
        _, query = self._bible_for(monkeypatch, row)
        assert "forbidden_drift" in query

    def test_populated_drift_carried_onto_the_character_dict_as_its_own_key(self, monkeypatch):
        row = {"name": "Nyla", "identity_tag": None, "description": "A woman in a blue coat.",
               "face_body_lock": None, "wardrobe_lock": None,
               "forbidden_drift": "hair changes color; suit gains a tie"}
        bible, _ = self._bible_for(monkeypatch, row)
        char = bible["characters"][0]
        assert char["forbidden_drift"] == "hair changes color; suit gains a tie"
        # forbidden_drift rides a SEPARATE key -- costume (identity/locks/description
        # precedence) is completely untouched by this column.
        assert char["costume"] == "A woman in a blue coat."

    def test_null_drift_key_is_none(self, monkeypatch):
        row = {"name": "Nyla", "identity_tag": None, "description": "prose",
               "face_body_lock": None, "wardrobe_lock": None, "forbidden_drift": None}
        bible, _ = self._bible_for(monkeypatch, row)
        assert bible["characters"][0]["forbidden_drift"] is None


# =============================================================================
# 1c. PROMPTS — _character_identity_line (board-sheet CHARACTER lines)
# =============================================================================

class TestCharacterIdentityLineDrift:
    def test_never_clause_appears_verbatim_in_the_composed_line(self):
        bible = {"characters": [{
            "id": "Nyla", "costume": "red jacket, undercut",
            "forbidden_drift": "hair changes color; jacket loses its collar",
            "scenes_present": [],
        }]}
        line = coverage_to_app._character_identity_line(bible, 1)
        assert line == "Nyla (red jacket, undercut) NEVER: hair changes color; jacket loses its collar"

    def test_absent_forbidden_drift_key_is_byte_identical_to_no_forbidden_drift_at_all(self):
        bible_no_key = {"characters": [{"id": "Nyla", "costume": "red jacket, undercut", "scenes_present": []}]}
        bible_with_none = {"characters": [{"id": "Nyla", "costume": "red jacket, undercut",
                                           "forbidden_drift": None, "scenes_present": []}]}
        line_a = coverage_to_app._character_identity_line(bible_no_key, 1)
        line_b = coverage_to_app._character_identity_line(bible_with_none, 1)
        assert line_a == line_b == "Nyla (red jacket, undercut)"

    def test_forbidden_drift_is_never_truncated_by_shorts_60_char_rule(self):
        long_drift = "eyes change from brown to blue" + (", extra descriptive words" * 4)
        assert len(long_drift) > 60
        bible = {"characters": [{"id": "Nyla", "costume": "", "forbidden_drift": long_drift,
                                 "scenes_present": []}]}
        line = coverage_to_app._character_identity_line(bible, 1)
        assert long_drift in line


# =============================================================================
# 1d. PROMPTS — redraw_asset_image's inline CHARACTER-block composer
# =============================================================================

_STORED_PROMPT = "(SETUP B) MCU OTS onto Nyla, glancing at the prep board"


class TestRedrawAssetImageCharacterDrift:
    VID, TENANT, ASSET = "vid-d94", "tenant-d94", "asset-d94"

    def _run_redraw(self, monkeypatch, crows):
        calls = []

        async def fake_fetch_one(query, *args):
            if "FROM assets a JOIN videos v" in query:
                return {"id": self.ASSET, "scene": 1, "image_index": 100,
                        "image_prompt": _STORED_PROMPT, "hero_shot": True,
                        "generation_method": "coverage", "aspect": "16:9",
                        "image_model_override": None, "image_style_override": None,
                        "visual_style": None}
            if "coverage_directive, scene_text FROM scripts" in query:
                return {"coverage_directive": "", "scene_text": ""}
            raise AssertionError(f"unexpected fetch_one: {query}")

        async def fake_fetch_all(query, *args):
            if "FROM video_characters" in query:
                assert "forbidden_drift" in query
                return crows
            raise AssertionError(f"unexpected fetch_all: {query}")

        async def fake_gen(ic, model_override, prompt, reference_urls=None, **kw):
            calls.append(prompt)
            return "https://fake/redrawn.png", "gpt-image-2"

        monkeypatch.setattr(coverage_to_app, "fetch_one", fake_fetch_one)
        monkeypatch.setattr(coverage_to_app, "fetch_all", fake_fetch_all)
        monkeypatch.setattr(coverage_to_app, "execute", AsyncMock())
        monkeypatch.setattr(coverage_to_app, "get_secret", AsyncMock(return_value="fake-key"))
        monkeypatch.setattr(coverage_to_app, "ImageClient", lambda **kw: object())
        monkeypatch.setattr(coverage_to_app, "_approved_envs", AsyncMock(return_value=[]))
        monkeypatch.setattr(coverage_to_app, "generate_scene_image_for_model", fake_gen)
        monkeypatch.setattr(coverage_to_app, "_stable_url", AsyncMock(return_value="https://stable/x.png"))
        monkeypatch.setattr(coverage_to_app, "record_ledger_entry", AsyncMock())

        result = asyncio.run(coverage_to_app.redraw_asset_image(self.VID, self.TENANT, self.ASSET))
        assert result["status"] == "completed", result
        assert len(calls) == 1
        return calls[0]

    def test_never_clause_appears_verbatim_in_the_assembled_prompt(self, monkeypatch):
        crows = [{"name": "Nyla", "identity_tag": None, "reference_url": "https://fake/nyla.png",
                  "face_body_lock": "Short black undercut.", "wardrobe_lock": "Red leather jacket.",
                  "forbidden_drift": "hair changes color; jacket loses its collar"}]
        prompt = self._run_redraw(monkeypatch, crows)
        assert "NEVER: hair changes color; jacket loses its collar" in prompt

    @staticmethod
    def _character_note(prompt: str) -> str:
        """Isolates the " CHARACTER — stated once, drawn identically: ...."
        note from the rest of the assembled prompt (which also contains the
        STORED_PROMPT's own free text, e.g. "Nyla" in the shot description,
        and whose descriptor text may itself contain periods) so assertions
        below check ONLY the note this chunk touches, not unrelated
        boilerplate elsewhere in the prompt (_STYLE_LOCK's own "NEVER draw
        speech bubbles..." sentence, for one). cast_identity_note is
        concatenated directly before _STORED_PROMPT with no separator (see
        redraw_asset_image's generate_scene_image_for_model call), so
        everything up to _STORED_PROMPT's own start is style_prefix (empty
        here, no style override) + cast_identity_note."""
        marker = "CHARACTER — stated once, drawn identically:"
        before_stored_prompt = prompt.split(_STORED_PROMPT, 1)[0]
        if marker not in before_stored_prompt:
            return ""
        return before_stored_prompt[before_stored_prompt.index(marker):]

    def test_null_forbidden_drift_is_byte_identical_to_before_this_chunk(self, monkeypatch):
        crows = [{"name": "Nyla", "identity_tag": None, "reference_url": "https://fake/nyla.png",
                  "face_body_lock": "Short black undercut.", "wardrobe_lock": "Red leather jacket.",
                  "forbidden_drift": None}]
        prompt = self._run_redraw(monkeypatch, crows)
        note = self._character_note(prompt)
        assert "NEVER" not in note
        # Exactly the OLD f"{name} ({_identity_tag_or_locks(r)})" shape.
        assert note == (
            "CHARACTER — stated once, drawn identically: "
            "Nyla (Short black undercut.; Red leather jacket.)."
        )

    def test_character_with_only_forbidden_drift_still_surfaces(self, monkeypatch):
        """Previously a row with no identity_tag/locks was excluded from
        the CHARACTER block entirely. A row whose ONLY signal is
        forbidden_drift must still surface (as bare "Name NEVER: ...")."""
        crows = [{"name": "Nyla", "identity_tag": None, "reference_url": "https://fake/nyla.png",
                  "face_body_lock": None, "wardrobe_lock": None,
                  "forbidden_drift": "hair changes color"}]
        prompt = self._run_redraw(monkeypatch, crows)
        assert "Nyla NEVER: hair changes color" in self._character_note(prompt)

    def test_no_signal_at_all_row_still_excluded(self, monkeypatch):
        """A row with neither identity/locks nor forbidden_drift contributes
        nothing to the CHARACTER block -- unchanged from before this chunk."""
        crows = [{"name": "Nyla", "identity_tag": None, "reference_url": "https://fake/nyla.png",
                  "face_body_lock": None, "wardrobe_lock": None, "forbidden_drift": None}]
        prompt = self._run_redraw(monkeypatch, crows)
        assert "CHARACTER — stated once, drawn identically:" not in prompt


# =============================================================================
# 2a. JUDGE RUBRIC — compose_character_drift_text (pure text, no I/O)
# =============================================================================

class TestComposeCharacterDriftText:
    def test_empty_and_none_are_empty_string(self):
        assert fa.compose_character_drift_text([]) == ""
        assert fa.compose_character_drift_text(None) == ""

    def test_single_character_single_entry(self):
        text = fa.compose_character_drift_text([{"name": "Nyla", "forbidden_drift": "hair changes color"}])
        assert text == "- flag as MODEL_DEFECT if: Nyla: hair changes color"

    def test_splits_semicolon_and_newline_separated_entries(self):
        text = fa.compose_character_drift_text([
            {"name": "Nyla", "forbidden_drift": "hair changes color; jacket loses its collar\nscar disappears"},
        ])
        assert text.splitlines() == [
            "- flag as MODEL_DEFECT if: Nyla: hair changes color",
            "- flag as MODEL_DEFECT if: Nyla: jacket loses its collar",
            "- flag as MODEL_DEFECT if: Nyla: scar disappears",
        ]

    def test_multiple_characters_each_contribute_their_own_lines(self):
        text = fa.compose_character_drift_text([
            {"name": "Nyla", "forbidden_drift": "hair changes color"},
            {"name": "Marcus", "forbidden_drift": "loses his glasses"},
        ])
        assert "- flag as MODEL_DEFECT if: Nyla: hair changes color" in text
        assert "- flag as MODEL_DEFECT if: Marcus: loses his glasses" in text

    def test_none_or_blank_forbidden_drift_contributes_nothing(self):
        assert fa.compose_character_drift_text([{"name": "Nyla", "forbidden_drift": None}]) == ""
        assert fa.compose_character_drift_text([{"name": "Nyla", "forbidden_drift": "   "}]) == ""


# =============================================================================
# 2b. JUDGE RUBRIC — _board_rubric_prompt
# =============================================================================

def _one_panel():
    return [{"panel": 1, "label": "M1 WS", "setup": "A", "expected_set": "a plain interior room",
             "brief": "Wide shot of the room, a character stands center frame."}]


class TestBoardRubricPromptCharacterDrift:
    def test_default_call_omits_the_section_entirely(self):
        text = fa._board_rubric_prompt(_one_panel(), None)
        assert "CHARACTER DRIFT" not in text
        assert "JUDGE THIS SHEET against FOUR things" in text

    def test_explicit_empty_string_is_byte_identical_to_the_default_call(self):
        panels = _one_panel()
        assert fa._board_rubric_prompt(panels, None) == fa._board_rubric_prompt(panels, None, "")

    def test_populated_adds_context_section_verbatim_plus_fifth_instruction(self):
        drift_text = "- flag as MODEL_DEFECT if: Nyla: hair changes color"
        text = fa._board_rubric_prompt(_one_panel(), None, drift_text)
        assert "CHARACTER DRIFT CONSTRAINTS" in text
        assert drift_text in text
        assert "5. CHARACTER DRIFT" in text
        assert "JUDGE THIS SHEET against FIVE things" in text

    def test_populated_does_not_touch_the_reply_format_instructions(self):
        """D9-5's sweep ruling forbids changing parse_verdict's reply
        format -- the CLASSIFICATION/FAILURE_CLASS/... block must be
        untouched regardless of character_drift_text."""
        drift_text = "- flag as MODEL_DEFECT if: Nyla: hair changes color"
        without = fa._board_rubric_prompt(_one_panel(), None)
        with_drift = fa._board_rubric_prompt(_one_panel(), None, drift_text)
        reply_format_tail = without.split("Reply with EXACTLY")[-1]
        assert with_drift.endswith(reply_format_tail)


# =============================================================================
# 2c. JUDGE RUBRIC — judge_board_sheet reads sheet["character_drift_text"]
# =============================================================================

def _spec_text():
    return (
        "This is storyboard sheet 1 of 5: a grid of 1 panel.\n"
        "FIXED SET — identical in every panel: a plain interior room.\n\n"
        "[1] M1 WS — (SETUP A) Wide shot of the room, a character stands center frame.\n"
    )


async def _fake_download(_url):
    return ("image/jpeg", "ZmFrZQ==")  # base64("fake")


def _ok_reply():
    return (
        "===PANEL 1===\n"
        "NEW_VS_PREVIOUS: FIRST_PANEL\n"
        "CLASSIFICATION: OK\n"
        "FAILURE_CLASS: NONE\n"
        "RULE_ID: NONE\n"
        "RUBRIC_LEVEL: guidance\n"
        "DECISIVE_FRAGMENT: NONE\n"
        "DESCRIPTION: fine\n"
    )


async def _no_breach(*a, **k):
    return None


async def _sink_ledger(**kw):
    return None


async def _sink_finding(*a, **kw):
    return {"crossed_threshold": False}


class TestJudgeBoardSheetCharacterDrift:
    def test_character_drift_text_reaches_the_assembled_vision_prompt(self):
        captured = {}

        async def fake_vision(tenant_id, content, **kw):
            captured["content"] = content
            return {"content": [{"type": "text", "text": _ok_reply()}],
                    "usage": {"input_tokens": 100, "output_tokens": 20}}

        sheet = {"image_url": "https://x/sheet.png", "sheet_index": 1, "spec_text": _spec_text(),
                 "character_drift_text": "- flag as MODEL_DEFECT if: Nyla: hair changes color"}
        result = _run(fa.judge_board_sheet(
            "tenant-x", "video-x", 1, sheet, download_image=_fake_download, call_vision=fake_vision,
            budget_check=_no_breach, ledger_write=_sink_ledger, record_finding_fn=_sink_finding,
        ))
        assert result["skipped"] is False
        prompt_text = next(b["text"] for b in captured["content"] if b.get("type") == "text")
        assert "Nyla: hair changes color" in prompt_text

    def test_absent_key_produces_a_byte_identical_prompt_to_before_this_chunk(self):
        captured = {}

        async def fake_vision(tenant_id, content, **kw):
            captured["content"] = content
            return {"content": [{"type": "text", "text": _ok_reply()}],
                    "usage": {"input_tokens": 100, "output_tokens": 20}}

        sheet_without_key = {"image_url": "https://x/sheet.png", "sheet_index": 1, "spec_text": _spec_text()}
        _run(fa.judge_board_sheet(
            "tenant-x", "video-x", 1, sheet_without_key, download_image=_fake_download, call_vision=fake_vision,
            budget_check=_no_breach, ledger_write=_sink_ledger, record_finding_fn=_sink_finding,
        ))
        prompt_without = next(b["text"] for b in captured["content"] if b.get("type") == "text")

        fixed_set, panels = fa._parse_sheet_panels(_spec_text(), 1)
        expected = fa._board_rubric_prompt(panels, fixed_set)
        assert prompt_without == expected

    def test_di_seam_signature_unchanged_a_4_positional_arg_judge_fn_wrapper_still_works(self):
        """The EXACT wrapper shape test_d5_a6_arbiter_hook.py's fakes use:
        judge_fn(tenant_id, video_id, scene, sheet) -- no new keyword arg.
        This proves run_after_storyboard_sheet's own call site (unmodified
        by this chunk) still only ever calls judge_fn with those 4
        positionals, so those tests' fake judge_fn signatures never break."""
        async def fake_vision(tenant_id, content, **kw):
            return {"content": [{"type": "text", "text": _ok_reply()}],
                    "usage": {"input_tokens": 50, "output_tokens": 10}}

        sheet = {"image_url": "https://x/sheet.png", "sheet_index": 1, "spec_text": _spec_text(),
                 "character_drift_text": "- flag as MODEL_DEFECT if: Nyla: hair changes color"}

        async def judge_fn(tenant_id, video_id, scene, sheet_arg):  # no **kwargs, no extra positional
            return await fa.judge_board_sheet(
                tenant_id, video_id, scene, sheet_arg,
                download_image=_fake_download, call_vision=fake_vision,
                budget_check=_no_breach, ledger_write=_sink_ledger, record_finding_fn=_sink_finding,
            )

        result = _run(judge_fn(TENANT, VIDEO_ID, 1, sheet))
        assert result["skipped"] is False


# =============================================================================
# 2d. JUDGE RUBRIC — frame_arbiter_hook's DB read + sheet-dict wiring
# =============================================================================

class TestFetchCharacterDriftText:
    def test_composes_from_real_rows(self, monkeypatch):
        async def fake_fetch_all(query, *args):
            assert "forbidden_drift IS NOT NULL" in query
            assert args == (VIDEO_ID, TENANT)
            return [{"name": "Nyla", "forbidden_drift": "hair changes color"}]

        monkeypatch.setattr(hook, "fetch_all", fake_fetch_all)
        text = _run(hook._fetch_character_drift_text(TENANT, VIDEO_ID))
        assert text == "- flag as MODEL_DEFECT if: Nyla: hair changes color"

    def test_no_rows_is_empty_string(self, monkeypatch):
        async def fake_fetch_all(query, *args):
            return []

        monkeypatch.setattr(hook, "fetch_all", fake_fetch_all)
        assert _run(hook._fetch_character_drift_text(TENANT, VIDEO_ID)) == ""

    def test_db_error_is_fail_soft_never_blocks_a_board_judgment(self, monkeypatch):
        async def boom_fetch_all(query, *args):
            raise RuntimeError("db unreachable")

        monkeypatch.setattr(hook, "fetch_all", boom_fetch_all)
        assert _run(hook._fetch_character_drift_text(TENANT, VIDEO_ID)) == ""


class TestFetchSceneSheetsAttachesCharacterDrift:
    def _stub_fetch_all(self, monkeypatch, *, character_rows):
        async def fake_fetch_all(query, *args):
            if "storyboard_1_url" in query:
                return [{"storyboard_1_url": "https://x/s1.png", "storyboard_2_url": None,
                         "storyboard_3_url": None, "storyboard_4_url": None, "storyboard_5_url": None,
                         "storyboard_beat_count": 1, "storyboard_prompts": "spec"}]
            if "video_characters" in query:
                return character_rows
            raise AssertionError(f"unexpected query: {query}")

        monkeypatch.setattr(hook, "fetch_all", fake_fetch_all)

    def test_sheets_carry_character_drift_text_when_populated(self, monkeypatch):
        self._stub_fetch_all(monkeypatch, character_rows=[
            {"name": "Nyla", "forbidden_drift": "hair changes color"}])
        sheets = _run(hook._fetch_scene_sheets(TENANT, VIDEO_ID, 1))
        assert len(sheets) == 1
        assert sheets[0]["character_drift_text"] == "- flag as MODEL_DEFECT if: Nyla: hair changes color"
        # spec_text/image_url/sheet_index untouched -- additive only.
        assert sheets[0]["spec_text"] == "spec"
        assert sheets[0]["image_url"] == "https://x/s1.png"

    def test_no_character_drift_omits_the_key_entirely_byte_identical_dict_shape(self, monkeypatch):
        self._stub_fetch_all(monkeypatch, character_rows=[])
        sheets = _run(hook._fetch_scene_sheets(TENANT, VIDEO_ID, 1))
        assert len(sheets) == 1
        assert "character_drift_text" not in sheets[0]
        assert sheets[0] == {"image_url": "https://x/s1.png", "sheet_index": 1, "spec_text": "spec"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
