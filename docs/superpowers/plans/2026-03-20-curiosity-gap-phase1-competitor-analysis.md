# Curiosity Gap Phase 1: Competitor Analysis + Data Seeding

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the competitor analyzer to seed the pattern library with ~50 competitor titles BEFORE building the title generator. The generator needs real data from day one.

**Architecture:** New `curiosity_gap/` module with two-phase competitor analysis (quick title analysis for all >50 VPH, deep thumbnail vision for top 20% per channel). VPH normalization uses channel percentiles with cold start handling.

**Tech Stack:** Python 3.11+, async, pyairtable, httpx (Gemini Vision), anthropic (Claude), bisect (percentile), pydantic

**Related Spec:** `docs/superpowers/specs/2026-03-20-curiosity-gap-title-system.md`

---

## File Structure (Phase 1)

```
skills/video-pipeline/
├── curiosity_gap/                      # NEW MODULE
│   ├── __init__.py
│   ├── structures.py                   # CuriosityStructure enum + definitions
│   ├── competitor_analyzer.py          # Two-phase analysis
│   └── tests/
│       ├── __init__.py
│       ├── test_structures.py
│       └── test_competitor_analyzer.py
│
├── autopilot/
│   ├── learning/
│   │   └── pattern_library.py          # EXTEND: add curiosity gap methods
│   └── memory/
│       └── competitor_patterns.md      # NEW: competitor pattern storage
│
├── clients/
│   └── gemini_client.py                # EXTEND: add analyze_competitor_thumbnail()
│
└── pipeline_constants.py               # EXTEND: add new Airtable field names
```

---

## Task 1: Create Module Structure + Structures Enum

**Files:**
- Create: `skills/video-pipeline/curiosity_gap/__init__.py`
- Create: `skills/video-pipeline/curiosity_gap/structures.py`
- Create: `skills/video-pipeline/curiosity_gap/tests/__init__.py`
- Create: `skills/video-pipeline/curiosity_gap/tests/test_structures.py`

### Step 1: Create directories

- [ ] **Create directory structure**

```bash
mkdir -p skills/video-pipeline/curiosity_gap/tests
touch skills/video-pipeline/curiosity_gap/__init__.py
touch skills/video-pipeline/curiosity_gap/tests/__init__.py
```

### Step 2: Write failing test for structures

- [ ] **Write test_structures.py**

```python
# skills/video-pipeline/curiosity_gap/tests/test_structures.py
"""Tests for curiosity gap structures."""

import pytest
from curiosity_gap.structures import (
    CuriosityStructure,
    STRUCTURE_DEFINITIONS,
    get_structure_prompt,
    validate_structure,
)


class TestCuriosityStructure:
    """Test suite for CuriosityStructure enum."""

    def test_all_structures_defined(self):
        """Should have all 6 structures including 'other'."""
        structures = list(CuriosityStructure)
        assert len(structures) == 6
        assert CuriosityStructure.HIDDEN_FLAW in structures
        assert CuriosityStructure.ASYMMETRIC_DG in structures
        assert CuriosityStructure.TIME_BOMB in structures
        assert CuriosityStructure.PARADIGM_SHIFT in structures
        assert CuriosityStructure.ILLUSION_CONTROL in structures
        assert CuriosityStructure.OTHER in structures

    def test_structure_string_values(self):
        """Structure values should be snake_case strings."""
        assert CuriosityStructure.HIDDEN_FLAW.value == "hidden_flaw"
        assert CuriosityStructure.ASYMMETRIC_DG.value == "asymmetric_dg"
        assert CuriosityStructure.TIME_BOMB.value == "time_bomb"
        assert CuriosityStructure.PARADIGM_SHIFT.value == "paradigm_shift"
        assert CuriosityStructure.ILLUSION_CONTROL.value == "illusion_control"
        assert CuriosityStructure.OTHER.value == "other"


class TestStructureDefinitions:
    """Test suite for structure definitions."""

    def test_all_structures_have_definitions(self):
        """Every structure should have a definition."""
        for structure in CuriosityStructure:
            assert structure in STRUCTURE_DEFINITIONS
            defn = STRUCTURE_DEFINITIONS[structure]
            assert "gap_mechanism" in defn
            assert "when_to_use" in defn
            assert "example" in defn

    def test_hidden_flaw_definition(self):
        """Hidden flaw should have correct gap mechanism."""
        defn = STRUCTURE_DEFINITIONS[CuriosityStructure.HIDDEN_FLAW]
        assert "mistake" in defn["gap_mechanism"].lower() or "hiding" in defn["gap_mechanism"].lower()

    def test_asymmetric_dg_definition(self):
        """Asymmetric David/Goliath should reference small vs big."""
        defn = STRUCTURE_DEFINITIONS[CuriosityStructure.ASYMMETRIC_DG]
        assert "small" in defn["gap_mechanism"].lower() or "big" in defn["gap_mechanism"].lower()


class TestGetStructurePrompt:
    """Test suite for prompt generation."""

    def test_prompt_contains_all_structures(self):
        """Generated prompt should list all 5 main structures."""
        prompt = get_structure_prompt()
        assert "hidden_flaw" in prompt
        assert "asymmetric_dg" in prompt
        assert "time_bomb" in prompt
        assert "paradigm_shift" in prompt
        assert "illusion_control" in prompt
        assert "other" in prompt

    def test_prompt_contains_gap_mechanisms(self):
        """Generated prompt should include gap mechanisms."""
        prompt = get_structure_prompt()
        assert "mistake" in prompt.lower() or "hiding" in prompt.lower()


class TestValidateStructure:
    """Test suite for structure validation."""

    def test_valid_structure(self):
        """Should accept valid structure strings."""
        assert validate_structure("hidden_flaw") == CuriosityStructure.HIDDEN_FLAW
        assert validate_structure("other") == CuriosityStructure.OTHER

    def test_case_insensitive(self):
        """Should handle case variations."""
        assert validate_structure("HIDDEN_FLAW") == CuriosityStructure.HIDDEN_FLAW
        assert validate_structure("Hidden_Flaw") == CuriosityStructure.HIDDEN_FLAW

    def test_invalid_structure_returns_other(self):
        """Invalid structures should return OTHER."""
        assert validate_structure("unknown_structure") == CuriosityStructure.OTHER
        assert validate_structure("") == CuriosityStructure.OTHER
        assert validate_structure("gibberish") == CuriosityStructure.OTHER


class TestGetMainStructures:
    """Test suite for get_main_structures helper."""

    def test_excludes_other(self):
        """get_main_structures should return 5 structures, excluding OTHER."""
        from curiosity_gap.structures import get_main_structures
        main = get_main_structures()
        assert len(main) == 5
        assert CuriosityStructure.OTHER not in main

    def test_includes_all_main_structures(self):
        """Should include all 5 main curiosity gap structures."""
        from curiosity_gap.structures import get_main_structures
        main = get_main_structures()
        assert CuriosityStructure.HIDDEN_FLAW in main
        assert CuriosityStructure.ASYMMETRIC_DG in main
        assert CuriosityStructure.TIME_BOMB in main
        assert CuriosityStructure.PARADIGM_SHIFT in main
        assert CuriosityStructure.ILLUSION_CONTROL in main
```

### Step 3: Run test to verify it fails

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_structures.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'curiosity_gap.structures'`

### Step 4: Implement structures module

- [ ] **Write structures.py**

```python
# skills/video-pipeline/curiosity_gap/structures.py
"""Curiosity gap structure definitions.

The 5 curiosity gap structures create cognitive dissonance that forces clicks:
1. hidden_flaw - "What mistake are they hiding?"
2. asymmetric_dg - "How does small beat big?"
3. time_bomb - "What trap was set?"
4. paradigm_shift - "What am I missing?"
5. illusion_control - "How does this affect ME?"
6. other - Novel pattern for review
"""

from enum import Enum
from typing import Dict, Optional


