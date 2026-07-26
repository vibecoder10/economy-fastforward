"""Cross-language Remotion props for visually approved director shots."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

from custom_film_contract import CustomFilmContractError
from custom_film_director import build_remotion_admission
from custom_film_remotion import remotion_props_hash

DIRECTOR_REMOTION_PROPS_VERSION = "custom-film-director-remotion-v1"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _remotion_error(message: str) -> CustomFilmContractError:
    return CustomFilmContractError(
        f"{message}; no Remotion render or provider work was started"
    )


def _strict_mapping(
    value: Any,
    label: str,
    keys: frozenset[str],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _remotion_error(f"Custom Film director {label} is invalid")
    result = copy.deepcopy(dict(value))
    if set(result) != set(keys):
        raise _remotion_error(f"Custom Film director {label} fields changed")
    return result


def _hash(value: Any, label: str) -> str:
    digest = str(value or "")
    if not _HASH_RE.fullmatch(digest):
        raise _remotion_error(f"Custom Film director {label} is invalid")
    return digest


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _remotion_error(f"Custom Film director {label} is invalid")
    return value


def _frame(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise _remotion_error(f"Custom Film director {label} is invalid")
    return value


def _local_path(value: Any, label: str) -> str:
    path = _text(value, label)
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or path.startswith(("http:", "https:")):
        raise _remotion_error(f"Custom Film director {label} must be staged locally")
    return str(parsed)


def _source(value: Any, label: str) -> dict[str, Any]:
    source = _strict_mapping(
        value,
        label,
        frozenset({"source_key", "local_path", "source_sha256"}),
    )
    return {
        "source_key": _text(source["source_key"], f"{label} source key"),
        "local_path": _local_path(source["local_path"], f"{label} local path"),
        "source_sha256": _hash(source["source_sha256"], f"{label} source hash"),
    }


def _measured_words(
    value: Any,
    *,
    line_text: str,
    start_frame: int,
    end_frame: int,
) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _remotion_error("Custom Film director measured words are invalid")
    words: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        word = _strict_mapping(
            raw,
            f"measured word {index + 1}",
            frozenset({"text", "from_frame", "to_frame"}),
        )
        from_frame = _frame(word["from_frame"], "word start frame")
        to_frame = _frame(word["to_frame"], "word end frame", minimum=1)
        if (
            to_frame <= from_frame
            or from_frame < start_frame
            or to_frame > end_frame
            or (words and from_frame < words[-1]["to_frame"])
        ):
            raise _remotion_error("Custom Film director measured-word timing changed")
        words.append(
            {
                "text": _text(word["text"], "measured word text"),
                "from_frame": from_frame,
                "to_frame": to_frame,
            }
        )
    if (
        not words
        or words[0]["from_frame"] != start_frame
        or words[-1]["to_frame"] != end_frame
        or " ".join("".join(row["text"] for row in words).split())
        != " ".join(line_text.split())
    ):
        raise _remotion_error("Custom Film director measured caption changed")
    return words


def _transition_frames(kind: str, duration_frames: int) -> int:
    if kind in {"opening", "continuous"}:
        return 0
    return min(12, max(1, duration_frames // 4))


def build_director_remotion_props(
    director_contract: Mapping[str, Any],
    storyboard_gate: Mapping[str, Any],
    picture_gate: Mapping[str, Any],
    visual_gate: Mapping[str, Any],
    *,
    clip_sources: Mapping[str, Mapping[str, Any]],
    voice_sources: Mapping[str, Mapping[str, Any]],
    sound_sources: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Bind approved clip/audio bytes to exact shot timing and measured captions."""
    admission = build_remotion_admission(
        director_contract,
        storyboard_gate,
        picture_gate,
        visual_gate,
    )
    expected_clip_ids = {
        str(shot["clip_artifact_id"]) for shot in admission["shots"]
    }
    expected_voice_ids = {
        f"{shot['shot_id']}:{line_index}"
        for shot in admission["shots"]
        for line_index, _line in enumerate(shot["spoken_lines"])
    }
    expected_shot_ids = {str(shot["shot_id"]) for shot in admission["shots"]}
    if (
        set(clip_sources) != expected_clip_ids
        or set(voice_sources) != expected_voice_ids
        or set(sound_sources) != expected_shot_ids
    ):
        raise _remotion_error(
            "Custom Film director Remotion sources do not match the admission"
        )

    aspect_ratio = str(director_contract["film_bible"]["style"]["aspect_ratio"])
    dimensions = {
        "16:9": (1920, 1080),
        "9:16": (1080, 1920),
        "1:1": (1080, 1080),
        "4:5": (1080, 1350),
    }
    if aspect_ratio not in dimensions:
        raise _remotion_error("Custom Film director aspect ratio is unsupported")
    width, height = dimensions[aspect_ratio]
    shots: list[dict[str, Any]] = []
    for shot in admission["shots"]:
        shot_id = str(shot["shot_id"])
        start_frame = int(shot["start_frame"])
        end_frame = int(shot["end_frame"])
        spoken_lines: list[dict[str, Any]] = []
        for line_index, line in enumerate(shot["spoken_lines"]):
            voice_id = f"{shot_id}:{line_index}"
            raw_voice = _strict_mapping(
                voice_sources[voice_id],
                f"voice source {voice_id}",
                frozenset(
                    {
                        "source_key",
                        "local_path",
                        "source_sha256",
                        "start_frame",
                        "end_frame",
                        "measured_words",
                    }
                ),
            )
            line_start = _frame(raw_voice["start_frame"], "voice start frame")
            line_end = _frame(
                raw_voice["end_frame"],
                "voice end frame",
                minimum=1,
            )
            if (
                line_start < start_frame
                or line_end > end_frame + 1
                or line_end <= line_start
            ):
                raise _remotion_error("Custom Film director voice timing changed")
            spoken_lines.append(
                {
                    "line_index": line_index,
                    "speaker_id": _text(line["speaker_id"], "speaker identity"),
                    "kind": _text(line["kind"], "spoken-line kind"),
                    "text": _text(line["text"], "spoken-line text"),
                    "source": _source(
                        {
                            key: raw_voice[key]
                            for key in ("source_key", "local_path", "source_sha256")
                        },
                        f"voice source {voice_id}",
                    ),
                    "start_frame": line_start,
                    "end_frame": line_end,
                    "measured_words": _measured_words(
                        raw_voice["measured_words"],
                        line_text=str(line["text"]),
                        start_frame=line_start,
                        end_frame=line_end,
                    ),
                }
            )

        sound_layers: list[dict[str, Any]] = []
        raw_layers = sound_sources[shot_id]
        if not isinstance(raw_layers, Sequence) or isinstance(
            raw_layers, (str, bytes)
        ):
            raise _remotion_error("Custom Film director sound layers are invalid")
        for layer_index, raw_layer in enumerate(raw_layers):
            layer = _strict_mapping(
                raw_layer,
                f"sound layer {shot_id}:{layer_index}",
                frozenset(
                    {
                        "layer_id",
                        "kind",
                        "source_key",
                        "local_path",
                        "source_sha256",
                        "start_frame",
                        "end_frame",
                        "gain_db",
                        "loop",
                    }
                ),
            )
            layer_start = _frame(layer["start_frame"], "sound start frame")
            layer_end = _frame(layer["end_frame"], "sound end frame", minimum=1)
            gain_db = layer["gain_db"]
            if (
                layer.get("kind") not in {"ambient", "score", "sfx"}
                or layer_start < start_frame
                or layer_end > end_frame + 1
                or layer_end <= layer_start
                or isinstance(gain_db, bool)
                or not isinstance(gain_db, (int, float))
                or not -120 <= float(gain_db) <= 12
                or type(layer.get("loop")) is not bool
            ):
                raise _remotion_error("Custom Film director sound layer changed")
            sound_layers.append(
                {
                    "layer_id": _text(layer["layer_id"], "sound layer identity"),
                    "kind": layer["kind"],
                    "source": _source(
                        {
                            key: layer[key]
                            for key in ("source_key", "local_path", "source_sha256")
                        },
                        f"sound source {shot_id}:{layer_index}",
                    ),
                    "start_frame": layer_start,
                    "end_frame": layer_end,
                    "gain_db": float(gain_db),
                    "loop": layer["loop"],
                }
            )
        if not sound_layers:
            raise _remotion_error(
                f"Custom Film director shot {shot['shot_key']} has no sound layer"
            )
        shots.append(
            {
                "shot_id": shot_id,
                "shot_key": shot["shot_key"],
                "section_id": shot["section_id"],
                "order_index": shot["order_index"],
                "start_frame": start_frame,
                "end_frame": end_frame,
                "duration_frames": shot["duration_frames"],
                "technique": shot["technique"],
                "performance_mode": shot["performance_mode"],
                "caption_mode": shot["caption_mode"],
                "transition_from_previous": shot["transition_from_previous"],
                "transition_duration_frames": _transition_frames(
                    str(shot["transition_from_previous"]),
                    int(shot["duration_frames"]),
                ),
                "clip": _source(
                    clip_sources[str(shot["clip_artifact_id"])],
                    f"clip source {shot_id}",
                ),
                "spoken_lines": spoken_lines,
                "sound_layers": sound_layers,
            }
        )
    body = {
        "schema_version": DIRECTOR_REMOTION_PROPS_VERSION,
        "identity": {
            "director_contract_hash": admission["director_contract_hash"],
            "storyboard_gate_hash": admission["storyboard_gate_hash"],
            "picture_gate_hash": admission["picture_gate_hash"],
            "visual_gate_hash": admission["visual_gate_hash"],
            "admission_hash": admission["admission_hash"],
        },
        "video": {
            "fps": admission["fps"],
            "width": width,
            "height": height,
            "total_frames": admission["total_frames"],
        },
        "shots": shots,
    }
    return {**body, "props_hash": remotion_props_hash(body)}
