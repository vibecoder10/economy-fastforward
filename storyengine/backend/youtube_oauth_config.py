"""Resolve the OAuth client used for YouTube without affecting other Google flows."""

from __future__ import annotations

import os
from typing import NamedTuple


YOUTUBE_CLIENT_ID_ENV = "YOUTUBE_OAUTH_CLIENT_ID"
YOUTUBE_CLIENT_SECRET_ENV = "YOUTUBE_OAUTH_CLIENT_SECRET"
LEGACY_CLIENT_ID_ENV = "GOOGLE_OAUTH_CLIENT_ID"
LEGACY_CLIENT_SECRET_ENV = "GOOGLE_OAUTH_CLIENT_SECRET"


class YouTubeOAuthCredentials(NamedTuple):
    client_id: str | None
    client_secret: str | None
    source: str
    missing_env: list[str]


def get_youtube_oauth_credentials() -> YouTubeOAuthCredentials:
    """Return one complete client pair; never mix dedicated and legacy values.

    A deployment that declares either dedicated variable has opted into the
    split. A partial dedicated pair therefore fails closed instead of silently
    pairing a new client ID with an unrelated legacy secret. Deployments that
    declare neither dedicated variable retain the legacy shared-client behavior.
    """
    dedicated_declared = any(
        name in os.environ
        for name in (YOUTUBE_CLIENT_ID_ENV, YOUTUBE_CLIENT_SECRET_ENV)
    )
    if dedicated_declared:
        client_id = os.getenv(YOUTUBE_CLIENT_ID_ENV) or None
        client_secret = os.getenv(YOUTUBE_CLIENT_SECRET_ENV) or None
        names = (YOUTUBE_CLIENT_ID_ENV, YOUTUBE_CLIENT_SECRET_ENV)
        source = "youtube_specific"
    else:
        client_id = os.getenv(LEGACY_CLIENT_ID_ENV) or None
        client_secret = os.getenv(LEGACY_CLIENT_SECRET_ENV) or None
        names = (LEGACY_CLIENT_ID_ENV, LEGACY_CLIENT_SECRET_ENV)
        source = "legacy_google_oauth" if client_id or client_secret else "missing"

    values = (client_id, client_secret)
    missing = [name for name, value in zip(names, values) if not value]
    if source == "missing":
        # Diagnostics should direct new deployments to the dedicated contract.
        missing = [YOUTUBE_CLIENT_ID_ENV, YOUTUBE_CLIENT_SECRET_ENV]
    return YouTubeOAuthCredentials(client_id, client_secret, source, missing)
