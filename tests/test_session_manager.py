"""
Each test gets its own SessionManager pointed at a pytest tmp_path file,
so tests never share state or leave artifacts behind (no cleanup needed —
pytest tears down tmp_path automatically).
"""

import asyncio

import pytest

from app.core.session_manager import SessionManager, SessionStatus
from app.exceptions import SessionChallengeRequired, SessionNotConnected


@pytest.fixture
def manager(tmp_path):
    return SessionManager(store_path=str(tmp_path / "session.enc"))


def test_fresh_manager_is_disconnected(manager):
    status = manager.get_status()
    assert status["status"] == SessionStatus.DISCONNECTED.value
    assert status["connected_at"] is None


def test_get_cookies_raises_when_disconnected(manager):
    with pytest.raises(SessionNotConnected):
        manager.get_cookies()


def test_connect_then_get_cookies(manager):
    asyncio.run(manager.connect("fake-li-at-value", "fake-jsessionid"))
    cookies = manager.get_cookies()
    assert cookies["li_at"] == "fake-li-at-value"
    assert cookies["JSESSIONID"] == "fake-jsessionid"

    status = manager.get_status()
    assert status["status"] == SessionStatus.CONNECTED.value
    assert status["connected_at"] is not None


def test_connect_without_jsessionid(manager):
    asyncio.run(manager.connect("fake-li-at-value", None))
    cookies = manager.get_cookies()
    assert cookies["li_at"] == "fake-li-at-value"
    assert "JSESSIONID" not in cookies


def test_disconnect_clears_session_and_deletes_file(manager, tmp_path):
    asyncio.run(manager.connect("fake-li-at-value", "fake-jsessionid"))
    store_file = tmp_path / "session.enc"
    assert store_file.exists()

    asyncio.run(manager.disconnect())

    assert not store_file.exists()  # deliberate full wipe, not just a status flip
    with pytest.raises(SessionNotConnected):
        manager.get_cookies()


def test_mark_challenge_required_locked_preserves_connected_at(manager, tmp_path):
    """Challenge should flip status but NOT delete the file or lose
    connected_at — this is deliberately different from disconnect(), so
    you can still see how long a session survived before breaking."""
    asyncio.run(manager.connect("fake-li-at-value", "fake-jsessionid"))
    original_status = manager.get_status()
    store_file = tmp_path / "session.enc"

    manager.mark_challenge_required_locked()

    assert store_file.exists()  # file preserved, unlike disconnect()
    new_status = manager.get_status()
    assert new_status["status"] == SessionStatus.CHALLENGE_REQUIRED.value
    assert new_status["connected_at"] == original_status["connected_at"]  # preserved


def test_get_cookies_raises_challenge_required_after_challenge(manager):
    asyncio.run(manager.connect("fake-li-at-value", "fake-jsessionid"))
    manager.mark_challenge_required_locked()
    with pytest.raises(SessionChallengeRequired):
        manager.get_cookies()


def test_session_survives_reload_from_disk(tmp_path):
    """Simulates a process restart: a second SessionManager instance
    pointed at the same file should pick up the persisted, encrypted
    session — this is the actual point of persisting to disk at all."""
    store_path = str(tmp_path / "session.enc")
    manager1 = SessionManager(store_path=store_path)
    asyncio.run(manager1.connect("fake-li-at-value", "fake-jsessionid"))

    manager2 = SessionManager(store_path=store_path)  # fresh instance, same file
    cookies = manager2.get_cookies()
    assert cookies["li_at"] == "fake-li-at-value"


def test_missing_file_is_treated_as_disconnected_not_a_crash(tmp_path):
    manager = SessionManager(store_path=str(tmp_path / "does_not_exist.enc"))
    status = manager.get_status()
    assert status["status"] == SessionStatus.DISCONNECTED.value


def test_corrupted_file_is_treated_as_disconnected_not_a_crash(tmp_path):
    """A file that exists but isn't valid encrypted session data (wrong
    key, corrupted bytes, etc.) should degrade to 'no session', not
    crash SessionManager's constructor / _load()."""
    store_path = tmp_path / "session.enc"
    store_path.write_bytes(b"not-valid-fernet-ciphertext-at-all")
    manager = SessionManager(store_path=str(store_path))
    status = manager.get_status()
    assert status["status"] == SessionStatus.DISCONNECTED.value
