# Per-Act Background Music Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-act background music beds to the video pipeline — mood classification via Claude Haiku, track selection from Google Drive, and crossfade rendering in Remotion.

**Architecture:** Three components: (1) `music_selector.py` classifies act moods and selects tracks from Drive, (2) `render_video.py` downloads tracks and writes `music_beds` to render_config.json, (3) `MusicBed.tsx` component handles audio looping and crossfades in Remotion.

**Tech Stack:** Python (async), TypeScript/Remotion, Claude Haiku API, Google Drive API

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `skills/video-pipeline/bots/music_selector.py` | Mood classification via Haiku + track selection from Drive |
| `remotion-video/src/components/MusicBed.tsx` | Audio component with looping, crossfades, volume control |
| `remotion-video/public/music/` | Local cache for downloaded music tracks (gitignored) |

### Modified Files
| File | Changes |
|------|---------|
| `skills/video-pipeline/render_video.py` | Add music selection step before render, download tracks, write `music_beds` to render_config |
| `remotion-video/src/renderConfig.ts` | Add `MusicBed` interface |
| `remotion-video/src/Main.tsx` | Import and render `<MusicBed>` component spanning full video |
| `remotion-video/.gitignore` | Add `public/music/` directory |

---

## Task 0: Clean Up Music Library in Google Drive

**Files:**
- None (Drive API operations only)

Music library folder ID: `17FF7IanYzbgfLrIwXIjKwNlqRSkefS9i`

The 18 MP3 files have inconsistent naming. Rename all to `{mood}_{track_name}_{variant}.mp3`.

- [ ] **Step 1: List files in Drive folder**

```bash
cd skills/video-pipeline && python -c "
from clients.google_client import GoogleClient
g = GoogleClient()
files = g.list_files_in_folder('17FF7IanYzbgfLrIwXIjKwNlqRSkefS9i')
for f in files:
    print(f['id'], f['name'])
"
```

- [ ] **Step 2: Create rename script**

Create a temporary Python script to rename all files:

```python
# temp_rename_music.py
from clients.google_client import GoogleClient

FOLDER_ID = '17FF7IanYzbgfLrIwXIjKwNlqRSkefS9i'

# Mapping: old name (case-insensitive partial match) -> new name
RENAME_MAP = {
    'dark horizon 1': 'tension_dark_horizon_1.mp3',
    'dark horizon 2': 'tension_dark_horizon_2.mp3',
    'pressure point 1': 'tension_pressure_point_1.mp3',
    'pressure point 2': 'tension_pressure_point_2.mp3',
    'silent escalation 1': 'tension_silent_escalation_1.mp3',
    'silent escalation 2': 'tension_silent_escalation_2.mp3',
    'power calculation 1': 'strategic_power_calculation_1.mp3',
    'power calculation 2': 'strategic_power_calculation_2.mp3',
    'grand chessboard 1': 'strategic_grand_chessboard_1.mp3',
    'grand chessboard 2': 'strategic_grand_chessboard_2.mp3',
    'hidden architecture 1': 'strategic_hidden_architecture_1.mp3',
    'hidden architecture 2': 'strategic_hidden_architecture_2.mp3',
    'unveiling 1': 'revelation_the_unveiling_1.mp3',
    'unveiling 2': 'revelation_the_unveiling_2.mp3',
    'your money your life 1': 'revelation_your_money_your_life_1.mp3',
    'your money your life 2': 'revelation_your_money_your_life_2.mp3',
    'empire fractures 1': 'revelation_empire_fractures_1.mp3',
    'empire fractures 2': 'revelation_empire_fractures_2.mp3',
}

def find_new_name(old_name: str) -> str | None:
    old_lower = old_name.lower()
    for pattern, new_name in RENAME_MAP.items():
        if pattern in old_lower:
            return new_name
    return None

def main():
    g = GoogleClient()
    files = g.list_files_in_folder(FOLDER_ID)

    for f in files:
        new_name = find_new_name(f['name'])
        if new_name and new_name != f['name']:
            print(f"Renaming: {f['name']} -> {new_name}")
            g.drive_service.files().update(
                fileId=f['id'],
                body={'name': new_name}
            ).execute()
        elif new_name == f['name']:
            print(f"Already correct: {f['name']}")
        else:
            print(f"WARNING: No mapping found for: {f['name']}")

if __name__ == '__main__':
    main()
```

