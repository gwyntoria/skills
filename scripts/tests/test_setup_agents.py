#!/usr/bin/env python3
"""Isolated installer regression checks; Python 3 standard library only."""

import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import shutil
import tarfile
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'setup-agents.sh'

NPX = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\n')
source = next(a for a in args if a.startswith('https://'))
if '--list' in args:
    if os.environ.get('FAIL_SOURCE') and os.environ['FAIL_SOURCE'] in source:
        print('fixture: source unavailable', file=sys.stderr)
        sys.exit(7)
    if os.environ.get('BAD_CATALOG'):
        print('unexpected CLI output')
        sys.exit(0)
    if '/gwyntoria/skills' in source:
        names = ['gwyntoria-first', 'gwyntoria-last']
    elif '/titanwings/distilly' in source:
        names = ['distilly']
    else:
        names = ['waza-first', 'fail-middle', 'waza-last'] if '/waza' in source else ['kami']
    print('\x1b[32m◇  Available Skills\x1b[0m')
    for name in names:
        print('│    ' + name + '\n│\n│      A fixture description.')
    sys.exit(0)
names = args[args.index('--skill') + 1:args.index('--agent')]
if os.environ.get('FAIL_SKILL') in names:
    sys.exit(9)
for name in names:
    folder = Path.home() / '.agents/skills' / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'SKILL.md').write_text(name)
'''
CURL = r'''#!/usr/bin/env python3
import os, sys, shutil, json
args = sys.argv[1:]
if '-o' in args:
    with open(os.environ['FETCH_LOG'], 'a') as log:
        log.write(' '.join(args) + '\n')
    if os.environ.get('FAIL_DOWNLOAD'):
        sys.exit(22)
    url = next(a for a in args if a.startswith('https://'))
    output = args[args.index('-o') + 1]
    if 'codeload.github.com/tw93/Waza/' in url:
        print('fixture: codeload TLS failure', file=sys.stderr)
        sys.exit(35)
    if 'api.github.com/repos/tw93/Waza/' in url:
        if os.environ.get('FAIL_WAZA_API') in ('all', 'commit' if '/commits/main' in url else 'catalog'):
            print('fixture: API HTTP 403 rate limit', file=sys.stderr)
            sys.exit(22)
        if '/commits/main' in url:
            with open(output, 'w') as target:
                json.dump({'sha': os.environ.get('WAZA_COMMIT', 'a' * 40)}, target)
        else:
            shutil.copyfile(os.environ['WAZA_CATALOG'], output)
    elif 'raw.githubusercontent.com/tw93/Waza/' in url:
        if os.environ.get('FAIL_WAZA_RULE') and os.environ['FAIL_WAZA_RULE'] in url:
            sys.exit(22)
        shutil.copyfile(os.path.join(os.environ['WAZA_FILES'], url.rsplit('/', 1)[-1]), output)
    else:
        source = os.environ['REMOTE_ARCHIVE' if 'codeload.github.com' in url else 'REMOTE_SCRIPT']
        shutil.copyfile(source, output)
else:
    if os.environ.get('FAIL_MATT'):
        sys.exit(8)
    names = os.environ.get('MATT_SKILLS', 'matt-a matt-b').split()
    print('<section aria-labelledby="skill-set-heading">' + ''.join('<a href="/skills-' + name + '">' + name + '</a>' for name in names) + '</section>')
'''


GIT = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args and args[0] == 'clone':
    with open(os.environ['GIT_LOG'], 'a') as log:
        log.write(json.dumps(args) + '\n')
    if os.environ.get('INTERRUPT_CLONE'):
        import signal
        os.kill(os.getppid(), signal.SIGTERM)
        sys.exit(143)
    source = os.environ.get('WAZA_GIT_REPO')
    if not source:
        print('fixture: Git clone unavailable', file=sys.stderr)
        sys.exit(128)
    args[args.index('https://github.com/tw93/Waza.git')] = Path(source).as_uri()
if 'fetch' in args and os.environ.get('FAIL_GIT_FETCH'):
    print('fixture: pinned commit unavailable', file=sys.stderr)
    sys.exit(128)
os.execv(os.environ['REAL_GIT'], [os.environ['REAL_GIT'], *args])
'''


PI = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.path.join(os.environ['HOME'], 'pi-calls.jsonl'), 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\n')
if sys.argv[1:] == ['--version'] and os.environ.get('FAIL_PI_CLI'): sys.exit(72)
if sys.argv[1:] == ['install', os.environ.get('FAIL_PI_PACKAGE')]: sys.exit(73)
'''



class Terminal:
    def __init__(self, env, script=SCRIPT, cwd=None, command=None):
        self.master, slave = pty.openpty()
        self.process = subprocess.Popen(command or ['bash', str(script)], stdin=slave,
                                        stdout=slave, stderr=slave, env=env, cwd=cwd)
        os.close(slave)
        self.pending = b''
        self.transcript = b''

    def expect(self, text):
        wanted = text.encode()
        deadline = time.monotonic() + 10
        while True:
            plain, ends = bytearray(), []
            offset = 0
            for match in re.finditer(rb'\x1b\[[0-9;]*m', self.pending):
                for i in range(offset, match.start()): plain.append(self.pending[i]); ends.append(i + 1)
                offset = match.end()
            for i in range(offset, len(self.pending)): plain.append(self.pending[i]); ends.append(i + 1)
            found = plain.find(wanted)
            if found >= 0:
                self.pending = self.pending[ends[found + len(wanted) - 1]:]
                return
            if time.monotonic() > deadline:
                raise AssertionError(f'Missing {text!r}: {self.transcript.decode(errors="replace")}')
            if select.select([self.master], [], [], 0.1)[0]:
                try: data = os.read(self.master, 65536)
                except OSError: data = b''
                if not data: raise AssertionError(f'Terminal exited before {text!r}: {self.transcript!r}')
                self.pending += data
                self.transcript += data

    def send(self, data):
        os.write(self.master, data)

    def finish(self):
        return self.process.wait(timeout=10)

    def return_home(self):
        self.expect('Press Enter to return to the main menu')
        if self.process.poll() is not None:
            raise AssertionError('Installer exited before returning home')
        self.send(b'\r')
        self.expect('Agent setup')
        self.expect('Item 1/6')

    def exit_home(self):
        self.send(b'\x1b[A\r')  # wrap from Install / Update to Exit
        return self.finish()

    def finish_action(self):
        self.return_home()
        return self.exit_home()

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        os.close(self.master)


class AgentSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agent-setup-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Quotes and spaces exercise the printed shell recovery command.
        self.home = self.root / "user's home"
        self.home.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'calls.jsonl'
        self.env = dict(os.environ, HOME=str(self.home),
                        PATH=f'{self.bin}:{os.environ["PATH"]}', CALL_LOG=str(self.log),
                        FETCH_LOG=str(self.root / "fetch.log"),
                        REAL_GIT=shutil.which('git'), GIT_LOG=str(self.root / 'git.log'))
        for name, content in [('npx', NPX), ('curl', CURL), ('git', GIT),
                              ('codex', '#!/bin/sh\nexit 0\n'),
                              ('claude', '#!/bin/sh\nexit 0\n'),
                              ('pi', PI)]:
            self.stub(name, content)
        self.env.pop('PI_CODING_AGENT_DIR', None)
        self.waza_bundle()
        self.old = self.home / '.agents/skills/existing/SKILL.md'
        self.old.parent.mkdir(parents=True)
        self.old.write_text('keep me')

    def stub(self, name, content):
        target = self.bin / name
        target.write_text(content)
        target.chmod(0o755)

    def run_script(self, *args):
        return subprocess.run(['bash', str(SCRIPT), *args], env=self.env,
                              capture_output=True, text=True, timeout=20)

    def source(self, command, script=SCRIPT, cwd=None):
        return subprocess.run(['bash', '-c', f'source {shlex.quote(str(script))}\n{command}'],
                              env=self.env, cwd=cwd, capture_output=True, text=True, timeout=20)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def run_piped(self, *args):
        return subprocess.run(['bash', '-s', '--', *args], input=SCRIPT.read_text(),
                              env=self.env, cwd=self.root, start_new_session=True,
                              capture_output=True, text=True, timeout=20)

    def test_pipe_help_and_invalid_arguments(self):
        result = self.run_piped('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Usage: setup-agents.sh', result.stdout)
        self.assertEqual(self.run_piped('--unknown').returncode, 2)
        self.assertEqual(self.run_piped('--list', '--skill').returncode, 2)
        self.assertFalse(self.calls())

    def test_pipe_without_terminal_reports_error(self):
        result = self.run_piped()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('requires a terminal', result.stderr)
        self.assertFalse(self.calls())

    def test_pipe_list_is_read_only(self):
        result = self.run_piped('--list-skill', '--remote')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('gwyntoria-first', result.stdout)
        self.assertTrue(self.calls())
        self.assertTrue(all('--list' in call for call in self.calls()))
        self.assertEqual(self.old.read_text(), 'keep me')

    def test_pipe_agent_install_fetches_resources_and_cleans_up(self):
        self.remote_bundle()
        scratch = self.root / 'scratch'
        scratch.mkdir()
        self.env['TMPDIR'] = str(scratch)
        result = self.run_piped('--agent')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('7 succeeded, 0 failed', result.stdout)
        self.assertTrue((self.home / '.claude/statusline.sh').exists())
        self.assertEqual(len((self.root / 'fetch.log').read_text().splitlines()), 1)
        self.assertEqual(list(scratch.iterdir()), [])

    def test_pipe_interactive_menu_uses_controlling_terminal(self):
        # A PTY fd alone is not a controlling terminal. Attach it to a new
        # session so /dev/tty behaves as it does in a user's terminal.
        launcher = (
            'import os, fcntl, termios; os.setsid(); '
            'fcntl.ioctl(0, termios.TIOCSCTTY, 0); '
            'os.execv("/bin/bash", ["bash", "-c", '
            + repr(f'cat {shlex.quote(str(SCRIPT))} | bash') + '])'
        )
        term = Terminal(self.env, cwd=self.root, command=['python3', '-c', launcher])
        self.addCleanup(term.close)
        term.expect('Agent setup')
        term.expect('Item 1/6')
        term.send(b'\r')
        term.expect('Choose installation tasks')
        term.expect('Item 1/3')
        term.send(b'q\n')
        self.assertEqual(term.finish(), 0)
        self.assertFalse(self.calls())

    def node_bootstrap_fixture(self, custom=False):
        # Exclude any host Node installation from the initial PATH.
        isolated = self.root / 'isolated-bin'
        isolated.mkdir()
        for command in ['bash', 'dirname', 'mktemp', 'rm']:
            (isolated / command).symlink_to(shutil.which(command))
        self.env['PATH'] = str(isolated)
        self.env.pop('NVM_DIR', None)
        runtime = self.root / 'node-bin'
        runtime.mkdir()
        (runtime / 'node').symlink_to(shutil.which('node'))
        nvm = self.root / 'custom-nvm' if custom else self.home / '.nvm'
        nvm.mkdir()
        if custom:
            self.env['NVM_DIR'] = str(nvm)
        (nvm / 'nvm.sh').write_text(
            '[ "$1" = --no-use ] || return 1\n'
            'nvm() {\n'
            '  [ "$*" = "use --silent default" ] || return 1\n'
            f'  export PATH={shlex.quote(str(runtime))}:"$PATH"\n'
            '}\n')
        return nvm

    def test_agents_nested_choices_preserve_selection_and_bundle_claude(self):
        term = self.terminal()
        term.send(b'\r')
        term.expect('Choose installation tasks')
        term.expect('Item 1/3')
        frame = term.transcript.decode().rsplit('Choose installation tasks', 1)[-1]
        self.assertIn('[ ] Agent', frame)
        self.assertNotIn('Claude statusline', frame)
        term.send(b'\x1b[B' * 2 + b' \r')
        term.expect('Choose Agents')
        term.expect('Item 1/3')
        self.assertIn('[ ] Pi (with three packages)', term.transcript.decode())
        term.send(b' \x1b[B \x1b[B\r')
        term.expect('Continue? [Y/n]')
        plan = term.transcript.decode().rsplit('Execution plan:', 1)[-1]
        self.assertIn('Claude Code CLI', plan)
        self.assertIn('Claude statusline (bundled)', plan)
        self.assertNotIn('Pi CLI', plan)
        self.assertNotIn('Codex CLI', plan)
        term.send(b'b\n')
        term.expect('Choose Agents')
        term.expect('Item 3/3')
        frame = term.transcript.decode().rsplit('Choose Agents', 1)[-1]
        self.assertIn('[ ] Codex', frame)
        self.assertIn('[x] Claude Code (with statusline)', frame)
        self.assertIn('[ ] Pi (with three packages)', frame)
        term.send(b'\r')
        term.expect('Continue? [Y/n]')
        term.send(b'\n')
        term.expect('2 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertTrue((self.home / '.claude/statusline.sh').exists())
        self.assertFalse((self.home / '.codex/AGENTS.md').exists())
        self.assertFalse(self.calls())
        self.assertFalse((self.home / 'pi-calls.jsonl').exists())

    def test_pi_bundles_continue_after_independent_extension_failure(self):
        self.env['FAIL_PI_PACKAGE'] = 'npm:pi-subagents'
        result = self.source('AGENT_ITEMS=(5); SELECTED_SKILLS=(); execute_plan')
        self.assertEqual(result.returncode, 1, result.stderr)
        calls = [json.loads(line) for line in (self.home / 'pi-calls.jsonl').read_text().splitlines()]
        self.assertEqual(calls, [['--version'], ['install', 'npm:pi-web-access'],
                                ['install', 'npm:pi-subagents'], ['install', 'npm:pi-powerline-footer']])
        self.assertIn('3 succeeded, 1 failed', result.stdout)
        self.assertFalse((self.home / '.claude').exists())

    def test_pi_cli_failure_skips_packages_and_continues_claude(self):
        self.env['FAIL_PI_CLI'] = '1'
        result = self.source('AGENT_ITEMS=(5 1); SELECTED_SKILLS=(); execute_plan')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual((self.home / 'pi-calls.jsonl').read_text().splitlines(), ['["--version"]'])
        self.assertIn('2 succeeded, 4 failed', result.stdout)
        self.assertTrue((self.home / '.claude/statusline.sh').exists())

    def test_pi_bootstrap_installs_missing_cli_with_npm(self):
        (self.bin / 'pi').unlink()
        for command in ['node', 'python3', 'dirname', 'bash', 'readlink']:
            (self.bin / command).symlink_to(shutil.which(command))
        self.env['PATH'] = str(self.bin)
        fixture = self.root / 'pi-fixture'
        fixture.write_text(PI)
        self.env['PI_FIXTURE'] = str(fixture)
        self.stub('npm', r'''#!/usr/bin/env python3
