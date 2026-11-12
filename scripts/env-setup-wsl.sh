#!/usr/bin/env bash

set -euo pipefail

# ============================================================
# WSL Ubuntu Development Environment
#
# Usage:
#   ./env-setup-wsl.sh  Install
#
# Interactive Fish/Zsh/Bash setup, plugins, prompts, development runtimes and AI tools.
#
# Target:
#   - Ubuntu on WSL
#   - Fish, Zsh or Bash
# ============================================================

PROGRAM_NAME="env-setup-wsl.sh"
SCRIPT_PATH=""
SETUP_URL="https://raw.githubusercontent.com/gwyntoria/skills/refs/heads/main/scripts/env-setup-wsl.sh"
# 管道执行没有源文件路径，本地执行才解析用于重试的绝对路径。
if [ -n "${BASH_SOURCE[0]:-}" ]; then
    SCRIPT_PATH="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/${BASH_SOURCE[0]##*/}"
    PROGRAM_NAME="${SCRIPT_PATH##*/}"
fi

PYTHON_VERSION="${PYTHON_VERSION:-3.14}"
NODE_VERSION="${NODE_VERSION:-24}"
SYSTEM_NODE_DIR="/usr/bin"
NODESOURCE_LIST="/etc/apt/sources.list.d/nodesource.list"
NODESOURCE_KEY="/usr/share/keyrings/nodesource.gpg"
NODESOURCE_PIN="/etc/apt/preferences.d/nodesource"

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
SHELL_NAME=fish
SHELL_LABEL=Fish
OMZ_DIR=""
OMZ_CUSTOM=""
SHELL_PATH=""
ACCOUNT_NAME=""
ORIGINAL_SHELL=""
STEP_LABELS=() STEP_STATES=() STEP_REMEDIES=() STEP_CODES=()
readonly STEP_BREW=4 STEP_LAZYGIT=5 STEP_UV=6 STEP_NODE=7
readonly STEP_USER_BIN=8 STEP_COMPLETION=9 STEP_LAZY_BREW=10
readonly STEP_OMZ=14 STEP_FZF=15 STEP_PLUGIN_BASE=16 STEP_STARSHIP=24 STEP_NODE_MIGRATION=25

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

# 备份命名沿用 agent-setup.sh 的 .pre-<事件>.bak-<时间戳> 约定，
# UTC 时间戳便于枚举和排序，也不受时区影响。
timestamp() {
    date -u '+%Y%m%dT%H%M%SZ'
}

# 写入 shell 配置前先备份；备份失败即放弃覆盖，原文件保持不动。
# 原件备份（pre-env-setup-wsl.bak）只在目标尚未被本脚本托管时建立一次：
# 此刻文件内容就是安装前的样子。此后每次改动另存一份带时间戳的上一版。
backup_shell_config() (
    local target="$1" directory="$2" filename="$3"
    local pristine="$directory/${filename}.pre-env-setup-wsl.bak"
    local increment stamp temporary_backup='' suffix='' count=1
    trap 'if [ -n "$temporary_backup" ]; then rm -f -- "$temporary_backup"; fi' EXIT

    # 调用方通过 || 检查返回值，函数内不能依赖 set -e。
    if ! stamp=$(timestamp) || [ -z "$stamp" ]; then
        printf '错误：无法生成配置备份时间戳；原文件已保留。\n' >&2
        return 1
    fi

    if [ ! -e "$pristine" ]; then
        if grep -Fq -- "$SHELL_BLOCK_START" "$target"; then
            printf '提示：配置已含托管块，无法补建安装前原件备份；本次改动仍会留下带时间戳的备份。\n'
        elif ! temporary_backup=$(mktemp "$pristine.tmp.XXXXXX") ||
             ! cp -p -- "$target" "$temporary_backup" ||
             ! mv -T -- "$temporary_backup" "$pristine"; then
            printf '错误：无法备份原始配置：%s%s%s；原文件已保留。\n' "${BLUE:-}" "$pristine" "${RESET:-}" >&2
            return 1
        else
            printf '原始配置备份：%s%s%s\n' "${BLUE:-}" "$pristine" "${RESET:-}"
        fi
    fi

    increment="$directory/${filename}.env-setup-wsl.bak-$stamp"
    # 同一秒内的连续运行也不能静默覆盖上一份备份。
    while [ -e "$increment$suffix" ]; do
        count=$((count + 1))
        suffix="-$count"
    done
    increment="$increment$suffix"
    if ! cp -p -- "$target" "$increment"; then
        printf '错误：无法备份当前配置：%s%s%s；原文件已保留。\n' "${BLUE:-}" "$increment" "${RESET:-}" >&2
        return 1
    fi
    printf '配置备份：%s%s%s\n' "${BLUE:-}" "$increment" "${RESET:-}"
    printf '恢复命令：%s' "${MAGENTA:-}"
    printf 'cp -p -- %q %q' "$increment" "$target"
    printf '%s\n' "${RESET:-}"
)

# ------------------------------------------------------------
# Argument parsing
# ------------------------------------------------------------

