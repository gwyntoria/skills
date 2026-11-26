#!/usr/bin/env bash

if [[ ${1:-} == -- ]]; then
    shift
fi
if (($# == 0)); then
    printf 'Usage: %s [--] FILE...\n' "${0##*/}" >&2
    exit 2
fi

result=0
if ! command -v markdownlint-cli2 >/dev/null; then
    printf 'markdownlint-cli2 is missing. Install it with:\n  npm install --global markdownlint-cli2\n' >&2
    result=1
fi
files=()
for file in "$@"; do
    if [[ ! -f $file ]]; then
        printf 'Expected a file: %s\n' "$file" >&2
        result=1
        continue
    fi
    [[ $file == /* ]] || file="$PWD/$file"
    files+=("$file")
done

workdir=$(mktemp -d) || exit 1
trap 'rm -rf -- "$workdir"' EXIT
cd -- "$workdir" || exit 1

cat >markdownlint.yaml <<'YAML' || exit 1
ul-style:
  style: dash
line-length: false
no-duplicate-heading:
  siblings_only: true
no-inline-html: false
no-emphasis-as-heading: true
emphasis-style:
  style: asterisk
strong-style:
  style: asterisk
YAML

cat >textlint.json <<'JSON' || exit 1
{
  "rules": {
    "ja-space-between-half-and-full-width": {
      "space": "always",
      "exceptPunctuation": true,
      "lintStyledNode": true
    },
    "zh-half-and-full-width-bracket": {
      "bracket": "mixed"
    }
  }
}
JSON

textlint_available=1
# textlint can return success from --print-config even when rule loading fails.
if ! command -v textlint >/dev/null ||
    ! lint_config=$(textlint --config textlint.json --print-config) ||
    [[ $lint_config != *'"ja-space-between-half-and-full-width"'* ||
        $lint_config != *'"zh-half-and-full-width-bracket"'* ]]; then
    printf '%s\n' 'textlint or a required rule is unavailable. Install them with:' \
        '  npm install --global textlint textlint-rule-ja-space-between-half-and-full-width textlint-rule-zh-half-and-full-width-bracket' >&2
    textlint_available=0
    result=1
fi

for index in "${!files[@]}"; do
    file=${files[index]}
    input="input-$((index + 1)).md"
    printf '%s -> %s\n' "$input" "$file"
    if ! ln -s -- "$file" "$input"; then
        result=1
        continue
    fi
    if command -v markdownlint-cli2 >/dev/null; then
        markdownlint-cli2 --fix --no-globs --config markdownlint.yaml ":$input" || result=1
    fi
    if ((textlint_available)); then
        textlint --fix --config textlint.json "$input" || result=1
    fi
done
exit "$result"
