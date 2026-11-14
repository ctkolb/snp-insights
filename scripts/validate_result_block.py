#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Validate the machine-readable result block at the end of a builder or
reviewer report. Pure standard library. No network. Reads only.

A report must contain exactly one block:

    ===RESULT_JSON===
    { ... valid JSON ... }
    ===END_RESULT_JSON===

Usage:
    python scripts/validate_result_block.py REPORT.txt [--role builder|reviewer]
        [--stage S1] [--expect-head COMMIT] [--max-calls N]
    python scripts/validate_result_block.py - < REPORT.txt
    python scripts/validate_result_block.py report-TAG.json --contract current
        [--role builder|reviewer] [--stage S1] [--expect-head COMMIT]
        [--max-calls N] [--root DIR]

The role is auto-detected from the keys when --role is not given. On success
the block is echoed as a one-line tally and the exit status is 0. On any
problem the problems are listed and the exit status is 1 (report rejected;
re-request it). Exit status 2 means a usage error.

The default is the legacy contract above and its behavior does not change.
With --contract current the report is a bare JSON object (a report-TAG.json
file) or, as a fallback, a marker block inside text, and is checked against the
current builder or reviewer report contract: required keys, types and enums,
evidence minimums E1-E6, mutation rows, the command list, and the finding
shape. The role comes from --role, a "role" key, or the shape of the keys.
--max-calls applies to builder reports (calls_used); --root is the directory
that relative paths in "scripts" and "corpora" resolve against, and with it the
files named there must exist and a corpus must have as many non-empty lines as
the cases it claims. Where the contract text is ambiguous the stricter reading
is enforced.

