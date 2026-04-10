"""Profile routes — read and update current user account."""

from fastapi import APIRouter, Depends, HTTPException

from auth import verify_token, AuthUser
from database import fetch_one, execute
from models import ProfileRead, ProfileUpdate

router = APIRouter(prefix="/api/profile", tags=["profile"])

DEV_ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"


def _get_account_id(user: AuthUser) -> str:
    """Resolve the account ID from the auth user."""
    if user.id == "dev-user":
        return DEV_ACCOUNT_ID
    return user.id


@router.get("", response_model=ProfileRead)
async def get_profile(user: AuthUser = Depends(verify_token)):
    """Get the current user's profile from accounts table."""
    account_id = _get_account_id(user)
    row = await fetch_one(
        "SELECT id, email, display_name, plan, created_at FROM accounts WHERE id = $1",
        account_id,
    )
    if not row and user.email:
        # Fallback: user may have re-authenticated with a new sub ID but same email
        row = await fetch_one(
            "SELECT id, email, display_name, plan, created_at FROM accounts WHERE email = $1",
            user.email,
        )
    if not row:
        # Auto-create account (handle both id and email conflicts)
        try:
            await execute(
                "INSERT INTO accounts (id, email, display_name, plan) VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO NOTHING",
                account_id, user.email or "dev@local", user.email or "Dev User", "free",
            )
        except Exception:
            pass  # email uniqueness conflict — account exists under different id
        row = await fetch_one(
            "SELECT id, email, display_name, plan, created_at FROM accounts WHERE id = $1",
            account_id,
        )
        if not row and user.email:
            # Account exists under different id — look up by email
            row = await fetch_one(
                "SELECT id, email, display_name, plan, created_at FROM accounts WHERE email = $1",
                user.email,
            )
    if not row:
        raise HTTPException(status_code=404, detail="Account not found")
    return ProfileRead(
        id=str(row["id"]),
        email=row.get("email"),
        display_name=row.get("display_name"),
        plan=row.get("plan") or "free",
        created_at=str(row["created_at"]) if row.get("created_at") else None,
    )


@router.put("", response_model=ProfileRead)
async def update_profile(
    update: ProfileUpdate,
    user: AuthUser = Depends(verify_token),
):
    """Update display name and/or email on the current user's account."""
    account_id = _get_account_id(user)

    # Check account exists
    row = await fetch_one("SELECT id FROM accounts WHERE id = $1", account_id)
    if not row:
        raise HTTPException(status_code=404, detail="Account not found")

    sets = []
    params = []
    idx = 1  # $1 is account_id

    if update.display_name is not None:
        idx += 1
        sets.append(f"display_name = ${idx}")
        params.append(update.display_name)

    if update.email is not None:
        idx += 1
        sets.append(f"email = ${idx}")
        params.append(update.email)

    if not sets:
        raise HTTPException(status_code=400, detail="No fields to update")

    sets.append("updated_at = now()")
    # SECURITY: column names are hardcoded (display_name, email), values use $N params
    query = f"UPDATE accounts SET {', '.join(sets)} WHERE id = $1"
    await execute(query, account_id, *params)

    # Return updated profile
    updated = await fetch_one(
        "SELECT id, email, display_name, plan, created_at FROM accounts WHERE id = $1",
        account_id,
    )
    return ProfileRead(
        id=str(updated["id"]),
        email=updated.get("email"),
        display_name=updated.get("display_name"),
        plan=updated.get("plan") or "free",
        created_at=str(updated["created_at"]) if updated.get("created_at") else None,
    )
