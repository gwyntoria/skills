# 保留旧版 manage-tools 单文件的配置启动入口

`manage-tools.sh` 可以作为单文件安装，旧副本会从 GitHub main 下载同一份配置代码和资源，并调用归档里的 `scripts/manage-tools/main.sh`。配置流程和后端迁入 Python 后，保留该路径和调用参数，由 Bash 检查 Python 运行环境并交接给 curses 程序。这样旧副本可以进入新版配置，用户仍可单独使用本地脚本运行无参数更新。

回退配置实现时，从改动前的完整仓库运行 `scripts/manage-tools.sh config`，让启动器、模块与规则资源来自同一版本。
