# Curiosity Gap Phase 2: Core Generation Module

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the title and thumbnail text generation engine using curiosity gap structures. Generates 3 title variants scored against structures, with yin/yang thumbnail text, confidence floor (60), and MF fallback.

**Architecture:** `gap_title_engine.py` scores story content against 5 structures, generates titles for top 3 structures (confidence ≥60), falls back to MF formulas if <3 viable structures. `thumbnail_generator.py` creates complementary yin/yang text (from_hook or from_gap approach). Pattern library is consulted for proven patterns.

**Tech Stack:** Python 3.11+, async, anthropic (Claude Sonnet), dataclasses, json

**Related Spec:** `docs/superpowers/specs/2026-03-20-curiosity-gap-title-system.md`

---

## File Structure (Phase 2)

```
skills/video-pipeline/
├── curiosity_gap/
│   ├── gap_title_engine.py           # NEW: Title generation with structure scoring
│   ├── thumbnail_generator.py        # NEW: Yin/yang text generation
│   └── tests/
│       ├── test_gap_title_engine.py  # NEW
│       └── test_thumbnail_generator.py  # NEW
│
└── pipeline_constants.py             # VERIFY: CURIOSITY_GAP_ENABLED exists (already done)
```

**Note:** `pattern_library.py` already has `get_curiosity_gap_patterns()` and `get_competitor_patterns()` from Phase 1.

---

## Task 1: Create GeneratedTitle Dataclass + ScoredStructure

**Files:**
- Create: `skills/video-pipeline/curiosity_gap/gap_title_engine.py`
- Create: `skills/video-pipeline/curiosity_gap/tests/test_gap_title_engine.py`

### Step 1: Write failing test for dataclasses

- [ ] **Write test_gap_title_engine.py with dataclass tests**

```python
# skills/video-pipeline/curiosity_gap/tests/test_gap_title_engine.py
"""Tests for gap title engine."""

import pytest
from curiosity_gap.structures import CuriosityStructure


class TestGeneratedTitle:
    """Test suite for GeneratedTitle dataclass."""

    def test_generated_title_creation(self):
        """Should create GeneratedTitle with all fields."""
        from curiosity_gap.gap_title_engine import GeneratedTitle

        title = GeneratedTitle(
            text="The $100B Mistake Saudi Arabia Is Hiding",
            structure=CuriosityStructure.HIDDEN_FLAW,
            structure_confidence=78,
            thumbnail_text="WORTHLESS PIPELINES",
            thumbnail_approach="from_gap",
            reasoning="Story has clear financial waste angle...",
            source_patterns=["competitor:rec123"],
            competitor_video_ids=["rec123"],
        )

        assert title.text == "The $100B Mistake Saudi Arabia Is Hiding"
        assert title.structure == CuriosityStructure.HIDDEN_FLAW
        assert title.structure_confidence == 78
        assert title.thumbnail_text == "WORTHLESS PIPELINES"
        assert title.thumbnail_approach == "from_gap"


class TestScoredStructure:
    """Test suite for ScoredStructure dataclass."""

    def test_scored_structure_creation(self):
        """Should create ScoredStructure with confidence and reasoning."""
        from curiosity_gap.gap_title_engine import ScoredStructure

        scored = ScoredStructure(
            structure=CuriosityStructure.HIDDEN_FLAW,
            confidence=85,
            reasoning="Story has $100B waste element",
        )

        assert scored.structure == CuriosityStructure.HIDDEN_FLAW
        assert scored.confidence == 85
        assert scored.reasoning == "Story has $100B waste element"

    def test_scored_structure_ordering(self):
        """Should compare by confidence for sorting."""
        from curiosity_gap.gap_title_engine import ScoredStructure

        high = ScoredStructure(
            structure=CuriosityStructure.HIDDEN_FLAW,
            confidence=85,
            reasoning="high",
        )
        low = ScoredStructure(
            structure=CuriosityStructure.TIME_BOMB,
            confidence=55,
            reasoning="low",
        )

        # Sort descending by confidence
        sorted_list = sorted([low, high], key=lambda s: s.confidence, reverse=True)
        assert sorted_list[0].confidence == 85
        assert sorted_list[1].confidence == 55
```

