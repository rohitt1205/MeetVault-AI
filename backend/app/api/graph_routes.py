from fastapi import APIRouter, Header, HTTPException, Query

from app.services.chroma_service import ChromaService
from app.services.embedding_service import EmbeddingService
from app.services.ingestion_service import IngestionService
from app.services.ingestion_state_service import IngestionStateService
from app.services.meeting_service import MeetingService

router = APIRouter()


def get_access_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Bearer token missing")

    return token


@router.get("/meetings/recent")
def fetch_recent_meetings(
    authorization: str = Header(None),
    limit: int = Query(10, ge=1, le=50),
):
    access_token = get_access_token(authorization)
    return MeetingService.get_recent_meetings(access_token, limit=limit)


@router.post("/ingestion/meetings/{event_id}")
def ingest_meeting(
    event_id: str,
    authorization: str = Header(None),
):
    access_token = get_access_token(authorization)
    return IngestionService.ingest_meeting(access_token, event_id)


@router.post("/ingestion/recent")
def ingest_recent_meetings(
    authorization: str = Header(None),
    limit: int = Query(5, ge=1, le=20),
):
    access_token = get_access_token(authorization)
    return IngestionService.ingest_recent_meetings(access_token, limit=limit)


@router.get("/search")
def semantic_search(
    query: str = Query(..., min_length=1),
    meeting_id: str | None = Query(None),
    x_meeting_context: str | None = Header(None, alias="X-Meeting-Context"),
):
    scoped_meeting_id = meeting_id or x_meeting_context
    query_embedding = EmbeddingService.generate_query_embedding(query)
    results = ChromaService.query_embeddings(
        query_embedding,
        meeting_id=scoped_meeting_id,
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

    return {
        "query": query,
        "meeting_id": scoped_meeting_id,
        "results": response,
    }


@router.get("/ingestion/status/{meeting_id}")
def get_ingestion_status(meeting_id: str):
    return IngestionStateService.get_status(meeting_id)


@router.get("/ingestion/status")
def get_all_ingestion_statuses():
    return IngestionStateService.get_all_statuses()
