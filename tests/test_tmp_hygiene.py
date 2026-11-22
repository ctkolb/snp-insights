#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Temporary-directory hygiene (TMP*). No framework; run with:

    python -B tests/test_tmp_hygiene.py

Pins the owned run root (scripts/runtmp.py), the read-only leak audit
(scripts/tmp_audit.py), the list-only stale sweep (scripts/tmp_sweep.py) and the
mutation runner's temp handling (scripts/loop_mutations.py). Every check works
in a fresh parent directory created inside this process's own temp space, never
in the system temp directory, and removes nothing itself: whatever it leaves is
removed with the owned run root when the process exits.
"""
import ast
import json
import os
import select
import signal
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
TESTS = os.path.join(ROOT, "tests")
AUDIT = os.path.join(SCRIPTS, "tmp_audit.py")
SWEEP = os.path.join(SCRIPTS, "tmp_sweep.py")
PREFIX = "snp-insights-run-"
MARKER = ".snp-insights-run.json"
TIMEOUT = 120

# Modules whose main() does not activate the owned run root yet. BUILD-2 of the
# temp-cleanup stage converts them and empties this set; a new module with a
# main() that does not activate the root fails TMP6.
PENDING_ACTIVATION = set()

# T-12 (decision D-7): live project-owned bytes while test_guard runs, and the
# number of times the project's tracked files are copied into a fixture.
PEAK_LIVE_BYTES = 25 * 1000 * 1000
MAX_FULL_COPIES = 14

# Shared by this process and the child programs below: a byte-level picture of
# a directory tree that never follows a symbolic link.
TREE_SRC = r'''
def tree(path):
    import os
    out = {}
    for dp, dns, fns in os.walk(path, followlinks=False):
        rel = os.path.relpath(dp, path)
        for n in sorted(dns + fns):
            p = os.path.join(dp, n)
            key = os.path.normpath(os.path.join(rel, n))
            if os.path.islink(p):
                out[key] = "link:" + os.readlink(p)
            elif os.path.isdir(p):
                out[key] = "dir"
            else:
                with open(p, "rb") as fh:
                    out[key] = "file:" + fh.read().hex()
    return out
'''
exec(TREE_SRC)  # defines tree()

# The child programs import the helper when the project has one. Without it
# they run unprotected, so the leak checks below fail on behavior (entries
# left behind), not on an import error.
LOAD_SRC = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
try:
    import runtmp
except ImportError:
    runtmp = None
'''

# TMP3: activate, create nested temp entries, report, then wait or exit.
SIGNAL_CHILD = LOAD_SRC + r'''
import json, signal, subprocess, tempfile
signal.signal(signal.SIGINT, signal.default_int_handler)
root = runtmp.activate(tool="hygiene-signal") if runtmp else None
made = [tempfile.mkdtemp() for _ in range(3)]
with open(os.path.join(made[0], "data.txt"), "w") as fh:
    fh.write("x")
fd, named = tempfile.mkstemp()
os.close(fd)
held = tempfile.TemporaryDirectory()
grand = subprocess.run([sys.executable, "-B", "-c",
                        "import tempfile; print(tempfile.gettempdir())"],
                       capture_output=True, text=True).stdout.strip()
info = {"root": root, "pid": os.getpid(), "made": made + [named, held.name],
        "env": os.environ.get("TMPDIR"), "gettempdir": tempfile.gettempdir(),
        "grandchild": grand}
print("READY " + json.dumps(info), flush=True)
mode = sys.argv[2]
if mode == "wait":
    sys.stdin.readline()
elif mode == "raise":
    raise RuntimeError("deliberate failure")
elif mode == "sysexit":
    sys.exit(4)
'''

# TMP4: tamper with the owned root, then exit normally. The helper must refuse
# to remove anything it cannot prove it created.
GUARD_CHILD = LOAD_SRC + TREE_SRC + r'''
import json, tempfile
mode = sys.argv[2]
parent = sys.argv[3]
root = runtmp.activate(tool="hygiene-guard", parent=parent)
sub = tempfile.mkdtemp()
with open(os.path.join(sub, "kept.txt"), "w") as fh:
    fh.write("kept")
marker = os.path.join(root, ".snp-insights-run.json")
with open(marker, "rb") as fh:
    marker_bytes = fh.read()
doc = json.loads(marker_bytes)
result = {"root": root}
def rewrite(**changes):
    doc.update(changes)
    with open(marker, "w") as fh:
        json.dump(doc, fh)
if mode == "symlink":
    decoy = os.path.join(parent, "decoy")
    os.mkdir(decoy)
    with open(os.path.join(decoy, "sentinel.txt"), "w") as fh:
        fh.write("owner data")
    with open(os.path.join(decoy, ".snp-insights-run.json"), "wb") as fh:
        fh.write(marker_bytes)
    os.rename(root, root + ".moved")
    os.symlink(decoy, root)
elif mode == "swapped":
    os.rename(root, root + ".moved")
    os.mkdir(root)
    with open(os.path.join(root, ".snp-insights-run.json"), "wb") as fh:
        fh.write(marker_bytes)
    with open(os.path.join(root, "sentinel.txt"), "w") as fh:
        fh.write("owner data")
elif mode == "nomarker":
    os.rename(marker, marker + ".moved")
elif mode == "badjson":
    with open(marker, "w") as fh:
        fh.write("{not json")
elif mode == "parentswap":
    os.rename(parent, parent + ".moved")
    os.symlink(parent + ".moved", parent)
elif mode == "forgedpid":
    rewrite(pid=1)
elif mode == "foreignuid":
    rewrite(uid=os.getuid() + 1)
elif mode == "token":
    rewrite(token="0" * 32)
elif mode == "fork":
    pid = os.fork()
    if pid == 0:
        sys.exit(0)
    os.waitpid(pid, 0)
    result["after_fork_exists"] = os.path.isdir(root)
elif mode == "explicit":
    result["removed"] = runtmp.cleanup()
    result["again"] = runtmp.cleanup()
    result["root_gone"] = not os.path.lexists(root)
    import signal
    result["handlers_default"] = all(signal.getsignal(s) is signal.SIG_DFL
                                     for s in (signal.SIGTERM, signal.SIGHUP))
    result["env_restored"] = os.environ.get("TMPDIR") == parent
    result["tempdir_restored"] = tempfile.tempdir is None
    result["inactive"] = not runtmp.active() and runtmp.root() is None
elif mode == "release":
    outside = os.path.join(parent, "outside")
    os.mkdir(outside)
    with open(os.path.join(outside, "sentinel.txt"), "w") as fh:
        fh.write("owner data")
    link = os.path.join(root, "link-out")
    os.symlink(outside, link)
    inner = tempfile.mkdtemp()
    os.makedirs(os.path.join(inner, "deep", "er"))
    os.chmod(os.path.join(inner, "deep"), 0o500)
    result["release_inner"] = runtmp.release(inner)
    result["inner_gone"] = not os.path.lexists(inner)
    result["release_outside"] = runtmp.release(outside)
    result["release_link"] = runtmp.release(link)
    result["release_root"] = runtmp.release(root)
    result["release_parent"] = runtmp.release(parent)
    result["link_kept"] = os.path.islink(link)
result["tree"] = tree(parent)
print("RESULT " + json.dumps(result), flush=True)
'''


def _py(*args, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("timeout", TIMEOUT)
    return subprocess.run([sys.executable, "-B", *args], **kw)


def _env(parent):
    env = dict(os.environ)
    env["TMPDIR"] = parent
    return env


def _fresh(label):
    return os.path.realpath(tempfile.mkdtemp(prefix="hyg-" + label + "-"))


def _entries(path):
    return sorted(os.listdir(path))


def _tagged(text, tag):
    for line in text.splitlines():
        if line.startswith(tag + " "):
            return json.loads(line[len(tag) + 1:])
    return None


def _marker(path):
    try:
        with open(os.path.join(path, MARKER)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------ TMP1 suites

STANDALONE_SUITES = ("tests/test_category.py", "tests/test_evidence.py",
                     "tests/test_cli.py", "tests/test_release_panel.py")


def test_child_suites(check):
    # Each suite runs by direct entry, exactly as the project runs it: its own
    # main() must activate the owned run root.
    for suite in STANDALONE_SUITES:
        parent = _fresh("suite")
        proc = _py(os.path.join(ROOT, suite), cwd=ROOT, env=_env(parent))
        name = os.path.basename(suite)
        check("TMP1.suite_passes[%s]" % name,
              proc.returncode == 0 and " 0 failed" in proc.stdout)
        left = _entries(parent)
        check("TMP1.suite_leaves_no_entries[%s] (left %d)" % (name, len(left))
              if left else "TMP1.suite_leaves_no_entries[%s]" % name, not left)


# ------------------------------------------------------------ TMP2 audit

def _audit_run(parent, *cmd, extra=()):
    return _py(AUDIT, "run", "--parent", parent, *extra, "--", sys.executable, "-B", *cmd,
               cwd=ROOT)


def test_audit_detects_leak(check):
    parent = _fresh("audit")
    proc = _audit_run(parent, "-c", "import sys, tempfile; print(tempfile.mkdtemp(dir=sys.argv[1]))",
                      parent)
    summary = _tagged(proc.stdout, "AUDIT")
    leaked = proc.stdout.splitlines()[0].strip() if proc.stdout else ""
    check("TMP2.audit_exits_1_on_leak", proc.returncode == 1)
    check("TMP2.audit_names_the_leak",
          summary is not None and summary.get("new_entries") == [os.path.basename(leaked)]
          and summary.get("new_count") == 1)
    check("TMP2.audit_reports_new_line", ("new: " + os.path.basename(leaked)) in proc.stdout)

    file_parent = _fresh("audit-file")
    proc = _audit_run(file_parent, "-c",
                      "import sys, os; open(os.path.join(sys.argv[1], 'stray.txt'), 'w').close()",
                      file_parent)
    summary = _tagged(proc.stdout, "AUDIT") or {}
    check("TMP2.audit_counts_files", proc.returncode == 1
          and summary.get("new_entries") == ["stray.txt"])

    clean = _fresh("audit-clean")
    proc = _audit_run(clean, "-c", "pass")
    summary = _tagged(proc.stdout, "AUDIT") or {}
    check("TMP2.audit_exits_0_when_clean", proc.returncode == 0 and summary.get("new_count") == 0)
    check("TMP2.audit_creates_nothing", _entries(clean) == [])

    owned = _fresh("audit-owned")
    proc = _audit_run(owned, "-c", LOAD_SRC + "runtmp.activate(tool='hygiene-audit')\n"
                      "import tempfile; tempfile.mkdtemp(); tempfile.mkstemp()", SCRIPTS)
    check("TMP2.audit_clean_for_owned_root_child", proc.returncode == 0 and _entries(owned) == [])

    bare = _fresh("audit-bare")
    proc = _audit_run(bare, "-c", "import tempfile; tempfile.mkdtemp(prefix='bare-')")
    summary = _tagged(proc.stdout, "AUDIT") or {}
    check("TMP2.audit_sets_tmpdir_for_command", proc.returncode == 1
          and [n[:5] for n in summary.get("new_entries", [])] == ["bare-"])

    failing = _fresh("audit-fail")
    proc = _audit_run(failing, "-c", "raise SystemExit(5)")
    summary = _tagged(proc.stdout, "AUDIT") or {}
    check("TMP2.audit_exits_2_on_command_failure",
          proc.returncode == 2 and summary.get("rc") == 5 and summary.get("new_count") == 0)

    allowed = _fresh("audit-allow")
    proc = _audit_run(allowed, "-c", "import sys, tempfile; tempfile.mkdtemp(dir=sys.argv[1])",
                      allowed, extra=("--max-new", "1"))
    check("TMP2.audit_max_new_allows_one", proc.returncode == 0)


# ------------------------------------------------------------ TMP3 signals

def _start_signal_child(parent, mode):
    proc = subprocess.Popen([sys.executable, "-B", "-c", SIGNAL_CHILD, SCRIPTS, mode],
                            cwd=ROOT, env=_env(parent), stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    ready, _, _ = select.select([proc.stdout], [], [], TIMEOUT)
    line = proc.stdout.readline() if ready else ""
    info = json.loads(line[6:]) if line.startswith("READY ") else None
    return proc, info


def _finish(proc, wait_first=False):
    try:
        if wait_first:
            proc.wait(timeout=TIMEOUT)
        out, err = proc.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    return proc.returncode, out, err


def _sweep(parent, *extra):
    proc = _py(SWEEP, "--parent", parent, "--json", *extra, cwd=ROOT)
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        doc = {}
    return proc.returncode, doc


def _state_of(doc, name):
    for entry in doc.get("entries", []):
        if entry.get("name") == name:
            return entry.get("state")
    return None


def test_signals(check):
    expected_rc = {"TERM": 128 + signal.SIGTERM, "HUP": 128 + signal.SIGHUP,
                   "INT": -signal.SIGINT, "exit": 0, "raise": 1, "sysexit": 4}
    for label in ("KILL", "TERM", "INT", "HUP", "exit", "raise", "sysexit"):
        parent = _fresh("sig")
        mode = "wait" if label in ("KILL", "TERM", "INT", "HUP") else label
        proc, info = _start_signal_child(parent, mode)
        check("TMP3.child_ready[%s]" % label, info is not None)
        if info is None:
            proc.kill()
            _finish(proc)
            continue
        root = info["root"] or ""
        if label == "KILL":
            check("TMP3.owned_root_under_parent", os.path.dirname(root) == parent
                  and os.path.basename(root).startswith(PREFIX))
            check("TMP3.tmpdir_env_points_into_root", info["env"] == root)
            check("TMP3.gettempdir_is_root", info["gettempdir"] == root)
            check("TMP3.grandchild_inherits_root", info["grandchild"] == root)
            check("TMP3.nested_entries_inside_root",
                  bool(root) and all(p.startswith(root + os.sep) for p in info["made"]))
            mk = _marker(root) or {}
            check("TMP3.marker_fields", mk.get("schema") == 1 and mk.get("pid") == info["pid"]
                  and mk.get("uid") == os.getuid() and mk.get("tool") == "hygiene-signal"
                  and isinstance(mk.get("created"), str) and mk["created"].endswith("Z")
                  and isinstance(mk.get("token"), str) and len(mk["token"]) == 32)
            check("TMP3.root_mode_0700", bool(root) and os.path.isdir(root)
                  and (os.stat(root).st_mode & 0o777) == 0o700)
            _, live = _sweep(parent)
            check("TMP3.sweep_lists_running_root_live",
                  _state_of(live, os.path.basename(root)) == "live")
        if label in ("KILL", "TERM", "INT", "HUP"):
            os.kill(proc.pid, getattr(signal, "SIG" + label))
        rc, _, err = _finish(proc, wait_first=label in ("KILL", "TERM", "INT", "HUP"))
        left = _entries(parent)
        if label == "KILL":
            only = left[0] if len(left) == 1 else ""
            check("TMP3.kill_leaves_at_most_one (left %d)" % len(left) if len(left) > 1
                  else "TMP3.kill_leaves_at_most_one", len(left) <= 1)
            check("TMP3.kill_leftover_is_marked_root", only == os.path.basename(root)
                  and (_marker(os.path.join(parent, only)) or {}).get("pid") == info["pid"])
            rc_sweep, doc = _sweep(parent)
            check("TMP3.sweep_lists_killed_root_stale", rc_sweep == 0
                  and _state_of(doc, only) == "stale"
                  and doc.get("eligible") == [os.path.join(parent, only)])
            rc_fail, _ = _sweep(parent, "--fail-on-stale")
            check("TMP3.sweep_fail_on_stale_exits_3", rc_fail == 3)
            check("TMP3.sweep_left_killed_root", left == _entries(parent))
        else:
            check("TMP3.leaves_no_entries[%s]" % label, left == [])
            check("TMP3.exit_code[%s]" % label, rc == expected_rc[label])
            check("TMP3.no_cleanup_noise[%s]" % label, "runtmp:" not in err
                  and "Exception ignored" not in err)


# ------------------------------------------------------------ TMP4 guards

def _guard_child(mode, parent=None):
    parent = parent or _fresh("guard")
    proc = _py("-c", GUARD_CHILD, SCRIPTS, mode, parent, cwd=ROOT, env=_env(parent))
    result = _tagged(proc.stdout, "RESULT")
    return parent, proc, result


def test_cleanup_guards(check):
    clean_parent, proc, result = _guard_child("clean")
    check("TMP4.control_removes_root", result is not None and proc.returncode == 0
          and _entries(clean_parent) == [])
    for mode in ("symlink", "swapped", "parentswap", "nomarker", "badjson", "forgedpid",
                 "foreignuid", "token"):
        parent, proc, result = _guard_child(mode)
        ok = result is not None and proc.returncode == 0
        check("TMP4.refusal_leaves_bytes_unchanged[%s]" % mode,
              ok and tree(parent) == result["tree"])
        check("TMP4.refusal_reported[%s]" % mode, "runtmp: refusing" in proc.stderr)
        if mode == "symlink" and ok:
            check("TMP4.decoy_sentinel_intact", tree(os.path.join(parent, "decoy")).get(
                "sentinel.txt") == "file:" + b"owner data".hex())
            check("TMP4.symlink_left_in_place", os.path.islink(result["root"]))
    parent, proc, result = _guard_child("fork")
    check("TMP4.forked_child_does_not_remove",
          result is not None and result.get("after_fork_exists") is True)
    check("TMP4.owner_removes_after_fork", proc.returncode == 0 and _entries(parent) == [])
    check("TMP4.forked_child_stays_silent", "runtmp:" not in proc.stderr)
    parent, proc, result = _guard_child("explicit")
    result = result or {}
    check("TMP4.explicit_cleanup_removes_once", result.get("removed") is True
          and result.get("again") is False and result.get("root_gone") is True)
    check("TMP4.cleanup_restores_signal_handlers", result.get("handlers_default") is True)
    check("TMP4.cleanup_restores_tmpdir", result.get("env_restored") is True
          and result.get("tempdir_restored") is True and result.get("inactive") is True)
    real = _fresh("guard-real")
    link = real + "-link"
    os.symlink(real, link)
    _, proc, result = _guard_child("clean", parent=link)
    check("TMP4.symlinked_parent_resolved",
          result is not None and os.path.dirname(result["root"]) == real)
    check("TMP4.symlinked_parent_root_removed", proc.returncode == 0 and _entries(real) == []
          and "runtmp:" not in proc.stderr)
    parent, proc, result = _guard_child("release")
    result = result or {}
    check("TMP4.release_removes_inner_tree", result.get("release_inner") is True
          and result.get("inner_gone") is True)
    check("TMP4.release_refuses_outside", result.get("release_outside") is False
          and tree(os.path.join(parent, "outside")).get("sentinel.txt")
          == "file:" + b"owner data".hex())
    check("TMP4.release_refuses_symlink", result.get("release_link") is False
          and result.get("link_kept") is True)
    check("TMP4.release_refuses_root_and_parent", result.get("release_root") is False
          and result.get("release_parent") is False)
    check("TMP4.release_then_exit_removes_root", proc.returncode == 0
          and _entries(parent) == ["outside"])


# ------------------------------------------------------------ TMP5 sweep

def _write(path, text):
    with open(path, "w") as fh:
        fh.write(text)


def _fake_root(parent, name, pid, **extra):
    path = os.path.join(parent, name)
    os.mkdir(path, 0o700)
    doc = {"schema": 1, "tool": "fake", "pid": pid, "uid": os.getuid(),
           "created": "2026-01-01T00:00:00Z", "token": "a" * 32}
    doc.update(extra)
    _write(os.path.join(path, MARKER), json.dumps(doc))
    return path


def _stat_picture(parent):
    out = {}
    for name in sorted(os.listdir(parent)):
        p = os.path.join(parent, name)
        st = os.lstat(p)
        out[name] = (st.st_mode, st.st_uid, st.st_size, st.st_mtime_ns, st.st_ino)
    return out, tree(parent)


def test_sweep(check):
    parent = _fresh("sweep")
    dead = subprocess.run([sys.executable, "-B", "-c", "import os; print(os.getpid())"],
                          capture_output=True, text=True).stdout.strip()
    dead_pid = int(dead) if dead.isdigit() else 999999
    _fake_root(parent, PREFIX + "live0001", os.getpid())
    _fake_root(parent, PREFIX + "stale001", dead_pid)
    os.mkdir(os.path.join(parent, PREFIX + "nomarkr1"))
    _fake_root(parent, PREFIX + "baduid01", dead_pid, uid=os.getuid() + 1)
    _fake_root(parent, PREFIX + "badpid01", "12")
    _fake_root(parent, PREFIX + "schema02", dead_pid, schema=2)
    bad = os.path.join(parent, PREFIX + "badjson1")
    os.mkdir(bad)
    _write(os.path.join(bad, MARKER), "{broken")
    target = _fake_root(parent, "elsewhere", dead_pid)
    os.symlink(target, os.path.join(parent, PREFIX + "symlink1"))
    lm = os.path.join(parent, PREFIX + "linkmkr1")
    os.mkdir(lm)
    os.symlink(os.path.join(target, MARKER), os.path.join(lm, MARKER))
    _fake_root(parent, PREFIX + "TOOLONG-name", dead_pid)
    _write(os.path.join(parent, PREFIX + "plainfl1"), "not a dir")
    for legacy in ("snp-insights-full-abc", "snp-insights-hg-def", "r2e-e2e-ghi", "loop-mut-jkl"):
        os.mkdir(os.path.join(parent, legacy))
    os.mkdir(os.path.join(parent, "tmpunrelated"))

    before = _stat_picture(parent)
    rc, doc = _sweep(parent)
    rc_text = _py(SWEEP, "--parent", parent, cwd=ROOT)
    rc_legacy, doc_legacy = _sweep(parent, "--show-legacy")
    after = _stat_picture(parent)
    check("TMP5.sweep_is_read_only", before == after)
    check("TMP5.sweep_exit_0", rc == 0 and rc_text.returncode == 0 and rc_legacy == 0)
    expected = {
        PREFIX + "live0001": "live", PREFIX + "stale001": "stale",
        PREFIX + "nomarkr1": "invalid", PREFIX + "baduid01": "invalid",
        PREFIX + "badpid01": "invalid", PREFIX + "badjson1": "invalid",
        PREFIX + "schema02": "invalid",
        PREFIX + "symlink1": "invalid", PREFIX + "linkmkr1": "invalid",
        PREFIX + "TOOLONG-name": "invalid", PREFIX + "plainfl1": "invalid",
    }
    for name, state in sorted(expected.items()):
        check("TMP5.sweep_state[%s]=%s" % (name[len(PREFIX):], state),
              _state_of(doc, name) == state)
    listed = {e.get("name") for e in doc.get("entries", [])}
    check("TMP5.sweep_lists_only_run_roots", listed == set(expected))
    check("TMP5.sweep_eligible_is_stale_only",
          doc.get("eligible") == [os.path.join(parent, PREFIX + "stale001")])
    check("TMP5.sweep_counts_legacy", doc.get("legacy_count") == 4 and "legacy" not in doc)
    check("TMP5.sweep_show_legacy_lists_names", sorted(doc_legacy.get("legacy") or []) == [
        "loop-mut-jkl", "r2e-e2e-ghi", "snp-insights-full-abc", "snp-insights-hg-def"])
    check("TMP5.sweep_text_names_exact_path",
          ("stale\t" + os.path.join(parent, PREFIX + "stale001")) in rc_text.stdout
          and "4 legacy-pattern entries, owner-managed, never eligible" in rc_text.stdout)
    try:
        with open(SWEEP) as fh:
            src = fh.read()
    except OSError:
        src = "raise SystemExit"
    calls = {n.func.attr for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    check("TMP5.sweep_has_no_deletion_calls", not calls & {
        "rmtree", "remove", "unlink", "rmdir", "removedirs", "release", "cleanup", "rename",
        "replace", "chmod", "truncate"})


# ------------------------------------------------------------ TMP6 activation

def _main_activates(path):
    with open(path) as fh:
        tree_ = ast.parse(fh.read())
    for node in tree_.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "activate"
                        and isinstance(sub.func.value, ast.Name) and sub.func.value.id == "runtmp"):
                    return True
            return False
    return None


def test_activation(check):
    pending = set()
    for name in sorted(os.listdir(TESTS)):
        if name.startswith("test_") and name.endswith(".py"):
            state = _main_activates(os.path.join(TESTS, name))
            if state is False:
                pending.add("tests/" + name)
    check("TMP6.unactivated_mains_are_the_known_pending_set", pending == PENDING_ACTIVATION)
    for rel in ("tests/test_pipeline.py", "tests/test_tmp_hygiene.py", "scripts/loop_mutations.py"):
        check("TMP6.main_activates[%s]" % os.path.basename(rel),
              _main_activates(os.path.join(ROOT, rel)) is True)


# ------------------------------------------------------------ TMP7 loop_mutations

FAKE_SUITE = r'''
import tempfile
d = tempfile.mkdtemp()
print("  FAIL where=" + d)
'''


def test_loop_mutations(check):
    sys.path.insert(0, SCRIPTS)
    try:
        import loop_mutations
    except ImportError:
        check("TMP7.loop_mutations_importable", False)
        return
    copy = _fresh("lm-copy")
    os.makedirs(os.path.join(copy, "tests"))
    _write(os.path.join(copy, "tests", "test_fake.py"), FAKE_SUITE)
    here = tempfile.gettempdir()
    before = _entries(here)
    saved = loop_mutations.SUITES
    loop_mutations.SUITES = ("tests/test_fake.py",)
    try:
        runner = getattr(loop_mutations, "checks_in_scratch", None)
        fails = runner(copy) if runner else set()
    finally:
        loop_mutations.SUITES = saved
    where = next((f.split("where=", 1)[1] for f in fails if "where=" in f), "")
    scratch = os.path.dirname(where)
    check("TMP7.suite_tmpdir_is_per_mutation_scratch",
          os.path.basename(scratch).startswith("loop-mut-suite-")
          and os.path.dirname(scratch) == os.path.realpath(here))
    check("TMP7.per_mutation_scratch_removed", bool(where) and not os.path.lexists(scratch))
    check("TMP7.no_new_entries_after_mutation", _entries(here) == before)


# ------------------------------------------------------------ TMP8 scrubbed env (D-10)

def _scrubbed_env_sites():
    """(file, line) of every dict literal or dict() call that names both PATH and
    HOME as keys in a test module: a scrubbed environment for a child process."""
    sites = []
    for name in sorted(os.listdir(TESTS)):
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        with open(os.path.join(TESTS, name)) as fh:
            tree_ = ast.parse(fh.read())
        for node in ast.walk(tree_):
            keys = None
            if isinstance(node, ast.Dict):
                keys = {k.value for k in node.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id == "dict"):
                keys = {k.arg for k in node.keywords if k.arg}
            if keys and {"PATH", "HOME"} <= keys:
                sites.append((name, node.lineno, "TMPDIR" in keys))
    return sites


def test_scrubbed_env(check):
    sites = _scrubbed_env_sites()
    check("TMP8.scrubbed_env_sites_found", len(sites) >= 6)
    missing = ["%s:%d" % (n, ln) for n, ln, has in sites if not has]
    check("TMP8.scrubbed_env_passes_tmpdir (missing %s)" % ",".join(missing) if missing
          else "TMP8.scrubbed_env_passes_tmpdir", not missing)
    # The detector itself must see an omission.
    probe = ast.parse("e = {'PATH': 1, 'HOME': 2}\nf = {'PATH': 1, 'HOME': 2, 'TMPDIR': 3}")
    flags = [("TMPDIR" in {k.value for k in n.keys}) for n in ast.walk(probe)
             if isinstance(n, ast.Dict)]
    check("TMP8.detector_distinguishes_omission", sorted(flags) == [False, True])


# ------------------------------------------------------------ TMP9 fixture isolation

def test_fixture_isolation(check):
    sys.path.insert(0, TESTS)
    sys.path.insert(0, SCRIPTS)
    import test_guard as tg
    scope = getattr(tg, "_fixture_scope", None)
    fingerprint = getattr(tg, "_template_fingerprint", None)
    check("TMP9.fixture_scope_exists", scope is not None and fingerprint is not None)
    if scope is None or fingerprint is None:
        return
    before = fingerprint()
    with scope():
        repo1, base1 = tg._full_fixture()
        repo2, base2 = tg._full_fixture(("clean synthetic message", "second"))
        gits = [os.path.realpath(os.path.join(r, ".git")) for r in (repo1, repo2)]
        homes = [os.path.realpath(os.path.join(r, ".home")) for r in (repo1, repo2)]
        check("TMP9.fixtures_do_not_share_paths",
              len({base1, base2}) == 2 and len(set(gits)) == 2 and len(set(homes)) == 2
              and all(os.path.isdir(g) and not os.path.islink(g) for g in gits))
        heads = [tg._fx(r, "rev-list", "--count", "HEAD") for r in (repo1, repo2)]
        check("TMP9.fixtures_keep_independent_history", heads == ["2", "3"])
        marker = os.path.join(repo1, "docs", "fixture-isolation-probe.md")
        with open(marker, "w") as fh:
            fh.write("probe")
        check("TMP9.mutating_one_fixture_leaves_the_other",
              not os.path.exists(os.path.join(repo2, "docs", "fixture-isolation-probe.md")))
        check("TMP9.fixtures_live_inside_owned_root",
              not runtmp_active() or all(
                  os.path.realpath(b).startswith(runtmp_root() + os.sep) for b in (base1, base2)))
    check("TMP9.scope_releases_fixtures", not os.path.lexists(base1) and not os.path.lexists(base2))
    check("TMP9.template_unchanged", fingerprint() == before)


def runtmp_active():
    try:
        import runtmp
    except ImportError:
        return False
    return runtmp.active()


def runtmp_root():
    import runtmp
    return os.path.realpath(runtmp.root())


# ------------------------------------------------------------ TMP10 no in-tree scratch (A-1)

def test_no_in_tree_scratch(check):
    with open(os.path.join(TESTS, "test_guard.py")) as fh:
        src = fh.read()
    tree_ = ast.parse(src)
    literals = [n.value for n in ast.walk(tree_)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    check("TMP10.no_fixed_in_tree_large_file",
          not any("tmp_large" in s for s in literals))
    check("TMP10.no_stray_large_file_in_tree",
          not os.path.lexists(os.path.join(TESTS, ".tmp_large.bin")))


# ------------------------------------------------------------ TMP11 test_guard (heavy)

GUARD_CHILD_SRC = r'''
import json, os, shutil, sys
root = sys.argv[1]
sys.path.insert(0, os.path.join(root, "scripts"))
sys.path.insert(0, os.path.join(root, "tests"))
import test_guard as tg
stats = {"fixtures": 0, "copies": 0}
real_full = tg._full_fixture
real_copy = shutil.copy2
readme = os.path.join(root, "README.md")
def counting_full(*a, **k):
    stats["fixtures"] += 1
    return real_full(*a, **k)
def counting_copy(src, dst, *a, **k):
    if os.path.abspath(src) == readme:
        stats["copies"] += 1
    return real_copy(src, dst, *a, **k)
tg._full_fixture = counting_full
shutil.copy2 = counting_copy
rc = tg.main()
print("STATS " + json.dumps(stats), flush=True)
sys.exit(rc)
'''


def test_guard_standalone(check):
    parent = _fresh("guard")
    out_json = os.path.join(_fresh("guard-json"), "audit.json")
    proc = _py(AUDIT, "run", "--parent", parent, "--sample-peak", "--json", out_json, "--",
               sys.executable, "-B", "-c", GUARD_CHILD_SRC, ROOT, cwd=ROOT, timeout=900)
    summary = _tagged(proc.stdout, "AUDIT") or {}
    stats = _tagged(proc.stdout, "STATS") or {}
    check("TMP11.test_guard_passes", summary.get("rc") == 0 and " 0 failed" in proc.stdout)
    new = summary.get("new_count", -1)
    check("TMP11.test_guard_leaves_no_entries (left %s)" % new if new else
          "TMP11.test_guard_leaves_no_entries", new == 0)
    peak = summary.get("peak_bytes", 10 ** 12)
    check("TMP11.peak_live_bytes_bounded (peak %s)" % peak if peak > PEAK_LIVE_BYTES else
          "TMP11.peak_live_bytes_bounded", peak <= PEAK_LIVE_BYTES)
    copies = stats.get("copies", 10 ** 6)
    check("TMP11.full_copies_bounded (copies %s)" % copies if copies > MAX_FULL_COPIES else
          "TMP11.full_copies_bounded", copies <= MAX_FULL_COPIES)
    check("TMP11.fixture_count_recorded", stats.get("fixtures", 0) > 0)
    check("TMP11.no_stray_large_file_after_run",
          not os.path.lexists(os.path.join(TESTS, ".tmp_large.bin")))
    sys.stderr.write("TMP11 measured: fixtures=%s copies=%s peak=%s new=%s seconds=%s\n" % (
        stats.get("fixtures"), stats.get("copies"), peak, new, summary.get("seconds")))


def run(check, heavy=False):
    test_scrubbed_env(check)
    test_fixture_isolation(check)
    test_no_in_tree_scratch(check)
    if heavy:
        test_guard_standalone(check)
    test_child_suites(check)
    test_audit_detects_leak(check)
    test_signals(check)
    test_cleanup_guards(check)
    test_sweep(check)
    test_activation(check)
    test_loop_mutations(check)


def main():
    sys.path.insert(0, SCRIPTS)
    try:
        import runtmp
    except ImportError:
        runtmp = None
    passed, failed = [], []

    def check(name, cond):
        (passed if cond else failed).append(name)

    if runtmp is None:
        check("TMP0.runtmp_importable", False)
    else:
        runtmp.activate(tool="test_tmp_hygiene")
    # Standalone only: the test_guard child takes about a minute, and the full
    # pipeline already runs test_guard itself.
    run(check, heavy=True)
    for name in passed:
        print(f"  ok   {name}")
    for name in failed:
        print(f"  FAIL {name}")
    print(f"\n{len(passed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
