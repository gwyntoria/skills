# Python 文件检查

新增或修改 Python 文件后，在任务结束前对每个改动的文件依次运行 `ruff check --fix` 和 `ruff format`。

下述命令中的路径换成实际改动的文件。

## 项目有 Ruff 配置

若改动文件适用项目的 `ruff.toml`、`.ruff.toml` 或带 `[tool.ruff]` 的 `pyproject.toml`，让 Ruff 加载项目配置。项目已指定配置路径时，沿用该路径。

```bash
ruff check --fix path/to/script.py
ruff format path/to/script.py
```

## Ruff 可用且项目无 Ruff 配置

从项目根目录运行以下命令。`--isolated` 关闭配置文件加载，所需设置由命令传入。

```bash
ruff check --isolated --fix --target-version py310 --line-length 80 \
    --select E,F,W,C90,I --ignore E501,W191 \
    --config 'src = ["scripts/manage-tools/agents", "scripts/manage-tools/content"]' \
    --config 'lint.isort.combine-as-imports = true' \
    --config 'lint.isort.length-sort = true' \
    --config 'lint.isort.lines-after-imports = 2' \
    path/to/script.py

ruff format --isolated --target-version py310 --line-length 80 \
    --config 'format.docstring-code-format = true' \
    --config 'format.line-ending = "lf"' \
    path/to/script.py
```

## Ruff 缺失时

根据系统提示用户安装 Ruff：

| 系统 | 安装命令 |
| -- | -- |
| Windows | `winget install --id astral-sh.ruff -e` |
| Mac | `brew install ruff` |
| Linux | `curl -LsSf <https://astral.sh/ruff/install.sh> \| sh` |
