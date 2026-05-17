import json
import os
from pathlib import Path
from threading import Lock


MCP_CONNECTION_STORE_PATH = Path(
    os.getenv("MCP_CONNECTION_STORE_PATH", "./mcp_connections.json")
)


class MCPConnectionStore:
    _lock = Lock()

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
    def get(provider: str, user_key: str) -> dict | None:
        normalized_key = (user_key or "demo").lower().strip()
        with MCPConnectionStore._lock:
            return (
                MCPConnectionStore._read()
                .get(provider, {})
                .get(normalized_key)
            )

    @staticmethod
    def set(provider: str, user_key: str, session: dict) -> dict:
        normalized_key = (user_key or "demo").lower().strip()
        with MCPConnectionStore._lock:
            payload = MCPConnectionStore._read()
            payload.setdefault(provider, {})[normalized_key] = session
            MCPConnectionStore._write(payload)
        return session
