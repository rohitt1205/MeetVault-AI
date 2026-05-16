import os

from sentence_transformers import SentenceTransformer


EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")


class EmbeddingService:
    _model = None

    @classmethod
    def get_model(cls):
        if cls._model is None:
            cls._model = SentenceTransformer(EMBEDDING_MODEL_NAME)

        return cls._model

    @staticmethod
    def generate_embeddings(chunks: list[dict]) -> list[dict]:
        if not chunks:
            return []

        model = EmbeddingService.get_model()
        texts = [chunk["text"] for chunk in chunks]
        embeddings = model.encode(texts, convert_to_numpy=True).tolist()

        embedded_chunks = []
        for chunk, embedding in zip(chunks, embeddings):
            embedded_chunks.append({
                **chunk,
                "embedding": embedding,
            })

        return embedded_chunks

    @staticmethod
    def generate_query_embedding(query: str) -> list[float]:
        model = EmbeddingService.get_model()
        return model.encode(query).tolist()