import os, sys, shutil, json
from pathlib import Path
Path(os.environ['HOME'], 'npm-call.json').write_text(json.dumps(sys.argv[1:]))
target = Path(os.environ['HOME']).parent / 'bin/pi'
shutil.copyfile(os.environ['PI_FIXTURE'], target)
target.chmod(0o755)
''')
        result = self.source('install_pi')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.home / 'npm-call.json').read_text()),
                         ['install', '-g', '--ignore-scripts', '@earendil-works/pi-coding-agent'])

    def test_node_bootstrap_preserves_available_node(self):
        nvm = self.home / '.nvm'
        nvm.mkdir()
        (nvm / 'nvm.sh').write_text('echo unexpected-nvm-load >&2; return 1\n')
        result = self.source('require_node\nnode --version')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r'v\d+\.')
        self.assertEqual(result.stderr, '')

    def test_node_bootstrap_scans_rules_with_default_or_custom_nvm(self):
        for custom in [False, True]:
            with self.subTest(custom=custom):
                # Each case needs its own isolated command directories.
                if custom:
                    shutil.rmtree(self.root / 'isolated-bin')
                    shutil.rmtree(self.root / 'node-bin')
                self.node_bootstrap_fixture(custom)
                target = self.home / '.codex/AGENTS.md'
                target.parent.mkdir(exist_ok=True)
                target.write_text('<!-- gwyn-space-skills: agent-behavior:start -->\n'
                                  'rule\n<!-- gwyn-space-skills: agent-behavior:end -->\n')
                result = self.source('REMOVE_RULES=1\nscan_removal_inventory\n'
                                     'printf "%s\\n" "${REMOVAL_RULE_LABELS[@]}"')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('AGENTS.md [Codex:file]', result.stdout)

    def test_node_bootstrap_reports_missing_nvm_or_default(self):
        nvm = self.node_bootstrap_fixture()
        for broken_default in [False, True]:
            with self.subTest(broken_default=broken_default):
                if broken_default:
                    (nvm / 'nvm.sh').write_text('nvm() { return 3; }\n')
                else:
                    (nvm / 'nvm.sh').unlink()
                result = self.source('require_node')
                self.assertEqual(result.returncode, 1)
                self.assertIn('Node.js is unavailable', result.stderr)
                self.assertIn('nvm use default', result.stderr)

    def terminal(self, cwd=None):
        terminal = Terminal(self.env, cwd=cwd)
        self.addCleanup(terminal.close)
        terminal.expect('Agent setup')
        terminal.expect('Item 1/6')
        return terminal

    def removal_terminal(self, types=('Skills',), agents='all', scope='global', cwd=None):
        term = self.terminal(cwd=cwd)
        term.send(b'\x1b[B\r')
        term.expect('Remove: choose content')
        term.expect('Item 1/2')
        if 'Rules' in types: term.send(b' ')
        if 'Skills' in types: term.send(b'\x1b[B ')
        term.send(b'\r')
        term.expect('Remove: choose scope')
        term.expect('Item 1/2')
        if scope == 'project': term.send(b'\x1b[B')
        term.send(b'\r')
        term.expect('Remove: choose agents')
        term.expect('Item 1/3' if scope == 'global' else 'Item 1/2')
        if agents == 'all':
            term.send(b'a')
        elif agents != 'default':
            index = {'codex': 0, 'claude': 1, 'pi': 2}[agents]
            term.send(b'n' + b'\x1b[B' * index + b' ')
        term.send(b'\r')
        return term

    def inventory(self, action, *args, scope='global', cwd=None):
        folder = self.root / 'plan'
        folder.mkdir(mode=0o700, exist_ok=True)
        command = f'REMOVE_SCOPE={shlex.quote(scope)}\nREMOVAL_TEMP={shlex.quote(str(folder))}\nremoval_inventory {shlex.join([action, *map(str, args)])}'
        return self.source(command, cwd=cwd)

    def scan_entries(self, codex=True, claude=True, rules=True, skills=True, pi=False):
        result = self.inventory('scan', *map(int, [codex, claude, rules, skills, pi]))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((self.root / 'plan/inventory.json').read_text())['entries']

    def select_entries(self, entries):
        result = self.inventory('select', *(e['id'] for e in entries))
        self.assertEqual(result.returncode, 0, result.stderr)

    def lock_fixture(self):
        lock = self.home / '.agents/.skill-lock.json'
        data = {'version': 3, 'dismissed': {'keep': True}, 'skills': {
            name: {'source': 'owner/repo', 'sourceType': 'github', 'sourceUrl': 'https://github.com/owner/repo',
                   'skillPath': f'skills/{name}/SKILL.md', 'pluginName': 'preserve'} for name in ['existing', 'other']}}
        lock.write_text(json.dumps(data))
        other = self.home / '.agents/skills/other/SKILL.md'
        other.parent.mkdir()
        other.write_text('other skill')
        return lock, data

    def project_removal_fixture(self):
        # Outside HOME; spaces and quotes also exercise the recovery command.
        project = self.root / "project's directory"
        project.mkdir()
        files = {
            'AGENTS.md': 'personal\r\n<!-- gwyn-space-skills: one:start -->\r\nrule\r\n<!-- gwyn-space-skills: one:end -->\r\nend\r\n',
            '.claude/rules/nested/.custom.md': 'legacy Claude rule',
            'docs/rules/one.md': 'project rule',
            'docs/rules/.custom.md': 'custom rule',
            '.claude/CLAUDE.md': '<!-- gwyn-space-skills: ignored:start -->\nkeep\n<!-- gwyn-space-skills: ignored:end -->\n',
            '.codex/AGENTS.md': '<!-- gwyn-space-skills: ignored:start -->\nkeep\n<!-- gwyn-space-skills: ignored:end -->\n',
            '.agents/skills/existing/SKILL.md': 'project skill',
            '.agents/skills/.system/SKILL.md': 'system skill',
            '.claude/skills/.system/SKILL.md': 'system skill',
            'skills-lock.json': json.dumps({'version': 1, 'extra': 'keep', 'skills': {
                'existing': {'source': 'project/repo', 'sourceType': 'github', 'computedHash': 'keep'},
                'uninstalled': {'source': 'other/repo', 'sourceType': 'github'}}}),
        }
        for name, content in files.items():
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode())
        (project / '.claude/skills/existing').symlink_to('../../.agents/skills/existing')
        return project, files

    def project_entries(self, project, codex=True, claude=True, rules=True, skills=True):
        result = self.inventory('scan', *map(int, [codex, claude, rules, skills]), scope='project', cwd=project)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((self.root / 'plan/inventory.json').read_text())['entries']

    def test_project_removal_isolated_and_backup_restores_rules_skills_and_lock(self):
        global_lock, _ = self.lock_fixture()
        global_bytes = global_lock.read_bytes()
        project, files = self.project_removal_fixture()
        entries = self.project_entries(project)
        self.assertEqual({e['relative'] for e in entries}, {
            'docs/rules/one.md', 'docs/rules/.custom.md',
            '.agents/skills/existing', '.claude/skills/existing'})
        self.assertTrue(all(e['group'] == 'project/repo' for e in entries if e['kind'] == 'skills'))
        self.assertEqual(self.inventory('select', *(e['id'] for e in entries), scope='project', cwd=project).returncode, 0)
        result = self.inventory('preview', scope='project', cwd=project)
        self.assertIn(f'Removal scope: project ({project})', result.stdout)
        result = self.inventory('remove', '1', scope='project', cwd=project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('4 succeeded, 0 failed', result.stdout)
        self.assertEqual((project / 'AGENTS.md').read_bytes(), files['AGENTS.md'].encode())
        self.assertEqual((project / '.claude/rules/nested/.custom.md').read_text(), 'legacy Claude rule')
        self.assertFalse((project / 'docs/rules/one.md').exists())
        self.assertFalse((project / '.agents/skills/existing').exists())
        self.assertFalse((project / '.claude/skills/existing').is_symlink())
        remaining = json.loads((project / 'skills-lock.json').read_text())
        self.assertEqual(remaining['skills'], {'uninstalled': {'source': 'other/repo', 'sourceType': 'github'}})
        self.assertEqual(remaining['extra'], 'keep')
        self.assertEqual(global_lock.read_bytes(), global_bytes)
        self.assertEqual(self.old.read_text(), 'keep me')
        for name in ['.agents/skills/.system/SKILL.md', '.claude/skills/.system/SKILL.md', '.codex/AGENTS.md', '.claude/CLAUDE.md']:
            self.assertEqual((project / name).read_bytes(), files[name].encode())
        backup, = self.home.glob('.agent-rules-backup-*/removal.tar')
        with tarfile.open(backup) as archive:
            self.assertIn('docs/rules/one.md', archive.getnames())
            self.assertNotIn('AGENTS.md', archive.getnames())
            self.assertIn('skills-lock.json', archive.getnames())
        plain = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout)
        recovery = next(line.removeprefix('Restore: ') for line in plain.splitlines() if line.startswith('Restore: '))
        # Execute the printed command, including its quoting and project destination.
        subprocess.run(['bash', '-c', recovery], check=True)
        for name, content in files.items():
            self.assertEqual((project / name).read_bytes(), content.encode())
        self.assertEqual(os.readlink(project / '.claude/skills/existing'), '../../.agents/skills/existing')

    def test_project_claude_only_preserves_shared_skill_and_lock(self):
        project, files = self.project_removal_fixture()
        entries = self.project_entries(project, codex=False, rules=False)
        self.assertEqual(len(entries), 1)
        self.inventory('select', entries[0]['id'], scope='project', cwd=project)
        result = self.inventory('remove', scope='project', cwd=project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((project / '.claude/skills/existing').is_symlink())
        self.assertEqual((project / 'skills-lock.json').read_bytes(), files['skills-lock.json'].encode())
        self.assertTrue((project / '.agents/skills/existing/SKILL.md').exists())

    def test_project_invalid_lock_and_backup_failure_prevent_removal(self):
        project, _ = self.project_removal_fixture()
        lock = project / 'skills-lock.json'
        lock.write_text('{broken')
        entries = self.project_entries(project, claude=False, rules=False)
        self.inventory('select', entries[0]['id'], scope='project', cwd=project)
        result = self.inventory('remove', '1', scope='project', cwd=project)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Invalid skill lock', result.stderr)
        lock.unlink()
        entries = self.project_entries(project, claude=False, rules=False)
        self.inventory('select', entries[0]['id'], scope='project', cwd=project)
        self.stub('tar', '#!/bin/sh\nexit 23\n')
        result = self.inventory('remove', '1', scope='project', cwd=project)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Backup failed; nothing removed', result.stderr)
        self.assertTrue((project / '.agents/skills/existing/SKILL.md').exists())
        self.assertFalse(lock.exists())

    def test_removal_manifest_cannot_be_reused_in_another_scope_or_project(self):
        project, _ = self.project_removal_fixture()
        entries = self.project_entries(project)
        self.inventory('select', *(e['id'] for e in entries), scope='project', cwd=project)
        for scope, cwd in [('global', project), ('project', self.home)]:
            result = self.inventory('remove', scope=scope, cwd=cwd)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('scope or root changed', result.stderr)
        self.assertTrue((project / '.agents/skills/existing/SKILL.md').exists())
        self.assertTrue(self.old.exists())

    def test_project_scan_rejects_root_and_symlinked_parent(self):
        result = self.inventory('scan', 1, 1, 1, 1, scope='project', cwd='/')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsafe removal root', result.stderr)
        project, _ = self.project_removal_fixture()
        shutil.rmtree(project / '.agents')
        (project / '.agents').symlink_to(self.home / '.agents')
        result = self.inventory('scan', 1, 1, 1, 1, scope='project', cwd=project)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Refusing symlinked directory', result.stderr)
        self.assertTrue(self.old.exists())

    def test_project_removal_ui_rules_and_skills(self):
        project, _ = self.project_removal_fixture()
        term = self.removal_terminal(types=('Rules', 'Skills'), scope='project', cwd=project)
        term.expect('Choose installed rules to remove')
        term.expect('Item 1/2')
        term.send(b'a\r')
        term.expect('Remove skills by repository')
        term.expect('Item 1/2')
        term.send(b' \x1b[A\r')
        term.expect('Removal scope: project')
        term.expect(str(project / 'skills-lock.json'))
        term.expect('Create backup? [y/N]')
        term.send(b'\n')
        term.expect('Confirm removal? [Y/n]')
        term.send(b'y\n')
        term.expect('4 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertTrue(self.old.exists())
        self.assertFalse((project / '.agents/skills/existing').exists())

    def test_removal_scope_back_rescans_project_and_preserves_agent_selection(self):
        project, _ = self.project_removal_fixture()
        global_rule = self.home / '.claude/rules/global.md'
        global_rule.parent.mkdir(parents=True)
        global_rule.write_text('global')
        term = self.removal_terminal(types=('Rules',), agents='claude', cwd=project)
        term.expect('global.md [Claude:file]')
        term.send(b'b')
        term.expect('Remove: choose agents')
        term.expect('Item 2/3')
        term.send(b'b')
        term.expect('Remove: choose scope')
        term.expect('Item 1/2')
        term.send(b'\x1b[B\r')
        term.expect('Remove: choose agents')
        term.expect('[ ] Codex')
        term.expect('[x] Claude Code')
        term.expect('Item 2/2')
        term.send(b'\r')
        term.expect('Choose installed rules to remove')
        term.expect('.custom.md [Project:file]')
        term.expect('Item 1/2')
        term.send(b' \r')
        term.expect('Removal scope: project')
        term.expect('Create backup? [y/N]')
        term.send(b'\n')
        term.expect('Confirm removal? [Y/n]')
        term.send(b'y\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertTrue(global_rule.exists())
        self.assertFalse((project / 'docs/rules/.custom.md').exists())
        self.assertTrue((project / '.claude/rules/nested/.custom.md').exists())

    def install_skill_terminal(self, repos=(0,)):
        """Choose skill repositories on the first page, then land on the picker.

        repos is a sequence of source indices (0 = tw93/waza), or 'all'.
        """
        term = self.terminal()
        term.send(b'\r')
        term.expect('Item 1/3')
        term.send(b'\x1b[B \r')
        term.expect('Choose skill repositories')
        term.expect('Item 1/6')
        if repos == 'all':
            term.send(b'a')
        else:
            cursor = 0
            for repo in sorted(repos):
                if repo > cursor:
                    term.send(b'\x1b[B' * (repo - cursor))
                    cursor = repo
                term.send(b' ')
        term.send(b'\r')
        term.expect('Install skills by repository')
        # Wait for the whole picker to redraw before the caller sends keys.
        term.expect('Item 1/%d' % ((6 if repos == 'all' else len(repos)) + 1))
        return term

    def standalone(self):
        target = self.root / 'standalone/bin/agent-setup'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SCRIPT, target)
        return target

    def waza_bundle(self, names=('anti-patterns',)):
        tree = self.root / 'waza-source/Waza-main/rules'
        if tree.exists():
            shutil.rmtree(tree)
        tree.mkdir(parents=True)
        for name in names:
            (tree / f'{name}.md').write_text(f'# {name}\nUpstream {name} body.\n')
        catalog = self.root / 'waza-catalog.json'
        catalog.write_text(json.dumps([{'name': f'{name}.md', 'type': 'file'} for name in names]))
        self.env['WAZA_CATALOG'] = str(catalog)
        self.env['WAZA_FILES'] = str(tree)

    def remote_bundle(self):
        tree = self.root / 'remote/skills-main'
        shutil.copytree(SCRIPT.parents[1] / 'rules', tree / 'rules')
        (tree / 'scripts').mkdir()
        shutil.copyfile(SCRIPT.parent / 'statusline.sh', tree / 'scripts/statusline.sh')
        archive = self.root / 'remote.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(tree, arcname='skills-main')
        self.env['REMOTE_ARCHIVE'] = str(archive)
        self.env['REMOTE_SCRIPT'] = str(SCRIPT)

    def rule_terminal(self, cwd=None, script=SCRIPT):
        term = Terminal(self.env, script=script, cwd=cwd)
        self.addCleanup(term.close)
        term.expect('Item 1/6')
        term.send(b'\r')
        term.expect('Choose installation tasks')
        term.expect('Item 1/3')
        term.send(b' \r')
        term.expect('Choose rules')
        term.expect('Item 1/3')
        return term

    def rule_agents_and_scope(self, term, agents='all', scope='project'):
        term.expect('Rules: choose scope')
        term.expect('Item 1/2')
        term.send(b'\x1b[B\r' if scope == 'project' else b'\r')
        if scope == 'global':
            term.expect('Rules: choose agents')
            term.expect('Item 1/3')
            for label in ['[x] Codex', '[ ] Claude Code', '[ ] Pi']:
                self.assertIn(label, term.transcript.decode())
            if agents == 'all':
                term.send(b'a')
            elif agents != 'default':
                index = {'codex': 0, 'claude': 1, 'pi': 2}[agents]
                term.send(b'n' + b'\x1b[B' * index + b' ')
            term.send(b'\r')
        term.expect('Confirm installation')
        term.expect('Item 1/2')


    def waza_git_fixture(self):
        repo = self.root / 'git-source'
        repo.mkdir()
        shutil.copytree(Path(self.env['WAZA_FILES']), repo / 'rules')
        git = self.env['REAL_GIT']
        for args in [('init', '-q', '-b', 'main'), ('add', '.'),
                     ('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com',
                      'commit', '-qm', 'rules')]:
            subprocess.run([git, '-C', str(repo), *args], check=True, capture_output=True)
        commit = subprocess.check_output([git, '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
        self.env.update(WAZA_GIT_REPO=str(repo), WAZA_COMMIT=commit)
        return repo, commit

    def test_waza_api_failure_clones_caches_and_cleans_checkout(self):
        self.waza_bundle(('chinese', 'english'))
        repo, commit = self.waza_git_fixture()
        for failure in ('commit', 'catalog', 'invalid-json'):
            with self.subTest(failure=failure):
                self.env['FAIL_WAZA_API'] = failure
                catalog = Path(self.env['WAZA_CATALOG'])
                catalog.write_text('broken' if failure == 'invalid-json' else json.dumps(
                    [{'name': 'chinese.md', 'type': 'file'}, {'name': 'english.md', 'type': 'file'}]))
                result = self.source(
                    'load_waza_rules || exit 1\n'
                    'printf "CACHE=%s\\nCOMMIT=%s\\n" "$RESOURCE_TEMP" "$WAZA_RULES_COMMIT"\n'
                    '[ -z "$(find "$RESOURCE_TEMP" -name "waza-clone.*")" ] || exit 2\n'
                    'load_waza_rules || exit 3\n'
                    'fetch_waza_rule waza-chinese || exit 4\n'
                    'cat "$WAZA_RULES_PATH/waza-chinese.md"\n'
                    'apply_rule waza-chinese global pi install waza')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('COMMIT=' + commit, result.stdout)
                self.assertIn('Upstream chinese body.', result.stdout)
                cache = re.search(r'CACHE=(.+)', result.stdout).group(1)
                self.assertFalse(Path(cache).exists())
        installed = (self.home / '.pi/agent/AGENTS.md').read_text()
        self.assertIn('Upstream chinese body.', installed)
        self.assertNotIn('Installed from', installed)
        self.assertEqual(installed.count('Upstream chinese body.'), 3)
        self.assertEqual(len((self.root / 'git.log').read_text().splitlines()), 3)
        self.assertNotIn('raw.githubusercontent', (self.root / 'fetch.log').read_text())

    def test_waza_raw_fallback_preserves_pinned_commit_after_main_moves(self):
        repo, commit = self.waza_git_fixture()
        (repo / 'rules/anti-patterns.md').write_text('# New main\nDifferent body.\n')
        git = self.env['REAL_GIT']
        subprocess.run([git, '-C', str(repo), 'add', '.'], check=True)
        subprocess.run([git, '-C', str(repo), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.com', 'commit', '-qm', 'advance'], check=True)
        self.env['FAIL_WAZA_RULE'] = 'anti-patterns.md'
        result = self.source('load_waza_rules && fetch_waza_rule waza-anti-patterns && '
                             'cat "$WAZA_RULES_PATH/waza-anti-patterns.md"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Upstream anti-patterns body.', result.stdout)
        self.assertNotIn('Different body.', result.stdout)
        self.env['FAIL_WAZA_API'] = 'catalog'
        result = self.source('load_waza_rules && fetch_waza_rule waza-anti-patterns && '
                             'cat "$WAZA_RULES_PATH/waza-anti-patterns.md"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Upstream anti-patterns body.', result.stdout)
        self.env.pop('FAIL_WAZA_API')
        self.env['FAIL_GIT_FETCH'] = '1'
        result = self.source('load_waza_rules && fetch_waza_rule waza-anti-patterns')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('pinned commit unavailable', result.stderr)

    def test_waza_clone_rejects_invalid_selected_heading_and_skips_symlinks(self):
        repo, _ = self.waza_git_fixture()
        (repo / 'rules/anti-patterns.md').write_text('Invalid title\n')
        (repo / 'rules/link.md').symlink_to('anti-patterns.md')
        git = self.env['REAL_GIT']
        subprocess.run([git, '-C', str(repo), 'add', '.'], check=True)
        subprocess.run([git, '-C', str(repo), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.com', 'commit', '-qm', 'invalid'], check=True)
        self.env['FAIL_WAZA_API'] = 'commit'
        result = self.source('load_waza_rules || exit 1; '
                             'printf "%s\\n" "${RULE_NAMES_WAZA[@]}"; '
                             'fetch_waza_rule waza-anti-patterns')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must start with H1 or H2', result.stderr)
        self.assertEqual(result.stdout.strip(), 'waza-anti-patterns')

    def test_waza_failed_or_interrupted_clone_cleans_temporary_resources(self):
        self.env['FAIL_WAZA_API'] = 'commit'
        for interrupt in ('', '1'):
            with self.subTest(interrupt=interrupt):
                self.env['INTERRUPT_CLONE'] = interrupt
                result = self.source(
                    'if load_waza_rules; then status=0; else status=$?; fi; '
                    'printf "CACHE=%s\\n" "$RESOURCE_TEMP"; '
                    '[ -z "$(find "$RESOURCE_TEMP" -name "waza-clone.*")" ] || exit 99; '
                    'exit "$status"')
                self.assertNotEqual(result.returncode, 0)
                self.assertNotEqual(result.returncode, 99)
                cache = re.search(r'CACHE=(.+)', result.stdout).group(1)
                self.assertFalse(Path(cache).exists())

    def test_waza_clone_rejects_empty_or_unsafe_catalog(self):
        repo, _ = self.waza_git_fixture()
        self.env['FAIL_WAZA_API'] = 'commit'
        for filename in ('README.txt', 'bad name.md'):
            with self.subTest(filename=filename):
                shutil.rmtree(repo / 'rules')
                (repo / 'rules').mkdir()
                (repo / 'rules' / filename).write_text('# Example\n')
                git = self.env['REAL_GIT']
                subprocess.run([git, '-C', str(repo), 'add', '-A'], check=True)
                subprocess.run([git, '-C', str(repo), '-c', 'user.name=Fixture',
                                '-c', 'user.email=fixture@example.com', 'commit', '-qm', filename], check=True)
                result = self.source('if load_waza_rules; then status=0; else status=$?; fi; '
                                     '[ -z "$WAZA_RULES_PATH" ] || exit 99; exit "$status"')
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('No Waza rules available' if filename.endswith('.txt') else
                              'Invalid Waza rule filename', result.stderr)

    def test_waza_missing_git_reports_failure_without_publishing_catalog(self):
        self.env['FAIL_WAZA_API'] = 'commit'
        result = self.source(
            'require_command() { if [ "$1" = git ]; then '
            'printf "Git unavailable\\n" >&2; return 1; fi; command -v "$1" >/dev/null; }\n'
            'if load_waza_rules; then status=0; else status=$?; fi; '
            'printf "%s" "$WAZA_RULES_ERROR"; '
            '[ -z "$WAZA_RULES_PATH" ] || exit 99; exit "$status"')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('Git unavailable', result.stdout)

    def test_waza_selected_download_failure_preserves_configs_and_continues(self):
        self.waza_bundle(('chinese', 'english'))
        self.env['FAIL_WAZA_RULE'] = '/rules/english.md'
        old = self.home / '.codex/AGENTS.md'
        old.parent.mkdir()
        old.write_text('Personal notes.\n')
        result = self.source(
            'load_waza_rules\nAGENT_ITEMS=(2)\n'
            'SELECTED_RULES=(waza-english waza-chinese code-comments)\n'
            'SELECTED_RULE_SOURCES=(waza waza project)\nexecute_plan')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('2 succeeded, 1 failed', result.stdout)
        self.assertIn('Personal notes.', old.read_text())
        self.assertIn('Upstream chinese body.', old.read_text())
        self.assertIn('## Code Comment Guidelines', old.read_text())
        self.assertNotIn('Upstream english body.', old.read_text())
        self.assertFalse((self.home / '.claude/rules/waza-english.md').exists())

    def test_waza_engine_keeps_project_source_heading_in_shared_file(self):
        fixture = self.root / 'waza-h2'
        fixture.mkdir()
        content = '## English Coaching\n\nOriginal body.\n'
        (fixture / 'waza-english.md').write_text(content)
        result = self.source(
            f'rule_engine waza-english project both install {shlex.quote(str(fixture))} waza',
            cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(content, (self.root / 'docs/rules/waza-english.md').read_text())

    def test_waza_api_pins_commit_and_formats_selected_h2(self):
        self.waza_bundle(('chinese', 'english'))
        chinese = Path(self.env['WAZA_FILES']) / 'chinese.md'
        content = '## Chinese Anti-AI Patterns\n\nUpstream body.\n'
        chinese.write_text(content)
        result = self.source(
            'load_waza_rules\n'
            'export WAZA_COMMIT=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n'
            'apply_rule waza-chinese project both install waza', cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.root / 'docs/rules/waza-chinese.md'
        self.assertEqual(installed.read_text(), content)
        self.assertIn(content, (self.root / 'docs/rules/waza-chinese.md').read_text())
        fetches = (self.root / 'fetch.log').read_text()
        self.assertIn('/contents/rules?ref=' + 'a' * 40, fetches)
        self.assertIn('/' + 'a' * 40 + '/rules/chinese.md', fetches)
        self.assertNotIn('/' + 'b' * 40, fetches)
        self.assertNotIn('/rules/english.md', fetches)
        self.assertFalse((self.root / 'git.log').exists())

    def test_global_rule_headings_preserve_fences_unselected_blocks_and_user_content(self):
        fixture = self.root / 'headings'
        fixture.mkdir()
        for level in (1, 2):
            with self.subTest(source_level=level):
                title = '#' * level
                child = '#' * (level + 1)
                body = (f'{title} Example\n\n{child} Details\nText # stays.\n'
                        '```md\n# In code\n~~~\n```\n'
                        '   ~~~~ markdown\n## Also code\n~~~\n~~~~\n'
                        '    # Indented code\n')
                shutil.rmtree(self.home / '.claude', ignore_errors=True)
                source = fixture / 'waza-example.md'
                source.write_text(body)
                destination = self.home / '.codex/AGENTS.md'
                destination.parent.mkdir(exist_ok=True)
                personal = ('# Personal\nKeep me.\n'
                            '<!-- gwyn-space-skills: unselected:start -->\n'
                            '# Old rule\n<!-- gwyn-space-skills: unselected:end -->\n')
                destination.write_bytes(personal.replace('\n', '\r\n').encode())
                command = f'rule_engine waza-example global both install {shlex.quote(str(fixture))} waza'
                result = self.source(command)
                self.assertEqual(result.returncode, 0, result.stderr)
                text = destination.read_text()
                self.assertTrue(text.startswith(personal))
                self.assertEqual(text.count('# Global Rules\n'), 0)
                self.assertIn('\n## Example\n\n### Details\n', text)
                unchanged = body[body.index('Text # stays.'):]
                self.assertIn(unchanged, text)
                self.assertNotIn(b'\n', destination.read_bytes().replace(b'\r\n', b''))
                claude = self.home / '.claude/rules/waza-example.md'
                self.assertEqual(claude.read_text().count('# Example\n'), 1)
                self.assertTrue(claude.read_text().endswith('# Example\n\n## Details\n' + unchanged))
                before = destination.read_bytes()
                result = self.source(command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(destination.read_bytes().startswith(before))
                self.assertEqual(destination.read_text().count('## Example\n'), 2)
                self.assertNotIn('already installed', result.stdout)
                result = self.source('rule_engine waza-example global codex remove')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(destination.exists())

    def test_repeated_rule_batch_appends_in_place_without_backups_or_temp_files(self):
        self.waza_bundle(('chinese', 'clarity', 'english'))
        fixture = self.root / 'append-rules'
        fixture.mkdir()
        for name in ('chinese', 'clarity', 'english'):
            (fixture / f'waza-{name}.md').write_text(f'# {name}\nRule body.\n')
        command = '\n'.join(f'rule_engine waza-{name} global "codex claude pi" install {shlex.quote(str(fixture))} waza'
                            for name in ('chinese', 'clarity', 'english'))
        for eol in ('\n', '\r\n'):
            with self.subTest(eol=repr(eol)):
                for folder in ('.codex', '.claude', '.pi'):
                    shutil.rmtree(self.home / folder, ignore_errors=True)
                shared = [self.home / '.codex/AGENTS.md', self.home / '.pi/agent/AGENTS.md']
                for target in shared:
                    target.parent.mkdir(parents=True)
                    target.write_bytes(('Personal notes.\n').replace('\n', eol).encode())
                    target.chmod(0o640)
                # Any attempt to create a replacement or backup must fail the test.
                for command_name in ('mktemp', 'cp', 'mv'):
                    self.stub(command_name, '#!/bin/sh\necho forbidden >&2\nexit 99\n')
                first = self.source(command)
                self.assertEqual(first.returncode, 0, first.stderr)
                targets = shared + list((self.home / '.claude/rules').glob('*.md'))
                before = {t: (t.read_bytes(), t.stat().st_ino, t.stat().st_mode) for t in targets}
                second = self.source(command)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertEqual(second.stdout.count('installation complete ('), 9)
                for target, (content, inode, mode) in before.items():
                    self.assertTrue(target.read_bytes().startswith(content))
                    self.assertGreater(target.stat().st_size, len(content))
                    self.assertEqual(target.stat().st_ino, inode)
                    self.assertEqual(target.stat().st_mode, mode)
                    self.assertNotIn(b'gwyn-space-skills:', target.read_bytes())
                    self.assertNotIn(b'Installed from', target.read_bytes())

    def test_changed_rule_appends_after_previous_version_and_personal_text(self):
        self.waza_bundle(('clarity',))
        target = self.home / '.codex/AGENTS.md'
        command = 'apply_rule waza-clarity global codex install waza'
        self.assertEqual(self.source(command).returncode, 0)
        with target.open('a') as output:
            output.write('\nPersonal text after rules.')
        before = target.read_bytes()
        source = Path(self.env['WAZA_FILES']) / 'clarity.md'
        source.write_text('# clarity\nUpdated clarity body.\n')
        # Use a new process so the changed upstream body is downloaded again.
        result = self.source(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_bytes(), before + b'\n\n## clarity\nUpdated clarity body.\n')
        self.assertIn(b'Upstream clarity body.', target.read_bytes())

    def test_rule_append_preserves_existing_endings_and_link_target_inode(self):
        target = self.root / 'external-rules.md'
        link = self.home / '.claude/rules/code-comments.md'
        link.parent.mkdir(parents=True)
        link.symlink_to(target)
        for old in (b'', b'Personal', b'Personal\n', b'Personal\n\n', b'Personal\r\n'):
            with self.subTest(old=old):
                target.write_bytes(old)
                inode = target.stat().st_ino
                result = self.source('apply_rule code-comments global claude install project')
                self.assertEqual(result.returncode, 0, result.stderr)
                content = target.read_bytes()
                self.assertTrue(link.is_symlink())
                self.assertEqual(target.stat().st_ino, inode)
                self.assertTrue(content.startswith(old))
                eol = b'\r\n' if b'\r' in old else b'\n'
                if old:
                    self.assertIn(b'Personal' + eol + eol + b'# Code Comment Guidelines', content)
                else:
                    self.assertTrue(content.startswith(b'# Code Comment Guidelines'))
                self.assertNotIn(b'Installed from', content)

    def test_rule_engine_remove_unlinks_files_and_dangling_links(self):
        for agent, relative in [('codex', '.codex/AGENTS.md'), ('pi', '.pi/agent/AGENTS.md'),
                                ('claude', '.claude/rules/code-comments.md')]:
            destination = self.home / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            for linked in (False, True):
                with self.subTest(agent=agent, linked=linked):
                    if linked:
                        destination.symlink_to(self.root / 'absent-target')
                    else:
                        destination.write_text('Personal rules without markers.')
                    result = self.source(f'rule_engine code-comments global {agent} remove')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(destination.exists())
                    self.assertFalse(destination.is_symlink())

    def test_project_rules_use_shared_files_without_changing_legacy_instructions(self):
        legacy = {'AGENTS.md': b'User instructions.\r\n',
                  'AGENTS.override.md': b'Override instructions.\n',
                  '.claude/rules/code-comments.md': b'Claude rules.\n'}
        for relative, content in legacy.items():
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        command = 'apply_rule code-comments project "codex claude pi" install project'
        for count in (1, 2):
            result = self.source(command, cwd=self.root)
            self.assertEqual(result.returncode, 0, result.stderr)
            rule = self.root / 'docs/rules/code-comments.md'
            self.assertTrue(rule.is_file())
            self.assertEqual(rule.read_text().count('## Code Comment Guidelines'), count)
            self.assertEqual(result.stdout.count('installation complete ('), 1)
            self.assertNotIn('takes precedence', result.stderr)
            for relative, content in legacy.items():
                self.assertEqual((self.root / relative).read_bytes(), content)
        self.assertFalse((self.home / '.codex').exists())
        self.assertFalse((self.home / '.pi').exists())

    def test_project_rule_list_and_remove_preserve_legacy_files_and_link_targets(self):
        project, files = self.project_removal_fixture()
        outside = self.root / 'external-rule.md'
        outside.write_text('External rules.')
        link = project / 'docs/rules/linked.md'
        link.symlink_to(outside)
        broken = project / 'docs/rules/broken.md'
        broken.symlink_to(self.root / 'absent.md')
        other = project / 'docs/rules/notes.txt'
        other.write_text('Keep non-rule file.')
        nested = project / 'docs/rules/nested/keep.md'
        nested.parent.mkdir()
        nested.write_text('Keep nested document.')
        for codex, claude in ((True, False), (False, True), (True, True)):
            entries = self.project_entries(project, codex=codex, claude=claude, skills=False)
            self.assertEqual(len(entries), 4)
            self.assertEqual({e['agent'] for e in entries}, {'project'})
            self.assertTrue(all(e['relative'].startswith('docs/rules/') for e in entries))
        result = subprocess.run(['bash', str(SCRIPT), '--list-rule', '--project'],
                                env=self.env, cwd=project, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Shared project rules:', result.stdout)
        self.assertIn('linked.md', result.stdout)
        self.assertIn('broken.md [Unknown / local (broken link)]', result.stdout)
        self.assertNotIn('AGENTS.md', result.stdout)
        self.assertNotIn('.claude/rules', result.stdout)
        self.assertNotIn('notes.txt', result.stdout)
        self.assertNotIn('keep.md', result.stdout)
        self.assertEqual(self.inventory('select', *(e['id'] for e in entries), scope='project', cwd=project).returncode, 0)
        result = self.inventory('remove', scope='project', cwd=project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(link.is_symlink())
        self.assertFalse(broken.is_symlink())
        self.assertEqual(outside.read_text(), 'External rules.')
        self.assertEqual(other.read_text(), 'Keep non-rule file.')
        self.assertEqual(nested.read_text(), 'Keep nested document.')
        for relative in ('AGENTS.md', '.claude/rules/nested/.custom.md', '.claude/CLAUDE.md'):
            self.assertEqual((project / relative).read_bytes(), files[relative].encode())

    def test_project_rule_removal_rejects_symlinked_rule_directory_and_parent(self):
        project = self.root / 'project'
        project.mkdir()
        outside = self.root / 'outside-docs'
        (outside / 'rules').mkdir(parents=True)
        target = outside / 'rules/keep.md'
        target.write_text('External rules.')
        (project / 'docs').symlink_to(outside, target_is_directory=True)
        result = self.inventory('scan', 1, 0, 1, 0, scope='project', cwd=project)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsafe parent directory', result.stderr)
        (project / 'docs').unlink()
        (project / 'docs').mkdir()
        (project / 'docs/rules').symlink_to(outside / 'rules', target_is_directory=True)
        result = self.inventory('scan', 1, 0, 1, 0, scope='project', cwd=project)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Refusing symlinked directory', result.stderr)
        self.assertEqual(target.read_text(), 'External rules.')

    def test_global_local_rule_keeps_title_and_project_behavior(self):
        result = self.source('apply_rule code-comments global both install project', cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        source = (SCRIPT.parents[1] / 'rules/code-comments.md').read_text()
        codex = (self.home / '.codex/AGENTS.md').read_text()
        self.assertTrue(codex.startswith('# Global Rules\n'))
        self.assertIn('## Code Comment Guidelines\n', codex)
        self.assertIn(source.split('\n', 1)[1], codex)
        self.assertEqual((self.home / '.claude/rules/code-comments.md').read_text(), source)
        result = self.source('apply_rule code-comments project codex', cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        project = (self.root / 'docs/rules/code-comments.md').read_text()
        self.assertNotIn('# Global Rules', project)
        self.assertIn('## Code Comment Guidelines\n', project)
        self.assertIn(source.split('\n', 1)[1], project)
        before = (self.root / 'docs/rules/code-comments.md').read_bytes()
        repeated = self.source('apply_rule code-comments project codex', cwd=self.root)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertTrue((self.root / 'docs/rules/code-comments.md').read_bytes().startswith(before))
        self.assertEqual((self.root / 'docs/rules/code-comments.md').read_text().count('## Code Comment Guidelines'), 2)

    def test_waza_snapshot_dynamic_names_collision_and_additive_update(self):
        self.waza_bundle(('code-comments', 'new-rule'))
        old = self.home / '.codex/AGENTS.md'
        old.parent.mkdir()
        old.write_text('Personal\n<!-- gwyn-space-skills: agent-behavior:start -->\n'
                       'Legacy\n<!-- gwyn-space-skills: agent-behavior:end -->\n')
        result = self.source(
            'load_waza_rules\n'
            # Advance main after discovery: downloads must still use the discovered commit.
            'export WAZA_COMMIT=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n'
            'AGENT_ITEMS=(2)\n'
            'SELECTED_RULES=(code-comments waza-code-comments waza-new-rule)\n'
            'SELECTED_RULE_SOURCES=(project waza waza)\n'
            'execute_plan\n'
            'SELECTED_RULES=(waza-code-comments)\nSELECTED_RULE_SOURCES=(waza)\n'
            'execute_plan')
        self.assertEqual(result.returncode, 0, result.stderr)
        text = old.read_text()
        self.assertEqual(text.count('gwyn-space-skills: agent-behavior:start'), 1)
        self.assertEqual(text.count('Upstream code-comments body.'), 2)
        self.assertNotIn('gwyn-space-skills: waza-', text)
        self.assertIn('Personal', text)
        self.assertIn('Legacy', text)
        self.assertEqual((self.home / '.claude/rules/waza-code-comments.md').read_text(),
                         '# code-comments\nUpstream code-comments body.\n\n# code-comments\nUpstream code-comments body.\n')
        self.assertTrue((self.home / '.claude/rules/code-comments.md').exists())
        self.assertEqual(len((self.root / 'fetch.log').read_text().splitlines()), 4)

    def test_all_agent_pickers_default_to_codex_only(self):
        for page, title, size in [
            ('agent_choices', 'Choose Agents', 3),
            ('rule_targets', 'Rules: choose agents', 3),
            ('targets', 'Install skills for', 2),
            ('remove_agents', 'Remove: choose agents', 3),
            ('list_agents', 'List: choose agents', 3),
        ]:
            with self.subTest(page=page):
                command = ['bash', '-c', f'source {shlex.quote(str(SCRIPT))}\nLIST_SCOPE=global; LIST_RULES=1; interactive_setup {page}']
                term = Terminal(self.env, cwd=self.root, command=command)
                self.addCleanup(term.close)
                term.expect(title)
                term.expect(f'Item 1/{size}')
                frame = term.transcript.decode().rsplit(title, 1)[-1]
                self.assertIn('[x] Codex', frame)
                self.assertIn('[ ] Claude Code', frame)
                if size == 3:
                    self.assertIn('[ ] Pi', frame)
                term.send(b'q')
                self.assertEqual(term.finish(), 0)
        self.assertFalse(self.calls())

    def test_agent_flag_terminal_opens_agent_selection(self):
        term = Terminal(self.env, cwd=self.root, command=['bash', str(SCRIPT), '--agent'])
        self.addCleanup(term.close)
        term.expect('Choose Agents')
        term.expect('Item 1/3')
        for label in ['[x] Codex', '[ ] Claude Code (with statusline)', '[ ] Pi (with three packages)']:
            self.assertIn(label, term.transcript.decode())
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertFalse((self.home / '.codex').exists())

    def test_waza_failure_can_skip_without_touching_configs(self):
        self.env['FAIL_DOWNLOAD'] = '1'
        term = Terminal(self.env, cwd=self.root)
        self.addCleanup(term.close)
        term.expect('Item 1/6')
        term.send(b'\r')
        term.expect('Choose installation tasks')
        term.expect('Item 1/3')
        term.send(b' \r')
        term.expect('Waza rules unavailable')
        term.expect('fixture: Git clone unavailable')
        term.expect('Item 1/3')
        term.send(b'\x1b[B\r')
        term.expect('Choose rules')
        term.expect('Item 1/2')
        self.assertIn('[ ] Gwyntoria', re.sub(r'\x1b\[[0-9;]*m', '', term.transcript.decode()))
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertFalse((self.home / '.codex').exists())

    def test_rule_picker_c_continues_from_both_levels_preserving_selection(self):
        for child in (False, True):
            for selected in (False, True):
                with self.subTest(child=child, selected=selected):
                    term = self.rule_terminal(cwd=self.root)
                    self.assertIn(b'c: continue', term.transcript)
                    if child:
                        term.send(b'\r')
                        term.expect('Source: Waza')
                        term.expect('c: continue')
                        term.expect('Item 1/1')
                    if selected:
                        term.send(b' ')
                    term.send(b'c')
                    if selected:
                        term.expect('Rules: choose scope')
                        term.expect('Item 1/2')
                        term.send(b'b')
                        term.expect('Choose rules')
                        term.expect('[x] Waza')
                    else:
                        term.expect('Confirm installation')
                        term.expect('Item 1/2')
                    term.send(b'q')
                    self.assertEqual(term.finish(), 0)
        self.assertFalse((self.home / '.codex/AGENTS.md').exists())

    def test_rule_tree_group_selection_installs_every_rule_with_correct_source(self):
        self.waza_bundle(('anti-patterns', 'chinese', 'code-comments'))
        term = self.rule_terminal(cwd=self.root)
        term.send(b' ')
        term.expect('[x] Waza')
        term.expect('(3/3)')
        term.send(b'\x1b[B ')
        term.expect('[x] Gwyntoria')
        term.expect('(3/3)')
        term.send(b'\x1b[B\r')
        self.rule_agents_and_scope(term)
        term.send(b'\r')
        term.expect('6 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        text = '\n'.join(file.read_text() for file in (self.root / 'docs/rules').glob('*.md'))
        for name in ('waza-anti-patterns', 'waza-chinese', 'waza-code-comments',
                     'code-comments', 'chinese-punctuation', 'writing-repo'):
            self.assertNotIn(f'gwyn-space-skills: {name}:start', text)
        self.assertIn('Upstream code-comments body.', text)
        self.assertNotIn('Installed from', text)

    def test_rule_tree_children_partial_state_and_group_toggle(self):
        self.waza_bundle(('anti-patterns', 'chinese', 'clarity'))
        term = self.rule_terminal(cwd=self.root)
        term.send(b' \r')
        term.expect('Source: Waza')
        for name in ('anti-patterns', 'chinese', 'clarity'):
            term.expect('[x] ' + name)
        term.expect('Item 1/3')
        term.send(b' b')  # deselect one child and return to sources
        term.expect('[-] Waza')
        term.expect('(2/3)')
        term.send(b' ')
        term.expect('[x] Waza')
        term.expect('(3/3)')
        term.send(b' ')
        term.expect('[ ] Waza')
        term.expect('(0/3)')
        term.send(b'\x1b[B \r')
        term.expect('Source: Gwyntoria')
        term.expect('[x] code-comments')
        term.send(b'n')
        term.expect('[ ] code-comments')
        term.send(b'ab')
        term.expect('[x] Gwyntoria')
        term.expect('(3/3)')
        term.send(b'n')
        term.expect('[ ] Waza')
        term.expect('[ ] Gwyntoria')
        term.send(b'a')
        term.expect('[x] Waza')
        term.expect('[x] Gwyntoria')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertFalse((self.root / 'AGENTS.md').exists())

    def test_project_rules_install_current_subdirectory_and_review_back(self):
        project = self.root / 'project'
        project.mkdir()
        subprocess.run(['git', 'init', '-q', str(project)], check=True, capture_output=True)
        nested = project / 'nested'
        nested.mkdir()
        (project / 'AGENTS.md').write_text('root must stay unchanged\n')
        personal = 'Personal project notes.\n'
        (nested / 'AGENTS.md').write_text(personal)
        rule = nested / 'docs/rules/code-comments.md'
        rule.parent.mkdir(parents=True)
        rule.write_text('Existing rule notes.\n')
        term = self.rule_terminal(cwd=nested)
        self.assertIn('[ ] Waza', re.sub(r'\x1b\[[0-9;]*m', '', term.transcript.decode()))
        self.assertIn('[ ] Gwyntoria', re.sub(r'\x1b\[[0-9;]*m', '', term.transcript.decode()))
        term.send(b'\x1b[B\r\x1b[B \r\x1b[B\r')
        self.rule_agents_and_scope(term)
        self.assertIn(str(rule), term.transcript.decode())
        self.assertNotIn('Rules: choose agents', term.transcript.decode())
        self.assertIn('Rule source:', term.transcript.decode())
        frame = term.transcript.decode().rsplit('\x1b[H\x1b[2J', 1)[-1]
        self.assertIn(str(rule), frame)
        self.assertIn('Execution plan:', frame)
        self.assertIn('project / code-comments -> docs/rules/code-comments.md', frame)
        term.send(b'b')
        term.expect('Rules: choose scope')
        term.expect('> Project')
        term.send(b'b')
        term.expect('Choose rules')
        term.expect('[-] Gwyntoria')
        term.expect('Item 3/3')
        term.send(b'\r')
        term.expect('Rules: choose scope')
        term.expect('> Project')
        term.send(b'\r')
        term.expect('Confirm installation')
        term.expect('Item 1/2')
        term.send(b'\r')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        text = rule.read_text()
        self.assertEqual((nested / 'AGENTS.md').read_text(), personal)
        self.assertIn('Existing rule notes.', text)
        self.assertNotIn('<!-- gwyn-space-skills: code-comments:start -->', text)
        self.assertNotIn('Installed from', text)
        self.assertEqual((project / 'AGENTS.md').read_text(), 'root must stay unchanged\n')
        self.assertFalse((nested / '.claude').exists())
        result = self.source('apply_rule code-comments project codex', cwd=nested)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(rule.read_text().startswith(text))
        self.assertEqual(rule.read_text().count('## Code Comment Guidelines'), 2)

    def test_rule_pages_q_defaults_and_scope_selection_preserved(self):
        for page in ['rules', 'scope', 'agents', 'confirm']:
            with self.subTest(page=page):
                term = self.rule_terminal(cwd=self.root)
                if page != 'rules':
                    term.send(b' \x1b[A\r')
                    term.expect('Rules: choose scope')
                    term.expect('Item 1/2')
                if page in ['agents', 'confirm']:
                    term.send(b'\r')
                    term.expect('Rules: choose agents')
                    term.expect('Item 1/3')
                    for label in ['[x] Codex', '[ ] Claude Code', '[ ] Pi']:
                        self.assertIn(label, term.transcript.decode())
                if page == 'confirm':
                    term.send(b'\r')
                    term.expect('Confirm installation')
                    term.expect('Item 1/2')
                term.send(b'q')
                self.assertEqual(term.finish(), 0)
                self.assertFalse((self.home / '.codex/AGENTS.md').exists())
                self.assertFalse((self.home / '.pi').exists())
        term = self.rule_terminal(cwd=self.root)
        term.send(b'an\x1b[B\r\x1b[B \r\x1b[B\r')  # all, none, expand project, select code-comments, continue
        self.rule_agents_and_scope(term, agents='claude', scope='global')
        term.send(b'b')
        term.expect('Rules: choose agents')
        term.expect('> [x] Claude Code')
        term.expect('[ ] Pi')
        frame = term.transcript.decode().rsplit('\x1b[H\x1b[2J', 1)[-1]
        self.assertIn('[ ] Codex', frame)
        self.assertIn('[ ] Pi', frame)
        term.send(b'b')
        term.expect('Rules: choose scope')
        term.expect('> Global')
        term.send(b'b')
        term.expect('Choose rules')
        term.expect('[-] Gwyntoria')
        term.expect('Item 3/3')
        term.send(b'b')
        term.expect('Choose installation tasks')
        term.expect('> [x] Rules')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)

    def test_global_rule_ui_installs_only_selected_agent(self):
        for agent in ['default', 'claude', 'codex', 'pi']:
            with self.subTest(agent=agent):
                # Keep each selection isolated so unexpected destinations are visible.
                for directory in ['.claude', '.codex', '.pi']:
                    shutil.rmtree(self.home / directory, ignore_errors=True)
                term = self.rule_terminal(cwd=self.root)
                term.send(b' \x1b[A\r')
                self.rule_agents_and_scope(term, agents=agent, scope='global')
                destinations = {
                    'claude': self.home / '.claude/rules/waza-anti-patterns.md',
                    'codex': self.home / '.codex/AGENTS.md',
                    'pi': self.home / '.pi/agent/AGENTS.md',
                }
                frame = term.transcript.decode().rsplit('\x1b[H\x1b[2J', 1)[-1]
                selected = {'codex'} if agent == 'default' else {agent}
                for name, destination in destinations.items():
                    self.assertEqual(str(destination) in frame, name in selected)
                term.send(b'\r')
                term.expect('1 succeeded, 0 failed')
                self.assertEqual(term.finish_action(), 0)
                for name, destination in destinations.items():
                    self.assertEqual(destination.exists(), name in selected)

    def test_pi_global_engine_custom_directory_appends_and_preserves_content(self):
        self.env['PI_CODING_AGENT_DIR'] = '~/custom pi'
        destination = self.home / 'custom pi/AGENTS.md'
        destination.parent.mkdir()
        personal = 'Personal notes.\n<!-- gwyn-space-skills: broken:start -->\n'
        destination.write_text(personal)
        command = 'apply_rule code-comments global pi install project'
        for count in (1, 2):
            result = self.source(command)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = destination.read_text()
            self.assertTrue(text.startswith(personal))
            self.assertEqual(text.count('## Code Comment Guidelines'), count)
        self.assertFalse((self.home / '.pi').exists())

    def test_pi_global_preflight_failure_prevents_other_agent_writes(self):
        blocked = self.home / 'not-a-directory'
        blocked.write_text('keep me')
        self.env['PI_CODING_AGENT_DIR'] = str(blocked)
        result = self.source('apply_rule code-comments global "codex claude pi" install project')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(blocked.read_text(), 'keep me')
        self.assertFalse((self.home / '.codex/AGENTS.md').exists())
        self.assertFalse((self.home / '.claude/rules/code-comments.md').exists())

    def test_mixed_rule_sources_install_to_selected_scope(self):
        for scope in ['project', 'global']:
            with self.subTest(scope=scope):
                project = self.root / scope
                project.mkdir()
                term = self.rule_terminal(cwd=project)
                term.send(b' \x1b[B\r\x1b[B \r\x1b[B\r')  # Waza group plus code-comments
                self.rule_agents_and_scope(term, scope=scope)
                frame = term.transcript.decode().rsplit('\x1b[H\x1b[2J', 1)[-1]
                self.assertIn('tw93/Waza @ main', frame)
                self.assertIn('rules/code-comments.md', frame)
                term.send(b'\r')
                term.expect('2 succeeded, 0 failed')
                self.assertEqual(term.finish_action(), 0)
                codex = project / 'docs/rules/waza-anti-patterns.md' if scope == 'project' else self.home / '.codex/AGENTS.md'
                text = codex.read_text()
                self.assertIn('Upstream anti-patterns body.', text)
                self.assertNotIn('Installed from', text)
                self.assertNotIn('waza-anti-patterns:start', text)
                self.assertNotIn('code-comments:start', text)
                if scope == 'project':
                    self.assertTrue((project / 'docs/rules/code-comments.md').exists())
                    self.assertFalse((project / 'AGENTS.md').exists())
                    self.assertNotIn('Rules: choose agents', term.transcript.decode())
                    self.assertFalse((project / '.claude').exists())
                    self.assertFalse((self.home / '.pi').exists())
                else:
                    claude = self.home / '.claude/rules'
                    self.assertTrue((claude / 'code-comments.md').exists())
                    self.assertTrue((claude / 'waza-anti-patterns.md').exists())
                    pi = self.home / '.pi/agent/AGENTS.md'
                    self.assertEqual(pi.read_text(), codex.read_text())

    def test_rule_engine_preserves_old_and_unbalanced_markers_while_appending(self):
        project = self.root / 'project'
        project.mkdir()
        destination = project / 'docs/rules/code-comments.md'
        destination.parent.mkdir(parents=True)
        for old in ('Personal\n<!-- gwyn-space-skills: code-comments:start -->\nold body\n'
                    '<!-- gwyn-space-skills: code-comments:end -->\n',
                    'Personal\n<!-- gwyn-space-skills: code-comments:start -->\nkeep\n'):
            destination.write_text(old)
            result = self.source('apply_rule code-comments project codex', cwd=project)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(destination.read_text().startswith(old))
            self.assertEqual(destination.read_text().count('code-comments:start'), 1)
            self.assertIn('## Code Comment Guidelines', destination.read_text())

    def test_legacy_global_copy_is_kept_without_backup_or_migration(self):
        fixture = self.root / 'legacy'
        fixture.mkdir()
        original = '# Legacy behavior\nLegacy rule\n'
        (fixture / 'agent-behavior.md').write_text(original)
        for agent, relative in [('codex', '.codex/AGENTS.md'), ('claude', '.claude/CLAUDE.md')]:
            destination = self.home / relative
            destination.parent.mkdir(exist_ok=True)
            destination.write_text(original)
            result = self.source(f'rule_engine agent-behavior global {agent} install {shlex.quote(str(fixture))} global')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(destination.read_text().startswith(original))
            self.assertEqual(destination.read_text().count('Legacy rule'), 2)
            self.assertEqual(list(destination.parent.iterdir()), [destination])

    def test_standalone_agent_install_downloads_once_and_cleans_resources(self):
        self.remote_bundle()
        script = self.standalone()
        scratch = self.root / 'scratch'
        scratch.mkdir()
        self.env['TMPDIR'] = str(scratch)
        result = subprocess.run(['bash', str(script), '--agent'], env=self.env, cwd=self.root,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('7 succeeded, 0 failed', result.stdout)
        self.assertFalse((self.home / '.codex/AGENTS.md').exists())
        self.assertFalse((self.home / '.claude/CLAUDE.md').exists())
        self.assertIn('installing all Agents', result.stdout)
        self.assertTrue((self.home / '.claude/statusline.sh').exists())
        self.assertEqual(len((self.root / 'fetch.log').read_text().splitlines()), 1)
        self.assertEqual(list(scratch.iterdir()), [])

    def test_local_rules_win_and_missing_directory_fetches_without_merging(self):
        self.remote_bundle()
        script = self.standalone()
        local = script.parent.parent / 'rules'
        local.mkdir(parents=True)
        (local / 'local-only.md').write_text('# Local only\nlocal content\n')
        result = self.source('RULE_SCOPE=project\nload_rule_catalog\nprintf "%s\\n" "${RULE_NAMES_PROJECT[@]}"', script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('local-only', result.stdout)
        self.assertNotIn('code-comments', result.stdout)
        self.assertFalse((self.root / 'fetch.log').exists())
        shutil.rmtree(local)
        result = self.source('RULE_SCOPE=project\nload_rule_catalog\nprintf "%s\\n" "${RULE_NAMES_PROJECT[@]}"', script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('code-comments', result.stdout)
        local.mkdir()
        (local / 'local-only.md').write_text('# Local only\nlocal content\n')
        (local / 'bad.md').write_text('missing heading\n')
        before = (self.root / 'fetch.log').read_text()
        result = self.source('RULE_SCOPE=project\nload_rule_catalog', script)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Rule must start with H1', result.stderr)
        self.assertEqual((self.root / 'fetch.log').read_text(), before)

    def test_standalone_project_ui_uses_remote_rules_in_caller_directory(self):
        self.remote_bundle()
        script = self.standalone()
        project = self.root / 'non-git project'
        project.mkdir()
        term = self.rule_terminal(cwd=project, script=script)
        term.send(b'\x1b[B\r \r\x1b[B\r')
        self.rule_agents_and_scope(term, agents='codex')
        frame = term.transcript.decode().rsplit('\x1b[H\x1b[2J', 1)[-1]
        self.assertIn(str(project / 'docs/rules/chinese-punctuation.md'), frame)
        self.assertIn('GitHub gwyntoria/skills @ main', frame)
        term.send(b'\r')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertTrue((project / 'docs/rules/chinese-punctuation.md').exists())
        self.assertFalse((project / 'AGENTS.md').exists())
        self.assertFalse((project / '.claude').exists())
        self.assertFalse((script.parent / 'AGENTS.md').exists())
        self.assertEqual(len((self.root / 'fetch.log').read_text().splitlines()), 3)

    def test_remote_failure_preserves_configs_and_continues_tasks(self):
        script = self.standalone()
        self.env['FAIL_DOWNLOAD'] = '1'
        target = self.home / '.codex/AGENTS.md'
        target.parent.mkdir()
        target.write_text('keep existing\n')
        result = subprocess.run(['bash', str(script), '--agent'], env=self.env,
                                capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('6 succeeded, 1 failed', result.stdout)
        self.assertEqual(target.read_text(), 'keep existing\n')
        self.assertFalse((self.home / '.claude/statusline.sh').exists())

    def test_script_symlink_uses_real_local_resources(self):
        link = self.root / 'linked-command'
        link.symlink_to(SCRIPT)
        result = self.source('apply_rule code-comments project codex', link, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / 'docs/rules/code-comments.md').exists())
        self.assertFalse((self.root / 'fetch.log').exists())

    def test_command_install_from_repository_and_remote_update(self):
        result = self.source('install_setup_command')
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.home / '.local/bin/agent-setup'
        self.assertEqual(installed.read_bytes(), SCRIPT.read_bytes())
        self.assertTrue(installed.stat().st_mode & 0o111)
        self.assertIn('Add this directory to PATH', result.stdout)
        self.assertFalse((self.root / 'fetch.log').exists())
        remote = self.root / 'latest.sh'
        remote.write_text('#!/usr/bin/env bash\nprintf "new version\\n"\n')
        self.env['REMOTE_SCRIPT'] = str(remote)
        term = Terminal(self.env, script=installed, cwd=self.root)
        self.addCleanup(term.close)
        term.expect('Item 1/6')
        term.send(b'\x1b[B' * 3 + b'\r')
        term.expect('Update this command?')
        term.expect('Continue? [Y/n]')
        self.assertEqual(installed.read_bytes(), SCRIPT.read_bytes())
        self.assertFalse((self.root / 'fetch.log').exists())
        term.send(b'\n')
        term.expect('used on next launch')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertEqual(installed.read_bytes(), remote.read_bytes())
        self.assertNotIn('new version\r\n', term.transcript.decode())
        result = subprocess.run([str(installed)], capture_output=True, text=True)
        self.assertEqual(result.stdout, 'new version\n')

    def test_command_confirmation_install_update_cancel_back_and_exit(self):
        destination = self.home / '.local/bin/agent-setup'
        for installed in (False, True):
            if installed:
                destination.parent.mkdir(parents=True)
                destination.write_text('existing command\n')
            for answer in (b'n\n', b'N\n', b'b\n', b'q\n', b'yes\n'):
                with self.subTest(installed=installed, answer=answer):
                    term = self.terminal()
                    term.send(b'\x1b[B' * 3 + b'\r')
                    term.expect(('Update' if installed else 'Install') + ' this command?')
                    term.expect(str(destination))
                    term.expect('Continue? [Y/n]')
                    self.assertEqual(destination.exists(), installed)
                    term.send(answer)
                    if answer == b'b\n':
                        term.expect('Agent setup')
                        term.expect('Item 4/6')
                        term.send(b'q')
                        self.assertEqual(term.finish(), 0)
                    elif answer == b'q\n':
                        self.assertEqual(term.finish(), 0)
                    else:
                        term.expect('Cancelled.')
                        self.assertEqual(term.finish_action(), 0)
                    if installed:
                        self.assertEqual(destination.read_text(), 'existing command\n')
                    else:
                        self.assertFalse(destination.parent.exists())
                    self.assertFalse((self.root / 'fetch.log').exists())

    def test_command_confirmation_installs_after_yes_or_enter(self):
        destination = self.home / '.local/bin/agent-setup'
        for answer in (b'y\n', b'Y\n', b'\n'):
            with self.subTest(answer=answer):
                term = self.terminal()
                term.send(b'\x1b[B' * 3 + b'\r')
                term.expect('Install this command?')
                term.expect('Continue? [Y/n]')
                self.assertFalse(destination.exists())
                term.send(answer)
                term.expect('1 succeeded, 0 failed')
                self.assertEqual(term.finish_action(), 0)
                self.assertEqual(destination.read_bytes(), SCRIPT.read_bytes())
                destination.unlink()

    def test_command_update_failure_keeps_existing_bytes(self):
        script = self.standalone()
        destination = self.home / '.local/bin/agent-setup'
        destination.parent.mkdir(parents=True)
        destination.write_text('old command\n')
        bad = self.root / 'invalid.sh'
        bad.write_text('if then\n')
        self.env['REMOTE_SCRIPT'] = str(bad)
        for failure in ['syntax', 'download', 'empty']:
            with self.subTest(failure=failure):
                self.env.pop('FAIL_DOWNLOAD', None)
                if failure == 'download':
                    self.env['FAIL_DOWNLOAD'] = '1'
                if failure == 'empty':
                    bad.write_text('')
                result = self.source('install_setup_command', script)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(destination.read_text(), 'old command\n')
                self.assertEqual(list(destination.parent.glob('.agent-setup.*')), [])


    def test_session_failure_then_success_preserves_exit_status(self):
        settings = self.home / '.claude/settings.json'
        settings.parent.mkdir()
        settings.write_text('invalid json')
        term = self.terminal()
        term.send(b'\r')
        term.expect('Item 1/3')
        term.send(b'\x1b[B' * 2 + b' \r')
        term.expect('Choose Agents')
        term.expect('Item 1/3')
        term.send(b'n\x1b[B \r')
        term.expect('Continue? [Y/n]')
        term.send(b'y\n')
        term.expect('1 succeeded, 1 failed')
        term.return_home()
        self.assertEqual(settings.read_text(), 'invalid json')
        term.send(b'\r')
        term.expect('Choose installation tasks')
        term.expect('Item 1/3')
        frame = term.transcript.decode().rsplit('\x1b[H\x1b[2J', 1)[-1]
        self.assertNotIn('[x]', frame)
        term.send(b'\x1b[B' * 2 + b' \r')
        term.expect('Choose Agents')
        term.expect('Item 1/3')
        term.send(b'n \r')
        term.expect('Continue? [Y/n]')
        term.send(b'y\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 1)

    def test_session_preparation_failure_returns_home_and_can_continue(self):
        command = ['bash', '-c', f"""source {shlex.quote(str(SCRIPT))}
require_command() {{
    if [ "$1" = npx ]; then printf 'fixture: missing npx\n' >&2; return 1; fi
    command -v "$1" >/dev/null 2>&1
}}
main"""]
        term = Terminal(self.env, command=command)
        self.addCleanup(term.close)
        term.expect('Item 1/6')
        term.send(b'\r')
        term.expect('Item 1/3')
        term.send(b'\x1b[B \r')
        term.expect('fixture: missing npx')
        term.expect('Installation preparation failed')
        term.return_home()
        term.send(b'\x1b[B' * 2 + b'\r')
        term.expect('No setup backups found.')
        self.assertEqual(term.finish_action(), 1)
        self.assertFalse(self.calls())

    def test_session_rule_catalog_failure_returns_home(self):
        script = self.standalone()
        self.env['FAIL_DOWNLOAD'] = '1'
        term = Terminal(self.env, script=script)
        self.addCleanup(term.close)
        term.expect('Item 1/6')
        term.send(b'\r')
        term.expect('Item 1/3')
        term.send(b' \r')
        term.expect('project rule catalog unavailable')
        term.return_home()
        term.send(b'q')
        self.assertEqual(term.finish(), 1)



    def test_session_reuses_downloaded_resources_for_multiple_actions(self):
        self.remote_bundle()
        script = self.standalone()
        term = Terminal(self.env, script=script)
        self.addCleanup(term.close)
        term.expect('Item 1/6')
        for _ in range(2):
            term.send(b'\r')
            term.expect('Choose installation tasks')
            term.expect('Item 1/3')
            term.send(b'\x1b[B' * 2 + b' \r')
            term.expect('Choose Agents')
            term.expect('Item 1/3')
            term.send(b'n\x1b[B \r')
            term.expect('Continue? [Y/n]')
            term.send(b'y\n')
            term.expect('2 succeeded, 0 failed')
            term.return_home()
        self.assertEqual(term.exit_home(), 0)
        self.assertEqual(len((self.root / 'fetch.log').read_text().splitlines()), 1)
        self.assertTrue((self.home / '.claude/statusline.sh').exists())

    def test_session_q_exits_from_result_pause(self):
        term = self.terminal()
        term.send(b'\x1b[B' * 2 + b'\r')
        term.expect('No setup backups found.')
        term.expect('Press Enter to return to the main menu')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)

    def test_repository_install_partial_selection_batching_and_agent_target(self):
        term = self.install_skill_terminal()
        term.send(b'\r')
        term.expect('Repository: tw93/waza')
        term.expect('Item 1/3')
        term.send(b'\x1b[B b')
        term.expect('Install skills by repository')
        term.expect('[-] tw93/waza')
        term.expect('(2/3)')
        term.send(b'b')
        term.expect('Choose skill repositories')
        term.expect('[x] tw93/waza')
        term.send(b'b')
        term.expect('Choose installation tasks')
        term.expect('Item 2/3')
        term.send(b'\r')
        term.expect('Choose skill repositories')
        term.expect('[x] tw93/waza')
        term.send(b'\r')
        term.expect('Install skills by repository')
        term.expect('[-] tw93/waza')
        term.send(b'\r')
        term.expect('[x] waza-first')
        term.expect('[x] waza-last')
        term.send(b'\r')
        term.expect('Install skills by repository')
        term.send(b'\x1b[A\r')
        term.expect('Install skills for')
        term.expect('Item 1/2')
        term.send(b'n\x1b[B \r')
        term.expect('Continue? [Y/n]')
        self.assertIn(b'\x1b[32m', term.transcript)
        term.send(b'y\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        calls = self.calls()
        # Only the chosen repository is pulled; the other sources stay untouched.
        self.assertEqual(sum('--list' in call for call in calls), 1)
        installs = [c for c in calls if '--list' not in c]
        self.assertEqual(len(installs), 1)
        self.assertEqual(installs[0][installs[0].index('--skill') + 1:installs[0].index('--agent')], ['waza-first', 'waza-last'])
        self.assertEqual(installs[0][installs[0].index('--agent') + 1:], ['claude-code', '--global', '--yes'])

    def test_repository_select_all_none_partial_toggle_and_q(self):
        term = self.install_skill_terminal(repos='all')
        term.send(b'an\r')
        term.expect('Repository: tw93/waza')
        term.expect('Item 1/3')
        term.send(b'an \r')
        term.expect('[-] tw93/waza')
        term.expect('(1/3)')
        term.send(b' ')
        term.expect('[x] tw93/waza')
        term.expect('(3/3)')
        term.send(b' ')
        term.expect('[ ] tw93/waza')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        term = self.install_skill_terminal(repos='all')
        term.send(b'\r')
        term.expect('Repository: tw93/waza')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertTrue(all('--list' in call for call in self.calls()))

    def test_skill_picker_c_continues_from_both_levels_preserving_selection(self):
        for child in (False, True):
            for selected in (False, True):
                with self.subTest(child=child, selected=selected):
                    term = self.install_skill_terminal()
                    self.assertIn(b'c: continue', term.transcript)
                    if child:
                        term.send(b'\r')
                        term.expect('Repository: tw93/waza')
                        term.expect('c: continue')
                        term.expect('Item 1/3')
                    term.send(b'n')
                    if selected:
                        term.send(b' ')
                    term.send(b'c')
                    if selected:
                        term.expect('Install skills for')
                        term.expect('Item 1/2')
                        term.send(b'b')
                        term.expect('Install skills by repository')
                        term.expect('(1/3)' if child else '(3/3)')
                    else:
                        term.expect('Results: 0 succeeded, 0 failed')
                        term.expect('Press Enter to return to the main menu')
                    term.send(b'q')
                    self.assertEqual(term.finish(), 0)
        self.assertTrue(all('--list' in call for call in self.calls()))

    def test_skill_picker_c_preserves_dependencies_through_installation(self):
        self.env['MATT_SKILLS'] = 'implement tdd codebase-design code-review independent'
        term = self.install_skill_terminal(repos=(2,))
        term.send(b'\r')
        term.expect('Repository: mattpocock/skills')
        term.expect('Item 1/5')
        term.send(b'n c')
        term.expect('Install skills for')
        term.expect('Item 1/2')
        term.send(b'\r')
        term.expect('Continue? [Y/n]')
        term.send(b'y\r')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        for name in ('implement', 'tdd', 'codebase-design', 'code-review'):
            self.assertEqual((self.home / '.agents/skills' / name / 'SKILL.md').read_text(), name)
        self.assertFalse((self.home / '.agents/skills/independent').exists())

    def test_matt_dependency_selection_and_cascade(self):
        self.env['MATT_SKILLS'] = 'implement tdd codebase-design code-review'
        term = self.install_skill_terminal(repos=(2,))
        term.send(b'\r')
        term.expect('Repository: mattpocock/skills')
        term.expect('Item 1/4')
        term.send(b'n ')
        term.expect('[x] implement')
        term.expect('[x] tdd')
        term.expect('[dependency: implement]')
        term.expect('[x] codebase-design')
        term.expect('[dependency: implement]')
        term.send(b'\x1b[B ')
        term.expect('Also deselected implement.')
        term.expect('[ ] implement')
        term.expect('[ ] tdd')
        term.expect('[ ] codebase-design')
        term.expect('[ ] code-review')
        self.assertIn(b'Also deselected \x1b[32mimplement\x1b[0m.', term.transcript)
        self.assertIn(b'Deselected \x1b[32mcodebase-design\x1b[0m.', term.transcript)
        self.assertIn(b'[dependency: \x1b[32mimplement\x1b[0m]', term.transcript)
        term.send(b'q')
        self.assertEqual(term.finish(), 0)

    def test_matt_branch_dependencies(self):
        cases = [
            ('retro', ['writing-for-agents']),
            ('triage', ['grilling', 'domain-modeling']),
            ('improve-codebase-architecture', ['codebase-design', 'grilling', 'domain-modeling']),
            ('wayfinder', ['grilling', 'domain-modeling', 'prototype', 'research']),
            ('implement-spec', ['tdd', 'code-review', 'codebase-design']),
        ]
        for root, dependencies in cases:
            with self.subTest(skill=root):
                self.env['MATT_SKILLS'] = ' '.join([root, *dependencies, 'independent'])
                term = self.install_skill_terminal(repos=(2,))
                term.send(b'\r')
                term.expect('Item 1/%d' % (len(dependencies) + 2))
                term.send(b'n ')
                term.expect('[x] ' + root)
                for dependency in dependencies:
                    term.expect('[x] ' + dependency)
                    term.expect('[dependency: ' + root + ']')
                term.expect('[ ] independent')
                term.send(b' ')
                for dependency in dependencies:
                    term.expect('[ ] ' + dependency)
                term.send(b'q')
                self.assertEqual(term.finish(), 0)

    def test_matt_explicit_selection_survives_back_and_install(self):
        self.env['MATT_SKILLS'] = 'implement tdd codebase-design code-review'
        term = self.install_skill_terminal(repos=(2,))
        term.send(b'\r')
        term.expect('Item 1/4')
        # Explicit tdd, then implement. Removing implement must keep tdd.
        term.send(b'n\x1b[B \x1b[A b')
        term.expect('Install skills by repository')
        term.send(b'b')
        term.expect('Choose skill repositories')
        term.send(b'\r\r')
        term.expect('Repository: mattpocock/skills')
        term.expect('Item 1/4')
        term.send(b' ')
        term.expect('[ ] implement')
        term.expect('[x] tdd')
        term.expect('[x] codebase-design')
        term.expect('[dependency: tdd]')
        term.expect('[ ] code-review')
        term.send(b'b\x1b[B\r')
        term.expect('Install skills for')
        term.expect('Item 1/2')
        term.send(b'\r')
        term.expect('Continue? [Y/n]')
        term.send(b'y\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        installs = [c for c in self.calls() if '--list' not in c]
        self.assertEqual(len(installs), 1)
        call = installs[0]
        self.assertEqual(call[call.index('--skill') + 1:call.index('--agent')],
                         ['tdd', 'codebase-design'])

    def test_matt_shared_dependencies_and_bulk_selection(self):
        self.env['MATT_SKILLS'] = 'grill-me grill-with-docs grilling domain-modeling'
        term = self.install_skill_terminal(repos=(2,))
        term.send(b'\r')
        term.expect('Item 1/4')
        term.send(b'n \x1b[B \x1b[A ')
        term.expect('[ ] grill-me')
        term.expect('[x] grill-with-docs')
        term.expect('[x] grilling')
        term.expect('[dependency: grill-with-docs]')
        # All promotes dependencies to explicit choices; removing wrappers keeps them.
        term.send(b'a \x1b[B ')
        term.expect('[ ] grill-me')
        term.expect('[ ] grill-with-docs')
        term.expect('[x] grilling')
        term.expect('[x] domain-modeling')
        term.send(b'n')
        term.expect('[ ] grilling')
        term.expect('[ ] domain-modeling')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)

    def test_matt_missing_transitive_dependency_blocks_selection(self):
        self.env['MATT_SKILLS'] = 'implement tdd code-review independent'
        term = self.install_skill_terminal(repos=(2,))
        self.assertIn(b'Cannot select \x1b[32mimplement\x1b[0m: missing dependency \x1b[32mcodebase-design\x1b[0m.', term.transcript)
        self.assertIn(b'Cannot select \x1b[32mtdd\x1b[0m: missing dependency \x1b[32mcodebase-design\x1b[0m.', term.transcript)
        term.send(b'\r')
        term.expect('Item 1/4')
        term.send(b' ')
        term.expect('Cannot select implement: missing dependency codebase-design.')
        term.expect('[ ] implement')
        term.expect('[x] independent')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)

    def test_matt_removal_picker_does_not_complete_dependencies(self):
        lock = self.home / '.agents/.skill-lock.json'
        lock.write_text(json.dumps({'version': 3, 'skills': {
            name: {'source': 'mattpocock/skills', 'sourceType': 'github'}
            for name in ['tdd', 'codebase-design']}}))
        for name in ['tdd', 'codebase-design']:
            folder = self.home / '.agents/skills' / name
            folder.mkdir(parents=True)
            (folder / 'SKILL.md').write_text(name)
        term = self.removal_terminal()
        term.expect('Remove skills by repository')
        term.expect('Item 1/3')
        # Matt sorts before the separate Local group containing "existing".
        term.send(b'\r')
        term.expect('Repository: mattpocock/skills')
        term.expect('Item 1/2')
        term.send(b'\x1b[B ')
        term.expect('[ ] codebase-design [Codex:directory]')
        term.expect('[x] tdd [Codex:directory]')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)

    def test_repository_whole_selection_reuses_catalog_across_tasks(self):
        term = self.install_skill_terminal(repos='all')
        for run in range(2):
            term.send(b'a\x1b[A\r')  # every skill, then Continue
            term.expect('Install skills for')
            term.expect('Item 1/2')
            term.send(b'\r')
            term.expect('Continue? [Y/n]')
            term.send(b'y\n')
            term.expect('6 succeeded, 0 failed')
            term.return_home()
            if run == 0:
                term.send(b'\r')
                term.expect('Item 1/3')
                term.send(b'\x1b[B \r')
                term.expect('Choose skill repositories')
                term.send(b'a\r')
                term.expect('Install skills by repository')
        self.assertEqual(term.exit_home(), 0)
        self.assertEqual(sum('--list' in call for call in self.calls()), 4)

    def test_inventory_groups_by_actual_entries_and_separates_agents(self):
        lock, data = self.lock_fixture()
        malformed = self.home / '.agents/skills/malformed'
        malformed.mkdir()
        data['skills']['malformed'] = {'sourceType': 'github', 'source': {'unsupported': True}}
        lock.write_text(json.dumps(data))
        claude = self.home / '.claude/skills'
        claude.mkdir(parents=True)
        (claude / 'existing').symlink_to(self.old.parent)
        (claude / 'local-only').mkdir()
        (claude / 'broken').symlink_to(self.root / 'missing')
        system = self.home / '.agents/skills/.system'
        system.mkdir()
        (system / 'keep').write_text('system')
        entries = self.scan_entries(rules=False)
        known = [e for e in entries if e['group'] == 'owner/repo']
        self.assertEqual({(e['agent'], e['name']) for e in known}, {('codex', 'existing'), ('codex', 'other'), ('claude', 'existing')})
        unknown = {e['name'] for e in entries if e['group'] == 'Unknown / local'}
        self.assertEqual(unknown, {'local-only', 'broken', 'malformed'})
        self.assertNotIn('.system', {e['name'] for e in entries})
        self.assertEqual(json.loads(lock.read_text()), data)
        self.assertFalse(self.calls())

    def test_selective_codex_removal_updates_only_successful_lock_entries(self):
        lock, original = self.lock_fixture()
        claude = self.home / '.claude/skills/existing'
        claude.parent.mkdir(parents=True)
        claude.symlink_to(self.old.parent)
        entries = self.scan_entries(rules=False)
        self.select_entries([e for e in entries if e['agent'] == 'codex' and e['name'] == 'existing'])
        preview = self.inventory('preview')
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn('WARNING: Claude link will be kept', preview.stdout)
        self.assertIn('\x1b[31m', preview.stdout)
        result = self.inventory('remove', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.old.exists())
        self.assertTrue((self.home / '.agents/skills/other/SKILL.md').exists())
        self.assertTrue(claude.is_symlink())
        expected = json.loads(json.dumps(original))
        del expected['skills']['existing']
        self.assertEqual(json.loads(lock.read_text()), expected)
        backup, = self.home.glob('.agent-skills-backup-*/removal.tar')
        self.assertEqual(backup.parent.stat().st_mode & 0o777, 0o700)
        with tarfile.open(backup) as tar:
            self.assertIn('.agents/.skill-lock.json', tar.getnames())
        subprocess.run(['tar', '-xf', str(backup), '-C', str(self.home)], check=True)
        self.assertEqual(self.old.read_text(), 'keep me')
        self.assertEqual(json.loads(lock.read_text()), original)
        self.assertIn('\x1b[36mRestore:', result.stdout)

    def test_global_skill_rows_merge_aliases_but_keep_unknown_copies_separate(self):
        self.lock_fixture()
        claude = self.home / '.claude/skills'
        claude.mkdir(parents=True)
        (claude / 'renamed').symlink_to(self.old.parent)
        (claude / 'other').mkdir()  # Unknown provenance is not evidence of identity.
        self.scan_entries(rules=False)
        rows = self.inventory('rows')
        self.assertEqual(rows.returncode, 0, rows.stderr)
        lines = [line.split('\t') for line in rows.stdout.splitlines()]
        self.assertEqual(len(lines), 3)
        merged, = [line for line in lines if line[3].startswith('existing ')]
        self.assertEqual(merged[3], 'existing [Codex:directory] [Claude:link]')
        self.assertEqual(len(merged[0].split(',')), 2)
        self.assertEqual({line[2] for line in lines if line[3].startswith('other ')},
                         {'owner/repo', 'Unknown / local'})

    def test_global_unknown_skill_and_proven_reference_share_one_row(self):
        claude = self.home / '.claude/skills'
        claude.mkdir(parents=True)
        (claude / 'alias').symlink_to(self.old.parent)
        self.scan_entries(rules=False)
        rows = self.inventory('rows')
        self.assertEqual(rows.returncode, 0, rows.stderr)
        self.assertEqual(len(rows.stdout.splitlines()), 1)
        self.assertIn('existing [Codex:directory] [Claude:link]', rows.stdout)

    def test_external_link_inclusion_is_backed_up_and_restorable(self):
        lock, original = self.lock_fixture()
        link = self.home / '.claude/skills/alias'
        link.parent.mkdir(parents=True)
        link.symlink_to(self.old.parent)
        entries = self.scan_entries(claude=False, rules=False)
        self.select_entries([e for e in entries if e['name'] == 'existing'])
        links = self.inventory('linked-skills')
        self.assertEqual(links.returncode, 0, links.stderr)
        self.assertIn(str(link), links.stdout)
        included = self.inventory('include-links')
        self.assertEqual(included.returncode, 0, included.stderr)
        preview = self.inventory('preview')
        self.assertIn('claude / alias [link]', preview.stdout)
        self.assertNotIn('will be kept', preview.stdout)
        removed = self.inventory('remove', '1')
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertFalse(link.is_symlink())
        self.assertFalse(self.old.exists())
        backup, = self.home.glob('.agent-skills-backup-*/removal.tar')
        with tarfile.open(backup) as tar:
            self.assertTrue(tar.getmember('.claude/skills/alias').issym())
        subprocess.run(['tar', '-xf', str(backup), '-C', str(self.home)], check=True)
        self.assertTrue(link.is_symlink())
        self.assertEqual(self.old.read_text(), 'keep me')
        self.assertEqual(json.loads(lock.read_text()), original)

    def test_external_link_change_after_prompt_stops_removal(self):
        self.lock_fixture()
        link = self.home / '.claude/skills/existing'
        link.parent.mkdir(parents=True)
        link.symlink_to(self.old.parent)
        entries = self.scan_entries(claude=False, rules=False)
        self.select_entries([e for e in entries if e['name'] == 'existing'])
        self.assertEqual(self.inventory('linked-skills').returncode, 0)
        link.unlink()
        link.symlink_to(self.home / '.agents/skills/other')
        result = self.inventory('include-links')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Content changed', result.stderr)
        self.assertTrue(self.old.exists())
        self.assertTrue(link.is_symlink())

    def test_shared_claude_directory_link_is_warned_and_kept(self):
        self.lock_fixture()
        link = self.home / '.claude/skills'
        link.parent.mkdir(parents=True)
        link.symlink_to(self.home / '.agents/skills')
        entries = self.scan_entries(claude=False, rules=False)
        self.select_entries([e for e in entries if e['name'] == 'existing'])
        links = self.inventory('linked-skills')
        self.assertEqual(links.returncode, 0, links.stderr)
        self.assertEqual(links.stdout, '')
        preview = self.inventory('preview')
        self.assertIn('Shared Claude skills directory link will be kept', preview.stdout)
        self.assertIn('also affects Claude', preview.stdout)
        result = self.inventory('remove')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(link.is_symlink())
        self.assertTrue((link / 'other/SKILL.md').exists())

    def test_external_link_cleanup_preserves_system_entries(self):
        self.lock_fixture()
        link = self.home / '.claude/skills/.system/reference'
        link.parent.mkdir(parents=True)
        link.symlink_to(self.old.parent)
        entries = self.scan_entries(claude=False, rules=False)
        self.select_entries([e for e in entries if e['name'] == 'existing'])
        links = self.inventory('linked-skills')
        self.assertEqual(links.returncode, 0, links.stderr)
        self.assertEqual(links.stdout, '')
        self.assertIn('Claude link will be kept', self.inventory('preview').stdout)
        result = self.inventory('remove')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(link.is_symlink())

    def test_claude_only_removal_keeps_shared_source_and_lock(self):
        lock, original = self.lock_fixture()
        link = self.home / '.claude/skills/existing'
        link.parent.mkdir(parents=True)
        link.symlink_to(self.old.parent)
        entries = self.scan_entries(codex=False, rules=False)
        self.select_entries(entries)
        result = self.inventory('remove')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(link.is_symlink())
        self.assertTrue(self.old.exists())
        self.assertEqual(json.loads(lock.read_text()), original)

    def test_rule_inventory_selects_whole_files_and_backs_up_personal_bytes(self):
        target = self.home / '.codex/AGENTS.md'
        target.parent.mkdir()
        original = '个人文字\r\nNo managed markers.\r\n'.encode()
        target.write_bytes(original)
        custom = self.home / '.claude/rules/nested/.custom.md'
        custom.parent.mkdir(parents=True)
        custom.write_text('custom content')
        kept = custom.parent / 'keep.md'
        kept.write_text('keep')
        main = self.home / '.claude/CLAUDE.md'
        main.write_text('Claude personal rules.')
        entries = self.scan_entries(skills=False)
        self.assertEqual({e['type'] for e in entries}, {'file'})
        self.select_entries([e for e in entries if e['name'] != 'rules/nested/keep.md'])
        result = self.inventory('remove', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(target.exists())
        self.assertFalse(custom.exists())
        self.assertFalse(main.exists())
        self.assertEqual(kept.read_text(), 'keep')
        backup, = self.home.glob('.agent-rules-backup-*/removal.tar')
        with tarfile.open(backup) as tar:
            self.assertEqual(tar.extractfile('.codex/AGENTS.md').read(), original)
            self.assertIn('.claude/CLAUDE.md', tar.getnames())

    def pi_removal_fixture(self, directory=None):
        directory = directory or self.home / '.pi/agent'
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / 'AGENTS.md'
        personal = '# Global Rules\n\nPersonal rules.\n'
        blocks = {name: (f'<!-- gwyn-space-skills: {name}:start -->\n'
                         f'## {name}\nBody.\n<!-- gwyn-space-skills: {name}:end -->\n')
                  for name in ['one', 'two']}
        target.write_text(personal + blocks['one'] + blocks['two'])
        return target, personal, blocks

    def test_pi_removal_ui_only_pi_preserves_other_agents_and_config(self):
        target, personal, blocks = self.pi_removal_fixture()
        settings = target.parent / 'settings.json'
        settings.write_text('{"keep": true}')
        codex = self.home / '.codex/AGENTS.md'
        codex.parent.mkdir()
        codex.write_text('Codex user rules.\n')
        claude = self.home / '.claude/rules/keep.md'
        claude.parent.mkdir(parents=True)
        claude.write_text('Claude user rules.\n')
        term = self.removal_terminal(types=('Rules',), agents='pi')
        term.expect('AGENTS.md [Pi:file]')
        term.expect('Item 1/1')
        frame = term.transcript.decode().rsplit('\x1b[H\x1b[2J', 1)[-1]
        self.assertNotIn('Codex /', frame)
        self.assertNotIn('Claude /', frame)
        term.send(b' \r')
        term.expect(str(target))
        term.expect('Create backup? [y/N]')
        term.send(b'\n')
        term.expect('Confirm removal? [Y/n]')
        self.assertIn('## one', target.read_text())
        term.send(b'y\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertFalse(target.exists())
        self.assertEqual(settings.read_text(), '{"keep": true}')
        self.assertEqual(codex.read_text(), 'Codex user rules.\n')
        self.assertEqual(claude.read_text(), 'Claude user rules.\n')
        self.assertFalse(list(self.home.glob('.agent-rules-backup-*')))

    def test_global_removal_explicit_all_includes_pi_and_mixed_agents(self):
        target, personal, blocks = self.pi_removal_fixture()
        codex = self.home / '.codex/AGENTS.md'
        codex.parent.mkdir()
        codex.write_text('Codex notes.\n' + blocks['one'])
        term = self.removal_terminal(types=('Rules',))
        self.assertIn('[ ] Pi (rules only)', term.transcript.decode())
        term.expect('AGENTS.md [Codex:file]')
        term.expect('AGENTS.md [Pi:file]')
        term.expect('Item 1/2')
        term.send(b'a\r')
        term.expect('Create backup? [y/N]')
        term.send(b'\n')
        term.expect('Confirm removal? [Y/n]')
        term.send(b'y\n')
        term.expect('2 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertFalse(target.exists())
        self.assertFalse(codex.exists())

    def test_global_removal_default_preserves_claude_and_pi_rules(self):
        codex, claude, pi, _, _ = self.grouped_rule_fixture()
        before = pi.read_bytes()
        claude_before = claude.read_bytes()
        term = self.removal_terminal(types=('Rules',), agents='default')
        term.expect('AGENTS.md [Codex:file]')
        term.expect('Item 1/1')
        term.send(b'a\r')
        term.expect('Create backup? [y/N]')
        term.send(b'\n')
        term.expect('Confirm removal? [Y/n]')
        term.send(b'y\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertEqual(pi.read_bytes(), before)
        self.assertFalse(codex.exists())
        self.assertEqual(claude.read_bytes(), claude_before)

    def grouped_rule_fixture(self):
        pi, personal, blocks = self.pi_removal_fixture()
        codex = self.home / '.codex/AGENTS.md'
        codex.parent.mkdir()
        codex.write_text('Codex notes.\n' + blocks['one'])
        claude = self.home / '.claude/rules/one.md'
        claude.parent.mkdir(parents=True)
        claude.write_text('# one\nBody.\n')
        return codex, claude, pi, personal, blocks

    def test_rule_inventory_lists_plain_installed_files_in_both_scopes(self):
        for scope in ('global', 'project'):
            with self.subTest(scope=scope):
                result = self.source(f'apply_rule waza-anti-patterns {scope} both install waza', cwd=self.root)
                self.assertEqual(result.returncode, 0, result.stderr)
                if scope == 'global':
                    self.assertEqual(self.source('apply_rule waza-anti-patterns global pi install waza').returncode, 0)
                result = self.inventory('scan', 1, 1, 1, 0, int(scope == 'global'), scope=scope, cwd=self.root)
                self.assertEqual(result.returncode, 0, result.stderr)
                rows = self.inventory('rows', scope=scope, cwd=self.root).stdout.splitlines()
                self.assertEqual(len(rows), 3 if scope == 'global' else 1)
                if scope == 'global':
                    self.assertTrue(any('AGENTS.md [Codex:file]' in row for row in rows))
                    self.assertTrue(any('rules/waza-anti-patterns.md [Claude:file]' in row for row in rows))
                else:
                    self.assertIn('waza-anti-patterns.md [Project:file]', rows[0])

    def test_rule_file_ui_selects_only_one_agent_file(self):
        codex, claude, pi, _, _ = self.grouped_rule_fixture()
        before = {target: target.read_bytes() for target in (claude, pi)}
        term = self.removal_terminal(types=('Rules',))
        term.expect('AGENTS.md [Codex:file]')
        term.expect('rules/one.md [Claude:file]')
        term.expect('AGENTS.md [Pi:file]')
        term.expect('Item 1/3')
        term.send(b' \r')
        term.expect('Removal targets:')
        term.expect(str(codex))
        term.expect('Create backup? [y/N]')
        term.send(b'\n')
        term.expect('Confirm removal? [Y/n]')
        term.send(b'y\n')
        term.expect('Rules: 1 removed, 0 partial, 0 failed')
        term.expect('1 succeeded, 0 failed (installation targets)')
        self.assertEqual(term.finish_action(), 0)
        self.assertFalse(codex.exists())
        for target, content in before.items():
            self.assertEqual(target.read_bytes(), content)

    def test_rule_file_back_and_explicit_cancel_preserve_all_files(self):
        codex, claude, pi, _, _ = self.grouped_rule_fixture()
        before = {target: target.read_bytes() for target in (codex, claude, pi)}
        term = self.removal_terminal(types=('Rules',))
        label = 'AGENTS.md [Codex:file]'
        term.expect('Item 1/3')
        term.send(b' \r')
        term.expect('Create backup? [y/N]')
        term.send(b'b\n')
        term.expect('[x] ' + label)
        term.expect('Item 1/3')
        term.send(b'\r')
        term.expect('Create backup? [y/N]')
        term.send(b'y\n')
        term.expect('Confirm removal? [Y/n]')
        term.send(b'n\n')
        term.expect('Cancelled.')
        self.assertEqual(term.finish_action(), 0)
        for target, content in before.items():
            self.assertEqual(target.read_bytes(), content)
        self.assertFalse(list(self.home.glob('.agent-*-backup-*')))

    def test_rule_file_rows_respect_agent_filter_and_keep_links_separate(self):
        codex, claude, pi, _, _ = self.grouped_rule_fixture()
        nested = claude.parent / 'nested/one.md'
        nested.parent.mkdir()
        nested.write_text(claude.read_text())
        linked = claude.parent / 'linked.md'
        linked.symlink_to(claude)
        entries = self.scan_entries(codex=False, skills=False, pi=True)
        rows = self.inventory('rows')
        self.assertNotIn('Codex', rows.stdout)
        for label in ('AGENTS.md [Pi:file]', 'rules/one.md [Claude:file]',
                      'rules/nested/one.md [Claude:file]', 'rules/linked.md [Claude:link]'):
            self.assertIn(label, rows.stdout)
        self.select_entries([e for e in entries if e['agent'] == 'pi' or e['name'] == 'rules/one.md'])
        result = self.inventory('remove')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(codex.exists())
        self.assertFalse(claude.exists())
        self.assertFalse(pi.exists())
        self.assertTrue(nested.exists())
        self.assertTrue(linked.is_symlink())

    def test_rule_files_are_independent_of_headings_and_managed_markers(self):
        _, claude, _, _, _ = self.grouped_rule_fixture()
        claude.write_text('# Personal rule\nKeep me.\n')
        entries = self.scan_entries(skills=False, pi=True)
        self.assertEqual(len(entries), 3)
        self.assertTrue(all(e['type'] == 'file' for e in entries))
        self.assertTrue(all('ruleName' not in e for e in entries))

    def test_rule_file_backup_contains_all_selected_agents_and_restores(self):
        codex, claude, pi, _, _ = self.grouped_rule_fixture()
        before = {target: target.read_bytes() for target in (codex, claude, pi)}
        entries = self.scan_entries(skills=False, pi=True)
        self.select_entries(entries)
        result = self.inventory('remove', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        backup, = self.home.glob('.agent-rules-backup-*/removal.tar')
        with tarfile.open(backup) as tar:
            self.assertEqual(set(tar.getnames()), {str(target.relative_to(self.home)) for target in before})
        subprocess.run(['tar', '-xf', str(backup), '-C', str(self.home)], check=True)
        for target, content in before.items():
            self.assertEqual(target.read_bytes(), content)

    def test_rule_file_change_aborts_before_any_deletion(self):
        codex, claude, pi, _, _ = self.grouped_rule_fixture()
        entries = self.scan_entries(skills=False, pi=True)
        self.select_entries(entries)
        claude.write_text('# one\nUser edit during confirmation.\n')
        before = {target: target.read_bytes() for target in (codex, claude, pi)}
        result = self.inventory('remove')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Content changed; rescan', result.stderr)
        for target, content in before.items():
            self.assertEqual(target.read_bytes(), content)

    def test_rule_file_failure_reports_each_target_and_continues(self):
        codex, claude, pi, personal, blocks = self.grouped_rule_fixture()
        entries = self.scan_entries(skills=False, pi=True)
        self.select_entries(entries)
        preload = self.root / 'fail-rule.cjs'
        preload.write_text('const fs=require("fs");const original=fs.rmSync;fs.rmSync=function(p,...args){if(p==='
                           + json.dumps(str(claude)) + ') throw Error("fixture rule removal failed");return original.call(this,p,...args);};')
        self.env['NODE_OPTIONS'] = f'--require={preload}'
        result = self.inventory('remove')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('FAIL rules/one.md [Claude:file]', result.stdout)
        self.assertIn('Rules: 2 removed, 0 partial, 1 failed', result.stdout)
        self.assertIn('2 succeeded, 1 failed (installation targets)', result.stdout)
        self.assertIn('OK [Codex:file] ' + str(codex), result.stdout)
        self.assertIn('OK [Pi:file] ' + str(pi), result.stdout)
        self.assertIn('FAIL [Claude:file] ' + str(claude), result.stderr)
        self.assertIn('fixture rule removal failed', result.stderr)
        self.assertFalse(codex.exists())
        self.assertTrue(claude.exists())
        self.assertFalse(pi.exists())

    def test_pi_removal_scope_switch_keeps_project_two_agent_menu(self):
        term = self.removal_terminal(types=('Rules',), agents='pi')
        # No installed Pi rules: return through the completed action and inspect
        # project scope in a fresh removal, preserving the normal project flow.
        term.expect('No removal targets selected.')
        term.return_home()
        term.send(b'\x1b[B\r')
        term.expect('Remove: choose content')
        term.expect('Item 1/2')
        term.send(b' \r')
        term.expect('Remove: choose scope')
        term.expect('Item 1/2')
        term.send(b'\r')
        term.expect('Remove: choose agents')
        term.expect('Item 1/3')
        term.send(b'\x1b[B\x1b[Bb')
        term.expect('Remove: choose scope')
        term.expect('Item 1/2')
        term.send(b'\x1b[B\r')
        term.expect('Remove: choose agents')
        term.expect('Item 2/2')
        frame = term.transcript.decode().rsplit('\x1b[H\x1b[2J', 1)[-1]
        self.assertNotIn('Pi', frame)
        term.send(b'q')
        self.assertEqual(term.finish(), 0)

    def test_pi_removal_whole_file_backup_includes_user_content(self):
        target, personal, blocks = self.pi_removal_fixture()
        before = target.read_bytes()
        entries = self.scan_entries(codex=False, claude=False, skills=False, pi=True)
        self.assertEqual([(e['agent'], e['name']) for e in entries], [('pi', 'AGENTS.md')])
        rows = self.inventory('rows')
        self.assertIn('AGENTS.md [Pi:file]', rows.stdout)
        self.select_entries([entries[0]])
        preview = self.inventory('preview')
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn(str(target), preview.stdout)
        result = self.inventory('remove', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(target.exists())
        backup, = self.home.glob('.agent-rules-backup-*/removal.tar')
        with tarfile.open(backup) as archive:
            self.assertEqual(archive.extractfile('.pi/agent/AGENTS.md').read(), before)
        self.assertTrue(self.old.exists())

    def test_pi_removal_custom_directory_and_path_change_require_rescan(self):
        target, _, _ = self.pi_removal_fixture(self.home / 'custom pi')
        self.env['PI_CODING_AGENT_DIR'] = '~/custom pi'
        entries = self.scan_entries(codex=False, claude=False, skills=False, pi=True)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['relative'], 'custom pi/AGENTS.md')
        self.select_entries(entries)
        before = target.read_bytes()
        self.env['PI_CODING_AGENT_DIR'] = str(self.home / 'other pi')
        result = self.inventory('remove')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Pi rule path changed', result.stderr)
        self.assertEqual(target.read_bytes(), before)

    def test_pi_removal_rejects_external_directory_and_symlinked_parents(self):
        external, _, _ = self.pi_removal_fixture(self.root / 'external pi')
        before = external.read_bytes()
        self.env['PI_CODING_AGENT_DIR'] = str(external.parent)
        result = self.inventory('scan', 0, 0, 1, 0, 1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Path outside removal root', result.stderr)
        self.assertEqual(external.read_bytes(), before)
        link = self.home / 'linked pi'
        link.symlink_to(external.parent, target_is_directory=True)
        self.env['PI_CODING_AGENT_DIR'] = str(link)
        result = self.inventory('scan', 0, 0, 1, 0, 1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsafe parent directory', result.stderr)
        self.assertEqual(external.read_bytes(), before)

    def test_pi_removal_file_symlink_only_removes_link(self):
        target, _, _ = self.pi_removal_fixture(self.root / 'external pi')
        before = target.read_bytes()
        link = self.home / '.pi/agent/AGENTS.md'
        link.parent.mkdir(parents=True)
        link.symlink_to(target)
        entries = self.scan_entries(codex=False, claude=False, skills=False, pi=True)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['type'], 'link')
        self.select_entries(entries)
        result = self.inventory('remove')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(link.is_symlink())
        self.assertEqual(target.read_bytes(), before)

    def test_pi_removal_accepts_broken_markers_but_rejects_changes_and_backup_failure(self):
        target, _, _ = self.pi_removal_fixture()
        before = target.read_bytes()
        target.write_text('<!-- gwyn-space-skills: broken:start -->\n')
        result = self.inventory('scan', 0, 0, 1, 0, 1)
        self.assertEqual(result.returncode, 0, result.stderr)
        target.write_bytes(before)
        entries = self.scan_entries(codex=False, claude=False, skills=False, pi=True)
        self.select_entries(entries)
        target.write_bytes(before + b'User edit.\n')
        result = self.inventory('remove')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Content changed', result.stderr)
        self.assertEqual(target.read_bytes(), before + b'User edit.\n')
        target.write_bytes(before)
        entries = self.scan_entries(codex=False, claude=False, skills=False, pi=True)
        self.select_entries(entries)
        self.stub('tar', '#!/bin/sh\nexit 23\n')
        result = self.inventory('remove', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Backup failed; nothing removed', result.stderr)
        self.assertEqual(target.read_bytes(), before)

    def test_pi_removal_skills_only_does_not_scan_other_agent_skills(self):
        self.pi_removal_fixture()
        # An unrelated unsafe source must not affect a Pi-only skills request.
        shutil.rmtree(self.home / '.agents')
        (self.home / '.agents').symlink_to(self.root / 'missing')
        entries = self.scan_entries(codex=False, claude=False, rules=False, skills=True, pi=True)
        self.assertEqual(entries, [])

    def test_multiple_legacy_blocks_are_one_file_removal(self):
        target = self.home / '.codex/AGENTS.md'
        target.parent.mkdir()
        target.write_text('personal\n' + ''.join(f'<!-- gwyn-space-skills: {n}:start -->\n{n}\n<!-- gwyn-space-skills: {n}:end -->\n' for n in ['one', 'two']))
        entries = self.scan_entries(skills=False)
        self.select_entries(entries)
        result = self.inventory('remove')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('1 succeeded, 0 failed', result.stdout)
        self.assertFalse(target.exists())

    def test_rules_and_skills_backup_failure_prevents_entire_batch(self):
        target = self.home / '.claude/rules/custom.md'
        target.parent.mkdir(parents=True)
        target.write_text('custom')
        entries = self.scan_entries()
        self.select_entries(entries)
        self.stub('tar', '#!/bin/sh\nexit 23\n')
        result = self.inventory('remove', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Backup failed; nothing removed', result.stderr)
        self.assertTrue(self.old.exists())
        self.assertEqual(target.read_text(), 'custom')

    def test_changed_targets_and_lock_stop_before_any_deletion(self):
        lock, original = self.lock_fixture()
        entries = self.scan_entries(rules=False)
        self.select_entries(entries)
        self.old.write_text('changed after scan')
        result = self.inventory('remove')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Content changed; rescan', result.stderr)
        self.assertTrue((self.home / '.agents/skills/other').exists())
        self.assertFalse(list(self.home.glob('.agent-skills-backup-*')))
        entries = self.scan_entries(rules=False)
        self.select_entries(entries)
        lock.write_text(json.dumps({**original, 'version': 9}))
        result = self.inventory('remove')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Skill lock changed', result.stderr)
        self.assertTrue(self.old.exists())

    def test_changes_during_backup_stop_deletion(self):
        entries = self.scan_entries(rules=False)
        self.select_entries(entries)
        real_tar = shutil.which('tar')
        self.stub('tar', f'#!/bin/sh\nprintf changed > {shlex.quote(str(self.old))}\nexec {shlex.quote(real_tar)} "$@"\n')
        result = self.inventory('remove', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Content changed; rescan', result.stderr)
        self.assertEqual(self.old.read_text(), 'changed')

    def test_symlinks_are_entries_and_never_followed(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'keep').write_text('outside')
        rules = self.home / '.claude/rules'
        rules.parent.mkdir()
        rules.symlink_to(outside)
        skills = self.home / '.claude/skills'
        skills.symlink_to(outside)
        entries = self.scan_entries(codex=False)
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(e['type'] == 'link' for e in entries))
        self.select_entries(entries)
        result = self.inventory('remove', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(rules.is_symlink())
        self.assertFalse(skills.is_symlink())
        self.assertEqual((outside / 'keep').read_text(), 'outside')
        backup, = self.home.glob('.agent-rules-backup-*/removal.tar')
        subprocess.run(['tar', '-xf', str(backup), '-C', str(self.home)], check=True)
        self.assertTrue(rules.is_symlink() and skills.is_symlink())

    def test_scan_rejects_symlinked_parents_but_accepts_unbalanced_legacy_markers(self):
        directory = self.home / '.claude'
        directory.symlink_to(self.root)
        result = self.inventory('scan', 1, 1, 1, 1)
        self.assertNotEqual(result.returncode, 0)
        directory.unlink()
        target = self.home / '.codex/AGENTS.md'
        target.parent.mkdir()
        target.write_text('<!-- gwyn-space-skills: broken:start -->\nkeep\n')
        result = self.inventory('scan', 1, 1, 1, 1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.old.exists())

    def test_invalid_lock_refuses_codex_but_allows_claude_link_removal(self):
        lock = self.home / '.agents/.skill-lock.json'
        lock.write_text('{broken')
        link = self.home / '.claude/skills/existing'
        link.parent.mkdir(parents=True)
        link.symlink_to(self.old.parent)
        entries = self.scan_entries(rules=False)
        self.select_entries([e for e in entries if e['agent'] == 'codex'])
        result = self.inventory('remove')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.old.exists())
        self.select_entries([e for e in entries if e['agent'] == 'claude'])
        result = self.inventory('remove')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(lock.read_text(), '{broken')
        self.assertTrue(self.old.exists())
        self.assertFalse(link.is_symlink())

    def test_individual_failure_continues_and_keeps_failed_lock_record(self):
        lock, original = self.lock_fixture()
        entries = self.scan_entries(rules=False)
        self.select_entries(entries)
        preload = self.root / 'fail-one.cjs'
        preload.write_text('const fs=require("fs");const original=fs.rmSync;fs.rmSync=function(p,...args){if(p===' + json.dumps(str(self.old.parent)) + ') throw Error("fixture remove failed");return original.call(this,p,...args);};')
        self.env['NODE_OPTIONS'] = f'--require={preload}'
        result = self.inventory('remove')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('1 succeeded, 1 failed', result.stdout)
        self.assertTrue(self.old.exists())
        self.assertFalse((self.home / '.agents/skills/other').exists())
        self.assertIn('existing', json.loads(lock.read_text())['skills'])
        self.assertNotIn('other', json.loads(lock.read_text())['skills'])

    def test_merged_removal_ui_agent_filter_and_unified_confirmation(self):
        self.lock_fixture()
        custom = self.home / '.claude/rules/custom.md'
        custom.parent.mkdir(parents=True)
        custom.write_text('keep custom')
        link = self.home / '.claude/skills/existing'
        link.parent.mkdir()
        link.symlink_to(self.old.parent)
        term = self.removal_terminal(types=('Rules', 'Skills'), agents='claude')
        term.expect('Choose installed rules to remove')
        term.expect('Item 1/1')
        self.assertNotIn('Codex /', term.transcript.decode())
        term.send(b' \r')
        term.expect('Remove skills by repository')
        term.expect('Item 1/2')
        term.send(b' \x1b[A\r')
        term.expect('Create backup? [y/N]')
        term.send(b'y\n')
        term.expect('Confirm removal? [Y/n]')
        self.assertEqual(term.transcript.count(b'Confirm removal? [Y/n]'), 1)
        self.assertIn(b'\x1b[31m', term.transcript)
        term.send(b'y\n')
        term.expect('2 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertFalse(custom.exists())
        self.assertFalse(link.is_symlink())
        self.assertTrue(self.old.exists())
        backup, = self.home.glob('.agent-rules-backup-*/removal.tar')
        self.assertEqual(backup.parent.stat().st_mode & 0o777, 0o700)

    def test_removal_picker_c_continues_from_both_levels_without_confirming_removal(self):
        for child in (False, True):
            for selected in (False, True):
                with self.subTest(child=child, selected=selected):
                    term = self.removal_terminal()
                    term.expect('Remove skills by repository')
                    term.expect('c: continue')
                    term.expect('Item 1/2')
                    if child:
                        term.send(b'\r')
                        term.expect('Repository: Unknown / local')
                        term.expect('c: continue')
                        term.expect('Item 1/1')
                    if selected:
                        term.send(b' ')
                    term.send(b'c')
                    if selected:
                        term.expect('Create backup? [y/N]')
                        self.assertTrue(self.old.exists())
                        term.send(b'\r')
                        term.expect('Confirm removal? [Y/n]')
                        self.assertTrue(self.old.exists())
                        term.send(b'n\r')
                        term.expect('Cancelled.')
                    else:
                        term.expect('No removal targets selected.')
                    self.assertEqual(term.finish_action(), 0)
                    self.assertTrue(self.old.exists())

    def test_removal_repository_child_counts_and_removes_one_skill_across_agents(self):
        self.lock_fixture()
        link = self.home / '.claude/skills/existing'
        link.parent.mkdir(parents=True)
        link.symlink_to(self.old.parent)
        term = self.removal_terminal()
        term.expect('Remove skills by repository')
        term.expect('owner/repo (0/2)')
        term.send(b'\r')
        term.expect('existing [Codex:directory] [Claude:link]')
        term.expect('other [Codex:directory]')
        term.send(b' \r')
        term.expect('owner/repo (1/2)')
        term.send(b'b')
        term.expect('Remove: choose agents')
        term.expect('Item 1/3')
        term.send(b'\r')
        term.expect('owner/repo (1/2)')
        term.send(b'c')
        term.expect('Create backup? [y/N]')
        self.assertNotIn(b'Also remove these Claude links?', term.transcript)
        term.send(b'\n')
        term.expect('Confirm removal? [Y/n]')
        term.send(b'y\n')
        term.expect('2 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertFalse(link.is_symlink())
        self.assertFalse(self.old.exists())
        self.assertTrue((self.home / '.agents/skills/other').exists())

    def test_codex_only_ui_confirms_external_links_before_backup(self):
        self.lock_fixture()
        link = self.home / '.claude/skills/existing'
        link.parent.mkdir(parents=True)
        for accept in [False, True]:
            with self.subTest(accept=accept):
                before = set(self.home.glob('.agent-skills-backup-*/removal.tar'))
                if link.is_symlink(): link.unlink()
                link.symlink_to(self.old.parent)
                term = self.removal_terminal(agents='codex')
                term.expect('owner/repo (0/2)')
                term.send(b'\r')
                term.expect('existing [Codex:directory]')
                term.send(b' \r\x1b[A\r')
                term.expect('Also remove these Claude links? [y/N]')
                self.assertNotIn(b'Create backup?', term.transcript)
                self.assertTrue(self.old.exists())
                term.send(b'y\n' if accept else b'\n')
                if not accept: term.expect('WARNING: Claude link will be kept')
                term.expect('Create backup? [y/N]')
                term.send(b'y\n')
                term.expect('Confirm removal? [Y/n]')
                term.send(b'y\n')
                term.expect(f'{2 if accept else 1} succeeded, 0 failed')
                self.assertEqual(term.finish_action(), 0)
                self.assertEqual(link.is_symlink(), not accept)
                self.assertFalse(self.old.exists())
                # Restore the source and lock before the next subcase.
                backup, = set(self.home.glob('.agent-skills-backup-*/removal.tar')) - before
                subprocess.run(['tar', '-xf', str(backup), '-C', str(self.home)], check=True)

    def test_codex_external_link_prompt_back_and_exit_preserve_files(self):
        self.lock_fixture()
        link = self.home / '.claude/skills/existing'
        link.parent.mkdir(parents=True)
        link.symlink_to(self.old.parent)
        term = self.removal_terminal(agents='codex')
        term.expect('owner/repo (0/2)')
        term.send(b' \x1b[A\r')
        term.expect('Also remove these Claude links? [y/N]')
        term.send(b'b\n')
        term.expect('Remove skills by repository')
        term.expect('owner/repo (2/2)')
        term.send(b'\r')
        term.expect('Also remove these Claude links? [y/N]')
        term.send(b'q\n')
        self.assertEqual(term.finish(), 0)
        self.assertTrue(self.old.exists())
        self.assertTrue(link.is_symlink())

    def test_removal_menu_defaults_back_cancel_q_and_fresh_scan(self):
        term = self.terminal()
        term.send(b'\x1b[B\r')
        term.expect('Remove: choose content')
        term.expect('Item 1/2')
        frame = re.sub(r'\x1b\[[0-9;]*m', '', term.transcript.decode()).rsplit('\x1b[H\x1b[2J', 1)[-1]
        self.assertIn('[ ] Rules', frame)
        self.assertIn('[ ] Skills', frame)
        term.send(b' \r')
        term.expect('Remove: choose scope')
        term.expect('Item 1/2')
        term.send(b'\r')
        term.expect('Remove: choose agents')
        term.expect('Item 1/3')
        term.send(b'n\x1b[B b')  # Claude only; return to scope
        term.expect('Remove: choose scope')
        term.expect('Item 1/2')
        term.send(b'b')
        term.expect('Remove: choose content')
        term.expect('[x] Rules')
        term.expect('Item 1/2')
        term.send(b'b')
        term.expect('Item 2/6')
        term.send(b'\r')
        term.expect('Remove: choose content')
        term.expect('Item 1/2')
        term.send(b'\r')
        term.expect('Remove: choose scope')
        term.expect('Item 1/2')
        term.send(b'\r')
        term.expect('> [x] Claude Code')
        term.send(b'b')
        term.expect('Remove: choose scope')
        term.expect('Item 1/2')
        term.send(b'b')
        term.expect('Remove: choose content')
        term.expect('Item 1/2')
        term.send(b'n\r')
        term.expect('No content selected')
        term.return_home()
        # Add content after the first action. A new removal must see it.
        custom = self.home / '.claude/rules/new.md'
        custom.parent.mkdir(parents=True)
        custom.write_text('new rule')
        term.send(b'\x1b[B\r')
        term.expect('Remove: choose content')
        term.expect('Item 1/2')
        term.send(b' \r')
        term.expect('Remove: choose scope')
        term.expect('Item 1/2')
        term.send(b'\r')
        term.expect('Remove: choose agents')
        term.expect('Item 1/3')
        term.send(b'n\x1b[B \r')
        term.expect('new.md [Claude:file]')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertTrue(custom.exists())

    def test_removal_ui_changed_content_stops_and_session_continues(self):
        term = self.removal_terminal()
        term.expect('Remove skills by repository')
        term.expect('Item 1/2')
        term.send(b' \x1b[A\r')
        term.expect('Create backup? [y/N]')
        term.send(b'\n')
        term.expect('Confirm removal? [Y/n]')
        self.old.write_text('edited during confirmation')
        term.send(b'y\n')
        term.expect('Content changed; rescan')
        term.return_home()
        self.assertEqual(term.exit_home(), 1)
        self.assertEqual(self.old.read_text(), 'edited during confirmation')

    def test_removal_no_selection_and_backup_failure_return_home(self):
        term = self.removal_terminal()
        term.expect('Remove skills by repository')
        term.expect('Item 1/2')
        term.send(b'\x1b[A\r')
        term.expect('No removal targets selected.')
        self.assertEqual(term.finish_action(), 0)
        self.assertTrue(self.old.exists())
        self.stub('tar', '#!/bin/sh\nexit 23\n')
        term = self.removal_terminal()
        term.expect('Remove skills by repository')
        term.expect('Item 1/2')
        term.send(b' \x1b[A\r')
        term.expect('Create backup? [y/N]')
        term.send(b'y\n')
        term.expect('Confirm removal? [Y/n]')
        term.send(b'y\n')
        term.expect('Backup failed; nothing removed')
        self.assertEqual(term.finish_action(), 1)
        self.assertTrue(self.old.exists())

    def test_changed_parent_rejected_without_touching_external_target(self):
        custom = self.home / '.claude/rules/nested/custom.md'
        custom.parent.mkdir(parents=True)
        custom.write_text('original')
        entries = self.scan_entries()
        self.select_entries(entries)
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'custom.md').write_text('outside')
        shutil.rmtree(custom.parent)
        custom.parent.symlink_to(outside)
        result = self.inventory('remove')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsafe parent directory', result.stderr)
        self.assertEqual((outside / 'custom.md').read_text(), 'outside')
        self.assertTrue(self.old.exists())

    def test_installed_rules_default_empty_and_main_file_link_is_not_followed(self):
        custom = self.home / '.claude/rules/custom.md'
        custom.parent.mkdir(parents=True)
        custom.write_text('custom')
        term = self.removal_terminal(types=('Rules',))
        term.expect('Choose installed rules to remove')
        term.expect('Item 1/1')
        self.assertIn('[ ] rules/custom.md [Claude:file]', term.transcript.decode())
        term.send(b'\r')
        term.expect('No removal targets selected.')
        self.assertEqual(term.finish_action(), 0)
        self.assertTrue(custom.exists())
        outside = self.root / 'external-AGENTS.md'
        outside.write_text('outside personal text')
        linked = self.home / '.codex/AGENTS.md'
        linked.parent.mkdir()
        linked.symlink_to(outside)
        entries = self.scan_entries(codex=True, claude=False, skills=False)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['type'], 'link')
        self.select_entries(entries)
        result = self.inventory('remove')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(linked.is_symlink())
        self.assertEqual(outside.read_text(), 'outside personal text')

    def test_install_targets_and_removal_recovery_use_distinct_colors(self):
        result = self.source('install_codex\ninstall_claude\ninstall_statusline\ninstall_setup_command')
        self.assertEqual(result.returncode, 0, result.stderr)
        for label in ['Codex CLI:', 'Claude Code CLI:', 'Statusline target:', 'Installed:']:
            self.assertIn('\x1b[32m' + label, result.stdout)
        self.assertIn(str(self.home / '.claude/settings.json'), result.stdout)
        entries = self.scan_entries(rules=False)
        self.select_entries(entries)
        preview = self.inventory('preview')
        self.assertIn('\x1b[31m' + str(self.old.parent) + '\x1b[0m', preview.stdout)
        result = self.inventory('remove', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('\x1b[36mBackup:', result.stdout)
        plain = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout)
        command = next(line.removeprefix('Restore: ') for line in plain.splitlines() if line.startswith('Restore: '))
        subprocess.run(['bash', '-c', command], check=True)
        self.assertEqual(self.old.read_text(), 'keep me')

    def test_escape_returns_through_skill_and_menu_pages_preserving_selection(self):
        term = self.removal_terminal()
        term.expect('Remove skills by repository')
        term.expect('Item 1/2')
        term.send(b'\r')
        term.expect('existing [Codex:directory]')
        term.send(b' ')
        term.expect('[x] existing [Codex:directory]')
        term.send(b'\x1b')
        term.expect('Remove skills by repository')
        term.expect('Unknown / local (1/1)')
        term.send(b'\x1b')
        term.expect('Remove: choose agents')
        term.expect('Item 1/3')
        term.send(b'\x1b')
        term.expect('Remove: choose scope')
        term.expect('Item 1/2')
        term.send(b'\x1b')
        term.expect('Remove: choose content')
        term.expect('[x] Skills')
        term.send(b'\x1b')
        term.expect('Agent setup')
        term.expect('Item 2/6')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertTrue(self.old.exists())

    def test_escape_back_responds_within_half_a_second(self):
        term = self.terminal()
        term.send(b'\x1b[B\r')
        term.expect('Remove: choose content')
        term.expect('Item 1/2')
        start = time.monotonic()
        term.send(b'\x1b')
        term.expect('Agent setup')
        term.expect('Item 2/6')
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.5, f'Esc Back took {elapsed:.3f}s')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)

    def test_segmented_arrow_sequences_move_without_triggering_back(self):
        term = self.removal_terminal()
        term.expect('Remove skills by repository')
        term.expect('Item 1/2')
        for suffix, position in [(b'[B', 'Item 2/2'), (b'OA', 'Item 1/2')]:
            term.send(b'\x1b')
            time.sleep(0.01)
            term.send(suffix[:1])
            time.sleep(0.01)
            term.send(suffix[1:])
            term.expect(position)
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertTrue(self.old.exists())

    def test_escape_on_main_is_ignored_and_arrow_sequences_still_move(self):
        term = self.terminal()
        term.send(b'\x1b')
        term.expect('Agent setup')
        term.expect('Item 1/6')
        term.send(b'\x1bOB')
        term.expect('Item 2/6')
        term.send(b'\x1b[A')
        term.expect('Item 1/6')
        self.assertEqual(term.exit_home(), 0)

    def test_escape_in_removal_prompts_discards_pending_yes_without_deleting(self):
        term = self.removal_terminal()
        term.expect('Remove skills by repository')
        term.expect('Item 1/2')
        term.send(b' \x1b[A\r')
        term.expect('Create backup? [y/N]')
        term.send(b'y\x1b')
        term.expect('Remove skills by repository')
        term.expect('Unknown / local (1/1)')
        term.send(b'\r')
        term.expect('Create backup? [y/N]')
        term.send(b'y\n')
        term.expect('Confirm removal? [Y/n]')
        term.send(b'y\x1b')
        term.expect('Create backup? [y/N]')
        self.assertTrue(self.old.exists())
        self.assertFalse(list(self.home.glob('.agent-*-backup-*')))
        # A full arrow sequence at a prompt must not be mistaken for Back.
        term.send(b'\x1b[Bn\n')
        term.expect('Confirm removal? [Y/n]')
        term.send(b'q\n')
        self.assertEqual(term.finish(), 0)

    def test_escape_at_command_confirmation_returns_home_without_installing(self):
        term = self.terminal()
        term.send(b'\x1b[B' * 3 + b'\r')
        term.expect('Continue? [Y/n]')
        term.send(b'\x1b')
        term.expect('Agent setup')
        term.expect('Item 4/6')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertFalse((self.home / '.local/bin/agent-setup').exists())

    def test_escape_on_completion_returns_home(self):
        term = self.terminal()
        term.send(b'\x1b[B' * 3 + b'\r')
        term.expect('Continue? [Y/n]')
        term.send(b'n\n')
        term.expect('Press Enter to return to the main menu')
        term.send(b'\x1b')
        term.expect('Agent setup')
        term.expect('Item 1/6')
        self.assertEqual(term.exit_home(), 0)

    def test_escape_at_install_confirmation_returns_to_agent_choices(self):
        term = self.terminal()
        term.send(b'\r')
        term.expect('Item 1/3')
        term.send(b'\x1b[B' * 2 + b' \r')
        term.expect('Choose Agents')
        term.expect('Item 1/3')
        term.send(b'n \r')
        term.expect('Continue? [Y/n]')
        term.send(b'\x1b')
        term.expect('Choose Agents')
        term.expect('[x] Codex')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertFalse(self.calls())
        self.assertFalse((self.home / '.codex').exists())

    def test_escape_at_external_link_prompt_returns_without_removing_links(self):
        self.lock_fixture()
        link = self.home / '.claude/skills/existing'
        link.parent.mkdir(parents=True)
        link.symlink_to(self.old.parent)
        term = self.removal_terminal(agents='codex')
        term.expect('owner/repo (0/2)')
        term.send(b' \x1b[A\r')
        term.expect('Also remove these Claude links? [y/N]')
        term.send(b'\x1b')
        term.expect('Remove skills by repository')
        term.expect('owner/repo (2/2)')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertTrue(link.is_symlink())
        self.assertTrue(self.old.exists())
        self.assertFalse(list(self.home.glob('.agent-*-backup-*')))

    def test_confirmation_backspace_keeps_enter_submission(self):
        term = self.terminal()
        term.send(b'\x1b[B' * 3 + b'\r')
        term.expect('Continue? [Y/n]')
        term.send(b'y\x7fn\n')
        term.expect('Cancelled.')
        self.assertEqual(term.finish_action(), 0)
        self.assertFalse((self.home / '.local/bin/agent-setup').exists())

    def test_removal_confirmation_back_preserves_selection_and_q_exits(self):
        term = self.removal_terminal()
        term.expect('Remove skills by repository')
        term.expect('Item 1/2')
        term.send(b' \x1b[A\r')
        term.expect('Create backup? [y/N]')
        term.send(b'y\n')
        term.expect('All selected content will be backed up')
        term.expect('Confirm removal? [Y/n]')
        self.assertFalse(list(self.home.glob('.agent-*-backup-*')))
        term.send(b'b\n')
        term.expect('Create backup? [y/N]')
        term.send(b'\n')  # returning resets the previous yes to no
        term.expect('No backup will be created.')
        term.expect('Confirm removal? [Y/n]')
        term.send(b'b\n')
        term.expect('Create backup? [y/N]')
        term.send(b'b\n')
        term.expect('Remove skills by repository')
        term.expect('[x] Unknown / local')
        term.expect('Item 2/2')
        term.send(b'\r')
        term.expect('Create backup? [y/N]')
        term.send(b'nope\n')
        term.expect('Please enter y or n')
        term.expect('Create backup? [y/N]')
        term.send(b'N\n')
        term.expect('No backup will be created.')
        term.expect('Confirm removal? [Y/n]')
        term.send(b'q\n')
        self.assertEqual(term.finish(), 0)
        self.assertTrue(self.old.exists())
        self.assertFalse(list(self.home.glob('.agent-*-backup-*')))

    def test_removal_backup_prompt_q_and_confirmation_cancel_create_nothing(self):
        for choice in [b'q\n', b'n\n', b'N\n', b'DELETE\n', b'yes\n']:
            with self.subTest(choice=choice):
                term = self.removal_terminal()
                term.expect('Remove skills by repository')
                term.expect('Item 1/2')
                term.send(b' \x1b[A\r')
                term.expect('Create backup? [y/N]')
                if choice == b'q\n':
                    term.send(choice)
                    self.assertEqual(term.finish(), 0)
                else:
                    term.send(b'y\n')
                    term.expect('Confirm removal? [Y/n]')
                    term.send(choice)
                    term.expect('Cancelled.')
                    self.assertEqual(term.finish_action(), 0)
                self.assertTrue(self.old.exists())
                self.assertFalse(list(self.home.glob('.agent-*-backup-*')))

    def test_removal_backup_choices_only_archive_after_confirmation(self):
        for choice in [b'\n', b'n\n', b'N\n', b'y\n', b'Y\n']:
            with self.subTest(choice=choice):
                self.old.parent.mkdir(parents=True, exist_ok=True)
                self.old.write_text('keep me')
                term = self.removal_terminal()
                term.expect('Remove skills by repository')
                term.expect('Item 1/2')
                term.send(b' \x1b[A\r')
                term.expect('Create backup? [y/N]')
                term.send(choice)
                creates_backup = choice in [b'y\n', b'Y\n']
                term.expect('All selected content will be backed up' if creates_backup else 'No backup will be created.')
                term.expect('Confirm removal? [Y/n]')
                self.assertTrue(self.old.exists())
                self.assertFalse(list(self.home.glob('.agent-*-backup-*')))
                term.send(b'\n')
                term.expect('1 succeeded, 0 failed')
                self.assertEqual(term.finish_action(), 0)
                self.assertFalse(self.old.exists())
                backups = list(self.home.glob('.agent-skills-backup-*'))
                self.assertEqual(len(backups), int(creates_backup))
                if creates_backup:
                    self.assertTrue((backups[0] / 'removal.tar').is_file())
                    shutil.rmtree(backups[0])
                else:
                    self.assertNotIn(b'Restore:', term.transcript)

    def test_no_backup_removal_skips_tar_for_rules_skills_and_lock(self):
        self.stub('tar', '#!/bin/sh\nexit 23\n')
        for scope in ['global', 'project']:
            with self.subTest(scope=scope):
                if scope == 'project':
                    root, _ = self.project_removal_fixture()
                    lock = root / 'skills-lock.json'
                    entries = self.project_entries(root)
                    rule = root / 'docs/rules/.custom.md'
                    main_rule = root / 'docs/rules/one.md'
                else:
                    root = self.home
                    lock, _ = self.lock_fixture()
                    rule = root / '.claude/rules/custom.md'
                    rule.parent.mkdir(parents=True)
                    rule.write_text('custom')
                    main_rule = root / '.codex/AGENTS.md'
                    main_rule.parent.mkdir()
                    main_rule.write_text('personal\n<!-- gwyn-space-skills: one:start -->\none\n<!-- gwyn-space-skills: one:end -->\n')
                    entries = self.scan_entries()
                self.inventory('select', *(e['id'] for e in entries), scope=scope, cwd=root)
                result = self.inventory('remove', scope=scope, cwd=root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('No backup will be created.', result.stdout)
                self.assertNotIn('Restore:', result.stdout)
                self.assertFalse(rule.exists())
                self.assertFalse((root / '.agents/skills/existing').exists())
                self.assertNotIn('existing', json.loads(lock.read_text())['skills'])
                self.assertFalse(main_rule.exists())
                if scope == 'project':
                    self.assertTrue((root / 'AGENTS.md').exists())
                    self.assertTrue((root / '.claude/rules/nested/.custom.md').exists())
                self.assertFalse(list(self.home.glob('.agent-*-backup-*')))

    def test_local_list_defaults_order_and_read_only(self):
        project, _ = self.project_removal_fixture()
        self.lock_fixture()
        shared = self.home / '.claude/skills'
        shared.parent.mkdir(exist_ok=True)
        shared.symlink_to(self.home / '.agents/skills', target_is_directory=True)
        before = {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        outputs = []
        for args in [('--list',), ('--local', '--list'), ('--list', '--local')]:
            result = subprocess.run(['bash', str(SCRIPT), *args], env=self.env, cwd=project,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs.append(result.stdout)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1], outputs[2])
        for text in ['Global (', 'Project (', 'Rules:', 'Skills:', 'Codex:', 'Claude:', 'Pi:',
                     'owner/repo', 'project/repo', 'existing', 'None']:
            self.assertIn(text, outputs[0])
        self.assertFalse(self.calls())
        self.assertFalse((self.root / 'fetch.log').exists())
        self.assertEqual(before, {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()})

    def test_local_list_filters_broken_links_and_unreadable_lock(self):
        broken = self.home / '.agents/skills/broken'
        broken.symlink_to('missing')
        (self.home / '.agents/.skill-lock.json').write_text('invalid')
        result = self.run_script('--global', '--list-skill')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('broken', result.stdout)
        self.assertIn('Unknown / local', result.stdout)
        self.assertIn('unreadable skill lock', result.stderr)
        self.assertNotIn('Project (', result.stdout)
        self.assertNotIn('Rules:', result.stdout)
        result = self.run_script('--list-rule', '--project')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('Global (', result.stdout)
        self.assertNotIn('Skills:', result.stdout)

    def test_local_rule_sources_require_install_provenance(self):
        directory = self.home / '.claude/rules'
        directory.mkdir(parents=True)
        (directory / 'manual.md').write_text('# Manual\nSee https://github.com/unrelated/reference\n')
        (directory / 'managed.md').write_text('<!-- Installed from https://github.com/owner/repo/blob/main/rules/a.md by setup-agents.sh. -->\n# Managed\n')
        (directory / 'broken.md').symlink_to('missing')
        (directory / 'cycle').symlink_to(directory, target_is_directory=True)
        result = self.run_script('--list-rule', '--global')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('manual.md [Unknown / local]', result.stdout)
        self.assertIn('managed.md [owner/repo]', result.stdout)
        self.assertIn('broken.md [Unknown / local (broken link)]', result.stdout)
        self.assertNotIn('unrelated/reference', result.stdout)

    def test_list_argument_conflicts_and_union(self):
        for args in [('--list', '--local', '--remote'), ('--list-rule', '--agent'),
                     ('--list', '--global', '--project'), ('--remote', '--list', '--global')]:
            result = self.run_script(*args)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        all_content = self.run_script('--list', '--global')
        union = self.run_script('--list-rule', '--global', '--list-skill')
        self.assertEqual(all_content.stdout, union.stdout)
        result = self.source('parse_args --remote --local; printf "%s/%s" "$LIST_RULES" "$LIST_SKILLS"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '0/0')
        self.assertFalse(self.calls())

    def test_remote_rule_and_combined_catalogs(self):
        self.remote_bundle()
        for args in [('--list-rule', '--remote'), ('--remote', '--list-rule'), ('--list', '--remote')]:
            result = self.run_script(*args)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for text in ['Remote available content:', 'Rules:', 'Gwyntoria', 'Waza', 'waza-anti-patterns']:
                self.assertIn(text, result.stdout)
            self.assertEqual('Skills:' in result.stdout, '--list' in args)
        self.assertEqual(list(self.home.rglob('SKILL.md')), [self.old])

    def test_list_ui_local_back_and_remote(self):
        term = self.terminal(cwd=self.root)
        term.send(b'\x1b[B' * 4 + b'\r')
        term.expect('List: choose content')
        term.send(b'\r')
        term.expect('List: choose location')
        term.send(b'\r')
        term.expect('List: choose scope')
        term.send(b'\r')
        term.expect('List: choose agents')
        term.send(b'\x1b')
        term.expect('List: choose scope')
        term.send(b'\r')
        term.expect('List: choose agents')
        term.send(b'\r')
        term.expect('Global (')
        term.expect('existing')
        self.assertEqual(term.finish_action(), 0)
        self.assertFalse(self.calls())

    def test_list_ui_remote_skips_scope_and_agents(self):
        term = self.terminal()
        term.send(b'\x1b[B' * 4 + b'\r')
        term.expect('List: choose content')
        term.send(b' \r')  # skills only
        term.expect('List: choose location')
        term.send(b'\x1b[B\r')
        term.expect('Remote available content:')
        term.expect('Distilly')
        self.assertEqual(term.finish_action(), 0)
        self.assertNotIn(b'List: choose scope', term.transcript)
        self.assertNotIn(b'List: choose agents', term.transcript)

    def test_cli_help_invalid_and_nonterminal(self):
        self.assertEqual(self.run_script('--help').returncode, 0)
        self.assertEqual(self.run_script('--unknown').returncode, 2)
        self.assertEqual(self.run_script('--list', '--skill').returncode, 2)
        result = self.run_script()
        self.assertEqual(result.returncode, 2)
        self.assertIn('requires a terminal', result.stderr)
        self.assertFalse(self.calls())

    def test_list_is_read_only_and_has_all_sources(self):
        result = self.run_script('--list-skill', '--remote')
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ['Waza', 'Kami', 'Matt Pocock', 'HumanLayer', 'show-me',
                     'Gwyntoria', 'gwyntoria-first', 'gwyntoria-last',
                     'Distilly', 'distilly']:
            self.assertIn(name, result.stdout)
        self.assertTrue(any('https://github.com/gwyntoria/skills' in call for call in self.calls()))
        self.assertTrue(all('--list' in call for call in self.calls()))
        self.assertEqual(list(self.home.rglob('SKILL.md')), [self.old])

    def test_repository_batch_failure_continues_to_other_sources(self):
        self.env['FAIL_SKILL'] = 'fail-middle'
        result = self.run_script('--agent', '--skill')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        installed = [c[c.index('--skill') + 1:c.index('--agent')]
                     for c in self.calls() if '--list' not in c]
        self.assertEqual(installed, [['waza-first', 'fail-middle', 'waza-last'],
                                    ['kami'], ['matt-a', 'matt-b'], ['show-me'],
                                    ['gwyntoria-first', 'gwyntoria-last'], ['distilly']])
        self.assertIn('12 succeeded, 1 failed', result.stdout)
        self.assertIn('Waza: waza-first fail-middle waza-last (exit 9)', result.stdout)
        self.assertEqual(self.old.read_text(), 'keep me')
        self.assertTrue((self.home / '.claude/settings.json').is_file())
        self.assertFalse((self.home / '.codex/AGENTS.md').exists())

    def test_nonadjacent_selections_group_by_repository(self):
        result = self.source('''
