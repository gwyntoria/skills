# Gwyn Space Skills

![Gwyn Space Skills](assets/readme-hero.png)

## Skills

### dialog

写作与分析方法。

| Skill | 适用场景 | 主要输出 |
| --- | --- | --- |
| [`wangshuo`](skills/dialog/wangshuo/SKILL.md) | 分析组织、市场、公共议题和个人重大选择等复杂问题 | 证据分级、激励与博弈分析、有限判断和行动条件 |
| [`hecaitou`](skills/dialog/hecaitou/SKILL.md) | 从日常观察切入，分析平台、产品、关系与个人边界 | 带有具体场景、机制分析和边界意识的中文长文 |

### work

报告与工程类技能。

| Skill | 适用场景 | 主要输出 |
| --- | --- | --- |
| [`daily-weekly-reporting`](skills/work/daily-weekly-reporting/SKILL.md) | 根据 Git 记录编写中文日报、周报或工作总结 | 区分已提交成果、未提交进展和待验证事项的工作报告 |
| [`scan-codebase`](skills/work/scan-codebase/SKILL.md) | 阅读实现代码前，先从 Git 历史判断仓库阶段与风险区域 | 当前阶段判断、风险地图和代码阅读顺序 |
| [`maintain-changelog`](skills/work/maintain-changelog/SKILL.md) | 按 Keep a Changelog 规范编写、更新或审核版本记录 | 有证据支撑的版本条目或分级审核结果 |

### writing

中文写作审读技能。

| Skill | 适用场景 | 主要输出 |
| --- | --- | --- |
| [`review-chinese-writing`](skills/writing/review-chinese-writing/SKILL.md) | 审读面向普通读者的中文非虚构稿件，判断能否发布 | 两阶段评审报告：合格判定、必须修改项和按收益排序的提升建议 |

### 使用示例

在支持 Skills 的 Agent 中，可以直调用：

```text
使用 $wangshuo 分析这个决策，区分事实、推论、风险和未知。
```

```text
使用 $hecaitou 把这件日常小事写成一篇中文随笔，保留不确定性。
```

```text
使用 $scan-codebase 扫描当前仓库，先不要读取实现代码。
```

```text
使用 $daily-weekly-reporting，根据今天所有分支的 Git 记录写一份日报。
```

```text
使用 $maintain-changelog 根据 v1.2.0 到 HEAD 的变化更新 Unreleased，并审核现有条目。
```

```text
使用 $review-chinese-writing 审读这篇稿子，先判断是否合格，再给修改建议。
```

### 补充说明

