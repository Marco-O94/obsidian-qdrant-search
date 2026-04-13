"""MCP Server for semantic search over the Obsidian vault."""

from mcp.server.fastmcp import FastMCP

from vault_search.config import (
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    QDRANT_URL,
    SIMILARITY_THRESHOLD,
    TOP_K,
)

mcp = FastMCP(
    "obsidian-qdrant-search",
    instructions=(
        "Obsidian vault management with semantic search and full CRUD. "
        "WORKFLOW: 1) Orient with get_vault_map/list_projects to understand structure, "
        "2) Search with search_vault (semantic) or simple_search (text), "
        "3) Read with get_file_contents/get_file_metadata, "
        "4) Write with create_or_update_file/append_content/patch_content, "
        "5) Navigate with get_backlinks/get_outgoing_links, "
        "6) Maintain with lint_vault for health checks, log_operation to record actions. "
        "SEARCH: search_vault (semantic), simple_search (text), get_chunk_context (expand results). "
        "READ: get_file_contents, get_file_metadata, list_files_in_dir, list_files_in_vault. "
        "WRITE: create_or_update_file, append_content, patch_content (by heading/frontmatter), delete_file. "
        "DISCOVER: list_projects, list_tags, get_recent_changes, get_vault_map, get_frontmatter_schema. "
        "GRAPH: get_backlinks, get_outgoing_links, find_broken_links, find_orphan_files. "
        "BATCH: batch_update_frontmatter, batch_rename_tag (preview with confirm=False, apply with confirm=True). "
        "LOG: log_operation (record actions), get_operation_log (read history). "
        "HEALTH: lint_vault (broken links, orphans, stale docs, missing metadata, stubs). "
        "MAINTENANCE: reindex_vault. "
        "All write ops auto-reindex. Use patch_content for surgical edits by heading. "
        "Start with get_vault_map to understand structure before writing."
    ),
)

# Lazy-loaded globals — imports deferred to avoid slow startup
_model = None
_client = None


def get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(EMBEDDING_MODEL)
    return _model


def get_client():
    global _client
    if _client is None:
        from qdrant_client import QdrantClient
        from vault_search.qdrant import ensure_qdrant
        ensure_qdrant()
        _client = QdrantClient(url=QDRANT_URL)
    return _client


@mcp.tool()
def search_vault(
    query: str,
    project: str | None = None,
    doc_type: str | None = None,
    tag: str | None = None,
    top_k: int = TOP_K,
) -> str:
    """Search the Obsidian vault documentation by semantic similarity.

    Args:
        query: Natural language search query (e.g. "How does authentication work?")
        project: Filter by project name (e.g. "core", "sentinel-ai", "internal-dashboard-next")
        doc_type: Filter by document type (e.g. "overview", "api-contract", "service-layer", "data-model")
        tag: Filter by frontmatter tag (e.g. "kubernetes", "database", "security")
        top_k: Number of results to return (default 5)

    Returns:
        Formatted search results with content, file paths, and relevance scores.
    """
    model = get_model()
    client = get_client()

    query_vector = list(model.embed([query]))[0].tolist()

    # Build filters
    from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

    must_conditions = []
    if project:
        must_conditions.append(FieldCondition(key="project", match=MatchValue(value=project)))
    if doc_type:
        must_conditions.append(FieldCondition(key="type", match=MatchValue(value=doc_type)))
    if tag:
        must_conditions.append(FieldCondition(key="tags", match=MatchAny(any=[tag])))

    query_filter = Filter(must=must_conditions) if must_conditions else None

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=query_filter,
        limit=top_k,
        with_payload=True,
    )

    if not results.points:
        return "No results found for this query."

    output_parts = []
    for i, point in enumerate(results.points, 1):
        p = point.payload
        score = point.score
        if score < SIMILARITY_THRESHOLD:
            continue

        output_parts.append(
            f"### Result {i} (score: {score:.3f})\n"
            f"**File**: `Projects/{p.get('file_path', '')}`\n"
            f"**Project**: {p.get('project', '')}\n"
            f"**Title**: {p.get('doc_title', '')}\n"
            f"**Section**: {p.get('chunk_heading', '(intro)')}\n"
            f"**Type**: {p.get('type', '')}\n\n"
            f"{p.get('chunk_content', '')}\n"
        )

    if not output_parts:
        return f"No results above similarity threshold ({SIMILARITY_THRESHOLD}). Try a broader query."

    return f"Found {len(output_parts)} results for: \"{query}\"\n\n" + "\n---\n\n".join(output_parts)


