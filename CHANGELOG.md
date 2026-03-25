# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