- [ ] **Step 3: Run rename script**

```bash
cd skills/video-pipeline && python temp_rename_music.py
```

- [ ] **Step 4: Verify all 18 files renamed**

```bash
cd skills/video-pipeline && python -c "
from clients.google_client import GoogleClient
g = GoogleClient()
files = g.list_files_in_folder('17FF7IanYzbgfLrIwXIjKwNlqRSkefS9i')
files.sort(key=lambda x: x['name'])
for f in files:
    print(f['name'])
print(f'Total: {len(files)} files')
"
```

Expected output (18 files):
```
revelation_empire_fractures_1.mp3
revelation_empire_fractures_2.mp3
revelation_the_unveiling_1.mp3
revelation_the_unveiling_2.mp3
revelation_your_money_your_life_1.mp3
revelation_your_money_your_life_2.mp3
strategic_grand_chessboard_1.mp3
strategic_grand_chessboard_2.mp3
strategic_hidden_architecture_1.mp3
strategic_hidden_architecture_2.mp3
strategic_power_calculation_1.mp3
strategic_power_calculation_2.mp3
tension_dark_horizon_1.mp3
tension_dark_horizon_2.mp3
tension_pressure_point_1.mp3
tension_pressure_point_2.mp3
tension_silent_escalation_1.mp3
tension_silent_escalation_2.mp3
Total: 18 files
```

- [ ] **Step 5: Clean up temp script**

```bash
rm skills/video-pipeline/temp_rename_music.py
```

---

## Task 1: Create music_selector.py

**Files:**
- Create: `skills/video-pipeline/bots/music_selector.py`
- Test: `skills/video-pipeline/tests/test_music_selector.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_music_selector.py
"""Tests for music_selector module."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestClassifyActMood:
    """Tests for act mood classification."""

    @pytest.mark.asyncio
    async def test_classify_act_mood_returns_valid_mood(self):
        """Should return one of: tension, strategic, revelation."""
        from bots.music_selector import classify_act_mood

        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(return_value='tension')

        result = await classify_act_mood(
            mock_client,
            act_number=1,
            act_text="The missiles launched at dawn..."
        )

        assert result in ['tension', 'strategic', 'revelation']

    @pytest.mark.asyncio
    async def test_classify_act_mood_normalizes_response(self):
        """Should normalize irregular Claude responses."""
        from bots.music_selector import classify_act_mood

        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(return_value='  TENSION  ')

        result = await classify_act_mood(mock_client, 1, "text")

        assert result == 'tension'


class TestSelectTrackForMood:
    """Tests for track selection."""

    def test_select_track_for_mood_returns_matching_track(self):
        """Should return a track starting with the mood prefix."""
        from bots.music_selector import select_track_for_mood

        available_tracks = [
            {'name': 'tension_dark_horizon_1.mp3', 'id': 'abc'},
            {'name': 'tension_dark_horizon_2.mp3', 'id': 'def'},
            {'name': 'strategic_power_calc_1.mp3', 'id': 'ghi'},
        ]

        result = select_track_for_mood('tension', available_tracks)

        assert result['name'].startswith('tension_')

    def test_select_track_for_mood_returns_none_if_no_match(self):
        """Should return None if no track matches mood."""
        from bots.music_selector import select_track_for_mood

        available_tracks = [
            {'name': 'strategic_power_calc_1.mp3', 'id': 'ghi'},
        ]

        result = select_track_for_mood('revelation', available_tracks)

        assert result is None


class TestSelectMusicForScript:
    """Integration tests for the full selection flow."""

    @pytest.mark.asyncio
    async def test_select_music_for_script_returns_music_beds(self):
        """Should return music_beds array with one entry per act."""
        from bots.music_selector import select_music_for_script

        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(side_effect=[
            'tension', 'strategic', 'revelation'
        ])

        script_acts = {
            1: "Act 1 text about crisis...",
            2: "Act 2 text about strategy...",
            3: "Act 3 text about revelation...",
        }

        mock_tracks = [
            {'name': 'tension_dark_horizon_1.mp3', 'id': 'a'},
            {'name': 'strategic_power_calc_1.mp3', 'id': 'b'},
            {'name': 'revelation_unveiling_1.mp3', 'id': 'c'},
        ]

        with patch('bots.music_selector._list_music_tracks', return_value=mock_tracks):
            result = await select_music_for_script(mock_client, script_acts)

        assert len(result) == 3
        assert result[0]['act'] == 1
        assert result[0]['mood'] == 'tension'
        assert 'file' in result[0]
        assert result[0]['volume'] == 0.08
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd skills/video-pipeline && python -m pytest tests/test_music_selector.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'bots.music_selector'"

- [ ] **Step 3: Write music_selector.py implementation**

```python
# bots/music_selector.py
"""Music selection for per-act background music beds.

Classifies each act's mood using Claude Haiku, then selects a random
track from the matching mood category in the Google Drive music library.
"""

