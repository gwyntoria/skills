initialize_snapshot() {
    SNAPSHOT_KIND="$1"
    SNAPSHOT_ARCHIVE_URL="$2"
    SNAPSHOT_ROOT="$(cd -- "$MODULE_DIR/../.." && pwd -P)"
}

snapshot_is_published() {
    [ "$SNAPSHOT_KIND" = archive ]
}

snapshot_resource() {
    local relative="$1" root="${2:-$SNAPSHOT_ROOT}" path
    path="$root/$relative"
    case "$relative" in
    rules) [ -d "$path" ] ;;
    scripts/statusline.sh) [ -f "$path" ] ;;
    *) return 2 ;;
    esac || {
        printf 'Invalid resource: %s\n' "$path" >&2
        return 1
    }
    printf '%s\n' "$path"
}

# Keep a published rules directory alive only while the caller reads it.
with_published_rules() (
    local reader="$1" directory published
    if snapshot_is_published; then
        directory="$(snapshot_resource rules)" || return 1
    else
        require_command curl || return 1
        require_command tar || return 1
        published="$(mktemp -d)" || return 1
        trap 'rm -rf -- "$published"' EXIT
        trap 'exit 130' INT
        trap 'exit 143' TERM
        trap 'exit 129' HUP
        curl -fLsS "$SNAPSHOT_ARCHIVE_URL" -o "$published/source.tar.gz" || return 1
        tar -xzf "$published/source.tar.gz" -C "$published" -- skills-main/rules || return 1
        directory="$(snapshot_resource rules "$published/skills-main")" || return 1
    fi
    "$reader" "$directory"
)
