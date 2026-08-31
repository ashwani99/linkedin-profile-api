"""
Application configuration, loaded and validated from environment variables.

Using pydantic-settings instead of raw os.environ.get() calls scattered
across the codebase gets us:
  - Fail-fast startup: if a required var is missing, the app refuses to
    boot with a clear error, instead of failing confusingly on the first
    request that happens to touch that config value.
  - A single source of truth for what configuration the app needs — useful
    documentation in itself (see .env.example, which should mirror this).
  - Type coercion + validation (e.g. RATE_LIMIT_MIN_INTERVAL_SECONDS is
    guaranteed to be a float, not a string, everywhere it's used).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Auth ---
    # Admin token protecting /auth/* routes. Set as a platform env var in
    # deployment, never committed. See README security notes.
    admin_token: str

    # --- Session encryption at rest ---
    # Fernet key used to encrypt the stored LinkedIn session cookie on disk.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    fernet_key: str

    # Where the encrypted session blob lives on disk.
    session_store_path: str = "session.enc"

    # --- Rate limiting ---
    # Minimum seconds between outbound LinkedIn requests, before jitter is added.
    # Conservative default — see README for reasoning (avoiding LinkedIn abuse detection).
    rate_limit_min_interval_seconds: float = 10
    # Random jitter added on top of the min interval, range [0, this value].
    rate_limit_jitter_seconds: float = 2.0

    # --- HTTP client ---
    voyager_request_timeout_seconds: float = 15.0


# Instantiated once at import time. If required env vars are missing,
# this raises immediately on app startup — not on first request.
settings = Settings()
