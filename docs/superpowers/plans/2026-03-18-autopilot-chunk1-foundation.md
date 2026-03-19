# Autopilot Brain - Chunk 1: Foundation + Decision Engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get the autopilot loop running — reads config, checks cadence, scores ideas, picks best, notifies Slack.

**Architecture:** New `autopilot/` module as a layer above existing pipeline. Reads `autopilot_program.md` for config, `autopilot_state.json` for runtime state. Scores ideas from Competitor Videos table using weighted signals. Notifies Slack with reasoning.

**Tech Stack:** Python 3.11+, async, pyairtable, slack_sdk, pydantic for config parsing.

**Related Spec:** `docs/superpowers/specs/2026-03-18-autopilot-brain-design.md`

---

## File Structure (Chunk 1)

```
skills/video-pipeline/
├── autopilot/
│   ├── __init__.py
│   ├── autopilot.py              # Main loop entry point
│   ├── autopilot_program.md      # Human-editable config
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config_parser.py      # Parse autopilot_program.md → pydantic model
│   │   ├── state_manager.py      # Read/write autopilot_state.json
│   │   ├── cadence_manager.py    # Check if production slot available
│   │   ├── confidence_scorer.py  # Weighted idea ranking
│   │   └── notifier.py           # Slack notifications with reasoning
│   │
│   ├── state/
│   │   └── autopilot_state.json  # Runtime state (gitignored)
│   │
│   └── tests/
│       ├── __init__.py
│       ├── test_config_parser.py
│       ├── test_state_manager.py
│       ├── test_cadence_manager.py
│       ├── test_confidence_scorer.py
│       └── test_notifier.py
```

---

## Task 1: Create Module Structure + Config Parser

**Files:**
- Create: `skills/video-pipeline/autopilot/__init__.py`
- Create: `skills/video-pipeline/autopilot/core/__init__.py`
- Create: `skills/video-pipeline/autopilot/core/config_parser.py`
- Create: `skills/video-pipeline/autopilot/tests/__init__.py`
- Create: `skills/video-pipeline/autopilot/tests/test_config_parser.py`

### Step 1: Create directory structure

- [ ] **Create directories**

```bash
mkdir -p skills/video-pipeline/autopilot/core
mkdir -p skills/video-pipeline/autopilot/state
mkdir -p skills/video-pipeline/autopilot/tests
touch skills/video-pipeline/autopilot/__init__.py
touch skills/video-pipeline/autopilot/core/__init__.py
touch skills/video-pipeline/autopilot/tests/__init__.py
```

### Step 2: Write failing test for config parser

- [ ] **Write test_config_parser.py**

```python
# skills/video-pipeline/autopilot/tests/test_config_parser.py
"""Tests for autopilot config parser."""

import pytest
from pathlib import Path
from autopilot.core.config_parser import AutopilotConfig, parse_config


SAMPLE_CONFIG = """# Autopilot Program

## Mission

Your mission: **Maximize click-through rate for this YouTube channel.**

---

## Cadence

videos_per_month: 15
production_interval_days: 2

---

## Confidence Scoring Weights

weights:
  competitor_vph: 0.30
  topic_channel_fit: 0.25
  timing_freshness: 0.20
  channel_momentum: 0.10
  retention_patterns: 0.08
  title_formula: 0.07

---

## Thresholds

thresholds:
  min_confidence_score: 60
  min_competitor_vph: 50
  max_idea_age_days: 7
  ctr_success_threshold: 4.0
  ctr_failure_threshold: 2.5
  early_warning_hours: 6
"""


class TestConfigParser:
    """Test suite for config parsing."""

    def test_parse_cadence(self):
        """Should extract cadence settings."""
        config = parse_config(SAMPLE_CONFIG)
        assert config.videos_per_month == 15
        assert config.production_interval_days == 2

    def test_parse_weights(self):
        """Should extract confidence scoring weights."""
        config = parse_config(SAMPLE_CONFIG)
        assert config.weights.competitor_vph == 0.30
        assert config.weights.topic_channel_fit == 0.25
        assert config.weights.timing_freshness == 0.20
        assert config.weights.channel_momentum == 0.10
        assert config.weights.retention_patterns == 0.08
        assert config.weights.title_formula == 0.07

    def test_weights_sum_to_one(self):
        """Weights should sum to 1.0."""
        config = parse_config(SAMPLE_CONFIG)
        total = (
            config.weights.competitor_vph +
            config.weights.topic_channel_fit +
            config.weights.timing_freshness +
            config.weights.channel_momentum +
            config.weights.retention_patterns +
            config.weights.title_formula
        )
        assert abs(total - 1.0) < 0.01

    def test_parse_thresholds(self):
        """Should extract threshold settings."""
        config = parse_config(SAMPLE_CONFIG)
        assert config.thresholds.min_confidence_score == 60
        assert config.thresholds.min_competitor_vph == 50
        assert config.thresholds.max_idea_age_days == 7
        assert config.thresholds.ctr_success_threshold == 4.0
        assert config.thresholds.ctr_failure_threshold == 2.5
        assert config.thresholds.early_warning_hours == 6
```

### Step 3: Run test to verify it fails

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_config_parser.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'autopilot.core.config_parser'`

### Step 4: Implement config parser

- [ ] **Write config_parser.py**

```python
# skills/video-pipeline/autopilot/core/config_parser.py
"""Parse autopilot_program.md into typed configuration."""

import re
from pathlib import Path
from pydantic import BaseModel, field_validator
from typing import Optional


class WeightsConfig(BaseModel):
    """Confidence scoring weights (must sum to 1.0)."""
    competitor_vph: float = 0.30
    topic_channel_fit: float = 0.25
    timing_freshness: float = 0.20
    channel_momentum: float = 0.10
    retention_patterns: float = 0.08
    title_formula: float = 0.07

    @field_validator('*', mode='before')
    @classmethod
    def coerce_float(cls, v):
        return float(v) if v is not None else 0.0


class ThresholdsConfig(BaseModel):
    """Decision thresholds."""
    min_confidence_score: int = 60
    min_competitor_vph: int = 50
    max_idea_age_days: int = 7
    ctr_success_threshold: float = 4.0
    ctr_failure_threshold: float = 2.5
    early_warning_hours: int = 6


class AutopilotConfig(BaseModel):
    """Full autopilot configuration."""
    videos_per_month: int = 15
    production_interval_days: int = 2
    weights: WeightsConfig = WeightsConfig()
    thresholds: ThresholdsConfig = ThresholdsConfig()


