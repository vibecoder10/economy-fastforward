# Module 0: Supabase Migration Report

**Date:** 2026-03-24
**Status:** Complete

## Summary

Supabase schema brought to 100% parity with Airtable. Migration 004 applied, full re-sync completed, all data verified.

## Tables Verified (8 data tables + 1 config)

| Table | Supabase Rows | Airtable Records | Match |
|-------|--------------|-------------------|-------|
| videos (Idea Concepts) | 26 | 26 | Yes |
| scripts | 53 | 53 | Yes |
| assets (Images) | 568 | 568 | Yes |
| competitor_channels | 8 | 8 | Yes |
| competitor_videos | 330 | 330 | Yes |
| learnings (Osiris) | 8 | 8 | Yes |
| title_insights | 9 | 9 | Yes |
| title_tests | 0 | 0 | Yes |
| autopilot_config | (new) | N/A | Created |

## Columns Added (Migration 004)

| Table | Columns Added | Details |
|-------|--------------|---------|
| videos | 26 | Pipeline state, storyboard, curiosity gap, performance snapshots |
| assets | 7 | Storyboard tracking, cost estimation |
| competitor_videos | 14 | Airtable sync fields, modeling tracking |
| learnings | 4 | Airtable record ID, detail, dates |
| **Total** | **51** | |

## Bugs Fixed

1. `image_model` renamed to `image_model_override` (matches backend route queries)
2. `modeled_at` column added to `competitor_videos` (autopilot launch endpoint)
3. `autopilot_config` table created (was only in migration 003, not schema.sql)
4. `learnings.source_videos` type normalized from JSONB to TEXT (matches sync script)
5. `learnings.airtable_record_id` UNIQUE constraint added (needed for upsert)

## Files Changed

- **Created:** `storyengine/backend/migrations/004_schema_parity.sql`
- **Updated:** `storyengine/schema.sql` (canonical reference)
- **Updated:** `storyengine/sync/airtable_sync.py` (26 video + 7 asset field mappings)

## Sync Verified

Full sync ran 2026-03-24 14:46 UTC with zero errors across all 8 tables.
