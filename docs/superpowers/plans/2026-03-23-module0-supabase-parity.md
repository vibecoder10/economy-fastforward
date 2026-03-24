# Module 0: Supabase Migration Verification & Fix

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get Supabase schema to 100% parity with Airtable (203 fields across 8 tables), fix schema bugs, update sync script, and verify data integrity. This is the P0 blocker before any other StoryEngine module.

**Architecture:** Write an `ALTER TABLE` migration to add ~30 missing columns across 3 tables (videos, assets, competitor_videos), add the `autopilot_config` table, fix column naming bugs, update the sync script to populate the new columns, then run a full re-sync and verify.

**Tech Stack:** PostgreSQL (Supabase), Python (sync script), FastAPI (backend routes)

**Key Files:**
- Schema: `storyengine/schema.sql`
- Migration: `storyengine/backend/migrations/004_schema_parity.sql` (NEW)
- Sync: `storyengine/sync/airtable_sync.py`
- Backend routes: `storyengine/backend/routes/videos.py`
- Airtable reference: `skills/video-pipeline/pipeline_constants.py`

---

## Gap Summary

### videos table — 26 columns missing

| Column to Add | Type | Airtable Source Field |
|---|---|---|
| `scene_file_path` | TEXT | `Scene File Path` |
| `core_image_url` | TEXT | `Core Image` (attachment) |
| `reference_url` | TEXT | `Reference URL` |
| `idea_reasoning` | TEXT | `Idea Reasoning` |
| `source_views` | INTEGER | `Source Views` |
| `source_channel` | TEXT | `Source Channel` |
| `pipeline_mode` | TEXT | `Pipeline Mode` |
| `notes` | TEXT | `Notes` |
| `final_video_attachment_url` | TEXT | `Final Video` (attachment) |
| `framework` | TEXT | `Framework` |
| `sources` | TEXT | `Sources` |
| `scene_count` | INTEGER | `Scene Count` |
| `validation_status` | TEXT | `Validation Status` |
| `video_id_internal` | TEXT | `Video ID` (internal) |
| `storyboard_status` | TEXT | `Storyboard Status` |
| `storyboard_preview_url` | TEXT | `Storyboard Preview` (attachment) |
| `storyboard_beat_count` | INTEGER | `Storyboard Beat Count` |
| `video_model` | TEXT | `Video Model` |
| `structure_source` | TEXT | `Structure Source` |
| `pattern_library_snapshot` | TEXT | `Pattern Library Snapshot` |
| `title_poll_result` | TEXT | `Title Poll Result` |
| `poll_closed` | BOOLEAN | `Poll Closed` |
| `thumbnail_palette` | TEXT | `Thumbnail Palette` |
| `summary` | TEXT | `Summary` |
| `ctr_12h` | NUMERIC | `CTR 12h (%)` |
| `ctr_24h` | NUMERIC | `CTR 24h (%)` |

### assets table — 7 columns missing

| Column to Add | Type | Airtable Source Field |
|---|---|---|
| `drive_image_url` | TEXT | `Drive Image URL` |
| `storyboard_grid_url` | TEXT | `Storyboard Grid URL` |
| `panel_position` | INTEGER | `Panel Position` |
| `generation_method` | TEXT | `Generation Method` |
| `camera_movement` | TEXT | `Camera Movement` |
| `assigned_video_duration` | NUMERIC | `Assigned Video Duration` |
| `estimated_clip_cost` | NUMERIC | `Estimated Clip Cost` |

### competitor_videos table — up to 14 columns missing

Migration 003 created this table with a stripped-down schema. If 003 was the actual DDL run (not schema.sql), these columns from schema.sql are missing:

| Column to Add | Type | Notes |
|---|---|---|
| `airtable_record_id` | TEXT | Sync dedup key |
| `our_video` | TEXT | Title of our modeled video |
| `topic_cluster` | TEXT | Auto-categorized topic |
| `curiosity_structure` | TEXT | Curiosity gap structure |
| `structure_confidence` | NUMERIC | 0-100 |
| `thumbnail_style_json` | TEXT | Thumbnail analysis JSON |
| `yin_yang_approach` | TEXT | from_hook or from_gap |
| `yin_yang_text` | TEXT | Extracted thumbnail text |
| `analysis_date` | DATE | When analysis ran |
| `modeled_by_us` | BOOLEAN | Whether we modeled this |
| `our_ctr_result` | NUMERIC | Our CTR if modeled |
| `modeled_at` | TIMESTAMPTZ | Written by autopilot launch |
| `our_video_id` | UUID FK | References videos(id) |
| `updated_at` | TIMESTAMPTZ | Last update timestamp |

