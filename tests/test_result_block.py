#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Tests for scripts/validate_result_block.py. Run: python tests/test_result_block.py"""
import copy
import io
import json
import os
import sys
import tempfile
import types
from contextlib import redirect_stderr, redirect_stdout

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


# ---- current contract mode ----
# Required keys and enums are written out here from the role contracts, not imported
# from the validator, so a wrong constant in the validator cannot hide itself.
C_BUILDER_KEYS = (
    "session", "stage", "mode", "base_commit", "head_commit", "status", "plan_first", "sheet_path",
    "calls_used", "calls_limit", "remaining_work", "files_changed", "contracts_addressed", "checks",
    "red_kind", "red_evidence", "mutants", "findings_addressed", "candidates", "coverage",
    "measurements", "adjacent_findings", "report_path", "blockers",
)
C_REVIEWER_KEYS = (
    "session", "stage", "reviewed_commit", "reviewed_exports", "mode", "verdict", "coverage",
    "findings", "measurements", "mutations", "builder_mutants", "corpora", "commands", "scripts",
    "versions", "evidence_minimums", "validator", "isolation_note", "riskiest_points", "not_checked",
    "verification_tooling", "report_path", "repository_unchanged", "status",
)


def runc(text, **kw):
    args = types.SimpleNamespace(role=kw.get("role"), stage=kw.get("stage"),
                                 expect_head=kw.get("expect_head"), max_calls=kw.get("max_calls"),
                                 contract="current", root=kw.get("root"))
    try:
        return v.validate(text, args)
    except Exception as exc:  # a crash is a failed check, not a pass
        return ["EXC %r" % exc], None, None


def cok(block, **kw):
    return runc(json.dumps(block), **kw)[0] == []


def cbad(block, needle, **kw):
    problems = runc(json.dumps(block), **kw)[0]
    return any(needle in p for p in problems if not p.startswith("EXC"))


def cli(argv):
    out = io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            rc = v.main(argv)
    except SystemExit as exc:
        rc = exc.code
    except Exception as exc:  # a crash is a failed check, not a pass
        rc = "EXC %r" % exc
    return rc, out.getvalue()


def setd(base, path, value):
    """Deep copy of base with base[path[0]][path[1]]... set to value."""
    out = copy.deepcopy(base)
    node = out
    for part in path[:-1]:
        node = node[part]
    node[path[-1]] = value
    return out


FINDING = {
    "id": "F-1", "type": "defect", "confidence": "reproduced", "contract": "contract text",
    "severity": "MEDIUM", "status": "open", "file": "a.py", "line": 3, "expected": "x", "actual": "y",
    "reproduction": "sh repro.sh", "reproduction_output": "repro.out", "base_commit_result": "passes",
    "proposed_test": "t.py", "proposed_fix": "f.patch",
}
MUTATION = {
    "name": "m1", "file": "a.py", "anchor": "x > 1", "replacement": "x > 2", "modules": ["tests/t.py"],
    "expect": "KILLED", "why": "boundary", "result": "KILLED",
}
CREVIEWER = {
    "session": "tag-r1", "stage": "S1", "reviewed_commit": "def5678",
    "reviewed_exports": [{"role": "tip", "path": "/x/tip", "sha": "def5678"},
                         {"role": "base", "path": "/x/base", "sha": "abc1234"}],
    "mode": "CODE", "verdict": "READY_WITH_CHANGES",
    "coverage": [{"attack": "a1", "stage": "S1", "result": "PASS", "depth": "executed", "evidence": "ran it"}],
    "findings": [FINDING], "measurements": [], "mutations": [MUTATION],
    "builder_mutants": [{"file": "m.json", "rows": 6, "killed": 5, "survived": [], "invalid": 0}],
    "corpora": [{"file": "corpus-cases.jsonl", "cases": 2, "seed": 1, "oracle": "contract text"}],
    "commands": [{"command": "python tests/test_pipeline.py", "exit_code": 0}],
    "scripts": [{"path": "repro.sh", "output": "repro.out"}],
    "versions": {"language": "Python 3.12.1", "tests_run": 120},
    "evidence_minimums": {"E1": "met", "E2": "met", "E3": "met", "E4": "met", "E5": "met", "E6": "met"},
    "validator": {"status": "passed", "command": "python v.py r.json", "exit_code": 0, "output": "OK"},
    "isolation_note": "ran in scratch", "riskiest_points": ["p"], "not_checked": [],
    "verification_tooling": "approved", "report_path": "/x/report.md",
    "repository_unchanged": True, "status": "complete",
}
CBUILDER = {
    "session": "tag-r2", "stage": "S1", "mode": "BUILD", "base_commit": "abc1234", "head_commit": "def5678",
    "status": "ready", "plan_first": False, "sheet_path": None, "calls_used": 40, "calls_limit": 90,
    "remaining_work": [], "files_changed": ["scripts/x.py"], "contracts_addressed": ["c1"],
    "checks": [{"command": "python tests/test_pipeline.py", "exit_code": 0, "log": "/x/log.txt"}],
    "red_kind": "FAILING", "red_evidence": ["t1 failed before the fix"],
    "mutants": [{"name": "m1", "result": "KILLED"}],
    "findings_addressed": [{"id": "F-1", "outcome": "fixed"}], "candidates": [], "coverage": [],
    "measurements": [], "adjacent_findings": [], "report_path": "/x/report.md", "blockers": [],
}
CANDIDATE = {
    "id": "S-1", "title": "t", "file": "a.py", "line": 1, "category": "bug", "contract": "c",
    "evidence": "REPRODUCED", "severity": "MEDIUM", "fix_size": "S", "fix_files": ["a.py"],
    "fix_risk": "low", "depends_on": [], "reproduction": "sh r.sh",
}
CSURVEY = dict(CBUILDER, mode="SURVEY", red_kind="n/a", red_evidence=[], mutants=[],
               findings_addressed=[], candidates=[CANDIDATE],
               coverage=[{"area": "a", "depth": "read", "note": "n"}])