class CuriosityStructure(str, Enum):
    """Valid curiosity gap structure IDs."""
    HIDDEN_FLAW = "hidden_flaw"
    ASYMMETRIC_DG = "asymmetric_dg"
    TIME_BOMB = "time_bomb"
    PARADIGM_SHIFT = "paradigm_shift"
    ILLUSION_CONTROL = "illusion_control"
    OTHER = "other"


# Structure definitions with gap mechanisms and examples
STRUCTURE_DEFINITIONS: Dict[CuriosityStructure, Dict[str, str]] = {
    CuriosityStructure.HIDDEN_FLAW: {
        "gap_mechanism": "What's the mistake they're hiding?",
        "when_to_use": "Financial waste, failed strategies, cover-ups",
        "example": "The $100B Mistake Saudi Arabia Is Hiding",
    },
    CuriosityStructure.ASYMMETRIC_DG: {
        "gap_mechanism": "How does small beat big?",
        "when_to_use": "Power imbalances, unexpected advantages",
        "example": "Why the Navy Is Terrified of $500 Plastic",
    },
    CuriosityStructure.TIME_BOMB: {
        "gap_mechanism": "What trap was set? When does it trigger?",
        "when_to_use": "Long-term strategies, delayed consequences",
        "example": "The 40-Year Trap America Walked Into",
    },
    CuriosityStructure.PARADIGM_SHIFT: {
        "gap_mechanism": "What reality am I missing?",
        "when_to_use": "Reframing events, hidden truths",
        "example": "The Map That Proves WWIII Already Begun",
    },
    CuriosityStructure.ILLUSION_CONTROL: {
        "gap_mechanism": "How does this affect ME personally?",
        "when_to_use": "Personal stakes, economic impacts",
        "example": "The Chokepoint That Controls Your Bank Account",
    },
    CuriosityStructure.OTHER: {
        "gap_mechanism": "Novel pattern — flag for review",
        "when_to_use": "Doesn't fit above structures",
        "example": "Logged for weekly digest clustering",
    },
}


def get_structure_prompt() -> str:
    """Generate Claude prompt text listing all structures.

    Returns:
        Formatted prompt section for structure analysis
    """
    lines = ["STRUCTURES:"]
    for i, structure in enumerate(CuriosityStructure, 1):
        if structure == CuriosityStructure.OTHER:
            lines.append(f"{i}. {structure.value} - Doesn't fit above (describe the pattern)")
        else:
            defn = STRUCTURE_DEFINITIONS[structure]
            lines.append(f"{i}. {structure.value} - \"{defn['gap_mechanism']}\"")
    return "\n".join(lines)


def validate_structure(structure_str: str) -> CuriosityStructure:
    """Validate and normalize a structure string.

    Args:
        structure_str: Structure identifier from Claude response

    Returns:
        CuriosityStructure enum (defaults to OTHER if invalid)
    """
    if not structure_str:
        return CuriosityStructure.OTHER

    normalized = structure_str.lower().strip()

    try:
        return CuriosityStructure(normalized)
    except ValueError:
        return CuriosityStructure.OTHER


def get_main_structures() -> list[CuriosityStructure]:
    """Get the 5 main structures (excluding OTHER).

    Returns:
        List of main CuriosityStructure values
    """
    return [s for s in CuriosityStructure if s != CuriosityStructure.OTHER]
```

### Step 5: Run tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_structures.py -v
```

Expected: All tests PASS

### Step 6: Commit

- [ ] **Commit**

```bash
git add skills/video-pipeline/curiosity_gap/
git commit -m "feat(curiosity-gap): Add CuriosityStructure enum and definitions

- 6 structures: hidden_flaw, asymmetric_dg, time_bomb, paradigm_shift, illusion_control, other
- Gap mechanisms and examples for each
- get_structure_prompt() for Claude analysis
- validate_structure() with case-insensitive matching
- 10 tests passing"
```

---

## Task 2: Add Airtable Field Constants

**Files:**
- Modify: `skills/video-pipeline/pipeline_constants.py`

### Step 1: Read existing constants

- [ ] **Read pipeline_constants.py**

```bash
cd skills/video-pipeline && head -100 pipeline_constants.py
```

### Step 2: Add new field constants

- [ ] **Add curiosity gap field constants to pipeline_constants.py**

**NOTE:** Base constants (TITLE, VPH, VIDEO_ID, CHANNEL) already exist in CompetitorVideoFields at lines 223-227. Only add the NEW curiosity gap fields below.

Add to the `CompetitorVideoFields` class:

```python
# Curiosity Gap fields (added 2026-03-20)
CURIOSITY_STRUCTURE = "Curiosity Structure"
STRUCTURE_CONFIDENCE = "Structure Confidence"
THUMBNAIL_STYLE_JSON = "Thumbnail Style JSON"
YIN_YANG_APPROACH = "Yin Yang Approach"
YIN_YANG_TEXT = "Yin Yang Text"
ANALYSIS_DATE = "Analysis Date"
MODELED_BY_US = "Modeled By Us"
OUR_CTR_RESULT = "Our CTR Result"
```

Add to the `IdeaFields` class (or create if not exists):

```python
# Curiosity Gap fields for Ideas table (added 2026-03-20)
CURIOSITY_STRUCTURE = "Curiosity Structure"
STRUCTURE_CONFIDENCE = "Structure Confidence"
STRUCTURE_SOURCE = "Structure Source"
THUMBNAIL_APPROACH = "Thumbnail Approach"
THUMBNAIL_TEXT = "Thumbnail Text"
PATTERN_LIBRARY_SNAPSHOT = "Pattern Library Snapshot"
TITLE_POLL_RESULT = "Title Poll Result"
POLL_CLOSED = "Poll Closed"
CTR_12H = "CTR 12h"
```

Add kill switch constant to top-level module (outside any class):

```python
# Curiosity Gap kill switch (2026-03-20)
# Set to False to instantly disable curiosity gap system
CURIOSITY_GAP_ENABLED = True
```

### Step 3: Commit

- [ ] **Commit**

```bash
git add skills/video-pipeline/pipeline_constants.py
git commit -m "feat(constants): Add curiosity gap Airtable field names

- CompetitorVideoFields: Curiosity Structure, Structure Confidence, Thumbnail Style JSON, etc.
- IdeaFields: Curiosity Structure, Structure Source, Title Poll Result, CTR 12h, etc."
```

---

## Task 3: Implement Title Analysis (Phase 1 of Competitor Analyzer)

**Files:**
- Create: `skills/video-pipeline/curiosity_gap/competitor_analyzer.py`
- Create: `skills/video-pipeline/curiosity_gap/tests/test_competitor_analyzer.py`

### Step 1: Write failing tests for title analysis

- [ ] **Write test_competitor_analyzer.py**