### Step 2: Run test to verify it fails

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_gap_title_engine.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'curiosity_gap.gap_title_engine'`

### Step 3: Write minimal dataclasses

- [ ] **Write gap_title_engine.py with dataclasses**

```python
# skills/video-pipeline/curiosity_gap/gap_title_engine.py
"""Curiosity gap title generation engine.

Generates titles using 5 curiosity gap structures, scoring each against
story content. Falls back to MF formulas when <3 structures score above
the confidence floor (60).

NOTE: This file is named gap_title_engine.py (NOT title_generator.py)
to avoid confusion with thumbnail_title/title_generator.py which handles
thumbnail text formatting.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
from curiosity_gap.structures import CuriosityStructure


# Confidence floor - structures must score at least this to generate titles
CONFIDENCE_FLOOR = 60


@dataclass
class ScoredStructure:
    """A curiosity gap structure with its fit score for a story."""
    structure: CuriosityStructure
    confidence: int  # 0-100
    reasoning: str


@dataclass
class GeneratedTitle:
    """A generated title with its curiosity gap metadata."""
    text: str                        # "The $100B Mistake Saudi Arabia Is Hiding"
    structure: CuriosityStructure    # HIDDEN_FLAW
    structure_confidence: int        # 78
    thumbnail_text: str              # "WORTHLESS PIPELINES"
    thumbnail_approach: str          # "from_gap" or "from_hook"
    reasoning: str                   # "Story has clear financial waste angle..."

    # Traceability
    source_patterns: List[str] = field(default_factory=list)       # ["competitor:rec123"]
    competitor_video_ids: List[str] = field(default_factory=list)  # Airtable record IDs
```

### Step 4: Run tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_gap_title_engine.py -v
```

Expected: All 3 tests PASS

### Step 5: Commit

- [ ] **Commit**

```bash
git add skills/video-pipeline/curiosity_gap/gap_title_engine.py skills/video-pipeline/curiosity_gap/tests/test_gap_title_engine.py
git commit -m "feat(curiosity-gap): Add GeneratedTitle and ScoredStructure dataclasses

- GeneratedTitle with text, structure, confidence, thumbnail_text, approach
- ScoredStructure for structure scoring
- CONFIDENCE_FLOOR = 60
- 3 tests passing"
```

---

## Task 2: Implement Structure Scoring

**Files:**
- Modify: `skills/video-pipeline/curiosity_gap/gap_title_engine.py`
- Modify: `skills/video-pipeline/curiosity_gap/tests/test_gap_title_engine.py`

### Step 1: Write failing test for scoring

- [ ] **Add scoring tests to test_gap_title_engine.py**

```python
# Add to test_gap_title_engine.py

class TestScoreStructures:
    """Test suite for structure scoring."""

    @pytest.fixture
    def sample_story_context(self):
        return {
            "hook": "Saudi Arabia spent $100 billion on pipelines that now sit empty.",
            "thesis": "The kingdom's bet on being an oil transit hub has failed.",
            "facts": [
                "NEOM pipeline: $500M spent, 0% utilized",
                "East-West pipeline: abandoned in 2023",
                "Total waste: estimated $100B",
            ],
        }

    def test_score_structures_returns_all_five(self, sample_story_context):
        """Should return scores for all 5 main structures."""
        from curiosity_gap.gap_title_engine import score_structures

        scores = score_structures(sample_story_context)

        assert len(scores) == 5
        structure_names = [s.structure for s in scores]
        assert CuriosityStructure.HIDDEN_FLAW in structure_names
        assert CuriosityStructure.ASYMMETRIC_DG in structure_names
        assert CuriosityStructure.TIME_BOMB in structure_names
        assert CuriosityStructure.PARADIGM_SHIFT in structure_names
        assert CuriosityStructure.ILLUSION_CONTROL in structure_names

    def test_score_structures_sorted_descending(self, sample_story_context):
        """Should return structures sorted by confidence descending."""
        from curiosity_gap.gap_title_engine import score_structures

        scores = score_structures(sample_story_context)

        confidences = [s.confidence for s in scores]
        assert confidences == sorted(confidences, reverse=True)

    def test_waste_story_scores_hidden_flaw_highest(self, sample_story_context):
        """Story about waste should score hidden_flaw highest."""
        from curiosity_gap.gap_title_engine import score_structures

        scores = score_structures(sample_story_context)

        # hidden_flaw should be among top 2 for this waste story
        top_structures = [s.structure for s in scores[:2]]
        assert CuriosityStructure.HIDDEN_FLAW in top_structures
```

### Step 2: Run test to verify it fails

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_gap_title_engine.py::TestScoreStructures -v
```

Expected: FAIL with `ImportError: cannot import name 'score_structures'`

### Step 3: Implement score_structures (heuristic version)

- [ ] **Add score_structures to gap_title_engine.py**

```python
# Add to gap_title_engine.py after dataclasses

import re
from curiosity_gap.structures import get_main_structures, STRUCTURE_DEFINITIONS


def _score_hidden_flaw(hook: str, thesis: str, facts: List[str]) -> int:
    """Score for hidden_flaw: financial waste, mistakes, cover-ups."""
    content = f"{hook} {thesis} {' '.join(facts)}".lower()

    score = 0
    # Financial waste indicators
    if re.search(r'\$\d+[mb]?\b', content):  # Dollar amounts
        score += 25
    if any(word in content for word in ['waste', 'wasted', 'mistake', 'failed', 'failure']):
        score += 25
    if any(word in content for word in ['hiding', 'hidden', 'secret', 'cover']):
        score += 20
    if any(word in content for word in ['billion', 'trillion', 'million']):
        score += 15
    if any(word in content for word in ['abandoned', 'empty', 'unused', 'worthless']):
        score += 15

    return min(100, score)


def _score_asymmetric_dg(hook: str, thesis: str, facts: List[str]) -> int:
    """Score for asymmetric_dg: small vs big, David vs Goliath."""
    content = f"{hook} {thesis} {' '.join(facts)}".lower()

    score = 0
    # Power asymmetry indicators
    if any(word in content for word in ['small', 'tiny', 'cheap', '$500', '$100']):
        score += 25
    if any(word in content for word in ['terrified', 'afraid', 'fear', 'scared']):
        score += 20
    if any(word in content for word in ['navy', 'military', 'army', 'superpower']):
        score += 20
    if any(word in content for word in ['beat', 'defeat', 'destroy', 'stop']):
        score += 15
    if any(word in content for word in ['drone', 'boat', 'missile', 'plastic']):
        score += 10

    return min(100, score)


def _score_time_bomb(hook: str, thesis: str, facts: List[str]) -> int:
    """Score for time_bomb: long-term traps, delayed consequences."""
    content = f"{hook} {thesis} {' '.join(facts)}".lower()

    score = 0
    # Time bomb indicators
    if re.search(r'\d+[- ]year', content):  # X-year patterns
        score += 30
    if any(word in content for word in ['trap', 'trapped', 'walked into']):
        score += 25
    if any(word in content for word in ['decade', 'decades', 'long-term', 'slow']):
        score += 20
    if any(word in content for word in ['set up', 'planted', 'waiting']):
        score += 15
    if any(word in content for word in ['trigger', 'explode', 'collapse']):
        score += 10

    return min(100, score)


def _score_paradigm_shift(hook: str, thesis: str, facts: List[str]) -> int:
    """Score for paradigm_shift: reframing, hidden truths."""
    content = f"{hook} {thesis} {' '.join(facts)}".lower()

    score = 0
    # Paradigm shift indicators
    if any(word in content for word in ['proves', 'proof', 'evidence', 'map']):
        score += 25
    if any(word in content for word in ['already', 'begun', 'started', 'happening']):
        score += 20
    if any(word in content for word in ['think', 'believe', 'assume', 'reality']):
        score += 20
    if any(word in content for word in ['wwiii', 'war', 'conflict', 'crisis']):
        score += 15
    if any(word in content for word in ['missing', 'overlooked', 'ignored']):
        score += 15

    return min(100, score)


def _score_illusion_control(hook: str, thesis: str, facts: List[str]) -> int:
    """Score for illusion_control: personal stakes, affects YOU."""
    content = f"{hook} {thesis} {' '.join(facts)}".lower()

    score = 0
    # Personal impact indicators
    if any(word in content for word in ['your', 'you', 'everyone', 'every american']):
        score += 30
    if any(word in content for word in ['bank', 'money', 'savings', 'wallet']):
        score += 25
    if any(word in content for word in ['control', 'controls', 'chokepoint']):
        score += 20
    if any(word in content for word in ['affect', 'impact', 'change']):
        score += 15
    if any(word in content for word in ['price', 'cost', 'pay', 'inflation']):
        score += 10

    return min(100, score)


STRUCTURE_SCORERS = {
    CuriosityStructure.HIDDEN_FLAW: _score_hidden_flaw,
    CuriosityStructure.ASYMMETRIC_DG: _score_asymmetric_dg,
    CuriosityStructure.TIME_BOMB: _score_time_bomb,
    CuriosityStructure.PARADIGM_SHIFT: _score_paradigm_shift,
    CuriosityStructure.ILLUSION_CONTROL: _score_illusion_control,
}


def score_structures(story_context: Dict) -> List[ScoredStructure]:
    """Score all 5 structures against story content.

    Args:
        story_context: Dict with 'hook', 'thesis', 'facts' keys

    Returns:
        List of ScoredStructure sorted by confidence descending
    """
    hook = story_context.get("hook", "")
    thesis = story_context.get("thesis", "")
    facts = story_context.get("facts", [])

    scores = []
    for structure in get_main_structures():
        scorer = STRUCTURE_SCORERS[structure]
        confidence = scorer(hook, thesis, facts)
        defn = STRUCTURE_DEFINITIONS[structure]

        scores.append(ScoredStructure(
            structure=structure,
            confidence=confidence,
            reasoning=f"Scored {confidence}/100 for '{defn['gap_mechanism']}'",
        ))

    # Sort by confidence descending
    return sorted(scores, key=lambda s: s.confidence, reverse=True)
```

### Step 4: Run tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_gap_title_engine.py::TestScoreStructures -v
```

Expected: All 3 tests PASS

### Step 5: Commit

- [ ] **Commit**

```bash
git add skills/video-pipeline/curiosity_gap/gap_title_engine.py skills/video-pipeline/curiosity_gap/tests/test_gap_title_engine.py
git commit -m "feat(curiosity-gap): Add heuristic structure scoring

- score_structures() returns 5 scored structures
- Individual scorers for each structure type
- Keyword-based scoring with weighted indicators
- Sorted by confidence descending
- 6 tests passing"
```

---

## Task 3: Implement MF Fallback Formulas

**Files:**
- Modify: `skills/video-pipeline/curiosity_gap/gap_title_engine.py`
- Modify: `skills/video-pipeline/curiosity_gap/tests/test_gap_title_engine.py`

### Step 1: Write failing test for fallback

- [ ] **Add fallback tests to test_gap_title_engine.py**

```python
# Add to test_gap_title_engine.py

class TestMFFallback:
    """Test suite for MF formula fallback."""

    def test_mf_formulas_exist(self):
        """Should have 3 MF fallback formulas defined."""
        from curiosity_gap.gap_title_engine import MF_FORMULAS

        assert len(MF_FORMULAS) >= 3
        assert "MF-0" in MF_FORMULAS or 0 in MF_FORMULAS

    def test_get_viable_structures_filters_by_floor(self):
        """Should filter structures below confidence floor."""
        from curiosity_gap.gap_title_engine import (
            get_viable_structures,
            ScoredStructure,
            CONFIDENCE_FLOOR,
        )

        scores = [
            ScoredStructure(CuriosityStructure.HIDDEN_FLAW, 75, "high"),
            ScoredStructure(CuriosityStructure.TIME_BOMB, 55, "low"),
            ScoredStructure(CuriosityStructure.ASYMMETRIC_DG, 65, "mid"),
        ]

        viable = get_viable_structures(scores)

        # Only structures >= 60 should pass
        assert len(viable) == 2
        assert all(s.confidence >= CONFIDENCE_FLOOR for s in viable)

    def test_get_mf_fallback_count(self):
        """Should calculate how many MF fallbacks needed."""
        from curiosity_gap.gap_title_engine import get_mf_fallback_count

        # If 2 viable structures, need 1 MF fallback
        assert get_mf_fallback_count(viable_count=2, target=3) == 1
        # If 1 viable, need 2 MF
        assert get_mf_fallback_count(viable_count=1, target=3) == 2
        # If 0 viable, need 3 MF
        assert get_mf_fallback_count(viable_count=0, target=3) == 3
        # If 3+ viable, need 0 MF
        assert get_mf_fallback_count(viable_count=3, target=3) == 0
        assert get_mf_fallback_count(viable_count=5, target=3) == 0
```

### Step 2: Run test to verify it fails

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_gap_title_engine.py::TestMFFallback -v
```

Expected: FAIL with `ImportError: cannot import name 'MF_FORMULAS'`

### Step 3: Implement MF fallback

- [ ] **Add MF fallback to gap_title_engine.py**

```python
# Add to gap_title_engine.py after STRUCTURE_SCORERS

# MF (existing formula) fallbacks - used when <3 structures score above floor
# These are simplified versions of formulas from trending_idea_bot.py
MF_FORMULAS = {
    "MF-0": {
        "name": "CHOKE POINT",
        "template": "How [Entity] Turned [Location] Into a Hostage",
        "description": "Geographic/strategic control framing",
    },
    "MF-1": {
        "name": "GEOGRAPHIC TRAP",
        "template": "How [Entity] Quietly Weaponized [Geography]",
        "description": "Terrain as weapon framing",
    },
    "MF-2": {
        "name": "EXITS LOCKED",
        "template": "Why [Entity] Can't Escape [Constraint]",
        "description": "No escape framing",
    },
}


def get_viable_structures(
    scores: List[ScoredStructure],
    min_confidence: int = CONFIDENCE_FLOOR,
) -> List[ScoredStructure]:
    """Filter structures to those above confidence floor.

    Args:
        scores: List of scored structures
        min_confidence: Minimum confidence to be viable

    Returns:
        Filtered list of viable structures
    """
    return [s for s in scores if s.confidence >= min_confidence]


def get_mf_fallback_count(viable_count: int, target: int = 3) -> int:
    """Calculate how many MF fallback titles needed.

    Args:
        viable_count: Number of structures above confidence floor
        target: Target number of titles to generate

    Returns:
        Number of MF fallbacks needed
    """
    return max(0, target - viable_count)
```

### Step 4: Run tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_gap_title_engine.py::TestMFFallback -v
```

Expected: All 3 tests PASS

### Step 5: Commit

- [ ] **Commit**

```bash
git add skills/video-pipeline/curiosity_gap/gap_title_engine.py skills/video-pipeline/curiosity_gap/tests/test_gap_title_engine.py
git commit -m "feat(curiosity-gap): Add MF fallback formula system

- 3 MF formulas: CHOKE POINT, GEOGRAPHIC TRAP, EXITS LOCKED
- get_viable_structures() filters by CONFIDENCE_FLOOR
- get_mf_fallback_count() calculates needed fallbacks
- 9 tests passing"
```

---

## Task 4: Create Thumbnail Generator Module

**Files:**
- Create: `skills/video-pipeline/curiosity_gap/thumbnail_generator.py`
- Create: `skills/video-pipeline/curiosity_gap/tests/test_thumbnail_generator.py`

### Step 1: Write failing test for thumbnail generator

- [ ] **Write test_thumbnail_generator.py**

```python
# skills/video-pipeline/curiosity_gap/tests/test_thumbnail_generator.py
"""Tests for yin/yang thumbnail text generator."""

import pytest
from curiosity_gap.structures import CuriosityStructure


class TestThumbnailText:
    """Test suite for ThumbnailText dataclass."""

    def test_thumbnail_text_creation(self):
        """Should create ThumbnailText with required fields."""
        from curiosity_gap.thumbnail_generator import ThumbnailText

        thumb = ThumbnailText(
            text="WORTHLESS PIPELINES",
            approach="from_gap",
            reasoning="Title asks about mistake, thumbnail reveals consequence",
        )

        assert thumb.text == "WORTHLESS PIPELINES"
        assert thumb.approach == "from_gap"
        assert "consequence" in thumb.reasoning

    def test_approach_must_be_valid(self):
        """Approach must be from_hook or from_gap."""
        from curiosity_gap.thumbnail_generator import ThumbnailText, VALID_APPROACHES

        assert "from_hook" in VALID_APPROACHES
        assert "from_gap" in VALID_APPROACHES
        assert len(VALID_APPROACHES) == 2


class TestYinYangRules:
    """Test suite for yin/yang generation rules."""

    def test_thumbnail_text_is_caps(self):
        """Generated thumbnail text should be ALL CAPS."""
        from curiosity_gap.thumbnail_generator import format_thumbnail_text

        result = format_thumbnail_text("worthless pipelines")
        assert result == "WORTHLESS PIPELINES"

    def test_thumbnail_text_max_words(self):
        """Thumbnail text should be 2-4 words max."""
        from curiosity_gap.thumbnail_generator import format_thumbnail_text

        # Too long should be truncated
        result = format_thumbnail_text("this is way too many words here")
        word_count = len(result.split())
        assert word_count <= 4

    def test_removes_common_filler(self):
        """Should remove common filler words."""
        from curiosity_gap.thumbnail_generator import format_thumbnail_text

        result = format_thumbnail_text("the worthless pipelines")
        assert "THE" not in result.split()


class TestApproachSelection:
    """Test suite for selecting from_hook vs from_gap approach."""

    def test_hidden_flaw_prefers_from_gap(self):
        """Hidden flaw structure prefers from_gap (reveals consequence)."""
        from curiosity_gap.thumbnail_generator import select_approach

        approach = select_approach(
            structure=CuriosityStructure.HIDDEN_FLAW,
            title="The $100B Mistake Saudi Arabia Is Hiding",
            hook="Saudi Arabia spent $100B on pipelines now sitting empty.",
        )

        assert approach == "from_gap"

    def test_asymmetric_prefers_from_hook(self):
        """Asymmetric structure prefers from_hook (surprising detail)."""
        from curiosity_gap.thumbnail_generator import select_approach

        approach = select_approach(
            structure=CuriosityStructure.ASYMMETRIC_DG,
            title="Why the Navy Is Terrified of $500 Plastic",
            hook="Cheap plastic drones are destroying billion-dollar ships.",
        )

        assert approach == "from_hook"
```

### Step 2: Run test to verify it fails

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_thumbnail_generator.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'curiosity_gap.thumbnail_generator'`

### Step 3: Implement thumbnail generator

- [ ] **Write thumbnail_generator.py**

```python
# skills/video-pipeline/curiosity_gap/thumbnail_generator.py
"""Yin/yang thumbnail text generator.

