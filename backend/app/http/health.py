from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe for the uptime monitor; touches no dependencies."""
    return {"status": "ok"}
