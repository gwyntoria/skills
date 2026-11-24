#!/usr/bin/env bash

MODE="$2"
MODULE_DIR="$(cd -P -- "${BASH_SOURCE[0]%/*}" && pwd -P)" || exit 1

# shellcheck source=scripts/manage-tools/common.sh
source "$MODULE_DIR/common.sh" || exit 1
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

if [ "$MODE" = config ]; then
    # shellcheck source=scripts/manage-tools/snapshot.sh
    source "$MODULE_DIR/snapshot.sh" || exit 1
    initialize_snapshot "$1" "$3" || exit 1
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
    # shellcheck source=scripts/manage-tools/agents/actions.sh
    source "$MODULE_DIR/agents/actions.sh" || exit 1
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
run_tool_updates "$MODE"
