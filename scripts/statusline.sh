#!/bin/bash
# Claude Code statusline: Model effort | cwd on branch | Context % left | tokens in/out | rate limits | version
# The rate limit segment renders only while the session reports rate_limits, which Claude.ai
# subscription sessions do and API key sessions do not. Nothing is carried over from an earlier
# session, so an API key session never inherits a subscription session's numbers.
# Set WAZA_STATUSLINE_DEBUG=1 to surface stderr (jq parse errors, missing tools).
[ "${WAZA_STATUSLINE_DEBUG:-}" = "1" ] || exec 2>/dev/null

CACHE_DIR="$HOME/.cache/waza-statusline"
HIGHWATER_FILE="$CACHE_DIR/highwater.json"
HIGHWATER_LOCK_DIR="$CACHE_DIR/highwater.lock"
HIGHWATER_LOCK_MAX_AGE=10
HIGHWATER_RESET_SKEW_MAX=7200 # tolerate session jitter, reject crossed windows
RATE_WARN_PCT=70
RATE_ALERT_PCT=90

# Context thresholds compare percent remaining, so they trip from below rather than above:
# 15 means "15% left", not "15% used".
CONTEXT_WARN_PCT=50
CONTEXT_ALERT_PCT=20

input=$(cat)

# Field separator for jq output. ASCII 31 is not IFS whitespace, so empty fields survive `read`
# instead of collapsing into their neighbours the way a tab would.
sep=$(printf '\037')

# `pct` reduces a numeric field to whole percent and turns an absent one into an empty string.
jq_pct='def pct: if type == "number" then (round | tostring) else "" end;'

