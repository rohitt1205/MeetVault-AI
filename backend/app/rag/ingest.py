import hashlib

from app.services.chunk_service import ChunkService
from app.services.chroma_service import ChromaService
from app.services.embedding_service import EmbeddingService
from app.services.transcript_service import TranscriptService

def ingest_transcript(transcript_text: str):
    """
    Ingests free-form transcript text into the current ChromaDB collection using
    the same chunking and embedding pipeline as the main meeting ingestion flow.
    """
    normalized_transcript = TranscriptService.normalize_transcript(transcript_text)
    if not normalized_transcript:
        return {
            "status": "error",
            "chunks_stored": 0,
            "message": "No transcript text could be parsed from the provided input.",
        }

    transcript_hash = hashlib.sha1(transcript_text.encode("utf-8")).hexdigest()[:12]
    meeting_id = f"rag-{transcript_hash}"
    meeting_title = f"RAG Ingest {transcript_hash}"
    chunks = ChunkService.chunk_transcript(
        normalized_transcript,
        meeting_id=meeting_id,
        meeting_title=meeting_title,
        source_type="rag_manual_ingest",
        max_words=120,
        overlap_turns=1,
    )
    embedded_chunks = EmbeddingService.generate_embeddings(chunks)
    result = ChromaService.store_embeddings(embedded_chunks)

    return {
        "status": "success",
        "chunks_stored": len(embedded_chunks),
        "meeting_id": meeting_id,
        "meeting_title": meeting_title,
        "message": result.get("message", "Ingestion complete")
    }
