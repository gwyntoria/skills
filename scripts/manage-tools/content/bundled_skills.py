"""Discover bundled CLI skills without loading personal or project configuration."""

import os
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


# These documented Claude Code skills can appear in the command registry without
# appearing in the model's skill frontmatter. The registry also contains commands.
CLAUDE_MANUAL_SKILLS = {
    "artifact-capabilities",
    "batch",
    "claude-approvals",
    "claude-in-chrome",
    "debug",
    "design",
    "design-sync",
    "doctor",
    "run-skill-generator",
    "ship",
    "slides",
    "steward",
    "verify",
    "whiteboard",
}
AGY_SKILLS = ".gemini/antigravity-cli/builtin/skills"


def run_listing(binary, args, home, *, input_text=""):
    env = {
        "HOME": home,
        "TMPDIR": home,
        "PATH": os.environ.get("PATH", os.defpath),
    }
    if binary.name == "claude":
        env["CLAUDE_CODE_ENTRYPOINT"] = "sdk-py"
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return subprocess.run(
        [binary, *args],
        cwd=home,
        env=env,
        input=input_text,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=5,
        check=True,
    ).stdout


def claude_skills(_home):
    binary = shutil.which("claude")
    if not binary:
        return []
    requests = (
        {
            "type": "control_request",
            "request_id": command,
            "request": {"subtype": command},
        }
        for command in ("initialize", "get_context_usage")
    )
    # The SDK control requests fetch metadata only. No user prompt is sent.
    args = (
        "-p",
        "--verbose",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--no-session-persistence",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
    )
    try:
        with TemporaryDirectory(prefix="manage-tools-claude-") as home:
            output = run_listing(
                Path(binary).absolute(),
                args,
                home,
                input_text="".join(
                    json.dumps(request) + "\n" for request in requests
                ),
            )
        responses = {
            record["response"]["request_id"]: record["response"]["response"]
            for record in map(json.loads, output.splitlines())
            if record.get("type") == "control_response"
            and record["response"].get("subtype") == "success"
        }
        commands = responses.get("initialize", {}).get("commands", [])
        context = responses.get("get_context_usage", {}).get("skills", {})
        names = {
            skill["name"]
            for skill in context.get("skillFrontmatter", [])
            if skill.get("source") == "built-in"
        }
        names.update(
            command["name"]
            for command in commands
            if command.get("builtin") is True
            and command.get("name") in CLAUDE_MANUAL_SKILLS
        )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        subprocess.SubprocessError,
    ):
        return []
    return [(name, None) for name in sorted(names)]


def antigravity_skills(home):
    files = sorted((home / AGY_SKILLS).glob("*/SKILL.md"))
    installed = [(file.parent.name, file) for file in files if file.is_file()]
    binary = shutil.which("agy")
    if installed or not binary:
        return installed
    try:
        # The agents inventory unpacks vendor assets before sign-in. A temporary
        # home keeps the inventory read-only with respect to the user's settings.
        with TemporaryDirectory(prefix="manage-tools-agy-") as home:
            run_listing(Path(binary).absolute(), ("agents",), home)
            files = sorted((Path(home) / AGY_SKILLS).glob("*/SKILL.md"))
            return [
                (file.parent.name, None) for file in files if file.is_file()
            ]
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
