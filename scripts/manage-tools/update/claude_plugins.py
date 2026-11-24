import os
import sys
import json


plugins = json.load(sys.stdin)
if not isinstance(plugins, list):
    raise ValueError("expected an array from claude plugin list --json")
entries = []
for plugin in plugins:
    if not isinstance(plugin, dict):
        raise ValueError("invalid Claude plugin record")
    scope = plugin.get("scope")
    if scope not in ("user", "project", "local", "managed"):
        continue
    project = plugin.get("projectPath")
    if scope in ("project", "local"):
        if not isinstance(project, str) or os.path.realpath(
            project
        ) != os.path.realpath(os.getcwd()):
            continue
    name = plugin.get("id")
    if (
        not isinstance(name, str)
        or not name
        or name.startswith("-")
        or any(c in name for c in "\t\r\n")
    ):
        raise ValueError("invalid Claude plugin id")
    if name.endswith(("@inline", "@skills-dir", "@synced", "@builtin")):
        continue
    entry = (name, scope)
    if entry not in entries:
        entries.append(entry)
for name, scope in entries:
    print(name + "\t" + scope)
