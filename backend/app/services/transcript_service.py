import re

from app.services.graph_client import GraphClient


TIMESTAMP_PATTERN = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?)\s+-->\s+"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?)"
)
VOICE_PATTERN = re.compile(r"<v\s+([^>]+)>(.*?)</v>", re.IGNORECASE | re.DOTALL)
TAG_PATTERN = re.compile(r"<[^>]+>")
PLAIN_TEXT_LINE_PATTERN = re.compile(
    r"^(?:(?P<timestamp>\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?)\s+)?"
    r"(?:(?P<speaker>[^:]{1,60}):\s+)?(?P<text>.+)$"
)


class TranscriptService:
    @staticmethod
    def list_online_meeting_transcripts(
        access_token: str,
        online_meeting_id: str,
        user_id: str = "me",
    ) -> list[dict]:
        endpoint = f"/{user_id}/onlineMeetings/{GraphClient.quote(online_meeting_id)}/transcripts"
        response = GraphClient.get(endpoint=endpoint, access_token=access_token)
        return response.get("value", [])

    @staticmethod
    def download_online_meeting_transcript(
        access_token: str,
        online_meeting_id: str,
        transcript_id: str,
        user_id: str = "me",
    ) -> str:
        endpoint = (
            f"/{user_id}/onlineMeetings/{GraphClient.quote(online_meeting_id)}"
            f"/transcripts/{GraphClient.quote(transcript_id)}/content"
        )

        return GraphClient.get_text(
            endpoint=endpoint,
            access_token=access_token,
            params={"$format": "text/vtt"},
            accept="text/vtt",
        )

    @staticmethod
    def parse_vtt(vtt_text: str) -> list[dict]:
        entries = []
        current_timestamp = None
        text_lines = []

        def flush_entry():
            if not current_timestamp or not text_lines:
                return

            raw_text = " ".join(line.strip() for line in text_lines if line.strip())
            voice_match = VOICE_PATTERN.search(raw_text)

            speaker = None
            if voice_match:
                speaker = voice_match.group(1).strip()
                raw_text = voice_match.group(2)

            cleaned_text = TAG_PATTERN.sub("", raw_text).strip()

            if cleaned_text:
                entries.append({
                    "speaker": speaker or "Unknown",
                    "timestamp": current_timestamp["start"],
                    "end_timestamp": current_timestamp["end"],
                    "text": cleaned_text,
                })

        for raw_line in vtt_text.splitlines():
            line = raw_line.strip()

            if not line or line.upper() == "WEBVTT" or line.startswith("NOTE"):
                continue

            timestamp_match = TIMESTAMP_PATTERN.search(line)
            if timestamp_match:
                flush_entry()
                current_timestamp = {
                    "start": timestamp_match.group("start"),
                    "end": timestamp_match.group("end"),
                }
                text_lines = []
                continue

            if line.isdigit():
                continue

            text_lines.append(line)

        flush_entry()
        return entries

    @staticmethod
    def normalize_transcript(raw_transcript: list[dict] | str) -> list[dict]:
        if isinstance(raw_transcript, str):
            parsed_vtt = TranscriptService.parse_vtt(raw_transcript)
            raw_transcript = (
                parsed_vtt
                if parsed_vtt
                else TranscriptService.parse_plain_text(raw_transcript)
            )

        normalized_transcript = []

        for index, item in enumerate(raw_transcript):
            text = (item.get("text") or "").strip()
            if not text:
                continue

            normalized_transcript.append({
                "turn_id": index + 1,
                "speaker": item.get("speaker") or "Unknown",
                "timestamp": item.get("timestamp"),
                "end_timestamp": item.get("end_timestamp"),
                "text": text,
            })

        return normalized_transcript

    @staticmethod
    def parse_plain_text(raw_text: str) -> list[dict]:
        entries = []

        for raw_line in raw_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            match = PLAIN_TEXT_LINE_PATTERN.match(line)
            if not match:
                continue

            entries.append({
                "speaker": (match.group("speaker") or "Unknown").strip(),
                "timestamp": match.group("timestamp"),
                "end_timestamp": None,
                "text": match.group("text").strip(),
            })

        return entries

    @staticmethod
    def transcript_to_text(transcript: list[dict]) -> str:
        return "\n".join(
            f"{item.get('timestamp') or ''} {item.get('speaker')}: {item.get('text')}"
            for item in transcript
        )