import random
from typing import Optional

from pipeline_constants import Models

# Music library folder in Google Drive
MUSIC_FOLDER_ID = '17FF7IanYzbgfLrIwXIjKwNlqRSkefS9i'

# Valid moods and their keywords (for fallback classification)
MOOD_KEYWORDS = {
    'tension': ['crisis', 'conflict', 'danger', 'threat', 'war', 'sanctions',
                'military', 'attack', 'strike', 'missiles', 'nuclear', 'invasion'],
    'strategic': ['analysis', 'power', 'calculated', 'geopolitical', 'chess',
                  'trade', 'alliance', 'operation', 'strategy', 'move', 'position'],
    'revelation': ['personal', 'hidden', 'exposed', 'financial', 'consequences',
                   'stakes', 'collapse', 'systemic', 'failure', 'truth', 'secret'],
}

CLASSIFICATION_SYSTEM_PROMPT = """You are a music director for a geopolitical documentary channel. Given script acts, classify each act's dominant mood as exactly one of: tension, strategic, revelation.

- tension: crisis, conflict, danger, threat, war, sanctions, military action
- strategic: analysis, power moves, calculated decisions, geopolitical chess, trade, alliances, operations
- revelation: personal impact, hidden truth exposed, financial consequences, stakes hitting the viewer, collapse, systemic failure

Output ONLY the single word mood classification (tension, strategic, or revelation). No explanation."""


async def classify_act_mood(
    anthropic_client,
    act_number: int,
    act_text: str,
) -> str:
    """Classify an act's dominant mood using Claude Haiku.

    Args:
        anthropic_client: AnthropicClient instance
        act_number: The act number (1-6)
        act_text: The narration text for this act

    Returns:
        One of: 'tension', 'strategic', 'revelation'
    """
    # Truncate to first 500 words to save tokens
    words = act_text.split()[:500]
    truncated_text = ' '.join(words)

    prompt = f"Classify the dominant mood of this script act:\n\nACT {act_number}:\n{truncated_text}"

    try:
        response = await anthropic_client.generate(
            prompt=prompt,
            system_prompt=CLASSIFICATION_SYSTEM_PROMPT,
            model=Models.CLAUDE_HAIKU,
            max_tokens=10,
            temperature=0.0,
        )

        mood = response.strip().lower()

        # Validate response
        if mood in ['tension', 'strategic', 'revelation']:
            return mood

        # Fallback: keyword matching
        return _classify_by_keywords(act_text)

    except Exception as e:
        print(f"  Warning: Mood classification failed for Act {act_number}: {e}")
        return _classify_by_keywords(act_text)


def _classify_by_keywords(text: str) -> str:
    """Fallback mood classification using keyword matching."""
    text_lower = text.lower()
    scores = {'tension': 0, 'strategic': 0, 'revelation': 0}

    for mood, keywords in MOOD_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                scores[mood] += 1

    # Return highest scoring mood, default to 'strategic' if tie
    max_score = max(scores.values())
    if max_score == 0:
        return 'strategic'

    for mood in ['tension', 'strategic', 'revelation']:
        if scores[mood] == max_score:
            return mood

    return 'strategic'


def select_track_for_mood(
    mood: str,
    available_tracks: list[dict],
) -> Optional[dict]:
    """Select a random track matching the mood.

    Args:
        mood: One of 'tension', 'strategic', 'revelation'
        available_tracks: List of track dicts with 'name' and 'id'

    Returns:
        Selected track dict, or None if no match
    """
    matching = [t for t in available_tracks if t['name'].startswith(f"{mood}_")]

    if not matching:
        return None

    return random.choice(matching)


def _list_music_tracks() -> list[dict]:
    """List all tracks in the music library folder."""
    from clients.google_client import GoogleClient

    google = GoogleClient()
    files = google.list_files_in_folder(MUSIC_FOLDER_ID)

    # Filter to mp3 files only
    return [f for f in files if f['name'].endswith('.mp3')]


