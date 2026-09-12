#!/usr/bin/env bash

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
SOURCE_ROOT="$REPO/skills"

source_skill_files=()
while IFS= read -r skill_md; do
	source_skill_files+=("$skill_md")
done < <(find "$SOURCE_ROOT" -name SKILL.md -not -path '*/node_modules/*' -print | LC_ALL=C sort)

contains_name() {
	local sought="$1"
	shift
	local candidate

	for candidate in "$@"; do
		if [ "$candidate" = "$sought" ]; then
			return 0
		fi
	done
	return 1
}

if [ "${#source_skill_files[@]}" -gt 0 ]; then
	for skill_md in "${source_skill_files[@]}"; do
		echo "${skill_md#"$REPO"/}"
	done
fi

echo
echo "Audit:"
echo "  source skills: ${#source_skill_files[@]}"

source_names=()
audit_failed=0

if [ "${#source_skill_files[@]}" -gt 0 ]; then
	for skill_md in "${source_skill_files[@]}"; do
		source_dir="${skill_md%/SKILL.md}"
		name="${source_dir##*/}"
		if [ "${#source_names[@]}" -gt 0 ] && contains_name "$name" "${source_names[@]}"; then
			echo "  duplicate source skill: $name"
			audit_failed=1
		else
			source_names+=("$name")
		fi
	done
fi

if [ "$audit_failed" -ne 0 ]; then
	echo "  status: FAILED"
	exit 1
fi

echo "  status: ok"
