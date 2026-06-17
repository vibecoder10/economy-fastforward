# Engine / Identity Split — Implementation Plan

> **For agentic workers:** implement task-by-task. Steps use checkbox (`- [ ]`) syntax.
> This codebase has NO pytest-TDD culture for prompts — it verifies with `python3 -m py_compile`,
> `tsc --noEmit`, `next build`, and **prod regenerate-and-inspect** (generate for a tenant, read
> the DB output). Use real unit tests only for pure logic (the IdentityContext builder, the title
> path). For prompt-content changes, "the test" = regenerate and read the output. Deploy =
> push `main` → VPS `git pull --ff-only` → restart (see `tasks/todo.md` deploy notes; remember the
> `kill -9 $(pgrep -f "uvicorn main:app")` self-match footgun — run it from a script file).

## STATUS (2026-06-16)
- ✅ **Phase 1 (Foundation)** — `IdentityContext` + builder (`identity.py`), neutral engine templates + `safe_fill` (`engine_templates.py`), executor injection + neutral fallback (`pipeline_executor.py resolve_prompt`). Merged to `main`, deployed.
- ✅ **Phase 2 (Text engine)** — `script` (template + bot append-blocks + user-prompt tail), the script **validator** (PD checks now opt-in via `ScriptProfile`, default OFF; `power_doctrine_v2` re-enables), `research`, and `video_motion` all neutralized. PD originals preserved verbatim in `tasks/engine-identity-seeds/power-doctrine.md`. Reviewer-approved (no craft-loss). 24 backend + 154 script tests green. Merged to `main`, deployed.
- ✅ **Phase 2b (ScriptProfile)** — added `neutral_v1` profile + flipped `DEFAULT_PROFILE_ID`; brief-gate now opt-in (`requires_research_brief`); PD profiles stay loadable. PROVEN live: a clean ESL script generated on prod. Merged, deployed.
- ✅ **Phase 3 (Titles + thumbnail copy)** — `title_patterns.json` + the title prompts + the `infer_framework_from_research` 17-framework classifier + the thumbnail prompt all neutralized; engine `title`/`thumbnail` templates promoted. Reviewer-approved. Merged, deployed.
- ◻︎ **Phase 4 (Images)** — see below. Also still tracked: `_generate_cinematic_direction` PD act-structure in `research/agent.py`, `gap_title_engine.py` `MF_FORMULAS`, and a pre-existing `title_patterns.json` loader path bug (own task).
- ◻︎ **Phase 4 (Images)** — `prompt_builder.py` constants, the lone `cinematic_illustration` profile, AND `anthropic_client.py:~408-487` image prompt ("intelligence operations center / never show humans"). Needs the Phase-4 visual-store decision (Open Question 1).
- ◻︎ **Phase 5 (Clone seeds voice + creator direction)**.