@mcp.tool()
def get_chunk_context(
    file_path: str,
    chunk_index: int,
    window: int = 1,
) -> str:
    """Get surrounding chunks for context expansion around a search result.

    Args:
        file_path: The file_path from a search result (e.g. "core/02-modules/scripts-manager/api-contracts.md")
        chunk_index: The chunk_index from a search result
        window: Number of chunks before and after to include (default 1)

    Returns:
        Concatenated content of the target chunk and its neighbors.
    """
    from qdrant_client.models import (
        FieldCondition,
        Filter,
        MatchValue,
        Range,
    )

    client = get_client()

    results = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="file_path", match=MatchValue(value=file_path)),
                FieldCondition(
                    key="chunk_index",
                    range=Range(gte=chunk_index - window, lte=chunk_index + window),
                ),
            ]
        ),
        limit=2 * window + 1,
        with_payload=["chunk_index", "chunk_heading", "chunk_content", "doc_title"],
        with_vectors=False,
    )

    points = sorted(results[0], key=lambda p: p.payload.get("chunk_index", 0))

    if not points:
        return f"No chunks found for file_path='{file_path}' around chunk_index={chunk_index}."

    parts = []
    for point in points:
        p = point.payload
        idx = p.get("chunk_index", "?")
        heading = p.get("chunk_heading", "")
        marker = " **(target)**" if idx == chunk_index else ""
        header = f"### Chunk {idx}{marker}"
        if heading:
            header += f" — {heading}"
        parts.append(f"{header}\n\n{p.get('chunk_content', '')}")

    doc_title = points[0].payload.get("doc_title", file_path)
    return f"# Context: {doc_title}\n\n" + "\n\n---\n\n".join(parts)


@mcp.tool()
def list_projects() -> str:
    """List all projects indexed in the vault with document and chunk counts."""
    client = get_client()

    # Scroll all points to count by project
    project_stats: dict[str, dict] = {}
    offset = None

    while True:
        results = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=100,
            offset=offset,
            with_payload=["project", "file_path"],
            with_vectors=False,
        )
        points, next_offset = results
        for point in points:
            proj = point.payload.get("project", "unknown")
            fp = point.payload.get("file_path", "")
            if proj not in project_stats:
                project_stats[proj] = {"chunks": 0, "files": set()}
            project_stats[proj]["chunks"] += 1
            project_stats[proj]["files"].add(fp)
        if next_offset is None:
            break
        offset = next_offset

    if not project_stats:
        return "No projects indexed. Run reindex_vault first."

    lines = ["# Indexed Projects\n"]
    total_files = 0
    total_chunks = 0
    for proj in sorted(project_stats.keys()):
        stats = project_stats[proj]
        n_files = len(stats["files"])
        n_chunks = stats["chunks"]
        total_files += n_files
        total_chunks += n_chunks
        lines.append(f"- **{proj}**: {n_files} files, {n_chunks} chunks")

    lines.append(f"\n**Total**: {total_files} files, {total_chunks} chunks")
    return "\n".join(lines)


@mcp.tool()
def reindex_vault(full: bool = False) -> str:
    """Reindex the Obsidian vault into Qdrant.

    Args:
        full: If True, delete everything and reindex from scratch.
              If False (default), only reindex files that changed since last indexing.

    Returns:
        Indexing report with stats.
    """
    from vault_search.indexer import index_vault

    report = index_vault(full=full)
    return (
        f"# Reindex Report ({report['mode']} mode)\n\n"
        f"- **Files indexed**: {report['files_indexed']}\n"
        f"- **Files skipped** (unchanged): {report['files_skipped']}\n"
        f"- **Total chunks**: {report['total_chunks']}\n"
        f"- **Total files in vault**: {report['total_files']}\n"
        f"- **Time**: {report['elapsed_seconds']}s\n"
    )


# ---------------------------------------------------------------------------
# Vault file operations (CRUD)
# ---------------------------------------------------------------------------


