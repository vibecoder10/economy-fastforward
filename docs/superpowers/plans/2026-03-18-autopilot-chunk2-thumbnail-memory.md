# Autopilot Brain - Chunk 2: Thumbnail Intel + Memory System

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add thumbnail analysis (Claude vision), title selection, and memory system for pattern persistence.

**Architecture:** New `analysis/` and `learning/` directories under `autopilot/`. Memory files in `autopilot/memory/` store learned patterns that persist across sessions.

**Tech Stack:** Python 3.11+, async, anthropic (vision), pydantic.

**Related Spec:** `docs/superpowers/specs/2026-03-18-autopilot-brain-design.md` (Section 5, 8.4-8.7)

---

## File Structure (Chunk 2)

```
skills/video-pipeline/autopilot/
├── analysis/
│   ├── __init__.py
│   ├── thumbnail_analyzer.py    # Vision analysis of competitor thumbnails
│   ├── thumbnail_adapter.py     # Generate REPLACE:/APPEND: overrides
│   └── title_selector.py        # Score and select best title variant
│
├── learning/
│   ├── __init__.py
│   └── pattern_library.py       # Read/query memory files
│
├── memory/
│   ├── LEARNINGS.md             # Master summary (always loaded)
│   ├── thumbnail_patterns.md    # What thumbnail elements work
│   ├── title_patterns.md        # What title formulas work
│   ├── topic_performance.md     # Which topics work for OUR channel
│   ├── experiments_log.md       # Every video as an experiment
│   └── competitor_models.md     # Which competitors to trust
│
└── tests/
    ├── test_thumbnail_analyzer.py
    ├── test_thumbnail_adapter.py
    ├── test_title_selector.py
    └── test_pattern_library.py
```

---

## Task 1: Create Memory Files + Directory Structure

**Files:**
- Create: `skills/video-pipeline/autopilot/analysis/__init__.py`
- Create: `skills/video-pipeline/autopilot/learning/__init__.py`
- Create: `skills/video-pipeline/autopilot/memory/LEARNINGS.md`
- Create: `skills/video-pipeline/autopilot/memory/thumbnail_patterns.md`
- Create: `skills/video-pipeline/autopilot/memory/title_patterns.md`
- Create: `skills/video-pipeline/autopilot/memory/topic_performance.md`
- Create: `skills/video-pipeline/autopilot/memory/experiments_log.md`
- Create: `skills/video-pipeline/autopilot/memory/competitor_models.md`

### Step 1: Create directories

```bash
mkdir -p skills/video-pipeline/autopilot/analysis
mkdir -p skills/video-pipeline/autopilot/learning
mkdir -p skills/video-pipeline/autopilot/memory
touch skills/video-pipeline/autopilot/analysis/__init__.py
touch skills/video-pipeline/autopilot/learning/__init__.py
```

### Step 2: Create LEARNINGS.md template

```markdown
# Autopilot Learnings

Last updated: 2026-03-18
Videos produced: 0
Avg CTR: 0.0%
Best CTR: 0.0% ("")

---

## Top 5 Proven Patterns

*No patterns yet. Produce videos and measure CTR to learn.*

---

## Current Hypotheses (Testing)

*No active hypotheses.*

---

## Anti-Patterns (Stop Doing)

*No confirmed anti-patterns yet.*

---

## Notes

This file is the master summary loaded into context before each production cycle.
Pattern files contain detailed reasoning; this file contains actionable summaries.
```

### Step 3: Create thumbnail_patterns.md template

```markdown
# Thumbnail Patterns

Last updated: 2026-03-18
Sample size: 0 videos

---

## Proven Elements (KEEP)

*No proven elements yet.*

---

## Promising Elements (TESTING)

*No elements being tested.*

---

## Anti-Patterns (AVOID)

*No confirmed anti-patterns.*

---

## Color Performance

| Color Combo | CTR Avg | Sample | Verdict |
|-------------|---------|--------|---------|
| *No data yet* | | | |

---

## Composition Performance

| Layout | CTR Avg | Sample | Verdict |
|--------|---------|--------|---------|
| *No data yet* | | | |

---

## Notes

Elements are promoted from TESTING → PROVEN after 3+ videos with CTR ≥ 4.0%.
Elements are demoted to ANTI-PATTERNS after 2+ videos with CTR ≤ 2.5%.
```

