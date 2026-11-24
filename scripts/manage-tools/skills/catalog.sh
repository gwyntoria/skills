install_agent_skills() (
    local source="$1"
    shift
    local name scope_args=()
    if [ "$INSTALL_SCOPE" = global ]; then
        scope_args=(--global)
    else
        if [ "$PROJECT_TARGET" = / ]; then
            printf 'Error: refusing to use / as a project directory.\n' >&2
            return 1
        fi
        cd -- "$PROJECT_TARGET" || return 1
    fi
    for name in "$@"; do print_skill_targets "$name"; done
    npx --yes skills add "$source" --skill "$@" \
        --agent "${TARGET_AGENTS[@]}" "${scope_args[@]+"${scope_args[@]}"}" --yes
)

# skills add --list is read-only. Restrict parsing to its Available Skills
# section and reject empty/unrecognised output rather than hiding a failure.
fetch_repository_skill_names() {
    local output
    output=$(NO_COLOR=1 npx --yes skills add "$1" --list </dev/null) || return $?
    printf '%s\n' "$output" | run_python "Skills catalog" skills/parse_catalog.py cli
}

fetch_mattpocock_skill_names() (
    set -o pipefail

    curl -fsSL --connect-timeout 10 --max-time 60 "$MATTPOCOCK_SKILLS_PAGE_URL" |
        run_python "Matt Pocock skills catalog" skills/parse_catalog.py homepage
)

skill_source_url() {
    case "$1" in
    Waza) printf '%s\n' "$WAZA_SKILLS_URL" ;;
    Kami) printf '%s\n' "$KAMI_SKILLS_URL" ;;
    'Matt Pocock') printf '%s\n' "$MATTPOCOCK_SKILLS_URL" ;;
    HumanLayer) printf '%s\n' "$HUMANLAYER_SKILLS_URL" ;;
    Gwyntoria) printf '%s\n' "$GWYNTORIA_SKILLS_URL" ;;
    Distilly) printf '%s\n' "$DISTILLY_SKILLS_URL" ;;
    *) return 1 ;;
    esac
}

catalog_report_failure() {
    CATALOG_FAILURES+=("$1")
    FAILED+=("$1")
}

