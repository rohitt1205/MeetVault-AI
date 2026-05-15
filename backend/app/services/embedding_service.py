from sentence_transformers import SentenceTransformer


class EmbeddingService:

    model = SentenceTransformer("all-MiniLM-L6-v2")

    @staticmethod
    def generate_embeddings(chunks):

        embedded_chunks = []

        for chunk in chunks:

            embedding = EmbeddingService.model.encode(
                chunk["text"]
            ).tolist()

            embedded_chunks.append({
                "chunk_id": chunk["chunk_id"],
                "text": chunk["text"],
                "embedding": embedding,
                "metadata": chunk["metadata"]
            })

        return embedded_chunks
    
    @staticmethod
    def generate_query_embedding(query):

        embedding = EmbeddingService.model.encode(
            query
        ).tolist()

        return embedding