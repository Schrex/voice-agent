from fastapi import FastAPI

from app.http import health, hooks
from app.observability import init_from_env

init_from_env()

app = FastAPI(title="Voice Agent")
app.include_router(health.router)
app.include_router(hooks.router)
