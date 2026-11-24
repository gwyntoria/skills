log() { printf '\n==> %s\n' "$1"; }

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

require_python() {
    local feature="$1"
    if ! command -v python3 >/dev/null 2>&1 ||
        ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
        printf 'Error: %s requires Python 3.10 or later (python3).\n' "$feature" >&2
        return 1
    fi
}

run_python() {
    local feature="$1" module="$2"
    shift 2
    require_python "$feature" || return 1
    python3 -B "$MODULE_DIR/$module" "$@"
}