def _extract_yaml_block(content: str, section_name: str) -> dict:
    """Extract key-value pairs from a markdown section.

    Handles both flat and nested YAML-style blocks.
    """
    # Find section
    pattern = rf"##\s+{re.escape(section_name)}\s*\n(.*?)(?=\n##|\Z)"
    match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
    if not match:
        return {}

    section_content = match.group(1)
    result = {}
    current_nested = None
    nested_dict = {}

    for line in section_content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('---'):
            continue

        # Check for nested block start (e.g., "weights:")
        if line.endswith(':') and ':' not in line[:-1]:
            if current_nested and nested_dict:
                result[current_nested] = nested_dict
            current_nested = line[:-1].strip()
            nested_dict = {}
            continue

        # Parse key: value
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()

            # Try to parse as number
            try:
                if '.' in value:
                    value = float(value)
                else:
                    value = int(value)
            except ValueError:
                pass

            if current_nested:
                nested_dict[key] = value
            else:
                result[key] = value

    # Don't forget last nested block
    if current_nested and nested_dict:
        result[current_nested] = nested_dict

    return result


def parse_config(content: str) -> AutopilotConfig:
    """Parse autopilot_program.md content into config object.

    Args:
        content: Raw markdown content of autopilot_program.md

    Returns:
        AutopilotConfig with all settings
    """
    # Extract sections
    cadence = _extract_yaml_block(content, "Cadence")
    weights_section = _extract_yaml_block(content, "Confidence Scoring Weights")
    thresholds_section = _extract_yaml_block(content, "Thresholds")

    # Build config
    weights_data = weights_section.get("weights", {})
    thresholds_data = thresholds_section.get("thresholds", {})

    return AutopilotConfig(
        videos_per_month=cadence.get("videos_per_month", 15),
        production_interval_days=cadence.get("production_interval_days", 2),
        weights=WeightsConfig(**weights_data) if weights_data else WeightsConfig(),
        thresholds=ThresholdsConfig(**thresholds_data) if thresholds_data else ThresholdsConfig(),
    )


def load_config(config_path: Optional[Path] = None) -> AutopilotConfig:
    """Load config from autopilot_program.md file.

    Args:
        config_path: Path to config file. Defaults to autopilot/autopilot_program.md

    Returns:
        AutopilotConfig
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent / "autopilot_program.md"

    if not config_path.exists():
        # Return defaults if no config file
        return AutopilotConfig()

    content = config_path.read_text()
    return parse_config(content)
```

### Step 5: Run tests to verify they pass

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_config_parser.py -v
```

Expected: All 4 tests PASS

### Step 6: Commit

- [ ] **Commit**

```bash
cd skills/video-pipeline && git add autopilot/ && git commit -m "feat(autopilot): Add config parser for autopilot_program.md

- Parse cadence, weights, thresholds from markdown
- Pydantic models for type safety
- 4 tests passing"
```

---

## Task 2: State Manager

**Files:**
- Create: `skills/video-pipeline/autopilot/core/state_manager.py`
- Create: `skills/video-pipeline/autopilot/tests/test_state_manager.py`

### Step 1: Write failing test

- [ ] **Write test_state_manager.py**

```python
# skills/video-pipeline/autopilot/tests/test_state_manager.py
"""Tests for autopilot state manager."""

import pytest
import json
from pathlib import Path
from datetime import datetime, timezone
from autopilot.core.state_manager import (
    AutopilotState,
    StateManager,
    ExperimentState,
)


class TestStateManager:
    """Test suite for state management."""

    @pytest.fixture
    def temp_state_file(self, tmp_path):
        """Create a temporary state file path."""
        return tmp_path / "autopilot_state.json"

    def test_default_state(self, temp_state_file):
        """Should return default state when file doesn't exist."""
        manager = StateManager(state_path=temp_state_file)
        state = manager.load()

        assert state.autopilot_enabled is True
        assert state.videos_produced == 0
        assert state.channel_avg_ctr == 0.0
        assert state.current_experiment is None

    def test_save_and_load(self, temp_state_file):
        """Should persist state to file."""
        manager = StateManager(state_path=temp_state_file)

        state = AutopilotState(
            autopilot_enabled=True,
            last_cycle="2026-03-18T09:00:00Z",
            videos_produced=5,
            channel_avg_ctr=4.2,
        )
        manager.save(state)

        # Reload
        loaded = manager.load()
        assert loaded.videos_produced == 5
        assert loaded.channel_avg_ctr == 4.2
        assert loaded.last_cycle == "2026-03-18T09:00:00Z"

    def test_update_after_production(self, temp_state_file):
        """Should update state after video production."""
        manager = StateManager(state_path=temp_state_file)

        initial = manager.load()
        manager.record_production_cycle("Test Video Title")

        updated = manager.load()
        assert updated.videos_produced == initial.videos_produced + 1
        assert updated.last_cycle is not None
        assert updated.current_experiment is not None
        assert updated.current_experiment.video_title == "Test Video Title"

    def test_is_enabled(self, temp_state_file):
        """Should check enabled state."""
        manager = StateManager(state_path=temp_state_file)
        assert manager.is_enabled() is True

        state = manager.load()
        state.autopilot_enabled = False
        manager.save(state)

        assert manager.is_enabled() is False
```

### Step 2: Run test to verify it fails

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_state_manager.py -v
```

Expected: FAIL with `ModuleNotFoundError`

### Step 3: Implement state manager

- [ ] **Write state_manager.py**

