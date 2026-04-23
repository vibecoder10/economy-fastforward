"""Functional regression lock for Google Auth / Drive OAuth endpoint shapes.

Stage 3.3 audit (2026-04-23): all 5 Drive OAuth endpoints and the Google
login endpoint shipped in commit e167b0a8. This file pins their response
shapes so a refactor can't silently break the callback contract that the
frontend drive-callback page depends on.

Wire-up links pinned here (6 total):
  1. GET  /api/auth/google-drive/connect   → {"auth_url": str}
  2. POST /api/auth/google-drive/callback  → {"status": "connected", "access_token": str}
  3. GET  /api/auth/google-drive/status    → {"connected": bool, "folder_id": str|None, "folder_name": str|None}
  4. POST /api/auth/google-drive/disconnect → {"status": "disconnected"}
  5. POST /api/auth/google-drive/access-token → {"access_token": str}
  6. POST /api/auth/google              → AuthResponse {"token": str, "user": dict}

If any of these shapes change without updating the frontend and this test,
this file flags it.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _storyengine_dir() -> Path:
    return Path(__file__).resolve().parents[3]


def _repo_read(rel: str) -> str:
    path = _storyengine_dir() / rel
    assert path.exists(), f"Expected file missing: {rel}"
    return path.read_text()


# ── Link 1: GET /google-drive/connect ──────────────────────────────────────

def test_drive_connect_endpoint_exists():
    src = _repo_read("backend/routes/google_auth.py")
    assert re.search(
        r'@router\.get\(\s*"/google-drive/connect"\s*\)\s*\nasync\s+def\s+google_drive_connect',
        src,
    ), "GET /google-drive/connect must exist as google_drive_connect()."


def test_drive_connect_returns_auth_url():
    src = _repo_read("backend/routes/google_auth.py")
    m = re.search(
        r"async def google_drive_connect[\s\S]*?(?=\n@router\.|\Z)",
        src,
    )
    assert m, "google_drive_connect() function not found."
    assert re.search(r'return\s*\{\s*["\']auth_url["\']\s*:', m.group(0)), (
        "google_drive_connect() must return {'auth_url': ...}."
    )


# ── Link 2: POST /google-drive/callback ────────────────────────────────────

def test_drive_callback_endpoint_exists():
    src = _repo_read("backend/routes/google_auth.py")
    assert re.search(
        r'@router\.post\(\s*"/google-drive/callback"\s*\)\s*\nasync\s+def\s+google_drive_callback',
        src,
    ), "POST /google-drive/callback must exist as google_drive_callback()."


def test_drive_callback_returns_connected_status_and_access_token():
    src = _repo_read("backend/routes/google_auth.py")
    assert re.search(
        r'return\s*\{\s*["\']status["\']\s*:\s*["\']connected["\']\s*,\s*["\']access_token["\']\s*:',
        src,
    ), (
        "google_drive_callback() must return {'status': 'connected', 'access_token': ...}. "
        "drive-callback/page.tsx relies on this shape."
    )


def test_drive_callback_request_has_code_field():
    src = _repo_read("backend/routes/google_auth.py")
    assert re.search(
        r"class\s+DriveCallbackRequest\b[\s\S]{0,200}?code\s*:\s*str",
        src,
    ), "DriveCallbackRequest must have `code: str` field (frontend sends {code})."


# ── Link 3: GET /google-drive/status ───────────────────────────────────────

def test_drive_status_endpoint_exists():
    src = _repo_read("backend/routes/google_auth.py")
    assert re.search(
        r'@router\.get\(\s*"/google-drive/status"\s*\)\s*\nasync\s+def\s+google_drive_status',
        src,
    ), "GET /google-drive/status must exist as google_drive_status()."


def test_drive_status_returns_connected_folder_id_folder_name():
    src = _repo_read("backend/routes/google_auth.py")
    m = re.search(
        r"async def google_drive_status[\s\S]*?(?=\n@router\.|\Z)",
        src,
    )
    assert m, "google_drive_status() function not found."
    fn = m.group(0)
    assert re.search(r'["\']connected["\']\s*:', fn), (
        "google_drive_status() must return 'connected' key."
    )
    assert re.search(r'["\']folder_id["\']\s*:', fn), (
        "google_drive_status() must return 'folder_id' key."
    )
    assert re.search(r'["\']folder_name["\']\s*:', fn), (
        "google_drive_status() must return 'folder_name' key."
    )


# ── Link 4: POST /google-drive/disconnect ──────────────────────────────────

def test_drive_disconnect_endpoint_exists():
    src = _repo_read("backend/routes/google_auth.py")
    assert re.search(
        r'@router\.post\(\s*"/google-drive/disconnect"\s*\)\s*\nasync\s+def\s+google_drive_disconnect',
        src,
    ), "POST /google-drive/disconnect must exist as google_drive_disconnect()."


def test_drive_disconnect_returns_disconnected_status():
    src = _repo_read("backend/routes/google_auth.py")
    m = re.search(
        r"async def google_drive_disconnect[\s\S]*?(?=\n@router\.|\Z)",
        src,
    )
    assert m, "google_drive_disconnect() function not found."
    assert re.search(
        r'return\s*\{\s*["\']status["\']\s*:\s*["\']disconnected["\']\s*\}',
        m.group(0),
    ), "google_drive_disconnect() must return {'status': 'disconnected'}."


# ── Link 5: POST /google-drive/access-token ────────────────────────────────

def test_drive_access_token_endpoint_exists():
    src = _repo_read("backend/routes/google_auth.py")
    assert re.search(
        r'@router\.post\(\s*"/google-drive/access-token"\s*\)\s*\nasync\s+def\s+google_drive_access_token',
        src,
    ), "POST /google-drive/access-token must exist as google_drive_access_token()."


def test_drive_access_token_returns_access_token():
    src = _repo_read("backend/routes/google_auth.py")
    m = re.search(
        r"async def google_drive_access_token[\s\S]*?(?=\n@router\.|\Z)",
        src,
    )
    assert m, "google_drive_access_token() function not found."
    assert re.search(r'return\s*\{\s*["\']access_token["\']\s*:', m.group(0)), (
        "google_drive_access_token() must return {'access_token': ...}."
    )


# ── Link 6: POST /api/auth/google (Google login) ──────────────────────────

def test_google_login_endpoint_exists():
    src = _repo_read("backend/routes/google_auth.py")
    assert re.search(
        r'@router\.post\(\s*"/google"[\s\S]{0,60}?\)\s*\nasync\s+def\s+google_login',
        src,
    ), "POST /api/auth/google must exist as google_login()."


def test_google_login_returns_token_and_user():
    src = _repo_read("backend/routes/google_auth.py")
    assert re.search(r"response_model\s*=\s*AuthResponse", src), (
        "google_login() must declare response_model=AuthResponse."
    )
    assert re.search(
        r"class\s+AuthResponse\b[\s\S]{0,200}?token\s*:\s*str[\s\S]{0,200}?user\s*:\s*dict",
        src,
    ), "AuthResponse must have `token: str` and `user: dict` fields."


# ── Frontend api.ts wiring ─────────────────────────────────────────────────

def test_frontend_api_exports_all_drive_functions():
    src = _repo_read("frontend/src/lib/api.ts")
    for fn_name in [
        "getDriveStatus",
        "getDriveConnectUrl",
        "postDriveCallback",
        "disconnectDrive",
        "getDriveAccessToken",
    ]:
        assert f"export const {fn_name}" in src, (
            f"frontend/src/lib/api.ts must export `{fn_name}`."
        )


def test_frontend_drive_status_type_has_required_fields():
    src = _repo_read("frontend/src/lib/api.ts")
    m = re.search(
        r"interface\s+DriveStatus\b[\s\S]{0,300}?connected\s*:\s*bool",
        src,
    )
    assert m, "DriveStatus interface must have `connected: boolean`."
    assert re.search(r"folder_id\s*\??\s*:\s*string", src), (
        "DriveStatus interface must have `folder_id` field."
    )
    assert re.search(r"folder_name\s*\??\s*:\s*string", src), (
        "DriveStatus interface must have `folder_name` field."
    )


def test_drive_callback_page_exchanges_code_with_backend():
    src = _repo_read("frontend/src/app/settings/drive-callback/page.tsx")
    assert re.search(
        r"/api/auth/google-drive/callback",
        src,
    ), "drive-callback/page.tsx must POST to /api/auth/google-drive/callback."
    assert re.search(r'method:\s*"POST"', src), (
        "drive-callback/page.tsx must use POST method for the callback exchange."
    )
