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
#   QDRANT_PORT=6333            host port for Qdrant (default 6333)
#   SKIP_QDRANT=1               don't try to start Qdrant
#   QDRANT_URL=http://host:6333 full URL override (wins over QDRANT_PORT)
#
set -euo pipefail

# --- Resolve the repo root (this script lives in <repo>/scripts/) ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Colors (no-op when not a TTY) -----------------------------------------
if [ -t 1 ]; then
  BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); RESET=$(printf '\033[0m')
  GREEN=$(printf '\033[32m'); YELLOW=$(printf '\033[33m'); CYAN=$(printf '\033[36m')
  # Always restore the cursor if we exit mid-menu (Ctrl-C, error).
  trap 'printf "\033[?25h"' EXIT INT TERM
else
  BOLD=""; DIM=""; RESET=""; GREEN=""; YELLOW=""; CYAN=""
fi
say()  { printf '%s\n' "$*"; }
info() { printf '%s%s%s\n' "$CYAN" "$*" "$RESET"; }
ok()   { printf '%s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$RESET" "$*"; }
die()  { printf '%s✗ error:%s %s\n' "$YELLOW" "$RESET" "$*" >&2; exit 1; }

# Surface any unexpected failure instead of dying silently under `set -e`.
# (Conditionals like `is_installed x && ...` are exempt and won't trigger it.)
on_err() {
  local rc=$?
  printf '\033[?25h'   # ensure the cursor is restored if we died mid-menu
  printf '%s✗ installer failed%s (line %s, exit %s). Nothing further was written.\n' \
    "$YELLOW" "$RESET" "${1:-?}" "$rc" >&2
  exit "$rc"
}
trap 'on_err "$LINENO"' ERR

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

# --- Interactive multiselect (space to toggle) -----------------------------
# Renders the target list in raw-TTY mode: arrows / j,k move the cursor,
# space toggles, 'a' toggles all, enter confirms. Detected clients start
# checked. Populates the global SELECTED with the chosen ids. Only called
# when stdin/stdout are a real terminal (see the caller's guard).
_ms_ids=""        # space-separated ids, set by multiselect_menu
_ms_checked=""    # parallel 0/1 flags

multiselect_menu() {
  local ids; ids=($TARGET_IDS)
  local n=${#ids[@]} idx cur=0 key rest
  local checked=()
  for ((idx=0; idx<n; idx++)); do
    if is_installed "${ids[$idx]}"; then checked[$idx]=1; else checked[$idx]=0; fi
  done

  _ms_draw() {
    local j box flag pointer
    for ((j=0; j<n; j++)); do
      [ "${checked[$j]}" = "1" ] && box="${GREEN}◉${RESET}" || box="○"
      is_installed "${ids[$j]}" && flag="${DIM}(detected)${RESET}" || flag="${DIM}(not found)${RESET}"
      [ "$j" = "$cur" ] && pointer="${CYAN}❯${RESET}" || pointer=" "
      printf "  %s %s %s %s\033[K\n" "$pointer" "$box" "$(t_name "${ids[$j]}")" "$flag"
    done
  }

  printf "%sWhich clients should be configured?%s  %s↑/↓ move · space toggle · a all · enter confirm%s\n" \
    "$BOLD" "$RESET" "$DIM" "$RESET"
  printf '\033[?25l'                      # hide cursor
  _ms_draw
  while true; do
    IFS= read -rsn1 key || break
    case "$key" in
      ""|$'\r'|$'\n') break ;;            # enter (raw TTY sends CR)
      " ") checked[$cur]=$(( 1 - ${checked[$cur]} )) ;;
      a|A)
        local anyoff=0
        for ((idx=0; idx<n; idx++)); do
          [ "${checked[$idx]}" = "0" ] && anyoff=1 || true
        done
        for ((idx=0; idx<n; idx++)); do checked[$idx]=$anyoff; done ;;
      k) cur=$(( (cur - 1 + n) % n )) ;;
      j) cur=$(( (cur + 1) % n )) ;;
      $'\e')                              # arrow keys: ESC [ A/B
        rest=""; read -rsn2 rest || true  # tolerate partial/lone ESC
        case "$rest" in
          "[A") cur=$(( (cur - 1 + n) % n )) ;;
          "[B") cur=$(( (cur + 1) % n )) ;;
        esac ;;
    esac
    printf '\033[%dA' "$n"                 # cursor up to redraw in place
    _ms_draw
  done
  printf '\033[?25h'                       # show cursor

  _ms_ids=""
  for ((idx=0; idx<n; idx++)); do
    [ "${checked[$idx]}" = "1" ] && _ms_ids="$_ms_ids ${ids[$idx]}" || true
  done
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
elif [ -t 0 ] && [ -t 1 ] && [ "${TERM:-dumb}" != "dumb" ]; then
  # Interactive space-toggle multiselect (detected clients pre-checked).
  multiselect_menu
  SELECTED="$_ms_ids"
else
  # Fallback for non-TTY (piped) input: typed numbers.
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
    for id in $TARGET_IDS; do is_installed "$id" && SELECTED="$SELECTED $id" || true; done
  else
    for n in $picks; do
      # Map the typed number to the Nth id in TARGET_IDS.
      sel="$(echo "$TARGET_IDS" | cut -d' ' -f"$n" 2>/dev/null)"
      case " $TARGET_IDS " in
        *" $sel "*) [ -n "$sel" ] && SELECTED="$SELECTED $sel" || true ;;
        *) warn "ignoring invalid choice '$n'" ;;
      esac
    done
  fi
fi
SELECTED="$(echo "$SELECTED" | xargs)"   # trim
[ -n "$SELECTED" ] || die "no clients selected."

