from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import jobs
from app.config import frontend_dist
from app.http import (
    api,
    api_admin_roster,
    api_alerts,
    api_calls,
    api_drafts,
    api_quick_entry,
    api_request_edit,
    health,
    hooks,
    spa,
    tools,
)
from app.observability import init_from_env

init_from_env()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    jobs.start_scheduler()  # scheduled jobs, architecture §6 (end-of-day summary, #23)
    try:
        yield
    finally:
        jobs.stop_scheduler()


app = FastAPI(title="Voice Agent", lifespan=lifespan)
app.include_router(health.router)
app.include_router(hooks.router)
app.include_router(tools.router)
app.include_router(api.router)
app.include_router(api_drafts.router)
app.include_router(api_admin_roster.router)
app.include_router(api_calls.router)
app.include_router(api_quick_entry.router)
app.include_router(api_request_edit.router)
app.include_router(api_alerts.router)
# Last: the dashboard's catch-all route must not shadow the API.
spa.mount(app, frontend_dist())
