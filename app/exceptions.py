"""
Custom exceptions + centralized FastAPI exception handlers.

Response shape: {"error": "<CODE>", "detail": "<message>"}
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for all domain exceptions. Never raised directly."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, detail: str, headers: dict[str, str] | None = None):
        self.detail = detail
        self.headers = headers or {}
        super().__init__(detail)


class SessionNotConnected(AppError):
    """No LinkedIn session has been established yet (never connected, or
    was explicitly disconnected). Corresponds to auth being absent, hence 401."""

    status_code = 401
    error_code = "SESSION_NOT_CONNECTED"


class SessionChallengeRequired(AppError):
    """LinkedIn responded with a CAPTCHA/checkpoint challenge instead of
    data. The session is no longer usable and requires a human to
    re-run the local bootstrap script. 503 because this is a temporary
    service-side unavailability, not a client input error."""

    status_code = 503
    error_code = "SESSION_CHALLENGE_REQUIRED"


class InvalidProfileUrl(AppError):
    """The provided URL is not a recognizable LinkedIn profile URL.
    Client input error -> 400."""

    status_code = 400
    error_code = "INVALID_PROFILE_URL"


class ProfileNotAccessible(AppError):
    """LinkedIn returned a response indicating the profile is private,
    doesn't exist, or is otherwise not viewable (e.g. 404 from Voyager).
    404 to mirror standard REST semantics for 'resource not found'."""

    status_code = 404
    error_code = "PROFILE_NOT_ACCESSIBLE"


class RateLimited(AppError):
    """Rejected because a LinkedIn request happened too recently (see
    core/rate_limiter.py — non-blocking gate, no queuing/sleeping).
    429, distinct from LinkedIn's own rate limiting (which surfaces as
    SessionChallengeRequired instead)."""

    status_code = 429
    error_code = "RATE_LIMITED"

    def __init__(self, detail: str, retry_after_seconds: float):
        super().__init__(detail, headers={"Retry-After": str(int(retry_after_seconds) + 1)})


class UpstreamError(AppError):
    """LinkedIn returned something that doesn't cleanly fit any other
    category (unexpected status code, malformed JSON, unrecognized
    redirect). 502 signals 'the upstream dependency misbehaved', distinct
    from our own bugs (500) or the caller's input (400)."""

    status_code = 502
    error_code = "UPSTREAM_ERROR"


class InvalidAdminToken(AppError):
    """Missing or incorrect admin token on a protected /auth/* route."""

    status_code = 401
    error_code = "INVALID_ADMIN_TOKEN"


def register_exception_handlers(app: FastAPI) -> None:
    """Call once from main.py at app startup."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.error_code, "detail": exc.detail},
            headers=exc.headers,
        )
