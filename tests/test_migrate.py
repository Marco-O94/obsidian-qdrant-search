"""Tests for vault migration module."""

import frontmatter
import pytest

from vault_search import indexer, migrate, vault_ops


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """Set up a temporary vault directory and patch module-level paths."""
    monkeypatch.setattr(migrate, "VAULT_PATH", tmp_path)
    monkeypatch.setattr(migrate, "LOG_FILE", "_log.md")
    monkeypatch.setattr(vault_ops, "_trigger_reindex", lambda *a, **kw: None)
    monkeypatch.setattr(vault_ops, "VAULT_PATH", tmp_path)
    monkeypatch.setattr(vault_ops, "LOG_FILE", "_log.md")
    indexer._wikilink_cache.clear()
    return tmp_path


# ---------------------------------------------------------------------------
# _classify_file
# ---------------------------------------------------------------------------


class TestClassifyFile:
    def test_classify_with_type_field(self, vault):
        """File with type in frontmatter is classified as wiki."""
        # Arrange
        md = vault / "overview.md"
        md.write_text("---\ntype: overview\n---\n# Overview\n\nSome content.\n")

        # Act
        result = migrate._classify_file(md, vault)

        # Assert
        assert result == "wiki"

    def test_classify_with_wikilinks(self, vault):
        """File with wikilinks but no type field is classified as wiki."""
        # Arrange
        md = vault / "linked.md"
        md.write_text("---\ntags: []\n---\n# Linked\n\nSee [[other-note]] for more.\n")

        # Act
        result = migrate._classify_file(md, vault)

        # Assert
        assert result == "wiki"

    def test_classify_bare_file(self, vault):
        """File with no frontmatter and no links is classified as raw."""
        # Arrange
        md = vault / "plain.md"
        md.write_text("Just plain text with no frontmatter.\n")

        # Act
        result = migrate._classify_file(md, vault)

        # Assert
        assert result == "raw"

    def test_classify_file_in_raw_dir(self, vault):
        """File inside raw/ directory is classified as raw."""
        # Arrange
        (vault / "raw").mkdir()
        md = vault / "raw" / "source.md"
        md.write_text("---\ntype: guide\n---\n# Source\n\nContent.\n")

        # Act
        result = migrate._classify_file(md, vault)

        # Assert
        assert result == "raw"

    def test_classify_file_in_wiki_dir(self, vault):
        """File inside wiki/ directory is classified as wiki."""
        # Arrange
        (vault / "wiki").mkdir()
        md = vault / "wiki" / "page.md"
        md.write_text("No frontmatter at all.\n")

        # Act
        result = migrate._classify_file(md, vault)

        # Assert
        assert result == "wiki"


# ---------------------------------------------------------------------------
# _check_directory_structure
# ---------------------------------------------------------------------------


class TestCheckDirectoryStructure:
    def test_missing_dirs(self, vault):
        """Empty vault reports both raw/ and wiki/ as needing creation."""
        # Act
        results = migrate._check_directory_structure(vault)

        # Assert
        assert len(results) == 2
        raw_entry = next(r for r in results if r["path"] == "raw/")
        wiki_entry = next(r for r in results if r["path"] == "wiki/")
        assert raw_entry["exists"] is False
        assert wiki_entry["exists"] is False

    def test_existing_dirs(self, vault):
        """When raw/ and wiki/ exist, both report exists=True."""
        # Arrange
        (vault / "raw").mkdir()
        (vault / "wiki").mkdir()

        # Act
        results = migrate._check_directory_structure(vault)

        # Assert
        raw_entry = next(r for r in results if r["path"] == "raw/")
        wiki_entry = next(r for r in results if r["path"] == "wiki/")
        assert raw_entry["exists"] is True
        assert wiki_entry["exists"] is True

    def test_partial_dirs(self, vault):
        """When only raw/ exists, raw is True and wiki is False."""
        # Arrange
        (vault / "raw").mkdir()

        # Act
        results = migrate._check_directory_structure(vault)

        # Assert
        raw_entry = next(r for r in results if r["path"] == "raw/")
        wiki_entry = next(r for r in results if r["path"] == "wiki/")
        assert raw_entry["exists"] is True
        assert wiki_entry["exists"] is False


