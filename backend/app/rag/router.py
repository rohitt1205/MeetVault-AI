import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.api.deps import get_access_token
from app.api.mcp_routes import get_user_key_from_header, resolve_tokens
from app.rag.ingest import ingest_transcript
from app.rag.retrieve import retrieve_and_answer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["RAG Pipeline"])


class IngestRequest(BaseModel):
    text: str


class QueryRequest(BaseModel):
    query: str
    meeting_id: str | None = None
    output_format: str | None = None


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


@router.post("/query")
def query_rag(
    request: QueryRequest,
    authorization: str = Header(None),
    x_supabase_token: str | None = Header(None, alias="X-Supabase-Token"),
):
    """
    Queries the RAG pipeline with a user question and returns the grounded answer.
    """
    get_access_token(authorization)
    try:
        user_key = get_user_key_from_header(authorization)
        graph_jwt, supabase_jwt = resolve_tokens(authorization, x_supabase_token)
        result = retrieve_and_answer(
            request.query,
            meeting_id=request.meeting_id,
            user_key=user_key,
            graph_jwt=graph_jwt,
            supabase_jwt=supabase_jwt,
            output_format=request.output_format,
        )
        return result
    except Exception as exc:
        logger.exception("RAG query failed")
        raise HTTPException(status_code=500, detail="Query failed.") from exc

