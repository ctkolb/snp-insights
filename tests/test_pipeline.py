#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Pipeline tests. No framework; run with:  python tests/test_pipeline.py

Covers the AncestryDNA parser, the deterministic annotator, ETL robustness
against messy ClinVar/gnomAD inputs, condition normalization, the semantic lint,
and an end-to-end validator pass/fail.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "stage2"))

import ancestry  # noqa: E402
import annotate  # noqa: E402
import build_panel  # noqa: E402
import validate_report  # noqa: E402

FIX = os.path.join(ROOT, "fixtures")
DATA = os.path.join(ROOT, "data")
ALIASES = os.path.join(DATA, "condition_aliases.json")

PASSED = []
FAILED = []


def check(name, cond):
    (PASSED if cond else FAILED).append(name)


def load(path):
    with open(path) as fh:
        return json.load(fh)


def test_parser():
    raw = ancestry.parse_ancestry(os.path.join(FIX, "raw.sample.txt"))
    check("parser array_version", raw["meta"]["array_version"] == "V2.0")
    check("parser build", raw["meta"]["genome_build"] == "GRCh37")
    check("parser row_count", raw["row_count"] == 11)
    check("parser no-call is 0", raw["rows"]["rs429358"]["allele1"] == "0")
    check("chromosome 23->X", ancestry.normalize_chromosome("23") == "X")
    check("chromosome 24->Y", ancestry.normalize_chromosome("24") == "Y")
    check("chromosome 25->PAR", ancestry.normalize_chromosome("25") == "PAR")
    check("chromosome 26->MT", ancestry.normalize_chromosome("26") == "MT")


def test_annotator():
    panel = load(os.path.join(DATA, "panel.sample.json"))
    doc = annotate.build_findings(os.path.join(FIX, "raw.sample.txt"), panel, annotate.load_aliases(ALIASES))
    by = {f["rsid"]: f for f in doc["findings"] if f["rsid"]}
    check("state detected", by["rs4988235"]["state"] == "detected")
    check("state covered_reference", by["rs6025"]["state"] == "covered_reference")
    check("state covered_nocall", by["rs429358"]["state"] == "covered_nocall")
    check("state not_covered", by["rs80357906"]["state"] == "not_covered")
    check("state not_assayable", any(f["state"] == "not_assayable" for f in doc["findings"]))
    check("state covered_uninterpretable", any(f["state"] == "covered_uninterpretable" for f in doc["findings"]))
    check("rare ppv set", by["rs121918897"]["confidence"]["array_reliability"]["ppv_note"] is not None)
    check("contradiction emitted", len(doc["contradictions"]) == 1)
    check("palindromic strand flag", by["rs1333049"]["call"]["strand"] == "ambiguous")


def test_condition_normalization():
    aliases = annotate.load_aliases(ALIASES)
    check("normalize alias", annotate.normalize_condition("Haemochromatosis", aliases) == "hereditary hemochromatosis")
    check("normalize punctuation", annotate.normalize_condition("  Hemochromatosis! ", aliases) == "hereditary hemochromatosis")
    f1 = {"condition": "Hemochromatosis", "rsid": "rs1", "finding_id": "f_a",
          "evidence": {"clinvar": {"review_stars": 2, "significance": "Pathogenic"}, "association": "established"}}
    f2 = {"condition": "Hereditary haemochromatosis", "rsid": "rs2", "finding_id": "f_b",
          "evidence": {"clinvar": {"review_stars": 1, "significance": "Conflicting interpretations of pathogenicity"}, "association": "conflicting"}}
    cs = annotate.compute_contradictions([f1, f2], aliases)
    check("alias-grouped contradiction", len(cs) == 1 and set(cs[0]["finding_ids"]) == {"f_a", "f_b"})


def test_etl_messy():
    cv = build_panel.load_clinvar(os.path.join(FIX, "sources/clinvar.messy.tsv"), "test")
    check("etl messy stars", cv.get("rs1800562", {}).get("review_stars") == 2)
    check("etl numeric RS# -> rsid", cv.get("rs6025", {}).get("review_stars") == 3)
    check("etl skips GRCh38", "rs1799945" not in cv)
    g = build_panel.load_gnomad(os.path.join(FIX, "sources/gnomad.messy.vcf"))
    check("etl scientific AF", abs(g.get("rs1800562", {}).get("af", -1) - 0.02) < 1e-9)
    check("etl multiallelic AF first", abs(g.get("rs1799945", {}).get("af", -1) - 0.1) < 1e-9)
    check("etl missing AF -> None", g.get("rs6025", {}).get("af") is None)


def test_semantic_lint():
    v = validate_report.semantic_violations
    check("lint presence on non-detected", bool(v("The variant was detected in HFE.", [{"state": "covered_reference"}])))
    check("lint sequencing", bool(v("The array used sequencing data.", [{"state": "detected"}])))
    check("lint absence on not_covered", bool(v("You do not have the variant.", [{"state": "not_covered"}])))
    check("lint absolute", bool(v("You will develop the disease.", [{"state": "detected"}])))
    check("lint ok unmeasured phrase", not v("This marker was not measured by the array.", [{"state": "not_covered"}]))
    check("lint ok detected phrase", not v("The variant was detected.", [{"state": "detected"}]))
    check("lint ok reference phrase", not v("the variant is not present.", [{"state": "covered_reference"}]))


