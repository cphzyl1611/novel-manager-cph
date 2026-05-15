"""Tests for pairing API and device authorization."""
from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path

from novel_manager.db import connect as db_connect, initialize
from novel_manager.server.services.pairing_service import (
    create_pairing_session,
    confirm_pairing,
    verify_device_token,
    list_paired_devices,
    revoke_device,
    is_localhost_request,
    cleanup_expired_pairing_sessions,
    _ensure_tables,
)
from novel_manager.server.services.sync_service import get_sync_manifest


def _make_repo() -> Path:
    """Create a temporary repo with test data."""
    repo = Path(tempfile.mkdtemp())
    (repo / "library").mkdir()
    (repo / "incoming").mkdir()
    (repo / "db").mkdir()

    conn = db_connect(repo)
    initialize(conn)

    # Add test book
    conn.execute(
        """INSERT INTO books
           (current_path, title_raw, title_norm, author_raw, author_norm,
            file_size, raw_sha256, clean_sha256, chapter_count, quality_score,
            quality_level, repo_area, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "library/book1.txt",
            "测试小说",
            "测试小说",
            "作者",
            "作者",
            100000,
            "sha256_aaa",
            "sha256_clean_aaa",
            100,
            85.0,
            "good",
            "library",
            "active",
        ),
    )
    conn.commit()
    conn.close()

    return repo


def test_create_pairing_session():
    """Test creating a pairing session."""
    repo = _make_repo()
    try:
        result = create_pairing_session(str(repo))

        assert "pairing_code" in result
        assert len(result["pairing_code"]) == 6
        assert result["pairing_code"].isdigit()
        assert "expires_at" in result
    finally:
        import shutil

        shutil.rmtree(repo)


def test_confirm_pairing_success():
    """Test successful pairing confirmation."""
    repo = _make_repo()
    try:
        # Create pairing session
        session = create_pairing_session(str(repo))
        pairing_code = session["pairing_code"]

        # Confirm pairing
        result = confirm_pairing(
            str(repo),
            pairing_code,
            "test-device-001",
            "Test Phone",
            "TestBrowser/1.0",
        )

        assert result["ok"] is True
        assert result["device_id"] == "test-device-001"
        assert "device_token" in result
        assert len(result["device_token"]) > 20  # token_urlsafe(32) is ~43 chars

        # Verify token is not stored in plain text
        conn = db_connect(repo)
        row = conn.execute(
            "SELECT token_hash FROM paired_devices WHERE device_id = ?",
            ("test-device-001",),
        ).fetchone()
        assert row is not None
        token_hash = row["token_hash"]
        # Verify hash matches
        expected_hash = hashlib.sha256(result["device_token"].encode()).hexdigest()
        assert token_hash == expected_hash
        conn.close()
    finally:
        import shutil

        shutil.rmtree(repo)


def test_database_does_not_store_plain_token():
    """Test that database only stores token hash, not plain token."""
    repo = _make_repo()
    try:
        session = create_pairing_session(str(repo))
        result = confirm_pairing(str(repo), session["pairing_code"], "device-xyz")

        conn = db_connect(repo)
        # Check all columns in paired_devices
        row = conn.execute(
            "SELECT * FROM paired_devices WHERE device_id = ?",
            ("device-xyz",),
        ).fetchone()
        assert row is not None

        # Verify no column contains the plain token
        row_dict = dict(row)
        plain_token = result["device_token"]
        for key, value in row_dict.items():
            if value:
                assert plain_token not in str(value)

        conn.close()
    finally:
        import shutil

        shutil.rmtree(repo)


def test_pairing_code_used_once():
    """Test that pairing code can only be used once."""
    repo = _make_repo()
    try:
        session = create_pairing_session(str(repo))
        pairing_code = session["pairing_code"]

        # First use - success
        result1 = confirm_pairing(str(repo), pairing_code, "device-1")
        assert result1["ok"] is True

        # Second use - failure
        result2 = confirm_pairing(str(repo), pairing_code, "device-2")
        assert result2["ok"] is False
        assert result2["error_code"] == "pairing_code_used"
    finally:
        import shutil

        shutil.rmtree(repo)


def test_pairing_code_expired():
    """Test that expired pairing code cannot be used."""
    repo = _make_repo()
    try:
        # Create session with very short expiry
        session = create_pairing_session(str(repo), expires_in_seconds=1)
        pairing_code = session["pairing_code"]

        # Wait for expiry
        time.sleep(2)

        # Try to use expired code
        result = confirm_pairing(str(repo), pairing_code, "device-late")
        assert result["ok"] is False
        assert result["error_code"] == "pairing_code_expired"
    finally:
        import shutil

        shutil.rmtree(repo)


def test_invalid_pairing_code():
    """Test that invalid pairing code is rejected."""
    repo = _make_repo()
    try:
        result = confirm_pairing(str(repo), "999999", "device-xyz")
        assert result["ok"] is False
        assert result["error_code"] == "invalid_pairing_code"
    finally:
        import shutil

        shutil.rmtree(repo)


def test_verify_device_token_success():
    """Test successful token verification."""
    repo = _make_repo()
    try:
        session = create_pairing_session(str(repo))
        result = confirm_pairing(str(repo), session["pairing_code"], "device-test")

        # Verify token
        verify_result = verify_device_token(
            str(repo), "device-test", result["device_token"]
        )
        assert verify_result["ok"] is True
        assert verify_result["device_id"] == "device-test"
    finally:
        import shutil

        shutil.rmtree(repo)


def test_verify_device_token_wrong_token():
    """Test that wrong token is rejected."""
    repo = _make_repo()
    try:
        session = create_pairing_session(str(repo))
        confirm_pairing(str(repo), session["pairing_code"], "device-test")

        # Try with wrong token
        verify_result = verify_device_token(str(repo), "device-test", "wrong-token")
        assert verify_result["ok"] is False
        assert verify_result["error_code"] == "unauthorized_device"
    finally:
        import shutil

        shutil.rmtree(repo)


def test_verify_device_token_wrong_device():
    """Test that wrong device_id is rejected."""
    repo = _make_repo()
    try:
        session = create_pairing_session(str(repo))
        result = confirm_pairing(str(repo), session["pairing_code"], "device-test")

        # Try with wrong device_id
        verify_result = verify_device_token(
            str(repo), "wrong-device", result["device_token"]
        )
        assert verify_result["ok"] is False
        assert verify_result["error_code"] == "unauthorized_device"
    finally:
        import shutil

        shutil.rmtree(repo)


def test_list_paired_devices():
    """Test listing paired devices."""
    repo = _make_repo()
    try:
        # Pair two devices
        session1 = create_pairing_session(str(repo))
        confirm_pairing(str(repo), session1["pairing_code"], "device-1", "Phone 1")

        session2 = create_pairing_session(str(repo))
        confirm_pairing(str(repo), session2["pairing_code"], "device-2", "Phone 2")

        # List devices
        devices = list_paired_devices(str(repo))
        assert len(devices) == 2

        # Check device names
        device_names = [d["device_name"] for d in devices]
        assert "Phone 1" in device_names
        assert "Phone 2" in device_names
    finally:
        import shutil

        shutil.rmtree(repo)


def test_revoke_device():
    """Test revoking a device."""
    repo = _make_repo()
    try:
        session = create_pairing_session(str(repo))
        result = confirm_pairing(str(repo), session["pairing_code"], "device-test")

        # Revoke device
        revoke_result = revoke_device(str(repo), "device-test")
        assert revoke_result["ok"] is True

        # Verify revoked device cannot access
        verify_result = verify_device_token(
            str(repo), "device-test", result["device_token"]
        )
        assert verify_result["ok"] is False
        assert verify_result["error_code"] == "device_revoked"

        # Check device list shows revoked
        devices = list_paired_devices(str(repo))
        assert len(devices) == 1
        assert devices[0]["revoked"] is True
    finally:
        import shutil

        shutil.rmtree(repo)


def test_revoke_nonexistent_device():
    """Test revoking a device that doesn't exist."""
    repo = _make_repo()
    try:
        result = revoke_device(str(repo), "nonexistent-device")
        assert result["ok"] is False
        assert result["error_code"] == "device_not_found"
    finally:
        import shutil

        shutil.rmtree(repo)


def test_is_localhost_request():
    """Test localhost detection."""
    assert is_localhost_request("127.0.0.1") is True
    assert is_localhost_request("::1") is True
    assert is_localhost_request("localhost") is True
    assert is_localhost_request("::ffff:127.0.0.1") is True
    assert is_localhost_request("192.168.1.1") is False
    assert is_localhost_request("10.0.0.1") is False
    assert is_localhost_request(None) is False


def test_authorized_device_can_access_sync_manifest():
    """Test that authorized device can access sync manifest."""
    repo = _make_repo()
    try:
        session = create_pairing_session(str(repo))
        result = confirm_pairing(str(repo), session["pairing_code"], "device-test")

        # Verify token works
        verify_result = verify_device_token(
            str(repo), "device-test", result["device_token"]
        )
        assert verify_result["ok"] is True

        # Access sync manifest (this would be tested via API in real scenario)
        manifest = get_sync_manifest(str(repo))
        assert manifest is not None
        assert "repo_id" in manifest
    finally:
        import shutil

        shutil.rmtree(repo)


def test_cleanup_expired_pairing_sessions():
    """Test cleanup of expired pairing sessions."""
    repo = _make_repo()
    try:
        # Create session with short expiry
        create_pairing_session(str(repo), expires_in_seconds=1)

        # Wait for expiry
        time.sleep(2)

        # Cleanup
        deleted = cleanup_expired_pairing_sessions(str(repo))
        assert deleted >= 1

        # Verify session is deleted
        conn = db_connect(repo)
        count = conn.execute(
            "SELECT COUNT(*) FROM pairing_sessions WHERE used = 0"
        ).fetchone()[0]
        assert count == 0
        conn.close()
    finally:
        import shutil

        shutil.rmtree(repo)


def test_pairing_tables_created():
    """Test that pairing tables are created automatically."""
    repo = _make_repo()
    try:
        conn = db_connect(repo)
        _ensure_tables(conn)

        # Check paired_devices table
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='paired_devices'"
        ).fetchone()
        assert tables is not None

        # Check pairing_sessions table
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pairing_sessions'"
        ).fetchone()
        assert tables is not None

        conn.close()
    finally:
        import shutil

        shutil.rmtree(repo)


