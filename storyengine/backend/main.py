"""StoryEngine Dashboard API — FastAPI backend."""

import os
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import get_pool, close_pool, fetch_all, fetch_one, execute
from routes import dashboard, videos, assets, activity, review, pipeline, settings, autopilot, skills, agents, niche, channel_profile, projects, visual_styles, discovery, learning_extraction, youtube_sync, analytics, profile, google_auth, billing, preferences, system_prompts, demo
from routes.autopilot import _bg_task_status


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
                print("[AutoExtract] No tenants found, skipping")
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
                        print(f"[AutoExtract] Tenant {tenant_id[:8]}: {result.patterns_extracted} patterns from {result.videos_analyzed} videos ({result.patterns_new} new, {result.patterns_updated} updated)")
                    else:
                        print(f"[AutoExtract] Tenant {tenant_id[:8]}: no new videos")
                except Exception as e:
                    _update_bg_status(tenant_id, "learning_extraction", is_running=False, last_error=str(e))
                    print(f"[AutoExtract] Tenant {tenant_id[:8]} error: {e}")

        except Exception as e:
            print(f"[AutoExtract] Error: {e}")

        await asyncio.sleep(86400)  # Run every 24 hours


async def _auto_sync_youtube():
    """Background task: sync YouTube metrics every 6 hours.

    Only runs for tenants with autopilot ENABLED.
    Pulls views, CTR, impressions, retention from YouTube APIs
    into the videos table so the learning extraction can process them.
    """
    await asyncio.sleep(60)  # Wait for DB pool to stabilize
    while True:
        try:
            tenant_ids = await _get_all_tenant_ids()
            for tenant_id in tenant_ids:
                try:
                    if not await _is_autopilot_enabled(tenant_id):
                        continue
                    _update_bg_status(tenant_id, "youtube_sync", is_running=True, last_error=None)
                    from routes.youtube_sync import _run_sync
                    await _run_sync(tenant_id)
                    _update_bg_status(tenant_id, "youtube_sync", is_running=False, last_run=datetime.now(timezone.utc).isoformat())
                    print(f"[AutoYTSync] Tenant {tenant_id[:8]}: sync complete")
                except Exception as e:
                    _update_bg_status(tenant_id, "youtube_sync", is_running=False, last_error=str(e))
                    print(f"[AutoYTSync] Tenant {tenant_id[:8]} error: {e}")
        except Exception as e:
            print(f"[AutoYTSync] Error: {e}")

        await asyncio.sleep(21600)  # Run every 6 hours


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
                    print(f"[AutoTitleAnalysis] Tenant {tenant_id[:8]}: {title_insights} title + {hook_insights} hook insights saved")
                except Exception as e:
                    _update_bg_status(tenant_id, "title_analysis", is_running=False, last_error=str(e))
                    print(f"[AutoTitleAnalysis] Tenant {tenant_id[:8]} error: {e}")
        except Exception as e:
            print(f"[AutoTitleAnalysis] Error: {e}")

        await asyncio.sleep(86400)  # Run every 24 hours


async def _auto_scrape_competitors():
    """Background task: scrape competitor channels daily.

    Only runs for tenants with autopilot ENABLED.
    Uses the configurable videos_per_scrape setting from autopilot_config.
    Scrapes top-performing videos from competitor channels, extracts
    transcripts and metadata for the learning system.
    """
    await asyncio.sleep(120)  # Offset from other tasks
    while True:
        try:
            tenant_ids = await _get_all_tenant_ids()
            for tenant_id in tenant_ids:
                try:
                    config = await _get_autopilot_config(tenant_id)
                    if not config.get("enabled"):
                        continue
                    videos_per_scrape = config.get("videos_per_scrape", 10)
                    _update_bg_status(tenant_id, "scrape", is_running=True, last_error=None)
                    from routes.niche import _run_scrape
                    await _run_scrape(tenant_id, max_videos_per_channel=videos_per_scrape)
                    _update_bg_status(tenant_id, "scrape", is_running=False, last_run=datetime.now(timezone.utc).isoformat())
                    print(f"[AutoScrape] Tenant {tenant_id[:8]}: daily scrape complete ({videos_per_scrape} per channel)")
                except Exception as e:
                    _update_bg_status(tenant_id, "scrape", is_running=False, last_error=str(e))
                    print(f"[AutoScrape] Tenant {tenant_id[:8]} error: {e}")
        except Exception as e:
            print(f"[AutoScrape] Error: {e}")

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
                print(f"[TrialWarnings] Sent {sent} warning emails ({checked} accounts checked)")
        except Exception as e:
            print(f"[TrialWarnings] Error: {e}")

        await asyncio.sleep(43200)  # Run every 12 hours


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
                print(f"  ✅ Migration applied: {sql_file.name}")
            except Exception as e:
                print(f"  ⚠️  Migration {sql_file.name} failed: {e}")

        print(f"✅ Migrations checked ({len(sql_files)} files, {len(sql_files) - len(applied_set)} new)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # Startup: create DB pool
    try:
        await get_pool()
        print("✅ Database pool connected")
    except Exception as e:
        print(f"⚠️  Database connection failed (will retry on first query): {e}")

    # Auto-run pending migrations
    try:
        await _run_pending_migrations()
    except Exception as e:
        print(f"⚠️  Migration runner error (non-blocking): {e}")

    # Start background tasks (only run for tenants with autopilot enabled)
    extraction_task = asyncio.create_task(_auto_extract_learnings())
    youtube_sync_task = asyncio.create_task(_auto_sync_youtube())
    title_analysis_task = asyncio.create_task(_auto_analyze_competitor_titles())
    scrape_task = asyncio.create_task(_auto_scrape_competitors())
    trial_warning_task = asyncio.create_task(_auto_check_trial_warnings())

    yield

    # Shutdown
    extraction_task.cancel()
    youtube_sync_task.cancel()
    title_analysis_task.cancel()
    scrape_task.cancel()
    trial_warning_task.cancel()
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
app.include_router(analytics.router)
app.include_router(profile.router)
app.include_router(google_auth.router)
app.include_router(billing.router)
app.include_router(preferences.router)
app.include_router(system_prompts.router)
app.include_router(demo.router)


@app.get("/api/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "storyengine-api"}
