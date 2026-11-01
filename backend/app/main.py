from fastapi import FastAPI

from app.http import health, hooks

app = FastAPI(title="Voice Agent")
app.include_router(health.router)
app.include_router(hooks.router)
