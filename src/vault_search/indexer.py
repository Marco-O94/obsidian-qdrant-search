"""Vault indexer: parses Obsidian markdown files and indexes them into Qdrant."""

import hashlib
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import frontmatter
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)
from fastembed import TextEmbedding

from vault_search.config import (
    CHUNK_OVERLAP_TOKENS,
    CHUNK_SIZE_TOKENS,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    QDRANT_URL,
    VAULT_PATH,
    VECTOR_SIZE,
)


def get_model() -> TextEmbedding:
    return TextEmbedding(EMBEDDING_MODEL)


def get_client() -> QdrantClient:
    from vault_search.qdrant import ensure_qdrant
    ensure_qdrant()
    return QdrantClient(url=QDRANT_URL)


def ensure_collection(client: QdrantClient) -> None:
    """Create collection if it doesn't exist."""
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        client.create_payload_index(COLLECTION_NAME, "project", PayloadSchemaType.KEYWORD)
        client.create_payload_index(COLLECTION_NAME, "type", PayloadSchemaType.KEYWORD)
        client.create_payload_index(COLLECTION_NAME, "status", PayloadSchemaType.KEYWORD)
        client.create_payload_index(COLLECTION_NAME, "tags", PayloadSchemaType.KEYWORD)
        client.create_payload_index(COLLECTION_NAME, "chunk_index", PayloadSchemaType.INTEGER)


def find_markdown_files(vault_path: Path) -> list[Path]:
    """Find all .md files in the vault."""
    return sorted(vault_path.rglob("*.md"))


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_wikilinks(text: str) -> str:
    """Replace [[target|alias]] with alias, [[target]] with target name."""
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", lambda m: m.group(1).split("/")[-1], text)
    return text


def extract_first_paragraph(body: str) -> str:
    """Extract the first non-empty paragraph after front matter."""
    lines = []
    in_content = False
    for line in body.split("\n"):
        stripped = line.strip()
        if not in_content:
            if stripped and not stripped.startswith("#"):
                in_content = True
                lines.append(stripped)
            elif stripped.startswith("# "):
                continue
        else:
            if stripped == "":
                break
            if stripped.startswith("#"):
                break
            lines.append(stripped)
    return " ".join(lines)


def extract_doc_title(body: str) -> str:
    """Extract the first H1 heading."""
    for line in body.split("\n"):
        if line.strip().startswith("# ") and not line.strip().startswith("## "):
            return line.strip().lstrip("# ").strip()
    return ""


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def split_into_blocks(text: str) -> list[str]:
    """Split markdown text into atomic blocks (tables, code fences, paragraphs).

    Never breaks inside a table or fenced code block.
    """
    blocks = []
    current_lines: list[str] = []
    in_code_fence = False
    in_table = False

    for line in text.split("\n"):
        stripped = line.strip()

        # Toggle code fence state
        if stripped.startswith("```"):
            if in_code_fence:
                # End of code block
                current_lines.append(line)
                blocks.append("\n".join(current_lines))
                current_lines = []
                in_code_fence = False
                continue
            else:
                # Start of code block — flush any pending paragraph
                if current_lines:
                    blocks.append("\n".join(current_lines))
                    current_lines = []
                in_code_fence = True
                current_lines.append(line)
                continue

        if in_code_fence:
            current_lines.append(line)
            continue

        # Table detection: lines starting with |
        is_table_line = stripped.startswith("|") and stripped.endswith("|")
        if is_table_line:
            if not in_table:
                # Flush pending paragraph before table starts
                if current_lines:
                    blocks.append("\n".join(current_lines))
                    current_lines = []
                in_table = True
            current_lines.append(line)
            continue

        if in_table:
            # Table ended — flush it
            blocks.append("\n".join(current_lines))
            current_lines = []
            in_table = False

        # Empty line separates paragraphs
        if stripped == "":
            if current_lines:
                blocks.append("\n".join(current_lines))
                current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        blocks.append("\n".join(current_lines))

    return [b for b in blocks if b.strip()]