### autopilot_config table — missing from schema.sql entirely

Exists only in migration 003. Must be added to schema.sql.

### Bugs to Fix

1. **Backend routes/videos.py** queries `image_model_override` but schema column is `image_model` — rename column to `image_model_override` for clarity
2. **Backend routes/autopilot.py** writes to `modeled_at` on `competitor_videos` — column doesn't exist in schema.sql
3. **schema.sql diverges from migration 003** — competitor_videos and learnings have different column sets

---

## Task 1: Write Migration SQL

**Files:**
- Create: `storyengine/backend/migrations/004_schema_parity.sql`

- [ ] **Step 1: Create migration file**

```sql
-- 004_schema_parity.sql
-- Adds all missing Airtable fields to Supabase for 100% parity
-- Run in Supabase SQL Editor

-- =============================================
-- VIDEOS — Add 26 missing columns
-- =============================================

ALTER TABLE videos ADD COLUMN IF NOT EXISTS scene_file_path TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS core_image_url TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS reference_url TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS idea_reasoning TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS source_views INTEGER;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS source_channel TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS pipeline_mode TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS final_video_attachment_url TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS framework TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS sources TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS scene_count INTEGER;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS validation_status TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS video_id_internal TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS storyboard_status TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS storyboard_preview_url TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS storyboard_beat_count INTEGER;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS video_model TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS structure_source TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS pattern_library_snapshot TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS title_poll_result TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS poll_closed BOOLEAN DEFAULT false;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS thumbnail_palette TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS ctr_12h NUMERIC;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS ctr_24h NUMERIC;

-- Rename image_model → image_model_override (idempotent — only if old name exists)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'videos' AND column_name = 'image_model') THEN
    ALTER TABLE videos RENAME COLUMN image_model TO image_model_override;
  END IF;
END $$;

-- =============================================
-- ASSETS — Add 7 missing columns
-- =============================================

ALTER TABLE assets ADD COLUMN IF NOT EXISTS drive_image_url TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS storyboard_grid_url TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS panel_position INTEGER;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS generation_method TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS camera_movement TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS assigned_video_duration NUMERIC;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS estimated_clip_cost NUMERIC;

-- =============================================
-- COMPETITOR_VIDEOS — Add columns missing from migration 003
-- (migration 003 has a stripped-down schema; these columns exist
--  in schema.sql but may not exist if 003 was the actual DDL run)
-- =============================================

ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS airtable_record_id TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS our_video TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS topic_cluster TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS curiosity_structure TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS structure_confidence NUMERIC;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS thumbnail_style_json TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS yin_yang_approach TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS yin_yang_text TEXT;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS analysis_date DATE;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS modeled_by_us BOOLEAN DEFAULT false;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS our_ctr_result NUMERIC;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS modeled_at TIMESTAMPTZ;
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS our_video_id UUID REFERENCES videos(id);
ALTER TABLE competitor_videos ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- Add unique constraint if not exists (idempotent via DO block)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'competitor_videos_tenant_video_unique'
  ) THEN
    ALTER TABLE competitor_videos ADD CONSTRAINT competitor_videos_tenant_video_unique
      UNIQUE (tenant_id, video_id);
  END IF;
END $$;

-- Add VPH index for autopilot ranking
CREATE INDEX IF NOT EXISTS idx_competitor_videos_vph ON competitor_videos(vph DESC);
CREATE INDEX IF NOT EXISTS idx_competitor_videos_modeled ON competitor_videos(modeled);

-- =============================================
-- AUTOPILOT_CONFIG — Create if not exists
-- =============================================

CREATE TABLE IF NOT EXISTS autopilot_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) UNIQUE,
    enabled BOOLEAN DEFAULT TRUE,
    videos_per_month INT DEFAULT 15,
    production_interval_days INT DEFAULT 2,
    weights JSONB DEFAULT '{"competitor_vph": 0.55, "timing_freshness": 0.45}'::jsonb,
    thresholds JSONB DEFAULT '{
        "min_confidence_score": 60,
        "min_competitor_vph": 50,
        "max_idea_age_days": 7,
        "ctr_success_threshold": 4.0,
        "ctr_failure_threshold": 2.5
    }'::jsonb,
    last_cycle TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE autopilot_config ENABLE ROW LEVEL SECURITY;

-- Use same RLS pattern as other tables
-- Check both policy name variants (migration 003 used lowercase, schema.sql uses capitalized)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'autopilot_config'
      AND (policyname = 'Tenant isolation' OR policyname = 'tenant_isolation')
  ) THEN
    CREATE POLICY "Tenant isolation" ON autopilot_config FOR ALL TO authenticated
      USING (tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid())));
  END IF;
END $$;

-- =============================================
-- LEARNINGS — Add missing columns from schema.sql
-- (migration 003 version is missing these)
-- =============================================

ALTER TABLE learnings ADD COLUMN IF NOT EXISTS airtable_record_id TEXT;
ALTER TABLE learnings ADD COLUMN IF NOT EXISTS detail TEXT;
ALTER TABLE learnings ADD COLUMN IF NOT EXISTS created_date DATE;
ALTER TABLE learnings ADD COLUMN IF NOT EXISTS last_updated DATE;

-- Fix type mismatch: migration 003 created source_videos as JSONB,
-- but sync script writes plain strings via _str(). Normalize to TEXT.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'learnings' AND column_name = 'source_videos' AND data_type = 'jsonb'
  ) THEN
    ALTER TABLE learnings ALTER COLUMN source_videos TYPE TEXT USING source_videos::TEXT;
  END IF;
END $$;

-- Add unique constraint on airtable_record_id if not exists (needed for upsert)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'learnings_airtable_record_id_key'
  ) THEN
    ALTER TABLE learnings ADD CONSTRAINT learnings_airtable_record_id_key UNIQUE (airtable_record_id);
  END IF;
EXCEPTION WHEN duplicate_object THEN
  NULL; -- constraint already exists under different name
END $$;
```

