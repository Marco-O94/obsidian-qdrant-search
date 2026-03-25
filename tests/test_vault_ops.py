"""Tests for vault_ops module."""

from unittest.mock import patch
import pytest

from vault_search import vault_ops


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """Set up a temporary vault directory and patch VAULT_PATH."""
    monkeypatch.setattr(vault_ops, "VAULT_PATH", tmp_path)

    # Create some sample files
    (tmp_path / "note1.md").write_text(
        "---\ntags:\n  - python\n  - testing\n---\n# Note One\n\nHello world.\n"
    )
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "note2.md").write_text(
        "---\ntags:\n  - python\n---\n# Note Two\n\n## Setup\n\nSetup content here.\n\n## Usage\n\nUsage content here.\n"
    )
    return tmp_path


@pytest.fixture
def no_reindex(monkeypatch):
    """Disable auto-reindex for write tests."""
    monkeypatch.setattr(vault_ops, "_trigger_reindex", lambda *a, **kw: None)


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


class TestGetFileContents:
    def test_read_existing(self, vault):
        content = vault_ops.get_file_contents("note1.md")
        assert "Hello world." in content

    def test_read_nested(self, vault):
        content = vault_ops.get_file_contents("subdir/note2.md")
        assert "Note Two" in content

    def test_file_not_found(self, vault):
        with pytest.raises(FileNotFoundError):
            vault_ops.get_file_contents("nonexistent.md")

    def test_path_traversal(self, vault):
        with pytest.raises(ValueError, match="Path traversal"):
            vault_ops.get_file_contents("../outside.md")


class TestGetFileMetadata:
    def test_metadata(self, vault):
        meta = vault_ops.get_file_metadata("note1.md")
        assert meta["path"] == "note1.md"
        assert "python" in meta["tags"]
        assert "testing" in meta["tags"]
        assert meta["frontmatter"]["tags"] == ["python", "testing"]
        assert meta["stat"]["size"] > 0


class TestListFiles:
    def test_list_root(self, vault):
        entries = vault_ops.list_files_in_vault()
        assert "note1.md" in entries
        assert "subdir/" in entries

    def test_list_subdir(self, vault):
        entries = vault_ops.list_files_in_dir("subdir")
        assert any("note2.md" in e for e in entries)

    def test_not_a_directory(self, vault):
        with pytest.raises(NotADirectoryError):
            vault_ops.list_files_in_dir("note1.md")


class TestSimpleSearch:
    def test_search_found(self, vault):
        results = vault_ops.simple_search("Hello world")
        assert len(results) == 1
        assert results[0]["filepath"] == "note1.md"

    def test_search_case_insensitive(self, vault):
        results = vault_ops.simple_search("hello WORLD")
        assert len(results) == 1

    def test_search_no_match(self, vault):
        results = vault_ops.simple_search("zzz_nonexistent_zzz")
        assert len(results) == 0

    def test_search_multiple_files(self, vault):
        results = vault_ops.simple_search("Note")
        assert len(results) == 2


class TestGetRecentChanges:
    def test_recent(self, vault):
        results = vault_ops.get_recent_changes(days=1, limit=10)
        assert len(results) >= 2
        assert all("filepath" in r for r in results)

    def test_limit(self, vault):
        results = vault_ops.get_recent_changes(days=1, limit=1)
        assert len(results) == 1


class TestListTags:
    def test_tags(self, vault):
        tags = vault_ops.list_tags()
        assert "python" in tags
        assert tags["python"] == 2  # appears in both files
        assert "testing" in tags
        assert tags["testing"] == 1


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


class TestCreateOrUpdateFile:
    def test_create_new(self, vault, no_reindex):
        result = vault_ops.create_or_update_file("new.md", "# New Note\n\nContent.")
        assert result["created"] is True
        assert (vault / "new.md").read_text() == "# New Note\n\nContent."

    def test_update_existing(self, vault, no_reindex):
        result = vault_ops.create_or_update_file("note1.md", "Replaced.")
        assert result["created"] is False
        assert (vault / "note1.md").read_text() == "Replaced."

    def test_create_nested(self, vault, no_reindex):
        result = vault_ops.create_or_update_file("deep/nested/file.md", "Deep content.")
        assert result["created"] is True
        assert (vault / "deep" / "nested" / "file.md").read_text() == "Deep content."

    def test_path_traversal(self, vault, no_reindex):
        with pytest.raises(ValueError, match="Path traversal"):
            vault_ops.create_or_update_file("../../evil.md", "bad")