```python
# skills/video-pipeline/autopilot/core/state_manager.py
"""Manage autopilot runtime state (autopilot_state.json)."""

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List
from pydantic import BaseModel


class HypothesisState(BaseModel):
    """Active hypothesis being tested."""
    pattern: str
    videos_remaining: int


class ExperimentState(BaseModel):
    """Current experiment (video in production/monitoring)."""
    video_title: str
    status: str = "producing"  # producing, monitoring, complete
    publish_date: Optional[str] = None
    modeled_from: Optional[str] = None
    thumbnail_override: Optional[str] = None


class AutopilotState(BaseModel):
    """Runtime state for autopilot."""
    autopilot_enabled: bool = True
    last_cycle: Optional[str] = None
    videos_produced: int = 0
    channel_avg_ctr: float = 0.0
    current_experiment: Optional[ExperimentState] = None
    active_hypotheses: List[HypothesisState] = []


class StateManager:
    """Manage autopilot_state.json file."""

    def __init__(self, state_path: Optional[Path] = None):
        """Initialize state manager.

        Args:
            state_path: Path to state file. Defaults to autopilot/state/autopilot_state.json
        """
        if state_path is None:
            state_path = Path(__file__).parent.parent / "state" / "autopilot_state.json"
        self.state_path = state_path

        # Ensure directory exists
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AutopilotState:
        """Load state from file.

        Returns:
            AutopilotState (defaults if file doesn't exist)
        """
        if not self.state_path.exists():
            return AutopilotState()

        try:
            content = self.state_path.read_text()
            data = json.loads(content)
            return AutopilotState(**data)
        except (json.JSONDecodeError, Exception) as e:
            print(f"Warning: Could not load state file: {e}")
            return AutopilotState()

    def save(self, state: AutopilotState) -> None:
        """Save state to file.

        Args:
            state: State to persist
        """
        content = state.model_dump_json(indent=2)
        self.state_path.write_text(content)

    def is_enabled(self) -> bool:
        """Check if autopilot is enabled.

        Returns:
            True if enabled
        """
        return self.load().autopilot_enabled

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable autopilot.

        Args:
            enabled: New enabled state
        """
        state = self.load()
        state.autopilot_enabled = enabled
        self.save(state)

    def record_production_cycle(
        self,
        video_title: str,
        modeled_from: Optional[str] = None,
        thumbnail_override: Optional[str] = None,
    ) -> None:
        """Record that a production cycle started.

        Args:
            video_title: Title of video being produced
            modeled_from: Competitor video this models (optional)
            thumbnail_override: Thumbnail override used (optional)
        """
        state = self.load()
        state.videos_produced += 1
        state.last_cycle = datetime.now(timezone.utc).isoformat()
        state.current_experiment = ExperimentState(
            video_title=video_title,
            status="producing",
            modeled_from=modeled_from,
            thumbnail_override=thumbnail_override,
        )
        self.save(state)

    def get_last_cycle_datetime(self) -> Optional[datetime]:
        """Get datetime of last production cycle.

        Returns:
            datetime or None if never run
        """
        state = self.load()
        if state.last_cycle is None:
            return None
        return datetime.fromisoformat(state.last_cycle.replace('Z', '+00:00'))
```

### Step 4: Run tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_state_manager.py -v
```

Expected: All 4 tests PASS

### Step 5: Commit

- [ ] **Commit**

```bash
cd skills/video-pipeline && git add autopilot/ && git commit -m "feat(autopilot): Add state manager for runtime persistence

- AutopilotState pydantic model
- Save/load to autopilot_state.json
- Record production cycles
- 4 tests passing"
```

---

## Task 3: Cadence Manager

**Files:**
- Create: `skills/video-pipeline/autopilot/core/cadence_manager.py`
- Create: `skills/video-pipeline/autopilot/tests/test_cadence_manager.py`

### Step 1: Write failing test

- [ ] **Write test_cadence_manager.py**

```python
# skills/video-pipeline/autopilot/tests/test_cadence_manager.py
"""Tests for cadence manager."""

import pytest
from datetime import datetime, timezone, timedelta
from autopilot.core.cadence_manager import CadenceManager
from autopilot.core.config_parser import AutopilotConfig
from autopilot.core.state_manager import AutopilotState


class TestCadenceManager:
    """Test suite for cadence management."""

    def test_first_run_is_ready(self):
        """Should be ready on first run (no previous cycle)."""
        config = AutopilotConfig(videos_per_month=15, production_interval_days=2)
        state = AutopilotState(last_cycle=None)

        manager = CadenceManager(config, state)
        assert manager.is_production_slot_available() is True

    def test_too_soon(self):
        """Should not be ready if last cycle was too recent."""
        config = AutopilotConfig(videos_per_month=15, production_interval_days=2)

        # Last cycle was 1 day ago (need 2 days)
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        state = AutopilotState(last_cycle=yesterday.isoformat())

        manager = CadenceManager(config, state)
        assert manager.is_production_slot_available() is False

    def test_ready_after_interval(self):
        """Should be ready after interval passes."""
        config = AutopilotConfig(videos_per_month=15, production_interval_days=2)

        # Last cycle was 3 days ago (need 2 days)
        three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
        state = AutopilotState(last_cycle=three_days_ago.isoformat())

        manager = CadenceManager(config, state)
        assert manager.is_production_slot_available() is True

    def test_next_production_date(self):
        """Should calculate next production date."""
        config = AutopilotConfig(videos_per_month=15, production_interval_days=2)

        last = datetime.now(timezone.utc) - timedelta(days=1)
        state = AutopilotState(last_cycle=last.isoformat())

        manager = CadenceManager(config, state)
        next_date = manager.get_next_production_date()

        # Should be last_cycle + 2 days
        expected = last + timedelta(days=2)
        assert abs((next_date - expected).total_seconds()) < 1

    def test_days_until_next(self):
        """Should calculate days until next production."""
        config = AutopilotConfig(videos_per_month=15, production_interval_days=2)

        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        state = AutopilotState(last_cycle=yesterday.isoformat())

        manager = CadenceManager(config, state)
        days = manager.days_until_next()

        # 1 day until next (interval=2, elapsed=1)
        assert days == 1
```

### Step 2: Run test to verify it fails

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_cadence_manager.py -v
```

Expected: FAIL with `ModuleNotFoundError`

### Step 3: Implement cadence manager

- [ ] **Write cadence_manager.py**

```python
# skills/video-pipeline/autopilot/core/cadence_manager.py
"""Manage production cadence (videos per month)."""

from datetime import datetime, timezone, timedelta
from typing import Optional
from autopilot.core.config_parser import AutopilotConfig
from autopilot.core.state_manager import AutopilotState


class CadenceManager:
    """Check if it's time to produce the next video."""

    def __init__(self, config: AutopilotConfig, state: AutopilotState):
        """Initialize cadence manager.

        Args:
            config: Autopilot configuration
            state: Current autopilot state
        """
        self.config = config
        self.state = state
        self._last_cycle = self._parse_last_cycle()

    def _parse_last_cycle(self) -> Optional[datetime]:
        """Parse last_cycle string to datetime."""
        if self.state.last_cycle is None:
            return None
        try:
            return datetime.fromisoformat(
                self.state.last_cycle.replace('Z', '+00:00')
            )
        except ValueError:
            return None

    def is_production_slot_available(self) -> bool:
        """Check if enough time has passed since last production.

        Returns:
            True if ready to produce next video
        """
        if self._last_cycle is None:
            # Never run before - ready to go
            return True

        elapsed = datetime.now(timezone.utc) - self._last_cycle
        required = timedelta(days=self.config.production_interval_days)

        return elapsed >= required

    def get_next_production_date(self) -> datetime:
        """Calculate when next production should occur.

        Returns:
            datetime of next production slot
        """
        if self._last_cycle is None:
            return datetime.now(timezone.utc)

        return self._last_cycle + timedelta(days=self.config.production_interval_days)

    def days_until_next(self) -> int:
        """Calculate days until next production slot.

        Returns:
            Number of days (0 = ready now, negative = overdue)
        """
        if self._last_cycle is None:
            return 0

        next_date = self.get_next_production_date()
        delta = next_date - datetime.now(timezone.utc)

        return max(0, int(delta.total_seconds() / 86400))
```

