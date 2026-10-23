#!/usr/bin/env python3
"""Isolated installer regression checks; Python 3 standard library only."""

import json
import os
from pathlib import Path
import pty
import select
import shlex
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
import os, sys
if os.environ.get('FAIL_MATT'):
    sys.exit(8)
print('<section aria-labelledby="skill-set-heading"><a href="/skills-matt-a">A</a><a href="/skills-matt-b">B</a></section>')
'''


class Terminal:
    def __init__(self, env):
        self.master, slave = pty.openpty()
        self.process = subprocess.Popen(['bash', str(SCRIPT)], stdin=slave,
                                        stdout=slave, stderr=slave, env=env)
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
                        PATH=f'{self.bin}:{os.environ["PATH"]}', CALL_LOG=str(self.log))
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

    def source(self, command):
        return subprocess.run(['bash', '-c', f'source {shlex.quote(str(SCRIPT))}\n{command}'],
                              env=self.env, capture_output=True, text=True, timeout=20)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def terminal(self):
        terminal = Terminal(self.env)
        self.addCleanup(terminal.close)
        terminal.expect('Agent setup')
        terminal.expect('Item 1/4')
        return terminal

    def removal_terminal(self, kind='skills', agents='both', rules=False):
        term = self.terminal()
        term.send(b'\x1b[B' * (1 if kind == 'skills' else 2) + b'\r')
        term.expect(f'Remove global {kind}: choose agents')
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
        ordered = ['Skills', 'Global instructions (both agents)', 'Codex CLI',
                   'Claude Code CLI', 'Claude statusline']
        positions = [task_screen.index(name) for name in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('b: back | q: exit', task_screen)
        term.send(b' \x1b[B\x1b[B b')  # Skills + Codex, Back while on Codex
        term.expect('Agent setup')
        term.expect('Item 1/4')
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
        installed = self.source('install_instructions')
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
        installed = self.source('install_instructions')
        self.assertEqual(installed.returncode, 0, installed.stderr)
        original = path.read_bytes()
        self.stub('cp', '#!/bin/sh\nexit 24\n')
        result = self.source('run_item remove remove_global_instructions\nprint_summary')
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
                term.expect(f'Item {offset + 1}/4')
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
                installed = self.source('install_instructions')
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
        installed = self.source('install_instructions')
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
        installed = self.source('install_instructions')
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
        installed = self.source('install_instructions')
        self.assertEqual(installed.returncode, 0, installed.stderr)
        rules = self.home / '.claude/rules'
        rules.mkdir()
        (rules / 'custom.md').write_text('custom')
        claude = self.home / '.claude/CLAUDE.md'
        original = claude.read_bytes()
        self.stub('tar', '#!/bin/sh\nexit 23\n')
        result = self.source('REMOVE_CODEX=0\nREMOVE_CLAUDE_RULES=1\nrun_item remove remove_global_instructions\nprint_summary')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Rules backup failed; nothing removed', result.stderr)
        self.assertEqual(claude.read_bytes(), original)
        self.assertEqual((rules / 'custom.md').read_text(), 'custom')

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
