#!/usr/bin/env bash

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
PROGRAM_NAME="${SCRIPT_SOURCE:-manage-tools.sh}"
PROGRAM_NAME="${PROGRAM_NAME##*/}"
UPDATE_ALL=0
OPEN_AGENT_SETUP=0
SOURCE_ARCHIVE_URL=https://codeload.github.com/gwyntoria/skills/tar.gz/refs/heads/main
SOURCE_TEMP=""

usage() {
    printf 'Usage: %s [-a | all | -c | config | -h | help]\n' "$PROGRAM_NAME"
    printf '\n'
    printf 'Arguments:\n'
    printf '  -a, all     Also update Claude, Pi and Hermes, including supported plugins and extensions\n'
    printf '  -c, config  Open the Agent configuration menu (requires an interactive terminal)\n'
    printf '  -h, help    Show this help message\n'
    printf '\nDefault: update Skills, Codex (including Plugin Marketplace) and Homebrew.\n'
}

# 解析命令行选项。
# 约定：0 继续执行，1 已打印 usage，2 选项错误。这里不自己 exit，
# 退出码统一由 main 决定。
parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
        -a | all)
            UPDATE_ALL=1
            shift
            ;;
        -c | config)
            OPEN_AGENT_SETUP=1
            shift
            ;;
        -h | help)
            usage
            return 1
            ;;
        *)
            printf 'Error: unknown option: %s\n\n' "$1" >&2
            usage >&2
            return 2
            ;;
        esac
    done

    if [ "$OPEN_AGENT_SETUP" -eq 1 ] && [ "$UPDATE_ALL" -eq 1 ]; then
        printf 'Error: config cannot be combined with all.\n' >&2
        return 2
    fi

    return 0
}

resolve_script_path() {
    local file="$1" directory link hops=0 CDPATH=""
    case "$file" in /*) ;; *) file="./$file" ;; esac
    while [ -L "$file" ]; do
        [ "$hops" -lt 40 ] || {
            printf 'Too many script symlinks\n' >&2
            return 1
        }
        hops=$((hops + 1))
        directory="$(cd -P -- "$(dirname "$file")" && pwd -P)" || return 1
        link="$(readlink "$file")" || return 1
        case "$link" in /*) file="$link" ;; *) file="$directory/$link" ;; esac
    done
    directory="$(cd -P -- "$(dirname "$file")" && pwd -P)" || return 1
    printf '%s/%s\n' "$directory" "${file##*/}"
}

load_remote_source() {
    local command
    for command in curl tar; do
        if ! command -v "$command" >/dev/null 2>&1; then
            printf 'Error: required command not found: %s\n' "$command" >&2
            return 1
        fi
    done

    SOURCE_TEMP="$(mktemp -d)" || return 1
    trap 'rm -rf -- "$SOURCE_TEMP"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'exit 129' HUP

    printf 'Fetching manage-tools from GitHub main...\n' >&2
    curl -fLsS "$SOURCE_ARCHIVE_URL" -o "$SOURCE_TEMP/source.tar.gz" || return 1
    # Extract the module tree and the resources it uses from the same snapshot.
    tar -xzf "$SOURCE_TEMP/source.tar.gz" -C "$SOURCE_TEMP" -- \
        skills-main/scripts/manage-tools skills-main/rules \
        skills-main/scripts/statusline.sh || return 1
    MODULE_ENTRY="$SOURCE_TEMP/skills-main/scripts/manage-tools/main.sh"
    if [ ! -f "$MODULE_ENTRY" ]; then
        printf 'Error: manage-tools entry missing from the downloaded archive.\n' >&2
        return 1
    fi
}

main() {
    local parse_rc mode=default script_path input_fd=0 MODULE_ENTRY=""
    parse_args "$@"
    parse_rc=$?
    case "$parse_rc" in
    0) ;;
    1) return 0 ;;
    *) return 2 ;;
    esac
    if [ "${BASH_VERSINFO[0]:-0}" -lt 5 ]; then
        printf 'Error: manage-tools requires Bash 5.x or later.\n' >&2
        return 2
    fi

    if [ "$OPEN_AGENT_SETUP" -eq 1 ]; then
        mode=config
        if [ -z "$SCRIPT_SOURCE" ] && [ ! -t 0 ] && [ -t 1 ]; then
            # Give the menu a terminal while Bash keeps reading the launcher from its pipe.
            { exec {input_fd}</dev/tty; } 2>/dev/null || true
        fi
        if [ ! -t "$input_fd" ] || [ ! -t 1 ]; then
            printf 'Error: Agent configuration requires an interactive terminal.\n' >&2
            return 2
        fi
    elif [ "$UPDATE_ALL" -eq 1 ]; then
        mode=all
    fi

    if [ -n "$SCRIPT_SOURCE" ]; then
        script_path="$(resolve_script_path "$SCRIPT_SOURCE")" || return 1
        MODULE_ENTRY="${script_path%/*}/manage-tools/main.sh"
    fi
    if [ -f "$MODULE_ENTRY" ]; then
        exec "$BASH" "$MODULE_ENTRY" local "$mode" "$SOURCE_ARCHIVE_URL" <&"$input_fd"
    fi
    load_remote_source || return 1
    "$BASH" "$MODULE_ENTRY" archive "$mode" "$SOURCE_ARCHIVE_URL" <&"$input_fd"
}

main "$@"
