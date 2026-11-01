from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from apscheduler.schedulers.base import BaseScheduler
from fastapi import FastAPI

from app.config import frontend_dist, scheduler_enabled
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
from app.jobs import build_scheduler
from app.observability import init_from_env

init_from_env()

# The running scheduler (architecture §6), or None when off or the app is not running.
scheduler: BaseScheduler | None = None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global scheduler
    if scheduler_enabled():
        scheduler = build_scheduler()
        scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
            scheduler = None


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
