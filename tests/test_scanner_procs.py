"""Reliable per-owner scanner process detection + kill — the fix for an orphaned scanner that lingers
on an old port holding its per-owner FYERS lock (blocking the next day's feed) and for the start-race
double-spawn. Uses a FAKE /proc so it's deterministic on any OS.

- ControlCenter._scanner_procs / scanner_status: find our scanner by its per-owner selection file,
  independent of the (changing) port.
- scanners.stop_all_scanner_processes: EOD sweep of all live `launch.py run` scanners.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from radar.control import ControlCenter
from server import scanners


def _write_proc(root, pid, cmdline_parts, state='S'):
    d = Path(root) / str(pid)
    d.mkdir(parents=True)
    (d / 'cmdline').write_bytes(b'\x00'.join(p.encode() for p in cmdline_parts) + b'\x00')
    (d / 'stat').write_text(f'{pid} (python3.11) {state} 1 1 1 0 -1 0 0 0')


def _run_cmd(port, sel):
    return ['python', '/app/launch.py', 'run', '--port', str(port),
            '--selection', sel, '--lock', '/app/data/.fyers_api_u1.lock']


class ScannerProcsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cc = ControlCenter()
        self.cc.sim = False
        self.cc.demo = False
        self.cc.selection_path = Path('/app/data/today100_u1.json')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_finds_own_scanner_with_port(self):
        _write_proc(self.tmp, 2451, _run_cmd(34341, '/app/data/today100_u1.json'))
        self.assertEqual(self.cc._scanner_procs(proc_root=self.tmp), [(2451, 34341)])

    def test_ignores_other_user_zombie_and_unrelated(self):
        _write_proc(self.tmp, 100, _run_cmd(1, '/app/data/today100_u3.json'))                 # other user
        _write_proc(self.tmp, 101, _run_cmd(2, '/app/data/today100_u1.json'), state='Z')      # zombie (dead)
        _write_proc(self.tmp, 102, ['python', '-c', 'print(1)'])                              # unrelated
        self.assertEqual(self.cc._scanner_procs(proc_root=self.tmp), [])

    def test_scanner_status_uses_proc_and_aligns_port(self):
        _write_proc(self.tmp, 2451, _run_cmd(34341, '/app/data/today100_u1.json'))
        orig = self.cc._scanner_procs
        self.cc._scanner_procs = lambda: orig(proc_root=self.tmp)
        st = self.cc.scanner_status()
        self.assertTrue(st['running'])
        self.assertEqual(st['pid'], 2451)
        self.assertEqual(self.cc.scanner_port, 34341)   # port realigned to the live process

    def test_sim_returns_none(self):
        self.cc.sim = True
        self.assertIsNone(self.cc._scanner_procs(proc_root=self.tmp))


class StopAllTest(unittest.TestCase):
    def test_counts_only_run_scanners(self):
        tmp = tempfile.mkdtemp()
        try:
            # high fake pids so the (harmless) kills are no-ops on this machine
            _write_proc(tmp, 999991, ['python', '/app/launch.py', 'run', '--selection', '/app/data/today100_u1.json'])
            _write_proc(tmp, 999992, ['python', '/app/launch.py', 'sim'])    # sim, not a 'run' scanner
            _write_proc(tmp, 999993, ['python', '/app/launch.py', 'run', '--selection', '/app/data/today100_u3.json'])
            self.assertEqual(scanners.stop_all_scanner_processes(proc_root=tmp), 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