### Step 4: Run tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_cadence_manager.py -v
```

Expected: All 5 tests PASS

### Step 5: Commit

- [ ] **Commit**

```bash
cd skills/video-pipeline && git add autopilot/ && git commit -m "feat(autopilot): Add cadence manager for production scheduling

- Check if production slot available
- Calculate next production date
- 5 tests passing"
```

---

## Task 4: Confidence Scorer

**Files:**
- Create: `skills/video-pipeline/autopilot/core/confidence_scorer.py`
- Create: `skills/video-pipeline/autopilot/tests/test_confidence_scorer.py`

### Step 1: Write failing test

- [ ] **Write test_confidence_scorer.py**

```python
# skills/video-pipeline/autopilot/tests/test_confidence_scorer.py
"""Tests for confidence scorer."""

import pytest
from datetime import datetime, timezone, timedelta
from autopilot.core.confidence_scorer import (
    ConfidenceScorer,
    IdeaCandidate,
    ScoredIdea,
)
from autopilot.core.config_parser import AutopilotConfig, WeightsConfig


class TestConfidenceScorer:
    """Test suite for confidence scoring."""

    @pytest.fixture
    def config(self):
        return AutopilotConfig()

    @pytest.fixture
    def scorer(self, config):
        return ConfidenceScorer(config)

    def test_score_single_idea(self, scorer):
        """Should score an idea based on weighted signals."""
        candidate = IdeaCandidate(
            record_id="rec123",
            title="China's $3T Dollar Trap",
            source_type="competitor",
            competitor_vph=150.0,
            competitor_title="China's Economic Collapse",
            hours_old=24,
        )

        scored = scorer.score(candidate)

        assert scored.score > 0
        assert scored.score <= 100
        assert scored.candidate == candidate
        assert len(scored.reasoning) > 0

    def test_higher_vph_scores_higher(self, scorer):
        """Ideas from higher VPH competitors should score higher."""
        low_vph = IdeaCandidate(
            record_id="rec1",
            title="Low VPH Idea",
            source_type="competitor",
            competitor_vph=20.0,
            hours_old=24,
        )
        high_vph = IdeaCandidate(
            record_id="rec2",
            title="High VPH Idea",
            source_type="competitor",
            competitor_vph=200.0,
            hours_old=24,
        )

        low_score = scorer.score(low_vph)
        high_score = scorer.score(high_vph)

        assert high_score.score > low_score.score

    def test_fresher_ideas_score_higher(self, scorer):
        """Fresher ideas should score higher."""
        old = IdeaCandidate(
            record_id="rec1",
            title="Old Idea",
            source_type="competitor",
            competitor_vph=100.0,
            hours_old=168,  # 7 days
        )
        fresh = IdeaCandidate(
            record_id="rec2",
            title="Fresh Idea",
            source_type="competitor",
            competitor_vph=100.0,
            hours_old=12,  # 12 hours
        )

        old_score = scorer.score(old)
        fresh_score = scorer.score(fresh)

        assert fresh_score.score > old_score.score

    def test_rank_candidates(self, scorer):
        """Should rank candidates by score descending."""
        candidates = [
            IdeaCandidate(record_id="low", title="Low", source_type="competitor", competitor_vph=20.0, hours_old=72),
            IdeaCandidate(record_id="high", title="High", source_type="competitor", competitor_vph=200.0, hours_old=12),
            IdeaCandidate(record_id="mid", title="Mid", source_type="competitor", competitor_vph=100.0, hours_old=24),
        ]

        ranked = scorer.rank(candidates)

        assert len(ranked) == 3
        assert ranked[0].candidate.record_id == "high"
        assert ranked[0].score > ranked[1].score > ranked[2].score

    def test_filter_by_threshold(self, scorer):
        """Should filter out ideas below min_confidence_score."""
        candidates = [
            IdeaCandidate(record_id="good", title="Good", source_type="competitor", competitor_vph=150.0, hours_old=12),
            IdeaCandidate(record_id="bad", title="Bad", source_type="competitor", competitor_vph=10.0, hours_old=168),
        ]

        ranked = scorer.rank(candidates, min_score=50)

        # Only good idea should pass threshold
        assert all(s.score >= 50 for s in ranked)
```

### Step 2: Run test to verify it fails

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_confidence_scorer.py -v
```

Expected: FAIL with `ModuleNotFoundError`

### Step 3: Implement confidence scorer

- [ ] **Write confidence_scorer.py**

