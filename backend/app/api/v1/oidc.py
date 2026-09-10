"""Google OIDC login, backed by Authlib's Starlette integration.

Requires `SessionMiddleware` on the app (wired in app/main.py) - Authlib's
`authorize_redirect`/`authorize_access_token` pair use `request.session` to
carry the `state` and `nonce` between the redirect out to Google and the
callback back in. `authorize_access_token` validates the returned ID token's
signature (against Google's published JWKS) and its `nonce` before this file
ever sees a claim from it - see StarletteOAuth2App.authorize_access_token.

The provider's identity is never itself a session credential here: the
callback exchanges it for a MoodVerse access/refresh pair via
app.services.auth.issue_tokens, the same call the password-login route makes,
so get_current_user recognises an OIDC-authenticated user exactly like any
other.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from authlib.integrations.base_client import OAuthError

from app.core.config import Settings, get_settings
from app.core.oauth import oauth
from app.db.session import get_session
from app.schemas.auth import TokenResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/auth/oidc", tags=["auth"])


def _require_enabled(settings: Settings) -> None:
    if not settings.oidc_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google OIDC login is not configured (GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET unset).",
        )


@router.get("/login", name="oidc_login")
async def oidc_login(
    request: Request,
    redirect_uri: str | None = None,
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Start the flow: redirect the user agent to Google.

    `redirect_uri` here is OUR client's deep link to return to after login
    (e.g. a React Native app's `moodverse://auth`), not the OIDC callback URL
    registered with Google - that one is `oidc_redirect_uri` / oidc_callback
    below. It is only honoured against `OIDC_ALLOWED_APP_REDIRECTS`: handing
    a freshly issued access/refresh token to an unvalidated caller-supplied
    URL would be an open redirect that leaks credentials to whoever crafted
    the link.
    """
    _require_enabled(settings)

    if redirect_uri is not None and redirect_uri not in settings.oidc_allowed_app_redirects:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "redirect_uri is not on the configured allow-list "
            "(OIDC_ALLOWED_APP_REDIRECTS).",
        )
    # Read back in the callback below; separate from Authlib's own
    # state/nonce bookkeeping, which it manages in this same session itself.
    request.session["oidc_app_redirect"] = redirect_uri

    callback_url = settings.oidc_redirect_uri or str(request.url_for("oidc_callback"))
    return await oauth.google.authorize_redirect(request, callback_url)


@router.get("/callback", name="oidc_callback", response_model=None)
async def oidc_callback(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TokenResponse | RedirectResponse:
    _require_enabled(settings)

    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"OIDC login failed: {exc.description or exc.error}",
        ) from exc

    # authorize_access_token already parsed and nonce-validated the ID token
    # into token["userinfo"] whenever an id_token came back, which the openid
    # scope guarantees. The userinfo-endpoint fetch is only a fallback.
    userinfo = token.get("userinfo") or await oauth.google.userinfo(token=token)

    sub = userinfo.get("sub")
    if not sub:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "OIDC provider did not return a subject identifier."
        )

    user = await auth_service.find_or_create_oidc_user(
        session,
        provider="google",
        provider_user_id=sub,
        email=userinfo.get("email"),
        email_verified=bool(userinfo.get("email_verified")),
        display_name=userinfo.get("name"),
    )
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is disabled.")

    tokens = await auth_service.issue_tokens(session, user, settings)

    app_redirect = request.session.pop("oidc_app_redirect", None)
    if app_redirect:
        separator = "&" if "?" in app_redirect else "?"
        return RedirectResponse(
            f"{app_redirect}{separator}access_token={tokens.access_token}"
            f"&refresh_token={tokens.refresh_token}&token_type=bearer"
        )

    return tokens


@router.get("/logout", name="oidc_logout")
async def oidc_logout(
    request: Request,
    post_logout_redirect_uri: str | None = None,
    settings: Settings = Depends(get_settings),
):
    """RP-Initiated Logout (OIDC spec) via Authlib's `logout_redirect`.

    Written against the spec so it works unchanged for any compliant
    provider (Okta, Auth0, Keycloak, ...). Google specifically does not
    publish an `end_session_endpoint` in its discovery document - it does not
    implement RP-Initiated Logout - so for Google this clears the local
    session and reports that fact rather than redirecting, which is the most
    an RP can do against a provider that does not support the flow.
    """
    _require_enabled(settings)
    request.session.clear()

    metadata = await oauth.google.load_server_metadata()
    if not metadata.get("end_session_endpoint"):
        return {
            "logged_out": True,
            "provider_logout": False,
            "reason": "google does not publish an end_session_endpoint (no RP-Initiated Logout support)",
        }

    safe_redirect = (
        post_logout_redirect_uri
        if post_logout_redirect_uri in settings.oidc_allowed_app_redirects
        else None
    )
    return await oauth.google.logout_redirect(
        request, post_logout_redirect_uri=safe_redirect
    )
