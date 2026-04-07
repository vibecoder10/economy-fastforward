"""Data models for the video dispatch system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ContinuityBible:
    """Visual consistency rules locked before generation."""

    characters: list[dict] = field(default_factory=list)
    locations: list[dict] = field(default_factory=list)
    lighting: str = ""
    camera: str = ""
    color_grade: str = ""
    aspect_ratio: str = "16:9"

    @classmethod
    def from_dict(cls, data: dict) -> ContinuityBible:
        return cls(
            characters=data.get("characters", []),
            locations=data.get("locations", []),
            lighting=data.get("lighting", ""),
            camera=data.get("camera", ""),
            color_grade=data.get("color_grade", ""),
            aspect_ratio=data.get("aspect_ratio", "16:9"),
        )


@dataclass
class Keyframe:
    """A single keyframe image to generate."""

    keyframe_id: str
    shot_type: str
    prompt: str
    aspect_ratio: str = "16:9"
    notes: str = ""
    location: str = ""  # Location name from bible (for location ref injection)
    characters: list = field(default_factory=list)  # Character names in this scene

    # Filled after generation
    status: TaskStatus = TaskStatus.PENDING
    task_id: Optional[str] = None
    image_url: Optional[str] = None
    error: Optional[str] = None


@dataclass
class Bridge:
    """A video bridge between two keyframes."""

    bridge_id: str
    from_keyframe: str
    to_keyframe: str
    prompt: str
    duration: int = 6
    mode: str = "normal"
    resolution: str = "720p"
    aspect_ratio: str = "16:9"
    characters: list = field(default_factory=list)  # Character names in this scene
    location: str = ""  # Location name from bible (for location ref injection)
    waypoints: list = field(default_factory=list)  # Intermediate keyframe IDs as visual guides

    # Filled after generation
    status: TaskStatus = TaskStatus.PENDING
    task_id: Optional[str] = None
    video_url: Optional[str] = None
    error: Optional[str] = None


@dataclass
class Scene:
    """A scene groups keyframes and bridges into a logical unit."""

    scene_id: str
    name: str
    location: str = ""
    characters: list = field(default_factory=list)
    keyframes: list = field(default_factory=list)  # Keyframe IDs
    bridges: list = field(default_factory=list)  # Bridge IDs
    notes: str = ""


@dataclass
class ProductionSheet:
    """Complete production sheet from the story-to-video skill."""

    title: str
    total_duration_s: int
    visual_style: str
    aspect_ratio: str
    bible: ContinuityBible
    keyframes: list[Keyframe]
    bridges: list[Bridge]
    scenes: list[Scene] = field(default_factory=list)
    assembly_order: list[dict] = field(default_factory=list)

    def get_scene(self, scene_id: str) -> Optional[Scene]:
        """Get a scene by ID or name (fuzzy)."""
        for sc in self.scenes:
            if sc.scene_id == scene_id or sc.name.lower() == scene_id.lower():
                return sc
        # Fuzzy: check if query is in the name
        query = scene_id.lower()
        for sc in self.scenes:
            if query in sc.scene_id.lower() or query in sc.name.lower():
                return sc
        return None

    def get_scene_keyframes(self, scene_id: str) -> list[Keyframe]:
        """Get all keyframe objects for a scene."""
        sc = self.get_scene(scene_id)
        if not sc:
            return []
        kf_map = {kf.keyframe_id: kf for kf in self.keyframes}
        return [kf_map[kid] for kid in sc.keyframes if kid in kf_map]

    def get_scene_bridges(self, scene_id: str) -> list[Bridge]:
        """Get all bridge objects for a scene."""
        sc = self.get_scene(scene_id)
        if not sc:
            return []
        br_map = {br.bridge_id: br for br in self.bridges}
        return [br_map[bid] for bid in sc.bridges if bid in br_map]

    @classmethod
    def from_dict(cls, data: dict) -> ProductionSheet:
        bible = ContinuityBible.from_dict(data.get("bible", {}))
        aspect = data.get("aspect_ratio", "16:9")

        keyframes = [
            Keyframe(
                keyframe_id=kf["keyframe_id"],
                shot_type=kf.get("shot_type", "wide"),
                prompt=kf["prompt"],
                aspect_ratio=kf.get("aspect_ratio", aspect),
                notes=kf.get("notes", ""),
                location=kf.get("location", ""),
                characters=kf.get("characters", []),
            )
            for kf in data.get("keyframes", [])
        ]

        bridges = [
            Bridge(
                bridge_id=br["bridge_id"],
                from_keyframe=br["from_keyframe"],
                to_keyframe=br["to_keyframe"],
                prompt=br["prompt"],
                duration=br.get("duration", 6),
                mode=br.get("mode", "normal"),
                resolution=br.get("resolution", "720p"),
                aspect_ratio=br.get("aspect_ratio", aspect),
                characters=br.get("characters", []),
                location=br.get("location", ""),
                waypoints=br.get("waypoints", []),
            )
            for br in data.get("bridges", [])
        ]

        scenes = [
            Scene(
                scene_id=sc["scene_id"],
                name=sc.get("name", ""),
                location=sc.get("location", ""),
                characters=sc.get("characters", []),
                keyframes=sc.get("keyframes", []),
                bridges=sc.get("bridges", []),
                notes=sc.get("notes", ""),
            )
            for sc in data.get("scenes", [])
        ]

        assembly_order = data.get("assembly_order", [])
        if not assembly_order:
            # Auto-generate: interleave keyframes and bridges
            for i, kf in enumerate(keyframes):
                assembly_order.append({"type": "keyframe", "id": kf.keyframe_id})
                if i < len(bridges):
                    assembly_order.append({"type": "bridge", "id": bridges[i].bridge_id})

        return cls(
            title=data.get("title", "Untitled"),
            total_duration_s=data.get("total_duration_s", 0),
            visual_style=data.get("visual_style", "cinematic"),
            aspect_ratio=aspect,
            bible=bible,
            keyframes=keyframes,
            bridges=bridges,
            scenes=scenes,
            assembly_order=assembly_order,
        )
