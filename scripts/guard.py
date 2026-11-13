#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Privacy/publication guard for SNP Insights. Deterministic; stdlib only.

This repo mixes application code (safe to publish) with genetic data and derived
artifacts (must stay local). The guard enforces the boundary in layers so a
single skipped step — a stray force-add, a moment of forgetfulness — is caught:

  1. allowlist      every tracked path must be application code/docs/template
  2. data-suffix    data-bearing file types are refused outside known fixtures
  3. large-file     tracked files above a size ceiling are refused
  4. secrets/PII    key shapes, private-key blocks, env assignments, home/cloud
                    paths and internal-hostname patterns
  5. denylist       owner-specific PRIVATE terms (plain or sha256:<hex>), read
                    only from a gitignored file or the SENSITIVE_TERMS env var
  6. gitignore      self-test: sensitive paths ignored, application paths not
  7. history        branch name and the commit messages of an explicit range

Modes:
  --staged   check only what is staged (fast; used by pre-commit)
  --all      check every tracked file (default)
  --full     --all + the .gitignore self-test + the history scan (pre-push/CI)
  --hash T   print sha256:<digest> for T and exit (for building a denylist)

History options (only with an explicit --full):
  --history-base SHA     lowercase 40-hex commit; scan SHA..HEAD (default main..HEAD)
  --history-branch NAME  branch name to scan on a detached HEAD (caller assertion)

Exit status is nonzero if anything is found. Findings print a path and line
only — never a matched secret or private term.
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys

DEFAULT_BRANCH = "main"
MAX_FILE_BYTES = 1_000_000

# --- allowlist --------------------------------------------------------------
# Exact tracked paths that are application/docs/config templates.
ALLOW_EXACT = {
    ".editorconfig",
    ".env.example",
    ".gitattributes",
    ".gitignore",
    ".gitleaks.toml",
    ".mailmap",
    ".sensitive-terms.example",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "DESIGN.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "pyproject.toml",
}
# Prefixes whose whole subtree may be tracked.
ALLOW_PREFIX = (
    ".github/",
    "docs/",
    "hooks/",
    "schema/",
    "scripts/",
    "snp_insights/",
    "stage2/",
    "stage3/",
    "tools/",
    "tests/",
    "harness/",
    "fixtures/",
)
# data/ holds curation + schema + snapshots only; generated panels are ignored.
ALLOW_DATA_RE = re.compile(
    r"^data/(?:condition_aliases\.json|panel\.sample\.json|targets\.[A-Za-z0-9._-]+\.json)$"
)

# --- data-suffix guard ------------------------------------------------------
DATA_SUFFIXES = {
    ".sqlite", ".sqlite3", ".db", ".csv", ".tsv", ".xlsx", ".xls", ".pdf",
    ".parquet", ".feather", ".arrow", ".bam", ".cram", ".vcf", ".vcf.gz",
    ".gz", ".zip", ".tar", ".tgz", ".7z", ".json", ".jsonl", ".ndjson",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp",
    ".mp3", ".mp4", ".mov", ".wav", ".m4a", ".ogg",
    ".photoslibrary", ".numbers", ".pages", ".key",
    ".pem", ".p12", ".pfx", ".kdbx",
}
# Data-bearing suffixes are permitted only inside these (deliberate, synthetic).
DATA_ALLOWED_PREFIX = ("fixtures/", "data/", "schema/", "harness/")

