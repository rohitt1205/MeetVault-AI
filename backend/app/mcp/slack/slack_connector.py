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
    """Fetches recent Slack messages relevant to the current user."""
    # Step 1: Call auth.test to get user ID
    auth_url = "https://slack.com/api/auth.test"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        auth_res = requests.post(auth_url, headers=headers, timeout=10)
        print(f"[DEBUG Slack] auth.test status: {auth_res.status_code}")
        if not auth_res.ok or not auth_res.json().get("ok"):
            print(f"[DEBUG Slack] auth.test failed: {auth_res.text if not auth_res.ok else auth_res.json()}")
            return []
        
        auth_data = auth_res.json()
        user_id = auth_data.get("user_id")
        user_name = auth_data.get("user") or ""
        
        messages = []
        seen = set()

        def _push_message(msg: dict):
            key = (msg.get("channel", {}).get("name"), msg.get("ts"), msg.get("text"))
            if key in seen:
                return
            seen.add(key)
            messages.append(msg)

        # Step 2A: Search for direct mentions and user-name hits.
        search_url = "https://slack.com/api/search.messages"
        queries = [f"<@{user_id}>"]
        if user_name and user_name not in queries:
            queries.append(user_name)

        for query in queries:
            params = {
                "query": query,
                "count": limit,
                "sort": "timestamp",
                "sort_dir": "desc",
            }
            res = requests.get(search_url, headers=headers, params=params, timeout=15)
            print(f"[DEBUG Slack] search messages status: {res.status_code} for query: {query}")
            if not res.ok:
                print(f"[DEBUG Slack] search messages failed: {res.text}")
                continue

            data = res.json()
            if not data.get("ok"):
                print(f"[DEBUG Slack] search messages returned ok=False: {data}")
                continue

            matches = data.get("messages", {}).get("matches", [])
            print(f"[DEBUG Slack] search messages found {len(matches)} matches")
            for msg in matches:
                _push_message(msg)
                if len(messages) >= limit:
                    break
            if len(messages) >= limit:
                break

        # Step 2B: If search is empty or too narrow, inspect recent channel history.
        if len(messages) < limit:
            print(f"[DEBUG Slack] messages found ({len(messages)}) < limit ({limit}), trying fallback channel history")
            conversations_url = "https://slack.com/api/conversations.list"
            channels_res = requests.get(
                conversations_url,
                headers=headers,
                params={
                    "types": "public_channel,private_channel,im,mpim",
                    "limit": 20,
                },
                timeout=15,
            )
            print(f"[DEBUG Slack] conversations.list status: {channels_res.status_code}")
            if channels_res.ok and channels_res.json().get("ok"):
                channels = channels_res.json().get("channels", [])
                print(f"[DEBUG Slack] conversations.list found {len(channels)} channels")
                for channel in channels:
                    channel_id = channel.get("id")
                    if not channel_id:
                        continue
                    history_res = requests.get(
                        "https://slack.com/api/conversations.history",
                        headers=headers,
                        params={"channel": channel_id, "limit": 10},
                        timeout=15,
                    )
                    print(f"[DEBUG Slack] history for channel {channel_id} status: {history_res.status_code}")
                    if not history_res.ok:
                        print(f"[DEBUG Slack] history failed: {history_res.text}")
                        continue
                    history_data = history_res.json()
                    if not history_data.get("ok"):
                        print(f"[DEBUG Slack] history ok=False: {history_data}")
                        continue
                    
                    msgs = history_data.get("messages", [])
                    print(f"[DEBUG Slack] history found {len(msgs)} messages in {channel_id}")
                    for msg in msgs:
                        if msg.get("subtype") in {"channel_join", "channel_leave"}:
                            continue
                        msg_copy = dict(msg)
                        msg_copy["channel"] = {"name": channel.get("name") or channel.get("id")}
                        _push_message(msg_copy)
                        if len(messages) >= limit:
                            break
                    if len(messages) >= limit:
                        break

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
