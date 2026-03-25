# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-03-25

### Added

- **File read operations**: `get_file_contents`, `get_file_metadata`, `list_files_in_dir`, `list_files_in_vault`
- **File write operations**: `create_or_update_file`, `append_content`, `patch_content`, `delete_file`
- **Text search**: `simple_search` for case-insensitive keyword search across all markdown files
- **Discovery tools**: `list_tags` (frontmatter + inline tags with counts), `get_recent_changes` (recently modified files)
- **Patch by heading**: targeted modifications to specific markdown sections, supporting nested heading paths (e.g. "Setup/Installation")
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
