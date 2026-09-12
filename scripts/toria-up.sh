#!/usr/bin/env bash

PROGRAM_NAME="${0##*/}"

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
    local status
    local detail
    local rc

    shift 2

    printf '\n'
    printf '%s\n' "=================================================="
    printf '[%s] Starting: %s\n' "$(date '+%H:%M:%S')" "$name"
    printf 'Command:'
    printf ' %s' "$@"
    printf '\n'
    printf '%s\n' "=================================================="

    if ! command -v "$executable" >/dev/null 2>&1; then
        printf '⚠️  Skipped: command '\''%s'\'' not found\n' "$executable"
        status=skip
        detail="$executable"
    else
        "$@"
        rc=$?

        if [ "$rc" -eq 0 ]; then
            printf '✅ Completed: %s\n' "$name"
            status=ok
            detail=
        else
            printf '❌ Failed: %s\n' "$name"
            printf 'Exit code: %s\n' "$rc"
            status=fail
            detail="$rc"
        fi
    fi

    RESULTS+=("$status"$'\t'"$name"$'\t'"$detail")

    # 单个任务失败后继续跑剩下的，让一次运行拿到全部结果。
    return 0
}

# 按固定顺序跑更新任务。clean_homebrew 为 1 时，在 Homebrew 之后加一步 cleanup。
run_tasks() {
    local clean_homebrew="$1"

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

    run_update \
        "Pi" \
        "pi" \
        pi update

    run_update \
        "Pi Extension Packages" \
        "pi" \
        pi update --extensions
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

    printf '\n'
    printf '%s\n' "##################################################"
    printf 'Update started: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')"
    printf '%s\n' "##################################################"

    run_tasks "$clean_homebrew"

    # report_results 的返回值就是脚本的退出码。
    report_results
}

main "$@"