```python
# skills/video-pipeline/autopilot/core/confidence_scorer.py
"""Score idea candidates using weighted signals."""

from dataclasses import dataclass, field
from typing import List, Optional
from autopilot.core.config_parser import AutopilotConfig


@dataclass
class IdeaCandidate:
    """A potential video idea to score."""
    record_id: str
    title: str
    source_type: str  # "competitor" or "discovery"
    competitor_vph: float = 0.0
    competitor_title: Optional[str] = None
    hours_old: float = 0.0
    topic: Optional[str] = None
    # Future: topic_fit_score, retention_history, etc.


@dataclass
class ScoredIdea:
    """An idea with its confidence score and reasoning."""
    candidate: IdeaCandidate
    score: float  # 0-100
    reasoning: List[str] = field(default_factory=list)
    component_scores: dict = field(default_factory=dict)


class ConfidenceScorer:
    """Score ideas using weighted signals from config."""

    # Normalization constants
    MAX_VPH = 500.0  # VPH above this gets max score
    MAX_HOURS = 168.0  # 7 days - older than this gets 0 freshness

    def __init__(self, config: AutopilotConfig):
        """Initialize scorer with config weights.

        Args:
            config: Autopilot configuration with weights
        """
        self.config = config
        self.weights = config.weights

    def _score_vph(self, vph: float) -> float:
        """Score based on competitor VPH (0-100).

        Higher VPH = more proven appeal.
        """
        if vph <= 0:
            return 0.0
        # Log scale to handle wide range
        import math
        # VPH 50 = 50, VPH 200 = 75, VPH 500 = 100
        normalized = min(1.0, math.log10(max(1, vph)) / math.log10(self.MAX_VPH))
        return normalized * 100

    def _score_freshness(self, hours_old: float) -> float:
        """Score based on idea freshness (0-100).

        Fresher = more timely.
        """
        if hours_old <= 0:
            return 100.0
        if hours_old >= self.MAX_HOURS:
            return 0.0
        # Linear decay
        return (1 - hours_old / self.MAX_HOURS) * 100

    def _score_topic_fit(self, topic: Optional[str]) -> float:
        """Score based on topic fit for our channel (0-100).

        TODO: Cross-reference with topic_performance.md
        For now, return neutral score.
        """
        # Placeholder - will be enhanced in Chunk 2 with memory
        return 50.0

    def _score_channel_momentum(self, competitor_title: Optional[str]) -> float:
        """Score based on competitor channel momentum (0-100).

        TODO: Track competitor channel trends over time
        For now, return neutral score.
        """
        # Placeholder
        return 50.0

    def _score_retention_patterns(self, topic: Optional[str]) -> float:
        """Score based on our retention on similar topics (0-100).

        TODO: Cross-reference with script_forensics.md (V2)
        For now, return neutral score.
        """
        # Placeholder
        return 50.0

    def _score_title_formula(self, title: str) -> float:
        """Score based on title formula patterns (0-100).

        TODO: Cross-reference with title_patterns.md
        For now, return neutral score.
        """
        # Placeholder
        return 50.0

    def score(self, candidate: IdeaCandidate) -> ScoredIdea:
        """Calculate confidence score for a candidate idea.

        Args:
            candidate: Idea to score

        Returns:
            ScoredIdea with score and reasoning
        """
        reasoning = []
        components = {}

        # Score each component
        vph_score = self._score_vph(candidate.competitor_vph)
        components['competitor_vph'] = vph_score
        reasoning.append(f"VPH {candidate.competitor_vph:.0f} → {vph_score:.0f}/100")

        freshness_score = self._score_freshness(candidate.hours_old)
        components['timing_freshness'] = freshness_score
        reasoning.append(f"Age {candidate.hours_old:.0f}h → {freshness_score:.0f}/100")

        topic_fit_score = self._score_topic_fit(candidate.topic)
        components['topic_channel_fit'] = topic_fit_score

        momentum_score = self._score_channel_momentum(candidate.competitor_title)
        components['channel_momentum'] = momentum_score

        retention_score = self._score_retention_patterns(candidate.topic)
        components['retention_patterns'] = retention_score

        title_score = self._score_title_formula(candidate.title)
        components['title_formula'] = title_score

        # Calculate weighted sum
        total_score = (
            vph_score * self.weights.competitor_vph +
            freshness_score * self.weights.timing_freshness +
            topic_fit_score * self.weights.topic_channel_fit +
            momentum_score * self.weights.channel_momentum +
            retention_score * self.weights.retention_patterns +
            title_score * self.weights.title_formula
        )

        return ScoredIdea(
            candidate=candidate,
            score=total_score,
            reasoning=reasoning,
            component_scores=components,
        )

    def rank(
        self,
        candidates: List[IdeaCandidate],
        min_score: Optional[float] = None,
    ) -> List[ScoredIdea]:
        """Score and rank candidates.

        Args:
            candidates: Ideas to rank
            min_score: Filter out ideas below this score (optional)

        Returns:
            Scored ideas sorted by score descending
        """
        scored = [self.score(c) for c in candidates]

        if min_score is not None:
            scored = [s for s in scored if s.score >= min_score]

        return sorted(scored, key=lambda s: s.score, reverse=True)

    def get_best(
        self,
        candidates: List[IdeaCandidate],
    ) -> Optional[ScoredIdea]:
        """Get the highest-scoring candidate.

        Args:
            candidates: Ideas to evaluate

        Returns:
            Best idea or None if none pass threshold
        """
        min_score = self.config.thresholds.min_confidence_score
        ranked = self.rank(candidates, min_score=min_score)
        return ranked[0] if ranked else None
```

### Step 4: Run tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_confidence_scorer.py -v
```

Expected: All 5 tests PASS

### Step 5: Commit

- [ ] **Commit**

```bash
cd skills/video-pipeline && git add autopilot/ && git commit -m "feat(autopilot): Add confidence scorer with weighted signals

- Score VPH, freshness, topic fit, momentum
- Rank and filter by threshold
- Placeholder hooks for memory integration (Chunk 2)
- 5 tests passing"
```

---

## Task 5: Notifier (Slack)

**Files:**
- Create: `skills/video-pipeline/autopilot/core/notifier.py`
- Create: `skills/video-pipeline/autopilot/tests/test_notifier.py`

### Step 1: Write failing test

- [ ] **Write test_notifier.py**

```python
# skills/video-pipeline/autopilot/tests/test_notifier.py
"""Tests for autopilot notifier."""

import pytest
from unittest.mock import Mock, patch
from autopilot.core.notifier import AutopilotNotifier
from autopilot.core.confidence_scorer import IdeaCandidate, ScoredIdea


