import os

import chromadb


CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "./chroma_db")
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "meetvault_transcripts")

MICROSOFT_SOURCE_TYPES = {
    "graph_transcript",
    "graph_recording_transcription",
    "onedrive_transcript",
    "onedrive_video_transcription",
    "sharepoint_transcript",
    "sharepoint_recording_transcription",
}


class ChromaService:
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    collection = client.get_or_create_collection(name=CHROMA_COLLECTION_NAME)

    @staticmethod
    def _is_live_metadata(metadata: dict | None) -> bool:
        return isinstance(metadata, dict) and bool(metadata.get("meeting_id"))

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
        candidate_pool_size: int | None = None,
        allowed_source_types: set[str] | None = None,
    ) -> dict:
        where = {"meeting_id": meeting_id} if meeting_id else None
        collection_count = ChromaService.collection.count()
        if collection_count == 0:
            return {
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "ids": [[]],
            }

        requested_pool_size = candidate_pool_size or max(n_results * 10, 50)
        raw_limit = min(
            collection_count,
            n_results if meeting_id else max(requested_pool_size, n_results),
        )
        response = ChromaService.collection.query(
            query_embeddings=[query_embedding],
            n_results=raw_limit,
            where=where,
        )

        documents = response.get("documents", [[]])[0]
        metadatas = response.get("metadatas", [[]])[0]
        distances = response.get("distances", [[]])[0]
        ids = response.get("ids", [[]])[0]

        filtered_documents = []
        filtered_metadatas = []
        filtered_distances = []
        filtered_ids = []

        for index, document in enumerate(documents):
            metadata = metadatas[index] if index < len(metadatas) else {}
            if not ChromaService._is_live_metadata(metadata):
                continue
            if (
                allowed_source_types is not None
                and metadata.get("source_type") not in allowed_source_types
            ):
                continue

            filtered_documents.append(document)
            filtered_metadatas.append(metadata)
            filtered_distances.append(
                distances[index] if index < len(distances) else None
            )
            filtered_ids.append(ids[index] if index < len(ids) else str(index + 1))

            if len(filtered_documents) == n_results:
                break

        return {
            "documents": [filtered_documents],
            "metadatas": [filtered_metadatas],
            "distances": [filtered_distances],
            "ids": [filtered_ids],
        }

    @staticmethod
    def has_meeting_embeddings(meeting_id: str) -> bool:
        if not meeting_id:
            return False

        results = ChromaService.collection.get(
            where={"meeting_id": meeting_id},
            limit=1,
        )
        return bool(results.get("ids"))

    @staticmethod
    def get_status() -> dict:
        data = ChromaService.collection.get()
        metadatas = data.get("metadatas", [])
        ids = data.get("ids", [])
        documents = data.get("documents", [])
        source_counts = {}

        indexed_count = sum(
            1
            for metadata in metadatas
            if isinstance(metadata, dict) and metadata.get("meeting_id")
        )
        legacy_count = len(ids) - indexed_count
        sample_chunks = []

        for chunk_id, metadata, document in zip(ids[-5:], metadatas[-5:], documents[-5:]):
            source_type = metadata.get("source_type") if isinstance(metadata, dict) else None
            if source_type:
                source_counts[source_type] = source_counts.get(source_type, 0) + 1
            sample_chunks.append({
                "chunk_id": chunk_id,
                "meeting_id": metadata.get("meeting_id") if isinstance(metadata, dict) else None,
                "meeting_title": metadata.get("meeting_title") if isinstance(metadata, dict) else None,
                "source_type": source_type,
                "preview": (document or "")[:140],
            })

        for metadata in metadatas[:-5]:
            if isinstance(metadata, dict) and metadata.get("source_type"):
                source_type = metadata["source_type"]
                source_counts[source_type] = source_counts.get(source_type, 0) + 1

        return {
            "db_path": CHROMA_DB_PATH,
            "collection_name": CHROMA_COLLECTION_NAME,
            "document_count": ChromaService.collection.count(),
            "indexed_document_count": indexed_count,
            "legacy_document_count": legacy_count,
            "source_counts": source_counts,
            "sample_chunks": sample_chunks,
        }

    @staticmethod
    def remove_legacy_documents() -> dict:
        data = ChromaService.collection.get()
        ids = data.get("ids", [])
        metadatas = data.get("metadatas", [])
        legacy_ids = [
            chunk_id
            for chunk_id, metadata in zip(ids, metadatas)
            if not ChromaService._is_live_metadata(metadata)
        ]

        if legacy_ids:
            ChromaService.collection.delete(ids=legacy_ids)

        return {
            "removed": len(legacy_ids),
            "ids": legacy_ids,
        }
