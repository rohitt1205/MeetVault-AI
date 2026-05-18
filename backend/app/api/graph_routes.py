from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_access_token
from app.services.answer_service import AnswerService
from app.services.chroma_service import ChromaService, MICROSOFT_SOURCE_TYPES
from app.services.embedding_service import EmbeddingService
from app.services.ingestion_service import IngestionService
from app.services.ingestion_state_service import IngestionStateService
from app.services.meeting_catalog_service import MeetingCatalogService
from app.services.meeting_service import MeetingService
from app.services.recording_service import RecordingService
from app.services.token_diagnostics_service import TokenDiagnosticsService
from app.services.transcript_service import TranscriptService

router = APIRouter()


class CatalogMergePayload(BaseModel):
    teams: dict[str, Any]
    onedrive: dict[str, Any]


class OnedriveDiscoverPayload(BaseModel):
    meeting_titles: list[str] | None = None


def get_graph_access_token(authorization: str | None = Header(None)) -> str:
    token = get_access_token(authorization)
    diagnostics = TokenDiagnosticsService.inspect(token)

    if not diagnostics.get("is_graph_token"):
        raise HTTPException(
            status_code=401,
            detail=(
                "Microsoft Graph provider token missing or invalid. "
                "Sign out and sign in again so Supabase returns provider_token."
            ),
        )

    return token


@router.get("/meetings/recent")
def fetch_recent_meetings(
    authorization: str = Header(None),
    limit: int = Query(10, ge=1, le=50),
):
    access_token = get_graph_access_token(authorization)
    meetings = MeetingService.get_recent_meetings(access_token, limit=limit)

    for meeting in meetings:
        status_payload = IngestionStateService.get_status(meeting["event_id"])
        meeting["status"] = status_payload.get("status", "NOT_STARTED")
        meeting["ingestion"] = status_payload

    return meetings


@router.get("/meetings/catalog")
def get_meeting_catalog(authorization: str = Header(None)):
    get_access_token(authorization)
    return MeetingCatalogService.get_catalog()


@router.post("/meetings/catalog/discover/teams")
def discover_teams_catalog(
    authorization: str = Header(None),
    limit: int = Query(30, ge=1, le=50),
    scan_graph: bool = Query(
        False,
        description="When true, probe Graph for Teams transcripts per meeting (slower).",
    ),
):
    access_token = get_graph_access_token(authorization)
    return MeetingCatalogService.discover_teams(access_token, limit=limit, scan_graph=scan_graph)


@router.post("/meetings/catalog/discover/onedrive")
def discover_onedrive_catalog(
    authorization: str = Header(None),
    video_limit: int = Query(200, ge=1, le=500),
    payload: OnedriveDiscoverPayload | None = Body(default=None),
):
    access_token = get_graph_access_token(authorization)
    meeting_titles = payload.meeting_titles if payload else None
    return MeetingCatalogService.discover_onedrive(
        access_token,
        video_limit=video_limit,
        meeting_titles=meeting_titles,
    )


@router.post("/meetings/catalog/merge")
def merge_meeting_catalog(
    payload: CatalogMergePayload,
    authorization: str = Header(None),
):
    """
    Merge prior discover/teams and discover/onedrive payloads into the in-memory catalog.
    """
    get_graph_access_token(authorization)
    return MeetingCatalogService.merge_discovery_sources(payload.teams, payload.onedrive)


@router.post("/meetings/catalog/sync")
def sync_meeting_catalog(
    authorization: str = Header(None),
    limit: int = Query(30, ge=1, le=50),
    scan_graph: bool = Query(
        False,
        description="When true, include per-meeting Graph transcript discovery in the Teams leg.",
    ),
):
    access_token = get_graph_access_token(authorization)
    return MeetingCatalogService.sync_catalog(access_token, limit=limit, scan_graph=scan_graph)


@router.get("/meetings/catalog/debug")
def debug_meeting_resolution(
    authorization: str = Header(None),
    event_id: str | None = Query(None, description="Calendar event id to test; defaults to latest Teams meeting"),
):
    """
    Postman-friendly probe: shows how one calendar event resolves to Graph
    onlineMeeting id / transcripts. Use the same Bearer token as the app.
    """
    access_token = get_graph_access_token(authorization)
    token_info = TokenDiagnosticsService.inspect(access_token)

    if event_id:
        meeting = MeetingService.get_meeting_event(access_token, event_id)
    else:
        recent = MeetingService.get_recent_meetings(access_token, limit=1)
        if not recent:
            raise HTTPException(status_code=404, detail="No past Teams meetings found on calendar.")
        meeting = recent[0]
        event_id = meeting.get("event_id")

    result = {
        "token": {
            "is_graph_token": token_info.get("is_graph_token"),
            "scopes": token_info.get("scopes"),
            "missing_scopes": token_info.get("missing_scopes"),
        },
        "calendar_event": {
            "event_id": event_id,
            "title": meeting.get("title"),
            "start_time": meeting.get("start_time"),
            "join_url_from_calendar_view": meeting.get("join_url"),
            "online_meeting_id_from_calendar_view": meeting.get("online_meeting_id"),
        },
        "event_fetch": None,
        "resolved_online_meeting_id": None,
        "recordings_count": 0,
        "transcripts_count": 0,
        "errors": [],
    }

    try:
        online_id, join_url = MeetingService._online_meeting_id_from_event(
            access_token,
            event_id,
        )
        result["event_fetch"] = {
            "online_meeting_id": online_id,
            "join_url": join_url,
        }
    except HTTPException as exc:
        result["errors"].append({"step": "GET /me/events/{id}", "detail": exc.detail})

    join_parse = MeetingService._parse_teams_join_url(meeting.get("join_url") or "")
    result["join_url_parse"] = {
        **join_parse,
        "constructed_online_meeting_id": MeetingService._construct_online_meeting_id_from_join_url(
            meeting.get("join_url") or "",
        ),
    }

    resolved = MeetingService.resolve_online_meeting(access_token, meeting)
    result["resolved"] = resolved
    result["resolved_online_meeting_id"] = (
        resolved["online_meeting_id"] if resolved else None
    )

    if resolved:
        graph_user_id = resolved["graph_user_id"]
        online_meeting_id = resolved["online_meeting_id"]
        try:
            recordings = RecordingService.list_online_meeting_recordings(
                access_token,
                online_meeting_id,
                user_id=graph_user_id,
            )
            result["recordings_count"] = len(recordings)
        except HTTPException as exc:
            result["errors"].append({"step": "list recordings", "detail": exc.detail})

        try:
            transcripts = TranscriptService.list_online_meeting_transcripts(
                access_token,
                online_meeting_id,
                user_id=graph_user_id,
            )
            result["transcripts_count"] = len(transcripts)
        except HTTPException as exc:
            result["errors"].append({"step": "list transcripts", "detail": exc.detail})

    return result


