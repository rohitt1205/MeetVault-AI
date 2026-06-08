import os
from urllib.parse import urlencode

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from app.mcp.mcp_manager import MCPManager
from app.mcp.connection_store import MCPConnectionStore
from app.mcp.oauth_state_store import MCPOAuthStateStore
from app.mcp.tool_registry import MCPToolRegistry
from app.mcp import oauth_providers
from app.services.token_diagnostics_service import TokenDiagnosticsService

router = APIRouter(prefix="/mcp", tags=["mcp"])


class JiraConnectRequest(BaseModel):
    jira_email: str
    jira_domain: str
    jira_api_token: str


class SlackConnectRequest(BaseModel):
    slack_token: str


class SalesforceConnectRequest(BaseModel):
    access_token: str
    instance_url: str


class CustomMcpConnectRequest(BaseModel):
    url: str
    token: str | None = None


class NotionGmailConnectRequest(BaseModel):
    email: str
    token: str


class ExecuteToolRequest(BaseModel):
    provider: str
    tool_name: str
    arguments: dict = {}


class GenericConnectRequest(BaseModel):
    provider: str
    provider_user_id: str
    connected: bool


class OAuthContextResponse(BaseModel):
    state_token: str


def get_user_key_from_header(authorization: str | None) -> str:
    if not authorization:
        return "demo"
    try:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return "demo"
        # Parse the active JWT claim
        diagnostics = TokenDiagnosticsService.inspect(token)
        # Handle both Microsoft Graph (upn) and Supabase JWT (email) token schemas
        try:
            parts = token.split(".")
            if len(parts) >= 2:
                import json
                import base64
                segment = parts[1]
                padding = "=" * (-len(segment) % 4)
                decoded = base64.urlsafe_b64decode(f"{segment}{padding}")
                claims = json.loads(decoded.decode("utf-8"))
                upn = claims.get("email") or claims.get("upn") or claims.get("unique_name")
                if upn:
                    return upn.lower().strip()
        except Exception:
            pass

        upn = diagnostics.get("user_principal_name")
        if upn:
            return upn.lower().strip()
    except Exception:
        pass
    return "demo"


def _resolve_oauth_callback_context(state: str | None) -> tuple[str, str | None]:
    if not state:
        return "demo", None

    context = MCPOAuthStateStore.consume(state)
    if context:
        return (
            context.get("user_key") or "demo",
            context.get("supabase_jwt"),
        )

    if "@" in state or "." in state or state == "demo":
        return state, None

    return "demo", None


def resolve_tokens(
    authorization: str | None, x_supabase_token: str | None = None
) -> tuple[str | None, str | None]:
    graph_jwt = None
    supabase_jwt = x_supabase_token

    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            diagnostics = TokenDiagnosticsService.inspect(token)
            if diagnostics.get("is_graph_token"):
                graph_jwt = token
            else:
                if not supabase_jwt:
                    supabase_jwt = token

    return graph_jwt, supabase_jwt


@router.post("/oauth/context", response_model=OAuthContextResponse)
def create_oauth_context(
    authorization: str | None = Header(None),
    x_supabase_token: str | None = Header(None, alias="X-Supabase-Token"),
):
    user_key = get_user_key_from_header(authorization)
    _, supabase_jwt = resolve_tokens(authorization, x_supabase_token)

    if not supabase_jwt:
        raise HTTPException(
            status_code=401,
            detail="Supabase session token is required to start an OAuth redirect.",
        )

    state_token = MCPOAuthStateStore.create(user_key, supabase_jwt)
    return OAuthContextResponse(state_token=state_token)


@router.get("/connections")
def get_connections(
    authorization: str | None = Header(None),
    x_supabase_token: str | None = Header(None, alias="X-Supabase-Token"),
):
    user_key = get_user_key_from_header(authorization)
    graph_jwt, supabase_jwt = resolve_tokens(authorization, x_supabase_token)
    return MCPManager.get_all_connections(
        user_key, graph_jwt=graph_jwt, supabase_jwt=supabase_jwt
    )


