import pytest

import pipeline_executor as pe


def test_factual_subjects_use_locked_scene_position_without_reading_prose(monkeypatch):
    from factual_image_subjects import factual_scene_subjects

    entries = [
        {"name": "HMS Argus", "aliases": ["I49", "Argus"], "facts": {"role": "aircraft carrier"}},
        {"name": "HMS Campania (D48)", "aliases": ["Campania"], "facts": {"role": "escort carrier"}},
        {"name": "Colossus class", "aliases": [], "facts": {}},
    ]
    monkeypatch.setattr(pe, "_machine_documentary_hold_roster_entries", lambda _video: entries)

    subjects, invalid = factual_scene_subjects(
        {"id": "video"},
        [{"scene": 2, "scene_text": "This paragraph deliberately names the wrong ship."}],
    )

    assert invalid == []
    assert subjects == {
        2: {
            "machine": "HMS Campania (D48)",
            "aliases": ["Campania"],
            "caption_title": "HMS Campania (D48)",
            "caption_sub": "",
            "caption_specs": [],
            "detail_focus": "",
            "search_query": "HMS Campania (D48) escort carrier",
        }
    }


@pytest.mark.parametrize(
    ("entries", "scripts", "message"),
    [
        ([], [{"scene": 1, "scene_text": "Paragraph"}], "locked machine roster"),
        ([{"name": "HMS Argus"}], [{"scene": 0, "scene_text": "Paragraph"}], "positional index"),
        ([{"name": "HMS Argus"}], [{"scene": 2, "scene_text": "Paragraph"}], "outside locked roster"),
        ([{"name": ""}], [{"scene": 1, "scene_text": "Paragraph"}], "identity is empty"),
        ([{"name": "HMS Argus"}], [{"scene": 1, "scene_text": "  "}], "paragraph is empty"),
    ],
)
def test_factual_subjects_fail_visibly_instead_of_guessing(monkeypatch, entries, scripts, message):
    from factual_image_subjects import FactualImageSubjectError, factual_scene_subjects

    monkeypatch.setattr(pe, "_machine_documentary_hold_roster_entries", lambda _video: entries)

    with pytest.raises(FactualImageSubjectError, match=message):
        factual_scene_subjects({"id": "video"}, scripts)


def test_factual_subjects_reject_duplicate_scene_positions(monkeypatch):
    from factual_image_subjects import FactualImageSubjectError, factual_scene_subjects

    monkeypatch.setattr(
        pe,
        "_machine_documentary_hold_roster_entries",
        lambda _video: [{"name": "HMS Argus"}],
    )

    with pytest.raises(FactualImageSubjectError, match="duplicate scene index 1"):
        factual_scene_subjects(
            {"id": "video"},
            [{"scene": 1, "scene_text": "First"}, {"scene": 1, "scene_text": "Second"}],
        )