# --- secret / PII patterns --------------------------------------------------
# The guard and its tests deliberately contain decoy strings; they are exempt
# from this scan (see SECRET_SCAN_EXEMPT) so they do not flag themselves.
SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bghp_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b")),
    ("openrouter-key", re.compile(r"\bsk-or-v1-[A-Za-z0-9]{32,}\b")),
    ("home-path-mac", re.compile(r"/Users/[A-Za-z0-9._-]+/")),
    ("home-path-linux", re.compile(r"/home/[A-Za-z0-9._-]+/")),
    ("home-path-windows", re.compile(r"[Cc]:\\Users\\[A-Za-z0-9._-]+")),
    ("cloud-sync-path", re.compile(
        r"Dropbox/|OneDrive/|Google Drive/|iCloud|Library/Mobile Documents")),
    ("internal-host", re.compile(r"\b[\w-]+\.(?:internal|corp)(?:[:/]|$)", re.M)),
    ("env-secret-assignment", re.compile(
        r"(?im)^[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|API_?KEY|PRIVATE_KEY)[A-Z0-9_]*\s*=\s*\S+")),
)
SECRET_SCAN_EXEMPT = {
    "scripts/guard.py",
    "tests/test_guard.py",
    ".sensitive-terms.example",
    ".env.example",
}

# --- .gitignore self-test ---------------------------------------------------
SELFTEST_MUST_BE_IGNORED = (
    ".env",
    ".env.local",
    ".sensitive-terms",
    "secrets.json",
    "data/panel.carrier.json",
    "data/panel.traits.json",
    "fixtures/example.generated.json",
    "notes/private.md",
    "output/report.pdf",
    "__pycache__/x.pyc",
    ".venv/bin/python",
)
SELFTEST_MUST_BE_TRACKED = (
    "stage2/ancestry.py",
    "scripts/guard.py",
    ".gitleaks.toml",
    ".github/workflows/ci.yml",
    "docs/security.md",
    "AGENTS.md",
    "fixtures/raw.sample.txt",
    "data/panel.sample.json",
)
SELFTEST_MUST_NOT_BE_IGNORED = (
    "pyproject.toml",
    "snp_insights/cli.py",
)


def git(*args, check=False):
    proc = subprocess.run(
        ("git",) + args, cwd=repo_root(), capture_output=True, text=True
    )
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


_ROOT = None


def repo_root():
    global _ROOT
    if _ROOT is None:
        out = subprocess.run(
            ("git", "rev-parse", "--show-toplevel"),
            capture_output=True, text=True,
        )
        _ROOT = out.stdout.strip() or os.getcwd()
    return _ROOT


class Finding:
    def __init__(self, check, path, line=None, detail=""):
        self.check = check
        self.path = path
        self.line = line
        self.detail = detail

    def __str__(self):
        loc = f"{self.path}:{self.line}" if self.line else self.path
        tail = f" — {self.detail}" if self.detail else ""
        return f"{loc}: [{self.check}]{tail}"


def _read_text(path):
    try:
        with open(path, "rb") as fh:
            raw = fh.read(8000)
            if b"\x00" in raw:
                return None
            with open(path, "r", encoding="utf-8", errors="replace") as fh2:
                return fh2.read()
    except (OSError, ValueError):
        return None


# --- checks -----------------------------------------------------------------
def check_allowlist(paths):
    findings = []
    for p in paths:
        if p in ALLOW_EXACT:
            continue
        if any(p.startswith(pre) for pre in ALLOW_PREFIX):
            continue
        if ALLOW_DATA_RE.match(p):
            continue
        findings.append(Finding("allowlist", p, detail="tracked path is not allowlisted"))
    return findings


def check_data_suffix(paths):
    findings = []
    for p in paths:
        lower = p.lower()
        suffix = next((s for s in DATA_SUFFIXES if lower.endswith(s)), None)
        if suffix is None:
            continue
        if any(p.startswith(pre) for pre in DATA_ALLOWED_PREFIX):
            continue
        findings.append(Finding(
            "data-suffix", p,
            detail=f"data-bearing '{suffix}' outside a fixtures directory"))
    return findings


def check_large_files(paths):
    findings = []
    root = repo_root()
    for p in paths:
        try:
            size = os.path.getsize(os.path.join(root, p))
        except OSError:
            continue
        if size > MAX_FILE_BYTES:
            findings.append(Finding(
                "large-file", p,
                detail=f"{size} bytes exceeds {MAX_FILE_BYTES}"))
    return findings


