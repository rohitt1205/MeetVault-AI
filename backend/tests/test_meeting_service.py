import unittest
from datetime import timezone
from unittest.mock import patch

from app.services.meeting_service import MeetingService


class MeetingServiceTests(unittest.TestCase):
    def test_parse_datetime_treats_graph_naive_values_as_utc(self):
        parsed = MeetingService._parse_datetime("2026-05-17T10:30:00")

        self.assertEqual(parsed.tzinfo, timezone.utc)

    @patch("app.services.meeting_service.GraphClient.get_collection")
    def test_get_recent_meetings_returns_latest_past_online_meetings(self, mock_get_collection):
        mock_get_collection.return_value = [
            {
                "id": "future-meeting",
                "subject": "Tomorrow planning",
                "isOnlineMeeting": True,
                "start": {"dateTime": "2099-01-01T10:00:00+00:00"},
                "end": {"dateTime": "2099-01-01T11:00:00+00:00"},
                "organizer": {"emailAddress": {"name": "Owner"}},
            },
            {
                "id": "older-meeting",
                "subject": "Older sync",
                "isOnlineMeeting": True,
                "start": {"dateTime": "2026-05-10T10:00:00+00:00"},
                "end": {"dateTime": "2026-05-10T11:00:00+00:00"},
                "organizer": {"emailAddress": {"name": "Owner"}},
            },
            {
                "id": "latest-meeting",
                "subject": "Latest review",
                "isOnlineMeeting": True,
                "start": {"dateTime": "2026-05-15T10:00:00+00:00"},
                "end": {"dateTime": "2026-05-15T11:00:00+00:00"},
                "organizer": {"emailAddress": {"name": "Owner"}},
            },
        ]

        meetings = MeetingService.get_recent_meetings("access-token", limit=2)

        self.assertEqual([meeting["event_id"] for meeting in meetings], ["latest-meeting", "older-meeting"])


if __name__ == "__main__":
    unittest.main()