@router.post("/connections")
def post_connections(
    req: GenericConnectRequest,
    authorization: str | None = Header(None),
    x_supabase_token: str | None = Header(None, alias="X-Supabase-Token"),
):
    user_key = get_user_key_from_header(authorization)
    graph_jwt, supabase_jwt = resolve_tokens(authorization, x_supabase_token)

    if req.provider in {"outlook", "calendar"} and req.connected and not graph_jwt:
        raise HTTPException(
            status_code=401,
            detail=f"{req.provider.title()} requires a Microsoft Graph access token.",
        )
    
    session = {
        "connected": req.connected,
        "provider_user_id": req.provider_user_id,
        "access_token": graph_jwt,
    }
    
    # Save in store
    MCPConnectionStore.set(req.provider, user_key, session, supabase_jwt)
    
    if req.connected:
        MCPManager.register_provider_tools(req.provider, user_key, supabase_jwt)
    else:
        MCPToolRegistry.clear_tools(req.provider, user_key, supabase_jwt)
        
    return {"connected": req.connected}


@router.get("/github/login")
def github_login(
    user_key: str = Query("demo"),
    state_token: str | None = Query(None),
):
    frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://127.0.0.1:5173").rstrip("/")
    try:
        url = MCPManager.get_github_login_url(state_token or user_key)
        return RedirectResponse(url)
    except HTTPException as exc:
        params = urlencode({
            "github_connected": "false",
            "mcp_error": str(exc.detail),
        })
        return RedirectResponse(url=f"{frontend_origin}/oauth-complete.html?{params}")
    except Exception as exc:
        params = urlencode({
            "github_connected": "false",
            "mcp_error": str(exc),
        })
        return RedirectResponse(url=f"{frontend_origin}/oauth-complete.html?{params}")


@router.get("/github/callback")
def github_callback(
    code: str | None = None,
    state: str = "demo",
    error: str | None = None,
    error_description: str | None = None,
):
    frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://127.0.0.1:5173").rstrip("/")
    if error:
        params = urlencode({
            "github_connected": "false",
            "mcp_error": error_description or error,
        })
        return RedirectResponse(url=f"{frontend_origin}/oauth-complete.html?{params}")

    if not code:
        params = urlencode({
            "github_connected": "false",
            "mcp_error": "GitHub callback did not include an OAuth code.",
        })
        return RedirectResponse(url=f"{frontend_origin}/oauth-complete.html?{params}")

    try:
        user_key, supabase_jwt = _resolve_oauth_callback_context(state)
        MCPManager.connect_github(code, user_key, supabase_jwt=supabase_jwt)
        return RedirectResponse(url=f"{frontend_origin}/oauth-complete.html?github_connected=true")
    except HTTPException as exc:
        params = urlencode({
            "github_connected": "false",
            "mcp_error": str(exc.detail),
        })
        return RedirectResponse(url=f"{frontend_origin}/oauth-complete.html?{params}")
    except Exception as e:
        params = urlencode({
            "github_connected": "false",
            "mcp_error": str(e),
        })
        return RedirectResponse(url=f"{frontend_origin}/oauth-complete.html?{params}")


@router.get("/{provider}/login")
def oauth_login(
    provider: str,
    user_key: str = Query("demo"),
    state_token: str | None = Query(None),
):
    if provider not in {"slack", "salesforce", "notion", "gmail"}:
        raise HTTPException(status_code=404, detail=f"OAuth provider {provider} is not supported.")
    try:
        return RedirectResponse(MCPManager.get_oauth_login_url(provider, state_token or user_key))
    except HTTPException as exc:
        return RedirectResponse(oauth_providers.frontend_redirect(provider, False, str(exc.detail)))
    except Exception as exc:
        return RedirectResponse(oauth_providers.frontend_redirect(provider, False, str(exc)))


@router.get("/{provider}/callback")
def oauth_callback(
    provider: str,
    code: str | None = None,
    state: str = "demo",
    error: str | None = None,
    error_description: str | None = None,
):
    if provider not in {"slack", "salesforce", "notion", "gmail"}:
        raise HTTPException(status_code=404, detail=f"OAuth provider {provider} is not supported.")

    if error:
        return RedirectResponse(oauth_providers.frontend_redirect(provider, False, error_description or error))

    if not code:
        return RedirectResponse(
            oauth_providers.frontend_redirect(provider, False, f"{provider.title()} callback did not include an OAuth code.")
        )

    try:
        user_key, supabase_jwt = _resolve_oauth_callback_context(state)
        MCPManager.connect_oauth_provider(provider, code, user_key, supabase_jwt=supabase_jwt)
        return RedirectResponse(oauth_providers.frontend_redirect(provider, True))
    except HTTPException as exc:
        return RedirectResponse(oauth_providers.frontend_redirect(provider, False, str(exc.detail)))
    except Exception as exc:
        return RedirectResponse(oauth_providers.frontend_redirect(provider, False, str(exc)))


