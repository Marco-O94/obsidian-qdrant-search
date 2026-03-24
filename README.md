<p align="center">
  <img src="banner.png" alt="obsidian-qdrant-search" width="100%">
</p>

# obsidian-qdrant-search

MCP server for **semantic search** over an Obsidian vault. Uses Qdrant as vector store and FastEmbed for local embeddings.

## Why?

Standard text search in Obsidian (and MCP tools like mcp-obsidian) is keyword-based — it only finds exact matches. This means:

- Searching for "API logs" won't find a section titled "Execution tracking endpoints"
- Searching for "how does authentication work" returns nothing unless those exact words appear
- Typos, synonyms, and rephrased concepts are invisible to keyword search

**obsidian-qdrant-search** uses vector embeddings to understand the *meaning* of your query and match it against the *meaning* of your documentation. It finds relevant results even when the wording is completely different.

### Features

- **Semantic search** — find docs by meaning, not just keywords
- **Markdown-aware chunking** — tables and code blocks are never split mid-block
- **Frontmatter filters** — narrow results by project, document type, or tags
- **Context expansion** — fetch adjacent chunks around a search result
- **Incremental indexing** — only re-embeds changed files
- **Auto-start Qdrant** — Docker container is managed automatically
- **Local embeddings** — no API keys needed, runs entirely on your machine

## Prerequisites

- Python 3.11+
- Docker (for Qdrant)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Quick start

### 1. Install

**With uvx (no install needed):**

```bash
uvx obsidian-qdrant-search
```

**Or install locally for development:**

```bash
uv venv && source .venv/bin/activate
uv pip install -e .
```

Qdrant is started automatically via Docker when needed. If a `qdrant` container already exists, it will be reused.

### 2. Initial indexing

```bash
VAULT_PATH=/path/to/your/vault uvx --from obsidian-qdrant-search vault-index --full
```

## MCP Configuration

Add to your `.mcp.json` (project root or Claude Code settings):

```json
{
  "mcpServers": {
    "obsidian-qdrant-search": {
      "command": "uvx",
      "args": ["obsidian-qdrant-search"],
      "env": {
        "VAULT_PATH": "/absolute/path/to/your/vault"
      }
    }
  }
}
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULT_PATH` | Current working directory | Path to the Obsidian vault directory to index |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant server URL |
| `COLLECTION_NAME` | `vault_docs` | Qdrant collection name |

## MCP Tools

### search_vault

Semantic search over the vault documentation.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Natural language search query |
| `project` | string | null | Filter by project name (e.g. `"core"`) |
| `doc_type` | string | null | Filter by document type (e.g. `"api-contract"`, `"service-layer"`) |
| `tag` | string | null | Filter by frontmatter tag (e.g. `"kubernetes"`, `"database"`) |
| `top_k` | int | 5 | Number of results to return |

### get_chunk_context

Expand context around a search result by fetching adjacent chunks.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | string | required | The `file_path` from a search result |
| `chunk_index` | int | required | The `chunk_index` from a search result |
| `window` | int | 1 | Number of chunks before/after to include |

### list_projects

Lists all indexed projects with file and chunk counts.

### reindex_vault

Re-indexes the vault into Qdrant.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `full` | bool | false | If true, drops and recreates the collection |

## CLI Commands

| Command | Description |
|---------|-------------|
| `obsidian-qdrant-search` | Start the MCP server (stdio transport) |
| `vault-index` | Run indexing from the command line |
| `vault-index --full` | Full reindex (drops existing data) |

## Architecture

```
Obsidian vault (.md files)
    |
    v
indexer ── chunk by H2/H3 sections ──> Qdrant (vector DB)
    |         preserves tables              |
    |         preserves code blocks         |
    v                                       v
fastembed (BAAI/bge-small-en-v1.5)    server (MCP stdio)
    local embeddings, 384 dim            search / reindex
```

**Chunking strategy**: Documents are split by `##` headings, then `###` if needed. Tables and fenced code blocks are never split mid-block. Large sections fall back to a block-aware sliding window with overlap.

**Incremental indexing**: Files are tracked by SHA-256 hash. Only changed files are re-embedded on `reindex_vault()`. Deleted files are automatically cleaned up.

## Project structure

```
obsidian-qdrant-search/
├── pyproject.toml
├── docker-compose.yml
├── README.md
└── src/
    └── vault_search/
        ├── __init__.py
        ├── __main__.py     # python -m vault_search
        ├── cli.py           # vault-index CLI
        ├── config.py        # env-based configuration
        ├── qdrant.py        # auto-start Qdrant Docker container
        ├── indexer.py       # markdown parsing, chunking, embedding
        └── server.py        # MCP server + tools
```

## Recommended companion

This tool provides **read-only semantic search** over your vault. For **writing and editing** Obsidian notes via MCP, use [mcp-obsidian](https://github.com/MarkusPfundstein/mcp-obsidian). The two servers complement each other well when used together.
