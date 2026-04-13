"""CLI entry points for vault indexing and management."""

import json
import sys


def index_cli():
    """Run vault indexing from the command line."""
    from vault_search.indexer import index_vault

    full_mode = "--full" in sys.argv
    print(f"Indexing vault ({'full' if full_mode else 'incremental'} mode)...")
    report = index_vault(full=full_mode)
    print(json.dumps(report, indent=2))


def _parse_flag(args: list[str], flag: str, default: str = "") -> str:
    """Extract --flag value from args list."""
    for i, arg in enumerate(args):
        if arg == flag and i + 1 < len(args):
            return args[i + 1]
    return default


def _has_flag(args: list[str], flag: str) -> bool:
    """Check if a flag is present in args."""
    return flag in args


def _parse_int_flag(args: list[str], flag: str, default: int) -> int:
    """Extract --flag integer value from args list."""
    raw = _parse_flag(args, flag, str(default))
    try:
        return int(raw)
    except ValueError:
        print(f"Error: {flag} requires an integer, got '{raw}'", file=sys.stderr)
        sys.exit(1)


def search_cli():
    """Search the vault from the command line.

    Usage: vault-search search "query" [--project X] [--top-k 5] [--json]
    """
    args = sys.argv[1:]
    if not args:
        print("Usage: vault-search search <query> [--project X] [--top-k N] [--json]", file=sys.stderr)
        sys.exit(1)

    # First positional arg is the query
    query = args[0]
    project = _parse_flag(args, "--project") or None
    top_k = _parse_int_flag(args, "--top-k", 5)
    json_output = _has_flag(args, "--json")

    from vault_search.server import search_vault

    result = search_vault(query=query, project=project, top_k=top_k)

    if json_output:
        print(json.dumps({"query": query, "result": result}))
    else:
        print(result)


def read_cli():
    """Read a vault file from the command line.

    Usage: vault-search read <filepath>
    """
    args = sys.argv[1:]
    if not args:
        print("Usage: vault-search read <filepath>", file=sys.stderr)
        sys.exit(1)

    from vault_search import vault_ops

    try:
        content = vault_ops.get_file_contents(args[0])
        print(content)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def write_cli():
    """Write content to a vault file from the command line.

    Usage: vault-search write <filepath> --content "..." | vault-search write <filepath> < file
    """
    args = sys.argv[1:]
    if not args:
        print("Usage: vault-search write <filepath> --content '...'", file=sys.stderr)
        sys.exit(1)

    filepath = args[0]
    content = _parse_flag(args, "--content")

    if not content and not sys.stdin.isatty():
        content = sys.stdin.read()

    if not content:
        print("Error: --content required or pipe content via stdin", file=sys.stderr)
        sys.exit(1)

    from vault_search import vault_ops

    try:
        result = vault_ops.create_or_update_file(filepath, content)
        action = "Created" if result["created"] else "Updated"
        print(f"{action} {result['path']} ({result['size']} bytes)")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def lint_cli():
    """Run vault health check from the command line.

    Usage: vault-search lint [--stale-days 90] [--json]
    """
    args = sys.argv[1:]
    stale_days = _parse_int_flag(args, "--stale-days", 90)
    json_output = _has_flag(args, "--json")

    from vault_search import vault_ops

    result = vault_ops.lint_vault(stale_days=stale_days)

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        summary = result["summary"]
        print(f"Vault Health Report ({summary['total_files']} files scanned)")
        print(f"  Critical: {summary['critical_count']}")
        print(f"  Warnings: {summary['warning_count']}")
        print(f"  Info:     {summary['info_count']}")

        for severity, label in [("critical", "CRITICAL"), ("warning", "WARNING"), ("info", "INFO")]:
            issues = result[severity]
            if issues:
                print(f"\n{label}:")
                for issue in issues:
                    print(f"  - {issue.get('file', '')}: {issue['message']}")

        if not result["critical"] and not result["warning"]:
            print("\nVault is healthy!")


