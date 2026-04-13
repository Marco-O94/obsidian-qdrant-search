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
        migrate.migrate_vault(confirm=True, mode="manual")

        # Assert
        log_content = (vault / "_log.md").read_text()
        assert "migration" in log_content.lower() or "Migration" in log_content


# ---------------------------------------------------------------------------
# _plan_moves
# ---------------------------------------------------------------------------


class TestPlanMoves:
    def test_classifies_raw_file(self, vault):
        """File with no frontmatter is planned to move to raw/."""
        # Arrange
        (vault / "article.md").write_text("Just plain text, no frontmatter.\n")

        # Act
        moves = migrate._plan_moves(vault)

        # Assert
        move = next(m for m in moves if m["path"] == "article.md")
        assert move["classification"] == "raw"
        assert move["destination"] == "raw/article.md"
        assert move["action"] == "move"

    def test_classifies_wiki_file(self, vault):
        """File with type frontmatter is planned to move to wiki/."""
        # Arrange
        (vault / "overview.md").write_text(
            "---\ntype: overview\n---\n# Overview\n\nContent.\n"
        )

        # Act
        moves = migrate._plan_moves(vault)

        # Assert
        move = next(m for m in moves if m["path"] == "overview.md")
        assert move["classification"] == "wiki"
        assert move["destination"] == "wiki/overview.md"
        assert move["action"] == "move"

    def test_unknown_file_skipped(self, vault):
        """File classified as unknown stays in place."""
        # Arrange — has frontmatter but no type and no wikilinks
        (vault / "ambiguous.md").write_text(
            "---\ntags:\n  - misc\n---\n# Ambiguous\n\nSome text.\n"
        )

        # Act
        moves = migrate._plan_moves(vault)

        # Assert
        move = next(m for m in moves if m["path"] == "ambiguous.md")
        assert move["classification"] == "unknown"
        assert move["destination"] is None
        assert move["action"] == "skip"

    def test_skips_files_already_in_raw(self, vault):
        """Files already in raw/ are not included in moves."""
        # Arrange
        (vault / "raw").mkdir()
        (vault / "raw" / "source.md").write_text("Already in raw.\n")

        # Act
        moves = migrate._plan_moves(vault)

        # Assert
        paths = [m["path"] for m in moves]
        assert "raw/source.md" not in paths

    def test_skips_files_already_in_wiki(self, vault):
        """Files already in wiki/ are not included in moves."""
        # Arrange
        (vault / "wiki").mkdir()
        (vault / "wiki" / "page.md").write_text("Already in wiki.\n")

        # Act
        moves = migrate._plan_moves(vault)

        # Assert
        paths = [m["path"] for m in moves]
        assert "wiki/page.md" not in paths

    def test_preserves_subdirectory_structure(self, vault):
        """File in a subdir moves to raw/subdir/ or wiki/subdir/."""
        # Arrange
        (vault / "notes").mkdir()
        (vault / "notes" / "plain.md").write_text("No frontmatter at all.\n")

        # Act
        moves = migrate._plan_moves(vault)

        # Assert
        move = next(m for m in moves if m["path"] == "notes/plain.md")
        assert move["destination"] == "raw/notes/plain.md"


# ---------------------------------------------------------------------------
# migrate_vault — assisted mode
# ---------------------------------------------------------------------------