# Set CATALOG_FETCHED_NAMES for one source group. A group is fetched at most
# once per session; the cache survives returning to the main menu so a second
# run never waits on a repository it already pulled.
catalog_fetch_group() {
    local group="$1" source names valid name i
    CATALOG_FETCHED_NAMES=""
    for ((i = 0; i < ${#CATALOG_CACHE_GROUPS[@]}; i++)); do
        if [ "${CATALOG_CACHE_GROUPS[i]}" = "$group" ]; then
            CATALOG_FETCHED_NAMES="${CATALOG_CACHE_NAMES[i]}"
            return 0
        fi
    done
    source="$(skill_source_url "$group")" || return 0
    printf 'Loading %s...\n' "$group" >&2
    names=""
    if [ "$group" = 'Matt Pocock' ]; then
        names=$(fetch_mattpocock_skill_names) || names=""
    elif [ "$group" = HumanLayer ]; then
        names=show-me
    else
        names=$(fetch_repository_skill_names "$source") || names=""
    fi
    if [ -z "$names" ]; then
        CATALOG_CACHE_GROUPS+=("$group")
        CATALOG_CACHE_NAMES+=("")
        catalog_report_failure "Catalog: $group ($source)"
        return 0
    fi
    valid=""
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        if [[ ! "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then
            catalog_report_failure "Catalog: $group (invalid skill name)"
            continue
        fi
        if [ -n "$valid" ]; then valid="$valid"$'\n'; fi
        valid="$valid$name"
    done <<<"$names"
    CATALOG_CACHE_GROUPS+=("$group")
    CATALOG_CACHE_NAMES+=("$valid")
    CATALOG_FETCHED_NAMES="$valid"
}

# Append one source group's skills to the session table, fetching only when
# the cache has no copy yet. An omitted default list selects every skill.
catalog_add_group() {
    local group="$1" defaults="${2-*}" source name i picked
    source="$(skill_source_url "$group")" || return 1
    for ((i = 0; i < ${#SKILL_GROUPS[@]}; i++)); do
        [ "${SKILL_GROUPS[i]}" != "$group" ] || return 0
    done
    catalog_fetch_group "$group"
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        SKILL_NAMES+=("$name")
        SKILL_SOURCES+=("$source")
        SKILL_GROUPS+=("$group")
        picked=0
        if [[ "$defaults" = '*' || " $defaults " = *" $name "* ]]; then picked=1; fi
        SKILL_PICKED+=("$picked")
        SKILL_EXPLICIT+=("$picked")
    done <<<"$CATALOG_FETCHED_NAMES"
}

load_catalog() {
    local group name
    SKILL_NAMES=()
    SKILL_SOURCES=()
    SKILL_GROUPS=()
    SKILL_PICKED=()
    SKILL_EXPLICIT=()
    for group in "${SKILL_SOURCE_GROUPS[@]}"; do
        catalog_add_group "$group"
    done
    for name in "${FAILED[@]+"${FAILED[@]}"}"; do printf 'Unavailable: %s\n' "$name" >&2; done
}

print_catalog() {
    local i previous=""
    for ((i = 0; i < ${#SKILL_NAMES[@]}; i++)); do
        if [ "$previous" != "${SKILL_GROUPS[i]}" ]; then
            previous="${SKILL_GROUPS[i]}"
            list_heading "Skills · $previous"
            printf '%s\n' "${SKILL_SOURCES[i]}"
        fi
        printf '  %s\n' "${SKILL_NAMES[i]}"
    done
}

# Whether a source group is ticked on the repository page.
repo_group_selected() {
    local group="$1" i
    for i in "${SELECTED_REPOS[@]+"${SELECTED_REPOS[@]}"}"; do
        [ "${SKILL_SOURCE_GROUPS[i]}" != "$group" ] || return 0
    done
    return 1
}

# Rebuild the repository/skill picker for the chosen repositories only.
# VIEW_SKILL_INDICES maps picker positions back to SKILL_* indices so
# selection survives adding or dropping a repository between visits.
catalog_build_view() {
    local i pos
    REPO_ITEM_LABELS=()
    REPO_ITEM_GROUPS=()
    REPO_SELECTED=()
    REPO_EXPLICIT=()
    VIEW_SKILL_INDICES=()
    for ((i = 0; i < ${#SKILL_NAMES[@]}; i++)); do
        repo_group_selected "${SKILL_GROUPS[i]}" || continue
        REPO_ITEM_LABELS+=("${SKILL_NAMES[i]}")
        REPO_ITEM_GROUPS+=("${SKILL_SOURCES[i]#https://github.com/}")
        VIEW_SKILL_INDICES+=("$i")
        pos=$((${#VIEW_SKILL_INDICES[@]} - 1))
        REPO_EXPLICIT+=("${SKILL_EXPLICIT[i]}")
        [ "${SKILL_PICKED[i]}" -eq 0 ] || REPO_SELECTED+=("$pos")
    done
}

# Write the picker's selection back into SKILL_PICKED, then refresh the
# install set. Skills outside the view keep their last state.
catalog_sync_selection() {
    local pos i
    for ((pos = 0; pos < ${#VIEW_SKILL_INDICES[@]}; pos++)); do
        i="${VIEW_SKILL_INDICES[pos]}"
        SKILL_PICKED[i]=0
        SKILL_EXPLICIT[i]="${REPO_EXPLICIT[pos]}"
    done
    for pos in "${REPO_SELECTED[@]+"${REPO_SELECTED[@]}"}"; do
        i="${VIEW_SKILL_INDICES[pos]}"
        SKILL_PICKED[i]=1
    done
    catalog_collect_selection
}

# SELECTED_SKILLS is the install set: picked skills from chosen repositories.
catalog_collect_selection() {
    local i
    SELECTED_SKILLS=()
    for ((i = 0; i < ${#SKILL_NAMES[@]}; i++)); do
        [ "${SKILL_PICKED[i]}" -ne 0 ] || continue
        repo_group_selected "${SKILL_GROUPS[i]}" || continue
        SELECTED_SKILLS+=("$i")
    done
}

# Dependency helpers use the picker's local arrays through Bash dynamic scope.
# Keep this table in sync with upstream SKILL.md, not workflow/related links:
# https://github.com/mattpocock/skills
# https://www.aihero.dev/skills
# Include calls in conditional branches so every supported path is available.
matt_skill_dependencies() {
    case "$1" in
    grill-me) printf '%s\n' grilling ;;
    grill-with-docs) printf '%s\n' grilling domain-modeling ;;
    tdd) printf '%s\n' codebase-design ;;
    implement | implement-spec) printf '%s\n' tdd code-review ;;
    wayfinder) printf '%s\n' grilling domain-modeling prototype research ;;
    improve-codebase-architecture) printf '%s\n' codebase-design grilling domain-modeling ;;
    triage) printf '%s\n' grilling domain-modeling ;;
    retro) printf '%s\n' writing-for-agents ;;
    esac
}

picker_dependency_graph() {
    local i j dependency match changed=1
    for ((i = 0; i < ${#selected[@]}; i++)); do
        requirements[i]=" $i "
        missing[i]=''
        [ "${REPO_ITEM_GROUPS[i]}" = mattpocock/skills ] || continue
        while IFS= read -r dependency; do
            [ -n "$dependency" ] || continue
            match=-1
            for ((j = 0; j < ${#selected[@]}; j++)); do
                if [ "${REPO_ITEM_GROUPS[j]}" = mattpocock/skills ] && [ "${REPO_ITEM_LABELS[j]}" = "$dependency" ]; then
                    match="$j"
                    break
                fi
            done
            if [ "$match" -lt 0 ]; then
                missing[i]="$dependency"
            else requirements[i]+="$match "; fi
        done < <(matt_skill_dependencies "${REPO_ITEM_LABELS[i]}")
    done
    # Compute transitive closure once, including missing transitive dependencies.
    # Membership checks also make cycles terminate.
    while [ "$changed" -eq 1 ]; do
        changed=0
        for ((i = 0; i < ${#selected[@]}; i++)); do
            for j in ${requirements[i]}; do
                if [ -z "${missing[i]}" ] && [ -n "${missing[j]}" ]; then
                    missing[i]="${missing[j]}"
                    changed=1
                fi
                for dependency in ${requirements[j]}; do
                    if [[ "${requirements[i]}" != *" $dependency "* ]]; then
                        requirements[i]+="$dependency "
                        changed=1
                    fi
                done
            done
        done
    done
}

picker_resolve_dependencies() {
    local i dependency
    for ((i = 0; i < ${#selected[@]}; i++)); do selected[i]=0; done
    for ((i = 0; i < ${#selected[@]}; i++)); do
        [ "${explicit[i]}" -ne 0 ] || continue
        if [ -n "${missing[i]}" ]; then
            explicit[i]=0
            notice+="Cannot select "$'\033[32m'"${REPO_ITEM_LABELS[i]}"$'\033[0m'": missing dependency "$'\033[32m'"${missing[i]}"$'\033[0m'". "
            continue
        fi
        for dependency in ${requirements[i]}; do selected[dependency]=1; done
    done
}

picker_deselect_dependency() {
    local target="$1" root
    for ((root = 0; root < ${#explicit[@]}; root++)); do
        if [ "${explicit[root]}" -eq 1 ] && [[ "${requirements[root]}" = *" $target "* ]]; then
            explicit[root]=0
            [ "$root" -eq "$target" ] || notice+="Also deselected "$'\033[32m'"${REPO_ITEM_LABELS[root]}"$'\033[0m'". "
        fi
    done
}
