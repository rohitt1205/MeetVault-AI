import json
import os
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import Lock


MCP_OAUTH_STATE_STORE_PATH = Path(
    os.getenv(
        "MCP_OAUTH_STATE_STORE_PATH",
        Path(__file__).resolve().parents[2] / "mcp_oauth_states.json",
    )
)
MCP_OAUTH_STATE_TTL_MINUTES = int(os.getenv("MCP_OAUTH_STATE_TTL_MINUTES", "30"))


class MCPOAuthStateStore:
    _lock = Lock()

    @staticmethod
    def _read() -> dict:
        if not MCP_OAUTH_STATE_STORE_PATH.exists():
            return {}

        try:
            return json.loads(MCP_OAUTH_STATE_STORE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _write(payload: dict) -> None:
        MCP_OAUTH_STATE_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        MCP_OAUTH_STATE_STORE_PATH.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _is_expired(created_at: str | None) -> bool:
        if not created_at:
            return True

        try:
            created = datetime.fromisoformat(created_at)
        except ValueError:
            return True

        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        expiry = created + timedelta(minutes=MCP_OAUTH_STATE_TTL_MINUTES)
        return datetime.now(timezone.utc) > expiry

    @staticmethod
    def _cleanup(payload: dict) -> dict:
        cleaned = {}
        for token, entry in payload.items():
            if not isinstance(entry, dict):
                continue
            if MCPOAuthStateStore._is_expired(entry.get("created_at")):
                continue
            cleaned[token] = entry
        return cleaned

    @staticmethod
    def create(user_key: str, supabase_jwt: str) -> str:
        state_token = secrets.token_urlsafe(32)
        entry = {
            "user_key": (user_key or "demo").lower().strip(),
            "supabase_jwt": supabase_jwt,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        with MCPOAuthStateStore._lock:
            payload = MCPOAuthStateStore._cleanup(MCPOAuthStateStore._read())
            payload[state_token] = entry
            MCPOAuthStateStore._write(payload)

        return state_token

    @staticmethod
    def consume(state_token: str) -> dict | None:
        if not state_token:
            return None

        with MCPOAuthStateStore._lock:
            payload = MCPOAuthStateStore._cleanup(MCPOAuthStateStore._read())
            entry = payload.pop(state_token, None)
            MCPOAuthStateStore._write(payload)

        return entry
