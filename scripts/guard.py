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
  7. history        branch name, staged diff, and commit messages since main

Modes:
  --staged   check only what is staged (fast; used by pre-commit)
  --all      check every tracked file (default)
  --full     --all + the .gitignore self-test + the history scan (pre-push/CI)
  --hash T   print sha256:<digest> for T and exit (for building a denylist)

Exit status is nonzero if anything is found. Findings print a path and line
only — never a matched secret or private term.
"""
import argparse
import hashlib
import os
import re
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


def load_denylist():
    """Plain lowercase terms and sha256 hex digests from a gitignored file
    and/or the SENSITIVE_TERMS env var. Never from a tracked file."""
    raw_lines = []
    local = os.path.join(repo_root(), ".sensitive-terms")
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


def check_history():
    findings = []
    plain, hashed = load_denylist()
    root = repo_root()
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    if plain or hashed:
        for line, label in scan_text_for_denylist(branch, plain, hashed):
            findings.append(Finding(label, f"branch {branch}", detail="owner-specific term"))
    base = f"{DEFAULT_BRANCH}..HEAD"
    proc = subprocess.run(
        ("git", "log", "--format=%H%n%B%n<<>>", base),
        cwd=root, capture_output=True, text=True,
    )
    messages = proc.stdout if proc.returncode == 0 else ""
    for line, name in scan_text_for_secrets(messages):
        findings.append(Finding("history-secret", "commit message", detail=f"looks like {name}"))
    if plain or hashed:
        for line, label in scan_text_for_denylist(messages, plain, hashed):
            findings.append(Finding(label, "commit message", detail="owner-specific term"))
    return findings


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


def run_full():
    findings = run_all()
    findings += check_gitignore_selftest()
    findings += check_history()
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description="SNP Insights privacy/publication guard")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--staged", action="store_true", help="check staged files only")
    group.add_argument("--all", action="store_true", help="check every tracked file (default)")
    group.add_argument("--full", action="store_true",
                       help="--all + .gitignore self-test + history scan")
    parser.add_argument("--hash", metavar="TERM",
                        help="print sha256:<digest> for TERM and exit")
    args = parser.parse_args(argv)

    if args.hash is not None:
        print("sha256:" + _sha256(args.hash.strip().lower()))
        return 0

    if args.staged:
        findings = run_staged()
        scope = "staged files"
    elif args.full:
        findings = run_full()
        scope = "full (tracked files + gitignore self-test + history)"
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
