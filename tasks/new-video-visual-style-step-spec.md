# Spec — New Video "Visual style" step (unified picker)

**Date:** 2026-06-17 · **Status:** design approved, ready for implementation plan
**Builds on:** the engine/identity Phase 4 + 4b visual work (see
`tasks/engine-identity-split-plan.md`). Those already make image generation read the
look from `videos.image_style_override` (per-video, wins) → the channel's active
`visual_styles` row → `channel_profiles.style_description` → neutral default. THIS
spec is the front-of-house: how a creator picks that look when making a video.

---

## 1. Goal

On the New Video page, replace today's **two competing style controls** with **one
clear "Visual style" step**: either use the style of a referenced YouTube video, or
pick a common preset, or describe your own — applied to that video, with an optional
checkbox to lock it in as the channel's identity. Plain-language, non-designer
friendly.

## 2. Decisions (from brainstorming, all confirmed by Ryan)

1. **Scope:** the pick applies to **that one video**, with a **"Lock this in as
   <channel>'s identity" checkbox on the form** to also make it the channel default.
2. **Menu shape:** **presets + "Describe your own"** (free text), plus "use this
   video's style" when a reference is provided.
3. **Thumbnail:** **separate** — this step sets the SCENE-IMAGE look only. The
   thumbnail keeps its own look (`thumbnail_style_override`); the clone still captures
   the source's thumbnail look. No thumbnail-style picker in this step.
