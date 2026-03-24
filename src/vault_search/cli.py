"""CLI entry point for standalone indexing."""

import json
import sys


def index_cli():
    """Run vault indexing from the command line."""
    from vault_search.indexer import index_vault

    full_mode = "--full" in sys.argv
    print(f"Indexing vault ({'full' if full_mode else 'incremental'} mode)...")
    report = index_vault(full=full_mode)
    print(json.dumps(report, indent=2))