@mcp.tool()
def get_file_contents(filepath: str) -> str:
    """Read the content of a file in the Obsidian vault.

    Args:
        filepath: Path relative to vault root (e.g. "notes/daily.md")

    Returns:
        The raw file content.
    """
    from vault_search import vault_ops

    try:
        return vault_ops.get_file_contents(filepath)
    except (FileNotFoundError, ValueError) as e:
        return f"Error: {e}"


@mcp.tool()
def get_file_metadata(filepath: str) -> str:
    """Get frontmatter metadata and file stats for a vault file.

    Args:
        filepath: Path relative to vault root.

    Returns:
        Formatted metadata including frontmatter fields, tags, and file stats.
    """
    from vault_search import vault_ops

    try:
        meta = vault_ops.get_file_metadata(filepath)
        lines = [f"# Metadata: {meta['path']}\n"]
        lines.append(f"**Size**: {meta['stat']['size']} bytes")
        lines.append(f"**Modified**: {meta['stat']['modified']}")
        lines.append(f"**Created**: {meta['stat']['created']}")
        if meta["tags"]:
            lines.append(f"**Tags**: {', '.join(meta['tags'])}")
        if meta["frontmatter"]:
            lines.append("\n## Frontmatter\n")
            for key, value in meta["frontmatter"].items():
                lines.append(f"- **{key}**: {value}")
        return "\n".join(lines)
    except (FileNotFoundError, ValueError) as e:
        return f"Error: {e}"


@mcp.tool()
def create_or_update_file(filepath: str, content: str) -> str:
    """Create a new file or overwrite an existing file in the vault.

    Args:
        filepath: Path relative to vault root (e.g. "projects/new-note.md"). Parent directories are created automatically.
        content: Full file content to write.

    Returns:
        Confirmation with file path and whether it was created or updated.
    """
    from vault_search import vault_ops

    try:
        result = vault_ops.create_or_update_file(filepath, content)
        action = "Created" if result["created"] else "Updated"
        return f"{action} `{result['path']}` ({result['size']} bytes)"
    except ValueError as e:
        return f"Error: {e}"


@mcp.tool()
def append_content(filepath: str, content: str) -> str:
    """Append content to the end of a vault file (creates the file if it doesn't exist).

    Args:
        filepath: Path relative to vault root.
        content: Content to append.

    Returns:
        Confirmation with bytes appended.
    """
    from vault_search import vault_ops

    try:
        result = vault_ops.append_content(filepath, content)
        return f"Appended {result['appended_bytes']} bytes to `{result['path']}`"
    except ValueError as e:
        return f"Error: {e}"


@mcp.tool()
def patch_content(
    filepath: str,
    operation: str,
    target_type: str,
    target: str,
    content: str,
) -> str:
    """Apply a targeted modification to a specific section of a vault file.

    Args:
        filepath: Path relative to vault root.
        operation: "append" (add after section), "prepend" (add before section content), or "replace" (replace section content).
        target_type: "heading" (target a markdown heading) or "frontmatter" (target a frontmatter field).
        target: For headings: the heading text (e.g. "Setup") or nested path using '::' separator (e.g. "Setup::Installation"). For frontmatter: the field name.
        content: Content to insert or replace with.

    Returns:
        Confirmation of the patch operation.
    """
    from vault_search import vault_ops

    try:
        result = vault_ops.patch_content(filepath, operation, target_type, target, content)
        return f"Patched `{result['path']}`: {result['operation']} on {result['target_type']} '{result['target']}'"
    except (FileNotFoundError, ValueError) as e:
        return f"Error: {e}"


@mcp.tool()
def delete_file(filepath: str, confirm: bool = False) -> str:
    """Delete a file from the vault.

    Args:
        filepath: Path relative to vault root.
        confirm: Must be True to actually delete. Safety guard to prevent accidental deletion.

    Returns:
        Confirmation of deletion.
    """
    from vault_search import vault_ops

    try:
        result = vault_ops.delete_file(filepath, confirm=confirm)
        return f"Deleted `{result['path']}`"
    except (FileNotFoundError, ValueError) as e:
        return f"Error: {e}"


@mcp.tool()
def list_files_in_dir(dirpath: str = "") -> str:
    """List files and subdirectories in a vault directory.

    Args:
        dirpath: Relative directory path. Empty string or omit for vault root.

    Returns:
        Formatted list of files and directories.
    """
    from vault_search import vault_ops

    try:
        entries = vault_ops.list_files_in_dir(dirpath)
        if not entries:
            return f"Directory `{dirpath or '/'}` is empty."
        header = f"# Contents of `{dirpath or '/'}`\n"
        return header + "\n".join(f"- {e}" for e in entries)
    except (NotADirectoryError, ValueError) as e:
        return f"Error: {e}"


