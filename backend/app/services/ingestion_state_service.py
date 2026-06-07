from datetime import datetime, timezone


class IngestionStateService:
    _statuses = {}
    _cancelled_meetings: set[str] = set()
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
    def request_cancel(meeting_id: str) -> None:
        if meeting_id:
            IngestionStateService._cancelled_meetings.add(meeting_id)

    @staticmethod
    def clear_cancel(meeting_id: str) -> None:
        IngestionStateService._cancelled_meetings.discard(meeting_id)

    @staticmethod
    def is_cancelled(meeting_id: str) -> bool:
        return meeting_id in IngestionStateService._cancelled_meetings

    @staticmethod
    def clear_status(meeting_id: str) -> dict:
        IngestionStateService._statuses.pop(meeting_id, None)
        return {
            "meeting_id": meeting_id,
            "status": "NOT_STARTED",
            "updated_at": None,
            "details": {},
        }

    @staticmethod
    def clear_all() -> dict:
        status_count = len(IngestionStateService._statuses)
        cancel_count = len(IngestionStateService._cancelled_meetings)
        IngestionStateService._statuses.clear()
        IngestionStateService._cancelled_meetings.clear()
        IngestionStateService._workspace_sync = {
            "status": "IDLE",
            "updated_at": None,
            "message": "Index reset. Open a recording card to prepare transcript embeddings.",
        }
        return {
            "cleared_statuses": status_count,
            "cleared_cancellations": cancel_count,
        }

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
