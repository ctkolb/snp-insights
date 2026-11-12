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
import contextlib
import hashlib
import io
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
import caveats  # noqa: E402
import run as stage3_run  # noqa: E402
import validate_report  # noqa: E402
from render_report import render  # noqa: E402

FIX = os.path.join(ROOT, "fixtures")
DATA = os.path.join(ROOT, "data")
RELEASE_PANEL = os.path.join(DATA, "targets.release-panel.json")
ALIASES = os.path.join(DATA, "condition_aliases.json")
RELEASE_FIXTURES = ("raw.release.synthetic.txt", "raw.release.synthetic.states.txt")

# C0 characterization pins (computed on the base commit f9f0d6f, legacy path
# unchanged by this ticket).
LEGACY_FIXTURE_IR_HASH = "11a7d41940946dcaeb6a50992fa8d0ee5a8acb8cae578d83e3dbfc7524018a62"
LEGACY_FIXTURE_MD_HASH = "784e96d9a6283f1bdb640c4d2ad4fe6f081889d8dd3c53826a3023a5f8a77313"
LEGACY_SECTION_IDS = ["s_detected", "s_covered_reference", "s_covered_nocall",
                      "s_not_covered", "s_not_assayable", "s_c_000000000001"]

RESULT_SECTION_IDS = ("s_carrier_status", "s_associations", "s_traits")
ALL_ZYGOSITIES = ("hom_ref", "het", "hom_alt", "hemizygous", "homoplasmic", "unknown")


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


def _hf(finding_id, rsid, gene, condition, state, zygosity, result_type, effect="A",
        association="replicated", clinvar=None, rarity="common", strand="forward",
        ref="G"):
    """A hand-built finding (for trait and nonstandard-zygosity cases)."""
    if state == "detected":
        call = {"state": "called", "allele1": effect,
                "allele2": effect if zygosity == "hom_alt" else ref,
                "zygosity": zygosity, "strand": strand}
    elif state == "covered_reference":
        call = {"state": "called", "allele1": ref, "allele2": ref,
                "zygosity": zygosity, "strand": strand}
    elif state == "covered_nocall":
        call = {"state": "no_call", "zygosity": zygosity, "strand": strand}
    elif state == "covered_uninterpretable":
        call = {"state": "uninterpretable", "zygosity": zygosity, "strand": strand}
    else:
        call = {"state": "not_applicable"}
    finding = {
        "finding_id": finding_id, "rsid": rsid, "gene": gene, "condition": condition,
        "assayability": "snp",
        "coverage": {"state": "not_covered" if state in ("not_covered", "not_assayable")
                     else "covered", "source": "AncestryDNA TESTARRAY-1 file manifest"},
        "call": call,
        "confidence": {"annotation_mapping": {"level": "high", "basis": []},
                       "array_reliability": {"rarity_class": rarity, "ppv_note": None}},
        "evidence": {"clinvar": clinvar, "snpedia": None, "association": association},
        "state": state, "references": [],
    }
    if result_type is not None:
        finding["result_type"] = result_type
    if effect is not None:
        finding["effect_allele"] = effect
    return finding


def _hdoc(fs):
    return {
        "schema_version": "1.2.0",
        "provenance": {"input_hash": "0" * 64, "array_version": "TESTARRAY-1",
                       "converter_version": "TESTCONVERTER-1", "genome_build": "GRCh37",
                       "input_build": "GRCh37", "build_basis": "file_statement",
                       "strand": "forward", "inferred_sex": "unknown",
                       "manifest_row_count": 0, "generated_at": "2026-01-01T00:00:00Z",
                       "pipeline_version": "0.1.0", "annotation_snapshots": []},
        "findings": fs, "contradictions": [],
    }


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


def _section(ir, section_id):
    for sec in ir["sections"]:
        if sec["section_id"] == section_id:
            return sec
    _require(f"section {section_id!r} is missing", False)


def _texts(ir, section_id=None):
    return {cl["claim_id"]: cl["text"] for _s, cl in _claims(ir, section_id)}


def _groups(ir, sec, by):
    found = set()
    for cl in sec["claims"]:
        for cit in cl["citations"]:
            if cit["finding_id"] in by:
                found.add(by[cit["finding_id"]].get("result_type"))
    return found


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