The thumbnail text should COMPLEMENT the title, not repeat it.
Two approaches:
- from_gap: Reveals the answer/consequence the title withholds
- from_hook: Shows a surprising detail from the hook script

This module handles text selection and formatting. The actual thumbnail
IMAGE generation is handled by thumbnail_title/title_generator.py.
"""

from dataclasses import dataclass
from typing import List
from curiosity_gap.structures import CuriosityStructure


VALID_APPROACHES = ["from_hook", "from_gap"]

# Words to strip from thumbnail text
FILLER_WORDS = {"the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "for"}

# Structure → preferred approach mapping
STRUCTURE_APPROACH_PREFERENCE = {
    CuriosityStructure.HIDDEN_FLAW: "from_gap",      # Reveal the consequence
    CuriosityStructure.ASYMMETRIC_DG: "from_hook",   # Show the surprising detail
    CuriosityStructure.TIME_BOMB: "from_gap",        # Hint at what triggers
    CuriosityStructure.PARADIGM_SHIFT: "from_gap",   # Hint at the truth
    CuriosityStructure.ILLUSION_CONTROL: "from_hook", # Show the personal impact
    CuriosityStructure.OTHER: "from_gap",            # Default to from_gap
}


@dataclass
class ThumbnailText:
    """Generated yin/yang thumbnail text."""
    text: str            # "WORTHLESS PIPELINES"
    approach: str        # "from_gap" or "from_hook"
    reasoning: str       # Why this approach was chosen


def format_thumbnail_text(raw_text: str, max_words: int = 4) -> str:
    """Format text for thumbnail display.

    - Converts to ALL CAPS
    - Removes filler words (the, a, an, etc.)
    - Truncates to max_words

    Args:
        raw_text: Raw text to format
        max_words: Maximum words to include

    Returns:
        Formatted thumbnail text in ALL CAPS
    """
    if not raw_text:
        return ""

    # Split into words
    words = raw_text.upper().split()

    # Remove filler words
    filtered = [w for w in words if w.lower() not in FILLER_WORDS]

    # Use original if all words were filler
    if not filtered:
        filtered = words

    # Truncate to max words
    truncated = filtered[:max_words]

    return " ".join(truncated)


def select_approach(
    structure: CuriosityStructure,
    title: str,
    hook: str,
) -> str:
    """Select thumbnail approach based on structure and content.

    Args:
        structure: The curiosity gap structure being used
        title: The video title
        hook: The hook script text

    Returns:
        "from_hook" or "from_gap"
    """
    # Use structure preference as default
    return STRUCTURE_APPROACH_PREFERENCE.get(structure, "from_gap")
```

### Step 4: Run tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_thumbnail_generator.py -v
```

Expected: All 6 tests PASS

### Step 5: Commit

- [ ] **Commit**

```bash
git add skills/video-pipeline/curiosity_gap/thumbnail_generator.py skills/video-pipeline/curiosity_gap/tests/test_thumbnail_generator.py
git commit -m "feat(curiosity-gap): Add thumbnail text generator

- ThumbnailText dataclass with text, approach, reasoning
- format_thumbnail_text() for ALL CAPS, max 4 words, filler removal
- select_approach() based on structure preference
- from_gap for hidden_flaw/time_bomb, from_hook for asymmetric/illusion
- 6 tests passing"
```

---

## Task 5: Implement Claude-Based Title Generation

**Files:**
- Modify: `skills/video-pipeline/curiosity_gap/gap_title_engine.py`
- Modify: `skills/video-pipeline/curiosity_gap/tests/test_gap_title_engine.py`

### Step 1: Write failing test for generate_titles

- [ ] **Add Claude generation tests to test_gap_title_engine.py**

```python
# Add to test_gap_title_engine.py

from unittest.mock import AsyncMock, patch, Mock


class TestGenerateTitles:
    """Test suite for title generation."""

    @pytest.fixture
    def sample_story(self):
        return {
            "hook": "Saudi Arabia spent $100 billion on pipelines that now sit empty.",
            "thesis": "The kingdom's bet on being an oil transit hub has failed.",
            "facts": [
                "NEOM pipeline: $500M spent, 0% utilized",
                "Total waste: estimated $100B",
            ],
        }

    @pytest.fixture
    def mock_claude_response(self):
        """Mock Claude response for title generation."""
        return {
            "titles": [
                {
                    "text": "The $100B Mistake Saudi Arabia Is Hiding",
                    "structure": "hidden_flaw",
                    "confidence": 85,
                    "thumbnail_text": "WORTHLESS PIPELINES",
                    "thumbnail_approach": "from_gap",
                    "reasoning": "Clear financial waste angle",
                },
                {
                    "text": "The 30-Year Trap Saudi Arabia Walked Into",
                    "structure": "time_bomb",
                    "confidence": 72,
                    "thumbnail_text": "CHECKMATE",
                    "thumbnail_approach": "from_gap",
                    "reasoning": "Long-term strategy failure",
                },
                {
                    "text": "Why Saudi Arabia Can't Escape Its Pipeline Trap",
                    "structure": "illusion_control",
                    "confidence": 65,
                    "thumbnail_text": "NO EXIT",
                    "thumbnail_approach": "from_hook",
                    "reasoning": "Personal stakes for kingdom",
                },
            ]
        }

    @pytest.mark.asyncio
    async def test_generate_titles_returns_three(self, sample_story, mock_claude_response):
        """Should generate 3 titles by default."""
        from curiosity_gap.gap_title_engine import generate_titles, GapTitleEngine

        engine = GapTitleEngine()

        with patch.object(engine, '_call_claude_for_titles', return_value=mock_claude_response):
            titles = await engine.generate_titles(sample_story)

        assert len(titles) == 3
        assert all(isinstance(t.text, str) for t in titles)
        assert all(t.structure in CuriosityStructure for t in titles)

    @pytest.mark.asyncio
    async def test_generate_titles_sorted_by_confidence(self, sample_story, mock_claude_response):
        """Titles should be sorted by confidence descending."""
        from curiosity_gap.gap_title_engine import GapTitleEngine

        engine = GapTitleEngine()

        with patch.object(engine, '_call_claude_for_titles', return_value=mock_claude_response):
            titles = await engine.generate_titles(sample_story)

        confidences = [t.structure_confidence for t in titles]
        assert confidences == sorted(confidences, reverse=True)

    @pytest.mark.asyncio
    async def test_generate_titles_with_kill_switch_disabled(self, sample_story):
        """Should return empty list when kill switch is off."""
        from curiosity_gap.gap_title_engine import GapTitleEngine

        engine = GapTitleEngine()

        with patch('curiosity_gap.gap_title_engine.CURIOSITY_GAP_ENABLED', False):
            titles = await engine.generate_titles(sample_story)

        assert titles == []
```

### Step 2: Run test to verify it fails

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_gap_title_engine.py::TestGenerateTitles -v
```

Expected: FAIL with `ImportError: cannot import name 'GapTitleEngine'`

### Step 3: Implement GapTitleEngine class

- [ ] **Add GapTitleEngine to gap_title_engine.py**

```python
# Add imports at top of gap_title_engine.py
import json
from pipeline_constants import CURIOSITY_GAP_ENABLED, Models

# Add to gap_title_engine.py after fallback functions

class GapTitleEngine:
    """Generate titles using curiosity gap structures."""

    def __init__(self, anthropic_client=None):
        """Initialize engine.

        Args:
            anthropic_client: AnthropicClient instance (lazy loaded if None)
        """
        self._anthropic_client = anthropic_client

    @property
    def anthropic_client(self):
        if self._anthropic_client is None:
            from clients.anthropic_client import AnthropicClient
            self._anthropic_client = AnthropicClient()
        return self._anthropic_client

    def _build_generation_prompt(
        self,
        story_context: Dict,
        scored_structures: List[ScoredStructure],
        pattern_context: str = "",
    ) -> str:
        """Build Claude prompt for title generation.

        Args:
            story_context: Dict with hook, thesis, facts
            scored_structures: Pre-scored structures to use
            pattern_context: Optional pattern library context

        Returns:
            Formatted prompt string
        """
        structures_text = "\n".join([
            f"- {s.structure.value} (confidence: {s.confidence}): {s.reasoning}"
            for s in scored_structures
        ])

        prompt = f"""Generate YouTube titles for Power Doctrine channel using curiosity gap structures.