- [ ] **Step 2: Verify migration is idempotent**

Read the file and confirm every statement uses `IF NOT EXISTS` or `IF NOT EXISTS` guards so it can be safely re-run.

- [ ] **Step 3: Commit**

```bash
git add storyengine/backend/migrations/004_schema_parity.sql
git commit -m "feat(storyengine): Add migration 004 — Supabase schema parity with Airtable

Adds 26 missing columns to videos, 7 to assets, 3 to competitor_videos.
Creates autopilot_config table. Renames image_model → image_model_override.
All statements idempotent (IF NOT EXISTS)."
```

---

## Task 2: Update schema.sql (Canonical Reference)

**Files:**
- Modify: `storyengine/schema.sql`

- [ ] **Step 1: Add missing columns to videos table definition**

Add after the `-- Post-mortem` section (around line 143):

```sql
  -- Storyboard
  storyboard_status TEXT,
  storyboard_preview_url TEXT,
  storyboard_beat_count INTEGER,
  video_model TEXT,

  -- Pipeline state
  scene_file_path TEXT,
  core_image_url TEXT,
  scene_count INTEGER,
  validation_status TEXT,
  video_id_internal TEXT,
  framework TEXT,
  sources TEXT,
  pipeline_mode TEXT,
  notes TEXT,

  -- Source tracking
  reference_url TEXT,
  idea_reasoning TEXT,
  source_views INTEGER,
  source_channel TEXT,

  -- Upload (additional)
  final_video_attachment_url TEXT,

  -- Curiosity Gap (additional)
  structure_source TEXT,
  pattern_library_snapshot TEXT,
  title_poll_result TEXT,
  poll_closed BOOLEAN DEFAULT false,

  -- Thumbnail (additional)
  thumbnail_palette TEXT,
  summary TEXT,

  -- Performance snapshots (additional)
  ctr_12h NUMERIC,
  ctr_24h NUMERIC,
```

- [ ] **Step 2: Rename `image_model` to `image_model_override` in videos CREATE**

Change line 100 from `image_model TEXT,` to `image_model_override TEXT,`.

- [ ] **Step 3: Add missing columns to assets table definition**

Add after `hero_shot` (around line 229):

