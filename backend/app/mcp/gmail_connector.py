import requests
from fastapi import HTTPException


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def fetch_unread_messages(token: str, limit: int = 10) -> list[dict]:
    try:
        list_response = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers=_headers(token),
            params={"q": "is:unread", "maxResults": limit},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Gmail list request failed: {exc}") from exc

    if not list_response.ok:
        raise HTTPException(status_code=502, detail=f"Gmail list failed: {list_response.text}")

    messages = list_response.json().get("messages", [])
    results = []
    for message in messages:
        detail = _fetch_message(token, message.get("id"))
        headers = {
            item.get("name", "").lower(): item.get("value")
            for item in detail.get("payload", {}).get("headers", [])
        }
        results.append(
            {
                "id": detail.get("id"),
                "sender": headers.get("from"),
                "subject": headers.get("subject"),
                "date": headers.get("date"),
                "snippet": detail.get("snippet"),
            }
        )
    return results


def _fetch_message(token: str, message_id: str | None) -> dict:
    if not message_id:
        return {}

    try:
        response = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
            headers=_headers(token),
            params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Gmail message request failed: {exc}") from exc

    if not response.ok:
        raise HTTPException(status_code=502, detail=f"Gmail message fetch failed: {response.text}")

    return response.json()
