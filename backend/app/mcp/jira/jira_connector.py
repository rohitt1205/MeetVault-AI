import requests

from requests.auth import HTTPBasicAuth

def verify_and_connect(
    email: str,
    domain: str,
    api_token: str,
    user_key: str
):
    clean_domain = (
        domain
        .replace("https://", "")
        .replace("http://", "")
        .replace(".atlassian.net", "")
        .replace("/", "")
    )

    url = f"https://{clean_domain}.atlassian.net/rest/api/3/myself"

    response = requests.get(
        url,
        auth=HTTPBasicAuth(email, api_token),
        timeout=15
    )

    if not response.ok:
        print(response.text)
        return None

    data = response.json()

    return {
        "connected": True,
        "display_name": data.get("displayName"),
        "email": email,
        "domain": clean_domain,
        "token": api_token
    }

def fetch_tickets(
    email: str,
    domain: str,
    token: str
):
    url = f"https://{domain}.atlassian.net/rest/api/3/search"

    jql = (
        f'assignee = "{email}" '
        f'AND statusCategory != Done '
        f'ORDER BY updated DESC'
    )

    params = {
        "jql": jql,
        "maxResults": 5,
        "fields": "summary,status"
    }

    response = requests.get(
        url,
        params=params,
        auth=HTTPBasicAuth(email, token),
        timeout=15
    )

    if not response.ok:
        print(response.text)
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
