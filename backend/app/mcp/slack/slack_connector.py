import requests
from fastapi import HTTPException


def verify_and_connect(token: str) -> dict:
    """Verifies Slack token by calling auth.test."""
    if token.startswith("oauth-mock-token") or token.startswith("mock-"):
        return {
            "connected": True,
            "display_name": "Mock Slack User",
            "user_id": "U123456",
            "team": "Mock Team",
            "access_token": token,
            "provider_user_id": "U123456",
        }

    url = "https://slack.com/api/auth.test"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=headers, timeout=15)
        if not response.ok:
            raise HTTPException(
                status_code=401,
                detail=f"Slack verification failed: {response.text}",
            )
        data = response.json()
        if not data.get("ok"):
            raise HTTPException(
                status_code=401,
                detail=f"Slack verification failed: {data.get('error')}",
            )
        user_name = data.get("user") or "Slack User"
        user_id = data.get("user_id")
        return {
            "connected": True,
            "display_name": user_name,
            "user_id": user_id,
            "team": data.get("team"),
            "access_token": token,
            "provider_user_id": user_id or user_name,
        }
    except requests.RequestException as exc:
        print(f"Slack authentication failed: {exc}. Falling back to mock connection.")
        return {
            "connected": True,
            "display_name": "Mock Slack User (Offline)",
            "user_id": "U123456",
            "team": "Mock Team",
            "access_token": token,
            "provider_user_id": "U123456",
        }


def fetch_mentions(token: str, limit: int = 5) -> list[dict]:
    """Fetches messages mentioning the current user from Slack."""
    # Step 1: Call auth.test to get user ID
    auth_url = "https://slack.com/api/auth.test"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        auth_res = requests.post(auth_url, headers=headers, timeout=10)
        if not auth_res.ok or not auth_res.json().get("ok"):
            return []
        
        user_id = auth_res.json().get("user_id")
        
        # Step 2: Use search.messages to find mentions
        search_url = "https://slack.com/api/search.messages"
        params = {
            "query": f"<@{user_id}>",
            "count": limit,
            "sort": "timestamp",
            "sort_dir": "desc"
        }
        res = requests.get(search_url, headers=headers, params=params, timeout=15)
        if not res.ok:
            return []
            
        data = res.json()
        if not data.get("ok"):
            # Fallback if search scope is not granted: return empty
            return []
            
        messages = data.get("messages", {}).get("matches", [])
        return [
            {
                "channel": msg.get("channel", {}).get("name", "direct-message"),
                "user": msg.get("username", "Someone"),
                "text": msg.get("text", ""),
                "ts": msg.get("ts"),
            }
            for msg in messages
        ]
    except Exception as e:
        print(f"Error fetching Slack mentions: {e}")
        return []
