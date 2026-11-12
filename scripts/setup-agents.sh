#!/usr/bin/env bash

set -eu

PROGRAM_NAME="setup-agents.sh"
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
SCRIPT_PATH=""
SCRIPT_DIR=""
REPO=""
# stdin execution has no source file; never infer a repository from the caller.
if [ -n "${BASH_SOURCE[0]:-}" ]; then
    PROGRAM_NAME="${0##*/}"
    SCRIPT_PATH="$(resolve_script_path "${BASH_SOURCE[0]}")"
    SCRIPT_DIR="${SCRIPT_PATH%/*}"
    REPO="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
fi
PROJECT_TARGET="$(pwd -P)"
SOURCE_ARCHIVE_URL=https://codeload.github.com/gwyntoria/skills/tar.gz/refs/heads/main
LATEST_SCRIPT_URL=https://raw.githubusercontent.com/gwyntoria/skills/main/scripts/setup-agents.sh
RESOURCE_TEMP=""
RESOURCE_PATH=""
STATUSLINE_SOURCE=""
RULE_SCOPE=global
RULE_TARGETS="codex claude pi"
SELECTED_RULES=()
SELECTED_RULE_SOURCES=()
RULE_NAMES_GLOBAL=()
RULE_NAMES_PROJECT=()
RULE_CATALOG_PROJECT=0
RULE_NAMES_WAZA=()
WAZA_RULES_PATH=""
WAZA_RULES_COMMIT=""
WAZA_RULES_ERROR=""

WAZA_SKILLS_URL="https://github.com/tw93/waza"
KAMI_SKILLS_URL="https://github.com/tw93/kami"
MATTPOCOCK_SKILLS_URL="https://github.com/mattpocock/skills"
MATTPOCOCK_SKILLS_PAGE_URL="https://www.aihero.dev/skills"
HUMANLAYER_SKILLS_URL="https://github.com/humanlayer/skills"
GWYNTORIA_SKILLS_URL="https://github.com/gwyntoria/skills"
DISTILLY_SKILLS_URL="https://github.com/titanwings/distilly"
# Parallel arrays keep this compatible with the Bash shipped by macOS.
SKILL_SOURCE_GROUPS=(Waza Kami 'Matt Pocock' HumanLayer Gwyntoria Distilly)
SKILL_NAMES=()
SKILL_SOURCES=()
SKILL_GROUPS=()
SKILL_PICKED=()
SKILL_EXPLICIT=()
CATALOG_CACHE_GROUPS=()
CATALOG_CACHE_NAMES=()
CATALOG_FAILURES=()
CATALOG_FETCHED_NAMES=""
SELECTED_REPOS=()
VIEW_SKILL_INDICES=()
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
REMOVE_PI=1
REMOVE_RULES=0
REMOVE_SKILLS=0
REMOVE_SCOPE=global
REMOVAL_TEMP=""
REMOVAL_RULE_IDS=(); REMOVAL_RULE_LABELS=(); REMOVAL_SKILL_IDS=(); REMOVAL_SKILL_LABELS=(); REMOVAL_SKILL_GROUPS=()
REMOVAL_RULE_SELECTION=(); REMOVAL_SKILL_SELECTION=()
REPO_ITEM_LABELS=(); REPO_ITEM_GROUPS=(); REPO_SELECTED=()
REPO_EXPLICIT=()

log() { printf '\n==> %s\n' "$1"; }

usage() {
    cat <<EOF
Usage: $PROGRAM_NAME [--agent] [--skill] | --list

No arguments: open the interactive menu (requires a terminal).
  --agent     Choose Codex and Claude Code by default; Pi is optional, with bundled components
  --skill     Install/update all configured skills; preserve existing skills
  --list      List available skills by source without installing
  -h, --help  Show help

The menu also provides a separate, confirmed removal action with an optional backup (default: no).
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

# A Bash child cannot trigger the parent Zsh's lazy nvm functions.
require_node() {
    command -v node >/dev/null 2>&1 && return 0
    local nvm_script="${NVM_DIR:-$HOME/.nvm}/nvm.sh"
    if [ -s "$nvm_script" ]; then
        # shellcheck disable=SC1090
        if source "$nvm_script" --no-use && nvm use --silent default; then
            command -v node >/dev/null 2>&1 && return 0
        fi
    fi
    printf 'Error: Node.js is unavailable. Load nvm and activate an installed default version (nvm use default), or install Node.js, then retry.\n' >&2
    return 1
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
    printf '    \033[32mShared skill / %s -> %s/.agents/skills/%s\033[0m\n' "$name" "$HOME" "$name"
    for agent in "${TARGET_AGENTS[@]}"; do
        if [ "$agent" = claude-code ]; then
            destination="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/$name"
            printf '    \033[32mClaude / %s -> %s\033[0m\n' "$name" "$destination"
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

skill_source_url() {
    case "$1" in
        Waza) printf '%s\n' "$WAZA_SKILLS_URL" ;;
        Kami) printf '%s\n' "$KAMI_SKILLS_URL" ;;
        'Matt Pocock') printf '%s\n' "$MATTPOCOCK_SKILLS_URL" ;;
        HumanLayer) printf '%s\n' "$HUMANLAYER_SKILLS_URL" ;;
        Gwyntoria) printf '%s\n' "$GWYNTORIA_SKILLS_URL" ;;
        Distilly) printf '%s\n' "$DISTILLY_SKILLS_URL" ;;
        *) return 1 ;;
    esac
}

catalog_report_failure() {
    CATALOG_FAILURES+=("$1")
    FAILED+=("$1")
}

