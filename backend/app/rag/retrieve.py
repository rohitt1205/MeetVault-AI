import re

from app.services.chroma_service import ChromaService, MICROSOFT_SOURCE_TYPES
from app.services.embedding_service import EmbeddingService
from app.services.answer_service import AnswerService
from app.rag.prompts import RAG_SYSTEM_PROMPT
from app.rag.llm import generate_answer


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
    compact_query = " ".join(token for token in re.findall(r"[a-zA-Z0-9]+", query.lower()) if token not in STOPWORDS)
    compact_title = " ".join(re.findall(r"[a-zA-Z0-9]+", title.lower()))
    phrase_bonus = 3.0 if compact_query and compact_query in compact_title else 0.0
    source_bonus = 0.2 if source_type in {"sharepoint_recording_transcription", "graph_recording_transcription"} else 0.0

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


def retrieve_and_answer(user_query: str, meeting_id: str | None = None) -> dict:
    """
    Retrieves relevant transcript chunks from ChromaDB based on the user query,
    constructs a prompt, and calls the LLM to get a grounded answer.
    """
    # 1. Embed the user query
    query_embedding = EmbeddingService.generate_query_embedding(user_query)
    
    # 2. Query ChromaDB for relevant chunks
    results = ChromaService.query_embeddings(
        query_embedding,
        meeting_id=meeting_id,
        n_results=5,
        candidate_pool_size=80,
        allowed_source_types=MICROSOFT_SOURCE_TYPES,
    )
    
    # 3. Extract the text chunks from the results
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
    )

    if not sources:
        return {
            "query": user_query,
            "answer": (
                "I found embeddings in ChromaDB, but none from Microsoft Graph, "
                "SharePoint, or OneDrive recordings matched this query yet."
            ),
            "answer_mode": "no_microsoft_context",
            "sources": [],
        }
        
    # Join retrieved chunks to form the context
    context_text = "\n\n---\n\n".join(
        f"Source: {(source.get('metadata') or {}).get('meeting_title') or 'Untitled meeting'}\n{source.get('text') or ''}"
        for source in sources
    )
    
    # 4. Construct the Prompt
    final_prompt = RAG_SYSTEM_PROMPT.format(
        context=context_text,
        query=user_query
    )
    
    # 5. Call LLM
    llm_error = None
    try:
        answer = generate_answer(final_prompt, query=user_query, context=context_text)
        answer_mode = "rag_answer"
    except Exception as e:
        llm_error = str(e)
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
