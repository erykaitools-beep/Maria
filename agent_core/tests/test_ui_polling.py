"""Run deterministic client scheduling/vision flows without a server/browser."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_visibility_polling_and_manual_snapshot_flow():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed for the offline JavaScript contract tests")
    harness = Path(__file__).parent / "js" / "test_polling.cjs"
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