- `hecaitou` 与 `wangshuo` 使用 [dot-skill](https://github.com/titanwings/colleague-skill) 从公开材料中提炼的写作和分析方法。输出具有一定启发性，但与本人仍有不少差别，感兴趣的可以阅读他们的文章，再用相同的话题提问 AI。
- `scan-codebase` 所执行的内容来自 [The Git Commands I Run Before Reading Any Code](https://piechowski.io/post/git-commands-before-reading-code/) 中提到的 git 命令，适合接手新代码库时运行，了解仓库现状。

## Rules

规则按默认使用范围分为 `rules/global/` 和 `rules/project/` 两个目录，安装时仍使用文件名作为规则名。

| 文件 | 使用范围 | 说明 |
| --- | --- | --- |
| [`agent-behavior.md`](rules/global/agent-behavior.md) | 全局 | 可放在 Agent 的配置目录中，如 `~/.codex/`、`~/.claude/` |
| [`c-project.md`](rules/project/c-project.md) | 项目 | C/C++ 项目的格式、命名、注释和提交信息约定 |
| [`writing-repo.md`](rules/project/writing-repo.md) | 项目 | Markdown 写作仓库的资源路径、引用方式和格式检查规则 |
| [`chinese-punctuation.md`](rules/project/chinese-punctuation.md) | 项目 | 终端回复的中文半角标点、空格规则和适用范围 |

规则通过 [`scripts/agent-setup.sh`](scripts/agent-setup.sh) 的交互菜单安装：选择 `Install / Update` → `Rules`，依次多选规则、多选目标 Agent、选择 Global 或 Project 范围，再确认安装。Agent 默认全选，规则默认不选；选择页支持 `b` 返回、`q` 退出，并保留勾选与光标。确认页展示资源来源和完整安装路径。规则页按 `rules/global/` 和 `rules/project/` 来源分组列出全部规则，允许跨范围安装；所选规则统一安装到最后选择的范围，确认页保留原始来源。

```bash
# 在仓库中打开菜单，可安装规则或安装本地命令
bash scripts/agent-setup.sh

# 在菜单选择 Install / Update this command 后，在任意项目运行
cd /path/to/project
agent-setup
```

Project 规则安装到启动命令时的当前目录，包括 Git 子目录和非 Git 目录，不自动寻找仓库根目录。先确认当前路径，再在确认页执行安装。

资源相对脚本实际位置查找，符号链接会解析到真实脚本。`rules/global/`、`rules/project/` 和 `scripts/statusline.sh` 分别优先使用本地内容；缺少某个目录或文件时，从 GitHub `gwyntoria/skills` 的 `main` 分支下载临时资源，同一次运行复用，退出清理。本地规则目录不会混入远端规则，格式错误直接报告；远端获取失败不覆盖配置。改了本地 `rules/` 后重新安装即可更新。

`Install / Update this command` 将命令安装到 `~/.local/bin/agent-setup`。实际脚本位于 `scripts/agent-setup.sh` 且仓库根目录存在 `rules/` 时，安装当前版本；从独立位置运行时，下载 GitHub `main` 最新脚本。安装文件通过 `bash -n` 后原子替换，下载或检查失败保留旧命令，下次启动生效。PATH 缺少 `~/.local/bin` 时仅打印配置方法，不修改 shell 配置。需要 Bash；远端获取需要 cURL、tar；保留原有 CLI 和 skills 安装任务所需的 Node.js、npx 等依赖。

### 补充说明

[`agent-behavior.md`](rules/global/agent-behavior.md) 中的以下规则来源于 [Waza 项目的 `rules` 目录](https://github.com/tw93/Waza/tree/main/rules)，并按个人使用习惯做了调整：

- [`Chinese Anti-AI Patterns`](rules/global/agent-behavior.md#chinese-anti-ai-patterns)：源自 Waza 的 [`rules/chinese.md`](https://github.com/tw93/Waza/blob/main/rules/chinese.md)。
- [`English Coaching`](rules/global/agent-behavior.md#english-coaching)：源自 Waza 的 [`rules/english.md`](https://github.com/tw93/Waza/blob/main/rules/english.md)。
- [`Anti-Patterns: Cross-Skill AI Behavior`](rules/global/agent-behavior.md#anti-patterns-cross-skill-ai-behavior)：源自 Waza 的 [`rules/anti-patterns.md`](https://github.com/tw93/Waza/blob/main/rules/anti-patterns.md)。

## Scripts

[`scripts/`](scripts/) 下是个人环境安装、WSL 配置和仓库维护三类辅助脚本。

| 脚本 | 运行环境 | 说明 |
| --- | --- | --- |
| [`agent-setup.sh`](scripts/agent-setup.sh) | macOS / Linux | 统一交互安装全局或项目 rules、Agent 配置和第三方 skills；支持安装本地命令、非交互安装及 `--list` 候选清单 |
| [`env-setup-wsl.sh`](scripts/env-setup-wsl.sh) | WSL Ubuntu | 装配 Homebrew、Git、lazygit、Starship、uv、Python、nvm、Node.js 和 Codex CLI |
| [`env-update.sh`](scripts/env-update.sh) | macOS / Linux | 依次更新 skills、Codex、Claude Code 和 Homebrew，末尾汇总每个任务的结果 |
| [`statusline.sh`](scripts/statusline.sh) | Claude Code | 状态栏脚本，显示模型与思考等级、目录与 Git 分支、上下文余量、输入输出 token、速率限制和版本 |
| [`list-skills.sh`](scripts/list-skills.sh) | 仓库维护 | 列出仓库内全部 skill 路径，并检查是否有重名 |

### 补充说明

- 无参数运行 `bash scripts/agent-setup.sh` 进入终端菜单：方向键移动、空格勾选、`a` 全选、`n` 取消全选、回车继续、下级选择页面按 `b` 返回上一级、`q` 退出整个流程。主菜单只显示适用的导航按键；安装任务顺序为 Skills、Rules、Codex CLI、Claude Code CLI、Claude 状态栏。返回后保留勾选与光标位置，同一次运行中复用已获取的 skills 候选。Codex CLI、Claude Code CLI、Rules、Claude 状态栏可以分别选择；skills 先按来源仓库分组，仓库页按 Space 全选或取消该仓库，Enter 展开单个 skill 多选，选择完成后通过仓库页的 `Continue` 进入下一步；`[ ]`、`[-]`、`[x]` 分别表示未选、部分选中和全选。仓库内 Enter 或 `b` 返回仓库页并保留选择，`a`、`n` 作用于当前层级。安装目标可选 Codex、Claude Code 或两者。安装项目默认不选，执行前展示清单并确认。菜单使用 Bash 内置能力，不依赖额外的 TUI 工具。
- 交互模式中，每项任务成功、失败、确认取消或没有可操作内容后，结果日志会停留，按 Enter 返回首页继续选择；结果页和各级菜单仍支持 `q` 退出，首页也可选 `Exit`，`b` 继续返回上一级。回到首页后重置本轮勾选、光标和结果统计，候选清单与临时资源在会话内复用；流程内返回上一级仍保留选择。依赖检查、资源获取或执行失败不会阻止下一项任务。只要会话中曾有失败，最终退出码就为非零，后续任务成功不会清除失败状态；Ctrl-C 和终端关闭仍可中断。非交互参数执行一次后退出。
- `agent-setup.sh --agent` 安装两个 CLI、全局 `agent-behavior` 规则和状态栏（支持本地资源与远端回退）；`--skill` 安装全部候选 skills，保留已有内容；两个参数可以同时使用并保持非交互执行。`--list` 只列出可安装 skills，不执行安装，不能与安装参数组合。Waza、Kami 和 Gwyntoria（`gwyntoria/skills`）从来源仓库读取候选，Matt Pocock 沿用官网清单，HumanLayer 安装 `show-me`。候选获取失败后继续展示其他来源，同一来源仓库中选中的 skills 合并为一条安装命令，仓库批次失败后继续处理其他仓库，不自动逐项重试；结尾按安装批次汇总结果，有失败时返回非零退出码。无参数且没有终端时会提示使用参数并退出。
- 首页统一使用 `Remove`：先单选 Global / Project（默认 Global），再多选 Agent（默认全选），再多选 Rules / Skills（默认不选），扫描所选范围内这些 Agent 的已安装内容，然后逐项选择并统一确认。Project 使用启动命令时的当前目录，不查找 Git 根目录，也不递归扫描子项目；范围同时作用于 rules 和 skills。删除不联网，不依赖源仓库；rules、skills 和仓库默认均不勾选。skills 使用与安装相同的仓库分层选择，同名 skill 按 Agent 显示为独立条目，可只删除某个 Agent 的某个 skill。没有可用来源记录的内容归入 `Unknown / local`，实际目录和链接决定候选，锁文件只辅助识别来源。
- 删除 skills 时，Global 范围中 Codex 对应共享的 `~/.agents/skills` 条目，Claude 对应 `~/.claude/skills` 条目；Project 范围对应当前项目的 `.agents/skills` 和 `.claude/skills`，两种范围都保留 `.system`。全局锁文件使用 `~/.agents/.skill-lock.json`，项目锁文件使用项目根目录的 `skills-lock.json`，来源分组与锁记录更新只使用所选范围的锁文件。只清理已成功删除的共享 skill 对应的锁记录，保留其他 skill、锁文件顶层字段和未知字段；Claude-only 删除保留共享源和锁记录。未选中的 Claude 链接若会因共享源删除而失效，确认页用红色列出；其他 Agent 也可能使用共享目录。软链接只删除链接本身，不跟随目标；无法解析的锁文件会使 skill 归入未知来源，修改共享源前必须有可读取的锁文件（原本不存在锁文件时不创建）。
- 删除 rules 时，Global 范围扫描 `~/.codex/AGENTS.md` 和 `~/.claude/CLAUDE.md` 中所有可识别的 `gwyn-space-skills` 托管块，按 Agent 分别列出，只移除所选块并保留个人文字和其他块；Claude `~/.claude/rules` 中的自定义文件、隐藏文件及子目录内文件也可逐项选择。Project 范围扫描项目根目录 `AGENTS.md` 的托管块及 `.claude/rules` 中的文件和链接，保留手写内容与未选块；不扫描项目的 `CLAUDE.md`、`.claude/CLAUDE.md` 或 `.codex/AGENTS.md`。文件和目录软链接作为独立链接列出，只删除链接本身。未选内容和实际目录本身保留，不再提供整目录清空询问。
- 每次新删除流程重新扫描，并在预览、执行、备份完成后核对所选对象的路径及内容指纹；内容或锁文件变化时停止这一轮，需重新扫描选择。统一输入一次 `DELETE` 后，先把所有所选文件、规则块所在文件、skill 目录、链接及需要更新的锁文件备份到权限为 `0700` 的 `~/.agent-rules-backup-*/removal.tar` 或 `~/.agent-skills-backup-*/removal.tar`，备份失败不删除任何条目；单项删除失败则继续其余项并逐项汇总。全局和项目备份均存放在 HOME，项目位于 HOME 外也可备份；恢复命令的目标目录与所选范围一致。日志记录范围、Agent、对象、路径、备份和 `tar -xf` 恢复命令；回滚前停止安装或删除操作，执行对应恢复命令并保留备份供核对。
- 安装或更新目标使用绿色，删除目标使用红色，备份路径和恢复命令使用青色，风险提示使用黄色；确认页、执行日志与结果汇总标明操作对象及路径。受影响的未删除 Claude 链接继续用红色提醒。
- 主菜单的 `Remove all backups` 清理 HOME 直属的安装器备份目录：`.agent-skills-backup-` 或 `.agent-rules-backup-` 加六位字母数字后缀。先列出实际路径，输入 `DELETE` 后只删除确认清单中的目录；跳过软链接、不匹配名称和其他备份文件。日志逐项记录删除结果。清理不会再创建备份，删除后无法使用这些备份回滚；仍需保留的备份应在执行前复制到其他位置。
- 安装器的隔离回归检查使用 Python 3 标准库运行：`python3 scripts/tests/test_agent_setup.py`。检查不安装真实 CLI 或 skills，不修改当前用户配置。
- `agent-setup.sh` 将全局 `agent-behavior.md` 分别写入 `~/.claude/CLAUDE.md` 和 `~/.codex/AGENTS.md` 的 `<!-- gwyn-space-skills: <规则>:start -->` 与 `:end` 托管块；项目规则仍使用 Claude Code 的 `.claude/rules/`，Codex 项目规则写入项目 `AGENTS.md` 的托管块。**块内手改会在下次安装时被覆盖**，块外内容不受影响。规则清单由 `rules/global/*.md` 和 `rules/project/*.md` 决定，加一个文件就多一条规则；安装范围由范围页决定，源目录用于标识规则来源。规则文件名只能使用字母、数字、点、下划线和连字符，并以字母或数字开头；内容必须以 Markdown H1 开头。
- 从 `agent-setup.sh` 早期版本升级时，`~/.claude/CLAUDE.md` 与 `~/.codex/AGENTS.md` 可能是和 `agent-behavior.md` 逐字节相同的整文件副本。`agent-setup.sh` 检测到这种副本会先创建 `.pre-rules.bak-<时间戳>` 备份，再改成托管块。旧版 `~/.claude/rules/global.md` 与仓库内容完全相同时会移到 `~/.claude/` 下备份；文件已被修改或是软链接时会停止安装并保留原文件。迁移过程保留备份供恢复。
- `env-update.sh` 按固定顺序执行更新，前置命令不存在时记为跳过而不是失败，最后打印成功、失败和跳过的清单；带 `-c` 时在 Homebrew 更新后追加 `brew cleanup`。交互终端使用 Bash 和终端控制序列把进度固定在最后一行，上方保留日志和普通确认输入；任务切换时更新底栏，退出或 Ctrl-C 时恢复终端。子程序清屏、全屏交互和运行中缩放窗口可能影响底栏，尺寸在下一次任务边界重新读取。重定向或定时任务保持普通输出。
- `statusline.sh` 由 `agent-setup.sh` 从本地或远端资源复制到 `~/.claude/statusline.sh`，其中速率限制一段只在会话上报数据时显示。

## 安装

### npx skills

安装前需要本地已有 Node.js 与 npm。运行下面的命令，从仓库中选择需要的 skill 和目标 Agent：

```bash
npx skills add gwyntoria/skills -g -y
```

也可以直接安装指定的 skill：

```bash
npx skills add gwyntoria/skills -g --skill scan-codebase
```

### Claude Code marketplace

添加 marketplace 并安装插件：

```bash
claude plugin marketplace add gwyntoria/skills
claude plugin install gwyn-space-skills-work@gwyn-space
claude plugin install gwyn-space-skills-dialog@gwyn-space
claude plugin install gwyn-space-skills-writing@gwyn-space
```

安装或更新插件后，新建会话以加载最新的 skill。
