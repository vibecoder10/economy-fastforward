"""Channel profile transparency documents.

Builds small Word documents from the same data StoryEngine uses for channel
learning, then stores them in the user's own Google Drive profile folder.
"""

import asyncio
import io
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape

from database import execute, fetch_all, fetch_one

PIPELINE_PATH = Path(__file__).parent.parent.parent / "skills" / "video-pipeline"
if str(PIPELINE_PATH) not in sys.path:
    sys.path.insert(0, str(PIPELINE_PATH))

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PROFILE_FOLDER_NAME = "StoryEngine Profile"


async def ensure_profile_document_schema() -> None:
    """Keep the feature resilient if migrations have not run yet."""
    for ddl in [
        "ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS profile_drive_folder_id TEXT",
        "ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS profile_drive_folder_link TEXT",
        "ALTER TABLE channel_profiles ADD COLUMN IF NOT EXISTS channel_dna_updated_at TIMESTAMPTZ",
        "ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS transcript TEXT",
        "ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS transcript_source TEXT",
        "ALTER TABLE channel_videos ADD COLUMN IF NOT EXISTS transcript_fetched_at TIMESTAMPTZ",
        "ALTER TABLE visual_styles ADD COLUMN IF NOT EXISTS proof_image_url TEXT",
        "ALTER TABLE visual_styles ADD COLUMN IF NOT EXISTS proof_drive_url TEXT",
        "ALTER TABLE visual_styles ADD COLUMN IF NOT EXISTS proof_drive_file_id TEXT",
        "ALTER TABLE visual_styles ADD COLUMN IF NOT EXISTS proof_prompt TEXT",
        "ALTER TABLE visual_styles ADD COLUMN IF NOT EXISTS proof_model TEXT",
        "ALTER TABLE visual_styles ADD COLUMN IF NOT EXISTS proof_status TEXT DEFAULT 'not_generated'",
        "ALTER TABLE visual_styles ADD COLUMN IF NOT EXISTS proof_generated_at TIMESTAMPTZ",
        "ALTER TABLE visual_styles ADD COLUMN IF NOT EXISTS proof_approved_at TIMESTAMPTZ",
        """CREATE TABLE IF NOT EXISTS channel_profile_documents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            doc_type TEXT NOT NULL,
            title TEXT NOT NULL,
            drive_file_id TEXT NOT NULL,
            drive_url TEXT NOT NULL,
            drive_folder_id TEXT,
            source_counts JSONB DEFAULT '{}'::jsonb,
            metadata JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE (tenant_id, doc_type)
        )""",
    ]:
        await execute(ddl)


async def get_channel_profile_documents(tenant_id: str) -> dict:
    await ensure_profile_document_schema()
    profile = await fetch_one(
        """SELECT profile_drive_folder_id, profile_drive_folder_link, channel_dna_updated_at
           FROM channel_profiles WHERE tenant_id = $1""",
        tenant_id,
    )
    docs = await fetch_all(
        """SELECT doc_type, title, drive_file_id, drive_url, drive_folder_id,
                  source_counts, metadata, updated_at::text
           FROM channel_profile_documents
           WHERE tenant_id = $1
           ORDER BY doc_type""",
        tenant_id,
    )
    counts = await _collect_counts(tenant_id)
    return {
        "folder_id": (profile or {}).get("profile_drive_folder_id"),
        "folder_url": (profile or {}).get("profile_drive_folder_link"),
        "last_refreshed_at": (profile or {}).get("channel_dna_updated_at"),
        "source_counts": counts,
        "documents": [_normalize_doc_row(row) for row in docs or []],
    }


