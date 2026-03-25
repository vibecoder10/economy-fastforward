# Module 3: Interactive Features — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the video detail page from read-only to fully interactive — script editing, voice generation, storyboard review, image generation, and pipeline advancement.

**Architecture:** Backend-first (new endpoints + migration), then shared frontend components (hooks, reusable UI), then tab rewrites (Script, Visuals), then consolidation (6→5 tabs). Each task produces a working, typecheck-passing commit.

**Tech Stack:** FastAPI + asyncpg (backend), React + TypeScript + React Query + Framer Motion + Lucide icons (frontend). Dark editorial design system with CSS variables.

**Spec:** `docs/superpowers/specs/2026-03-24-module3-interactive-features-design.md`

---

## File Map

### Backend — New/Modified

| File | Action | Responsibility |
|------|--------|---------------|
| `storyengine/backend/migrations/007_tone_column.sql` | Create | Add `tone` column to scripts table |
| `storyengine/backend/routes/videos.py` | Modify | Add scene text/tone/segments/storyboard-mode endpoints |
| `storyengine/backend/routes/pipeline.py` | Modify | Add `?scene=` query param to voice + images endpoints |
| `storyengine/backend/models.py` | Modify | Add `SceneUpdate`, `SegmentUpdate` request models |

### Frontend — New Components

| File | Responsibility |
|------|---------------|
| `storyengine/frontend/src/hooks/use-task-poller.ts` | Poll background task status, return state + retry |
| `storyengine/frontend/src/components/video-detail/prompt-expander.tsx` | Collapsible prompt viewer/editor |
| `storyengine/frontend/src/components/video-detail/voice-player.tsx` | Mini audio player (play/pause, progress, redo) |
| `storyengine/frontend/src/components/video-detail/stage-advancer.tsx` | Per-tab advancement button with polling indicator |
| `storyengine/frontend/src/components/video-detail/scene-editor.tsx` | Editable scene card (text, tone, regen, voice, segments) |
| `storyengine/frontend/src/components/video-detail/segment-list.tsx` | Collapsible sentence segment list with split handles |
| `storyengine/frontend/src/components/video-detail/panel-magnifier.tsx` | CSS crop/zoom of storyboard grid panel (no extraction) |
| `storyengine/frontend/src/components/video-detail/storyboard-viewer.tsx` | Grids side-by-side with VO + magnified panel viewer |
| `storyengine/frontend/src/components/video-detail/image-segment-card.tsx` | Per-segment image card (storyboard OFF path) |

### Frontend — Modified

| File | Changes |
|------|---------|
| `storyengine/frontend/src/lib/api.ts` | Add ~12 new API functions + types |
| `storyengine/frontend/src/components/video-detail/script-tab.tsx` | Replace read-only list with SceneEditor cards |
| `storyengine/frontend/src/components/video-detail/visuals-tab.tsx` | Full rewrite: storyboard toggle, ON/OFF paths |
| `storyengine/frontend/src/components/video-detail/thumbnail-tab.tsx` | Add StageAdvancer |
| `storyengine/frontend/src/app/pipeline/[videoId]/page.tsx` | Remove Board tab, pass video status to tabs |

### Frontend — Deleted

| File | Reason |
|------|--------|
| `storyengine/frontend/src/components/video-detail/storyboard-tab.tsx` | Merged into visuals-tab.tsx |

---

## Task 1: Database Migration — `tone` Column

**Files:**
- Create: `storyengine/backend/migrations/007_tone_column.sql`

- [ ] **Step 1: Write migration**

```sql
-- 007_tone_column.sql
-- Add tone column for per-scene tone control (Module 3: Interactive Features)
ALTER TABLE scripts ADD COLUMN IF NOT EXISTS tone TEXT DEFAULT 'serious';
```

- [ ] **Step 2: Apply migration to Supabase**

Run in Supabase SQL Editor or via:
```bash
cd storyengine/backend
cat migrations/007_tone_column.sql
# Copy and execute in Supabase dashboard → SQL Editor
```
Expected: Column added successfully.

- [ ] **Step 3: Commit**

```bash
git add storyengine/backend/migrations/007_tone_column.sql
git commit -m "feat(storyengine): Add migration 007 — tone column on scripts"
```

---

## Task 2: Backend — Scene Edit Endpoints

**Files:**
- Modify: `storyengine/backend/routes/videos.py`
- Modify: `storyengine/backend/models.py`

**Reference docs:**
- `storyengine/backend/database.py` — `fetch_all`, `fetch_one`, `execute` pattern
- `storyengine/backend/auth.py` — `get_tenant_id` dependency

- [ ] **Step 1: Add request models to models.py**

After the existing `BatchApproval` class, add:

```python
class SceneTextUpdate(BaseModel):
    text: str

class SceneToneUpdate(BaseModel):
    tone: str  # serious | conversational | urgent | concise

class SegmentUpdate(BaseModel):
    segments: list[dict]  # [{image_index: int, sentence_text: str}, ...]

class StoryboardModeUpdate(BaseModel):
    enabled: bool
```

- [ ] **Step 2: Expand get_video_script query to include storyboard + tone columns**

