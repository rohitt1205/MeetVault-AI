import re
from difflib import SequenceMatcher

from app.services.answer_service import AnswerService

EXCERPT_LIMIT = 220
FUZZY_MATCH_RATIO = 0.72
SPEAKER_LINE_PREFIX = re.compile(
    r"^\s*(?:\d{1,2}:\d{2}(?::\d{2})?(?:\.\d{1,3})?\s+)?[^:\n]{1,48}:\s*",
    re.MULTILINE,
)

SKIP_SOURCE_TYPES = {"mcp_jira"}


def _clean_excerpt(text: str, *, limit: int = EXCERPT_LIMIT) -> str:
    cleaned = SPEAKER_LINE_PREFIX.sub("", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""

    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}…"


def _format_speaker(speaker_start: str | None, speaker_end: str | None) -> str:
    start = (speaker_start or "").strip()
    end = (speaker_end or "").strip()

    if start and end and start != end:
        return f"{start} → {end}"
    if start:
        return start
    if end:
        return end
    return "Unknown speaker"


def _format_time_range(start_time: str | None, end_time: str | None) -> str | None:
    start = (start_time or "").strip()
    end = (end_time or "").strip()

    if start and end and start != end:
        return f"{start} – {end}"
    return start or end or None


def _sort_key(citation: dict) -> tuple:
    start = citation.get("start_time") or ""
    end = citation.get("end_time") or ""
    return (start, end, citation.get("id") or "")


def _source_key(source: dict) -> str:
    return str(source.get("chunk_id") or id(source))


def _topic_tokens(topic: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-zA-Z0-9']+", (topic or "").lower())
        if len(token) > 1
    ]


def _haystack_words(haystack: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9']+", (haystack or "").lower())


def _token_matches_text(token: str, haystack: str) -> bool:
    if not token or not haystack:
        return False

    lowered = haystack.lower()
    if token in lowered:
        return True

    for word in _haystack_words(lowered):
        if token in word or word in token:
            return True
        if len(token) >= 4 and len(word) >= 4:
            if SequenceMatcher(None, token, word).ratio() >= FUZZY_MATCH_RATIO:
                return True
    return False


def _topic_match_score(topic: str, source: dict) -> float:
    topic_text = (topic or "").strip().lower()
    if not topic_text:
        return 0.0

    haystack = (source.get("text") or "").lower()
    if not haystack:
        return 0.0

    if _token_matches_text(topic_text, haystack):
        return 10.0 + len(topic_text)

    tokens = _topic_tokens(topic_text)
    if not tokens:
        return 0.0

    matched = sum(1 for token in tokens if _token_matches_text(token, haystack))
    if matched == 0:
        return 0.0

    return matched / len(tokens)


def _excerpt_for_topic(source: dict, topic: str) -> str:
    text = source.get("text") or ""
    if not text:
        return ""

    best_line = ""
    best_score = 0.0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        score = _topic_match_score(topic, {"text": line})
        if score > best_score:
            best_score = score
            best_line = line

    if best_line and best_score > 0:
        return _clean_excerpt(best_line)

    sentences = re.split(r"(?<=[.!?])\s+", _clean_excerpt(text))
    best_sentence = ""
    best_score = 0.0
    for sentence in sentences:
        score = _topic_match_score(topic, {"text": sentence})
        if score > best_score:
            best_score = score
            best_sentence = sentence

    if best_sentence and best_score > 0:
        return best_sentence

    return _clean_excerpt(text)


def _source_to_citation(source: dict, *, index: int) -> dict | None:
    metadata = source.get("metadata") or {}
    source_type = metadata.get("source_type") or ""
    if source_type in SKIP_SOURCE_TYPES:
        return None

    topic = source.get("_proof_topic")
    excerpt = source.get("_proof_excerpt")
    if not excerpt:
        excerpt = _excerpt_for_topic(source, topic) if topic else _clean_excerpt(source.get("text") or "")
    if not excerpt:
        return None

    chunk_id = source.get("chunk_id") or f"source-{index + 1}"
    citation_id = f"{chunk_id}:{topic}" if topic else str(chunk_id)

    return {
        "id": citation_id,
        "speaker": _format_speaker(
            metadata.get("speaker_start"),
            metadata.get("speaker_end"),
        ),
        "start_time": metadata.get("start_timestamp"),
        "end_time": metadata.get("end_timestamp"),
        "time_label": _format_time_range(
            metadata.get("start_timestamp"),
            metadata.get("end_timestamp"),
        ),
        "meeting_title": metadata.get("meeting_title"),
        "excerpt": excerpt,
        "source_type": source_type or None,
        "topic": topic,
    }


def _best_source_for_topic(
    sources: list[dict],
    topic: str,
    *,
    used_keys: set[str],
    allow_reuse: bool,
) -> tuple[dict | None, float]:
    best_source = None
    best_score = 0.0

    for source in sources:
        source_id = _source_key(source)
        if not allow_reuse and source_id in used_keys:
            continue

        score = _topic_match_score(topic, source)
        if score > best_score:
            best_score = score
            best_source = source

    return best_source, best_score


def _select_sources_for_topics(sources: list[dict], topics: list[str]) -> list[dict]:
    selected: list[dict] = []
    used_keys: set[str] = set()

    for topic in topics:
        best_source, best_score = _best_source_for_topic(
            sources,
            topic,
            used_keys=used_keys,
            allow_reuse=False,
        )

        if not best_source or best_score <= 0:
            best_source, best_score = _best_source_for_topic(
                sources,
                topic,
                used_keys=used_keys,
                allow_reuse=True,
            )

        if not best_source or best_score <= 0:
            continue

        source_id = _source_key(best_source)
        tagged = {
            **best_source,
            "_proof_topic": topic,
            "_proof_excerpt": _excerpt_for_topic(best_source, topic),
        }
        selected.append(tagged)

        if source_id not in used_keys:
            used_keys.add(source_id)

    return selected


def build_citations(
    sources: list[dict] | None,
    *,
    limit: int = 5,
    query: str | None = None,
) -> list[dict]:
    """Normalize ranked RAG sources into UI-friendly proof citations."""
    usable_sources = list(sources or [])
    query_text = query or ""
    topics = AnswerService.extract_query_topics(query_text)

    if len(topics) >= 2:
        picked_sources = _select_sources_for_topics(usable_sources, topics[:limit])
    else:
        primary_topic = AnswerService.extract_primary_topic(query_text)
        if primary_topic:
            best_source, best_score = _best_source_for_topic(
                usable_sources,
                primary_topic,
                used_keys=set(),
                allow_reuse=True,
            )
            if best_source and best_score > 0:
                picked_sources = [{
                    **best_source,
                    "_proof_topic": primary_topic,
                    "_proof_excerpt": _excerpt_for_topic(best_source, primary_topic),
                }]
            else:
                picked_sources = usable_sources[:limit]
        else:
            picked_sources = usable_sources[:limit]

    citations: list[dict] = []
    for index, source in enumerate(picked_sources):
        citation = _source_to_citation(source, index=index)
        if citation:
            citations.append(citation)

    citations.sort(key=_sort_key)
    return citations
