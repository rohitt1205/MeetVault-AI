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
            "documents": [[
                "Speaker: The team reviewed project blockers and assigned follow up owners for delivery.",
                "Speaker: The meeting ended with clear action items for the integration milestone.",
            ]],
            "metadatas": [[
                {"meeting_id": "upload-1", "source_type": "sharepoint_recording_transcription"},
                {"meeting_id": "upload-1", "source_type": "sharepoint_recording_transcription"},
            ]],
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
        self.assertEqual(result["answer_mode"], "rag_answer")
        self.assertEqual(len(result["sources"]), 2)
        self.assertIn("project blockers", result["sources"][0]["text"])
        self.assertEqual(result["sources"][0]["chunk_id"], "upload-1:1")

    def test_retrieve_and_answer_reranks_by_meeting_title(self):
        fake_results = {
            "documents": [[
                "finance transcript text",
                "00:00:00.000 Unknown: The sales assistant agent reviews account context, summarizes customer needs, and recommends next actions.",
            ]],
            "metadatas": [[
                {"meeting_id": "upload-1", "meeting_title": "AI_Finance_video"},
                {
                    "meeting_id": "sharepoint-1",
                    "meeting_title": "Sales Assistant Agent Rohit Kumar.mp4",
                    "source_type": "sharepoint_recording_transcription",
                },
            ]],
            "ids": [["upload-1:1", "sharepoint-1:1"]],
            "distances": [[0.05, 1.20]],
        }

        with patch(
            "app.rag.retrieve.EmbeddingService.generate_query_embedding",
            return_value=[0.3, 0.4],
        ), patch(
            "app.rag.retrieve.ChromaService.query_embeddings",
            return_value=fake_results,
        ), patch(
            "app.rag.retrieve.generate_answer",
            return_value="Sales assistant answer",
        ):
            result = retrieve_and_answer("Summarize Sales Assistant Agent")

        self.assertEqual(result["sources"][0]["metadata"]["meeting_title"], "Sales Assistant Agent Rohit Kumar.mp4")

    def test_retrieve_and_answer_ignores_uploaded_local_sources(self):
        fake_results = {
            "documents": [[
                "async apex local transcript",
                "LWC component lifecycle training covered decorators, reactive data, component events, and deployment steps.",
            ]],
            "metadatas": [[
                {
                    "meeting_id": "upload-1",
                    "meeting_title": "Asynchronous apex",
                    "source_type": "uploaded_transcript",
                },
                {
                    "meeting_id": "sharepoint-1",
                    "meeting_title": "LWC Training",
                    "source_type": "sharepoint_recording_transcription",
                },
            ]],
            "ids": [["upload-1:1", "sharepoint-1:1"]],
            "distances": [[0.01, 1.20]],
        }

        with patch(
            "app.rag.retrieve.EmbeddingService.generate_query_embedding",
            return_value=[0.3, 0.4],
        ), patch(
            "app.rag.retrieve.ChromaService.query_embeddings",
            return_value=fake_results,
        ), patch(
            "app.rag.retrieve.generate_answer",
            return_value="LWC answer",
        ):
            result = retrieve_and_answer("Summarize LWC")

        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["sources"][0]["metadata"]["meeting_title"], "LWC Training")

    def test_retrieve_and_answer_ignores_repeated_low_signal_chunks(self):
        fake_results = {
            "documents": [[
                "Unknown: You You You You You You You You You You You You You You",
            ]],
            "metadatas": [[
                {
                    "meeting_id": "sharepoint-1",
                    "meeting_title": "20260418-1531-58.4944759.mp4",
                    "source_type": "sharepoint_recording_transcription",
                },
            ]],
            "ids": [["sharepoint-1:1"]],
            "distances": [[0.01]],
        }

        with patch(
            "app.rag.retrieve.EmbeddingService.generate_query_embedding",
            return_value=[0.3, 0.4],
        ), patch(
            "app.rag.retrieve.ChromaService.query_embeddings",
            return_value=fake_results,
        ):
            result = retrieve_and_answer("Summarize LWC Training")

        self.assertEqual(result["answer_mode"], "no_microsoft_context")
        self.assertEqual(result["sources"], [])

    def test_retrieve_and_answer_falls_back_to_extractive_answer_when_llm_unavailable(self):
        fake_results = {
            "documents": [[
                "00:00:01.000 Speaker: The system summarizes each call automatically.",
                "00:00:07.000 Speaker: It stores grounded chunks in Chroma for retrieval.",
            ]],
            "metadatas": [[
                {"meeting_id": "upload-1", "source_type": "sharepoint_recording_transcription"},
                {"meeting_id": "upload-1", "source_type": "sharepoint_recording_transcription"},
            ]],
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
            side_effect=RuntimeError("Ollama SLM unavailable"),
        ):
            result = retrieve_and_answer("summarize the call")

        self.assertEqual(result["answer_mode"], "extractive_summary")
        self.assertIn("The system summarizes each call automatically.", result["answer"])
        self.assertEqual(result["llm_error"], "Ollama SLM unavailable")


if __name__ == "__main__":
    unittest.main()