@router.post("/jira/connect")
def connect_jira(
    req: JiraConnectRequest,
    authorization: str | None = Header(None),
    x_supabase_token: str | None = Header(None, alias="X-Supabase-Token"),
):
    user_key = get_user_key_from_header(authorization)
    graph_jwt, supabase_jwt = resolve_tokens(authorization, x_supabase_token)
    result = MCPManager.connect_jira(
        req.jira_email,
        req.jira_domain,
        req.jira_api_token,
        user_key,
        supabase_jwt,
    )
    if not result:
        raise HTTPException(
            status_code=401, detail="Invalid Jira credentials or domain"
        )
    return {"connected": True}


@router.post("/slack/connect")
def connect_slack(
    req: SlackConnectRequest,
    authorization: str | None = Header(None),
    x_supabase_token: str | None = Header(None, alias="X-Supabase-Token"),
):
    user_key = get_user_key_from_header(authorization)
    graph_jwt, supabase_jwt = resolve_tokens(authorization, x_supabase_token)
    result = MCPManager.connect_slack(req.slack_token, user_key, supabase_jwt)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid Slack credentials")
    return {"connected": True}


@router.post("/salesforce/connect")
def connect_salesforce(
    req: SalesforceConnectRequest,
    authorization: str | None = Header(None),
    x_supabase_token: str | None = Header(None, alias="X-Supabase-Token"),
):
    user_key = get_user_key_from_header(authorization)
    graph_jwt, supabase_jwt = resolve_tokens(authorization, x_supabase_token)
    result = MCPManager.connect_salesforce(
        req.access_token, req.instance_url, user_key, supabase_jwt
    )
    if not result:
        raise HTTPException(
            status_code=401, detail="Invalid Salesforce credentials"
        )
    return {"connected": True}


@router.post("/custom/connect")
def connect_custom_mcp(
    req: CustomMcpConnectRequest,
    authorization: str | None = Header(None),
    x_supabase_token: str | None = Header(None, alias="X-Supabase-Token"),
):
    user_key = get_user_key_from_header(authorization)
    graph_jwt, supabase_jwt = resolve_tokens(authorization, x_supabase_token)
    result = MCPManager.connect_custom_mcp(req.url, req.token, user_key, supabase_jwt)
    return result


@router.post("/notion/connect")
def connect_notion_endpoint(
    req: NotionGmailConnectRequest,
    authorization: str | None = Header(None),
    x_supabase_token: str | None = Header(None, alias="X-Supabase-Token"),
):
    user_key = get_user_key_from_header(authorization)
    graph_jwt, supabase_jwt = resolve_tokens(authorization, x_supabase_token)
    MCPManager.connect_notion(req.email, req.token, user_key, supabase_jwt)
    return {"connected": True}


@router.post("/gmail/connect")
def connect_gmail_endpoint(
    req: NotionGmailConnectRequest,
    authorization: str | None = Header(None),
    x_supabase_token: str | None = Header(None, alias="X-Supabase-Token"),
):
    user_key = get_user_key_from_header(authorization)
    graph_jwt, supabase_jwt = resolve_tokens(authorization, x_supabase_token)
    MCPManager.connect_gmail(req.email, req.token, user_key, supabase_jwt)
    return {"connected": True}


@router.get("/tools")
def list_tools(
    authorization: str | None = Header(None),
    x_supabase_token: str | None = Header(None, alias="X-Supabase-Token"),
):
    user_key = get_user_key_from_header(authorization)
    graph_jwt, supabase_jwt = resolve_tokens(authorization, x_supabase_token)
    return MCPToolRegistry.get_active_tools(user_key, supabase_jwt)