async def refresh_channel_profile_documents(
    tenant_id: str,
    transcript_limit: int = 5,
) -> dict:
    """Refresh Drive docs and return the new document inventory."""
    await ensure_profile_document_schema()
    transcript_result = await backfill_channel_video_transcripts(tenant_id, transcript_limit)
    data = await _collect_profile_data(tenant_id)
    data["transcript_backfill"] = transcript_result

    client, parent_folder_id = await _get_tenant_drive_client(tenant_id)
    profile_folder = _get_or_create_child_folder(client, PROFILE_FOLDER_NAME, parent_folder_id)
    folder_id = profile_folder["id"]
    folder_url = f"https://drive.google.com/drive/folders/{folder_id}"

    documents = _build_documents(data)
    saved_docs = []
    source_counts = data["source_counts"]
    for doc_type, payload in documents.items():
        file_info = client.upload_file(
            content=payload["content"],
            name=payload["filename"],
            folder_id=folder_id,
            mime_type=DOCX_MIME,
            check_existing=True,
        )
        drive_url = f"https://drive.google.com/file/d/{file_info['id']}/view"
        await execute(
            """INSERT INTO channel_profile_documents (
                 tenant_id, doc_type, title, drive_file_id, drive_url,
                 drive_folder_id, source_counts, metadata, updated_at
               ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, now())
               ON CONFLICT (tenant_id, doc_type) DO UPDATE SET
                 title = EXCLUDED.title,
                 drive_file_id = EXCLUDED.drive_file_id,
                 drive_url = EXCLUDED.drive_url,
                 drive_folder_id = EXCLUDED.drive_folder_id,
                 source_counts = EXCLUDED.source_counts,
                 metadata = EXCLUDED.metadata,
                 updated_at = now()""",
            tenant_id,
            doc_type,
            payload["title"],
            file_info["id"],
            drive_url,
            folder_id,
            json.dumps(source_counts),
            json.dumps(payload.get("metadata") or {}),
        )
        saved_docs.append({
            "doc_type": doc_type,
            "title": payload["title"],
            "drive_file_id": file_info["id"],
            "drive_url": drive_url,
            "drive_folder_id": folder_id,
            "source_counts": source_counts,
            "metadata": payload.get("metadata") or {},
        })

    await execute(
        """UPDATE channel_profiles
           SET profile_drive_folder_id = $1,
               profile_drive_folder_link = $2,
               channel_dna_updated_at = now(),
               updated_at = now()
           WHERE tenant_id = $3""",
        folder_id,
        folder_url,
        tenant_id,
    )

    return {
        "status": "complete",
        "folder_id": folder_id,
        "folder_url": folder_url,
        "documents": saved_docs,
        "source_counts": source_counts,
        "transcript_backfill": transcript_result,
    }


