import os
import logging
<<<<<<< HEAD
from typing import Optional

import requests
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

=======
import requests
from typing import Optional
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

# Import Guardrails and Safety Middleware
>>>>>>> origin/main
from app.rag.guardrails_config import SafetyMiddleware

load_dotenv()
logger = logging.getLogger(__name__)
<<<<<<< HEAD
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")


def _generate_with_ollama(prompt: str, model_name: str) -> str:
    if not model_name:
        raise ValueError("RAG_MODEL must be set. Example: qwen2.5:7b")

=======

# Use explicit IPv4 loopback (127.0.0.1) instead of localhost to prevent Windows IPv6 socket [WinError 10061] issues
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

def _get_available_qwen_model() -> str:
    """
    Queries the local Ollama instance to find the exact installed Qwen model tag.
    Returns 'qwen2.5:7b' by default, or the installed tag (e.g. 'qwen2.5:latest', 'qwen2.5').
    """
    default_model = "qwen2.5:7b"
    try:
        res = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if res.status_code == 200:
            models = res.json().get("models", [])
            installed_names = [m.get("name") for m in models if m.get("name")]
            logger.info(f"Installed Ollama models detected: {installed_names}")
            
            # Check for exact match first
            if default_model in installed_names:
                return default_model
            # Check for other qwen variants
            for name in installed_names:
                if "qwen" in name:
                    logger.info(f"Default model '{default_model}' not found. Using installed variant: '{name}'")
                    return name
    except Exception as e:
        logger.warning(f"Could not query Ollama tags at {OLLAMA_BASE_URL}: {e}")
    return default_model

try:
    # pyrefly: ignore [missing-import]
    from langchain_ollama import OllamaLLM
    def get_ollama_llm(model_name: str):
        return OllamaLLM(model=model_name, base_url=OLLAMA_BASE_URL, temperature=0.0)
except ImportError:
    try:
        from langchain_community.llms import Ollama
        def get_ollama_llm(model_name: str):
            return Ollama(model=model_name, base_url=OLLAMA_BASE_URL, temperature=0.0)
    except ImportError:
        def get_ollama_llm(model_name: str):
            return None

def fallback_on_retry_error(retry_state):
    """
    Callback for tenacity retry mechanism when all attempts fail.
    Ensures a graceful production fallback response.
    """
    logger.error(f"Ollama LLM generation failed after all retries: {retry_state.outcome.exception()}")
    return "Information not found in the provided context."

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry_error_callback=fallback_on_retry_error
)
def _invoke_llm(prompt: str) -> str:
    """
    Invokes the local Ollama SLM using LangChain with retry logic.
    Falls back to direct requests API if LangChain wrapper fails or is unavailable.
    """
    model_name = _get_available_qwen_model()
    
    # 1. Try LangChain Ollama wrapper
    llm = get_ollama_llm(model_name)
    if llm:
        try:
            logger.info(f"Invoking LangChain Ollama wrapper ({model_name}) at {OLLAMA_BASE_URL}...")
            return llm.invoke(prompt)
        except Exception as e:
            logger.warning(f"LangChain Ollama wrapper failed with error: {e}. Falling back to direct REST API...")

    # 2. Fallback to direct Ollama REST API
    logger.info(f"Invoking Ollama REST API directly ({OLLAMA_BASE_URL}/api/generate) for model '{model_name}'...")
>>>>>>> origin/main
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={
            "model": model_name,
            "prompt": prompt,
            "stream": False,
<<<<<<< HEAD
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
=======
            "options": {"temperature": 0.0, "top_p": 0.1}
        },
        timeout=30
    )
    if response.status_code != 200:
        logger.error(f"Ollama REST API error ({response.status_code}): {response.text}")
        response.raise_for_status()
        
    return response.json().get("response", "")

def generate_answer(prompt: str, query: Optional[str] = None, context: Optional[str] = None) -> str:
    """
    Production-grade generation function for MeetVault RAG.
    Replaces Gemini with local Qwen2.5 SLM.
    Includes input validation, pure Python SafetyMiddleware enforcement,
    retry logic, exception handling, and guaranteed fallback responses.
    """
    fallback_response = "Information not found in the provided context."

    # 1. Input Validation (Anti-Prompt-Injection & Jailbreak Check)
    if query:
        is_safe = SafetyMiddleware.validate_input(query)
        if not is_safe:
            logger.warning("Input validation failed: Malicious query or prompt injection detected.")
            return fallback_response

    # 2. LLM Invocation with Exception Handling & Retry Logic
    try:
        raw_output = _invoke_llm(prompt)
    except Exception as e:
        logger.error(f"Fatal error in LLM invocation: {e}")
        return fallback_response

    # 3. Output Validation & Context Grounding Enforcement
    validated_output = SafetyMiddleware.validate_output(raw_output, context=context, query=query)

    # 4. Output Sanitization
    final_output = SafetyMiddleware.sanitize_output(validated_output)

    return final_output
>>>>>>> origin/main
