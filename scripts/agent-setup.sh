#!/usr/bin/env bash

set -eu

PROGRAM_NAME="${0##*/}"
INSTALL_AGENT=0
INSTALL_SKILLS=0
LIST_SKILLS=0

# Resolve the script itself, independently of the caller's project directory.
resolve_script_path() {
    local file="$1" directory link hops=0
    while [ -L "$file" ]; do
        [ "$hops" -lt 40 ] || { printf 'Too many script symlinks\n' >&2; return 1; }
        hops=$((hops + 1))
        directory="$(cd -P "$(dirname "$file")" && pwd -P)"
        link="$(readlink "$file")"
        case "$link" in /*) file="$link" ;; *) file="$directory/$link" ;; esac
    done
    directory="$(cd -P "$(dirname "$file")" && pwd -P)"
    printf '%s/%s\n' "$directory" "${file##*/}"
}
SCRIPT_PATH="$(resolve_script_path "${BASH_SOURCE[0]:-$0}")"
SCRIPT_DIR="${SCRIPT_PATH%/*}"
REPO="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
PROJECT_TARGET="$(pwd -P)"
SOURCE_ARCHIVE_URL=https://codeload.github.com/gwyntoria/skills/tar.gz/refs/heads/main
LATEST_SCRIPT_URL=https://raw.githubusercontent.com/gwyntoria/skills/main/scripts/agent-setup.sh
RESOURCE_TEMP=""
RESOURCE_PATH=""
STATUSLINE_SOURCE=""
RULE_SCOPE=global
RULE_TARGETS=both
SELECTED_RULES=()
SELECTED_RULE_SOURCES=()
RULE_NAMES_GLOBAL=()
RULE_NAMES_PROJECT=()
RULE_CATALOG_GLOBAL=0
RULE_CATALOG_PROJECT=0

WAZA_SKILLS_URL="https://github.com/tw93/waza"
KAMI_SKILLS_URL="https://github.com/tw93/kami"
MATTPOCOCK_SKILLS_URL="https://github.com/mattpocock/skills"
MATTPOCOCK_SKILLS_PAGE_URL="https://www.aihero.dev/skills"
HUMANLAYER_SKILLS_URL="https://github.com/humanlayer/skills"
GWYNTORIA_SKILLS_URL="https://github.com/gwyntoria/skills"
# Parallel arrays keep this compatible with the Bash shipped by macOS.
SKILL_NAMES=()
SKILL_SOURCES=()
SKILL_GROUPS=()
TARGET_AGENTS=(codex claude-code)
SUCCEEDED=()
FAILED=()
MENU_SELECTED=()
MENU_CURSORS=()
MENU_CHOICES=()
MENU_VISITED=()
KEY=""
REMOVE_CODEX=1
REMOVE_CLAUDE=1
REMOVE_RULES=0
REMOVE_SKILLS=0
REMOVAL_TEMP=""
REMOVAL_RULE_IDS=(); REMOVAL_RULE_LABELS=(); REMOVAL_SKILL_IDS=(); REMOVAL_SKILL_LABELS=(); REMOVAL_SKILL_GROUPS=()
REMOVAL_RULE_SELECTION=(); REMOVAL_SKILL_SELECTION=()
REPO_ITEM_LABELS=(); REPO_ITEM_GROUPS=(); REPO_SELECTED=()

log() { printf '\n==> %s\n' "$1"; }

usage() {
    cat <<EOF
Usage: $PROGRAM_NAME [--agent] [--skill] | --list

No arguments: open the interactive menu (requires a terminal).
  --agent     Install both CLIs, global rules, and Claude statusline
  --skill     Install/update all configured skills; preserve existing skills
  --list      List available skills by source without installing
  -h, --help  Show help

The menu also provides a separate, confirmed removal action with a backup.
EOF
}

parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --agent) INSTALL_AGENT=1 ;;
            --skill) INSTALL_SKILLS=1 ;;
            --list) LIST_SKILLS=1 ;;
            -h | --help) usage; return 1 ;;
            *) printf 'Error: unknown option: %s\n' "$1" >&2; return 2 ;;
        esac
        shift
    done
    if [ "$LIST_SKILLS" -eq 1 ] && [ "$((INSTALL_AGENT + INSTALL_SKILLS))" -gt 0 ]; then
        printf 'Error: --list cannot be combined with installation options.\n' >&2
        return 2
    fi
}

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        printf 'Error: required command not found: %s\n' "$1" >&2
        return 1
    fi
}

# Do not put the subshell in an if/! condition: that disables errexit inside
# called functions, allowing an earlier failed write to look successful.
run_item() {
    local label="$1" result
    shift
    case "$label" in Remove*) printf '\n==> \033[31m%s\033[0m\n' "$label" ;;
        *) printf '\n==> \033[32m%s\033[0m\n' "$label" ;; esac
    set +e
    ( set -e; set -o pipefail; "$@" ) </dev/null
    result=$?
    set -e
    if [ "$result" -eq 0 ]; then
        SUCCEEDED+=("$label")
    else
        FAILED+=("$label (exit $result)")
        printf 'Failed; continuing: %s\n' "$label" >&2
    fi
}

print_summary() {
    local item
    printf '\nResults: %s succeeded, %s failed\n' "${#SUCCEEDED[@]}" "${#FAILED[@]}"
    for item in "${SUCCEEDED[@]+"${SUCCEEDED[@]}"}"; do
        case "$item" in Remove*) printf '  OK    \033[31m%s\033[0m\n' "$item" ;;
            *) printf '  OK    \033[32m%s\033[0m\n' "$item" ;; esac
    done
    for item in "${FAILED[@]+"${FAILED[@]}"}"; do printf '  FAIL  \033[31m%s\033[0m\n' "$item"; done
    [ "${#FAILED[@]}" -eq 0 ]
}

print_skill_targets() {
    local name="$1" agent destination
    printf '  \033[32mShared skill / %s -> %s/.agents/skills/%s\033[0m\n' "$name" "$HOME" "$name"
    for agent in "${TARGET_AGENTS[@]}"; do
        if [ "$agent" = claude-code ]; then
            destination="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/$name"
            printf '  \033[32mClaude / %s -> %s\033[0m\n' "$name" "$destination"
        fi
    done
}

install_agent_skills() {
    local source="$1"
    shift
    local name
    for name in "$@"; do print_skill_targets "$name"; done
    npx --yes skills add "$source" --skill "$@" \
        --agent "${TARGET_AGENTS[@]}" --global --yes
}

# skills add --list is read-only. Restrict parsing to its Available Skills
# section and reject empty/unrecognised output rather than hiding a failure.
fetch_repository_skill_names() {
    local output
    output=$(NO_COLOR=1 npx --yes skills add "$1" --list </dev/null) || return $?
    printf '%s\n' "$output" | node -e '
        const fs = require("fs");
        const text = fs.readFileSync(0, "utf8").replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "");
        const section = text.split("Available Skills")[1] ?? "";
        const names = [...new Set([...section.matchAll(/^[│|] {3,4}([a-zA-Z0-9][a-zA-Z0-9._-]*)[ \t]*$/gm)].map(m => m[1]))];
        if (!names.length) {
            process.stderr.write("Error: skills --list returned no recognisable skill names.\n");
            process.exit(1);
        }
        console.log(names.join("\n"));
    '
}

fetch_mattpocock_skill_names() (
    set -o pipefail

    curl -fsSL --connect-timeout 10 --max-time 60 "$MATTPOCOCK_SKILLS_PAGE_URL" |
        node -e '
            const fs = require("fs");
            const html = fs.readFileSync(0, "utf8");
            // Restrict the allowlist to the homepage skill set, excluding other links.
            const section = html.match(/<section\b[^>]*\baria-labelledby=["\x27]skill-set-heading["\x27][^>]*>([\s\S]*?)<\/section>/i);
            const links = (section?.[1] ?? "").matchAll(
                /<a\b[^>]*\bhref=["\x27](?:https:\/\/www\.aihero\.dev)?\/skills-([a-z0-9][a-z0-9-]*)\/?["\x27][^>]*>/g
            );
            const names = [...new Set([...links].map(match => match[1]))];

            if (names.length === 0) {
                process.stderr.write("Error: no main skills found on the Matt Pocock skills page.\n");
                process.exit(1);
            }

            process.stdout.write(names.join("\n") + "\n");
        '
)

load_catalog() {
    local group source names name
    SKILL_NAMES=(); SKILL_SOURCES=(); SKILL_GROUPS=()
    for group in Waza Kami 'Matt Pocock' HumanLayer Gwyntoria; do
        case "$group" in
            Waza) source="$WAZA_SKILLS_URL" ;;
            Kami) source="$KAMI_SKILLS_URL" ;;
            'Matt Pocock') source="$MATTPOCOCK_SKILLS_URL" ;;
            HumanLayer) source="$HUMANLAYER_SKILLS_URL" ;;
            Gwyntoria) source="$GWYNTORIA_SKILLS_URL" ;;
        esac
        printf 'Loading %s...\n' "$group" >&2
        if [ "$group" = 'Matt Pocock' ]; then
            if ! names=$(fetch_mattpocock_skill_names); then
                FAILED+=("Catalog: $group ($source)")
                continue
            fi
        elif [ "$group" = HumanLayer ]; then
            names=show-me
        elif ! names=$(fetch_repository_skill_names "$source"); then
            FAILED+=("Catalog: $group ($source)")
            continue
        fi
        while IFS= read -r name; do
            if [[ ! "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then
                FAILED+=("Catalog: $group (invalid skill name)")
                continue
            fi
            SKILL_NAMES+=("$name")
            SKILL_SOURCES+=("$source")
            SKILL_GROUPS+=("$group")
        done <<<"$names"
    done
    for name in "${FAILED[@]+"${FAILED[@]}"}"; do printf 'Unavailable: %s\n' "$name" >&2; done
}

print_catalog() {
    local i previous=""
    for ((i=0; i<${#SKILL_NAMES[@]}; i++)); do
        if [ "$previous" != "${SKILL_GROUPS[i]}" ]; then
            previous="${SKILL_GROUPS[i]}"
            printf '\n%s (%s):\n' "$previous" "${SKILL_SOURCES[i]}"
        fi
        printf '  %s\n' "${SKILL_NAMES[i]}"
    done
}

cleanup_setup_resources() {
    if [ -t 1 ]; then printf '\033[?25h'; fi
    if [ -n "$RESOURCE_TEMP" ]; then rm -rf -- "$RESOURCE_TEMP"; fi
    if [ -n "$REMOVAL_TEMP" ]; then rm -rf -- "$REMOVAL_TEMP"; fi
}

resolve_resource() {
    local relative="$1" candidate="$REPO/$1"
    case "$relative" in rules/global | rules/project | scripts/statusline.sh) ;; *) return 2 ;; esac
    if [ -e "$candidate" ] || [ -L "$candidate" ]; then
        RESOURCE_PATH="$candidate"
    else
        require_command curl || return 1
        require_command tar || return 1
        if [ -z "$RESOURCE_TEMP" ]; then
            RESOURCE_TEMP="$(mktemp -d)" || return 1
            trap cleanup_setup_resources EXIT
            trap 'exit 130' INT
            trap 'exit 143' TERM
        fi
        if [ ! -f "$RESOURCE_TEMP/source.tar.gz" ]; then
            printf 'Fetching resources from GitHub main...\n' >&2
            curl -fLsS "$SOURCE_ARCHIVE_URL" -o "$RESOURCE_TEMP/download.tar.gz" || return 1
            mv "$RESOURCE_TEMP/download.tar.gz" "$RESOURCE_TEMP/source.tar.gz" || return 1
        fi
        candidate="$RESOURCE_TEMP/skills-main/$relative"
        if [ ! -e "$candidate" ]; then
            tar -xzf "$RESOURCE_TEMP/source.tar.gz" -C "$RESOURCE_TEMP" -- "skills-main/$relative" || return 1
        fi
        RESOURCE_PATH="$candidate"
    fi
    case "$relative" in
        rules/*) [ -d "$RESOURCE_PATH" ] ;;
        *) [ -f "$RESOURCE_PATH" ] ;;
    esac || { printf 'Invalid resource: %s\n' "$RESOURCE_PATH" >&2; return 1; }
}

load_rule_catalog() {
    local file name title names=()
    resolve_resource "rules/$RULE_SCOPE" || return 1
    for file in "$RESOURCE_PATH"/*.md; do
        [ -f "$file" ] || continue
        name="${file##*/}"; name="${name%.md}"
        if [[ ! "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then
            printf 'Invalid rule name: %s\n' "$file" >&2; return 1
        fi
        title=""
        IFS= read -r title <"$file" || true
        case "$title" in '# '*) ;; *) printf 'Rule must start with H1: %s\n' "$file" >&2; return 1 ;; esac
        names+=("$name")
    done
    if [ "$RULE_SCOPE" = global ]; then
        RULE_NAMES_GLOBAL=("${names[@]+"${names[@]}"}"); RULE_CATALOG_GLOBAL=1
    else
        RULE_NAMES_PROJECT=("${names[@]+"${names[@]}"}"); RULE_CATALOG_PROJECT=1
    fi
}

install_setup_command() (
    set -e
    local directory="$HOME/.local/bin" temporary
    case "${HOME:-}" in /*) [ "$HOME" != / ] ;; *) return 1 ;; esac
    mkdir -p "$directory"
    temporary="$(mktemp "$directory/.agent-setup.XXXXXX")"
    trap 'rm -f -- "$temporary"' EXIT
    if [ "${SCRIPT_PATH##*/}" = agent-setup.sh ] &&
        [ "${SCRIPT_DIR##*/}" = scripts ] && [ -d "$REPO/rules" ]; then
        cp "$SCRIPT_PATH" "$temporary"
    else
        require_command curl
        curl -fLsS "$LATEST_SCRIPT_URL" -o "$temporary"
    fi
    [ -s "$temporary" ] || { printf 'Downloaded script is empty.\n' >&2; return 1; }
    bash -n "$temporary"
    chmod 0755 "$temporary"
    mv -f "$temporary" "$directory/agent-setup"
    printf '\033[32mInstalled: %s/agent-setup (used on next launch)\033[0m\n' "$directory"
    # Print the PATH command literally for the user.
    # shellcheck disable=SC2016
    case ":$PATH:" in
        *":$directory:"*) ;;
        *) printf 'Add this directory to PATH in your shell config:\n  export PATH="$HOME/.local/bin:$PATH"\n' ;;
    esac
)

