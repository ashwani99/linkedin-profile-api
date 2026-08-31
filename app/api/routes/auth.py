from fastapi import APIRouter, Depends

from app.api.deps import verify_admin_token
from app.core.session_manager import session_manager
from app.models.requests import ConnectRequest
from app.models.responses import StatusResponse

# Every route on this router requires a valid admin bearer token — set
# once at the router level so it can't be forgotten on an individual route.
router = APIRouter(prefix="/auth", dependencies=[Depends(verify_admin_token)])


@router.post("/connect", response_model=StatusResponse)
async def connect(payload: ConnectRequest) -> StatusResponse:
    """Called by scripts/bootstrap_session.py after a successful local
    login. Ingests and activates a session — does not perform login
    itself (see README: automated login is out of scope)."""
    await session_manager.connect(payload.li_at, payload.jsessionid)
    return StatusResponse(**session_manager.get_status())


@router.post("/disconnect", response_model=StatusResponse)
async def disconnect() -> StatusResponse:
    await session_manager.disconnect()
    return StatusResponse(**session_manager.get_status())


@router.get("/status", response_model=StatusResponse)
async def status() -> StatusResponse:
    return StatusResponse(**session_manager.get_status())
