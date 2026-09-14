"""Saved image approvals belong to exact pixels and configuration evidence."""
import hashlib
import json
import re

IMAGE_REVIEW_VERSION = 1


def factual_image_review_required(video):
    payload = video.get("research_payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            return False
    return (video.get("render_mode") == "static_docu" and isinstance(payload, dict)
            and payload.get("machine_script_contract") == "factual_100_v1")



def machine_geometry_requirement(machine):
    # USAF One Hundred Years of Flight (22 August 1923) and the cached
    # XNBL-1 in-flight photograph: the Barling was a six-engine triplane.
    # https://media.defense.gov/2025/Jun/16/2003738822/-1/-1/0/ONE%20HUNDRED%20YEARS%20FLIGHT.PDF
    if re.search(r"\bXNBL[ -]?1\b|\bBarling Bomber\b", str(machine or ""), re.I):
        return (
            "XNBL-1 Barling geometry: preserve three vertically stacked main-wing planes "
            "(upper, middle, lower), including the shorter middle wing visible in the "
            "historical reference. It is a TRIPLANE, never a two-wing biplane. Count "
            "the main wings separately from the tailplanes and reject a missing or merged "
            "wing level. Preserve the six-engine arrangement: four tractor and two pusher "
            "engines. Do not simplify the aircraft into a generic biplane. "
        )
    return ""


def image_review_stamp(machine, reference_url, facts, image_url):
    inputs = [machine, reference_url, facts or {}]
    requirement = machine_geometry_requirement(machine)
    if requirement:
        inputs.append(requirement)
    context = json.dumps(inputs, sort_keys=True, default=str)
    return {"image_review_version": IMAGE_REVIEW_VERSION,
            "image_review_context": hashlib.sha256(context.encode()).hexdigest(),
            "image_review_url": image_url}


def image_review_current(caption, image_url, expected=None):
    if isinstance(caption, str):
        try:
            caption = json.loads(caption)
        except (TypeError, ValueError):
            return False
    if not isinstance(caption, dict) or not image_url:
        return False
    if not (caption.get("image_review_version") == IMAGE_REVIEW_VERSION
            and caption.get("image_review_url") == image_url
            and caption.get("image_review_context")):
        return False
    return expected is None or all(caption.get(k) == v for k, v in expected.items())
