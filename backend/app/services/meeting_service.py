from app.services.graph_client import GraphClient


class MeetingService:
    @staticmethod
    def _normalize_event(event: dict) -> dict:
        online_meeting = event.get("onlineMeeting") or {}

        return {
            "meeting_id": event.get("id"),
            "event_id": event.get("id"),
            "online_meeting_id": online_meeting.get("id"),
            "join_url": online_meeting.get("joinUrl") or event.get("onlineMeetingUrl"),
            "title": event.get("subject") or "Untitled meeting",
            "organizer": (
                event.get("organizer", {})
                .get("emailAddress", {})
                .get("name")
            ),
            "organizer_email": (
                event.get("organizer", {})
                .get("emailAddress", {})
                .get("address")
            ),
            "start_time": event.get("start", {}).get("dateTime"),
            "end_time": event.get("end", {}).get("dateTime"),
            "is_online_meeting": event.get("isOnlineMeeting"),
            "body_preview": event.get("bodyPreview"),
        }

    @staticmethod
    def get_recent_meetings(access_token: str, limit: int = 10) -> list[dict]:
        params = {
            "$top": limit,
            "$orderby": "start/dateTime desc",
            "$select": (
                "id,subject,organizer,start,end,isOnlineMeeting,"
                "onlineMeeting,onlineMeetingUrl,bodyPreview"
            ),
        }

        events = GraphClient.get_collection(
            endpoint="/me/events",
            access_token=access_token,
            params=params,
        )

        meetings = []

        for event in events:
            if event.get("isOnlineMeeting"):
                meetings.append(MeetingService._normalize_event(event))

        return meetings

    @staticmethod
    def get_meeting_event(access_token: str, event_id: str) -> dict:
        event = GraphClient.get(
            endpoint=f"/me/events/{GraphClient.quote(event_id)}",
            access_token=access_token,
            params={
                "$select": (
                    "id,subject,organizer,start,end,isOnlineMeeting,"
                    "onlineMeeting,onlineMeetingUrl,bodyPreview"
                )
            },
        )

        return MeetingService._normalize_event(event)

    @staticmethod
    def resolve_online_meeting_id(access_token: str, meeting: dict) -> str | None:
        if meeting.get("online_meeting_id"):
            return meeting["online_meeting_id"]

        join_url = meeting.get("join_url")
        if not join_url:
            return None

        response = GraphClient.get(
            endpoint="/me/onlineMeetings",
            access_token=access_token,
            params={"$filter": f"JoinWebUrl eq '{join_url}'"},
        )

        online_meetings = response.get("value", [])
        if not online_meetings:
            return None

        return online_meetings[0].get("id")
