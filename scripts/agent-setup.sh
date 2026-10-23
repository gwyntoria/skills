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
REMOVE_CLAUDE_RULES=0

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
        exit 1
    fi
}

# Do not put the subshell in an if/! condition: that disables errexit inside
# called functions, allowing an earlier failed write to look successful.
run_item() {
    local label="$1" result
    shift
    log "$label"
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
    for item in "${SUCCEEDED[@]+"${SUCCEEDED[@]}"}"; do printf '  OK    %s\n' "$item"; done
    for item in "${FAILED[@]+"${FAILED[@]}"}"; do printf '  FAIL  %s\n' "$item"; done
    [ "${#FAILED[@]}" -eq 0 ]
}

install_agent_skills() {
    local source="$1"
    shift
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
    for group in Waza Kami 'Matt Pocock' HumanLayer; do
        case "$group" in
            Waza) source="$WAZA_SKILLS_URL" ;;
            Kami) source="$KAMI_SKILLS_URL" ;;
            'Matt Pocock') source="$MATTPOCOCK_SKILLS_URL" ;;
            HumanLayer) source="$HUMANLAYER_SKILLS_URL" ;;
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
    if [ -n "$RESOURCE_TEMP" ]; then rm -rf -- "$RESOURCE_TEMP"; fi
}

resolve_resource() {
    local relative="$1" candidate="$REPO/$1"
    case "$relative" in rules/global | rules/project | scripts/statusline.sh) ;; *) return 2 ;; esac
    if [ -e "$candidate" ] || [ -L "$candidate" ]; then
        RESOURCE_PATH="$candidate"
    else
        require_command curl
        require_command tar
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
    printf 'Installed: %s/agent-setup (used on next launch)\n' "$directory"
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
    PROGRAM_NAME=agent-setup.sh
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
    printf '\n\033[1;34m==> %s\033[0m\n' "$1"
}

success() {
    printf '\033[1;32m✓ %s\033[0m\n' "$1"
}

warn() {
    printf '\033[1;33m! %s\033[0m\n' "$1" >&2
}

error() {
    printf 'Error: %s\n' "$1" >&2
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

    success "Moved obsolete Claude rule to $backup"
    printf '  Restore with: mv "%s" "%s"\n' "$backup" "$legacy"
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

    success "Backed up the legacy copy to $backup"
    printf '  Restore with: mv "%s" "%s"\n' "$backup" "$destination"

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
    if command -v codex >/dev/null 2>&1; then return 0; fi
    curl -fsSL https://chatgpt.com/codex/install.sh | sh
    require_command codex
}