def log_cli():
    """Log an operation or read the log from the command line.

    Usage:
        vault-search log <type> "<title>" [--summary "..."] [--source "..."]
        vault-search log --read [--last 20] [--filter <type>] [--json]
    """
    args = sys.argv[1:]

    if _has_flag(args, "--read"):
        last_n = _parse_int_flag(args, "--last", 20)
        filter_type = _parse_flag(args, "--filter")
        json_output = _has_flag(args, "--json")

        from vault_search import vault_ops

        entries = vault_ops.get_operation_log(last_n=last_n, filter_type=filter_type)

        if json_output:
            print(json.dumps(entries, indent=2))
        else:
            if not entries:
                print("No log entries found.")
            else:
                for entry in entries:
                    print(f"[{entry['date']}] {entry['operation_type']} | {entry['title']}")
                    if entry["body"]:
                        for line in entry["body"].split("\n"):
                            print(f"  {line}")
        return

    if len(args) < 2:
        print("Usage: vault-search log <type> '<title>' [--summary '...'] [--source '...']", file=sys.stderr)
        sys.exit(1)

    operation_type = args[0]
    title = args[1]
    summary = _parse_flag(args, "--summary")
    source = _parse_flag(args, "--source")

    from vault_search import vault_ops

    result = vault_ops.log_operation(
        operation_type=operation_type,
        title=title,
        summary=summary,
        source=source,
    )
    print(f"Logged to {result['path']}")


def map_cli():
    """Show vault structure from the command line.

    Usage: vault-search map [--depth 3] [--json]
    """
    args = sys.argv[1:]
    max_depth = _parse_int_flag(args, "--depth", 3)
    json_output = _has_flag(args, "--json")

    from vault_search import vault_ops

    tree = vault_ops.get_vault_map(max_depth=max_depth)

    if json_output:
        print(json.dumps(tree, indent=2))
    else:
        print(vault_ops.format_vault_tree(tree))


def migrate_cli():
    """Migrate vault to LLM Wiki pattern from the command line.

    Usage: vault-search-migrate [--mode assisted|manual] [--apply] [--json]
    """
    args = sys.argv[1:]
    confirm = _has_flag(args, "--apply")
    json_output = _has_flag(args, "--json")
    mode = _parse_flag(args, "--mode", "assisted")

    from vault_search.migrate import migrate_vault

    result = migrate_vault(confirm=confirm, mode=mode)

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        summary = result["summary"]
        status = "Applied" if result["applied"] else "Preview"
        print(f"Vault Migration ({status}, {result['mode']} mode)")
        print(f"  Total files: {summary['total_files']}")
        print(f"  Directories to create: {summary['dirs_to_create']}")
        print(f"  Log file to create: {summary['log_to_create']}")

        if result["mode"] == "assisted":
            print(f"  Files to move: {summary['files_to_move']}")
            print(f"  Files unknown: {summary['files_unknown']}")

        print(f"  Files needing frontmatter: {summary['files_needing_frontmatter']}")

        for d in result["directories"]:
            status_str = "exists" if d["exists"] else ("created" if result["applied"] else "will create")
            print(f"  {d['path']} — {status_str}")

        if result["file_moves"]:
            moves = [m for m in result["file_moves"] if m["action"] == "move"]
            skips = [m for m in result["file_moves"] if m["action"] == "skip"]

            if moves:
                print(f"\nFile moves ({len(moves)} files):")
                for m in moves:
                    print(f"  {m['path']} [{m['classification']}] -> {m['destination']}")

            if skips:
                print(f"\nUnknown files ({len(skips)} — need manual review):")
                for m in skips:
                    print(f"  {m['path']}")

        if result["frontmatter_changes"]:
            print(f"\nFrontmatter changes ({len(result['frontmatter_changes'])} files):")
            for change in result["frontmatter_changes"]:
                fields = ", ".join(change["missing_fields"])
                print(f"  {change['path']} — missing: {fields}")

        if not result["applied"]:
            print("\nRun with --apply to apply changes.")
