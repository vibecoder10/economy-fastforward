"""Single-use customer YouTube consent, with no StoryEngine login required."""
import hashlib
import hmac
import html
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel, Field

from auth import get_tenant_id, verify_token, AuthUser
from database import execute, fetch_one, get_pool
from youtube_oauth_config import get_youtube_oauth_credentials

router = APIRouter(prefix="/youtube", tags=["auth"])
COOKIE = "youtube_invite_browser"
COOKIE_PATH = "/api/auth/youtube"
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def redirect_uri() -> str:
    return os.getenv("YOUTUBE_REDIRECT_URI", os.getenv("FRONTEND_URL", "https://storyengine.dev").rstrip("/") + "/settings/youtube-callback")


class InviteRequest(BaseModel):
    expected_channel_id: str = Field(pattern=r"^UC[A-Za-z0-9_-]{22}$")


class InviteCallback(BaseModel):
    state: str = Field(max_length=256)
    code: str = Field(default="", max_length=4096)
    error: str | None = Field(default=None, max_length=256)


@router.post("/invites")
async def create_invite(body: InviteRequest, tenant: uuid.UUID = Depends(get_tenant_id), user: AuthUser = Depends(verify_token)):
    # Independently verify membership even when tenant was supplied by a session.
    member = await fetch_one("SELECT role FROM memberships WHERE user_id = $1 AND tenant_id = $2", user.id, tenant)
    if not member or member["role"] not in ("owner", "admin"):
        raise HTTPException(403, "Workspace owner or admin required")
    token = secrets.token_urlsafe(32)
    expiry = datetime.now(timezone.utc) + timedelta(hours=48)
    await execute("""INSERT INTO youtube_authorization_invites
        (id, tenant_id, token_hash, expected_channel_id, expires_at) VALUES ($1,$2,$3,$4,$5)""",
        uuid.uuid4(), tenant, digest(token), body.expected_channel_id, expiry)
    origin = os.getenv("FRONTEND_URL", "https://storyengine.dev").rstrip("/")
    return JSONResponse({"invite_url": f"{origin}/api/auth/youtube/invite/{token}", "expires_at": expiry.isoformat()}, headers=HEADERS)


async def active_invite(token: str):
    if len(token) > 128:
        raise HTTPException(404, "Invitation unavailable")
    row = await fetch_one("""SELECT i.id, i.expected_channel_id, p.youtube_channel_name
        FROM youtube_authorization_invites i
        LEFT JOIN channel_profiles p ON p.tenant_id=i.tenant_id
        WHERE i.token_hash=$1 AND i.consumed_at IS NULL AND i.expires_at>now()""", digest(token))
    if not row:
        raise HTTPException(410, "Invitation expired or already used. Request a new link.")
    return row


