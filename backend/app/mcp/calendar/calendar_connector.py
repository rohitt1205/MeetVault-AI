from datetime import datetime, timedelta
from app.services.graph_client import GraphClient
from app.services.token_diagnostics_service import TokenDiagnosticsService
from app.mcp.connection_store import MCPConnectionStore


def get_calendar_status(
    user_key: str = "demo",
    graph_jwt: str | None = None,
    supabase_jwt: str | None = None,
):
    db_conn = MCPConnectionStore.get("calendar", user_key, supabase_jwt=supabase_jwt)
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


def fetch_upcoming_meetings(graph_jwt: str, limit: int = 5) -> list[dict]:
    """Fetches upcoming meetings for the next 7 days using Microsoft Graph calendarView."""
    try:
        now = datetime.utcnow()
        end_time = now + timedelta(days=7)
        
        start_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        endpoint = (
            f"/me/calendarView?startDateTime={start_str}&endDateTime={end_str}&"
            f"$select=subject,start,end,organizer&$top={limit}&$orderby=start/dateTime"
        )
        res = GraphClient.get(endpoint, graph_jwt)
        events = res.get("value", [])
        return [
            {
                "subject": ev.get("subject", "No Subject"),
                "organizer": ev.get("organizer", {}).get("emailAddress", {}).get("name", "Unknown"),
                "start": ev.get("start", {}).get("dateTime"),
                "end": ev.get("end", {}).get("dateTime"),
            }
            for ev in events
        ]
    except Exception as e:
        print(f"Error fetching upcoming meetings: {e}")
        return []


def fetch_recent_meetings(graph_jwt: str, limit: int = 5) -> list[dict]:
    """Fetches recent/past meetings from the last 14 days using Microsoft Graph calendarView."""
    try:
        now = datetime.utcnow()
        start_time = now - timedelta(days=14)
        
        start_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        endpoint = (
            f"/me/calendarView?startDateTime={start_str}&endDateTime={end_str}&"
            f"$select=subject,start,end,organizer&$top={limit}&$orderby=start/dateTime desc"
        )
        res = GraphClient.get(endpoint, graph_jwt)
        events = res.get("value", [])
        return [
            {
                "subject": ev.get("subject", "No Subject"),
                "organizer": ev.get("organizer", {}).get("emailAddress", {}).get("name", "Unknown"),
                "start": ev.get("start", {}).get("dateTime"),
                "end": ev.get("end", {}).get("dateTime"),
            }
            for ev in events
        ]
    except Exception as e:
        print(f"Error fetching recent meetings: {e}")
        return []


def fetch_deadlines(graph_jwt: str, limit: int = 5) -> list[dict]:
    """Scans calendar events for subjects containing keywords indicating project/sprint deadlines."""
    try:
        now = datetime.utcnow()
        end_time = now + timedelta(days=14)
        
        start_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        endpoint = (
            f"/me/calendarView?startDateTime={start_str}&endDateTime={end_str}&"
            f"$select=subject,start,end&$top=50"
        )
        res = GraphClient.get(endpoint, graph_jwt)
        events = res.get("value", [])

        deadline_keywords = {"deadline", "due", "deliverable", "sprint end", "release", "milestone"}
        deadlines = []

        for ev in events:
            subject = (ev.get("subject") or "").lower()
            if any(kw in subject for kw in deadline_keywords):
                deadlines.append({
                    "subject": ev.get("subject", "Deadline"),
                    "due_date": ev.get("start", {}).get("dateTime"),
                })
                if len(deadlines) >= limit:
                    break

        return deadlines
    except Exception as e:
        print(f"Error fetching deadlines: {e}")
        return []
