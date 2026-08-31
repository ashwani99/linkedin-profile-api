"""
Validates that an input URL is a plausible LinkedIn profile URL and
extracts the public_id Voyager needs (e.g. 'jane-doe-12345' from
https://www.linkedin.com/in/jane-doe-12345/).
"""

import re
from urllib.parse import urlparse

from app.exceptions import InvalidProfileUrl

# Accepts optional locale subdomain (e.g. in.linkedin.com, uk.linkedin.com)
# and optional www.
_ALLOWED_HOST_RE = re.compile(r"^([a-z]{2,3}\.)?(www\.)?linkedin\.com$", re.IGNORECASE)
_PROFILE_PATH_RE = re.compile(r"^/in/([A-Za-z0-9\-_%.]+)/?$")


def extract_public_id(url: str) -> str:
    parsed = urlparse((url or "").strip())

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise InvalidProfileUrl("URL must be an absolute http(s) URL.")

    if not _ALLOWED_HOST_RE.match(parsed.hostname):
        raise InvalidProfileUrl(f"'{parsed.hostname}' is not a linkedin.com host.")

    match = _PROFILE_PATH_RE.match(parsed.path)
    if not match:
        raise InvalidProfileUrl(
            "URL path must look like '/in/<public-id>' (e.g. /in/jane-doe-12345)."
        )

    return match.group(1)