class TestNotifier:
    """Test suite for Slack notifications."""

    @pytest.fixture
    def mock_slack(self):
        return Mock()

    @pytest.fixture
    def notifier(self, mock_slack):
        return AutopilotNotifier(slack_client=mock_slack)

    @pytest.fixture
    def scored_idea(self):
        candidate = IdeaCandidate(
            record_id="rec123",
            title="China's $3T Dollar Trap",
            source_type="competitor",
            competitor_vph=150.0,
            competitor_title="China's Economic Collapse",
            hours_old=24,
        )
        return ScoredIdea(
            candidate=candidate,
            score=78.5,
            reasoning=["VPH 150 → 72/100", "Age 24h → 86/100"],
            component_scores={
                "competitor_vph": 72,
                "timing_freshness": 86,
                "topic_channel_fit": 50,
            },
        )

    def test_notify_production_start(self, notifier, mock_slack, scored_idea):
        """Should send formatted production start message."""
        notifier.notify_production_start(scored_idea)

        mock_slack.send_message.assert_called_once()
        message = mock_slack.send_message.call_args[0][0]

        assert "AUTOPILOT" in message
        assert "China's $3T Dollar Trap" in message
        assert "78" in message  # score
        assert "China's Economic Collapse" in message  # modeled from

    def test_notify_not_ready(self, notifier, mock_slack):
        """Should send not ready message with next date."""
        notifier.notify_not_ready(days_until=2, next_date="2026-03-20")

        mock_slack.send_message.assert_called_once()
        message = mock_slack.send_message.call_args[0][0]

        assert "not time" in message.lower() or "2 days" in message.lower()

    def test_notify_no_candidates(self, notifier, mock_slack):
        """Should notify when no candidates meet threshold."""
        notifier.notify_no_candidates(threshold=60, best_score=45)

        mock_slack.send_message.assert_called_once()
        message = mock_slack.send_message.call_args[0][0]

        assert "no candidates" in message.lower() or "threshold" in message.lower()

    def test_format_reasoning(self, notifier, scored_idea):
        """Should format reasoning as bullet list."""
        formatted = notifier._format_reasoning(scored_idea)

        assert "VPH" in formatted
        assert "•" in formatted or "-" in formatted
```

### Step 2: Run test to verify it fails

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_notifier.py -v
```

Expected: FAIL with `ModuleNotFoundError`

### Step 3: Implement notifier

- [ ] **Write notifier.py**

```python
# skills/video-pipeline/autopilot/core/notifier.py
"""Slack notifications for autopilot decisions."""

from typing import Optional
from autopilot.core.confidence_scorer import ScoredIdea


class AutopilotNotifier:
    """Send formatted notifications to Slack."""

    def __init__(self, slack_client):
        """Initialize notifier.

        Args:
            slack_client: SlackClient instance
        """
        self.slack = slack_client

    def _format_reasoning(self, scored: ScoredIdea) -> str:
        """Format scoring reasoning as bullet list.

        Args:
            scored: Scored idea with reasoning

        Returns:
            Formatted string
        """
        lines = [f"• {r}" for r in scored.reasoning]
        return "\n".join(lines)

    def notify_production_start(self, scored: ScoredIdea) -> None:
        """Send notification that production is starting.

        Args:
            scored: The idea being produced
        """
        candidate = scored.candidate

        message = f"""🎬 *AUTOPILOT: Starting production*

*VIDEO:* {candidate.title}
*CONFIDENCE:* {scored.score:.0f}/100

*WHY THIS IDEA:*
{self._format_reasoning(scored)}
"""

        if candidate.competitor_title:
            message += f"\n*MODELING:* {candidate.competitor_title}"
            if candidate.competitor_vph:
                message += f" (VPH: {candidate.competitor_vph:.0f})"

        message += "\n\n_Production begins. Reply STOP to abort._"

        self.slack.send_message(message)

    def notify_not_ready(self, days_until: int, next_date: str) -> None:
        """Send notification that it's not time yet.

        Args:
            days_until: Days until next production slot
            next_date: Date string for next production
        """
        message = f"""⏳ *AUTOPILOT: Not time yet*

Next production slot in *{days_until} day(s)* ({next_date}).

Cadence is on track. Checking again later."""

        self.slack.send_message(message)

    def notify_no_candidates(self, threshold: int, best_score: Optional[float] = None) -> None:
        """Send notification that no candidates meet threshold.

        Args:
            threshold: Minimum confidence score required
            best_score: Score of the best candidate (if any)
        """
        message = f"""📭 *AUTOPILOT: No candidates ready*

No ideas meet the confidence threshold of *{threshold}*.
"""

        if best_score is not None:
            message += f"Best candidate scored *{best_score:.0f}* (need ≥{threshold}).\n"

        message += "\nWaiting for better opportunities. Will check again next cycle."

        self.slack.send_message(message)

    def notify_disabled(self) -> None:
        """Send notification that autopilot is disabled."""
        message = """🔴 *AUTOPILOT: Disabled*

Autopilot is currently OFF. To enable:
• Edit `autopilot_program.md` and set `autopilot: ON`
• Or send `autopilot on` command"""

        self.slack.send_message(message)

    def notify_error(self, error: str, context: Optional[str] = None) -> None:
        """Send error notification.

        Args:
            error: Error message
            context: Additional context (optional)
        """
        message = f"""🚨 *AUTOPILOT: Error*

{error}
"""

        if context:
            message += f"\n_Context: {context}_"

        self.slack.send_message(message)
```

### Step 4: Run tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_notifier.py -v
```

Expected: All 4 tests PASS

### Step 5: Commit

- [ ] **Commit**

```bash
cd skills/video-pipeline && git add autopilot/ && git commit -m "feat(autopilot): Add Slack notifier with formatted messages

- Production start with reasoning
- Not ready, no candidates, disabled, error states
- 4 tests passing"
```

---

## Task 6: Create autopilot_program.md

**Files:**
- Create: `skills/video-pipeline/autopilot/autopilot_program.md`

### Step 1: Write the config file

- [ ] **Write autopilot_program.md**

```markdown
# Autopilot Program

## Mission

Your mission: **Maximize click-through rate for this YouTube channel.**

You have access to the full video production pipeline. Your job is to:
1. Find winning videos from competitors (high VPH = proven appeal)
2. Understand WHY they're winning (thumbnail, title, topic timing)
3. Model the winning elements for OUR channel
4. Produce the video (pipeline handles execution)
5. Measure YOUR results vs the competitor you modeled
6. Learn what works for THIS channel, not just what worked for them

You are not a passive scheduler. You are an active learner.
Every video is an experiment. Every CTR measurement is data.

The pipeline is your hands. You are the brain.

---

## Cadence

videos_per_month: 15
production_interval_days: 2

---

## Confidence Scoring Weights

weights:
  competitor_vph: 0.30
  topic_channel_fit: 0.25
  timing_freshness: 0.20
  channel_momentum: 0.10
  retention_patterns: 0.08
  title_formula: 0.07

---

## Thresholds

thresholds:
  min_confidence_score: 60
  min_competitor_vph: 50
  max_idea_age_days: 7
  ctr_success_threshold: 4.0
  ctr_failure_threshold: 2.5
  early_warning_hours: 6

---

## Scope Boundaries

