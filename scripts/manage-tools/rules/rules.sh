# Keep API and Git acquisition separate; publish the catalog only after success.
waza_catalog_api() {
    local staged="$1" commit
    loading_download https://api.github.com/repos/tw93/Waza/commits/main "$staged/commit.json" 'Resolving commit' || return 1
    commit="$(run_python "Waza rule catalog" rules/parse_waza.py commit "$staged/commit.json")" || return 1
    printf '%s\n' "$commit" >"$staged/resolved-commit" || return 1
    loading_download "https://api.github.com/repos/tw93/Waza/contents/rules?ref=$commit" "$staged/catalog.json" 'Downloading catalog' || return 1
    run_python "Waza rule catalog" rules/parse_waza.py catalog "$staged/catalog.json" >"$staged/names" || return 1
}

# The checkout never escapes this subshell. Only rule bytes and metadata survive it.
waza_clone_snapshot() (
    local staged="$1" pinned="${2:-}" checkout commit hash name
    require_command git || return 1
    checkout="$(mktemp -d "$staged/waza-clone.XXXXXX")" || return 1
    trap 'rm -rf -- "$checkout"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    printf 'Fetching Waza rules using Git clone...\n' >&2
    git clone --quiet --depth 1 --no-checkout --single-branch --branch main \
        https://github.com/tw93/Waza.git "$checkout/repo" || return 1
    commit="$(git -C "$checkout/repo" rev-parse HEAD)" || return 1
    if [ -n "$pinned" ] && [ "$commit" != "$pinned" ]; then
        git -C "$checkout/repo" fetch --quiet --depth 1 origin "$pinned" || return 1
        commit="$pinned"
    fi
    [[ "$commit" =~ ^[a-f0-9]{40}$ ]] || {
        printf 'Invalid Waza Git commit\n' >&2
        return 1
    }
    # Read blobs without a worktree, excluding symlinks and nested directories.
    git -C "$checkout/repo" ls-tree -z "$commit:rules" >"$checkout/tree" || return 1
    mkdir -p "$checkout/snapshot/rules" || return 1
    run_python "Waza rule catalog" rules/parse_waza.py tree "$checkout/tree" "$checkout/snapshot" || return 1
    while IFS=$'\t' read -r hash name; do
        git -C "$checkout/repo" cat-file blob "$hash" >"$checkout/snapshot/rules/$name.md" || return 1
    done <"$checkout/snapshot/blobs"
    cp "$checkout/snapshot/rules/"*.md "$staged/rules/" || return 1
    cp "$checkout/snapshot/names" "$staged/names" || return 1
    printf '%s\n' "$commit" >"$staged/resolved-commit"
)

# Publish the commit and names together after API discovery or its Git fallback.
acquire_waza_catalog() {
    local staged="$1" commit=""
    mkdir -p "$staged/rules" || return 1
    if ! waza_catalog_api "$staged"; then
        if [ -f "$staged/resolved-commit" ]; then IFS= read -r commit <"$staged/resolved-commit"; fi
        loading_phase 'Git fallback' || return 1
        waza_clone_snapshot "$staged" "$commit"
    fi
}

collect_waza_catalog() {
    local job="$1" staged="$LOADING_DIR/$1" commit names=()
    if ! content_load_succeeded "$job"; then
        WAZA_RULES_ERROR="$(cat "$staged/error")"
        return 1
    fi
    IFS= read -r commit <"$staged/resolved-commit" || return 1
    mapfile -t names <"$staged/names" || return 1
    if [ -z "$WAZA_TEMP" ]; then WAZA_TEMP="$(mktemp -d)" || return 1; fi
    mv -- "$staged" "$WAZA_TEMP/waza" || return 1
    # shellcheck disable=SC2034
    RULE_NAMES_WAZA=("${names[@]}")
    WAZA_RULES_COMMIT="$commit"
    WAZA_RULES_PATH="$WAZA_TEMP/waza/rules"
    # shellcheck disable=SC2034
    WAZA_RULES_ERROR=""
}

