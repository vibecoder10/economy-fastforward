# Autopilot Brain - Chunk 3: CTR Monitoring + Learning Loop

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Complete the learning loop — monitor CTR at milestones, extract patterns, update memory files.

**Architecture:** New `monitoring/` directory under `autopilot/`. Integrates with existing `performance_tracker.py` for YouTube API access.

**Tech Stack:** Python 3.11+, async, googleapiclient (YouTube Analytics), pydantic.

**Related Spec:** `docs/superpowers/specs/2026-03-18-autopilot-brain-design.md` (Sections 4, 8.3)

---

## File Structure (Chunk 3)

```
skills/video-pipeline/autopilot/
├── monitoring/
│   ├── __init__.py
│   ├── ctr_monitor.py           # Poll CTR at 6h/24h/48h milestones
│   ├── early_warning.py         # Alert logic (CRITICAL/WARNING/NORMAL/STRONG)
│   └── performance_comparator.py # Compare our CTR vs competitor VPH
│
├── learning/
│   ├── __init__.py              # Already exists
│   ├── pattern_library.py       # Already exists (Chunk 2)
│   ├── learning_extractor.py    # Extract patterns from 48h+ videos
│   └── memory_writer.py         # Update markdown memory files
│
└── tests/
    ├── test_ctr_monitor.py
    ├── test_early_warning.py
    ├── test_performance_comparator.py
    ├── test_learning_extractor.py
    └── test_memory_writer.py
```

---

## Task 1: Create Monitoring Directory + Early Warning

**Files:**
- Create: `skills/video-pipeline/autopilot/monitoring/__init__.py`
- Create: `skills/video-pipeline/autopilot/monitoring/early_warning.py`
- Create: `skills/video-pipeline/autopilot/tests/test_early_warning.py`

### Implementation

Early warning classifies CTR into alert levels per spec section 4:

```python
"""Alert logic for CTR early warning system."""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class AlertLevel(Enum):
    """CTR alert levels per spec."""
    CRITICAL = "critical"   # CTR < 2.5%
    WARNING = "warning"     # CTR < 3.5%
    NORMAL = "normal"       # CTR 3.5-5.0%
    STRONG = "strong"       # CTR >= 5.0%


class CTRVerdict(Enum):
    """Final CTR verdict after 48h."""
    KEEP = "keep"           # CTR >= 4.0% - pattern confirmed
    DISCARD = "discard"     # CTR <= 2.5% - pattern failed
    NEUTRAL = "neutral"     # In between - need more data


@dataclass
class CTRAlert:
    """CTR check result with alert classification."""
    video_title: str
    ctr: float
    impressions: int
    hours_since_publish: float
    alert_level: AlertLevel
    message: str


class EarlyWarning:
    """Classify CTR into alert levels."""

    # Thresholds from spec
    CRITICAL_THRESHOLD = 2.5
    WARNING_THRESHOLD = 3.5
    STRONG_THRESHOLD = 5.0

    # Verdict thresholds
    KEEP_THRESHOLD = 4.0
    DISCARD_THRESHOLD = 2.5

    def classify(self, ctr: float) -> AlertLevel:
        """Classify CTR into alert level.

        Args:
            ctr: Click-through rate as percentage (e.g., 4.2)

        Returns:
            AlertLevel
        """
        if ctr < self.CRITICAL_THRESHOLD:
            return AlertLevel.CRITICAL
        elif ctr < self.WARNING_THRESHOLD:
            return AlertLevel.WARNING
        elif ctr >= self.STRONG_THRESHOLD:
            return AlertLevel.STRONG
        else:
            return AlertLevel.NORMAL

    def get_verdict(self, ctr: float) -> CTRVerdict:
        """Get final verdict for 48h+ CTR.

        Args:
            ctr: Click-through rate as percentage

        Returns:
            CTRVerdict (KEEP/DISCARD/NEUTRAL)
        """
        if ctr >= self.KEEP_THRESHOLD:
            return CTRVerdict.KEEP
        elif ctr <= self.DISCARD_THRESHOLD:
            return CTRVerdict.DISCARD
        else:
            return CTRVerdict.NEUTRAL

    def create_alert(
        self,
        video_title: str,
        ctr: float,
        impressions: int,
        hours_since_publish: float,
    ) -> CTRAlert:
        """Create a CTR alert with full context.

        Args:
            video_title: Title of the video
            ctr: CTR percentage
            impressions: Number of impressions
            hours_since_publish: Hours since video was published

        Returns:
            CTRAlert with classification and message
        """
        level = self.classify(ctr)

        emoji_map = {
            AlertLevel.CRITICAL: "🚨",
            AlertLevel.WARNING: "⚠️",
            AlertLevel.NORMAL: "📊",
            AlertLevel.STRONG: "✅",
        }

        message_map = {
            AlertLevel.CRITICAL: f"CTR {ctr:.1f}% is CRITICAL — consider thumbnail/title swap",
            AlertLevel.WARNING: f"CTR {ctr:.1f}% needs monitoring — below average",
            AlertLevel.NORMAL: f"CTR {ctr:.1f}% is on track — normal performance",
            AlertLevel.STRONG: f"CTR {ctr:.1f}% is STRONG — pattern working!",
        }

        return CTRAlert(
            video_title=video_title,
            ctr=ctr,
            impressions=impressions,
            hours_since_publish=hours_since_publish,
            alert_level=level,
            message=f"{emoji_map[level]} {message_map[level]}",
        )
```