async def backfill_channel_video_transcripts(tenant_id: str, limit: int = 5) -> dict:
    """Fetch a small batch of missing own-channel transcripts via yt-dlp."""
    limit = max(0, min(limit, 10))
    if limit == 0:
        return {"attempted": 0, "saved": 0, "failed": 0}

    rows = await fetch_all(
        """SELECT id, video_id, title
           FROM channel_videos
           WHERE tenant_id = $1
             AND video_id IS NOT NULL
             AND (transcript IS NULL OR transcript = '')
             AND (transcript_fetched_at IS NULL OR transcript_fetched_at < now() - interval '7 days')
           ORDER BY view_count DESC NULLS LAST, published_at DESC NULLS LAST
           LIMIT $2""",
        tenant_id,
        limit,
    )

    attempted = 0
    saved = 0
    failed = 0
    for row in rows or []:
        attempted += 1
        try:
            from routes.niche import _extract_video_info

            info = await asyncio.to_thread(_extract_video_info, row["video_id"])
            transcript = (info or {}).get("transcript")
            metadata = {
                "transcript_fetch": {
                    "status": "saved" if transcript else "unavailable",
                    "source": "yt-dlp",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
            }
            await execute(
                """UPDATE channel_videos
                   SET transcript = COALESCE($3, transcript),
                       transcript_source = $4,
                       transcript_fetched_at = now(),
                       duration_seconds = COALESCE($5, duration_seconds),
                       thumbnail_url = COALESCE($6, thumbnail_url),
                       metadata = COALESCE(metadata, '{}'::jsonb) || $7::jsonb,
                       updated_at = now()
                   WHERE id = $1 AND tenant_id = $2""",
                row["id"],
                tenant_id,
                transcript,
                "yt-dlp" if transcript else "unavailable",
                (info or {}).get("duration_seconds"),
                (info or {}).get("thumbnail_url"),
                json.dumps(metadata),
            )
            if transcript:
                saved += 1
            else:
                failed += 1
        except Exception:
            failed += 1

    return {"attempted": attempted, "saved": saved, "failed": failed}


async def _get_tenant_drive_client(tenant_id: str):
    profile = await fetch_one(
        """SELECT google_drive_refresh_token, google_drive_folder_id
           FROM channel_profiles WHERE tenant_id = $1""",
        tenant_id,
    )
    if not profile or not profile.get("google_drive_refresh_token"):
        raise ValueError("Google Drive is not connected.")
    if not profile.get("google_drive_folder_id"):
        raise ValueError("Choose a Google Drive parent folder before creating profile docs.")

    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError("Google OAuth client credentials are not configured.")

    from shared.clients.google_client import GoogleClient

    client = GoogleClient(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=profile["google_drive_refresh_token"],
    )
    client.parent_folder_id = profile["google_drive_folder_id"]
    return client, profile["google_drive_folder_id"]


def _get_or_create_child_folder(client: Any, name: str, parent_id: str) -> dict:
    escaped_name = name.replace("'", "\\'")
    query = (
        f"name = '{escaped_name}' and '{parent_id}' in parents and "
        "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    results = client.drive_service.files().list(
        q=query,
        fields="files(id, name, mimeType)",
        pageSize=10,
    ).execute()
    files = results.get("files", [])
    if files:
        return files[0]
    return client.create_folder(name, parent_id=parent_id)


async def _collect_counts(tenant_id: str) -> dict:
    channel = await fetch_one(
        """SELECT COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE transcript IS NOT NULL AND transcript <> '') AS with_transcripts,
                  COUNT(*) FILTER (WHERE ctr_percent IS NOT NULL) AS with_ctr,
                  COUNT(*) FILTER (
                    WHERE avg_view_duration_seconds IS NOT NULL OR avg_retention IS NOT NULL
                  ) AS with_retention
           FROM channel_videos
           WHERE tenant_id = $1""",
        tenant_id,
    )
    competitors = await fetch_one(
        """SELECT COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE transcript IS NOT NULL AND transcript <> '') AS with_transcripts,
                  COUNT(*) FILTER (WHERE distilled_at IS NOT NULL) AS distilled
           FROM competitor_videos
           WHERE tenant_id = $1""",
        tenant_id,
    )
    learnings = await fetch_one(
        """SELECT COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE active = true) AS active
           FROM learnings
           WHERE tenant_id = $1""",
        tenant_id,
    )
    return {
        "channel_videos": _as_count_dict(channel, ["total", "with_transcripts", "with_ctr", "with_retention"]),
        "competitor_videos": _as_count_dict(competitors, ["total", "with_transcripts", "distilled"]),
        "learnings": _as_count_dict(learnings, ["total", "active"]),
    }


async def _collect_profile_data(tenant_id: str) -> dict:
    profile = await fetch_one(
        """SELECT channel_name, niche, target_audience, style_description,
                  youtube_channel_id, youtube_channel_name
           FROM channel_profiles
           WHERE tenant_id = $1""",
        tenant_id,
    )
    project = await fetch_one(
        """SELECT name, niche, target_audience, frameworks
           FROM projects
           WHERE tenant_id = $1
           ORDER BY updated_at DESC NULLS LAST
           LIMIT 1""",
        tenant_id,
    )
    channel_videos = await fetch_all(
        """SELECT title, video_id, view_count, impressions, ctr_percent,
                  avg_view_duration_seconds, avg_retention, published_at::text,
                  LEFT(transcript, 700) AS transcript_excerpt
           FROM channel_videos
           WHERE tenant_id = $1
           ORDER BY ctr_percent DESC NULLS LAST, view_count DESC NULLS LAST
           LIMIT 12""",
        tenant_id,
    )
    transcript_examples = await fetch_all(
        """SELECT title, video_id, LEFT(transcript, 900) AS excerpt
           FROM channel_videos
           WHERE tenant_id = $1
             AND transcript IS NOT NULL AND transcript <> ''
           ORDER BY view_count DESC NULLS LAST
           LIMIT 8""",
        tenant_id,
    )
    hook_rows = await fetch_all(
        """SELECT COALESCE(
                    ci.structured_metadata->'hook_dna'->>'type',
                    ci.structured_metadata->'hook'->>'type'
                  ) AS hook_type,
                  COUNT(*) AS count,
                  ROUND(AVG(cv.vph)::numeric, 1) AS avg_vph
           FROM content_intelligence ci
           JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
           WHERE ci.tenant_id = $1
             AND ci.source_type = 'competitor_transcript'
             AND COALESCE(
                   ci.structured_metadata->'hook_dna'->>'type',
                   ci.structured_metadata->'hook'->>'type'
                 ) IS NOT NULL
           GROUP BY hook_type
           ORDER BY count DESC, avg_vph DESC NULLS LAST
           LIMIT 10""",
        tenant_id,
    )
    tone_rows = await fetch_all(
        """SELECT ci.structured_metadata->'content_dna'->>'tone' AS tone,
                  COUNT(*) AS count,
                  ROUND(AVG(cv.vph)::numeric, 1) AS avg_vph
           FROM content_intelligence ci
           JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
           WHERE ci.tenant_id = $1
             AND ci.source_type = 'competitor_transcript'
             AND ci.structured_metadata->'content_dna'->>'tone' IS NOT NULL
           GROUP BY tone
           ORDER BY count DESC, avg_vph DESC NULLS LAST
           LIMIT 10""",
        tenant_id,
    )
    competitor_examples = await fetch_all(
        """SELECT cv.title, cv.channel, cv.vph, ci.summary, ci.structured_metadata
           FROM content_intelligence ci
           JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
           WHERE ci.tenant_id = $1
             AND ci.source_type = 'competitor_transcript'
           ORDER BY cv.vph DESC NULLS LAST
           LIMIT 10""",
        tenant_id,
    )
    learnings = await fetch_all(
        """SELECT category, pattern, avg_ctr, avg_retention, sample_size, confidence
           FROM learnings
           WHERE tenant_id = $1 AND active = true
           ORDER BY confidence DESC NULLS LAST, sample_size DESC NULLS LAST
           LIMIT 20""",
        tenant_id,
    )
    production_video = await _collect_production_video_profile(tenant_id)
    source_counts = await _collect_counts(tenant_id)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": dict(profile or {}),
        "project": dict(project or {}),
        "source_counts": source_counts,
        "channel_videos": [dict(row) for row in channel_videos or []],
        "transcript_examples": [dict(row) for row in transcript_examples or []],
        "hook_rows": [dict(row) for row in hook_rows or []],
        "tone_rows": [dict(row) for row in tone_rows or []],
        "competitor_examples": [_normalize_competitor_example(row) for row in competitor_examples or []],
        "learnings": [dict(row) for row in learnings or []],
        "production_video": production_video,
    }


