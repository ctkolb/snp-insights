#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Owned temporary run root for tests and build-loop tooling. Standard library only.

    import runtmp
    runtmp.activate(tool="test_pipeline")

activate() creates one directory, <parent>/snp-insights-run-<8 chars>, with a
marker file (.snp-insights-run.json: schema, tool, pid, uid, UTC creation time,
random token). It then points tempfile.tempdir and TMPDIR at that directory, so
bare mkdtemp(), TemporaryDirectory() and NamedTemporaryFile() calls in this
process and in child processes that inherit the environment land inside it.

The root is removed on normal exit, on an exception, on SystemExit and
KeyboardInterrupt, and on SIGTERM and SIGHUP (turned into a clean exit only when
the signal still has its default disposition). SIGKILL and os._exit cannot be
caught and leave the one root behind; scripts/tmp_sweep.py lists such leftovers.

Removal is guarded. The helper removes only the directory it created: a real
directory (not a symbolic link) with the same device and inode, directly under
the recorded parent, with the expected name, owned by this uid, whose marker is
a regular file that still names this pid, uid and token. Only the creating
process removes it, never a forked child. Anything else is left in place and
reported on stderr as "runtmp: refusing ...".
"""
import atexit
import json
import os
import re
import secrets
import shutil
import signal
import stat
import string
import sys
import tempfile
import threading
import time

PREFIX = "snp-insights-run-"
MARKER = ".snp-insights-run.json"
SCHEMA = 1
NAME_RE = re.compile(r"^snp-insights-run-[a-z0-9]{8}$")
_ALPHABET = string.ascii_lowercase + string.digits
_SIGNALS = tuple(getattr(signal, n) for n in ("SIGTERM", "SIGHUP") if hasattr(signal, n))

_state = None


def active():
    """True when this process owns an active run root."""
    return _state is not None and _state["pid"] == os.getpid()


def root():
    """The active run root of this process, or None."""
    return _state["root"] if active() else None


def _warn(msg):
    try:
        sys.stderr.write("runtmp: %s\n" % msg)
        sys.stderr.flush()
    except Exception:
        pass


def _on_signal(signum, frame):
    raise SystemExit(128 + signum)


def activate(tool="tests", parent=None):
    """Create and activate this process's owned run root; return its path.

    Idempotent within one process. A forked child that calls it gets its own
    root. A nested call under another process's root creates a root inside it.
    """
    global _state
    if active():
        return _state["root"]
    base = os.path.realpath(parent if parent is not None else tempfile.gettempdir())
    for _ in range(100):
        name = PREFIX + "".join(secrets.choice(_ALPHABET) for _ in range(8))
        path = os.path.join(base, name)
        try:
            os.mkdir(path, 0o700)
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError("runtmp: no free run-root name under %s" % base)
    os.chmod(path, 0o700)
    st = os.lstat(path)
    token = secrets.token_hex(16)
    doc = {"schema": SCHEMA, "tool": str(tool), "pid": os.getpid(), "uid": os.getuid(),
           "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "token": token}
    fd = os.open(os.path.join(path, MARKER), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(doc, fh)
    _state = {"root": path, "parent": base, "name": name, "pid": os.getpid(),
              "uid": os.getuid(), "token": token, "dev": st.st_dev, "ino": st.st_ino,
              "tempdir": tempfile.tempdir, "env": os.environ.get("TMPDIR"), "handlers": {}}
    tempfile.tempdir = path
    os.environ["TMPDIR"] = path
    atexit.register(cleanup)
    if threading.current_thread() is threading.main_thread():
        for sig in _SIGNALS:
            if signal.getsignal(sig) is signal.SIG_DFL:
                _state["handlers"][sig] = signal.signal(sig, _on_signal)
    return path


def read_marker(path):
    """Return the marker of a run-root candidate as a dict, or None.

    Never follows a symbolic link: the marker must be a regular file.
    """
    try:
        fd = os.open(os.path.join(path, MARKER), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        with os.fdopen(fd, "rb") as fh:
            fd = None
            doc = json.loads(fh.read(65536).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    finally:
        if fd is not None:
            os.close(fd)
    return doc if isinstance(doc, dict) else None


def pid_state(pid):
    """'alive', 'dead' or 'unknown' for a process id (no signal is sent)."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return "unknown"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "dead"
    except PermissionError:
        return "alive"
    except OSError:
        return "unknown"
    return "alive"


