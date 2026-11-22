#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""List-only sweep for leftover run roots. Read-only; it never deletes anything.

    python -B scripts/tmp_sweep.py [--parent DIR] [--json] [--show-legacy] [--fail-on-stale]

Reads only the top level of DIR (default: the current temp directory) and
classifies every entry whose name starts with "snp-insights-run-":

  live     a valid marker whose process is still running (or cannot be
           checked); never eligible
  stale    a valid marker whose process has ended; eligible for the manual
           removal procedure in docs/test-temp-cleanup.md
  invalid  the name matches but the entry is not a real directory owned by
           you with a valid marker (a symbolic link, a plain file, another
           user's directory, a missing or malformed marker); reported, never
           eligible

Entries left by older test runs (other "snp-insights-", "r2e-" and "loop-mut-"
names) are counted on one line, never listed as eligible, and stay
owner-managed; --show-legacy prints their names. Exit 0, or 3 with
--fail-on-stale when any stale root is listed.
"""
import argparse
import json
import os
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runtmp  # noqa: E402

LEGACY_PREFIXES = ("snp-insights-", "r2e-", "loop-mut-")


def classify(parent, name):
    """(state, reason, pid) for one top-level run-root candidate."""
    path = os.path.join(parent, name)
    try:
        info = os.lstat(path)
    except OSError as exc:
        return "invalid", "unreadable (%s)" % exc.__class__.__name__, None
    if stat.S_ISLNK(info.st_mode):
        return "invalid", "symbolic link", None
    if not stat.S_ISDIR(info.st_mode):
        return "invalid", "not a directory", None
    if info.st_uid != os.getuid():
        return "invalid", "owned by another user", None
    if not runtmp.NAME_RE.match(name):
        return "invalid", "unexpected name", None
    doc = runtmp.read_marker(path)
    if doc is None:
        return "invalid", "marker missing or unreadable", None
    pid = doc.get("pid")
    if doc.get("schema") != runtmp.SCHEMA:
        return "invalid", "unknown marker schema", None
    if doc.get("uid") != os.getuid():
        return "invalid", "marker names another user", None
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return "invalid", "marker pid is not a process id", None
    state = runtmp.pid_state(pid)
    if state == "dead":
        return "stale", "process %d has ended" % pid, pid
    if state == "alive":
        return "live", "process %d is running" % pid, pid
    return "live", "process %d could not be checked" % pid, pid


def sweep(parent, show_legacy=False):
    parent = os.path.realpath(parent)
    entries, legacy = [], []
    for name in sorted(os.listdir(parent)):
        if name.startswith(runtmp.PREFIX):
            state, reason, pid = classify(parent, name)
            entries.append({"name": name, "path": os.path.join(parent, name),
                            "state": state, "reason": reason, "pid": pid})
        elif name.startswith(LEGACY_PREFIXES):
            legacy.append(name)
    doc = {"parent": parent, "entries": entries,
           "eligible": [e["path"] for e in entries if e["state"] == "stale"],
           "legacy_count": len(legacy)}
    if show_legacy:
        doc["legacy"] = legacy
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description="List-only sweep for leftover run roots.")
    ap.add_argument("--parent", default=None, help="directory to read (default: temp dir)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show-legacy", action="store_true")
    ap.add_argument("--fail-on-stale", action="store_true")
    args = ap.parse_args(argv)
    parent = args.parent if args.parent is not None else tempfile.gettempdir()
    doc = sweep(parent, args.show_legacy)
    if args.json:
        print(json.dumps(doc, indent=1, sort_keys=True))
    else:
        for e in doc["entries"]:
            print("%s\t%s\t%s" % (e["state"], e["path"], e["reason"]))
        print("%d eligible (stale) of %d run roots under %s" % (
            len(doc["eligible"]), len(doc["entries"]), doc["parent"]))
        print("%d legacy-pattern entries, owner-managed, never eligible" % doc["legacy_count"])
        for name in doc.get("legacy", []):
            print("legacy\t%s" % os.path.join(doc["parent"], name))
    return 3 if args.fail_on_stale and doc["eligible"] else 0


if __name__ == "__main__":
    sys.exit(main())
