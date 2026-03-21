# Curiosity Gap Phase 3: Learning Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire curiosity gap structures into the learning system so CTR performance feeds back into pattern library.

**Architecture:** Extend existing `learning_extractor.py` with new "structure" category, extend `memory_writer.py` to write curiosity gap learnings, add Airtable fields to Ideas table for CTR tracking, wire performance_tracker.py for 12h/24h/48h snapshots.

**Tech Stack:** Python 3.11+, async, pyairtable, existing autopilot learning infrastructure.

**Related Spec:** `docs/superpowers/specs/2026-03-20-curiosity-gap-title-system.md` (Section 3, 4, Appendix A.1, A.2)

---

## File Structure (Phase 3)

```
skills/video-pipeline/
├── autopilot/
│   └── learning/
│       ├── learning_extractor.py     # MODIFY: add extract_structure_learnings()
│       └── memory_writer.py          # MODIFY: add update_curiosity_gap_patterns()
│
├── autopilot/memory/
│   └── title_patterns.md             # MODIFY: add curiosity gap section
│
├── performance_tracker.py            # MODIFY: add CTR 12h snapshot
│
├── pipeline_constants.py             # ALREADY HAS: IdeaFields.CTR_12H etc (via TitleTestFields)
│
└── curiosity_gap/
    └── tests/
        └── test_learning_integration.py  # CREATE: tests for learning system
```

---

## Task 1: Add "structure" Category to Learning Extractor

**Files:**
- Modify: `skills/video-pipeline/autopilot/learning/learning_extractor.py`
- Create: `skills/video-pipeline/autopilot/tests/test_learning_extractor_structure.py`

### Step 1: Write failing test

- [ ] **Write test_learning_extractor_structure.py**

```python
# skills/video-pipeline/autopilot/tests/test_learning_extractor_structure.py
"""Tests for curiosity gap structure learning extraction."""

import pytest
from autopilot.learning.learning_extractor import (
    LearningExtractor,
    ExtractedLearning,
)
from autopilot.monitoring.early_warning import CTRVerdict


class TestStructureLearningExtraction:
    """Test suite for structure learning extraction."""

    @pytest.fixture
    def extractor(self):
        return LearningExtractor()

    def test_extract_structure_learning_keep(self, extractor):
        """Should extract structure learning with KEEP verdict for high CTR."""
        learnings = extractor.extract_structure_learnings(
            video_title="The $100B Mistake Saudi Arabia Is Hiding",
            ctr=5.2,
            structure="hidden_flaw",
            structure_confidence=78,
        )

        assert len(learnings) == 1
        learning = learnings[0]
        assert learning.category == "structure"
        assert learning.pattern == "hidden_flaw"
        assert learning.verdict == CTRVerdict.KEEP
        assert learning.ctr == 5.2
        assert "hidden_flaw" in learning.evidence

    def test_extract_structure_learning_discard(self, extractor):
        """Should extract structure learning with DISCARD verdict for low CTR."""
        learnings = extractor.extract_structure_learnings(
            video_title="The Time Bomb In Iran's Strategy",
            ctr=2.1,
            structure="time_bomb",
            structure_confidence=65,
        )

        assert len(learnings) == 1
        learning = learnings[0]
        assert learning.category == "structure"
        assert learning.pattern == "time_bomb"
        assert learning.verdict == CTRVerdict.DISCARD

    def test_extract_structure_learning_none_structure(self, extractor):
        """Should return empty list when no structure provided."""
        learnings = extractor.extract_structure_learnings(
            video_title="Some Video",
            ctr=4.0,
            structure=None,
            structure_confidence=None,
        )
        assert len(learnings) == 0

    def test_extract_structure_learning_other(self, extractor):
        """Should extract 'other' structure for unclassified titles."""
        learnings = extractor.extract_structure_learnings(
            video_title="5 Days Until China's Dollar Deadline",
            ctr=4.5,
            structure="other",
            structure_confidence=45,
        )

        assert len(learnings) == 1
        assert learnings[0].pattern == "other"

    def test_extract_all_includes_structure(self, extractor):
        """extract_all should include structure learnings when present."""
        result = extractor.extract_all(
            video_title="The $100B Mistake",
            ctr=5.0,
            thumbnail_override=None,
            modeled_from=None,
            theme_data=None,
            structure="hidden_flaw",
            structure_confidence=80,
        )

        # Should have structure learning
        structure_learnings = [l for l in result.learnings if l.category == "structure"]
        assert len(structure_learnings) == 1
        assert structure_learnings[0].pattern == "hidden_flaw"
```

