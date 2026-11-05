#!/usr/bin/env bash

PROGRAM_NAME="${0##*/}"

PROGRESS_ENABLED=0
PROGRESS_ROWS=0
PROGRESS_COLS=0

# 最后一行留给进度，其余行正常滚动；不接管子命令的输入输出。
setup_progress() {
    local dimensions
    if ! [ -t 0 ] || ! [ -t 1 ] || ! [ -t 2 ] || [ "${TERM:-dumb}" = dumb ]; then
        return
    fi
    dimensions=$(stty size 2>/dev/null) || return
    read -r PROGRESS_ROWS PROGRESS_COLS <<<"$dimensions"
    case "$PROGRESS_ROWS:$PROGRESS_COLS" in
    *[!0-9:]* | :* | *:) return ;;
    esac
    if [ "$PROGRESS_ROWS" -lt 3 ] || [ "$PROGRESS_COLS" -lt 2 ]; then
        return
    fi

    # 先腾出一行，再把光标放回滚动区，兼容启动时已在屏幕底部。
    printf '\n\0337\033[1;%dr\0338\033[1A\r' "$((PROGRESS_ROWS - 1))" >&2
    PROGRESS_ENABLED=1
}

restore_terminal() {
    if [ "$PROGRESS_ENABLED" -eq 1 ]; then
        printf '\0337\033[%d;1H\033[2K\033[r\0338' "$PROGRESS_ROWS" >&2
        PROGRESS_ENABLED=0
    fi
}

draw_progress() {
    local current="$1"
    local total="$2"
    local name="$3"
    local state="$4"
    local width=20
    local filled
    local empty
    local bar=
    local text
    local dimensions
    local rows
    local cols

    if [ "$PROGRESS_ENABLED" -ne 1 ]; then
        return
    fi

    # 在子命令结束后的安全边界重新读取尺寸，运行中不争用光标。
    dimensions=$(stty size 2>/dev/null) || return
    read -r rows cols <<<"$dimensions"
    if [ "$rows" != "$PROGRESS_ROWS" ] || [ "$cols" != "$PROGRESS_COLS" ]; then
        restore_terminal
        setup_progress
        [ "$PROGRESS_ENABLED" -eq 1 ] || return
    fi

    filled=$((current * width / total))
    empty=$((width - filled))

    while [ "$filled" -gt 0 ]; do
        bar="${bar}#"
        filled=$((filled - 1))
    done
    while [ "$empty" -gt 0 ]; do
        bar="${bar}-"
        empty=$((empty - 1))
    done

    text="[$bar] $current/$total  $name ($state)"
    # 留出右侧一列，避免窄窗口中自动换行；一次写完再恢复日志光标。
    printf '\0337\033[%d;1H\033[2K%s\0338' \
        "$PROGRESS_ROWS" "${text:0:$((PROGRESS_COLS - 1))}" >&2
}

usage() {
    printf 'Usage: %s [options]\n' "$PROGRAM_NAME"
    printf '\n'
    printf 'Options:\n'
    printf '  -h, --help   Show this help message\n'
}

# 解析命令行选项。
# 约定：0 继续执行，1 已打印 usage，2 选项错误。这里不自己 exit，
# 退出码统一由 main 决定。
parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
        -h | --help)
            usage
            return 1
            ;;
        *)
            printf 'Error: unknown option: %s\n\n' "$1" >&2
            usage >&2
            return 2
            ;;
        esac
    done

    return 0
}

