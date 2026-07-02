"""Functional tests for render_perform's pure timeline math.

No network, no DB, no ffmpeg: database + storage are stubbed (the module-stub
pattern from tasks/lessons.md) and only the pure functions are exercised.
Proves the performance-track contract — segments lay end to end with the
dialogue head-pad mirroring the clip mux lead, speaking shots claim exactly
their lines (masters before angles, merged turns span), narration blocks split
by word count, and the final strip is gapless and exactly as long as the track.

Run: python3 tests/functional/test_render_perform.py  (from backend dir)
"""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ── Stub database + storage BEFORE importing the module under test ──
for name in ("database", "storage"):
    mod = types.ModuleType(name)
    if name == "database":
        async def _nope(*a, **k):
            raise AssertionError("pure tests must not touch the DB")
        mod.fetch_all = _nope
        mod.fetch_one = _nope
        mod.execute = _nope
    else:
        async def _noup(*a, **k):
            raise AssertionError("pure tests must not upload")
        mod.upload_bytes = _noup
        mod.download_bytes = _noup
    sys.modules[name] = mod

from render_perform import (  # noqa: E402
    DIALOGUE_HEAD_SECONDS,
    DIALOGUE_TAIL_SECONDS,
    build_segment_spans,
    build_timeline,
    match_speaking_shots,
)


def _nar(text, dur, url="u"):
    return {"type": "narration", "text": text, "audio_url": url, "duration": dur}


def _dlg(speaker, text, dur, url="u"):
    return {"type": "dialogue", "speaker": speaker, "text": text,
            "audio_url": url, "duration": dur}


def _shot(idx, sentence="", assigned=None, hero=False):
    return {"id": f"a{idx}", "image_index": idx, "sentence_text": sentence,
            "assigned_dialogue": assigned, "hero_shot": hero,
            "video_clip_url": f"clip{idx}", "video_duration": 6}


def _covers(entries, total):
    """The strip must start at 0, end at total, and be gapless + monotonic."""
    assert entries, "empty strip"
    assert entries[0]["start"] == 0.0
    assert abs(entries[-1]["end"] - total) < 0.01, (entries[-1]["end"], total)
    for a, b in zip(entries, entries[1:]):
        assert abs(a["end"] - b["start"]) < 0.001, (a["end"], b["start"])
        assert a["end"] > a["start"]


def test_segment_spans_pads_dialogue():
    spans = build_segment_spans([_nar("Marco was late.", 4.0),
                                 _dlg("Marco", "¡Lo siento!", 2.0),
                                 _nar("He said sorry.", 3.0)])
    assert spans[0]["start"] == 0.0 and spans[0]["end"] == 4.0
    assert spans[0]["audio_at"] == 0.0
    # dialogue gets the mux-mirroring head pad + a tail beat
    assert spans[1]["start"] == 4.0
    assert spans[1]["audio_at"] == 4.0 + DIALOGUE_HEAD_SECONDS
    assert abs(spans[1]["end"] - (4.0 + DIALOGUE_HEAD_SECONDS + 2.0
                                  + DIALOGUE_TAIL_SECONDS)) < 0.001
    # the narrator resumes where the padded line ends
    assert spans[2]["start"] == spans[1]["end"]
    assert spans[2]["audio_at"] == spans[2]["start"]


def test_segment_spans_skips_unvoiced():
    spans = build_segment_spans([_nar("Voiced.", 2.0),
                                 {"type": "narration", "text": "", "audio_url": None},
                                 _nar("Also voiced.", 2.0)])
    assert spans[1]["start"] == spans[1]["end"] == 2.0
    assert spans[2]["start"] == 2.0


def test_assigned_dialogue_claims_master_not_angle():
    segs = [_nar("Intro.", 3.0), _dlg("Marco", "¡Lo siento, Sofia!", 2.0),
            _nar("Outro.", 3.0)]
    spans = build_segment_spans(segs)
    shots = [
        _shot(101, "Marco apologizes in the doorway"),                       # angle
        _shot(102, "Marco apologizes in the doorway",
              assigned='Marco: "¡Lo siento, Sofia!"', hero=True),            # master
        _shot(103, "Sofia rolls her eyes"),
    ]
    claims = match_speaking_shots(shots, spans)
    assert claims == {1: [1]}, claims  # only the master claims the line


