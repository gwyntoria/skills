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
import os, sys, shutil
args = sys.argv[1:]
if '-o' in args:
    with open(os.environ['FETCH_LOG'], 'a') as log:
        log.write(' '.join(args) + '\n')
    if os.environ.get('FAIL_DOWNLOAD'):
        sys.exit(22)
    source = os.environ['REMOTE_ARCHIVE' if 'codeload.github.com' in ' '.join(args) else 'REMOTE_SCRIPT']
    shutil.copyfile(source, args[args.index('-o') + 1])
else:
    if os.environ.get('FAIL_MATT'):
        sys.exit(8)
    print('<section aria-labelledby="skill-set-heading"><a href="/skills-matt-a">A</a><a href="/skills-matt-b">B</a></section>')
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
                        FETCH_LOG=str(self.root / "fetch.log"))
        for name, content in [('npx', NPX), ('curl', CURL),
                              ('codex', '#!/bin/sh\nexit 0\n'),
                              ('claude', '#!/bin/sh\nexit 0\n')]:
            self.stub(name, content)
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

    def terminal(self):
        terminal = Terminal(self.env)
        self.addCleanup(terminal.close)
        terminal.expect('Agent setup')
        terminal.expect('Item 1/5')
        return terminal

    def removal_terminal(self, types=('Skills',), agents='both'):
        term = self.terminal()
        term.send(b'\x1b[B\r')
        term.expect('Remove: choose agents')
        term.expect('Item 1/2')
        if agents == 'codex': term.send(b'\x1b[B ')
        elif agents == 'claude': term.send(b' ')
        term.send(b'\r')
        term.expect('Remove: choose content')
        term.expect('Item 1/2')
        if 'Rules' in types: term.send(b' ')
        if 'Skills' in types: term.send(b'\x1b[B ')
        term.send(b'\r')
        return term

    def inventory(self, action, *args):
        folder = self.root / 'plan'
        folder.mkdir(mode=0o700, exist_ok=True)
        command = f'REMOVAL_TEMP={shlex.quote(str(folder))}\nremoval_inventory {shlex.join([action, *map(str, args)])}'
        return self.source(command)

    def scan_entries(self, codex=True, claude=True, rules=True, skills=True):
        result = self.inventory('scan', *map(int, [codex, claude, rules, skills]))
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

    def install_skill_terminal(self):
        term = self.terminal()
        term.send(b'\r')
        term.expect('Item 1/5')
        term.send(b' \r')
        term.expect('Install skills by repository')
        term.expect('Item 1/5')
        return term

    def standalone(self):
        target = self.root / 'standalone/bin/agent-setup'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SCRIPT, target)
        return target

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
        term.expect('Item 1/5')
        term.send(b'\x1b[B \r')
        term.expect('Choose rules')
        term.expect('Item 1/4')
        return term

    def rule_agents_and_scope(self, term, agents='both', scope='project'):
        term.expect('Rules: choose agents')
        term.expect('Item 1/2')
        if agents == 'claude':
            term.send(b' ')
        elif agents == 'codex':
            term.send(b'\x1b[B ')
        term.send(b'\r')
        term.expect('Rules: choose scope')
        term.expect('Item 1/2')
        term.send(b'\x1b[B\r' if scope == 'project' else b'\r')
        term.expect('Confirm installation')
        term.expect('Item 1/2')

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
        self.assertIn('[ ] global / agent-behavior', term.transcript.decode())
        self.assertIn('[ ] project / c-project', term.transcript.decode())
        term.send(b'\x1b[B \r')
        self.rule_agents_and_scope(term)
        self.assertIn(str(nested / 'AGENTS.md'), term.transcript.decode())
        self.assertIn(str(nested / '.claude/rules/c-project.md'), term.transcript.decode())
        self.assertIn('Rule source:', term.transcript.decode())
        frame = term.transcript.decode().rsplit('\x1b[H\x1b[2J', 1)[-1]
        self.assertIn(str(nested / 'AGENTS.md'), frame)
        self.assertIn('Execution plan:', frame)
        term.send(b'b')
        term.expect('Rules: choose scope')
        term.expect('> Project')
        term.send(b'b')
        term.expect('Rules: choose agents')
        term.expect('Item 1/2')
        term.send(b'b')
        term.expect('Choose rules')
        term.expect('> [x] project / c-project')
        term.send(b'\r')
        term.expect('Rules: choose agents')
        term.expect('Item 1/2')
        self.assertIn('[x] Codex', term.transcript.decode())
        self.assertIn('[x] Claude Code', term.transcript.decode())
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
        self.assertEqual(text.count('<!-- gwyn-space-skills: c-project:start -->'), 1)
        self.assertIn('Installed from rules/project/c-project.md by agent-setup.sh', text)
        self.assertEqual((project / 'AGENTS.md').read_text(), 'root must stay unchanged\n')
        self.assertEqual((nested / '.claude/rules/c-project.md').read_bytes(),
                         (SCRIPT.parents[1] / 'rules/project/c-project.md').read_bytes())
        result = self.source('apply_rule c-project project both', cwd=nested)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((nested / 'AGENTS.md').read_text(), text)

    def test_rule_pages_q_defaults_and_scope_selection_preserved(self):
        for page in ['rules', 'agents', 'scope', 'confirm']:
            with self.subTest(page=page):
                term = self.rule_terminal(cwd=self.root)
                if page != 'rules':
                    term.send(b' \r')
                    term.expect('Rules: choose agents')
                    term.expect('Item 1/2')
                    self.assertIn('[x] Codex', term.transcript.decode())
                    self.assertIn('[x] Claude Code', term.transcript.decode())
                if page in ['scope', 'confirm']:
                    term.send(b'\r')
                    term.expect('Rules: choose scope')
                    term.expect('Item 1/2')
                if page == 'confirm':
                    term.send(b'\r')
                    term.expect('Confirm installation')
                    term.expect('Item 1/2')
                term.send(b'q')
                self.assertEqual(term.finish(), 0)
                self.assertFalse((self.home / '.codex/AGENTS.md').exists())
        term = self.rule_terminal(cwd=self.root)
        term.send(b'an\x1b[B \r')  # all, none, c-project
        self.rule_agents_and_scope(term, agents='claude')
        term.send(b'b')
        term.expect('Rules: choose scope')
        term.expect('> Project')
        term.send(b'b')
        term.expect('Rules: choose agents')
        term.expect('[ ] Codex')
        term.send(b'b')
        term.expect('Choose rules')
        term.expect('> [x] project / c-project')
        term.send(b'b')
        term.expect('Choose installation tasks')
        term.expect('> [x] Rules')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)

    def test_global_rule_ui_installs_only_selected_agent(self):
        term = self.rule_terminal(cwd=self.root)
        term.send(b' \r')  # global / agent-behavior
        self.rule_agents_and_scope(term, agents='claude', scope='global')
        term.send(b'\r')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertTrue((self.home / '.claude/CLAUDE.md').exists())
        self.assertFalse((self.home / '.codex/AGENTS.md').exists())

    def test_mixed_rule_sources_install_to_selected_scope(self):
        for scope in ['project', 'global']:
            with self.subTest(scope=scope):
                project = self.root / scope
                project.mkdir()
                term = self.rule_terminal(cwd=project)
                term.send(b' \x1b[B \r')  # select both source groups
                self.rule_agents_and_scope(term, scope=scope)
                frame = term.transcript.decode().rsplit('\x1b[H\x1b[2J', 1)[-1]
                self.assertIn('rules/global/agent-behavior.md', frame)
                self.assertIn('rules/project/c-project.md', frame)
                term.send(b'\r')
                term.expect('2 succeeded, 0 failed')
                self.assertEqual(term.finish_action(), 0)
                codex = project / 'AGENTS.md' if scope == 'project' else self.home / '.codex/AGENTS.md'
                text = codex.read_text()
                self.assertIn('Installed from rules/global/agent-behavior.md', text)
                self.assertIn('Installed from rules/project/c-project.md', text)
                self.assertEqual(text.count('agent-behavior:start'), 1)
                self.assertEqual(text.count('c-project:start'), 1)
                claude = project / '.claude/rules' if scope == 'project' else self.home / '.claude/rules'
                self.assertTrue((claude / 'c-project.md').exists())
                behavior = claude / 'agent-behavior.md' if scope == 'project' else self.home / '.claude/CLAUDE.md'
                self.assertTrue(behavior.exists())

    def test_rule_engine_preserves_old_markers_and_rejects_conflicts(self):
        project = self.root / 'project'
        project.mkdir()
        destination = project / 'AGENTS.md'
        destination.write_text('Personal\n\n<!-- gwyn-space-skills: c-project:start -->\n'
                               '<!-- Installed from instructions/project/c-project.md by agent-install-rule.sh. -->\n'
                               'old body\n<!-- gwyn-space-skills: c-project:end -->\n')
        result = self.source('apply_rule c-project project codex', cwd=project)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = destination.read_text()
        self.assertIn('Personal', text)
        self.assertNotIn('old body', text)
        self.assertEqual(text.count('c-project:start'), 1)
        destination.write_text('Personal\n<!-- gwyn-space-skills: c-project:start -->\nkeep\n')
        before = destination.read_bytes()
        result = self.source('apply_rule c-project project codex', cwd=project)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unbalanced markers', result.stderr)
        self.assertEqual(destination.read_bytes(), before)

    def test_legacy_global_copy_migrates_with_restore_backup(self):
        destination = self.home / '.codex/AGENTS.md'
        destination.parent.mkdir()
        original = (SCRIPT.parents[1] / 'rules/global/agent-behavior.md').read_bytes()
        destination.write_bytes(original)
        result = self.source('apply_rule agent-behavior global codex')
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
        self.assertIn('4 succeeded, 0 failed', result.stdout)
        self.assertTrue((self.home / '.codex/AGENTS.md').exists())
        self.assertTrue((self.home / '.claude/CLAUDE.md').exists())
        self.assertTrue((self.home / '.claude/statusline.sh').exists())
        self.assertEqual(len((self.root / 'fetch.log').read_text().splitlines()), 1)
        self.assertEqual(list(scratch.iterdir()), [])

    def test_local_scope_wins_and_missing_scope_fetches_without_merging(self):
        self.remote_bundle()
        script = self.standalone()
        local = script.parent.parent / 'rules/project'
        local.mkdir(parents=True)
        (local / 'local-only.md').write_text('# Local only\nlocal content\n')
        result = self.source('RULE_SCOPE=project\nload_rule_catalog\nprintf "%s\\n" "${RULE_NAMES_PROJECT[@]}"', script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('local-only', result.stdout)
        self.assertNotIn('c-project', result.stdout)
        self.assertFalse((self.root / 'fetch.log').exists())
        result = self.source('RULE_SCOPE=global\nload_rule_catalog\nprintf "%s\\n" "${RULE_NAMES_GLOBAL[@]}"', script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('agent-behavior', result.stdout)
        self.assertEqual((local / 'local-only.md').read_text(), '# Local only\nlocal content\n')
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
        term.send(b'\x1b[B \r')
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
        self.assertEqual(len((self.root / 'fetch.log').read_text().splitlines()), 1)

    def test_remote_failure_preserves_configs_and_continues_tasks(self):
        script = self.standalone()
        self.env['FAIL_DOWNLOAD'] = '1'
        target = self.home / '.codex/AGENTS.md'
        target.parent.mkdir()
        target.write_text('keep existing\n')
        result = subprocess.run(['bash', str(script), '--agent'], env=self.env,
                                capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('2 succeeded, 2 failed', result.stdout)
        self.assertEqual(target.read_text(), 'keep existing\n')
        self.assertFalse((self.home / '.claude/statusline.sh').exists())

    def test_script_symlink_uses_real_local_resources(self):
        link = self.root / 'linked-command'
        link.symlink_to(SCRIPT)
        result = self.source('apply_rule c-project project codex', link, cwd=self.root)
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
        term.expect('used on next launch')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertEqual(installed.read_bytes(), remote.read_bytes())
        self.assertNotIn('new version\r\n', term.transcript.decode())
        result = subprocess.run([str(installed)], capture_output=True, text=True)
        self.assertEqual(result.stdout, 'new version\n')

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
        term.expect('Item 1/5')
        term.send(b'\x1b[B' * 4 + b' \r')
        term.expect('Continue? [y/N]')
        term.send(b'y\n')
        term.expect('0 succeeded, 1 failed')
        term.return_home()
        self.assertEqual(settings.read_text(), 'invalid json')
        term.send(b'\r')
        term.expect('Choose installation tasks')
        term.expect('Item 1/5')
        frame = term.transcript.decode().rsplit('\x1b[H\x1b[2J', 1)[-1]
        self.assertNotIn('[x]', frame)
        term.send(b'\x1b[B' * 2 + b' \r')
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
        term.expect('Item 1/5')
        term.send(b' \r')
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
        term.expect('Item 1/5')
        term.send(b'\x1b[B \r')
        term.expect('global rule catalog unavailable')
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
            term.expect('Item 1/5')
            term.send(b'\x1b[B' * 4 + b' \r')
            term.expect('Continue? [y/N]')
            term.send(b'y\n')
            term.expect('1 succeeded, 0 failed')
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
        term.send(b' \x1b[B\x1b[B b')
        term.expect('Install skills by repository')
        term.expect('[-] tw93/waza')
        term.expect('(2/3)')
        term.send(b'b')
        term.expect('Choose installation tasks')
        term.expect('Item 1/5')
        term.send(b'\r')
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
        calls = [c for c in self.calls() if '--list' not in c]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][calls[0].index('--skill') + 1:calls[0].index('--agent')], ['waza-first', 'waza-last'])
        self.assertEqual(calls[0][calls[0].index('--agent') + 1:], ['claude-code', '--global', '--yes'])

    def test_repository_select_all_none_partial_toggle_and_q(self):
        term = self.install_skill_terminal()
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
        term = self.install_skill_terminal()
        term.send(b'\r')
        term.expect('Repository: tw93/waza')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertTrue(all('--list' in call for call in self.calls()))

    def test_repository_whole_selection_reuses_catalog_across_tasks(self):
        term = self.install_skill_terminal()
        for run in range(2):
            term.send(b' \x1b[A\r')  # all Waza, then Continue
            term.expect('Install skills for')
            term.expect('Item 1/2')
            term.send(b'\r')
            term.expect('Continue? [y/N]')
            term.send(b'y\n')
            term.expect('1 succeeded, 0 failed')
            term.return_home()
            if run == 0:
                term.send(b'\r')
                term.expect('Item 1/5')
                term.send(b' \r')
                term.expect('[ ] tw93/waza')
        self.assertEqual(term.exit_home(), 0)
        self.assertEqual(sum('--list' in call for call in self.calls()), 2)

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
        result = self.inventory('remove')
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
        result = self.inventory('remove')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_bytes(), personal + b + b'last\r\n')
        self.assertFalse(custom.exists())
        self.assertEqual(kept.read_text(), 'keep')
        backup, = self.home.glob('.agent-rules-backup-*/removal.tar')
        with tarfile.open(backup) as tar:
            self.assertIn('.codex/AGENTS.md', tar.getnames())
            self.assertIn('.claude/rules/nested/.custom.md', tar.getnames())

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
        result = self.inventory('remove')
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
        result = self.inventory('remove')
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
        result = self.inventory('remove')
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
        term.expect('Type DELETE')
        self.assertEqual(term.transcript.count(b'Type DELETE'), 1)
        self.assertIn(b'\x1b[31m', term.transcript)
        term.send(b'DELETE\n')
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
        term.expect('Remove: choose content')
        term.expect('Item 2/2')
        term.send(b'\r')
        term.expect('[-] owner/repo')
        term.send(b'\x1b[A\r')
        term.expect('WARNING: Claude link will be kept')
        term.expect('Type DELETE')
        term.send(b'DELETE\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish_action(), 0)
        self.assertTrue(link.is_symlink())
        self.assertFalse(self.old.exists())
        self.assertTrue((self.home / '.agents/skills/other').exists())

    def test_removal_menu_defaults_back_cancel_q_and_fresh_scan(self):
        term = self.terminal()
        term.send(b'\x1b[B\r')
        term.expect('Remove: choose agents')
        term.expect('Item 1/2')
        term.send(b' \x1b[Bb')  # Claude only; return home
        term.expect('Item 2/5')
        term.send(b'\r')
        term.expect('> [x] Claude Code')
        term.send(b'\r')
        term.expect('Remove: choose content')
        term.expect('Item 1/2')
        frame = re.sub(r'\x1b\[[0-9;]*m', '', term.transcript.decode()).rsplit('\x1b[H\x1b[2J', 1)[-1]
        self.assertIn('[ ] Rules', frame)
        self.assertIn('[ ] Skills', frame)
        term.send(b'\r')
        term.expect('No content selected')
        term.return_home()
        # Add content after the first action. A new removal must see it.
        custom = self.home / '.claude/rules/new.md'
        custom.parent.mkdir(parents=True)
        custom.write_text('new rule')
        term.send(b'\x1b[B\r')
        term.expect('Remove: choose agents')
        term.expect('Item 1/2')
        term.send(b'\r')
        term.expect('Remove: choose content')
        term.expect('Item 1/2')
        term.send(b' \r')
        term.expect('new.md [file]')
        term.send(b'q')
        self.assertEqual(term.finish(), 0)
        self.assertTrue(custom.exists())

    def test_removal_ui_changed_content_stops_and_session_continues(self):
        term = self.removal_terminal()
        term.expect('Remove skills by repository')
        term.expect('Item 1/2')
        term.send(b' \x1b[A\r')
        term.expect('Type DELETE')
        self.old.write_text('edited during confirmation')
        term.send(b'DELETE\n')
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
        term.expect('Type DELETE')
        term.send(b'DELETE\n')
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
        self.assertIn('[ ] Claude / rules/custom.md', term.transcript.decode())
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
        result = self.inventory('remove')
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
        term.expect('Type DELETE')
        term.send(b'b\n')
        term.expect('Remove skills by repository')
        term.expect('[x] Unknown / local')
        term.expect('Item 2/2')
        term.send(b'\r')
        term.expect('Type DELETE')
        term.send(b'q\n')
        self.assertEqual(term.finish(), 0)
        self.assertTrue(self.old.exists())
        self.assertFalse(list(self.home.glob('.agent-skills-backup-*')))

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
        for name in ['Waza', 'Kami', 'Matt Pocock', 'HumanLayer', 'show-me']:
            self.assertIn(name, result.stdout)
        self.assertTrue(all('--list' in call for call in self.calls()))
        self.assertEqual(list(self.home.rglob('SKILL.md')), [self.old])

    def test_repository_batch_failure_continues_to_other_sources(self):
        self.env['FAIL_SKILL'] = 'fail-middle'
        result = self.run_script('--agent', '--skill')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        installed = [c[c.index('--skill') + 1:c.index('--agent')]
                     for c in self.calls() if '--list' not in c]
        self.assertEqual(installed, [['waza-first', 'fail-middle', 'waza-last'],
                                    ['kami'], ['matt-a', 'matt-b'], ['show-me']])
        self.assertIn('7 succeeded, 1 failed', result.stdout)
        self.assertIn('Waza: waza-first fail-middle waza-last (exit 9)', result.stdout)
        self.assertEqual(self.old.read_text(), 'keep me')
        self.assertTrue((self.home / '.claude/settings.json').is_file())
        self.assertTrue((self.home / '.codex/AGENTS.md').is_file())

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
        term.expect('Item 1/5')
        term.send(b'\r')
        self.assertEqual(term.finish_action(), 0)
        self.assertFalse(self.calls())




    def test_terminal_all_none_and_confirmation_cancel(self):
        term = self.terminal()
        term.send(b'\r')
        term.expect('Item 1/5')
        term.send(b'an\x1b[B\x1b[B \r')  # all, none, then just Codex
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
        term.expect('Type DELETE')
        preview = term.transcript.decode()
        for target in targets:
            self.assertIn(str(target), preview)
        self.assertNotIn(str(link), preview)
        self.assertIn('No new backup is created', preview)
        later = self.home / '.agent-rules-backup-LATER1'
        later.mkdir()  # never confirmed, so it must survive
        term.send(b'DELETE\n')
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
        term = self.terminal()
        term.send(b'\x1b[B' * 2 + b'\r')
        term.expect('Type DELETE')
        term.send(b'\n')
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
