"""
Ties together: SessionManager (cookies + serialization lock),
RateLimiter (throttling), and the endpoint/header constants. This is the
only file that actually talks to linkedin.com.

Uses curl_cffi instead of httpx specifically to impersonate a real
Chrome TLS/HTTP fingerprint (JA3, ClientHello, header ordering) — not
just Chrome-like headers. A raw httpx client, even with a realistic
User-Agent, has a fingerprint anti-abuse systems can distinguish from an
actual browser. This was added after live testing showed LinkedIn
issuing an explicit session-kill (Set-Cookie deleting li_at) after
exactly one httpx-based request — see notes.md section 13.

Lock discipline: `session_manager.lock` is held for the ENTIRE outbound
request (acquire -> get cookies -> rate check -> HTTP call -> interpret
response -> release). This serializes all LinkedIn traffic through one
request at a time, which is deliberate — see notes.md for why (single
shared LinkedIn identity, concurrent requests would be a detection
signal). Any mutation to session state while the lock is held MUST use
the `_locked` variant of the relevant SessionManager method, never the
plain async one — see the deadlock note in session_manager.py.
"""

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.errors import RequestsError

from app.config import settings
from app.core.rate_limiter import rate_limiter
from app.core.session_manager import session_manager
from app.exceptions import ProfileNotAccessible, SessionChallengeRequired, UpstreamError
from app.linkedin.endpoints import STATIC_HEADERS, profile_view_url

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_CHALLENGE_URL_MARKERS = ("checkpoint", "challenge", "/uas/login")
_IMPERSONATE = "chrome124"


class VoyagerClient:
    def __init__(self):
        self._client = AsyncSession(timeout=settings.voyager_request_timeout_seconds)

    async def aclose(self) -> None:
        await self._client.close()

    async def fetch_profile(self, public_id: str) -> dict:
        """Returns the raw Voyager profileView JSON. Raises SessionNotConnected,
        SessionChallengeRequired, RateLimited, ProfileNotAccessible, or
        UpstreamError — never returns a partial/malformed dict."""
        async with session_manager.lock:
            cookies = session_manager.get_cookies()  # raises if not usable
            rate_limiter.check()  # raises RateLimited if too soon

            jsessionid = cookies.get("JSESSIONID", "").strip('"')
            headers = {**STATIC_HEADERS, "csrf-token": jsessionid}

            try:
                response = await self._client.get(
                    profile_view_url(public_id),
                    cookies=cookies,
                    headers=headers,
                    allow_redirects=False,
                    impersonate=_IMPERSONATE,
                )
            except RequestsError as exc:
                raise UpstreamError(f"Network error contacting LinkedIn: {exc}") from exc

            # LinkedIn may rotate (or, as observed, explicitly kill)
            # cookies on any response. Capture and persist any change
            # BEFORE interpreting the response, so it's saved regardless
            # of what we do with THIS response.
            new_li_at = response.cookies.get("li_at")
            new_jsessionid = response.cookies.get("JSESSIONID")
            if new_li_at or new_jsessionid:
                session_manager.update_cookies_locked(li_at=new_li_at, jsessionid=new_jsessionid)

            return self._interpret_response(response)

    def _interpret_response(self, response) -> dict:
        # A redirect to a login/checkpoint/challenge page means the
        # session is no longer usable — most common cause of this in
        # practice.
        if response.status_code in _REDIRECT_STATUSES:
            location = response.headers.get("location", "")
            print(  # TODO: remove this later
                f"[DEBUG] Redirect encountered. Status={response.status_code} "
                f"Location='{location}' "
                f"Set-Cookie header={response.headers.get('set-cookie')} "
                f"All response headers={dict(response.headers)}",
                flush=True,
            )
            if any(marker in location for marker in _CHALLENGE_URL_MARKERS):
                session_manager.mark_challenge_required_locked()
                raise SessionChallengeRequired(
                    "LinkedIn redirected to a login/checkpoint page. "
                    "Re-run the local bootstrap script to reconnect."
                )
            raise UpstreamError(f"Unexpected redirect to '{location}'.")

        # 401/403 without a redirect is the other common "session dead" shape.
        if response.status_code in (401, 403):
            session_manager.mark_challenge_required_locked()
            raise SessionChallengeRequired(
                "LinkedIn rejected the request as unauthorized. "
                "Re-run the local bootstrap script to reconnect."
            )

        if response.status_code == 404:
            raise ProfileNotAccessible(
                "Profile not found, private, or otherwise not viewable."
            )

        if response.status_code != 200:
            raise UpstreamError(
                f"LinkedIn returned unexpected status {response.status_code}."
            )

        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            # A 200 with an HTML body typically means we got a login page,
            # not data — treat the same as an explicit challenge.
            session_manager.mark_challenge_required_locked()
            raise SessionChallengeRequired(
                "LinkedIn returned an HTML page instead of profile data "
                "(likely a login/checkpoint page). Re-run the local "
                "bootstrap script to reconnect."
            )

        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamError("LinkedIn returned a response that wasn't valid JSON.") from exc


# Single shared instance + client — reused across requests for connection
# pooling. Created/closed via FastAPI lifespan in main.py.
voyager_client = VoyagerClient()