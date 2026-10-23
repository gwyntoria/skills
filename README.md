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

## Instructions

规则按默认使用范围分为 `instructions/global/` 和 `instructions/project/` 两个目录，安装时仍使用文件名作为规则名。

| 文件 | 使用范围 | 说明 |
| --- | --- | --- |
| [`agent-behavior.md`](instructions/global/agent-behavior.md) | 全局 | 可放在 Agent 的配置目录中，如 `~/.codex/`、`~/.claude/` |
| [`c-project.md`](instructions/project/c-project.md) | 项目 | C/C++ 项目的格式、命名、注释和提交信息约定 |
| [`writing-repo.md`](instructions/project/writing-repo.md) | 项目 | Markdown 写作仓库的资源路径、引用方式和格式检查规则 |
| [`chinese-punctuation.md`](instructions/project/chinese-punctuation.md) | 项目 | 终端回复的中文半角标点、空格规则和适用范围 |

这些 instruction 是可复用的规则片段，可以用 [`scripts/agent-install-rule.sh`](scripts/agent-install-rule.sh) 安装。脚本直接读取工作区里的 `instructions/`，不依赖网络，但因此**需要先 clone 本仓库**，再从仓库里运行:

```bash
git clone https://github.com/gwyntoria/skills.git
cd skills

# 全局。写入 ~/.claude/CLAUDE.md 和 ~/.codex/AGENTS.md 里的托管块
scripts/agent-install-rule.sh agent-behavior --target both --global

# 项目级。写进当前仓库的 .claude/rules/ 和 AGENTS.md
scripts/agent-install-rule.sh writing-repo --target both

# 查看安装状态，或撤销
scripts/agent-install-rule.sh --list
scripts/agent-install-rule.sh agent-behavior --remove
```

改了 `instructions/` 下的文件后重新运行即可生效，不需要发版或切 ref。

### 补充说明

