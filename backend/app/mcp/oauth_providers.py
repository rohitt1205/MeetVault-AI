import os
from urllib.parse import urlencode

import requests
from fastapi import HTTPException


def _frontend_origin() -> str:
    return os.getenv("FRONTEND_ORIGIN", "http://127.0.0.1:5173").rstrip("/")


def _required_env(provider: str, names: list[str]) -> dict[str, str]:
    values = {name: os.getenv(name) for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=(
                f"{provider} OAuth is not configured. "
                f"Missing environment variable(s): {', '.join(missing)}."
            ),
        )
    return values


def _callback_url(provider: str) -> str:
    env_name = f"{provider.upper()}_REDIRECT_URI"
    redirect_uri = os.getenv(env_name)
    if not redirect_uri or "YOUR_EC2_PUBLIC_IP" in redirect_uri or "YOUR_" in redirect_uri:
        return f"http://localhost:8000/mcp/{provider}/callback"
    return redirect_uri


def _post_form(url: str, data: dict, headers: dict | None = None) -> dict:
    try:
        response = requests.post(url, data=data, headers=headers or {}, timeout=15)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"OAuth token request failed: {exc}") from exc

    if not response.ok:
        raise HTTPException(status_code=502, detail=f"OAuth token exchange failed: {response.text}")

    return response.json()


def _get_json(url: str, token: str, headers: dict | None = None) -> dict:
    request_headers = {"Authorization": f"Bearer {token}", **(headers or {})}
    try:
        response = requests.get(url, headers=request_headers, timeout=15)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"OAuth profile request failed: {exc}") from exc

    if not response.ok:
        raise HTTPException(status_code=502, detail=f"OAuth profile fetch failed: {response.text}")

    return response.json()


def build_login_url(provider: str, state: str) -> str:
    normalized_state = state or "demo"

    if provider == "slack":
        cfg = _required_env("Slack", ["SLACK_CLIENT_ID"])
        user_scopes = os.getenv(
            "SLACK_USER_OAUTH_SCOPES",
            os.getenv(
                "SLACK_OAUTH_SCOPES",
                "users:read users:read.email search:read channels:read groups:read im:read mpim:read channels:history groups:history im:history mpim:history",
            ),
        ).replace(",", " ")
        params = urlencode(
            {
                "client_id": cfg["SLACK_CLIENT_ID"],
                "user_scope": user_scopes,
                "redirect_uri": _callback_url("slack"),
                "state": normalized_state,
            }
        )
        return f"https://slack.com/oauth/v2/authorize?{params}"

    if provider == "salesforce":
        cfg = _required_env("Salesforce", ["SALESFORCE_CLIENT_ID"])
        login_base = os.getenv("SALESFORCE_LOGIN_URL", "https://login.salesforce.com").rstrip("/")
        params = urlencode(
            {
                "client_id": cfg["SALESFORCE_CLIENT_ID"],
                "redirect_uri": _callback_url("salesforce"),
                "response_type": "code",
                "scope": os.getenv("SALESFORCE_OAUTH_SCOPES", "api refresh_token openid email profile"),
                "state": normalized_state,
            }
        )
        return f"{login_base}/services/oauth2/authorize?{params}"

    if provider == "notion":
        cfg = _required_env("Notion", ["NOTION_CLIENT_ID"])
        params = urlencode(
            {
                "client_id": cfg["NOTION_CLIENT_ID"],
                "redirect_uri": _callback_url("notion"),
                "response_type": "code",
                "owner": "user",
                "state": normalized_state,
            }
        )
        return f"https://api.notion.com/v1/oauth/authorize?{params}"

    if provider == "gmail":
        cfg = _required_env("Google", ["GOOGLE_CLIENT_ID"])
        params = urlencode(
            {
                "client_id": cfg["GOOGLE_CLIENT_ID"],
                "redirect_uri": _callback_url("gmail"),
                "response_type": "code",
                "scope": os.getenv(
                    "GOOGLE_GMAIL_OAUTH_SCOPES",
                    "openid email profile https://www.googleapis.com/auth/gmail.readonly",
                ),
                "access_type": "offline",
                "prompt": "consent",
                "state": normalized_state,
            }
        )
        return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"

    raise HTTPException(status_code=404, detail=f"OAuth provider {provider} is not supported.")


