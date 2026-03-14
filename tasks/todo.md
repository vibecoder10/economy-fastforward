# Task Tracking

## Current Sprint

_Reference `ANIMATION_SYSTEM_REVIEW.md` for detailed feature specs before starting any roadmap item._

- [ ] _No active tasks_

## Backlog (from Roadmap)

### Phase 2: Character Consistency
- [ ] Feature 1: Character Reference System (BYOC) — HIGH
- [ ] Feature 5: Style Locking via Golden Frame — HIGH
- [ ] Feature 10: Quality Scoring via Gemini Vision — MEDIUM

### Phase 3: Product Mode
- [ ] Feature 3: One-Shot `!create` Pipeline — HIGH
- [ ] Feature 4: Airtable Schema Optimization — MEDIUM
- [ ] Feature 7: Health Dashboard & Self-Healing — MEDIUM

### Phase 4: Animation Quality
- [ ] Feature 8: Start/End Frame Bridging — MEDIUM
- [ ] Feature 9: Multi-Voice & Sound Design — LOW

## Completed

- [x] Feature 2: Auto-Pull from GitHub on Cron — DONE
- [x] Feature 6: Veo 3.1 Fast Integration — DONE
- [x] Workflow orchestration rules (CLAUDE.md) — DONE
- [x] Blocking Script Validation with Senior Editor Pass — DONE (2026-03-14)

## Review Notes

### 2026-03-14: Blocking Script Validation

**What Changed:**
- Added 2 new validators to `script_validator.py`:
  - `promise_payoff` — detects forward references ("what Part 3 reveals") and verifies they're resolved
  - `act_coherence` — detects 3+ distinct topic shifts within an act
- Made all 7 validation checks BLOCKING (previously advisory)
- Created `senior_editor.py` — single Claude call to fix flagged issues
- Wired into `BriefTranslator.translate()`:
  1. generate_script()
  2. validate (7 checks)
  3. IF flags → senior_editor() (ONE pass)
  4. IF still failing → BLOCK (status="Needs Script Review", Slack notification)
  5. IF clean → advance to "Ready For Voice"

**Files Modified:**
- `brief_translator/script_validator.py` — added new validators, made checks blocking
- `brief_translator/senior_editor.py` — NEW file
- `brief_translator/__init__.py` — wired senior editor flow
- `brief_translator/tests/test_script_validator.py` — added tests for new validators

**What to Verify:**
- Run `python -m pytest brief_translator/tests/test_script_validator.py` on VPS
- Test with a real video: generate script, verify validation runs, check Slack notifications
- Test manual approval flow: `!approve <title>` should force advance blocked scripts

**Cost Impact:** +1 Sonnet call per script (~$0.03) when validation fails
