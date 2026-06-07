import re


SUMMARY_HINTS = (
    "summary",
    "summarize",
    "summarise",
    "overview",
    "key point",
    "key takeaway",
    "high level",
    "more detail",
    "in detail",
    "elaborate",
    "recap",
)
MEETING_QUESTION_HINTS = (
    "action item",
    "decision",
    "discuss",
    "explain",
    "follow up",
    "follow-up",
    "list ",
    "main tip",
    "recap",
    "takeaway",
    "talk about",
    "what did",
    "who said",
)
VAGUE_SOCIAL_PATTERNS = (
    r"^\s*(hi|hello|hey|hiya|yo|hol|sup|thanks|thank you|thx|ok|okay|cool|nice|great)\s*[!?.]*\s*$",
    r"^\s*(what|why|how|who|huh)\s*\??\s*$",
    r"^\s*good\s+(morning|afternoon|evening)\s*[!?.]*\s*$",
    r"^\s*what can you (do|help with)\??\s*$",
    r"^\s*who are you\??\s*$",
)
QUESTION_FILLER_WORDS = {
    "what",
    "why",
    "how",
    "who",
    "when",
    "where",
    "huh",
    "hol",
    "hi",
    "hey",
}
MAX_BRIEF_EXCERPT_CHARS = 280
LOW_SIGNAL_WORDS = {
    "ah",
    "hmm",
    "okay",
    "ok",
    "um",
    "uh",
    "yeah",
    "yes",
    "you",
}

LINE_PREFIX_PATTERN = re.compile(
    r"^\s*(?:\d{2}:\d{2}:\d{2}(?:\.\d{3})?\s+)?[^:]{1,40}:\s*"
)


class AnswerService:
    @staticmethod
    def has_summary_intent(query: str) -> bool:
        query_lower = (query or "").lower()
        return any(hint in query_lower for hint in SUMMARY_HINTS)

    @staticmethod
    def is_vague_or_social_query(query: str) -> bool:
        normalized = (query or "").strip()
        if not normalized:
            return True

        if AnswerService.has_summary_intent(normalized):
            return False

        query_lower = normalized.lower()
        if any(hint in query_lower for hint in MEETING_QUESTION_HINTS):
            return False

        if any(
            re.search(pattern, normalized, flags=re.IGNORECASE)
            for pattern in VAGUE_SOCIAL_PATTERNS
        ):
            return True

        raw_tokens = [
            token
            for token in re.findall(r"[a-zA-Z0-9']+", query_lower)
            if len(token) > 1
        ]
        substantive_tokens = [
            token
            for token in raw_tokens
            if token not in LOW_SIGNAL_WORDS and token not in QUESTION_FILLER_WORDS
        ]
        if substantive_tokens:
            return False

        if len(raw_tokens) <= 2 and len(normalized) < 48:
            return True

        return False

    @staticmethod
    def _truncate_excerpt(text: str, limit: int = MAX_BRIEF_EXCERPT_CHARS) -> str:
        cleaned = (text or "").strip()
        if len(cleaned) <= limit:
            return cleaned
        return f"{cleaned[: limit - 1].rstrip()}…"

    @staticmethod
    def _normalize_passage(text: str) -> str:
        cleaned_lines = []
        for raw_line in (text or "").splitlines():
            line = LINE_PREFIX_PATTERN.sub("", raw_line).strip()
            if line:
                cleaned_lines.append(line)
        return " ".join(cleaned_lines)

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        sentences = []
        for part in re.split(r"(?<=[.!?])\s+", text):
            sentence = part.strip()
            if sentence:
                sentences.append(sentence)
        return sentences

    @staticmethod
    def _is_meaningful_passage(text: str) -> bool:
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

    @staticmethod
    def compose(query: str, results: list[dict]) -> dict | None:
        if not results:
            return None

        if AnswerService.is_vague_or_social_query(query):
            return None

        normalized_passages = [
            AnswerService._normalize_passage(result.get("text") or "")
            for result in results[:4]
        ]
        normalized_passages = [
            passage
            for passage in normalized_passages
            if passage and AnswerService._is_meaningful_passage(passage)
        ]
        if not normalized_passages:
            return None

        is_summary_intent = AnswerService.has_summary_intent(query)

        if is_summary_intent:
            seen = set()
            selected_sentences = []
            for passage in normalized_passages:
                for sentence in AnswerService._split_sentences(passage):
                    normalized_sentence = sentence.lower()
                    if normalized_sentence in seen:
                        continue
                    seen.add(normalized_sentence)
                    selected_sentences.append(sentence)
                    if len(selected_sentences) == 8:
                        break
                if len(selected_sentences) == 8:
                    break

            if selected_sentences:
                return {
                    "mode": "extractive_summary",
                    "text": "\n".join(f"- {sentence}" for sentence in selected_sentences),
                }

        supporting_points = []
        for passage in normalized_passages[:2]:
            excerpt = AnswerService._truncate_excerpt(passage.strip())
            if excerpt:
                supporting_points.append(excerpt)

        if not supporting_points:
            return None

        return {
            "mode": "retrieval_brief",
            "text": "\n".join(f"- {point}" for point in supporting_points),
        }
