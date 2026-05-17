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
<<<<<<< HEAD

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
=======
class IngestionStateService:
    # In-memory dictionary to store ingestion status for meetings
    # Format: {meeting_id: {"status": "PROCESSING|EMBEDDED|SKIPPED", "updated_at": timestamp}}
    _statuses = {}

    @staticmethod
    def is_processed(meeting_id: str) -> bool:
        """
        Checks if a meeting has already been processed (status is EMBEDDED).
        """
        data = IngestionStateService._statuses.get(meeting_id)
        if data and data.get("status") == "EMBEDDED":
            return True
        return False

    @staticmethod
    def mark_status(meeting_id: str, status: str):
        """
        Marks or updates the status of a meeting ingestion.
        """
        import time
        IngestionStateService._statuses[meeting_id] = {
            "meeting_id": meeting_id,
            "status": status,
            "updated_at": time.time()
        }

    @staticmethod
    def get_status(meeting_id: str) -> dict:
        """
        Retrieves the ingestion status for a specific meeting.
        """
        data = IngestionStateService._statuses.get(meeting_id)
        if not data:
            return {"meeting_id": meeting_id, "status": "NOT_FOUND"}
        return data

    @staticmethod
    def get_all_statuses() -> dict:
        """
        Retrieves all meeting ingestion statuses.
        """
        return {"statuses": list(IngestionStateService._statuses.values())}
>>>>>>> origin/main
