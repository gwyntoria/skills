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

SCRIPT = Path(__file__).resolve().parents[1] / 'setup-wsl.sh'
ZSH_BINARY = shutil.which('zsh')
FISH_BINARY = shutil.which('fish')

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
elif name == 'gpg':
    Path(args[args.index('-o') + 1]).write_text('fixture-key')
elif name == 'apt-cache':
    if args[:1] == ['madison']:
        major = os.environ.get('NODE_VERSION', '24')
        if not os.environ.get('NO_NODE_CANDIDATE'):
            print('nodejs | ' + major + '.1.0-1nodesource1 | https://deb.nodesource.com/node_' + major + '.x nodistro/main amd64 Packages')
        if os.environ.get('MADISON_LARGE'):
            import signal
            signal.signal(signal.SIGPIPE, signal.SIG_DFL)
            sys.stdout.flush()
            row = ('nodejs | ' + major + '.0.0-1nodesource1 | https://deb.nodesource.com/node_' + major + '.x nodistro/main amd64 Packages\n').encode()
            for _ in range(256): os.write(1, row * 1024)
        if os.environ.get('MADISON_ERROR'): sys.exit(54)
        sys.exit(0)
    if args[-1] == '7zip' and os.environ.get('NO_7ZIP'): sys.exit(100)
    if args[-1] == 'lazygit' and os.environ.get('NO_LAZY_APT'): sys.exit(100)
    print('Package: ' + args[-1])
elif name == 'sudo':
    if os.environ.get('REQUIRE_SUDO_TTY') and not os.isatty(0): sys.exit(79)
    sys.exit(__import__('subprocess').call(args))
elif name == 'apt':
    print('fixture: apt ' + ' '.join(args), flush=True)
    if args[0] == 'update' and os.environ.get('FAIL_UPDATE'): sys.exit(41)
    if args[:2] == ['-s', 'install']:
        if os.environ.get('APT_REMOVES') or (os.environ.get('APT_REMOVES_NODE') and any(a.startswith('nodejs=') for a in args)):
            print('Remv libnode-dev [18.0]')
        sys.exit(0)
    if args[0] == 'install':
        if any(a.startswith('nodejs=') for a in args):
            if os.environ.get('FAIL_NODE'): sys.exit(55)
            directory = Path(os.environ['SYSTEM_NODE_FIXTURE'])
            for tool in ['node', 'npm']:
                target = directory / tool
                target.write_bytes((Path(os.environ['FIXTURE_BIN']) / (tool + '-fixture')).read_bytes())
                target.chmod(0o755)

        if 'zsh' in args:
            if os.environ.get('FAIL_SHELL'): sys.exit(42)
            target = Path(os.environ['FIXTURE_BIN']) / 'zsh'
            target.write_bytes(target.with_name('zsh-fixture').read_bytes()); target.chmod(0o755)
        elif 'fish' in args:
            if os.environ.get('FAIL_SHELL'): sys.exit(42)
            target = Path(os.environ['FIXTURE_BIN']) / 'fish'
            target.write_bytes(target.with_name('fish-fixture').read_bytes()); target.chmod(0o755)
        elif 'bash' in args:
            if os.environ.get('FAIL_SHELL'): sys.exit(42)
            target = Path(os.environ['FIXTURE_BIN']) / 'bash'
            if not target.exists(): target.symlink_to('/bin/bash')
        elif 'fzf' in args and os.environ.get('FAIL_FZF'): sys.exit(74)
        elif 'lazygit' in args:
            if os.environ.get('FAIL_LAZY_APT'): sys.exit(56)
            target = Path(os.environ['FIXTURE_BIN']) / 'lazygit'
            target.write_bytes((Path(os.environ['FIXTURE_BIN']) / 'lazygit-fixture').read_bytes())
            target.chmod(0o755)
        elif os.environ.get('FAIL_PACKAGES'): sys.exit(43)
        state = Path(os.environ['PACKAGE_STATE'])
        old = state.read_text() if state.exists() else ''
        state.write_text(old + '\n'.join(a for a in args[1:] if not a.startswith('-')) + '\n')
        for name in ['curl', 'git', 'make', 'fzf']:
            target = Path(os.environ['FIXTURE_BIN']) / name
            fixture = target.with_name(name + '-fixture')
            if name in args and not target.exists() and fixture.exists():
                target.write_bytes(fixture.read_bytes()); target.chmod(0o755)
elif name == 'chsh':
    if os.environ.get('FAIL_CHSH'): sys.exit(44)
    if not os.environ.get('UNCHANGED_SHELL'):
        Path(os.environ['SHELL_STATE']).write_text(args[1])
elif name == 'starship':
    if os.environ.get('FAIL_STARSHIP'): sys.exit(81)
    if args[:1] == ['init']:
        print("printf '%s\\n' starship-loaded >> \"$HOME/prompt-loads\"")
    else: print('starship fixture version')
elif name == 'wslpath':
    print(r'C:\fixture dir')
elif name == 'fzf':
    if args == ['--help']: print('--fish --bash')
    elif args == ['--fish']: print('set -g FIXTURE_FZF_LOADED 1')
    elif args == ['--bash']: print('export FIXTURE_FZF_LOADED=1')
    else: print('0.60.0')
elif name in ('7zz', '7z'):
    if os.environ.get('FAIL_7ZIP'): sys.exit(45)
    print('7-Zip fixture')
elif name == 'node':
    if args[:1] == ['-e']:
        for package, info in json.load(sys.stdin).get('dependencies', {}).items(): print(package + '@' + info['version'])
        sys.exit(0)
    print('v' + os.environ.get('NODE_VERSION', '24') + '.1.0')
elif name == 'npm':
    config = Path(os.environ['HOME']) / '.npmrc'
    if args[:3] == ['config', 'get', 'prefix']:
        prefix = os.environ.get('NPM_CONFIG_PREFIX', '/usr')
        if config.exists():
            for line in config.read_text().splitlines():
                if line.startswith('prefix='): prefix = line[7:]
        print(prefix)
    elif args[:3] == ['config', 'set', 'prefix']:
        if os.environ.get('FAIL_NPM_CONFIG'): sys.exit(61)
        lines = config.read_text().splitlines() if config.exists() else []
        config.write_text('\n'.join(l for l in lines if not l.startswith('prefix=')) + '\nprefix=' + args[3] + '\n')
    elif args[:1] == ['ls']: print(json.dumps({'dependencies': {'old-tool': {'version': '1.2.3'}}}))
    else: print('9.2.0')
elif name in ('brew', 'eza', 'lazygit', 'uv', 'git'):
    if name == 'git' and args[:1] == ['clone']:
        if os.environ.get('FAIL_OMZ'): sys.exit(71)
        if os.environ.get('FAIL_PLUGIN') == Path(args[-1]).name: sys.exit(72)
        target = Path(args[-1]); target.mkdir(parents=True)
        if 'ohmyzsh/ohmyzsh' in args[-2]:
            (target / 'oh-my-zsh.sh').write_text(
                'for p in $plugins; do\n'
                '  for base in "${ZSH_CUSTOM:-$ZSH/custom}" "$ZSH"; do\n'
                '    if [[ -f "$base/plugins/$p/$p.plugin.zsh" ]]; then\n'
                '      source "$base/plugins/$p/$p.plugin.zsh"; break\n'
                '    fi\n'
                '  done\n'
                'done\n')
            for plugin in ['git', 'copypath', 'z', 'fzf', 'nvm', 'extract']:
                directory = target / 'plugins' / plugin
                directory.mkdir(parents=True)
                body = 'print ' + plugin + ' >> "$HOME/plugin-loads"\n'
                if plugin == 'nvm': body += 'FIXTURE_NVM_LOADER=plugin\nexport NVM_DIR="${NVM_DIR:-$HOME/.nvm}"\n(( $+functions[nvm] )) || source "$NVM_DIR/nvm.sh"\n'
                (directory / (plugin + '.plugin.zsh')).write_text(body)
        else:
            plugin = target.name
            (target / (plugin + '.plugin.zsh')).write_text('print ' + plugin + ' >> "$HOME/plugin-loads"\n')
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
        if args[-1] == 'fish': print('set -gx PATH "' + os.environ['FIXTURE_BIN'] + '" $PATH')
        else: print('export PATH="' + os.environ['FIXTURE_BIN'] + ':$PATH"')
    else: print(name + ' fixture version')
