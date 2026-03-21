# Curiosity Gap Phase 2: Title Generator Integration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing `gap_title_engine.py` into the idea generation flow so new ideas get curiosity-gap-optimized titles with structure metadata saved to Airtable.

**Architecture:** The `GapTitleEngine` already exists and generates titles with structure scoring. This plan wires it into `idea_bot.py` to generate titles during idea creation, adds Airtable methods to save structure metadata, and adds a Slack command for on-demand regeneration.

**Tech Stack:** Python 3.11+, async, existing `GapTitleEngine`, `AirtableClient`, `SlackClient`

**Related Files:**
- Engine: `skills/video-pipeline/curiosity_gap/gap_title_engine.py` (exists, 437 lines)
- Patterns: `skills/video-pipeline/autopilot/learning/pattern_library.py` (exists)
- Integration target: `skills/video-pipeline/bots/idea_bot.py`
- Tests: `skills/video-pipeline/curiosity_gap/tests/test_gap_title_engine.py` (13 tests exist)

---

## File Structure

```
skills/video-pipeline/
├── curiosity_gap/
│   ├── gap_title_engine.py          # EXISTS - no changes needed
│   └── tests/
│       └── test_gap_title_engine.py  # EXISTS - add integration tests
│
├── bots/
│   └── idea_bot.py                   # MODIFY - integrate GapTitleEngine
│
├── clients/
│   └── airtable_client.py            # MODIFY - add update_idea_curiosity_structure()
│
├── run_gap_titles.py                 # CREATE - CLI runner for testing
│
└── pipeline_control.py               # MODIFY - add Slack command
```

---

## Task 1: Add Airtable Method for Curiosity Structure Metadata

**Files:**
- Modify: `skills/video-pipeline/clients/airtable_client.py`

The Airtable fields already exist (`IdeaFields.CURIOSITY_STRUCTURE`, `STRUCTURE_CONFIDENCE`, `THUMBNAIL_APPROACH`). We need a method to update them.

### Step 1: Write the test

- [ ] **Write test for update_idea_curiosity_structure**

```python
# Add to existing test file or create new test
# skills/video-pipeline/tests/test_airtable_curiosity.py

import pytest
from unittest.mock import Mock, patch
from clients.airtable_client import AirtableClient


class TestAirtableCuriosityStructure:
    """Tests for curiosity structure updates."""

    def test_update_idea_curiosity_structure(self):
        """Should update curiosity structure fields on idea record."""
        client = AirtableClient()

        with patch.object(client, 'idea_concepts_table') as mock_table:
            mock_table.update.return_value = {"id": "rec123"}

            client.update_idea_curiosity_structure(
                record_id="rec123",
                structure="hidden_flaw",
                confidence=85,
                thumbnail_text="WORTHLESS PIPELINES",
                thumbnail_approach="from_gap",
            )

            mock_table.update.assert_called_once()
            call_args = mock_table.update.call_args[0]
            assert call_args[0] == "rec123"
            assert call_args[1]["Curiosity Structure"] == "hidden_flaw"
            assert call_args[1]["Structure Confidence"] == 85
            assert call_args[1]["Thumbnail Approach"] == "from_gap"
```

### Step 2: Run test to verify it fails

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest tests/test_airtable_curiosity.py -v
```

Expected: FAIL with `AttributeError: 'AirtableClient' object has no attribute 'update_idea_curiosity_structure'`

### Step 3: Implement the method

- [ ] **Add method to airtable_client.py**

Find the `AirtableClient` class and add this method:

```python
def update_idea_curiosity_structure(
    self,
    record_id: str,
    structure: str,
    confidence: int,
    thumbnail_text: str = "",
    thumbnail_approach: str = "from_gap",
) -> dict:
    """Update curiosity structure metadata on an idea record.

    Args:
        record_id: Airtable record ID
        structure: CuriosityStructure value (e.g., "hidden_flaw")
        confidence: 0-100 confidence score
        thumbnail_text: Thumbnail text (2-4 words, ALL CAPS)
        thumbnail_approach: "from_hook" or "from_gap"

    Returns:
        Updated record dict
    """
    fields = {
        IdeaFields.CURIOSITY_STRUCTURE: structure,
        IdeaFields.STRUCTURE_CONFIDENCE: confidence,
        IdeaFields.THUMBNAIL_APPROACH: thumbnail_approach,
    }

    if thumbnail_text:
        fields[IdeaFields.THUMBNAIL_TEXT] = thumbnail_text

    return self.idea_concepts_table.update(record_id, fields)