# 执行一个更新任务，把结果追加到 RESULTS。
#
# RESULTS 的每条记录是 tab 分隔的三段：<status>\t<name>\t<detail>
# status 取 ok / fail / skip；detail 在 fail 时是退出码，skip 时是原因。
#
# 前置命令不存在算跳过，不算失败，所以这里始终返回 0。
run_update() {
    local name="$1"
    local executable="$2"
    local elapsed
    local status
    local detail
    local rc

    shift 2
    if [ "${IN_AGENTS:-0}" -eq 0 ]; then
        TASK_CURRENT=$((TASK_CURRENT + 1))
    fi

    printf '\n'
    printf '%s\n' "=================================================="
    printf '[%s] [%s/%s] Starting: %s\n' \
        "$(date '+%H:%M:%S')" "$TASK_CURRENT" "$TASK_TOTAL" "$name"
    printf 'Command:'
    printf ' %s' "$@"
    printf '\n'
    printf '%s\n' "=================================================="

    if ! command -v "$executable" >/dev/null 2>&1; then
        printf '⚠️  Skipped: command '\''%s'\'' not found\n' "$executable"
        status=skip
        detail="command '$executable' unavailable in current PATH"
    else
        SECONDS=0
        draw_progress "$TASK_CURRENT" "$TASK_TOTAL" "$name" "Running"

        # 子命令直接使用终端，保留无换行提示和交互能力。
        "$@"
        rc=$?
        elapsed=$SECONDS

        if [ "$rc" -eq 0 ]; then
            printf '✅ Completed: %s (%ss)\n' "$name" "$elapsed"
            status=ok
            detail=
        else
            printf '❌ Failed: %s (%ss)\n' "$name" "$elapsed"
            printf 'Exit code: %s\n' "$rc"
            status=fail
            detail="$rc"
        fi
    fi

    draw_progress "$TASK_CURRENT" "$TASK_TOTAL" "$name" "$status"

    if [ "${IN_AGENTS:-0}" -eq 1 ]; then
        AGENT_RESULTS+=("$status"$'\t'"$name"$'\t'"$detail")
    else
        RESULTS+=("$status"$'\t'"$name"$'\t'"$detail")
    fi

    # 单个任务失败后继续跑剩下的，让一次运行拿到全部结果。
    return 0
}

# 插件/扩展独立于本体更新；旧版本缺少能力时仅跳过相应项目。
run_pi_extensions() {
    local executable="$1" help
    if [ -n "$executable" ]; then
        help=$("$executable" update --help 2>/dev/null) || help=
        if [[ "$help" = *--extensions* ]]; then
            run_update 'Pi Extensions' "$executable" "$executable" update --extensions
            return
        fi
    fi
    AGENT_RESULTS+=("skip"$'\t'"Pi Extensions"$'\t'"Pi unavailable or lacks update --extensions")
}

