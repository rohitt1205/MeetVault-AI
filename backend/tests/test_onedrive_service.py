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

    @patch("app.services.onedrive_service.GraphClient.get")
    @patch("app.services.onedrive_service.GraphClient.post")
    def test_search_files_includes_shared_with_me_remote_items(
        self,
        mock_post,
        mock_get,
    ):
        mock_get.side_effect = [
            {"value": []},
            {
                "value": [
                    {
                        "id": "shared-link",
                        "remoteItem": {
                            "id": "remote-file",
                            "name": "Weekly Sync Recording.mp4",
                            "parentReference": {"driveId": "sharepoint-drive"},
                        },
                    }
                ]
            },
        ]
        mock_post.return_value = {"value": []}

        results = OneDriveService.search_files("access-token", "weekly sync recording")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "remote-file")
        self.assertEqual(results[0]["parentReference"]["driveId"], "sharepoint-drive")

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

    @patch("app.services.onedrive_service.OneDriveService.search_files")
    @patch("app.services.onedrive_service.OneDriveService._search_shared_with_me")
    @patch("app.services.onedrive_service.OneDriveService._list_recent_files")
    def test_find_recent_recording_assets_discovers_sharepoint_videos(
        self,
        mock_recent_files,
        mock_shared_with_me,
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
        mock_shared_with_me.return_value = [
            {
                "id": "shared-transcript",
                "name": "Project Review Transcript.vtt",
                "lastModifiedDateTime": "2026-05-17T10:10:00Z",
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


if __name__ == "__main__":
    unittest.main()
