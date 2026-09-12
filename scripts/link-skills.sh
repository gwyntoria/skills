#!/usr/bin/env bash

set -euo pipefail
# NOTE: This is a dev-only script, intended for use by maintainers of this repo.
# It is not a supported installer. Modifications to it — or requests for
# modifications — will not be approved.
#
# Links all skills in the repository into ~/.agents/skills by default.
# Pass --skill NAME to link only one skill. Pass --claude to also link skills
# into ~/.claude/skills.
# Each entry is a symlink into this repo, so a `git pull` is all that's needed
# to keep installed skills up to date.

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
# Tests can isolate link destinations without changing the maintainer's home.
LINK_HOME="${SKILLS_LINK_HOME:-$HOME}"
AGENTS_DEST="$LINK_HOME/.agents/skills"
mode="agents"
selected_skill=""
usage() {
	echo "usage: $0 [--claude] [--skill NAME]" >&2
}

while [ "$#" -gt 0 ]; do
	case "$1" in
	--claude)
		mode="claude"
		;;
	--skill)
		if [ -n "$selected_skill" ]; then
			echo "error: --skill can only be specified once." >&2
			usage
			exit 2
		fi
		if [ "$#" -lt 2 ] || [ -z "$2" ]; then
			echo "error: --skill requires a skill name." >&2
			usage
			exit 2
		fi
		case "$2" in
		--*)
			echo "error: --skill requires a skill name." >&2
			usage
			exit 2
			;;
		esac
		selected_skill="$2"
		shift
		;;
	*)
		usage
		exit 2
		;;
	esac
	shift
done

case "$mode" in
claude)
	DESTS=("$AGENTS_DEST" "$LINK_HOME/.claude/skills")
	;;
*)
	DESTS=("$AGENTS_DEST")
	;;
esac

ensure_destination_is_safe() {
	local dest="$1"
	local resolved

	if [ ! -L "$dest" ]; then
		return
	fi

	if ! resolved="$(cd -P "$dest" 2>/dev/null && pwd -P)"; then
		echo "error: cannot resolve destination symlink: $dest" >&2
		exit 1
	fi
	case "$resolved" in
	"$REPO" | "$REPO"/*)
		echo "error: $dest is a symlink into this repo ($resolved)." >&2
		echo "Remove it (rm \"$dest\") and re-run." >&2
		exit 1
		;;
	esac
}

# Collect the repo's skills once, link into every destination.
names=()
srcs=()
while IFS= read -r -d '' skill_md; do
	src="$(dirname "$skill_md")"
	name="$(basename "$src")"
	if [ -n "$selected_skill" ] && [ "$name" != "$selected_skill" ]; then
		continue
	fi
	names+=("$name")
	srcs+=("$src")
done < <(find "$REPO/skills" -name SKILL.md -not -path '*/node_modules/*' -not -path '*/deprecated/*' -print0)

if [ -n "$selected_skill" ]; then
	if [ "${#names[@]}" -eq 0 ]; then
		echo "error: skill not found: $selected_skill" >&2
		exit 1
	fi
	if [ "${#names[@]}" -gt 1 ]; then
		echo "error: multiple skills named $selected_skill were found." >&2
		exit 1
	fi
fi

for DEST in "${DESTS[@]}"; do
	# If $DEST is a symlink that resolves into this repo, we'd end up writing the
	# per-skill symlinks back into the repo's own skills/ tree. Detect and bail
	# out instead of polluting the working copy.
	ensure_destination_is_safe "$DEST"

	mkdir -p "$DEST"
	for i in "${!names[@]}"; do
		name="${names[$i]}"
		src="${srcs[$i]}"
		target="$DEST/$name"
		if [ -e "$target" ] && [ ! -L "$target" ]; then
			rm -rf "$target"
		fi
		ln -sfn "$src" "$target"
		echo "linked $name -> $src ($DEST)"
	done
done
