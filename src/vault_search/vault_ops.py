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
# Vault map
# ---------------------------------------------------------------------------


def get_vault_map(max_depth: int = 3) -> dict:
    """Build a tree representation of the vault directory structure.

    Args:
        max_depth: Maximum directory depth to traverse (default 3). 0 = root only.

    Returns:
        Nested dict with: name, path, files (count), extensions (set), children (list).
    """
    vault = VAULT_PATH.resolve()

    def _build_tree(dirpath: Path, current_depth: int) -> dict:
        name = dirpath.name or "/"
        rel = relative_to_vault(VAULT_PATH, dirpath) if dirpath != vault else ""

        files = []
        children = []

        try:
            entries = sorted(dirpath.iterdir())
        except PermissionError:
            entries = []

        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_file():
                files.append(entry.name)
            elif entry.is_dir() and current_depth < max_depth:
                children.append(_build_tree(entry, current_depth + 1))

        extensions = list(set(Path(f).suffix for f in files if Path(f).suffix))

        return {
            "name": name,
            "path": rel,
            "files": len(files),
            "extensions": extensions,
            "children": children,
        }

    return _build_tree(vault, 0)


def format_vault_tree(tree: dict, indent: int = 0) -> str:
    """Format a vault map tree as a readable markdown string.

    Args:
        tree: Tree dict from get_vault_map.
        indent: Current indentation level.

    Returns:
        Formatted tree string.
    """
    prefix = "  " * indent
    name = tree["name"] + "/" if tree["children"] or indent == 0 else tree["name"]
    ext_info = ", ".join(sorted(tree["extensions"])) if tree["extensions"] else ""
    file_info = f"{tree['files']} files" if tree["files"] else "empty"
    if ext_info:
        file_info += f" ({ext_info})"

    lines = [f"{prefix}{name} — {file_info}"]
    for child in tree["children"]:
        lines.append(format_vault_tree(child, indent + 1))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Frontmatter schema discovery
# ---------------------------------------------------------------------------


def get_frontmatter_schema() -> list[dict]:
    """Scan all .md files and report frontmatter field usage.

    Returns:
        List of dicts sorted by frequency, each with:
        field, type, count, total_files, examples (up to 3).
    """
    vault = VAULT_PATH.resolve()
    field_stats: dict[str, dict] = {}
    total_files = 0

    for md_file in sorted(vault.rglob("*.md")):
        try:
            post = frontmatter.load(str(md_file))
        except Exception:
            continue
        total_files += 1

        for key, value in post.metadata.items():
            if key not in field_stats:
                field_stats[key] = {"types": [], "count": 0, "examples": []}

            field_stats[key]["count"] += 1
            field_stats[key]["types"].append(_detect_type(value))

            if len(field_stats[key]["examples"]) < 3:
                example = str(value)
                if len(example) > 50:
                    example = example[:50] + "..."
                if example not in field_stats[key]["examples"]:
                    field_stats[key]["examples"].append(example)

    result = []
    for field, stats in field_stats.items():
        # Most common type
        type_counts: dict[str, int] = {}
        for t in stats["types"]:
            type_counts[t] = type_counts.get(t, 0) + 1
        most_common_type = max(type_counts, key=type_counts.get) if type_counts else "str"

        result.append({
            "field": field,
            "type": most_common_type,
            "count": stats["count"],
            "total_files": total_files,
            "examples": stats["examples"],
        })

    result.sort(key=lambda x: x["count"], reverse=True)
    return result


