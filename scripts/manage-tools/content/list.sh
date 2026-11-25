list_heading() {
    if [ "$1" -eq 1 ]; then
        printf '\n\033[1;36m%s\033[0m\n' "$2"
    else
        printf '\n%s\n' "$2"
    fi
}

print_skill_catalog() {
    local color="$1" i previous=""
    for ((i = 0; i < ${#SKILL_NAMES[@]}; i++)); do
        if [ "$previous" != "${SKILL_GROUPS[i]}" ]; then
            previous="${SKILL_GROUPS[i]}"
            list_heading "$color" "Skills · $previous"
            printf '%s\n' "${SKILL_SOURCES[i]}"
        fi
        printf '  %s\n' "${SKILL_NAMES[i]}"
    done
}

# Remote queries use the content flags alone. Local queries also take scope and location filters.
list_content() {
    local mode="$1" rules="$2" skills="$3"
    local list_color=0 name failed=0
    if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ]; then
        printf '\033[H\033[2J'
        if [ -z "${NO_COLOR:-}" ]; then list_color=1; fi
    fi
    if [ "$mode" = local ]; then
        local scope="$4" shared="$5" codex="$6" claude="$7" pi="$8"
        run_python "Installed content listing" content/list_installed.py \
            "$HOME" "$PROJECT_TARGET" "$scope" "$rules" "$skills" \
            "$shared" "$codex" "$claude" "$pi" "$(pi_rule_path)" "$list_color"
        return $?
    fi
    list_remote_content "$rules" "$skills" "$list_color"
}

list_remote_content() {
    local rules="$1" skills="$2" color="$3" name index failed=0
    # shellcheck disable=SC2034
    local LOADING_JOBS=() LOADING_INDEX CATALOG_LOAD_IDS=() published='' waza=''
    # A list action runs in its own subshell. Keep inherited install cache
    # directories owned by the menu session.
    trap cleanup_loading_batch EXIT
    if [ "$rules" -eq 1 ]; then
        queue_content_load rules-published 'Rules / Gwyntoria'
        published="$LOADING_INDEX"
        if [ -z "$WAZA_RULES_PATH" ]; then
            queue_content_load rules-waza 'Rules / Waza'
            waza="$LOADING_INDEX"
        fi
    fi
    if [ "$skills" -eq 1 ]; then queue_skill_catalogs "${!SKILL_SOURCE_GROUPS[@]}" || return 1; fi
    run_content_loads 'List / Remote catalogs' || return 1

    list_heading "$color" 'Available · Remote'
    if [ "$rules" -eq 1 ]; then
        if content_load_succeeded "$published"; then
            list_heading "$color" 'Rules · Gwyntoria'
            printf '%s\n' "$GWYNTORIA_SKILLS_URL"
            while IFS= read -r name; do printf '  %s\n' "$name"; done <"$LOADING_DIR/$published/output"
        else
            report_content_load_error "$published"
            failed=1
        fi
        local waza_names=("${RULE_NAMES_WAZA[@]}")
        if [ -n "$waza" ]; then
            if content_load_succeeded "$waza"; then
                mapfile -t waza_names <"$LOADING_DIR/$waza/names"
            else
                report_content_load_error "$waza"
                waza_names=()
                failed=1
            fi
        fi
        if [ "${#waza_names[@]}" -gt 0 ]; then
            list_heading "$color" 'Rules · Waza'
            printf '%s\n' 'https://github.com/tw93/Waza/tree/main/rules'
            printf '  %s\n' "${waza_names[@]}"
        fi
    fi
    if [ "$skills" -eq 1 ]; then
        collect_skill_catalogs
        SKILL_NAMES=()
        SKILL_SOURCES=()
        SKILL_GROUPS=()
        # shellcheck disable=SC2034
        SKILL_PICKED=()
        # shellcheck disable=SC2034
        SKILL_EXPLICIT=()
        for index in "${!SKILL_SOURCE_GROUPS[@]}"; do catalog_add_group "$index" ''; done
        print_skill_catalog "$color"
        [ "${#CATALOG_FAILURES[@]}" -eq 0 ] || failed=1
    fi
    return "$failed"
}