@mcp.tool()
def list_files_in_vault() -> str:
    """List all top-level files and directories in the vault root.

    Returns:
        Formatted list of root-level entries.
    """
    from vault_search import vault_ops

    try:
        entries = vault_ops.list_files_in_vault()
        if not entries:
            return "Vault is empty."
        return "# Vault Root\n\n" + "\n".join(f"- {e}" for e in entries)
    except ValueError as e:
        return f"Error: {e}"


@mcp.tool()
def simple_search(query: str, context_length: int = 100) -> str:
    """Search for text across all markdown files in the vault (case-insensitive).

    Args:
        query: Text to search for.
        context_length: Characters of context around each match (default 100).

    Returns:
        Formatted search results with file paths and context snippets.
    """
    from vault_search import vault_ops

    results = vault_ops.simple_search(query, context_length=context_length)
    if not results:
        return f"No matches found for: \"{query}\""

    parts = [f"Found {len(results)} matches for: \"{query}\"\n"]
    for r in results:
        parts.append(f"### {r['filepath']}\n```\n...{r['context']}...\n```\n")

    return "\n".join(parts)


@mcp.tool()
def get_recent_changes(days: int = 14, limit: int = 10) -> str:
    """Get recently modified files in the vault.

    Args:
        days: Only include files modified within this many days (default 14).
        limit: Maximum number of results (default 10).

    Returns:
        List of recently changed files with modification dates and sizes.
    """
    from vault_search import vault_ops

    results = vault_ops.get_recent_changes(days=days, limit=limit)
    if not results:
        return f"No files modified in the last {days} days."

    lines = [f"# Recent Changes (last {days} days)\n"]
    for r in results:
        lines.append(f"- `{r['filepath']}` — {r['modified']} ({r['size']} bytes)")
    return "\n".join(lines)


