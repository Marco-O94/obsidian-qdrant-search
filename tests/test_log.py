"""Tests for vault_ops log_operation and get_operation_log."""

import pytest

from vault_search import vault_ops


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """Set up a temporary vault directory and patch VAULT_PATH and LOG_FILE."""
    monkeypatch.setattr(vault_ops, "VAULT_PATH", tmp_path)
    monkeypatch.setattr(vault_ops, "LOG_FILE", "_log.md")
    return tmp_path


# ---------------------------------------------------------------------------
# log_operation
# ---------------------------------------------------------------------------


class TestLogOperation:
    def test_creates_log_file_on_first_write(self, vault):
        vault_ops.log_operation("ingest", "First entry")
        log_path = vault / "_log.md"
        assert log_path.exists()
        content = log_path.read_text()
        assert "# Operation Log" in content
        assert "First entry" in content

    def test_appends_to_existing_log(self, vault):
        vault_ops.log_operation("ingest", "Entry one")
        vault_ops.log_operation("query", "Entry two")
        content = (vault / "_log.md").read_text()
        assert "Entry one" in content
        assert "Entry two" in content

    def test_entry_format(self, vault):
        vault_ops.log_operation("lint", "Check vault")
        content = (vault / "_log.md").read_text()
        # Entry should contain the timestamp pattern, type, and title
        assert "lint | Check vault" in content
        # Timestamp bracket pattern: [YYYY-MM-DD HH:MM]
        assert "## [" in content

    def test_with_source_and_pages(self, vault):
        vault_ops.log_operation(
            "ingest",
            "Import docs",
            summary="Imported 3 files",
            pages_touched=["a.md", "b.md"],
            source="upload.zip",
        )
        content = (vault / "_log.md").read_text()
        assert "Source: upload.zip" in content
        assert "Pages touched: a.md, b.md" in content
        assert "Summary: Imported 3 files" in content

    def test_returns_path_and_entry(self, vault):
        result = vault_ops.log_operation("query", "Search test")
        assert result["path"] == "_log.md"
        assert "query | Search test" in result["entry"]


# ---------------------------------------------------------------------------
# get_operation_log
# ---------------------------------------------------------------------------


class TestGetOperationLog:
    def test_returns_empty_when_no_log(self, vault):
        entries = vault_ops.get_operation_log()
        assert entries == []

    def test_reads_entries(self, vault):
        vault_ops.log_operation("ingest", "First")
        vault_ops.log_operation("query", "Second")
        entries = vault_ops.get_operation_log()
        assert len(entries) == 2
        assert entries[0]["operation_type"] == "ingest"
        assert entries[0]["title"] == "First"
        assert entries[1]["operation_type"] == "query"
        assert entries[1]["title"] == "Second"

    def test_last_n_limit(self, vault):
        for i in range(5):
            vault_ops.log_operation("ingest", f"Entry {i}")
        entries = vault_ops.get_operation_log(last_n=2)
        assert len(entries) == 2
        assert entries[0]["title"] == "Entry 3"
        assert entries[1]["title"] == "Entry 4"

    def test_filter_by_type(self, vault):
        vault_ops.log_operation("ingest", "Import")
        vault_ops.log_operation("query", "Search")
        vault_ops.log_operation("ingest", "Import again")
        entries = vault_ops.get_operation_log(filter_type="ingest")
        assert len(entries) == 2
        assert all(e["operation_type"] == "ingest" for e in entries)

    def test_filter_case_insensitive(self, vault):
        vault_ops.log_operation("Ingest", "Capitalized")
        entries = vault_ops.get_operation_log(filter_type="ingest")
        assert len(entries) == 1
        assert entries[0]["title"] == "Capitalized"
