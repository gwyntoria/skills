# Python 文件检查

新增或修改 Python 文件后，在任务结束前对每个改动的文件运行 Ruff。沿用项目已声明的 Ruff 版本和运行方式。以下命令中的路径换成实际改动的文件。

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

## 检查结果

两条命令都会写回改动文件。即使 `ruff check --fix` 报告仍有问题，也要执行 `ruff format`。核对自动修复和格式化产生的差异，处理本次改动引入的剩余问题后，再运行这两条命令。

## Ruff 缺失时

先确认项目的开发环境是否已经提供 Ruff，例如 `uv run ruff --version`。仍不可用时，告知用户哪些检查未运行，并按其环境提供安装命令。已安装 uv 或 pipx 时，任选一种。 [Ruff 安装文档](https://docs.astral.sh/ruff/installation/)

```bash
uv tool install ruff
```

```bash
pipx install ruff
```

已有启用的项目虚拟环境时，也可以在该环境中执行 `python -m pip install ruff`。
