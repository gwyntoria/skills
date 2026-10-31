#!/usr/bin/env bash

set -euo pipefail

# ============================================================
# WSL Ubuntu Development Environment
#
# Usage:
#   ./env-setup-wsl.sh  Install
#
# Current wizard: Bash/Zsh, development runtimes and AI tools.
# Other component installer functions are retained for follow-up tickets.
#
# Target:
#   - Ubuntu on WSL
#   - Bash or Zsh
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
SHELL_RC=""
INPUTRC=""
NVM_DIR=""
SHELL_BLOCK_START='# >>> env-setup-wsl.sh shell >>>'
SHELL_BLOCK_END='# <<< env-setup-wsl.sh shell <<<'
SHELL_NAME=bash
SHELL_LABEL=Bash
OMZ_DIR=""
OMZ_CUSTOM=""
SHELL_PATH=""
ACCOUNT_NAME=""
ORIGINAL_SHELL=""
STEP_LABELS=() STEP_STATES=() STEP_REMEDIES=() STEP_CODES=()
readonly STEP_BREW=4 STEP_LAZYGIT=5 STEP_UV=6 STEP_NODE=7
readonly STEP_USER_BIN=8 STEP_COMPLETION=9 STEP_LAZY_BREW=10
readonly STEP_CODEX=11 STEP_CLAUDE=12 STEP_AGENT=13 STEP_OMZ=14 STEP_FZF=15 STEP_PLUGIN_BASE=16

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
    SHELL_RC="$HOME/.bashrc"
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
    printf '\n交互式 Bash/Zsh 环境配置：选择 shell 和组件，确认后安装并设置默认 shell。\n'
    printf '可选：系统基础包、Homebrew/eza、lazygit、uv/Python、nvm/Node.js。\n'
    printf '\n选项：\n  -h, --help       显示帮助（无需交互终端）\n'
    printf '\n安装需要交互终端；NO_COLOR 可禁用颜色，不提供无人值守安装参数。\n'
    printf '保留版本环境变量：PYTHON_VERSION=3.14、NODE_VERSION=lts/*。\n'
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

# Homebrew's installer prints shell setup instructions; it does not write profiles.
ensure_homebrew() {
    if ! command_exists brew; then
        if [ ! -x "$HOMEBREW_BIN" ]; then
            local installer
            installer=$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)
            NONINTERACTIVE=1 /bin/bash -c "$installer"
        fi
        export PATH="${HOMEBREW_BIN%/*}:$PATH"
    fi
    local shell_environment
    shell_environment=$(brew shellenv bash)
    eval "$shell_environment"
    brew --version
}

install_homebrew() {
    ensure_homebrew
    if ! command_exists eza; then brew install eza; fi
    eza --version
}

check_git() {
    log "Checking Git"

    git --version

    success "Git installed"
}

install_lazygit() {
    if command_exists lazygit; then
        lazygit --version
        return
    fi
    if apt-cache show lazygit >/dev/null 2>&1 && sudo apt install -y lazygit; then
        lazygit --version
        return
    fi
    # A distinct result requests the separately reported Homebrew fallback step.
    return 20
}

install_lazygit_brew() {
    local shell_environment
    shell_environment=$(brew shellenv bash)
    eval "$shell_environment"
    brew install lazygit
    lazygit --version
}

configure_user_bin() {
    printf '配置用户工具目录：%s%s%s\n' "$BLUE" "$LOCAL_BIN" "$RESET"

    mkdir -p "$LOCAL_BIN"

    install -m 0755 "$SCRIPT_DIR/env-update.sh" "$LOCAL_BIN/toria-update"
    printf 'toria-update 已安装\n'

    export PATH="$LOCAL_BIN:$PATH"
}

configure_inputrc() {
    printf '配置 Bash 大小写不敏感补全\n'

    append_once 'set completion-ignore-case on' "$INPUTRC"

    printf 'Bash 补全已配置\n'
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

    remove_managed_block "$WT_HOOK_START" "$WT_HOOK_END" "$SHELL_RC" || return 1
    remove_exact_line 'eval "$(starship init bash)"' "$SHELL_RC" || return 1
    remove_exact_line 'starship_precmd_user_func="__wt_update_cwd"' "$SHELL_RC" || return 1

    if ! active_line_contains 'function __wt_update_cwd()' "$SHELL_RC"; then
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
            >>"$SHELL_RC"
    else
        append_once 'starship_precmd_user_func="__wt_update_cwd"' "$SHELL_RC"
        append_once 'eval "$(starship init bash)"' "$SHELL_RC"
    fi
}

install_uv() {
    if ! command_exists uv; then
        curl -LsSf https://astral.sh/uv/install.sh |
            UV_NO_MODIFY_PATH=1 UV_INSTALL_DIR="$LOCAL_BIN" sh
    fi
    uv --version
    install_python
}

install_python() {
    printf '检查 Python %s\n' "$PYTHON_VERSION"

    if uv python find "$PYTHON_VERSION" >/dev/null 2>&1; then
        printf 'Python %s 已安装\n' "$PYTHON_VERSION"
    else
        uv python install "$PYTHON_VERSION"
        printf 'Python %s 已安装\n' "$PYTHON_VERSION"
    fi

    uv python find "$PYTHON_VERSION"
    uv python list --only-installed
}

install_nvm() {
    export NVM_DIR
    if [ ! -s "$NVM_DIR/nvm.sh" ]; then
        curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.6/install.sh |
            PROFILE=/dev/null NODE_VERSION='' bash
    fi
    [ -s "$NVM_DIR/nvm.sh" ]
    # shellcheck disable=SC1090
    source "$NVM_DIR/nvm.sh"
    nvm --version
    install_node
}

install_node() {
    local installed_version
    local version_status

    printf '检查 Node.js %s\n' "$NODE_VERSION"

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
        printf 'Node.js 已安装：%s\n' "$installed_version"
    else
        nvm install "$NODE_VERSION" || return "$?"
    fi

    nvm use "$NODE_VERSION" || return "$?"
    node --version
    npm --version
    # Persist the verified request: run_step's active version dies with its subshell.
    nvm alias default "$NODE_VERSION"
}