install_claude() {
    if command -v claude >/dev/null 2>&1; then return 0; fi
    curl -fsSL https://claude.ai/install.sh | bash
    require_command claude
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
# Return 0 to continue, 1 to exit, and 2 to go back.
choose_items() {
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
        if [ "$page" -eq 11 ]; then print_install_plan || return 1; printf '\n'; fi
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

# Preview and execution use the same target plan. Symlinks are archived and
# unlinked without traversing their targets; bundled .system entries survive.
remove_installed_agent_skills() {
    node - "$HOME" "${1:-remove}" "$REMOVE_CODEX" "$REMOVE_CLAUDE" <<'JS'
const fs = require('fs');
const path = require('path');
const cp = require('child_process');
const [home, action, codex, claude] = process.argv.slice(2);
if (!home || !path.isAbsolute(home) || path.resolve(home) === '/') throw Error('Unsafe HOME');
const stat = full => {
    try { return fs.lstatSync(full); } catch (e) { if (e.code !== 'ENOENT') throw e; }
};
for (const name of ['.agents', '.claude', ...(codex === '1' ? ['.agents/skills'] : [])]) {
    const full = path.join(home, name);
    if (stat(full)?.isSymbolicLink()) throw Error(`Refusing symlinked directory: ${full}`);
}
const shared = path.join(home, '.agents/skills');
const targets = [];
const addEntries = relative => {
    const full = path.join(home, relative);
    const info = stat(full);
    if (info?.isSymbolicLink()) targets.push(relative);
    else if (info?.isDirectory()) {
        for (const name of fs.readdirSync(full)) {
            if (name !== '.system') targets.push(path.join(relative, name));
        }
    }
};
if (codex === '1') {
    addEntries('.agents/skills');
    if (stat(path.join(home, '.agents/.skill-lock.json'))) targets.push('.agents/.skill-lock.json');
}
if (claude === '1') addEntries('.claude/skills');
if (action === 'preview' && codex === '1' && claude !== '1') {
    const affected = [];
    const scan = full => {
        const info = stat(full);
        if (info?.isSymbolicLink()) {
            const target = path.resolve(path.dirname(full), fs.readlinkSync(full));
            if (targets.some(relative => {
                const removed = path.join(home, relative);
                return target === removed || target.startsWith(removed + path.sep) || removed.startsWith(target + path.sep);
            })) affected.push(`${full} -> ${target}`);
        } else if (info?.isDirectory()) {
            for (const name of fs.readdirSync(full)) scan(path.join(full, name));
        }
    };
    scan(path.join(home, '.claude/skills'));
    if (affected.length) console.log('\x1b[31mWARNING: Claude links will be kept, but their shared skills will be removed:\n' + affected.join('\n') + '\x1b[0m');
}
console.log('Removal targets:\n' + (targets.map(p => path.join(home, p)).join('\n') || '(none)'));
if (action === 'preview') process.exit(0);
if (!targets.length) { console.log('No managed global skills to remove.'); process.exit(0); }
const backupDir = fs.mkdtempSync(path.join(home, '.agent-skills-backup-'));
fs.chmodSync(backupDir, 0o700);
const backup = path.join(backupDir, 'skills.tar');
const result = cp.spawnSync('tar', ['-cf', backup, '-C', home, '--', ...targets], {stdio: 'inherit'});
if (result.status !== 0) throw Error('Backup failed; nothing removed');
console.log(`Backup: ${backup}`);
const quote = value => "'" + value.replace(/'/g, "'\\''") + "'";
console.log(`Restore: tar -xf ${quote(backup)} -C ${quote(home)}`);
for (const target of targets) fs.rmSync(path.join(home, target), {recursive: true, force: true});
JS
}

confirm_removal() {
    local answer
    require_command node
    require_command tar
    remove_installed_agent_skills preview
    printf 'A tar backup is created before removal. Other agents may use shared skills.\n'
    printf 'Type DELETE to confirm, or press Enter to cancel: '
    IFS= read -r answer || return 0
    [ "$answer" = DELETE ] || return 0
    run_item 'Remove global skills' remove_installed_agent_skills
    printf '\nRemove skills for the selected agents; preserve .system entries.\n'
    print_summary
}

# Keep the rules directory itself, except when it is a symlink: unlink that
# entry without touching its target. Back up hidden files and links as well.
claude_rules() {
    node - "$HOME" "$1" <<'JS'
const fs = require('fs');
const path = require('path');
const cp = require('child_process');
const [home, action] = process.argv.slice(2);
if (!home || !path.isAbsolute(home) || path.resolve(home) === '/') throw Error('Unsafe HOME');
const stat = full => {
    try { return fs.lstatSync(full); } catch (e) { if (e.code !== 'ENOENT') throw e; }
};
if (stat(path.join(home, '.claude'))?.isSymbolicLink()) throw Error('Refusing symlinked .claude directory');
const relative = '.claude/rules';
const full = path.join(home, relative);
const info = stat(full);
const targets = info?.isSymbolicLink() ? [relative] : info?.isDirectory()
    ? fs.readdirSync(full).map(name => path.join(relative, name)) : [];
if (action === 'preview') {
    console.log('Claude rules removal targets:\n' + (targets.map(p => path.join(home, p)).join('\n') || '(none)'));
} else if (action === 'backup' && targets.length) {
    const dir = fs.mkdtempSync(path.join(home, '.agent-rules-backup-'));
    fs.chmodSync(dir, 0o700);
    const backup = path.join(dir, 'rules.tar');
    const result = cp.spawnSync('tar', ['-cf', backup, '-C', home, '--', ...targets], {stdio: 'inherit'});
    if (result.status !== 0) throw Error('Rules backup failed; nothing removed');
    const quote = value => "'" + value.replace(/'/g, "'\\''") + "'";
    console.log(`Backup: ${backup}`);
    console.log(`Restore: tar -xf ${quote(backup)} -C ${quote(home)}`);
} else if (action === 'remove') {
    for (const target of targets) fs.rmSync(path.join(home, target), {recursive: true, force: true});
}
JS
}


remove_global_rules() {
    local relative destination backup_dir="" target=both
    local files=()
    if [ "$REMOVE_CODEX" -eq 1 ]; then files+=(.codex/AGENTS.md); fi
    if [ "$REMOVE_CLAUDE" -eq 1 ]; then files+=(.claude/CLAUDE.md); fi
    if [ "$REMOVE_CODEX" -eq 0 ]; then target=claude; fi
    if [ "$REMOVE_CLAUDE" -eq 0 ]; then target=codex; fi
    # Back up selected files before the first removal. cp restores through an
    # existing file symlink, matching the rule installer's path handling.
    for relative in "${files[@]}"; do
        destination="$HOME/$relative"
        [ -f "$destination" ] || continue
        if [ -z "$backup_dir" ]; then
            backup_dir=$(mktemp -d "$HOME/.agent-rules-backup-XXXXXX")
        fi
        cp -pL "$destination" "$backup_dir/${relative##*/}"
    done
    if [ -n "$backup_dir" ]; then
        printf 'Backup: %s\n' "$backup_dir"
        for relative in "${files[@]}"; do
            [ -f "$backup_dir/${relative##*/}" ] || continue
            printf 'Restore: cp -p %q %q\n' "$backup_dir/${relative##*/}" "$HOME/$relative"
        done
    fi
    if [ "$REMOVE_CLAUDE_RULES" -eq 1 ]; then claude_rules backup; fi
    apply_rule agent-behavior global "$target" remove </dev/null
    if [ "$REMOVE_CLAUDE_RULES" -eq 1 ]; then claude_rules remove; fi
}

confirm_rule_removal() {
    local answer
    printf '\nRemove the managed agent-behavior rules from:\n'
    if [ "$REMOVE_CODEX" -eq 1 ]; then printf '  %s/.codex/AGENTS.md\n' "$HOME"; fi
    if [ "$REMOVE_CLAUDE" -eq 1 ]; then printf '  %s/.claude/CLAUDE.md\n' "$HOME"; fi
    if [ "$REMOVE_CLAUDE_RULES" -eq 1 ]; then
        require_command node
        require_command tar
        claude_rules preview
    fi
    printf 'Keep personal content and other rule blocks in AGENTS.md/CLAUDE.md. Back up existing files before removal.\n'
    printf 'Type DELETE to confirm, or press Enter to cancel: '
    IFS= read -r answer || return 0
    [ "$answer" = DELETE ] || return 0
    run_item 'Remove global rules' remove_global_rules
    print_summary
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
    console.log(`Removed backup: ${full}`);
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
        printf '  %s/%s\n' "$HOME" "$name"
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
            0 | 1) require_command curl ;;
            2) : ;;
            3) require_command node ;;
            4) require_command curl; require_command node; require_command npx ;;
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
        [ "$i" -eq 2 ] || printf '  %s\n' "${labels[i]}"
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
            printf '  %s / %s -> %s\n' "$RULE_SCOPE" "$i" "$RULE_TARGETS"
            if [ "$RULE_SCOPE" = project ]; then
                if [ "$RULE_TARGETS" != claude ]; then printf '    %s/AGENTS.md\n' "$PROJECT_TARGET"; fi
                if [ "$RULE_TARGETS" != codex ]; then printf '    %s/.claude/rules/%s.md\n' "$PROJECT_TARGET" "$i"; fi
            else
                if [ "$RULE_TARGETS" != claude ]; then printf '    %s/.codex/AGENTS.md\n' "$HOME"; fi
                if [ "$RULE_TARGETS" != codex ]; then
                    destination="$HOME/.claude/rules/$i.md"
                    if [ "$i" = agent-behavior ]; then destination="$HOME/.claude/CLAUDE.md"; fi
                    printf '    %s\n' "$destination"
                fi
            fi
        done
    fi
    for i in "${SELECTED_SKILLS[@]+"${SELECTED_SKILLS[@]}"}"; do
        printf '  %s / %s -> %s\n' "${SKILL_GROUPS[i]}" "${SKILL_NAMES[i]}" "${TARGET_AGENTS[*]}"
    done
    for i in "${FAILED[@]+"${FAILED[@]}"}"; do printf '  UNAVAILABLE: %s\n' "$i"; done
}

