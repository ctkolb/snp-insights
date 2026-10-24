#!/usr/bin/env python3
"""Free, model-free check that a review session left the repository untouched.

Pure standard library. Offline. Only READS git state (status, diff, refs);
it never writes to the repository and never runs a git command that changes
anything. The only file it can write is the snapshot you ask for with `-o`.

Typical use around a reviewer session:

    python scripts/loop_check_clean.py snapshot -o /tmp/before.json
    # ... run the reviewer session ...
    python scripts/loop_check_clean.py check --against /tmp/before.json

Subcommands
  check     Assert the working tree is clean (no staged, unstaged, or
            untracked changes, empty `git diff --stat`). With --against, also
            assert that HEAD, branch, refs, stash, worktrees, .git/config, and
            the set of ignored files match a prior snapshot.
  snapshot  Record that state to a JSON file (store it outside the repo).

Exit status: 0 clean, 1 something changed, 2 usage or git error.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys


def git(repo, *args):
    """Run a read-only git command and return stdout; raise on failure."""
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), proc.stderr.strip()))
    return proc.stdout


def sha(text):
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def ignored_files(repo):
    """Ignored paths, excluding interpreter caches that tests always create."""
    out = git(repo, "status", "--porcelain", "--ignored", "--untracked-files=all")
    paths = []
    for line in out.splitlines():
        if line.startswith("!! "):
            path = line[3:]
            if "__pycache__/" in path or path.endswith(".pyc"):
                continue
            paths.append(path)
    return sorted(paths)


def capture(repo):
    """Collect the state that a read-only session must not change."""
    config_path = os.path.join(repo, ".git", "config")
    try:
        with open(config_path, "r", encoding="utf-8", errors="replace") as fh:
            config_hash = sha(fh.read())
    except OSError:
        config_hash = None  # .git may be a file (worktree); config lives elsewhere
    return {
        "head": git(repo, "rev-parse", "HEAD").strip(),
        "branch": git(repo, "branch", "--show-current").strip(),
        "status": git(repo, "status", "--porcelain", "--untracked-files=all").splitlines(),
        "diff_stat": git(repo, "diff", "--stat", "HEAD").strip(),
        "diff_hash": sha(git(repo, "diff", "HEAD")),
        "refs_hash": sha(git(repo, "for-each-ref", "--format=%(refname) %(objectname)")),
        "stash": git(repo, "stash", "list").splitlines(),
        "worktrees": git(repo, "worktree", "list", "--porcelain").splitlines(),
        "config_hash": config_hash,
        "ignored": ignored_files(repo),
    }


def problems_in(state):
    """Problems that make the tree dirty regardless of any snapshot."""
    found = []
    if state["status"]:
        found.append("working tree not clean (%d entries):" % len(state["status"]))
        found.extend("    " + line for line in state["status"][:20])
    if state["diff_stat"]:
        found.append("git diff --stat HEAD is not empty:")
        found.extend("    " + line for line in state["diff_stat"].splitlines()[:20])
    return found


def compare(before, after):
    """Differences between a snapshot and the current state."""
    found = []
    for key in ("head", "branch", "refs_hash", "config_hash", "diff_hash"):
        if before.get(key) != after.get(key):
            found.append("%s changed: %r -> %r" % (key, before.get(key), after.get(key)))
    for key in ("stash", "worktrees"):
        if before.get(key) != after.get(key):
            found.append("%s changed" % key)
    old, new = set(before.get("ignored", [])), set(after["ignored"])
    for path in sorted(new - old):
        found.append("new ignored file: " + path)
    for path in sorted(old - new):
        found.append("ignored file removed: " + path)
    return found


def cmd_snapshot(args):
    state = capture(args.repo)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("snapshot written: %s (head %s, branch %s)" % (args.output, state["head"][:12], state["branch"]))
    return 0


def cmd_check(args):
    state = capture(args.repo)
    found = problems_in(state)
    if args.against:
        with open(args.against, "r", encoding="utf-8") as fh:
            before = json.load(fh)
        found += compare(before, state)
    if found:
        print("FAIL: repository changed during the session")
        for line in found:
            print("  " + line)
        return 1
    print("OK: working tree clean%s" % (", matches snapshot" if args.against else ""))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", default=".", help="repository to inspect (default: current directory)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    snap = sub.add_parser("snapshot", help="record repository state to a JSON file")
    snap.add_argument("-o", "--output", required=True, help="snapshot path (keep it outside the repo)")
    snap.set_defaults(func=cmd_snapshot)
    chk = sub.add_parser("check", help="assert the tree is clean (and unchanged vs a snapshot)")
    chk.add_argument("--against", help="snapshot JSON from an earlier `snapshot` run")
    chk.set_defaults(func=cmd_check)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, OSError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
