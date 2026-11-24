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

# Remote queries use the content flags alone. Local queries also take scope and Agent filters.
list_content() {
    local mode="$1" rules="$2" skills="$3"
    local list_color=0 name failed=0
    if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ]; then
        printf '\033[H\033[2J'
        if [ -z "${NO_COLOR:-}" ]; then list_color=1; fi
    fi
    if [ "$mode" = local ]; then
        local scope="$4" codex="$5" claude="$6" pi="$7"
        run_python "Installed content listing" content/list_installed.py \
            "$HOME" "$PROJECT_TARGET" "$scope" "$rules" "$skills" \
            "$codex" "$claude" "$pi" "$(pi_rule_path)" "$list_color"
        return $?
    fi
    trap cleanup_setup_resources EXIT
    list_heading "$list_color" 'Available · Remote'
    if [ "$rules" -eq 1 ]; then
        local catalog
        if catalog="$(published_rule_catalog)"; then
            list_heading "$list_color" 'Rules · Gwyntoria'
            printf '%s\n' "$GWYNTORIA_SKILLS_URL"
            while IFS= read -r name; do
                if [ -n "$name" ]; then printf '  %s\n' "$name"; fi
            done <<<"$catalog"
        else failed=1; fi
        if load_waza_rules; then
            list_heading "$list_color" 'Rules · Waza'
            printf '%s\n' 'https://github.com/tw93/Waza/tree/main/rules'
            for name in "${RULE_NAMES_WAZA[@]+"${RULE_NAMES_WAZA[@]}"}"; do printf '  %s\n' "$name"; done
        else failed=1; fi
    fi
    if [ "$skills" -eq 1 ]; then
        require_skill_catalog || return 1
        load_catalog
        print_skill_catalog "$list_color"
        [ "${#FAILED[@]}" -eq 0 ] || failed=1
    fi
    return "$failed"
}
