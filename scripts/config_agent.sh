#!/usr/bin/env bash

set -eu

# This repository's own install content — the instruction rules and the statusline
# script — is read from the working copy, so the script must run from a clone.
# Only third-party sources below are fetched over the network.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
REPO="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
SETUP_RULE="$REPO/scripts/setup-rule.sh"
STATUSLINE_SOURCE="$REPO/scripts/statusline.sh"

WAZA_SKILLS_URL="https://github.com/tw93/waza"
KAMI_SKILLS_URL="https://github.com/tw93/kami"
MATTPOCOCK_SKILLS_URL="https://github.com/mattpocock/skills"
MATTPOCOCK_ENGINEERING_URL="$MATTPOCOCK_SKILLS_URL/tree/main/skills/engineering"
MATTPOCOCK_PRODUCTIVITY_URL="$MATTPOCOCK_SKILLS_URL/tree/main/skills/productivity"
HUMANLAYER_SKILLS_URL="https://github.com/humanlayer/skills"
UNWANTED_AGENT_SKILLS=()
PI_EXTENSIONS=(
    "npm:pi-web-access"
)

log() {
    printf '\n\033[1;34m==> %s\033[0m\n' "$1"
}

success() {
    printf '\033[1;32m✓ %s\033[0m\n' "$1"
}

require_command() {
    command_name="$1"

    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'Error: required command not found: %s\n' "$command_name" >&2
        exit 1
    fi
}

install_agent_skills() {
    local source_url="$1"
    shift

    npx skills add "$source_url" \
        "$@" \
        --agent codex claude-code \
        --global \
        --yes
}

remove_installed_agent_skills() {
    local agents_dir
    local skills_dir
    local lock_file
    local claude_skills_dir

    if [ -z "${HOME:-}" ] || [ "$HOME" = "/" ]; then
        printf '%s\n' "Error: HOME does not identify a safe user directory." >&2
        exit 1
    fi

    case "$HOME" in
    /*) ;;
    *)
        printf '%s\n' "Error: HOME must be an absolute path." >&2
        exit 1
        ;;
    esac

    agents_dir="$HOME/.agents"
    skills_dir="$agents_dir/skills"
    lock_file="$agents_dir/.skill-lock.json"
    claude_skills_dir="$HOME/.claude/skills"

    rm -rf "$skills_dir"
    rm -f "$lock_file"

    if [ -d "$claude_skills_dir" ]; then
        find "$claude_skills_dir" -maxdepth 1 -type l -exec rm -f {} +
    elif [ -L "$claude_skills_dir" ]; then
        rm -f "$claude_skills_dir"
    fi
}

remove_unwanted_agent_skills() {
    local lock_file="$HOME/.agents/.skill-lock.json"
    local skill_name

    if ((${#UNWANTED_AGENT_SKILLS[@]} == 0)); then
        log "No unwanted agent skills configured; skipping cleanup"
        return 0
    fi

    for skill_name in "${UNWANTED_AGENT_SKILLS[@]}"; do
        if [[ ! "$skill_name" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
            printf 'Error: unexpected skill name: %s\n' "$skill_name" >&2
            exit 1
        fi
    done

    npx skills remove "${UNWANTED_AGENT_SKILLS[@]}" \
        --global \
        --yes

    for skill_name in "${UNWANTED_AGENT_SKILLS[@]}"; do
        rm -rf "$HOME/.agents/skills/$skill_name"
    done

    if [ -f "$lock_file" ]; then
        node -e '
            const fs = require("fs");
            const lockPath = process.argv[1];
            const unwantedSkills = process.argv.slice(2);
            const lock = JSON.parse(fs.readFileSync(lockPath, "utf8"));

            for (const skillName of unwantedSkills) {
                delete lock.skills?.[skillName];
            }

            fs.writeFileSync(lockPath, JSON.stringify(lock, null, 2) + "\n");
        ' "$lock_file" "${UNWANTED_AGENT_SKILLS[@]}"
    fi
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

main() {
    # Stage 1: Check required commands and coding agents.

    if ! command -v codex >/dev/null 2>&1; then
        log "Installing Codex"
        curl -fsSL https://chatgpt.com/codex/install.sh | sh
        require_command codex
        success "Codex installed"
    else
        log "Codex has been installed"
    fi

    if ! command -v claude >/dev/null 2>&1; then
        log "Installing Claude Code"
        curl -fsSL https://claude.ai/install.sh | bash
        require_command claude
        success "Claude Code installed"
    else
        log "Claude Code has been installed"
    fi

    if ! command -v pi >/dev/null 2>&1; then
        log "Installing Pi"
        curl -fsSL https://pi.dev/install.sh | sh
        require_command pi
        success "Pi installed"
    else
        log "Pi has been installed"
    fi

    require_command curl
    require_command node
    require_command npx

    # Stage 2: Install the global instructions for Codex and Claude Code.

    log "Installing global instructions for Codex and Claude Code"

    for required in "$SETUP_RULE" "$STATUSLINE_SOURCE"; do
        if [ ! -f "$required" ]; then
            printf 'Error: %s is missing. Run this script from a clone of the repository.\n' "$required" >&2
            exit 1
        fi
    done

    mkdir -p "$HOME/.codex"
    mkdir -p "$HOME/.claude"

    # Delegated to setup-rule.sh so both scripts write global.md the same way:
    # a rules file for Claude Code, a managed block in AGENTS.md for Codex.
    # stdin is closed because setup-rule.sh is non-interactive by design.
    bash "$SETUP_RULE" global --target both --global --migrate-legacy </dev/null

    success "Global instructions installed for Codex and Claude Code"

    # Stage 3: Install the Claude Code statusline.

    log "Installing the Claude Code statusline"

    install_statusline

    success "Claude Code statusline installed"

    # Stage 4: Remove existing global agent skills.

    log "Removing existing agent skills"

    remove_installed_agent_skills

    success "Existing agent skills removed"

    # Stage 5: Install global skills for Codex and Claude Code.

    log "Installing skills for Codex and Claude Code"

    # Install the Waza engineering workflow skills and the Kami document skill.

    install_agent_skills "$WAZA_SKILLS_URL"
    install_agent_skills "$KAMI_SKILLS_URL"

    # Install the Mattpocock engineering and productivity skills.

    install_agent_skills "$MATTPOCOCK_ENGINEERING_URL"
    install_agent_skills "$MATTPOCOCK_PRODUCTIVITY_URL"

    # Install the Humanlayer show-me skill.

    npx skills add "$HUMANLAYER_SKILLS_URL" \
        --skill show-me \
        --agent codex claude-code \
        --global \
        --yes

    # Remove skills that are not part of the desired setup.

    remove_unwanted_agent_skills

    success "Agent skills installed"

    # Stage 6: Install Pi extensions.

    require_command pi

    log "Installing Pi extensions"

    for extension in "${PI_EXTENSIONS[@]}"; do
        pi install "$extension"
    done

    success "Pi extensions installed"
}

# ${BASH_SOURCE[0]:-} rather than ${BASH_SOURCE[0]}: under `set -u` the bare form
# is an unbound-variable error when the script arrives on a pipe, so
# `curl … | bash` finished all its work and then exited 1.
if [ "${BASH_SOURCE[0]:-}" = "$0" ]; then
    main "$@"
fi
