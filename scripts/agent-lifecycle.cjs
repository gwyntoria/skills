"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { emitKeypressEvents } = require("node:readline");
const readline = require("node:readline/promises");

const [action, agent, commandPaths, statuslineSource, ...bundledPackages] =
  process.argv.slice(2);
const { HOME: home } = process.env;
const uninstall = action === "Uninstall";
const env = process.env;
const warnings = new Set();
const required = [];
const optional = [];
const credentialSteps = [];
const seenPaths = new Set();
const paths = [...new Set(commandPaths.split("\n").filter(Boolean))];
const within = (root, file) => file.startsWith(root + path.sep);
const show = (value) => JSON.stringify(value);

function stat(file) {
  try {
    return fs.lstatSync(file);
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
}

function safe(file) {
  if (
    !path.isAbsolute(file) ||
    path.resolve(file) !== file ||
    !within(home, file) ||
    /[\x00-\x1f\x7f]/.test(file)
  )
    return false;
  const shared = path.join(home, ".agents");
  if (file === shared || within(shared, file)) return false;
  const device = stat(home).dev;
  const info = stat(file);
  if (info && (info.uid !== process.getuid() || info.dev !== device))
    return false;
  for (
    let parent = path.dirname(file);
    parent !== home;
    parent = path.dirname(parent)
  ) {
    const entry = stat(parent);
    if (
      entry &&
      (!entry.isDirectory() ||
        entry.uid !== process.getuid() ||
        entry.dev !== device ||
        stat(path.join(parent, ".git")))
    )
      return false;
  }
  return true;
}

function json(file) {
  if (!safe(file) || !stat(file)?.isFile()) return undefined;
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function identity(file) {
  const info = stat(file);
  return (
    info &&
    [
      info.dev,
      info.ino,
      info.mode,
      info.uid,
      info.isDirectory() ? "" : info.mtimeMs,
    ].join(":")
  );
}

function protectedDescendant(root, device) {
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const file = path.join(root, entry.name);
    const info = stat(file);
    if (!info) continue;
    if (
      info.uid !== process.getuid() ||
      info.dev !== device ||
      entry.name === ".git"
    )
      return file;
    if (info.isDirectory()) {
      const protectedPath = protectedDescendant(file, device);
      if (protectedPath) return protectedPath;
    }
  }
}

function removal(file, label = "Delete", recursive = false) {
  const info = stat(file);
  if (!info || seenPaths.has(file)) return undefined;
  if (uninstall && info.isSymbolicLink() && label.startsWith("Delete user")) {
    warnings.add(
      `Only the link can be deleted; target remains for ${show(file)}`,
    );
  }
  if (
    !safe(file) ||
    (info.isDirectory() && (!recursive || stat(path.join(file, ".git")))) ||
    !(info.isDirectory() || info.isFile() || info.isSymbolicLink())
  ) {
    warnings.add(`Unprocessed path ${show(file)}`);
    return undefined;
  }
  const protectedPath =
    info.isDirectory() && protectedDescendant(file, info.dev);
  if (protectedPath) {
    warnings.add(
      `Unprocessed directory ${show(file)} contains protected entry ${show(protectedPath)}`,
    );
    return undefined;
  }
  const before = identity(file);
  const parentBefore = identity(path.dirname(file));
  seenPaths.add(file);
  return {
    description: `${label} ${show(file)}`,
    check() {
      if (!safe(file) || identity(file) !== before)
        throw Error(`Path changed ${show(file)}`);
    },
    apply() {
      const current = stat(file);
      if (!current) return;
      if (
        !safe(file) ||
        identity(path.dirname(file)) !== parentBefore ||
        (current.isDirectory() &&
          (!recursive || protectedDescendant(file, current.dev)))
      ) {
        throw Error(`Path changed ${show(file)}`);
      }
      fs.rmSync(file, { recursive });
    },
  };
}

function add(list, item) {
  if (item) list.push(item);
}

function run(program, args, options = {}) {
  const result = spawnSync(program, args, {
    cwd: "/",
    encoding: "utf8",
    ...options,
  });
  if (result.error || result.status !== 0) {
    throw Error(`Command failed: ${[program, ...args].map(show).join(" ")}`);
  }
  return result.stdout;
}

function checkedCommand(description, executable, apply) {
  const before = identity(executable);
  const target = fs.realpathSync(executable);
  const targetBefore = identity(target);
  return {
    description,
    check() {
      if (
        identity(executable) !== before ||
        fs.realpathSync(executable) !== target ||
        identity(target) !== targetBefore
      )
        throw Error(`Executable changed ${show(executable)}`);
    },
    apply,
  };
}

function managedPi(executable) {
  const command = stat(executable);
  if (!command || (!safe(executable) && !command.isSymbolicLink())) return;
  const launcher = fs.realpathSync(executable);
  if (
    !safe(launcher) ||
    !stat(launcher)?.isFile() ||
    path.basename(launcher) !== "pi" ||
    path.basename(path.dirname(launcher)) !== "bin"
  )
    return;
  const install = path.resolve(path.dirname(launcher), "../install");
  const marker = json(path.join(install, "managed-install.json"));
  const entry = marker?.entrypoint?.path;
  if (
    marker?.kind !== "pi-managed-install" ||
    marker.schemaVersion !== 1 ||
    marker.layout !== "releases-v1" ||
    ![launcher, executable].includes(entry)
  )
    return;

  const files = [launcher];
  const externalLinks = [];
  for (const file of new Set([executable, entry])) {
    if (
      file === launcher ||
      !stat(file)?.isSymbolicLink() ||
      fs.realpathSync(file) !== launcher
    )
      continue;
    if (safe(file)) files.push(file);
    else if (file === entry && marker.entrypoint.type === "symlink")
      externalLinks.push(file);
    else return;
  }
  return {
    method: "Pi managed installer",
    launcher,
    files,
    install,
    externalLinks,
  };
}

function cliPlan(executable, roots) {
  if (!safe(executable) || !stat(executable)) return;
  const target = fs.realpathSync(executable);
  if (!safe(target)) return;

  if (agent === "codex") {
    for (const root of roots) {
      const install = path.join(root, "packages/standalone");
      if (
        !stat(executable).isSymbolicLink() ||
        !within(path.join(install, "releases"), target) ||
        !["codex", "bin/codex"].some(
          (name) =>
            path.join(install, "current", name) ===
            path.resolve(path.dirname(executable), fs.readlinkSync(executable)),
        )
      )
        continue;
      const companion = path.join(
        path.dirname(executable),
        "codex-code-mode-host",
      );
      const files = [executable];
      if (
        stat(companion)?.isSymbolicLink() &&
        path.resolve(path.dirname(companion), fs.readlinkSync(companion)) ===
          path.join(install, "current/bin/codex-code-mode-host")
      )
        files.push(companion);
      return { method: "Codex standalone", files, install };
    }
  }

  if (agent === "claude") {
    const install = path.join(
      env.XDG_DATA_HOME || path.join(home, ".local/share"),
      "claude",
    );
    if (
      stat(executable)?.isSymbolicLink() &&
      within(path.join(install, "versions"), target)
    ) {
      return { method: "Claude native", files: [executable], install };
    }
  }

  const packages = {
    codex: ["@openai/codex"],
    claude: ["@anthropic-ai/claude-code"],
    pi: ["@earendil-works/pi-coding-agent", "@mariozechner/pi-coding-agent"],
  };
  const prefix = path.dirname(path.dirname(executable));
  for (const name of packages[agent]) {
    const directory = path.join(prefix, "lib/node_modules", name);
    const metadata = json(path.join(directory, "package.json"));
    const entry =
      typeof metadata?.bin === "string" ? metadata.bin : metadata?.bin?.[agent];
    if (
      executable !== path.join(prefix, "bin", agent) ||
      metadata?.name !== name ||
      !entry ||
      !within(directory, path.resolve(directory, entry)) ||
      !stat(executable).isSymbolicLink() ||
      path.resolve(path.dirname(executable), fs.readlinkSync(executable)) !==
        path.resolve(directory, entry)
    )
      continue;
    const npm = path.join(prefix, "bin/npm");
    const manager = stat(npm) ? npm : "npm";
    return {
      method: `npm ${name} (prefix ${show(prefix)})`,
      command: checkedCommand(
        `Uninstall ${name} from npm prefix ${show(prefix)}`,
        executable,
        () => {
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
            { stdio: "inherit" },
          );
          if (stat(executable) || stat(directory))
            throw Error("npm installation remains");
        },
      ),
    };
  }
}

