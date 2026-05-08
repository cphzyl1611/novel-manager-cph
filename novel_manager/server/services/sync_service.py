from __future__ import annotations

import platform
from pathlib import Path
from typing import Any


def get_sync_status(repo_path: str) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    ops_count = 0
    last_op_time = None

    ops_log = root / "logs" / "operations.log"
    if ops_log.exists():
        try:
            lines = ops_log.read_text(encoding="utf-8").strip().splitlines()
            ops_count = len([line for line in lines if line.strip()])
            if ops_count > 0 and len(lines[-1]) >= 19:
                last_op_time = lines[-1][:19]
        except OSError:
            pass

    return {
        "server_device_id": f"desktop-{platform.node() or 'unknown'}",
        "repo_revision": ops_count,
        "connected_clients": 0,
        "last_operation_time": last_op_time,
    }
