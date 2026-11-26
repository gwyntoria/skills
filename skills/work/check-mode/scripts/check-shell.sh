#!/usr/bin/env bash

dialect=
indent=4
while (($#)); do
    case $1 in
    --dialect | --indent)
        if (($# < 2)); then
            printf 'Missing value for %s\n' "$1" >&2
            exit 2
        fi
        if [[ $1 == --dialect ]]; then
            dialect=$2
        else
            indent=$2
        fi
        shift 2
        ;;
    --)
        shift
        break
        ;;
    *) break ;;
    esac
done
if (($# == 0)) || [[ ! $indent =~ ^[0-9]+$ || (-n $dialect && $dialect != bash && $dialect != sh) ]]; then
    printf 'Usage: %s [--dialect bash|sh] [--indent SPACES] [--] FILE...\n' "${0##*/}" >&2
    exit 2
fi

result=0
missing=()
for tool in shfmt shellcheck; do
    if ! command -v "$tool" >/dev/null; then
        missing+=("$tool")
        result=1
    fi
done
if ((${#missing[@]})); then
    printf 'Missing tools: %s\n' "${missing[*]}" >&2
    if [[ $OSTYPE == darwin* ]]; then
        printf '  brew install %s\n' "${missing[*]}" >&2
    else
        printf '  Ubuntu/WSL: sudo apt update && sudo apt install %s\n' "${missing[*]}" >&2
    fi
fi

shebang_pattern='^#![[:blank:]]*([^[:blank:]]*/)?(env[[:blank:]]+(-S[[:blank:]]+)?)?(bash|sh|dash)([[:space:]]|$)'
for file in "$@"; do
    if [[ ! -f $file ]]; then
        printf 'Expected a file: %s\n' "$file" >&2
        result=1
        continue
    fi
    [[ $file == /* ]] || file="./$file"
    file_dialect=$dialect
    if [[ -z $file_dialect ]]; then
        IFS= read -r shebang <"$file" || true
        if [[ $shebang =~ $shebang_pattern ]]; then
            file_dialect=${BASH_REMATCH[4]}
        else
            printf 'Specify --dialect bash or --dialect sh for %s\n' "$file" >&2
            result=1
            continue
        fi
    fi
    if [[ $file_dialect == bash ]]; then
        formatter_dialect=bash
    else
        formatter_dialect=posix
    fi

    if command -v shfmt >/dev/null; then
        shfmt -ln "$formatter_dialect" -i "$indent" -w "$file" || result=1
        shfmt -ln "$formatter_dialect" -i "$indent" -d "$file" || result=1
    fi
    if command -v shellcheck >/dev/null; then
        shellcheck -s "$file_dialect" -x "$file" || result=1
    fi
done
exit "$result"
