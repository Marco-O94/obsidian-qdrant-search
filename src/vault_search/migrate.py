"""Vault migration: upgrade existing vaults to the LLM Wiki pattern (v0.4.0+)."""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

logger = logging.getLogger(__name__)

from vault_search.config import LOG_FILE, VAULT_PATH
from vault_search.path_utils import relative_to_vault

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

REQUIRED_FIELDS = ("project", "type", "status", "tags", "created", "updated")
WIKI_DIRS = ("raw", "wiki")


def _classify_file(file_path: Path, vault: Path) -> str:
    """Classify a file as 'wiki', 'raw', or 'unknown'.

    Heuristic only — used for advisory reporting, not for moving files.
    """
    rel = file_path.relative_to(vault)
    first_dir = rel.parts[0] if len(rel.parts) > 1 else ""

    if first_dir == "raw":
        return "raw"
    if first_dir == "wiki":
        return "wiki"

    try:
        post = frontmatter.load(str(file_path))
    except Exception:
        return "unknown"

    if post.metadata.get("type"):
        return "wiki"

    if WIKILINK_RE.search(post.content):
        return "wiki"

    if not post.metadata:
        return "raw"

    return "unknown"


def _check_directory_structure(vault: Path) -> list[dict]:
    """Check whether raw/ and wiki/ directories exist."""
    results = []
    for dirname in WIKI_DIRS:
        dirpath = vault / dirname
        results.append({
            "type": "create_dir",
            "path": dirname + "/",
            "exists": dirpath.is_dir(),
        })
    return results


def _check_log_file(vault: Path) -> dict | None:
    """Check whether the operation log file exists."""
    log_path = vault / LOG_FILE
    if log_path.exists():
        return None
    return {"type": "create_log", "path": LOG_FILE, "exists": False}


def _find_vault_md_files(vault: Path) -> list[Path]:
    """Find all .md files in the vault, excluding hidden dirs and .venv."""
    files = []
    for md_file in sorted(vault.rglob("*.md")):
        rel = md_file.relative_to(vault)
        # Skip hidden directories and .venv
        if any(part.startswith(".") for part in rel.parts):
            continue
        files.append(md_file)
    return files


def _check_frontmatter(vault: Path) -> list[dict]:
    """Scan files for missing frontmatter fields.

    Excludes files in raw/, hidden directories, and the log file.
    """
    changes = []

    for md_file in _find_vault_md_files(vault):
        rel_path = str(md_file.relative_to(vault))

        # Skip raw sources and log file
        if rel_path.startswith("raw/") or rel_path == LOG_FILE:
            continue

        try:
            post = frontmatter.load(str(md_file))
        except Exception:
            continue

        missing = []
        defaults: dict = {}

        for field in REQUIRED_FIELDS:
            if field not in post.metadata:
                missing.append(field)

        if not missing:
            continue

        # Build defaults for missing fields
        stat = md_file.stat()

        if "project" in missing:
            rel = md_file.relative_to(vault)
            defaults["project"] = rel.parts[0] if len(rel.parts) > 1 else "unknown"

        if "type" in missing:
            defaults["type"] = "guide"

        if "status" in missing:
            defaults["status"] = "draft"

        if "tags" in missing:
            defaults["tags"] = []

        if "created" in missing:
            defaults["created"] = datetime.fromtimestamp(
                stat.st_ctime, tz=timezone.utc
            ).strftime("%Y-%m-%d")

        if "updated" in missing:
            defaults["updated"] = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).strftime("%Y-%m-%d")

        changes.append({
            "type": "add_frontmatter",
            "path": rel_path,
            "missing_fields": missing,
            "defaults": defaults,
            "classification": _classify_file(md_file, vault),
        })

    return changes


def _apply_directory_structure(vault: Path, changes: list[dict]) -> int:
    """Create directories that do not exist."""
    created = 0
    for change in changes:
        if change["exists"]:
            continue
        dirpath = vault / change["path"].rstrip("/")
        dirpath.mkdir(parents=True, exist_ok=True)
        created += 1
    return created


def _apply_log_file(vault: Path, log_change: dict | None) -> bool:
    """Create the operation log file if it does not exist."""
    if log_change is None:
        return False

    log_path = vault / LOG_FILE
    header = "# Operation Log\n\nChronological record of vault operations.\n"
    log_path.write_text(header, encoding="utf-8")
    return True


def _apply_frontmatter(vault: Path, changes: list[dict]) -> int:
    """Add missing frontmatter fields without overwriting existing values."""
    modified = 0

    for change in changes:
        abs_path = vault / change["path"]
        try:
            post = frontmatter.load(str(abs_path))
        except Exception as exc:
            logger.warning("Failed to parse %s during migration: %s", abs_path, exc)
            continue

        changed = False
        for field, value in change["defaults"].items():
            if field not in post.metadata:
                post.metadata[field] = value
                changed = True

        if changed:
            abs_path.write_text(frontmatter.dumps(post), encoding="utf-8")
            modified += 1

    return modified


def migrate_vault(confirm: bool = False) -> dict:
    """Migrate an existing vault to the LLM Wiki pattern.

    Args:
        confirm: If False, return preview of what would change.
                 If True, apply changes.

    Returns:
        Dict with directories, log_file, frontmatter_changes, summary,
        preview (bool), and applied (bool).
    """
    vault = VAULT_PATH.resolve()

    # Analyze
    dir_changes = _check_directory_structure(vault)
    log_change = _check_log_file(vault)
    fm_changes = _check_frontmatter(vault)

    dirs_to_create = sum(1 for d in dir_changes if not d["exists"])
    md_files = _find_vault_md_files(vault)

    result = {
        "directories": dir_changes,
        "log_file": {
            "path": LOG_FILE,
            "exists": log_change is None,
            "action": "skip" if log_change is None else "create",
        },
        "frontmatter_changes": fm_changes,
        "summary": {
            "total_files": len(md_files),
            "files_needing_frontmatter": len(fm_changes),
            "dirs_to_create": dirs_to_create,
            "log_to_create": log_change is not None,
        },
        "preview": not confirm,
        "applied": False,
    }

    if not confirm:
        return result

    # Apply
    _apply_directory_structure(vault, dir_changes)
    _apply_log_file(vault, log_change)
    files_modified = _apply_frontmatter(vault, fm_changes)

    # Update action fields
    for d in result["directories"]:
        d["action"] = "skip" if d["exists"] else "create"

    result["applied"] = True
    result["preview"] = False

    # Log the migration
    from vault_search.vault_ops import log_operation

    pages = [c["path"] for c in fm_changes]
    log_operation(
        operation_type="maintenance",
        title="Vault migration to LLM Wiki pattern",
        summary=(
            f"Created {dirs_to_create} directories, "
            f"added frontmatter to {files_modified} files"
        ),
        pages_touched=pages,
    )

    # Trigger reindex for modified files
    from vault_search.vault_ops import _trigger_reindex

    for change in fm_changes:
        _trigger_reindex(change["path"])

    return result
