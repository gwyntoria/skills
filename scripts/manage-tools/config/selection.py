"""Grouped choices and transitive Matt Pocock skill selection."""

from .screen import Back, paint, selection_mark


DEPENDENCIES = {
    "grill-me": ("grilling",),
    "grill-with-docs": ("grilling", "domain-modeling"),
    "tdd": ("codebase-design",),
    "implement": ("tdd", "code-review"),
    "implement-spec": ("tdd", "code-review"),
    "wayfinder": ("grilling", "domain-modeling", "prototype", "research"),
    "improve-codebase-architecture": (
        "codebase-design",
        "grilling",
        "domain-modeling",
    ),
    "triage": ("grilling", "domain-modeling"),
    "retro": ("writing-for-agents",),
}


class Selection:
    def __init__(self, groups, explicit, *, skills=False):
        self.groups = groups
        self.explicit = explicit
        self.notice = ""
        self.requirements = {}
        self.missing = {}
        available = {
            (group, item) for group, items in groups.items() for item in items
        }
        for choice in available:
            required, missing = (
                self.expand(choice, available) if skills else ({choice}, set())
            )
            self.requirements[choice] = required
            self.missing[choice] = missing
        self.resolve()

    def expand(self, choice, available):
        group, _ = choice
        required = set()
        pending = [choice]
        while pending:
            item = pending.pop()
            if item in required:
                continue
            required.add(item)
            if group == "mattpocock/skills":
                pending.extend(
                    (group, name) for name in DEPENDENCIES.get(item[1], ())
                )
        return required & available, required - available

    def resolve(self):
        self.selected = set()
        for choice in sorted(self.explicit & self.requirements.keys()):
            if self.missing[choice]:
                missing = ", ".join(
                    name for _, name in sorted(self.missing[choice])
                )
                self.notice = f"Cannot select {choice[1]}: missing {missing}"
                self.explicit.remove(choice)
            else:
                self.selected.update(self.requirements[choice])

    def toggle(self, keys, selected):
        self.notice = ""
        if selected:
            self.explicit.update(keys)
        else:
            removed = {
                choice
                for choice in self.explicit & self.requirements.keys()
                if self.requirements[choice] & keys
            }
            self.explicit.difference_update(removed)
            if removed - keys:
                names = ", ".join(name for _, name in sorted(removed - keys))
                self.notice = f"Also deselected: {names}"
        self.resolve()

    def choose(self, screen, title, label=lambda _group, value: str(value)):
        group = None
        names = list(self.groups)
        while True:
            choices = (
                names + ["Continue"]
                if group is None
                else [*self.groups[group], "Back"]
            )
            try:
                picked = self.pick(screen, title, choices, group, label)
            except Back:
                if group is None:
                    raise
                group = None
                continue
            if picked is None or (group is None and picked == len(names)):
                return
            group = choices[picked] if group is None else None

    def pick(self, screen, title, choices, group, label):
        def keys(index):
            choice = choices[index]
            if group is None:
                return {(choice, item) for item in self.groups[choice]}
            return {(group, choice)}

        def rows():
            result = []
            for index, value in enumerate(choices[:-1]):
                items = keys(index)
                picked = len(items & self.selected)
                name = value if group is None else label(group, value)
                indicator = selection_mark(picked, len(items))
                count = f" ({picked}/{len(items)})" if group is None else ""
                result.append((f"{name}{count}", indicator))
            return [*result, choices[-1]]

        def toggle(key, index):
            if key == ord(" ") and index < len(choices) - 1:
                items = keys(index)
                self.toggle(items, not items <= self.selected)
            elif key in (ord("a"), ord("n")):
                self.toggle(
                    set().union(*(keys(i) for i in range(len(choices) - 1))),
                    key == ord("a"),
                )

        def footer():
            if self.notice:
                return paint("1;33", self.notice)
            return (
                "↑↓ Move  Space Toggle  Enter Open / Back  c Continue  Esc Back"
            )

        suffix = f" / {group}" if group else ""
        return screen.menu(
            title + suffix,
            rows,
            toggle=toggle,
            footer=footer,
            continue_key=True,
        )