SKILL_NAMES=(waza-first kami waza-last unselected)
SKILL_SOURCES=("$WAZA_SKILLS_URL" "$KAMI_SKILLS_URL" "$WAZA_SKILLS_URL" "$WAZA_SKILLS_URL")
SKILL_GROUPS=(Waza Kami Waza Waza)
AGENT_ITEMS=()
SELECTED_SKILLS=(0 1 2)
execute_plan''')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        names = [c[c.index('--skill') + 1:c.index('--agent')] for c in calls]
        self.assertEqual(names, [['waza-first', 'waza-last'], ['kami']])
        self.assertFalse((self.home / '.agents/skills/unselected').exists())

    def test_unavailable_sources_continue_and_return_failure(self):
        self.env.update(FAIL_SOURCE='/waza', FAIL_MATT='1')
        result = self.run_script('--skill')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Catalog: Waza', result.stderr)
        self.assertIn('Catalog: Matt Pocock', result.stderr)
        self.assertTrue((self.home / '.agents/skills/kami/SKILL.md').exists())
        self.assertTrue((self.home / '.agents/skills/show-me/SKILL.md').exists())
        self.assertEqual(self.old.read_text(), 'keep me')
        result = self.run_script('--list-skill', '--remote')
        self.assertEqual(result.returncode, 1)
        self.assertIn('HumanLayer', result.stdout)

    def test_unrecognised_catalog_is_reported(self):
        self.env['BAD_CATALOG'] = '1'
        result = self.run_script('--list-skill', '--remote')
        self.assertEqual(result.returncode, 1)
        self.assertIn('no recognisable skill names', result.stderr)
        self.assertIn('Catalog: Waza', result.stderr)

    def test_runner_stops_failed_function_but_continues_next_item(self):
        result = self.source('''bad() { false; touch "$HOME/should-not-exist"; }
