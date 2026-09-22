#!/usr/bin/env bash

set -euo pipefail

# ============================================================
# WSL Ubuntu Development Environment
#
# Usage:
#   ./wsl_setup.sh              Install
#   ./wsl_setup.sh --uninstall  Remove what the installer created
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
#
# --uninstall preserves Codex CLI and, by default, the apt packages.
#
# Target:
#   - Ubuntu on WSL
#   - Bash
# ============================================================

PROGRAM_NAME="${0##*/}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

PYTHON_VERSION="${PYTHON_VERSION:-3.14}"
NODE_VERSION="${NODE_VERSION:-lts/*}"
REMOVE_APT_PACKAGES="${REMOVE_APT_PACKAGES:-0}"
ASSUME_YES="${ASSUME_YES:-0}"

HOMEBREW_BIN="/home/linuxbrew/.linuxbrew/bin/brew"

WT_HOOK_START='# >>> wsl_setup.sh Windows Terminal CWD hook >>>'
WT_HOOK_END='# <<< wsl_setup.sh Windows Terminal CWD hook <<<'

# 安装和卸载共用同一份清单：安装时补装缺失项，REMOVE_APT_PACKAGES=1 时按它卸载。
# 两份清单分开写会逐渐漂移，之前就漏掉了 make、cmake、clang-format 等包。
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
    ripgrep
    fd-find
    tree
)

# $HOME 派生路径统一由 set_paths 赋值。顺序要求：require_safe_home 必须先通过，
# 否则 HOME 为空或为 / 时这些路径指向错误位置，而卸载路径里跟着 rm -rf。
MODE="install"
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

require_not_root() {
    if [ "$EUID" -eq 0 ]; then
        printf 'Error: do not run this script with sudo or as root.\n' >&2
        exit 1
    fi
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

    directory="$(dirname "$file")"
    filename="$(basename "$file")"
    temporary_file="$(mktemp "$directory/.${filename}.tmp.XXXXXX")"

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
        chmod --reference="$file" "$temporary_file"
        mv -- "$temporary_file" "$file"
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

    directory="$(dirname "$file")"
    filename="$(basename "$file")"
    temporary_file="$(mktemp "$directory/.${filename}.tmp.XXXXXX")"

    awk -v start="$start_marker" -v end="$end_marker" '
        $0 == start { removing = 1; next }
        removing && $0 == end { removing = 0; next }
        !removing { print }
    ' "$file" >"$temporary_file"

    if cmp -s "$file" "$temporary_file"; then
        rm -f -- "$temporary_file"
    else
        chmod --reference="$file" "$temporary_file"
        mv -- "$temporary_file" "$file"
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
    printf '      --uninstall  Remove the tools and shell configuration this script installed\n'
    printf '\n'
    printf 'Environment variables:\n'
    printf '  PYTHON_VERSION=3.14    uv-managed Python version to install or remove\n'
    printf '  NODE_VERSION=lts/*     Node.js version installed through nvm\n'
    printf '  ASSUME_YES=1           Skip the UNINSTALL confirmation\n'
    printf '  REMOVE_APT_PACKAGES=1  Also remove the apt packages during --uninstall\n'
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
        --uninstall)
            MODE="uninstall"
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

    append_once 'alias la="eza -laG --group-directories-first --icons=auto"' "$BASHRC"
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

    install -m 0755 "$SCRIPT_DIR/toria-up.sh" "$LOCAL_BIN/toria-up"
    success "toria-up installed"

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

    remove_managed_block "$WT_HOOK_START" "$WT_HOOK_END" "$BASHRC"
    remove_exact_line 'eval "$(starship init bash)"' "$BASHRC"
    remove_exact_line 'starship_precmd_user_func="__wt_update_cwd"' "$BASHRC"

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

    log "Checking Node.js ${NODE_VERSION}"

    # 有意分两行写。`local x="$(...)"` 会用 local 的退出码盖掉命令替换的失败，
    # 这里要和改动前的全局赋值保持一致的错误传播。
    installed_version="$(nvm version "$NODE_VERSION")"

    if [ "$installed_version" != "N/A" ]; then
        success "Node.js already installed: $installed_version"
    else
        nvm install "$NODE_VERSION"
        nvm alias default "$NODE_VERSION"
        nvm use default
        success "Node.js installed: $(node --version)"
        success "npm installed: $(npm --version)"
    fi
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
}

# ------------------------------------------------------------
# Uninstall steps
# ------------------------------------------------------------

# 打印删除清单并等待确认。ASSUME_YES=1 时直接通过。
# 返回 0 继续卸载，1 表示用户取消。
confirm_uninstall() {
    printf '%s\n' \
        "This script will remove:" \
        "  - nvm and every Node.js version installed under ~/.nvm" \
        "  - uv binaries and uv-managed Python ${PYTHON_VERSION}" \
        "  - Starship installed at ~/.local/bin/starship" \
        "  - toria-up installed at ~/.local/bin/toria-up" \
        "  - lazygit installed by apt or Homebrew" \
        "  - Homebrew and every package installed through Homebrew" \
        "  - Exact ~/.bashrc lines added by wsl_setup.sh" \
        "  - The ~/.inputrc line added by wsl_setup.sh" \
        "" \
        "Codex CLI and all Codex data will be preserved." \
        "apt system packages are preserved by default."

    if [ "$ASSUME_YES" = "1" ]; then
        return 0
    fi

    printf '\nType UNINSTALL to continue: '
    local confirmation=""
    read -r confirmation || true

    if [ "$confirmation" != "UNINSTALL" ]; then
        warn "Uninstallation cancelled"
        return 1
    fi

    return 0
}