run_claude_plugins() {
    local executable="$1" help plugins entries plugin scope rc
    if [ -z "$executable" ]; then
        AGENT_RESULTS+=("skip"$'\t'"Claude Plugin Marketplace"$'\t'"Claude unavailable in current PATH")
        AGENT_RESULTS+=("skip"$'\t'"Claude Plugins"$'\t'"Claude unavailable in current PATH")
        return
    fi
    help=$("$executable" plugin marketplace update --help 2>/dev/null) || help=
    if [[ "$help" = *'marketplace update'* ]]; then
        run_update 'Claude Plugin Marketplace' "$executable" "$executable" plugin marketplace update
    else
        AGENT_RESULTS+=("skip"$'\t'"Claude Plugin Marketplace"$'\t'"installed Claude lacks marketplace update")
    fi
    help=$("$executable" plugin list --help 2>/dev/null) || help=
    if [[ "$help" != *--json* ]] || ! command -v python3 >/dev/null 2>&1; then
        AGENT_RESULTS+=("skip"$'\t'"Claude Plugins"$'\t'"requires plugin list --json and Python 3")
        return
    fi
    plugins=$("$executable" plugin list --json)
    rc=$?
    if [ "$rc" -ne 0 ]; then
        AGENT_RESULTS+=("fail"$'\t'"Claude Plugins (list)"$'\t'"$rc")
        return
    fi
    # 只解析官方 JSON，不读取 Claude 私有安装文件；忽略其他项目及非安装型插件。
    entries=$(python3 -c '
import json, os, sys
plugins = json.load(sys.stdin)
if not isinstance(plugins, list):
    raise ValueError("expected an array from claude plugin list --json")
entries = []
for plugin in plugins:
    if not isinstance(plugin, dict):
        raise ValueError("invalid Claude plugin record")
    scope = plugin.get("scope")
    if scope not in ("user", "project", "local", "managed"):
        continue
    project = plugin.get("projectPath")
    if scope in ("project", "local"):
        if not isinstance(project, str) or os.path.realpath(project) != os.path.realpath(os.getcwd()):
            continue
    name = plugin.get("id")
    if not isinstance(name, str) or not name or name.startswith("-") or any(c in name for c in "\t\r\n"):
        raise ValueError("invalid Claude plugin id")
    if name.endswith(("@inline", "@skills-dir", "@synced", "@builtin")):
        continue
    entry = (name, scope)
    if entry not in entries:
        entries.append(entry)
for name, scope in entries:
    print(name + "\t" + scope)
' <<<"$plugins")
    rc=$?
    if [ "$rc" -ne 0 ]; then
        AGENT_RESULTS+=("fail"$'\t'"Claude Plugins (parse list)"$'\t'"$rc")
        return
    fi
    if [ -z "$entries" ]; then
        AGENT_RESULTS+=("skip"$'\t'"Claude Plugins"$'\t'"no installed plugins in current context")
        return
    fi
    while IFS=$'\t' read -r plugin scope; do
        run_update "Claude Plugin $plugin [$scope]" "$executable" \
            "$executable" plugin update "$plugin" --scope "$scope" <&3
    done 3<&0 <<<"$entries"
}

run_agents() {
    local IN_AGENTS=1
    local -a names=('Codex' 'Claude Code' 'Pi' 'Hermes Agent')
    local -a commands=(codex claude pi hermes)
    local -a paths=() reasons=()
    local i executable help record status name detail
    local success=0 failed=0 group_status group_detail
    AGENT_RESULTS=()
    TASK_CURRENT=$((TASK_CURRENT + 1))
    printf '\n[%s/%s] Starting: Agents\n' "$TASK_CURRENT" "$TASK_TOTAL"
    draw_progress "$TASK_CURRENT" "$TASK_TOTAL" Agents Running
    printf '\nAgent detection (current PATH):\n'

    # 完成全部检测后再开始更新；帮助探针不执行更新。
    for i in "${!commands[@]}"; do
        executable=$(command -v "${commands[$i]}")
        paths[i]="$executable"
        reasons[i]=
        if [ -z "$executable" ]; then
            reasons[i]="command '${commands[$i]}' unavailable in current PATH"
        else
            help=$("$executable" --help 2>/dev/null) || help=
            if ! [[ "$help" =~ (^|$'\n')[[:space:]]*(${commands[$i]}[[:space:]]+)?update([[:space:]|]|$) ]]; then
                reasons[i]="installed CLI does not advertise 'update'; update manually"
            elif [ "${commands[$i]}" = pi ]; then
                help=$("$executable" update --help 2>/dev/null) || help=
                if [[ "$help" != *--self* ]]; then
                    reasons[i]='installed Pi lacks update --self; update manually'
                fi
            fi
        fi
        if [ -n "${reasons[$i]}" ]; then
            printf '  %s: skipped (%s)\n' "${names[$i]}" "${reasons[$i]}"
        else
            printf '  %s: %s\n' "${names[$i]}" "$executable"
        fi
    done

    for i in "${!commands[@]}"; do
        if [ -n "${reasons[$i]}" ]; then
            AGENT_RESULTS+=("skip"$'\t'"${names[$i]}"$'\t'"${reasons[$i]}")
            case "${commands[$i]}" in
            codex) AGENT_RESULTS+=("skip"$'\t'"Codex Plugin Marketplace"$'\t'"${reasons[$i]}") ;;
            claude) run_claude_plugins "${paths[$i]}" ;;
            pi) run_pi_extensions "${paths[$i]}" ;;
            esac
            continue
        fi
        executable="${paths[$i]}"
        case "${commands[$i]}" in
        codex)
            run_update Codex "$executable" "$executable" update
            run_update 'Codex Plugin Marketplace' "$executable" "$executable" plugin marketplace upgrade ;;
        claude)
            run_update 'Claude Code' "$executable" "$executable" update
            run_claude_plugins "$executable" ;;
        pi)
            run_update Pi "$executable" "$executable" update --self
            run_pi_extensions "$executable" ;;
        *) run_update "${names[$i]}" "$executable" "$executable" update ;;
        esac
    done

    for record in "${AGENT_RESULTS[@]}"; do
        IFS=$'\t' read -r status name detail <<<"$record"
        case "$status" in
        ok) success=$((success + 1)) ;;
        fail) failed=$((failed + 1)) ;;
        esac
    done
    group_detail=
    if [ "$failed" -gt 0 ]; then
        group_status=fail
        group_detail=1
    elif [ "$success" -gt 0 ]; then
        group_status=ok
    else
        group_status=skip
        group_detail='no Agent has a confirmed update method in current PATH'
    fi
    RESULTS+=("$group_status"$'\t'"Agents"$'\t'"$group_detail")
    draw_progress "$TASK_CURRENT" "$TASK_TOTAL" Agents "$group_status"
}

