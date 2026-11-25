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
# Old standalone launchers unpack the statusline link without its target.
if [ "$1" = archive ] && [ -L "$module_dir/../statusline.sh" ] &&
    [ ! -e "$module_dir/../statusline.sh" ]; then
    archive_dir="$module_dir/../../.."
    tar -xzf "$archive_dir/source.tar.gz" -C "$archive_dir" -- \
        skills-main/scripts/statusline/claude-statusline.sh || exit 1
fi
exec python3 -B "$module_dir/main.py" "$1" "$3"