def exchange_callback(provider: str, code: str) -> dict:
    if provider == "slack":
        cfg = _required_env("Slack", ["SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET"])
        data = _post_form(
            "https://slack.com/api/oauth.v2.access",
            {
                "client_id": cfg["SLACK_CLIENT_ID"],
                "client_secret": cfg["SLACK_CLIENT_SECRET"],
                "code": code,
                "redirect_uri": _callback_url("slack"),
            },
        )
        if not data.get("ok"):
            raise HTTPException(status_code=502, detail=data.get("error") or "Slack OAuth failed.")
        token = data.get("authed_user", {}).get("access_token") or data.get("access_token")
        if not token:
            raise HTTPException(status_code=502, detail="Slack access token missing.")
        return {
            "connected": True,
            "access_token": token,
            "provider_user_id": data.get("authed_user", {}).get("id") or data.get("team", {}).get("id"),
            "display_name": data.get("team", {}).get("name"),
            "team": data.get("team", {}).get("name"),
        }

    if provider == "salesforce":
        cfg = _required_env("Salesforce", ["SALESFORCE_CLIENT_ID", "SALESFORCE_CLIENT_SECRET"])
        login_base = os.getenv("SALESFORCE_LOGIN_URL", "https://login.salesforce.com").rstrip("/")
        data = _post_form(
            f"{login_base}/services/oauth2/token",
            {
                "grant_type": "authorization_code",
                "client_id": cfg["SALESFORCE_CLIENT_ID"],
                "client_secret": cfg["SALESFORCE_CLIENT_SECRET"],
                "code": code,
                "redirect_uri": _callback_url("salesforce"),
            },
        )
        token = data.get("access_token")
        instance_url = data.get("instance_url")
        if not token or not instance_url:
            raise HTTPException(status_code=502, detail="Salesforce OAuth response missing token or instance URL.")
        profile = _get_json(f"{instance_url.rstrip('/')}/services/oauth2/userinfo", token)
        email = profile.get("email") or profile.get("preferred_username")
        return {
            "connected": True,
            "access_token": token,
            "refresh_token": instance_url.rstrip("/"),
            "instance_url": instance_url.rstrip("/"),
            "display_name": profile.get("name"),
            "email": email,
            "provider_user_id": email or profile.get("sub"),
            "expires_at": data.get("expires_in"),
        }

    if provider == "notion":
        cfg = _required_env("Notion", ["NOTION_CLIENT_ID", "NOTION_CLIENT_SECRET"])
        data = _post_form(
            "https://api.notion.com/v1/oauth/token",
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _callback_url("notion"),
            },
            headers={
                "Authorization": requests.auth._basic_auth_str(
                    cfg["NOTION_CLIENT_ID"], cfg["NOTION_CLIENT_SECRET"]
                ),
            },
        )
        token = data.get("access_token")
        if not token:
            raise HTTPException(status_code=502, detail="Notion access token missing.")
        owner = data.get("owner", {}).get("user", {})
        provider_user_id = owner.get("person", {}).get("email") or owner.get("id") or data.get("workspace_id")
        return {
            "connected": True,
            "access_token": token,
            "provider_user_id": provider_user_id,
            "email": owner.get("person", {}).get("email"),
            "display_name": owner.get("name") or data.get("workspace_name"),
            "workspace_name": data.get("workspace_name"),
        }

    if provider == "gmail":
        cfg = _required_env("Google", ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"])
        data = _post_form(
            "https://oauth2.googleapis.com/token",
            {
                "grant_type": "authorization_code",
                "client_id": cfg["GOOGLE_CLIENT_ID"],
                "client_secret": cfg["GOOGLE_CLIENT_SECRET"],
                "code": code,
                "redirect_uri": _callback_url("gmail"),
            },
        )
        token = data.get("access_token")
        if not token:
            raise HTTPException(status_code=502, detail="Google access token missing.")
        profile = _get_json("https://www.googleapis.com/oauth2/v3/userinfo", token)
        return {
            "connected": True,
            "access_token": token,
            "refresh_token": data.get("refresh_token"),
            "expires_at": data.get("expires_in"),
            "email": profile.get("email"),
            "display_name": profile.get("name"),
            "provider_user_id": profile.get("email") or profile.get("sub"),
        }

    raise HTTPException(status_code=404, detail=f"OAuth provider {provider} is not supported.")


def frontend_redirect(provider: str, connected: bool, error: str | None = None) -> str:
    params = {f"{provider}_connected": "true" if connected else "false"}
    if error:
        params["mcp_error"] = error
    return f"{_frontend_origin()}/oauth-complete.html?{urlencode(params)}"
