from fastapi import APIRouter, Query

from app.linkedin.parser import parse_profile
from app.linkedin.url_utils import extract_public_id
from app.linkedin.voyager_client import voyager_client
from app.models.responses import ProfileResponse

router = APIRouter()


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    url: str = Query(..., description="A LinkedIn profile URL, e.g. https://www.linkedin.com/in/jane-doe-12345/"),
) -> ProfileResponse:
    public_id = extract_public_id(url)  # raises InvalidProfileUrl (400) on bad input
    raw = await voyager_client.fetch_profile(public_id)
    return parse_profile(raw, profile_url=url)
