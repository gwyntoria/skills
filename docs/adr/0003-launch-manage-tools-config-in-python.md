# manage-tools 配置菜单直接从 Python 启动

`manage-tools.sh config` 直接调用 `scripts/manage-tools/main.py`，用于完整仓库和从 GitHub 下载的源码归档。删除中间的 Shell 启动脚本及其旧状态栏解包兼容路径，Python 成为唯一的 TUI 入口。已安装的旧版单文件启动器需要更新后才能从归档打开配置菜单，无参数工具更新仍由单文件脚本负责。
