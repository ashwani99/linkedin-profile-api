"""
Sets required env vars BEFORE any `app.*` import happens anywhere in the
test suite. app/config.py instantiates Settings() at module import time,
so this can't live inside a fixture (too late — the import would already
have failed). conftest.py is loaded by pytest before test modules, which
is exactly the timing we need.
"""

import os

from cryptography.fernet import Fernet

os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