async def select_music_for_script(
    anthropic_client,
    script_acts: dict[int, str],
) -> list[dict]:
    """Select background music for each act in a script.

    Args:
        anthropic_client: AnthropicClient instance
        script_acts: Dict mapping act number to act text

    Returns:
        List of music_bed entries:
        [
            {
                "act": 1,
                "file": "music/tension_dark_horizon_1.mp3",
                "file_id": "abc123",
                "mood": "tension",
                "volume": 0.08
            },
            ...
        ]
    """
    # Get available tracks
    available_tracks = _list_music_tracks()
    print(f"  Found {len(available_tracks)} music tracks in Drive")

    music_beds = []

    for act_num in sorted(script_acts.keys()):
        act_text = script_acts[act_num]

        # Classify mood
        mood = await classify_act_mood(anthropic_client, act_num, act_text)
        print(f"  Act {act_num}: mood = {mood}")

        # Select track
        track = select_track_for_mood(mood, available_tracks)

        if track:
            music_beds.append({
                'act': act_num,
                'file': f"music/{track['name']}",
                'file_id': track['id'],
                'mood': mood,
                'volume': 0.08,
            })
        else:
            print(f"  Warning: No track found for mood '{mood}' in Act {act_num}")

    return music_beds
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd skills/video-pipeline && python -m pytest tests/test_music_selector.py -v
```

Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add skills/video-pipeline/bots/music_selector.py skills/video-pipeline/tests/test_music_selector.py
git commit -m "feat: Add music_selector.py for per-act mood classification"
```

---

## Task 2: Add MusicBed TypeScript interface to renderConfig.ts

**Files:**
- Modify: `remotion-video/src/renderConfig.ts`

- [ ] **Step 1: Add MusicBed interface**

Add after the `RenderConfig` interface (around line 47):

```typescript
export interface MusicBed {
    act: number;
    file: string;
    mood: string;
    volume: number;
}
```

- [ ] **Step 2: Update RenderConfig interface**

Add `music_beds?: MusicBed[];` to the `RenderConfig` interface:

```typescript
export interface RenderConfig {
    video_id: string;
    audio_path: string;
    total_duration_seconds: number;
    fps: number;
    resolution: {
        width: number;
        height: number;
    };
    scenes: RenderScene[];
    music_beds?: MusicBed[];
}
```

- [ ] **Step 3: Add getMusicBeds function**

Add at the end of the file:

```typescript
/**
 * Get music beds from render config.
 * Returns empty array if unavailable.
 */
export function getMusicBeds(): MusicBed[] {
    const config = loadRenderConfig();
    if (!config || !config.music_beds) return [];
    return config.music_beds;
}

/**
 * Get act boundaries in frames from render config.
 * Returns array of { act, startFrame, endFrame } for each act.
 */
export function getActBoundaries(fps: number): Array<{ act: number; startFrame: number; endFrame: number }> {
    const config = loadRenderConfig();
    if (!config || !config.scenes || config.scenes.length === 0) return [];

    const actMap = new Map<number, { start: number; end: number }>();

    for (const scene of config.scenes) {
        const act = scene.act || 0;
        if (act === 0) continue;

        const existing = actMap.get(act);
        if (existing) {
            existing.start = Math.min(existing.start, scene.display_start);
            existing.end = Math.max(existing.end, scene.display_end);
        } else {
            actMap.set(act, { start: scene.display_start, end: scene.display_end });
        }
    }

    const result: Array<{ act: number; startFrame: number; endFrame: number }> = [];
    for (const [act, bounds] of Array.from(actMap.entries()).sort((a, b) => a[0] - b[0])) {
        result.push({
            act,
            startFrame: Math.floor(bounds.start * fps),
            endFrame: Math.floor(bounds.end * fps),
        });
    }

    return result;
}
```

- [ ] **Step 4: Run TypeScript check**

