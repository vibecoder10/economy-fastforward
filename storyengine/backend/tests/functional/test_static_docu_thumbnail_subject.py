"""Focused regression tests for static-documentary thumbnail packaging."""

import json
import os
import sys


_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

from pipeline_executor import (  # noqa: E402
    _select_static_thumbnail_subject,
    _usable_thumbnail_copy,
)


def _asset(scene, title, sub, url, *, specs=None, role="three_quarter", status="done"):
    return {
        "scene": scene,
        "image_index": 1,
        "image_url": url,
        "status": status,
        "generation_method": "static_docu",
        "caption": json.dumps({
            "title": title,
            "sub": sub,
            "specs": specs or [],
            "view_role": role,
        }),
    }


def test_selects_strongest_locked_roster_subject_and_approved_view():
    roster = [
        {"designation": "CV-1", "name": "USS Langley"},
        {"designation": "CVA-62", "name": "USS Independence"},
        {"designation": "CVN-78", "name": "USS Gerald R. Ford"},
    ]
    rows = [
        _asset(1, "CV-1 USS Langley", "Converted • 1 ship • 1922", "https://img/langley.png"),
        _asset(
            18,
            "CVA-62 USS Independence",
            "US Navy • 1959–1998",
            "https://img/independence.png",
            specs=["Scrapping completed at Brownsville in 2018"],
        ),
        _asset(
            24,
            "CVN-78 USS Gerald R. Ford",
            "Production • 1 ship commissioned • 2017",
            "https://img/ford-side.png",
            role="side_profile",
        ),
        _asset(
            24,
            "CVN-78 USS Gerald R. Ford",
            "Production • 1 ship commissioned • 2017",
            "https://img/ford-three-quarter.png",
            role="three_quarter",
        ),
        _asset(
            24,
            "CVN-78 USS Gerald R. Ford",
            "Production • 1 ship commissioned • 2017",
            "https://img/rejected.png",
            status="qa_rejected",
        ),
        _asset(25, "CVA-58 United States", "Never-built design", "https://img/unlocked.png"),
    ]

    chosen = _select_static_thumbnail_subject(rows, roster)

    assert chosen["title"] == "CVN-78 USS Gerald R. Ford"
    assert chosen["image_url"] == "https://img/ford-three-quarter.png"


def test_every_built_series_gets_grammatical_title_condensation():
    title = "Every US Aircraft Carrier Ever Built (2026)"

    expected = "US AIRCRAFT CARRIER EVER BUILT"
    assert _usable_thumbnail_copy(title, "EVERY BUILT") == expected
    assert _usable_thumbnail_copy(title, "EVER BUILT") == expected
    assert _usable_thumbnail_copy(title, title) == expected
    assert _usable_thumbnail_copy(title, "NAVAL GIANTS") == expected


def test_non_series_copy_stays_title_related_instead_of_generic_slogan():
    title = "How the Iowa Class Changed Naval Gunnery"

    assert _usable_thumbnail_copy(
        title, "NAVAL GIANTS"
    ) == "NAVAL GIANTS"
    assert _usable_thumbnail_copy(title, "THE ONE TO BEAT") == "IOWA CLASS NAVAL GUNNERY"
