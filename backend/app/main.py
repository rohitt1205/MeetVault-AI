from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.graph_routes import router as graph_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"message": "MeetVault AI Backend Running"}

app.include_router(graph_router)