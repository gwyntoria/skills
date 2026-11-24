"""Plan, confirm and apply Agent cleanup or uninstall for the current user."""

import os
import re
import sys
import json
import stat
import signal
import subprocess
from os.path import join, dirname, basename, normpath, realpath
from tempfile import NamedTemporaryFile
from dataclasses import field, dataclass

from picker import pick_optional
from profiles import PROFILES
from user_paths import (
    Step,
    UserPaths,
    info,
    show,
    is_dir,
    within,
    is_file,
    is_link,
    identity,
    checked_command,
)


NPM_PACKAGES = {
    "codex": ("@openai/codex",),
    "claude": ("@anthropic-ai/claude-code",),
    "pi": ("@earendil-works/pi-coding-agent", "@mariozechner/pi-coding-agent"),
}
BREW_PREFIXES = ("/opt/homebrew", "/usr/local", "/home/linuxbrew/.linuxbrew")
UNINSTALL_GUIDE = {
    "codex": "https://developers.openai.com/codex/cli",
    "claude": "https://code.claude.com/docs/en/setup#uninstall-claude-code",
    "pi": "https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/quickstart.md#uninstall-pi",
}


@dataclass
class Installation:
    method: str
    files: list[str] = field(default_factory=list)
    root: str | None = None
    launcher: str | None = None
    outside_links: list[str] = field(default_factory=list)
    command: Step | None = None


def real(path):
    return realpath(path, strict=True)


def link_target(path):
    return normpath(join(dirname(path), os.readlink(path)))


def color(text, sgr):
    if (
        sys.stdout.isatty()
        and os.environ.get("TERM", "dumb") != "dumb"
        and not os.environ.get("NO_COLOR")
    ):
        return f"\033[{sgr}m{text}\033[0m"
    return text


def ask(prompt):
    try:
        return input(color(prompt, "1;33")).strip()
    except EOFError:
        return ""


