import os
import tempfile
import unittest
from unittest.mock import patch

from app.services.post_meeting_notification_service import PostMeetingNotificationService


GRAPH_MAIL_TOKEN = (
    "header."
    "eyJhdWQiOiIwMDAwMDAwMy0wMDAwLTAwMDAtYzAwMC0wMDAwMDAwMDAwMDAiLCJzY3AiOiJNYWlsLlNlbmQifQ."
    "signature"
)


class PostMeetingNotificationServiceTests(unittest.TestCase):
    def _env(self, tmpdir):
        return patch.dict(
            os.environ,
            {
                "POST_MEETING_NOTIFICATION_STORE_PATH": os.path.join(
                    tmpdir,
                    "post_meeting_notifications.json",
                ),
                "POST_MEETING_EMAIL_ENABLED": "true",
                "MEETVAULT_CHAT_URL": "https://meetvault.example.com",
            },
        )

    @patch("app.services.post_meeting_notification_service.GraphClient.post")
    @patch("app.services.post_meeting_notification_service.PostMeetingNotificationService._generate_brief")
    @patch("app.services.post_meeting_notification_service.MeetingService.get_meeting_event_with_attendees")
    def test_send_now_sends_brief_to_unique_invitees_and_records_status(
        self,
        mock_get_event,
        mock_generate_brief,
        mock_graph_post,
    ):
        with tempfile.TemporaryDirectory() as tmpdir, self._env(tmpdir):
            mock_get_event.return_value = {
                "title": "Roadmap Review",
                "organizer": "Organizer",
                "organizer_email": "owner@example.com",
                "attendees": [
                    {"name": "Rohit", "email": "rohit@example.com", "type": "required"},
                    {"name": "Rohit Duplicate", "email": "ROHIT@example.com", "type": "optional"},
                ],
            }
            mock_generate_brief.return_value = {
                "bullets": [
                    "The team aligned on launch risks and customer follow-up.",
                    "A clear owner was assigned for open integration checks.",
                ],
                "hash": "brief-hash",
                "source_count": 2,
            }

            result = PostMeetingNotificationService.send_now(
                GRAPH_MAIL_TOKEN,
                "meeting-1",
                "Roadmap Review",
            )

            self.assertEqual(result["status"], "SENT")
            self.assertEqual(result["recipient_count"], 2)
            self.assertEqual(result["brief_hash"], "brief-hash")
            self.assertEqual(result["chat_url"], "https://meetvault.example.com/#meeting=meeting-1")
            mock_graph_post.assert_called_once()
            endpoint, _token, payload = mock_graph_post.call_args.args
            self.assertEqual(endpoint, "/me/sendMail")
            self.assertEqual(payload["message"]["subject"], "MeetVault brief: Roadmap Review")
            self.assertIn("Chat with us", payload["message"]["body"]["content"])
            self.assertIn("linear-gradient", payload["message"]["body"]["content"])
            self.assertEqual(
                [
                    item["emailAddress"]["address"]
                    for item in payload["message"]["toRecipients"]
                ],
                ["owner@example.com", "rohit@example.com"],
            )

    @patch("app.services.post_meeting_notification_service.GraphClient.post")
    @patch("app.services.post_meeting_notification_service.PostMeetingNotificationService._generate_brief")
    @patch("app.services.post_meeting_notification_service.MeetingService.get_meeting_event_with_attendees")
    def test_send_now_does_not_send_duplicate_success(
        self,
        mock_get_event,
        mock_generate_brief,
        mock_graph_post,
    ):
        with tempfile.TemporaryDirectory() as tmpdir, self._env(tmpdir):
            mock_get_event.return_value = {
                "title": "Roadmap Review",
                "organizer_email": "owner@example.com",
                "attendees": [],
            }
            mock_generate_brief.return_value = {
                "bullets": ["The team agreed on next steps for the release."],
                "hash": "brief-hash",
                "source_count": 1,
            }

            first = PostMeetingNotificationService.send_now(
                GRAPH_MAIL_TOKEN,
                "meeting-1",
                "Roadmap Review",
            )
            second = PostMeetingNotificationService.send_now(
                GRAPH_MAIL_TOKEN,
                "meeting-1",
                "Roadmap Review",
            )

            self.assertEqual(first["status"], "SENT")
            self.assertEqual(second["status"], "SENT")
            mock_graph_post.assert_called_once()

    @patch("app.services.post_meeting_notification_service.GraphClient.post")
    def test_queue_skips_without_mail_send_scope(self, mock_graph_post):
        with tempfile.TemporaryDirectory() as tmpdir, self._env(tmpdir):
            result = PostMeetingNotificationService.queue_after_index(
                "not-a-jwt",
                "meeting-1",
                "Roadmap Review",
            )

            self.assertEqual(result["status"], "SKIPPED")
            self.assertIn("Mail.Send", result["message"])
            mock_graph_post.assert_not_called()

    @patch("app.services.post_meeting_notification_service.GraphClient.post")
    def test_queue_skips_asset_only_id_without_calendar_attendees(self, mock_graph_post):
        with tempfile.TemporaryDirectory() as tmpdir, self._env(tmpdir):
            result = PostMeetingNotificationService.queue_after_index(
                GRAPH_MAIL_TOKEN,
                "sharepoint-1234567890abcdef",
                "Standalone recording",
            )

            self.assertEqual(result["status"], "SKIPPED")
            self.assertIn("calendar-backed", result["message"])
            mock_graph_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
