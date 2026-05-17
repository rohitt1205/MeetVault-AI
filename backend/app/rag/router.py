from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.rag.ingest import ingest_transcript
from app.rag.retrieve import retrieve_and_answer
from app.rag.dummy_data import DUMMY_MEETING_TRANSCRIPT

router = APIRouter(prefix="/rag", tags=["RAG Pipeline"])

class IngestRequest(BaseModel):
    text: str
    
class QueryRequest(BaseModel):
    query: str
<<<<<<< HEAD
    meeting_id: str | None = None
=======
>>>>>>> origin/main

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
def query_rag(request: QueryRequest):
    """
    Queries the RAG pipeline with a user question and returns the grounded answer.
    """
    try:
<<<<<<< HEAD
        result = retrieve_and_answer(request.query, meeting_id=request.meeting_id)
=======
        result = retrieve_and_answer(request.query)
>>>>>>> origin/main
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
