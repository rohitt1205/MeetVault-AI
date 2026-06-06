from app.services.graph_client import GraphClient
from app.services.token_diagnostics_service import TokenDiagnosticsService
from app.mcp.connection_store import MCPConnectionStore


def get_outlook_status(
    user_key: str = "demo",
    graph_jwt: str | None = None,
    supabase_jwt: str | None = None,
):
    # Check if there is a disconnect record
    db_conn = MCPConnectionStore.get("outlook", user_key, supabase_jwt=supabase_jwt)
    if db_conn and not db_conn.get("connected", True):
        return {
            "connected": False,
            "provider": "microsoft",
            "email": db_conn.get("provider_user_id"),
            "scopes": [],
        }

    diagnostics = (
        TokenDiagnosticsService.inspect(graph_jwt) if graph_jwt else {}
    )
    is_connected = bool(diagnostics.get("is_graph_token"))
    email = diagnostics.get("user_principal_name") or (
        user_key if user_key != "demo" else None
    )

    return {
        "connected": is_connected,
        "provider": "microsoft",
        "email": email,
        "scopes": diagnostics.get("scopes", []),
    }


def fetch_flagged_emails(graph_jwt: str, limit: int = 5) -> list[dict]:
    """Fetches flagged emails from Microsoft Graph."""
    try:
        endpoint = (
            f"/me/messages?$filter=flag/flagStatus eq 'flagged'&"
            f"$select=subject,sender,receivedDateTime,bodyPreview&$top={limit}"
        )
        res = GraphClient.get(endpoint, graph_jwt)
        messages = res.get("value", [])
        return [
            {
                "subject": msg.get("subject", "No Subject"),
                "from": msg.get("sender", {}).get("emailAddress", {}).get("name", "Unknown"),
                "date": msg.get("receivedDateTime"),
                "preview": msg.get("bodyPreview", ""),
            }
            for msg in messages
        ]
    except Exception as e:
        print(f"Error fetching flagged emails: {e}")
        return []


def fetch_unread_important_emails(graph_jwt: str, limit: int = 5) -> list[dict]:
    """Fetches unread high-importance emails from Microsoft Graph."""
    try:
        endpoint = (
            f"/me/messages?$filter=isRead eq false and importance eq 'high'&"
            f"$select=subject,sender,receivedDateTime,bodyPreview&$top={limit}"
        )
        res = GraphClient.get(endpoint, graph_jwt)
        messages = res.get("value", [])
        return [
            {
                "subject": msg.get("subject", "No Subject"),
                "from": msg.get("sender", {}).get("emailAddress", {}).get("name", "Unknown"),
                "date": msg.get("receivedDateTime"),
                "preview": msg.get("bodyPreview", ""),
            }
            for msg in messages
        ]
    except Exception as e:
        print(f"Error fetching unread important emails: {e}")
        return []


def fetch_action_required_emails(graph_jwt: str, limit: int = 5) -> list[dict]:
    """Fetches emails requiring action by scanning recent messages for keywords or flag status."""
    try:
        # Fetch recent 20 messages and filter in-memory for relevance/action items
        endpoint = (
            f"/me/messages?$select=subject,sender,receivedDateTime,bodyPreview,flag&$top=20"
        )
        res = GraphClient.get(endpoint, graph_jwt)
        messages = res.get("value", [])

        action_keywords = {"action required", "please review", "urgent", "todo", "blocker", "due"}
        action_emails = []

        for msg in messages:
            subject = (msg.get("subject") or "").lower()
            preview = (msg.get("bodyPreview") or "").lower()
            is_flagged = msg.get("flag", {}).get("flagStatus") == "flagged"

            has_keyword = any(kw in subject or kw in preview for kw in action_keywords)

            if is_flagged or has_keyword:
                action_emails.append({
                    "subject": msg.get("subject", "No Subject"),
                    "from": msg.get("sender", {}).get("emailAddress", {}).get("name", "Unknown"),
                    "date": msg.get("receivedDateTime"),
                    "preview": msg.get("bodyPreview", ""),
                })
                if len(action_emails) >= limit:
                    break

        return action_emails
    except Exception as e:
        print(f"Error fetching action required emails: {e}")
        return []
