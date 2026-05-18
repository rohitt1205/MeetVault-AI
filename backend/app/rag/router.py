import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.api.deps import get_access_token
from app.rag.dummy_data import DUMMY_MEETING_TRANSCRIPT
from app.rag.ingest import ingest_transcript
from app.rag.retrieve import retrieve_and_answer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["RAG Pipeline"])


class IngestRequest(BaseModel):
    text: str


class QueryRequest(BaseModel):
    query: str
    meeting_id: str | None = None


@router.post("/ingest")
def ingest_text(request: IngestRequest, authorization: str = Header(None)):
    """
    Ingests any given text into ChromaDB after chunking and embedding.
    """
    get_access_token(authorization)
    try:
        result = ingest_transcript(request.text)
        return result
    except Exception as exc:
        logger.exception("RAG ingest failed")
        raise HTTPException(status_code=500, detail="Ingest failed.") from exc


@router.post("/ingest_dummy")
def ingest_dummy_data(authorization: str = Header(None)):
    """
    Convenience endpoint for the hackathon to load dummy data quickly.
    """
    get_access_token(authorization)
    try:
        result = ingest_transcript(DUMMY_MEETING_TRANSCRIPT)
        return {"message": "Dummy data ingested successfully", "details": result}
    except Exception as exc:
        logger.exception("RAG dummy ingest failed")
        raise HTTPException(status_code=500, detail="Dummy ingest failed.") from exc


@router.post("/query")
def query_rag(request: QueryRequest, authorization: str = Header(None)):
    """
    Queries the RAG pipeline with a user question and returns the grounded answer.
    """
    get_access_token(authorization)
    try:
        result = retrieve_and_answer(request.query, meeting_id=request.meeting_id)
        return result
    except Exception as exc:
        logger.exception("RAG query failed")
        raise HTTPException(status_code=500, detail="Query failed.") from exc
