# 保留旧版 manage-tools 单文件的配置启动入口

已由 [ADR 0003](0003-launch-manage-tools-config-in-python.md) 替代。

`manage-tools.sh` 可以作为单文件安装，旧副本会从 GitHub main 下载同一份配置代码和资源，并调用归档里的 `scripts/manage-tools/main.sh`。保留该路径和调用参数，让旧副本可以进入新版配置，也让用户继续通过单文件脚本运行无参数更新。

TUI 的主入口是 `scripts/manage-tools/main.py`。在完整仓库中无参数调用时，它直接使用当前检出的配置代码和资源，并检查 Python 版本和终端运行环境。`main.sh` 负责从 Bash 启动 `main.py` 并传递配置来源。这样，后续移植 TUI 时可以从 Python 入口开始，旧版单文件启动器仍可使用归档。

回退配置实现时，从改动前的完整仓库运行 `scripts/manage-tools.sh config`，让启动器、模块与规则资源来自同一版本。