@router.post("/tools/execute")
def execute_tool_endpoint(
    req: ExecuteToolRequest,
    authorization: str | None = Header(None),
    x_supabase_token: str | None = Header(None, alias="X-Supabase-Token"),
):
    user_key = get_user_key_from_header(authorization)
    graph_jwt, supabase_jwt = resolve_tokens(authorization, x_supabase_token)

    provider = req.provider
    tool_name = req.tool_name
    args = req.arguments

    # 1. Custom MCP execution
    if provider.startswith("mcp:"):
        url = provider.replace("mcp:", "", 1)
        conn = MCPConnectionStore.get(provider, user_key, supabase_jwt)
        token = conn.get("refresh_token") if conn else None
        from app.mcp import custom_mcp_connector
        return custom_mcp_connector.execute_tool(url, tool_name, args, token)

    # 2. Built-in execution
    # Jira
    if provider == "jira" and tool_name == "get_jira_tickets":
        return MCPManager.get_jira_tickets(user_key, supabase_jwt)

    # GitHub
    if provider == "github":
        session = MCPConnectionStore.get("github", user_key, supabase_jwt)
        token = session.get("access_token") if session else None
        if not token:
            raise HTTPException(status_code=401, detail="GitHub not connected")
        if tool_name == "get_github_issues":
            from app.mcp.github import github_connector
            return github_connector.fetch_assigned_issues(token)
        elif tool_name == "get_github_prs":
            from app.mcp.github import github_connector
            return github_connector.fetch_pull_requests(token)
        elif tool_name == "get_github_reviews":
            from app.mcp.github import github_connector
            return github_connector.fetch_pending_reviews(token)

    # Slack
    if provider == "slack" and tool_name == "get_slack_mentions":
        session = MCPConnectionStore.get("slack", user_key, supabase_jwt)
        token = session.get("access_token") if session else None
        if not token:
            raise HTTPException(status_code=401, detail="Slack not connected")
        from app.mcp.slack import slack_connector
        return slack_connector.fetch_mentions(token)

    # Salesforce
    if provider == "salesforce" and tool_name == "get_salesforce_opportunities":
        session = MCPConnectionStore.get("salesforce", user_key, supabase_jwt)
        token = session.get("access_token") if session else None
        instance = session.get("refresh_token") if session else None
        if not token or not instance:
            raise HTTPException(status_code=401, detail="Salesforce not connected")
        from app.mcp.salesforce import salesforce_connector
        opps = salesforce_connector.fetch_opportunities(token, instance)
        leads = salesforce_connector.fetch_leads(token, instance)
        return {"opportunities": opps, "leads": leads}

    # Outlook
    if provider == "outlook" and tool_name == "get_outlook_emails":
        if not graph_jwt:
            raise HTTPException(status_code=401, detail="Graph JWT missing for Outlook")
        from app.mcp.outlook import outlook_connector
        unread = outlook_connector.fetch_unread_important_emails(graph_jwt)
        flagged = outlook_connector.fetch_flagged_emails(graph_jwt)
        action = outlook_connector.fetch_action_required_emails(graph_jwt)
        return {"unread_important": unread, "flagged": flagged, "action_required": action}

    # Calendar
    if provider == "calendar" and tool_name == "get_calendar_events":
        if not graph_jwt:
            raise HTTPException(status_code=401, detail="Graph JWT missing for Calendar")
        from app.mcp.calendar import calendar_connector
        upcoming = calendar_connector.fetch_upcoming_meetings(graph_jwt)
        deadlines = calendar_connector.fetch_deadlines(graph_jwt)
        return {"upcoming_meetings": upcoming, "deadlines": deadlines}

    # Notion
    if provider == "notion":
        session = MCPConnectionStore.get("notion", user_key, supabase_jwt)
        token = session.get("access_token") if session else None
        if not token:
            raise HTTPException(status_code=401, detail="Notion not connected")
        from app.mcp import notion_connector
        return notion_connector.fetch_recent_pages(token)

    # Gmail
    if provider == "gmail":
        session = MCPConnectionStore.get("gmail", user_key, supabase_jwt)
        token = session.get("access_token") if session else None
        if not token:
            raise HTTPException(status_code=401, detail="Gmail not connected")
        from app.mcp import gmail_connector
        return gmail_connector.fetch_unread_messages(token)

    raise HTTPException(status_code=404, detail=f"Tool {tool_name} for provider {provider} not found.")


@router.delete("/disconnect/{provider}")
def disconnect_provider(
    provider: str,
    authorization: str | None = Header(None),
    x_supabase_token: str | None = Header(None, alias="X-Supabase-Token"),
):
    user_key = get_user_key_from_header(authorization)
    graph_jwt, supabase_jwt = resolve_tokens(authorization, x_supabase_token)
    result = MCPManager.disconnect_provider(provider, user_key, supabase_jwt)
    if not result:
        raise HTTPException(
            status_code=400, detail=f"Failed to disconnect {provider}"
        )
    return {"disconnected": True}