In `videos.py`, find `get_video_script` (~line 213). Update the SELECT to include the missing columns:

```python
@router.get("/{video_id}/script")
async def get_video_script(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Get full script for a video."""
    rows = await fetch_all(
        """SELECT id, video_id, scene, scene_text, voice_over_url, voice_status,
                  script_status, sources, storyboard_on_off, tone,
                  storyboard_1_url, storyboard_2_url, storyboard_3_url,
                  storyboard_prompts, storyboard_beat_count, storyboard_status,
                  created_at::text
           FROM scripts WHERE video_id = $1 AND tenant_id = $2
           ORDER BY scene""",
        video_id, tenant_id,
    )
    return rows
```

- [ ] **Step 3: Add scene endpoints to videos.py**

Add these endpoints after the existing `reject_suggestion` endpoint. **IMPORTANT:** Use `tenant_id: str = Depends(get_tenant_id)` to match the existing auth pattern in this file (NOT `verify_token`).

**PATCH scene text:**
```python
@router.patch("/{video_id}/scenes/{scene}/text")
async def update_scene_text(
    video_id: str, scene: int, body: SceneTextUpdate, tenant_id: str = Depends(get_tenant_id)
):
    result = await execute(
        "UPDATE scripts SET scene_text = $1, updated_at = now() "
        "WHERE video_id = $2 AND scene = $3 AND tenant_id = $4",
        body.text, video_id, scene, tenant_id,
    )
    if not result or "UPDATE 0" in result:
        raise HTTPException(404, "Scene not found")
    return {"status": "updated", "scene": scene}
```

**PATCH scene tone:**
```python
@router.patch("/api/videos/{video_id}/scenes/{scene}/tone")
async def update_scene_tone(
    video_id: str, scene: int, body: SceneToneUpdate, tenant_id: str = Depends(get_tenant_id)
):
    valid_tones = {"serious", "conversational", "urgent", "concise"}
    if body.tone not in valid_tones:
        raise HTTPException(400, f"Invalid tone. Must be one of: {valid_tones}")
    await execute(
        "UPDATE scripts SET tone = $1, updated_at = now() "
        "WHERE video_id = $2 AND scene = $3 AND tenant_id = $4",
        body.tone, video_id, scene, tenant_id,
    )
    return {"status": "updated", "scene": scene, "tone": body.tone}
```

**GET segments (computed from assets):**
```python
@router.get("/api/videos/{video_id}/scenes/{scene}/segments")
async def get_scene_segments(
    video_id: str, scene: int, tenant_id: str = Depends(get_tenant_id)
):
    rows = await fetch_all(
        "SELECT id, image_index, sentence_text, shot_type, status "
        "FROM assets WHERE video_id = $1 AND scene = $2 AND tenant_id = $3 "
        "ORDER BY image_index",
        video_id, scene, tenant_id,
    )
    segments = []
    for row in rows:
        text = row.get("sentence_text") or ""
        word_count = len(text.split()) if text else 0
        segments.append({
            "id": row["id"],
            "image_index": row.get("image_index"),
            "sentence_text": text,
            "shot_type": row.get("shot_type"),
            "status": row.get("status"),
            "word_count": word_count,
            "duration_seconds": round(word_count / 2.5, 1),
        })
    return {"scene": scene, "segments": segments}
```

**PUT segments (update split points):**
```python
@router.put("/api/videos/{video_id}/scenes/{scene}/segments")
async def update_scene_segments(
    video_id: str, scene: int, body: SegmentUpdate, tenant_id: str = Depends(get_tenant_id)
):
    updated = 0
    for seg in body.segments:
        result = await execute(
            "UPDATE assets SET sentence_text = $1, updated_at = now() "
            "WHERE video_id = $2 AND scene = $3 AND image_index = $4 AND tenant_id = $5",
            seg["sentence_text"], video_id, scene, seg["image_index"], tenant_id,
        )
        if result and "UPDATE 1" in result:
            updated += 1
    return {"status": "updated", "scene": scene, "updated_count": updated}
```

**PATCH storyboard mode (bulk toggle):**
```python
@router.patch("/api/videos/{video_id}/storyboard-mode")
async def update_storyboard_mode(
    video_id: str, body: StoryboardModeUpdate, tenant_id: str = Depends(get_tenant_id)
):
    value = "On" if body.enabled else "Off"
    await execute(
        "UPDATE scripts SET storyboard_on_off = $1, updated_at = now() "
        "WHERE video_id = $2 AND tenant_id = $3",
        value, video_id, tenant_id,
    )
    return {"status": "updated", "storyboard_mode": value}
```

- [ ] **Step 4: Add imports to videos.py**

Add `SceneTextUpdate, SceneToneUpdate, SegmentUpdate, StoryboardModeUpdate` to the models import at the top of videos.py. Note: `get_tenant_id` is already imported — verify it's there.

- [ ] **Step 5: Verify backend starts**

```bash
cd storyengine/backend && python -c "from routes.videos import router; print('OK')"
```

- [ ] **Step 6: Commit**

```bash
git add storyengine/backend/routes/videos.py storyengine/backend/models.py
git commit -m "feat(storyengine): Add scene edit, segment, storyboard-mode endpoints + expand script query"
```

