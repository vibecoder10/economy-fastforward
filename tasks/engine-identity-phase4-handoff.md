# Phase 4 Handoff — Neutralize the IMAGE engine (the last Power Doctrine stronghold)

**Written:** 2026-06-17 · **For:** a fresh agent window with no prior context · **Repo:** `~/economy-fastforward`

---

## 0. 30-second orientation (read this first)

**StoryEngine** is a multi-tenant SaaS that turns a topic into a finished narrated video
(script → voice → image prompts → images → motion → render). It lives in this monorepo:
- `storyengine/backend/` — the FastAPI backend that orchestrates the pipeline (per-tenant).
- `skills/video-pipeline/` — the actual generation "bots" (script, image_prompts, images, etc.).
- **Hard constraint:** `skills/video-pipeline` **cannot import** `storyengine/backend`. They talk
  through env vars and the pipeline object, never direct imports.

**The refactor in flight (the "cloneable system"):** the app was originally built as ONE channel —
Ryan's old geopolitics channel, **"Power Doctrine."** Its voice, frameworks, and *look* were
hardcoded into every generator. We are splitting the universal **engine** (the craft — how a good
script/image/title is built) away from the per-channel **identity** (the voice + the look). After the
split, Power Doctrine is just one *optional* identity you can load, not the baked-in default. A new
creator should be able to clone any YouTube channel's style and generate in *their* look.

**Done so far (Phases 1–3, all merged + deployed + proven live):** the entire **text** side is
neutral now — script, research, motion, titles, thumbnail *copy*. Power Doctrine is opt-in there.
See `tasks/engine-identity-split-plan.md` for the full plan and `tasks/engine-identity-seeds/power-doctrine.md`
for the PD originals preserved verbatim.

**Phase 4 = the one piece still locked to Power Doctrine: the PICTURES.** That's this handoff.

---

## 1. The good news: the image engine is ALREADY a profile system

Phase 4 is **NOT** "build the split from scratch." Unlike the text side, the image side already has the
engine/identity architecture — it just **defaults to the Power Doctrine profile.** So Phase 4 mirrors
**Phase 2b** (the ScriptProfile fix), not Phase 1.

The architecture that already exists:
- `skills/video-pipeline/shared/profiles/visual/` — a registry of `VisualProfile` objects, each a
  **complete, standalone look**: `holographic_hud`, `cinematic_dossier`, `clay_mannequin`,
  `cinematic_illustration`. (Schema: `shared/profiles/visual/schema.py`.)
- `shared/profiles/visual/__init__.py` — `load_profile()` resolves: explicit `profile_id` →
  `VISUAL_PROFILE` env var → `DEFAULT_PROFILE_ID`. **`DEFAULT_PROFILE_ID = "cinematic_illustration"`.**
- The pipeline sets the env var per video: `orchestrator/pipeline.py:203` does
  `os.environ["VISUAL_PROFILE"] = self.visual_style`, and the backend feeds that from the tenant
  (`storyengine/backend/pipeline_executor.py:284`, defaulting to `"cinematic_illustration"`).
- `image_prompts/engine/prompt_builder.py` reads the active profile's prefix/suffix/figure-rules and
  only falls back to **hardcoded constants** when no profile loads.
- `shared/clients/anthropic_client.py:generate_image_prompts` (~line 408) uses the active profile's
  `scene_description.system_prompt`; it only falls back to a hardcoded **"holographic intelligence
  operations center / NEVER include human figures"** system prompt when the profile is
  `None`/`holographic_hud`.

**So the whole job is the same shape as Phase 2b:** make a neutral profile, make it the default
everywhere, neutralize the hardcoded fallbacks so even the no-profile path is clean, and keep the
Power Doctrine look loadable as a named preset.

---

## 2. Exactly where Power Doctrine still lives in images (the inventory)

### A. The default profile IS the Power Doctrine look
`cinematic_illustration` is Ryan's old channel's exact aesthetic AND it's geopolitics to the core.
File: `skills/video-pipeline/shared/profiles/visual/cinematic_illustration.py`
- The look itself: "Cinematic 2D animated illustration of … ink outlines, muted earthy palette, film
  grain" (`_CHARACTER_PREFIX`/`_ENVIRONMENT_PREFIX`/`_SUFFIX`, ~lines 87–100).
- `_CHARACTER_ARCHETYPES` (~lines 251–307): `russian_leader` (Putin/Kremlin), `chinese_official`,
  `american_president`, `iranian_leader` (turban/IRGC/ayatollah), `saudi_royal`, `military_general`,
  `insurgent_militia` (Houthi/Hezbollah/Hamas), `wall_street_banker`, `intelligence_officer`, etc.
