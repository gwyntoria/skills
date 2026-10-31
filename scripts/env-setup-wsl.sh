#!/usr/bin/env bash

set -euo pipefail

# ============================================================
# WSL Ubuntu Development Environment
#
# Usage:
#   ./env-setup-wsl.sh  Install
#
# Current wizard: Bash and apt system packages.
# Other component installer functions are retained for follow-up tickets.
#
# Target:
#   - Ubuntu on WSL
#   - Bash
# ============================================================

PROGRAM_NAME="${0##*/}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

PYTHON_VERSION="${PYTHON_VERSION:-3.14}"
NODE_VERSION="${NODE_VERSION:-lts/*}"

HOMEBREW_BIN="/home/linuxbrew/.linuxbrew/bin/brew"

WT_HOOK_START='# >>> env-setup-wsl.sh Windows Terminal CWD hook >>>'
WT_HOOK_END='# <<< env-setup-wsl.sh Windows Terminal CWD hook <<<'

# 安装时按清单补装缺失的系统包。
SYSTEM_PACKAGES=(
    git
    curl
    wget
    ca-certificates
    build-essential
    make
    cmake
    clang-format
    direnv
    procps
    file
    unzip
    jq
    net-tools
    ripgrep
    fd-find
    shellcheck
    7zip
)

# $HOME 派生路径统一由 set_paths 赋值。顺序要求：require_safe_home 必须先通过，
# 避免 HOME 为空或为 / 时向错误位置写入配置。
LOCAL_BIN=""
BASHRC=""
INPUTRC=""
NVM_DIR=""
SHELL_BLOCK_START='# >>> env-setup-wsl.sh shell >>>'
SHELL_BLOCK_END='# <<< env-setup-wsl.sh shell <<<'
SHELL_PATH=""
ACCOUNT_NAME=""
ORIGINAL_SHELL=""
STEP_LABELS=() STEP_STATES=() STEP_REMEDIES=()

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
    printf '\033[1;33m! %s\033[0m\n' "$1"
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# ------------------------------------------------------------
# Environment guards
# ------------------------------------------------------------

