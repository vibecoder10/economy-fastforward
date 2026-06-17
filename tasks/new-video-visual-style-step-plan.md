# New Video "Visual style" step — Implementation Plan

> **For agentic workers:** Use the subagent-driven or executing-plans workflow to implement this task-by-task. Steps use checkbox (`- [ ]`) syntax. Spec: `tasks/new-video-visual-style-step-spec.md`.

**Goal:** Replace the New Video page's two clashing style controls (the "Copy a video's style" box + the 4 profile-id buttons) with ONE "Visual style" step — use this video's style / a preset (with preview icon) / describe your own — applied per-video, with a "Lock in as channel identity" checkbox.

**Architecture:** The choice writes a free-text look to `videos.image_style_override` (the generator already front-loads it — Phase 4/4b, no gen-path changes). "Lock in" upserts + activates a `visual_styles` row (future non-cloned videos inherit it — Phase 4b). Clone mode fills `image_style_override` in its existing background task; lock-in there happens when that DNA is written.

**Tech Stack:** Python/FastAPI backend (`storyengine/backend`), Postgres (asyncpg), Next.js/React frontend (`storyengine/frontend`). Backend pure-logic tests = `pytest` (driven via `asyncio.run` in sync tests, monkeypatching the DB layer — mirror `tests/test_identity_context.py`). Frontend verification = `tsc --noEmit` + `next build` (authed pages can't be browser-checked — see `[[storyengine-local-preview-auth]]`).

**Conventions to respect:**
- DB access via `from database import fetch_one, fetch_all, execute` (asyncpg; JSONB columns come back as raw JSON STRINGS — `json.dumps` on write, `json.loads`/`_parse_jsonb` on read).
- The generation path is DONE; do NOT touch `identity.py` / `prompt_builder.py` / `pipeline_executor.py`.
- Commit after every green step.

---

## File structure

| File | Change | Responsibility |
|------|--------|----------------|
| `storyengine/backend/routes/visual_styles.py` | Modify | NEW `upsert_active_visual_style(project_id, name, look)` helper (importable) |
| `storyengine/backend/tests/test_visual_style_upsert.py` | Create | Unit tests for the helper |
| `storyengine/backend/models.py` | Modify | `CreateVideoRequest`: add `image_style_override`, `lock_in_identity`, `visual_style_label` |
| `storyengine/backend/routes/videos.py` | Modify | `create_video`: persist `image_style_override`; lock-in for preset/custom; thread lock-in into clone modeling |
| `storyengine/backend/routes/model_video.py` | Modify | `_run_modeling` + `_persist_pack`/`_persist_style_overrides`: lock-in the cloned look |
| `storyengine/backend/tests/test_create_video_style.py` | Create | Unit tests for the create-path style logic |
| `storyengine/frontend/src/lib/api.ts` | Modify | `createVideo` payload type: new fields |
| `storyengine/frontend/src/app/pipeline/page.tsx` | Modify | The unified "Visual style" step + `VISUAL_PRESETS` + state + payload |
| `storyengine/frontend/public/style-icons/*.png` | Create (asset) | 6 preset preview icons (Ryan provides) |

---

## Task 1: `upsert_active_visual_style` helper (backend)

**Files:**
- Modify: `storyengine/backend/routes/visual_styles.py`
- Test: `storyengine/backend/tests/test_visual_style_upsert.py`

The helper makes a chosen look the project's active library style. There is **no
unique constraint on `(project_id, name)`** (migration 010 — only the `id` PK), so it
is an explicit SELECT → UPDATE-or-INSERT (dedup by name), then activate (mirrors
`activate_visual_style`'s deactivate-all-then-activate-one at lines 425-450). `execute`
runs `INSERT/UPDATE`; `fetch_one` runs the SELECT.

- [ ] **Step 1: Write the failing test**

```python
# storyengine/backend/tests/test_visual_style_upsert.py
"""Unit tests for upsert_active_visual_style (no real DB — the asyncpg layer is
stubbed). Mirrors the monkeypatch style of test_identity_context.py."""
import asyncio
import json
import importlib


def _load(monkeypatch, existing_row):
    """Import the module and stub its DB calls; return (module, calls)."""
    mod = importlib.import_module("routes.visual_styles")
    calls = {"execute": [], "fetch_one": []}

    async def fake_fetch_one(query, *args):
        calls["fetch_one"].append((query, args))
        if "SELECT id FROM visual_styles" in query and "name" in query:
            return existing_row  # None = no match, dict = match
        return None

    async def fake_execute(query, *args):
        calls["execute"].append((query, args))
        return None

    monkeypatch.setattr(mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(mod, "execute", fake_execute)
    return mod, calls


def test_inserts_and_activates_when_absent(monkeypatch):
    mod, calls = _load(monkeypatch, existing_row=None)
    asyncio.run(mod.upsert_active_visual_style("proj-1", "Pixar 3D", "soft 3D Pixar CG"))
    qs = " ".join(q for q, _ in calls["execute"])
    # deactivates others, then INSERTs a new active row
    assert "is_active = false" in qs
    assert "INSERT INTO visual_styles" in qs
    # style_profile carries the look under prompt_prefix
    insert_args = [a for q, a in calls["execute"] if "INSERT" in q][0]
    assert any("soft 3D Pixar CG" in json.dumps(a) for a in insert_args)


def test_updates_existing_same_name(monkeypatch):
    mod, calls = _load(monkeypatch, existing_row={"id": "style-9"})
    asyncio.run(mod.upsert_active_visual_style("proj-1", "Pixar 3D", "new look"))
    qs = " ".join(q for q, _ in calls["execute"])
    assert "is_active = false" in qs
    assert "UPDATE visual_styles" in qs          # updated, not inserted
    assert "INSERT INTO visual_styles" not in qs


def test_blank_look_is_noop(monkeypatch):
    mod, calls = _load(monkeypatch, existing_row=None)
    asyncio.run(mod.upsert_active_visual_style("proj-1", "X", "   "))
    assert calls["execute"] == []                # nothing written for empty look
```

- [ ] **Step 2: Run it, verify it fails**

Run: `cd storyengine/backend && python3 -m pytest tests/test_visual_style_upsert.py -v`
Expected: FAIL — `AttributeError: module 'routes.visual_styles' has no attribute 'upsert_active_visual_style'`.

- [ ] **Step 3: Implement the helper**

Add to `storyengine/backend/routes/visual_styles.py` (top-level function, after the
imports / near the other helpers so `videos.py` and `model_video.py` can import it):

```python
async def upsert_active_visual_style(project_id: str, name: str, look: str) -> None:
    """Make `look` the project's ACTIVE library style under display name `name`.

    Dedups by (project_id, name) with an explicit SELECT → UPDATE-or-INSERT (no
    unique constraint exists to ON CONFLICT on). No-op when `look` is blank.
    Mirrors activate_visual_style: deactivate all, then activate the one row.
    """
    look = (look or "").strip()
    name = (name or "").strip() or "Custom style"
    if not look:
        return
    profile = json.dumps({"prompt_prefix": look})

    # Deactivate every style for this project first.
    await execute(
        "UPDATE visual_styles SET is_active = false, updated_at = now() WHERE project_id = $1",
        project_id,
    )
    existing = await fetch_one(
        "SELECT id FROM visual_styles WHERE project_id = $1 AND name = $2 LIMIT 1",
        project_id, name,
    )
    if existing:
        await execute(
            "UPDATE visual_styles SET style_profile = $1::jsonb, is_active = true, "
            "updated_at = now() WHERE id = $2",
            profile, str(existing["id"]),
        )
    else:
        await execute(
            "INSERT INTO visual_styles (project_id, name, style_profile, is_active, is_default) "
            "VALUES ($1, $2, $3::jsonb, true, false)",
            project_id, name, profile,
        )
```

(Confirm `execute` is imported at the top of the file — it already is: `from database import fetch_one, fetch_all, execute`.)

- [ ] **Step 4: Run tests, verify pass**

Run: `cd storyengine/backend && python3 -m pytest tests/test_visual_style_upsert.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add storyengine/backend/routes/visual_styles.py storyengine/backend/tests/test_visual_style_upsert.py
git commit -m "feat(visual-styles): upsert_active_visual_style helper (lock a look in as the active style)"
```

---

## Task 2: `CreateVideoRequest` new fields (backend)

**Files:**
- Modify: `storyengine/backend/models.py` (`CreateVideoRequest`, ~line 164)
- Test: `storyengine/backend/tests/test_create_video_style.py`

- [ ] **Step 1: Write the failing test**

```python
# storyengine/backend/tests/test_create_video_style.py
from models import CreateVideoRequest

def test_new_style_fields_default_safe():
    r = CreateVideoRequest(title="t")
    assert r.image_style_override is None
    assert r.lock_in_identity is False
    assert r.visual_style_label is None

def test_new_style_fields_accept_values():
    r = CreateVideoRequest(title="t", image_style_override="soft 3D Pixar CG",
                           lock_in_identity=True, visual_style_label="Pixar 3D")
    assert r.image_style_override == "soft 3D Pixar CG"
    assert r.lock_in_identity is True
    assert r.visual_style_label == "Pixar 3D"
```

- [ ] **Step 2: Run, verify fail** — `cd storyengine/backend && python3 -m pytest tests/test_create_video_style.py -v` → FAIL (unexpected kwargs).

- [ ] **Step 3: Implement** — in `models.py` `CreateVideoRequest`, add after `visual_style`:

```python
    # Free-text per-video scene LOOK (preset look sentence or the creator's own
    # words). Front-loaded into every image prompt; wins over channel/neutral.
    # Omitted for the clone ("use this video's style") and "none" choices.
    image_style_override: Optional[str] = None
    # When true, also save+activate this look as the channel's library identity
    # so future (non-cloned) videos inherit it.
    lock_in_identity: bool = False
    # Friendly name for the locked-in library entry ("Pixar 3D", "Custom", …).
    visual_style_label: Optional[str] = None
```

- [ ] **Step 4: Run, verify pass** — 2 passed.

- [ ] **Step 5: Commit**

```bash
git add storyengine/backend/models.py storyengine/backend/tests/test_create_video_style.py
git commit -m "feat(videos): CreateVideoRequest accepts image_style_override + lock_in_identity"
```

---

## Task 3: `create_video` persists the look + locks in (backend)

**Files:**
- Modify: `storyengine/backend/routes/videos.py` (`create_video`, INSERT ~line 240)

Two changes: (a) add `image_style_override` to the INSERT; (b) after insert, if
`lock_in_identity` and a concrete look is present (preset/custom path), call the helper.
The clone path (`is_modeled`) is handled in Task 4 (it has no look yet at create time).

- [ ] **Step 1: Add `image_style_override` to the INSERT.** Edit the INSERT (currently
  `routes/videos.py:240`):

```python
    style_override = (body.image_style_override or "").strip() or None
    row = await fetch_one(
        """INSERT INTO videos (tenant_id, project_id, video_title, status, source, framework_angle, video_length_minutes, writer_guidance, visual_style, image_style_override, accent_color, aspect_ratio, skip_voice, pipeline_stages, reference_url)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, COALESCE($11, '#00D4AA'), $12, $13, $14, $15)
           RETURNING id, video_title, status, thumbnail_url, accent_color, total_cost, views, ctr,
                     created_at::text, updated_at::text""",
        tenant_id, project_id, body.title.strip(), initial_status, source_val, body.framework_angle,
        body.video_length_minutes, body.writer_guidance, body.visual_style, style_override, body.accent_color,
        body.aspect_ratio, skip_voice, json.dumps(plan) if plan is not None else None, reference_url,
    )
```

(Note the new `image_style_override` column + `$10` placeholder, and every later
placeholder shifts by one — accent_color→`$11`, aspect_ratio→`$12`, skip_voice→`$13`,
pipeline_stages→`$14`, reference_url→`$15`. Double-check the count.)

- [ ] **Step 2: Lock-in for the preset/custom path.** Right after the INSERT returns
  `row` (and before the `is_modeled` background-task block), add:

```python
    # Lock the chosen look in as the channel identity (preset/custom path; the
    # clone path locks in later, when modeling writes the DNA — see model_video).
    if body.lock_in_identity and style_override and not is_modeled:
        try:
            from routes.visual_styles import upsert_active_visual_style
            await upsert_active_visual_style(
                project_id, (body.visual_style_label or "Custom style"), style_override,
            )
        except Exception as e:  # never block video creation on lock-in
            import logging
            logging.getLogger(__name__).warning("lock-in visual style failed: %s", e)
```

- [ ] **Step 3: Thread lock-in into the clone task.** In the `if is_modeled:` block,
  pass the lock-in intent + label into `_run_modeling` (Task 4 consumes them):

```python
        background_tasks.add_task(
            _run_modeling, tenant_id, str(row["id"]), reference_youtube_id,
            reference_url, plan, True,
            body.lock_in_identity,                      # NEW
        )
```

- [ ] **Step 4: Verify compile + existing tests.**

Run: `cd storyengine/backend && python3 -m py_compile routes/videos.py && python3 -m pytest tests/ -q -k "video or create or identity or visual_style"`
Expected: compiles; existing tests still pass (no regressions).

- [ ] **Step 5: Commit**

```bash
git add storyengine/backend/routes/videos.py
git commit -m "feat(videos): persist image_style_override + lock-in the chosen look on create"
```

---

## Task 4: Clone-mode lock-in (backend)

**Files:**
- Modify: `storyengine/backend/routes/model_video.py` (`_run_modeling` ~821, `_persist_style_overrides` ~608)

The clone's look only exists after modeling runs. The **New Video / Create-form** clone
path (`preserve_topic=True`) calls **`_persist_style_overrides`** — that's the one
required hook here. (`_persist_pack` is the standalone "Model A Video" flow; locking in
there too is OPTIONAL parity, left out to keep this tight.)

**Accuracy notes the implementer must respect (the reviewer caught these):**
- The module logger is `logger` (`model_video.py:40`), NOT `_log`.
- In `_persist_style_overrides` the value actually written to `image_style_override` is
  **`img_val`** (line ~640; it's `None` when "images" isn't an enabled stage), NOT
  `image_dna`. Gate + pass `img_val`, so lock-in never fires for an images-disabled clone.
- Neither the creator's `video_title` nor `project_id` is in scope in
  `_persist_style_overrides` — fetch them from the `videos` row (see Step 2).

- [ ] **Step 1: Thread the flag through `_run_modeling`.** Add
  `lock_in_identity: bool = False` to its signature (~821) and pass it down into the
  `_persist_style_overrides(...)` call (mirror how `enabled_stages` is already threaded).

- [ ] **Step 2: Lock in inside `_persist_style_overrides`.** After the UPDATE that writes
  `image_style_override = $5` (~665), add (using `img_val`, `logger`, and a freshly
  fetched project_id + title):

```python
    if lock_in_identity and (img_val or "").strip():
        try:
            from routes.visual_styles import upsert_active_visual_style
            vrow = await fetch_one(
                "SELECT project_id, video_title FROM videos WHERE id = $1", video_id,
            )
            if vrow and vrow.get("project_id"):
                name = f"Cloned from {vrow.get('video_title') or 'video'}".strip()
                await upsert_active_visual_style(str(vrow["project_id"]), name, img_val.strip())
        except Exception as e:
            logger.warning("clone lock-in failed: %s", e)
```

  (Confirm `fetch_one` is imported in `model_video.py`; it is used throughout. Accept the
  signature change to `_persist_style_overrides` to receive `lock_in_identity`, or read
  it off a value `_run_modeling` already has — whichever matches the existing call shape.)

- [ ] **Step 3: Verify compile.**

Run: `cd storyengine/backend && python3 -m py_compile routes/model_video.py routes/videos.py`
Expected: clean.

- [ ] **Step 4: (If practical) a focused test.** If the modeling functions can be
  exercised with the DB stubbed, add a test asserting `upsert_active_visual_style` is
  called with the cloned DNA when `lock_in_identity=True` and not when False. If the
  function is too entangled for a unit test, note it and rely on the prod check (Task 8).

- [ ] **Step 5: Commit**

```bash
git add storyengine/backend/routes/model_video.py
git commit -m "feat(model-video): lock the cloned look in as channel identity when requested"
```

---

## Task 5: Frontend — `VISUAL_PRESETS` + the unified Visual style step

**Files:**
- Modify: `storyengine/frontend/src/app/pipeline/page.tsx`

- [ ] **Step 1: Add the presets constant** (module scope, near the other consts like
  `PIPELINE_STAGES`):

```tsx
type VisualPreset = { id: string; label: string; look: string; icon: string };
const VISUAL_PRESETS: VisualPreset[] = [
  { id: "pixar_3d",   label: "Pixar 3D",   icon: "/style-icons/pixar_3d.png",
    look: "Soft 3D Pixar-style CG, rounded forms, warm cinematic light, subsurface skin, shallow depth of field" },
  { id: "flat_2d",    label: "2D flat",    icon: "/style-icons/flat_2d.png",
    look: "Clean 2D flat vector animation, bold flat colors, simple shapes, crisp outlines, minimal shading" },
  { id: "realistic",  label: "Realistic",  icon: "/style-icons/realistic.png",
    look: "Photorealistic cinematic photography, natural lighting, real textures, shallow depth of field" },
  { id: "anime",      label: "Anime",      icon: "/style-icons/anime.png",
    look: "Modern anime cel-shaded illustration, expressive faces, clean linework, soft gradient shading" },
  { id: "watercolor", label: "Watercolor", icon: "/style-icons/watercolor.png",
    look: "Warm hand-painted watercolor storybook art, soft edges, textured paper, gentle palette" },
  { id: "comic",      label: "Comic",      icon: "/style-icons/comic.png",
    look: "Bold graphic-novel illustration, inked outlines, halftone shading, dynamic high-contrast color" },
];
```

- [ ] **Step 2: Replace state.** Remove `newVisualStyle` usage for the look; add:

```tsx
  // Visual style choice: 'reference' (use the pasted video), a preset id,
  // 'custom' (typed), or '' (none → channel identity / neutral).
  const [styleMode, setStyleMode] = useState<"reference" | "preset" | "custom" | "">("");
  const [stylePresetId, setStylePresetId] = useState<string>("");
  const [styleCustom, setStyleCustom] = useState<string>("");
  const [lockInIdentity, setLockInIdentity] = useState<boolean>(false);
```

  When the user pastes a reference URL, default `styleMode` to `"reference"`; when they
  pick a preset set `styleMode='preset'` + `stylePresetId`; the custom box sets
  `styleMode='custom'`. Selecting one clears the others (single choice).

- [ ] **Step 3: Replace the JSX.** Remove the standalone "Visual Style" 4-button block
  (~1388-1417) and fold the "Copy a video's style" input (~1231-1252) into ONE
  "Visual style" section implementing the §4 layout: a "Use this video's style" option
  shown only when `newReferenceUrl.trim()` is set; a grid of preset buttons each showing
  `<img src={p.icon}>` + label; a "Describe your own" radio revealing a text input; and
  a "Lock this in as <channel>'s identity" checkbox bound to `lockInIdentity`. Use the
  channel name already available on the page (fall back to "this channel"). Keep the
  reference `<input>` (it still drives the clone) inside this section.

- [ ] **Step 4: Verify types + build.**

Run: `cd storyengine/frontend && npx tsc --noEmit && npm run build`
Expected: tsc clean; build succeeds (exit 0).

- [ ] **Step 5: Commit**

```bash
git add storyengine/frontend/src/app/pipeline/page.tsx
git commit -m "feat(new-video): unified Visual style step (use-this-video / presets w/ icons / custom + lock-in)"
```

---

## Task 6: Frontend — send the new payload

**Files:**
- Modify: `storyengine/frontend/src/lib/api.ts` (`createVideo` type, ~215)
- Modify: `storyengine/frontend/src/app/pipeline/page.tsx` (`handleCreate`, ~485)

- [ ] **Step 1: Extend the `createVideo` payload type** in `api.ts`:

```tsx
  image_style_override?: string;
  lock_in_identity?: boolean;
  visual_style_label?: string;
```

- [ ] **Step 2: Compute + send in `handleCreate`.** Replace the `visual_style` line in
  the `createMutation.mutate({...})` payload with the resolved look:

```tsx
    const preset = VISUAL_PRESETS.find((p) => p.id === stylePresetId);
    const imageStyle =
      styleMode === "preset" ? preset?.look :
      styleMode === "custom" ? (styleCustom.trim() || undefined) :
      undefined;                          // 'reference' / '' → clone or channel default
    const styleLabel =
      styleMode === "preset" ? preset?.label :
      styleMode === "custom" ? "Custom" : undefined;
    // ...inside mutate({ ... }):
      image_style_override: imageStyle,
      lock_in_identity: lockInIdentity || undefined,
      visual_style_label: styleLabel,
      reference_url: newReferenceUrl.trim() || undefined,
      // STOP sending visual_style for the look — leave it omitted so the server
      // keeps the neutral engine; the look now travels via image_style_override.
```

  Remove `visual_style: newVisualStyle || undefined` from the payload.

- [ ] **Step 3: Verify types + build.**

Run: `cd storyengine/frontend && npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add storyengine/frontend/src/lib/api.ts storyengine/frontend/src/app/pipeline/page.tsx
git commit -m "feat(new-video): send image_style_override + lock_in_identity; drop visual_style profile id"
```

---

## Task 7: Preset icon assets

**Files:**
- Create: `storyengine/frontend/public/style-icons/{pixar_3d,flat_2d,realistic,anime,watercolor,comic}.png`

- [ ] **Step 1:** Place the six icons Ryan generated (GPT Image, Appendix A of the
  spec) at those exact paths. Square PNGs.
- [ ] **Step 2: Verify** they're committed and load: `ls storyengine/frontend/public/style-icons/` shows all 6; `npm run build` still passes.
- [ ] **Step 3: Commit**

```bash
git add storyengine/frontend/public/style-icons/
git commit -m "assets: preset preview icons for the Visual style step"
```

---

## Task 8: Deploy + prove on prod

- [ ] **Step 1: Merge to main + push.** (Or merge the worktree branch ff → main.)
- [ ] **Step 2: Backend deploy.** `ssh storyengine-vps`, `cd ~/projects/economy-fastforward && git pull --ff-only`, then restart: `pkill -9 -f "[u]vicorn main:app"` (systemd revives in ~13s; health `curl 127.0.0.1:8001/health` → 404 = up).
- [ ] **Step 3: Frontend deploy (MUST build).** On the VPS: `cd ~/projects/economy-fastforward/storyengine/frontend && npm run build` (exit 0), THEN restart the frontend (`pkill` its `next start` MainPID; systemd revives serving the new `.next`). A restart WITHOUT build serves the old bundle — see `[[storyengine-vps-access]]`. Verify `curl https://storyengine.dev/` → 200.
- [ ] **Step 4: Prove preset path.** Create a video with the **Pixar 3D** preset (Ryan's tenant). Confirm `videos.image_style_override` holds the Pixar look and the generated image prompts front-load it (reuse the Phase-4 identity/prompt-builder inspection, or read the `assets`/image-prompt rows). Repeat with **Describe your own**.
- [ ] **Step 5: Prove lock-in.** Create with a preset + the lock-in checkbox; confirm the Visual Styles page shows it active, and the NEXT non-cloned video resolves to that look (build_identity_context on prod, as in Phase 4b).
- [ ] **Step 6: Prove clone + lock-in.** Create with a YouTube reference + lock-in; after modeling completes, confirm `image_style_override` set on that video AND a "Cloned from …" active style on the Visual Styles page.
- [ ] **Step 7: Update trackers.** Mark this done in `tasks/new-video-visual-style-step-spec.md` / `tasks/todo.md`; update memory `[[storyengine-engine-identity-shipped]]` and `[[storyengine-channels-profile-ia]]` (the New Video style UX changed).

---

## Verification summary
- **Pure logic (Tasks 1-2):** `pytest` (helper dedup/activate; request fields).
- **Backend integration (Tasks 3-4):** `py_compile` + existing tests + **prod regenerate-and-inspect** (this repo verifies prompts on prod, not pytest — see the spec).
- **Frontend (Tasks 5-7):** `tsc --noEmit` + `next build` (no browser for authed pages).
- **End-to-end (Task 8):** create-in-style + lock-in proven on prod.

## Out of scope (from spec §12)
Phase 5 (voice cloning); a thumbnail-style picker; server-side preset validation;
migrating the 4 seeded library styles; character-reference management changes.
