#!/usr/bin/env bash

set -euo pipefail
# NOTE: This is a dev-only script, intended for use by maintainers of this repo.
# It is not a supported installer. Modifications to it — or requests for
# modifications — will not be approved.
#
# Links skills in the repository into ~/.agents/skills by default.
# Pass --skill NAME to link only that skill, and --domain NAME to link only the
# skills under skills/NAME. Either flag takes every following name up to the
# next flag, and may be repeated, so --domain work --domain writing and
# --domain work writing are the same thing. They may be combined, in which case
# only the named skills are linked and each must live under one of the given
# domains. Pass --claude to also link into ~/.claude/skills.
# Pass --remove to unlink the selected skills instead, and --prune to also
# unlink repo symlinks that are not selected. Both only ever touch symlinks
# that resolve into this repo: a real directory or a symlink pointing elsewhere
# is reported as skipped and left alone.
# Each entry is a symlink into this repo, so a `git pull` is all that's needed
# to keep installed skills up to date, and re-running is safe: an entry that
# already serves the right source is reported and left untouched.

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
# Tests can isolate link destinations without changing the maintainer's home.
LINK_HOME="${SKILLS_LINK_HOME:-$HOME}"
AGENTS_DEST="$LINK_HOME/.agents/skills"
SOURCE_ROOT="$REPO/skills"
mode="agents"
remove=false
prune=false
selected_skills=()
selected_domains=()

contains() {
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

available_domains() {
	local dir
	local list=""

	# The wildcard stays literal when there is no match, which is not a directory.
	for dir in "$SOURCE_ROOT"/*/; do
		if [ -d "$dir" ] && [ "$(basename "$dir")" != "deprecated" ]; then
			list+="${list:+ }$(basename "$dir")"
		fi
	done
	echo "$list"
}

usage() {
	cat >&2 <<EOF
usage: $0 [--claude] [--skill NAME...] [--domain NAME...] [--remove | --prune]

  --skill, -s NAME...   select the named skills; one or more names
  --domain, -d NAME...  select the skills under skills/NAME; one or more
  --claude              also operate on ~/.claude/skills
  --remove              unlink the selected skills instead of linking them
  --prune               also unlink repo symlinks that are not selected

Either flag takes every following name up to the next flag, and may repeat.
With no selection every skill is selected, so a bare run links all of them and
a bare --prune removes nothing. --domain and --skill combine: each named skill
must live under one of the given domains. Removal only ever touches symlinks
that resolve into this repo.

examples:
  link-skills.sh -d dialog writing --claude
  link-skills.sh --remove -s changelog
  link-skills.sh --prune -d dialog writing --claude
EOF
}

while [ "$#" -gt 0 ]; do
	case "$1" in
	--claude)
		mode="claude"
		;;
	--remove)
		remove=true
		;;
	--prune)
		prune=true
		;;
	--skill | -s)
		consumed=0
		# Take every following argument up to the next flag, so -s a b works
		# as well as -s a -s b.
		while [ "$#" -ge 2 ] && [ -n "$2" ]; do
			case "$2" in
			-*)
				break
				;;
			esac
			selected_skills+=("$2")
			consumed=$((consumed + 1))
			shift
		done
		if [ "$consumed" -eq 0 ]; then
			echo "error: --skill requires a skill name." >&2
			usage
			exit 2
		fi
		;;
	--domain | -d)
		consumed=0
		while [ "$#" -ge 2 ] && [ -n "$2" ]; do
			case "$2" in
			-*)
				break
				;;
			*/* | .*)
				echo "error: invalid domain: $2" >&2
				usage
				exit 2
				;;
			esac
			if [ ! -d "$SOURCE_ROOT/$2" ]; then
				echo "error: unknown domain: $2" >&2
				echo "available domains: $(available_domains)" >&2
				exit 1
			fi
			selected_domains+=("$2")
			consumed=$((consumed + 1))
			shift
		done
		if [ "$consumed" -eq 0 ]; then
			echo "error: --domain requires a domain name." >&2
			usage
			exit 2
		fi
		;;
	*)
		usage
		exit 2
		;;
	esac
	shift
done

if [ "$remove" = true ] && [ "$prune" = true ]; then
	echo "error: --remove and --prune cannot be combined." >&2
	usage
	exit 2
fi

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

# Collect the repo's skills once, keeping only the requested domain and skill.
names=()
srcs=()
while IFS= read -r -d '' skill_md; do
	src="$(dirname "$skill_md")"
	name="$(basename "$src")"
	domain="$(basename "$(dirname "$src")")"
	if [ "${#selected_domains[@]}" -gt 0 ] && ! contains "$domain" "${selected_domains[@]}"; then
		continue
	fi
	if [ "${#selected_skills[@]}" -gt 0 ] && ! contains "$name" "${selected_skills[@]}"; then
		continue
	fi
	names+=("$name")
	srcs+=("$src")