def sliding_window_chunks(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    """Split text into chunks respecting markdown block boundaries.

    Groups atomic blocks (tables, code fences, paragraphs) together
    without breaking them. Falls back to hard split only for single
    blocks that exceed the token limit.
    """
    blocks = split_into_blocks(text)
    chunks = []
    current_parts: list[str] = []
    current_tokens = 0

    for block in blocks:
        block_tokens = estimate_tokens(block)

        # Single block exceeds limit — must include it as-is
        if block_tokens > max_tokens:
            if current_parts:
                chunks.append("\n\n".join(current_parts))
                current_parts = []
                current_tokens = 0
            chunks.append(block)
            continue

        # Adding this block would exceed limit — flush and start new chunk
        if current_tokens + block_tokens > max_tokens and current_parts:
            chunks.append("\n\n".join(current_parts))
            # Overlap: keep last block(s) up to overlap_tokens
            overlap_parts: list[str] = []
            overlap_tokens_count = 0
            for part in reversed(current_parts):
                part_tokens = estimate_tokens(part)
                if overlap_tokens_count + part_tokens > overlap_tokens:
                    break
                overlap_parts.insert(0, part)
                overlap_tokens_count += part_tokens
            current_parts = overlap_parts
            current_tokens = overlap_tokens_count

        current_parts.append(block)
        current_tokens += block_tokens

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks if chunks else [text]


def chunk_by_headings(body: str, level: str = "## ") -> list[tuple[str, str]]:
    """Split markdown body by heading level. Returns list of (heading, content)."""
    sections = []
    current_heading = ""
    current_lines = []

    for line in body.split("\n"):
        if line.strip().startswith(level) and not line.strip().startswith(level + "#"):
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line.strip().lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))

    return sections


def chunk_document(body: str) -> list[dict]:
    """Chunk a markdown document using heading-based strategy.

    Returns list of dicts with 'heading' and 'content' keys.
    """
    doc_title = extract_doc_title(body)
    first_para = extract_first_paragraph(body)

    # Remove the H1 line from body for chunking
    body_no_h1 = re.sub(r"^#\s+[^\n]+\n?", "", body, count=1).strip()

    h2_sections = chunk_by_headings(body_no_h1, "## ")

    chunks = []

    for heading, content in h2_sections:
        content = resolve_wikilinks(content)
        if not content.strip():
            continue

        if estimate_tokens(content) <= CHUNK_SIZE_TOKENS:
            chunks.append({"heading": heading, "content": content})
        else:
            # Try splitting on H3
            h3_sections = chunk_by_headings(content, "### ")
            for sub_heading, sub_content in h3_sections:
                sub_content = sub_content.strip()
                if not sub_content:
                    continue
                full_heading = f"{heading} > {sub_heading}" if heading and sub_heading else (heading or sub_heading)

                if estimate_tokens(sub_content) <= CHUNK_SIZE_TOKENS:
                    chunks.append({"heading": full_heading, "content": sub_content})
                else:
                    # Fallback: sliding window
                    for i, window in enumerate(
                        sliding_window_chunks(sub_content, CHUNK_SIZE_TOKENS, CHUNK_OVERLAP_TOKENS)
                    ):
                        chunks.append({
                            "heading": f"{full_heading} (part {i + 1})" if i > 0 else full_heading,
                            "content": window,
                        })

    # If no H2 sections found, treat entire body as one chunk
    if not chunks and body_no_h1.strip():
        content = resolve_wikilinks(body_no_h1)
        if estimate_tokens(content) <= CHUNK_SIZE_TOKENS:
            chunks.append({"heading": "", "content": content})
        else:
            for i, window in enumerate(
                sliding_window_chunks(content, CHUNK_SIZE_TOKENS, CHUNK_OVERLAP_TOKENS)
            ):
                chunks.append({"heading": f"(part {i + 1})" if i > 0 else "", "content": window})

    # Prepend context header to each chunk
    for chunk in chunks:
        header_parts = []
        if doc_title:
            header_parts.append(f"[{doc_title}]")
        if chunk["heading"]:
            header_parts.append(f"> {chunk['heading']}")
        header = " ".join(header_parts)

        if first_para and first_para not in chunk["content"]:
            chunk["content"] = f"{header}\n{first_para}\n---\n{chunk['content']}"
        elif header:
            chunk["content"] = f"{header}\n---\n{chunk['content']}"

    return chunks


def extract_project_name(file_path: Path, vault_path: Path) -> str:
    """Extract project name from file path relative to vault."""
    rel = file_path.relative_to(vault_path)
    parts = rel.parts
    return parts[0] if parts else "unknown"


def get_existing_hashes(client: QdrantClient) -> dict[str, str]:
    """Get file_path -> file_hash mapping for all indexed documents."""
    hashes = {}
    offset = None
    while True:
        results = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=None,
            limit=100,
            offset=offset,
            with_payload=["file_path", "file_hash"],
            with_vectors=False,
        )
        points, next_offset = results
        for point in points:
            fp = point.payload.get("file_path", "")
            fh = point.payload.get("file_hash", "")
            if fp and fh:
                hashes[fp] = fh
        if next_offset is None:
            break
        offset = next_offset
    return hashes


def delete_file_points(client: QdrantClient, file_path: str) -> None:
    """Delete all points for a given file_path."""
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[FieldCondition(key="file_path", match=MatchValue(value=file_path))]
        ),
    )