@mcp.tool()
def list_tags() -> str:
    """List all tags used across the vault with occurrence counts.

    Returns:
        Tags sorted by frequency, from both frontmatter and inline #tags.
    """
    from vault_search import vault_ops

    tags = vault_ops.list_tags()
    if not tags:
        return "No tags found in the vault."

    lines = ["# Vault Tags\n"]
    for tag, count in tags.items():
        lines.append(f"- **{tag}**: {count}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Vault structure & schema discovery
# ---------------------------------------------------------------------------


@mcp.tool()
def get_vault_map(max_depth: int = 3) -> str:
    """Get the vault's directory structure as a tree with file counts per directory.

    Args:
        max_depth: Maximum directory depth to show (default 3). Use 0 for root only.

    Returns:
        Formatted tree showing directory hierarchy, file counts, and file types.
    """
    from vault_search import vault_ops

    tree = vault_ops.get_vault_map(max_depth=max_depth)
    return "# Vault Structure\n\n" + vault_ops.format_vault_tree(tree)


@mcp.tool()
def get_frontmatter_schema() -> str:
    """Discover all frontmatter fields used across the vault with types and frequency.

    Returns:
        Table of frontmatter fields showing name, type, usage count, and example values.
    """
    from vault_search import vault_ops

    schema = vault_ops.get_frontmatter_schema()
    if not schema:
        return "No frontmatter fields found in the vault."

    total = schema[0]["total_files"] if schema else 0
    lines = [f"# Frontmatter Schema ({total} files scanned)\n"]
    lines.append("| Field | Type | Count | Examples |")
    lines.append("|-------|------|-------|----------|")
    for entry in schema:
        examples = ", ".join(str(e) for e in entry["examples"][:3])
        pct = round(entry["count"] / total * 100) if total else 0
        lines.append(f"| `{entry['field']}` | {entry['type']} | {entry['count']} ({pct}%) | {examples} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Wikilink graph
# ---------------------------------------------------------------------------


@mcp.tool()
def get_backlinks(filepath: str) -> str:
    """Find all files that contain wikilinks pointing to the given file.

    Args:
        filepath: Relative path to the target file (e.g. "projects/auth.md").

    Returns:
        List of files linking to this file.
    """
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    client = get_client()

    files = set()
    offset = None

    while True:
        results = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(
                must=[FieldCondition(key="links_to", match=MatchValue(value=filepath))]
            ),
            limit=100,
            offset=offset,
            with_payload=["file_path", "doc_title"],
            with_vectors=False,
        )
        points, next_offset = results
        for point in points:
            fp = point.payload.get("file_path", "")
            title = point.payload.get("doc_title", "")
            if fp and fp != filepath:
                files.add((fp, title))
        if next_offset is None:
            break
        offset = next_offset

    if not files:
        return f"No backlinks found for `{filepath}`."

    lines = [f"# Backlinks to `{filepath}`\n"]
    for fp, title in sorted(files):
        label = f"{title} (`{fp}`)" if title else f"`{fp}`"
        lines.append(f"- {label}")
    return "\n".join(lines)


@mcp.tool()
def get_outgoing_links(filepath: str) -> str:
    """List all files that the given file links to via wikilinks.

    Args:
        filepath: Relative path to the source file.

    Returns:
        List of outgoing link targets.
    """
    from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

    client = get_client()

    results = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="file_path", match=MatchValue(value=filepath)),
                FieldCondition(key="chunk_index", range=Range(gte=0, lte=0)),
            ]
        ),
        limit=1,
        with_payload=["links_to", "links_to_raw"],
        with_vectors=False,
    )

    points = results[0]
    if not points:
        return f"No indexed data found for `{filepath}`."

    links = points[0].payload.get("links_to", [])
    raw_links = points[0].payload.get("links_to_raw", [])

    if not raw_links:
        return f"`{filepath}` contains no wikilinks."

    lines = [f"# Outgoing links from `{filepath}`\n"]
    for raw, resolved in zip(raw_links, [None] * len(raw_links)):
        # Match raw to resolved
        pass

    # Show resolved links
    for link in links:
        lines.append(f"- `{link}`")

    # Show unresolved raw targets
    unresolved = set(raw_links) - set(
        t.split("#")[0].strip() for t in raw_links
        if any(l.endswith(t + ".md") or l.endswith("/" + t.split("/")[-1] + ".md") or l == t for l in links)
    )

    return "\n".join(lines)


@mcp.tool()
def find_broken_links() -> str:
    """Find all wikilinks in the vault that point to non-existent files.

    Returns:
        List of broken links with source file and target.
    """
    from vault_search.config import VAULT_PATH as vault_path
    from vault_search.indexer import find_markdown_files

    # Scan filesystem directly for accuracy
    md_files = find_markdown_files(vault_path)
    all_stems = {f.stem: str(f.relative_to(vault_path)) for f in md_files}
    all_paths = set(all_stems.values())

    broken = []
    wikilink_re = __import__("re").compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')

    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        rel_path = str(md_file.relative_to(vault_path))
        for match in wikilink_re.finditer(content):
            target = match.group(1).split("#")[0].strip()
            if not target:
                continue

            # Try to resolve
            resolved = False
            for candidate in [target, target + ".md"]:
                if candidate in all_paths:
                    resolved = True
                    break
            if not resolved:
                stem = target.split("/")[-1]
                if stem in all_stems:
                    resolved = True
            if not resolved:
                broken.append({"source": rel_path, "target": target})

    if not broken:
        return "No broken wikilinks found."

    lines = [f"# Broken Wikilinks ({len(broken)} found)\n"]
    for b in broken:
        lines.append(f"- `{b['source']}` -> `[[{b['target']}]]`")
    return "\n".join(lines)


@mcp.tool()
def find_orphan_files() -> str:
    """Find files that have no incoming wikilinks from other files.

    Returns:
        List of files with zero backlinks.
    """
    from vault_search.config import VAULT_PATH as vault_path
    from vault_search.indexer import find_markdown_files, extract_wikilinks, resolve_wikilink_target

    md_files = find_markdown_files(vault_path)
    all_file_paths = set()
    linked_to = set()

    for md_file in md_files:
        rel = str(md_file.relative_to(vault_path))
        all_file_paths.add(rel)

        try:
            content = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for target in extract_wikilinks(content):
            resolved = resolve_wikilink_target(target, vault_path)
            if resolved:
                linked_to.add(resolved)

    orphans = sorted(all_file_paths - linked_to)

    if not orphans:
        return "No orphan files found — every file has at least one incoming link."

    lines = [f"# Orphan Files ({len(orphans)} found)\n"]
    for f in orphans:
        lines.append(f"- `{f}`")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Batch operations
