import json
import os
import base64
import requests
from pathlib import Path
from threading import Lock
from typing import Any

MCP_CONNECTION_STORE_PATH = Path(
    os.getenv("MCP_CONNECTION_STORE_PATH", "./mcp_connections.json")
)

# Load Supabase URL & Key from environment
SUPABASE_URL = os.getenv("VITE_SUPABASE_URL") or os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("VITE_SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_KEY")


class MCPConnectionStore:
    _lock = Lock()

    @staticmethod
    def _is_mock_session(session: dict | None) -> bool:
        if not session:
            return False

        token = session.get("access_token") or session.get("token")
        provider_user_id = session.get("provider_user_id") or session.get("username") or session.get("email")

        if isinstance(token, str) and token.startswith(("oauth-mock-token", "mock-")):
            return True
        if isinstance(provider_user_id, str) and provider_user_id.startswith(("jira-mock", "salesforce-mock", "U123456")):
            return True
        return False

    @staticmethod
    def _read() -> dict:
        if not MCP_CONNECTION_STORE_PATH.exists():
            return {}

        try:
            return json.loads(MCP_CONNECTION_STORE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _write(payload: dict) -> None:
        MCP_CONNECTION_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        MCP_CONNECTION_STORE_PATH.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _extract_user_id(supabase_jwt: str) -> str | None:
        try:
            parts = supabase_jwt.split(".")
            if len(parts) >= 2:
                segment = parts[1]
                padding = "=" * (-len(segment) % 4)
                decoded = base64.urlsafe_b64decode(f"{segment}{padding}")
                claims = json.loads(decoded.decode("utf-8"))
                return claims.get("sub")
        except Exception:
            pass
        return None

    @staticmethod
    def _get_db_headers(supabase_jwt: str) -> dict:
        return {
            "apikey": SUPABASE_KEY or "",
            "Authorization": f"Bearer {supabase_jwt}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    @staticmethod
    def get_from_db(provider: str, supabase_jwt: str) -> dict | None:
        if not SUPABASE_URL or not supabase_jwt:
            return None

        user_id = MCPConnectionStore._extract_user_id(supabase_jwt)
        if not user_id:
            return None

        url = f"{SUPABASE_URL}/rest/v1/mcp_connections?user_id=eq.{user_id}&provider=eq.{provider}"
        headers = MCPConnectionStore._get_db_headers(supabase_jwt)
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                rows = response.json()
                if rows:
                    row = rows[0]
                    connected = row.get("connected", False)
                    if not connected:
                        return {
                            "connected": False,
                            "username": None,
                            "email": None,
                            "domain": None,
                        }

                    session = {
                        "connected": True,
                        "provider_user_id": row.get("provider_user_id"),
                        "access_token": row.get("access_token"),
                        "refresh_token": row.get("refresh_token"),
                        "expires_at": row.get("expires_at"),
                    }
                    if provider == "github":
                        session["username"] = row.get("provider_user_id")
                    elif provider == "jira":
                        session["email"] = row.get("provider_user_id")
                        session["token"] = row.get("access_token")
                        session["domain"] = row.get("refresh_token")
                    elif provider in ("slack", "salesforce", "outlook", "calendar"):
                        session["email"] = row.get("provider_user_id")
                        session["token"] = row.get("access_token")
                    if MCPConnectionStore._is_mock_session(session):
                        return {
                            "connected": False,
                            "username": None,
                            "email": None,
                            "domain": None,
                        }
                    return session
        except Exception as e:
            print(f"Error fetching from Supabase DB: {e}")
        return None

    @staticmethod
    def set_in_db(provider: str, supabase_jwt: str, session: dict) -> dict | None:
        if not SUPABASE_URL or not supabase_jwt:
            return None

        user_id = MCPConnectionStore._extract_user_id(supabase_jwt)
        if not user_id:
            return None

        url = f"{SUPABASE_URL}/rest/v1/mcp_connections?on_conflict=user_id,provider"
        headers = MCPConnectionStore._get_db_headers(supabase_jwt)

        provider_user_id = (
            session.get("username")
            or session.get("email")
            or session.get("display_name")
            or session.get("provider_user_id")
        )
        access_token = session.get("access_token") or session.get("token")
        refresh_token = session.get("refresh_token") or session.get("domain")

        payload = {
            "user_id": user_id,
            "provider": provider,
            "provider_user_id": provider_user_id,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": session.get("expires_at"),
            "connected": session.get("connected", True),
            "updated_at": "now()",
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code in (200, 201):
                rows = response.json()
                return rows[0] if rows else session
        except Exception as e:
            print(f"Error setting in Supabase DB: {e}")
        return None

    @staticmethod
    def disconnect_in_db(provider: str, supabase_jwt: str) -> bool:
        if not SUPABASE_URL or not supabase_jwt:
            return False

        user_id = MCPConnectionStore._extract_user_id(supabase_jwt)
        if not user_id:
            return False

        url = f"{SUPABASE_URL}/rest/v1/mcp_connections?user_id=eq.{user_id}&provider=eq.{provider}"
        headers = MCPConnectionStore._get_db_headers(supabase_jwt)
        payload = {
            "access_token": None,
            "refresh_token": None,
            "expires_at": None,
            "connected": False,
            "updated_at": "now()",
        }

        try:
            response = requests.patch(url, json=payload, headers=headers, timeout=10)
            return response.status_code in (200, 204)
        except Exception as e:
            print(f"Error disconnecting in Supabase DB: {e}")
        return False

    @staticmethod
    def get_all_user_connections(user_key: str, supabase_jwt: str | None = None) -> list[dict]:
        if supabase_jwt and SUPABASE_URL:
            user_id = MCPConnectionStore._extract_user_id(supabase_jwt)
            if user_id:
                url = f"{SUPABASE_URL}/rest/v1/mcp_connections?user_id=eq.{user_id}&connected=eq.true"
                headers = MCPConnectionStore._get_db_headers(supabase_jwt)
                try:
                    res = requests.get(url, headers=headers, timeout=5)
                    if res.status_code == 200:
                        return res.json()
                except Exception as e:
                    print(f"Supabase connection failed, falling back to local: {e}")
                    pass

        # Fallback local
        normalized_key = (user_key or "demo").lower().strip()
        with MCPConnectionStore._lock:
            payload = MCPConnectionStore._read()
            conns = []
            for provider, users in payload.items():
                if normalized_key in users:
                    session = users[normalized_key]
                    if session.get("connected") and not MCPConnectionStore._is_mock_session(session):
                        conns.append({
                            "provider": provider,
                            "provider_user_id": session.get("username") or session.get("email") or session.get("provider_user_id"),
                            "access_token": session.get("access_token") or session.get("token"),
                            "refresh_token": session.get("refresh_token") or session.get("domain"),
                        })
            return conns

    @staticmethod
    def get(provider: str, user_key: str, supabase_jwt: str | None = None) -> dict | None:
        if supabase_jwt and SUPABASE_URL:
            db_val = MCPConnectionStore.get_from_db(provider, supabase_jwt)
            if db_val is not None:
                return db_val

        # Fallback to local store
        normalized_key = (user_key or "demo").lower().strip()
        with MCPConnectionStore._lock:
            session = (
                MCPConnectionStore._read()
                .get(provider, {})
                .get(normalized_key)
            )
            if MCPConnectionStore._is_mock_session(session):
                return None
            return session

    @staticmethod
    def set(
        provider: str, user_key: str, session: dict, supabase_jwt: str | None = None
    ) -> dict:
        if supabase_jwt and SUPABASE_URL:
            db_res = MCPConnectionStore.set_in_db(provider, supabase_jwt, session)
            if db_res is not None:
                return session

        # Fallback to local store
        normalized_key = (user_key or "demo").lower().strip()
        with MCPConnectionStore._lock:
            payload = MCPConnectionStore._read()
            payload.setdefault(provider, {})[normalized_key] = session
            MCPConnectionStore._write(payload)
        return session
