from fastapi import APIRouter, Header, HTTPException
from app.services.meeting_service import MeetingService
from app.services.chunk_service import ChunkService
from app.services.transcript_service import TranscriptService
from app.services.embedding_service import EmbeddingService
from app.services.chroma_service import ChromaService
from fastapi import Query

router = APIRouter()


@router.get("/meetings/recent")
def fetch_recent_meetings(authorization: str = Header(None)):

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header missing"
        )

    access_token = authorization.replace("Bearer ", "")

    meetings = MeetingService.get_recent_meetings(access_token)

    return meetings

@router.get("/transcripts/mock")
def mock_transcript():

    mock_data = [
        {
            "speaker": "Rohit",
            "timestamp": "00:00:05",
            "text": "Welcome everyone to the hackathon."
        },
        {
            "speaker": "Teammate",
            "timestamp": "00:00:15",
            "text": "We will start with Graph API integration."
        }
    ]

    return mock_data

@router.get("/chunks/mock")
def mock_chunks():

    transcript = [
        {
            "speaker": "Rohit",
            "timestamp": "00:00:05",
            "text": "Welcome everyone to the hackathon."
        },
        {
            "speaker": "Teammate",
            "timestamp": "00:00:15",
            "text": "We will start with Graph API integration."
        },
        {
            "speaker": "Rohit",
            "timestamp": "00:00:30",
            "text": "Transcript ingestion is important."
        }
    ]

    normalized = TranscriptService.normalize_transcript(transcript)

    chunks = ChunkService.chunk_transcript(normalized)

    return chunks

@router.get("/pipeline/mock")
def full_pipeline_mock():

    transcript = [
        {
            "speaker": "Rohit",
            "timestamp": "00:00:05",
            "text": "Welcome everyone to the hackathon."
        },
        {
            "speaker": "Teammate",
            "timestamp": "00:00:15",
            "text": "We will start with Graph API integration."
        },
        {
            "speaker": "Rohit",
            "timestamp": "00:00:30",
            "text": "Transcript ingestion is important."
        }
    ]

    normalized = TranscriptService.normalize_transcript(
        transcript
    )

    chunks = ChunkService.chunk_transcript(
        normalized
    )

    embedded_chunks = EmbeddingService.generate_embeddings(
        chunks
    )

    result = ChromaService.store_embeddings(
        embedded_chunks
    )

    return result

@router.get("/search")
def semantic_search(query: str = Query(...)):

    query_embedding = EmbeddingService.generate_query_embedding(
        query
    )

    results = ChromaService.query_embeddings(
        query_embedding
    )

    documents = results.get("documents", [[]])[0]

    response = []

    for index, doc in enumerate(documents):

        response.append({
            "chunk_id": index + 1,
            "text": doc
        })

    return {
        "query": query,
        "results": response
    }