### Step 2: Run test to verify it fails

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_learning_extractor_structure.py -v
```

Expected: FAIL with `TypeError: extract_structure_learnings() missing` or similar

### Step 3: Implement extract_structure_learnings

- [ ] **Modify learning_extractor.py — add method**

Add after `extract_theme_learnings()` (around line 293):

```python
def extract_structure_learnings(
    self,
    video_title: str,
    ctr: float,
    structure: Optional[str],
    structure_confidence: Optional[int],
) -> List[ExtractedLearning]:
    """Extract curiosity gap structure learnings.

    Tracks which curiosity gap structure was used and correlates
    with CTR performance.

    Args:
        video_title: Title of the video
        ctr: Actual CTR percentage
        structure: Curiosity gap structure ID (e.g., "hidden_flaw")
        structure_confidence: Confidence score at generation time

    Returns:
        List of ExtractedLearning for structure pattern
    """
    learnings = []

    if not structure:
        return learnings

    verdict = self.early_warning.get_verdict(ctr)
    confidence = self._get_confidence_for_verdict(verdict)

    # Adjust confidence based on structure_confidence at generation
    if structure_confidence:
        # Blend: 60% CTR verdict, 40% generation confidence
        confidence = confidence * 0.6 + (structure_confidence / 100 * 100) * 0.4

    learnings.append(ExtractedLearning(
        category="structure",
        pattern=structure,
        verdict=verdict,
        confidence=confidence,
        evidence=f"Structure '{structure}' (gen_conf: {structure_confidence or 'N/A'}). CTR: {ctr:.1f}%",
        video_title=video_title,
        ctr=ctr,
    ))

    return learnings
```

### Step 4: Modify extract_all to include structure parameter

- [ ] **Modify extract_all signature and body**

Update the `extract_all` method signature (around line 320):

```python
def extract_all(
    self,
    video_title: str,
    ctr: float,
    thumbnail_override: Optional[str] = None,
    modeled_from: Optional[str] = None,
    theme_data: Optional[ThemeData] = None,
    structure: Optional[str] = None,             # NEW
    structure_confidence: Optional[int] = None,  # NEW
) -> ExperimentResult:
```

And add to the learnings extraction (inside the method):

```python
    learnings = []
    learnings.extend(self.extract_thumbnail_learnings(video_title, ctr, thumbnail_override))
    learnings.extend(self.extract_title_learnings(video_title, ctr))
    learnings.extend(self.extract_theme_learnings(video_title, ctr, theme_data))
    learnings.extend(self.extract_structure_learnings(video_title, ctr, structure, structure_confidence))  # NEW
```

### Step 5: Run tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_learning_extractor_structure.py -v
```

Expected: All tests PASS

### Step 6: Commit

- [ ] **Commit**

```bash
cd skills/video-pipeline && git add autopilot/ && git commit -m "feat(learning): Add curiosity gap structure extraction

- New extract_structure_learnings() method for 'structure' category
- Tracks structure ID + CTR correlation
- Blends generation confidence with CTR verdict
- 5 tests passing"
```

---

## Task 2: Add Curiosity Gap Section to Memory Writer

**Files:**
- Modify: `skills/video-pipeline/autopilot/learning/memory_writer.py`
- Create: `skills/video-pipeline/autopilot/tests/test_memory_writer_structure.py`

### Step 1: Write failing test

- [ ] **Write test_memory_writer_structure.py**

