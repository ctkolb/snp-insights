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

The role is auto-detected from the keys when --role is not given. On success
the block is echoed as a one-line tally and the exit status is 0. On any
problem the problems are listed and the exit status is 1 (report rejected;
re-request it). Exit status 2 means a usage error.

Text in the report is treated as data. Nothing in it is executed.
"""

import argparse
import json
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


def detect_role(block):
    builder = sum(1 for k in BUILDER_FIELDS if k in block)
    reviewer = sum(1 for k in REVIEWER_FIELDS if k in block)
    if builder == reviewer:
        return None
    return "builder" if builder > reviewer else "reviewer"


def validate(text, args):
    """Return (problems, block, role)."""
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
    parser.add_argument("--max-calls", type=int, help="reviewer tool-call cap")
    args = parser.parse_args(argv)
    try:
        text = sys.stdin.read() if args.report == "-" else open(args.report, "r", encoding="utf-8").read()
    except OSError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    problems, block, role = validate(text, args)
    if problems:
        print("REJECTED: result block invalid; re-request the report")
        for line in problems:
            print("  - " + line)
        return 1
    print("OK: " + tally(block, role))
    return 0


if __name__ == "__main__":
    sys.exit(main())