```bash
cd remotion-video && npm run typecheck
```

Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add remotion-video/src/renderConfig.ts
git commit -m "feat: Add MusicBed interface and act boundary helpers"
```

---

## Task 3: Create MusicBed.tsx component

**Files:**
- Create: `remotion-video/src/components/MusicBed.tsx`

- [ ] **Step 1: Create components directory if needed**

```bash
mkdir -p remotion-video/src/components
```

- [ ] **Step 2: Write MusicBed.tsx**

```typescript
// MusicBed.tsx
/**
 * Background music bed component that spans the full video.
 *
 * Features:
 * - Per-act music tracks (one track per act)
 * - Automatic looping (tracks are ~1:33, acts are 2-3 min)
 * - Crossfade between acts (3 second overlap)
 * - Fade in at video start (2 seconds)
 * - Fade out at video end (3 seconds)
 * - Configurable volume (default 8%)
 */

import React, { useMemo } from 'react';
import { Audio } from '@remotion/media';
import { staticFile, useCurrentFrame, useVideoConfig, interpolate } from 'remotion';
import { getMusicBeds, getActBoundaries, MusicBed as MusicBedType } from '../renderConfig';

interface ActMusicProps {
    bed: MusicBedType;
    actStart: number;      // Start frame of this act
    actEnd: number;        // End frame of this act
    isFirstAct: boolean;
    isLastAct: boolean;
    totalDuration: number; // Total video duration in frames
}

const CROSSFADE_FRAMES = 90;  // 3 seconds at 30fps
const FADE_IN_FRAMES = 60;    // 2 seconds at 30fps
const FADE_OUT_FRAMES = 90;   // 3 seconds at 30fps

/**
 * Single act's music track with looping and volume control.
 */
const ActMusic: React.FC<ActMusicProps> = ({
    bed,
    actStart,
    actEnd,
    isFirstAct,
    isLastAct,
    totalDuration,
}) => {
    const frame = useCurrentFrame();
    const { fps } = useVideoConfig();

    // Calculate volume based on position
    const getVolume = useMemo(() => {
        return (currentFrame: number) => {
            const baseVolume = bed.volume;

            // Calculate frame relative to video start (not act start)
            const videoFrame = currentFrame;

            // First act: fade in from 0 over first 2 seconds of VIDEO
            if (isFirstAct && videoFrame < FADE_IN_FRAMES) {
                return interpolate(
                    videoFrame,
                    [0, FADE_IN_FRAMES],
                    [0, baseVolume],
                    { extrapolateRight: 'clamp' }
                );
            }

            // Last act: fade out over last 3 seconds of VIDEO
            if (isLastAct && videoFrame > totalDuration - FADE_OUT_FRAMES) {
                return interpolate(
                    videoFrame,
                    [totalDuration - FADE_OUT_FRAMES, totalDuration],
                    [baseVolume, 0],
                    { extrapolateLeft: 'clamp' }
                );
            }

            // Crossfade at act boundaries (non-first/last)
            // At the END of this act: fade out over 3 seconds
            if (!isLastAct && videoFrame > actEnd - CROSSFADE_FRAMES) {
                return interpolate(
                    videoFrame,
                    [actEnd - CROSSFADE_FRAMES, actEnd],
                    [baseVolume, 0],
                    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
                );
            }

            // At the START of this act (non-first): fade in over 3 seconds
            if (!isFirstAct && videoFrame < actStart + CROSSFADE_FRAMES) {
                return interpolate(
                    videoFrame,
                    [actStart, actStart + CROSSFADE_FRAMES],
                    [0, baseVolume],
                    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
                );
            }

            return baseVolume;
        };
    }, [bed.volume, isFirstAct, isLastAct, actStart, actEnd, totalDuration]);

    return (
        <Audio
            src={staticFile(bed.file)}
            volume={getVolume}
            loop
        />
    );
};

/**
 * Full video music bed manager.
 * Renders nothing if no music_beds in render config (backward compatible).
 */
