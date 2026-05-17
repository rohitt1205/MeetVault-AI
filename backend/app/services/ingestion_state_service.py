from datetime import datetime, timezone


class IngestionStateService:
    _statuses = {}
    _workspace_sync = {
        "status": "IDLE",
        "updated_at": None,
    }

    @staticmethod
    def mark_status(meeting_id: str, status: str, **details) -> dict:
        payload = {
            "meeting_id": meeting_id,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **{key: value for key, value in details.items() if value is not None},
        }
        IngestionStateService._statuses[meeting_id] = payload
        return payload

    @staticmethod
    def get_status(meeting_id: str) -> dict:
        return IngestionStateService._statuses.get(
            meeting_id,
            {
                "meeting_id": meeting_id,
                "status": "NOT_STARTED",
                "updated_at": None,
                "details": {},
            },
        )

    @staticmethod
    def get_all_statuses() -> list[dict]:
        return list(IngestionStateService._statuses.values())

    @staticmethod
    def has_status(meeting_id: str, *statuses: str) -> bool:
        if not statuses:
            return False

        return IngestionStateService.get_status(meeting_id).get("status") in set(statuses)

    @staticmethod
    def is_processed(meeting_id: str) -> bool:
        return (
            IngestionStateService
            .get_status(meeting_id)
            .get("status") == "EMBEDDED"
        )

    @staticmethod
    def mark_workspace_sync(status: str, **details) -> dict:
        payload = {
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **{key: value for key, value in details.items() if value is not None},
        }
        IngestionStateService._workspace_sync = payload
        return payload

    @staticmethod
    def get_workspace_sync_status() -> dict:
        return IngestionStateService._workspace_sync