```

### Step 4: Run test to verify it passes

- [ ] **Run test**

```bash
cd skills/video-pipeline && python -m pytest tests/test_airtable_curiosity.py -v
```

Expected: PASS

### Step 5: Commit

- [ ] **Commit**

```bash
git add clients/airtable_client.py tests/test_airtable_curiosity.py
git commit -m "feat(airtable): Add update_idea_curiosity_structure method"
```

---

## Task 2: Integrate GapTitleEngine into IdeaBot

**Files:**
- Modify: `skills/video-pipeline/bots/idea_bot.py`

### Step 1: Add GapTitleEngine to IdeaBot

- [ ] **Add import and initialization**

At the top of `idea_bot.py`, add:

```python
from curiosity_gap.gap_title_engine import GapTitleEngine, GeneratedTitle
from autopilot.learning.pattern_library import PatternLibrary
from pipeline_constants import CURIOSITY_GAP_ENABLED
```

In `IdeaBot.__init__`, add:

```python
def __init__(
    self,
    anthropic_client,
    airtable_client,
    gemini_client=None,
    slack_client=None,
    gap_title_engine=None,  # NEW
    pattern_library=None,    # NEW
):
    # ... existing code ...
    self.gap_title_engine = gap_title_engine
    self.pattern_library = pattern_library
```

### Step 2: Add title enhancement method

- [ ] **Add _enhance_title_with_curiosity_gap method**

```python
async def _enhance_title_with_curiosity_gap(
    self,
    idea: dict,
) -> dict:
    """Enhance idea with curiosity gap optimized title.

    Args:
        idea: Idea dict from generate_video_ideas

    Returns:
        Enhanced idea dict with structure metadata
    """
    if not CURIOSITY_GAP_ENABLED:
        return idea

    # Lazy initialize engine if needed
    if self.gap_title_engine is None:
        self.gap_title_engine = GapTitleEngine(self.anthropic)

    if self.pattern_library is None:
        self.pattern_library = PatternLibrary()

    # Build story context from idea
    story_context = {
        "hook": idea.get("hook_script", ""),
        "thesis": idea.get("narrative_logic", {}).get("present_parallel", ""),
        "facts": [],  # Could extract from research if available
    }

    try:
        titles = await self.gap_title_engine.generate_titles(
            story_context,
            pattern_library=self.pattern_library,
            target_count=1,  # Just need best title
        )

        if titles:
            best = titles[0]
            idea["viral_title"] = best.text
            idea["curiosity_structure"] = best.structure.value
            idea["structure_confidence"] = best.structure_confidence
            idea["thumbnail_text"] = best.thumbnail_text
            idea["thumbnail_approach"] = best.thumbnail_approach
            print(f"    Enhanced title: {best.text}")
            print(f"    Structure: {best.structure.value} ({best.structure_confidence}%)")

    except Exception as e:
        print(f"    Curiosity gap enhancement failed: {e}")
        # Non-blocking - keep original title

    return idea
```

### Step 3: Wire into generate_ideas

- [ ] **Call enhancement in generate_ideas**

In the `generate_ideas` method, after `ideas = await self.anthropic.generate_video_ideas(video_dna)`, add:

```python
# Enhance with curiosity gap titles
if CURIOSITY_GAP_ENABLED:
    print("  Enhancing with curiosity gap structures...")
    enhanced_ideas = []
    for idea in ideas:
        enhanced = await self._enhance_title_with_curiosity_gap(idea)
        enhanced_ideas.append(enhanced)
    ideas = enhanced_ideas