def _run_behavior(attempt):
    def sections_split_by_result_type():
        fs = [
            _hf("f_000000000001", "rs9000001", "GENEA", "Condition one", "detected", "het", "carrier_status"),
            _hf("f_000000000002", "rs9000002", "GENEB", "Condition two", "detected", "hom_alt", "risk_association"),
            _hf("f_000000000003", "rs9000003", "GENEC", "Example trait one", "detected", "het", "trait"),
        ]
        ir, errors = _report(_hdoc(fs))
        _require(f"unexpected validation errors: {errors}", not errors)
        titles = {s["title"] for s in ir["sections"]}
        for want in ("Health-related: carrier status", "Health-related: associations", "Traits"):
            _require(f"missing section {want!r}", want in titles)
        by = {f["finding_id"]: f for f in fs}
        for sec in ir["sections"]:
            if sec["section_id"] == "s_summary":
                continue
            groups = _groups(ir, sec, by)
            _require(f"section {sec['section_id']} mixes result types {groups}", len(groups) <= 1)
        return True
    attempt("R4A.sections_split_by_result_type", sections_split_by_result_type)

    def trait_claim_states_effect_allele_and_zygosity():
        doc = _doc_from([("rs9000001", 1, 1000, "A", "G")],
                        [_variant("rs9000001", "G", "A", "A", "trait")])
        f = doc["findings"][0]
        _require("trait finding is not a detected het", f["state"] == "detected"
                 and f["call"]["zygosity"] == "het")
        ir, errors = _report(doc)
        _require(f"unexpected validation errors: {errors}", not errors)
        texts = _texts(ir, "s_traits")
        _require("Trait section has no claim", texts)
        text = next(iter(texts.values()))
        _require(f"trait claim lacks the effect allele: {text}", "effect allele A" in text)
        _require(f"trait claim lacks zygosity: {text}", "one copy" in text)
        return True
    attempt("R4A.trait_claim_states_effect_allele_and_zygosity", trait_claim_states_effect_allele_and_zygosity)

    def health_claim_uses_association_not_carrier_language_for_risk_entries():
        fs = [
            _hf("f_000000000001", "rs9000001", "GENEB", "Condition two", "detected", "het", "risk_association"),
            _hf("f_000000000002", "rs9000002", "GENEB", "Condition two", "detected", "hom_alt", "risk_association"),
        ]
        ir, errors = _report(_hdoc(fs))
        _require(f"unexpected validation errors: {errors}", not errors)
        texts = _texts(ir, "s_associations")
        _require("association section has no claim", texts)
        for text in texts.values():
            _require(f"carrier wording on a risk association: {text}", "carrier" not in text.lower())
            _require(f"risk claim lacks association wording: {text}", "association with" in text)
        return True
    attempt("R4A.health_claim_uses_association_not_carrier_language_for_risk_entries",
            health_claim_uses_association_not_carrier_language_for_risk_entries)

    def carrier_status_claim_wording():
        fs = [
            _hf("f_000000000001", "rs9000001", "GENEA", "Condition one", "detected", "het", "carrier_status"),
            _hf("f_000000000002", "rs9000002", "GENEA", "Condition one", "detected", "hom_alt", "carrier_status"),
        ]
        ir, errors = _report(_hdoc(fs))
        _require(f"unexpected validation errors: {errors}", not errors)
        texts = _texts(ir, "s_carrier_status")
        het = texts.get("cl_000000000001", "")
        hom = texts.get("cl_000000000002", "")
        _require(f"het carrier wording: {het}", "one copy of the effect allele A was detected" in het
                 and "carrier status for Condition one; one copy is not the condition itself" in het)
        _require(f"hom_alt carrier wording: {hom}", "two copies of the effect allele A were detected" in hom
                 and "carrier status refers to one copy; this report does not diagnose Condition one" in hom)
        return True
    attempt("R4A.carrier_status_claim_wording", carrier_status_claim_wording)

    def nonstandard_zygosity_fallback_never_says_carrier():
        fs, mapping, n = [], {}, 1
        for result_type in ("carrier_status", "risk_association", "trait"):
            for zygosity in ("hemizygous", "homoplasmic", "unknown"):
                fid = f"f_{n:012d}"
                fs.append(_hf(fid, f"rs9{n:07d}", "GENEA", "Condition one", "detected",
                              zygosity, result_type))
                mapping[(result_type, zygosity)] = "cl_" + fid[2:]
                n += 1
        ir, errors = _report(_hdoc(fs))
        _require(f"unexpected validation errors: {errors}", not errors)
        texts = _texts(ir)
        for key, cid in mapping.items():
            text = texts.get(cid, "")
            _require(f"{key} fallback says carrier: {text}", "carrier" not in text.lower())
            _require(f"{key} fallback counts copies: {text}", "two copies" not in text.lower())
            _require(f"{key} fallback lacks neutral wording: {text}",
                     "does not interpret the number of copies" in text)
        return True
    attempt("R4A.nonstandard_zygosity_fallback_never_says_carrier",
            nonstandard_zygosity_fallback_never_says_carrier)

    def summary_counts_match_findings():
        fs = [
            _hf("f_000000000001", "rs9000001", "GENEA", "Condition one", "detected", "het", "carrier_status"),
            _hf("f_000000000002", "rs9000002", "GENEA", "Condition one", "not_covered", "unknown", "carrier_status"),
            _hf("f_000000000003", "rs9000003", "GENEB", "Condition two", "detected", "hom_alt", "risk_association"),
        ]
        ir, errors = _report(_hdoc(fs))
        _require(f"unexpected validation errors: {errors}", not errors)
        texts = _texts(ir, "s_summary")
        _require("totals claim missing", "cl_summary_total" in texts)
        total = texts["cl_summary_total"]
        _require(f"totals count wrong: {total}", "three curated markers were examined" in total)
        _require(f"measured count wrong: {total}", "two were measured" in total)
        _require(f"not-measured count wrong: {total}", "one was not measured" in total)
        _require("carrier per-type claim missing", "cl_summary_carrier_status" in texts)
        carrier = texts["cl_summary_carrier_status"]
        _require(f"carrier per-type counts wrong: {carrier}",
                 "two carrier status markers were examined" in carrier and "one was measured" in carrier)
        return True
    attempt("R4A.summary_counts_match_findings", summary_counts_match_findings)

    def zero_trait_markers_stated():
        fs = [_hf("f_000000000001", "rs9000001", "GENEA", "Condition one", "detected", "het", "carrier_status")]
        ir, errors = _report(_hdoc(fs))
        _require(f"unexpected validation errors: {errors}", not errors)
        texts = _texts(ir, "s_summary")
        _require("zero-trait statement missing", any("no trait markers" in t for t in texts.values()))
        _require("Traits section present with no traits",
                 all(s["section_id"] != "s_traits" for s in ir["sections"]))
        with_trait = [_hf("f_000000000001", "rs9000001", "GENEA", "Example trait one", "detected", "het", "trait")]
        ir2, _ = _report(_hdoc(with_trait))
        texts2 = _texts(ir2, "s_summary")
        _require("zero-trait statement present with traits",
                 not any("no trait markers" in t for t in texts2.values()))
        _require("Traits section missing", any(s["section_id"] == "s_traits" for s in ir2["sections"]))
        return True
    attempt("R4A.zero_trait_markers_stated", zero_trait_markers_stated)

    def not_measured_section_says_not_measured():
        fs = [_hf("f_000000000001", "rs9000001", "GENEA", "Condition one", "not_covered", "unknown", "risk_association")]
        ir, errors = _report(_hdoc(fs))
        _require(f"unexpected validation errors: {errors}", not errors)
        texts = _texts(ir, "s_associations")
        _require("not_covered finding is not in a result section", texts)
        text = next(iter(texts.values()))
        _require(f"not_covered claim must say not measured: {text}", "not measured" in text)
        return True
    attempt("R4A.not_measured_section_says_not_measured", not_measured_section_says_not_measured)

    def nocall_and_uninterpretable_wording():
        fs = [
            _hf("f_000000000001", "rs9000001", "GENEA", "Condition one", "covered_nocall", "unknown", "carrier_status"),
            _hf("f_000000000002", "rs9000002", "GENEB", "Condition two", "covered_uninterpretable", "unknown", "risk_association"),
        ]
        ir, errors = _report(_hdoc(fs))
        _require(f"unexpected validation errors: {errors}", not errors)
        texts = _texts(ir)
        _require("no-call wording", "returned no call" in texts.get("cl_000000000001", ""))
        _require("uninterpretable wording", "did not match the known alleles" in texts.get("cl_000000000002", ""))
        return True
    attempt("R4A.nocall_and_uninterpretable_wording", nocall_and_uninterpretable_wording)

    def evidence_tier_and_source_shown():
        clinvar = {"significance": "Pathogenic", "review_stars": 2,
                   "review_status_text": "criteria provided, multiple submitters, no conflicts"}
        fs = [
            _hf("f_000000000001", "rs9000001", "GENEA", "Condition one", "detected", "het",
                "risk_association", association="replicated", clinvar=clinvar),
            _hf("f_000000000002", "rs9000002", "GENEB", "Example trait one", "detected", "het",
                "trait", association="single_study"),
            _hf("f_000000000003", "rs9000003", "GENEC", "Condition three", "detected", "het",
                "carrier_status", association="unknown"),
        ]
        ir, errors = _report(_hdoc(fs))
        _require(f"unexpected validation errors: {errors}", not errors)
        texts = _texts(ir)
        clin = texts.get("cl_000000000001", "")
        _require(f"ClinVar evidence clause: {clin}", "from ClinVar's review level" in clin
                 and "two review stars" in clin)
        _require(f"GWAS evidence clause: {texts.get('cl_000000000002', '')}",
                 "from the GWAS Catalog association count" in texts.get("cl_000000000002", ""))
        _require(f"unknown evidence clause: {texts.get('cl_000000000003', '')}",
                 "No evidence tier is recorded" in texts.get("cl_000000000003", ""))
        return True
    attempt("R4A.evidence_tier_and_source_shown", evidence_tier_and_source_shown)

    def every_claim_cites_resolvable_fields():
        doc = _release_doc("raw.release.synthetic.states.txt")
        ir, errors = _report(doc)
        _require(f"unexpected validation errors: {errors}", not errors)
        by = {f["finding_id"]: f for f in doc["findings"]}
        for sec in ir["sections"]:
            for cl in sec["claims"]:
                _require(f"claim {cl['claim_id']} has no citations", bool(cl["citations"]))
                for cit in cl["citations"]:
                    fid = cit["finding_id"]
                    _require(f"claim {cl['claim_id']} cites unknown finding {fid}", fid in by)
                    try:
                        validate_report.resolve(by[fid], cit["field_path"])
                    except KeyError:
                        _require(f"claim {cl['claim_id']} field_path {cit['field_path']!r} unresolved", False)
        return True
    attempt("R4A.every_claim_cites_resolvable_fields", every_claim_cites_resolvable_fields)

    def cross_product_lint():
        states = ("detected", "covered_reference", "covered_nocall", "covered_uninterpretable",
                  "not_covered", "not_assayable")
        fs, n = [], 1
        for state in states:
            for result_type in ("carrier_status", "risk_association", "trait"):
                for zygosity in ALL_ZYGOSITIES:
                    fid = f"f_{n:012d}"
                    association = "single_study" if result_type == "trait" else "replicated"
                    fs.append(_hf(fid, f"rs9{n:07d}", "GENEA", "Condition one", state, zygosity,
                                  result_type, association=association))
                    n += 1
        doc = _hdoc(fs)
        ir, errors = _report(doc)
        _require(f"cross-product validation errors: {errors}", not errors)
        by = {f["finding_id"]: f for f in fs}
        hits = []
        for sec in ir["sections"]:
            for cl in sec["claims"]:
                cited = [by[c["finding_id"]] for c in cl["citations"] if c["finding_id"] in by]
                hits += validate_report.semantic_violations(cl["text"], cited)
        _require(f"cross-product semantic lint hits: {hits[:3]}", not hits)
        return True
    attempt("R4A.cross_product_lint", cross_product_lint)

    def no_numbers_outside_cited_fields():
        for name in RELEASE_FIXTURES:
            _ir, errors = _report(_release_doc(name))
            r1 = [e for e in errors if e[0] == "R1"]
            _require(f"{name}: R1 violations: {r1}", not r1)
        return True
    attempt("R4A.no_numbers_outside_cited_fields", no_numbers_outside_cited_fields)

    def no_prescriptive_language():
        for name in RELEASE_FIXTURES:
            ir, errors = _report(_release_doc(name))
            r4 = [e for e in errors if e[0] == "R4"]
            _require(f"{name}: R4 violations: {r4}", not r4)
            for _sec, cl in _claims(ir):
                low = cl["text"].lower()
                for phrase in validate_report.PRESCRIPTIVE:
                    _require(f"{name}: prescriptive {phrase!r} in {cl['text']}", phrase not in low)
        return True
    attempt("R4A.no_prescriptive_language", no_prescriptive_language)

    def no_internal_state_tokens_in_text():
        tokens = ("covered_", "not_covered", "_nocall", "not_assayable", "covered_uninterpretable")
        docs = [_release_doc(name) for name in RELEASE_FIXTURES]
        docs.append(_hdoc([
            _hf("f_000000000001", "rs9000001", "GENEA", "Condition one", "covered_nocall", "unknown", "carrier_status"),
            _hf("f_000000000002", "rs9000002", "GENEB", "Condition two", "covered_uninterpretable", "unknown", "risk_association"),
            _hf("f_000000000003", "rs9000003", "GENEC", "Condition three", "not_covered", "unknown", "trait"),
        ]))
        for doc in docs:
            ir, _ = _report(doc)
            for _sec, cl in _claims(ir):
                for token in tokens:
                    _require(f"internal state token {token!r} in {cl['text']}", token not in cl["text"])
        return True
    attempt("R4A.no_internal_state_tokens_in_text", no_internal_state_tokens_in_text)

    def evidence_clause_clinvar_review_level():
        ir, errors = _report(_release_doc("raw.release.synthetic.txt"))
        _require(f"unexpected validation errors: {errors}", not errors)
        texts = list(_texts(ir, "s_carrier_status").values()) + list(_texts(ir, "s_associations").values())
        hfe = next((t for t in texts if t.startswith("Hereditary hemochromatosis")), "")
        _require(f"review-level clause missing: {hfe}",
                 "from ClinVar's review level: ClinVar lists this record as Pathogenic with two review "
                 "stars (criteria provided, multiple submitters, no conflicts); this is a review level, "
                 "not a count of independent studies." in hfe)
        return True
    attempt("R4A.evidence_clause_clinvar_review_level", evidence_clause_clinvar_review_level)

    def risk_association_all_zygosities_have_association_sentence():
        fs, n = [], 1
        for zygosity in ("het", "hom_alt", "hemizygous", "homoplasmic", "unknown"):
            fs.append(_hf(f"f_{n:012d}", f"rs9{n:07d}", "GENEA", "Condition one", "detected",
                          zygosity, "risk_association"))
            n += 1
        ir, errors = _report(_hdoc(fs))
        _require(f"unexpected validation errors: {errors}", not errors)
        texts = _texts(ir, "s_associations")
        _require("association section has no claim", texts)
        sentence = "This is an association with Condition one; this report does not diagnose the condition."
        for text in texts.values():
            _require(f"risk claim lacks the association sentence: {text}", text.endswith(sentence))
        return True
    attempt("R4A.risk_association_all_zygosities_have_association_sentence",
            risk_association_all_zygosities_have_association_sentence)

    def summary_is_r9_exception():
        fs = [
            _hf("f_000000000001", "rs9000001", "GENEA", "Condition one", "detected", "het", "carrier_status"),
            _hf("f_000000000002", "rs9000002", "GENEB", "Condition two", "detected", "hom_alt", "risk_association"),
            _hf("f_000000000003", "rs9000003", "GENEC", "Example trait one", "detected", "het", "trait"),
        ]
        ir, errors = _report(_hdoc(fs))
        _require(f"unexpected validation errors: {errors}", not errors)
        by = {f["finding_id"]: f for f in fs}
        summary = _section(ir, "s_summary")
        _require(f"Summary does not span multiple result types: {_groups(ir, summary, by)}",
                 len(_groups(ir, summary, by)) > 1)
        for sec in ir["sections"]:
            if sec["section_id"] == "s_summary" or not sec["claims"]:
                continue
            _require(f"section {sec['section_id']} mixes result types", len(_groups(ir, sec, by)) <= 1)
        return True
    attempt("R4A.summary_is_r9_exception", summary_is_r9_exception)


