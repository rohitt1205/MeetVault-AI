import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.services.graph_client import GraphClient
from app.services.transcript_service import TranscriptService


TRANSCRIPT_EXTENSIONS = {".vtt", ".txt"}
VIDEO_EXTENSIONS = {".mp4", ".m4a", ".mp3", ".wav", ".webm"}
RECORDING_KEYWORDS = {"recording", "transcript", "meeting", "teams"}
VIDEO_NAME_MARKERS = (
    "meeting recording",
    "teams recording",
    "-meeting recording",
    " meeting recording",
)


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
    _shared_folder_keywords = {
        "record",
        "teams",
        "meeting",
        "video",
        "call",
        "transcript",
        "sync",
        "stream",
    }
    _shared_recording_search_queries = [
        "sharedwithme mp4",
        "sharedwithme webm",
        "sharedwithme m4a",
        "sharedwithme recording",
        "sharedwithme meeting",
        "sharedwithme teams",
        "sharedwithme video",
        "sharedwithme transcript",
        "sharedwithme filetype:mp4",
        "sharedwithme kind:video",
    ]
    # Microsoft Search — include plain queries (sharedwithme KQL is often empty via Graph)
    _shared_video_search_queries = [
        '"Meeting Recording"',
        "Meeting Recording",
        "filetype:mp4",
        "filetype:webm",
        'sharedwithme "Meeting Recording"',
        "sharedwithme",
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
        files.extend(
            OneDriveService._discover_shared_recording_assets(
                access_token,
                limit=expanded_limit,
            )
        )
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
    def find_recent_recording_assets_fast(
        access_token: str,
        limit: int = 10,
        meeting_titles: list[str] | None = None,
    ) -> dict:
        """Lightweight discovery for workspace sync — avoids dozens of Graph searches."""
        files = []
        expanded_limit = max(limit * 3, 20)
        files.extend(OneDriveService._list_recent_files(access_token, limit=expanded_limit))
        files.extend(
            OneDriveService._discover_shared_recording_assets(
                access_token,
                limit=expanded_limit,
                max_pages=3,
                max_folders_to_expand=20,
            )
        )
        files.extend(OneDriveService._list_recording_folder_assets(access_token, limit=expanded_limit))
        files.extend(OneDriveService._list_special_recordings_assets(access_token, limit=expanded_limit))

        for meeting_title in (meeting_titles or [])[:3]:
            cleaned_title = re.sub(r"[^a-zA-Z0-9 ()_-]+", " ", meeting_title or "").strip()
            if not cleaned_title:
                continue
            search_terms = OneDriveService._search_terms_for_meeting_title(cleaned_title)[:2]
            for search_term in search_terms:
                files.extend(OneDriveService.search_files(access_token, search_term, limit=expanded_limit))

        files = OneDriveService._dedupe_items(files)
        files = [file_item for file_item in files if OneDriveService._is_recording_asset(file_item)]
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
    def find_all_recording_assets(
        access_token: str,
        meeting_titles: list[str] | None = None,
    ) -> dict:
        """Discover all accessible recording-like files the user can read via Graph."""
        expanded_limit = 200
        files: list[dict] = []
        files.extend(OneDriveService._list_recent_files(access_token, limit=expanded_limit))
        files.extend(
            OneDriveService._discover_shared_recording_assets(
                access_token,
                limit=expanded_limit,
            )
        )
        files.extend(OneDriveService._list_special_recordings_assets(access_token, limit=expanded_limit))
        files.extend(
            OneDriveService._list_recording_folder_assets(
                access_token,
                limit=expanded_limit,
                cap_results=False,
            )
        )

        for query in OneDriveService._recording_search_queries:
            files.extend(OneDriveService.search_files(access_token, query, limit=expanded_limit))

        for meeting_title in meeting_titles or []:
            cleaned_title = re.sub(r"[^a-zA-Z0-9 ()_-]+", " ", meeting_title or "").strip()
            if not cleaned_title:
                continue
            for search_term in OneDriveService._search_terms_for_meeting_title(cleaned_title):
                files.extend(OneDriveService.search_files(access_token, search_term, limit=expanded_limit))

        files = OneDriveService._dedupe_items(files)
        files = [file_item for file_item in files if OneDriveService._is_recording_asset(file_item)]
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
            "transcripts": transcript_files,
            "videos": video_files,
        }

    @staticmethod
    def _is_teams_recording_name(file_name: str) -> bool:
        """Teams shared recordings are often extensionless in Graph (e.g. 'LWC Training-…-Meeting Recording')."""
        lowered = (file_name or "").lower()
        if any(marker in lowered for marker in VIDEO_NAME_MARKERS):
            return True
        if "recording" in lowered and re.search(r"\d{8}", lowered):
            return True
        return False

    @staticmethod
    def _is_video_asset(file_item: dict) -> bool:
        """True for video/audio files only (no transcripts, docs, or generic text)."""
        if "folder" in file_item:
            return False

        name = file_item.get("name") or ""
        lowered = name.lower()
        mime_type = ((file_item.get("file") or {}).get("mimeType") or "").lower()
        if mime_type.startswith("video/") or mime_type.startswith("audio/"):
            return True
        if "video" in file_item:
            return True

        extension = OneDriveService._extension_for_item(file_item)
        if extension in VIDEO_EXTENSIONS:
            return True

        web_url = (file_item.get("webUrl") or "").lower()
        if "stream.aspx" in web_url or "/recordings/" in web_url:
            return True

        return OneDriveService._is_teams_recording_name(name)

    @staticmethod
    def find_onedrive_videos(
        access_token: str,
        *,
        limit: int = 200,
        max_shared_pages: int = 5,
        meeting_titles: list[str] | None = None,
    ) -> dict:
        """
        List video/audio from your OneDrive (recent, Recordings folders) and whatever
        sharedWithMe/search returns under Files.Read (no Files.Read.All required).
        """
        files: list[dict] = []

        recent = OneDriveService._list_recent_files(access_token, limit=limit)
        recent_videos = [item for item in recent if OneDriveService._is_video_asset(item)]
        files.extend(recent_videos)

        mine_folder_items = OneDriveService._list_special_recordings_assets(
            access_token,
            limit=limit,
        )
        mine_folder_items.extend(
            OneDriveService._list_recording_folder_assets(
                access_token,
                limit=limit,
                cap_results=True,
            )
        )
        mine_folder_videos = [
            item for item in mine_folder_items if OneDriveService._is_video_asset(item)
        ]
        files.extend(mine_folder_videos)

        search_raw, search_videos, search_probe = OneDriveService._list_shared_videos_via_search(
            access_token,
            limit=limit,
            meeting_titles=meeting_titles,
        )
        files.extend(OneDriveService._tag_shared_with_me(search_videos))

        shared_raw = OneDriveService._list_shared_with_me_items(
            access_token,
            limit=limit,
            max_pages=max_shared_pages,
        )
        shared_videos = [
            item
            for item in OneDriveService._tag_shared_with_me(shared_raw)
            if OneDriveService._is_video_asset(item)
        ]
        files.extend(shared_videos)

        files = OneDriveService._dedupe_items(files)
        files = [file_item for file_item in files if OneDriveService._is_video_asset(file_item)]
        files.sort(
            key=lambda item: item.get("lastModifiedDateTime") or item.get("createdDateTime") or "",
            reverse=True,
        )

        return {
            "transcripts": [],
            "videos": files,
            "_probe": {
                "mine_recent_video_count": len(recent_videos),
                "mine_recordings_folder_video_count": len(mine_folder_videos),
                "shared_raw_count": len(shared_raw),
                "shared_video_count": len(shared_videos),
                "shared_sample_names": [
                    item.get("name") for item in shared_raw[:8] if item.get("name")
                ],
                "search_raw_count": len(search_raw),
                "search_video_count": len(search_videos),
                "search_sample_names": [
                    item.get("name") for item in search_raw[:8] if item.get("name")
                ],
                "search_errors": search_probe.get("search_errors", []),
                "search_totals_by_query": search_probe.get("search_totals_by_query", {}),
            },
        }

    @staticmethod
    def _list_shared_videos_via_search(
        access_token: str,
        limit: int = 200,
        meeting_titles: list[str] | None = None,
    ) -> tuple[list[dict], list[dict], dict]:
        """Use Microsoft Search + drive search for recordings the user can access."""
        per_query = min(max(limit, 1), 100)
        queries = list(OneDriveService._shared_video_search_queries)
        seen_query = {query.lower() for query in queries}

        for meeting_title in meeting_titles or []:
            cleaned = re.sub(r"[^a-zA-Z0-9 ()_-]+", " ", meeting_title or "").strip()
            if len(cleaned) < 4:
                continue
            for title_query in (f'"{cleaned[:48]}"', f'"{cleaned[:48]} Meeting Recording"'):
                if title_query.lower() not in seen_query:
                    seen_query.add(title_query.lower())
                    queries.append(title_query)

        hits: list[dict] = []
        search_errors: list[str] = []
        search_totals: dict[str, int] = {}

        for query in queries:
            search_result = OneDriveService._search_graph_content(
                access_token,
                query,
                limit=per_query,
            )
            search_totals[query] = search_result.get("total", 0)
            search_errors.extend(search_result.get("errors") or [])
            hits.extend(search_result.get("hits") or [])

        for drive_query in ('"Meeting Recording"', "Meeting Recording"):
            try:
                hits.extend(
                    OneDriveService._search_current_drive(
                        access_token,
                        drive_query,
                        limit=per_query,
                    )
                )
            except HTTPException:
                continue

        normalized_hits = []
        for item in OneDriveService._dedupe_items(hits):
            normalized = OneDriveService._normalize_search_item(
                OneDriveService._normalize_shared_item(item),
            )
            normalized_hits.append(normalized)

        videos = [item for item in normalized_hits if OneDriveService._is_video_asset(item)]
        probe = {
            "search_errors": list(dict.fromkeys(error for error in search_errors if error))[:5],
            "search_totals_by_query": search_totals,
            "search_queries_tried": len(queries),
        }
        return normalized_hits, videos, probe

    @staticmethod
    def _normalize_search_item(item: dict) -> dict:
        """Ensure search hits have driveId for later download."""
        parent = dict(item.get("parentReference") or {})
        if not parent.get("driveId"):
            sharepoint_ids = parent.get("sharepointIds") or {}
            list_id = sharepoint_ids.get("listId")
            if list_id and not parent.get("driveId"):
                parent["driveId"] = list_id
            item = dict(item)
            if parent:
                item["parentReference"] = parent
        return item

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
        probes["sharedWithMe"] = summarize(
            OneDriveService._discover_shared_recording_assets(access_token, limit=expanded_limit)
        )
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
    def _list_recording_folder_assets(
        access_token: str,
        limit: int = 50,
        *,
        cap_results: bool = True,
    ) -> list[dict]:
        items = []

        for path in OneDriveService._recording_folder_paths:
            items.extend(OneDriveService._list_folder_tree_by_path(access_token, path, limit=limit))

        for root_item in OneDriveService._list_root_children(access_token, limit=limit):
            name = (root_item.get("name") or "").lower()
            if "folder" in root_item and "record" in name:
                items.extend(
                    OneDriveService._list_folder_tree_by_item(
                        access_token,
                        root_item,
                        limit=limit,
                    )
                )

        items = OneDriveService._dedupe_items(items)
        return items[:limit] if cap_results else items

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
            if "folder" in item:
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
    def _search_graph_content(
        access_token: str,
        query: str,
        limit: int = 25,
    ) -> dict:
        """Microsoft Search API with error details for diagnostics."""
        page_size = min(max(limit, 1), 100)
        result = {"hits": [], "total": 0, "errors": [], "query": query}
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
                            "size": page_size,
                        }
                    ]
                },
            )
        except HTTPException as exc:
            detail = exc.detail
            message = detail if isinstance(detail, str) else str(detail)
            result["errors"].append(message)
            return result

        for request_result in response.get("value", []):
            for hits_container in request_result.get("hitsContainers", []):
                container_error = hits_container.get("error")
                if isinstance(container_error, dict):
                    result["errors"].append(
                        container_error.get("message") or str(container_error)
                    )
                result["total"] += int(hits_container.get("total") or 0)
                for hit in hits_container.get("hits", []):
                    resource = hit.get("resource")
                    if isinstance(resource, dict):
                        result["hits"].append(resource)

        return result

    @staticmethod
    def _search_shared_content(
        access_token: str,
        query: str,
        limit: int = 25,
    ) -> list[dict]:
        return OneDriveService._search_graph_content(access_token, query, limit=limit)["hits"]

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
    def _list_shared_with_me_items(
        access_token: str,
        *,
        limit: int = 200,
        max_pages: int = 10,
    ) -> list[dict]:
        page_size = min(max(limit, 1), 100)
        try:
            raw_items = GraphClient.get_collection(
                endpoint="/me/drive/sharedWithMe",
                access_token=access_token,
                params={"$top": page_size},
                max_pages=max_pages,
            )
        except HTTPException:
            return []

        return [
            OneDriveService._normalize_shared_item(raw_item)
            for raw_item in raw_items
            if isinstance(raw_item, dict)
        ]

    @staticmethod
    def _tag_shared_with_me(items: list[dict]) -> list[dict]:
        tagged = []
        for item in items:
            normalized = dict(item)
            normalized["_shared_with_me"] = True
            tagged.append(normalized)
        return tagged

    @staticmethod
    def _should_expand_shared_folder(folder_name: str) -> bool:
        lowered = (folder_name or "").lower()
        return any(keyword in lowered for keyword in OneDriveService._shared_folder_keywords)

    @staticmethod
    def _discover_shared_recording_assets(
        access_token: str,
        *,
        limit: int = 200,
        max_pages: int = 10,
        max_folders_to_expand: int = 50,
    ) -> list[dict]:
        """
        Discover recording-like files shared with the user: paginated sharedWithMe,
        shallow folder walks, and Microsoft Search queries scoped to shared content.
        """
        items: list[dict] = []
        shared_items = OneDriveService._list_shared_with_me_items(
            access_token,
            limit=limit,
            max_pages=max_pages,
        )

        folders_to_expand: list[dict] = []
        for item in shared_items:
            if "folder" in item:
                folders_to_expand.append(item)
                continue
            items.append(item)

        prioritized_folders = [
            folder
            for folder in folders_to_expand
            if OneDriveService._should_expand_shared_folder(folder.get("name") or "")
        ]
        other_folders = [
            folder
            for folder in folders_to_expand
            if folder not in prioritized_folders
        ]
        expand_queue = prioritized_folders + other_folders

        for folder in expand_queue[:max_folders_to_expand]:
            items.extend(
                OneDriveService._list_folder_tree_by_item(
                    access_token,
                    folder,
                    limit=limit,
                    max_depth=2,
                )
            )

        for query in OneDriveService._shared_recording_search_queries:
            items.extend(
                OneDriveService._search_shared_content(
                    access_token,
                    query,
                    limit=min(limit, 50),
                )
            )

        return OneDriveService._tag_shared_with_me(OneDriveService._dedupe_items(items))

    @staticmethod
    def _search_shared_with_me(
        access_token: str,
        query: str,
        limit: int = 25,
    ) -> list[dict]:
        max_pages = max(1, (limit + 99) // 100)
        shared_items = OneDriveService._tag_shared_with_me(
            OneDriveService._list_shared_with_me_items(
                access_token,
                limit=limit,
                max_pages=max_pages,
            )
        )

        query_terms = [term for term in query.lower().split() if term]
        if not query_terms:
            return shared_items[:limit]

        return [
            item
            for item in shared_items
            if any(term in (item.get("name") or "").lower() for term in query_terms)
        ][:limit]

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
            "video",
            "package",
            "size",
            "lastModifiedDateTime",
            "createdDateTime",
            "parentReference",
        ]:
            if remote_item.get(key) is not None:
                normalized[key] = remote_item[key]

        remote_parent = remote_item.get("parentReference") or {}
        parent = normalized.get("parentReference") or {}
        if remote_parent.get("driveId"):
            parent = {**parent, "driveId": remote_parent["driveId"]}
            normalized["parentReference"] = parent

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
    def _normalize_match_text(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", (value or "").lower())
        return " ".join(normalized.split())

    @staticmethod
    def _title_from_recording_filename(file_name: str) -> str | None:
        """Teams often names files like 'Weekly Sync-20260430_143022.mp4'."""
        base = re.sub(r"\.[a-z0-9]+$", "", file_name or "", flags=re.IGNORECASE)
        match = re.match(r"^(?P<title>.+?)(?:-|_)\d{8}", base)
        if match:
            return match.group("title").strip()
        return None

    @staticmethod
    def _titles_match(file_name: str, meeting_title: str) -> bool:
        file_text = OneDriveService._normalize_match_text(file_name)
        meeting_text = OneDriveService._normalize_match_text(meeting_title)
        if not file_text or not meeting_text:
            return False
        if meeting_text in file_text or file_text in meeting_text:
            return True

        extracted_title = OneDriveService._title_from_recording_filename(file_name)
        if extracted_title:
            extracted_text = OneDriveService._normalize_match_text(extracted_title)
            if extracted_text == meeting_text or meeting_text in extracted_text:
                return True

        meeting_words = [word for word in meeting_text.split() if len(word) > 2]
        if len(meeting_words) < 2:
            return bool(meeting_words and meeting_words[0] in file_text)

        matched_words = sum(1 for word in meeting_words if word in file_text)
        if matched_words >= max(2, len(meeting_words) - 1):
            return True

        # Allow a single distinctive word (e.g. project codename) when it is long enough.
        long_words = [word for word in meeting_words if len(word) >= 4]
        return any(word in file_text for word in long_words)

    @staticmethod
    def _parse_graph_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    @staticmethod
    def _file_matches_meeting(
        file_item: dict,
        meeting_title: str,
        start_time: str | None = None,
    ) -> bool:
        file_name = file_item.get("name") or ""
        if not OneDriveService._titles_match(file_name, meeting_title):
            return False

        meeting_start = OneDriveService._parse_graph_datetime(start_time)
        if not meeting_start:
            return True

        file_time = OneDriveService._parse_graph_datetime(
            file_item.get("lastModifiedDateTime") or file_item.get("createdDateTime"),
        )
        if not file_time:
            return True

        return abs((file_time - meeting_start).total_seconds()) <= timedelta(days=30).total_seconds()

    @staticmethod
    def catalog_event_id(file_item: dict) -> str | None:
        item_id = file_item.get("id")
        if not item_id:
            return None
        drive_id = (file_item.get("parentReference") or {}).get("driveId") or "me"
        return f"onedrive:{drive_id}:{item_id}"

    @staticmethod
    def display_title_from_filename(file_name: str) -> str:
        extracted = OneDriveService._title_from_recording_filename(file_name)
        if extracted:
            return extracted
        base = re.sub(r"\.[a-z0-9]+$", "", file_name or "", flags=re.IGNORECASE)
        return base.replace("_", " ").replace("-", " ").strip() or "OneDrive recording"

    @staticmethod
    def match_recording_assets_to_meetings(
        meetings: list[dict],
        assets: dict,
    ) -> tuple[set[str], list[dict]]:
        """Map OneDrive / SharePoint recording assets onto calendar event ids by title/time."""
        event_ids: set[str] = set()
        files = [
            *assets.get("transcripts", []),
            *assets.get("videos", []),
        ]
        if not files:
            return event_ids, []

        matched_files: set[str] = set()

        for meeting in meetings:
            event_id = meeting.get("event_id") or meeting.get("meeting_id")
            title = meeting.get("title") or ""
            if not event_id or not title:
                continue

            start_time = meeting.get("start_time") or meeting.get("end_time")
            for file_item in files:
                file_key = file_item.get("id") or file_item.get("webUrl") or file_item.get("name")
                if OneDriveService._file_matches_meeting(file_item, title, start_time):
                    event_ids.add(event_id)
                    if file_key:
                        matched_files.add(file_key)
                    break

        unmatched = [
            file_item
            for file_item in files
            if (file_item.get("id") or file_item.get("webUrl") or file_item.get("name")) not in matched_files
        ]
        return event_ids, unmatched

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