### Tests

- `test_classify_critical` — CTR < 2.5% returns CRITICAL
- `test_classify_warning` — CTR 2.5-3.5% returns WARNING
- `test_classify_normal` — CTR 3.5-5.0% returns NORMAL
- `test_classify_strong` — CTR >= 5.0% returns STRONG
- `test_verdict_keep` — CTR >= 4.0% returns KEEP
- `test_verdict_discard` — CTR <= 2.5% returns DISCARD
- `test_verdict_neutral` — CTR in between returns NEUTRAL
- `test_create_alert_has_message` — Alert includes formatted message

### Commit

```bash
git add autopilot/monitoring/ autopilot/tests/test_early_warning.py
git commit -m "feat(autopilot): Add early warning system for CTR classification

- AlertLevel enum (CRITICAL/WARNING/NORMAL/STRONG)
- CTRVerdict enum (KEEP/DISCARD/NEUTRAL)
- EarlyWarning classifier with thresholds from spec
- 8 tests passing"
```

---

## Task 2: CTR Monitor

**Files:**
- Create: `skills/video-pipeline/autopilot/monitoring/ctr_monitor.py`
- Create: `skills/video-pipeline/autopilot/tests/test_ctr_monitor.py`

### Implementation

CTR monitor polls YouTube Analytics API and reads from Airtable:

