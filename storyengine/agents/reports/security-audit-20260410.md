# Security Audit Report — PRD 4 T14
**Date:** 2026-04-10
**Auditor:** pipeline-tester (Opus)
**Scope:** All StoryEngine backend routes (25 files, 151+ endpoints)

---

## Executive Summary

**Overall posture: GOOD with 3 CRITICAL and 3 HIGH findings.**

All PRD4-specific endpoints (analytics, preferences, channel_profile, demo) pass security review. Issues are in older routes (assets, videos, visual_styles).

---

## CRITICAL Findings

### C1: Tenant Isolation Bypass in assets.py
**File:** `storyengine/backend/routes/assets.py` lines 22, 39
**Risk:** Tenant A can approve/reject Tenant B's assets if they know the asset_id.
```sql
-- Current (BROKEN):
UPDATE assets SET status = 'approved' WHERE id = $1
-- Fix:
UPDATE assets SET status = 'approved' WHERE id = $1 AND tenant_id = $2
```

### C2: Tenant Isolation Bypass in videos.py (accept_suggestion)
**File:** `storyengine/backend/routes/videos.py` line 650
**Risk:** Tenant A can modify Tenant B's video suggestion fields.
```sql
-- Current (BROKEN):
UPDATE videos SET ... WHERE id = $1
-- Fix:
UPDATE videos SET ... WHERE id = $1 AND tenant_id = $2
```

### C3: Full API Key Exposure via Reveal Endpoint
**File:** `storyengine/backend/routes/settings.py` line ~270
**Risk:** `/api/settings/keys/{key}/reveal` returns the complete unmasked API key in plaintext. Rate-limited to 5/min but still high risk.
**Recommendation:** Require additional confirmation (re-enter password or 2FA) before reveal. Or remove endpoint and require users to re-enter keys.

---

## HIGH Findings

### H1: Unauthenticated Endpoints in visual_styles.py
**File:** `storyengine/backend/routes/visual_styles.py`
**Endpoints:**
- `POST /api/visual-styles/characters/generate` — no auth
- `POST /api/visual-styles/analyze-image` — no auth
**Risk:** Anyone can call these endpoints without authentication. If they call external AI APIs, this is a cost exposure vector.
**Fix:** Add `Depends(get_tenant_id)` to both endpoints.

### H2: Missing tenant_id in projects.py UPDATE
**File:** `storyengine/backend/routes/projects.py` line 176
**Risk:** UPDATE uses only `WHERE id = $1` without tenant_id. Defense-in-depth violation.
**Fix:** Add `AND tenant_id = $X` to WHERE clause.

### H3: Missing tenant_id in videos.py UPDATEs
**File:** `storyengine/backend/routes/videos.py` lines 325, 597
**Risk:** `update_video` and `update_video_styles` UPDATE queries lack tenant_id in WHERE clause.
**Fix:** Add `AND tenant_id = $X` to WHERE clauses.

---

## MEDIUM Findings

### M1: Export Manifest Exposes Storage URLs
**File:** `storyengine/backend/routes/videos.py` lines 1091-1142
**Risk:** Returns direct Supabase/Google Drive URLs. If storage buckets are misconfigured as public, assets could be accessed without auth.
**Recommendation:** Verify bucket permissions. Consider signed URLs with expiration.

### M2: Parameter Indexing Fragility in videos.py
**File:** `storyengine/backend/routes/videos.py` lines 324-326
**Risk:** Dynamic parameter indexing in `update_video` could lead to type mismatch bugs.
**Recommendation:** Review and add test coverage.

---

## LOW / Informational

### L1: Dev Token Bypass Active
**File:** `storyengine/backend/auth.py` lines 44-47
**Status:** Guarded by DEV_MODE + DEV_TOKEN env vars. Acceptable for development. Must be removed before production.

### L2: CORS allow_methods=["*"] and allow_headers=["*"]
**File:** `storyengine/backend/main.py`
**Status:** Permissive but acceptable. Origins are properly restricted.

---

## Passing Checks

| Check | Status |
|-------|--------|
| JWT expiry validation | PASS |
| Malformed token rejection | PASS |
| All routes (except demo/login/register) require JWT | PASS (except H1) |
| All PRD4 endpoints enforce tenant_id | PASS |
| Demo endpoints return only static data | PASS |
| API keys masked in GET responses | PASS |
| No SQL injection vectors (all parameterized) | PASS |
| No secrets in demo static data | PASS |
| .env files gitignored | PASS |
| CORS allowlist appropriate | PASS |
| Password hashes never returned | PASS |

---

## Recommendations (Priority Order)

1. **Fix C1 + C2 + H2 + H3** — Add `AND tenant_id = $X` to all UPDATE/DELETE WHERE clauses (backend-dev, 1 session)
2. **Fix H1** — Add auth to visual_styles generate/analyze endpoints (backend-dev, 15 min)
3. **Review C3** — Decide on reveal endpoint security (product decision)
4. **Verify M1** — Check Supabase bucket permissions are private (ops task)
5. **Remove L1** — Disable dev token before beta launch (ops task)

---

## Acceptance Criteria Status

- [x] All routes (except demo/login/register) require valid JWT (PASS, except 2 visual_styles endpoints)
- [x] All database queries enforce tenant_id isolation (FAIL — 5 UPDATE queries missing tenant_id)
- [x] No SQL injection vectors found (all parameterized) (PASS)
- [x] Demo endpoints return only hardcoded static data (PASS)
- [x] API keys are never returned unmasked (FAIL — reveal endpoint returns full key)
- [x] No secrets or internal paths exposed in any response (PASS)
- [x] Security report written with findings categorized (PASS — this document)
- [x] All CRITICAL and HIGH findings have fix recommendations (PASS)
