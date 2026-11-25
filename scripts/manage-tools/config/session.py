"""Config workflows for Skill, Rule and Agent operations."""

import os
from io import StringIO
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout

from rules import installation
from agents import list_installed as agent_list
from content import list_installed
from content.catalog import (
    KAMI,
    WAZA,
    GITHUB,
    GWYNTORIA,
    KAMI_ARCHIVE,
    SKILL_SOURCES,
    WAZA_DEFAULTS,
    Catalogs,
)
from content.removal import Removal
from agents.lifecycle import Lifecycle

from .screen import Back, Quit, paint
from .execution import (
    AGENTS,
    BUNDLES,
    ACTION_ERRORS,
    Execution,
    require,
    command_paths,
    node_environment,
)
from .selection import Selection


WAZA_CATALOG = ("rules-waza", "Rules / Waza", "", "")
BUNDLED_RULES = ("rules-bundled", "Rules / Gwyntoria", "", "")
PUBLISHED_RULES = ("rules-published", "Rules / Gwyntoria", "", "")
SCOPES = ("global", "project")
CLAUDE_STATUSLINE = "scripts/statusline/claude-statusline.sh"


def capture(operation, *args):
    result = StringIO()
    with redirect_stdout(result):
        operation(*args)
    return result.getvalue().splitlines()


def result_summary(completed, failed):
    success = f"{completed} succeeded"
    errors = f"{failed} failed"
    if completed:
        success = paint("1;32", success)
    if failed:
        errors = paint("1;31", errors)
    return f"Results: {success}, {errors}"


def choose_steps(steps):
    """Return to the nearest displayed step with its current choices intact."""
    index = 0
    visited = []
    while index < len(steps):
        try:
            visible = steps[index]()
        except Back:
            if not visited:
                raise
            index = visited.pop()
            continue
        if visible is not False:
            visited.append(index)
        index += 1


def skill_spec(source):
    return (source.kind, f"Skills / {source.repository}", source.repository, "")