```python
"""Monitor CTR at 6h/24h/48h milestones."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from autopilot.monitoring.early_warning import EarlyWarning, CTRAlert, CTRVerdict
from autopilot.core.state_manager import StateManager


@dataclass
class CTRCheckpoint:
    """CTR measurement at a milestone."""
    video_id: str
    video_title: str
    milestone: str  # "6h", "24h", "48h", "7d"
    ctr: Optional[float]
    impressions: Optional[int]
    checked_at: datetime
    data_available: bool


class CTRMonitor:
    """Monitor CTR at milestones for active experiments."""

    # Milestone intervals in hours
    MILESTONES = {
        "6h": 6,
        "24h": 24,
        "48h": 48,
        "7d": 168,
    }

    def __init__(
        self,
        airtable_client,
        token_path: Optional[Path] = None,
    ):
        """Initialize CTR monitor.

        Args:
            airtable_client: AirtableClient instance
            token_path: Path to YouTube OAuth token
        """
        self.airtable = airtable_client
        self.token_path = token_path or Path(__file__).parent.parent.parent / ".youtube-token.json"
        self.early_warning = EarlyWarning()
        self.state_manager = StateManager()
        self._youtube_analytics = None

    def _get_youtube_analytics(self):
        """Get or create YouTube Analytics API client."""
        if self._youtube_analytics is not None:
            return self._youtube_analytics

        if not self.token_path.exists():
            return None

        with open(self.token_path) as f:
            token_data = json.load(f)

        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=["https://www.googleapis.com/auth/yt-analytics.readonly"],
        )

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())

        self._youtube_analytics = build("youtubeAnalytics", "v2", credentials=creds)
        return self._youtube_analytics

    async def check_6h_ctr(self, video_id: str) -> Optional[float]:
        """Early CTR check via YouTube Analytics API (per spec 8.3).

        Args:
            video_id: YouTube video ID

        Returns:
            CTR as percentage, or None if data not yet available
        """
        analytics = self._get_youtube_analytics()
        if analytics is None:
            return None

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        try:
            response = analytics.reports().query(
                ids="channel==MINE",
                startDate=today,
                endDate=today,
                metrics="impressionClickThroughRate,impressions",
                filters=f"video=={video_id}",
            ).execute()

            if response.get("rows"):
                ctr_decimal = response["rows"][0][0]
                return ctr_decimal * 100  # Convert to percentage
            return None  # Data not yet available
        except Exception as e:
            print(f"6h CTR check failed: {e}")
            return None  # Non-blocking, will retry

    def get_ctr_from_airtable(self, video_title: str) -> Optional[dict]:
        """Get CTR data from Airtable (populated by performance_tracker).

        Args:
            video_title: Video title to look up

        Returns:
            Dict with ctr, impressions, or None if not found
        """
        try:
            record = self.airtable.get_idea_by_title(video_title)
            if record:
                fields = record.get("fields", {})
                ctr = fields.get("CTR (%)")
                impressions = fields.get("Impressions")
                if ctr is not None:
                    return {"ctr": ctr, "impressions": impressions}
        except Exception as e:
            print(f"Airtable CTR lookup failed: {e}")
        return None

    def get_active_experiments(self) -> List[dict]:
        """Get videos currently being monitored.

        Returns:
            List of experiment dicts from state
        """
        state = self.state_manager.load()
        experiments = []

        if state.current_experiment:
            exp = state.current_experiment
            if exp.status == "monitoring" and exp.publish_date:
                experiments.append({
                    "video_title": exp.video_title,
                    "publish_date": exp.publish_date,
                    "modeled_from": exp.modeled_from,
                })

        return experiments

    def get_due_milestones(self, publish_date: str) -> List[str]:
        """Determine which milestones are due for checking.

        Args:
            publish_date: ISO format publish date

        Returns:
            List of milestone names due for checking
        """
        pub_dt = datetime.fromisoformat(publish_date.replace('Z', '+00:00'))
        hours_elapsed = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600

        due = []
        for milestone, hours in self.MILESTONES.items():
            # Due if elapsed >= milestone hours
            if hours_elapsed >= hours:
                due.append(milestone)

        return due

    async def check_experiment(self, experiment: dict) -> Optional[CTRAlert]:
        """Check CTR for an experiment at its current milestone.

        Args:
            experiment: Experiment dict with video_title, publish_date

        Returns:
            CTRAlert if data available, None otherwise
        """
        milestones = self.get_due_milestones(experiment["publish_date"])
        if not milestones:
            return None

        # Get latest due milestone
        latest = milestones[-1]

        # Get CTR (prefer Airtable for 24h+, use API for 6h)
        ctr_data = None
        if latest == "6h":
            # Need video_id for API call
            record = self.airtable.get_idea_by_title(experiment["video_title"])
            if record:
                video_id = record.get("fields", {}).get("YouTube Video ID")
                if video_id:
                    ctr = await self.check_6h_ctr(video_id)
                    if ctr is not None:
                        ctr_data = {"ctr": ctr, "impressions": None}
        else:
            ctr_data = self.get_ctr_from_airtable(experiment["video_title"])

        if ctr_data is None:
            return None

        # Calculate hours since publish
        pub_dt = datetime.fromisoformat(
            experiment["publish_date"].replace('Z', '+00:00')
        )
        hours = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600

        return self.early_warning.create_alert(
            video_title=experiment["video_title"],
            ctr=ctr_data["ctr"],
            impressions=ctr_data.get("impressions") or 0,
            hours_since_publish=hours,
        )
```