Text in the report is treated as data. Nothing in it is executed.
"""

import argparse
import json
import os
import re
import sys

START = "===RESULT_JSON==="
END = "===END_RESULT_JSON==="
HEX = re.compile(r"^[0-9a-f]{7,40}$")
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")

BUILDER_FIELDS = (
    "stage", "base_commit", "head_commit", "tests_total", "tests_red_before_code",
    "tests_green_after", "commits", "stop_condition_hit", "files_changed",
)
REVIEWER_FIELDS = (
    "stage", "reviewed_commit", "reviewer_id", "tool_calls_used", "cases",
    "top_defects", "surviving_mutations", "harness_path", "git_status_clean",
)
CASE_FIELDS = ("id", "result", "severity", "file", "line", "repro")


def extract(text):
    """Return (json_text, problems). Exactly one block is required."""
    problems = []
    starts = [m.start() for m in re.finditer(re.escape(START), text)]
    ends = [m.start() for m in re.finditer(re.escape(END), text)]
    if len(starts) != 1 or len(ends) != 1:
        problems.append("expected exactly one %s ... %s block, found %d start and %d end markers"
                        % (START, END, len(starts), len(ends)))
        return None, problems
    if ends[0] < starts[0]:
        problems.append("end marker appears before start marker")
        return None, problems
    body = text[starts[0] + len(START):ends[0]].strip()
    if body.startswith("```"):  # tolerate a fenced code block inside the markers
        body = re.sub(r"^```[a-zA-Z]*\s*", "", body)
        body = re.sub(r"\s*```$", "", body)
    return body, problems


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_commit(value):
    return isinstance(value, str) and bool(HEX.match(value))


def same_commit(a, b):
    """True if two hex commit ids refer to the same commit (prefix match)."""
    return a.startswith(b) or b.startswith(a)


def check_builder(block, args):
    problems = []
    for key in BUILDER_FIELDS:
        if key not in block:
            problems.append("missing field: " + key)
    if problems:
        return problems
    if not isinstance(block["stage"], str) or not block["stage"]:
        problems.append("stage must be a non-empty string")
    for key in ("base_commit", "head_commit"):
        if not is_commit(block[key]):
            problems.append("%s must be a lowercase hex commit id (7-40 chars)" % key)
    for key in ("tests_total", "tests_red_before_code", "tests_green_after"):
        if not is_int(block[key]) or block[key] < 0:
            problems.append("%s must be a non-negative integer" % key)
    if not problems:
        if block["tests_red_before_code"] > block["tests_total"]:
            problems.append("tests_red_before_code (%d) exceeds tests_total (%d)"
                            % (block["tests_red_before_code"], block["tests_total"]))
        if block["tests_green_after"] > block["tests_total"]:
            problems.append("tests_green_after (%d) exceeds tests_total (%d)"
                            % (block["tests_green_after"], block["tests_total"]))
    commits = block["commits"]
    if not isinstance(commits, list) or not all(is_commit(c) for c in commits):
        problems.append("commits must be a list of lowercase hex commit ids")
    elif commits and is_commit(block["head_commit"]) and not same_commit(commits[-1], block["head_commit"]):
        problems.append("last entry of commits does not match head_commit")
    elif not commits and block["head_commit"] != block["base_commit"]:
        problems.append("commits is empty but head_commit differs from base_commit")
    stop = block["stop_condition_hit"]
    if stop is not None and not (isinstance(stop, str) and stop.strip()):
        problems.append("stop_condition_hit must be null or a non-empty string")
    files = block["files_changed"]
    if not isinstance(files, list) or not all(isinstance(f, str) and f for f in files):
        problems.append("files_changed must be a list of non-empty strings")
    if args.expect_head and is_commit(block["head_commit"]) and not same_commit(block["head_commit"], args.expect_head):
        problems.append("head_commit %s does not match expected %s" % (block["head_commit"], args.expect_head))
    return problems


def check_reviewer(block, args):
    problems = []
    for key in REVIEWER_FIELDS:
        if key not in block:
            problems.append("missing field: " + key)
    if problems:
        return problems
    if not isinstance(block["stage"], str) or not block["stage"]:
        problems.append("stage must be a non-empty string")
    if not is_commit(block["reviewed_commit"]):
        problems.append("reviewed_commit must be a lowercase hex commit id (7-40 chars)")
    if not isinstance(block["reviewer_id"], str) or not block["reviewer_id"]:
        problems.append("reviewer_id must be a non-empty string")
    calls = block["tool_calls_used"]
    if not is_int(calls) or calls < 0:
        problems.append("tool_calls_used must be a non-negative integer")
    elif args.max_calls is not None and calls > args.max_calls:
        problems.append("tool_calls_used (%d) exceeds the cap (%d)" % (calls, args.max_calls))
    if not isinstance(block["git_status_clean"], bool):
        problems.append("git_status_clean must be true or false")
    elif block["git_status_clean"] is False:
        problems.append("reviewer reports git_status_clean=false (repository was modified)")
    if not isinstance(block["harness_path"], str) or not block["harness_path"]:
        problems.append("harness_path must be a non-empty string")
    mutations = block["surviving_mutations"]
    if not isinstance(mutations, list):
        problems.append("surviving_mutations must be a list")

    cases = block["cases"]
    fail_ids = set()
    if not isinstance(cases, list) or not cases:
        problems.append("cases must be a non-empty list")
        cases = []
    seen = set()
    for i, case in enumerate(cases):
        label = "cases[%d]" % i
        if not isinstance(case, dict):
            problems.append(label + " must be an object")
            continue
        for key in CASE_FIELDS:
            if key not in case:
                problems.append("%s missing field: %s" % (label, key))
        if any(key not in case for key in CASE_FIELDS):
            continue
        cid = case["id"]
        if not isinstance(cid, str) or not cid:
            problems.append(label + ".id must be a non-empty string")
            continue
        if cid in seen:
            problems.append("duplicate case id: " + cid)
        seen.add(cid)
        result, sev = case["result"], case["severity"]
        if result not in ("PASS", "FAIL"):
            problems.append("%s (%s) result must be PASS or FAIL" % (label, cid))
        elif result == "FAIL":
            fail_ids.add(cid)
            if sev not in SEVERITIES:
                problems.append("%s (%s) is FAIL and needs a severity of %s" % (label, cid, "/".join(SEVERITIES)))
            if not isinstance(case["repro"], str) or not case["repro"].strip():
                problems.append("%s (%s) is FAIL and needs a non-empty repro" % (label, cid))
            if not isinstance(case["file"], str) or not case["file"]:
                problems.append("%s (%s) is FAIL and needs a file" % (label, cid))
            if not is_int(case["line"]) or case["line"] < 0:
                problems.append("%s (%s) is FAIL and needs a non-negative integer line" % (label, cid))
        else:
            if sev is not None:
                problems.append("%s (%s) is PASS so severity must be null" % (label, cid))

    top = block["top_defects"]
    if not isinstance(top, list) or not all(isinstance(t, str) for t in top):
        problems.append("top_defects must be a list of case ids")
    else:
        if len(top) > 3:
            problems.append("top_defects lists %d ids; at most 3" % len(top))
        for tid in top:
            if tid not in fail_ids:
                problems.append("top_defects id %r is not a FAIL case" % tid)
        if fail_ids and not top:
            problems.append("there are FAIL cases but top_defects is empty")
    if args.expect_head and is_commit(block["reviewed_commit"]) and not same_commit(block["reviewed_commit"], args.expect_head):
        problems.append("reviewed_commit %s does not match expected %s" % (block["reviewed_commit"], args.expect_head))
    return problems


# ---- current contract (--contract current) ----

BUILDER_MODES_WITH_RED = ("BUILD", "FIX")
REVIEWER_MODES = ("SPEC", "CODE", "AUDIT", "CONFIRM_FIX", "DIGEST")
VERDICTS = ("READY", "READY_WITH_CHANGES", "NOT_READY")
EVIDENCE_IDS = ("E1", "E2", "E3", "E4", "E5", "E6")
EVIDENCE_VALUES = ("met", "not_required", "not_met")
HIGH = ("CRITICAL", "HIGH")


def _nes(x):
    return isinstance(x, str) and bool(x.strip())


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _enum(*values):
    return (lambda x: isinstance(x, str) and x in values), "one of " + ", ".join(values)


def _strlist(x):
    return isinstance(x, list) and all(_nes(i) for i in x)


NES = (_nes, "a non-empty string")
STR = (lambda x: isinstance(x, str), "a string")
NSTR = (lambda x: x is None or isinstance(x, str), "a string or null")
NNSTR = (lambda x: x is None or _nes(x), "a non-empty string or null")
HEXC = (is_commit, "a lowercase hex commit id (7-40 chars)")
INT = (is_int, "an integer")
NNINT = (lambda x: is_int(x) and x >= 0, "a non-negative integer")
POSINT = (lambda x: is_int(x) and x >= 1, "a positive integer")
NUM = (_num, "a number")
BOOL = (lambda x: isinstance(x, bool), "true or false")
LIST = (lambda x: isinstance(x, list), "a list")
STRLIST = (_strlist, "a list of non-empty strings")
MODULES = (lambda x: _strlist(x) and bool(x), "a non-empty list of strings")
OBJ = (lambda x: isinstance(x, dict), "an object")
SEV = _enum(*SEVERITIES)

CHECK_ROW = (("command", NES), ("exit_code", INT), ("log", NES))
MUTANT_ROW = (("name", NES), ("result", _enum("KILLED", "SURVIVED", "EQUIVALENT")))
ADDRESSED_ROW = (("id", NES), ("outcome", _enum("fixed", "not_reproduced", "disputed")))
CANDIDATE_ROW = (
    ("id", NES), ("title", NES), ("file", NES), ("line", NNINT), ("category", NES), ("contract", NES),
    ("evidence", _enum("REPRODUCED", "SUSPECTED")), ("severity", SEV), ("fix_size", _enum("S", "M", "L")),
    ("fix_files", STRLIST), ("fix_risk", NES), ("depends_on", STRLIST), ("reproduction", NSTR),
)
B_COVERAGE_ROW = (("area", NES), ("depth", _enum("read", "executed", "profiled", "not_examined")), ("note", STR))
B_MEASUREMENT_ROW = (
    ("metric", NES), ("method", NES), ("baseline_commit", HEXC), ("base", NUM), ("after", NUM),
    ("runs", NNINT), ("spread", STR), ("within_noise", BOOL),
)
ADJACENT_ROW = (("title", NES), ("file", NES), ("line", NNINT), ("severity", SEV), ("evidence", NES))

BUILDER_SPEC = (
    ("session", NES), ("stage", NES), ("mode", NES), ("base_commit", HEXC), ("head_commit", HEXC),
    ("status", _enum("ready", "blocked")), ("plan_first", BOOL), ("sheet_path", NNSTR),
    ("calls_used", NNINT), ("calls_limit", POSINT), ("remaining_work", STRLIST),
    ("files_changed", STRLIST), ("contracts_addressed", STRLIST), ("checks", LIST),
    ("red_kind", _enum("FAILING", "CHARACTERIZATION", "NONE", "n/a")), ("red_evidence", LIST),
    ("mutants", LIST), ("findings_addressed", LIST), ("candidates", LIST), ("coverage", LIST),
    ("measurements", LIST), ("adjacent_findings", LIST), ("report_path", NES), ("blockers", STRLIST),
)
BUILDER_ROWS = (
    ("checks", CHECK_ROW), ("mutants", MUTANT_ROW), ("findings_addressed", ADDRESSED_ROW),
    ("candidates", CANDIDATE_ROW), ("coverage", B_COVERAGE_ROW), ("measurements", B_MEASUREMENT_ROW),
    ("adjacent_findings", ADJACENT_ROW),
)

EXPORT_ROW = (("role", _enum("tip", "base", "context")), ("path", NES), ("sha", HEXC))
R_COVERAGE_ROW = (
    ("attack", NES), ("stage", NES), ("result", _enum("PASS", "FAIL", "NOT_CHECKED")),
    ("depth", _enum("read", "executed", "profiled", "mutated", "n/a")), ("evidence", NES),
)
FINDING_ROW = (
    ("id", NES), ("type", _enum("defect", "decision_issue", "scope_issue")),
    ("confidence", _enum("reproduced", "source_supported", "suspected")), ("contract", NES),
    ("severity", SEV), ("status", _enum("open", "fixed", "disputed", "not_checked")),
    ("file", NNSTR), ("line", (lambda x: x is None or (is_int(x) and x >= 0), "a non-negative integer or null")),
    ("expected", NES), ("actual", NES), ("reproduction", NNSTR), ("reproduction_output", NNSTR),
    ("base_commit_result", NSTR), ("proposed_test", NNSTR), ("proposed_fix", NNSTR),
)
R_MEASUREMENT_ROW = (
    ("metric", NES), ("method", NES), ("base", NUM), ("after", NUM), ("runs", NNINT),
    ("spread", STR), ("within_noise", BOOL),
)
MUTATION_ROW = (
    ("name", NES), ("file", NES), ("anchor", NES), ("replacement", STR),
    ("modules", MODULES), ("expect", _enum("KILLED", "EQUIVALENT")), ("why", STR),
    ("result", _enum("KILLED", "SURVIVED", "EQUIVALENT", "INVALID")),
)
BUILDER_MUTANTS_ROW = (
    ("file", NES), ("rows", NNINT), ("killed", NNINT), ("survived", STRLIST), ("invalid", NNINT),
)
CORPUS_ROW = (("file", NES), ("cases", NNINT), ("seed", INT), ("oracle", NES))
COMMAND_ROW = (("command", NES), ("exit_code", INT))
SCRIPT_ROW = (("path", NES), ("output", STR))
VERSIONS_SPEC = (("language", NES), ("tests_run", NNINT))
VALIDATOR_SPEC = (
    ("status", _enum("passed", "failed", "not_available")), ("command", NNSTR),
    ("exit_code", (lambda x: x is None or is_int(x), "an integer or null")), ("output", NSTR),
)

REVIEWER_SPEC = (
    ("session", NES), ("stage", NES), ("reviewed_commit", HEXC), ("reviewed_exports", LIST),
    ("mode", _enum(*REVIEWER_MODES)), ("verdict", _enum(*VERDICTS)), ("coverage", LIST),
    ("findings", LIST), ("measurements", LIST), ("mutations", LIST), ("builder_mutants", LIST),
    ("corpora", LIST), ("commands", LIST), ("scripts", LIST), ("versions", OBJ),
    ("evidence_minimums", OBJ), ("validator", OBJ), ("isolation_note", NES),
    ("riskiest_points", STRLIST), ("not_checked", STRLIST),
    ("verification_tooling", _enum("approved", "issues", "not_reviewed", "unchanged")),
    ("report_path", NES), ("repository_unchanged", BOOL),
    ("status", _enum("complete", "incomplete", "blocked")),
)
REVIEWER_ROWS = (
    ("reviewed_exports", EXPORT_ROW), ("coverage", R_COVERAGE_ROW), ("findings", FINDING_ROW),
    ("measurements", R_MEASUREMENT_ROW), ("mutations", MUTATION_ROW),
    ("builder_mutants", BUILDER_MUTANTS_ROW), ("corpora", CORPUS_ROW), ("commands", COMMAND_ROW),
    ("scripts", SCRIPT_ROW),
)

BUILDER_ONLY = ("base_commit", "head_commit", "calls_used", "calls_limit", "checks", "red_kind", "plan_first")
REVIEWER_ONLY = ("reviewed_commit", "reviewed_exports", "verdict", "findings", "evidence_minimums",
                 "validator", "repository_unchanged")


def check_object(problems, prefix, obj, spec):
    """Check that obj has every key of spec with a valid value. Return True if clean."""
    if not isinstance(obj, dict):
        problems.append((prefix.rstrip(".") or "report") + " must be an object")
        return False
    before = len(problems)
    for key, _ in spec:
        if key not in obj:
            problems.append("%s missing field: %s" % (prefix.rstrip("."), key) if prefix else "missing field: " + key)
    if len(problems) != before:
        return False
    for key, (pred, desc) in spec:
        if not pred(obj[key]):
            problems.append("%s%s must be %s" % (prefix, key, desc))
    return len(problems) == before


def check_rows(problems, block, rows_spec):
    for name, spec in rows_spec:
        rows = block[name]
        if isinstance(rows, list):
            for i, row in enumerate(rows):
                check_object(problems, "%s[%d]." % (name, i), row, spec)


def current_role(block, args):
    problems = []
    declared = block.get("role")
    if "role" in block and declared not in ("builder", "reviewer"):
        problems.append("role must be builder or reviewer, got %r" % (declared,))
        return None, problems
    if args.role and declared is not None and declared != args.role:
        problems.append("role %r in the report conflicts with --role %s" % (declared, args.role))
        return None, problems
    role = args.role or declared
    if role is None:
        builder = sum(1 for k in BUILDER_ONLY if k in block)
        reviewer = sum(1 for k in REVIEWER_ONLY if k in block)
        if builder != reviewer:
            role = "builder" if builder > reviewer else "reviewer"
    if role is None:
        problems.append("cannot tell builder from reviewer; add a role key or pass --role")
    return role, problems


def check_current_builder(block, args):
    problems = []
    missing = ["missing field: " + k for k, _ in BUILDER_SPEC if k not in block]
    if missing:
        return missing
    check_object(problems, "", block, BUILDER_SPEC)
    check_rows(problems, block, BUILDER_ROWS)
    if problems:
        return problems
    if block["calls_used"] > block["calls_limit"]:
        problems.append("calls_used (%d) exceeds calls_limit (%d)" % (block["calls_used"], block["calls_limit"]))
    if args.max_calls is not None and block["calls_used"] > args.max_calls:
        problems.append("calls_used (%d) exceeds --max-calls (%d)" % (block["calls_used"], args.max_calls))
    if args.expect_head and not same_commit(block["head_commit"], args.expect_head):
        problems.append("head_commit %s does not match expected %s" % (block["head_commit"], args.expect_head))
    if block["plan_first"] and not _nes(block["sheet_path"]):
        problems.append("plan_first is true but sheet_path is not a non-empty string")
    if block["status"] == "blocked" and not (block["blockers"] or block["remaining_work"]):
        problems.append("status is blocked but blockers and remaining_work are both empty")
    mode_words = set(re.findall(r"[A-Z]+", block["mode"].upper()))
    if mode_words & set(BUILDER_MODES_WITH_RED):
        if block["red_kind"] == "n/a":
            problems.append("red_kind must not be n/a in a BUILD or FIX report")
        if block["status"] == "ready" and not block["checks"]:
            problems.append("checks must list the verification commands of a ready BUILD or FIX report")
    if block["red_kind"] in ("FAILING", "CHARACTERIZATION") and not block["red_evidence"]:
        problems.append("red_evidence must not be empty when red_kind is %s" % block["red_kind"])
    if "SURVEY" in mode_words and not block["coverage"]:
        problems.append("coverage must not be empty in a SURVEY report")
    if block["status"] == "ready":
        for i, row in enumerate(block["mutants"]):
            if row["result"] == "SURVIVED":
                problems.append("mutants[%d] (%s) is SURVIVED; kill it with a test before reporting ready" % (i, row["name"]))
    for i, row in enumerate(block["candidates"]):
        if row["evidence"] == "REPRODUCED" and not _nes(row["reproduction"]):
            problems.append("candidates[%d] (%s) is REPRODUCED and needs a non-empty reproduction" % (i, row["id"]))
    return problems


def corpus_lines(path):
    count = 0
    with open(path, "rb") as fh:
        for line in fh:
            if line.strip():
                count += 1
    return count


def check_named_files(problems, block, root):
    """Files named in scripts and corpora must exist under root; a corpus line count must match."""
    def resolve(path):
        return path if os.path.isabs(path) else os.path.join(root, path)
    for i, row in enumerate(block["scripts"]):
        if not os.path.isfile(resolve(row["path"])):
            problems.append("scripts[%d].path %r does not exist as a file under the root" % (i, row["path"]))
    for i, row in enumerate(block["corpora"]):
        path = resolve(row["file"])
        if not os.path.isfile(path):
            problems.append("corpora[%d].file %r does not exist as a file under the root" % (i, row["file"]))
            continue
        try:
            lines = corpus_lines(path)
        except OSError as exc:
            problems.append("corpora[%d].file %r cannot be read: %s" % (i, row["file"], exc))
            continue
        if lines != row["cases"]:
            problems.append("corpora[%d].cases (%d) does not match %d non-empty lines in %s"
                            % (i, row["cases"], lines, row["file"]))


def check_finding(problems, i, f, mode):
    label = "findings[%d] (%s)" % (i, f["id"])
    reproduced = f["confidence"] == "reproduced"
    if f["type"] == "defect":
        if not _nes(f["file"]) or f["line"] is None:
            problems.append("%s is a defect and needs a file and a line" % label)
        if mode in ("CODE", "CONFIRM_FIX") and not reproduced:
            problems.append("%s is a defect in %s and must have confidence reproduced" % (label, mode))
    if f["confidence"] == "suspected" and mode not in ("AUDIT", "SPEC"):
        problems.append("%s has confidence suspected, which only AUDIT and SPEC may use" % label)
    if f["type"] == "decision_issue" and reproduced:
        problems.append("%s is a decision_issue; use confidence source_supported, not reproduced" % label)
    if f["confidence"] == "source_supported" and (f["reproduction"] is not None or f["reproduction_output"] is not None):
        problems.append("%s is source_supported, so reproduction and reproduction_output must be null" % label)
    if mode in ("CODE", "AUDIT", "SPEC") and f["status"] != "open":
        problems.append("%s status must be open in %s" % (label, mode))
    if reproduced:
        if not _nes(f["reproduction"]):
            problems.append("%s is reproduced and needs a reproduction command" % label)
        if not _nes(f["reproduction_output"]):
            problems.append("%s is reproduced and needs a reproduction_output file" % label)
        if f["type"] == "defect" and mode in ("CODE", "AUDIT"):
            if f["severity"] != "LOW" and not _nes(f["proposed_test"]):
                problems.append("%s is a reproduced %s defect and needs a proposed_test" % (label, f["severity"]))
            if not _nes(f["proposed_fix"]):
                problems.append("%s is a reproduced defect and needs a proposed_fix" % label)


def check_current_reviewer(block, args):
    problems = []
    missing = ["missing field: " + k for k, _ in REVIEWER_SPEC if k not in block]
    if missing:
        return missing
    check_object(problems, "", block, REVIEWER_SPEC)
    check_rows(problems, block, REVIEWER_ROWS)
    evidence = block["evidence_minimums"]
    if isinstance(evidence, dict):
        for key in EVIDENCE_IDS:
            if key not in evidence:
                problems.append("evidence_minimums missing field: " + key)
            elif evidence[key] not in EVIDENCE_VALUES:
                problems.append("evidence_minimums.%s must be one of %s" % (key, ", ".join(EVIDENCE_VALUES)))
    if isinstance(block["versions"], dict):
        check_object(problems, "versions.", block["versions"], VERSIONS_SPEC)
    validator = block["validator"]
    if isinstance(validator, dict):
        check_object(problems, "validator.", validator, VALIDATOR_SPEC)
    if problems:
        return problems

    mode = block["mode"]
    if args.max_calls is not None:
        problems.append("--max-calls cannot be checked: the current reviewer report has no call counter")
    if args.expect_head and not same_commit(block["reviewed_commit"], args.expect_head):
        problems.append("reviewed_commit %s does not match expected %s" % (block["reviewed_commit"], args.expect_head))
    if block["repository_unchanged"] is False:
        problems.append("repository_unchanged is false (the reviewer modified the repository)")
    tips = [e for e in block["reviewed_exports"] if e["role"] == "tip"]
    if mode in ("CODE", "CONFIRM_FIX") and not tips:
        problems.append("reviewed_exports needs a tip export in %s" % mode)
    for e in tips:
        if not same_commit(e["sha"], block["reviewed_commit"]):
            problems.append("tip export sha %s does not match reviewed_commit %s" % (e["sha"], block["reviewed_commit"]))
    if mode != "DIGEST" and not block["coverage"]:
        problems.append("coverage must not be empty in %s" % mode)

    ids = set()
    for i, f in enumerate(block["findings"]):
        if f["id"] in ids:
            problems.append("duplicate finding id: " + f["id"])
        ids.add(f["id"])
        check_finding(problems, i, f, mode)
    open_defects = [f for f in block["findings"]
                    if f["type"] == "defect" and f["status"] == "open" and f["confidence"] == "reproduced"]
    high = [f["id"] for f in open_defects if f["severity"] in HIGH]
    verdict = block["verdict"]
    if mode == "DIGEST":
        if verdict == "READY_WITH_CHANGES":
            problems.append("verdict must be READY or NOT_READY in DIGEST")
    elif mode == "AUDIT":
        want = "NOT_READY" if high else "READY_WITH_CHANGES" if open_defects else "READY"
        if verdict != want:
            problems.append("verdict is %s but the reproduced defects call for %s in AUDIT" % (verdict, want))
    elif high and verdict == "READY":
        problems.append("verdict is READY but CRITICAL or HIGH defects are open (%s)" % ", ".join(high))

    names = set()
    for i, m in enumerate(block["mutations"]):
        if m["name"] in names:
            problems.append("duplicate mutation name: " + m["name"])
        names.add(m["name"])
        if "EQUIVALENT" in (m["expect"], m["result"]) and not _nes(m["why"]):
            problems.append("mutations[%d] (%s) is EQUIVALENT and needs a why" % (i, m["name"]))
    for i, b in enumerate(block["builder_mutants"]):
        if b["killed"] + len(b["survived"]) + b["invalid"] > b["rows"]:
            problems.append("builder_mutants[%d] counts (killed, survived, invalid) exceed rows" % i)

    if not block["commands"]:
        problems.append("commands must list the exact commands run with their exit codes")
    if mode not in ("SPEC", "DIGEST") and block["versions"]["tests_run"] < 1:
        problems.append("versions.tests_run must be at least 1 in %s" % mode)
    reproduced = any(f["confidence"] == "reproduced" for f in block["findings"])
    if reproduced and not block["scripts"]:
        problems.append("scripts must list the saved reproduction scripts of reproduced findings")

    for key in EVIDENCE_IDS:
        if evidence[key] == "not_met":
            problems.append("evidence_minimums.%s is not_met" % key)
    if evidence["E4"] != "met":
        problems.append("E4 must be met: every report records its commands, versions and test count")
    if block["corpora"] and evidence["E1"] != "met":
        problems.append("E1 must be met when corpora are listed, got %s" % evidence["E1"])
    if evidence["E1"] == "met" and not block["corpora"]:
        problems.append("E1 is met but corpora is empty")
    if evidence["E2"] == "met" and not (block["mutations"] or block["builder_mutants"]):
        problems.append("E2 is met but there are no mutations or builder_mutants rows")
    if reproduced:
        for key in ("E3", "E5", "E6"):
            if evidence[key] != "met":
                problems.append("%s must be met when a finding is reproduced, got %s" % (key, evidence[key]))

    if validator["status"] == "not_available":
        for key in ("command", "exit_code", "output"):
            if validator[key] is not None:
                problems.append("validator.%s must be null when status is not_available" % key)
    elif validator["status"] == "passed":
        if not _nes(validator["command"]):
            problems.append("validator.command must be a non-empty string when status is passed")
        if validator["exit_code"] != 0 or isinstance(validator["exit_code"], bool):
            problems.append("validator.exit_code must be 0 when status is passed")
        if not isinstance(validator["output"], str):
            problems.append("validator.output must be a string when status is passed")
    else:
        problems.append("validator status is failed; fix the report and rerun the validator")

    if args.root:
        check_named_files(problems, block, args.root)
    return problems


def validate_current(text, args):
    """Return (problems, block, role) for a bare report JSON or a marker block."""
    try:
        block = json.loads(text)
    except ValueError as exc:
        if START not in text:
            return ["report is not valid JSON and has no %s block: %s" % (START, exc)], None, None
        body, problems = extract(text)
        if body is None:
            return problems, None, None
        try:
            block = json.loads(body)
        except ValueError as inner:
            return ["block is not valid JSON: %s" % inner], None, None
    if not isinstance(block, dict):
        return ["report must be a JSON object"], None, None
    role, problems = current_role(block, args)
    if role is None:
        return problems, block, None
    if args.stage and block.get("stage") != args.stage:
        problems.append("stage is %r, expected %r" % (block.get("stage"), args.stage))
    check = check_current_builder if role == "builder" else check_current_reviewer
    problems += check(block, args)
    return problems, block, role


def tally_current(block, role):
    if role == "builder":
        return ("builder current %s %s: status=%s, calls %d/%d, %d checks, head %s"
                % (block["stage"], block["mode"], block["status"], block["calls_used"],
                   block["calls_limit"], len(block["checks"]), block["head_commit"]))
    counts = {s: 0 for s in SEVERITIES}
    for f in block["findings"]:
        counts[f["severity"]] += 1
    return ("reviewer current %s %s: verdict=%s, %d findings C/H/M/L = %d/%d/%d/%d, %d mutation rows, status=%s"
            % (block["stage"], block["mode"], block["verdict"], len(block["findings"]), counts["CRITICAL"],
               counts["HIGH"], counts["MEDIUM"], counts["LOW"], len(block["mutations"]), block["status"]))


def detect_role(block):
    builder = sum(1 for k in BUILDER_FIELDS if k in block)
    reviewer = sum(1 for k in REVIEWER_FIELDS if k in block)
    if builder == reviewer:
        return None
    return "builder" if builder > reviewer else "reviewer"


def validate(text, args):
    """Return (problems, block, role)."""
    if getattr(args, "contract", "legacy") == "current":
        return validate_current(text, args)
    body, problems = extract(text)
    if body is None:
        return problems, None, None
    try:
        block = json.loads(body)
    except ValueError as exc:
        return ["block is not valid JSON: %s" % exc], None, None
    if not isinstance(block, dict):
        return ["block must be a JSON object"], None, None
    role = args.role or detect_role(block)
    if role is None:
        return ["cannot tell builder from reviewer; pass --role"], block, None
    if args.stage and block.get("stage") != args.stage:
        problems.append("stage is %r, expected %r" % (block.get("stage"), args.stage))
    check = check_builder if role == "builder" else check_reviewer
    problems += check(block, args)
    return problems, block, role


def tally(block, role):
    if role == "builder":
        return ("builder %s: %s tests, %s red before code, %s green after, %d commits, stop=%s"
                % (block["stage"], block["tests_total"], block["tests_red_before_code"],
                   block["tests_green_after"], len(block["commits"]), block["stop_condition_hit"]))
    counts = {s: 0 for s in SEVERITIES}
    passes = 0
    for case in block["cases"]:
        if case["result"] == "PASS":
            passes += 1
        else:
            counts[case["severity"]] += 1
    return ("reviewer %s: %d calls, %d pass, fail C/H/M/L = %d/%d/%d/%d, %d surviving mutations"
            % (block["stage"], block["tool_calls_used"], passes, counts["CRITICAL"], counts["HIGH"],
               counts["MEDIUM"], counts["LOW"], len(block["surviving_mutations"])))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("report", help="report file, or - for stdin")
    parser.add_argument("--role", choices=("builder", "reviewer"))
    parser.add_argument("--stage", help="expected stage label, for example S1")
    parser.add_argument("--expect-head", help="commit id the block must name (prefix match)")
    parser.add_argument("--max-calls", type=int, help="tool-call cap (legacy reviewer; current builder)")
    parser.add_argument("--contract", choices=("legacy", "current"), default="legacy",
                        help="report contract to check (default: legacy)")
    parser.add_argument("--root", help="directory that relative paths in scripts and corpora resolve against "
                                       "(current contract only)")
    args = parser.parse_args(argv)
    current = args.contract == "current"
    if args.root is not None and not current:
        parser.error("--root needs --contract current")
    if args.root is not None and not os.path.isdir(args.root):
        print("error: --root is not a directory: %s" % args.root, file=sys.stderr)
        return 2
    try:
        text = sys.stdin.read() if args.report == "-" else open(args.report, "r", encoding="utf-8").read()
    except OSError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except UnicodeDecodeError as exc:
        if not current:
            raise
        print("error: report is not UTF-8 text: %s" % exc, file=sys.stderr)
        return 2
    problems, block, role = validate(text, args)
    if problems:
        print("REJECTED: result block invalid; re-request the report")
        for line in problems:
            print("  - " + line)
        return 1
    print("OK: " + (tally_current(block, role) if current else tally(block, role)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