done < <(find "$SOURCE_ROOT" -name SKILL.md -not -path '*/node_modules/*' -not -path '*/deprecated/*' -print0)

# Every requested skill must have resolved to exactly one source directory.
# Report all the misses in one pass, so a typo does not take a second run to
# surface, and fail before anything is linked.
if [ "${#selected_skills[@]}" -gt 0 ]; then
	missing=()
	for want in "${selected_skills[@]}"; do
		count=0
		if [ "${#names[@]}" -gt 0 ]; then
			for have in "${names[@]}"; do
				if [ "$have" = "$want" ]; then
					count=$((count + 1))
				fi
			done
		fi
		if [ "$count" -eq 0 ]; then
			missing+=("$want")
		elif [ "$count" -gt 1 ]; then
			echo "error: multiple skills named $want were found." >&2
			exit 1
		fi
	done

	if [ "${#missing[@]}" -gt 0 ]; then
		if [ "${#selected_domains[@]}" -eq 1 ]; then
			domain_word="domain"
		else
			domain_word="domains"
		fi
		domain_list=""
		if [ "${#selected_domains[@]}" -gt 0 ]; then
			for domain in "${selected_domains[@]}"; do
				domain_list+="${domain_list:+, }$domain"
			done
		fi
		for want in "${missing[@]}"; do
			if [ "${#selected_domains[@]}" -gt 0 ]; then
				echo "error: no skill named $want under $domain_word $domain_list." >&2
				# Names are unique repo-wide, so a miss can only live in one place.
				other="$(find "$SOURCE_ROOT" -name SKILL.md -not -path '*/node_modules/*' -not -path '*/deprecated/*' -path "*/$want/SKILL.md" -print -quit)"
				if [ -n "$other" ]; then
					echo "$want is in domain $(basename "$(dirname "$(dirname "$other")")")." >&2
				fi
			else
				echo "error: skill not found: $want" >&2
			fi
		done
		exit 1
	fi
fi

# True when $1 is a symlink that already resolves to the same directory as $2,
# compared after resolving both, so an equivalent link is not rewritten.
resolves_to() {
	local want got

	if ! want="$(cd -P "$2" 2>/dev/null && pwd -P)"; then
		return 1
	fi
	got="$(cd -P "$1" 2>/dev/null && pwd -P)" || return 1
	[ "$got" = "$want" ]
}

# True when $1 is a symlink whose target lives inside this repo, which is the
# only thing the removal paths are allowed to touch. A dangling symlink cannot
# be resolved, so fall back to judging its link text.
resolves_into_repo() {
	local resolved

	resolved="$(cd -P "$1" 2>/dev/null && pwd -P)" || resolved="$(readlink "$1" 2>/dev/null || true)"
	case "$resolved" in
	"$REPO" | "$REPO"/*)
		return 0
		;;
	esac
	return 1
}

skipped=0
for DEST in "${DESTS[@]}"; do
	# If $DEST is a symlink that resolves into this repo, we'd end up writing or
	# deleting entries inside the repo's own skills/ tree. Detect and bail out
	# instead of polluting the working copy.
	ensure_destination_is_safe "$DEST"

	if [ "$remove" = true ]; then
		for i in "${!names[@]}"; do
			name="${names[$i]}"
			target="$DEST/$name"
			if [ ! -e "$target" ] && [ ! -L "$target" ]; then
				echo "not installed $name ($DEST)"
				continue
			fi
			if [ ! -L "$target" ] || ! resolves_into_repo "$target"; then
				echo "skipped $name (not a symlink into this repo) ($DEST)" >&2
				skipped=1
				continue
			fi
			rm -f "$target"
			echo "removed $name ($DEST)"
		done
		continue
	fi

	mkdir -p "$DEST"
	for i in "${!names[@]}"; do
		name="${names[$i]}"
		src="${srcs[$i]}"
		target="$DEST/$name"
		action="linked"
		detail=""
		if [ -L "$target" ]; then
			if resolves_to "$target" "$src"; then
				echo "already linked $name -> $src ($DEST)"
				continue
			fi
			detail=" (was $(readlink "$target"))"
			action="relinked"
			rm -f "$target"
		elif [ -e "$target" ]; then
			detail=" (was not a symlink)"
			action="replaced"
			rm -rf "$target"
		fi
		ln -s "$src" "$target"
		echo "$action $name$detail -> $src ($DEST)"
	done

	if [ "$prune" = true ]; then
		for entry in "$DEST"/*; do
			[ -L "$entry" ] || continue
			name="$(basename "$entry")"
			if [ "${#names[@]}" -gt 0 ] && contains "$name" "${names[@]}"; then
				continue
			fi
			resolves_into_repo "$entry" || continue
			rm -f "$entry"
			echo "removed $name (not selected) ($DEST)"
		done
	fi
done

# A skipped entry means the request could not be carried out fully.
if [ "$skipped" -ne 0 ]; then
	exit 1
fi