usage() {
    printf '用法：%s [选项]\n' "$PROGRAM_NAME"
    printf '\n交互式 Fish/Zsh/Bash 环境配置：选择 shell 和组件，确认后安装并设置默认 shell。\n'
    printf '可选：系统基础包、Homebrew/eza、lazygit、uv/Python、Node.js/npm（apt）、Starship、fzf。\n'
    printf '\n选项：\n  -h, --help       显示帮助（无需交互终端）\n'
    printf '\n配置备份：写入前先在配置文件同目录留下 <配置名>.pre-env-setup-wsl.bak（安装前原件，仅一份）\n'
    printf '和 <配置名>.env-setup-wsl.bak-<UTC 时间戳>（每次改动各一份），并打印对应的恢复命令。\n'
    printf '\n安装需要交互终端；NO_COLOR 可禁用颜色，不提供无人值守安装参数。\n'
    printf '保留版本环境变量：PYTHON_VERSION=3.14、NODE_VERSION=24（仅主版本号）。\n'
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

    export PATH="$LOCAL_BIN:$PATH"
}

configure_inputrc() {
    printf '配置 Bash 大小写不敏感补全\n'

    append_once 'set completion-ignore-case on' "$INPUTRC"

    printf 'Bash 补全已配置\n'
}

install_starship() {
    if ! command_exists starship; then
        curl -fsS https://starship.rs/install.sh | sh -s -- -y -b "$LOCAL_BIN"
    fi
    starship --version
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

# --no-remove also protects against changes between simulation and installation.
apt_install_without_removal() {
    local simulation
    simulation=$(LC_ALL=C sudo apt -s install "$@") || return "$?"
    printf '%s\n' "$simulation"
    if [[ "$simulation" == *$'\nRemv '* || "$simulation" == Remv\ * ]]; then
        printf '错误：apt 需要移除现有软件包，请手动处理冲突。\n' >&2
        return 1
    fi
    sudo apt install --no-remove -y "$@"
}

check_npm_prefix() {
    local prefix
    if [ "${NPM_CONFIG_USERCONFIG:-${npm_config_userconfig:-$HOME/.npmrc}}" != "$HOME/.npmrc" ]; then
        printf '错误：npm 使用自定义 userconfig，保留配置，请手动处理。\n' >&2
        return 1
    fi
    if [ -n "${NPM_CONFIG_PREFIX:-${npm_config_prefix:-}}" ]; then
        prefix="${NPM_CONFIG_PREFIX:-$npm_config_prefix}"
        if [ "$prefix" != "$HOME/.local" ]; then
            printf '错误：npm prefix 环境变量为 %s，保留原值，请手动处理。\n' "$prefix" >&2
            return 1
        fi
    fi
    if command_exists npm; then
        prefix=$(npm config get prefix) || return "$?"
        case "$prefix" in
        "$HOME/.local"|/usr|/usr/local|"$NVM_DIR"/*) ;;
        *) printf '错误：已有自定义 npm prefix：%s，保留配置，请手动处理。\n' "$prefix" >&2; return 1 ;;
        esac
    fi
}

install_node() (
    local staging version source_line existing_source created_list=0 created_key=0 created_pin=0 committed=0
    check_npm_prefix
    staging=$(mktemp -d)
    trap 'if [ "$committed" -eq 0 ]; then
        [ "$created_list" -eq 0 ] || sudo rm -f -- "$NODESOURCE_LIST"
        [ "$created_key" -eq 0 ] || sudo rm -f -- "$NODESOURCE_KEY"
        [ "$created_pin" -eq 0 ] || sudo rm -f -- "$NODESOURCE_PIN"
    fi
    rm -rf -- "$staging"' EXIT
    printf -v source_line 'deb [signed-by=%s] https://deb.nodesource.com/node_%s.x nodistro main' "$NODESOURCE_KEY" "$NODE_VERSION"
    printf '%s\n' "$source_line" >"$staging/nodesource.list"
    printf 'Package: nodejs\nPin: origin deb.nodesource.com\nPin-Priority: 600\n' >"$staging/nodesource.pin"
    if [ -e "$NODESOURCE_PIN" ] && ! cmp -s "$NODESOURCE_PIN" "$staging/nodesource.pin"; then
        printf '错误：已有不同的 NodeSource 优先级配置，保留文件：%s\n' "$NODESOURCE_PIN" >&2
        return 1
    fi
    if [ -e "$NODESOURCE_LIST" ] && ! cmp -s "$NODESOURCE_LIST" "$staging/nodesource.list"; then
        printf '错误：已有不同的 NodeSource 源配置，保留文件：%s\n' "$NODESOURCE_LIST" >&2
        return 1
    fi
    for existing_source in "${NODESOURCE_LIST%/*}"/*.list "${NODESOURCE_LIST%/*}"/*.sources; do
        [ -f "$existing_source" ] || continue
        [ "$existing_source" != "$NODESOURCE_LIST" ] || continue
        if grep -Ev '^[[:space:]]*#' "$existing_source" | grep -q 'deb.nodesource.com'; then
            printf '错误：已有其他 NodeSource 源，保留配置：%s\n' "$existing_source" >&2
            return 1
        fi
    done
    sudo apt update
    apt_install_without_removal curl gnupg ca-certificates
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key -o "$staging/key.asc"
    gpg --batch --yes --dearmor -o "$staging/nodesource.gpg" "$staging/key.asc"
    if [ -e "$NODESOURCE_KEY" ]; then
        if ! cmp -s "$NODESOURCE_KEY" "$staging/nodesource.gpg"; then
            printf '错误：已有不同的 NodeSource 密钥，保留文件：%s\n' "$NODESOURCE_KEY" >&2
            return 1
        fi
    else
        created_key=1
        sudo install -m 644 "$staging/nodesource.gpg" "$NODESOURCE_KEY"
    fi
    if [ ! -e "$NODESOURCE_LIST" ]; then
        created_list=1
        sudo install -m 644 "$staging/nodesource.list" "$NODESOURCE_LIST"
    fi
    if [ ! -e "$NODESOURCE_PIN" ]; then
        created_pin=1
        sudo install -m 644 "$staging/nodesource.pin" "$NODESOURCE_PIN"
    fi
    sudo apt update
    # Drain all output: an early awk exit can SIGPIPE apt-cache under pipefail.
    # Select the first exact package version from NodeSource, never a distro fallback.
    version=$(apt-cache madison nodejs | awk -F '|' -v major="$NODE_VERSION" '
        $3 ~ /https:\/\/deb[.]nodesource[.]com\/node_/ {
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2)
            if (!selected && index($2, major ".") == 1) { print $2; selected=1 }
        }')
    if [ -z "$version" ]; then
        printf '错误：NodeSource 中无 Node.js %s 候选版本。\n' "$NODE_VERSION" >&2
        return 1
    fi
    apt_install_without_removal "nodejs=$version"
    [[ "$("$SYSTEM_NODE_DIR/node" --version)" == "v$NODE_VERSION."* ]]
    PATH="$SYSTEM_NODE_DIR:$PATH" "$SYSTEM_NODE_DIR/npm" --version
    # Installation succeeded; retain its source even if later user configuration fails.
    committed=1
    printf 'Node.js/npm 已安装；apt 源：%s；密钥：%s；优先级：%s\n' "$NODESOURCE_LIST" "$NODESOURCE_KEY" "$NODESOURCE_PIN"
)

report_old_node_tools() (
    local executable directory inventory specifications specification
    for executable in "$NVM_DIR"/versions/node/*/bin/npm; do
        [ -x "$executable" ] || continue
        directory=${executable%/*}
        printf '\n旧 nvm 全局工具（%s，保留，不自动重装）：\n' "$directory"
        if ! inventory=$(PATH="$directory:$PATH" "$executable" ls --global --depth=0 --json); then
            printf '清单读取失败，请手动核对。\n'; continue
        fi
        if ! specifications=$(printf '%s' "$inventory" | "$directory/node" -e '
            let input = "";
            process.stdin.on("data", chunk => input += chunk);
            process.stdin.on("end", () => {
                const packages = JSON.parse(input).dependencies || {};
                for (const [name, info] of Object.entries(packages)) {
                    if (info.version) console.log(name + "@" + info.version);
                }
            });'); then
            printf '清单解析失败，请手动核对。\n'; continue
        fi
        while IFS= read -r specification; do
            [ -n "$specification" ] || continue
            printf '重装命令（迁移后按需执行）：npm install -g %q\n' "$specification"
        done <<<"$specifications"
    done
)

# Edit staged copies only; keep unknown shell logic for manual inspection.
disable_nvm_startup() {
    local file="$1" language="$2" staging
    remove_managed_block '# >>> env-setup-wsl.sh nvm >>>' '# <<< env-setup-wsl.sh nvm <<<' "$file"
    remove_managed_block '# >>> env-setup-wsl.sh plugin-nvm >>>' '# <<< env-setup-wsl.sh plugin-nvm <<<' "$file"
    remove_managed_block '# >>> env-setup-wsl.sh nvm-owner >>>' '# <<< env-setup-wsl.sh nvm-owner <<<' "$file"
    staging=$(mktemp "${file}.nvm.XXXXXX")
    local result=0
    awk -v language="$language" -v original="${3:-$file}" '
        function without_nvm(text, token) {
            while (match(text, /(^|[[:space:](])nvm([[:space:])]|$)/)) {
                token=substr(text,RSTART,RLENGTH)
                sub(/nvm/, "", token)
                text=substr(text,1,RSTART-1) token substr(text,RSTART+RLENGTH)
            }
            return text
        }
        /^[[:space:]]*#/ { print; next }
        language == "zsh" && in_plugins {
            if ($0 ~ /^[[:space:]]*\)[[:space:]]*(#.*)?$/) {
                in_plugins=0; print; next
            }
            if ($0 ~ /^[[:space:]]*$/ || $0 ~ /^[[:space:]]*([a-zA-Z0-9_-]+[[:space:]]+)*[a-zA-Z0-9_-]+([[:space:]]+#.*)?[[:space:]]*$/) {
                comment=""; code=$0
                if (match(code, /[[:space:]]+#/)) {
                    comment=substr(code,RSTART); code=substr(code,1,RSTART-1)
                }
                print without_nvm(code) comment; next
            }
            print "请手动检查 Zsh 插件列表：" original ":" FNR ": " $0 > "/dev/stderr"
            unresolved=1; print; next
        }
        language == "zsh" && /^[[:space:]]*plugins=\([[:space:]]*(#.*)?$/ {
            in_plugins=1; print; next
        }
        # These static settings do not load nvm once its plugin is removed.
        language == "zsh" && /^[[:space:]]*zstyle ["\047]:omz:plugins:nvm["\047] lazy(-cmd)? [a-zA-Z0-9_ .\/-]+([[:space:]]+#.*)?[[:space:]]*$/ {
            print; next
        }
        # Exact wrapper emitted by the previous installer; retain trailing user commands.
        /^[[:space:]]*(\[ -[rs] "\$NVM_DIR\/nvm.sh" \] && )?\{ if/ && index($0, "{ if [[ ${_ENV_SETUP_WSL_NVM_PLUGIN:-0} != 1 ]] && (( ! $+functions[nvm] )); then ") {
            gsub(/if \[\[ \$\{_ENV_SETUP_WSL_NVM_PLUGIN:-0\} != 1 \]\] && \(\( ! \$\+functions\[nvm\] \)\)/, "if false")
            print; next
        }
        /^[[:space:]]*(\[ -[rs] "\$NVM_DIR\/nvm.sh" \] && )?\{ if false; then / { print; next }
        language == "zsh" && /^[[:space:]]*plugins=\([a-zA-Z0-9_ -]*\)[[:space:]]*$/ {
            print without_nvm($0); next
        }
        language == "fish" && /^[[:space:]]*nvm use (--silent )?default[[:space:]]*$/ {
            print "# env-setup-wsl.sh disabled: " $0; next
        }
        language != "fish" {
            if ($0 ~ /^[[:space:]]*(\[ [!-]*[[:space:]]*-[rs] "\$NVM_DIR\/(nvm.sh|bash_completion)" \] (&&|\|\|) )?(source|[.]|\\[.]) "\$NVM_DIR\/(nvm.sh|bash_completion)"([[:space:]]*;|[[:space:]]*(#.*)?$)/) {
                sub(/^[[:space:]]*(\[ [!-]*[[:space:]]*-[rs] "\$NVM_DIR\/(nvm.sh|bash_completion)" \] (&&|\|\|) )?(source|[.]|\\[.]) "\$NVM_DIR\/(nvm.sh|bash_completion)"/, ":")
                if ($0 ~ /(source|[.]|\\[.]) "\$NVM_DIR\/(nvm.sh|bash_completion)"/) {
                    print "请手动检查同一行的多个 nvm 加载：" original ":" FNR > "/dev/stderr"
                    unresolved=1
                }
                print "# env-setup-wsl.sh disabled nvm invocation"
                print; next
            }

        }
        /nvm[.]sh|nvm use|plugins.*nvm|NVM_DIR.*bash_completion|[.]nvm\/versions|NVM_DIR.*versions/ {
            print "请手动检查 nvm 自定义加载：" original ":" FNR ": " $0 > "/dev/stderr"
            unresolved=1
        }
        { print }
        END {
            if (in_plugins) {
                print "请手动检查未闭合的 Zsh 插件列表：" original > "/dev/stderr"
                unresolved=1
            }
            if (unresolved) exit 1
        }
    ' "$file" >"$staging" || result=$?
    if [ "$result" -eq 0 ]; then cat "$staging" >"$file" || result=$?; fi
    rm -f -- "$staging"
    return "$result"
}

migrate_node_environment() (
    local language file target staging directory command failed=0
    check_npm_prefix
    # Validate all three configurations before writing any of them.
    local -a targets=() staged=()
    trap 'for staging in "${staged[@]}"; do rm -f -- "$staging"; done' EXIT
    for language in bash zsh fish; do
        file="$HOME/.${language}rc"
        if [ "$language" = fish ]; then file="${XDG_CONFIG_HOME:-$HOME/.config}/fish/config.fish"; fi
        [ -e "$file" ] || [ -L "$file" ] || continue
        target=$(readlink -f -- "$file") || return 1
        [ -f "$target" ] || return 1
        for file in "${targets[@]}"; do
            if [ "$file" = "$target" ]; then
                printf '错误：多个 shell 共用配置，保留原文件：%s\n' "$target" >&2
                return 1
            fi
        done
        directory=${target%/*}
        staging=$(mktemp "$directory/.node-migration.XXXXXX")
        staged+=("$staging") targets+=("$target")
        cp -p -- "$target" "$staging"
        # Invoke outside a conditional to retain errexit for staged-file operations.
        disable_nvm_startup "$staging" "$language" "$target"
        if ! cmp -s "$target" "$staging"; then
            command=$(type -P "$language") || { printf '错误：需要 %s 检查迁移配置，请安装后重试。\n' "$language" >&2; return 1; }
            "$command" -n "$staging"
        fi
    done
    # Back up every changed file before committing any shell configuration.
    local id
    for id in "${!targets[@]}"; do
        target=${targets[id]} staging=${staged[id]}
        if ! cmp -s "$target" "$staging"; then
            backup_shell_config "$target" "${target%/*}" "${target##*/}" || return 1
        fi
    done
    if [ "$(PATH="$SYSTEM_NODE_DIR:$PATH" "$SYSTEM_NODE_DIR/npm" config get prefix)" != "$HOME/.local" ]; then
        if [ -f "$HOME/.npmrc" ]; then
            backup_shell_config "$HOME/.npmrc" "$HOME" .npmrc || return 1
        fi
        PATH="$SYSTEM_NODE_DIR:$PATH" "$SYSTEM_NODE_DIR/npm" config set prefix "$HOME/.local" --location=user
        [ "$(PATH="$SYSTEM_NODE_DIR:$PATH" "$SYSTEM_NODE_DIR/npm" config get prefix)" = "$HOME/.local" ]
        printf '回退 npm prefix：先恢复已有 .npmrc 的备份；若此前没有配置，运行 npm config delete prefix --location=user。\n'
    fi
    for id in "${!targets[@]}"; do
        target=${targets[id]} staging=${staged[id]}
        if ! cmp -s "$target" "$staging"; then
            if ! mv -- "$staging" "$target"; then failed=1; fi
        fi
    done
    return "$failed"
)

report_installed_versions() (
    printf '\n可用工具版本\n'
    local command shell_environment
    if [ "${STEP_STATES[STEP_BREW]:-}" = '成功' ] || [ "${STEP_STATES[STEP_LAZY_BREW]:-}" = '成功' ]; then
        if shell_environment=$(brew shellenv bash); then eval "$shell_environment"; fi
    fi
    if [ "${STEP_STATES[STEP_NODE]:-}" = '成功' ]; then export PATH="$SYSTEM_NODE_DIR:$PATH"; fi
    for command in git brew eza lazygit starship uv node npm; do
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
    for id in "${!PLUGIN_NAMES[@]}"; do
        step=$((STEP_PLUGIN_BASE + id))
        label="Zsh 插件 ${PLUGIN_NAMES[id]}"
        if [ "${PLUGIN_SELECTED[id]}" -eq 0 ]; then
            skip_step "$step" "$label" '用户未选择'
        elif [ "${STEP_STATES[STEP_OMZ]}" != '成功' ] ||
            { [ "$id" -eq "$PLUGIN_FZF" ] && [ "${STEP_STATES[STEP_FZF]}" != '成功' ]; }; then
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

readonly PLUGIN_FZF=3 PLUGIN_HIGHLIGHT=5
PLUGIN_NAMES=(git copypath z fzf zsh-autosuggestions zsh-syntax-highlighting extract)
PLUGIN_SELECTED=(1 1 1 1 1 1 1)

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
        if [ "$focus" -eq 7 ]; then printf '%s> ' "$FOCUS"; else printf '  '; fi
        printf '继续%s\n方向键移动 · 空格勾选 · 回车继续 · b 返回组件 · q 取消\n' "$RESET"
        IFS= read -rsn1 key || return 1
        case "$key" in
        $'\e')
            IFS= read -rsn2 -t 0.2 key || :
            case "$key" in '[A') focus=$(((focus + 7) % 8)) ;; '[B') focus=$(((focus + 1) % 8)) ;; esac ;;
        ' ') if [ "$focus" -lt 7 ]; then PLUGIN_SELECTED[focus]=$((1 - PLUGIN_SELECTED[focus])); fi ;;
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
        for id in 0 1 2; do
            case "$id" in 0) label=Fish ;; 1) label=Zsh ;; 2) label=Bash ;; esac
            if [ "$focus" -eq "$id" ]; then printf '%s> ' "$FOCUS"; else printf '  '; fi
            printf '%s%s%s\n' "$CYAN" "$label" "$RESET"
        done
        printf '方向键移动 · 回车选择 · q 取消\n'
        IFS= read -rsn1 key || return 1
        case "$key" in
        $'\e')
            IFS= read -rsn2 -t 0.2 key || :
            case "$key" in '[A') focus=$(((focus + 2) % 3)) ;; '[B') focus=$(((focus + 1) % 3)) ;; esac ;;
        '')
            case "$focus" in 0) SHELL_NAME=fish SHELL_LABEL=Fish ;; 1) SHELL_NAME=zsh SHELL_LABEL=Zsh ;; 2) SHELL_NAME=bash SHELL_LABEL=Bash ;; esac
            SHELL_RC="$HOME/.$SHELL_NAME"rc
            if [ "$SHELL_NAME" = fish ]; then SHELL_RC="${XDG_CONFIG_HOME:-$HOME/.config}/fish/config.fish"; fi
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
    for id in 0 1 2 "$PLUGIN_FZF" 4 6 "$PLUGIN_HIGHLIGHT"; do
        name=${PLUGIN_NAMES[id]} step=$((STEP_PLUGIN_BASE + id))
        if [ "${PLUGIN_SELECTED[id]}" -eq 0 ] || [ "${STEP_STATES[step]}" = '成功' ]; then
            begin_component_config "plugin-$name" "$block"
            printf 'plugins=("${(@)plugins:#%s}")\n' "$name" >>"$block"
            if [ "${PLUGIN_SELECTED[id]}" -eq 1 ]; then
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
}