require_safe_home() {
    if [ -z "${HOME:-}" ] || [ "$HOME" = "/" ]; then
        printf '错误：HOME 为空或指向不安全的位置。\n' >&2
        exit 1
    fi

    case "$HOME" in
    /*) ;;
    *)
        printf '错误：HOME 必须是绝对路径。\n' >&2
        exit 1
        ;;
    esac
}

set_paths() {
    LOCAL_BIN="$HOME/.local/bin"
    BASHRC="$HOME/.bashrc"
    INPUTRC="$HOME/.inputrc"
    NVM_DIR="$HOME/.nvm"
}

# ------------------------------------------------------------
# Shell file helpers
# ------------------------------------------------------------

append_once() {
    local line="$1"
    local file="$2"

    touch "$file"

    if ! grep -Fqx "$line" "$file"; then
        printf '\n%s\n' "$line" >>"$file"
    fi
}

active_line_contains() {
    local fragment="$1"
    local file="$2"
    local line=""
    local trimmed

    [ -f "$file" ] || return 1

    while IFS= read -r line || [ -n "$line" ]; do
        trimmed="${line#"${line%%[![:space:]]*}"}"

        case "$trimmed" in
        "" | \#*)
            continue
            ;;
        esac

        if [[ "$trimmed" == *"$fragment"* ]]; then
            return 0
        fi
    done <"$file"

    return 1
}

append_unless_active_line_contains() {
    local fragment="$1"
    local line="$2"
    local file="$3"

    touch "$file"

    if ! active_line_contains "$fragment" "$file"; then
        printf '\n%s\n' "$line" >>"$file"
    fi
}

remove_exact_line() {
    local line="$1"
    local file="$2"
    local directory
    local filename
    local temporary_file
    local grep_status

    [ -f "$file" ] || return 0

    # 替换符号链接的目标文件，保留用户的配置链接。
    file="$(readlink -f -- "$file")" || return 1
    directory="$(dirname "$file")"
    filename="$(basename "$file")"
    temporary_file="$(mktemp "$directory/.${filename}.tmp.XXXXXX")" || return 1

    if grep -Fvx -- "$line" "$file" >"$temporary_file"; then
        :
    else
        grep_status="$?"

        if [ "$grep_status" -ne 1 ]; then
            rm -f -- "$temporary_file"
            warn "Could not update $file"
            return 1
        fi
    fi

    if cmp -s "$file" "$temporary_file"; then
        rm -f -- "$temporary_file"
    else
        if ! chmod --reference="$file" "$temporary_file" || ! mv -- "$temporary_file" "$file"; then
            rm -f -- "$temporary_file"
            return 1
        fi
    fi
}

remove_managed_block() {
    local start_marker="$1"
    local end_marker="$2"
    local file="$3"
    local directory
    local filename
    local temporary_file

    [ -f "$file" ] || return 0

    # 临时文件和目标位于同一目录，替换时不覆盖配置符号链接。
    file="$(readlink -f -- "$file")" || return 1
    directory="$(dirname "$file")"
    filename="$(basename "$file")"
    temporary_file="$(mktemp "$directory/.${filename}.tmp.XXXXXX")" || return 1

    if ! awk -v start="$start_marker" -v end="$end_marker" '
        $0 == start {
            if (removing) invalid = 1
            removing = 1
            next
        }
        $0 == end {
            if (!removing) invalid = 1
            removing = 0
            next
        }
        !removing { print }
        END { if (removing || invalid) exit 1 }
    ' "$file" >"$temporary_file"; then
        rm -f -- "$temporary_file"
        printf '错误：无法安全更新托管块：%s%s%s；原文件已保留。\n' "${BLUE:-}" "$file" "${RESET:-}" >&2
        return 1
    fi

    if cmp -s "$file" "$temporary_file"; then
        rm -f -- "$temporary_file"
    else
        if ! chmod --reference="$file" "$temporary_file" || ! mv -- "$temporary_file" "$file"; then
            rm -f -- "$temporary_file"
            return 1
        fi
    fi
}

# ------------------------------------------------------------
# Argument parsing
# ------------------------------------------------------------

usage() {
    printf '用法：%s [选项]\n' "$PROGRAM_NAME"
    printf '\n交互式 Bash 环境配置：选择系统基础包，确认后安装并设置默认 shell。\n'
    printf '当前阶段仅开放 Bash 和系统基础包，其他组件将在后续任务接入。\n'
    printf '\n选项：\n  -h, --help       显示帮助（无需交互终端）\n'
    printf '\n安装需要交互终端；NO_COLOR 可禁用颜色，不提供无人值守安装参数。\n'
    printf '保留版本环境变量：PYTHON_VERSION=3.14、NODE_VERSION=lts/*（后续组件使用）。\n'
}

# 解析命令行选项。
# 约定：0 继续执行，1 已打印 usage，2 选项错误。这里不自己 exit，
# 退出码统一由 main 决定。
parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
        -h | --help)
            usage
            return 1
            ;;
        *)
            printf '错误：未知选项：%s\n\n' "$1" >&2
            usage >&2
            return 2
            ;;
        esac

        shift
    done

    return 0
}

# ------------------------------------------------------------
# Install steps
# ------------------------------------------------------------

install_system_packages() {
    local package
    local -a missing=()

    printf "检查系统基础包\n"

    for package in "${SYSTEM_PACKAGES[@]}"; do
        if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null |
            grep -Fqx 'install ok installed'; then
            missing+=("$package")
        fi
    done

    if [ "${#missing[@]}" -eq 0 ]; then
        printf "系统基础包已安装\n"
    else
        sudo apt update
        for package in "${missing[@]}"; do
            if [ "$package" = 7zip ]; then
                if ! apt-cache show 7zip >/dev/null; then
                    printf '%s未找到软件包 7zip，请检查发行版及 apt 软件源。%s\n' "$YELLOW" "$RESET" >&2
                    return 1
                fi
            fi
        done
        sudo apt install -y "${missing[@]}"
        printf '缺失的系统包安装完成\n'
    fi
    if command_exists 7zz; then
        7zz i
    elif command_exists 7z; then
        7z i
    else
        printf '错误：7-Zip 软件包未提供可用的 7zz 或 7z 命令。\n' >&2
        return 1
    fi
}

install_homebrew() {
    log "Checking Homebrew"

    if [ -x "$HOMEBREW_BIN" ]; then
        eval "$("$HOMEBREW_BIN" shellenv)"
        success "Homebrew already installed: $(brew --version | head -n 1)"
    else
        NONINTERACTIVE=1 /bin/bash -c \
            "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

        eval "$("$HOMEBREW_BIN" shellenv)"
        success "Homebrew installed"
    fi

    append_once 'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"' "$BASHRC"

    if brew list --formula eza >/dev/null 2>&1; then
        success "eza already installed: $(eza --version | head -n 1)"
    else
        brew install eza
        success "eza installed with Homebrew"
    fi

    append_once 'alias ls="eza -al --git --group-directories-first --icons=auto"' "$BASHRC"
    append_once 'alias la="eza -alG --git --group-directories-first --icons=auto"' "$BASHRC"
}

check_git() {
    log "Checking Git"

    git --version

    success "Git installed"
}

install_lazygit() {
    log "Installing lazygit"

    if command_exists lazygit; then
        success "lazygit already installed: $(lazygit --version)"
    elif apt-cache show lazygit >/dev/null 2>&1 && sudo apt install -y lazygit; then
        success "lazygit installed with apt"
    else
        warn "lazygit could not be installed with apt; falling back to Homebrew"
        brew install lazygit
        success "lazygit installed with Homebrew"
    fi
}

configure_user_bin() {
    log "Configuring user binary directory"

    mkdir -p "$LOCAL_BIN"

    install -m 0755 "$SCRIPT_DIR/env-update.sh" "$LOCAL_BIN/toria-update"
    success "toria-update installed"

    append_once 'export PATH="$HOME/.local/bin:$PATH"' "$BASHRC"

    export PATH="$LOCAL_BIN:$PATH"

    success "$HOME/.local/bin configured"
}

configure_inputrc() {
    log "Configuring case-insensitive completion"

    append_once 'set completion-ignore-case on' "$INPUTRC"

    success "$HOME/.inputrc configured"
}

install_starship() {
    log "Installing Starship"

    if command_exists starship; then
        success "Starship already installed: $(starship --version)"
    else
        curl -sS https://starship.rs/install.sh |
            sh -s -- -y -b "$LOCAL_BIN"

        success "Starship installed"
    fi

    remove_managed_block "$WT_HOOK_START" "$WT_HOOK_END" "$BASHRC" || return 1
    remove_exact_line 'eval "$(starship init bash)"' "$BASHRC" || return 1
    remove_exact_line 'starship_precmd_user_func="__wt_update_cwd"' "$BASHRC" || return 1

    if ! active_line_contains 'function __wt_update_cwd()' "$BASHRC"; then
        printf '\n%s\n' \
            "$WT_HOOK_START" \
            'function __wt_update_cwd() {' \
            '    printf '\''\e]9;9;%s\e\\'\'' "$(wslpath -w "$PWD")"' \
            '}' \
            '' \
            'starship_precmd_user_func="__wt_update_cwd"' \
            '' \
            'eval "$(starship init bash)"' \
            "$WT_HOOK_END" \
            >>"$BASHRC"
    else
        append_once 'starship_precmd_user_func="__wt_update_cwd"' "$BASHRC"
        append_once 'eval "$(starship init bash)"' "$BASHRC"
    fi
}

install_uv() {
    log "Installing uv"

    if command_exists uv; then
        success "uv already installed: $(uv --version)"
    else
        curl -LsSf https://astral.sh/uv/install.sh | sh

        export PATH="$LOCAL_BIN:$PATH"

        success "uv installed"
    fi
}

install_python() {
    log "Checking Python ${PYTHON_VERSION}"

    if uv python find "$PYTHON_VERSION" >/dev/null 2>&1; then
        success "Python ${PYTHON_VERSION} already installed"
    else
        uv python install "$PYTHON_VERSION"
        success "Python ${PYTHON_VERSION} installed"
    fi

    uv python list --only-installed
}

install_nvm() {
    log "Installing nvm"

    export NVM_DIR

    if [ -s "$NVM_DIR/nvm.sh" ]; then
        success "nvm already installed"
    else
        curl -o- \
            https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.6/install.sh |
            bash

        success "nvm installed"
    fi

    append_unless_active_line_contains \
        'export NVM_DIR="$HOME/.nvm"' \
        'export NVM_DIR="$HOME/.nvm"' \
        "$BASHRC"

    append_unless_active_line_contains \
        '"$NVM_DIR/nvm.sh"' \
        '[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm' \
        "$BASHRC"

    append_unless_active_line_contains \
        '"$NVM_DIR/bash_completion"' \
        '[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion' \
        "$BASHRC"

    # 在本脚本里加载 nvm，后面的 install_node 依赖它。
    # 有意写成 if：放到函数末尾的 `[ -s ... ] && source ...` 在条件不成立时
    # 会让函数返回 1，set -e 会直接终止脚本。
    if [ -s "$NVM_DIR/nvm.sh" ]; then
        # shellcheck disable=SC1090
        source "$NVM_DIR/nvm.sh"
    fi
}

install_node() {
    local installed_version
    local version_status

    log "Checking Node.js ${NODE_VERSION}"

    # nvm 用 N/A 和退出码 3 表示未安装；其他错误仍向调用者传播。
    if installed_version="$(nvm version "$NODE_VERSION")"; then
        :
    else
        version_status="$?"
        if [ "$version_status" -ne 3 ] || [ "$installed_version" != "N/A" ]; then
            return "$version_status"
        fi
    fi

    if [ "$installed_version" != "N/A" ]; then
        success "Node.js already installed: $installed_version"
    else
        nvm install "$NODE_VERSION" || return "$?"
        nvm alias default "$NODE_VERSION" || return "$?"
    fi

    nvm use "$NODE_VERSION" || return "$?"
    success "Node.js active: $(node --version)"
    success "npm available: $(npm --version)"
}

install_codex() {
    log "Checking Codex CLI"

    if command_exists codex; then
        success "Codex already installed"
    else
        curl -fsSL https://chatgpt.com/codex/install.sh | sh
        success "Codex installed"
    fi
}

install_claude() {
    log "Checking Claude Code"

    if command_exists claude; then
        success "Claude Code already installed"
    else
        curl -fsSL https://claude.ai/install.sh | bash
        command_exists claude
        success "Claude Code installed"
    fi
}

report_installed_versions() {
    log "Development environment summary"

    printf '\n'

    printf "Git:       "
    git --version

    printf "Homebrew:  "
    brew --version | head -n 1

    printf "lazygit:   "
    lazygit --version

    printf "Starship:  "
    starship --version

    printf "uv:        "
    uv --version

    printf "Python:    "
    uv run python --version

    printf "Node.js:   "
    node --version

    printf "npm:       "
    npm --version

    printf "Codex:     "
    codex --version

    printf "Claude:    "
    claude --version
}

# ------------------------------------------------------------
# Orchestration
# ------------------------------------------------------------

# Run outside a conditional: testing the subshell with if/! disables errexit
# inside its functions and can turn a failed write into a reported success.
run_step() {
    local id="$1" label="$2" remedy="$3" result
    shift 3
    printf '\n==> %s%s%s\n' "$CYAN" "$label" "$RESET"
    set +e
    ( set -e; set -o pipefail; "$@" )
    result=$?
    set -e
    STEP_LABELS[$id]="$label"
    STEP_REMEDIES[$id]="$remedy"
    if [ "$result" -eq 0 ]; then
        STEP_STATES[$id]='成功'
    else
        STEP_STATES[$id]='失败'
        printf '%s失败（退出码 %s），继续其他独立步骤。%s\n' "$RED" "$result" "$RESET" >&2
    fi
}

skip_step() {
    STEP_LABELS[$1]="$2"
    STEP_STATES[$1]="$3"
    STEP_REMEDIES[$1]="${4:-}"
}

load_account() {
    local entry uid
    local -a fields
    uid=$(id -u) || return 1
    entry=$(getent passwd "$uid") || return 1
    IFS=: read -r -a fields <<<"$entry"
    if [ "${#fields[@]}" -ne 7 ] || [ -z "${fields[0]}" ] || [[ "${fields[6]}" != /* ]]; then
        printf '错误：无法读取当前账号的默认 shell，未执行安装。\n' >&2
        return 1
    fi
    ACCOUNT_NAME="${fields[0]}"
    ORIGINAL_SHELL="${fields[6]}"
}

install_bash() {
    local shell_path
    if ! command_exists bash; then
        sudo apt update
        sudo apt install -y bash
    fi
    shell_path=$(type -P bash)
    "$shell_path" --version
}

prepare_shell_config() (
    local target directory filename temporary_file backup_file cleanup_command
    if [ -L "$BASHRC" ] && [ ! -e "$BASHRC" ]; then
        printf '错误：配置符号链接的目标不存在，保留原链接。\n' >&2
        return 1
    fi
    if [ "$BASHRC" -ef "$HOME/.zshrc" ]; then
        printf '错误：Bash 与 Zsh 共用同一个配置文件，保留原文件并跳过切换。\n' >&2
        return 1
    fi
    target=$(readlink -f -- "$BASHRC")
    if [ -e "$target" ] && [ ! -f "$target" ]; then
        printf '错误：配置路径不是普通文件：%s%s%s\n' "$BLUE" "$target" "$RESET" >&2
        return 1
    fi
    directory=$(dirname -- "$target")
    filename=${target##*/}
    temporary_file=$(mktemp "$directory/.${filename}.tmp.XXXXXX")
    printf -v cleanup_command 'rm -f -- %q' "$temporary_file"
    # Capture the shell-quoted temporary path now; function locals are gone at EXIT.
    # shellcheck disable=SC2064
    trap "$cleanup_command" EXIT
    if [ -f "$target" ]; then
        cp -p -- "$target" "$temporary_file"
    fi
    remove_managed_block "$SHELL_BLOCK_START" "$SHELL_BLOCK_END" "$temporary_file"
    printf '%s\n# 目标 shell：Bash；此块由环境安装向导管理。\n%s\n' \
        "$SHELL_BLOCK_START" "$SHELL_BLOCK_END" >>"$temporary_file"
    "$SHELL_PATH" -n "$temporary_file"
    if [ -f "$target" ] && cmp -s "$target" "$temporary_file"; then
        return 0
    fi
    if [ -f "$target" ]; then
        chmod --reference="$target" "$temporary_file"
        backup_file=$(mktemp "$directory/${filename}.env-setup-wsl.backup.XXXXXX")
        cp -p -- "$target" "$backup_file"
        printf '配置备份：%s%s%s\n' "$BLUE" "$backup_file" "$RESET"
        printf '恢复命令：%s' "$MAGENTA"
        printf 'cp -p -- %q %q' "$backup_file" "$target"
        printf '%s\n' "$RESET"
    fi
    mv -- "$temporary_file" "$target"
)