load_install_rule_catalogs() {
    local LOADING_JOBS=() LOADING_INDEX bundled='' waza='' result=0
    if [ "$RULE_CATALOG_PROJECT" -eq 0 ]; then
        queue_content_load rules-bundled 'Rules / Gwyntoria'
        bundled="$LOADING_INDEX"
    fi
    if [ -z "$WAZA_RULES_PATH" ]; then
        queue_content_load rules-waza 'Rules / Waza'
        waza="$LOADING_INDEX"
    fi
    if ! run_content_loads 'Install / Rule catalogs'; then
        cleanup_loading_batch
        return 2
    fi
    if [ -n "$bundled" ]; then
        if content_load_succeeded "$bundled" && mapfile -t RULE_NAMES_PROJECT <"$LOADING_DIR/$bundled/output"; then
            RULE_CATALOG_PROJECT=1
        else
            report_content_load_error "$bundled"
            result=2
        fi
    fi
    if [ "$result" -eq 0 ] && [ -n "$waza" ]; then collect_waza_catalog "$waza" || result=1; fi
    cleanup_loading_batch
    return "$result"
}

fetch_waza_rule() {
    local name="$1" commit="$2" path="$3"
    [[ "$name" =~ ^waza-[a-zA-Z0-9][a-zA-Z0-9._-]*$ && "$commit" =~ ^[a-f0-9]{40}$ ]] || return 2
    loading_download "https://raw.githubusercontent.com/tw93/Waza/$commit/rules/${name#waza-}.md" "$path" 'Downloading rule' || return 1
    validate_waza_rule "$path" || return 2
}

validate_waza_rule() {
    local title=""
    IFS= read -r title <"$1" || true
    case "$title" in '# '* | '## '*) return 0 ;; esac
    printf 'Waza rule must start with H1 or H2: %s\n' "${1##*/}" >&2
    return 1
}

prefetch_waza_rules() {
    local LOADING_JOBS=() LOADING_INDEX index job name status staged
    local names=() fallback=()
    for index in "${!SELECTED_RULES[@]}"; do
        [ "${SELECTED_RULE_SOURCES[index]:-$INSTALL_SCOPE}" = waza ] || continue
        name="${SELECTED_RULES[index]}"
        [ ! -f "$WAZA_RULES_PATH/$name.md" ] || continue
        queue_content_load waza-body "Rule / ${name#waza-}" "$name" "$WAZA_RULES_COMMIT"
        names+=("$name")
    done
    [ "${#names[@]}" -gt 0 ] || return 0
    if ! run_content_loads 'Install / Download Waza rules'; then
        cleanup_loading_batch
        return 1
    fi
    for job in "${!names[@]}"; do
        name="${names[job]}"
        IFS= read -r status <"$LOADING_DIR/$job/status" || status=1
        case "$status" in
        0)
            mv -- "$LOADING_DIR/$job/rule.md" "$WAZA_RULES_PATH/$name.md" || {
                cleanup_loading_batch
                return 1
            }
            ;;
        2) report_content_load_error "$job" ;;
        *) fallback+=("$name") ;;
        esac
    done
    cleanup_loading_batch

    [ "${#fallback[@]}" -gt 0 ] || return 0
    # shellcheck disable=SC2034
    LOADING_JOBS=()
    queue_content_load waza-fallback 'Rules / Waza Git fallback' '' "$WAZA_RULES_COMMIT"
    if ! run_content_loads 'Install / Download Waza rules'; then
        cleanup_loading_batch
        return 1
    fi
    if content_load_succeeded 0; then
        for name in "${fallback[@]}"; do
            staged="$LOADING_DIR/0/rules/$name.md"
            if [ -f "$staged" ] && validate_waza_rule "$staged"; then
                mv -- "$staged" "$WAZA_RULES_PATH/$name.md" || break
            fi
        done
    else
        report_content_load_error 0
    fi
    cleanup_loading_batch
}

resolve_rule_source() {
    local source_directory
    if [ "$1" = waza ]; then
        [ -n "$WAZA_RULES_PATH" ] || return 1
        source_directory="$WAZA_RULES_PATH"
    else
        source_directory="$(snapshot_resource rules)" || return 1
    fi
    printf -v "$2" '%s' "$source_directory"
}

