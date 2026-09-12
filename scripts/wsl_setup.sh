#!/usr/bin/env bash

set -euo pipefail

# ============================================================
# WSL Ubuntu Development Environment Setup
#
# Installs:
#   - Base development tools
#   - Homebrew
#   - Git
#   - lazygit
#   - Starship
#   - uv
#   - Python
#   - nvm
#   - Node.js
#   - Codex CLI
#
# Target:
#   - Ubuntu on WSL
#   - Bash
# ============================================================

PYTHON_VERSION="${PYTHON_VERSION:-3.14}"
NODE_VERSION="${NODE_VERSION:-lts/*}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

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
# 1. Check environment
# ------------------------------------------------------------

log "Checking environment"

if ! grep -qi microsoft /proc/version 2>/dev/null; then
    warn "This script is designed for WSL."
fi

if ! command_exists apt; then
    echo "Error: apt was not found. This script currently supports Ubuntu/Debian."
    exit 1
fi

success "WSL/Ubuntu environment detected"

# ------------------------------------------------------------
# 2. System packages
# ------------------------------------------------------------

log "Checking system packages"

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
MISSING_SYSTEM_PACKAGES=()

for package in "${SYSTEM_PACKAGES[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null |
        grep -Fqx 'install ok installed'; then
        MISSING_SYSTEM_PACKAGES+=("$package")
    fi
done

if [ "${#MISSING_SYSTEM_PACKAGES[@]}" -eq 0 ]; then
    success "System packages already installed"
else
    sudo apt update
    sudo apt install -y "${MISSING_SYSTEM_PACKAGES[@]}"
    success "Missing system packages installed"
fi

# ------------------------------------------------------------
# 3. Homebrew
# ------------------------------------------------------------

log "Checking Homebrew"

HOMEBREW_BIN="/home/linuxbrew/.linuxbrew/bin/brew"

if [ -x "$HOMEBREW_BIN" ]; then
    eval "$("$HOMEBREW_BIN" shellenv)"
    success "Homebrew already installed: $(brew --version | head -n 1)"
else
    NONINTERACTIVE=1 /bin/bash -c \
        "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    eval "$("$HOMEBREW_BIN" shellenv)"
    success "Homebrew installed"
fi

append_once 'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"' "$HOME/.bashrc"

# ------------------------------------------------------------
# 4. Git
# ------------------------------------------------------------

log "Checking Git"

git --version

success "Git installed"

# ------------------------------------------------------------
# 5. lazygit
# ------------------------------------------------------------

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

# ------------------------------------------------------------
# 6. User shell configuration
# ------------------------------------------------------------

log "Configuring user binary directory"

mkdir -p "$HOME/.local/bin"

install -m 0755 "$SCRIPT_DIR/toria-up.sh" "$HOME/.local/bin/toria-up"
success "toria-up installed"

append_once 'export PATH="$HOME/.local/bin:$PATH"' "$HOME/.bashrc"

export PATH="$HOME/.local/bin:$PATH"

success "$HOME/.local/bin configured"

log "Configuring case-insensitive completion"

append_once 'set completion-ignore-case on' "$HOME/.inputrc"

success "$HOME/.inputrc configured"

# ------------------------------------------------------------
# 7. Starship
# ------------------------------------------------------------

log "Installing Starship"

if command_exists starship; then
    success "Starship already installed: $(starship --version)"
else
    curl -sS https://starship.rs/install.sh |
        sh -s -- -y -b "$HOME/.local/bin"

    success "Starship installed"
fi

remove_managed_block \
    '# >>> wsl_setup.sh Windows Terminal CWD hook >>>' \
    '# <<< wsl_setup.sh Windows Terminal CWD hook <<<' \
    "$HOME/.bashrc"
remove_exact_line 'eval "$(starship init bash)"' "$HOME/.bashrc"
remove_exact_line 'starship_precmd_user_func="__wt_update_cwd"' "$HOME/.bashrc"

if ! active_line_contains 'function __wt_update_cwd()' "$HOME/.bashrc"; then
    printf '\n%s\n' \
        '# >>> wsl_setup.sh Windows Terminal CWD hook >>>' \
        'function __wt_update_cwd() {' \
        '    printf '\''\e]9;9;%s\e\\'\'' "$(wslpath -w "$PWD")"' \
        '}' \
        '' \
        'starship_precmd_user_func="__wt_update_cwd"' \
        '' \
        'eval "$(starship init bash)"' \
        '# <<< wsl_setup.sh Windows Terminal CWD hook <<<' \
        >>"$HOME/.bashrc"
else
    append_once 'starship_precmd_user_func="__wt_update_cwd"' "$HOME/.bashrc"
    append_once 'eval "$(starship init bash)"' "$HOME/.bashrc"
fi

# ------------------------------------------------------------
# 8. uv
# ------------------------------------------------------------

log "Installing uv"

if command_exists uv; then
    success "uv already installed: $(uv --version)"
else
    curl -LsSf https://astral.sh/uv/install.sh | sh

    export PATH="$HOME/.local/bin:$PATH"

    success "uv installed"
fi

# ------------------------------------------------------------
# 9. Python
# ------------------------------------------------------------

log "Checking Python ${PYTHON_VERSION}"

if uv python find "$PYTHON_VERSION" >/dev/null 2>&1; then
    success "Python ${PYTHON_VERSION} already installed"
else
    uv python install "$PYTHON_VERSION"
    success "Python ${PYTHON_VERSION} installed"
fi

uv python list --only-installed

# ------------------------------------------------------------
# 10. nvm
# ------------------------------------------------------------

log "Installing nvm"

export NVM_DIR="$HOME/.nvm"

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
    "$HOME/.bashrc"

append_unless_active_line_contains \
    '"$NVM_DIR/nvm.sh"' \
    '[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm' \
    "$HOME/.bashrc"

append_unless_active_line_contains \
    '"$NVM_DIR/bash_completion"' \
    '[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion' \
    "$HOME/.bashrc"

# Load nvm in this script
# shellcheck disable=SC1090
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

# ------------------------------------------------------------
# 11. Node.js
# ------------------------------------------------------------

log "Checking Node.js ${NODE_VERSION}"

NODE_INSTALLED_VERSION="$(nvm version "$NODE_VERSION")"

if [ "$NODE_INSTALLED_VERSION" != "N/A" ]; then
    success "Node.js already installed: $NODE_INSTALLED_VERSION"
else
    nvm install "$NODE_VERSION"
    nvm alias default "$NODE_VERSION"
    nvm use default
    success "Node.js installed: $(node --version)"
    success "npm installed: $(npm --version)"
fi

# ------------------------------------------------------------
# 12. Codex CLI
# ------------------------------------------------------------

log "Checking Codex CLI"

if command_exists codex; then
    success "Codex already installed"
else
    curl -fsSL https://chatgpt.com/codex/install.sh | sh
    success "Codex installed"
fi

# ------------------------------------------------------------
# 13. Verification
# ------------------------------------------------------------

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

# ------------------------------------------------------------
# Done
# ------------------------------------------------------------

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