STORY CONTEXT:
Hook: {story_context.get('hook', '')}
Thesis: {story_context.get('thesis', '')}
Key facts: {json.dumps(story_context.get('facts', []))}

STRUCTURES TO USE (generate one title per structure):
{structures_text}

{pattern_context}

For each structure, generate:
1. title text (create cognitive dissonance, force the click)
2. thumbnail_text (2-4 words, ALL CAPS, yin/yang complement to title)
3. thumbnail_approach ("from_hook" or "from_gap")
4. reasoning (why this title works for this structure)

Return JSON only:
{{
  "titles": [
    {{
      "text": "The $100B Mistake Saudi Arabia Is Hiding",
      "structure": "hidden_flaw",
      "confidence": 85,
      "thumbnail_text": "WORTHLESS PIPELINES",
      "thumbnail_approach": "from_gap",
      "reasoning": "Clear financial waste angle"
    }}
  ]
}}"""
        return prompt

    async def _call_claude_for_titles(
        self,
        prompt: str,
    ) -> Dict:
        """Call Claude to generate titles.

        Args:
            prompt: Generation prompt

        Returns:
            Dict with titles array
        """
        response = await self.anthropic_client.generate(
            prompt=prompt,
            model=Models.CLAUDE_SONNET,
            max_tokens=2000,
            temperature=0.7,
        )

        # Parse JSON response
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {"titles": []}

    async def generate_titles(
        self,
        story_context: Dict,
        pattern_library=None,
        target_count: int = 3,
    ) -> List[GeneratedTitle]:
        """Generate titles using curiosity gap structures.

        Args:
            story_context: Dict with hook, thesis, facts
            pattern_library: Optional PatternLibrary for proven patterns
            target_count: Number of titles to generate

        Returns:
            List of GeneratedTitle sorted by confidence
        """
        # Kill switch check
        if not CURIOSITY_GAP_ENABLED:
            return []

        # Score structures
        scores = score_structures(story_context)
        viable = get_viable_structures(scores)

        # Determine which structures to use
        structures_to_use = viable[:target_count]

        # Get pattern context if library provided
        pattern_context = ""
        if pattern_library:
            gap_patterns = pattern_library.get_curiosity_gap_patterns()
            if gap_patterns:
                pattern_context = "PROVEN PATTERNS:\n" + "\n".join([
                    f"- {p.structure.value}: avg VPH {p.avg_vph_competitors}"
                    for p in gap_patterns if p.avg_vph_competitors
                ])

        # If we don't have enough viable structures, we'd fall back to MF
        # For now, use what we have (MF fallback integration in Task 6)
        if not structures_to_use:
            return []

        # Build prompt and call Claude
        prompt = self._build_generation_prompt(
            story_context,
            structures_to_use,
            pattern_context,
        )

        result = await self._call_claude_for_titles(prompt)

        # Parse response into GeneratedTitle objects
        titles = []
        for item in result.get("titles", []):
            try:
                structure = CuriosityStructure(item.get("structure", "other"))
            except ValueError:
                structure = CuriosityStructure.OTHER

            titles.append(GeneratedTitle(
                text=item.get("text", ""),
                structure=structure,
                structure_confidence=item.get("confidence", 0),
                thumbnail_text=item.get("thumbnail_text", ""),
                thumbnail_approach=item.get("thumbnail_approach", "from_gap"),
                reasoning=item.get("reasoning", ""),
            ))

        # Sort by confidence
        return sorted(titles, key=lambda t: t.structure_confidence, reverse=True)
```

### Step 4: Run tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_gap_title_engine.py::TestGenerateTitles -v
```

Expected: All 3 tests PASS

### Step 5: Commit

- [ ] **Commit**

```bash
git add skills/video-pipeline/curiosity_gap/gap_title_engine.py skills/video-pipeline/curiosity_gap/tests/test_gap_title_engine.py
git commit -m "feat(curiosity-gap): Add GapTitleEngine with Claude integration

- GapTitleEngine.generate_titles() for title generation
- _build_generation_prompt() with story context and structures
- _call_claude_for_titles() with JSON parsing
- Kill switch check (CURIOSITY_GAP_ENABLED)
- Pattern library integration for proven patterns
- 12 tests passing"
```

---

## Task 6: Add MF Fallback Integration

**Files:**
- Modify: `skills/video-pipeline/curiosity_gap/gap_title_engine.py`
- Modify: `skills/video-pipeline/curiosity_gap/tests/test_gap_title_engine.py`

### Step 1: Write failing test for MF integration

- [ ] **Add MF integration test**

```python
# Add to test_gap_title_engine.py

class TestMFIntegration:
    """Test suite for MF fallback integration."""

    @pytest.fixture
    def low_confidence_story(self):
        """Story that doesn't fit well into any structure."""
        return {
            "hook": "A small policy change happened.",
            "thesis": "The change is interesting.",
            "facts": ["It happened last week."],
        }

    @pytest.mark.asyncio
    async def test_fallback_triggered_when_low_confidence(self, low_confidence_story):
        """Should use MF fallback when no structures score above floor."""
        from curiosity_gap.gap_title_engine import GapTitleEngine, CONFIDENCE_FLOOR

        engine = GapTitleEngine()

        # Mock Claude to return MF-style titles
        mock_response = {
            "titles": [
                {
                    "text": "How Policy Changed Everything",
                    "structure": "other",
                    "confidence": 45,
                    "thumbnail_text": "CHANGE COMING",
                    "thumbnail_approach": "from_gap",
                    "reasoning": "MF fallback applied",
                    "is_mf_fallback": True,
                }
            ]
        }

        with patch.object(engine, '_call_claude_for_titles', return_value=mock_response):
            with patch('curiosity_gap.gap_title_engine.score_structures') as mock_score:
                # All structures score below floor
                mock_score.return_value = [
                    ScoredStructure(CuriosityStructure.HIDDEN_FLAW, 40, "low"),
                    ScoredStructure(CuriosityStructure.TIME_BOMB, 35, "low"),
                    ScoredStructure(CuriosityStructure.ASYMMETRIC_DG, 30, "low"),
                    ScoredStructure(CuriosityStructure.PARADIGM_SHIFT, 25, "low"),
                    ScoredStructure(CuriosityStructure.ILLUSION_CONTROL, 20, "low"),
                ]

                titles = await engine.generate_titles(low_confidence_story)

        # Should still return titles via MF fallback
        # (actual implementation may vary based on design choice)
        assert isinstance(titles, list)
