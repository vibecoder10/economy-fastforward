# Backend Dev Memory
<!-- Lessons from past sessions. One line each. Max 50 entries. -->
- T8-001 render endpoint already exists (pipeline.py:849). Always grep before building — task descriptions can be stale.
- Adding routes to existing routers does NOT require touching main.py — only new router files need registration.
- T7-003: Pipeline executor bot methods must save result URLs to DB. run_thumbnail was missing thumbnail_url write — compare with run_render pattern.
- T7-004: When adding fields to VideoDetail, ALL THREE places must be updated: Pydantic model (models.py), SQL SELECT, and r.get() constructor mapping. Missing any one = field silently returns null.
- T15-001: New route files need 2 touches in main.py: import line AND app.include_router(). Existing routers (adding endpoints) need 0 touches.
- BUG-PT-001: Dev-mode routes that look up by hardcoded UUID will 404 if the seed migration didn't run. Auto-create on first access with ON CONFLICT DO NOTHING.
- Security audit: EVERY new endpoint must use Depends(get_tenant_id). Never hardcode DEV_TENANT_ID for tenant isolation. Audio proxy endpoints need JWT validation via query token.
- Security audit: API key reveal endpoints should use POST not GET (prevents URL logging), add rate limiting, and log all access to audit trail.
- Pipeline Tester caught SEC-2 REGRESSION: videos.py:459 audio endpoint still uses old os.getenv('ENV', 'development') == 'development' check for dev-token. SEC-1 fixed auth.py but audio has its own inline auth. Must update to match: dev_token = os.getenv('DEV_TOKEN'); if dev_token and token == dev_token and os.getenv('DEV_MODE') == 'true'.
- SEC-7: HTML audio elements can't set Authorization headers, so tokens go in URL query params. Fix: short-lived scoped JWT (5min, purpose=audio, video_id claim) via POST /audio-token. Frontend fetches token before building src URL.
- NEVER name a Python file after a stdlib module (email.py, logging.py, json.py, etc). email.py shadowed stdlib email package, broke jwt/fastapi/httpx imports, caused 404s on ALL auth-dependent routes. Renamed to email_service.py. Delete __pycache__/*.pyc too.
- Security audit (2026-04-08): Always html.escape() user-controlled values (display_name, plan) before interpolating into HTML email templates.
