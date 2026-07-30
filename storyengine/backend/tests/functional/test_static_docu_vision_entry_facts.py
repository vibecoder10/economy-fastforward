"""VIS-1 (2026-07-30): the vision identity check asks about THIS machine in
THIS role and era, not just a name.

WHY: audited live on video d2e37cd6 ("Every British Aircraft Carrier Class
Ever Built") — the sweep's alias path found candidates for 5 previously
unfindable roster entries and the old name-only vision question "verified"
4 of them WRONG:

  - "Courageous class"      -> Courageous as a WWI BATTLECRUISER (gun
                               turrets, no flight deck - pre-conversion)
  - "Majestic class"        -> HMS Glory, a COLOSSUS-class ship (a sister
                               design that is a DIFFERENT entry in the same
                               roster)
  - "Pretoria Castle"       -> her post-war LINER reconversion
  - "Ruler class (US-built)" -> USS Guadalcanal, a US Navy CASABLANCA-class
                               CVE that was never a British ship

Pixels alone cannot split sister classes, but the candidate's own filename
usually names the actual unit photographed — so the filename is handed to
the model as text (`source_label`). Era/configuration mismatches ARE visible
in pixels once the question states the role and era — so the roster entry's
own role/years/status/built_count are handed over too (`facts`, threaded
from pipeline_executor._machine_documentary_hold_roster_entries).

These tests pin the PROMPT CONTENT (what question gets asked), not the
model's answer — the question was the broken part.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_vision_entry_facts.py -q
"""
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import static_docu  # noqa: E402

# Same pre-import + fake-harness reuse as the other vision test files (see
# test_static_docu_c2g_vision_download_fix.py for why the pre-import matters).
import shared.clients.image_client  # noqa: E402,F401

from test_static_docu_c2f_vision_gate_fixes import (  # noqa: E402
    _FakeImageResp,
    _anthropic_body,
    _install_vision_fakes,
)

_FAKE_JPEG = b"\xff\xd8\xff" + b"1" * 64

_FACTS = {
    "role": "Merchant Aircraft Carriers - grain/oil tankers with flight decks",
    "years": "Conversions 1943-1944, operated until 1945",
    "status": "converted",
    "built_count": "19 grain ships and 6 tankers converted",
}


async def _ask_and_capture(monkeypatch, **kwargs):
    """Run _vision_confirms against the fake model and return the exact
    prompt text that was sent."""
    fake_client = _install_vision_fakes(
        monkeypatch,
        [_anthropic_body("YES, consistent")],
        get_replies=[_FakeImageResp(content=_FAKE_JPEG, content_type="image/jpeg")],
    )
    captured = {}
    orig_post = fake_client.post

    async def spy_post(url, headers=None, json=None, **kw):
        captured["json"] = json
        return await orig_post(url, headers=headers, json=json, **kw)

    monkeypatch.setattr(fake_client, "post", spy_post)
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/candidate.jpg",
        "CAM ships and MAC ships Archer class / Empire Mac-Ship conversions",
        **kwargs)
    content = captured["json"]["messages"][0]["content"]
    prompt_text = next(b["text"] for b in content if b.get("type") == "text")
    return result, prompt_text


@pytest.mark.asyncio
async def test_facts_reach_the_question(monkeypatch):
    result, prompt = await _ask_and_capture(monkeypatch, facts=_FACTS)
    assert result is True
    assert "Merchant Aircraft Carriers" in prompt
    assert "Conversions 1943-1944" in prompt
    # The conversion rule is the part that catches a right-name wrong-era
    # photo (battlecruiser-era Courageous, liner-era Pretoria Castle).
    assert "PRE-conversion" in prompt
    assert "counts as NO" in prompt


@pytest.mark.asyncio
async def test_source_filename_reaches_the_question(monkeypatch):
    result, prompt = await _ask_and_capture(
        monkeypatch, source_label="USS_Guadalcanal_(CVE-60)_underway.jpg")
    assert result is True
    assert "USS_Guadalcanal_(CVE-60)_underway.jpg" in prompt
    # The filename rule is what catches a sister-class/foreign lookalike
    # that pixels alone cannot split (HMS Glory as "Majestic class").
    assert "names a specific unit" in prompt
    assert "answer NO" in prompt


@pytest.mark.asyncio
async def test_no_facts_no_label_keeps_the_old_question(monkeypatch):
    """Every pre-existing caller passes neither parameter — their question
    must remain byte-identical in spirit: no facts block, no filename block."""
    result, prompt = await _ask_and_capture(monkeypatch)
    assert result is True
    assert "locked research roster" not in prompt
    assert "source filename/title" not in prompt
    # The core strict-variant question is unchanged.
    assert "THIS SPECIFIC designation/variant" in prompt


@pytest.mark.asyncio
async def test_prefetch_one_machine_threads_facts_and_filename(monkeypatch):
    """The sweep path actually passes the entry facts + candidate filename
    into the vision call — not just the signature existing."""
    seen = {}

    async def fake_gather(machine, aliases, query):
        return [("https://commons.example/HMS_Glory_SLV_Green_1946.jpg", False)]

    async def fake_host(cand, video_id, tenant_id, label):
        return "https://drive.example/hosted.jpg"

    async def fake_vision(tenant_id, hosted, machine, aliases=None,
                          trusted_source=False, facts=None, source_label=None):
        seen["facts"] = facts
        seen["source_label"] = source_label
        return False  # rejected — also exercises the miss-recording path

    async def fake_record(*args, **kwargs):
        seen["recorded_miss"] = True

    monkeypatch.setattr(static_docu, "_gather_reference_candidates", fake_gather)
    monkeypatch.setattr(static_docu, "_host_reference", fake_host)
    monkeypatch.setattr(static_docu, "_vision_confirms", fake_vision)
    monkeypatch.setattr(static_docu, "_record_reference_miss", fake_record)

    ok = await static_docu._prefetch_one_machine(
        "tenant-1", "video-1", "Improved Light Fleet Carriers Majestic class",
        3, aliases=["Majestic class"], facts={"years": "1945-1961"})

    assert ok is False
    assert seen["facts"] == {"years": "1945-1961"}
    assert seen["source_label"] == "HMS_Glory_SLV_Green_1946.jpg"
    assert seen.get("recorded_miss") is True


def test_roster_entries_carry_facts():
    """pipeline_executor's entry accessor exposes the structured entry's
    role/years/status/built_count as `facts` (additive key)."""
    from pathlib import Path
    sys.path.insert(0, str(Path(_BACKEND).resolve().parent / "skills" / "video-pipeline"))
    import pipeline_executor as pe

    roster = [
        {"name": "Archer class / Empire Mac-Ship conversions",
         "designation": "CAM ships and MAC ships",
         "role": "Merchant Aircraft Carriers",
         "years": "Conversions 1943-1944",
         "status": "converted",
         "built_count": "25 converted"},
        {"name": "Courageous class", "designation": "Courageous, Glorious"},
        {"name": "Unicorn", "designation": "HMS Unicorn (I72)"},
    ]
    video = {
        "render_mode": "static_docu",
        "research_payload": {
            "documentary_style": "designed_vs_used",
            "unit_roster": roster,
            "unit_roster_validation": {"passed": True},
        },
    }
    entries = pe._machine_documentary_hold_roster_entries(video)
    assert len(entries) == 3
    first = entries[0]
    assert first["facts"] == {
        "role": "Merchant Aircraft Carriers",
        "years": "Conversions 1943-1944",
        "status": "converted",
        "built_count": "25 converted",
    }
    # An entry with none of the fact keys gets an empty dict, not a KeyError.
    assert entries[1]["facts"] == {}
