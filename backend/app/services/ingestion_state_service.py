from datetime import datetime, timezone


class IngestionStateService:
    _statuses = {}

    @staticmethod
    def mark_status(meeting_id: str, status: str) -> dict:
        payload = {
            "meeting_id": meeting_id,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
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
            },
        )

    @staticmethod
    def get_all_statuses() -> list[dict]:
        return list(IngestionStateService._statuses.values())

    @staticmethod
    def is_processed(meeting_id: str) -> bool:
        return (
            IngestionStateService
            .get_status(meeting_id)
            .get("status") == "EMBEDDED"
        )