def _build_documents(data: dict) -> dict:
    generated = data["generated_at"]
    return {
        "channel_dna_profile": {
            "title": "Channel DNA Profile",
            "filename": "Channel DNA Profile.docx",
            "content": _docx_bytes("Channel DNA Profile", _channel_dna_lines(data)),
            "metadata": {"generated_at": generated},
        },
        "transcript_evidence_index": {
            "title": "Transcript Evidence Index",
            "filename": "Transcript Evidence Index.docx",
            "content": _docx_bytes("Transcript Evidence Index", _transcript_index_lines(data)),
            "metadata": {"generated_at": generated},
        },
        "script_guidance_receipt": {
            "title": "Script Guidance Receipt",
            "filename": "Script Guidance Receipt.docx",
            "content": _docx_bytes("Script Guidance Receipt", _script_guidance_lines(data)),
            "metadata": {"generated_at": generated},
        },
        "visual_generation_profile": {
            "title": "Visual Generation Profile",
            "filename": "Visual Generation Profile.docx",
            "content": _docx_bytes("Visual Generation Profile", _visual_generation_lines(data)),
            "metadata": {"generated_at": generated},
        },
    }


def _channel_dna_lines(data: dict) -> list[tuple[str, str]]:
    profile = data.get("profile") or {}
    project = data.get("project") or {}
    counts = data["source_counts"]
    lines = [
        ("Heading1", "Channel DNA Profile"),
        ("Normal", f"Generated at: {data['generated_at']}"),
        ("Heading2", "Channel"),
        ("Normal", f"Name: {profile.get('youtube_channel_name') or profile.get('channel_name') or project.get('name') or 'Not set'}"),
        ("Normal", f"Niche: {project.get('niche') or profile.get('niche') or 'Not set'}"),
        ("Normal", f"Target audience: {project.get('target_audience') or profile.get('target_audience') or 'Not set'}"),
        ("Normal", f"Style description: {profile.get('style_description') or 'Not set'}"),
        ("Heading2", "Source Coverage"),
        ("Normal", f"Own channel videos: {counts['channel_videos']['total']}"),
        ("Normal", f"Own transcripts saved: {counts['channel_videos']['with_transcripts']}"),
        ("Normal", f"Own videos with CTR: {counts['channel_videos']['with_ctr']}"),
        ("Normal", f"Own videos with retention/AVD: {counts['channel_videos']['with_retention']}"),
        ("Normal", f"Competitor/reference videos: {counts['competitor_videos']['total']}"),
        ("Normal", f"Competitor/reference transcripts: {counts['competitor_videos']['with_transcripts']}"),
        ("Normal", f"Distilled competitor/reference videos: {counts['competitor_videos']['distilled']}"),
        ("Heading2", "Seed Production Video"),
        ("Normal", _seed_video_summary(data)),
        ("Heading2", "Observed Hook DNA"),
    ]
    if data["hook_rows"]:
        for row in data["hook_rows"]:
            lines.append(("Normal", f"- {row.get('hook_type')}: {row.get('count')} samples, avg VPH {row.get('avg_vph') or 'n/a'}"))
    else:
        lines.append(("Normal", "No distilled hook DNA is available yet."))

    lines.append(("Heading2", "Observed Tone DNA"))
    if data["tone_rows"]:
        for row in data["tone_rows"]:
            lines.append(("Normal", f"- {row.get('tone')}: {row.get('count')} samples, avg VPH {row.get('avg_vph') or 'n/a'}"))
    else:
        lines.append(("Normal", "No distilled tone DNA is available yet."))

    lines.append(("Heading2", "Top Own-Channel Performance Signals"))
    if data["channel_videos"]:
        for row in data["channel_videos"][:8]:
            lines.append(("Normal", _format_channel_video(row)))
    else:
        lines.append(("Normal", "No own-channel videos have been synced yet."))
    return lines


