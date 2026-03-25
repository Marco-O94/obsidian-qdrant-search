"""Vault filesystem operations: CRUD, search, tags, and metadata."""

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

import frontmatter
import yaml

from vault_search.config import VAULT_PATH
from vault_search.path_utils import relative_to_vault, resolve_vault_path


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


def get_file_contents(filepath: str) -> str:
    """Read and return the raw content of a vault file.

    Args:
        filepath: Path relative to vault root.

    Returns:
        File content as string.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the path escapes the vault.
    """
    target = resolve_vault_path(VAULT_PATH, filepath)
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {filepath}")
    return target.read_text(encoding="utf-8")


def get_file_metadata(filepath: str) -> dict:
    """Return frontmatter metadata and file stats.

    Args:
        filepath: Path relative to vault root.

    Returns:
        Dict with keys: path, frontmatter, tags, stat (size, modified, created).
    """
    target = resolve_vault_path(VAULT_PATH, filepath)
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {filepath}")

    post = frontmatter.load(str(target))
    stat = target.stat()

    tags = post.metadata.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    return {
        "path": filepath,
        "frontmatter": dict(post.metadata),
        "tags": tags,
        "stat": {
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "created": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
        },
    }


def list_files_in_dir(dirpath: str = "") -> list[str]:
    """List files and subdirectories in a vault directory (non-recursive).

    Args:
        dirpath: Relative directory path. Empty string for vault root.

    Returns:
        Sorted list of names. Directories are suffixed with '/'.
    """
    target = resolve_vault_path(VAULT_PATH, dirpath)
    if not target.is_dir():
        raise NotADirectoryError(f"Not a directory: {dirpath}")

    entries = []
    for entry in sorted(target.iterdir()):
        rel = relative_to_vault(VAULT_PATH, entry)
        if entry.is_dir():
            entries.append(rel + "/")
        else:
            entries.append(rel)
    return entries


def list_files_in_vault() -> list[str]:
    """List top-level files and directories in the vault root."""
    return list_files_in_dir("")


def simple_search(query: str, context_length: int = 100) -> list[dict]:
    """Case-insensitive substring search across all .md files.

    Args:
        query: Search string.
        context_length: Characters of context around each match.

    Returns:
        List of dicts with filepath, match, context. Capped at 50 results.
    """
    vault = VAULT_PATH.resolve()
    results = []
    query_lower = query.lower()

    for md_file in sorted(vault.rglob("*.md")):
        if len(results) >= 50:
            break

        try:
            content = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        idx = content.lower().find(query_lower)
        if idx == -1:
            continue

        start = max(0, idx - context_length)
        end = min(len(content), idx + len(query) + context_length)
        context = content[start:end]

        results.append({
            "filepath": relative_to_vault(VAULT_PATH, md_file),
            "match": content[idx : idx + len(query)],
            "context": context,
        })

    return results