change_default_shell() {
    local current_entry
    if [ "$ORIGINAL_SHELL" != "$SHELL_PATH" ]; then
        chsh -s "$SHELL_PATH" "$ACCOUNT_NAME"
    fi
    current_entry=$(getent passwd "$ACCOUNT_NAME")
    if [ "${current_entry##*:}" != "$SHELL_PATH" ]; then
        printf '错误：账号记录中的默认 shell 尚未变更，请手动检查。\n' >&2
        return 1
    fi
    printf '默认 shell 已设置为 %sBash%s，请重新打开终端。\n' "$CYAN" "$RESET"
}

print_results() {
    local id color failed=0
    printf '\n安装结果\n'
    for id in "${!STEP_LABELS[@]}"; do
        case "${STEP_STATES[id]}" in
        成功) color="$GREEN" ;;
        失败) color="$RED"; failed=1 ;;
        *) color="$YELLOW" ;;
        esac
        printf '  %s[%s]%s %s%s%s\n' "$color" "${STEP_STATES[id]}" "$RESET" \
            "$CYAN" "${STEP_LABELS[id]}" "$RESET"
        if [ "${STEP_STATES[id]}" != '成功' ] && [ -n "${STEP_REMEDIES[id]}" ]; then
            printf '    手动处理：%s%s%s\n' "$MAGENTA" "${STEP_REMEDIES[id]}" "$RESET"
        fi
    done
    printf '原默认 shell：%s%s%s\n' "$BLUE" "$ORIGINAL_SHELL" "$RESET"
    printf '如需恢复默认 shell：%s' "$MAGENTA"
    printf 'chsh -s %q %q' "$ORIGINAL_SHELL" "$ACCOUNT_NAME"
    printf '%s\n' "$RESET"
    return "$failed"
}

