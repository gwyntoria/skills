#!/usr/bin/env python3
"""Isolated installer regression checks; Python 3 standard library only."""

import json
import os
from pathlib import Path
import pty
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
    def __init__(self, env, script=SCRIPT, cwd=None):
        self.master, slave = pty.openpty()
        self.process = subprocess.Popen(['bash', str(script)], stdin=slave,
                                        stdout=slave, stderr=slave, env=env, cwd=cwd)
        os.close(slave)
        self.pending = b''
        self.transcript = b''

    def expect(self, text):
        wanted = text.encode()
        deadline = time.monotonic() + 10
        while wanted not in self.pending:
            if time.monotonic() > deadline:
                raise AssertionError(f'Missing {text!r}: {self.transcript.decode(errors="replace")}')
            if select.select([self.master], [], [], 0.1)[0]:
                try:
                    data = os.read(self.master, 65536)
                except OSError:
                    data = b''
                if not data:
                    raise AssertionError(f'Terminal exited before {text!r}: {self.transcript!r}')
                self.pending += data
                self.transcript += data
        self.pending = self.pending.split(wanted, 1)[1]

    def send(self, data):
        os.write(self.master, data)

    def finish(self):
        return self.process.wait(timeout=10)

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
        terminal.expect('Item 1/6')
        return terminal

    def removal_terminal(self, kind='skills', agents='both', rules=False):
        term = self.terminal()
        term.send(b'\x1b[B' * (1 if kind == 'skills' else 2) + b'\r')
        term.expect(f'Remove global {"rules" if kind == "instructions" else kind}: choose agents')
        term.expect('Item 1/2')
        if agents == 'codex':
            term.send(b'\x1b[B ')
        elif agents == 'claude':
            term.send(b' ')
        term.send(b'\r')
        if kind == 'instructions' and agents != 'codex':
            term.expect('Also remove all Claude rules directory contents?')
            term.expect('Item 1/2')
            term.send(b'\x1b[B\r' if rules else b'\r')
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
        term.expect('Item 1/6')
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
        self.assertEqual(term.finish(), 0)
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
        self.assertEqual(term.finish(), 0)
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
                self.assertEqual(term.finish(), 0)
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
        self.assertEqual(term.finish(), 0)
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
        term.expect('Item 1/6')
        term.send(b'\x1b[B' * 4 + b'\r')
        term.expect('used on next launch')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish(), 0)
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
        self.assertEqual(term.finish(), 0)
        self.assertFalse(self.calls())

    def test_terminal_back_preserves_every_page_and_reuses_catalog(self):
        term = self.terminal()
        home_screen = term.transcript.decode()
        self.assertIn('Up/Down: move | Enter: continue | q: exit', home_screen)
        self.assertIn('Install / Update', home_screen)
        for unused in ['Space: select', 'a: all', 'n: none', 'b: back']:
            self.assertNotIn(unused, home_screen)
        term.send(b'\r')
        term.expect('Item 1/5')
        task_screen = term.transcript.decode().split('Choose installation tasks')[-1]
        ordered = ['Skills', 'Rules', 'Codex CLI',
                   'Claude Code CLI', 'Claude statusline']
        positions = [task_screen.index(name) for name in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('b: back | q: exit', task_screen)
        term.send(b' \x1b[B\x1b[B b')  # Skills + Codex, Back while on Codex
        term.expect('Agent setup')
        term.expect('Item 1/6')
        term.send(b'\r')
        term.expect('> [x] Codex CLI')
        term.expect('Item 3/5')
        term.send(b'\r')
        term.expect('Item 1/7')
        term.send(b' \x1b[B\x1b[B b')  # two skills, Back while on third
        term.expect('> [x] Codex CLI')
        term.expect('Item 3/5')
        term.send(b'\r')
        term.expect('[x] Waza / waza-first')
        term.expect('> [x] Waza / waza-last')
        term.expect('Item 3/7')
        term.send(b'\r')
        term.expect('Item 1/2')
        term.send(b' \x1b[Bb')  # deselect Codex; Back while on Claude
        term.expect('> [x] Waza / waza-last')
        term.expect('Item 3/7')
        term.send(b'\r')
        term.expect('[ ] Codex')
        term.expect('> [x] Claude Code')
        term.expect('Item 2/2')
        term.send(b'\r')
        term.expect('Continue? [y/N]')
        term.send(b'y\n')
        term.expect('2 succeeded, 0 failed')
        self.assertEqual(term.finish(), 0)
        calls = self.calls()
        self.assertEqual(sum('--list' in call for call in calls), 2)
        installs = [call for call in calls if '--list' not in call]
        self.assertEqual(len(installs), 1)
        self.assertEqual(installs[0][installs[0].index('--skill') + 1:installs[0].index('--agent')],
                         ['waza-first', 'waza-last'])
        self.assertEqual(installs[0][installs[0].index('--agent') + 1:],
                         ['claude-code', '--global', '--yes'])

    def test_terminal_q_exits_from_each_subpage(self):
        for page in ['tasks', 'skills', 'targets']:
            with self.subTest(page=page):
                term = self.terminal()
                term.send(b'\r')
                term.expect('Item 1/5')
                if page != 'tasks':
                    term.send(b' \r')
                    term.expect('Item 1/7')
                if page == 'targets':
                    term.send(b' \r')
                    term.expect('Item 1/2')
                term.send(b'q')
                self.assertEqual(term.finish(), 0)
                self.assertTrue(all('--list' in call for call in self.calls()))
                self.assertFalse((self.home / '.claude').exists())

    def test_terminal_select_skill_and_only_claude(self):
        term = self.terminal()
        term.send(b'\r')
        term.expect('Item 1/5')
        term.send(b' \r')  # Skills is the first task
        term.expect('Choose skills by source')
        term.expect('Item 1/7')
        term.send(b'\x1b[B\x1b[B \r')  # Waza's third skill only
        term.expect('Install skills for')
        term.expect('Item 1/2')
        term.send(b' \r')  # deselect Codex; Claude remains selected
        term.expect('Continue? [y/N]')
        term.send(b'y\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish(), 0)
        calls = [c for c in self.calls() if '--list' not in c]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][calls[0].index('--skill') + 1], 'waza-last')
        self.assertEqual(calls[0][calls[0].index('--agent') + 1:], ['claude-code', '--global', '--yes'])

    def test_terminal_all_none_and_confirmation_cancel(self):
        term = self.terminal()
        term.send(b'\r')
        term.expect('Item 1/5')
        term.send(b'an\x1b[B\x1b[B \r')  # all, none, then just Codex
        term.expect('Execution plan:')
        term.expect('Codex CLI')
        term.expect('Continue? [y/N]')
        term.send(b'\n')
        self.assertEqual(term.finish(), 0)
        self.assertFalse(self.calls())
        self.assertFalse((self.home / '.claude').exists())

    def test_terminal_delete_cancellation_and_q(self):
        term = self.removal_terminal()
        term.expect('Type DELETE')
        term.send(b'no\n')
        self.assertEqual(term.finish(), 0)
        self.assertTrue(self.old.exists())
        term = self.terminal()
        term.send(b'q')
        self.assertEqual(term.finish(), 0)

    def test_global_instruction_removal_preserves_content_and_can_restore(self):
        paths = [self.home / '.codex/AGENTS.md', self.home / '.claude/CLAUDE.md']
        personal = 'Personal instructions.\n\n<!-- gwyn-space-skills: other:start -->\nKeep other rule.\n<!-- gwyn-space-skills: other:end -->\n'
        for path in paths:
            path.parent.mkdir(parents=True)
            path.write_text(personal)
        installed = self.source('install_global_rules')
        self.assertEqual(installed.returncode, 0, installed.stderr)
        originals = [path.read_bytes() for path in paths]
        term = self.removal_terminal('instructions')
        term.expect('Type DELETE')
        term.send(b'DELETE\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish(), 0)
        for path in paths:
            text = path.read_text()
            self.assertIn('Personal instructions.', text)
            self.assertIn('Keep other rule.', text)
            self.assertNotIn('gwyn-space-skills: agent-behavior:start', text)
        backup, = self.home.glob('.agent-rules-backup-*')
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        restores = [line.removeprefix('Restore: ') for line in term.transcript.decode().splitlines()
                    if line.startswith('Restore: ')]
        self.assertEqual(len(restores), 2)
        for command in restores:
            subprocess.run(['bash', '-c', command], check=True)
        self.assertEqual([path.read_bytes() for path in paths], originals)
        self.assertEqual(self.old.read_text(), 'keep me')

    def test_global_instruction_removal_cancel_and_backup_failure(self):
        path = self.home / '.codex/AGENTS.md'
        path.parent.mkdir()
        path.write_text('Personal instructions.\n')
        term = self.removal_terminal('instructions')
        term.expect('Type DELETE')
        term.send(b'\n')
        self.assertEqual(term.finish(), 0)
        self.assertFalse(list(self.home.glob('.agent-rules-backup-*')))
        self.assertEqual(path.read_text(), 'Personal instructions.\n')
        installed = self.source('install_global_rules')
        self.assertEqual(installed.returncode, 0, installed.stderr)
        original = path.read_bytes()
        self.stub('cp', '#!/bin/sh\nexit 24\n')
        result = self.source('run_item remove remove_global_rules\nprint_summary')
        self.assertEqual(result.returncode, 1)
        self.assertIn('exit 24', result.stdout)
        self.assertEqual(path.read_bytes(), original)

    def test_removal_backup_restore_and_preservation(self):
        system = self.home / '.codex/skills/.system/keep'
        system.parent.mkdir(parents=True)
        system.write_text('system')
        shared_system = self.home / '.agents/skills/.system/keep'
        shared_system.parent.mkdir()
        shared_system.write_text('shared system')
        claude = self.home / '.claude/skills'
        claude.mkdir(parents=True)
        (claude / 'existing').symlink_to(self.old.parent)
        (claude / 'unrelated').symlink_to(system.parent)
        (claude / 'private').mkdir()
        (self.home / '.agents/.skill-lock.json').write_text('{"skills":{}}')
        term = self.removal_terminal()
        term.expect('Type DELETE')
        notice = 'Remove skills for the selected agents; preserve .system entries.'
        self.assertNotIn(notice, term.transcript.decode())
        term.send(b'DELETE\n')
        term.expect(notice)
        term.expect('1 succeeded, 0 failed')
        transcript = term.transcript.decode()
        self.assertLess(transcript.index('Restore:'), transcript.index(notice))
        self.assertEqual(term.finish(), 0)
        self.assertFalse(self.old.exists())
        self.assertFalse((claude / 'existing').is_symlink())
        self.assertFalse((claude / 'unrelated').is_symlink())
        self.assertFalse((claude / 'private').exists())
        self.assertEqual(system.read_text(), 'system')
        self.assertEqual(shared_system.read_text(), 'shared system')
        backup, = self.home.glob('.agent-skills-backup-*/skills.tar')
        self.assertEqual(backup.parent.stat().st_mode & 0o777, 0o700)
        restore = next(line for line in term.transcript.decode().splitlines() if line.startswith('Restore: '))
        subprocess.run(['bash', '-c', restore.removeprefix('Restore: ')], check=True)
        self.assertEqual(self.old.read_text(), 'keep me')
        self.assertTrue((claude / 'existing').is_symlink())
        self.assertTrue(backup.exists())

    def test_codex_skill_removal_warns_red_and_keeps_claude_links(self):
        claude = self.home / '.claude/skills'
        claude.mkdir(parents=True)
        link = claude / 'existing'
        link.symlink_to(self.old.parent)
        external = self.root / 'outside'
        external.mkdir()
        (claude / 'external').symlink_to(external)
        term = self.removal_terminal(agents='codex')
        term.expect('Type DELETE')
        preview = term.transcript.decode()
        self.assertIn('\x1b[31mWARNING:', preview)
        self.assertIn(f'{link} -> {self.old.parent}', preview)
        self.assertIn('Claude links will be kept', preview)
        term.send(b'DELETE\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish(), 0)
        self.assertFalse(self.old.exists())
        self.assertTrue(link.is_symlink())
        self.assertFalse(link.exists())
        self.assertTrue((claude / 'external').is_symlink())
        self.assertTrue(external.is_dir())

    def test_claude_skill_removal_keeps_shared_source_and_external_targets(self):
        claude = self.home / '.claude/skills'
        claude.mkdir(parents=True)
        (claude / 'existing').symlink_to(self.old.parent)
        (claude / 'private').mkdir()
        (claude / '.system').mkdir()
        (claude / '.system/keep').write_text('system')
        lock = self.home / '.agents/.skill-lock.json'
        lock.write_text('keep lock')
        term = self.removal_terminal(agents='claude')
        term.expect('Type DELETE')
        self.assertNotIn('\x1b[31mWARNING:', term.transcript.decode())
        term.send(b'DELETE\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish(), 0)
        self.assertFalse((claude / 'existing').is_symlink())
        self.assertFalse((claude / 'private').exists())
        self.assertEqual((claude / '.system/keep').read_text(), 'system')
        self.assertEqual(lock.read_text(), 'keep lock')
        self.assertEqual(self.old.read_text(), 'keep me')

    def test_removal_menus_back_q_and_selection_preservation(self):
        for offset, kind in [(1, 'skills'), (2, 'instructions')]:
            with self.subTest(kind=kind):
                term = self.terminal()
                term.send(b'\x1b[B' * offset + b'\r')
                term.expect('Item 1/2')
                term.send(b' \x1b[Bb')  # keep only Claude; cursor on Claude
                term.expect('Agent setup')
                term.expect(f'Item {offset + 1}/6')
                term.send(b'\r')
                term.expect('[ ] Codex')
                term.expect('> [x] Claude Code')
                term.expect('Item 2/2')
                if kind == 'instructions':
                    term.send(b'\r')
                    term.expect('Also remove all Claude rules directory contents?')
                    term.expect('Item 1/2')
                    term.send(b'b')
                    term.expect('> [x] Claude Code')
                    term.expect('Item 2/2')
                term.send(b'q')
                self.assertEqual(term.finish(), 0)
                self.assertEqual(self.old.read_text(), 'keep me')
                self.assertFalse(list(self.home.glob('.agent-*-backup-*')))

    def test_instruction_agent_isolation_and_default_keep_rules(self):
        for agent in ['codex', 'claude']:
            with self.subTest(agent=agent):
                installed = self.source('install_global_rules')
                self.assertEqual(installed.returncode, 0, installed.stderr)
                codex = self.home / '.codex/AGENTS.md'
                claude = self.home / '.claude/CLAUDE.md'
                originals = {path: path.read_bytes() for path in [codex, claude]}
                rules = self.home / '.claude/rules'
                rules.mkdir(exist_ok=True)
                (rules / 'custom.md').write_text('custom rule')
                term = self.removal_terminal('instructions', agents=agent)
                term.expect('Type DELETE')
                term.send(b'DELETE\n')
                term.expect('1 succeeded, 0 failed')
                self.assertEqual(term.finish(), 0)
                selected, other = (codex, claude) if agent == 'codex' else (claude, codex)
                self.assertNotIn('gwyn-space-skills: agent-behavior:start', selected.read_text())
                self.assertEqual(other.read_bytes(), originals[other])
                self.assertEqual((rules / 'custom.md').read_text(), 'custom rule')

    def test_claude_rules_clear_and_tar_restore_do_not_follow_links(self):
        installed = self.source('install_global_rules')
        self.assertEqual(installed.returncode, 0, installed.stderr)
        rules = self.home / '.claude/rules'
        rules.mkdir()
        (rules / 'custom.md').write_text('custom')
        (rules / '.hidden').write_text('hidden')
        external = self.root / 'outside-rule'
        external.write_text('external')
        (rules / 'external.md').symlink_to(external)
        codex = self.home / '.codex/AGENTS.md'
        codex_original = codex.read_bytes()
        term = self.removal_terminal('instructions', agents='claude', rules=True)
        term.expect('Type DELETE')
        self.assertIn('Claude rules removal targets:', term.transcript.decode())
        term.send(b'DELETE\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish(), 0)
        self.assertEqual(list(rules.iterdir()), [])
        self.assertEqual(external.read_text(), 'external')
        self.assertEqual(codex.read_bytes(), codex_original)
        restores = [line.removeprefix('Restore: ') for line in term.transcript.decode().splitlines()
                    if line.startswith('Restore: ')]
        self.assertEqual(len(restores), 2)
        for command in restores:
            subprocess.run(['bash', '-c', command], check=True)
        self.assertEqual((rules / 'custom.md').read_text(), 'custom')
        self.assertEqual((rules / '.hidden').read_text(), 'hidden')
        self.assertTrue((rules / 'external.md').is_symlink())

    def test_claude_skills_directory_link_unlinks_only_and_restores(self):
        claude = self.home / '.claude'
        claude.mkdir()
        link = claude / 'skills'
        link.symlink_to(self.old.parent.parent)
        term = self.removal_terminal(agents='claude')
        term.expect('Type DELETE')
        term.send(b'DELETE\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish(), 0)
        self.assertFalse(link.is_symlink())
        self.assertEqual(self.old.read_text(), 'keep me')
        restore = next(line.removeprefix('Restore: ') for line in term.transcript.decode().splitlines()
                       if line.startswith('Restore: '))
        subprocess.run(['bash', '-c', restore], check=True)
        self.assertTrue(link.is_symlink())

    def test_claude_rules_directory_link_does_not_clear_external_target(self):
        installed = self.source('install_global_rules')
        self.assertEqual(installed.returncode, 0, installed.stderr)
        outside = self.root / 'outside-rules'
        outside.mkdir()
        (outside / 'keep.md').write_text('keep')
        rules = self.home / '.claude/rules'
        rules.symlink_to(outside)
        term = self.removal_terminal('instructions', agents='claude', rules=True)
        term.expect('Type DELETE')
        term.send(b'DELETE\n')
        term.expect('1 succeeded, 0 failed')
        self.assertEqual(term.finish(), 0)
        self.assertFalse(rules.is_symlink())
        self.assertEqual((outside / 'keep.md').read_text(), 'keep')
        restores = [line.removeprefix('Restore: ') for line in term.transcript.decode().splitlines()
                    if line.startswith('Restore: ')]
        for command in restores:
            subprocess.run(['bash', '-c', command], check=True)
        self.assertTrue(rules.is_symlink())

    def test_rules_backup_failure_prevents_instruction_removal(self):
        installed = self.source('install_global_rules')
        self.assertEqual(installed.returncode, 0, installed.stderr)
        rules = self.home / '.claude/rules'
        rules.mkdir()
        (rules / 'custom.md').write_text('custom')
        claude = self.home / '.claude/CLAUDE.md'
        original = claude.read_bytes()
        self.stub('tar', '#!/bin/sh\nexit 23\n')
        result = self.source('REMOVE_CODEX=0\nREMOVE_CLAUDE_RULES=1\nrun_item remove remove_global_rules\nprint_summary')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Rules backup failed; nothing removed', result.stderr)
        self.assertEqual(claude.read_bytes(), original)
        self.assertEqual((rules / 'custom.md').read_text(), 'custom')

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
        term.send(b'\x1b[B' * 3 + b'\r')
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
        self.assertEqual(term.finish(), 0)
        for target in targets:
            self.assertFalse(target.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(later.exists())
        self.assertTrue(link.is_symlink())
        self.assertEqual((external / 'keep').read_text(), 'outside')
        self.assertEqual(self.old.read_text(), 'keep me')

    def test_remove_all_backups_cancel_and_empty(self):
        term = self.terminal()
        term.send(b'\x1b[B' * 3 + b'\r')
        term.expect('No setup backups found.')
        self.assertEqual(term.finish(), 0)
        target = self.home / '.agent-skills-backup-ABC123'
        target.mkdir()
        term = self.terminal()
        term.send(b'\x1b[B' * 3 + b'\r')
        term.expect('Type DELETE')
        term.send(b'\n')
        self.assertEqual(term.finish(), 0)
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

    def test_backup_failure_prevents_deletion(self):
        self.stub('tar', '#!/bin/sh\nexit 23\n')
        result = self.source('remove_installed_agent_skills')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Backup failed; nothing removed', result.stderr)
        self.assertEqual(self.old.read_text(), 'keep me')

    def test_removal_rejects_symlinked_parent_and_handles_empty_home(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'keep').write_text('external')
        (self.home / '.claude').symlink_to(outside)
        result = self.source('remove_installed_agent_skills')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Refusing symlinked directory', result.stderr)
        self.assertTrue(self.old.exists())
        self.assertEqual((outside / 'keep').read_text(), 'external')
        empty = self.root / 'empty'
        empty.mkdir()
        self.env['HOME'] = str(empty)
        result = self.source('remove_installed_agent_skills')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('No managed global skills', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