elif name == 'nvm':
    if args[:2] == ['alias', 'default']:
        Path(os.environ['HOME'], '.nvm', 'default-version').write_text(args[2])
    if args[0] == 'version' and os.environ.get('NVM_ERROR'): sys.exit(54)
    if args[0] == 'version' and os.environ.get('MISSING_NODE'):
        print('N/A'); sys.exit(3)
    if args[0] == 'install' and os.environ.get('FAIL_NODE'): sys.exit(55)
    print('v24.0.0')
elif name == 'fish':
    if args == ['--version']: print('fish fixture version')
    else: os.execv(os.environ['REAL_FISH'], [os.environ['REAL_FISH']] + args)
elif name == 'zsh':
    if args == ['--version']: print('zsh fixture version')
    else: os.execv(os.environ['REAL_ZSH'], [os.environ['REAL_ZSH']] + args)
elif name == 'curl':
    url = next(a for a in args if a.startswith('https://'))
    if os.environ.get('FAIL_DOWNLOAD'): sys.exit(51)
    if 'nodesource.com' in url:
        Path(args[args.index('-o') + 1]).write_text('fixture-key')
    elif 'starship.rs' in url:
        print('mkdir -p "$HOME/.local/bin"')
        print('cp "$FIXTURE_BIN/starship-fixture" "$HOME/.local/bin/starship"')
    elif 'astral.sh' in url:
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
    else: sys.exit(98)
else:
    print('UNEXPECTED external command: ' + name, file=sys.stderr)
    sys.exit(99)