def _transcript_index_lines(data: dict) -> list[tuple[str, str]]:
    counts = data["source_counts"]
    backfill = data.get("transcript_backfill") or {}
    lines = [
        ("Heading1", "Transcript Evidence Index"),
        ("Normal", f"Generated at: {data['generated_at']}"),
        ("Heading2", "Transcript Coverage"),
        ("Normal", f"Own-channel transcripts: {counts['channel_videos']['with_transcripts']} of {counts['channel_videos']['total']} videos"),
        ("Normal", f"Competitor/reference transcripts: {counts['competitor_videos']['with_transcripts']} of {counts['competitor_videos']['total']} videos"),
        ("Normal", f"Refresh transcript fetch attempted: {backfill.get('attempted', 0)}"),
        ("Normal", f"Refresh transcript fetch saved: {backfill.get('saved', 0)}"),
        ("Heading2", "Own-Channel Transcript Excerpts"),
    ]
    if data["transcript_examples"]:
        for row in data["transcript_examples"]:
            lines.append(("Heading3", row.get("title") or row.get("video_id") or "Untitled video"))
            lines.append(("Normal", row.get("excerpt") or "No excerpt available."))
    else:
        lines.append(("Normal", "No own-channel transcript excerpts are available yet."))

    lines.append(("Heading2", "Distilled Competitor/Reference Evidence"))
    if data["competitor_examples"]:
        for row in data["competitor_examples"]:
            lines.append(("Heading3", row.get("title") or "Untitled reference"))
            lines.append(("Normal", f"Channel: {row.get('channel') or 'Unknown'} | VPH: {row.get('vph') or 'n/a'}"))
            if row.get("hook_type"):
                lines.append(("Normal", f"Hook: {row.get('hook_type')}"))
            if row.get("tone"):
                lines.append(("Normal", f"Tone: {row.get('tone')}"))
            if row.get("summary"):
                lines.append(("Normal", row["summary"]))
    else:
        lines.append(("Normal", "No distilled competitor/reference evidence is available yet."))
    return lines


def _script_guidance_lines(data: dict) -> list[tuple[str, str]]:
    lines = [
        ("Heading1", "Script Guidance Receipt"),
        ("Normal", f"Generated at: {data['generated_at']}"),
        ("Heading2", "Seed Script Source"),
        ("Normal", _seed_video_summary(data)),
    ]
    seed = data.get("production_video") or {}
    video = seed.get("video") or {}
    if video.get("script_excerpt"):
        lines.append(("Heading3", "Script Opening Excerpt"))
        lines.append(("Normal", _shorten(video["script_excerpt"], 1800)))
    if seed.get("scenes"):
        lines.append(("Heading3", "Scene/Act Beats"))
        for scene in seed["scenes"][:8]:
            lines.append(("Normal", _format_scene(scene)))

    lines.append(
        ("Heading2", "Guidance That Can Be Injected Into Scripts"),
    )
    if data["learnings"]:
        for row in data["learnings"]:
            metrics = []
            if row.get("avg_ctr") is not None:
                metrics.append(f"CTR {float(row['avg_ctr']):.1f}%")
            if row.get("avg_retention") is not None:
                metrics.append(f"retention {float(row['avg_retention']):.1f}%")
            if row.get("sample_size") is not None:
                metrics.append(f"{row['sample_size']} samples")
            if row.get("confidence") is not None:
                metrics.append(f"confidence {float(row['confidence']):.0f}")
            metric_text = f" ({', '.join(metrics)})" if metrics else ""
            lines.append(("Normal", f"- [{row.get('category')}] {row.get('pattern')}{metric_text}"))
    else:
        lines.append(("Normal", "No active performance learnings are available yet."))

    lines.extend([
        ("Heading2", "Current Modeling Limits"),
        ("Normal", _missing_inputs_sentence(data)),
        ("Heading2", "Recommended Next Inputs"),
        ("Normal", "- Sync YouTube analytics after each upload so CTR, AVD, and retention can update the learning table."),
        ("Normal", "- Keep transcript coverage high for own-channel videos so tone and hook modeling is based on actual narration."),
        ("Normal", "- Distill reference videos before launching from them so competitor DNA can be attached to the script prompt."),
    ])
    return lines


