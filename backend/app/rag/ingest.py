<<<<<<< HEAD
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
=======
from sentence_transformers import SentenceTransformer
import uuid
from app.services.chroma_service import ChromaService

# Load the embedding model globally so it's not reloaded on every call
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50):
    """
    Splits text into smaller chunks for embedding, using a sliding window approach.
    """
    words = text.split()
    chunks = []
    
    # Very basic chunking logic for hackathon simplicity
    for i in range(0, len(words), chunk_size - overlap):
        chunk_words = words[i:i + chunk_size]
        if not chunk_words:
            break
        chunks.append(" ".join(chunk_words))
        
        # Break if we've reached the end
        if i + chunk_size >= len(words):
            break
            
    return chunks

def ingest_transcript(transcript_text: str):
    """
    Chunks a transcript, generates embeddings, and stores them in ChromaDB.
    """
    # 1. Chunk the transcript
    chunks = chunk_text(transcript_text, chunk_size=100, overlap=20)
    
    embedded_chunks = []
    
    # 2. Generate embeddings
    for chunk in chunks:
        # Generate embedding for the chunk
        embedding = embedding_model.encode(chunk).tolist()
        
        embedded_chunks.append({
            "chunk_id": str(uuid.uuid4()),
            "text": chunk,
            "embedding": embedding
        })
        
    # 3. Store in ChromaDB
    # ChromaService has a method store_embeddings(embedded_chunks)
    result = ChromaService.store_embeddings(embedded_chunks)
    
    return {
        "status": "success",
        "chunks_stored": len(embedded_chunks),
>>>>>>> origin/main
        "message": result.get("message", "Ingestion complete")
    }
