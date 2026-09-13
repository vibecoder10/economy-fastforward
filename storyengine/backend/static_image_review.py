"""Saved image approvals belong to exact pixels and configuration evidence."""
import hashlib
import json

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


def image_review_stamp(machine, reference_url, facts, image_url):
    context = json.dumps([machine, reference_url, facts or {}], sort_keys=True, default=str)
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
