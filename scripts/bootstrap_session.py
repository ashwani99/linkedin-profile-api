#!/usr/bin/env python3
"""
LOCAL-ONLY. Run this on your own machine — never deployed, never imported
by app/ code (see Dockerfile, which only COPYs app/).

Opens a real, visible Chromium window so you can log into LinkedIn
yourself, including any 2FA/checkpoint challenge. Once you confirm login
is complete, extracts the session cookies (li_at, JSESSIONID) and pushes
them to your deployed API's admin-protected POST /auth/connect.

Setup:
    pip install playwright
    playwright install chromium

Usage:
    python scripts/bootstrap_session.py \\
        --api-url https://your-deployed-api.example.com \\
        --admin-token <your ADMIN_TOKEN>

    (Or set API_URL / ADMIN_TOKEN env vars instead of flags.)

Automated login/2FA handling is deliberately out of scope — see README
Known Limitations. This script always requires a human at the keyboard.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

LOGIN_URL = "https://www.linkedin.com/login"


def extract_session_cookies(cookies: list[dict]) -> tuple[str, str | None]:
    li_at = None
    jsessionid = None
    for c in cookies:
        if c["name"] == "li_at":
            li_at = c["value"]
        elif c["name"] == "JSESSIONID":
            jsessionid = c["value"]

    if not li_at:
        print(
            "ERROR: 'li_at' cookie not found after login. "
            "Did you complete login successfully before pressing Enter?",
            file=sys.stderr,
        )
        sys.exit(1)

    return li_at, jsessionid


def push_session(api_url: str, admin_token: str, li_at: str, jsessionid: str | None) -> None:
    url = api_url.rstrip("/") + "/auth/connect"
    payload = json.dumps({"li_at": li_at, "jsessionid": jsessionid}).encode()

    request = urllib.request.Request(url, data=payload, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {admin_token}")

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            print(f"Session connected successfully (HTTP {response.status}):")
            print(response.read().decode())
    except urllib.error.HTTPError as exc:
        print(f"Failed to connect session (HTTP {exc.code}):", file=sys.stderr)
        print(exc.read().decode(), file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"Network error reaching {url}: {exc}", file=sys.stderr)
        sys.exit(1)


def run_login_flow() -> list[dict]:
    """Opens a headed browser, waits for the human to log in, returns the
    resulting cookie jar. Isolated from push_session so the two concerns
    (getting cookies vs. sending them) stay independently testable."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL)

        print("\n" + "=" * 70)
        print("A Chromium window has opened to LinkedIn's login page.")
        print("Log in manually — including any 2FA or verification step.")
        print("Once you see your LinkedIn feed/home page, return here and")
        print("press Enter to continue.")
        print("=" * 70 + "\n")
        input("Press Enter once you've finished logging in... ")

        cookies = context.cookies()
        browser.close()
        return cookies


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", default=os.environ.get("API_URL"))
    parser.add_argument("--admin-token", default=os.environ.get("ADMIN_TOKEN"))
    args = parser.parse_args()

    if not args.api_url or not args.admin_token:
        parser.error(
            "--api-url and --admin-token are required "
            "(or set API_URL / ADMIN_TOKEN environment variables)."
        )

    cookies = run_login_flow()
    li_at, jsessionid = extract_session_cookies(cookies)
    print("Session cookies extracted. Pushing to API...")
    push_session(args.api_url, args.admin_token, li_at, jsessionid)


if __name__ == "__main__":
    main()