```python
# skills/video-pipeline/autopilot/tests/test_memory_writer_structure.py
"""Tests for curiosity gap memory writing."""

import pytest
from pathlib import Path
from autopilot.learning.memory_writer import MemoryWriter, ExtractedLearning
from autopilot.monitoring.early_warning import CTRVerdict


class TestCuriosityGapMemoryWriter:
    """Test suite for curiosity gap memory writing."""

    @pytest.fixture
    def temp_memory_dir(self, tmp_path):
        """Create temporary memory directory with title_patterns.md."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        # Create initial title_patterns.md
        title_patterns = memory_dir / "title_patterns.md"
        title_patterns.write_text("""# Title Patterns

Last updated: 2026-03-18
Sample size: 0 videos

---

## Proven Formulas (USE)

*No proven formulas yet.*

---

## Curiosity Gap Structures

| Structure | Avg CTR | Sample | Verdict |
|-----------|---------|--------|---------|
| *No data yet* | | | |

---

## Notes

Pattern types: question, statement, number
""")
        return memory_dir

    @pytest.fixture
    def writer(self, temp_memory_dir):
        return MemoryWriter(memory_dir=temp_memory_dir)

    def test_update_curiosity_gap_patterns_keep(self, writer, temp_memory_dir):
        """Should add KEEP structure to Curiosity Gap Structures section."""
        learnings = [
            ExtractedLearning(
                category="structure",
                pattern="hidden_flaw",
                verdict=CTRVerdict.KEEP,
                confidence=75.0,
                evidence="Structure 'hidden_flaw'. CTR: 5.2%",
                video_title="The $100B Mistake",
                ctr=5.2,
            )
        ]

        writer.update_curiosity_gap_patterns(learnings)

        content = (temp_memory_dir / "title_patterns.md").read_text()
        assert "hidden_flaw" in content
        assert "5.2%" in content
        assert "keep" in content.lower()

    def test_update_curiosity_gap_patterns_discard(self, writer, temp_memory_dir):
        """Should add DISCARD structure to Anti-Patterns section."""
        learnings = [
            ExtractedLearning(
                category="structure",
                pattern="time_bomb",
                verdict=CTRVerdict.DISCARD,
                confidence=40.0,
                evidence="Structure 'time_bomb'. CTR: 2.1%",
                video_title="The 40-Year Trap",
                ctr=2.1,
            )
        ]

        writer.update_curiosity_gap_patterns(learnings)

        content = (temp_memory_dir / "title_patterns.md").read_text()
        assert "time_bomb" in content
        assert "2.1%" in content

    def test_update_curiosity_gap_patterns_skips_non_structure(self, writer, temp_memory_dir):
        """Should skip non-structure category learnings."""
        learnings = [
            ExtractedLearning(
                category="title",  # Not "structure"
                pattern="question_format",
                verdict=CTRVerdict.KEEP,
                confidence=60.0,
                evidence="Question format",
                video_title="Why X?",
                ctr=4.5,
            )
        ]

        original_content = (temp_memory_dir / "title_patterns.md").read_text()
        writer.update_curiosity_gap_patterns(learnings)
        new_content = (temp_memory_dir / "title_patterns.md").read_text()

        # Should be unchanged
        assert original_content == new_content

    def test_process_result_includes_structure(self, writer, temp_memory_dir):
        """process_result should call update_curiosity_gap_patterns."""
        from autopilot.learning.memory_writer import ExperimentResult

        result = ExperimentResult(
            video_title="The $100B Mistake",
            date="2026-03-20",
            modeled_from=None,
            predicted_ctr=None,
            actual_ctr=5.2,
            verdict=CTRVerdict.KEEP,
            thumbnail_override=None,
            title_formula=None,
            learnings=[
                ExtractedLearning(
                    category="structure",
                    pattern="hidden_flaw",
                    verdict=CTRVerdict.KEEP,
                    confidence=75.0,
                    evidence="hidden_flaw structure",
                    video_title="The $100B Mistake",
                    ctr=5.2,
                )
            ],
        )

        writer.process_result(result)

        content = (temp_memory_dir / "title_patterns.md").read_text()
        assert "hidden_flaw" in content
```

### Step 2: Run test to verify it fails

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_memory_writer_structure.py -v
```

Expected: FAIL with `AttributeError: 'MemoryWriter' has no attribute 'update_curiosity_gap_patterns'`

### Step 3: Implement update_curiosity_gap_patterns

- [ ] **Add method to memory_writer.py**

Add after `update_topic_performance()` (around line 263):

```python
def update_curiosity_gap_patterns(self, learnings: List[ExtractedLearning]) -> None:
    """Update title_patterns.md with curiosity gap structure performance.

    Adds notes about which curiosity gap structures performed well
    (KEEP) or poorly (DISCARD) based on CTR data.

    Args:
        learnings: List of learnings (only "structure" category used)
    """
    pattern_path = self.memory_dir / "title_patterns.md"
    content = pattern_path.read_text() if pattern_path.exists() else ""

    for learning in learnings:
        if learning.category != "structure":
            continue

        note = (
            f"\n- {learning.pattern}: CTR {learning.ctr:.1f}% "
            f"({learning.verdict.value}) - {learning.video_title}"
        )

        # Insert into Curiosity Gap Structures section
        if "## Curiosity Gap Structures" in content:
            content = content.replace(
                "## Curiosity Gap Structures\n",
                f"## Curiosity Gap Structures{note}\n",
                1
            )
        else:
            # Create section if missing
            content += f"\n## Curiosity Gap Structures{note}\n"

    pattern_path.write_text(content)