class Session:
    def __init__(self, screen, root, mode, archive_url, work):
        self.screen = screen
        self.root = root
        self.mode = mode
        self.work = work
        self.home = Path(os.environ.get("HOME") or "/")
        self.project = Path.cwd().resolve()
        self.catalogs = Catalogs(root, mode, archive_url, work)
        self.failed = False

    def run(self):
        actions = (
            lambda: self.content("Skill"),
            lambda: self.content("Rule"),
            self.agent,
        )
        while True:
            try:
                index = self.screen.home()
                if index == 3:
                    break
                actions[index]()
            except Quit:
                break
            except Back:
                continue
            except ACTION_ERRORS as error:
                self.failed = True
                try:
                    self.screen.page(
                        paint("31", "Operation failed"), str(error).splitlines()
                    )
                except Quit:
                    break
        return int(self.failed)

    def page(self, title, lines, *, failed=False, start_at_end=False):
        self.failed |= failed
        self.screen.page(title, lines, start_at_end=start_at_end)

    def scope(self, title, selected):
        return self.screen.choose(
            title,
            [
                ("Global", "User-wide configuration"),
                ("Project", str(self.project)),
            ],
            selected,
        )

    def content(self, kind):
        name = kind.lower()
        options = [
            ("Install", f"Add {name}s"),
            ("Remove", f"Remove installed {name}s"),
            ("List", f"Browse installed or available {name}s"),
            ("Back", "Return to the main menu"),
        ]
        action = 0
        while True:
            action = self.screen.choose(kind, options, action)
            if action == 3:
                return
            try:
                (self.install_content, self.remove_content, self.list_content)[
                    action
                ](kind)
            except Back:
                continue
            return

    def agent(self):
        selected = 0
        while True:
            selected = self.screen.choose(
                "Agent",
                [
                    ("Install", "Install agent CLIs"),
                    ("Cleanup", "Remove selected agent data"),
                    ("Uninstall", "Remove agent CLIs and selected data"),
                    ("List", "Show installed agents"),
                    ("Back", "Return to the main menu"),
                ],
                selected,
            )
            try:
                self.agent_action(selected)
            except Back:
                continue
            return

    def agent_action(self, action):
        if action == 3:
            self.page("Agent / List", capture(agent_list.main, True))
        elif action == 0:
            self.install_agents()
        elif action in (1, 2):
            self.agent_lifecycle(("Cleanup", "Uninstall")[action - 1])

    def perform(self, title, operation):
        execution = Execution(self.screen, self.work)
        execution.title = title
        with redirect_stdout(execution), redirect_stderr(execution):
            operation(execution)
        self.page(
            title,
            [
                *execution.lines,
                result_summary(execution.completed, execution.failed),
            ],
            failed=bool(execution.failed),
            start_at_end=True,
        )

    def select_agents(self, title, labels, selected):
        return [
            list(labels)[index]
            for index in self.screen.multi(
                title, list(labels.values()), selected
            )
        ]

    def install_agents(self):
        selected = set()
        labels = {
            "codex": "Codex",
            "claude": "Claude Code (with statusline)",
            "pi": "Pi (with three packages)",
        }
        while True:
            agents = self.select_agents("Agent / Install", labels, selected)
            if not agents:
                return
            try:
                lines = []
                for agent in agents:
                    lines.append(f"{AGENTS[agent]} CLI")
                    lines.extend(
                        f"  {bundle} (bundled)"
                        for bundle in BUNDLES.get(agent, ())
                    )
                confirmed = self.screen.confirm(
                    "Execution plan / Agent install",
                    lines,
                    action="Install",
                    default=True,
                )
            except Back:
                continue
            if confirmed:
                self.apply_agent_install(agents)
            return

    def apply_agent_install(self, agents):
        statusline = self.root / CLAUDE_STATUSLINE
        if "claude" in agents and not statusline.is_file():
            raise ValueError(f"Invalid resource: {statusline}")
        if set(agents) & {"codex", "claude"}:
            require("curl")
        environment = None
        if "pi" in agents:
            environment = node_environment(self.home)
            require("npm", environment)

        def install(execution):
            for agent in agents:
                execution.install_agent(
                    agent, self.home, statusline, environment
                )

        self.perform("Agent / Install results", install)

    def agent_lifecycle(self, action):
        selected = self.select_agents(f"Agent / {action}", AGENTS, set())
        if not selected:
            return
        source = self.root / CLAUDE_STATUSLINE

        def apply(execution):
            for agent in selected:
                statusline = (
                    str(source)
                    if agent == "claude" and source.is_file()
                    else ""
                )

                def lifecycle():
                    operation = Lifecycle(
                        action,
                        agent,
                        command_paths(agent),
                        statusline,
                        BUNDLES["pi"],
                        execution,
                    )
                    if not operation.execute():
                        raise Back

                execution.item(AGENTS[agent], lifecycle)

        self.perform(f"Agent / {action} results", apply)

    def install_content(self, kind):
        if kind == "Skill":
            workflow = SkillInstall(self)
        else:
            workflow = RuleInstall(self)
        workflow.run()

    def list_content(self, kind):
        def mode():
            state["mode"] = self.screen.choose(
                f"{kind} / List",
                [
                    ("Local", "Show installed items"),
                    ("Remote", "Browse source catalogs"),
                ],
                state["mode"],
            )

        def scope():
            if state["mode"] == 1:
                return False
            state["scope"] = self.scope(
                f"{kind} / List / Scope", state["scope"]
            )

        def locations():
            if state["mode"] == 1:
                self.list_remote(kind)
                return
            scope_name = SCOPES[state["scope"]]
            choices = dict(AGENTS)
            if kind == "Skill":
                choices = {"shared": "Shared", **choices}
            elif scope_name == "project":
                choices.pop("pi")
            selected = self.select_agents(
                f"{kind} / List / {scope_name.title()}",
                choices,
                state["selected"],
            )
            if not selected:
                raise Back
            rows = capture(
                list_installed.main,
                str(self.home),
                str(self.project),
                scope_name,
                flag(kind == "Rule"),
                flag(kind == "Skill"),
                *(
                    flag(name in selected)
                    for name in ("shared", "codex", "claude", "pi")
                ),
                str(installation.pi_rule_path(self.home)),
                "1",
            )
            self.page(f"{kind} / List / Local", rows)

        state = {"mode": 0, "scope": 0, "selected": {0}}
        choose_steps((mode, scope, locations))

    def list_remote(self, kind):
        specs = [skill_spec(source) for source in SKILL_SOURCES]
        if kind == "Rule":
            bundled = (
                BUNDLED_RULES if self.mode == "archive" else PUBLISHED_RULES
            )
            specs = [bundled, WAZA_CATALOG]
        data, errors = self.catalogs.load(
            "List / Remote catalogs", specs, self.screen.downloads
        )
        lines = [paint("1;36", "Available · Remote")]
        for spec in specs:
            if spec in data:
                _, label, repository, _ = spec
                repository = repository or (
                    WAZA if spec == WAZA_CATALOG else GWYNTORIA
                )
                lines.extend(
                    [
                        "",
                        paint("1;36", label),
                        GITHUB + repository,
                        *[f"  {name}" for name in data[spec][0]],
                    ]
                )
        lines.extend(paint("33", error) for _, error in errors.values())
        self.page(f"{kind} / List / Remote", lines, failed=bool(errors))

    def remove_content(self, kind):
        workflow = ContentRemoval(self, kind)
        choose_steps(
            (
                workflow.choose_scope,
                workflow.locations,
                workflow.choose_targets,
                workflow.confirm,
            )
        )