[`agent-behavior.md`](instructions/global/agent-behavior.md) 中的以下规则来源于 [Waza 项目的 `rules` 目录](https://github.com/tw93/Waza/tree/main/rules)，并按个人使用习惯做了调整：

- [`Chinese Anti-AI Patterns`](instructions/global/agent-behavior.md#chinese-anti-ai-patterns)：源自 Waza 的 [`rules/chinese.md`](https://github.com/tw93/Waza/blob/main/rules/chinese.md)。
- [`English Coaching`](instructions/global/agent-behavior.md#english-coaching)：源自 Waza 的 [`rules/english.md`](https://github.com/tw93/Waza/blob/main/rules/english.md)。
- [`Anti-Patterns: Cross-Skill AI Behavior`](instructions/global/agent-behavior.md#anti-patterns-cross-skill-ai-behavior)：源自 Waza 的 [`rules/anti-patterns.md`](https://github.com/tw93/Waza/blob/main/rules/anti-patterns.md)。

## Scripts

[`scripts/`](scripts/) 下是个人环境安装、WSL 配置和仓库维护三类辅助脚本。

| 脚本 | 运行环境 | 说明 |
| --- | --- | --- |
| [`agent-setup.sh`](scripts/agent-setup.sh) | macOS / Linux | 交互选择 Agent 配置和第三方 skills；支持非交互安装及 `--list` 候选清单 |
| [`agent-install-rule.sh`](scripts/agent-install-rule.sh) | macOS / Linux | 把 `instructions/` 下的单个规则装进 Claude Code 或 Codex，支持全局与项目两级，带 `--remove` 撤销 |
| [`env-setup-wsl.sh`](scripts/env-setup-wsl.sh) | WSL Ubuntu | 装配 Homebrew、Git、lazygit、Starship、uv、Python、nvm、Node.js 和 Codex CLI |
| [`env-update.sh`](scripts/env-update.sh) | macOS / Linux | 依次更新 skills、Codex、Claude Code 和 Homebrew，末尾汇总每个任务的结果 |
| [`statusline.sh`](scripts/statusline.sh) | Claude Code | 状态栏脚本，显示模型与思考等级、目录与 Git 分支、上下文余量、输入输出 token、速率限制和版本 |
| [`list-skills.sh`](scripts/list-skills.sh) | 仓库维护 | 列出仓库内全部 skill 路径，并检查是否有重名 |

### 补充说明

- 无参数运行 `bash scripts/agent-setup.sh` 进入终端菜单：方向键移动、空格勾选、`a` 全选、`n` 取消全选、回车继续、下级选择页面按 `b` 返回上一级、`q` 退出整个流程。主菜单只显示适用的导航按键；安装任务顺序为 Skills、全局指令、Codex CLI、Claude Code CLI、Claude 状态栏。返回后保留勾选与光标位置，同一次运行中复用已获取的 skills 候选。Codex CLI、Claude Code CLI、全局指令、Claude 状态栏可以分别选择；skills 按 Waza、Kami、Matt Pocock 和 HumanLayer 分组选择，安装目标可选 Codex、Claude Code 或两者。安装项目默认不选，执行前展示清单并确认。菜单使用 Bash 内置能力，不依赖额外的 TUI 工具。
- `agent-setup.sh --agent` 从仓库工作区安装两个 CLI、全局指令和状态栏；`--skill` 安装全部候选 skills，保留已有内容；两个参数可以同时使用并保持非交互执行。`--list` 只列出可安装 skills，不执行安装，不能与安装参数组合。Waza 和 Kami 从来源仓库读取候选，Matt Pocock 沿用官网清单，HumanLayer 安装 `show-me`。候选获取失败后继续展示其他来源，同一来源仓库中选中的 skills 合并为一条安装命令，仓库批次失败后继续处理其他仓库，不自动逐项重试；结尾按安装批次汇总结果，有失败时返回非零退出码。无参数且没有终端时会提示使用参数并退出。
- 主菜单提供 `Remove global skills` 和 `Remove global instructions`，两者都先进入 Agent 多选页，默认勾选 Codex 和 Claude Code，支持 `b` 返回、`q` 退出并保留勾选与光标。确认页展示实际范围，输入 `DELETE` 后执行。
- 删除 skills 时，Codex 清理共享的 `~/.agents/skills` 和相关锁文件；Claude 清理 `~/.claude/skills` 中的技能目录和链接。保留 `.system`，删除软链接时不删除其指向的内容。仅选 Claude 时保留共享源和锁文件；仅选 Codex 时保留 Claude 链接，扫描后在确认前用红色列出会受影响的链接。其他 Agent 也可能使用共享目录。实际删除目标先备份到权限为 `0700` 的 `~/.agent-skills-backup-*/skills.tar`，备份失败不删除；日志打印目标、备份路径和 `tar -xf` 恢复命令。
- 删除 instructions 时，只移除所选 Agent 的 `~/.codex/AGENTS.md` 或 `~/.claude/CLAUDE.md` 中安装器管理的 `agent-behavior` 规则块，保留文件中的个人内容与其他规则块。选中 Claude 后额外选择是否清空 `~/.claude/rules`，默认保留；选择清空时包括自定义规则、隐藏文件和子目录，软链接只删除链接本身。现有指令文件与 rules 内容在修改前备份到权限为 `0700` 的 `~/.agent-rules-backup-*`，任何备份失败都不执行移除。日志打印卸载范围、结果和 `cp -p` 或 `tar -xf` 恢复命令；回滚时先停止安装操作，再执行对应恢复命令，保留备份供核对。
- 主菜单的 `Remove all backups` 清理 HOME 直属的安装器备份目录：`.agent-skills-backup-` 或 `.agent-rules-backup-` 加六位字母数字后缀。先列出实际路径，输入 `DELETE` 后只删除确认清单中的目录；跳过软链接、不匹配名称和其他备份文件。日志逐项记录删除结果。清理不会再创建备份，删除后无法使用这些备份回滚；仍需保留的备份应在执行前复制到其他位置。
- 安装器的隔离回归检查使用 Python 3 标准库运行：`python3 scripts/tests/test_agent_setup.py`。检查不安装真实 CLI 或 skills，不修改当前用户配置。
- `agent-install-rule.sh` 将全局 `agent-behavior.md` 分别写入 `~/.claude/CLAUDE.md` 和 `~/.codex/AGENTS.md` 的 `<!-- gwyn-space-skills: <规则>:start -->` 与 `:end` 托管块；项目规则仍使用 Claude Code 的 `.claude/rules/`，Codex 项目规则写入项目 `AGENTS.md` 的托管块。**块内手改会在下次安装时被覆盖**，块外内容不受影响。规则清单由 `instructions/global/*.md` 和 `instructions/project/*.md` 决定，加一个文件就多一条规则；默认范围由所在目录决定，用 `--global` 或 `--project [DIR]` 可以覆盖。两个目录中的规则名不能重复。
- 从 `agent-setup.sh` 早期版本升级时，`~/.claude/CLAUDE.md` 与 `~/.codex/AGENTS.md` 可能是和 `agent-behavior.md` 逐字节相同的整文件副本。`agent-install-rule.sh` 检测到这种副本会报警；加 `--migrate-legacy` 才会先创建 `.pre-rules.bak-<时间戳>` 备份，再改成托管块。旧版 `~/.claude/rules/global.md` 与仓库内容完全相同时会移到 `~/.claude/` 下备份；文件已被修改或是软链接时会停止安装并保留原文件。`agent-setup.sh` 默认带上迁移选项。
- `env-update.sh` 按固定顺序执行更新，前置命令不存在时记为跳过而不是失败，最后打印成功、失败和跳过的清单；带 `-c` 时在 Homebrew 更新后追加 `brew cleanup`。交互终端使用 Bash 和终端控制序列把进度固定在最后一行，上方保留日志和普通确认输入；任务切换时更新底栏，退出或 Ctrl-C 时恢复终端。子程序清屏、全屏交互和运行中缩放窗口可能影响底栏，尺寸在下一次任务边界重新读取。重定向或定时任务保持普通输出。
- `statusline.sh` 由 `agent-setup.sh` 从工作区复制到 `~/.claude/statusline.sh`，其中速率限制一段只在会话上报数据时显示。

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