def scan_text_for_secrets(text):
    """Return list of (line_number, pattern_name) — never the matched value."""
    hits = []
    for name, rx in SECRET_PATTERNS:
        for m in rx.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            hits.append((line, name))
    return hits


def check_secrets(paths, contents=None):
    findings = []
    root = repo_root()
    for p in paths:
        if p in SECRET_SCAN_EXEMPT:
            continue
        if contents is not None and p in contents:
            text = contents[p]
        else:
            text = _read_text(os.path.join(root, p))
        if text is None:
            continue
        for line, name in scan_text_for_secrets(text):
            findings.append(Finding("secret", p, line, detail=f"looks like {name}"))
    return findings


def load_denylist(root=None):
    """Plain lowercase terms and sha256 hex digests from a gitignored file
    and/or the SENSITIVE_TERMS env var. Never from a tracked file. `root`
    defaults to the cached repository root for legacy callers."""
    raw_lines = []
    local = os.path.join(repo_root() if root is None else root, ".sensitive-terms")
    if os.path.exists(local):
        with open(local, encoding="utf-8", errors="replace") as fh:
            raw_lines.extend(fh.read().splitlines())
    env = os.environ.get("SENSITIVE_TERMS", "")
    if env.strip():
        raw_lines.extend(env.splitlines())
    plain, hashed = [], set()
    for line in raw_lines:
        term = line.strip()
        if not term or term.startswith("#"):
            continue
        if term.startswith("sha256:"):
            digest = term[len("sha256:"):].strip().lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest):
                hashed.add(digest)
            continue
        plain.append(term.lower())
    return plain, hashed


def _sha256(word):
    return hashlib.sha256(word.encode("utf-8")).hexdigest()


def scan_text_for_denylist(text, plain, hashed):
    """Return [(line_number, label)] without revealing the matched term."""
    hits = []
    lowered = text.lower()
    for term in plain:
        start = 0
        while True:
            idx = lowered.find(term, start)
            if idx < 0:
                break
            hits.append((text.count("\n", 0, idx) + 1, "denylist-term"))
            start = idx + len(term)
    if hashed:
        for word in re.findall(r"[A-Za-z0-9]+", lowered):
            if _sha256(word) in hashed:
                hits.append((None, "denylist-hash"))
    return hits


def check_denylist(paths, contents=None):
    plain, hashed = load_denylist()
    if not plain and not hashed:
        return []
    findings = []
    root = repo_root()
    for p in paths:
        if contents is not None and p in contents:
            text = contents[p]
        else:
            text = _read_text(os.path.join(root, p))
        if text is None:
            continue
        for line, label in scan_text_for_denylist(text, plain, hashed):
            findings.append(Finding(label, p, line, detail="owner-specific term"))
    return findings


def check_gitignore_selftest():
    findings = []
    root = repo_root()
    for p in SELFTEST_MUST_BE_IGNORED:
        proc = subprocess.run(
            ("git", "check-ignore", "-q", "--", p), cwd=root, capture_output=True
        )
        if proc.returncode != 0:
            findings.append(Finding(
                "gitignore", p, detail="expected to be gitignored but is not"))
    for p in SELFTEST_MUST_BE_TRACKED:
        proc = subprocess.run(
            ("git", "check-ignore", "-q", "--", p), cwd=root, capture_output=True
        )
        if proc.returncode == 0:
            findings.append(Finding(
                "gitignore", p, detail="application path is ignored"))
            continue
        tracked = subprocess.run(
            ("git", "ls-files", "--error-unmatch", "--", p),
            cwd=root, capture_output=True, text=True,
        )
        if tracked.returncode != 0 and not os.path.exists(os.path.join(root, p)):
            findings.append(Finding(
                "gitignore", p, detail="application path is missing/untracked"))
    for p in SELFTEST_MUST_NOT_BE_IGNORED:
        proc = subprocess.run(
            ("git", "check-ignore", "-q", "--", p), cwd=root, capture_output=True
        )
        if proc.returncode == 0:
            findings.append(Finding(
                "gitignore", p, detail="application path is ignored"))
        elif proc.returncode != 1:
            findings.append(Finding(
                "gitignore", p,
                detail=f"git check-ignore failed (exit {proc.returncode})"))
    return findings


