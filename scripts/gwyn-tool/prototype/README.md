# gwyn-tool 交互原型

这个一次性原型用 Go 和 Bubble Tea v2 验证更新入口、管理菜单与交互子进程的终端交接。所有数据和操作结果都是演示样例。

## 运行

使用 Actions 制品中的二进制，或在此目录通过 Go 本地构建。

```bash
go build -o gwyn-tool .
./gwyn-tool
./gwyn-tool update
```

在 Windows PowerShell 中运行 `./gwyn-tool.exe` 或 `./gwyn-tool.exe update`。将 `GWYN_TOOL_PROTOTYPE_UPDATE_FAIL` 设为 `1` 可模拟单项更新失败，观察后续任务和退出码。

## 场景

1. 在 Skills 勾选前两项，滚动、缩放窗口后按 Enter 查看移除计划。按 Esc 返回编辑，按 `y` 再确认时，可看到有外部引用的技能被保留。
2. 在 Rules 勾选带有手写内容的文件，检查预览。按 `n` 取消，确认勾选仍在。
3. 在 Agent 按 Enter 启动交互子进程。分别输入 `ok`、`fail` 或按 Ctrl+C。输入文本后按提示再次按 Enter，查看返回 TUI 后的结果。
4. 在命令行运行 `update`，查看成功、跳过及模拟失败。普通样例退出 `0`，失败样例继续执行后续任务并退出 `1`。

方向键或 `j` 和 `k` 移动，空格切换勾选，`q` 退出。终端尺寸显示用于观察缩放行为。

`go run ./smoke PATH_TO_BINARY` 在宿主系统的伪终端中运行这些场景，Windows 使用 ConPTY。
