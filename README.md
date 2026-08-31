# LinkedIn Profile API

A hosted API that accepts a public LinkedIn profile URL and returns structured
profile data (name, headline, location, about, experience, education,
skills, certifications, languages, and profile image) as JSON.

**This project scrapes LinkedIn using an unofficial, undocumented internal
API and a personal LinkedIn account, as explicitly permitted by the task
brief.** This is not sanctioned by LinkedIn's Terms of Service. See
[Legal & Ethical Considerations](#legal--ethical-considerations) below —
please read that section, it materially shapes several design decisions
in this repo.

---

## Table of Contents
- [Approach](#approach)
- [Architecture](#architecture)
- [API Documentation](#api-documentation)
- [Setup Instructions](#setup-instructions)
- [Security Notes](#security-notes)
- [Testing](#testing)
- [Known Limitations](#known-limitations)
- [Legal & Ethical Considerations](#legal--ethical-considerations)
- [Future Work](#future-work)

---

## Approach

LinkedIn's public HTML is difficult to scrape reliably (heavily
obfuscated class names, lazy-loaded sections). LinkedIn's own frontend
instead calls an internal, undocumented JSON API — referred to in the
community as **"Voyager"** — which is considerably more stable across
markup changes since LinkedIn's own UI depends on it.

However, calling Voyager endpoints directly from a bare HTTP client
(no browser context) is *more* fingerprintable to anti-abuse systems,
not less — a raw client lacks the TLS fingerprint, header ordering, and
JS execution signals a real browser produces.

**This project uses a hybrid approach:**
1. A **real, visible browser (Playwright/Chromium)**, driven by a human,
   is used once to log into LinkedIn and establish a legitimate,
   browser-originated session.
2. The extracted session cookie is then reused to call Voyager's JSON
   endpoints directly via a lightweight HTTP client (`httpx`) — giving
   stable, structured data without needing a browser at request time.

This means the **deployed API itself never runs a browser** — only a
local, one-time bootstrap script does. See [Architecture](#architecture).

The Voyager endpoint map used here (URL patterns, required headers,
cookie/csrf-token relationship) was **not reverse-engineered from
scratch**. It was cross-referenced against the open-source community
project `open-linkedin-api` (a maintained fork of the now-private
`tomquirk/linkedin-api`), which has already done this reverse-engineering
work and published it. The exact *nested* field names inside each
profile section (experience, education, etc.) were not fully confirmed
against a live response at the time of writing — see
[Known Limitations](#known-limitations).

---

## Architecture

```
┌──────────────────────────────┐
│  scripts/bootstrap_session.py │   ← runs LOCALLY, on your machine only
│  (Playwright, visible browser)│      never deployed, never imported by app/
└───────────────┬────────────────┘
                 │ HTTPS POST /auth/connect (cookie + admin token)
                 ▼
┌───────────────────────────────────────────────┐
│              Deployed FastAPI service           │
│                                                   │
│  GET  /profile        (public — the product)     │
│  GET  /auth/status     ┐                         │
│  POST /auth/connect    ├─ admin-token protected   │
│  POST /auth/disconnect ┘                         │
│  GET  /health          (liveness only)           │
│                                                   │
│  SessionManager  — encrypted-at-rest cookie       │
│                     store, asyncio.Lock for       │
│                     serialized LinkedIn access    │
│  RateLimiter     — reject-based (429), jitter     │
│  VoyagerClient   — httpx calls to LinkedIn's      │
│                     internal JSON API             │
│  ProfileParser   — raw JSON → response schema,    │
│                     defensive, never crashes on   │
│                     missing/unexpected fields     │
└───────────────────────────────────────────────┘
```

**The deployed server never runs a browser.** Only `httpx` is used to
call LinkedIn at request time — no Playwright/Chromium in the deployed
image (see `Dockerfile`, which only copies `app/`).

### Why a single, shared LinkedIn session
This project uses **one personal LinkedIn account** (per the task brief).
All incoming `/profile` requests share that one session, serialized
through a single lock — concurrent requests are never sent to LinkedIn
in parallel, since that itself is a strong signal to LinkedIn's abuse
detection. This is a deliberate, load-bearing architectural constraint,
not an accidental bottleneck — see [Known Limitations](#known-limitations).

### Session lifecycle
- **Bootstrap (semi-manual, by design):** `scripts/bootstrap_session.py`
  opens a real, visible browser on your machine. You log in yourself,
  including any 2FA/verification step LinkedIn requires. The script then
  extracts the session cookie and pushes it to the deployed API's
  `POST /auth/connect`. **Automated login (handling 2FA/checkpoints
  without a human) is explicitly out of scope** — see Known Limitations.
- **Normal operation:** the deployed API only *reads* the stored,
  encrypted session — it never performs a login itself.
- **Failure modes are distinguished, not conflated:**
  - *Rate limited by us* (`429`) — our own throttle rejected a request
    that came in too soon after the last one. Session is still fine.
  - *Session challenge required* (`503`) — LinkedIn returned a
    CAPTCHA/checkpoint or an authentication failure. The session is
    dead; **re-running the bootstrap script is required** before
    `/profile` will work again. This is *not* fixed by simply
    logging out and back in with the same account/device/behavior
    pattern — LinkedIn's challenge is tied to a trust/reputation signal
    on that account+pattern, not the token's freshness.

---

## API Documentation

Interactive OpenAPI/Swagger docs are auto-generated by FastAPI and
available at `/docs` on the running server.

### `GET /profile?url=<linkedin-profile-url>`
Public, no auth required.

**Example:**
```
GET /profile?url=https://www.linkedin.com/in/jane-doe-12345/
```

**Success response (`200`):**
```json
{
  "profile_url": "https://www.linkedin.com/in/jane-doe-12345/",
  "name": "Jane Doe",
  "headline": "Senior Software Engineer at Acme Corp",
  "location": "San Francisco Bay Area",
  "about": "Passionate backend engineer with 10 years of experience...",
  "profile_image_url": "https://media.licdn.com/dms/image/...",
  "experience": [
    {
      "title": "Senior Software Engineer",
      "company": "Acme Corp",
      "location": "San Francisco, CA",
      "duration": "06/2021 - Present",
      "description": "Leading backend infrastructure team."
    }
  ],
  "education": [
    {"school": "State University", "degree": "B.S. Computer Science", "duration": "2014 - 2018"}
  ],
  "skills": ["Python", "Distributed Systems", "Kubernetes"],
  "certifications": [
    {"name": "AWS Certified Solutions Architect", "issuer": "Amazon Web Services", "date": "03/2022"}
  ],
  "languages": ["English", "Spanish"],
  "scraped_at": "2026-08-30T12:00:00+00:00",
  "warnings": []
}
```

`warnings` is populated (non-fatally) when a section couldn't be fully
extracted — e.g. a missing profile picture — rather than silently
omitting it or failing the whole request.

### `GET /auth/status`
Admin-token protected. Reports current session state without making a
live LinkedIn call.
```json
{"status": "connected", "connected_at": "2026-08-30T09:00:00+00:00"}
```
`status` is one of `connected`, `disconnected`, `challenge_required`.

### `POST /auth/connect`
Admin-token protected. Called only by `scripts/bootstrap_session.py`.
**Activates a pre-bootstrapped session — does not perform login itself.**
```json
// Request body
{"li_at": "<cookie value>", "jsessionid": "<cookie value, optional>"}
```

### `POST /auth/disconnect`
Admin-token protected. Explicitly revokes the current session (deletes
the stored cookie) without requiring a redeploy.

### `GET /health`
Public. Pure liveness — returns `{"status": "ok"}` if the process is
running. Deliberately does **not** call LinkedIn (see
[Known Limitations](#known-limitations) for why).

### Authentication
`/auth/*` routes require `Authorization: Bearer <ADMIN_TOKEN>`.

### Error format
All errors share one shape:
```json
{"error": "SESSION_CHALLENGE_REQUIRED", "detail": "LinkedIn redirected to a login/checkpoint page. Re-run the local bootstrap script to reconnect."}
```

| HTTP Status | `error` code | Meaning |
|---|---|---|
| 400 | `INVALID_PROFILE_URL` | URL isn't a recognizable `linkedin.com/in/...` profile URL |
| 401 | `SESSION_NOT_CONNECTED` | No session has ever been connected |
| 401 | `INVALID_ADMIN_TOKEN` | Missing/incorrect admin token on a protected route |
| 404 | `PROFILE_NOT_ACCESSIBLE` | Profile doesn't exist, is private, or isn't viewable |
| 429 | `RATE_LIMITED` | Our own throttle rejected the request; see `Retry-After` header |
| 502 | `UPSTREAM_ERROR` | LinkedIn returned something unexpected we couldn't categorize |
| 503 | `SESSION_CHALLENGE_REQUIRED` | LinkedIn issued a challenge; session is dead, needs reconnect |

---

## Setup Instructions

### Prerequisites
- Python 3.12+
- A personal LinkedIn account you're comfortable using for this (see
  [Legal & Ethical Considerations](#legal--ethical-considerations))

### 1. Deploy the API
```bash
git clone <this-repo>
cd linkedin-profile-api

# Set these as platform secrets/env vars on your host (Fly.io, Render,
# Railway, etc. — any host that runs a Dockerfile and lets you set
# persistent env vars works):
#   ADMIN_TOKEN     — any long random string, e.g. `openssl rand -hex 32`
#   FERNET_KEY      — python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

docker build -t linkedin-profile-api .
# deploy the built image to your platform of choice, with the above
# env vars set, exposing port 8000 behind HTTPS (most platforms provide
# this automatically)
```

### 2. Bootstrap a LinkedIn session (from your own machine, not the server)
```bash
cd scripts
pip install -r requirements.txt
playwright install chromium

python bootstrap_session.py \
  --api-url https://your-deployed-api.example.com \
  --admin-token <the ADMIN_TOKEN you set above>
```
A real Chromium window will open to LinkedIn's login page. Log in
manually (including any 2FA/verification). Once you see your feed,
return to the terminal and press Enter — the script extracts your
session cookie and pushes it to your deployed API automatically.

### 3. Verify it works
```bash
curl "https://your-deployed-api.example.com/profile?url=https://www.linkedin.com/in/<your-own-public-profile>/"
```
This manual check is the real end-to-end verification — see
[Known Limitations](#known-limitations) on why `/health` deliberately
doesn't automate this.

### Local development (running the API on your own machine)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ADMIN_TOKEN and FERNET_KEY
uvicorn app.main:app --reload
```

### Running tests
```bash
pip install -r requirements.txt   # includes pytest
pytest tests/ -v
```

---

## Security Notes

- **Admin token**: read from an environment variable, never hardcoded or
  committed (`.gitignore` excludes `.env`). Sent as `Authorization:
  Bearer <token>`, not a query parameter (query params leak into access
  logs and browser history). Compared using `hmac.compare_digest`
  rather than `==`, to avoid a timing side-channel — a defense-in-depth
  measure, not a response to a demonstrated real-world exploit at this
  scale.
- **Session cookie**: encrypted at rest on disk (`cryptography.fernet`),
  never logged anywhere (including error traces). In transit, protected
  by the mandatory HTTPS requirement — no custom transport encryption
  was built on top of TLS, since that would be redundant.
- **Cookie handoff**: the bootstrap script talks to LinkedIn's login
  page directly (never through this API), and separately pushes the
  resulting cookie to `/auth/connect` over HTTPS. The deployed API never
  sees your LinkedIn password.
- **Production gaps, named explicitly rather than glossed over:** a real
  production deployment would use a dedicated secrets manager (AWS
  Secrets Manager / HashiCorp Vault) with automatic rotation and access
  audit logging, rather than a platform env var and a Fernet-encrypted
  file. This wasn't built here — it's a legitimate scope cut for a
  take-home, not an oversight.

---

## Testing

`tests/` covers the parser, rate limiter, and session manager (26 tests,
run in well under a second — no real network calls, no real sleeps).

**Important, stated plainly:** the parser tests run against a
**synthetic, hand-built fixture** (`tests/fixtures/sample_voyager_response.json`),
not a real captured LinkedIn response, because building this without
live LinkedIn access was necessary to keep the test suite runnable by
anyone (including CI) without credentials. The top-level structure of
this fixture is grounded in the verified `open-linkedin-api` reference
implementation; the deeply-nested field names are a best-effort,
un-confirmed inference. **This is a known gap, not an oversight** — see
below.

---

## Known Limitations

Stated directly, because a take-home that hides its own limitations is
less useful than one that names them clearly:

- **Automated login is out of scope.** `bootstrap_session.py` requires a
  human to complete login (including any 2FA/checkpoint) on their own
  machine. There is no automated re-login on session expiry — this is a
  deliberate choice, not an oversight (see Approach).
- **CAPTCHA/challenge auto-solving is not built**, and shouldn't be — a
  challenge is surfaced as a clear `503 SESSION_CHALLENGE_REQUIRED`
  error requiring a human to re-run the bootstrap script.
- **Single-account, single-session architecture.** There is a hard
  ceiling on request volume before triggering LinkedIn's abuse
  detection. This is not multi-tenant and does not horizontally scale
  without a pool of accounts and rotation logic, which was out of scope.
- **Parser field-mapping is not fully verified against live data.** The
  top-level Voyager response structure is confirmed against a real
  open-source reference implementation; specific nested field names
  (e.g. inside experience/education entries) are best-effort and may
  need correction against real responses.
- **Certain fields are likely to be partial on some profiles:** `skills`
  and `certifications` may be truncated relative to what LinkedIn shows
  behind a "show all" expansion in the UI, which is not fetched
  separately; very long `experience`/`education` lists may be paginated
  by LinkedIn in ways this implementation doesn't follow.
- **`/health` is intentionally a pure liveness check** — it does not
  verify LinkedIn connectivity, because coupling a liveness probe to an
  external, adversarial dependency's uptime risks unnecessary restarts
  when LinkedIn (not this service) is having a bad day. `/auth/status`
  and a manual `/profile` call are the correct tools for verifying the
  LinkedIn-dependent parts of the system.
- **Reliability has a structural ceiling, not just a code-quality one.**
  Community-documented experience with LinkedIn's Voyager API suggests
  detection of non-official usage within roughly 3–7 days, with
  LinkedIn periodically rotating internal token formats when a given
  scraping approach becomes popular enough to appear in abuse patterns.
  This is inherent to building on an adversarial, undocumented API — see
  [Legal & Ethical Considerations](#legal--ethical-considerations).

---

## Legal & Ethical Considerations

LinkedIn's Terms of Service prohibit automated scraping. This project
was built per the task brief, which explicitly permits using personal
LinkedIn credentials — but that permission doesn't change LinkedIn's own
policy, and using this account for this purpose carries a real risk of
LinkedIn restricting or banning it.

**On the legal question specifically:** *hiQ Labs v. LinkedIn* (9th
Circuit) found that scraping publicly-visible data does not violate the
Computer Fraud and Abuse Act — but that is a narrow criminal-law finding,
not a defense against a ToS/breach-of-contract claim, which LinkedIn can
still pursue, alongside simply banning the account.

**On whether this kind of integration is reliable at all:** PhantomBuster
— a funded company built around this exact approach, and the reference
implementation cited in the task brief — states in its own
documentation that LinkedIn automation is never risk-free and that
accounts can be restricted regardless of how carefully automation is
paced. Independent reviews report meaningful account-restriction rates
for heavy usage. This project treats that fragility as a structural
property of unofficial integrations with an adversarial platform, not a
solvable engineering problem — the defensive measures here (rate
limiting, clear failure signaling, explicit session revocation) reduce
risk and make failures diagnosable, but do not eliminate it.

A compliant production alternative would use LinkedIn's official Partner
API (requires LinkedIn's approval) or a licensed third-party data
provider, rather than an unofficial internal API.

---

## Future Work

- Automated session refresh with challenge detection and alerting
  (e.g. a remote-debuggable headless browser behind `noVNC`, so a human
  can resolve a challenge without local machine access).
- A pool of LinkedIn accounts with rotation and per-account rate
  budgets, to remove the single-session bottleneck.
- A dedicated secrets manager (Vault/AWS Secrets Manager) with rotation
  and access audit logging, replacing the current env-var + encrypted-file
  approach.
- Shared session/rate-limiter state (e.g. Redis) if ever running more
  than one instance — the current in-memory lock only works
  single-instance.
- Validate and correct `parser.py`'s nested field mappings against real
  captured Voyager responses, replacing the synthetic test fixtures with
  real (sanitized) ones.
