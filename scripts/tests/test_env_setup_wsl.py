#!/usr/bin/env python3
"""Exercise the WSL wizard through its real entrypoint in an isolated HOME/PTY."""
import json
import os
from pathlib import Path
import pty
import re
import select
import shutil
import subprocess
import sys
import tempfile
import termios
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'env-setup-wsl.sh'

STUB = r'''
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(json.dumps([name] + args) + '\n')
if name == 'getent':
    state = Path(os.environ['SHELL_STATE'])
    shell = state.read_text() if state.exists() else '/bin/zsh'
    print('fixture:x:1000:1000::' + os.environ['HOME'] + ':' + shell)
elif name == 'tput':
    print('8')
elif name == 'dpkg-query':
    installed = Path(os.environ['PACKAGE_STATE'])
    packages = installed.read_text().splitlines() if installed.exists() else []
    if args[-1] in packages: print('install ok installed')
    else: sys.exit(1)
elif name == 'apt-cache':
    if os.environ.get('NO_7ZIP'): sys.exit(100)
    print('Package: ' + args[-1])
elif name == 'sudo':
    sys.exit(__import__('subprocess').call(args))
elif name == 'apt':
    print('fixture: apt ' + ' '.join(args), flush=True)
    if args[0] == 'update' and os.environ.get('FAIL_UPDATE'): sys.exit(41)
    if args[0] == 'install':
        if 'bash' in args:
            if os.environ.get('FAIL_SHELL'): sys.exit(42)
            target = Path(os.environ['FIXTURE_BIN']) / 'bash'
            if not target.exists(): target.symlink_to('/bin/bash')
        elif os.environ.get('FAIL_PACKAGES'): sys.exit(43)
        state = Path(os.environ['PACKAGE_STATE'])
        old = state.read_text() if state.exists() else ''
        state.write_text(old + '\n'.join(a for a in args[1:] if not a.startswith('-')) + '\n')
elif name == 'chsh':
    if os.environ.get('FAIL_CHSH'): sys.exit(44)
    if not os.environ.get('UNCHANGED_SHELL'):
        Path(os.environ['SHELL_STATE']).write_text(args[1])
elif name in ('7zz', '7z'):
    if os.environ.get('FAIL_7ZIP'): sys.exit(45)
    print('7-Zip fixture')
else:
    print('UNEXPECTED external command: ' + name, file=sys.stderr)
    sys.exit(99)
'''


class Terminal:
    def __init__(self, env):
        self.master, slave = pty.openpty()
        self.before = termios.tcgetattr(self.master)
        self.process = subprocess.Popen(['/bin/bash', str(SCRIPT)], stdin=slave,
                                        stdout=slave, stderr=slave, env=env)
        os.close(slave)
        self.output = b''
        self.consumed = 0

    def expect(self, text):
        deadline = time.monotonic() + 5
        while True:
            plain = re.sub(rb'\x1b\[[0-9;?]*[a-zA-Z]', b'', self.output).decode(errors='replace')
            offset = plain.find(text, self.consumed)
            if offset >= 0:
                self.consumed = offset + len(text)
                return
            if time.monotonic() >= deadline:
                raise AssertionError(f'Missing {text!r}: {plain}')
            self.read()

    def read(self):
        if select.select([self.master], [], [], .05)[0]:
            try:
                self.output += os.read(self.master, 65536)
            except OSError:
                pass

    def send(self, keys):
        os.write(self.master, keys)

    def finish(self):
        deadline = time.monotonic() + 8
        while self.process.poll() is None:
            self.read()
            if time.monotonic() >= deadline:
                raise AssertionError('Wizard did not exit: ' + self.output.decode(errors='replace'))
        for _ in range(3): self.read()
        return self.process.returncode

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        os.close(self.master)


class WslSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wsl-wizard-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "user's home"
        self.home.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        # No inherited PATH: even unexpected future installer calls cannot reach real tools.
        for name in ['awk', 'cat', 'chmod', 'cmp', 'cp', 'dirname', 'grep', 'id',
                     'mktemp', 'mv', 'readlink', 'rm', 'basename', 'bash']:
            (self.bin / name).symlink_to(shutil.which(name))
        for name in ['apt', 'apt-cache', 'sudo', 'getent', 'dpkg-query', 'chsh', 'tput',
                     '7zz', 'curl', 'wget', 'brew', 'git', 'nvm', 'uv']:
            self.stub(name, STUB)
        self.log = self.root / 'calls.jsonl'
        self.packages = self.root / 'packages'
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin), TERM='xterm-256color',
                        CALL_LOG=str(self.log), PACKAGE_STATE=str(self.packages), FIXTURE_BIN=str(self.bin),
                        SHELL_STATE=str(self.root / 'login-shell'))
        self.env.pop('NO_COLOR', None)
        self.bashrc = self.home / '.bashrc'
        self.zshrc = self.home / '.zshrc'
        self.zshrc.write_text('# untouched zsh\n')

    def stub(self, name, body):
        target = self.bin / name
        if target.is_symlink(): target.unlink()
        target.write_text('#!' + sys.executable + '\n' + body)
        target.chmod(0o755)

    def terminal(self):
        term = Terminal(self.env)
        self.addCleanup(term.close)
        term.expect('选择安装组件')
        return term

    def calls(self, name=None):
        calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return [call for call in calls if name is None or call[0] == name]

    def test_cancel_confirmation_does_not_modify_environment(self):
        term = self.terminal()
        term.send(b'\r')
        term.expect('安装计划')
        term.expect('确认执行')
        term.send(b'n\r')
        self.assertEqual(term.finish(), 0)
        self.assertFalse(self.bashrc.exists())
        self.assertEqual(self.zshrc.read_text(), '# untouched zsh\n')
        self.assertFalse(self.calls('apt'))
        self.assertFalse(self.calls('chsh'))
        self.assertEqual(term.before, termios.tcgetattr(term.master))

    def install(self, selected=True):
        term = self.terminal()
        if not selected: term.send(b' ')
        term.send(b'\r')
        term.expect('确认执行')
        term.send(b'y\r')
        term.expect('安装结果')
        code = term.finish()
        return term, code

    def test_default_install_prepares_bash_and_switches_after_packages(self):
        self.bashrc.write_text('# keep user settings\nalias ll="ls -l"\n')
        term, code = self.install()
        self.assertEqual(code, 0, term.output.decode())
        packages = self.calls('apt')
        self.assertEqual(packages[0], ['apt', 'update'])
        self.assertEqual(packages[1], ['apt', 'install', '-y', 'git', 'curl', 'wget',
                         'ca-certificates', 'build-essential', 'make', 'cmake', 'clang-format',
                         'direnv', 'procps', 'file', 'unzip', 'jq', 'net-tools', 'ripgrep',
                         'fd-find', 'shellcheck', '7zip'])
        self.assertIn('# keep user settings\nalias ll="ls -l"', self.bashrc.read_text())
        self.assertIn('# >>> env-setup-wsl.sh shell >>>', self.bashrc.read_text())
        self.assertEqual(self.zshrc.read_text(), '# untouched zsh\n')
        self.assertEqual(self.calls('chsh'), [['chsh', '-s', '/usr/bin/bash', 'fixture']])
        calls = self.calls()
        self.assertLess(calls.index(packages[1]), calls.index(self.calls('chsh')[0]))
        output = term.output.decode()
        self.assertIn('重新打开终端', output)
        self.assertIn('/bin/zsh', output)
        self.assertIn('成功', output)

    def test_repeated_run_preserves_symlink_permissions_and_can_restore_backup(self):
        target = self.home / "custom startup"
        original = '# custom settings without final newline'
        target.write_text(original)
        target.chmod(0o640)
        self.bashrc.symlink_to(target)
        first, code = self.install(selected=False)
        self.assertEqual(code, 0, first.output.decode())
        generated = target.read_bytes()
        second, code = self.install(selected=False)
        self.assertEqual(code, 0, second.output.decode())
        self.assertEqual(target.read_bytes(), generated)
        self.assertTrue(self.bashrc.is_symlink())
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        backups = list(self.home.glob('custom startup.env-setup-wsl.backup.*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), original)
        # Execute the printed recovery command; quoted paths include spaces and apostrophes.
        output = re.sub(r'\x1b\[[0-9;]*m', '', first.output.decode())
        command = re.search(r'恢复命令：(.*)', output).group(1).strip()
        subprocess.run(['/bin/bash', '-c', command], env=self.env, check=True)
        self.assertEqual(target.read_text(), original)
        self.assertFalse(self.calls('apt'))
        self.assertIn('用户未选择', second.output.decode())

    def test_failed_update_stops_package_step_but_still_prepares_and_switches(self):
        self.env['FAIL_UPDATE'] = '1'
        term, code = self.install()
        self.assertEqual(code, 1)
        self.assertEqual(self.calls('apt'), [['apt', 'update']])
        self.assertTrue(self.bashrc.is_file())
        self.assertTrue(self.calls('chsh'))
        output = re.sub(r'\x1b\[[0-9;]*m', '', term.output.decode())
        self.assertIn('[失败] 系统基础包', output)
        self.assertIn('[成功] Bash 配置', output)
        self.assertIn('[成功] 默认 shell 切换', output)
        self.assertIn('sudo apt update && sudo apt install', output)

    def test_unavailable_7zip_is_explained_without_installing_package_list(self):
        self.env['NO_7ZIP'] = '1'
        term, code = self.install()
        self.assertEqual(code, 1)
        self.assertEqual(self.calls('apt'), [['apt', 'update']])
        self.assertIn('未找到软件包 7zip', term.output.decode())
        self.assertTrue(self.calls('chsh'))

    def test_package_install_failure_still_runs_independent_steps(self):
        self.env['FAIL_PACKAGES'] = '1'
        term, code = self.install()
        self.assertEqual(code, 1)
        self.assertTrue(self.bashrc.exists())
        self.assertTrue(self.calls('chsh'))
        self.assertIn('退出码 43', term.output.decode())

    def test_missing_bash_is_installed_before_configuring(self):
        (self.bin / 'bash').unlink()
        term, code = self.install(selected=False)
        self.assertEqual(code, 0, term.output.decode())
        self.assertEqual(self.calls('apt'), [['apt', 'update'], ['apt', 'install', '-y', 'bash']])
        self.assertTrue(self.bashrc.is_file())
        self.assertTrue(self.calls('chsh'))

    def test_failed_bash_install_skips_configuration_and_switch(self):
        (self.bin / 'bash').unlink()
        self.env['FAIL_SHELL'] = '1'
        term, code = self.install(selected=False)
        self.assertEqual(code, 1)
        self.assertFalse(self.bashrc.exists())
        self.assertFalse(self.calls('chsh'))
        self.assertIn('因依赖失败跳过', term.output.decode())

    def test_configuration_failures_preserve_original_and_skip_switch(self):
        start = '# >>> env-setup-wsl.sh shell >>>'
        end = '# <<< env-setup-wsl.sh shell <<<'
        cases = {'unterminated': start + '\nuser content\n',
                 'orphan': end + '\nuser content\n',
                 'nested': start + '\n' + start + '\n' + end + '\n',
                 'syntax': "if broken bash syntax\n"}
        for label, original in cases.items():
            with self.subTest(label=label):
                self.bashrc.write_text(original)
                term, code = self.install(selected=False)
                self.assertEqual(code, 1)
                self.assertEqual(self.bashrc.read_text(), original)
                self.assertFalse(self.calls('chsh'))
                self.assertIn('因依赖失败跳过', term.output.decode())
                self.assertFalse(list(self.home.glob('.*.tmp.*')))

    def test_failed_file_operations_preserve_original_and_skip_switch(self):
        for name in ['mktemp', 'awk', 'chmod', 'mv', 'cp']:
            with self.subTest(command=name):
                original = '# user config\n'
                self.bashrc.write_text(original)
                self.stub(name, "import sys\nsys.exit(46)\n")
                term, code = self.install(selected=False)
                self.assertEqual(code, 1)
                self.assertEqual(self.bashrc.read_text(), original)
                self.assertFalse(self.calls('chsh'))
                self.assertNotIn('unbound variable', term.output.decode())
                self.assertFalse(list(self.home.glob('.*.tmp.*')))
                (self.bin / name).unlink()
                (self.bin / name).symlink_to(shutil.which(name))

    def test_configuration_directory_or_dangling_link_is_not_replaced(self):
        self.bashrc.mkdir()
        term, code = self.install(selected=False)
        self.assertEqual(code, 1)
        self.assertTrue(self.bashrc.is_dir())
        self.bashrc.rmdir()
        self.bashrc.symlink_to(self.home / 'missing')
        term, code = self.install(selected=False)
        self.assertEqual(code, 1)
        self.assertTrue(self.bashrc.is_symlink())
        self.assertFalse((self.home / 'missing').exists())
        self.assertFalse(self.calls('chsh'))

    def test_default_shell_switch_failure_is_reported(self):
        self.env['FAIL_CHSH'] = '1'
        term, code = self.install(selected=False)
        self.assertEqual(code, 1)
        output = re.sub(r'\x1b\[[0-9;]*m', '', term.output.decode())
        self.assertIn('[失败] 默认 shell 切换', output)
        self.assertIn('chsh -s /usr/bin/bash fixture', output)
        self.assertNotIn('默认 shell 已设置', output)

    def test_all_packages_installed_skips_apt_and_checks_archive_command(self):
        self.packages.write_text('\n'.join(['git', 'curl', 'wget', 'ca-certificates',
            'build-essential', 'make', 'cmake', 'clang-format', 'direnv', 'procps', 'file',
            'unzip', 'jq', 'net-tools', 'ripgrep', 'fd-find', 'shellcheck', '7zip']))
        term, code = self.install()
        self.assertEqual(code, 0, term.output.decode())
        self.assertFalse(self.calls('apt'))
        self.assertTrue(self.calls('7zz'))

    def test_7zip_command_failure_is_a_failure_not_a_success(self):
        self.env['FAIL_7ZIP'] = '1'
        term, code = self.install()
        self.assertEqual(code, 1)
        self.assertTrue(self.calls('chsh'))
        self.assertIn('退出码 45', term.output.decode())

    def test_plain_text_modes_keep_states_without_escape_sequences(self):
        for changes in [{'NO_COLOR': ''}, {'TERM': 'dumb'}]:
            with self.subTest(environment=changes):
                self.env.update(changes)
                term, code = self.install(selected=False)
                self.assertEqual(code, 0, term.output.decode())
                self.assertNotIn(b'\x1b', term.output)
                self.assertIn('[成功]', term.output.decode())
                self.assertIn('[用户未选择]', term.output.decode())
                self.assertEqual(term.before, termios.tcgetattr(term.master))
                for key in changes: self.env.pop(key, None)
                self.env['TERM'] = 'xterm-256color'

    def test_arrow_navigation_toggle_and_color_roles(self):
        term = self.terminal()
        term.send(b'\x1b[B\x1b[A ')
        term.expect('[ ]')
        term.send(b'\r')
        term.expect('确认执行')
        term.send(b'y\r')
        term.expect('安装结果')
        self.assertEqual(term.finish(), 0)
        self.assertFalse(self.calls('apt'))
        for code in [b'7', b'36', b'34', b'35', b'32', b'33']:
            self.assertIn(b'\x1b[' + code + b'm', term.output)
        self.assertEqual(term.before, termios.tcgetattr(term.master))

    def test_quit_menu_restores_terminal_and_does_not_install(self):
        term = self.terminal()
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertFalse(self.bashrc.exists())
        self.assertFalse(self.calls('apt'))
        self.assertEqual(term.before, termios.tcgetattr(term.master))

    def test_noninteractive_install_exits_but_help_and_bad_options_work(self):
        for args, expected in [((), 1), (('--help',), 0), (('--unattended',), 2)]:
            with self.subTest(args=args):
                result = subprocess.run(['/bin/bash', str(SCRIPT), *args], env=self.env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, expected)
        self.assertFalse(self.calls('apt'))
        self.assertFalse(self.calls('chsh'))
        self.assertFalse(self.bashrc.exists())

    def test_shell_switch_is_not_successful_until_account_state_matches(self):
        self.env['UNCHANGED_SHELL'] = '1'
        term, code = self.install(selected=False)
        self.assertEqual(code, 1)
        output = re.sub(r'\x1b\[[0-9;]*m', '', term.output.decode())
        self.assertIn('[失败] 默认 shell 切换', output)
        self.assertNotIn('默认 shell 已设置', output)

    def test_failed_shell_path_resolution_is_reported_and_does_not_switch(self):
        self.stub('readlink', 'import sys\nsys.exit(47)\n')
        term, code = self.install(selected=False)
        self.assertEqual(code, 1)
        self.assertFalse(self.calls('chsh'))
        self.assertFalse(self.bashrc.exists())
        self.assertIn('因依赖失败跳过', term.output.decode())

    def test_shared_zsh_startup_file_is_preserved_and_prevents_switch(self):
        self.bashrc.symlink_to(self.zshrc)
        term, code = self.install(selected=False)
        self.assertEqual(code, 1)
        self.assertEqual(self.zshrc.read_text(), '# untouched zsh\n')
        self.assertTrue(self.bashrc.is_symlink())
        self.assertFalse(self.calls('chsh'))

    def test_plain_text_navigation_has_visible_focus(self):
        self.env['NO_COLOR'] = '1'
        term = self.terminal()
        term.expect('> [x] 系统基础包')
        term.send(b'\x1b[B')
        term.expect('> 继续')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)

    def test_bad_managed_block_has_chinese_hint_and_runnable_diagnostic(self):
        self.bashrc.write_text('# >>> env-setup-wsl.sh shell >>>\n# keep\n')
        term, code = self.install(selected=False)
        self.assertEqual(code, 1)
        output = re.sub(r'\x1b\[[0-9;]*m', '', term.output.decode())
        self.assertNotIn('Error: could not safely remove', output)
        self.assertIn('原文件已保留', output)
        command = re.search(r'修复后运行：(bash -n .*?)\r?\n', output).group(1)
        result = subprocess.run(['/bin/bash', '-n'], input=command, text=True,
                                capture_output=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        # The recommended diagnostic targets the actual file including quotes/spaces.
        diagnostic = command.split(' && ')[0]
        self.assertEqual(subprocess.run(['/bin/bash', '-c', diagnostic], env=self.env).returncode, 0)


if __name__ == '__main__':
    unittest.main()
