import os
import tempfile
import wave
from pathlib import Path

from fastapi import HTTPException

from app.services.graph_client import GraphClient
from app.services.onedrive_service import OneDriveService
from app.services.transcript_service import TranscriptService


class RecordingService:
    _model = None
    _model_config = None

    @staticmethod
    def _get_model():
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

        model_config = (
            os.getenv("WHISPER_MODEL_SIZE", "base"),
            os.getenv("WHISPER_DEVICE", "cpu"),
            os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
        )

        if RecordingService._model is None or RecordingService._model_config != model_config:
            RecordingService._model = WhisperModel(
                model_config[0],
                device=model_config[1],
                compute_type=model_config[2],
            )
            RecordingService._model_config = model_config

        return RecordingService._model

    @staticmethod
    def transcribe_video_bytes(video_bytes: bytes, suffix: str = ".mp4") -> list[dict]:
        if not video_bytes:
            return []

        temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(temp_fd)
        try:
            with open(temp_path, "wb") as media_file:
                media_file.write(video_bytes)

            return RecordingService._transcribe_file_path(temp_path)
        finally:
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass

    @staticmethod
    def transcribe_drive_item(access_token: str, drive_item: dict) -> list[dict]:
        name = drive_item.get("name") or "recording.mp4"
        suffix = os.path.splitext(name)[1] or ".mp4"
        temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(temp_fd)

        try:
            download_info = OneDriveService.download_file_to_disk(access_token, drive_item, temp_path)
            RecordingService._validate_media_file(temp_path, drive_item, download_info)
            return RecordingService._transcribe_file_path(temp_path)
        finally:
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass

    @staticmethod
    def list_online_meeting_recordings(
        access_token: str,
        online_meeting_id: str,
        user_id: str = "me",
    ) -> list[dict]:
        endpoint = f"/{user_id}/onlineMeetings/{GraphClient.quote(online_meeting_id)}/recordings"
        response = GraphClient.get(endpoint=endpoint, access_token=access_token)
        return response.get("value", [])

    @staticmethod
    def transcribe_online_meeting_recording(
        access_token: str,
        recording: dict,
    ) -> list[dict]:
        content_url = recording.get("recordingContentUrl")
        if not content_url:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Graph recording does not include a content URL.",
                    "recording_id": recording.get("id"),
                },
            )

        temp_fd, temp_path = tempfile.mkstemp(suffix=".mp4")
        os.close(temp_fd)

        try:
            download_info = GraphClient.download_to_file(
                endpoint=content_url,
                access_token=access_token,
                file_path=temp_path,
            )
            RecordingService._validate_media_file(temp_path, recording, download_info)
            return RecordingService._transcribe_file_path(temp_path)
        finally:
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass

    @staticmethod
    def transcribe_local_file(file_path: str) -> list[dict]:
        if not os.path.exists(file_path):
            raise HTTPException(
                status_code=404,
                detail=f"Local recording not found: {file_path}",
            )

        return RecordingService._transcribe_file_path(file_path)

    @staticmethod
    def _validate_media_file(
        file_path: str,
        drive_item: dict | None = None,
        download_info: dict | None = None,
    ) -> None:
        file_size = Path(file_path).stat().st_size if os.path.exists(file_path) else 0
        if file_size < 128:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Downloaded recording is empty or too small to transcribe.",
                    "file_size": file_size,
                    "download": download_info or {},
                    "drive_item": RecordingService._drive_item_debug(drive_item or {}),
                },
            )

        with open(file_path, "rb") as media_file:
            header = media_file.read(512)

        lowered_header = header[:128].lower()
        if lowered_header.startswith(b"<!doctype html") or lowered_header.startswith(b"<html"):
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Graph downloaded an HTML page instead of recording media.",
                    "file_size": file_size,
                    "download": download_info or {},
                    "drive_item": RecordingService._drive_item_debug(drive_item or {}),
                },
            )

        if b"ftyp" not in header and not header.startswith((b"ID3", b"RIFF", b"\x1aE\xdf\xa3")):
            content_type = ((download_info or {}).get("content_type") or "").lower()
            if not (content_type.startswith("video/") or content_type.startswith("audio/")):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Downloaded file does not look like audio or video media.",
                        "file_size": file_size,
                        "content_probe": header[:32].hex(),
                        "download": download_info or {},
                        "drive_item": RecordingService._drive_item_debug(drive_item or {}),
                    },
                )

    @staticmethod
    def _drive_item_debug(drive_item: dict) -> dict:
        parent_reference = drive_item.get("parentReference") or {}
        return {
            "id": drive_item.get("id"),
            "name": drive_item.get("name"),
            "webUrl": drive_item.get("webUrl"),
            "driveId": parent_reference.get("driveId"),
            "mimeType": (drive_item.get("file") or {}).get("mimeType"),
            "size": drive_item.get("size"),
        }

    @staticmethod
    def _transcribe_file_path(file_path: str) -> list[dict]:
        wav_path = None
        try:
            wav_path = RecordingService._extract_audio_to_wav(file_path)
            model = RecordingService._get_model()
            segments, _info = model.transcribe(wav_path)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Recording transcription failed.",
                    "error": str(exc),
                },
            ) from exc
        finally:
            if wav_path and wav_path != file_path:
                try:
                    os.remove(wav_path)
                except FileNotFoundError:
                    pass

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
    def _extract_audio_to_wav(file_path: str) -> str:
        suffix = os.path.splitext(file_path)[1].lower()
        if suffix == ".wav":
            return file_path

        try:
            import av
        except ImportError as exc:
            raise HTTPException(
                status_code=501,
                detail={
                    "message": "Audio extraction is not configured. Install PyAV to transcribe recordings.",
                    "error": str(exc),
                },
            ) from exc

        temp_fd, wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(temp_fd)
        container = None

        try:
            container = av.open(file_path)
            audio_stream = next(
                (stream for stream in container.streams if stream.type == "audio"),
                None,
            )
            if audio_stream is None:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Recording does not contain an audio stream to transcribe.",
                        "file_size": Path(file_path).stat().st_size,
                    },
                )

            resampler = av.audio.resampler.AudioResampler(
                format="s16",
                layout="mono",
                rate=16000,
            )
            bytes_written = 0

            with wave.open(wav_path, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)

                for frame in container.decode(audio_stream):
                    bytes_written += RecordingService._write_resampled_audio(
                        wav_file,
                        resampler.resample(frame),
                    )

                bytes_written += RecordingService._write_resampled_audio(
                    wav_file,
                    resampler.resample(None),
                )

            if bytes_written == 0:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Recording audio stream decoded to zero samples.",
                        "file_size": Path(file_path).stat().st_size,
                    },
                )

            return wav_path
        except HTTPException:
            try:
                os.remove(wav_path)
            except FileNotFoundError:
                pass
            raise
        except Exception as exc:
            try:
                os.remove(wav_path)
            except FileNotFoundError:
                pass
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Recording audio extraction failed.",
                    "error": str(exc),
                    "file_size": Path(file_path).stat().st_size if os.path.exists(file_path) else 0,
                },
            ) from exc
        finally:
            if container is not None:
                container.close()

    @staticmethod
    def _write_resampled_audio(wav_file, frames) -> int:
        if frames is None:
            return 0

        if not isinstance(frames, list):
            frames = [frames]

        bytes_written = 0
        for frame in frames:
            audio = frame.to_ndarray()
            pcm_bytes = audio.reshape(-1).astype("int16", copy=False).tobytes()
            wav_file.writeframes(pcm_bytes)
            bytes_written += len(pcm_bytes)

        return bytes_written

    @staticmethod
    def _seconds_to_timestamp(seconds: float) -> str:
        whole_seconds = int(seconds)
        milliseconds = int((seconds - whole_seconds) * 1000)
        hours = whole_seconds // 3600
        minutes = (whole_seconds % 3600) // 60
        secs = whole_seconds % 60
        return f"{hours:02}:{minutes:02}:{secs:02}.{milliseconds:03}"
