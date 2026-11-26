#!/usr/bin/env bash

config=()
if [[ ${1:-} == --config ]]; then
    if (($# < 2)); then
        printf 'Missing path for --config\n' >&2
        exit 2
    fi
    config=(--config "$2")
    shift 2
fi
if [[ ${1:-} == -- ]]; then
    shift
fi
if (($# == 0)); then
    printf 'Usage: %s [--config PATH] [--] FILE...\n' "${0##*/}" >&2
    exit 2
fi

if ! command -v ruff >/dev/null; then
    printf 'Ruff is missing. Install it with:\n' >&2
    case $OSTYPE in
    darwin*) printf '  brew install ruff\n' >&2 ;;
    msys* | cygwin* | mingw*) printf '  winget install --id astral-sh.ruff -e\n' >&2 ;;
    *) printf '  curl -LsSf https://astral.sh/ruff/install.sh | sh\n' >&2 ;;
    esac
    exit 1
fi

fallback=(--isolated --target-version py310 --line-length 80)
settings_path_pattern=$'\n''Settings path: "([^"]*)(/|\\\\)[^/\\"]+"'
result=0
for file in "$@"; do
    if [[ ! -f $file ]]; then
        printf 'Expected a file: %s\n' "$file" >&2
        result=1
        continue
    fi

    if ((${#config[@]} == 0)); then
        if ! settings=$(ruff check --show-settings --no-force-exclude -- "$file"); then
            result=1
            continue
        fi
        # Ruff resolves user configuration relative to the working directory.
        if [[ ! $settings =~ $settings_path_pattern ||
            $settings != *$'\n'"file_resolver.project_root = \"${BASH_REMATCH[1]:-/}\""$'\n'* ]]; then
            ruff check "${fallback[@]}" --fix --select E,F,W,C90,I --ignore E501,W191 \
                --config 'src = ["scripts/manage-tools/agents", "scripts/manage-tools/content"]' \
                --config 'lint.isort.combine-as-imports = true' \
                --config 'lint.isort.length-sort = true' \
                --config 'lint.isort.lines-after-imports = 2' -- "$file" || result=1
            ruff format "${fallback[@]}" \
                --config 'format.docstring-code-format = true' \
                --config 'format.line-ending = "lf"' -- "$file" || result=1
            continue
        fi
    fi

    ruff check "${config[@]}" --fix -- "$file" || result=1
    ruff format "${config[@]}" -- "$file" || result=1
done
exit "$result"
