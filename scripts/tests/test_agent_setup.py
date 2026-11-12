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

SCRIPT = Path(__file__).resolve().parents[1] / 'agent-setup.sh'

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
        self.expect('Item 1/5')

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
        term.send(b' \x1b[B\x1b[B\r')
        term.expect('Continue? [y/N]')
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
        term.expect('Continue? [y/N]')
        term.send(b'y\n')
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
                self.assertIn('agent-behavior [Codex:block]', result.stdout)

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
        terminal.expect('Item 1/5')
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
            '.claude/rules/nested/.custom.md': 'custom rule',
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
            'AGENTS.md', '.claude/rules/nested/.custom.md',
            '.agents/skills/existing', '.claude/skills/existing'})
        self.assertTrue(all(e['group'] == 'project/repo' for e in entries if e['kind'] == 'skills'))
        self.assertEqual(self.inventory('select', *(e['id'] for e in entries), scope='project', cwd=project).returncode, 0)
        result = self.inventory('preview', scope='project', cwd=project)
        self.assertIn(f'Removal scope: project ({project})', result.stdout)
        result = self.inventory('remove', '1', scope='project', cwd=project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('4 succeeded, 0 failed', result.stdout)
        self.assertEqual((project / 'AGENTS.md').read_bytes(), b'personal\r\nend\r\n')
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
            self.assertIn('AGENTS.md', archive.getnames())
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
        term.expect('Confirm removal? [y/N]')
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
        term.expect('.custom.md [Claude:file]')
        term.expect('Item 1/1')
        term.send(b' \r')
        term.expect('Removal scope: project')
        term.expect('Create backup? [y/N]')
        term.send(b'\n')
        term.expect('Confirm removal? [y/N]')
        term.send(b'y\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertTrue(global_rule.exists())
        self.assertFalse((project / '.claude/rules/nested/.custom.md').exists())

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
        term.expect('Item 1/5')
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
            for label in ['[x] Codex', '[x] Claude Code', '[ ] Pi']:
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
        self.assertIn('/blob/' + commit + '/rules/chinese.md', installed)
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
        self.assertIn('waza-chinese:start', old.read_text())
        self.assertIn('code-comments:start', old.read_text())
        self.assertNotIn('waza-english:start', old.read_text())
        self.assertFalse((self.home / '.claude/rules/waza-english.md').exists())

    def test_waza_engine_formats_claude_h2_and_keeps_codex_project_body(self):
        fixture = self.root / 'waza-h2'
        fixture.mkdir()
        content = '## English Coaching\n\nOriginal body.\n'
        (fixture / 'waza-english.md').write_text(content)
        result = self.source(
            f'rule_engine waza-english project both install {shlex.quote(str(fixture))} waza',
            cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / '.claude/rules/waza-english.md').read_text(),
                         content.replace('## English Coaching', '# English Coaching'))
        self.assertIn(content, (self.root / 'AGENTS.md').read_text())

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
        installed = self.root / '.claude/rules/waza-chinese.md'
        self.assertEqual(installed.read_text(), content.replace('## Chinese', '# Chinese'))
        self.assertIn(content, (self.root / 'AGENTS.md').read_text())
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
                self.assertTrue(text.startswith('# Global Rules\n\n' + personal))
                self.assertEqual(text.count('# Global Rules\n'), 1)
                self.assertIn('\n## Example\n\n### Details\n', text)
                unchanged = body[body.index('Text # stays.'):]
                self.assertIn(unchanged, text)
                self.assertNotIn(b'\n', destination.read_bytes().replace(b'\r\n', b''))
                claude = self.home / '.claude/rules/waza-example.md'
                self.assertEqual(claude.read_text(), '# Example\n\n## Details\n' + unchanged)
                before = destination.read_bytes()
                result = self.source(command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(destination.read_bytes(), before)
                self.assertIn('already installed (claude, global)', result.stdout)
                result = self.source('rule_engine waza-example global codex remove')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(destination.read_text(), '# Global Rules\n\n' + personal)

    def test_repeated_rule_batch_is_already_installed_without_rewriting_shared_files(self):
        self.waza_bundle(('chinese', 'clarity', 'english'))
        command = '\n'.join(f'apply_rule waza-{name} global "codex claude pi" install waza'
                            for name in ('chinese', 'clarity', 'english'))
        for eol in ('\n', '\r\n'):
            with self.subTest(eol=repr(eol)):
                for folder in ('.codex', '.claude', '.pi'):
                    shutil.rmtree(self.home / folder, ignore_errors=True)
                shared = [self.home / '.codex/AGENTS.md', self.home / '.pi/agent/AGENTS.md']
                for target in shared:
                    target.parent.mkdir(parents=True)
                    target.write_bytes(('# Global Rules\n\nPersonal notes.\n').replace('\n', eol).encode())
                first = self.source(command)
                self.assertEqual(first.returncode, 0, first.stderr)
                self.assertEqual(first.stdout.count('installation complete ('), 9)
                targets = shared + list((self.home / '.claude/rules').glob('*.md'))
                before = {target: (target.read_bytes(), target.stat().st_ino, target.stat().st_mtime_ns)
                          for target in targets}
                second = self.source(command)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertEqual(second.stdout.count('already installed ('), 9, second.stdout)
                for target, state in before.items():
                    self.assertEqual((target.read_bytes(), target.stat().st_ino, target.stat().st_mtime_ns), state)

    def test_updating_middle_rule_preserves_order_separators_and_personal_text(self):
        for eol in (b'\n', b'\r\n'):
            with self.subTest(eol=eol):
                self.waza_bundle(('chinese', 'clarity', 'english'))
                for folder in ('.codex', '.claude', '.pi'):
                    shutil.rmtree(self.home / folder, ignore_errors=True)
                targets = [self.home / '.codex/AGENTS.md', self.home / '.pi/agent/AGENTS.md']
                for target in targets:
                    target.parent.mkdir(parents=True)
                    target.write_bytes(b'# Global Rules' + eol + eol + b'Personal notes.' + eol)
                command = '\n'.join(f'apply_rule waza-{name} global "codex claude pi" install waza'
                                    for name in ('chinese', 'clarity', 'english'))
                result = self.source(command)
                self.assertEqual(result.returncode, 0, result.stderr)
                before = {}
                for target in targets:
                    content = target.read_bytes().replace(
                        b'<!-- gwyn-space-skills: waza-clarity:end -->' + eol,
                        b'<!-- gwyn-space-skills: waza-clarity:end -->' + eol + eol
                        + b'Personal text between rules.' + eol + eol)
                    content += eol + eol
                    target.write_bytes(content)
                    before[target] = content
                source = Path(self.env['WAZA_FILES']) / 'clarity.md'
                source.write_text('# clarity\nUpdated clarity body.\n')
                result = self.source('apply_rule waza-clarity global "codex claude pi" install waza')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.count('installation complete ('), 3)
                for target, content in before.items():
                    self.assertEqual(target.read_bytes(), content.replace(b'Upstream clarity body.', b'Updated clarity body.'))
                repeated = self.source(command)
                self.assertEqual(repeated.returncode, 0, repeated.stderr)
                self.assertEqual(repeated.stdout.count('already installed ('), 9, repeated.stdout)

    def test_global_local_rule_keeps_title_and_project_behavior(self):
        result = self.source('apply_rule code-comments global both install project', cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        source = (SCRIPT.parents[1] / 'rules/code-comments.md').read_text()
        codex = (self.home / '.codex/AGENTS.md').read_text()
        self.assertTrue(codex.startswith('# Global Rules\n'))
        self.assertIn('## Code Comment Guidelines\n', codex)
        self.assertIn('### Format and Language\n', codex)
        self.assertEqual((self.home / '.claude/rules/code-comments.md').read_text(), source)
        result = self.source('apply_rule code-comments project codex', cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        project = (self.root / 'AGENTS.md').read_text()
        self.assertNotIn('# Global Rules', project)
        self.assertNotIn('Code Comment Guidelines', project)
        self.assertIn(source.split('\n', 1)[1], project)

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
        for name in ('code-comments', 'waza-code-comments', 'waza-new-rule', 'agent-behavior'):
            self.assertEqual(text.count(f'gwyn-space-skills: {name}:start'), 1)
        self.assertIn('Personal', text)
        self.assertIn('Legacy', text)
        self.assertEqual((self.home / '.claude/rules/waza-code-comments.md').read_text(),
                         '# code-comments\nUpstream code-comments body.\n')
        self.assertTrue((self.home / '.claude/rules/code-comments.md').exists())
        self.assertEqual(len((self.root / 'fetch.log').read_text().splitlines()), 4)

    def test_agent_flag_terminal_opens_agent_selection(self):
        term = Terminal(self.env, cwd=self.root, command=['bash', str(SCRIPT), '--agent'])
        self.addCleanup(term.close)
        term.expect('Choose Agents')
        term.expect('Item 1/3')
        for label in ['[x] Codex', '[x] Claude Code (with statusline)', '[ ] Pi (with three packages)']:
            self.assertIn(label, term.transcript.decode())
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertFalse((self.home / '.codex').exists())

    def test_waza_failure_can_skip_without_touching_configs(self):
        self.env['FAIL_DOWNLOAD'] = '1'
        term = Terminal(self.env, cwd=self.root)
        self.addCleanup(term.close)
        term.expect('Item 1/5')
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
        self.assertIn('[ ] project', re.sub(r'\x1b\[[0-9;]*m', '', term.transcript.decode()))
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertFalse((self.home / '.codex').exists())

    def test_rule_tree_group_selection_installs_every_rule_with_correct_source(self):
        self.waza_bundle(('anti-patterns', 'chinese', 'code-comments'))
        term = self.rule_terminal(cwd=self.root)
        term.send(b' ')
        term.expect('[x] Waza')
        term.expect('(3/3)')
        term.send(b'\x1b[B ')
        term.expect('[x] project')
        term.expect('(3/3)')
        term.send(b'\x1b[B\r')
        self.rule_agents_and_scope(term)
        term.send(b'\r')
        term.expect('6 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        text = (self.root / 'AGENTS.md').read_text()
        for name in ('waza-anti-patterns', 'waza-chinese', 'waza-code-comments',
                     'code-comments', 'chinese-punctuation', 'writing-repo'):
            self.assertEqual(text.count(f'gwyn-space-skills: {name}:start'), 1)
        self.assertIn('Upstream code-comments body.', text)
        self.assertIn('Installed from rules/code-comments.md', text)

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
        term.expect('Source: project')
        term.expect('[x] code-comments')
        term.send(b'n')
        term.expect('[ ] code-comments')
        term.send(b'ab')
        term.expect('[x] project')
        term.expect('(3/3)')
        term.send(b'n')
        term.expect('[ ] Waza')
        term.expect('[ ] project')
        term.send(b'a')
        term.expect('[x] Waza')
        term.expect('[x] project')
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
        term = self.rule_terminal(cwd=nested)
        self.assertIn('[ ] Waza', re.sub(r'\x1b\[[0-9;]*m', '', term.transcript.decode()))
        self.assertIn('[ ] project', re.sub(r'\x1b\[[0-9;]*m', '', term.transcript.decode()))
        term.send(b'\x1b[B\r\x1b[B \r\x1b[B\r')
        self.rule_agents_and_scope(term)
        self.assertIn(str(nested / 'AGENTS.md'), term.transcript.decode())
        self.assertNotIn('Rules: choose agents', term.transcript.decode())
        self.assertIn('Rule source:', term.transcript.decode())
        frame = term.transcript.decode().rsplit('\x1b[H\x1b[2J', 1)[-1]
        self.assertIn(str(nested / 'AGENTS.md'), frame)
        self.assertIn('Execution plan:', frame)
        self.assertIn('project / code-comments -> AGENTS.md', frame)
        term.send(b'b')
        term.expect('Rules: choose scope')
        term.expect('> Project')
        term.send(b'b')
        term.expect('Choose rules')
        term.expect('[-] project')
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
        text = (nested / 'AGENTS.md').read_text()
        self.assertIn(personal, text)
        self.assertEqual(text.count('<!-- gwyn-space-skills: code-comments:start -->'), 1)
        self.assertIn('Installed from rules/code-comments.md by agent-setup.sh', text)
        self.assertEqual((project / 'AGENTS.md').read_text(), 'root must stay unchanged\n')
        self.assertFalse((nested / '.claude').exists())
        result = self.source('apply_rule code-comments project codex', cwd=nested)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((nested / 'AGENTS.md').read_text(), text)

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
                    for label in ['[x] Codex', '[x] Claude Code', '[ ] Pi']:
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
        term.expect('[-] project')
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
                selected = {'codex', 'claude'} if agent == 'default' else {agent}
                for name, destination in destinations.items():
                    self.assertEqual(str(destination) in frame, name in selected)
                term.send(b'\r')
                term.expect('1 succeeded, 0 failed')
                self.assertEqual(term.finish_action(), 0)
                for name, destination in destinations.items():
                    self.assertEqual(destination.exists(), name in selected)

    def test_pi_global_engine_custom_directory_updates_and_preserves_content(self):
        self.env['PI_CODING_AGENT_DIR'] = '~/custom pi'
        destination = self.home / 'custom pi/AGENTS.md'
        destination.parent.mkdir()
        personal = 'Personal notes.\n'
        destination.write_text(personal)
        command = 'apply_rule code-comments global pi install project'
        result = self.source(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = destination.read_text()
        self.assertTrue(text.startswith('# Global Rules\n\n' + personal))
        self.assertIn('## Code Comment Guidelines', text)
        self.assertIn('### Format and Language', text)
        self.assertFalse((self.home / '.pi').exists())
        result = self.source(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(destination.read_text(), text)
        self.assertIn('already installed (pi, global)', result.stdout)
        destination.write_text(personal + '<!-- gwyn-space-skills: code-comments:start -->\n')
        before = destination.read_bytes()
        result = self.source(command)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unbalanced markers', result.stderr)
        self.assertEqual(destination.read_bytes(), before)

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
                codex = project / 'AGENTS.md' if scope == 'project' else self.home / '.codex/AGENTS.md'
                text = codex.read_text()
                self.assertIn('https://github.com/tw93/Waza/blob/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/rules/anti-patterns.md', text)
                self.assertIn('Installed from rules/code-comments.md', text)
                self.assertEqual(text.count('waza-anti-patterns:start'), 1)
                self.assertEqual(text.count('code-comments:start'), 1)
                if scope == 'project':
                    self.assertNotIn('Rules: choose agents', term.transcript.decode())
                    self.assertFalse((project / '.claude').exists())
                    self.assertFalse((self.home / '.pi').exists())
                else:
                    claude = self.home / '.claude/rules'
                    self.assertTrue((claude / 'code-comments.md').exists())
                    self.assertTrue((claude / 'waza-anti-patterns.md').exists())
                    pi = self.home / '.pi/agent/AGENTS.md'
                    self.assertEqual(pi.read_text(), codex.read_text())

    def test_rule_engine_preserves_old_markers_and_rejects_conflicts(self):
        project = self.root / 'project'
        project.mkdir()
        destination = project / 'AGENTS.md'
        destination.write_text('Personal\n\n<!-- gwyn-space-skills: code-comments:start -->\n'
                               '<!-- Installed from instructions/project/code-comments.md by agent-install-rule.sh. -->\n'
                               'old body\n<!-- gwyn-space-skills: code-comments:end -->\n')
        result = self.source('apply_rule code-comments project codex', cwd=project)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = destination.read_text()
        self.assertIn('Personal', text)
        self.assertNotIn('old body', text)
        self.assertEqual(text.count('code-comments:start'), 1)
        destination.write_text('Personal\n<!-- gwyn-space-skills: code-comments:start -->\nkeep\n')
        before = destination.read_bytes()
        result = self.source('apply_rule code-comments project codex', cwd=project)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unbalanced markers', result.stderr)
        self.assertEqual(destination.read_bytes(), before)

    def test_legacy_global_copy_migrates_with_restore_backup(self):
        destination = self.home / '.codex/AGENTS.md'
        destination.parent.mkdir()
        original = b'# Legacy behavior\nLegacy rule\n'
        fixture = self.root / 'legacy'
        fixture.mkdir()
        (fixture / 'agent-behavior.md').write_bytes(original)
        destination.write_bytes(original)
        result = self.source(f'rule_engine agent-behavior global codex install {shlex.quote(str(fixture))} global')
        self.assertEqual(result.returncode, 0, result.stderr)
        backups = list(destination.parent.glob('AGENTS.md.pre-rules.bak-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertIn('agent-behavior:start', destination.read_text())

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
        self.assertIn(str(project / 'AGENTS.md'), frame)
        self.assertIn('GitHub gwyntoria/skills @ main', frame)
        term.send(b'\r')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertTrue((project / 'AGENTS.md').exists())
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
        self.assertTrue((self.root / 'AGENTS.md').exists())
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
        term.expect('Item 1/5')
        term.send(b'\x1b[B' * 3 + b'\r')
        term.expect('Update this command?')
        term.expect('Continue? [y/N]')
        self.assertEqual(installed.read_bytes(), SCRIPT.read_bytes())
        self.assertFalse((self.root / 'fetch.log').exists())
        term.send(b'y\n')
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
            for answer in (b'\n', b'n\n', b'b\n', b'q\n'):
                with self.subTest(installed=installed, answer=answer):
                    term = self.terminal()
                    term.send(b'\x1b[B' * 3 + b'\r')
                    term.expect(('Update' if installed else 'Install') + ' this command?')
                    term.expect(str(destination))
                    term.expect('Continue? [y/N]')
                    self.assertEqual(destination.exists(), installed)
                    term.send(answer)
                    if answer == b'b\n':
                        term.expect('Agent setup')
                        term.expect('Item 4/5')
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

    def test_command_confirmation_installs_only_after_yes(self):
        destination = self.home / '.local/bin/agent-setup'
        term = self.terminal()
        term.send(b'\x1b[B' * 3 + b'\r')
        term.expect('Install this command?')
        term.expect('Continue? [y/N]')
        self.assertFalse(destination.parent.exists())
        term.send(b'y\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertEqual(destination.read_bytes(), SCRIPT.read_bytes())

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
        term.expect('Continue? [y/N]')
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
        term.expect('Continue? [y/N]')
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
        term.expect('Item 1/5')
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
        term.expect('Item 1/5')
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
        term.expect('Item 1/5')
        for _ in range(2):
            term.send(b'\r')
            term.expect('Choose installation tasks')
            term.expect('Item 1/3')
            term.send(b'\x1b[B' * 2 + b' \r')
            term.expect('Choose Agents')
            term.expect('Item 1/3')
            term.send(b'n\x1b[B \r')
            term.expect('Continue? [y/N]')
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
        term.send(b' \r')
        term.expect('Continue? [y/N]')
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
        term.expect('Continue? [y/N]')
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
        term.expect('[ ] Codex / codebase-design [directory]')
        term.expect('[x] Codex / tdd [directory]')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)

    def test_repository_whole_selection_reuses_catalog_across_tasks(self):
        term = self.install_skill_terminal(repos='all')
        for run in range(2):
            term.send(b'a\x1b[A\r')  # every skill, then Continue
            term.expect('Install skills for')
            term.expect('Item 1/2')
            term.send(b'\r')
            term.expect('Continue? [y/N]')
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

    def test_rule_inventory_and_selective_blocks_preserve_personal_bytes(self):
        personal = '个人文字\r\n'.encode()
        a = b'<!-- gwyn-space-skills: one:start -->\r\none\r\n<!-- gwyn-space-skills: one:end -->\r\n'
        b = b'<!-- gwyn-space-skills: two:start -->\r\ntwo\r\n<!-- gwyn-space-skills: two:end -->\r\n'
        target = self.home / '.codex/AGENTS.md'
        target.parent.mkdir()
        target.write_bytes(personal + a + b + b'last\r\n')
        custom = self.home / '.claude/rules/nested/.custom.md'
        custom.parent.mkdir(parents=True)
        custom.write_text('custom content')
        kept = custom.parent / 'keep.md'
        kept.write_text('keep')
        entries = self.scan_entries(skills=False)
        self.assertEqual({e['type'] for e in entries}, {'block', 'file'})
        self.select_entries([e for e in entries if e['name'] in ['one', 'rules/nested/.custom.md']])
        result = self.inventory('remove', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_bytes(), personal + b + b'last\r\n')
        self.assertFalse(custom.exists())
        self.assertEqual(kept.read_text(), 'keep')
        backup, = self.home.glob('.agent-rules-backup-*/removal.tar')
        with tarfile.open(backup) as tar:
            self.assertIn('.codex/AGENTS.md', tar.getnames())
            self.assertIn('.claude/rules/nested/.custom.md', tar.getnames())

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
        term.expect('one [Pi:block]')
        term.expect('two [Pi:block]')
        term.expect('Item 1/2')
        frame = term.transcript.decode().rsplit('\x1b[H\x1b[2J', 1)[-1]
        self.assertNotIn('Codex /', frame)
        self.assertNotIn('Claude /', frame)
        term.send(b' \r')
        term.expect(str(target))
        term.expect('Create backup? [y/N]')
        term.send(b'\n')
        term.expect('Confirm removal? [y/N]')
        self.assertIn('## one', target.read_text())
        term.send(b'y\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertEqual(target.read_text(), personal + blocks['two'])
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
        term.expect('one [Codex:block] [Pi:block]')
        term.expect('two [Pi:block]')
        term.expect('Item 1/2')
        term.send(b'a\r')
        term.expect('Create backup? [y/N]')
        term.send(b'\n')
        term.expect('Confirm removal? [y/N]')
        term.send(b'y\n')
        term.expect('3 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertEqual(target.read_text(), personal)
        self.assertEqual(codex.read_text(), 'Codex notes.\n')

    def test_global_removal_default_preserves_pi_rules(self):
        codex, claude, pi, _, _ = self.grouped_rule_fixture()
        before = pi.read_bytes()
        term = self.removal_terminal(types=('Rules',), agents='default')
        term.expect('one [Codex:block] [Claude:file]')
        term.expect('Item 1/1')
        term.send(b'a\r')
        term.expect('Create backup? [y/N]')
        term.send(b'\n')
        term.expect('Confirm removal? [y/N]')
        term.send(b'y\n')
        term.expect('2 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertEqual(pi.read_bytes(), before)
        self.assertEqual(codex.read_text(), 'Codex notes.\n')
        self.assertFalse(claude.exists())

    def grouped_rule_fixture(self):
        pi, personal, blocks = self.pi_removal_fixture()
        codex = self.home / '.codex/AGENTS.md'
        codex.parent.mkdir()
        codex.write_text('Codex notes.\n' + blocks['one'])
        claude = self.home / '.claude/rules/one.md'
        claude.parent.mkdir(parents=True)
        claude.write_text('# one\nBody.\n')
        return codex, claude, pi, personal, blocks

    def test_rule_group_recognizes_installer_generated_waza_files_in_both_scopes(self):
        for scope in ('global', 'project'):
            with self.subTest(scope=scope):
                result = self.source(f'apply_rule waza-anti-patterns {scope} both install waza', cwd=self.root)
                self.assertEqual(result.returncode, 0, result.stderr)
                if scope == 'global':
                    result = self.source('apply_rule waza-anti-patterns global pi install waza')
                    self.assertEqual(result.returncode, 0, result.stderr)
                result = self.inventory('scan', 1, 1, 1, 0, int(scope == 'global'), scope=scope, cwd=self.root)
                self.assertEqual(result.returncode, 0, result.stderr)
                result = self.inventory('rows', scope=scope, cwd=self.root)
                self.assertEqual(result.returncode, 0, result.stderr)
                rows = result.stdout.splitlines()
                self.assertEqual(len(rows), 1)
                self.assertIn('waza-anti-patterns [Codex:block] [Claude:file]', rows[0])
                self.assertEqual('[Pi:block]' in rows[0], scope == 'global')

    def test_rule_group_ui_expands_one_choice_to_all_agents(self):
        codex, claude, pi, personal, blocks = self.grouped_rule_fixture()
        term = self.removal_terminal(types=('Rules',))
        label = 'one [Codex:block] [Claude:file] [Pi:block]'
        term.expect(label)
        term.expect('two [Pi:block]')
        term.expect('Item 1/2')
        frame = term.transcript.decode().rsplit('\x1b[H\x1b[2J', 1)[-1]
        self.assertEqual(frame.count(label), 1)
        term.send(b' \r')
        term.expect('Removal targets:')
        term.expect(label)
        for target in (codex, claude, pi):
            term.expect(str(target))
        term.expect('Create backup? [y/N]')
        term.send(b'\n')
        term.expect('Confirm removal? [y/N]')
        term.send(b'y\n')
        term.expect('OK removed ' + label)
        term.expect('Rules: 1 removed, 0 partial, 0 failed')
        term.expect('3 succeeded, 0 failed (installation targets)')
        self.assertEqual(term.finish_action(), 0)
        self.assertEqual(codex.read_text(), 'Codex notes.\n')
        self.assertFalse(claude.exists())
        self.assertEqual(pi.read_text(), personal + blocks['two'])

    def test_rule_group_back_and_default_cancel_preserve_all_copies(self):
        codex, claude, pi, _, _ = self.grouped_rule_fixture()
        before = {target: target.read_bytes() for target in (codex, claude, pi)}
        term = self.removal_terminal(types=('Rules',))
        label = 'one [Codex:block] [Claude:file] [Pi:block]'
        term.expect('Item 1/2')
        term.send(b' \r')
        term.expect('Create backup? [y/N]')
        term.send(b'b\n')
        term.expect('[x] ' + label)
        term.expect('Item 1/2')
        term.send(b'\r')
        term.expect('Create backup? [y/N]')
        term.send(b'y\n')
        term.expect('Confirm removal? [y/N]')
        term.send(b'\n')
        term.expect('Cancelled.')
        self.assertEqual(term.finish_action(), 0)
        for target, content in before.items():
            self.assertEqual(target.read_bytes(), content)
        self.assertFalse(list(self.home.glob('.agent-*-backup-*')))

    def test_rule_group_respects_agent_filter_and_keeps_links_and_custom_files_separate(self):
        codex, claude, pi, _, _ = self.grouped_rule_fixture()
        nested = claude.parent / 'nested/one.md'
        nested.parent.mkdir()
        nested.write_text(claude.read_text())
        linked = claude.parent / 'linked.md'
        linked.symlink_to(claude)
        self.scan_entries(codex=False, skills=False, pi=True)
        rows = self.inventory('rows')
        self.assertEqual(rows.returncode, 0, rows.stderr)
        self.assertIn('one [Claude:file] [Pi:block]', rows.stdout)
        self.assertNotIn('Codex', rows.stdout)
        self.assertIn('rules/nested/one.md [Claude:file]', rows.stdout)
        self.assertIn('rules/linked.md [Claude:link]', rows.stdout)
        row = next(line for line in rows.stdout.splitlines() if 'one [Claude:file] [Pi:block]' in line)
        self.assertEqual(self.inventory('select', row.split('\t')[0]).returncode, 0)
        result = self.inventory('remove')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(codex.exists())
        self.assertIn('## one', codex.read_text())
        self.assertFalse(claude.exists())
        self.assertNotIn('## one', pi.read_text())
        self.assertTrue(nested.exists())
        self.assertTrue(linked.is_symlink())

    def test_rule_group_does_not_merge_same_filename_with_different_heading(self):
        _, claude, _, _, _ = self.grouped_rule_fixture()
        claude.write_text('# Personal rule\nKeep me.\n')
        self.scan_entries(skills=False, pi=True)
        rows = self.inventory('rows')
        self.assertIn('one [Codex:block] [Pi:block]', rows.stdout)
        self.assertIn('rules/one.md [Claude:file]', rows.stdout)
        self.assertNotIn('one [Codex:block] [Claude:file]', rows.stdout)

    def test_rule_group_backup_contains_all_selected_agents_and_restores(self):
        codex, claude, pi, _, _ = self.grouped_rule_fixture()
        before = {target: target.read_bytes() for target in (codex, claude, pi)}
        self.scan_entries(skills=False, pi=True)
        rows = self.inventory('rows')
        group_id = next(line.split('\t')[0] for line in rows.stdout.splitlines()
                        if 'one [Codex:block]' in line)
        self.assertEqual(self.inventory('select', group_id).returncode, 0)
        result = self.inventory('remove', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        backup, = self.home.glob('.agent-rules-backup-*/removal.tar')
        with tarfile.open(backup) as tar:
            self.assertEqual(set(tar.getnames()), {str(target.relative_to(self.home)) for target in before})
        subprocess.run(['tar', '-xf', str(backup), '-C', str(self.home)], check=True)
        for target, content in before.items():
            self.assertEqual(target.read_bytes(), content)

    def test_rule_group_changed_copy_aborts_before_any_deletion(self):
        codex, claude, pi, _, _ = self.grouped_rule_fixture()
        self.scan_entries(skills=False, pi=True)
        rows = self.inventory('rows')
        group_id = next(line.split('\t')[0] for line in rows.stdout.splitlines()
                        if 'one [Codex:block]' in line)
        self.assertEqual(self.inventory('select', group_id).returncode, 0)
        claude.write_text('# one\nUser edit during confirmation.\n')
        before = {target: target.read_bytes() for target in (codex, claude, pi)}
        result = self.inventory('remove')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Content changed; rescan', result.stderr)
        for target, content in before.items():
            self.assertEqual(target.read_bytes(), content)

    def test_rule_group_partial_failure_reports_each_target_and_continues(self):
        codex, claude, pi, personal, blocks = self.grouped_rule_fixture()
        self.scan_entries(skills=False, pi=True)
        rows = self.inventory('rows')
        group_id = next(line.split('\t')[0] for line in rows.stdout.splitlines()
                        if 'one [Codex:block]' in line)
        self.assertEqual(self.inventory('select', group_id).returncode, 0)
        preload = self.root / 'fail-rule.cjs'
        preload.write_text('const fs=require("fs");const original=fs.rmSync;fs.rmSync=function(p,...args){if(p==='
                           + json.dumps(str(claude)) + ') throw Error("fixture rule removal failed");return original.call(this,p,...args);};')
        self.env['NODE_OPTIONS'] = f'--require={preload}'
        result = self.inventory('remove')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('PARTIAL one [Codex:block] [Claude:file] [Pi:block]', result.stdout)
        self.assertIn('Rules: 0 removed, 1 partial, 0 failed', result.stdout)
        self.assertIn('2 succeeded, 1 failed (installation targets)', result.stdout)
        self.assertIn('OK [Codex:block] ' + str(codex), result.stdout)
        self.assertIn('OK [Pi:block] ' + str(pi), result.stdout)
        self.assertIn('FAIL [Claude:file] ' + str(claude), result.stderr)
        self.assertIn('fixture rule removal failed', result.stderr)
        self.assertEqual(codex.read_text(), 'Codex notes.\n')
        self.assertTrue(claude.exists())
        self.assertEqual(pi.read_text(), personal + blocks['two'])

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

    def test_pi_removal_selected_block_backup_and_user_content(self):
        target, personal, blocks = self.pi_removal_fixture()
        before = target.read_bytes()
        entries = self.scan_entries(codex=False, claude=False, skills=False, pi=True)
        self.assertEqual([(e['agent'], e['name']) for e in entries], [('pi', 'one'), ('pi', 'two')])
        rows = self.inventory('rows')
        self.assertIn('one [Pi:block]', rows.stdout)
        self.select_entries([entries[0]])
        preview = self.inventory('preview')
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn(str(target), preview.stdout)
        result = self.inventory('remove', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_text(), personal + blocks['two'])
        backup, = self.home.glob('.agent-rules-backup-*/removal.tar')
        with tarfile.open(backup) as archive:
            self.assertEqual(archive.extractfile('.pi/agent/AGENTS.md').read(), before)
        self.assertTrue(self.old.exists())

    def test_pi_removal_custom_directory_and_path_change_require_rescan(self):
        target, _, _ = self.pi_removal_fixture(self.home / 'custom pi')
        self.env['PI_CODING_AGENT_DIR'] = '~/custom pi'
        entries = self.scan_entries(codex=False, claude=False, skills=False, pi=True)
        self.assertEqual(len(entries), 2)
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

    def test_pi_removal_rejects_broken_markers_changed_files_and_backup_failure(self):
        target, _, _ = self.pi_removal_fixture()
        before = target.read_bytes()
        target.write_text('<!-- gwyn-space-skills: broken:start -->\n')
        result = self.inventory('scan', 0, 0, 1, 0, 1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unbalanced managed rule markers', result.stderr)
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

    def test_multiple_blocks_in_same_file_remove_together(self):
        target = self.home / '.codex/AGENTS.md'
        target.parent.mkdir()
        target.write_text('personal\n' + ''.join(f'<!-- gwyn-space-skills: {n}:start -->\n{n}\n<!-- gwyn-space-skills: {n}:end -->\n' for n in ['one', 'two']))
        entries = self.scan_entries(skills=False)
        self.select_entries(entries)
        result = self.inventory('remove')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('2 succeeded, 0 failed', result.stdout)
        self.assertEqual(target.read_text(), 'personal\n')

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

    def test_scan_rejects_symlinked_parents_and_unbalanced_blocks(self):
        directory = self.home / '.claude'
        directory.symlink_to(self.root)
        result = self.inventory('scan', 1, 1, 1, 1)
        self.assertNotEqual(result.returncode, 0)
        directory.unlink()
        target = self.home / '.codex/AGENTS.md'
        target.parent.mkdir()
        target.write_text('<!-- gwyn-space-skills: broken:start -->\nkeep\n')
        result = self.inventory('scan', 1, 1, 1, 1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unbalanced', result.stderr)
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
        term.expect('Confirm removal? [y/N]')
        self.assertEqual(term.transcript.count(b'Confirm removal? [y/N]'), 1)
        self.assertIn(b'\x1b[31m', term.transcript)
        term.send(b'y\n')
        term.expect('2 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertFalse(custom.exists())
        self.assertFalse(link.is_symlink())
        self.assertTrue(self.old.exists())
        backup, = self.home.glob('.agent-rules-backup-*/removal.tar')
        self.assertEqual(backup.parent.stat().st_mode & 0o777, 0o700)

    def test_removal_repository_child_can_select_one_agent_only(self):
        self.lock_fixture()
        link = self.home / '.claude/skills/existing'
        link.parent.mkdir(parents=True)
        link.symlink_to(self.old.parent)
        term = self.removal_terminal()
        term.expect('Remove skills by repository')
        term.expect('Item 1/2')
        term.send(b'\r')
        term.expect('Codex / existing [directory]')
        term.expect('Claude / existing [link]')
        term.send(b' \r')  # only first Codex entry
        term.expect('[-] owner/repo')
        term.send(b'b')
        term.expect('Remove: choose agents')
        term.expect('Item 1/3')
        term.send(b'\r')
        term.expect('[-] owner/repo')
        term.send(b'\x1b[A\r')
        term.expect('WARNING: Claude link will be kept')
        term.expect('Create backup? [y/N]')
        term.send(b'\n')
        term.expect('Confirm removal? [y/N]')
        term.send(b'y\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertTrue(link.is_symlink())
        self.assertFalse(self.old.exists())
        self.assertTrue((self.home / '.agents/skills/other').exists())

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
        term.expect('Item 2/5')
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
        term.send(b'\r')
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
        term.expect('Confirm removal? [y/N]')
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
        term.expect('Confirm removal? [y/N]')
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

    def test_removal_confirmation_back_preserves_selection_and_q_exits(self):
        term = self.removal_terminal()
        term.expect('Remove skills by repository')
        term.expect('Item 1/2')
        term.send(b' \x1b[A\r')
        term.expect('Create backup? [y/N]')
        term.send(b'y\n')
        term.expect('All selected content will be backed up')
        term.expect('Confirm removal? [y/N]')
        self.assertFalse(list(self.home.glob('.agent-*-backup-*')))
        term.send(b'b\n')
        term.expect('Create backup? [y/N]')
        term.send(b'\n')  # returning resets the previous yes to no
        term.expect('No backup will be created.')
        term.expect('Confirm removal? [y/N]')
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
        term.expect('Confirm removal? [y/N]')
        term.send(b'q\n')
        self.assertEqual(term.finish(), 0)
        self.assertTrue(self.old.exists())
        self.assertFalse(list(self.home.glob('.agent-*-backup-*')))

    def test_removal_backup_prompt_q_and_confirmation_cancel_create_nothing(self):
        for choice in [b'q\n', b'\n', b'n\n', b'N\n', b'DELETE\n', b'yes\n']:
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
                    term.expect('Confirm removal? [y/N]')
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
                term.expect('Confirm removal? [y/N]')
                self.assertTrue(self.old.exists())
                self.assertFalse(list(self.home.glob('.agent-*-backup-*')))
                term.send(b'y\n')
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
                    rule = root / '.claude/rules/nested/.custom.md'
                    main_rule = root / 'AGENTS.md'
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
                self.assertEqual(main_rule.read_text().splitlines()[0], 'personal')
                self.assertNotIn('gwyn-space-skills:', main_rule.read_text())
                self.assertFalse(list(self.home.glob('.agent-*-backup-*')))

    def test_cli_help_invalid_and_nonterminal(self):
        self.assertEqual(self.run_script('--help').returncode, 0)
        self.assertEqual(self.run_script('--unknown').returncode, 2)
        self.assertEqual(self.run_script('--list', '--skill').returncode, 2)
        result = self.run_script()
        self.assertEqual(result.returncode, 2)
        self.assertIn('requires a terminal', result.stderr)
        self.assertFalse(self.calls())

    def test_list_is_read_only_and_has_all_sources(self):
        result = self.run_script('--list')
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
        result = self.run_script('--list')
        self.assertEqual(result.returncode, 1)
        self.assertIn('HumanLayer', result.stdout)

    def test_unrecognised_catalog_is_reported(self):
        self.env['BAD_CATALOG'] = '1'
        result = self.run_script('--list')
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
        term.expect('Continue? [y/N]')
        term.send(b'\n')
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
        term.expect('Confirm removal? [y/N]')
        preview = term.transcript.decode()
        for target in targets:
            self.assertIn(str(target), preview)
        self.assertNotIn(str(link), preview)
        self.assertIn('No new backup is created', preview)
        later = self.home / '.agent-rules-backup-LATER1'
        later.mkdir()  # never confirmed, so it must survive
        term.send(b'Y\n')
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
        for choice in [b'\n', b'n\n', b'N\n', b'DELETE\n', b'yes\n']:
            with self.subTest(choice=choice):
                term = self.terminal()
                term.send(b'\x1b[B' * 2 + b'\r')
                term.expect('Confirm removal? [y/N]')
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
