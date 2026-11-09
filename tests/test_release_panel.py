#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Release-panel curation gates (R1B.*): the offline consistency suite for
docs/panel-curation.md and data/targets.release.json.

Run standalone:  python -B tests/test_release_panel.py
Or as part of:   python tests/test_pipeline.py

Every gate is isolated: a missing file, a missing function, or any exception
fails only that one check (via attempt()), never the whole run. All inputs for
the self-tests are invented; no real data is read.
"""
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

DATA = os.path.join(ROOT, "data")

# sha256 of the files this ticket must not touch (pinned on the base commit).
PINNED_HASHES = {
    "targets.carrier.json": "e9e7453a440ce51609b350b62a2f321c12374286355178edd3a52b47698c4f10",
    "targets.traits.json": "aabf84bfc412144214fc8f4f09eac8983a4ebaec0095c9cd2c9b16f6735fa6ce",
    "targets.sample.json": "0f1ae6151508f8bafeb3c64986d5f59c4cd0704f4ee6a859d795fe97047a93ad",
    "condition_aliases.json": "0960d4fa60a9f66c8927b0180226ca3551368afcaef7f0233105b3e68b91b1fb",
}


def _require(message, cond):
    if not cond:
        raise AssertionError(message)


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        digest.update(fh.read())
    return digest.hexdigest()


def _run_characterization(attempt):
    def char_draft_files_unchanged():
        for name, want in sorted(PINNED_HASHES.items()):
            path = os.path.join(DATA, name)
            _require(f"data/{name} missing", os.path.exists(path))
            got = _sha256_file(path)
            _require(f"data/{name} changed: sha256 {got} != pinned {want}", got == want)
        return True
    attempt("R1B.char_draft_files_unchanged", char_draft_files_unchanged)

    def char_guard_allows_release_targets_name():
        import guard
        found = guard.check_allowlist(["data/targets.release.json"])
        _require(f"guard refuses data/targets.release.json: {found}", found == [])
        return True
    attempt("R1B.char_guard_allows_release_targets_name", char_guard_allows_release_targets_name)


def run(check):
    def attempt(name, fn):
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001
            print(f"  detail {name}: {type(exc).__name__}: {exc}")
            check(name, False)
            return
        if not result:
            print(f"  detail {name}: gate returned false")
        check(name, bool(result))

    _run_characterization(attempt)


def main():
    passed, failed = [], []

    def check(name, cond):
        (passed if cond else failed).append(name)

    run(check)
    for name in passed:
        print(f"  ok   {name}")
    for name in failed:
        print(f"  FAIL {name}")
    print(f"\n{len(passed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
