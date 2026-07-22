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


def test_scene_opening_on_a_line_gets_a_leadin():
    """A scene whose first voiced segment is dialogue would give a planned
    establishing shot zero clock — the lead-in gives it a beat instead of
    dropping a paid frame."""
    from render_perform import SCENE_LEADIN_SECONDS
    segs = [_dlg("Marco", "¡Espera!", 1.5), _nar("Marco runs to school.", 5.0)]
    shots = [_shot(1, "Silent establishing — the school street"),
             _shot(2, "Marco shouts", assigned='Marco: "¡Espera!"', hero=True),
             _shot(3, "the street empties")]
    tl = build_timeline(segs, shots)
    assert not any("dropped" in w for w in tl["warnings"]), tl["warnings"]
    entries = tl["entries"]
    assert [e["speaking"] for e in entries] == [False, True, False]
    assert abs(entries[0]["end"] - SCENE_LEADIN_SECONDS) < 0.01, entries[0]
    # audio placements shifted with the spans — first line starts after the lead
    assert tl["placements"][0][1] >= SCENE_LEADIN_SECONDS
    _covers(entries, tl["total"])
    # no leading silent shot → no lead-in
    tl2 = build_timeline(segs, shots[1:])
    assert tl2["entries"][0]["start"] == 0.0 and tl2["entries"][0]["speaking"]
    assert tl2["placements"][0][1] < SCENE_LEADIN_SECONDS


def test_narration_cuts_align_to_content():
    """Shots in a narration block snap to the segments they were planned for
    (order-preserving content match), not word-count drift — the live failure
    was the clock close-up playing under the vocab recap."""
    segs = [_dlg("Marco", "¡Hola!", 2.0),
            _nar("Marco looks at the clock on the wall. It has been fixed.", 8.0),
            _nar("He laughs for the first time in weeks, laughing freely.", 3.0),
            _nar("Five words you learned: tarde, correr, amigos, reloj, roto.", 18.0)]
    shots = [_shot(1, "Marco speaks", assigned='Marco: "¡Hola!"', hero=True),
             _shot(2, "INSERT — the fixed clock reveals the real time"),
             _shot(3, "Marco laughs freely; he was never late at all"),
             _shot(4, "Floating word cards: tarde correr amigos reloj roto")]
    tl = build_timeline(segs, shots)
    ent = {e["shot"]["image_index"]: e for e in tl["entries"]}
    spans = build_segment_spans(segs)
    # clock shot covers the clock segment, laugh shot the laugh segment,
    # cards shot the vocab segment — cuts on the segment boundaries.
    assert abs(ent[2]["end"] - spans[1]["end"]) < 0.01, (ent[2], spans[1])
    assert abs(ent[3]["end"] - spans[2]["end"]) < 0.01, (ent[3], spans[2])
    assert abs(ent[4]["end"] - tl["total"]) < 0.01
    _covers(tl["entries"], tl["total"])


def test_no_voiced_segments_is_actionable():
    tl = build_timeline([{"type": "narration", "text": "x"}], [_shot(1, "s")])
    assert tl["entries"] == []
    assert any("voiceover" in w for w in tl["warnings"])


