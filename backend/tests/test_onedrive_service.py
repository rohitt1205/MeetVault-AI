import unittest
from unittest.mock import patch

from app.services.onedrive_service import OneDriveService


class OneDriveServiceTests(unittest.TestCase):
    @patch("app.services.onedrive_service.GraphClient.get")
    @patch("app.services.onedrive_service.GraphClient.post")
    def test_search_files_combines_current_drive_and_search_api(
        self,
        mock_post,
        mock_get,
    ):
        mock_get.side_effect = [
            {
                "value": [
                    {"id": "file-1", "name": "Meeting Recording.mp4"},
                ]
            },
            {"value": []},
        ]
        mock_post.return_value = {
            "value": [
                {
                    "hitsContainers": [
                        {
                            "hits": [
                                {
                                    "resource": {
                                        "id": "file-1",
                                        "name": "Meeting Recording.mp4",
                                    }
                                },
                                {
                                    "resource": {
                                        "id": "file-2",
                                        "name": "Meeting Transcript.vtt",
                                    }
                                },
                            ]
                        }
                    ]
                }
            ]
        }

        results = OneDriveService.search_files("access-token", "weekly sync recording")

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["id"], "file-1")
        self.assertEqual(results[1]["id"], "file-2")

    @patch("app.services.onedrive_service.OneDriveService._list_shared_with_me_items")
    @patch("app.services.onedrive_service.GraphClient.get")
    @patch("app.services.onedrive_service.GraphClient.post")
    def test_search_files_includes_shared_with_me_remote_items(
        self,
        mock_post,
        mock_get,
        mock_list_shared,
    ):
        mock_get.return_value = {"value": []}
        mock_post.return_value = {"value": []}
        mock_list_shared.return_value = [
            {
                "id": "remote-file",
                "name": "Weekly Sync Recording.mp4",
                "parentReference": {"driveId": "sharepoint-drive"},
            }
        ]

        results = OneDriveService.search_files("access-token", "weekly sync recording")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "remote-file")
        self.assertEqual(results[0]["parentReference"]["driveId"], "sharepoint-drive")

    @patch("app.services.onedrive_service.OneDriveService._search_shared_content")
    @patch("app.services.onedrive_service.OneDriveService._list_folder_tree_by_item")
    @patch("app.services.onedrive_service.OneDriveService._list_shared_with_me_items")
    def test_discover_shared_recording_assets_expands_shared_folders(
        self,
        mock_list_shared,
        mock_list_folder_tree,
        mock_search_shared,
    ):
        mock_list_shared.return_value = [
            {
                "id": "shared-folder",
                "name": "Teams Recordings",
                "folder": {},
                "parentReference": {"driveId": "shared-drive"},
            },
            {
                "id": "shared-video",
                "name": "Standup Recording.mp4",
                "file": {"mimeType": "video/mp4"},
                "parentReference": {"driveId": "shared-drive"},
            },
        ]
        mock_list_folder_tree.return_value = [
            {
                "id": "nested-video",
                "name": "Weekly Sync.mp4",
                "file": {"mimeType": "video/mp4"},
                "parentReference": {"driveId": "shared-drive"},
            }
        ]
        mock_search_shared.return_value = []

        items = OneDriveService._discover_shared_recording_assets("access-token", limit=50)

        self.assertTrue(any(item.get("id") == "shared-video" for item in items))
        self.assertTrue(any(item.get("id") == "nested-video" for item in items))
        self.assertTrue(all(item.get("_shared_with_me") for item in items))
        mock_list_folder_tree.assert_called_once()

    @patch("app.services.onedrive_service.GraphClient.download_to_file")
    def test_download_file_to_disk_uses_drive_specific_content_endpoint(self, mock_download):
        OneDriveService.download_file_to_disk(
            "access-token",
            {
                "id": "file-1",
                "parentReference": {"driveId": "drive-1"},
            },
            "recording.mp4",
        )

        mock_download.assert_called_once_with(
            endpoint="/drives/drive-1/items/file-1/content",
            access_token="access-token",
            file_path="recording.mp4",
        )

    def test_is_recording_asset_rejects_mp4_when_mime_is_not_media(self):
        self.assertFalse(
            OneDriveService._is_recording_asset({
                "name": "Meeting Transcript.mp4",
                "file": {"mimeType": "text/html"},
            })
        )

    def test_is_recording_asset_accepts_mp4_without_mime_hint(self):
        self.assertTrue(
            OneDriveService._is_recording_asset({
                "name": "Meeting Recording.mp4",
            })
        )

    def test_is_recording_asset_accepts_video_mime_without_extension(self):
        self.assertTrue(
            OneDriveService._is_recording_asset({
                "name": "LWC Training",
                "file": {"mimeType": "video/mp4"},
            })
        )

    def test_is_recording_asset_accepts_stream_meeting_card_without_extension(self):
        self.assertTrue(
            OneDriveService._is_recording_asset({
                "name": "LWC Training",
                "webUrl": "https://contoso.sharepoint.com/_layouts/15/stream.aspx?id=abc",
            })
        )

    def test_is_recording_asset_accepts_video_facet_without_extension(self):
        self.assertTrue(
            OneDriveService._is_recording_asset({
                "name": "MuleSoft ELT 7",
                "video": {},
            })
        )

    def test_is_video_asset_accepts_teams_meeting_recording_name_without_extension(self):
        self.assertTrue(
            OneDriveService._is_video_asset({
                "name": "LWC Training-20260506_111545-Meeting Recording",
            })
        )
        self.assertTrue(
            OneDriveService._is_video_asset({
                "name": "MuleSoft_ELT 7 (Virtual)-20260430_110503-Meeting Recording",
            })
        )

    def test_is_video_asset_rejects_transcripts_and_text(self):
        self.assertFalse(
            OneDriveService._is_video_asset({
                "name": "Meeting Transcript.vtt",
                "file": {"mimeType": "text/vtt"},
            })
        )
        self.assertFalse(
            OneDriveService._is_video_asset({
                "name": "Teams meeting notes.txt",
                "file": {"mimeType": "text/plain"},
            })
        )
        self.assertTrue(
            OneDriveService._is_video_asset({
                "name": "Weekly Sync.mp4",
                "file": {"mimeType": "video/mp4"},
            })
        )

    @patch("app.services.onedrive_service.OneDriveService._list_shared_with_me_items")
    @patch("app.services.onedrive_service.OneDriveService._list_recent_files")
    def test_find_onedrive_videos_merges_mine_and_shared(
        self,
        mock_recent,
        mock_shared,
    ):
        mock_recent.return_value = [
            {"id": "mine", "name": "My Recording.mp4", "file": {"mimeType": "video/mp4"}},
            {"id": "notes", "name": "notes.txt", "file": {"mimeType": "text/plain"}},
        ]
        mock_shared.return_value = [
            {
                "id": "shared",
                "name": "Colleague Recording.webm",
                "file": {"mimeType": "video/webm"},
            },
        ]

        assets = OneDriveService.find_onedrive_videos("access-token", limit=50)

        self.assertEqual(assets["transcripts"], [])
        self.assertEqual([v["id"] for v in assets["videos"]], ["mine", "shared"])
        self.assertTrue(assets["videos"][1].get("_shared_with_me"))

    @patch("app.services.onedrive_service.OneDriveService.search_files")
    @patch("app.services.onedrive_service.OneDriveService._discover_shared_recording_assets")
    @patch("app.services.onedrive_service.OneDriveService._list_recent_files")
    def test_find_recent_recording_assets_discovers_sharepoint_videos(
        self,
        mock_recent_files,
        mock_discover_shared,
        mock_search_files,
    ):
        mock_recent_files.return_value = [
            {
                "id": "recent-video",
                "name": "Project Review Recording.mp4",
                "lastModifiedDateTime": "2026-05-17T10:00:00Z",
            },
            {
                "id": "random-text",
                "name": "Asynchronous apex.txt",
                "lastModifiedDateTime": "2026-05-17T11:00:00Z",
                "webUrl": "https://example.sharepoint.com/Microsoft%20Teams%20Chat%20Files/Asynchronous%20apex.txt",
            }
        ]
        mock_discover_shared.return_value = [
            {
                "id": "shared-transcript",
                "name": "Project Review Transcript.vtt",
                "lastModifiedDateTime": "2026-05-17T10:10:00Z",
                "_shared_with_me": True,
            }
        ]
        mock_search_files.return_value = [
            {
                "id": "searched-video",
                "name": "Teams Meeting Recording.webm",
                "lastModifiedDateTime": "2026-05-17T09:00:00Z",
            }
        ]

        assets = OneDriveService.find_recent_recording_assets("access-token", limit=5)

        self.assertEqual([item["id"] for item in assets["transcripts"]], ["shared-transcript"])
        self.assertEqual(
            [item["id"] for item in assets["videos"]],
            ["recent-video", "searched-video"],
        )

    @patch("app.services.onedrive_service.OneDriveService.search_files")
    def test_find_meeting_assets_classifies_transcripts_and_videos(self, mock_search_files):
        mock_search_files.return_value = [
            {"id": "file-1", "name": "Weekly Sync.vtt"},
            {"id": "file-2", "name": "Weekly Sync.mp4"},
            {"id": "file-3", "name": "Weekly Notes.docx"},
        ]

        assets = OneDriveService.find_meeting_assets("access-token", "Weekly Sync")

        self.assertEqual([item["id"] for item in assets["transcripts"]], ["file-1"])
        self.assertEqual([item["id"] for item in assets["videos"]], ["file-2"])

    def test_match_recording_assets_to_meetings_by_title(self):
        meetings = [
            {
                "event_id": "evt-1",
                "title": "Weekly Product Sync",
                "start_time": "2026-05-15T10:00:00+00:00",
            },
            {
                "event_id": "evt-2",
                "title": "Unrelated Standup",
                "start_time": "2026-05-10T10:00:00+00:00",
            },
        ]
        assets = {
            "transcripts": [],
            "videos": [
                {
                    "name": "Weekly Product Sync-20260515.mp4",
                    "lastModifiedDateTime": "2026-05-15T11:00:00Z",
                },
            ],
        }

        matched, unmatched = OneDriveService.match_recording_assets_to_meetings(
            meetings,
            assets,
        )

        self.assertEqual(matched, {"evt-1"})
        self.assertEqual(unmatched, [])


if __name__ == "__main__":
    unittest.main()
