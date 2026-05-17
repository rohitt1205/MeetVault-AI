import os
import requests

def get_github_login_url(user_key: str):
    client_id = os.getenv("GITHUB_CLIENT_ID")
    redirect_uri = os.getenv(
        "GITHUB_REDIRECT_URI",
        "http://localhost:8000/mcp/github/callback"
    )

    if not client_id:
        raise Exception("Missing GITHUB_CLIENT_ID")

    return (
        "https://github.com/login/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=read:user,repo"
        f"&state={user_key}"
    )


def process_github_callback(code: str, user_key: str):
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    redirect_uri = os.getenv(
        "GITHUB_REDIRECT_URI",
        "http://localhost:8000/mcp/github/callback"
    )

    token_url = "https://github.com/login/oauth/access_token"

    headers = {
        "Accept": "application/json"
    }

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri
    }

    response = requests.post(
        token_url,
        json=data,
        headers=headers,
        timeout=15
    )

    if not response.ok:
        raise Exception(f"GitHub token exchange failed: {response.text}")

    token_data = response.json()
    access_token = token_data.get("access_token")

    if not access_token:
        raise Exception("GitHub access token missing")

    user_response = requests.get(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json"
        },
        timeout=15
    )

    if not user_response.ok:
        raise Exception(f"GitHub user fetch failed: {user_response.text}")

    user_data = user_response.json()

    return {
        "connected": True,
        "username": user_data.get("login"),
        "avatar_url": user_data.get("avatar_url"),
        "access_token": access_token
    }
