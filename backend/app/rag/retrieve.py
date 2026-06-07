import re

from app.mcp.mcp_manager import MCPManager
from app.rag.llm import generate_answer, generate_conversational_answer
from app.rag.prompts import CONVERSATIONAL_PROMPT, build_rag_prompt, normalize_output_format
from app.services.answer_service import AnswerService
from app.services.chroma_service import ChromaService, MICROSOFT_SOURCE_TYPES
from app.services.embedding_service import EmbeddingService

QUERYABLE_SOURCE_TYPES = MICROSOFT_SOURCE_TYPES | {"rag_manual_ingest"}

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

NOT_FOUND_ANSWER = "Information not found in the provided context."


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
        metadata.get("source_type") in QUERYABLE_SOURCE_TYPES
        and _is_informative_text(source.get("text") or "")
    )


def _is_not_found_answer(answer: str) -> bool:
    normalized = (answer or "").strip().lower()
    if normalized == NOT_FOUND_ANSWER.lower():
        return True
    return any(
        phrase in normalized
        for phrase in (
            "information not found",
            "do not contain the answer",
            "does not contain the answer",
            "not found in the provided context",
        )
    )


def _meeting_title_from_sources(sources: list[dict]) -> str:
    for source in sources:
        title = (source.get("metadata") or {}).get("meeting_title")
        if title:
            return str(title)
    return "this meeting"


def _topic_hint_from_sources(sources: list[dict]) -> str:
    if not sources:
        return "a recorded meeting conversation"

    text = re.sub(r"\s+", " ", (sources[0].get("text") or "").strip())
    if not text:
        return "a recorded meeting conversation"

    sentences = AnswerService._split_sentences(text)
    if sentences:
        return AnswerService._truncate_excerpt(sentences[0], limit=220)
    return AnswerService._truncate_excerpt(text, limit=220)


TIMESTAMP_PATTERN = re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?(?:\.\d{1,3})?\b")
SPEAKER_LINE_PATTERN = re.compile(r"(?m)^\s*[\w\s.'-]{1,48}:\s+\S")


def _looks_like_transcript_dump(answer: str) -> bool:
    """Detect pasted transcript text, not structured summaries or bullet answers."""
    normalized = (answer or "").strip()
    if len(normalized) < 600:
        return False

    timestamp_count = len(TIMESTAMP_PATTERN.findall(normalized))
    speaker_lines = len(SPEAKER_LINE_PATTERN.findall(normalized))

    if timestamp_count >= 3:
        return True
    if speaker_lines >= 5:
        return True

    # Long unstructured wall without markdown structure
    if len(normalized) > 2800 and normalized.count("\n") < 4:
        return True

    return False


def _generate_conversational_response(user_query: str, sources: list[dict]) -> dict:
    title = _meeting_title_from_sources(sources)
    topic_hint = _topic_hint_from_sources(sources)
    safe_query = (user_query or "").replace("{", "{{").replace("}", "}}")
    safe_hint = topic_hint.replace("{", "{{").replace("}", "}}")
    prompt = CONVERSATIONAL_PROMPT.format(
        meeting_title=title,
        query=safe_query,
        topic_hint=safe_hint,
    )

    llm_error = None
    try:
        answer = generate_conversational_answer(
            prompt,
            query=user_query,
            context=topic_hint,
        )
        if _is_not_found_answer(answer) or _looks_like_transcript_dump(answer):
            raise ValueError("Conversational model returned unusable text")
        answer_mode = "conversational"
    except Exception as exc:
        llm_error = str(exc)
        answer = (
            f"Hey — I'm MeetVault, your assistant for **{title}**. "
            "Ask me to summarize the meeting, list the main tips, or find a specific topic."
        )
        answer_mode = "conversational_fallback"

    return {
        "query": user_query,
        "answer": answer,
        "answer_mode": answer_mode,
        "llm_error": llm_error,
        "sources": sources[:2],
    }


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
    output_format: str | None = None,
) -> dict:
    """
    Retrieves relevant transcript chunks from ChromaDB and generates a grounded answer.
    """
    resolved_format = normalize_output_format(output_format)
    is_summary = AnswerService.has_summary_intent(user_query)
    query_embedding = EmbeddingService.generate_query_embedding(user_query)

    results = ChromaService.query_embeddings(
        query_embedding,
        meeting_id=meeting_id,
        n_results=8 if is_summary else 5,
        candidate_pool_size=120 if is_summary else 80,
        allowed_source_types=QUERYABLE_SOURCE_TYPES,
    )

    retrieved_documents = results.get("documents", [[]])[0]
    retrieved_metadatas = results.get("metadatas", [[]])[0]
    retrieved_distances = results.get("distances", [[]])[0]
    retrieved_ids = results.get("ids", [[]])[0]

    if not retrieved_documents:
        return {
            "query": user_query,
            "answer": "I don't have any meeting transcripts to answer that question.",
            "answer_mode": "no_context",
            "sources": [],
        }

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
        limit=8 if is_summary else 5,
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

    if AnswerService.is_vague_or_social_query(user_query):
        return _generate_conversational_response(user_query, sources)

    context_text = "\n\n---\n\n".join(
        f"Source: {(source.get('metadata') or {}).get('meeting_title') or 'Untitled meeting'}\n{source.get('text') or ''}"
        for source in sources
        if (source.get("metadata") or {}).get("source_type") != "mcp_jira"
    )
    context_text = f"{context_text}{jira_context}".strip()

    final_prompt = build_rag_prompt(context_text, user_query, resolved_format)
    num_predict = 1536 if is_summary else 768

    llm_error = None
    try:
        answer = generate_answer(
            final_prompt,
            query=user_query,
            context=context_text,
            num_predict=num_predict,
        )
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

    should_use_extractive_fallback = _is_not_found_answer(answer) or (
        _looks_like_transcript_dump(answer) and not is_summary
    )

    if should_use_extractive_fallback:
        if AnswerService.is_vague_or_social_query(user_query):
            return _generate_conversational_response(user_query, sources)

        fallback_answer = AnswerService.compose(user_query, sources)
        if fallback_answer:
            answer = fallback_answer["text"]
            answer_mode = fallback_answer["mode"]
        else:
            title = _meeting_title_from_sources(sources)
            answer = (
                f"I couldn't find a clear answer to that in **{title}**. "
                "Try asking for a summary, the main tips, or a specific topic from the meeting."
            )
            answer_mode = "clarification"

    return {
        "query": user_query,
        "answer": answer,
        "answer_mode": answer_mode,
        "output_format": resolved_format,
        "llm_error": llm_error,
        "sources": sources,
    }
