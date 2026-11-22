#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Read-only temporary-directory leak audit. Standard library only.

Point it at a dedicated, empty parent directory (never the system temp
directory, which other programs share). It never creates, changes or removes
anything inside the parent; it only lists the parent's top level and sizes
each entry without following symbolic links.

    python -B scripts/tmp_audit.py snap PARENT [-o FILE]
    python -B scripts/tmp_audit.py diff BEFORE.json AFTER.json
    python -B scripts/tmp_audit.py run --parent PARENT [--max-new N]
        [--interrupt-after SECONDS --signal KILL|TERM|INT|HUP] [--group]
        [--sample-peak] [--json FILE] -- COMMAND [ARGS...]

`run` snapshots PARENT, runs COMMAND with TMPDIR=PARENT, optionally signals it
after a delay, snapshots again, prints one "new: NAME" line per new entry and a
final "AUDIT {json}" summary line. Exit codes: 0 clean, 1 more new entries than
--max-new (default 0), 2 the command failed (not counting a requested signal),
64 usage error.
"""
import argparse
import json
import os
import signal
import stat
import subprocess
import sys
import threading
import time


def _size(path):
    """(files, bytes) under path, from lstat only; symbolic links count as files."""
    try:
        st = os.lstat(path)
    except OSError:
        return 0, 0
    if not stat.S_ISDIR(st.st_mode):
        return 1, st.st_size
    files = total = 0
    for dp, dns, fns in os.walk(path, followlinks=False, onerror=lambda e: None):
        for n in fns + [d for d in dns if os.path.islink(os.path.join(dp, d))]:
            try:
                total += os.lstat(os.path.join(dp, n)).st_size
                files += 1
            except OSError:
                pass
    return files, total


def snap(parent):
    """Top-level picture of parent: {name: {type, files, bytes}}."""
    entries = {}
    with os.scandir(parent) as it:
        for e in it:
            try:
                mode = os.lstat(e.path).st_mode
            except OSError:
                continue
            kind = "link" if stat.S_ISLNK(mode) else "dir" if stat.S_ISDIR(mode) else "file"
            files, size = _size(e.path)
            entries[e.name] = {"type": kind, "files": files, "bytes": size}
    return {"parent": os.path.realpath(parent), "entries": entries}


def diff(before, after):
    old, new = before["entries"], after["entries"]
    added = sorted(set(new) - set(old))
    return {
        "new_entries": added,
        "removed_entries": sorted(set(old) - set(new)),
        "new_count": len(added),
        "new_files": sum(new[n]["files"] for n in added),
        "new_bytes": sum(new[n]["bytes"] for n in added),
    }


def _total_bytes(parent):
    return sum(_size(os.path.join(parent, n))[1] for n in os.listdir(parent))


def _peak_sampler(parent, stop, out):
    while not stop.is_set():
        try:
            out["peak_bytes"] = max(out["peak_bytes"], _total_bytes(parent))
        except OSError:
            pass
        stop.wait(0.5)


def run(args):
    parent = os.path.realpath(args.parent)
    if not os.path.isdir(parent):
        print("tmp_audit: parent is not a directory: %s" % parent, file=sys.stderr)
        return 64
    if not args.command:
        print("tmp_audit: no command after --", file=sys.stderr)
        return 64
    before = snap(parent)
    env = dict(os.environ)
    env["TMPDIR"] = parent
    sent = None
    peak = {"peak_bytes": 0}
    stop = threading.Event()
    sampler = None
    t0 = time.monotonic()
    # A shell's background job inherits SIGINT ignored; restore the default so
    # that an INT measurement interrupts the command as Ctrl-C would.
    proc = subprocess.Popen(args.command, env=env, start_new_session=args.group,
                            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    if args.sample_peak:
        sampler = threading.Thread(target=_peak_sampler, args=(parent, stop, peak), daemon=True)
        sampler.start()
    try:
        if args.interrupt_after is not None:
            try:
                proc.wait(timeout=args.interrupt_after)
            except subprocess.TimeoutExpired:
                sig = getattr(signal, "SIG" + args.signal)
                if args.group:
                    os.killpg(proc.pid, sig)
                else:
                    proc.send_signal(sig)
                sent = args.signal
        rc = proc.wait()
    finally:
        stop.set()
        if sampler is not None:
            sampler.join()
    seconds = round(time.monotonic() - t0, 1)
    after = snap(parent)
    result = diff(before, after)
    for name in result["new_entries"]:
        print("new: %s" % name)
    result.update({"rc": rc, "signal": sent, "seconds": seconds, "parent": parent,
                   "command": args.command, "max_new": args.max_new})
    if args.sample_peak:
        result["peak_bytes"] = peak["peak_bytes"]
    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"before": before, "after": after, "result": result}, fh, indent=1)
    print("AUDIT " + json.dumps(result, sort_keys=True), flush=True)
    if result["new_count"] > args.max_new:
        return 1
    if rc != 0 and sent is None:
        return 2
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_snap = sub.add_parser("snap")
    p_snap.add_argument("parent")
    p_snap.add_argument("-o", "--output")
    p_diff = sub.add_parser("diff")
    p_diff.add_argument("before")
    p_diff.add_argument("after")
    p_run = sub.add_parser("run")
    p_run.add_argument("--parent", required=True)
    p_run.add_argument("--max-new", type=int, default=0)
    p_run.add_argument("--interrupt-after", type=float)
    p_run.add_argument("--signal", default="TERM", choices=("KILL", "TERM", "INT", "HUP"))
    p_run.add_argument("--group", action="store_true",
                       help="run the command in its own session and signal the whole group")
    p_run.add_argument("--sample-peak", action="store_true")
    p_run.add_argument("--json")
    p_run.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    if args.cmd == "snap":
        doc = snap(args.parent)
        text = json.dumps(doc, indent=1, sort_keys=True)
        if args.output:
            with open(args.output, "w") as fh:
                fh.write(text + "\n")
        else:
            print(text)
        return 0
    if args.cmd == "diff":
        with open(args.before) as fh:
            before = json.load(fh)
        with open(args.after) as fh:
            after = json.load(fh)
        result = diff(before, after)
        for name in result["new_entries"]:
            print("new: %s" % name)
        print("AUDIT " + json.dumps(result, sort_keys=True))
        return 1 if result["new_count"] else 0
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
