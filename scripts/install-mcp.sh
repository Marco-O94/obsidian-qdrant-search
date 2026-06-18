#!/usr/bin/env bash
#
# Guided installer for the obsidian-qdrant-search MCP server.
#
# Detects which AI CLIs are installed (Claude Code, Gemini CLI, Codex CLI,
# Cursor), lets you pick which ones to wire up, asks for the Obsidian vault
# path, and writes the MCP-server config into each selected client's config
# file. Idempotent: re-running updates the existing entry in place.
#
#   ./scripts/install-mcp.sh
#
# Non-interactive overrides (skip the matching prompt):
#   VAULT_PATH=/path/to/vault   pre-set the vault
#   SERVER_NAME=obsidian-vault  pre-set the MCP server key
#   SCOPE=global|project        pre-set the install scope
#   TARGETS=claude,gemini,...   pre-set the clients (comma list), skips menu
#
set -euo pipefail

# --- Resolve the repo root (this script lives in <repo>/scripts/) ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Colors (no-op when not a TTY) -----------------------------------------
if [ -t 1 ]; then
  BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); RESET=$(printf '\033[0m')
  GREEN=$(printf '\033[32m'); YELLOW=$(printf '\033[33m'); CYAN=$(printf '\033[36m')
else
  BOLD=""; DIM=""; RESET=""; GREEN=""; YELLOW=""; CYAN=""
fi
say()  { printf '%s\n' "$*"; }
info() { printf '%s%s%s\n' "$CYAN" "$*" "$RESET"; }
ok()   { printf '%s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$RESET" "$*"; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || die "python3 is required (used to edit config files safely)."

# --- Pick the launch command ------------------------------------------------
# Prefer `uv run` so no global install is needed; fall back to a console
# script already on PATH.
if command -v uv >/dev/null 2>&1; then
  RUN_CMD="uv"
  RUN_ARGS_JSON='["run","--directory","'"$REPO_DIR"'","obsidian-qdrant-search"]'
elif command -v obsidian-qdrant-search >/dev/null 2>&1; then
  RUN_CMD="obsidian-qdrant-search"
  RUN_ARGS_JSON='[]'
else
  die "neither 'uv' nor 'obsidian-qdrant-search' found on PATH. Install uv (https://docs.astral.sh/uv/) or 'pip install -e .' first."
fi

# --- Define known targets ---------------------------------------------------
# No associative arrays: macOS ships bash 3.2, which lacks them. Per-id
# attributes come from case-based lookup functions instead.
TARGET_IDS="claude gemini codex cursor"

t_name() { case "$1" in
  claude) echo "Claude Code";; gemini) echo "Gemini CLI";;
  codex)  echo "Codex CLI";;   cursor) echo "Cursor";; esac; }
t_bin()  { case "$1" in
  claude) echo "claude";; gemini) echo "gemini";;
  codex)  echo "codex";;  cursor) echo "cursor";; esac; }
t_dir()  { case "$1" in
  claude) echo "$HOME/.claude";; gemini) echo "$HOME/.gemini";;
  codex)  echo "$HOME/.codex";;  cursor) echo "$HOME/.cursor";; esac; }

is_installed() {
  local id="$1"
  command -v "$(t_bin "$id")" >/dev/null 2>&1 && return 0
  [ -e "$(t_dir "$id")" ] && return 0
  # Claude global config can exist without the dir
  [ "$id" = "claude" ] && [ -f "$HOME/.claude.json" ] && return 0
  return 1
}

say ""
say "${BOLD}obsidian-qdrant-search — MCP installer${RESET}"
say "${DIM}repo: $REPO_DIR${RESET}"
say ""

# --- Detect ----------------------------------------------------------------
info "Detected AI clients:"
for id in $TARGET_IDS; do
  if is_installed "$id"; then
    ok "$(t_name "$id")"
  else
    say "  ${DIM}- $(t_name "$id") (not found)${RESET}"
  fi
done
say ""

# --- Select targets --------------------------------------------------------
SELECTED=""
if [ -n "${TARGETS:-}" ]; then
  SELECTED="$(echo "$TARGETS" | tr ',' ' ')"
else
  say "Select clients to configure (space-separated numbers, e.g. ${BOLD}1 3${RESET}):"
  i=1
  for id in $TARGET_IDS; do
    mark="  "; is_installed "$id" && mark="${GREEN}●${RESET}"
    printf "  %s) %s %s\n" "$i" "$mark" "$(t_name "$id")"
    i=$((i+1))
  done
  printf "  a) all detected\n"
  printf "%s> %s" "$BOLD" "$RESET"; read -r picks
  if [ "$picks" = "a" ] || [ "$picks" = "A" ]; then
    for id in $TARGET_IDS; do is_installed "$id" && SELECTED="$SELECTED $id"; done
  else
    for n in $picks; do
      # Map the typed number to the Nth id in TARGET_IDS.
      sel="$(echo "$TARGET_IDS" | cut -d' ' -f"$n" 2>/dev/null)"
      case " $TARGET_IDS " in
        *" $sel "*) [ -n "$sel" ] && SELECTED="$SELECTED $sel" ;;
        *) warn "ignoring invalid choice '$n'" ;;
      esac
    done
  fi