```

### Step 4: Update Airtable save to include structure metadata

- [ ] **Save structure metadata when saving to Airtable**

In the Airtable save loop, after `record = self.airtable.create_idea(idea, source="url_analysis")`, add:

```python
# Save curiosity structure metadata if present
if idea.get("curiosity_structure"):
    try:
        self.airtable.update_idea_curiosity_structure(
            record_id=record.get("id"),
            structure=idea.get("curiosity_structure"),
            confidence=idea.get("structure_confidence", 0),
            thumbnail_text=idea.get("thumbnail_text", ""),
            thumbnail_approach=idea.get("thumbnail_approach", "from_gap"),
        )
    except Exception as e:
        print(f"    Warning: Could not save structure metadata: {e}")
```

### Step 5: Test manually

- [ ] **Test with a real idea**

```bash
cd skills/video-pipeline
python -c "
import asyncio
from bots.idea_bot import IdeaBot
from clients.anthropic_client import AnthropicClient
from clients.airtable_client import AirtableClient

async def test():
    bot = IdeaBot(
        anthropic_client=AnthropicClient(),
        airtable_client=AirtableClient(),
    )
    ideas = await bot.generate_ideas(
        'China dollar reserves declining rapidly',
        save_to_airtable=False,
        notify_slack=False,
    )
    for idea in ideas:
        print(f'Title: {idea.get(\"viral_title\")}')
        print(f'Structure: {idea.get(\"curiosity_structure\")}')
        print()

asyncio.run(test())
"
```

### Step 6: Commit

- [ ] **Commit**

```bash
git add bots/idea_bot.py
git commit -m "feat(idea-bot): Integrate curiosity gap title generation