def index_single_file(rel_path: str) -> dict:
    """Reindex a single file after modification.

    Args:
        rel_path: File path relative to vault root.

    Returns:
        Dict with file and chunks_indexed count.
    """
    client = get_client()
    model = get_model()
    ensure_collection(client)

    vault_path = VAULT_PATH
    abs_path = vault_path / rel_path

    # Delete old points for this file
    delete_file_points(client, rel_path)

    if not abs_path.is_file():
        return {"file": rel_path, "chunks_indexed": 0}

    post = frontmatter.load(str(abs_path))
    metadata = post.metadata
    body = post.content

    if not body.strip():
        return {"file": rel_path, "chunks_indexed": 0}

    doc_title = extract_doc_title(body)
    project = extract_project_name(abs_path, vault_path)
    chunks = chunk_document(body)
    fhash = file_hash(abs_path)
    now = datetime.now(timezone.utc).isoformat()

    chunk_texts = [chunk["content"] for chunk in chunks]
    embeddings = [v.tolist() for v in model.embed(chunk_texts)] if chunk_texts else []

    points = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{rel_path}:{i}"))
        points.append(PointStruct(
            id=point_id,
            vector=embedding,
            payload={
                "file_path": rel_path,
                "project": project,
                "doc_title": doc_title,
                "scope": metadata.get("scope", ""),
                "type": metadata.get("type", ""),
                "status": metadata.get("status", ""),
                "tags": metadata.get("tags", []),
                "chunk_index": i,
                "chunk_heading": chunk["heading"],
                "chunk_content": chunk["content"],
                "file_hash": fhash,
                "indexed_at": now,
            },
        ))

    if points:
        client.upsert(collection_name=COLLECTION_NAME, points=points)

    return {"file": rel_path, "chunks_indexed": len(points)}


def index_vault(full: bool = False) -> dict:
    """Index the vault into Qdrant.

    Args:
        full: If True, delete all and reindex. If False, only index changed files.

    Returns:
        Report dict with stats.
    """
    start_time = time.time()
    client = get_client()
    model = get_model()

    if full:
        # Delete collection and recreate
        collections = [c.name for c in client.get_collections().collections]
        if COLLECTION_NAME in collections:
            client.delete_collection(COLLECTION_NAME)
    ensure_collection(client)

    vault_path = VAULT_PATH
    md_files = find_markdown_files(vault_path)

    existing_hashes = {} if full else get_existing_hashes(client)
    current_file_paths = set()

    files_indexed = 0
    files_skipped = 0
    total_chunks = 0
    points_batch = []

    for md_file in md_files:
        rel_path = str(md_file.relative_to(vault_path))
        current_file_paths.add(rel_path)
        fhash = file_hash(md_file)

        # Skip unchanged files
        if not full and rel_path in existing_hashes and existing_hashes[rel_path] == fhash:
            files_skipped += 1
            continue

        # Parse file
        post = frontmatter.load(str(md_file))
        metadata = post.metadata
        body = post.content

        if not body.strip():
            files_skipped += 1
            continue

        # Delete old points for this file
        if not full and rel_path in existing_hashes:
            delete_file_points(client, rel_path)

        doc_title = extract_doc_title(body)
        project = extract_project_name(md_file, vault_path)
        chunks = chunk_document(body)

        now = datetime.now(timezone.utc).isoformat()

        # Batch embed all chunks for this file at once
        chunk_texts = [chunk["content"] for chunk in chunks]
        embeddings = [v.tolist() for v in model.embed(chunk_texts)] if chunk_texts else []

        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{rel_path}:{i}"))

            point = PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "file_path": rel_path,
                    "project": project,
                    "doc_title": doc_title,
                    "scope": metadata.get("scope", ""),
                    "type": metadata.get("type", ""),
                    "status": metadata.get("status", ""),
                    "tags": metadata.get("tags", []),
                    "chunk_index": i,
                    "chunk_heading": chunk["heading"],
                    "chunk_content": chunk["content"],
                    "file_hash": fhash,
                    "indexed_at": now,
                },
            )
            points_batch.append(point)
            total_chunks += 1

        files_indexed += 1

        # Batch upsert every 50 points
        if len(points_batch) >= 50:
            client.upsert(collection_name=COLLECTION_NAME, points=points_batch)
            points_batch = []

    # Upsert remaining
    if points_batch:
        client.upsert(collection_name=COLLECTION_NAME, points=points_batch)

    # Remove points for deleted files (incremental only)
    if not full:
        for old_path in set(existing_hashes.keys()) - current_file_paths:
            delete_file_points(client, old_path)

    elapsed = time.time() - start_time

    return {
        "files_indexed": files_indexed,
        "files_skipped": files_skipped,
        "total_chunks": total_chunks,
        "total_files": len(md_files),
        "elapsed_seconds": round(elapsed, 2),
        "mode": "full" if full else "incremental",
    }