def run(program, args, *, env=None, interactive=False):
    command = [program, *args]
    options = (
        {}
        if interactive
        else {"capture_output": True, "stdin": subprocess.DEVNULL}
    )
    try:
        result = subprocess.run(
            command, cwd="/", env=env, check=True, text=True, **options
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(
            "Command failed: " + " ".join(map(show, command))
        ) from error
    return result.stdout


def unused_claude_version(path):
    # lsof exits 1 with empty output when no process holds the file.
    try:
        result = subprocess.run(
            ["lsof", "-t", "--", path],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 1 and not result.stdout and not result.stderr


class Lifecycle:
    def __init__(
        self, action, agent, command_paths, statusline_source, packages
    ):
        if action not in ("Cleanup", "Uninstall") or agent not in PROFILES:
            raise ValueError("Invalid Agent lifecycle action or Agent")
        self.action = action
        self.agent = agent
        self.uninstall = action == "Uninstall"
        self.home = os.environ.get("HOME")
        self.warnings = {}
        self.user = UserPaths(self.home, self.uninstall, self.warnings)
        self.whole_directory = None
        self.required = []
        self.optional = []
        self.credentials = []
        self.command_paths = list(
            dict.fromkeys(filter(None, command_paths.split("\n")))
        )
        self.statusline_source = statusline_source
        self.packages = packages
        self.profile = PROFILES[agent]
        self.fallback = join(self.home, self.profile["fallback"])
        self.configured = self.expand_home(
            os.environ.get(self.profile["override"]) or self.fallback
        )
        self.roots = list(dict.fromkeys([self.fallback, self.configured]))

    def warn(self, message):
        self.warnings[message] = None

    def covered_by_directory(self, path):
        return (
            self.whole_directory
            and (
                path == self.whole_directory
                or within(self.whole_directory, path)
            )
            and normpath(path) == path
        )

    def add(self, steps, path, label, recursive=False):
        item = self.user.removal(path, label, recursive)
        if item is not None:
            steps.append(item)

    def expand_home(self, path):
        return join(self.home, path[2:]) if path.startswith("~/") else path

    def claude_install(self):
        return normpath(
            join(
                os.environ.get("XDG_DATA_HOME")
                or join(self.home, ".local/share"),
                "claude",
            )
        )

    def verified_pi_uninstall_alias(
        self, executable_info, launcher, entrypoint
    ):
        entry = entrypoint.get("path")
        if (
            not self.uninstall
            or not is_link(executable_info)
            or entrypoint.get("type") != "symlink"
            or not isinstance(entry, str)
            or not self.user.safe(entry)
            or not is_link(info(entry))
        ):
            return False
        try:
            return real(entry) == launcher
        except FileNotFoundError:
            return False

    def managed_pi(self, executable):
        executable_info = info(executable)
        if executable_info is None or (
            not self.user.safe(executable) and not is_link(executable_info)
        ):
            return None
        launcher = real(executable)
        if (
            not self.user.safe(launcher)
            or not is_file(info(launcher))
            or basename(launcher) != "pi"
            or basename(dirname(launcher)) != "bin"
        ):
            return None
        install = normpath(join(dirname(launcher), "../install"))
        marker = self.user.json(join(install, "managed-install.json"))
        entrypoint = marker.get("entrypoint")
        if not isinstance(entrypoint, dict):
            return None
        entry = entrypoint.get("path")
        is_alias = entry not in (launcher, executable)
        if (
            marker.get("kind") != "pi-managed-install"
            or marker.get("schemaVersion") != 1
            or marker.get("layout") != "releases-v1"
            or not isinstance(entry, str)
            or not os.path.isabs(entry)
            or (
                is_alias
                and not (self.uninstall and executable == launcher)
                and not self.verified_pi_uninstall_alias(
                    executable_info, launcher, entrypoint
                )
            )
        ):
            return None
        files = [launcher]
        outside_links = []
        for path in dict.fromkeys([entry if is_alias else executable, entry]):
            if (
                path == launcher
                or not is_link(info(path))
                or realpath(path) != launcher
            ):
                continue
            if self.user.safe(path):
                files.append(path)
            elif path == entry and entrypoint.get("type") == "symlink":
                outside_links.append(path)
            else:
                return None
        return Installation(
            "Pi managed installer", files, install, launcher, outside_links
        )

    def cli_installation(self, executable):
        if not self.user.safe(executable) or info(executable) is None:
            return None
        target = real(executable)
        if not self.user.safe(target):
            return None
        if self.agent == "codex" and is_link(info(executable)):
            for root in self.roots:
                install = normpath(join(root, "packages/standalone"))
                if not within(join(install, "releases"), target):
                    continue
                if link_target(executable) not in (
                    join(install, "current/codex"),
                    join(install, "current/bin/codex"),
                ):
                    continue
                companion = join(dirname(executable), "codex-code-mode-host")
                files = [executable]
                if is_link(info(companion)) and link_target(companion) == join(
                    install, "current/bin/codex-code-mode-host"
                ):
                    files.append(companion)
                return Installation("Codex standalone", files, install)
        if self.agent == "claude" and is_link(info(executable)):
            install = self.claude_install()
            if within(join(install, "versions"), target):
                return Installation("Claude native", [executable], install)
        return self.npm_installation(executable)

    def npm_installation(self, executable, *, external_pi=False):
        prefix = dirname(dirname(executable))
        for name in NPM_PACKAGES[self.agent]:
            folder = join(prefix, "lib/node_modules", name)
            manifest = join(folder, "package.json")
            if external_pi:
                if realpath(manifest) != manifest or not is_file(
                    info(manifest)
                ):
                    continue
                with open(manifest, encoding="utf-8") as stream:
                    metadata = json.load(stream)
                if not isinstance(metadata, dict):
                    continue
            else:
                metadata = self.user.json(manifest)
            entry = metadata.get("bin")
            if isinstance(entry, dict):
                entry = entry.get(self.agent)
            if (
                executable != join(prefix, "bin", self.agent)
                or metadata.get("name") != name
                or not isinstance(entry, str)
                or not entry
                or not is_link(info(executable))
            ):
                continue
            target = normpath(join(folder, entry))
            if (
                not within(folder, target)
                or link_target(executable) != target
                or (external_pi and real(target) != target)
            ):
                continue
            npm = join(prefix, "bin/npm")
            manager = npm if info(npm) else "npm"

            def uninstall_package():
                run(
                    manager,
                    [
                        "uninstall",
                        "--global",
                        "--ignore-scripts",
                        "--prefix",
                        prefix,
                        name,
                    ],
                    interactive=True,
                )
                if info(executable) or info(folder):
                    raise ValueError("npm installation remains")

            command = checked_command(
                f"Uninstall {name} from npm prefix {show(prefix)}",
                executable,
                uninstall_package,
            )
            return Installation(
                f"npm {name} (prefix {show(prefix)})", command=command
            )
        return None

    def brew_prefix_pi(self, path, target):
        prefix = dirname(dirname(path))
        brew = join(prefix, "bin/brew")
        cellar = join(prefix, "Cellar/pi-coding-agent")
        keg = join(cellar, os.path.relpath(target, cellar).split(os.sep)[0])
        if (
            not within(cellar, target)
            or realpath(join(keg, "bin/pi")) != target
            or not os.access(brew, os.X_OK)
        ):
            return self.npm_installation(
                path, external_pi=not within(self.home, path)
            )

        def uninstall_formula():
            run(
                brew,
                ["uninstall", "--formula", "pi-coding-agent"],
                interactive=True,
            )
            if info(path):
                raise ValueError(f"Homebrew entry remains {show(path)}")

        return Installation(
            "Homebrew pi-coding-agent",
            command=checked_command(
                f"Uninstall Homebrew pi-coding-agent at {show(path)}",
                path,
                uninstall_formula,
            ),
        )

    def pi_uninstall(self):
        prefixes = {*BREW_PREFIXES, join(self.home, ".linuxbrew")}
        brew_prefix = os.environ.get("HOMEBREW_PREFIX")
        if brew_prefix and os.path.isabs(brew_prefix):
            prefixes.add(normpath(brew_prefix))
        brew_entries = {join(prefix, "bin/pi") for prefix in prefixes}
        candidates = list(
            dict.fromkeys(
                [
                    *self.command_paths,
                    join(self.home, ".local/bin/pi"),
                    *sorted(brew_entries),
                    *(join(root, "bin/pi") for root in self.roots),
                ]
            )
        )
        installations = {}
        links = {}
        for path in candidates:
            if (
                not os.path.isabs(path)
                or basename(path) != "pi"
                or not info(path)
            ):
                continue
            if not os.path.isfile(path):
                self.warn(f"Unprocessed Pi entry {show(path)}")
                continue
            target = real(path)
            links[path] = target
            if target in installations:
                continue
            installation = self.managed_pi(path) or self.cli_installation(path)
            if (
                not installation
                and path in brew_entries
                and is_link(info(path))
            ):
                installation = self.brew_prefix_pi(path, target)
            if installation:
                installations[target] = path, installation
                for entry in installation.files + installation.outside_links:
                    links[entry] = target

        if not installations:
            raise ValueError(
                "No verified Pi installation found. Checked: "
                + ", ".join(map(show, candidates))
            )
        return installations, links, brew_entries

    def pi_alias_step(self, path, target, brew_entries):
        entry = info(path)
        if not is_link(entry) or not (
            self.user.safe(path)
            or (
                path in brew_entries
                and not within(self.home, path)
                and entry.st_uid == os.getuid()
                and real(dirname(path)) == dirname(path)
                and os.access(dirname(path), os.W_OK)
            )
        ):
            self.warn(f"Unprocessed Pi entry {show(path)}")
            return None
        before = identity(path)
        parent = identity(dirname(path))

        def unlink_alias():
            if (
                identity(path) != before
                or identity(dirname(path)) != parent
                or (os.path.exists(path) and real(path) != target)
            ):
                raise ValueError(f"Pi entry changed {show(path)}")
            os.unlink(path)

        return checked_command(
            f"Remove Pi launcher link {show(path)}", path, unlink_alias
        )

    def pi_uninstall_steps(self, installations, links, brew_entries):
        aliases = []
        steps = []
        preview = []
        for path, installation in installations.values():
            preview.append(f"Selected CLI {show(path)} ({installation.method})")
            steps.extend(self.cli_steps(installation))
        for path, target in links.items():
            if target not in installations:
                self.warn(f"Unrecognized Pi entry {show(path)}")
                continue
            primary, installation = installations[target]
            if path in installation.files or (
                path == primary and installation.command
            ):
                continue
            if self.covered_by_directory(path):
                continue
            alias = self.pi_alias_step(path, target, brew_entries)
            if alias:
                aliases.append(alias)
        primary, installation = next(iter(installations.values()))
        preview.append(
            "Removing Pi settings also removes extension enablement records."
        )
        return installation.launcher or primary, preview, aliases + steps

    def scan_root(self, root):
        if not self.user.safe(root):
            self.warn(f"Unprocessed data directory {show(root)}")
            return
        entry = info(root)
        if entry is None:
            return
        if not is_dir(entry) or info(join(root, ".git")):
            self.warn(f"Unprocessed data directory {show(root)}")
            return
        for name in sorted(os.listdir(root)):
            path = join(root, name)
            if name in self.profile["entries"] or any(
                p.search(name) for p in self.profile["patterns"]
            ):
                self.add(self.required, path, "Delete user data", True)
            elif name in self.profile["content"]:
                self.scan_content(path)
            elif name not in self.profile["retained"]:
                self.warnings[f"Unrecognized Agent entry {show(path)}"] = path

    def scan_content(self, path):
        entry = info(path)
        if (
            is_dir(entry)
            and self.user.safe(path)
            and not info(join(path, ".git"))
        ):
            for child in sorted(os.listdir(path)):
                if child != ".system":
                    self.add(
                        self.optional,
                        join(path, child),
                        "Delete skill/rule entry",
                        True,
                    )
        elif not is_dir(entry):
            self.add(
                self.optional,
                path,
                "Delete whole skill/rule file or link (including handwritten content)",
            )
        else:
            self.warn(f"Unprocessed skill/rule directory {show(path)}")

    def inactive_claude_versions(self, root, active_paths):
        available = []
        for name in os.listdir(root):
            if not re.fullmatch(
                r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?", name
            ):
                continue
            path = join(root, name)
            entry = info(path)
            if (
                path not in active_paths
                and is_file(entry)
                and entry.st_nlink == 1
                and entry.st_mode & stat.S_IXUSR
                and self.user.safe(path)
            ):
                available.append((entry.st_mtime_ns, path))
        return available

    def claude_version_candidates(self, root, launcher):
        try:
            if not self.user.safe(launcher) or not is_link(info(launcher)):
                return []
            active = real(launcher)
            if (
                dirname(active) != root
                or not self.user.safe(active)
                or not is_file(info(active))
            ):
                return []
            active_paths = {
                active,
                *(
                    real(path)
                    for path in self.command_paths
                    if os.path.exists(path)
                ),
            }
            available = self.inactive_claude_versions(root, active_paths)
            # Keep the newest nonactive release as a fallback.
            return [path for _, path in sorted(available, reverse=True)[1:]]
        except FileNotFoundError:
            return []

    def claude_old_versions(self):
        root = join(self.claude_install(), "versions")
        launcher = join(self.home, ".local/bin/claude")
        if not self.user.safe(root) or not is_dir(info(root)):
            return

        def guarded_apply(item, path):
            if path not in self.claude_version_candidates(
                root, launcher
            ) or not unused_claude_version(path):
                raise ValueError(
                    f"Claude version is now protected or unverifiable {show(path)}"
                )
            item.check()
            item.apply()

        for path in self.claude_version_candidates(root, launcher):
            if not unused_claude_version(path):
                self.warn(
                    f"Skipped in-use or unverifiable Claude version {show(path)}"
                )
                continue
            item = self.user.removal(
                path, "Remove old Claude Code native version"
            )
            if item:
                self.optional.append(
                    Step(
                        item.description,
                        item.check,
                        lambda item=item, path=path: guarded_apply(item, path),
                    )
                )

    def owns_statusline(self, script):
        if not self.statusline_source:
            return False
        with (
            open(self.statusline_source, "rb") as expected,
            open(script, "rb") as installed,
        ):
            return expected.read() == installed.read()

    def statusline(self):
        script = join(self.home, ".claude/statusline.sh")
        settings_path = join(self.home, ".claude/settings.json")
        cache = join(self.home, ".cache/waza-statusline/highwater.json")
        self.add(
            self.required if self.uninstall else self.optional,
            cache,
            "Reset statusline usage high-water mark",
        )
        if (
            self.covered_by_directory(script)
            or not self.user.safe(script)
            or not is_file(info(script))
        ):
            return
        if not self.owns_statusline(script):
            if not self.uninstall:
                self.warn(
                    f"Statusline ownership could not be verified {show(script)}"
                )
            return
        item = self.user.removal(script, "Remove bundled Claude statusline")
        if item is None:
            return
        steps = [item]
        setting = self.statusline_setting(settings_path, script)
        if setting is not None:
            steps.insert(0, setting)

        def check():
            for step in steps:
                step.check()

        def apply():
            for step in steps:
                step.apply()

        self.optional.append(
            Step("; ".join(step.description for step in steps), check, apply)
        )

    def statusline_setting(self, settings_path, script):
        settings = self.user.json(settings_path)
        configured = settings.get("statusLine")
        if not (
            isinstance(configured, dict)
            and configured.get("type") == "command"
            and configured.get("command") in ("~/.claude/statusline.sh", script)
        ):
            return None
        before = identity(settings_path)

        def check_setting():
            if (
                not self.user.safe(settings_path)
                or identity(settings_path) != before
            ):
                raise ValueError("Claude settings changed")

        def apply_setting():
            check_setting()
            del settings["statusLine"]
            with NamedTemporaryFile(
                "w",
                dir=dirname(settings_path),
                encoding="utf-8",
                delete=False,
            ) as temporary:
                try:
                    json.dump(settings, temporary, ensure_ascii=False, indent=2)
                    temporary.write("\n")
                    os.fchmod(
                        temporary.fileno(),
                        stat.S_IMODE(info(settings_path).st_mode) & 0o777,
                    )
                    temporary.close()
                    os.replace(temporary.name, settings_path)
                finally:
                    if os.path.exists(temporary.name):
                        os.unlink(temporary.name)

        return Step(
            f"remove statusLine setting in {show(settings_path)}",
            check_setting,
            apply_setting,
        )

    def pi_package_sources(self, installed):
        if not isinstance(installed, list):
            return
        sources = [
            entry.get("source") if isinstance(entry, dict) else entry
            for entry in installed
        ]

        for name in self.packages:
            source = next(
                (
                    entry
                    for entry in sources
                    if isinstance(entry, str)
                    and (entry == name or entry.startswith(name + "@"))
                ),
                None,
            )
            if source:
                yield source

    def pi_packages(self, executable, root):
        # Uninstall has already verified the CLI through pi_uninstall(),
        # including supported installations outside the user's home.
        if not self.user.safe(root) or (
            not self.uninstall
            and (
                not self.user.safe(executable)
                or not self.user.safe(real(executable))
            )
        ):
            return
        settings_path = join(root, "settings.json")
        npm = join(root, "npm")
        installed = self.user.json(settings_path).get("packages")

        def supported():
            return (
                self.user.safe(npm)
                and (info(npm) is None or is_dir(info(npm)))
                and not self.user.json(settings_path).get("npmCommand")
            )

        def apply(source):
            if not supported():
                raise ValueError("Pi package storage changed")
            env = dict(
                os.environ,
                npm_config_ignore_scripts="true",
                npm_config_global="false",
            )
            run(executable, ["remove", source], env=env, interactive=True)

        def check(command, before):
            command.check()
            if identity(settings_path) != before or not supported():
                raise ValueError("Pi package settings changed")

        for source in self.pi_package_sources(installed):
            if not supported():
                self.warn(
                    f"Unprocessed Pi package {show(source)} uses custom npm storage or command"
                )
                continue
            if self.covered_by_directory(npm):
                continue
            before = identity(settings_path)
            command = checked_command(
                f"Remove global Pi package {show(source)} (may have been installed manually)",
                executable,
                lambda source=source: apply(source),
            )
            self.optional.append(
                Step(
                    command.description,
                    lambda command=command, before=before: check(
                        command, before
                    ),
                    command.apply,
                    needs_cli=True,
                )
            )

    def claude_mcp_servers(self, root):
        configured_servers = {}
        paths = [join(root, ".claude.json")]
        if root == self.fallback:
            paths.append(join(self.home, ".claude.json"))
        for path in paths:
            servers = self.user.json(path).get("mcpServers")
            if isinstance(servers, dict):
                for name, server in servers.items():
                    if isinstance(server, dict) and server.get("type") in (
                        "http",
                        "sse",
                    ):
                        configured_servers[name] = None

        return configured_servers

    def logout_codex_mcp(self, executable, scoped):
        servers = json.loads(
            run(executable, ["mcp", "list", "--json"], env=scoped)
        )
        if not isinstance(servers, list):
            raise ValueError("Unexpected Codex MCP inventory")
        for server in servers:
            transport = server.get("transport") or {}
            if transport.get("type") == "streamable_http" and server.get(
                "auth_status"
            ) not in ("unsupported", "not_logged_in"):
                run(
                    executable,
                    ["mcp", "logout", server["name"]],
                    env=scoped,
                )

    def logout(self, executable, root):
        if self.agent == "pi":
            return
        scoped = dict(os.environ)
        override = self.profile["override"]
        if root == self.fallback:
            scoped.pop(override, None)
        else:
            scoped[override] = root
        configured_servers = (
            self.claude_mcp_servers(root) if self.agent == "claude" else {}
        )

        def apply():
            if self.agent == "codex":
                self.logout_codex_mcp(executable, scoped)
            for name in configured_servers:
                run(executable, ["mcp", "logout", name], env=scoped)
            args = ["logout"] if self.agent == "codex" else ["auth", "logout"]
            run(executable, args, env=scoped)

        self.credentials.append(
            checked_command(
                f"Clear {self.agent} stored login for {show(root)}",
                executable,
                apply,
            )
        )

    def custom_pi_sessions(self, root):
        if (
            not self.user.safe(root)
            or not is_dir(info(root))
            or info(join(root, ".git"))
        ):
            self.warn(f"Unprocessed custom session directory {show(root)}")
            return
        for name in sorted(os.listdir(root)):
            path = join(root, name)
            if (
                not name.endswith(".jsonl")
                or not self.user.safe(path)
                or not is_file(info(path))
            ):
                continue
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                if not is_file(os.fstat(stream.fileno())):
                    continue
                try:
                    header = json.loads(stream.readline(8192))
                except (ValueError, UnicodeError):
                    continue
            if (
                isinstance(header, dict)
                and header.get("type") == "session"
                and isinstance(header.get("id"), str)
                and isinstance(header.get("timestamp"), str)
                and name.endswith(f"_{header['id']}.jsonl")
            ):
                self.add(self.required, path, "Delete Pi session")

    def collect_uninstall(self, executable):
        for root in self.roots:
            if (
                self.user.safe(root)
                and is_dir(info(root))
                and not info(join(root, ".git"))
            ):
                self.logout(executable, root)
            if not self.covered_by_directory(realpath(root)):
                self.scan_root(root)
        if self.agent == "claude":
            self.add(
                self.required,
                join(self.home, ".claude.json"),
                "Delete user state",
            )
        if self.agent == "pi":
            sessions = [os.environ.get("PI_CODING_AGENT_SESSION_DIR")]
            sessions.extend(
                self.user.json(join(root, "settings.json")).get("sessionDir")
                for root in self.roots
            )
            for path in dict.fromkeys(
                path for path in sessions if isinstance(path, str) and path
            ):
                directory = self.expand_home(path)
                if not self.covered_by_directory(realpath(directory)) and all(
                    directory != join(root, "sessions") for root in self.roots
                ):
                    self.custom_pi_sessions(directory)

    def uninstall_preview(self, installation, executable):
        selected = installation.launcher or executable
        preview = [f"Selected CLI {show(selected)} ({installation.method})"]
        for path in installation.outside_links:
            self.warn(
                f"Launcher link {show(path)} is outside the permitted removal scope and will remain after its target is removed"
            )
        for path in self.command_paths:
            if (
                path == selected
                or path in installation.files
                or path in installation.outside_links
            ):
                continue
            try:
                target = real(path)
                shared = target == real(executable) or bool(
                    installation.root and within(installation.root, target)
                )
            except FileNotFoundError:
                shared = False
            impact = (
                "will lose its executable target"
                if shared
                else "may lose shared user data"
            )
            preview.append(f"Other CLI path {show(path)} {impact}.")
        if self.agent == "claude":
            preview.append(
                "Claude desktop and IDE clients may share these data paths."
            )
        return preview

    def selected_items(self):
        if not self.optional:
            return []
        if sys.stdin.isatty() and sys.stdout.isatty():
            return pick_optional(self.action, self.agent, self.optional)
        for index, item in enumerate(self.optional, start=1):
            print(f"  {index}) {item.description}")
        answer = ask(
            "Optional items (comma-separated numbers, Enter for none): "
        )
        if not answer:
            return []
        indices = list(
            dict.fromkeys(part.strip() for part in answer.split(","))
        )
        if any(
            not re.fullmatch(r"[1-9][0-9]*", value)
            or int(value) > len(self.optional)
            for value in indices
        ):
            raise ValueError("Invalid selection; no changes made")
        return [self.optional[int(value) - 1] for value in indices]

    def cli_steps(self, installation):
        if not installation:
            return []
        if installation.command:
            return [installation.command]
        steps = [
            self.user.removal(path, "Remove CLI launcher")
            for path in installation.files
            if not self.covered_by_directory(path)
        ]
        if not self.covered_by_directory(installation.root):
            steps.append(
                self.user.removal(
                    installation.root, "Remove CLI installation", True
                )
            )
        if any(step is None for step in steps):
            raise ValueError("Cannot verify CLI removal paths")
        return steps

    def collect_cleanup(self, executable, managed):
        if not self.uninstall and self.agent != "claude":
            cache = (
                "models_cache.json"
                if self.agent == "codex"
                else "models-store.json"
            )
            for root in self.roots:
                self.add(
                    self.optional,
                    join(root, cache),
                    "Remove model catalog cache",
                )
        if self.agent == "claude":
            if not self.uninstall:
                self.claude_old_versions()
            self.statusline()
        if self.agent == "pi" and executable:
            self.pi_packages(
                managed.launcher if managed else executable, self.configured
            )

    def execute(self):
        executable = self.command_paths[0] if self.command_paths else None
        managed = (
            self.managed_pi(executable)
            if executable and self.agent == "pi" and not self.uninstall
            else None
        )
        cli = []
        directory_step = None
        if self.uninstall:
            executable, preview, cli, directory_step = self.plan_uninstall(
                executable
            )
        self.collect_cleanup(executable, managed)
        if self.uninstall:
            self.collect_uninstall(executable)
        else:
            preview = list(self.warnings)
            if not self.optional:
                for message in preview:
                    print(message)
                print("No verified cleanup items found.")
                return

        selected = self.selected_items()
        if selected is None:
            print("Cancelled.")
            return
        plan = [
            *self.credentials,
            *(item for item in selected if item.needs_cli),
            *(item for item in selected if not item.needs_cli),
            *cli,
            *self.required,
        ]
        if directory_step:
            if self.warnings:
                raise ValueError(
                    "Cannot verify complete uninstall:\n"
                    + "\n".join(self.warnings)
                )
            plan.append(directory_step)
        self.apply_plan(plan, preview)

    def apply_plan(self, plan, preview):
        for message in preview:
            print(message)
        if not plan:
            return
        if self.uninstall:
            for message in self.warnings:
                print(color(message, "33"))
        print("\n" + color("Execution preview", "1;36"))
        if self.uninstall:
            print(
                color(
                    "This permanently removes the listed data without a backup.",
                    "1;31",
                )
            )
        for item in plan:
            print(f"  {item.description}")
        if ask("Apply these changes? [y/N]: ").lower() != "y":
            print("Cancelled.")
            return
        self.run_plan(plan)
        if self.uninstall and self.warnings:
            raise ValueError("Uninstall left unprocessed paths listed above")

    def plan_uninstall(self, executable):
        if self.agent == "pi":
            installations, links, brew_entries = self.pi_uninstall()
            directory_step = self.choose_agent_directory()
            executable, preview, cli = self.pi_uninstall_steps(
                installations, links, brew_entries
            )
        else:
            if not executable:
                raise ValueError(
                    f"No {self.agent} CLI found on PATH; cannot verify or clear CLI-managed credentials"
                )
            installation = self.cli_installation(executable)
            if not installation:
                raise ValueError(
                    f"Manual uninstall required for {show(executable)}. Use its original installer or package manager. {UNINSTALL_GUIDE[self.agent]}"
                )
            directory_step = self.choose_agent_directory()
            preview = self.uninstall_preview(installation, executable)
            cli = self.cli_steps(installation)
        return executable, preview, cli, directory_step

    def choose_agent_directory(self):
        root = join(self.home, self.profile["uninstall_directory"])
        entry = info(root)
        if entry is None:
            return None
        if not is_dir(entry):
            self.warn(f"Unprocessed Agent directory {show(root)}")
            return None
        print(
            f"Include the entire Agent directory {color(show(root), '1;33')} in the uninstall plan?"
        )
        print(
            "This includes all files, sessions and custom content. Choose No for individual cleanup."
        )
        if ask("Include entire directory? [y/N]: ").lower() != "y":
            return None
        step = self.user.removal(root, "Delete entire Agent directory", True)
        if step is None:
            raise ValueError(
                "\n".join(self.warnings) or f"Cannot verify {show(root)}"
            )
        self.whole_directory = root
        return step

    def run_plan(self, plan):
        # Validate the whole preview before commands rewrite settings or credentials.
        for item in plan:
            item.check()
        for item in plan:
            item.apply()
            print(color("Completed:", "32"), item.description)


def stop(signum, _frame):
    raise SystemExit(128 + signum)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)
    try:
        action, agent, command_paths, statusline_source, *packages = sys.argv[
            1:
        ]
        Lifecycle(
            action, agent, command_paths, statusline_source, packages
        ).execute()
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, AttributeError, KeyError) as error:
        sys.exit(str(error))
