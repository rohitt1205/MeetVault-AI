import os
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
import google.generativeai as genai

load_dotenv()

def generate_answer(prompt: str) -> str:
    """
    Calls the Gemini API to generate an answer based on the constructed prompt.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set in the environment variables.")
    
    genai.configure(api_key=api_key)
    
    # We use gemini-2.5-flash as it's fast and suitable for simple text generation/RAG tasks
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    response = model.generate_content(prompt)
    
    return response.text
