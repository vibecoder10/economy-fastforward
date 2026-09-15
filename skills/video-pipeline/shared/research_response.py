"""Private, scoped checkpoints for resumable research-model responses."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional


def request_fingerprint(
    *, prompt: str, system_prompt: str, model: str, tools: Any,
    max_tokens: int, temperature: float,
) -> str:
    """Hash every input that can change a provider response, without retaining secrets."""
    material = json.dumps(
        {"prompt": prompt, "system": system_prompt, "model": model, "tools": tools,
         "max_tokens": max_tokens, "temperature": temperature},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def checkpoint_path(scope: Optional[dict], fingerprint: str) -> Optional[Path]:
    """Return a private tenant/video/request checkpoint path, or None without scope."""
    if not scope or not scope.get("tenant_id") or not scope.get("video_id"):
        return None
    root = Path(os.getenv(
        "STORYENGINE_RESEARCH_RESPONSE_DIR",
        Path(__file__).resolve().parents[3] / "storyengine" / "data" / "research-responses",
    ))
    scope_hash = hashlib.sha256(
        f"{scope['tenant_id']}\0{scope['video_id']}\0{fingerprint}".encode("utf-8")
    ).hexdigest()
    return root / f"{scope_hash}.json"


def load(path: Optional[Path], fingerprint: str) -> list[dict]:
    if not path or not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Research response checkpoint is unreadable; saved work was not resumed") from exc
    if not isinstance(payload, dict) or payload.get("fingerprint") != fingerprint or not isinstance(payload.get("responses"), list):
        raise RuntimeError("Research response checkpoint does not match this request; saved work was not resumed")
    for item in payload["responses"]:
        if not isinstance(item, dict) or not isinstance(item.get("stop_reason"), str) \
                or not isinstance(item.get("content"), list) or not isinstance(item.get("text"), str):
            raise RuntimeError("Research response checkpoint is invalid; saved work was not resumed")
    return payload["responses"]


def save(path: Optional[Path], fingerprint: str, responses: list[dict]) -> None:
    """Write mode-0600 JSON atomically under a mode-0700 directory."""
    if not path:
        return
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"fingerprint": fingerprint, "responses": responses}, handle, separators=(",", ":"))
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
