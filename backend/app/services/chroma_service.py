import os

import chromadb


CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "./chroma_db")
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "meetvault_transcripts")


class ChromaService:
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    collection = client.get_or_create_collection(name=CHROMA_COLLECTION_NAME)

    @staticmethod
    def _metadata_for_chunk(chunk: dict) -> dict:
        chunk_metadata = chunk.get("metadata", {})

        return {
            "meeting_id": chunk.get("meeting_id"),
            "meeting_title": chunk.get("meeting_title"),
            "chunk_index": chunk.get("chunk_index"),
            "source_type": chunk.get("source_type"),
            "speaker_start": chunk_metadata.get("speaker_start"),
            "speaker_end": chunk_metadata.get("speaker_end"),
            "start_timestamp": chunk_metadata.get("start_timestamp"),
            "end_timestamp": chunk_metadata.get("end_timestamp"),
            "turn_count": chunk_metadata.get("turn_count"),
        }

    @staticmethod
    def store_embeddings(embedded_chunks: list[dict]) -> dict:
        if not embedded_chunks:
            return {
                "message": "No chunks to store",
                "stored_chunks": 0,
            }

        ChromaService.collection.upsert(
            ids=[str(chunk["chunk_id"]) for chunk in embedded_chunks],
            embeddings=[chunk["embedding"] for chunk in embedded_chunks],
            documents=[chunk["text"] for chunk in embedded_chunks],
            metadatas=[
                ChromaService._metadata_for_chunk(chunk)
                for chunk in embedded_chunks
            ],
        )

        return {
            "message": "Embeddings stored successfully",
            "stored_chunks": len(embedded_chunks),
        }

    @staticmethod
    def query_embeddings(
        query_embedding: list[float],
        *,
        meeting_id: str | None = None,
        n_results: int = 5,
    ) -> dict:
        where = {"meeting_id": meeting_id} if meeting_id else None

        return ChromaService.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
        )