- `_SCENE_DESCRIPTION.system_prompt` (~lines 328–425): worked examples are all geopolitics — "Iranian
  general slamming fist on map table," "Strait of Hormuz at dawn," "missile installations,"
  "TOP SECRET folder."
- `metaphor_translation_table` (~lines 406–419): `proxy_war`, `sanctions`, `surveillance_state`,
  `military_force`, `market_crash`, etc.
- `_RAW` (~lines 647–738): `material_vocabulary` (weapon rack, naval vessels, sandbags),
  `preview_prompts` (Shahed drones over Kyiv, Iranian news anchor), geopolitics tags.

### B. Hardcoded fallbacks in the prompt builder (apply when no profile / belt-and-suspenders)
File: `skills/video-pipeline/image_prompts/engine/prompt_builder.py`
- `_CHARACTER_PREFIX` / `_ENVIRONMENT_PREFIX` = `"Cinematic 2D animated illustration of"` (~lines 283–290).
- `_UNIVERSAL_SUFFIX` = ink outlines / muted earthy palette / film grain (~lines 293–296).
- The "never show humans" machinery: `PEOPLE_WORDS`, `_PEOPLE_REPLACEMENTS`, `validate_no_people`,
  `_remove_people_references` (~lines 55–147) — replaces people with "unmanned consoles," etc.
- `_EQUIPMENT_KEYWORDS` / `_enforce_equipment_integrity` (~lines 182–242) — drones/missiles/tanks
  "fully assembled and operational." PD-flavored.
- `_ARCHETYPE_KEYWORDS` in `_match_archetype_expression` (~lines 632–644) — russian/iran/kremlin/IRGC
  keyword routing.

### C. The hardcoded holographic fallback system prompt
File: `skills/video-pipeline/shared/clients/anthropic_client.py`, `generate_image_prompts`, ~lines 474–509.
- "HOLOGRAPHIC INTELLIGENCE DISPLAY … intelligence operations center … war room from Tom Clancy crossed
  with Bloomberg Terminal … NEVER include human figures … The room is ALWAYS empty of people."
- **Note:** this only fires when the active profile is `None` or `holographic_hud`. With a neutral
  default profile that has its own `scene_description.system_prompt`, this path goes dead — but
  neutralize/quarantine it anyway so it can't leak.

### D. All the places that hardcode `"cinematic_illustration"` as the default (flip every one)
1. `skills/video-pipeline/shared/profiles/visual/__init__.py:37` → `DEFAULT_PROFILE_ID`
2. `skills/video-pipeline/shared/clients/airtable_client.py:27,32` → valid list + `DEFAULT_VISUAL_STYLE`
3. `skills/video-pipeline/shared/channels/config.py:54`
4. `skills/video-pipeline/orchestrator/pipeline_constants.py:416` → `DEFAULT_VISUAL_STYLE`
5. `skills/video-pipeline/image_prompts/manifest.json:18`
6. `storyengine/backend/pipeline_executor.py:284`
7. `storyengine/backend/routes/projects.py:72`

---

## 3. THE DECISION you need from Ryan before building (Open Question 1)

A channel's *look* needs to live somewhere. Two options — Ryan should pick:

- **QUICK (recommended):** reuse the free-text visual-style field the channel already has.
  Phase 1 already builds `IdentityContext.visual_style` backend-side (from `channel_profiles` /
  `projects`) — see `storyengine/backend/identity.py` and `pipeline_executor.py:586`. Pipe that one
  sentence into the neutral visual profile's prefix/suffix at runtime (e.g. via a new
  `VISUAL_STYLE_DESCRIPTION` env var the neutral profile / prompt_builder reads, mirroring how
  `VISUAL_PROFILE` already flows). No schema, no UI. The named registry profiles
  (`cinematic_illustration`, `clay_mannequin`, `holographic_hud`, `cinematic_dossier`) stay as
  pickable presets.
- **FULL:** add a `channel_visual_styles` table + a Settings tab (structured palette / medium /
  scene-type weights per channel). More complete, but it's schema + frontend + backend wiring.

**Recommendation:** ship QUICK now (it completes "every generation prompt is neutral + slot-driven,"
which is the whole goal of this refactor), and leave FULL as a later polish if Ryan wants a dedicated
visual-style editor. **Confirm this with Ryan in the first message of the new window** — same as we did
at each prior decision point.

---

## 4. The build plan (mirrors Phase 2b)

Use the **subagent-driven workflow** like the prior phases: branch → implementer subagent per task →
`code-reviewer` review → fix → merge ff → push → deploy. Keep PD originals preserved (the
`cinematic_illustration.py` profile already IS the preserved copy — just stop defaulting to it; you do
NOT need a new seed file for it).

