# StoryEngine Phase 1: Pipeline Integration

**Date:** 2026-03-23
**Goal:** Wire existing pipeline skills into StoryEngine dashboard

---

## Critical Design Decision: Centralized Status Mapping

**Location:** `storyengine/backend/status_map.py`

The pipeline uses "Ready For Scripting" format. Supabase uses "ready_for_scripting" format.
ALL conversions go through this single file. No inline conversions anywhere.

```python
# status_map.py - SINGLE SOURCE OF TRUTH
STATUS_MAP = {
    # Pipeline → Supabase
    "Idea Logged": "idea_logged",
    "Approved": "approved",
    "Ready For Scripting": "ready_for_scripting",
    "Ready For Voice": "ready_for_voice",
    "Ready For Image Prompts": "ready_for_image_prompts",
    "Ready For Storyboards": "ready_for_storyboards",
    "Ready For Storyboard Images": "ready_for_storyboard_images",
    "Ready For Storyboard Extraction": "ready_for_storyboard_extraction",
    "Ready For Images": "ready_for_images",
    "Ready For Sound Design": "ready_for_sound_design",
    "Ready For Sound Effects": "ready_for_sound_effects",
    "Ready For Video Scripts": "ready_for_video_scripts",
    "Ready For Video Generation": "ready_for_video_generation",
    "Ready For Thumbnail": "ready_for_thumbnail",
    "Done": "done",
    "Ready To Render": "ready_to_render",
    "Rendered": "rendered",
    "Uploaded (Draft)": "uploaded_draft",
    "In Que": "in_queue",
    "Needs Script Review": "needs_script_review",
}

# Reverse map for Supabase → Pipeline
REVERSE_STATUS_MAP = {v: k for k, v in STATUS_MAP.items()}

def to_supabase(pipeline_status: str) -> str:
    """Convert pipeline status to Supabase format."""
    return STATUS_MAP.get(pipeline_status, pipeline_status.lower().replace(" ", "_"))

def to_pipeline(supabase_status: str) -> str:
    """Convert Supabase status to pipeline format."""
    return REVERSE_STATUS_MAP.get(supabase_status, supabase_status)
```

---

## Task 1: Create Status Map Module

**File:** `storyengine/backend/status_map.py`

- [ ] Create STATUS_MAP dict with all pipeline statuses
- [ ] Create REVERSE_STATUS_MAP for bidirectional lookup
- [ ] Add `to_supabase()` and `to_pipeline()` functions
- [ ] Add `get_next_status()` for pipeline progression

---

## Task 2: Create Pipeline Routes

**File:** `storyengine/backend/routes/pipeline.py`

Endpoints:
- [ ] `POST /api/pipeline/create-idea` - Create new video idea
- [ ] `POST /api/pipeline/research/{video_id}` - Run research agent
- [ ] `POST /api/pipeline/script/{video_id}` - Generate script
- [ ] `POST /api/pipeline/voice/{video_id}` - Generate voice
- [ ] `POST /api/pipeline/prompts/{video_id}` - Generate image prompts
- [ ] `POST /api/pipeline/images/{video_id}` - Generate images
- [ ] `POST /api/pipeline/thumbnail/{video_id}` - Generate thumbnail
- [ ] `POST /api/pipeline/render/{video_id}` - Trigger render
- [ ] `POST /api/pipeline/run-next/{video_id}` - Auto-advance one step
- [ ] `GET /api/pipeline/status/{video_id}` - Get current pipeline status

Each endpoint:
1. Validates video exists and is at correct status
2. Runs pipeline skill as background task
3. Logs to bot_activity table
4. Updates video status in Supabase
5. Returns immediately with task_id

---

## Task 3: Create Pipeline Executor

**File:** `storyengine/backend/pipeline_executor.py`

This module wraps the existing pipeline skills for use from StoryEngine:

- [ ] Add sys.path to import from `skills/video-pipeline/`
- [ ] Create `PipelineExecutor` class that:
  - Initializes pipeline clients (Anthropic, Airtable, etc.)
  - Loads API keys from Supabase Vault (fallback to .env)
  - Executes stages with proper error handling
  - Dual-writes results to both Airtable and Supabase
- [ ] Add activity logging wrapper

---

## Task 4: Create Vault Helper

**File:** `storyengine/backend/vault.py`

- [ ] `get_secret(name: str)` - Read from Supabase Vault
- [ ] `set_secret(name: str, value: str)` - Write to Supabase Vault
- [ ] `delete_secret(name: str)` - Remove from Vault
- [ ] `list_secrets()` - List available secrets (names only, not values)
- [ ] Fallback to os.environ if Vault not configured

---

## Task 5: Settings API Routes

**File:** `storyengine/backend/routes/settings.py`

- [ ] `GET /api/settings/keys` - List configured API keys (masked)
- [ ] `POST /api/settings/keys/{key_name}` - Set API key
- [ ] `DELETE /api/settings/keys/{key_name}` - Delete API key
- [ ] `POST /api/settings/keys/{key_name}/test` - Test connection

Key names:
- `anthropic_api_key`
- `elevenlabs_api_key`
- `kie_ai_api_key`
- `openai_api_key`
- `gemini_api_key`
- `google_service_account` (JSON)

---

## Task 6: Settings Page UI

**File:** `storyengine/frontend/src/app/settings/page.tsx`

- [ ] API Keys section with:
  - Key name, masked value (••••last4), status badge
  - "Reveal" toggle (shows full key briefly)
  - "Test" button (pings respective API)
  - "Save" button
- [ ] Add API functions to `api.ts`

---

## Task 7: Pipeline Actions in UI

**Files:**
- `storyengine/frontend/src/components/pipeline-actions.tsx`
- `storyengine/frontend/src/app/pipeline/page.tsx`

- [ ] Add action buttons to video detail panel based on current status
- [ ] Add "Create Video" button to Pipeline page header
- [ ] Create video dialog with topic input
- [ ] Add loading/progress states for running stages
- [ ] Add API functions to `api.ts`

---

## Task 8: Wire Routes into main.py

**File:** `storyengine/backend/main.py`

- [ ] Import and register pipeline routes
- [ ] Import and register settings routes
- [ ] Add sys.path for pipeline imports

---

## Verification Checklist

- [ ] Create a new video idea from UI
- [ ] Run research on the idea
- [ ] Verify video advances to "ready_for_scripting"
- [ ] Check bot_activity table has entries
- [ ] Settings page shows API keys
- [ ] Test connection works for at least Anthropic

---

## Files to Create

1. `storyengine/backend/status_map.py` - Status mapping
2. `storyengine/backend/routes/pipeline.py` - Pipeline trigger endpoints
3. `storyengine/backend/routes/settings.py` - Settings endpoints
4. `storyengine/backend/pipeline_executor.py` - Pipeline skill wrapper
5. `storyengine/backend/vault.py` - Supabase Vault helper
6. `storyengine/frontend/src/components/pipeline-actions.tsx` - Action buttons
7. `storyengine/frontend/src/components/create-video-dialog.tsx` - New video modal

## Files to Modify

1. `storyengine/backend/main.py` - Register new routes
2. `storyengine/frontend/src/app/settings/page.tsx` - Replace stub
3. `storyengine/frontend/src/app/pipeline/page.tsx` - Add actions
4. `storyengine/frontend/src/lib/api.ts` - Add API functions
