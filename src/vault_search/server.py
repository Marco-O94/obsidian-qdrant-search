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
    "vault-search",
    instructions=(
        "Semantic search over the Obsidian vault documentation. "
        "Use search_vault to find relevant documentation by natural language query. "
        "Use list_projects to see what's indexed. "
        "Use reindex_vault to update the index after documentation changes."
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


def main():
    mcp.run(transport="stdio")
