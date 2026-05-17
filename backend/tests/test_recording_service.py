import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.services.recording_service import RecordingService


class _FakeSegment:
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text


class _FakeModel:
    def __init__(self):
        self.transcribed_paths = []

    def transcribe(self, path):
        if not os.path.exists(path):
            raise AssertionError("temporary recording file was not created before transcription")

        self.transcribed_paths.append(path)
        return [_FakeSegment(0.0, 1.5, "hello world")], {}


class RecordingServiceTests(unittest.TestCase):
    @patch("app.services.recording_service.TranscriptService.normalize_transcript")
    @patch("app.services.recording_service.RecordingService._extract_audio_to_wav")
    @patch("app.services.recording_service.RecordingService._get_model")
    def test_transcribe_video_bytes_writes_temp_file_before_transcribing(
        self,
        mock_get_model,
        mock_extract_audio_to_wav,
        mock_normalize_transcript,
    ):
        mock_get_model.return_value = _FakeModel()
        mock_extract_audio_to_wav.side_effect = lambda path: path
        mock_normalize_transcript.side_effect = lambda transcript: transcript

        transcript = RecordingService.transcribe_video_bytes(b"media-bytes", suffix=".mp4")

        self.assertEqual(len(transcript), 1)
        self.assertEqual(transcript[0]["text"], "hello world")

    @patch("app.services.recording_service.RecordingService._transcribe_file_path")
    @patch("app.services.recording_service.OneDriveService.download_file_to_disk")
    def test_transcribe_drive_item_streams_to_disk_before_transcribing(
        self,
        mock_download_file_to_disk,
        mock_transcribe_file_path,
    ):
        def write_fake_media(_access_token, _drive_item, file_path):
            with open(file_path, "wb") as media_file:
                media_file.write(b"\x00\x00\x00\x20ftypisom" + (b"\x00" * 256))
            return {"content_type": "video/mp4", "bytes_written": 268}

        mock_download_file_to_disk.side_effect = write_fake_media
        mock_transcribe_file_path.return_value = [{"text": "hello from sharepoint"}]

        transcript = RecordingService.transcribe_drive_item(
            "access-token",
            {"id": "file-1", "name": "Recording.mp4"},
        )

        self.assertEqual(transcript, [{"text": "hello from sharepoint"}])
        mock_download_file_to_disk.assert_called_once()
        self.assertEqual(mock_download_file_to_disk.call_args.args[0], "access-token")
        self.assertEqual(mock_download_file_to_disk.call_args.args[1]["id"], "file-1")
        self.assertTrue(mock_download_file_to_disk.call_args.args[2].endswith(".mp4"))
        mock_transcribe_file_path.assert_called_once()

    @patch("app.services.recording_service.GraphClient.download_to_file")
    @patch("app.services.recording_service.RecordingService._transcribe_file_path")
    def test_transcribe_online_meeting_recording_downloads_graph_content(
        self,
        mock_transcribe_file_path,
        mock_download_to_file,
    ):
        def write_fake_media(endpoint, access_token, file_path):
            with open(file_path, "wb") as media_file:
                media_file.write(b"\x00\x00\x00\x20ftypisom" + (b"\x00" * 256))
            return {"content_type": "video/mp4", "bytes_written": 268}

        mock_download_to_file.side_effect = write_fake_media
        mock_transcribe_file_path.return_value = [{"text": "graph recording"}]

        transcript = RecordingService.transcribe_online_meeting_recording(
            "access-token",
            {
                "id": "recording-1",
                "recordingContentUrl": "https://graph.microsoft.com/v1.0/me/onlineMeetings/online-1/recordings/recording-1/content",
            },
        )

        self.assertEqual(transcript, [{"text": "graph recording"}])
        mock_download_to_file.assert_called_once()
        self.assertEqual(
            mock_download_to_file.call_args.kwargs["endpoint"],
            "https://graph.microsoft.com/v1.0/me/onlineMeetings/online-1/recordings/recording-1/content",
        )

    def test_validate_media_file_rejects_html_download(self):
        temp_fd, temp_path = tempfile.mkstemp(suffix=".mp4")
        os.close(temp_fd)
        try:
            with open(temp_path, "wb") as media_file:
                media_file.write(b"<!doctype html><html>not a recording</html>" * 10)

            with self.assertRaises(HTTPException) as context:
                RecordingService._validate_media_file(
                    temp_path,
                    {"id": "file-1", "name": "Meeting Transcript.mp4"},
                    {"content_type": "text/html", "bytes_written": 410},
                )

            self.assertEqual(context.exception.status_code, 422)
            self.assertIn("HTML page", context.exception.detail["message"])
        finally:
            os.remove(temp_path)

    @patch("app.services.recording_service.RecordingService._get_model")
    @patch("app.services.recording_service.RecordingService._extract_audio_to_wav")
    @patch("app.services.recording_service.TranscriptService.normalize_transcript")
    def test_transcribe_file_path_uses_extracted_wav_for_whisper(
        self,
        mock_normalize_transcript,
        mock_extract_audio_to_wav,
        mock_get_model,
    ):
        temp_fd, temp_path = tempfile.mkstemp(suffix=".mp4")
        os.close(temp_fd)
        wav_fd, wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(wav_fd)
        fake_model = _FakeModel()
        try:
            mock_extract_audio_to_wav.return_value = wav_path
            mock_get_model.return_value = fake_model
            mock_normalize_transcript.side_effect = lambda transcript: transcript

            RecordingService._transcribe_file_path(temp_path)

            self.assertEqual(fake_model.transcribed_paths, [wav_path])
            self.assertFalse(os.path.exists(wav_path))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            if os.path.exists(wav_path):
                os.remove(wav_path)


if __name__ == "__main__":
    unittest.main()