fi
SELECTED="$(echo "$SELECTED" | xargs)"   # trim
[ -n "$SELECTED" ] || die "no clients selected."

# --- Vault path ------------------------------------------------------------
VAULT="${VAULT_PATH:-}"
if [ -z "$VAULT" ]; then
  say ""
  printf "%sObsidian vault path%s: " "$BOLD" "$RESET"; read -r VAULT
fi
# Expand leading ~ and resolve to absolute
VAULT="${VAULT/#\~/$HOME}"
[ -d "$VAULT" ] || die "vault path does not exist or is not a directory: $VAULT"
VAULT="$(cd "$VAULT" && pwd)"
ok "vault: $VAULT"

# --- Server name + scope ---------------------------------------------------
SERVER_NAME="${SERVER_NAME:-obsidian-vault}"
SCOPE="${SCOPE:-}"
if [ -z "$SCOPE" ]; then
  say ""
  say "Install scope:"
  say "  1) ${BOLD}global${RESET}  — available in every project ${DIM}(recommended)${RESET}"
  say "  2) project — only when the client runs inside the vault folder"
  printf "%s> %s" "$BOLD" "$RESET"; read -r s
  case "$s" in 2) SCOPE="project" ;; *) SCOPE="global" ;; esac
fi
ok "scope: $SCOPE   server key: $SERVER_NAME"

# --- Config-path resolver --------------------------------------------------
# Echoes "format|path" for a given target id, or "" if unsupported.
config_target() {
  local id="$1"
  case "$id" in
    claude)
      if [ "$SCOPE" = "global" ]; then echo "json|$HOME/.claude.json";
      else echo "json|$VAULT/.mcp.json"; fi ;;
    gemini)
      if [ "$SCOPE" = "global" ]; then echo "json|$HOME/.gemini/settings.json";
      else echo "json|$VAULT/.gemini/settings.json"; fi ;;
    cursor)
      if [ "$SCOPE" = "global" ]; then echo "json|$HOME/.cursor/mcp.json";
      else echo "json|$VAULT/.cursor/mcp.json"; fi ;;
    codex)
      # Codex has no project-local config concept — always global.
      echo "toml|$HOME/.codex/config.toml" ;;
  esac
}

# --- The Python merger (handles both JSON and TOML, idempotently) ----------
write_config() {
  local fmt="$1" path="$2" id="$3"
  SRV_NAME="$SERVER_NAME" \
  RUN_CMD="$RUN_CMD" RUN_ARGS_JSON="$RUN_ARGS_JSON" \
  VAULT="$VAULT" CFG_FMT="$fmt" CFG_PATH="$path" \
  python3 - "$id" <<'PY'
import json, os, re, sys
from pathlib import Path

name   = os.environ["SRV_NAME"]
cmd    = os.environ["RUN_CMD"]
args   = json.loads(os.environ["RUN_ARGS_JSON"])
vault  = os.environ["VAULT"]
fmt    = os.environ["CFG_FMT"]
path   = Path(os.environ["CFG_PATH"])

env = {"VAULT_PATH": vault}
entry = {"command": cmd, "args": args, "env": env}

path.parent.mkdir(parents=True, exist_ok=True)

if fmt == "json":
    data = {}
    if path.exists() and path.stat().st_size > 0:
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            bak = path.with_suffix(path.suffix + ".backup")
            bak.write_text(path.read_text())
            print(f"  (unparseable JSON backed up to {bak})")
            data = {}
    servers = data.setdefault("mcpServers", {})
    existed = name in servers
    servers[name] = entry
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(("updated" if existed else "created") + f": {path}")

elif fmt == "toml":
    # Surgical TOML edit: strip any existing [mcp_servers.<name>] block,
    # then append a fresh one. Preserves the rest of the file (comments, etc).
    text = path.read_text() if path.exists() else ""
    header = f"[mcp_servers.{name}]"
    existed = header in text
    # Remove the existing block: from its header to the next top-level
    # header (a line starting with '[') or EOF.
    pattern = re.compile(
        r"(?ms)^\[mcp_servers\." + re.escape(name) + r"\].*?(?=^\[|\Z)"
    )
    text = pattern.sub("", text).rstrip()

    def toml_str(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    block = [f"\n{header}", f"command = {toml_str(cmd)}"]
    block.append("args = [" + ", ".join(toml_str(a) for a in args) + "]")
    block.append("env = { " + ", ".join(f"{k} = {toml_str(v)}" for k, v in env.items()) + " }")
    out = (text + "\n" if text else "") + "\n".join(block) + "\n"
    path.write_text(out)
    print(("updated" if existed else "created") + f": {path}")
PY
}

# --- Apply -----------------------------------------------------------------
say ""
info "Writing config..."
for id in $SELECTED; do
  spec="$(config_target "$id")"
  [ -n "$spec" ] || { warn "$(t_name "$id"): unsupported, skipping"; continue; }
  fmt="${spec%%|*}"; path="${spec#*|}"
  printf "  %s%s%s  " "$BOLD" "$(t_name "$id")" "$RESET"
  write_config "$fmt" "$path" "$id"
done

say ""
ok "Done."
say "${DIM}Restart your AI client(s) to load the '$SERVER_NAME' MCP server.${RESET}"
say "${DIM}Qdrant auto-starts via Docker the first time a tool is called.${RESET}"
