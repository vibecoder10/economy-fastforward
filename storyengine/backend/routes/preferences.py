"""User preferences endpoints — tab order, UI settings, notifications."""

from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_tenant_id
from database import fetch_all, fetch_one, execute

router = APIRouter(tags=["preferences"])


class PreferenceUpdate(BaseModel):
    value: Any


@router.get("/api/user/preferences")
async def get_preferences(tenant_id: str = Depends(get_tenant_id)):
    """Get all user preferences."""
    rows = await fetch_all(
        """SELECT preference_key, preference_value
           FROM user_preferences
           WHERE account_id = (
             SELECT a.id FROM accounts a
             JOIN projects p ON p.account_id = a.id
             WHERE p.tenant_id = $1
             LIMIT 1
           )""",
        tenant_id,
    )
    return {r["preference_key"]: r["preference_value"] for r in rows}


@router.get("/api/user/preferences/{key}")
async def get_preference(key: str, tenant_id: str = Depends(get_tenant_id)):
    """Get a single preference by key."""
    row = await fetch_one(
        """SELECT preference_value
           FROM user_preferences
           WHERE preference_key = $1
             AND account_id = (
               SELECT a.id FROM accounts a
               JOIN projects p ON p.account_id = a.id
               WHERE p.tenant_id = $2
               LIMIT 1
             )""",
        key, tenant_id,
    )
    if not row:
        return {"key": key, "value": None}
    return {"key": key, "value": row["preference_value"]}


@router.put("/api/user/preferences/{key}")
async def set_preference(
    key: str, body: PreferenceUpdate, tenant_id: str = Depends(get_tenant_id)
):
    """Set a user preference (upsert)."""
    import json

    value_json = json.dumps(body.value)

    await execute(
        """INSERT INTO user_preferences (account_id, preference_key, preference_value)
           VALUES (
             (SELECT a.id FROM accounts a
              JOIN projects p ON p.account_id = a.id
              WHERE p.tenant_id = $1
              LIMIT 1),
             $2, $3::jsonb
           )
           ON CONFLICT (account_id, preference_key)
           DO UPDATE SET preference_value = $3::jsonb, updated_at = now()""",
        tenant_id, key, value_json,
    )
    return {"status": "ok", "key": key}


@router.delete("/api/user/preferences/{key}")
async def delete_preference(key: str, tenant_id: str = Depends(get_tenant_id)):
    """Delete a user preference."""
    await execute(
        """DELETE FROM user_preferences
           WHERE preference_key = $1
             AND account_id = (
               SELECT a.id FROM accounts a
               JOIN projects p ON p.account_id = a.id
               WHERE p.tenant_id = $2
               LIMIT 1
             )""",
        key, tenant_id,
    )
    return {"status": "deleted", "key": key}


# --- Notification Preferences ---

class NotificationPreferences(BaseModel):
    email_weekly_digest: bool = True
    email_video_complete: bool = True
    email_error_alerts: bool = True
    email_ctr_alerts: bool = True


class NotificationPreferencesUpdate(BaseModel):
    email_weekly_digest: Optional[bool] = None
    email_video_complete: Optional[bool] = None
    email_error_alerts: Optional[bool] = None
    email_ctr_alerts: Optional[bool] = None


@router.get("/api/preferences/notifications")
async def get_notification_prefs(tenant_id: str = Depends(get_tenant_id)):
    """Get notification preferences for the current tenant."""
    row = await fetch_one(
        """SELECT email_weekly_digest, email_video_complete, email_error_alerts, email_ctr_alerts
           FROM notification_preferences WHERE tenant_id = $1""",
        tenant_id,
    )
    if not row:
        return NotificationPreferences()
    return NotificationPreferences(
        email_weekly_digest=row["email_weekly_digest"],
        email_video_complete=row["email_video_complete"],
        email_error_alerts=row["email_error_alerts"],
        email_ctr_alerts=row["email_ctr_alerts"],
    )


@router.patch("/api/preferences/notifications")
async def update_notification_prefs(
    update: NotificationPreferencesUpdate,
    tenant_id: str = Depends(get_tenant_id),
):
    """Update notification preferences (upsert)."""
    existing = await fetch_one(
        "SELECT id FROM notification_preferences WHERE tenant_id = $1", tenant_id
    )

    if not existing:
        await execute(
            """INSERT INTO notification_preferences
               (tenant_id, email_weekly_digest, email_video_complete, email_error_alerts, email_ctr_alerts)
               VALUES ($1, $2, $3, $4, $5)""",
            tenant_id,
            update.email_weekly_digest if update.email_weekly_digest is not None else True,
            update.email_video_complete if update.email_video_complete is not None else True,
            update.email_error_alerts if update.email_error_alerts is not None else True,
            update.email_ctr_alerts if update.email_ctr_alerts is not None else True,
        )
    else:
        sets = []
        params = []
        idx = 1

        for field in ["email_weekly_digest", "email_video_complete", "email_error_alerts", "email_ctr_alerts"]:
            val = getattr(update, field)
            if val is not None:
                idx += 1
                sets.append(f"{field} = ${idx}")
                params.append(val)

        if sets:
            sets.append("updated_at = now()")
            # SECURITY: column names from hardcoded allowlist loop, values use $N params
            query = f"UPDATE notification_preferences SET {', '.join(sets)} WHERE tenant_id = $1"
            await execute(query, tenant_id, *params)

    return await get_notification_prefs(tenant_id)
