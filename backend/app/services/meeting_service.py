import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse, urlunparse

from fastapi import HTTPException

from app.services.graph_client import GraphClient

TEAMS_MEETUP_PATTERN = re.compile(
    r"meetup-join/(?P<thread>[^/?#]+)",
    re.IGNORECASE,
)
TEAMS_JOIN_URL_PATTERN = re.compile(
    r"https://teams\.microsoft\.com/l/meetup-join/[^\s\"'<>]+",
    re.IGNORECASE,
)


class MeetingService:
    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
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
    def _normalize_event(event: dict) -> dict:
        online_meeting = event.get("onlineMeeting") or {}
        organizer_email = (event.get("organizer") or {}).get("emailAddress") or {}

        return {
            "meeting_id": event.get("id"),
            "event_id": event.get("id"),
            "online_meeting_id": online_meeting.get("id"),
            "join_url": online_meeting.get("joinUrl") or event.get("onlineMeetingUrl"),
            "title": event.get("subject") or "Untitled meeting",
            "organizer": organizer_email.get("name") or "Unknown Organizer",
            "organizer_email": organizer_email.get("address"),
            "start_time": event.get("start", {}).get("dateTime"),
            "end_time": event.get("end", {}).get("dateTime"),
            "is_online_meeting": event.get("isOnlineMeeting"),
            "body_preview": event.get("bodyPreview"),
        }

    @staticmethod
    def _escape_odata_string(value: str) -> str:
        return value.replace("'", "''")

    @staticmethod
    def _normalize_join_url_key(join_url: str) -> str:
        return unquote(unquote(join_url)).strip().rstrip("/").lower()

    @staticmethod
    def _extract_join_url_from_text(text: str) -> str | None:
        if not text:
            return None
        match = TEAMS_JOIN_URL_PATTERN.search(text)
        return match.group(0) if match else None

    @staticmethod
    def _subjects_similar(left: str | None, right: str | None) -> bool:
        left_norm = (left or "").strip().lower()
        right_norm = (right or "").strip().lower()
        if not left_norm or not right_norm:
            return True
        return (
            left_norm == right_norm
            or left_norm in right_norm
            or right_norm in left_norm
        )

    @staticmethod
    def get_recent_meetings(
        access_token: str,
        limit: int = 10,
        *,
        lookback_days: int = 60,
        scan_limit: int | None = None,
    ) -> list[dict]:
        now = datetime.now(timezone.utc)
        params = {
            "startDateTime": (now - timedelta(days=lookback_days)).isoformat(),
            "endDateTime": (now + timedelta(days=1)).isoformat(),
            "$top": 100,
            "$select": (
                "id,subject,organizer,start,end,isOnlineMeeting,"
                "onlineMeeting,onlineMeetingUrl,bodyPreview"
            ),
            "$orderby": "end/dateTime desc",
        }

        events = GraphClient.get_collection(
            endpoint="/me/calendarView",
            access_token=access_token,
            params=params,
            max_pages=5,
        )

        meetings = []

        for event in events:
            normalized = MeetingService._normalize_event(event)
            end_time = MeetingService._parse_datetime(normalized.get("end_time"))
            if event.get("isOnlineMeeting") and end_time and end_time <= now:
                meetings.append(normalized)

        meetings.sort(
            key=lambda meeting: (
                MeetingService._parse_datetime(meeting.get("end_time"))
                or MeetingService._parse_datetime(meeting.get("start_time"))
                or datetime.min.replace(tzinfo=timezone.utc)
            ),
            reverse=True,
        )

        max_results = scan_limit if scan_limit is not None else limit
        return meetings[:max_results]

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
    def _parse_teams_join_url(join_url: str) -> dict:
        """Extract thread id and organizer Oid from a Teams meetup-join URL."""
        decoded = unquote(unquote(join_url.strip()))
        parsed = urlparse(decoded)
        thread_id = None
        match = TEAMS_MEETUP_PATTERN.search(parsed.path or "")
        if match:
            thread_id = unquote(match.group("thread")).split("/")[0]
            if thread_id.endswith("/0"):
                thread_id = thread_id[:-2]

        organizer_oid = None
        tenant_id = None
        if parsed.query:
            context_values = parse_qs(parsed.query).get("context") or []
            if context_values:
                try:
                    context = json.loads(unquote(context_values[0]))
                except (json.JSONDecodeError, TypeError, ValueError):
                    context = {}
                if isinstance(context, dict):
                    organizer_oid = context.get("Oid")
                    tenant_id = context.get("Tid")

        return {
            "thread_id": thread_id,
            "organizer_oid": organizer_oid,
            "tenant_id": tenant_id,
            "decoded_url": decoded,
        }

    @staticmethod
    def _construct_online_meeting_id_from_join_url(join_url: str) -> str | None:
        """
        Graph onlineMeeting.id is often {organizerOid}_{threadId}, e.g.
        dc17674c-..._19:meeting_...@thread.v2 — derivable from the join link context.
        """
        parsed = MeetingService._parse_teams_join_url(join_url)
        thread_id = parsed.get("thread_id")
        organizer_oid = parsed.get("organizer_oid")
        if not thread_id or not organizer_oid:
            return None

        if not thread_id.startswith("19:"):
            thread_id = unquote(thread_id)

        return f"{organizer_oid}_{thread_id}"

    @staticmethod
    def _teams_join_url_stored_form(join_url: str) -> str:
        """Normalize calendar join URLs to Graph's single-encoded joinWebUrl form."""
        decoded = unquote(unquote(join_url.strip()))
        parsed = urlparse(decoded)
        path = parsed.path or ""
        match = TEAMS_MEETUP_PATTERN.search(path)
        if match:
            thread = unquote(match.group("thread")).split("/")[0]
            encoded_thread = quote(thread, safe="")
            path = f"{path[:match.start('thread')]}{encoded_thread}{path[match.end('thread'):]}"

        query = parsed.query
        if query:
            query_params = parse_qs(query, keep_blank_values=True)
            context_values = query_params.get("context") or []
            if context_values and context_values[0].startswith("{"):
                query_params["context"] = [quote(context_values[0], safe="")]
                query = urlencode(query_params, doseq=True)

        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            path,
            parsed.params,
            query,
            parsed.fragment,
        ))

    @staticmethod
    def _teams_join_url_filter_form(join_url: str) -> str:
        """Double-encode join URL for OData JoinWebUrl eq filter (Graph docs example 3)."""
        stored = MeetingService._teams_join_url_stored_form(join_url)
        return quote(stored, safe="")

    @staticmethod
    def _graph_user_candidates(meeting: dict, join_url: str | None = None) -> list[str]:
        candidates = ["me"]
        organizer_oid = None
        if join_url:
            organizer_oid = MeetingService._parse_teams_join_url(join_url).get("organizer_oid")
        if organizer_oid and organizer_oid not in candidates:
            candidates.append(organizer_oid)
        return candidates

    @staticmethod
    def _verify_online_meeting(
        access_token: str,
        online_meeting_id: str,
        user_id: str = "me",
    ) -> bool:
        try:
            GraphClient.get(
                endpoint=(
                    f"/{user_id}/onlineMeetings/"
                    f"{GraphClient.quote(online_meeting_id)}"
                ),
                access_token=access_token,
                params={"$select": "id"},
            )
            return True
        except HTTPException as exc:
            if MeetingService._is_graph_throttle(exc):
                return False
            if exc.status_code in {400, 404}:
                return False
            if exc.status_code in {401, 403}:
                return False
            raise

    @staticmethod
    def _verify_can_list_transcripts(
        access_token: str,
        online_meeting_id: str,
        user_id: str = "me",
    ) -> bool:
        """Confirm transcript API access — stricter than GET onlineMeeting alone."""
        try:
            GraphClient.get(
                endpoint=(
                    f"/{user_id}/onlineMeetings/"
                    f"{GraphClient.quote(online_meeting_id)}/transcripts"
                ),
                access_token=access_token,
                params={"$select": "id"},
            )
            return True
        except HTTPException as exc:
            if MeetingService._is_graph_throttle(exc):
                return False
            if exc.status_code in {400, 404}:
                return False
            if exc.status_code in {401, 403}:
                return False
            raise

    @staticmethod
    def _first_verified_access(
        access_token: str,
        online_meeting_id: str,
        meeting: dict,
        join_url: str | None,
    ) -> dict[str, str] | None:
        for user_id in MeetingService._graph_user_candidates(meeting, join_url):
            if MeetingService._verify_can_list_transcripts(
                access_token,
                online_meeting_id,
                user_id,
            ):
                return {
                    "online_meeting_id": online_meeting_id,
                    "graph_user_id": user_id,
                }
            if MeetingService._verify_online_meeting(
                access_token,
                online_meeting_id,
                user_id,
            ):
                return {
                    "online_meeting_id": online_meeting_id,
                    "graph_user_id": user_id,
                }
        return None

    @staticmethod
    def list_organized_online_meetings(
        access_token: str,
        *,
        lookback_days: int = 60,
    ) -> list[dict]:
        """Teams meetings the signed-in user organized (used to backfill calendar join URLs)."""
        now = datetime.now(timezone.utc)
        # Graph /me/onlineMeetings does not allow $top (or server-side $filter on all tenants).
        params = {
            "$select": "id,joinWebUrl,subject,startDateTime,endDateTime",
        }
        items = GraphClient.get_collection(
            endpoint="/me/onlineMeetings",
            access_token=access_token,
            params=params,
            max_pages=10,
        )

        cutoff = now - timedelta(days=lookback_days)
        filtered: list[dict] = []
        for item in items:
            start_time = MeetingService._parse_datetime(item.get("startDateTime"))
            if start_time and start_time >= cutoff:
                filtered.append(item)
        return filtered

    @staticmethod
    def enrich_meetings_from_online_index(
        meetings: list[dict],
        online_meetings: list[dict],
    ) -> tuple[list[dict], dict]:
        by_join_url: dict[str, dict] = {}
        by_start: list[tuple[datetime, dict]] = []

        for online_meeting in online_meetings:
            join_web_url = online_meeting.get("joinWebUrl")
            if join_web_url:
                by_join_url[MeetingService._normalize_join_url_key(join_web_url)] = online_meeting
            start_time = MeetingService._parse_datetime(online_meeting.get("startDateTime"))
            if start_time:
                by_start.append((start_time, online_meeting))
        by_start.sort(key=lambda item: item[0])

        stats = {
            "online_meetings_in_index": len(online_meetings),
            "matched_by_join_url": 0,
            "matched_by_start_time": 0,
            "still_missing_join_url": 0,
        }
        enriched_meetings: list[dict] = []

        for meeting in meetings:
            enriched = dict(meeting)
            if enriched.get("join_url") and enriched.get("online_meeting_id"):
                enriched_meetings.append(enriched)
                continue

            join_key = (
                MeetingService._normalize_join_url_key(enriched["join_url"])
                if enriched.get("join_url")
                else None
            )
            if join_key and join_key in by_join_url:
                online_meeting = by_join_url[join_key]
                enriched["join_url"] = enriched.get("join_url") or online_meeting.get("joinWebUrl")
                enriched["online_meeting_id"] = (
                    enriched.get("online_meeting_id") or online_meeting.get("id")
                )
                stats["matched_by_join_url"] += 1
            else:
                start_time = MeetingService._parse_datetime(enriched.get("start_time"))
                if start_time:
                    for online_start, online_meeting in by_start:
                        delta_seconds = abs((online_start - start_time).total_seconds())
                        if delta_seconds > 180:
                            continue
                        if not MeetingService._subjects_similar(
                            enriched.get("title"),
                            online_meeting.get("subject"),
                        ):
                            continue
                        enriched["join_url"] = (
                            enriched.get("join_url") or online_meeting.get("joinWebUrl")
                        )
                        enriched["online_meeting_id"] = (
                            enriched.get("online_meeting_id") or online_meeting.get("id")
                        )
                        stats["matched_by_start_time"] += 1
                        break

            if not enriched.get("join_url"):
                stats["still_missing_join_url"] += 1
            enriched_meetings.append(enriched)

        return enriched_meetings, stats

    @staticmethod
    def enrich_meeting_from_event(access_token: str, meeting: dict) -> dict:
        """calendarView often omits joinUrl; load it from the event when missing."""
        if meeting.get("join_url"):
            return meeting

        event_id = meeting.get("event_id") or meeting.get("meeting_id")
        if not event_id:
            return meeting

        try:
            online_meeting_id, join_url = MeetingService._online_meeting_id_from_event(
                access_token,
                event_id,
            )
        except HTTPException:
            return meeting

        enriched = dict(meeting)
        if join_url:
            enriched["join_url"] = join_url
        if online_meeting_id and not enriched.get("online_meeting_id"):
            enriched["online_meeting_id"] = online_meeting_id
        if not enriched.get("join_url"):
            preview_url = MeetingService._extract_join_url_from_text(
                enriched.get("body_preview") or "",
            )
            if preview_url:
                enriched["join_url"] = preview_url
        return enriched

    @staticmethod
    def _join_url_lookup_candidates(join_url: str) -> list[str]:
        """
        Graph expects JoinWebUrl filter values URL-encoded (see onlineMeeting-get examples).
        Calendar often returns a decoded URL; try Graph-normalized and double-encoded forms first.
        """
        candidates: list[str] = []
        seen: set[str] = set()

        for value in (
            MeetingService._teams_join_url_filter_form(join_url),
            MeetingService._teams_join_url_stored_form(join_url),
            join_url,
            unquote(join_url),
            unquote(unquote(join_url)),
        ):
            if not value or value in seen:
                continue
            seen.add(value)
            candidates.append(value)

            encoded = quote(value, safe="")
            if encoded not in seen:
                seen.add(encoded)
                candidates.append(encoded)

        return candidates

    @staticmethod
    def _lookup_online_meeting_by_join_url(access_token: str, join_url: str) -> str | None:
        for candidate in MeetingService._join_url_lookup_candidates(join_url):
            escaped_join_url = MeetingService._escape_odata_string(candidate)
            try:
                response = GraphClient.get(
                    endpoint="/me/onlineMeetings",
                    access_token=access_token,
                    params={
                        "$filter": f"JoinWebUrl eq '{escaped_join_url}'",
                        "$select": "id,joinWebUrl",
                    },
                )
            except HTTPException as exc:
                if MeetingService._is_graph_throttle(exc):
                    return None
                if exc.status_code in {400, 404}:
                    continue
                if exc.status_code in {401, 403}:
                    return None
                raise

            online_meetings = response.get("value", [])
            if online_meetings:
                return online_meetings[0].get("id")

            # Alternate key form: GET /me/onlineMeetings(joinWebUrl='...')
            try:
                keyed = GraphClient.get(
                    endpoint=f"/me/onlineMeetings(joinWebUrl='{escaped_join_url}')",
                    access_token=access_token,
                    params={"$select": "id,joinWebUrl"},
                )
                if keyed.get("id"):
                    return keyed.get("id")
            except HTTPException as exc:
                if exc.status_code not in {400, 404}:
                    if MeetingService._is_graph_throttle(exc):
                        return None
                    if exc.status_code in {401, 403}:
                        return None
                    raise

        return None

    @staticmethod
    def _is_graph_throttle(exc: HTTPException) -> bool:
        detail = exc.detail
        if exc.status_code == 429:
            return True
        if isinstance(detail, dict):
            return detail.get("graph_code") in {
                "ApplicationThrottled",
                "TooManyRequests",
                "activityLimitReached",
            }
        return False

    @staticmethod
    def _online_meeting_id_from_event(access_token: str, event_id: str) -> tuple[str | None, str | None]:
        """Returns (online_meeting_id, join_url) from the calendar event."""
        event = GraphClient.get(
            endpoint=f"/me/events/{GraphClient.quote(event_id)}",
            access_token=access_token,
            params={
                "$select": (
                    "onlineMeeting,onlineMeetingUrl,isOnlineMeeting,bodyPreview,subject"
                ),
            },
        )
        online_meeting = event.get("onlineMeeting") or {}
        join_url = online_meeting.get("joinUrl") or event.get("onlineMeetingUrl")
        if not join_url:
            join_url = MeetingService._extract_join_url_from_text(
                event.get("bodyPreview") or "",
            )
        return online_meeting.get("id"), join_url

    @staticmethod
    def resolve_online_meeting(
        access_token: str,
        meeting: dict,
    ) -> dict[str, str] | None:
        """
        Resolve calendar meeting → Graph onlineMeeting id and the user path (/me or /users/{id})
        that can access transcripts/recordings. Never returns an id we could not verify.
        """
        meeting = MeetingService.enrich_meeting_from_event(access_token, meeting)
        join_url = meeting.get("join_url")

        for candidate_id in (
            meeting.get("online_meeting_id"),
        ):
            if not candidate_id:
                continue
            verified = MeetingService._first_verified_access(
                access_token,
                candidate_id,
                meeting,
                join_url,
            )
            if verified:
                return verified

        if not join_url:
            return None

        constructed = MeetingService._construct_online_meeting_id_from_join_url(join_url)
        if constructed:
            verified = MeetingService._first_verified_access(
                access_token,
                constructed,
                meeting,
                join_url,
            )
            if verified:
                return verified

        looked_up = MeetingService._lookup_online_meeting_by_join_url(access_token, join_url)
        if looked_up:
            return MeetingService._first_verified_access(
                access_token,
                looked_up,
                meeting,
                join_url,
            )

        return None

    @staticmethod
    def resolve_online_meeting_id(access_token: str, meeting: dict) -> str | None:
        resolved = MeetingService.resolve_online_meeting(access_token, meeting)
        if not resolved:
            return None
        return resolved["online_meeting_id"]
