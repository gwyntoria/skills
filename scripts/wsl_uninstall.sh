#!/usr/bin/env bash

set -euo pipefail

# ============================================================
# WSL Ubuntu Development Environment Uninstaller
#
# Removes user-level tools and shell configuration installed by
# setup_wsl.sh. System packages are preserved by default because
# they may have existed before setup_wsl.sh was run.
#
# Optional environment variables:
#   PYTHON_VERSION=3.14       uv-managed Python version to remove
#   REMOVE_APT_PACKAGES=1    Also remove the apt packages
#   ASSUME_YES=1             Skip the UNINSTALL confirmation
# ============================================================

PYTHON_VERSION="${PYTHON_VERSION:-3.14}"
REMOVE_APT_PACKAGES="${REMOVE_APT_PACKAGES:-0}"
ASSUME_YES="${ASSUME_YES:-0}"

if [ -z "${HOME:-}" ] || [ "$HOME" = "/" ]; then
    echo "Error: HOME is empty or unsafe."
    exit 1
fi

if [ "$EUID" -eq 0 ]; then
    echo "Error: do not run this script with sudo or as root."
    exit 1
fi

HOMEBREW_BIN="/home/linuxbrew/.linuxbrew/bin/brew"
NVM_DIR="$HOME/.nvm"

log() {
    printf '\n\033[1;34m==> %s\033[0m\n' "$1"
}

success() {
    printf '\033[1;32m✓ %s\033[0m\n' "$1"
}

warn() {
    printf '\033[1;33m! %s\033[0m\n' "$1"
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

printf '%s\n' \
    "This script will remove:" \
    "  - nvm and every Node.js version installed under ~/.nvm" \
    "  - uv binaries and uv-managed Python ${PYTHON_VERSION}" \
    "  - Starship installed at ~/.local/bin/starship" \
    "  - toria-up installed at ~/.local/bin/toria-up" \
    "  - lazygit installed by apt or Homebrew" \
    "  - Homebrew and every package installed through Homebrew" \
    "  - Exact ~/.bashrc lines added by wsl_setup.sh" \
    "" \
    "Codex CLI and all Codex data will be preserved." \
    "apt system packages are preserved by default."

if [ "$ASSUME_YES" != "1" ]; then
    printf '\nType UNINSTALL to continue: '
    confirmation=""
    read -r confirmation || true

    if [ "$confirmation" != "UNINSTALL" ]; then
        warn "Uninstallation cancelled"
        exit 0
    fi
fi

# ------------------------------------------------------------
# 1. nvm and Node.js
# ------------------------------------------------------------

log "Removing nvm and Node.js"

if [ -d "$NVM_DIR" ]; then
    rm -rf -- "$NVM_DIR"
    success "nvm and its Node.js installations removed"
else
    warn "nvm was not found"
fi

# ------------------------------------------------------------
# 2. uv and Python
# ------------------------------------------------------------

log "Removing uv-managed Python ${PYTHON_VERSION} and uv"

if [ -x "$HOME/.local/bin/uv" ]; then
    "$HOME/.local/bin/uv" python uninstall "$PYTHON_VERSION" ||
        warn "uv could not uninstall Python ${PYTHON_VERSION}"

    rm -f -- \
        "$HOME/.local/bin/uv" \
        "$HOME/.local/bin/uvx" \
        "$HOME/.local/bin/uvw"

    success "uv binaries removed"
else
    warn "uv installed at ~/.local/bin was not found"
fi

# ------------------------------------------------------------
# 3. Starship
# ------------------------------------------------------------

log "Removing Starship"

if [ -e "$HOME/.local/bin/starship" ] || [ -L "$HOME/.local/bin/starship" ]; then
    rm -f -- "$HOME/.local/bin/starship"
    success "Starship removed"
else
    warn "Starship installed at ~/.local/bin was not found"
fi

# ------------------------------------------------------------
# 4. lazygit
# ------------------------------------------------------------

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

# ------------------------------------------------------------
# 5. Homebrew
# ------------------------------------------------------------

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

# ------------------------------------------------------------
# 6. Shell configuration
# ------------------------------------------------------------

log "Removing shell configuration"

remove_exact_line 'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"' "$HOME/.bashrc"
remove_exact_line 'export PATH="$HOME/.local/bin:$PATH"' "$HOME/.bashrc"
remove_managed_block \
    '# >>> wsl_setup.sh Windows Terminal CWD hook >>>' \
    '# <<< wsl_setup.sh Windows Terminal CWD hook <<<' \
    "$HOME/.bashrc"
remove_exact_line 'eval "$(starship init bash)"' "$HOME/.bashrc"
remove_exact_line 'starship_precmd_user_func="__wt_update_cwd"' "$HOME/.bashrc"
remove_exact_line 'export NVM_DIR="$HOME/.nvm"' "$HOME/.bashrc"
remove_exact_line '[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"' "$HOME/.bashrc"
remove_exact_line '[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm' "$HOME/.bashrc"
remove_exact_line '[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"' "$HOME/.bashrc"
remove_exact_line '[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion' "$HOME/.bashrc"

rm -f -- "$HOME/.local/bin/toria-up"

rmdir "$HOME/.local/bin" 2>/dev/null || true

success "Shell configuration removed"

# ------------------------------------------------------------
# 7. Optional apt packages
# ------------------------------------------------------------

if [ "$REMOVE_APT_PACKAGES" = "1" ]; then
    log "Removing apt system packages"

    warn "These packages may be used by software unrelated to setup_wsl.sh"

    if sudo apt remove -y \
        git \
        curl \
        wget \
        ca-certificates \
        build-essential \
        procps \
        file \
        unzip \
        zip \
        jq \
        ripgrep \
        fd-find; then
        success "apt system packages removed"
    else
        warn "apt reported an error while removing system packages"
    fi
else
    warn "apt system packages were preserved"
fi

# ------------------------------------------------------------
# Done
# ------------------------------------------------------------

printf '\n'
success "WSL development environment uninstallation completed"

printf '\nRestart your terminal or run:\n\n'
echo "    exec bash"
echo