install_codex() {
    if ! command_exists codex; then
        curl -fsSL https://chatgpt.com/codex/install.sh |
            SHELL="/bin/$SHELL_NAME" CODEX_INSTALL_DIR="$LOCAL_BIN" CODEX_NON_INTERACTIVE=true sh
    fi
    codex --version
}

install_claude() {
    if ! command_exists claude; then
        curl -fsSL https://claude.ai/install.sh | SHELL="/bin/$SHELL_NAME" bash
    fi
    claude --version
}

configure_agents() {
    # run_step owns this subshell; activate the verified Node for the delegated entrypoint.
    # shellcheck disable=SC1090
    source "$NVM_DIR/nvm.sh" --no-use
    nvm use "$NODE_VERSION"
    command_exists node
    command_exists npm
    command_exists npx
    SHELL="/bin/$SHELL_NAME" bash "$SCRIPT_DIR/agent-setup.sh" --agent --skill
}

report_installed_versions() (
    printf '\n可用工具版本\n'
    local command shell_environment
    if [ "${STEP_STATES[STEP_BREW]:-}" = '成功' ] || [ "${STEP_STATES[STEP_LAZY_BREW]:-}" = '成功' ]; then
        if shell_environment=$(brew shellenv bash); then eval "$shell_environment"; fi
    fi
    if [ "${STEP_STATES[STEP_NODE]:-}" = '成功' ]; then
        # Report the verified request, rather than an unrelated inherited Node.
        # shellcheck disable=SC1090
        source "$NVM_DIR/nvm.sh" --no-use || return 1
        nvm use "$NODE_VERSION" || return 1
    fi
    for command in git brew eza lazygit starship uv node npm codex claude; do
        if command_exists "$command"; then
            printf '%s%s%s: ' "$CYAN" "$command" "$RESET"
            "$command" --version || printf '%s版本查询失败%s\n' "$YELLOW" "$RESET"
        fi
    done
)

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
    STEP_CODES[$id]="$result"
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

install_selected_shell() {
    local shell_path
    if ! command_exists "$SHELL_NAME"; then
        sudo apt update
        sudo apt install -y "$SHELL_NAME"
    fi
    shell_path=$(type -P "$SHELL_NAME")
    "$shell_path" --version
}

install_oh_my_zsh() {
    if [ ! -s "$OMZ_DIR/oh-my-zsh.sh" ]; then
        # Clone only: the upstream installer creates a template even with KEEP_ZSHRC=yes
        # when .zshrc is absent. Never let it write profiles or change the account shell.
        if ! command_exists git; then
            sudo apt update
            sudo apt install -y git
        fi
        git clone --depth=1 https://github.com/ohmyzsh/ohmyzsh.git "$OMZ_DIR"
    fi
    test -s "$OMZ_DIR/oh-my-zsh.sh"
}

install_fzf() {
    if ! command_exists fzf; then
        sudo apt update
        sudo apt install -y fzf
    fi
    fzf --version
}

install_plugin() (
    local name="$1" temporary_file
    if plugin_file "$name" >/dev/null; then return 0; fi
    if ! command_exists git; then
        sudo apt update
        sudo apt install -y git
    fi
    mkdir -p "$OMZ_CUSTOM/plugins"
    case "$name" in
    zsh-autosuggestions|zsh-syntax-highlighting)
        git clone --depth=1 "https://github.com/zsh-users/$name.git" "$OMZ_CUSTOM/plugins/$name" ;;
    *)
        # Recover a missing bundled plugin without replacing an existing framework.
        temporary_file=$(mktemp -d)
        trap 'rm -rf -- "$temporary_file"' EXIT
        git clone --depth=1 https://github.com/ohmyzsh/ohmyzsh.git "$temporary_file/framework"
        cp -R -- "$temporary_file/framework/plugins/$name" "$OMZ_CUSTOM/plugins/$name" ;;
    esac
    plugin_file "$name" >/dev/null
)

install_plugins() {
    local rerun_command="$1" runtime_command="$2"
    local id step label
    if [ "${PLUGIN_SELECTED[PLUGIN_FZF]}" -eq 0 ]; then
        skip_step "$STEP_FZF" 'fzf 程序' '用户未选择'
    elif [ "${STEP_STATES[STEP_OMZ]}" != '成功' ]; then
        skip_step "$STEP_FZF" 'fzf 程序' '因依赖失败跳过' "$rerun_command"
    else
        run_step "$STEP_FZF" 'fzf 程序（自动依赖）' 'sudo apt update && sudo apt install -y fzf && fzf --version' install_fzf
    fi
    for id in "${!PLUGIN_NAMES[@]}"; do
        step=$((STEP_PLUGIN_BASE + id))
        label="Zsh 插件 ${PLUGIN_NAMES[id]}"
        if [ "${PLUGIN_SELECTED[id]}" -eq 0 ]; then
            skip_step "$step" "$label" '用户未选择'
        elif [ "${STEP_STATES[STEP_OMZ]}" != '成功' ] ||
            { [ "$id" -eq "$PLUGIN_FZF" ] && [ "${STEP_STATES[STEP_FZF]}" != '成功' ]; } ||
            { [ "$id" -eq "$PLUGIN_NVM" ] && [ "${STEP_STATES[STEP_NODE]}" != '成功' ]; }; then
            skip_step "$step" "$label" '因依赖失败跳过' "$runtime_command"
        else
            run_step "$step" "$label" "$rerun_command" install_plugin "${PLUGIN_NAMES[id]}"
        fi
    done
}

