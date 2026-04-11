"""Channel profile routes — CRUD for channel settings.

Handles channel name, niche, target audience, and frameworks.
"""

import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_tenant_id
from database import fetch_one, execute

router = APIRouter(prefix="/api/channel-profile", tags=["channel-profile"])


# --- Models ---

class ChannelProfile(BaseModel):
    """Channel profile data."""
    channel_name: str = ""
    niche: str = ""
    target_audience: str = ""
    frameworks: list[str] = []
    accent_color: str = ""
    logo_url: str = ""
    google_drive_folder_id: str = ""
    google_drive_folder_name: str = ""
    user_type: str = ""
    style_description: str = ""
    youtube_channel_id: str = ""
    youtube_channel_name: str = ""
    onboarding_completed_at: Optional[str] = None


class ChannelProfileUpdate(BaseModel):
    """Partial update for channel profile."""
    channel_name: Optional[str] = None
    niche: Optional[str] = None
    target_audience: Optional[str] = None
    frameworks: Optional[list[str]] = None
    accent_color: Optional[str] = None
    logo_url: Optional[str] = None
    google_drive_folder_id: Optional[str] = None
    google_drive_folder_name: Optional[str] = None
    user_type: Optional[str] = None
    style_description: Optional[str] = None
    youtube_channel_id: Optional[str] = None
    youtube_channel_name: Optional[str] = None


class IntegrationStatus(BaseModel):
    """Status of an integration based on API key presence."""
    name: str
    connected: bool


# --- Ensure table exists ---

async def _ensure_table():
    """Create channel_profiles table if it doesn't exist."""
    try:
        await execute("""
            CREATE TABLE IF NOT EXISTS channel_profiles (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE UNIQUE NOT NULL,
                channel_name TEXT DEFAULT '',
                niche TEXT DEFAULT '',
                target_audience TEXT DEFAULT '',
                frameworks JSONB DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )
        """)
    except Exception as e:
        print(f"Warning: Could not ensure channel_profiles table: {e}")


# --- Endpoints ---

@router.get("", response_model=ChannelProfile)
async def get_channel_profile(tenant_id: str = Depends(get_tenant_id)):
    """Get channel profile for the current tenant.

    Returns empty defaults if no profile exists yet.
    """
    await _ensure_table()

    row = await fetch_one(
        """SELECT channel_name, niche, target_audience, frameworks,
                  accent_color, logo_url, google_drive_folder_id, google_drive_folder_name,
                  user_type, style_description, youtube_channel_id, youtube_channel_name,
                  onboarding_completed_at::text
           FROM channel_profiles WHERE tenant_id = $1""",
        tenant_id,
    )

    if not row:
        return ChannelProfile()

    frameworks = row.get("frameworks") or []
    if isinstance(frameworks, str):
        try:
            frameworks = json.loads(frameworks)
        except (json.JSONDecodeError, TypeError):
            frameworks = []

    return ChannelProfile(
        channel_name=row.get("channel_name") or "",
        niche=row.get("niche") or "",
        target_audience=row.get("target_audience") or "",
        frameworks=frameworks,
        accent_color=row.get("accent_color") or "",
        logo_url=row.get("logo_url") or "",
        google_drive_folder_id=row.get("google_drive_folder_id") or "",
        google_drive_folder_name=row.get("google_drive_folder_name") or "",
        user_type=row.get("user_type") or "",
        style_description=row.get("style_description") or "",
        youtube_channel_id=row.get("youtube_channel_id") or "",
        youtube_channel_name=row.get("youtube_channel_name") or "",
        onboarding_completed_at=row.get("onboarding_completed_at"),
    )