prepare_prompt_config() (
    local file="$1" original="$2" staging keep_theme=0
    if [ "${SELECTED[5]}" -eq 1 ] && [ -f "$original" ] &&
        grep -Fqx '# >>> env-setup-wsl.sh prompt-theme >>>' "$original"; then keep_theme=1; fi
    # Preserve an existing prompt on installation failure, including legacy blocks.
    if [ "${STEP_STATES[STEP_STARSHIP]:-}" = '成功' ]; then
        remove_managed_block "$WT_HOOK_START" "$WT_HOOK_END" "$file"
        begin_component_config starship "$file"
        if ! active_line_contains "starship init $SHELL_NAME" "$file"; then
            printf 'if [ -z "${_ENV_SETUP_WSL_STARSHIP_LOADED:-}" ]; then\n    eval "$(starship init %s)"\n    _ENV_SETUP_WSL_STARSHIP_LOADED=1\nfi\n' "$SHELL_NAME" >>"$file"
        fi
        end_component_config starship "$file"
    elif [ "${SELECTED[5]}" -eq 0 ]; then
        remove_managed_block "$WT_HOOK_START" "$WT_HOOK_END" "$file"
        remove_managed_block '# >>> env-setup-wsl.sh starship >>>' '# <<< env-setup-wsl.sh starship <<<' "$file"
    fi
    if [ "$SHELL_NAME" = zsh ] && { [ "${STEP_STATES[STEP_STARSHIP]:-}" = '成功' ] || [ "${SELECTED[5]}" -eq 0 ] || [ "$keep_theme" -eq 1 ]; }; then
        remove_managed_block '# >>> env-setup-wsl.sh prompt-theme >>>' '# <<< env-setup-wsl.sh prompt-theme <<<' "$file"
        if [ "${STEP_STATES[STEP_STARSHIP]:-}" = '成功' ] || [ "$keep_theme" -eq 1 ]; then
            # Insert immediately before framework loading, after user theme assignments.
            staging=$(mktemp "${file}.prompt.XXXXXX")
            local cleanup_command
            printf -v cleanup_command 'rm -f -- %q' "$staging"
            # shellcheck disable=SC2064
            trap "$cleanup_command" EXIT
            if ! awk '
                $0 !~ /^[[:space:]]*#/ && /(^|[;&|[:space:]])(source|[.]|\\[.])[[:space:]]+[^#]*oh-my-zsh\.sh/ {
                    print "# >>> env-setup-wsl.sh prompt-theme >>>"
                    print "ZSH_THEME=\"\""
                    print "# <<< env-setup-wsl.sh prompt-theme <<<"
                }
                { print }
            ' "$file" >"$staging"; then rm -f -- "$staging"; return 1; fi
            cat "$staging" >"$file"
            rm -f -- "$staging"
        fi
    fi
    # A legacy hook already owns its registration when Starship failed to update.
    if active_line_contains '__wt_update_cwd' "$file"; then return 0; fi
    begin_component_config cwd "$file"
    cat >>"$file" <<'HOOK'
