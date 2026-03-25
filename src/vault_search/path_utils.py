"""Path security utilities for vault file operations."""

from pathlib import Path


def resolve_vault_path(vault_path: Path, relative_path: str) -> Path:
    """Resolve a relative path within the vault, preventing path traversal.

    Args:
        vault_path: Absolute path to the vault root.
        relative_path: User-provided relative path (e.g. "notes/daily.md").

    Returns:
        Resolved absolute path guaranteed to be inside the vault.

    Raises:
        ValueError: If the resolved path escapes the vault directory.
    """
    vault_resolved = vault_path.resolve()
    target = (vault_resolved / relative_path).resolve()

    if not (target == vault_resolved or str(target).startswith(str(vault_resolved) + "/")):
        raise ValueError(f"Path traversal detected: '{relative_path}' resolves outside the vault.")

    return target


def relative_to_vault(vault_path: Path, absolute_path: Path) -> str:
    """Return the string path relative to the vault root.

    Args:
        vault_path: Absolute path to the vault root.
        absolute_path: Absolute path to convert.

    Returns:
        Relative path as a string with forward slashes.
    """
    return str(absolute_path.resolve().relative_to(vault_path.resolve()))