load_rule_catalog() {
    local scope="$1" directory="$2" file name title names=()
    for file in "$directory"/*.md; do
        [ -f "$file" ] || continue
        name="${file##*/}"
        name="${name%.md}"
        if [[ ! "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then
            printf 'Invalid rule name: %s\n' "$file" >&2
            return 1
        fi
        title=""
        IFS= read -r title <"$file" || true
        case "$title" in '# '*) ;; *)
            printf 'Rule must start with H1: %s\n' "$file" >&2
            return 1
            ;;
        esac
        names+=("$name")
    done
    if [ "$scope" = global ]; then
        RULE_NAMES_GLOBAL=("${names[@]+"${names[@]}"}")
    else
        RULE_NAMES_PROJECT=("${names[@]+"${names[@]}"}")
        RULE_CATALOG_PROJECT=1
    fi
}

# Pi discovers global instructions here without a settings.json entry.
pi_rule_path() {
    local directory="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
    # Match a literal tilde supplied in the environment.
    # shellcheck disable=SC2088
    case "$directory" in
    '~') directory="$HOME" ;;
    '~/'*) directory="$HOME/${directory#\~/}" ;;
    esac
    printf '%s/AGENTS.md\n' "${directory%/}"
}

apply_rule() {
    rule_engine "$1" "$2" "$3" "$4" "$6" "$5"
}