**What the autopilot CAN do:**
- Score and select ideas from candidates
- Analyze competitor thumbnails (vision)
- Write style overrides to Airtable fields
- Select titles from generated options
- Trigger pipeline execution
- Read scripts for forensic analysis
- Update memory files with learnings

**What the autopilot CANNOT do:**
- Modify pipeline code (bots, clients, Remotion)
- Publish videos to YouTube (human does this)
- Delete Airtable records
- Change this config file (human does this)
- Spend money beyond normal pipeline costs
```

### Step 2: Add .gitignore for state file

- [ ] **Add gitignore entry**

```bash
echo "autopilot/state/autopilot_state.json" >> skills/video-pipeline/.gitignore
```

### Step 3: Commit

- [ ] **Commit**

```bash
cd skills/video-pipeline && git add autopilot/autopilot_program.md .gitignore && git commit -m "feat(autopilot): Add autopilot_program.md config file

- Mission statement
- Cadence settings (15 videos/month)
- Confidence weights
- Decision thresholds
- Scope boundaries"
```

---

## Task 7: Main Autopilot Loop

**Files:**
- Create: `skills/video-pipeline/autopilot/autopilot.py`

### Step 1: Write the main orchestrator

- [ ] **Write autopilot.py**

```python
# skills/video-pipeline/autopilot/autopilot.py
"""
Autopilot Brain - Main Orchestrator

This is the entry point for the autopilot system. It:
1. Loads config and state
2. Checks if enabled and if production slot is available
3. Gathers candidates from Competitor Videos table
4. Scores candidates using weighted signals
5. Picks the best idea and notifies Slack
6. Triggers pipeline execution

Usage:
    python -m autopilot.autopilot --check-cycle
    python -m autopilot.autopilot --status
    python -m autopilot.autopilot --force
"""

import os
import sys
import argparse
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from autopilot.core.config_parser import load_config, AutopilotConfig
from autopilot.core.state_manager import StateManager, AutopilotState
from autopilot.core.cadence_manager import CadenceManager
from autopilot.core.confidence_scorer import ConfidenceScorer, IdeaCandidate
from autopilot.core.notifier import AutopilotNotifier
from clients.airtable_client import AirtableClient
from clients.slack_client import SlackClient
from pipeline_constants import CompetitorVideoFields


class Autopilot:
    """Main autopilot orchestrator."""

    def __init__(self):
        """Initialize autopilot with all dependencies."""
        self.config = load_config()
        self.state_manager = StateManager()
        self.airtable = AirtableClient()
        self.slack = SlackClient()
        self.notifier = AutopilotNotifier(slack_client=self.slack)
        self.scorer = ConfidenceScorer(self.config)

    def _get_candidates_from_competitor_videos(self) -> List[IdeaCandidate]:
        """Fetch candidate ideas from Competitor Videos table.

        Returns:
            List of IdeaCandidate objects
        """
        # Get recent competitor videos with high VPH
        min_vph = self.config.thresholds.min_competitor_vph
        max_age_days = self.config.thresholds.max_idea_age_days

        # Query Airtable
        # Filter: VPH >= threshold, not already modeled, recent
        try:
            records = self.airtable.get_competitor_videos(
                min_vph=min_vph,
                max_age_days=max_age_days,
                exclude_modeled=True,
            )
        except Exception as e:
            print(f"Error fetching competitor videos: {e}")
            return []

        candidates = []
        for record in records:
            fields = record.get('fields', {})

            # Calculate hours old
            published = fields.get(CompetitorVideoFields.PUBLISHED_DATE)
            hours_old = 0
            if published:
                try:
                    pub_dt = datetime.fromisoformat(published.replace('Z', '+00:00'))
                    hours_old = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600
                except:
                    pass

            candidate = IdeaCandidate(
                record_id=record['id'],
                title=fields.get(CompetitorVideoFields.TITLE, "Unknown"),
                source_type="competitor",
                competitor_vph=fields.get(CompetitorVideoFields.VPH, 0),
                competitor_title=fields.get(CompetitorVideoFields.TITLE),
                hours_old=hours_old,
            )
            candidates.append(candidate)

        return candidates

    def check_cycle(self, force: bool = False) -> bool:
        """Run one autopilot cycle.

        Args:
            force: Skip cadence check and run anyway

        Returns:
            True if production started, False otherwise
        """
        print("🤖 Autopilot: Checking cycle...")

        # 1. Check if enabled
        state = self.state_manager.load()
        if not state.autopilot_enabled:
            print("   Autopilot is disabled.")
            return False

        # 2. Check cadence (unless forced)
        if not force:
            cadence = CadenceManager(self.config, state)
            if not cadence.is_production_slot_available():
                days = cadence.days_until_next()
                next_date = cadence.get_next_production_date().strftime("%Y-%m-%d")
                print(f"   Not time yet. Next slot in {days} day(s).")
                # Don't spam Slack on every check - only notify if explicitly requested
                return False

        # 3. Gather candidates
        print("   Gathering candidates...")
        candidates = self._get_candidates_from_competitor_videos()

        if not candidates:
            print("   No candidates found.")
            self.notifier.notify_no_candidates(
                threshold=self.config.thresholds.min_confidence_score,
                best_score=None,
            )
            return False

        print(f"   Found {len(candidates)} candidates.")

        # 4. Score and pick best
        best = self.scorer.get_best(candidates)

        if best is None:
            # Get best score for notification
            all_scored = self.scorer.rank(candidates)
            best_score = all_scored[0].score if all_scored else None
            print(f"   No candidates meet threshold. Best: {best_score:.0f}")
            self.notifier.notify_no_candidates(
                threshold=self.config.thresholds.min_confidence_score,
                best_score=best_score,
            )
            return False

        print(f"   Best candidate: {best.candidate.title} (score: {best.score:.0f})")

        # 5. Notify Slack
        self.notifier.notify_production_start(best)

        # 6. Record state
        self.state_manager.record_production_cycle(
            video_title=best.candidate.title,
            modeled_from=best.candidate.competitor_title,
        )

        # 7. Trigger pipeline (placeholder for Chunk 2)
        # For now, just mark as selected. Full pipeline integration in Chunk 2.
        print(f"   ✅ Selected: {best.candidate.title}")
        print("   TODO: Trigger pipeline (Chunk 2)")

        return True

    def status(self) -> None:
        """Print current autopilot status."""
        state = self.state_manager.load()

        print("\n🤖 Autopilot Status")
        print("=" * 40)
        print(f"Enabled: {'✅ ON' if state.autopilot_enabled else '🔴 OFF'}")
        print(f"Videos produced: {state.videos_produced}")
        print(f"Avg CTR: {state.channel_avg_ctr:.1f}%")

        if state.last_cycle:
            print(f"Last cycle: {state.last_cycle}")
            cadence = CadenceManager(self.config, state)
            if cadence.is_production_slot_available():
                print("Next slot: ✅ Ready now")
            else:
                days = cadence.days_until_next()
                next_date = cadence.get_next_production_date().strftime("%Y-%m-%d")
                print(f"Next slot: {next_date} ({days} day(s))")
        else:
            print("Last cycle: Never run")
            print("Next slot: ✅ Ready now")

        if state.current_experiment:
            exp = state.current_experiment
            print(f"\nCurrent experiment:")
            print(f"  Title: {exp.video_title}")
            print(f"  Status: {exp.status}")
            if exp.modeled_from:
                print(f"  Modeled from: {exp.modeled_from}")

        print("=" * 40)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Autopilot Brain")
    parser.add_argument("--check-cycle", action="store_true", help="Run one autopilot cycle")
    parser.add_argument("--status", action="store_true", help="Show current status")
    parser.add_argument("--force", action="store_true", help="Force production (skip cadence)")

    args = parser.parse_args()

    autopilot = Autopilot()

    if args.status:
        autopilot.status()
    elif args.check_cycle or args.force:
        autopilot.check_cycle(force=args.force)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

