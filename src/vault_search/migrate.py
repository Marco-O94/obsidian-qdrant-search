"""Vault migration: upgrade existing vaults to the LLM Wiki pattern (v0.4.0+)."""

import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

logger = logging.getLogger(__name__)

from vault_search.config import LOG_FILE, VAULT_PATH
from vault_search.path_utils import relative_to_vault

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

REQUIRED_FIELDS = ("project", "type", "status", "tags", "created", "updated")
WIKI_DIRS = ("raw", "wiki")


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------


def _classify_file(file_path: Path, vault: Path) -> str:
    """Classify a file as 'wiki', 'raw', or 'unknown'.

    Heuristic:
    - In raw/ directory -> raw
    - In wiki/ directory -> wiki
    - Has frontmatter 'type' field -> wiki
    - Has wikilinks -> wiki
    - No frontmatter at all -> raw
    - Otherwise -> unknown
    """
    rel = file_path.relative_to(vault)
    first_dir = rel.parts[0] if len(rel.parts) > 1 else ""

    if first_dir == "raw":
        return "raw"
    if first_dir == "wiki":
        return "wiki"

    try:
        post = frontmatter.load(str(file_path))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        logger.debug("Cannot parse %s for classification: %s", file_path, exc)
        return "unknown"

    if post.metadata.get("type"):
        return "wiki"

    if WIKILINK_RE.search(post.content):
        return "wiki"

    if not post.metadata:
        return "raw"

    return "unknown"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _find_vault_md_files(vault: Path) -> list[Path]:
    """Find all .md files in the vault, excluding directories that start with '.'."""
    files = []
    for md_file in sorted(vault.rglob("*.md")):
        rel = md_file.relative_to(vault)
        if any(part.startswith(".") for part in rel.parts):
            continue
        files.append(md_file)
    return files


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


def _check_frontmatter(vault: Path, exclude_raw: bool = True) -> list[dict]:
    """Scan files for missing frontmatter fields.

    Args:
        vault: Vault root path.
        exclude_raw: If True, skip files in raw/ directory.
    """
    changes = []

    for md_file in _find_vault_md_files(vault):
        rel_path = str(md_file.relative_to(vault))

        if exclude_raw and rel_path.startswith("raw/"):
            continue
        if rel_path == LOG_FILE:
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

        stat = md_file.stat()

        if "project" in missing:
            rel = md_file.relative_to(vault)
            # For files under wiki/project/ use the second segment
            parts = rel.parts
            if len(parts) > 2 and parts[0] == "wiki":
                defaults["project"] = parts[1]
            elif len(parts) > 1:
                defaults["project"] = parts[0]
            else:
                defaults["project"] = "unknown"

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


# ---------------------------------------------------------------------------
# Assisted mode: classify, move, update wikilinks
# ---------------------------------------------------------------------------


def _plan_moves(vault: Path) -> list[dict]:
    """Plan file moves based on classification.

    Returns list of {path, classification, destination, action} dicts.
    Files already in raw/ or wiki/ are skipped.
    """
    moves = []
    for md_file in _find_vault_md_files(vault):
        rel_path = str(md_file.relative_to(vault))

        # Skip log file
        if rel_path == LOG_FILE:
            continue

        # Skip files already in the right place
        if rel_path.startswith("raw/") or rel_path.startswith("wiki/"):
            continue

        classification = _classify_file(md_file, vault)

        if classification == "raw":
            destination = "raw/" + rel_path
        elif classification == "wiki":
            destination = "wiki/" + rel_path
        else:
            destination = None  # unknown — leave in place

        moves.append({
            "path": rel_path,
            "classification": classification,
            "destination": destination,
            "action": "move" if destination else "skip",
        })

    return moves


def _apply_moves(vault: Path, moves: list[dict]) -> int:
    """Move files to their destination directories.

    Skips moves where the destination already exists to prevent data loss.
    Returns count of files moved.
    """
    moved = 0
    vacated_dirs: set[Path] = set()

    for move in moves:
        if move["action"] != "move":
            continue

        src = vault / move["path"]
        dst = vault / move["destination"]

        if not src.is_file():
            continue

        if dst.exists():
            logger.warning("Destination already exists, skipping: %s", dst)
            move["action"] = "skip"
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        vacated_dirs.add(src.parent)
        shutil.move(str(src), str(dst))
        moved += 1

    # Clean up only directories vacated by moves
    _cleanup_empty_dirs(vault, vacated_dirs)

    return moved


def _cleanup_empty_dirs(vault: Path, vacated_dirs: set[Path]) -> None:
    """Remove empty directories that were vacated by file moves, bottom-up.

    Only targets directories that contained moved files — never deletes
    pre-existing empty directories unrelated to the migration.
    """
    # Walk up from each vacated dir to vault root
    dirs_to_check = set()
    for d in vacated_dirs:
        current = d
        while current != vault and current.is_relative_to(vault):
            dirs_to_check.add(current)
            current = current.parent

    for dirpath in sorted(dirs_to_check, reverse=True):
        if not dirpath.is_dir() or dirpath == vault:
            continue
        try:
            dirpath.rmdir()  # Only removes if empty
        except OSError:
            pass


