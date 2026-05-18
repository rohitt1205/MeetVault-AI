from datetime import datetime, timezone
from threading import Condition, Lock

from fastapi import HTTPException

from app.services.chroma_service import ChromaService
from app.services.ingestion_service import IngestionService
from app.services.ingestion_state_service import IngestionStateService
from app.services.meeting_service import MeetingService
from app.services.onedrive_service import OneDriveService


class MeetingCatalogService:
    _catalog: list[dict] = []
    _onedrive_items_by_event_id: dict[str, dict] = {}
    _last_synced_at: str | None = None
    _last_diagnostics: dict = {}
    _sync_lock = Lock()
    _sync_condition = Condition(_sync_lock)
    _sync_status: str = "IDLE"
    _sync_error: str | None = None

    @staticmethod
    def get_onedrive_item(event_id: str) -> dict | None:
        return MeetingCatalogService._onedrive_items_by_event_id.get(event_id)

    @staticmethod
    def mark_meeting_unindexed(meeting_id: str) -> bool:
        """Keep in-memory catalog in sync after chat/index deletion."""
        updated = False
        for item in MeetingCatalogService._catalog:
            if item.get("event_id") != meeting_id and item.get("meeting_id") != meeting_id:
                continue
            item["is_indexed"] = False
            item["ingestion_status"] = "NOT_STARTED"
            updated = True
        return updated

    @staticmethod
    def get_catalog() -> dict:
        return {
            "meetings": MeetingCatalogService._catalog,
            "synced_at": MeetingCatalogService._last_synced_at,
            "count": len(MeetingCatalogService._catalog),
            "diagnostics": MeetingCatalogService._last_diagnostics,
            "sync_status": MeetingCatalogService._sync_status,
            "sync_error": MeetingCatalogService._sync_error,
        }

    @staticmethod
    def discover_teams(access_token: str, limit: int = 30, *, scan_graph: bool = False) -> dict:
        """Teams/calendar discovery only — no OneDrive."""
        return IngestionService.discover_teams_sources(
            access_token,
            limit=limit,
            scan_graph=scan_graph,
        )

    @staticmethod
    def discover_onedrive(
        access_token: str,
        *,
        video_limit: int = 200,
        meeting_titles: list[str] | None = None,
    ) -> dict:
        """OneDrive + shared-with-me videos only — no calendar matching."""
        return IngestionService.discover_onedrive_sources(
            access_token,
            video_limit=video_limit,
            meeting_titles=meeting_titles,
        )

    @staticmethod
    def merge_discovery_sources(teams_source: dict, onedrive_source: dict) -> dict:
        """
        Match OneDrive videos to calendar meetings where possible; add every video
        and qualifying calendar/indexed meeting to the catalog.
        """
        meetings = teams_source.get("calendar_meetings") or []
        sync_error = teams_source.get("sync_error")
        recording_event_ids = set(teams_source.get("recording_event_ids") or [])
        videos = onedrive_source.get("videos") or []

        matched_calendar_ids, _unmatched = OneDriveService.match_recording_assets_to_meetings(
            meetings,
            {"transcripts": [], "videos": videos},
        )
        recording_event_ids.update(matched_calendar_ids)
        for file_item in videos:
            catalog_event_id = OneDriveService.catalog_event_id(file_item)
            if catalog_event_id:
                recording_event_ids.add(catalog_event_id)

        teams_diagnostics = dict(teams_source.get("diagnostics") or {})
        onedrive_diagnostics = dict(onedrive_source.get("diagnostics") or {})
        discovery_diagnostics = {
            **teams_diagnostics,
            **onedrive_diagnostics,
            "onedrive_matched_calendar_meetings": len(matched_calendar_ids),
            "onedrive_catalog_entries": len(videos),
            "meetings_with_graph_recording_or_transcript": teams_diagnostics.get(
                "meetings_with_graph_recording_or_transcript",
                len(teams_source.get("recording_event_ids") or []),
            ),
        }

        MeetingCatalogService._onedrive_items_by_event_id = {}
        return MeetingCatalogService._build_catalog(
            meetings=meetings,
            recording_event_ids=recording_event_ids,
            onedrive_catalog_files=videos,
            discovery_diagnostics=discovery_diagnostics,
            sync_error=sync_error,
        )

    @staticmethod
    def sync_catalog(access_token: str, limit: int = 30, *, scan_graph: bool = False) -> dict:
        """
        Run Teams + OneDrive discovery in parallel, merge, and return the final catalog.
        Concurrent callers block until the in-flight sync finishes.
        """
        with MeetingCatalogService._sync_condition:
            while MeetingCatalogService._sync_status == "RUNNING":
                MeetingCatalogService._sync_condition.wait(timeout=600)

            MeetingCatalogService._sync_status = "RUNNING"
            MeetingCatalogService._sync_error = None

        try:
            teams_source = MeetingCatalogService.discover_teams(
                access_token,
                limit,
                scan_graph=scan_graph,
            )
            calendar_titles = [
                meeting.get("title")
                for meeting in teams_source.get("calendar_meetings") or []
                if meeting.get("title")
            ]
            onedrive_source = MeetingCatalogService.discover_onedrive(
                access_token,
                meeting_titles=calendar_titles,
            )
            result = MeetingCatalogService.merge_discovery_sources(teams_source, onedrive_source)
            with MeetingCatalogService._sync_condition:
                MeetingCatalogService._sync_status = "COMPLETED"
                MeetingCatalogService._sync_condition.notify_all()
            return {
                **result,
                "sync_status": "COMPLETED",
                "sync_error": result.get("sync_error"),
            }
        except HTTPException as exc:
            message = MeetingCatalogService._graph_error_message(exc)
            with MeetingCatalogService._sync_condition:
                MeetingCatalogService._sync_status = "FAILED"
                MeetingCatalogService._sync_error = message
                MeetingCatalogService._sync_condition.notify_all()
            return {
                **MeetingCatalogService.get_catalog(),
                "sync_status": "FAILED",
                "sync_error": message,
            }
        except Exception as exc:  # pragma: no cover
            message = str(exc)
            with MeetingCatalogService._sync_condition:
                MeetingCatalogService._sync_status = "FAILED"
                MeetingCatalogService._sync_error = message
                MeetingCatalogService._sync_condition.notify_all()
            return {
                **MeetingCatalogService.get_catalog(),
                "sync_status": "FAILED",
                "sync_error": message,
            }

    @staticmethod
    def _build_catalog(
        *,
        meetings: list[dict],
        recording_event_ids: set[str],
        onedrive_catalog_files: list[dict],
        discovery_diagnostics: dict,
        sync_error: str | None,
    ) -> dict:
        indexed_meetings = ChromaService.list_indexed_meetings()
        indexed_by_event_id = {
            meeting["event_id"]: meeting for meeting in indexed_meetings if meeting.get("event_id")
        }

        catalog_by_id: dict[str, dict] = {}

        for meeting in meetings:
            event_id = meeting.get("event_id") or meeting.get("meeting_id")
            if not event_id:
                continue

            status_payload = IngestionStateService.get_status(event_id)
            status = status_payload.get("status", "NOT_STARTED")
            is_indexed = ChromaService.has_meeting_embeddings(event_id)
            has_recording = event_id in recording_event_ids

            if not has_recording and not is_indexed:
                continue

            start_time = meeting.get("start_time") or meeting.get("end_time")
            catalog_by_id[event_id] = {
                "event_id": event_id,
                "meeting_id": event_id,
                "title": meeting.get("title") or "Untitled meeting",
                "organizer": meeting.get("organizer") or "Microsoft Teams",
                "start_time": start_time,
                "end_time": meeting.get("end_time"),
                "has_recording": has_recording,
                "is_indexed": is_indexed,
                "ingestion_status": status,
                "content_source": "teams",
            }

        for event_id, indexed_meeting in indexed_by_event_id.items():
            if event_id in catalog_by_id:
                catalog_by_id[event_id]["is_indexed"] = True
                catalog_by_id[event_id]["has_recording"] = True
                continue

            status_payload = IngestionStateService.get_status(event_id)
            catalog_by_id[event_id] = {
                "event_id": event_id,
                "meeting_id": event_id,
                "title": indexed_meeting.get("title") or "Indexed meeting",
                "organizer": indexed_meeting.get("organizer") or "MeetVault index",
                "start_time": None,
                "end_time": None,
                "has_recording": True,
                "is_indexed": True,
                "ingestion_status": status_payload.get("status", "EMBEDDED"),
                "content_source": "chroma",
            }

        for file_item in onedrive_catalog_files:
            event_id = OneDriveService.catalog_event_id(file_item)
            if not event_id or event_id in catalog_by_id:
                continue

            MeetingCatalogService._onedrive_items_by_event_id[event_id] = file_item
            file_time = file_item.get("lastModifiedDateTime") or file_item.get("createdDateTime")
            status_payload = IngestionStateService.get_status(event_id)
            catalog_by_id[event_id] = {
                "event_id": event_id,
                "meeting_id": event_id,
                "title": OneDriveService.display_title_from_filename(file_item.get("name") or ""),
                "organizer": (
                    "Shared with me"
                    if file_item.get("_shared_with_me")
                    else "OneDrive"
                ),
                "start_time": file_time,
                "end_time": None,
                "has_recording": True,
                "is_indexed": ChromaService.has_meeting_embeddings(event_id),
                "ingestion_status": status_payload.get("status", "NOT_STARTED"),
                "content_source": (
                    "shared_onedrive"
                    if file_item.get("_shared_with_me")
                    else "onedrive"
                ),
            }

        catalog = list(catalog_by_id.values())
        catalog.sort(
            key=lambda item: item.get("start_time") or item.get("end_time") or "",
            reverse=True,
        )

        MeetingCatalogService._catalog = catalog
        MeetingCatalogService._last_synced_at = datetime.now(timezone.utc).isoformat()
        scanned_dates = [
            meeting.get("start_time") or meeting.get("end_time")
            for meeting in meetings
            if meeting.get("start_time") or meeting.get("end_time")
        ]
        scanned_dates.sort()

        MeetingCatalogService._last_diagnostics = {
            "calendar_meetings_scanned": len(meetings),
            "meetings_with_recording_or_transcript": len(recording_event_ids),
            "meetings_indexed_in_chroma": len(indexed_by_event_id),
            "catalog_count": len(catalog),
            "sync_error": sync_error,
            "calendar_oldest_scanned": scanned_dates[0] if scanned_dates else None,
            "calendar_newest_scanned": scanned_dates[-1] if scanned_dates else None,
            **discovery_diagnostics,
        }

        return {
            "meetings": catalog,
            "synced_at": MeetingCatalogService._last_synced_at,
            "count": len(catalog),
            "diagnostics": MeetingCatalogService._last_diagnostics,
            "sync_error": sync_error,
        }

    @staticmethod
    def _graph_error_message(exc: HTTPException) -> str:
        detail = exc.detail
        if isinstance(detail, dict):
            return (
                detail.get("graph_message")
                or detail.get("message")
                or str(detail)
            )
        if isinstance(detail, str):
            return detail
        return "Microsoft Graph request failed."
