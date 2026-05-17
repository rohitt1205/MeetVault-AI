import logging
import re


logger = logging.getLogger(__name__)


class SafetyMiddleware:
    INJECTION_PATTERNS = [
        r"ignore previous instructions",
        r"override system prompt",
        r"disregard context",
        r"you are now",
        r"dan mode",
        r"do anything now",
        r"forget instructions",
        r"forget rules",
        r"bypass system",
        r"jailbreak",
        r"ignore all rules",
        r"always output",
    ]
    UNAVAILABLE_PATTERNS = [
        r"^\s*i don't know",
        r"^\s*i do not know",
        r"^\s*information not found",
        r"^\s*no information is provided",
        r"^\s*the provided context does not",
        r"^\s*the transcript does not",
        r"^\s*cannot answer based on",
        r"^\s*none of the provided excerpts",
        r"^\s*i cannot answer",
        r"^\s*there is no mention",
    ]
    UNSAFE_PATTERNS = [
        r"\bfuck\b",
        r"\bshit\b",
        r"\bbitch\b",
        r"\basshole\b",
        r"kill yourself",
        r"hate speech",
    ]

    @classmethod
    def validate_input(cls, query: str) -> bool:
        query_lower = (query or "").lower()
        for pattern in [*cls.INJECTION_PATTERNS, *cls.UNSAFE_PATTERNS]:
            if re.search(pattern, query_lower):
                logger.warning("Blocked unsafe or prompt-injection query: %s", pattern)
                return False
        return True

    @classmethod
    def validate_output(cls, text: str, context: str | None = None, query: str | None = None) -> str:
        fallback_response = "Information not found in the provided context."
        if not text or not text.strip():
            return fallback_response

        text_lower = text.lower()
        for pattern in cls.UNAVAILABLE_PATTERNS:
            if re.search(pattern, text_lower):
                return fallback_response
        for pattern in cls.UNSAFE_PATTERNS:
            if re.search(pattern, text_lower):
                logger.warning("Blocked unsafe model output: %s", pattern)
                return fallback_response

        return text.strip()

    @staticmethod
    def sanitize_output(text: str) -> str:
        return re.sub(
            r"^(ANSWER:|Answer:|AI:|Assistant:)\s*",
            "",
            text or "",
            flags=re.IGNORECASE,
        ).strip()