def _update_wikilinks_after_moves(vault: Path, moves: list[dict]) -> int:
    """Update path-based wikilinks across the vault to reflect file moves.

    Only updates wikilinks that use path-based references (e.g. [[notes/article]]).
    Simple filename-based links (e.g. [[article]]) are not rewritten because
    Obsidian resolves them by stem regardless of directory.

    Returns count of files updated.
    """
    # Build mapping: old_path_no_ext -> new_path_no_ext
    path_map: list[tuple[str, str]] = []
    for move in moves:
        if move["action"] != "move" or not move["destination"]:
            continue
        old_ref = str(Path(move["path"]).with_suffix(""))
        new_ref = str(Path(move["destination"]).with_suffix(""))
        path_map.append((old_ref, new_ref))

    if not path_map:
        return 0

    # Sort longest-first to avoid prefix collisions
    # e.g. "notes/abcdef" must be matched before "notes/abc"
    path_map.sort(key=lambda x: len(x[0]), reverse=True)

    # Build a single regex that matches any of the old paths inside [[ ]]
    escaped_patterns = [re.escape(old) for old, _ in path_map]
    # Match [[old_path]] or [[old_path|alias]] or [[old_path#heading]]
    combined_re = re.compile(
        r"\[\[(" + "|".join(escaped_patterns) + r")([\]#|])"
    )

    # Build lookup for replacements
    replace_map = {old: new for old, new in path_map}

    updated = 0
    for md_file in _find_vault_md_files(vault):
        try:
            content = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        def _replace(match: re.Match) -> str:
            old_path = match.group(1)
            suffix = match.group(2)
            return f"[[{replace_map[old_path]}{suffix}"

        new_content = combined_re.sub(_replace, content)

        if new_content != content:
            md_file.write_text(new_content, encoding="utf-8")
            updated += 1

    return updated


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def migrate_vault(confirm: bool = False, mode: str = "manual") -> dict:
    """Migrate an existing vault to the LLM Wiki pattern.

    Args:
        confirm: If False, return preview. If True, apply changes.
        mode: "manual" — create dirs, add frontmatter, user moves files.
              "assisted" — also classify and move files to raw/wiki dirs,
              update wikilinks after moves.

    Returns:
        Dict with migration report.
    """
    if mode not in ("manual", "assisted"):
        raise ValueError(f"Invalid mode: {mode}. Must be 'manual' or 'assisted'.")

    vault = VAULT_PATH.resolve()

    # Analyze — common to both modes
    dir_changes = _check_directory_structure(vault)
    log_change = _check_log_file(vault)
    md_files = _find_vault_md_files(vault)
    dirs_to_create = sum(1 for d in dir_changes if not d["exists"])

    # Mode-specific analysis
    file_moves: list[dict] = []
    if mode == "assisted":
        file_moves = _plan_moves(vault)

    # Frontmatter check happens AFTER moves in assisted mode (preview uses current state)
    fm_changes = _check_frontmatter(vault)

    move_count = sum(1 for m in file_moves if m["action"] == "move")
    skip_count = sum(1 for m in file_moves if m["action"] == "skip")

    result = {
        "mode": mode,
        "directories": dir_changes,
        "log_file": {
            "path": LOG_FILE,
            "exists": log_change is None,
            "action": "skip" if log_change is None else "create",
        },
        "frontmatter_changes": fm_changes,
        "file_moves": file_moves,
        "summary": {
            "total_files": len(md_files),
            "files_needing_frontmatter": len(fm_changes),
            "dirs_to_create": dirs_to_create,
            "log_to_create": log_change is not None,
            "files_to_move": move_count,
            "files_unknown": skip_count,
            "files_moved": 0,
            "links_updated": 0,
        },
        "preview": not confirm,
        "applied": False,
    }

    if not confirm:
        return result

    # Apply — step 1: create directories (needed before moves)
    _apply_directory_structure(vault, dir_changes)

    # Apply — step 2: move files (assisted mode only)
    files_moved = 0
    links_updated = 0
    if mode == "assisted" and file_moves:
        files_moved = _apply_moves(vault, file_moves)
        links_updated = _update_wikilinks_after_moves(vault, file_moves)

    # Apply — step 3: re-check frontmatter AFTER moves (paths changed)
    if mode == "assisted" and files_moved > 0:
        fm_changes = _check_frontmatter(vault)
        result["frontmatter_changes"] = fm_changes
        result["summary"]["files_needing_frontmatter"] = len(fm_changes)

    # Apply — step 4: add missing frontmatter
    _apply_log_file(vault, log_change)
    files_modified = _apply_frontmatter(vault, fm_changes)

    # Update result
    for d in result["directories"]:
        d["action"] = "skip" if d["exists"] else "create"

    result["applied"] = True
    result["preview"] = False
    result["summary"]["files_moved"] = files_moved
    result["summary"]["links_updated"] = links_updated

    # Log the migration
    from vault_search.vault_ops import log_operation

    pages = [c["path"] for c in fm_changes]
    moved_pages = [m["destination"] for m in file_moves if m["action"] == "move" and m["destination"]]
    all_touched = list(set(pages + moved_pages))

    summary_parts = []
    if dirs_to_create > 0:
        summary_parts.append(f"created {dirs_to_create} directories")
    if files_moved > 0:
        summary_parts.append(f"moved {files_moved} files")
    if links_updated > 0:
        summary_parts.append(f"updated {links_updated} files with new wikilinks")
    if files_modified > 0:
        summary_parts.append(f"added frontmatter to {files_modified} files")

    log_operation(
        operation_type="maintenance",
        title=f"Vault migration to LLM Wiki pattern ({mode} mode)",
        summary=", ".join(summary_parts) if summary_parts else "No changes needed",
        pages_touched=all_touched,
    )

    # Trigger reindex for all affected files
    from vault_search.vault_ops import _trigger_reindex

    for path in all_touched:
        _trigger_reindex(path)

    return result