const profiles = {
  codex: {
    fallback: ".codex",
    override: "CODEX_HOME",
    entries: [
      "config.toml",
      "auth.json",
      "sessions",
      "archived_sessions",
      "history.jsonl",
      "session_index.jsonl",
      "log",
      "logs",
      "memories",
      "models_cache.json",
      "shell_snapshots",
      "version.json",
      "installation_id",
      "plugins",
      "hooks.json",
      "thread-writer-locks",
      "automations",
      "mcp_oauth",
      ".sandbox",
      ".sandbox_migration",
      ".tmp",
      "tmp",
      "cache",
      "auth.json.lock",
      "auth.lock",
      "memories.lock",
      "memories_extensions",
      "mention_usage.json",
      "mention_usage.lock",
      "session_index.jsonl.lock",
      ".sqlite-maintenance.lock",
      "ipc",
      "rollout-migrations",
      "editor",
      "threads",
      "tui-thread-reference-capabilities",
    ],
    patterns: [
      /^(?:state|logs|goals|memories|queue|thread_history)_\d+\.sqlite(?:-wal|-shm)?$/,
      /\.config\.toml$/,
    ],
    content: ["AGENTS.md", "AGENTS.override.md", "skills", "rules"],
    retained: ["packages", "app-server-daemon", "app-server-control"],
  },
  claude: {
    fallback: ".claude",
    override: "CLAUDE_CONFIG_DIR",
    entries: [
      "settings.json",
      "settings.local.json",
      ".credentials.json",
      "credentials.json",
      ".claude.json",
      "mcp.json",
      "projects",
      "history.jsonl",
      "debug",
      "logs",
      "backups",
      "file-history",
      "session-env",
      "sessions",
      "tasks",
      "todos",
      "plans",
      "paste-cache",
      "cache",
      "stats-cache.json",
      "plugins",
      "downloads",
      "shell-snapshots",
      "ide",
      "usage-data",
      "chrome",
      "mcp-needs-auth-cache.json",
      "daemon.log",
      "daemon",
      "statsig",
      "session-memory",
      "transcripts",
      "telemetry",
      "agents",
      "commands",
      "hooks",
      "keybindings.json",
      "output-styles",
    ],
    patterns: [],
    content: ["CLAUDE.md", "CLAUDE.local.md", "rules", "skills"],
    retained: ["statusline.sh"],
  },
  pi: {
    fallback: ".pi/agent",
    override: "PI_CODING_AGENT_DIR",
    entries: [
      "settings.json",
      "auth.json",
      "keybindings.json",
      "models.json",
      "models-store.json",
      "mcp.json",
      "mcp-auth.json",
      "sessions",
      "sessions-archive",
      "pi-debug.log",
      "cache",
      "extensions",
      "themes",
      "prompts",
      "SYSTEM.md",
      "APPEND_SYSTEM.md",
      "trusted-projects.json",
    ],
    patterns: [],
    content: [
      "AGENTS.override.md",
      "AGENTS.md",
      "AGENTS.MD",
      "CLAUDE.md",
      "CLAUDE.MD",
      "skills",
      "rules",
    ],
    retained: ["npm", "git", "bin", "install", "tools"],
  },
};

