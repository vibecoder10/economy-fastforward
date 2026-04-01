"""StoryEngine Dashboard API — FastAPI backend."""

import os
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import get_pool, close_pool, fetch_all, fetch_one, execute
from routes import dashboard, videos, assets, activity, review, pipeline, settings, autopilot, skills, agents, niche, channel_profile, projects, visual_styles, discovery, learning_extraction


async def _auto_extract_learnings():
    """Background task: extract learnings from videos with CTR data every 24h.

    This closes the learning feedback loop automatically:
    Videos get CTR data → patterns extracted → stored in learnings table →
    next discovery prompt includes proven/anti patterns → better titles.
    """
    await asyncio.sleep(30)  # Wait for DB pool to stabilize after startup
    while True:
        try:
            # Get the default tenant
            tenant = await fetch_one("SELECT id FROM tenants LIMIT 1")
            if not tenant:
                print("[AutoExtract] No tenant found, skipping")
                await asyncio.sleep(86400)
                continue

            tenant_id = str(tenant["id"])

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
                # Trigger extraction via the existing route logic
                from routes.learning_extraction import extract_learnings as _extract
                result = await _extract(tenant_id=tenant_id)
                print(f"[AutoExtract] Extracted {result.patterns_extracted} patterns from {result.videos_analyzed} videos ({result.patterns_new} new, {result.patterns_updated} updated)")
            else:
                print("[AutoExtract] No new videos to extract from")

        except Exception as e:
            print(f"[AutoExtract] Error: {e}")

        await asyncio.sleep(86400)  # Run every 24 hours


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # Startup: create DB pool
    try:
        await get_pool()
        print("✅ Database pool connected")
    except Exception as e:
        print(f"⚠️  Database connection failed (will retry on first query): {e}")

    # Start background learning extraction loop
    extraction_task = asyncio.create_task(_auto_extract_learnings())

    yield

    # Shutdown
    extraction_task.cancel()
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


@app.get("/api/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "storyengine-api"}