class TestAppendContent:
    def test_append_existing(self, vault, no_reindex):
        vault_ops.append_content("note1.md", "\nAppended line.")
        content = (vault / "note1.md").read_text()
        assert content.endswith("\nAppended line.")

    def test_append_creates_file(self, vault, no_reindex):
        vault_ops.append_content("new_append.md", "First content.")
        assert (vault / "new_append.md").read_text() == "First content."

    def test_newline_separator(self, vault, no_reindex):
        (vault / "no_newline.md").write_text("No trailing newline")
        vault_ops.append_content("no_newline.md", "Appended.")
        content = (vault / "no_newline.md").read_text()
        assert content == "No trailing newline\nAppended."


class TestDeleteFile:
    def test_delete_with_confirm(self, vault, no_reindex):
        result = vault_ops.delete_file("note1.md", confirm=True)
        assert result["deleted"] is True
        assert not (vault / "note1.md").exists()

    def test_delete_without_confirm(self, vault, no_reindex):
        with pytest.raises(ValueError, match="confirm=True"):
            vault_ops.delete_file("note1.md")

    def test_delete_nonexistent(self, vault, no_reindex):
        with pytest.raises(FileNotFoundError):
            vault_ops.delete_file("nope.md", confirm=True)


# ---------------------------------------------------------------------------
# Patch operations
# ---------------------------------------------------------------------------


class TestPatchHeading:
    def test_append_to_heading(self, vault, no_reindex):
        vault_ops.patch_content(
            "subdir/note2.md", "append", "heading", "Setup", "\nAppended to setup."
        )
        content = (vault / "subdir" / "note2.md").read_text()
        assert "Appended to setup." in content
        # Should be before Usage section
        setup_idx = content.index("Appended to setup.")
        usage_idx = content.index("## Usage")
        assert setup_idx < usage_idx

    def test_prepend_to_heading(self, vault, no_reindex):
        vault_ops.patch_content(
            "subdir/note2.md", "prepend", "heading", "Usage", "Prepended line.\n"
        )
        content = (vault / "subdir" / "note2.md").read_text()
        assert "Prepended line." in content
        usage_heading_idx = content.index("## Usage")
        prepend_idx = content.index("Prepended line.")
        assert prepend_idx > usage_heading_idx

    def test_replace_heading(self, vault, no_reindex):
        vault_ops.patch_content(
            "subdir/note2.md", "replace", "heading", "Setup", "Replaced content."
        )
        content = (vault / "subdir" / "note2.md").read_text()
        assert "Replaced content." in content
        assert "Setup content here." not in content

    def test_nested_heading_path(self, vault, no_reindex):
        # Create a file with nested headings
        (vault / "nested.md").write_text(
            "# Doc\n\n## Setup\n\n### Installation\n\nInstall steps.\n\n### Configuration\n\nConfig steps.\n\n## Usage\n\nUsage info.\n"
        )
        vault_ops.patch_content(
            "nested.md", "replace", "heading", "Setup/Installation", "New install steps."
        )
        content = (vault / "nested.md").read_text()
        assert "New install steps." in content
        assert "Install steps." not in content
        # Configuration section should be unchanged
        assert "Config steps." in content

    def test_heading_not_found(self, vault, no_reindex):
        with pytest.raises(ValueError, match="Heading not found"):
            vault_ops.patch_content(
                "subdir/note2.md", "append", "heading", "Nonexistent", "content"
            )

    def test_invalid_operation(self, vault, no_reindex):
        with pytest.raises(ValueError, match="Invalid operation"):
            vault_ops.patch_content(
                "subdir/note2.md", "invalid", "heading", "Setup", "content"
            )


class TestPatchFrontmatter:
    def test_replace_field(self, vault, no_reindex):
        vault_ops.patch_content(
            "note1.md", "replace", "frontmatter", "tags", "[go, rust]"
        )
        content = (vault / "note1.md").read_text()
        assert "go" in content
        assert "rust" in content

    def test_append_to_list(self, vault, no_reindex):
        vault_ops.patch_content(
            "note1.md", "append", "frontmatter", "tags", "new-tag"
        )
        import frontmatter
        post = frontmatter.load(str(vault / "note1.md"))
        assert "new-tag" in post.metadata["tags"]

    def test_create_new_field(self, vault, no_reindex):
        vault_ops.patch_content(
            "note1.md", "replace", "frontmatter", "status", "draft"
        )
        import frontmatter
        post = frontmatter.load(str(vault / "note1.md"))
        assert post.metadata["status"] == "draft"
