-- Migration 151 (D9-2): harvest CharacterLock-grade fields from the dormant
-- Custom Film system into the flagship's cast. Custom Film's CharacterLock
-- (backend/custom_film_director.py:147-161) proved a character description
-- needs to split into narrower, more BINDING facts than one prose blob:
-- face_body_lock (immutable facial/body facts), wardrobe_lock (the exact
-- outfit), and forbidden_drift (named failure modes to avoid). This
-- migration adds the same three concepts to video_characters — nullable,
-- additive, mirrors migration 142's identity_tag/material_map shape
-- exactly: NULL means "not authored yet", every existing row and every
-- existing consumer keeps working byte-identical until these are
-- populated.
--
-- Populated at cast-approval time (routes/characters.py's approve_cast),
-- extending the SAME vision call that already rewrites `description` from
-- the approved portrait pixels — ONE paid call, not two. A parse failure on
-- any of the three leaves that column untouched (NULL on a first approval)
-- and logs a warning; it never fails the approval.
--
-- face_body_lock and wardrobe_lock are consumed VERBATIM (same precedence
-- philosophy as identity_tag/material_map, migration 142) by
-- load_character_bible (scripts/coverage_to_app.py) and by
-- redraw_asset_image's inline CHARACTER-block composer, taking precedence
-- over the free-prose `description`'s corresponding aspects whenever
-- populated — but NOT over a creator-authored identity_tag, which still
-- wins when set (a deliberate manual correction outranks an automated
-- vision extraction).
--
-- forbidden_drift is STORED ONLY by this migration — it is not yet read by
-- any prompt or the frame arbiter (that wiring is a separate chunk, D9-4).
--
-- Idempotent.

ALTER TABLE video_characters ADD COLUMN IF NOT EXISTS face_body_lock TEXT;
ALTER TABLE video_characters ADD COLUMN IF NOT EXISTS wardrobe_lock TEXT;
ALTER TABLE video_characters ADD COLUMN IF NOT EXISTS forbidden_drift TEXT;

COMMENT ON COLUMN video_characters.face_body_lock IS
  'D9-2: immutable facial/body facts (hair color+style, skin tone, build, marks), extracted from the approved portrait pixels at cast-approval time -- mirrors Custom Film''s CharacterLock.face_body_lock (custom_film_director.py:147-161). Read VERBATIM into board/final-picture CHARACTER blocks, taking precedence over description''s corresponding aspects, but never over a creator-set identity_tag. NULL = not yet extracted, falls back to identity_tag/description exactly as before this column existed.';

COMMENT ON COLUMN video_characters.wardrobe_lock IS
  'D9-2: the exact outfit visible in the approved portrait (every garment + color + accessories), extracted at cast-approval time -- mirrors Custom Film''s CharacterLock.wardrobe_lock. Same VERBATIM/precedence contract as face_body_lock.';

COMMENT ON COLUMN video_characters.forbidden_drift IS
  'D9-2: newline- or semicolon-separated list of specific ways this character could visibly drift across redraws (e.g. "hair changes color; loses the scar"), extracted at cast-approval time -- mirrors Custom Film''s CharacterLock.forbidden_drift. STORED ONLY by this migration; not yet consumed by any prompt or the frame arbiter (D9-4 wires that in).';
