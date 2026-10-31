#!/usr/bin/env python3
"""Exercise the WSL wizard through its real entrypoint in an isolated HOME/PTY."""
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import shutil
import subprocess
import sys
import tempfile
import termios
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'env-setup-wsl.sh'
ZSH_BINARY = shutil.which('zsh')

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
    if args[-1] == '7zip' and os.environ.get('NO_7ZIP'): sys.exit(100)
    if args[-1] == 'lazygit' and os.environ.get('NO_LAZY_APT'): sys.exit(100)
    print('Package: ' + args[-1])
elif name == 'sudo':
    sys.exit(__import__('subprocess').call(args))
elif name == 'apt':
    print('fixture: apt ' + ' '.join(args), flush=True)
    if args[0] == 'update' and os.environ.get('FAIL_UPDATE'): sys.exit(41)
    if args[0] == 'install':
        if 'zsh' in args:
            if os.environ.get('FAIL_SHELL'): sys.exit(42)
            target = Path(os.environ['FIXTURE_BIN']) / 'zsh'
            target.write_bytes(target.with_name('zsh-fixture').read_bytes()); target.chmod(0o755)
        elif 'bash' in args:
            if os.environ.get('FAIL_SHELL'): sys.exit(42)
            target = Path(os.environ['FIXTURE_BIN']) / 'bash'
            if not target.exists(): target.symlink_to('/bin/bash')
        elif 'lazygit' in args:
            if os.environ.get('FAIL_LAZY_APT'): sys.exit(56)
            target = Path(os.environ['FIXTURE_BIN']) / 'lazygit'
            target.write_bytes((Path(os.environ['FIXTURE_BIN']) / 'lazygit-fixture').read_bytes())
            target.chmod(0o755)
        elif os.environ.get('FAIL_PACKAGES'): sys.exit(43)
        state = Path(os.environ['PACKAGE_STATE'])
        old = state.read_text() if state.exists() else ''
        state.write_text(old + '\n'.join(a for a in args[1:] if not a.startswith('-')) + '\n')
        for name in ['curl', 'git', 'make']:
            target = Path(os.environ['FIXTURE_BIN']) / name
            fixture = target.with_name(name + '-fixture')
            if name in args and not target.exists() and fixture.exists():
                target.write_bytes(fixture.read_bytes()); target.chmod(0o755)
elif name == 'chsh':
    if os.environ.get('FAIL_CHSH'): sys.exit(44)
    if not os.environ.get('UNCHANGED_SHELL'):
        Path(os.environ['SHELL_STATE']).write_text(args[1])
elif name in ('7zz', '7z'):
    if os.environ.get('FAIL_7ZIP'): sys.exit(45)
    print('7-Zip fixture')
elif name == 'node':
    print('v' + os.environ.get('FIXTURE_NODE_VERSION', '24'))
elif name in ('codex', 'claude'):
    if os.environ.get('FAIL_' + name.upper()): sys.exit(61)
    print(name + ' fixture version')
elif name == 'agent-setup':
    if os.environ.get('SHELL') != os.environ.get('EXPECTED_SHELL', '/bin/bash'): sys.exit(68)
    print('fixture: raw agent/skill log', flush=True)
    print('fixture: active node ' + os.environ.get('FIXTURE_NODE_VERSION', 'none'), flush=True)
    sys.exit(int(os.environ.get('AGENT_EXIT', '0')))
elif name in ('brew', 'eza', 'lazygit', 'uv', 'npm', 'git'):
    if name == 'git' and args[:1] == ['clone']:
        if os.environ.get('FAIL_OMZ'): sys.exit(71)
        target = Path(args[-1]); target.mkdir(parents=True)
        (target / 'oh-my-zsh.sh').write_text('# fixture framework\n')
    if name == 'uv' and args[:2] == ['python', 'find'] and os.environ.get('MISSING_PYTHON'):
        state = Path(os.environ['PACKAGE_STATE'] + '.python')
        if not state.exists(): sys.exit(1)
    if name == 'uv' and args[:2] == ['python', 'install']:
        if os.environ.get('FAIL_PYTHON'): sys.exit(52)
        Path(os.environ['PACKAGE_STATE'] + '.python').touch()
    if name == 'brew' and args[:1] == ['install']:
        if os.environ.get('FAIL_BREW'): sys.exit(57)
        target = Path(os.environ['FIXTURE_BIN']) / args[1]
        target.write_bytes((Path(os.environ['FIXTURE_BIN']) / (args[1] + '-fixture')).read_bytes())
        target.chmod(0o755)
    if name == 'brew' and args[:1] == ['shellenv']:
        print('export PATH="' + os.environ['FIXTURE_BIN'] + ':$PATH"')
    else: print(name + ' fixture version')
elif name == 'nvm':
    if args[:2] == ['alias', 'default']:
        Path(os.environ['HOME'], '.nvm', 'default-version').write_text(args[2])
    if args[0] == 'version' and os.environ.get('NVM_ERROR'): sys.exit(54)
    if args[0] == 'version' and os.environ.get('MISSING_NODE'):
        print('N/A'); sys.exit(3)
    if args[0] == 'install' and os.environ.get('FAIL_NODE'): sys.exit(55)
    print('v24.0.0')