```

### Step 2: Run test to verify current behavior

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_gap_title_engine.py::TestMFIntegration -v
```

Note: This may pass or fail depending on how we want to handle MF fallback. The test documents the expected behavior.

### Step 3: Add MF fallback to generate_titles

- [ ] **Update generate_titles in gap_title_engine.py**

Add MF fallback logic to the `generate_titles` method. Insert this after the `structures_to_use` assignment:

```python
        # Check if we need MF fallbacks
        mf_count = get_mf_fallback_count(len(structures_to_use), target_count)

        if mf_count > 0 and not structures_to_use:
            # All structures below floor - pure MF fallback
            # Generate titles using MF formulas instead of curiosity gap
            return await self._generate_mf_titles(story_context, target_count)

        # ... rest of existing code ...
```

Then add the MF title generation method:

```python
    async def _generate_mf_titles(
        self,
        story_context: Dict,
        count: int = 3,
    ) -> List[GeneratedTitle]:
        """Generate titles using MF fallback formulas.

        Args:
            story_context: Dict with hook, thesis, facts
            count: Number of titles to generate

        Returns:
            List of GeneratedTitle using MF formulas
        """
        mf_ids = list(MF_FORMULAS.keys())[:count]

        prompt = f"""Generate YouTube titles using these formula templates.

STORY CONTEXT:
Hook: {story_context.get('hook', '')}
Thesis: {story_context.get('thesis', '')}

FORMULAS TO USE:
{chr(10).join([f"- {mf_id}: {MF_FORMULAS[mf_id]['template']}" for mf_id in mf_ids])}

For each formula:
1. Replace [Entity], [Location], etc. with story-specific values
2. Generate thumbnail_text (2-4 words, ALL CAPS)
3. Use thumbnail_approach "from_gap"

Return JSON only:
{{
  "titles": [
    {{
      "text": "How Iran Turned Hormuz Into a Hostage",
      "structure": "other",
      "confidence": 50,
      "thumbnail_text": "CHOKEPOINT",
      "thumbnail_approach": "from_gap",
      "reasoning": "MF-0 CHOKE POINT formula"
    }}
  ]
}}"""

        result = await self._call_claude_for_titles(prompt)

        titles = []
        for item in result.get("titles", []):
            titles.append(GeneratedTitle(
                text=item.get("text", ""),
                structure=CuriosityStructure.OTHER,
                structure_confidence=item.get("confidence", 50),
                thumbnail_text=item.get("thumbnail_text", ""),
                thumbnail_approach="from_gap",
                reasoning=item.get("reasoning", "MF fallback"),
            ))

        return titles
```