discover_zsh_path() {
    local variable="$1"
    local result="$2"
    [ -f "$SHELL_RC" ] || { printf -v "$variable" '%s' "$result"; return 0; }
    local line value
    local assignment="^[[:space:]]*(export[[:space:]]+)?$variable=(.*)$"
    local double_quoted='^"([^"]*)"[[:space:]]*(#.*)?$'
    local single_quoted="^'([^']*)'[[:space:]]*(#.*)?$"
    local unquoted='^([^[:space:];]+)[[:space:]]*(#.*)?$'
    while IFS= read -r line || [ -n "$line" ]; do
        [[ "$line" =~ $assignment ]] || continue
        value=${BASH_REMATCH[2]}
        # Decode only literal paths and HOME prefixes. Never source/eval user config.
        if [[ "$value" =~ $single_quoted ]]; then
            value=${BASH_REMATCH[1]}
        elif [[ "$value" =~ $double_quoted ]] || [[ "$value" =~ $unquoted ]]; then
            value=${BASH_REMATCH[1]}
            case "$value" in
            '$HOME/'*) value="$HOME/${value#\$HOME/}" ;;
            '${HOME}/'*) value="$HOME/${value#\$\{HOME\}/}" ;;
            '$ZSH/'*) value="$OMZ_DIR/${value#\$ZSH/}" ;;
            '${ZSH}/'*) value="$OMZ_DIR/${value#\$\{ZSH\}/}" ;;
            \~/*) value="$HOME/${value:2}" ;;
            esac
        else
            continue
        fi
        if [[ "$value" == /* && "$value" != *'$'* && "$value" != *'`'* ]]; then
            result="$value"
        fi
    done <"$SHELL_RC"
    printf -v "$variable" '%s' "$result"
}

readonly PLUGIN_FZF=3 PLUGIN_NVM=4 PLUGIN_HIGHLIGHT=6
PLUGIN_NAMES=(git copypath z fzf nvm zsh-autosuggestions zsh-syntax-highlighting extract)
PLUGIN_SELECTED=(1 1 1 1 1 1 1 1)

plugin_file() {
    local name="$1" directory
    for directory in "$OMZ_CUSTOM/plugins/$name" "$OMZ_DIR/plugins/$name"; do
        if [ -f "$directory/$name.plugin.zsh" ] && [ -r "$directory/$name.plugin.zsh" ]; then
            printf '%s\n' "$directory/$name.plugin.zsh"; return 0
        elif [ -f "$directory/_$name" ] && [ -r "$directory/_$name" ]; then
            printf '%s\n' "$directory/_$name"; return 0
        fi
    done
    return 1
}

choose_plugins() {
    local focus=0 id key mark state color
    while :; do
        [ -z "$RESET" ] || printf '\033[H\033[2J'
        printf '\n选择 Zsh 插件\n'
        for id in "${!PLUGIN_NAMES[@]}"; do
            mark=' '; [ "${PLUGIN_SELECTED[id]}" -eq 0 ] || mark=x
            state=未安装 color="$YELLOW"
            if plugin_file "${PLUGIN_NAMES[id]}" >/dev/null; then state=已安装 color="$GREEN"; fi
            if [ "$focus" -eq "$id" ]; then printf '%s> ' "$FOCUS"; else printf '  '; fi
            printf '[%s] %s%s%s %s%s%s\n' "$mark" "$CYAN" "${PLUGIN_NAMES[id]}" "$RESET" "$color" "$state" "$RESET"
        done
        if [ "$focus" -eq 8 ]; then printf '%s> ' "$FOCUS"; else printf '  '; fi
        printf '继续%s\n方向键移动 · 空格勾选 · 回车继续 · b 返回组件 · q 取消\n' "$RESET"
        IFS= read -rsn1 key || return 1
        case "$key" in
        $'\e')
            IFS= read -rsn2 -t 0.2 key || :
            case "$key" in '[A') focus=$(((focus + 8) % 9)) ;; '[B') focus=$(((focus + 1) % 9)) ;; esac ;;
        ' ') if [ "$focus" -lt 8 ]; then PLUGIN_SELECTED[focus]=$((1 - PLUGIN_SELECTED[focus])); fi ;;
        '') resolve_components; return 0 ;;
        b|B) return 2 ;;
        q|Q) return 1 ;;
        esac
    done
}

choose_shell() {
    local key focus=0 id label
    while :; do
        [ -z "$RESET" ] || printf '\033[H\033[2J'
        printf '\n选择终端类型\n'
        for id in 0 1; do
            if [ "$id" -eq 0 ]; then label=Bash; else label=Zsh; fi
            if [ "$focus" -eq "$id" ]; then printf '%s> ' "$FOCUS"; else printf '  '; fi
            printf '%s%s%s\n' "$CYAN" "$label" "$RESET"
        done
        printf '方向键移动 · 回车选择 · q 取消\n'
        IFS= read -rsn1 key || return 1
        case "$key" in
        $'\e')
            IFS= read -rsn2 -t 0.2 key || :
            case "$key" in '[A'|'[B') focus=$((1 - focus)) ;; esac ;;
        '')
            if [ "$focus" -eq 0 ]; then SHELL_NAME=bash SHELL_LABEL=Bash; else SHELL_NAME=zsh SHELL_LABEL=Zsh; fi
            SHELL_RC="$HOME/.$SHELL_NAME"rc
            if [ "$SHELL_NAME" = zsh ]; then
                discover_zsh_path ZSH "${ZSH:-$HOME/.oh-my-zsh}"
                OMZ_DIR="$ZSH"
                discover_zsh_path ZSH_CUSTOM "${ZSH_CUSTOM:-$OMZ_DIR/custom}"
                OMZ_CUSTOM="$ZSH_CUSTOM"
            fi
            return 0 ;;
        q|Q) return 1 ;;
        esac
    done
}

# Sub-blocks let a successful component update its paths without removing a
# failed or unselected component's previous initialization. Only staged files enter here.
begin_component_config() {
    local name="$1" file="$2"
    remove_managed_block "# >>> env-setup-wsl.sh $name >>>" "# <<< env-setup-wsl.sh $name <<<" "$file"
    printf '# >>> env-setup-wsl.sh %s >>>\n' "$name" >>"$file"
}

end_component_config() {
    printf '# <<< env-setup-wsl.sh %s <<<\n' "$1" >>"$2"
}

prepare_plugin_config() {
    local file="$1" block staging id name step cleanup_command
    block=$(mktemp "${file}.plugins.XXXXXX")
    printf -v cleanup_command 'rm -f -- %q %q' "$file" "$block"
    # shellcheck disable=SC2064
    trap "$cleanup_command" EXIT
    staging=$(mktemp "${file}.stage.XXXXXX")
    # The parent configuration transaction owns every temporary file.
    printf -v cleanup_command 'rm -f -- %q %q %q' "$file" "$block" "$staging"
    # shellcheck disable=SC2064
    trap "$cleanup_command" EXIT
    awk '
        $0 == "# >>> env-setup-wsl.sh plugins >>>" { inside=1; next }
        $0 == "# <<< env-setup-wsl.sh plugins <<<" { inside=0; next }
        inside { print }
    ' "$file" >"$block"
    remove_managed_block '# >>> env-setup-wsl.sh plugins >>>' '# <<< env-setup-wsl.sh plugins <<<' "$file"
    remove_managed_block '# >>> env-setup-wsl.sh plugin-paths >>>' '# <<< env-setup-wsl.sh plugin-paths <<<' "$block"
    printf '# >>> env-setup-wsl.sh plugin-paths >>>\ntypeset -a plugins\nexport ZSH_CUSTOM=%q\n# <<< env-setup-wsl.sh plugin-paths <<<\n' "$OMZ_CUSTOM" >"$staging"
    cat "$block" >>"$staging"
    cat "$staging" >"$block"
    # Zsh syntax highlighting must load after the other selected plugins.
    for id in 0 1 2 "$PLUGIN_FZF" "$PLUGIN_NVM" 5 7 "$PLUGIN_HIGHLIGHT"; do
        name=${PLUGIN_NAMES[id]} step=$((STEP_PLUGIN_BASE + id))
        if [ "${PLUGIN_SELECTED[id]}" -eq 0 ] || [ "${STEP_STATES[step]}" = '成功' ]; then
            begin_component_config "plugin-$name" "$block"
            printf 'plugins=("${(@)plugins:#%s}")\n' "$name" >>"$block"
            if [ "${PLUGIN_SELECTED[id]}" -eq 1 ]; then
                if [ "$id" -eq "$PLUGIN_NVM" ]; then printf 'export NVM_DIR="$HOME/.nvm"\n' >>"$block"; fi
                printf 'plugins+=(%s)\n' "$name" >>"$block"
            fi
            end_component_config "plugin-$name" "$block"
        fi
    done
    # The override must precede OMZ, including when the user already loads it.
    awk -v block="$block" '
        !inserted && $0 !~ /^[[:space:]]*#/ && /(^|[;&|[:space:]])(source|[.]|\\[.])[[:space:]]+[^#]*oh-my-zsh\.sh/ {
            print "# >>> env-setup-wsl.sh plugins >>>"
            while ((getline line < block) > 0) print line
            close(block)
            print "# <<< env-setup-wsl.sh plugins <<<"
            inserted=1
        }
        { print }
        END { if (!inserted) exit 1 }
    ' "$file" >"$staging"
    cat "$staging" >"$file"
    # Keep original user initialization lines, guarding them instead of deleting them.
    # The plugin owns initialization when enabled; otherwise the first source owns it.
    if [ "${PLUGIN_SELECTED[PLUGIN_NVM]}" -eq 0 ] || [ "${STEP_STATES[STEP_PLUGIN_BASE+PLUGIN_NVM]}" = '成功' ]; then
        remove_managed_block '# >>> env-setup-wsl.sh nvm-owner >>>' '# <<< env-setup-wsl.sh nvm-owner <<<' "$file"
        printf '# >>> env-setup-wsl.sh nvm-owner >>>\n_ENV_SETUP_WSL_NVM_PLUGIN=%s\n# <<< env-setup-wsl.sh nvm-owner <<<\n' "${PLUGIN_SELECTED[PLUGIN_NVM]}" >"$staging"
    else
        : >"$staging"
    fi
    awk '
        function quoted_prefix(text, quote, i, c) {
            quote=""
            for (i=1; i<=length(text); i++) {
                c=substr(text,i,1)
                if (c == "\\" && quote != sprintf("%c",39)) { i++; continue }
                if (quote == "" && (c == "\"" || c == sprintf("%c",39))) quote=c
                else if (c == quote) quote=""
            }
            return quote != ""
        }
        function guard_sources(line, result, prefix, command, suffix) {
            result=""
            while (match(line, /(^|[;&|[:space:]])(source|[.]|\\[.])[[:space:]]+("[^"]*nvm[.]sh"|\047[^\047]*nvm[.]sh\047|[^[:space:];|&"]*nvm[.]sh)([[:space:]]+--no-use)?/)) {
                prefix=substr(line,1,RSTART-1)
                command=substr(line,RSTART,RLENGTH)
                suffix=substr(line,RSTART+RLENGTH)
                if (command ~ /^[;&|[:space:]]/) {
                    prefix=prefix substr(command,1,1)
                    command=substr(command,2)
                }
                if (quoted_prefix(prefix)) return result line
                result=result prefix "{ if [[ ${_ENV_SETUP_WSL_NVM_PLUGIN:-0} != 1 ]] && (( ! $+functions[nvm] )); then " command "; fi; }"
                line=suffix
                changed=1
            }
            return result line
        }
        $0 == "# >>> env-setup-wsl.sh nvm-source >>>" { guarded=1 }
        !guarded && $0 !~ /^[[:space:]]*#/ {
            changed=0
            replacement=guard_sources($0)
            if (changed) {
                print "# >>> env-setup-wsl.sh nvm-source >>>"
                print replacement
                print "# <<< env-setup-wsl.sh nvm-source <<<"
                next
            }
        }
        { print }
        $0 == "# <<< env-setup-wsl.sh nvm-source <<<" { guarded=0 }
    ' "$file" >>"$staging"
    cat "$staging" >"$file"
}

prepare_shell_config() (
    local target directory filename temporary_file backup_file cleanup_command
    if [ -L "$SHELL_RC" ] && [ ! -e "$SHELL_RC" ]; then
        printf '错误：配置符号链接的目标不存在，保留原链接。\n' >&2
        return 1
    fi
    local other_rc="$HOME/.zshrc"
    if [ "$SHELL_NAME" = zsh ]; then other_rc="$HOME/.bashrc"; fi
    if [ "$SHELL_RC" -ef "$other_rc" ]; then
        printf '错误：Bash 与 Zsh 共用同一个配置文件，保留原文件并跳过切换。\n' >&2
        return 1
    fi
    target=$(readlink -f -- "$SHELL_RC")
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
    printf '%s\n# 目标 shell：%s；此块由环境安装向导管理。\n' "$SHELL_BLOCK_START" "$SHELL_LABEL" >>"$temporary_file"
    # Keep failed/unselected component blocks; replace only successful components.
    if [ -f "$target" ]; then
        awk -v start="$SHELL_BLOCK_START" -v end="$SHELL_BLOCK_END" '
            $0 == start { inside=1; next }
            $0 == end { inside=0; next }
            inside && $0 !~ /^# 目标 shell/ { print }
        ' "$target" >>"$temporary_file"
    fi
    if [ "$SHELL_NAME" = zsh ] && [ "${STEP_STATES[STEP_OMZ]:-}" = '成功' ] && [ -f "$target" ]; then
        local previous_plugins
        previous_plugins=$(awk '
            $0 == "# >>> env-setup-wsl.sh plugins >>>" { inside=1 }
            inside { print }
            $0 == "# <<< env-setup-wsl.sh plugins <<<" { inside=0 }
        ' "$target")
        remove_managed_block '# >>> env-setup-wsl.sh plugins >>>' '# <<< env-setup-wsl.sh plugins <<<' "$temporary_file"
        # Move the previous selection out of the OMZ sub-block before refreshing it.
        # Failed plugins keep their prior initialization while successful ones update.
        if [ -n "$previous_plugins" ]; then printf '%s\n' "$previous_plugins" >>"$temporary_file"; fi
    fi
    if [ "${STEP_STATES[STEP_USER_BIN]:-}" = '成功' ] || [ "${STEP_STATES[STEP_UV]:-}" = '成功' ] ||
        [ "${STEP_STATES[STEP_CODEX]:-}" = '成功' ] || [ "${STEP_STATES[STEP_CLAUDE]:-}" = '成功' ]; then
        begin_component_config paths "$temporary_file"
        append_once 'export PATH="$HOME/.local/bin:$PATH"' "$temporary_file"
        end_component_config paths "$temporary_file"
    fi
    if [ "${STEP_STATES[STEP_BREW]:-}" = '成功' ] || [ "${STEP_STATES[STEP_LAZY_BREW]:-}" = '成功' ]; then
        local brew_path brew_line
        brew_path=$(type -P brew)
        printf -v brew_line 'eval "$(%q shellenv %s)"' "$brew_path" "$SHELL_NAME"
        begin_component_config homebrew "$temporary_file"
        append_once "$brew_line" "$temporary_file"
        end_component_config homebrew "$temporary_file"
    fi
    if [ "${STEP_STATES[STEP_BREW]:-}" = '成功' ]; then
        begin_component_config eza "$temporary_file"
        append_once 'alias ls="eza -al --git --group-directories-first --icons=auto"' "$temporary_file"
        append_once 'alias la="eza -alG --git --group-directories-first --icons=auto"' "$temporary_file"
        end_component_config eza "$temporary_file"
    fi
    if [ "$SHELL_NAME" = zsh ] && [ "${STEP_STATES[STEP_PLUGIN_BASE+PLUGIN_NVM]:-}" = '成功' ]; then
        remove_managed_block '# >>> env-setup-wsl.sh nvm >>>' '# <<< env-setup-wsl.sh nvm <<<' "$temporary_file"
    elif [ "${STEP_STATES[STEP_NODE]:-}" = '成功' ]; then
        begin_component_config nvm "$temporary_file"
        append_unless_active_line_contains 'export NVM_DIR=' 'export NVM_DIR="$HOME/.nvm"' "$temporary_file"
        append_unless_active_line_contains '"$NVM_DIR/nvm.sh"' '[ ! -s "$NVM_DIR/nvm.sh" ] || . "$NVM_DIR/nvm.sh"' "$temporary_file"
        if [ "$SHELL_NAME" = bash ]; then
            append_unless_active_line_contains '"$NVM_DIR/bash_completion"' '[ ! -s "$NVM_DIR/bash_completion" ] || . "$NVM_DIR/bash_completion"' "$temporary_file"
        fi
        end_component_config nvm "$temporary_file"
    fi
    if [ "$SHELL_NAME" = zsh ]; then
        begin_component_config completion "$temporary_file"
        append_once "zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}'" "$temporary_file"
        if [ "${STEP_STATES[STEP_OMZ]:-}" != '成功' ]; then
            append_once 'autoload -Uz compinit; compinit' "$temporary_file"
        fi
        end_component_config completion "$temporary_file"
        if [ "${STEP_STATES[STEP_OMZ]:-}" = '成功' ]; then
            begin_component_config oh-my-zsh "$temporary_file"
            if ! active_line_contains 'oh-my-zsh.sh' "$temporary_file"; then
                local omz_line
                printf -v omz_line 'export ZSH=%q' "$OMZ_DIR"
                append_unless_active_line_contains 'export ZSH=' "$omz_line" "$temporary_file"
                # Preserve user themes, including an explicitly empty theme.
                append_unless_active_line_contains 'ZSH_THEME=' 'ZSH_THEME="robbyrussell"' "$temporary_file"
                append_once 'source "$ZSH/oh-my-zsh.sh"' "$temporary_file"
            fi
            end_component_config oh-my-zsh "$temporary_file"
        fi
    fi
    printf '%s\n' "$SHELL_BLOCK_END" >>"$temporary_file"
    if [ "$SHELL_NAME" = zsh ] && [ "${STEP_STATES[STEP_OMZ]:-}" = '成功' ]; then
        prepare_plugin_config "$temporary_file"
    fi
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
    printf '默认 shell 已设置为 %s%s%s，请重新打开终端。\n' "$CYAN" "$SHELL_LABEL" "$RESET"
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

COMPONENT_LABELS=('系统基础包' 'Homebrew/eza' 'lazygit' 'uv/Python' 'nvm/Node.js' 'Codex CLI' 'Claude Code' 'Agent/Skill 配置')
EXPLICIT=(1 1 1 1 1 1 1 1)
SELECTED=(1 1 1 1 1 1 1 1)
COMPONENT_STEPS=(1 "$STEP_BREW" "$STEP_LAZYGIT" "$STEP_UV" "$STEP_NODE" "$STEP_CODEX" "$STEP_CLAUDE" "$STEP_AGENT")

needs_system_packages() {
    case "$1" in
    1) ! command_exists brew && { ! command_exists curl || ! command_exists git || ! command_exists make; } ;;
    2) ! command_exists lazygit && ! command_exists brew && { ! command_exists curl || ! command_exists git || ! command_exists make; } ;;
    3) ! command_exists uv && ! command_exists curl ;;
    4)
        if [ ! -s "$NVM_DIR/nvm.sh" ]; then
            ! command_exists curl || ! command_exists git
        else
            [ "$NVM_TARGET_INSTALLED" -eq 0 ] && ! command_exists curl && ! command_exists wget
        fi ;;
    5) ! command_exists codex && ! command_exists curl ;;
    6) ! command_exists claude && ! command_exists curl ;;
    7) ! command_exists curl ;;
    *) return 1 ;;
    esac
}

resolve_components() {
    SELECTED=("${EXPLICIT[@]}")
    local id
    if [ "$SHELL_NAME" = zsh ] && [ "${PLUGIN_SELECTED[PLUGIN_NVM]}" -eq 1 ]; then SELECTED[4]=1; fi
    if [ "${SELECTED[7]}" -eq 1 ]; then
        SELECTED[4]=1 SELECTED[5]=1 SELECTED[6]=1
    fi
    for id in 1 2 3 4 5 6 7; do
        if [ "${SELECTED[id]}" -eq 1 ] && needs_system_packages "$id"; then SELECTED[0]=1; fi
    done
    SYSTEM_SELECTED=${SELECTED[0]}
}

choose_components() {
    local key focus=0 mark id reason notice=''
    while :; do
        resolve_components
        [ -z "$RESET" ] || printf '\033[H\033[2J'
        printf '\n选择安装组件（%s）\n' "$SHELL_LABEL"
        for id in "${!COMPONENT_LABELS[@]}"; do
            mark=' '; reason=''
            if [ "${SELECTED[id]}" -eq 1 ]; then
                mark=x
                if [ "${EXPLICIT[id]}" -eq 1 ]; then reason='手动选择'; else reason='自动补齐'; fi
            fi
            if [ "$focus" -eq "$id" ]; then printf '%s> ' "$FOCUS"; else printf '  '; fi
            printf '[%s] %s%s%s %s%s%s\n' "$mark" "$CYAN" "${COMPONENT_LABELS[id]}" "$RESET" "$YELLOW" "$reason" "$RESET"
        done
        if [ "$focus" -eq "${#COMPONENT_LABELS[@]}" ]; then printf '%s> ' "$FOCUS"; else printf '  '; fi
        printf '继续%s\n' "$RESET"
        printf '%s%s%s\n方向键移动 · 空格勾选 · 回车继续 · q 取消\n' "$YELLOW" "$notice" "$RESET"
        IFS= read -rsn1 key || return 1
        case "$key" in
        $'\e')
            IFS= read -rsn2 -t 0.2 key || :
            case "$key" in '[A') focus=$(((focus + ${#COMPONENT_LABELS[@]}) % (${#COMPONENT_LABELS[@]} + 1))) ;; '[B') focus=$(((focus + 1) % (${#COMPONENT_LABELS[@]} + 1))) ;; esac ;;
        ' ')
            notice=''
            if [ "$focus" -lt "${#COMPONENT_LABELS[@]}" ]; then
                if [ "${SELECTED[focus]}" -eq 1 ]; then
                    EXPLICIT[focus]=0
                    if [ "$SHELL_NAME" = zsh ] && [ "$focus" -eq 4 ] && [ "${PLUGIN_SELECTED[PLUGIN_NVM]}" -eq 1 ]; then
                        PLUGIN_SELECTED[PLUGIN_NVM]=0
                        notice+='连带取消 nvm 插件；'
                    fi
                    if [ "$focus" -ge 4 ] && [ "$focus" -le 6 ] && [ "${SELECTED[7]}" -eq 1 ]; then
                        EXPLICIT[7]=0
                        notice+='连带取消 Agent/Skill 配置；'
                    fi
                    if [ "$focus" -eq 0 ]; then
                        for id in 1 2 3 4 5 6 7; do
                            if [ "${SELECTED[id]}" -eq 1 ] && needs_system_packages "$id"; then
                                EXPLICIT[id]=0
                                if [ "$SHELL_NAME" = zsh ] && [ "$id" -eq 4 ] && [ "${PLUGIN_SELECTED[PLUGIN_NVM]}" -eq 1 ]; then
                                    PLUGIN_SELECTED[PLUGIN_NVM]=0
                                    notice+='连带取消 nvm 插件；'
                                fi
                                notice+="连带取消 ${COMPONENT_LABELS[id]}；"
                                if [ "$id" -ge 4 ] && [ "$id" -le 6 ] && [ "${SELECTED[7]}" -eq 1 ] && [ "${EXPLICIT[7]}" -eq 1 ]; then
                                    EXPLICIT[7]=0
                                    notice+='连带取消 Agent/Skill 配置；'
                                fi
                            fi
                        done
                    fi
                else EXPLICIT[focus]=1
                fi
            fi ;;
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
    if ! choose_shell; then
        printf '已取消，未执行安装计划。\n'
        return 0
    fi
    # Discover existing installations before calculating dependencies; no files are changed.
    export PATH="$LOCAL_BIN:$PATH"
    if ! command_exists brew && [ -x "$HOMEBREW_BIN" ]; then
        export PATH="${HOMEBREW_BIN%/*}:$PATH"
    fi
    NVM_TARGET_INSTALLED=0
    if [ -s "$NVM_DIR/nvm.sh" ] && (
        # Query without activating the previous default in this planning subprocess.
        # shellcheck disable=SC1090
        source "$NVM_DIR/nvm.sh" --no-use || exit "$?"
        nvm version "$NODE_VERSION"
    ) >/dev/null 2>&1; then NVM_TARGET_INSTALLED=1; fi
    local picker_status
    while :; do
        if ! choose_components; then
            printf '已取消，未执行安装计划。\n'; return 0
        fi
        [ "$SHELL_NAME" = zsh ] || break
        picker_status=0
        choose_plugins || picker_status=$?
        case "$picker_status" in
        0) break ;;
        2) continue ;;
        *) printf '已取消，未执行安装计划。\n'; return 0 ;;
        esac
    done
    printf '\n安装计划\n目标 shell：%s%s%s\n配置路径：%s%s%s\n' "$CYAN" "$SHELL_LABEL" "$RESET" "$BLUE" "$SHELL_RC" "$RESET"
    if [ "$SHELL_NAME" = zsh ]; then
        printf '必做：%sOh My Zsh%s，安装位置：%s%s%s（复用已有安装，不覆盖启动文件）。\n' "$CYAN" "$RESET" "$BLUE" "$OMZ_DIR" "$RESET"
        if [ ! -s "$OMZ_DIR/oh-my-zsh.sh" ] && ! command_exists git; then
            printf '%sOh My Zsh 依赖 git：缺失时必须安装。%s\n' "$YELLOW" "$RESET"
        fi
    fi
    local component_id plugin_id
    if [ "$SHELL_NAME" = zsh ]; then
        for plugin_id in "${!PLUGIN_NAMES[@]}"; do
            if [ "${PLUGIN_SELECTED[plugin_id]}" -eq 1 ]; then
                printf '启用插件：%s%s%s\n' "$CYAN" "${PLUGIN_NAMES[plugin_id]}" "$RESET"
            fi
        done
        if ! command_exists git; then
            for plugin_id in "${!PLUGIN_NAMES[@]}"; do
                if [ "${PLUGIN_SELECTED[plugin_id]}" -eq 1 ] && ! plugin_file "${PLUGIN_NAMES[plugin_id]}" >/dev/null; then
                    printf '%s缺失插件依赖 git：安装时按需执行 sudo apt install -y git。%s\n' "$YELLOW" "$RESET"
                    break
                fi
            done
        fi
        if [ "${PLUGIN_SELECTED[PLUGIN_FZF]}" -eq 1 ] && ! command_exists fzf; then
            printf '%sfzf 程序（自动补齐）：sudo apt install -y fzf%s\n' "$YELLOW" "$RESET"
        fi
    fi
    for component_id in "${!COMPONENT_LABELS[@]}"; do
        if [ "${SELECTED[component_id]}" -eq 1 ]; then
            printf '安装组件：%s%s%s（' "$CYAN" "${COMPONENT_LABELS[component_id]}" "$RESET"
            if [ "${EXPLICIT[component_id]}" -eq 1 ]; then printf '手动选择'; else printf '%s自动补齐%s' "$YELLOW" "$RESET"; fi
            printf '）\n'
        fi
    done
    if [ "${SELECTED[2]}" -eq 1 ] && ! command_exists lazygit; then
        printf 'lazygit：优先 apt；失败时使用 Homebrew（按需安装，依赖 curl/git/make）。\n'
    fi
    if [ "${SELECTED[7]}" -eq 1 ]; then
        printf 'Agent/Skill：复用组合入口 %s' "$MAGENTA"
        printf 'bash %q --agent --skill' "$SCRIPT_DIR/agent-setup.sh"
        printf '%s（全局规则、Claude 状态栏和动态发现的技能）。\n' "$RESET"
    fi
    printf '请求版本：Python %s%s%s；Node.js %s%s%s\n' "$CYAN" "$PYTHON_VERSION" "$RESET" "$CYAN" "$NODE_VERSION" "$RESET"
    printf '原默认 shell：%s%s%s\n' "$BLUE" "$ORIGINAL_SHELL" "$RESET"
    if [ "$SYSTEM_SELECTED" -eq 1 ]; then
        printf '系统包：%s' "$CYAN"
        printf '%s ' "${SYSTEM_PACKAGES[@]}"
        printf '%s\n' "$RESET"
    fi
    printf '必做：准备 %s 和启动配置，在流程末尾设置为默认 shell。\n' "$SHELL_LABEL"
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
    STEP_LABELS=() STEP_STATES=() STEP_REMEDIES=() STEP_CODES=()
    local rerun_command config_command shell_install_command
    printf -v rerun_command 'bash %q' "$SCRIPT_DIR/$PROGRAM_NAME"
    printf -v config_command '%s -n %q && %s' "$SHELL_NAME" "$SHELL_RC" "$rerun_command"
    shell_install_command="sudo apt install -y $SHELL_NAME && $rerun_command"
    run_step 0 "$SHELL_LABEL 安装" "$shell_install_command" install_selected_shell
    if [ "${STEP_STATES[0]}" = '成功' ]; then
        if SHELL_PATH=$(type -P "$SHELL_NAME") && SHELL_PATH=$(readlink -f -- "$SHELL_PATH"); then
            :
        else
            STEP_STATES[0]='失败'
            printf '%s错误：无法解析 %s 路径，继续其他独立步骤。%s\n' "$RED" "$SHELL_LABEL" "$RESET" >&2
        fi
    fi
    if [ "$SYSTEM_SELECTED" -eq 1 ]; then
        local packages_command
        printf -v packages_command 'sudo apt update && sudo apt install -y %s' "${SYSTEM_PACKAGES[*]}"
        run_step 1 '系统基础包' "$packages_command" install_system_packages
    else
        skip_step 1 '系统基础包' '用户未选择'
    fi
    if [ "$SHELL_NAME" = zsh ]; then
        if [ "${STEP_STATES[0]}" = '成功' ]; then
            run_step "$STEP_OMZ" 'Oh My Zsh' "$rerun_command" install_oh_my_zsh
        else
            skip_step "$STEP_OMZ" 'Oh My Zsh' '因依赖失败跳过' "$shell_install_command"
        fi
    fi
    run_step "$STEP_USER_BIN" '用户工具目录 / toria-update' "$rerun_command" configure_user_bin
    export PATH="$LOCAL_BIN:$PATH"
    if ! command_exists brew && [ -x "$HOMEBREW_BIN" ]; then
        export PATH="${HOMEBREW_BIN%/*}:$PATH"
    fi
    local step_id installer dependency_failed runtime_command
    printf -v runtime_command 'PYTHON_VERSION=%q NODE_VERSION=%q %s' "$PYTHON_VERSION" "$NODE_VERSION" "$rerun_command"
    for component_id in 1 2 3 4 5 6; do
        step_id=${COMPONENT_STEPS[component_id]}
        case "$component_id" in
        1) installer=install_homebrew ;;
        2) installer=install_lazygit ;;
        3) installer=install_uv ;;
        4) installer=install_nvm ;;
        5) installer=install_codex ;;
        6) installer=install_claude ;;
        esac
        if [ "${SELECTED[component_id]}" -eq 0 ]; then
            skip_step "$step_id" "${COMPONENT_LABELS[component_id]}" '用户未选择'
            continue
        fi
        dependency_failed=0
        if needs_system_packages "$component_id" && [ "${STEP_STATES[1]}" != '成功' ]; then dependency_failed=1; fi
        if [ "$component_id" -eq 3 ] && ! command_exists uv && [ "${STEP_STATES[STEP_USER_BIN]}" != '成功' ]; then dependency_failed=1; fi
        if [ "$dependency_failed" -eq 1 ]; then
            skip_step "$step_id" "${COMPONENT_LABELS[component_id]}" '因依赖失败跳过' "$runtime_command"
        else
            run_step "$step_id" "${COMPONENT_LABELS[component_id]}" "$runtime_command" "$installer"
            if [ "$component_id" -eq 2 ] && [ "${STEP_CODES[STEP_LAZYGIT]:-0}" -eq 20 ]; then
                printf '%s警告：lazygit 的 apt 安装不可用，使用计划中的 Homebrew 后备路径。%s\n' "$YELLOW" "$RESET"
                run_step "$STEP_LAZY_BREW" 'Homebrew（lazygit 自动依赖）' "$runtime_command" ensure_homebrew
                if ! command_exists brew && [ -x "$HOMEBREW_BIN" ]; then export PATH="${HOMEBREW_BIN%/*}:$PATH"; fi
                if [ "${STEP_STATES[STEP_LAZY_BREW]}" = '成功' ]; then
                    run_step "$STEP_LAZYGIT" 'lazygit' "$runtime_command" install_lazygit_brew
                else
                    skip_step "$STEP_LAZYGIT" 'lazygit' '因依赖失败跳过' "$runtime_command"
                fi
            fi
        fi
    done
    local agent_command
    printf -v agent_command 'source %q && nvm use %q && bash %q --agent --skill' \
        "$NVM_DIR/nvm.sh" "$NODE_VERSION" "$SCRIPT_DIR/agent-setup.sh"
    if [ "${SELECTED[7]}" -eq 0 ]; then
        skip_step "$STEP_AGENT" 'Agent/Skill 配置' '用户未选择'
    elif [ "${STEP_STATES[STEP_NODE]}" != '成功' ] || [ "${STEP_STATES[STEP_CODEX]}" != '成功' ] ||
        [ "${STEP_STATES[STEP_CLAUDE]}" != '成功' ] ||
        { needs_system_packages 7 && [ "${STEP_STATES[1]}" != '成功' ]; }; then
        skip_step "$STEP_AGENT" 'Agent/Skill 配置' '因依赖失败跳过' "$runtime_command"
    else
        run_step "$STEP_AGENT" 'Agent/Skill 配置' "$agent_command" configure_agents
    fi
    if [ "$SHELL_NAME" = zsh ]; then install_plugins "$rerun_command" "$runtime_command"; fi
    # Each step runs in a subshell; rediscover installed command paths in the parent.
    if ! command_exists brew && [ -x "$HOMEBREW_BIN" ]; then export PATH="${HOMEBREW_BIN%/*}:$PATH"; fi
    if [ "$SHELL_NAME" = bash ]; then
        run_step "$STEP_COMPLETION" 'Bash 补全' "$rerun_command" configure_inputrc
    fi
    if [ "${STEP_STATES[0]}" = '成功' ]; then
        run_step 2 "$SHELL_LABEL 配置" "检查路径、权限及托管块，修复后运行：$config_command" prepare_shell_config
    else
        skip_step 2 "$SHELL_LABEL 配置" '因依赖失败跳过' "$shell_install_command"
    fi
    if [ "${STEP_STATES[0]}" = '成功' ] && [ "${STEP_STATES[2]}" = '成功' ]; then
        local shell_command
        printf -v shell_command 'chsh -s %q %q' "$SHELL_PATH" "$ACCOUNT_NAME"
        run_step 3 '默认 shell 切换' "$shell_command" change_default_shell
    else
        skip_step 3 '默认 shell 切换' '因依赖失败跳过' "先修复 $SHELL_LABEL 安装或配置，再运行：$rerun_command"
    fi
    report_installed_versions || printf '%s部分版本查询失败，继续显示安装结果。%s\n' "$YELLOW" "$RESET"
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