@router.post("/ingestion/meetings/{event_id}")
def ingest_meeting(
    event_id: str,
    authorization: str = Header(None),
):
    access_token = get_graph_access_token(authorization)
    return IngestionService.ingest_meeting(access_token, event_id)


@router.post("/ingestion/meetings/{event_id}/start")
def start_meeting_ingestion(
    event_id: str,
    authorization: str = Header(None),
):
    access_token = get_graph_access_token(authorization)
    return IngestionService.start_meeting_ingestion(access_token, event_id)


@router.delete("/ingestion/meetings/{meeting_id}")
def delete_meeting_ingestion(
    meeting_id: str,
    authorization: str = Header(None),
):
    get_access_token(authorization)
    IngestionStateService.request_cancel(meeting_id)
    chroma_result = ChromaService.delete_meeting_embeddings(meeting_id)
    ingestion_status = IngestionStateService.clear_status(meeting_id)
    IngestionStateService.clear_cancel(meeting_id)
    MeetingCatalogService.mark_meeting_unindexed(meeting_id)
    return {
        "meeting_id": meeting_id,
        "deleted_chunks": chroma_result.get("deleted_chunks", 0),
        "ingestion": ingestion_status,
    }


@router.post("/ingestion/recent")
def ingest_recent_meetings(
    authorization: str = Header(None),
    limit: int = Query(20, ge=1, le=50),
):
    access_token = get_graph_access_token(authorization)
    return IngestionService.ingest_recent_meetings(access_token, limit=limit)


@router.post("/ingestion/workspace-sync")
def start_workspace_sync(
    authorization: str = Header(None),
    limit: int = Query(20, ge=1, le=50),
):
    access_token = get_graph_access_token(authorization)
    return IngestionService.start_workspace_sync(access_token, limit=limit)


@router.get("/ingestion/recording-assets")
def discover_recording_assets(
    authorization: str = Header(None),
    limit: int = Query(20, ge=1, le=50),
    fast: bool = Query(True, description="Skip slow OneDrive scans; parallelize Graph lookups"),
):
    access_token = get_graph_access_token(authorization)
    return IngestionService.discover_recording_assets(access_token, limit=limit, fast=fast)


@router.get("/search")
def semantic_search(
    query: str = Query(..., min_length=1),
    meeting_id: str | None = Query(None),
    x_meeting_context: str | None = Header(None, alias="X-Meeting-Context"),
    authorization: str = Header(None),
):
    get_access_token(authorization)
    scoped_meeting_id = meeting_id or x_meeting_context
    query_embedding = EmbeddingService.generate_query_embedding(query)
    results = ChromaService.query_embeddings(
        query_embedding,
        meeting_id=scoped_meeting_id,
        allowed_source_types=MICROSOFT_SOURCE_TYPES,
    )

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    ids = results.get("ids", [[]])[0]

    response = []
    for index, doc in enumerate(documents):
        response.append({
            "chunk_id": ids[index] if index < len(ids) else index + 1,
            "text": doc,
            "metadata": metadatas[index] if index < len(metadatas) else {},
            "distance": distances[index] if index < len(distances) else None,
        })

    composed = AnswerService.compose(query, response)
    answer_text = composed.get("text") if isinstance(composed, dict) else composed
    answer_mode = composed.get("mode") if isinstance(composed, dict) else None

    return {
        "query": query,
        "meeting_id": scoped_meeting_id,
        "answer": answer_text,
        "answer_mode": answer_mode,
        "results": response,
    }


@router.get("/ingestion/status/{meeting_id}")
def get_ingestion_status(meeting_id: str, authorization: str = Header(None)):
    get_access_token(authorization)
    return IngestionStateService.get_status(meeting_id)


@router.get("/ingestion/status")
def get_all_ingestion_statuses(authorization: str = Header(None)):
    get_access_token(authorization)
    return IngestionStateService.get_all_statuses()


@router.get("/ingestion/workspace-status")
def get_workspace_sync_status(authorization: str = Header(None)):
    get_access_token(authorization)
    return IngestionStateService.get_workspace_sync_status()


@router.get("/vector-store/status")
def get_vector_store_status(authorization: str = Header(None)):
    get_access_token(authorization)
    return ChromaService.get_status()


@router.get("/auth/diagnostics")
def get_auth_diagnostics(authorization: str = Header(None)):
    access_token = get_access_token(authorization)
    return TokenDiagnosticsService.inspect(access_token)
