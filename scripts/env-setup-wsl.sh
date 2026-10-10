#!/usr/bin/env bash

set -euo pipefail

# ============================================================
# WSL Ubuntu Development Environment
#
# Usage:
#   ./env-setup-wsl.sh  Install
#
# Handles:
#   - apt system packages
#   - Homebrew
#   - Git
#   - lazygit
#   - Starship
#   - uv and Python
#   - nvm and Node.js
#   - Codex CLI
#   - Claude Code
#   - Global agent/skill configuration
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
    gcc-arm-none-eabi
    direnv
    procps
    file
    unzip
    zip
    jq
    net-tools
    ripgrep
    fd-find
    tree
)

# $HOME 派生路径统一由 set_paths 赋值。顺序要求：require_safe_home 必须先通过，
# 避免 HOME 为空或为 / 时向错误位置写入配置。
LOCAL_BIN=""
BASHRC=""
INPUTRC=""
NVM_DIR=""

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
        printf 'Error: HOME is empty or unsafe.\n' >&2
        exit 1
    fi

    case "$HOME" in
    /*) ;;
    *)
        printf 'Error: HOME must be an absolute path.\n' >&2
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
        printf 'Error: could not safely remove managed block from %s. Original file preserved.\n' "$file" >&2
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
    printf 'Usage: %s [options]\n' "$PROGRAM_NAME"
    printf '\n'
    printf 'Options:\n'
    printf '  -h, --help       Show this help message\n'
    printf '\n'
    printf 'Environment variables:\n'
    printf '  PYTHON_VERSION=3.14    uv-managed Python version to install\n'
    printf '  NODE_VERSION=lts/*     Node.js version installed through nvm\n'
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
            printf 'Error: unknown option: %s\n\n' "$1" >&2
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

    log "Checking system packages"

    for package in "${SYSTEM_PACKAGES[@]}"; do
        if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null |
            grep -Fqx 'install ok installed'; then
            missing+=("$package")
        fi
    done

    if [ "${#missing[@]}" -eq 0 ]; then
        success "System packages already installed"
    else
        sudo apt update
        sudo apt install -y "${missing[@]}"
        success "Missing system packages installed"
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

run_install() {
    log "Checking environment"

    if ! grep -qi microsoft /proc/version 2>/dev/null; then
        warn "This script is designed for WSL."
    fi

    if ! command_exists apt; then
        echo "Error: apt was not found. This script currently supports Ubuntu/Debian."
        exit 1
    fi

    success "WSL/Ubuntu environment detected"

    install_system_packages
    install_homebrew
    check_git
    install_lazygit
    configure_user_bin
    configure_inputrc
    install_starship
    install_uv
    install_python
    install_nvm
    install_node
    install_codex
    install_claude
    bash "$SCRIPT_DIR/agent-setup.sh" --agent --skill
    report_installed_versions

    printf '\n'
    success "WSL development environment setup completed."

    printf '\n'
    echo "Restart your terminal or run:"
    echo
    echo "    source ~/.bashrc"
    echo
    echo "Then authenticate Codex with:"
    echo
    echo "    codex"
    echo
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
