#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Tests for scripts/guard.py. No framework.

Run standalone:  python tests/test_guard.py
Or as part of:   python tests/test_pipeline.py

Each check has at least one positive and one negative case so the guard's rules
cannot silently rot. The decoy strings here are why the guard exempts this file
from its own secret scan.
"""
import contextlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import guard  # noqa: E402

S3_PACKAGE_PATHS = ("pyproject.toml", "snp_insights/cli.py")


def _temp_gitignore_repo(gitignore_text):
    tmp = tempfile.mkdtemp(prefix="snp-insights-s3-")
    subprocess.run(("git", "init", "-q"), cwd=tmp, check=True)
    with open(os.path.join(tmp, ".gitignore"), "w", encoding="utf-8") as fh:
        fh.write(gitignore_text)
    return tmp


def _selftest_for(tmp):
    old = guard._ROOT
    guard._ROOT = tmp
    try:
        return guard.check_gitignore_selftest()
    finally:
        guard._ROOT = old


def _new_path_findings(findings):
    return [f for f in findings if f.path in S3_PACKAGE_PATHS]


def _touch(repo, rel):
    full = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write("")


def _real_gitignore_text():
    with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as fh:
        return fh.read()


PACKAGE_IGNORE_PATHS = (
    "snp_insights/.env",
    "snp_insights/.env.local",
    "snp_insights/.sensitive-terms",
    "snp_insights/x.pyc",
    "snp_insights/__pycache__",
    "snp_insights/y.private",
    "snp_insights/z.local",
    "snp_insights/a.generated.json",
)


def _package_ignore_map(gitignore_text):
    repo = _temp_gitignore_repo(gitignore_text)
    try:
        for path in PACKAGE_IGNORE_PATHS:
            if path.endswith("__pycache__"):
                os.makedirs(os.path.join(repo, path), exist_ok=True)
            else:
                _touch(repo, path)
        return {p: _is_ignored(repo, p) for p in PACKAGE_IGNORE_PATHS}
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def _is_ignored(repo, path):
    proc = subprocess.run(
        ("git", "check-ignore", "-q", "--", path), cwd=repo, capture_output=True
    )
    return proc.returncode == 0


# --- synthetic history repositories (HG-*) ----------------------------------
HG_SENTINEL = "zzsentinelterm"
HG_CANARY = "AKIA" + "B" * 16


def _fixture_env(home):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({
        "HOME": home, "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_AUTHOR_NAME": "Test Author", "GIT_AUTHOR_EMAIL": "author@example.invalid",
        "GIT_COMMITTER_NAME": "Test Author", "GIT_COMMITTER_EMAIL": "author@example.invalid",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    })
    return env


def _fx(repo, *args, check_rc=True, text=True):
    proc = subprocess.run(
        ("git", "-c", "gc.auto=0", "-c", "commit.gpgsign=false") + args, cwd=repo,
        env=_fixture_env(os.path.join(repo, ".home") if os.path.isdir(repo) else repo),
        capture_output=True, text=text)
    if check_rc and proc.returncode != 0:
        raise RuntimeError("fixture git failed")
    return proc.stdout.strip() if text else proc.stdout


def _hg_repo(prefix="snp-insights-hg-"):
    """A synthetic repository with one commit on `main`; returns its path."""
    repo = tempfile.mkdtemp(prefix=prefix)
    os.makedirs(os.path.join(repo, ".home"))
    _fx(repo, "init", "-q")
    _fx(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _hg_commit(repo, "base commit")
    return repo


def _hg_commit(repo, message, name="f.txt"):
    os.makedirs(os.path.dirname(os.path.join(repo, name)), exist_ok=True)
    with open(os.path.join(repo, name), "a", encoding="utf-8") as fh:
        fh.write(message + "\n")
    _fx(repo, "add", "-f", "--", name)
    _fx(repo, "commit", "-q", "-m", message)
    return _fx(repo, "rev-parse", "HEAD")


@contextlib.contextmanager
def _guard_ctx(repo, denylist=None):
    """Point the guard at a synthetic repository with a scrubbed Git environment;
    every global it touches is restored in `finally`."""
    old_root, old_env, old_load = guard._ROOT, dict(os.environ), guard.load_denylist
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        del os.environ[key]
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    os.environ["GIT_CONFIG_GLOBAL"] = "/dev/null"
    guard._ROOT = repo
    if denylist is not None:
        guard.load_denylist = lambda: denylist
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old_env)
        guard._ROOT = old_root
        guard.load_denylist = old_load


def _hg_findings(repo, denylist=None, **kwargs):
    with _guard_ctx(repo, denylist):
        return guard.check_history(**kwargs)


def _hg_labels(findings):
    return sorted({f.check for f in findings})


def _history_synthetic(check):
    """Replaces the former assertion against this repository's live history.

    Positive controls pin behavior that must hold before and after the history
    hardening; the `red` cases assert the corrected behavior (HG-01/04/06)."""
    def repo_with(*messages, branch="feature"):
        repo = _hg_repo()
        if messages:
            _fx(repo, "switch", "-q", "-c", branch)
            for m in messages:
                _hg_commit(repo, m)
        return repo

    # CHARACTERIZATION: valid attached nonempty clean, genuine empty clean.
    r = repo_with("clean synthetic message")
    check("HG.pos.attached_nonempty_clean", _hg_findings(r) == [])
    r = repo_with()
    check("HG.pos.empty_range_clean", _hg_findings(r) == [])
    # CHARACTERIZATION: message and branch hits (labels only, never values).
    r = repo_with("leak " + HG_CANARY)
    check("HG.pos.msg_secret", "history-secret" in _hg_labels(_hg_findings(r)))
    r = repo_with("mentions " + HG_SENTINEL)
    check("HG.pos.msg_plain",
          "denylist-term" in _hg_labels(_hg_findings(r, ([HG_SENTINEL], set()))))
    r = repo_with("visit Wonderland today")
    check("HG.pos.msg_hash",
          "denylist-hash" in _hg_labels(_hg_findings(r, ([], {guard._sha256("wonderland")}))))
    r = repo_with("clean message", branch="feature-" + HG_SENTINEL)
    check("HG.pos.branch_plain",
          "denylist-term" in _hg_labels(_hg_findings(r, ([HG_SENTINEL], set()))))
    r = repo_with("clean message", branch="visit-wonderland-x")
    check("HG.pos.branch_hash",
          "denylist-hash" in _hg_labels(_hg_findings(r, ([], {guard._sha256("wonderland")}))))

    # FAILING reds against the pre-hardening API.
    plain = tempfile.mkdtemp(prefix="snp-insights-hg-")
    check("HG.red.nonrepo_history_git",
          "history-git" in _hg_labels(_hg_findings(plain)))
    r = repo_with("work")
    _fx(r, "branch", "-q", "-D", "main")
    check("HG.red.missing_main_history_git",
          "history-git" in _hg_labels(_hg_findings(r)))
    r = repo_with("work")
    with open(os.path.join(r, ".git", "refs", "heads", "main"), "w") as fh:
        fh.write("1" * 40 + "\n")
    check("HG.red.failed_log_history_git",
          "history-git" in _hg_labels(_hg_findings(r)))
    r = repo_with("leak " + HG_CANARY)
    _fx(r, "switch", "-q", "--detach")
    labels = _hg_labels(_hg_findings(r))
    check("HG.red.detached_nocontext_history_context",
          "history-context" in labels and "history-secret" in labels)
    r = repo_with("clean message", branch="feature-" + HG_SENTINEL)
    rendered = [str(f) for f in _hg_findings(r, ([HG_SENTINEL], set()))]
    check("HG.red.branch_diag_omits_sentinel",
          any("[denylist-term]" in t for t in rendered)
          and not any(HG_SENTINEL in t for t in rendered))


def run(check):
    # 1. allowlist ----------------------------------------------------------
    check("guard allowlist accepts app", not guard.check_allowlist(["stage2/ancestry.py"]))
    check("guard allowlist accepts docs", not guard.check_allowlist(["docs/security.md"]))
    check("guard allowlist accepts data curation",
          not guard.check_allowlist(["data/targets.carrier.json"]))
    check("guard allowlist rejects stray top-level", bool(guard.check_allowlist(["notes.txt"])))
    check("guard allowlist rejects generated panel",
          bool(guard.check_allowlist(["data/panel.carrier.json"])))

    # 2. data-suffix --------------------------------------------------------
    check("guard data-suffix allows fixture",
          not guard.check_data_suffix(["fixtures/sources/gnomad.sample.vcf"]))
    check("guard data-suffix allows schema json",
          not guard.check_data_suffix(["schema/findings.schema.json"]))
    check("guard data-suffix rejects csv", bool(guard.check_data_suffix(["notes/data.csv"])))
    check("guard data-suffix rejects db", bool(guard.check_data_suffix(["cache/store.db"])))

    # 3. secret/PII patterns (never returns the matched value) --------------
    priv = "-----BEGIN RSA PRIVATE KEY-----"
    check("guard secret detects private key", guard.scan_text_for_secrets(priv))
    check("guard secret detects openai key",
          guard.scan_text_for_secrets("k = 'sk-" + "A" * 30 + "'"))
    check("guard secret detects home path",
          guard.scan_text_for_secrets("cwd=/Users/" + "someone/proj"))
    check("guard secret detects env assignment",
          guard.scan_text_for_secrets("SERVICE_API_KEY=abc123"))
    check("guard secret ignores ordinary prose", not guard.scan_text_for_secrets("hello world"))
    check("guard secret reports only line+name",
          all(isinstance(h, tuple) and len(h) == 2 for h in guard.scan_text_for_secrets(priv)))

    # 4. denylist (plain + hashed) ------------------------------------------
    check("guard denylist plain match",
          guard.scan_text_for_denylist("in secret town", ["secret town"], set()))
    check("guard denylist plain miss",
          not guard.scan_text_for_denylist("nothing here", ["secret town"], set()))
    digest = guard._sha256("wonderland")
    check("guard denylist hash match",
          guard.scan_text_for_denylist("visit Wonderland today", [], {digest}))
    check("guard denylist hash miss",
          not guard.scan_text_for_denylist("visit elsewhere", [], {digest}))

    # 5. gitignore self-test (integration, against this repo) ---------------
    check("guard gitignore self-test passes", not guard.check_gitignore_selftest())

    # 6. staged-content scanning -------------------------------------------
    contents = {"evil.py": "tok = 'ghp_" + "a" * 36 + "'"}
    check("guard scans provided staged content",
          guard.check_secrets(["evil.py"], contents))
    check("guard exempts itself from secret scan",
          not guard.check_secrets([".env.example"]))

    # 7. large-file guard ---------------------------------------------------
    tmp = os.path.join(ROOT, "tests", ".tmp_large.bin")
    try:
        with open(tmp, "wb") as fh:
            fh.write(b"0" * (guard.MAX_FILE_BYTES + 1))
        check("guard rejects oversized tracked file",
              guard.check_large_files(["tests/.tmp_large.bin"]))
    finally:
        os.remove(tmp)
    check("guard allows small file", not guard.check_large_files(["README.md"]))

    # 8. history scan (synthetic repositories; never this repo's own history) -
    _history_synthetic(check)
    _history_api(check)
    _env_classifier(check)
    _hook_env(check)
    _ci_static(check)
    _ci_dispatch(check)
    _doc_checks(check)

    # S3. packaging paths are allowed but never data-bearing -----------------
    def s3(name, fn):
        try:
            check(name, bool(fn()))
        except Exception:
            check(name, False)

    s3("S3.allows_pyproject",
       lambda: not guard.check_allowlist(["pyproject.toml"]))
    s3("S3.allows_package_py",
       lambda: not guard.check_allowlist(["snp_insights/cli.py"])
       and not guard.check_allowlist(["snp_insights/__main__.py"]))
    s3("S3.refuses_data_in_package",
       lambda: all(bool(guard.check_data_suffix([f"snp_insights/x{s}"]))
                   for s in (".csv", ".json", ".zip", ".vcf", ".tsv", ".db")))
    s3("S3.still_refuses_other_root",
       lambda: all(bool(guard.check_allowlist([p])) for p in (
           "notes.txt", "data.csv", "report.md", "pyproject.json",
           "snp_insights.zip", "snp_insightsX/cli.py", "pyproject.toml.bak")))

    def _env_refused():
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as fh:
            text = fh.read()
        tmp = _temp_gitignore_repo(text)
        try:
            return _is_ignored(tmp, "snp_insights/.env")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    s3("S3.package_env_still_refused", _env_refused)

    def _secret_in_package():
        text = "SERVICE_API_KEY=" + "abc123"
        tmp = tempfile.mkdtemp(prefix="snp-insights-s3-")
        old = guard._ROOT
        guard._ROOT = tmp
        try:
            os.makedirs(os.path.join(tmp, "snp_insights"))
            with open(os.path.join(tmp, "snp_insights", "cli.py"), "w",
                      encoding="utf-8") as fh:
                fh.write(text)
            return bool(guard.check_secrets(["snp_insights/cli.py"]))
        finally:
            guard._ROOT = old
            shutil.rmtree(tmp, ignore_errors=True)

    s3("S3.secret_scan_covers_package", _secret_in_package)

    def _denylist_in_package():
        contents = {"snp_insights/cli.py": "a decoyterm lives here"}
        old = guard.load_denylist
        guard.load_denylist = lambda: (["decoyterm"], set())
        try:
            return bool(guard.check_denylist(["snp_insights/cli.py"], contents))
        finally:
            guard.load_denylist = old

    s3("S3.denylist_covers_package", _denylist_in_package)

    s3("S3.gitignore_selftest_real",
       lambda: not guard.check_gitignore_selftest())

    def _selftest_mutation():
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as fh:
            text = fh.read()
        both = _temp_gitignore_repo(text)
        try:
            if _new_path_findings(_selftest_for(both)):
                return False
        finally:
            shutil.rmtree(both, ignore_errors=True)
        for line, expected in (("!/pyproject.toml", "pyproject.toml"),
                               ("!/snp_insights/", "snp_insights/cli.py")):
            mutated = "\n".join(
                ln for ln in text.split("\n") if ln.strip() != line)
            tmp = _temp_gitignore_repo(mutated)
            try:
                if expected not in [f.path for f in _new_path_findings(
                        _selftest_for(tmp))]:
                    return False
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        return True

    s3("S3.gitignore_selftest_detects", _selftest_mutation)

    def _reincludes():
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as fh:
            text = fh.read()
        tmp = _temp_gitignore_repo(text)
        try:
            if _is_ignored(tmp, "pyproject.toml"):
                return False
            if _is_ignored(tmp, "snp_insights/cli.py"):
                return False
            for path in ("snp_insights/__pycache__/x.pyc", "snp_insights/.env",
                         "snp_insights.egg-info/x", "build/x", "dist/x",
                         "report.md"):
                if not _is_ignored(tmp, path):
                    return False
            return True
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    s3("S3.gitignore_reincludes", _reincludes)

    def _checkignore_error():
        text = _real_gitignore_text()
        repo = _temp_gitignore_repo(text)
        target = tempfile.mkdtemp(prefix="snp-insights-s3-")
        real = guard.repo_root
        try:
            os.symlink(target, os.path.join(repo, "snp_insights"))
            guard.repo_root = lambda: repo
            try:
                findings = guard.check_gitignore_selftest()
            finally:
                guard.repo_root = real
            if "snp_insights/cli.py" not in [f.path for f in findings]:
                return False
        finally:
            shutil.rmtree(repo, ignore_errors=True)
            shutil.rmtree(target, ignore_errors=True)
        repo2 = _temp_gitignore_repo(text)
        try:
            os.makedirs(os.path.join(repo2, "snp_insights"))
            guard.repo_root = lambda: repo2
            try:
                findings2 = guard.check_gitignore_selftest()
            finally:
                guard.repo_root = real
            if _new_path_findings(findings2):
                return False
        finally:
            shutil.rmtree(repo2, ignore_errors=True)
        return True

    s3("S3.selftest_checkignore_error", _checkignore_error)

    s3("S3.gitignore_package_ignores",
       lambda: all(_package_ignore_map(_real_gitignore_text()).values()))

    def _package_ignore_mutations():
        base = _real_gitignore_text()
        for line, path in (
                ("!/snp_insights/.sensitive-terms", "snp_insights/.sensitive-terms"),
                ("!/snp_insights/*.pyc", "snp_insights/x.pyc"),
                ("!/snp_insights/__pycache__/", "snp_insights/__pycache__")):
            mutated = base + line + "\n"
            if _package_ignore_map(mutated)[path]:
                return False
        return True

    s3("S3.gitignore_package_ignores_mutations", _package_ignore_mutations)


# --- history API, CLI, environment and hook tests (C2) ----------------------
SENT = "snpsentinel"  # unique values are SENT + "-" + case so leaks are attributable
ENV_MSG = "[history-git] — inherited Git environment not permitted"
RECEIPT_RE = re.compile(r"guard: history selected=(\d+) scanned=(\d+) complete=yes")


def _hg_commit_raw(repo, message_bytes):
    """Commit with exact message bytes (hash-object --literally; commit-tree
    would re-encode invalid UTF-8)."""
    tree = _fx(repo, "write-tree")
    parent = _fx(repo, "rev-parse", "HEAD")
    stamp = b"Test Author <author@example.invalid> 1767225600 +0000\n"
    body = (b"tree " + tree.encode() + b"\nparent " + parent.encode() + b"\nauthor " + stamp
            + b"committer " + stamp + b"\n" + message_bytes)
    proc = subprocess.run(
        ("git", "hash-object", "-t", "commit", "-w", "--literally", "--stdin"), cwd=repo,
        env=_fixture_env(os.path.join(repo, ".home")), input=body,
        capture_output=True, check=True)
    oid = proc.stdout.decode().strip()
    _fx(repo, "update-ref", "HEAD", oid)
    return oid


def _hg_feature(messages=("clean synthetic message",), branch="feature", prefix="snp-insights-hg-"):
    repo = _hg_repo(prefix)
    _fx(repo, "switch", "-q", "-c", branch)
    for m in messages:
        _hg_commit(repo, m)
    return repo


def _scan(repo, denylist=None, **kwargs):
    with _guard_ctx(repo, denylist):
        return guard._scan_history(**kwargs)


@contextlib.contextmanager
def _git_exe(path=None, timeout=None):
    old, old_t = guard._GIT_EXE, guard.HISTORY_TIMEOUT
    guard._GIT_EXE = path
    if timeout is not None:
        guard.HISTORY_TIMEOUT = timeout
    try:
        yield
    finally:
        guard._GIT_EXE, guard.HISTORY_TIMEOUT = old, old_t


def _script(directory, name, text):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\n" + text)
    os.chmod(path, 0o755)
    return path


def _wrap_git(directory, body, name="git-wrap"):
    """An executable that runs `body` and then the real git."""
    return _script(directory, name, body + f'\nexec "{guard._GIT_EXE}" "$@"\n')


def _text(findings):
    return "\n".join(str(f) for f in findings)


def _run_main(argv, repo, denylist=None, env=None):
    import io
    out, err = io.StringIO(), io.StringIO()
    with _guard_ctx(repo, denylist):
        if env:
            os.environ.update(env)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = guard.main(argv)
            except SystemExit as exc:
                rc = exc.code
    return rc, out.getvalue(), err.getvalue()


def _full_fixture(messages=("clean synthetic message",), base=None):
    """A git-free manifest copy of this project's tracked files, committed on
    `main`, with the given messages committed on `feature`. Only
    tests/test_pipeline.py differs (a stub that exits 0). Returns (work, base)."""
    base = base or tempfile.mkdtemp(prefix="snp-insights-full-")
    repo = os.path.join(base, "work")
    os.makedirs(os.path.join(repo, ".home"))
    listing = subprocess.run(
        ("git", "ls-files", "-z"), cwd=ROOT, env=_fixture_env(base),
        capture_output=True, check=True).stdout.decode().split("\0")
    paths = [p for p in listing if p and os.path.exists(os.path.join(ROOT, p))]
    for rel in paths:
        dst = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, rel), dst)
    with open(os.path.join(repo, "tests", "test_pipeline.py"), "w", encoding="utf-8") as fh:
        fh.write("import sys\nsys.exit(0)\n")
    _fx(repo, "init", "-q")
    _fx(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _fx(repo, "add", "-f", "--", *paths)
    _fx(repo, "commit", "-q", "-m", "base commit")
    _fx(repo, "switch", "-q", "-c", "feature")
    for m in messages:
        _hg_commit(repo, m, name="docs/hg-note.md")
    return repo, base


def _history_api(check):
    def guarded(name, fn):
        try:
            check(name, bool(fn()))
        except Exception as exc:  # a crash is a failure, never a pass
            check(name + " [" + type(exc).__name__ + "]", False)

    sent_repo = lambda tag: _hg_feature(prefix=f"snp-insights-hg-{SENT}-{tag}-")  # noqa: E731

    # HG-01: every Git step fails closed; failed output is never consumed.
    def unborn():
        repo = tempfile.mkdtemp(prefix="snp-insights-hg-")
        os.makedirs(os.path.join(repo, ".home"))
        _fx(repo, "init", "-q")
        return "history-git" in _hg_labels(_hg_findings(repo))
    guarded("HG-01.unborn_head", unborn)

    def shallow():
        src = _hg_feature(("one", "two"))
        dst = tempfile.mkdtemp(prefix="snp-insights-hg-")
        os.makedirs(os.path.join(dst, ".home"))
        _fx(dst, "clone", "-q", "--depth", "1", "file://" + src, os.path.join(dst, "c"))
        c = os.path.join(dst, "c")
        os.makedirs(os.path.join(c, ".home"))
        _fx(c, "switch", "-q", "-c", "feature2")
        _hg_commit(c, "after shallow clone")
        return "history-git" in _hg_labels(_hg_findings(c))
    guarded("HG-01.shallow_repository", shallow)

    def missing_exe():
        with _git_exe(None):
            s = _scan(sent_repo("noexe"))
        return "history-git" in _hg_labels(s.findings) and not s.complete
    guarded("HG-01.git_unavailable", missing_exe)

    def failed_output_dropped():
        d = tempfile.mkdtemp(prefix="snp-insights-hg-")
        exe = _script(d, "bad-git", f"echo {HG_CANARY}\nexit 3\n")
        with _git_exe(exe):
            s = _scan(_hg_feature())
        labels = _hg_labels(s.findings)
        return "history-git" in labels and "history-secret" not in labels and not s.complete \
            and HG_CANARY not in _text(s.findings)
    guarded("HG-01.nonzero_stdout_discarded", failed_output_dropped)

    def timeout():
        d = tempfile.mkdtemp(prefix="snp-insights-hg-")
        exe = _script(d, "slow-git", "sleep 5\n")
        with _git_exe(exe, timeout=0.3):
            s = _scan(_hg_feature())
        return "history-git" in _hg_labels(s.findings) and not s.complete
    guarded("HG-01.timeout", timeout)

    def bad_decode_continues():
        repo = _hg_feature(("leak " + HG_CANARY,))
        _hg_commit_raw(repo, b"bad bytes \xff\xfe in message\n")
        s = _scan(repo)
        labels = _hg_labels(s.findings)
        return "history-git" in labels and "history-secret" in labels \
            and s.selected == 2 and s.scanned == 1 and not s.complete
    guarded("HG-01.undecodable_message_counts_unscanned", bad_decode_continues)

    def each_command_fails():
        d = tempfile.mkdtemp(prefix="snp-insights-hg-")
        for sub in ("rev-parse", "symbolic-ref", "merge-base", "rev-list", "show"):
            exe = _wrap_git(d, f'case " $* " in *" {sub} "*) echo {HG_CANARY}; exit 3;; esac',
                            name="fail-" + sub)
            with _git_exe(exe):
                s = _scan(_hg_feature(("a", "b")))
            if ("history-git" not in _hg_labels(s.findings) or s.complete
                    or "history-secret" in _hg_labels(s.findings)
                    or HG_CANARY in _text(s.findings)):
                return False
        return True
    guarded("HG-01.each_command_failure_fails_closed", each_command_fails)

    def ref_format_exec_failure():
        repo = _hg_feature()
        with _git_exe(None):
            rc, out, err = _run_main(["--full", "--history-branch", "ok/name"], repo)
        return rc == 1 and "[history-git]" in err and "complete=no" in out and "ok/name" not in out + err
    guarded("HG-05.check_ref_format_exec_failure_is_exit_1", ref_format_exec_failure)

    # HG-02: base resolution.
    def base_oids(repo):
        return _fx(repo, "rev-list", "--reverse", "main..HEAD").split()

    def explicit_base():
        repo = _hg_feature(("one", "two", "three"))
        first = base_oids(repo)[0]
        s = _scan(repo, base=first)
        return (s.selected, s.scanned, s.complete) == (2, 2, True)
    guarded("HG-02.explicit_base_range", explicit_base)

    def tag_peeled():
        repo = _hg_feature(("one", "two"))
        first = base_oids(repo)[0]
        _fx(repo, "tag", "-a", "-m", "synthetic", "v1", first)
        tag_oid = _fx(repo, "rev-parse", "v1")
        s = _scan(repo, base=tag_oid)
        return tag_oid != first and (s.selected, s.complete) == (1, True)
    guarded("HG-02.annotated_tag_peels_to_commit", tag_peeled)

    def bad_bases():
        repo = _hg_feature(("one", "two"))
        blob = _fx(repo, "hash-object", "-w", "f.txt")
        tree = _fx(repo, "rev-parse", "HEAD^{tree}")
        _fx(repo, "switch", "-q", "-c", "other", "main")
        other = _hg_commit(repo, "divergent", name="g.txt")
        _fx(repo, "switch", "-q", "feature")
        head = _fx(repo, "rev-parse", "HEAD")
        bad = {"blob": blob, "tree": tree, "missing": "2" * 40, "zero": "0" * 40,
               "divergent": other, "upper": head.upper(), "abbrev": head[:12],
               "dash": "-" + head[1:], "space": head + " ", "newline": head + "\n",
               "empty": "", "expression": "HEAD~1"}
        for name, value in bad.items():
            s = _scan(repo, base=value)
            if "history-git" not in _hg_labels(s.findings) or s.complete:
                return False
        return True
    guarded("HG-02.rejected_base_shapes", bad_bases)

    def default_is_local_branch_only():
        repo = _hg_feature(("one",))
        head = _fx(repo, "rev-parse", "HEAD")
        _fx(repo, "branch", "-q", "-m", "main", "old-main")
        _fx(repo, "tag", "main", head)
        _fx(repo, "update-ref", "refs/remotes/origin/main", head)
        s = _scan(repo)
        return "history-git" in _hg_labels(s.findings) and not s.complete
    guarded("HG-02.default_requires_refs_heads_main", default_is_local_branch_only)

    # HG-03: receipt counts.
    def receipts():
        empty = _scan(_hg_feature(()))
        some = _scan(_hg_feature(("a", "b", "c")))
        hit = _scan(_hg_feature(("leak " + HG_CANARY,)))
        return ((empty.selected, empty.scanned, empty.complete) == (0, 0, True)
                and (some.selected, some.scanned, some.complete) == (3, 3, True)
                and some.receipt() == "guard: history selected=3 scanned=3 complete=yes"
                and hit.complete and hit.findings)
    guarded("HG-03.receipt_empty_nonempty_and_hit", receipts)

    def merge_no_duplicates():
        repo = _hg_feature(("c1",))
        _fx(repo, "switch", "-q", "-c", "side", "main")
        _hg_commit(repo, "s1", name="s.txt")
        _hg_commit(repo, "s2", name="s.txt")
        _fx(repo, "switch", "-q", "feature")
        _fx(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
        expected = int(_fx(repo, "rev-list", "--count", "main..HEAD"))
        s = _scan(repo)
        return expected == 4 and (s.selected, s.scanned, s.complete) == (4, 4, True)
    guarded("HG-03.merge_traversal_counts_once", merge_no_duplicates)

    def count_mismatch():
        d = tempfile.mkdtemp(prefix="snp-insights-hg-")
        exe = _wrap_git(d, 'case " $* " in *" --count "*) echo 99; exit 0;; esac')
        with _git_exe(exe):
            s = _scan(_hg_feature(("a", "b")))
        return "history-git" in _hg_labels(s.findings) and s.selected is None \
            and "selected=unknown" in s.receipt() and not s.complete
    guarded("HG-03.count_enumeration_mismatch", count_mismatch)

    # HG-04: attached/detached context.
    def nested_and_tag_collision():
        repo = _hg_feature(("one",), branch="team/feature-" + HG_SENTINEL)
        _fx(repo, "tag", "team/feature-" + HG_SENTINEL)  # same short name as the branch
        s = _scan(repo, ([HG_SENTINEL], set()))
        return "denylist-term" in _hg_labels(s.findings) and s.complete \
            and HG_SENTINEL not in _text(s.findings)
    guarded("HG-04.attached_name_survives_tag_collision", nested_and_tag_collision)

    def detached_context():
        repo = _hg_feature(("leak " + HG_CANARY,))
        _fx(repo, "switch", "-q", "--detach")
        none = _scan(repo)
        ctx = _scan(repo, branch="team/detached-ok")
        named = _scan(repo, ([HG_SENTINEL], set()), branch="x-" + HG_SENTINEL)
        return ("history-context" in _hg_labels(none.findings) and not none.complete
                and none.selected == 1 and "history-secret" in _hg_labels(none.findings)
                and "history-context" not in _hg_labels(ctx.findings) and ctx.complete
                and "denylist-term" in _hg_labels(named.findings))
    guarded("HG-04.detached_requires_or_uses_context", detached_context)

    def unexpected_symbolic_ref():
        d = tempfile.mkdtemp(prefix="snp-insights-hg-")
        exe = _wrap_git(d, 'case " $* " in *" symbolic-ref "*) exit 2;; esac')
        with _git_exe(exe):
            s = _scan(_hg_feature())
        return "history-git" in _hg_labels(s.findings) and not s.complete
    guarded("HG-04.unexpected_symbolic_ref_status", unexpected_symbolic_ref)

    def outside_prefix():
        repo = _hg_feature()
        head = _fx(repo, "rev-parse", "HEAD")
        _fx(repo, "update-ref", "refs/remotes/origin/topic", head)
        _fx(repo, "symbolic-ref", "HEAD", "refs/remotes/origin/topic")
        s = _scan(repo)
        return "history-git" in _hg_labels(s.findings) and not s.complete
    guarded("HG-04.head_outside_refs_heads", outside_prefix)

    # HG-05: caller-asserted branch context.
    def attached_override():
        s = _scan(_hg_feature(), branch="asserted")
        return s.usage and not s.complete
    guarded("HG-05.attached_override_is_usage", attached_override)

    def shell_text_is_data():
        repo = _hg_feature()
        _fx(repo, "switch", "-q", "--detach")
        marker = os.path.join(repo, "HG_PWNED")
        s = _scan(repo, branch="$(touch HG_PWNED);`touch HG_PWNED`")
        return s.complete and not os.path.exists(marker) \
            and not os.path.exists(os.path.join(os.getcwd(), "HG_PWNED"))
    guarded("HG-05.shell_text_never_executed", shell_text_is_data)

    # HG-07: Git view is pinned to OIDs and ignores replacement/signature config.
    def replacement_ignored():
        repo = _hg_feature(("leak " + HG_CANARY,))
        bad = _fx(repo, "rev-parse", "HEAD")
        clean = _hg_commit_raw(repo, b"clean replacement\n")
        _fx(repo, "update-ref", "HEAD", bad)
        _fx(repo, "replace", bad, clean)
        return "history-secret" in _hg_labels(_scan(repo).findings)
    guarded("HG-07.replacement_refs_ignored", replacement_ignored)

    def argv_pinned():
        d = tempfile.mkdtemp(prefix="snp-insights-hg-")
        log = os.path.join(d, "argv.log")
        exe = _wrap_git(d, f'printf "%s\\n" "$*" >> "{log}"')
        with _git_exe(exe):
            s = _scan(_hg_feature(("a",)))
        lines = open(log, encoding="utf-8").read().splitlines()
        shows = [ln for ln in lines if " show " in f" {ln} "]
        return (s.complete and lines and all("--no-replace-objects" in ln for ln in lines)
                and shows and all("--no-show-signature" in ln for ln in shows)
                and not any("main..HEAD" in ln or "feature" in ln.split("rev-list")[-1]
                            for ln in lines if " rev-list " in f" {ln} "))
    guarded("HG-07.argv_flags_and_oid_ranges", argv_pinned)

    def deleted_object():
        repo = _hg_feature(("one", "two"))
        oid = _fx(repo, "rev-parse", "HEAD")
        src = os.path.join(repo, ".git", "objects", oid[:2], oid[2:])
        os.rename(src, os.path.join(repo, ".home", "moved-object"))
        s = _scan(repo)
        return "history-git" in _hg_labels(s.findings) and not s.complete
    guarded("HG-07.deleted_object", deleted_object)

    def ref_moves():
        results = []
        for target, expect_ctx in (("refs/heads/main", True), ("refs/heads/feature", True)):
            repo = _hg_feature(("one", "two"))
            d = tempfile.mkdtemp(prefix="snp-insights-hg-")
            flag = os.path.join(d, "moved")
            other = _fx(repo, "rev-list", "--reverse", "main..HEAD").split()[0]
            move = other if target.endswith("main") else _fx(repo, "rev-parse", "main")
            body = (f'case " $* " in *" show "*) if [ ! -e "{flag}" ]; then : > "{flag}"; '
                    f'"{guard._GIT_EXE}" update-ref {target} {move}; fi;; esac')
            with _git_exe(_wrap_git(d, body)):
                s = _scan(repo)
            results.append(("history-context" in _hg_labels(s.findings)) == expect_ctx
                           and not s.complete)
        # An explicit base is OID-bound: moving main afterwards changes nothing.
        repo = _hg_feature(("one", "two"))
        d = tempfile.mkdtemp(prefix="snp-insights-hg-")
        flag = os.path.join(d, "moved")
        first = _fx(repo, "rev-list", "--reverse", "main..HEAD").split()[0]
        body = (f'case " $* " in *" show "*) if [ ! -e "{flag}" ]; then : > "{flag}"; '
                f'"{guard._GIT_EXE}" update-ref refs/heads/main {first}; fi;; esac')
        base = _fx(repo, "rev-parse", "main")
        with _git_exe(_wrap_git(d, body)):
            s = _scan(repo, base=base)
        results.append(s.complete and "history-context" not in _hg_labels(s.findings))
        return all(results)
    guarded("HG-07.ref_movement_recheck", ref_moves)

    # HG-06: diagnostics carry fixed text only (sentinel lives in the repo path).
    def no_leak_failures():
        repo = sent_repo("leak")
        texts = []
        with _git_exe(None):
            texts.append(_text(_scan(repo).findings))
        d = tempfile.mkdtemp(prefix=f"snp-insights-hg-{SENT}-")
        texts.append(_text(_scan(d).findings))
        bad = _hg_feature(("x",), prefix=f"snp-insights-hg-{SENT}-b-")
        d = tempfile.mkdtemp(prefix=f"snp-insights-hg-{SENT}-")
        # A branch name that is not valid UTF-8 (filesystems often refuse to create one).
        exe = _wrap_git(d, 'case " $* " in *" symbolic-ref "*) '
                           "printf 'refs/heads/feat-\\377\\n'; exit 0;; esac")
        with _git_exe(exe):
            s = _scan(bad)
        texts.append(_text(s.findings))
        return (all(SENT not in t and "Traceback" not in t and "�" not in t for t in texts)
                and "history-git" in _hg_labels(s.findings) and not s.complete)
    guarded("HG-06.failures_leak_nothing", no_leak_failures)

    def argument_errors():
        repo = _hg_feature(prefix=f"snp-insights-hg-{SENT}-cli-")
        cases = [
            ["--bogus=" + SENT], ["--marker=" + SENT], ["--history-base"],
            ["--history-base=" + SENT], ["--full", "--history-base", SENT],
            ["--full", "--history-base", "A" * 40], ["--history-base", "a" * 40],
            ["--hash", SENT, "--history-branch", SENT],
            ["--hash", SENT, "--full", "--history-base", "a" * 40],
            ["--history-branch=" + SENT], ["--all", "--history-branch", SENT],
            ["--staged", "--history-base", "a" * 40], ["--full", "--staged", SENT],
            ["--full", "--history-branch", "-" + SENT], ["--full", "--history-branch", ""],
            ["--full", "--history-branch", "a\nb" + SENT],
            ["--full", "--history-branch", "bad..name" + SENT],
            ["--full", "--history-branch", "sp ace" + SENT],
            ["--full", "--history-branch", "ctl\x01" + SENT],
            ["--ful"], ["--hist", "x"],
        ]
        for argv in cases:
            rc, out, err = _run_main(argv, repo)
            wants_receipt = any(a.startswith("--history") for a in argv)
            if rc != 2 or SENT in out + err or "guard: invalid arguments" not in err \
                    or ("history selected=unknown scanned=0 complete=no" in out) != wants_receipt:
                return False
        return True
    guarded("HG-06.parser_errors_fixed_and_exit_2", argument_errors)

    def argv0_and_help():
        d = tempfile.mkdtemp(prefix=f"snp-insights-hg-{SENT}-")
        copy = os.path.join(d, "guard.py")
        shutil.copy(os.path.join(ROOT, "scripts", "guard.py"), copy)
        proc = subprocess.run((sys.executable, "-I", copy, "--bogus"), cwd=d,
                              capture_output=True, text=True)
        helped = subprocess.run((sys.executable, "-I", copy, "--help"), cwd=d,
                                capture_output=True, text=True)
        return (proc.returncode == 2 and SENT not in proc.stdout + proc.stderr
                and helped.returncode == 0 and "--history-base" in helped.stdout)
    guarded("HG-06.argv0_fixed_and_help_retained", argv0_and_help)

    # HG-08: modes and entry points.
    def hash_still_works():
        rc, out, _ = _run_main(["--hash", "Wonder Land"], ROOT)
        return rc == 0 and out.strip() == "sha256:" + guard._sha256("wonder land")
    guarded("HG-08.hash_positive_control", hash_still_works)

    def valid_ref_name_variants():
        repo = _hg_feature()
        _fx(repo, "switch", "-q", "--detach")
        rc, out, err = _run_main(["--history-branch", "team/x"], repo)
        return rc == 2 and "complete=no" in out
    guarded("HG-08.history_options_need_explicit_full", valid_ref_name_variants)

    def full_modes():
        repo, _ = _full_fixture(("clean synthetic message", "another clean one"))
        rc, out, err = _run_main(["--full"], repo)
        ok_default = rc == 0 and "history selected=2 scanned=2 complete=yes" in out
        base = _fx(repo, "rev-list", "--reverse", "main..HEAD").split()[0]
        rc2, out2, _ = _run_main(["--full", "--history-base", base], repo)
        ok_base = rc2 == 0 and "history selected=1 scanned=1 complete=yes" in out2
        head = _fx(repo, "rev-parse", "HEAD")
        rc3, out3, _ = _run_main(["--full", "--history-base", head], repo)
        ok_empty = rc3 == 0 and "history selected=0 scanned=0 complete=yes" in out3
        _fx(repo, "switch", "-q", "--detach")
        rc4, out4, err4 = _run_main(["--full"], repo)
        ok_detached = rc4 == 1 and "complete=no" in out4 and "history-context" in err4
        rc5, out5, _ = _run_main(["--full", "--history-branch", "ci/asserted"], repo)
        ok_ctx = rc5 == 0 and "complete=yes" in out5
        return all((ok_default, ok_base, ok_empty, ok_detached, ok_ctx))
    guarded("HG-08.full_cli_receipts_and_context", full_modes)

    def simultaneous_findings():
        repo, _ = _full_fixture(("leak " + HG_CANARY,))
        _hg_commit(repo, "add decoy file", name="docs/decoy.md")
        with open(os.path.join(repo, "docs", "decoy.md"), "a", encoding="utf-8") as fh:
            fh.write("key " + HG_CANARY + "\n")
        _fx(repo, "add", "-f", "--", "docs/decoy.md")
        _fx(repo, "commit", "-q", "-m", "decoy content")
        rc, out, err = _run_main(["--full"], repo)
        return (rc == 1 and "[secret]" in err and "[history-secret]" in err
                and "complete=yes" in out and HG_CANARY not in out + err)
    guarded("HG-08.content_and_history_findings_together", simultaneous_findings)

    def io_boundary():
        repo, _ = _full_fixture()
        real = guard.run_all

        def boom():
            raise OSError(f"{SENT} secret path")
        guard.run_all = boom
        try:
            rc, out, err = _run_main(["--full"], repo)
        finally:
            guard.run_all = real
        return (rc == 1 and "[guard-io]" in err and SENT not in out + err
                and "Traceback" not in err and "complete=no" in out)
    guarded("HG-08.full_entry_io_failure_fixed", io_boundary)

    def attached_override_cli():
        repo = _hg_feature(prefix=f"snp-insights-hg-{SENT}-att-")
        rc, out, err = _run_main(["--full", "--history-branch", "asserted"], repo)
        return (rc == 2 and "selected=unknown scanned=0 complete=no" in out
                and SENT not in out + err and "guard: invalid arguments" in err)
    guarded("HG-05.attached_override_cli_exit_2", attached_override_cli)

    def selftest_io_boundary():
        repo, _ = _full_fixture()
        real = guard.check_gitignore_selftest

        def boom():
            raise OSError(f"{SENT} secret path")
        guard.check_gitignore_selftest = boom
        try:
            rc, out, err = _run_main(["--full"], repo)
        finally:
            guard.check_gitignore_selftest = real
        return (rc == 1 and "[guard-io]" in err and SENT not in out + err
                and "complete=no" in out and "selected=1 scanned=1" in out)
    guarded("HG-08.selftest_io_failure_fixed_history_still_runs", selftest_io_boundary)

    def other_modes_unchanged():
        repo, _ = _full_fixture()
        rc, out, _ = _run_main(["--all"], repo)
        rc2, out2, _ = _run_main([], repo)
        return rc == 0 and rc2 == 0 and "history" not in out + out2
    guarded("HG-08.all_and_default_modes_have_no_history", other_modes_unchanged)

    def default_args_callable():
        repo = _hg_feature()
        with _guard_ctx(repo):
            return guard.check_history() == [] and isinstance(guard.run_full(), list)
    guarded("HG-08.zero_argument_apis_callable", default_args_callable)


def _env_classifier(check):
    def guarded(name, fn):
        try:
            check(name, bool(fn()))
        except Exception as exc:
            check(name + " [" + type(exc).__name__ + "]", False)

    repo = _hg_feature()
    other = _hg_feature(prefix=f"snp-insights-hg-{SENT}-other-")
    link = os.path.join(tempfile.mkdtemp(prefix="snp-insights-hg-"), "gitdir-link")
    os.symlink(os.path.join(repo, ".git"), link)
    base = {"PATH": os.environ.get("PATH", ""), "HOME": "/nonexistent"}

    def classify(extra, cwd=repo):
        before = dict(os.environ)
        res = guard._classify_git_env({**base, **extra}, cwd)
        assert dict(os.environ) == before
        return res

    guarded("ENV.no_git_names_accepted", lambda: classify({})[0]
            and not [k for k in classify({})[1] if k.startswith("GIT_")
                     and k not in ("GIT_OPTIONAL_LOCKS", "GIT_TERMINAL_PROMPT")])
    guarded("ENV.child_always_sets_locks_and_prompts", lambda: classify({})[1][
        "GIT_OPTIONAL_LOCKS"] == "0" and classify({})[1]["GIT_TERMINAL_PROMPT"] == "0")
    guarded("ENV.class_I_ignored_not_passed", lambda: classify(
        {"GIT_PREFIX": "sub/", "GIT_EXEC_PATH": "/x/" + SENT})[0]
        and "GIT_PREFIX" not in classify({"GIT_PREFIX": "p"})[1]
        and "GIT_EXEC_PATH" not in classify({"GIT_EXEC_PATH": "p"})[1])
    guarded("ENV.class_II_matching_accepted_and_dropped", lambda: (
        lambda ok_env: ok_env[0] and "GIT_DIR" not in ok_env[1]
        and "GIT_WORK_TREE" not in ok_env[1])(
        classify({"GIT_DIR": os.path.join(repo, ".git"), "GIT_WORK_TREE": repo})))
    guarded("ENV.relative_git_dir_accepted", lambda: classify({"GIT_DIR": ".git"})[0])
    guarded("ENV.symlinked_git_dir_accepted", lambda: classify({"GIT_DIR": link})[0])
    guarded("ENV.work_tree_alone_validated", lambda: classify({"GIT_WORK_TREE": repo})[0]
            and not classify({"GIT_WORK_TREE": other})[0])
    guarded("ENV.nonexistent_git_dir_refused", lambda: not classify(
        {"GIT_DIR": os.path.join(repo, "missing-" + SENT)})[0])
    guarded("ENV.other_repository_git_dir_refused", lambda: not classify(
        {"GIT_DIR": os.path.join(other, ".git")})[0])
    guarded("ENV.git_dir_ok_but_work_tree_elsewhere_refused", lambda: not classify(
        {"GIT_DIR": os.path.join(repo, ".git"), "GIT_WORK_TREE": other})[0])
    guarded("ENV.discovery_failure_refused", lambda: not classify(
        {"GIT_DIR": ".git"}, cwd=tempfile.mkdtemp(prefix="snp-insights-hg-"))[0])

    fixed = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_GLOBAL": "/dev/null"}
    guarded("ENV.class_III_exact_values_accepted", lambda: all(
        classify({k: v})[0] and classify({k: v})[1][k] == v for k, v in fixed.items()))
    guarded("ENV.class_III_wrong_values_refused", lambda: all(
        not classify({k: v + "x"})[0] and not classify({k: ""})[0] for k, v in fixed.items()))
    names = ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0",
             "GIT_CONFIG_VALUE_0", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
             "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE",
             "GIT_SHALLOW_FILE", "GIT_GRAFT_FILE", "GIT_REPLACE_REF_BASE",
             "GIT_NO_REPLACE_OBJECTS", "GIT_IMPLICIT_WORK_TREE", "GIT_CEILING_DIRECTORIES",
             "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_TRACE", "GIT_TRACE2", "GIT_ASKPASS",
             "GIT_PUSH_OPTION_COUNT", "GIT_EDITOR", "GIT_SNP_TEST_SENTINEL")
    guarded("ENV.class_IV_every_other_name_refused", lambda: all(
        classify({n: SENT})[0] is False for n in names))
    guarded("ENV.case_sensitive_names", lambda: classify({"git_index_file": SENT})[0])

    def scan_refuses_without_echo():
        results = []
        for name in ("GIT_INDEX_FILE", "GIT_CONFIG_PARAMETERS", "GIT_SNP_TEST_SENTINEL"):
            with _guard_ctx(repo):
                os.environ[name] = "value-" + SENT
                scan = guard._scan_history()
                snapshot = dict(os.environ)
            results.append(
                [str(f) for f in scan.findings] == ["history: " + ENV_MSG]
                and not scan.complete and scan.selected is None
                and snapshot[name] == "value-" + SENT and name not in os.environ)
        return all(results)
    guarded("ENV.history_scan_refuses_generically", scan_refuses_without_echo)

    def other_layers_continue():
        rc, out, err = _run_main(["--full"], repo, env={"GIT_SNP_TEST_SENTINEL": SENT})
        return rc == 1 and "[allowlist]" in err and ENV_MSG in err and SENT not in out + err
    guarded("ENV.other_layers_still_run_on_refusal", other_layers_continue)

    def refusal_keeps_other_layers():
        repo2, _ = _full_fixture(("clean synthetic message",))
        rc, out, err = _run_main(["--full"], repo2, env={"GIT_SNP_TEST_SENTINEL": SENT})
        return rc == 1 and ENV_MSG in err and SENT not in out + err and "complete=no" in out
    guarded("ENV.full_mode_refuses_with_receipt", refusal_keeps_other_layers)


# --- HOOK-ENV: the unchanged hooks/pre-push driven by a real `git push` -----
class _HookFx:
    pass


def _hook_fixture(probe=False, gitleaks_stub=False):
    work, base = _full_fixture(("clean synthetic message",))
    fx = _HookFx()
    fx.work, fx.base = work, base
    fx.bare = os.path.join(base, "bare.git")
    fx.bin = os.path.join(base, "bin")
    os.makedirs(fx.bin)
    os.makedirs(os.path.join(base, "home"))
    _fx(base, "init", "-q", "--bare", fx.bare, check_rc=True)
    _fx(work, "remote", "add", "origin", fx.bare)
    hooks = os.path.join(work, "hooks")
    _fx(work, "config", "core.hooksPath", hooks)  # absolute, per the approved contract
    with open(os.path.join(ROOT, "hooks", "pre-push"), "rb") as fh:
        project_bytes = fh.read()
    with open(os.path.join(hooks, "pre-push"), "rb") as fh:
        fx.unchanged = fh.read() == project_bytes
    if probe:
        dump = os.path.join(base, "git-names.txt")
        _script(hooks, "pre-push", f"/usr/bin/env | /usr/bin/cut -d= -f1 | "
                f"/usr/bin/grep '^GIT_' | /usr/bin/sort > \"{dump}\"\nexit 0\n")
        fx.dump = dump
    for name in os.listdir(hooks):
        os.chmod(os.path.join(hooks, name), 0o755)
    os.symlink(sys.executable, os.path.join(fx.bin, "python3"))
    os.symlink(guard._GIT_EXE, os.path.join(fx.bin, "git"))
    if gitleaks_stub:
        _script(fx.bin, "gitleaks", "exit 0\n")
    fx.env = {"PATH": fx.bin + ":/usr/bin:/bin", "HOME": os.path.join(base, "home"),
              "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    return fx


def _hook_push(fx, branch="feature", cwd=None, git_args=(), extra_env=None):
    env = dict(fx.env)
    env.update(extra_env or {})
    proc = subprocess.run(
        (os.path.join(fx.bin, "git"),) + tuple(git_args) + ("push", "-q", "origin", branch),
        cwd=cwd or fx.work, env=env, capture_output=True, text=True, timeout=300)
    return proc.returncode, proc.stdout + proc.stderr


def _bare_refs(fx):
    proc = subprocess.run((guard._GIT_EXE, "--git-dir", fx.bare, "for-each-ref",
                           "--format=%(refname)"), capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "HOME": fx.base})
    return proc.stdout.split()


def _snapshot(fx):
    import hashlib
    digest = {}
    targets = [(fx.bare, None)] + [(os.path.join(fx.work, ".git", p), None) for p in
                                   ("refs", "packed-refs", "index", "config", "HEAD")]
    for top, _ in targets:
        if os.path.isfile(top):
            walk = [(os.path.dirname(top), [], [os.path.basename(top)])]
        else:
            walk = os.walk(top) if os.path.isdir(top) else []
        for dirpath, _dirs, files in walk:
            for name in files:
                full = os.path.join(dirpath, name)
                with open(full, "rb") as fh:
                    digest[full] = hashlib.sha256(fh.read()).hexdigest()
    return digest


def _hook_env(check):
    def guarded(name, fn):
        try:
            check(name, bool(fn()))
        except Exception as exc:
            check(name + " [" + type(exc).__name__ + "]", False)

    def accepted(fx, **kwargs):
        rc, out = _hook_push(fx, **kwargs)
        m = RECEIPT_RE.search(out)
        refs = _bare_refs(fx)
        branch = kwargs.get("branch", "feature")
        return (fx.unchanged and rc == 0 and m is not None and int(m.group(1)) >= 1
                and m.group(1) == m.group(2) and "refs/heads/" + branch in refs)

    def shapes(fx):
        """name -> (push kwargs); P3/P4 need extra setup done here."""
        sub = os.path.join(fx.work, "sub")
        os.makedirs(sub)
        wt = os.path.join(fx.base, "wt")
        _fx(fx.work, "worktree", "add", "-q", "-b", "wtbranch", wt, "feature")
        return {
            "P1": dict(),
            "P2": dict(cwd=sub),
            "P3": dict(cwd=wt, branch="wtbranch"),
            "P4": dict(cwd=fx.base, git_args=("--git-dir", os.path.join(fx.work, ".git"),
                                              "--work-tree", fx.work)),
        }

    for pid in ("P1", "P2", "P3", "P4"):
        fx = _hook_fixture()
        guarded(f"HOOK-ENV-{pid}.push_reaches_guard_and_succeeds",
                lambda fx=fx, pid=pid: accepted(fx, **shapes(fx)[pid]))
    fx = _hook_fixture(gitleaks_stub=True)
    guarded("HOOK-ENV-P1.with_gitleaks_stub", lambda: accepted(fx))

    # P5: the names Git actually exports to the hook are exactly the known ones.
    def probe_names():
        allowed_common = {"GIT_PREFIX", "GIT_EXEC_PATH", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL"}
        extra = {"P1": set(), "P2": set(), "P3": {"GIT_DIR"}, "P4": {"GIT_DIR", "GIT_WORK_TREE"}}
        for pid in ("P1", "P2", "P3", "P4"):
            fx = _hook_fixture(probe=True)
            rc, out = _hook_push(fx, **shapes(fx)[pid])
            seen = set(open(fx.dump, encoding="utf-8").read().split())
            if rc != 0 or not seen <= allowed_common | extra[pid]:
                return False
            if not {"GIT_EXEC_PATH"} <= seen:
                return False
        return True
    guarded("HOOK-ENV-P5.exported_names_are_known", probe_names)

    # Refused shapes: one hostile addition each; nothing may change.
    def refused(case, setup):
        fx = _hook_fixture()
        sent = f"{SENT}-{case}"
        kwargs = setup(fx, sent)
        before = _snapshot(fx)
        rc, out = _hook_push(fx, **kwargs)
        after = _snapshot(fx)
        return (fx.unchanged and rc != 0 and ENV_MSG in out and sent not in out
                and not _bare_refs(fx) and before == after)

    def simple(name, value=lambda fx, sent: sent):
        def setup(fx, sent):
            return dict(extra_env={name: value(fx, sent)})
        return setup

    def link_to(target, label):
        def make(fx, sent):
            path = os.path.join(fx.base, f"{label}-{sent}")
            os.symlink(target(fx), path)
            return path
        return make

    def r1(fx, sent):
        other = os.path.join(fx.base, f"other-{sent}")
        _fx(fx.base, "clone", "-q", fx.work, other)
        _fx(other, "remote", "set-url", "origin", fx.bare)
        _fx(other, "config", "core.hooksPath", os.path.join(fx.work, "hooks"))
        return dict(extra_env={"GIT_DIR": os.path.join(other, ".git")})

    def r2(fx, sent):
        alt = os.path.join(fx.work, f"wtother-{sent}")
        for rel in ("tests/test_pipeline.py", "scripts/guard.py"):
            os.makedirs(os.path.dirname(os.path.join(alt, rel)), exist_ok=True)
            shutil.copy2(os.path.join(fx.work, rel), os.path.join(alt, rel))
        return dict(extra_env={"GIT_WORK_TREE": alt})

    def r10_args(fx, sent):
        return dict(git_args=("-c", "user.name=" + sent))

    def r10_count(fx, sent):
        return dict(extra_env={"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "user.name",
                               "GIT_CONFIG_VALUE_0": sent})

    def file_in_base(label):
        def value(fx, sent):
            path = os.path.join(fx.base, f"{label}-{sent}")
            open(path, "w").close()
            return path
        return value

    def dir_in_base(label):
        def value(fx, sent):
            path = os.path.join(fx.base, f"{label}-{sent}")
            os.makedirs(path)
            return path
        return value

    objects = lambda fx: os.path.join(fx.work, ".git", "objects")  # noqa: E731
    gitdir = lambda fx: os.path.join(fx.work, ".git")  # noqa: E731
    cases = {
        "R1.GIT_DIR_other_repository": r1,
        "R2.GIT_WORK_TREE_elsewhere": r2,
        "R3.GIT_INDEX_FILE": simple("GIT_INDEX_FILE", lambda fx, s: os.path.join(fx.base, "idx-" + s)),
        "R4.GIT_OBJECT_DIRECTORY": lambda fx, s: dict(extra_env={
            "GIT_OBJECT_DIRECTORY": link_to(objects, "objs")(fx, s)}),
        "R5.GIT_ALTERNATE_OBJECT_DIRECTORIES": simple(
            "GIT_ALTERNATE_OBJECT_DIRECTORIES", dir_in_base("alt")),
        "R6.GIT_COMMON_DIR": lambda fx, s: dict(extra_env={
            "GIT_COMMON_DIR": link_to(gitdir, "common")(fx, s)}),
        "R7.GIT_NAMESPACE": simple("GIT_NAMESPACE"),
        "R8.GIT_SHALLOW_FILE": simple("GIT_SHALLOW_FILE", file_in_base("shallow")),
        "R9a.GIT_REPLACE_REF_BASE": simple("GIT_REPLACE_REF_BASE", lambda fx, s: f"refs/{s}/"),
        "R9b.GIT_NO_REPLACE_OBJECTS": simple("GIT_NO_REPLACE_OBJECTS"),
        "R9c.GIT_GRAFT_FILE": simple("GIT_GRAFT_FILE", file_in_base("graft")),
        "R10a.git_dash_c_push": r10_args,
        "R10b.GIT_CONFIG_COUNT": r10_count,
        "R11.GIT_CONFIG_GLOBAL_not_devnull": simple("GIT_CONFIG_GLOBAL", file_in_base("gconf")),
        "R12.GIT_OPTIONAL_LOCKS_1": simple("GIT_OPTIONAL_LOCKS", lambda fx, s: "1"),
        "R13.GIT_SNP_TEST_SENTINEL": simple("GIT_SNP_TEST_SENTINEL"),
    }
    for case, setup in cases.items():
        guarded(f"HOOK-ENV-{case}.refused_with_no_change",
                lambda case=case, setup=setup: refused(case.split(".")[0], setup))


# --- CI binding: the workflow's dispatch body, run offline (C3) -------------
def _ci_text():
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as fh:
        return fh.read()


def _dispatch_source():
    lines = _ci_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == "python - <<'PY'") + 1
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "PY")
    indent = len(lines[start]) - len(lines[start].lstrip())
    return "\n".join(ln[indent:] for ln in lines[start:end]) + "\n"


def _ci_static(check):
    text = _ci_text()
    src = _dispatch_source()
    privacy = text[text.index("  privacy-guard:"):text.index("  secret-scan:")]
    check("CI.triggers_unchanged",
          "on:\n  push:\n    branches: [main]\n  pull_request:\n    branches: [main]\n" in text
          and "pull_request_target" not in text and "workflow_run" not in text)
    check("CI.permissions_and_jobs_unchanged",
          "permissions:\n  contents: read\n" in text
          and all(k in text for k in ("  test:\n    name: test (py${{ matrix.python }})",
                                      "  privacy-guard:\n    name: privacy guard",
                                      "  secret-scan:\n    name: secret scan"))
          and text.count("timeout-minutes:") == 3)
    check("CI.secret_mapping_unchanged_and_single",
          text.count("secrets.") == 1
          and "        env:\n          SENSITIVE_TERMS: ${{ secrets.SENSITIVE_TERMS }}\n" in privacy)
    check("CI.privacy_checkout_exact_sha_full_depth",
          "          ref: ${{ github.sha }}\n          fetch-depth: 0\n" in privacy)
    check("CI.no_expression_in_run_source", "${{" not in src and "${{" not in
          privacy[privacy.index("run: |"):])
    check("CI.test_job_still_runs_pipeline",
          "        run: python tests/test_pipeline.py\n" in text)
    check("CI.action_pins_unchanged",
          text.count("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1") == 3
          and text.count("actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97") == 2)
    check("CI.guard_invoked_by_argv_not_shell",
          "sys.executable, \"scripts/guard.py\", \"--full\"" in src and "shell=True" not in src
          and "eval" not in src and "os.system" not in src)


def _ci_dispatch(check):
    def guarded(name, fn):
        try:
            check(name, bool(fn()))
        except Exception as exc:
            check(name + " [" + type(exc).__name__ + "]", False)

    src = _dispatch_source()
    import json
    repository = "owner/synthetic"

    def setup(kind):
        repo, base = _full_fixture(("clean synthetic message",))
        main = _fx(repo, "rev-parse", "main")
        feature = _fx(repo, "rev-parse", "feature")
        merge = None
        if kind == "pr":
            _fx(repo, "switch", "-q", "-c", "mergeref", "main")
            _fx(repo, "merge", "-q", "--no-ff", "-m", "Merge synthetic pull request", "feature")
            merge = _fx(repo, "rev-parse", "HEAD")
        _fx(repo, "switch", "-q", "--detach", merge or feature)
        return repo, base, main, feature, merge

    def run(repo, base, name, event, sha, ref="refs/heads/main", raw=None, drop=None):
        path = os.path.join(base, "event.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(raw if raw is not None else json.dumps(event))
        env = {"PATH": os.environ.get("PATH", ""), "HOME": base, "LC_ALL": "C",
               "GITHUB_EVENT_NAME": name, "GITHUB_EVENT_PATH": path, "GITHUB_SHA": sha,
               "GITHUB_REF": ref, "GITHUB_REPOSITORY": repository}
        env.pop(drop, None)
        proc = subprocess.run((sys.executable, "-I", "-c", src), cwd=repo, env=env,
                              capture_output=True, text=True, timeout=300)
        return proc.returncode, proc.stdout, proc.stderr

    def refused(result):
        rc, out, err = result
        return (rc == 1 and err.startswith("privacy-guard: ") and "guard: history" not in out
                and SENT not in out + err and "Traceback" not in err)

    def push_event(main, feature, **over):
        event = {"ref": "refs/heads/main", "before": main, "after": feature,
                 "deleted": False, "forced": False, "created": False}
        event.update(over)
        return event

    def push_ok():
        repo, base, main, feature, _ = setup("push")
        rc, out, _ = run(repo, base, "push", push_event(main, feature), feature)
        empty = run(repo, base, "push", push_event(feature, feature), feature)
        return (rc == 0 and "history selected=1 scanned=1 complete=yes" in out
                and empty[0] == 0 and "history selected=0 scanned=0 complete=yes" in empty[1])
    guarded("CI.dispatch_push_accepts_fast_forward_and_empty", push_ok)

    def push_refusals():
        repo, base, main, feature, _ = setup("push")
        other = _fx(repo, "commit-tree", "-m", "unrelated", _fx(repo, "write-tree"))
        cases = [
            run(repo, base, "push", push_event("0" * 40, feature), feature),
            run(repo, base, "push", push_event("0" * 40, feature, created=True), feature),
            run(repo, base, "push", push_event(main, feature, deleted=True), feature),
            run(repo, base, "push", push_event(main, feature, forced=True), feature),
            run(repo, base, "push", push_event(other, feature), feature),
            run(repo, base, "push", push_event("3" * 40, feature), feature),
            run(repo, base, "push", push_event(main, feature, ref="refs/heads/" + SENT), feature),
            run(repo, base, "push", push_event(main, feature), feature, ref="refs/heads/" + SENT),
            run(repo, base, "push", push_event(main, main), feature),
            run(repo, base, "push", push_event(main, feature), main),
            run(repo, base, "push", push_event(main.upper(), feature), feature),
            run(repo, base, "push", push_event(main, feature), feature, raw="{" + SENT),
            run(repo, base, "push", {}, feature),
            run(repo, base, "push", push_event(main, feature), feature, drop="GITHUB_EVENT_PATH"),
            run(repo, base, "push", push_event(main, feature), feature, drop="GITHUB_REF"),
            run(repo, base, "schedule", push_event(main, feature), feature),
            run(repo, base, "workflow_dispatch", {}, feature),
        ]
        return all(refused(c) for c in cases)
    guarded("CI.dispatch_push_refuses_unsafe_contexts", push_refusals)

    def pr_event(main, feature, branch="topic/synthetic", **over):
        event = {"action": "synchronize", "pull_request": {
            "base": {"ref": "main", "sha": main, "repo": {"full_name": repository}},
            "head": {"ref": branch, "sha": feature, "repo": {"full_name": "other/fork"}}}}
        for key, value in over.items():
            event["pull_request"][key] = value
        return event

    def pr_ok():
        repo, base, main, feature, merge = setup("pr")
        rc, out, _ = run(repo, base, "pull_request", pr_event(main, feature), merge,
                         ref="refs/pull/1/merge")
        return rc == 0 and "history selected=2 scanned=2 complete=yes" in out
    guarded("CI.dispatch_pull_request_merge_tuple_accepted", pr_ok)

    def pr_attached_is_normalized_and_branch_is_data():
        repo, base, main, feature, merge = setup("pr")
        _fx(repo, "switch", "-q", "mergeref")
        marker = os.path.join(repo, "CI_PWNED")
        rc, out, _ = run(repo, base, "pull_request",
                         pr_event(main, feature, branch="x$(touch${IFS}CI_PWNED);`id`"),
                         merge, ref="refs/pull/1/merge")
        return rc == 0 and "complete=yes" in out and not os.path.exists(marker) \
            and _fx(repo, "symbolic-ref", "--quiet", "HEAD", check_rc=False) == ""
    guarded("CI.dispatch_normalizes_head_and_never_executes_branch", pr_attached_is_normalized_and_branch_is_data)

    def pr_refusals():
        repo, base, main, feature, merge = setup("pr")
        stale = _fx(repo, "commit-tree", "-m", "stale", _fx(repo, "write-tree"))
        run_pr = lambda event, sha=merge, **kw: run(  # noqa: E731
            repo, base, "pull_request", event, sha, ref="refs/pull/1/merge", **kw)
        bad_base = pr_event(main, feature)
        bad_base["pull_request"]["base"]["repo"]["full_name"] = "other/" + SENT
        wrong_ref = pr_event(main, feature)
        wrong_ref["pull_request"]["base"]["ref"] = "dev"
        closed = pr_event(main, feature)
        closed["action"] = "closed"
        cases = [
            run_pr(pr_event(stale, feature)),               # stale base: first parent differs
            run_pr(pr_event(main, stale)),                  # head is not the second parent
            run_pr(bad_base), run_pr(wrong_ref), run_pr(closed),
            run_pr(pr_event(main, feature), sha=feature),   # direct head checkout
            run_pr(pr_event(main, feature, branch="")),
            run_pr({"action": "opened"}),
            run_pr({"action": "opened", "pull_request": "x"}),
            run_pr(pr_event("0" * 40, feature)),
        ]
        return all(refused(c) for c in cases)
    guarded("CI.dispatch_pull_request_refuses_stale_or_inconsistent", pr_refusals)

    def pr_bad_branch_is_guard_usage_error():
        repo, base, main, feature, merge = setup("pr")
        rc, out, err = run(repo, base, "pull_request",
                           pr_event(main, feature, branch="bad..name" + SENT), merge,
                           ref="refs/pull/1/merge")
        return rc == 2 and SENT not in out + err and "guard: invalid arguments" in err
    guarded("CI.dispatch_invalid_asserted_branch_fails_closed", pr_bad_branch_is_guard_usage_error)


def _doc_checks(check):
    with open(os.path.join(ROOT, "docs", "security.md"), encoding="utf-8") as fh:
        doc = fh.read()
    trust = (
        "### CI trust assumptions\n\n"
        "- **Same-repository pull requests are trusted with `SENSITIVE_TERMS`.** This\n"
        "  repository is solo-owned and the secret holds `sha256:`-hashed terms only.\n"
        "  Workflow and guard code in a same-repository pull request can read the secret\n"
        "  during the `privacy-guard` job, and the owner accepts that. Revisit this\n"
        "  before anyone else gets push access.\n"
        "- **Fork pull requests do not receive the secret.** The built-in patterns and the\n"
        "  synthetic denylist tests still run, but owner terms are not checked there; that\n"
        "  is a known coverage gap, closed by running the guard locally before merge.\n"
        "- The workflow does not use `pull_request_target` or `workflow_run`, and no\n"
        "  secret is added or made conditional on the event.\n"
        "- Considered and rejected: providing the secret only on `push` to `main`. It\n"
        "  would keep it away from pull-request code but delay owner-term findings until\n"
        "  after merge.\n")
    hook = (
        "The history scan in `guard.py --full` accepts the environment Git gives a hook\n"
        "(`GIT_PREFIX`, `GIT_EXEC_PATH`, and `GIT_DIR` / `GIT_WORK_TREE` when they name\n"
        "this repository) and refuses any other inherited `GIT_*` variable with a\n"
        "generic message. `git -c key=value push` sets `GIT_CONFIG_PARAMETERS`, so repeat\n"
        "the push without `-c`. Do not work around a refusal with `--no-verify`.\n")
    check("DOC.ci_trust_assumptions_exact_bytes", doc.count(trust) == 1)
    check("DOC.hook_environment_paragraph_exact_bytes", doc.count(hook) == 1)
    check("DOC.states_path_trust_and_offline_wording",
          "trusted host inputs" in doc and "does not\n  enforce it" in doc)


def _hash_cli_ok(check):
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = guard.main(["--hash", "Wonder Land"])
    out = buf.getvalue().strip()
    check("guard --hash exit zero", rc == 0)
    check("guard --hash prints sha256", out.startswith("sha256:") and len(out) == 71)
    check("guard --hash is case-insensitive",
          out == "sha256:" + guard._sha256("wonder land"))


def main():
    passed, failed = [], []

    def check(name, cond):
        (passed if cond else failed).append(name)

    run(check)
    _hash_cli_ok(check)
    for name in passed:
        print(f"  ok   {name}")
    for name in failed:
        print(f"  FAIL {name}")
    print(f"\n{len(passed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