def test_current_mode():
    # transport and role
    check("current: builder bare json ok", cok(CBUILDER))
    check("current: reviewer bare json ok", cok(CREVIEWER))
    check("current: survey builder ok", cok(CSURVEY))
    check("current: block inside text ok", runc(wrap(CBUILDER))[0] == [])
    check("current: not json rejected", cbad_text("just prose", "not valid JSON"))
    check("current: broken block rejected", cbad_text("===RESULT_JSON===\n{nope\n===END_RESULT_JSON===", "block is not valid JSON"))
    check("current: two blocks rejected", cbad_text(wrap(CBUILDER) + wrap(CBUILDER), "exactly one"))
    check("current: json array rejected", cbad_text("[1]", "object"))
    check("current: role key used", cok(dict(CBUILDER, role="builder")))
    check("current: role key vs --role conflict", cbad(dict(CBUILDER, role="reviewer"), "role", role="builder"))
    check("current: bad role value", cbad(dict(CBUILDER, role="boss"), "role"))
    check("current: ambiguous shape rejected", cbad({"stage": "S1"}, "role"))
    check("current: --role override", cok(CBUILDER, role="builder"))
    check("current: legacy block rejected in current mode", cbad(BUILDER, "missing field"))
    check("current: bare json rejected in legacy mode", run(json.dumps(CBUILDER))[0] != [])
    check("current: stage mismatch", cbad(CBUILDER, "stage", stage="S2"))
    check("current: stage match", cok(CBUILDER, stage="S1"))

    # builder
    for key in C_BUILDER_KEYS:
        check("current builder missing " + key, cbad(dropped(CBUILDER, key), "missing field: " + key, role="builder"))
    for field, value in (("status", "done"), ("red_kind", "SOME"), ("session", ""), ("stage", ""), ("mode", ""),
                         ("plan_first", "no"), ("calls_used", "9"), ("calls_used", True), ("calls_used", -1),
                         ("calls_limit", 0), ("calls_limit", 1.5), ("base_commit", "HEAD"),
                         ("head_commit", "XYZ"), ("sheet_path", 5), ("report_path", ""),
                         ("remaining_work", "x"), ("files_changed", "a.py"), ("files_changed", [""]),
                         ("contracts_addressed", "c"), ("red_evidence", "x"), ("blockers", "x"),
                         ("blockers", [1]), ("measurements", {}), ("adjacent_findings", "x")):
        check("current builder bad %s=%r" % (field, value), cbad(mutated(CBUILDER, **{field: value}), field))
    check("current builder calls over limit", cbad(mutated(CBUILDER, calls_used=91), "calls_used"))
    check("current builder calls at limit ok", cok(mutated(CBUILDER, calls_used=90)))
    check("current builder --max-calls exceeded", cbad(CBUILDER, "max-calls", max_calls=39))
    check("current builder --max-calls respected", cok(CBUILDER, max_calls=40))
    check("current builder head mismatch", cbad(CBUILDER, "head_commit", expect_head="9999999"))
    check("current builder head prefix ok", cok(CBUILDER, expect_head="def5678abcdef"))
    check("current builder plan_first needs sheet", cbad(mutated(CBUILDER, plan_first=True), "sheet_path"))
    check("current builder plan_first with sheet ok", cok(mutated(CBUILDER, plan_first=True, sheet_path="/x/sheet.md")))
    check("current builder blocked needs reason",
          cbad(mutated(CBUILDER, status="blocked"), "blocked"))
    check("current builder blocked with blockers ok", cok(mutated(CBUILDER, status="blocked", blockers=["b"])))
    check("current builder blocked with remaining_work ok",
          cok(mutated(CBUILDER, status="blocked", remaining_work=["w"])))
    check("current builder BUILD n/a red_kind", cbad(mutated(CBUILDER, red_kind="n/a"), "red_kind"))
    check("current builder FIX n/a red_kind", cbad(mutated(CBUILDER, mode="FIX", red_kind="n/a"), "red_kind"))
    check("current builder FAILING needs evidence", cbad(mutated(CBUILDER, red_evidence=[]), "red_evidence"))
    check("current builder CHARACTERIZATION needs evidence",
          cbad(mutated(CBUILDER, red_kind="CHARACTERIZATION", red_evidence=[]), "red_evidence"))
    check("current builder NONE without evidence ok", cok(mutated(CBUILDER, red_kind="NONE", red_evidence=[])))
    check("current builder ready BUILD needs checks", cbad(mutated(CBUILDER, checks=[]), "checks"))
    for field, value in (("command", ""), ("exit_code", "0"), ("exit_code", True), ("log", "")):
        row = dict(CBUILDER["checks"][0], **{field: value})
        check("current builder check bad %s=%r" % (field, value), cbad(mutated(CBUILDER, checks=[row]), "checks[0]"))
    check("current builder check row missing key", cbad(mutated(CBUILDER, checks=[{"command": "x"}]), "checks[0]"))
    check("current builder check row not object", cbad(mutated(CBUILDER, checks=["x"]), "checks[0]"))
    check("current builder mutant bad result", cbad(mutated(CBUILDER, mutants=[{"name": "m", "result": "DEAD"}]), "mutants[0]"))
    check("current builder mutant no name", cbad(mutated(CBUILDER, mutants=[{"name": "", "result": "KILLED"}]), "mutants[0]"))
    check("current builder survivor rejected when ready",
          cbad(mutated(CBUILDER, mutants=[{"name": "m", "result": "SURVIVED"}]), "SURVIVED"))
    check("current builder survivor ok when blocked",
          cok(mutated(CBUILDER, status="blocked", blockers=["b"], mutants=[{"name": "m", "result": "SURVIVED"}])))
    check("current builder equivalent mutant ok", cok(mutated(CBUILDER, mutants=[{"name": "m", "result": "EQUIVALENT"}])))
    check("current builder finding bad outcome",
          cbad(mutated(CBUILDER, findings_addressed=[{"id": "F", "outcome": "wontfix"}]), "findings_addressed[0]"))
    check("current builder finding no id",
          cbad(mutated(CBUILDER, findings_addressed=[{"id": "", "outcome": "fixed"}]), "findings_addressed[0]"))
    for outcome in ("fixed", "not_reproduced", "disputed"):
        check("current builder outcome ok " + outcome,
              cok(mutated(CBUILDER, findings_addressed=[{"id": "F", "outcome": outcome}])))
    for field, value in (("evidence", "MAYBE"), ("fix_size", "XL"), ("line", "1"), ("fix_files", "a"),
                         ("depends_on", "x"), ("severity", "")):
        check("current survey candidate bad %s=%r" % (field, value),
              cbad(mutated(CSURVEY, candidates=[dict(CANDIDATE, **{field: value})]), "candidates[0]"))
    check("current survey candidate missing key",
          cbad(mutated(CSURVEY, candidates=[dropped(CANDIDATE, "reproduction")]), "candidates[0]"))
    check("current survey REPRODUCED needs reproduction",
          cbad(mutated(CSURVEY, candidates=[dict(CANDIDATE, reproduction=None)]), "needs a non-empty reproduction"))
    check("current survey needs coverage", cbad(mutated(CSURVEY, coverage=[]), "coverage"))
    check("current survey candidate SUSPECTED ok",
          cok(mutated(CSURVEY, candidates=[dict(CANDIDATE, evidence="SUSPECTED")])))
    for field, value in (("depth", "skimmed"), ("area", ""), ("note", 3)):
        check("current survey coverage bad %s=%r" % (field, value),
              cbad(mutated(CSURVEY, coverage=[dict(CSURVEY["coverage"][0], **{field: value})]), "coverage[0]"))
    for depth in ("read", "executed", "profiled", "not_examined"):
        check("current survey depth ok " + depth,
              cok(mutated(CSURVEY, coverage=[dict(CSURVEY["coverage"][0], depth=depth)])))
    meas = {"metric": "t", "method": "m", "baseline_commit": "abc1234", "base": 1.5, "after": 1, "runs": 5,
            "spread": "s", "within_noise": False}
    check("current builder measurement ok", cok(mutated(CBUILDER, measurements=[meas])))
    for field, value in (("within_noise", "no"), ("runs", "5"), ("base", "1"), ("base", True), ("after", False), ("metric", "")):
        check("current builder measurement bad %s=%r" % (field, value),
              cbad(mutated(CBUILDER, measurements=[dict(meas, **{field: value})]), "measurements[0]"))
    adj = {"title": "t", "file": "a.py", "line": 2, "severity": "LOW", "evidence": "e"}
    check("current builder adjacent ok", cok(mutated(CBUILDER, adjacent_findings=[adj])))
    check("current builder adjacent bad line",
          cbad(mutated(CBUILDER, adjacent_findings=[dict(adj, line="2")]), "adjacent_findings[0]"))
    check("current builder adjacent missing key",
          cbad(mutated(CBUILDER, adjacent_findings=[dropped(adj, "evidence")]), "adjacent_findings[0]"))

    # reviewer: top-level keys, types and enums
    for key in C_REVIEWER_KEYS:
        check("current reviewer missing " + key, cbad(dropped(CREVIEWER, key), "missing field: " + key, role="reviewer"))
    for field, value in (("verdict", "OK"), ("mode", "REVIEW"), ("status", "done"), ("verification_tooling", "fine"),
                         ("repository_unchanged", "yes"), ("isolation_note", ""), ("report_path", ""),
                         ("riskiest_points", "x"), ("not_checked", [1]), ("reviewed_commit", "HEAD"),
                         ("session", ""), ("measurements", "x")):
        check("current reviewer bad %s=%r" % (field, value), cbad(mutated(CREVIEWER, **{field: value}), field))
    check("current reviewer repository modified", cbad(mutated(CREVIEWER, repository_unchanged=False), "repository_unchanged"))
    for verdict in ("READY", "READY_WITH_CHANGES", "NOT_READY"):
        base = mutated(CREVIEWER, verdict=verdict, findings=[], mutations=[], builder_mutants=[],
                       corpora=[], scripts=[], evidence_minimums=dict(CREVIEWER["evidence_minimums"], E1="not_required",
                       E2="not_required", E3="not_required", E5="not_required", E6="not_required"))
        check("current reviewer verdict ok " + verdict, cok(base) if verdict != "NOT_READY" else cok(base))
    for mode in ("SPEC", "CODE", "AUDIT", "CONFIRM_FIX", "DIGEST"):
        check("current reviewer mode ok " + mode, "mode" not in " ".join(runc(json.dumps(mutated(CREVIEWER, mode=mode)))[0]))
    digest = mutated(CREVIEWER, mode="DIGEST", verdict="READY", findings=[], coverage=[], mutations=[],
                     builder_mutants=[], corpora=[], scripts=[], versions={"language": "p", "tests_run": 0},
                     evidence_minimums=dict(CREVIEWER["evidence_minimums"], E1="not_required", E2="not_required",
                                            E3="not_required", E5="not_required", E6="not_required"))
    check("current reviewer DIGEST READY ok", cok(digest))
    check("current reviewer DIGEST NOT_READY ok", cok(dict(digest, verdict="NOT_READY")))
    check("current reviewer DIGEST READY_WITH_CHANGES rejected", cbad(dict(digest, verdict="READY_WITH_CHANGES"), "DIGEST"))
    check("current reviewer expect-head mismatch", cbad(CREVIEWER, "reviewed_commit", expect_head="9999999"))
    check("current reviewer expect-head prefix ok", cok(CREVIEWER, expect_head="def5678abcdef"))
    check("current reviewer tip sha differs from reviewed_commit",
          cbad(setd(CREVIEWER, ["reviewed_exports", 0, "sha"], "1111111"), "tip"))
    check("current reviewer CODE needs tip export",
          cbad(mutated(CREVIEWER, reviewed_exports=[CREVIEWER["reviewed_exports"][1]]), "tip"))
    check("current reviewer AUDIT without exports ok",
          cok(mutated(CREVIEWER, mode="AUDIT", reviewed_exports=[], findings=[], verdict="READY",
                      evidence_minimums=dict(CREVIEWER["evidence_minimums"], E3="not_required", E5="not_required", E6="not_required"))))
    for field, value in (("role", "main"), ("path", ""), ("sha", "nothex")):
        check("current reviewer export bad %s" % field,
              cbad(setd(CREVIEWER, ["reviewed_exports", 1, field], value), "reviewed_exports[1]"))
    check("current reviewer max-calls cannot be checked", cbad(CREVIEWER, "max-calls", max_calls=10))
    check("current reviewer max-calls reviewer blocks only when passed", cok(CREVIEWER))

    # reviewer: coverage
    for field, value in (("result", "OK"), ("depth", "deep"), ("evidence", ""), ("attack", ""), ("stage", "")):
        check("current reviewer coverage bad %s" % field,
              cbad(setd(CREVIEWER, ["coverage", 0, field], value), "coverage[0]"))
    check("current reviewer coverage missing key", cbad(setd(CREVIEWER, ["coverage"], [{"attack": "a"}]), "coverage[0]"))
    check("current reviewer CODE needs coverage", cbad(mutated(CREVIEWER, coverage=[]), "coverage"))
    for res in ("PASS", "FAIL", "NOT_CHECKED"):
        check("current reviewer coverage result ok " + res, cok(setd(CREVIEWER, ["coverage", 0, "result"], res)))
    for depth in ("read", "executed", "profiled", "mutated", "n/a"):
        check("current reviewer coverage depth ok " + depth, cok(setd(CREVIEWER, ["coverage", 0, "depth"], depth)))

    # reviewer: findings
    for key in FINDING:
        check("current reviewer finding missing " + key, cbad(setd(CREVIEWER, ["findings"], [dropped(FINDING, key)]), "findings[0]"))
    for field, value in (("type", "bug"), ("confidence", "sure"), ("status", "closed"), ("severity", "SEVERE"),
                         ("id", ""), ("line", "3"), ("file", ""), ("expected", ""), ("actual", ""), ("contract", "")):
        check("current reviewer finding bad %s=%r" % (field, value),
              cbad(setd(CREVIEWER, ["findings"], [dict(FINDING, **{field: value})]), "findings[0]"))
    check("current reviewer duplicate finding id",
          cbad(setd(CREVIEWER, ["findings"], [FINDING, FINDING]), "duplicate"))
    check("current reviewer reproduced needs reproduction",
          cbad(setd(CREVIEWER, ["findings"], [dict(FINDING, reproduction=None)]), "reproduction"))
    check("current reviewer reproduced needs output",
          cbad(setd(CREVIEWER, ["findings"], [dict(FINDING, reproduction_output=None)]), "reproduction_output"))
    check("current reviewer MEDIUM needs proposed_test",
          cbad(setd(CREVIEWER, ["findings"], [dict(FINDING, proposed_test=None)]), "proposed_test"))
    check("current reviewer MEDIUM needs proposed_fix",
          cbad(setd(CREVIEWER, ["findings"], [dict(FINDING, proposed_fix=None)]), "proposed_fix"))
    low = dict(FINDING, severity="LOW", proposed_test=None)
    check("current reviewer LOW needs only fix idea", cok(setd(CREVIEWER, ["findings"], [low])))
    check("current reviewer LOW needs fix idea",
          cbad(setd(CREVIEWER, ["findings"], [dict(low, proposed_fix=None)]), "proposed_fix"))
    src = dict(FINDING, confidence="source_supported", reproduction=None, reproduction_output=None,
               proposed_test=None, proposed_fix=None, base_commit_result=None)
    ev = dict(CREVIEWER["evidence_minimums"], E3="not_required", E5="not_required", E6="not_required")
    scope = dict(src, type="scope_issue")
    check("current reviewer source_supported scope_issue ok",
          cok(mutated(CREVIEWER, findings=[scope], evidence_minimums=ev, scripts=[])))
    check("current reviewer CODE defect cannot be source_supported",
          cbad(mutated(CREVIEWER, findings=[src], evidence_minimums=ev, scripts=[]), "must have confidence reproduced"))
    check("current reviewer AUDIT defect may be source_supported",
          cok(mutated(dict(CREVIEWER, mode="AUDIT"), findings=[src], verdict="READY", evidence_minimums=ev, scripts=[])))
    check("current reviewer defect needs file",
          cbad(setd(CREVIEWER, ["findings"], [dict(FINDING, file=None)]), "needs a file and a line"))
    check("current reviewer defect needs line",
          cbad(setd(CREVIEWER, ["findings"], [dict(FINDING, line=None)]), "needs a file and a line"))
    check("current reviewer source_supported must not claim reproduction",
          cbad(mutated(CREVIEWER, findings=[dict(scope, reproduction="sh x")], evidence_minimums=ev, scripts=[]), "must be null"))
    check("current reviewer source_supported must not carry output",
          cbad(mutated(CREVIEWER, findings=[dict(scope, reproduction_output="o.txt")], evidence_minimums=ev, scripts=[]), "must be null"))
    check("current reviewer CODE defect cannot be suspected",
          cbad(setd(CREVIEWER, ["findings"], [dict(src, confidence="suspected")]), "suspected"))
    audit = dict(CREVIEWER, mode="AUDIT", verdict="READY_WITH_CHANGES")
    check("current reviewer AUDIT may suspect",
          cok(mutated(audit, findings=[dict(src, confidence="suspected", severity="HIGH")], verdict="READY",
                      evidence_minimums=ev, scripts=[])))
    check("current reviewer SPEC may suspect",
          cok(mutated(audit, mode="SPEC", findings=[dict(src, confidence="suspected")], verdict="READY",
                      evidence_minimums=ev, scripts=[])))
    check("current reviewer decision_issue cannot be reproduced",
          cbad(setd(CREVIEWER, ["findings"], [dict(FINDING, type="decision_issue")]), "decision_issue"))
    check("current reviewer decision_issue source_supported no file ok",
          cok(mutated(CREVIEWER, findings=[dict(src, type="decision_issue", file=None, line=None)],
                      evidence_minimums=ev, scripts=[])))
    check("current reviewer CODE finding must be open",
          cbad(setd(CREVIEWER, ["findings"], [dict(FINDING, status="fixed")]), "status"))
    confirm = mutated(CREVIEWER, mode="CONFIRM_FIX", findings=[dict(FINDING, status="fixed")], verdict="READY")
    check("current reviewer CONFIRM_FIX fixed ok", cok(confirm))
    for st in ("open", "fixed", "disputed", "not_checked"):
        check("current reviewer CONFIRM_FIX status ok " + st,
              cok(mutated(confirm, findings=[dict(FINDING, status=st)], verdict="READY_WITH_CHANGES")))
    check("current reviewer READY with open HIGH defect",
          cbad(mutated(CREVIEWER, verdict="READY", findings=[dict(FINDING, severity="HIGH")]), "verdict"))
    check("current reviewer READY with open CRITICAL defect",
          cbad(mutated(CREVIEWER, verdict="READY", findings=[dict(FINDING, severity="CRITICAL")]), "verdict"))
    check("current reviewer READY with MEDIUM defect ok",
          cok(mutated(CREVIEWER, verdict="READY")))
    check("current AUDIT HIGH needs NOT_READY",
          cbad(mutated(audit, findings=[dict(FINDING, severity="HIGH")], verdict="READY_WITH_CHANGES"), "verdict"))
    check("current AUDIT HIGH NOT_READY ok",
          cok(mutated(audit, findings=[dict(FINDING, severity="HIGH")], verdict="NOT_READY")))
    check("current AUDIT MEDIUM needs READY_WITH_CHANGES",
          cbad(mutated(audit, verdict="NOT_READY"), "verdict"))
    check("current AUDIT none needs READY",
          cbad(mutated(audit, findings=[], verdict="READY_WITH_CHANGES",
                       evidence_minimums=dict(ev), scripts=[]), "verdict"))

    # reviewer: mutation rows, builder mutants
    for key in MUTATION:
        check("current reviewer mutation missing " + key, cbad(setd(CREVIEWER, ["mutations"], [dropped(MUTATION, key)]), "mutations[0]"))
    for field, value in (("name", ""), ("file", ""), ("anchor", ""), ("replacement", 3), ("modules", "t"),
                         ("modules", []), ("expect", "SURVIVED"), ("result", "DEAD"), ("why", 4)):
        check("current reviewer mutation bad %s=%r" % (field, value),
              cbad(setd(CREVIEWER, ["mutations"], [dict(MUTATION, **{field: value})]), "mutations[0]"))
    check("current reviewer empty replacement ok",
          cok(setd(CREVIEWER, ["mutations"], [dict(MUTATION, replacement="")])))
    check("current reviewer equivalent needs why",
          cbad(setd(CREVIEWER, ["mutations"], [dict(MUTATION, expect="EQUIVALENT", result="EQUIVALENT", why="")]), "why"))
    check("current reviewer equivalent with why ok",
          cok(setd(CREVIEWER, ["mutations"], [dict(MUTATION, expect="EQUIVALENT", result="EQUIVALENT", why="no effect")])))
    for result in ("KILLED", "SURVIVED", "EQUIVALENT", "INVALID"):
        check("current reviewer mutation result ok " + result,
              cok(setd(CREVIEWER, ["mutations"], [dict(MUTATION, result=result, why="reason")])))
    check("current reviewer duplicate mutation name",
          cbad(setd(CREVIEWER, ["mutations"], [MUTATION, MUTATION]), "duplicate"))
    check("current reviewer E2 met needs mutation rows",
          cbad(mutated(CREVIEWER, mutations=[], builder_mutants=[]), "E2"))
    check("current reviewer E2 met by builder_mutants alone ok", cok(mutated(CREVIEWER, mutations=[])))
    check("current reviewer E2 not_required without rows ok",
          cok(mutated(CREVIEWER, mutations=[], builder_mutants=[],
                      evidence_minimums=dict(CREVIEWER["evidence_minimums"], E2="not_required"))))
    bm = CREVIEWER["builder_mutants"][0]
    for field, value in (("rows", "6"), ("killed", 7), ("invalid", -1), ("survived", "x"), ("file", "")):
        check("current reviewer builder_mutants bad %s=%r" % (field, value),
              cbad(setd(CREVIEWER, ["builder_mutants"], [dict(bm, **{field: value})]), "builder_mutants[0]"))
    check("current reviewer builder_mutants counts exceed rows",
          cbad(setd(CREVIEWER, ["builder_mutants"], [dict(bm, killed=5, survived=["a", "b"])]), "builder_mutants[0]"))
    check("current reviewer builder_mutants missing key",
          cbad(setd(CREVIEWER, ["builder_mutants"], [dropped(bm, "invalid")]), "builder_mutants[0]"))

    # reviewer: commands, versions, scripts, corpora
    check("current reviewer commands required", cbad(mutated(CREVIEWER, commands=[]), "commands"))
    for field, value in (("command", ""), ("exit_code", "0"), ("exit_code", True)):
        check("current reviewer command bad %s=%r" % (field, value),
              cbad(setd(CREVIEWER, ["commands"], [dict(CREVIEWER["commands"][0], **{field: value})]), "commands[0]"))
    check("current reviewer command missing exit_code",
          cbad(setd(CREVIEWER, ["commands"], [{"command": "x"}]), "commands[0]"))
    check("current reviewer nonzero exit_code recorded ok",
          cok(setd(CREVIEWER, ["commands"], [{"command": "false", "exit_code": 1}])))
    check("current reviewer versions language", cbad(setd(CREVIEWER, ["versions", "language"], ""), "versions"))
    check("current reviewer versions tests_run type", cbad(setd(CREVIEWER, ["versions", "tests_run"], "9"), "versions"))
    check("current reviewer versions tests_run zero", cbad(setd(CREVIEWER, ["versions", "tests_run"], 0), "tests_run"))
    check("current reviewer versions not object", cbad(mutated(CREVIEWER, versions="3.12"), "versions"))
    check("current reviewer versions missing tests_run", cbad(setd(CREVIEWER, ["versions"], {"language": "p"}), "versions"))
    check("current reviewer script row bad path", cbad(setd(CREVIEWER, ["scripts"], [{"path": "", "output": "o"}]), "scripts[0]"))
    check("current reviewer script row missing output", cbad(setd(CREVIEWER, ["scripts"], [{"path": "p"}]), "scripts[0]"))
    check("current reviewer reproduced needs scripts", cbad(mutated(CREVIEWER, scripts=[]), "scripts"))
    for field, value in (("file", ""), ("cases", "2"), ("cases", -1), ("seed", "x"), ("oracle", "")):
        check("current reviewer corpus bad %s=%r" % (field, value),
              cbad(setd(CREVIEWER, ["corpora"], [dict(CREVIEWER["corpora"][0], **{field: value})]), "corpora[0]"))
    check("current reviewer corpus missing key", cbad(setd(CREVIEWER, ["corpora"], [{"file": "f"}]), "corpora[0]"))
    check("current reviewer E1 met needs corpora", cbad(mutated(CREVIEWER, corpora=[]), "E1"))
    check("current reviewer corpora without E1", cbad(setd(CREVIEWER, ["evidence_minimums", "E1"], "not_required"), "E1"))

    # reviewer: evidence minimums
    for key in ("E1", "E2", "E3", "E4", "E5", "E6"):
        check("current reviewer evidence missing " + key,
              cbad(setd(CREVIEWER, ["evidence_minimums"], dropped(CREVIEWER["evidence_minimums"], key)), key))
        check("current reviewer evidence bad value " + key,
              cbad(setd(CREVIEWER, ["evidence_minimums", key], "yes"), key))
        check("current reviewer evidence not_met " + key,
              cbad(setd(CREVIEWER, ["evidence_minimums", key], "not_met"), key))
    check("current reviewer evidence not object", cbad(mutated(CREVIEWER, evidence_minimums="met"), "evidence_minimums"))
    check("current reviewer E4 must be met", cbad(setd(CREVIEWER, ["evidence_minimums", "E4"], "not_required"), "E4"))
    for key in ("E3", "E5", "E6"):
        check("current reviewer reproduced finding needs " + key,
              cbad(setd(CREVIEWER, ["evidence_minimums", key], "not_required"), key))

    # reviewer: validator object
    val = CREVIEWER["validator"]
    check("current reviewer validator not_available ok",
          cok(setd(CREVIEWER, ["validator"], {"status": "not_available", "command": None, "exit_code": None, "output": None})))
    check("current reviewer validator not_available with command",
          cbad(setd(CREVIEWER, ["validator"], {"status": "not_available", "command": "x", "exit_code": None, "output": None}), "validator"))
    check("current reviewer validator not_available with exit_code",
          cbad(setd(CREVIEWER, ["validator"], {"status": "not_available", "command": None, "exit_code": 0, "output": None}), "validator"))
    check("current reviewer validator not_available with output",
          cbad(setd(CREVIEWER, ["validator"], {"status": "not_available", "command": None, "exit_code": None, "output": "o"}), "validator"))
    check("current reviewer validator passed nonzero exit", cbad(setd(CREVIEWER, ["validator", "exit_code"], 1), "validator"))
    check("current reviewer validator passed no command", cbad(setd(CREVIEWER, ["validator", "command"], ""), "validator"))
    check("current reviewer validator failed rejected", cbad(setd(CREVIEWER, ["validator"], dict(val, status="failed", exit_code=1)), "validator"))
    check("current reviewer validator bad status", cbad(setd(CREVIEWER, ["validator", "status"], "ok"), "validator"))
    check("current reviewer validator missing key", cbad(setd(CREVIEWER, ["validator"], {"status": "passed"}), "validator"))
    check("current reviewer validator not object", cbad(mutated(CREVIEWER, validator="passed"), "validator"))
    check("current reviewer validator passed exit_code bool", cbad(setd(CREVIEWER, ["validator", "exit_code"], False), "validator"))

    # files named in scripts and corpora (--root)
    with tempfile.TemporaryDirectory() as root:
        for name, lines in (("corpus-cases.jsonl", 2), ("repro.sh", 1)):
            with open(os.path.join(root, name), "w") as fh:
                fh.write("".join('{"n": %d}\n' % i for i in range(lines)))
        check("current root: files present ok", cok(CREVIEWER, root=root))
        check("current root: absent script", cbad(setd(CREVIEWER, ["scripts", 0, "path"], "gone.sh"), "scripts[0].path 'gone.sh' does not exist", root=root))
        check("current root: absent corpus", cbad(setd(CREVIEWER, ["corpora", 0, "file"], "gone.jsonl"), "corpora[0].file 'gone.jsonl' does not exist", root=root))
        check("current root: corpus line count mismatch",
              cbad(setd(CREVIEWER, ["corpora", 0, "cases"], 3), "cases", root=root))
        check("current root: absolute path inside root ok",
              cok(setd(CREVIEWER, ["scripts", 0, "path"], os.path.join(root, "repro.sh")), root=root))
        check("current root: absolute path absent",
              cbad(setd(CREVIEWER, ["scripts", 0, "path"], os.path.join(root, "nope.sh")), "does not exist", root=root))
        with open(os.path.join(root, "blank.jsonl"), "w") as fh:
            fh.write('{"n": 1}\n\n   \n{"n": 2}\n')
        check("current root: blank lines are not cases",
              cok(setd(CREVIEWER, ["corpora", 0, "file"], "blank.jsonl"), root=root))
        check("current root: unreadable corpus",
              cbad(setd(CREVIEWER, ["corpora", 0, "file"], "."), "does not exist", root=root))
        check("current root: directory is not a file",
              cbad(setd(CREVIEWER, ["scripts", 0, "path"], "."), "scripts[0]", root=root))
        check("current no root: absent files not checked",
              cok(setd(CREVIEWER, ["scripts", 0, "path"], "gone.sh")))

    # command line
    with tempfile.TemporaryDirectory() as tmp:
        good = os.path.join(tmp, "good.json")
        badf = os.path.join(tmp, "bad.json")
        legacy = os.path.join(tmp, "legacy.txt")
        with open(good, "w") as fh:
            json.dump(CBUILDER, fh)
        with open(badf, "w") as fh:
            json.dump(dropped(CBUILDER, "calls_used"), fh)
        with open(legacy, "w") as fh:
            fh.write(wrap(BUILDER))
        rc, out = cli([good, "--contract", "current"])
        check("current cli: ok exit 0", rc == 0 and out.startswith("OK:"))
        check("current cli: tally names builder", "builder" in out and "40/90" in out)
        rc, out = cli([badf, "--contract", "current"])
        check("current cli: rejected exit 1", rc == 1 and "calls_used" in out)
        rc, out = cli([good, "--contract", "current", "--expect-head", "9999999"])
        check("current cli: head mismatch exit 1", rc == 1)
        rc, out = cli([good, "--contract", "current", "--max-calls", "10"])
        check("current cli: call cap exit 1", rc == 1)
        rc, out = cli([os.path.join(tmp, "absent.json"), "--contract", "current"])
        check("current cli: unreadable exit 2", rc == 2)
        rc, out = cli([good, "--contract", "bogus"])
        check("current cli: bad contract exit 2", rc == 2)
        rc, out = cli([good, "--contract", "current", "--root", os.path.join(tmp, "nodir")])
        check("current cli: missing root exit 2", rc == 2)
        rc, out = cli([good, "--root", tmp])
        check("current cli: --root without current exit 2", rc == 2)
        rc, out = cli([legacy])
        check("current cli: legacy default unchanged", rc == 0 and "builder S1" in out)
        rc, out = cli([legacy, "--contract", "legacy"])
        check("current cli: explicit legacy", rc == 0)
        rc, out = cli([legacy, "--contract", "current"])
        check("current cli: legacy block under current rejected", rc == 1)
        rc, out = cli([good])
        check("current cli: bare json under default legacy rejected", rc == 1)
        with open(os.path.join(tmp, "bin.json"), "wb") as fh:
            fh.write(b"\xff\xfe\x00bad")
        rc, out = cli([os.path.join(tmp, "bin.json"), "--contract", "current"])
        check("current cli: undecodable file exit 2", rc == 2)
        rc, out = cli([os.path.join(tmp, "bin.json")])
        check("current cli: legacy undecodable file is not swallowed", isinstance(rc, str) and "UnicodeDecodeError" in rc)
        rc, out = cli([os.path.join(tmp, "bin.json"), "--role", "builder"])
        check("current cli: legacy undecodable with role is not swallowed", isinstance(rc, str) and "UnicodeDecodeError" in rc)

    # tally in current mode
    problems, block, role = runc(json.dumps(CREVIEWER))
    check("current role detected: reviewer", role == "reviewer" and problems == [])
    tally = v.tally_current(block, role) if role == "reviewer" else ""
    check("current tally reviewer", "READY_WITH_CHANGES" in tally and "0/0/1/0" in tally)
    problems, block, role = runc(json.dumps(CBUILDER))
    check("current role detected: builder", role == "builder" and problems == [])
    tally = v.tally_current(block, role) if role == "builder" else ""
    check("current tally builder", "40/90" in tally)


def cbad_text(text, needle, **kw):
    return any(needle in p for p in runc(text, **kw)[0] if not p.startswith("EXC"))



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

    test_current_mode()

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