### Tests

- `test_get_due_milestones_none` — No milestones due if < 6h
- `test_get_due_milestones_6h` — Returns ["6h"] if 6-24h elapsed
- `test_get_due_milestones_24h` — Returns ["6h", "24h"] if 24-48h elapsed
- `test_get_due_milestones_48h` — Returns all milestones if >= 48h
- `test_check_6h_ctr_returns_none_when_no_data` — Graceful when data unavailable
- `test_get_ctr_from_airtable` — Reads CTR from Airtable record
- `test_check_experiment_creates_alert` — Full flow produces CTRAlert

### Commit

```bash
git add autopilot/monitoring/ctr_monitor.py autopilot/tests/test_ctr_monitor.py
git commit -m "feat(autopilot): Add CTR monitor for milestone checks

- YouTube Analytics API integration for 6h early warning
- Airtable fallback for 24h/48h data
- Milestone detection (6h/24h/48h/7d)
- Integration with early warning system
- 7 tests passing"
```

---

## Task 3: Performance Comparator

**Files:**
- Create: `skills/video-pipeline/autopilot/monitoring/performance_comparator.py`
- Create: `skills/video-pipeline/autopilot/tests/test_performance_comparator.py`

### Implementation

Compare our CTR against the competitor we modeled:

```python
"""Compare our performance vs competitor we modeled."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PerformanceComparison:
    """Comparison between our video and competitor."""
    our_title: str
    our_ctr: float
    competitor_title: str
    competitor_vph: float
    verdict: str  # "outperformed", "matched", "underperformed"
    delta_description: str


class PerformanceComparator:
    """Compare our CTR against competitor VPH."""

    # VPH to expected CTR mapping (rough heuristic)
    # High VPH suggests topic appeal, but doesn't guarantee our CTR
    VPH_TO_CTR_BASELINE = {
        50: 3.0,    # VPH 50 → expect ~3% CTR
        100: 3.5,   # VPH 100 → expect ~3.5% CTR
        150: 4.0,   # VPH 150 → expect ~4% CTR
        200: 4.5,   # VPH 200 → expect ~4.5% CTR
        300: 5.0,   # VPH 300+ → expect ~5% CTR
    }

    def estimate_expected_ctr(self, competitor_vph: float) -> float:
        """Estimate expected CTR based on competitor VPH.

        This is a rough heuristic. Higher VPH suggests proven topic appeal,
        so we'd expect to capture some of that with good execution.

        Args:
            competitor_vph: Competitor's views per hour

        Returns:
            Expected CTR percentage
        """
        # Interpolate from VPH breakpoints
        if competitor_vph <= 50:
            return 3.0
        elif competitor_vph >= 300:
            return 5.0
        else:
            # Linear interpolation
            for vph, ctr in sorted(self.VPH_TO_CTR_BASELINE.items()):
                if competitor_vph <= vph:
                    prev_vph = max(k for k in self.VPH_TO_CTR_BASELINE.keys() if k < vph)
                    prev_ctr = self.VPH_TO_CTR_BASELINE[prev_vph]
                    ratio = (competitor_vph - prev_vph) / (vph - prev_vph)
                    return prev_ctr + ratio * (ctr - prev_ctr)
            return 5.0

    def compare(
        self,
        our_title: str,
        our_ctr: float,
        competitor_title: str,
        competitor_vph: float,
    ) -> PerformanceComparison:
        """Compare our performance against competitor.

        Args:
            our_title: Our video title
            our_ctr: Our CTR percentage
            competitor_title: Competitor video we modeled
            competitor_vph: Competitor's VPH when we selected them

        Returns:
            PerformanceComparison with verdict
        """
        expected = self.estimate_expected_ctr(competitor_vph)
        delta = our_ctr - expected

        if delta >= 0.5:
            verdict = "outperformed"
            delta_desc = f"+{delta:.1f}% above expected ({expected:.1f}%)"
        elif delta <= -0.5:
            verdict = "underperformed"
            delta_desc = f"{delta:.1f}% below expected ({expected:.1f}%)"
        else:
            verdict = "matched"
            delta_desc = f"~{expected:.1f}% as expected"

        return PerformanceComparison(
            our_title=our_title,
            our_ctr=our_ctr,
            competitor_title=competitor_title,
            competitor_vph=competitor_vph,
            verdict=verdict,
            delta_description=delta_desc,
        )
```

