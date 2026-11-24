# Shell 脚本检查

新增或修改 Shell 脚本后，在任务结束前对每个改动的文件运行 `shfmt` 和 `ShellCheck`。包括无扩展名的可执行脚本，以及通过 `source` 或 `.` 加载的脚本。优先沿用项目的 Shell 方言、缩进和检查参数。

以下示例使用 Bash 和 4 空格缩进。把路径换成改动的文件。POSIX `sh` 脚本对应使用 `shfmt -ln posix` 和 `shellcheck -s sh`。

```bash
shfmt -ln bash -i 4 -w path/to/script.sh
shfmt -ln bash -i 4 -d path/to/script.sh
shellcheck -s bash -x path/to/script.sh
```

直接将每个改动的脚本传给 ShellCheck。`-x` 允许跟踪 `source`，单独检查入口仍可能漏掉被加载文件中的诊断。无 shebang 的文件通过 `-s` 指定实际解释器。修正本次改动引入的问题后复跑检查。 [ShellCheck 手册](https://github.com/koalaman/shellcheck/blob/master/shellcheck.1.md)

## 工具缺失时

运行仍可用的检查，告知用户哪些检查未运行，并提供适合其系统的安装命令。若项目固定了版本，优先安装要求的版本。Ubuntu 的 `shfmt` 由 Universe 软件源提供。 [Ubuntu shfmt 软件包](https://packages.ubuntu.com/shfmt) [Homebrew shfmt](https://formulae.brew.sh/formula/shfmt) [ShellCheck 安装方式](https://github.com/koalaman/shellcheck#installing)

```bash
# Ubuntu 或使用 Ubuntu 的 WSL
sudo apt update
sudo apt install shfmt shellcheck

# macOS 已安装 Homebrew
brew install shfmt shellcheck
```
