"""StoryEngine Dashboard API — FastAPI backend."""

import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import get_pool, close_pool
from routes import dashboard, videos, assets, activity, review, pipeline, settings, autopilot, skills, agents, niche, channel_profile


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # Startup: create DB pool
    try:
        await get_pool()
        print("✅ Database pool connected")
    except Exception as e:
        print(f"⚠️  Database connection failed (will retry on first query): {e}")
    yield
    # Shutdown
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


@app.get("/api/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "storyengine-api"}