---

## Task 3: Backend — Targeted Pipeline Endpoints (Status Gate Bypass)

**Files:**
- Modify: `storyengine/backend/routes/pipeline.py`

**Key context:** The existing `run_voice` and `run_images` endpoints check `video["status"]` before allowing execution. We add optional `?scene=` and `?index=` query params. When present, these bypass the status gate (edit-in-place operations).

- [ ] **Step 1: Modify voice endpoint to accept scene query param**

In `pipeline.py`, find the `run_voice` function. Add `scene: Optional[int] = None` as a query parameter. When `scene` is set, skip the status check:

```python
@router.post("/voice/{video_id}")
async def run_voice(
    video_id: str,
    background_tasks: BackgroundTasks,
    scene: Optional[int] = None,  # NEW: targeted single-scene regen
    tenant_id: str = Depends(get_tenant_id),
):
    video = await fetch_one(
        "SELECT id, status, video_title FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(404, "Video not found")

    # Only enforce status gate for full pipeline runs (no scene param)
    if scene is None and video["status"] != "ready_for_voice":
        raise HTTPException(400, f"Video not at ready_for_voice (current: {video['status']})")

    # ... rest of function unchanged, but pass scene to executor if set
```

- [ ] **Step 2: Modify images endpoint to accept scene + index query params**

Same pattern for `run_images`:

```python
@router.post("/images/{video_id}")
async def run_images(
    video_id: str,
    background_tasks: BackgroundTasks,
    scene: Optional[int] = None,     # NEW: targeted single-scene
    index: Optional[int] = None,     # NEW: targeted single-image
    variants: Optional[int] = None,  # NEW: generate N variants
    tenant_id: str = Depends(get_tenant_id),
):
    # ... same pattern: skip status gate when scene/index are set
```

- [ ] **Step 3: Add `Optional` import if not present**

Check top of pipeline.py for `from typing import Optional`. Add if missing.

- [ ] **Step 4: Commit**

```bash
git add storyengine/backend/routes/pipeline.py
git commit -m "feat(storyengine): Add targeted voice/image regen with status gate bypass"
```

---

## Task 4: Frontend — API Functions + Types

**Files:**
- Modify: `storyengine/frontend/src/lib/api.ts`

- [ ] **Step 1: Add new API functions**

After the Niche section (~line 205), before the Types section:

```typescript
// Scene Editing
export const updateSceneText = (videoId: string, scene: number, text: string) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/scenes/${scene}/text`, {
    method: "PATCH",
    body: JSON.stringify({ text }),
  });

export const updateSceneTone = (videoId: string, scene: number, tone: string) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/scenes/${scene}/tone`, {
    method: "PATCH",
    body: JSON.stringify({ tone }),
  });

export const getSceneSegments = (videoId: string, scene: number) =>
  fetchApi<SegmentResponse>(`/api/videos/${videoId}/scenes/${scene}/segments`);

export const updateSceneSegments = (
  videoId: string, scene: number,
  segments: { image_index: number; sentence_text: string }[]
) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/scenes/${scene}/segments`, {
    method: "PUT",
    body: JSON.stringify({ segments }),
  });

export const updateStoryboardMode = (videoId: string, enabled: boolean) =>
  fetchApi<{ status: string }>(`/api/videos/${videoId}/storyboard-mode`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });

// Targeted regeneration (single scene/image, bypasses status gate)
export const runVoiceForScene = (videoId: string, scene: number) =>
  fetchApi<PipelineResponse>(`/api/pipeline/voice/${videoId}?scene=${scene}`, {
    method: "POST",
  });

export const runImageForSegment = (videoId: string, scene: number, index: number) =>
  fetchApi<PipelineResponse>(
    `/api/pipeline/images/${videoId}?scene=${scene}&index=${index}`,
    { method: "POST" }
  );

export const runImageVariants = (videoId: string, scene: number, index: number, count = 3) =>
  fetchApi<PipelineResponse>(
    `/api/pipeline/images/${videoId}?scene=${scene}&index=${index}&variants=${count}`,
    { method: "POST" }
  );
```

- [ ] **Step 2: Add `tone` to existing ScriptScene interface**

In the `ScriptScene` interface (~line 306), add after `storyboard_status`:

```typescript
  tone: string | null; // serious | conversational | urgent | concise
```

- [ ] **Step 3: Add new types**

After `ThumbnailVersion` interface (~line 507):

```typescript
export interface Segment {
  id: string;
  image_index: number;
  sentence_text: string;
  shot_type: string | null;
  status: string | null;
  word_count: number;
  duration_seconds: number;
}

export interface SegmentResponse {
  scene: number;
  segments: Segment[];
}
```

- [ ] **Step 4: Run typecheck**

```bash
cd storyengine/frontend && npx tsc --noEmit
```
Expected: Clean compile.

- [ ] **Step 5: Commit**

```bash
git add storyengine/frontend/src/lib/api.ts
git commit -m "feat(storyengine): Add API functions for scene editing, segments, storyboard mode"
```

---

## Task 5: Frontend — `useTaskPoller` Hook

**Files:**
- Create: `storyengine/frontend/src/hooks/use-task-poller.ts`

**Purpose:** Polls `GET /api/pipeline/task/{videoId}` every 3s while a task is running. Returns current status and a retry function.

- [ ] **Step 1: Create the hook**

```typescript
"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { getPipelineTaskStatus, TaskStatus } from "@/lib/api";