function scanRoot(root, profile) {
  if (!safe(root)) {
    warnings.add(`Unprocessed data directory ${show(root)}`);
    return;
  }
  if (!stat(root)) return;
  if (!stat(root).isDirectory() || stat(path.join(root, ".git"))) {
    warnings.add(`Unprocessed data directory ${show(root)}`);
    return;
  }
  for (const name of fs.readdirSync(root)) {
    const file = path.join(root, name);
    if (
      profile.entries.includes(name) ||
      profile.patterns.some((pattern) => pattern.test(name))
    ) {
      add(required, removal(file, "Delete user data", true));
    } else if (profile.content.includes(name)) {
      const info = stat(file);
      if (info.isDirectory() && safe(file) && !stat(path.join(file, ".git"))) {
        for (const entry of fs.readdirSync(file)) {
          if (entry !== ".system")
            add(
              optional,
              removal(path.join(file, entry), "Delete skill/rule entry", true),
            );
        }
      } else if (!info.isDirectory()) {
        add(
          optional,
          removal(
            file,
            "Delete whole skill/rule file or link (including handwritten content)",
          ),
        );
      } else {
        warnings.add(`Unprocessed skill/rule directory ${show(file)}`);
      }
    } else if (!profile.retained.includes(name)) {
      warnings.add(`Unrecognized Agent entry ${show(file)}`);
    }
  }
}

