from app.services.chroma_service import ChromaService
from app.rag.ingest import embedding_model
from app.rag.prompts import RAG_SYSTEM_PROMPT
from app.rag.llm import generate_answer

def retrieve_and_answer(user_query: str) -> dict:
    """
    Retrieves relevant transcript chunks from ChromaDB based on the user query,
    constructs a prompt, and calls the LLM to get a grounded answer.
    """
    # 1. Embed the user query
    query_embedding = embedding_model.encode(user_query).tolist()
    
    # 2. Query ChromaDB for relevant chunks
    results = ChromaService.query_embeddings(query_embedding)
    
    # 3. Extract the text chunks from the results
    # results["documents"] is a list of lists, where the inner list corresponds to the single query
    retrieved_documents = results.get("documents", [[]])[0]
    
    if not retrieved_documents:
        return {
            "query": user_query,
            "answer": "I don't have any meeting transcripts to answer that question.",
            "sources": []
        }
        
    # Join retrieved chunks to form the context
    context_text = "\n\n---\n\n".join(retrieved_documents)
    
    # 4. Construct the Prompt
    final_prompt = RAG_SYSTEM_PROMPT.format(
        context=context_text,
        query=user_query
    )
    
    # 5. Call LLM
    try:
        answer = generate_answer(final_prompt)
    except Exception as e:
        answer = f"Error generating answer from LLM: {str(e)}"
        
    return {
        "query": user_query,
        "answer": answer,
        "sources": retrieved_documents
    }
