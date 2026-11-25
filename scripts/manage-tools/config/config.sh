cleanup_setup_resources() {
    cleanup_loading_batch
    if [ -t 1 ]; then printf '\033[?25h'; fi
    if [ -n "$WAZA_TEMP" ]; then rm -rf -- "$WAZA_TEMP"; fi
    reset_removal
}

# Capture action failures outside a conditional, which would disable errexit inside its file writes and backup steps.
run_interactive_task() {
    set +e
    (
        set -e
        set -o pipefail
        "$@"
    )
    INTERACTIVE_RESULT=$?
    set -e
    if [ "$INTERACTIVE_RESULT" -ne 0 ]; then
        printf 'Task failed (exit %s).\n' "$INTERACTIVE_RESULT" >&2
    fi
    return 0
}

interactive_setup() {
    trap cleanup_setup_resources EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    local page=main i task menu_status removal_backup=0
    local REMOVE_SCOPE=global REMOVE_CODEX=1 REMOVE_CLAUDE=1 REMOVE_PI=1 REMOVE_RULES=0 REMOVE_SKILLS=0
    local session_status=0 INTERACTIVE_RESULT=0 show_summary=0 list_result=0
    local list_rules list_skills list_scope
    local repo_labels=() repo_defaults=() repo_url
    local rule_labels=() rule_names=() rule_sources=() source_scope default_rule selected_rule catalog_status
    local task_labels=('Rules' 'Skills')
    local lifecycle_action
    local agent_names=(codex claude pi) selected_agents=()
    local tasks=() agent_requested=0 scope rules_visited=0 project_option
    local install_title='Install / Global' remove_title='Remove / Global'
    printf -v project_option 'Project\n    %q' "$PROJECT_TARGET"
    while :; do
        case "$page" in
        main)
            choose_items 0 'AGENT CONFIG' 0 0 'Skill / Rule' Agent Exit || return "$session_status"
            case "${MENU_SELECTED[0]}" in
            0) page=content_menu ;;
            1) page=agent_menu ;;
            2) return "$session_status" ;;
            esac
            ;;
        agent_menu)
            choose_items 20 Agent 0 0 Install Cleanup Uninstall List Back || {
                [ "$?" -eq 2 ] || return "$session_status"
                page=main
                continue
            }
            case "${MENU_SELECTED[0]}" in
            0)
                agent_requested=1
                page=agent_choices
                ;;
            1)
                lifecycle_action=Cleanup
                page=lifecycle_agent
                ;;
            2)
                lifecycle_action=Uninstall
                page=lifecycle_agent
                ;;
            3)
                run_interactive_task run_python 'Agent listing' agents/list_installed.py
                list_result=1
                page=complete
                ;;
            4) page=main ;;
            esac
            ;;
        lifecycle_agent)
            MENU_VISITED[21]=0
            choose_items 21 "Agent / $lifecycle_action" 1 0 Codex 'Claude Code' Pi || {
                [ "$?" -eq 2 ] || return "$session_status"
                page=agent_menu
                continue
            }
            if [ "${#MENU_SELECTED[@]}" -eq 0 ]; then
                page=agent_menu
                continue
            fi
            selected_agents=()
            for i in "${MENU_SELECTED[@]}"; do selected_agents+=("${agent_names[i]}"); done
            run_agent_lifecycles "$lifecycle_action" "${selected_agents[@]}"
            page=complete
            ;;
        content_menu)
            choose_items 22 'Skill / Rule' 0 0 Install Remove List 'Remove all backups' Back || {
                [ "$?" -eq 2 ] || return "$session_status"
                page=main
                continue
            }
            case "${MENU_SELECTED[0]}" in
            0) page=install_scope ;;
            1)
                reset_removal
                page=remove_scope
                ;;
            2) page=list_categories ;;
            3)
                run_interactive_task confirm_backup_removal
                page=complete
                ;;
            4) page=main ;;
            esac
            ;;
        list_categories)
            choose_items 15 'List: choose content' 1 '1 1' Rules Skills || {
                [ "$?" -eq 2 ] || return "$session_status"
                page=content_menu
                continue
            }
            [ "${#MENU_SELECTED[@]}" -gt 0 ] || {
                page=content_menu
                continue
            }
            list_rules=0
            list_skills=0
            for i in "${MENU_SELECTED[@]}"; do
                if [ "$i" -eq 0 ]; then list_rules=1; else list_skills=1; fi
            done
            page=list_mode
            ;;
        list_mode)
            choose_items 16 'List: choose location' 0 0 Local Remote || {
                [ "$?" -eq 2 ] || return "$session_status"
                page=list_categories
                continue
            }
            if [ "${MENU_SELECTED[0]}" -eq 0 ]; then
                page=list_scope
            else
                run_interactive_task list_content remote "$list_rules" "$list_skills"
                list_result=1
                page=complete
            fi
            ;;
        list_scope)
            choose_items 17 'List: choose scope' 0 0 Global Project || {
                [ "$?" -eq 2 ] || return "$session_status"
                page=list_mode
                continue
            }
            if [ "${MENU_SELECTED[0]}" -eq 0 ]; then list_scope=global; else list_scope=project; fi
            page=list_agents
            ;;
        list_agents)
            local list_agent_labels=(Codex 'Claude Code') list_agent_defaults='1 0'
            if [ "$list_scope" = global ] && [ "$list_rules" -eq 1 ]; then
                list_agent_labels+=(Pi)
                list_agent_defaults+=' 0'
            elif [ "${MENU_CURSORS[18]:-0}" -gt 1 ]; then MENU_CURSORS[18]=1; fi
            choose_items 18 'List: choose agents' 1 "$list_agent_defaults" "${list_agent_labels[@]}" || {
                [ "$?" -eq 2 ] || return "$session_status"
                page=list_scope
                continue
            }
            [ "${#MENU_SELECTED[@]}" -gt 0 ] || {
                page=list_scope
                continue
            }
            local list_codex=0 list_claude=0 list_pi=0
            for i in "${MENU_SELECTED[@]}"; do
                case "$i" in 0) list_codex=1 ;; 1) list_claude=1 ;; 2) list_pi=1 ;; esac
            done
            run_interactive_task list_content local "$list_rules" "$list_skills" \
                "$list_scope" "$list_codex" "$list_claude" "$list_pi"
            list_result=1
            page=complete
            ;;
        remove_categories)
            choose_items 5 "$remove_title / Content" 1 0 Rules Skills || {
                [ "$?" -eq 2 ] || return "$session_status"
                page=remove_scope
                continue
            }
            [ "${#MENU_SELECTED[@]}" -gt 0 ] || {
                printf 'No content selected; cancelled.\n'
                page=complete
                continue
            }
            REMOVE_RULES=0
            REMOVE_SKILLS=0
            for i in "${MENU_SELECTED[@]}"; do
                if [ "$i" -eq 0 ]; then REMOVE_RULES=1; else REMOVE_SKILLS=1; fi
            done
            page=remove_agents
            ;;
        remove_scope)
            choose_items 14 'Remove / Choose scope' 0 0 Global "$project_option" || {
                [ "$?" -eq 2 ] || return "$session_status"
                page=content_menu
                continue
            }
            if [ "${MENU_SELECTED[0]}" -eq 0 ]; then
                REMOVE_SCOPE=global
                remove_title='Remove / Global'
            else
                REMOVE_SCOPE=project
                remove_title='Remove / Project'
            fi
            page=remove_categories
            ;;
        remove_agents)
            local remove_agent_labels=(Codex 'Claude Code') remove_agent_defaults='1 0'
            if [ "$REMOVE_SCOPE" = global ]; then
                remove_agent_labels+=('Pi (rules only)')
                remove_agent_defaults+=' 0'
            elif [ "${MENU_CURSORS[4]:-0}" -gt 1 ]; then
                MENU_CURSORS[4]=1
            fi
            choose_items 4 "$remove_title / Agents" 1 "$remove_agent_defaults" "${remove_agent_labels[@]}" || {
                [ "$?" -eq 2 ] || return "$session_status"
                page=remove_categories
                continue
            }
            [ "${#MENU_SELECTED[@]}" -gt 0 ] || {
                printf 'No agents selected; cancelled.\n'
                page=complete
                continue
            }
            REMOVE_CODEX=0
            REMOVE_CLAUDE=0
            REMOVE_PI=0
            for i in "${MENU_SELECTED[@]}"; do
                case "$i" in 0) REMOVE_CODEX=1 ;; 1) REMOVE_CLAUDE=1 ;; 2) REMOVE_PI=1 ;; esac
            done
            menu_status=0
            prepare_removal_inventory "$REMOVE_SCOPE" "$REMOVE_CODEX" "$REMOVE_CLAUDE" "$REMOVE_RULES" "$REMOVE_SKILLS" "$REMOVE_PI" || menu_status=$?
            case "$menu_status" in
            0)
                MENU_VISITED[12]=0
                MENU_CURSORS[12]=0
                MENU_CURSORS[13]=0
                ;;
            2) ;;
            *)
                FAILED+=('Installed content scan failed')
                show_summary=1
                page=complete
                continue
                ;;
            esac
            page=remove_rules
            ;;
        remove_rules)
            if [ "${#REMOVAL_RULE_LABELS[@]}" -gt 0 ]; then
                choose_items 12 "$remove_title / Rules" 1 0 "${REMOVAL_RULE_LABELS[@]}" || {
                    [ "$?" -eq 2 ] || return "$session_status"
                    page=remove_agents
                    continue
                }
                select_removal_entries rules "${MENU_SELECTED[@]}"
            fi
            page=remove_skills
            ;;
        remove_skills)
            if [ "${#REMOVAL_SKILL_LABELS[@]}" -gt 0 ]; then
                REPO_ITEM_LABELS=("${REMOVAL_SKILL_LABELS[@]}")
                REPO_ITEM_GROUPS=("${REMOVAL_SKILL_GROUPS[@]}")
                REPO_SELECTED=("${REMOVAL_SKILL_SELECTION[@]+"${REMOVAL_SKILL_SELECTION[@]}"}")
                menu_status=0
                choose_skill_repositories 13 "$remove_title / Skills by repository" 31 || menu_status=$?
                select_removal_entries skills "${REPO_SELECTED[@]}"
                if [ "$menu_status" -ne 0 ]; then
                    [ "$menu_status" -eq 2 ] || return "$session_status"
                    if [ "${#REMOVAL_RULE_LABELS[@]}" -gt 0 ]; then page=remove_rules; else page=remove_agents; fi
                    continue
                fi
            fi
            preview_selected_removal || {
                menu_status=$?
                if [ "$menu_status" -eq 3 ]; then continue; fi
                if [ "$menu_status" -eq 4 ]; then return "$session_status"; fi
                if [ "$menu_status" -ne 2 ]; then
                    FAILED+=('Removal preview failed; rescan required')
                    show_summary=1
                fi
                page=complete
                continue
            }
            page=remove_backup
            ;;
        remove_backup)
            removal_backup=0
            printf 'Create backup? [y/N] (b/Esc: back | q: exit): '
            read_back_answer || return "$session_status"
            case "$REPLY" in
            y | Y)
                removal_backup=1
                page=remove_confirm
                ;;
            n | N | '') page=remove_confirm ;;
            q | Q) return "$session_status" ;;
            b | B)
                if [ "${#REMOVAL_SKILL_LABELS[@]}" -gt 0 ]; then
                    page=remove_skills
                elif [ "${#REMOVAL_RULE_LABELS[@]}" -gt 0 ]; then
                    page=remove_rules
                else page=remove_agents; fi
                continue
                ;;
            *) printf 'Please enter y or n (b/Esc: back | q: exit).\n' ;;
            esac
            ;;
        remove_confirm)
            printf '\n%s\n  Targets: %s\n' "$remove_title" "$REMOVAL_TARGET_COUNT"
            if [ "$removal_backup" -eq 1 ]; then
                printf '  Backup: create before removal\n'
            else
                printf '  Backup: none\n'
            fi
            printf 'Confirm removal? [Y/n] (b/Esc: back | q: exit): '
            read_back_answer || return "$session_status"
            case "$REPLY" in
            y | Y | '') run_interactive_task apply_selected_removal "$removal_backup" ;;
            q | Q) return "$session_status" ;;
            b | B)
                page=remove_backup
                continue
                ;;
            *) printf 'Cancelled.\n' ;;
            esac
            page=complete
            ;;
        install_scope)
            choose_items 7 'Install / Choose scope' 0 0 Global "$project_option" || {
                [ "$?" -eq 2 ] || return "$session_status"
                page=content_menu
                continue
            }
            if [ "${MENU_SELECTED[0]}" -eq 0 ]; then
                scope=global
                install_title='Install / Global'
            else
                scope=project
                install_title='Install / Project'
            fi
            if [ "$scope" != "$INSTALL_SCOPE" ]; then
                SELECTED_RULES=()
                SELECTED_RULE_SOURCES=()
                rules_visited=0
                SKILL_NAMES=()
                SKILL_SOURCES=()
                SKILL_GROUPS=()
                SKILL_PICKED=()
                SKILL_EXPLICIT=()
                MENU_VISITED[6]=0
            fi
            INSTALL_SCOPE="$scope"
            page=tasks
            ;;
        tasks)
            choose_items 1 "$install_title / Tasks" 1 0 "${task_labels[@]}" || {
                [ "$?" -eq 2 ] || return "$session_status"
                page=install_scope
                continue
            }
            tasks=("${MENU_SELECTED[@]+"${MENU_SELECTED[@]}"}")
            [ "${#tasks[@]}" -gt 0 ] || {
                printf 'No tasks selected.\n'
                page=complete
                continue
            }
            AGENT_ITEMS=()
            INSTALL_SKILLS=0
            agent_requested=0
            for task in "${tasks[@]}"; do
                case "$task" in
                0) AGENT_ITEMS+=(rules) ;;
                1) INSTALL_SKILLS=1 ;;
                esac
            done
            page=before_rules
            ;;
        agent_choices)
            choose_items 12 'Agent / Install' 1 0 Codex 'Claude Code (with statusline)' 'Pi (with three packages)' || {
                [ "$?" -eq 2 ] || return "$session_status"
                page=agent_menu
                continue
            }
            AGENT_ITEMS=()
            for i in "${MENU_SELECTED[@]}"; do AGENT_ITEMS+=("${agent_names[i]}"); done
            if ! preflight_agent_install "${AGENT_ITEMS[@]}"; then
                FAILED+=('Installation preparation failed')
                show_summary=1
                page=complete
                continue
            fi
            page=before_rules
            ;;
        before_rules)
            if [[ " ${AGENT_ITEMS[*]+${AGENT_ITEMS[*]}} " = *" rules "* ]]; then
                page=rule_choices
            else
                SELECTED_RULES=()
                SELECTED_RULE_SOURCES=()
                rules_visited=0
                page=after_rules
            fi
            ;;
        rule_choices)
            catalog_status=0
            load_install_rule_catalogs || catalog_status=$?
            if [ "$catalog_status" -eq 2 ]; then
                FAILED+=('project rule catalog unavailable')
                show_summary=1
                page=complete
                continue
            fi
            if [ "$catalog_status" -eq 1 ]; then
                choose_items 13 "$install_title / Waza rules unavailable${WAZA_RULES_ERROR:+$'\n'$WAZA_RULES_ERROR}" 0 0 Retry 'Continue without Waza rules' Back || {
                    [ "$?" -eq 2 ] || return "$session_status"
                    page=tasks
                    continue
                }
                case "${MENU_SELECTED[0]}" in
                0) continue ;;
                2)
                    page=tasks
                    continue
                    ;;
                esac
                RULE_NAMES_WAZA=()
            fi
            rule_labels=()
            rule_names=()
            rule_sources=()
            for i in "${RULE_NAMES_WAZA[@]+"${RULE_NAMES_WAZA[@]}"}"; do
                rule_labels+=("${i#waza-}")
                rule_names+=("$i")
                rule_sources+=(waza)
            done
            for i in "${RULE_NAMES_GLOBAL[@]+"${RULE_NAMES_GLOBAL[@]}"}"; do
                rule_labels+=("$i")
                rule_names+=("$i")
                rule_sources+=(global)
            done
            for i in "${RULE_NAMES_PROJECT[@]+"${RULE_NAMES_PROJECT[@]}"}"; do
                rule_labels+=("$i")
                rule_names+=("$i")
                rule_sources+=(project)
            done
            if [ "${#rule_labels[@]}" -eq 0 ]; then
                FAILED+=('No rules available')
                show_summary=1
                page=complete
                continue
            fi
            REPO_ITEM_LABELS=("${rule_labels[@]}")
            REPO_ITEM_GROUPS=()
            REPO_SELECTED=()
            for ((i = 0; i < ${#rule_names[@]}; i++)); do
                source_scope="${rule_sources[i]}"
                if [ "$source_scope" = waza ]; then
                    REPO_ITEM_GROUPS+=(Waza)
                else
                    REPO_ITEM_GROUPS+=(Gwyntoria)
                fi

                if [ "$INSTALL_SCOPE" = global ] && [ "$rules_visited" -eq 0 ]; then
                    for default_rule in "${RULE_SOURCE_DEFAULTS[@]}"; do
                        [ "$default_rule" = "$source_scope:${rule_names[i]}" ] || continue
                        REPO_SELECTED+=("$i")
                        break
                    done
                fi
                for ((selected_rule = 0; selected_rule < ${#SELECTED_RULES[@]}; selected_rule++)); do
                    if [ "${SELECTED_RULES[selected_rule]}" = "${rule_names[i]}" ] &&
                        [ "${SELECTED_RULE_SOURCES[selected_rule]}" = "$source_scope" ]; then
                        REPO_SELECTED+=("$i")
                        break
                    fi
                done
            done
            menu_status=0
            choose_skill_repositories 9 "$install_title / Rules" 32 || menu_status=$?
            rules_visited=1
            SELECTED_RULES=()
            SELECTED_RULE_SOURCES=()
            for i in "${REPO_SELECTED[@]+"${REPO_SELECTED[@]}"}"; do
                SELECTED_RULES+=("${rule_names[i]}")
                SELECTED_RULE_SOURCES+=("${rule_sources[i]}")
            done
            if [ "$menu_status" -ne 0 ]; then
                [ "$menu_status" -eq 2 ] || return "$session_status"
                if [ "$agent_requested" -eq 1 ]; then page=agent_choices; else page=tasks; fi
                continue
            fi
            if [ "$INSTALL_SCOPE" = global ] && [ "${#SELECTED_RULES[@]}" -gt 0 ]; then
                page=rule_targets
            else
                if [ "$INSTALL_SCOPE" = project ]; then RULE_TARGETS=codex; fi
                page=after_rules
            fi
            ;;
        rule_targets)
            choose_items 8 "$install_title / Agents for rules" 1 '1 0 0' Codex 'Claude Code' Pi || {
                [ "$?" -eq 2 ] || return "$session_status"
                page=rule_choices
                continue
            }
            [ "${#MENU_SELECTED[@]}" -gt 0 ] || {
                printf 'No rule targets selected; cancelled.\n'
                page=complete
                continue
            }
            RULE_TARGETS=""
            for i in "${MENU_SELECTED[@]}"; do
                case "$i" in 0) destination=codex ;; 1) destination=claude ;; 2) destination=pi ;; esac
                RULE_TARGETS="${RULE_TARGETS:+$RULE_TARGETS }$destination"
            done
            page=after_rules
            ;;
        after_rules)
            if [ "$INSTALL_SKILLS" -eq 1 ]; then
                page=skill_repos
            else
                SELECTED_SKILLS=()
                page=review
            fi
            ;;
        skill_repos)
            repo_labels=()
            repo_defaults=()
            for i in "${!SKILL_SOURCE_GROUPS[@]}"; do
                repo_url="$(skill_source_url "${SKILL_SOURCE_GROUPS[i]}")"
                repo_labels+=("${repo_url#https://github.com/}")
                if [ "$INSTALL_SCOPE" = global ] && [ -n "${SKILL_SOURCE_DEFAULTS[i]}" ]; then
                    repo_defaults+=(1)
                else
                    repo_defaults+=(0)
                fi
            done
            choose_items 6 "$install_title / Skill repositories" 1 "${repo_defaults[*]}" "${repo_labels[@]}" || {
                [ "$?" -eq 2 ] || return "$session_status"
                if [[ " ${AGENT_ITEMS[*]+${AGENT_ITEMS[*]}} " = *" rules "* ]]; then
                    if [ "$INSTALL_SCOPE" = global ] && [ "${#SELECTED_RULES[@]}" -gt 0 ]; then page=rule_targets; else page=rule_choices; fi
                elif [ "$agent_requested" -eq 1 ]; then page=agent_choices; else page=tasks; fi
                continue
            }
            SELECTED_REPOS=("${MENU_SELECTED[@]+"${MENU_SELECTED[@]}"}")
            if ! load_selected_skill_catalogs; then
                CATALOG_FAILURES+=('Skill catalog preparation failed')
            fi
            FAILED=("${CATALOG_FAILURES[@]+"${CATALOG_FAILURES[@]}"}")
            [ "${#FAILED[@]}" -eq 0 ] || session_status=1
            catalog_collect_selection
            catalog_build_view
            if [ "${#REPO_ITEM_LABELS[@]}" -gt 0 ]; then page=skills; else page=review; fi
            ;;
        skills)
            choose_skill_repositories 2 "$install_title / Skills by repository" 32 1 || {
                menu_status=$?
                catalog_sync_selection
                [ "$menu_status" -eq 2 ] || return "$session_status"
                page=skill_repos
                continue
            }
            catalog_sync_selection
            if [ "${#SELECTED_SKILLS[@]}" -gt 0 ]; then page=targets; else page=review; fi
            ;;
        targets)
            choose_items 3 "$install_title / Agents for skills" 1 '1 0' Codex 'Claude Code' || {
                [ "$?" -eq 2 ] || return "$session_status"
                page=skills
                continue
            }
            TARGET_AGENTS=()
            for i in "${MENU_SELECTED[@]+"${MENU_SELECTED[@]}"}"; do
                if [ "$i" -eq 0 ]; then TARGET_AGENTS+=(codex); else TARGET_AGENTS+=(claude-code); fi
            done
            if [ "${#TARGET_AGENTS[@]}" -eq 0 ]; then
                printf 'No skill targets selected; cancelled.\n'
                page=complete
                continue
            fi
            page=review
            ;;
        review)
            if [[ " ${AGENT_ITEMS[*]+${AGENT_ITEMS[*]}} " = *" rules "* ]]; then
                choose_items 11 '' 0 0 Install Cancel || {
                    menu_status=$?
                    if [ "$menu_status" -eq 3 ]; then
                        FAILED+=('Cannot prepare installation plan')
                        show_summary=1
                        page=complete
                        continue
                    fi
                    [ "$menu_status" -eq 2 ] || return "$session_status"
                    if [ "$INSTALL_SKILLS" -eq 1 ]; then
                        if [ "${#SELECTED_SKILLS[@]}" -gt 0 ]; then page=targets; else page=skill_repos; fi
                    else
                        if [ "$INSTALL_SCOPE" = global ] && [ "${#SELECTED_RULES[@]}" -gt 0 ]; then page=rule_targets; else page=rule_choices; fi
                    fi
                    continue
                }
                if [ "${MENU_SELECTED[0]}" -ne 0 ]; then
                    printf 'Cancelled.\n'
                    page=complete
                    continue
                fi
            else
                if ! print_install_plan; then
                    FAILED+=('Cannot prepare installation plan')
                    show_summary=1
                    page=complete
                    continue
                fi
                if [ "$((${#AGENT_ITEMS[@]} + ${#SELECTED_SKILLS[@]}))" -eq 0 ]; then
                    show_summary=1
                    page=complete
                    continue
                fi
                printf 'Continue? [Y/n] (b/Esc: back | q: exit) '
                read_back_answer || return "$session_status"
                case "$REPLY" in
                y | Y | '') ;;
                q | Q) return "$session_status" ;;
                b | B)
                    if [ "$INSTALL_SKILLS" -eq 1 ]; then
                        if [ "${#SELECTED_SKILLS[@]}" -gt 0 ]; then page=targets; else page=skill_repos; fi
                    elif [ "$agent_requested" -eq 1 ]; then page=agent_choices; else page=tasks; fi
                    continue
                    ;;
                *)
                    printf 'Cancelled.\n'
                    page=complete
                    continue
                    ;;
                esac
            fi
            run_interactive_task execute_plan
            page=complete
            ;;
        complete)
            if [ "$INTERACTIVE_RESULT" -ne 0 ] || [ "${#FAILED[@]}" -gt 0 ]; then session_status=1; fi
            if [ "$show_summary" -eq 1 ]; then print_summary || true; fi
            if [ "$list_result" -eq 1 ]; then
                printf '\nEnter / Esc  Main menu    q  Exit '
            else
                printf '\nPress Enter to return to the main menu (Esc: back | q: exit): '
            fi
            while :; do
                read_key || return "$session_status"
                case "$KEY" in
                '' | $'\e') break ;;
                q | Q) return "$session_status" ;;
                esac
            done
            # New actions start with defaults; Back within an action keeps selections.
            # The catalog cache survives so a later run never refetches a repository.
            SUCCEEDED=()
            FAILED=()
            MENU_SELECTED=()
            MENU_CURSORS=()
            MENU_CHOICES=()
            MENU_VISITED=()
            AGENT_ITEMS=()
            agent_requested=0
            SELECTED_SKILLS=()
            SELECTED_RULES=()
            SELECTED_RULE_SOURCES=()
            SKILL_NAMES=()
            SKILL_SOURCES=()
            SKILL_GROUPS=()
            SKILL_PICKED=()
            SKILL_EXPLICIT=()
            SELECTED_REPOS=()
            VIEW_SKILL_INDICES=()
            TARGET_AGENTS=(codex claude-code)
            RULE_TARGETS="codex claude pi"
            INSTALL_SCOPE=global
            rules_visited=0
            REMOVE_CODEX=1
            REMOVE_CLAUDE=1
            REMOVE_PI=1
            REMOVE_RULES=0
            REMOVE_SKILLS=0
            REMOVE_SCOPE=global
            install_title='Install / Global'
            remove_title='Remove / Global'
            reset_removal
            INTERACTIVE_RESULT=0
            show_summary=0
            list_result=0
            INSTALL_SKILLS=0
            page=main
            ;;
        esac
    done
}