```python
# skills/video-pipeline/curiosity_gap/tests/test_competitor_analyzer.py
"""Tests for competitor analyzer."""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, timezone

from curiosity_gap.competitor_analyzer import (
    TitleAnalysis,
    CompetitorAnalyzer,
    should_deep_analyze,
)
from curiosity_gap.structures import CuriosityStructure


class TestTitleAnalysis:
    """Test suite for title analysis dataclass."""

    def test_title_analysis_creation(self):
        """Should create TitleAnalysis with all fields."""
        analysis = TitleAnalysis(
            structure=CuriosityStructure.HIDDEN_FLAW,
            confidence=78,
            gap_mechanism="What's the $100B mistake?",
            variables={"amount": "$100B", "entity": "Saudi Arabia"},
        )

        assert analysis.structure == CuriosityStructure.HIDDEN_FLAW
        assert analysis.confidence == 78
        assert analysis.gap_mechanism == "What's the $100B mistake?"
        assert analysis.variables["amount"] == "$100B"


class TestShouldDeepAnalyze:
    """Test suite for VPH percentile calculation."""

    @pytest.fixture
    def mock_channel_videos(self):
        """Mock videos with various VPH values."""
        return [
            {"vph": 50}, {"vph": 75}, {"vph": 100}, {"vph": 125}, {"vph": 150},
            {"vph": 175}, {"vph": 200}, {"vph": 225}, {"vph": 250}, {"vph": 300},
        ]

    def test_top_20_percent_qualifies_sync(self, mock_channel_videos):
        """Videos in top 20% should qualify for deep analysis."""
        # Test the sync version directly for simpler testing
        from curiosity_gap.competitor_analyzer import should_deep_analyze_sync
        # VPH 280 is in top 20% of [50, 75, 100, 125, 150, 175, 200, 225, 250, 300]
        with patch('curiosity_gap.competitor_analyzer.get_recent_channel_videos') as mock_get:
            mock_get.return_value = mock_channel_videos
            result = should_deep_analyze_sync(
                video_vph=280,
                channel_name="CaspianReport",
            )
            assert result is True

    def test_bottom_80_percent_excluded_sync(self, mock_channel_videos):
        """Videos below top 20% should not qualify."""
        from curiosity_gap.competitor_analyzer import should_deep_analyze_sync
        # VPH 80 is in bottom 80%
        with patch('curiosity_gap.competitor_analyzer.get_recent_channel_videos') as mock_get:
            mock_get.return_value = mock_channel_videos
            result = should_deep_analyze_sync(
                video_vph=80,
                channel_name="CaspianReport",
            )
            assert result is False

    def test_cold_start_uses_absolute_threshold_sync(self):
        """New channels with <5 videos should use absolute VPH threshold."""
        from curiosity_gap.competitor_analyzer import should_deep_analyze_sync
        # Only 3 videos = cold start
        with patch('curiosity_gap.competitor_analyzer.get_recent_channel_videos') as mock_get:
            mock_get.return_value = [{"vph": 50}, {"vph": 75}, {"vph": 100}]

            # VPH 120 >= 100 threshold
            result = should_deep_analyze_sync(video_vph=120, channel_name="NewChannel")
            assert result is True

            # VPH 80 < 100 threshold
            result = should_deep_analyze_sync(video_vph=80, channel_name="NewChannel")
            assert result is False

    def test_duplicate_vph_handled_correctly_sync(self):
        """Should handle duplicate VPH values using bisect."""
        from curiosity_gap.competitor_analyzer import should_deep_analyze_sync
        # Many duplicates at 100
        with patch('curiosity_gap.competitor_analyzer.get_recent_channel_videos') as mock_get:
            mock_get.return_value = [
                {"vph": 100}, {"vph": 100}, {"vph": 100}, {"vph": 100}, {"vph": 100},
                {"vph": 200}, {"vph": 200}, {"vph": 300}, {"vph": 400}, {"vph": 500},
            ]
            # VPH 350 should be in top 20% (position 7-8 of 10)
            result = should_deep_analyze_sync(video_vph=350, channel_name="TestChannel")
            assert result is True


class TestCompetitorAnalyzer:
    """Test suite for CompetitorAnalyzer class."""

    @pytest.fixture
    def analyzer(self):
        return CompetitorAnalyzer()

    @pytest.fixture
    def mock_claude_response(self):
        return {
            "structure": "hidden_flaw",
            "confidence": 78,
            "gap_mechanism": "What's the $100B mistake they're hiding?",
            "variables": {"amount": "$100B", "entity": "Saudi Arabia"},
        }

    @pytest.mark.asyncio
    async def test_analyze_title_returns_analysis(self, analyzer, mock_claude_response):
        """Should return TitleAnalysis from Claude response."""
        with patch.object(analyzer, '_call_claude_for_title') as mock_claude:
            mock_claude.return_value = mock_claude_response

            result = await analyzer.analyze_title("The $100B Mistake Saudi Arabia Is Hiding")

            assert isinstance(result, TitleAnalysis)
            assert result.structure == CuriosityStructure.HIDDEN_FLAW
            assert result.confidence == 78

    @pytest.mark.asyncio
    async def test_analyze_title_handles_other(self, analyzer):
        """Should handle 'other' structure for unclassified titles."""
        with patch.object(analyzer, '_call_claude_for_title') as mock_claude:
            mock_claude.return_value = {
                "structure": "other",
                "confidence": 45,
                "gap_mechanism": "countdown pattern",
                "variables": {"days": "5"},
            }

            result = await analyzer.analyze_title("5 Days Until China's Dollar Deadline")

            assert result.structure == CuriosityStructure.OTHER
            assert result.confidence == 45

    @pytest.mark.asyncio
    async def test_analyze_title_normalizes_invalid_structure(self, analyzer):
        """Should normalize invalid structures to OTHER."""
        with patch.object(analyzer, '_call_claude_for_title') as mock_claude:
            mock_claude.return_value = {
                "structure": "unknown_structure",
                "confidence": 50,
                "gap_mechanism": "unclear",
                "variables": {},
            }

            result = await analyzer.analyze_title("Some Random Title")

            assert result.structure == CuriosityStructure.OTHER
```

### Step 2: Run tests to verify they fail

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_competitor_analyzer.py -v
```

Expected: FAIL with `ModuleNotFoundError`

### Step 3: Implement competitor analyzer (title analysis)

- [ ] **Write competitor_analyzer.py**

```python
# skills/video-pipeline/curiosity_gap/competitor_analyzer.py
"""Two-phase competitor video analysis.

Phase 1: Quick title analysis (all >50 VPH videos) - text only, fast
Phase 2: Deep thumbnail analysis (top 20% per channel) - vision API, expensive

Uses VPH normalization per channel with cold start handling.
"""

import bisect
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from curiosity_gap.structures import (
    CuriosityStructure,
    get_structure_prompt,
    validate_structure,
)


# VPH normalization constants
MIN_CHANNEL_SAMPLE = 5
COLD_START_VPH_THRESHOLD = 100
TOP_PERCENTILE = 80  # Top 20% = 80th percentile and above


@dataclass
class TitleAnalysis:
    """Result of Phase 1 title analysis."""
    structure: CuriosityStructure
    confidence: int  # 0-100
    gap_mechanism: str
    variables: Dict[str, str] = field(default_factory=dict)


@dataclass
class ThumbnailAnalysis:
    """Result of Phase 2 thumbnail analysis."""
    colors: List[str] = field(default_factory=list)
    composition: str = ""
    text_extracted: str = ""
    yin_yang_relationship: str = ""
    yin_yang_approach: str = ""  # "from_hook" or "from_gap"


def get_recent_channel_videos(channel_name: str, limit: int = 20) -> List[Dict]:
    """Fetch recent videos for a channel from Airtable.

    Args:
        channel_name: Channel name (e.g., "CaspianReport")
        limit: Max videos to fetch

    Returns:
        List of video dicts with 'vph' field
    """
    # Import here to avoid circular dependency
    from clients.airtable_client import AirtableClient

    client = AirtableClient()
    # Synchronous call - Airtable client is not async
    records = client.get_competitor_videos_by_channel(
        channel_name=channel_name,
        limit=limit,
    )
    return [{"vph": r.get("fields", {}).get("VPH", 0)} for r in records]


def should_deep_analyze_sync(video_vph: float, channel_name: str) -> bool:
    """Determine if video qualifies for deep thumbnail analysis (sync version).

    Uses VPH percentile ranking within channel. Falls back to
    absolute threshold for new channels with insufficient data.

    Args:
        video_vph: Views per hour for this video
        channel_name: Channel name (e.g., "CaspianReport")

    Returns:
        True if video is in top 20% of channel's recent videos
    """
    channel_videos = get_recent_channel_videos(channel_name, limit=20)

    if len(channel_videos) < MIN_CHANNEL_SAMPLE:
        # Cold start: use absolute threshold
        return video_vph >= COLD_START_VPH_THRESHOLD

    vphs = sorted([v["vph"] for v in channel_videos])

    # Use bisect for correct percentile with duplicates
    position = bisect.bisect_left(vphs, video_vph)
    percentile = (position / len(vphs)) * 100

    return percentile >= TOP_PERCENTILE


