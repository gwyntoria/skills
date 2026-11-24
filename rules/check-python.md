# Python 文件检查

新增或修改 Python 文件后，在任务结束前对每个改动的文件运行 Ruff。优先使用项目已声明的 Ruff 版本、运行方式和配置。以下命令中的路径换成实际改动的文件。

```bash
ruff check --fix path/to/script.py
ruff format path/to/script.py
```

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

项目没有 Ruff 配置时，检查可用默认设置运行。需要固定项目设置时，建议在项目根目录新增 `ruff.toml`。下面以最低支持 Python 3.10 为例。若项目使用 `pyproject.toml` 管理 Ruff，就把对应设置加到 `[tool.ruff]` 和 `[tool.ruff.lint]`。 [Ruff 配置文档](https://docs.astral.sh/ruff/configuration/)

```toml
target-version = "py310"
fix = true

[lint]
select = ["E4", "E7", "E9", "F"]
```
