from fastapi import APIRouter, HTTPException, Header
from app.api.mcp_routes import get_user_key_from_header
from pydantic import BaseModel
from app.rag.ingest import ingest_transcript
from app.rag.retrieve import retrieve_and_answer
from app.rag.dummy_data import DUMMY_MEETING_TRANSCRIPT

router = APIRouter(prefix="/rag", tags=["RAG Pipeline"])

class IngestRequest(BaseModel):
    text: str
    
class QueryRequest(BaseModel):
    query: str
    meeting_id: str | None = None

@router.post("/ingest")
def ingest_text(request: IngestRequest):
    """
    Ingests any given text into ChromaDB after chunking and embedding.
    """
    try:
        result = ingest_transcript(request.text)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ingest_dummy")
def ingest_dummy_data():
    """
    Convenience endpoint for the hackathon to load dummy data quickly.
    """
    try:
        result = ingest_transcript(DUMMY_MEETING_TRANSCRIPT)
        return {"message": "Dummy data ingested successfully", "details": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/query")
def query_rag(request: QueryRequest, authorization: str = Header(None)):
    """
    Queries the RAG pipeline with a user question and returns the grounded answer.
    """
    try:
        user_key = get_user_key_from_header(authorization)
        result = retrieve_and_answer(request.query, meeting_id=request.meeting_id, user_key=user_key)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