- Generate curiosity-gap-optimized titles for new ideas
- Save structure metadata to Airtable
- Non-blocking: falls back to original title on failure"
```

---

## Task 3: Create CLI Runner Script

**Files:**
- Create: `skills/video-pipeline/run_gap_titles.py`

### Step 1: Write the runner script

- [ ] **Create run_gap_titles.py**

```python
#!/usr/bin/env python3
"""Run curiosity gap title generation.

Usage:
    python run_gap_titles.py "China's dollar reserves are declining"
    python run_gap_titles.py --record rec123  # Regenerate for existing idea
    python run_gap_titles.py --dry-run "topic"  # Preview only
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from curiosity_gap.gap_title_engine import GapTitleEngine
from autopilot.learning.pattern_library import PatternLibrary
from clients.anthropic_client import AnthropicClient
from clients.airtable_client import AirtableClient
from pipeline_constants import CURIOSITY_GAP_ENABLED


async def generate_titles_for_topic(topic: str, dry_run: bool = False) -> None:
    """Generate titles for a topic description."""
    print(f"\n🎯 Generating curiosity gap titles for: {topic}\n")

    if not CURIOSITY_GAP_ENABLED:
        print("❌ CURIOSITY_GAP_ENABLED is False. Enable in pipeline_constants.py")
        return

    engine = GapTitleEngine(AnthropicClient())
    pattern_library = PatternLibrary()

    story_context = {
        "hook": topic,
        "thesis": topic,
        "facts": [],
    }

    titles = await engine.generate_titles(
        story_context,
        pattern_library=pattern_library,
        target_count=3,
    )

    if not titles:
        print("❌ No titles generated (all structures below confidence floor)")
        return

    print("Generated titles:\n")
    for i, title in enumerate(titles, 1):
        print(f"{i}. {title.text}")
        print(f"   Structure: {title.structure.value} ({title.structure_confidence}%)")
        print(f"   Thumbnail: {title.thumbnail_text} ({title.thumbnail_approach})")
        print(f"   Reasoning: {title.reasoning}")
        print()


async def regenerate_for_record(record_id: str, dry_run: bool = False) -> None:
    """Regenerate titles for an existing Airtable idea record."""
    print(f"\n🔄 Regenerating titles for record: {record_id}\n")

    airtable = AirtableClient()
    record = airtable.get_idea(record_id)

    if not record:
        print(f"❌ Record not found: {record_id}")
        return

    fields = record.get("fields", {})
    title = fields.get("Video Title", "")
    hook = fields.get("Hook Script", "")
    thesis = fields.get("Thesis", "")

    print(f"Current title: {title}")
    print(f"Hook: {hook[:100]}..." if len(hook) > 100 else f"Hook: {hook}")

    engine = GapTitleEngine(AnthropicClient())
    pattern_library = PatternLibrary()

    story_context = {
        "hook": hook or title,
        "thesis": thesis or title,
        "facts": [],
    }

    titles = await engine.generate_titles(
        story_context,
        pattern_library=pattern_library,
        target_count=3,
    )

    if not titles:
        print("❌ No titles generated")
        return

    print("\nGenerated alternatives:\n")
    for i, t in enumerate(titles, 1):
        print(f"{i}. {t.text}")
        print(f"   Structure: {t.structure.value} ({t.structure_confidence}%)")
        print()

    if dry_run:
        print("(dry run - not saving)")
        return

    # Update with best title
    best = titles[0]
    print(f"\nSaving best title: {best.text}")

    airtable.update_idea_curiosity_structure(
        record_id=record_id,
        structure=best.structure.value,
        confidence=best.structure_confidence,
        thumbnail_text=best.thumbnail_text,
        thumbnail_approach=best.thumbnail_approach,
    )

    # Also update the title itself
    airtable.ideas_table.update(record_id, {"Video Title": best.text})

    print("✅ Saved")


def main():
    parser = argparse.ArgumentParser(description="Generate curiosity gap titles")
    parser.add_argument("topic", nargs="?", help="Topic to generate titles for")
    parser.add_argument("--record", help="Airtable record ID to regenerate")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")

    args = parser.parse_args()

    if args.record:
        asyncio.run(regenerate_for_record(args.record, args.dry_run))
    elif args.topic:
        asyncio.run(generate_titles_for_topic(args.topic, args.dry_run))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

### Step 2: Test the runner

- [ ] **Test with a topic**

```bash
cd skills/video-pipeline && python run_gap_titles.py "China's dollar reserves declining"
```

### Step 3: Commit

- [ ] **Commit**

```bash
git add run_gap_titles.py
git commit -m "feat: Add CLI runner for curiosity gap title generation"
```

---

## Task 4: Add Slack Command

**Files:**
- Modify: `skills/video-pipeline/pipeline_control.py`

### Step 1: Find the command handler section

- [ ] **Locate where Slack commands are handled**

Search for existing command patterns like `!status` or `autopilot`.

### Step 2: Add the gap titles command

- [ ] **Add handler for `gap titles` command**

In the command handling section, add:

```python
# Curiosity gap title commands
elif message_lower.startswith("gap titles "):
    # gap titles rec123 - regenerate titles for a record
    parts = message_lower.split()
    if len(parts) >= 3:
        record_id = parts[2]
        await self._handle_gap_titles(record_id, channel)
    else:
        await self.slack.send_message(
            "Usage: `gap titles <record_id>` - Regenerate curiosity gap titles for an idea",
            channel=channel,
        )

elif message_lower == "gap titles":
    await self.slack.send_message(
        "Usage: `gap titles <record_id>` - Regenerate curiosity gap titles for an idea",
        channel=channel,
    )
```

### Step 3: Add the handler method

- [ ] **Implement _handle_gap_titles**

```python
async def _handle_gap_titles(self, record_id: str, channel: str) -> None:
    """Handle gap titles command."""
    from curiosity_gap.gap_title_engine import GapTitleEngine
    from autopilot.learning.pattern_library import PatternLibrary
    from pipeline_constants import CURIOSITY_GAP_ENABLED

    if not CURIOSITY_GAP_ENABLED:
        await self.slack.send_message(
            "❌ Curiosity gap system is disabled",
            channel=channel,
        )
        return

    await self.slack.send_message(
        f"🎯 Generating curiosity gap titles for `{record_id}`...",
        channel=channel,
    )

    try:
        record = self.airtable.get_idea(record_id)
        if not record:
            await self.slack.send_message(
                f"❌ Record not found: `{record_id}`",
                channel=channel,
            )
            return

        fields = record.get("fields", {})
        hook = fields.get("Hook Script", "")
        thesis = fields.get("Thesis", "")
        current_title = fields.get("Video Title", "")

        engine = GapTitleEngine(self.anthropic)
        pattern_library = PatternLibrary()

        story_context = {
            "hook": hook or current_title,
            "thesis": thesis or current_title,
            "facts": [],
        }

        titles = await engine.generate_titles(
            story_context,
            pattern_library=pattern_library,
            target_count=3,
        )

        if not titles:
            await self.slack.send_message(
                "❌ No titles generated (all structures below confidence floor)",
                channel=channel,
            )
            return

        # Format response
        response = f"*Current:* {current_title}\n\n*Alternatives:*\n"
        for i, t in enumerate(titles, 1):
            response += f"{i}. {t.text}\n"
            response += f"   _{t.structure.value}_ ({t.structure_confidence}%)\n"

        response += f"\nReply `gap select {record_id} 1` to use title #1"

        await self.slack.send_message(response, channel=channel)

    except Exception as e:
        await self.slack.send_message(
            f"❌ Error: {e}",
            channel=channel,
        )
```

### Step 4: Add gap select command

- [ ] **Add handler for `gap select` to apply a title**

```python
elif message_lower.startswith("gap select "):
    # gap select rec123 1 - select title option 1
    parts = message_lower.split()
    if len(parts) >= 4:
        record_id = parts[2]
        selection = int(parts[3])
        await self._handle_gap_select(record_id, selection, channel)
    else:
        await self.slack.send_message(
            "Usage: `gap select <record_id> <number>` - Select a title option",
            channel=channel,
        )
```

### Step 4b: Implement _handle_gap_select method

- [ ] **Add _handle_gap_select method**

```python
async def _handle_gap_select(self, record_id: str, selection: int, channel: str) -> None:
    """Apply a previously generated title option by regenerating and selecting by index."""
    from curiosity_gap.gap_title_engine import GapTitleEngine
    from autopilot.learning.pattern_library import PatternLibrary

    try:
        record = self.airtable.get_idea(record_id)
        if not record:
            await self.slack.send_message(
                f"❌ Record not found: `{record_id}`",
                channel=channel,
            )
            return

        fields = record.get("fields", {})
        hook = fields.get("Hook Script", "")
        thesis = fields.get("Thesis", "")
        current_title = fields.get("Video Title", "")

        engine = GapTitleEngine(self.anthropic)
        pattern_library = PatternLibrary()

        story_context = {
            "hook": hook or current_title,
            "thesis": thesis or current_title,
            "facts": [],
        }

        titles = await engine.generate_titles(
            story_context,
            pattern_library=pattern_library,
            target_count=3,
        )

        if not titles or selection < 1 or selection > len(titles):
            await self.slack.send_message(
                f"❌ Invalid selection. Must be 1-{len(titles) if titles else 0}",
                channel=channel,
            )
            return

        selected = titles[selection - 1]

        # Update Airtable with selected title
        self.airtable.idea_concepts_table.update(
            record_id,
            {"Video Title": selected.text}
        )
        self.airtable.update_idea_curiosity_structure(
            record_id=record_id,
            structure=selected.structure.value,
            confidence=selected.structure_confidence,
            thumbnail_text=selected.thumbnail_text,
            thumbnail_approach=selected.thumbnail_approach,
        )

        await self.slack.send_message(
            f"✅ Applied title #{selection}:\n*{selected.text}*\n_{selected.structure.value}_ ({selected.structure_confidence}%)",
            channel=channel,
        )

    except Exception as e:
        await self.slack.send_message(
            f"❌ Error: {e}",
            channel=channel,
        )
```

### Step 5: Commit

- [ ] **Commit**

```bash
git add pipeline_control.py
git commit -m "feat(slack): Add gap titles command for title regeneration"
```

---

## Task 5: Add Integration Tests

**Files:**
- Modify: `skills/video-pipeline/curiosity_gap/tests/test_integration.py`

### Step 1: Add integration test for idea bot flow

- [ ] **Add test_idea_bot_with_curiosity_gap**

```python
class TestIdeaBotCuriosityGapIntegration:
    """Integration tests for idea bot with curiosity gap."""

    @pytest.fixture
    def mock_anthropic(self):
        mock = Mock()
        mock.generate_video_ideas = AsyncMock(return_value=[
            {
                "viral_title": "China's Dollar Crisis",
                "hook_script": "China's dollar reserves are declining at record pace.",
                "narrative_logic": {
                    "past_context": "China accumulated $4T in reserves",
                    "present_parallel": "Now losing $100B per month",
                    "future_prediction": "Could trigger currency crisis",
                },
            }
        ])
        mock.generate = AsyncMock(return_value='{"titles": [{"text": "The $3T Trap China Cannot Escape", "structure": "time_bomb", "confidence": 85, "thumbnail_text": "CHECKMATE", "thumbnail_approach": "from_gap", "reasoning": "Long-term trap framing"}]}')
        return mock

    @pytest.fixture
    def mock_airtable(self):
        mock = Mock()
        mock.create_idea = Mock(return_value={"id": "rec123"})
        mock.update_idea_curiosity_structure = Mock()
        return mock

    def test_generate_ideas_with_curiosity_gap(self, mock_anthropic, mock_airtable):
        """Should enhance ideas with curiosity gap titles."""
        from bots.idea_bot import IdeaBot

        bot = IdeaBot(
            anthropic_client=mock_anthropic,
            airtable_client=mock_airtable,
        )

        async def run_test():
            ideas = await bot.generate_ideas(
                "China dollar reserves",
                save_to_airtable=True,
                notify_slack=False,
            )
            return ideas

        # CURIOSITY_GAP_ENABLED defaults to True in pipeline_constants

        ideas = run_async(run_test())

        # Should have enhanced title
        assert len(ideas) == 1
        # Structure metadata should be saved
        mock_airtable.update_idea_curiosity_structure.assert_called()
```

### Step 2: Run all curiosity gap tests

- [ ] **Run tests**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/ -v
```

### Step 3: Commit

- [ ] **Commit**

```bash
git add curiosity_gap/tests/
git commit -m "test: Add integration tests for idea bot curiosity gap flow"
```

---

## Task 6: Final Verification

### Step 1: Run all tests

- [ ] **Run full test suite**

```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/ -v
```

### Step 2: Test CLI runner on VPS

- [ ] **SSH and test**

```bash
ssh clawd@76.13.119.181
cd /home/clawd/projects/economy-fastforward/skills/video-pipeline
git pull
python3 run_gap_titles.py "China dollar reserves declining"
```

### Step 3: Test Slack command

- [ ] **Send Slack command**

In Slack: `gap titles rec123` (use a real record ID)

### Step 4: Final commit

- [ ] **Commit**

```bash
git add .
git commit -m "feat(curiosity-gap): Complete Phase 2 - title generator integration

- IdeaBot generates curiosity-gap-optimized titles
- Structure metadata saved to Airtable
- CLI runner for testing
- Slack command for regeneration
- Integration tests"
```

---

## Summary

**What this plan accomplishes:**
1. Wires existing `GapTitleEngine` into `IdeaBot` for automatic title enhancement
2. Adds Airtable method to save structure metadata
3. Adds CLI runner for testing/debugging
4. Adds Slack command for on-demand regeneration
5. Adds integration tests

**Test command:**
```bash
cd skills/video-pipeline && python -m pytest curiosity_gap/tests/ -v
```

**Manual test:**
```bash
python run_gap_titles.py "China's dollar reserves are declining"
```

**Slack commands:**
- `gap titles <record_id>` - Generate alternatives
- `gap select <record_id> <number>` - Apply selected title