# C0 pins for ticket 4A-2 (computed on the base 66a2ca7): the model-path notice and
# the rare-call caveat condition must not change, and a legacy document keeps its
# provenance block.
OLD_STANDING_NOTICE = (
    "This report was synthesized from a raw DNA file by an external language "
    "model from structured findings produced locally. It is a research and "
    "curiosity tool, not medical advice or a diagnostic test."
)


def _notice_line(markdown):
    for line in markdown.splitlines():
        if line.startswith("> "):
            return line[2:]
    return None


def _run_4a2_characterization(attempt):
    def notice_model_path_unchanged():
        doc = _load(os.path.join(FIX, "findings.sample.json"))
        ir = _load(os.path.join(FIX, "report.sample.json"))
        _require("sample report IR already carries generated_by", "generated_by" not in ir)
        got = _notice_line(render(doc, ir))
        _require(f"notice for an IR without generated_by changed: {got!r}", got == OLD_STANDING_NOTICE)
        model_ir = dict(ir, generated_by="model")
        got = _notice_line(render(doc, model_ir))
        _require(f"notice for generated_by=model changed: {got!r}", got == OLD_STANDING_NOTICE)
        _require("STANDING_NOTICE constant changed", caveats.STANDING_NOTICE == OLD_STANDING_NOTICE)
        return True
    attempt("R4A.notice_model_path_unchanged", notice_model_path_unchanged)

    def rare_ppv_applies_to_hom_alt():
        # required_caveats and the validator already attach rare_ppv for any detected
        # zygosity; this pins that behavior (only the wording changes in 4A-2).
        for zygosity in ("het", "hom_alt", "hemizygous"):
            for rarity in ("rare", "ultra_rare"):
                f = _hf("f_000000000001", "rs9000001", "GENEA", "Condition one", "detected",
                        zygosity, "carrier_status", rarity=rarity)
                _require(f"{zygosity}/{rarity}: rare_ppv not attached",
                         "rare_ppv" in stage3_run.required_caveats([f]))
        common = _hf("f_000000000001", "rs9000001", "GENEA", "Condition one", "detected",
                     "hom_alt", "carrier_status", rarity="common")
        _require("rare_ppv attached to a common call", "rare_ppv" not in stage3_run.required_caveats([common]))
        rare_ref = _hf("f_000000000001", "rs9000001", "GENEA", "Condition one", "covered_reference",
                       "hom_ref", "carrier_status", rarity="rare")
        _require("rare_ppv attached to a non-detected call",
                 "rare_ppv" not in stage3_run.required_caveats([rare_ref]))
        fs = [_hf("f_000000000001", "rs9000001", "GENEA", "Condition one", "detected", "hom_alt",
                  "carrier_status", rarity="rare")]
        ir, errors = _report(_hdoc(fs))
        _require(f"template IR for a rare hom_alt call is invalid: {errors}", not errors)
        sec = _section(ir, "s_carrier_status")
        _require("section lacks rare_ppv", "rare_ppv" in sec["caveat_ids"])
        sec["caveat_ids"] = [c for c in sec["caveat_ids"] if c != "rare_ppv"]
        with tempfile.TemporaryDirectory() as d:
            doc = _hdoc(fs)
            path = os.path.join(d, "findings.json")
            with open(path, "w") as fh:
                json.dump(doc, fh)
            ir["findings_hash"] = stage3_run.sha256_file(path)
            errors, _ = validate_report.check(path, ir, findings=doc)
        _require("validator no longer requires rare_ppv for hom_alt",
                 any(code == "R2" and "rare_ppv" in msg for code, msg in errors))
        return True
    attempt("R4A.rare_ppv_applies_to_hom_alt", rare_ppv_applies_to_hom_alt)

    def provenance_legacy_unchanged():
        doc = _load(os.path.join(FIX, "findings.sample.json"))
        ir = _load(os.path.join(FIX, "report.sample.json"))
        _require("legacy findings unexpectedly carry input_build", "input_build" not in doc["provenance"])
        lines = render(doc, ir).splitlines()
        start = lines.index("## Provenance")
        block = []
        for line in lines[start + 2:]:
            if line.startswith("## "):
                break
            block.append(line)
        _require(f"legacy provenance block gained an Input build line: {block}",
                 not any(l.startswith("- Input build") for l in block))
        _require("legacy Build line changed",
                 f"- Build: {doc['provenance']['genome_build']}, strand: {doc['provenance']['strand']}" in block)
        return True
    attempt("R4A.provenance_legacy_unchanged", provenance_legacy_unchanged)

    def sample_report_fixture_validates():
        path = os.path.join(FIX, "findings.sample.json")
        errors, _ = validate_report.check(path, _load(os.path.join(FIX, "report.sample.json")))
        _require(f"sample report fixture invalid: {errors}", not errors)
        return True
    attempt("R4A.sample_report_fixture_validates", sample_report_fixture_validates)