def flag(value):
    return "1" if value else "0"


class Installation:
    def __init__(self, session):
        self.session = session
        self.screen = session.screen
        self.scope_index = 0
        self.scope = "global"

    def choose_scope(self):
        index = self.session.scope("Install / Choose scope", self.scope_index)
        if index != self.scope_index:
            self.reset()
            self.scope_index = index
            self.scope = SCOPES[index]

    @property
    def title(self):
        return f"Install / {self.scope.title()}"


class SkillInstall(Installation):
    def __init__(self, session):
        super().__init__(session)
        self.reset()

    def reset(self):
        self.repositories = {
            index
            for index, source in enumerate(SKILL_SOURCES)
            if source.defaults
        }
        self.targets = {0}
        self.explicit = set()
        self.visited = set()
        self.selected = {}
        self.errors = {}

    def run(self):
        choose_steps(
            (
                self.choose_scope,
                self.choose_repositories,
                self.choose_skills,
                self.choose_agents,
                self.confirm,
            )
        )

    def choose_scope(self):
        previous = self.scope
        super().choose_scope()
        if previous != self.scope and self.scope == "project":
            self.repositories.clear()

    def choose_repositories(self):
        self.screen.multi(
            f"{self.title} / Skill repositories",
            [source.repository for source in SKILL_SOURCES],
            self.repositories,
        )

    def choose_skills(self):
        sources = [SKILL_SOURCES[index] for index in sorted(self.repositories)]
        data, self.errors = self.session.catalogs.load(
            "Install / Skill catalogs",
            [skill_spec(source) for source in sources],
            self.screen.downloads,
        )
        groups = {}
        for source in sources:
            if skill_spec(source) not in data:
                continue
            names = data[skill_spec(source)][0]
            groups[source.repository] = names
            if source.repository not in self.visited:
                self.visited.add(source.repository)
                if self.scope == "global":
                    self.explicit.update(
                        (source.repository, name)
                        for name in names
                        if name in source.defaults.split()
                    )
        selection = Selection(groups, self.explicit, skills=True)
        if groups:
            selection.choose(
                self.screen, f"{self.title} / Skills by repository"
            )
        self.selected = {
            repo: [name for name in names if (repo, name) in selection.selected]
            for repo, names in groups.items()
            if any((repo, name) in selection.selected for name in names)
        }
        return bool(groups)

    def choose_agents(self):
        if not self.selected:
            return False
        self.agents = self.session.select_agents(
            f"{self.title} / Agents for skills",
            {"codex": "Shared", "claude-code": "Claude Code"},
            self.targets,
        )

    def confirm(self):
        lines = (
            [f"Project root: {self.session.project}"]
            if self.scope == "project"
            else []
        )
        lines.extend(paint("33", error) for _, error in self.errors.values())
        if not self.selected or not self.agents:
            self.session.page(
                "Skill / Install",
                lines or ["No installation targets selected."],
                failed=bool(self.errors),
            )
            return
        home = self.session.home
        root = self.session.project if self.scope == "project" else home
        claude = (
            Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude")
            if self.scope == "global"
            else root / ".claude"
        )
        for repo, names in self.selected.items():
            for name in names:
                lines.extend(
                    [
                        f"{repo} / {name}",
                        f"  Shared -> {root / '.agents/skills' / name}",
                    ]
                )
                if "claude-code" in self.agents:
                    lines.append(f"  Claude -> {claude / 'skills' / name}")
        if self.screen.confirm(
            "Execution plan / Skill install",
            lines,
            action="Install",
            default=True,
        ):
            self.session.perform("Skill / Install results", self.apply)

    def apply(self, execution):
        for _, message in self.errors.values():
            execution.failed += 1
            execution.report(f"Unavailable: {message}")
        if self.scope == "project" and self.session.project == Path("/"):
            raise ValueError("Refusing to use / as a project directory.")
        env = node_environment(self.session.home)
        if self.screen.color_enabled:
            env = dict(os.environ if env is None else env)
            # skills detects a pipe as non-interactive and otherwise omits color.
            env.setdefault("FORCE_COLOR", "1")
        npx = require("npx", env)
        scope = ["--global"] if self.scope == "global" else []
        for repository, names in self.selected.items():
            source = KAMI_ARCHIVE if repository == KAMI else GITHUB + repository
            command = [
                npx,
                "--yes",
                "skills",
                "add",
                source,
                "--skill",
                *names,
                "--agent",
                *self.agents,
                *scope,
                "--yes",
            ]

            def install():
                execution.command(command, cwd=self.session.project, env=env)

            execution.item(f"{repository}: {', '.join(names)}", install)


