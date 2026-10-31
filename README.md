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

Matt skills 的安装菜单默认全选。勾选技能会递归补齐依赖，并标明自动补齐的原因；取消依赖会连带取消上层技能，清理不再需要的自动补齐项，保留手动选择项和仍被共用的依赖。“全选”将全部项视为手动选择，“全不选”清空选择。依赖表随脚本维护，包含技能明确调用的条件分支，排除工作流推荐和项目配置前置条件；网页名单缺少必要依赖时，阻止选择受影响的技能并提示原因。卸载菜单保持独立选择。

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
| [`env-setup-wsl.sh`](scripts/env-setup-wsl.sh) | WSL Ubuntu | 通过中文 TUI 选择基础包、开发环境与 AI 工具，准备 Bash 配置并切换默认 shell |
| [`env-update.sh`](scripts/env-update.sh) | macOS / Linux | 依次更新 skills、Codex、Claude Code 和 Homebrew，末尾汇总每个任务的结果 |
| [`statusline.sh`](scripts/statusline.sh) | Claude Code | 状态栏脚本，显示模型与思考等级、目录与 Git 分支、上下文余量、输入输出 token、速率限制和版本 |
| [`list-skills.sh`](scripts/list-skills.sh) | 仓库维护 | 列出仓库内全部 skill 路径，并检查是否有重名 |

### WSL 环境配置

在 WSL Ubuntu 的交互终端中运行：

```bash
bash scripts/env-setup-wsl.sh
```

当前 Bash 向导提供系统基础包、Homebrew/eza、lazygit、uv/Python、nvm/Node.js、Codex CLI、Claude Code、Agent/Skill 配置，默认全选。
方向键移动、空格勾选、回车进入计划确认，`q` 取消；`>` 标记当前焦点。列表与计划区分手动选择和自动补齐：缺失的安装依赖会自动选中系统基础包，共享依赖保留到所有请求都取消；取消依赖会连带取消需要它的组件并显示提示。已有程序按需复用，未选中的工具不会卸载。
确认前会显示配置路径、原默认 shell、完整包清单与版本。确认后仅补装缺失包，准备 Bash 启动配置，并在流程末尾将 Bash 设置为账号默认 shell。
Zsh、插件与 Starship 的选择将在后续任务接入，已有安装函数保留。

选择 Agent/Skill 会自动补齐两个 CLI 和 nvm/Node.js；取消其中一个依赖会连带取消 Agent/Skill，移除 Agent/Skill 后仍保留手动选择的依赖。
Codex CLI 和 Claude Code 优先复用已有命令，缺失时使用各自的[原生 Codex 安装器](https://chatgpt.com/codex/install.sh)和[原生 Claude 安装器](https://claude.ai/install.sh)，安装或复用后执行版本检查。
原生安装进程使用目标 `SHELL=/bin/bash`，提前将 `~/.local/bin` 加入 PATH，并将 Codex 安装目录固定到该路径；启动 PATH 由向导托管，避免沿用旧默认 shell 的配置目标。

Agent/Skill 在所选 Node.js 环境中执行 `bash scripts/agent-setup.sh --agent --skill`，沿用全局规则、Claude 状态栏以及 Waza、Kami、Matt Pocock、HumanLayer、Gwyntoria、Distilly 六个技能源的发现机制，技能名称和数量由组合入口动态读取。
组合入口的原始日志直接显示，真实退出码决定成功或失败；CLI、Node.js 或下载依赖失败时跳过 Agent/Skill，汇总给出重试命令。CLI 或技能失败仍继续独立步骤和符合条件的默认 shell 切换。

Homebrew/eza 保留 shellenv 和 `ls`、`la` 别名。lazygit 优先复用，其次尝试 apt，失败则使用计划列出的 Homebrew 后备路径；按需安装的 Homebrew 依赖单独报告，不会因此安装 eza 或添加文件列表别名。
uv/Python 默认使用 Python `3.14`，nvm/Node.js 默认使用 `lts/*`，可以通过环境变量指定请求版本。Node.js 安装或复用后验证可用，再设为 nvm 默认版本，供新终端加载：

```bash
PYTHON_VERSION=3.13 NODE_VERSION=22 bash scripts/env-setup-wsl.sh
```

保留 `~/.local/bin`、`toria-update` 和 Bash 大小写不敏感补全。第三方安装器不负责写启动配置：[uv 设置 `UV_NO_MODIFY_PATH=1`](https://docs.astral.sh/uv/reference/installer/)，[nvm 设置 `PROFILE=/dev/null`](https://github.com/nvm-sh/nvm/blob/v0.40.6/install.sh)；[Homebrew 安装器](https://github.com/Homebrew/install/blob/HEAD/install.sh)只打印配置建议。
工具安装并检查可用后才在 Bash 托管块中添加初始化。失败时保留已有配置，不新增失败组件初始化；重复运行保留用户内容、符号链接和权限。失败后的重试命令包含请求版本。

基础包新增 `shellcheck` 和 `7zip`，保留 `unzip`；不再安装 `tree`、`gcc-arm-none-eabi` 和 `zip`，已有软件不会被卸载。
安装器会检查目标软件源是否提供 `7zip`，并检查 `7zz` 或 `7z` 命令是否可用。

步骤失败后继续独立步骤，依赖失败则跳过，末尾显示各项结果及手动处理命令；有失败时退出码为 `1`。
只有 Bash 和启动配置准备成功才切换默认 shell，切换后回读账号记录并提示重新打开终端。其他组件失败不阻止符合条件的切换。

只修改 Bash 启动配置，保留 Zsh 配置、配置符号链接和文件权限。已有文件有实际变化时，先在目标文件所在目录保存备份并打印恢复命令；异常托管块、配置语法错误或与 Zsh 共用同一配置文件时，会阻止修改和切换。
汇总保留原默认 shell 及恢复命令；软件包安装不提供全局回滚。

使用 `NO_COLOR=1 bash scripts/env-setup-wsl.sh` 禁用颜色；没有颜色能力的终端也会使用文字状态。
`bash scripts/env-setup-wsl.sh --help` 无需交互终端，安装不提供无人值守参数。

隔离回归测试使用临时 HOME、PATH 命令替身和 PTY，并将脚本副本中的固定 Homebrew 外部路径替换为临时目录，避免调用本机 Homebrew。Agent/Skill 组合入口也使用替身，核对传参、原始日志和退出结果，不安装远程技能。测试不安装软件或更改当前账号：

```bash
python3 -m unittest discover -s scripts/tests -p 'test_env_setup_wsl.py'
bash -n scripts/env-setup-wsl.sh
shellcheck -S warning scripts/env-setup-wsl.sh
```

真实 WSL 安装、新终端启动和默认 shell 生效情况需要另外验收。

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
