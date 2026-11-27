# Agent、Skills 和 Rules 的三平台支持

核对日期 2026-11-27。议题见 [核对 Agent、Skills 和 Rules 的三平台支持](https://github.com/gwyntoria/skills/issues/9)。Windows 指 PowerShell 或 CMD 中运行原生 Windows 进程。WSL 中的 Ubuntu 属于 Linux 环境，拥有自己的工具链和文件路径。以下结论依据上游文档、当前工作区的 `scripts/gwyn-tool.sh` 和 `scripts/gwyn-tool/`，以及 Ubuntu 22.04.5 上的有限启动检查。

## Agent 安装、更新、清理和卸载

四个上游 CLI 都有原生 Windows、macOS 和 Linux 安装方式。当前 `gwyn-tool` 的入口和生命周期实现面向 POSIX 环境。Ubuntu 属于上游 Linux 路径，具体架构、系统库和最低版本仍随发行渠道而异。

| Agent | Windows 原生上游 | macOS / Ubuntu 上游 | 当前 `gwyn-tool` 清理与卸载 |
| --- | --- | --- | --- |
| Codex | PowerShell 独立安装器支持 x64、ARM64，原渠道可重新运行安装器更新。可以用 npm 安装、更新或卸载。独立版卸载应先核对实际 launcher、独立安装目录及 PATH。若启用了旧版 Windows 沙箱，`codex sandbox uninstall` 可单独卸载其机器级资源，需要管理员权限。[^1][^2][^3] | 官方 shell 安装器、npm，macOS 另有 Homebrew cask。安装渠道可分别更新，支持自更新的发布版提供 `codex update`。npm 和 Homebrew 安装由相应包管理器卸载。[^1][^2] | 清理可选模型目录缓存、未归档和归档会话。卸载只接受核验通过的独立版 launcher 或用户所有的 npm 安装，按计划处理 CLI、CLI 管理的登录和本地数据。Homebrew、非预期布局和无法识别的 launcher 走原渠道。 |
| Claude Code | PowerShell 或 CMD 的原生安装器、WinGet、npm。Git for Windows 可选，未安装时 CLI 可用 PowerShell 工具。原生安装后台更新，也可用 `claude update`。WinGet 用原渠道升级或卸载，官方文档另列原生安装和可选配置清除。[^4] | 官方支持 macOS 13+、Ubuntu 20.04+。原生 shell 安装器、npm，以及适用时的 Homebrew cask 或发行版包。原生安装可用 `claude update`，包管理器安装按原渠道更新与卸载。CLI 与桌面及 IDE 客户端可能共用 `~/.claude/`。[^4] | 清理可选经 `lsof` 确认未被使用的旧二进制、本地会话和自带 statusline。卸载识别核验通过的用户目录原生版与 npm 版，其他渠道手动处理。整目录清除需单独确认，预览提示跨客户端共享的路径。 |
| Pi | 官方 PowerShell 安装器或 npm。手动 npm 安装需 Node.js 22.19+。Windows 的 Bash 工具默认用 Git Bash，也可启用 PowerShell 工具。安装器支持卸载，npm 安装用 npm 卸载。[^5][^6] | 官方 shell 安装器、npm、Nix，适用时可用 Homebrew 的 `pi-coding-agent` formula。安装器支持卸载，Nix 和 Homebrew 走原渠道。`pi update` 更新本体，`pi update --extensions` 更新已安装包。官方卸载方法保留配置、凭据、会话及 Pi 包。[^5][^7][^8] | 清理可选模型目录缓存、归档和未归档会话及识别到的附带包。卸载识别受管安装和当前/旧 npm 包名，并检查其他 launcher。核验通过的 Homebrew formula 交给 Homebrew 卸载。整目录和自定义会话路径按预览处理。 |
| Antigravity CLI | 官方 PowerShell 或 CMD 安装器，默认 launcher 在 `%LOCALAPPDATA%\agy\bin`。提供后台自更新，更新依赖安装目录可写。[^9][^10][^11] | 官方 shell 安装器，默认 `~/.local/bin/agy`。支持后台自更新和 `agy update`。已查官方入门和排障文档给出了安装位置及更新机制，完整 CLI 卸载入口仍待确认。[^9][^10][^11] | 清理可选 CLI 本地会话。卸载只接受用户 home 下精确位置且版本可核验的 POSIX 可执行文件，可选移除 `~/.gemini/antigravity-cli`。保留共享配置 `~/.gemini/config` 和共享登录。 |

仓库中的安装计划使用四家的 **shell** 安装器，仅在找不到命令时执行安装。Pi 的菜单单独要求本机 Node.js 和 npm，可尝试加载 nvm 默认版本。Agent 清单依 `PATH` 顺序显示入口与解引用后的实际文件，首个入口标记为当前入口。列表手工拼接无后缀命令名，原生 Windows 的 `.exe`、`.cmd`、shim 和别名覆盖不完整。清理默认保留会话、CLI 和凭据。卸载需核验渠道和路径，且默认保护共享 Skills。代码见 `config/execution.py`、`agents/list_installed.py`、`agents/lifecycle.py`、`agents/profiles.py` 和 `agents/user_paths.py`。

Shell 入口要求 Bash 5+，TUI 要求 Python 3.10+ 与交互终端。原生 Windows 的缺口涉及 Bash 入口、标配 Python 中缺少 `curses`、子进程管道与进程组处理，以及 `getuid`、`O_NOFOLLOW`、`O_DIRECTORY`、`dir_fd` 等文件检查。清理当前以 POSIX UID、设备号、真实路径及文件类型约束删除范围。Windows 需要为 ACL、文件身份及 reparse point 建立等价的校验。Git Bash 能提供部分命令，Python 和文件系统保护仍需独立验证。macOS 与 Ubuntu 使用同一实现，仍各自需要核对命令、工具版本和安装布局。[^12][^13]

## 附带组件与默认更新

| 项目 | 现有覆盖和平台边界 |
| --- | --- |
| Claude statusline | 安装 Claude 时写入 `~/.claude/statusline.sh` 与 `settings.json` 的 `statusLine`。脚本依赖 Bash 和 `jq`，Git 提供分支信息。上游支持 Windows 的 Git Bash 和 PowerShell statusline。仓库脚本需要验证 Git Bash、路径和依赖，纯 PowerShell 需要相应入口。当前独立清理可识别仓库自带脚本及设置。默认更新未单独更新该脚本。[^14] |
| Pi 附带包 | 安装随 Pi 执行 `pi install`，包为 `npm:pi-web-access`、`npm:pi-subagents`、`npm:pi-powerline-footer`。统一使用 Pi 的包更新机制，清理针对识别到的已安装附带包。Web Access 还需验证所选搜索提供方与授权，Subagents 要求 Pi 1.2.0+，后台运行的发行版及平台另有限制，Powerline Footer 需验证终端、字体与 ASCII 回退。安装成功与扩展能运行应分别验证。[^7][^15][^16][^17] |
| Antigravity statusline | 仓库另有 `scripts/statusline/antigravity.py`，`gwyn-tool` 安装计划没有为 `agy` 配置附带组件。默认更新只执行 `agy update`，没有插件或 statusline 更新步骤。 |
| Codex 与 Claude 插件 | Codex 在本体更新分支中运行 `codex plugin marketplace upgrade`，本体不提供更新命令时整项跳过。Claude 分别探测 marketplace 更新和 JSON 清单，按所列 scope 更新可识别插件，project/local 仅处理当前项目，跳过 inline、同步及内置等来源。插件列表解析依赖 Python 3.10+。插件更新仍受登录、来源与组织策略限制。[^2][^18] |
| 全局 Skills | 无参数首先执行 `npx skills update -g -y`。Vercel 当前要求 Node.js 22.20+，按可识别的安装记录处理更新。项目 Skills、独立手写文件及 Agent 内置 Skills 不在该命令的更新范围内。原生命令可用性、全局锁格式、既有路径和工具版本需同测。[^19][^20] |
| Homebrew | 最后执行 `brew upgrade --no-ask`，PATH 中无 `brew` 则跳过。适用 macOS 和已安装 Linuxbrew 的 Ubuntu。Windows 文档路径是 WSL 2，原生 Windows 跳过。Homebrew 自身会按策略跳过部分自动更新 cask，当前脚本也无 WinGet、apt 或 Nix 更新步骤。[^21][^22] |

默认更新依据当前 PATH 和 CLI 帮助判定是否有更新能力。Pi 本体额外要求帮助包含 `--self`，附带包独立探测 `--extensions`。该判断不能确认安装渠道允许自更新。后续任务会继续执行，任一任务失败时最终退出码为 1。代码见 `scripts/gwyn-tool.sh`。

## Skills 和 Rules 范围与已安装清单

| 内容 | 上游发现范围 | 仓库当前行为 |
| --- | --- | --- |
| Codex Skills / Rules | Skills 从用户和项目的 `.agents/skills`、安装内置等位置读取，支持技能目录软链接。规则文本使用 `$CODEX_HOME/AGENTS.md` 与项目祖先链，同层非空 `AGENTS.override.md` 优先。另外有单独的命令执行策略 `.rules`。[^23][^24][^25] | Shared 清单列 `.agents/skills`，Codex 栏还检查 `.codex/skills` 和全局 `CODEX_HOME` 对应路径。规则写入和清单仍固定 `~/.codex/AGENTS.md`。 |
| Claude Skills / Rules | Skills 用用户或项目的 `.claude/skills`，也有企业、插件和同步来源。普通技能目录支持软链接。规则用 `CLAUDE.md` 或用户/项目 `.claude/rules`。项目规则链接指向工作目录外时需批准，带 `paths` 的外部规则即使批准也不加载，UNC 等网络链接会被忽略。[^26][^27] | 从 `.claude/skills` 列项目和全局，另探测全局内置技能。特殊全局规则 `agent-behavior` 追加到 `CLAUDE.md`，其余追加到 `~/.claude/rules/<name>.md`。生命周期识别 `CLAUDE_CONFIG_DIR`，Vercel 的全局 Skills 安装也识别该变量。[^28]仓库的清单、Rules 和 statusline 仍读写默认位置。 |
| Pi Skills / Rules | 支持用户 agent 目录与项目 `.pi/skills`，也读用户和项目 `.agents/skills`。源码会跟随指向目录的软链接。规则从 agent 目录以及当前目录和祖先的上下文文件发现。同层的 `AGENTS.override.md` 可替代常规文件。[^29][^30][^31] | 安装通过 Shared 提供技能。清单还扫描 Pi 自有目录、嵌套与独立 Markdown，支持全局 `PI_CODING_AGENT_DIR`。全局规则写入该目录或 `~/.pi/agent/AGENTS.md`。现有技能移除范围仅处理 Shared 和纳入扫描的 Agent 安装位置，移除菜单未覆盖 Pi 自有目录。 |
| Antigravity Skills / Rules | 项目用 `.agents/skills`、`.agents/rules`、`AGENTS.md` 或 `GEMINI.md`，用户用 `~/.gemini/config/skills`、`~/.gemini/config/rules` 及全局指导文件。CLI 另读自己的历史技能路径。App 和 CLI 共用配置，官方提供继承共享目录的清单格式。[^32][^33] | 项目技能走 Shared。全局可选从 Shared 向 `~/.gemini/config/skills` 创建单技能链接，遇到现有目录链接或同名条目即保留。清单检查该全局位置及内置包。全局规则按文件建在配置目录，加入 `trigger: always_on`。 |

工具对项目范围以启动时的当前目录为根。Skills 安装委托 `npx skills add`，默认项目范围，可选全局。已安装清单用 `skills-lock.json` 或 `.agents/.skill-lock.json` 补充来源，仍能列出部分手工安装和改名软链接。Claude 和 Antigravity 内置 Skills 依赖本地探测，超时或探测失败时可能显示空清单。清单覆盖的目录与各 Agent 的完整发现路径有差异，需在 Agent 内确认实际加载情况。项目 Rules 对四个 Agent 一律写到 `docs/rules/<name>.md`，需要从该 Agent 会加载的指令文件明确引用。规则移除以整个文件或链接为单位，预览应核对其中是否混有手写内容。代码见 `config/session.py`、`content/list_installed.py`、`content/bundled_skills.py`、`content/removal.py` 和 `rules/installation.py`。

## 迁移约束及原生验收

- **先核对链接类型和落点。** 原生 Windows 创建 Python 软链接取决于 Developer Mode 或创建链接权限，且区分文件和目录。NTFS junction 与普通目录、目录软链接需要分别识别。Vercel 安装器源码有 Windows junction 和复制回退，仓库为 Antigravity 额外创建的链接使用 POSIX `dir_fd`，指向 Shared 的绝对路径。搬迁到另一台机器、盘符或 home 后应按新根重建链接。Git 在 `core.symlinks=false` 时把跟踪的链接检出为含目标文本的普通文件。macOS 和 Ubuntu 也要验证实际文件系统是否区分大小写、是否支持链接及 Rules 创建所需的同目录硬链接。[^13][^34][^35][^36]
- **先盘点技能外部引用，再移除共享源。** 当前只沿受管 Claude 和全局 Antigravity 的安装位置搜寻相关链接，跳过有链接父目录的路径。全局移除可单独选择已发现的外部单技能链接，整目录共享链接保留并提示影响。项目链接仅提示，其他项目、Pi、自定义目录及以绝对路径搬走的引用都需要额外盘点。复制回退会产生独立副本，不能依赖链接扫描发现它。现有移除会重验源条目和锁快照，先移除条目再原子替换锁，仍需演练删除成功而锁写入失败后的对账。代码见 `content/removal.py`。
- **原生 Windows 待实测。** 用标准用户在 PowerShell 和 CMD 分别安装和刷新 PATH，验证 `.exe`、`.cmd`、多入口、空格和非 ASCII 路径。分别验证默认更新和原渠道更新、凭据保留、组件能运行、可选会话清理与卸载。练习无链接权限和有权限的 NTFS 目录，覆盖 junction、悬空链接、跨盘链接、大小写碰撞和损坏的锁文件。确认取消与路径变更不会删除源目录、共享配置或跨客户端凭据。
- **macOS 待实测。** 用 Bash 5+、支持的 Python/curses 和真实终端验证菜单、取消与终端恢复，并确认旧版系统 Bash 运行更新或配置时会按预期拒绝。在实际支持的架构上核对独立版、npm 和 Homebrew 入口、cask 更新跳过和重复 launcher、Claude 旧版本占用和 statusline、Pi 扩展及 Skills/Rules 创建、列表与移除。
- **Ubuntu 待实测。** 当前 Ubuntu 22.04.5 上 `bash -n scripts/gwyn-tool.sh`、`bash scripts/gwyn-tool.sh -h`、`python3 -B scripts/gwyn-tool/main.py --help` 均成功，`TERM=xterm-256color bash scripts/gwyn-tool.sh config` 在 PTY 打开菜单并按 `q` 退出，退出码为 0。只读帮助探针中本机 Codex 列出 `update`，Pi 列出 `--self` 和 `--extensions`。仍需在隔离用户环境完成四个 CLI 和组件的安装、更新、清理、卸载，验证有无 Linuxbrew、不同安装渠道、会话保留以及 Skills/Rules 和链接实际加载。

跨平台验收可用隔离用户目录和项目做同一套操作，记录当前 launcher、安装渠道、各 scope 的条目与锁文件，然后重复运行并对照增删结果。回退时按原渠道恢复 CLI，从备份恢复内容及锁，再按目标平台创建链接。需要登录的 CLI 在目标平台重新认证。

## References

1. [^1]: OpenAI, [Codex CLI 安装与更新](https://learn.chatgpt.com/docs/codex/cli#getting-started)。
2. [^2]: OpenAI, [Developer commands](https://learn.chatgpt.com/docs/developer-commands)。
3. [^3]: OpenAI, [Codex Windows 安装器源码](https://releases.openai.com/codex/install.ps1)。
4. [^4]: Anthropic, [Claude Code Advanced setup](https://code.claude.com/docs/en/setup)。
5. [^5]: Earendil, [Pi Quickstart](https://docs.pi.dev/latest/quickstart)。
6. [^6]: Earendil, [Run Pi on Windows](https://docs.pi.dev/latest/windows)。
7. [^7]: Earendil, [Pi Command Line](https://docs.pi.dev/latest/cli)。
8. [^8]: Homebrew, [pi-coding-agent formula](https://formulae.brew.sh/formula/pi-coding-agent)。
9. [^9]: Google, [Antigravity CLI 入门](https://antigravity.google/docs/getting-started?tab=cli)。
10. [^10]: Google, [Antigravity CLI 排障](https://antigravity.google/docs/cli/troubleshooting/)。
11. [^11]: Google, [Antigravity 更新记录](https://antigravity.google/docs/changelog)。
12. [^12]: Python Software Foundation, [Curses Programming with Python](https://docs.python.org/3/howto/curses.html)。
13. [^13]: Python Software Foundation, [操作系统接口与软链接](https://docs.python.org/3/library/os.html#os.symlink)。
14. [^14]: Anthropic, [Claude Code statusline 的 Windows 配置](https://code.claude.com/docs/en/statusline#windows-configuration)。
15. [^15]: nicobailon, [pi-web-access](https://github.com/nicobailon/pi-web-access)。
16. [^16]: nicobailon, [pi-subagents](https://github.com/nicobailon/pi-subagents)。
17. [^17]: nicobailon, [pi-powerline-footer](https://github.com/nicobailon/pi-powerline-footer)。
18. [^18]: Anthropic, [安装和管理 Claude Code 插件](https://code.claude.com/docs/en/plugins/install)。
19. [^19]: Vercel, [Skills CLI](https://github.com/vercel-labs/skills)。
20. [^20]: Vercel, [Skills 更新源码](https://github.com/vercel-labs/skills/blob/main/src/update.ts)。
21. [^21]: Homebrew, [Homebrew on Linux](https://docs.brew.sh/Homebrew-on-Linux)。
22. [^22]: Homebrew, [brew 手册](https://docs.brew.sh/Manpage)。
23. [^23]: OpenAI, [Build skills](https://learn.chatgpt.com/docs/build-skills)。
24. [^24]: OpenAI, [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)。
25. [^25]: OpenAI, [Codex 命令执行规则](https://learn.chatgpt.com/docs/agent-configuration/rules)。
26. [^26]: Anthropic, [Claude Code Skills](https://code.claude.com/docs/en/skills)。
27. [^27]: Anthropic, [Claude Code 指令与规则加载](https://code.claude.com/docs/en/memory)。
28. [^28]: Vercel, [Skills Agent 路径源码](https://github.com/vercel-labs/skills/blob/main/src/agents.ts)。
29. [^29]: Earendil, [Pi Skills](https://docs.pi.dev/latest/skills)。
30. [^30]: Earendil, [Pi Configuration](https://docs.pi.dev/latest/configuration)。
31. [^31]: Earendil, [Pi 技能目录发现源码](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/skills.ts)。
32. [^32]: Google, [Antigravity 自定义内容发现](https://antigravity.google/docs/customization-discovery?tab=cli)。
33. [^33]: Google, [Antigravity Rules](https://antigravity.google/docs/rules/)。
34. [^34]: Vercel, [Skills 安装源码](https://github.com/vercel-labs/skills/blob/main/src/installer.ts)。
35. [^35]: Git, [core.symlinks](https://git-scm.com/docs/git-config#Documentation/git-config.txt-coresymlinks)。
36. [^36]: Microsoft, [Windows 和 Linux 文件系统](https://learn.microsoft.com/windows/wsl/filesystems)。