# --- history ----------------------------------------------------------------
# PATH and the git executable it selects are trusted host inputs; git is
# resolved once, here, and every history call uses that executable.
_GIT_EXE = shutil.which("git")
HISTORY_TIMEOUT = 10
_OID_RE = re.compile(r"[0-9a-f]{40}")
HISTORY_LABEL = "history"
ENV_REFUSED = "inherited Git environment not permitted"

# Inherited GIT_* names fall in exactly one class (see docs/security.md):
#   I   ignored, never passed on        II  validated against discovery, dropped
#   III accepted only with a fixed value  IV  everything else is refused
_ENV_IGNORED = frozenset({
    "GIT_PREFIX", "GIT_EXEC_PATH",
    "GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_TEMPLATE_DIR", "GIT_PAGER",
    "GIT_PAGER_IN_USE", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE", "GIT_SSH",
    "GIT_SSH_COMMAND", "GIT_ASKPASS", "GIT_EXTERNAL_DIFF", "GIT_DIFF_OPTS",
    "GIT_TRACE", "GIT_TRACE_SETUP", "GIT_TRACE_PACKET", "GIT_TRACE2",
    "GIT_TRACE2_EVENT", "GIT_TRACE2_PERF",
})
_ENV_VALIDATED = ("GIT_DIR", "GIT_WORK_TREE")
_ENV_FIXED = {
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_CONFIG_GLOBAL": "/dev/null",
}
_EXPECTED_IO = (OSError, subprocess.SubprocessError, UnicodeError)


class _HistoryError(Exception):
    """A history Git step failed; carries only a fixed step name."""

    def __init__(self, step):
        super().__init__(step)
        self.step = step


class _HistoryScan:
    def __init__(self):
        self.findings = []
        self.selected = None
        self.scanned = 0
        self.failed = False
        self.context_missing = False
        self.usage = False
        self.io_failed = False

    @property
    def complete(self):
        return (not self.failed and not self.context_missing and not self.io_failed
                and self.selected is not None and self.scanned == self.selected)

    def receipt(self):
        selected = "unknown" if self.selected is None else str(self.selected)
        return (f"guard: history selected={selected} scanned={self.scanned} "
                f"complete={'yes' if self.complete else 'no'}")

    def fail(self, check, detail):
        self.failed = True
        self.findings.append(Finding(check, HISTORY_LABEL, detail=detail))


def _hgit(step, args, env, cwd, ok=(0,)):
    """Checked Git call: argv list, no shell, no replacement objects, bounded
    time. Returns (returncode, stdout bytes); never exposes stderr or argv."""
    if not _GIT_EXE:
        raise _HistoryError(step)
    argv = [_GIT_EXE, "--no-replace-objects"] + list(args)
    try:
        proc = subprocess.run(
            argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            capture_output=True, timeout=HISTORY_TIMEOUT)
    except _EXPECTED_IO + (ValueError,):
        raise _HistoryError(step) from None
    if proc.returncode not in ok:
        raise _HistoryError(step)
    return proc.returncode, proc.stdout


def _oid(step, out):
    try:
        text = out.decode("ascii")
    except UnicodeError:
        raise _HistoryError(step) from None
    if text.endswith("\n"):
        text = text[:-1]
    if not _OID_RE.fullmatch(text):
        raise _HistoryError(step)
    return text


def _utf8(step, raw):
    try:
        return raw.decode("utf-8")
    except UnicodeError:
        raise _HistoryError(step) from None