4. **Visual Styles page:** **kept as the style library** (saved/reusable styles +
   character references + the channel's locked-in/active identity). "Lock in" from
   New Video creates/activates an entry there.
5. **Approach:** **hybrid** — presets live in the form (no library seeding required);
   "lock in" *promotes* the chosen look into a `visual_styles` row.

## 3. Current state (what we're replacing)

In `storyengine/frontend/src/app/pipeline/page.tsx`, the New Video form has TWO
controls that can conflict:
- **"Copy a video's style" box** (`newReferenceUrl` → `reference_url`, ~line 1231) —
  triggers the clone/modeling flow (`model_video.py`), which writes
  `videos.image_style_override` + `thumbnail_style_override` in a background task.
- **4-preset "Visual Style" picker** (`newVisualStyle` → `visual_style`, ~line 1394) —
  the Power-Doctrine-era profile IDs (`cinematic_illustration`, `holographic_hud`,
  `cinematic_dossier`, `clay_mannequin`). These are PROFILE ids (the engine), not
  looks, and are confusing next to the clone box.

Create payload today (`page.tsx` ~497, `models.py:164 CreateVideoRequest`):
`visual_style`, `accent_color`, `aspect_ratio`, `skip_voice`, `pipeline_stages`,
`reference_url`, … . The INSERT (`routes/videos.py:240`) writes `visual_style` but
**not** `image_style_override` (only the clone sets that, later).

## 4. The unified "Visual style" step (UX)

A single-choice step (radio semantics — exactly one source wins):

```
 Visual style
 ┌─────────────────────────────────────────────┐
 │ ◉ Use this video's style                     │  ← shown ONLY when a reference
 │   from the YouTube link above                │     URL is present; auto-selected
 ├─────────────────────────────────────────────┤     when a reference is pasted
 │ Pick a style                                 │
 │ ○ Pixar 3D  ○ 2D flat  ○ Realistic           │
 │ ○ Anime     ○ Watercolor ○ Comic             │  ← one-click presets
 ├─────────────────────────────────────────────┤
 │ ○ Describe your own…                         │
 │   [ gritty noir comic, muted palette______ ] │  ← free text (enables on focus)
 └─────────────────────────────────────────────┘
 ☐ Lock this in as <channel>'s identity
```

**States & rules:**
- **Reference present:** "Use this video's style" appears and is the default
  selection. Picking a preset / custom instead is allowed (overrides the clone look
  for scene images; the clone still copies the thumbnail look + script/etc per the
  stage toggles).
- **No reference:** the "Use this video's style" row is hidden; presets + custom show.
- **Nothing selected:** allowed → the video inherits the channel's locked-in identity,
  else neutral (backend already resolves this). Show subtle helper text:
  "Leave blank to use <channel>'s current style."
- **One source wins.** Selecting a preset clears the custom box and vice-versa;
  selecting "use this video's style" clears preset/custom.
- **Lock-in checkbox:** label shows the channel name; only meaningful when a concrete
  look is chosen (preset/custom, or the clone once modeled — see §7 deferral).

## 5. Presets (frontend constant; edit freely)

Each preset = friendly `label` + hidden `look` sentence (front-loaded into every
image prompt). Starter set (approved as a good base):

| id | label | look sentence |
|----|-------|---------------|
| `pixar_3d`   | Pixar 3D    | Soft 3D Pixar-style CG, rounded forms, warm cinematic light, subsurface skin, shallow depth of field |
| `flat_2d`    | 2D flat     | Clean 2D flat vector animation, bold flat colors, simple shapes, crisp outlines, minimal shading |
| `realistic`  | Realistic   | Photorealistic cinematic photography, natural lighting, real textures, shallow depth of field |
| `anime`      | Anime       | Modern anime cel-shaded illustration, expressive faces, clean linework, soft gradient shading |
| `watercolor` | Watercolor  | Warm hand-painted watercolor storybook art, soft edges, textured paper, gentle palette |
| `comic`      | Comic       | Bold graphic-novel illustration, inked outlines, halftone shading, dynamic high-contrast color |

Single source of truth: one `VISUAL_PRESETS` constant in the frontend. (Looks are
plain text; if we later want them server-validated, lift the constant to the backend —
out of scope now.)

## 6. Data model & flow

No new tables. Three existing stores, each already read by generation:
- **`videos.image_style_override`** (free text) — the per-video scene look. The pick
  writes here: preset → its `look`; custom → the typed text; "use this video's style"
  → left empty at create (the clone fills it in its background task). **Wins over
  everything** (Phase 4).
- **`visual_styles`** active row (per project) — the channel identity. "Lock in"
  upserts + activates a row here (Phase 4b reads it for future non-cloned videos).
- **`videos.visual_style`** (profile id) — stays the neutral engine (`neutral_v1`),
  set server-side; NOT a look. The old 4-profile picker is removed.

Resolution at generation (unchanged, already shipped):
`image_style_override` → active `visual_styles` look → `channel_profiles.style_description`
→ neutral default.

## 7. Backend changes

**`models.py` `CreateVideoRequest`:** add
- `image_style_override: Optional[str] = None` — the chosen scene look (preset look or
  custom text). Omitted/None for the "use this video's style" (clone) mode.
- `lock_in_identity: bool = False`
- `visual_style_label: Optional[str] = None` — friendly name for the locked-in library
  entry (e.g. "Pixar 3D", "Custom", or "Cloned from <title>"). Optional cosmetic.

**`routes/videos.py` `create_video`:**
- Add `image_style_override` to the INSERT column list + value (trim → None if blank).
- Keep `visual_style` defaulting to the neutral engine (do NOT send PD profile ids
  from the form anymore; the form stops sending `visual_style`).
- After insert, if `lock_in_identity` AND a concrete look is present (preset/custom):
  call a shared helper `upsert_active_visual_style(project_id, label, look)`.
  - For the **clone mode** + lock-in: the look isn't known until the background
    modeling finishes, so pass the lock-in intent into `_run_modeling`; persist the
    active style when `_persist_pack` / `_persist_style_overrides` writes
    `image_style_override`. (If this proves fiddly, ship lock-in for preset/custom
    first and treat clone-lock-in as a fast follow — call it out in the plan.)

**New shared helper `upsert_active_visual_style(project_id, name, look)`** (in
`routes/visual_styles.py`, importable by `videos.py`/`model_video.py`):
- Deactivate other styles for the project (`is_active=false`).
- Upsert a row `{name, style_profile: {"prompt_prefix": look}, is_active: true}`.
  Match on `name` per project to avoid duplicates on repeat lock-ins; else insert.
- Mirrors the existing `activate_visual_style` deactivation logic.

**No change needed** to `identity.py` / `prompt_builder.py` / `pipeline_executor.py` —
Phase 4/4b already read `image_style_override` and the active `visual_styles` row.

## 8. Frontend changes (`pipeline/page.tsx`)

- Replace the standalone 4-preset "Visual Style" picker block (~1388-1417) and fold
  the "Copy a video's style" box (~1231) into the unified step described in §4.
- State: a small reducer/object, e.g.
  `styleChoice = { mode: 'reference' | 'preset' | 'custom' | 'none', presetId?, customText? }`.
  Keep `newReferenceUrl` as the reference source; `mode:'reference'` requires it.
- `VISUAL_PRESETS` constant (id/label/look) from §5.
- New state `lockInIdentity: boolean`.
- On submit (~497), compute and send:
  - `reference_url`: as today (still drives the clone when mode='reference').
  - `image_style_override`: preset `look` (mode='preset') | `customText` (mode='custom')
    | omitted (mode='reference' or 'none').
  - `lock_in_identity`: `lockInIdentity`.
  - `visual_style_label`: preset label | "Custom" | undefined.
  - Stop sending `visual_style` (the PD profile id).
- Channel name for the labels/helper text comes from existing project/profile data
  already loaded on the page (fallback "this channel").
- Verify with `tsc --noEmit` + `next build` (local preview can't reach authed pages —
  see `[[storyengine-local-preview-auth]]`; no browser check).

## 9. What's removed / replaced
- The 4 hardcoded profile-id style buttons (`cinematic_illustration` etc.) leave the
  New Video form. (`cinematic_illustration` etc. remain loadable engine presets in the
  skill registry — not surfaced here.)
- The separate "Copy a video's style" box is absorbed into the unified step as the
  "Use this video's style" option.
- The Visual Styles page is unchanged (kept as the library).

## 10. Edge cases
- **Reference pasted, then a preset chosen:** scene images use the preset look
  (`image_style_override` set explicitly); the clone still copies thumbnail/script per
  the stage toggles. Documented in helper text.
- **Nothing chosen, no channel identity:** neutral default (already handled).
- **Lock-in with clone mode:** deferred to modeling completion (§7); never blocks
  create. If modeling fails, no library entry is created (no half-state).
- **Repeat lock-in of the same label:** upsert by name → no duplicate rows.
- **Empty/whitespace custom text:** treated as "none".

## 11. Testing / verification (per this repo's real workflow)
The project verifies prompts by **regenerate-and-inspect on prod**, not pytest (see
`engine-identity-split-plan.md` intro). So:
- **Backend unit tests** (pure logic only): `create_video` writes `image_style_override`
  for preset/custom; `upsert_active_visual_style` deactivates others + activates the new
  row + dedups by name; `lock_in_identity=false` writes no library row.
- **Prompt effect (manual / prod):** create a video with "Pixar 3D" → confirm the image
  prompts front-load the Pixar look (reuse the Phase-4 identity/prompt-builder check).
  Create with "Describe your own" → confirm the typed look appears. Lock in → confirm
  the Visual Styles page shows it active and the NEXT non-cloned video inherits it.
- **Frontend:** `tsc --noEmit` + `next build` green; the form sends the new payload
  (inspect network / a unit test of the submit mapper if practical).
- **Deploy:** backend = pull + restart (kill `[u]vicorn`, systemd revives); frontend =
  **`npm run build` THEN restart** `storyengine-frontend` (it serves the prebuilt
  `.next`; a restart without build serves the old bundle — see `[[storyengine-vps-access]]`).

## 12. Out of scope (explicit)
- Phase 5 (clone seeds the VOICE/creator-direction).
- A thumbnail-style picker (thumbnail stays separate/default).
- Server-side preset validation / migrating the existing 4 seeded library styles.
- Character-reference management changes on the Visual Styles page.

## 13. Definition of done
On the New Video page a creator can, in one step: use the referenced video's style,
pick a common preset, or type their own — applied to that video — with a checkbox to
lock it in as the channel's identity. The old 4-profile picker and the standalone
copy-style box are gone. A preset/custom pick lands in `videos.image_style_override`
and shows up in the generated image prompts; "lock in" creates/activates a
`visual_styles` row that future non-cloned videos inherit. Frontend builds clean;
backend unit tests green; deployed (backend + rebuilt frontend); proven by creating a
video in a chosen style and inspecting the prompts.
