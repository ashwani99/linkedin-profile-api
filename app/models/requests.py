from pydantic import BaseModel, Field


class ConnectRequest(BaseModel):
    """Body for POST /auth/connect. Cookie data only — the admin token is
    a header (Authorization: Bearer ...), verified via Depends(), not part
    of this model. See core/security.py + api/deps.py."""

    li_at: str = Field(..., min_length=1)
    jsessionid: str | None = None
