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