### Step 4: Create title_patterns.md template

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

## Structure Performance

| Pattern | Example | CTR Avg | Sample | Verdict |
|---------|---------|---------|--------|---------|
| *No data yet* | | | | |

---

## Notes

Pattern types: question, statement, number, contrast, urgency, curiosity_gap
Formulas are promoted after 3+ videos with CTR ≥ 4.0%.
```

### Step 5: Create remaining memory files

**topic_performance.md:**
```markdown
# Topic Performance

Last updated: 2026-03-18
Sample size: 0 videos

---

## Strong Topics (CTR ≥ 4.0%)

*No strong topics identified yet.*

---

## Weak Topics (CTR ≤ 2.5%)

*No weak topics identified yet.*

---

## Topic × Timing Matrix

| Topic | Recent Event | CTR | Notes |
|-------|--------------|-----|-------|
| *No data yet* | | | |
```

**experiments_log.md:**
```markdown
# Experiment Log

---

*No experiments logged yet. Each video production will be logged here with:*
- *Video title and date*
- *Competitor modeled*
- *Predicted vs actual CTR*
- *Thumbnail/title patterns used*
- *Verdict (KEEP/DISCARD)*
- *Learnings extracted*
```

**competitor_models.md:**
```markdown
# Competitor Models

Last updated: 2026-03-18

---

## Trusted Competitors (High Correlation)

*No competitors assessed yet.*

---

## Unreliable Competitors (Low Correlation)

*No competitors assessed yet.*

---

## Competitor Performance Log

| Competitor | Videos Modeled | Avg Our CTR | Avg Their VPH | Trust Score |
|------------|----------------|-------------|---------------|-------------|
| *No data yet* | | | | |

---

## Notes

Trust score = correlation between their VPH and our CTR when modeling them.
High trust (≥0.7): Their winners tend to be our winners.
Low trust (≤0.3): Their performance doesn't predict ours.
```

### Step 6: Commit

```bash
git add skills/video-pipeline/autopilot/analysis/ skills/video-pipeline/autopilot/learning/ skills/video-pipeline/autopilot/memory/
git commit -m "feat(autopilot): Add memory system directory structure

- analysis/ and learning/ directories
- Memory files: LEARNINGS.md, thumbnail_patterns.md, title_patterns.md
- topic_performance.md, experiments_log.md, competitor_models.md
- Template structures ready for pattern accumulation"
```

---

## Task 2: Pattern Library

**Files:**
- Create: `skills/video-pipeline/autopilot/learning/pattern_library.py`
- Create: `skills/video-pipeline/autopilot/tests/test_pattern_library.py`

### Implementation

The pattern library reads memory files and provides queryable interfaces:

```python
"""Read and query patterns from memory files."""

from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
import re


@dataclass
class ThumbnailPattern:
    """A thumbnail pattern with performance data."""
    element: str
    category: str  # "color", "composition", "subject", "text"
    status: str  # "proven", "testing", "anti"
    avg_ctr: Optional[float] = None
    sample_size: int = 0


@dataclass
class TitlePattern:
    """A title formula pattern."""
    formula: str
    example: str
    status: str  # "proven", "testing", "anti"
    avg_ctr: Optional[float] = None
    sample_size: int = 0


class PatternLibrary:
    """Read and query memory files."""

    def __init__(self, memory_dir: Optional[Path] = None):
        if memory_dir is None:
            memory_dir = Path(__file__).parent.parent / "memory"
        self.memory_dir = memory_dir

    def get_learnings_summary(self) -> str:
        """Get the LEARNINGS.md content for context injection."""
        path = self.memory_dir / "LEARNINGS.md"
        if path.exists():
            return path.read_text()
        return ""

    def get_thumbnail_patterns(self, status: Optional[str] = None) -> List[ThumbnailPattern]:
        """Get thumbnail patterns, optionally filtered by status."""
        # Parse thumbnail_patterns.md
        # Return structured patterns
        pass

    def get_title_patterns(self, status: Optional[str] = None) -> List[TitlePattern]:
        """Get title patterns, optionally filtered by status."""
        # Parse title_patterns.md
        pass

    def get_anti_patterns(self, category: str) -> List[str]:
        """Get anti-patterns for a category (thumbnail or title)."""
        pass

    def is_proven_element(self, element: str, category: str) -> bool:
        """Check if an element is in the proven list."""
        pass
