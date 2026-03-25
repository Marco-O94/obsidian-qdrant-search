---
description: Search and manage the Obsidian vault using semantic search and CRUD operations via Qdrant MCP server.
---

# Vault Search & Management

You have access to the `obsidian-qdrant-search` MCP server which provides semantic search and full CRUD operations over the Obsidian vault.

## Available MCP tools

### Search

#### search_vault
Primary semantic search. Always start here for finding documentation by meaning.

```
search_vault(query, project?, doc_type?, tag?, top_k?)
```

- `query`: Natural language search query
- `project`: Filter by project (e.g. "core", "sentinel-ai", "internal-dashboard-next")
- `doc_type`: Filter by type (e.g. "api-contract", "service-layer", "data-model", "overview")
- `tag`: Filter by frontmatter tag (e.g. "kubernetes", "database", "security")
- `top_k`: Number of results (default 5)

#### simple_search
Case-insensitive text search across all `.md` files. Use when you need exact keyword matches.

```
simple_search(query, context_length?)
```

#### get_chunk_context
Expand context around a search result by fetching adjacent chunks.

```
get_chunk_context(file_path, chunk_index, window?)
```

### Read

#### get_file_contents
Read the raw content of any vault file.

```
get_file_contents(filepath)
```

#### get_file_metadata
Get frontmatter, tags, and file stats (size, modified date).

```
get_file_metadata(filepath)
```

#### list_files_in_dir / list_files_in_vault
List files and subdirectories. Use `list_files_in_vault` for root, `list_files_in_dir` for a specific directory.

```
list_files_in_dir(dirpath?)
list_files_in_vault()
```

### Write

#### create_or_update_file
Create a new file or overwrite an existing one. Parent directories are created automatically.

```
create_or_update_file(filepath, content)
```

#### append_content
Append content to a file (creates if missing).

```
append_content(filepath, content)
```

#### patch_content
Targeted modification of a specific section by heading or frontmatter field.

```
patch_content(filepath, operation, target_type, target, content)
```

- `operation`: "append", "prepend", or "replace"
- `target_type`: "heading" or "frontmatter"
- `target`: Heading text (e.g. "Setup" or nested "Setup::Installation") or frontmatter field name. Use '::' to separate nested heading levels (not '/' which conflicts with URL paths in headings)

#### delete_file
Delete a file. Requires `confirm=True` as safety guard.

```
delete_file(filepath, confirm=True)
```

### Discover

#### list_projects
Lists all indexed projects with file and chunk counts.

#### list_tags
Lists all tags (frontmatter + inline) with occurrence counts.

#### get_recent_changes
Returns recently modified `.md` files sorted by date.

```
get_recent_changes(days?, limit?)
```

#### get_vault_map
Shows directory hierarchy with file counts and types. Use to understand vault organization.

```
get_vault_map(max_depth?)
```

#### get_frontmatter_schema
Lists all frontmatter fields used across the vault with types, frequency, and examples.

### Graph

#### get_backlinks
Find all files that link TO a given file via wikilinks.

```
get_backlinks(filepath)
```

#### get_outgoing_links
List all files a document links to via wikilinks.

```
get_outgoing_links(filepath)
```

#### find_broken_links
Find wikilinks pointing to non-existent files. No parameters.

#### find_orphan_files
Find files with no incoming wikilinks. No parameters.

### Batch

#### batch_update_frontmatter
Update a frontmatter field across files filtered by project, tag, or glob.

```
batch_update_frontmatter(filter_type, filter_value, field, value, operation?, confirm?)
```

- `filter_type`: "project", "tag", or "glob"
- `operation`: "set" (default), "append", or "remove"
- `confirm`: False returns preview, True applies changes

#### batch_rename_tag
Rename a tag across all files (frontmatter + inline #tags).

```
batch_rename_tag(old_tag, new_tag, confirm?)
```

### Maintenance

#### reindex_vault
Re-indexes the vault. Use `full=true` after major changes or after upgrading to index wikilink data.

## Workflow

1. **Orient** with `get_vault_map` to understand vault structure
2. **Search** with `search_vault` using a natural language query
3. **Evaluate** results — scores >0.7 are strong, 0.5-0.7 moderate
4. **Expand** context with `get_chunk_context` if a result is promising but incomplete
5. **Navigate** with `get_backlinks`/`get_outgoing_links` to find related documents
6. **Read** full files with `get_file_contents` when you need the complete document
7. **Write** using `create_or_update_file`, `append_content`, or `patch_content`
8. **Maintain** with `find_broken_links`, `find_orphan_files` to keep vault healthy
9. **Batch** with `batch_update_frontmatter` or `batch_rename_tag` for bulk changes

All write operations automatically reindex the modified file in Qdrant (best-effort).

## Tips

- Rephrase technical jargon into natural language for better semantic matches
- Use `project` filter when you know which project the user is asking about
- Use `simple_search` for exact keyword matches when semantic search returns low scores
- Use `patch_content` with heading targeting to surgically edit specific sections
- Use `get_vault_map` first to understand how the vault is organized
- Use `get_frontmatter_schema` to discover available metadata fields for filtering
- Use `get_backlinks` to understand how documents relate to each other
- Batch operations always preview first (confirm=False) — review before applying
- All file paths are relative to the vault root

## User query

$ARGUMENTS