__env_setup_wsl_update_cwd() {
    local windows_path
    command -v wslpath >/dev/null 2>&1 || return 0
    windows_path=$(wslpath -w "$PWD") || return 0
    printf '\e]9;9;%s\e\\' "$windows_path"
}
HOOK
    if [ "$SHELL_NAME" = bash ]; then
        cat >>"$file" <<'HOOK'
if [[ $(declare -p PROMPT_COMMAND 2>/dev/null) == 'declare -a '* ]]; then
    if [[ ! " ${PROMPT_COMMAND[*]} " == *' __env_setup_wsl_update_cwd '* ]]; then
        PROMPT_COMMAND+=(__env_setup_wsl_update_cwd)
    fi
else
    case $'\n'"${PROMPT_COMMAND:-}"$'\n' in
    *$'\n__env_setup_wsl_update_cwd\n'*) ;;
    *) PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND$'\n'}__env_setup_wsl_update_cwd" ;;
    esac
fi
HOOK
    else
        cat >>"$file" <<'HOOK'
typeset -ga precmd_functions
if (( ! ${precmd_functions[(Ie)__env_setup_wsl_update_cwd]} )); then
    precmd_functions+=(__env_setup_wsl_update_cwd)
fi
HOOK
    fi
    end_component_config cwd "$file"
)

