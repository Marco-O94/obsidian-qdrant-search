---
description: Search the Obsidian vault documentation using semantic search via Qdrant. Use when you need to find documentation by meaning rather than exact keywords.
---

# Vault Semantic Search

You have access to the `obsidian-qdrant-search` MCP server which provides semantic search over the Obsidian vault. Use it to find relevant documentation even when the user's query doesn't match exact keywords.

## Available MCP tools

### search_vault
Primary search tool. Always start here.

```
search_vault(query, project?, doc_type?, tag?, top_k?)
```

- `query`: Natural language search query
- `project`: Filter by project (e.g. "core", "sentinel-ai", "internal-dashboard-next")
- `doc_type`: Filter by type (e.g. "api-contract", "service-layer", "data-model", "overview")
- `tag`: Filter by frontmatter tag (e.g. "kubernetes", "database", "security")
- `top_k`: Number of results (default 5)

### get_chunk_context
Use after search_vault when a result is relevant but needs more context.

```
get_chunk_context(file_path, chunk_index, window?)
```

- `file_path`: From search result (e.g. "core/02-modules/scripts-manager/api-contracts.md")
- `chunk_index`: From search result
- `window`: Chunks before/after (default 1)

### list_projects
Lists all indexed projects with stats. Use to discover what's available.

### reindex_vault
Re-indexes the vault. Use `full=true` after major documentation changes.

## Workflow

1. **Search** with `search_vault` using a natural language query derived from the user's question
2. **Evaluate** results — check scores (>0.7 is strong, 0.5-0.7 is moderate)
3. **Expand** context with `get_chunk_context` if a result is promising but incomplete
4. **Filter** — if too many results, narrow with `project`, `doc_type`, or `tag`
5. **Synthesize** — combine findings into a clear answer for the user

## Tips

- Rephrase technical jargon into natural language for better semantic matches
- Use `project` filter when you know which project the user is asking about
- If scores are low, try a broader or differently worded query
- Use `get_chunk_context` to see tables and code blocks that may have been in adjacent chunks

## User query

$ARGUMENTS
