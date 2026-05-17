import re

from app.mcp.mcp_manager import MCPManager
from app.rag.llm import generate_answer
from app.rag.prompts import RAG_SYSTEM_PROMPT
from app.services.answer_service import AnswerService
from app.services.chroma_service import ChromaService, MICROSOFT_SOURCE_TYPES
from app.services.embedding_service import EmbeddingService


STOPWORDS = {
    "a",
    "an",
    "and",
    "about",
    "ask",
    "brief",
    "for",
    "from",
    "give",
    "in",
    "is",
    "me",
    "of",
    "on",
    "please",
    "recording",
    "recordings",
    "summary",
    "summarize",
    "summarise",
    "the",
    "this",
    "to",
    "video",
    "what",
}
LOW_SIGNAL_WORDS = {"ah", "hmm", "okay", "ok", "um", "uh", "yeah", "yes", "you"}
JIRA_KEYWORDS = {
    "jira",
    "ticket",
    "tickets",
    "assigned",
    "task",
    "tasks",
    "issue",
    "issues",
    "sprint",
}


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9]+", (value or "").lower())
        if len(token) > 1 and token not in STOPWORDS
    }


def _source_from_result(
    *,
    index: int,
    document: str,
    retrieved_ids: list,
    retrieved_distances: list,
    retrieved_metadatas: list,
) -> dict:
    return {
        "chunk_id": (
            retrieved_ids[index]
            if index < len(retrieved_ids)
            else f"source-{index + 1}"
        ),
        "distance": (
            retrieved_distances[index]
            if index < len(retrieved_distances)
            else None
        ),
        "text": document,
        "metadata": (
            retrieved_metadatas[index]
            if index < len(retrieved_metadatas)
            else {}
        ),
    }


def _score_source(query: str, source: dict) -> float:
    metadata = source.get("metadata") or {}
    title = metadata.get("meeting_title") or ""
    source_type = metadata.get("source_type") or ""
    text = source.get("text") or ""
    distance = source.get("distance")

    query_tokens = _tokens(query)
    title_tokens = _tokens(title)
    text_tokens = _tokens(text)

    semantic_score = 0.0
    if isinstance(distance, (float, int)):
        semantic_score = 1 / (1 + max(float(distance), 0.0))

    title_overlap = len(query_tokens & title_tokens)
    text_overlap = len(query_tokens & text_tokens)
    compact_query = " ".join(
        token
        for token in re.findall(r"[a-zA-Z0-9]+", query.lower())
        if token not in STOPWORDS
    )
    compact_title = " ".join(re.findall(r"[a-zA-Z0-9]+", title.lower()))
    phrase_bonus = 3.0 if compact_query and compact_query in compact_title else 0.0
    source_bonus = (
        0.2
        if source_type in {"sharepoint_recording_transcription", "graph_recording_transcription"}
        else 0.0
    )

    return (
        semantic_score
        + (title_overlap * 2.5)
        + (text_overlap * 0.6)
        + phrase_bonus
        + source_bonus
    )


def _is_informative_text(text: str) -> bool:
    tokens = re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
    meaningful_tokens = [
        token
        for token in tokens
        if len(token) > 2 and token not in LOW_SIGNAL_WORDS
    ]
    if len(meaningful_tokens) < 5:
        return False

    unique_ratio = len(set(meaningful_tokens)) / len(meaningful_tokens)
    return unique_ratio >= 0.25


def _rank_sources(query: str, sources: list[dict], limit: int = 5) -> list[dict]:
    ranked = sorted(
        sources,
        key=lambda source: _score_source(query, source),
        reverse=True,
    )
    if not ranked:
        return []

    top_meeting_id = (ranked[0].get("metadata") or {}).get("meeting_id")
    if top_meeting_id:
        same_meeting = [
            source
            for source in ranked
            if (source.get("metadata") or {}).get("meeting_id") == top_meeting_id
        ]
        other_meetings = [
            source
            for source in ranked
            if (source.get("metadata") or {}).get("meeting_id") != top_meeting_id
        ]
        ranked = [*same_meeting, *other_meetings]

    return ranked[:limit]


