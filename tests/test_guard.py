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
import os
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


def _is_ignored(repo, path):
    proc = subprocess.run(
        ("git", "check-ignore", "-q", "--", path), cwd=repo, capture_output=True
    )
    return proc.returncode == 0


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

    # 8. history scan (integration; clean repo -> no findings) --------------
    check("guard history scan clean", not guard.check_history())

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