'''


class Terminal:
    def __init__(self, env, command=None, cwd=None):
        self.master, slave = pty.openpty()
        self.before = termios.tcgetattr(self.master)
        self.process = subprocess.Popen(command or ['/bin/bash', env.get('WIZARD_SCRIPT', str(SCRIPT))], stdin=slave,
                                        stdout=slave, stderr=slave, env=env, cwd=cwd)
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
                     'date', 'mktemp', 'mv', 'readlink', 'rm', 'basename', 'bash', 'mkdir', 'install', 'touch', 'head', 'sh', 'env']:
            (self.bin / name).symlink_to(shutil.which(name))
        for name in ['apt', 'apt-cache', 'sudo', 'getent', 'dpkg-query', 'chsh', 'tput',
                     '7zz', 'curl', 'wget', 'brew', 'git', 'nvm', 'uv', 'gpg']:
            self.stub(name, STUB)
        self.log = self.root / 'calls.jsonl'
        self.packages = self.root / 'packages'
        self.env = dict(os.environ, EXPECTED_SHELL='/bin/bash', HOME=str(self.home), PATH=str(self.bin), TERM='xterm-256color',
                        NVM_DIR=str(self.home / '.nvm'), XDG_CONFIG_HOME=str(self.home / '.config'), REAL_ZSH=ZSH_BINARY or '', REAL_FISH=FISH_BINARY or '', CALL_LOG=str(self.log), PACKAGE_STATE=str(self.packages), FIXTURE_BIN=str(self.bin),
                        SHELL_STATE=str(self.root / 'login-shell'))
        # Mock the fixed external Homebrew location as well as PATH. The whole
        # entrypoint still runs; no installed host Homebrew can bypass the fakes.
        isolated_script = self.root / 'setup-wsl.sh'
        source = SCRIPT.read_text()
        external_path = 'HOMEBREW_BIN="/home/linuxbrew/.linuxbrew/bin/brew"'
        self.assertEqual(source.count(external_path), 1, 'Refresh the external-path fixture before running installers')
        isolated_script.write_text(source.replace(
            external_path, 'HOMEBREW_BIN=' + shlex.quote(str(self.bin / 'brew'))))
        self.system_bin = self.root / 'system-bin'
        self.system_bin.mkdir()
        source = isolated_script.read_text().replace('SYSTEM_NODE_DIR="/usr/bin"', 'SYSTEM_NODE_DIR=' + shlex.quote(str(self.system_bin)))
        for variable, basename in [('NODESOURCE_LIST', 'nodesource.list'), ('NODESOURCE_KEY', 'nodesource.gpg'), ('NODESOURCE_PIN', 'nodesource.pin')]:
            source = re.sub(r'^' + variable + r'=.*$', variable + '=' + shlex.quote(str(self.root / basename)), source, flags=re.M)
        isolated_script.write_text(source)
        self.env['SYSTEM_NODE_FIXTURE'] = str(self.system_bin)
        for tool in ['node', 'npm']:
            self.stub(tool + '-fixture', STUB)
        self.env['WIZARD_SCRIPT'] = str(isolated_script)
        self.env.pop('NO_COLOR', None)
        for key in ['ZSH', 'ZSH_CUSTOM', 'ZDOTDIR', 'NODE_VERSION', 'NPM_CONFIG_PREFIX', 'npm_config_prefix', 'NPM_CONFIG_USERCONFIG', 'npm_config_userconfig']:
            self.env.pop(key, None)
        self.bashrc = self.home / '.bashrc'
        self.zshrc = self.home / '.zshrc'
        self.zshrc.write_text('# untouched zsh\n')

    def stub(self, name, body):
        if name in ('zsh', 'zsh-fixture'):
            self.assertIsNotNone(ZSH_BINARY, 'Zsh tests require zsh on PATH; see README.md')
        if name in ('fish', 'fish-fixture'):
            self.assertIsNotNone(FISH_BINARY, 'Fish tests require fish on PATH')
        target = self.bin / name
        if target.is_symlink(): target.unlink()
        target.write_text('#!' + sys.executable + '\n' + body)
        target.chmod(0o755)

    def terminal(self, shell="bash", piped=False):
        self.env['EXPECTED_SHELL'] = '/bin/' + shell
        command = None
        if piped:
            # /dev/tty needs a controlling terminal, not merely PTY descriptors.
            pipeline = '/bin/cat ' + shlex.quote(self.env['WIZARD_SCRIPT']) + ' | /bin/bash'
            launcher = ('import os, fcntl, termios; os.setsid(); '
                        'fcntl.ioctl(0, termios.TIOCSCTTY, 0); '
                        'os.execv("/bin/bash", ["bash", "-c", ' + repr(pipeline) + '])')
            command = [sys.executable, '-c', launcher]
        term = Terminal(self.env, command=command, cwd=self.home if piped else None)
        self.addCleanup(term.close)
        term.expect('选择终端类型')
        term.send(b'\x1b[B' * {'fish': 0, 'zsh': 1, 'bash': 2}[shell] + b'\r')
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

    def test_starship_defaults_install_and_bash_hooks_preserve_user_prompt(self):
        self.stub('starship-fixture', STUB)
        self.stub('wslpath', STUB)
        self.bashrc.write_text('user_prompt() { echo user >> "$HOME/user-prompts"; }\nPROMPT_COMMAND=user_prompt\n')
        term = self.terminal()
        term.expect('[x] Starship')
        term.send(b'q')
        term.finish()
        output, code = self.confirm(self.choose_only({5}))
        self.assertEqual(code, 0, output)
        self.assertIn('[成功] Starship', output)
        self.assertEqual(self.zshrc.read_text(), '# untouched zsh\n')
        loaded = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c',
                                 'source "$HOME/.bashrc"; source "$HOME/.bashrc"; eval "$PROMPT_COMMAND"'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(loaded.returncode, 0, loaded.stderr)
        self.assertEqual((self.home / 'user-prompts').read_text().splitlines(), ['user'])
        self.assertEqual((self.home / 'prompt-loads').read_text().splitlines(), ['starship-loaded'])
        self.assertEqual(loaded.stdout.count('\x1b]9;9;C:\\fixture dir\x1b\\'), 1)
        self.assertEqual(len([c for c in self.calls('curl') if 'starship.rs' in c[-1]]), 1)
        output, code = self.confirm(self.choose_only({5}))
        self.assertEqual(code, 0, output)
        self.assertEqual(len([c for c in self.calls('curl') if 'starship.rs' in c[-1]]), 1)

    def test_starship_zsh_theme_hooks_restore_on_deselection_and_reuse(self):
        self.stub('zsh', STUB)
        self.stub('starship', STUB)
        self.stub('wslpath', STUB)
        omz = self.home / '.oh-my-zsh'
        omz.mkdir()
        (omz / 'oh-my-zsh.sh').write_text('print "theme:$ZSH_THEME" >> "$HOME/theme-loads"\n')
        self.bashrc.write_text('# keep bash\n')
        self.zshrc.write_text('export ZSH="$HOME/.oh-my-zsh"\nZSH_THEME="custom-theme"\n'
                             'user_prompt() { print user >> "$HOME/user-prompts"; }\n'
                             'precmd_functions=(user_prompt)\nsource "$ZSH/oh-my-zsh.sh"\n')
        for selected in [True, True, False]:
            output, code = self.confirm(self.choose_only({5} if selected else set(), shell='zsh'))
            self.assertEqual(code, 0, output)
            for filename in ['prompt-loads', 'theme-loads', 'user-prompts']:
                (self.home / filename).unlink(missing_ok=True)
            loaded = subprocess.run([ZSH_BINARY, '-dfc',
                                     'source "$HOME/.zshrc"; for hook in $precmd_functions; do "$hook"; done'],
                                    env=self.env, text=True, capture_output=True)
            self.assertEqual(loaded.returncode, 0, loaded.stderr)
            self.assertEqual((self.home / 'theme-loads').read_text(), 'theme:' + ('' if selected else 'custom-theme') + '\n')
            self.assertEqual((self.home / 'user-prompts').read_text(), 'user\n')
            self.assertEqual(loaded.stdout.count('\x1b]9;9;C:\\fixture dir\x1b\\'), 1)
            if selected:
                self.assertEqual((self.home / 'prompt-loads').read_text().splitlines(), ['starship-loaded'])
            else:
                self.assertFalse((self.home / 'prompt-loads').exists())
            self.assertEqual(self.bashrc.read_text(), '# keep bash\n')
        self.assertFalse([c for c in self.calls('curl') if 'starship.rs' in c[-1]])

    def test_starship_failure_keeps_prompt_and_allows_shell_switch(self):
        for shell in ['bash', 'zsh']:
            with self.subTest(shell=shell):
                if shell == 'zsh': self.stub('zsh', STUB)
                self.stub('starship', STUB)
                self.env['FAIL_STARSHIP'] = '1'
                rc = self.bashrc if shell == 'bash' else self.zshrc
                rc.write_text('ZSH_THEME="kept-theme"\n# user prompt\n')
                output, code = self.confirm(self.choose_only({5}, shell=shell))
                self.assertEqual(code, 1, output)
                self.assertIn('[失败] Starship', output)
                self.assertIn('[成功] 默认 shell 切换', output)
                self.assertIn('手动处理：', output)
                config = rc.read_text()
                self.assertIn('ZSH_THEME="kept-theme"', config)
                self.assertNotIn('starship init', config)
                self.assertNotIn('prompt-theme >>>', config)
                self.env.pop('FAIL_STARSHIP')
                output, code = self.confirm(self.choose_only({5}, shell=shell))
                self.assertEqual(code, 0, output)
                self.env['FAIL_STARSHIP'] = '1'
                output, code = self.confirm(self.choose_only({5}, shell=shell))
                self.assertEqual(code, 1, output)
                self.assertIn('starship init ' + shell, rc.read_text())
                if shell == 'zsh': self.assertIn('prompt-theme >>>', rc.read_text())
                self.env.pop('FAIL_STARSHIP')

    def test_starship_hook_preserves_bash_prompt_arrays_and_user_callback(self):
        self.stub('starship', STUB)
        self.stub('wslpath', STUB)
        self.bashrc.write_text("PROMPT_COMMAND=('echo first' 'echo second')\n"
                              'starship_precmd_user_func=user_callback\n')
        output, code = self.confirm(self.choose_only({5}))
        self.assertEqual(code, 0, output)
        loaded = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c',
                                 'source "$HOME/.bashrc"; source "$HOME/.bashrc"; '
                                 'for cmd in "${PROMPT_COMMAND[@]}"; do eval "$cmd"; done; '
                                 'printf "callback:%s" "$starship_precmd_user_func"'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(loaded.returncode, 0, loaded.stderr)
        self.assertIn('first\nsecond\n', loaded.stdout)
        self.assertIn('callback:user_callback', loaded.stdout)
        self.assertEqual(loaded.stdout.count('\x1b]9;9;C:\\fixture dir\x1b\\'), 1)

    def test_starship_missing_download_dependency_cascades_and_skips_on_failure(self):
        (self.bin / 'curl').unlink()
        self.env['FAIL_UPDATE'] = '1'
        term = self.choose_only({5})
        term.send(b'\r')
        term.expect('确认执行')
        plan = re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', term.output.decode()).split('安装计划')[-1]
        self.assertIn('安装组件：系统基础包（自动补齐）', plan)
        self.assertIn('安装组件：Starship（手动选择）', plan)
        term.send(b'y\r')
        term.expect('安装结果')
        self.assertEqual(term.finish(), 1)
        self.assertIn('[因依赖失败跳过] Starship', re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', term.output.decode()))
        self.assertNotIn('starship init', self.bashrc.read_text())
        self.assertTrue(self.calls('chsh'))
        self.assertFalse(self.calls('curl'))
        term = self.choose_only({5})
        term.send(b' \r')
        term.expect('确认执行')
        plan = re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', term.output.decode()).split('安装计划')[-1]
        self.assertNotIn('安装组件：Starship', plan)
        term.send(b'n\r')
        self.assertEqual(term.finish(), 0)

    def test_starship_configuration_guards_symlinks_permissions_and_malformed_hooks(self):
        self.stub('starship', STUB)
        target = self.home / 'custom rc'
        target.write_text('# custom\n')
        target.chmod(0o600)
        self.bashrc.symlink_to(target)
        output, code = self.confirm(self.choose_only({5}))
        self.assertEqual(code, 0, output)
        self.assertTrue(self.bashrc.is_symlink())
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertIn('恢复命令：', output)
        invalid = target.read_text() + '# >>> env-setup-wsl.sh Windows Terminal CWD hook >>>\n'
        target.write_text(invalid)
        output, code = self.confirm(self.choose_only({5}))
        self.assertEqual(code, 1, output)
        self.assertEqual(target.read_text(), invalid)
        self.assertIn('[失败] Bash 配置', output)
        self.assertIn('[因依赖失败跳过] 默认 shell 切换', output)
        self.assertFalse(list(self.home.glob('.*.tmp.*')))
        self.assertEqual(self.zshrc.read_text(), '# untouched zsh\n')

    def test_starship_legacy_hook_migrates_without_duplicate_notifications(self):
        self.stub('starship', STUB)
        self.stub('wslpath', STUB)
        self.bashrc.write_text('# >>> env-setup-wsl.sh Windows Terminal CWD hook >>>\n'
                              'function __wt_update_cwd() { echo old; }\n'
                              'starship_precmd_user_func="__wt_update_cwd"\n'
                              'eval "$(starship init bash)"\n'
                              '# <<< env-setup-wsl.sh Windows Terminal CWD hook <<<\n')
        output, code = self.confirm(self.choose_only({5}))
        self.assertEqual(code, 0, output)
        loaded = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c',
                                 'source "$HOME/.bashrc"; eval "$PROMPT_COMMAND"'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(loaded.returncode, 0, loaded.stderr)
        self.assertEqual((self.home / 'prompt-loads').read_text().splitlines(), ['starship-loaded'])
        self.assertNotIn('__wt_update_cwd', self.bashrc.read_text())
        self.assertEqual(loaded.stdout.count('\x1b]9;9;C:\\fixture dir\x1b\\'), 1)

    def test_starship_bash_hook_accepts_user_command_terminators_and_comments(self):
        self.stub('wslpath', STUB)
        for command in ['user_prompt;', 'user_prompt # keep comment']:
            with self.subTest(command=command):
                self.bashrc.write_text('user_prompt() { echo user; }\nPROMPT_COMMAND=' + shlex.quote(command) + '\n')
                output, code = self.confirm(self.choose_only(set()))
                self.assertEqual(code, 0, output)
                loaded = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c',
                                         'source "$HOME/.bashrc"; source "$HOME/.bashrc"; eval "$PROMPT_COMMAND"'],
                                        env=self.env, text=True, capture_output=True)
                self.assertEqual(loaded.returncode, 0, loaded.stderr)
                self.assertEqual(loaded.stdout.count('user\n'), 1)
                self.assertEqual(loaded.stdout.count('\x1b]9;9;C:\\fixture dir\x1b\\'), 1)

    def test_starship_deselection_migrates_legacy_owned_initialization(self):
        self.bashrc.write_text('# >>> env-setup-wsl.sh Windows Terminal CWD hook >>>\n'
                              'function __wt_update_cwd() { echo old; }\n'
                              'starship_precmd_user_func="__wt_update_cwd"\n'
                              'eval "$(starship init bash)"\n'
                              '# <<< env-setup-wsl.sh Windows Terminal CWD hook <<<\n')
        output, code = self.confirm(self.choose_only(set()))
        self.assertEqual(code, 0, output)
        self.assertNotIn('starship init', self.bashrc.read_text())
        loaded = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c',
                                 'source "$HOME/.bashrc"; eval "$PROMPT_COMMAND"'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(loaded.returncode, 0, loaded.stderr)

    def test_zsh_selected_plugins_install_reuse_and_initialize_nvm_once(self):
        self.dev_fixture()
        self.stub('zsh', STUB)
        self.stub('fzf-fixture', STUB)
        self.zshrc.unlink()
        names = ['git', 'copypath', 'z', 'fzf', 'zsh-autosuggestions',
                 'zsh-syntax-highlighting', 'extract']
        output, code = self.confirm(self.choose_only(set(), shell='zsh', plugins=names))
        self.assertEqual(code, 0, output)
        self.assertNotIn('安装组件：Node.js/npm（apt）', output)
        self.assertIn('fzf 程序（自动补齐）', output)
        self.assertIn(['apt', 'install', '-y', 'fzf'], self.calls())
        for name in names: self.assertIn('[成功] Zsh 插件 ' + name, output)
        clones = [c for c in self.calls('git') if 'clone' in c]
        self.assertEqual(len(clones), 3)
        self.assertTrue(any('zsh-users/zsh-autosuggestions' in str(c) for c in clones))
        self.assertTrue(any('zsh-users/zsh-syntax-highlighting' in str(c) for c in clones))
        nvm = self.home / '.nvm/nvm.sh'
        nvm.write_text('echo "${FIXTURE_NVM_LOADER:-standalone}" >> "$HOME/nvm-loads"\n' + nvm.read_text())
        result = subprocess.run([ZSH_BINARY, '-dfc', 'source "$HOME/.zshrc"; print -l -- $plugins'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.home / 'nvm-loads').exists())
        self.assertEqual((self.home / 'plugin-loads').read_text().splitlines(),
                         ['git', 'copypath', 'z', 'fzf', 'zsh-autosuggestions', 'extract', 'zsh-syntax-highlighting'])
        before = self.zshrc.read_bytes()
        output, code = self.confirm(self.choose_only(set(), shell='zsh', plugins=names))
        self.assertEqual(code, 0, output)
        self.assertEqual(self.zshrc.read_bytes(), before)
        self.assertEqual(len([c for c in self.calls('git') if 'clone' in c]), 3)

    def test_zsh_plugin_deselection_keeps_custom_files_and_unlisted_plugins(self):
        self.dev_fixture()
        self.stub('zsh', STUB)
        # Obtain the fixture framework through the public installer first.
        output, code = self.confirm(self.choose_only(set(), shell='zsh'))
        self.assertEqual(code, 0, output)
        custom = self.home / 'my plugins'
        for name in ['custom', 'extract', 'zsh-autosuggestions']:
            directory = custom / 'plugins' / name
            directory.mkdir(parents=True)
            (directory / (name + '.plugin.zsh')).write_text('print ' + name + ' >> "$HOME/plugin-loads"\n')
        self.zshrc.write_text('export ZSH="$HOME/.oh-my-zsh"\nexport ZSH_CUSTOM="$HOME/my plugins"\n'
                             'ZSH_THEME="agnoster"\nplugins=(extract custom zsh-autosuggestions)\n'
                             'source "$ZSH/oh-my-zsh.sh"\n')
        original_files = {str(p): p.read_bytes() for p in custom.rglob('*.zsh')}
        clone_count = len([c for c in self.calls('git') if 'clone' in c])
        output, code = self.confirm(self.choose_only(set(), shell='zsh', plugins=['zsh-autosuggestions']))
        self.assertEqual(code, 0, output)
        self.assertIn('[x] zsh-autosuggestions 已安装', output)
        self.assertIn('[用户未选择] Zsh 插件 extract', output)
        self.assertEqual(len([c for c in self.calls('git') if 'clone' in c]), clone_count)
        self.assertEqual({str(p): p.read_bytes() for p in custom.rglob('*.zsh')}, original_files)
        result = subprocess.run([ZSH_BINARY, '-dfc', 'source "$HOME/.zshrc"; print -l -- $plugins'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['custom', 'zsh-autosuggestions'])
        self.assertEqual((self.home / 'plugin-loads').read_text(), 'custom\nzsh-autosuggestions\n')
        self.assertIn('ZSH_THEME="agnoster"', self.zshrc.read_text())

    def test_zsh_plugin_failures_skip_dependents_and_continue_independent_plugins(self):
        self.dev_fixture()
        self.stub('zsh', STUB)
        self.stub('fzf-fixture', STUB)
        self.env.update(FAIL_PLUGIN='zsh-autosuggestions', FAIL_FZF='1')
        output, code = self.confirm(self.choose_only(set(), shell='zsh',
                                      plugins=['fzf', 'zsh-autosuggestions', 'extract']))
        self.assertEqual(code, 1, output)
        self.assertIn('[失败] fzf', output)
        self.assertIn('[因依赖失败跳过] Zsh 插件 fzf', output)
        self.assertIn('[失败] Zsh 插件 zsh-autosuggestions', output)
        self.assertIn('[成功] Zsh 插件 extract', output)
        self.assertIn('[成功] 默认 shell 切换', output)
        self.assertIn('手动处理：', output)
        result = subprocess.run([ZSH_BINARY, '-dfc', 'source "$HOME/.zshrc"; print -l -- $plugins'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['extract'])
        self.assertEqual((self.home / 'plugin-loads').read_text(), 'extract\n')
        # Previously configured selected plugins survive a failed retry.
        self.env.pop('FAIL_PLUGIN')
        output, code = self.confirm(self.choose_only(set(), shell='zsh', plugins=['zsh-autosuggestions']))
        self.assertEqual(code, 0, output)
        plugin = self.home / '.oh-my-zsh/custom/plugins/zsh-autosuggestions/zsh-autosuggestions.plugin.zsh'
        plugin.unlink()
        plugin.parent.rmdir()
        self.env['FAIL_PLUGIN'] = 'zsh-autosuggestions'
        output, code = self.confirm(self.choose_only(set(), shell='zsh', plugins=['zsh-autosuggestions']))
        self.assertEqual(code, 1, output)
        self.assertIn('plugins+=(zsh-autosuggestions)', self.zshrc.read_text())

    def test_zsh_missing_bundled_plugin_is_recovered_without_replacing_framework(self):
        self.stub('zsh', STUB)
        framework = self.home / '.oh-my-zsh'
        framework.mkdir()
        original = '# existing custom framework\n'
        (framework / 'oh-my-zsh.sh').write_text(original)
        output, code = self.confirm(self.choose_only(set(), shell='zsh', plugins=['extract']))
        self.assertEqual(code, 0, output)
        self.assertEqual((framework / 'oh-my-zsh.sh').read_text(), original)
        self.assertTrue((framework / 'custom/plugins/extract/extract.plugin.zsh').is_file())
        self.assertIn('[成功] Zsh 插件 extract', output)
        self.assertFalse(self.calls('apt'))
        clone = [c for c in self.calls('git') if 'clone' in c]
        self.assertEqual(len(clone), 1)
        self.assertFalse(Path(clone[0][-1]).exists(), 'Temporary clone must be removed')

    def test_zsh_plugin_staging_failure_preserves_config_and_cleans_temporary_files(self):
        self.stub('zsh', STUB)
        original = self.zshrc.read_text()
        self.stub('mktemp', 'import os, sys\n'
                  'if any(".stage." in arg for arg in sys.argv): sys.exit(78)\n'
                  'os.execv(' + repr(shutil.which('mktemp')) + ', ["mktemp"] + sys.argv[1:])\n')
        output, code = self.confirm(self.choose_only(set(), shell='zsh'))
        self.assertEqual(code, 1, output)
        self.assertEqual(self.zshrc.read_text(), original)
        self.assertFalse(self.calls('chsh'))
        self.assertFalse(list(self.home.glob('.*.tmp.*')))

    def test_zsh_plugin_choices_apply_before_conditional_framework_sources(self):
        self.stub('zsh', STUB)
        output, code = self.confirm(self.choose_only(set(), shell='zsh'))
        self.assertEqual(code, 0, output)
        for loader in ['[ -s "$ZSH/oh-my-zsh.sh" ] && source "$ZSH/oh-my-zsh.sh"',
                       '[ -s "$ZSH/oh-my-zsh.sh" ] && \\. "$ZSH/oh-my-zsh.sh"']:
            with self.subTest(loader=loader):
                self.zshrc.write_text('export ZSH="$HOME/.oh-my-zsh"\nplugins=(extract)\n' + loader + '\n')
                output, code = self.confirm(self.choose_only(set(), shell='zsh', plugins=['git']))
                self.assertEqual(code, 0, output)
                (self.home / 'plugin-loads').unlink(missing_ok=True)
                result = subprocess.run([ZSH_BINARY, '-dfc', 'source "$HOME/.zshrc"; print -l -- $plugins'],
                                        env=self.env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), ['git'])
                self.assertEqual((self.home / 'plugin-loads').read_text(), 'git\n')

    def test_zsh_plugin_page_has_exact_defaults_and_loadable_status(self):
        self.stub('zsh', STUB)
        framework = self.home / '.oh-my-zsh'
        (framework / 'plugins/git').mkdir(parents=True)
        (framework / 'oh-my-zsh.sh').write_text('# framework\n')
        (framework / 'plugins/git/git.plugin.zsh').write_text('# git\n')
        (framework / 'plugins/copypath').mkdir()
        (framework / 'plugins/copypath/_copypath').write_text('# completion\n')
        (framework / 'plugins/extract').mkdir()
        self.zshrc.write_text('plugins=(extract imaginary)\n')
        term = self.terminal('zsh')
        term.send(b'\r')
        term.expect('选择 Zsh 插件')
        term.expect('方向键移动')
        screen = re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', term.output.decode()).split('选择 Zsh 插件')[-1]
        rows = re.findall(r'\[x\] ([^ ]+) (已安装|未安装)', screen)
        self.assertEqual(rows, [('git', '已安装'), ('copypath', '已安装'), ('z', '未安装'),
                               ('fzf', '未安装'),
                               ('zsh-autosuggestions', '未安装'), ('zsh-syntax-highlighting', '未安装'),
                               ('extract', '未安装')])
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertFalse(self.calls('apt'))
        self.assertFalse(self.calls('chsh'))

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
        for line in original.splitlines(): self.assertIn(line, config)
        self.assertEqual(config.count('oh-my-zsh.sh'), 1)
        self.assertIn('shellenv zsh', config)
        self.assertNotIn('bash_completion', config)
        self.assertTrue(self.zshrc.is_symlink())
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        self.assertEqual((self.home / 'linked zsh startup.pre-env-setup-wsl.bak').read_text(), original)
        self.assertEqual(len(list(self.home.glob('linked zsh startup.env-setup-wsl.bak-*'))), 1)
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

    def test_fish_first_default_selection_and_existing_configuration_are_preserved(self):
        self.stub('fish', STUB)
        fishrc = self.home / '.config/fish/config.fish'
        fishrc.parent.mkdir(parents=True)
        fishrc.write_text('# user fish settings\nset -g KEEP_ME yes\n')
        output, code = self.confirm(self.choose_only(set(), shell='fish'))
        self.assertEqual(code, 0, output)
        self.assertIn('set -g KEEP_ME yes', fishrc.read_text())
        subprocess.run([FISH_BINARY, '-n', str(fishrc)], check=True)
        self.assertEqual(self.zshrc.read_text(), '# untouched zsh\n')
        self.assertFalse(self.bashrc.exists())
        self.assertEqual(self.calls('chsh')[-1][2], str(self.bin / 'fish'))
        self.assertNotIn('选择 Zsh 插件', output)
        self.assertFalse([c for c in self.calls('git') if 'clone' in c])

    def test_fish_fzf_configuration_loads_and_repeated_runs_are_idempotent(self):
        self.stub('fish', STUB)
        self.stub('fzf', STUB)
        self.stub('wslpath', STUB)
        output, code = self.confirm(self.choose_only({6}, shell='fish'))
        self.assertEqual(code, 0, output)
        fishrc = self.home / '.config/fish/config.fish'
        generated = fishrc.read_bytes()
        loaded = subprocess.run([FISH_BINARY, '-i', '-c',
                                 'test "$FIXTURE_FZF_LOADED" = 1; and test "$EDITOR" = "code --wait"; and functions -q __env_setup_wsl_update_cwd'],
                                env=dict(self.env, WSL_DISTRO_NAME='Fixture'), capture_output=True, text=True)
        self.assertEqual(loaded.returncode, 0, loaded.stderr)
        output, code = self.confirm(self.choose_only({6}, shell='fish'))
        self.assertEqual(code, 0, output)
        self.assertEqual(fishrc.read_bytes(), generated)

    def test_zsh_public_fzf_deselection_cancels_plugin_dependency(self):
        self.stub('zsh', STUB)
        term = self.choose_only(set(), shell='zsh', plugins=['fzf'])
        term.send(b'b')
        term.expect('选择安装组件（Zsh）')
        term.send(b'\x1b[B' * 6 + b' ' + b'\r')
        term.expect('选择 Zsh 插件')
        term.expect('方向键移动')
        screen = re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', term.output.decode()).split('选择 Zsh 插件')[-1]
        self.assertIn('[ ] fzf', screen)
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertFalse(self.calls('apt'))

    def test_missing_fish_is_installed_and_its_config_directory_is_created(self):
        self.stub('fish-fixture', STUB)
        output, code = self.confirm(self.choose_only(set(), shell='fish'))
        self.assertEqual(code, 0, output)
        self.assertIn(['apt', 'install', '-y', 'fish'], self.calls('apt'))
        fishrc = self.home / '.config/fish/config.fish'
        self.assertTrue(fishrc.is_file())
        subprocess.run([FISH_BINARY, '-n', str(fishrc)], check=True)

    def test_failed_fish_install_does_not_write_configuration_or_switch(self):
        self.stub('fish-fixture', STUB)
        self.env['FAIL_SHELL'] = '1'
        output, code = self.confirm(self.choose_only(set(), shell='fish'))
        self.assertEqual(code, 1, output)
        self.assertFalse((self.home / '.config/fish/config.fish').exists())
        self.assertFalse(self.calls('chsh'))

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

    def choose_only(self, chosen, shell="bash", plugins=(), piped=False):
        term = self.terminal(shell, piped=piped)
        # Reset in dependency order, then express only the requested selections.
        term.send(b'\x1b[B' * 6)
        for row in range(6, 0, -1):
            term.send(b' \x1b[A')
        term.send(b' ')
        focus = 0
        for row in sorted(chosen):
            term.send(b'\x1b[B' * (row - focus) + b' ')
            focus = row
        term.send(b'\x1b[A' * focus)
        if shell == 'zsh':
            term.send(b'\r')
            term.expect('选择 Zsh 插件')
            term.expect('方向键移动')
            screen = re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', term.output.decode()).split('选择 Zsh 插件')[-1]
            states = re.findall(r'\[([ x])\] ([^ ]+) (?:已安装|未安装)', screen)
            for row, (mark, name) in enumerate(states):
                if (mark == 'x') != (name in plugins): term.send(b' ')
                term.send(b'\x1b[B')
        return term

    def confirm(self, term):
        term.send(b'\r')
        term.expect('确认执行')
        term.send(b'y\r')
        term.expect('安装结果')
        code = term.finish()
        return re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', term.output.decode()), code

    def test_node_migrates_all_shells_preserving_tools_commands_and_backups(self):
        self.dev_fixture()
        self.stub('zsh', STUB)
        self.stub('fish', STUB)
        old_nvm = self.home / '.nvm/nvm.sh'
        old_nvm.write_text('echo loaded >> "$HOME/nvm-loads"\n')
        self.bashrc.write_text('export NVM_DIR="$HOME/.nvm"\n'
                              '[ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"\n'
                              'source "$NVM_DIR/nvm.sh"; export KEEP_BASH=yes\n')
        self.zshrc.write_text('plugins=(nvm custom)\n'
                             '{ if [[ ${_ENV_SETUP_WSL_NVM_PLUGIN:-0} != 1 ]] && (( ! $+functions[nvm] )); then source "$NVM_DIR/nvm.sh"; fi; }; export KEEP_ZSH=yes\n')
        fishrc = self.home / '.config/fish/config.fish'
        fishrc.parent.mkdir(parents=True)
        fishrc.write_text('# >>> env-setup-wsl.sh nvm >>>\n'
                          'if status is-interactive\n    nvm use --silent default\nend\n'
                          '# <<< env-setup-wsl.sh nvm <<<\nset -gx KEEP_FISH yes\n')
        functions = fishrc.parent / 'functions'
        functions.mkdir()
        (functions / 'bass.fish').write_text('# user bass\n')
        self.zshrc.chmod(0o640)
        originals = {p: p.read_bytes() for p in [self.bashrc, self.zshrc, fishrc]}
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 0, output)
        self.assertFalse(self.calls('nvm'))
        for path, original in originals.items():
            self.assertEqual(path.with_name(path.name + '.pre-env-setup-wsl.bak').read_bytes(), original)
        for binary, script in [(str(self.bin / 'bash'), 'source "$HOME/.bashrc"; echo "$KEEP_BASH"'),
                               (ZSH_BINARY, 'source "$HOME/.zshrc"; echo "$KEEP_ZSH"'),
                               (FISH_BINARY, 'source "$HOME/.config/fish/config.fish"; echo "$KEEP_FISH"')]:
            result = subprocess.run([binary, '-c', script], env=self.env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('yes', result.stdout)
        self.assertFalse((self.home / 'nvm-loads').exists())
        self.assertEqual(old_nvm.read_text(), 'echo loaded >> "$HOME/nvm-loads"\n')
        self.assertEqual((functions / 'bass.fish').read_text(), '# user bass\n')
        self.assertEqual(self.zshrc.stat().st_mode & 0o777, 0o640)
        current = {p: p.read_bytes() for p in originals}
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 0, output)
        self.assertEqual({p: p.read_bytes() for p in originals}, current)
        self.assertIn('prefix=' + str(self.home / '.local'), (self.home / '.npmrc').read_text())

    def test_old_global_tool_inventory_prints_commands_without_reinstall(self):
        directory = self.home / '.nvm/versions/node/v22.1.0/bin'
        directory.mkdir(parents=True)
        for name in ['node', 'npm']:
            self.stub(name + '-old', STUB)
            (self.bin / (name + '-old')).rename(directory / name)
        # The external runtime is simulated here; assert inventory and shell orchestration.
        for name in ['node', 'npm']:
            target = directory / name
            target.write_text('#!' + sys.executable + '\n' + STUB)
            target.chmod(0o755)
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 0, output)
        self.assertIn('npm install -g old-tool@1.2.3', output)
        self.assertIn(['npm', 'ls', '--global', '--depth=0', '--json'], self.calls())
        self.assertFalse(any(c[:3] == ['npm', 'install', '-g'] for c in self.calls()))
        self.assertTrue((directory / 'npm').exists())

    def test_node_migrates_multiline_zsh_plugins_and_retains_lazy_settings(self):
        self.dev_fixture()
        self.stub('zsh', STUB)
        self.stub('fish', STUB)
        settings = ("zstyle ':omz:plugins:nvm' lazy yes\n"
                    "zstyle ':omz:plugins:nvm' lazy-cmd pi textlint\n")
        self.zshrc.write_text('plugins=(\n    git\n    # user comment\n    nvm # old Node loader\n    custom\n)\n' + settings)
        output, code = self.confirm(self.choose_only({4}, shell='fish'))
        self.assertEqual(code, 0, output)
        self.assertIn(settings, self.zshrc.read_text())
        self.assertIn('# old Node loader', self.zshrc.read_text())
        loaded = subprocess.run([ZSH_BINARY, '-dfc', 'source "$HOME/.zshrc"; print -l -- $plugins'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(loaded.returncode, 0, loaded.stderr)
        self.assertEqual(loaded.stdout.splitlines(), ['git', 'custom'])
        original = self.zshrc.read_bytes()
        output, code = self.confirm(self.choose_only({4}, shell='fish'))
        self.assertEqual(code, 0, output)
        self.assertEqual(self.zshrc.read_bytes(), original)

    def test_node_custom_multiline_zsh_plugin_logic_still_blocks_migration(self):
        self.stub('zsh', STUB)
        self.zshrc.write_text('plugins=(\n    nvm\n    "$CUSTOM_PLUGIN"\n)\n')
        original = self.zshrc.read_bytes()
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 1, output)
        self.assertEqual(self.zshrc.read_bytes(), original)
        self.assertIn('先修复 npm 目录 / nvm 启动迁移', output)
        self.assertFalse(self.calls('chsh'))

    def test_node_invalid_version_rejected_before_any_installation(self):
        for value in ['lts/*', '24.1.0', '0', '24;touch /tmp/unwanted']:
            with self.subTest(value=value):
                result = subprocess.run(['/bin/bash', self.env['WIZARD_SCRIPT']],
                                        env=dict(self.env, NODE_VERSION=value), text=True, capture_output=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('仅接受主版本号', result.stderr)
                self.assertFalse(self.calls())

    def test_node_prefix_conflict_preserves_configuration_and_skips_install(self):
        self.dev_fixture()
        config = self.home / '.npmrc'
        config.write_text('prefix=/custom/npm\nregistry=https://example.invalid\n')
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 1, output)
        self.assertIn('已有自定义 npm prefix', output)
        self.assertEqual(config.read_text(), 'prefix=/custom/npm\nregistry=https://example.invalid\n')
        self.assertFalse(self.calls('apt'))
        self.assertFalse(self.calls('curl'))

    def test_node_source_conflict_preserves_existing_source(self):
        source = self.root / 'nodesource.sources'
        source.write_text('Types: deb\nURIs: https://deb.nodesource.com/node_22.x\n')
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 1, output)
        self.assertIn('已有其他 NodeSource 源', output)
        self.assertIn('node_22.x', source.read_text())
        self.assertFalse(self.calls('apt'))

    def test_node_apt_removal_stops_and_rolls_back_new_source(self):
        self.dev_fixture()
        self.env['APT_REMOVES_NODE'] = '1'
        self.bashrc.write_text('source "$NVM_DIR/nvm.sh"\n')
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 1, output)
        self.assertIn('apt 需要移除现有软件包', output)
        self.assertFalse(any(c[:4] == ['apt', 'install', '--no-remove', '-y'] and any(a.startswith('nodejs=') for a in c) for c in self.calls('apt')))
        self.assertFalse((self.root / 'nodesource.list').exists())
        self.assertFalse((self.root / 'nodesource.gpg').exists())
        self.assertFalse((self.root / 'nodesource.pin').exists())
        self.assertIn('source "$NVM_DIR/nvm.sh"', self.bashrc.read_text())
        self.assertFalse((self.home / '.npmrc').exists())

    def test_node_large_madison_output_preserves_first_candidate_without_sigpipe(self):
        self.env['MADISON_LARGE'] = '1'
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 0, output)
        self.assertIn(['apt', 'install', '--no-remove', '-y', 'nodejs=24.1.0-1nodesource1'], self.calls())
        self.assertIn('[成功] Node.js/npm（apt）', output)

    def test_node_madison_error_propagates_after_printing_candidate(self):
        self.env['MADISON_ERROR'] = '1'
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 1, output)
        self.assertIn('失败（退出码 54）', output)
        self.assertIn('[失败] Node.js/npm（apt）', output)
        self.assertFalse(any(any(a.startswith('nodejs=') for a in c) for c in self.calls('apt')))
        self.assertFalse((self.root / 'nodesource.list').exists())

    def test_node_missing_candidate_does_not_fall_back_or_change_nvm(self):
        self.env['NO_NODE_CANDIDATE'] = '1'
        self.bashrc.write_text('source "$NVM_DIR/nvm.sh"\n')
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 1, output)
        self.assertIn('无 Node.js 24 候选版本', output)
        self.assertFalse((self.root / 'nodesource.list').exists())
        self.assertFalse((self.root / 'nodesource.gpg').exists())
        self.assertFalse((self.root / 'nodesource.pin').exists())
        self.assertIn('source "$NVM_DIR/nvm.sh"', self.bashrc.read_text())

    def test_node_unknown_nvm_loader_blocks_migration_before_prefix_change(self):
        self.zshrc.write_text('if [[ -n "$CUSTOM" ]]; then source "$NVM_DIR/nvm.sh"; fi\n')
        original = self.zshrc.read_bytes()
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 1, output)
        self.assertIn('请手动检查 nvm 自定义加载', output)
        self.assertEqual(self.zshrc.read_bytes(), original)
        self.assertFalse((self.home / '.npmrc').exists())
        self.assertFalse(self.calls('chsh'))
        self.assertTrue((self.root / 'nodesource.list').exists())
        self.assertFalse(list(self.home.glob('.node-migration.*')))
        self.assertFalse(list(self.home.glob('.node-migration.*.nvm.*')))

    def test_node_npm_config_failure_preserves_nvm_startup(self):
        self.env['FAIL_NPM_CONFIG'] = '1'
        self.bashrc.write_text('source "$NVM_DIR/nvm.sh"; export KEEP=yes\n')
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 1, output)
        self.assertIn('[失败] npm 目录 / nvm 启动迁移', output)
        self.assertIn('source "$NVM_DIR/nvm.sh"; export KEEP=yes', self.bashrc.read_text())
        self.assertFalse(self.calls('chsh'))

    def test_unselected_node_keeps_existing_nvm(self):
        self.bashrc.write_text('source "$NVM_DIR/nvm.sh"\n')
        output, code = self.confirm(self.choose_only(set()))
        self.assertEqual(code, 0, output)
        self.assertIn('source "$NVM_DIR/nvm.sh"', self.bashrc.read_text())
        self.assertFalse(self.calls('apt'))
        self.assertFalse((self.home / '.npmrc').exists())

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
        self.assertIn(['apt', 'install', '--no-remove', '-y', 'nodejs=22.1.0-1nodesource1'], self.calls())
        self.assertFalse(self.calls('nvm'))
        self.assertIn('node_22.x', (self.root / 'nodesource.list').read_text())
        self.assertIn('Pin-Priority: 600', (self.root / 'nodesource.pin').read_text())
        self.assertEqual(profile.read_text(), '# keep profile\n')
        self.assertEqual(self.zshrc.read_text(), '# untouched zsh\n')
        self.assertNotIn('NVM_DIR', self.bashrc.read_text())

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
        self.assertIn('[失败] Node.js/npm（apt）', output)
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
        self.assertIn('[失败] Node.js/npm（apt）', output)
        self.assertNotIn('NVM_DIR', self.bashrc.read_text())
        self.assertNotIn(['nvm', 'use', 'lts/*'], self.calls())
        original = self.bashrc.read_text().replace('# 目标 shell', 'export KEEP_INIT=1\n# 目标 shell')
        self.bashrc.write_text(original)
        output, code = self.confirm(self.choose_only({4}))
        self.assertEqual(code, 1, output)
        self.assertIn('export KEEP_INIT=1', self.bashrc.read_text())
        self.assertNotIn('NVM_DIR', self.bashrc.read_text())
        self.assertTrue(self.calls('chsh'))

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
        self.assertEqual(self.bashrc.read_text().count('. "$NVM_DIR/nvm.sh"'), 0)

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
        self.assertEqual(self.bashrc.read_text().count('. "$NVM_DIR/nvm.sh"'), 0)
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
        self.assertNotIn('安装组件：系统基础包', output)
        self.assertTrue(self.calls('apt'))
        self.assertIn(['apt', 'install', '--no-remove', '-y', 'nodejs=24.1.0-1nodesource1'], self.calls())

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

    def test_existing_updater_is_preserved_and_not_installed(self):
        self.dev_fixture()
        updater = self.home / '.local/bin/toria-update'
        updater.parent.mkdir(parents=True)
        updater.write_text('user-owned updater\n')
        updater.chmod(0o700)
        self.stub('install', 'import sys\nsys.exit(60)\n')
        output, code = self.confirm(self.choose_only({3}))
        self.assertEqual(code, 0, output)
        self.assertIn('[成功] 用户工具目录', output)
        self.assertIn('[成功] uv/Python', output)
        self.assertEqual(updater.read_text(), 'user-owned updater\n')
        self.assertEqual(updater.stat().st_mode & 0o777, 0o700)
        self.assertFalse(self.calls('curl'))

    def test_development_components_default_selected_and_reuse_installed_tools(self):
        self.stub('fzf', STUB)
        self.dev_fixture()
        term = self.terminal()
        term.expect('[x] Homebrew/eza')
        term.expect('[x] lazygit')
        term.expect('[x] uv/Python')
        term.expect('[x] Node.js/npm（apt）')
        term.send(b'\x1b[B' * 8 + b' \x1b[A \x1b[A \x1b[A ')
        term.send(b'\r')
        term.expect('确认执行')
        term.send(b'y\r')
        term.expect('安装结果')
        self.assertEqual(term.finish(), 0, term.output.decode())
        config = self.bashrc.read_text()
        for expected in ['brew shellenv', 'alias ls=', 'alias la=', '.local/bin']:
            self.assertIn(expected, config)
        self.assertFalse((self.home / '.local/bin/toria-update').exists())
        self.assertIn('set completion-ignore-case on', (self.home / '.inputrc').read_text())
        self.assertEqual(self.zshrc.read_text(), '# untouched zsh\n')
        self.assertTrue(self.calls('curl'))
        self.assertTrue(all('nodesource.com' in ' '.join(c) for c in self.calls('curl')))
        self.assertNotIn('NVM_DIR', config)
        self.assertNotIn('bash_completion', config)

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
        pristine = self.home / 'custom startup.pre-env-setup-wsl.bak'
        self.assertEqual(pristine.read_text(), original)
        increments = sorted(self.home.glob('custom startup.env-setup-wsl.bak-*'))
        self.assertEqual(len(increments), 1)
        self.assertEqual(increments[0].read_text(), original)
        # Execute the printed recovery command; quoted paths include spaces and apostrophes.
        output = re.sub(r'\x1b\[[0-9;]*m', '', first.output.decode())
        command = re.search(r'恢复命令：(.*)', output).group(1).strip()
        subprocess.run(['/bin/bash', '-c', command], env=self.env, check=True)
        self.assertEqual(target.read_text(), original)
        self.assertFalse(self.calls('apt'))
        self.assertIn('用户未选择', second.output.decode())

    def test_changed_rerun_keeps_pristine_backup_and_stacks_timestamped_increments(self):
        self.dev_fixture()
        # 固定时间，确保覆盖同一秒内的备份重名分支。
        self.stub('date', "print('20261104T000000Z')\n")
        original = '# original settings\n'
        self.bashrc.write_text(original)
        first, code = self.install(selected=False)
        self.assertEqual(code, 0, first.output.decode())
        generated = self.bashrc.read_text()
        self.assertIn('原始配置备份：', first.output.decode())
        pristine = self.home / '.bashrc.pre-env-setup-wsl.bak'
        self.assertEqual(pristine.read_text(), original)
        # 第二次改动必须另存一份，且不覆盖安装前原件。
        second, code = self.confirm(self.choose_only({1}))
        self.assertEqual(code, 0, second)
        self.assertNotEqual(self.bashrc.read_text(), generated)
        self.assertEqual(pristine.read_text(), original)
        increments = sorted(self.home.glob('.bashrc.env-setup-wsl.bak-*'))
        for path in increments:
            self.assertRegex(path.name, r'^\.bashrc\.env-setup-wsl\.bak-\d{8}T\d{6}Z(?:-\d+)?$')
        self.assertEqual([path.read_text() for path in increments], [original, generated])

    def test_partial_pristine_backup_failure_can_retry(self):
        original = '# original settings\n'
        self.bashrc.write_text(original)
        self.stub('cp', """import os, sys
from pathlib import Path
if 'pre-env-setup-wsl.bak' in sys.argv[-1]:
    Path(sys.argv[-1]).write_text('partial')
    sys.exit(46)
os.execv(""" + repr(shutil.which('cp')) + """, ['cp'] + sys.argv[1:])
""")
        term, code = self.install(selected=False)
        self.assertEqual(code, 1, term.output.decode())
        self.assertEqual(self.bashrc.read_text(), original)
        self.assertFalse((self.home / '.bashrc.pre-env-setup-wsl.bak').exists())
        self.assertFalse(list(self.home.glob('*.tmp.*')))
        self.assertFalse(self.calls('chsh'))
        (self.bin / 'cp').unlink()
        (self.bin / 'cp').symlink_to(shutil.which('cp'))
        term, code = self.install(selected=False)
        self.assertEqual(code, 0, term.output.decode())
        self.assertEqual((self.home / '.bashrc.pre-env-setup-wsl.bak').read_text(), original)

    def test_timestamp_failure_preserves_config_and_skips_switch(self):
        original = '# original settings\n'
        self.bashrc.write_text(original)
        self.stub('date', 'import sys\nsys.exit(47)\n')
        term, code = self.install(selected=False)
        self.assertEqual(code, 1, term.output.decode())
        self.assertEqual(self.bashrc.read_text(), original)
        self.assertFalse(list(self.home.glob('.bashrc.env-setup-wsl.bak-*')))
        self.assertFalse(self.calls('chsh'))
        (self.bin / 'date').unlink()
        (self.bin / 'date').symlink_to(shutil.which('date'))
        term, code = self.install(selected=False)
        self.assertEqual(code, 0, term.output.decode())
        backups = list(self.home.glob('.bashrc.env-setup-wsl.bak-*'))
        self.assertEqual(len(backups), 1)
        self.assertRegex(backups[0].name, r'^\.bashrc\.env-setup-wsl\.bak-\d{8}T\d{6}Z$')
        self.assertEqual(backups[0].read_text(), original)

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

    def test_pipe_help_errors_and_no_terminal(self):
        for args, code, message in [(('--help',), 0, '用法：setup-wsl.sh'),
                                    (('--unattended',), 2, '未知选项'),
                                    ((), 1, '需要交互终端')]:
            with self.subTest(args=args):
                result = subprocess.run(['/bin/bash', '-s', '--', *args],
                                        input=Path(self.env['WIZARD_SCRIPT']).read_text(),
                                        env=self.env, cwd=self.home, start_new_session=True,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertIn(message, result.stdout + result.stderr)
        self.assertFalse(self.calls())
        self.assertFalse(self.bashrc.exists())

    def test_pipe_menu_quit_restores_terminal(self):
        term = self.terminal(piped=True)
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertEqual(term.before, termios.tcgetattr(term.master))
        self.assertFalse(self.calls('apt'))
        self.assertFalse(self.calls('chsh'))
        self.assertFalse(self.bashrc.exists())

    def test_pipe_declining_confirmation_does_not_write(self):
        term = self.choose_only(set(), piped=True)
        term.send(b'\r')
        term.expect('确认执行')
        term.send(b'n\r')
        self.assertEqual(term.finish(), 0)
        self.assertFalse(self.calls('apt'))
        self.assertFalse(self.calls('chsh'))
        self.assertFalse((self.home / '.local').exists())
        self.assertFalse(self.bashrc.exists())

    def test_pipe_install_is_standalone_and_does_not_create_updater(self):
        self.dev_fixture()
        self.env['REQUIRE_SUDO_TTY'] = '1'
        output, code = self.confirm(self.choose_only({0}, piped=True))
        self.assertEqual(code, 0, output)
        self.assertIn('[成功] 用户工具目录', output)
        self.assertTrue((self.home / '.local/bin').is_dir())
        self.assertFalse((self.home / '.local/bin/toria-update').exists())
        self.assertIn('.local/bin', self.bashrc.read_text())
        self.assertTrue(self.calls('sudo'))
        self.assertTrue(self.calls('chsh'))

    def test_pipe_failure_prints_retry_with_versions_on_bash(self):
        self.dev_fixture()
        (self.bin / 'uv').unlink()
        self.env.update(FAIL_DOWNLOAD='1', PYTHON_VERSION='3.13', NODE_VERSION='22')
        output, code = self.confirm(self.choose_only({3}, piped=True))
        self.assertEqual(code, 1, output)
        self.assertIn('[失败] uv/Python', output)
        retry = ('curl -fsSL https://raw.githubusercontent.com/gwyntoria/skills/'
                 'refs/heads/main/scripts/setup-wsl.sh | '
                 'PYTHON_VERSION=3.13 NODE_VERSION=22 bash')
        self.assertIn(retry, output)
        # Execute the displayed command with harmless stubs to prove the
        # variables reach Bash on the right side of the pipeline.
        probe = self.root / 'retry-probe'
        probe.mkdir()
        curl = probe / 'curl'
        curl.write_text('#!/bin/sh\nexit 0\n')
        curl.chmod(0o755)
        bash = probe / 'bash'
        bash.write_text('#!/bin/sh\nprintf "%s %s" "$PYTHON_VERSION" "$NODE_VERSION"\n')
        bash.chmod(0o755)
        env = dict(self.env, PATH=str(probe), PYTHON_VERSION='wrong', NODE_VERSION='wrong')
        result = subprocess.run(['/bin/bash', '-c', retry], env=env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '3.13 22')

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
        term.send(b'\x1b[B' * 10)
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