```sql
  -- Storyboard tracking
  drive_image_url TEXT,
  storyboard_grid_url TEXT,
  panel_position INTEGER,
  generation_method TEXT,
  camera_movement TEXT,
  assigned_video_duration NUMERIC,
  estimated_clip_cost NUMERIC,
```

- [ ] **Step 4: Add modeled_at and our_video_id to competitor_videos definition**

Add after `our_ctr_result NUMERIC,` (around line 282):

```sql
  modeled_at TIMESTAMPTZ,
  our_video_id UUID REFERENCES videos(id),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id, video_id),
```

- [ ] **Step 5: Add autopilot_config table to schema.sql**

Add a new section after `title_tests` and before `stage_transitions`:

```sql
-- =============================================
-- AUTOPILOT CONFIG (per-tenant settings)
-- =============================================

CREATE TABLE autopilot_config (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE UNIQUE NOT NULL,
  enabled BOOLEAN DEFAULT TRUE,
  videos_per_month INT DEFAULT 15,
  production_interval_days INT DEFAULT 2,
  weights JSONB DEFAULT '{"competitor_vph": 0.55, "timing_freshness": 0.45}'::jsonb,
  thresholds JSONB DEFAULT '{
      "min_confidence_score": 60,
      "min_competitor_vph": 50,
      "max_idea_age_days": 7,
      "ctr_success_threshold": 4.0,
      "ctr_failure_threshold": 2.5
  }'::jsonb,
  last_cycle TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

Add RLS + policy for autopilot_config in the RLS section.

Add to DROP TABLE list at top: `DROP TABLE IF EXISTS autopilot_config CASCADE;`

- [ ] **Step 6: Commit**

```bash
git add storyengine/schema.sql
git commit -m "docs(storyengine): Update schema.sql to canonical reference with all Airtable fields

Now includes all 203 fields across 8 data tables + autopilot_config.
Renames image_model → image_model_override for consistency."
```

---

## Task 3: Update Sync Script

**Files:**
- Modify: `storyengine/sync/airtable_sync.py`

- [ ] **Step 1: Add missing video fields to sync_videos()**

In the `sync_videos` method (around line 316), add to the `row` dict after `"performance_verdict"`:

```python
                # Pipeline state
                "scene_file_path": _str(f.get("Scene File Path")),
                "core_image_url": _att_url(f.get("Core Image")),
                "scene_count": _int(f.get("Scene Count")) if f.get("Scene Count") is not None else None,
                "validation_status": _str(f.get("Validation Status")),
                "video_id_internal": _str(f.get("Video ID")),
                "framework": _str(f.get("Framework")),
                "sources": _str(f.get("Sources")),
                "pipeline_mode": _str(f.get("Pipeline Mode")),
                "notes": _str(f.get("Notes")),
                # Source tracking
                "reference_url": _str(f.get("Reference URL")),
                "idea_reasoning": _str(f.get("Idea Reasoning")),
                "source_views": _int(f.get("Source Views")) if f.get("Source Views") is not None else None,
                "source_channel": _str(f.get("Source Channel")),
                # Upload (additional)
                "final_video_attachment_url": _att_url(f.get("Final Video")),
                # Storyboard
                "storyboard_status": _str(f.get("Storyboard Status")),
                "storyboard_preview_url": _att_url(f.get("Storyboard Preview")),
                "storyboard_beat_count": _int(f.get("Storyboard Beat Count")) if f.get("Storyboard Beat Count") is not None else None,
                "video_model": _str(f.get("Video Model")),
                # Curiosity Gap (additional)
                "structure_source": _str(f.get("Structure Source")),
                "pattern_library_snapshot": _str(f.get("Pattern Library Snapshot")),
                "title_poll_result": _str(f.get("Title Poll Result")),
                "poll_closed": _bool(f.get("Poll Closed")),
                # Thumbnail (additional)
                "thumbnail_palette": _str(f.get("Thumbnail Palette")),
                "summary": _str(f.get("Summary")),
                # Performance snapshots (additional)
                "ctr_12h": _float(f.get("CTR 12h (%)")),
                "ctr_24h": _float(f.get("CTR 24h (%)")),
