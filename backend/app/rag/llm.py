import logging
import os
from typing import Optional

import requests
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

from app.rag.guardrails_config import SafetyMiddleware


load_dotenv()
logger = logging.getLogger(__name__)
OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
).rstrip("/")


def _generate_with_ollama(prompt: str, model_name: str) -> str:
    if not model_name:
        raise ValueError("RAG_MODEL must be set. Example: qwen2.5:7b")

    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0, "top_p": 0.1},
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    return (payload.get("response") or "").strip()


def _get_available_qwen_model() -> str:
    configured_model = (os.getenv("RAG_MODEL") or "").strip()
    default_model = "qwen2.5:7b"
    preferred_model = configured_model or default_model

    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        response.raise_for_status()
        installed_names = [
            model.get("name")
            for model in response.json().get("models", [])
            if model.get("name")
        ]
        if preferred_model in installed_names:
            return preferred_model
        if configured_model:
            logger.warning(
                "Configured RAG_MODEL '%s' is not installed in Ollama. Installed models: %s",
                configured_model,
                installed_names,
            )
        for name in installed_names:
            if "qwen" in name.lower():
                return name
    except Exception as exc:
        logger.info("Could not inspect Ollama models: %s", exc)

    return preferred_model


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
def _generate_with_qwen(prompt: str) -> str:
    return _generate_with_ollama(prompt, _get_available_qwen_model())


def generate_answer(prompt: str, query: Optional[str] = None, context: Optional[str] = None) -> str:
    """
    Calls the local Ollama/Qwen SLM to generate a grounded response.
    """
    fallback_response = "Information not found in the provided context."
    if query and not SafetyMiddleware.validate_input(query):
        return fallback_response

    answer = _generate_with_qwen(prompt)

    return SafetyMiddleware.sanitize_output(
        SafetyMiddleware.validate_output(answer, context=context, query=query)
    )
