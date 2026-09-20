#!/usr/bin/env bash
# Install one instruction fragment from this repository's instructions/ directory
# into Claude Code or Codex, at global or project scope.
#
# Usage:
#   setup-rule.sh <rule> [--target claude|codex|both|auto]
#                        [--global | --project [DIR]] [--remove] [--list]
#                        [--migrate-legacy] [-h|--help]
#
# Rules are read from the working copy, so this script must be run from a clone
# of the repository. Nothing is fetched over the network.
#
# The two agents need different install engines, because their mechanisms differ:
#
#   Claude Code  ~/.claude/rules/**/*.md and <project>/.claude/rules/**/*.md are
#                loaded natively, so a rule is just a file. Nothing else is
#                touched, and removal is an unlink.
#   Codex        has no rules directory and no import syntax; AGENTS.md is the
#                only mechanism. A rule therefore has to be merged into that file
#                inside a marker block so re-runs replace it instead of stacking.

set -euo pipefail

PROGRAM_NAME="${0##*/}"

MARKER_PREFIX="gwyn-space-skills"

TARGET_OPT="auto"
SCOPE_OPT=""
PROJECT_DIR_OPT=""
PROJECT_DIR=""
MODE="install"
MIGRATE_LEGACY=0
LIST_ONLY=0

RULE=""
# RULE_FILE is the basename, used to build destination paths. RULE_SOURCE is the
# absolute path in instructions/, used to read the content. Keeping them in one
# variable would concatenate an absolute path onto a destination directory.
RULE_FILE=""
RULE_SOURCE=""
RULE_SCOPE=""
RULE_TITLE=""

TARGETS=""
SCOPES=""
FAILURES=0
SCRATCH_DIR=""

# ------------------------------------------------------------
# Output helpers
# ------------------------------------------------------------

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

# ------------------------------------------------------------
# Locate the repository
# ------------------------------------------------------------

# Follow symlinks so an invocation through a link still finds instructions/.
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

SCRIPT_PATH="$(resolve_symlinks "${BASH_SOURCE[0]:-$0}")" || exit 1
REPO="$(cd -P "$(dirname "$SCRIPT_PATH")/.." && pwd -P)"
SOURCE_ROOT="$REPO/instructions"

# ------------------------------------------------------------
# Environment guards
# ------------------------------------------------------------