def test_carrier_shot_window_follows_clip_speech_not_tts_mp3():
    """STS voice-lock (migration 114): a speaking shot whose clip CARRIES its
    line must be timed by the clip's measured speech bounds — head = where the
    take starts talking, duration = the take's speech length — and its TTS mp3
    must be dropped from the scene-track placements (the clip's own audio
    plays instead). Grok's pace, not the unused mp3's."""
    segs = [_nar("One two three four five six.", 6.0),        # 0
            _dlg("Marco", "¡Lo siento, Sofia!", 2.0),         # 1 (TTS says 2.0s)
            _nar("Seven eight nine.", 3.0)]                   # 2
    shot = _shot(3, "Marco speaks", assigned='Marco: "¡Lo siento, Sofia!"', hero=True)
    shot["carries_own_line"] = True
    shot["clip_speech_start"] = 1.2   # Grok starts talking 1.2s into the take
    shot["clip_speech_end"] = 4.2     # and speaks for 3.0s (vs the 2.0s mp3)
    shots = [_shot(1, "one two three four"), _shot(2, "five six"),
             shot, _shot(4, "closing shot")]
    tl = build_timeline(segs, shots)

    entry = next(e for e in tl["entries"] if e["speaking"])
    assert entry.get("carries") is True
    # window = clip head (1.2) + speech (3.0) + tail — NOT 0.5 + 2.0 + tail
    expected = 1.2 + 3.0 + DIALOGUE_TAIL_SECONDS
    assert abs((entry["end"] - entry["start"]) - expected) < 0.01, entry
    # the claimed line's mp3 is NOT on the scene track (2 narrator segs only)
    assert len(tl["placements"]) == 2
    # non-carrier runs stay byte-identical: same segments without the marker
    tl_plain = build_timeline(segs, [
        _shot(1, "one two three four"), _shot(2, "five six"),
        _shot(3, "Marco speaks", assigned='Marco: "¡Lo siento, Sofia!"', hero=True),
        _shot(4, "closing shot")])
    plain_entry = next(e for e in tl_plain["entries"] if e["speaking"])
    from render_perform import DIALOGUE_HEAD_SECONDS as _H
    assert abs((plain_entry["end"] - plain_entry["start"])
               - (_H + 2.0 + DIALOGUE_TAIL_SECONDS)) < 0.01
    assert len(tl_plain["placements"]) == 3


def test_multi_span_carrier_keeps_overlay_behavior():
    """Review finding #1: a merged master claiming spans with narration
    BETWEEN them plays one continuous take — the span math can't interleave
    the narration placement inside its window. Multi-span carriers must NOT
    get the override; everything stays on the TTS clock."""
    segs = [_dlg("Marco", "First line here totally.", 2.0),
            _nar("Narration between the turns.", 2.5),
            _dlg("Marco", "Second line here truly.", 2.0)]
    master = _shot(1, "Marco speaks", hero=True,
                   assigned='Marco: "First line here totally. Second line here truly."')
    master["carries_own_line"] = True
    master["clip_speech_start"] = 0.8
    master["clip_speech_end"] = 5.3
    tl = build_timeline(segs, [master, _shot(2, "closing")])
    entry = next(e for e in tl["entries"] if e["speaking"])
    assert not entry.get("carries"), "multi-span master must not carry"
    assert len(tl["placements"]) == 3, "all three mp3s must stay on the track"


def test_first_entry_carrier_moved_by_normalization_is_demoted():
    """Review finding #2: when the scene's first SHOT is a carrier but its
    window starts later on the clock (leading narration, no earlier shots),
    normalization pulls its start to 0.0 — the audio anchor no longer matches
    the window, so the carrier must demote to overlay and its TTS line must
    come back to the scene track."""
    segs = [_nar("Some opening narration first.", 3.0),
            _dlg("Marco", "¡Lo siento, Sofia!", 2.0),
            _nar("Closing narration.", 2.0)]
    shot = _shot(1, "Marco speaks", assigned='Marco: "¡Lo siento, Sofia!"', hero=True)
    shot["carries_own_line"] = True
    shot["clip_speech_start"] = 1.2
    shot["clip_speech_end"] = 4.2
    # ONLY the speaking shot — normalization must stretch it over the intro.
    tl = build_timeline(segs, [shot])
    entry = tl["entries"][0]
    assert entry["start"] == 0.0
    assert not entry.get("carries"), "moved carrier must be demoted"
    # the claimed line's mp3 must be RESTORED to the track (3 total again)
    assert len(tl["placements"]) == 3
    assert any("normalization" in w for w in tl["warnings"])


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} render_perform timeline tests passed")