uninstall_nvm() {
    log "Removing nvm and Node.js"

    if [ -d "$NVM_DIR" ]; then
        rm -rf -- "$NVM_DIR"
        success "nvm and its Node.js installations removed"
    else
        warn "nvm was not found"
    fi
}

uninstall_uv_and_python() {
    log "Removing uv-managed Python ${PYTHON_VERSION} and uv"

    if [ -x "$LOCAL_BIN/uv" ]; then
        "$LOCAL_BIN/uv" python uninstall "$PYTHON_VERSION" ||
            warn "uv could not uninstall Python ${PYTHON_VERSION}"

        rm -f -- \
            "$LOCAL_BIN/uv" \
            "$LOCAL_BIN/uvx" \
            "$LOCAL_BIN/uvw"

        success "uv binaries removed"
    else
        warn "uv installed at ~/.local/bin was not found"
    fi
}

uninstall_starship() {
    log "Removing Starship"

    if [ -e "$LOCAL_BIN/starship" ] || [ -L "$LOCAL_BIN/starship" ]; then
        rm -f -- "$LOCAL_BIN/starship"
        success "Starship removed"
    else
        warn "Starship installed at ~/.local/bin was not found"
    fi
}

# 必须在 uninstall_homebrew 之前调用：Homebrew 不在时这条腿才轮到 apt。
uninstall_lazygit() {
    log "Removing lazygit"

    if dpkg-query -W -f='${Status}' lazygit 2>/dev/null | grep -Fq 'install ok installed'; then
        if sudo apt remove -y lazygit; then
            success "apt-installed lazygit removed"
        else
            warn "apt could not remove lazygit"
        fi
    elif [ -x "$HOMEBREW_BIN" ] && "$HOMEBREW_BIN" list --formula lazygit >/dev/null 2>&1; then
        if "$HOMEBREW_BIN" uninstall lazygit; then
            success "Homebrew-installed lazygit removed"
        else
            warn "Homebrew could not remove lazygit"
        fi
    else
        warn "lazygit was not found"
    fi
}

uninstall_homebrew() {
    log "Removing Homebrew"

    if [ -x "$HOMEBREW_BIN" ]; then
        if curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/uninstall.sh |
            NONINTERACTIVE=1 /bin/bash; then
            success "Homebrew removed"
        else
            warn "Homebrew uninstaller reported an error"
        fi
    else
        warn "Homebrew was not found"
    fi
}

# 每行删除都挂 || warn。remove_exact_line 只在文件读写出错时返回 1，
# 让它冒泡出去的话 set -e 会在卸载进行到一半时终止脚本，留下半清理状态。
uninstall_shell_config() {
    log "Removing shell configuration"

    remove_exact_line 'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"' "$BASHRC" ||
        warn "Could not update $BASHRC"

    remove_exact_line 'alias la="eza -laG --group-directories-first --icons=auto"' "$BASHRC" ||
        warn "Could not update $BASHRC"

    remove_exact_line 'export PATH="$HOME/.local/bin:$PATH"' "$BASHRC" ||
        warn "Could not update $BASHRC"

    remove_managed_block "$WT_HOOK_START" "$WT_HOOK_END" "$BASHRC" ||
        warn "Could not update $BASHRC"

    remove_exact_line 'eval "$(starship init bash)"' "$BASHRC" ||
        warn "Could not update $BASHRC"

    remove_exact_line 'starship_precmd_user_func="__wt_update_cwd"' "$BASHRC" ||
        warn "Could not update $BASHRC"

    remove_exact_line 'export NVM_DIR="$HOME/.nvm"' "$BASHRC" ||
        warn "Could not update $BASHRC"

    remove_exact_line '[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"' "$BASHRC" ||
        warn "Could not update $BASHRC"

    remove_exact_line '[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm' "$BASHRC" ||
        warn "Could not update $BASHRC"

    remove_exact_line '[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"' "$BASHRC" ||
        warn "Could not update $BASHRC"

    remove_exact_line '[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion' "$BASHRC" ||
        warn "Could not update $BASHRC"

    # 只删安装脚本写入的那一行，~/.inputrc 文件本身保留。
    remove_exact_line 'set completion-ignore-case on' "$INPUTRC" ||
        warn "Could not update $INPUTRC"

    rm -f -- "$LOCAL_BIN/toria-up"

    rmdir "$LOCAL_BIN" 2>/dev/null || true

    success "Shell configuration removed"
}

# 必须排在最后。这一步会移除 curl 和 git，提前执行会让后面依赖它们的
# Homebrew 卸载器失效。
uninstall_optional_apt_packages() {
    if [ "$REMOVE_APT_PACKAGES" != "1" ]; then
        warn "apt system packages were preserved"
        return 0
    fi

    log "Removing apt system packages"

    warn "These packages may be used by software unrelated to wsl_setup.sh"

    if sudo apt remove -y "${SYSTEM_PACKAGES[@]}"; then
        success "apt system packages removed"
    else
        warn "apt reported an error while removing system packages"
    fi
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

run_uninstall() {
    require_not_root

    if ! confirm_uninstall; then
        return 0
    fi

    uninstall_nvm
    uninstall_uv_and_python
    uninstall_starship
    uninstall_lazygit
    uninstall_homebrew
    uninstall_shell_config
    uninstall_optional_apt_packages

    printf '\n'
    success "WSL development environment uninstallation completed"

    printf '\nRestart your terminal or run:\n\n'
    echo "    exec bash"
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

    if [ "$MODE" = "uninstall" ]; then
        run_uninstall
    else
        run_install
    fi
}

# 守卫让脚本可以被 source 进来单独调用某个函数做检查，
# 直接执行时行为不变。
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