```

### Tests

- `test_get_learnings_summary` - Returns content of LEARNINGS.md
- `test_get_thumbnail_patterns_all` - Returns all patterns
- `test_get_thumbnail_patterns_filtered` - Filters by status
- `test_empty_memory_returns_empty` - Handles missing files gracefully

---

## Task 3: Thumbnail Analyzer

**Files:**
- Create: `skills/video-pipeline/autopilot/analysis/thumbnail_analyzer.py`
- Create: `skills/video-pipeline/autopilot/tests/test_thumbnail_analyzer.py`

### Implementation

Uses Claude vision to extract elements from competitor thumbnails:

```python
"""Analyze competitor thumbnails using Claude vision."""

import httpx
import base64
from dataclasses import dataclass
from typing import Optional
from pydantic import BaseModel


class ThumbnailAnalysis(BaseModel):
    """Extracted thumbnail elements."""
    colors: dict  # background, text, accents
    composition: str  # face_left_text_right, centered, etc.
    text: dict  # lines, size_pct, style
    subject: dict  # face, expression, type
    style: str  # editorial illustration, photorealistic, etc.
    confidence: float  # 0-1


class ThumbnailAnalyzer:
    """Analyze thumbnails using Claude vision."""

    VISION_PROMPT = '''Analyze this YouTube thumbnail and extract:

1. Colors: What are the dominant colors? Background, text, accents.
2. Composition: Where is the subject? Where is the text? (e.g., "face_left_text_right")
3. Text: How many lines? What percentage of frame width? Style (caps, outline, etc.)
4. Subject: Is there a face? Expression? What type of subject?
5. Style: Is it photorealistic, illustrated, editorial, etc.?

Return JSON:
{
  "colors": {"background": "...", "text": "...", "accents": "..."},
  "composition": "...",
  "text": {"lines": N, "size_pct": N, "style": "..."},
  "subject": {"face": true/false, "expression": "...", "type": "..."},
  "style": "...",
  "confidence": 0.0-1.0
}'''

    def __init__(self, anthropic_client):
        self.client = anthropic_client

    async def analyze(self, image_url: str) -> Optional[ThumbnailAnalysis]:
        """Analyze a thumbnail image.

        Args:
            image_url: URL to the thumbnail image

        Returns:
            ThumbnailAnalysis or None if analysis fails
        """
        # Download image
        # Send to Claude vision
        # Parse response
        # Return structured analysis
        pass

    async def analyze_from_video_id(self, video_id: str) -> Optional[ThumbnailAnalysis]:
        """Analyze thumbnail for a YouTube video ID."""
        # Get thumbnail URL (maxres or high)
        # Call analyze()
        pass
```

### Error Handling (per spec section 8.7)

- Image 404 → return None, log warning
- Rate limit → retry with exponential backoff (3 attempts)
- Vision returns empty → return None, use defaults
- Low confidence (<0.6) → log, proceed with partial extraction

---

## Task 4: Thumbnail Adapter

**Files:**
- Create: `skills/video-pipeline/autopilot/analysis/thumbnail_adapter.py`
- Create: `skills/video-pipeline/autopilot/tests/test_thumbnail_adapter.py`

### Implementation

Generates `Thumbnail Style Override` field content:

```python
"""Generate thumbnail style overrides from analysis."""

from typing import Optional
from autopilot.analysis.thumbnail_analyzer import ThumbnailAnalysis
from autopilot.learning.pattern_library import PatternLibrary


class ThumbnailAdapter:
    """Generate style overrides from analysis + memory."""

    def __init__(self, pattern_library: PatternLibrary):
        self.patterns = pattern_library

    def generate_override(
        self,
        analysis: ThumbnailAnalysis,
        use_replace: bool = True,
    ) -> str:
        """Generate Thumbnail Style Override field content.

        Args:
            analysis: Extracted thumbnail elements
            use_replace: Use REPLACE: prefix (full override) vs APPEND:

        Returns:
            Override string for Airtable field
        """
        # Cross-reference with memory patterns
        # Keep proven elements
        # Adjust based on our optimal values
        # Add brand elements
        # Avoid anti-patterns

        prefix = "REPLACE:" if use_replace else "APPEND:"

        # Build override description
        # ...

        return f"{prefix} {override_text}"

    def _should_keep(self, element: str, category: str) -> bool:
        """Check if element should be kept (proven or neutral)."""
        pass

    def _should_avoid(self, element: str, category: str) -> bool:
        """Check if element is an anti-pattern."""
        pass

    def _apply_adjustments(self, analysis: ThumbnailAnalysis) -> dict:
        """Apply channel-optimal adjustments."""
        # e.g., text 65% → 70% (our optimal)
        pass
