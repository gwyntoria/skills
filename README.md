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
| [`changelog`](skills/work/changelog/SKILL.md) | 按 Keep a Changelog 规范编写、更新或审核版本记录 | 有证据支撑的版本条目或分级审核结果 |

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
使用 $changelog 根据 v1.2.0 到 HEAD 的变化更新 Unreleased，并审核现有条目。
```

```text
使用 $review-chinese-writing 审读这篇稿子，先判断是否合格，再给修改建议。
```

### 补充说明

- `hecaitou` 与 `wangshuo` 使用 [dot-skill](https://github.com/titanwings/colleague-skill) 从公开材料中提炼的写作和分析方法。输出具有一定启发性，但与本人仍有不少差别，感兴趣的可以阅读他们的文章，再用相同的话题提问 AI。
- `scan-codebase` 所执行的内容来自 [The Git Commands I Run Before Reading Any Code](https://piechowski.io/post/git-commands-before-reading-code/) 中提到的 git 命令，适合接手新代码库时运行，了解仓库现状。

## Instructions

| 文件 | 使用范围 | 说明 |
| --- | --- | --- |
| [`global.md`](instructions/global.md) | 全局 | 可放在 Agent 的配置目录中，如 `~/.codex/`、`~/.claude/` |
| [`c-project.md`](instructions/c-project.md) | 项目 | C/C++ 项目的格式、命名、注释和提交信息约定 |
| [`writing.md`](instructions/writing.md) | 项目 | Markdown 写作仓库的资源路径、引用方式和格式检查规则 |
| [`chinese-punctuation.md`](instructions/chinese-punctuation.md) | 项目 | 终端回复的中文半角标点、空格规则和适用范围 |

这些 instruction 是可复用的规则片段。使用时应根据目标 Agent 的配置方式，选择适用文件并合并到项目指令中。

### 补充说明

[`global.md`](instructions/global.md) 中的以下规则来源于 [Waza 项目的 `rules` 目录](https://github.com/tw93/Waza/tree/main/rules)，并按个人使用习惯做了调整：

- [`Chinese Anti-AI Patterns`](instructions/global.md#chinese-anti-ai-patterns)：源自 Waza 的 [`rules/chinese.md`](https://github.com/tw93/Waza/blob/main/rules/chinese.md)。
- [`English Coaching`](instructions/global.md#english-coaching)：源自 Waza 的 [`rules/english.md`](https://github.com/tw93/Waza/blob/main/rules/english.md)。
- [`Anti-Patterns: Cross-Skill AI Behavior`](instructions/global.md#anti-patterns-cross-skill-ai-behavior)：源自 Waza 的 [`rules/anti-patterns.md`](https://github.com/tw93/Waza/blob/main/rules/anti-patterns.md)。

## Scripts

[`scripts/`](scripts/) 下是个人环境安装、WSL 配置和仓库维护三类辅助脚本。

| 脚本 | 运行环境 | 说明 |
| --- | --- | --- |
| [`config_agent.sh`](scripts/config_agent.sh) | macOS / Linux | 安装 Codex CLI、Claude Code 和 Pi，写入全局指令，安装状态栏、Pi 扩展和第三方 skills，并清理已有的全局 skills |
| [`toria-up.sh`](scripts/toria-up.sh) | macOS / Linux | 依次更新 skills、Codex、Claude Code、Homebrew 和 Pi，末尾汇总每个任务的结果 |
| [`statusline.sh`](scripts/statusline.sh) | Claude Code | 状态栏脚本，显示模型与思考等级、目录与 Git 分支、上下文余量、输入输出 token、速率限制和版本 |
| [`wsl_setup.sh`](scripts/wsl_setup.sh) | WSL Ubuntu | 装配 Homebrew、Git、lazygit、Starship、uv、Python、nvm、Node.js 和 Codex CLI |
| [`wsl_uninstall.sh`](scripts/wsl_uninstall.sh) | WSL Ubuntu | 撤销 `wsl_setup.sh` 写入的用户级工具和 `~/.bashrc` 配置 |
| [`list-skills.sh`](scripts/list-skills.sh) | 仓库维护 | 列出仓库内全部 skill 路径，并检查是否有重名 |
| [`link-skills.sh`](scripts/link-skills.sh) | 仓库维护 | 把仓库内的 skill 软链到 `~/.agents/skills`，可指定 skill 或目录，也可移除和清理 |

### 补充说明

- `config_agent.sh` 面向个人环境，会覆盖 `~/.codex/AGENTS.md` 和 `~/.claude/CLAUDE.md`，并先删除 `~/.agents/skills` 和 `~/.claude/skills` 下的已有内容，再按脚本内的清单重新安装。运行前确认这些位置没有需要保留的内容。
- `toria-up.sh` 按固定顺序执行更新，前置命令不存在时记为跳过而不是失败，最后打印成功、失败和跳过的清单；带 `-c` 时在 Homebrew 更新后追加 `brew cleanup`。
- `statusline.sh` 由 `config_agent.sh` 从仓库的 raw 地址拉取并安装到 `~/.claude/statusline.sh`，其中速率限制一段只在会话上报数据时显示。
- `link-skills.sh` 只处理指向本仓库的软链，遇到真实目录或指向别处的软链会跳过并报告，重复运行不会产生重复条目。
- `wsl_uninstall.sh` 默认保留 apt 安装的系统包，需要一并删除时设置 `REMOVE_APT_PACKAGES=1`。

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
