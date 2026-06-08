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
        raise HTTPException(
            status_code=502,
            detail=f"Slack authentication failed: {exc}",
        ) from exc


def fetch_mentions(token: str, limit: int = 5) -> list[dict]:
    """Fetches recent Slack messages relevant to the current user."""
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
        
        messages = []
        seen = set()
        user_cache: dict[str, str] = {}
        permission_errors = set()

        def _api_get(url: str, params: dict | None = None) -> dict:
            res = requests.get(url, headers=headers, params=params or {}, timeout=15)
            try:
                data = res.json()
            except ValueError:
                data = {"ok": False, "error": res.text}
            if not res.ok:
                data.setdefault("ok", False)
                data.setdefault("error", res.text)
            return data

        def _api_post(url: str, payload: dict | None = None) -> dict:
            res = requests.post(url, headers=headers, json=payload or {}, timeout=15)
            try:
                data = res.json()
            except ValueError:
                data = {"ok": False, "error": res.text}
            if not res.ok:
                data.setdefault("ok", False)
                data.setdefault("error", res.text)
            return data

        def _display_user(slack_user_id: str | None) -> str:
            if not slack_user_id:
                return "Someone"
            if slack_user_id in user_cache:
                return user_cache[slack_user_id]

            data = _api_get("https://slack.com/api/users.info", {"user": slack_user_id})
            profile = ((data.get("user") or {}).get("profile") or {}) if data.get("ok") else {}
            name = (
                profile.get("display_name")
                or profile.get("real_name")
                or (data.get("user") or {}).get("name")
                or slack_user_id
            )
            user_cache[slack_user_id] = name
            return name

        def _push_message(msg: dict):
            key = (msg.get("channel", {}).get("name"), msg.get("ts"), msg.get("text"))
            if key in seen:
                return
            seen.add(key)
            messages.append(msg)

        conversations_url = "https://slack.com/api/conversations.list"
        channel_groups = [
            "public_channel",
            "private_channel",
            "im,mpim",
        ]

        for channel_types in channel_groups:
            if len(messages) >= limit:
                break

            channels_data = _api_get(
                conversations_url,
                {
                    "types": channel_types,
                    "limit": 100,
                    "exclude_archived": True,
                },
            )
            print(
                f"[DEBUG Slack] conversations.list types={channel_types} ok={channels_data.get('ok')} "
                f"error={channels_data.get('error')} count={len(channels_data.get('channels', []))}"
            )
            if not channels_data.get("ok"):
                if channels_data.get("error"):
                    permission_errors.add(channels_data.get("error"))
                continue

            for channel in channels_data.get("channels", []):
                if len(messages) >= limit:
                    break

                channel_id = channel.get("id")
                if not channel_id:
                    continue

                channel_name = (
                    channel.get("name")
                    or channel.get("user")
                    or channel_id
                )
                is_public = bool(channel.get("is_channel")) and not channel.get("is_group")
                if is_public and not channel.get("is_member"):
                    join_data = _api_post(
                        "https://slack.com/api/conversations.join",
                        {"channel": channel_id},
                    )
                    print(
                        f"[DEBUG Slack] conversations.join channel={channel_id} ok={join_data.get('ok')} "
                        f"error={join_data.get('error')}"
                    )
                    if join_data.get("ok"):
                        channel = join_data.get("channel") or channel
                    elif join_data.get("error") not in {"already_in_channel"}:
                        if join_data.get("error"):
                            permission_errors.add(join_data.get("error"))
                        continue

                history_data = _api_get(
                    "https://slack.com/api/conversations.history",
                    {"channel": channel_id, "limit": 20},
                )
                print(
                    f"[DEBUG Slack] conversations.history channel={channel_id} ok={history_data.get('ok')} "
                    f"error={history_data.get('error')} count={len(history_data.get('messages', []))}"
                )
                if not history_data.get("ok"):
                    if history_data.get("error"):
                        permission_errors.add(history_data.get("error"))
                    continue

                for msg in history_data.get("messages", []):
                    if msg.get("subtype") in {"channel_join", "channel_leave"}:
                        continue

                    text = msg.get("text") or ""
                    # Prefer direct mentions, but keep recent visible messages as useful context.
                    mentions_current_user = bool(user_id and f"<@{user_id}>" in text)
                    if not mentions_current_user and len(messages) >= max(1, limit // 2):
                        continue

                    msg_copy = dict(msg)
                    msg_copy["channel"] = {"name": channel_name}
                    _push_message(msg_copy)
                    if len(messages) >= limit:
                        break

        if not messages and permission_errors:
            detail = (
                "Slack is connected, but this token cannot read the workspace messages. "
                "Invite the Slack app/bot to the channels you want indexed, or reconnect Slack "
                "with message-history scopes such as channels:history, groups:history, im:history, "
                "and mpim:history."
            )
            print(f"[DEBUG Slack] no readable messages due to Slack errors: {sorted(permission_errors)}")
            raise HTTPException(status_code=403, detail=detail)

        return [
            {
                "channel": msg.get("channel", {}).get("name", "direct-message"),
                "user": msg.get("username") or _display_user(msg.get("user")),
                "text": msg.get("text", ""),
                "ts": msg.get("ts"),
            }
            for msg in messages
        ]
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching Slack mentions: {e}")
        return []
