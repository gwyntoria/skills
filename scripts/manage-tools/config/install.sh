# Keep execution out of an if/! condition so failures inside a task retain errexit.
run_item() {
    local label="$1" result
    shift
    case "$label" in Remove*) printf '\n==> \033[31m%s\033[0m\n' "$label" ;;
    *) printf '\n==> \033[32m%s\033[0m\n' "$label" ;; esac
    set +e
    (
        set -e
        set -o pipefail
        "$@"
    ) </dev/null
    result=$?
    set -e
    if [ "$result" -eq 0 ]; then
        SUCCEEDED+=("$label")
    else
        FAILED+=("$label (exit $result)")
        printf 'Failed; continuing: %s\n' "$label" >&2
    fi
}

print_summary() {
    local item
    printf '\nResults: %s succeeded, %s failed\n' "${#SUCCEEDED[@]}" "${#FAILED[@]}"
    for item in "${SUCCEEDED[@]+"${SUCCEEDED[@]}"}"; do
        case "$item" in Remove*) printf '  OK    \033[31m%s\033[0m\n' "$item" ;;
        *) printf '  OK    \033[32m%s\033[0m\n' "$item" ;; esac
    done
    for item in "${FAILED[@]+"${FAILED[@]}"}"; do printf '  FAIL  \033[31m%s\033[0m\n' "$item"; done
    [ "${#FAILED[@]}" -eq 0 ]
}

print_skill_targets() {
    local name="$1" format="${2:-}" agent root="$HOME/" claude_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
    local shared_label="Shared skill / $name" claude_label="Claude / $name"
    if [ "$format" = preview ]; then
        shared_label='Shared skill'
        claude_label=Claude
    fi
    if [ "$INSTALL_SCOPE" = project ]; then
        root="$PROJECT_TARGET/"
        if [ "$format" = preview ]; then root=""; fi
        claude_dir="${root}.claude"
    fi
    printf '    \033[32m%s -> %s.agents/skills/%s\033[0m\n' "$shared_label" "$root" "$name"
    for agent in "${TARGET_AGENTS[@]}"; do
        if [ "$agent" = claude-code ]; then
            printf '    \033[32m%s -> %s/skills/%s\033[0m\n' "$claude_label" "$claude_dir" "$name"
        fi
    done
}

