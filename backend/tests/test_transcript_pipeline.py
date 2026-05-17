import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.services.chunk_service import ChunkService
from app.services.ingestion_service import IngestionService
from app.services.transcript_service import TranscriptService


class TranscriptPipelineTests(unittest.TestCase):
    def test_parse_vtt_and_normalize_transcript(self):
        vtt_text = """WEBVTT

00:00:00.000 --> 00:00:03.000
<v Alex>Hello team</v>

00:00:03.000 --> 00:00:06.000
We are moving forward.
"""

        parsed = TranscriptService.parse_vtt(vtt_text)
        normalized = TranscriptService.normalize_transcript(parsed)

        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0]["speaker"], "Alex")
        self.assertEqual(normalized[0]["timestamp"], "00:00:00.000")
        self.assertEqual(normalized[0]["text"], "Hello team")
        self.assertEqual(normalized[1]["speaker"], "Unknown")
        self.assertEqual(normalized[1]["text"], "We are moving forward.")

    def test_normalize_transcript_falls_back_to_plain_text_lines(self):
        raw_text = """00:00:00.000 Narrator: This is a transcript parsing smoke test.
00:00:03.000 Narrator: Graph automation is working.
"""

        normalized = TranscriptService.normalize_transcript(raw_text)

        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0]["speaker"], "Narrator")
        self.assertEqual(normalized[0]["timestamp"], "00:00:00.000")
        self.assertEqual(
            normalized[0]["text"],
            "This is a transcript parsing smoke test.",
        )

    def test_chunk_transcript_uses_overlap_and_metadata(self):
        transcript = [
            {
                "turn_id": 1,
                "speaker": "Alex",
                "timestamp": "00:00:00.000",
                "end_timestamp": "00:00:01.000",
                "text": "alpha beta",
            },
            {
                "turn_id": 2,
                "speaker": "Blair",
                "timestamp": "00:00:01.000",
                "end_timestamp": "00:00:02.000",
                "text": "gamma delta",
            },
            {
                "turn_id": 3,
                "speaker": "Casey",
                "timestamp": "00:00:02.000",
                "end_timestamp": "00:00:03.000",
                "text": "epsilon zeta",
            },
        ]

        chunks = ChunkService.chunk_transcript(
            transcript,
            meeting_id="meeting-1",
            meeting_title="Weekly Sync",
            source_type="graph_transcript",
            max_words=4,
            overlap_turns=1,
        )

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["chunk_id"], "meeting-1:1")
        self.assertEqual(chunks[0]["metadata"]["turn_count"], 2)
        self.assertEqual(chunks[1]["metadata"]["turn_count"], 2)
        self.assertIn("gamma delta", chunks[1]["text"])
        self.assertIn("epsilon zeta", chunks[1]["text"])

    @patch("app.services.ingestion_service.IngestionService._load_transcript_for_meeting")
    @patch("app.services.ingestion_service.IngestionStateService.is_processed", return_value=False)
    @patch("app.services.ingestion_service.ChromaService.has_meeting_embeddings", return_value=False)
    @patch("app.services.ingestion_service.IngestionStateService.mark_status")
    @patch("app.services.ingestion_service.MeetingService.get_meeting_event")
    @patch("app.services.ingestion_service.ChunkService.chunk_transcript")
    @patch("app.services.ingestion_service.EmbeddingService.generate_embeddings")
    @patch("app.services.ingestion_service.ChromaService.store_embeddings")
    def test_ingest_meeting_pushes_embedded_chunks_to_chroma(
        self,
        mock_store_embeddings,
        mock_generate_embeddings,
        mock_chunk_transcript,
        mock_get_meeting_event,
        mock_mark_status,
        _mock_has_meeting_embeddings,
        _mock_is_processed,
        mock_load_transcript,
    ):
        mock_get_meeting_event.return_value = {
            "event_id": "event-1",
            "title": "Weekly Sync",
            "online_meeting_id": "online-1",
            "join_url": "https://teams.microsoft.com/l/meetup-join/abc",
        }
        mock_load_transcript.return_value = (
            [
                {
                    "turn_id": 1,
                    "speaker": "Alex",
                    "timestamp": "00:00:00.000",
                    "end_timestamp": "00:00:02.000",
                    "text": "hello world",
                }
            ],
            "graph_transcript",
        )
        mock_chunk_transcript.return_value = [
            {
                "chunk_id": "event-1:1",
                "chunk_index": 1,
                "meeting_id": "event-1",
                "meeting_title": "Weekly Sync",
                "source_type": "graph_transcript",
                "text": "00:00:00.000 Alex: hello world",
                "metadata": {
                    "speaker_start": "Alex",
                    "speaker_end": "Alex",
                    "start_timestamp": "00:00:00.000",
                    "end_timestamp": "00:00:02.000",
                    "turn_count": 1,
                },
            }
        ]
        mock_generate_embeddings.return_value = [
            {
                **mock_chunk_transcript.return_value[0],
                "embedding": [0.1, 0.2, 0.3],
            }
        ]
        mock_store_embeddings.return_value = {
            "message": "Embeddings stored successfully",
            "stored_chunks": 1,
        }

        result = IngestionService.ingest_meeting("access-token", "event-1")

        self.assertEqual(result["status"], "EMBEDDED")
        self.assertEqual(result["meeting_id"], "event-1")
        self.assertEqual(result["chunks"], 1)
        self.assertEqual(result["transcript_turns"], 1)
        mock_mark_status.assert_any_call(
            "event-1",
            "PROCESSING",
            meeting_title="Weekly Sync",
        )
        mock_mark_status.assert_any_call(
            "event-1",
            "EMBEDDED",
            meeting_title="Weekly Sync",
            source_type="graph_transcript",
            transcript_turns=1,
            chunks=1,
            stored_chunks=1,
        )

    @patch("app.services.ingestion_service.IngestionService._load_transcript_for_meeting", return_value=([], "none"))
    @patch("app.services.ingestion_service.IngestionStateService.is_processed", return_value=False)
    @patch("app.services.ingestion_service.ChromaService.has_meeting_embeddings", return_value=False)
    @patch("app.services.ingestion_service.IngestionStateService.mark_status")
    @patch("app.services.ingestion_service.MeetingService.get_meeting_event")
    def test_ingest_meeting_raises_when_no_transcript_is_found(
        self,
        mock_get_meeting_event,
        mock_mark_status,
        _mock_has_meeting_embeddings,
        _mock_is_processed,
        _mock_load_transcript,
    ):
        mock_get_meeting_event.return_value = {
            "event_id": "event-1",
            "title": "Weekly Sync",
            "online_meeting_id": "online-1",
            "join_url": "https://teams.microsoft.com/l/meetup-join/abc",
        }

        with self.assertRaises(HTTPException) as ctx:
            IngestionService.ingest_meeting("access-token", "event-1")

        self.assertEqual(ctx.exception.status_code, 404)
        mock_mark_status.assert_any_call(
            "event-1",
            "PROCESSING",
            meeting_title="Weekly Sync",
        )
        mock_mark_status.assert_any_call(
            "event-1",
            "NO_TRANSCRIPT",
            meeting_title="Weekly Sync",
        )

    @patch("app.services.ingestion_service.TranscriptService.list_online_meeting_transcripts")
    @patch("app.services.ingestion_service.TranscriptService.download_online_meeting_transcript")
    @patch("app.services.ingestion_service.TranscriptService.normalize_transcript")
    def test_load_graph_transcript_chooses_latest_transcript_by_timestamp(
        self,
        mock_normalize_transcript,
        mock_download_transcript,
        mock_list_transcripts,
    ):
        mock_list_transcripts.return_value = [
            {
                "id": "transcript-old",
                "createdDateTime": "2024-01-01T10:00:00Z",
                "endDateTime": "2024-01-01T10:10:00Z",
            },
            {
                "id": "transcript-new",
                "createdDateTime": "2024-02-01T10:00:00Z",
                "endDateTime": "2024-02-01T10:10:00Z",
            },
        ]
        mock_normalize_transcript.return_value = [{"text": "latest"}]

        result = IngestionService._load_graph_transcript("access-token", "online-1")

        self.assertEqual(result, [{"text": "latest"}])
        mock_download_transcript.assert_called_once()
        called_args = mock_download_transcript.call_args.args
        self.assertEqual(called_args[2], "transcript-new")

    @patch("app.services.ingestion_service.IngestionService._load_graph_transcript", side_effect=HTTPException(status_code=403, detail="Forbidden"))
    @patch("app.services.ingestion_service.OneDriveService.find_meeting_assets")
    @patch("app.services.ingestion_service.RecordingService.transcribe_drive_item")
    @patch("app.services.ingestion_service.MeetingService.resolve_online_meeting_id", return_value="online-1")
    def test_load_transcript_for_meeting_falls_back_when_transcript_access_is_forbidden(
        self,
        mock_resolve_online_meeting_id,
        mock_transcribe_drive_item,
        mock_find_meeting_assets,
        _mock_load_graph_transcript,
    ):
        mock_find_meeting_assets.return_value = {
            "transcripts": [],
            "videos": [
                {
                    "id": "video-1",
                    "name": "Weekly Sync.mp4",
                }
            ],
        }
        mock_transcribe_drive_item.return_value = [
            {
                "turn_id": 1,
                "speaker": "Unknown",
                "timestamp": "00:00:00.000",
                "end_timestamp": "00:00:02.000",
                "text": "fallback transcript",
            }
        ]

        transcript, source_type = IngestionService._load_transcript_for_meeting(
            "access-token",
            {"title": "Weekly Sync"},
        )

        self.assertEqual(source_type, "onedrive_video_transcription")
        self.assertEqual(transcript[0]["text"], "fallback transcript")
        mock_resolve_online_meeting_id.assert_called_once()
        mock_find_meeting_assets.assert_called_once()

    @patch("app.services.ingestion_service.IngestionStateService.is_processed", return_value=False)
    @patch("app.services.ingestion_service.ChromaService.has_meeting_embeddings", return_value=False)
    @patch("app.services.ingestion_service.IngestionService._store_transcript")
    @patch("app.services.ingestion_service.RecordingService.transcribe_drive_item")
    def test_ingest_drive_item_transcribes_sharepoint_video_and_stores_embeddings(
        self,
        mock_transcribe_drive_item,
        mock_store_transcript,
        _mock_has_meeting_embeddings,
        _mock_is_processed,
    ):
        mock_transcribe_drive_item.return_value = [
            {
                "turn_id": 1,
                "speaker": "Unknown",
                "timestamp": "00:00:01.000",
                "text": "sharepoint recording transcript",
            }
        ]
        mock_store_transcript.return_value = {
            "stored_chunks": 1,
            "chunks": 1,
        }

        result = IngestionService.ingest_drive_item(
            "access-token",
            {
                "id": "video-1",
                "name": "SharePoint Recording.mp4",
                "parentReference": {"driveId": "drive-1"},
            },
        )

        self.assertEqual(result["status"], "EMBEDDED")
        self.assertEqual(result["source_type"], "sharepoint_recording_transcription")
        mock_transcribe_drive_item.assert_called_once()
        mock_store_transcript.assert_called_once()

    @patch("app.services.ingestion_service.IngestionStateService.is_processed", return_value=False)
    @patch("app.services.ingestion_service.ChromaService.has_meeting_embeddings", return_value=False)
    @patch("app.services.ingestion_service.IngestionService._store_transcript")
    @patch("app.services.ingestion_service.RecordingService.transcribe_drive_item")
    def test_ingest_drive_item_transcribes_video_mime_without_extension(
        self,
        mock_transcribe_drive_item,
        mock_store_transcript,
        _mock_has_meeting_embeddings,
        _mock_is_processed,
    ):
        mock_transcribe_drive_item.return_value = [
            {
                "turn_id": 1,
                "speaker": "Unknown",
                "timestamp": "00:00:01.000",
                "text": "teams card recording transcript",
            }
        ]
        mock_store_transcript.return_value = {
            "stored_chunks": 1,
            "chunks": 1,
        }

        result = IngestionService.ingest_drive_item(
            "access-token",
            {
                "id": "video-1",
                "name": "LWC Training",
                "file": {"mimeType": "video/mp4"},
                "parentReference": {"driveId": "drive-1"},
            },
        )

        self.assertEqual(result["status"], "EMBEDDED")
        self.assertEqual(result["source_type"], "sharepoint_recording_transcription")
        mock_transcribe_drive_item.assert_called_once()

    @patch("app.services.ingestion_service.MeetingService.get_recent_meetings")
    @patch("app.services.ingestion_service.IngestionService.ingest_drive_item")
    @patch("app.services.ingestion_service.OneDriveService.find_recent_recording_assets")
    @patch("app.services.ingestion_service.IngestionService.discover_graph_recordings")
    def test_ingest_recent_meetings_processes_recorded_assets_without_calendar_failures(
        self,
        mock_discover_graph_recordings,
        mock_find_recent_recording_assets,
        mock_ingest_drive_item,
        mock_get_recent_meetings,
    ):
        mock_get_recent_meetings.return_value = [
            {"event_id": "meeting-1", "title": "LWC Training"}
        ]
        mock_discover_graph_recordings.return_value = []
        mock_find_recent_recording_assets.return_value = {
            "transcripts": [],
            "videos": [{"id": "video-1", "name": "Recorded Meeting.mp4"}],
        }
        mock_ingest_drive_item.side_effect = RuntimeError("tuple index out of range")

        result = IngestionService.ingest_recent_meetings("access-token", limit=5)

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["results"][0]["status"], "FAILED")
        mock_get_recent_meetings.assert_called_once()
        mock_find_recent_recording_assets.assert_called_once_with(
            "access-token",
            limit=5,
            meeting_titles=["LWC Training"],
        )

    @patch("app.services.ingestion_service.IngestionStateService.is_processed", return_value=False)
    @patch("app.services.ingestion_service.ChromaService.has_meeting_embeddings", return_value=False)
    @patch("app.services.ingestion_service.IngestionService._store_transcript")
    @patch("app.services.ingestion_service.RecordingService.transcribe_online_meeting_recording")
    def test_ingest_graph_recording_transcribes_and_stores_embeddings(
        self,
        mock_transcribe_online_meeting_recording,
        mock_store_transcript,
        _mock_has_meeting_embeddings,
        _mock_is_processed,
    ):
        mock_transcribe_online_meeting_recording.return_value = [
            {
                "turn_id": 1,
                "speaker": "Unknown",
                "timestamp": "00:00:01.000",
                "text": "teams recording transcript",
            }
        ]
        mock_store_transcript.return_value = {
            "stored_chunks": 1,
            "chunks": 1,
        }

        result = IngestionService.ingest_graph_recording(
            "access-token",
            {
                "asset_id": "graph-recording-1",
                "meeting_title": "Recorded Teams Meeting",
                "online_meeting_id": "online-1",
                "recording_id": "recording-1",
                "recording": {
                    "id": "recording-1",
                    "recordingContentUrl": "https://graph.microsoft.com/v1.0/me/onlineMeetings/online-1/recordings/recording-1/content",
                },
            },
        )

        self.assertEqual(result["status"], "EMBEDDED")
        self.assertEqual(result["source_type"], "graph_recording_transcription")
        mock_transcribe_online_meeting_recording.assert_called_once()
        mock_store_transcript.assert_called_once()

    @patch("app.services.ingestion_service.IngestionService.ingest_drive_item")
    @patch("app.services.ingestion_service.OneDriveService.find_recent_recording_assets")
    @patch("app.services.ingestion_service.IngestionService.ingest_graph_recording")
    @patch("app.services.ingestion_service.IngestionService.discover_graph_recordings")
    @patch("app.services.ingestion_service.MeetingService.get_recent_meetings")
    def test_ingest_recent_meetings_skips_untranscribable_recordings(
        self,
        mock_get_recent_meetings,
        mock_discover_graph_recordings,
        mock_ingest_graph_recording,
        mock_find_recent_recording_assets,
        _mock_ingest_drive_item,
    ):
        mock_get_recent_meetings.return_value = [
            {"event_id": "meeting-1", "title": "No Audio Meeting"}
        ]
        mock_discover_graph_recordings.return_value = [
            {
                "asset_id": "graph-recording-1",
                "meeting_title": "No Audio Meeting",
                "recording": {"id": "recording-1"},
            }
        ]
        mock_ingest_graph_recording.side_effect = HTTPException(
            status_code=422,
            detail={"message": "Recording does not contain an audio stream to transcribe."},
        )
        mock_find_recent_recording_assets.return_value = {"transcripts": [], "videos": []}

        result = IngestionService.ingest_recent_meetings("access-token", limit=20)

        self.assertEqual(result["results"][0]["status"], "SKIPPED")
        self.assertEqual(result["results"][0]["skip_reason"], "untranscribable_media")


if __name__ == "__main__":
    unittest.main()
