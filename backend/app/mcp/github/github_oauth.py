import os
from urllib.parse import urlencode

import requests
from fastapi import HTTPException


def _github_config() -> tuple[str, str, str]:
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    redirect_uri = os.getenv("GITHUB_REDIRECT_URI")
    if not redirect_uri or "YOUR_EC2_PUBLIC_IP" in redirect_uri or "YOUR_" in redirect_uri:
        redirect_uri = "http://localhost:8000/mcp/github/callback"

    missing = [
        name
        for name, value in {
            "GITHUB_CLIENT_ID": client_id,
            "GITHUB_CLIENT_SECRET": client_secret,
        }.items()
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=(
                "GitHub OAuth is not configured. "
                f"Missing environment variable(s): {', '.join(missing)}."
            ),
        )

    return client_id, client_secret, redirect_uri


def get_github_login_url(user_key: str):
    client_id, _client_secret, redirect_uri = _github_config()
    params = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "read:user repo",
            # Ask GitHub to show the account chooser so users can pick the right login.
            "prompt": "select_account",
            # Keep the state token exact; it is an opaque value used to restore the user context.
            "state": (user_key or "demo").strip(),
            "allow_signup": "true",
        }
    )
    return f"https://github.com/login/oauth/authorize?{params}"


def process_github_callback(code: str, user_key: str):
    client_id, client_secret, redirect_uri = _github_config()

    token_url = "https://github.com/login/oauth/access_token"

    headers = {
        "Accept": "application/json"
    }

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }

    try:
        response = requests.post(
            token_url,
            data=data,
            headers=headers,
            timeout=15,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub token exchange request failed: {exc}",
        ) from exc

    if not response.ok:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub token exchange failed: {response.text}",
        )

    token_data = response.json()
    access_token = token_data.get("access_token")

    if not access_token:
        raise HTTPException(
            status_code=502,
            detail=token_data.get("error_description") or "GitHub access token missing.",
        )

    try:
        user_response = requests.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub user fetch request failed: {exc}",
        ) from exc

    if not user_response.ok:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub user fetch failed: {user_response.text}",
        )

    user_data = user_response.json()

    return {
        "connected": True,
        "username": user_data.get("login"),
        "avatar_url": user_data.get("avatar_url"),
        "access_token": access_token,
    }