run_agent_setup() (
    set -eu
    PROJECT_TARGET="$(pwd -P)"
    INSTALL_SKILLS=0

    WAZA_TEMP=""
    # shellcheck disable=SC2034
    LOADING_DIR=""
    INSTALL_SCOPE=global
    RULE_TARGETS="codex claude pi"
    SELECTED_RULES=()
    SELECTED_RULE_SOURCES=()
    RULE_NAMES_GLOBAL=()
    RULE_NAMES_PROJECT=()
    # shellcheck disable=SC2034
    RULE_CATALOG_PROJECT=0
    RULE_NAMES_WAZA=()
    WAZA_RULES_PATH=""
    WAZA_RULES_COMMIT=""
    WAZA_RULES_ERROR=""

    WAZA_SKILLS_URL="https://github.com/tw93/waza"
    KAMI_SKILLS_URL="https://github.com/tw93/kami"
    MATTPOCOCK_SKILLS_URL="https://github.com/mattpocock/skills"
    MATTPOCOCK_SKILLS_PAGE_URL="https://www.aihero.dev/skills"
    HUMANLAYER_SKILLS_URL="https://github.com/humanlayer/skills"
    GWYNTORIA_SKILLS_URL="https://github.com/gwyntoria/skills"
    DISTILLY_SKILLS_URL="https://github.com/titanwings/distilly"
    RULE_SOURCE_DEFAULTS=(
        waza:waza-anti-patterns
        # waza:waza-clarity
        waza:waza-durable-context
    )
    SKILL_SOURCE_GROUPS=(Waza Kami 'Matt Pocock' HumanLayer Gwyntoria Distilly)
    SKILL_SOURCE_DEFAULTS=(
        'check health hunt learn read think ui write'
        ''
        'setup-matt-pocock-skills grill-with-docs to-spec to-tickets improve-codebase-architecture implement-spec writing-for-agents codebase-design wayfinder'
        'show-me'
        'how why'
        ''
    )
    SKILL_NAMES=()
    SKILL_SOURCES=()
    SKILL_GROUPS=()
    SKILL_PICKED=()
    SKILL_EXPLICIT=()
    CATALOG_CACHE_NAMES=()
    CATALOG_FAILURES=()
    # shellcheck disable=SC2034
    SELECTED_REPOS=()
    VIEW_SKILL_INDICES=()
    TARGET_AGENTS=(codex claude-code)
    SUCCEEDED=()
    FAILED=()
    MENU_SELECTED=()
    MENU_CURSORS=()
    MENU_CHOICES=()
    MENU_VISITED=()
    KEY=""
    REPO_ITEM_LABELS=()
    REPO_ITEM_GROUPS=()
    REPO_SELECTED=()
    REPO_EXPLICIT=()
    AGENT_ITEMS=()
    SELECTED_SKILLS=()

    trap 'exit 129' HUP
    interactive_setup
)