def _detect_type(value) -> str:
    """Detect the type of a frontmatter value."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if hasattr(value, "isoformat"):
        return "date"
    return "str"


# ---------------------------------------------------------------------------
# Batch operations
# ---------------------------------------------------------------------------


def batch_update_frontmatter(
    filter_type: str,
    filter_value: str,
    field: str,
    value: str,
    operation: str = "set",
    confirm: bool = False,
) -> dict:
    """Update a frontmatter field across multiple files matching a filter.

    Args:
        filter_type: "project", "tag", or "glob".
        filter_value: Project name, tag name, or glob pattern.
        field: Frontmatter field to modify.
        value: Value to set/append/remove (parsed as YAML).
        operation: "set", "append", or "remove".
        confirm: If False, return preview. If True, apply changes.

    Returns:
        Dict with affected_files, count, preview, applied.
    """
    if filter_type not in ("project", "tag", "glob"):
        raise ValueError(f"Invalid filter_type: {filter_type}. Must be 'project', 'tag', or 'glob'.")
    if operation not in ("set", "append", "remove"):
        raise ValueError(f"Invalid operation: {operation}. Must be 'set', 'append', or 'remove'.")

    try:
        parsed_value = yaml.safe_load(value)
    except yaml.YAMLError:
        parsed_value = value

    vault = VAULT_PATH.resolve()
    matching_files = _find_matching_files(vault, filter_type, filter_value)

    affected = []
    for md_file in matching_files:
        rel = relative_to_vault(VAULT_PATH, md_file)
        affected.append(rel)

    if not confirm:
        return {
            "affected_files": affected,
            "count": len(affected),
            "preview": True,
            "applied": False,
        }

    # Apply changes
    for md_file in matching_files:
        post = frontmatter.load(str(md_file))

        if operation == "set":
            post.metadata[field] = parsed_value
        elif operation == "append":
            current = post.metadata.get(field)
            if isinstance(current, list):
                current.append(parsed_value)
            elif current is None:
                post.metadata[field] = [parsed_value] if not isinstance(parsed_value, list) else parsed_value
            else:
                post.metadata[field] = [current, parsed_value]
        elif operation == "remove":
            current = post.metadata.get(field)
            if isinstance(current, list) and parsed_value in current:
                current.remove(parsed_value)
            elif current == parsed_value:
                del post.metadata[field]

        md_file.write_text(frontmatter.dumps(post), encoding="utf-8")
        _trigger_reindex(relative_to_vault(VAULT_PATH, md_file))

    return {
        "affected_files": affected,
        "count": len(affected),
        "preview": False,
        "applied": True,
    }


def batch_rename_tag(
    old_tag: str,
    new_tag: str,
    confirm: bool = False,
) -> dict:
    """Rename a tag across all vault files (frontmatter and inline).

    Args:
        old_tag: Tag to find (without # prefix).
        new_tag: Replacement tag (without # prefix).
        confirm: If False, preview only. If True, apply.

    Returns:
        Dict with affected_files, count, frontmatter_changes, inline_changes, preview, applied.
    """
    vault = VAULT_PATH.resolve()
    affected = []
    fm_changes = 0
    inline_changes = 0
    inline_pattern = re.compile(r'(?<=\s)#' + re.escape(old_tag) + r'(?=\s|$)')

    for md_file in sorted(vault.rglob("*.md")):
        try:
            post = frontmatter.load(str(md_file))
        except Exception:
            continue

        file_changed = False
        tags = post.metadata.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
            post.metadata["tags"] = tags

        # Check frontmatter
        if old_tag in tags:
            file_changed = True
            fm_changes += 1

        # Check inline
        inline_count = len(inline_pattern.findall(post.content))
        if inline_count > 0:
            file_changed = True
            inline_changes += inline_count

        if file_changed:
            affected.append(relative_to_vault(VAULT_PATH, md_file))

    if not confirm:
        return {
            "affected_files": affected,
            "count": len(affected),
            "frontmatter_changes": fm_changes,
            "inline_changes": inline_changes,
            "preview": True,
            "applied": False,
        }

    # Apply changes
    for md_file in sorted(vault.rglob("*.md")):
        try:
            post = frontmatter.load(str(md_file))
        except Exception:
            continue

        changed = False
        tags = post.metadata.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
            post.metadata["tags"] = tags

        if old_tag in tags:
            idx = tags.index(old_tag)
            tags[idx] = new_tag
            changed = True

        new_content, count = inline_pattern.subn(f"#{new_tag}", post.content)
        if count > 0:
            post.content = new_content
            changed = True

        if changed:
            md_file.write_text(frontmatter.dumps(post), encoding="utf-8")
            _trigger_reindex(relative_to_vault(VAULT_PATH, md_file))

    return {
        "affected_files": affected,
        "count": len(affected),
        "frontmatter_changes": fm_changes,
        "inline_changes": inline_changes,
        "preview": False,
        "applied": True,
    }


def _find_matching_files(vault: Path, filter_type: str, filter_value: str) -> list[Path]:
    """Find files matching a filter criterion."""
    matching = []

    if filter_type == "glob":
        for path in sorted(vault.glob(filter_value)):
            if path.is_file() and path.suffix == ".md":
                matching.append(path)
    else:
        for md_file in sorted(vault.rglob("*.md")):
            if filter_type == "project":
                try:
                    rel = md_file.relative_to(vault)
                    project = rel.parts[0] if rel.parts else ""
                except ValueError:
                    continue
                if project == filter_value:
                    matching.append(md_file)
            elif filter_type == "tag":
                try:
                    post = frontmatter.load(str(md_file))
                    tags = post.metadata.get("tags", [])
                    if isinstance(tags, str):
                        tags = [tags]
                    if filter_value in tags:
                        matching.append(md_file)
                except Exception:
                    continue

    return matching


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