prepare_fish_config() (
    local target directory temporary_file other_rc
    if [ -L "$SHELL_RC" ] && [ ! -e "$SHELL_RC" ]; then
        printf '错误：配置符号链接的目标不存在，保留原链接。\n' >&2
        return 1
    fi
    mkdir -p -- "$(dirname -- "$SHELL_RC")"
    target=$(readlink -f -- "$SHELL_RC")
    for other_rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
        if [ "$SHELL_RC" -ef "$other_rc" ]; then
            printf '错误：多个 shell 共用同一个配置文件，保留原文件。\n' >&2
            return 1
        fi
    done
    [ ! -e "$target" ] || [ -f "$target" ] || return 1
    directory=$(dirname -- "$target")
    temporary_file=$(mktemp "$directory/.config.fish.tmp.XXXXXX")
    trap 'rm -f -- "$temporary_file"' EXIT
    [ ! -f "$target" ] || cp -p -- "$target" "$temporary_file"
    remove_managed_block "$SHELL_BLOCK_START" "$SHELL_BLOCK_END" "$temporary_file"
    printf '%s\n# 目标 shell：Fish；此块由环境安装向导管理。\n' "$SHELL_BLOCK_START" >>"$temporary_file"
    if [ -f "$target" ]; then
        awk -v start="$SHELL_BLOCK_START" -v end="$SHELL_BLOCK_END" '$0==start {inside=1;next} $0==end {inside=0;next} inside && $0 !~ /^# 目标 shell/ {print}' "$target" >>"$temporary_file"
    fi
    begin_component_config fish-base "$temporary_file"
    cat >>"$temporary_file" <<'FISH'
fish_add_path --global "$HOME/.local/bin"
set -gx EDITOR 'code --wait'
set -gx VISUAL 'code --wait'
if status is-interactive
    alias ll 'ls'
    alias grep 'grep --color=auto'
    alias .. 'cd ..'
    alias ... 'cd ../..'
    alias mk 'make -j'
    alias ml 'make load'
    alias mc 'make clean'
    if type -q direnv
        direnv hook fish | source
    end
    if set -q WSL_DISTRO_NAME; and type -q wslpath
        function __env_setup_wsl_update_cwd --on-event fish_prompt
            set -l windows_path (wslpath -w "$PWD" 2>/dev/null)
            or return
            printf '\e]9;9;%s\e\\' "$windows_path"
        end
    end
end
FISH
    end_component_config fish-base "$temporary_file"
    if [ "${STEP_STATES[STEP_BREW]:-}" = '成功' ] || [ "${STEP_STATES[STEP_LAZY_BREW]:-}" = '成功' ]; then
        local brew_path
        brew_path=$(type -P brew)
        # Fish escaping is performed by fish rather than Bash printf %q.
        begin_component_config homebrew "$temporary_file"
        "$SHELL_PATH" --no-config -c 'printf "%s shellenv fish | source\n" (string escape -- $argv[1])' -- "$brew_path" >>"$temporary_file"
        end_component_config homebrew "$temporary_file"
    fi
    if [ "${STEP_STATES[STEP_BREW]:-}" = '成功' ]; then
        begin_component_config eza "$temporary_file"
        printf '%s\n' 'if status is-interactive' '    alias ls "eza -al --git --group-directories-first --icons=auto"' '    alias la "eza -alG --git --group-directories-first --icons=auto"' end >>"$temporary_file"
        end_component_config eza "$temporary_file"
    fi
    if [ "${STEP_STATES[STEP_FZF]:-}" = '成功' ]; then
        begin_component_config fzf "$temporary_file"
        cat >>"$temporary_file" <<'FISH'
if status is-interactive
    if fzf --help | string match -q '*--fish*'
        fzf --fish | source
    else if test -r /usr/share/doc/fzf/examples/key-bindings.fish
        source /usr/share/doc/fzf/examples/key-bindings.fish
        fzf_key_bindings
    else if test -r /usr/share/fish/vendor_functions.d/fzf_key_bindings.fish
        source /usr/share/fish/vendor_functions.d/fzf_key_bindings.fish
        fzf_key_bindings
    end
end
FISH
        end_component_config fzf "$temporary_file"
    fi
    if [ "${STEP_STATES[STEP_STARSHIP]:-}" = '成功' ]; then
        begin_component_config starship "$temporary_file"
        printf '%s\n' 'if status is-interactive' '    starship init fish | source' end >>"$temporary_file"
        end_component_config starship "$temporary_file"
    elif [ "${SELECTED[5]}" -eq 0 ]; then
        remove_managed_block '# >>> env-setup-wsl.sh starship >>>' '# <<< env-setup-wsl.sh starship <<<' "$temporary_file"
    fi
    printf '%s\n' "$SHELL_BLOCK_END" >>"$temporary_file"
    "$SHELL_PATH" -n "$temporary_file"
    if [ -f "$target" ] && cmp -s "$target" "$temporary_file"; then return 0; fi
    if [ -f "$target" ]; then
        chmod --reference="$target" "$temporary_file"
        backup_shell_config "$target" "$directory" "${target##*/}" || return 1
    fi
    mv -- "$temporary_file" "$target"
)

