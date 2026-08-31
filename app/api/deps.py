"""
Shared FastAPI dependencies. Currently just admin-token verification for
the /auth/* routes.
"""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import is_valid_admin_token
from app.exceptions import InvalidAdminToken

# auto_error=False so a missing header falls through to our own
# InvalidAdminToken (consistent {"error", "detail"} shape) instead of
# FastAPI's default HTTPException.
_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_admin_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """Depend on this in any route that should require
    `Authorization: Bearer <ADMIN_TOKEN>`. Raises InvalidAdminToken (401)
    on missing or incorrect token; returns None on success — routes don't
    need the return value, just the fact that it didn't raise."""
    if credentials is None or not is_valid_admin_token(credentials.credentials):
        raise InvalidAdminToken("Missing or invalid admin token.")