def _refusal(st):
    """Why the recorded root must not be removed, or None when it is ours."""
    path = st["root"]
    if os.getpid() != st["pid"]:
        return "not the creating process"
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return "missing"
    except OSError as exc:
        return "unreadable (%s)" % exc
    if stat.S_ISLNK(info.st_mode):
        return "is a symbolic link"
    if not stat.S_ISDIR(info.st_mode):
        return "not a directory"
    if (info.st_dev, info.st_ino) != (st["dev"], st["ino"]):
        return "replaced by another directory"
    if info.st_uid != st["uid"] or os.getuid() != st["uid"]:
        return "owned by another user"
    if os.path.dirname(path) != st["parent"] or os.path.realpath(path) != path:
        return "not directly under the recorded parent"
    if not NAME_RE.match(os.path.basename(path)) or os.path.basename(path) != st["name"]:
        return "unexpected name"
    doc = read_marker(path)
    if doc is None:
        return "marker missing or unreadable"
    if doc.get("pid") != st["pid"]:
        return "marker names another process"
    if doc.get("uid") != st["uid"]:
        return "marker names another user"
    if doc.get("token") != st["token"]:
        return "marker token differs"
    return None


def _onexc(func, path, exc):
    if isinstance(exc, FileNotFoundError):
        return
    if isinstance(exc, PermissionError):
        try:
            parent = os.path.dirname(path)
            os.chmod(parent, os.lstat(parent).st_mode | stat.S_IRWXU)
            if not os.path.islink(path) and os.path.isdir(path):
                os.chmod(path, os.lstat(path).st_mode | stat.S_IRWXU)
            func(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            pass
    raise exc


def _remove_tree(path):
    """Remove a tree known to be ours; retries while late writers finish."""
    for _ in range(5):
        try:
            shutil.rmtree(path, onexc=_onexc)
        except FileNotFoundError:
            return True
        except OSError:
            pass
        if not os.path.lexists(path):
            return True
        time.sleep(0.05)
    return not os.path.lexists(path)


def _inside(path):
    """Resolved path when it is strictly inside the active root, else None."""
    if not active():
        return None
    resolved = os.path.realpath(path)
    if not resolved.startswith(_state["root"] + os.sep):
        return None
    return resolved


def release(path):
    """Remove a directory this process created inside its run root, early.

    Refuses (returns False) a path outside the root, the root itself, a
    symbolic link, and anything that is not a directory.
    """
    if not active():
        return False
    try:
        if os.path.islink(path) or not os.path.isdir(path):
            return False
    except OSError:
        return False
    resolved = _inside(path)
    if resolved is None or resolved != os.path.abspath(path):
        return False
    if _refusal(_state) is not None:
        return False
    return _remove_tree(resolved)


def cleanup():
    """Remove the owned root if it is provably ours; never raises.

    Returns True when the root was removed. Runs at exit; calling it earlier
    ends the run root for the rest of the process.
    """
    global _state
    st = _state
    if st is None or os.getpid() != st["pid"]:
        return False
    removed = False
    try:
        for sig in st["handlers"]:
            try:
                signal.signal(sig, signal.SIG_IGN)
            except (OSError, ValueError):
                pass
        reason = _refusal(st)
        if reason is not None:
            _warn("refusing to remove %s: %s" % (st["root"], reason))
        else:
            try:
                removed = _remove_tree(st["root"])
            except BaseException:
                removed = _remove_tree(st["root"])
            if not removed:
                _warn("could not fully remove %s" % st["root"])
    except BaseException as exc:
        _warn("cleanup error for %s: %r" % (st["root"], exc))
    finally:
        _state = None
        tempfile.tempdir = st["tempdir"]
        if st["env"] is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = st["env"]
        for sig, previous in st["handlers"].items():
            try:
                signal.signal(sig, previous)
            except (OSError, ValueError, TypeError):
                pass
    return removed
