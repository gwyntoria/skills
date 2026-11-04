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

- `hecaitou` 与 `wangshuo` 使用 [distilly](https://github.com/titanwings/distilly) 从公开材料中提炼的写作和分析方法。输出具有一定启发性，但与本人仍有不少差别，感兴趣的可以阅读他们的文章，再用相同的话题提问 AI。
- `scan-codebase` 所执行的内容来自 [The Git Commands I Run Before Reading Any Code](https://piechowski.io/post/git-commands-before-reading-code/) 中提到的 git 命令，适合接手新代码库时运行，了解仓库现状。

## Rules

本仓库规则位于 `rules/project/`；安装器还会动态获取 [Waza 的规则](https://github.com/tw93/Waza/tree/main/rules)。来源与安装范围独立。

| 文件 | 使用范围 | 说明 |
| --- | --- | --- |
| [`c-project.md`](rules/project/c-project.md) | 项目 | C/C++ 项目的格式、命名、注释和提交信息约定 |
| [`writing-repo.md`](rules/project/writing-repo.md) | 项目 | Markdown 写作仓库的资源路径、引用方式和格式检查规则 |
| [`chinese-punctuation.md`](rules/project/chinese-punctuation.md) | 项目 | 终端回复的中文半角标点、空格规则和适用范围 |

规则通过 [`scripts/agent-setup.sh`](scripts/agent-setup.sh) 的交互菜单安装：选择 `Install / Update` → `Rules`，依次多选规则、多选目标 Agent、选择 Global 或 Project 范围，再确认安装。Agent 默认全选，规则默认不选；选择页支持 `b` 返回、`q` 退出，并保留勾选与光标。确认页展示资源来源和完整安装路径。规则页按 Waza 和本仓库来源分组列出规则，允许跨范围安装；所选规则统一安装到最后选择的范围，确认页保留原始来源。

```bash
# 在仓库中打开菜单，可安装规则或安装本地命令
bash scripts/agent-setup.sh

# 在菜单选择 Install / Update this command 后，在任意项目运行
cd /path/to/project
agent-setup
```

Matt skills 的安装菜单默认全选。勾选技能会递归补齐依赖，并标明自动补齐的原因；取消依赖会连带取消上层技能，清理不再需要的自动补齐项，保留手动选择项和仍被共用的依赖。“全选”将全部项视为手动选择，“全不选”清空选择。依赖表随脚本维护，包含技能明确调用的条件分支，排除工作流推荐和项目配置前置条件；网页名单缺少必要依赖时，阻止选择受影响的技能并提示原因。卸载菜单保持独立选择。

Project 规则安装到启动命令时的当前目录，包括 Git 子目录和非 Git 目录，不自动寻找仓库根目录。先确认当前路径，再在确认页执行安装。

资源相对脚本实际位置查找，符号链接会解析到真实脚本。`rules/project/` 和 `scripts/statusline.sh` 分别优先使用本地内容；缺少某个目录或文件时，从 GitHub `gwyntoria/skills` 的 `main` 分支下载临时资源，同一次运行复用，退出清理。本地规则目录不会混入远端规则，格式错误直接报告；远端获取失败不覆盖配置。改了本地 `rules/` 后重新安装即可更新。

`Install / Update this command` 将命令安装到 `~/.local/bin/agent-setup`。实际脚本位于 `scripts/agent-setup.sh` 且仓库根目录存在 `rules/` 时，安装当前版本；从独立位置运行时，下载 GitHub `main` 最新脚本。安装文件通过 `bash -n` 后原子替换，下载或检查失败保留旧命令，下次启动生效。PATH 缺少 `~/.local/bin` 时仅打印配置方法，不修改 shell 配置。需要 Bash；远端获取需要 cURL，本仓库归档资源还需要 tar，Waza 目录解析需要 Node.js（可复用现有 nvm 引导）；保留原有 CLI 和 skills 安装任务所需的 Node.js、npx 等依赖。

Waza 规则每次启动后首次进入规则页时，通过 GitHub API 固定 `main` 的提交并读取目录；确认安装后仅从 raw 下载所选规则，始终使用该提交，退出清理临时文件。默认不勾选；安装标识使用 `waza-<规则名>`，支持上游的 H1 和 H2 标题。获取失败可重试、返回或跳过 Waza。再次安装只更新所选项，不卸载未选规则；旧 `agent-behavior` 不再提供，也不会自动清理已安装内容。

安装时按目标格式化所选规则的标题：Codex 全局 `~/.codex/AGENTS.md` 顶部使用 `# Global Rules`，各规则标题统一为二级标题；Claude 独立规则文件的标题统一为一级标题。子标题随规则标题调整层级，最深为六级，代码块和其他正文保持原样。Codex 项目范围保留现有标题行为。重复安装不重复添加总标题，卸载规则后保留总标题；未选中的已有规则及用户自有内容保持原样，统一已有规则需要重新选择安装。

`--agent` 在有终端时进入 Agent 多选和安装确认；无终端时安装全部三个 CLI 及其附带组件。Agent 默认全选 Codex、Claude Code、Pi；Claude Code 附带 statusline，Pi 附带 `npm:pi-web-access`、`npm:pi-subagents`、`npm:pi-powerline-footer`。交互安装的任务页按 Skills、Rules、Agent 分组，Rules 和 Skills 保持独立选择。与 `--skill` 同用时，有终端进入技能选择，无终端保持安装全部已配置技能的行为。

## Scripts

[`scripts/`](scripts/) 下是个人环境安装、WSL 配置和仓库维护三类辅助脚本。

| 脚本 | 运行环境 | 说明 |
| --- | --- | --- |
| [`agent-setup.sh`](scripts/agent-setup.sh) | macOS / Linux | 统一交互安装全局或项目 rules、Agent 配置和第三方 skills；支持安装本地命令、非交互安装及 `--list` 候选清单 |
| [`env-setup-wsl.sh`](scripts/env-setup-wsl.sh) | WSL Ubuntu | 通过中文 TUI 选择基础包、开发环境与 AI 工具，选择 Fish/Zsh/Bash（默认 Fish）、准备启动配置并切换默认 shell |
| [`env-update.sh`](scripts/env-update.sh) | macOS / Linux | 依次更新 skills、Codex、Claude Code 和 Homebrew，末尾汇总每个任务的结果 |
| [`statusline.sh`](scripts/statusline.sh) | Claude Code | 状态栏脚本，显示模型与思考等级、目录与 Git 分支、上下文余量、输入输出 token、速率限制和版本 |
| [`list-skills.sh`](scripts/list-skills.sh) | 仓库维护 | 列出仓库内全部 skill 路径，并检查是否有重名 |

## Skills 安装

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