# The rule engine owns its helpers only inside this subshell.
rule_engine() (
    set -euo pipefail
    RULE="$1"
    SCOPE="$2"
    TARGET_OPT="$3"
    MODE="${4:-install}"
    RULE_FILE="$RULE.md"
    RULE_CLASSIFICATION="${6:-$SCOPE}"
    RULE_SOURCE=""
    RULE_TITLE=""
    TARGETS=""
    SCOPES=""
    FAILURES=0
    PROJECT_DIR=""
    case "$SCOPE" in global | project) ;; *) return 2 ;; esac
    if [[ ! "$RULE" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then return 2; fi
    if [ "$MODE" = install ]; then
        RULE_SOURCE="$5/$RULE_FILE"
        [ -f "$RULE_SOURCE" ] || {
            printf 'Missing rule: %s\n' "$RULE_SOURCE" >&2
            return 1
        }
        IFS= read -r RULE_TITLE <"$RULE_SOURCE" || true
        if [ "$RULE_CLASSIFICATION" = waza ]; then
            case "$RULE_TITLE" in '# '* | '## '*) ;; *)
                printf 'Waza rule must start with H1 or H2: %s\n' "$RULE_SOURCE" >&2
                return 1
                ;;
            esac
        else
            case "$RULE_TITLE" in '# '*) ;; *)
                printf 'Rule must start with H1: %s\n' "$RULE_SOURCE" >&2
                return 1
                ;;
            esac
        fi
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

    resolve_symlinks() {
        local path="$1"
        local directory
        local link
        local hops=0

        while [ -L "$path" ]; do
            if [ "$hops" -ge 8 ]; then
                error "too many symlink hops resolving $1"
                return 1
            fi
            hops=$((hops + 1))
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
        claude | codex | pi | 'codex claude' | 'codex pi' | 'claude pi' | 'codex claude pi')
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
            error "unknown target: $TARGET_OPT (expected selected codex, claude, pi targets, both, or auto)"
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
        esac
    }

    codex_file_path() {
        case "$1" in
        global) printf '%s\n' "$HOME/.codex/AGENTS.md" ;;
        esac
    }

    rule_file_path() {
        if [ "$2" = project ]; then
            printf '%s/docs/rules/%s\n' "$PROJECT_DIR" "$RULE_FILE"
            return 0
        fi
        case "$1" in
        claude) claude_rule_path "$2" ;;
        codex) codex_file_path "$2" ;;
        pi) pi_rule_path ;;
        esac
    }

    # Shift ATX headings relative to the rule title, leaving fenced/indented code alone.
    format_rule_headings() {
        local body="$1"
        local level="$2"
        awk -v target="$level" '
        NR == 1 {
            title = $0
            sub(/[^#].*$/, "", title)
            shift = target - length(title)
        }
        {
            line = $0
            sub(/\r$/, "", line)
            # Markdown fences and headings allow at most three leading spaces.
            sub(/^ ? ? ?/, "", line)
            if (fence != "") {
                run = line
                sub(fence == "`" ? "[^`].*$" : "[^~].*$", "", run)
                tail = substr(line, length(run) + 1)
                if (substr(line, 1, 1) == fence && length(run) >= width && tail ~ /^[ \t]*$/)
                    fence = ""
                print
                next
            }
            if (line ~ /^```/ || line ~ /^~~~/) {
                fence = substr(line, 1, 1)
                run = line
                sub(fence == "`" ? "[^`].*$" : "[^~].*$", "", run)
                width = length(run)
                print
                next
            }
            if (line ~ /^#+([ \t]|$)/) {
                hashes = line
                sub(/[^#].*$/, "", hashes)
                if (length(hashes) <= 6) {
                    level = length(hashes) + shift
                    if (level > 6) level = 6
                    prefix = ""
                    for (i = 0; i < level; i++) prefix = prefix "#"
                    indent = length($0) - length(line)
                    # line has no CR; use the original line to preserve its ending.
                    if ($0 ~ /\r$/) indent--
                    $0 = substr($0, 1, indent) prefix substr($0, indent + length(hashes) + 1)
                }
            }
            print
        }
    ' "$body"
    }

    # Append in place: existing bytes, including legacy markers, are user content.
    append_rule_file() {
        local source_hashes="${RULE_TITLE%% *}"
        local target="$1" scope="$2" destination resolved level="${#source_hashes}" eol="" last_byte
        destination="$(rule_file_path "$target" "$scope")"
        resolved="$(resolve_symlinks "$destination")" || return 1
        mkdir -p "$(dirname "$resolved")" || return 1
        if [ "$target" = claude ]; then
            level=1
        else
            if [ "$scope" = global ] && [ -f "$(dirname "$destination")/AGENTS.override.md" ]; then
                warn "$(dirname "$destination")/AGENTS.override.md exists and takes precedence; $target will not read $(basename "$destination")."
            fi
            if [ "$scope" = global ] || [ "$RULE_CLASSIFICATION" = project ]; then level=2; fi
        fi
        if [ -f "$resolved" ] && LC_ALL=C grep -qU $'\r' "$resolved"; then eol=$'\r'; fi

        if [ -s "$resolved" ]; then
            last_byte="$(tail -c 1 "$resolved" | od -An -tu1 | tr -d '[:space:]')"
            if [ "$last_byte" != 10 ]; then
                printf '%s\n%s\n' "$eol" "$eol" >>"$resolved" || return 1
            elif [ -n "$(tail -n 1 "$resolved" | tr -d '\r\n')" ]; then
                printf '%s\n' "$eol" >>"$resolved" || return 1
            fi
        elif [ "$target" != claude ] && [ "$scope" = global ]; then
            printf '# Global Rules%s\n%s\n' "$eol" "$eol" >>"$resolved" || return 1
        fi
        if ! format_rule_headings "$RULE_SOURCE" "$level" |
            awk -v eol="$eol" '{ sub(/\r$/, ""); printf "%s%s\n", $0, eol }' >>"$resolved"; then
            error "could not append $resolved"
            return 1
        fi
        printf '\033[1;34m✓ installation complete (%s, %s): %s\033[0m\n' "$target" "$scope" "$resolved"
    }

    remove_rule_file() {
        local destination
        destination="$(rule_file_path "$1" "$2")"
        if [ ! -e "$destination" ] && [ ! -L "$destination" ]; then
            printf '  not installed (%s, %s): %s\n' "$1" "$2" "$destination"
            return 0
        fi
        # Unlink the selected path; never resolve a rule link for removal.
        rm -f -- "$destination" || return 1
        success "removed ($1, $2): $destination"
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
            codex | pi | project)
                for scope in $SCOPES; do
                    directory="$(dirname "$(rule_file_path "$target" "$scope")")"
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

        resolve_targets || return 1
        # Project rules are shared files, so multiple selected agents write only once.
        if [ "$SCOPE" = project ]; then TARGETS=project; fi

        if [ "$MODE" = "install" ]; then
            preflight || return 1

            log "Installing $RULE_FILE"
        else
            log "Removing $RULE_FILE"
        fi

        for target in $TARGETS; do
            for scope in $SCOPES; do
                status=0
                if [ "$MODE" = install ]; then
                    append_rule_file "$target" "$scope" || status=1
                else
                    remove_rule_file "$target" "$scope" || status=1
                fi
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

print_rule_names() {
    local RULE_NAMES_GLOBAL=()
    load_rule_catalog global "$1" || return 1
    if [ "${#RULE_NAMES_GLOBAL[@]}" -gt 0 ]; then
        printf '%s\n' "${RULE_NAMES_GLOBAL[@]}"
    fi
}