def _visual_generation_lines(data: dict) -> list[tuple[str, str]]:
    seed = data.get("production_video") or {}
    video = seed.get("video") or {}
    style = seed.get("active_visual_style") or {}
    assets = seed.get("assets") or []
    scenes = seed.get("scenes") or []
    characters = seed.get("style_characters") or []

    lines = [
        ("Heading1", "Visual Generation Profile"),
        ("Normal", f"Generated at: {data['generated_at']}"),
        ("Heading2", "Seed Video"),
        ("Normal", _seed_video_summary(data)),
    ]
    if not video:
        lines.append(("Normal", "No production video is available yet. Generate or script one video, then refresh this profile."))
        return lines

    lines.extend([
        ("Heading2", "Video-Level Visual Settings"),
        ("Normal", f"Visual style: {video.get('visual_style') or 'Not set'}"),
        ("Normal", f"Accent color: {video.get('accent_color') or 'Not set'}"),
        ("Normal", f"Image model: {video.get('image_model_override') or 'Project/default model'}"),
        ("Normal", f"Video model: {video.get('video_model') or 'Project/default model'}"),
        ("Normal", f"Image style override: {video.get('image_style_override') or 'Not set'}"),
        ("Normal", f"Thumbnail text: {video.get('thumbnail_text') or 'Not set'}"),
        ("Normal", f"Thumbnail approach: {video.get('thumbnail_approach') or 'Not set'}"),
        ("Normal", f"Thumbnail style override: {video.get('thumbnail_style_override') or 'Not set'}"),
    ])
    if video.get("thumbnail_prompt"):
        lines.append(("Normal", f"Thumbnail prompt: {_shorten(video['thumbnail_prompt'], 900)}"))
    if video.get("story_bible"):
        lines.append(("Heading2", "Story Bible / Continuity Notes"))
        lines.append(("Normal", _shorten(video["story_bible"], 1800)))

    research_payload = video.get("research_payload") or {}
    visual_seed_lines = _research_visual_seed_lines(research_payload)
    if visual_seed_lines:
        lines.append(("Heading2", "Research Brief Visual Seeds"))
        for line in visual_seed_lines:
            lines.append(("Normal", line))

    lines.append(("Heading2", "Active Visual Style"))
    if style:
        lines.append(("Normal", f"Style name: {style.get('name') or 'Unnamed'}"))
        if style.get("reference_image_url"):
            lines.append(("Normal", f"Reference image: {style['reference_image_url']}"))
        lines.append(("Normal", f"Proof status: {style.get('proof_status') or 'not_generated'}"))
        if style.get("proof_drive_url") or style.get("proof_image_url"):
            lines.append(("Normal", f"Approved/proof frame: {style.get('proof_drive_url') or style.get('proof_image_url')}"))
        if style.get("proof_model"):
            lines.append(("Normal", f"Proof model: {style['proof_model']}"))
        if style.get("proof_approved_at"):
            lines.append(("Normal", f"Proof approved at: {style['proof_approved_at']}"))
        if style.get("proof_prompt"):
            lines.append(("Normal", f"Proof prompt: {_shorten(style['proof_prompt'], 1600)}"))
        for line in _style_profile_lines(style.get("style_profile")):
            lines.append(("Normal", line))
    else:
        lines.append(("Normal", "No active visual style record was found for this project."))

    if characters:
        lines.append(("Heading2", "Character / Reference Assets"))
        for char in characters:
            lines.append(("Normal", f"- {char.get('name')}: {char.get('image_url')}"))

    lines.append(("Heading2", "Image Prompt DNA"))
    image_assets = [a for a in assets if a.get("image_prompt")]
    if image_assets:
        for asset in image_assets[:10]:
            lines.append(("Heading3", _asset_title(asset)))
            lines.append(("Normal", _shorten(asset.get("image_prompt"), 1300)))
            if asset.get("original_image_prompt") and asset.get("original_image_prompt") != asset.get("image_prompt"):
                lines.append(("Normal", "Original prompt: " + _shorten(asset.get("original_image_prompt"), 700)))
            meta = _asset_meta(asset)
            if meta:
                lines.append(("Normal", meta))
    else:
        lines.append(("Normal", "No image prompts have been generated for the seed video yet. Use the research visual seeds above as the first image-generation source."))

    lines.append(("Heading2", "Video Motion Prompt DNA"))
    motion_assets = [a for a in assets if a.get("video_clip_prompt") or a.get("video_prompt")]
    if motion_assets:
        for asset in motion_assets[:10]:
            lines.append(("Heading3", _asset_title(asset)))
            prompt = asset.get("video_clip_prompt") or asset.get("video_prompt")
            lines.append(("Normal", _shorten(prompt, 1200)))
            meta = _asset_motion_meta(asset)
            if meta:
                lines.append(("Normal", meta))
    else:
        lines.append(("Normal", "No video motion prompts have been generated for the seed video yet. Use the scene/act beats and research visual seeds above as the first motion-planning source."))

    lines.append(("Heading2", "Storyboard / Scene Visual Notes"))
    storyboard_scenes = [s for s in scenes if s.get("storyboard_prompts")]
    if storyboard_scenes:
        for scene in storyboard_scenes[:6]:
            lines.append(("Heading3", f"Scene {scene.get('scene') or '?'} storyboard"))
            lines.append(("Normal", _shorten(scene.get("storyboard_prompts"), 1400)))
    else:
        lines.append(("Normal", "No storyboard prompt grids have been generated for the seed video yet."))

    lines.append(("Heading2", "Use In Generation"))
    lines.append(("Normal", "Use this document as the visual continuity source for image prompts, storyboard expansion, image-to-video motion, thumbnails, and render checks."))
    return lines


def _missing_inputs_sentence(data: dict) -> str:
    counts = data["source_counts"]
    missing = []
    if counts["channel_videos"]["with_transcripts"] == 0:
        missing.append("own-channel transcripts")
    if counts["channel_videos"]["with_ctr"] == 0:
        missing.append("own-channel CTR")
    if counts["channel_videos"]["with_retention"] == 0:
        missing.append("own-channel retention/AVD")
    if counts["competitor_videos"]["distilled"] == 0:
        missing.append("distilled competitor/reference DNA")
    if not missing:
        return "Core channel modeling inputs are present."
    return "Missing or thin inputs: " + ", ".join(missing) + "."


