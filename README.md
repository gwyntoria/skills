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

这些 instruction 是可复用的规则片段，可以用 [`scripts/setup-rule.sh`](scripts/setup-rule.sh) 安装。脚本直接读取工作区里的 `instructions/`，不依赖网络，但因此**需要先 clone 本仓库**，再从仓库里运行:

```bash
git clone https://github.com/gwyntoria/skills.git
cd skills

# 全局。Claude Code 写 ~/.claude/rules/，Codex 写 ~/.codex/AGENTS.md 里的托管块
scripts/setup-rule.sh global --target both --global

# 项目级。写进当前仓库的 .claude/rules/ 和 AGENTS.md
scripts/setup-rule.sh writing --target both

# 查看安装状态，或撤销
scripts/setup-rule.sh --list
scripts/setup-rule.sh global --remove
```

改了 `instructions/` 下的文件后重新运行即可生效，不需要发版或切 ref。

### 补充说明

[`global.md`](instructions/global.md) 中的以下规则来源于 [Waza 项目的 `rules` 目录](https://github.com/tw93/Waza/tree/main/rules)，并按个人使用习惯做了调整：

- [`Chinese Anti-AI Patterns`](instructions/global.md#chinese-anti-ai-patterns)：源自 Waza 的 [`rules/chinese.md`](https://github.com/tw93/Waza/blob/main/rules/chinese.md)。
- [`English Coaching`](instructions/global.md#english-coaching)：源自 Waza 的 [`rules/english.md`](https://github.com/tw93/Waza/blob/main/rules/english.md)。
- [`Anti-Patterns: Cross-Skill AI Behavior`](instructions/global.md#anti-patterns-cross-skill-ai-behavior)：源自 Waza 的 [`rules/anti-patterns.md`](https://github.com/tw93/Waza/blob/main/rules/anti-patterns.md)。

## Scripts

[`scripts/`](scripts/) 下是个人环境安装、WSL 配置和仓库维护三类辅助脚本。

| 脚本 | 运行环境 | 说明 |
| --- | --- | --- |
| [`config_agent.sh`](scripts/config_agent.sh) | macOS / Linux | 按参数安装 Agent 配置或第三方 skills；`--agent` 安装 CLI、全局指令和状态栏，`--skill` 清理并重装全局 skills |
| [`setup-rule.sh`](scripts/setup-rule.sh) | macOS / Linux | 把 `instructions/` 下的单个规则装进 Claude Code 或 Codex，支持全局与项目两级，带 `--remove` 撤销 |
| [`toria-up.sh`](scripts/toria-up.sh) | macOS / Linux | 依次更新 skills、Codex、Claude Code 和 Homebrew，末尾汇总每个任务的结果 |
| [`statusline.sh`](scripts/statusline.sh) | Claude Code | 状态栏脚本，显示模型与思考等级、目录与 Git 分支、上下文余量、输入输出 token、速率限制和版本 |
| [`wsl_setup.sh`](scripts/wsl_setup.sh) | WSL Ubuntu | 装配 Homebrew、Git、lazygit、Starship、uv、Python、nvm、Node.js 和 Codex CLI，带 `--uninstall` 撤销上述改动 |
| [`list-skills.sh`](scripts/list-skills.sh) | 仓库维护 | 列出仓库内全部 skill 路径，并检查是否有重名 |
| [`link-skills.sh`](scripts/link-skills.sh) | 仓库维护 | 把仓库内的 skill 软链到 `~/.agents/skills`，可指定 skill 或目录，也可移除和清理 |

### 补充说明

- `config_agent.sh --agent` 需要从 clone 出来的仓库里运行，会安装 Codex CLI 和 Claude Code，通过 `setup-rule.sh` 安装全局指令，并从工作区安装 Claude Code 状态栏。`config_agent.sh --skill` 会先删除 `~/.agents/skills` 和 `~/.claude/skills` 下的已有内容，再按脚本内的清单重新安装；两个参数可以同时使用。运行前确认这些位置没有需要保留的内容。
- `setup-rule.sh` 的两个 Agent 机制不同，所以安装方式也不同: Claude Code 原生读取 `.claude/rules/` 下的规则，装的是独立文件；Codex 只有 `AGENTS.md`，装的是 `<!-- gwyn-space-skills: <规则>:start -->` 与 `:end` 之间的托管块。**块内手改会在下次安装时被覆盖**，块外内容不受影响。规则清单由 `instructions/*.md` 决定，加一个文件就多一条规则；默认范围只有 `global.md` 是全局，其余按项目处理，用 `--global` 可以覆盖。
- 从 `config_agent.sh` 早期版本升级时，`~/.claude/CLAUDE.md` 与 `~/.codex/AGENTS.md` 里各有一份和 `global.md` 逐字节相同的旧副本，装上规则后同一份内容会加载两遍。`setup-rule.sh` 检测到这种副本会报警；加 `--migrate-legacy` 才会改名成 `.legacy-<时间戳>` 备份，从不删除。`config_agent.sh` 默认带上这个选项。
- `toria-up.sh` 按固定顺序执行更新，前置命令不存在时记为跳过而不是失败，最后打印成功、失败和跳过的清单；带 `-c` 时在 Homebrew 更新后追加 `brew cleanup`。
- `statusline.sh` 由 `config_agent.sh` 从工作区复制到 `~/.claude/statusline.sh`，其中速率限制一段只在会话上报数据时显示。
- `link-skills.sh` 只处理指向本仓库的软链，遇到真实目录或指向别处的软链会跳过并报告，重复运行不会产生重复条目。
- `wsl_setup.sh --uninstall` 保留 Codex CLI 和 apt 安装的系统包，需要一并删除 apt 包时设置 `REMOVE_APT_PACKAGES=1`，确认提示可以用 `ASSUME_YES=1` 跳过。

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