interactive_setup() {
    local page=main catalog_loaded=0 i task answer
    local rule_labels=() rule_names=() rule_sources=() source_scope
    local task_labels=('Skills' 'Rules' 'Codex CLI' 'Claude Code CLI' 'Claude statusline')
    local task_ids=(4 2 0 1 3) skill_labels=() tasks=()
    while :; do
        case "$page" in
            main)
                choose_items 0 'Agent setup' 0 0 'Install / Update' 'Remove global skills' 'Remove global rules' 'Remove all backups' 'Install / Update this command' 'Exit' || return 0
                case "${MENU_SELECTED[0]}" in
                    0) page=tasks ;;
                    1) page=remove_skills ;;
                    2) page=remove_rule_agents ;;
                    3) confirm_backup_removal; return $? ;;
                    4) run_item 'Install / Update this command' install_setup_command; print_summary; return $? ;;
                    5) return 0 ;;
                esac ;;
            remove_skills | remove_rule_agents)
                if [ "$page" = remove_skills ]; then i=4; answer='Remove global skills';
                else i=5; answer='Remove global rules'; fi
                choose_items "$i" "$answer: choose agents" 1 1 Codex 'Claude Code' || {
                    [ "$?" -eq 2 ] || return 0
                    page=main; continue
                }
                [ "${#MENU_SELECTED[@]}" -gt 0 ] || { printf 'No agents selected; cancelled.\n'; return 0; }
                REMOVE_CODEX=0; REMOVE_CLAUDE=0; REMOVE_CLAUDE_RULES=0
                for i in "${MENU_SELECTED[@]}"; do
                    if [ "$i" -eq 0 ]; then REMOVE_CODEX=1; else REMOVE_CLAUDE=1; fi
                done
                if [ "$page" = remove_skills ]; then confirm_removal; return $?; fi
                if [ "$REMOVE_CLAUDE" -eq 1 ]; then page=remove_rules;
                else confirm_rule_removal; return $?; fi ;;
            remove_rules)
                choose_items 6 'Also remove all Claude rules directory contents?' 0 0 \
                    'Keep rules (default)' 'Remove rules directory contents' || {
                    [ "$?" -eq 2 ] || return 0
                    page=remove_rule_agents; continue
                }
                REMOVE_CLAUDE_RULES="${MENU_SELECTED[0]}"
                confirm_rule_removal; return $? ;;
            tasks)
                choose_items 1 'Choose installation tasks' 1 0 "${task_labels[@]}" || {
                    [ "$?" -eq 2 ] || return 0
                    page=main; continue
                }
                tasks=("${MENU_SELECTED[@]+"${MENU_SELECTED[@]}"}")
                [ "${#tasks[@]}" -gt 0 ] || return 0
                AGENT_ITEMS=(); INSTALL_SKILLS=0
                # Keep installation order independent of the menu's display order.
                for i in 0 1 2 3 4; do
                    for task in "${tasks[@]}"; do
                        [ "${task_ids[task]}" -eq "$i" ] || continue
                        preflight "$i"
                        if [ "$i" -eq 4 ]; then INSTALL_SKILLS=1; else AGENT_ITEMS+=("$i"); fi
                    done
                done
                if [[ " ${AGENT_ITEMS[*]+${AGENT_ITEMS[*]}} " = *" 2 "* ]]; then page=rule_choices;
                else SELECTED_RULES=(); SELECTED_RULE_SOURCES=(); page=after_rules; fi ;;
            rule_choices)
                # The catalog contains both source groups; destination scope is chosen later.
                for source_scope in global project; do
                    if { [ "$source_scope" = global ] && [ "$RULE_CATALOG_GLOBAL" -eq 0 ]; } ||
                       { [ "$source_scope" = project ] && [ "$RULE_CATALOG_PROJECT" -eq 0 ]; }; then
                        RULE_SCOPE="$source_scope" load_rule_catalog || return 1
                    fi
                done
                rule_labels=(); rule_names=(); rule_sources=()
                for i in "${RULE_NAMES_GLOBAL[@]+"${RULE_NAMES_GLOBAL[@]}"}"; do
                    rule_labels+=("global / $i"); rule_names+=("$i"); rule_sources+=(global)
                done
                for i in "${RULE_NAMES_PROJECT[@]+"${RULE_NAMES_PROJECT[@]}"}"; do
                    rule_labels+=("project / $i"); rule_names+=("$i"); rule_sources+=(project)
                done
                if [ "${#rule_labels[@]}" -eq 0 ]; then printf 'No rules available.\n'; return 1; fi
                choose_items 9 'Choose rules' 1 0 "${rule_labels[@]}" || {
                    [ "$?" -eq 2 ] || return 0
                    page=tasks; continue
                }
                SELECTED_RULES=(); SELECTED_RULE_SOURCES=()
                for i in "${MENU_SELECTED[@]+"${MENU_SELECTED[@]}"}"; do
                    SELECTED_RULES+=("${rule_names[i]}"); SELECTED_RULE_SOURCES+=("${rule_sources[i]}")
                done
                if [ "${#SELECTED_RULES[@]}" -gt 0 ]; then page=rule_targets; else page=after_rules; fi ;;
            rule_targets)
                choose_items 8 'Rules: choose agents' 1 1 Codex 'Claude Code' || {
                    [ "$?" -eq 2 ] || return 0
                    page=rule_choices; continue
                }
                [ "${#MENU_SELECTED[@]}" -gt 0 ] || { printf 'No rule targets selected; cancelled.\n'; return 0; }
                RULE_TARGETS=both
                if [ "${#MENU_SELECTED[@]}" -eq 1 ]; then
                    if [ "${MENU_SELECTED[0]}" -eq 0 ]; then RULE_TARGETS=codex; else RULE_TARGETS=claude; fi
                fi
                page=rule_scope ;;
            rule_scope)
                choose_items 7 'Rules: choose scope' 0 0 Global Project || {
                    [ "$?" -eq 2 ] || return 0
                    page=rule_targets; continue
                }
                if [ "${MENU_SELECTED[0]}" -eq 0 ]; then RULE_SCOPE=global; else RULE_SCOPE=project; fi
                page=after_rules ;;
            after_rules)
                if [ "$INSTALL_SKILLS" -eq 1 ]; then
                    if [ "$catalog_loaded" -eq 0 ]; then
                        load_catalog
                        catalog_loaded=1
                        for ((i=0; i<${#SKILL_NAMES[@]}; i++)); do
                            skill_labels+=("${SKILL_GROUPS[i]} / ${SKILL_NAMES[i]}")
                        done
                    fi
                    if [ "${#SKILL_NAMES[@]}" -gt 0 ]; then page=skills; else page=review; fi
                else
                    SELECTED_SKILLS=()
                    page=review
                fi ;;
            skills)
                choose_items 2 'Choose skills by source' 1 0 "${skill_labels[@]}" || {
                    [ "$?" -eq 2 ] || return 0
                    if [[ " ${AGENT_ITEMS[*]+${AGENT_ITEMS[*]}} " = *" 2 "* ]]; then page=rule_scope; else page=tasks; fi
                    continue
                }
                SELECTED_SKILLS=("${MENU_SELECTED[@]+"${MENU_SELECTED[@]}"}")
                if [ "${#SELECTED_SKILLS[@]}" -gt 0 ]; then page=targets; else page=review; fi ;;
            targets)
                choose_items 3 'Install skills for' 1 1 Codex 'Claude Code' || {
                    [ "$?" -eq 2 ] || return 0
                    page=skills; continue
                }
                TARGET_AGENTS=()
                for i in "${MENU_SELECTED[@]+"${MENU_SELECTED[@]}"}"; do
                    if [ "$i" -eq 0 ]; then TARGET_AGENTS+=(codex); else TARGET_AGENTS+=(claude-code); fi
                done
                if [ "${#TARGET_AGENTS[@]}" -eq 0 ]; then
                    printf 'No skill targets selected; cancelled.\n'; return 0
                fi
                page=review ;;
            review)
                if [[ " ${AGENT_ITEMS[*]+${AGENT_ITEMS[*]}} " != *" 2 "* ]]; then break; fi
                [ "$((${#AGENT_ITEMS[@]} + ${#SELECTED_SKILLS[@]}))" -gt 0 ] || { print_summary; return $?; }
                choose_items 11 'Confirm installation' 0 0 Install Cancel || {
                    [ "$?" -eq 2 ] || return 0
                    if [ "$INSTALL_SKILLS" -eq 1 ] && [ "${#SELECTED_SKILLS[@]}" -gt 0 ]; then page=targets;
                    elif [[ " ${AGENT_ITEMS[*]+${AGENT_ITEMS[*]}} " = *" 2 "* ]]; then page=rule_scope;
                    else page=tasks; fi
                    continue
                }
                [ "${MENU_SELECTED[0]}" -eq 0 ] || { printf 'Cancelled.\n'; return 0; }
                execute_plan; return $? ;;
        esac
    done
    print_install_plan
    [ "$((${#AGENT_ITEMS[@]} + ${#SELECTED_SKILLS[@]}))" -gt 0 ] || { print_summary; return $?; }
    printf 'Continue? [y/N] '
    IFS= read -r answer || return 0
    case "$answer" in y | Y) execute_plan ;; *) printf 'Cancelled.\n' ;; esac
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