async def _collect_production_video_profile(tenant_id: str) -> dict:
    """Collect one real video as the seed for script and visual modeling."""
    video = await fetch_one(
        """SELECT id, project_id, video_title, status, headline, thesis, executive_hook,
                  framework_angle, writer_guidance, video_length_minutes,
                  visual_style, accent_color, image_model_override, image_style_override,
                  video_model, thumbnail_prompt, thumbnail_style_override,
                  thumbnail_text, thumbnail_approach, thumbnail_url, story_bible,
                  script_validation, drive_folder_link, final_video_url, research_payload,
                  LEFT(script, 4200) AS script_excerpt,
                  char_length(COALESCE(script, '')) AS script_chars,
                  updated_at::text
           FROM videos
           WHERE tenant_id = $1
           ORDER BY
             CASE WHEN script IS NOT NULL AND script <> '' THEN 0 ELSE 1 END,
             updated_at DESC NULLS LAST,
             created_at DESC NULLS LAST
           LIMIT 1""",
        tenant_id,
    )
    if not video:
        return {}

    video_id = str(video["id"])
    scenes = await fetch_all(
        """SELECT scene, title, LEFT(scene_text, 1200) AS scene_text, tone,
                  sources, framework, psych_angle, storyboard_on_off,
                  storyboard_prompts, storyboard_beat_count, storyboard_status
           FROM scripts
           WHERE tenant_id = $1 AND video_id = $2
           ORDER BY scene NULLS LAST
           LIMIT 12""",
        tenant_id,
        video_id,
    )
    assets = await fetch_all(
        """SELECT scene, image_index, sentence_index, LEFT(sentence_text, 500) AS sentence_text,
                  duration_seconds, image_prompt, original_image_prompt,
                  shot_type, hero_shot, status, image_url, drive_image_url,
                  video_prompt, video_clip_prompt, video_clip_url, video_status,
                  animation_status, camera_movement, aspect_ratio,
                  generation_method, assigned_video_duration
           FROM assets
           WHERE tenant_id = $1 AND video_id = $2
           ORDER BY scene NULLS LAST, image_index NULLS LAST, sentence_index NULLS LAST
           LIMIT 24""",
        tenant_id,
        video_id,
    )

    active_style = None
    style_characters = []
    if video.get("project_id"):
        active_style = await fetch_one(
            """SELECT id, name, style_profile, reference_image_url,
                      proof_image_url, proof_drive_url, proof_drive_file_id,
                      proof_prompt, proof_model, proof_status,
                      proof_generated_at::text, proof_approved_at::text,
                      is_active, is_default
               FROM visual_styles
               WHERE project_id = $1 AND is_active = true
               ORDER BY updated_at DESC NULLS LAST
               LIMIT 1""",
            str(video["project_id"]),
        )
        if active_style:
            style_characters = await fetch_all(
                """SELECT name, image_url, sort_order
                   FROM style_characters
                   WHERE visual_style_id = $1
                   ORDER BY sort_order, created_at
                   LIMIT 12""",
                str(active_style["id"]),
            )

    return {
        "video": _normalize_video_row(video),
        "scenes": [dict(row) for row in scenes or []],
        "assets": [dict(row) for row in assets or []],
        "active_visual_style": _normalize_style_row(active_style) if active_style else None,
        "style_characters": [dict(row) for row in style_characters or []],
    }


def _docx_bytes(title: str, lines: list[tuple[str, str]]) -> bytes:
    body = [_p(style, text) for style, text in lines]
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {''.join(body)}
    <w:sectPr>
      <w:pgSz w:w="12240" w:h="15840"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>
    </w:sectPr>
  </w:body>
</w:document>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
</w:styles>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/styles.xml", styles)
    return buffer.getvalue()


def _p(style: str, text: Any) -> str:
    cleaned = str(text or "").replace("\x00", "").strip()
    style_xml = f'<w:pPr><w:pStyle w:val="{escape(style)}"/></w:pPr>' if style else ""
    return f'<w:p>{style_xml}<w:r><w:t xml:space="preserve">{escape(cleaned)}</w:t></w:r></w:p>'


def _format_channel_video(row: dict) -> str:
    bits = [f"- {row.get('title') or row.get('video_id') or 'Untitled'}"]
    if row.get("ctr_percent") is not None:
        bits.append(f"CTR {float(row['ctr_percent']):.1f}%")
    if row.get("avg_retention") is not None:
        bits.append(f"retention {float(row['avg_retention']):.1f}%")
    if row.get("avg_view_duration_seconds") is not None:
        bits.append(f"AVD {int(row['avg_view_duration_seconds'])}s")
    if row.get("view_count") is not None:
        bits.append(f"{int(row['view_count']):,} views")
    return " | ".join(bits)


