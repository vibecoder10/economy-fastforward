"""StoryEngine Dashboard API — FastAPI backend."""

import os
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlparse as _urlparse
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from database import get_pool, close_pool, fetch_all, fetch_one, execute
from logging_config import logger, RequestLoggingMiddleware
from rate_limit import RateLimitMiddleware
from routes import dashboard, videos, assets, activity, review, pipeline, settings, autopilot, skills, agents, niche, channel_profile, projects, visual_styles, discovery, learning_extraction, youtube_sync, youtube_channel, analytics, profile, google_auth, billing, preferences, system_prompts, demo, intelligence, model_video, characters, environments, media, chat, onboarding, workspaces, queue, script_templates, model_registry, style_presets, style_descriptions, camera_presets, script_profiles, agent_access
from routes.autopilot import _bg_task_status
from routes.pipeline import recover_stale_tasks, reap_stale_running_tasks
from job_queue import enqueue_stage


def _update_bg_status(tenant_id: str, task_name: str, **kwargs):
    """Update background task status for a tenant."""
    if tenant_id not in _bg_task_status:
        _bg_task_status[tenant_id] = {}
    status = _bg_task_status[tenant_id].get(task_name, {})
    status.update(kwargs)
    _bg_task_status[tenant_id][task_name] = status


async def _get_all_tenant_ids() -> list[str]:
    """Get all tenant IDs for background task iteration."""
    rows = await fetch_all("SELECT id FROM tenants")
    return [str(r["id"]) for r in rows] if rows else []


async def _is_autopilot_enabled(tenant_id: str) -> bool:
    """Check if autopilot is enabled for this tenant."""
    row = await fetch_one(
        "SELECT enabled FROM autopilot_config WHERE tenant_id = $1",
        tenant_id,
    )
    # Default to False if no config exists (user must explicitly enable)
    return bool(row.get("enabled")) if row else False


async def _get_autopilot_config(tenant_id: str) -> dict:
    """Get autopilot config for a tenant, with defaults."""
    row = await fetch_one(
        "SELECT * FROM autopilot_config WHERE tenant_id = $1",
        tenant_id,
    )
    if not row:
        return {"enabled": False, "videos_per_scrape": 10}
    return dict(row)


async def _auto_extract_learnings():
    """Background task: extract learnings from videos with CTR data every 24h.

    Only runs for tenants with autopilot ENABLED.
    Videos get CTR data → patterns extracted → stored in learnings table →
    next discovery prompt includes proven/anti patterns → better titles.
    """
    await asyncio.sleep(30)  # Wait for DB pool to stabilize after startup
    while True:
        try:
            tenant_ids = await _get_all_tenant_ids()
            if not tenant_ids:
                logger.info("[AutoExtract] No tenants found, skipping")
                await asyncio.sleep(86400)
                continue

            for tenant_id in tenant_ids:
                try:
                    if not await _is_autopilot_enabled(tenant_id):
                        continue

                    # Check for unprocessed videos with CTR data
                    videos = await fetch_all(
                        """SELECT id FROM videos
                           WHERE tenant_id = $1
                             AND ctr IS NOT NULL
                             AND COALESCE(impressions, 0) >= 1000
                             AND learnings_extracted_at IS NULL
                           LIMIT 1""",
                        tenant_id,
                    )

                    if videos:
                        _update_bg_status(tenant_id, "learning_extraction", is_running=True, last_error=None)
                        from routes.learning_extraction import extract_learnings as _extract
                        result = await _extract(tenant_id=tenant_id)
                        _update_bg_status(tenant_id, "learning_extraction", is_running=False, last_run=datetime.now(timezone.utc).isoformat())
                        logger.info("[AutoExtract] Tenant %s: %d patterns from %d videos (%d new, %d updated)", tenant_id[:8], result.patterns_extracted, result.videos_analyzed, result.patterns_new, result.patterns_updated)
                    else:
                        logger.info("[AutoExtract] Tenant %s: no new videos", tenant_id[:8])
                except Exception as e:
                    _update_bg_status(tenant_id, "learning_extraction", is_running=False, last_error=str(e))
                    logger.error("[AutoExtract] Tenant %s error: %s", tenant_id[:8], e)

        except Exception as e:
            logger.error("[AutoExtract] Error: %s", e)

        await asyncio.sleep(86400)  # Run every 24 hours


