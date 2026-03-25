<p align="center">
  <img src="banner.png" alt="obsidian-qdrant-search" width="100%">
</p>

# Obsidian Qdrant Search

<p align="center">

[![Version](https://img.shields.io/badge/version-0.2.0-green?style=flat-square)](CHANGELOG.md)
[![PyPI](https://img.shields.io/pypi/v/obsidian-qdrant-search?style=flat-square)](https://pypi.org/project/obsidian-qdrant-search/)
[![Python](https://img.shields.io/pypi/pyversions/obsidian-qdrant-search?style=flat-square)](https://pypi.org/project/obsidian-qdrant-search/)
[![License](https://img.shields.io/pypi/l/obsidian-qdrant-search?style=flat-square)](LICENSE)
[![Qdrant](https://img.shields.io/badge/vector%20db-Qdrant-dc244c?style=flat-square&logo=qdrant)](https://qdrant.tech/)
[![MCP](https://img.shields.io/badge/protocol-MCP-blue?style=flat-square)](https://modelcontextprotocol.io/)
[![Obsidian](https://img.shields.io/badge/vault-Obsidian-7c3aed?style=flat-square&logo=obsidian)](https://obsidian.md/)

</p>

MCP server for **semantic search** and **file management** over an Obsidian vault. Uses Qdrant as vector store and FastEmbed for local embeddings. Provides a complete set of tools for AI agents to read, write, search, and manage vault content — no external Obsidian plugins required.

## Why?

Standard text search in Obsidian (and MCP tools like mcp-obsidian) is keyword-based — it only finds exact matches. This means:

- Searching for "API logs" won't find a section titled "Execution tracking endpoints"
- Searching for "how does authentication work" returns nothing unless those exact words appear
- Typos, synonyms, and rephrased concepts are invisible to keyword search

**obsidian-qdrant-search** uses vector embeddings to understand the *meaning* of your query and match it against the *meaning* of your documentation. It finds relevant results even when the wording is completely different.

Additionally, it provides **full CRUD file operations** directly on the vault filesystem, so AI agents can read, create, update, and manage notes without relying on external Obsidian community plugins like Local Rest API.

### Features

- **Semantic search** — find docs by meaning, not just keywords
- **Full file management** — read, create, update, append, patch, and delete vault files
- **Targeted patching** — modify specific sections by heading or frontmatter field
- **Text search** — case-insensitive keyword search across all markdown files
- **Markdown-aware chunking** — tables and code blocks are never split mid-block
- **Frontmatter filters** — narrow results by project, document type, or tags
- **Context expansion** — fetch adjacent chunks around a search result
- **Tag discovery** — list all tags (frontmatter + inline) with occurrence counts
- **Recent changes** — track recently modified files
- **Incremental indexing** — only re-embeds changed files
- **Auto-reindex on write** — modified files are automatically re-indexed (best-effort)
- **Auto-start Qdrant** — Docker container is managed automatically
- **Local embeddings** — no API keys needed, runs entirely on your machine
- **Path security** — all file operations are validated to prevent access outside the vault

## Prerequisites

- Python 3.11+
- Docker (for Qdrant)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Quick start

### 1. MCP Configuration

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

Qdrant is started automatically via Docker when needed. If a `qdrant` container already exists, it will be reused.

### 2. Initial indexing

```bash
VAULT_PATH=/path/to/your/vault uvx --from obsidian-qdrant-search vault-index --full
```

### Agent skill

This repo includes a Claude Code skill at `.claude/commands/vault-search.md` that teaches the agent how to use all 15 MCP tools effectively — search workflow, when to use semantic vs text search, how to read/write/patch files, and best practices.

Copy the `.claude/commands/` directory into your project to make the skill available. Then use it as a slash command:

```
/vault-search how does authentication work
```

The agent will automatically choose the right tools, search the vault, and synthesize relevant documentation.

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULT_PATH` | Current working directory | Path to the Obsidian vault directory |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant server URL |
| `COLLECTION_NAME` | `vault_docs` | Qdrant collection name |

## MCP Tools

### Search

#### search_vault

Semantic search over the vault documentation.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Natural language search query |
| `project` | string | null | Filter by project name (e.g. `"core"`) |
| `doc_type` | string | null | Filter by document type (e.g. `"api-contract"`, `"service-layer"`) |
| `tag` | string | null | Filter by frontmatter tag (e.g. `"kubernetes"`, `"database"`) |
| `top_k` | int | 5 | Number of results to return |

#### simple_search

Case-insensitive text search across all markdown files.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Text to search for |
| `context_length` | int | 100 | Characters of context around each match |

#### get_chunk_context

Expand context around a search result by fetching adjacent chunks.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | string | required | The `file_path` from a search result |
| `chunk_index` | int | required | The `chunk_index` from a search result |
| `window` | int | 1 | Number of chunks before/after to include |

### Read

#### get_file_contents

Read the raw content of a vault file.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filepath` | string | required | Path relative to vault root |

#### get_file_metadata

Get frontmatter metadata, tags, and file stats (size, dates).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filepath` | string | required | Path relative to vault root |

#### list_files_in_dir

List files and subdirectories in a vault directory (non-recursive).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dirpath` | string | `""` | Relative directory path (empty for root) |

#### list_files_in_vault

List all top-level files and directories in the vault root.

### Write

#### create_or_update_file

Create a new file or overwrite an existing one. Parent directories are created automatically.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filepath` | string | required | Path relative to vault root |
| `content` | string | required | Full file content |

#### append_content

Append content to a file (creates the file if it doesn't exist).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filepath` | string | required | Path relative to vault root |
| `content` | string | required | Content to append |

#### patch_content

Targeted modification of a specific section by heading or frontmatter field.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filepath` | string | required | Path relative to vault root |
| `operation` | string | required | `"append"`, `"prepend"`, or `"replace"` |
| `target_type` | string | required | `"heading"` or `"frontmatter"` |
| `target` | string | required | Heading text (e.g. `"Setup"` or `"Setup/Installation"`) or frontmatter field name |
| `content` | string | required | Content to insert or replace with |

#### delete_file

Delete a file from the vault.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filepath` | string | required | Path relative to vault root |
| `confirm` | bool | false | Must be `true` to actually delete (safety guard) |

### Discover

#### list_projects

Lists all indexed projects with file and chunk counts.

#### list_tags

Lists all tags (frontmatter + inline `#tag`) with occurrence counts across the vault.

#### get_recent_changes

Returns recently modified markdown files sorted by modification date.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | int | 14 | Only include files modified within this many days |
| `limit` | int | 10 | Maximum number of results |

### Maintenance

#### reindex_vault

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
    local embeddings, 384 dim            search / CRUD / reindex
```

**Chunking strategy**: Documents are split by `##` headings, then `###` if needed. Tables and fenced code blocks are never split mid-block. Large sections fall back to a block-aware sliding window with overlap.

**Incremental indexing**: Files are tracked by SHA-256 hash. Only changed files are re-embedded on `reindex_vault()`. Deleted files are automatically cleaned up.

**Auto-reindex on write**: When files are created, updated, or deleted via MCP tools, the search index is automatically updated for the affected file. This is best-effort — if Qdrant is unavailable, the write still succeeds.

## Project structure

```
obsidian-qdrant-search/
├── pyproject.toml
├── docker-compose.yml
├── CHANGELOG.md
├── README.md
├── tests/
│   ├── test_path_utils.py
│   └── test_vault_ops.py
└── src/
    └── vault_search/
        ├── __init__.py
        ├── __main__.py      # python -m vault_search
        ├── cli.py            # vault-index CLI
        ├── config.py         # env-based configuration
        ├── path_utils.py     # path security & validation
        ├── vault_ops.py      # CRUD file operations
        ├── qdrant.py         # auto-start Qdrant Docker container
        ├── indexer.py         # markdown parsing, chunking, embedding
        └── server.py         # MCP server + 15 tools
```
