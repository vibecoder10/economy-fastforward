"""Shared helpers for roster reference-photo tests (no DB, no network).

The roster reference layer only treats a saved photo as "verified" when its
cache row carries a valid source-grounded selection receipt
(reference_selection.selection_ready). Tests that need a genuinely verified
cache row build it here instead of hand-writing a bare hosted_url dict.
"""


def ready_cache_row(hosted="https://storage.example/ready.jpg",
                    source="https://source.example/ready.jpg"):
    """A static_reference_cache row that passes reference_selection.selection_ready."""
    import reference_selection as rs
    caption = "USS Exact is a member of Example class."
    page = "https://archive.example/exact"
    selected = {
        "id": "a", "image_url": source, "source_page": page, "caption": caption,
        "evidence": [{"url": page, "text": caption, "kind": "image_caption"}],
        "identity": {"status": "confirmed", "reason": "Caption identifies the exact subject.",
                     "evidence": [{"url": page, "quote": caption}]},
        "usable": True, "scores": dict.fromkeys(rs.WEIGHTS, 4), "view": "side",
        "reason": "Complete hull is visible.", "limitations": [],
        "hosted_url": hosted, "score": 80,
    }
    receipt = {"version": rs.VERSION, "status": "selected", "compared_count": 2, "selected": selected}
    return {"reference_kind": "photo", "hosted_url": hosted, "source_url": source,
            "selection_review": receipt}