@router.put("", response_model=ChannelProfile)
async def update_channel_profile(
    update: ChannelProfileUpdate,
    tenant_id: str = Depends(get_tenant_id),
):
    """Update channel profile (upsert).

    Creates the profile if it doesn't exist yet.
    Only updates fields that are provided (non-None).
    """
    await _ensure_table()

    # Check if profile exists
    existing = await fetch_one(
        "SELECT id FROM channel_profiles WHERE tenant_id = $1",
        tenant_id,
    )

    if not existing:
        # Create new profile with provided values
        frameworks_json = json.dumps(update.frameworks or [])
        await execute(
            """INSERT INTO channel_profiles
               (tenant_id, channel_name, niche, target_audience, frameworks,
                accent_color, logo_url, google_drive_folder_id, google_drive_folder_name,
                user_type, style_description, youtube_channel_id, youtube_channel_name)
               VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10, $11, $12, $13)""",
            tenant_id,
            update.channel_name or "",
            update.niche or "",
            update.target_audience or "",
            frameworks_json,
            update.accent_color or "",
            update.logo_url or "",
            update.google_drive_folder_id or "",
            update.google_drive_folder_name or "",
            update.user_type or "",
            update.style_description or "",
            update.youtube_channel_id or "",
            update.youtube_channel_name or "",
        )
    else:
        # Build dynamic update
        sets = []
        params = []
        param_idx = 1

        if update.channel_name is not None:
            param_idx += 1
            sets.append(f"channel_name = ${param_idx}")
            params.append(update.channel_name)

        if update.niche is not None:
            param_idx += 1
            sets.append(f"niche = ${param_idx}")
            params.append(update.niche)

        if update.target_audience is not None:
            param_idx += 1
            sets.append(f"target_audience = ${param_idx}")
            params.append(update.target_audience)

        if update.frameworks is not None:
            param_idx += 1
            sets.append(f"frameworks = ${param_idx}::jsonb")
            params.append(json.dumps(update.frameworks))

        if update.accent_color is not None:
            param_idx += 1
            sets.append(f"accent_color = ${param_idx}")
            params.append(update.accent_color)

        if update.logo_url is not None:
            param_idx += 1
            sets.append(f"logo_url = ${param_idx}")
            params.append(update.logo_url)

        if update.google_drive_folder_id is not None:
            param_idx += 1
            sets.append(f"google_drive_folder_id = ${param_idx}")
            params.append(update.google_drive_folder_id)

        if update.google_drive_folder_name is not None:
            param_idx += 1
            sets.append(f"google_drive_folder_name = ${param_idx}")
            params.append(update.google_drive_folder_name)

        if update.user_type is not None:
            param_idx += 1
            sets.append(f"user_type = ${param_idx}")
            params.append(update.user_type)

        if update.style_description is not None:
            param_idx += 1
            sets.append(f"style_description = ${param_idx}")
            params.append(update.style_description)

        if update.youtube_channel_id is not None:
            param_idx += 1
            sets.append(f"youtube_channel_id = ${param_idx}")
            params.append(update.youtube_channel_id)

        if update.youtube_channel_name is not None:
            param_idx += 1
            sets.append(f"youtube_channel_name = ${param_idx}")
            params.append(update.youtube_channel_name)

        if sets:
            sets.append("updated_at = now()")
            # SECURITY: column names are hardcoded per-field conditionals, values use $N params
            query = f"UPDATE channel_profiles SET {', '.join(sets)} WHERE tenant_id = $1"
            await execute(query, tenant_id, *params)

    # Return updated profile
    return await get_channel_profile(tenant_id)


@router.patch("", response_model=ChannelProfile)
async def patch_channel_profile(
    update: ChannelProfileUpdate,
    tenant_id: str = Depends(get_tenant_id),
):
    """Partial update channel profile (same logic as PUT)."""
    return await update_channel_profile(update, tenant_id)


@router.get("/integrations", response_model=list[IntegrationStatus])
async def get_integration_statuses(tenant_id: str = Depends(get_tenant_id)):
    """Get connection status for integrations based on API key existence.

    Checks if the relevant API keys exist and are non-empty.
    """
    from vault import get_secret_status

    # Map integration names to their required API keys
    integration_keys = {
        "YouTube": ["google_client_id", "google_refresh_token"],
        "Google Drive": ["google_client_id", "google_refresh_token"],
    }

    statuses = []
    for name, keys in integration_keys.items():
        connected = True
        for key_name in keys:
            status = await get_secret_status(key_name, tenant_id)
            if not status.get("configured"):
                connected = False
                break
        statuses.append(IntegrationStatus(name=name, connected=connected))

    return statuses
