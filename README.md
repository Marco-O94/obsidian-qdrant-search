<p align="center">
  <img src="banner.png" alt="obsidian-qdrant-search" width="100%">
</p>

# Obsidian Qdrant Search

<p align="center">

[![Version](https://img.shields.io/badge/version-0.4.0-green?style=flat-square)](CHANGELOG.md)
[![PyPI](https://img.shields.io/pypi/v/obsidian-qdrant-search?style=flat-square)](https://pypi.org/project/obsidian-qdrant-search/)
[![Python](https://img.shields.io/pypi/pyversions/obsidian-qdrant-search?style=flat-square)](https://pypi.org/project/obsidian-qdrant-search/)
[![License](https://img.shields.io/pypi/l/obsidian-qdrant-search?style=flat-square)](LICENSE)
[![Qdrant](https://img.shields.io/badge/vector%20db-Qdrant-dc244c?style=flat-square&logo=qdrant)](https://qdrant.tech/)
[![MCP](https://img.shields.io/badge/protocol-MCP-blue?style=flat-square)](https://modelcontextprotocol.io/)
[![Obsidian](https://img.shields.io/badge/vault-Obsidian-7c3aed?style=flat-square&logo=obsidian)](https://obsidian.md/)

</p>

MCP server for **semantic search** and **file management** over an Obsidian vault. Uses Qdrant as vector store and FastEmbed for local embeddings. Provides a complete set of tools for AI agents to read, write, search, and manage vault content — no external Obsidian plugins required.

---

### Table of Contents

| | Section | Description |
|---|---|---|
| **?** | [Why?](#why) | The problem this solves |
| **✨** | [Features](#features) | Full feature list |
| **⚡** | [Quick Start](#quick-start) | Installation and setup |
| **📖** | [LLM Wiki Pattern](#llm-wiki-pattern) | Karpathy-inspired knowledge base model |
| **🤖** | [Agent Skills](#agent-skills) | Skill and agent for Claude Code |
| **🔧** | [MCP Tools](#mcp-tools) | All 27 tools — Search, Read, Write, Discover, Graph, Batch, Log, Health, Maintenance |
| **💻** | [CLI Commands](#cli-commands) | Command-line interface for any agent |
| **🏗️** | [Architecture](#architecture) | How it works under the hood |
| **📁** | [Project Structure](#project-structure) | File layout |

---

## Why?

Standard text search in Obsidian (and MCP tools like mcp-obsidian) is keyword-based — it only finds exact matches. This means:

- Searching for "API logs" won't find a section titled "Execution tracking endpoints"
- Searching for "how does authentication work" returns nothing unless those exact words appear
- Typos, synonyms, and rephrased concepts are invisible to keyword search

**obsidian-qdrant-search** uses vector embeddings to understand the *meaning* of your query and match it against the *meaning* of your documentation. It finds relevant results even when the wording is completely different.

Additionally, it provides **full CRUD file operations** directly on the vault filesystem, so AI agents can read, create, update, and manage notes without relying on external Obsidian community plugins like Local Rest API.

## Features

- **LLM Wiki pattern** — Karpathy-inspired three-layer architecture for persistent, compounding knowledge bases
- **Semantic search** — find docs by meaning, not just keywords
- **Full file management** — read, create, update, append, patch, and delete vault files
- **Targeted patching** — modify specific sections by heading or frontmatter field
- **Text search** — case-insensitive keyword search across all markdown files
- **Markdown-aware chunking** — tables and code blocks are never split mid-block
- **Frontmatter filters** — narrow results by project, document type, or tags
- **Context expansion** — fetch adjacent chunks around a search result
- **Wikilink graph** — navigate backlinks, outgoing links, find broken links and orphan files
- **Vault health checks** — comprehensive lint with broken links, orphans, stale docs, missing metadata
- **Operation log** — chronological record of ingest, query, lint, and maintenance actions
- **Vault migration** — non-destructive upgrade of existing vaults to the LLM Wiki conventions
- **Multi-agent CLI** — 7 CLI commands with `--json` output for any agent (Codex, OpenCode, etc.)
- **Vault map** — visualize directory structure with file counts
- **Frontmatter schema discovery** — see all fields, types, and usage across the vault
- **Tag discovery** — list all tags (frontmatter + inline) with occurrence counts
- **Recent changes** — track recently modified files
- **Batch operations** — update frontmatter or rename tags across multiple files at once
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

## LLM Wiki Pattern

Inspired by [Karpathy's LLM Wiki](https://gist.github.com/karpathy/1dd0294ef9567971c1e4348a90d69285), this project supports a three-layer architecture for building persistent, compounding knowledge bases maintained by LLMs:

| Layer | Directory | Purpose |
|-------|-----------|---------|
| **Raw sources** | `raw/` | Immutable source documents — articles, papers, transcripts, web clips. The LLM reads from these but never modifies them. |
| **Wiki** | `wiki/` | LLM-maintained pages — entities, concepts, summaries, syntheses. The LLM owns this layer entirely. |
| **Schema** | `CLAUDE.md` / `AGENTS.md` | Conventions that tell the LLM how the wiki is structured and what workflows to follow. |

### Operations

- **Ingest** — Drop a new source into `raw/`, the LLM reads it, creates/updates wiki pages, adds wikilinks, and logs the operation
- **Query** — Search the wiki, synthesize answers, and optionally file valuable results back as new wiki pages
- **Lint** — Run `lint_vault` for a comprehensive health check (broken links, orphans, stale docs, missing metadata)

### Migration from older versions

Existing vaults can be upgraded with the migration tool. From **Claude Code** (or any MCP client), just ask in natural language:

> "migrate my vault to the LLM Wiki pattern"

Claude Code will call the `migrate_vault` MCP tool automatically — first in preview mode, then ask for confirmation before applying.

From the **command line** (for other agents or manual use):

```bash
# Preview what would change
VAULT_PATH=/path/to/vault uvx --from obsidian-qdrant-search vault-search-migrate

# Apply changes (creates raw/ and wiki/ dirs, adds missing frontmatter, initializes log)
VAULT_PATH=/path/to/vault uvx --from obsidian-qdrant-search vault-search-migrate --apply
```

The migration is non-destructive (never moves or deletes files) and idempotent (safe to run multiple times). See `CLAUDE.md` for the full document structure rules and conventions.

## Agent Skills

This repo includes Claude Code skills and agents in `.claude/`. Copy the `.claude/` directory into your project to make them available. Claude will automatically discover and use them based on context.

#### `/vault-search` — Skill (`.claude/skills/vault-search/`)

Guides the agent through semantic search, text search, file reading, and knowledge graph navigation. Claude can invoke it automatically or you can use it as a slash command:

```
/vault-search how does authentication work
```

#### `doc-manager` — Agent (`.claude/agents/`)

An autonomous documentation agent that creates, updates, organizes, and maintains vault documentation. Includes templates, conventions, health check workflows, and restructuring procedures. Claude dispatches it as a subagent when documentation tasks are needed.

```
/doc-manager document the new authentication module in projects/core
/doc-manager run a vault health check
/doc-manager create an ADR for switching to PostgreSQL
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULT_PATH` | Current working directory | Path to the Obsidian vault directory |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant server URL |
| `COLLECTION_NAME` | `vault_docs` | Qdrant collection name |
| `VAULT_LOG_FILE` | `_log.md` | Operation log filename |

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
| `target` | string | required | Heading text (e.g. `"Setup"` or `"Setup::Installation"`) or frontmatter field name |
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

#### get_vault_map

Get the vault's directory structure as a tree with file counts.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_depth` | int | 3 | Maximum directory depth to show |

#### get_frontmatter_schema

Discover all frontmatter fields used across the vault with types, frequency, and examples.

### Graph

#### get_backlinks

Find all files that contain wikilinks pointing to the given file.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filepath` | string | required | Relative path to the target file |

#### get_outgoing_links

List all files that the given file links to via wikilinks.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filepath` | string | required | Relative path to the source file |

#### find_broken_links

Find all wikilinks in the vault that point to non-existent files.

#### find_orphan_files

Find files that have no incoming wikilinks from other files.

### Batch

#### batch_update_frontmatter

Update a frontmatter field across multiple files matching a filter.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filter_type` | string | required | `"project"`, `"tag"`, or `"glob"` |
| `filter_value` | string | required | Filter value (project name, tag, or glob pattern) |
| `field` | string | required | Frontmatter field to update |
| `value` | string | required | Value to set/append/remove (YAML parsed) |
| `operation` | string | `"set"` | `"set"`, `"append"`, or `"remove"` |
| `confirm` | bool | false | Set to `true` to apply (default returns preview) |

#### batch_rename_tag

Rename a tag across all vault files (both frontmatter and inline `#tags`).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `old_tag` | string | required | Tag to rename (without `#`) |
| `new_tag` | string | required | New tag name (without `#`) |
| `confirm` | bool | false | Set to `true` to apply (default returns preview) |

### Log

#### log_operation

Append a structured entry to the vault operation log.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation_type` | string | required | `"ingest"`, `"query"`, `"lint"`, or `"maintenance"` |
| `title` | string | required | Short title for the entry |
| `summary` | string | `""` | Optional description |
| `pages_touched` | list | `[]` | Optional list of modified file paths |
| `source` | string | `""` | Optional source file path (for ingest) |

#### get_operation_log

Read recent entries from the operation log.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `last_n` | int | 20 | Number of recent entries to return |
| `filter_type` | string | `""` | Filter by operation type (e.g. `"ingest"`) |

### Health

#### lint_vault

Comprehensive vault health check. Reports broken wikilinks (critical), orphan files (warning), missing frontmatter (warning), stale documents (info), stub documents (info), and isolated pages (info).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `stale_days` | int | 90 | Flag files not modified within this many days |

### Maintenance

#### reindex_vault

Re-indexes the vault into Qdrant. After upgrading, run with `full=true` to rebuild the index.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `full` | bool | false | If true, drops and recreates the collection |

#### migrate_vault

Migrate an existing vault to the LLM Wiki pattern. Creates `raw/` and `wiki/` directories, adds missing frontmatter fields with sensible defaults, and initializes the operation log. Non-destructive and idempotent.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `confirm` | bool | false | Set to `true` to apply (default returns preview) |

## CLI Commands

### MCP Server & Indexing

| Command | Description |
|---------|-------------|
| `obsidian-qdrant-search` | Start the MCP server (stdio transport) |
| `vault-index [--full]` | Run indexing (incremental by default, `--full` drops and recreates) |

### Multi-Agent CLI

All commands support `--json` for structured output that any agent can parse.

| Command | Description |
|---------|-------------|
| `vault-search-search "<query>" [--project X] [--top-k 5] [--json]` | Semantic search |
| `vault-search-read <filepath>` | Read a vault file |
| `vault-search-write <filepath> --content "..."` | Create or update a file |
| `vault-search-lint [--stale-days 90] [--json]` | Vault health check |
| `vault-search-log <type> "<title>" [--summary "..."] [--source "..."]` | Log an operation |
| `vault-search-log --read [--last 20] [--filter <type>] [--json]` | Read log entries |
| `vault-search-map [--depth 3] [--json]` | Show vault structure |
| `vault-search-migrate [--apply] [--json]` | Migrate vault to LLM Wiki pattern |

These CLI commands make the vault accessible to any agent that can shell out (Codex, OpenCode, etc.), not just MCP-aware clients. See `AGENTS.md` for the full agent-oriented reference.

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
├── CLAUDE.md              # schema layer for Claude Code (auto-loaded)
├── AGENTS.md              # schema layer for other agents (Codex, OpenCode)
├── .claude/
│   ├── skills/
│   │   └── vault-search/SKILL.md   # /vault-search slash command
│   └── agents/
│       └── doc-manager.md           # documentation manager agent
├── tests/
│   ├── test_path_utils.py
│   ├── test_vault_ops.py
│   ├── test_indexer.py
│   ├── test_log.py
│   ├── test_lint.py
│   └── test_migrate.py
└── src/
    └── vault_search/
        ├── __init__.py
        ├── __main__.py      # python -m vault_search
        ├── cli.py            # CLI entry points (index + 7 commands)
        ├── config.py         # env-based configuration
        ├── path_utils.py     # path security & validation
        ├── vault_ops.py      # CRUD, batch, log, lint operations
        ├── migrate.py        # vault migration to LLM Wiki pattern
        ├── qdrant.py         # auto-start Qdrant Docker container
        ├── indexer.py        # markdown parsing, chunking, wikilinks, embedding
        └── server.py         # MCP server + 27 tools
```
