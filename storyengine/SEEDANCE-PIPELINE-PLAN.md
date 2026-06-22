# GOAL — StoryEngine coverage storyboards + two animation routes

**North star:** StoryEngine makes videos whose cuts feel like real coverage (several cinematic angles of the same moment), via two routes off one shared storyboard: a cheap any-length **grok** route and a short coherent **Seedance one-shot** route.
**Success looks like:** a grok any-length video and a Seedance short both render with smooth coverage cuts; the route is selectable; the existing 3×3 flow + per-panel Seedance stay as fallbacks (no regression for live tenants).
**Status:** Phase 1 of 4 — Coverage storyboard generator (not started)
**Updated:** 2026-06-22

Proven groundwork: the beats+coverage approach and the Seedance whole-sheet one-shot are both proven in the content-engine skill (`~/.claude/skills/content-engine`, fishing v2 + Phase 0). This is porting that into StoryEngine.

Locked decisions (2026-06-22): coverage is a NEW mode (current 3×3 storyboard stays as fallback); build the grok route before the Seedance route. Plan lives here, NOT in StoryEngine GOAL.md (the launch-readiness agent owns that).

---

## Phase 0 — Per-panel Seedance animator  `[done]`
Goal: Seedance selectable as the pricey per-clip animator (drop-in for grok).
- [x] Deployed + verified live on the VPS (`video_model=seedance-2-fast`); see [[storyengine-seedance-deploy]].
Done when: a video set to seedance-2-fast animates per-panel on prod. ✓ (script→storyboards proven; picker frontend still owed, see Phase 4.)

## Phase 1 — Coverage storyboard generator  `[todo]`
Goal: the storyboard step produces coverage — per beat, several matched cinematic angles of the SAME moment.
- [ ] Port beats/coverage prompting from content-engine into StoryEngine storyboard gen (`skills/video-pipeline/storyboard/bot.py`): per beat define 2-4 angles (wide / medium / close / OTS / insert).
- [ ] Generate matched angles: anchor each angle on the beat's master frame + cast sheet (the reference-chaining that makes angles match).
- [ ] Store coverage panels as assets with angle/shot-type metadata; gate behind the new route so the current 3×3 flow is untouched.
Done when: a test scene yields 3-4 matched angles that clearly read as the same moment.

## Phase 2 — Grok route on coverage (any length)  `[todo]`
Goal: animate each coverage panel individually, stitch → any-length video with coverage cuts.
- [ ] Point the per-panel clip stage at coverage panels; reuse existing animate + FFmpeg stitch.
- [ ] Verify cuts read as coverage across multiple scenes.
Done when: a multi-scene video stitches with smooth coverage cuts.

## Phase 3 — Seedance route on coverage (short, one-shot)  `[todo]`
Goal: lay a scene's coverage panels into one high-res sheet → one-shot Seedance → coherent clip.
- [ ] Compose coverage panels into one high-res storyboard sheet (GPT Image 2; the 3×3 preview is too low-res).
- [ ] Seedance route: feed the whole sheet → one clip per scene → stitch scenes. Gate scenes ≤15s on this route.
Done when: a short one-shots coherent clips from coverage sheets.

## Phase 4 — Deploy + route picker  `[todo]`
Goal: ship it.
- [ ] Surgical patch to the VPS (clean-base + my-edits, like Phase 0).
- [ ] Frontend route/mode picker + the still-owed Seedance picker option (needs the Next.js rebuild skipped in Phase 0).
Done when: routes are selectable in the app and both produce video on prod.

---

## Log
- 2026-06-22 — Phase 0 done (per-panel Seedance live on VPS). Planned coverage architecture; locked: coverage = new mode, grok route first. Phase 1 next.
