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
    @staticmethod
    def ingest_meeting(access_token: str, event_id: str) -> dict:
        meeting = MeetingService.get_meeting_event(access_token, event_id)
        meeting_id = meeting.get("event_id") or event_id
        meeting_title = meeting.get("title") or "Untitled meeting"

        if IngestionStateService.is_processed(meeting_id):
            return {
                "meeting_id": meeting_id,
                "title": meeting_title,
                "status": "SKIPPED",
                "message": "Meeting already embedded",
            }

        IngestionStateService.mark_status(meeting_id, "PROCESSING")

        transcript, source_type = IngestionService._load_transcript_for_meeting(
            access_token,
            meeting,
        )

        if not transcript:
            IngestionStateService.mark_status(meeting_id, "NO_TRANSCRIPT")
            raise HTTPException(
                status_code=404,
                detail="No transcript or transcribable recording found for this meeting",
            )

        chunks = ChunkService.chunk_transcript(
            transcript,
            meeting_id=meeting_id,
            meeting_title=meeting_title,
            source_type=source_type,
        )
        embedded_chunks = EmbeddingService.generate_embeddings(chunks)
        storage_result = ChromaService.store_embeddings(embedded_chunks)

        IngestionStateService.mark_status(meeting_id, "EMBEDDED")

        return {
            "meeting_id": meeting_id,
            "title": meeting_title,
            "status": "EMBEDDED",
            "source_type": source_type,
            "transcript_turns": len(transcript),
            "chunks": len(chunks),
            **storage_result,
        }

    @staticmethod
    def ingest_recent_meetings(access_token: str, limit: int = 5) -> dict:
        meetings = MeetingService.get_recent_meetings(access_token, limit=limit)
        results = []

        for meeting in meetings:
            try:
                results.append(
                    IngestionService.ingest_meeting(
                        access_token=access_token,
                        event_id=meeting["event_id"],
                    )
                )
            except HTTPException as exc:
                results.append({
                    "meeting_id": meeting.get("event_id"),
                    "title": meeting.get("title"),
                    "status": "FAILED",
                    "detail": exc.detail,
                })

        return {
            "requested": limit,
            "processed": len(results),
            "results": results,
        }

    @staticmethod
    def _load_transcript_for_meeting(access_token: str, meeting: dict) -> tuple[list[dict], str]:
        online_meeting_id = MeetingService.resolve_online_meeting_id(access_token, meeting)
        if online_meeting_id:
            transcript = IngestionService._load_graph_transcript(
                access_token,
                online_meeting_id,
            )
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

        latest_transcript = transcripts[-1]
        transcript_id = latest_transcript.get("id")
        if not transcript_id:
            return []

        vtt_text = TranscriptService.download_online_meeting_transcript(
            access_token,
            online_meeting_id,
            transcript_id,
        )

        return TranscriptService.normalize_transcript(vtt_text)