### Tests

- `test_estimate_expected_ctr_low_vph` — VPH 50 → 3.0%
- `test_estimate_expected_ctr_high_vph` — VPH 300 → 5.0%
- `test_estimate_expected_ctr_interpolation` — VPH 125 interpolates correctly
- `test_compare_outperformed` — CTR significantly above expected
- `test_compare_underperformed` — CTR significantly below expected
- `test_compare_matched` — CTR within expected range

### Commit

```bash
git add autopilot/monitoring/performance_comparator.py autopilot/tests/test_performance_comparator.py
git commit -m "feat(autopilot): Add performance comparator for us vs competitor

- VPH to expected CTR mapping
- Verdict classification (outperformed/matched/underperformed)
- 6 tests passing"
```

---

## Task 4: Learning Extractor

**Files:**
- Create: `skills/video-pipeline/autopilot/learning/learning_extractor.py`
- Create: `skills/video-pipeline/autopilot/tests/test_learning_extractor.py`

### Implementation

Extract patterns from 48h+ videos:

```python
"""Extract learnable patterns from video performance."""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

from autopilot.monitoring.early_warning import CTRVerdict, EarlyWarning
from autopilot.monitoring.performance_comparator import PerformanceComparator


@dataclass
class ExtractedLearning:
    """A learning extracted from video performance."""
    category: str  # "thumbnail", "title", "topic"
    pattern: str  # e.g., "red_yellow_color_scheme"
    verdict: CTRVerdict
    confidence: float  # 0-100
    evidence: str  # Human-readable explanation
    video_title: str
    ctr: float


@dataclass
class ExperimentResult:
    """Full result of a video experiment."""
    video_title: str
    date: str
    modeled_from: Optional[str]
    predicted_ctr: Optional[float]
    actual_ctr: float
    verdict: CTRVerdict
    thumbnail_override: Optional[str]
    title_formula: Optional[str]
    learnings: List[ExtractedLearning] = field(default_factory=list)


class LearningExtractor:
    """Extract patterns from video performance."""

    def __init__(self):
        self.early_warning = EarlyWarning()
        self.comparator = PerformanceComparator()

    def extract_thumbnail_learnings(
        self,
        video_title: str,
        ctr: float,
        thumbnail_override: Optional[str],
    ) -> List[ExtractedLearning]:
        """Extract thumbnail-related learnings.

        Args:
            video_title: Video title
            ctr: Actual CTR
            thumbnail_override: The override string used

        Returns:
            List of extracted learnings
        """
        learnings = []
        verdict = self.early_warning.get_verdict(ctr)

        if not thumbnail_override:
            return learnings

        # Parse key elements from override
        override_lower = thumbnail_override.lower()

        # Color patterns
        if "red" in override_lower and "yellow" in override_lower:
            learnings.append(ExtractedLearning(
                category="thumbnail",
                pattern="red_yellow_color_scheme",
                verdict=verdict,
                confidence=60.0 if verdict == CTRVerdict.KEEP else 40.0,
                evidence=f"Red/yellow color scheme used. CTR: {ctr:.1f}%",
                video_title=video_title,
                ctr=ctr,
            ))

        # Composition patterns
        if "face" in override_lower and "left" in override_lower:
            learnings.append(ExtractedLearning(
                category="thumbnail",
                pattern="face_left_composition",
                verdict=verdict,
                confidence=60.0 if verdict == CTRVerdict.KEEP else 40.0,
                evidence=f"Face-left composition used. CTR: {ctr:.1f}%",
                video_title=video_title,
                ctr=ctr,
            ))

        # Text patterns
        if "caps" in override_lower or "bold" in override_lower:
            learnings.append(ExtractedLearning(
                category="thumbnail",
                pattern="bold_caps_text",
                verdict=verdict,
                confidence=60.0 if verdict == CTRVerdict.KEEP else 40.0,
                evidence=f"Bold caps text used. CTR: {ctr:.1f}%",
                video_title=video_title,
                ctr=ctr,
            ))

        return learnings

    def extract_title_learnings(
        self,
        video_title: str,
        ctr: float,
    ) -> List[ExtractedLearning]:
        """Extract title-related learnings.

        Args:
            video_title: The video title
            ctr: Actual CTR

        Returns:
            List of extracted learnings
        """
        learnings = []
        verdict = self.early_warning.get_verdict(ctr)

        # Question pattern
        if video_title.rstrip().endswith("?"):
            learnings.append(ExtractedLearning(
                category="title",
                pattern="question_format",
                verdict=verdict,
                confidence=60.0 if verdict == CTRVerdict.KEEP else 40.0,
                evidence=f"Question format title. CTR: {ctr:.1f}%",
                video_title=video_title,
                ctr=ctr,
            ))

        # Number pattern
        import re
        if re.search(r'\d+', video_title):
            learnings.append(ExtractedLearning(
                category="title",
                pattern="number_in_title",
                verdict=verdict,
                confidence=60.0 if verdict == CTRVerdict.KEEP else 40.0,
                evidence=f"Number in title. CTR: {ctr:.1f}%",
                video_title=video_title,
                ctr=ctr,
            ))

        # Caps emphasis
        if re.search(r'\b[A-Z]{2,}\b', video_title):
            learnings.append(ExtractedLearning(
                category="title",
                pattern="caps_emphasis",
                verdict=verdict,
                confidence=60.0 if verdict == CTRVerdict.KEEP else 40.0,
                evidence=f"Caps emphasis in title. CTR: {ctr:.1f}%",
                video_title=video_title,
                ctr=ctr,
            ))

        return learnings

    def extract_all(
        self,
        video_title: str,
        ctr: float,
        thumbnail_override: Optional[str] = None,
        modeled_from: Optional[str] = None,
    ) -> ExperimentResult:
        """Extract all learnings from a video experiment.

        Args:
            video_title: Video title
            ctr: Actual CTR
            thumbnail_override: Override string used
            modeled_from: Competitor video modeled

        Returns:
            ExperimentResult with all learnings
        """
        verdict = self.early_warning.get_verdict(ctr)

        learnings = []
        learnings.extend(self.extract_thumbnail_learnings(video_title, ctr, thumbnail_override))
        learnings.extend(self.extract_title_learnings(video_title, ctr))

        return ExperimentResult(
            video_title=video_title,
            date=datetime.now().strftime("%Y-%m-%d"),
            modeled_from=modeled_from,
            predicted_ctr=None,  # TODO: Add prediction tracking
            actual_ctr=ctr,
            verdict=verdict,
            thumbnail_override=thumbnail_override,
            title_formula=None,  # TODO: Track formula used
            learnings=learnings,
        )
```

