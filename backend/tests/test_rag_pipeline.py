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

    def test_retrieve_and_answer_handles_greeting_conversationally(self):
        fake_results = {
            "documents": [[
                "00:03:07.000 Unknown: The rose is simply a win you experienced since the last chat.",
            ]],
            "metadatas": [[
                {
                    "meeting_id": "onedrive-1",
                    "source_type": "onedrive_video_transcription",
                    "meeting_title": "6 Tips for Productive 11 Meetings",
                },
            ]],
            "ids": [["onedrive-1:1"]],
            "distances": [[1.6]],
        }

        with patch(
            "app.rag.retrieve.EmbeddingService.generate_query_embedding",
            return_value=[0.1, 0.2],
        ), patch(
            "app.rag.retrieve.ChromaService.query_embeddings",
            return_value=fake_results,
        ), patch(
            "app.rag.retrieve.generate_conversational_answer",
            return_value="Hi! This recording covers tips for productive 1:1s. Want a quick summary?",
        ) as mock_conversational:
            result = retrieve_and_answer("Hi", meeting_id="onedrive-1")

        mock_conversational.assert_called_once()
        self.assertEqual(result["answer_mode"], "conversational")
        self.assertIn("productive 1:1s", result["answer"])
        self.assertNotIn("Information not found", result["answer"])

    def test_retrieve_and_answer_does_not_dump_transcript_for_vague_what(self):
        fake_results = {
            "documents": [[
                "The rose is simply a win you experienced since the last time YouTube had a chat. "
                "This doesn't have to be a big win, the point is to start the meeting on a positive note.",
            ]],
            "metadatas": [[
                {
                    "meeting_id": "onedrive-1",
                    "source_type": "onedrive_video_transcription",
                    "meeting_title": "6 Tips for Productive 11 Meetings",
                },
            ]],
            "ids": [["onedrive-1:1"]],
            "distances": [[0.4]],
        }

        with patch(
            "app.rag.retrieve.EmbeddingService.generate_query_embedding",
            return_value=[0.1, 0.2],
        ), patch(
            "app.rag.retrieve.ChromaService.query_embeddings",
            return_value=fake_results,
        ), patch(
            "app.rag.retrieve.generate_conversational_answer",
            return_value="Not sure what you meant — want a summary of the 1:1 tips from this video?",
        ), patch(
            "app.rag.retrieve.generate_answer",
            return_value="Information not found in the provided context.",
        ) as mock_rag_answer:
            result = retrieve_and_answer("What?", meeting_id="onedrive-1")

        mock_rag_answer.assert_not_called()
        self.assertEqual(result["answer_mode"], "conversational")
        self.assertLess(len(result["answer"]), 400)
        self.assertNotIn("YouTube had a chat", result["answer"])

    def test_retrieve_and_answer_work_summary_uses_all_active_tools(self):
        active_tools = [
            {
                "provider": "jira",
                "name": "get_jira_tickets",
                "description": "Fetch Jira tickets",
                "parameters": {},
                "status": "active",
            },
            {
                "provider": "github",
                "name": "get_github_repositories",
                "description": "Fetch GitHub repositories",
                "parameters": {},
                "status": "active",
            },
        ]

        with patch(
            "app.mcp.tool_registry.MCPToolRegistry.get_active_tools",
            return_value=active_tools,
        ), patch(
            "app.rag.retrieve.MCPManager.execute_tool",
            side_effect=[
                [
                    {
                        "ticket_id": "JIRA-1",
                        "summary": "Fix login bug",
                        "status": "In Progress",
                    }
                ],
                [
                    {
                        "full_name": "org/repo",
                        "url": "https://github.com/org/repo",
                    }
                ],
            ],
        ) as mock_execute_tool, patch(
            "app.rag.retrieve.MCPManager.get_all_connections",
            return_value={
                "jira": {"connected": True},
                "github": {"connected": True},
                "slack": {"connected": False},
                "outlook": {"connected": False},
                "calendar": {"connected": False},
                "salesforce": {"connected": False},
            },
        ), patch(
            "app.rag.retrieve.generate_answer",
            return_value="Work summary",
        ) as mock_generate_answer:
            result = retrieve_and_answer("summarize my work today")

        self.assertEqual(result["answer_mode"], "work_summary")
        self.assertEqual(mock_execute_tool.call_count, 2)
        self.assertEqual(mock_execute_tool.call_args_list[0].args[1], "get_jira_tickets")
        self.assertEqual(mock_execute_tool.call_args_list[1].args[1], "get_github_repositories")
        self.assertIn("Jira Tasks Assigned to Me", mock_generate_answer.call_args.kwargs["context"])
        self.assertIn("GitHub Repositories", mock_generate_answer.call_args.kwargs["context"])


if __name__ == "__main__":
    unittest.main()