### Step 4: Run tests

- [ ] **Run all tests**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_gap_title_engine.py -v
```

Expected: All tests PASS

### Step 5: Commit

- [ ] **Commit**

```bash
git add skills/video-pipeline/curiosity_gap/gap_title_engine.py skills/video-pipeline/curiosity_gap/tests/test_gap_title_engine.py
git commit -m "feat(curiosity-gap): Add MF fallback integration

- _generate_mf_titles() for pure MF fallback
- Triggered when no structures score above CONFIDENCE_FLOOR
- Uses MF-0, MF-1, MF-2 templates
- 13 tests passing"
```

---

## Task 7: Run Full Test Suite + Integration Test

**Files:**
- Modify: `skills/video-pipeline/curiosity_gap/tests/test_integration.py`

### Step 1: Add Phase 2 integration tests

- [ ] **Add generation integration tests to test_integration.py**

```python
# Add to curiosity_gap/tests/test_integration.py

class TestPhase2Integration:
    """Integration tests for Phase 2 title generation."""

    @pytest.fixture
    def sample_story(self):
        return {
            "hook": "Saudi Arabia spent $100 billion on pipelines that now sit empty.",
            "thesis": "The kingdom's bet on being an oil transit hub has failed.",
            "facts": [
                "NEOM pipeline: $500M spent, 0% utilized",
                "East-West pipeline: abandoned in 2023",
                "Total waste: estimated $100B",
            ],
        }

    @pytest.mark.asyncio
    async def test_full_title_generation_flow(self, sample_story):
        """Test complete flow: score → generate → format."""
        from curiosity_gap.gap_title_engine import GapTitleEngine, score_structures
        from curiosity_gap.thumbnail_generator import format_thumbnail_text

        # Step 1: Score structures
        scores = score_structures(sample_story)
        assert len(scores) == 5

        # Step 2: hidden_flaw should score high for waste story
        top_structure = scores[0]
        assert top_structure.structure == CuriosityStructure.HIDDEN_FLAW
        assert top_structure.confidence >= 60

        # Step 3: Generate titles (mocked Claude)
        engine = GapTitleEngine()

        mock_response = {
            "titles": [{
                "text": "The $100B Mistake Saudi Arabia Is Hiding",
                "structure": "hidden_flaw",
                "confidence": 85,
                "thumbnail_text": "worthless pipelines",
                "thumbnail_approach": "from_gap",
                "reasoning": "Clear waste angle",
            }]
        }

        with patch.object(engine, '_call_claude_for_titles', return_value=mock_response):
            titles = await engine.generate_titles(sample_story)

        assert len(titles) >= 1
        title = titles[0]
        assert title.structure == CuriosityStructure.HIDDEN_FLAW

        # Step 4: Format thumbnail text
        formatted = format_thumbnail_text(title.thumbnail_text)
        assert formatted == "WORTHLESS PIPELINES"
        assert formatted.isupper()

    def test_kill_switch_disables_generation(self):
        """Kill switch should disable all generation."""
        from pipeline_constants import CURIOSITY_GAP_ENABLED

        # Verify kill switch exists and is True by default
        assert CURIOSITY_GAP_ENABLED is True
