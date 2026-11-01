from fastapi import FastAPI

from app.config import frontend_dist
from app.http import api, health, spa
from app.observability import init_from_env

init_from_env()

app = FastAPI(title="Voice Agent")
app.include_router(health.router)
app.include_router(api.router)
# Last: the dashboard's catch-all route must not shadow the API.
spa.mount(app, frontend_dist())
