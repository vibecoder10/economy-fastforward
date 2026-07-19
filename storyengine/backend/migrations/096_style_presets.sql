-- STYLE_PRESETS (checklist §2.1 [D]+[B], chunk C20 — "5 rich Python visual
-- profiles invisible to users; UI shows only 6 shallow hardcoded presets").
--
-- This is the catalog for the VISUAL_PROFILE axis — the structural image-
-- engine choice (shared.profiles.visual/*.py: scene-type variety, camera/
-- composition cycling, anti-clustering rules). `id` is the profile MODULE
-- NAME (shared.profiles.visual._PROFILE_MODULES key), so a valid row id is
-- always a value load_profile() already knows how to resolve — no separate
-- id scheme to keep in sync.
--
-- NOT the same axis as `visual_styles` (migration 010) or the frontend's
-- hardcoded VISUAL_PRESETS (pixar_3d/flat_2d/realistic/anime/watercolor/
-- comic) — those feed VISUAL_STYLE_DESCRIPTION, a free-text aesthetic
-- overlay (image_style_override), a DIFFERENT env seam from VISUAL_PROFILE.
-- See docs/reports/2026-07-17-storyengine-agent-audit-findings.md §S9-5 and
-- SYSTEM_STATE.md §C20 for the full reconciliation note (left for C21).
--
-- Idempotent (CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS) —
-- applied LIVE via the Supabase MCP against project wrromlupsmyzrrcqlucn,
-- confirmed via information_schema (same pattern as migrations 088-095).
--
-- RLS: enabled, NO policies (playbook §7 pattern — the backend connects as
-- the `postgres` role, BYPASSRLS, proven safe already for generation_claims/
-- director_preferences/generation_passes etc.). This is a GLOBAL catalog
-- (not tenant data), so there is no tenant-scoped policy to write anyway;
-- GET /api/style-presets mirrors GET /api/models's auth posture (any
-- authenticated tenant may read the shared catalog).

CREATE TABLE IF NOT EXISTS style_presets (
  id TEXT PRIMARY KEY,                 -- shared.profiles.visual module name
  display_name TEXT NOT NULL,
  description TEXT,
  tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  best_for JSONB NOT NULL DEFAULT '[]'::jsonb,
  cost_tier TEXT,                       -- 'low' | 'mid' | 'high' (TemplateMetadata's own vocabulary)
  preview_url TEXT,                     -- NULL for python_profile seeds — no static preview image exists yet
  source TEXT NOT NULL DEFAULT 'python_profile',
  sort INT NOT NULL DEFAULT 0,
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE style_presets ENABLE ROW LEVEL SECURITY;
-- No policies (deny-all to anon/authenticated/PostgREST); backend bypasses
-- via table ownership + BYPASSRLS (see migration 083 for the proof).

-- Seed: the 5 real profiles in shared.profiles.visual._PROFILE_MODULES
-- (excludes the "mannequin_storytelling" legacy ALIAS, which maps to the
-- same cinematic_illustration module — not a distinct 6th profile). Every
-- field below is copied verbatim from each module's TemplateMetadata
-- (display_name/tags/description/best_for/cost_tier) — NOT invented copy.
-- `sort` follows _PROFILE_MODULES's own declaration order (no subjective
-- ranking introduced).
--
-- ON CONFLICT DO UPDATE refreshes only the CODE-DERIVED columns (display_
-- name/description/tags/best_for/cost_tier/sort/source/updated_at) so a
-- re-run after fixing a typo in this seed — or a future re-application —
-- keeps the catalog text in sync with the Python source of truth. `active`
-- and `preview_url` are deliberately left OUT of the SET clause: those are
-- the two fields C21+ may let an admin mutate (deactivate a preset / attach
-- a generated preview image), and a reseed must never silently reactivate a
-- disabled preset or wipe a manually-set preview.
INSERT INTO style_presets (id, display_name, description, tags, best_for, cost_tier, source, sort, active)
VALUES
  ('neutral_v1', 'Neutral Documentary (default)',
   'The style-agnostic default. Keeps the full image craft (scene-type variety, expressive characters, specific environments, anti-repetition rotation) but takes its actual look from your channel''s visual style — so prompts come out in YOUR aesthetic, for any niche.',
   '["neutral","documentary","default","any-niche","storytelling","characters","flexible"]'::jsonb,
   '["any niche","education","explainers","documentary","how-to"]'::jsonb,
   'low', 'python_profile', 0, true),

  ('holographic_hud', 'Holographic Intelligence Display',
   'Dark high-security intelligence operations center with holographic projections. War room meets Bloomberg Terminal meets Minority Report. Zero human figures — every frame is pure analytical data visualization. 8 content types, 5 display formats, 6 color moods create infinite visual variety. Best for: geopolitics, military analysis, economic data, investigative journalism.',
   '["dark","holographic","data","intelligence","geopolitics","military","HUD"]'::jsonb,
   '["geopolitics","military analysis","economic data","investigative journalism"]'::jsonb,
   'low', 'python_profile', 1, true),

  ('cinematic_dossier', 'Cinematic Intelligence Briefing',
   'Dark, moody photorealistic stills with Rembrandt lighting. Three visual substyles (Dossier, Schema, Echo) create a documentary thriller aesthetic. Anonymous human figures with obscured faces convey emotion through body language. Best for: geopolitics, finance, corporate power, historical analysis.',
   '["dark","cinematic","geopolitics","finance","thriller","documentary","Rembrandt"]'::jsonb,
   '["geopolitics","finance","corporate power","historical analysis"]'::jsonb,
   'mid', 'python_profile', 2, true),

  ('clay_mannequin', 'Clay Mannequin Dioramas',
   '3D editorial conceptual renders using faceless matte ceramic mannequin figures in department store diorama compositions. A warm golden protagonist glow tracks narrative emotion. Mixed material contrasts create tactile, three-dimensional storytelling. Best for: explainers, personal finance, social commentary, philosophical content.',
   '["3D","clay","mannequin","diorama","conceptual","editorial","warm"]'::jsonb,
   '["explainers","personal finance","social commentary","philosophy"]'::jsonb,
   'mid', 'python_profile', 3, true),

  ('cinematic_illustration', 'Cinematic Animated Illustration',
   'Cinematic 2D animated illustration. Muted earthy palette with ink outlines. Characters have expressive illustrated faces with angular features. Period-appropriate clothing. 5 scene types. Best for: geopolitics, military analysis, proxy wars, economic power, intelligence operations.',
   '["illustration","animated","documentary","geopolitics","storytelling","cinematic","narrative","war","finance","expressive"]'::jsonb,
   '["geopolitics","military analysis","proxy wars","economic power","intelligence operations"]'::jsonb,
   'low', 'python_profile', 4, true)
ON CONFLICT (id) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  description = EXCLUDED.description,
  tags = EXCLUDED.tags,
  best_for = EXCLUDED.best_for,
  cost_tier = EXCLUDED.cost_tier,
  source = EXCLUDED.source,
  sort = EXCLUDED.sort,
  updated_at = now();

-- videos.style_preset_id (checklist §2.1 [B] — create_video accepts an
-- optional style_preset_id, validated against style_presets, and the
-- executor's VISUAL_PROFILE seam prefers it over the legacy free-text
-- `visual_style` column when set). ON DELETE SET NULL: a video's chosen
-- preset is a soft reference, never a reason to block a (currently
-- unbuilt) catalog-row delete.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS style_preset_id TEXT REFERENCES style_presets(id) ON DELETE SET NULL;