# ---------------------------------------------------------------------------


@mcp.tool()
def batch_update_frontmatter(
    filter_type: str,
    filter_value: str,
    field: str,
    value: str,
    operation: str = "set",
    confirm: bool = False,
) -> str:
    """Update a frontmatter field across multiple files matching a filter.

    Args:
        filter_type: "project" (by project name), "tag" (by tag), or "glob" (by file pattern like "projects/**/*.md").
        filter_value: Filter value.
        field: Frontmatter field to update.
        value: Value to set, append, or remove (YAML parsed).
        operation: "set" (replace), "append" (add to list), "remove" (remove from list).
        confirm: Set to True to apply changes. Default False returns a preview.

    Returns:
        Preview or confirmation of changes applied.
    """
    from vault_search import vault_ops

    try:
        result = vault_ops.batch_update_frontmatter(
            filter_type=filter_type,
            filter_value=filter_value,
            field=field,
            value=value,
            operation=operation,
            confirm=confirm,
        )
        if result["preview"]:
            lines = [f"# Preview: batch update frontmatter\n"]
            lines.append(f"**Filter**: {filter_type} = `{filter_value}`")
            lines.append(f"**Operation**: {operation} `{field}` = `{value}`")
            lines.append(f"**Affected files**: {result['count']}\n")
            for f in result["affected_files"]:
                lines.append(f"- `{f}`")
            lines.append(f"\nSet `confirm=True` to apply.")
            return "\n".join(lines)
        return f"Applied `{operation}` on `{field}` to {result['count']} files."
    except ValueError as e:
        return f"Error: {e}"


@mcp.tool()
def batch_rename_tag(
    old_tag: str,
    new_tag: str,
    confirm: bool = False,
) -> str:
    """Rename a tag across all vault files (both frontmatter and inline #tags).

    Args:
        old_tag: The tag to rename (without # prefix).
        new_tag: The new tag name (without # prefix).
        confirm: Set to True to apply. Default False returns a preview of affected files.

    Returns:
        Preview or confirmation of tag rename.
    """
    from vault_search import vault_ops

    try:
        result = vault_ops.batch_rename_tag(old_tag=old_tag, new_tag=new_tag, confirm=confirm)
        if result["preview"]:
            lines = [f"# Preview: rename tag `{old_tag}` -> `{new_tag}`\n"]
            lines.append(f"**Affected files**: {result['count']}")
            lines.append(f"**Frontmatter changes**: {result['frontmatter_changes']}")
            lines.append(f"**Inline changes**: {result['inline_changes']}\n")
            for f in result["affected_files"]:
                lines.append(f"- `{f}`")
            lines.append(f"\nSet `confirm=True` to apply.")
            return "\n".join(lines)
        return f"Renamed tag `{old_tag}` -> `{new_tag}` in {result['count']} files ({result['frontmatter_changes']} frontmatter, {result['inline_changes']} inline)."
    except ValueError as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Operation log
# ---------------------------------------------------------------------------


@mcp.tool()
def log_operation(
    operation_type: str,
    title: str,
    summary: str = "",
    pages_touched: list[str] | None = None,
    source: str = "",
) -> str:
    """Append a structured entry to the vault operation log.

    Use after ingesting sources, running maintenance, or filing valuable query results.

    Args:
        operation_type: Type of operation — "ingest", "query", "lint", or "maintenance".
        title: Short title for the log entry (e.g. article title, query summary).
        summary: Optional longer description of what was done.
        pages_touched: Optional list of file paths that were created or modified.
        source: Optional source file path (for ingest operations).

    Returns:
        Confirmation with the formatted log entry.
    """
    from vault_search import vault_ops

    result = vault_ops.log_operation(
        operation_type=operation_type,
        title=title,
        summary=summary,
        pages_touched=pages_touched or [],
        source=source,
    )
    return f"Logged to `{result['path']}`:\n\n{result['entry']}"


