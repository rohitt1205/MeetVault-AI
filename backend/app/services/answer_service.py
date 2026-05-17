import re


SUMMARY_HINTS = (
    "summary",
    "summarize",
    "summarise",
    "overview",
    "key point",
    "key takeaway",
    "high level",
)

LINE_PREFIX_PATTERN = re.compile(
    r"^\s*(?:\d{2}:\d{2}:\d{2}(?:\.\d{3})?\s+)?[^:]{1,40}:\s*"
)


class AnswerService:
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
    def compose(query: str, results: list[dict]) -> dict | None:
        if not results:
            return None

        normalized_passages = [
            AnswerService._normalize_passage(result.get("text") or "")
            for result in results[:4]
        ]
        normalized_passages = [passage for passage in normalized_passages if passage]
        if not normalized_passages:
            return None

        query_lower = (query or "").lower()
        is_summary_intent = any(hint in query_lower for hint in SUMMARY_HINTS)

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
                    if len(selected_sentences) == 4:
                        break
                if len(selected_sentences) == 4:
                    break

            if selected_sentences:
                return {
                    "mode": "extractive_summary",
                    "text": "\n".join(f"- {sentence}" for sentence in selected_sentences),
                }

        supporting_points = []
        for passage in normalized_passages[:3]:
            excerpt = passage.strip()
            if excerpt:
                supporting_points.append(excerpt)

        if not supporting_points:
            return None

        return {
            "mode": "retrieval_brief",
            "text": "\n".join(f"- {point}" for point in supporting_points),
        }
