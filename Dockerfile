# Deliberately minimal — the deployed service only needs httpx to call
# LinkedIn's Voyager API, not a browser. scripts/ (Playwright) is never
# copied into this image; it's local-only tooling.

FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only app/ — NOT scripts/, NOT tests/, NOT .env. See note above.
COPY app/ ./app/

EXPOSE 8000

# ADMIN_TOKEN, FERNET_KEY, and any RATE_LIMIT_* overrides are supplied as
# platform env vars / secrets at deploy time — never baked into the image.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