init_colors() {
    RESET="" CYAN="" BLUE="" MAGENTA="" GREEN="" RED="" YELLOW="" FOCUS=""
    local colors=0
    if [ -t 1 ] && [ -z "${NO_COLOR+x}" ] && [ "${TERM:-dumb}" != dumb ]; then
        colors=$(tput colors 2>/dev/null) || colors=0
        if [[ "$colors" =~ ^[0-9]+$ ]] && [ "$colors" -ge 8 ]; then
            RESET=$'\e[0m' CYAN=$'\e[36m' BLUE=$'\e[34m' MAGENTA=$'\e[35m'
            GREEN=$'\e[32m' RED=$'\e[31m' YELLOW=$'\e[33m' FOCUS=$'\e[7m'
        fi
    fi
}

choose_components() {
    local key focus=0 mark
    SYSTEM_SELECTED=1
    while :; do
        [ -z "$RESET" ] || printf '\033[H\033[2J'
        printf '\n选择安装组件（当前阶段：Bash / 系统基础包）\n'
        mark='x'
        [ "$SYSTEM_SELECTED" -eq 1 ] || mark=' '
        if [ "$focus" -eq 0 ]; then printf '%s> ' "$FOCUS"; else printf '  '; fi
        printf '[%s] %s系统基础包%s\n' "$mark" "$CYAN" "$RESET"
        if [ "$focus" -eq 1 ]; then printf '%s> ' "$FOCUS"; else printf '  '; fi
        printf '继续%s\n' "$RESET"
        printf '方向键移动 · 空格勾选 · 回车继续 · q 取消\n'
        IFS= read -rsn1 key || return 1
        case "$key" in
        $'\e')
            IFS= read -rsn2 -t 0.2 key || :
            case "$key" in '[A'|'[B') focus=$((1 - focus)) ;; esac ;;
        ' ') [ "$focus" -ne 0 ] || SYSTEM_SELECTED=$((1 - SYSTEM_SELECTED)) ;;
        '') return 0 ;;
        q|Q) return 1 ;;
        esac
    done
}