```

- [ ] **Step 2: Rename `image_model` key to `image_model_override` in sync_videos()**

Change line 358 from:
```python
"image_model": _str(f.get("Image Model")),
```
to:
```python
# Image Model Override is a Multiple Select in Airtable.
# Try both field names (field may be named "Image Model" or "Image Model Override").
_imo = f.get("Image Model Override") or f.get("Image Model")
"image_model_override": _str(_imo[0]) if isinstance(_imo, list) and _imo else _str(_imo),
```

Note: `Image Model Override` is a Multiple Select field in Airtable — it returns a list like `["z-image"]`. We extract the first value to store as a clean string. We try both possible field names since the current sync uses `"Image Model"` but `pipeline_constants.py` defines it as `"Image Model Override"`.

- [ ] **Step 3: Add missing asset fields to sync_assets()**

In the `sync_assets` method (around line 461), add to the `row` dict after `"hero_shot"`:

```python
                # Storyboard tracking
                "drive_image_url": _str(f.get("Drive Image URL")),
                "storyboard_grid_url": _str(f.get("Storyboard Grid URL")),
                "panel_position": _int(f.get("Panel Position")) if f.get("Panel Position") is not None else None,
                "generation_method": _str(f.get("Generation Method")),
                "camera_movement": _str(f.get("Camera Movement")),
                "assigned_video_duration": _float(f.get("Assigned Video Duration")),
                "estimated_clip_cost": _float(f.get("Estimated Clip Cost")),
```

- [ ] **Step 4: Commit**

```bash
git add storyengine/sync/airtable_sync.py
git commit -m "feat(storyengine): Sync all missing Airtable fields to Supabase

Adds 26 new video fields, 7 new asset fields to sync.
Renames image_model → image_model_override.
Full parity with Airtable schema (203 fields)."
```

---

## Task 4: Fix Backend Route Bugs

**Files:**
- Modify: `storyengine/backend/routes/videos.py`

- [ ] **Step 1: Verify the column rename fixed the videos.py bug**

After running migration 004, the column is now `image_model_override` which matches what `routes/videos.py` already queries. No code change needed — the migration fixes the mismatch.

Verify by reading `storyengine/backend/routes/videos.py` lines 95-100 and confirming the query uses `image_model_override`.

- [ ] **Step 2: Check autopilot route for modeled_at**

Read `storyengine/backend/routes/autopilot.py` and verify the `launch_candidate` endpoint writes to `modeled_at`. After migration 004, this column now exists. No code change needed.

- [ ] **Step 3: Commit (if any fixes needed)**

Only commit if code changes were required. The migration handles the schema side.

---

## Task 5: Run Migration on Supabase

**IMPORTANT:** This task requires running SQL against the live Supabase instance.

- [ ] **Step 1: Connect to Supabase SQL Editor**

Go to `https://supabase.com/dashboard` → project `rcbobwaldrefnyllhjyo` → SQL Editor.

- [ ] **Step 2: Run migration 004**

Paste the contents of `storyengine/backend/migrations/004_schema_parity.sql` and execute.

Expected: All statements succeed (no errors due to IF NOT EXISTS guards).

- [ ] **Step 3: Verify columns were added**

Run in SQL Editor:
```sql
-- Count columns per table
SELECT 'videos' as tbl, count(*) FROM information_schema.columns WHERE table_name = 'videos'
UNION ALL
SELECT 'assets', count(*) FROM information_schema.columns WHERE table_name = 'assets'
UNION ALL
SELECT 'scripts', count(*) FROM information_schema.columns WHERE table_name = 'scripts'
UNION ALL
SELECT 'competitor_videos', count(*) FROM information_schema.columns WHERE table_name = 'competitor_videos'
UNION ALL
SELECT 'learnings', count(*) FROM information_schema.columns WHERE table_name = 'learnings'
UNION ALL
SELECT 'title_insights', count(*) FROM information_schema.columns WHERE table_name = 'title_insights'
UNION ALL
SELECT 'title_tests', count(*) FROM information_schema.columns WHERE table_name = 'title_tests'
UNION ALL
SELECT 'autopilot_config', count(*) FROM information_schema.columns WHERE table_name = 'autopilot_config';
```

Expected column counts:
- videos: ~99
- assets: ~34
- scripts: ~25
- competitor_videos: ~25
- learnings: ~15
- title_insights: ~13
- title_tests: ~17
- autopilot_config: ~10

- [ ] **Step 4: Verify autopilot_config table exists**

