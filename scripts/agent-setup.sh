#!/usr/bin/env bash

set -eu

PROGRAM_NAME="${0##*/}"
INSTALL_AGENT=0
INSTALL_SKILLS=0
LIST_SKILLS=0

# This repository's own install content — the instruction rules and the statusline
# script — is read from the working copy, so the script must run from a clone.
# Only third-party sources below are fetched over the network.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
REPO="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
SETUP_RULE="$REPO/scripts/agent-install-rule.sh"
STATUSLINE_SOURCE="$REPO/scripts/statusline.sh"

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
  --agent     Install both CLIs, global instructions, and Claude statusline
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

# 安装 Claude Code 状态栏脚本，并把 statusLine 写进 settings.json。
# settings.json 已存在时只更新 statusLine 键，其余配置原样保留；
# 文件不是合法 JSON 就报错退出，不覆盖用户原有内容。
install_statusline() {
    local claude_dir="$HOME/.claude"
    local settings_file="$claude_dir/settings.json"

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

install_instructions() {
    bash "$SETUP_RULE" agent-behavior --target both --global --migrate-legacy </dev/null
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


remove_global_instructions() {
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
    bash "$SETUP_RULE" agent-behavior --target "$target" --global --remove </dev/null
    if [ "$REMOVE_CLAUDE_RULES" -eq 1 ]; then claude_rules remove; fi
}

confirm_instruction_removal() {
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
    [ -f "$SETUP_RULE" ] || { printf 'Missing: %s\n' "$SETUP_RULE" >&2; return 1; }
    run_item 'Remove global instructions' remove_global_instructions
    print_summary
}

preflight() {
    local item
    for item in "$@"; do
        case "$item" in
            0 | 1) require_command curl ;;
            2) require_command node; [ -f "$SETUP_RULE" ] || { printf 'Missing: %s\n' "$SETUP_RULE" >&2; exit 1; } ;;
            3) require_command node; [ -f "$STATUSLINE_SOURCE" ] || { printf 'Missing: %s\n' "$STATUSLINE_SOURCE" >&2; exit 1; } ;;
            4) require_command curl; require_command node; require_command npx ;;
        esac
    done
}

execute_plan() {
    local item other source previous handled
    local completed_sources=() names=()
    for item in "${AGENT_ITEMS[@]+"${AGENT_ITEMS[@]}"}"; do
        case "$item" in
            0) run_item 'Codex CLI' install_codex ;;
            1) run_item 'Claude Code CLI' install_claude ;;
            2) run_item 'Global instructions' install_instructions ;;
            3) run_item 'Claude statusline' install_statusline ;;
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

interactive_setup() {
    local page=main catalog_loaded=0 i task answer
    local labels=('Codex CLI' 'Claude Code CLI' 'Global instructions (both agents)' 'Claude statusline')
    local task_labels=('Skills' 'Global instructions (both agents)' 'Codex CLI' 'Claude Code CLI' 'Claude statusline')
    local task_ids=(4 2 0 1 3) skill_labels=() tasks=()
    while :; do
        case "$page" in
            main)
                choose_items 0 'Agent setup' 0 0 'Install / Update' 'Remove global skills' 'Remove global instructions' 'Exit' || return 0
                case "${MENU_SELECTED[0]}" in
                    0) page=tasks ;;
                    1) page=remove_skills ;;
                    2) page=remove_instructions ;;
                    3) return 0 ;;
                esac ;;
            remove_skills | remove_instructions)
                if [ "$page" = remove_skills ]; then i=4; answer='Remove global skills';
                else i=5; answer='Remove global instructions'; fi
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
                else confirm_instruction_removal; return $?; fi ;;
            remove_rules)
                choose_items 6 'Also remove all Claude rules directory contents?' 0 0 \
                    'Keep rules (default)' 'Remove rules directory contents' || {
                    [ "$?" -eq 2 ] || return 0
                    page=remove_instructions; continue
                }
                REMOVE_CLAUDE_RULES="${MENU_SELECTED[0]}"
                confirm_instruction_removal; return $? ;;
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
                    page=tasks; continue
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
            review) break ;;
        esac
    done
    printf '\nExecution plan:\n'
    for i in "${AGENT_ITEMS[@]+"${AGENT_ITEMS[@]}"}"; do printf '  %s\n' "${labels[i]}"; done
    for i in "${SELECTED_SKILLS[@]+"${SELECTED_SKILLS[@]}"}"; do
        printf '  %s / %s -> %s\n' "${SKILL_GROUPS[i]}" "${SKILL_NAMES[i]}" "${TARGET_AGENTS[*]}"
    done
    for i in "${FAILED[@]+"${FAILED[@]}"}"; do printf '  UNAVAILABLE: %s\n' "$i"; done
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
    if [ "$INSTALL_AGENT" -eq 1 ]; then AGENT_ITEMS=(0 1 2 3); fi
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
