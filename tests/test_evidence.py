#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Stage 1 gates for tools/evidence.py and condition-aware matching.

Run standalone:  python tests/test_evidence.py
Or as part of:   python tests/test_pipeline.py

Every gate is isolated: a missing module, a missing function, or any exception
fails only that one check (via attempt()), never the whole run.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

DATA = os.path.join(ROOT, "data")
FIX = os.path.join(ROOT, "fixtures")
ALIASES_PATH = os.path.join(DATA, "condition_aliases.json")


def _load(path):
    with open(path) as fh:
        return json.load(fh)


def _mods():
    import build_panel  # noqa: F401
    import evidence  # noqa: F401
    import fetch_reference  # noqa: F401
    return evidence, fetch_reference, build_panel


def _identity(modname, attr):
    evidence, fetch_reference, build_panel = _mods()
    mod = {"fetch_reference": fetch_reference, "build_panel": build_panel}[modname]
    return getattr(mod, attr) is getattr(evidence, attr)


def _clinvar_rows():
    return [
        {"sig": "Pathogenic", "review": "reviewed by expert panel",
         "phenotype": "Factor V Leiden thrombophilia"},
        {"sig": "drug response", "review": "reviewed by expert panel",
         "phenotype": "Warfarin response"},
    ]


def run(check):
    def attempt(name, fn):
        try:
            result = fn()
        except Exception:  # noqa: BLE001
            check(name, False)
            return
        check(name, bool(result))

    try:
        aliases = _load(ALIASES_PATH)
    except Exception:  # noqa: BLE001
        aliases = {}

    # --- S1.identity_* ---------------------------------------------------
    for attr in ("norm_cond", "condition_matches", "sig_rank", "review_stars"):
        attempt(f"S1.identity_fetch_{attr}",
                lambda a=attr: _identity("fetch_reference", a))
        attempt(f"S1.identity_build_{attr}",
                lambda a=attr: _identity("build_panel", a))

    # --- S1.cond_* -------------------------------------------------------
    def cond_word_boundary():
        evidence, _, _ = _mods()
        return (not evidence.condition_matches("G6PDX deficiency", "G6PD", {})
                and evidence.condition_matches("G6PD deficiency", "G6PD", {}))
    attempt("S1.cond_word_boundary", cond_word_boundary)

    def cond_alias_hit():
        evidence, _, _ = _mods()
        return evidence.condition_matches("Hemochromatosis type 1",
                                          "Hereditary hemochromatosis", aliases)
    attempt("S1.cond_alias_hit", cond_alias_hit)

    def cond_case_punct():
        evidence, _, _ = _mods()
        return evidence.condition_matches("  HEMOCHROMATOSIS!!  ", "hemochromatosis", {})
    attempt("S1.cond_case_punctuation", cond_case_punct)

    def cond_falsy():
        evidence, _, _ = _mods()
        return (not evidence.condition_matches("", "x", {})
                and not evidence.condition_matches("x", "", {})
                and not evidence.condition_matches(None, None, {}))
    attempt("S1.cond_falsy", cond_falsy)

    # --- S1.select_* -----------------------------------------------------
    def sel_pathogenic_beats_drug():
        evidence, _, _ = _mods()
        rows = _clinvar_rows()
        fwd = evidence.select_clinvar(rows, "Factor V Leiden thrombophilia", aliases)
        rev = evidence.select_clinvar(list(reversed(rows)), "Factor V Leiden thrombophilia", aliases)
        return fwd["sig"] == "Pathogenic" and rev["sig"] == "Pathogenic"
    attempt("S1.select_pathogenic_beats_drug", sel_pathogenic_beats_drug)

    def sel_phenotype_beats_unmatched():
        evidence, _, _ = _mods()
        rows = [
            {"sig": "Pathogenic", "review": "criteria provided, multiple submitters, no conflicts",
             "phenotype": "Cystic fibrosis"},
            {"sig": "Pathogenic", "review": "criteria provided, multiple submitters, no conflicts",
             "phenotype": "Hereditary hemochromatosis"},
        ]
        best = evidence.select_clinvar(rows, "Hereditary hemochromatosis", aliases)
        return best["phenotype"] == "Hereditary hemochromatosis"
    attempt("S1.select_phenotype_beats_unmatched", sel_phenotype_beats_unmatched)

    def sel_stars_break_tie():
        evidence, _, _ = _mods()
        rows = [
            {"sig": "Pathogenic", "review": "criteria provided, single submitter",
             "phenotype": "Hereditary hemochromatosis"},
            {"sig": "Pathogenic", "review": "reviewed by expert panel",
             "phenotype": "Hereditary hemochromatosis"},
        ]
        best = evidence.select_clinvar(rows, "Hereditary hemochromatosis", aliases)
        return best["review"] == "reviewed by expert panel"
    attempt("S1.select_stars_break_tie", sel_stars_break_tie)

    def sel_first_row_tie():
        evidence, _, _ = _mods()
        rows = [
            {"sig": "Pathogenic", "review": "reviewed by expert panel",
             "phenotype": "Hereditary hemochromatosis", "tag": "first"},
            {"sig": "Pathogenic", "review": "reviewed by expert panel",
             "phenotype": "Hereditary hemochromatosis", "tag": "second"},
        ]
        return evidence.select_clinvar(rows, "Hereditary hemochromatosis", aliases)["tag"] == "first"
    attempt("S1.select_first_row_tie", sel_first_row_tie)

    def sel_skip_empty_sig():
        evidence, _, _ = _mods()
        rows = [
            {"sig": "", "review": "reviewed by expert panel",
             "phenotype": "Hereditary hemochromatosis"},
            {"sig": "Pathogenic", "review": "criteria provided, single submitter",
             "phenotype": "Hereditary hemochromatosis"},
        ]
        best = evidence.select_clinvar(rows, "Hereditary hemochromatosis", aliases)
        return best["sig"] == "Pathogenic"
    attempt("S1.select_skip_empty_sig", sel_skip_empty_sig)

    def sel_empty_none():
        evidence, _, _ = _mods()
        return evidence.select_clinvar([], "x", aliases) is None
    attempt("S1.select_empty_list_none", sel_empty_none)

    # --- S1.clinvar_* ----------------------------------------------------
    def clinvar_rs6025_both_orders():
        _, _, build_panel = _mods()

        def write(order):
            p = os.path.join(tempfile.mkdtemp(), "clinvar.tsv")
            with open(p, "w") as fh:
                fh.write("RS# (dbSNP)\tAssembly\tReviewStatus\tClinicalSignificance\tPhenotypeList\n")
                for sig, pheno in order:
                    fh.write(f"6025\tGRCh37\treviewed by expert panel\t{sig}\t{pheno}\n")
            return p

        thrombo = ("Pathogenic", "Factor V Leiden thrombophilia")
        warfarin = ("drug response", "Warfarin response")
        conds = {"rs6025": "Factor V Leiden thrombophilia"}
        a = build_panel.load_clinvar(write([thrombo, warfarin]), "test", conditions=conds, aliases=aliases)
        b = build_panel.load_clinvar(write([warfarin, thrombo]), "test", conditions=conds, aliases=aliases)
        c = build_panel.load_clinvar(write([warfarin, thrombo]), "test")
        return (a["rs6025"]["significance"] == "Pathogenic"
                and b["rs6025"]["significance"] == "Pathogenic"
                and c["rs6025"]["significance"] == "Pathogenic")
    attempt("S1.clinvar_rs6025_both_orders", clinvar_rs6025_both_orders)

    def clinvar_old_format():
        _, _, build_panel = _mods()
        messy = build_panel.load_clinvar(os.path.join(FIX, "sources/clinvar.messy.tsv"), "test")
        ok_messy = (messy.get("rs1800562", {}).get("review_stars") == 2
                    and messy.get("rs6025", {}).get("review_stars") == 3
                    and "rs1799945" not in messy)
        p = os.path.join(tempfile.mkdtemp(), "old.tsv")
        with open(p, "w") as fh:
            fh.write("RS# (dbSNP)\tAssembly\tReviewStatus\tClinicalSignificance\n")
            fh.write("1800562\tGRCh37\tcriteria provided, multiple submitters, no conflicts\tPathogenic\n")
        got = build_panel.load_clinvar(p, "test")
        return (ok_messy and got["rs1800562"]["review_stars"] == 2
                and got["rs1800562"]["phenotype"] == "")
    attempt("S1.clinvar_old_format", clinvar_old_format)

    def clinvar_cache_roundtrip():
        _, fetch_reference, build_panel = _mods()
        d = tempfile.mkdtemp()
        p = os.path.join(d, "clinvar.tsv")
        fetch_reference.write_clinvar_tsv(p, {
            "rs1800562": ("Pathogenic", "criteria provided, multiple submitters, no conflicts",
                          "Hereditary hemochromatosis"),
        })
        got = build_panel.load_clinvar(p, "test")
        ok3 = (got["rs1800562"]["significance"] == "Pathogenic"
               and got["rs1800562"]["review_status_text"]
               == "criteria provided, multiple submitters, no conflicts"
               and got["rs1800562"]["phenotype"] == "Hereditary hemochromatosis")
        p2 = os.path.join(d, "clinvar2.tsv")
        fetch_reference.write_clinvar_tsv(p2, {"rs1800562": ("Pathogenic", "reviewed by expert panel")})
        got2 = build_panel.load_clinvar(p2, "test")
        ok2 = (got2["rs1800562"]["significance"] == "Pathogenic"
               and got2["rs1800562"]["phenotype"] == "")
        return ok3 and ok2
    attempt("S1.clinvar_cache_roundtrip", clinvar_cache_roundtrip)

    # --- S1.gwas_* -------------------------------------------------------
    def gwas_load_unchanged():
        _, _, build_panel = _mods()
        g = build_panel.load_gwas(os.path.join(FIX, "sources/gwas.sample.tsv"),
                                  {"rs1333049", "rs4988235"})
        return g["rs1333049"] == 2 and g["rs4988235"] == 1
    attempt("S1.gwas_load_gwas_unchanged", gwas_load_unchanged)

    def gwas_pairs_dedupe():
        _, _, build_panel = _mods()
        pairs = build_panel.load_gwas_studies(os.path.join(FIX, "sources/gwas.sample.tsv"),
                                              {"rs1333049", "rs4988235"})
        return (pairs["rs1333049"] == [("17478679", "Coronary artery disease"),
                                       ("17634449", "Coronary artery disease")]
                and pairs["rs4988235"] == [("999", "Lactose intolerance")])
    attempt("S1.gwas_studies_pairs_dedupe", gwas_pairs_dedupe)

    def gwas_count_matching():
        evidence, _, _ = _mods()
        pairs = [
            ("s1", "Coronary artery disease"),
            ("s2", "Coronary artery disease"),
            ("s3", "Type 2 diabetes"),
            ("s1", "Coronary artery disease"),
        ]
        return (evidence.count_matching_studies(pairs, "Coronary artery disease", aliases) == 2
                and evidence.count_matching_studies(pairs, "Type 2 diabetes", aliases) == 1
                and evidence.count_matching_studies(pairs, "Height", aliases) == 0
                and evidence.count_matching_studies(pairs, None, aliases) == 3)
    attempt("S1.gwas_count_matching", gwas_count_matching)

    # --- S1.build_* ------------------------------------------------------
    def build_trait_match():
        _, _, build_panel = _mods()
        targets = {"variants": [{"rsid": "rsX", "gene": "G", "condition": "Coronary artery disease",
                                 "assayability": "snp"}]}
        panel = build_panel.build(targets, sources=[], gwas={"rsX": [("s1", "Type 2 diabetes")]},
                                  aliases=aliases)
        return panel["variants"][0]["association"] == "unknown"
    attempt("S1.build_trait_match", build_trait_match)

    def build_legacy_int():
        _, _, build_panel = _mods()
        targets = {"variants": [{"rsid": "rsX", "gene": "G", "condition": "Coronary artery disease",
                                 "assayability": "snp"}]}
        panel = build_panel.build(targets, sources=[], gwas={"rsX": 2}, aliases=aliases)
        return panel["variants"][0]["association"] == "replicated"
    attempt("S1.build_legacy_int", build_legacy_int)

    # --- S1.aliases_cover_traits ----------------------------------------
    def aliases_cover_traits():
        evidence, _, _ = _mods()
        traits = _load(os.path.join(DATA, "targets.traits.json"))
        al = evidence.load_aliases()
        groups = {}
        for k, vals in al.items():
            if k.startswith("_"):
                continue
            groups[evidence.norm_cond(k)] = {evidence.norm_cond(m) for m in vals}
        for v in traits["variants"]:
            c = evidence.norm_cond(v.get("condition"))
            if not c or c not in groups:
                return False
            if "color" in c and not any("colour" in m for m in groups[c]):
                return False
        return True
    attempt("S1.aliases_cover_traits", aliases_cover_traits)

    # --- S1.panel_sample_reproduces -------------------------------------
    def panel_sample_reproduces():
        out = os.path.join(tempfile.mkdtemp(), "panel.check.json")
        cmd = [sys.executable, os.path.join(ROOT, "tools", "build_panel.py"),
               "--targets", os.path.join(DATA, "targets.sample.json"),
               "--clinvar", os.path.join(FIX, "sources", "clinvar.sample.tsv"),
               "--gnomad", os.path.join(FIX, "sources", "gnomad.sample.vcf"),
               "-o", out]
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if proc.returncode != 0:
            return False
        with open(out) as fh:
            got = fh.read()
        with open(os.path.join(DATA, "panel.sample.json")) as fh:
            want = fh.read()
        return got == want
    attempt("S1.panel_sample_reproduces", panel_sample_reproduces)

    # --- S1.no_network --------------------------------------------------
    def no_network():
        import importlib
        forbidden = re.compile(r"^\s*(?:import|from)\s+(urllib|http|socket|requests)\b", re.M)
        for name in ("evidence", "build_panel"):
            mod = importlib.import_module(name)
            with open(mod.__file__) as fh:
                if forbidden.search(fh.read()):
                    return False
        return True
    attempt("S1.no_network", no_network)

    # --- S1.select_matched_first (round 2) ------------------------------
    def sel_matched_first():
        evidence, _, _ = _mods()
        risk = {"sig": "risk factor", "review": "reviewed by expert panel",
                "phenotype": "Hereditary hemochromatosis", "tag": "risk"}
        path = {"sig": "Pathogenic", "review": "criteria provided, single submitter",
                "phenotype": "Cystic fibrosis", "tag": "path"}
        drug = {"sig": "drug response", "review": "reviewed by expert panel",
                "phenotype": "Hereditary hemochromatosis", "tag": "drug"}
        other = {"sig": "drug response", "review": "reviewed by expert panel",
                 "phenotype": "Unrelated", "tag": "other"}
        empty = {"sig": "", "review": "reviewed by expert panel",
                 "phenotype": "Hereditary hemochromatosis", "tag": "empty"}
        cond = "Hereditary hemochromatosis"
        if evidence.select_clinvar([risk, path], cond, aliases)["tag"] != "risk":
            return False
        if evidence.select_clinvar([path, risk], cond, aliases)["tag"] != "risk":
            return False
        if evidence.select_clinvar([drug, path], cond, aliases)["tag"] != "drug":
            return False
        if evidence.select_clinvar([path, drug], cond, aliases)["tag"] != "drug":
            return False
        if evidence.select_clinvar([other, path], cond, aliases)["tag"] != "path":
            return False
        if evidence.select_clinvar([drug, path], None, aliases)["tag"] != "path":
            return False
        if evidence.select_clinvar([empty, path], cond, aliases)["tag"] != "path":
            return False
        return True
    attempt("S1.select_matched_first", sel_matched_first)

    # --- S1.norm_cond_direct (round 2) ----------------------------------
    def norm_cond_direct():
        evidence, _, _ = _mods()
        return (evidence.norm_cond("  A-b!! c ") == "a b c"
                and evidence.norm_cond(None) == ""
                and evidence.norm_cond("a_b/c") == "a b c"
                and evidence.norm_cond("X9") == "x9")
    attempt("S1.norm_cond_direct", norm_cond_direct)

    # --- S1.bom_* (round 2) ---------------------------------------------
    def _bom_write(path, text):
        with open(path, "w", encoding="utf-8-sig") as fh:
            fh.write(text)

    def bom_gwas_tsv():
        _, _, build_panel = _mods()
        text = "SNPS\tPUBMEDID\tDISEASE/TRAIT\nrs1333049\t1\tCoronary artery disease\n"
        plain = os.path.join(tempfile.mkdtemp(), "g.tsv")
        bom = os.path.join(tempfile.mkdtemp(), "gb.tsv")
        with open(plain, "w") as fh:
            fh.write(text)
        _bom_write(bom, text)
        a = build_panel.load_gwas_studies(plain, {"rs1333049"})
        b = build_panel.load_gwas_studies(bom, {"rs1333049"})
        return a == b and b.get("rs1333049") == [("1", "Coronary artery disease")]
    attempt("S1.bom_gwas_tsv", bom_gwas_tsv)

    def bom_clinvar_tsv():
        _, _, build_panel = _mods()
        text = ("RS# (dbSNP)\tAssembly\tReviewStatus\tClinicalSignificance\tPhenotypeList\n"
                "1800562\tGRCh37\tcriteria provided, multiple submitters, no conflicts\t"
                "Pathogenic\tHereditary hemochromatosis\n")
        plain = os.path.join(tempfile.mkdtemp(), "c.tsv")
        bom = os.path.join(tempfile.mkdtemp(), "cb.tsv")
        with open(plain, "w") as fh:
            fh.write(text)
        _bom_write(bom, text)
        a = build_panel.load_clinvar(plain, "test")
        b = build_panel.load_clinvar(bom, "test")
        return a == b and b["rs1800562"]["review_stars"] == 2
    attempt("S1.bom_clinvar_tsv", bom_clinvar_tsv)

    def bom_dbsnp_tsv():
        _, _, build_panel = _mods()
        text = ("rsid\tchromosome\tposition\treference_allele\talternate_allele\n"
                "rs6025\t1\t169519049\tG\tA\n")
        plain = os.path.join(tempfile.mkdtemp(), "d.tsv")
        bom = os.path.join(tempfile.mkdtemp(), "db.tsv")
        with open(plain, "w") as fh:
            fh.write(text)
        _bom_write(bom, text)
        a = build_panel.load_dbsnp(plain, {"rs6025"})
        b = build_panel.load_dbsnp(bom, {"rs6025"})
        return a == b and b["rs6025"]["position"] == 169519049
    attempt("S1.bom_dbsnp_tsv", bom_dbsnp_tsv)

    def bom_gz():
        import gzip
        _, _, build_panel = _mods()
        text = ("rsid\tchromosome\tposition\treference_allele\talternate_allele\n"
                "rs6025\t1\t169519049\tG\tA\n")
        p = os.path.join(tempfile.mkdtemp(), "d.tsv.gz")
        with gzip.open(p, "wt", encoding="utf-8-sig") as fh:
            fh.write(text)
        got = build_panel.load_dbsnp(p, {"rs6025"})
        return got.get("rs6025", {}).get("position") == 169519049
    attempt("S1.bom_gz", bom_gz)

    # --- S1.tsv_sanitize_* (round 2) ------------------------------------
    def tsv_sanitize_clinvar():
        _, fetch_reference, build_panel = _mods()
        p = os.path.join(tempfile.mkdtemp(), "c.tsv")
        fetch_reference.write_clinvar_tsv(p, {
            "rs1800562": ("Pathogenic\tlikely", "reviewed\rmaybe", "cond\none"),
        })
        got = build_panel.load_clinvar(p, "test")
        rec = got.get("rs1800562")
        if not rec:
            return False
        with open(p) as fh:
            lines = fh.read().splitlines()
        return (len(lines) == 2 and len(lines[1].split("\t")) == 5
                and rec["significance"] == "Pathogenic likely"
                and rec["review_status_text"] == "reviewed maybe"
                and rec["phenotype"] == "cond one")
    attempt("S1.tsv_sanitize_clinvar", tsv_sanitize_clinvar)

    def tsv_sanitize_gwas():
        _, fetch_reference, build_panel = _mods()
        hostile_sid = "study\tid"
        hostile_trait = "trait\nvalue"

        def fake_ot(query, email=None):
            if "mapIds" in query:
                return {"data": {"mapIds": {"mappings": [
                    {"term": "rs1", "hits": [{"id": "1-100-A-G"}]}]}}}
            return {"data": {"a0": {"credibleSets": {"rows": [
                {"study": {"id": hostile_sid, "traitFromSource": hostile_trait}}]}}}}

        orig = fetch_reference._ot_query
        fetch_reference._ot_query = fake_ot
        try:
            cache = tempfile.mkdtemp()
            fetch_reference.fetch_gwas_ot([{"rsid": "rs1"}], None, cache)
            p = os.path.join(cache, "gwas.tsv")
            with open(p) as fh:
                lines = fh.read().splitlines()
            pairs = build_panel.load_gwas_studies(p, {"rs1"})
        finally:
            fetch_reference._ot_query = orig
        return (len(lines) == 2 and len(lines[1].split("\t")) == 3
                and pairs.get("rs1") == [("study id", "trait value")])
    attempt("S1.tsv_sanitize_gwas", tsv_sanitize_gwas)

    # --- S1.alias_* (round 2) -------------------------------------------
    def alias_file_wellformed():
        evidence, _, _ = _mods()
        al = evidence.load_aliases()
        for k, v in al.items():
            if k.startswith("_"):
                continue
            if not isinstance(v, list) or not all(isinstance(m, str) for m in v):
                return False
        return True
    attempt("S1.alias_file_wellformed", alias_file_wellformed)

    def alias_string_value_raises():
        evidence, _, _ = _mods()
        p = os.path.join(tempfile.mkdtemp(), "aliases.json")
        with open(p, "w") as fh:
            json.dump({"A": "eye"}, fh)
        try:
            evidence.load_aliases(p)
        except ValueError as exc:
            return "A" in str(exc)
        except Exception:  # noqa: BLE001
            return False
        return False
    attempt("S1.alias_string_value_raises", alias_string_value_raises)

    def alias_bare_string_as_list():
        evidence, _, _ = _mods()
        m = {"a": "eye"}
        return (not evidence.condition_matches("y", "a", m)
                and not evidence.condition_matches("y", "e", {"A": "eye"})
                and evidence.condition_matches("an eye test", "a", m)
                and evidence.condition_matches("e", "e", {"A": "eye"}))
    attempt("S1.alias_bare_string_as_list", alias_bare_string_as_list)

    def alias_member_and_key_lookup():
        evidence, _, _ = _mods()
        m = {"hereditary hemochromatosis": ["haemochromatosis"]}
        return evidence.condition_matches("Hereditary hemochromatosis", "haemochromatosis", m)
    attempt("S1.alias_member_and_key_lookup", alias_member_and_key_lookup)

    def alias_key_normalized():
        evidence, _, _ = _mods()
        m = {"Hereditary-Hemochromatosis": ["haemochromatosis"]}
        return evidence.condition_matches("haemochromatosis", "hereditary hemochromatosis", m)
    attempt("S1.alias_key_normalized", alias_key_normalized)

    def alias_members_normalized():
        evidence, _, _ = _mods()
        m = {"cond": ["Haemo-Chromatosis!"]}
        return evidence.condition_matches("haemo chromatosis", "cond", m)
    attempt("S1.alias_members_normalized", alias_members_normalized)

    def alias_underscore_key_skipped():
        evidence, _, _ = _mods()
        m = {"_comment": ["zzz"]}
        return not evidence.condition_matches("zzz", "comment", m)
    attempt("S1.alias_underscore_key_skipped", alias_underscore_key_skipped)

    def alias_non_string_entries_ignored():
        evidence, _, _ = _mods()
        m = {"c1": [123, None, "alias"]}
        return (evidence.condition_matches("an alias here", "c1", m)
                and not evidence.condition_matches("123", "c1", m))
    attempt("S1.alias_non_string_entries_ignored", alias_non_string_entries_ignored)

    def count_ignores_missing_study_id():
        evidence, _, _ = _mods()
        pairs = [("", "Coronary artery disease"),
                 (None, "Coronary artery disease"),
                 ("S1", "Coronary artery disease")]
        return evidence.count_matching_studies(pairs, "coronary artery disease", {}) == 1
    attempt("S1.count_ignores_missing_study_id", count_ignores_missing_study_id)

    def gwas_studies_dedupe():
        _, _, build_panel = _mods()
        p = os.path.join(tempfile.mkdtemp(), "gwas.tsv")
        with open(p, "w") as fh:
            fh.write("SNPS\tPUBMEDID\tDISEASE/TRAIT\n")
            fh.write("rs1\t100\tTrait A\n")
            fh.write("rs1\t100\tTrait A\n")
            fh.write("rs1\t100\tTrait B\n")
            fh.write("rs1\t101\tTrait A\n")
        pairs = build_panel.load_gwas_studies(p, {"rs1"})
        return pairs.get("rs1") == [("100", "Trait A"), ("100", "Trait B"), ("101", "Trait A")]
    attempt("S1.gwas_studies_dedupe", gwas_studies_dedupe)


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