### Tests

- `test_extract_thumbnail_color_pattern` — Extracts red_yellow pattern
- `test_extract_thumbnail_composition_pattern` — Extracts face_left pattern
- `test_extract_title_question_pattern` — Extracts question format
- `test_extract_title_number_pattern` — Extracts number pattern
- `test_verdict_affects_confidence` — KEEP verdict = higher confidence
- `test_extract_all_combines_learnings` — Full extraction combines all patterns

### Commit

```bash
git add autopilot/learning/learning_extractor.py autopilot/tests/test_learning_extractor.py
git commit -m "feat(autopilot): Add learning extractor for pattern discovery

- Extract thumbnail patterns (colors, composition, text)
- Extract title patterns (question, number, caps)
- Verdict-based confidence scoring
- 6 tests passing"
```

---

## Task 5: Memory Writer

**Files:**
- Create: `skills/video-pipeline/autopilot/learning/memory_writer.py`
- Create: `skills/video-pipeline/autopilot/tests/test_memory_writer.py`

### Implementation

Update markdown memory files with extracted learnings:

```python
"""Update markdown memory files with learnings."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from autopilot.learning.learning_extractor import ExperimentResult, ExtractedLearning
from autopilot.monitoring.early_warning import CTRVerdict


class MemoryWriter:
    """Write learnings to markdown memory files."""

    def __init__(self, memory_dir: Optional[Path] = None):
        if memory_dir is None:
            memory_dir = Path(__file__).parent.parent / "memory"
        self.memory_dir = memory_dir

    def append_experiment(self, result: ExperimentResult) -> None:
        """Append experiment to experiments_log.md.

        Args:
            result: ExperimentResult to log
        """
        log_path = self.memory_dir / "experiments_log.md"

        # Count existing experiments
        existing = log_path.read_text() if log_path.exists() else ""
        exp_count = existing.count("## Video #") + 1

        # Format learnings
        learnings_str = ", ".join(l.pattern for l in result.learnings) or "None extracted"

        entry = f"""
## Video #{exp_count}: "{result.video_title}"
- Date: {result.date}
- Modeled: {result.modeled_from or "N/A"}
- Predicted CTR: {result.predicted_ctr or "N/A"}% | Actual: {result.actual_ctr:.1f}%
- Status: {result.verdict.value.upper()}
- Thumbnail override: {result.thumbnail_override or "None"}
- Learnings: {learnings_str}

"""

        with open(log_path, "a") as f:
            f.write(entry)

    def update_thumbnail_patterns(self, learnings: list[ExtractedLearning]) -> None:
        """Update thumbnail_patterns.md with new data.

        Args:
            learnings: Thumbnail learnings to incorporate
        """
        pattern_path = self.memory_dir / "thumbnail_patterns.md"
        content = pattern_path.read_text() if pattern_path.exists() else ""

        for learning in learnings:
            if learning.category != "thumbnail":
                continue

            # For now, just append to notes section
            # TODO: More sophisticated pattern tracking
            note = f"\n- {learning.pattern}: CTR {learning.ctr:.1f}% ({learning.verdict.value}) - {learning.video_title}"

            if "## Notes" in content:
                content = content.replace("## Notes", f"## Notes{note}")
            else:
                content += f"\n## Notes{note}\n"

        pattern_path.write_text(content)

    def update_title_patterns(self, learnings: list[ExtractedLearning]) -> None:
        """Update title_patterns.md with new data.

        Args:
            learnings: Title learnings to incorporate
        """
        pattern_path = self.memory_dir / "title_patterns.md"
        content = pattern_path.read_text() if pattern_path.exists() else ""

        for learning in learnings:
            if learning.category != "title":
                continue

            note = f"\n- {learning.pattern}: CTR {learning.ctr:.1f}% ({learning.verdict.value}) - {learning.video_title}"

            if "## Notes" in content:
                content = content.replace("## Notes", f"## Notes{note}")
            else:
                content += f"\n## Notes{note}\n"

        pattern_path.write_text(content)

    def update_learnings_summary(
        self,
        videos_produced: int,
        avg_ctr: float,
        best_ctr: float,
        best_title: str,
    ) -> None:
        """Update LEARNINGS.md summary header.

        Args:
            videos_produced: Total videos
            avg_ctr: Average CTR
            best_ctr: Best CTR achieved
            best_title: Title with best CTR
        """
        path = self.memory_dir / "LEARNINGS.md"
        content = path.read_text() if path.exists() else ""

        # Update header fields
        today = datetime.now().strftime("%Y-%m-%d")

        new_header = f"""# Autopilot Learnings

Last updated: {today}
Videos produced: {videos_produced}
Avg CTR: {avg_ctr:.1f}%
Best CTR: {best_ctr:.1f}% ("{best_title}")
"""

        # Replace header section
        if "# Autopilot Learnings" in content:
            # Find end of header (next ## or ---)
            lines = content.split("\n")
            header_end = 0
            for i, line in enumerate(lines):
                if i > 0 and (line.startswith("## ") or line.startswith("---")):
                    header_end = i
                    break
            content = new_header + "\n".join(lines[header_end:])
        else:
            content = new_header + content

        path.write_text(content)

    def process_result(self, result: ExperimentResult) -> None:
        """Process a full experiment result and update all memory files.

        Args:
            result: ExperimentResult to process
        """
        # Log the experiment
        self.append_experiment(result)

        # Update pattern files
        thumbnail_learnings = [l for l in result.learnings if l.category == "thumbnail"]
        title_learnings = [l for l in result.learnings if l.category == "title"]

        if thumbnail_learnings:
            self.update_thumbnail_patterns(thumbnail_learnings)
        if title_learnings:
            self.update_title_patterns(title_learnings)
```

