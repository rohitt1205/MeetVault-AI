import requests


def _headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "MeetVault-AI",
    }


def fetch_assigned_issues(token: str, limit: int = 5) -> list[dict]:
    """Fetches open GitHub issues assigned to the authenticated user."""
    try:
        user_response = requests.get(
            "https://api.github.com/user",
            headers=_headers(token),
            timeout=10,
        )
        if not user_response.ok:
            return []
        username = user_response.json().get("login")
        if not username:
            return []

        url = "https://api.github.com/search/issues"
        params = {
            "q": f"is:issue is:open assignee:{username}",
            "per_page": limit,
        }
        response = requests.get(url, headers=_headers(token), params=params, timeout=15)
        if not response.ok:
            return []
        issues = response.json().get("items", [])
        return [
            {
                "issue_id": issue.get("number"),
                "title": issue.get("title"),
                "repo": (issue.get("repository_url") or "").rstrip("/").split("/")[-1] or "Unknown Repo",
                "url": issue.get("html_url"),
                "status": issue.get("state"),
            }
            for issue in issues
            if "pull_request" not in issue  # Exclude pull requests
        ]
    except Exception as e:
        print(f"Error fetching GitHub issues: {e}")
        return []


def fetch_pull_requests(token: str, limit: int = 5) -> list[dict]:
    """Fetches open GitHub PRs created by or assigned to the authenticated user."""
    # We can fetch via search API for better control
    url = "https://api.github.com/search/issues"
    # Query for open pull requests assigned to or authored by the user
    # First get user info to know their username
    user_url = "https://api.github.com/user"
    try:
        user_res = requests.get(user_url, headers=_headers(token), timeout=10)
        if not user_res.ok:
            return []
        username = user_res.json().get("login")

        q = f"is:pr state:open author:{username}"
        params = {"q": q, "per_page": limit}
        response = requests.get(url, headers=_headers(token), params=params, timeout=15)
        if not response.ok:
            return []
        items = response.json().get("items", [])
        return [
            {
                "pr_id": pr.get("number"),
                "title": pr.get("title"),
                "url": pr.get("html_url"),
                "status": pr.get("state"),
            }
            for pr in items
        ]
    except Exception as e:
        print(f"Error fetching GitHub pull requests: {e}")
        return []


def fetch_pending_reviews(token: str, limit: int = 5) -> list[dict]:
    """Fetches open pull requests awaiting review by the authenticated user."""
    url = "https://api.github.com/search/issues"
    user_url = "https://api.github.com/user"
    try:
        user_res = requests.get(user_url, headers=_headers(token), timeout=10)
        if not user_res.ok:
            return []
        username = user_res.json().get("login")

        q = f"is:pr state:open review-requested:{username}"
        params = {"q": q, "per_page": limit}
        response = requests.get(url, headers=_headers(token), params=params, timeout=15)
        if not response.ok:
            return []
        items = response.json().get("items", [])
        return [
            {
                "pr_id": pr.get("number"),
                "title": pr.get("title"),
                "url": pr.get("html_url"),
            }
            for pr in items
        ]
    except Exception as e:
        print(f"Error fetching pending PR reviews: {e}")
        return []


def fetch_repositories(token: str, limit: int = 5) -> list[dict]:
    """Fetches repositories the user is contributing to or owns."""
    url = "https://api.github.com/user/repos"
    params = {
        "sort": "updated",
        "direction": "desc",
        "per_page": limit,
    }
    try:
        response = requests.get(url, headers=_headers(token), params=params, timeout=15)
        if not response.ok:
            return []
        repos = response.json()
        return [
            {
                "name": repo.get("name"),
                "full_name": repo.get("full_name"),
                "url": repo.get("html_url"),
            }
            for repo in repos
        ]
    except Exception as e:
        print(f"Error fetching repositories: {e}")
        return []