# Immediate confirmation of what was picked.
_names=""
for id in $SELECTED; do _names="$_names, $(t_name "$id")"; done
ok "selected:${_names#,}"

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

# --- Qdrant port -----------------------------------------------------------
# Default is Qdrant's own default (6333). Pick a dedicated port to avoid
# clashing with another Qdrant already on 6333. The chosen URL is written
# into each client's MCP env so the server connects to THIS instance, and
# is reused to bring the container up below.
QDRANT_PORT="${QDRANT_PORT:-}"
if [ -z "$QDRANT_PORT" ] && [ -z "${QDRANT_URL:-}" ]; then
  say ""
  printf "%sQdrant host port%s [%s6333%s]: " "$BOLD" "$RESET" "$DIM" "$RESET"; read -r p
  QDRANT_PORT="${p:-6333}"
fi
QDRANT_PORT="${QDRANT_PORT:-6333}"
# QDRANT_URL wins if explicitly exported; otherwise derive from the port.
QDRANT_URL="${QDRANT_URL:-http://localhost:$QDRANT_PORT}"
QDRANT_GRPC_PORT="${QDRANT_GRPC_PORT:-$((QDRANT_PORT + 1))}"
ok "qdrant: $QDRANT_URL"

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
  Q_URL="$QDRANT_URL" \
  python3 - "$id" <<'PY'
import json, os, re, sys
from pathlib import Path

name   = os.environ["SRV_NAME"]
cmd    = os.environ["RUN_CMD"]
args   = json.loads(os.environ["RUN_ARGS_JSON"])
vault  = os.environ["VAULT"]
qurl   = os.environ["Q_URL"]
fmt    = os.environ["CFG_FMT"]
path   = Path(os.environ["CFG_PATH"])

env = {"VAULT_PATH": vault, "QDRANT_URL": qurl}
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

# --- Qdrant bring-up --------------------------------------------------------
# If Qdrant isn't reachable, start it with this repo's docker-compose.yml.
# Skip entirely with SKIP_QDRANT=1. Non-fatal: a failure here still leaves
# the MCP config written (the server also auto-starts Qdrant at runtime).
# QDRANT_URL / QDRANT_PORT / QDRANT_GRPC_PORT were resolved above.

qdrant_reachable() {
  python3 - "$QDRANT_URL" <<'PY' >/dev/null 2>&1
import sys, urllib.request
urllib.request.urlopen(sys.argv[1], timeout=2)
PY
}

compose_cmd() {
  # Prefer the `docker compose` plugin; fall back to legacy `docker-compose`.
  if docker compose version >/dev/null 2>&1; then echo "docker compose"; return 0; fi
  command -v docker-compose >/dev/null 2>&1 && { echo "docker-compose"; return 0; }
  return 1
}

ensure_qdrant() {
  [ "${SKIP_QDRANT:-0}" = "1" ] && return 0
  say ""
  info "Checking Qdrant..."
  if qdrant_reachable; then
    ok "Qdrant already reachable at $QDRANT_URL"
    return 0
  fi
  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker not found — start Qdrant yourself or install Docker. (config is still written)"
    return 0
  fi
  if ! docker info >/dev/null 2>&1; then
    warn "Docker daemon not running — start Docker, then Qdrant auto-starts on first tool call."
    return 0
  fi
  local cc; cc="$(compose_cmd)" || {
    warn "docker compose not available — Qdrant will auto-start at runtime instead."
    return 0
  }
  say "  starting Qdrant on port $QDRANT_PORT via: $cc -f $REPO_DIR/docker-compose.yml up -d"
  if ! QDRANT_PORT="$QDRANT_PORT" QDRANT_GRPC_PORT="$QDRANT_GRPC_PORT" \
       $cc -f "$REPO_DIR/docker-compose.yml" up -d; then
    warn "compose up failed — the server will try to start Qdrant at runtime."
    return 0
  fi
  printf "  waiting for Qdrant"
  local i=0
  while [ "$i" -lt 30 ]; do
    if qdrant_reachable; then say ""; ok "Qdrant is up at $QDRANT_URL"; return 0; fi
    printf "."; sleep 1; i=$((i+1))
  done
  say ""
  warn "Qdrant did not become ready in 30s — check 'docker ps' / 'docker logs'."
}

# --- Apply -----------------------------------------------------------------
say ""
info "Writing config..."
WROTE=0; FAILED=0
for id in $SELECTED; do
  spec="$(config_target "$id")"
  [ -n "$spec" ] || { warn "$(t_name "$id"): unsupported, skipping"; continue; }
  fmt="${spec%%|*}"; path="${spec#*|}"
  printf "  %s%-12s%s " "$BOLD" "$(t_name "$id")" "$RESET"
  # A single client failing shouldn't abort the rest — capture and report it.
  if write_config "$fmt" "$path" "$id"; then
    WROTE=$((WROTE + 1))
  else
    FAILED=$((FAILED + 1))
    warn "could not write config for $(t_name "$id")"
  fi
done

ensure_qdrant

# --- Summary ---------------------------------------------------------------
say ""
if [ "$WROTE" -gt 0 ] && [ "$FAILED" -eq 0 ]; then
  ok "${BOLD}Success${RESET} — '$SERVER_NAME' configured for $WROTE client(s)."
  say "  ${DIM}vault:${RESET} $VAULT"
  say "  ${DIM}qdrant:${RESET} $QDRANT_URL"
  say "${DIM}Restart your AI client(s) to load the MCP server.${RESET}"
elif [ "$WROTE" -gt 0 ]; then
  warn "Partial: $WROTE client(s) configured, $FAILED failed. See messages above."
else
  die "no client config was written."
fi
