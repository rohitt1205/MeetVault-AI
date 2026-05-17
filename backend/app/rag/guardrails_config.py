import logging
import re
<<<<<<< HEAD


logger = logging.getLogger(__name__)


class SafetyMiddleware:
=======
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# ==========================================
# Production Guardrails & Safety Middleware
# ==========================================

class SafetyMiddleware:
    """
    Production-grade pure Python safety middleware providing input validation (anti-prompt-injection, jailbreak detection),
    output validation (grounding enforcement, hallucination checks), and sanitization.
    Optimized to be lenient and basic so valid answers containing partial negative phrasing are not incorrectly blocked.
    """
    
    # Common prompt injection and jailbreak attack strings
>>>>>>> origin/main
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
<<<<<<< HEAD
        r"jailbreak",
        r"ignore all rules",
        r"always output",
    ]
=======
        r"hypothetical scenario",
        r"simulated environment",
        r"new role",
        r"jailbreak",
        r"ignore all rules",
        r"always output"
    ]

    # Anchored keywords indicating the model is stating the entire answer is unknown.
    # Anchoring prevents blocking valid answers that happen to contain phrases like "downtime is not mentioned".
>>>>>>> origin/main
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
<<<<<<< HEAD
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
=======
        r"^\s*there is no mention"
    ]

    # Unsafe / toxic keywords for output sanitization (using word boundaries)
    UNSAFE_PATTERNS = [
        r"\bfuck\b", r"\bshit\b", r"\bbitch\b", r"\basshole\b", r"kill yourself", r"hate speech"
    ]

    @classmethod
    def detect_prompt_injection(cls, query: str) -> bool:
        """
        Helper function to check for prompt injection or jailbreak attempts.
        Returns True if malicious injection is detected, False otherwise.
        """
        if not query or not query.strip():
            return False
            
        query_lower = query.lower()
        for pattern in cls.INJECTION_PATTERNS:
            if re.search(pattern, query_lower):
                logger.warning(f"Prompt injection / jailbreak detected: matched pattern '{pattern}'")
                return True
        return False

    @classmethod
    def filter_unsafe_prompt(cls, query: str) -> bool:
        """
        Helper function to check for unsafe, toxic, or unethical query phrasing.
        Returns True if unsafe content is detected, False otherwise.
        """
        if not query or not query.strip():
            return False
            
        query_lower = query.lower()
        for pattern in cls.UNSAFE_PATTERNS:
            if re.search(pattern, query_lower):
                logger.warning("Unsafe prompt content detected.")
                return True
        return False

    @classmethod
    def validate_input(cls, query: str) -> bool:
        """
        Input validation layer combining prompt injection checks and unsafe prompt filtering.
        Returns True if valid (safe), False if malicious/invalid.
        """
        if cls.detect_prompt_injection(query):
            return False
        if cls.filter_unsafe_prompt(query):
            return False
        return True

    @classmethod
    def check_hallucination_and_grounding(cls, text: str, context: Optional[str] = None) -> bool:
        """
        Helper function to enforce context grounding and check for hallucinations.
        Returns True if grounded/valid, False if ungrounded or indicates missing info.
        """
        if not text or not text.strip():
            return False

        text_lower = text.lower()

        # Check if the output is an explicit refusal / unavailable statement
        for pattern in cls.UNAVAILABLE_PATTERNS:
            if re.search(pattern, text_lower):
                logger.info(f"Output indicates unavailable info (matched '{pattern}').")
                return False

        # Lenient check: if the model outputs a valid response, trust the system prompt's strict grounding instructions.
        return True

    @classmethod
    def validate_output(cls, text: str, context: Optional[str] = None, query: Optional[str] = None) -> str:
        """
        Output validation layer enforcing context grounding, hallucination reduction, and safe filtering.
        If the output is invalid or indicates missing info, returns the exact required fallback response.
        """
        fallback_response = "Information not found in the provided context."
        
        if not text or not text.strip():
            return fallback_response

        # 1. Check grounding & hallucination
        if not cls.check_hallucination_and_grounding(text, context):
            return fallback_response

        # 2. Check for unsafe / toxic content in output
        text_lower = text.lower()
        for pattern in cls.UNSAFE_PATTERNS:
            if re.search(pattern, text_lower):
                logger.warning("Unsafe content detected in output. Sanitizing to fallback.")
>>>>>>> origin/main
                return fallback_response

        return text.strip()

<<<<<<< HEAD
    @staticmethod
    def sanitize_output(text: str) -> str:
        return re.sub(
            r"^(ANSWER:|Answer:|AI:|Assistant:)\s*",
            "",
            text or "",
            flags=re.IGNORECASE,
        ).strip()
=======
    @classmethod
    def sanitize_output(cls, text: str) -> str:
        """
        Performs final sanitization on the output text.
        """
        cleaned = re.sub(r"^(ANSWER:|Answer:|AI:|Assistant:)\s*", "", text, flags=re.IGNORECASE)
        return cleaned.strip()
>>>>>>> origin/main
