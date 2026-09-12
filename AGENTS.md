# Project Agent Instructions

## Markdown File Format

After finishing edits to a Markdown file, format only the files that was changed with `markdownlint-cli2`, then run `textlint` to apply typography fixes and terminology replacements.

```bash
npx markdownlint-cli2 --fix --no-globs path/to/file.md
npx textlint --fix path/to/file.md
```

Avoid running broad auto-fix commands unless the task is specifically to clean up formatting across the repository.

## Folder Structure

Skill source documents are organized into bucket folders under `skills/` and are used by the `npx skills` and Claude marketplace installation paths. Codex requires skill directories directly under `plugins/gwyn-space-skills/skills/`, so its synchronized copies remain flat.

When changing a skill under the root `skills/` directory, apply the same content change to the directory with the same skill name under `plugins/gwyn-space-skills/skills/`.

Agent instructions are under `./instructions`.

## Chinese Punctuation

### 适用范围

只作用于终端里的对话回复。写进文件或对外发布的中文内容保持默认的中文全角标点：

- Markdown 文档、README、代码注释
- issue 和 PR 评论
- 提交信息

### 半角标点

终端回复里的标点使用半角英文符号：

| 名称 | 中文 | 英文 |
| --- | --- | --- |
| 逗号 | `，` | `,` |
| 顿号 | `、` | `,` |
| 句号 | `。` | `.` |
| 冒号 | `：` | `:` |
| 分号 | `；` | `;` |
| 问号 | `？` | `?` |
| 感叹号 | `！` | `!` |
| 引号 | `“ ”` | `"` |

括号、书名号、破折号、省略号等其他标点保持中文全角。

### 空格

半角标点不带全角标点的留白，标点后补一个空格，标点前不加。句末标点后面不补空格，引号前后各留一个空格。

终端回复示例：

- `第一次运行需要初始化配置, 之后再改选项.`
- `支持快速, 标准, 严格三种模式: 默认是标准.`
- `失败了吗? 先看日志.`

### 例外

终端回复里出现代码、命令、路径、URL、版本号和文件名时，符号保持原样，不要为了补空格去改它们。引用别人的原文也不动。

## Agent skills

### Issue tracker

Issues and PRDs are tracked in this repo's GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the five default canonical labels. See `docs/agents/triage-labels.md`.

### Domain docs

Domain documentation uses the single-context layout. See `docs/agents/domain.md`.
