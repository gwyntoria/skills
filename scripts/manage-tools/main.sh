#!/usr/bin/env bash

# Older standalone launchers call this path with <local|archive> config <url>.
if [ "$#" -ne 3 ] || [ "$2" != config ]; then
    printf 'Error: expected a manage-tools config invocation.\n' >&2
    exit 2
fi
if ! command -v python3 >/dev/null 2>&1; then
    printf 'Error: config requires Python 3.10 or later (python3).\n' >&2
    exit 2
fi
module_dir="$(cd -P -- "${BASH_SOURCE[0]%/*}" && pwd -P)" || exit 1
exec python3 -B "$module_dir/main.py" "$1" "$3"