async def _auto_sync_youtube():
    """Background task: sync YouTube metrics once per day.

    Cycle 53 (Stage 6.7 #1): removed the autopilot-enabled gate. Any
    tenant with YouTube credentials (OAuth token in channel_profiles OR
    legacy google_refresh_token in vault) gets a daily metric sync —
    otherwise analytics silently drift out of date for every non-autopilot
    tenant. Tenants with no credentials are skipped to avoid spamming the
    log with "YouTube not connected" noise.

    Interval bumped from 6h → 24h: daily is sufficient for YouTube
    metrics (they aggregate slowly) and reduces API quota pressure.
    """
    await asyncio.sleep(60)  # Wait for DB pool to stabilize
    while True:
        try:
            tenant_ids = await _get_all_tenant_ids()
            for tenant_id in tenant_ids:
                try:
                    # Skip tenants without YouTube credentials — syncing
                    # them would just log an auth error every day.
                    yt_row = await fetch_one(
                        "SELECT youtube_refresh_token FROM channel_profiles WHERE tenant_id = $1",
                        tenant_id,
                    )
                    has_oauth = bool((yt_row or {}).get("youtube_refresh_token"))
                    if not has_oauth:
                        from vault import get_secret
                        legacy = await get_secret("google_refresh_token", tenant_id)
                        if not legacy:
                            continue
                    _update_bg_status(tenant_id, "youtube_sync", is_running=True, last_error=None)
                    from routes.youtube_sync import _run_sync
                    await _run_sync(tenant_id)
                    _update_bg_status(tenant_id, "youtube_sync", is_running=False, last_run=datetime.now(timezone.utc).isoformat())
                    logger.info("[AutoYTSync] Tenant %s: sync complete", tenant_id[:8])
                except Exception as e:
                    _update_bg_status(tenant_id, "youtube_sync", is_running=False, last_error=str(e))
                    logger.error("[AutoYTSync] Tenant %s error: %s", tenant_id[:8], e)
        except Exception as e:
            logger.error("[AutoYTSync] Error: %s", e)

        await asyncio.sleep(86400)  # Run once daily


async def _auto_analyze_competitor_titles():
    """Background task: analyze competitor title patterns every 24h.

    Only runs for tenants with autopilot ENABLED.
    Reads high-VPH competitor videos, detects title patterns,
    writes to title_insights table.
    """
    await asyncio.sleep(90)  # Offset from other tasks
    while True:
        try:
            tenant_ids = await _get_all_tenant_ids()
            for tenant_id in tenant_ids:
                try:
                    if not await _is_autopilot_enabled(tenant_id):
                        continue
                    _update_bg_status(tenant_id, "title_analysis", is_running=True, last_error=None)
                    from routes.learning_extraction import analyze_competitor_titles, analyze_competitor_transcripts
                    result = await analyze_competitor_titles(tenant_id=tenant_id)
                    title_insights = result.get("insights_saved", 0) if isinstance(result, dict) else 0
                    result2 = await analyze_competitor_transcripts(tenant_id=tenant_id)
                    hook_insights = result2.get("insights_saved", 0) if isinstance(result2, dict) else 0
                    _update_bg_status(tenant_id, "title_analysis", is_running=False, last_run=datetime.now(timezone.utc).isoformat())
                    logger.info("[AutoTitleAnalysis] Tenant %s: %d title + %d hook insights saved", tenant_id[:8], title_insights, hook_insights)
                except Exception as e:
                    _update_bg_status(tenant_id, "title_analysis", is_running=False, last_error=str(e))
                    logger.error("[AutoTitleAnalysis] Tenant %s error: %s", tenant_id[:8], e)
        except Exception as e:
            logger.error("[AutoTitleAnalysis] Error: %s", e)

        await asyncio.sleep(86400)  # Run every 24 hours