function statusline() {
  const script = path.join(home, ".claude/statusline.sh");
  const settingsFile = path.join(home, ".claude/settings.json");
  const cache = path.join(home, ".cache/waza-statusline/highwater.json");
  add(
    uninstall ? required : optional,
    removal(cache, "Reset statusline usage high-water mark"),
  );
  if (!safe(script) || !stat(script)?.isFile()) return;
  if (
    !statuslineSource ||
    !fs.readFileSync(statuslineSource).equals(fs.readFileSync(script))
  ) {
    if (!uninstall)
      warnings.add(
        `Statusline ownership could not be verified ${show(script)}`,
      );
    return;
  }
  const files = [removal(script, "Remove bundled Claude statusline")];
  const settings = json(settingsFile);
  const configured = settings?.statusLine;
  if (
    configured?.type === "command" &&
    ["~/.claude/statusline.sh", script].includes(configured.command)
  ) {
    const before = identity(settingsFile);
    files.unshift({
      description: `remove statusLine setting in ${show(settingsFile)}`,
      check() {
        if (!safe(settingsFile) || identity(settingsFile) !== before)
          throw Error("Claude settings changed");
      },
      apply() {
        this.check();
        delete settings.statusLine;
        const temporary = fs.mkdtempSync(
          path.join(path.dirname(settingsFile), ".setup-statusline-"),
        );
        try {
          const updated = path.join(temporary, "settings.json");
          fs.writeFileSync(updated, JSON.stringify(settings, null, 2) + "\n", {
            mode: stat(settingsFile).mode & 0o777,
          });
          fs.renameSync(updated, settingsFile);
        } finally {
          fs.rmSync(temporary, { recursive: true });
        }
      },
    });
  }
  optional.push({
    description: files.map((item) => item.description).join("; "),
    check() {
      files.forEach((item) => item.check());
    },
    apply() {
      files.forEach((item) => item.apply());
    },
  });
}

function piPackages(executable, root) {
  if (
    !executable ||
    !safe(root) ||
    !safe(executable) ||
    !safe(fs.realpathSync(executable))
  )
    return;
  const settingsFile = path.join(root, "settings.json");
  const npmRoot = path.join(root, "npm");
  const settings = json(settingsFile);
  const installed = settings?.packages;
  const hasSupportedStorage = () =>
    safe(npmRoot) &&
    (!stat(npmRoot) || stat(npmRoot).isDirectory()) &&
    !json(settingsFile)?.npmCommand;
  if (!Array.isArray(installed)) return;
  for (const name of bundledPackages) {
    const source = installed
      .map((entry) => (typeof entry === "string" ? entry : entry?.source))
      .find((entry) => entry === name || entry?.startsWith(name + "@"));
    if (!source) continue;
    if (!hasSupportedStorage()) {
      warnings.add(
        `Unprocessed Pi package ${show(source)} uses custom npm storage or command`,
      );
      continue;
    }
    const settingsBefore = identity(settingsFile);
    const command = checkedCommand(
      `Remove global Pi package ${show(source)} (may have been installed manually)`,
      executable,
      () => {
        if (!hasSupportedStorage()) throw Error("Pi package storage changed");
        run(executable, ["remove", source], {
          stdio: "inherit",
          env: {
            ...env,
            npm_config_ignore_scripts: "true",
            npm_config_global: "false",
          },
        });
      },
    );
    optional.push({
      ...command,
      check() {
        command.check();
        if (
          identity(settingsFile) !== settingsBefore ||
          !hasSupportedStorage()
        ) {
          throw Error("Pi package settings changed");
        }
      },
      needsCli: true,
    });
  }
}