### Tests

- `test_append_experiment` — Adds entry to experiments_log.md
- `test_append_increments_number` — Video numbers increment correctly
- `test_update_thumbnail_patterns` — Adds to thumbnail notes
- `test_update_title_patterns` — Adds to title notes
- `test_update_learnings_summary` — Updates header stats
- `test_process_result_updates_all` — Full flow updates all files

### Commit

```bash
git add autopilot/learning/memory_writer.py autopilot/tests/test_memory_writer.py
git commit -m "feat(autopilot): Add memory writer for pattern persistence

- Append experiments to log
- Update thumbnail/title pattern files
- Update LEARNINGS.md summary
- 6 tests passing"
```

---

## Task 6: Integration + CLI

Wire up the monitoring and learning modules into a CLI for cron execution.

### Update autopilot.py

Add monitoring integration:

```python
# In check_cycle(), after production:
# ... existing code ...

# Update state to start monitoring
self.state_manager.record_production_cycle(
    video_title=best.candidate.title,
    modeled_from=best.candidate.competitor_title,
    thumbnail_override=thumbnail_override,
)
```

### Create CLI for CTR monitoring

```bash
python -m autopilot.monitoring.ctr_monitor --check-active
```

### Run all tests

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/ -v
```

Expected: 90+ tests passing (60 existing + 30+ new)

### Commit

```bash
git add autopilot/
git commit -m "feat(autopilot): Complete Chunk 3 - CTR monitoring + learning loop

Monitoring:
- CTR monitor with 6h/24h/48h milestones
- Early warning system (CRITICAL/WARNING/NORMAL/STRONG)
- Performance comparator (us vs competitor)

Learning:
- Learning extractor for thumbnail/title patterns
- Memory writer for pattern persistence
- Experiment logging

90+ tests passing. Ready for production."
```

---

## Chunk 3 Complete

**Deliverables:**
- `autopilot/monitoring/early_warning.py` — Alert classification
- `autopilot/monitoring/ctr_monitor.py` — Milestone CTR checks
- `autopilot/monitoring/performance_comparator.py` — Us vs competitor
- `autopilot/learning/learning_extractor.py` — Pattern extraction
- `autopilot/learning/memory_writer.py` — Memory file updates
- 30+ new tests

**Test Command:**
```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/ -v
```

**Cron Commands (to add to setup_cron.sh):**
```bash
# CTR monitoring - every 2 hours
0 */2 * * * cd /path && python -m autopilot.monitoring.ctr_monitor --check-active

# Learning extraction - daily at 8:30 AM PT
30 8 * * * cd /path && python -m autopilot.learning.learning_extractor --daily
```

**Next:** Integration testing + cron setup
