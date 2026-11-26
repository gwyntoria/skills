"""Run confirmed installation and lifecycle operations."""

import os
import re
import sys
import json
import shutil
import subprocess
from pathlib import Path

from content.paths import SKILL_DIRECTORIES, display, safe_root
from agents.list_installed import AGENTS, executable_entries
from agents.statusline_settings import install_setting

from .screen import Back, paint, stream_command


BUNDLES = {
    "claude": ("Claude statusline",),
    "pi": ("npm:pi-web-access", "npm:pi-subagents", "npm:pi-powerline-footer"),
}
INSTALLERS = {
    "codex": ("https://chatgpt.com/codex/install.sh", "sh"),
    "claude": ("https://claude.ai/install.sh", "bash"),
    "pi": ("https://pi.dev/install.sh", "sh"),
    "agy": ("https://antigravity.google/cli/install.sh", "bash"),
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


def cli_label(agent):
    return AGENTS[agent] if agent == "agy" else f"{AGENTS[agent]} CLI"


def installed_skill_name(name):
    # The skills installer normalizes catalog names when choosing directory names.
    return re.sub(r"[^a-z0-9._]+", "-", name.lower()).strip(".-")[:255]


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
        self.report(paint("1;36", f"==> {label}"))
        try:
            if operation(*args) is False:
                return False
        except Back:
            self.report("Cancelled.")
        except ACTION_ERRORS as error:
            self.failed += 1
            self.report(paint("1;31", f"FAIL {label}: {error}"))
            return False
        else:
            self.completed += 1
        return True

    def install_agent(self, agent, home, statusline, environment):
        label = cli_label(agent)
        if self.item(label, self.install_cli, agent, home, environment):
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

    def install_cli(self, agent, home, env):
        search_path = None if env is None else env.get("PATH")
        if agent == "agy":
            search_path = os.pathsep.join(
                (*os.get_exec_path(env), str(home / ".local/bin"))
            )
        if not shutil.which(agent, path=search_path):
            url, shell = INSTALLERS[agent]
            installer = self.work / f"{agent}-install.sh"
            try:
                self.command(["curl", "-fsSL", url, "-o", str(installer)])
                # Pass the installer as standard input, as the documented vendor pipeline does.
                with installer.open("rb") as script:
                    self.command([shell], env=env, stdin=script)
            finally:
                installer.unlink(missing_ok=True)
        path = shutil.which(agent, path=search_path)
        if path is None:
            raise ValueError(f"Required command not found: {agent}")
        self.report(f"{cli_label(agent)}: {path}")
        if agent in ("pi", "agy"):
            self.command([path, "--version"], env=env)

    def link_antigravity_skills(self, home, names):
        safe_root(str(home), "HOME")
        shared = home / SKILL_DIRECTORIES["codex"]
        folder = home / SKILL_DIRECTORIES["agy"]
        for path in (folder.parent.parent, folder.parent, folder):
            if path.is_symlink():
                note = (
                    "skills already use Shared"
                    if os.path.realpath(folder) == os.path.realpath(shared)
                    else "retained existing directory link"
                )
                self.report(
                    paint(
                        "1;33",
                        f"Skipped Antigravity skill links: {note}: {display(path)}",
                    )
                )
                return
        try:
            folder.mkdir(parents=True, exist_ok=True)
            directory_fd = os.open(
                folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
        except OSError as error:
            self.failed += 1
            self.report(
                paint("1;31", f"FAIL Antigravity CLI skill links: {error}")
            )
            return
        try:
            for name in names:
                self.item(
                    f"Link Antigravity skill: {name}",
                    self.link_skill,
                    shared / installed_skill_name(name),
                    folder,
                    directory_fd,
                )
        finally:
            os.close(directory_fd)

    def link_skill(self, source, folder, directory_fd):
        destination = folder / source.name
        if not (source / "SKILL.md").is_file():
            raise ValueError(f"Skill missing from Shared: {display(source)}")
        try:
            os.symlink(source, source.name, dir_fd=directory_fd)
        except FileExistsError:
            self.report(
                paint("1;33", f"Skipped existing skill: {display(destination)}")
            )
            return False
        self.report(f"Linked: {display(destination)} -> {display(source)}")
        return True

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
        return self.screen.confirm(title, details, destructive=True)

    def native(self, command, *, env=None):
        self.screen.native(command, env=env, cwd="/")
