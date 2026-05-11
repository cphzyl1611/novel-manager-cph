import shutil
import subprocess
from pathlib import Path
import pytest


def test_app_js_syntax_with_node():
    """Verify app.js has no syntax errors using node --check."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    app_js = Path(__file__).parent.parent / "novel_manager" / "server" / "static" / "app.js"
    result = subprocess.run([node, "--check", str(app_js)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