export const MusicBed: React.FC = () => {
    const { fps, durationInFrames } = useVideoConfig();

    const musicBeds = useMemo(() => getMusicBeds(), []);
    const actBoundaries = useMemo(() => getActBoundaries(fps), [fps]);

    // If no music beds, render nothing (backward compatible)
    if (musicBeds.length === 0) {
        return null;
    }

    // Map music beds to act boundaries
    const actsWithMusic = useMemo(() => {
        return musicBeds.map((bed, index) => {
            const boundary = actBoundaries.find(b => b.act === bed.act);
            if (!boundary) return null;

            return {
                bed,
                actStart: boundary.startFrame,
                actEnd: boundary.endFrame,
                isFirstAct: index === 0,
                isLastAct: index === musicBeds.length - 1,
            };
        }).filter(Boolean) as Array<{
            bed: MusicBedType;
            actStart: number;
            actEnd: number;
            isFirstAct: boolean;
            isLastAct: boolean;
        }>;
    }, [musicBeds, actBoundaries]);

    return (
        <>
            {actsWithMusic.map(({ bed, actStart, actEnd, isFirstAct, isLastAct }) => (
                <ActMusic
                    key={bed.act}
                    bed={bed}
                    actStart={actStart}
                    actEnd={actEnd}
                    isFirstAct={isFirstAct}
                    isLastAct={isLastAct}
                    totalDuration={durationInFrames}
                />
            ))}
        </>
    );
};
```

- [ ] **Step 3: Run TypeScript check**

```bash
cd remotion-video && npm run typecheck
```

Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add remotion-video/src/components/MusicBed.tsx
git commit -m "feat: Add MusicBed component with looping and crossfades"
```

---

## Task 4: Integrate MusicBed into Main.tsx

**Files:**
- Modify: `remotion-video/src/Main.tsx:1-10` (imports)
- Modify: `remotion-video/src/Main.tsx:140-158` (render)

- [ ] **Step 1: Add import**

Add after the existing imports (around line 6):

```typescript
import { MusicBed } from "./components/MusicBed";
```

- [ ] **Step 2: Add MusicBed to render**

Replace the return statement (starting around line 140):

```typescript
    return (
        <AbsoluteFill style={{ backgroundColor: "#000" }}>
            {/* Background music bed - spans full video, manages its own timing */}
            <MusicBed />

            {scenesWithTiming.map((scene) => (
                <Sequence
                    key={scene.sceneNumber}
                    from={scene.startFrame}
                    durationInFrames={scene.durationFrames}
                >
                    <Scene
                        sceneNumber={scene.sceneNumber}
                        audioFile={scene.audioFile}
                        images={scene.images}
                        transcript={scene.transcript}
                    />
                </Sequence>
            ))}
        </AbsoluteFill>
    );
```

- [ ] **Step 3: Run TypeScript check**

```bash
cd remotion-video && npm run typecheck
```

Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add remotion-video/src/Main.tsx
git commit -m "feat: Integrate MusicBed component into Main.tsx"
```

---

## Task 5: Update render_video.py with music selection

**Files:**
- Modify: `skills/video-pipeline/render_video.py`

- [ ] **Step 1: Add imports**

Add after existing imports (around line 27):

```python
from bots.music_selector import select_music_for_script
from brief_translator.script_generator import extract_acts
from clients.anthropic_client import AnthropicClient
```

- [ ] **Step 2: Add music directory creation**

After `sfx_dir.mkdir(...)` (around line 239), add:

```python
    # Ensure music directory exists
    music_dir = remotion_dir / "public" / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 3: Add music selection function**

Add before `main()` function:

```python
async def _select_and_download_music(
    title: str,
    scripts: list[dict],
    music_dir: Path,
    google: GoogleClient,
    dry_run: bool = False,
) -> list[dict]:
    """Select music for each act and download tracks.

    Args:
        title: Video title
        scripts: List of script records from Airtable
        music_dir: Local directory to download tracks to
        google: GoogleClient instance
        dry_run: If True, skip downloads

    Returns:
        music_beds array for render_config.json
    """
    from bots.music_selector import select_music_for_script, MUSIC_FOLDER_ID
    from brief_translator.script_generator import extract_acts
    from clients.anthropic_client import AnthropicClient

    # Reassemble full script from Airtable records
    full_script = ""
    for script in sorted(scripts, key=lambda s: s.get("scene", 0)):
        scene_text = script.get("Scene text", "")
        scene_num = script.get("scene", 0)
        # Add act markers if present in the scene text
        full_script += f"\n\n[ACT {scene_num}]\n{scene_text}"

    # Extract acts from script
    acts = extract_acts(full_script)
    if not acts:
        print("  Warning: Could not extract acts from script, skipping music")
        return []

    print(f"  Extracted {len(acts)} acts from script")

    # Select music for each act
    anthropic = AnthropicClient()
    music_beds = []

    import asyncio
    music_beds = asyncio.get_event_loop().run_until_complete(
        select_music_for_script(anthropic, acts)
    )

    if not music_beds:
        print("  Warning: No music selected, skipping")
        return []

    print(f"  Selected {len(music_beds)} music tracks")

    # Download tracks (skip if already exist)
    for bed in music_beds:
        local_path = music_dir / Path(bed['file']).name

        if local_path.exists():
            print(f"  Music cached: {local_path.name}")
            continue

        if dry_run:
            print(f"  [DRY RUN] Would download: {bed['file']}")
            continue

        try:
            google.download_file_to_local(bed['file_id'], str(local_path))
            print(f"  Downloaded: {local_path.name}")
        except Exception as e:
            print(f"  Warning: Failed to download {bed['file']}: {e}")

    # Remove file_id from output (not needed in render_config)
    return [
        {
            'act': b['act'],
            'file': b['file'],
            'mood': b['mood'],
            'volume': b['volume'],
        }
        for b in music_beds
    ]
```

