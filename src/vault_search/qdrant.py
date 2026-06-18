"""Qdrant client with auto-start of Docker container.

The host port is derived from ``QDRANT_URL`` so the runtime stays consistent
with whatever port the guided installer (``scripts/install-mcp.sh``) wrote into
the MCP config. When the source ships the compose file (dev / ``uv run`` from a
checkout) we bring Qdrant up via ``docker compose`` on that port; otherwise we
fall back to a standalone ``docker run`` mapped to the same port.
"""

import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from vault_search.config import QDRANT_URL

# docker-compose.yml lives at the repo root: src/vault_search/qdrant.py -> ../../
_COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def _qdrant_port(default: int = 6333) -> int:
    """Host port Qdrant should be reachable on, parsed from QDRANT_URL."""
    return urlparse(QDRANT_URL).port or default


def _reachable() -> bool:
    try:
        urllib.request.urlopen(QDRANT_URL, timeout=2)
        return True
    except Exception:
        return False


def _compose_cmd() -> list[str] | None:
    """Return the available Docker Compose command, or None."""
    try:
        if subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
        ).returncode == 0:
            return ["docker", "compose"]
    except FileNotFoundError:
        return None
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    return None


def ensure_qdrant() -> None:
    """Start Qdrant via Docker if not reachable, on the port from QDRANT_URL."""
    if _reachable():
        return

    port = _qdrant_port()
    grpc_port = port + 1
    started = False

    # Prefer docker compose when the compose file ships with the source so the
    # runtime uses the same container/volume the installer set up.
    if _COMPOSE_FILE.is_file():
        cc = _compose_cmd()
        if cc:
            env = {
                **os.environ,
                "QDRANT_PORT": str(port),
                "QDRANT_GRPC_PORT": str(grpc_port),
            }
            try:
                subprocess.run(
                    [*cc, "-f", str(_COMPOSE_FILE), "up", "-d"],
                    check=True,
                    env=env,
                )
                started = True
            except (subprocess.CalledProcessError, FileNotFoundError):
                started = False

    if not started:
        # Fallback: reuse a stopped standalone container, or run a fresh one
        # mapped to the chosen port.
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
                "-p", f"{port}:6333",
                "-p", f"{grpc_port}:6334",
                "-v", "qdrant_data:/qdrant/storage",
                "--restart", "unless-stopped",
                "qdrant/qdrant:latest",
            ], check=True)

    # Wait for Qdrant to be ready
    for _ in range(30):
        if _reachable():
            return
        time.sleep(1)
    raise RuntimeError("Qdrant did not become ready in time")
