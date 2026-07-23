-- Public production styles: the high-level video pipeline shape.
--
-- This is deliberately distinct from style_presets/visual_styles, which cover
-- image-engine and aesthetic axes. Catalog rows are global system data. A
-- selected row is snapshotted onto videos so profile updates apply to new work
-- without mutating existing productions.
CREATE TABLE IF NOT EXISTS production_style_profiles (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    label TEXT NOT NULL,
    description TEXT NOT NULL,
    knobs JSONB NOT NULL,
    estimate JSONB NOT NULL DEFAULT '{}'::jsonb,
    requires_byok BOOLEAN NOT NULL DEFAULT TRUE CHECK (requires_byok),
    public BOOLEAN NOT NULL DEFAULT TRUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE production_style_profiles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON production_style_profiles FROM anon;
REVOKE ALL ON production_style_profiles FROM authenticated;

ALTER TABLE videos
    ADD COLUMN IF NOT EXISTS production_style_id TEXT,
    ADD COLUMN IF NOT EXISTS production_style_version INTEGER,
    ADD COLUMN IF NOT EXISTS production_style_snapshot JSONB;

ALTER TABLE channel_profiles
    ADD COLUMN IF NOT EXISTS production_style_id TEXT;

CREATE INDEX IF NOT EXISTS idx_videos_production_style
    ON videos (production_style_id)
    WHERE production_style_id IS NOT NULL;

-- Link every currently-recognized static-documentary channel to the public
-- profile without copying or exposing its private channel_identity JSON.
UPDATE channel_profiles
SET production_style_id = 'photo_documentary',
    updated_at = now()
WHERE production_style_id IS NULL
  AND (
    lower(COALESCE(channel_identity->'visual_format'->>'motion', '')) LIKE ANY
      (ARRAY['%static%', '%ken burns%', '%ken-burns%', '%still image%', '%photograph%'])
    OR lower(COALESCE(channel_identity->'visual_format'->>'style', '')) LIKE ANY
      (ARRAY['%static%', '%ken burns%', '%ken-burns%', '%still image%', '%photograph%'])
    OR lower(COALESCE(channel_identity->'visual_format'->>'segmentation', '')) LIKE ANY
      (ARRAY['%static%', '%ken burns%', '%ken-burns%', '%still image%', '%photograph%'])
  )
  AND lower(COALESCE(channel_identity->'visual_format'->>'motion', '')) NOT LIKE ALL
      (ARRAY['%animation%', '%animated%', '%3d render%', '%motion graphics heavy%']);

INSERT INTO production_style_profiles
    (id, version, label, description, knobs, estimate, requires_byok, public, sort)
VALUES
    (
      'bilingual_character_animation',
      1,
      'Bilingual Character Animation',
      'Animated character stories with dialogue in two languages and natural dubbed voices.',
      '{
        "render_mode": "coverage",
        "script_profile": "neutral_v1",
        "visual_profile": "neutral_v1",
        "image_density": {"mode": "dialogue_shape", "target_per_minute": 8},
        "animation": {"enabled": true, "mode": "grok_native"},
        "language": {"mode": "bilingual"},
        "dubbing": {"enabled": true, "mode": "speech_to_speech"},
        "segmentation": {"mode": "speaker_turn"},
        "camera": {"mode": "dialogue_coverage"},
        "quality_laws": ["character_continuity", "lip_sync", "translation_fidelity"],
        "image_source": "generate"
      }'::jsonb,
      '{"cost_tier":"high","image_count_mode":"duration","images_per_minute":8,"clips_per_image":1,"copy":"Animated images + clips + bilingual dubbing. You pay providers directly with your keys."}'::jsonb,
      TRUE,
      TRUE,
      10
    ),
    (
      'simple_language_animation',
      1,
      'Simple-Language Animation',
      'Simple-language animated stories built for learners and clear comprehension.',
      '{
        "render_mode": "coverage",
        "script_profile": "neutral_v1",
        "visual_profile": "neutral_v1",
        "image_density": {"mode": "dialogue_shape", "target_per_minute": 8},
        "animation": {"enabled": true, "mode": "grok_native"},
        "language": {"mode": "simple_single_language"},
        "dubbing": {"enabled": false, "mode": "none"},
        "segmentation": {"mode": "speaker_turn"},
        "camera": {"mode": "dialogue_coverage"},
        "quality_laws": ["character_continuity", "clear_language", "lip_sync"],
        "image_source": "generate"
      }'::jsonb,
      '{"cost_tier":"medium","image_count_mode":"duration","images_per_minute":8,"clips_per_image":1,"copy":"Animated images + clips in one clear language. You pay providers directly with your keys."}'::jsonb,
      TRUE,
      TRUE,
      20
    ),
    (
      'photo_documentary',
      1,
      'Photo Documentary',
      'Item-by-item narration using still images, captions, and slow cinematic pan-and-zoom.',
      '{
        "render_mode": "static_docu",
        "script_profile": "neutral_v1",
        "visual_profile": "neutral_v1",
        "image_density": {"mode": "per_item", "target": 3, "minimum": 2},
        "animation": {"enabled": false, "mode": "ken_burns"},
        "language": {"mode": "narrator"},
        "dubbing": {"enabled": false, "mode": "none"},
        "segmentation": {"mode": "item"},
        "camera": {"mode": "three_complementary_views"},
        "quality_laws": ["verified_reference", "variant_accuracy", "caption_grounding"],
        "image_source": "generate"
      }'::jsonb,
      '{"cost_tier":"low","image_count_mode":"per_item","images_per_item":3,"clips_per_image":0,"copy":"Three still images per item, no generated animation clips. You pay providers directly with your keys."}'::jsonb,
      TRUE,
      TRUE,
      30
    ),
    (
      'animated_investigative_documentary',
      1,
      'Animated Investigative Documentary',
      'Investigative narration with a fresh animated visual for nearly every sentence or visual cue.',
      '{
        "render_mode": "coverage",
        "script_profile": "power_doctrine_v2",
        "visual_profile": "cinematic_illustration",
        "image_density": {"mode": "visual_cue", "target_per_minute": 10},
        "animation": {"enabled": true, "mode": "grok_native"},
        "language": {"mode": "narrator"},
        "dubbing": {"enabled": false, "mode": "none"},
        "segmentation": {"mode": "visual_cue"},
        "camera": {"mode": "investigative_coverage"},
        "quality_laws": ["source_grounding", "visual_cue_fidelity", "motion_prompt_presence"],
        "image_source": "generate"
      }'::jsonb,
      '{"cost_tier":"highest","image_count_mode":"duration","images_per_minute":10,"clips_per_image":1,"copy":"About one image and clip per meaningful visual cue. You pay providers directly with your keys."}'::jsonb,
      TRUE,
      TRUE,
      40
    )
ON CONFLICT (id) DO UPDATE SET
    version = EXCLUDED.version,
    label = EXCLUDED.label,
    description = EXCLUDED.description,
    knobs = EXCLUDED.knobs,
    estimate = EXCLUDED.estimate,
    requires_byok = EXCLUDED.requires_byok,
    public = EXCLUDED.public,
    sort = EXCLUDED.sort,
    updated_at = now();