```

### Step 4: Modify process_result to call new method

- [ ] **Update process_result in memory_writer.py**

Add to the `process_result` method (around line 287):

```python
def process_result(self, result: ExperimentResult) -> None:
    """Process a full experiment result and update all memory files."""
    # Always log the experiment
    self.append_experiment(result)

    # Filter learnings by category
    thumbnail_learnings = [l for l in result.learnings if l.category == "thumbnail"]
    title_learnings = [l for l in result.learnings if l.category == "title"]
    topic_learnings = [l for l in result.learnings if l.category in ("topic", "angle", "hook", "formula")]
    structure_learnings = [l for l in result.learnings if l.category == "structure"]  # NEW

    # Update pattern files if there are relevant learnings
    if thumbnail_learnings:
        self.update_thumbnail_patterns(thumbnail_learnings)
    if title_learnings:
        self.update_title_patterns(title_learnings)
    if topic_learnings:
        self.update_topic_performance(topic_learnings)
    if structure_learnings:  # NEW
        self.update_curiosity_gap_patterns(structure_learnings)
```

### Step 5: Run tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_memory_writer_structure.py -v
```

Expected: All tests PASS

### Step 6: Commit

- [ ] **Commit**

```bash
cd skills/video-pipeline && git add autopilot/ && git commit -m "feat(memory): Add curiosity gap structure writing to title_patterns.md

- New update_curiosity_gap_patterns() method
- Writes structure performance to Curiosity Gap Structures section
- Integrated into process_result()
- 4 tests passing"
```

---

## Task 3: Add CTR 12h Field to Ideas Table + Performance Tracker

**Files:**
- Modify: `skills/video-pipeline/pipeline_constants.py` (already has field, verify)
- Modify: `skills/video-pipeline/performance_tracker.py`
- Create: `skills/video-pipeline/tests/test_ctr_12h_tracking.py`

### Step 1: Add CTR milestone fields to IdeaFields

- [ ] **Add fields to pipeline_constants.py IdeaFields class**

Add after `CTR_48H = "CTR 48h (%)"` (around line 106):

```python
    # Curiosity Gap CTR milestones (written by performance_tracker.py)
    CTR_12H = "CTR 12h"
    CTR_24H = "CTR 24h"
    # Note: CTR_48H already exists as "CTR 48h (%)" - we add separate "CTR 48h" for consistency
```

**Note:** The existing `CTR_48H = "CTR 48h (%)"` field includes percentage suffix. For milestone tracking, we use simpler field names without `(%)` suffix for consistency with the Title Tests table schema.

### Step 2: Write failing test for CTR 12h tracking

- [ ] **Write test_ctr_12h_tracking.py**