# --- ticket 4A-2: mode-aware notice, caveat text, provenance line, validator
# rules R8-R10, registries (red at C1, green at C2) ---------------------------
TEMPLATE_NOTICE_TEXT = (
    "This report was generated by fixed templates on this machine from structured "
    "findings; no language model was used to write it. It is a research and curiosity "
    "tool, not medical advice or a diagnostic test."
)
NEW_RARE_PPV = ("Rare array calls can be inaccurate; a rare result should be confirmed by a "
                "clinical-grade test.")
TIER_KEYS = ("established", "replicated", "single study", "conflicting", "unknown")
# key phrase (present in the registry item, lower case) -> must appear in the docs
LIMITATION_KEYS = ("0.02%", "forward-strand", "three health entries", "no result is a diagnosis",
                   "clinical-grade test", "template-only narration", "no public array manifest",
                   "owner's aggregate judgment")
DOC_FILES = ("panel-curation.md", "owner-checkpoint.md")
STATE_PROSE = {
    "detected": "This entry was detected on the array.",
    "covered_reference": "The reference genotype was observed at this position.",
    "covered_nocall": "The array returned no call at this position.",
    "covered_uninterpretable": "The alleles at this position could not be interpreted.",
    "not_covered": "This marker was not measured by the array.",
    "not_assayable": "This locus cannot be assessed from array data.",
}