function credentials(executable, root) {
  if (agent === "pi") return;
  const scoped = { ...env };
  const profile = profiles[agent];
  if (root === path.join(home, profile.fallback))
    delete scoped[profile.override];
  else scoped[profile.override] = root;
  const args = agent === "codex" ? ["logout"] : ["auth", "logout"];
  const claudeMcp =
    agent === "claude"
      ? new Set(
          [
            path.join(root, ".claude.json"),
            ...(root === path.join(home, profile.fallback)
              ? [path.join(home, ".claude.json")]
              : []),
          ]
            .flatMap((file) => Object.entries(json(file)?.mcpServers || {}))
            .filter(([, server]) => ["http", "sse"].includes(server?.type))
            .map(([name]) => name),
        )
      : [];
  credentialSteps.push(
    checkedCommand(
      `Clear ${agent} stored login for ${show(root)}`,
      executable,
      () => {
        if (agent === "codex") {
          const servers = JSON.parse(
            run(executable, ["mcp", "list", "--json"], { env: scoped }),
          );
          if (!Array.isArray(servers))
            throw Error("Unexpected Codex MCP inventory");
          for (const server of servers) {
            if (
              server.transport?.type === "streamable_http" &&
              !["unsupported", "not_logged_in"].includes(server.auth_status)
            ) {
              run(executable, ["mcp", "logout", server.name], { env: scoped });
            }
          }
        }
        for (const name of claudeMcp) {
          run(executable, ["mcp", "logout", name], { env: scoped });
        }
        run(executable, args, { env: scoped });
      },
    ),
  );
}

function customPiSessions(directory) {
  if (
    !safe(directory) ||
    !stat(directory)?.isDirectory() ||
    stat(path.join(directory, ".git"))
  ) {
    warnings.add(`Unprocessed custom session directory ${show(directory)}`);
    return;
  }
  for (const name of fs.readdirSync(directory)) {
    const file = path.join(directory, name);
    if (!safe(file) || !stat(file)?.isFile() || !name.endsWith(".jsonl"))
      continue;
    const buffer = Buffer.alloc(8192);
    const fd = fs.openSync(
      file,
      fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW,
    );
    let header;
    try {
      const length = fs.readSync(fd, buffer);
      const firstLine = buffer.toString("utf8", 0, length).split("\n")[0];
      try {
        header = JSON.parse(firstLine);
      } catch {
        continue;
      }
    } finally {
      fs.closeSync(fd);
    }
    if (
      header?.type === "session" &&
      typeof header.id === "string" &&
      typeof header.timestamp === "string" &&
      name.endsWith(`_${header.id}.jsonl`)
    ) {
      add(required, removal(file, "Delete Pi session"));
    }
  }
}

