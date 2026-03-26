-- Migration 010: visual_styles + style_characters tables
-- Replaces hardcoded style selection with user-creatable styles
-- Characters now belong to a specific visual style, not global

-- =============================================
-- VISUAL STYLES (user-creatable + 4 defaults)
-- =============================================

CREATE TABLE IF NOT EXISTS visual_styles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE NOT NULL,

  name TEXT NOT NULL,
  style_profile JSONB NOT NULL,
  reference_image_url TEXT,
  is_active BOOLEAN DEFAULT false,
  is_default BOOLEAN DEFAULT false,

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_visual_styles_project ON visual_styles(project_id);
CREATE INDEX IF NOT EXISTS idx_visual_styles_active ON visual_styles(project_id, is_active) WHERE is_active = true;

ALTER TABLE visual_styles ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'visual_styles' AND policyname = 'Project owner access'
  ) THEN
    CREATE POLICY "Project owner access" ON visual_styles FOR ALL TO authenticated
      USING (project_id IN (
        SELECT p.id FROM projects p
        WHERE p.account_id = (SELECT auth.uid())
           OR p.tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid()))
      ));
  END IF;
END $$;

-- =============================================
-- STYLE CHARACTERS (belong to a visual style)
-- =============================================

CREATE TABLE IF NOT EXISTS style_characters (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  visual_style_id UUID REFERENCES visual_styles(id) ON DELETE CASCADE NOT NULL,

  name TEXT NOT NULL,
  image_url TEXT NOT NULL,
  sort_order INTEGER DEFAULT 0,

  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_style_characters_style ON style_characters(visual_style_id);

ALTER TABLE style_characters ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'style_characters' AND policyname = 'Style owner access'
  ) THEN
    CREATE POLICY "Style owner access" ON style_characters FOR ALL TO authenticated
      USING (visual_style_id IN (
        SELECT vs.id FROM visual_styles vs
        JOIN projects p ON vs.project_id = p.id
        WHERE p.account_id = (SELECT auth.uid())
           OR p.tenant_id IN (SELECT m.tenant_id FROM memberships m WHERE m.user_id = (SELECT auth.uid()))
      ));
  END IF;
END $$;

-- =============================================
-- SEED: 4 default styles for all existing projects
-- =============================================

DO $$
DECLARE
  _project_id UUID;
BEGIN
  FOR _project_id IN SELECT id FROM projects
  LOOP
    -- Only seed if no styles exist yet for this project
    IF NOT EXISTS (SELECT 1 FROM visual_styles WHERE project_id = _project_id) THEN

      -- 1. Cinematic Illustration (active by default)
      INSERT INTO visual_styles (project_id, name, style_profile, is_active, is_default)
      VALUES (
        _project_id,
        'Cinematic Illustration',
        '{"mood": "Dramatic, editorial", "lighting": "Rembrandt with warm fill, dramatic shadows", "composition": "Rule of thirds, subject left", "texture": "Film grain 15%, vignette", "color_palette": {"primary": "#1A1A2E", "secondary": "#0F3460", "accent": "#E94560", "highlight": "#F0C75E"}, "keywords": ["Editorial", "Dramatic Lighting", "Photorealistic"]}'::jsonb,
        true,
        true
      );

      -- 2. Holographic HUD
      INSERT INTO visual_styles (project_id, name, style_profile, is_active, is_default)
      VALUES (
        _project_id,
        'Holographic HUD',
        '{"mood": "Tactical, high-tech", "lighting": "Ambient neon glow, no directional source", "composition": "Centered data displays, layered depth", "texture": "Clean digital, scanline overlay", "color_palette": {"primary": "#0A0A1A", "secondary": "#00D4AA", "accent": "#FF3366", "highlight": "#00FFFF"}, "keywords": ["Neon", "Data Overlay", "Sci-fi"]}'::jsonb,
        false,
        true
      );

      -- 3. Cinematic Dossier
      INSERT INTO visual_styles (project_id, name, style_profile, is_active, is_default)
      VALUES (
        _project_id,
        'Cinematic Dossier',
        '{"mood": "Classified, archival", "lighting": "Warm desk lamp, scattered shadows", "composition": "Overhead document spread, layered papers", "texture": "Aged paper, coffee stains, redaction marks", "color_palette": {"primary": "#2C1810", "secondary": "#8B7355", "accent": "#CC0000", "highlight": "#D4A574"}, "keywords": ["Documents", "Stamps", "Intelligence Briefing"]}'::jsonb,
        false,
        true
      );

      -- 4. Clay Mannequin
      INSERT INTO visual_styles (project_id, name, style_profile, is_active, is_default)
      VALUES (
        _project_id,
        'Clay Mannequin',
        '{"mood": "Minimal, uncanny", "lighting": "Soft studio, even diffusion", "composition": "Character-centered, shallow depth of field", "texture": "Matte clay surface, smooth gradients", "color_palette": {"primary": "#E8E0D8", "secondary": "#B0A090", "accent": "#FFB347", "highlight": "#FFFFFF"}, "keywords": ["3D", "Faceless", "Minimalist"]}'::jsonb,
        false,
        true
      );

    END IF;
  END LOOP;
END $$;
