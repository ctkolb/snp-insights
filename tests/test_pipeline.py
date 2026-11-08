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
import fetch_reference  # noqa: E402
import snpedia_to_tsv  # noqa: E402
import validate_report  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import check_raw  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "tests"))
import test_guard  # noqa: E402
import test_evidence  # noqa: E402
import test_category  # noqa: E402
import test_cli  # noqa: E402
import test_interpretation  # noqa: E402

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


def test_references_and_scan():
    panel = load(os.path.join(DATA, "panel.sample.json"))
    doc = annotate.build_findings(os.path.join(FIX, "raw.sample.txt"), panel, annotate.load_aliases(ALIASES))
    by = {f["rsid"]: f for f in doc["findings"] if f["rsid"]}
    srcs = {r["source"] for r in by["rs4988235"]["references"]}
    check("references include dbSNP/ClinVar/gnomAD", {"dbSNP", "ClinVar", "gnomAD"} <= srcs)
    cftr = next(f for f in doc["findings"] if f.get("gene") == "CFTR")
    check("indel has no gnomAD link", all(r["source"] != "gnomAD" for r in cftr["references"]))
    s = check_raw.structural_scan(os.path.join(FIX, "raw.sample.txt"))
    check("scan chrom sum equals rows", sum(s["chrom_counts"].values()) == s["row_count"])


def test_evidence_tiers():
    schema = load(os.path.join(ROOT, "schema", "findings.schema.json"))
    enum = schema["$defs"]["evidence"]["properties"]["association"]["enum"]
    check("association tiers", set(enum) == {"established", "replicated", "single_study", "conflicting", "none", "unknown"})

    swf = validate_report.strong_wording_forbidden

    def f(assoc, stars=None):
        return {"evidence": {"association": assoc,
                             "clinvar": ({"review_stars": stars} if stars is not None else None)}}

    check("strong allowed only when established", not swf(f("established", 3)))
    check("strong blocked for replicated", swf(f("replicated", 2)))
    check("strong blocked for single_study", swf(f("single_study", None)))
    check("strong blocked for conflicting", swf(f("conflicting", 1)))
    check("strong blocked for unknown", swf(f("unknown", None)))
    check("strong blocked for established-with-1-star", swf(f("established", 1)))


def test_etl_sources():
    vcf = os.path.join(FIX, "sources/dbsnp.sample.vcf")
    db = build_panel.load_dbsnp(vcf, {"rs4988235", "rs1333049"})
    check("dbsnp vcf coords", db["rs4988235"]["position"] == 136608646 and db["rs4988235"]["reference_allele"] == "G")
    dbt = build_panel.load_dbsnp(os.path.join(FIX, "sources/dbsnp.sample.tsv"), {"rs6025"})
    check("dbsnp tsv coords", dbt["rs6025"]["position"] == 169519049)

    gwas = build_panel.load_gwas(os.path.join(FIX, "sources/gwas.sample.tsv"), {"rs1333049", "rs4988235"})
    check("gwas study count", gwas["rs1333049"] == 2 and gwas["rs4988235"] == 1)
    check("gwas tier mapping", build_panel.assoc_from_gwas(2) == "replicated" and build_panel.assoc_from_gwas(1) == "single_study")
    check("clinvar tier established", build_panel.assoc_from_clinvar({"review_stars": 3, "significance": "Pathogenic"}) == "established")
    check("clinvar tier replicated", build_panel.assoc_from_clinvar({"review_stars": 2, "significance": "Pathogenic"}) == "replicated")
    check("clinvar tier conflicting", build_panel.assoc_from_clinvar({"review_stars": 1, "significance": "Conflicting interpretations of pathogenicity"}) == "conflicting")
    check("clinvar 0-star defers to gwas", build_panel.assoc_from_clinvar({"review_stars": 0, "significance": "not provided"}) is None)

    sp = build_panel.load_snpedia(os.path.join(FIX, "sources/snpedia.sample.tsv"))
    check("snpedia magnitude", sp.get("rs4988235", {}).get("magnitude") == 2)

    targets = {"variants": [
        {"rsid": "rs1333049", "gene": "CDKN2B-AS1", "condition": "Coronary artery disease", "assayability": "snp", "cls": "risk"},
        {"rsid": "rs4988235", "gene": "MCM6", "condition": None, "assayability": "snp", "cls": "risk"},
    ]}
    panel = build_panel.build(targets, sources=[], dbsnp=build_panel.load_dbsnp(vcf, {"rs1333049", "rs4988235"}),
                              gwas=gwas, snpedia=sp)
    by = {x["rsid"]: x for x in panel["variants"]}
    check("dbsnp fill in build", by["rs1333049"]["chromosome"] == "9" and by["rs1333049"]["position"] == 22125504)
    check("association derived from gwas",
          by["rs1333049"]["association"] == "replicated" and by["rs4988235"]["association"] == "single_study")
    check("snpedia attached", by["rs4988235"]["snpedia"] == {"magnitude": 2})