1. **Create a neutral VisualProfile** — `shared/profiles/visual/neutral_v1.py` (or `documentary_neutral`).
   A complete standalone profile like the others, but: style-agnostic prefix/suffix (no "2D animated
   illustration," no ink-outline/earthy-palette lock-in), `allow_human_figures=True` with **neutral**
   character guidance (no national-leader archetypes), generic scene-type system prompt with **non-political
   worked examples**, empty/neutral metaphor table, neutral `_RAW` vocab. This is the engine's "craft"
   for images with the identity left as slots. **Make its prefix/suffix accept the injected
   `visual_style` sentence** (the QUICK path from §3).

2. **Flip the default everywhere** — all 7 spots in §2.D point at the neutral profile id.

3. **Neutralize the hardcoded fallbacks** in `prompt_builder.py` (§2.B): generic prefixes/suffix; make
   the "never show humans" + equipment-integrity + archetype-keyword machinery **opt-in/profile-driven**
   (off by default) rather than always-on. Pattern to copy: Phase 2 made the PD script-validator checks
   `= False` by default and opt-in via the profile.

4. **Quarantine the holographic fallback prompt** in `anthropic_client.py` (§2.C) — neutralize the text
   and/or confirm it's unreachable once the neutral profile is the default.

5. **Wire the QUICK style injection** — pass `IdentityContext.visual_style` from the backend into the
   image step (env var, since skills can't import backend). Verify the channel's look sentence actually
   lands in the final image prompt.

6. **Verify** (see §5), **commit**, **merge to main**, **deploy** (see §6), **prove live**, **update memory**.

---

## 5. Verification (do all before merge)
- `python -c "from shared.profiles.visual import load_profile; print(load_profile().profile_id)"` from
  `skills/video-pipeline/` → must print the neutral id.
- Render a real image prompt for a non-political topic and grep the output: **no** "2D animated
  illustration," "ink outlines," "earthy palette," "operations center," "Iranian/Russian/Kremlin," and
  the channel's `visual_style` sentence **is** present.
- `cinematic_illustration` still loads when explicitly requested (`load_profile("cinematic_illustration")`).
- `py_compile` the touched files; run `image_prompts/engine/tests/` (note the tests set
  `VISUAL_PROFILE` — update expectations if they assume the old default).
- Backend: the image stage still runs end-to-end (`tsc`/import smoke; the pipeline runs in-process).

## 6. Deploy + prove (gotchas that bit us before)
- `ssh storyengine-vps`, then in the repo: `git pull --ff-only`.
- Restart: `pkill -9 -f "[u]vicorn main:app"` — **the bracket is mandatory**; without it the pattern
  matches your own SSH shell's argv and kills your session. systemd `Restart=always` revives in ~13s.
- The pipeline runs **inside** the uvicorn process (no separate arq worker on the VPS).
- Health check: `curl 127.0.0.1:8001/health` (use `127.0.0.1`, not `localhost` = IPv6; a 404 means it's up).
- **Prove it live:** generate image prompts on prod for Ryan's tenant
  (`ee93e6d1-a9cc-44c3-81e9-84adee8329aa`) on a neutral topic (his example channel is ESL now) and
  confirm the prompts are neutral + in the channel's look. Token at `/tmp/se_token`; Supabase project
  `wrromlupsmyzrrcqlucn`. See `[[storyengine-vps-access]]`.

## 7. Hard-won lessons to respect
- **The default is the real gate.** Phase 2b's failed first live test was caused entirely by a default
  id (`DEFAULT_PROFILE_ID`), not by prompt content. For images the equivalent gate is `DEFAULT_PROFILE_ID`
  / `DEFAULT_VISUAL_STYLE` + the backend default at `pipeline_executor.py:284`. Flip ALL of them (§2.D).
- **Overrides must keep winning.** Tenants who explicitly chose a profile must still get it — only the
  *unset* default changes.
- **Don't break `skills`↔`backend` isolation.** Pass style via env var / pipeline object, never import.

## 8. Definition of done
Image prompts for a brand-new channel come out in **that channel's look**, with **zero** Power Doctrine
geopolitics, the hardcoded "2D animated / never-show-humans / operations-center" defaults are gone (or
opt-in), `cinematic_illustration` survives as a loadable preset, it's deployed, and a live prod run
proves it. Then update `tasks/todo.md`, the STATUS section of `tasks/engine-identity-split-plan.md`, and
the memory file `storyengine-engine-identity-shipped.md`. After Phase 4, only **Phase 5** (clone seeds
the voice + creator-direction layer) and the minor residuals listed in the plan remain.
