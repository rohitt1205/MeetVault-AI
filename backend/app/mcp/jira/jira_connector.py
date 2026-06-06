import requests

from fastapi import HTTPException
from requests.auth import HTTPBasicAuth


def _clean_domain(domain: str) -> str:
    clean_domain = (
        (domain or "")
        .strip()
        .replace("https://", "")
        .replace("http://", "")
        .replace(".atlassian.net", "")
        .strip("/")
    )
    if not clean_domain:
        raise HTTPException(status_code=400, detail="Jira domain is required.")
    return clean_domain


def verify_and_connect(
    email: str,
    domain: str,
    api_token: str,
    user_key: str
):
    clean_domain = _clean_domain(domain)

    url = f"https://{clean_domain}.atlassian.net/rest/api/3/myself"

    try:
        response = requests.get(
            url,
            auth=HTTPBasicAuth(email.strip(), api_token),
            headers={"Accept": "application/json"},
            timeout=15,
        )
        if not response.ok:
            raise HTTPException(status_code=401, detail=f"Jira credential verification failed: {response.text}")
        data = response.json()
        return {
            "connected": True,
            "display_name": data.get("displayName") or "Jira User",
            "email": email.strip(),
            "domain": clean_domain,
            "account_id": data.get("accountId"),
            "token": api_token,
        }
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Jira credential verification failed: {exc}",
        ) from exc

def fetch_tickets(
    email: str,
    domain: str,
    token: str
):
    url = f"https://{domain}.atlassian.net/rest/api/3/search"

    jql = (
        "assignee = currentUser() "
        "AND statusCategory != Done "
        "ORDER BY updated DESC"
    )

    params = {
        "jql": jql,
        "maxResults": 5,
        "fields": "summary,status",
    }

    try:
        response = requests.get(
            url,
            params=params,
            auth=HTTPBasicAuth(email, token),
            headers={"Accept": "application/json"},
            timeout=15,
        )
    except requests.RequestException:
        return []

    if not response.ok:
        return []

    data = response.json()
    issues = data.get("issues", [])

    return [
        {
            "ticket_id": issue["key"],
            "summary": issue["fields"]["summary"],
            "status": issue["fields"].get("status", {}).get("name", "Unknown")
        }
        for issue in issues
    ]