```python
# skills/video-pipeline/tests/test_ctr_12h_tracking.py
"""Tests for CTR 12h/24h/48h snapshot tracking."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, AsyncMock


class TestCTRMilestoneTracking:
    """Test CTR milestone snapshot writing."""

    def test_should_write_12h_snapshot(self):
        """12h CTR should be written when video is 12+ hours old."""
        from performance_tracker import should_write_ctr_snapshot

        upload_time = datetime.now(timezone.utc) - timedelta(hours=13)
        existing_fields = {}  # No CTR 12h yet

        result = should_write_ctr_snapshot(
            milestone="12h",
            upload_time=upload_time,
            existing_fields=existing_fields,
        )
        assert result is True

    def test_should_not_write_12h_if_already_set(self):
        """12h CTR should NOT be written if already present."""
        from performance_tracker import should_write_ctr_snapshot

        upload_time = datetime.now(timezone.utc) - timedelta(hours=13)
        existing_fields = {"CTR 12h": 4.5}  # Already has value

        result = should_write_ctr_snapshot(
            milestone="12h",
            upload_time=upload_time,
            existing_fields=existing_fields,
        )
        assert result is False

    def test_should_not_write_12h_if_too_young(self):
        """12h CTR should NOT be written if video < 12 hours old."""
        from performance_tracker import should_write_ctr_snapshot

        upload_time = datetime.now(timezone.utc) - timedelta(hours=8)
        existing_fields = {}

        result = should_write_ctr_snapshot(
            milestone="12h",
            upload_time=upload_time,
            existing_fields=existing_fields,
        )
        assert result is False

    def test_should_write_24h_snapshot(self):
        """24h CTR should be written when video is 24+ hours old."""
        from performance_tracker import should_write_ctr_snapshot

        upload_time = datetime.now(timezone.utc) - timedelta(hours=25)
        existing_fields = {"CTR 12h": 4.0}  # 12h already set

        result = should_write_ctr_snapshot(
            milestone="24h",
            upload_time=upload_time,
            existing_fields=existing_fields,
        )
        assert result is True

    def test_milestone_hours_mapping(self):
        """Verify milestone to hours mapping."""
        from performance_tracker import MILESTONE_HOURS

        assert MILESTONE_HOURS["12h"] == 12
        assert MILESTONE_HOURS["24h"] == 24
        assert MILESTONE_HOURS["48h"] == 48
```

### Step 3: Run test to verify it fails

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest tests/test_ctr_12h_tracking.py -v
```

Expected: FAIL with `ImportError: cannot import name 'should_write_ctr_snapshot'`

### Step 4: Implement CTR milestone logic in performance_tracker.py

- [ ] **Add milestone tracking to performance_tracker.py**

First, read the current file structure, then add near the top:

```python
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

# CTR snapshot milestones
MILESTONE_HOURS = {
    "12h": 12,
    "24h": 24,
    "48h": 48,
}

MILESTONE_FIELDS = {
    "12h": "CTR 12h",
    "24h": "CTR 24h",
    "48h": "CTR 48h",
}


def should_write_ctr_snapshot(
    milestone: str,
    upload_time: datetime,
    existing_fields: Dict[str, any],
) -> bool:
    """Check if CTR snapshot should be written for milestone.

    Args:
        milestone: "12h", "24h", or "48h"
        upload_time: When video was uploaded
        existing_fields: Current Airtable field values

    Returns:
        True if snapshot should be written
    """
    if milestone not in MILESTONE_HOURS:
        return False

    required_hours = MILESTONE_HOURS[milestone]
    field_name = MILESTONE_FIELDS[milestone]

    # Already has value?
    if existing_fields.get(field_name) is not None:
        return False

    # Video old enough?
    now = datetime.now(timezone.utc)
    hours_old = (now - upload_time).total_seconds() / 3600

    return hours_old >= required_hours
```

### Step 5: Wire into existing update loop

- [ ] **Find and modify the main update function**

In the function that updates video records (likely `update_video_analytics` or similar), add after fetching current CTR:

```python
# Check if we need to write CTR snapshots
upload_date_str = record.get("Upload Date")
if upload_date_str:
    upload_time = datetime.fromisoformat(upload_date_str.replace('Z', '+00:00'))

    for milestone in ["12h", "24h", "48h"]:
        if should_write_ctr_snapshot(milestone, upload_time, record):
            updates[MILESTONE_FIELDS[milestone]] = current_ctr
```

### Step 6: Run tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest tests/test_ctr_12h_tracking.py -v
```

Expected: All tests PASS

### Step 7: Commit

- [ ] **Commit**

```bash
cd skills/video-pipeline && git add performance_tracker.py tests/ pipeline_constants.py && git commit -m "feat(tracking): Add CTR 12h/24h/48h snapshot milestones

- New should_write_ctr_snapshot() for milestone detection
- Writes CTR at 12h, 24h, 48h marks (once each)
- Adds MILESTONE_HOURS and MILESTONE_FIELDS constants
- 5 tests passing"
```

---

## Task 4: Add Airtable Fields to Ideas Table

**Files:**
- Modify: `skills/video-pipeline/pipeline_constants.py` (verify fields exist)
- Create: `skills/video-pipeline/setup_curiosity_gap_fields.py`

### Step 1: Verify IdeaFields has all curiosity gap fields

- [ ] **Check pipeline_constants.py IdeaFields**

Ensure these fields exist in IdeaFields class (some may already be there):

