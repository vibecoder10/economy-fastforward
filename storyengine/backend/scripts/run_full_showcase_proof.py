#!/usr/bin/env python3
"""Cold-resumable, local-only proof harness for the 300s Custom Film showcase.

This script creates deterministic local fixtures, runs the real Remotion
renderer, and verifies the creative inspection set plus technical, subtitle,
and source-audio evidence. A second render adds a byte-identity diagnostic,
but creative acceptance does not depend on container-byte equality. It never
contacts providers, databases, Redis, or the network.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]
REMOTION_ROOT = REPOSITORY_ROOT / "remotion-video"
PROOF_ROOT = REMOTION_ROOT / "out" / "full-showcase-proof"
FIXTURE_ROOT = PROOF_ROOT / "fixtures"
PROPS_PATH = PROOF_ROOT / "props.json"
SOURCE_MAP_PATH = PROOF_ROOT / "source-map.json"
PREPARED_PATH = PROOF_ROOT / "prepared.json"
FPS = 24
WIDTH = 1920
HEIGHT = 1080
TOTAL_SECONDS = 300
TOTAL_FRAMES = FPS * TOTAL_SECONDS
SECTION_SPECS = (
    ("opening", "opening", 0, 1080, 45),
    ("evidence", "evidence", 1080, 2520, 105),
    ("witness", "case_study", 3600, 2160, 90),
    ("explanation", "explanation", 5760, 1440, 60),
)
PRIMITIVE_FRAMES = (
    480,   # SignalPulse
    1600,  # OutageMap
    2400,  # EvidenceBoard
    3250,  # IncidentTimeline
    3900,  # measured bilingual captions
    5100,  # RadioWaveform
    5900,  # NetworkExplainer failure state
    6200,  # NetworkExplainer ordered reconnection
)
BOUNDARY_FRAMES = (1079, 1080, 3599, 3600, 5759, 5760)
REPRESENTATIVE_FRAMES = (120, 1200, 3720, 6000)
REVEAL_FRAMES = tuple(range(6840, 7177, FPS)) + (7199,)

sys.path.insert(0, str(BACKEND_ROOT))

from custom_film_compositor import probe_media  # noqa: E402
from custom_film_remotion import (  # noqa: E402
    REMOTION_PROPS_VERSION,
    REMOTION_RENDERER_CONTRACT_VERSION,
    _renderer_source_specs,
    _validate_renderer_props,
    canonical_remotion_json,
    remotion_props_hash,
    renderer_bundle_hash,
    run_remotion_renderer,
)


def digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_local(args: list[str], *, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "LC_ALL": "C",
        "LANG": "C",
        "NO_PROXY": "*",
        "no_proxy": "*",
    }
    return subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env=environment,
    )


def ffmpeg(args: list[str], *, timeout: int = 900) -> None:
    run_local(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], timeout=timeout)


def fixture_paths() -> dict[str, Path]:
    return {
        "proof:opening:still": FIXTURE_ROOT / "opening.png",
        "proof:opening:narration": FIXTURE_ROOT / "opening.wav",
        "proof:evidence:still": FIXTURE_ROOT / "evidence.png",
        "proof:evidence:narration": FIXTURE_ROOT / "evidence.wav",
        "proof:witness:video": FIXTURE_ROOT / "witness.mp4",
        "proof:explanation:still": FIXTURE_ROOT / "explanation.png",
        "proof:explanation:narration": FIXTURE_ROOT / "explanation.wav",
    }


def generate_still(path: Path, *, color: str, accent: str, inset: int) -> None:
    ffmpeg(
        [
            "-f", "lavfi", "-i", f"color=c={color}:s={WIDTH}x{HEIGHT}",
            "-vf",
            (
                f"drawbox=x={inset}:y={inset}:w={WIDTH-(2*inset)}:"
                f"h={HEIGHT-(2*inset)}:color={accent}@0.48:t=18,"
                f"drawbox=x={inset+180}:y={inset+150}:w=520:h=260:"
                f"color={accent}@0.18:t=fill"
            ),
            "-frames:v", "1", "-c:v", "png", "-map_metadata", "-1", str(path),
        ]
    )


def generate_narration(path: Path, *, seconds: int, frequency: int) -> None:
    samples = seconds * 48_000
    ffmpeg(
        [
            "-f", "lavfi", "-i",
            f"sine=frequency={frequency}:sample_rate=48000:duration={seconds}",
            "-af", f"volume=0.08,atrim=end_sample={samples},asetpts=N/SR/TB",
            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
            "-map_metadata", "-1", str(path),
        ]
    )


def generate_witness(path: Path) -> None:
    seconds = 90
    samples = seconds * 48_000
    ffmpeg(
        [
            "-f", "lavfi", "-i",
            f"testsrc2=size={WIDTH}x{HEIGHT}:rate={FPS}:duration={seconds}",
            "-f", "lavfi", "-i",
            f"sine=frequency=440:sample_rate=48000:duration={seconds}",
            "-map", "0:v:0", "-map", "1:a:0",
            "-vf",
            "hue=s=0.35,drawbox=x=656:y=0:w=608:h=1080:color=0x2de2d0@0.16:t=10",
            "-af", f"volume=0.08,atrim=end_sample={samples},asetpts=N/SR/TB",
            "-frames:v", str(seconds * FPS),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", "-map_metadata", "-1", str(path),
        ],
        timeout=1800,
    )


def transition(*, first: bool, last: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    incoming = {
        "type": "none" if first else "fade_from_black",
        "duration_frames": 0 if first else 12,
        "overlap_frames": 0,
        "accounting": "inside_section",
        "audio": "none" if first else "fade_in",
    }
    outgoing = {
        "type": "none" if last else "dip_to_black",
        "duration_frames": 0 if last else 12,
        "overlap_frames": 0,
        "accounting": "inside_section",
        "audio": "none" if last else "fade_out",
    }
    return incoming, outgoing


def build_props(paths: Mapping[str, Path]) -> dict[str, Any]:
    bundle_hash = renderer_bundle_hash(REMOTION_ROOT)
    sections: list[dict[str, Any]] = []
    for order, (section_id, role, start, frames, seconds) in enumerate(SECTION_SPECS):
        first = order == 0
        last = order == len(SECTION_SPECS) - 1
        transition_in, transition_out = transition(first=first, last=last)
        scene_id = f"proof:{section_id}:scene"
        if section_id == "witness":
            visual_key = "proof:witness:video"
            visual_path = paths[visual_key]
            assets = [
                {
                    "asset_id": "proof:witness:asset",
                    "source_key": visual_key,
                    "source_sha256": digest_file(visual_path),
                    "provenance_hash": digest_text("proof:witness:provenance"),
                    "caption_hash": digest_text("proof:witness:caption"),
                    "caption_card": {"fixture": "local", "role": role},
                    "actual_duration_ms": 90_000,
                    "assigned_duration_ms": 90_000,
                    "start_frame": 0,
                    "duration_frames": frames,
                    "timing_transform": {
                        "mode": "none",
                        "source_duration_ms": 90_000,
                        "output_duration_ms": 90_000,
                    },
                    "camera": {"mode": "approved_source_clip"},
                }
            ]
            audio = {
                "mode": "source_clip",
                "sources": [],
                "timing_transform": {
                    "mode": "source_clip",
                    "source_duration_ms": 90_000,
                    "output_duration_ms": 90_000,
                    "atempo_chain": [],
                    "caption_scale": 1,
                },
                "gain_db": -3,
            }
            dialogue_audio = "grok_native"
            render_mode = "approved_source_clip"
            caption_text = "Mara: Si puedes oírme. / Mara, if you can hear me."
            language = {"mode": "bilingual", "languages": ["es", "en"]}
        else:
            visual_key = f"proof:{section_id}:still"
            audio_key = f"proof:{section_id}:narration"
            visual_path = paths[visual_key]
            audio_path = paths[audio_key]
            assets = [
                {
                    "asset_id": f"proof:{section_id}:asset",
                    "source_key": visual_key,
                    "source_sha256": digest_file(visual_path),
                    "provenance_hash": digest_text(f"proof:{section_id}:provenance"),
                    "caption_hash": digest_text(f"proof:{section_id}:caption"),
                    "caption_card": {"fixture": "local", "role": role},
                    "actual_duration_ms": None,
                    "assigned_duration_ms": None,
                    "start_frame": 0,
                    "duration_frames": frames,
                    "timing_transform": {
                        "mode": "static_hold",
                        "source_duration_ms": None,
                        "output_duration_ms": seconds * 1000,
                    },
                    "camera": {"mode": "deterministic_remotion_frames"},
                }
            ]
            audio = {
                "mode": "voice_over",
                "sources": [
                    {
                        "source_key": audio_key,
                        "source_sha256": digest_file(audio_path),
                        "source_duration_ms": seconds * 1000,
                    }
                ],
                "timing_transform": {
                    "mode": "none",
                    "source_duration_ms": seconds * 1000,
                    "output_duration_ms": seconds * 1000,
                    "atempo_chain": [],
                    "caption_scale": 1,
                },
                "gain_db": -6,
            }
            dialogue_audio = "voice_over"
            render_mode = "static_docu"
            caption_text = f"Deterministic approved {role} proof."
            language = {"mode": "narration", "languages": ["en"]}
        sections.append(
            {
                "section_id": f"proof-{section_id}",
                "order_index": order,
                "role": role,
                "render_mode": render_mode,
                "visual_profile": role,
                "dialogue_audio": dialogue_audio,
                "scene_ids": [scene_id],
                "start_frame": start,
                "duration_frames": frames,
                "transition_in": transition_in,
                "transition_out": transition_out,
                "assets": assets,
                "audio": audio,
                "captions": [
                    {
                        "scene_id": scene_id,
                        "text": caption_text,
                        "language": language,
                        "section_start_ms": 0,
                        "section_end_ms": seconds * 1000,
                        "start_frame": start,
                        "end_frame": start + frames,
                    }
                ],
            }
        )
    body = {
        "schema_version": REMOTION_PROPS_VERSION,
        "identity": {
            "assembly_version": "custom-film-assembly-v3",
            "assembly_manifest_hash": digest_text("full-showcase-proof:assembly-v3"),
            "tenant_id": "local-proof-tenant",
            "video_id": "storyengine-full-showcase-proof",
            "plan_id": "storyengine-full-showcase-proof-plan",
            "plan_hash": digest_text("full-showcase-proof:plan"),
            "quote_inputs_hash": digest_text("full-showcase-proof:quote"),
            "approval_hash": digest_text("full-showcase-proof:approval"),
            "runtime_hash": digest_text("full-showcase-proof:runtime"),
            "runtime_job_id": "local-proof-job",
            "max_spend": 15,
            "render_engine": "remotion",
            "renderer_contract_version": REMOTION_RENDERER_CONTRACT_VERSION,
            "renderer_bundle_hash": bundle_hash,
        },
        "video": {
            "fps": FPS,
            "width": WIDTH,
            "height": HEIGHT,
            "total_duration_seconds": TOTAL_SECONDS,
            "total_frames": TOTAL_FRAMES,
        },
        "transition_accounting": {
            "type": "dip_to_black_non_overlap",
            "duration_source": "fixed_12_frames_inside_section",
            "overlap_frames_total": 0,
            "duration_lives_inside_assigned_sections": True,
        },
        "sections": sections,
    }
    props = {**body, "props_hash": remotion_props_hash(body)}
    return _validate_renderer_props(props)


async def validate_sources(props: Mapping[str, Any], paths: Mapping[str, Path]) -> list[dict[str, Any]]:
    expected = {spec["source_key"]: spec for spec in _renderer_source_specs(props)}
    if set(expected) != set(paths):
        raise RuntimeError("Prepared fixture source set does not exactly match props")
    records: list[dict[str, Any]] = []
    for source_key in sorted(paths):
        path = paths[source_key]
        spec = expected[source_key]
        actual_hash = digest_file(path)
        if actual_hash != spec["sha256"]:
            raise RuntimeError(f"Prepared source hash changed: {source_key}")
        result = run_local(
            [
                "ffprobe", "-v", "error", "-show_entries",
                (
                    "format=duration:stream=codec_type,codec_name,pix_fmt,width,"
                    "height,sample_rate,channels,nb_frames,avg_frame_rate,duration"
                ),
                "-of", "json", str(path),
            ]
        )
        probe = json.loads(result.stdout)
        streams = probe.get("streams") or []
        video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
        audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
        if spec["kind"] == "image":
            if (
                not video
                or audio
                or video.get("codec_name") != "png"
                or video.get("width") != WIDTH
                or video.get("height") != HEIGHT
            ):
                raise RuntimeError(f"Prepared still identity changed: {source_key}")
        elif spec["kind"] == "audio":
            duration = float((audio or {}).get("duration") or (probe.get("format") or {}).get("duration") or 0)
            if (
                video
                or not audio
                or audio.get("codec_name") != "pcm_s16le"
                or audio.get("sample_rate") != "48000"
                or audio.get("channels") != 2
                or abs(duration * 1000 - spec["source_duration_ms"]) > 0.001
            ):
                raise RuntimeError(f"Prepared narration identity changed: {source_key}")
        else:
            video_duration = float((video or {}).get("duration") or 0)
            audio_duration = float((audio or {}).get("duration") or 0)
            if (
                not video
                or not audio
                or video.get("codec_name") != "h264"
                or video.get("pix_fmt") != "yuv420p"
                or video.get("width") != WIDTH
                or video.get("height") != HEIGHT
                or video.get("avg_frame_rate") != "24/1"
                or int(video.get("nb_frames") or 0) != 2160
                or audio.get("codec_name") != "aac"
                or audio.get("sample_rate") != "48000"
                or audio.get("channels") != 2
                or abs(video_duration * 1000 - spec["source_duration_ms"]) > 0.001
                or audio_duration + 0.002 < video_duration
                or audio_duration - video_duration > ((1024 / 48_000) + 0.002)
            ):
                raise RuntimeError(f"Prepared witness identity changed: {source_key}")
        records.append(
            {
                "source_key": source_key,
                "kind": spec["kind"],
                "path": str(path),
                "sha256": actual_hash,
                "bytes": path.stat().st_size,
                "probe": probe,
            }
        )
    return records


async def prepare() -> None:
    PROOF_ROOT.mkdir(parents=True, exist_ok=True)
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    paths = fixture_paths()
    generate_still(paths["proof:opening:still"], color="0x071217", accent="0x2de2d0", inset=150)
    generate_still(paths["proof:evidence:still"], color="0x15100b", accent="0xffb454", inset=190)
    generate_still(paths["proof:explanation:still"], color="0x0b1020", accent="0x6aa7ff", inset=230)
    generate_narration(paths["proof:opening:narration"], seconds=45, frequency=220)
    generate_narration(paths["proof:evidence:narration"], seconds=105, frequency=275)
    generate_narration(paths["proof:explanation:narration"], seconds=60, frequency=330)
    generate_witness(paths["proof:witness:video"])
    props = build_props(paths)
    if [
        (section["role"], section["start_frame"], section["duration_frames"])
        for section in props["sections"]
    ] != [
        (role, start, frames)
        for _section_id, role, start, frames, _seconds in SECTION_SPECS
    ]:
        raise RuntimeError("Prepared section contract changed")
    records = await validate_sources(props, paths)
    still_hashes = {
        record["sha256"] for record in records if record["kind"] == "image"
    }
    if len(still_hashes) != 3:
        raise RuntimeError("Prepared still fixtures are not distinct")
    PROPS_PATH.write_text(canonical_remotion_json(props), encoding="utf-8")
    write_json(SOURCE_MAP_PATH, {key: str(value) for key, value in sorted(paths.items())})
    write_json(
        PREPARED_PATH,
        {
            "status": "prepared_local",
            "props_path": str(PROPS_PATH),
            "props_hash": props["props_hash"],
            "renderer_bundle_hash": props["identity"]["renderer_bundle_hash"],
            "source_map_path": str(SOURCE_MAP_PATH),
            "source_count": len(records),
            "sources": records,
            "render_commands": [
                f"{sys.executable} {Path(__file__).resolve()} --render a",
                f"{sys.executable} {Path(__file__).resolve()} --render b",
                f"{sys.executable} {Path(__file__).resolve()} --verify",
            ],
        },
    )
    print(f"Prepared {len(records)} deterministic sources and strict props at {PROOF_ROOT}")
    print("No 300-second render was started.")


def load_prepared() -> tuple[dict[str, Any], dict[str, Path]]:
    if not PREPARED_PATH.is_file() or not PROPS_PATH.is_file() or not SOURCE_MAP_PATH.is_file():
        raise RuntimeError("Run --prepare-only before rendering")
    props = _validate_renderer_props(read_json(PROPS_PATH))
    paths = {key: Path(value) for key, value in read_json(SOURCE_MAP_PATH).items()}
    expected = {spec["source_key"]: spec["sha256"] for spec in _renderer_source_specs(props)}
    if set(paths) != set(expected):
        raise RuntimeError("Prepared source map changed")
    for key, path in paths.items():
        if not path.is_file() or digest_file(path) != expected[key]:
            raise RuntimeError(f"Prepared source changed: {key}")
    return props, paths


async def render(label: str) -> None:
    props, paths = load_prepared()
    output = PROOF_ROOT / f"master-{label}.mp4"
    result_path = PROOF_ROOT / f"result-{label}.json"
    probe_path = PROOF_ROOT / f"probe-{label}.json"
    hash_path = PROOF_ROOT / f"hash-{label}.json"
    state_path = PROOF_ROOT / f"render-{label}-state.json"
    if output.is_file() and result_path.is_file() and probe_path.is_file() and hash_path.is_file():
        if digest_file(output) == read_json(hash_path)["sha256"]:
            print(f"Render {label} is already complete and hash-valid: {output}")
            return
        raise RuntimeError(f"Existing render {label} sidecars do not match")

    async def progress(message: str) -> None:
        write_json(state_path, {"status": "rendering", "label": label, "progress": message})
        print(message, flush=True)

    write_json(state_path, {"status": "starting", "label": label, "output": str(output)})
    try:
        result = await run_remotion_renderer(
            remotion_props=props,
            source_paths=paths,
            output_path=output,
            on_progress=progress,
            timeout_seconds=7200,
        )
        probe = await probe_media(output)
        artifact_hash = digest_file(output)
        write_json(result_path, result)
        write_json(probe_path, probe)
        write_json(hash_path, {"sha256": artifact_hash, "bytes": output.stat().st_size})
        write_json(
            state_path,
            {"status": "complete", "label": label, "sha256": artifact_hash, "output": str(output)},
        )
    except Exception as exc:
        write_json(state_path, {"status": "failed", "label": label, "error": str(exc)})
        raise


def volume_stats(path: Path, *, start: float, duration: float) -> dict[str, Any]:
    result = run_local(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "info",
            "-ss", f"{start:.6f}", "-t", f"{duration:.6f}", "-i", str(path),
            "-vn", "-af", "volumedetect", "-f", "null", "-",
        ],
        timeout=300,
    )
    combined = result.stdout + result.stderr

    def value(name: str) -> float:
        match = re.search(rf"{name}: (-?inf|-?[0-9.]+) dB", combined)
        if not match:
            raise RuntimeError(f"Missing {name} for {start:.3f}s segment")
        return -math.inf if match.group(1) == "-inf" else float(match.group(1))

    return {
        "start_seconds": start,
        "duration_seconds": duration,
        "mean_volume_db": value("mean_volume"),
        "max_volume_db": value("max_volume"),
    }


def band_volume_stats(
    path: Path,
    *,
    start: float,
    duration: float,
    frequency: int,
) -> dict[str, Any]:
    result = run_local(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "info",
            "-ss", f"{start:.6f}", "-t", f"{duration:.6f}", "-i", str(path),
            "-vn", "-af",
            f"bandpass=f={frequency}:width_type=h:width=12,volumedetect",
            "-f", "null", "-",
        ],
        timeout=300,
    )
    combined = result.stdout + result.stderr
    match = re.search(r"mean_volume: (-?inf|-?[0-9.]+) dB", combined)
    if not match:
        raise RuntimeError(
            f"Missing spectral evidence for {frequency} Hz at {start:.3f}s"
        )
    mean = -math.inf if match.group(1) == "-inf" else float(match.group(1))
    return {
        "start_seconds": start,
        "duration_seconds": duration,
        "frequency_hz": frequency,
        "mean_volume_db": mean,
    }


def subtitle_evidence(
    master: Path,
    props: Mapping[str, Any],
) -> dict[str, Any]:
    extracted = run_local(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(master),
            "-map", "0:s:0", "-f", "srt", "-",
        ],
        timeout=300,
    ).stdout
    expected = [
        {
            "text": caption["text"],
            "start_seconds": caption["start_frame"] / FPS,
            "end_seconds": caption["end_frame"] / FPS,
        }
        for section in props["sections"]
        for caption in section["captions"]
    ]
    for caption in expected:
        if caption["text"] not in extracted:
            raise RuntimeError(
                f"Approved Unicode caption missing: {caption['text']}"
            )
    stream_probe = json.loads(
        run_local(
            [
                "ffprobe", "-v", "error", "-select_streams", "s:0",
                "-show_entries", "stream=index,codec_name:stream_tags=language",
                "-of", "json", str(master),
            ]
        ).stdout
    )
    streams = stream_probe.get("streams") or []
    if (
        len(streams) != 1
        or streams[0].get("codec_name") != "mov_text"
        or (streams[0].get("tags") or {}).get("language") != "mul"
    ):
        raise RuntimeError("Approved multilingual subtitle identity changed")
    return {
        "expected": expected,
        "extracted_srt_sha256": digest_text(extracted),
        "stream": streams[0],
        "unicode_text_verified": True,
    }


def audio_stream_evidence(master: Path) -> dict[str, Any]:
    payload = json.loads(
        run_local(
            [
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries",
                "stream=codec_name,sample_rate,channels,time_base,duration_ts,duration",
                "-of", "json", str(master),
            ]
        ).stdout
    )
    streams = payload.get("streams") or []
    if len(streams) != 1:
        raise RuntimeError("Final master audio stream count changed")
    stream = streams[0]
    duration = float(stream.get("duration") or 0)
    if (
        stream.get("codec_name") != "aac"
        or stream.get("sample_rate") != "48000"
        or stream.get("channels") != 2
        or abs(duration - TOTAL_SECONDS) > (1 / FPS + 0.002)
    ):
        raise RuntimeError("Final master audio identity changed")
    return stream


def extract_frames(master: Path, destination: Path) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    frames = tuple(
        dict.fromkeys(
            (
                *REPRESENTATIVE_FRAMES,
                *PRIMITIVE_FRAMES,
                *BOUNDARY_FRAMES,
                *REVEAL_FRAMES,
            )
        )
    )
    for index, frame in enumerate(frames):
        ffmpeg(
            [
                "-i", str(master),
                "-vf", f"select=eq(n\\,{frame})",
                "-vsync", "vfr", "-frames:v", "1",
                str(destination / f"frame-{index:03d}.png"),
            ],
            timeout=300,
        )
    wide = destination / "contact-wide.png"
    vertical = destination / "contact-vertical.png"
    input_pattern = str(destination / "frame-%03d.png")
    rows_wide = math.ceil(len(frames) / 5)
    rows_vertical = math.ceil(len(frames) / 8)
    ffmpeg(
        [
            "-framerate", "1", "-i", input_pattern,
            "-vf", f"scale=384:216,tile=5x{rows_wide}",
            "-frames:v", "1", str(wide),
        ]
    )
    ffmpeg(
        [
            "-framerate", "1", "-i", input_pattern,
            "-vf",
            f"crop=608:1080:656:0,scale=152:270,tile=8x{rows_vertical}",
            "-frames:v", "1", str(vertical),
        ]
    )
    mapping = [
        {"index": index, "frame": frame, "seconds": frame / FPS}
        for index, frame in enumerate(frames)
    ]
    write_json(destination / "frame-map.json", mapping)
    return {
        "frames": mapping,
        "wide_contact": str(wide),
        "vertical_contact": str(vertical),
    }


async def verify() -> None:
    props, _paths = load_prepared()
    masters = {
        label: master
        for label in ("a", "b")
        if (master := PROOF_ROOT / f"master-{label}.mp4").is_file()
    }
    if "a" not in masters:
        raise RuntimeError("Creative master A is missing; run --render a")
    hashes = {label: digest_file(path) for label, path in masters.items()}
    byte_identical = (
        hashes["a"] == hashes["b"]
        if "b" in hashes
        else None
    )
    probes = {label: await probe_media(path) for label, path in masters.items()}
    for label, probe in probes.items():
        if (
            probe.get("frame_count") != TOTAL_FRAMES
            or probe.get("width") != WIDTH
            or probe.get("height") != HEIGHT
            or probe.get("fps_fraction") != "24/1"
            or not probe.get("has_audio")
            or not probe.get("has_subtitles")
            or abs(float(probe.get("duration_seconds") or 0) - TOTAL_SECONDS)
            > (1 / FPS + 0.002)
        ):
            raise RuntimeError(f"Render {label} failed exact final probe")
    contacts = {
        label: extract_frames(master, PROOF_ROOT / f"inspection-{label}")
        for label, master in masters.items()
    }
    section_audio = {
        label: [
            {
                "section": section_id,
                **volume_stats(master, start=start / FPS, duration=seconds),
            }
            for section_id, _role, start, _frames, seconds in SECTION_SPECS
        ]
        for label, master in masters.items()
    }
    checks = {
        label: {
            "hard_silence": volume_stats(master, start=16.25, duration=2),
            "first_pulse": volume_stats(master, start=18.5, duration=1.5),
            "witness_native_audio": volume_stats(master, start=160, duration=5),
        }
        for label, master in masters.items()
    }
    subtitles = {
        label: subtitle_evidence(master, props)
        for label, master in masters.items()
    }
    audio_streams = {
        label: audio_stream_evidence(master)
        for label, master in masters.items()
    }
    source_audio = {}
    frequency_windows = (
        ("opening_narration", 30, 220),
        ("evidence_narration", 80, 275),
        ("witness_native", 170, 440),
        ("explanation_narration", 260, 330),
    )
    for label, master in masters.items():
        source_audio[label] = {}
        for name, start, frequency in frequency_windows:
            target = band_volume_stats(
                master,
                start=start,
                duration=5,
                frequency=frequency,
            )
            control = band_volume_stats(
                master,
                start=start,
                duration=5,
                frequency=frequency + 37,
            )
            margin = target["mean_volume_db"] - control["mean_volume_db"]
            if not math.isfinite(margin) or margin < 6:
                raise RuntimeError(
                    f"Render {label} lost causal {name} audio evidence"
                )
            source_audio[label][name] = {
                "target": target,
                "control": control,
                "margin_db": margin,
            }
    for label, values in checks.items():
        if values["hard_silence"]["max_volume_db"] > -80:
            raise RuntimeError(f"Render {label} hard-silence window is audible")
        if not math.isfinite(values["first_pulse"]["max_volume_db"]):
            raise RuntimeError(f"Render {label} first-pulse window is silent")
        if not math.isfinite(values["witness_native_audio"]["max_volume_db"]):
            raise RuntimeError(f"Render {label} witness native audio is silent")
    write_json(
        PROOF_ROOT / "verification.json",
        {
            "status": "verified",
            "props_hash": props["props_hash"],
            "creative_master_sha256": hashes["a"],
            "hashes": hashes,
            "byte_identical_diagnostic": byte_identical,
            "probes": probes,
            "contacts": contacts,
            "section_audio": section_audio,
            "audio_checks": checks,
            "source_audio": source_audio,
            "audio_streams": audio_streams,
            "subtitles": subtitles,
        },
    )
    print(f"Verified creative master and inspection evidence: {hashes['a']}")
    if byte_identical is None:
        print("A/B byte comparison not run; source-frame/audio determinism is secondary.")
    else:
        print(f"A/B byte-identical diagnostic: {byte_identical}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare-only", action="store_true")
    action.add_argument("--render", choices=("a", "b"))
    action.add_argument("--verify", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.prepare_only:
        asyncio.run(prepare())
    elif args.render:
        asyncio.run(render(args.render))
    else:
        asyncio.run(verify())


if __name__ == "__main__":
    main()
