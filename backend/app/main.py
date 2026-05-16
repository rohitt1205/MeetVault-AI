from fastapi import FastAPI
from app.api.graph_routes import router as graph_router
from app.rag.router import router as rag_router

app = FastAPI()


@app.get("/")
def home():
    return {"message": "MeetVault AI Backend Running"}


app.include_router(graph_router)
app.include_router(rag_router)