run_install() {
    if [ ! -t 0 ] || [ ! -t 1 ]; then
        printf '错误：安装向导需要交互终端，请在终端中直接运行。\n' >&2
        return 1
    fi
    init_colors
    if ! load_account; then
        printf '错误：无法读取当前账号信息，未执行安装。\n' >&2
        return 1
    fi
    if ! choose_components; then
        printf '已取消，未执行安装计划。\n'
        return 0
    fi
    printf '\n安装计划\n目标 shell：%sBash%s\n配置路径：%s%s%s\n' "$CYAN" "$RESET" "$BLUE" "$BASHRC" "$RESET"
    if [ "$SYSTEM_SELECTED" -eq 1 ]; then
        printf '安装组件：%s系统基础包%s\n' "$CYAN" "$RESET"
    else
        printf '系统基础包：用户未选择\n'
    fi
    printf '原默认 shell：%s%s%s\n' "$BLUE" "$ORIGINAL_SHELL" "$RESET"
    if [ "$SYSTEM_SELECTED" -eq 1 ]; then
        printf '系统包：%s' "$CYAN"
        printf '%s ' "${SYSTEM_PACKAGES[@]}"
        printf '%s\n' "$RESET"
    fi
    printf '必做：准备 Bash 和启动配置，在流程末尾设置为默认 shell。\n'
    printf '确认执行？[y/N] '
    local reply
    IFS= read -r reply || reply=''
    case "$reply" in
    y|Y) ;;
    *) printf '已取消，未执行安装计划。\n'; return 0 ;;
    esac

    if ! command_exists apt; then
        printf '错误：未找到 apt，当前仅支持 WSL Ubuntu/Debian。\n' >&2
        return 1
    fi
    if ! grep -qi microsoft /proc/version 2>/dev/null; then
        printf '%s警告：此脚本面向 WSL，当前未检测到 WSL 标记。%s\n' "$YELLOW" "$RESET"
    fi
    STEP_LABELS=() STEP_STATES=() STEP_REMEDIES=()
    local rerun_command config_command bash_command
    printf -v rerun_command 'bash %q' "$SCRIPT_DIR/$PROGRAM_NAME"
    printf -v config_command 'bash -n %q && %s' "$BASHRC" "$rerun_command"
    bash_command="sudo apt install -y bash && $rerun_command"
    run_step 0 'Bash 安装' "$bash_command" install_bash
    if [ "${STEP_STATES[0]}" = '成功' ]; then
        if SHELL_PATH=$(type -P bash) && SHELL_PATH=$(readlink -f -- "$SHELL_PATH"); then
            :
        else
            STEP_STATES[0]='失败'
            printf '%s错误：无法解析 Bash 路径，继续其他独立步骤。%s\n' "$RED" "$RESET" >&2
        fi
    fi
    if [ "$SYSTEM_SELECTED" -eq 1 ]; then
        local packages_command
        printf -v packages_command 'sudo apt update && sudo apt install -y %s' "${SYSTEM_PACKAGES[*]}"
        run_step 1 '系统基础包' "$packages_command" install_system_packages
    else
        skip_step 1 '系统基础包' '用户未选择'
    fi
    if [ "${STEP_STATES[0]}" = '成功' ]; then
        run_step 2 'Bash 配置' "检查路径、权限及托管块，修复后运行：$config_command" prepare_shell_config
    else
        skip_step 2 'Bash 配置' '因依赖失败跳过' "$bash_command"
    fi
    if [ "${STEP_STATES[0]}" = '成功' ] && [ "${STEP_STATES[2]}" = '成功' ]; then
        local shell_command
        printf -v shell_command 'chsh -s %q %q' "$SHELL_PATH" "$ACCOUNT_NAME"
        run_step 3 '默认 shell 切换' "$shell_command" change_default_shell
    else
        skip_step 3 '默认 shell 切换' '因依赖失败跳过' "先修复 Bash 安装或配置，再运行：$rerun_command"
    fi
    print_results
}

main() {
    local parse_rc=0

    # 有意用 || 而不是写成裸命令：set -e 会在 parse_args 返回 1（--help）时
    # 立刻终止脚本，下面的 case 根本走不到。放进 AND-OR 列表后 errexit 被豁免。
    parse_args "$@" || parse_rc=$?

    # 0 继续；1 已打印 usage，按成功退出；其余是选项错误。
    case "$parse_rc" in
    0) ;;
    1) return 0 ;;
    *) return 2 ;;
    esac

    # 路径全部由 set_paths 赋值，必须先过 require_safe_home。
    require_safe_home
    set_paths

    run_install
}

# 守卫让脚本可以被 source 进来单独调用某个函数做检查，
# 直接执行时行为不变。
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