class _FakeChat:
    """Replace llm.chat for one block (no network); restores it on exit."""

    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def __enter__(self):
        self.orig = stage3_run.llm.chat

        def chat(**kwargs):
            self.calls += 1
            if isinstance(self.reply, Exception):
                raise self.reply
            return self.reply(kwargs) if callable(self.reply) else self.reply
        stage3_run.llm.chat = chat
        return self

    def __exit__(self, *exc):
        stage3_run.llm.chat = self.orig


def _main_run(doc, argv, reply=None):
    """Run stage3 main on a findings doc; returns (rc, markdown, ir, audit)."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "findings.json")
        with open(path, "w") as fh:
            json.dump(doc, fh)
        out = os.path.join(d, "report.md")
        with contextlib.redirect_stdout(io.StringIO()):
            if reply is None:
                rc = stage3_run.main([path] + argv + ["-o", out])
            else:
                with _FakeChat(reply):
                    rc = stage3_run.main([path] + argv + ["-o", out])
        with open(out) as fh:
            markdown = fh.read()
        return rc, markdown, _load(os.path.join(d, "report.ir.json")), _load(os.path.join(d, "report.run.json"))


def _prose_for(doc, only=None):
    base, _fallback = stage3_run.build_skeleton(doc, "0" * 64)
    by_id = {f["finding_id"]: f for f in doc["findings"]}
    prose = {}
    for cl in stage3_run._state_claims(base):
        if only is not None and cl["claim_id"] not in only:
            continue
        prose[cl["claim_id"]] = STATE_PROSE[by_id[cl["citations"][0]["finding_id"]]["state"]]
    return prose


def _validate_ir(doc, ir):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "findings.json")
        with open(path, "w") as fh:
            json.dump(doc, fh)
        ir = dict(ir, findings_hash=stage3_run.sha256_file(path))
        errors, _ = validate_report.check(path, ir, findings=doc)
    return errors


def _mixed_doc():
    return _hdoc([
        _hf("f_000000000001", "rs9000001", "GENEA", "Condition one", "detected", "het", "carrier_status"),
        _hf("f_000000000002", "rs9000002", "GENEB", "Condition two", "detected", "hom_alt", "risk_association"),
        _hf("f_000000000003", "rs9000003", "GENEC", "Example trait one", "detected", "het", "trait"),
        _hf("f_000000000004", "rs9000004", "GENED", "Condition four", "not_covered", "unknown", "carrier_status"),
    ])


def _run_4a2_behavior(attempt):
    def notice_template_only_has_no_llm_claim():
        _require("TEMPLATE_NOTICE constant missing or wrong",
                 getattr(caveats, "TEMPLATE_NOTICE", None) == TEMPLATE_NOTICE_TEXT)
        docs = [_release_doc(n) for n in RELEASE_FIXTURES] + [_load(os.path.join(FIX, "findings.sample.json"))]
        for doc in docs:
            rc, markdown, ir, _audit = _main_run(doc, ["--template-only"])
            _require(f"template-only run exit {rc}", rc == 0)
            _require("template-only IR is not labeled template", ir.get("generated_by") == "template")
            got = _notice_line(markdown)
            _require(f"template-only notice wrong: {got!r}", got == TEMPLATE_NOTICE_TEXT)
            _require("template-only report still says it was synthesized by an external model",
                     "synthesized" not in markdown and "external language model" not in markdown)
        return True
    attempt("R4A.notice_template_only_has_no_llm_claim", notice_template_only_has_no_llm_claim)

    def fallback_after_model_failure_uses_template_notice():
        doc = _release_doc("raw.release.synthetic.txt")
        cases = [("skeleton request failure", ["--mode", "skeleton"], RuntimeError("connection refused")),
                 ("skeleton unparseable", ["--mode", "skeleton", "--attempts", "1"], "not json"),
                 ("full request failure", ["--mode", "full"], RuntimeError("connection refused")),
                 ("full unparseable", ["--mode", "full", "--attempts", "1"], "not json")]
        for label, argv, reply in cases:
            rc, markdown, ir, audit = _main_run(doc, argv, reply)
            _require(f"{label}: exit {rc}", rc == 0)
            _require(f"{label}: not reported as a fallback", audit["used_fallback"] is True)
            _require(f"{label}: IR not labeled template", ir.get("generated_by") == "template")
            got = _notice_line(markdown)
            _require(f"{label}: notice wrong: {got!r}", got == TEMPLATE_NOTICE_TEXT)
        return True
    attempt("R4A.fallback_after_model_failure_uses_template_notice",
            fallback_after_model_failure_uses_template_notice)

    def skeleton_success_uses_model_notice():
        doc = _release_doc("raw.release.synthetic.states.txt")
        reply = json.dumps(_prose_for(doc))
        rc, markdown, ir, audit = _main_run(doc, ["--mode", "skeleton"], reply)
        _require(f"skeleton run exit {rc}", rc == 0)
        _require(f"skeleton run was not accepted: {audit}", audit["used_fallback"] is False)
        _require("no model prose was used", audit["prose_claims"] > 0)
        _require(f"accepted skeleton IR not labeled model: {ir.get('generated_by')!r}",
                 ir.get("generated_by") == "model")
        got = _notice_line(markdown)
        _require(f"model-path notice wrong: {got!r}", got == OLD_STANDING_NOTICE)
        _require("model-path report gained the registry sections",
                 "## Limitations" not in markdown and "## Evidence and sources" not in markdown)
        # one accepted sentence is enough to make the text model-written
        first = next(iter(_prose_for(doc)))
        rc, markdown, ir, audit = _main_run(doc, ["--mode", "skeleton"],
                                            json.dumps(_prose_for(doc, only={first})))
        _require("single accepted sentence did not label the report model",
                 ir.get("generated_by") == "model" and _notice_line(markdown) == OLD_STANDING_NOTICE)
        # model prose that fails validation is reverted; if every sentence is
        # reverted the final text is the template text again
        bad = {cid: "Entry 12345 was observed." for cid in _prose_for(doc)}
        rc, markdown, ir, audit = _main_run(doc, ["--mode", "skeleton"], json.dumps(bad))
        _require(f"all-reverted skeleton exit {rc}", rc == 0)
        _require(f"all-reverted skeleton still labeled {ir.get('generated_by')!r}",
                 ir.get("generated_by") == "template")
        _require("all-reverted skeleton kept the model notice", _notice_line(markdown) == TEMPLATE_NOTICE_TEXT)
        return True
    attempt("R4A.skeleton_success_uses_model_notice", skeleton_success_uses_model_notice)

    def skeleton_model_prose_not_subject_to_r8_r10():
        doc = _release_doc("raw.release.synthetic.states.txt")
        by_id = {f["finding_id"]: f for f in doc["findings"]}
        prose = _prose_for(doc)
        target = next(cid for cid, text in prose.items()
                      if by_id["f_" + cid[3:]]["state"] == "not_covered")
        prose[target] = "This entry is unavailable from the array."
        rc, markdown, ir, audit = _main_run(doc, ["--mode", "skeleton"], json.dumps(prose))
        text = _texts(ir)[target]
        _require(f"model sentence was rewritten or reverted: {text!r}",
                 text == "This entry is unavailable from the array.")
        _require("model-labeled report was not accepted", ir.get("generated_by") == "model")
        return True
    attempt("R4A.skeleton_model_prose_not_subject_to_r8_r10", skeleton_model_prose_not_subject_to_r8_r10)

    def full_mode_ir_never_labeled_template():
        doc = _release_doc("raw.release.synthetic.txt")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "findings.json")
            with open(path, "w") as fh:
                json.dump(doc, fh)
            ir = stage3_run.template_ir(doc, stage3_run.sha256_file(path))
        ir["sections"] = [s for s in ir["sections"] if s["section_id"] != "s_summary"]
        ir["generated_by"] = "template"  # a model claiming the template label
        rc, markdown, out_ir, audit = _main_run(doc, ["--mode", "full", "--attempts", "1"], json.dumps(ir))
        _require(f"full-mode IR was not accepted: {audit}", audit["used_fallback"] is False)
        _require("accepted full-mode IR kept generated_by", "generated_by" not in out_ir)
        got = _notice_line(markdown)
        _require(f"full-mode notice wrong: {got!r}", got == OLD_STANDING_NOTICE)
        return True
    attempt("R4A.full_mode_ir_never_labeled_template", full_mode_ir_never_labeled_template)

    def rare_ppv_text():
        got = caveats.CAVEAT_REGISTRY["rare_ppv"]
        _require(f"rare_ppv text wrong: {got!r}", got == NEW_RARE_PPV)
        fs = [_hf("f_000000000001", "rs9000001", "GENEA", "Condition one", "detected", "hom_alt",
                  "carrier_status", rarity="rare")]
        doc = _hdoc(fs)
        ir, errors = _report(doc)
        _require(f"template IR invalid: {errors}", not errors)
        markdown = render(doc, ir)
        _require("rendered report lacks the new rare caveat", f"- {NEW_RARE_PPV}" in markdown)
        _require("rendered report still has the old rare caveat", "Rare heterozygous" not in markdown)
        return True
    attempt("R4A.rare_ppv_text", rare_ppv_text)

    def provenance_line_states_input_build():
        fs = _mixed_doc()["findings"]
        stated = _hdoc(fs)
        lines = render(stated, stage3_run.template_ir(stated, "0" * 64)).splitlines()
        i = lines.index(f"- Build: {stated['provenance']['genome_build']}, strand: {stated['provenance']['strand']}")
        _require(f"stated-build line wrong: {lines[i + 1]!r}",
                 lines[i + 1] == "- Input build: GRCh37 (stated in the file)")
        assumed = _hdoc(fs)
        assumed["provenance"].update(input_build="unknown", build_basis="not_stated")
        lines = render(assumed, stage3_run.template_ir(assumed, "0" * 64)).splitlines()
        i = lines.index("- Build: GRCh37, strand: forward")
        _require(f"assumed-build line wrong: {lines[i + 1]!r}",
                 lines[i + 1] == "- Input build: not stated in the file; assumed to match the panel (GRCh37)")
        for name, want in (("raw.release.synthetic.txt", "- Input build: GRCh37 (stated in the file)"),):
            doc = _release_doc(name)
            _require("release fixture provenance changed",
                     doc["provenance"]["build_basis"] == "file_statement")
            _require(f"{name}: no input build line",
                     want in render(doc, stage3_run.template_ir(doc, "0" * 64)).splitlines())
        legacy = _load(os.path.join(FIX, "findings.sample.json"))
        _require("legacy report gained an Input build line",
                 "Input build" not in render(legacy, _load(os.path.join(FIX, "report.sample.json"))))
        return True
    attempt("R4A.provenance_line_states_input_build", provenance_line_states_input_build)

    def validator_rejects_missing_coverage_summary():
        doc = _mixed_doc()
        ir, errors = _report(doc)
        _require(f"pristine template IR invalid: {errors}", not errors)
        _require("template IR not labeled template", ir.get("generated_by") == "template")
        for label, mutate in (
                ("Summary section removed", lambda i: i.update(
                    sections=[s for s in i["sections"] if s["section_id"] != "s_summary"])),
                ("Summary section emptied", lambda i: _section(i, "s_summary").update(claims=[]))):
            bad = json.loads(json.dumps(ir))
            mutate(bad)
            codes = [c for c, _m in _validate_ir(doc, bad)]
            _require(f"{label}: R8 not raised ({codes})", "R8" in codes)
        return True
    attempt("R4A.validator_rejects_missing_coverage_summary", validator_rejects_missing_coverage_summary)

    def validator_rejects_mixed_result_type_section():
        doc = _mixed_doc()
        ir, errors = _report(doc)
        _require(f"pristine template IR invalid: {errors}", not errors)
        bad = json.loads(json.dumps(ir))
        moved = _section(bad, "s_traits")["claims"].pop()
        _section(bad, "s_carrier_status")["claims"].append(moved)
        errors = _validate_ir(doc, bad)
        _require(f"R9 not raised: {errors}", any(c == "R9" for c, _m in errors))
        _require(f"unexpected extra errors: {errors}", all(c == "R9" for c, _m in errors))
        return True
    attempt("R4A.validator_rejects_mixed_result_type_section", validator_rejects_mixed_result_type_section)

    def validator_not_covered_keeps_phrase():
        doc = _mixed_doc()
        ir, errors = _report(doc)
        _require(f"pristine template IR invalid: {errors}", not errors)
        bad = json.loads(json.dumps(ir))
        claim = next(cl for _s, cl in _claims(bad, "s_carrier_status") if cl["claim_id"].endswith("000000000004"))
        _require("not_covered claim lacks 'not measured'", "not measured" in claim["text"])
        claim["text"] = "Condition four (GENED): this entry is unavailable on this array."
        errors = _validate_ir(doc, bad)
        _require(f"R10 not raised: {errors}", any(c == "R10" for c, _m in errors))
        # a not_covered anchor in the Summary must not trip R10 on a pristine report
        first_missing = _hdoc([
            _hf("f_000000000001", "rs9000001", "GENEA", "Condition one", "not_covered", "unknown", "carrier_status"),
            _hf("f_000000000002", "rs9000002", "GENEB", "Condition two", "detected", "het", "risk_association")])
        _ir, errors = _report(first_missing)
        _require(f"pristine report with a not_covered anchor invalid: {errors}", not errors)
        return True
    attempt("R4A.validator_not_covered_keeps_phrase", validator_not_covered_keeps_phrase)

    def legacy_and_model_reports_still_validate():
        errors, _ = validate_report.check(os.path.join(FIX, "findings.sample.json"),
                                          _load(os.path.join(FIX, "report.sample.json")))
        _require(f"sample report fixture invalid: {errors}", not errors)
        doc = _mixed_doc()
        ir, _errors = _report(doc)
        model = json.loads(json.dumps(ir))
        model["sections"] = [s for s in model["sections"] if s["section_id"] != "s_summary"]
        moved = _section(model, "s_traits")["claims"].pop()
        _section(model, "s_carrier_status")["claims"].append(moved)
        _claim = next(cl for _s, cl in _claims(model, "s_carrier_status") if cl["claim_id"].endswith("000000000004"))
        _claim["text"] = "Condition four (GENED): this entry is unavailable on this array."
        for label, value in (("model", "model"), ("absent", None)):
            candidate = dict(model)
            if value is not None:
                candidate["generated_by"] = value
            errors = _validate_ir(doc, candidate)
            _require(f"generated_by={label}: model-shaped IR rejected: {errors}", not errors)
        legacy = _load(os.path.join(FIX, "findings.sample.json"))
        lir, errors = _report(legacy)
        _require(f"legacy template IR invalid: {errors}", not errors)
        _require("legacy template IR not labeled template", lir.get("generated_by") == "template")
        return True
    attempt("R4A.legacy_and_model_reports_still_validate", legacy_and_model_reports_still_validate)

    def limitations_section_present():
        limitations = getattr(caveats, "LIMITATIONS", None)
        _require("caveats.LIMITATIONS missing", isinstance(limitations, list) and len(limitations) == 8)
        for name in RELEASE_FIXTURES:
            doc = _release_doc(name)
            markdown = render(doc, stage3_run.template_ir(doc, "0" * 64))
            headings = [l for l in markdown.splitlines() if l.startswith("## ")]
            _require(f"{name}: last sections are {headings[-2:]}",
                     headings[-2:] == ["## Evidence and sources", "## Limitations"])
            tail = markdown[markdown.index("## Limitations"):]
            for item in limitations:
                _require(f"{name}: limitation not rendered: {item!r}", f"- {item}" in tail)
        # only a template-generated release-format report gets them
        legacy = _load(os.path.join(FIX, "findings.sample.json"))
        legacy_md = render(legacy, stage3_run.template_ir(legacy, "0" * 64))
        _require("legacy template report gained the registry sections",
                 "## Limitations" not in legacy_md and "## Evidence and sources" not in legacy_md)
        doc = _release_doc("raw.release.synthetic.txt")
        model_ir = dict(stage3_run.template_ir(doc, "0" * 64), generated_by="model")
        model_md = render(doc, model_ir)
        _require("model report gained the registry sections",
                 "## Limitations" not in model_md and "## Evidence and sources" not in model_md)
        return True
    attempt("R4A.limitations_section_present", limitations_section_present)

    def tier_definitions_present():
        tiers = getattr(caveats, "TIER_DEFINITIONS", None)
        _require("caveats.TIER_DEFINITIONS missing", isinstance(tiers, dict))
        _require(f"tier keys wrong: {sorted(tiers)}", sorted(tiers) == sorted(TIER_KEYS))
        replicated = tiers["replicated"]
        for phrase in ("two review stars", "two or more matching GWAS",
                       "does not by itself mean independent replication studies"):
            _require(f"replicated definition lacks {phrase!r}", phrase in replicated)
        for key in TIER_KEYS:
            _require(f"definition for {key!r} is empty", isinstance(tiers[key], str) and tiers[key].strip())
        # the registry tier words are the words the claims use
        for word in stage3_run.TIER_WORDS.values():
            _require(f"claim tier word {word!r} has no definition",
                     word in tiers or word == "none")
        doc = _release_doc("raw.release.synthetic.txt")
        markdown = render(doc, stage3_run.template_ir(doc, "0" * 64))
        section = markdown[markdown.index("## Evidence and sources"):markdown.index("## Limitations")]
        for key in TIER_KEYS:
            _require(f"{key!r} definition not rendered", tiers[key] in section)
        _require("Evidence and sources section carries claims or citations", "[f_" not in section)
        return True
    attempt("R4A.tier_definitions_present", tier_definitions_present)

    def limitations_agree_with_docs():
        limitations = getattr(caveats, "LIMITATIONS", None)
        _require("caveats.LIMITATIONS missing", isinstance(limitations, list) and limitations)
        docs = ""
        for name in DOC_FILES:
            with open(os.path.join(ROOT, "docs", name)) as fh:
                docs += " " + fh.read()
        docs = " ".join(docs.lower().split())
        for item in limitations:
            hits = [k for k in LIMITATION_KEYS if k in item.lower()]
            _require(f"limitation has no key phrase: {item!r}", len(hits) == 1)
            _require(f"key phrase {hits[0]!r} not found in the docs", hits[0] in docs)
        for key in LIMITATION_KEYS:
            _require(f"key phrase {key!r} matches {sum(key in i.lower() for i in limitations)} items",
                     sum(key in i.lower() for i in limitations) == 1)
        return True
    attempt("R4A.limitations_agree_with_docs", limitations_agree_with_docs)

    def schema_accepts_generated_by():
        try:
            import jsonschema
        except ImportError:
            return True  # schema checks run only where jsonschema is installed
        with open(os.path.join(ROOT, "schema", "report_ir.schema.json")) as fh:
            schema = json.load(fh)
        props = schema["properties"]
        _require(f"generated_by property wrong: {props.get('generated_by')}",
                 props.get("generated_by", {}).get("enum") == ["template", "model"])
        _require("generated_by became required", "generated_by" not in schema["required"])
        validator = jsonschema.Draft202012Validator(schema)
        base = _load(os.path.join(FIX, "report.sample.json"))
        _require("existing IR without generated_by rejected", not list(validator.iter_errors(base)))
        for value in ("template", "model"):
            errs = list(validator.iter_errors(dict(base, generated_by=value)))
            _require(f"generated_by={value!r} rejected: {[e.message for e in errs]}", not errs)
        _require("generated_by='other' accepted",
                 bool(list(validator.iter_errors(dict(base, generated_by="other")))))
        return True
    attempt("R4A.schema_accepts_generated_by", schema_accepts_generated_by)


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
    _run_4a2_characterization(attempt)
    _run_behavior(attempt)
    _run_4a2_behavior(attempt)


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
