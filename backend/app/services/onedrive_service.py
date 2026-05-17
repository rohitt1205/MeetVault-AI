from app.services.graph_client import GraphClient
from app.services.transcript_service import TranscriptService


TRANSCRIPT_EXTENSIONS = {".vtt", ".txt"}
VIDEO_EXTENSIONS = {".mp4", ".m4a", ".mp3", ".wav", ".webm"}


class OneDriveService:
    @staticmethod
    def search_files(access_token: str, query: str, limit: int = 25) -> list[dict]:
        encoded_query = GraphClient.quote(query)
        personal_response = GraphClient.get(
            endpoint=f"/me/drive/root/search(q='{encoded_query}')",
            access_token=access_token,
            params={"$top": limit},
        )
        files = personal_response.get("value", [])

        # Search shared files
        shared_response = GraphClient.get(
            endpoint="/me/drive/sharedWithMe",
            access_token=access_token,
        )
        shared_items = shared_response.get("value", [])
        
        query_terms = query.lower().split()
        for item in shared_items:
            name = (item.get("name") or "").lower()
            if any(term in name for term in query_terms):
                if not any(f.get("id") == item.get("id") for f in files):
                    # Extract remoteItem details for shared files
                    if "remoteItem" in item:
                        remote = item["remoteItem"]
                        item["id"] = remote.get("id", item.get("id"))
                        item["name"] = remote.get("name", item.get("name"))
                        if "parentReference" in remote:
                            item["parentReference"] = remote["parentReference"]
                    files.append(item)

        return files[:limit]

    @staticmethod
    def find_meeting_assets(access_token: str, meeting_title: str) -> dict:
        import re
        # Clean the title: remove special chars, keep only letters/numbers/spaces
        cleaned_title = re.sub(r'[^a-zA-Z0-9\s]', ' ', meeting_title)
        # Use up to the first 3 significant words to ensure a broad search match
        words = [w for w in cleaned_title.split() if w]
        search_query = " ".join(words[:3]) if words else meeting_title

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
    def _get_content_endpoint(drive_item: dict) -> str:
        item_id = drive_item.get("id")
        drive_id = drive_item.get("parentReference", {}).get("driveId")

        if drive_id:
            return f"/drives/{GraphClient.quote(drive_id)}/items/{GraphClient.quote(item_id)}/content"
        return f"/me/drive/items/{GraphClient.quote(item_id)}/content"

    @staticmethod
    def download_file_text(access_token: str, drive_item: dict) -> str:
        if not drive_item.get("id"):
            return ""

        endpoint = OneDriveService._get_content_endpoint(drive_item)
        return GraphClient.get_text(endpoint=endpoint, access_token=access_token)

    @staticmethod
    def download_file_bytes(access_token: str, drive_item: dict) -> bytes:
        if not drive_item.get("id"):
            return b""

        endpoint = OneDriveService._get_content_endpoint(drive_item)
        return GraphClient.get_bytes(endpoint=endpoint, access_token=access_token)

    @staticmethod
    def download_file_to_disk(access_token: str, drive_item: dict, file_path: str) -> None:
        if not drive_item.get("id"):
            raise ValueError("Drive item missing id")

        endpoint = OneDriveService._get_content_endpoint(drive_item)
        GraphClient.download_to_file(
            endpoint=endpoint,
            access_token=access_token,
            file_path=file_path,
        )

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
