import chromadb


class ChromaService:

    client = chromadb.PersistentClient(
        path="./chroma_db"
    )

    collection = client.get_or_create_collection(
        name="meetvault_transcripts"
    )

    @staticmethod
    def store_embeddings(embedded_chunks):

        for chunk in embedded_chunks:

            ChromaService.collection.add(
                ids=[str(chunk["chunk_id"])],
                embeddings=[chunk["embedding"]],
                documents=[chunk["text"]],
                metadatas=[{
                    "source": "meeting_transcript"
                }]
            )

        return {
            "message": "Embeddings stored successfully"
        }

    @staticmethod
    def query_embeddings(query_embedding):

        results = ChromaService.collection.query(
            query_embeddings=[query_embedding],
            n_results=3
        )

        return results