"""Demo mode — static endpoints with sample data. No auth required."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/demo", tags=["demo"])

DEMO_VIDEOS = [
    {
        "id": "demo-1",
        "video_title": "How China's $50B Chip War Backfired",
        "status": "done",
        "views": 142000,
        "ctr": 8.3,
        "avg_retention": 42.1,
        "thumbnail_url": None,
    },
    {
        "id": "demo-2",
        "video_title": "The Secret Arms Deal That Changed Everything",
        "status": "ready_for_thumbnail",
        "views": 0,
        "ctr": None,
        "avg_retention": None,
        "thumbnail_url": None,
    },
    {
        "id": "demo-3",
        "video_title": "Why Nobody Can Stop the Houthi Blockade",
        "status": "done",
        "views": 87500,
        "ctr": 6.1,
        "avg_retention": 38.7,
        "thumbnail_url": None,
    },
]


@router.get("/dashboard")
async def demo_dashboard():
    return {
        "active_bots": 3,
        "pending_review": 1,
        "pipeline_distribution": {
            "idea_logged": 2,
            "ready_for_scripting": 1,
            "ready_for_images": 1,
            "done": 3,
        },
        "cost_today": 4.25,
        "total_videos": 7,
        "recent_videos": DEMO_VIDEOS,
    }


@router.get("/analytics")
async def demo_analytics():
    return {
        "total_videos": 7,
        "total_views": 312500,
        "avg_ctr": 6.8,
        "avg_retention": 39.2,
        "published_videos": 5,
        "ctr_timeline": [
            {"video_title": "How China's $50B Chip War Backfired", "ctr": 8.3, "views": 142000, "date": "2026-03-15"},
            {"video_title": "Why Nobody Can Stop the Houthi Blockade", "ctr": 6.1, "views": 87500, "date": "2026-03-22"},
            {"video_title": "Iran's Nuclear Gambit", "ctr": 5.9, "views": 54000, "date": "2026-03-29"},
        ],
        "framework_performance": [
            {"framework": "Asymmetric Warfare", "video_count": 3, "avg_ctr": 7.2},
            {"framework": "Sun Tzu", "video_count": 2, "avg_ctr": 5.8},
        ],
    }


@router.get("/pipeline")
async def demo_pipeline():
    return {
        "stages": [
            {"name": "idea_logged", "count": 2},
            {"name": "ready_for_scripting", "count": 1},
            {"name": "ready_for_voice", "count": 0},
            {"name": "ready_for_images", "count": 1},
            {"name": "ready_for_thumbnail", "count": 1},
            {"name": "ready_to_render", "count": 0},
            {"name": "done", "count": 3},
        ],
        "recent_activity": [
            {"bot": "script-bot", "video_title": "The Secret Arms Deal That Changed Everything", "status": "completed", "message": "Script generated: 6 scenes"},
            {"bot": "image-bot", "video_title": "How China's $50B Chip War Backfired", "status": "completed", "message": "120 images generated"},
        ],
        "videos": DEMO_VIDEOS,
    }
