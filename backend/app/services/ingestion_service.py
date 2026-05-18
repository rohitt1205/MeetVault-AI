import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Thread

from fastapi import HTTPException

from app.services.chunk_service import ChunkService
from app.services.chroma_service import ChromaService
from app.services.embedding_service import EmbeddingService
from app.services.ingestion_state_service import IngestionStateService
from app.services.meeting_service import MeetingService
from app.services.onedrive_service import OneDriveService
from app.services.recording_service import RecordingService
from app.services.transcript_service import TranscriptService


class IngestionService:
    _sync_lock = Lock()
    _sync_thread: Thread | None = None
    _meeting_ingest_lock = Lock()
    _transcript_extensions = {".vtt", ".txt"}
    _video_extensions = {".mp4", ".m4a", ".mp3", ".wav", ".webm"}

    @staticmethod
    def discover_recording_assets(
        access_token: str,
        limit: int = 20,
        *,
        fast: bool = True,
    ) -> dict:
        scan_limit = min(limit, 8) if fast else limit
        meetings = MeetingService.get_recent_meetings(access_token, limit=scan_limit)
        graph_recordings = IngestionService.discover_graph_recordings(
            access_token,
            limit=limit,
            meetings=meetings,
            max_workers=6 if fast else 3,
        )

        if fast:
            return {
                "limit": limit,
                "fast": True,
                "graph_recordings": graph_recordings,
                "transcripts": [],
                "videos": [],
            }

        assets = OneDriveService.find_recent_recording_assets(
            access_token,
            limit=limit,
            meeting_titles=[meeting.get("title") or "" for meeting in meetings],
        )
        return {
            "limit": limit,
            "fast": False,
            "graph_recordings": graph_recordings,
            "transcripts": [
                IngestionService._drive_item_summary(item)
                for item in assets.get("transcripts", [])
            ],
            "videos": [
                IngestionService._drive_item_summary(item)
                for item in assets.get("videos", [])
            ],
        }

    @staticmethod
    def discover_graph_recordings(
        access_token: str,
        limit: int = 20,
        meetings: list[dict] | None = None,
        *,
        max_workers: int = 6,
    ) -> list[dict]:
        meeting_list = meetings or MeetingService.get_recent_meetings(access_token, limit=limit)
        recordings: list[dict] = []

        def _recordings_for_meeting(meeting: dict) -> list[dict]:
            try:
                resolved = MeetingService.resolve_online_meeting(
                    access_token,
                    meeting,
                )
                if not resolved:
                    return []

                meeting_recordings = RecordingService.list_online_meeting_recordings(
                    access_token,
                    resolved["online_meeting_id"],
                    user_id=resolved["graph_user_id"],
                )
            except HTTPException as exc:
                if exc.status_code in {401, 403, 404}:
                    return []
                raise

            online_meeting_id = resolved["online_meeting_id"]
            return [
                IngestionService._graph_recording_summary(
                    meeting,
                    online_meeting_id,
                    recording,
                )
                for recording in meeting_recordings
            ]

        worker_count = max(1, min(max_workers, len(meeting_list) or 1))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(_recordings_for_meeting, meeting): meeting
                for meeting in meeting_list
            }
            for future in as_completed(futures):
                recordings.extend(future.result())
                if len(recordings) >= limit:
                    break

        return recordings[:limit]

    @staticmethod
    def discover_onedrive_sources(
        access_token: str,
        *,
        video_limit: int = 200,
        max_shared_pages: int = 5,
        meeting_titles: list[str] | None = None,
    ) -> dict:
        """Fetch OneDrive + shared-with-me videos only (no calendar matching)."""
        try:
            assets = OneDriveService.find_onedrive_videos(
                access_token,
                limit=video_limit,
                max_shared_pages=max_shared_pages,
                meeting_titles=meeting_titles,
            )
        except HTTPException as exc:
            if exc.status_code in {401, 403, 404}:
                return {
                    "source": "onedrive",
                    "videos": [],
                    "diagnostics": {
                        "onedrive_videos_found": 0,
                        "onedrive_shared_assets": 0,
                        "onedrive_discovery_error": True,
                    },
                }
            raise

        videos = assets.get("videos", [])
        probe = assets.get("_probe") or {}
        return {
            "source": "onedrive",
            "videos": videos,
            "diagnostics": {
                "onedrive_videos_found": len(videos),
                "onedrive_shared_assets": sum(
                    1 for file_item in videos if file_item.get("_shared_with_me")
                ),
                "onedrive_mine_recent_video_count": probe.get("mine_recent_video_count", 0),
                "onedrive_mine_recordings_folder_video_count": probe.get(
                    "mine_recordings_folder_video_count",
                    0,
                ),
                "onedrive_shared_raw_count": probe.get("shared_raw_count", 0),
                "onedrive_shared_video_count": probe.get("shared_video_count", 0),
                "onedrive_shared_sample_names": probe.get("shared_sample_names", []),
                "onedrive_search_raw_count": probe.get("search_raw_count", 0),
                "onedrive_search_video_count": probe.get("search_video_count", 0),
                "onedrive_search_sample_names": probe.get("search_sample_names", []),
                "onedrive_search_errors": probe.get("search_errors", []),
                "onedrive_search_totals_by_query": probe.get("search_totals_by_query", {}),
                "onedrive_videos_only": True,
                "onedrive_permission_hint": (
                    "Using Files.Read only: your OneDrive recent files and limited sharedWithMe. "
                    "Colleagues' shared recordings may not appear without Files.Read.All (admin consent)."
                ),
                "onedrive_discovery_error": False,
            },
        }

    @staticmethod
    def discover_teams_sources(
        access_token: str,
        limit: int = 30,
        meetings: list[dict] | None = None,
        *,
        scan_graph: bool = False,
    ) -> dict:
        """Fetch calendar Teams meetings and optional Graph transcript/recording discovery."""
        sync_error = None
        try:
            meeting_list = meetings or MeetingService.get_recent_meetings(
                access_token,
                limit=limit,
                lookback_days=30,
                scan_limit=limit,
            )
        except HTTPException as exc:
            meeting_list = []
            detail = exc.detail
            if isinstance(detail, dict):
                sync_error = detail.get("graph_message") or detail.get("message") or str(detail)
            elif isinstance(detail, str):
                sync_error = detail
            else:
                sync_error = "Calendar fetch failed."

        recording_event_ids: set[str] = set()
        diagnostics: dict = {
            "teams_scan_graph": scan_graph,
            "meetings_scanned": len(meeting_list),
        }

        if meeting_list:
            recording_event_ids, _, graph_diagnostics = (
                IngestionService.discover_meeting_event_ids_with_recordings(
                    access_token,
                    limit=limit,
                    meetings=meeting_list,
                    max_workers=1,
                    include_graph_recordings=False,
                    include_onedrive=False,
                    catalog_mode=not scan_graph,
                )
            )
            diagnostics.update(graph_diagnostics)

        return {
            "source": "teams",
            "sync_error": sync_error,
            "calendar_meetings": meeting_list,
            "recording_event_ids": sorted(recording_event_ids),
            "diagnostics": diagnostics,
        }

    @staticmethod
    def discover_onedrive_meeting_event_ids(
        access_token: str,
        meetings: list[dict],
        *,
        limit: int = 30,
        fast: bool = False,
        show_all: bool = False,
    ) -> tuple[set[str], list[dict], dict]:
        """Match OneDrive / SharePoint recordings and transcript files to calendar meetings."""
        meeting_titles = [meeting.get("title") for meeting in meetings if meeting.get("title")]
        title_limit = 8 if fast else 25
        asset_limit = max(limit * 2, 24) if fast else max(limit * 3, 40)

        try:
            if show_all:
                assets = OneDriveService.find_onedrive_videos(access_token, limit=200)
            elif fast:
                assets = OneDriveService.find_recent_recording_assets_fast(
                    access_token,
                    limit=asset_limit,
                    meeting_titles=meeting_titles[:title_limit],
                )
            else:
                assets = OneDriveService.find_recent_recording_assets(
                    access_token,
                    limit=asset_limit,
                    meeting_titles=meeting_titles[:title_limit],
                )
        except HTTPException as exc:
            if exc.status_code in {401, 403, 404}:
                return set(), [], {
                    "onedrive_transcripts_found": 0,
                    "onedrive_videos_found": 0,
                    "onedrive_matched_calendar_meetings": 0,
                    "onedrive_unmatched_assets": 0,
                    "onedrive_unmatched_samples": [],
                    "onedrive_discovery_error": True,
                }
            raise

        matched_event_ids, unmatched_files = OneDriveService.match_recording_assets_to_meetings(
            meetings,
            assets,
        )
        all_files = [
            *assets.get("transcripts", []),
            *assets.get("videos", []),
        ]
        catalog_files = all_files if show_all else unmatched_files
        return matched_event_ids, catalog_files, {
            "onedrive_transcripts_found": len(assets.get("transcripts", [])),
            "onedrive_videos_found": len(assets.get("videos", [])),
            "onedrive_matched_calendar_meetings": len(matched_event_ids),
            "onedrive_catalog_entries": len(catalog_files),
            "onedrive_unmatched_assets": len(unmatched_files),
            "onedrive_show_all": show_all,
            "onedrive_videos_only": show_all,
            "onedrive_shared_assets": sum(
                1 for file_item in catalog_files if file_item.get("_shared_with_me")
            ),
            "onedrive_unmatched_samples": [
                file_item.get("name")
                for file_item in catalog_files[:8]
                if file_item.get("name")
            ],
            "onedrive_discovery_error": False,
        }

    @staticmethod
    def discover_meeting_event_ids_with_recordings(
        access_token: str,
        limit: int = 30,
        meetings: list[dict] | None = None,
        *,
        max_workers: int = 2,
        include_graph_recordings: bool = False,
        include_onedrive: bool = True,
        catalog_mode: bool = False,
    ) -> tuple[set[str], list[dict], dict]:
        """
        Return calendar event_ids that have Graph transcripts, Graph recordings (optional),
        OneDrive assets, or are already indexed. Graph recordings require
        OnlineMeetingRecording.Read.All; catalog sync skips them by default.

        catalog_mode=True skips slow per-meeting Graph resolution (OneDrive + calendar only).
        """
        meeting_list = meetings or MeetingService.get_recent_meetings(
            access_token,
            limit=limit,
        )
        calendar_with_join_url = sum(1 for meeting in meeting_list if meeting.get("join_url"))

        index_stats = {
            "online_meetings_in_index": 0,
            "matched_by_join_url": 0,
            "matched_by_start_time": 0,
            "still_missing_join_url": 0,
        }
        if catalog_mode:
            diagnostics_note = {"catalog_fast_path": True, "graph_per_meeting_scan_skipped": True}
        else:
            diagnostics_note = {}
            try:
                online_meetings_index = MeetingService.list_organized_online_meetings(
                    access_token,
                    lookback_days=60,
                )
                meeting_list, index_stats = MeetingService.enrich_meetings_from_online_index(
                    meeting_list,
                    online_meetings_index,
                )
            except HTTPException as exc:
                if exc.status_code not in {400, 401, 403, 404}:
                    raise
                meeting_list, index_stats = MeetingService.enrich_meetings_from_online_index(
                    meeting_list,
                    [],
                )

        after_enrich_join_url = sum(1 for meeting in meeting_list if meeting.get("join_url"))

        event_ids: set[str] = set()
        diagnostics = {
            "meetings_scanned": len(meeting_list),
            "calendar_with_join_url": calendar_with_join_url,
            "calendar_with_join_url_after_index": after_enrich_join_url,
            "with_join_url": 0,
            "resolved_online_meeting_id": 0,
            "unresolved_online_meeting_id": 0,
            "with_graph_recordings": 0,
            "with_graph_transcripts": 0,
            "graph_permission_errors": 0,
            "graph_throttled": 0,
            **index_stats,
            **diagnostics_note,
        }
        diagnostics_lock = Lock()

        def _is_throttled(exc: HTTPException) -> bool:
            if exc.status_code == 429:
                return True
            detail = exc.detail
            return isinstance(detail, dict) and detail.get("graph_code") in {
                "ApplicationThrottled",
                "TooManyRequests",
                "activityLimitReached",
            }

        def _list_graph_meeting_content(
            online_meeting_id: str,
            graph_user_id: str,
            join_url: str | None,
        ) -> tuple[list[dict], list[dict], str]:
            user_candidates = MeetingService._graph_user_candidates(meeting, join_url)
            ordered_user_ids = [graph_user_id] + [
                user_id for user_id in user_candidates if user_id != graph_user_id
            ]
            last_forbidden: HTTPException | None = None

            for user_id in ordered_user_ids:
                try:
                    transcripts = TranscriptService.list_online_meeting_transcripts(
                        access_token,
                        online_meeting_id,
                        user_id=user_id,
                    )
                    recordings = []
                    if include_graph_recordings and not transcripts:
                        recordings = RecordingService.list_online_meeting_recordings(
                            access_token,
                            online_meeting_id,
                            user_id=user_id,
                        )
                    if transcripts or recordings:
                        return recordings, transcripts, user_id
                except HTTPException as exc:
                    if exc.status_code in {401, 403}:
                        last_forbidden = exc
                        continue
                    raise

            if last_forbidden is not None:
                raise last_forbidden
            return [], [], graph_user_id

        def _inspect_meeting(meeting: dict) -> str | None:
            event_id = meeting.get("event_id") or meeting.get("meeting_id")
            if not event_id:
                return None

            has_join_url = bool(
                meeting.get("join_url")
                or meeting.get("online_meeting_id")
            )

            try:
                meeting_for_resolve = MeetingService.enrich_meeting_from_event(
                    access_token,
                    meeting,
                )
                join_url = meeting_for_resolve.get("join_url")
                has_join_url = bool(
                    join_url or meeting_for_resolve.get("online_meeting_id")
                )

                resolved = MeetingService.resolve_online_meeting(
                    access_token,
                    meeting_for_resolve,
                )
                if not resolved:
                    with diagnostics_lock:
                        if has_join_url:
                            diagnostics["with_join_url"] += 1
                        diagnostics["unresolved_online_meeting_id"] += 1
                    return None

                online_meeting_id = resolved["online_meeting_id"]
                graph_user_id = resolved["graph_user_id"]

                recordings, transcripts, graph_user_id = _list_graph_meeting_content(
                    online_meeting_id,
                    graph_user_id,
                    join_url,
                )

                with diagnostics_lock:
                    if has_join_url or online_meeting_id:
                        diagnostics["with_join_url"] += 1
                    diagnostics["resolved_online_meeting_id"] += 1
                    if recordings:
                        diagnostics["with_graph_recordings"] += 1
                    if transcripts:
                        diagnostics["with_graph_transcripts"] += 1

                if recordings or transcripts:
                    return event_id
            except HTTPException as exc:
                if _is_throttled(exc):
                    with diagnostics_lock:
                        diagnostics["graph_throttled"] += 1
                        diagnostics["unresolved_online_meeting_id"] += 1
                    return None
                if exc.status_code in {400, 401, 403, 404}:
                    with diagnostics_lock:
                        if exc.status_code in {401, 403}:
                            diagnostics["graph_permission_errors"] += 1
                        diagnostics["unresolved_online_meeting_id"] += 1
                    return None
                raise
            finally:
                if max_workers <= 1:
                    time.sleep(0.4)

            return None

        include_graph_scan = not catalog_mode

        if include_graph_scan:
            worker_count = max(1, min(max_workers, len(meeting_list) or 1))
            if worker_count <= 1:
                for meeting in meeting_list:
                    discovered = _inspect_meeting(meeting)
                    if discovered:
                        event_ids.add(discovered)
            else:
                with ThreadPoolExecutor(max_workers=worker_count) as executor:
                    futures = [
                        executor.submit(_inspect_meeting, meeting) for meeting in meeting_list
                    ]
                    for future in as_completed(futures):
                        discovered = future.result()
                        if discovered:
                            event_ids.add(discovered)

        graph_matched_count = len(event_ids)

        onedrive_catalog_files: list[dict] = []
        if include_onedrive:
            onedrive_event_ids, onedrive_catalog_files, onedrive_stats = (
                IngestionService.discover_onedrive_meeting_event_ids(
                    access_token,
                    meeting_list,
                    limit=limit,
                    fast=catalog_mode,
                    show_all=catalog_mode,
                )
            )
            event_ids.update(onedrive_event_ids)
            for file_item in onedrive_catalog_files:
                catalog_event_id = OneDriveService.catalog_event_id(file_item)
                if catalog_event_id:
                    event_ids.add(catalog_event_id)
            diagnostics.update(onedrive_stats)

        diagnostics["meetings_with_graph_recording_or_transcript"] = graph_matched_count
        diagnostics["meetings_with_onedrive_assets"] = diagnostics.get(
            "onedrive_catalog_entries",
            len(onedrive_catalog_files),
        )
        diagnostics["meetings_with_recording_or_transcript"] = len(event_ids)
        return event_ids, onedrive_catalog_files, diagnostics

    @staticmethod
    def _load_transcript_from_onedrive_item(
        access_token: str,
        drive_item: dict,
    ) -> tuple[list[dict], str]:
        name = (drive_item.get("name") or "").lower()
        if name.endswith((".vtt", ".txt")):
            transcript = OneDriveService.transcript_from_drive_item(access_token, drive_item)
            if transcript:
                return transcript, "onedrive_transcript"

        transcript = RecordingService.transcribe_drive_item(access_token, drive_item)
        if transcript:
            return transcript, "onedrive_video_transcription"
        return [], "none"

    @staticmethod
    def start_meeting_ingestion(access_token: str, event_id: str) -> dict:
        from app.services.meeting_catalog_service import MeetingCatalogService

        if event_id.startswith("onedrive:"):
            drive_item = MeetingCatalogService.get_onedrive_item(event_id)
            if not drive_item:
                raise HTTPException(
                    status_code=404,
                    detail="OneDrive recording not found. Run catalog sync again.",
                )
            meeting_id = event_id
            meeting_title = OneDriveService.display_title_from_filename(
                drive_item.get("name") or "",
            )
            meeting = {
                "event_id": event_id,
                "meeting_id": meeting_id,
                "title": meeting_title,
                "onedrive_item": drive_item,
            }
        else:
            meeting = MeetingService.get_meeting_event(access_token, event_id)
            meeting_id = meeting.get("event_id") or event_id
            meeting_title = meeting.get("title") or "Untitled meeting"

        def run_ingestion() -> None:
            try:
                IngestionService.ingest_meeting(access_token, event_id)
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                IngestionStateService.mark_status(
                    meeting_id,
                    "FAILED",
                    meeting_title=meeting_title,
                    stage="failed",
                    message=detail,
                    error_detail=exc.detail,
                )
            except Exception as exc:  # pragma: no cover - background safety net
                IngestionStateService.mark_status(
                    meeting_id,
                    "FAILED",
                    meeting_title=meeting_title,
                    stage="failed",
                    message=str(exc),
                    error_detail=str(exc),
                )

        with IngestionService._meeting_ingest_lock:
            IngestionStateService.clear_cancel(meeting_id)

            if (
                IngestionStateService.is_processed(meeting_id)
                or ChromaService.has_meeting_embeddings(meeting_id)
            ):
                IngestionStateService.mark_status(
                    meeting_id,
                    "EMBEDDED",
                    meeting_title=meeting_title,
                    source_type="existing_index",
                    stage="ready",
                    message="Meeting is ready for chat.",
                )
                return {
                    "meeting_id": meeting_id,
                    "title": meeting_title,
                    "status": "EMBEDDED",
                    "message": "Meeting already embedded",
                }

            current_status = IngestionStateService.get_status(meeting_id).get("status")
            if current_status in {"QUEUED", "PROCESSING"}:
                return {
                    "meeting_id": meeting_id,
                    "title": meeting_title,
                    "status": current_status,
                    "message": "Meeting preparation is already running.",
                }

            IngestionStateService.mark_status(
                meeting_id,
                "QUEUED",
                meeting_title=meeting_title,
                stage="discover",
                message="Queued for preparation.",
            )

            worker = Thread(target=run_ingestion, daemon=True)
            worker.start()

        return {
            "meeting_id": meeting_id,
            "title": meeting_title,
            "status": "QUEUED",
            "message": "Meeting preparation started in the background.",
        }

    @staticmethod
    def ingest_meeting(access_token: str, event_id: str) -> dict:
        from app.services.meeting_catalog_service import MeetingCatalogService

        if event_id.startswith("onedrive:"):
            drive_item = MeetingCatalogService.get_onedrive_item(event_id)
            if not drive_item:
                raise HTTPException(
                    status_code=404,
                    detail="OneDrive recording not found. Run catalog sync again.",
                )
            meeting_id = event_id
            meeting_title = OneDriveService.display_title_from_filename(
                drive_item.get("name") or "",
            )
            meeting = {
                "event_id": event_id,
                "meeting_id": meeting_id,
                "title": meeting_title,
                "onedrive_item": drive_item,
            }
        else:
            meeting = MeetingService.get_meeting_event(access_token, event_id)
            meeting_id = meeting.get("event_id") or event_id
            meeting_title = meeting.get("title") or "Untitled meeting"

        if (
            IngestionStateService.is_processed(meeting_id)
            or ChromaService.has_meeting_embeddings(meeting_id)
        ):
            IngestionStateService.mark_status(
                meeting_id,
                "EMBEDDED",
                meeting_title=meeting_title,
                source_type="existing_index",
                stage="ready",
                message="Meeting is ready for chat.",
            )
            return {
                "meeting_id": meeting_id,
                "title": meeting_title,
                "status": "SKIPPED",
                "message": "Meeting already embedded",
            }

        IngestionStateService.mark_status(
            meeting_id,
            "PROCESSING",
            meeting_title=meeting_title,
            stage="discover",
            message="Discovering meeting resources.",
        )

        IngestionStateService.mark_status(
            meeting_id,
            "PROCESSING",
            meeting_title=meeting_title,
            stage="download",
            message="Downloading transcript or recording.",
        )

        if meeting.get("onedrive_item"):
            transcript, source_type = IngestionService._load_transcript_from_onedrive_item(
                access_token,
                meeting["onedrive_item"],
            )
        else:
            transcript, source_type = IngestionService._load_transcript_for_meeting(
                access_token,
                meeting,
            )

        if not transcript:
            IngestionStateService.mark_status(
                meeting_id,
                "NO_TRANSCRIPT",
                meeting_title=meeting_title,
                stage="failed",
                message="No transcript or transcribable recording found.",
            )
            raise HTTPException(
                status_code=404,
                detail="No transcript or transcribable recording found for this meeting",
            )

        storage_result = IngestionService._store_transcript(
            transcript=transcript,
            meeting_id=meeting_id,
            meeting_title=meeting_title,
            source_type=source_type,
            report_progress=True,
        )

        if storage_result.get("cancelled"):
            IngestionStateService.clear_cancel(meeting_id)
            IngestionStateService.clear_status(meeting_id)
            return {
                "meeting_id": meeting_id,
                "title": meeting_title,
                "status": "CANCELLED",
                "message": "Meeting preparation was cancelled.",
            }

        IngestionStateService.mark_status(
            meeting_id,
            "EMBEDDED",
            meeting_title=meeting_title,
            source_type=source_type,
            stage="ready",
            transcript_turns=len(transcript),
            chunks=storage_result.get("chunks", 0),
            stored_chunks=storage_result.get("stored_chunks", 0),
            message="Meeting is ready for chat.",
        )

        return {
            "meeting_id": meeting_id,
            "title": meeting_title,
            "status": "EMBEDDED",
            "source_type": source_type,
            "transcript_turns": len(transcript),
            "chunks": storage_result.get("chunks", 0),
            **storage_result,
        }

    @staticmethod
    def _update_workspace_sync_progress(
        *,
        processed: int,
        total: int,
        current_item: str | None = None,
    ) -> None:
        label = current_item or "recordings"
        IngestionStateService.mark_workspace_sync(
            "RUNNING",
            processed=processed,
            total=total,
            current_item=current_item,
            message=f"Syncing {processed + 1}/{total}: {label}",
        )

    @staticmethod
    def ingest_recent_meetings(
        access_token: str,
        limit: int = 20,
        *,
        fast: bool = True,
    ) -> dict:
        IngestionStateService.mark_workspace_sync(
            "RUNNING",
            requested=limit,
            processed=0,
            total=0,
            message="Discovering meetings with available recordings...",
        )

        results = []
        meetings = MeetingService.get_recent_meetings(access_token, limit=limit)
        graph_recordings = IngestionService.discover_graph_recordings(
            access_token,
            limit=limit,
            meetings=meetings,
            max_workers=6 if fast else 3,
        )

        if fast:
            discovered_assets = OneDriveService.find_recent_recording_assets_fast(
                access_token,
                limit=limit,
                meeting_titles=[meeting.get("title") or "" for meeting in meetings],
            )
        else:
            discovered_assets = OneDriveService.find_recent_recording_assets(
                access_token,
                limit=limit,
                meeting_titles=[meeting.get("title") or "" for meeting in meetings],
            )

        drive_items = [
            *discovered_assets.get("transcripts", []),
            *discovered_assets.get("videos", []),
        ]
        work_queue: list[tuple[str, object]] = [
            ("graph", recording_summary) for recording_summary in graph_recordings
        ] + [("drive", drive_item) for drive_item in drive_items]
        total_items = len(work_queue)

        IngestionStateService.mark_workspace_sync(
            "RUNNING",
            requested=limit,
            processed=0,
            total=total_items,
            discovered=len(graph_recordings) + len(drive_items),
            message=(
                f"Found {total_items} recording(s). Starting ingestion..."
                if total_items
                else "No recordings found to ingest."
            ),
        )

        for index, (item_type, payload) in enumerate(work_queue):
            if item_type == "graph":
                recording_summary = payload
                current_label = recording_summary.get("meeting_title") or "Teams recording"
                IngestionService._update_workspace_sync_progress(
                    processed=index,
                    total=total_items,
                    current_item=current_label,
                )
                try:
                    results.append(
                        IngestionService.ingest_graph_recording(
                            access_token=access_token,
                            recording_summary=recording_summary,
                        )
                    )
                except HTTPException as exc:
                    status = (
                        "SKIPPED"
                        if IngestionService._is_untranscribable_media_error(exc.detail)
                        else "FAILED"
                    )
                    IngestionStateService.mark_status(
                        recording_summary["asset_id"],
                        status,
                        meeting_title=recording_summary.get("meeting_title") or "Teams recording",
                        source_type="graph_recording",
                        error_detail=exc.detail,
                        message=IngestionService._status_message_for_exception(exc.detail),
                    )
                    results.append({
                        "meeting_id": recording_summary["asset_id"],
                        "title": recording_summary.get("meeting_title"),
                        "status": status,
                        "skip_reason": "untranscribable_media" if status == "SKIPPED" else None,
                        "detail": exc.detail,
                    })
                continue

            drive_item = payload
            current_label = drive_item.get("name") or "SharePoint recording"
            IngestionService._update_workspace_sync_progress(
                processed=index,
                total=total_items,
                current_item=current_label,
            )
            try:
                results.append(
                    IngestionService.ingest_drive_item(
                        access_token=access_token,
                        drive_item=drive_item,
                    )
                )
            except HTTPException as exc:
                asset_id = IngestionService._drive_asset_id(drive_item)
                status = (
                    "SKIPPED"
                    if IngestionService._is_untranscribable_media_error(exc.detail)
                    else "FAILED"
                )
                IngestionStateService.mark_status(
                    asset_id,
                    status,
                    meeting_title=drive_item.get("name") or "SharePoint recording",
                    source_type="sharepoint_asset",
                    error_detail=exc.detail,
                    message=IngestionService._status_message_for_exception(exc.detail),
                )
                results.append({
                    "meeting_id": asset_id,
                    "title": drive_item.get("name"),
                    "status": status,
                    "skip_reason": "untranscribable_media" if status == "SKIPPED" else None,
                    "detail": exc.detail,
                })
            except Exception as exc:  # pragma: no cover - protects long background sync jobs
                asset_id = IngestionService._drive_asset_id(drive_item)
                IngestionStateService.mark_status(
                    asset_id,
                    "FAILED",
                    meeting_title=drive_item.get("name") or "SharePoint recording",
                    source_type="sharepoint_asset",
                    error_detail=str(exc),
                    message=(
                        "SharePoint asset ingestion failed. Other recordings will continue. "
                        f"Error: {exc}"
                    ),
                )
                results.append({
                    "meeting_id": asset_id,
                    "title": drive_item.get("name"),
                    "status": "FAILED",
                    "detail": str(exc),
                })

        summary = {
            "requested": limit,
            "processed": len(results),
            "results": results,
        }
        discovered_count = len([
            *graph_recordings,
            *discovered_assets.get("transcripts", []),
            *discovered_assets.get("videos", []),
        ])

        embedded_count = sum(1 for item in results if item.get("status") == "EMBEDDED")
        existing_count = sum(
            1
            for item in results
            if item.get("status") == "SKIPPED"
            and IngestionService._is_existing_index_result(item)
        )
        ignored_count = sum(
            1
            for item in results
            if item.get("status") == "SKIPPED"
            and item.get("skip_reason") == "untranscribable_media"
        )
        skipped_count = sum(1 for item in results if item.get("status") == "SKIPPED")
        failed_count = sum(1 for item in results if item.get("status") == "FAILED")

        IngestionStateService.mark_workspace_sync(
            "COMPLETED",
            requested=limit,
            processed=len(results),
            discovered=discovered_count,
            embedded=embedded_count,
            already_indexed=existing_count,
            ignored=ignored_count,
            skipped=skipped_count,
            failed=failed_count,
            message=(
                f"Workspace sync finished. Found {discovered_count} recorded asset(s). "
                f"Embedded {embedded_count} new item(s), "
                f"reused {existing_count} already indexed item(s), "
                f"ignored {ignored_count} non-transcribable item(s), "
                f"failed {failed_count}."
            ),
        )

        return summary

    @staticmethod
    def ingest_graph_recording(access_token: str, recording_summary: dict) -> dict:
        asset_id = recording_summary["asset_id"]
        title = recording_summary.get("meeting_title") or recording_summary.get("recording_id") or "Teams recording"

        if (
            IngestionStateService.is_processed(asset_id)
            or ChromaService.has_meeting_embeddings(asset_id)
        ):
            IngestionStateService.mark_status(
                asset_id,
                "EMBEDDED",
                meeting_title=title,
                source_type="graph_recording_existing_index",
                message="Graph recording was already indexed earlier.",
            )
            return {
                "meeting_id": asset_id,
                "title": title,
                "status": "SKIPPED",
                "source_type": "graph_recording_existing_index",
                "skip_reason": "already_indexed",
                "message": "Graph recording already embedded",
            }

        IngestionStateService.mark_status(
            asset_id,
            "PROCESSING",
            meeting_title=title,
            source_type="graph_recording_transcription",
            recording_id=recording_summary.get("recording_id"),
            online_meeting_id=recording_summary.get("online_meeting_id"),
            message="Downloading Teams recording from Microsoft Graph and extracting audio.",
        )

        transcript = RecordingService.transcribe_online_meeting_recording(
            access_token,
            recording_summary["recording"],
        )
        if not transcript:
            IngestionStateService.mark_status(
                asset_id,
                "NO_TRANSCRIPT",
                meeting_title=title,
                source_type="graph_recording_transcription",
                message="No transcript could be generated from this Teams recording.",
            )
            raise HTTPException(
                status_code=422,
                detail="No transcript could be generated from this Teams recording.",
            )

        storage_result = IngestionService._store_transcript(
            transcript=transcript,
            meeting_id=asset_id,
            meeting_title=title,
            source_type="graph_recording_transcription",
        )

        IngestionStateService.mark_status(
            asset_id,
            "EMBEDDED",
            meeting_title=title,
            source_type="graph_recording_transcription",
            recording_id=recording_summary.get("recording_id"),
            online_meeting_id=recording_summary.get("online_meeting_id"),
            transcript_turns=len(transcript),
            chunks=storage_result.get("chunks", 0),
            stored_chunks=storage_result.get("stored_chunks", 0),
            message=f"Teams recording embedded successfully. {storage_result.get('stored_chunks', 0)} chunk(s) indexed.",
        )

        return {
            "meeting_id": asset_id,
            "title": title,
            "status": "EMBEDDED",
            "source_type": "graph_recording_transcription",
            "transcript_turns": len(transcript),
            "chunks": storage_result.get("chunks", 0),
            **storage_result,
        }

    @staticmethod
    def ingest_drive_item(access_token: str, drive_item: dict) -> dict:
        asset_id = IngestionService._drive_asset_id(drive_item)
        title = drive_item.get("name") or "SharePoint recording"

        if (
            IngestionStateService.is_processed(asset_id)
            or ChromaService.has_meeting_embeddings(asset_id)
        ):
            IngestionStateService.mark_status(
                asset_id,
                "EMBEDDED",
                meeting_title=title,
                source_type="sharepoint_existing_index",
                web_url=drive_item.get("webUrl"),
                message="SharePoint item was already indexed earlier.",
            )
            return {
                "meeting_id": asset_id,
                "title": title,
                "status": "SKIPPED",
                "source_type": "sharepoint_existing_index",
                "skip_reason": "already_indexed",
                "message": "SharePoint item already embedded",
            }

        if IngestionStateService.has_status(asset_id, "QUEUED"):
            status = IngestionStateService.get_status(asset_id)
            return {
                "meeting_id": asset_id,
                "title": title,
                "status": status.get("status"),
                "source_type": status.get("source_type"),
                "skip_reason": "already_processing",
                "message": status.get("message") or "SharePoint item is already processing.",
            }

        source_type = (
            "sharepoint_transcript"
            if IngestionService._is_transcript_drive_item(drive_item)
            else "sharepoint_recording_transcription"
        )
        IngestionStateService.mark_status(
            asset_id,
            "PROCESSING",
            meeting_title=title,
            source_type=source_type,
            web_url=drive_item.get("webUrl"),
            message=(
                "Reading SharePoint recording. Large files may take several minutes "
                "to download and transcribe before embeddings appear."
            ),
        )

        if IngestionService._is_transcript_drive_item(drive_item):
            transcript = OneDriveService.transcript_from_drive_item(access_token, drive_item)
        elif IngestionService._is_media_drive_item(drive_item):
            transcript = RecordingService.transcribe_drive_item(access_token, drive_item)
        else:
            transcript = []

        if not transcript:
            IngestionStateService.mark_status(
                asset_id,
                "NO_TRANSCRIPT",
                meeting_title=title,
                source_type=source_type,
                web_url=drive_item.get("webUrl"),
                message="No transcript could be generated from this SharePoint item.",
            )
            raise HTTPException(
                status_code=422,
                detail="No transcript could be generated from this SharePoint item.",
            )

        storage_result = IngestionService._store_transcript(
            transcript=transcript,
            meeting_id=asset_id,
            meeting_title=title,
            source_type=source_type,
        )

        IngestionStateService.mark_status(
            asset_id,
            "EMBEDDED",
            meeting_title=title,
            source_type=source_type,
            web_url=drive_item.get("webUrl"),
            transcript_turns=len(transcript),
            chunks=storage_result.get("chunks", 0),
            stored_chunks=storage_result.get("stored_chunks", 0),
            message=(
                f"SharePoint item embedded successfully. "
                f"{storage_result.get('stored_chunks', 0)} chunk(s) indexed."
            ),
        )

        return {
            "meeting_id": asset_id,
            "title": title,
            "status": "EMBEDDED",
            "source_type": source_type,
            "transcript_turns": len(transcript),
            "chunks": storage_result.get("chunks", 0),
            **storage_result,
        }

    @staticmethod
    def _is_transcript_drive_item(drive_item: dict) -> bool:
        title = drive_item.get("name") or ""
        extension = os.path.splitext(title)[1].lower()
        return extension in IngestionService._transcript_extensions

    @staticmethod
    def _is_media_drive_item(drive_item: dict) -> bool:
        title = drive_item.get("name") or ""
        extension = os.path.splitext(title)[1].lower()
        mime_type = ((drive_item.get("file") or {}).get("mimeType") or "").lower()

        return (
            extension in IngestionService._video_extensions
            or mime_type.startswith("video/")
            or mime_type.startswith("audio/")
        )

    @staticmethod
    def _drive_asset_id(drive_item: dict) -> str:
        parent_reference = drive_item.get("parentReference") or {}
        stable_key = (
            f"{parent_reference.get('driveId')}:{drive_item.get('id')}"
            if drive_item.get("id")
            else drive_item.get("webUrl") or drive_item.get("name") or "sharepoint-asset"
        )
        digest = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:16]
        return f"sharepoint-{digest}"

    @staticmethod
    def _drive_item_summary(drive_item: dict) -> dict:
        parent_reference = drive_item.get("parentReference") or {}
        return {
            "asset_id": IngestionService._drive_asset_id(drive_item),
            "id": drive_item.get("id"),
            "name": drive_item.get("name"),
            "webUrl": drive_item.get("webUrl"),
            "driveId": parent_reference.get("driveId"),
            "mimeType": (drive_item.get("file") or {}).get("mimeType"),
            "size": drive_item.get("size"),
            "lastModifiedDateTime": drive_item.get("lastModifiedDateTime"),
            "createdDateTime": drive_item.get("createdDateTime"),
        }

    @staticmethod
    def _graph_recording_summary(
        meeting: dict,
        online_meeting_id: str,
        recording: dict,
    ) -> dict:
        stable_key = (
            recording.get("id")
            or recording.get("recordingContentUrl")
            or f"{online_meeting_id}:{meeting.get('event_id')}"
        )
        digest = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:16]
        return {
            "asset_id": f"graph-recording-{digest}",
            "meeting_id": meeting.get("event_id"),
            "meeting_title": meeting.get("title"),
            "online_meeting_id": online_meeting_id,
            "recording_id": recording.get("id"),
            "createdDateTime": recording.get("createdDateTime"),
            "endDateTime": recording.get("endDateTime"),
            "contentCorrelationId": recording.get("contentCorrelationId"),
            "recordingContentUrl": recording.get("recordingContentUrl"),
            "recording": recording,
        }

    @staticmethod
    def _status_message_for_exception(detail) -> str:
        if isinstance(detail, str):
            return detail

        if isinstance(detail, dict):
            return detail.get("message") or detail.get("error") or "Ingestion failed."

        return "Ingestion failed."

    @staticmethod
    def _is_untranscribable_media_error(detail) -> bool:
        message = IngestionService._status_message_for_exception(detail).lower()
        return any(
            text in message
            for text in [
                "does not contain an audio stream",
                "decoded to zero samples",
                "downloaded an html page",
                "does not look like audio or video",
                "empty or too small",
            ]
        )

    @staticmethod
    def _is_existing_index_result(result: dict) -> bool:
        if result.get("skip_reason") == "already_indexed":
            return True

        source_type = result.get("source_type") or ""
        message = (result.get("message") or "").lower()
        return "existing_index" in source_type or "already embedded" in message

    @staticmethod
    def start_workspace_sync(access_token: str, limit: int = 20) -> dict:
        with IngestionService._sync_lock:
            if (
                IngestionService._sync_thread
                and IngestionService._sync_thread.is_alive()
            ):
                return {
                    "status": "RUNNING",
                    "message": "Workspace sync is already running.",
                    "limit": limit,
                }

            IngestionStateService.mark_workspace_sync(
                "QUEUED",
                requested=limit,
                message="Workspace sync queued.",
            )

            def run_sync() -> None:
                try:
                    IngestionService.ingest_recent_meetings(
                        access_token,
                        limit=limit,
                        fast=True,
                    )
                except HTTPException as exc:
                    IngestionStateService.mark_workspace_sync(
                        "FAILED",
                        requested=limit,
                        error_detail=exc.detail,
                        message="Workspace sync failed while calling Microsoft Graph.",
                    )
                except Exception as exc:  # pragma: no cover - safety net for background worker
                    IngestionStateService.mark_workspace_sync(
                        "FAILED",
                        requested=limit,
                        error_detail=str(exc),
                        message="Workspace sync failed unexpectedly.",
                    )

            IngestionService._sync_thread = Thread(target=run_sync, daemon=True)
            IngestionService._sync_thread.start()

        return {
            "status": "QUEUED",
            "message": "Workspace sync started in the background.",
            "limit": limit,
        }

    @staticmethod
    def _store_transcript(
        *,
        transcript: list[dict],
        meeting_id: str,
        meeting_title: str,
        source_type: str,
        report_progress: bool = False,
    ) -> dict:
        if report_progress:
            IngestionStateService.mark_status(
                meeting_id,
                "PROCESSING",
                meeting_title=meeting_title,
                stage="transcribe",
                message="Normalizing transcript.",
            )
            IngestionStateService.mark_status(
                meeting_id,
                "PROCESSING",
                meeting_title=meeting_title,
                stage="chunk",
                message="Chunking transcript for search.",
            )

        chunks = ChunkService.chunk_transcript(
            transcript,
            meeting_id=meeting_id,
            meeting_title=meeting_title,
            source_type=source_type,
        )

        if report_progress:
            IngestionStateService.mark_status(
                meeting_id,
                "PROCESSING",
                meeting_title=meeting_title,
                stage="embed",
                message="Generating embeddings.",
            )

        embedded_chunks = EmbeddingService.generate_embeddings(chunks)
        if IngestionStateService.is_cancelled(meeting_id):
            return {
                "message": "Ingestion cancelled before storage",
                "stored_chunks": 0,
                "chunks": len(chunks),
                "cancelled": True,
            }

        storage_result = ChromaService.store_embeddings(embedded_chunks)
        return {
            **storage_result,
            "chunks": len(chunks),
        }

    @staticmethod
    def _load_transcript_for_meeting(access_token: str, meeting: dict) -> tuple[list[dict], str]:
        resolved = None
        try:
            resolved = MeetingService.resolve_online_meeting(access_token, meeting)
        except HTTPException as exc:
            if exc.status_code not in {401, 403, 404}:
                raise

        if resolved:
            try:
                transcript = IngestionService._load_graph_transcript(
                    access_token,
                    resolved["online_meeting_id"],
                    graph_user_id=resolved["graph_user_id"],
                )
            except HTTPException as exc:
                if exc.status_code not in {401, 403, 404}:
                    raise
                transcript = []

            if transcript:
                return transcript, "graph_transcript"

        assets = OneDriveService.find_meeting_assets(
            access_token,
            meeting.get("title") or "",
        )

        for transcript_file in assets["transcripts"]:
            transcript = OneDriveService.transcript_from_drive_item(
                access_token,
                transcript_file,
            )
            if transcript:
                return transcript, "onedrive_transcript"

        for video_file in assets["videos"]:
            transcript = RecordingService.transcribe_drive_item(access_token, video_file)
            if transcript:
                return transcript, "onedrive_video_transcription"

        return [], "none"

    @staticmethod
    def _merge_transcript_turns(turn_lists: list[list[dict]]) -> list[dict]:
        merged: list[dict] = []
        turn_offset = 0

        for turns in turn_lists:
            if not turns:
                continue

            for turn in turns:
                merged_turn = dict(turn)
                if "turn_id" in merged_turn:
                    merged_turn["turn_id"] = turn_offset + int(merged_turn["turn_id"])
                merged.append(merged_turn)

            turn_offset += len(turns)

        return merged

    @staticmethod
    def _load_graph_transcript(
        access_token: str,
        online_meeting_id: str,
        *,
        graph_user_id: str = "me",
    ) -> list[dict]:
        transcript_turn_lists: list[list[dict]] = []

        transcripts = TranscriptService.list_online_meeting_transcripts(
            access_token,
            online_meeting_id,
            user_id=graph_user_id,
        )
        for transcript in sorted(
            transcripts,
            key=lambda item: (
                item.get("createdDateTime") or "",
                item.get("endDateTime") or "",
                item.get("id") or "",
            ),
        ):
            transcript_id = transcript.get("id")
            if not transcript_id:
                continue

            vtt_text = TranscriptService.download_online_meeting_transcript(
                access_token,
                online_meeting_id,
                transcript_id,
                user_id=graph_user_id,
            )
            normalized = TranscriptService.normalize_transcript(vtt_text)
            if normalized:
                transcript_turn_lists.append(normalized)

        if transcript_turn_lists:
            return IngestionService._merge_transcript_turns(transcript_turn_lists)

        recordings = RecordingService.list_online_meeting_recordings(
            access_token,
            online_meeting_id,
            user_id=graph_user_id,
        )
        for recording in sorted(
            recordings,
            key=lambda item: (
                item.get("createdDateTime") or "",
                item.get("id") or "",
            ),
        ):
            try:
                turns = RecordingService.transcribe_online_meeting_recording(
                    access_token,
                    recording,
                )
            except HTTPException:
                continue

            if turns:
                transcript_turn_lists.append(turns)

        return IngestionService._merge_transcript_turns(transcript_turn_lists)
