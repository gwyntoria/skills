# Only remove temporary directories created by this session.
REMOVAL_TEMP=""
REMOVAL_SIGNATURE=""

reset_removal() {
    if [ -n "$REMOVAL_TEMP" ]; then rm -rf -- "$REMOVAL_TEMP"; fi
    REMOVAL_TEMP=""
    REMOVAL_SIGNATURE=""
    REMOVAL_RULE_IDS=()
    REMOVAL_RULE_LABELS=()
    REMOVAL_SKILL_IDS=()
    REMOVAL_SKILL_LABELS=()
    REMOVAL_SKILL_GROUPS=()
    REMOVAL_RULE_SELECTION=()
    REMOVAL_SKILL_SELECTION=()
    REMOVAL_TARGET_COUNT=0
}

# The private manifest binds picker selections to scanned paths and fingerprints.
removal_inventory() {
    run_python "Skill / Rule removal" content/removal.py "$HOME" "$PROJECT_TARGET" "$REMOVAL_SCOPE" "$REMOVAL_TEMP/inventory.json" "$(pi_rule_path)" "$@"
}

# Return 0 for a fresh inventory, 2 for a reused inventory, or 1 on failure.
prepare_removal_inventory() {
    local scope="$1" codex="$2" claude="$3" rules="$4" skills="$5" pi="$6"
    local signature rows id kind group label
    printf -v signature '%q ' "$@" "$PROJECT_TARGET" "$(pi_rule_path)"
    if [ "$signature" = "$REMOVAL_SIGNATURE" ]; then return 2; fi

    reset_removal
    require_python "Skill / Rule removal" || return 1
    REMOVAL_TEMP="$(mktemp -d)" || return 1
    REMOVAL_SCOPE="$scope"
    removal_inventory scan "$codex" "$claude" "$rules" "$skills" "$pi" || return 1
    rows=$(removal_inventory rows) || return 1
    while IFS=$'\t' read -r id kind group label; do
        [ -n "$id" ] || continue
        if [ "$kind" = rules ]; then
            REMOVAL_RULE_IDS+=("$id")
            REMOVAL_RULE_LABELS+=("$label")
        else
            REMOVAL_SKILL_IDS+=("$id")
            REMOVAL_SKILL_LABELS+=("$label")
            REMOVAL_SKILL_GROUPS+=("$group")
        fi
    done <<<"$rows"
    REMOVAL_SIGNATURE="$signature"
}

select_removal_entries() {
    local kind="$1"
    shift
    case "$kind" in
    rules) REMOVAL_RULE_SELECTION=("$@") ;;
    skills) REMOVAL_SKILL_SELECTION=("$@") ;;
    esac
}

preview_selected_removal() {
    local i links preview ids=()
    for i in "${REMOVAL_RULE_SELECTION[@]+"${REMOVAL_RULE_SELECTION[@]}"}"; do ids+=("${REMOVAL_RULE_IDS[i]}"); done
    for i in "${REMOVAL_SKILL_SELECTION[@]+"${REMOVAL_SKILL_SELECTION[@]}"}"; do ids+=("${REMOVAL_SKILL_IDS[i]}"); done
    if [ "${#ids[@]}" -eq 0 ]; then
        printf 'No removal targets selected.\n'
        return 2
    fi
    removal_inventory select "${ids[@]}" || return 1
    links=$(removal_inventory linked-skills) || return 1
    if [ -n "$links" ]; then
        printf 'Claude links referencing the selected skills:\n%s\n' "$links"
        while :; do
            printf 'Also remove these Claude links? [y/N] (b/Esc: back | q: exit): '
            read_back_answer || return 4
            case "$REPLY" in
            y | Y)
                removal_inventory include-links || return 1
                break
                ;;
            n | N | '') break ;;
            b | B) return 3 ;;
            q | Q) return 4 ;;
            *) printf 'Please enter y or n (b/Esc: back | q: exit).\n' ;;
            esac
        done
    fi
    preview=$(removal_inventory preview) || return 1
    # The first line counts actual manifest entries, including opted-in links.
    REMOVAL_TARGET_COUNT="${preview%%$'\n'*}"
    printf '\n%s\n' "${preview#*$'\n'}"
}

apply_selected_removal() {
    removal_inventory remove "$1"
}

list_setup_backups() {
    run_python "Backup listing" content/backups.py list "$HOME" "$1"
}

remove_setup_backups() {
    run_python "Backup removal" content/backups.py remove "$HOME" "$@"
}

confirm_backup_removal() {
    local kind="$1" names name answer
    local backups=()
    names=$(list_setup_backups "$kind") || return 1
    if [ -z "$names" ]; then
        printf 'No setup backups found for %s.\n' "$kind"
        return 0
    fi
    printf '\nRemove all %s setup backup directories listed below:\n' "$kind"
    while IFS= read -r name; do
        backups+=("$name")
        printf '  \033[31m%s/%s\033[0m\n' "$HOME" "$name"
    done <<<"$names"
    printf 'This permanently deletes these backups and their restore data. No new backup is created.\n'
    printf 'Confirm removal? [Y/n]: '
    IFS= read -r answer || return 0
    case "$answer" in y | Y | '') ;; *) return 0 ;; esac
    run_item 'Remove all backups' remove_setup_backups "$kind" "${backups[@]}"
    print_summary
}