interface UseTaskPollerOptions {
  videoId: string;
  enabled: boolean; // Start polling when true
  interval?: number; // Default 3000ms
  onComplete?: () => void;
  onFailed?: (error: string) => void;
}

interface TaskPollerState {
  status: TaskStatus["status"] | "idle";
  message: string | null;
  error: string | null;
}

export function useTaskPoller({
  videoId,
  enabled,
  interval = 3000,
  onComplete,
  onFailed,
}: UseTaskPollerOptions) {
  const [state, setState] = useState<TaskPollerState>({
    status: "idle",
    message: null,
    error: null,
  });
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Store callbacks in refs to avoid stale closures in polling interval
  const onCompleteRef = useRef(onComplete);
  const onFailedRef = useRef(onFailed);
  onCompleteRef.current = onComplete;
  onFailedRef.current = onFailed;

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    setState({ status: "running", message: "Starting...", error: null });

    const poll = async () => {
      try {
        const task = await getPipelineTaskStatus(videoId);
        setState({
          status: task.status,
          message: task.message,
          error: task.error || null,
        });

        if (task.status === "completed") {
          stopPolling();
          onCompleteRef.current?.();
        } else if (task.status === "failed") {
          stopPolling();
          onFailedRef.current?.(task.error || "Unknown error");
        }
      } catch {
        // Network error — keep polling, don't crash
      }
    };

    poll(); // Initial check
    intervalRef.current = setInterval(poll, interval);
  }, [videoId, interval, stopPolling]);

  useEffect(() => {
    if (enabled) {
      startPolling();
    } else {
      stopPolling();
      setState({ status: "idle", message: null, error: null });
    }
    return stopPolling;
  }, [enabled, startPolling, stopPolling]);

  const reset = useCallback(() => {
    stopPolling();
    setState({ status: "idle", message: null, error: null });
  }, [stopPolling]);

  return { ...state, reset, isPolling: !!intervalRef.current };
}
```

- [ ] **Step 2: Typecheck**

```bash
cd storyengine/frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add storyengine/frontend/src/hooks/use-task-poller.ts
git commit -m "feat(storyengine): Add useTaskPoller hook for background task polling"
```

---

## Task 6: Frontend — Shared Components (PromptExpander, VoicePlayer, StageAdvancer)

**Files:**
- Create: `storyengine/frontend/src/components/video-detail/prompt-expander.tsx`
- Create: `storyengine/frontend/src/components/video-detail/voice-player.tsx`
- Create: `storyengine/frontend/src/components/video-detail/stage-advancer.tsx`

**Design tokens reference:** `--bg-card`, `--bg-card-hover`, `--border`, `--text-primary`, `--text-secondary`, `--text-muted`, `--amber` (#D4A844), teal (#1A8A7A), red (#C44545).

- [ ] **Step 1: Create PromptExpander**

Collapsible prompt viewer/editor. Collapsed shows one-line preview, expanded shows full text + optional edit mode.

```typescript
// prompt-expander.tsx
"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Pencil, Check, X } from "lucide-react";

interface PromptExpanderProps {
  prompt: string;
  onSave?: (newPrompt: string) => void; // If provided, enables edit mode
  label?: string;
  previewLength?: number;
}