apply_rule() {
    if [ "${4:-install}" = install ]; then resolve_resource "rules/${5:-$2}" || return 1; fi
    rule_engine "$1" "$2" "$3" "${4:-install}" "$RESOURCE_PATH" "${5:-$2}"
}

# The rule engine owns its helpers and traps only inside this subshell.
rule_engine() (
    set -euo pipefail
    PROGRAM_NAME='agent-setup.sh'
    RULE="$1"; SCOPE="$2"; TARGET_OPT="$3"; MODE="${4:-install}"
    RULE_FILE="$RULE.md"; RULE_CLASSIFICATION="${6:-$SCOPE}"; RULE_SOURCE=""; RULE_TITLE=""
    MARKER_PREFIX=gwyn-space-skills
    MIGRATE_LEGACY=1; TARGETS=""; SCOPES=""; FAILURES=0; SCRATCH_DIR=""
    PROJECT_DIR=""
    case "$SCOPE" in global | project) ;; *) return 2 ;; esac
    if [[ ! "$RULE" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then return 2; fi
    if [ "$MODE" = install ]; then
        RULE_SOURCE="$5/$RULE_FILE"
        [ -f "$RULE_SOURCE" ] || { printf 'Missing rule: %s\n' "$RULE_SOURCE" >&2; return 1; }
        IFS= read -r RULE_TITLE <"$RULE_SOURCE" || true
        case "$RULE_TITLE" in '# '*) ;; *) printf 'Rule must start with H1: %s\n' "$RULE_SOURCE" >&2; return 1 ;; esac
    fi

log() {
    printf '\n\033[1;32m==> %s\033[0m\n' "$1"
}

success() {
    printf '\033[1;32m✓ %s\033[0m\n' "$1"
}

warn() {
    printf '\033[1;33m! %s\033[0m\n' "$1" >&2
}

error() {
    printf '\033[31mError: %s\033[0m\n' "$1" >&2
}