async function pickOptionalItems() {
  const input = process.stdin;
  const output = process.stdout;
  const wasRaw = input.isRaw;
  const selected = new Set();
  const pageSize = Math.max(1, Math.min(8, (output.rows || 24) - 7));
  let cursor = 0;

  function render() {
    const start = Math.floor(cursor / pageSize) * pageSize;
    const rows = optional.slice(start, start + pageSize).map((item, offset) => {
      const index = start + offset;
      return `${index === cursor ? ">" : " "} [${selected.has(index) ? "x" : " "}] ${item.description}`;
    });
    output.write(
      [
        "\x1b[H\x1b[2J" + `Agent / ${action} / ${agent} / Optional items`,
        "",
        ...rows,
        "",
        `Item ${cursor + 1}/${optional.length} | Selected: ${selected.size}`,
        "↑↓ Move   Space Toggle   Enter Continue",
        "a All   n None   Esc/q Cancel",
        "",
      ].join("\n"),
    );
  }

  emitKeypressEvents(input);
  input.setRawMode(true);
  output.write("\x1b[?25l");
  try {
    return await new Promise((resolve) => {
      function finish(result) {
        input.removeListener("keypress", onKey);
        input.removeListener("end", onEnd);
        input.pause();
        resolve(result);
      }
      const onEnd = () => finish(null);
      function onKey(character, key) {
        switch (key.name) {
          case "up":
            cursor = (cursor + optional.length - 1) % optional.length;
            break;
          case "down":
            cursor = (cursor + 1) % optional.length;
            break;
          case "space":
            if (selected.has(cursor)) selected.delete(cursor);
            else selected.add(cursor);
            break;
          case "a":
            optional.forEach((_, index) => selected.add(index));
            break;
          case "n":
            selected.clear();
            break;
          case "return":
            return finish(optional.filter((_, index) => selected.has(index)));
          case "escape":
          case "q":
            return finish(null);
          case "c":
            if (key.ctrl) return finish(null);
            return;
          default:
            return;
        }
        render();
      }
      input.on("keypress", onKey);
      input.once("end", onEnd);
      render();
      input.resume();
    });
  } finally {
    input.setRawMode(wasRaw);
    output.write("\x1b[?25h");
  }
}