elif name == 'zsh':
    if args == ['--version']: print('zsh fixture version')
    else: os.execv(os.environ['REAL_ZSH'], [os.environ['REAL_ZSH']] + args)
elif name == 'curl':
    url = args[-1]
    if os.environ.get('FAIL_DOWNLOAD'): sys.exit(51)
    if 'astral.sh' in url:
        print('test "$UV_NO_MODIFY_PATH" = 1 || echo polluted >> "$HOME/.zshrc"')
        print('test -n "$UV_INSTALL_DIR"')
        print('cp "$FIXTURE_BIN/uv-fixture" "$UV_INSTALL_DIR/uv"')
    elif 'nvm-sh' in url:
        print('test -z "$NODE_VERSION" || exit 59')
        print('test "$PROFILE" = /dev/null || echo polluted >> "$HOME/.zshrc"')
        print('mkdir -p "$NVM_DIR"')
        print('cp "$FIXTURE_BIN/nvm-fixture" "$NVM_DIR/nvm.sh"')
    elif 'Homebrew' in url:
        print('test "$NONINTERACTIVE" = 1')
        print('cp "$FIXTURE_BIN/brew-fixture" "$FIXTURE_BIN/brew"')
    elif 'codex/install.sh' in url or 'claude.ai/install.sh' in url:
        tool = 'codex' if 'codex' in url else 'claude'
        if tool == 'codex' and os.environ.get('FAIL_CODEX_DOWNLOAD'): sys.exit(62)
        if tool == 'codex':
            print('test "$CODEX_INSTALL_DIR" = "$HOME/.local/bin" || exit 66')
            print('test "$CODEX_NON_INTERACTIVE" = true || exit 67')
        print('test "$SHELL" = "$EXPECTED_SHELL" || echo polluted >> "$HOME/.profile"')
        print('case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo polluted >> "$HOME/.profile" ;; esac')
        print('mkdir -p "$HOME/.local/bin"')
        print('cp "$FIXTURE_BIN/' + tool + '-fixture" "$HOME/.local/bin/' + tool + '"')
    else: sys.exit(98)
else:
    print('UNEXPECTED external command: ' + name, file=sys.stderr)
    sys.exit(99)