class RuleInstall(Installation):
    def __init__(self, session):
        super().__init__(session)
        self.reset()

    def reset(self):
        self.explicit = set()
        self.targets = {0}
        self.visited = False

    def run(self):
        choose_steps(
            (
                self.choose_scope,
                self.choose_rules,
                self.choose_agents,
                self.confirm,
            )
        )

    def choose_rules(self):
        title = f"{self.title} / Rule catalogs"
        while True:
            data, errors = self.session.catalogs.load(
                title, [BUNDLED_RULES, WAZA_CATALOG], self.screen.downloads
            )
            if BUNDLED_RULES in errors:
                raise ValueError(errors[BUNDLED_RULES][1])
            if WAZA_CATALOG not in errors:
                break
            options = ["Retry", "Continue without Waza rules", "Back"]
            choice = self.screen.choose(
                title + " / " + paint("1;33", "Waza unavailable"), options
            )
            if choice == 1:
                break
            if choice == 2:
                raise Back
        self.waza = data.get(WAZA_CATALOG, ([], None))[1]
        groups = {}
        if self.waza:
            groups["Waza"] = data[WAZA_CATALOG][0]
        groups["Gwyntoria"] = data[BUNDLED_RULES][0]
        if self.scope == "global" and not self.visited:
            self.explicit.update(
                ("Waza", name)
                for name in groups.get("Waza", [])
                if name in WAZA_DEFAULTS
            )
        self.visited = True
        selection = Selection(
            {name: items for name, items in groups.items() if items},
            self.explicit,
        )
        selection.choose(
            self.screen,
            f"{self.title} / Rules",
            label=lambda group, name: (
                name.removeprefix("waza-") if group == "Waza" else name
            ),
        )
        self.selected = [
            (group, name)
            for group, items in groups.items()
            for name in items
            if (group, name) in selection.selected
        ]

    def choose_agents(self):
        if not self.selected or self.scope == "project":
            self.agents = []
            return False
        self.agents = self.session.select_agents(
            f"{self.title} / Agents for rules", AGENTS, self.targets
        )

    def confirm(self):
        if not self.selected or (self.scope == "global" and not self.agents):
            self.session.page(
                "Rule / Install", ["No installation targets selected."]
            )
            return
        lines = []
        for group, name in self.selected:
            paths = installation.destinations(
                self.session.home,
                self.session.project,
                self.scope,
                self.agents,
                name,
            )
            if group == "Waza":
                origin = f"tw93/Waza @ {self.waza_ref()} / rules/{name.removeprefix('waza-')}.md"
            elif self.session.mode == "archive":
                origin = f"{GWYNTORIA} @ main / rules/{name}.md"
            else:
                origin = str(self.session.root / "rules" / f"{name}.md")
            lines.extend(
                [
                    f"Rule source: {origin}",
                    *[
                        f"  {target} -> {path}"
                        for target, path in paths.items()
                    ],
                ]
            )
        if self.screen.confirm(
            "Execution plan / Rule install",
            lines,
            action="Install",
            default=True,
        ):
            self.session.perform("Rule / Install results", self.apply)

    def waza_ref(self):
        return (self.waza / "resolved-commit").read_text().strip()

    def fetch_waza(self, execution):
        if not self.waza:
            return
        rules = self.waza / "rules"
        specs = [
            ("waza-body", f"Rule / {name}", name, self.waza_ref())
            for group, name in self.selected
            if group == "Waza" and not (rules / f"{name}.md").is_file()
        ]

        def loading(title, jobs):
            self.screen.downloads(title, jobs, cancel=False)

        title = "Install / Download Waza rules"
        data, errors = self.session.catalogs.load(title, specs, loading)
        for spec, (_, directory) in data.items():
            (directory / "rule.md").replace(rules / f"{spec[2]}.md")
        retry = [spec for spec, (status, _) in errors.items() if status != 2]
        for _, message in errors.values():
            execution.report(message)
        if retry:
            self.fetch_waza_fallback(execution, title, retry, loading, rules)

    def fetch_waza_fallback(self, execution, title, retry, loading, rules):
        spec = (
            "waza-fallback",
            "Rules / Waza Git fallback",
            "",
            self.waza_ref(),
        )
        fallback, errors = self.session.catalogs.load(title, [spec], loading)
        if spec in errors:
            execution.report(errors[spec][1])
            return
        for _, _, name, _ in retry:
            path = fallback[spec][1] / "rules" / f"{name}.md"
            if path.is_file():
                (rules / path.name).write_bytes(path.read_bytes())

    def apply(self, execution):
        self.fetch_waza(execution)
        for group, name in self.selected:
            waza = group == "Waza"
            directory = self.waza if waza else self.session.root
            execution.item(
                f"{group} / {name}",
                installation.install,
                self.session.home,
                self.session.project,
                self.scope,
                self.agents,
                name,
                directory / "rules" / f"{name}.md",
                waza,
            )