```python
# Curiosity Gap fields
CURIOSITY_STRUCTURE = "Curiosity Structure"
STRUCTURE_CONFIDENCE = "Structure Confidence"
THUMBNAIL_APPROACH = "Thumbnail Approach"
THUMBNAIL_TEXT = "Thumbnail Text"  # May already exist
STRUCTURE_SOURCE = "Structure Source"
PATTERN_LIBRARY_SNAPSHOT = "Pattern Library Snapshot"
TITLE_POLL_RESULT = "Title Poll Result"
POLL_CLOSED = "Poll Closed"
CTR_12H = "CTR 12h"
CTR_24H = "CTR 24h"
CTR_48H = "CTR 48h"
```

### Step 2: Create setup script for Airtable fields

- [ ] **Write setup_curiosity_gap_fields.py**

```python
#!/usr/bin/env python3
"""Setup script for Curiosity Gap Airtable fields.

Run this script to verify all required fields exist in the Ideas table.
Fields that don't exist will be listed for manual creation.

Usage:
    python setup_curiosity_gap_fields.py --check
    python setup_curiosity_gap_fields.py --create (interactive)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from pyairtable import Api

# Required fields for curiosity gap learning
REQUIRED_FIELDS = {
    # Single Select fields
    "Curiosity Structure": {
        "type": "singleSelect",
        "options": ["hidden_flaw", "asymmetric_dg", "time_bomb", "paradigm_shift", "illusion_control", "other"],
    },
    "Thumbnail Approach": {
        "type": "singleSelect",
        "options": ["from_hook", "from_gap"],
    },
    "Title Poll Result": {
        "type": "singleSelect",
        "options": ["human_selected", "auto_selected"],
    },

    # Number fields
    "Structure Confidence": {"type": "number"},
    "CTR 12h": {"type": "number"},
    "CTR 24h": {"type": "number"},
    "CTR 48h": {"type": "number"},

    # Text fields
    "Thumbnail Text": {"type": "singleLineText"},
    "Structure Source": {"type": "multilineText"},
    "Pattern Library Snapshot": {"type": "multilineText"},

    # Checkbox
    "Poll Closed": {"type": "checkbox"},
}


def check_fields():
    """Check which fields exist in Ideas table."""
    api = Api(os.environ["AIRTABLE_API_KEY"])
    base = api.base(os.environ["AIRTABLE_BASE_ID"])
    table = base.table(os.environ.get("AIRTABLE_IDEAS_TABLE_ID", "Ideas"))

    # Get existing fields by fetching schema
    print("Checking Ideas table fields...\n")

    # Try to read one record to get field names
    records = table.all(max_records=1)
    if records:
        existing_fields = set(records[0].get("fields", {}).keys())
    else:
        existing_fields = set()

    missing = []
    found = []

    for field_name, field_spec in REQUIRED_FIELDS.items():
        if field_name in existing_fields:
            found.append(field_name)
        else:
            missing.append((field_name, field_spec))

    print(f"Found {len(found)} fields:")
    for f in found:
        print(f"  [x] {f}")

    if missing:
        print(f"\nMissing {len(missing)} fields:")
        for name, spec in missing:
            print(f"  [ ] {name} ({spec['type']})")
            if spec.get("options"):
                print(f"      Options: {', '.join(spec['options'])}")

        print("\nPlease create these fields in Airtable before proceeding.")
        return False

    print("\nAll required fields exist!")
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Setup Curiosity Gap Airtable fields")
    parser.add_argument("--check", action="store_true", help="Check which fields exist")
    args = parser.parse_args()

    if args.check:
        check_fields()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

### Step 3: Test the setup script

- [ ] **Run check**

```bash
cd skills/video-pipeline && python setup_curiosity_gap_fields.py --check
```

### Step 4: Commit

- [ ] **Commit**

```bash
cd skills/video-pipeline && git add setup_curiosity_gap_fields.py pipeline_constants.py && git commit -m "feat(airtable): Add curiosity gap field setup script

- Lists all required fields for Ideas table
- Checks which fields exist vs missing
- Provides options for Single Select fields"
```

---

## Task 5: Update title_patterns.md Template

**Files:**
- Modify: `skills/video-pipeline/autopilot/memory/title_patterns.md`

### Step 1: Add Curiosity Gap Structures section

- [ ] **Update title_patterns.md**

```markdown
# Title Patterns

