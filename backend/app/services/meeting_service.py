from app.services.graph_client import GraphClient


class MeetingService:

    @staticmethod
    def get_recent_meetings(access_token: str):

        endpoint = "/me/events"

        response = GraphClient.make_get_request(
            endpoint=endpoint,
            access_token=access_token
        )

        events = response.get("value", [])

        normalized_meetings = []

        for event in events:

            if not event.get("isOnlineMeeting"):
                continue

            normalized_meetings.append({
                "meeting_id": event.get("id"),
                "title": event.get("subject"),
                "organizer": event.get("organizer", {})
                                  .get("emailAddress", {})
                                  .get("name"),
                "start_time": event.get("start", {}).get("dateTime"),
                "end_time": event.get("end", {}).get("dateTime"),
                "is_online_meeting": event.get("isOnlineMeeting")
            })

        return normalized_meetings