"""Deterministic image subjects for approved factual machine scripts.

The factual script contract already binds each script scene to the locked
roster position.  Image planning can therefore reuse that identity directly;
it must not ask another model to infer a machine or manufacture title-card
facts from narration prose.
"""

from collections.abc import Mapping, Sequence
from typing import Any


class FactualImageSubjectError(ValueError):
    """Raised when saved factual scenes cannot be mapped to the locked roster."""


def factual_scene_subjects(
    video: dict,
    scripts: Sequence[Mapping[str, Any]],
) -> tuple[dict[int, dict], list[int]]:
    """Map factual script scenes to their exact locked-roster identities.

    The return shape matches ``static_docu._scene_subjects`` so the factual
    path can substitute this helper without changing legacy subject planning.
    ``scripts`` may be a scene subset, but every supplied scene must retain its
    one-based roster position and a nonempty saved paragraph.
    """
    from pipeline_executor import _machine_documentary_hold_roster_entries

    roster_entries = _machine_documentary_hold_roster_entries(video)
    if not roster_entries:
        raise FactualImageSubjectError(
            "Factual image subjects require a valid locked machine roster."
        )
    if not scripts:
        raise FactualImageSubjectError(
            "Factual image subjects require at least one saved script paragraph."
        )

    subjects: dict[int, dict] = {}
    for script in scripts:
        raw_scene = script.get("scene") if isinstance(script, Mapping) else None
        if isinstance(raw_scene, bool):
            raise FactualImageSubjectError(
                f"Factual script has invalid positional index {raw_scene!r}."
            )
        try:
            scene = int(raw_scene)
        except (TypeError, ValueError) as exc:
            raise FactualImageSubjectError(
                f"Factual script has invalid positional index {raw_scene!r}."
            ) from exc
        if scene < 1:
            raise FactualImageSubjectError(
                f"Factual script has invalid positional index {raw_scene!r}."
            )
        if scene > len(roster_entries):
            raise FactualImageSubjectError(
                f"Factual script scene {scene} is outside locked roster "
                f"positions 1-{len(roster_entries)}."
            )
        if scene in subjects:
            raise FactualImageSubjectError(
                f"Factual scripts contain duplicate scene index {scene}."
            )
        if not str(script.get("scene_text") or "").strip():
            raise FactualImageSubjectError(
                f"Factual script scene {scene} paragraph is empty."
            )

        entry = roster_entries[scene - 1]
        machine = str(entry.get("name") or "").strip()
        if not machine:
            raise FactualImageSubjectError(
                f"Factual script scene {scene} locked roster identity is empty."
            )
        aliases = [
            str(alias).strip()
            for alias in (entry.get("aliases") or [])
            if str(alias).strip()
        ]
        facts = entry.get("facts") if isinstance(entry.get("facts"), Mapping) else {}
        role = str(facts.get("role") or "").strip()
        search_query = f"{machine} {role}".strip()[:240].rstrip()
        subjects[scene] = {
            "machine": machine,
            "aliases": aliases,
            "caption_title": machine,
            "caption_sub": "",
            "caption_specs": [],
            "detail_focus": "",
            "search_query": search_query,
        }

    return subjects, []


__all__ = ["FactualImageSubjectError", "factual_scene_subjects"]