Last updated: 2026-03-18
Sample size: 0 videos

---

## Proven Formulas (USE)

*No proven formulas yet.*

---

## Promising Formulas (TESTING)

*No formulas being tested.*

---

## Anti-Patterns (AVOID)

*No confirmed anti-patterns.*

---

## Curiosity Gap Structures

Performance by structure type (5 main + other):

| Structure | Gap Mechanism | Avg CTR | Sample | Status |
|-----------|---------------|---------|--------|--------|
| hidden_flaw | "What mistake are they hiding?" | — | 0 | testing |
| asymmetric_dg | "How does small beat big?" | — | 0 | testing |
| time_bomb | "What trap was set?" | — | 0 | testing |
| paradigm_shift | "What am I missing?" | — | 0 | testing |
| illusion_control | "How does this affect ME?" | — | 0 | testing |
| other | Novel patterns | — | 0 | — |

---

## Structure Performance

| Pattern | Example | CTR Avg | Sample | Verdict |
|---------|---------|---------|--------|---------|
| *No data yet* | | | | |

---

## Notes

Pattern types: question, statement, number, contrast, urgency, curiosity_gap
Formulas are promoted after 3+ videos with CTR >= 4.0%.
```

### Step 2: Commit

- [ ] **Commit**

```bash
cd skills/video-pipeline && git add autopilot/memory/title_patterns.md && git commit -m "feat(memory): Add curiosity gap structures to title_patterns.md

- New Curiosity Gap Structures section
- Documents 5 main structures + other
- Ready for learning system to populate"
```

---

## Task 6: Integration Test — Full Learning Flow

**Files:**
- Create: `skills/video-pipeline/curiosity_gap/tests/test_learning_integration.py`

### Step 1: Write integration test

- [ ] **Write test_learning_integration.py**

```python
# skills/video-pipeline/curiosity_gap/tests/test_learning_integration.py
"""Integration tests for curiosity gap learning flow."""

import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch

from autopilot.learning.learning_extractor import LearningExtractor
from autopilot.learning.memory_writer import MemoryWriter
from autopilot.monitoring.early_warning import CTRVerdict


class TestCuriosityGapLearningIntegration:
    """End-to-end tests for structure learning flow."""

    @pytest.fixture
    def temp_memory_dir(self, tmp_path):
        """Create temporary memory directory."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        # Create initial title_patterns.md
        (memory_dir / "title_patterns.md").write_text("""# Title Patterns

## Curiosity Gap Structures