jq_full='[
  (.context_window.total_input_tokens // 0 | tostring),
  (.context_window.total_output_tokens // 0 | tostring),
  (.context_window.context_window_size // 0 | tostring),
  (.context_window.remaining_percentage | pct),
  (.rate_limits.five_hour.used_percentage | pct),
  (.rate_limits.five_hour.resets_at // "" | tostring),
  (.rate_limits.seven_day.used_percentage | pct),
  (.rate_limits.seven_day.resets_at // "" | tostring),
  (.cwd // .workspace.current_dir // "" | tostring),
  (.model.display_name // "" | tostring),
  (.effort.level // "" | tostring),
  (.version // "" | tostring)
] | join("\u001f")'

jq_highwater='[
  (.five_hour.used_percentage | pct),
  (.five_hour.resets_at // "" | tostring),
  (.seven_day.used_percentage | pct),
  (.seven_day.resets_at // "" | tostring)
] | join("\u001f")'

cache_file_mtime() {
  local path="$1"
  local ts=""
  ts=$(stat -c %Y "$path" 2>/dev/null || true)
  if [ -z "$ts" ]; then
    ts=$(stat -f %m "$path" 2>/dev/null || true)
  fi
  printf '%s\n' "${ts:-0}"
}

is_uint() {
  case "$1" in
  '' | null) return 1 ;;
  *[!0-9]*) return 1 ;;
  *) return 0 ;;
  esac
}

acquire_highwater_lock() {
  mkdir -p "$CACHE_DIR" 2>/dev/null || return 1
  local attempts=0 lock_mtime now
  while [ "$attempts" -lt 5 ]; do
    attempts=$((attempts + 1))
    if mkdir "$HIGHWATER_LOCK_DIR" 2>/dev/null; then
      return 0
    fi
    lock_mtime=$(cache_file_mtime "$HIGHWATER_LOCK_DIR")
    now=$(date +%s)
    if [ $((now - lock_mtime)) -gt "$HIGHWATER_LOCK_MAX_AGE" ]; then
      rmdir "$HIGHWATER_LOCK_DIR" 2>/dev/null || true
      continue
    fi
    sleep 0.05
  done
  return 1
}

release_highwater_lock() {
  rmdir "$HIGHWATER_LOCK_DIR" 2>/dev/null || true
}

read_highwater() {
  hw_5h_pct=""
  hw_5h_reset=""
  hw_7d_pct=""
  hw_7d_reset=""
  [ -f "$HIGHWATER_FILE" ] || return
  local row
  row=$(jq -r "$jq_pct$jq_highwater" "$HIGHWATER_FILE" 2>/dev/null)
  IFS="$sep" read -r hw_5h_pct hw_5h_reset hw_7d_pct hw_7d_reset <<<"$row"
  is_uint "$hw_5h_pct" || hw_5h_pct=""
  is_uint "$hw_5h_reset" || hw_5h_reset=""
  is_uint "$hw_7d_pct" || hw_7d_pct=""
  is_uint "$hw_7d_reset" || hw_7d_reset=""
}

# Merge one window's live value with its stored high water mark.
# A live value that is missing or already reset leaves the segment hidden: the session is not
# reporting rate limits, and a stale number from an earlier session must not stand in for it.
# Sets applied_pct / applied_reset / applied_hw_pct / applied_hw_reset.
merge_highwater() {
  local live_pct="$1" live_reset="$2" hw_pct="$3" hw_reset="$4"
  local reset_diff

  applied_pct=""
  applied_reset=""
  applied_hw_pct=""
  applied_hw_reset=""

  is_uint "$live_pct" && is_uint "$live_reset" || return
  [ -n "$now_epoch" ] || now_epoch=$(date +%s)
  [ "$live_reset" -le "$now_epoch" ] && return

  if is_uint "$hw_pct" && is_uint "$hw_reset"; then
    reset_diff=$((live_reset - hw_reset))
    [ "$reset_diff" -lt 0 ] && reset_diff=$((-reset_diff))
    if [ "$reset_diff" -gt "$HIGHWATER_RESET_SKEW_MAX" ] || [ "$hw_reset" -le "$now_epoch" ]; then
      hw_pct=""
    fi
  else
    hw_pct=""
  fi

  if is_uint "$hw_pct" && [ "$hw_pct" -gt "$live_pct" ]; then
    applied_pct="$hw_pct"
  else
    applied_pct="$live_pct"
  fi
  applied_reset="$live_reset"
  applied_hw_pct="$applied_pct"
  applied_hw_reset="$applied_reset"
}

apply_highwater_all() {
  now_epoch=""
  read_highwater

  merge_highwater "$five_pct" "$five_reset" "$hw_5h_pct" "$hw_5h_reset"
  five_pct="$applied_pct"
  new_hw_5h_pct="$applied_hw_pct"
  new_hw_5h_reset="$applied_hw_reset"

  merge_highwater "$seven_pct" "$seven_reset" "$hw_7d_pct" "$hw_7d_reset"
  seven_pct="$applied_pct"
  new_hw_7d_pct="$applied_hw_pct"
  new_hw_7d_reset="$applied_hw_reset"
}

write_highwater() {
  is_uint "$new_hw_5h_pct" || is_uint "$new_hw_7d_pct" || return
  # Runs on every render, but the mark only moves when a percentage rises: skip the
  # write-and-rename when the stored mark already says the same thing.
  if [ "$new_hw_5h_pct" = "$hw_5h_pct" ] && [ "$new_hw_5h_reset" = "$hw_5h_reset" ] &&
    [ "$new_hw_7d_pct" = "$hw_7d_pct" ] && [ "$new_hw_7d_reset" = "$hw_7d_reset" ]; then
    return
  fi
  mkdir -p "$CACHE_DIR" 2>/dev/null || return
  local r5="${new_hw_5h_reset:-0}" r7="${new_hw_7d_reset:-0}"
  is_uint "$r5" || r5=0
  is_uint "$r7" || r7=0
  {
    printf '{\n'
    if is_uint "$new_hw_5h_pct"; then
      printf '  "five_hour": {"used_percentage": %s, "resets_at": %s}' "$new_hw_5h_pct" "$r5"
      is_uint "$new_hw_7d_pct" && printf ','
      printf '\n'
    fi
    if is_uint "$new_hw_7d_pct"; then
      printf '  "seven_day": {"used_percentage": %s, "resets_at": %s}\n' "$new_hw_7d_pct" "$r7"
    fi
    printf '}\n'
  } >"${HIGHWATER_FILE}.tmp" 2>/dev/null &&
    mv "${HIGHWATER_FILE}.tmp" "$HIGHWATER_FILE" 2>/dev/null
}

# Single jq pass over the live input; every other field is derived from these values.
used_tokens="0"
output_tokens="0"
window_size="0"
remaining_pct=""
five_pct=""
five_reset=""
seven_pct=""
seven_reset=""
cwd=""
model_display=""
effort_level=""
cc_version=""

parsed=""
[ -n "$input" ] && parsed=$(printf '%s' "$input" | jq -r "$jq_pct$jq_full" 2>/dev/null)
IFS="$sep" read -r used_tokens output_tokens window_size remaining_pct five_pct five_reset seven_pct \
  seven_reset cwd model_display effort_level cc_version <<<"$parsed"

is_uint "$used_tokens" || used_tokens="0"
is_uint "$output_tokens" || output_tokens="0"
is_uint "$window_size" || window_size="0"

new_hw_5h_pct=""
new_hw_5h_reset=""
new_hw_7d_pct=""
new_hw_7d_reset=""
if acquire_highwater_lock; then
  apply_highwater_all
  write_highwater
  release_highwater_lock
else
  apply_highwater_all
fi

# --- Colors ---
# ANSI-C quoting puts the real escape bytes in the variables, so the final print can use %s.
# Under %b, any backslash in the line gets read as an escape: a directory named `dir\twith`
# renders a tab, and one named `dir\cwith` truncates the line from there on.
RESET=$'\033[0m'
DIM=$'\033[2m'
YELLOW=$'\033[33m'
RED=$'\033[31m'
CYAN=$'\033[36m'
BRIGHT_GREEN=$'\033[92m'
BRIGHT_CYAN=$'\033[96m'
BRIGHT_MAGENTA=$'\033[95m'

# 1. Working directory + git branch
if [ -z "$cwd" ]; then
  cwd=$(pwd)
fi
cwd_display="${cwd/#$HOME/~}"

# One git call in the common case: symbolic-ref prints the branch name straight from HEAD, so it
# still answers in a repository with no commits yet. It prints nothing for a detached HEAD or
# outside a repository; the second call tells those apart and names the detached commit.
git_branch=""
git_head=""
git_branch=$(git -C "$cwd" symbolic-ref --short -q HEAD 2>/dev/null)
if [ -z "$git_branch" ]; then
  git_head=$(git -C "$cwd" rev-parse --short HEAD 2>/dev/null)
fi

if [ -n "$git_branch" ]; then
  location_part="${CYAN}${cwd_display}${RESET} ${DIM}on${RESET} ${YELLOW}${git_branch}${RESET}"
elif [ -n "$git_head" ]; then
  location_part="${CYAN}${cwd_display}${RESET} ${DIM}on${RESET} ${YELLOW}@${git_head}${RESET}"
else
  location_part="${CYAN}${cwd_display}${RESET}"
fi

# 2. Window remaining percentage, preferring the value Claude Code already computed
if [ -z "$remaining_pct" ] && [ "$window_size" -gt 0 ]; then
  remaining_pct=$((100 - used_tokens * 100 / window_size))
fi

if [ -n "$remaining_pct" ]; then
  if [ "$remaining_pct" -le "$CONTEXT_ALERT_PCT" ]; then
    remaining_color="$RED"
  elif [ "$remaining_pct" -le "$CONTEXT_WARN_PCT" ]; then
    remaining_color="$YELLOW"
  else
    remaining_color="$BRIGHT_GREEN"
  fi
  window_part="${DIM}Context${RESET} ${remaining_color}${remaining_pct}%${RESET} ${DIM}left${RESET}"
else
  window_part="${DIM}Context --${RESET}"
fi

# 3. Model and effort level
if [ -n "$model_display" ]; then
  if [ -n "$effort_level" ]; then
    model_part="${BRIGHT_MAGENTA}${model_display}${RESET} ${DIM}${effort_level}${RESET}"
  else
    model_part="${BRIGHT_MAGENTA}${model_display}${RESET}"
  fi
else
  model_part="${DIM}--${RESET}"
fi

# 4. Context tokens, input and output separate
#
# `total_input_tokens` is everything in context apart from the newest response; the context
# percentage counts input only, so it lines up with the "in" number, not with the sum.
# `total_output_tokens` covers the most recent response alone, and reads 0 before the first
# response of a session and just after /compact.
#
# Sets `scaled`; a function rather than command substitution because a subshell would fork.
scaled=""
scale_tokens() {
  if [ "$1" -ge 1000000 ]; then
    scaled="$(($1 / 1000000)).$(($1 % 1000000 / 100000))M"
  elif [ "$1" -ge 1000 ]; then
    scaled="$(($1 / 1000)).$(($1 % 1000 / 100))K"
  else
    scaled="$1"
  fi
}

scale_tokens "$used_tokens"
tokens_part="${BRIGHT_CYAN}${scaled}${RESET} ${DIM}in${RESET}"
if [ "$output_tokens" -gt 0 ]; then
  scale_tokens "$output_tokens"
  tokens_part="$tokens_part ${DIM}·${RESET} ${BRIGHT_CYAN}${scaled}${RESET} ${DIM}out${RESET}"
fi

# 5. Rate limits, present only when this session reports them (Claude.ai subscription sessions)
rate_color_var() {
  if [ "$1" -ge "$RATE_ALERT_PCT" ]; then
    rate_color="$RED"
  elif [ "$1" -ge "$RATE_WARN_PCT" ]; then
    rate_color="$YELLOW"
  else
    rate_color="$BRIGHT_GREEN"
  fi
}

rate_5h=""
rate_7d=""
if is_uint "$five_pct"; then
  rate_color_var "$five_pct"
  rate_5h="${DIM}5h${RESET} ${rate_color}${five_pct}%${RESET}"
fi
if is_uint "$seven_pct"; then
  rate_color_var "$seven_pct"
  rate_7d="${DIM}7d${RESET} ${rate_color}${seven_pct}%${RESET}"
fi

if [ -n "$rate_5h" ] && [ -n "$rate_7d" ]; then
  rate_part="${rate_5h} ${DIM}·${RESET} ${rate_7d}"
elif [ -n "$rate_5h" ]; then
  rate_part="$rate_5h"
elif [ -n "$rate_7d" ]; then
  rate_part="$rate_7d"
else
  rate_part=""
fi

# 6. Claude Code version (from stdin JSON; avoid forking `claude --version`)
if [ -n "$cc_version" ]; then
  version_part="${DIM}v${cc_version}${RESET}"
else
  version_part="${DIM}v?${RESET}"
fi

line="$model_part | $location_part | $window_part | $tokens_part"
[ -n "$rate_part" ] && line="$line | $rate_part"
line="$line | $version_part"
printf '%s\n' "$line"