prepare_shell_config() (
    if [ "$SHELL_NAME" = fish ]; then prepare_fish_config; return; fi
    local target directory filename temporary_file cleanup_command
    if [ -L "$SHELL_RC" ] && [ ! -e "$SHELL_RC" ]; then
        printf '错误：配置符号链接的目标不存在，保留原链接。\n' >&2
        return 1
    fi
    local fish_rc="${XDG_CONFIG_HOME:-$HOME/.config}/fish/config.fish"
    if [ "$SHELL_RC" -ef "$fish_rc" ]; then
        printf '错误：多个 shell 共用同一个配置文件，保留原文件。\n' >&2
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
        [ "${STEP_STATES[STEP_STARSHIP]:-}" = '成功' ]; then
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
    if [ "$SHELL_NAME" = bash ] && [ "${STEP_STATES[STEP_FZF]:-}" = '成功' ]; then
        begin_component_config fzf "$temporary_file"
        cat >>"$temporary_file" <<'FZF'
if fzf --help | grep -q -- '--bash'; then
    eval "$(fzf --bash)"
elif [ -r /usr/share/doc/fzf/examples/key-bindings.bash ]; then
    source /usr/share/doc/fzf/examples/key-bindings.bash
fi
FZF
        end_component_config fzf "$temporary_file"
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
    prepare_prompt_config "$temporary_file" "$target"
    "$SHELL_PATH" -n "$temporary_file"
    if [ -f "$target" ] && cmp -s "$target" "$temporary_file"; then
        return 0
    fi
    if [ -f "$target" ]; then
        chmod --reference="$target" "$temporary_file"
        backup_shell_config "$target" "$directory" "$filename" || return 1
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

COMPONENT_LABELS=('系统基础包' 'Homebrew/eza' 'lazygit' 'uv/Python' 'Node.js/npm（apt）' 'Starship' 'fzf')
EXPLICIT=(1 1 1 1 1 1 1)
SELECTED=(1 1 1 1 1 1 1)
COMPONENT_STEPS=(1 "$STEP_BREW" "$STEP_LAZYGIT" "$STEP_UV" "$STEP_NODE" "$STEP_STARSHIP" "$STEP_FZF")

needs_system_packages() {
    case "$1" in
    1) ! command_exists brew && { ! command_exists curl || ! command_exists git || ! command_exists make; } ;;
    2) ! command_exists lazygit && ! command_exists brew && { ! command_exists curl || ! command_exists git || ! command_exists make; } ;;
    3) ! command_exists uv && ! command_exists curl ;;
    4) return 1 ;; # NodeSource prepares its own apt prerequisites without removal.
    5) ! command_exists starship && ! command_exists curl ;;
    6) ! command_exists fzf ;;
    *) return 1 ;;
    esac
}