'''


class Terminal:
    def __init__(self, env):
        self.master, slave = pty.openpty()
        self.before = termios.tcgetattr(self.master)
        self.process = subprocess.Popen(['/bin/bash', env.get('WIZARD_SCRIPT', str(SCRIPT))], stdin=slave,
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
                     'mktemp', 'mv', 'readlink', 'rm', 'basename', 'bash', 'mkdir', 'install', 'touch', 'head', 'sh', 'env']:
            (self.bin / name).symlink_to(shutil.which(name))
        for name in ['apt', 'apt-cache', 'sudo', 'getent', 'dpkg-query', 'chsh', 'tput',
                     '7zz', 'curl', 'wget', 'brew', 'git', 'nvm', 'uv']:
            self.stub(name, STUB)
        self.log = self.root / 'calls.jsonl'
        self.packages = self.root / 'packages'
        self.env = dict(os.environ, EXPECTED_SHELL='/bin/bash', HOME=str(self.home), PATH=str(self.bin), TERM='xterm-256color',
                        REAL_ZSH=ZSH_BINARY or '', CALL_LOG=str(self.log), PACKAGE_STATE=str(self.packages), FIXTURE_BIN=str(self.bin),
                        SHELL_STATE=str(self.root / 'login-shell'))
        # Mock the fixed external Homebrew location as well as PATH. The whole
        # entrypoint still runs; no installed host Homebrew can bypass the fakes.
        isolated_script = self.root / 'env-setup-wsl.sh'
        source = SCRIPT.read_text()
        external_path = 'HOMEBREW_BIN="/home/linuxbrew/.linuxbrew/bin/brew"'
        self.assertEqual(source.count(external_path), 1, 'Refresh the external-path fixture before running installers')
        isolated_script.write_text(source.replace(
            external_path, 'HOMEBREW_BIN=' + shlex.quote(str(self.bin / 'brew'))))
        shutil.copyfile(SCRIPT.with_name('env-update.sh'), self.root / 'env-update.sh')
        self.env['WIZARD_SCRIPT'] = str(isolated_script)
        self.env.pop('NO_COLOR', None)
        for key in ['ZSH', 'ZSH_CUSTOM', 'ZDOTDIR']:
            self.env.pop(key, None)
        self.bashrc = self.home / '.bashrc'
        self.zshrc = self.home / '.zshrc'
        self.zshrc.write_text('# untouched zsh\n')

    def stub(self, name, body):
        if name in ('zsh', 'zsh-fixture'):
            self.assertIsNotNone(ZSH_BINARY, 'Zsh tests require zsh on PATH; see README.md')
        target = self.bin / name
        if target.is_symlink(): target.unlink()
        target.write_text('#!' + sys.executable + '\n' + body)
        target.chmod(0o755)

    def terminal(self, shell="bash"):
        self.env['EXPECTED_SHELL'] = '/bin/' + shell
        term = Terminal(self.env)
        self.addCleanup(term.close)
        term.expect('选择终端类型')
        term.send((b'\x1b[B' if shell == 'zsh' else b'') + b'\r')
        term.expect('选择安装组件')
        return term

    def calls(self, name=None):
        calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return [call for call in calls if name is None or call[0] == name]

    def dev_fixture(self):
        for name in ['brew', 'eza', 'lazygit', 'uv', 'node', 'npm', 'git', 'make']:
            self.stub(name, STUB)
        for name in ['eza', 'lazygit', 'uv', 'brew', 'curl', 'git', 'make']:
            self.stub(name + '-fixture', STUB)
        (self.bin / 'nvm-fixture').write_text(
            'nvm() { if [ "$1" = use ]; then export FIXTURE_NODE_VERSION="$2"; fi; command nvm "$@"; }\n'
            'if [ "${1:-}" != --no-use ] && [ -f "$HOME/.nvm/default-version" ]; then\n'
            '  nvm use "$(cat "$HOME/.nvm/default-version")"\nfi\n')
        nvm = self.home / '.nvm'
        nvm.mkdir(exist_ok=True)
        (nvm / 'nvm.sh').write_text((self.bin / 'nvm-fixture').read_text())

    def ai_fixture(self):
        self.dev_fixture()
        for name in ['codex', 'claude', 'codex-fixture', 'claude-fixture']:
            self.stub(name, STUB)
        self.stub('npx', STUB)
        entry = self.root / 'agent-setup.sh'
        entry.write_text('#!/bin/bash\nexec agent-setup "$@"\n')
        self.stub('agent-setup', STUB)

    def test_zsh_choice_installs_framework_and_only_configures_zsh(self):
        self.stub('zsh', STUB)
        self.bashrc.write_text('# keep bash\n')
        self.zshrc.unlink()
        output, code = self.confirm(self.choose_only(set(), shell='zsh'))
        self.assertEqual(code, 0, output)
        self.assertIn('目标 shell：Zsh', output)
        self.assertIn('[成功] Oh My Zsh', output)
        self.assertEqual(self.bashrc.read_text(), '# keep bash\n')
        config = self.zshrc.read_text()
        self.assertIn('robbyrussell', config)
        self.assertIn('oh-my-zsh.sh', config)
        self.assertIn('matcher-list', config)
        self.assertFalse((self.home / '.inputrc').exists())
        self.assertEqual(self.calls('chsh')[-1][2], str(self.bin / 'zsh'))
        self.assertLess(self.calls().index([c for c in self.calls('git') if 'clone' in c][0]),
                        self.calls().index(self.calls('chsh')[-1]))

    def test_zsh_reuses_custom_framework_theme_and_runtime_config_once(self):
        self.dev_fixture()
        self.stub('zsh', STUB)
        framework = self.home / 'custom framework'
        framework.mkdir()
        (framework / 'oh-my-zsh.sh').write_text('print -r -- "$ZSH_THEME" >> "$HOME/framework-loads"\n')
        self.env['ZSH'] = str(framework)
        original = 'export ZSH=' + shlex.quote(str(framework)) + '\nZSH_THEME="agnoster"\nplugins=(git custom)\nsource "$ZSH/oh-my-zsh.sh"\n'
        target = self.home / 'linked zsh startup'
        target.write_text(original)
        target.chmod(0o640)
        self.zshrc.unlink()
        self.zshrc.symlink_to(target)
        self.bashrc.write_text('# keep bash\n')
        for _ in range(2):
            output, code = self.confirm(self.choose_only({1, 3, 4}, shell='zsh'))
            self.assertEqual(code, 0, output)
        config = target.read_text()
        self.assertIn(original, config)
        self.assertEqual(config.count('oh-my-zsh.sh'), 1)
        self.assertIn('shellenv zsh', config)
        self.assertNotIn('bash_completion', config)
        self.assertTrue(self.zshrc.is_symlink())
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        self.assertEqual(len(list(self.home.glob('linked zsh startup.env-setup-wsl.backup.*'))), 1)
        self.assertFalse([c for c in self.calls('git') if 'clone' in c])
        self.assertEqual(self.bashrc.read_text(), '# keep bash\n')
        result = subprocess.run([ZSH_BINARY, '-dfc', 'source "$HOME/.zshrc"; alias ls; print -r -- "$NVM_DIR"'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('eza -al', result.stdout)
        self.assertIn(str(self.home / '.nvm'), result.stdout)
        self.assertEqual((self.home / 'framework-loads').read_text(), 'agnoster\n')

    def test_missing_zsh_and_framework_git_are_installed_as_mandatory_dependencies(self):
        self.stub('zsh-fixture', STUB)
        self.stub('git-fixture', STUB)
        (self.bin / 'git').unlink()
        output, code = self.confirm(self.choose_only(set(), shell='zsh'))
        self.assertEqual(code, 0, output)
        self.assertIn(['apt', 'install', '-y', 'zsh'], self.calls())
        self.assertIn(['apt', 'install', '-y', 'git'], self.calls())
        self.assertIn('Oh My Zsh 依赖 git', output)
        self.assertTrue(self.calls('chsh'))

    def test_zsh_all_native_installers_respect_target_and_delegate_after_node(self):
        self.ai_fixture()
        self.stub('zsh', STUB)
        self.bashrc.write_text('# untouched bash\n')
        profile = self.home / '.profile'
        profile.write_text('# untouched profile\n')
        for name in ['codex', 'claude', 'uv']:
            (self.bin / name).unlink()
        shutil.rmtree(self.home / '.nvm')
        output, code = self.confirm(self.choose_only({3, 7}, shell='zsh'))
        self.assertEqual(code, 0, output)
        self.assertEqual(self.bashrc.read_text(), '# untouched bash\n')
        self.assertEqual(profile.read_text(), '# untouched profile\n')
        self.assertNotIn('polluted', self.zshrc.read_text())
        self.assertIn('[成功] Agent/Skill 配置', output)
        self.assertIn('fixture: active node lts/*', output)
        self.assertLess(self.calls().index(self.calls('agent-setup')[0]),
                        self.calls().index(self.calls('chsh')[0]))

    def test_zsh_failures_preserve_other_shell_and_switch_only_after_valid_config(self):
        for failure in ['shell', 'config', 'framework', 'runtime', 'switch']:
            with self.subTest(failure=failure):
                self.stub('zsh-fixture', STUB)
                self.stub('zsh', STUB)
                self.dev_fixture()
                self.env.pop('FAIL_SHELL', None)
                self.env.pop('FAIL_OMZ', None)
                self.env.pop('FAIL_PYTHON', None)
                self.env.pop('FAIL_CHSH', None)
                self.env.pop('MISSING_PYTHON', None)
                if self.log.exists(): self.log.unlink()
                (self.root / 'login-shell').unlink(missing_ok=True)
                shutil.rmtree(self.home / '.oh-my-zsh', ignore_errors=True)
                self.bashrc.write_text('# untouched bash\n')
                original = '# original zsh\n'
                if failure == 'shell':
                    (self.bin / 'zsh').unlink()
                    self.env['FAIL_SHELL'] = '1'
                elif failure == 'config':
                    original += '# >>> env-setup-wsl.sh shell >>>\n'
                elif failure == 'framework': self.env['FAIL_OMZ'] = '1'
                elif failure == 'runtime':
                    self.env.update(MISSING_PYTHON='1', FAIL_PYTHON='1')
                elif failure == 'switch': self.env['FAIL_CHSH'] = '1'
                self.zshrc.write_text(original)
                output, code = self.confirm(self.choose_only({3}, shell='zsh'))
                self.assertEqual(code, 1, output)
                self.assertEqual(self.bashrc.read_text(), '# untouched bash\n')
                if failure in ('shell', 'config'):
                    self.assertFalse(self.calls('chsh'))
                    self.assertEqual(self.zshrc.read_text(), original)
                    self.assertIn('[因依赖失败跳过] 默认 shell 切换', output)
                else: self.assertTrue(self.calls('chsh'))
                if failure == 'framework':
                    self.assertNotIn('source "$ZSH/oh-my-zsh.sh"', self.zshrc.read_text())
                    self.assertIn('[失败] Oh My Zsh', output)
                    self.assertIn('compinit', self.zshrc.read_text())
                if failure == 'runtime': self.assertIn('[失败] uv/Python', output)
                if failure == 'switch': self.assertIn('[失败] 默认 shell 切换', output)
                self.assertIn('手动处理：', output)

    def test_shell_page_cancel_never_runs_installation(self):
        term = Terminal(self.env)
        self.addCleanup(term.close)
        term.expect('选择终端类型')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertFalse(self.calls('apt'))
        self.assertFalse(self.calls('chsh'))
        self.assertFalse(self.bashrc.exists())
        self.assertEqual(self.zshrc.read_text(), '# untouched zsh\n')
        self.assertEqual(term.before, termios.tcgetattr(term.master))

    def test_zsh_discovers_existing_framework_from_config_without_executing_it(self):
        self.stub('zsh', STUB)
        framework = self.home / 'custom framework'
        framework.mkdir()
        (framework / 'oh-my-zsh.sh').write_text('# framework\n')
        self.zshrc.write_text('export ZSH="$HOME/custom framework"\nZSH_THEME="agnoster"\n'
                             'source "$ZSH/oh-my-zsh.sh"\necho unsafe > "$HOME/should-not-exist"\n')
        output, code = self.confirm(self.choose_only(set(), shell='zsh'))
        self.assertEqual(code, 0, output)
        self.assertFalse([c for c in self.calls('git') if 'clone' in c])
        self.assertIn(str(framework), output)
        self.assertFalse((self.home / 'should-not-exist').exists())

    def test_zsh_rejects_unsafe_configuration_targets(self):
        self.stub('zsh', STUB)
        for kind in ['directory', 'dangling', 'shared', 'syntax']:
            with self.subTest(kind=kind):
                if self.zshrc.is_dir(): self.zshrc.rmdir()
                else: self.zshrc.unlink(missing_ok=True)
                self.bashrc.write_text('# untouched bash\n')
                if self.log.exists(): self.log.unlink()
                if kind == 'directory': self.zshrc.mkdir()
                elif kind == 'dangling': self.zshrc.symlink_to(self.home / 'missing')
                elif kind == 'shared': self.zshrc.symlink_to(self.bashrc)
                else: self.zshrc.write_text('if broken\n')
                output, code = self.confirm(self.choose_only(set(), shell='zsh'))
                self.assertEqual(code, 1, output)
                self.assertFalse(self.calls('chsh'))
                self.assertEqual(self.bashrc.read_text(), '# untouched bash\n')
                self.assertIn('[失败] Zsh 配置', output)
                if kind == 'directory': self.assertTrue(self.zshrc.is_dir())
                elif kind == 'dangling': self.assertTrue(self.zshrc.is_symlink())
                elif kind == 'shared': self.assertTrue(self.zshrc.samefile(self.bashrc))
                else: self.assertEqual(self.zshrc.read_text(), 'if broken\n')

    def test_native_clis_install_and_verify_without_touching_other_profiles(self):
        self.ai_fixture()
        (self.bin / 'codex').unlink()
        (self.bin / 'claude').unlink()
        profile = self.home / '.profile'
        profile.write_text('# keep profile\n')
        self.env['SHELL'] = '/bin/zsh'
        output, code = self.confirm(self.choose_only({5, 6}))
        self.assertEqual(code, 0, output)
        self.assertIn(['curl', '-fsSL', 'https://chatgpt.com/codex/install.sh'], self.calls())
        self.assertIn(['curl', '-fsSL', 'https://claude.ai/install.sh'], self.calls())
        self.assertIn(['codex', '--version'], self.calls())
        self.assertIn(['claude', '--version'], self.calls())
        self.assertIn('[成功] Codex CLI', output)
        self.assertIn('[成功] Claude Code', output)
        self.assertEqual(self.zshrc.read_text(), '# untouched zsh\n')
        self.assertEqual(profile.read_text(), '# keep profile\n')
        self.assertFalse([call for call in self.calls('npm') if 'install' in call])

    def test_agent_combined_entrypoint_reuses_clis_and_reports_real_exit(self):
        for status in (0, 73):
            with self.subTest(status=status):
                self.ai_fixture()
                self.env['AGENT_EXIT'] = str(status)
                output, code = self.confirm(self.choose_only({7}))
                self.assertEqual(code, int(status != 0), output)
                self.assertIn(['agent-setup', '--agent', '--skill'], self.calls())
                for label in ['nvm/Node.js', 'Codex CLI', 'Claude Code']:
                    self.assertIn('安装组件：' + label + '（自动补齐）', output)
                self.assertIn('fixture: raw agent/skill log', output)
                self.assertIn(('[成功]' if status == 0 else '[失败]') + ' Agent/Skill 配置', output)
                self.assertTrue(self.calls('chsh'))
                self.assertFalse(self.calls('curl'))
                if status:
                    self.assertIn('agent-setup.sh --agent --skill', output)
                    self.assertIn('失败（退出码 73）', output)

    def test_usable_cli_gets_path_even_when_updater_install_fails(self):
        self.ai_fixture()
        local_bin = self.home / '.local/bin'
        local_bin.mkdir(parents=True)
        shutil.copy2(self.bin / 'codex', local_bin / 'codex')
        (self.bin / 'codex').unlink()
        self.stub('install', 'import sys; sys.exit(64)')
        output, code = self.confirm(self.choose_only({5}))
        self.assertEqual(code, 1, output)
        self.assertIn('[成功] Codex CLI', output)
        self.assertIn('export PATH="$HOME/.local/bin:$PATH"', self.bashrc.read_text())

    def test_agent_dependency_failures_skip_delegate_and_keep_shell_switch(self):
        self.ai_fixture()
        for failure in ['FAIL_CODEX', 'FAIL_CLAUDE', 'NVM_ERROR']:
            with self.subTest(failure=failure):
                self.env[failure] = '1'
                self.log.write_text('')
                output, code = self.confirm(self.choose_only({7}))
                self.assertEqual(code, 1, output)
                self.assertIn('[因依赖失败跳过] Agent/Skill 配置', output)
                self.assertFalse(self.calls('agent-setup'))
                self.assertIn('[成功] 默认 shell 切换', output)
                self.assertIn('手动处理：', output)
                self.env.pop(failure)

    def test_native_download_failure_continues_independent_cli_and_preserves_config(self):
        self.ai_fixture()
        (self.bin / 'codex').unlink()
        (self.bin / 'claude').unlink()
        self.env['FAIL_CODEX_DOWNLOAD'] = '1'
        self.bashrc.write_text('# user settings\n')
        output, code = self.confirm(self.choose_only({5, 6}))
        self.assertEqual(code, 1, output)
        self.assertIn('[失败] Codex CLI', output)
        self.assertIn('[成功] Claude Code', output)
        self.assertIn('[成功] 默认 shell 切换', output)
        self.assertIn('# user settings', self.bashrc.read_text())
        self.assertEqual(self.zshrc.read_text(), '# untouched zsh\n')

    def test_failed_system_dependency_skips_missing_clis_and_delegate(self):
        self.ai_fixture()
        for name in ['curl', 'codex', 'claude']:
            (self.bin / name).unlink()
        self.env['FAIL_UPDATE'] = '1'
        output, code = self.confirm(self.choose_only({7}))
        self.assertEqual(code, 1, output)
        for label in ['Codex CLI', 'Claude Code', 'Agent/Skill 配置']:
            self.assertIn('[因依赖失败跳过] ' + label, output)
        self.assertIn('[成功] nvm/Node.js', output)
        self.assertFalse(self.calls('curl'))
        self.assertFalse(self.calls('agent-setup'))
        self.assertTrue(self.calls('chsh'))

    def test_agent_uses_requested_node_and_defaults_reuse_all_components(self):
        self.ai_fixture()
        self.env['NODE_VERSION'] = '22'
        term = self.terminal()
        output, code = self.confirm(term)
        self.assertEqual(code, 0, output)
        self.assertIn('fixture: active node 22', output)
        self.assertIn('[成功] Agent/Skill 配置', output)
        self.assertFalse(self.calls('curl'))

    def test_agent_deselection_retains_explicit_shared_dependencies(self):
        self.ai_fixture()
        term = self.choose_only({4, 5, 7})
        term.send(b'\x1b[B' * 7 + b' ')
        term.send(b'\r')
        term.expect('确认执行')
        plan = re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', term.output.decode()).split('安装计划')[-1]
        self.assertIn('安装组件：nvm/Node.js（手动选择）', plan)
        self.assertIn('安装组件：Codex CLI（手动选择）', plan)
        self.assertNotIn('安装组件：Claude Code', plan)
        self.assertNotIn('安装组件：Agent/Skill', plan)
        term.send(b'n\r')
        self.assertEqual(term.finish(), 0)

    def choose_only(self, chosen, shell="bash"):
        term = self.terminal(shell)
        # Reset in dependency order, then express only the requested selections.
        term.send(b'\x1b[B' * 7)
        for row in range(7, 0, -1):
            term.send(b' \x1b[A')
        term.send(b' ')
        focus = 0
        for row in sorted(chosen):
            term.send(b'\x1b[B' * (row - focus) + b' ')
            focus = row
        term.send(b'\x1b[A' * focus)
        return term

    def confirm(self, term):
        term.send(b'\r')
        term.expect('确认执行')
        term.send(b'y\r')
        term.expect('安装结果')
        code = term.finish()
        return re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', term.output.decode()), code

    def test_ai_components_default_selected(self):
        term = self.terminal()
        term.expect('[x] Codex CLI')
        term.expect('[x] Claude Code')
        term.expect('[x] Agent/Skill 配置')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)

    def test_agent_selection_pulls_clis_node_and_cascades_on_dependency_cancel(self):
        self.dev_fixture()
        term = self.choose_only(set())
        term.send(b'\x1b[B' * 7 + b' ')
        term.expect('[x] nvm/Node.js')
        term.expect('自动补齐')
        term.expect('[x] Codex CLI')
        term.expect('[x] Claude Code')
        term.send(b'\x1b[A' * 2 + b' ')
        term.expect('连带取消 Agent/Skill 配置')
        term.send(b'\r')
        term.expect('确认执行')
        plan = term.output.decode().split('安装计划')[-1]
        self.assertNotIn('安装组件：', plan)
        term.send(b'n\r')
        self.assertEqual(term.finish(), 0)

    def test_requested_versions_installed_and_activated_with_profiles_untouched(self):
        self.dev_fixture()
        (self.bin / 'uv').unlink()
        (self.home / '.nvm/nvm.sh').unlink()
        self.env.update(PYTHON_VERSION='3.13', NODE_VERSION='22', MISSING_NODE='1', MISSING_PYTHON='1')
        profile = self.home / '.profile'
        profile.write_text('# keep profile\n')
        output, code = self.confirm(self.choose_only({3, 4}))
        self.assertEqual(code, 0, output)
        self.assertIn(['uv', 'python', 'install', '3.13'], self.calls())
        self.assertIn(['nvm', 'install', '22'], self.calls())
        self.assertIn(['nvm', 'alias', 'default', '22'], self.calls())
        self.assertIn(['nvm', 'use', '22'], self.calls())
        self.assertEqual(profile.read_text(), '# keep profile\n')
        self.assertEqual(self.zshrc.read_text(), '# untouched zsh\n')
        self.assertIn('NVM_DIR', self.bashrc.read_text())

    def test_existing_brew_shellenv_exposes_installed_eza_without_reinstall(self):
        self.dev_fixture()
        (self.bin / 'eza').unlink()
        cellar = self.home / 'cellar bin'
        cellar.mkdir()
        executable = cellar / 'eza'
        executable.write_bytes((self.bin / 'eza-fixture').read_bytes())
        executable.chmod(0o755)
        self.stub('brew', 'import sys\nif sys.argv[1] == "shellenv": print(' + repr('export PATH="' + str(cellar) + ':$PATH"') + ')\nelse: print("brew fixture")\n')
        output, code = self.confirm(self.choose_only({1}))
        self.assertEqual(code, 0, output)
        self.assertIn('alias ls=', self.bashrc.read_text())

    def test_shared_dependency_survives_until_last_request_and_cascades_on_cancel(self):
        self.dev_fixture()
        (self.bin / 'curl').unlink()
        (self.bin / 'uv').unlink()
        (self.bin / 'brew').unlink()
        term = self.choose_only(set())
        term.send(b'\x1b[B ')
        term.expect('自动补齐')
        term.send(b'\x1b[B\x1b[B ')
        term.expect('> [x] uv/Python')
        term.send(b'\x1b[A\x1b[A ')
        term.expect('[x] 系统基础包')
        term.expect('> [ ] Homebrew/eza')
        term.send(b'\x1b[A ')
        term.expect('连带取消 uv/Python')
        term.send(b'\x1b[B\x1b[B\x1b[B ')
        term.expect('自动补齐')
        term.send(b' ')
        term.expect('[ ] 系统基础包')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertFalse(self.calls('apt'))
        self.assertFalse(self.calls('curl'))

    def test_missing_bootstrap_dependencies_are_installed_before_download(self):
        self.dev_fixture()
        (self.bin / 'curl').unlink()
        (self.bin / 'uv').unlink()
        term = self.choose_only(set())
        term.send(b'\x1b[B' * 3 + b' ')
        output, code = self.confirm(term)
        self.assertEqual(code, 0, output)
        self.assertIn('自动补齐', output)
        calls = self.calls()
        package_install = next(call for call in calls if call[:3] == ['apt', 'install', '-y'])
        self.assertLess(calls.index(package_install), calls.index(self.calls('curl')[0]))
        self.assertIn('export PATH="$HOME/.local/bin:$PATH"', self.bashrc.read_text())

    def test_failed_dependency_skips_download_but_continues_existing_runtime(self):
        self.dev_fixture()
        (self.bin / 'curl').unlink()
        (self.bin / 'uv').unlink()
        self.env['FAIL_UPDATE'] = '1'
        term = self.choose_only(set())
        term.send(b'\x1b[B' * 3 + b' ' + b'\x1b[B ')
        output, code = self.confirm(term)
        self.assertEqual(code, 1, output)
        self.assertIn('[因依赖失败跳过] uv/Python', output)
        self.assertIn('[成功] nvm/Node.js', output)
        self.assertFalse(self.calls('curl'))
        self.assertTrue(self.calls('chsh'))

    def test_lazygit_apt_and_brew_fallback_paths_are_reported_in_plan(self):
        self.dev_fixture()
        (self.bin / 'lazygit').unlink()
        output, code = self.confirm(self.choose_only({2}))
        self.assertEqual(code, 0, output)
        self.assertIn('Homebrew', output)
        self.assertIn(['apt', 'install', '-y', 'lazygit'], self.calls())
        self.assertNotIn(['brew', 'install', 'lazygit'], self.calls())
        (self.bin / 'lazygit').unlink()
        (self.bin / 'brew').unlink()
        self.env['FAIL_LAZY_APT'] = '1'
        output, code = self.confirm(self.choose_only({0, 2}))
        self.assertEqual(code, 0, output)
        self.assertIn(['brew', 'install', 'lazygit'], self.calls())
        self.assertTrue(any('Homebrew' in c[-1] for c in self.calls('curl')))
        self.assertIn('brew shellenv', self.bashrc.read_text())
        self.assertNotIn('alias ls=', self.bashrc.read_text())

    def test_runtime_failure_retains_existing_init_and_never_adds_failed_init(self):
        self.dev_fixture()
        self.env.update(MISSING_NODE='1', FAIL_NODE='1', MISSING_PYTHON='1', FAIL_PYTHON='1')
        output, code = self.confirm(self.choose_only({3, 4}))
        self.assertEqual(code, 1, output)
        self.assertIn('[失败] uv/Python', output)
        self.assertIn('[失败] nvm/Node.js', output)
        self.assertNotIn('NVM_DIR', self.bashrc.read_text())
        self.assertNotIn(['nvm', 'use', 'lts/*'], self.calls())
        original = self.bashrc.read_text().replace('# 目标 shell', 'export KEEP_INIT=1\n# 目标 shell')
        self.bashrc.write_text(original)
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 1, output)
        self.assertIn('export KEEP_INIT=1', self.bashrc.read_text())
        self.assertNotIn('NVM_DIR', self.bashrc.read_text())
        self.assertTrue(self.calls('chsh'))

    def test_installed_node_request_is_activated_and_other_nvm_errors_propagate(self):
        self.dev_fixture()
        self.env['NODE_VERSION'] = '20'
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 0, output)
        self.assertIn(['nvm', 'version', '20'], self.calls())
        self.assertIn(['nvm', 'use', '20'], self.calls())
        self.assertIn(['nvm', 'alias', 'default', '20'], self.calls())
        self.assertIn('node: v20', output.split('可用工具版本')[-1])
        reopened = subprocess.run(['/bin/bash', '--noprofile', '--rcfile', str(self.bashrc),
                                   '-ic', 'node --version'], env=self.env,
                                  capture_output=True, text=True, timeout=5)
        self.assertEqual(reopened.returncode, 0, reopened.stderr)
        self.assertIn('v20', reopened.stdout)
        self.assertFalse(any(c[:2] == ['nvm', 'install'] for c in self.calls()))
        self.env['NVM_ERROR'] = '1'
        before = len(self.calls())
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 1, output)
        self.assertFalse(any(c[:2] == ['nvm', 'install'] for c in self.calls()[before:]))

    def test_successful_development_configuration_is_idempotent(self):
        self.dev_fixture()
        first, code = self.confirm(self.choose_only({1, 3, 4}))
        self.assertEqual(code, 0, first)
        original = self.bashrc.read_bytes()
        self.bashrc.chmod(0o640)
        second, code = self.confirm(self.choose_only({1, 3, 4}))
        self.assertEqual(code, 0, second)
        self.assertEqual(self.bashrc.read_bytes(), original)
        self.assertEqual(self.bashrc.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.bashrc.read_text().count('alias ls='), 1)
        self.assertEqual(self.bashrc.read_text().count('. "$NVM_DIR/nvm.sh"'), 1)

    def test_apt_lazygit_does_not_enable_unselected_homebrew(self):
        self.dev_fixture()
        (self.bin / 'lazygit').unlink()
        output, code = self.confirm(self.choose_only({2}))
        self.assertEqual(code, 0, output)
        self.assertNotIn('brew shellenv', self.bashrc.read_text())
        self.assertNotIn('alias ls=', self.bashrc.read_text())

    def test_existing_user_nvm_initialization_is_not_loaded_twice(self):
        self.dev_fixture()
        self.bashrc.write_text('export NVM_DIR="$HOME/.nvm"\n[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" # user init\n')
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 0, output)
        self.assertEqual(self.bashrc.read_text().count('. "$NVM_DIR/nvm.sh"'), 1)
        self.assertIn('# user init', self.bashrc.read_text())

    def test_existing_local_uv_is_reused_when_not_on_inherited_path(self):
        self.dev_fixture()
        local_bin = self.home / '.local/bin'
        local_bin.mkdir(parents=True)
        (self.bin / 'uv').rename(local_bin / 'uv')
        (self.bin / 'curl').unlink()
        output, code = self.confirm(self.choose_only({3}))
        self.assertEqual(code, 0, output)
        self.assertIn('[成功] uv/Python', output)
        self.assertFalse(self.calls('curl'))
        self.assertFalse(self.calls('apt'))

    def test_existing_nvm_missing_node_pulls_missing_download_dependency(self):
        self.dev_fixture()
        (self.bin / 'curl').unlink()
        (self.bin / 'wget').unlink()
        self.env['MISSING_NODE'] = '1'
        term = self.choose_only(set())
        term.send(b'\x1b[B' * 4 + b' ')
        output, code = self.confirm(term)
        self.assertEqual(code, 0, output)
        self.assertIn('自动补齐', output)
        self.assertTrue(self.calls('apt'))
        self.assertIn(['nvm', 'install', 'lts/*'], self.calls())

    def test_successful_brew_reconfiguration_replaces_previous_managed_path(self):
        self.dev_fixture()
        output, code = self.confirm(self.choose_only({1}))
        self.assertEqual(code, 0, output)
        previous = str(self.bin / 'brew')
        alternate = self.home / 'alternate bin'
        alternate.mkdir()
        (self.bin / 'brew').rename(alternate / 'brew')
        self.env['PATH'] = str(alternate) + ':' + str(self.bin)
        output, code = self.confirm(self.choose_only({1}))
        self.assertEqual(code, 0, output)
        config = self.bashrc.read_text()
        self.assertNotIn(previous, config)
        self.assertEqual(config.count(' shellenv'), 1)
        self.assertEqual(config.count('alias ls='), 1)

    def test_failed_homebrew_dependency_skips_lazygit_and_keeps_independent_python(self):
        self.dev_fixture()
        (self.bin / 'lazygit').unlink()
        (self.bin / 'brew').unlink()
        self.env.update(NO_LAZY_APT='1', FAIL_DOWNLOAD='1')
        output, code = self.confirm(self.choose_only({2, 3}))
        self.assertEqual(code, 1, output)
        self.assertIn('[失败] Homebrew（lazygit 自动依赖）', output)
        self.assertIn('[因依赖失败跳过] lazygit', output)
        self.assertIn('[成功] uv/Python', output)
        self.assertFalse(self.calls('brew'))
        self.assertNotIn('brew shellenv', self.bashrc.read_text())
        self.assertTrue(self.calls('chsh'))

    def test_updater_install_failure_does_not_block_existing_uv(self):
        self.dev_fixture()
        self.stub('install', 'import sys\nsys.exit(60)\n')
        output, code = self.confirm(self.choose_only({3}))
        self.assertEqual(code, 1, output)
        self.assertIn('[失败] 用户工具目录 / toria-update', output)
        self.assertIn('[成功] uv/Python', output)
        self.assertFalse(self.calls('curl'))

    def test_development_components_default_selected_and_reuse_installed_tools(self):
        self.dev_fixture()
        term = self.terminal()
        term.expect('[x] Homebrew/eza')
        term.expect('[x] lazygit')
        term.expect('[x] uv/Python')
        term.expect('[x] nvm/Node.js')
        term.send(b'\x1b[B' * 7 + b' \x1b[A \x1b[A ')
        term.send(b'\r')
        term.expect('确认执行')
        term.send(b'y\r')
        term.expect('安装结果')
        self.assertEqual(term.finish(), 0, term.output.decode())
        config = self.bashrc.read_text()
        for expected in ['brew shellenv', 'alias ls=', 'alias la=', '.local/bin', 'NVM_DIR', 'bash_completion']:
            self.assertIn(expected, config)
        self.assertTrue((self.home / '.local/bin/toria-update').is_file())
        self.assertIn('set completion-ignore-case on', (self.home / '.inputrc').read_text())
        self.assertEqual(self.zshrc.read_text(), '# untouched zsh\n')
        self.assertFalse(self.calls('curl'))

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
        term = self.choose_only({0} if selected else set())
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
        term = self.choose_only(set())
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
        term.send(b'\x1b[B' * 8)
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
