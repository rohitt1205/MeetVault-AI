import os
import tempfile

from fastapi import HTTPException

from app.services.onedrive_service import OneDriveService
from app.services.transcript_service import TranscriptService


class RecordingService:
    @staticmethod
    def transcribe_video_bytes(video_bytes: bytes, suffix: str = ".mp4") -> list[dict]:
        if not video_bytes:
            return []

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise HTTPException(
                status_code=501,
                detail=(
                    "A recording was found but local transcription is not configured. "
                    "Install faster-whisper and set WHISPER_MODEL_SIZE to enable video fallback."
                ),
            ) from exc

        model_size = os.getenv("WHISPER_MODEL_SIZE", "base")

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as media_file:
            media_file.write(video_bytes)
            media_file.flush()

            model = WhisperModel(
                model_size,
                device=os.getenv("WHISPER_DEVICE", "cpu"),
                compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
            )
            segments, _info = model.transcribe(media_file.name)

            transcript = []
            for index, segment in enumerate(segments):
                transcript.append({
                    "turn_id": index + 1,
                    "speaker": "Unknown",
                    "timestamp": RecordingService._seconds_to_timestamp(segment.start),
                    "end_timestamp": RecordingService._seconds_to_timestamp(segment.end),
                    "text": segment.text.strip(),
                })

            return TranscriptService.normalize_transcript(transcript)

    @staticmethod
    def transcribe_drive_item(access_token: str, drive_item: dict) -> list[dict]:
        name = drive_item.get("name") or "recording.mp4"
        suffix = os.path.splitext(name)[1] or ".mp4"
        video_bytes = OneDriveService.download_file_bytes(access_token, drive_item)
        return RecordingService.transcribe_video_bytes(video_bytes, suffix=suffix)

    @staticmethod
    def _seconds_to_timestamp(seconds: float) -> str:
        whole_seconds = int(seconds)
        milliseconds = int((seconds - whole_seconds) * 1000)
        hours = whole_seconds // 3600
        minutes = (whole_seconds % 3600) // 60
        secs = whole_seconds % 60
        return f"{hours:02}:{minutes:02}:{secs:02}.{milliseconds:03}"
