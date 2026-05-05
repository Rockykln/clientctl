"""core.procs — /proc-based process index.

Uses a fake /proc tree (see conftest.fake_proc) so the tests don't depend
on what's actually running on the host.
"""

from core import procs


def test_snapshot_reads_fake_proc(fake_proc):
    fake_proc.add(pid=10, comm="firefox", cmdline=["/usr/bin/firefox"])
    fake_proc.add(pid=11, comm="bash",    cmdline=["/bin/bash"])
    snap = procs.snapshot()
    pids = sorted(p.pid for p in snap)
    assert pids == [10, 11]


def test_find_app_pids_by_comm(fake_proc):
    fake_proc.add(pid=42, comm="firefox", cmdline=["/usr/bin/firefox"])
    pids = procs.find_app_pids({"binary": "firefox"})
    assert pids == [42]


def test_find_app_pids_by_cmdline_path(fake_proc):
    # Common case: comm differs from cmdline (e.g. wrapper scripts)
    fake_proc.add(pid=99, comm="other", cmdline=["/opt/myapp/bin/myapp", "--gui"])
    pids = procs.find_app_pids({"binary": "myapp"})
    assert pids == [99]


def test_find_app_pids_by_cmdline_match(fake_proc):
    # Electron apps: comm=electron but the right --class arg identifies them
    fake_proc.add(pid=200, comm="electron",
                  cmdline=["electron", "--class=MyApp", "--enable-features=..."])
    pids = procs.find_app_pids({"binary": "my-electron-app", "cmdline_match": "--class=MyApp"})
    assert 200 in pids


def test_find_app_pids_truncated_comm(fake_proc):
    # /proc/comm is truncated to 15 chars
    fake_proc.add(pid=300, comm="plasma-systemmo",
                  cmdline=["/usr/bin/plasma-systemmonitor"])
    pids = procs.find_app_pids({"binary": "plasma-systemmo"})
    assert 300 in pids


def test_find_app_pids_pwa_returns_empty(fake_proc):
    fake_proc.add(pid=500, comm="chromium",
                  cmdline=["/usr/bin/chromium", "--app-id=abc"])
    pids = procs.find_app_pids({"pwa_id": "abc", "binary": "chromium"})
    assert pids == []


def test_find_app_pids_no_binary():
    assert procs.find_app_pids({}) == []


def test_is_paused_true_when_state_T(fake_proc):
    fake_proc.add(pid=10, comm="x", cmdline=["x"], state="T")
    assert procs.is_paused([10]) is True


def test_is_paused_false_when_state_S(fake_proc):
    fake_proc.add(pid=11, comm="x", cmdline=["x"], state="S")
    assert procs.is_paused([11]) is False


def test_is_paused_empty_list(fake_proc):
    fake_proc.add(pid=12, comm="x", cmdline=["x"])
    assert procs.is_paused([]) is False


def test_descendants_walks_tree(fake_proc):
    fake_proc.add(pid=1, comm="init", cmdline=["init"], ppid=0)
    fake_proc.add(pid=2, comm="a",    cmdline=["a"],    ppid=1)
    fake_proc.add(pid=3, comm="b",    cmdline=["b"],    ppid=2)
    fake_proc.add(pid=4, comm="c",    cmdline=["c"],    ppid=2)

    descs = sorted(procs.descendants([1]))
    assert descs == [1, 2, 3, 4]

    # Subtree only
    descs = sorted(procs.descendants([2]))
    assert descs == [2, 3, 4]


def test_descendants_handles_cycle_safely(fake_proc):
    # Defensive: even if we accidentally pass overlapping pids, no infinite loop
    fake_proc.add(pid=1, comm="a", cmdline=["a"], ppid=0)
    fake_proc.add(pid=2, comm="b", cmdline=["b"], ppid=1)
    descs = sorted(procs.descendants([1, 2]))
    assert descs == [1, 2]


def test_invalidate_forces_rescan(fake_proc):
    fake_proc.add(pid=1, comm="a", cmdline=["a"])
    procs.snapshot()
    fake_proc.add(pid=2, comm="b", cmdline=["b"])
    # Without invalidate the cache hides pid 2
    snap_before = {p.pid for p in procs.snapshot()}
    procs.invalidate()
    snap_after = {p.pid for p in procs.snapshot()}
    assert 2 not in snap_before
    assert 2 in snap_after


def test_find_konsole_with_arg(fake_proc):
    fake_proc.add(pid=1, comm="konsole",
                  cmdline=["/usr/bin/konsole", "--title", "Cachy-Update", "-e", "arch-update"])
    fake_proc.add(pid=2, comm="konsole",
                  cmdline=["/usr/bin/konsole"])
    pids = procs.find_konsole_with_arg("arch-update")
    assert pids == [1]
