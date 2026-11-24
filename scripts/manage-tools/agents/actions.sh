PI_BUNDLED_PACKAGES=(npm:pi-web-access npm:pi-subagents npm:pi-powerline-footer)

agent_statusline_source() {
    snapshot_resource scripts/statusline.sh
}

agent_install_label() {
    case "$1" in
    codex) printf 'Codex CLI' ;;
    claude) printf 'Claude Code CLI' ;;
    pi) printf 'Pi CLI' ;;
    statusline) printf 'Claude statusline' ;;
    esac
}

print_agent_bundles() {
    case "$1" in
    claude) printf '    Claude statusline (bundled)\n' ;;
    pi) printf '    %s (bundled)\n' "${PI_BUNDLED_PACKAGES[@]}" ;;
    esac
}

preflight_agent_install() {
    local agent needs_statusline=0
    for agent in "$@"; do
        case "$agent" in
        codex) require_command curl || return 1 ;;
        claude)
            require_command curl || return 1
            require_python "Claude statusline configuration" || return 1
            needs_statusline=1
            ;;
        statusline) require_python "Claude statusline configuration" || return 1 ;;
        pi)
            require_node || return 1
            require_command npm || return 1
            ;;
        esac
    done
    if [ "$needs_statusline" -eq 1 ]; then
        agent_statusline_source >/dev/null
    fi
}

install_agent_with_bundles() {
    local agent="$1" label failed_before="${#FAILED[@]}" package
    label="$(agent_install_label "$agent")"
    case "$agent" in
    codex) run_item "$label" install_codex ;;
    claude)
        run_item "$label" install_claude
        if [ "${#FAILED[@]}" -eq "$failed_before" ]; then
            install_agent_statusline
        else
            FAILED+=('Claude statusline: skipped because Claude installation failed')
        fi
        ;;
    pi)
        run_item "$label" install_pi
        if [ "${#FAILED[@]}" -eq "$failed_before" ]; then
            for package in "${PI_BUNDLED_PACKAGES[@]}"; do
                run_item "$package" pi install "$package"
            done
        else
            for package in "${PI_BUNDLED_PACKAGES[@]}"; do
                FAILED+=("$package: skipped because Pi installation failed")
            done
        fi
        ;;
    statusline) install_agent_statusline ;;
    esac
}

install_agent_statusline() {
    if agent_statusline_source >/dev/null; then
        run_item 'Claude statusline' install_statusline
    else
        FAILED+=('Claude statusline: resource unavailable')
    fi
}

run_agent_lifecycles() {
    local action="$1" agent command_paths statusline_source status=0
    shift
    if ! require_python "Agent $action"; then
        INTERACTIVE_RESULT=1
        return 0
    fi
    for agent in "$@"; do
        command_paths="$(type -aP "$agent" || true)"
        statusline_source=""
        if [ "$agent" = claude ] && [ -f "$HOME/.claude/statusline.sh" ]; then
            statusline_source="$(agent_statusline_source)" || statusline_source=""
        fi
        if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ] && [ -z "${NO_COLOR:-}" ]; then
            printf '\n\033[1;36mAgent / %s / %s\033[0m\n' "$action" "$agent"
        else
            printf '\nAgent / %s / %s\n' "$action" "$agent"
        fi
        run_interactive_task python3 -B "$MODULE_DIR/agents/lifecycle.py" \
            "$action" "$agent" "$command_paths" "$statusline_source" "${PI_BUNDLED_PACKAGES[@]}"
        if [ "$INTERACTIVE_RESULT" -ne 0 ]; then status=1; fi
    done
    INTERACTIVE_RESULT="$status"
}