## Notes
""")
        (memory_dir / "experiments_log.md").write_text("# Experiment Log\n")
        return memory_dir

    def test_full_learning_flow(self, temp_memory_dir):
        """Test: Extract structure learning → Write to memory."""
        extractor = LearningExtractor()
        writer = MemoryWriter(memory_dir=temp_memory_dir)

        # 1. Extract learnings from a high-CTR video
        result = extractor.extract_all(
            video_title="The $100B Mistake Saudi Arabia Is Hiding",
            ctr=5.2,
            thumbnail_override=None,
            modeled_from="competitor_video_123",
            theme_data=None,
            structure="hidden_flaw",
            structure_confidence=78,
        )

        # Verify structure learning extracted
        structure_learnings = [l for l in result.learnings if l.category == "structure"]
        assert len(structure_learnings) == 1
        assert structure_learnings[0].pattern == "hidden_flaw"
        assert result.verdict == CTRVerdict.KEEP

        # 2. Write to memory
        writer.process_result(result)

        # 3. Verify memory files updated
        title_patterns = (temp_memory_dir / "title_patterns.md").read_text()
        assert "hidden_flaw" in title_patterns
        assert "5.2%" in title_patterns
        assert "The $100B Mistake" in title_patterns

        experiments_log = (temp_memory_dir / "experiments_log.md").read_text()
        assert "The $100B Mistake" in experiments_log

    def test_low_ctr_produces_discard(self, temp_memory_dir):
        """Test: Low CTR produces DISCARD verdict and learning."""
        extractor = LearningExtractor()
        writer = MemoryWriter(memory_dir=temp_memory_dir)

        result = extractor.extract_all(
            video_title="The 40-Year Trap Nobody Saw",
            ctr=2.0,  # Below 2.5% threshold
            structure="time_bomb",
            structure_confidence=65,
        )

        assert result.verdict == CTRVerdict.DISCARD

        structure_learnings = [l for l in result.learnings if l.category == "structure"]
        assert len(structure_learnings) == 1
        assert structure_learnings[0].verdict == CTRVerdict.DISCARD

        writer.process_result(result)

        title_patterns = (temp_memory_dir / "title_patterns.md").read_text()
        assert "time_bomb" in title_patterns
        assert "discard" in title_patterns.lower()

    def test_no_structure_produces_no_learning(self, temp_memory_dir):
        """Test: Video without structure produces no structure learning."""
        extractor = LearningExtractor()

        result = extractor.extract_all(
            video_title="Random Video Title",
            ctr=4.0,
            structure=None,
            structure_confidence=None,
        )

        structure_learnings = [l for l in result.learnings if l.category == "structure"]
        assert len(structure_learnings) == 0
```

### Step 2: Run integration tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_learning_integration.py -v
```

Expected: All tests PASS

### Step 3: Commit

- [ ] **Commit**

```bash
cd skills/video-pipeline && git add curiosity_gap/tests/test_learning_integration.py && git commit -m "test(learning): Add curiosity gap learning integration tests

- Full flow: extract → write → verify memory
- Tests KEEP/DISCARD verdicts
- Tests no-structure edge case
- 3 tests passing"
```

---

## Task 7: Run Full Test Suite

### Step 1: Run all curiosity_gap tests

- [ ] **Run curiosity gap tests**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/ -v
```

Expected: All tests PASS (55+ tests)

### Step 2: Run all autopilot tests

- [ ] **Run autopilot tests**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/ -v
```

Expected: All tests PASS (or known pre-existing failures only)

### Step 3: Final commit

- [ ] **Final commit**

```bash
cd skills/video-pipeline && git add . && git commit -m "feat(curiosity-gap): Complete Phase 3 - Learning Integration

Phase 3 delivers:
- Structure category in learning_extractor.py
- Curiosity gap section in memory_writer.py
- CTR 12h/24h/48h milestone tracking in performance_tracker.py
- Airtable field setup script
- Updated title_patterns.md template
- Full integration tests

The learning loop is now closed:
  generate title → publish → measure CTR → extract pattern → update memory"
```

---

## Phase 3 Complete

**Deliverables:**
- `learning_extractor.py` — new `extract_structure_learnings()` method
- `memory_writer.py` — new `update_curiosity_gap_patterns()` method
- `performance_tracker.py` — CTR 12h/24h/48h milestone snapshots
- `setup_curiosity_gap_fields.py` — Airtable field verification script
- `title_patterns.md` — Curiosity Gap Structures section
- Integration tests for full learning flow

**Test Commands:**
```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/ -v
cd skills/video-pipeline && python -m pytest autopilot/tests/ -v
```

**Manual Verification:**
```bash
# Check Airtable fields
python setup_curiosity_gap_fields.py --check

# Test learning extraction
python -c "
from autopilot.learning.learning_extractor import LearningExtractor
e = LearningExtractor()
r = e.extract_all('Test', 5.0, structure='hidden_flaw', structure_confidence=75)
print([l.category for l in r.learnings])
"
```

---

## ⚠️ WIRING AUDIT

Before marking Phase 3 complete, verify ALL of these:

### Entry Points:
- [ ] `learning_extractor.py` is called from `autopilot/autopilot.py` when CTR data is available
- [ ] `performance_tracker.py` runs at 7:00 AM via cron (verify in `setup_cron.sh`)
- [ ] `should_write_ctr_snapshot()` is called in the main update loop

### Data Flow:
- [ ] Airtable field names match exactly: "CTR 12h", "CTR 24h", "CTR 48h"
- [ ] Test one real Airtable read AND one real write on VPS
- [ ] Verify `structure` field is populated when ideas are created (Phase 2 wiring)

### Integration:
- [ ] New imports added to all files that call the new code
- [ ] `autopilot/learning/learning_extractor.py` imports work correctly
- [ ] Memory files are writable on VPS

### Smoke Test:
- [ ] Run `python -m autopilot.learning.learning_extractor --daily` on VPS
- [ ] Check `autopilot/memory/title_patterns.md` for updates
- [ ] Check `/tmp/pipeline-*.log` for errors

---

**Next:** Phase 4 (Autopilot + Slack Integration)
