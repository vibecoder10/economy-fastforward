import copy

import reference_selection as rs


def _candidate(text, cid="c1"):
    return {
        "id": cid,
        "image_url": f"https://images.example/{cid}.jpg",
        "source_page": f"https://source.example/{cid}",
        "evidence": [{"url": f"https://source.example/{cid}", "kind": "image_caption", "text": text}],
    }


def _identity(quote, status="confirmed", cid="c1"):
    return {"status": status, "reason": "Source caption identifies the vessel.",
            "evidence": [{"url": f"https://source.example/{cid}", "quote": quote}]}


def _judgment(cid, quote, score=4):
    return {"id": cid, "identity": _identity(quote, cid=cid), "usable": True,
            "scores": dict.fromkeys(rs.WEIGHTS, score), "view": "side",
            "reason": "Clear hull profile.", "limitations": []}


def test_actual_plunger_pronoun_only_receipt_is_not_ready():
    # Minimal saved shape from the live Plunger receipt: the cited Commons
    # image-caption speaks only of Nimitz serving "on her".
    caption = ("Fleet Admiral Chester W. Nimitz, USN, served on her in January 1909, "
               "and became her CO on 3 May 1909 as well as Commander First Sub Flotilla "
               "until 21 January 1910. He has sign this photo.")
    source = "https://commons.wikimedia.org/wiki/File:USS_PLUNGER_(SS-2)_NH_58109.jpeg"
    image = "https://thumb.wikimedia.org/wikipedia/commons/USS_PLUNGER_(SS-2)_NH_58109.jpeg"
    hosted = "https://drive.google.com/uc?id=plunger-receipt"
    selected = {"image_url": image, "hosted_url": hosted, "caption": caption, "score": 75,
                "identity": {"status": "confirmed", "reason": "Filename and pixels say Plunger.",
                             "evidence": [{"url": source, "quote": caption}]},
                "evidence": [{"url": source, "kind": "image_caption", "text": caption}]}
    row = {"reference_kind": "photo", "source_url": image, "hosted_url": hosted,
           "selection_review": {"version": rs.VERSION, "status": "selected",
                                "machine": "SS-2 USS Plunger", "compared_count": 8,
                                "selected": selected}}
    assert "Plunger" not in caption
    assert not rs.selection_ready(row)
    repaired = copy.deepcopy(row)
    direct = "USS Plunger (SS-2) under way."
    repaired_selected = repaired["selection_review"]["selected"]
    repaired_selected["caption"] = direct
    repaired_selected["identity"]["evidence"][0]["quote"] = direct
    repaired_selected["evidence"][0]["text"] = direct
    assert rs.selection_ready(repaired)


def test_named_or_hull_caption_identifies_single_uss_submarine():
    machine = "SS-2 USS Plunger"
    for text in ("Plunger is under way.", "USS Plunger is under way.", "USSPlunger is under way.",
                 "Plunger (SS2) is under way."):
        candidate = _candidate(text)
        assert rs._valid_citations(candidate, _identity(text), machine)


def test_conflicting_hulls_reject_same_name_but_target_hull_can_coexist():
    tang = "SS-563 USS Tang"
    wrong_tang = "USS Tang (SS-306) under way."
    assert not rs._valid_citations(_candidate(wrong_tang), _identity(wrong_tang), tang)
    seawolf = "SSN-21 USS Seawolf"
    wrong_seawolf = "USS Seawolf (SSN-575) under way."
    assert not rs._valid_citations(_candidate(wrong_seawolf), _identity(wrong_seawolf), seawolf)
    partial_seawolf = "USS Seawolf (SSN-212) under way."
    assert not rs._valid_citations(_candidate(partial_seawolf), _identity(partial_seawolf), seawolf)
    conversion = "USS Albacore (AGSS569), with USS Other (SS-306), under way."
    assert rs._valid_citations(_candidate(conversion), _identity(conversion), "SS-569 USS Albacore")


def test_complete_name_required_not_partial_or_generic():
    machine = "SSBN-598 USS George Washington"
    partial = "George is under way."
    assert not rs._valid_citations(_candidate(partial), _identity(partial), machine)
    full = "George Washington is under way."
    assert rs._valid_citations(_candidate(full), _identity(full), machine)
    generic = "The submarine is under way."
    assert not rs._valid_citations(_candidate(generic), _identity(generic), "SS-2 USS Plunger")


def test_class_and_aircraft_citations_keep_existing_behavior():
    text = "USS Exact is a member of Example class."
    assert rs._valid_citations(_candidate(text), _identity(text), "Example class")
    assert rs._valid_citations(_candidate(text), _identity(text), "B-52 Stratofortress")


def test_invalid_saved_selected_reranks_to_lower_score_valid_alternate():
    bad_text = "Fleet Admiral Nimitz served on her during 1909."
    good_text = "USS Plunger (SS-2) under way."
    bad = _candidate(bad_text, "bad")
    bad["hosted_url"] = "https://assets.example/bad.jpg"
    bad["identity"] = _identity(bad_text, cid="bad")
    bad["score"] = 100
    good = _candidate(good_text, "good")
    good["identity"] = _identity(good_text, cid="good")
    good.update(_judgment("good", good_text, score=3))
    receipt = {"version": rs.VERSION, "status": "selected", "machine": "SS-2 USS Plunger",
               "compared_count": 2, "selected": bad,
               "candidates": [bad | _judgment("bad", bad_text, score=5), good]}
    reranked = rs._rerank_saved_review(copy.deepcopy(receipt))
    assert reranked is not None and reranked[1][2]["id"] == "good"
