# obsidian-qdrant-search

MCP server for semantic search and CRUD over Obsidian vaults using Qdrant and local embeddings (BAAI/bge-small-en-v1.5, 384-dim).

## Development

- Python 3.11+ with hatchling build
- Install: `uv sync`
- Run MCP server: `uv run obsidian-qdrant-search` (stdio transport)
- Run indexer: `uv run vault-index [--full]`
- Run tests: `uv run pytest`
- Qdrant auto-starts via Docker when tools are first called

### Project Structure

```
src/vault_search/
├── server.py      # FastMCP server, 27 tool definitions
├── vault_ops.py   # Filesystem operations, log, lint
├── indexer.py      # Markdown parsing, chunking, embedding
├── config.py       # Environment-based configuration
├── path_utils.py   # Path security
├── cli.py          # CLI entry points
├── qdrant.py       # Docker auto-start
└── __main__.py     # CLI entry
```

### Configuration (env vars)

- `VAULT_PATH` -- path to Obsidian vault (default: cwd)
- `QDRANT_URL` -- Qdrant server URL (default: `http://localhost:6333`)
- `COLLECTION_NAME` -- Qdrant collection name (default: `vault_docs`)
- `VAULT_LOG_FILE` -- operation log filename (default: `_log.md`)

## Vault Conventions (LLM Wiki Schema)

### Three-Layer Architecture

- **raw/** -- Immutable source documents. Articles, papers, transcripts, web clips. The LLM reads from these but never modifies them. This is the source of truth.
- **wiki/** -- LLM-maintained pages. Entities, concepts, summaries, syntheses, comparisons. The LLM owns this layer -- it creates, updates, and maintains all pages here. You read it; the LLM writes it.
- **Schema** -- This CLAUDE.md plus the frontmatter conventions below. Tells the LLM how the wiki is structured and what workflows to follow.

### Document Structure Rules

1. **Frontmatter required** on every wiki page:
   ```yaml
   ---
   project: <project-name>
   type: <overview|entity|concept|summary|synthesis|comparison|guide|adr>
   status: <draft|active|review|deprecated>
   tags:
     - <relevant-tags>
   created: <YYYY-MM-DD>
   updated: <YYYY-MM-DD>
   ---
   ```

2. **H1 title + one-paragraph summary** -- the first paragraph after H1 becomes the chunk context header in search results. Make it count.

3. **H2 as primary structure** -- each H2 section becomes a searchable chunk. Keep H2 sections under ~500 words for optimal retrieval.

4. **H3 for subsections** -- only when an H2 section exceeds ~500 words.

5. **Wikilinks mandatory** -- every page must link to related pages via `[[wikilinks]]`. Orphans are bugs.

6. **Related section at bottom** -- bidirectional links: if A links to B, B should link back to A.

### Operations

**Ingest** -- Process a new raw source into the wiki:
1. Read the raw source with `get_file_contents`
2. Discuss key takeaways with the user
3. Create/update wiki pages: entity pages, concept pages, summary
4. Add `[[wikilinks]]` to related existing pages
5. Update existing pages to link back
6. `log_operation("ingest", "<source title>", source="raw/...", pages_touched=[...])`

**Query** -- Search the wiki and optionally file results back:
1. `search_vault` or `simple_search` to find relevant pages
2. `get_chunk_context` to expand promising results
3. Synthesize answer with citations
4. If the answer is reusable, save as a new wiki page
5. `log_operation("query", "<query summary>", pages_touched=[...])`

**Lint** -- Periodic health check:
1. Run `lint_vault` for a comprehensive report
2. Fix issues by priority: critical (broken links) > warning (orphans, missing metadata) > info (stale, stubs)
3. `log_operation("lint", "Health check", summary="Fixed N issues")`

## MCP Tools Reference

### Search

- `search_vault(query, project?, doc_type?, tag?, top_k=5)` -- semantic similarity search
- `simple_search(query, context_length=100)` -- case-insensitive text search
- `get_chunk_context(file_path, chunk_index, window=1)` -- expand context around a result

### Read

- `get_file_contents(filepath)` -- raw file content
- `get_file_metadata(filepath)` -- frontmatter + file stats
- `list_files_in_dir(dirpath="")` -- directory listing
- `list_files_in_vault()` -- vault root listing

### Write

- `create_or_update_file(filepath, content)` -- create or overwrite (auto-mkdir)
- `append_content(filepath, content)` -- append to file
- `patch_content(filepath, operation, target_type, target, content)` -- surgical edit by heading or frontmatter. Use `::` separator for nested headings (e.g. `"Setup::Installation"`)
- `delete_file(filepath, confirm=True)` -- delete (requires confirmation)

### Discover

- `list_projects()` -- indexed projects with counts
- `list_tags()` -- all tags with counts
- `get_recent_changes(days=14, limit=10)` -- recently modified files
- `get_vault_map(max_depth=3)` -- directory tree
- `get_frontmatter_schema()` -- frontmatter field usage

### Graph

- `get_backlinks(filepath)` -- files linking TO this file
- `get_outgoing_links(filepath)` -- files this file links TO
- `find_broken_links()` -- wikilinks to non-existent targets
- `find_orphan_files()` -- files with no incoming links

### Batch

- `batch_update_frontmatter(filter_type, filter_value, field, value, operation="set", confirm=False)` -- bulk metadata updates (preview first)
- `batch_rename_tag(old_tag, new_tag, confirm=False)` -- rename tags across vault

### Log

- `log_operation(operation_type, title, summary?, pages_touched?, source?)` -- record an action
- `get_operation_log(last_n=20, filter_type="")` -- read log history

### Health

- `lint_vault(stale_days=90)` -- comprehensive vault health check

### Maintenance

- `reindex_vault(full=False)` -- reindex vault (incremental by default)
- `migrate_vault(confirm=False)` -- migrate existing vault to LLM Wiki pattern. Creates raw/ and wiki/ dirs, adds missing frontmatter, initializes operation log. Preview first, then `confirm=True` to apply. Idempotent.

## Tips for Agents

- Start with `get_vault_map` to orient before doing anything.
- Use `search_vault` first, fall back to `simple_search` for exact matches.
- Use `patch_content` over full rewrites -- it preserves structure.
- Always preview batch operations (`confirm=False`) before applying.
- Log significant operations with `log_operation`.
- Run `lint_vault` periodically to catch issues early.
- All write operations auto-reindex the modified file.
- For vaults created before v0.4.0, run `migrate_vault` to adopt the LLM Wiki conventions.
