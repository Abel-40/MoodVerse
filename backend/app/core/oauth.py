"""The Authlib OAuth client registry for OIDC login.

One `OAuth` registry for the whole app, the way `get_settings()` is one
Settings for the whole app. `oauth.google` only exists once `GOOGLE_CLIENT_ID`
and `GOOGLE_CLIENT_SECRET` are set; api/v1/oidc.py checks `settings.oidc_enabled`
before touching it, the same tolerance the Gemini provider gives a missing key.
"""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from app.core.config import get_settings

_settings = get_settings()

oauth = OAuth()

if _settings.oidc_enabled:
    oauth.register(
        name="google",
        client_id=_settings.google_client_id,
        client_secret=_settings.google_client_secret,
        server_metadata_url=_settings.oidc_google_discovery_url,
        client_kwargs={"scope": "openid profile email"},
    )