resolve_components() {
    SELECTED=("${EXPLICIT[@]}")
    if [ "$SHELL_NAME" = zsh ] && [ "${PLUGIN_SELECTED[PLUGIN_FZF]}" -eq 1 ]; then SELECTED[6]=1; fi
    local id
    for id in 1 2 3 4 5 6; do
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
                    if [ "$SHELL_NAME" = zsh ] && [ "$focus" -eq 6 ]; then PLUGIN_SELECTED[PLUGIN_FZF]=0; fi
                    if [ "$focus" -eq 0 ]; then
                        for id in 1 2 3 4 5 6; do
                            if [ "${SELECTED[id]}" -eq 1 ] && needs_system_packages "$id"; then
                                EXPLICIT[id]=0
                                if [ "$SHELL_NAME" = zsh ] && [ "$id" -eq 6 ]; then PLUGIN_SELECTED[PLUGIN_FZF]=0; fi
                                notice+="连带取消 ${COMPONENT_LABELS[id]}；"
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
    if [ "${SELECTED[4]}" -eq 1 ]; then
        printf 'Node.js：NodeSource apt 源，固定 %s.x；npm 随附，用户 prefix：%s/.local。\n' "$NODE_VERSION" "$HOME"
        printf '成功后备份并停用 Bash/Zsh/Fish 的可识别 nvm 自动加载；旧文件和工具保留。\n'
        printf 'apt 需要移除现有包、自定义 prefix 或软件源冲突时停止该步骤。\n'
        report_old_node_tools
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
    if [ -n "$SCRIPT_PATH" ]; then
        printf -v rerun_command 'bash %q' "$SCRIPT_PATH"
    else
        printf -v rerun_command 'curl -fsSL %q | bash' "$SETUP_URL"
    fi
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
    run_step "$STEP_USER_BIN" '用户工具目录' "$rerun_command" configure_user_bin
    export PATH="$LOCAL_BIN:$PATH"
    if ! command_exists brew && [ -x "$HOMEBREW_BIN" ]; then
        export PATH="${HOMEBREW_BIN%/*}:$PATH"
    fi
    local step_id installer dependency_failed runtime_command
    if [ -n "$SCRIPT_PATH" ]; then
        printf -v runtime_command 'PYTHON_VERSION=%q NODE_VERSION=%q %s' "$PYTHON_VERSION" "$NODE_VERSION" "$rerun_command"
    else
        # 版本变量属于安装器，必须传给管道右侧的 Bash。
        printf -v runtime_command 'curl -fsSL %q | PYTHON_VERSION=%q NODE_VERSION=%q bash' "$SETUP_URL" "$PYTHON_VERSION" "$NODE_VERSION"
    fi
    for component_id in 1 2 3 4 5 6; do
        step_id=${COMPONENT_STEPS[component_id]}
        case "$component_id" in
        1) installer=install_homebrew ;;
        2) installer=install_lazygit ;;
        3) installer=install_uv ;;
        4) installer=install_node ;;
        5) installer=install_starship ;;
        6) installer=install_fzf ;;
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
    if [ "${STEP_STATES[STEP_NODE]:-}" = '成功' ]; then
        export PATH="$SYSTEM_NODE_DIR:$PATH"
        run_step "$STEP_NODE_MIGRATION" 'npm 目录 / nvm 启动迁移' "$rerun_command" migrate_node_environment
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
    if [ "${STEP_STATES[0]}" = '成功' ] && [ "${STEP_STATES[2]}" = '成功' ] &&
        { [ "${STEP_STATES[STEP_NODE]:-}" != '成功' ] || [ "${STEP_STATES[STEP_NODE_MIGRATION]:-}" = '成功' ]; }; then
        local shell_command
        printf -v shell_command 'chsh -s %q %q' "$SHELL_PATH" "$ACCOUNT_NAME"
        run_step 3 '默认 shell 切换' "$shell_command" change_default_shell
    elif [ "${STEP_STATES[STEP_NODE]:-}" = '成功' ] && [ "${STEP_STATES[STEP_NODE_MIGRATION]:-}" != '成功' ]; then
        skip_step 3 '默认 shell 切换' '因依赖失败跳过' "先修复 npm 目录 / nvm 启动迁移（见上方具体错误），再运行：$rerun_command"
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
    if ! [[ "$NODE_VERSION" =~ ^[1-9][0-9]*$ ]]; then
        printf '错误：NODE_VERSION 仅接受主版本号（如 24），不接受 lts/* 或完整版本号。\n' >&2
        return 2
    fi

    # Bash 已解析入口后再切换 stdin，菜单和 sudo 共用控制终端。
    if [ -z "$SCRIPT_PATH" ] && [ ! -t 0 ] && [ -t 1 ]; then
        if ! { exec 0</dev/tty; } 2>/dev/null; then
            printf '错误：安装向导需要交互终端，请在终端中直接运行。\n' >&2
            return 1
        fi
    fi
    run_install
}

# 守卫让脚本可以被 source 进来单独调用某个函数做检查，
# 直接执行时行为不变。
if [ -z "${BASH_SOURCE[0]:-}" ] || [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
    # stdin 可能已切换为终端，退出后不能继续把键盘输入当作脚本读取。
    exit $?
fi
