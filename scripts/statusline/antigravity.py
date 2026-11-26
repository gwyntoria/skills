#!/usr/bin/env python3
"""Custom Powerline statusline script for Antigravity CLI (agy)."""

from datetime import datetime
import json
import os
import socket
import subprocess
import sys

RESET = "\033[0m"
BOLD = "\033[1m"

# Powerline Nerd Font glyphs (BMP range for wide Nerd Font compatibility)
PL_LEFT_CAP = "\ue0b6"
PL_RIGHT_CAP = "\ue0b4"
PL_SEP = "\ue0b0"

ICON_DIR = "\uf07c"
ICON_GIT = "\ue725"
ICON_CLOCK = "\uf017"
ICON_HOST = "\uf233"
ICON_MODEL = "\uf0e7"
ICON_CTX = "\uf080"
ICON_IDLE = "\uf00c"
ICON_WORK = "\uf085"
ICON_TOOL = "\uf0ad"
ICON_OTHER = "\uf110"

# Catppuccin Mocha-inspired 24-bit palette
BG_HOST = (137, 180, 250)     # Blue
FG_HOST = (24, 24, 37)
BG_DIR = (49, 50, 68)         # Surface0
FG_DIR = (205, 214, 244)
BG_GIT = (69, 71, 90)         # Surface1
FG_GIT = (166, 227, 161)
BG_TIME = (30, 30, 46)        # Base
FG_TIME = (166, 173, 200)

BG_MODEL = (203, 166, 247)    # Mauve
FG_MODEL = (24, 24, 37)
BG_STATE_IDLE = (166, 227, 161)
BG_STATE_WORK = (249, 226, 175)
BG_STATE_TOOL = (250, 179, 135)
BG_STATE_OTHER = (180, 190, 254)
FG_STATE = (24, 24, 37)
BG_CTX = (49, 50, 68)
FG_CTX = (205, 214, 244)

CTX_GREEN = (166, 227, 161)
CTX_YELLOW = (249, 226, 175)
CTX_RED = (243, 139, 168)


def fg(rgb: tuple[int, int, int]) -> str:
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def bg(rgb: tuple[int, int, int]) -> str:
    return f"\033[48;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def render_powerline(segments: list[tuple[tuple[int, int, int], str]]) -> str:
    """Render contiguous Powerline segments with rounded caps and arrow transitions."""
    if not segments:
        return ""
    parts: list[str] = []
    first_bg, _ = segments[0]
    parts.append(f"{fg(first_bg)}{PL_LEFT_CAP}")
    for idx, (seg_bg, text) in enumerate(segments):
        parts.append(f"{bg(seg_bg)} {text} ")
        if idx + 1 < len(segments):
            next_bg, _ = segments[idx + 1]
            parts.append(f"{RESET}{fg(seg_bg)}{bg(next_bg)}{PL_SEP}")
        else:
            parts.append(f"{RESET}{fg(seg_bg)}{PL_RIGHT_CAP}{RESET}")
    return "".join(parts)


def format_dir(cwd: str) -> str:
    if not cwd:
        return "~"
    home = os.path.expanduser("~")
    display = "~" + cwd[len(home):] if cwd == home or cwd.startswith(home + os.sep) else cwd
    parts = [p for p in display.split(os.sep) if p]
    if display.startswith("~"):
        if len(parts) > 3:
            return os.path.join("~", "…", parts[-2], parts[-1])
        return display
    if len(parts) > 3:
        return os.path.join(os.sep, "…", parts[-2], parts[-1])
    return display