def _classify_git_env(environ=None, cwd=None):
    """Classify inherited GIT_* names. Returns (ok, child_env); never mutates
    the process environment and never reports a name, value or path."""
    environ = os.environ if environ is None else environ
    cwd = cwd or os.getcwd()
    child = {k: v for k, v in environ.items() if not k.startswith("GIT_")}
    child["GIT_OPTIONAL_LOCKS"] = "0"
    child["GIT_TERMINAL_PROMPT"] = "0"
    validate = {}
    for name, value in environ.items():
        if not name.startswith("GIT_") or name in _ENV_IGNORED:
            continue
        if name in _ENV_VALIDATED:
            validate[name] = value
        elif name in _ENV_FIXED and value == _ENV_FIXED[name]:
            child[name] = value
        else:
            return False, None
    if validate:
        wanted = {"GIT_DIR": ("rev-parse", "--absolute-git-dir"),
                  "GIT_WORK_TREE": ("rev-parse", "--show-toplevel")}
        try:
            for name, value in validate.items():
                _, out = _hgit("env", wanted[name], child, cwd)
                found = _utf8("env", out).rstrip("\n")
                given = os.path.join(cwd, value)
                if os.path.realpath(given) != os.path.realpath(found):
                    return False, None
        except _HistoryError:
            return False, None
    return True, child


def _child_env_stripped():
    """Environment for Git calls that need no repository: no GIT_* inherited."""
    child = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    child["GIT_OPTIONAL_LOCKS"] = "0"
    child["GIT_TERMINAL_PROMPT"] = "0"
    return child


def _history_root(env, cwd):
    """Repository top level from the pinned runner in the classified child
    environment; the generic PATH helper is never used on the history path."""
    _, out = _hgit("root", ["rev-parse", "--show-toplevel"], env, cwd)
    text = _utf8("root", out)
    if text.endswith("\n"):
        text = text[:-1]
    if not os.path.isabs(text):
        raise _HistoryError("root")
    return text


def _branch_syntax_ok(name):
    return (isinstance(name, str) and name != "" and not name.startswith("-")
            and all(0x20 <= ord(c) != 0x7F for c in name))


def _scan_history(base=None, branch=None):
    scan = _HistoryScan()
    try:
        cwd = os.getcwd()
        ok_env, env = _classify_git_env(None, cwd)
    except _EXPECTED_IO:
        scan.fail("history-git", "history setup could not complete")
        return scan
    if not ok_env:
        scan.fail("history-git", ENV_REFUSED)
        return scan
    try:
        root = _history_root(env, cwd)
    except (_HistoryError,) + _EXPECTED_IO:
        scan.fail("history-git", "repository could not be resolved")
        return scan
    try:
        _scan_history_body(scan, env, root, base, branch)
    except _HistoryError as exc:
        scan.fail("history-git", f"Git step failed: {exc.step}")
    return scan


