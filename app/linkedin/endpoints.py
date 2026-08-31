"""
Voyager endpoint constants and required request headers.
"""

LINKEDIN_BASE_URL = "https://www.linkedin.com"
VOYAGER_BASE_URL = f"{LINKEDIN_BASE_URL}/voyager/api"

# Current profile endpoint. Query-param based, not
# path-based like the older, now-deprecated pattern.
_PROFILE_DECORATION_ID = "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-93"


def profile_view_url(public_id: str) -> str:
    return (
        f"{VOYAGER_BASE_URL}/identity/dash/profiles"
        f"?q=memberIdentity&memberIdentity={public_id}&decorationId={_PROFILE_DECORATION_ID}"
    )


# Static headers sent with every Voyager request, beyond cookies.
# csrf-token is NOT included here — it's derived per-request from the
# JSESSIONID cookie value (see voyager_client.py).
# The `accept` header matters for the dash API specifically — it expects
# LinkedIn's normalized Rest.li JSON format, not plain application/json.
STATIC_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_5) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "accept-language": "en-US,en;q=0.9",
    "accept": "application/vnd.linkedin.normalized+json+2.1",
    "x-li-lang": "en_US",
    "x-restli-protocol-version": "2.0.0",
}