# gwyn-tool 跨平台 TUI 与安装分发调查

对应 [比较跨平台 TUI 技术与安装分发方式](https://github.com/gwyntoria/skills/issues/10)。目标是让 `gwyn-tool` 默认打开 TUI，让 `gwyn-tool update` 显式更新受管理的工具，并能通过 Windows 原生终端、macOS 和 Ubuntu 运行。Scoop、Homebrew 和 Ubuntu 的安装渠道负责安装与升级 gwyn-tool 自身。

## 技术栈对比

| 候选 | 用户端制品与目标平台 | TUI 能力与迁移成本 |
| --- | --- | --- |
| Go + Bubble Tea | 纯 Go 构建可用 `CGO_ENABLED=0` 按 `GOOS/GOARCH` 交叉编译。Windows、macOS、Linux 均有 amd64 和 arm64 目标，用户无需安装 Go。[^1][^2] | `ExecProcess` 将终端交给交互子进程，在子进程结束后恢复 TUI，支持回调接收错误。`WindowSizeMsg` 和按键消息可驱动重排、滚动和中断。Bubbles 的列表支持翻页、自定义行渲染及统一行高，Huh 提供多选。若每项描述需随宽度折成不同行数，原型应验证列表能否按可见行滚动并保持勾选。Bubble Tea v2 曾出现 Windows 缩放回归，报告者在 v2.0.6 确认修复。迁移需要重写现有 Python 菜单和相关业务逻辑。[^3][^4][^5][^6] |
| Rust + Ratatui / Crossterm | 可交付原生二进制，用户无需安装 Rust 或 Cargo。三平台都有 x86_64 和 ARM64 目标。Rust 当前将 Intel macOS 列为 Tier 2，Apple Silicon、两种 Linux GNU 目标和两种 Windows MSVC 目标列为 Tier 1。Linux GNU 制品需验证 glibc 基线，也可评估静态 musl 构建。Windows 需检查 MSVC C 运行库链接方式。[^7][^8] | Crossterm 支持 Windows、键盘和缩放事件。Ratatui 的列表项支持多行，`ListState` 管理滚动与一个高亮索引，勾选集合由应用维护。官方示例先退出备用屏幕并关闭 raw mode，同步运行交互子进程，再初始化终端。应用负责错误路径上的恢复与中断语义。迁移需要重写 Python 逻辑，事件循环与终端交接也由应用组织。[^9][^10][^11][^12][^13] |
| Python + Textual / PyInstaller | PyInstaller 将 CPython、依赖和程序打成一个目录或一个文件，用户无需预装 Python。按目标操作系统构建。官方列出 Windows x64 / ARM64、macOS x64 / ARM64（也可构建 universal2）和 Linux 多架构。Linux 制品应在最旧承诺支持的系统上构建并验证 glibc 兼容性。`--onefile` 启动时先解包，目录型制品可随安装渠道打包。[^14][^15][^16][^17] | Textual 有原生 Windows 驱动、`Resize` 事件和 `App.suspend()`，后者可在应用模式外运行交互程序，Windows 驱动也声明支持挂起。`SelectionList` 的选项提示设计为单行，多行描述可用 `ListView` 内的自定义列表项显示，应用维护勾选状态。Textual 默认把 `Ctrl+C` 用于复制或提示退出，需要显式设计中断行为。可复用现有 Python 的安装选择与目录逻辑。需处理冻结后启动 worker 的入口，以及 PyInstaller 对外部工具动态库搜索路径的影响。[^18][^19][^20][^21][^22][^23][^24] |

现有 `scripts/gwyn-tool.sh` 依赖 Bash 5，默认执行更新，`config` 才进入 Python curses 菜单。现有 Python 还使用 Unix 进程组取消后台任务，并通过 `sys.executable` 和脚本路径启动 worker。换 TUI 或冻结程序后，仍需梳理 Bash 启动的安装步骤和外部命令在原生 Windows 上的对应入口。

## 安装与升级

建议每个版本从同一 Git 标签生成按系统和架构区分的制品，再由各渠道引用该版制品。发布页可提供对应归档及 SHA-256 校验值。先将 Windows、macOS 和 Ubuntu 的 x64 / ARM64 视为候选构建矩阵，实际支持范围由原生验证结果确定。[^25]

| 渠道 | 制品和升级方式 |
| --- | --- |
| Windows Scoop | 自有 bucket 的 manifest 可用 `architecture.64bit` 和 `architecture.arm64` 选取对应 ZIP，配 `url`、`hash` 和 `bin`，由 shim 暴露 `gwyn-tool`。发布后更新 manifest 的版本与哈希，也可配置 `checkver` 和 `autoupdate` 辅助生成新版清单。用户用 `scoop update gwyn-tool` 升级。[^26][^27] |
| macOS Homebrew | 自有 tap 可用 cask 引用已构建的归档，以 `binary` 将命令链接到 Homebrew 的 `bin`，分架构声明下载地址及校验值。也可用源码 formula 配 tap 自己的 bottles，承担额外构建及发布维护。新版通过 `brew upgrade` 安装。Homebrew 当前把 Intel Mac 列为 Tier 3，已经停止构建新的官方 Intel bottles，项目若承诺 Intel macOS，应实测自己的归档及安装渠道。[^28][^29][^30][^31] |
| Ubuntu | 带校验值的 Release tarball 可直接解压运行，适合作为无需额外包仓库的入口，升级时下载新版。也可按架构提供 `.deb`，用 `sudo apt install ./gwyn-tool_版本_架构.deb` 安装。若需要 `apt upgrade` 持续发现新版本，则维护签名 APT 仓库并发布索引。Homebrew on Linux 可作为已有 Brew 用户的入口。[^25][^32][^33][^34] |

## 原生环境验证

- 在 Windows Terminal + PowerShell、macOS Terminal 和 Ubuntu 终端实测多选和滚动。使用带中文长描述的项目，连续缩放，核对高亮项、勾选状态和滚动位置。
- 从 TUI 运行需要键盘输入的子进程，确认标准输入、输出和错误输出直达终端。分别验证成功、非零退出、启动失败、子进程运行中缩放和 `Ctrl+C`。也验证在 TUI 内中断及后台任务取消后，光标、回显和备用屏幕恢复，子进程退出状态得到正确处理。Windows 控制台会依据输入模式将 `Ctrl+C` 作为键或控制事件处理，需验证父子进程实际收到的事件。[^35]
- 使用未预装对应语言运行时的干净系统，按每个承诺支持的系统和架构安装发布制品，确认 PATH 命令默认进 TUI、显式 `update` 才更新外部工具，并试一次从上一版升级及卸载。特别验证 Windows 原生入口能执行相关外部工具，以及冻结 Python 后调用 worker 和外部程序的行为。[^24]

Go 的主要收益是纯 Go 制品容易交叉构建，Bubble Tea 已提供交互命令的终端交接。Rust 提供多行列表项和直接的终端控制，应用承担更多事件和生命周期代码。Python 能复用既有业务逻辑，需投入平台构建、冻结后的子进程兼容和多行勾选界面。优先对候选方案验证多行选择、终端交接和安装后启动，再依据实测决定技术栈。

## References

1. [^1]: Go, [Installing Go from source](https://go.dev/doc/install/source#environment).
2. [^2]: Go, [Building Windows Go programs on Linux](https://go.dev/wiki/WindowsCrossCompiling).
3. [^3]: Charm, [Bubble Tea v2 API](https://pkg.go.dev/charm.land/bubbletea/v2).
4. [^4]: Charm, [Bubbles v2 list](https://pkg.go.dev/charm.land/bubbles/v2/list).
5. [^5]: Charm, [Huh MultiSelect](https://github.com/charmbracelet/huh#forms).
6. [^6]: Bubble Tea, [Windows resize regression and confirmation of the fix](https://github.com/charmbracelet/bubbletea/issues/1601).
7. [^7]: Rust, [Platform Support](https://doc.rust-lang.org/stable/rustc/platform-support.html).
8. [^8]: Rust, [Linkage](https://doc.rust-lang.org/stable/reference/linkage.html#static-and-dynamic-c-runtimes).
9. [^9]: Ratatui, [Comparison of Backends](https://ratatui.rs/concepts/backends/comparison/).
10. [^10]: Crossterm, [Event](https://docs.rs/crossterm/latest/crossterm/event/enum.Event.html).
11. [^11]: Ratatui, [ListItem](https://docs.rs/ratatui/latest/ratatui/widgets/struct.ListItem.html).
12. [^12]: Ratatui, [ListState](https://docs.rs/ratatui/latest/ratatui/widgets/struct.ListState.html).
13. [^13]: Ratatui, [Spawn External Editor](https://ratatui.rs/recipes/apps/spawn-vim/).
14. [^14]: PyInstaller, [What PyInstaller Does and How It Does It](https://pyinstaller.org/en/stable/operating-mode.html).
15. [^15]: PyInstaller, [Supported platforms](https://github.com/pyinstaller/pyinstaller#supported-platforms).
16. [^16]: PyInstaller, [Requirements](https://pyinstaller.org/en/stable/requirements.html).
17. [^17]: PyInstaller, [Making GNU/Linux Apps Forward-Compatible](https://pyinstaller.org/en/stable/usage.html#making-gnu-linux-apps-forward-compatible).
18. [^18]: Textual, [Suspending](https://textual.textualize.io/guide/app/#suspending).
19. [^19]: Textual, [Windows driver source](https://github.com/Textualize/textual/blob/main/src/textual/drivers/windows_driver.py).
20. [^20]: Textual, [Resize event](https://textual.textualize.io/events/resize/).
21. [^21]: Textual, [SelectionList](https://textual.textualize.io/widgets/selection_list/).
22. [^22]: Textual, [ListView](https://textual.textualize.io/widgets/list_view/).
23. [^23]: Textual, [App bindings](https://textual.textualize.io/api/app/#textual.app.App.BINDINGS).
24. [^24]: PyInstaller, [Common Issues and Pitfalls](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html).
25. [^25]: GitHub, [About releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).
26. [^26]: Scoop, [App Manifests](https://github.com/ScoopInstaller/Scoop/wiki/App-Manifests).
27. [^27]: Scoop, [App Manifest Autoupdate](https://github.com/ScoopInstaller/Scoop/wiki/App-Manifest-Autoupdate).
28. [^28]: Homebrew, [How to Create and Maintain a Tap](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap).
29. [^29]: Homebrew, [Cask Cookbook](https://docs.brew.sh/Cask-Cookbook).
30. [^30]: Homebrew, [brew manual](https://docs.brew.sh/Manpage).
31. [^31]: Homebrew, [Support Tiers](https://docs.brew.sh/Support-Tiers).
32. [^32]: Ubuntu, [How to install built packages](https://documentation.ubuntu.com/project/contributors/bug-fix/install-built-packages/).
33. [^33]: Ubuntu, [Consuming Public and Private PPAs](https://documentation.ubuntu.com/hardware-support/image-cookbook/howto/launchpad/consume_ppa/).
34. [^34]: Homebrew, [Homebrew on Linux](https://docs.brew.sh/Homebrew-on-Linux).
35. [^35]: Microsoft, [CTRL+C and CTRL+BREAK Signals](https://learn.microsoft.com/en-us/windows/console/ctrl-c-and-ctrl-break-signals).