def test_db_merge():
    merges = build_panel.load_merges(os.path.join(FIX, "sources/rsmerge.sample.tsv"))
    check("merge high-to-low", merges.get("rs1234567") == "rs1800562" and merges.get("rs424242") == "rs1799945")
    rev = build_panel.load_merges(os.path.join(FIX, "sources/rsmerge.sample.tsv"), "low-to-high")
    check("merge low-to-high", rev.get("rs1800562") == "rs1234567")

    # panel carries an OLD rsID; file carries the NEW one (raw.sample has rs1800562)
    old_panel = {"merges": {"rs1234567": "rs1800562"}, "variants": [{
        "rsid": "rs1234567", "chromosome": "6", "position": 26093141, "gene": "HFE",
        "condition": None, "assayability": "snp", "reference_allele": "G", "alternate_allele": "A",
        "cls": "pathogenic", "association": "established", "clinvar": None, "snpedia": None,
    }]}
    doc = annotate.build_findings(os.path.join(FIX, "raw.sample.txt"), old_panel)
    f = doc["findings"][0]
    check("merge matches old panel id to new file id", f["state"] == "detected")
    check("merge recorded in basis", any("merge map applied" in b for b in f["confidence"]["annotation_mapping"]["basis"]))

    # panel carries the NEW rsID; file carries the OLD one
    import tempfile
    new_panel = {"merges": {"rs1234567": "rs1800562"}, "variants": [{
        "rsid": "rs1800562", "chromosome": "6", "position": 26093141, "gene": "HFE",
        "condition": None, "assayability": "snp", "reference_allele": "G", "alternate_allele": "A",
        "cls": "pathogenic", "association": "established", "clinvar": None, "snpedia": None,
    }]}
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write("rsid\tchromosome\tposition\tallele1\tallele2\n")
        fh.write("rs1234567\t6\t26093141\tA\tG\n")
        tmp = fh.name
    try:
        doc2 = annotate.build_findings(tmp, new_panel)
        check("merge matches new panel id to old file id", doc2["findings"][0]["state"] == "detected")
    finally:
        os.unlink(tmp)


def test_sex_chromosomes():
    raw = ancestry.parse_ancestry(os.path.join(FIX, "raw.sex.txt"))
    check("infer male", annotate.infer_sex(raw) == "male")

    def v(rsid, chrom, pos, ref, alt):
        return {"rsid": rsid, "chromosome": chrom, "position": pos, "gene": "G", "condition": None,
                "assayability": "snp", "reference_allele": ref, "alternate_allele": alt,
                "cls": "risk", "association": "none", "clinvar": None, "snpedia": None}

    panel = {"merges": {}, "variants": [
        v("rsX1", "X", 1000000, "G", "A"),   # raw A/A -> hom_alt detected
        v("rsY1", "Y", 3000000, "T", "C"),   # raw T/T -> hom_ref
        v("rsMT1", "MT", 4000000, "C", "T"), # raw C/C -> hom_ref
    ]}
    doc = annotate.build_findings(os.path.join(FIX, "raw.sex.txt"), panel)
    check("provenance inferred_sex", doc["provenance"]["inferred_sex"] == "male")
    by = {f["rsid"]: f for f in doc["findings"]}
    check("male X hemizygous", by["rsX1"]["call"]["zygosity"] == "hemizygous")
    check("male Y hemizygous", by["rsY1"]["call"]["zygosity"] == "hemizygous")
    check("MT homoplasmic", by["rsMT1"]["call"]["zygosity"] == "homoplasmic")

    # female: X heterozygous, no Y
    import tempfile
    lines = ["rsid\tchromosome\tposition\tallele1\tallele2"]
    for i in range(20):
        a1, a2 = ("A", "G") if i < 3 else ("A", "A")
        lines.append(f"rsF{i}\t23\t{1000000+i*1000}\t{a1}\t{a2}")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write("\n".join(lines) + "\n")
        tmp = fh.name
    try:
        fraww = ancestry.parse_ancestry(tmp)
        check("infer female", annotate.infer_sex(fraww) == "female")
        fpanel = {"merges": {}, "variants": [v("rsF0", "X", 1000000, "A", "G")]}
        fdoc = annotate.build_findings(tmp, fpanel)
        check("female X stays diploid", fdoc["findings"][0]["call"]["zygosity"] == "het")
    finally:
        os.unlink(tmp)


def test_validator_e2e():
    good = validate_report.check(os.path.join(FIX, "findings.sample.json"), load(os.path.join(FIX, "report.sample.json")))
    check("validator accepts sample", not good[0])
    bad = validate_report.check(os.path.join(FIX, "findings.sample.json"), load(os.path.join(FIX, "report.bad.json")))
    check("validator rejects bad", bool(bad[0]))


def main():
    test_parser()
    test_annotator()
    test_condition_normalization()
    test_etl_messy()
    test_db_merge()
    test_sex_chromosomes()
    test_semantic_lint()
    test_validator_e2e()
    for name in PASSED:
        print(f"  ok   {name}")
    for name in FAILED:
        print(f"  FAIL {name}")
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
