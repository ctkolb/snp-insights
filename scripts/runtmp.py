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
process removes it, never a forked child. The removal itself is bound to that
device and inode: it works through directory descriptors that never follow a
symbolic link, changes permissions only on directories inside the tree, and
never changes the parent. Anything else is left in place and reported on
stderr as "runtmp: refusing ...".
"""
import atexit
import json
import os
import re
import secrets
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


_DIR_FLAGS = (os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
              | getattr(os, "O_CLOEXEC", 0))


class _Refused(Exception):
    """A directory being removed no longer is the one that was checked."""


def _open_dir(name, dir_fd):
    """Open a directory entry relative to dir_fd; a symbolic link fails."""
    return os.open(name, _DIR_FLAGS, dir_fd=dir_fd)


def _open_checked(name, dir_fd, expect=None):
    """Open directory name under dir_fd, bound to the inode that was opened.

    After the open, the descriptor must be the directory expect (when given),
    and name must still resolve, without following a link, to the same device
    and inode as the descriptor. A directory renamed away or replaced after
    the open is refused before anything is removed through the descriptor.
    """
    fd = _open_dir(name, dir_fd)
    try:
        info = os.fstat(fd)
        if expect is not None and not _same(info, expect):
            raise _Refused("%s was replaced by another directory" % name)
        try:
            now = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            raise _Refused("%s was moved after it was opened" % name)
        if not _same(now, (info.st_dev, info.st_ino)):
            raise _Refused("%s no longer names the opened directory" % name)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _onexc(func, path, exc):
    """Error policy for one failed removal step; never touches the filesystem.

    True when the step can be ignored (the entry is already gone), False when it
    failed. Permission is repaired only through descriptors inside the tree
    being removed (see _clear), never through a path, so there is nothing to
    retry here; func and path are accepted for the onexc calling convention.
    """
    return isinstance(exc, FileNotFoundError)


def _same(st, ident):
    return (st.st_dev, st.st_ino) == ident


def _rmdir_checked(dir_fd, name, ident):
    """rmdir name under dir_fd only while it is still the directory ident.

    rmdir removes only an empty directory, so the window between this check
    and the rmdir can at worst remove an empty directory swapped in there.
    """
    if not _same(os.stat(name, dir_fd=dir_fd, follow_symlinks=False), ident):
        raise _Refused("%s was replaced during removal" % name)
    os.rmdir(name, dir_fd=dir_fd)


def _repair_dir(dir_fd, name, expect):
    """Give the owner rwx on subdirectory name without following a link."""
    st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    if not stat.S_ISDIR(st.st_mode):
        raise PermissionError("not a directory: %s" % name)
    if not _same(st, expect):
        raise _Refused("%s was replaced by another directory" % name)
    try:
        os.chmod(name, stat.S_IMODE(st.st_mode) | stat.S_IRWXU, dir_fd=dir_fd,
                 follow_symlinks=False)
    except NotImplementedError:
        raise PermissionError("cannot change %s without following links" % name)


def _remove_subdir(dir_fd, name, expect=None):
    """Remove subdirectory name of dir_fd, which was listed as inode expect."""
    if expect is None:
        raise _Refused("%s has no recorded identity" % name)
    try:
        fd = _open_checked(name, dir_fd, expect)
    except PermissionError:
        _repair_dir(dir_fd, name, expect)
        fd = _open_checked(name, dir_fd, expect)
    try:
        empty = _clear(fd)
    finally:
        os.close(fd)
    if not empty:
        raise PermissionError("could not empty %s" % name)
    _rmdir_checked(dir_fd, name, expect)


def _clear(dir_fd):
    """Remove every entry of the open directory dir_fd; True when it is empty.

    Works only through descriptors: a symbolic link is unlinked, never
    followed, and a permission failure is repaired with fchmod on dir_fd
    itself, which is inside the tree being removed.
    """
    for attempt in range(2):
        failed = False
        entries = []
        with os.scandir(dir_fd) as it:
            for e in it:
                ident = None
                if e.is_dir(follow_symlinks=False):
                    try:
                        listed = e.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    except OSError:
                        failed = True
                        continue
                    ident = (listed.st_dev, listed.st_ino)
                entries.append((e.name, ident))
        for name, ident in entries:
            try:
                if ident is not None:
                    _remove_subdir(dir_fd, name, ident)
                else:
                    os.unlink(name, dir_fd=dir_fd)
            except OSError as exc:
                if not _onexc(os.unlink, name, exc):
                    failed = True
        if not failed:
            return True
        if attempt == 0:
            os.fchmod(dir_fd, stat.S_IMODE(os.fstat(dir_fd).st_mode) | stat.S_IRWXU)
    return False


def _remove_tree(path, expect=None):
    """Remove the active root, or a directory inside it, bound to one inode.

    The directory is reached from a descriptor of the recorded parent (and,
    below the root, through descriptors that never follow a symbolic link),
    and its device and inode must equal expect: for the root, the identity
    recorded at activation. Each directory is checked again right after it is
    opened (see _open_checked) and each subdirectory against the identity it
    was listed with, before anything is removed through its descriptor. Its
    contents are removed through that descriptor, so a directory swapped in at
    the same path, or renamed away after the open, is never touched. Removing the
    root never changes the recorded parent: a parent this process cannot write
    to leaves the root in place. Returns True when removed; anything that no
    longer matches leaves the tree and prints "runtmp: refusing ...".
    """
    st = _state
    if st is None or os.getpid() != st["pid"]:
        return False
    root_ident = (st["dev"], st["ino"])
    is_root = path == st["root"]
    if expect is None and is_root:
        expect = root_ident
    rel = os.path.relpath(path, st["root"]).split(os.sep)
    if expect is None or (not is_root and (not _inside(path) or "." in rel or ".." in rel)):
        _warn("refusing to remove %s: not a checked directory of the run root" % path)
        return False
    if is_root and not os.access(st["parent"], os.W_OK | os.X_OK):
        _warn("refusing to remove %s: parent directory is not writable" % path)
        return False
    opened = []
    try:
        opened.append(os.open(st["parent"], _DIR_FLAGS))
        name = st["name"]
        if not is_root:
            opened.append(_open_checked(name, opened[-1], root_ident))
            for part in rel[:-1]:
                opened.append(_open_checked(part, opened[-1]))
            name = rel[-1]
        anchor = opened[-1]
        for _ in range(5):
            try:
                fd = _open_checked(name, anchor, expect)
            except FileNotFoundError:
                return True
            try:
                empty = _clear(fd)
            finally:
                os.close(fd)
            if empty:
                try:
                    _rmdir_checked(anchor, name, expect)
                    return True
                except FileNotFoundError:
                    return True
                except PermissionError:
                    if is_root:
                        raise _Refused("parent directory is not writable")
                    os.fchmod(anchor, stat.S_IMODE(os.fstat(anchor).st_mode) | stat.S_IRWXU)
                except OSError:
                    pass
            time.sleep(0.05)
        _warn("could not fully remove %s" % path)
        return False
    except _Refused as exc:
        _warn("refusing to remove %s: %s" % (path, exc))
        return False
    except OSError as exc:
        _warn("refusing to remove %s: %s" % (path, exc))
        return False
    finally:
        for fd in reversed(opened):
            os.close(fd)


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
    symbolic link, anything that is not a directory, and any spelling with a
    "." or ".." component or a trailing separator. Removal is bound to the
    device and inode seen here (see _remove_tree).
    """
    if not active():
        return False
    raw = os.fspath(path)
    if raw.endswith(os.sep):
        return False
    if any(part in (".", "..") for part in raw.split(os.sep)):
        return False
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        return False
    resolved = _inside(path)
    if resolved is None or resolved != os.path.abspath(path):
        return False
    if _refusal(_state) is not None:
        return False
    return _remove_tree(resolved, (info.st_dev, info.st_ino))


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