RESOLVED_IS_LINK=0
resolve_symlinks() {
    local path="$1"
    local directory
    local link
    local hops=0

    RESOLVED_IS_LINK=0

    while [ -L "$path" ]; do
        if [ "$hops" -ge 8 ]; then
            error "too many symlink hops resolving $1"
            return 1
        fi
        hops=$((hops + 1))
        RESOLVED_IS_LINK=1
        directory="$(cd -P "$(dirname "$path")" && pwd -P)" || return 1
        link="$(readlink "$directory/$(basename "$path")")" || return 1
        case "$link" in
        /*) path="$link" ;;
        *) path="$directory/$link" ;;
        esac
    done

    if [ -d "$(dirname "$path")" ]; then
        directory="$(cd -P "$(dirname "$path")" && pwd -P)" || return 1
        path="$directory/$(basename "$path")"
    fi

    printf '%s\n' "$path"
    return 0
}


require_safe_home() {
    if [ -z "${HOME:-}" ] || [ "$HOME" = "/" ]; then
        error "HOME is empty or unsafe."
        exit 1
    fi

    case "$HOME" in
    /*) ;;
    *)
        error "HOME must be an absolute path."
        exit 1
        ;;
    esac
}


resolve_targets() {
    local resolved=""
    local name

    case "$TARGET_OPT" in
    claude | codex)
        resolved="$TARGET_OPT"
        ;;
    both)
        resolved="claude codex"
        ;;
    auto)
        # Autodetection never creates an agent's directory: doing so would
        # pollute a machine that does not run that agent.
        for name in claude codex; do
            if [ -d "$HOME/.$name" ]; then
                resolved="${resolved:+$resolved }$name"
            fi
        done
        if [ -z "$resolved" ]; then
            error "neither $HOME/.claude nor $HOME/.codex exists; pass --target explicitly."
            return 1
        fi
        ;;
    *)
        error "unknown target: $TARGET_OPT (expected claude, codex, both, or auto)"
        return 1
        ;;
    esac

    TARGETS="$resolved"
    return 0
}


resolve_project_dir() {
    PROJECT_DIR="$PROJECT_TARGET"

    # Never mkdir a directory that was not there: a typo would quietly create a
    # tree that nothing loads rules from.
    if [ ! -d "$PROJECT_DIR" ]; then
        error "project directory does not exist: $PROJECT_DIR"
        return 1
    fi

    if [ "$PROJECT_DIR" = "/" ]; then
        error "refusing to use / as a project directory."
        return 1
    fi

    PROJECT_DIR="$(cd -P "$PROJECT_DIR" && pwd -P)"
    return 0
}

# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------

claude_rule_path() {
    case "$1" in
    global)
        if [ "$RULE" = "agent-behavior" ]; then
            printf '%s\n' "$HOME/.claude/CLAUDE.md"
        else
            printf '%s\n' "$HOME/.claude/rules/$RULE_FILE"
        fi
        ;;
    project) printf '%s\n' "$PROJECT_DIR/.claude/rules/$RULE_FILE" ;;
    esac
}

codex_file_path() {
    case "$1" in
    global) printf '%s\n' "$HOME/.codex/AGENTS.md" ;;
    project) printf '%s\n' "$PROJECT_DIR/AGENTS.md" ;;
    esac
}

start_marker() {
    printf '<!-- %s: %s:start -->\n' "$MARKER_PREFIX" "$RULE"
}

end_marker() {
    printf '<!-- %s: %s:end -->\n' "$MARKER_PREFIX" "$RULE"
}

# GNU stat first, BSD second. `chmod --reference` is not an option: it is GNU
# only, and this script runs on macOS.
mode_of() {
    local file="$1"
    local mode=""

    mode="$(stat -c '%a' "$file" 2>/dev/null)" || mode=""
    if [ -z "$mode" ]; then
        mode="$(stat -f '%Lp' "$file" 2>/dev/null)" || mode=""
    fi
    if [ -z "$mode" ]; then
        mode="644"
    fi

    printf '%s\n' "$mode"
}

# ------------------------------------------------------------
# Atomic writes
# ------------------------------------------------------------

# Replace $destination with $source in one rename: build the new bytes beside the
# destination (so the rename stays on one filesystem), then swap. A partial write
# can therefore never be observed at the destination path.
atomic_write() {
    local destination="$1"
    local source="$2"
    local directory
    local base
    local mode
    local temporary

    directory="$(dirname "$destination")"
    base="$(basename "$destination")"

    if [ -e "$destination" ]; then
        mode="$(mode_of "$destination")"
    else
        mode="644"
    fi

    temporary="$(mktemp "$directory/.${base}.tmp.XXXXXX")" || return 1

    if ! cat "$source" >"$temporary"; then
        rm -f "$temporary"
        return 1
    fi
    if ! chmod "$mode" "$temporary"; then
        rm -f "$temporary"
        return 1
    fi
    if ! mv -f "$temporary" "$destination"; then
        rm -f "$temporary"
        return 1
    fi

    return 0
}

# ------------------------------------------------------------
# Marker blocks
# ------------------------------------------------------------

# Line endings are compared after stripping a trailing CR but printed unmodified,
# so a file touched by a Windows editor still matches its own markers and keeps
# its original bytes everywhere the block is not.
count_marker_lines() {
    local file="$1"
    local marker="$2"

    if [ ! -f "$file" ]; then
        printf '0\n'
        return 0
    fi

    awk -v marker="$marker" '
        { line = $0; sub(/\r$/, "", line) }
        line == marker { n++ }
        END { print n + 0 }
    ' "$file"
}

marker_line_numbers() {
    local file="$1"
    local marker="$2"

    awk -v marker="$marker" '
        { line = $0; sub(/\r$/, "", line) }
        line == marker { printf "%d ", NR }
        END { printf "\n" }
    ' "$file"
}

# Refuse to guess when the markers do not pair up: a start with no end would
# otherwise delete everything after it.
assert_markers_balanced() {
    local file="$1"
    local start
    local end
    local starts
    local ends

    [ -f "$file" ] || return 0

    start="$(start_marker)"
    end="$(end_marker)"
    starts="$(count_marker_lines "$file" "$start")"
    ends="$(count_marker_lines "$file" "$end")"

    if [ "$starts" -eq 0 ] && [ "$ends" -eq 0 ]; then
        return 0
    fi

    if [ "$starts" -eq 1 ] && [ "$ends" -eq 1 ]; then
        return 0
    fi

    error "unbalanced markers in $file"
    printf '  start markers at lines: %s\n' "$(marker_line_numbers "$file" "$start")" >&2
    printf '  end markers at lines:   %s\n' "$(marker_line_numbers "$file" "$end")" >&2
    printf '  Fix the markers by hand, then re-run.\n' >&2
    return 1
}

# Build the managed block: markers, a provenance line, then the rule body.
# Project-classified rules omit their H1 in Codex AGENTS.md files. agent-behavior.md
# keeps its title, and every Claude destination keeps the source verbatim.
write_block() {
    local output="$1"
    local body="$2"
    local eol="$3"
    local omit_h1="$4"
    local start
    local end
    local line
    local line_number=0

    start="$(start_marker)"
    end="$(end_marker)"

    {
        printf '%s%s\n' "$start" "$eol"
        printf '<!-- Installed from rules/%s by %s. Edits inside this block are overwritten on reinstall. -->%s\n' \
            "$RULE_CLASSIFICATION/$RULE_FILE" "$PROGRAM_NAME" "$eol"
        while IFS= read -r line || [ -n "$line" ]; do
            line_number=$((line_number + 1))
            if [ "$omit_h1" -eq 1 ] && [ "$line_number" -eq 1 ]; then
                continue
            fi
            printf '%s%s\n' "$line" "$eol"
        done <"$body"
        printf '%s%s\n' "$end" "$eol"
    } >"$output"

    return 0
}

# Produce the file $destination should become: everything outside the block kept
# byte-for-byte, the block replaced or appended. Trailing blank lines left behind
# by a removed block are dropped by holding them back until a real line arrives.
merge_block() {
    local destination="$1"
    local block_file="$2"
    local output="$3"
    local start
    local end
    local eol=""

    start="$(start_marker)"
    end="$(end_marker)"

    if [ -f "$destination" ] && grep -qU $'\r' "$destination" 2>/dev/null; then
        eol=$'\r'
    fi

    if [ -f "$destination" ]; then
        awk -v start="$start" -v end="$end" '
            { line = $0; sub(/\r$/, "", line) }
            line == start { removing = 1; next }
            removing && line == end { removing = 0; next }
            removing { next }
            {
                if ($0 ~ /^[ \t\r]*$/) {
                    blanks = blanks $0 "\n"
                } else {
                    printf "%s", blanks
                    blanks = ""
                    print
                }
            }
        ' "$destination" >"$output"
    else
        : >"$output"
    fi

    # An empty block file means "remove the block and add nothing back", which is
    # how --remove reuses this path. The strip above has already flushed every
    # trailing blank line, so there is nothing left to append.
    if [ ! -s "$block_file" ]; then
        return 0
    fi

    # Use the file's own line ending for the separator too, or a CRLF file ends
    # up with one bare-LF line in the middle.
    if [ -s "$output" ]; then
        printf '%s\n' "$eol" >>"$output"
    fi
    cat "$block_file" >>"$output"

    return 0
}

# ------------------------------------------------------------
# Legacy copies
# ------------------------------------------------------------
# Older config_agent.sh versions wrote global.md straight over CLAUDE.md and
# AGENTS.md. The immediately previous setup-rule.sh version also installed a
# duplicate at ~/.claude/rules/global.md.

timestamp() {
    date -u '+%Y%m%dT%H%M%SZ'
}

remove_legacy_claude_global_rule() {
    local legacy="$HOME/.claude/rules/global.md"
    local backup

    [ "$RULE" = "agent-behavior" ] || return 0
    [ -e "$legacy" ] || [ -L "$legacy" ] || return 0

    if [ -L "$legacy" ]; then
        warn "$legacy is a symlink; remove it manually before installing agent-behavior.md."
        return 1
    fi

    if ! cmp -s "$legacy" "$RULE_SOURCE"; then
        warn "$legacy differs from $RULE_FILE; it was left in place."
        warn "Remove or reconcile it before installing agent-behavior.md into CLAUDE.md."
        return 1
    fi

    backup="$HOME/.claude/global.md.pre-claude-md.bak-$(timestamp)"

    if ! mv "$legacy" "$backup"; then
        error "could not move obsolete $legacy aside"
        return 1
    fi

    printf '\033[36mMoved obsolete Claude rule to %s\033[0m\n' "$backup"
    printf '\033[36m  Restore with: mv "%s" "%s"\033[0m\n' "$backup" "$legacy"
    return 0
}

# A byte-identical AGENTS.md has no markers, so appending would leave the rule in
# the file twice. Refuse, unless migration was explicitly requested.
adopt_legacy_managed_file() {
    local destination="$1"
    local stamp
    local backup

    [ -f "$destination" ] || return 1

    if ! cmp -s "$destination" "$RULE_SOURCE"; then
        if grep -qF -- "$RULE_TITLE" "$destination" 2>/dev/null; then
            warn "$destination contains an unmanaged copy of $RULE_FILE; see lines $(marker_line_numbers "$destination" "$RULE_TITLE")."
        fi
        return 1
    fi

    if [ "$MIGRATE_LEGACY" -ne 1 ]; then
        error "$destination is byte-identical to $RULE_FILE and has no managed block."
        printf '  Appending would leave two copies in the file the agent loads every session.\n' >&2
        printf '  Use the Rules installer to migrate the legacy copy with a backup.\n' >&2
        return 2
    fi

    stamp="$(timestamp)"
    backup="$destination.pre-rules.bak-$stamp"

    if ! cp -p "$destination" "$backup"; then
        error "could not back up $destination"
        return 2
    fi

    printf '\033[36mBacked up the legacy copy to %s\033[0m\n' "$backup"
    printf '\033[36m  Restore with: mv "%s" "%s"\033[0m\n' "$backup" "$destination"

    # Tell the caller the current content should be discarded.
    return 0
}

# ------------------------------------------------------------
# Claude Code
# ------------------------------------------------------------

install_claude() {
    local scope="$1"
    local target
    local destination
    local resolved
    local backup

    if [ "$RULE" = "agent-behavior" ] && [ "$scope" = "global" ]; then
        install_managed_file claude "$scope"
        return $?
    fi

    if [ "$scope" = "global" ]; then
        target="$HOME/.claude/rules"
    else
        target="$PROJECT_DIR/.claude/rules"
    fi

    mkdir -p "$target"

    destination="$target/$RULE_FILE"

    if ! resolved="$(resolve_symlinks "$destination")"; then
        error "could not resolve $destination"
        return 1
    fi
    if [ "$RESOLVED_IS_LINK" -eq 1 ]; then
        printf '  %s is a symlink; writing through to %s\n' "$destination" "$resolved"
    fi

    if [ -e "$resolved" ] && ! cmp -s "$resolved" "$RULE_SOURCE"; then
        if ! head -n 1 "$resolved" | grep -qF -- "$RULE_TITLE"; then
            # Not ours. Keep the bytes, but never leave a .md backup behind:
            # Claude Code would load it as another rule.
            backup="$resolved.bak-$(timestamp)"
            if ! cp -p "$resolved" "$backup"; then
                error "could not back up $resolved"
                return 1
            fi
            warn "$resolved was replaced; the previous file is at $backup"
        fi
    fi

    if [ -e "$resolved" ] && cmp -s "$resolved" "$RULE_SOURCE"; then
        success "already current (claude, $scope): $resolved"
        return 0
    fi

    if ! atomic_write "$resolved" "$RULE_SOURCE"; then
        error "could not write $resolved"
        return 1
    fi

    success "installed (claude, $scope): $resolved"
    return 0
}

remove_claude() {
    local scope="$1"
    local destination
    local resolved

    if [ "$RULE" = "agent-behavior" ] && [ "$scope" = "global" ]; then
        remove_managed_file claude "$scope"
        return $?
    fi

    destination="$(claude_rule_path "$scope")"

    if [ ! -e "$destination" ] && [ ! -L "$destination" ]; then
        printf '  not installed (claude, %s): %s\n' "$scope" "$destination"
        return 0
    fi

    if [ -L "$destination" ] && [ ! -e "$destination" ]; then
        rm -f "$destination"
        success "removed dangling link (claude, $scope): $destination"
        return 0
    fi

    if ! resolved="$(resolve_symlinks "$destination")"; then
        error "could not resolve $destination"
        return 1
    fi

    if [ "$RESOLVED_IS_LINK" -eq 1 ]; then
        rm -f "$destination"
        success "removed link (claude, $scope): $destination"
        printf '  The linked target was left in place: %s\n' "$resolved"
        return 0
    fi

    if ! head -n 1 "$resolved" | grep -qF -- "$RULE_TITLE"; then
        warn "not managed by $PROGRAM_NAME, left alone: $resolved"
        return 1
    fi

    rm -f "$resolved"
    success "removed (claude, $scope): $resolved"
    return 0
}

# ------------------------------------------------------------
# Managed instruction files
# ------------------------------------------------------------

# $1 target, $2 scope, $3 1 when the destination's current content must be discarded
# (legacy adoption).
write_managed_block() {
    local target="$1"
    local scope="$2"
    local discard_existing="$3"
    local destination
    local resolved
    local directory
    local block_file
    local merged_file
    local eol=""
    local omit_h1=0

    case "$target" in
    claude) destination="$(claude_rule_path "$scope")" ;;
    codex) destination="$(codex_file_path "$scope")" ;;
    esac

    if ! resolved="$(resolve_symlinks "$destination")"; then
        error "could not resolve $destination"
        return 1
    fi
    if [ "$RESOLVED_IS_LINK" -eq 1 ]; then
        printf '  %s is a symlink; writing through to %s\n' "$destination" "$resolved"
    fi

    directory="$(dirname "$resolved")"

    if ! mkdir -p "$directory"; then
        error "could not create $directory"
        return 1
    fi

    mkdir -p "$SCRATCH_DIR"
    block_file="$SCRATCH_DIR/block"
    merged_file="$SCRATCH_DIR/merged"

    if [ -f "$resolved" ] && grep -qU $'\r' "$resolved" 2>/dev/null; then
        eol=$'\r'
    fi

    if [ "$target" = "codex" ] && [ "$RULE_CLASSIFICATION" = "project" ]; then
        omit_h1=1
    fi

    write_block "$block_file" "$RULE_SOURCE" "$eol" "$omit_h1"

    if [ "$discard_existing" -eq 1 ] && [ -f "$resolved" ]; then
        : >"$merged_file"
        cat "$block_file" >>"$merged_file"
    else
        merge_block "$resolved" "$block_file" "$merged_file"
    fi

    if [ -f "$resolved" ] && cmp -s "$resolved" "$merged_file"; then
        success "already current ($target, $scope): $resolved"
        return 0
    fi

    if ! atomic_write "$resolved" "$merged_file"; then
        error "could not write $resolved"
        return 1
    fi

    success "installed ($target, $scope): $resolved"

    return 0
}

install_managed_file() {
    local target="$1"
    local scope="$2"
    local destination
    local override
    # Tri-state, and the initial value matters: 1 means "no legacy copy was
    # involved", which must merge rather than discard. Reusing a two-state flag
    # here would drop everything outside the block on an ordinary re-install.
    #   1 = nothing to adopt, 0 = adopted, 2 = refused
    local adopt_status=1

    case "$target" in
    claude) destination="$(claude_rule_path "$scope")" ;;
    codex) destination="$(codex_file_path "$scope")" ;;
    esac

    # Checked before the write decision, not after it: AGENTS.override.md wins
    # over AGENTS.md, so the rule is inert even when nothing needed writing.
    if [ "$target" = "codex" ]; then
        override="$(dirname "$destination")/AGENTS.override.md"
        if [ -f "$override" ]; then
            warn "$override exists and takes precedence; Codex will not read $(basename "$destination")."
        fi
    fi

    if ! assert_markers_balanced "$destination"; then
        return 1
    fi

    if [ "$scope" = "global" ] &&
        [ "$(count_marker_lines "$destination" "$(start_marker)")" -eq 0 ]; then
        # Not in a condition context, and the function returns non-zero for the
        # ordinary "no legacy copy" case, so capture instead of letting set -e
        # abort.
        adopt_status=0
        adopt_legacy_managed_file "$destination" || adopt_status=$?
        if [ "$adopt_status" -eq 2 ]; then
            return 1
        fi
    fi

    if [ "$adopt_status" -eq 0 ]; then
        write_managed_block "$target" "$scope" 1
    else
        write_managed_block "$target" "$scope" 0
    fi
}

remove_managed_file() {
    local target="$1"
    local scope="$2"
    local destination
    local resolved
    local rendered

    case "$target" in
    claude) destination="$(claude_rule_path "$scope")" ;;
    codex) destination="$(codex_file_path "$scope")" ;;
    esac

    if [ ! -f "$destination" ]; then
        printf '  not installed (%s, %s): %s\n' "$target" "$scope" "$destination"
        return 0
    fi

    if ! assert_markers_balanced "$destination"; then
        return 1
    fi

    if [ "$(count_marker_lines "$destination" "$(start_marker)")" -eq 0 ]; then
        printf '  not installed (%s, %s): %s\n' "$target" "$scope" "$destination"
        return 0
    fi

    if ! resolved="$(resolve_symlinks "$destination")"; then
        error "could not resolve $destination"
        return 1
    fi

    mkdir -p "$SCRATCH_DIR"
    rendered="$SCRATCH_DIR/rendered"

    # A block with no body: reusing the merge path keeps the surrounding bytes
    # intact and drops the blank lines the block leaves behind.
    : >"$SCRATCH_DIR/empty"
    merge_block "$resolved" "$SCRATCH_DIR/empty" "$rendered"

    if cmp -s "$resolved" "$rendered"; then
        printf '  not installed (%s, %s): %s\n' "$target" "$scope" "$resolved"
        return 0
    fi

    if ! atomic_write "$resolved" "$rendered"; then
        error "could not write $resolved"
        return 1
    fi

    success "removed ($target, $scope): $resolved"
    return 0
}

# ------------------------------------------------------------
# Codex
# ------------------------------------------------------------

install_codex() {
    install_managed_file codex "$1"
}

remove_codex() {
    remove_managed_file codex "$1"
}

# ------------------------------------------------------------
# Pre-flight
# ------------------------------------------------------------

# Check every planned destination before the first write, so a failure on the
# second target cannot leave the first one installed.
preflight() {
    local target
    local scope
    local directory

    for target in $TARGETS; do
        case "$target" in
        claude)
            for scope in $SCOPES; do
                if [ "$RULE" = "agent-behavior" ] && [ "$scope" = "global" ]; then
                    directory="$HOME/.claude"
                elif [ "$scope" = "global" ]; then
                    directory="$HOME/.claude/rules"
                else
                    directory="$PROJECT_DIR/.claude/rules"
                fi
                if ! mkdir -p "$directory"; then
                    error "cannot create $directory"
                    return 1
                fi
                if [ ! -w "$directory" ]; then
                    error "cannot write to $directory"
                    return 1
                fi
            done
            ;;
        codex)
            for scope in $SCOPES; do
                if [ "$scope" = "global" ]; then
                    directory="$HOME/.codex"
                else
                    directory="$PROJECT_DIR"
                fi
                if [ ! -d "$directory" ]; then
                    if ! mkdir -p "$directory"; then
                        error "cannot create $directory"
                        return 1
                    fi
                fi
                if [ ! -w "$directory" ]; then
                    error "cannot write to $directory"
                    return 1
                fi
            done
            ;;
        esac
    done

    return 0
}


# Invoked by the EXIT trap below.
# shellcheck disable=SC2329
cleanup_scratch() {
    if [ -n "$SCRATCH_DIR" ] && [ -d "$SCRATCH_DIR" ]; then
        rm -rf "$SCRATCH_DIR"
    fi
    return 0
}

run() {
    local target
    local scope
    local status

    if [ "$SCOPE" = "everywhere" ] || [ "$SCOPE" = "project" ]; then
        resolve_project_dir || return 1
    fi

    if [ "$SCOPE" = "everywhere" ]; then
        SCOPES="global project"
    else
        SCOPES="$SCOPE"
    fi

    SCRATCH_DIR="$(mktemp -d)" || return 1
    trap cleanup_scratch EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    resolve_targets || return 1

    if [ "$MODE" = "install" ]; then
        preflight || return 1

        log "Installing $RULE_FILE"

        case " $TARGETS " in
        *" claude "*)
            if { [ "$SCOPE" = "everywhere" ] || [ "$SCOPE" = "global" ]; } &&
                ! remove_legacy_claude_global_rule; then
                error "obsolete Claude rule must be resolved before installation."
                return 1
            fi
            ;;
        esac
    else
        log "Removing $RULE_FILE"
    fi

    for target in $TARGETS; do
        for scope in $SCOPES; do
            status=0
            case "$target" in
            claude)
                if [ "$MODE" = "install" ]; then
                    install_claude "$scope" || status=1
                else
                    remove_claude "$scope" || status=1
                fi
                ;;
            codex)
                if [ "$MODE" = "install" ]; then
                    install_codex "$scope" || status=1
                else
                    remove_codex "$scope" || status=1
                fi
                ;;
            esac
            if [ "$status" -ne 0 ]; then
                FAILURES=$((FAILURES + 1))
            fi
        done
    done

    if [ "$FAILURES" -ne 0 ]; then
        printf '\n'
        error "$FAILURES destination(s) did not complete."
        return 1
    fi

    return 0
}


    require_safe_home
    run
)

# 安装 Claude Code 状态栏脚本，并把 statusLine 写进 settings.json。
# settings.json 已存在时只更新 statusLine 键，其余配置原样保留；
# 文件不是合法 JSON 就报错退出，不覆盖用户原有内容。
install_statusline() {
    local claude_dir="$HOME/.claude"
    local settings_file="$claude_dir/settings.json"
    resolve_resource scripts/statusline.sh
    STATUSLINE_SOURCE="$RESOURCE_PATH"
    printf '\033[32mStatusline target: %s/statusline.sh\nSettings target: %s\033[0m\n' "$claude_dir" "$settings_file"

    mkdir -p "$claude_dir"

    install -m 0755 "$STATUSLINE_SOURCE" "$claude_dir/statusline.sh"

    # 单引号里是 JS 而不是 shell：~ 原样写进 JSON，交给 Claude Code 执行命令时展开，
    # ${settingsPath} 是 JS 模板字符串。这两处故意如此。
    # shellcheck disable=SC2088,SC2016
    node -e '
        const fs = require("fs");
        const [settingsPath, command] = process.argv.slice(1);
        let settings = {};

        if (fs.existsSync(settingsPath)) {
            try {
                settings = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
            } catch (error) {
                process.stderr.write(`Error: cannot parse ${settingsPath}: ${error.message}\n`);
                process.exit(1);
            }
        }

        settings.statusLine = { type: "command", command };

        const temporaryPath = `${settingsPath}.tmp`;
        fs.writeFileSync(temporaryPath, `${JSON.stringify(settings, null, 2)}\n`);
        fs.renameSync(temporaryPath, settingsPath);
    ' "$settings_file" "~/.claude/statusline.sh"
}

install_codex() {
    if ! command -v codex >/dev/null 2>&1; then curl -fsSL https://chatgpt.com/codex/install.sh | sh; fi
    require_command codex
    printf '\033[32mCodex CLI: %s\033[0m\n' "$(command -v codex)"
}

install_claude() {
    if ! command -v claude >/dev/null 2>&1; then curl -fsSL https://claude.ai/install.sh | bash; fi
    require_command claude
    printf '\033[32mClaude Code CLI: %s\033[0m\n' "$(command -v claude)"
}

install_global_rules() {
    apply_rule agent-behavior global both
}

# No stty mode changes: read -s restores echo even on cancellation/signals.
read_key() {
    local suffix=""
    KEY=""
    IFS= read -rsn1 KEY || return 1
    if [ "$KEY" = $'\e' ]; then
        IFS= read -rsn2 -t 1 suffix || true
        KEY="$KEY$suffix"
    fi
}

# Fixed-height pages keep long skill catalogs usable in a small terminal.
# Save each page's selection/cursor before reading a key, including Back/Exit.
# Return 0 to continue, 1 to exit, 2 to go back, or 3 on plan preparation failure.
choose_items() {
    local status=0
    printf '\033[?25l'
    choose_items_page "$@" || status=$?
    printf '\033[?25h'
    return "$status"
}

choose_items_page() {
    local page="$1" title="$2" multiple="$3" defaults="$4"
    shift 4
    local options=("$@") selected=() restored=() cursor=0 i start end mark
    for ((i=0; i<${#options[@]}; i++)); do selected+=("$defaults"); done
    if [ "${MENU_VISITED[page]:-0}" -eq 1 ]; then
        cursor="${MENU_CURSORS[page]}"
        for ((i=0; i<${#options[@]}; i++)); do selected[i]=0; done
        IFS=' ' read -r -a restored <<<"${MENU_CHOICES[page]}"
        for i in "${restored[@]+"${restored[@]}"}"; do selected[i]=1; done
    fi
    while :; do
        MENU_SELECTED=()
        for ((i=0; i<${#options[@]}; i++)); do
            [ "${selected[i]}" -eq 0 ] || MENU_SELECTED+=("$i")
        done
        MENU_VISITED[page]=1
        MENU_CURSORS[page]="$cursor"
        MENU_CHOICES[page]="${MENU_SELECTED[*]}"
        printf '\033[H\033[2J%s\n' "$title"
        printf 'Up/Down: move'
        if [ "$multiple" -eq 1 ]; then printf ' | Space: select | a: all | n: none'; fi
        printf ' | Enter: continue'
        if [ "$page" -ne 0 ]; then printf ' | b: back'; fi
        printf ' | q: exit\n\n'
        if [ "$page" -eq 11 ]; then print_install_plan || return 3; printf '\n'; fi
        start=$((cursor / 8 * 8)); end=$((start + 8))
        for ((i=start; i<end && i<${#options[@]}; i++)); do
            mark=' '; [ "${selected[i]}" -eq 0 ] || mark=x
            if [ "$i" -eq "$cursor" ]; then printf '> '; else printf '  '; fi
            if [ "$multiple" -eq 1 ]; then printf '[%s] ' "$mark"; fi
            printf '%s\n' "${options[i]}"
        done
        printf '\nItem %s/%s\n' "$((cursor + 1))" "${#options[@]}"
        read_key || return 1
        case "$KEY" in
            $'\e[A' | $'\eOA') cursor=$(((cursor + ${#options[@]} - 1) % ${#options[@]})) ;;
            $'\e[B' | $'\eOB') cursor=$(((cursor + 1) % ${#options[@]})) ;;
            ' ')
                if [ "$multiple" -eq 1 ]; then selected[cursor]=$((1 - selected[cursor])); fi ;;
            a | n)
                if [ "$multiple" -eq 1 ]; then
                    for ((i=0; i<${#options[@]}; i++)); do
                        selected[i]=0; [ "$KEY" != a ] || selected[i]=1
                    done
                fi ;;
            '')
                if [ "$multiple" -eq 0 ]; then MENU_SELECTED=("$cursor"); fi
                return 0 ;;
            b | B) if [ "$page" -ne 0 ]; then return 2; fi ;;
            q | Q | $'\e') return 1 ;;
        esac
    done
}

# Shared repository/skill selector. REPO_SELECTED contains item indices, so
# distinct agents or unknown local entries never collapse into one deletion.
choose_skill_repositories() {
    local status=0
    printf '\033[?25l'
    choose_skill_repositories_page "$@" || status=$?
    printf '\033[?25h'
    return "$status"
}

choose_skill_repositories_page() {
    local page="$1" title="$2" color="$3" cursor=0 child=-1 i j group found start end total chosen mark row key_page
    local groups=() item_groups=() selected=() children=()
    for ((i=0; i<${#REPO_ITEM_LABELS[@]}; i++)); do
        group="${REPO_ITEM_GROUPS[i]}"; found=-1
        for ((j=0; j<${#groups[@]}; j++)); do [ "${groups[j]}" != "$group" ] || { found="$j"; break; }; done
        if [ "$found" -eq -1 ]; then found="${#groups[@]}"; groups+=("$group"); fi
        item_groups+=("$found"); selected+=(0)
    done
    for i in "${REPO_SELECTED[@]+"${REPO_SELECTED[@]}"}"; do selected[i]=1; done
    cursor="${MENU_CURSORS[page]:-0}"
    while :; do
        REPO_SELECTED=()
        for ((i=0; i<${#selected[@]}; i++)); do [ "${selected[i]}" -eq 0 ] || REPO_SELECTED+=("$i"); done
        printf '\033[H\033[2J%s\n' "$title"
        if [ "$child" -lt 0 ]; then
            printf 'Up/Down: move | Space: select repository | Enter: open / Continue | a: all | n: none | b: back | q: exit\n\n'
            total=$((${#groups[@]} + 1)); MENU_CURSORS[page]="$cursor"
        else
            printf 'Repository: %s\nUp/Down: move | Space: select | a: all | n: none | Enter/b: repositories | q: exit\n\n' "${groups[child]}"
            children=()
            for ((i=0; i<${#selected[@]}; i++)); do [ "${item_groups[i]}" -ne "$child" ] || children+=("$i"); done
            total="${#children[@]}"; key_page=$((100 + page * 100 + child)); MENU_CURSORS[key_page]="$cursor"
        fi
        if [ "$cursor" -ge "$total" ]; then cursor=0; fi
        start=$((cursor / 8 * 8)); end=$((start + 8))
        for ((row=start; row<end && row<total; row++)); do
            if [ "$row" -eq "$cursor" ]; then printf '> '; else printf '  '; fi
            if [ "$child" -lt 0 ]; then
                if [ "$row" -eq "${#groups[@]}" ]; then printf 'Continue\n'; continue; fi
                chosen=0; found=0
                for ((i=0; i<${#selected[@]}; i++)); do
                    if [ "${item_groups[i]}" -eq "$row" ]; then found=$((found + 1)); chosen=$((chosen + selected[i])); fi
                done
                mark=' '; if [ "$chosen" -eq "$found" ]; then mark=x; elif [ "$chosen" -gt 0 ]; then mark=-; fi
                printf '[%s] \033[%sm%s\033[0m (%s/%s)\n' "$mark" "$color" "${groups[row]}" "$chosen" "$found"
            else
                i="${children[row]}"; mark=' '; [ "${selected[i]}" -eq 0 ] || mark=x
                printf '[%s] \033[%sm%s\033[0m\n' "$mark" "$color" "${REPO_ITEM_LABELS[i]}"
            fi
        done
        printf '\nItem %s/%s\n' "$((cursor + 1))" "$total"
        read_key || return 1
        case "$KEY" in
            $'\e[A' | $'\eOA') cursor=$(((cursor + total - 1) % total)) ;;
            $'\e[B' | $'\eOB') cursor=$(((cursor + 1) % total)) ;;
            ' ' | a | n)
                if [ "$child" -lt 0 ]; then
                    [ "$cursor" -lt "${#groups[@]}" ] || [ "$KEY" != ' ' ] || continue
                    found=1
                    if [ "$KEY" = n ]; then found=0;
                    elif [ "$KEY" = ' ' ]; then
                        chosen=0; total=0
                        for ((i=0; i<${#selected[@]}; i++)); do
                            if [ "${item_groups[i]}" -eq "$cursor" ]; then total=$((total + 1)); chosen=$((chosen + selected[i])); fi
                        done
                        [ "$chosen" -ne "$total" ] || found=0
                    fi
                    for ((i=0; i<${#selected[@]}; i++)); do
                        if [ "$KEY" != ' ' ] || [ "${item_groups[i]}" -eq "$cursor" ]; then selected[i]="$found"; fi
                    done
                elif [ "$KEY" = ' ' ]; then i="${children[cursor]}"; selected[i]=$((1 - selected[i]));
                else
                    found=1; [ "$KEY" != n ] || found=0
                    for i in "${children[@]}"; do selected[i]="$found"; done
                fi ;;
            '')
                if [ "$child" -ge 0 ]; then child=-1; cursor="${MENU_CURSORS[page]}";
                elif [ "$cursor" -eq "${#groups[@]}" ]; then return 0;
                else child="$cursor"; key_page=$((100 + page * 100 + child)); cursor="${MENU_CURSORS[key_page]:-0}"; fi ;;
            b | B)
                if [ "$child" -ge 0 ]; then child=-1; cursor="${MENU_CURSORS[page]}"; else return 2; fi ;;
            q | Q | $'\e') return 1 ;;
        esac
    done
}

# The private manifest binds selection IDs to scanned paths and content hashes.
# No source checkout or network access is required to remove installed content.
removal_inventory() {
    node - "$HOME" "$REMOVAL_TEMP/inventory.json" "$@" <<'JS'
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const cp = require('child_process');
const [home, manifest, action, ...args] = process.argv.slice(2);
const red = s => `\x1b[31m${s}\x1b[0m`;
const cyan = s => `\x1b[36m${s}\x1b[0m`;
const yellow = s => `\x1b[33m${s}\x1b[0m`;
process.on('uncaughtException', error => { console.error(red(error.message)); process.exitCode = 1; });
const display = s => JSON.stringify(String(s)).slice(1, -1);
const quote = s => "'" + s.replace(/'/g, "'\\''") + "'";
const stat = p => { try { return fs.lstatSync(p); } catch (e) { if (e.code !== 'ENOENT') throw e; } };
if (!home || !path.isAbsolute(home) || path.resolve(home) === '/') throw Error('Unsafe HOME');
const full = relative => {
    const value = path.resolve(home, relative);
    if (!value.startsWith(path.resolve(home) + path.sep)) throw Error('Path outside HOME');
    return value;
};
function parents(relative) {
    let current = path.dirname(full(relative));
    const result = [];
    while (current !== path.resolve(home)) {
        const info = stat(current);
        if (!info?.isDirectory() || info.isSymbolicLink()) throw Error(`Unsafe parent directory: ${current}`);
        result.push([current, info.dev, info.ino]);
        current = path.dirname(current);
    }
    return result;
}
function fingerprint(relative) {
    const hash = crypto.createHash('sha256');
    function walk(p) {
        const info = stat(p);
        if (!info) { hash.update('missing'); return; }
        hash.update(JSON.stringify([p, info.dev, info.ino, info.mode, info.size, info.mtimeMs, info.ctimeMs]));
        if (info.isSymbolicLink()) hash.update(fs.readlinkSync(p));
        else if (info.isDirectory()) for (const name of fs.readdirSync(p).sort()) walk(path.join(p, name));
        else if (info.isFile()) hash.update(fs.readFileSync(p));
        else throw Error(`Unsupported entry: ${p}`);
    }
    walk(full(relative));
    return hash.digest('hex');
}
function markers(text) {
    const lines = text.match(/[^\n]*\n|[^\n]+$/g) || [];
    let offset = 0, opened = null;
    const result = [], names = new Set();
    for (const line of lines) {
        const start = line.replace(/[\r\n]+$/, '').match(/^<!-- gwyn-space-skills: ([a-zA-Z0-9][a-zA-Z0-9._-]*):start -->$/);
        const end = line.replace(/[\r\n]+$/, '').match(/^<!-- gwyn-space-skills: ([a-zA-Z0-9][a-zA-Z0-9._-]*):end -->$/);
        if (start) {
            if (opened || names.has(start[1])) throw Error('Duplicate or nested managed rule markers');
            opened = {name: start[1], start: offset}; names.add(start[1]);
        }
        if (end) {
            if (!opened || opened.name !== end[1]) throw Error('Unbalanced managed rule markers');
            result.push({...opened, end: offset + line.length}); opened = null;
        }
        offset += line.length;
    }
    if (opened) throw Error('Unbalanced managed rule markers');
    return result;
}
const lockPath = '.agents/.skill-lock.json';
function readLock() {
    const info = stat(full(lockPath));
    if (!info) return {data: {skills: {}}, valid: true};
    if (!info.isFile() || info.isSymbolicLink()) return {valid: false};
    try {
        const data = JSON.parse(fs.readFileSync(full(lockPath), 'utf8'));
        if (!data || typeof data !== 'object' || Array.isArray(data) ||
            (data.skills !== undefined && (!data.skills || typeof data.skills !== 'object' || Array.isArray(data.skills)))) return {valid: false};
        return {data, valid: true};
    } catch { return {valid: false}; }
}
function repository(record) {
    if (!record || record.sourceType !== 'github') return 'Unknown / local';
    const source = record.source || record.sourceUrl || '';
    if (typeof source !== 'string') return 'Unknown / local';
    const match = source.replace(/^https?:\/\/github.com\//, '').replace(/^git@github.com:/, '').match(/^([\w.-]+)\/([\w.-]+)(?:\/|$)/);
    return match ? `${match[1]}/${match[2].replace(/\.git$/, '')}`.toLowerCase() : 'Unknown / local';
}
function scan(codex, claude, rules, skills) {
    for (const directory of [...(skills ? ['.agents'] : []), ...(claude ? ['.claude'] : []), ...(rules && codex ? ['.codex'] : [])]) {
        if (stat(full(directory))?.isSymbolicLink()) throw Error(`Refusing symlinked directory: ${full(directory)}`);
    }
    const entries = [], lock = skills ? readLock() : {valid: true};
    const add = entry => {
        entries.push({...entry, id: entries.length, snapshot: fingerprint(entry.relative), parents: parents(entry.relative)});
    };
    for (const agent of ['codex', 'claude']) {
        if (!(agent === 'codex' ? codex : claude)) continue;
        if (rules) {
            const relative = agent === 'codex' ? '.codex/AGENTS.md' : '.claude/CLAUDE.md';
            const info = stat(full(relative));
            if (info?.isSymbolicLink()) add({kind: 'rules', type: 'link', agent, relative, name: path.basename(relative)});
            else if (info?.isFile()) {
                parents(relative);
                for (const block of markers(fs.readFileSync(full(relative), 'latin1'))) {
                    add({kind: 'rules', type: 'block', agent, relative, name: block.name});
                }
            }
            if (agent === 'claude') {
                const walk = relative => {
                    const info = stat(full(relative));
                    if (!info) return;
                    if (info.isSymbolicLink()) add({kind: 'rules', type: 'link', agent, relative, name: relative.slice('.claude/'.length)});
                    else if (info.isDirectory()) {
                        for (const name of fs.readdirSync(full(relative)).sort()) walk(path.join(relative, name));
                    } else if (info.isFile()) add({kind: 'rules', type: 'file', agent, relative, name: relative.slice('.claude/'.length)});
                };
                walk('.claude/rules');
            }
        }
        if (skills) {
            const root = agent === 'codex' ? '.agents/skills' : '.claude/skills';
            const info = stat(full(root));
            if (info?.isSymbolicLink()) {
                if (agent === 'codex') throw Error(`Refusing symlinked directory: ${full(root)}`);
                add({kind: 'skills', type: 'link', agent, relative: root, name: 'skills directory link', group: 'Unknown / local'});
            } else if (info?.isDirectory()) {
                parents(path.join(root, 'entry'));
                for (const name of fs.readdirSync(full(root)).sort()) {
                    if (name === '.system') continue;
                    const relative = path.join(root, name), info = stat(full(relative));
                    let record = agent === 'codex' ? lock.data?.skills?.[name] : null;
                    if (agent === 'claude' && info.isSymbolicLink()) {
                        const destination = path.resolve(path.dirname(full(relative)), fs.readlinkSync(full(relative)));
                        if (path.dirname(destination) === full('.agents/skills')) record = lock.data?.skills?.[path.basename(destination)];
                    }
                    add({kind: 'skills', type: info.isSymbolicLink() ? 'link' : info.isDirectory() ? 'directory' : 'file',
                         agent, relative, name, group: repository(record)});
                }
            }
        }
    }
    if (skills && !lock.valid) console.error(yellow('Skill lock is unreadable; skills are grouped under Unknown / local. Codex deletion requires a valid lock.'));
    return {entries, selected: [], lockSnapshot: skills ? fingerprint(lockPath) : null};
}
function selected(data) {
    const ids = new Set(data.selected);
    return data.entries.filter(e => ids.has(e.id));
}
function verify(data, items) {
    for (const entry of items) {
        if (JSON.stringify(parents(entry.relative)) !== JSON.stringify(entry.parents) || fingerprint(entry.relative) !== entry.snapshot) {
            throw Error(`Content changed; rescan and select again: ${full(entry.relative)}`);
        }
    }
    if (items.some(e => e.kind === 'skills') && fingerprint(lockPath) !== data.lockSnapshot) throw Error('Skill lock changed; rescan and select again');
}
function warnings(items) {
    const removed = new Set(items.filter(e => e.type !== 'block').map(e => full(e.relative)));
    const sources = items.filter(e => e.kind === 'skills' && e.agent === 'codex').map(e => full(e.relative));
    if (!sources.length) return;
    console.log(yellow('Other agents may use shared skills.'));
    function walk(p) {
        const info = stat(p);
        if (!info) return;
        if (info.isSymbolicLink()) {
            const destination = path.resolve(path.dirname(p), fs.readlinkSync(p));
            if (!removed.has(p) && sources.some(source => destination === source || destination.startsWith(source + path.sep) || source.startsWith(destination + path.sep))) {
                console.log(red(`WARNING: Claude link will be kept: ${display(p)} -> ${display(destination)}`));
            }
        } else if (info.isDirectory()) for (const name of fs.readdirSync(p)) walk(path.join(p, name));
    }
    // Do not traverse a symlinked agent parent just to produce a warning.
    if (!stat(full('.claude'))?.isSymbolicLink()) walk(full('.claude/skills'));
}
function atomicWrite(relative, text) {
    parents(relative);
    const destination = full(relative), info = fs.lstatSync(destination);
    if (!info.isFile() || info.isSymbolicLink()) throw Error(`Not a regular file: ${destination}`);
    const temporary = `${destination}.agent-setup-${crypto.randomBytes(8).toString('hex')}`;
    try {
        fs.writeFileSync(temporary, text, {flag: 'wx', mode: info.mode & 0o777});
        fs.chmodSync(temporary, info.mode & 0o777);
        fs.renameSync(temporary, destination);
    } finally { fs.rmSync(temporary, {force: true}); }
}
if (action === 'scan') {
    const data = scan(...args.map(value => value === '1'));
    fs.writeFileSync(manifest, JSON.stringify(data), {mode: 0o600});
} else {
    const data = JSON.parse(fs.readFileSync(manifest, 'utf8'));
    if (action === 'rows') {
        for (const e of data.entries) console.log([e.id, e.kind, display(e.group || '-'), `${e.agent === 'codex' ? 'Codex' : 'Claude'} / ${display(e.name)} [${e.type}]`].join('\t'));
    } else if (action === 'select') {
        data.selected = [...new Set(args.map(Number))];
        if (data.selected.some(id => !data.entries.some(e => e.id === id))) throw Error('Invalid removal selection');
        fs.writeFileSync(manifest, JSON.stringify(data));
    } else {
        const items = selected(data);
        if (!items.length) { console.log('No removal targets selected.'); process.exit(0); }
        verify(data, items);
        if (action === 'preview') {
            console.log('Removal targets:');
            for (const e of items) console.log(`  ${e.agent} / ${display(e.name)} [${e.type}]: ${red(display(full(e.relative)) + (e.type === 'block' ? ` # ${e.name}` : ''))}`);
            const lock = readLock();
            const names = items.filter(e => e.kind === 'skills' && e.agent === 'codex' && lock.valid && Object.hasOwn(lock.data.skills || {}, e.name)).map(e => e.name);
            if (names.length) console.log(`  Remove lock entries (${names.map(display).join(', ')}): ${red(display(full(lockPath)))}`);
            warnings(items);
        } else if (action === 'remove') {
            const lock = readLock();
            const codexSkills = items.filter(e => e.kind === 'skills' && e.agent === 'codex');
            if (codexSkills.length && !lock.valid) throw Error('Invalid skill lock; nothing removed');
            const updatesLock = codexSkills.some(e => Object.hasOwn(lock.data.skills || {}, e.name));
            const targets = [...new Set([...items.map(e => e.relative), ...(updatesLock ? [lockPath] : [])])];
            const prefix = items.some(e => e.kind === 'rules') ? '.agent-rules-backup-' : '.agent-skills-backup-';
            const backupDir = fs.mkdtempSync(path.join(home, prefix));
            fs.chmodSync(backupDir, 0o700);
            const backup = path.join(backupDir, 'removal.tar');
            const result = cp.spawnSync('tar', ['-cf', backup, '-C', home, '--', ...targets], {stdio: 'inherit'});
            if (result.status !== 0) throw Error('Backup failed; nothing removed');
            console.log(cyan(`Backup: ${display(backup)}`));
            console.log(cyan(`Restore: tar -xf ${quote(backup)} -C ${quote(home)}`));
            verify(data, items);
            let succeeded = 0, failed = 0;
            const removedSkills = [], handled = new Set();
            for (const item of items) {
                if (handled.has(item.id)) continue;
                const batch = item.type === 'block' ? items.filter(e => e.type === 'block' && e.relative === item.relative) : [item];
                for (const e of batch) handled.add(e.id);
                try {
                    parents(item.relative);
                    if (item.type === 'block') {
                        const text = fs.readFileSync(full(item.relative), 'latin1'), names = new Set(batch.map(e => e.name));
                        let next = text;
                        for (const block of markers(text).filter(b => names.has(b.name)).reverse()) next = next.slice(0, block.start) + next.slice(block.end);
                        atomicWrite(item.relative, Buffer.from(next, 'latin1'));
                    } else fs.rmSync(full(item.relative), {recursive: true});
                    for (const e of batch) {
                        succeeded++;
                        console.log(`  OK removed ${e.agent} / ${display(e.name)}: ${red(display(full(e.relative)) + (e.type === 'block' ? ` # ${e.name}` : ''))}`);
                        if (e.kind === 'skills' && e.agent === 'codex') removedSkills.push(e.name);
                    }
                } catch (error) {
                    failed += batch.length;
                    for (const e of batch) console.error(red(`  FAIL ${e.agent} / ${display(e.name)}: ${display(full(e.relative))}: ${error.message}`));
                }
            }
            if (updatesLock && removedSkills.length) {
                try {
                    if (fingerprint(lockPath) !== data.lockSnapshot) throw Error('Skill lock changed during deletion; restore from backup if needed');
                    for (const name of removedSkills) delete lock.data.skills[name];
                    atomicWrite(lockPath, JSON.stringify(lock.data, null, 2) + '\n');
                    console.log(`Updated lock: ${red(display(full(lockPath)))}`);
                } catch (error) { failed++; console.error(red(`  FAIL lock update: ${error.message}`)); }
            }
            console.log(`\nResults: ${succeeded} succeeded, ${failed} failed`);
            if (items.some(e => e.kind === 'skills')) console.log('Remove skills for the selected agents; preserve .system entries.');
            process.exitCode = failed ? 1 : 0;
        } else throw Error('Unknown removal action');
    }
}
JS
}

scan_removal_inventory() {
    local rows id kind group label
    require_command node || return 1
    if [ -n "$REMOVAL_TEMP" ]; then rm -rf -- "$REMOVAL_TEMP"; fi
    REMOVAL_TEMP="$(mktemp -d)" || return 1
    trap cleanup_setup_resources EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    removal_inventory scan "$REMOVE_CODEX" "$REMOVE_CLAUDE" "$REMOVE_RULES" "$REMOVE_SKILLS" || return 1
    rows=$(removal_inventory rows) || return 1
    REMOVAL_RULE_IDS=(); REMOVAL_RULE_LABELS=(); REMOVAL_SKILL_IDS=(); REMOVAL_SKILL_LABELS=(); REMOVAL_SKILL_GROUPS=()
    REMOVAL_RULE_SELECTION=(); REMOVAL_SKILL_SELECTION=()
    MENU_VISITED[12]=0; MENU_CURSORS[12]=0; MENU_CURSORS[13]=0
    while IFS=$'\t' read -r id kind group label; do
        [ -n "$id" ] || continue
        if [ "$kind" = rules ]; then REMOVAL_RULE_IDS+=("$id"); REMOVAL_RULE_LABELS+=("$label");
        else REMOVAL_SKILL_IDS+=("$id"); REMOVAL_SKILL_LABELS+=("$label"); REMOVAL_SKILL_GROUPS+=("$group"); fi
    done <<<"$rows"
}

preview_selected_removal() {
    local i ids=()
    for i in "${REMOVAL_RULE_SELECTION[@]+"${REMOVAL_RULE_SELECTION[@]}"}"; do ids+=("${REMOVAL_RULE_IDS[i]}"); done
    for i in "${REMOVAL_SKILL_SELECTION[@]+"${REMOVAL_SKILL_SELECTION[@]}"}"; do ids+=("${REMOVAL_SKILL_IDS[i]}"); done
    if [ "${#ids[@]}" -eq 0 ]; then printf 'No removal targets selected.\n'; return 2; fi
    removal_inventory select "${ids[@]}" || return 1
    removal_inventory preview || return 1
}

list_setup_backups() {
    node - "$HOME" <<'JS'
const fs = require('fs');
const path = require('path');
const home = process.argv[2];
if (!home || !path.isAbsolute(home) || path.resolve(home) === '/') throw Error('Unsafe HOME');
for (const entry of fs.readdirSync(home, {withFileTypes: true}).sort((a, b) => a.name.localeCompare(b.name))) {
    if (entry.isDirectory() && /^\.agent-(skills|rules)-backup-[A-Za-z0-9]{6}$/.test(entry.name)) {
        console.log(entry.name);
    }
}
JS
}

remove_setup_backups() {
    node - "$HOME" "$@" <<'JS'
const fs = require('fs');
const path = require('path');
const [home, ...names] = process.argv.slice(2);
if (!home || !path.isAbsolute(home) || path.resolve(home) === '/') throw Error('Unsafe HOME');
// Validate the complete confirmed list before deleting anything. A directory
// replaced by a symlink after preview must never redirect the deletion.
for (const name of names) {
    if (!/^\.agent-(skills|rules)-backup-[A-Za-z0-9]{6}$/.test(name)) throw Error('Invalid backup directory name');
    const info = fs.lstatSync(path.join(home, name));
    if (!info.isDirectory() || info.isSymbolicLink()) throw Error(`Backup is no longer a directory: ${name}`);
}
for (const name of names) {
    const full = path.join(home, name);
    fs.rmSync(full, {recursive: true});
    console.log(`Removed backup: \x1b[31m${full}\x1b[0m`);
}
JS
}

confirm_backup_removal() {
    local names name answer
    local backups=()
    require_command node
    names=$(list_setup_backups)
    if [ -z "$names" ]; then printf 'No setup backups found.\n'; return 0; fi
    printf '\nRemove all setup backup directories listed below:\n'
    while IFS= read -r name; do
        backups+=("$name")
        printf '  \033[31m%s/%s\033[0m\n' "$HOME" "$name"
    done <<<"$names"
    printf 'This permanently deletes these backups and their restore data. No new backup is created.\n'
    printf 'Type DELETE to confirm, or press Enter to cancel: '
    IFS= read -r answer || return 0
    [ "$answer" = DELETE ] || return 0
    run_item 'Remove all backups' remove_setup_backups "${backups[@]}"
    print_summary
}

preflight() {
    local item
    for item in "$@"; do
        case "$item" in
            0 | 1) require_command curl || return 1 ;;
            2) : ;;
            3) require_command node || return 1 ;;
            4) require_command curl || return 1; require_command node || return 1; require_command npx || return 1 ;;
        esac
    done
}

execute_plan() {
    local item other source previous handled index source_scope
    local completed_sources=() names=()
    for item in "${AGENT_ITEMS[@]+"${AGENT_ITEMS[@]}"}"; do
        case "$item" in
            0) run_item 'Codex CLI' install_codex ;;
            1) run_item 'Claude Code CLI' install_claude ;;
            2)
                for ((index=0; index<${#SELECTED_RULES[@]}; index++)); do
                    other="${SELECTED_RULES[index]}"
                    source_scope="${SELECTED_RULE_SOURCES[index]:-$RULE_SCOPE}"
                    if ! resolve_resource "rules/$source_scope"; then FAILED+=("$source_scope rule: $other (resource unavailable)"); continue; fi
                    run_item "$RULE_SCOPE rule: $other ($RULE_TARGETS)" apply_rule "$other" "$RULE_SCOPE" "$RULE_TARGETS" install "$source_scope"
                done ;;
            3)
                if ! resolve_resource scripts/statusline.sh; then FAILED+=('Claude statusline: resource unavailable'); continue; fi
                run_item 'Claude statusline' install_statusline ;;
        esac
    done
    for item in "${SELECTED_SKILLS[@]+"${SELECTED_SKILLS[@]}"}"; do
        source="${SKILL_SOURCES[item]}"
        handled=0
        for previous in "${completed_sources[@]+"${completed_sources[@]}"}"; do
            if [ "$previous" = "$source" ]; then handled=1; break; fi
        done
        [ "$handled" -eq 0 ] || continue
        names=()
        for other in "${SELECTED_SKILLS[@]}"; do
            if [ "${SKILL_SOURCES[other]}" = "$source" ]; then
                names+=("${SKILL_NAMES[other]}")
            fi
        done
        completed_sources+=("$source")
        run_item "${SKILL_GROUPS[item]}: ${names[*]}" \
            install_agent_skills "$source" "${names[@]}"
    done
    print_summary
}

print_install_plan() {
    local i destination index source_scope
    local labels=('Codex CLI' 'Claude Code CLI' 'Rules' 'Claude statusline')
    printf '\nExecution plan:\n'
    for i in "${AGENT_ITEMS[@]+"${AGENT_ITEMS[@]}"}"; do
        [ "$i" -eq 2 ] || printf '  \033[32m%s\033[0m\n' "${labels[i]}"
    done
    if [ "${#SELECTED_RULES[@]}" -gt 0 ]; then
        for ((index=0; index<${#SELECTED_RULES[@]}; index++)); do
            i="${SELECTED_RULES[index]}"
            source_scope="${SELECTED_RULE_SOURCES[index]:-$RULE_SCOPE}"
            resolve_resource "rules/$source_scope" || return 1
            if [ -n "$RESOURCE_TEMP" ] && [[ "$RESOURCE_PATH" = "$RESOURCE_TEMP/"* ]]; then
                printf '  Rule source: GitHub gwyntoria/skills @ main (rules/%s/%s.md)\n' "$source_scope" "$i"
            else
                printf '  Rule source: %s/%s.md\n' "$RESOURCE_PATH" "$i"
            fi
            printf '  \033[32m%s / %s -> %s\033[0m\n' "$RULE_SCOPE" "$i" "$RULE_TARGETS"
            if [ "$RULE_SCOPE" = project ]; then
                if [ "$RULE_TARGETS" != claude ]; then printf '    \033[32m%s/AGENTS.md\033[0m\n' "$PROJECT_TARGET"; fi
                if [ "$RULE_TARGETS" != codex ]; then printf '    \033[32m%s/.claude/rules/%s.md\033[0m\n' "$PROJECT_TARGET" "$i"; fi
            else
                if [ "$RULE_TARGETS" != claude ]; then printf '    \033[32m%s/.codex/AGENTS.md\033[0m\n' "$HOME"; fi
                if [ "$RULE_TARGETS" != codex ]; then
                    destination="$HOME/.claude/rules/$i.md"
                    if [ "$i" = agent-behavior ]; then destination="$HOME/.claude/CLAUDE.md"; fi
                    printf '    \033[32m%s\033[0m\n' "$destination"
                fi
            fi
        done
    fi
    for i in "${SELECTED_SKILLS[@]+"${SELECTED_SKILLS[@]}"}"; do
        printf '  \033[32m%s / %s -> %s\033[0m\n' "${SKILL_GROUPS[i]}" "${SKILL_NAMES[i]}" "${TARGET_AGENTS[*]}"
        print_skill_targets "${SKILL_NAMES[i]}"
    done
    for i in "${FAILED[@]+"${FAILED[@]}"}"; do printf '  UNAVAILABLE: %s\n' "$i"; done
}

# Capture action failures without putting the action in a conditional, which
# would disable errexit inside its file writes and backup steps.
run_interactive_task() {
    set +e
    ( set -e; set -o pipefail; "$@" )
    INTERACTIVE_RESULT=$?
    set -e
    if [ "$INTERACTIVE_RESULT" -ne 0 ]; then
        printf 'Task failed (exit %s).\n' "$INTERACTIVE_RESULT" >&2
    fi
    return 0
}

interactive_setup() {
    trap cleanup_setup_resources EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    local page=main catalog_loaded=0 i task answer menu_status removal_scanned=0 removal_signature="" signature command_action
    local session_status=0 INTERACTIVE_RESULT=0 show_summary=0
    local catalog_failures=()
    local rule_labels=() rule_names=() rule_sources=() source_scope
    local task_labels=('Skills' 'Rules' 'Codex CLI' 'Claude Code CLI' 'Claude statusline')
    local task_ids=(4 2 0 1 3) tasks=()
    while :; do
        case "$page" in
            main)
                choose_items 0 'Agent setup' 0 0 'Install / Update' 'Remove' 'Remove all backups' 'Install / Update this command' 'Exit' || return "$session_status"
                case "${MENU_SELECTED[0]}" in
                    0) page=tasks ;;
                    1) removal_scanned=0; page=remove_agents ;;
                    2) run_interactive_task confirm_backup_removal; page=complete ;;
                    3) page=command_confirm ;;
                    4) return "$session_status" ;;
                esac ;;
            command_confirm)
                command_action=Install
                if [ -e "$HOME/.local/bin/agent-setup" ] || [ -L "$HOME/.local/bin/agent-setup" ]; then
                    command_action=Update
                fi
                printf '\n%s this command?\nTarget: \033[32m%s/.local/bin/agent-setup\033[0m\n' "$command_action" "$HOME"
                printf 'Continue? [y/N] (b: back | q: exit) '
                IFS= read -r answer || return "$session_status"
                case "$answer" in
                    y | Y)
                        run_item "$command_action this command" install_setup_command
                        print_summary || session_status=1
                        page=complete ;;
                    b | B) page=main ;;
                    q | Q) return "$session_status" ;;
                    *) printf 'Cancelled.\n'; page=complete ;;
                esac ;;
            remove_agents)
                choose_items 4 'Remove: choose agents' 1 1 Codex 'Claude Code' || {
                    [ "$?" -eq 2 ] || return "$session_status"
                    page=main; continue
                }
                [ "${#MENU_SELECTED[@]}" -gt 0 ] || { printf 'No agents selected; cancelled.\n'; page=complete; continue; }
                REMOVE_CODEX=0; REMOVE_CLAUDE=0
                for i in "${MENU_SELECTED[@]}"; do
                    if [ "$i" -eq 0 ]; then REMOVE_CODEX=1; else REMOVE_CLAUDE=1; fi
                done
                page=remove_categories ;;
            remove_categories)
                choose_items 5 'Remove: choose content' 1 0 Rules Skills || {
                    [ "$?" -eq 2 ] || return "$session_status"
                    page=remove_agents; continue
                }
                [ "${#MENU_SELECTED[@]}" -gt 0 ] || { printf 'No content selected; cancelled.\n'; page=complete; continue; }
                REMOVE_RULES=0; REMOVE_SKILLS=0
                for i in "${MENU_SELECTED[@]}"; do
                    if [ "$i" -eq 0 ]; then REMOVE_RULES=1; else REMOVE_SKILLS=1; fi
                done
                signature="$REMOVE_CODEX/$REMOVE_CLAUDE/$REMOVE_RULES/$REMOVE_SKILLS"
                if [ "$removal_scanned" -eq 0 ] || [ "$signature" != "$removal_signature" ]; then
                    if ! scan_removal_inventory; then FAILED+=('Installed content scan failed'); show_summary=1; page=complete; continue; fi
                    removal_signature="$signature"; removal_scanned=1
                fi
                page=remove_rules ;;
            remove_rules)
                if [ "$REMOVE_RULES" -eq 1 ] && [ "${#REMOVAL_RULE_IDS[@]}" -gt 0 ]; then
                    choose_items 12 'Choose installed rules to remove' 1 0 "${REMOVAL_RULE_LABELS[@]}" || {
                        [ "$?" -eq 2 ] || return "$session_status"
                        page=remove_categories; continue
                    }
                    REMOVAL_RULE_SELECTION=("${MENU_SELECTED[@]+"${MENU_SELECTED[@]}"}")
                fi
                page=remove_skills ;;
            remove_skills)
                if [ "$REMOVE_SKILLS" -eq 1 ] && [ "${#REMOVAL_SKILL_IDS[@]}" -gt 0 ]; then
                    REPO_ITEM_LABELS=("${REMOVAL_SKILL_LABELS[@]}"); REPO_ITEM_GROUPS=("${REMOVAL_SKILL_GROUPS[@]}")
                    REPO_SELECTED=("${REMOVAL_SKILL_SELECTION[@]+"${REMOVAL_SKILL_SELECTION[@]}"}")
                    choose_skill_repositories 13 'Remove skills by repository' 31 || {
                        menu_status=$?
                        REMOVAL_SKILL_SELECTION=("${REPO_SELECTED[@]+"${REPO_SELECTED[@]}"}")
                        [ "$menu_status" -eq 2 ] || return "$session_status"
                        if [ "$REMOVE_RULES" -eq 1 ] && [ "${#REMOVAL_RULE_IDS[@]}" -gt 0 ]; then page=remove_rules; else page=remove_categories; fi
                        continue
                    }
                    REMOVAL_SKILL_SELECTION=("${REPO_SELECTED[@]+"${REPO_SELECTED[@]}"}")
                fi
                preview_selected_removal || {
                    menu_status=$?
                    if [ "$menu_status" -ne 2 ]; then FAILED+=('Removal preview failed; rescan required'); show_summary=1; fi
                    page=complete; continue
                }
                printf 'All selected content is backed up before any removal.\nType DELETE to confirm, or press Enter to cancel (b: back | q: exit): '
                IFS= read -r answer || return "$session_status"
                case "$answer" in
                    DELETE) run_interactive_task removal_inventory remove ;;
                    q | Q) return "$session_status" ;;
                    b | B)
                        if [ "$REMOVE_SKILLS" -eq 1 ] && [ "${#REMOVAL_SKILL_IDS[@]}" -gt 0 ]; then page=remove_skills;
                        elif [ "$REMOVE_RULES" -eq 1 ] && [ "${#REMOVAL_RULE_IDS[@]}" -gt 0 ]; then page=remove_rules;
                        else page=remove_categories; fi
                        continue ;;
                    *) printf 'Cancelled.\n' ;;
                esac
                page=complete ;;
            tasks)
                choose_items 1 'Choose installation tasks' 1 0 "${task_labels[@]}" || {
                    [ "$?" -eq 2 ] || return "$session_status"
                    page=main; continue
                }
                tasks=("${MENU_SELECTED[@]+"${MENU_SELECTED[@]}"}")
                [ "${#tasks[@]}" -gt 0 ] || { printf 'No tasks selected.\n'; page=complete; continue; }
                AGENT_ITEMS=(); INSTALL_SKILLS=0
                # Keep installation order independent of the menu's display order.
                for i in 0 1 2 3 4; do
                    for task in "${tasks[@]}"; do
                        [ "${task_ids[task]}" -eq "$i" ] || continue
                        if ! preflight "$i" || { [ "$i" -eq 3 ] && ! resolve_resource scripts/statusline.sh; }; then
                            FAILED+=("Installation preparation failed"); show_summary=1; page=complete; break 2
                        fi
                        if [ "$i" -eq 4 ]; then INSTALL_SKILLS=1; else AGENT_ITEMS+=("$i"); fi
                    done
                done
                [ "$page" != complete ] || continue
                if [[ " ${AGENT_ITEMS[*]+${AGENT_ITEMS[*]}} " = *" 2 "* ]]; then page=rule_choices;
                else SELECTED_RULES=(); SELECTED_RULE_SOURCES=(); page=after_rules; fi ;;
            rule_choices)
                # The catalog contains both source groups; destination scope is chosen later.
                for source_scope in global project; do
                    if { [ "$source_scope" = global ] && [ "$RULE_CATALOG_GLOBAL" -eq 0 ]; } ||
                       { [ "$source_scope" = project ] && [ "$RULE_CATALOG_PROJECT" -eq 0 ]; }; then
                        if ! RULE_SCOPE="$source_scope" load_rule_catalog; then
                            FAILED+=("$source_scope rule catalog unavailable"); show_summary=1; page=complete; break
                        fi
                    fi
                done
                [ "$page" != complete ] || continue
                rule_labels=(); rule_names=(); rule_sources=()
                for i in "${RULE_NAMES_GLOBAL[@]+"${RULE_NAMES_GLOBAL[@]}"}"; do
                    rule_labels+=("global / $i"); rule_names+=("$i"); rule_sources+=(global)
                done
                for i in "${RULE_NAMES_PROJECT[@]+"${RULE_NAMES_PROJECT[@]}"}"; do
                    rule_labels+=("project / $i"); rule_names+=("$i"); rule_sources+=(project)
                done
                if [ "${#rule_labels[@]}" -eq 0 ]; then FAILED+=('No rules available'); show_summary=1; page=complete; continue; fi
                choose_items 9 'Choose rules' 1 0 "${rule_labels[@]}" || {
                    [ "$?" -eq 2 ] || return "$session_status"
                    page=tasks; continue
                }
                SELECTED_RULES=(); SELECTED_RULE_SOURCES=()
                for i in "${MENU_SELECTED[@]+"${MENU_SELECTED[@]}"}"; do
                    SELECTED_RULES+=("${rule_names[i]}"); SELECTED_RULE_SOURCES+=("${rule_sources[i]}")
                done
                if [ "${#SELECTED_RULES[@]}" -gt 0 ]; then page=rule_targets; else page=after_rules; fi ;;
            rule_targets)
                choose_items 8 'Rules: choose agents' 1 1 Codex 'Claude Code' || {
                    [ "$?" -eq 2 ] || return "$session_status"
                    page=rule_choices; continue
                }
                [ "${#MENU_SELECTED[@]}" -gt 0 ] || { printf 'No rule targets selected; cancelled.\n'; page=complete; continue; }
                RULE_TARGETS=both
                if [ "${#MENU_SELECTED[@]}" -eq 1 ]; then
                    if [ "${MENU_SELECTED[0]}" -eq 0 ]; then RULE_TARGETS=codex; else RULE_TARGETS=claude; fi
                fi
                page=rule_scope ;;
            rule_scope)
                choose_items 7 'Rules: choose scope' 0 0 Global Project || {
                    [ "$?" -eq 2 ] || return "$session_status"
                    page=rule_targets; continue
                }
                if [ "${MENU_SELECTED[0]}" -eq 0 ]; then RULE_SCOPE=global; else RULE_SCOPE=project; fi
                page=after_rules ;;
            after_rules)
                if [ "$INSTALL_SKILLS" -eq 1 ]; then
                    if [ "$catalog_loaded" -eq 0 ]; then
                        load_catalog
                        catalog_loaded=1
                        catalog_failures=("${FAILED[@]+"${FAILED[@]}"}")
                    fi
                    if [ "$catalog_loaded" -eq 1 ]; then
                        FAILED=("${catalog_failures[@]+"${catalog_failures[@]}"}")
                        [ "${#FAILED[@]}" -eq 0 ] || session_status=1
                    fi
                    if [ "${#SKILL_NAMES[@]}" -gt 0 ]; then page=skills; else page=review; fi
                else
                    SELECTED_SKILLS=()
                    page=review
                fi ;;
            skills)
                REPO_ITEM_LABELS=("${SKILL_NAMES[@]}"); REPO_ITEM_GROUPS=()
                for i in "${SKILL_SOURCES[@]}"; do REPO_ITEM_GROUPS+=("${i#https://github.com/}"); done
                REPO_SELECTED=("${SELECTED_SKILLS[@]+"${SELECTED_SKILLS[@]}"}")
                choose_skill_repositories 2 'Install skills by repository' 32 || {
                    menu_status=$?
                    SELECTED_SKILLS=("${REPO_SELECTED[@]+"${REPO_SELECTED[@]}"}")
                    [ "$menu_status" -eq 2 ] || return "$session_status"
                    if [[ " ${AGENT_ITEMS[*]+${AGENT_ITEMS[*]}} " = *" 2 "* ]]; then page=rule_scope; else page=tasks; fi
                    continue
                }
                SELECTED_SKILLS=("${REPO_SELECTED[@]+"${REPO_SELECTED[@]}"}")
                if [ "${#SELECTED_SKILLS[@]}" -gt 0 ]; then page=targets; else page=review; fi ;;
            targets)
                choose_items 3 'Install skills for' 1 1 Codex 'Claude Code' || {
                    [ "$?" -eq 2 ] || return "$session_status"
                    page=skills; continue
                }
                TARGET_AGENTS=()
                for i in "${MENU_SELECTED[@]+"${MENU_SELECTED[@]}"}"; do
                    if [ "$i" -eq 0 ]; then TARGET_AGENTS+=(codex); else TARGET_AGENTS+=(claude-code); fi
                done
                if [ "${#TARGET_AGENTS[@]}" -eq 0 ]; then
                    printf 'No skill targets selected; cancelled.\n'; page=complete; continue
                fi
                page=review ;;
            review)
                if [[ " ${AGENT_ITEMS[*]+${AGENT_ITEMS[*]}} " = *" 2 "* ]]; then
                    choose_items 11 'Confirm installation' 0 0 Install Cancel || {
                        menu_status=$?
                        if [ "$menu_status" -eq 3 ]; then
                            FAILED+=('Cannot prepare installation plan'); show_summary=1; page=complete; continue
                        fi
                        [ "$menu_status" -eq 2 ] || return "$session_status"
                        if [ "$INSTALL_SKILLS" -eq 1 ] && [ "${#SELECTED_SKILLS[@]}" -gt 0 ]; then page=targets;
                        else page=rule_scope; fi
                        continue
                    }
                    if [ "${MENU_SELECTED[0]}" -ne 0 ]; then printf 'Cancelled.\n'; page=complete; continue; fi
                else
                    if ! print_install_plan; then FAILED+=('Cannot prepare installation plan'); show_summary=1; page=complete; continue; fi
                    if [ "$((${#AGENT_ITEMS[@]} + ${#SELECTED_SKILLS[@]}))" -eq 0 ]; then
                        show_summary=1; page=complete; continue
                    fi
                    printf 'Continue? [y/N] (b: back | q: exit) '
                    IFS= read -r answer || return "$session_status"
                    case "$answer" in
                        y | Y) ;;
                        q | Q) return "$session_status" ;;
                        b | B)
                            if [ "$INSTALL_SKILLS" -eq 1 ] && [ "${#SELECTED_SKILLS[@]}" -gt 0 ]; then page=targets;
                            else page=tasks; fi
                            continue ;;
                        *) printf 'Cancelled.\n'; page=complete; continue ;;
                    esac
                fi
                run_interactive_task execute_plan
                page=complete ;;
            complete)
                if [ "$INTERACTIVE_RESULT" -ne 0 ] || [ "${#FAILED[@]}" -gt 0 ]; then session_status=1; fi
                if [ "$show_summary" -eq 1 ]; then print_summary || true; fi
                printf '\nPress Enter to return to the main menu (q: exit): '
                while :; do
                    read_key || return "$session_status"
                    case "$KEY" in
                        '') break ;;
                        q | Q | $'\e') return "$session_status" ;;
                    esac
                done
                # New actions start with defaults; Back within an action keeps selections.
                SUCCEEDED=(); FAILED=(); MENU_SELECTED=(); MENU_CURSORS=(); MENU_CHOICES=(); MENU_VISITED=()
                AGENT_ITEMS=(); SELECTED_SKILLS=(); SELECTED_RULES=(); SELECTED_RULE_SOURCES=()
                TARGET_AGENTS=(codex claude-code); RULE_TARGETS=both; RULE_SCOPE=global
                REMOVE_CODEX=1; REMOVE_CLAUDE=1; REMOVE_RULES=0; REMOVE_SKILLS=0
                REMOVAL_RULE_SELECTION=(); REMOVAL_SKILL_SELECTION=(); removal_scanned=0
                if [ -n "$REMOVAL_TEMP" ]; then rm -rf -- "$REMOVAL_TEMP"; REMOVAL_TEMP=""; fi
                INTERACTIVE_RESULT=0; show_summary=0; INSTALL_SKILLS=0
                page=main ;;
        esac
    done
}

main() {
    local parse_status i
    AGENT_ITEMS=(); SELECTED_SKILLS=()
    if [ "$#" -eq 0 ]; then
        if [ ! -t 0 ] || [ ! -t 1 ]; then
            printf 'Error: interactive setup requires a terminal. Use --agent, --skill, or --list.\n' >&2
            return 2
        fi
        interactive_setup
        return $?
    fi
    parse_args "$@" || {
        parse_status=$?
        [ "$parse_status" -ne 1 ] || return 0
        return "$parse_status"
    }
    if [ "$INSTALL_AGENT" -eq 1 ]; then
        AGENT_ITEMS=(0 1 2 3); SELECTED_RULES=(agent-behavior); SELECTED_RULE_SOURCES=(global); RULE_SCOPE=global; RULE_TARGETS=both
    fi
    preflight "${AGENT_ITEMS[@]+"${AGENT_ITEMS[@]}"}"
    if [ "$INSTALL_SKILLS" -eq 1 ] || [ "$LIST_SKILLS" -eq 1 ]; then
        preflight 4
        load_catalog
        if [ "$LIST_SKILLS" -eq 1 ]; then
            print_catalog
            [ "${#FAILED[@]}" -eq 0 ]
            return $?
        fi
        for ((i=0; i<${#SKILL_NAMES[@]}; i++)); do SELECTED_SKILLS+=("$i"); done
    fi
    execute_plan
}

if [ "${BASH_SOURCE[0]:-}" = "$0" ]; then
    main "$@"
fi
