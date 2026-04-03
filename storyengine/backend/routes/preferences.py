"""User preferences endpoints — tab order, UI settings, etc."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_tenant_id
from database import fetch_all, fetch_one, execute

router = APIRouter(prefix="/api/user/preferences", tags=["preferences"])


class PreferenceUpdate(BaseModel):
    value: dict


@router.get("")
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


@router.get("/{key}")
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


@router.put("/{key}")
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


@router.delete("/{key}")
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
