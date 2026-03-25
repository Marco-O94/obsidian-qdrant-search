"""Tests for indexer wikilink functions."""

import pytest

from vault_search import indexer
from vault_search.indexer import extract_wikilinks, resolve_wikilink_target


@pytest.fixture(autouse=True)
def clear_wikilink_cache():
    """Clear the wikilink resolution cache between tests."""
    indexer._wikilink_cache.clear()
    yield
    indexer._wikilink_cache.clear()


class TestExtractWikilinks:
    def test_simple_link(self):
        assert extract_wikilinks("See [[my-note]] for details.") == ["my-note"]

    def test_aliased_link(self):
        assert extract_wikilinks("See [[my-note|display text]] here.") == ["my-note"]

    def test_path_link(self):
        assert extract_wikilinks("Check [[folder/sub/note]] out.") == ["folder/sub/note"]

    def test_heading_anchor(self):
        result = extract_wikilinks("See [[note#heading]] for info.")
        assert result == ["note#heading"]

    def test_multiple_links(self):
        text = "Link to [[note1]] and [[note2]] and [[note1]] again."
        result = extract_wikilinks(text)
        assert result == ["note1", "note2"]  # deduplicated, order preserved

    def test_no_links(self):
        assert extract_wikilinks("No links here.") == []

    def test_mixed_formats(self):
        text = "[[simple]] and [[path/note|alias]] and [[other#section]]"
        result = extract_wikilinks(text)
        assert result == ["simple", "path/note", "other#section"]


class TestResolveWikilinkTarget:
    def test_resolve_by_name(self, tmp_path):
        (tmp_path / "my-note.md").write_text("# My Note")
        result = resolve_wikilink_target("my-note", tmp_path)
        assert result == "my-note.md"

    def test_resolve_by_path(self, tmp_path):
        (tmp_path / "folder").mkdir()
        (tmp_path / "folder" / "note.md").write_text("# Note")
        result = resolve_wikilink_target("folder/note", tmp_path)
        assert result == "folder/note.md"

    def test_resolve_with_md_extension(self, tmp_path):
        (tmp_path / "note.md").write_text("# Note")
        result = resolve_wikilink_target("note.md", tmp_path)
        assert result == "note.md"

    def test_resolve_strips_heading(self, tmp_path):
        (tmp_path / "note.md").write_text("# Note")
        result = resolve_wikilink_target("note#heading", tmp_path)
        assert result == "note.md"

    def test_resolve_by_filename_search(self, tmp_path):
        (tmp_path / "deep").mkdir()
        (tmp_path / "deep" / "nested").mkdir()
        (tmp_path / "deep" / "nested" / "target.md").write_text("# Target")
        result = resolve_wikilink_target("target", tmp_path)
        assert result == "deep/nested/target.md"

    def test_resolve_not_found(self, tmp_path):
        result = resolve_wikilink_target("nonexistent", tmp_path)
        assert result is None

    def test_resolve_empty_after_strip(self, tmp_path):
        result = resolve_wikilink_target("#just-heading", tmp_path)
        assert result is None
