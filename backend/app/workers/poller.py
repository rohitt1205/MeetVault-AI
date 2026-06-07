import os
import threading
from datetime import datetime, timezone

from app.services.chroma_service import ChromaService
from app.services.ingestion_service import IngestionService
from app.services.ingestion_state_service import IngestionStateService
from app.services.token_diagnostics_service import TokenDiagnosticsService


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class WorkspaceSyncPoller:
    _lock = threading.Lock()
    _tokens: dict[str, dict] = {}
    _thread: threading.Thread | None = None
    _stop_event = threading.Event()
    _last_started_at: str | None = None
    _last_checked_at: str | None = None
    _last_error: str | None = None
    _last_result: dict | None = None

    enabled = _env_bool("MEETVAULT_AUTO_SYNC_ENABLED", False)
    interval_seconds = max(30, int(os.getenv("MEETVAULT_AUTO_SYNC_INTERVAL_SECONDS", "60")))
    max_recordings_per_poll = max(1, int(os.getenv("MEETVAULT_AUTO_SYNC_LIMIT", "50")))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def start(cls) -> None:
        if not cls.enabled:
            return

        with cls._lock:
            if cls._thread and cls._thread.is_alive():
                return

            cls._stop_event.clear()
            cls._thread = threading.Thread(
                target=cls._run,
                name="meetvault-workspace-sync-poller",
                daemon=True,
            )
            cls._thread.start()

    @classmethod
    def stop(cls) -> None:
        cls._stop_event.set()

    @classmethod
    def register_token(cls, access_token: str, limit: int | None = None) -> dict:
        if not cls.enabled:
            cls._last_error = None
            cls._last_result = {
                "status": "DISABLED",
                "message": "Auto-sync polling is disabled. Meeting preparation is manual.",
            }
            return cls.status()

        diagnostics = TokenDiagnosticsService.inspect(access_token)
        user_key = (
            diagnostics.get("user_principal_name")
            or diagnostics.get("user_id")
            or "current-user"
        )
        payload = {
            "access_token": access_token,
            "registered_at": cls._now(),
            "limit": limit or cls.max_recordings_per_poll,
            "diagnostics": {
                "user_principal_name": diagnostics.get("user_principal_name"),
                "scopes": diagnostics.get("scopes", []),
                "missing_scopes": diagnostics.get("missing_scopes", []),
                "can_auto_sync": diagnostics.get("can_auto_sync", False),
                "expires_at": diagnostics.get("expires_at"),
            },
        }

        with cls._lock:
            cls._tokens[user_key] = payload

        cls.start()
        threading.Thread(
            target=cls.tick,
            name="meetvault-workspace-sync-immediate",
            daemon=True,
        ).start()
        return cls.status()

    @classmethod
    def status(cls) -> dict:
        workspace_sync = IngestionStateService.get_workspace_sync_status()
        vector_status = ChromaService.get_status()
        with cls._lock:
            users = [
                {
                    "user_key": user_key,
                    "registered_at": payload.get("registered_at"),
                    "limit": payload.get("limit"),
                    "diagnostics": payload.get("diagnostics", {}),
                }
                for user_key, payload in cls._tokens.items()
            ]

        return {
            "enabled": cls.enabled,
            "running": bool(cls._thread and cls._thread.is_alive()),
            "registered_users": users,
            "registered_user_count": len(users),
            "interval_seconds": cls.interval_seconds,
            "max_recordings_per_poll": cls.max_recordings_per_poll,
            "last_started_at": cls._last_started_at,
            "last_checked_at": cls._last_checked_at,
            "last_error": cls._last_error,
            "last_result": cls._last_result,
            "workspace_sync": workspace_sync,
            "vector_store": {
                "db_path": vector_status.get("db_path"),
                "collection_name": vector_status.get("collection_name"),
                "document_count": vector_status.get("document_count", 0),
                "indexed_document_count": vector_status.get("indexed_document_count", 0),
                "indexed_meeting_count": vector_status.get("indexed_meeting_count", 0),
                "source_counts": vector_status.get("source_counts", {}),
            },
        }

    @classmethod
    def _run(cls) -> None:
        while not cls._stop_event.wait(cls.interval_seconds):
            cls.tick()

    @classmethod
    def tick(cls) -> dict:
        if not cls.enabled:
            cls._last_error = "Auto-sync polling is disabled."
            return cls.status()

        workspace_status = IngestionStateService.get_workspace_sync_status().get("status")
        if workspace_status in {"QUEUED", "RUNNING"}:
            cls._last_checked_at = cls._now()
            cls._last_result = {
                "status": "SKIPPED",
                "message": "Workspace sync is already running.",
            }
            return cls.status()

        with cls._lock:
            token_items = list(cls._tokens.items())

        if not token_items:
            cls._last_checked_at = cls._now()
            cls._last_result = {
                "status": "IDLE",
                "message": "Waiting for a signed-in user token.",
            }
            return cls.status()

        cls._last_started_at = cls._now()
        cls._last_checked_at = cls._last_started_at
        cls._last_error = None
        results = []

        for user_key, payload in token_items:
            diagnostics = payload.get("diagnostics", {})
            if diagnostics.get("missing_scopes"):
                results.append({
                    "user_key": user_key,
                    "status": "SKIPPED",
                    "message": "Token is missing Graph scopes needed for auto-sync.",
                    "missing_scopes": diagnostics.get("missing_scopes", []),
                })
                continue

            try:
                result = IngestionService.start_workspace_sync(
                    payload["access_token"],
                    limit=payload.get("limit") or cls.max_recordings_per_poll,
                )
                results.append({"user_key": user_key, **result})
            except Exception as exc:  # pragma: no cover - background guard
                cls._last_error = str(exc)
                results.append({
                    "user_key": user_key,
                    "status": "FAILED",
                    "message": str(exc),
                })

        cls._last_checked_at = cls._now()
        cls._last_result = {
            "status": "COMPLETED",
            "users_checked": len(token_items),
            "results": results,
        }
        return cls.status()