export function PromptExpander({
  prompt,
  onSave,
  label = "Prompt",
  previewLength = 80,
}: PromptExpanderProps) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(prompt);

  const preview = prompt.length > previewLength
    ? prompt.slice(0, previewLength) + "..."
    : prompt;

  const handleSave = () => {
    onSave?.(editText);
    setEditing(false);
  };

  const handleCancel = () => {
    setEditText(prompt);
    setEditing(false);
  };

  return (
    <div
      className="rounded-lg"
      style={{ background: "var(--bg-card-hover)", border: "1px solid var(--border)" }}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
      >
        {expanded ? (
          <ChevronDown size={12} style={{ color: "var(--text-muted)" }} />
        ) : (
          <ChevronRight size={12} style={{ color: "var(--text-muted)" }} />
        )}
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>{label}:</span>
        {!expanded && (
          <span
            className="text-xs truncate flex-1"
            style={{ color: "var(--text-secondary)" }}
          >
            {preview}
          </span>
        )}
      </button>

      {expanded && (
        <div className="px-3 pb-3">
          {editing ? (
            <div className="space-y-2">
              <textarea
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                className="w-full rounded-md px-3 py-2 text-xs outline-none resize-y min-h-[80px]"
                style={{
                  background: "var(--bg-primary)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
              <div className="flex gap-2">
                <button
                  onClick={handleSave}
                  className="flex items-center gap-1 text-xs px-3 py-1 rounded"
                  style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
                >
                  <Check size={10} /> Save
                </button>
                <button
                  onClick={handleCancel}
                  className="flex items-center gap-1 text-xs px-3 py-1 rounded"
                  style={{ color: "var(--text-muted)" }}
                >
                  <X size={10} /> Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-start gap-2">
              <p className="text-xs flex-1" style={{ color: "var(--text-secondary)", lineHeight: 1.6 }}>
                {prompt}
              </p>
              {onSave && (
                <button
                  onClick={() => setEditing(true)}
                  className="flex-shrink-0 p-1 rounded"
                  style={{ color: "var(--text-muted)" }}
                >
                  <Pencil size={12} />
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create VoicePlayer**

Mini audio player with play/pause, progress bar, timestamp, and redo button.

```typescript
// voice-player.tsx
"use client";

import { useState, useRef, useEffect } from "react";
import { Play, Pause, RotateCcw } from "lucide-react";

interface VoicePlayerProps {
  audioUrl: string;
  onRedo?: () => void;
  redoLoading?: boolean;
}

export function VoicePlayer({ audioUrl, onRedo, redoLoading }: VoicePlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const onTimeUpdate = () => {
      setCurrentTime(audio.currentTime);
      setProgress(audio.duration ? (audio.currentTime / audio.duration) * 100 : 0);
    };
    const onLoaded = () => setDuration(audio.duration);
    const onEnded = () => setPlaying(false);

    audio.addEventListener("timeupdate", onTimeUpdate);
    audio.addEventListener("loadedmetadata", onLoaded);
    audio.addEventListener("ended", onEnded);

    return () => {
      audio.removeEventListener("timeupdate", onTimeUpdate);
      audio.removeEventListener("loadedmetadata", onLoaded);
      audio.removeEventListener("ended", onEnded);
    };
  }, [audioUrl]);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      audio.pause();
    } else {
      audio.play();
    }
    setPlaying(!playing);
  };

  const seek = (e: React.MouseEvent<HTMLDivElement>) => {
    const audio = audioRef.current;
    if (!audio || !audio.duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    audio.currentTime = pct * audio.duration;
  };

  const fmt = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  };

  return (
    <div
      className="flex items-center gap-2 rounded-lg px-3 py-2"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <audio ref={audioRef} src={audioUrl} preload="metadata" />

      <button
        onClick={togglePlay}
        className="flex items-center justify-center rounded-full"
        style={{
          width: 28,
          height: 28,
          background: "#1A8A7A",
          color: "#fff",
          border: "none",
          flexShrink: 0,
        }}
      >
        {playing ? <Pause size={12} /> : <Play size={12} style={{ marginLeft: 1 }} />}
      </button>

      <div className="flex-1 cursor-pointer" onClick={seek}>
        <div className="h-1 rounded-full" style={{ background: "var(--border)" }}>
          <div
            className="h-full rounded-full transition-all"
            style={{ width: `${progress}%`, background: "#1A8A7A" }}
          />
        </div>
      </div>

      <span className="text-xs tabular-nums" style={{ color: "var(--text-muted)", flexShrink: 0 }}>
        {fmt(currentTime)} / {fmt(duration)}
      </span>

      {onRedo && (
        <button
          onClick={onRedo}
          disabled={redoLoading}
          className="flex items-center gap-1 text-xs px-2 py-1 rounded"
          style={{
            background: "var(--bg-card-hover)",
            border: "1px solid var(--border)",
            color: "var(--text-muted)",
            opacity: redoLoading ? 0.5 : 1,
          }}
        >
          <RotateCcw size={10} /> Redo
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create StageAdvancer**

Per-tab advancement button with polling indicator. Calls a specific pipeline stage endpoint (not generic advance).

```typescript
// stage-advancer.tsx
"use client";

import { useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, CheckCircle, AlertCircle } from "lucide-react";
import { runPipelineStage } from "@/lib/api";
import { useTaskPoller } from "@/hooks/use-task-poller";

interface StageAdvancerProps {
  videoId: string;
  stage: string; // Pipeline stage key (e.g., "voice", "images", "storyboards")
  label: string; // Button text (e.g., "Generate Voice")
  nextLabel?: string; // What the next stage is (e.g., "→ Image Prompts")
  disabled?: boolean;
  disabledReason?: string;
  cost?: string; // e.g., "$0.45"
}

export function StageAdvancer({
  videoId,
  stage,
  label,
  nextLabel,
  disabled,
  disabledReason,
  cost,
}: StageAdvancerProps) {
  const queryClient = useQueryClient();
  const [taskRunning, setTaskRunning] = useState(false);
  const [result, setResult] = useState<"success" | "error" | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const { status, message } = useTaskPoller({
    videoId,
    enabled: taskRunning,
    onComplete: () => {
      setTaskRunning(false);
      setResult("success");
      queryClient.invalidateQueries({ queryKey: ["video", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
      setTimeout(() => setResult(null), 3000);
    },
    onFailed: (err) => {
      setTaskRunning(false);
      setResult("error");
      setErrorMsg(err);
    },
  });

  const handleClick = useCallback(async () => {
    setResult(null);
    setErrorMsg(null);
    try {
      await runPipelineStage(videoId, stage);
      setTaskRunning(true);
    } catch (err: any) {
      setResult("error");
      setErrorMsg(err.message || "Failed to start");
    }
  }, [videoId, stage]);

  const handleRetry = () => {
    setResult(null);
    setErrorMsg(null);
    handleClick();
  };

  if (result === "success") {
    return (
      <div className="flex items-center gap-2 text-sm" style={{ color: "#1A8A7A" }}>
        <CheckCircle size={16} /> Done {nextLabel}
      </div>
    );
  }

  if (result === "error") {
    return (
      <div className="flex items-center gap-2">
        <span className="text-xs" style={{ color: "#C44545" }}>
          <AlertCircle size={14} className="inline mr-1" />
          {errorMsg || "Failed"}
        </span>
        <button
          onClick={handleRetry}
          className="text-xs px-3 py-1.5 rounded-lg font-medium"
          style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
        >
          Retry
        </button>
      </div>
    );
  }

  if (taskRunning) {
    return (
      <div className="flex items-center gap-2">
        <Loader2 size={14} className="animate-spin" style={{ color: "var(--amber)" }} />
        <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
          {message || "Processing..."}
        </span>
      </div>
    );
  }

  return (
    <button
      onClick={handleClick}
      disabled={disabled}
      className="flex items-center gap-2 text-sm px-4 py-2 rounded-lg font-medium transition-opacity disabled:opacity-40"
      style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
      title={disabled ? disabledReason : undefined}
    >
      {label}
      {cost && <span className="opacity-60">· {cost}</span>}
    </button>
  );
}
```

- [ ] **Step 4: Typecheck**

```bash
cd storyengine/frontend && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add storyengine/frontend/src/components/video-detail/prompt-expander.tsx \
       storyengine/frontend/src/components/video-detail/voice-player.tsx \
       storyengine/frontend/src/components/video-detail/stage-advancer.tsx
git commit -m "feat(storyengine): Add PromptExpander, VoicePlayer, StageAdvancer components"
```

---

## Task 7: Frontend — SceneEditor + SegmentList Components

**Files:**
- Create: `storyengine/frontend/src/components/video-detail/scene-editor.tsx`
- Create: `storyengine/frontend/src/components/video-detail/segment-list.tsx`

- [ ] **Step 1: Create SegmentList**

Collapsible sentence segment list. Collapsed shows summary "N segments · X words · Ys". Expanded shows each segment with metadata.

Key props: `videoId`, `scene`, `segments` (from parent query), `onRefresh`.

This component fetches segment data via `getSceneSegments` and displays the segment rows with word count, duration, and style tags. The split handle adjustment is a V2 feature — for now, show segments read-only with a "Re-split" button that calls the backend.

- [ ] **Step 2: Create SceneEditor**

Editable scene card combining: scene badge, tone dropdown, regen button, editable textarea, VoicePlayer (if voice exists), voice gen button (if no voice), and collapsible SegmentList.

Key props: `scene: ScriptScene`, `videoId: string`, `videoStatus: string`, `onRefresh: () => void`.

State management:
- `editing` boolean — toggle between display and textarea
- `text` — local text state for optimistic updates
- Blur handler calls `updateSceneText` API
- Tone dropdown calls `updateSceneTone` API
- Voice button calls `runVoiceForScene` + starts `useTaskPoller`
- Regen button calls `runPipelineStage(videoId, "script")` (regenerates full script — single-scene regen is a V2 endpoint)

- [ ] **Step 3: Typecheck**

```bash
cd storyengine/frontend && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add storyengine/frontend/src/components/video-detail/scene-editor.tsx \
       storyengine/frontend/src/components/video-detail/segment-list.tsx
git commit -m "feat(storyengine): Add SceneEditor and SegmentList components"
```

---

## Task 8: Frontend — Script Tab Rewrite

**Files:**
- Modify: `storyengine/frontend/src/components/video-detail/script-tab.tsx`

**Key context:** Current script-tab.tsx (205 lines) is read-only with suggestion diff UI. Replace the scene list with SceneEditor cards while preserving the suggestion comparison at the top.

- [ ] **Step 1: Rewrite script-tab.tsx**

Structure:
1. Keep existing suggestion banner (if `suggested_script` exists) — accept/reject at top
2. Replace the scene rendering with `<SceneEditor>` per scene
3. Add `StageAdvancer` at top-right:
   - If video status is `ready_for_scripting` or `ready_for_voice`: show appropriate advance button
   - Script → Voice: enabled when all scenes have text
   - Voice → Prompts: enabled when all scenes have `voice_over_url`
4. Pass `videoStatus` through so SceneEditor knows what to show

Remove: mobile single-scene carousel (simplify to scrollable list for both mobile and desktop — the scene cards are now interactive enough that carousel nav is unnecessary).

- [ ] **Step 2: Typecheck**

```bash
cd storyengine/frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add storyengine/frontend/src/components/video-detail/script-tab.tsx
git commit -m "feat(storyengine): Rewrite Script tab with SceneEditor cards and StageAdvancer"
```

---

## Task 9: Frontend — PanelMagnifier + StoryboardViewer Components

**Files:**
- Create: `storyengine/frontend/src/components/video-detail/panel-magnifier.tsx`
- Create: `storyengine/frontend/src/components/video-detail/storyboard-viewer.tsx`

- [ ] **Step 1: Create PanelMagnifier**

CSS crop/zoom of a storyboard grid image to show a single panel enlarged. **No extraction, no API calls.**

Props: `gridUrl: string`, `panelIndex: number` (0-8 within the grid), `size: number` (display size in px).

Implementation:
- The grid is a 3×3 image. Panel position: `row = Math.floor(panelIndex / 3)`, `col = panelIndex % 3`.
- Use CSS `background-image` with `background-position` and `background-size` to crop to the panel region.
- `background-size: 300% 300%` (3x zoom for a 3×3 grid).
- `background-position: ${col * 50}% ${row * 50}%`.

```typescript
// panel-magnifier.tsx
"use client";

interface PanelMagnifierProps {
  gridUrl: string;
  panelIndex: number; // 0-8 within the grid
  size?: number; // Display size in px
  className?: string;
}

export function PanelMagnifier({
  gridUrl,
  panelIndex,
  size = 200,
  className = "",
}: PanelMagnifierProps) {
  const row = Math.floor(panelIndex / 3);
  const col = panelIndex % 3;

  return (
    <div
      className={`rounded-lg ${className}`}
      style={{
        width: size,
        height: size,
        backgroundImage: `url(${gridUrl})`,
        backgroundSize: "300% 300%",
        backgroundPosition: `${col * 50}% ${row * 50}%`,
        backgroundRepeat: "no-repeat",
        flexShrink: 0,
      }}
    />
  );
}
```

- [ ] **Step 2: Create StoryboardViewer**

Complex component — one per scene. Contains: VO player, storyboard grids side by side, collapsible storyboard prompt, and panel detail area (uses PanelMagnifier).

Props: `scene: ScriptScene`, `assets: Asset[]`, `videoId: string`, `onRefresh: () => void`.

Key logic:
- Grid URLs come from `scene.storyboard_1_url`, `storyboard_2_url`, `storyboard_3_url`
- Filter out null URLs → array of grid URLs
- Panel count per grid = 9 (last grid may have fewer based on total image count)
- Total panels = assets for this scene, ordered by image_index
- Selected panel state — clicking a grid cell sets it, shows PanelMagnifier + detail below
- Panel numbering is continuous across grids (grid 1: 1-9, grid 2: 10-18)
- Map `panelIndex` → which grid + which cell within that grid
- VO player at top using VoicePlayer (if `scene.voice_over_url` exists)
- Storyboard prompt via PromptExpander (from `scene.storyboard_prompts`)
- Approve/reject per panel calls `approveAsset` / `rejectAsset` on the corresponding asset
- Keyboard handler: attach on focus, arrows navigate selectedPanel, Space toggles audio, A/R approve/reject

- [ ] **Step 3: Typecheck**

```bash
cd storyengine/frontend && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add storyengine/frontend/src/components/video-detail/panel-magnifier.tsx \
       storyengine/frontend/src/components/video-detail/storyboard-viewer.tsx
git commit -m "feat(storyengine): Add PanelMagnifier and StoryboardViewer components"
```

---

## Task 10: Frontend — ImageSegmentCard Component

**Files:**
- Create: `storyengine/frontend/src/components/video-detail/image-segment-card.tsx`

- [ ] **Step 1: Create ImageSegmentCard**

Horizontal card for storyboard-OFF path. Shows: image thumbnail (or placeholder), sentence text, collapsible prompt, action buttons.

Props: `asset: Asset`, `videoId: string`, `onRefresh: () => void`.

States:
- **No image:** Dashed border placeholder + amber "Generate · $0.025" button
- **Has image:** Thumbnail + Regenerate, 3 Variants, Edit Prompt, Hero Shot buttons
- **Generating:** Spinner overlay on thumbnail area

Actions:
- Generate/Regenerate → `runImageForSegment(videoId, scene, index)` + `useTaskPoller`
- 3 Variants → `runImageVariants(videoId, scene, index)` + poller
- Edit Prompt → `PromptExpander` in edit mode
- Hero Shot → `approveAsset` with hero flag (or separate endpoint if needed)

Uses `PromptExpander` for the collapsible prompt.

- [ ] **Step 2: Typecheck**

```bash
cd storyengine/frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add storyengine/frontend/src/components/video-detail/image-segment-card.tsx
git commit -m "feat(storyengine): Add ImageSegmentCard component for direct image generation"
```

---

## Task 11: Frontend — Visuals Tab Rewrite

**Files:**
- Modify: `storyengine/frontend/src/components/video-detail/visuals-tab.tsx`

**Key context:** Current visuals-tab.tsx (177 lines) is read-only image grid. Full rewrite to add storyboard toggle and two rendering paths.

- [ ] **Step 1: Rewrite visuals-tab.tsx**

Structure:
1. **Header** — "Visuals" title + storyboard mode toggle switch
2. **Info banner** — amber for storyboard ON, muted for OFF, explains the flow
3. **Pipeline progress indicator** — horizontal step dots (4 steps ON, 3 steps OFF)
4. **StageAdvancer** — contextual button based on current video status + storyboard mode
5. **Scene cards** — iterate over script scenes:
   - **Storyboard ON:** render `<StoryboardViewer>` per scene
   - **Storyboard OFF:** render per-segment `<ImageSegmentCard>` list grouped by scene, with VO player per scene

Props need `videoId` and `videoStatus` (status determines which StageAdvancer to show).

Data fetching:
- `useQuery(["video-script", videoId], () => getVideoScript(videoId))` for scene data
- `useQuery(["video-assets", videoId], () => getVideoAssets(videoId))` for image/segment data
- Determine storyboard mode from script scenes: if any scene has `storyboard_on_off === "On"`, mode is ON

Toggle handler:
- `updateStoryboardMode(videoId, !currentMode)` → invalidate queries

- [ ] **Step 2: Typecheck**

```bash
cd storyengine/frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add storyengine/frontend/src/components/video-detail/visuals-tab.tsx
git commit -m "feat(storyengine): Rewrite Visuals tab with storyboard toggle and dual-path rendering"
```

---

## Task 12: Frontend — Tab Consolidation (6 → 5 tabs) + Thumbnail Advancement

**Files:**
- Modify: `storyengine/frontend/src/app/pipeline/[videoId]/page.tsx`
- Modify: `storyengine/frontend/src/components/video-detail/thumbnail-tab.tsx`
- Delete: `storyengine/frontend/src/components/video-detail/storyboard-tab.tsx`

- [ ] **Step 1: Update video detail page tabs**

In `page.tsx`, change TABS array from 6 to 5 (remove "Board"):

```typescript
const TABS = [
  { id: "info", label: "Info" },
  { id: "script", label: "Script" },
  { id: "visuals", label: "Visuals" },
  { id: "thumbnail", label: "Thumb" },
  { id: "performance", label: "Perf" },
];
```

Remove the `StoryboardTab` import and its render case. Pass `video.status` to tabs that need it:

```typescript
{activeTab === "script" && <ScriptTab videoId={videoId} video={video} />}
{activeTab === "visuals" && <VisualsTab videoId={videoId} videoStatus={video.status || ""} />}
```

- [ ] **Step 2: Add StageAdvancer to thumbnail tab**

In `thumbnail-tab.tsx`, add at the top of the tab (after the header):

```typescript
<StageAdvancer
  videoId={video.id}
  stage="render"
  label="Approve Thumbnail → Render"
  disabled={!video.thumbnail_url}
  disabledReason="No thumbnail generated yet"
/>
```

Add the import: `import { StageAdvancer } from "./stage-advancer";`

- [ ] **Step 3: Delete storyboard-tab.tsx**

```bash
rm storyengine/frontend/src/components/video-detail/storyboard-tab.tsx
```

- [ ] **Step 4: Typecheck + verify build**

```bash
cd storyengine/frontend && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add -A storyengine/frontend/src/app/pipeline/[videoId]/page.tsx \
           storyengine/frontend/src/components/video-detail/thumbnail-tab.tsx \
           storyengine/frontend/src/components/video-detail/storyboard-tab.tsx
git commit -m "feat(storyengine): Consolidate tabs 6→5, merge storyboard into visuals, add thumbnail advancement"
```

---

## Task 13: Final Integration Verification

**Files:** None (verification only)

- [ ] **Step 1: Full typecheck**

```bash
cd storyengine/frontend && npx tsc --noEmit
```
Expected: Clean compile, zero errors.

- [ ] **Step 2: Verify all imports resolve**

```bash
cd storyengine/frontend && npx next build 2>&1 | head -30
```
Expected: Build starts successfully (may be slow, just verify no import errors).

- [ ] **Step 3: Verify backend starts**

```bash
cd storyengine/backend && python -c "
from routes.videos import router as v
from routes.pipeline import router as p
from routes.assets import router as a
print('All routes import cleanly')
"
```

- [ ] **Step 4: Update tasks/todo.md**

Mark Module 3 as complete, update handoff notes for next session.

- [ ] **Step 5: Final commit**

```bash
git add tasks/todo.md
git commit -m "docs: Mark Module 3 interactive features complete"
```

---

## Dependency Graph

```
Task 1 (migration) ──────────────────────────────┐
Task 2 (backend scene endpoints) ─────────────────┤
Task 3 (backend targeted regen) ──────────────────┤
                                                   ▼
Task 4 (frontend API functions) ──────────────────┐
                                                   ▼
Task 5 (useTaskPoller hook) ──────────────────────┐
Task 6 (shared components) ───────────────────────┤
                                                   ▼
Task 7 (SceneEditor + SegmentList) ──► Task 8 (Script tab rewrite)
Task 9 (PanelMagnifier + StoryboardViewer) ──┐
Task 10 (ImageSegmentCard) ──────────────────┤
                                              ▼
                              Task 11 (Visuals tab rewrite) ──► Task 12 (Tab consolidation)
                                                                        ▼
                                                              Task 13 (Verification)
```

**Parallelizable:** Tasks 1-3 (backend), Tasks 7+9+10 (independent components), Tasks 8+11 (tab rewrites after their deps).