@router.get("/invite/{token}")
async def invite_landing(token: str):
    row = await active_invite(token)
    nonce = secrets.token_urlsafe(32)
    response = HTMLResponse(f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Connect YouTube · StoryEngine</title></head>
      <body style="font-family:system-ui;max-width:600px;margin:12vh auto;padding:24px"><h1>Connect your YouTube channel</h1>
      <p>Authorize StoryEngine to read your channel information and upload videos on your behalf. No StoryEngine account is needed.</p>
      <p>Choose the Google account that manages <strong>{html.escape(row.get('youtube_channel_name') or 'your channel')}</strong>, then select that YouTube channel.</p>
      <p><small>Channel ID: {html.escape(row['expected_channel_id'])}</small></p>
      <form method="post" action="/api/auth/youtube/invite/{html.escape(token)}/start"><input type="hidden" name="nonce" value="{nonce}"><button style="padding:14px 24px;font-size:18px">Connect with Google</button></form>
      <p>You can revoke access in your Google Account settings at any time. This invitation expires after 48 hours and can be used once.</p>
      <p><a href="/privacy">Privacy Policy</a> · <a href="/terms">Terms of Service</a></p></body></html>""", headers={**HEADERS, "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://accounts.google.com; frame-ancestors 'none'"})
    response.set_cookie(COOKIE, nonce, max_age=900, secure=True, httponly=True, samesite="lax", path=COOKIE_PATH)
    return response


@router.post("/invite/{token}/start")
async def invite_start(token: str, request: Request):
    from urllib.parse import parse_qs
    raw = await request.body()
    nonce = parse_qs(raw.decode()).get("nonce", [""])[0] if len(raw) < 2048 else ""
    cookie = request.cookies.get(COOKIE, "")
    if not nonce or not cookie or not hmac.compare_digest(nonce, cookie):
        raise HTTPException(403, "Please reopen the invitation in this browser.")
    row = await active_invite(token)
    oauth = get_youtube_oauth_credentials()
    if oauth.missing_env:
        raise HTTPException(503, "YouTube authorization is temporarily unavailable")
    state = "ytinvite." + secrets.token_urlsafe(32)
    browser = secrets.token_urlsafe(32)
    await execute("""INSERT INTO youtube_invite_oauth_states (state_hash,invite_id,browser_hash,expires_at)
        VALUES ($1,$2,$3,$4)""", digest(state), row["id"], digest(browser), datetime.now(timezone.utc)+timedelta(minutes=15))
    response = RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": oauth.client_id, "redirect_uri": redirect_uri(), "response_type": "code",
        "scope": SCOPES, "access_type": "offline", "prompt": "consent select_account", "state": state,
    }), status_code=303, headers=HEADERS)
    response.set_cookie(COOKIE, browser, max_age=900, secure=True, httponly=True, samesite="lax", path=COOKIE_PATH)
    return response


@router.post("/invite-callback")
async def invite_callback(body: InviteCallback, request: Request):
    browser = request.cookies.get(COOKIE, "")
    if not body.state.startswith("ytinvite.") or not browser:
        raise HTTPException(403, "Authorization browser session is missing. Reopen your invitation.")
    # Claim state atomically before contacting Google. Replays cannot exchange codes.
    state = await fetch_one("""UPDATE youtube_invite_oauth_states SET consumed_at=now()
        WHERE state_hash=$1 AND browser_hash=$2 AND consumed_at IS NULL AND expires_at>now()
        RETURNING invite_id""", digest(body.state), digest(browser))
    if not state:
        raise HTTPException(410, "Authorization expired or already processed. Reopen your invitation.")
    if body.error or not body.code:
        raise HTTPException(400, "Google authorization was not completed. Reopen your invitation to retry.")
    invite = await fetch_one("""SELECT tenant_id, expected_channel_id FROM youtube_authorization_invites
        WHERE id=$1 AND consumed_at IS NULL AND expires_at>now()""", state["invite_id"])
    if not invite:
        raise HTTPException(410, "Invitation expired or already used")
    oauth = get_youtube_oauth_credentials()
    if oauth.missing_env:
        raise HTTPException(503, "YouTube authorization is temporarily unavailable")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://oauth2.googleapis.com/token", data={
                "code": body.code, "client_id": oauth.client_id, "client_secret": oauth.client_secret,
                "redirect_uri": redirect_uri(), "grant_type": "authorization_code"}, timeout=15)
            response.raise_for_status()
            tokens = response.json()
            if not tokens.get("refresh_token") or not tokens.get("access_token"):
                raise ValueError("Missing tokens")
            if not set(SCOPES.split()).issubset(set(tokens.get("scope", "").split())):
                raise ValueError("Missing permissions")
            response = await client.get("https://www.googleapis.com/youtube/v3/channels",
                params={"part": "snippet", "mine": "true"}, headers={"Authorization": "Bearer " + tokens["access_token"]}, timeout=15)
            response.raise_for_status()
            channels = response.json().get("items", [])
            if len(channels) != 1 or channels[0].get("id") != invite["expected_channel_id"]:
                raise HTTPException(400, "The selected YouTube channel does not match this invitation. Reopen the link and choose the correct channel.")
            name = channels[0].get("snippet", {}).get("title", "")
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(400, "Could not verify YouTube access. Reopen your invitation and grant both requested permissions.")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            claimed = await conn.fetchrow("""UPDATE youtube_authorization_invites SET consumed_at=now()
                WHERE id=$1 AND consumed_at IS NULL AND expires_at>now() RETURNING tenant_id""", state["invite_id"])
            if not claimed:
                raise HTTPException(410, "Invitation expired or already used")
            await conn.execute("""INSERT INTO channel_profiles (tenant_id,youtube_refresh_token,youtube_channel_id,youtube_channel_name)
                VALUES ($1,$2,$3,$4) ON CONFLICT (tenant_id) DO UPDATE SET youtube_refresh_token=EXCLUDED.youtube_refresh_token,
                youtube_channel_id=EXCLUDED.youtube_channel_id,youtube_channel_name=EXCLUDED.youtube_channel_name,updated_at=now()""",
                claimed["tenant_id"], tokens["refresh_token"], invite["expected_channel_id"], name)
    result = JSONResponse({"connected": True, "channel_id": invite["expected_channel_id"], "channel_name": name}, headers=HEADERS)
    result.delete_cookie(COOKIE, path=COOKIE_PATH, secure=True, httponly=True, samesite="lax")
    return result
