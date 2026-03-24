"""Qdrant client with auto-start of Docker container."""

import subprocess
import time
import urllib.request

from vault_search.config import QDRANT_URL


def ensure_qdrant() -> None:
    """Start Qdrant Docker container if not reachable."""
    try:
        urllib.request.urlopen(QDRANT_URL, timeout=2)
        return
    except Exception:
        pass

    # Check if container exists but is stopped
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", "qdrant"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        if result.stdout.strip() == "false":
            subprocess.run(["docker", "start", "qdrant"], check=True)
    else:
        subprocess.run([
            "docker", "run", "-d",
            "--name", "qdrant",
            "-p", "6333:6333",
            "-p", "6334:6334",
            "-v", "qdrant_data:/qdrant/storage",
            "--restart", "unless-stopped",
            "qdrant/qdrant:latest",
        ], check=True)

    # Wait for Qdrant to be ready
    for _ in range(15):
        try:
            urllib.request.urlopen(QDRANT_URL, timeout=2)
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("Qdrant did not become ready in time")