async function main() {
  if (
    !["Cleanup", "Uninstall"].includes(action) ||
    !Object.hasOwn(profiles, agent) ||
    !home ||
    fs.realpathSync(home) !== home ||
    home === "/" ||
    stat(home).uid !== process.getuid() ||
    process.getuid() === 0
  )
    throw Error("Unsafe user home");
  const profile = profiles[agent];
  const fallback = path.join(home, profile.fallback);
  const configured =
    env[profile.override]?.replace(/^~\//, home + "/") || fallback;
  const roots = [...new Set([fallback, configured])];
  const executable = paths[0];
  const managed =
    agent === "pi" && executable ? managedPi(executable) : undefined;
  const installation =
    uninstall && executable ? managed || cliPlan(executable, roots) : undefined;

  if (uninstall && !installation) {
    const guide = {
      codex: "https://developers.openai.com/codex/cli",
      claude: "https://code.claude.com/docs/en/setup#uninstall-claude-code",
      pi: "https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/quickstart.md#uninstall-pi",
    };
    throw Error(
      executable
        ? `Manual uninstall required for ${show(executable)}. Use its original installer or package manager. ${guide[agent]}`
        : `No ${agent} CLI found on PATH; cannot verify or clear CLI-managed credentials`,
    );
  }
  if (!uninstall && agent !== "claude") {
    const cache = agent === "codex" ? "models_cache.json" : "models-store.json";
    for (const root of roots)
      add(
        optional,
        removal(path.join(root, cache), "Remove model catalog cache"),
      );
  }
  if (agent === "claude") statusline();
  if (agent === "pi" && executable)
    piPackages(managed?.launcher || executable, configured);

  if (uninstall) {
    for (const root of roots) {
      if (
        safe(root) &&
        stat(root)?.isDirectory() &&
        !stat(path.join(root, ".git"))
      ) {
        credentials(executable, root);
      }
      scanRoot(root, profile);
    }
    if (agent === "claude")
      add(
        required,
        removal(path.join(home, ".claude.json"), "Delete user state"),
      );
    if (agent === "pi") {
      const sessionDirs = new Set([
        env.PI_CODING_AGENT_SESSION_DIR,
        ...roots.map(
          (root) => json(path.join(root, "settings.json"))?.sessionDir,
        ),
      ]);
      for (const sessionDir of sessionDirs) {
        if (typeof sessionDir !== "string" || !sessionDir) continue;
        const directory = sessionDir.replace(/^~\//, home + "/");
        if (!roots.some((root) => directory === path.join(root, "sessions")))
          customPiSessions(directory);
      }
    }
  }

  const preview = [];
  if (!uninstall) for (const warning of warnings) preview.push(warning);
  if (uninstall) {
    preview.push(
      `Selected CLI ${show(installation.launcher || executable)} (${installation.method})`,
    );
    for (const file of installation.externalLinks || []) {
      warnings.add(
        `Launcher link ${show(file)} is outside the permitted removal scope and will remain after its target is removed`,
      );
    }
    const other = paths
      .slice(1)
      .filter((file) => !installation.files?.includes(file));
    for (const file of other) {
      let target;
      try {
        target = fs.realpathSync(file);
      } catch (error) {
        if (error.code !== "ENOENT") throw error;
      }
      const sharesInstall =
        target &&
        (target === fs.realpathSync(executable) ||
          (installation.install && within(installation.install, target)));
      const impact = sharesInstall
        ? "will lose its executable target"
        : "may lose shared user data";
      preview.push(`Other CLI path ${show(file)} ${impact}.`);
    }
    if (agent === "claude")
      preview.push(
        "Claude desktop and IDE clients may share these data paths.",
      );
    if (agent === "pi")
      preview.push(
        "Removing Pi settings also removes extension enablement records.",
      );
  } else if (!optional.length) {
    for (const message of preview) console.log(message);
    console.log("No verified cleanup items found.");
    return;
  }

  const interactivePicker = process.stdin.isTTY && process.stdout.isTTY;
  const picked =
    interactivePicker && optional.length ? await pickOptionalItems() : [];
  if (picked === null) {
    console.log("Cancelled.");
    return;
  }
  const terminal = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });
  try {
    let selected = picked;
    if (optional.length && !interactivePicker) {
      optional.forEach((item, index) =>
        console.log(`  ${index + 1}) ${item.description}`),
      );
      const answer = (
        await terminal.question(
          "Optional items (comma-separated numbers, Enter for none): ",
        )
      ).trim();
      if (answer) {
        const indices = [
          ...new Set(answer.split(",").map((value) => value.trim())),
        ];
        if (
          indices.some(
            (value) =>
              !/^[1-9]\d*$/.test(value) || Number(value) > optional.length,
          )
        ) {
          throw Error("Invalid selection; no changes made");
        }
        selected = indices.map((value) => optional[Number(value) - 1]);
      }
    }

    const cli = [];
    if (installation?.command) cli.push(installation.command);
    if (installation?.files) {
      for (const file of installation.files)
        cli.push(removal(file, "Remove CLI launcher"));
      cli.push(removal(installation.install, "Remove CLI installation", true));
      if (cli.some((item) => !item))
        throw Error("Cannot verify CLI removal paths");
    }
    const plan = [
      ...credentialSteps,
      ...selected.filter((item) => item.needsCli),
      ...selected.filter((item) => !item.needsCli),
      ...cli,
      ...required,
    ];
    for (const message of preview) console.log(message);
    if (!plan.length) return;
    for (const warning of warnings) if (uninstall) console.log(warning);
    console.log("\nExecution preview");
    if (uninstall)
      console.log("This permanently removes the listed data without a backup.");
    for (const item of plan) console.log(`  ${item.description}`);
    const answer = (
      await terminal.question("Apply these changes? [y/N]: ")
    ).trim();
    if (!/^y$/i.test(answer)) {
      console.log("Cancelled.");
      return;
    }
    // Validate the preview before commands that legitimately rewrite settings or credentials.
    for (const item of plan) item.check();
    for (const item of plan) {
      item.apply();
      console.log(`Completed: ${item.description}`);
    }
    if (warnings.size && uninstall)
      throw Error("Uninstall left unprocessed paths listed above");
  } finally {
    terminal.close();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
