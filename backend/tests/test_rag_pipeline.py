import unittest
from unittest.mock import patch

from app.rag.ingest import ingest_transcript
from app.rag.retrieve import retrieve_and_answer


class RagPipelineTests(unittest.TestCase):
    def test_ingest_transcript_uses_current_chunk_and_embedding_pipeline(self):
        with patch("app.rag.ingest.EmbeddingService.generate_embeddings") as mock_embed, patch(
            "app.rag.ingest.ChromaService.store_embeddings"
        ) as mock_store:
            mock_embed.return_value = [
                {
                    "chunk_id": "rag-1:1",
                    "meeting_id": "rag-1",
                    "meeting_title": "RAG Ingest rag-1",
                    "source_type": "rag_manual_ingest",
                    "text": "Speaker: transcript ingestion matters.",
                    "embedding": [0.1, 0.2],
                    "metadata": {},
                }
            ]
            mock_store.return_value = {
                "message": "Embeddings stored successfully",
                "stored_chunks": 1,
            }

            result = ingest_transcript("Speaker: transcript ingestion matters.")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chunks_stored"], 1)
        self.assertTrue(result["meeting_id"].startswith("rag-"))
        mock_embed.assert_called_once()
        mock_store.assert_called_once()

    def test_retrieve_and_answer_returns_structured_sources(self):
        fake_results = {
            "documents": [["Chunk one", "Chunk two"]],
            "metadatas": [[{"meeting_id": "upload-1"}, {"meeting_id": "upload-1"}]],
            "ids": [["upload-1:1", "upload-1:2"]],
            "distances": [[0.12, 0.34]],
        }

        with patch(
            "app.rag.retrieve.EmbeddingService.generate_query_embedding",
            return_value=[0.3, 0.4],
        ), patch(
            "app.rag.retrieve.ChromaService.query_embeddings",
            return_value=fake_results,
        ), patch(
            "app.rag.retrieve.generate_answer",
            return_value="Grounded answer",
        ):
            result = retrieve_and_answer("What happened?")

        self.assertEqual(result["query"], "What happened?")
        self.assertEqual(result["answer"], "Grounded answer")
        self.assertEqual(result["answer_mode"], "gemini")
        self.assertEqual(len(result["sources"]), 2)
        self.assertEqual(result["sources"][0]["text"], "Chunk one")
        self.assertEqual(result["sources"][0]["chunk_id"], "upload-1:1")

    def test_retrieve_and_answer_falls_back_to_extractive_answer_when_llm_unavailable(self):
        fake_results = {
            "documents": [[
                "00:00:01.000 Speaker: The system summarizes each call automatically.",
                "00:00:07.000 Speaker: It stores grounded chunks in Chroma for retrieval.",
            ]],
            "metadatas": [[{"meeting_id": "upload-1"}, {"meeting_id": "upload-1"}]],
            "ids": [["upload-1:1", "upload-1:2"]],
            "distances": [[0.12, 0.34]],
        }

        with patch(
            "app.rag.retrieve.EmbeddingService.generate_query_embedding",
            return_value=[0.3, 0.4],
        ), patch(
            "app.rag.retrieve.ChromaService.query_embeddings",
            return_value=fake_results,
        ), patch(
            "app.rag.retrieve.generate_answer",
            side_effect=RuntimeError("GEMINI_API_KEY missing"),
        ):
            result = retrieve_and_answer("summarize the call")

        self.assertEqual(result["answer_mode"], "extractive_summary")
        self.assertIn("The system summarizes each call automatically.", result["answer"])
        self.assertEqual(result["llm_error"], "GEMINI_API_KEY missing")


if __name__ == "__main__":
    unittest.main()
