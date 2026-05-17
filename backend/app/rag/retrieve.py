from app.services.chroma_service import ChromaService
from app.services.embedding_service import EmbeddingService
from app.services.answer_service import AnswerService
from app.rag.prompts import RAG_SYSTEM_PROMPT
from app.rag.llm import generate_answer

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

    sources = [
        {
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
        for index, document in enumerate(retrieved_documents)
    ]
        
    # Join retrieved chunks to form the context
    context_text = "\n\n---\n\n".join(retrieved_documents)
    
    # 4. Construct the Prompt
    final_prompt = RAG_SYSTEM_PROMPT.format(
        context=context_text,
        query=user_query
    )
    
    # 5. Call LLM
    llm_error = None
    try:
        answer = generate_answer(final_prompt)
        answer_mode = "gemini"
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
