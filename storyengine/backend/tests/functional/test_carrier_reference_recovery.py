"""Bounded alternate photo search after an identity rejection, never QA bypass."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "skills/video-pipeline"))
import static_docu as sd


def _run(initial, alternatives, accepts):
    search = AsyncMock(side_effect=alternatives)
    vision = AsyncMock(side_effect=accepts)
    write = AsyncMock()
    misses = AsyncMock()
    with patch.object(sd, "_gather_reference_candidates", AsyncMock(return_value=initial)), \
         patch.object(sd, "find_commons_photos", search), \
         patch.object(sd, "_host_reference", AsyncMock(side_effect=lambda url, *_a: url)), \
         patch.object(sd, "_vision_confirms", vision), \
         patch.object(sd, "execute", write), \
         patch.object(sd, "_clear_reference_miss", AsyncMock()), \
         patch.object(sd, "_record_reference_miss", misses):
        result = asyncio.run(sd._prefetch_one_machine(
            "tenant", "video", "Queen Elizabeth class", 15,
            aliases=["Queen Elizabeth", "Prince of Wales"],
            facts={"role": "British aircraft carrier", "years": "2017 onwards"},
        ))
    return result, search, vision, write, misses


def test_rejection_tries_new_candidate_without_rejudging_duplicate():
    result, search, vision, write, misses = _run(
        [("battleship.jpg", True)],
        [[{"url": "battleship.jpg"}, {"url": "carrier.jpg"}]],
        [False, True],
    )
    assert result is True
    search.assert_awaited_once_with("Queen Elizabeth aircraft carrier")
    assert vision.await_count == 2
    assert vision.call_args.kwargs["trusted_source"] is False
    assert vision.call_args.kwargs["facts"]["years"] == "2017 onwards"
    assert write.await_count == 1
    misses.assert_not_awaited()


def test_all_candidates_rejected_stops_after_two_alternatives():
    result, search, vision, write, misses = _run(
        [("wrong1.jpg", True)],
        [[{"url": "wrong2.jpg"}], [{"url": "wrong3.jpg"}]],
        [False, False, False],
    )
    assert result is False
    assert search.await_count == 2
    assert vision.await_count == 3
    write.assert_not_awaited()
    assert misses.call_args.args[-1] == sd.REASON_VISION_REJECTED


def test_valid_first_photo_does_not_search_or_spend_again():
    result, search, vision, write, _misses = _run([("carrier.jpg", True)], [], [True])
    assert result is True
    search.assert_not_awaited()
    assert vision.await_count == 1
    assert write.await_count == 1
