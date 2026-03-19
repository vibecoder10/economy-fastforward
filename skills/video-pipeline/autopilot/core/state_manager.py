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
    idea_record_id: Optional[str] = None  # Airtable record ID for the created idea


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
        idea_record_id: Optional[str] = None,
    ) -> None:
        """Record that a production cycle started.

        Args:
            video_title: Title of video being produced
            modeled_from: Competitor video this models (optional)
            thumbnail_override: Thumbnail override used (optional)
            idea_record_id: Airtable record ID for the created idea (optional)
        """
        state = self.load()
        state.videos_produced += 1
        state.last_cycle = datetime.now(timezone.utc).isoformat()
        state.current_experiment = ExperimentState(
            video_title=video_title,
            status="producing",
            modeled_from=modeled_from,
            thumbnail_override=thumbnail_override,
            idea_record_id=idea_record_id,
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
