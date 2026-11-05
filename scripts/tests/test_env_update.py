#!/usr/bin/env python3
"""Run the updater with an isolated PATH/HOME; never invoke installed agents."""
import json
import os
import errno
import fcntl
import pty
import select
import struct
import termios
import time
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'env-update.sh'
STUB = r'''
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(json.dumps([name] + args) + '\n')
if args == ['--help']:
    if name != os.environ.get('NO_UPDATE_COMMAND'):
        if name == 'claude':
            print('Commands:\n  update|upgrade  Update application')
        elif name == 'pi':
            print('Commands:\n  pi update  Update application')
        else:
            print('Commands:\n  update  Update application')
elif args == ['update', '--help']:
    flags = []
    if not os.environ.get('NO_SELF_FLAG'): flags.append('--self')
    if not os.environ.get('NO_EXTENSIONS_FLAG'): flags.append('--extensions')
    print('Usage: pi update ' + ' '.join(flags))
elif name == 'claude' and args == ['plugin', 'marketplace', 'update', '--help']:
    print('Usage: claude plugin marketplace update [options] [name]')
elif name == 'claude' and args == ['plugin', 'list', '--help']:
    print('Usage: claude plugin list [--json]')
elif name == 'claude' and args == ['plugin', 'list', '--json']:
    if os.environ.get('FAIL_LIST'): sys.exit(42)
    print(os.environ.get('CLAUDE_PLUGINS', '[]'))
else:
    fail = json.loads(os.environ.get('FAIL_CALL', '[]'))
    if [name] + args == fail:
        sys.exit(42)
    if os.environ.get('CHECK_TTY') and (name == 'hermes' or (name == 'claude' and args[:2] == ['plugin', 'update'])):
        if not all(os.isatty(fd) for fd in (0, 1, 2)):
            sys.exit(43)
        print('fixture: terminal interaction preserved')
    print('fixture: ' + name + ' ' + ' '.join(args))
'''


class EnvUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='env update ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'home'
        self.bin = self.root / 'bin'
        self.home.mkdir()
        self.bin.mkdir()
        (self.bin / 'python3').symlink_to(sys.executable)
        self.log = self.root / 'calls.jsonl'
        self.env = {
            'HOME': str(self.home), 'PATH': str(self.bin), 'TERM': 'dumb',
            'CALL_LOG': str(self.log), 'LC_ALL': 'C',
        }
        for cmd in ('date',):
            (self.bin / cmd).symlink_to(shutil.which(cmd))

    def install(self, name, directory=None):
        path = (directory or self.bin) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!' + sys.executable + '\n' + STUB)
        path.chmod(0o755)
        if directory is not None:
            (self.bin / name).symlink_to(path)
        return path

    def run_script(self, *args):
        result = subprocess.run(
            ['/bin/bash', str(SCRIPT), *args], env=self.env, cwd=self.home,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10,
        )
        self.output = result.stdout
        self.calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return result

    def updates(self):
        return [call for call in self.calls
                if '--help' not in call and call[1:] not in
                (['plugin', 'list', '--json'],)]

    def test_no_agents_skips_group_and_continues(self):
        self.install('npx')
        self.install('brew')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, self.output)
        self.assertEqual(self.updates(), [['npx', 'skills', 'update', '-g', '-y'], ['brew', 'upgrade', '--no-ask']])
        self.assertIn('Succeeded: 2\nFailed: 0\nSkipped: 1', self.output)
        self.assertIn('Agents: no Agent has a confirmed update method', self.output)
        for name in ('Codex', 'Claude Code', 'Pi', 'Hermes Agent', 'Codex Plugin Marketplace', 'Claude Plugin Marketplace', 'Claude Plugins', 'Pi Extensions'):
            self.assertIn(name + ': skip', self.output)
        self.assertNotIn('not installed', self.output)

    def test_all_agents_share_one_task_and_detection_precedes_updates(self):
        for name in ('npx', 'brew', 'codex', 'claude', 'pi', 'hermes'):
            self.install(name)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, self.output)
        self.assertEqual(self.updates(), [
            ['npx', 'skills', 'update', '-g', '-y'], ['codex', 'update'],
            ['codex', 'plugin', 'marketplace', 'upgrade'], ['claude', 'update'],
            ['claude', 'plugin', 'marketplace', 'update'],
            ['pi', 'update', '--self'], ['pi', 'update', '--extensions'], ['hermes', 'update'], ['brew', 'upgrade', '--no-ask'],
        ])
        self.assertIn('[2/3] Starting: Agents', self.output)
        self.assertIn('[3/3] Starting: Homebrew Packages', self.output)
        self.assertIn('Succeeded: 3\nFailed: 0\nSkipped: 0', self.output)
        self.assertLess(self.calls.index(['hermes', '--help']), self.calls.index(['codex', 'update']))
        self.assertIn('Codex Plugin Marketplace: ok', self.output)

    def test_agent_failure_continues_marketplace_other_agents_and_brew(self):
        for name in ('codex', 'claude', 'brew'):
            self.install(name)
        self.env['FAIL_CALL'] = json.dumps(['codex', 'update'])
        result = self.run_script()
        self.assertEqual(result.returncode, 1, self.output)
        self.assertEqual(self.updates(), [
            ['codex', 'update'], ['codex', 'plugin', 'marketplace', 'upgrade'],
            ['claude', 'update'], ['claude', 'plugin', 'marketplace', 'update'], ['brew', 'upgrade', '--no-ask'],
        ])
        self.assertIn('Codex: fail (42)', self.output)
        self.assertIn('Failed: 1', self.output)

    def test_skills_failure_does_not_prevent_agents_or_brew(self):
        for name in ('npx', 'hermes', 'brew'):
            self.install(name)
        self.env['FAIL_CALL'] = json.dumps(['npx', 'skills', 'update', '-g', '-y'])
        self.assertEqual(self.run_script().returncode, 1, self.output)
        self.assertEqual(self.updates(), [
            ['npx', 'skills', 'update', '-g', '-y'], ['hermes', 'update'], ['brew', 'upgrade', '--no-ask'],
        ])
        self.assertIn('Succeeded: 2\nFailed: 1\nSkipped: 0', self.output)

    def test_marketplace_failure_marks_agents_failed(self):
        self.install('codex')
        self.install('hermes')
        self.env['FAIL_CALL'] = json.dumps(['codex', 'plugin', 'marketplace', 'upgrade'])
        self.assertEqual(self.run_script().returncode, 1, self.output)
        self.assertIn('Codex Plugin Marketplace: fail (42)', self.output)
        self.assertIn(['hermes', 'update'], self.updates())

    def test_removed_agents_are_not_detected_or_updated(self):
        self.install('opencode')
        self.install('mimo')
        self.assertEqual(self.run_script().returncode, 0, self.output)
        self.assertEqual(self.calls, [])
        self.assertNotIn('OpenCode', self.output)
        self.assertNotIn('MiMoCode', self.output)

    def test_old_pi_does_not_update_extensions(self):
        self.install('pi')
        self.env['NO_SELF_FLAG'] = 'pi'
        self.env['NO_EXTENSIONS_FLAG'] = 'pi'
        self.assertEqual(self.run_script().returncode, 0, self.output)
        self.assertEqual(self.updates(), [])
        self.assertIn('Pi: skip (installed Pi lacks update --self', self.output)

    def test_cli_without_update_command_is_skipped(self):
        self.install('hermes')
        self.env['NO_UPDATE_COMMAND'] = 'hermes'
        self.assertEqual(self.run_script().returncode, 0, self.output)
        self.assertEqual(self.updates(), [])
        self.assertIn("does not advertise 'update'", self.output)

    def test_claude_plugins_refresh_catalog_and_update_each_scope(self):
        self.install('claude')
        self.env['CLAUDE_PLUGINS'] = json.dumps([
            {'id': 'fmt@tools', 'scope': 'user'},
            {'id': 'fmt@tools', 'scope': 'project', 'projectPath': str(self.home)},
            {'id': 'other@tools', 'scope': 'local', 'projectPath': str(self.root / 'other')},
            {'id': 'skill@skills-dir', 'scope': 'user'},
            {'id': 'temp@inline', 'scope': 'session'},
            {'id': 'fmt@tools', 'scope': 'user'},
        ])
        self.assertEqual(self.run_script().returncode, 0, self.output)
        self.assertEqual(self.updates(), [
            ['claude', 'update'], ['claude', 'plugin', 'marketplace', 'update'],
            ['claude', 'plugin', 'update', 'fmt@tools', '--scope', 'user'],
            ['claude', 'plugin', 'update', 'fmt@tools', '--scope', 'project'],
        ])
        self.assertIn('Claude Plugin fmt@tools [user]: ok', self.output)
        self.assertIn('Claude Plugin fmt@tools [project]: ok', self.output)

    def test_claude_plugin_failure_continues_other_plugins_and_pi(self):
        self.install('claude')
        self.install('pi')
        self.install('brew')
        self.env['CLAUDE_PLUGINS'] = json.dumps([
            {'id': 'one@tools', 'scope': 'user'}, {'id': 'two@tools', 'scope': 'user'},
        ])
        self.env['FAIL_CALL'] = json.dumps(['claude', 'plugin', 'update', 'one@tools', '--scope', 'user'])
        self.assertEqual(self.run_script().returncode, 1, self.output)
        self.assertIn('Claude Plugin one@tools [user]: fail (42)', self.output)
        self.assertIn('Claude Plugin two@tools [user]: ok', self.output)
        self.assertIn(['pi', 'update', '--extensions'], self.updates())
        self.assertEqual(self.updates()[-1], ['brew', 'upgrade', '--no-ask'])

    def test_claude_list_errors_are_failures(self):
        self.install('claude')
        self.install('hermes')
        for malformed in (False, True):
            with self.subTest(malformed=malformed):
                self.env['CLAUDE_PLUGINS'] = 'invalid json' if malformed else '[]'
                if malformed:
                    self.env.pop('FAIL_LIST', None)
                else:
                    self.env['FAIL_LIST'] = '1'
                self.assertEqual(self.run_script().returncode, 1, self.output)
                self.assertIn('Claude Plugins (', self.output)
                self.assertIn('Hermes Agent: ok', self.output)

    def test_missing_python_skips_plugins_but_refreshes_marketplace(self):
        self.install('claude')
        (self.bin / 'python3').unlink()
        self.assertEqual(self.run_script().returncode, 0, self.output)
        self.assertIn(['claude', 'plugin', 'marketplace', 'update'], self.updates())
        self.assertNotIn(['claude', 'plugin', 'list', '--json'], self.calls)
        self.assertIn('Claude Plugins: skip (requires plugin list --json and Python 3)', self.output)

    def test_pi_extension_failure_marks_agents_failed(self):
        self.install('pi')
        self.install('brew')
        self.env['FAIL_CALL'] = json.dumps(['pi', 'update', '--extensions'])
        self.assertEqual(self.run_script().returncode, 1, self.output)
        self.assertIn('Pi: ok', self.output)
        self.assertIn('Pi Extensions: fail (42)', self.output)
        self.assertIn(['brew', 'upgrade', '--no-ask'], self.updates())

    def test_pi_extensions_run_when_self_update_unavailable_or_failed(self):
        self.install('pi')
        self.env['NO_SELF_FLAG'] = '1'
        self.assertEqual(self.run_script().returncode, 0, self.output)
        self.assertEqual(self.updates(), [['pi', 'update', '--extensions']])
        self.assertIn('Pi Extensions: ok', self.output)
        self.env.pop('NO_SELF_FLAG')
        self.env['FAIL_CALL'] = json.dumps(['pi', 'update', '--self'])
        self.assertEqual(self.run_script().returncode, 1, self.output)
        self.assertIn('Pi Extensions: ok', self.output)

    def test_missing_extension_flag_skips_only_extensions(self):
        self.install('pi')
        self.env['NO_EXTENSIONS_FLAG'] = '1'
        self.assertEqual(self.run_script().returncode, 0, self.output)
        self.assertEqual(self.updates(), [['pi', 'update', '--self']])
        self.assertIn('Pi Extensions: skip', self.output)

    def test_terminal_updates_preserve_tty_and_restore_progress(self):
        self.install('hermes')
        self.install('claude')
        self.env['CLAUDE_PLUGINS'] = json.dumps([{'id': 'tty@tools', 'scope': 'user'}])
        (self.bin / 'stty').symlink_to(shutil.which('stty'))
        self.env.update(TERM='xterm', CHECK_TTY='1')
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 100, 0, 0))
        process = subprocess.Popen(
            ['/bin/bash', str(SCRIPT)], env=self.env, cwd=self.home,
            stdin=slave, stdout=slave, stderr=slave,
        )
        os.close(slave)
        chunks = []
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if not select.select([master], [], [], 0.1)[0]:
                    continue
                try:
                    data = os.read(master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        break
                    raise
                if not data:
                    break
                chunks.append(data)
            self.assertEqual(process.wait(timeout=1), 0, b''.join(chunks).decode())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        output = b''.join(chunks).decode()
        self.assertIn('fixture: terminal interaction preserved', output)
        self.assertIn('2/3  Agents', output)
        self.assertIn('\x1b[1;23r', output)
        self.assertIn('\x1b[r', output)
        self.assertIn('Hermes Agent: ok', output)

    def test_removed_clean_options_fail_before_any_command(self):
        for option in ('-c', '--clean'):
            with self.subTest(option=option):
                result = self.run_script(option)
                self.assertEqual(result.returncode, 2, self.output)
                self.assertIn('unknown option: ' + option, self.output)
                self.assertEqual(self.calls, [])

    def test_help_has_no_clean_option(self):
        self.assertEqual(self.run_script('--help').returncode, 0, self.output)
        self.assertNotIn('--clean', self.output)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