def _is_queryable_source(source: dict) -> bool:
    metadata = source.get("metadata") or {}
    return (
        metadata.get("source_type") in MICROSOFT_SOURCE_TYPES
        and _is_informative_text(source.get("text") or "")
    )


def _append_jira_context(user_query: str, user_key: str, sources: list[dict]) -> tuple[str, list[dict]]:
    query_terms = _tokens(user_query)
    if not query_terms & JIRA_KEYWORDS:
        return "", sources

    jira_tickets = MCPManager.get_jira_tickets(user_key)
    if not jira_tickets:
        return "", sources

    jira_context = "\n".join(
        f"[{ticket['ticket_id']}] {ticket['summary']} (Status: {ticket['status']})"
        for ticket in jira_tickets
    )
    mcp_source = {
        "chunk_id": "mcp-jira-live",
        "distance": 0.0,
        "text": f"Found {len(jira_tickets)} live Jira ticket(s) assigned to {user_key}.",
        "metadata": {
            "source_type": "mcp_jira",
            "meeting_title": "Jira Workspace",
            "meeting_id": "mcp-jira-live",
        },
    }
    return f"\n\n---\n\nSource: Jira Workspace\n{jira_context}", [*sources, mcp_source]


def retrieve_and_answer(
    user_query: str,
    meeting_id: str | None = None,
    user_key: str = "demo",
) -> dict:
    """
    Retrieves relevant transcript chunks from ChromaDB and generates a grounded answer.
    """
    query_embedding = EmbeddingService.generate_query_embedding(user_query)
    results = ChromaService.query_embeddings(
        query_embedding,
        meeting_id=meeting_id,
        n_results=5,
        candidate_pool_size=80,
        allowed_source_types=MICROSOFT_SOURCE_TYPES,
    )

    retrieved_documents = results.get("documents", [[]])[0]
    retrieved_metadatas = results.get("metadatas", [[]])[0]
    retrieved_distances = results.get("distances", [[]])[0]
    retrieved_ids = results.get("ids", [[]])[0]

    candidate_sources = [
        _source_from_result(
            index=index,
            document=document,
            retrieved_ids=retrieved_ids,
            retrieved_distances=retrieved_distances,
            retrieved_metadatas=retrieved_metadatas,
        )
        for index, document in enumerate(retrieved_documents)
    ]
    sources = _rank_sources(
        user_query,
        [source for source in candidate_sources if _is_queryable_source(source)],
    )

    jira_context, sources = _append_jira_context(user_query, user_key, sources)

    if not sources:
        return {
            "query": user_query,
            "answer": (
                "I found embeddings in ChromaDB, but none from Microsoft Graph, "
                "SharePoint, OneDrive recordings, or connected MCP tools matched this query yet."
            ),
            "answer_mode": "no_microsoft_context",
            "sources": [],
        }

    context_text = "\n\n---\n\n".join(
        f"Source: {(source.get('metadata') or {}).get('meeting_title') or 'Untitled meeting'}\n{source.get('text') or ''}"
        for source in sources
        if (source.get("metadata") or {}).get("source_type") != "mcp_jira"
    )
    context_text = f"{context_text}{jira_context}".strip()
    final_prompt = RAG_SYSTEM_PROMPT.format(context=context_text, query=user_query)

    llm_error = None
    try:
        answer = generate_answer(final_prompt, query=user_query, context=context_text)
        answer_mode = "rag_answer"
    except Exception as exc:
        llm_error = str(exc)
        fallback_answer = AnswerService.compose(user_query, sources)
        if fallback_answer:
            answer = fallback_answer["text"]
            answer_mode = fallback_answer["mode"]
        else:
            answer = (
                "I found relevant transcript chunks, but the answer model is not "
                "available right now. Review the retrieved sources below."
            )
            answer_mode = "retrieval_only"

    return {
        "query": user_query,
        "answer": answer,
        "answer_mode": answer_mode,
        "llm_error": llm_error,
        "sources": sources,
    }