execute_plan() {
    local item other source previous handled index source_scope rules_directory
    local completed_sources=() names=()
    if [ "${#SELECTED_SKILLS[@]}" -gt 0 ] && { ! require_node || ! require_command npx; }; then
        FAILED+=('Skill installation requires Node.js and npx')
        print_summary
        return 1
    fi
    trap cleanup_loading_batch EXIT
    if ! prefetch_waza_rules; then
        FAILED+=('Waza rule download preparation failed')
    fi
    for item in "${AGENT_ITEMS[@]+"${AGENT_ITEMS[@]}"}"; do
        case "$item" in
        rules)
            for ((index = 0; index < ${#SELECTED_RULES[@]}; index++)); do
                other="${SELECTED_RULES[index]}"
                source_scope="${SELECTED_RULE_SOURCES[index]:-$INSTALL_SCOPE}"
                if ! resolve_rule_source "$source_scope" rules_directory; then
                    FAILED+=("$source_scope rule: $other (resource unavailable)")
                    continue
                fi
                run_item "$INSTALL_SCOPE rule: $other ($RULE_TARGETS)" apply_rule \
                    "$other" "$INSTALL_SCOPE" "$RULE_TARGETS" install "$source_scope" "$rules_directory"
            done
            ;;
        *) install_agent_with_bundles "$item" ;;
        esac
    done
    for item in "${SELECTED_SKILLS[@]+"${SELECTED_SKILLS[@]}"}"; do
        source="${SKILL_SOURCES[item]}"
        handled=0
        for previous in "${completed_sources[@]+"${completed_sources[@]}"}"; do
            if [ "$previous" = "$source" ]; then
                handled=1
                break
            fi
        done
        [ "$handled" -eq 0 ] || continue
        names=()
        for other in "${SELECTED_SKILLS[@]}"; do
            if [ "${SKILL_SOURCES[other]}" = "$source" ]; then
                names+=("${SKILL_NAMES[other]}")
            fi
        done
        completed_sources+=("$source")
        run_item "${SKILL_GROUPS[item]}: ${names[*]}" \
            install_agent_skills "$source" "${names[@]}"
    done
    print_summary
}

print_install_plan() {
    local i destination index source_scope rules_directory rule_targets="$RULE_TARGETS" user_clis="" scope_title=Global
    local label
    printf '\nExecution plan'
    if [ "$INSTALL_SCOPE" = project ]; then
        printf ' (project-relative destinations)'
        rule_targets=docs/rules
        scope_title=Project
    elif [ "$rule_targets" = both ]; then
        rule_targets='codex claude'
    fi
    printf ':\n'
    for i in "${AGENT_ITEMS[@]+"${AGENT_ITEMS[@]}"}"; do
        if [ "$i" = rules ]; then continue; fi
        label="$(agent_install_label "$i")"
        printf '  \033[32m%s\033[0m\n' "$label"
        user_clis="${user_clis:+$user_clis, }$label"
        print_agent_bundles "$i"
    done
    if [ "${#SELECTED_RULES[@]}" -gt 0 ]; then
        for ((index = 0; index < ${#SELECTED_RULES[@]}; index++)); do
            i="${SELECTED_RULES[index]}"
            source_scope="${SELECTED_RULE_SOURCES[index]:-$INSTALL_SCOPE}"
            resolve_rule_source "$source_scope" rules_directory || return 1
            if [ "$source_scope" = waza ]; then
                printf '  Rule source: GitHub tw93/Waza @ main -> %s (rules/%s.md)\n' "$WAZA_RULES_COMMIT" "${i#waza-}"
            elif snapshot_is_published; then
                printf '  Rule source: GitHub gwyntoria/skills @ main (rules/%s.md)\n' "$i"
            else
                printf '  Rule source: %s/%s.md\n' "$rules_directory" "$i"
            fi
            if [ "$INSTALL_SCOPE" = project ]; then
                printf '    \033[32mDestination: docs/rules/%s.md\033[0m\n' "$i"
            else
                printf '  \033[32m%s / %s -> %s\033[0m\n' "$INSTALL_SCOPE" "$i" "$rule_targets"
                for destination in $rule_targets; do
                    case "$destination" in
                    codex) printf '    \033[32m%s/.codex/AGENTS.md\033[0m\n' "$HOME" ;;
                    pi) printf '    \033[32m%s\033[0m\n' "$(pi_rule_path)" ;;
                    claude)
                        destination="$HOME/.claude/rules/$i.md"
                        if [ "$i" = agent-behavior ]; then destination="$HOME/.claude/CLAUDE.md"; fi
                        printf '    \033[32m%s\033[0m\n' "$destination"
                        ;;
                    esac
                done
            fi
        done
    fi
    for i in "${SELECTED_SKILLS[@]+"${SELECTED_SKILLS[@]}"}"; do
        printf '  \033[32m%s / %s -> %s\033[0m\n' "${SKILL_GROUPS[i]}" "${SKILL_NAMES[i]}" "${TARGET_AGENTS[*]}"
        print_skill_targets "${SKILL_NAMES[i]}" preview
    done
    for i in "${FAILED[@]+"${FAILED[@]}"}"; do printf '  UNAVAILABLE: %s\n' "$i"; done
    printf '\nInstall / %s\n' "$scope_title"
    if [ "$INSTALL_SCOPE" = project ]; then printf '  Project root: %q\n' "$PROJECT_TARGET"; fi
    if [ "${#SELECTED_RULES[@]}" -gt 0 ]; then
        printf '  Rules: %s -> %s\n' "${#SELECTED_RULES[@]}" "$rule_targets"
    fi
    if [ "${#SELECTED_SKILLS[@]}" -gt 0 ]; then
        printf '  Skills: %s -> %s\n' "${#SELECTED_SKILLS[@]}" "${TARGET_AGENTS[*]}"
    fi
    if [ -n "$user_clis" ]; then printf '  User CLIs: %s\n' "$user_clis"; fi
    if [ "${#FAILED[@]}" -gt 0 ]; then printf '  Unavailable: %s (see plan)\n' "${#FAILED[@]}"; fi
    printf '\n'
}