**Goal:** Separate the universal *engine* (the craft of turning a sentence into a video) from the
swappable *identity* (a channel's voice + look), so any creator can clone a YouTube video, steer it
in their own direction, and generate on-brand videos — with zero hardcoded "Power Doctrine".

**Architecture:** Every generation prompt today fuses two things: CRAFT (how to write a gripping
script, prompt an image, build a title — universal, keep verbatim) and IDENTITY (the Power Doctrine
geopolitics voice + 2D-animated look — channel-specific, must be injected). We introduce a single
`IdentityContext` (built from the channel profile + a per-channel voice/visual style), inject it into
every generation call site, and rewrite the base prompts to be neutral craft templates with
`{identity.*}` slots. The clone flow *seeds* the identity; the creator *steers* it. "Power Doctrine"
becomes one saved identity, not the default.

**Tech Stack:** Python/FastAPI backend (`storyengine/backend`), the pipeline skill bots
(`skills/video-pipeline/*`), Supabase Postgres, Next.js frontend. LLM calls route through
`kie_unified.get_text_client_for_tenant` (tenant's Anthropic key → else kie.ai). Image gen via
kie.ai (nano-banana / GPT Image 2).

---

## The Identity model (the core design)

A channel's **identity** has two halves, both sourced from data that already exists:

| Half | What it controls | Source of truth (today) | Gap |
|------|------------------|--------------------------|-----|
| **Voice** | script, research, titles, thumbnail copy, motion phrasing | `channel_profiles` (`channel_name`, `niche`, `target_audience`, `style_description`, `frameworks`) + per-channel `tenant_prompt_defaults` | not passed to most call sites; title has no per-channel path |
| **Visual** | characters, environments, scene panels, grid | per-*video* `videos.image_style_override` (set by clone) + the lone `cinematic_illustration` visual profile | no per-*channel* store; characters/envs ignore it; hardcoded "2D animated / earthy" default |

**The engine** is the neutral craft: the script structure/retention rules, the image-direction rules,
the title science, the motion rules — everything EXCEPT the geopolitics and the 2D-animated look.

**Injection principle:** load the identity ONCE per run, pass an `IdentityContext` object to every bot,
and have each neutral prompt reference `identity.*`. When a tenant has a custom prompt
(`tenant_prompt_defaults`) it still wins; when they don't, the neutral engine template — filled with
their identity — runs (NEVER an empty string, NEVER Power Doctrine).

```
IdentityContext (built per run from channel_profiles + visual style):
  channel_name: str          # "Slow English"   (free text, editable in Profile)
  niche: str                 # "Beginner English learning (ESL)"
  target_audience: str       # "adult ESL learners, A1-A2"
  voice_style: str           # creator's direction / style_description ("warm, slow, simple")
  visual_style: str          # the look ("soft 3D Pixar CG", or cloned image DNA)
  frameworks: list[str]      # optional angle labels, NOT hardcoded geopolitics
```

---

## File structure — what changes and why

**New:**
- `storyengine/backend/identity.py` — `IdentityContext` dataclass + `build_identity_context(tenant_id, video)` (single source; reads `channel_profiles`, falls back to `projects`, then to generic neutral defaults).
- `storyengine/backend/engine_templates.py` — the canonical NEUTRAL engine prompts (script/research/thumbnail/motion/title), each a craft template with `{identity.*}` slots. This REPLACES the Power-Doctrine bodies currently in `prompt_defaults.py` and the hidden copies in the skill bots. One source of truth.
- `tasks/engine-identity-seeds/power-doctrine.md` — the original Power Doctrine prompts preserved verbatim as a *saved identity/example* (so the craft history isn't lost and PD can be re-loaded as a demo channel).

**Modified (text engine):**
- `storyengine/backend/prompt_defaults.py` — `PROMPT_DEFAULTS` bodies become the neutral templates (import from `engine_templates.py`); fix `META_PROMPT_TEMPLATE` to ADAPT structure to the niche (not "keep ALL structure EXACTLY").
- `storyengine/backend/pipeline_executor.py` — `_load_prompt_overrides` (~516-556): after resolving per-video/tenant override, fall back to the neutral engine template (not `None`); build + attach `IdentityContext`; the resolved prompt is `.format`-filled with identity.
- `storyengine/backend/routes/system_prompts.py` — `/generate` (~92): route through `get_text_client_for_tenant` (kie OR anthropic), not the raw anthropic key (line 97).
- `skills/video-pipeline/research/agent.py` (~518-551 research persona, ~159-232 inline title prompt) — replace hardcoded "Economy FastForward (Power Doctrine)" body with the neutral template + identity injection.
- `skills/video-pipeline/script/brief_translator/script_generator.py` (~1058-1159 assembly, ~1376-1381) — neutral-template fallback instead of empty string; thread identity.
- `skills/video-pipeline/thumbnail/prompt_builder.py` (~29-77 `VARIABLE_FILL_SYSTEM_PROMPT`) — strip "Economy FastForward" + "CHECKMATE/WEAPONIZED/bear trap"; neutral + identity.
- `skills/video-pipeline/shared/clients/anthropic_client.py` (~1157-1199 motion fallback) — replace missile/bomber examples with niche-neutral ones.
- `skills/video-pipeline/title_patterns.json` — neutralize `power_doctrine_adaptations` + `master_formulas` geopolitics; keep the structural title science.

**Modified (visual engine — Phase 4):**
- `skills/video-pipeline/image_prompts/engine/prompt_builder.py` (283-296 `_CHARACTER_PREFIX`/`_ENVIRONMENT_PREFIX`/`_UNIVERSAL_SUFFIX`), `skills/video-pipeline/storyboard/bot.py` (~1068-1072 `_KF_PREFIX`/`_KF_SUFFIX`), `skills/video-pipeline/shared/profiles/visual/cinematic_illustration.py` (the lone profile) — drive from the channel visual identity; neutral default.
- `storyengine/backend/routes/characters.py` (~143-198) + `routes/environments.py` — apply the channel visual style (today they fall back to generic "consistent illustrated style" and ignore `image_style_override`).

---

## Phase 1 — Identity foundation (plumbing, no prompt rewrites yet)

*Ships: every text bot receives an `IdentityContext`; keyless steps fall back to a neutral
(placeholder) engine template filled with identity — instead of empty string / Power Doctrine.
Existing tenant overrides still win, so no behavior change for customized tenants.*

### Task 1.1: `IdentityContext` + builder

**Files:**
- Create: `storyengine/backend/identity.py`
- Test: `storyengine/backend/tests/test_identity_context.py`

- [ ] **Step 1: Write the failing test** — build from a profile row, and the empty/neutral fallback.

```python
# tests/test_identity_context.py
from identity import build_identity_context_from_rows, IdentityContext

def test_builds_from_channel_profile():
    ctx = build_identity_context_from_rows(
        project={"name": "Slow English", "niche": "Beginner English (ESL)"},
        profile={"target_audience": "A1-A2 adult learners", "style_description": "warm, slow, simple", "frameworks": []},
        video={},
    )
    assert ctx.channel_name == "Slow English"
    assert "ESL" in ctx.niche
    assert ctx.voice_style == "warm, slow, simple"

def test_neutral_fallback_when_empty():
    ctx = build_identity_context_from_rows(project=None, profile=None, video={})
    # Never Power Doctrine, never blank-and-broken: a safe generic creator identity.
    assert ctx.channel_name == "this channel"
    assert ctx.niche and "geopolit" not in ctx.niche.lower()
```

- [ ] **Step 2: Run it, verify it fails** — `cd storyengine/backend && python3 -m pytest tests/test_identity_context.py -v` → FAIL (no module).
- [ ] **Step 3: Implement** `IdentityContext` (dataclass) + `build_identity_context_from_rows(project, profile, video)` (pure, testable) and an async `build_identity_context(tenant_id, video)` wrapper that fetches `projects` then `channel_profiles` (mirror the precedence already in `routes/videos.py:1429-1451`). `image_style_override` on the video overrides `visual_style`.
- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Commit** — `feat(identity): IdentityContext + builder (single source of channel voice/look)`

### Task 1.2: Neutral engine-template scaffold

**Files:**
- Create: `storyengine/backend/engine_templates.py`

- [ ] **Step 1:** Add neutral PLACEHOLDER templates for `script/research/thumbnail/video_motion/title` as craft skeletons with `{channel_name}/{niche}/{target_audience}/{voice_style}/{visual_style}` slots. (Real craft content lands in Phase 2/3 — here they just must be neutral + slot-filled, NOT Power Doctrine.) Add `render(key, identity)` that fills ONLY the known identity slots and leaves every other `{...}` UNTOUCHED — use a safe/partial substitution (a custom `string.Formatter` or a regex over the known identity keys), **never plain `str.format`**, which would `KeyError` on prompt braces like `{HEADLINE}`/`{TOPIC}` or choke on JSON `{{...}}` (e.g. in `TITLE_GENERATION_PROMPT`). This same safe-substitute helper is the ONLY thing the executor uses to fill overrides too (Task 1.3) — so a stray brace in a tenant override can never raise at run time. Add a unit test that a template containing both `{niche}` and `{HEADLINE}` fills the former and preserves the latter verbatim.
- [ ] **Step 2:** `py_compile`. Commit — `feat(engine): neutral engine-template scaffold with identity slots`

### Task 1.3: Inject identity + neutral fallback in the executor

**Files:**
- Modify: `storyengine/backend/pipeline_executor.py` (`_load_prompt_overrides`, ~516-556)

- [ ] **Step 1:** Build `IdentityContext` once at the start of the run (or in `_load_prompt_overrides`); store on `self._identity`.
- [ ] **Step 2:** Change the resolve line from `resolved = per_video or tenant or None` to `resolved = per_video or tenant or engine_templates.render(prompt_key, self._identity)`. Where a bot expects identity injected into an EXISTING override too, `.format`-fill the override with the identity dict (guard for prompts that legitimately contain other `{...}` like `{HEADLINE}` — only fill identity keys, leave the rest).
- [ ] **Step 3:** Verify: `py_compile`; deploy to VPS; pick a throwaway tenant with NO overrides and confirm the resolved script/research/thumbnail prompts are neutral + carry the channel niche (log them, or add a temporary `/debug/resolved-prompts` behind auth). Expected: no "Power Doctrine", niche present.
- [ ] **Step 4: Commit** — `feat(pipeline): inject IdentityContext + neutral engine fallback (no more empty/PD default)`

---

## Phase 2 — Neutralize the text engine (script, research, motion)

*Ships: scripts/research/motion are written in the channel's voice for ANY niche; the hidden
Power-Doctrine copies in the skill bots are gone. This is the biggest leak.*

For EACH of `script`, `research`, `video_motion`:
- [ ] Identify CRAFT vs IDENTITY in the current prompt (the audit quotes the giveaway lines). KEEP craft verbatim (hook discipline, retention cadence, "every claim specific", cliffhangers, motion-enacts-the-verb, 2-actions-max). STRIP identity (Power Doctrine name, "reveal hidden geopolitical mechanisms", incentive-chain-about-money, "19 numbers", Machiavelli/Sun Tzu, missile/bomber examples).
- [ ] Move the neutral version into `engine_templates.py` with identity slots; point the skill-bot copy at it (delete the duplicate body so there's ONE source). **Important for `research`:** the real runtime default is the hardcoded `RESEARCH_SYSTEM_PROMPT` in `skills/video-pipeline/research/agent.py:518` (NOT `prompt_defaults.py`) — it MUST be deleted/replaced, or it survives as a shadow default and the change has no effect. Same caution for the script assembly in `script_generator.py` and the motion fallback in `anthropic_client.py:~1157`.
- [ ] **Verify (regenerate-and-inspect):** generate the artifact for TWO different niches (Ryan's ESL tenant `ee93e6d1-…` + a second test niche, e.g. cooking) and read the output. Pass = on-brand for each niche, geopolitics absent, craft intact (hook in first lines, retention beats present). Script: run through storyboard only / inspect the script row — no paid clip spend.
- [ ] Commit per prompt.

---

## Phase 3 — Titles + thumbnail copy become identity-aware

*Ships: title + thumbnail-text generation follow the channel niche everywhere (discovery already
fixed; this closes the OTHER paths the audit found with no per-channel hook).*

- [ ] **Task 3.1 — title_patterns.json:** neutralize `master_formulas` examples + `power_doctrine_adaptations` (drop PROXY WAR/NATO/PBOC/Machiavelli verdicts); keep the structural science (curiosity gap, length discipline, specificity). Verify the readers (autopilot/research-agent/discovery-scanner) still load it (`py_compile` + a smoke generate).
- [ ] **Task 3.2 — give title generation an identity path:** add a `"title"` entry to `PROMPT_MAP` (or pass `IdentityContext` into `research/agent.py:159-232` and the title selector), so titles read `niche`/`voice_style`. Verify by regenerating titles for two niches.
- [ ] **Task 3.3 — thumbnail copy:** in `thumbnail/prompt_builder.py` replace "Economy FastForward" + the geopolitics power-words/object-metaphors with identity-driven neutral guidance. Verify by regenerating a thumbnail prompt (inspect text; optional one paid GPT-Image-2 render).

---

## Phase 4 — Neutralize the visual engine (images) — *gets its own detailed plan*

*Ships: characters, environments, scenes, and grids all render in the channel's chosen look
instead of the hardcoded "2D animated / earthy" default.*

Outline (detail when we reach it):
- [ ] Decide the per-channel visual-style store: simplest = reuse `channel_profiles.style_description` as the channel default for `image_style_override` when a video has none; fuller = a `channel_visual_styles` row + a Settings UI (the audit's recommendation). **Decision needed from Ryan** (see Open Questions).
- [ ] Make `routes/characters.py` + `routes/environments.py` actually apply the channel/video visual style (today they ignore `image_style_override` and use generic fallback).
- [ ] Replace the hardcoded `_CHARACTER_PREFIX`/`_ENVIRONMENT_PREFIX`/`_UNIVERSAL_SUFFIX` (`prompt_builder.py:283-296`) and `_KF_PREFIX`/`_KF_SUFFIX` (`storyboard/bot.py`) with a neutral default + the channel visual identity; the `cinematic_illustration` profile becomes one selectable style, not THE default.
- [ ] Verify with a small paid grid gen per the project's "storyboard-grids-only" cheap-test pattern.

---

## Phase 5 — Clone seeds the voice + creator-direction layer — *gets its own detailed plan*

*Ships: the full "cloneable system" — clone a link → identity (voice + look) is modeled → creator
steers it → on-brand videos.*

Outline:
- [ ] Extend the clone/model flow (`model_video.py`) to model the source's VOICE (script style, title patterns, tone) into the channel identity, the way it already models visual DNA — so a clone seeds both halves.
- [ ] Make "creator direction" a first-class input (a steer field on the channel/video that flows into `voice_style`), AI-assisted (suggest-and-refine via the existing `/system-prompts/generate`, now niche-adaptive from Phase 2).
- [ ] Save Power Doctrine as a loadable example identity (`tasks/engine-identity-seeds/power-doctrine.md`).

---

## Verification summary (per the project's real workflow)
- Pure logic (1.1, 1.3 resolve, 3.2 title path): `pytest` in `storyengine/backend`.
- Everything else: `python3 -m py_compile` (backend) / `tsc --noEmit` + `next build` (frontend) + **regenerate-and-inspect on prod** for two different niches. Local preview can't reach authed pages — verify via DB output, not the browser ([[storyengine-local-preview-auth]]).
- After each phase: deploy (push → VPS pull → restart) and confirm Ryan's ESL tenant + a second niche both come out on-brand with the craft intact.

## Open questions (need Ryan)
1. **Phase 4 visual store:** quick (reuse `style_description` as the channel default) vs full (new `channel_visual_styles` table + Settings UI)? Recommend quick first, full later.
2. **Default engine voice:** when a brand-new tenant has set NOTHING, should the neutral fallback be a plain documentary-explainer style, or should onboarding force a clone/direction first so there's always a real identity? Recommend: neutral explainer fallback + nudge to clone.
3. **Scope of "craft" to keep in the script template:** keep the full 6-act structure as the default skeleton (adapted per niche), or a lighter neutral skeleton? Recommend: keep the craft, let the meta-prompt adapt the act count/structure to the niche (ESL ≠ 6-act exposé).