def test_fallback_matching_without_assigned():
    segs = [_nar("Intro.", 3.0), _dlg("Sofia", "Siempre llegas tarde.", 2.0)]
    spans = build_segment_spans(segs)
    shots = [_shot(1, 'Sofia frowns: "Siempre llegas tarde."'), _shot(2, "A clock ticks")]
    claims = match_speaking_shots(shots, spans)
    assert claims == {0: [1]}, claims


def test_merged_turns_one_master_claims_both():
    segs = [_dlg("Marco", "¡Lo siento!", 2.0), _nar("Sofia waited.", 3.0),
            _dlg("Marco", "El reloj está roto.", 2.0)]
    spans = build_segment_spans(segs)
    shots = [_shot(1, "Marco explains",
                   assigned='Marco: "¡Lo siento! El reloj está roto."', hero=True)]
    claims = match_speaking_shots(shots, spans)
    assert claims == {0: [0, 2]}, claims
    tl = build_timeline(segs, shots)
    # the merged window spans across the narration between the two turns
    assert len(tl["entries"]) == 1
    _covers(tl["entries"], tl["total"])


def test_timeline_speaking_windows_and_wordcount_blocks():
    segs = [_nar("One two three four five six.", 6.0),        # 0
            _dlg("Marco", "¡Lo siento, Sofia!", 2.0),         # 1
            _nar("Seven eight nine.", 3.0)]                   # 2
    spans = build_segment_spans(segs)
    shots = [_shot(1, "one two three four"),                  # 4 words
             _shot(2, "five six"),                            # 2 words
             _shot(3, "Marco speaks", assigned='Marco: "¡Lo siento, Sofia!"', hero=True),
             _shot(4, "closing shot")]
    tl = build_timeline(segs, shots)
    assert tl["total"] == spans[-1]["end"]
    assert not tl["warnings"], tl["warnings"]
    entries = tl["entries"]
    assert [e["speaking"] for e in entries] == [False, False, True, False]
    _covers(entries, tl["total"])
    # block 1 (0..6s) splits 4:2 by word count
    assert abs(entries[0]["end"] - 4.0) < 0.01, entries[0]
    assert abs(entries[1]["end"] - 6.0) < 0.01, entries[1]
    # the speaking window is exactly the padded line span
    assert abs(entries[2]["start"] - spans[1]["start"]) < 0.001
    assert abs(entries[2]["end"] - spans[1]["end"]) < 0.001
    # audio placements carry every voiced segment at its offset
    assert len(tl["placements"]) == 3
    assert tl["placements"][1][1] == spans[1]["audio_at"]


def test_unclaimed_line_plays_over_narration():
    segs = [_nar("Intro words here.", 3.0), _dlg("Sofia", "No clip for this.", 2.0),
            _nar("Outro words.", 3.0)]
    shots = [_shot(1, "some narration shot"), _shot(2, "another shot")]
    tl = build_timeline(segs, shots)
    assert any("no speaking clip" in w for w in tl["warnings"]), tl["warnings"]
    _covers(tl["entries"], tl["total"])
    assert all(not e["speaking"] for e in tl["entries"])


def test_crowded_block_drops_shots():
    segs = [_nar("Two words.", 1.0)]
    shots = [_shot(i, f"shot {i}") for i in range(1, 6)]  # 5 shots into 1s
    tl = build_timeline(segs, shots)
    assert any("can't fit" in w for w in tl["warnings"]), tl["warnings"]
    assert len(tl["entries"]) == 1
    _covers(tl["entries"], tl["total"])


def test_gap_with_no_shots_stretches_neighbor():
    # narration → line → narration, but the only clip is the speaking master:
    # its window must stretch to cover the whole scene.
    segs = [_nar("Setup.", 3.0), _dlg("Marco", "¡Hola!", 2.0), _nar("Wrap.", 3.0)]
    shots = [_shot(1, "Marco speaks", assigned='Marco: "¡Hola!"', hero=True)]
    tl = build_timeline(segs, shots)
    assert len(tl["entries"]) == 1
    _covers(tl["entries"], tl["total"])


def test_no_voiced_segments_is_actionable():
    tl = build_timeline([{"type": "narration", "text": "x"}], [_shot(1, "s")])
    assert tl["entries"] == []
    assert any("voiceover" in w for w in tl["warnings"])


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} render_perform timeline tests passed")