@mcp.tool()
def get_operation_log(last_n: int = 20, filter_type: str = "") -> str:
    """Read recent entries from the vault operation log.

    Args:
        last_n: Number of most recent entries to return (default 20).
        filter_type: Only return entries of this type (e.g. "ingest", "lint"). Empty for all.

    Returns:
        Formatted log entries.
    """
    from vault_search import vault_ops

    entries = vault_ops.get_operation_log(last_n=last_n, filter_type=filter_type)
    if not entries:
        msg = "No log entries found"
        if filter_type:
            msg += f" for type '{filter_type}'"
        return msg + "."

    lines = [f"# Operation Log (last {len(entries)} entries)\n"]
    for entry in entries:
        lines.append(f"## [{entry['date']}] {entry['operation_type']} | {entry['title']}")
        if entry["body"]:
            lines.append(entry["body"])
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Vault lint
# ---------------------------------------------------------------------------


@mcp.tool()
def lint_vault(stale_days: int = 90) -> str:
    """Run a comprehensive health check on the vault.

    Checks for: broken wikilinks, orphan files, missing frontmatter,
    stale documents, stub documents, and isolated pages (no outgoing links).

    Args:
        stale_days: Flag files not modified within this many days (default 90).

    Returns:
        Structured health report grouped by severity.
    """
    from vault_search import vault_ops

    result = vault_ops.lint_vault(stale_days=stale_days)
    summary = result["summary"]

    lines = [
        "# Vault Health Report\n",
        f"**Files scanned**: {summary['total_files']}",
        f"**Critical**: {summary['critical_count']}",
        f"**Warnings**: {summary['warning_count']}",
        f"**Info**: {summary['info_count']}\n",
    ]

    if result["critical"]:
        lines.append("## Critical\n")
        for issue in result["critical"]:
            lines.append(f"- `{issue.get('file', '')}`: {issue['message']}")
        lines.append("")

    if result["warning"]:
        lines.append("## Warnings\n")
        for issue in result["warning"]:
            lines.append(f"- `{issue.get('file', '')}`: {issue['message']}")
        lines.append("")

    if result["info"]:
        lines.append("## Info\n")
        for issue in result["info"]:
            lines.append(f"- `{issue.get('file', '')}`: {issue['message']}")
        lines.append("")

    if not result["critical"] and not result["warning"]:
        lines.append("Vault is healthy!")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Vault migration
# ---------------------------------------------------------------------------


@mcp.tool()
def migrate_vault(confirm: bool = False) -> str:
    """Migrate an existing vault to the LLM Wiki pattern (v0.4.0+).

    Creates raw/ and wiki/ directories, adds missing frontmatter fields
    (project, type, status, tags, created, updated), and initializes the
    operation log. Non-destructive: never moves or deletes files.

    Args:
        confirm: If False (default), return preview of what would change.
                 If True, apply changes.

    Returns:
        Migration report showing what was (or would be) changed.
    """
    from vault_search.migrate import migrate_vault as _migrate

    result = _migrate(confirm=confirm)
    summary = result["summary"]

    lines = [
        "# Vault Migration Report\n",
        f"**Mode**: {'Applied' if result['applied'] else 'Preview'}",
        f"**Total files**: {summary['total_files']}",
        f"**Files needing frontmatter**: {summary['files_needing_frontmatter']}",
        f"**Directories to create**: {summary['dirs_to_create']}",
        f"**Log file to create**: {summary['log_to_create']}\n",
    ]

    # Directories
    lines.append("## Directories\n")
    for d in result["directories"]:
        status = "exists" if d["exists"] else ("created" if result["applied"] else "will create")
        lines.append(f"- `{d['path']}` — {status}")

    # Log file
    log = result["log_file"]
    log_status = "exists" if log["exists"] else ("created" if result["applied"] else "will create")
    lines.append(f"\n## Operation Log\n\n- `{log['path']}` — {log_status}")

    # Frontmatter changes
    if result["frontmatter_changes"]:
        lines.append(f"\n## Frontmatter Changes ({len(result['frontmatter_changes'])} files)\n")
        for change in result["frontmatter_changes"]:
            fields = ", ".join(change["missing_fields"])
            classification = change.get("classification", "unknown")
            lines.append(f"- `{change['path']}` [{classification}] — missing: {fields}")

    if not result["applied"]:
        lines.append(f"\nSet `confirm=True` to apply these changes.")

    return "\n".join(lines)


def main():
    mcp.run(transport="stdio")