# ---------------------------------------------------------------------------
# _check_log_file
# ---------------------------------------------------------------------------


class TestCheckLogFile:
    def test_missing_log(self, vault):
        """Missing _log.md returns a change dict."""
        # Act
        result = migrate._check_log_file(vault)

        # Assert
        assert result is not None
        assert result["type"] == "create_log"
        assert result["path"] == "_log.md"
        assert result["exists"] is False

    def test_existing_log(self, vault):
        """Existing _log.md returns None (no change needed)."""
        # Arrange
        (vault / "_log.md").write_text("# Operation Log\n")

        # Act
        result = migrate._check_log_file(vault)

        # Assert
        assert result is None


# ---------------------------------------------------------------------------
# _check_frontmatter
# ---------------------------------------------------------------------------


class TestCheckFrontmatter:
    def test_detects_all_missing(self, vault):
        """File with no frontmatter lists all 6 required fields as missing."""
        # Arrange
        (vault / "bare.md").write_text("# Bare Note\n\nNo frontmatter.\n")

        # Act
        changes = migrate._check_frontmatter(vault)

        # Assert
        assert len(changes) == 1
        change = changes[0]
        assert change["path"] == "bare.md"
        assert set(change["missing_fields"]) == {
            "project", "type", "status", "tags", "created", "updated",
        }

    def test_detects_partial(self, vault):
        """File with project and type reports only the 4 remaining fields."""
        # Arrange
        (vault / "partial.md").write_text(
            "---\nproject: myproj\ntype: guide\n---\n# Partial\n\nContent.\n"
        )

        # Act
        changes = migrate._check_frontmatter(vault)

        # Assert
        assert len(changes) == 1
        assert set(changes[0]["missing_fields"]) == {
            "status", "tags", "created", "updated",
        }

    def test_skips_complete(self, vault):
        """File with all 6 required fields does not appear in changes."""
        # Arrange
        (vault / "complete.md").write_text(
            "---\n"
            "project: proj\n"
            "type: guide\n"
            "status: draft\n"
            "tags: []\n"
            "created: '2025-01-01'\n"
            "updated: '2025-01-01'\n"
            "---\n"
            "# Complete\n\nAll fields present.\n"
        )

        # Act
        changes = migrate._check_frontmatter(vault)

        # Assert
        assert len(changes) == 0

    def test_excludes_raw_dir(self, vault):
        """Files in raw/ are excluded from frontmatter changes."""
        # Arrange
        (vault / "raw").mkdir()
        (vault / "raw" / "source.md").write_text("# Raw\n\nNo frontmatter.\n")

        # Act
        changes = migrate._check_frontmatter(vault)

        # Assert
        paths = [c["path"] for c in changes]
        assert "raw/source.md" not in paths

    def test_excludes_log_file(self, vault):
        """_log.md is excluded from frontmatter changes."""
        # Arrange
        (vault / "_log.md").write_text("# Operation Log\n")

        # Act
        changes = migrate._check_frontmatter(vault)

        # Assert
        paths = [c["path"] for c in changes]
        assert "_log.md" not in paths

    def test_project_default_from_dir(self, vault):
        """File in a subdirectory gets project default from first dir name."""
        # Arrange
        (vault / "myproject").mkdir()
        (vault / "myproject" / "note.md").write_text("# Note\n\nContent.\n")

        # Act
        changes = migrate._check_frontmatter(vault)

        # Assert
        change = next(c for c in changes if c["path"] == "myproject/note.md")
        assert change["defaults"]["project"] == "myproject"

    def test_project_default_root(self, vault):
        """File at vault root gets project default of 'unknown'."""
        # Arrange
        (vault / "root.md").write_text("# Root\n\nContent.\n")

        # Act
        changes = migrate._check_frontmatter(vault)

        # Assert
        change = next(c for c in changes if c["path"] == "root.md")
        assert change["defaults"]["project"] == "unknown"


# ---------------------------------------------------------------------------
# migrate_vault — preview mode
# ---------------------------------------------------------------------------


