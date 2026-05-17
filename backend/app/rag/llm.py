import os

import requests
from dotenv import load_dotenv

load_dotenv()


def _generate_with_gemini(prompt: str, model_name: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set in the environment variables.")

    try:
        # pyrefly: ignore [missing-import]
        import google.generativeai as genai
    except ImportError as exc:  # pragma: no cover - depends on local dependency install
        raise RuntimeError(
            "google-generativeai is not installed. Install it in the backend environment to use Gemini for /rag/query."
        ) from exc

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    response = model.generate_content(prompt)
    return response.text


def _generate_with_ollama(prompt: str, model_name: str) -> str:
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    if not model_name:
        raise ValueError(
            "RAG_MODEL must be set when RAG_PROVIDER=ollama. Example: qwen2.5:3b-instruct"
        )

    response = requests.post(
        f"{ollama_host}/api/generate",
        json={
            "model": model_name,
            "prompt": prompt,
            "stream": False,
        },
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    return (payload.get("response") or "").strip()


def generate_answer(prompt: str) -> str:
    """
    Calls the configured answer model provider to generate a grounded response.
    """
    provider = (os.getenv("RAG_PROVIDER") or "gemini").strip().lower()
    model_name = (os.getenv("RAG_MODEL") or "gemini-2.5-flash").strip()

    if provider == "gemini":
        return _generate_with_gemini(prompt, model_name)
    if provider == "ollama":
        return _generate_with_ollama(prompt, model_name)

    raise ValueError(
        f"Unsupported RAG_PROVIDER '{provider}'. Use 'gemini' or 'ollama'."
    )
