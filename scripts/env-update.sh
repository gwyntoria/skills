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
    printf '  -c, --clean  Run brew cleanup after updates\n'
    printf '  -h, --help   Show this help message\n'
}

# 解析命令行选项。
# 约定：0 继续执行，1 已打印 usage，2 选项错误。这里不自己 exit，
# 退出码统一由 main 决定。
parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
        -c | --clean)
            # 有意不用 local：main 要读这个值，再传给 run_tasks。
            clean_homebrew=1
            ;;
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

        shift
    done

    return 0
}

# 执行一个更新任务，把结果追加到 RESULTS。
#
# RESULTS 的每条记录是 tab 分隔的三段：<status>\t<name>\t<detail>
# status 取 ok / fail / skip；detail 在 fail 时是退出码，skip 时是缺失的命令名。
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
    TASK_CURRENT=$((TASK_CURRENT + 1))

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
        detail="$executable"
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

    RESULTS+=("$status"$'\t'"$name"$'\t'"$detail")

    # 单个任务失败后继续跑剩下的，让一次运行拿到全部结果。
    return 0
}

# 按固定顺序跑更新任务。clean_homebrew 为 1 时，在 Homebrew 之后加一步 cleanup。
run_tasks() {
    local clean_homebrew="$1"

    TASK_CURRENT=0
    TASK_TOTAL=5

    if [ "$clean_homebrew" -eq 1 ]; then
        TASK_TOTAL=$((TASK_TOTAL + 1))
    fi

    run_update \
        "Skills" \
        "npx" \
        npx skills update -g -y

    run_update \
        "Codex" \
        "codex" \
        codex update

    run_update \
        "Codex Plugin Marketplace" \
        "codex" \
        codex plugin marketplace upgrade

    run_update \
        "Claude Code" \
        "claude" \
        claude update

    run_update \
        "Homebrew Packages" \
        "brew" \
        brew upgrade

    # cleanup 必须排在 upgrade 之后，所以跟着 Homebrew 一起放在这里。
    if [ "$clean_homebrew" -eq 1 ]; then
        run_update \
            "Homebrew Cleanup" \
            "brew" \
            brew cleanup
    fi
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
            skipped_items+=("  ⚠️  $name: missing $detail")
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
    clean_homebrew=0

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

    run_tasks "$clean_homebrew"

    restore_terminal
    # report_results 的返回值就是脚本的退出码。
    report_results
}

main "$@"
