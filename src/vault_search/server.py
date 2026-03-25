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
        "Full-featured Obsidian vault management with semantic search. "
        "SEARCH: search_vault (semantic), simple_search (text), get_chunk_context (expand results). "
        "READ: get_file_contents, get_file_metadata, list_files_in_dir, list_files_in_vault. "
        "WRITE: create_or_update_file, append_content, patch_content (by heading/frontmatter), delete_file. "
        "DISCOVER: list_projects, list_tags, get_recent_changes. "
        "MAINTENANCE: reindex_vault. "
        "Write operations auto-reindex the modified file in Qdrant."
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
        target: For headings: the heading text (e.g. "Setup") or nested path (e.g. "Setup/Installation"). For frontmatter: the field name.
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


def main():
    mcp.run(transport="stdio")
