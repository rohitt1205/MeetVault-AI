import requests
from fastapi import HTTPException


NOTION_VERSION = "2022-06-28"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def fetch_recent_pages(token: str, limit: int = 10) -> list[dict]:
    try:
        response = requests.post(
            "https://api.notion.com/v1/search",
            headers=_headers(token),
            json={
                "filter": {"value": "page", "property": "object"},
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
                "page_size": limit,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Notion search request failed: {exc}") from exc

    if not response.ok:
        raise HTTPException(status_code=502, detail=f"Notion search failed: {response.text}")

    pages = response.json().get("results", [])
    return [
        {
            "page_id": page.get("id"),
            "title": _page_title(page),
            "url": page.get("url"),
            "last_edited": page.get("last_edited_time"),
        }
        for page in pages
    ]


def _page_title(page: dict) -> str:
    properties = page.get("properties", {})
    for value in properties.values():
        if value.get("type") == "title":
            parts = value.get("title") or []
            title = "".join(part.get("plain_text", "") for part in parts).strip()
            if title:
                return title
    return "Untitled"