def get_git_status(cwd: str) -> dict | None:
    if not cwd or not os.path.isdir(cwd):
        return None
    try:
        proc = subprocess.run(
            ["git", "--no-optional-locks", "-C", cwd, "status", "--porcelain=v2", "--branch"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if proc.returncode != 0:
        return None

    branch = ""
    oid = ""
    ahead = 0
    behind = 0
    staged = 0
    modified = 0
    untracked = 0

    for line in proc.stdout.splitlines():
        if line.startswith("# branch.head "):
            branch = line[len("# branch.head "):].strip()
        elif line.startswith("# branch.oid "):
            oid = line[len("# branch.oid "):].strip()
        elif line.startswith("# branch.ab "):
            for token in line[len("# branch.ab "):].split():
                if token.startswith("+"):
                    ahead = int(token[1:] or 0)
                elif token.startswith("-"):
                    behind = int(token[1:] or 0)
        elif line.startswith(("1 ", "2 ")):
            xy = line.split(" ", 2)[1]
            if len(xy) >= 2:
                if xy[0] != ".":
                    staged += 1
                if xy[1] != ".":
                    modified += 1
        elif line.startswith("u "):
            modified += 1
        elif line.startswith("? "):
            untracked += 1

    if branch == "(detached)":
        branch = f"@{oid[:7]}" if oid and oid != "(initial)" else "@HEAD"
    elif not branch:
        branch = "HEAD"

    return {
        "branch": branch,
        "ahead": ahead,
        "behind": behind,
        "staged": staged,
        "modified": modified,
        "untracked": untracked,
    }


def build_git_text(info: dict) -> str:
    pieces = [f"{fg(FG_GIT)}{BOLD}{ICON_GIT} {info['branch']}{RESET}{bg(BG_GIT)}"]
    counts: list[str] = []
    if info["staged"]:
        counts.append(f"{fg((166, 227, 161))}+{info['staged']}")
    if info["modified"]:
        counts.append(f"{fg((249, 226, 175))}~{info['modified']}")
    if info["untracked"]:
        counts.append(f"{fg((243, 139, 168))}?{info['untracked']}")
    if info["ahead"]:
        counts.append(f"{fg((137, 220, 235))}↑{info['ahead']}")
    if info["behind"]:
        counts.append(f"{fg((250, 179, 135))}↓{info['behind']}")
    if counts:
        pieces.append(" " + " ".join(counts))
    return "".join(pieces)


def build_context_text(ctx: dict) -> str:
    pct = float(ctx.get("used_percentage") or 0.0)
    pct = max(0.0, min(100.0, pct))

    if pct < 60.0:
        bar_color = CTX_GREEN
    elif pct <= 85.0:
        bar_color = CTX_YELLOW
    else:
        bar_color = CTX_RED

    bar_width = 6
    filled = int(round((pct / 100.0) * bar_width))
    bar = "█" * filled + "░" * (bar_width - filled)
    return f"{fg(bar_color)}{ICON_CTX} {bar} {pct:.0f}%"


def format_model_label(model: dict) -> str:
    model_name = str(model.get("display_name") or model.get("id") or "unknown")
    effort = str(model.get("effort") or "").strip()
    if effort and f"({effort.lower()})" not in model_name.lower() and f"[{effort.lower()}]" not in model_name.lower():
        return f"{model_name} [{effort}]"
    return model_name


def build_statusline(payload: dict) -> str:
    segments: list[tuple[tuple[int, int, int], str]] = []

    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        host = socket.gethostname().split(".")[0]
        segments.append((BG_HOST, f"{fg(FG_HOST)}{BOLD}{ICON_HOST} {host}"))

    model = payload.get("model") or {}
    segments.append((BG_MODEL, f"{fg(FG_MODEL)}{BOLD}{ICON_MODEL} {format_model_label(model)}"))

    state = str(payload.get("agent_state") or "idle")
    state_map = {
        "idle": (BG_STATE_IDLE, ICON_IDLE),
        "working": (BG_STATE_WORK, ICON_WORK),
        "thinking": (BG_STATE_WORK, ICON_WORK),
        "tool_use": (BG_STATE_TOOL, ICON_TOOL),
    }
    state_bg, state_icon = state_map.get(state, (BG_STATE_OTHER, ICON_OTHER))
    segments.append((state_bg, f"{fg(FG_STATE)}{BOLD}{state_icon} {state}"))

    workspace = payload.get("workspace") or {}
    cwd = workspace.get("current_dir") or payload.get("cwd") or ""
    segments.append((BG_DIR, f"{fg(FG_DIR)}{ICON_DIR} {format_dir(cwd)}"))

    git_info = get_git_status(cwd)
    if git_info:
        segments.append((BG_GIT, build_git_text(git_info)))

    ctx = payload.get("context_window") or {}
    segments.append((BG_CTX, build_context_text(ctx)))

    now = datetime.now().strftime("%H:%M")
    segments.append((BG_TIME, f"{fg(FG_TIME)}{ICON_CLOCK} {now}"))

    return render_powerline(segments)


def main() -> int:
    raw = sys.stdin.read().strip()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    sys.stdout.write(f"{build_statusline(payload)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
