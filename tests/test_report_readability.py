#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Readable template-report gates (R4A.*): the deterministic Stage 3 report.

Run standalone:  python -B tests/test_report_readability.py
Or as part of:   python tests/test_pipeline.py

Ticket 4A-1 builds the sentence templates, the result-type sections and the
Summary. Every gate is isolated (attempt()); all inputs are synthetic and
written to temporary directories, or are the repository's synthetic release
fixtures. Assertions that need the optional jsonschema package run only when it
is importable (the semantic rules run regardless).
"""
import hashlib
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "stage2"))
sys.path.insert(0, os.path.join(ROOT, "stage3"))

import annotate  # noqa: E402
import run as stage3_run  # noqa: E402
import validate_report  # noqa: E402
from render_report import render  # noqa: E402

FIX = os.path.join(ROOT, "fixtures")
DATA = os.path.join(ROOT, "data")
RELEASE_PANEL = os.path.join(DATA, "targets.release-panel.json")
ALIASES = os.path.join(DATA, "condition_aliases.json")

# C0 characterization pins (computed on the base commit f9f0d6f, legacy path
# unchanged by this ticket).
LEGACY_FIXTURE_IR_HASH = "11a7d41940946dcaeb6a50992fa8d0ee5a8acb8cae578d83e3dbfc7524018a62"
LEGACY_FIXTURE_MD_HASH = "784e96d9a6283f1bdb640c4d2ad4fe6f081889d8dd3c53826a3023a5f8a77313"
LEGACY_SECTION_IDS = ["s_detected", "s_covered_reference", "s_covered_nocall",
                      "s_not_covered", "s_not_assayable", "s_c_000000000001"]


class _Gate(AssertionError):
    pass


def _require(label, cond):
    if not cond:
        raise _Gate(label)


def _load(path):
    with open(path) as fh:
        return json.load(fh)


def _write_raw(directory, rows, build="37.1", array_version="TESTARRAY-1"):
    lines = ["#synthetic raw data for report-readability tests",
             f"#Data was collected using AncestryDNA array version: {array_version}"]
    if build is not None:
        lines.append(f"#using human reference build {build} coordinates.")
    lines.append("rsid\tchromosome\tposition\tallele1\tallele2")
    lines.extend("\t".join(str(c) for c in r) for r in rows)
    path = os.path.join(directory, "raw.txt")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def _panel(*variants):
    return {"merges": {}, "sources": [], "variants": list(variants)}


def _variant(rsid, ref, alt, effect, result_type, gene="GENEZ", condition="Example trait one",
             association="single_study", clinvar=None, rarity="common", strand="forward"):
    return {"rsid": rsid, "chromosome": "1", "position": 1000, "gene": gene,
            "condition": condition, "category": "trait" if result_type == "trait" else "carrier",
            "result_type": result_type, "effect_allele": effect, "assayability": "snp",
            "reference_allele": ref, "alternate_allele": alt, "cls": "risk",
            "association": association, "gnomad_af": 0.2, "clinvar": clinvar,
            "snpedia": None, "strand": strand}


def _doc_from(rows, variants, build="37.1"):
    with tempfile.TemporaryDirectory() as d:
        raw = _write_raw(d, rows, build=build)
        return annotate.build_findings(raw, _panel(*variants), {})


def _release_doc(name):
    return annotate.build_findings(os.path.join(FIX, name), _load(RELEASE_PANEL),
                                   annotate.load_aliases(ALIASES))


def _report(doc):
    """template_ir for a findings document plus the validator's semantic errors."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "findings.json")
        with open(path, "w") as fh:
            json.dump(doc, fh)
        ir = stage3_run.template_ir(doc, stage3_run.sha256_file(path))
        errors, _ = validate_report.check(path, ir, findings=doc)
    return ir, errors


def _ir_hash(ir):
    return hashlib.sha256(json.dumps(ir, sort_keys=True).encode()).hexdigest()


def _claims(ir, section_id=None):
    for sec in ir["sections"]:
        if section_id is not None and sec["section_id"] != section_id:
            continue
        for claim in sec["claims"]:
            yield sec, claim


def _run_characterization(attempt):
    def legacy_panel_report_unchanged():
        path = os.path.join(FIX, "findings.sample.json")
        doc = _load(path)
        ir = stage3_run.template_ir(doc, stage3_run.sha256_file(path))
        _require(f"legacy IR changed: {_ir_hash(ir)}", _ir_hash(ir) == LEGACY_FIXTURE_IR_HASH)
        _require("legacy section ids changed",
                 [s["section_id"] for s in ir["sections"]] == LEGACY_SECTION_IDS)
        markdown = render(doc, ir)
        got = hashlib.sha256(markdown.encode()).hexdigest()
        _require(f"legacy rendered report changed: {got}", got == LEGACY_FIXTURE_MD_HASH)
        return True
    attempt("R4A.legacy_panel_report_unchanged", legacy_panel_report_unchanged)

    def report_hash_binding_unchanged():
        doc = _release_doc("raw.release.synthetic.txt")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "findings.json")
            with open(path, "w") as fh:
                json.dump(doc, fh)
            want = stage3_run.sha256_file(path)
            ir = stage3_run.template_ir(doc, want)
        _require("findings_hash not bound to the findings file", ir["findings_hash"] == want)
        return True
    attempt("R4A.report_hash_binding_unchanged", report_hash_binding_unchanged)

    def run_json_audit_unchanged():
        doc = _release_doc("raw.release.synthetic.txt")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "findings.json")
            with open(path, "w") as fh:
                json.dump(doc, fh)
            out = os.path.join(d, "report.md")
            rc = stage3_run.main([path, "--template-only", "-o", out])
            _require(f"template-only run exit {rc}", rc == 0)
            audit = _load(os.path.join(d, "report.run.json"))
        for key in ("endpoint", "model", "mode", "findings_hash", "used_fallback",
                    "prose_claims", "fallback_claims", "payload", "generated_at"):
            _require(f"run.json lost key {key!r}", key in audit)
        _require("used_fallback not true for a template-only run", audit["used_fallback"] is True)
        _require("endpoint changed", audit["endpoint"] == "ollama")
        return True
    attempt("R4A.run_json_audit_unchanged", run_json_audit_unchanged)


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
