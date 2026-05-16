from app.services.graph_client import GraphClient
from app.services.transcript_service import TranscriptService


TRANSCRIPT_EXTENSIONS = {".vtt", ".txt"}
VIDEO_EXTENSIONS = {".mp4", ".m4a", ".mp3", ".wav", ".webm"}


class OneDriveService:
    @staticmethod
    def search_files(access_token: str, query: str, limit: int = 25) -> list[dict]:
        encoded_query = GraphClient.quote(query)
        response = GraphClient.get(
            endpoint=f"/me/drive/root/search(q='{encoded_query}')",
            access_token=access_token,
            params={"$top": limit},
        )

        return response.get("value", [])

    @staticmethod
    def find_meeting_assets(access_token: str, meeting_title: str) -> dict:
        search_query = f"{meeting_title} transcript recording"
        files = OneDriveService.search_files(access_token, search_query)

        transcript_files = []
        video_files = []

        for file_item in files:
            name = (file_item.get("name") or "").lower()

            if any(name.endswith(extension) for extension in TRANSCRIPT_EXTENSIONS):
                transcript_files.append(file_item)
                continue

            if any(name.endswith(extension) for extension in VIDEO_EXTENSIONS):
                video_files.append(file_item)

        return {
            "transcripts": transcript_files,
            "videos": video_files,
        }

    @staticmethod
    def download_file_text(access_token: str, drive_item: dict) -> str:
        item_id = drive_item.get("id")
        if not item_id:
            return ""

        endpoint = f"/me/drive/items/{GraphClient.quote(item_id)}/content"
        return GraphClient.get_text(endpoint=endpoint, access_token=access_token)

    @staticmethod
    def download_file_bytes(access_token: str, drive_item: dict) -> bytes:
        item_id = drive_item.get("id")
        if not item_id:
            return b""

        endpoint = f"/me/drive/items/{GraphClient.quote(item_id)}/content"
        return GraphClient.get_bytes(endpoint=endpoint, access_token=access_token)

    @staticmethod
    def transcript_from_drive_item(access_token: str, drive_item: dict) -> list[dict]:
        name = (drive_item.get("name") or "").lower()
        content = OneDriveService.download_file_text(access_token, drive_item)

        if name.endswith(".vtt"):
            return TranscriptService.normalize_transcript(content)

        return [
            {
                "turn_id": 1,
                "speaker": "Unknown",
                "timestamp": None,
                "end_timestamp": None,
                "text": content.strip(),
            }
        ] if content.strip() else []