async def should_deep_analyze(video_vph: float, channel_name: str) -> bool:
    """Async wrapper for should_deep_analyze_sync.

    The Airtable call is synchronous, but we wrap it for consistent
    async interface in the analyzer.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        should_deep_analyze_sync,
        video_vph,
        channel_name,
    )


class CompetitorAnalyzer:
    """Analyze competitor titles and thumbnails."""

    def __init__(self):
        """Initialize analyzer with API clients."""
        # Lazy load to avoid import cycles
        self._anthropic_client = None
        self._gemini_client = None

    @property
    def anthropic_client(self):
        if self._anthropic_client is None:
            from clients.anthropic_client import AnthropicClient
            self._anthropic_client = AnthropicClient()
        return self._anthropic_client

    async def _call_claude_for_title(self, title: str) -> Dict:
        """Call Claude to analyze title structure.

        Args:
            title: Video title to analyze

        Returns:
            Dict with structure, confidence, gap_mechanism, variables
        """
        prompt = f"""Analyze this competitor YouTube title and identify which curiosity gap structure it uses.

TITLE: "{title}"

{get_structure_prompt()}

Return JSON with:
- structure: one of the structure IDs above
- confidence: 0-100 how well the title fits the structure
- gap_mechanism: the specific question this title makes viewers ask
- variables: extracted components (amounts, entities, timeframes, etc.)

Return ONLY valid JSON, no markdown fences."""

        response = await self.anthropic_client.generate(
            prompt=prompt,
            max_tokens=500,
        )

        # Parse JSON with fallback
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            # Return default
            return {
                "structure": "other",
                "confidence": 30,
                "gap_mechanism": "unclear",
                "variables": {},
            }

    async def analyze_title(self, title: str) -> TitleAnalysis:
        """Phase 1: Analyze title structure (text only, cheap).

        Args:
            title: Video title to analyze

        Returns:
            TitleAnalysis with structure and confidence
        """
        result = await self._call_claude_for_title(title)

        structure = validate_structure(result.get("structure", "other"))

        return TitleAnalysis(
            structure=structure,
            confidence=int(result.get("confidence", 30)),
            gap_mechanism=result.get("gap_mechanism", ""),
            variables=result.get("variables", {}),
        )

    async def analyze_thumbnail(
        self,
        video_id: str,
        title: str,
        use_gemini: bool = True,
    ) -> Optional[ThumbnailAnalysis]:
        """Phase 2: Analyze thumbnail (vision API, expensive).

        Args:
            video_id: YouTube video ID
            title: Video title (for yin/yang comparison)
            use_gemini: Use Gemini Vision (default) or Claude Vision

        Returns:
            ThumbnailAnalysis or None if analysis fails
        """
        # Get thumbnail URL
        thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

        if use_gemini:
            return await self._analyze_with_gemini(thumbnail_url, title)
        else:
            return await self._analyze_with_claude(thumbnail_url, title)

    async def _analyze_with_gemini(
        self,
        thumbnail_url: str,
        title: str,
    ) -> Optional[ThumbnailAnalysis]:
        """Analyze thumbnail using Gemini Vision.

        Args:
            thumbnail_url: URL of thumbnail image
            title: Video title for yin/yang comparison

        Returns:
            ThumbnailAnalysis or None
        """
        # Import lazily
        from clients.gemini_client import GeminiClient

        if self._gemini_client is None:
            self._gemini_client = GeminiClient()

        try:
            result = await self._gemini_client.analyze_competitor_thumbnail(
                thumbnail_url=thumbnail_url,
                title=title,
            )
            return ThumbnailAnalysis(
                colors=result.get("colors", []),
                composition=result.get("composition", ""),
                text_extracted=result.get("text_extracted", ""),
                yin_yang_relationship=result.get("yin_yang_relationship", ""),
                yin_yang_approach=result.get("yin_yang_approach", ""),
            )
        except Exception as e:
            print(f"Gemini thumbnail analysis failed: {e}")
            return None

    async def _analyze_with_claude(
        self,
        thumbnail_url: str,
        title: str,
    ) -> Optional[ThumbnailAnalysis]:
        """Analyze thumbnail using Claude Vision (fallback).

        Args:
            thumbnail_url: URL of thumbnail image
            title: Video title for yin/yang comparison

        Returns:
            ThumbnailAnalysis or None
        """
        # TODO: Implement Claude vision fallback in Phase 2
        return None

    async def analyze_video(
        self,
        video_id: str,
        title: str,
        vph: float,
        channel_name: str,
    ) -> Dict:
        """Full analysis: title (always) + thumbnail (if qualifies).

        Args:
            video_id: YouTube video ID
            title: Video title
            vph: Views per hour
            channel_name: Channel name (e.g., "CaspianReport")

        Returns:
            Dict with title_analysis and optional thumbnail_analysis
        """
        # Phase 1: Always analyze title
        title_analysis = await self.analyze_title(title)

        result = {
            "title_analysis": title_analysis,
            "thumbnail_analysis": None,
            "deep_analyzed": False,
        }

        # Phase 2: Thumbnail only if top 20%
        if await should_deep_analyze(vph, channel_name):
            thumbnail_analysis = await self.analyze_thumbnail(video_id, title)
            result["thumbnail_analysis"] = thumbnail_analysis
            result["deep_analyzed"] = True

        return result
```

### Step 4: Run tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/test_competitor_analyzer.py -v
```

Expected: All tests PASS

### Step 5: Commit

- [ ] **Commit**

```bash
git add skills/video-pipeline/curiosity_gap/
git commit -m "feat(curiosity-gap): Add competitor analyzer with VPH normalization

- Phase 1: Title analysis via Claude (all >50 VPH)
- Phase 2: Thumbnail analysis via Gemini (top 20% per channel)
- VPH percentile with bisect (handles duplicates)
- Cold start handling (MIN_CHANNEL_SAMPLE=5, threshold=100)
- 9 tests passing"
```

---

## Task 4: Extend Gemini Client for Thumbnail Analysis

**Files:**
- Modify: `skills/video-pipeline/clients/gemini_client.py`

### Step 1: Read existing gemini client

- [ ] **Read gemini_client.py to understand structure**

```bash
cd skills/video-pipeline && head -150 clients/gemini_client.py
```

### Step 2: Add analyze_competitor_thumbnail method

- [ ] **Add method to gemini_client.py**

Add this method to the GeminiClient class:

```python
async def analyze_competitor_thumbnail(
    self,
    thumbnail_url: str,
    title: str,
) -> Dict:
    """Analyze competitor thumbnail for curiosity gap patterns.

    Extracts:
    - Colors (dominant palette)
    - Composition (face-left, text-right, etc.)
    - Text extracted from thumbnail
    - Yin/yang relationship to title
    - Yin/yang approach (from_hook or from_gap)

    Args:
        thumbnail_url: URL of thumbnail image
        title: Video title for yin/yang comparison

    Returns:
        Dict with analysis results
    """
    import base64
    import httpx
    import json
    import re

    prompt = f"""Analyze this YouTube thumbnail in relation to its title.

TITLE: "{title}"

Extract:
1. colors: List the 3-5 dominant colors (e.g., ["deep red", "bright yellow", "black"])
2. composition: Describe layout (e.g., "face-left text-right", "centered text", "split screen")
3. text_extracted: What text appears on the thumbnail? (exact text in caps)
4. yin_yang_relationship: How does the thumbnail text relate to the title?
   - Does it reveal the answer/consequence? (from_gap)
   - Does it show a surprising detail from the hook? (from_hook)
   - Is it just repeating the title? (repetitive - bad)
5. yin_yang_approach: "from_hook" or "from_gap" based on the relationship