# Set CATALOG_FETCHED_NAMES for one source group. A group is fetched at most
# once per session; the cache survives returning to the main menu so a second
# run never waits on a repository it already pulled.
catalog_fetch_group() {
    local group="$1" source names valid name i
    CATALOG_FETCHED_NAMES=""
    for ((i=0; i<${#CATALOG_CACHE_GROUPS[@]}; i++)); do
        if [ "${CATALOG_CACHE_GROUPS[i]}" = "$group" ]; then
            CATALOG_FETCHED_NAMES="${CATALOG_CACHE_NAMES[i]}"
            return 0
        fi
    done
    source="$(skill_source_url "$group")" || return 0
    printf 'Loading %s...\n' "$group" >&2
    names=""
    if [ "$group" = 'Matt Pocock' ]; then
        names=$(fetch_mattpocock_skill_names) || names=""
    elif [ "$group" = HumanLayer ]; then
        names=show-me
    else
        names=$(fetch_repository_skill_names "$source") || names=""
    fi
    if [ -z "$names" ]; then
        CATALOG_CACHE_GROUPS+=("$group")
        CATALOG_CACHE_NAMES+=("")
        catalog_report_failure "Catalog: $group ($source)"
        return 0
    fi
    valid=""
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        if [[ ! "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then
            catalog_report_failure "Catalog: $group (invalid skill name)"
            continue
        fi
        if [ -n "$valid" ]; then valid="$valid"$'\n'; fi
        valid="$valid$name"
    done <<<"$names"
    CATALOG_CACHE_GROUPS+=("$group")
    CATALOG_CACHE_NAMES+=("$valid")
    CATALOG_FETCHED_NAMES="$valid"
}

# Append one source group's skills to the session table, fetching only when
# the cache has no copy yet. New skills start selected.
catalog_add_group() {
    local group="$1" source name i
    source="$(skill_source_url "$group")" || return 1
    for ((i=0; i<${#SKILL_GROUPS[@]}; i++)); do
        [ "${SKILL_GROUPS[i]}" != "$group" ] || return 0
    done
    catalog_fetch_group "$group"
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        SKILL_NAMES+=("$name")
        SKILL_SOURCES+=("$source")
        SKILL_GROUPS+=("$group")
        SKILL_PICKED+=(1)
        SKILL_EXPLICIT+=(1)
    done <<<"$CATALOG_FETCHED_NAMES"
}

load_catalog() {
    local group name
    SKILL_NAMES=(); SKILL_SOURCES=(); SKILL_GROUPS=(); SKILL_PICKED=(); SKILL_EXPLICIT=()
    for group in "${SKILL_SOURCE_GROUPS[@]}"; do
        catalog_add_group "$group"
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

# Whether a source group is ticked on the repository page.
repo_group_selected() {
    local group="$1" i
    for i in "${SELECTED_REPOS[@]+"${SELECTED_REPOS[@]}"}"; do
        [ "${SKILL_SOURCE_GROUPS[i]}" != "$group" ] || return 0
    done
    return 1
}

# Rebuild the repository/skill picker for the chosen repositories only.
# VIEW_SKILL_INDICES maps picker positions back to SKILL_* indices so
# selection survives adding or dropping a repository between visits.
catalog_build_view() {
    local i pos
    REPO_ITEM_LABELS=(); REPO_ITEM_GROUPS=(); REPO_SELECTED=(); REPO_EXPLICIT=(); VIEW_SKILL_INDICES=()
    for ((i=0; i<${#SKILL_NAMES[@]}; i++)); do
        repo_group_selected "${SKILL_GROUPS[i]}" || continue
        REPO_ITEM_LABELS+=("${SKILL_NAMES[i]}")
        REPO_ITEM_GROUPS+=("${SKILL_SOURCES[i]#https://github.com/}")
        VIEW_SKILL_INDICES+=("$i")
        pos=$((${#VIEW_SKILL_INDICES[@]} - 1))
        REPO_EXPLICIT+=("${SKILL_EXPLICIT[i]}")
        [ "${SKILL_PICKED[i]}" -eq 0 ] || REPO_SELECTED+=("$pos")
    done
}

# Write the picker's selection back into SKILL_PICKED, then refresh the
# install set. Skills outside the view keep their last state.
catalog_sync_selection() {
    local pos i
    for ((pos=0; pos<${#VIEW_SKILL_INDICES[@]}; pos++)); do
        i="${VIEW_SKILL_INDICES[pos]}"
        SKILL_PICKED[i]=0
        SKILL_EXPLICIT[i]="${REPO_EXPLICIT[pos]}"
    done
    for pos in "${REPO_SELECTED[@]+"${REPO_SELECTED[@]}"}"; do
        i="${VIEW_SKILL_INDICES[pos]}"
        SKILL_PICKED[i]=1
    done
    catalog_collect_selection
}

# SELECTED_SKILLS is the install set: picked skills from chosen repositories.
catalog_collect_selection() {
    local i
    SELECTED_SKILLS=()
    for ((i=0; i<${#SKILL_NAMES[@]}; i++)); do
        [ "${SKILL_PICKED[i]}" -ne 0 ] || continue
        repo_group_selected "${SKILL_GROUPS[i]}" || continue
        SELECTED_SKILLS+=("$i")
    done
}

cleanup_setup_resources() {
    if [ -t 1 ]; then printf '\033[?25h'; fi
    if [ -n "$RESOURCE_TEMP" ]; then rm -rf -- "$RESOURCE_TEMP"; fi
    if [ -n "$REMOVAL_TEMP" ]; then rm -rf -- "$REMOVAL_TEMP"; fi
}

resolve_resource() {
    local relative="$1" candidate="$REPO/$1"
    case "$relative" in rules | scripts/statusline.sh) ;; *) return 2 ;; esac
    if [ -n "$REPO" ] && { [ -e "$candidate" ] || [ -L "$candidate" ]; }; then
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
        rules) [ -d "$RESOURCE_PATH" ] ;;
        *) [ -f "$RESOURCE_PATH" ] ;;
    esac || { printf 'Invalid resource: %s\n' "$RESOURCE_PATH" >&2; return 1; }
}

# Keep API and Git acquisition separate; publish the catalog only after success.
waza_catalog_api() {
    local staged="$1" commit
    require_command curl || return 1
    curl -fLsS https://api.github.com/repos/tw93/Waza/commits/main -o "$staged/commit.json" || return 1
    commit="$(node -e '
        const fs = require("fs");
        const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
        if (!/^[a-f0-9]{40}$/.test(data.sha)) { console.error("Invalid Waza commit"); process.exit(1); }
        console.log(data.sha);
    ' "$staged/commit.json")" || return 1
    printf '%s\n' "$commit" > "$staged/resolved-commit" || return 1
    curl -fLsS "https://api.github.com/repos/tw93/Waza/contents/rules?ref=$commit" -o "$staged/catalog.json" || return 1
    node -e '
        const fs = require("fs");
        const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
        if (!Array.isArray(data)) { console.error("Invalid Waza rule catalog"); process.exit(1); }
        const names = [];
        for (const entry of data) {
            if (entry.type !== "file" || typeof entry.name !== "string" || !entry.name.endsWith(".md")) continue;
            if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]*\.md$/.test(entry.name)) {
                console.error("Invalid Waza rule filename"); process.exit(1);
            }
            names.push("waza-" + entry.name.slice(0, -3));
        }
        if (!names.length) { console.error("No Waza rules available"); process.exit(1); }
        console.log([...new Set(names)].sort().join("\n"));
    ' "$staged/catalog.json" > "$staged/names" || return 1
}

# The checkout never escapes this subshell. Only rule bytes and metadata survive it.
waza_clone_snapshot() (
    local staged="$1" pinned="${2:-}" checkout commit hash name
    require_command git || return 1
    checkout="$(mktemp -d "$RESOURCE_TEMP/waza-clone.XXXXXX")" || return 1
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
    [[ "$commit" =~ ^[a-f0-9]{40}$ ]] || { printf 'Invalid Waza Git commit\n' >&2; return 1; }
    # Read blobs without a worktree, excluding symlinks and nested directories.
    git -C "$checkout/repo" ls-tree -z "$commit:rules" > "$checkout/tree" || return 1
    mkdir -p "$checkout/snapshot/rules" || return 1
    node -e '
        const fs = require("fs");
        const [tree, output] = process.argv.slice(1);
        const entries = [];
        for (const row of fs.readFileSync(tree, "utf8").split("\0")) {
            if (!row) continue;
            const match = /^(100644|100755) blob ([a-f0-9]{40})\t(.*)$/s.exec(row);
            if (!match || !match[3].endsWith(".md")) continue;
            if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]*\.md$/.test(match[3])) throw new Error("Invalid Waza rule filename");
            entries.push(["waza-" + match[3].slice(0, -3), match[2]]);
        }
        if (!entries.length) throw new Error("No Waza rules available");
        entries.sort((a, b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0);
        fs.writeFileSync(output + "/names", entries.map(e => e[0]).join("\n") + "\n");
        fs.writeFileSync(output + "/blobs", entries.map(e => e[1] + "\t" + e[0]).join("\n") + "\n");
    ' "$checkout/tree" "$checkout/snapshot" || return 1
    while IFS=$'\t' read -r hash name; do
        git -C "$checkout/repo" cat-file blob "$hash" > "$checkout/snapshot/rules/$name.md" || return 1
    done < "$checkout/snapshot/blobs"
    cp "$checkout/snapshot/rules/"*.md "$staged/rules/" || return 1
    cp "$checkout/snapshot/names" "$staged/names" || return 1
    printf '%s\n' "$commit" > "$staged/resolved-commit"
)

# Pin the catalog before selection; every selected body uses the same commit.
load_waza_rules() {
    local staged commit name names=()
    [ -n "$WAZA_RULES_PATH" ] && return 0
    require_node || return 1
    if [ -z "$RESOURCE_TEMP" ]; then
        RESOURCE_TEMP="$(mktemp -d)" || return 1
        trap cleanup_setup_resources EXIT
        trap 'exit 130' INT
        trap 'exit 143' TERM
    fi
    staged="$RESOURCE_TEMP/waza"
    rm -rf -- "$staged" || return 1
    mkdir -p "$staged/rules" || return 1
    printf 'Fetching Waza rule catalog from GitHub main...\n' >&2
    if ! waza_catalog_api "$staged" 2> "$staged/error.log"; then
        commit=""
        if [ -f "$staged/resolved-commit" ]; then IFS= read -r commit < "$staged/resolved-commit"; fi
        printf 'Waza API unavailable; trying Git clone.\n' >&2
        if ! waza_clone_snapshot "$staged" "$commit" 2>> "$staged/error.log"; then
            WAZA_RULES_ERROR="$(cat "$staged/error.log")"
            printf '%s\n' "$WAZA_RULES_ERROR" >&2
            return 1
        fi
    fi
    IFS= read -r commit < "$staged/resolved-commit" || return 1
    while IFS= read -r name; do names+=("$name"); done < "$staged/names"
    RULE_NAMES_WAZA=("${names[@]}")
    WAZA_RULES_COMMIT="$commit"
    WAZA_RULES_PATH="$staged/rules"
    WAZA_RULES_ERROR=""
}

fetch_waza_rule() {
    local name="$1" candidate title listed found=0
    load_waza_rules || return 1
    for listed in "${RULE_NAMES_WAZA[@]}"; do
        if [ "$listed" = "$name" ]; then found=1; break; fi
    done
    [ "$found" -eq 1 ] || { printf 'Unknown Waza rule: %s\n' "$name" >&2; return 1; }
    candidate="$WAZA_RULES_PATH/$name.md"
    if [ ! -f "$candidate" ]; then
        if curl -fLsS "https://raw.githubusercontent.com/tw93/Waza/$WAZA_RULES_COMMIT/rules/${name#waza-}.md" \
            -o "$candidate.download"; then
            mv "$candidate.download" "$candidate" || return 1
        else
            rm -f -- "$candidate.download"
            printf 'Waza raw download unavailable; trying Git clone at %s.\n' "$WAZA_RULES_COMMIT" >&2
            waza_clone_snapshot "$RESOURCE_TEMP/waza" "$WAZA_RULES_COMMIT" || return 1
        fi
    fi
    title=""; IFS= read -r title < "$candidate" || true
    case "$title" in '# '* | '## '*) ;; *)
        rm -f -- "$candidate"
        printf 'Waza rule must start with H1 or H2: %s\n' "$name" >&2; return 1 ;;
    esac
}

resolve_rule_source() {
    if [ "$1" = waza ]; then
        load_waza_rules || return 1
        RESOURCE_PATH="$WAZA_RULES_PATH"
    else
        resolve_resource rules
    fi
}

load_rule_catalog() {
    local file name title names=()
    resolve_resource rules || return 1
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
        RULE_NAMES_GLOBAL=("${names[@]+"${names[@]}"}")
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
    if [ "${SCRIPT_PATH##*/}" = setup-agents.sh ] &&
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
    if [ "${4:-install}" = install ]; then
        resolve_rule_source "${5:-$2}" || return 1
        if [ "${5:-$2}" = waza ]; then fetch_waza_rule "$1" || return 1; fi
    fi
    rule_engine "$1" "$2" "$3" "${4:-install}" "$RESOURCE_PATH" "${5:-$2}"
}

# The rule engine owns its helpers and traps only inside this subshell.
rule_engine() (
    set -euo pipefail
    PROGRAM_NAME='setup-agents.sh'
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
        if [ "$RULE_CLASSIFICATION" = waza ]; then
            case "$RULE_TITLE" in '# '* | '## '*) ;; *) printf 'Waza rule must start with H1 or H2: %s\n' "$RULE_SOURCE" >&2; return 1 ;; esac
        else
            case "$RULE_TITLE" in '# '*) ;; *) printf 'Rule must start with H1: %s\n' "$RULE_SOURCE" >&2; return 1 ;; esac
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
    project) printf '%s\n' "$PROJECT_DIR/.claude/rules/$RULE_FILE" ;;
    esac
}

codex_file_path() {
    case "$1" in
    global) printf '%s\n' "$HOME/.codex/AGENTS.md" ;;
    project) printf '%s\n' "$PROJECT_DIR/AGENTS.md" ;;
    esac
}

managed_file_path() {
    case "$1" in
        claude) claude_rule_path "$2" ;;
        codex) codex_file_path "$2" ;;
        pi)
            if [ "$2" = global ]; then pi_rule_path
            else printf '%s/AGENTS.md\n' "$PROJECT_DIR"; fi ;;
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

# Build the managed block: markers, a provenance line, then the rendered body.
# Only Codex project installations retain the legacy omit-title behavior.
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
        if [ "$RULE_CLASSIFICATION" = waza ]; then
            printf '<!-- Installed from https://github.com/tw93/Waza/blob/%s/rules/%s.md by %s. Edits inside this block are overwritten on reinstall. -->%s\n' \
                "${WAZA_RULES_COMMIT:-main}" "${RULE#waza-}" "$PROGRAM_NAME" "$eol"
        else
            printf '<!-- Installed from rules/%s by %s. Edits inside this block are overwritten on reinstall. -->%s\n' \
                "$RULE_FILE" "$PROGRAM_NAME" "$eol"
        fi
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

    # Replacing an existing block in place keeps other blocks and separators
    # stable, so repeated batch installations compare equal to the current file.
    if [ -s "$block_file" ] && [ -f "$destination" ] &&
       grep -qFx -e "$start" -e "$start"$'\r' -- "$destination"; then
        awk -v start="$start" -v end="$end" '
            NR == FNR { replacement = replacement $0 "\n"; next }
            { line = $0; sub(/\r$/, "", line) }
            line == start { printf "%s", replacement; replacing = 1; next }
            replacing && line == end { replacing = 0; next }
            !replacing { print }
        ' "$block_file" "$destination" >"$output"
        return $?
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
    local body="$SCRATCH_DIR/claude-body"
    local title

    format_rule_headings "$RULE_SOURCE" 1 >"$body"
    IFS= read -r title <"$body" || true

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

    if [ -e "$resolved" ] && ! cmp -s "$resolved" "$body"; then
        if ! head -n 1 "$resolved" | grep -qF -- "$RULE_TITLE" &&
           ! head -n 1 "$resolved" | grep -qF -- "$title"; then
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

    if [ -e "$resolved" ] && cmp -s "$resolved" "$body"; then
        printf '\033[1;33m✓ already installed (claude, %s): %s\033[0m\n' "$scope" "$resolved"
        return 0
    fi

    if ! atomic_write "$resolved" "$body"; then
        error "could not write $resolved"
        return 1
    fi

    printf '\033[1;34m✓ installation complete (claude, %s): %s\033[0m\n' "$scope" "$resolved"
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
    local body="$RULE_SOURCE"

    destination="$(managed_file_path "$target" "$scope")"

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

    if [ "$target" != "claude" ] && [ "$scope" = "global" ]; then
        body="$SCRATCH_DIR/codex-body"
        format_rule_headings "$RULE_SOURCE" 2 >"$body"
    elif [ "$target" = "codex" ] && [ "$RULE_CLASSIFICATION" = "project" ]; then
        omit_h1=1
    fi

    write_block "$block_file" "$body" "$eol" "$omit_h1"

    if [ "$discard_existing" -eq 1 ] && [ -f "$resolved" ]; then
        : >"$merged_file"
        cat "$block_file" >>"$merged_file"
    else
        merge_block "$resolved" "$block_file" "$merged_file"
    fi

    if [ "$target" != "claude" ] && [ "$scope" = "global" ] &&
       [ "$(head -n 1 "$merged_file" | tr -d '\r')" != '# Global Rules' ]; then
        { printf '# Global Rules%s\n%s\n' "$eol" "$eol"; cat "$merged_file"; } >"$SCRATCH_DIR/titled"
        mv "$SCRATCH_DIR/titled" "$merged_file"
    fi

    if [ -f "$resolved" ] && cmp -s "$resolved" "$merged_file"; then
        printf '\033[1;33m✓ already installed (%s, %s): %s\033[0m\n' "$target" "$scope" "$resolved"
        return 0
    fi

    if ! atomic_write "$resolved" "$merged_file"; then
        error "could not write $resolved"
        return 1
    fi

    printf '\033[1;34m✓ installation complete (%s, %s): %s\033[0m\n' "$target" "$scope" "$resolved"

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

    destination="$(managed_file_path "$target" "$scope")"

    # Checked before the write decision, not after it: AGENTS.override.md wins
    # over AGENTS.md, so the rule is inert even when nothing needed writing.
    if [ "$target" != "claude" ]; then
        override="$(dirname "$destination")/AGENTS.override.md"
        if [ -f "$override" ]; then
            warn "$override exists and takes precedence; $target will not read $(basename "$destination")."
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

    destination="$(managed_file_path "$target" "$scope")"

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
        codex | pi)
            for scope in $SCOPES; do
                directory="$(dirname "$(managed_file_path "$target" "$scope")")"
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
            pi)
                if [ "$MODE" = "install" ]; then
                    install_managed_file pi "$scope" || status=1
                else
                    remove_managed_file pi "$scope" || status=1
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

install_pi() {
    require_node
    require_command npm
    if ! command -v pi >/dev/null 2>&1; then
        npm install -g --ignore-scripts @earendil-works/pi-coding-agent
    fi
    require_command pi
    pi --version
}

PI_PACKAGES=(npm:pi-web-access npm:pi-subagents npm:pi-powerline-footer)

# No stty mode changes: read -s restores echo even on cancellation/signals.
read_key() {
    local suffix=""
    KEY=""
    IFS= read -rsn1 KEY || return 1
    if [ "$KEY" = $'\e' ]; then
        # Allow split arrow sequences while keeping standalone Esc responsive.
        IFS= read -rsn2 -t 0.05 suffix || true
        KEY="$KEY$suffix"
    fi
}

# Read a confirmation into REPLY, retaining Enter submission and backspace.
# A standalone Esc discards pending input and returns the existing Back answer.
read_back_answer() {
    REPLY=""
    while read_key; do
        case "$KEY" in
            '') printf '\n'; return 0 ;;
            $'\e') REPLY=b; printf '\n'; return 0 ;;
            $'\177' | $'\b')
                if [ -n "$REPLY" ]; then REPLY="${REPLY%?}"; printf '\b \b'; fi ;;
            $'\e'*) ;; # Navigation sequences are not confirmation text or Back.
            *) REPLY+="$KEY"; printf '%s' "$KEY" ;;
        esac
    done
    return 1
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
    # Defaults are one shared flag or a space-separated flag for each option.
    if [[ "$defaults" = *" "* ]]; then
        read -r -a selected <<<"$defaults"
    else
        for ((i=0; i<${#options[@]}; i++)); do selected+=("$defaults"); done
    fi
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
        if [ "$page" -ne 0 ]; then printf ' | b/Esc: back'; fi
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
            b | B | $'\e') if [ "$page" -ne 0 ]; then return 2; fi ;;
            q | Q) return 1 ;;
        esac
    done
}

