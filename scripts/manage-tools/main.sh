#!/usr/bin/env bash

SOURCE_KIND="$1"
MODE="$2"
SOURCE_ARCHIVE_URL="$3"
MODULE_DIR="$(cd -P -- "${BASH_SOURCE[0]%/*}" && pwd -P)" || exit 1
REPO="$(cd -- "$MODULE_DIR/../.." && pwd -P)" || exit 1

# shellcheck source=scripts/manage-tools/common.sh
source "$MODULE_DIR/common.sh" || exit 1
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

if [ "$MODE" = config ]; then
    # shellcheck source=scripts/manage-tools/config/menu.sh
    source "$MODULE_DIR/config/menu.sh" || exit 1
    # shellcheck source=scripts/manage-tools/config/install.sh
    source "$MODULE_DIR/config/install.sh" || exit 1
    # shellcheck source=scripts/manage-tools/skills/catalog.sh
    source "$MODULE_DIR/skills/catalog.sh" || exit 1
    # shellcheck source=scripts/manage-tools/rules/rules.sh
    source "$MODULE_DIR/rules/rules.sh" || exit 1
    # shellcheck source=scripts/manage-tools/agents/install.sh
    source "$MODULE_DIR/agents/install.sh" || exit 1
    # shellcheck source=scripts/manage-tools/content/list.sh
    source "$MODULE_DIR/content/list.sh" || exit 1
    # shellcheck source=scripts/manage-tools/content/removal.sh
    source "$MODULE_DIR/content/removal.sh" || exit 1
    # shellcheck source=scripts/manage-tools/config/config.sh
    source "$MODULE_DIR/config/config.sh" || exit 1
    run_agent_setup
    exit "$?"
fi

# shellcheck source=scripts/manage-tools/update/update.sh
source "$MODULE_DIR/update/update.sh" || exit 1
UPDATE_ALL=0
if [ "$MODE" = all ]; then UPDATE_ALL=1; fi
TITLE_STYLE=
STEP_COLOR=
DIVIDER_COLOR=
COLOR_RESET=
# RESULTS 是 run_update 和 report_results 之间唯一的交接面。
RESULTS=()
AGENT_RESULTS=()

if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ] && [ -z "${NO_COLOR:-}" ]; then
    TITLE_STYLE=$'\033[1m'
    STEP_COLOR=$'\033[33m'
    DIVIDER_COLOR=$'\033[90m'
    COLOR_RESET=$'\033[0m'
fi

trap restore_terminal EXIT
setup_progress

printf '\n'
printf '%s\n' "##################################################"
printf 'Update started: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')"
printf '%s\n' "##################################################"

run_tasks

restore_terminal
# report_results 的返回值就是脚本的退出码。
report_results