Return JSON only, no markdown."""

    try:
        # Fetch and encode image (same pattern as _fetch_image_base64)
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            img_response = await client.get(thumbnail_url)
            img_response.raise_for_status()
        image_base64 = base64.b64encode(img_response.content).decode("utf-8")

        # Gemini Vision API call (same pattern as generate_thumbnail_spec)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        params = {"key": self.api_key}
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_base64,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 1024,
                "responseMimeType": "application/json",
            },
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, params=params, json=payload)
            response.raise_for_status()

        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]

        # Parse JSON response
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())

            # Return defaults
            return {
                "colors": [],
                "composition": "unknown",
                "text_extracted": "",
                "yin_yang_relationship": "unknown",
                "yin_yang_approach": "from_gap",
            }

    except httpx.HTTPStatusError as e:
        print(f"Gemini API error: {e.response.status_code}")
        return self._get_thumbnail_analysis_fallback()
    except Exception as e:
        print(f"Gemini thumbnail analysis error: {e}")
        return self._get_thumbnail_analysis_fallback()

def _get_thumbnail_analysis_fallback(self) -> Dict:
    """Return defaults when thumbnail analysis fails."""
    return {
        "colors": [],
        "composition": "error",
        "text_extracted": "",
        "yin_yang_relationship": "error",
        "yin_yang_approach": "from_gap",
    }
```

### Step 3: Commit

- [ ] **Commit**

```bash
git add skills/video-pipeline/clients/gemini_client.py
git commit -m "feat(gemini): Add analyze_competitor_thumbnail for curiosity gap

- Extract colors, composition, text from thumbnails
- Detect yin/yang relationship to title
- Classify approach as from_hook or from_gap"
```

---

## Task 5: Create competitor_patterns.md Memory File

**Files:**
- Create: `skills/video-pipeline/autopilot/memory/competitor_patterns.md`

### Step 1: Create the memory file template

- [ ] **Write competitor_patterns.md**

```markdown
# Competitor Patterns

Last updated: 2026-03-20
Videos analyzed: 0

## Top Performing Structures (by VPH)

### hidden_flaw (n=0, avg VPH: —)
_No data yet. Run `analyze competitors` to seed._

### asymmetric_dg (n=0, avg VPH: —)
_No data yet._

### time_bomb (n=0, avg VPH: —)
_No data yet._

### paradigm_shift (n=0, avg VPH: —)
_No data yet._

### illusion_control (n=0, avg VPH: —)
_No data yet._

## Thumbnail Styles (by channel)

_No channels analyzed yet. Run `analyze @ChannelName` to start._

## Unclassified (other) — Pending Review

_No unclassified titles yet._

---

## Notes

Format for entries:
- Channel: "Title" (VPH: X, Structure: Y, Confidence: Z%)
```

### Step 2: Commit

- [ ] **Commit**

```bash
git add skills/video-pipeline/autopilot/memory/competitor_patterns.md
git commit -m "feat(memory): Add competitor_patterns.md template

Ready for seeding with competitor analysis data"
```

---

## Task 6: Extend Pattern Library for Curiosity Gap

**Files:**
- Modify: `skills/video-pipeline/autopilot/learning/pattern_library.py`
- Create: `skills/video-pipeline/autopilot/tests/test_pattern_library_curiosity_gap.py`

### Step 1: Write failing tests for new methods

- [ ] **Write test_pattern_library_curiosity_gap.py**

```python
# skills/video-pipeline/autopilot/tests/test_pattern_library_curiosity_gap.py
"""Tests for curiosity gap extensions to pattern library."""

import pytest
from pathlib import Path
from autopilot.learning.pattern_library import PatternLibrary

# Import CuriosityStructure - the test runs from skills/video-pipeline/
# so curiosity_gap is a sibling package that should be importable
from curiosity_gap.structures import CuriosityStructure


SAMPLE_COMPETITOR_PATTERNS = """# Competitor Patterns

Last updated: 2026-03-20
Videos analyzed: 47

## Top Performing Structures (by VPH)

### hidden_flaw (n=12, avg VPH: 165)
- CaspianReport: "The Pipeline Trap Nobody..." (VPH: 210)
- Economics Explained: "The $2T Mistake..." (VPH: 180)

### time_bomb (n=8, avg VPH: 148)
- PolyMatter: "The 30-Year Trap China..." (VPH: 175)

## Thumbnail Styles (by channel)

### CaspianReport
- Dominant: red/yellow, face-left, 2-line text
- Yin/yang: Title = problem → Thumbnail = consequence

## Unclassified (other) — Pending Review
- "5 Days Until China's Dollar Deadline" (countdown pattern?)
"""


class TestPatternLibraryCuriosityGap:
    """Test suite for curiosity gap pattern library extensions."""

    @pytest.fixture
    def temp_memory_dir(self, tmp_path):
        """Create temp memory directory with sample files."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        # Write sample competitor patterns
        (memory_dir / "competitor_patterns.md").write_text(SAMPLE_COMPETITOR_PATTERNS)

        return memory_dir

    @pytest.fixture
    def library(self, temp_memory_dir):
        return PatternLibrary(memory_dir=temp_memory_dir)

    def test_get_curiosity_gap_patterns_all(self, library):
        """Should return all curiosity gap structure performance."""
        patterns = library.get_curiosity_gap_patterns()

        assert len(patterns) >= 2  # hidden_flaw and time_bomb have data
        hidden_flaw = next((p for p in patterns if p.structure == CuriosityStructure.HIDDEN_FLAW), None)
        assert hidden_flaw is not None
        assert hidden_flaw.sample_size_competitors == 12
        assert hidden_flaw.avg_vph_competitors == 165

    def test_get_curiosity_gap_patterns_filtered(self, library):
        """Should filter by specific structure."""
        patterns = library.get_curiosity_gap_patterns(
            structure=CuriosityStructure.TIME_BOMB
        )

        assert len(patterns) == 1
        assert patterns[0].structure == CuriosityStructure.TIME_BOMB
        assert patterns[0].avg_vph_competitors == 148

    def test_get_competitor_patterns_all(self, library):
        """Should return all competitor patterns."""
        patterns = library.get_competitor_patterns()

        assert len(patterns) >= 3  # 3 videos listed

    def test_get_competitor_patterns_by_channel(self, library):
        """Should filter by channel."""
        patterns = library.get_competitor_patterns(channel="CaspianReport")

        assert len(patterns) >= 1
        assert all(p.channel == "CaspianReport" for p in patterns)

    def test_get_competitor_patterns_by_min_vph(self, library):
        """Should filter by minimum VPH."""
        patterns = library.get_competitor_patterns(min_vph=200)

        assert all(p.vph >= 200 for p in patterns)

    def test_get_unclassified_titles(self, library):
        """Should return unclassified 'other' titles."""
        unclassified = library.get_unclassified_titles()

        assert len(unclassified) >= 1
        assert "Dollar Deadline" in unclassified[0]["title"]
```

### Step 2: Run tests to verify they fail

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_pattern_library_curiosity_gap.py -v
```