async def _auto_scrape_competitors():
    """Background task: scrape competitor channels daily.

    Cycle 34 (Stage 6.4 #2): removed the autopilot-enabled gate. Any
    tenant with at least one active competitor_channel row gets a daily
    scrape — otherwise the competitors tab data goes stale within 24h
    (a video scraped today is "24 hours old"; tomorrow it's 48h old but
    we never re-pulled its current view count / VPH). Previously only
    autopilot-enabled tenants benefited.

    Uses `videos_per_scrape` from autopilot_config if set, else defaults
    to 10. Tenants with zero active competitor channels are skipped
    (scraping them would be a no-op + wasted DB round-trip).
    """
    await asyncio.sleep(120)  # Offset from other tasks
    while True:
        try:
            tenant_ids = await _get_all_tenant_ids()
            for tenant_id in tenant_ids:
                try:
                    # Skip tenants with no competitor channels — scraping
                    # them has no effect and spams the log.
                    ch_count_row = await fetch_one(
                        "SELECT COUNT(*) AS cnt FROM competitor_channels "
                        "WHERE tenant_id = $1 AND active = true",
                        tenant_id,
                    )
                    if int((ch_count_row or {}).get("cnt", 0) or 0) == 0:
                        continue
                    config = await _get_autopilot_config(tenant_id)
                    videos_per_scrape = config.get("videos_per_scrape", 10)
                    _update_bg_status(tenant_id, "scrape", is_running=True, last_error=None)
                    from routes.niche import _run_scrape
                    await _run_scrape(tenant_id, max_videos_per_channel=videos_per_scrape)
                    _update_bg_status(tenant_id, "scrape", is_running=False, last_run=datetime.now(timezone.utc).isoformat())
                    logger.info("[AutoScrape] Tenant %s: daily scrape complete (%d per channel)", tenant_id[:8], videos_per_scrape)
                except Exception as e:
                    _update_bg_status(tenant_id, "scrape", is_running=False, last_error=str(e))
                    logger.error("[AutoScrape] Tenant %s error: %s", tenant_id[:8], e)
        except Exception as e:
            logger.error("[AutoScrape] Error: %s", e)

        await asyncio.sleep(86400)  # Run once daily


async def _auto_check_trial_warnings():
    """Background task: send trial expiry warning emails every 12 hours.

    Checks all accounts (cross-tenant) for trials expiring within 3 days.
    Only sends once per account (trial_warning_sent flag).
    """
    await asyncio.sleep(150)  # Offset from other tasks
    while True:
        try:
            from email_tasks import check_trial_warnings
            result = await check_trial_warnings()
            checked = result.get("checked", 0)
            sent = result.get("sent", 0)
            if sent > 0:
                logger.info("[TrialWarnings] Sent %d warning emails (%d accounts checked)", sent, checked)
        except Exception as e:
            logger.error("[TrialWarnings] Error: %s", e)

        await asyncio.sleep(43200)  # Run every 12 hours


async def _auto_check_trial_expired():
    """Background task: downgrade expired-trial accounts to Starter + email them.

    Runs every 6 hours. Idempotent (trial_expired_handled flag prevents repeats).
    Targets accounts with trial_ends_at < now() and no paid subscription.
    """
    await asyncio.sleep(180)  # Offset from trial-warnings task
    while True:
        try:
            from email_tasks import check_trial_expired
            result = await check_trial_expired()
            downgraded = result.get("downgraded", 0)
            if downgraded > 0:
                logger.info(
                    "[TrialExpired] Downgraded %d accounts, emailed %d (%d checked)",
                    downgraded, result.get("emailed", 0), result.get("checked", 0),
                )
        except Exception as e:
            logger.error("[TrialExpired] Error: %s", e)

        await asyncio.sleep(21600)  # Run every 6 hours


