-- Migration 142 (D6-1): canonical per-video cast/set inputs — the fix
-- BOARD-PLANNER-ARCHITECTURE.md's "What is calculated, never invented"
-- section calls a prerequisite for the whole determinism build.
--
-- Two columns, both nullable, both additive, both drawn from BOARD-LAWS.md:
--
-- 1. video_characters.identity_tag (L6 — IDENTITY ONCE): a short LOCKED
--    identity tag, e.g. "Nyla (red jacket, undercut, mid-20s)". video_
--    characters.description already exists but is long free prose (up to
--    1000 chars) meant for the cast-sheet portrait prompt and the writer's
--    bible — the composer (_character_identity_line, coverage_to_app.py)
--    was truncating it to 60 chars with a word-boundary cut as a stand-in
--    for a real short tag, which risks an arbitrary mid-thought cut and is
--    not an authored fact. identity_tag is that authored fact: written
--    once (by the creator or a future one-time extraction pass, mirroring
--    how video_environments.props is authored once at approval — 115_
--    environment_props.sql), then read VERBATIM into the sheet composer's
--    CHARACTER block. NULL means "no canonical tag yet" — every consumer
--    falls back to today's truncated-description behavior, byte-identical
--    to before this column existed.
--
-- 2. video_environments.material_map (L20 — DEFINE THE SET'S MATERIAL MAP
--    ONCE): which surfaces of a set are solid and which are transparent,
--    and where the boundary runs, e.g. "the pod's outer wall is fully
--    transparent glass from floor to shoulder height; everything above
--    shoulder height and the interior partition wall are solid opaque
--    metal." Placed on video_environments, NOT videos, after reading both
--    L3 (LOCATION SCOPING — a set is defined and scoped PER LOCATION) and
--    L20 side by side: L20's "once, for the whole film" is about
--    AUTHORING CADENCE (never re-derive it per scene, the way the planner
--    LLM's [MATERIAL|...] line currently does — see coverage.py's
--    parse_material_map), not about there being exactly one set in a film.
--    A film with N locations has N material maps, each authored once and
--    reused by every scene shot in that location — exactly the same shape
--    as props (115) and the existing per-location [LOCSET|...] blocks (L3).
--    Putting it on videos would force one map to cover every location,
--    which is wrong the moment a film has more than one set (L3's own
--    provenance is about exactly this kind of accidental scene-wide
--    over-application). NULL means "no canonical map for this location" —
--    the composer falls back to the planner LLM's own [MATERIAL|...] line,
--    unchanged from today, until this field is authored.
--
-- Both columns are read-only from this migration's point of view — no
-- backfill, existing videos/environments/characters keep working exactly
-- as before with NULLs. Creator-editable via the existing PATCH
-- /api/videos/{id}/characters/{id} and /environments/{id} routes, extended
-- in the same commit (routes/characters.py, routes/environments.py).
--
-- Idempotent.

ALTER TABLE video_characters ADD COLUMN IF NOT EXISTS identity_tag TEXT;

COMMENT ON COLUMN video_characters.identity_tag IS
  'L6 (IDENTITY ONCE): short locked identity tag (2-4 words of wardrobe/build), authored once, injected verbatim into every board''s CHARACTER block — NULL falls back to a truncated video_characters.description, the prior behavior';

ALTER TABLE video_environments ADD COLUMN IF NOT EXISTS material_map TEXT;

COMMENT ON COLUMN video_environments.material_map IS
  'L20 (MATERIAL MAP): which surfaces of this ONE location are solid vs transparent and where the boundary runs, authored once per location (mirrors props, migration 115), injected verbatim and WINS over the planner LLM''s own [MATERIAL|...] line — NULL falls back to that LLM-derived line, the prior behavior';
