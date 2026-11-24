queue_content_load() {
    # Return the result slot to the caller through Bash dynamic scope.
    # shellcheck disable=SC2034
    LOADING_INDEX=$((${#LOADING_JOBS[@]} / 4))
    LOADING_JOBS+=("$1" "$2" "${3:-}" "${4:-}")
}

run_content_loads() {
    local status=0
    [ "${#LOADING_JOBS[@]}" -gt 0 ] || return 0
    require_python 'Content loading' || return 1
    LOADING_DIR="$(mktemp -d)" || return 1
    python3 -B "$MODULE_DIR/content/loading.py" "$1" "$LOADING_DIR" "$BASH" \
        "$MODULE_DIR/main.sh" "$SNAPSHOT_KIND" "$SNAPSHOT_ARCHIVE_URL" "${LOADING_JOBS[@]}" || status=$?
    case "$status" in
    129 | 130 | 143) exit "$status" ;;
    *) return "$status" ;;
    esac
}

content_load_succeeded() {
    local status
    IFS= read -r status <"$LOADING_DIR/$1/status" && [ "$status" -eq 0 ]
}

report_content_load_error() {
    local index="$1"
    printf 'Unavailable: %s\n' "${LOADING_JOBS[index * 4 + 1]}" >&2
    if [ -s "$LOADING_DIR/$index/error" ]; then cat "$LOADING_DIR/$index/error" >&2; fi
}

cleanup_loading_batch() {
    if [ -n "${LOADING_DIR:-}" ]; then
        rm -rf -- "$LOADING_DIR"
        LOADING_DIR=''
    fi
}

loading_phase() {
    printf '%s\n%s\n' "$1" "${2:-}" >"$LOAD_JOB_DIR/next-transfer" &&
        mv -f -- "$LOAD_JOB_DIR/next-transfer" "$LOAD_JOB_DIR/transfer"
}

loading_download() {
    local url="$1" path="$2" phase="$3"
    require_command curl || return 1
    loading_phase "$phase" "$path" || return 1
    curl -fLsS --no-compressed --connect-timeout 10 --no-buffer -D "$path.headers" -o "$path" "$url"
}

content_load_worker() {
    local kind="$1" value="$2" ref="$3" LOAD_JOB_DIR="$4" path
    case "$kind" in
    skill_archive)
        path="$LOAD_JOB_DIR/skills.tar.gz"
        loading_download "https://codeload.github.com/${value#https://github.com/}/tar.gz/HEAD" "$path" 'Downloading archive' &&
            run_python 'Skills catalog' skills/parse_catalog.py archive "$path"
        ;;
    skill_tree) fetch_tree_skill_names "$value" ;;
    skill_homepage)
        path="$LOAD_JOB_DIR/skills.html"
        loading_download "$value" "$path" 'Downloading catalog' &&
            run_python 'Skills catalog' skills/parse_catalog.py homepage "$path"
        ;;
    skill_fixed) printf '%s\n' "$value" ;;
    rules-bundled)
        path="$(snapshot_resource rules)" && print_rule_names "$path"
        ;;
    rules-published) with_published_rules print_rule_names "$LOAD_JOB_DIR" ;;
    rules-waza) acquire_waza_catalog "$LOAD_JOB_DIR" ;;
    waza-body) fetch_waza_rule "$value" "$ref" "$LOAD_JOB_DIR/rule.md" ;;
    waza-fallback)
        loading_phase 'Git fallback' &&
            mkdir -p "$LOAD_JOB_DIR/rules" &&
            waza_clone_snapshot "$LOAD_JOB_DIR" "$ref"
        ;;
    *) return 2 ;;
    esac
}
