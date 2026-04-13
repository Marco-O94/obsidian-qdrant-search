"""Tests for vault_ops lint_vault."""

import os
import time

import pytest

from vault_search import vault_ops
from vault_search import indexer as vault_indexer


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """Set up a temporary vault directory and patch VAULT_PATH."""
    monkeypatch.setattr(vault_ops, "VAULT_PATH", tmp_path)
    # Clear the wikilink cache so resolution works against tmp_path
    monkeypatch.setattr(vault_indexer, "_wikilink_cache", {})
    return tmp_path


# ---------------------------------------------------------------------------
# lint_vault
# ---------------------------------------------------------------------------


class TestLintVault:
    def test_healthy_vault(self, vault):
        # Arrange: two files that link to each other with full frontmatter
        (vault / "alpha.md").write_text(
            "---\nproject: demo\ntype: note\nstatus: active\n---\n"
            "# Alpha\n\nThis links to [[beta]].\n\n"
            + ("Content padding. " * 10)
        )
        (vault / "beta.md").write_text(
            "---\nproject: demo\ntype: note\nstatus: active\n---\n"
            "# Beta\n\nThis links to [[alpha]].\n\n"
            + ("Content padding. " * 10)
        )

        # Act
        result = vault_ops.lint_vault()

        # Assert
        assert result["critical"] == []
        assert not any(
            w["type"] in ("missing_frontmatter", "parse_error")
            for w in result["warning"]
        )

    def test_broken_links(self, vault):
        # Arrange: file references a nonexistent target
        (vault / "note.md").write_text(
            "---\nproject: x\ntype: x\nstatus: x\n---\n"
            "# Note\n\n[[nonexistent]]\n\n"
            + ("Padding text. " * 10)
        )

        # Act
        result = vault_ops.lint_vault()

        # Assert
        broken = [i for i in result["critical"] if i["type"] == "broken_link"]
        assert len(broken) >= 1
        assert "nonexistent" in broken[0]["message"]

    def test_orphan_files(self, vault):
        # Arrange: two files, neither links to the other
        (vault / "lonely.md").write_text(
            "---\nproject: x\ntype: x\nstatus: x\n---\n"
            "# Lonely\n\nNo links here.\n\n"
            + ("Padding text. " * 10)
        )
        (vault / "also_lonely.md").write_text(
            "---\nproject: x\ntype: x\nstatus: x\n---\n"
            "# Also Lonely\n\nNo links here either.\n\n"
            + ("Padding text. " * 10)
        )

        # Act
        result = vault_ops.lint_vault()

        # Assert
        orphans = [w for w in result["warning"] if w["type"] == "orphan"]
        orphan_files = {o["file"] for o in orphans}
        assert "lonely.md" in orphan_files
        assert "also_lonely.md" in orphan_files

    def test_missing_frontmatter(self, vault):
        # Arrange: file missing project/type/status fields
        (vault / "bare.md").write_text(
            "---\ntags:\n  - test\n---\n# Bare\n\nSome content here.\n\n"
            + ("Padding text. " * 10)
        )

        # Act
        result = vault_ops.lint_vault()

        # Assert
        missing = [
            w for w in result["warning"] if w["type"] == "missing_frontmatter"
        ]
        assert len(missing) >= 1
        assert "bare.md" in missing[0]["file"]
        assert "project" in missing[0]["message"]

    def test_stub_document(self, vault):
        # Arrange: file with body under 100 chars
        (vault / "stub.md").write_text(
            "---\nproject: x\ntype: x\nstatus: x\n---\n# Stub\n\nShort.\n"
        )

        # Act
        result = vault_ops.lint_vault()

        # Assert
        stubs = [i for i in result["info"] if i["type"] == "stub"]
        assert len(stubs) >= 1
        assert "stub.md" in stubs[0]["file"]

    def test_stale_document(self, vault):
        # Arrange: file with modification time 120 days ago
        stale_file = vault / "old.md"
        stale_file.write_text(
            "---\nproject: x\ntype: x\nstatus: x\n---\n# Old\n\nOld content.\n"
        )
        old_time = time.time() - (120 * 86400)
        os.utime(stale_file, (old_time, old_time))

        # Act
        result = vault_ops.lint_vault(stale_days=90)

        # Assert
        stale = [i for i in result["info"] if i["type"] == "stale"]
        assert len(stale) >= 1
        assert "old.md" in stale[0]["file"]

    def test_no_outgoing_links(self, vault):
        # Arrange: file without any wikilinks
        (vault / "island.md").write_text(
            "---\nproject: x\ntype: x\nstatus: x\n---\n"
            "# Island\n\nNo links at all.\n\n"
            + ("Padding text. " * 10)
        )

        # Act
        result = vault_ops.lint_vault()

        # Assert
        no_links = [
            i for i in result["info"] if i["type"] == "no_outgoing_links"
        ]
        island_issues = [i for i in no_links if "island.md" in i["file"]]
        assert len(island_issues) >= 1

    def test_summary_counts(self, vault):
        # Arrange: one broken link (critical), one missing frontmatter (warning),
        # one stub (info)
        (vault / "broken.md").write_text(
            "---\nproject: x\ntype: x\nstatus: x\n---\n"
            "# Broken\n\n[[does_not_exist]]\n\n"
            + ("Padding text. " * 10)
        )
        (vault / "no_fm.md").write_text(
            "---\ntags: []\n---\n# No FM\n\nSome text.\n\n"
            + ("Padding text. " * 10)
        )
        (vault / "tiny.md").write_text(
            "---\nproject: x\ntype: x\nstatus: x\n---\n# Tiny\n\nSmall.\n"
        )

        # Act
        result = vault_ops.lint_vault()

        # Assert
        summary = result["summary"]
        assert summary["total_files"] == 3
        assert summary["critical_count"] == len(result["critical"])
        assert summary["warning_count"] == len(result["warning"])
        assert summary["info_count"] == len(result["info"])
        assert summary["critical_count"] >= 1
        assert summary["warning_count"] >= 1
        assert summary["info_count"] >= 1