# 外层固定三个任务；Agent 明细独立于外层计数。
run_tasks() {
    TASK_CURRENT=0
    TASK_TOTAL=3
    run_update Skills npx npx skills update -g -y
    run_agents
    run_update 'Homebrew Packages' brew brew upgrade --no-ask
}

# 把 RESULTS 渲染成尾部汇总。
# 返回值就是脚本的退出码：有任务失败返回 1，只跳过或全部成功返回 0。
report_results() {
    local record
    local status
    local name
    local detail
    local success_count=0
    local failed_count=0
    local skipped_count=0
    local -a success_items=()
    local -a failed_items=()
    local -a skipped_items=()

    for record in "${RESULTS[@]}"; do
        IFS=$'\t' read -r status name detail <<<"$record"

        case "$status" in
        ok)
            success_count=$((success_count + 1))
            success_items+=("  ✅ $name")
            ;;
        fail)
            failed_count=$((failed_count + 1))
            failed_items+=("  ❌ $name (exit code $detail)")
            ;;
        skip)
            skipped_count=$((skipped_count + 1))
            skipped_items+=("  ⚠️  $name: $detail")
            ;;
        esac
    done

    printf '\n'
    printf '%s\n' "##################################################"
    printf 'Update finished: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')"
    printf 'Succeeded: %s\n' "$success_count"
    printf 'Failed: %s\n' "$failed_count"
    printf 'Skipped: %s\n' "$skipped_count"
    printf '%s\n' "##################################################"

    if [ "${#success_items[@]}" -gt 0 ]; then
        printf '\nSuccessful updates:\n'
        printf '%s\n' "${success_items[@]}"
    fi

    if [ "${#failed_items[@]}" -gt 0 ]; then
        printf '\nFailed updates:\n'
        printf '%s\n' "${failed_items[@]}"
    fi

    if [ "${#skipped_items[@]}" -gt 0 ]; then
        printf '\nSkipped updates:\n'
        printf '%s\n' "${skipped_items[@]}"
    fi

    if [ "${#AGENT_RESULTS[@]}" -gt 0 ]; then
        printf '\nAgent results:\n'
        for record in "${AGENT_RESULTS[@]}"; do
            IFS=$'\t' read -r status name detail <<<"$record"
            printf '  %s: %s%s\n' "$name" "$status" "${detail:+ ($detail)}"
        done
    fi
    printf '\n'

    if [ "$failed_count" -gt 0 ]; then
        return 1
    fi

    return 0
}

main() {
    local parse_rc

    # RESULTS 是 run_update 和 report_results 之间唯一的交接面。
    RESULTS=()
    AGENT_RESULTS=()

    parse_args "$@"
    parse_rc=$?

    # 0 继续；1 已打印 usage，按成功退出；其余是选项错误。
    case "$parse_rc" in
    0) ;;
    1) return 0 ;;
    *) return 2 ;;
    esac

    trap restore_terminal EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'exit 129' HUP
    setup_progress

    printf '\n'
    printf '%s\n' "##################################################"
    printf 'Update started: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')"
    printf '%s\n' "##################################################"

    run_tasks

    restore_terminal
    # report_results 的返回值就是脚本的退出码。
    report_results
}

main "$@"