async def _auto_reap_stale_tasks():
    """Background task: fail tasks stuck 'running'/'pending' past the stale
    threshold (a dead worker leaves a zombie row that blocks a 1-job-plan
    tenant's whole pipeline). recover_stale_tasks() only runs at startup; this
    runs on a timer so the tenant auto-unblocks without an API restart.

    Runs every 30 minutes. The 3h threshold (in reap_stale_running_tasks) keeps
    it from ever touching a legitimately long-running render.
    """
    await asyncio.sleep(210)  # Offset from the other startup tasks
    while True:
        try:
            reaped = await reap_stale_running_tasks()
            if reaped:
                logger.info("[Reaper] Failed %d stale background task(s)", reaped)
        except Exception as e:
            logger.error("[Reaper] Error: %s", e)

        await asyncio.sleep(1800)  # Run every 30 minutes


async def _run_pending_migrations():
    """Auto-run SQL migration files on startup.

    Tracks which migrations have run in a `_migrations` table.
    Each .sql file in migrations/ runs exactly once, in order.
    Non-blocking — errors are logged but don't prevent startup.
    """
    import pathlib

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Ensure migrations tracking table exists (RLS enabled, no client access)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("ALTER TABLE _migrations ENABLE ROW LEVEL SECURITY")
        await conn.execute("REVOKE ALL ON _migrations FROM anon")
        await conn.execute("REVOKE ALL ON _migrations FROM authenticated")

        # Get already-applied migrations
        applied = await conn.fetch("SELECT filename FROM _migrations")
        applied_set = {r["filename"] for r in applied}

        # Find and run pending migrations in order
        migrations_dir = pathlib.Path(__file__).parent / "migrations"
        if not migrations_dir.exists():
            return

        sql_files = sorted(migrations_dir.glob("*.sql"))
        for sql_file in sql_files:
            if sql_file.name in applied_set:
                continue
            try:
                sql = sql_file.read_text()
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO _migrations (filename) VALUES ($1)",
                    sql_file.name,
                )
                logger.info("Migration applied: %s", sql_file.name)
            except Exception as e:
                logger.warning("Migration %s failed: %s", sql_file.name, e)

        logger.info("Migrations checked (%d files, %d new)", len(sql_files), len(sql_files) - len(applied_set))


async def _auto_distill_intelligence():
    """Background task: distill new competitor transcripts every 12h.

    Only runs for tenants with autopilot ENABLED.
    Extracts structured DNA (hook, title, content, retention, villain, thumbnail)
    from competitor video transcripts and stores in content_intelligence table
    with vector embeddings for semantic search.
    """
    await asyncio.sleep(120)  # Offset from other startup tasks
    while True:
        try:
            tenant_ids = await _get_all_tenant_ids()
            for tenant_id in tenant_ids:
                try:
                    if not await _is_autopilot_enabled(tenant_id):
                        continue
                    _update_bg_status(tenant_id, "distillation", is_running=True, last_error=None)
                    from distillation.pipeline import backfill_competitor_transcripts
                    result = await backfill_competitor_transcripts(tenant_id, batch_size=25)
                    _update_bg_status(tenant_id, "distillation", is_running=False, last_run=datetime.now(timezone.utc).isoformat())
                    processed = result.get("processed", 0) if isinstance(result, dict) else 0
                    logger.info("[AutoDistill] Tenant %s: %d videos distilled", tenant_id[:8], processed)
                except Exception as e:
                    _update_bg_status(tenant_id, "distillation", is_running=False, last_error=str(e))
                    logger.error("[AutoDistill] Tenant %s error: %s", tenant_id[:8], e)
        except Exception as e:
            logger.error("[AutoDistill] Error: %s", e)

        await asyncio.sleep(43200)  # Every 12 hours


