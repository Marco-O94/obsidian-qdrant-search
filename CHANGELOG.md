# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-04-13

### Added

- **LLM Wiki pattern** (inspired by Karpathy): adopted the three-layer architecture (raw sources / wiki pages / schema) as the vault convention model. Documents are structured for incremental, compounding knowledge bases maintained by LLMs
- **Operation log**: `log_operation` and `get_operation_log` MCP tools — append-only chronological record of vault operations (ingest, query, lint, maintenance) with structured markdown entries
- **Vault lint**: `lint_vault` MCP tool — comprehensive health check in one call: broken wikilinks (critical), orphan files (warning), missing frontmatter (warning), stale documents (info), stub documents (info), isolated pages with no outgoing links (info)
- **Vault migration**: `migrate_vault` MCP tool + `vault-search-migrate` CLI — non-destructive, idempotent migration for existing vaults: creates raw/ and wiki/ directories, adds missing frontmatter (project, type, status, tags, created, updated) with sensible defaults, initializes operation log. Preview mode by default, apply with `confirm=True` / `--apply`
- **CLI interface for multi-agent access**: 6 new CLI commands (`vault-search-search`, `vault-search-read`, `vault-search-write`, `vault-search-lint`, `vault-search-log`, `vault-search-map`) with `--json` output for non-MCP agents (Codex, OpenCode, etc.)
- **CLAUDE.md**: unified schema document auto-loaded by Claude Code — includes vault conventions, document structure rules, Ingest/Query/Lint workflows, and full 26-tool MCP reference
- **AGENTS.md**: schema document for non-Claude agents, same conventions with CLI command references
- **Test suite expanded**: 120 tests (was 76), including operation log, vault lint, and migration coverage
- **`VAULT_LOG_FILE` env var**: configurable log filename (default `_log.md`)

### Changed

- **MCP server instructions**: expanded from a brief tool listing to a workflow-oriented guide (orient → search → read → write → maintain)
- **Doc-manager agent**: added Karpathy-style Ingest, Query-to-file, and Lint workflows; added Log and Health tool phases
- **Vault search skill**: added log and lint tool documentation
- Server now exposes 27 tools (was 23)

### Fixed

- **Security**: sanitize newlines in `log_operation` title/type to prevent log entry injection
- **Security**: validate `VAULT_LOG_FILE` env var against path traversal (absolute paths and `..` rejected)
- **lint_vault**: exclude hidden directories (`.git/`, `.obsidian/`, `.venv/`) from scan — previously generated spurious warnings
- **get_operation_log**: widen regex to accept hyphenated operation types (e.g. `"my-type"`) — previously silently dropped
- **log_operation**: use atomic file creation (`open("x")`) to prevent race condition with duplicate headers under concurrent writes
- **CLI**: validate integer flags (`--top-k`, `--stale-days`, `--last`, `--depth`) with clean error message instead of Python traceback
- **migrate**: log warnings for files that fail to parse during migration instead of silently skipping

## [0.3.1] - 2026-03-25

### Fixed

- **patch_content**: changed nested heading separator from `/` to `::` to avoid conflicts with URL paths in heading text (e.g. `GET /api/v1/users/{id}`)

## [0.3.0] - 2026-03-25

### Added

- **Vault map**: `get_vault_map` shows directory hierarchy with file counts and types, excluding hidden dirs
- **Frontmatter schema discovery**: `get_frontmatter_schema` reports all frontmatter fields, types, frequency, and examples
- **Wikilink graph**: wikilinks are now extracted and indexed during indexing (`links_to`, `links_to_raw` payload fields)
  - `get_backlinks(filepath)` — find files linking to a given file
  - `get_outgoing_links(filepath)` — list all wikilink targets from a file
  - `find_broken_links()` — detect wikilinks pointing to non-existent files
  - `find_orphan_files()` — find files with no incoming wikilinks
- **Batch operations**:
  - `batch_update_frontmatter` — update a frontmatter field across files filtered by project, tag, or glob (with preview/confirm)
  - `batch_rename_tag` — rename a tag across frontmatter and inline #tags (with preview/confirm)
- **Test suite expanded**: 76 tests (was 43), including wikilink extraction, vault map, schema discovery, and batch operations
- **Documentation manager agent**: `.claude/agents/doc-manager.md` — autonomous agent for creating, updating, and maintaining vault documentation
- **Vault search skill**: moved from `.claude/commands/` to `.claude/skills/vault-search/SKILL.md` (Claude Code skills format)

### Changed

- Server instructions updated to describe all 23 available tools
- Qdrant payload now includes `links_to` and `links_to_raw` for wikilink graph (backward compatible)
- New payload indexes on `links_to` and `file_path` for efficient graph queries
- README restructured with table of contents and icons

## [0.2.0] - 2026-03-25

### Added

- **File read operations**: `get_file_contents`, `get_file_metadata`, `list_files_in_dir`, `list_files_in_vault`
- **File write operations**: `create_or_update_file`, `append_content`, `patch_content`, `delete_file`
- **Text search**: `simple_search` for case-insensitive keyword search across all markdown files
- **Discovery tools**: `list_tags` (frontmatter + inline tags with counts), `get_recent_changes` (recently modified files)
- **Patch by heading**: targeted modifications to specific markdown sections, supporting nested heading paths (e.g. "Setup::Installation")
- **Patch by frontmatter**: targeted modifications to frontmatter fields with append/prepend/replace operations
- **Auto-reindex**: write operations automatically reindex the modified file in Qdrant (best-effort, never blocks writes)
- **Path security**: all file operations validate paths to prevent traversal outside the vault
- **Delete safety guard**: `delete_file` requires explicit `confirm=True` parameter
- **`index_single_file()`**: extracted per-file indexing function for efficient single-file reindexing
- **Test suite**: 43 tests covering path security, all CRUD operations, patch operations, and search

### Changed

- MCP server name changed from `vault-search` to `obsidian-qdrant-search`
- Server instructions updated to describe all 15 available tools
- Skill file updated with complete tool reference and workflow guide

## [0.1.0] - 2025-05-22

### Added

- Initial release
- Semantic search over Obsidian vault using Qdrant and FastEmbed
- Markdown-aware chunking (H2/H3 sections, preserves tables and code blocks)
- Incremental indexing with SHA-256 change detection
- Auto-start Qdrant Docker container
- MCP tools: `search_vault`, `get_chunk_context`, `list_projects`, `reindex_vault`
- CLI commands: `obsidian-qdrant-search` (MCP server), `vault-index` (indexing)
- Frontmatter-based filtering by project, document type, and tags