```

### Override Format (per spec section 8.4)

```
REPLACE: Red gradient background transitioning from deep crimson top to
darker red bottom. Leader portrait (stern expression) positioned on LEFT
side of frame, taking up 40% of width. Two lines of bold yellow text on
RIGHT side, approximately 70% of frame width, thick black outline with
heavy drop shadow. Text in all caps. High saturation editorial illustration
style. No blue tones. Dominant colors: red, yellow, black only.
```

---

## Task 5: Title Selector

**Files:**
- Create: `skills/video-pipeline/autopilot/analysis/title_selector.py`
- Create: `skills/video-pipeline/autopilot/tests/test_title_selector.py`

### Implementation

Scores title variants against patterns:

```python
"""Select best title from variants using pattern memory."""

from dataclasses import dataclass
from typing import List, Optional
from autopilot.learning.pattern_library import PatternLibrary


@dataclass
class ScoredTitle:
    """A title with its pattern score."""
    title: str
    score: float
    matched_patterns: List[str]
    avoided_antipatterns: List[str]
    reasoning: str


class TitleSelector:
    """Score and select best title variant."""

    # Pattern detection
    QUESTION_PATTERN = r'\?$'
    NUMBER_PATTERN = r'\d+'
    CAPS_PATTERN = r'[A-Z]{2,}'

    def __init__(self, pattern_library: PatternLibrary):
        self.patterns = pattern_library

    def score_title(self, title: str, competitor_title: Optional[str] = None) -> ScoredTitle:
        """Score a single title against patterns.

        Scoring factors (per spec 8.6):
        - Match to proven formulas: +2 points
        - Avoid anti-patterns: no penalty if avoided
        - Similar to competitor structure: +1 point
        - Anti-pattern present: -3 points
        """
        pass

    def select_best(
        self,
        variants: List[str],
        competitor_title: Optional[str] = None,
        min_score: float = 0.0,
    ) -> Optional[ScoredTitle]:
        """Select the highest-scoring title variant.

        Args:
            variants: List of title options (usually 3)
            competitor_title: Original competitor title for structure matching
            min_score: Minimum acceptable score

        Returns:
            Best title or None if all below threshold
        """
        pass

    def detect_patterns(self, title: str) -> List[str]:
        """Detect which patterns a title matches."""
        # question, number, caps_emphasis, urgency, etc.
        pass
```

---

## Task 6: Integration + Tests

Wire up the new modules in autopilot.py and add comprehensive tests.

### Update autopilot.py

Add thumbnail analysis step in the cycle:

```python
# After selecting best candidate...

# 6. Analyze competitor thumbnail (non-blocking)
thumbnail_override = None
if best.candidate.source_type == "competitor":
    try:
        analysis = await self.thumbnail_analyzer.analyze_from_video_id(
            best.candidate.video_id
        )
        if analysis:
            thumbnail_override = self.thumbnail_adapter.generate_override(analysis)
    except Exception as e:
        print(f"   Thumbnail analysis failed (non-blocking): {e}")

# 7. Write overrides to Airtable
# ...
```

### Run all tests

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/ -v
```

Expected: 35+ tests passing

---

## Chunk 2 Complete

**Deliverables:**
- `autopilot/memory/` — 6 pattern files
- `autopilot/learning/pattern_library.py` — Read/query patterns
- `autopilot/analysis/thumbnail_analyzer.py` — Claude vision extraction
- `autopilot/analysis/thumbnail_adapter.py` — Generate overrides
- `autopilot/analysis/title_selector.py` — Score and select titles
- 8+ new tests

**Test Command:**
```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/ -v
```

**Next:** Chunk 3 (CTR Monitoring + Learning Loop)