async def _auto_produce_queue():
    """Background task: drain the creator's own production queue, every 30 min.

    Only runs for tenants with autopilot ENABLED. The queue (CSV titles dropped
    into chat, "queue these") wins over scored competitor candidates: when a
    video is due (production_interval_days cadence, shared with autopilot
    launches) and nothing is in flight, the front of the queue is claimed and
    launched (routes/queue.py:auto_produce_next — FOR UPDATE SKIP LOCKED, so a
    manual Build can't race this loop)."""
    await asyncio.sleep(240)  # Offset from other startup tasks
    while True:
        try:
            tenant_ids = await _get_all_tenant_ids()
            for tenant_id in tenant_ids:
                try:
                    if not await _is_autopilot_enabled(tenant_id):
                        continue
                    from routes.queue import auto_produce_next
                    result = await auto_produce_next(tenant_id)
                    if result:
                        logger.info(
                            "[AutoQueue] Tenant %s launched queued video %s (%s)",
                            tenant_id[:8], result.get("video_id"), result.get("video_title"),
                        )
                except Exception as e:
                    logger.error("[AutoQueue] Tenant %s error: %s", tenant_id[:8], e)
        except Exception as e:
            logger.error("[AutoQueue] Error: %s", e)

        await asyncio.sleep(1800)  # Every 30 minutes


async def _auto_generate_meta_insights():
    """Background task: generate niche meta-insights every 24h.

    Only runs for tenants with autopilot ENABLED and 20+ distilled videos.
    Produces second-order distillation: cross-video meta-analysis of niche patterns
    stored in niche_meta_insights table.
    """
    await asyncio.sleep(180)  # Offset from other startup tasks
    while True:
        try:
            tenant_ids = await _get_all_tenant_ids()
            for tenant_id in tenant_ids:
                try:
                    if not await _is_autopilot_enabled(tenant_id):
                        continue
                    from distillation.meta_analyzer import generate_niche_meta_insights
                    result = await generate_niche_meta_insights(tenant_id)
                    if result:
                        logger.info("[AutoMetaInsights] Tenant %s: generated (%d videos)", tenant_id[:8], result.get("sample_size", 0))
                except Exception as e:
                    logger.error("[AutoMetaInsights] Tenant %s error: %s", tenant_id[:8], e)
        except Exception as e:
            logger.error("[AutoMetaInsights] Error: %s", e)

        await asyncio.sleep(86400)  # Every 24 hours


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # Startup: create DB pool
    try:
        await get_pool()
        logger.info("Database pool connected")
    except Exception as e:
        logger.warning("Database connection failed (will retry on first query): %s", e)

    # arq job queue pool (Redis)
    try:
        from arq import create_pool
        from arq.connections import RedisSettings
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        _parsed = _urlparse(redis_url)
        _host = _parsed.hostname or "localhost"
        _port = _parsed.port or 6379
        app.state.arq = await create_pool(RedisSettings(host=_host, port=_port))
        logger.info("arq pool connected to Redis at %s:%d", _host, _port)
    except Exception as e:
        app.state.arq = None
        logger.warning("Redis/arq pool not available (queue features disabled): %s", e)

    # Auto-run pending migrations
    try:
        await _run_pending_migrations()
    except Exception as e:
        logger.warning("Migration runner error (non-blocking): %s", e)

    # Recover tasks that were running when the server last stopped
    try:
        recovered = await recover_stale_tasks()
        if recovered:
            logger.info("Recovered %d stale background tasks (marked as failed)", recovered)

        # Re-enqueue stale tasks via arq if Redis is available
        if getattr(app.state, "arq", None):
            stale_rows = await fetch_all(
                "SELECT video_id, task_type, tenant_id, COALESCE(attempt, 1) AS attempt "
                "FROM background_tasks "
                "WHERE status = 'failed' "
                "AND error_message = 'Server restarted — task interrupted' "
                "AND completed_at >= now() - interval '10 minutes'"
            )
            for row in stale_rows or []:
                new_attempt = row["attempt"] + 1
                if new_attempt <= 3:
                    try:
                        await enqueue_stage(
                            app.state.arq,
                            row["task_type"],
                            str(row["video_id"]),
                            str(row["tenant_id"]),
                            new_attempt,
                        )
                    except (ValueError, Exception) as eq:
                        logger.warning("Could not re-enqueue %s: %s", row["task_type"], eq)
    except Exception as e:
        logger.warning("Stale task recovery error (non-blocking): %s", e)

    # Start background tasks (only run for tenants with autopilot enabled)
    extraction_task = asyncio.create_task(_auto_extract_learnings())
    youtube_sync_task = asyncio.create_task(_auto_sync_youtube())
    title_analysis_task = asyncio.create_task(_auto_analyze_competitor_titles())
    scrape_task = asyncio.create_task(_auto_scrape_competitors())
    trial_warning_task = asyncio.create_task(_auto_check_trial_warnings())
    trial_expired_task = asyncio.create_task(_auto_check_trial_expired())
    distillation_task = asyncio.create_task(_auto_distill_intelligence())
    meta_insights_task = asyncio.create_task(_auto_generate_meta_insights())
    reaper_task = asyncio.create_task(_auto_reap_stale_tasks())
    produce_queue_task = asyncio.create_task(_auto_produce_queue())

    yield

    # Shutdown
    if getattr(app.state, "arq", None):
        await app.state.arq.aclose()
    extraction_task.cancel()
    youtube_sync_task.cancel()
    title_analysis_task.cancel()
    scrape_task.cancel()
    trial_warning_task.cancel()
    trial_expired_task.cancel()
    distillation_task.cancel()
    meta_insights_task.cancel()
    reaper_task.cancel()
    produce_queue_task.cancel()
    await close_pool()


