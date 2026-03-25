"""Tests for path_utils module."""

import pytest
from pathlib import Path

from vault_search.path_utils import relative_to_vault, resolve_vault_path


class TestResolveVaultPath:
    def test_simple_path(self, tmp_path):
        result = resolve_vault_path(tmp_path, "notes/daily.md")
        assert result == tmp_path / "notes" / "daily.md"

    def test_root_path(self, tmp_path):
        result = resolve_vault_path(tmp_path, "")
        assert result == tmp_path

    def test_nested_path(self, tmp_path):
        result = resolve_vault_path(tmp_path, "a/b/c/d.md")
        assert result == tmp_path / "a" / "b" / "c" / "d.md"

    def test_traversal_dotdot(self, tmp_path):
        with pytest.raises(ValueError, match="Path traversal detected"):
            resolve_vault_path(tmp_path, "../outside.md")

    def test_traversal_nested_dotdot(self, tmp_path):
        with pytest.raises(ValueError, match="Path traversal detected"):
            resolve_vault_path(tmp_path, "notes/../../outside.md")

    def test_traversal_absolute_path(self, tmp_path):
        with pytest.raises(ValueError, match="Path traversal detected"):
            resolve_vault_path(tmp_path, "/etc/passwd")

    def test_dotdot_within_vault(self, tmp_path):
        # notes/../other.md resolves to other.md which is still inside vault
        result = resolve_vault_path(tmp_path, "notes/../other.md")
        assert result == tmp_path / "other.md"


class TestRelativeToVault:
    def test_simple(self, tmp_path):
        result = relative_to_vault(tmp_path, tmp_path / "notes" / "daily.md")
        assert result == "notes/daily.md"

    def test_root_file(self, tmp_path):
        result = relative_to_vault(tmp_path, tmp_path / "file.md")
        assert result == "file.md"
