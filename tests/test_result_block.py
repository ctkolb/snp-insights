#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Tests for scripts/validate_result_block.py. Run: python tests/test_result_block.py"""
import copy
import json
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import validate_result_block as v  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond):
    (PASSED if cond else FAILED).append(name)
    print(("  ok   " if cond else "  FAIL ") + name)


def wrap(block):
    return "prose\n===RESULT_JSON===\n" + json.dumps(block) + "\n===END_RESULT_JSON===\n"


def run(text, **kw):
    args = types.SimpleNamespace(role=kw.get("role"), stage=kw.get("stage"),
                                 expect_head=kw.get("expect_head"), max_calls=kw.get("max_calls"))
    return v.validate(text, args)


BUILDER = {
    "stage": "S1", "base_commit": "abc1234", "head_commit": "def5678",
    "tests_total": 10, "tests_red_before_code": 9, "tests_green_after": 10,
    "commits": ["bbb2222", "def5678"], "stop_condition_hit": None,
    "files_changed": ["tools/evidence.py"],
}
REVIEWER = {
    "stage": "S1", "reviewed_commit": "def5678", "reviewer_id": "model-x", "tool_calls_used": 12,
    "cases": [
        {"id": "c1", "result": "PASS", "severity": None, "file": None, "line": None, "repro": None},
        {"id": "c2", "result": "FAIL", "severity": "HIGH", "file": "a.py", "line": 3, "repro": "run x"},
    ],
    "top_defects": ["c2"], "surviving_mutations": [], "harness_path": "/tmp/h.py", "git_status_clean": True,
}


def mutated(base, **changes):
    out = copy.deepcopy(base)
    out.update(changes)
    return out


def dropped(base, key):
    out = copy.deepcopy(base)
    out.pop(key)
    return out


def ok(block, **kw):
    return run(wrap(block), **kw)[0] == []


def bad(block, **kw):
    return run(wrap(block), **kw)[0] != []


def main():
    # markers and JSON
    check("builder valid", ok(BUILDER))
    check("reviewer valid", ok(REVIEWER))
    check("no block rejected", run("just prose")[0] != [])
    check("two blocks rejected", run(wrap(BUILDER) + wrap(BUILDER))[0] != [])
    check("invalid json rejected", run("===RESULT_JSON===\n{nope\n===END_RESULT_JSON===")[0] != [])
    check("json array rejected", run("===RESULT_JSON===\n[1]\n===END_RESULT_JSON===")[0] != [])
    check("end before start rejected", run("===END_RESULT_JSON===\n{}\n===RESULT_JSON===")[0] != [])
    fenced = "===RESULT_JSON===\n```json\n" + json.dumps(BUILDER) + "\n```\n===END_RESULT_JSON==="
    check("fenced json tolerated", run(fenced)[0] == [])
    check("ambiguous role rejected", run(wrap({"stage": "S1"}))[0] != [])

    # builder
    for key in v.BUILDER_FIELDS:
        check("builder missing " + key, bad(dropped(BUILDER, key), role="builder"))
    check("builder red > total", bad(mutated(BUILDER, tests_red_before_code=11)))
    check("builder green > total", bad(mutated(BUILDER, tests_green_after=11)))
    check("builder bool is not int", bad(mutated(BUILDER, tests_total=True)))
    check("builder negative count", bad(mutated(BUILDER, tests_total=-1, tests_green_after=0, tests_red_before_code=0)))
    check("builder bad hash", bad(mutated(BUILDER, head_commit="HEAD")))
    check("builder head != last commit", bad(mutated(BUILDER, head_commit="1111111")))
    check("builder no commits needs head == base", bad(mutated(BUILDER, commits=[])))
    check("builder no commits, head == base ok", ok(mutated(BUILDER, commits=[], head_commit="abc1234")))
    check("builder stop reason ok", ok(mutated(BUILDER, stop_condition_hit="spec conflict")))
    check("builder empty stop string", bad(mutated(BUILDER, stop_condition_hit="  ")))
    check("builder files not list", bad(mutated(BUILDER, files_changed="a.py")))
    check("builder expect-head mismatch", bad(BUILDER, expect_head="9999999"))
    check("builder expect-head prefix match", ok(BUILDER, expect_head="def5678abcdef"))
    check("stage mismatch", bad(BUILDER, stage="S2"))

    # reviewer
    for key in v.REVIEWER_FIELDS:
        check("reviewer missing " + key, bad(dropped(REVIEWER, key), role="reviewer"))
    check("reviewer call cap exceeded", bad(REVIEWER, max_calls=10))
    check("reviewer call cap respected", ok(REVIEWER, max_calls=12))
    check("reviewer dirty git status", bad(mutated(REVIEWER, git_status_clean=False)))
    check("reviewer git_status_clean not bool", bad(mutated(REVIEWER, git_status_clean="yes")))
    check("reviewer empty cases", bad(mutated(REVIEWER, cases=[], top_defects=[])))
    check("reviewer top_defects not a fail case", bad(mutated(REVIEWER, top_defects=["c1"])))
    check("reviewer top_defects unknown id", bad(mutated(REVIEWER, top_defects=["zz"])))
    check("reviewer fails but no top_defects", bad(mutated(REVIEWER, top_defects=[])))
    many = copy.deepcopy(REVIEWER)
    many["cases"] = [{"id": "f%d" % i, "result": "FAIL", "severity": "LOW", "file": "a.py", "line": 1, "repro": "r"}
                     for i in range(4)]
    many["top_defects"] = ["f0", "f1", "f2", "f3"]
    check("reviewer more than 3 top_defects", bad(many))
    for field, value in (("severity", None), ("repro", ""), ("file", None), ("line", "x")):
        case = dict(REVIEWER["cases"][1], **{field: value})
        check("reviewer FAIL bad " + field, bad(mutated(REVIEWER, cases=[REVIEWER["cases"][0], case])))
    check("reviewer PASS with severity", bad(mutated(REVIEWER, cases=[dict(REVIEWER["cases"][0], severity="LOW")])))
    check("reviewer bad result word", bad(mutated(REVIEWER, cases=[dict(REVIEWER["cases"][0], result="OK")])))
    check("reviewer bad severity word", bad(mutated(REVIEWER, cases=[REVIEWER["cases"][0], dict(REVIEWER["cases"][1], severity="SEVERE")])))
    check("reviewer duplicate case id", bad(mutated(REVIEWER, cases=[REVIEWER["cases"][0], REVIEWER["cases"][0]], top_defects=[])))
    check("reviewer expect-head mismatch", bad(REVIEWER, expect_head="9999999"))
    check("reviewer mutations must be list", bad(mutated(REVIEWER, surviving_mutations="none")))
    check("reviewer all pass needs no top_defects", ok(mutated(REVIEWER, cases=[REVIEWER["cases"][0]], top_defects=[])))

    # tally
    problems, block, role = run(wrap(REVIEWER))
    check("tally reviewer", "fail C/H/M/L = 0/1/0/0" in v.tally(block, role))
    problems, block, role = run(wrap(BUILDER))
    check("tally builder", "9 red before code" in v.tally(block, role))

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