def test_repairing_existing_device():
    """Test that re-pairing an existing device updates its token."""
    repo = _make_repo()
    try:
        # First pairing
        session1 = create_pairing_session(str(repo))
        result1 = confirm_pairing(str(repo), session1["pairing_code"], "device-test")

        # Second pairing (same device_id)
        session2 = create_pairing_session(str(repo))
        result2 = confirm_pairing(str(repo), session2["pairing_code"], "device-test")

        assert result2["ok"] is True
        assert result2["device_token"] != result1["device_token"]  # New token

        # Old token should no longer work
        verify_old = verify_device_token(str(repo), "device-test", result1["device_token"])
        assert verify_old["ok"] is False

        # New token should work
        verify_new = verify_device_token(str(repo), "device-test", result2["device_token"])
        assert verify_new["ok"] is True
    finally:
        import shutil

        shutil.rmtree(repo)


def test_no_file_modification():
    """Test that pairing operations don't modify any files."""
    repo = _make_repo()
    try:
        # Create a test file
        test_file = repo / "library" / "test.txt"
        test_file.write_text("original content", encoding="utf-8")
        original_content = test_file.read_text(encoding="utf-8")

        # Perform pairing operations
        session = create_pairing_session(str(repo))
        result = confirm_pairing(str(repo), session["pairing_code"], "device-test")
        verify_device_token(str(repo), "device-test", result["device_token"])
        list_paired_devices(str(repo))
        revoke_device(str(repo), "device-test")

        # Verify file unchanged
        assert test_file.read_text(encoding="utf-8") == original_content
    finally:
        import shutil

        shutil.rmtree(repo)