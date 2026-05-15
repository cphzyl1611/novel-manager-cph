from __future__ import annotations

import hashlib
import secrets
import string
import time
from pathlib import Path
from typing import Any

from ...db import connect as db_connect
from ...utils import now_ts


def _ensure_tables(conn: Any) -> None:
    """Ensure pairing tables exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS paired_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL UNIQUE,
            device_name TEXT,
            token_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_seen_at TEXT,
            revoked INTEGER NOT NULL DEFAULT 0,
            user_agent TEXT,
            note TEXT
        );

        CREATE TABLE IF NOT EXISTS pairing_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pairing_code TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_paired_devices_device_id ON paired_devices(device_id);
        CREATE INDEX IF NOT EXISTS idx_pairing_sessions_code ON pairing_sessions(pairing_code);
    """)
    conn.commit()


def generate_pairing_code(length: int = 6) -> str:
    """Generate a numeric pairing code."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def create_pairing_session(repo_path: str, expires_in_seconds: int = 300) -> dict[str, Any]:
    """Create a new pairing session.

    Args:
        repo_path: Path to repository
        expires_in_seconds: Code validity duration (default 5 minutes)

    Returns:
        {
            "pairing_code": "123456",
            "expires_at": "2024-01-15T10:35:00Z",
            "pair_url": "http://<ip>:8765/#pair=123456"
        }
    """
    root = Path(repo_path).expanduser().resolve()
    conn = db_connect(root)
    _ensure_tables(conn)

    pairing_code = generate_pairing_code(6)
    created_at = now_ts()
    # Calculate expiry using local time to match now_ts format
    import datetime
    expires_at_dt = datetime.datetime.now() + datetime.timedelta(seconds=expires_in_seconds)
    expires_at = expires_at_dt.strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        "INSERT INTO pairing_sessions (pairing_code, expires_at, used, created_at) VALUES (?, ?, 0, ?)",
        (pairing_code, expires_at, created_at),
    )
    conn.commit()
    conn.close()

    return {
        "pairing_code": pairing_code,
        "expires_at": expires_at,
        "pair_url": None,  # Will be set by API layer
    }


def confirm_pairing(
    repo_path: str,
    pairing_code: str,
    device_id: str,
    device_name: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Confirm pairing and generate device token.

    Args:
        repo_path: Path to repository
        pairing_code: The pairing code to use
        device_id: Unique device identifier
        device_name: Human-readable device name
        user_agent: User agent string

    Returns:
        {
            "ok": true,
            "device_id": "...",
            "device_token": "plain_token_returned_once",
            "error": null
        }
    """
    root = Path(repo_path).expanduser().resolve()
    conn = db_connect(root)
    _ensure_tables(conn)

    # Check pairing session
    row = conn.execute(
        "SELECT id, expires_at, used FROM pairing_sessions WHERE pairing_code = ?",
        (pairing_code,),
    ).fetchone()

    if row is None:
        conn.close()
        return {"ok": False, "error": "配对码不存在", "error_code": "invalid_pairing_code"}

    if row["used"]:
        conn.close()
        return {"ok": False, "error": "配对码已使用", "error_code": "pairing_code_used"}

    expires_at = row["expires_at"]
    now = now_ts()
    if expires_at and expires_at < now:
        conn.close()
        return {"ok": False, "error": "配对码已过期", "error_code": "pairing_code_expired"}

    # Mark pairing code as used
    conn.execute("UPDATE pairing_sessions SET used = 1 WHERE id = ?", (row["id"],))

    # Generate token
    device_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(device_token.encode()).hexdigest()
    created_at = now_ts()

    # Check if device already exists
    existing = conn.execute(
        "SELECT id FROM paired_devices WHERE device_id = ?",
        (device_id,),
    ).fetchone()

    if existing:
        # Update existing device
        conn.execute(
            """UPDATE paired_devices
               SET token_hash = ?, device_name = ?, user_agent = ?, revoked = 0, last_seen_at = ?
               WHERE device_id = ?""",
            (token_hash, device_name, user_agent, created_at, device_id),
        )
    else:
        # Insert new device
        conn.execute(
            """INSERT INTO paired_devices
               (device_id, device_name, token_hash, created_at, last_seen_at, revoked, user_agent)
               VALUES (?, ?, ?, ?, ?, 0, ?)""",
            (device_id, device_name, token_hash, created_at, created_at, user_agent),
        )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "device_id": device_id,
        "device_token": device_token,  # Plain token, only returned once
    }