def test_fetch_reference():
    import tempfile
    check("accession map chr2", fetch_reference.GRCH37_ACCESSIONS["NC_000002.11"] == "2")
    check("accession map X", fetch_reference.GRCH37_ACCESSIONS["NC_000023.10"] == "X")
    rs = fetch_reference.load_target_rsids([os.path.join(DATA, "targets.carrier.json"),
                                            os.path.join(DATA, "targets.traits.json")])
    check("target rsids collected + deduped", "rs334" in rs and "rs12913832" in rs and len(rs) == len(set(rs)))

    d = tempfile.mkdtemp()
    coords = {"rs4988235": ("2", 136608646, "G", "A")}
    fetch_reference.write_dbsnp_tsv(os.path.join(d, "dbsnp.tsv"), coords)
    check("fetch dbsnp tsv -> etl", build_panel.load_dbsnp(os.path.join(d, "dbsnp.tsv"), {"rs4988235"})["rs4988235"]["position"] == 136608646)
    fetch_reference.write_clinvar_tsv(os.path.join(d, "clinvar.tsv"),
                                      {"rs1800562": ("Pathogenic", "criteria provided, multiple submitters, no conflicts")})
    check("fetch clinvar tsv -> etl", build_panel.load_clinvar(os.path.join(d, "clinvar.tsv"), "test")["rs1800562"]["review_stars"] == 2)
    fetch_reference.write_snpedia_tsv(os.path.join(d, "snpedia.tsv"), {"rs1805007": 3})
    check("fetch snpedia tsv -> etl", build_panel.load_snpedia(os.path.join(d, "snpedia.tsv"))["rs1805007"]["magnitude"] == 3)
    fetch_reference.write_gnomad_vcf(os.path.join(d, "g.vcf"), coords, {"rs4988235": 0.25})
    check("fetch gnomad vcf -> etl", build_panel.load_gnomad(os.path.join(d, "g.vcf"))["rs4988235"]["af"] == 0.25)

    header = ["SNPS", "PUBMEDID", "DISEASE/TRAIT"]
    lines = ["rs1333049\t1\tTrait A", "rs999\t2\tTrait B", "rs1333049 x rs4988235\t3\tTrait C"]
    kept = fetch_reference._filter_gwas(header, lines, {"rs1333049"})
    check("gwas filter keeps matches", len(kept) == 2)

    unassessed = build_panel.build({"variants": [{"rsid": "rsNOPE", "gene": "X", "condition": "Trait", "assayability": "snp"}]}, sources=[])
    check("unassessed association is unknown", unassessed["variants"][0]["association"] == "unknown")


def test_effect_allele():
    import tempfile

    panel = {"merges": {}, "variants": [{
        "rsid": "rs6025", "chromosome": "1", "position": 169519049, "gene": "F5",
        "condition": "Factor V Leiden thrombophilia", "assayability": "snp",
        "reference_allele": "T", "alternate_allele": "C", "effect_allele": "T",
        "cls": "risk", "association": "established"}]}

    def state(a1, a2):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("rsid\tchromosome\tposition\tallele1\tallele2\n")
            fh.write(f"rs6025\t1\t169519049\t{a1}\t{a2}\n")
            path = fh.name
        try:
            return annotate.build_findings(path, panel)["findings"][0]
        finally:
            os.unlink(path)

    check("effect present homozygous -> detected", state("T", "T")["state"] == "detected")
    check("effect present heterozygous -> detected", state("T", "C")["state"] == "detected")
    check("effect absent -> covered_reference", state("C", "C")["state"] == "covered_reference")


def test_clinvar_selection():
    recs = [
        {"title": "NM_198578.4(LRRK2):c.6055G>A", "sig": "Pathogenic", "review": "criteria provided, multiple submitters, no conflicts"},
        {"title": "NM_000130.5(F5):c.1601=", "sig": "Conflicting classifications of pathogenicity", "review": "criteria provided, conflicting classifications"},
        {"title": "NM_000130.4(F5):c.1601G>A", "sig": "drug response", "review": "reviewed by expert panel"},
    ]
    best = fetch_reference._select_clinvar(recs, "F5")
    check("clinvar gene filter drops unrelated record", best == ("drug response", "reviewed by expert panel"))


def test_clinvar_phenotype():
    aliases = fetch_reference.load_condition_aliases()
    check("condition matches alias", fetch_reference._condition_matches("Hemochromatosis|not provided", "Hereditary hemochromatosis", aliases))
    check("condition no match", not fetch_reference._condition_matches("Cystic fibrosis", "Hereditary hemochromatosis", {}))
    rows = [
        {"sig": "drug response", "review": "reviewed by expert panel", "phenotype": "not provided"},
        {"sig": "Pathogenic", "review": "criteria provided, multiple submitters, no conflicts", "phenotype": "Hereditary hemochromatosis"},
    ]
    best = fetch_reference._select_clinvar_summary(rows, "Hereditary hemochromatosis", aliases)
    check("phenotype-matched record preferred", best == ("Pathogenic", "criteria provided, multiple submitters, no conflicts"))


def test_snpedia_convert():
    import tempfile
    xml = "<mediawiki><page><title>Rs1805007</title><revision><text>{{magnitude=3}}</text></revision></page></mediawiki>"
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
        fh.write(xml)
        xp = fh.name
    try:
        check("snpedia xml convert", list(snpedia_to_tsv.from_xml(xp)) == [("rs1805007", 3)])
    finally:
        os.unlink(xp)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        fh.write('{"Rs4988235":"...|magnitude=2|..."}')
        jp = fh.name
    try:
        check("snpedia json convert", list(snpedia_to_tsv.from_json(jp)) == [("rs4988235", 2)])
    finally:
        os.unlink(jp)


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
    test_etl_sources()
    test_fetch_reference()
    test_db_merge()
    test_sex_chromosomes()
    test_semantic_lint()
    test_references_and_scan()
    test_evidence_tiers()
    test_effect_allele()
    test_clinvar_selection()
    test_clinvar_phenotype()
    test_snpedia_convert()
    test_validator_e2e()
    test_guard.run(check)
    test_evidence.run(check)
    test_category.run(check)
    test_cli.run(check)
    test_interpretation.run(check)
    for name in PASSED:
        print(f"  ok   {name}")
    for name in FAILED:
        print(f"  FAIL {name}")
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
