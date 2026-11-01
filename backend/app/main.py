from fastapi import FastAPI

from app.http import health

app = FastAPI(title="Voice Agent")
app.include_router(health.router)