def verify_device_token(repo_path: str, device_id: str, device_token: str) -> dict[str, Any]:
    """Verify a device token.

    Args:
        repo_path: Path to repository
        device_id: Device identifier
        device_token: Plain token to verify

    Returns:
        {
            "ok": true,
            "device_id": "...",
            "revoked": false
        }
    """
    root = Path(repo_path).expanduser().resolve()
    conn = db_connect(root)
    _ensure_tables(conn)

    token_hash = hashlib.sha256(device_token.encode()).hexdigest()

    row = conn.execute(
        "SELECT id, revoked FROM paired_devices WHERE device_id = ? AND token_hash = ?",
        (device_id, token_hash),
    ).fetchone()

    if row is None:
        conn.close()
        return {"ok": False, "error": "设备未授权", "error_code": "unauthorized_device"}

    if row["revoked"]:
        conn.close()
        return {"ok": False, "error": "设备已被撤销", "error_code": "device_revoked"}

    # Update last_seen_at
    conn.execute(
        "UPDATE paired_devices SET last_seen_at = ? WHERE device_id = ?",
        (now_ts(), device_id),
    )
    conn.commit()
    conn.close()

    return {"ok": True, "device_id": device_id, "revoked": False}


def list_paired_devices(repo_path: str) -> list[dict[str, Any]]:
    """List all paired devices.

    Args:
        repo_path: Path to repository

    Returns:
        List of device records
    """
    root = Path(repo_path).expanduser().resolve()
    conn = db_connect(root)
    _ensure_tables(conn)

    rows = conn.execute(
        """SELECT device_id, device_name, created_at, last_seen_at, revoked, user_agent, note
           FROM paired_devices
           ORDER BY created_at DESC"""
    ).fetchall()

    devices = []
    for row in rows:
        devices.append({
            "device_id": row["device_id"],
            "device_name": row["device_name"],
            "created_at": row["created_at"],
            "last_seen_at": row["last_seen_at"],
            "revoked": bool(row["revoked"]),
            "user_agent": row["user_agent"],
            "note": row["note"],
        })

    conn.close()
    return devices


def revoke_device(repo_path: str, device_id: str) -> dict[str, Any]:
    """Revoke a device's authorization.

    Args:
        repo_path: Path to repository
        device_id: Device to revoke

    Returns:
        {"ok": true, "device_id": "..."}
    """
    root = Path(repo_path).expanduser().resolve()
    conn = db_connect(root)
    _ensure_tables(conn)

    row = conn.execute(
        "SELECT id FROM paired_devices WHERE device_id = ?",
        (device_id,),
    ).fetchone()

    if row is None:
        conn.close()
        return {"ok": False, "error": "设备不存在", "error_code": "device_not_found"}

    conn.execute(
        "UPDATE paired_devices SET revoked = 1 WHERE device_id = ?",
        (device_id,),
    )
    conn.commit()
    conn.close()

    return {"ok": True, "device_id": device_id}


def is_localhost_request(client_host: str | None) -> bool:
    """Check if request is from localhost.

    Args:
        client_host: Client IP address or host

    Returns:
        True if request is from localhost
    """
    if not client_host:
        return False

    localhost_patterns = ["127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"]
    return client_host in localhost_patterns or client_host.startswith("::ffff:127.")


def cleanup_expired_pairing_sessions(repo_path: str) -> int:
    """Clean up expired pairing sessions.

    Args:
        repo_path: Path to repository

    Returns:
        Number of sessions cleaned up
    """
    root = Path(repo_path).expanduser().resolve()
    conn = db_connect(root)
    _ensure_tables(conn)

    now = now_ts()
    cursor = conn.execute("DELETE FROM pairing_sessions WHERE expires_at < ? AND used = 0", (now,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()

    return deleted
