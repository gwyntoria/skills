# Listing follows links for inspection. Removal uses its own snapshots.
print_installed_content() {
    run_python "Installed content listing" content/list_installed.py "$HOME" "$PROJECT_TARGET" "$LIST_SCOPE" "$LIST_RULES" "$LIST_SKILLS" "$LIST_CODEX" "$LIST_CLAUDE" "$LIST_PI" "$(pi_rule_path)" "$list_color"
}

list_heading() {
    if [ "$list_color" -eq 1 ]; then
        printf '\n\033[1;36m%s\033[0m\n' "$1"
    else
        printf '\n%s\n' "$1"
    fi
}

list_content() {
    local list_color=0 name failed=0
    if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ]; then
        printf '\033[H\033[2J'
        if [ -z "${NO_COLOR:-}" ]; then list_color=1; fi
    fi
    if [ "$LIST_MODE" = local ]; then
        print_installed_content
        return $?
    fi
    trap cleanup_setup_resources EXIT
    list_heading 'Available · Remote'
    if [ "$LIST_RULES" -eq 1 ]; then
        local catalog
        if catalog="$(published_rule_catalog)"; then
            list_heading 'Rules · Gwyntoria'
            printf '%s\n' "$GWYNTORIA_SKILLS_URL"
            while IFS= read -r name; do
                if [ -n "$name" ]; then printf '  %s\n' "$name"; fi
            done <<<"$catalog"
        else failed=1; fi
        if load_waza_rules; then
            list_heading 'Rules · Waza'
            printf '%s\n' "$WAZA_RULES_URL"
            for name in "${RULE_NAMES_WAZA[@]+"${RULE_NAMES_WAZA[@]}"}"; do printf '  %s\n' "$name"; done
        else failed=1; fi
    fi
    if [ "$LIST_SKILLS" -eq 1 ]; then
        preflight 4 || return 1
        load_catalog
        print_catalog
        [ "${#FAILED[@]}" -eq 0 ] || failed=1
    fi
    return "$failed"
}