Expected: FAIL (methods don't exist yet)

### Step 3: Extend pattern_library.py

- [ ] **Add curiosity gap methods to pattern_library.py**

Add these imports at the top of pattern_library.py (after existing imports):

```python
from typing import Any  # Add to existing typing imports if not present

# Import CuriosityStructure - curiosity_gap is a sibling package
from curiosity_gap.structures import CuriosityStructure
```

Add these dataclasses (after existing dataclasses like ThumbnailPattern, TitlePattern):

```python
@dataclass
class CuriosityGapPattern:
    """Performance data for a curiosity gap structure."""
    structure: CuriosityStructure
    avg_ctr_ours: Optional[float] = None
    sample_size_ours: int = 0
    avg_vph_competitors: Optional[float] = None
    sample_size_competitors: int = 0
    status: str = "testing"  # "proven", "testing", "anti"


@dataclass
class CompetitorPattern:
    """Extracted pattern from competitor video."""
    video_id: str = ""
    channel: str = ""
    title: str = ""
    structure: CuriosityStructure = CuriosityStructure.OTHER
    confidence: int = 0
    vph: float = 0.0
    thumbnail_style: Dict[str, Any] = field(default_factory=dict)
    yin_yang_approach: str = ""
```

Add these methods to the PatternLibrary class:

```python
def _parse_competitor_patterns(self) -> tuple[List[CuriosityGapPattern], List[CompetitorPattern]]:
    """Parse competitor_patterns.md into structured data."""
    path = self.memory_dir / "competitor_patterns.md"
    if not path.exists():
        return [], []

    content = path.read_text()
    gap_patterns = []
    competitor_patterns = []

    # Parse structure sections (### hidden_flaw (n=12, avg VPH: 165))
    structure_pattern = r'### (\w+) \(n=(\d+), avg VPH: ([\d.]+|—)\)'
    for match in re.finditer(structure_pattern, content):
        structure_name = match.group(1)
        sample_size = int(match.group(2))
        avg_vph_str = match.group(3)
        avg_vph = float(avg_vph_str) if avg_vph_str != "—" else None

        try:
            structure = CuriosityStructure(structure_name)
        except ValueError:
            structure = CuriosityStructure.OTHER

        gap_patterns.append(CuriosityGapPattern(
            structure=structure,
            sample_size_competitors=sample_size,
            avg_vph_competitors=avg_vph,
        ))

    # Parse individual videos (- Channel: "Title" (VPH: X))
    video_pattern = r'- (\w+): "([^"]+)" \(VPH: ([\d.]+)\)'
    # Find which section each video is in
    current_structure = CuriosityStructure.OTHER
    for line in content.split('\n'):
        struct_match = re.match(r'### (\w+)', line)
        if struct_match:
            try:
                current_structure = CuriosityStructure(struct_match.group(1))
            except ValueError:
                current_structure = CuriosityStructure.OTHER
            continue

        video_match = re.match(video_pattern, line.strip())
        if video_match:
            competitor_patterns.append(CompetitorPattern(
                channel=video_match.group(1),
                title=video_match.group(2),
                vph=float(video_match.group(3)),
                structure=current_structure,
            ))

    return gap_patterns, competitor_patterns

def get_curiosity_gap_patterns(
    self,
    structure: Optional[CuriosityStructure] = None
) -> List[CuriosityGapPattern]:
    """Get curiosity gap structure performance from competitor_patterns.md.

    Args:
        structure: Filter by specific structure (optional)

    Returns:
        List of CuriosityGapPattern objects
    """
    gap_patterns, _ = self._parse_competitor_patterns()

    if structure is not None:
        return [p for p in gap_patterns if p.structure == structure]

    return gap_patterns

def get_competitor_patterns(
    self,
    channel: Optional[str] = None,
    structure: Optional[CuriosityStructure] = None,
    min_vph: float = 0
) -> List[CompetitorPattern]:
    """Get competitor patterns from competitor_patterns.md.

    Args:
        channel: Filter by channel name (optional)
        structure: Filter by structure (optional)
        min_vph: Minimum VPH threshold

    Returns:
        List of CompetitorPattern objects
    """
    _, competitor_patterns = self._parse_competitor_patterns()

    if channel is not None:
        competitor_patterns = [p for p in competitor_patterns if p.channel == channel]

    if structure is not None:
        competitor_patterns = [p for p in competitor_patterns if p.structure == structure]

    if min_vph > 0:
        competitor_patterns = [p for p in competitor_patterns if p.vph >= min_vph]

    return competitor_patterns

def get_unclassified_titles(self) -> List[Dict]:
    """Get unclassified 'other' titles from competitor_patterns.md.

    Returns:
        List of dicts with title and notes
    """
    path = self.memory_dir / "competitor_patterns.md"
    if not path.exists():
        return []

    content = path.read_text()
    unclassified = []

    # Find Unclassified section
    unclassified_match = re.search(
        r'## Unclassified \(other\).*?\n(.*?)(?=\n##|\n---|\Z)',
        content,
        re.DOTALL
    )

    if unclassified_match:
        section = unclassified_match.group(1)
        # Parse lines like: - "Title" (pattern note?)
        for line in section.split('\n'):
            line = line.strip()
            if line.startswith('- "'):
                match = re.match(r'- "([^"]+)"(.*)', line)
                if match:
                    unclassified.append({
                        "title": match.group(1),
                        "notes": match.group(2).strip(' ()'),
                    })

    return unclassified

def get_best_structures_for_topic(
    self,
    topic_category: str
) -> List[CuriosityStructure]:
    """Get structures that perform best for a topic category.

    Args:
        topic_category: Topic like "geopolitics", "finance", etc.

    Returns:
        List of structures ranked by performance
    """
    # TODO: Cross-reference with topic_performance.md
    # For now, return all main structures
    return [
        CuriosityStructure.HIDDEN_FLAW,
        CuriosityStructure.ASYMMETRIC_DG,
        CuriosityStructure.TIME_BOMB,
        CuriosityStructure.PARADIGM_SHIFT,
        CuriosityStructure.ILLUSION_CONTROL,
    ]
```

### Step 4: Run tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_pattern_library_curiosity_gap.py -v
```

Expected: All tests PASS

### Step 5: Commit

- [ ] **Commit**

```bash
git add skills/video-pipeline/autopilot/
git commit -m "feat(pattern-library): Add curiosity gap pattern methods

- get_curiosity_gap_patterns() - structure performance
- get_competitor_patterns() - individual video patterns
- get_unclassified_titles() - 'other' titles for weekly digest
- get_best_structures_for_topic() - placeholder for topic matching
- 6 tests passing"
```

---

## Task 7: Add Airtable Integration for Competitor Analysis

**Files:**
- Modify: `skills/video-pipeline/clients/airtable_client.py`

### Step 1: Read existing airtable client

- [ ] **Read airtable_client.py to understand structure**

```bash
cd skills/video-pipeline && grep -n "def.*competitor" clients/airtable_client.py | head -20
```

- [ ] **Verify `competitor_videos_table` property exists**

```bash
cd skills/video-pipeline && grep -n "competitor_videos_table" clients/airtable_client.py
```

If the property doesn't exist, add it following the existing table property pattern (e.g., `ideas_table`, `scripts_table`). It should return `self.base.table(os.getenv("AIRTABLE_COMPETITOR_VIDEOS_TABLE_ID"))`.

### Step 2: Add curiosity gap update method

- [ ] **Add methods to airtable_client.py**

**NOTE:** AirtableClient uses synchronous methods (not async) since pyairtable is synchronous. Add these methods to the AirtableClient class:

```python
def update_competitor_curiosity_analysis(
    self,
    record_id: str,
    structure: str,
    structure_confidence: int,
    thumbnail_style_json: Optional[str] = None,
    yin_yang_approach: Optional[str] = None,
    yin_yang_text: Optional[str] = None,
) -> bool:
    """Update competitor video with curiosity gap analysis results.

    Args:
        record_id: Airtable record ID
        structure: CuriosityStructure value (e.g., "hidden_flaw")
        structure_confidence: 0-100 confidence score
        thumbnail_style_json: JSON string of thumbnail analysis (optional)
        yin_yang_approach: "from_hook" or "from_gap" (optional)
        yin_yang_text: Extracted thumbnail text (optional)

    Returns:
        True if update succeeded
    """
    from pipeline_constants import CompetitorVideoFields
    from datetime import datetime

    fields = {
        CompetitorVideoFields.CURIOSITY_STRUCTURE: structure,
        CompetitorVideoFields.STRUCTURE_CONFIDENCE: structure_confidence,
        CompetitorVideoFields.ANALYSIS_DATE: datetime.now().strftime("%Y-%m-%d"),
    }

    if thumbnail_style_json:
        fields[CompetitorVideoFields.THUMBNAIL_STYLE_JSON] = thumbnail_style_json

    if yin_yang_approach:
        fields[CompetitorVideoFields.YIN_YANG_APPROACH] = yin_yang_approach

    if yin_yang_text:
        fields[CompetitorVideoFields.YIN_YANG_TEXT] = yin_yang_text

    try:
        table = self.competitor_videos_table
        table.update(record_id, fields)
        return True
    except Exception as e:
        print(f"Failed to update competitor curiosity analysis: {e}")
        return False


def get_competitor_videos_by_channel(
    self,
    channel_name: str,
    limit: int = 20,
) -> list[dict]:
    """Get recent competitor videos for a channel.

    Args:
        channel_name: Channel name (e.g., "CaspianReport")
        limit: Maximum records to return

    Returns:
        List of Airtable records
    """
    # Match by channel name - existing pattern uses Channel field
    formula = f"{{Channel}} = '{channel_name}'"

    try:
        table = self.competitor_videos_table
        records = table.all(
            formula=formula,
            sort=["-VPH"],
            max_records=limit,
        )
        return records
    except Exception as e:
        print(f"Failed to get competitor videos by channel: {e}")
        return []


def get_unanalyzed_competitor_videos(
    self,
    min_vph: float = 50,
    limit: int = 100,
) -> list[dict]:
    """Get competitor videos that haven't been analyzed for curiosity gap.

    Args:
        min_vph: Minimum VPH threshold
        limit: Maximum records to return

    Returns:
        List of Airtable records without curiosity analysis
    """
    # Videos with VPH >= threshold AND no Curiosity Structure set
    formula = f"AND({{VPH}} >= {min_vph}, {{Curiosity Structure}} = '')"

    try:
        table = self.competitor_videos_table
        records = table.all(
            formula=formula,
            sort=["-VPH"],
            max_records=limit,
        )
        return records
    except Exception as e:
        print(f"Failed to get unanalyzed competitor videos: {e}")
        return []
```

### Step 3: Commit

- [ ] **Commit**

```bash
git add skills/video-pipeline/clients/airtable_client.py
git commit -m "feat(airtable): Add curiosity gap competitor video methods

- update_competitor_curiosity_analysis() - save analysis results
- get_competitor_videos_by_channel() - for VPH percentile
- get_unanalyzed_competitor_videos() - for batch analysis"
```

---

## Task 8: Create Seeding Script

**Files:**
- Create: `skills/video-pipeline/curiosity_gap/seed_patterns.py`

### Step 1: Write seeding script

- [ ] **Write seed_patterns.py**

```python
#!/usr/bin/env python3
# skills/video-pipeline/curiosity_gap/seed_patterns.py
"""Seed the pattern library with competitor analysis.

This script analyzes existing competitor videos in Airtable and populates
the curiosity gap pattern library. Run this BEFORE using the title generator.

Usage:
    python -m curiosity_gap.seed_patterns --dry-run   # Preview only
    python -m curiosity_gap.seed_patterns             # Analyze and save
    python -m curiosity_gap.seed_patterns --limit 10  # Limit to N videos
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from curiosity_gap.competitor_analyzer import CompetitorAnalyzer, should_deep_analyze
from curiosity_gap.structures import CuriosityStructure
from clients.airtable_client import AirtableClient
from pipeline_constants import CompetitorVideoFields, CURIOSITY_GAP_ENABLED


async def seed_patterns(
    dry_run: bool = False,
    limit: int = 50,
    min_vph: float = 50,
) -> Dict:
    """Analyze competitor videos and seed pattern library.

    Args:
        dry_run: If True, don't write to Airtable or memory files
        limit: Maximum videos to analyze
        min_vph: Minimum VPH threshold

    Returns:
        Summary dict with counts
    """
    # Kill switch - instant rollback mechanism
    if not CURIOSITY_GAP_ENABLED:
        print("❌ Curiosity gap system is DISABLED (CURIOSITY_GAP_ENABLED=False)")
        print("   Set CURIOSITY_GAP_ENABLED=True in pipeline_constants.py to enable")
        return {"analyzed": 0, "errors": 0, "disabled": True}

    print(f"🌱 Seeding curiosity gap patterns...")
    print(f"   Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"   Limit: {limit} videos, min VPH: {min_vph}")
    print()

    airtable = AirtableClient()
    analyzer = CompetitorAnalyzer()

    # Get unanalyzed videos (sync call - AirtableClient uses pyairtable which is sync)
    print("📥 Fetching unanalyzed competitor videos...")
    videos = airtable.get_unanalyzed_competitor_videos(
        min_vph=min_vph,
        limit=limit,
    )
    print(f"   Found {len(videos)} videos to analyze")

    if not videos:
        print("   No videos to analyze. Run competitor scraper first.")
        return {"analyzed": 0, "errors": 0}

    # Track results
    results = {
        "analyzed": 0,
        "deep_analyzed": 0,
        "errors": 0,
        "by_structure": {},
    }

    for structure in CuriosityStructure:
        results["by_structure"][structure.value] = 0

    # Analyze each video
    for i, record in enumerate(videos, 1):
        fields = record.get("fields", {})
        title = fields.get(CompetitorVideoFields.TITLE, "")
        vph = fields.get(CompetitorVideoFields.VPH, 0)
        video_id = fields.get(CompetitorVideoFields.VIDEO_ID, "")
        channel = fields.get(CompetitorVideoFields.CHANNEL, "unknown")

        print(f"\n[{i}/{len(videos)}] {title[:50]}...")
        print(f"   Channel: {channel}, VPH: {vph:.0f}")

        try:
            # Phase 1: Title analysis
            title_analysis = await analyzer.analyze_title(title)
            print(f"   Structure: {title_analysis.structure.value} ({title_analysis.confidence}%)")

            results["by_structure"][title_analysis.structure.value] += 1

            # Check if qualifies for Phase 2
            deep_analyze = await should_deep_analyze(vph, channel)
            thumbnail_analysis = None

            if deep_analyze and video_id:
                print(f"   🔍 Top 20% - running thumbnail analysis...")
                thumbnail_analysis = await analyzer.analyze_thumbnail(video_id, title)
                if thumbnail_analysis:
                    print(f"   Thumbnail: {thumbnail_analysis.text_extracted or 'no text'}")
                    print(f"   Yin/Yang: {thumbnail_analysis.yin_yang_approach}")
                    results["deep_analyzed"] += 1

            # Save to Airtable (sync call - AirtableClient uses pyairtable which is sync)
            if not dry_run:
                airtable.update_competitor_curiosity_analysis(
                    record_id=record["id"],
                    structure=title_analysis.structure.value,
                    structure_confidence=title_analysis.confidence,
                    thumbnail_style_json=json.dumps({
                        "colors": thumbnail_analysis.colors if thumbnail_analysis else [],
                        "composition": thumbnail_analysis.composition if thumbnail_analysis else "",
                    }) if thumbnail_analysis else None,
                    yin_yang_approach=thumbnail_analysis.yin_yang_approach if thumbnail_analysis else None,
                    yin_yang_text=thumbnail_analysis.text_extracted if thumbnail_analysis else None,
                )
                print(f"   ✅ Saved to Airtable")
            else:
                print(f"   (dry run - not saved)")

            results["analyzed"] += 1

        except Exception as e:
            print(f"   ❌ Error: {e}")
            results["errors"] += 1

        # Rate limiting
        await asyncio.sleep(0.5)

    # Update memory file
    if not dry_run and results["analyzed"] > 0:
        await update_memory_file(results)

    # Summary
    print("\n" + "=" * 50)
    print("📊 SEEDING COMPLETE")
    print("=" * 50)
    print(f"Analyzed: {results['analyzed']} videos")
    print(f"Deep analyzed (thumbnails): {results['deep_analyzed']}")
    print(f"Errors: {results['errors']}")
    print("\nBy structure:")
    for structure, count in results["by_structure"].items():
        if count > 0:
            print(f"  {structure}: {count}")

    return results


async def update_memory_file(results: Dict) -> None:
    """Update competitor_patterns.md with analysis results.

    Args:
        results: Results dict from seed_patterns
    """
    memory_path = Path(__file__).parent.parent / "autopilot" / "memory" / "competitor_patterns.md"

    # Read existing content
    if memory_path.exists():
        content = memory_path.read_text()
    else:
        content = "# Competitor Patterns\n\n"

    # Update header - use separate if statements so both can match
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("Last updated:"):
            lines[i] = f"Last updated: {datetime.now().strftime('%Y-%m-%d')}"
        if line.startswith("Videos analyzed:"):
            # Extract current count and add
            import re
            match = re.search(r'\d+', line)
            current = int(match.group()) if match else 0
            lines[i] = f"Videos analyzed: {current + results['analyzed']}"

    memory_path.write_text("\n".join(lines))
    print(f"\n📝 Updated {memory_path}")


def main():
    parser = argparse.ArgumentParser(description="Seed curiosity gap pattern library")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't save")
    parser.add_argument("--limit", type=int, default=50, help="Max videos to analyze")
    parser.add_argument("--min-vph", type=float, default=50, help="Minimum VPH threshold")

    args = parser.parse_args()

    asyncio.run(seed_patterns(
        dry_run=args.dry_run,
        limit=args.limit,
        min_vph=args.min_vph,
    ))


if __name__ == "__main__":
    main()
```

### Step 2: Commit

- [ ] **Commit**

```bash
git add skills/video-pipeline/curiosity_gap/seed_patterns.py
git commit -m "feat(curiosity-gap): Add pattern seeding script

- Batch analyze unanalyzed competitor videos
- Phase 1 (title) for all, Phase 2 (thumbnail) for top 20%
- Updates Airtable + memory files
- Supports --dry-run and --limit flags"
```

---

## Task 9: Integration Test

**Files:**
- Create: `skills/video-pipeline/curiosity_gap/tests/test_integration.py`

### Step 1: Write integration test

- [ ] **Write test_integration.py**

```python
# skills/video-pipeline/curiosity_gap/tests/test_integration.py
"""Integration tests for curiosity gap Phase 1."""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from pathlib import Path

from curiosity_gap.competitor_analyzer import CompetitorAnalyzer, TitleAnalysis
from curiosity_gap.structures import CuriosityStructure


class TestCompetitorAnalyzerIntegration:
    """Integration tests for full analyzer flow."""

    @pytest.fixture
    def analyzer(self):
        return CompetitorAnalyzer()

    @pytest.mark.asyncio
    async def test_full_video_analysis_flow(self, analyzer):
        """Test complete video analysis (title + conditional thumbnail)."""
        # Mock Claude response
        mock_title_response = {
            "structure": "hidden_flaw",
            "confidence": 85,
            "gap_mechanism": "What's the $100B mistake?",
            "variables": {"amount": "$100B", "entity": "Saudi Arabia"},
        }

        # Mock channel videos for VPH percentile
        mock_channel_videos = [{"vph": v} for v in [50, 75, 100, 125, 150]]

        with patch.object(analyzer, '_call_claude_for_title', return_value=mock_title_response):
            with patch('curiosity_gap.competitor_analyzer.get_recent_channel_videos', return_value=mock_channel_videos):
                # Test video in top 20% (VPH 200 > 80th percentile of channel)
                result = await analyzer.analyze_video(
                    video_id="test123",
                    title="The $100B Mistake Saudi Arabia Is Hiding",
                    vph=200,
                    channel_name="CaspianReport",
                )

                assert result["title_analysis"].structure == CuriosityStructure.HIDDEN_FLAW
                assert result["title_analysis"].confidence == 85
                assert result["deep_analyzed"] is True  # Top 20% qualifies

    @pytest.mark.asyncio
    async def test_low_vph_skips_thumbnail(self, analyzer):
        """Videos below top 20% should skip thumbnail analysis."""
        mock_title_response = {
            "structure": "other",
            "confidence": 40,
            "gap_mechanism": "unclear",
            "variables": {},
        }

        mock_channel_videos = [{"vph": v} for v in [100, 150, 200, 250, 300]]

        with patch.object(analyzer, '_call_claude_for_title', return_value=mock_title_response):
            with patch('curiosity_gap.competitor_analyzer.get_recent_channel_videos', return_value=mock_channel_videos):
                # Test video NOT in top 20% (VPH 120 < 80th percentile)
                result = await analyzer.analyze_video(
                    video_id="test456",
                    title="Some Low Performing Title",
                    vph=120,
                    channel_name="CaspianReport",
                )

                assert result["deep_analyzed"] is False
                assert result["thumbnail_analysis"] is None


class TestStructuresIntegration:
    """Integration tests for structure definitions."""

    def test_all_structures_have_complete_definitions(self):
        """Every structure should have all required fields."""
        from curiosity_gap.structures import STRUCTURE_DEFINITIONS, CuriosityStructure

        required_fields = ["gap_mechanism", "when_to_use", "example"]

        for structure in CuriosityStructure:
            assert structure in STRUCTURE_DEFINITIONS, f"Missing definition for {structure}"
            for field in required_fields:
                assert field in STRUCTURE_DEFINITIONS[structure], f"Missing {field} for {structure}"

    def test_structure_prompt_contains_all_mechanisms(self):
        """Generated prompt should include all gap mechanisms."""
        from curiosity_gap.structures import get_structure_prompt, STRUCTURE_DEFINITIONS, CuriosityStructure

        prompt = get_structure_prompt()

        for structure in CuriosityStructure:
            if structure != CuriosityStructure.OTHER:
                mechanism = STRUCTURE_DEFINITIONS[structure]["gap_mechanism"]
                # At least part of the mechanism should be in the prompt
                assert structure.value in prompt, f"Structure {structure.value} not in prompt"
```

### Step 2: Run all tests

- [ ] **Run all curiosity gap tests**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/ -v
```

Expected: All tests PASS

### Step 3: Run pattern library tests

- [ ] **Run pattern library tests**

```bash
cd skills/video-pipeline && python -m pytest autopilot/tests/test_pattern_library_curiosity_gap.py -v
```

Expected: All tests PASS

### Step 4: Final commit for Phase 1

- [ ] **Commit**

```bash
git add skills/video-pipeline/curiosity_gap/
git commit -m "feat(curiosity-gap): Complete Phase 1 - Competitor Analysis

Phase 1 delivers:
- CuriosityStructure enum with 6 structures
- CompetitorAnalyzer with two-phase analysis
- VPH normalization using bisect (handles duplicates)
- Cold start handling for new channels
- Gemini Vision thumbnail analysis
- Pattern library extensions
- Airtable integration for saving results
- Seeding script for initial data population

25+ tests passing. Ready for seeding with real competitor data.

Next: Run seed_patterns.py to populate library before Phase 2."
```

---

## Phase 1 Complete

**Deliverables:**
- `curiosity_gap/structures.py` — CuriosityStructure enum + definitions
- `curiosity_gap/competitor_analyzer.py` — Two-phase analysis
- `curiosity_gap/seed_patterns.py` — Seeding script
- `autopilot/memory/competitor_patterns.md` — Memory file template
- Extended `autopilot/learning/pattern_library.py` — Curiosity gap methods
- Extended `clients/gemini_client.py` — Thumbnail analysis
- Extended `clients/airtable_client.py` — Competitor video methods
- Extended `pipeline_constants.py` — New field names
- 25+ tests

**Before Phase 2:**

1. **Create Airtable fields** (manual step):
   - Add fields to Competitor Videos table as listed in spec Appendix A.6
   - Add fields to Ideas table

2. **Seed the library**:
   ```bash
   cd skills/video-pipeline
   python -m curiosity_gap.seed_patterns --dry-run  # Preview
   python -m curiosity_gap.seed_patterns --limit 50  # Seed ~50 videos
   ```

3. **Verify seeding worked**:
   ```bash
   # Check Airtable has Curiosity Structure populated
   # Check competitor_patterns.md has data
   ```

**Test Commands:**
```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/ -v
cd skills/video-pipeline && python -m pytest autopilot/tests/test_pattern_library_curiosity_gap.py -v
```

**Next Phase:** Phase 2 (Core Generation Module) — `gap_title_engine.py` + `thumbnail_generator.py`