### Step 2: Test manually

- [ ] **Test status command**

```bash
cd skills/video-pipeline && python -m autopilot.autopilot --status
```

Expected: Status output showing enabled state, videos produced, next slot

### Step 3: Commit

- [ ] **Commit**

```bash
cd skills/video-pipeline && git add autopilot/ && git commit -m "feat(autopilot): Add main orchestrator loop

- Check cycle: enabled → cadence → candidates → score → notify
- Status command shows current state
- Force flag to skip cadence check
- Ready for integration (Chunk 2)"
```

---

## Task 8: Integration Test

**Files:**
- Create: `skills/video-pipeline/autopilot/tests/test_integration.py`

### Step 1: Write integration test

- [ ] **Write test_integration.py**

```python
# skills/video-pipeline/autopilot/tests/test_integration.py
"""Integration tests for autopilot."""

import pytest
from unittest.mock import Mock, patch
from pathlib import Path
from autopilot.autopilot import Autopilot
from autopilot.core.config_parser import AutopilotConfig
from autopilot.core.state_manager import AutopilotState


class TestAutopilotIntegration:
    """Integration test for full autopilot cycle."""

    @pytest.fixture
    def mock_airtable(self):
        """Mock Airtable client."""
        mock = Mock()
        mock.get_competitor_videos.return_value = [
            {
                'id': 'rec123',
                'fields': {
                    'Title': "China's Economic Collapse",
                    'VPH': 150.0,
                    'Hours Old': 24,
                    'Published Date': '2026-03-17T12:00:00Z',
                }
            },
            {
                'id': 'rec456',
                'fields': {
                    'Title': "Why NATO is Failing",
                    'VPH': 80.0,
                    'Hours Old': 48,
                    'Published Date': '2026-03-16T12:00:00Z',
                }
            },
        ]
        return mock

    @pytest.fixture
    def mock_slack(self):
        """Mock Slack client."""
        return Mock()

    @pytest.fixture
    def temp_state(self, tmp_path):
        """Temporary state file."""
        return tmp_path / "autopilot_state.json"

    @patch('autopilot.autopilot.AirtableClient')
    @patch('autopilot.autopilot.SlackClient')
    @patch('autopilot.autopilot.StateManager')
    @patch('autopilot.autopilot.load_config')
    def test_full_cycle_selects_best_candidate(
        self,
        mock_load_config,
        mock_state_manager_cls,
        mock_slack_cls,
        mock_airtable_cls,
        mock_airtable,
        mock_slack,
    ):
        """Full cycle should select highest-scoring candidate."""
        # Setup mocks
        mock_load_config.return_value = AutopilotConfig()
        mock_airtable_cls.return_value = mock_airtable
        mock_slack_cls.return_value = mock_slack

        # Setup state manager mock
        mock_state_manager = Mock()
        mock_state_manager.load.return_value = AutopilotState(
            autopilot_enabled=True,
            last_cycle=None,  # Never run = ready
        )
        mock_state_manager_cls.return_value = mock_state_manager

        # Run cycle
        autopilot = Autopilot()
        result = autopilot.check_cycle()

        # Should have selected best candidate (China - higher VPH)
        assert result is True
        mock_slack.send_message.assert_called()

        # State should have been updated
        mock_state_manager.record_production_cycle.assert_called_once()
        call_args = mock_state_manager.record_production_cycle.call_args
        assert "China" in call_args[1]['video_title']
```

### Step 2: Run integration test

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_integration.py -v
```

Expected: PASS

### Step 3: Run all autopilot tests

- [ ] **Run all tests**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/ -v
```

Expected: All tests PASS (18+ tests)

### Step 4: Final commit for Chunk 1

- [ ] **Commit**

```bash
cd skills/video-pipeline && git add autopilot/ && git commit -m "feat(autopilot): Complete Chunk 1 - Foundation + Decision Engine

Autopilot brain now:
- Reads config from autopilot_program.md
- Manages state in autopilot_state.json
- Checks cadence (videos per month)
- Scores candidates with weighted signals
- Picks best idea above threshold
- Notifies Slack with reasoning

18 tests passing. Ready for Chunk 2 (thumbnail intel + memory)."
```

---

## Chunk 1 Complete

**Deliverables:**
- `autopilot/core/config_parser.py` — Parse autopilot_program.md
- `autopilot/core/state_manager.py` — Manage autopilot_state.json
- `autopilot/core/cadence_manager.py` — Check production slots
- `autopilot/core/confidence_scorer.py` — Score ideas with weights
- `autopilot/core/notifier.py` — Slack notifications
- `autopilot/autopilot.py` — Main loop orchestrator
- `autopilot/autopilot_program.md` — Config file
- 18+ tests

**Test Command:**
```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/ -v
```

**Manual Test:**
```bash
cd skills/video-pipeline && python -m autopilot.autopilot --status
cd skills/video-pipeline && python -m autopilot.autopilot --check-cycle
```

**Next:** Chunk 2 (Thumbnail Intel + Memory System)