```sql
SELECT * FROM autopilot_config LIMIT 1;
```

Expected: Empty result (no error).

---

## Task 6: Run Full Re-sync

- [ ] **Step 1: SSH to VPS**

```bash
ssh clawd@76.13.119.181
```

- [ ] **Step 2: Pull latest code**

```bash
cd ~/projects/economy-fastforward && git pull --ff-only
```

- [ ] **Step 3: Run full sync**

```bash
cd ~/projects/storyengine && \
  backend/venv/bin/python sync/airtable_sync.py --full
```

Expected: All 8 tables sync successfully. Watch for individual row errors (printed to stdout).

- [ ] **Step 4: Note the sync output counts**

Record the counts:
```
Synced X videos, Y scripts, Z assets, ...
```

---

## Task 7: Verify Data Integrity

- [ ] **Step 1: Compare record counts**

Run in Supabase SQL Editor:
```sql
SELECT 'videos' as tbl, count(*) FROM videos
UNION ALL SELECT 'scripts', count(*) FROM scripts
UNION ALL SELECT 'assets', count(*) FROM assets
UNION ALL SELECT 'competitor_channels', count(*) FROM competitor_channels
UNION ALL SELECT 'competitor_videos', count(*) FROM competitor_videos
UNION ALL SELECT 'learnings', count(*) FROM learnings
UNION ALL SELECT 'title_insights', count(*) FROM title_insights
UNION ALL SELECT 'title_tests', count(*) FROM title_tests;
```

Compare against Airtable record counts (check via Airtable UI or API).

- [ ] **Step 2: Spot check — verify new video columns have data**

```sql
SELECT video_title, scene_file_path, storyboard_status, notes, ctr_12h, ctr_24h,
       source_views, framework, pipeline_mode
FROM videos
WHERE status = 'done'
ORDER BY created_at DESC
LIMIT 5;
```

Expected: At least some non-null values in the new columns for completed videos.

- [ ] **Step 3: Spot check — verify new asset columns have data**

```sql
SELECT video_title, scene, image_index, drive_image_url, storyboard_grid_url,
       panel_position, generation_method, camera_movement
FROM assets
WHERE status = 'Done'
ORDER BY created_at DESC
LIMIT 10;
```

Expected: `drive_image_url` and storyboard fields populated for videos that used storyboards.

- [ ] **Step 4: Verify image_model_override column works**

```sql
SELECT video_title, image_model_override, visual_style
FROM videos
WHERE image_model_override IS NOT NULL
LIMIT 5;
```

Expected: No error (column exists and is queryable).

- [ ] **Step 5: Verify JSON fields are proper JSONB**

```sql
SELECT video_title,
       pg_typeof(research_payload) as rp_type,
       pg_typeof(original_dna) as dna_type,
       jsonb_typeof(research_payload::jsonb) as rp_json_type
FROM videos
WHERE research_payload IS NOT NULL
LIMIT 3;
```

Expected: `rp_type = jsonb`, `rp_json_type = object`.

- [ ] **Step 6: Write migration report**

Create `storyengine/MIGRATION_REPORT.md` summarizing:
- Tables verified (8)
- Columns added (26 + 7 + 3 = 36)
- Bugs fixed (image_model rename, modeled_at, autopilot_config)
- Record counts
- Data integrity spot check results

- [ ] **Step 7: Final commit**

```bash
git add storyengine/MIGRATION_REPORT.md
git commit -m "docs(storyengine): Module 0 complete — Supabase schema at 100% Airtable parity

Migration 004 adds 36 missing columns, fixes image_model naming,
adds autopilot_config table. Full re-sync verified.
Record counts match. JSON fields validated."
```

---

## Completion Criteria

- [ ] All 8 Supabase tables have identical columns to their Airtable counterparts
- [ ] Record counts match between Airtable and Supabase
- [ ] JSON fields (Research Payload, Original DNA) stored as proper JSONB
- [ ] `image_model_override` column name matches backend route queries
- [ ] `modeled_at` column exists on competitor_videos
- [ ] `autopilot_config` table exists and is in schema.sql
- [ ] Full re-sync completed without errors
- [ ] Migration report generated

**Total estimated changes:** 1 new SQL file (~80 lines), 2 modified files (~60 lines of additions), 1 report.
