"""Per-channel (per-tenant) configuration.

Loads a ChannelConfig by slug from the multi-tenant Supabase state store
(YOUTUBER_DB_URL). Media stays in each creator's Google Drive; Supabase holds
only lightweight metadata/state.

The default channel ('economy_fastforward') falls back to environment variables
if the state DB is unset/unreachable, so the legacy single-channel pipeline keeps
running exactly as before even without Supabase.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_CHANNEL = "economy_fastforward"


@dataclass
class ChannelConfig:
    channel_id: str                                  # stable slug, used in code/CLI
    title: Optional[str] = None
    niche: Optional[str] = None
    state_store: str = "airtable"                    # 'airtable' (legacy) | 'supabase'
    # production settings
    voice_id: Optional[str] = None
    drive_folder_id: Optional[str] = None            # root folder (creator's Drive)
    script_profile: Optional[str] = None
    visual_profile: Optional[str] = None
    accent_color: Optional[str] = None
    airtable_base_id: Optional[str] = None           # only when state_store == 'airtable'
    # per-creator Google Drive OAuth (None => fall back to global env creds)
    drive_client_id: Optional[str] = None
    drive_client_secret: Optional[str] = None
    drive_refresh_token: Optional[str] = None
    # learned profiles (from onboarding)
    voice_profile: dict = field(default_factory=dict)
    thumbnail_style: dict = field(default_factory=dict)
    # tenant
    creator_id: Optional[str] = None
    creator_email: Optional[str] = None


def _from_env(channel_id: str) -> ChannelConfig:
    """Reconstruct the legacy single-channel config from env (no DB needed)."""
    return ChannelConfig(
        channel_id=channel_id,
        title="Economy FastForward",
        state_store="airtable",
        voice_id=os.getenv("ELEVENLABS_VOICE_ID"),
        drive_folder_id=os.getenv("GOOGLE_DRIVE_FOLDER_ID"),
        script_profile=os.getenv("SCRIPT_PROFILE") or "power_doctrine_v2",
        visual_profile=os.getenv("VISUAL_PROFILE") or "cinematic_illustration",
        airtable_base_id=os.getenv("AIRTABLE_BASE_ID"),
    )


def load_channel(channel_id: Optional[str] = None) -> ChannelConfig:
    """Load a channel's config. Resolves channel_id from arg -> CHANNEL_ID env -> default."""
    channel_id = channel_id or os.getenv("CHANNEL_ID") or DEFAULT_CHANNEL
    db_url = os.getenv("YOUTUBER_DB_URL")
    if not db_url:
        if channel_id == DEFAULT_CHANNEL:
            return _from_env(channel_id)
        raise RuntimeError(
            f"YOUTUBER_DB_URL not set; cannot load non-default channel '{channel_id}'"
        )
    try:
        return _load_from_db(channel_id, db_url)
    except Exception as e:
        if channel_id == DEFAULT_CHANNEL:
            print(f"  ⚠ channel config DB load failed ({e}); using env for default channel")
            return _from_env(channel_id)
        raise


def _load_from_db(channel_id: str, db_url: str) -> ChannelConfig:
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(db_url, connect_timeout=10)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            select ch.slug, ch.title, ch.niche, ch.state_store, ch.creator_id,
                   cf.elevenlabs_voice_id, cf.drive_folder_id, cf.script_profile,
                   cf.visual_profile, cf.accent_color, cf.voice_profile,
                   cf.thumbnail_style, cf.airtable_base_id,
                   cr.email as creator_email,
                   dc.refresh_token as drive_refresh_token,
                   dc.root_folder_id as drive_root_folder_id
            from channels ch
            join channel_config cf on cf.channel_id = ch.id
            join creators cr on cr.id = ch.creator_id
            left join lateral (
                select refresh_token, root_folder_id
                from drive_connections d
                where d.creator_id = ch.creator_id
                order by connected_at desc limit 1
            ) dc on true
            where ch.slug = %s
            """,
            (channel_id,),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"channel '{channel_id}' not found in state store")
        return ChannelConfig(
            channel_id=row["slug"],
            title=row["title"],
            niche=row["niche"],
            state_store=row["state_store"],
            creator_id=str(row["creator_id"]) if row["creator_id"] else None,
            creator_email=row["creator_email"],
            voice_id=row["elevenlabs_voice_id"],
            # prefer the creator's connected Drive root if present
            drive_folder_id=row["drive_root_folder_id"] or row["drive_folder_id"],
            script_profile=row["script_profile"],
            visual_profile=row["visual_profile"],
            accent_color=row["accent_color"],
            airtable_base_id=row["airtable_base_id"],
            drive_refresh_token=row["drive_refresh_token"],
            voice_profile=row["voice_profile"] or {},
            thumbnail_style=row["thumbnail_style"] or {},
        )
    finally:
        conn.close()