app = FastAPI(
    title="StoryEngine API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — origins from ALLOWED_ORIGINS env var (comma-separated)
# Defaults to localhost dev servers if not set
_default_origins = "http://localhost:3001,http://localhost:3000"
_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",")
    if o.strip()
]
_frontend_url = os.getenv("FRONTEND_URL")
if _frontend_url and _frontend_url not in _origins:
    _origins.append(_frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting + request logging (added AFTER CORS so they run on CORS-allowed requests)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestLoggingMiddleware)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all so an uncaught error returns clean JSON instead of a raw 500
    that could leak internals. HTTPException keeps its own (more specific)
    handler, so this only fires for genuinely unhandled exceptions."""
    from fastapi.responses import JSONResponse
    from logging_config import track_error
    from error_utils import humanize_error
    try:
        track_error()
    except Exception:
        pass
    logger.error(
        "Unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path,
        exc_info=exc,
    )
    return JSONResponse(status_code=500, content={"detail": humanize_error(exc)})

# Register routes
app.include_router(dashboard.router)
app.include_router(videos.router)
app.include_router(assets.router)
app.include_router(activity.router)
app.include_router(review.router)
app.include_router(pipeline.router)
app.include_router(settings.router)
app.include_router(autopilot.router)
app.include_router(skills.router)
app.include_router(agents.router)
app.include_router(niche.router)
app.include_router(channel_profile.router)
app.include_router(projects.router)
app.include_router(visual_styles.router)
app.include_router(discovery.router)
app.include_router(learning_extraction.router)
app.include_router(youtube_sync.router)
app.include_router(youtube_channel.router)
app.include_router(analytics.router)
app.include_router(profile.router)
app.include_router(google_auth.router)
app.include_router(billing.router)
app.include_router(preferences.router)
app.include_router(system_prompts.router)
app.include_router(demo.router)
app.include_router(intelligence.router)
app.include_router(model_video.router)
app.include_router(model_registry.router)
app.include_router(style_presets.router)
app.include_router(style_descriptions.router)
app.include_router(camera_presets.router)
app.include_router(script_profiles.router)
app.include_router(characters.router)
app.include_router(environments.router)
app.include_router(media.router)
app.include_router(chat.router)
app.include_router(onboarding.router)
app.include_router(workspaces.router)
app.include_router(queue.router)
app.include_router(script_templates.router)
app.include_router(agent_access.router)

# StoryEngine MCP server (checklist P2.4a, chunk C26 — tasks/storyengine-
# copilot-ux-map.md §7, "the Higgsfield-killer door"). DARK BY DEFAULT: the
# router only registers when MCP_ENABLED=true, so with the env var unset or
# false these routes structurally do not exist (a request 404s, same as any
# other undefined path — there is nothing "there but blocked" to probe).
# Left off until a coordinated deploy flips the flag: C25a's Drive media-
# proxy tenant-auth fix is held on `claude/c25a-media-auth-hold` and NOT on
# this branch, and nothing external may reach an MCP tool result until that
# lands (see docs/reports/2026-07-17-storyengine-agent-audit-findings.md §S5
# and routes/mcp.py's module docstring — the v1 tool surface avoids media
# URLs anyway, but the flag is the belt to that suspenders).
if os.getenv("MCP_ENABLED", "").lower() == "true":
    from routes import mcp as mcp_routes
    app.include_router(mcp_routes.router)


@app.get("/api/health")
async def health():
    """Health check with real system status."""
    checks: dict = {}

    # Database connectivity
    try:
        await fetch_one("SELECT 1 as ok")
        checks["database"] = True
    except Exception:
        checks["database"] = False

    # Active background tasks
    try:
        row = await fetch_one(
            "SELECT count(*) as cnt FROM background_tasks WHERE status = 'running'"
        )
        checks["active_tasks"] = row["cnt"] if row else 0
    except Exception:
        checks["active_tasks"] = -1

    # Storage (basic check — Google Drive client initialized)
    checks["storage"] = True  # Will fail visibly on actual upload if broken

    # Queue mode (C16d, S7-7): when the arq/Redis pool failed to connect at
    # startup (see the lifespan warning above, "Redis/arq pool not available"),
    # every pipeline stage silently falls back to in-process BackgroundTasks —
    # this is a supported degraded mode (docs/failure-modes.md), not a crash,
    # but it was previously invisible outside the startup log line. Surfaced
    # here as data only; no UI banner yet (tracked as a frontend follow-up).
    checks["queue"] = "arq" if getattr(app.state, "arq", None) else "degraded-inprocess"

    # Overall status
    if checks.get("database") is True:
        status = "healthy"
    else:
        status = "unhealthy"

    return {"status": status, "service": "storyengine-api", **checks}


@app.get("/api/health/detailed")
async def health_detailed(request: Request):
    """Extended health check — protected by HEALTH_TOKEN env var.

    Returns task queue depth, error rate, and resource info.

    Fails CLOSED (S5-7): this endpoint returns internal error-rate, task
    queue depth, and memory/uptime info — it must never serve without a
    token configured. An unset HEALTH_TOKEN previously made the `if token
    and ...` check a no-op, serving the endpoint to anyone. Now a missing
    HEALTH_TOKEN 503s instead. The plain /api/health check above stays
    public on purpose (needed unauthenticated by uptime monitors and the
    queue-status field, C16d/S7-7) — this fix does not touch it.
    """
    from fastapi import HTTPException

    token = os.getenv("HEALTH_TOKEN")
    if not token:
        raise HTTPException(
            status_code=503,
            detail="Health detailed endpoint disabled — HEALTH_TOKEN not configured",
        )
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != token:
        raise HTTPException(status_code=401, detail="Invalid health token")

    checks: dict = {}

    # DB
    try:
        await fetch_one("SELECT 1 as ok")
        checks["database"] = True
    except Exception:
        checks["database"] = False

    # Task queue depth by status
    try:
        rows = await fetch_all(
            "SELECT status, count(*) as cnt FROM background_tasks GROUP BY status"
        )
        checks["task_queue"] = {r["status"]: r["cnt"] for r in rows} if rows else {}
    except Exception:
        checks["task_queue"] = {"error": "query failed"}

    # Queue mode (C16d, S7-7) — see /api/health for the full rationale.
    checks["queue"] = "arq" if getattr(app.state, "arq", None) else "degraded-inprocess"

    # Error rate (from logging_config tracker)
    from logging_config import _error_counts, _error_window_start
    import time
    window_age = round(time.time() - _error_window_start)
    checks["error_rate"] = {
        "errors_in_window": _error_counts.get("total", 0),
        "window_seconds": min(window_age, 300),
    }

    # Uptime / memory (optional — psutil may not be installed)
    try:
        import psutil
        process = psutil.Process()
        checks["uptime_seconds"] = round(time.time() - process.create_time())
        checks["memory_mb"] = round(process.memory_info().rss / 1024 / 1024, 1)
    except ImportError:
        pass

    status = "healthy" if checks.get("database") else "unhealthy"
    return {"status": status, **checks}
