# AGENTS.md -- obsidian-qdrant-search

This project is an MCP server and CLI for managing Obsidian vaults with semantic search backed by Qdrant and local embeddings.

## CLI Commands

```bash
# MCP server (stdio transport)
uv run obsidian-qdrant-search

# Indexer
uv run vault-index [--full]

# CLI tools (human and agent friendly, JSON output with --json)
uv run vault-search-search "query" [--project X] [--top-k 5] [--json]
uv run vault-search-read <filepath>
uv run vault-search-write <filepath> --content "..."
uv run vault-search-lint [--stale-days 90] [--json]
uv run vault-search-log <type> "<title>" [--summary "..."] [--source "..."]
uv run vault-search-log --read [--last 20] [--filter <type>] [--json]
uv run vault-search-map [--depth 3] [--json]
uv run vault-search-migrate [--apply] [--json]
```

## Vault Conventions

### Three-Layer Architecture

- **raw/** -- Immutable source documents. Articles, papers, transcripts, web clips. The LLM reads from these but never modifies them. This is the source of truth.
- **wiki/** -- LLM-maintained pages. Entities, concepts, summaries, syntheses, comparisons. The LLM owns this layer -- it creates, updates, and maintains all pages here. You read it; the LLM writes it.
- **Schema** -- CLAUDE.md plus the frontmatter conventions below. Tells the LLM how the wiki is structured and what workflows to follow.

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
1. Read the raw source
2. Discuss key takeaways with the user
3. Create/update wiki pages: entity pages, concept pages, summary
4. Add `[[wikilinks]]` to related existing pages
5. Update existing pages to link back
6. Log the operation: `uv run vault-search-log ingest "<source title>" --source "raw/..."`

**Query** -- Search the wiki and optionally file results back:
1. Search: `uv run vault-search-search "<query>" --json`
2. Read promising results: `uv run vault-search-read <filepath>`
3. Synthesize answer with citations
4. If the answer is reusable, save as a new wiki page
5. Log: `uv run vault-search-log query "<query summary>"`

**Lint** -- Periodic health check:
1. Run: `uv run vault-search-lint --json`
2. Fix issues by priority: critical (broken links) > warning (orphans, missing metadata) > info (stale, stubs)
3. Log: `uv run vault-search-log lint "Health check" --summary "Fixed N issues"`

**Migrate** -- Upgrade existing vault to LLM Wiki pattern:
1. Preview: `uv run vault-search-migrate` (assisted mode, classifies and moves files)
2. Apply: `uv run vault-search-migrate --apply`
3. Manual mode (no file moves): `uv run vault-search-migrate --mode manual --apply`
4. Assisted mode classifies files as raw/wiki/unknown, moves them to correct dirs, updates wikilinks
5. Idempotent -- safe to run multiple times

## Development

- Python 3.11+, hatchling build
- Install: `uv sync`
- Tests: `uv run pytest`
- Source: `src/vault_search/`
- Embedding model: BAAI/bge-small-en-v1.5 (384-dim, local)
- Qdrant auto-starts via Docker when tools are first called

### Configuration (env vars)

- `VAULT_PATH` -- path to Obsidian vault (default: cwd)
- `QDRANT_URL` -- Qdrant server URL (default: `http://localhost:6333`)
- `COLLECTION_NAME` -- Qdrant collection name (default: `vault_docs`)
- `VAULT_LOG_FILE` -- operation log filename (default: `_log.md`)