class TestMigrateVaultPreview:
    def test_preview_no_filesystem_changes(self, vault):
        """Preview mode (confirm=False) does not create dirs or modify files."""
        # Arrange
        (vault / "note.md").write_text("# Note\n\nContent.\n")
        original_content = (vault / "note.md").read_text()

        # Act
        result = migrate.migrate_vault(confirm=False)

        # Assert
        assert result["preview"] is True
        assert result["applied"] is False
        assert not (vault / "raw").exists()
        assert not (vault / "wiki").exists()
        assert not (vault / "_log.md").exists()
        assert (vault / "note.md").read_text() == original_content

    def test_preview_returns_correct_summary(self, vault):
        """Summary counts match the actual state of the vault."""
        # Arrange
        (vault / "a.md").write_text("# A\n\nContent.\n")
        (vault / "b.md").write_text(
            "---\nproject: x\ntype: guide\nstatus: draft\ntags: []\n"
            "created: '2025-01-01'\nupdated: '2025-01-01'\n---\n# B\n\nComplete.\n"
        )

        # Act
        result = migrate.migrate_vault(confirm=False)

        # Assert
        summary = result["summary"]
        assert summary["total_files"] == 2
        assert summary["files_needing_frontmatter"] == 1
        assert summary["dirs_to_create"] == 2
        assert summary["log_to_create"] is True


# ---------------------------------------------------------------------------
# migrate_vault — apply mode
# ---------------------------------------------------------------------------


class TestMigrateVaultApply:
    def test_creates_directories(self, vault):
        """Apply mode creates raw/ and wiki/ directories."""
        # Act
        result = migrate.migrate_vault(confirm=True)

        # Assert
        assert result["applied"] is True
        assert (vault / "raw").is_dir()
        assert (vault / "wiki").is_dir()

    def test_creates_log_file(self, vault):
        """Apply mode creates _log.md with header content."""
        # Act
        migrate.migrate_vault(confirm=True)

        # Assert
        log_path = vault / "_log.md"
        assert log_path.exists()
        content = log_path.read_text()
        assert "Operation Log" in content

    def test_adds_missing_frontmatter(self, vault):
        """Apply mode adds all missing required fields to files."""
        # Arrange
        (vault / "note.md").write_text("# Note\n\nContent.\n")

        # Act
        migrate.migrate_vault(confirm=True)

        # Assert
        post = frontmatter.load(str(vault / "note.md"))
        assert post.metadata["project"] == "unknown"
        assert post.metadata["type"] == "guide"
        assert post.metadata["status"] == "draft"
        assert post.metadata["tags"] == []
        assert "created" in post.metadata
        assert "updated" in post.metadata

    def test_preserves_existing_frontmatter(self, vault):
        """Apply mode does not overwrite existing frontmatter values."""
        # Arrange
        (vault / "existing.md").write_text(
            "---\nproject: myproj\ntype: overview\n---\n# Existing\n\nContent.\n"
        )

        # Act
        migrate.migrate_vault(confirm=True)

        # Assert
        post = frontmatter.load(str(vault / "existing.md"))
        assert post.metadata["project"] == "myproj"
        assert post.metadata["type"] == "overview"
        assert post.metadata["status"] == "draft"

    def test_idempotent(self, vault):
        """Running apply twice produces zero frontmatter changes on second run."""
        # Arrange
        (vault / "note.md").write_text("# Note\n\nContent.\n")

        # Act
        migrate.migrate_vault(confirm=True)
        second = migrate.migrate_vault(confirm=True)

        # Assert
        assert second["summary"]["files_needing_frontmatter"] == 0
        assert second["summary"]["dirs_to_create"] == 0
        assert second["summary"]["log_to_create"] is False

    def test_logs_migration(self, vault):
        """Apply mode writes a migration entry to _log.md."""
        # Arrange
        (vault / "note.md").write_text("# Note\n\nContent.\n")

        # Act
        migrate.migrate_vault(confirm=True)

        # Assert
        log_content = (vault / "_log.md").read_text()
        assert "migration" in log_content.lower() or "Migration" in log_content
