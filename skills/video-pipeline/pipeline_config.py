"""Pipeline Configuration Layer.

Computes all derived pipeline parameters from two inputs:
- video_length_minutes: Target video duration (3-30 minutes)
- clip_duration_seconds: Duration of each video clip (6 or 10 seconds)

Every downstream system (script, segmentation, images, animation, rendering)
reads from VideoConfig instead of using hardcoded constants.
"""


class VideoConfig:
    """All pipeline parameters derived from video_length_minutes and clip_duration_seconds."""

    SPEAKING_RATE_WPS = 2.5  # words per second for narration

    def __init__(self, video_length_minutes: int = 10, clip_duration_seconds: int = 10):
        # Input validation
        if video_length_minutes < 3:
            raise ValueError("Minimum video length is 3 minutes")
        if video_length_minutes > 30:
            raise ValueError("Maximum video length is 30 minutes")
        if clip_duration_seconds not in (6, 10):
            raise ValueError("Clip duration must be 6 or 10 seconds")

        # Core inputs
        self.video_length_minutes = video_length_minutes
        self.clip_duration_seconds = clip_duration_seconds

        # Computed: timing
        self.total_seconds = video_length_minutes * 60
        self.total_clips = self.total_seconds // clip_duration_seconds

        # Computed: script
        self.words_per_clip = int(clip_duration_seconds * self.SPEAKING_RATE_WPS)
        self.total_script_words = self.total_clips * self.words_per_clip
        self.script_min_words = int(self.total_script_words * 0.9)
        self.script_max_words = int(self.total_script_words * 1.1)

        # Computed: structure
        self.act_count = max(3, min(6, video_length_minutes // 2))
        self.clips_per_act = self.total_clips // self.act_count
        self.scenes_per_act = max(2, self.clips_per_act // self._clips_per_scene())

        # Computed: costs
        self.image_cost = self.total_clips * 0.004
        self.animation_cost = self.total_clips * 0.10
        self.voice_cost_estimate = self.total_script_words * 0.0003
        self.script_cost_estimate = 0.50
        self.total_estimated_cost = (
            self.image_cost + self.animation_cost
            + self.voice_cost_estimate + self.script_cost_estimate
        )

        # Computed: segmentation tolerances
        self.segment_min_words = self.words_per_clip - 3
        self.segment_max_words = self.words_per_clip + 3

        # Computed: animation intensity distribution
        self.high_movement_clips = max(3, int(self.total_clips * 0.10))
        self.medium_movement_clips = int(self.total_clips * 0.30)
        self.low_movement_clips = (
            self.total_clips - self.high_movement_clips - self.medium_movement_clips
        )

    def _clips_per_scene(self) -> int:
        """How many clips (segments) per script scene."""
        if self.video_length_minutes <= 5:
            return 2
        elif self.video_length_minutes <= 10:
            return 3
        elif self.video_length_minutes <= 15:
            return 4
        else:
            return 5

    def to_dict(self) -> dict:
        """Serialize for Airtable storage or Slack reporting."""
        return {
            "video_length_minutes": self.video_length_minutes,
            "clip_duration_seconds": self.clip_duration_seconds,
            "total_clips": self.total_clips,
            "total_script_words": self.total_script_words,
            "act_count": self.act_count,
            "estimated_cost": round(self.total_estimated_cost, 2),
        }

    def summary(self) -> str:
        """Human-readable summary for Slack notifications."""
        return (
            f"Video Config: {self.video_length_minutes}min / {self.clip_duration_seconds}s clips\n"
            f"Total clips: {self.total_clips} | Script: ~{self.total_script_words} words\n"
            f"Acts: {self.act_count} | Words per clip: {self.words_per_clip}\n"
            f"Est. cost: ${self.total_estimated_cost:.2f} "
            f"(img: ${self.image_cost:.2f} + anim: ${self.animation_cost:.2f} + "
            f"voice: ${self.voice_cost_estimate:.2f} + script: ${self.script_cost_estimate:.2f})"
        )

    @classmethod
    def from_airtable_record(cls, record: dict) -> "VideoConfig":
        """Create VideoConfig from an Airtable Idea Concepts record.

        Reads 'Video Length (min)' and 'Clip Duration (s)' fields.
        Falls back to defaults (10 min, 10s clips) if fields are empty.
        """
        fields = record.get("fields", record)
        length = fields.get("Video Length (min)")
        clip = fields.get("Clip Duration (s)")

        video_length = int(length) if length else 10
        clip_duration = int(clip) if clip else 10

        return cls(
            video_length_minutes=video_length,
            clip_duration_seconds=clip_duration,
        )


# Act structure templates scaled by act count
ACT_TEMPLATES = {
    3: [
        {"name": "Setup & Event", "purpose": "Hook + what happened", "pct": 0.35},
        {"name": "Framework & Proof", "purpose": "Why it matters + historical parallel", "pct": 0.40},
        {"name": "Empowerment", "purpose": "Frameworks taught + viewer tools", "pct": 0.25},
    ],
    4: [
        {"name": "The Event", "purpose": "Hook + what happened", "pct": 0.25},
        {"name": "The Framework", "purpose": "Why it matters, the analytical lens", "pct": 0.25},
        {"name": "The Proof", "purpose": "Historical parallels proving the pattern", "pct": 0.30},
        {"name": "Empowerment", "purpose": "Frameworks taught + detection tools", "pct": 0.20},
    ],
    5: [
        {"name": "The Event", "purpose": "Hook + breaking news", "pct": 0.20},
        {"name": "The Framework", "purpose": "Analytical lens explaining why", "pct": 0.20},
        {"name": "The Proof", "purpose": "Historical parallels", "pct": 0.25},
        {"name": "The Consequences", "purpose": "Personal financial/life impact", "pct": 0.20},
        {"name": "Empowerment", "purpose": "Frameworks + tools + what to watch", "pct": 0.15},
    ],
    6: [
        {"name": "The Event", "purpose": "Hook + breaking news", "pct": 0.15},
        {"name": "The Context", "purpose": "Background the viewer needs", "pct": 0.15},
        {"name": "The Framework", "purpose": "Analytical lens", "pct": 0.17},
        {"name": "The Proof", "purpose": "Historical parallels", "pct": 0.20},
        {"name": "The Consequences", "purpose": "Personal impact cascade", "pct": 0.18},
        {"name": "Empowerment", "purpose": "Frameworks + tools + detection", "pct": 0.15},
    ],
}


def get_act_word_targets(config: VideoConfig) -> list[dict]:
    """Compute per-act word targets based on VideoConfig.

    Returns list of dicts with act number, name, purpose, and word target.
    """
    templates = ACT_TEMPLATES.get(config.act_count, ACT_TEMPLATES[6])
    result = []
    for i, tmpl in enumerate(templates):
        word_target = int(config.total_script_words * tmpl["pct"])
        result.append({
            "act_number": i + 1,
            "name": tmpl["name"],
            "purpose": tmpl["purpose"],
            "pct": tmpl["pct"],
            "word_target": word_target,
        })
    return result
