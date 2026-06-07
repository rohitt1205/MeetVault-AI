import re

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
    user_key: str,
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
            raise HTTPException(
                status_code=401,
                detail=f"Jira credential verification failed: {response.text}",
            )
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
    token: str,
    account_id: str | None = None,
    display_name: str | None = None,
):
    """
    Fetch open Jira issues first, then filter locally against the current user's
    real identity. This avoids brittle JQL assumptions while still returning only
    items assigned to the user.
    """

    def _normalize(value: str | None) -> str:
        return re.sub(r"[^a-z0-9]+", "", (value or "").lower())

    normalized_email = _normalize(email)
    email_local = _normalize((email or "").split("@", 1)[0])
    normalized_display_name = _normalize(display_name)

    def _matches_assignee(issue: dict) -> bool:
        assignee = (issue.get("fields") or {}).get("assignee") or {}
        if not assignee:
            return False

        if account_id and assignee.get("accountId") == account_id:
            return True

        assignee_email = _normalize(assignee.get("emailAddress"))
        if assignee_email and assignee_email == normalized_email:
            return True

        assignee_name = _normalize(assignee.get("displayName"))
        if assignee_name and (
            assignee_name == normalized_display_name
            or assignee_name == email_local
            or email_local in assignee_name
            or normalized_display_name in assignee_name
            or assignee_name in normalized_display_name
        ):
            return True

        return False

    def _format_issue(issue: dict) -> dict:
        fields = issue.get("fields") or {}
        return {
            "ticket_id": issue.get("key"),
            "summary": fields.get("summary"),
            "status": (fields.get("status") or {}).get("name", "Unknown"),
            "due_date": fields.get("duedate"),
            "assignee": (fields.get("assignee") or {}).get("displayName"),
        }

    url = f"https://{domain}.atlassian.net/rest/api/3/search"
    current_user_params = {
        "jql": "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC",
        "maxResults": 50,
        "startAt": 0,
        "fields": "summary,status,assignee,duedate,project",
    }

    try:
        response = requests.get(
            url,
            params=current_user_params,
            auth=HTTPBasicAuth(email, token),
            headers={"Accept": "application/json"},
            timeout=15,
        )
        print(f"[DEBUG Jira] current_user search status: {response.status_code}")
        if response.ok:
            data = response.json()
            direct_issues = data.get("issues", [])
            print(f"[DEBUG Jira] current_user search found {len(direct_issues)} issues")
            if direct_issues:
                res = [_format_issue(issue) for issue in direct_issues]
                print(f"[DEBUG Jira] returning {len(res)} direct issues")
                return res
        else:
            print(f"[DEBUG Jira] current_user search failed: {response.text}")
    except requests.RequestException as exc:
        print(f"[DEBUG Jira] current_user search exception: {exc}")

    fallback_params = {
        "jql": "statusCategory != Done ORDER BY updated DESC",
        "maxResults": 50,
        "startAt": 0,
        "fields": "summary,status,assignee,duedate,project",
    }

    issues: list[dict] = []
    total = None

    try:
        while True:
            response = requests.get(
                url,
                params=fallback_params,
                auth=HTTPBasicAuth(email, token),
                headers={"Accept": "application/json"},
                timeout=15,
            )
            print(f"[DEBUG Jira] fallback search status: {response.status_code}")
            if not response.ok:
                print(f"[DEBUG Jira] fallback search failed: {response.text}")
                return []

            data = response.json()
            page_issues = data.get("issues", [])
            print(f"[DEBUG Jira] fallback search returned {len(page_issues)} issues on this page")
            issues.extend(page_issues)
            total = data.get("total", total)

            if not page_issues or len(issues) >= 100:
                break

            fallback_params["startAt"] = fallback_params["startAt"] + len(page_issues)
            if total is not None and fallback_params["startAt"] >= total:
                break
    except requests.RequestException as exc:
        print(f"[DEBUG Jira] fallback search exception: {exc}")
        return []

    final_res = [_format_issue(issue) for issue in issues if _matches_assignee(issue)]
    print(f"[DEBUG Jira] returning {len(final_res)} filtered issues from fallback out of {len(issues)} total fetched")
    return final_res