class ContentRemoval:
    def __init__(self, session, kind):
        self.session = session
        self.screen = session.screen
        self.kind = kind
        self.scope_index = 0
        self.selected_locations = {0}
        self.scan_signature = None
        self.explicit = set()

    def choose_scope(self):
        self.scope_index = self.session.scope(
            "Remove / Choose scope", self.scope_index
        )

    @property
    def title(self):
        return f"Remove / {SCOPES[self.scope_index].title()}"

    def locations(self):
        labels = {
            "codex": "Shared" if self.kind == "Skill" else "Codex",
            "claude": "Claude Code",
        }
        if self.scope_index == 0 and self.kind == "Rule":
            labels["pi"] = "Pi (rules only)"
        self.selected_locations.intersection_update(range(len(labels)))
        self.agents = self.session.select_agents(
            f"{self.title} / Agents", labels, self.selected_locations
        )
        if not self.agents:
            raise Back

    def choose_targets(self):
        signature = (self.scope_index, *self.agents)
        if signature != self.scan_signature:
            self.scan()
            self.scan_signature = signature
        if not self.rows:
            self.selected = []
            return False
        groups = {}
        labels = {}
        for row in self.rows:
            identifier, _, group, label = row.split("\t", 3)
            groups.setdefault(
                group if self.kind == "Skill" else "Rules", []
            ).append(identifier)
            labels[identifier] = label
        if self.kind == "Skill":
            selector = Selection(groups, self.explicit)
            selector.choose(
                self.screen,
                f"{self.title} / Skills by repository",
                label=lambda _group, identifier: labels[identifier],
            )
            self.selected = [
                identifier
                for _, identifier in sorted(
                    selector.selected,
                    key=lambda item: int(item[1].split(",")[0]),
                )
            ]
        else:
            identifiers = list(labels)
            picked = {
                index
                for index, identifier in enumerate(identifiers)
                if identifier in self.explicit
            }
            try:
                self.screen.multi(
                    f"{self.title} / Rules", list(labels.values()), picked
                )
            finally:
                self.explicit = {identifiers[index] for index in picked}
            self.selected = [
                identifier
                for identifier in identifiers
                if identifier in self.explicit
            ]

    def scan(self):
        session = self.session
        self.explicit.clear()
        self.inventory = Removal(
            str(session.home),
            str(session.project),
            SCOPES[self.scope_index],
            str(session.work / "removal.json"),
            str(installation.pi_rule_path(session.home)),
        )
        warnings = StringIO()
        with redirect_stderr(warnings):
            self.inventory.run(
                "scan",
                [
                    flag("codex" in self.agents),
                    flag("claude" in self.agents),
                    flag(self.kind == "Rule"),
                    flag(self.kind == "Skill"),
                    flag("pi" in self.agents),
                ],
            )
        self.warnings = warnings.getvalue().splitlines()
        self.rows = capture(self.inventory.run, "rows", [])

    def confirm(self):
        if not self.selected:
            self.session.page(
                self.title, ["No removal targets selected.", *self.warnings]
            )
            return
        self.inventory.run("select", self.selected)
        links = capture(self.inventory.run, "linked-skills", [])
        if links and self.screen.confirm(
            "Also remove these Claude links?",
            links,
            action="Include",
            cancel="Keep",
            destructive=True,
        ):
            self.inventory.run("include-links", [])
        preview = capture(self.inventory.run, "preview", [])
        if self.screen.confirm(
            self.title,
            [
                paint("1;33", f"Targets: {preview[0]}"),
                *preview[1:],
                *self.warnings,
            ],
            action="Remove",
            default=True,
            destructive=True,
        ):
            self.session.perform(f"{self.title} / Results", self.apply)

    def apply(self, execution):
        if self.inventory.run("remove", []):
            execution.failed += 1
        else:
            execution.completed += 1
