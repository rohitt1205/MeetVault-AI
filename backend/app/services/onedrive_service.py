import re

from fastapi import HTTPException

from app.services.graph_client import GraphClient
from app.services.transcript_service import TranscriptService


TRANSCRIPT_EXTENSIONS = {".vtt", ".txt"}
VIDEO_EXTENSIONS = {".mp4", ".m4a", ".mp3", ".wav", ".webm"}
RECORDING_KEYWORDS = {"recording", "transcript", "meeting", "teams"}


class OneDriveService:
    _recording_search_queries = [
        "*",
        "mp4",
        ".mp4",
        "webm",
        ".webm",
        "m4a",
        ".m4a",
        "mp3",
        ".mp3",
        "recording",
        "recorded",
        "video",
        "training",
        "Recordings",
        "teams recording",
        "meeting recording",
        "transcript",
        "Microsoft Teams",
        "filetype:mp4",
        "filetype:webm",
        "filetype:m4a",
        "filetype:mp3",
        "kind:video",
        "recording filetype:mp4",
        "meeting filetype:mp4",
        "teams filetype:mp4",
    ]
    _recording_folder_paths = [
        "Recordings",
        "Microsoft Teams Recordings",
        "Teams Recordings",
        "Microsoft Teams Chat Files",
    ]

    @staticmethod
    def search_files(access_token: str, query: str, limit: int = 25) -> list[dict]:
        results = []

        results.extend(
            OneDriveService._search_current_drive(access_token, query, limit=limit)
        )
        results.extend(
            OneDriveService._search_shared_content(access_token, query, limit=limit)
        )
        results.extend(
            OneDriveService._search_shared_with_me(access_token, query, limit=limit)
        )

        return OneDriveService._dedupe_items(results)[:limit]

    @staticmethod
    def find_recent_recording_assets(
        access_token: str,
        limit: int = 10,
        meeting_titles: list[str] | None = None,
    ) -> dict:
        files = []
        expanded_limit = max(limit * 5, 50)
        files.extend(OneDriveService._list_recent_files(access_token, limit=expanded_limit))
        files.extend(OneDriveService._search_shared_with_me(access_token, "", limit=expanded_limit))
        files.extend(OneDriveService._list_special_recordings_assets(access_token, limit=expanded_limit))
        files.extend(OneDriveService._list_recording_folder_assets(access_token, limit=expanded_limit))

        for query in OneDriveService._recording_search_queries:
            files.extend(OneDriveService.search_files(access_token, query, limit=expanded_limit))

        for meeting_title in meeting_titles or []:
            cleaned_title = re.sub(r"[^a-zA-Z0-9 ()_-]+", " ", meeting_title or "").strip()
            if not cleaned_title:
                continue
            search_terms = OneDriveService._search_terms_for_meeting_title(cleaned_title)
            for search_term in search_terms:
                files.extend(OneDriveService.search_files(access_token, search_term, limit=expanded_limit))

        files = OneDriveService._dedupe_items(files)
        files = [
            file_item
            for file_item in files
            if OneDriveService._is_recording_asset(file_item)
        ]
        files.sort(
            key=lambda item: item.get("lastModifiedDateTime") or item.get("createdDateTime") or "",
            reverse=True,
        )

        transcript_files = []
        video_files = []

        for file_item in files:
            name = (file_item.get("name") or "").lower()
            mime_type = ((file_item.get("file") or {}).get("mimeType") or "").lower()

            if any(name.endswith(extension) for extension in TRANSCRIPT_EXTENSIONS):
                transcript_files.append(file_item)
                continue

            if (
                mime_type.startswith("video/")
                or mime_type.startswith("audio/")
                or any(name.endswith(extension) for extension in VIDEO_EXTENSIONS)
            ):
                video_files.append(file_item)

        return {
            "transcripts": transcript_files[:limit],
            "videos": video_files[:limit],
        }

    @staticmethod
    def discovery_diagnostics(
        access_token: str,
        meeting_titles: list[str] | None = None,
        limit: int = 20,
    ) -> dict:
        expanded_limit = max(limit * 5, 50)
        probes = {}

        def summarize(items: list[dict]) -> dict:
            assets = [item for item in OneDriveService._dedupe_items(items) if OneDriveService._is_recording_asset(item)]
            return {
                "raw_count": len(items),
                "recording_asset_count": len(assets),
                "sample": [
                    OneDriveService._summary_for_debug(item)
                    for item in assets[:5]
                ],
            }

        probes["recent"] = summarize(OneDriveService._list_recent_files(access_token, limit=expanded_limit))
        probes["sharedWithMe"] = summarize(OneDriveService._search_shared_with_me(access_token, "", limit=expanded_limit))
        probes["specialRecordings"] = summarize(OneDriveService._list_special_recordings_assets(access_token, limit=expanded_limit))
        probes["recordingFolders"] = summarize(OneDriveService._list_recording_folder_assets(access_token, limit=expanded_limit))

        query_samples = {}
        for query in OneDriveService._recording_search_queries[:8]:
            query_samples[query] = summarize(OneDriveService.search_files(access_token, query, limit=expanded_limit))
        for title in (meeting_titles or [])[:5]:
            for term in OneDriveService._search_terms_for_meeting_title(title)[:3]:
                query_samples[term] = summarize(OneDriveService.search_files(access_token, term, limit=expanded_limit))

        probes["searchQueries"] = query_samples
        return probes

    @staticmethod
    def _summary_for_debug(item: dict) -> dict:
        parent_reference = item.get("parentReference") or {}
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "webUrl": item.get("webUrl"),
            "mimeType": (item.get("file") or {}).get("mimeType"),
            "size": item.get("size"),
            "driveId": parent_reference.get("driveId"),
            "lastModifiedDateTime": item.get("lastModifiedDateTime"),
        }

    @staticmethod
    def _search_terms_for_meeting_title(meeting_title: str) -> list[str]:
        words = [word for word in meeting_title.split() if word]
        terms = [
            meeting_title,
            f"{meeting_title} recording",
            f"{meeting_title} mp4",
            f"{meeting_title} video",
        ]

        if len(words) > 1:
            terms.append(" ".join(words[:2]))
        if words:
            terms.append(words[0])

        deduped = []
        seen = set()
        for term in terms:
            normalized = term.strip()
            if normalized and normalized.lower() not in seen:
                seen.add(normalized.lower())
                deduped.append(normalized)

        return deduped

    @staticmethod
    def _list_special_recordings_assets(access_token: str, limit: int = 50) -> list[dict]:
        try:
            return GraphClient.get_collection(
                endpoint="/me/drive/special/recordings/children",
                access_token=access_token,
                params={
                    "$top": limit,
                    "$select": "id,name,webUrl,file,folder,size,lastModifiedDateTime,createdDateTime,parentReference",
                },
            )
        except HTTPException:
            return []

    @staticmethod
    def _list_recording_folder_assets(access_token: str, limit: int = 50) -> list[dict]:
        items = []

        for path in OneDriveService._recording_folder_paths:
            items.extend(OneDriveService._list_folder_tree_by_path(access_token, path, limit=limit))

        for root_item in OneDriveService._list_root_children(access_token, limit=limit):
            name = (root_item.get("name") or "").lower()
            if root_item.get("folder") and "record" in name:
                items.extend(
                    OneDriveService._list_folder_tree_by_item(
                        access_token,
                        root_item,
                        limit=limit,
                    )
                )

        return OneDriveService._dedupe_items(items)[:limit]

    @staticmethod
    def _list_root_children(access_token: str, limit: int = 50) -> list[dict]:
        try:
            response = GraphClient.get(
                endpoint="/me/drive/root/children",
                access_token=access_token,
                params={
                    "$top": limit,
                    "$select": "id,name,webUrl,file,folder,size,lastModifiedDateTime,createdDateTime,parentReference",
                },
            )
        except HTTPException:
            return []

        return response.get("value", [])

    @staticmethod
    def _list_folder_tree_by_path(
        access_token: str,
        path: str,
        *,
        limit: int = 50,
        max_depth: int = 2,
    ) -> list[dict]:
        encoded_path = "/".join(GraphClient.quote(segment) for segment in path.split("/") if segment)
        if not encoded_path:
            return []

        endpoint = f"/me/drive/root:/{encoded_path}:/children"
        try:
            response = GraphClient.get(
                endpoint=endpoint,
                access_token=access_token,
                params={
                    "$top": limit,
                    "$select": "id,name,webUrl,file,folder,size,lastModifiedDateTime,createdDateTime,parentReference",
                },
            )
        except HTTPException:
            return []

        return OneDriveService._walk_folder_children(
            access_token,
            response.get("value", []),
            limit=limit,
            max_depth=max_depth,
        )

    @staticmethod
    def _list_folder_tree_by_item(
        access_token: str,
        folder_item: dict,
        *,
        limit: int = 50,
        max_depth: int = 2,
    ) -> list[dict]:
        endpoint = OneDriveService._get_children_endpoint(folder_item)
        if not endpoint:
            return []

        try:
            response = GraphClient.get(
                endpoint=endpoint,
                access_token=access_token,
                params={
                    "$top": limit,
                    "$select": "id,name,webUrl,file,folder,size,lastModifiedDateTime,createdDateTime,parentReference",
                },
            )
        except HTTPException:
            return []

        return OneDriveService._walk_folder_children(
            access_token,
            response.get("value", []),
            limit=limit,
            max_depth=max_depth,
        )

    @staticmethod
    def _walk_folder_children(
        access_token: str,
        children: list[dict],
        *,
        limit: int,
        max_depth: int,
    ) -> list[dict]:
        results = []
        folders = []

        for item in children:
            if item.get("folder"):
                folders.append(item)
            else:
                results.append(item)

        if max_depth <= 0 or len(results) >= limit:
            return results[:limit]

        for folder in folders:
            results.extend(
                OneDriveService._list_folder_tree_by_item(
                    access_token,
                    folder,
                    limit=limit,
                    max_depth=max_depth - 1,
                )
            )
            if len(results) >= limit:
                break

        return results[:limit]

    @staticmethod
    def _is_recording_asset(file_item: dict) -> bool:
        name = (file_item.get("name") or "").lower()
        web_url = (file_item.get("webUrl") or "").lower()
        extension = OneDriveService._extension_for_item(file_item)
        content_type = (
            ((file_item.get("listItem") or {}).get("contentType") or {}).get("name")
            or file_item.get("contentType")
            or ""
        ).lower()

        mime_type = ((file_item.get("file") or {}).get("mimeType") or "").lower()
        if (
            mime_type.startswith("video/")
            or mime_type.startswith("audio/")
            or "recording" in mime_type
            or "stream" in mime_type
        ):
            return True
        if "video" in file_item or "recording" in content_type or "video" in content_type:
            return True
        if mime_type:
            return False

        if extension in VIDEO_EXTENSIONS:
            return True

        if extension == ".vtt":
            return True

        if extension == ".txt":
            return any(keyword in name for keyword in RECORDING_KEYWORDS)

        if "stream.aspx" in web_url or "/recordings/" in web_url:
            return True

        return False

    @staticmethod
    def _extension_for_item(file_item: dict) -> str:
        return "." + (file_item.get("name") or "").rsplit(".", 1)[-1].lower() if "." in (file_item.get("name") or "") else ""

    @staticmethod
    def _list_recent_files(access_token: str, limit: int = 25) -> list[dict]:
        try:
            items = GraphClient.get_collection(
                endpoint="/me/drive/recent",
                access_token=access_token,
                params={
                    "$top": limit,
                    "$select": "id,name,webUrl,file,folder,size,lastModifiedDateTime,createdDateTime,parentReference",
                },
            )
        except HTTPException:
            return []

        return [
            OneDriveService._normalize_shared_item(item)
            for item in items
            if isinstance(item, dict)
        ]

    @staticmethod
    def _search_current_drive(access_token: str, query: str, limit: int = 25) -> list[dict]:
        encoded_query = GraphClient.quote(query)

        try:
            response = GraphClient.get(
                endpoint=f"/me/drive/root/search(q='{encoded_query}')",
                access_token=access_token,
                params={"$top": limit},
            )
        except HTTPException:
            return []

        return response.get("value", [])

    @staticmethod
    def _search_shared_content(
        access_token: str,
        query: str,
        limit: int = 25,
    ) -> list[dict]:
        try:
            response = GraphClient.post(
                endpoint="/search/query",
                access_token=access_token,
                payload={
                    "requests": [
                        {
                            "entityTypes": ["driveItem"],
                            "query": {
                                "queryString": query,
                            },
                            "from": 0,
                            "size": limit,
                        }
                    ]
                },
            )
        except HTTPException:
            return []

        return OneDriveService._extract_search_hits(response)

    @staticmethod
    def _extract_search_hits(response: dict) -> list[dict]:
        items = []

        for request_result in response.get("value", []):
            for hits_container in request_result.get("hitsContainers", []):
                for hit in hits_container.get("hits", []):
                    resource = hit.get("resource")
                    if isinstance(resource, dict):
                        items.append(resource)

        return items

    @staticmethod
    def _search_shared_with_me(
        access_token: str,
        query: str,
        limit: int = 25,
    ) -> list[dict]:
        try:
            raw_items = GraphClient.get_collection(
                endpoint="/me/drive/sharedWithMe",
                access_token=access_token,
                params={"$top": limit},
            )
        except HTTPException:
            return []

        query_terms = [term for term in query.lower().split() if term]
        items = []

        for raw_item in raw_items:
            item = OneDriveService._normalize_shared_item(raw_item)
            name = (item.get("name") or "").lower()
            if not query_terms or any(term in name for term in query_terms):
                items.append(item)

        return items

    @staticmethod
    def _normalize_shared_item(item: dict) -> dict:
        remote_item = item.get("remoteItem")
        if not isinstance(remote_item, dict):
            return item

        normalized = dict(item)
        for key in [
            "id",
            "name",
            "webUrl",
            "file",
            "folder",
            "size",
            "lastModifiedDateTime",
            "createdDateTime",
            "parentReference",
        ]:
            if remote_item.get(key) is not None:
                normalized[key] = remote_item[key]

        return normalized

    @staticmethod
    def _dedupe_items(items: list[dict]) -> list[dict]:
        deduped = []
        seen_keys = set()

        for item in items:
            parent_reference = item.get("parentReference") or {}
            key = (
                f"{parent_reference.get('driveId')}:{item.get('id')}"
                if item.get("id")
                else item.get("webUrl") or item.get("name")
            )
            if not key or key in seen_keys:
                continue

            seen_keys.add(key)
            deduped.append(item)

        return deduped

    @staticmethod
    def find_meeting_assets(access_token: str, meeting_title: str) -> dict:
        cleaned_title = re.sub(r"[^a-zA-Z0-9 ]+", " ", meeting_title or "").strip()
        broad_title = " ".join(cleaned_title.split()[:4]) if cleaned_title else meeting_title
        search_queries = [
            broad_title,
            f"{meeting_title} transcript recording",
            f"{meeting_title} recording",
            f"{meeting_title} video",
        ]

        files = []
        for search_query in search_queries:
            if not search_query:
                continue
            files.extend(OneDriveService.search_files(access_token, search_query))

        files = OneDriveService._dedupe_items(files)

        transcript_files = []
        video_files = []

        for file_item in files:
            name = (file_item.get("name") or "").lower()
            mime_type = ((file_item.get("file") or {}).get("mimeType") or "").lower()

            if any(name.endswith(extension) for extension in TRANSCRIPT_EXTENSIONS):
                transcript_files.append(file_item)
                continue

            if (
                mime_type.startswith("video/")
                or mime_type.startswith("audio/")
                or any(name.endswith(extension) for extension in VIDEO_EXTENSIONS)
            ):
                video_files.append(file_item)

        return {
            "transcripts": transcript_files,
            "videos": video_files,
        }

    @staticmethod
    def _get_content_endpoint(drive_item: dict) -> str | None:
        item_id = drive_item.get("id")
        if not item_id:
            return None

        parent_reference = drive_item.get("parentReference") or {}
        drive_id = parent_reference.get("driveId")
        if drive_id:
            return (
                f"/drives/{GraphClient.quote(drive_id)}"
                f"/items/{GraphClient.quote(item_id)}/content"
            )

        return f"/me/drive/items/{GraphClient.quote(item_id)}/content"

    @staticmethod
    def _get_children_endpoint(drive_item: dict) -> str | None:
        item_id = drive_item.get("id")
        if not item_id:
            return None

        parent_reference = drive_item.get("parentReference") or {}
        drive_id = parent_reference.get("driveId")
        if drive_id:
            return (
                f"/drives/{GraphClient.quote(drive_id)}"
                f"/items/{GraphClient.quote(item_id)}/children"
            )

        return f"/me/drive/items/{GraphClient.quote(item_id)}/children"

    @staticmethod
    def download_file_text(access_token: str, drive_item: dict) -> str:
        endpoint = OneDriveService._get_content_endpoint(drive_item)
        if not endpoint:
            return ""

        return GraphClient.get_text(endpoint=endpoint, access_token=access_token)

    @staticmethod
    def download_file_bytes(access_token: str, drive_item: dict) -> bytes:
        endpoint = OneDriveService._get_content_endpoint(drive_item)
        if not endpoint:
            return b""

        return GraphClient.get_bytes(endpoint=endpoint, access_token=access_token)

    @staticmethod
    def download_file_to_disk(access_token: str, drive_item: dict, file_path: str) -> dict:
        endpoint = OneDriveService._get_content_endpoint(drive_item)
        if not endpoint:
            raise HTTPException(status_code=400, detail="Drive item does not include an id.")

        return GraphClient.download_to_file(
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
