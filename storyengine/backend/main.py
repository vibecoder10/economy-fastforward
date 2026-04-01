"""StoryEngine Dashboard API — FastAPI backend."""

import os
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import get_pool, close_pool, fetch_all, fetch_one, execute
from routes import dashboard, videos, assets, activity, review, pipeline, settings, autopilot, skills, agents, niche, channel_profile, projects, visual_styles, discovery, learning_extraction, youtube_sync


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
                        from routes.learning_extraction import extract_learnings as _extract
                        result = await _extract(tenant_id=tenant_id)
                        print(f"[AutoExtract] Tenant {tenant_id[:8]}: {result.patterns_extracted} patterns from {result.videos_analyzed} videos ({result.patterns_new} new, {result.patterns_updated} updated)")
                    else:
                        print(f"[AutoExtract] Tenant {tenant_id[:8]}: no new videos")
                except Exception as e:
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
                    from routes.youtube_sync import _run_sync
                    await _run_sync(tenant_id)
                    print(f"[AutoYTSync] Tenant {tenant_id[:8]}: sync complete")
                except Exception as e:
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
                    from routes.learning_extraction import analyze_competitor_titles, analyze_competitor_transcripts
                    result = await analyze_competitor_titles(tenant_id=tenant_id)
                    title_insights = result.get("insights_saved", 0) if isinstance(result, dict) else 0
                    result2 = await analyze_competitor_transcripts(tenant_id=tenant_id)
                    hook_insights = result2.get("insights_saved", 0) if isinstance(result2, dict) else 0
                    print(f"[AutoTitleAnalysis] Tenant {tenant_id[:8]}: {title_insights} title + {hook_insights} hook insights saved")
                except Exception as e:
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
                    from routes.niche import _run_scrape
                    await _run_scrape(tenant_id, max_videos_per_channel=videos_per_scrape)
                    print(f"[AutoScrape] Tenant {tenant_id[:8]}: daily scrape complete ({videos_per_scrape} per channel)")
                except Exception as e:
                    print(f"[AutoScrape] Tenant {tenant_id[:8]} error: {e}")
        except Exception as e:
            print(f"[AutoScrape] Error: {e}")

        await asyncio.sleep(86400)  # Run once daily


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # Startup: create DB pool
    try:
        await get_pool()
        print("✅ Database pool connected")
    except Exception as e:
        print(f"⚠️  Database connection failed (will retry on first query): {e}")

    # Start background tasks (only run for tenants with autopilot enabled)
    extraction_task = asyncio.create_task(_auto_extract_learnings())
    youtube_sync_task = asyncio.create_task(_auto_sync_youtube())
    title_analysis_task = asyncio.create_task(_auto_analyze_competitor_titles())
    scrape_task = asyncio.create_task(_auto_scrape_competitors())

    yield

    # Shutdown
    extraction_task.cancel()
    youtube_sync_task.cancel()
    title_analysis_task.cancel()
    scrape_task.cancel()
    await close_pool()


app = FastAPI(
    title="StoryEngine API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow frontend origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3001",
        "http://localhost:3000",
        "http://76.13.119.181:3000",
        "http://76.13.119.181:3001",
        os.getenv("FRONTEND_URL", "http://localhost:3001"),
    ],
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


@app.get("/api/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "storyengine-api"}
