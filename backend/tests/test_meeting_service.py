import unittest
from datetime import timezone
from unittest.mock import patch

from app.services.meeting_service import MeetingService

SAMPLE_JOIN_URL = (
    "https://teams.microsoft.com/l/meetup-join/"
    "19:meeting_abc123@thread.v2/0"
    "?context=%7b%22Tid%22%3a%22tenant-1%22%2c%22Oid%22%3a%22organizer-oid%22%7d"
)


class MeetingServiceTests(unittest.TestCase):
    def test_parse_datetime_treats_graph_naive_values_as_utc(self):
        parsed = MeetingService._parse_datetime("2026-05-17T10:30:00")

        self.assertEqual(parsed.tzinfo, timezone.utc)

    def test_parse_teams_join_url_extracts_thread_and_organizer(self):
        parsed = MeetingService._parse_teams_join_url(SAMPLE_JOIN_URL)

        self.assertEqual(parsed["thread_id"], "19:meeting_abc123@thread.v2")
        self.assertEqual(parsed["organizer_oid"], "organizer-oid")
        self.assertEqual(parsed["tenant_id"], "tenant-1")

    def test_enrich_meetings_from_online_index_matches_by_start_time(self):
        meetings = [
            {
                "event_id": "evt-1",
                "title": "Weekly sync",
                "start_time": "2026-05-15T10:00:00+00:00",
            },
        ]
        online_meetings = [
            {
                "id": "organizer-oid_19:meeting_abc@thread.v2",
                "subject": "Weekly sync",
                "startDateTime": "2026-05-15T10:01:00Z",
                "joinWebUrl": SAMPLE_JOIN_URL,
            },
        ]

        enriched, stats = MeetingService.enrich_meetings_from_online_index(
            meetings,
            online_meetings,
        )

        self.assertEqual(enriched[0]["join_url"], SAMPLE_JOIN_URL)
        self.assertEqual(stats["matched_by_start_time"], 1)

    def test_construct_online_meeting_id_from_join_url(self):
        constructed = MeetingService._construct_online_meeting_id_from_join_url(
            SAMPLE_JOIN_URL,
        )

        self.assertEqual(
            constructed,
            "organizer-oid_19:meeting_abc123@thread.v2",
        )

    def test_teams_join_url_filter_form_double_encodes(self):
        stored = MeetingService._teams_join_url_stored_form(SAMPLE_JOIN_URL)
        self.assertIn("19%3Ameeting_abc123%40thread.v2", stored)

        filter_form = MeetingService._teams_join_url_filter_form(SAMPLE_JOIN_URL)
        self.assertTrue(filter_form.startswith("https%3A%2F%2F"))
        self.assertIn("%253A", filter_form)

    @patch("app.services.meeting_service.GraphClient.get")
    def test_get_recent_meetings_returns_latest_past_online_meetings(self, mock_get):
        mock_get.return_value = {
            "value": [
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
            ],
        }

        meetings = MeetingService.get_recent_meetings("access-token", limit=2)

        self.assertEqual(
            [meeting["event_id"] for meeting in meetings],
            ["latest-meeting", "older-meeting"],
        )

    @patch("app.services.meeting_service.MeetingService._lookup_online_meeting_by_join_url")
    @patch("app.services.meeting_service.MeetingService._first_verified_access")
    @patch("app.services.meeting_service.MeetingService.enrich_meeting_from_event")
    def test_resolve_online_meeting_uses_verified_constructed_id(
        self,
        mock_enrich,
        mock_verified,
        mock_lookup,
    ):
        mock_enrich.side_effect = lambda _token, meeting: meeting
        constructed = "organizer-oid_19:meeting_abc123@thread.v2"

        def verified_side_effect(_token, meeting_id, _meeting, _join_url):
            if meeting_id == constructed:
                return {
                    "online_meeting_id": constructed,
                    "graph_user_id": "me",
                }
            return None

        mock_verified.side_effect = verified_side_effect
        mock_lookup.return_value = None

        meeting = {"event_id": "evt-1", "join_url": SAMPLE_JOIN_URL}
        resolved = MeetingService.resolve_online_meeting("token", meeting)

        self.assertEqual(
            resolved,
            {
                "online_meeting_id": constructed,
                "graph_user_id": "me",
            },
        )
        mock_lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