run_item bad bad
run_item good touch "$HOME/continued"
print_summary''')
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.home / 'should-not-exist').exists())
        self.assertTrue((self.home / 'continued').exists())

    def test_terminal_cancel_exit_and_default_empty(self):
        term = self.terminal()
        term.send(b'\r')
        term.expect('Choose installation tasks')
        term.expect('> [ ] Rules')
        term.expect('[ ] Skills')
        term.expect('[ ] Agent')
        term.expect('Item 1/3')
        term.send(b'\r')
        self.assertEqual(term.finish_action(), 0)
        self.assertFalse(self.calls())




    def test_terminal_all_none_and_confirmation_cancel(self):
        term = self.terminal()
        term.send(b'\r')
        term.expect('Item 1/3')
        term.send(b'an\x1b[B\x1b[B \r')  # all, none, then Agent
        term.expect('Choose Agents')
        term.expect('Item 1/3')
        term.send(b'n \r')  # just Codex
        term.expect('Execution plan:')
        term.expect('Codex CLI')
        term.expect('Continue? [Y/n]')
        term.send(b'n\n')
        self.assertEqual(term.finish_action(), 0)
        self.assertFalse(self.calls())
        self.assertFalse((self.home / '.claude').exists())













    def test_remove_all_backups_only_deletes_confirmed_setup_directories(self):
        targets = [self.home / '.agent-skills-backup-ABC123', self.home / '.agent-rules-backup-def456']
        for directory in targets:
            directory.mkdir()
            (directory / 'backup').write_text('archive')
        unrelated = self.home / '.agent-skills-backup-manual-copy'
        unrelated.mkdir()
        external = self.root / 'external-backup'
        external.mkdir()
        (external / 'keep').write_text('outside')
        link = self.home / '.agent-rules-backup-LINK12'
        link.symlink_to(external)
        (targets[0] / 'external-link').symlink_to(external)
        term = self.terminal()
        term.send(b'\x1b[B' * 2 + b'\r')
        term.expect('Confirm removal? [Y/n]')
        preview = term.transcript.decode()
        for target in targets:
            self.assertIn(str(target), preview)
        self.assertNotIn(str(link), preview)
        self.assertIn('No new backup is created', preview)
        later = self.home / '.agent-rules-backup-LATER1'
        later.mkdir()  # never confirmed, so it must survive
        term.send(b'\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        for target in targets:
            self.assertFalse(target.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(later.exists())
        self.assertTrue(link.is_symlink())
        self.assertEqual((external / 'keep').read_text(), 'outside')
        self.assertEqual(self.old.read_text(), 'keep me')

    def test_remove_all_backups_cancel_and_empty(self):
        term = self.terminal()
        term.send(b'\x1b[B' * 2 + b'\r')
        term.expect('No setup backups found.')
        self.assertEqual(term.finish_action(), 0)
        target = self.home / '.agent-skills-backup-ABC123'
        target.mkdir()
        for choice in [b'n\n', b'N\n', b'DELETE\n', b'yes\n']:
            with self.subTest(choice=choice):
                term = self.terminal()
                term.send(b'\x1b[B' * 2 + b'\r')
                term.expect('Confirm removal? [Y/n]')
                term.send(choice)
                self.assertEqual(term.finish_action(), 0)
                self.assertTrue(target.is_dir())

    def test_backup_cleanup_rejects_changed_targets_before_deleting_any(self):
        first = self.home / '.agent-skills-backup-ABC123'
        first.mkdir()
        external = self.root / 'outside-backup'
        external.mkdir()
        link = self.home / '.agent-rules-backup-LINK12'
        link.symlink_to(external)
        result = self.source('remove_setup_backups .agent-skills-backup-ABC123 .agent-rules-backup-LINK12')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Backup is no longer a directory', result.stderr)
        self.assertTrue(first.is_dir())
        self.assertTrue(link.is_symlink())




if __name__ == '__main__':
    unittest.main(verbosity=2)
