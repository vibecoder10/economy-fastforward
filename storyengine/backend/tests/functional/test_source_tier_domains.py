"""_source_tier_for_url must recognize non-US official and naval sources.

WHY THIS EXISTS (2026-07-30): the tier map's Tier-1 rule was
endswith(".gov")/".mil") plus a US-companies whitelist, and the Tier-2 list
was US/UK aviation museums. Every Commonwealth institution fell through:
awm.gov.au ends ".gov.au" (not ".gov"), royalnavy.mod.uk ends ".mod.uk",
and Royal Museums Greenwich (rmg.co.uk) has no "museum" substring for the
fallback heuristic. So a Royal Navy documentary's most authoritative
sources were graded Tier 3 - and the source-package quality gate then
rejected honest packages for "no Tier 1-2 authoritative source" (live case:
the HMS Hermes package, whose best source was the Australian War Memorial).

Found live by the research simulator's Hermes gather.

No network. Pure function.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_source_tier_domains.py -q
"""
import os
import sys
from pathlib import Path

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PIPELINE_ROOT = _REPO_ROOT / "skills" / "video-pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

import pipeline_executor as pe  # noqa: E402


def _tier(url, title=""):
    return pe._source_tier_for_url(url, title)["tier"]


def test_australian_war_memorial_is_tier_1():
    assert _tier("https://www.awm.gov.au/collection/C172467") == 1


def test_uk_ministry_of_defence_estate_is_tier_1():
    assert _tier("https://www.royalnavy.mod.uk/news") == 1


def test_uk_national_archives_is_tier_1():
    assert _tier("https://www.nationalarchives.gov.uk/records") == 1


def test_nz_government_history_is_tier_1():
    assert _tier("https://nzhistory.govt.nz/war") == 1


def test_sri_lanka_navy_is_tier_1():
    assert _tier("https://shipwrecks.navy.lk/hermes") == 1


def test_royal_museums_greenwich_is_tier_2():
    assert _tier("https://www.rmg.co.uk/collections") == 2


def test_national_museum_royal_navy_is_tier_2():
    assert _tier("https://www.nmrn.org.uk/exhibit") == 2


def test_us_hosts_unchanged():
    assert _tier("https://www.af.mil/news") == 1
    assert _tier("https://www.iwm.org.uk/collections/item/object/1") == 2
    assert _tier("https://www.naval-history.net/page.htm") == 3


def test_caution_hosts_unchanged():
    assert _tier("https://en.wikipedia.org/wiki/HMS_Hermes") == 4
    assert _tier("https://www.reddit.com/r/warships") == 4


def test_gov_substring_in_plain_domain_is_not_tier_1():
    # "gov" appearing inside an ordinary word must not promote the host.
    assert _tier("https://www.governorshipmodels.com/kits") == 3
