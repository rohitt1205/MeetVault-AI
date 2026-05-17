import hashlib
import os
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
    _transcript_extensions = {".vtt", ".txt"}
    _video_extensions = {".mp4", ".m4a", ".mp3", ".wav", ".webm"}

    @staticmethod
    def discover_recording_assets(access_token: str, limit: int = 20) -> dict:
        meetings = MeetingService.get_recent_meetings(access_token, limit=limit)
        graph_recordings = IngestionService.discover_graph_recordings(
            access_token,
            limit=limit,
            meetings=meetings,
        )
        assets = OneDriveService.find_recent_recording_assets(
            access_token,
            limit=limit,
            meeting_titles=[meeting.get("title") or "" for meeting in meetings],
        )
        return {
            "limit": limit,
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
    ) -> list[dict]:
        recordings = []

        for meeting in meetings or MeetingService.get_recent_meetings(access_token, limit=limit):
            try:
                online_meeting_id = MeetingService.resolve_online_meeting_id(
                    access_token,
                    meeting,
                )
                if not online_meeting_id:
                    continue

                meeting_recordings = RecordingService.list_online_meeting_recordings(
                    access_token,
                    online_meeting_id,
                )
            except HTTPException as exc:
                if exc.status_code in {401, 403, 404}:
                    continue
                raise

            for recording in meeting_recordings:
                recordings.append(
                    IngestionService._graph_recording_summary(
                        meeting,
                        online_meeting_id,
                        recording,
                    )
                )

            if len(recordings) >= limit:
                break

        return recordings[:limit]

    @staticmethod
    def ingest_meeting(access_token: str, event_id: str) -> dict:
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
        )

        transcript, source_type = IngestionService._load_transcript_for_meeting(
            access_token,
            meeting,
        )

        if not transcript:
            IngestionStateService.mark_status(
                meeting_id,
                "NO_TRANSCRIPT",
                meeting_title=meeting_title,
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
        )

        IngestionStateService.mark_status(
            meeting_id,
            "EMBEDDED",
            meeting_title=meeting_title,
            source_type=source_type,
            transcript_turns=len(transcript),
            chunks=storage_result.get("chunks", 0),
            stored_chunks=storage_result.get("stored_chunks", 0),
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
    def ingest_recent_meetings(access_token: str, limit: int = 20) -> dict:
        IngestionStateService.mark_workspace_sync(
            "RUNNING",
            requested=limit,
            message=(
                "Syncing recorded SharePoint/OneDrive meeting assets into ChromaDB."
            ),
        )

        results = []
        meetings = MeetingService.get_recent_meetings(access_token, limit=limit)
        graph_recordings = IngestionService.discover_graph_recordings(
            access_token,
            limit=limit,
            meetings=meetings,
        )

        for recording_summary in graph_recordings:
            try:
                results.append(
                    IngestionService.ingest_graph_recording(
                        access_token=access_token,
                        recording_summary=recording_summary,
                    )
                )
            except HTTPException as exc:
                status = "SKIPPED" if IngestionService._is_untranscribable_media_error(exc.detail) else "FAILED"
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

        discovered_assets = OneDriveService.find_recent_recording_assets(
            access_token,
            limit=limit,
            meeting_titles=[meeting.get("title") or "" for meeting in meetings],
        )
        for drive_item in [
            *discovered_assets.get("transcripts", []),
            *discovered_assets.get("videos", []),
        ]:
            try:
                results.append(
                    IngestionService.ingest_drive_item(
                        access_token=access_token,
                        drive_item=drive_item,
                    )
                )
            except HTTPException as exc:
                asset_id = IngestionService._drive_asset_id(drive_item)
                status = "SKIPPED" if IngestionService._is_untranscribable_media_error(exc.detail) else "FAILED"
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
                    IngestionService.ingest_recent_meetings(access_token, limit=limit)
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
    ) -> dict:
        chunks = ChunkService.chunk_transcript(
            transcript,
            meeting_id=meeting_id,
            meeting_title=meeting_title,
            source_type=source_type,
        )
        embedded_chunks = EmbeddingService.generate_embeddings(chunks)
        storage_result = ChromaService.store_embeddings(embedded_chunks)
        return {
            **storage_result,
            "chunks": len(chunks),
        }

    @staticmethod
    def _load_transcript_for_meeting(access_token: str, meeting: dict) -> tuple[list[dict], str]:
        try:
            online_meeting_id = MeetingService.resolve_online_meeting_id(access_token, meeting)
        except HTTPException as exc:
            if exc.status_code not in {401, 403, 404}:
                raise
            online_meeting_id = None

        if online_meeting_id:
            try:
                transcript = IngestionService._load_graph_transcript(
                    access_token,
                    online_meeting_id,
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
    def _load_graph_transcript(access_token: str, online_meeting_id: str) -> list[dict]:
        transcripts = TranscriptService.list_online_meeting_transcripts(
            access_token,
            online_meeting_id,
        )
        if not transcripts:
            return []

        latest_transcript = max(
            transcripts,
            key=lambda transcript: (
                transcript.get("createdDateTime") or "",
                transcript.get("endDateTime") or "",
                transcript.get("id") or "",
            ),
        )
        transcript_id = latest_transcript.get("id")
        if not transcript_id:
            return []

        vtt_text = TranscriptService.download_online_meeting_transcript(
            access_token,
            online_meeting_id,
            transcript_id,
        )

        return TranscriptService.normalize_transcript(vtt_text)