def _seed_video_summary(data: dict) -> str:
    seed = data.get("production_video") or {}
    video = seed.get("video") or {}
    if not video:
        return "No seed production video found yet."
    bits = [
        video.get("video_title") or video.get("headline") or "Untitled video",
        f"status {video.get('status') or 'unknown'}",
    ]
    if video.get("script_chars"):
        bits.append(f"{video['script_chars']} script chars")
    if seed.get("scenes"):
        bits.append(f"{len(seed['scenes'])} script scenes")
    if seed.get("assets"):
        bits.append(f"{len(seed['assets'])} visual assets/prompts sampled")
    if video.get("drive_folder_link"):
        bits.append(f"Drive folder {video['drive_folder_link']}")
    return " | ".join(bits)


def _format_scene(scene: dict) -> str:
    title = scene.get("title") or f"Scene {scene.get('scene') or '?'}"
    text = _shorten(scene.get("scene_text"), 700)
    parts = [f"- {title}: {text}"]
    if scene.get("tone"):
        parts.append(f"tone {scene['tone']}")
    if scene.get("framework"):
        parts.append(f"framework {scene['framework']}")
    if scene.get("storyboard_status"):
        parts.append(f"storyboard {scene['storyboard_status']}")
    return " | ".join(parts)


def _asset_title(asset: dict) -> str:
    scene = asset.get("scene") or "?"
    index = asset.get("image_index") or asset.get("sentence_index") or "?"
    return f"Scene {scene}, visual {index}"


def _asset_meta(asset: dict) -> str:
    bits = []
    for key, label in [
        ("shot_type", "shot"),
        ("generation_method", "method"),
        ("aspect_ratio", "aspect"),
        ("status", "status"),
        ("duration_seconds", "duration"),
    ]:
        if asset.get(key) is not None:
            bits.append(f"{label}: {asset[key]}")
    if asset.get("hero_shot"):
        bits.append("hero shot")
    if asset.get("image_url") or asset.get("drive_image_url"):
        bits.append("image saved")
    return " | ".join(bits)


def _asset_motion_meta(asset: dict) -> str:
    bits = []
    for key, label in [
        ("camera_movement", "camera"),
        ("video_status", "video status"),
        ("animation_status", "animation"),
        ("assigned_video_duration", "assigned duration"),
    ]:
        if asset.get(key) is not None:
            bits.append(f"{label}: {asset[key]}")
    if asset.get("video_clip_url"):
        bits.append("clip saved")
    return " | ".join(bits)


def _style_profile_lines(style_profile: Any) -> list[str]:
    profile = _parse_json(style_profile, {})
    if not profile:
        return ["Style profile: not set"]
    lines = []
    for key, value in list(profile.items())[:12]:
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=True)[:900]
        else:
            rendered = str(value)
        lines.append(f"{key}: {_shorten(rendered, 900)}")
    return lines


def _research_visual_seed_lines(research_payload: Any) -> list[str]:
    payload = _parse_json(research_payload, {})
    if not payload:
        return []
    candidates = [
        ("visual_seeds", "Visual seeds"),
        ("character_dossier", "Character dossier"),
        ("narrative_arc", "Narrative arc"),
        ("historical_parallels", "Historical parallels"),
        ("framework_analysis", "Framework analysis"),
        ("executive_hook", "Executive hook"),
        ("thesis", "Thesis"),
    ]
    lines = []
    for key, label in candidates:
        value = payload.get(key)
        if not value:
            continue
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=True)
        else:
            text = str(value)
        lines.append(f"{label}: {_shorten(text, 1300)}")
    return lines


def _shorten(value: Any, limit: int = 800) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _parse_json(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def _normalize_video_row(row: Any) -> dict:
    item = dict(row)
    item["id"] = str(item.get("id")) if item.get("id") else None
    item["project_id"] = str(item.get("project_id")) if item.get("project_id") else None
    item["research_payload"] = _parse_json(item.get("research_payload"), {})
    return item


def _normalize_style_row(row: Any) -> dict:
    item = dict(row)
    item["id"] = str(item.get("id")) if item.get("id") else None
    item["style_profile"] = _parse_json(item.get("style_profile"), {})
    return item


def _normalize_competitor_example(row: Any) -> dict:
    item = dict(row)
    metadata = item.get("structured_metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    hook = metadata.get("hook_dna") or metadata.get("hook") or {}
    content = metadata.get("content_dna") or {}
    item["hook_type"] = hook.get("type")
    item["tone"] = content.get("tone")
    item.pop("structured_metadata", None)
    return item


def _normalize_doc_row(row: Any) -> dict:
    item = dict(row)
    for key in ("source_counts", "metadata"):
        value = item.get(key) or {}
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = {}
        item[key] = value
    return item


def _as_count_dict(row: Optional[Any], keys: list[str]) -> dict:
    return {key: int((row or {}).get(key) or 0) for key in keys}
