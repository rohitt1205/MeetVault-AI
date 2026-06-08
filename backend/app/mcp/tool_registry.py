import json
import os
import base64
import requests
from urllib.parse import quote
from pathlib import Path
from threading import Lock
from typing import Any

MCP_TOOL_REGISTRY_PATH = Path(
    os.getenv(
        "MCP_TOOL_REGISTRY_PATH",
        Path(__file__).resolve().parents[2] / "mcp_tools.json",
    )
)

SUPABASE_URL = os.getenv("VITE_SUPABASE_URL") or os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("VITE_SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_KEY")


class MCPToolRegistry:
    _lock = Lock()

    @staticmethod
    def _read() -> dict:
        if not MCP_TOOL_REGISTRY_PATH.exists():
            return {}
        try:
            return json.loads(MCP_TOOL_REGISTRY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _write(payload: dict) -> None:
        MCP_TOOL_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        MCP_TOOL_REGISTRY_PATH.write_text(
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
    def register_tools(
        provider: str,
        user_key: str,
        tools: list[dict],
        supabase_jwt: str | None = None,
    ) -> bool:
        """
        Registers a list of tools for a provider.
        tools format: list of dict with 'name', 'description', 'parameters'.
        """
        if supabase_jwt and SUPABASE_URL:
            user_id = MCPToolRegistry._extract_user_id(supabase_jwt)
            if user_id:
                # 1. Clear existing tools for this provider
                MCPToolRegistry.clear_tools(provider, user_key, supabase_jwt)

                # 2. Insert new tools
                url = f"{SUPABASE_URL}/rest/v1/mcp_tools"
                headers = MCPToolRegistry._get_db_headers(supabase_jwt)
                
                payload = [
                    {
                        "user_id": user_id,
                        "provider": provider,
                        "tool_name": tool.get("name"),
                        "description": tool.get("description"),
                        "parameters": tool.get("parameters") or {},
                        "status": "active",
                        "updated_at": "now()",
                    }
                    for tool in tools
                ]
                if not payload:
                    return True
                try:
                    response = requests.post(url, json=payload, headers=headers, timeout=5)
                    if response.status_code in (200, 201):
                        return True
                except Exception as e:
                    print(f"Error registering tools in Supabase DB: {e}. Falling back to local.")
                    pass

        # Fallback to local store
        normalized_key = (user_key or "demo").lower().strip()
        with MCPToolRegistry._lock:
            payload = MCPToolRegistry._read()
            payload.setdefault(normalized_key, {})[provider] = [
                {
                    "name": tool.get("name"),
                    "description": tool.get("description"),
                    "parameters": tool.get("parameters") or {},
                    "status": "active",
                }
                for tool in tools
            ]
            MCPToolRegistry._write(payload)
            return True

    @staticmethod
    def get_active_tools(
        user_key: str,
        supabase_jwt: str | None = None,
    ) -> list[dict]:
        """
        Returns all active tools for the user.
        Format: list of dict with 'provider', 'name', 'description', 'parameters', 'status'.
        """
        if supabase_jwt and SUPABASE_URL:
            user_id = MCPToolRegistry._extract_user_id(supabase_jwt)
            if user_id:
                url = f"{SUPABASE_URL}/rest/v1/mcp_tools?user_id=eq.{user_id}&status=eq.active"
                headers = MCPToolRegistry._get_db_headers(supabase_jwt)
                try:
                    response = requests.get(url, headers=headers, timeout=10)
                    if response.status_code == 200:
                        rows = response.json()
                        return [
                            {
                                "provider": row.get("provider"),
                                "name": row.get("tool_name"),
                                "description": row.get("description"),
                                "parameters": row.get("parameters") or {},
                                "status": row.get("status"),
                            }
                            for row in rows
                        ]
                except Exception as e:
                    print(f"Error fetching active tools from Supabase DB: {e}")

        # Fallback to local store
        normalized_key = (user_key or "demo").lower().strip()
        with MCPToolRegistry._lock:
            local_data = MCPToolRegistry._read().get(normalized_key, {})
            all_tools = []
            for provider, tools in local_data.items():
                for tool in tools:
                    if tool.get("status") == "active":
                        all_tools.append({
                            "provider": provider,
                            "name": tool.get("name"),
                            "description": tool.get("description"),
                            "parameters": tool.get("parameters") or {},
                            "status": tool.get("status"),
                        })
            return all_tools

    @staticmethod
    def clear_tools(
        provider: str,
        user_key: str,
        supabase_jwt: str | None = None,
    ) -> bool:
        """Clears all registered tools for a given provider."""
        if supabase_jwt and SUPABASE_URL:
            user_id = MCPToolRegistry._extract_user_id(supabase_jwt)
            if user_id:
                provider_filter = quote(provider, safe="")
                url = f"{SUPABASE_URL}/rest/v1/mcp_tools?user_id=eq.{user_id}&provider=eq.{provider_filter}"
                headers = MCPToolRegistry._get_db_headers(supabase_jwt)
                try:
                    response = requests.delete(url, headers=headers, timeout=5)
                    if response.status_code in (200, 204):
                        return True
                except Exception as e:
                    print(f"Error clearing tools in Supabase DB: {e}. Falling back to local.")
                    pass

        # Fallback to local store
        normalized_key = (user_key or "demo").lower().strip()
        with MCPToolRegistry._lock:
            payload = MCPToolRegistry._read()
            if normalized_key in payload and provider in payload[normalized_key]:
                del payload[normalized_key][provider]
                MCPToolRegistry._write(payload)
                return True
        return False