# Dependency helpers use the picker's local arrays through Bash dynamic scope.
# Keep this table in sync with upstream SKILL.md, not workflow/related links:
# https://github.com/mattpocock/skills
# https://www.aihero.dev/skills
# Include calls in conditional branches so every supported path is available.
matt_skill_dependencies() {
    case "$1" in
        grill-me) printf '%s\n' grilling ;;
        grill-with-docs) printf '%s\n' grilling domain-modeling ;;
        tdd) printf '%s\n' codebase-design ;;
        implement | implement-spec) printf '%s\n' tdd code-review ;;
        wayfinder) printf '%s\n' grilling domain-modeling prototype research ;;
        improve-codebase-architecture) printf '%s\n' codebase-design grilling domain-modeling ;;
        triage) printf '%s\n' grilling domain-modeling ;;
        retro) printf '%s\n' writing-for-agents ;;
    esac
}

picker_dependency_graph() {
    local i j dependency match changed=1
    for ((i=0; i<${#selected[@]}; i++)); do
        requirements[i]=" $i "; missing[i]=''
        [ "${REPO_ITEM_GROUPS[i]}" = mattpocock/skills ] || continue
        while IFS= read -r dependency; do
            [ -n "$dependency" ] || continue
            match=-1
            for ((j=0; j<${#selected[@]}; j++)); do
                if [ "${REPO_ITEM_GROUPS[j]}" = mattpocock/skills ] && [ "${REPO_ITEM_LABELS[j]}" = "$dependency" ]; then match="$j"; break; fi
            done
            if [ "$match" -lt 0 ]; then missing[i]="$dependency";
            else requirements[i]+="$match "; fi
        done < <(matt_skill_dependencies "${REPO_ITEM_LABELS[i]}")
    done
    # Compute transitive closure once, including missing transitive dependencies.
    # Membership checks also make cycles terminate.
    while [ "$changed" -eq 1 ]; do
        changed=0
        for ((i=0; i<${#selected[@]}; i++)); do
            for j in ${requirements[i]}; do
                if [ -z "${missing[i]}" ] && [ -n "${missing[j]}" ]; then missing[i]="${missing[j]}"; changed=1; fi
                for dependency in ${requirements[j]}; do
                    if [[ "${requirements[i]}" != *" $dependency "* ]]; then requirements[i]+="$dependency "; changed=1; fi
                done
            done
        done
    done
}

picker_resolve_dependencies() {
    local i dependency
    for ((i=0; i<${#selected[@]}; i++)); do selected[i]=0; done
    for ((i=0; i<${#selected[@]}; i++)); do
        [ "${explicit[i]}" -ne 0 ] || continue
        if [ -n "${missing[i]}" ]; then
            explicit[i]=0
            notice+="Cannot select "$'\033[32m'"${REPO_ITEM_LABELS[i]}"$'\033[0m'": missing dependency "$'\033[32m'"${missing[i]}"$'\033[0m'". "
            continue
        fi
        for dependency in ${requirements[i]}; do selected[dependency]=1; done
    done
}

picker_deselect_dependency() {
    local target="$1" root
    for ((root=0; root<${#explicit[@]}; root++)); do
        if [ "${explicit[root]}" -eq 1 ] && [[ "${requirements[root]}" = *" $target "* ]]; then
            explicit[root]=0
            [ "$root" -eq "$target" ] || notice+="Also deselected "$'\033[32m'"${REPO_ITEM_LABELS[root]}"$'\033[0m'". "
        fi
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
    local group_word=repository group_list=repositories group_heading=Repository
    if [ "$page" -eq 9 ]; then group_word=source; group_list=sources; group_heading=Source; fi
    local dependency_mode="${4:-0}" notice='' reasons explicit=() requirements=() missing=() before=() touched=()
    for ((i=0; i<${#REPO_ITEM_LABELS[@]}; i++)); do
        group="${REPO_ITEM_GROUPS[i]}"; found=-1
        for ((j=0; j<${#groups[@]}; j++)); do [ "${groups[j]}" != "$group" ] || { found="$j"; break; }; done
        if [ "$found" -eq -1 ]; then found="${#groups[@]}"; groups+=("$group"); fi
        item_groups+=("$found"); selected+=(0)
    done
    for i in "${REPO_SELECTED[@]+"${REPO_SELECTED[@]}"}"; do selected[i]=1; done
    if [ "$dependency_mode" -eq 1 ]; then
        explicit=("${REPO_EXPLICIT[@]}")
        picker_dependency_graph
        picker_resolve_dependencies
    fi
    cursor="${MENU_CURSORS[page]:-0}"
    while :; do
        REPO_SELECTED=()
        for ((i=0; i<${#selected[@]}; i++)); do [ "${selected[i]}" -eq 0 ] || REPO_SELECTED+=("$i"); done
        if [ "$dependency_mode" -eq 1 ]; then REPO_EXPLICIT=("${explicit[@]}"); fi
        printf '\033[H\033[2J%s\n' "$title"
        [ -z "$notice" ] || printf '%s\n' "$notice"
        if [ "$child" -lt 0 ]; then
            printf 'Up/Down: move | Space: select %s | Enter: open / Continue | a: all | n: none | b/Esc: back | q: exit\n\n' "$group_word"
            total=$((${#groups[@]} + 1)); MENU_CURSORS[page]="$cursor"
        else
            printf '%s: %s\nUp/Down: move | Space: select | a: all | n: none | Enter/b/Esc: %s | q: exit\n\n' "$group_heading" "${groups[child]}" "$group_list"
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
                if [ "$dependency_mode" -eq 1 ] && [ "${selected[i]}" -eq 1 ] && [ "${explicit[i]}" -eq 0 ]; then
                    reasons=''
                    for ((j=0; j<${#selected[@]}; j++)); do
                        if [ "${explicit[j]}" -eq 1 ] && [[ "${requirements[j]}" = *" $i "* ]]; then
                            reasons+="${reasons:+, }"$'\033[32m'"${REPO_ITEM_LABELS[j]}"$'\033[0m'
                        fi
                    done
                    printf '      [dependency: %s]\n' "$reasons"
                fi
            fi
        done
        printf '\nItem %s/%s\n' "$((cursor + 1))" "$total"
        read_key || return 1
        case "$KEY" in
            $'\e[A' | $'\eOA') cursor=$(((cursor + total - 1) % total)) ;;
            $'\e[B' | $'\eOB') cursor=$(((cursor + 1) % total)) ;;
            ' ' | a | n)
                before=("${selected[@]}"); touched=(); notice=''
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
                        if [ "$KEY" != ' ' ] || [ "${item_groups[i]}" -eq "$cursor" ]; then selected[i]="$found"; touched+=("$i"); fi
                    done
                elif [ "$KEY" = ' ' ]; then i="${children[cursor]}"; selected[i]=$((1 - selected[i])); touched+=("$i");
                else
                    found=1; [ "$KEY" != n ] || found=0
                    for i in "${children[@]}"; do selected[i]="$found"; touched+=("$i"); done
                fi
                if [ "$dependency_mode" -eq 1 ]; then
                    # All also promotes already checked dependencies to explicit.
                    for i in "${touched[@]}"; do
                        if [ "${selected[i]}" -eq 1 ]; then explicit[i]=1;
                        else picker_deselect_dependency "$i"; fi
                    done
                    picker_resolve_dependencies
                    for ((i=0; i<${#selected[@]}; i++)); do
                        if [ "${before[i]}" -eq 1 ] && [ "${selected[i]}" -eq 0 ] && [ "${REPO_ITEM_GROUPS[i]}" = mattpocock/skills ]; then
                            notice+="Deselected "$'\033[32m'"${REPO_ITEM_LABELS[i]}"$'\033[0m'". "
                        fi
                    done
                fi ;;
            '')
                if [ "$child" -ge 0 ]; then child=-1; cursor="${MENU_CURSORS[page]}";
                elif [ "$cursor" -eq "${#groups[@]}" ]; then return 0;
                else child="$cursor"; key_page=$((100 + page * 100 + child)); cursor="${MENU_CURSORS[key_page]:-0}"; fi ;;
            b | B | $'\e')
                if [ "$child" -ge 0 ]; then child=-1; cursor="${MENU_CURSORS[page]}"; else return 2; fi ;;
            q | Q) return 1 ;;
        esac
    done
}

# The private manifest binds selection IDs to scanned paths and content hashes.
# No source checkout or network access is required to remove installed content.
removal_inventory() {
    node - "$HOME" "$PROJECT_TARGET" "$REMOVE_SCOPE" "$REMOVAL_TEMP/inventory.json" "$(pi_rule_path)" "$@" <<'JS'
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const cp = require('child_process');
const [home, project, scope, manifest, piRulePath, action, ...args] = process.argv.slice(2);
const red = s => `\x1b[31m${s}\x1b[0m`;
const cyan = s => `\x1b[36m${s}\x1b[0m`;
const yellow = s => `\x1b[33m${s}\x1b[0m`;
process.on('uncaughtException', error => { console.error(red(error.message)); process.exitCode = 1; });
const display = s => JSON.stringify(String(s)).slice(1, -1);
const quote = s => "'" + s.replace(/'/g, "'\\''") + "'";
const stat = p => { try { return fs.lstatSync(p); } catch (e) { if (e.code !== 'ENOENT') throw e; } };
if (!home || !path.isAbsolute(home) || path.resolve(home) === '/') throw Error('Unsafe HOME');
if (!['global', 'project'].includes(scope)) throw Error('Invalid removal scope');
const root = scope === 'project' ? project : home;
if (!root || !path.isAbsolute(root) || path.resolve(root) === '/') throw Error('Unsafe removal root');
const rootInfo = fs.lstatSync(root);
if (!rootInfo.isDirectory() || rootInfo.isSymbolicLink()) throw Error('Unsafe removal root directory');
const full = relative => {
    const value = path.resolve(root, relative);
    if (!value.startsWith(path.resolve(root) + path.sep)) throw Error('Path outside removal root');
    return value;
};
function parents(relative) {
    let current = path.dirname(full(relative));
    const result = [];
    while (current !== path.resolve(root)) {
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
const lockPath = scope === 'project' ? 'skills-lock.json' : '.agents/.skill-lock.json';
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
function ruleTitle(text) {
    return text.match(/^#{1,6}[ \t]+(.+?)[ \t]*\r?$/m)?.[1] || null;
}
function ruleGroups(entries) {
    const groups = new Map();
    for (const e of entries.filter(e => e.kind === 'rules')) {
        const key = e.ruleName ? `rule:${e.ruleName}` : `entry:${e.id}`;
        if (!groups.has(key)) groups.set(key, {name: e.ruleName || e.name, entries: []});
        groups.get(key).entries.push(e);
    }
    return [...groups.values()];
}
const agentName = agent => ({codex: 'Codex', claude: 'Claude', pi: 'Pi'}[agent]);
const ruleLabel = group => `${display(group.name)} ${group.entries.map(e => `[${agentName(e.agent)}:${e.type}]`).join(' ')}`;
const targetLabel = e => display(full(e.relative)) + (e.type === 'block' ? ` # ${display(e.name)}` : '');
function linkDestination(p) {
    const destination = path.resolve(path.dirname(p), fs.readlinkSync(p));
    if (scope !== 'global') return destination;
    // Keep the named Codex entry even when it is itself a link to another location.
    if (path.dirname(destination) === full('.agents/skills')) return destination;
    try { return fs.realpathSync(p); }
    catch (error) {
        if (!['ENOENT', 'ENOTDIR', 'ELOOP'].includes(error.code)) throw error;
        return destination;
    }
}
function skillGroups(entries) {
    const groups = new Map();
    for (const e of entries.filter(e => e.kind === 'skills')) {
        const name = e.skillName || e.name;
        const key = e.group !== 'Unknown / local' ? JSON.stringify([e.group, name]) : e.skillSource || e.relative;
        if (!groups.has(key)) groups.set(key, {name, group: e.group, entries: []});
        groups.get(key).entries.push(e);
    }
    return [...groups.values()];
}
function scan(codex, claude, rules, skills, pi = false) {
    const piRelative = pi && rules && scope === 'global' ? path.relative(root, path.resolve(piRulePath)) : null;
    if (piRelative !== null) full(piRelative); // Preserve the HOME boundary for custom Pi paths.
    for (const directory of [...(skills && (codex || claude) ? ['.agents'] : []), ...(claude ? ['.claude'] : []), ...(rules && codex && scope === 'global' ? ['.codex'] : [])]) {
        if (stat(full(directory))?.isSymbolicLink()) throw Error(`Refusing symlinked directory: ${full(directory)}`);
    }
    const entries = [], lock = skills && (codex || claude) ? readLock() : {valid: true};
    const add = entry => {
        entries.push({...entry, id: entries.length, snapshot: fingerprint(entry.relative), parents: parents(entry.relative)});
    };
    for (const agent of ['codex', 'claude', 'pi']) {
        if (!({codex, claude, pi}[agent]) || (agent === 'pi' && scope !== 'global')) continue;
        if (rules) {
            const relative = agent === 'codex' ? (scope === 'project' ? 'AGENTS.md' : '.codex/AGENTS.md') :
                agent === 'pi' ? piRelative : (scope === 'global' ? '.claude/CLAUDE.md' : null);
            const info = relative ? stat(full(relative)) : null;
            if (info?.isSymbolicLink()) add({kind: 'rules', type: 'link', agent, relative, name: path.basename(relative)});
            else if (info?.isFile()) {
                parents(relative);
                const text = fs.readFileSync(full(relative), 'latin1');
                for (const block of markers(text)) {
                    add({kind: 'rules', type: 'block', agent, relative, name: block.name,
                        ruleTitle: ruleTitle(text.slice(block.start, block.end))});
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
        if (skills && agent !== 'pi') {
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
                    let skillName = name, skillSource = relative;
                    if (agent === 'claude' && info.isSymbolicLink()) {
                        const destination = linkDestination(full(relative));
                        if (path.dirname(destination) === full('.agents/skills')) {
                            skillName = path.basename(destination);
                            skillSource = path.join('.agents/skills', skillName);
                            record = lock.data?.skills?.[skillName];
                        }
                    }
                    add({kind: 'skills', type: info.isSymbolicLink() ? 'link' : info.isDirectory() ? 'directory' : 'file',
                         agent, relative, name, skillName, skillSource, group: repository(record)});
                }
            }
        }
    }
    const blocks = entries.filter(e => e.kind === 'rules' && e.type === 'block');
    for (const e of blocks) e.ruleName = e.name;
    for (const e of entries.filter(e => e.kind === 'rules' && e.type === 'file')) {
        // Claude files have no managed marker. Require both the installer's exact
        // top-level filename and a matching heading before linking to a block.
        const title = ruleTitle(fs.readFileSync(full(e.relative), 'latin1'));
        const block = blocks.find(b => e.name === `rules/${b.name}.md` && title && title === b.ruleTitle);
        if (block) e.ruleName = block.name;
    }
    if (skills && !lock.valid) console.error(yellow('Skill lock is unreadable; skills are grouped under Unknown / local. Codex deletion requires a valid lock.'));
    return {scope, root: path.resolve(root), rootIdentity: [rootInfo.dev, rootInfo.ino],
        entries, selected: [], piRulePath: piRelative === null ? null : path.resolve(piRulePath), lockSnapshot: skills && (codex || claude) ? fingerprint(lockPath) : null};
}
function selected(data) {
    const ids = new Set(data.selected);
    return data.entries.filter(e => ids.has(e.id));
}
function verify(data, items) {
    const info = fs.lstatSync(root);
    if (!info.isDirectory() || info.isSymbolicLink() ||
        JSON.stringify(data.rootIdentity) !== JSON.stringify([info.dev, info.ino])) {
        throw Error('Removal root changed; rescan and select again');
    }
    for (const entry of items) {
        if (JSON.stringify(parents(entry.relative)) !== JSON.stringify(entry.parents) || fingerprint(entry.relative) !== entry.snapshot) {
            throw Error(`Content changed; rescan and select again: ${full(entry.relative)}`);
        }
    }
    if (items.some(e => e.kind === 'skills') && fingerprint(lockPath) !== data.lockSnapshot) throw Error('Skill lock changed; rescan and select again');
}
function relatedLinks(items) {
    const removed = new Set(items.filter(e => e.type !== 'block').map(e => full(e.relative)));
    const sources = items.filter(e => e.kind === 'skills' && e.agent === 'codex').map(e => full(e.relative));
    const links = [];
    if (!sources.length) return links;
    function walk(p) {
        const info = stat(p);
        if (!info) return;
        if (info.isSymbolicLink()) {
            const destination = linkDestination(p);
            if (!removed.has(p) && sources.some(source => destination === source || destination.startsWith(source + path.sep) || source.startsWith(destination + path.sep))) {
                links.push({relative: path.relative(root, p), destination,
                    shared: sources.some(source => source.startsWith(destination + path.sep))});
            }
        } else if (info.isDirectory()) for (const name of fs.readdirSync(p)) walk(path.join(p, name));
    }
    // Do not traverse a symlinked agent parent just to produce a warning.
    if (!stat(full('.claude'))?.isSymbolicLink()) walk(full('.claude/skills'));
    return links;
}
function warnings(items) {
    for (const link of relatedLinks(items)) {
        if (scope === 'global' && link.shared) console.log(yellow(`WARNING: Shared Claude skills directory link will be kept: ${display(full(link.relative))} -> ${display(link.destination)}; removing the selected skills also affects Claude.`));
        else console.log(red(`WARNING: Claude link will be kept: ${display(full(link.relative))} -> ${display(link.destination)}; it will become broken if its target is removed.`));
    }
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
    if (data.scope !== scope || data.root !== path.resolve(root) ||
        JSON.stringify(data.rootIdentity) !== JSON.stringify([rootInfo.dev, rootInfo.ino])) {
        throw Error('Removal scope or root changed; rescan and select again');
    }
    if (data.piRulePath && data.piRulePath !== path.resolve(piRulePath)) throw Error('Pi rule path changed; rescan and select again');
    if (action === 'rows') {
        for (const group of ruleGroups(data.entries)) console.log([group.entries.map(e => e.id).join(','), 'rules', '-', ruleLabel(group)].join('\t'));
        if (scope === 'global') {
            for (const group of skillGroups(data.entries)) {
                const label = `${display(group.name)} ${group.entries.map(e => `[${agentName(e.agent)}:${e.type}]`).join(' ')}`;
                console.log([group.entries.map(e => e.id).join(','), 'skills', display(group.group || '-'), label].join('\t'));
            }
        } else for (const e of data.entries.filter(e => e.kind === 'skills')) console.log([e.id, e.kind, display(e.group || '-'), `${agentName(e.agent)} / ${display(e.name)} [${e.type}]`].join('\t'));
    } else if (action === 'select') {
        data.entries = data.entries.filter(e => !e.external);
        data.externalLinks = [];
        data.selected = [...new Set(args.flatMap(value => value.split(',').map(Number)))];
        if (data.selected.some(id => !data.entries.some(e => e.id === id))) throw Error('Invalid removal selection');
        fs.writeFileSync(manifest, JSON.stringify(data));
    } else {
        const items = selected(data);
        if (!items.length) { console.log('No removal targets selected.'); process.exit(0); }
        verify(data, items);
        if (action === 'linked-skills') {
            data.externalLinks = scope === 'global' ? relatedLinks(items).filter(link => !link.shared &&
                link.relative !== '.claude/skills/.system' && !link.relative.startsWith('.claude/skills/.system/')).map(link => ({
                kind: 'skills', type: 'link', agent: 'claude', relative: link.relative,
                name: path.relative('.claude/skills', link.relative), external: true,
                snapshot: fingerprint(link.relative), parents: parents(link.relative)
            })) : [];
            for (const e of data.externalLinks) console.log(`  ${targetLabel(e)} -> ${display(fs.readlinkSync(full(e.relative)))}`);
            fs.writeFileSync(manifest, JSON.stringify(data));
        } else if (action === 'include-links') {
            const links = data.externalLinks || [];
            verify(data, links);
            for (const e of links) {
                e.id = data.entries.length;
                data.entries.push(e);
                data.selected.push(e.id);
            }
            data.externalLinks = [];
            fs.writeFileSync(manifest, JSON.stringify(data));
        } else if (action === 'preview') {
            console.log(`Removal scope: ${scope} (${display(root)})`);
            console.log('Removal targets:');
            for (const group of ruleGroups(items)) {
                console.log(`  ${ruleLabel(group)}`);
                for (const e of group.entries) console.log(`    [${agentName(e.agent)}:${e.type}] ${red(targetLabel(e))}`);
            }
            for (const e of items.filter(e => e.kind === 'skills')) console.log(`  ${e.agent} / ${display(e.name)} [${e.type}]: ${red(targetLabel(e))}`);
            const lock = readLock();
            const names = items.filter(e => e.kind === 'skills' && e.agent === 'codex' && lock.valid && Object.hasOwn(lock.data.skills || {}, e.name)).map(e => e.name);
            if (names.length) console.log(`  Remove lock entries (${names.map(display).join(', ')}): ${red(display(full(lockPath)))}`);
            warnings(items);
        } else if (action === 'remove') {
            const backupChoice = args[0] ?? '0';
            if (args.length > 1 || !['0', '1'].includes(backupChoice)) throw Error('Invalid backup choice; nothing removed');
            const createBackup = backupChoice === '1';
            const lock = readLock();
            const codexSkills = items.filter(e => e.kind === 'skills' && e.agent === 'codex');
            if (codexSkills.length && !lock.valid) throw Error('Invalid skill lock; nothing removed');
            const updatesLock = codexSkills.some(e => Object.hasOwn(lock.data.skills || {}, e.name));
            if (createBackup) {
                const targets = [...new Set([...items.map(e => e.relative), ...(updatesLock ? [lockPath] : [])])];
                const prefix = items.some(e => e.kind === 'rules') ? '.agent-rules-backup-' : '.agent-skills-backup-';
                const backupDir = fs.mkdtempSync(path.join(home, prefix));
                fs.chmodSync(backupDir, 0o700);
                const backup = path.join(backupDir, 'removal.tar');
                const result = cp.spawnSync('tar', ['-cf', backup, '-C', root, '--', ...targets], {stdio: 'inherit'});
                if (result.status !== 0) throw Error('Backup failed; nothing removed');
                console.log(cyan(`Backup: ${display(backup)}`));
                console.log(cyan(`Restore: tar -xf ${quote(backup)} -C ${quote(root)}`));
            } else console.log('No backup will be created.');
            verify(data, items);
            let succeeded = 0, failed = 0;
            const removedSkills = [], handled = new Set(), outcomes = new Map();
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
                        outcomes.set(e.id, null);
                        if (e.kind === 'skills') console.log(`  OK removed ${e.agent} / ${display(e.name)}: ${red(targetLabel(e))}`);
                        if (e.kind === 'skills' && e.agent === 'codex') removedSkills.push(e.name);
                    }
                } catch (error) {
                    failed += batch.length;
                    for (const e of batch) {
                        outcomes.set(e.id, error.message);
                        if (e.kind === 'skills') console.error(red(`  FAIL ${e.agent} / ${display(e.name)}: ${display(full(e.relative))}: ${error.message}`));
                    }
                }
            }
            const groups = ruleGroups(items);
            for (const group of groups) {
                const errors = group.entries.filter(e => outcomes.get(e.id) !== null);
                const status = errors.length === 0 ? 'OK removed' : errors.length === group.entries.length ? 'FAIL' : 'PARTIAL';
                console.log(`  ${status} ${ruleLabel(group)}`);
                for (const e of group.entries) {
                    const error = outcomes.get(e.id);
                    const detail = `    ${error === null ? 'OK' : 'FAIL'} [${agentName(e.agent)}:${e.type}] ${targetLabel(e)}`;
                    if (error === null) console.log(red(detail));
                    else console.error(red(`${detail}: ${display(error)}`));
                }
            }
            if (groups.length) {
                const complete = groups.filter(g => g.entries.every(e => outcomes.get(e.id) === null)).length;
                const partial = groups.filter(g => g.entries.some(e => outcomes.get(e.id) === null) && g.entries.some(e => outcomes.get(e.id) !== null)).length;
                console.log(`Rules: ${complete} removed, ${partial} partial, ${groups.length - complete - partial} failed`);
            }
            if (updatesLock && removedSkills.length) {
                try {
                    if (fingerprint(lockPath) !== data.lockSnapshot) throw Error('Skill lock changed during deletion; ' + (createBackup ? 'restore from backup if needed' : 'no recovery backup was created'));
                    for (const name of removedSkills) delete lock.data.skills[name];
                    atomicWrite(lockPath, JSON.stringify(lock.data, null, 2) + '\n');
                    console.log(`Updated lock: ${red(display(full(lockPath)))}`);
                } catch (error) { failed++; console.error(red(`  FAIL lock update: ${error.message}`)); }
            }
            console.log(`\nResults: ${succeeded} succeeded, ${failed} failed${groups.length ? ' (installation targets' + (updatesLock ? ' / lock update' : '') + ')' : ''}`);
            if (items.some(e => e.kind === 'skills')) console.log('Remove skills for the selected agents; preserve .system entries.');
            process.exitCode = failed ? 1 : 0;
        } else throw Error('Unknown removal action');
    }
}
JS
}

scan_removal_inventory() {
    local rows id kind group label
    require_node || return 1
    if [ -n "$REMOVAL_TEMP" ]; then rm -rf -- "$REMOVAL_TEMP"; fi
    REMOVAL_TEMP="$(mktemp -d)" || return 1
    trap cleanup_setup_resources EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    removal_inventory scan "$REMOVE_CODEX" "$REMOVE_CLAUDE" "$REMOVE_RULES" "$REMOVE_SKILLS" "$REMOVE_PI" || return 1
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
    local i links ids=()
    for i in "${REMOVAL_RULE_SELECTION[@]+"${REMOVAL_RULE_SELECTION[@]}"}"; do ids+=("${REMOVAL_RULE_IDS[i]}"); done
    for i in "${REMOVAL_SKILL_SELECTION[@]+"${REMOVAL_SKILL_SELECTION[@]}"}"; do ids+=("${REMOVAL_SKILL_IDS[i]}"); done
    if [ "${#ids[@]}" -eq 0 ]; then printf 'No removal targets selected.\n'; return 2; fi
    removal_inventory select "${ids[@]}" || return 1
    links=$(removal_inventory linked-skills) || return 1
    if [ -n "$links" ]; then
        printf 'Claude links referencing the selected skills:\n%s\n' "$links"
        while :; do
            printf 'Also remove these Claude links? [y/N] (b/Esc: back | q: exit): '
            read_back_answer || return 4
            case "$REPLY" in
                y | Y) removal_inventory include-links || return 1; break ;;
                n | N | '') break ;;
                b | B) return 3 ;;
                q | Q) return 4 ;;
                *) printf 'Please enter y or n (b/Esc: back | q: exit).\n' ;;
            esac
        done
    fi
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
    require_node || return 1
    names=$(list_setup_backups)
    if [ -z "$names" ]; then printf 'No setup backups found.\n'; return 0; fi
    printf '\nRemove all setup backup directories listed below:\n'
    while IFS= read -r name; do
        backups+=("$name")
        printf '  \033[31m%s/%s\033[0m\n' "$HOME" "$name"
    done <<<"$names"
    printf 'This permanently deletes these backups and their restore data. No new backup is created.\n'
    printf 'Confirm removal? [Y/n]: '
    IFS= read -r answer || return 0
    case "$answer" in y | Y | '') ;; *) return 0 ;; esac
    run_item 'Remove all backups' remove_setup_backups "${backups[@]}"
    print_summary
}

preflight() {
    local item
    for item in "$@"; do
        case "$item" in
            0) require_command curl || return 1 ;;
            1) require_command curl || return 1; require_node || return 1 ;;
            2) : ;;
            3) require_node || return 1 ;;
            5) require_node || return 1; require_command npm || return 1 ;;
            4) require_command curl || return 1; require_node || return 1; require_command npx || return 1 ;;
        esac
    done
}

execute_plan() {
    local item other source previous handled index source_scope before package
    local completed_sources=() names=()
    for item in "${AGENT_ITEMS[@]+"${AGENT_ITEMS[@]}"}"; do
        case "$item" in
            0) run_item 'Codex CLI' install_codex ;;
            1)
                before=${#FAILED[@]}
                run_item 'Claude Code CLI' install_claude
                if [ "${#FAILED[@]}" -eq "$before" ]; then
                    if resolve_resource scripts/statusline.sh; then
                        run_item 'Claude statusline' install_statusline
                    else FAILED+=('Claude statusline: resource unavailable'); fi
                else FAILED+=('Claude statusline: skipped because Claude installation failed'); fi ;;
            2)
                for ((index=0; index<${#SELECTED_RULES[@]}; index++)); do
                    other="${SELECTED_RULES[index]}"
                    source_scope="${SELECTED_RULE_SOURCES[index]:-$RULE_SCOPE}"
                    if ! resolve_rule_source "$source_scope"; then FAILED+=("$source_scope rule: $other (resource unavailable)"); continue; fi
                    run_item "$RULE_SCOPE rule: $other ($RULE_TARGETS)" apply_rule "$other" "$RULE_SCOPE" "$RULE_TARGETS" install "$source_scope"
                done ;;
            5)
                before=${#FAILED[@]}
                run_item 'Pi CLI' install_pi
                if [ "${#FAILED[@]}" -eq "$before" ]; then
                    for package in "${PI_PACKAGES[@]}"; do run_item "$package" pi install "$package"; done
                else
                    for package in "${PI_PACKAGES[@]}"; do FAILED+=("$package: skipped because Pi installation failed"); done
                fi ;;
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
    local i destination index source_scope rule_targets
    local labels=('Codex CLI' 'Claude Code CLI' 'Rules' 'Claude statusline' 'Skills' 'Pi CLI')
    printf '\nExecution plan:\n'
    for i in "${AGENT_ITEMS[@]+"${AGENT_ITEMS[@]}"}"; do
        [ "$i" -eq 2 ] || printf '  \033[32m%s\033[0m\n' "${labels[i]}"
        if [ "$i" -eq 1 ]; then printf '    Claude statusline (bundled)\n'; fi
        if [ "$i" -eq 5 ]; then printf '    %s (bundled)\n' "${PI_PACKAGES[@]}"; fi
    done
    if [ "${#SELECTED_RULES[@]}" -gt 0 ]; then
        for ((index=0; index<${#SELECTED_RULES[@]}; index++)); do
            i="${SELECTED_RULES[index]}"
            source_scope="${SELECTED_RULE_SOURCES[index]:-$RULE_SCOPE}"
            resolve_rule_source "$source_scope" || return 1
            if [ "$source_scope" = waza ]; then
                printf '  Rule source: GitHub tw93/Waza @ main -> %s (rules/%s.md)\n' "$WAZA_RULES_COMMIT" "${i#waza-}"
            elif [ -n "$RESOURCE_TEMP" ] && [[ "$RESOURCE_PATH" = "$RESOURCE_TEMP/"* ]]; then
                printf '  Rule source: GitHub gwyntoria/skills @ main (rules/%s.md)\n' "$i"
            else
                printf '  Rule source: %s/%s.md\n' "$RESOURCE_PATH" "$i"
            fi
            if [ "$RULE_SCOPE" = project ]; then
                printf '  \033[32mproject / %s -> AGENTS.md\033[0m\n' "$i"
                printf '    \033[32m%s/AGENTS.md\033[0m\n' "$PROJECT_TARGET"
            else
                printf '  \033[32m%s / %s -> %s\033[0m\n' "$RULE_SCOPE" "$i" "$RULE_TARGETS"
                rule_targets="$RULE_TARGETS"
                if [ "$rule_targets" = both ]; then rule_targets='codex claude'; fi
                for destination in $rule_targets; do
                    case "$destination" in
                        codex) printf '    \033[32m%s/.codex/AGENTS.md\033[0m\n' "$HOME" ;;
                        pi) printf '    \033[32m%s\033[0m\n' "$(pi_rule_path)" ;;
                        claude)
                            destination="$HOME/.claude/rules/$i.md"
                            if [ "$i" = agent-behavior ]; then destination="$HOME/.claude/CLAUDE.md"; fi
                            printf '    \033[32m%s\033[0m\n' "$destination" ;;
                    esac
                done
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
    local page="${1:-main}" i task menu_status removal_scanned=0 removal_signature="" signature command_action removal_backup=0
    local session_status=0 INTERACTIVE_RESULT=0 show_summary=0
    local repo_labels=() repo_group repo_url
    local rule_labels=() rule_names=() rule_sources=() source_scope selected_rule
    local task_labels=('Rules' 'Skills' 'Agent')
    local tasks=() agent_requested=0
    [ "$page" != agent_choices ] || agent_requested=1
    while :; do
        case "$page" in
            main)
                choose_items 0 'Agent setup' 0 0 'Install / Update' 'Remove' 'Remove all backups' 'Install / Update this command' 'Exit' || return "$session_status"
                case "${MENU_SELECTED[0]}" in
                    0) page=tasks ;;
                    1) removal_scanned=0; page=remove_categories ;;
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
                printf 'Continue? [Y/n] (b/Esc: back | q: exit) '
                read_back_answer || return "$session_status"
                case "$REPLY" in
                    y | Y | '')
                        run_item "$command_action this command" install_setup_command
                        print_summary || session_status=1
                        page=complete ;;
                    b | B) page=main ;;
                    q | Q) return "$session_status" ;;
                    *) printf 'Cancelled.\n'; page=complete ;;
                esac ;;
            remove_categories)
                choose_items 5 'Remove: choose content' 1 0 Rules Skills || {
                    [ "$?" -eq 2 ] || return "$session_status"
                    page=main; continue
                }
                [ "${#MENU_SELECTED[@]}" -gt 0 ] || { printf 'No content selected; cancelled.\n'; page=complete; continue; }
                REMOVE_RULES=0; REMOVE_SKILLS=0
                for i in "${MENU_SELECTED[@]}"; do
                    if [ "$i" -eq 0 ]; then REMOVE_RULES=1; else REMOVE_SKILLS=1; fi
                done
                page=remove_scope ;;
            remove_scope)
                choose_items 14 'Remove: choose scope' 0 0 Global Project || {
                    [ "$?" -eq 2 ] || return "$session_status"
                    page=remove_categories; continue
                }
                if [ "${MENU_SELECTED[0]}" -eq 0 ]; then REMOVE_SCOPE=global; else REMOVE_SCOPE=project; fi
                page=remove_agents ;;
            remove_agents)
                local remove_agent_labels=(Codex 'Claude Code') remove_agent_defaults='1 1'
                if [ "$REMOVE_SCOPE" = global ]; then
                    remove_agent_labels+=('Pi (rules only)')
                    remove_agent_defaults+=' 0'
                elif [ "${MENU_CURSORS[4]:-0}" -gt 1 ]; then
                    MENU_CURSORS[4]=1
                fi
                choose_items 4 'Remove: choose agents' 1 "$remove_agent_defaults" "${remove_agent_labels[@]}" || {
                    [ "$?" -eq 2 ] || return "$session_status"
                    page=remove_scope; continue
                }
                [ "${#MENU_SELECTED[@]}" -gt 0 ] || { printf 'No agents selected; cancelled.\n'; page=complete; continue; }
                REMOVE_CODEX=0; REMOVE_CLAUDE=0; REMOVE_PI=0
                for i in "${MENU_SELECTED[@]}"; do
                    case "$i" in 0) REMOVE_CODEX=1 ;; 1) REMOVE_CLAUDE=1 ;; 2) REMOVE_PI=1 ;; esac
                done
                signature="$REMOVE_SCOPE/$PROJECT_TARGET/$REMOVE_CODEX/$REMOVE_CLAUDE/$REMOVE_PI/$REMOVE_RULES/$REMOVE_SKILLS/$(pi_rule_path)"
                if [ "$removal_scanned" -eq 0 ] || [ "$signature" != "$removal_signature" ]; then
                    if ! scan_removal_inventory; then FAILED+=('Installed content scan failed'); show_summary=1; page=complete; continue; fi
                    removal_signature="$signature"; removal_scanned=1
                fi
                page=remove_rules ;;
            remove_rules)
                if [ "$REMOVE_RULES" -eq 1 ] && [ "${#REMOVAL_RULE_IDS[@]}" -gt 0 ]; then
                    choose_items 12 'Choose installed rules to remove' 1 0 "${REMOVAL_RULE_LABELS[@]}" || {
                        [ "$?" -eq 2 ] || return "$session_status"
                        page=remove_agents; continue
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
                        if [ "$REMOVE_RULES" -eq 1 ] && [ "${#REMOVAL_RULE_IDS[@]}" -gt 0 ]; then page=remove_rules; else page=remove_agents; fi
                        continue
                    }
                    REMOVAL_SKILL_SELECTION=("${REPO_SELECTED[@]+"${REPO_SELECTED[@]}"}")
                fi
                preview_selected_removal || {
                    menu_status=$?
                    if [ "$menu_status" -eq 3 ]; then continue; fi
                    if [ "$menu_status" -eq 4 ]; then return "$session_status"; fi
                    if [ "$menu_status" -ne 2 ]; then FAILED+=('Removal preview failed; rescan required'); show_summary=1; fi
                    page=complete; continue
                }
                page=remove_backup ;;
            remove_backup)
                removal_backup=0
                printf 'Create backup? [y/N] (b/Esc: back | q: exit): '
                read_back_answer || return "$session_status"
                case "$REPLY" in
                    y | Y) removal_backup=1; page=remove_confirm ;;
                    n | N | '') page=remove_confirm ;;
                    q | Q) return "$session_status" ;;
                    b | B)
                        if [ "$REMOVE_SKILLS" -eq 1 ] && [ "${#REMOVAL_SKILL_IDS[@]}" -gt 0 ]; then page=remove_skills;
                        elif [ "$REMOVE_RULES" -eq 1 ] && [ "${#REMOVAL_RULE_IDS[@]}" -gt 0 ]; then page=remove_rules;
                        else page=remove_agents; fi
                        continue ;;
                    *) printf 'Please enter y or n (b/Esc: back | q: exit).\n' ;;
                esac ;;
            remove_confirm)
                if [ "$removal_backup" -eq 1 ]; then
                    printf 'All selected content will be backed up before removal.\n'
                else
                    printf 'No backup will be created.\n'
                fi
                printf 'Confirm removal? [Y/n] (b/Esc: back | q: exit): '
                read_back_answer || return "$session_status"
                case "$REPLY" in
                    y | Y | '') run_interactive_task removal_inventory remove "$removal_backup" ;;
                    q | Q) return "$session_status" ;;
                    b | B) page=remove_backup; continue ;;
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
                AGENT_ITEMS=(); INSTALL_SKILLS=0; agent_requested=0
                for task in "${tasks[@]}"; do
                    case "$task" in
                    0) AGENT_ITEMS+=(2) ;;
                    1) INSTALL_SKILLS=1 ;;
                    2) agent_requested=1 ;;
                    esac
                done
                if [ "$INSTALL_SKILLS" -eq 1 ] && ! preflight 4; then
                    FAILED+=('Installation preparation failed'); show_summary=1; page=complete; continue
                fi
                if [ "$agent_requested" -eq 1 ]; then page=agent_choices; else page=before_rules; fi ;;
            agent_choices)
                choose_items 12 'Choose Agents' 1 '1 1 0' Codex 'Claude Code (with statusline)' 'Pi (with three packages)' || {
                    [ "$?" -eq 2 ] || return "$session_status"
                    page=tasks; continue
                }
                # Back/re-entry replaces the previous Agent choices, preserving Rules.
                if [[ " ${AGENT_ITEMS[*]+${AGENT_ITEMS[*]}} " = *" 2 "* ]]; then AGENT_ITEMS=(2); else AGENT_ITEMS=(); fi
                for i in "${MENU_SELECTED[@]+"${MENU_SELECTED[@]}"}"; do
                    case "$i" in 0) AGENT_ITEMS+=(0) ;; 1) AGENT_ITEMS+=(1) ;; 2) AGENT_ITEMS+=(5) ;; esac
                done
                if ! preflight "${AGENT_ITEMS[@]+"${AGENT_ITEMS[@]}"}"; then
                    FAILED+=('Installation preparation failed'); show_summary=1; page=complete; continue
                fi
                if [[ " ${AGENT_ITEMS[*]+${AGENT_ITEMS[*]}} " = *" 1 "* ]] && ! resolve_resource scripts/statusline.sh; then
                    FAILED+=('Installation preparation failed'); show_summary=1; page=complete; continue
                fi
                page=before_rules ;;
            before_rules)
                if [[ " ${AGENT_ITEMS[*]+${AGENT_ITEMS[*]}} " = *" 2 "* ]]; then page=rule_choices;
                else SELECTED_RULES=(); SELECTED_RULE_SOURCES=(); page=after_rules; fi ;;
            rule_choices)
                if [ "$RULE_CATALOG_PROJECT" -eq 0 ]; then
                    if ! RULE_SCOPE=project load_rule_catalog; then
                        FAILED+=('project rule catalog unavailable'); show_summary=1; page=complete; continue
                    fi
                fi
                if ! load_waza_rules; then
                    choose_items 13 "Waza rules unavailable${WAZA_RULES_ERROR:+$'\n'$WAZA_RULES_ERROR}" 0 0 Retry 'Continue without Waza rules' Back || {
                        [ "$?" -eq 2 ] || return "$session_status"
                        page=tasks; continue
                    }
                    case "${MENU_SELECTED[0]}" in
                        0) continue ;;
                        2) page=tasks; continue ;;
                    esac
                    RULE_NAMES_WAZA=()
                fi
                rule_labels=(); rule_names=(); rule_sources=()
                for i in "${RULE_NAMES_WAZA[@]+"${RULE_NAMES_WAZA[@]}"}"; do
                    rule_labels+=("${i#waza-}"); rule_names+=("$i"); rule_sources+=(waza)
                done
                for i in "${RULE_NAMES_GLOBAL[@]+"${RULE_NAMES_GLOBAL[@]}"}"; do
                    rule_labels+=("$i"); rule_names+=("$i"); rule_sources+=(global)
                done
                for i in "${RULE_NAMES_PROJECT[@]+"${RULE_NAMES_PROJECT[@]}"}"; do
                    rule_labels+=("$i"); rule_names+=("$i"); rule_sources+=(project)
                done
                if [ "${#rule_labels[@]}" -eq 0 ]; then FAILED+=('No rules available'); show_summary=1; page=complete; continue; fi
                REPO_ITEM_LABELS=("${rule_labels[@]}"); REPO_ITEM_GROUPS=(); REPO_SELECTED=()
                for ((i=0; i<${#rule_names[@]}; i++)); do
                    source_scope="${rule_sources[i]}"
                    if [ "$source_scope" = waza ]; then REPO_ITEM_GROUPS+=(Waza); else REPO_ITEM_GROUPS+=("$source_scope"); fi
                    for ((selected_rule=0; selected_rule<${#SELECTED_RULES[@]}; selected_rule++)); do
                        if [ "${SELECTED_RULES[selected_rule]}" = "${rule_names[i]}" ] &&
                           [ "${SELECTED_RULE_SOURCES[selected_rule]}" = "$source_scope" ]; then REPO_SELECTED+=("$i"); break; fi
                    done
                done
                menu_status=0
                choose_skill_repositories 9 'Choose rules' 32 || menu_status=$?
                SELECTED_RULES=(); SELECTED_RULE_SOURCES=()
                for i in "${REPO_SELECTED[@]+"${REPO_SELECTED[@]}"}"; do
                    SELECTED_RULES+=("${rule_names[i]}"); SELECTED_RULE_SOURCES+=("${rule_sources[i]}")
                done
                if [ "$menu_status" -ne 0 ]; then
                    [ "$menu_status" -eq 2 ] || return "$session_status"
                    page=tasks; continue
                fi
                if [ "${#SELECTED_RULES[@]}" -gt 0 ]; then page=rule_scope; else page=after_rules; fi ;;
            rule_scope)
                choose_items 7 'Rules: choose scope' 0 0 Global Project || {
                    [ "$?" -eq 2 ] || return "$session_status"
                    page=rule_choices; continue
                }
                if [ "${MENU_SELECTED[0]}" -eq 0 ]; then
                    RULE_SCOPE=global; page=rule_targets
                else
                    RULE_SCOPE=project; RULE_TARGETS=codex; page=after_rules
                fi ;;
            rule_targets)
                choose_items 8 'Rules: choose agents' 1 '1 1 0' Codex 'Claude Code' Pi || {
                    [ "$?" -eq 2 ] || return "$session_status"
                    page=rule_scope; continue
                }
                [ "${#MENU_SELECTED[@]}" -gt 0 ] || { printf 'No rule targets selected; cancelled.\n'; page=complete; continue; }
                RULE_TARGETS=""
                for i in "${MENU_SELECTED[@]}"; do
                    case "$i" in 0) destination=codex ;; 1) destination=claude ;; 2) destination=pi ;; esac
                    RULE_TARGETS="${RULE_TARGETS:+$RULE_TARGETS }$destination"
                done
                page=after_rules ;;
            after_rules)
                if [ "$INSTALL_SKILLS" -eq 1 ]; then
                    page=skill_repos
                else
                    SELECTED_SKILLS=()
                    page=review
                fi ;;
            skill_repos)
                repo_labels=()
                for repo_group in "${SKILL_SOURCE_GROUPS[@]}"; do
                    repo_url="$(skill_source_url "$repo_group")"
                    repo_labels+=("${repo_url#https://github.com/}")
                done
                choose_items 6 'Choose skill repositories' 1 0 "${repo_labels[@]}" || {
                    [ "$?" -eq 2 ] || return "$session_status"
                    if [[ " ${AGENT_ITEMS[*]+${AGENT_ITEMS[*]}} " = *" 2 "* ]]; then
                        if [ "$RULE_SCOPE" = global ] && [ "${#SELECTED_RULES[@]}" -gt 0 ]; then page=rule_targets; else page=rule_scope; fi
                    else page=tasks; fi
                    continue
                }
                SELECTED_REPOS=("${MENU_SELECTED[@]+"${MENU_SELECTED[@]}"}")
                # Cached failures come back first so a later visit still reports them.
                FAILED=("${CATALOG_FAILURES[@]+"${CATALOG_FAILURES[@]}"}")
                for i in "${SELECTED_REPOS[@]+"${SELECTED_REPOS[@]}"}"; do
                    catalog_add_group "${SKILL_SOURCE_GROUPS[i]}"
                done
                [ "${#FAILED[@]}" -eq 0 ] || session_status=1
                catalog_collect_selection
                catalog_build_view
                if [ "${#REPO_ITEM_LABELS[@]}" -gt 0 ]; then page=skills; else page=review; fi ;;
            skills)
                choose_skill_repositories 2 'Install skills by repository' 32 1 || {
                    menu_status=$?
                    catalog_sync_selection
                    [ "$menu_status" -eq 2 ] || return "$session_status"
                    page=skill_repos; continue
                }
                catalog_sync_selection
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
                        if [ "$INSTALL_SKILLS" -eq 1 ]; then
                            if [ "${#SELECTED_SKILLS[@]}" -gt 0 ]; then page=targets; else page=skill_repos; fi
                        else
                            if [ "$RULE_SCOPE" = global ] && [ "${#SELECTED_RULES[@]}" -gt 0 ]; then page=rule_targets; else page=rule_scope; fi
                        fi
                        continue
                    }
                    if [ "${MENU_SELECTED[0]}" -ne 0 ]; then printf 'Cancelled.\n'; page=complete; continue; fi
                else
                    if ! print_install_plan; then FAILED+=('Cannot prepare installation plan'); show_summary=1; page=complete; continue; fi
                    if [ "$((${#AGENT_ITEMS[@]} + ${#SELECTED_SKILLS[@]}))" -eq 0 ]; then
                        show_summary=1; page=complete; continue
                    fi
                    printf 'Continue? [Y/n] (b/Esc: back | q: exit) '
                    read_back_answer || return "$session_status"
                    case "$REPLY" in
                        y | Y | '') ;;
                        q | Q) return "$session_status" ;;
                        b | B)
                            if [ "$INSTALL_SKILLS" -eq 1 ]; then
                                if [ "${#SELECTED_SKILLS[@]}" -gt 0 ]; then page=targets; else page=skill_repos; fi
                            elif [ "$agent_requested" -eq 1 ]; then page=agent_choices; else page=tasks; fi
                            continue ;;
                        *) printf 'Cancelled.\n'; page=complete; continue ;;
                    esac
                fi
                run_interactive_task execute_plan
                page=complete ;;
            complete)
                if [ "$INTERACTIVE_RESULT" -ne 0 ] || [ "${#FAILED[@]}" -gt 0 ]; then session_status=1; fi
                if [ "$show_summary" -eq 1 ]; then print_summary || true; fi
                printf '\nPress Enter to return to the main menu (Esc: back | q: exit): '
                while :; do
                    read_key || return "$session_status"
                    case "$KEY" in
                        '' | $'\e') break ;;
                        q | Q) return "$session_status" ;;
                    esac
                done
                # New actions start with defaults; Back within an action keeps selections.
                # The catalog cache survives so a later run never refetches a repository.
                SUCCEEDED=(); FAILED=(); MENU_SELECTED=(); MENU_CURSORS=(); MENU_CHOICES=(); MENU_VISITED=()
                AGENT_ITEMS=(); SELECTED_SKILLS=(); SELECTED_RULES=(); SELECTED_RULE_SOURCES=()
                SKILL_NAMES=(); SKILL_SOURCES=(); SKILL_GROUPS=(); SKILL_PICKED=(); SKILL_EXPLICIT=()
                SELECTED_REPOS=(); VIEW_SKILL_INDICES=()
                TARGET_AGENTS=(codex claude-code); RULE_TARGETS="codex claude pi"; RULE_SCOPE=global
                REMOVE_CODEX=1; REMOVE_CLAUDE=1; REMOVE_PI=1; REMOVE_RULES=0; REMOVE_SKILLS=0; REMOVE_SCOPE=global
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
        # curl | bash uses stdin for the program. Read menu input from the
        # controlling terminal only after Bash has parsed the entrypoint.
        if [ -z "$SCRIPT_PATH" ] && [ ! -t 0 ] && [ -t 1 ]; then
            if ! { exec 0</dev/tty; } 2>/dev/null; then
                printf 'Error: interactive setup requires a terminal. Use --agent, --skill, or --list.\n' >&2
                return 2
            fi
        fi
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
        AGENT_ITEMS=(0 1 5); SELECTED_RULES=(); SELECTED_RULE_SOURCES=()
        if [ -t 0 ] && [ -t 1 ]; then
            preflight "${AGENT_ITEMS[@]}" || return 1
            interactive_setup agent_choices
            return $?
        fi
        printf 'No terminal available; installing all Agents and bundled components.\n'
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

if [ -z "${BASH_SOURCE[0]:-}" ] || [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
    # stdin may now be /dev/tty; do not let Bash read it as more program text.
    exit $?
fi