def get_recent_changes(days: int = 14, limit: int = 10) -> list[dict]:
    """Return recently modified files sorted by modification time.

    Args:
        days: Only include files modified within this many days.
        limit: Maximum number of results.

    Returns:
        List of dicts with filepath, modified (ISO), size.
    """
    vault = VAULT_PATH.resolve()
    cutoff = datetime.now(tz=timezone.utc).timestamp() - days * 86400
    files = []

    for path in vault.rglob("*.md"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime >= cutoff:
            files.append((path, stat))

    files.sort(key=lambda x: x[1].st_mtime, reverse=True)

    return [
        {
            "filepath": relative_to_vault(VAULT_PATH, path),
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "size": stat.st_size,
        }
        for path, stat in files[:limit]
    ]


def list_tags() -> dict[str, int]:
    """Scan all .md files for tags (frontmatter + inline #tag).

    Returns:
        Dict mapping tag name to occurrence count, sorted by count descending.
    """
    vault = VAULT_PATH.resolve()
    tag_counts: dict[str, int] = {}
    inline_tag_re = re.compile(r"(?:^|\s)#([a-zA-Z][\w/-]*)", re.MULTILINE)

    for md_file in vault.rglob("*.md"):
        try:
            post = frontmatter.load(str(md_file))
        except Exception:
            continue

        # Frontmatter tags
        fm_tags = post.metadata.get("tags", [])
        if isinstance(fm_tags, str):
            fm_tags = [fm_tags]
        for tag in fm_tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # Inline tags (skip headings: lines starting with # followed by space)
        for line in post.content.split("\n"):
            stripped = line.strip()
            if re.match(r"^#{1,6}\s", stripped):
                continue
            for match in inline_tag_re.finditer(line):
                tag = match.group(1)
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

    return dict(sorted(tag_counts.items(), key=lambda x: x[1], reverse=True))


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


def create_or_update_file(filepath: str, content: str) -> dict:
    """Create or overwrite a file in the vault.

    Args:
        filepath: Path relative to vault root.
        content: Full file content.

    Returns:
        Dict with path, created (bool), size.
    """
    target = resolve_vault_path(VAULT_PATH, filepath)
    created = not target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    _trigger_reindex(filepath)
    return {"path": filepath, "created": created, "size": len(content.encode("utf-8"))}


def append_content(filepath: str, content: str) -> dict:
    """Append content to a file (create if it doesn't exist).

    Args:
        filepath: Path relative to vault root.
        content: Content to append.

    Returns:
        Dict with path, appended_bytes.
    """
    target = resolve_vault_path(VAULT_PATH, filepath)
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        existing = target.read_text(encoding="utf-8")
        separator = "" if existing.endswith("\n") or existing == "" else "\n"
        target.write_text(existing + separator + content, encoding="utf-8")
    else:
        target.write_text(content, encoding="utf-8")

    _trigger_reindex(filepath)
    return {"path": filepath, "appended_bytes": len(content)}


def patch_content(
    filepath: str,
    operation: str,
    target_type: str,
    target: str,
    content: str,
) -> dict:
    """Targeted modification of a file section.

    Args:
        filepath: Path relative to vault root.
        operation: "append", "prepend", or "replace".
        target_type: "heading" or "frontmatter".
        target: Heading text (e.g. "## Setup" or "Setup/Installation") or frontmatter field name.
        content: Content to insert/replace.

    Returns:
        Dict with path, operation, target_type, target, success.

    Raises:
        ValueError: On invalid operation/target_type or if target not found.
        FileNotFoundError: If the file does not exist.
    """
    if operation not in ("append", "prepend", "replace"):
        raise ValueError(f"Invalid operation: {operation}. Must be 'append', 'prepend', or 'replace'.")
    if target_type not in ("heading", "frontmatter"):
        raise ValueError(f"Invalid target_type: {target_type}. Must be 'heading' or 'frontmatter'.")

    abs_path = resolve_vault_path(VAULT_PATH, filepath)
    if not abs_path.is_file():
        raise FileNotFoundError(f"File not found: {filepath}")

    if target_type == "heading":
        _patch_heading(abs_path, operation, target, content)
    else:
        _patch_frontmatter(abs_path, operation, target, content)

    _trigger_reindex(filepath)
    return {
        "path": filepath,
        "operation": operation,
        "target_type": target_type,
        "target": target,
        "success": True,
    }


def delete_file(filepath: str, confirm: bool = False) -> dict:
    """Delete a file from the vault.

    Args:
        filepath: Path relative to vault root.
        confirm: Must be True to actually delete. Safety guard.

    Returns:
        Dict with path, deleted (bool).

    Raises:
        ValueError: If confirm is not True.
        FileNotFoundError: If the file does not exist.
    """
    if not confirm:
        raise ValueError("Set confirm=True to delete the file. This is a safety guard.")

    target = resolve_vault_path(VAULT_PATH, filepath)
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {filepath}")

    target.unlink()
    _trigger_reindex(filepath, deleted=True)
    return {"path": filepath, "deleted": True}


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------


def _find_heading_range(lines: list[str], target: str) -> tuple[int, int]:
    """Find the line range for content under a heading.

    Supports nested paths like "Setup/Installation" where "Setup" is an H2
    and "Installation" is an H3 under it.

    Args:
        lines: File lines.
        target: Heading text or nested path separated by '/'.

    Returns:
        (start, end) — start is the line after the heading,
        end is the line before the next heading of same/higher level (or EOF).

    Raises:
        ValueError: If the heading is not found.
    """
    segments = [s.strip() for s in target.split("/")]

    search_start = 0
    search_end = len(lines)

    for i, segment in enumerate(segments):
        found = False
        for line_idx in range(search_start, search_end):
            line = lines[line_idx].strip()
            if not line.startswith("#"):
                continue

            # Parse heading: count '#' chars
            hashes = 0
            for ch in line:
                if ch == "#":
                    hashes += 1
                else:
                    break

            heading_text = line[hashes:].strip()
            if heading_text.lower() == segment.lower():
                heading_level = hashes
                # Content starts after the heading line
                content_start = line_idx + 1

                # Find where this heading's content ends
                content_end = search_end
                for j in range(content_start, search_end):
                    next_line = lines[j].strip()
                    if next_line.startswith("#"):
                        next_hashes = 0
                        for ch in next_line:
                            if ch == "#":
                                next_hashes += 1
                            else:
                                break
                        if next_hashes <= heading_level:
                            content_end = j
                            break

                if i < len(segments) - 1:
                    # Narrow the search window for the next segment
                    search_start = content_start
                    search_end = content_end
                else:
                    return (content_start, content_end)

                found = True
                break

        if not found:
            raise ValueError(f"Heading not found: '{segment}' (in path '{target}')")

    # Should not reach here
    raise ValueError(f"Heading not found: '{target}'")


def _patch_heading(abs_path: Path, operation: str, target: str, content: str) -> None:
    """Apply a patch operation targeting a heading."""
    text = abs_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    start, end = _find_heading_range(lines, target)

    content_lines = content.split("\n")

    if operation == "replace":
        new_lines = lines[:start] + content_lines + lines[end:]
    elif operation == "append":
        # Insert before the end of the section
        # Remove trailing empty lines in the section for clean append
        insert_at = end
        new_lines = lines[:insert_at] + content_lines + lines[insert_at:]
    elif operation == "prepend":
        new_lines = lines[:start] + content_lines + lines[start:]
    else:
        raise ValueError(f"Invalid operation: {operation}")

    abs_path.write_text("\n".join(new_lines), encoding="utf-8")


def _patch_frontmatter(abs_path: Path, operation: str, target: str, content: str) -> None:
    """Apply a patch operation targeting a frontmatter field."""
    post = frontmatter.load(str(abs_path))

    current = post.metadata.get(target)

    # Try to parse content as YAML for structured values
    try:
        parsed_content = yaml.safe_load(content)
    except yaml.YAMLError:
        parsed_content = content

    if operation == "replace":
        post.metadata[target] = parsed_content
    elif operation == "append":
        if isinstance(current, list):
            if isinstance(parsed_content, list):
                current.extend(parsed_content)
            else:
                current.append(parsed_content)
        elif isinstance(current, str):
            post.metadata[target] = current + content
        elif current is None:
            post.metadata[target] = parsed_content
        else:
            post.metadata[target] = str(current) + content
    elif operation == "prepend":
        if isinstance(current, list):
            if isinstance(parsed_content, list):
                post.metadata[target] = parsed_content + current
            else:
                current.insert(0, parsed_content)
        elif isinstance(current, str):
            post.metadata[target] = content + current
        elif current is None:
            post.metadata[target] = parsed_content
        else:
            post.metadata[target] = content + str(current)

    abs_path.write_text(frontmatter.dumps(post), encoding="utf-8")


# ---------------------------------------------------------------------------
# Auto-reindex helper
# ---------------------------------------------------------------------------


def _trigger_reindex(rel_path: str, deleted: bool = False) -> None:
    """Best-effort reindex of a single file after modification.

    Never raises — write operations must not fail due to indexing issues.
    """
    try:
        from vault_search.indexer import delete_file_points, get_client, index_single_file

        if deleted:
            client = get_client()
            delete_file_points(client, rel_path)
        else:
            index_single_file(rel_path)
    except Exception:
        logger.debug("Auto-reindex failed for %s", rel_path, exc_info=True)