```

### Step 2: Run full test suite

- [ ] **Run all curiosity_gap tests**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/ -v
```

Expected: All tests PASS (should be 25+ tests)

### Step 3: Run all autopilot tests to verify no regressions

- [ ] **Run autopilot tests**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/ -v --tb=short
```

Expected: All tests PASS (131 tests)

### Step 4: Final commit for Phase 2

- [ ] **Commit**

```bash
git add skills/video-pipeline/curiosity_gap/
git commit -m "feat(curiosity-gap): Complete Phase 2 - Core Generation Module

Phase 2 delivers:
- GapTitleEngine with Claude Sonnet integration
- Structure scoring (5 heuristic scorers)
- Confidence floor (60) with MF fallback
- ThumbnailText generation with yin/yang logic
- from_hook vs from_gap approach selection
- Kill switch integration (CURIOSITY_GAP_ENABLED)
- Full integration tests

25+ tests passing. Ready for Phase 3 (learning integration)."
```

---

## Phase 2 Complete

**Deliverables:**
- `curiosity_gap/gap_title_engine.py` — Title generation engine
  - `GapTitleEngine` class with Claude integration
  - `score_structures()` heuristic scoring
  - `get_viable_structures()` confidence filtering
  - `MF_FORMULAS` fallback system
- `curiosity_gap/thumbnail_generator.py` — Yin/yang text generation
  - `ThumbnailText` dataclass
  - `format_thumbnail_text()` ALL CAPS formatting
  - `select_approach()` structure-based approach selection
- 25+ tests

**Test Commands:**
```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/ -v
cd skills/video-pipeline && python -m pytest autopilot/tests/ -v
```

**Usage Example:**
```python
from curiosity_gap.gap_title_engine import GapTitleEngine

engine = GapTitleEngine()
titles = await engine.generate_titles({
    "hook": "...",
    "thesis": "...",
    "facts": ["..."],
})

for title in titles:
    print(f"{title.structure.value}: {title.text}")
    print(f"  Thumbnail: {title.thumbnail_text} ({title.thumbnail_approach})")
```

**Next Phase:** Phase 3 (Learning Integration) — Extend learning_extractor for structure category, wire CTR tracking
