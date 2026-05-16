from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.graph_routes import router as graph_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"message": "MeetVault AI Backend Running"}

app.include_router(graph_router)