- [ ] **Step 4: Call music selection in main()**

After the render_config loading section (around line 375, before "Video clip downloads"), add:

```python
    # ── Music selection and download ──────────────────────────────────
    print("\n🎵 Selecting background music...")
    import asyncio

    try:
        music_beds = asyncio.get_event_loop().run_until_complete(
            _select_and_download_music(
                title=title,
                scripts=scripts,
                music_dir=remotion_dir / "public" / "music",
                google=google,
                dry_run=dry_run,
            )
        )
    except Exception as e:
        print(f"  Warning: Music selection failed: {e}")
        music_beds = []

    # Add music_beds to render_config
    if music_beds and rc_data:
        rc_data['music_beds'] = music_beds
        print(f"  Added {len(music_beds)} music beds to render_config")
```

- [ ] **Step 5: Write updated render_config with music_beds**

Ensure the `rc_data` with `music_beds` is written before the render call. The existing code at line 500-502 already handles this:

```python
            # Write updated render_config back to disk
            if not dry_run:
                with open(rc_path, "w") as f:
                    json.dump(rc_data, f, indent=2)
```

- [ ] **Step 6: Run linting**

```bash
cd skills/video-pipeline && python -m ruff check render_video.py
```

- [ ] **Step 7: Commit**

```bash
git add skills/video-pipeline/render_video.py
git commit -m "feat: Add music selection step to render_video.py"
```

---

## Task 6: Add music directory to gitignore

**Files:**
- Modify: `remotion-video/.gitignore`

- [ ] **Step 1: Check existing gitignore**

```bash
cat remotion-video/.gitignore
```

- [ ] **Step 2: Add music directory**

Add to the end of `.gitignore`:

```
# Downloaded music tracks (cached from Google Drive)
public/music/
```

- [ ] **Step 3: Commit**

```bash
git add remotion-video/.gitignore
git commit -m "chore: Ignore downloaded music tracks"
```

---

## Task 7: Integration Test

**Files:**
- None (manual testing)

- [ ] **Step 1: Run render with dry-run**

```bash
cd skills/video-pipeline && python render_video.py "Test Video Title" --dry-run
```

Verify:
- Music selection step runs
- Acts are extracted from script
- Moods are classified
- Tracks are selected
- `music_beds` array appears in render_config.json

- [ ] **Step 2: Check render_config.json**

```bash
cat remotion-video/public/render_config.json | jq '.music_beds'
```

Expected output:
```json
[
  {
    "act": 1,
    "file": "music/tension_dark_horizon_1.mp3",
    "mood": "tension",
    "volume": 0.08
  },
  ...
]
```

- [ ] **Step 3: Test in Remotion Studio**

```bash
cd remotion-video && npm run studio
```

Verify:
- No TypeScript errors
- Video plays without errors
- If music_beds exists, audio should be audible

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "Add per-act background music bed — Drive cleanup, mood classification, Remotion crossfade

- Clean up music library naming in Google Drive (18 files)
- Add music_selector.py with Claude Haiku mood classification
- Add MusicBed.tsx component with looping and 3s crossfades
- Integrate music selection into render_video.py pipeline
- Add music_beds to render_config.json schema"
```

---

## Verification Checklist

Before marking complete:

- [ ] All 18 music files in Drive renamed to `{mood}_{track_name}_{variant}.mp3`
- [ ] `music_selector.py` tests pass
- [ ] TypeScript compiles without errors (`npm run typecheck`)
- [ ] `render_video.py --dry-run` shows music selection step
- [ ] `render_config.json` contains `music_beds` array
- [ ] Remotion Studio plays without errors
- [ ] Backward compatible: videos without `music_beds` render normally
