# Gwyn Space Skills

![Gwyn Space Skills](assets/readme-hero.png)

## Skills

### dialog

写作与分析方法。

| Skill | 适用场景 | 主要输出 |
| --- | --- | --- |
| [`hecaitou`](skills/dialog/hecaitou/SKILL.md) | 从日常观察切入，分析平台、产品、关系与个人边界 | 带有具体场景、机制分析和边界意识的中文长文 |
| [`wangshuo`](skills/dialog/wangshuo/SKILL.md) | 分析组织、市场、公共议题和个人重大选择等复杂问题 | 证据分级、激励与博弈分析、有限判断和行动条件 |

### work

报告与工程类技能。

| Skill | 适用场景 | 主要输出 |
| --- | --- | --- |
| [`daily-weekly-reporting`](skills/work/daily-weekly-reporting/SKILL.md) | 根据 Git 记录编写中文日报、周报或工作总结 | 区分已提交成果、未提交进展和待验证事项的工作报告 |
| [`maintain-changelog`](skills/work/maintain-changelog/SKILL.md) | 按 Keep a Changelog 规范编写、更新或审核版本记录 | 有证据支撑的版本条目或分级审核结果 |
| [`scan-codebase`](skills/work/scan-codebase/SKILL.md) | 阅读实现代码前，先从 Git 历史判断仓库阶段与风险区域 | 当前阶段判断、风险地图和代码阅读顺序 |
| [`how`](skills/work/how/SKILL.md) | 理解代码如何运作、模块归属和架构分层 | 代码运行流程、关键概念、文件地图和注意事项 |
| [`why`](skills/work/why/SKILL.md) | 追查代码设计动机、历史决策和取舍 | 带来源引用和置信度分级的调查结果，区分证据、推断和未知 |

### writing

中文写作审读技能。

| Skill | 适用场景 | 主要输出 |
| --- | --- | --- |
| [`review-chinese-writing`](skills/writing/review-chinese-writing/SKILL.md) | 审读面向普通读者的中文非虚构稿件，判断能否发布 | 两阶段评审报告：合格判定、必须修改项和按收益排序的提升建议 |

<details>
<summary>使用示例</summary>

在支持 Skills 的 Agent 中，可以直调用：

```text
$wangshuo 分析这个决策，区分事实、推论、风险和未知
```

```text
$hecaitou 把这上述的日常小事写成一篇中文随笔
```

```text
$scan-codebase
```

```text
$how 解释这个子系统的入口、数据流和模块分工
```

```text
$why 这个超时阈值被设为当前值？
```

```text
$daily-weekly-reporting 日报/周报
```

```text
根据 v1.2.0 到 当前的修改 $maintain-changelog
```

```text
$review-chinese-writing 审查刚才编辑的文章
```

</details>

### Skills 安装

#### npx skills

安装前需要本地已有 Node.js 与 npm。运行下面的命令，从仓库中选择需要的 skill 和目标 Agent：

```bash
npx skills add gwyntoria/skills -g -y
```

也可以直接安装指定的 skill：

```bash
npx skills add gwyntoria/skills -g --skill scan-codebase
```

#### Claude Code marketplace

添加 marketplace 并安装插件：

```bash
claude plugin marketplace add gwyntoria/skills
claude plugin install gwyn-space-skills-work@gwyn-space
claude plugin install gwyn-space-skills-dialog@gwyn-space
claude plugin install gwyn-space-skills-writing@gwyn-space
```

安装或更新插件后，新建会话以加载最新的 skill。

> 使用 Claude Code 的插件形式，单纯是为了在 npx skills 安装的时候能提供分类信息。

### 补充说明

- `hecaitou` 与 `wangshuo` 是使用 [distilly](https://github.com/titanwings/distilly) 从公开材料中提炼的写作和分析方法。输出具有一定启发性，但与本人仍有不少差别，感兴趣的可以阅读他们的文章，再用相同的话题提问 AI。
- `maintain-changelog` 参考 [keep a changelog](https://keepachangelog.com/en/1.1.0/) 中的编写规则。
- `scan-codebase` 参考 [The Git Commands I Run Before Reading Any Code](https://piechowski.io/post/git-commands-before-reading-code/) 中提到的 git 命令，适合接手新代码库时运行，了解仓库现状。
- `how` 与 `why` 参考 [poteto](https://x.com/poteto) 为 Cursor 创建的 [pstack](https://github.com/cursor/plugins/tree/main/pstack) 中的 `how` 与 `why`。

## Rules

| 文件 | 说明 |
| --- | --- |
| [`chinese-punctuation.md`](rules/chinese-punctuation.md) | 终端回复的中文半角标点、空格规则和适用范围 |
| [`code-comments.md`](rules/code-comments.md) | 跨语言的接口契约、数据含义、流程与分支注释规则 |
| [`writing-repo.md`](rules/writing-repo.md) | Markdown 写作仓库的资源路径、引用方式和格式检查规则 |

> 规则可通过 [`scripts/setup-agents.sh`](scripts/setup-agents.sh) 的交互菜单安装和卸载。安装器还会动态获取 [Waza 的规则](https://github.com/tw93/Waza/tree/main/rules)。

## Scripts

[`scripts/`](scripts/) 下是个人环境安装、Ubuntu 配置和仓库维护三类辅助脚本。

| 脚本 | 运行环境 | 说明 |
| --- | --- | --- |
| [`setup-agents.sh`](scripts/setup-agents.sh) | macOS / Linux | 统一交互安装全局或项目 rules、Agent 配置和第三方 skills；支持安装本地命令、非交互安装及本地已安装清单与远程可安装目录 |
| [`setup-ubuntu.sh`](scripts/setup-ubuntu.sh) | Ubuntu（原生 / WSL） | 通过中文 TUI 选择基础包、开发环境与 AI 工具，选择 Fish/Zsh/Bash（默认 Fish）、准备启动配置并切换默认 shell |
| [`update-tools.sh`](scripts/update-tools.sh) | macOS / Linux | 依次更新 Skills、Agents 和 Homebrew（使用 `brew upgrade --no-ask` 自动确认）；Agents 默认仅更新 Codex 及其插件市场，传入 `--all` 才加入 Claude（含插件市场和插件）、Pi（含扩展）及 Hermes；末尾汇总结果 |
| [`list-skills.sh`](scripts/list-skills.sh) | 仓库维护 | 列出仓库内全部 skill 路径，并检查是否有重名 |
| [`statusline.sh`](scripts/statusline.sh) | Claude Code | 状态栏脚本，显示模型与思考等级、目录与 Git 分支、上下文余量、输入输出 token、速率限制和版本 |

Ubuntu 安装器面向仍受常规安全维护的 Ubuntu Desktop、Server（含 SSH）和 WSL Ubuntu，支持 amd64/arm64，需以有 sudo 权限的普通用户运行；不支持 root、容器和无人值守安装。Windows Terminal 目录同步仅在 WSL 下配置。第三方组件与软件包仍取决于当前架构、版本及已启用的软件源，不自动开启软件源；失败项会给出手动处理提示。

可在交互终端执行如下命令打开 Agent 和 Ubuntu 配置菜单：

```bash
curl -fsSL https://raw.githubusercontent.com/gwyntoria/skills/refs/heads/main/scripts/setup-agents.sh | bash
```

```bash
curl -fsSL https://raw.githubusercontent.com/gwyntoria/skills/refs/heads/main/scripts/setup-ubuntu.sh | bash
```