def _scan_history_body(scan, env, root, base, branch):
    def run(step, args, ok=(0,)):
        return _hgit(step, args, env, root, ok)

    head = _oid("head", run("head", ["rev-parse", "--verify", "--end-of-options",
                                     "HEAD^{commit}"])[1])
    rc, out = run("symbolic-ref", ["symbolic-ref", "--quiet", "HEAD"], ok=(0, 1))
    attached = None
    if rc == 0:
        ref = _utf8("symbolic-ref", out).rstrip("\n")
        if not ref.startswith("refs/heads/") or ref == "refs/heads/":
            raise _HistoryError("symbolic-ref")
        attached = ref[len("refs/heads/"):]
    if attached is not None:
        if branch is not None:
            scan.usage = True
            scan.fail("history-context", "branch context not allowed for an attached HEAD")
            return
        name = attached
    elif branch is None:
        scan.context_missing = True
        scan.findings.append(Finding(
            "history-context", HISTORY_LABEL, detail="detached HEAD without branch context"))
        name = None
    elif _branch_syntax_ok(branch):
        name = branch
    else:
        raise _HistoryError("branch-context")
    try:
        plain, hashed = load_denylist(root)
    except _EXPECTED_IO:
        scan.fail("history-git", "denylist could not be read")
        return
    if name is not None and (plain or hashed):
        for _, label in scan_text_for_denylist(name, plain, hashed):
            scan.findings.append(Finding(label, "branch", detail="owner-specific term"))

    if _oid_text(run("shallow", ["rev-parse", "--is-shallow-repository"])[1]) != "false":
        raise _HistoryError("shallow")
    if base is None:
        spec = "refs/heads/" + DEFAULT_BRANCH + "^{commit}"
    elif _OID_RE.fullmatch(base):
        spec = base + "^{commit}"
    else:
        raise _HistoryError("base-syntax")
    base_oid = _oid("base", run("base", ["rev-parse", "--verify", "--end-of-options", spec])[1])
    if run("ancestry", ["merge-base", "--is-ancestor", base_oid, head], ok=(0, 1))[0] != 0:
        raise _HistoryError("ancestry")
    rng = f"{base_oid}..{head}"
    listed = run("enumerate", ["rev-list", rng])[1]
    oids = [_oid("enumerate", line) for line in listed.splitlines()]
    counted = _oid_text(run("count", ["rev-list", "--count", rng])[1])
    if not counted.isascii() or not counted.isdigit() or int(counted) != len(oids):
        raise _HistoryError("count")
    scan.selected = len(oids)

    for oid in oids:
        try:
            _, raw = run("message", ["show", "-s", "--no-show-signature",
                                     "--format=%B", oid])
            text = _utf8("message", raw)
        except _HistoryError as exc:
            scan.fail("history-git", f"Git step failed: {exc.step}")
            continue
        for _, name_ in scan_text_for_secrets(text):
            scan.findings.append(Finding(
                "history-secret", "commit message", detail=f"looks like {name_}"))
        if plain or hashed:
            for _, label in scan_text_for_denylist(text, plain, hashed):
                scan.findings.append(Finding(label, "commit message", detail="owner-specific term"))
        scan.scanned += 1

    moved = _oid("head", run("head", ["rev-parse", "--verify", "--end-of-options",
                                      "HEAD^{commit}"])[1]) != head
    rc2, out2 = run("symbolic-ref", ["symbolic-ref", "--quiet", "HEAD"], ok=(0, 1))
    state = _utf8("symbolic-ref", out2).rstrip("\n") if rc2 == 0 else None
    moved = moved or state != (None if attached is None else "refs/heads/" + attached)
    if base is None:
        again = _oid("base", run("base", ["rev-parse", "--verify", "--end-of-options",
                                          spec])[1])
        moved = moved or again != base_oid
    if moved:
        scan.fail("history-context", "HEAD or base changed during the scan")


def _oid_text(out):
    try:
        return out.decode("ascii").strip()
    except UnicodeError:
        raise _HistoryError("output") from None


def check_history(history_base=None, history_branch=None):
    return _scan_history(history_base, history_branch).findings


# --- modes ------------------------------------------------------------------
def _staged_paths():
    out = git("diff", "--cached", "--name-only", "--diff-filter=ACM")
    return [p for p in out.splitlines() if p]


def _staged_contents(paths):
    contents = {}
    for p in paths:
        proc = subprocess.run(
            ("git", "show", f":{p}"), cwd=repo_root(), capture_output=True, text=True
        )
        if proc.returncode == 0 and "\x00" not in proc.stdout[:8000]:
            contents[p] = proc.stdout
    return contents


def _tracked_paths():
    return [p for p in git("ls-files").splitlines() if p]


def run_paths(paths, contents=None):
    findings = []
    findings += check_allowlist(paths)
    findings += check_data_suffix(paths)
    findings += check_secrets(paths, contents)
    findings += check_denylist(paths, contents)
    return findings


def run_staged():
    paths = _staged_paths()
    return run_paths(paths, _staged_contents(paths))


def run_all():
    paths = _tracked_paths()
    findings = run_paths(paths)
    findings += check_large_files(paths)
    return findings