require_repo_layout() {
    if [ ! -d "$SOURCE_ROOT" ]; then
        error "cannot find $SOURCE_ROOT"
        printf '  Run this script from a clone of the repository.\n' >&2
        exit 1
    fi
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

# ------------------------------------------------------------
# Rule discovery
# ------------------------------------------------------------
# Rules are whatever instructions/*.md holds, so adding a file needs no edit
# here. Only the scope default is declared, and it defaults to project: a wrong
# global write pollutes $HOME, a wrong project write is local and visible.

available_rules() {
    local file

    for file in "$SOURCE_ROOT"/*.md; do
        [ -f "$file" ] || continue
        basename "$file" .md
    done
}

default_scope() {
    case "$1" in
    global) printf 'global\n' ;;
    *) printf 'project\n' ;;
    esac
}

# Resolve a rule name to its source file, default scope, and first line. The
# first line is what a whole-file install must start with to count as ours,
# which is how a foreign file of the same name is told apart from a managed one.
lookup_rule() {
    RULE_FILE="$1.md"
    RULE_SOURCE="$SOURCE_ROOT/$RULE_FILE"

    if [ ! -f "$RULE_SOURCE" ]; then
        return 1
    fi

    RULE_SCOPE="$(default_scope "$1")"
    RULE_TITLE="$(head -n 1 "$RULE_SOURCE")"

    case "$RULE_TITLE" in
    "# "*) ;;
    *)
        error "$RULE_SOURCE does not start with a Markdown H1"
        return 1
        ;;
    esac

    return 0
}

print_rule_names() {
    local name

    for name in $(available_rules); do
        printf '  %s\n' "$name" >&2
    done
}

# ------------------------------------------------------------
# Argument parsing
# ------------------------------------------------------------
# 约定：0 继续执行，1 已打印 usage，2 选项错误。这里不自己 exit，
# 退出码统一由 main 决定。

usage() {
    printf 'Usage: %s <rule> [options]\n' "$PROGRAM_NAME"
    printf '\n'
    printf 'Rules are read from %s.\n' "$SOURCE_ROOT"
    printf '\n'
    printf 'Options:\n'
    printf '  --target NAME        claude, codex, both, or auto (default: auto)\n'
    printf '  --global             install into the user config, whatever the rule default is\n'
    printf '  --project [DIR]      install into a project config (default: the git work tree root)\n'
    printf '  --remove             remove the rule instead of installing it\n'
    printf '  --list               list the rules and whether they are installed\n'
    printf '  --migrate-legacy     rename byte-identical legacy copies instead of refusing\n'
    printf '  -h, --help           Show this help message\n'
    printf '\n'
    printf 'Edits made inside a managed block are overwritten on the next install.\n'
}

parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
        -h | --help)
            usage
            return 1
            ;;
        --target)
            if [ "$#" -lt 2 ]; then
                printf 'Error: --target requires a value.\n\n' >&2
                usage >&2
                return 2
            fi
            TARGET_OPT="$2"
            shift
            ;;
        --global)
            if [ -n "$SCOPE_OPT" ]; then
                printf 'Error: --global and --project cannot be combined.\n\n' >&2
                usage >&2
                return 2
            fi
            SCOPE_OPT="global"
            ;;
        # Only swallow the next argument when it is not another flag, so
        # `--project --global` is a conflict rather than a directory named
        # "--global".
        --project)
            if [ -n "$SCOPE_OPT" ]; then
                printf 'Error: --global and --project cannot be combined.\n\n' >&2
                usage >&2
                return 2
            fi
            SCOPE_OPT="project"
            if [ "$#" -ge 2 ]; then
                case "$2" in
                -*) ;;
                *)
                    PROJECT_DIR_OPT="$2"
                    shift
                    ;;
                esac
            fi
            ;;
        --remove)
            MODE="remove"
            ;;
        --list)
            LIST_ONLY=1
            ;;
        --migrate-legacy)
            MIGRATE_LEGACY=1
            ;;
        -*)
            printf 'Error: unknown option: %s\n\n' "$1" >&2
            usage >&2
            return 2
            ;;
        *)
            if [ -n "$RULE" ]; then
                printf 'Error: unexpected argument: %s\n\n' "$1" >&2
                usage >&2
                return 2
            fi
            RULE="${1%.md}"
            ;;
        esac

        shift
    done

    return 0
}

# ------------------------------------------------------------
# Resolution
# ------------------------------------------------------------

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

resolve_scope() {
    if [ "$MODE" = "remove" ] && [ -z "$SCOPE_OPT" ]; then
        # Removal broadens by default: install narrows. A bare --remove should
        # undo wherever the rule landed, while a bare install must not.
        SCOPE="everywhere"
        return 0
    fi

    if [ -n "$SCOPE_OPT" ]; then
        SCOPE="$SCOPE_OPT"
    else
        SCOPE="$RULE_SCOPE"
    fi

    if [ "$SCOPE" != "$RULE_SCOPE" ] && [ "$MODE" = "install" ]; then
        warn "$RULE_FILE is classified $RULE_SCOPE in README.md; installing as $SCOPE."
    fi

    return 0
}

resolve_project_dir() {
    if [ -n "$PROJECT_DIR_OPT" ]; then
        PROJECT_DIR="$PROJECT_DIR_OPT"
    else
        PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null)" || PROJECT_DIR=""
        if [ -z "$PROJECT_DIR" ]; then
            PROJECT_DIR="$PWD"
            warn "not inside a git work tree; using $PROJECT_DIR"
        fi
    fi

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
    global) printf '%s\n' "$HOME/.claude/rules/$RULE_FILE" ;;
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

# Build the managed block: markers, a provenance line, then the rule verbatim.
write_block() {
    local output="$1"
    local body="$2"
    local eol="$3"
    local start
    local end
    local line

    start="$(start_marker)"
    end="$(end_marker)"

    {
        printf '%s%s\n' "$start" "$eol"
        printf '<!-- Installed from instructions/%s by %s. Edits inside this block are overwritten on reinstall. -->%s\n' \
            "$RULE_FILE" "$PROGRAM_NAME" "$eol"
        while IFS= read -r line || [ -n "$line" ]; do
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
# config_agent.sh used to write global.md straight over ~/.claude/CLAUDE.md and
# ~/.codex/AGENTS.md. Once global.md is also installed as a rule, those copies
# make every session load the same text twice.

timestamp() {
    date -u '+%Y%m%dT%H%M%SZ'
}

# Claude Code loads every .md under rules/, so a backup that keeps a .md suffix
# would be picked up as a rule. Hence the suffix.
migrate_legacy_claude_md() {
    local legacy="$HOME/.claude/CLAUDE.md"
    local stamp
    local backup

    [ -f "$legacy" ] || return 0

    if ! cmp -s "$legacy" "$RULE_SOURCE"; then
        if grep -qF -- "$RULE_TITLE" "$legacy" 2>/dev/null; then
            warn "$legacy contains an unmanaged copy of $RULE_FILE."
            warn "That copy plus the new rule loads the same text twice. Review it by hand; nothing was changed."
        fi
        return 0
    fi

    if [ "$MIGRATE_LEGACY" -ne 1 ]; then
        warn "$legacy is byte-identical to $RULE_FILE and will now load twice."
        warn "Re-run with --migrate-legacy, or remove it yourself: rm \"$legacy\""
        return 0
    fi

    stamp="$(timestamp)"
    backup="$legacy.legacy-$stamp"

    if ! mv "$legacy" "$backup"; then
        warn "could not move $legacy aside"
        return 1
    fi

    success "Moved the duplicate to $backup"
    printf '  Restore with: mv "%s" "%s"\n' "$backup" "$legacy"

    return 0
}

# A byte-identical AGENTS.md has no markers, so appending would leave the rule in
# the file twice. Refuse, unless migration was explicitly requested.
adopt_legacy_codex_agents() {
    local agents="$1"
    local stamp
    local backup

    [ -f "$agents" ] || return 1

    if ! cmp -s "$agents" "$RULE_SOURCE"; then
        if grep -qF -- "$RULE_TITLE" "$agents" 2>/dev/null; then
            warn "$agents contains an unmanaged copy of $RULE_FILE; see lines $(marker_line_numbers "$agents" "$RULE_TITLE")."
        fi
        return 1
    fi

    if [ "$MIGRATE_LEGACY" -ne 1 ]; then
        error "$agents is byte-identical to $RULE_FILE and has no managed block."
        printf '  Appending would leave two copies in the file Codex loads every session.\n' >&2
        printf '  Re-run with --migrate-legacy to back it up and replace it with a managed block.\n' >&2
        return 2
    fi

    stamp="$(timestamp)"
    backup="$agents.pre-rules.bak-$stamp"

    if ! cp -p "$agents" "$backup"; then
        error "could not back up $agents"
        return 2
    fi

    success "Backed up the legacy copy to $backup"
    printf '  Restore with: mv "%s" "%s"\n' "$backup" "$agents"

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
# Codex
# ------------------------------------------------------------

# $1 scope, $2 1 when the destination's current content must be discarded
# (legacy adoption).
write_codex_block() {
    local scope="$1"
    local discard_existing="$2"
    local destination
    local resolved
    local directory
    local block_file
    local merged_file
    local eol=""

    destination="$(codex_file_path "$scope")"

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

    write_block "$block_file" "$RULE_SOURCE" "$eol"

    if [ "$discard_existing" -eq 1 ] && [ -f "$resolved" ]; then
        : >"$merged_file"
        cat "$block_file" >>"$merged_file"
    else
        merge_block "$resolved" "$block_file" "$merged_file"
    fi

    if [ -f "$resolved" ] && cmp -s "$resolved" "$merged_file"; then
        success "already current (codex, $scope): $resolved"
        return 0
    fi

    if ! atomic_write "$resolved" "$merged_file"; then
        error "could not write $resolved"
        return 1
    fi

    success "installed (codex, $scope): $resolved"

    return 0
}

install_codex() {
    local scope="$1"
    local destination
    local override
    # Tri-state, and the initial value matters: 1 means "no legacy copy was
    # involved", which must merge rather than discard. Reusing a two-state flag
    # here would drop everything outside the block on an ordinary re-install.
    #   1 = nothing to adopt, 0 = adopted, 2 = refused
    local adopt_status=1

    destination="$(codex_file_path "$scope")"

    # Checked before the write decision, not after it: AGENTS.override.md wins
    # over AGENTS.md, so the rule is inert even when nothing needed writing.
    override="$(dirname "$destination")/AGENTS.override.md"
    if [ -f "$override" ]; then
        warn "$override exists and takes precedence; Codex will not read $(basename "$destination")."
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
        adopt_legacy_codex_agents "$destination" || adopt_status=$?
        if [ "$adopt_status" -eq 2 ]; then
            return 1
        fi
    fi

    if [ "$adopt_status" -eq 0 ]; then
        write_codex_block "$scope" 1
    else
        write_codex_block "$scope" 0
    fi
}

remove_codex() {
    local scope="$1"
    local destination
    local resolved
    local rendered

    destination="$(codex_file_path "$scope")"

    if [ ! -f "$destination" ]; then
        printf '  not installed (codex, %s): %s\n' "$scope" "$destination"
        return 0
    fi

    if ! assert_markers_balanced "$destination"; then
        return 1
    fi

    if [ "$(count_marker_lines "$destination" "$(start_marker)")" -eq 0 ]; then
        printf '  not installed (codex, %s): %s\n' "$scope" "$destination"
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
        printf '  not installed (codex, %s): %s\n' "$scope" "$resolved"
        return 0
    fi

    if ! atomic_write "$resolved" "$rendered"; then
        error "could not write $resolved"
        return 1
    fi

    success "removed (codex, $scope): $resolved"
    return 0
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
                if [ "$scope" = "global" ]; then
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

# ------------------------------------------------------------
# Listing
# ------------------------------------------------------------

is_installed_claude() {
    local scope="$1"
    local path

    path="$(claude_rule_path "$scope")"
    [ -f "$path" ] && head -n 1 "$path" | grep -qF -- "$RULE_TITLE"
}

is_installed_codex() {
    local scope="$1"
    local path

    path="$(codex_file_path "$scope")"
    [ -f "$path" ] && [ "$(count_marker_lines "$path" "$(start_marker)")" -gt 0 ]
}

list_rules() {
    local name
    local scope
    local state
    local target

    printf 'Rules in %s\n\n' "$SOURCE_ROOT"

    for name in $(available_rules); do
        lookup_rule "$name" || continue
        scope="$RULE_SCOPE"
        # start_marker/end_marker read $RULE, which is empty when --list ran
        # without a rule argument; without this every rule looks uninstalled.
        RULE="$name"

        state=""
        for target in $TARGETS; do
            case "$target" in
            claude)
                if is_installed_claude global; then
                    state="${state:+$state }claude:global"
                fi
                if is_installed_claude project; then
                    state="${state:+$state }claude:project"
                fi
                ;;
            codex)
                if is_installed_codex global; then
                    state="${state:+$state }codex:global"
                fi
                if is_installed_codex project; then
                    state="${state:+$state }codex:project"
                fi
                ;;
            esac
        done

        printf '  %-20s %-8s %s\n' "$name" "$scope" "${state:-not installed}"
    done

    printf '\nPass --global to install a project-scoped rule for the whole user account.\n'
}

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

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

        if [ "$SCOPE" = "everywhere" ] || [ "$SCOPE" = "global" ]; then
            if ! migrate_legacy_claude_md; then
                FAILURES=$((FAILURES + 1))
            fi
        fi
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

main() {
    # `|| parse_rc=$?` rather than a bare call: parse_args returns 1 after
    # printing --help, and under `set -e` a bare call would abort the script
    # before the return code could be read. wsl_setup.sh gets away with the bare
    # form only because it does not run under `set -e`.
    parse_rc=0
    parse_args "$@" || parse_rc=$?

    # 0 继续；1 已打印 usage，按成功退出；其余是选项错误。
    case "$parse_rc" in
    0) ;;
    1) return 0 ;;
    *) return 2 ;;
    esac

    require_repo_layout
    require_safe_home

    if [ "$LIST_ONLY" -eq 1 ]; then
        resolve_targets || return 1
        PROJECT_DIR="$PWD"
        list_rules
        return 0
    fi

    if [ -z "$RULE" ]; then
        printf 'Error: missing rule name.\n\n' >&2
        usage >&2
        return 2
    fi

    if ! lookup_rule "$RULE"; then
        error "unknown rule: $RULE"
        printf 'Valid rules:\n' >&2
        print_rule_names
        return 1
    fi

    resolve_scope

    run
}

if [ "${BASH_SOURCE[0]:-}" = "$0" ]; then
    main "$@"
fi
