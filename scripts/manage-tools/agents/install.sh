# 安装 Claude Code 状态栏脚本，并更新 settings.json。
# settings.json 已存在时只更新 statusLine 键，其余配置原样保留；
# 文件不是合法 JSON 就报错退出，不覆盖用户原有内容。
install_statusline() {
    local claude_dir="$HOME/.claude"
    local settings_file="$claude_dir/settings.json"
    local statusline_source
    statusline_source="$(agent_statusline_source)" || return 1
    printf '\033[32mStatusline target: %s/statusline.sh\nSettings target: %s\033[0m\n' "$claude_dir" "$settings_file"

    mkdir -p "$claude_dir"

    install -m 0755 "$statusline_source" "$claude_dir/statusline.sh"

    # 让 Claude Code 执行命令时展开 ~。
    # shellcheck disable=SC2088,SC2016
    run_python "Claude statusline configuration" agents/statusline_settings.py "$settings_file" "~/.claude/statusline.sh"
}

install_codex() {
    if ! command -v codex >/dev/null 2>&1; then
        curl -fsSL https://chatgpt.com/codex/install.sh | sh
    fi
    require_command codex
    printf '\033[32mCodex CLI: %s\033[0m\n' "$(command -v codex)"
}

install_claude() {
    if ! command -v claude >/dev/null 2>&1; then
        curl -fsSL https://claude.ai/install.sh | bash
    fi
    require_command claude
    printf '\033[32mClaude Code CLI: %s\033[0m\n' "$(command -v claude)"
}

install_pi() {
    require_node
    require_command npm
    if ! command -v pi >/dev/null 2>&1; then
        curl -fsSL https://pi.dev/install.sh | sh
    fi
    require_command pi
    pi --version
}
