"""Run confirmed installation and lifecycle operations."""

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path

from content.paths import safe_root
from agents.list_installed import executable_entries
from agents.statusline_settings import install_setting

from .screen import Back, stream_command


AGENTS = {"codex": "Codex", "claude": "Claude Code", "pi": "Pi"}
BUNDLES = {
    "claude": ("Claude statusline",),
    "pi": ("npm:pi-web-access", "npm:pi-subagents", "npm:pi-powerline-footer"),
}
INSTALLERS = {
    "codex": ("https://chatgpt.com/codex/install.sh", "sh"),
    "claude": ("https://claude.ai/install.sh", "bash"),
    "pi": ("https://pi.dev/install.sh", "sh"),
}
ACTION_ERRORS = (OSError, ValueError, RuntimeError, subprocess.SubprocessError)


def require(command, env=None):
    path = shutil.which(command, path=None if env is None else env.get("PATH"))
    if not path:
        raise ValueError(f"Required command not found: {command}")
    return path


def node_environment(home):
    if shutil.which("node"):
        return None
    script = Path(os.environ.get("NVM_DIR") or home / ".nvm") / "nvm.sh"
    if script.is_file():
        result = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1" --no-use >&2 && nvm use --silent default >&2 && "$2" -c "$3"',
                "manage-tools",
                str(script),
                sys.executable,
                "import json, os; print(json.dumps(dict(os.environ)))",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
        )
        if result.returncode == 0:
            env = json.loads(result.stdout)
            require("node", env)
            return env
    raise ValueError(
        "Node.js is unavailable. Install Node.js or activate the default nvm version."
    )


def command_paths(agent):
    paths = [
        os.path.join(os.getcwd(), directory) for directory in os.get_exec_path()
    ]
    return "\n".join(entry for entry, _ in executable_entries(agent, paths))


class Execution:
    def __init__(self, screen, work):
        self.screen = screen
        self.work = work
        self.lines = []
        self.failed = 0
        self.completed = 0
        self.title = ""

    def write(self, text):
        fragments = text.split("\n")
        if not self.lines:
            self.lines.append("")
        self.lines[-1] += fragments[0]
        self.lines.extend(fragments[1:])
        return len(text)

    def flush(self):
        pass

    def progress(self, lines):
        for line in lines:
            self.write(line + "\n")
        self.screen.busy(self.title, self.lines)

    def command(self, args, **kwargs):
        stream_command(args, self.progress, **kwargs)

    def report(self, text):
        self.progress([text])

    def item(self, label, operation, *args):
        self.report(f"==> {label}")
        try:
            operation(*args)
        except Back:
            self.report("Cancelled.")
        except ACTION_ERRORS as error:
            self.failed += 1
            self.report(f"FAIL {label}: {error}")
            return False
        else:
            self.completed += 1
        return True

    def install_agent(self, agent, home, statusline, environment):
        label = f"{AGENTS[agent]} CLI"
        if self.item(label, self.install_cli, agent, environment):
            if agent == "claude":
                self.item(
                    "Claude statusline", self.statusline, home, statusline
                )
            elif agent == "pi":
                for package in BUNDLES[agent]:
                    self.item(
                        package, self.install_pi_package, package, environment
                    )
        else:
            for bundle in BUNDLES.get(agent, ()):
                self.failed += 1
                self.report(
                    f"{bundle}: skipped because {label} installation failed"
                )

    def install_pi_package(self, package, environment):
        self.command(["pi", "install", package], env=environment)

    def install_cli(self, agent, env):
        if not shutil.which(
            agent, path=None if env is None else env.get("PATH")
        ):
            url, shell = INSTALLERS[agent]
            installer = self.work / f"{agent}-install.sh"
            try:
                self.command(["curl", "-fsSL", url, "-o", str(installer)])
                # Pass the installer as standard input, as the documented vendor pipeline does.
                with installer.open("rb") as script:
                    self.command([shell], env=env, stdin=script)
            finally:
                installer.unlink(missing_ok=True)
        path = require(agent, env)
        self.report(f"{AGENTS[agent]} CLI: {path}")
        if agent == "pi":
            self.command([path, "--version"], env=env)

    def statusline(self, home, source):
        safe_root(str(home), "HOME")
        directory = home / ".claude"
        directory.mkdir(parents=True, exist_ok=True)
        script = directory / "statusline.sh"
        target = directory / "settings.json"
        self.command(["install", "-m", "0755", str(source), str(script)])
        install_setting(target, "~/.claude/statusline.sh")
        self.report(f"Statusline: {script}; settings: {target}")

    def optional(self, action, agent, items, selected):
        picked = self.screen.multi(
            f"Agent / {action} / {AGENTS[agent]} / Optional items",
            [item.description for item in items],
            selected,
        )
        return [items[index] for index in picked]

    def review(self, details, *, can_edit):
        try:
            return self.confirm("Execution preview", details)
        except Back:
            if not can_edit:
                raise
            return None

    def confirm(self, title, details):
        return self.screen.confirm(title, details)

    def native(self, command, *, env=None):
        self.screen.native(command, env=env, cwd="/")
