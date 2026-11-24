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

# Download only the skill documents from repositories whose assets make a full
# archive disproportionately large.
fetch_tree_skill_names() {
    local repo="${1#https://github.com/}" tree="$LOAD_JOB_DIR/tree.json"
    local paths="$LOAD_JOB_DIR/paths" blob path number=0
    loading_download "https://api.github.com/repos/$repo/git/trees/HEAD?recursive=1" "$tree" 'Downloading tree' || return 1
    run_python 'Skills catalog' skills/parse_catalog.py tree "$tree" >"$paths" || return 1
    while IFS= read -r blob; do
        number=$((number + 1))
        path="$LOAD_JOB_DIR/skill-$number.json"
        loading_download "https://api.github.com/repos/$repo/git/blobs/$blob" "$path" "Downloading SKILL.md ($number)" || return 1
        run_python 'Skills catalog' skills/parse_catalog.py blob "$path" || return 1
    done <"$paths"
    [ "$number" -gt 0 ]
}

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

queue_skill_catalogs() {
    local index group source kind
    CATALOG_LOAD_IDS=()
    for index in "$@"; do
        [ -z "${CATALOG_CACHE_NAMES[index]+loaded}" ] || continue
        group="${SKILL_SOURCE_GROUPS[index]}"
        source="$(skill_source_url "$group")" || return 1
        case "$group" in
        Kami) kind=skill_tree ;;
        'Matt Pocock')
            kind=skill_homepage
            source="$MATTPOCOCK_SKILLS_PAGE_URL"
            ;;
        HumanLayer)
            kind=skill_fixed
            source=show-me
            ;;
        *) kind=skill_archive ;;
        esac
        queue_content_load "$kind" "Skills / $group" "$source"
        CATALOG_LOAD_IDS[index]="$LOADING_INDEX"
    done
}

collect_skill_catalogs() {
    local index job group
    for index in "${!CATALOG_LOAD_IDS[@]}"; do
        job="${CATALOG_LOAD_IDS[index]}"
        if content_load_succeeded "$job" && [ -s "$LOADING_DIR/$job/output" ]; then
            CATALOG_CACHE_NAMES[index]="$(awk '!seen[$0]++' "$LOADING_DIR/$job/output")"
        else
            group="${SKILL_SOURCE_GROUPS[index]}"
            CATALOG_CACHE_NAMES[index]=''
            CATALOG_FAILURES+=("Catalog: $group ($(skill_source_url "$group"))")
            report_content_load_error "$job"
        fi
    done
}

# Append skills in configured order, independent of which download finishes first.
catalog_add_group() {
    local index="$1" defaults="$2" group source name i picked
    group="${SKILL_SOURCE_GROUPS[index]}"
    source="$(skill_source_url "$group")" || return 1
    for ((i = 0; i < ${#SKILL_GROUPS[@]}; i++)); do
        [ "${SKILL_GROUPS[i]}" != "$group" ] || return 0
    done
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        SKILL_NAMES+=("$name")
        SKILL_SOURCES+=("$source")
        SKILL_GROUPS+=("$group")
        picked=0
        if [[ "$defaults" = '*' || " $defaults " = *" $name "* ]]; then picked=1; fi
        SKILL_PICKED+=("$picked")
        SKILL_EXPLICIT+=("$picked")
    done <<<"${CATALOG_CACHE_NAMES[index]:-}"
}

load_selected_skill_catalogs() {
    # shellcheck disable=SC2034
    local LOADING_JOBS=() LOADING_INDEX CATALOG_LOAD_IDS=() index defaults=''
    queue_skill_catalogs "${SELECTED_REPOS[@]}" || return 1
    if ! run_content_loads 'Install / Skill catalogs'; then
        cleanup_loading_batch
        return 1
    fi
    collect_skill_catalogs
    cleanup_loading_batch
    for index in "${SELECTED_REPOS[@]}"; do
        if [ "$INSTALL_SCOPE" = global ]; then defaults="${SKILL_SOURCE_DEFAULTS[index]}"; fi
        catalog_add_group "$index" "$defaults" || return 1
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