def _run_full(history_base=None, history_branch=None):
    findings, io_failed = [], False
    for label, layer in (("tracked-file checks", run_all),
                         (".gitignore self-test", check_gitignore_selftest)):
        try:
            findings += layer()
        except _EXPECTED_IO:
            io_failed = True
            findings.append(Finding("guard-io", "guard", detail=f"{label} could not complete"))
    scan = _scan_history(history_base, history_branch)
    scan.io_failed = io_failed
    return findings + scan.findings, scan


def run_full(history_base=None, history_branch=None):
    return _run_full(history_base, history_branch)[0]


USAGE = ("usage: guard.py [--staged | --all | --full] "
         "[--history-base SHA] [--history-branch NAME] [--hash TERM]")


class _FixedParser(argparse.ArgumentParser):
    """Argument errors never echo user input: fixed text and exit status 2."""

    history_requested = False

    def error(self, message):
        _usage_error(self.history_requested)


def _usage_error(history_requested):
    if history_requested:
        print(_HistoryScan().receipt())
    print(USAGE, file=sys.stderr)
    print("guard: invalid arguments", file=sys.stderr)
    raise SystemExit(2)


def main(argv=None):
    parser = _FixedParser(prog="guard.py", allow_abbrev=False,
                          description="SNP Insights privacy/publication guard")
    parser.history_requested = any(
        a.startswith("--history") for a in (sys.argv[1:] if argv is None else argv))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--staged", action="store_true", help="check staged files only")
    group.add_argument("--all", action="store_true", help="check every tracked file (default)")
    group.add_argument("--full", action="store_true",
                       help="--all + .gitignore self-test + history scan")
    parser.add_argument("--hash", metavar="TERM",
                        help="print sha256:<digest> for TERM and exit")
    parser.add_argument("--history-base", metavar="SHA",
                        help="with --full: scan SHA..HEAD (lowercase 40-hex commit)")
    parser.add_argument("--history-branch", metavar="NAME",
                        help="with --full on a detached HEAD: branch name to scan")
    args = parser.parse_args(argv)

    history_opts = args.history_base is not None or args.history_branch is not None
    if history_opts and (not args.full or args.hash is not None):
        _usage_error(True)
    if args.history_base is not None and not _OID_RE.fullmatch(args.history_base):
        _usage_error(True)
    if args.history_branch is not None:
        if not _branch_syntax_ok(args.history_branch):
            _usage_error(True)
        try:
            rc, _ = _hgit("check-ref-format",
                          ["check-ref-format", "refs/heads/" + args.history_branch],
                          _child_env_stripped(), os.getcwd(), ok=(0, 1))
        except _HistoryError as exc:
            scan = _HistoryScan()
            scan.fail("history-git", f"Git step failed: {exc.step}")
            print(scan.receipt())
            print(f"  {scan.findings[0]}", file=sys.stderr)
            return 1
        except _EXPECTED_IO:
            scan = _HistoryScan()
            scan.fail("history-git", "history setup could not complete")
            print(scan.receipt())
            print(f"  {scan.findings[0]}", file=sys.stderr)
            return 1
        if rc != 0:
            _usage_error(True)

    if args.hash is not None:
        print("sha256:" + _sha256(args.hash.strip().lower()))
        return 0

    scan = None
    if args.staged:
        findings = run_staged()
        scope = "staged files"
    elif args.full:
        findings, scan = _run_full(args.history_base, args.history_branch)
        scope = "full (tracked files + gitignore self-test + history)"
        if scan.usage:
            _usage_error(True)
        print(scan.receipt())
    else:
        findings = run_all()
        scope = "all tracked files"

    if findings:
        print(f"guard: {len(findings)} finding(s) in {scope}\n", file=sys.stderr)
        for f in findings:
            print(f"  {f}", file=sys.stderr)
        print("\nFix the input, or change a rule deliberately with owner approval — "
              "never weaken the guard to make a commit pass.", file=sys.stderr)
        return 1
    print(f"guard: clean ({scope})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