class TestMigrateVaultAssisted:
    def test_preview_shows_moves(self, vault):
        """Assisted preview shows planned file moves."""
        # Arrange
        (vault / "source.md").write_text("Plain text, no frontmatter.\n")
        (vault / "page.md").write_text(
            "---\ntype: entity\n---\n# Entity\n\nContent.\n"
        )

        # Act
        result = migrate.migrate_vault(confirm=False, mode="assisted")

        # Assert
        assert result["mode"] == "assisted"
        assert result["summary"]["files_to_move"] == 2
        moves = result["file_moves"]
        source_move = next(m for m in moves if m["path"] == "source.md")
        page_move = next(m for m in moves if m["path"] == "page.md")
        assert source_move["destination"] == "raw/source.md"
        assert page_move["destination"] == "wiki/page.md"

    def test_preview_no_filesystem_changes(self, vault):
        """Assisted preview does not move any files."""
        # Arrange
        (vault / "source.md").write_text("Plain text.\n")

        # Act
        migrate.migrate_vault(confirm=False, mode="assisted")

        # Assert
        assert (vault / "source.md").exists()
        assert not (vault / "raw" / "source.md").exists()

    def test_apply_moves_files(self, vault):
        """Assisted apply moves files to correct directories."""
        # Arrange
        (vault / "article.md").write_text("No frontmatter content.\n")
        (vault / "page.md").write_text(
            "---\ntype: concept\n---\n# Concept\n\nExplanation.\n"
        )

        # Act
        result = migrate.migrate_vault(confirm=True, mode="assisted")

        # Assert
        assert result["applied"] is True
        assert not (vault / "article.md").exists()
        assert (vault / "raw" / "article.md").exists()
        assert not (vault / "page.md").exists()
        assert (vault / "wiki" / "page.md").exists()

    def test_apply_preserves_subdir_structure(self, vault):
        """Files in subdirectories maintain their structure after move."""
        # Arrange
        (vault / "project").mkdir()
        (vault / "project" / "readme.md").write_text(
            "---\ntype: overview\n---\n# Project\n\nInfo.\n"
        )

        # Act
        migrate.migrate_vault(confirm=True, mode="assisted")

        # Assert
        assert not (vault / "project" / "readme.md").exists()
        assert (vault / "wiki" / "project" / "readme.md").exists()

    def test_apply_adds_frontmatter_after_move(self, vault):
        """Frontmatter is added to files after they are moved."""
        # Arrange
        (vault / "page.md").write_text(
            "---\ntype: guide\n---\n# Guide\n\nContent.\n"
        )

        # Act
        migrate.migrate_vault(confirm=True, mode="assisted")

        # Assert
        post = frontmatter.load(str(vault / "wiki" / "page.md"))
        assert post.metadata["type"] == "guide"
        assert post.metadata["status"] == "draft"
        assert "project" in post.metadata

    def test_unknown_files_stay_in_place(self, vault):
        """Files classified as unknown are not moved."""
        # Arrange
        (vault / "ambiguous.md").write_text(
            "---\ntags:\n  - random\n---\n# Maybe\n\nUnclear.\n"
        )

        # Act
        migrate.migrate_vault(confirm=True, mode="assisted")

        # Assert
        assert (vault / "ambiguous.md").exists()

    def test_idempotent(self, vault):
        """Running assisted apply twice produces zero moves on second run."""
        # Arrange
        (vault / "article.md").write_text("Plain text.\n")
        (vault / "page.md").write_text(
            "---\ntype: entity\n---\n# Entity\n\nContent.\n"
        )

        # Act
        migrate.migrate_vault(confirm=True, mode="assisted")
        second = migrate.migrate_vault(confirm=True, mode="assisted")

        # Assert
        assert second["summary"]["files_to_move"] == 0
        assert second["summary"]["files_needing_frontmatter"] == 0

    def test_skips_destination_collision(self, vault):
        """If a file already exists at the destination, the move is skipped."""
        # Arrange
        (vault / "raw").mkdir()
        (vault / "raw" / "article.md").write_text("Pre-existing raw file.\n")
        (vault / "article.md").write_text("New article, no frontmatter.\n")

        # Act
        result = migrate.migrate_vault(confirm=True, mode="assisted")

        # Assert — source file stays, destination not overwritten
        assert (vault / "article.md").exists()
        assert (vault / "raw" / "article.md").read_text() == "Pre-existing raw file.\n"

    def test_updates_path_based_wikilinks(self, vault):
        """Path-based wikilinks are updated after file moves."""
        # Arrange
        (vault / "notes").mkdir()
        (vault / "notes" / "article.md").write_text("No frontmatter.\n")
        (vault / "index.md").write_text(
            "---\ntype: overview\n---\n# Index\n\nSee [[notes/article]] for details.\n"
        )

        # Act
        migrate.migrate_vault(confirm=True, mode="assisted")

        # Assert — index moved to wiki/, its link updated
        content = (vault / "wiki" / "index.md").read_text()
        assert "[[raw/notes/article]]" in content
        assert "[[notes/article]]" not in content

    def test_no_prefix_collision_in_wikilinks(self, vault):
        """Wikilink update does not corrupt links that share a path prefix."""
        # Arrange
        (vault / "notes").mkdir()
        (vault / "notes" / "abc.md").write_text("No frontmatter.\n")
        (vault / "notes" / "abcdef.md").write_text("No frontmatter either.\n")
        (vault / "linker.md").write_text(
            "---\ntype: guide\n---\n# Linker\n\n"
            "See [[notes/abc]] and [[notes/abcdef]].\n"
        )

        # Act
        migrate.migrate_vault(confirm=True, mode="assisted")

        # Assert — both links updated independently, no corruption
        content = (vault / "wiki" / "linker.md").read_text()
        assert "[[raw/notes/abc]]" in content
        assert "[[raw/notes/abcdef]]" in content

    def test_cleanup_only_vacated_dirs(self, vault):
        """Empty dirs not related to moves are preserved."""
        # Arrange
        (vault / "keep-empty").mkdir()
        (vault / "article.md").write_text("No frontmatter.\n")

        # Act
        migrate.migrate_vault(confirm=True, mode="assisted")

        # Assert
        assert (vault / "keep-empty").is_dir()

    def test_fixes_partial_path_wikilinks(self, vault):
        """Partial path wikilinks like [[02-modules/auth/README]] are updated."""
        # Arrange — simulate a real project structure
        (vault / "Projects" / "myapp" / "_agent-context").mkdir(parents=True)
        (vault / "Projects" / "myapp" / "02-modules" / "auth").mkdir(parents=True)

        (vault / "Projects" / "myapp" / "02-modules" / "auth" / "README.md").write_text(
            "---\ntype: service-layer\n---\n# Auth Module\n\nAuth docs.\n"
        )
        (vault / "Projects" / "myapp" / "_agent-context" / "SUMMARY.md").write_text(
            "---\ntype: overview\n---\n# Summary\n\nSee [[02-modules/auth/README]] for auth.\n"
        )

        # Act
        result = migrate.migrate_vault(confirm=True, mode="assisted")

        # Assert — both files moved to wiki/, link updated
        summary_path = vault / "wiki" / "Projects" / "myapp" / "_agent-context" / "SUMMARY.md"
        assert summary_path.exists()
        content = summary_path.read_text()
        assert "[[wiki/Projects/myapp/02-modules/auth/README]]" in content

    def test_fixes_relative_parent_path_wikilinks(self, vault):
        """Wikilinks with ../ relative paths are updated after moves."""
        # Arrange
        (vault / "docs" / "sub").mkdir(parents=True)
        (vault / "docs" / "target.md").write_text(
            "---\ntype: guide\n---\n# Target\n\nTarget page.\n"
        )
        (vault / "docs" / "sub" / "source.md").write_text(
            "---\ntype: guide\n---\n# Source\n\nSee [[../target]] for info.\n"
        )

        # Act
        migrate.migrate_vault(confirm=True, mode="assisted")

        # Assert — the ../ link should be rewritten to the new path
        source = vault / "wiki" / "docs" / "sub" / "source.md"
        assert source.exists()
        content = source.read_text()
        # The link should reference the new wiki path
        assert "wiki/docs/target" in content

    def test_invalid_mode_raises(self, vault):
        """Invalid mode raises ValueError."""
        with pytest.raises(ValueError, match="Invalid mode"):
            migrate.migrate_vault(mode="bad")
