"""Pipeline Configuration Layer.

Computes all derived pipeline parameters from:
- video_length_minutes: Target video duration (3-30 minutes)

Clip duration is assigned dynamically per-segment by the segmentation engine:
- Segments with <= 6s of narration get 6s clips
- Segments with > 6s of narration get 10s clips
- Remotion trims each clip to fit the actual voiceover duration

The planning default of 10s clips is used for estimating total clips, script
word targets, and costs. Actual clip durations vary per segment.
"""


class VideoConfig:
    """Pipeline parameters derived from video_length_minutes.

    clip_duration_seconds is a planning default (10s) used to estimate total
    clips and script word targets. Actual clip durations are assigned per-segment
    by the segmentation engine based on narration length.
    """

    SPEAKING_RATE_WPS = 2.5  # words per second for narration

    def __init__(self, video_length_minutes: int = 10, clip_duration_seconds: int = 10):
        # Input validation
        if video_length_minutes < 1:
            raise ValueError("Minimum video length is 1 minute")
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
        self.script_min_words = self.total_script_words - 150
        self.script_max_words = self.total_script_words + 150

        # Computed: structure. Short videos (1-2 min) get a single act; 3+ min keep
        # the established 3-6 act structure (unchanged).
        self.act_count = max(3, min(6, video_length_minutes // 2)) if video_length_minutes >= 3 else 1
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
    def from_airtable_record(cls, record: dict) -> tuple["VideoConfig", bool]:
        """Create VideoConfig from an Airtable Idea Concepts record.

        Reads 'Video Length (min)' field. Falls back to 10 min if empty.
        Clip duration is always 10s for planning estimates — actual clip
        durations are assigned per-segment by the segmentation engine.

        Returns:
            Tuple of (VideoConfig, duration_was_set) where duration_was_set
            is True if the field was present, False if defaulted to 10 min.
        """
        fields = record.get("fields", record)
        length = fields.get("Video Length (min)")

        duration_was_set = length is not None and length != ""
        video_length = int(length) if duration_was_set else 10

        return cls(video_length_minutes=video_length), duration_was_set


# Act structure templates scaled by act count
ACT_TEMPLATES = {
    1: [
        # Short videos (1-2 min): one tight beat. Generic/format-agnostic so it works
        # for any topic, not just the legacy geopolitics structure below.
        {"name": "The Whole Thing", "purpose": "Hook fast, deliver the idea clearly, land the payoff", "pct": 1.0},
    ],
    2: [
        {"name": "Hook & Setup", "purpose": "Grab attention and set up the idea", "pct": 0.5},
        {"name": "Payoff", "purpose": "Deliver the answer/idea and end strong", "pct": 0.5},
    ],
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
