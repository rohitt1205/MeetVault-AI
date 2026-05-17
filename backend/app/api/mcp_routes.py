import os
from urllib.parse import urlencode

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from app.mcp.mcp_manager import MCPManager
from app.services.token_diagnostics_service import TokenDiagnosticsService

router = APIRouter(prefix="/mcp", tags=["mcp"])

class JiraConnectRequest(BaseModel):
    jira_email: str
    jira_domain: str
    jira_api_token: str

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

@router.get("/connections")
def get_connections(authorization: str = Header(None)):
    user_key = get_user_key_from_header(authorization)
    token = None
    if authorization:
        scheme, _, candidate = authorization.partition(" ")
        if scheme.lower() == "bearer" and candidate:
            token = candidate
    return MCPManager.get_all_connections(user_key, access_token=token)

@router.get("/github/login")
def github_login(user_key: str = Query("demo")):
    frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://127.0.0.1:5173").rstrip("/")
    try:
        url = MCPManager.get_github_login_url(user_key)
        return RedirectResponse(url)
    except HTTPException as exc:
        params = urlencode({
            "github_connected": "false",
            "mcp_error": str(exc.detail),
        })
        return RedirectResponse(url=f"{frontend_origin}/?{params}")
    except Exception as exc:
        params = urlencode({
            "github_connected": "false",
            "mcp_error": str(exc),
        })
        return RedirectResponse(url=f"{frontend_origin}/?{params}")

@router.get("/github/callback")
def github_callback(code: str | None = None, state: str = "demo", error: str | None = None, error_description: str | None = None):
    frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://127.0.0.1:5173").rstrip("/")
    if error:
        params = urlencode({
            "github_connected": "false",
            "mcp_error": error_description or error,
        })
        return RedirectResponse(url=f"{frontend_origin}/?{params}")

    if not code:
        params = urlencode({
            "github_connected": "false",
            "mcp_error": "GitHub callback did not include an OAuth code.",
        })
        return RedirectResponse(url=f"{frontend_origin}/?{params}")

    try:
        MCPManager.connect_github(code, state)
        return RedirectResponse(url=f"{frontend_origin}/?github_connected=true")
    except HTTPException as exc:
        params = urlencode({
            "github_connected": "false",
            "mcp_error": str(exc.detail),
        })
        return RedirectResponse(url=f"{frontend_origin}/?{params}")
    except Exception as e:
        params = urlencode({
            "github_connected": "false",
            "mcp_error": str(e),
        })
        return RedirectResponse(url=f"{frontend_origin}/?{params}")

@router.post("/jira/connect")
def connect_jira(req: JiraConnectRequest, authorization: str = Header(None)):
    user_key = get_user_key_from_header(authorization)
    result = MCPManager.connect_jira(req.jira_email, req.jira_domain, req.jira_api_token, user_key)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid Jira credentials or domain")
    return {"connected": True}

@router.get("/jira/my-tasks")
def get_jira_tasks(authorization: str = Header(None)):
    user_key = get_user_key_from_header(authorization)
    tasks = MCPManager.get_jira_tickets(user_key)
    return tasks
