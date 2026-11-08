#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Stage 2 call-interpretation gates (R2A.*): allele membership, build
provenance, locus identity and duplicate rows.

Run standalone:  python tests/test_interpretation.py
Or as part of:   python tests/test_pipeline.py

Every gate is isolated: a missing function or any exception fails only that one
check (via attempt()), never the whole run. All inputs are synthetic and written
to temporary directories; no real data is read. Assertions that need the
optional jsonschema package are skipped visibly (a SKIP line on stdout) when it
is absent, never silently.
"""
import contextlib
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "stage2"))

FIX = os.path.join(ROOT, "fixtures")
SCHEMA_PATH = os.path.join(ROOT, "schema", "findings.schema.json")

ZYGOSITIES = ("hom_ref", "het", "hom_alt", "unknown")


def _load(path):
    with open(path) as fh:
        return json.load(fh)


def _jsonschema():
    """The optional jsonschema module, or None when it is not installed."""
    try:
        import jsonschema
    except ImportError:
        return None
    return jsonschema


def _skip(name, why):
    print(f"  SKIP {name}: {why}")


def _write_raw(directory, rows, build="37.1", name="raw.txt"):
    """Write a synthetic five-column file; build=None omits the build statement."""
    lines = ["#synthetic raw data for tests",
             "#Data was collected using AncestryDNA array version: V2.0"]
    if build is not None:
        lines.append(f"#using human reference build {build} coordinates.")
    lines.append("rsid\tchromosome\tposition\tallele1\tallele2")
    lines.extend("\t".join(str(c) for c in row) for row in rows)
    path = os.path.join(directory, name)
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def _variant(rsid, chrom, pos, ref, alt, effect=None, assay="snp", strand=None):
    v = {"rsid": rsid, "chromosome": chrom, "position": pos, "gene": "GENE1",
         "condition": "Condition A", "assayability": assay,
         "reference_allele": ref, "alternate_allele": alt, "cls": "risk",
         "association": "established", "gnomad_af": None, "clinvar": None, "snpedia": None}
    if effect:
        v["effect_allele"] = effect
    if strand:
        v["strand"] = strand
    return v


def _panel(*variants, **extra):
    panel = {"merges": {}, "sources": [], "variants": list(variants)}
    panel.update(extra)
    return panel


def _findings(rows, panel, build="37.1"):
    """Annotate synthetic rows against a panel; returns the findings document."""
    import annotate
    with tempfile.TemporaryDirectory() as d:
        return annotate.build_findings(_write_raw(d, rows, build=build), panel, {})


def _finding(rows, variant, build="37.1"):
    return _findings(rows, _panel(variant), build=build)["findings"][0]


def _sig(f):
    call = f["call"]
    return (f["state"], call.get("state"), call.get("zygosity"),
            f["confidence"]["annotation_mapping"]["level"])


def _caveat_texts(f):
    return list(f["caveats"])


def _run_main(argv):
    """Run annotate.main capturing (rc, stdout, stderr)."""
    import annotate
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = annotate.main(argv)
    return rc, out.getvalue(), err.getvalue()


# Effect-allele entry (A is the risk allele, dbSNP ref/alt G/A) and a plain
# ref/alt entry, used by most gates.
def _effect_variant(**kw):
    return _variant("rs900001", "1", 1000, "G", "A", effect="A", **kw)


def _refalt_variant(**kw):
    return _variant("rs900002", "1", 2000, "G", "A", **kw)


def _run_characterization(attempt):
    from caveats import CAVEAT_REGISTRY

    # --- R2A.char_nocall_half_nocall (R32-F1): either allele '0' is a no-call --
    def char_nocall_half_nocall():
        cases = [
            ([("rs900001", 1, 1000, "0", "A")], _effect_variant()),
            ([("rs900001", 1, 1000, "A", "0")], _effect_variant()),
            ([("rs900002", 1, 2000, "0", "A")], _refalt_variant()),
            ([("rs900002", 1, 2000, "G", "0")], _refalt_variant()),
            ([("rs900003", 7, 3000, "0", "D")], _variant("rs900003", "7", 3000, None, None,
                                                         effect="D", assay="indel")),
        ]
        for rows, variant in cases:
            f = _finding(rows, variant)
            if f["state"] != "covered_nocall" or f["coverage"]["state"] != "covered":
                return False
            if f["call"]["state"] != "no_call" or f["call"]["zygosity"] != "unknown":
                return False
            if CAVEAT_REGISTRY["no_call"] not in _caveat_texts(f):
                return False
        return True
    attempt("R2A.char_nocall_half_nocall", char_nocall_half_nocall)

    # --- R2A.char_not_covered ------------------------------------------------
    def char_not_covered():
        f = _finding([("rs999999", 1, 5000, "A", "A")], _effect_variant())
        return (f["state"] == "not_covered" and f["coverage"]["state"] == "not_covered"
                and f["call"] == {"state": "not_applicable"}
                and CAVEAT_REGISTRY["not_covered"] in _caveat_texts(f))
    attempt("R2A.char_not_covered", char_not_covered)

    # --- R2A.char_not_assayable ----------------------------------------------
    def char_not_assayable():
        v = _variant(None, "4", 4000, None, None, assay="not_assayable")
        f = _finding([("rs999999", 1, 5000, "A", "A")], v)
        return (f["state"] == "not_assayable" and f["call"] == {"state": "not_applicable"}
                and CAVEAT_REGISTRY["not_assayable"] in _caveat_texts(f))
    attempt("R2A.char_not_assayable", char_not_assayable)

    # --- R2A.char_position_mismatch_medium (P13) ------------------------------
    def char_position_mismatch_medium():
        f = _finding([("rs900001", 1, 1500, "A", "A")], _effect_variant())
        basis = f["confidence"]["annotation_mapping"]["basis"]
        return (f["state"] == "detected" and f["call"]["zygosity"] == "hom_alt"
                and f["confidence"]["annotation_mapping"]["level"] == "medium"
                and "position differs from snapshot" in basis)
    attempt("R2A.char_position_mismatch_medium", char_position_mismatch_medium)

    # --- R2A.char_merge_map_applied -------------------------------------------
    def char_merge_map_applied():
        panel = _panel(_variant("rs900110", "1", 1000, "G", "A", effect="A"),
                       merges={"rs900110": "rs900001"})
        f = _findings([("rs900001", 1, 1000, "A", "G")], panel)["findings"][0]
        basis = f["confidence"]["annotation_mapping"]["basis"]
        return (f["state"] == "detected" and f["call"]["zygosity"] == "het"
                and any("dbSNP merge map applied (rs900110->rs900001)" in b for b in basis))
    attempt("R2A.char_merge_map_applied", char_merge_map_applied)

    # --- R2A.char_sex_inference_male_female_unknown ---------------------------
    def char_sex_inference_male_female_unknown():
        import annotate
        import ancestry
        with tempfile.TemporaryDirectory() as d:
            male = _write_raw(d, [("rsM1", 24, 3000000, "T", "T")], name="male.txt")
            female_rows = [(f"rsF{i}", 23, 1000000 + i * 1000, *(("A", "G") if i < 3 else ("A", "A")))
                           for i in range(20)]
            female = _write_raw(d, female_rows, name="female.txt")
            unknown = _write_raw(d, [("rsU1", 1, 1000, "A", "A")], name="unknown.txt")
            got = [annotate.infer_sex(ancestry.parse_ancestry(p)) for p in (male, female, unknown)]
        return got == ["male", "female", "unknown"]
    attempt("R2A.char_sex_inference_male_female_unknown", char_sex_inference_male_female_unknown)

    # --- R2A.char_x_male_hemizygous -------------------------------------------
    def char_x_male_hemizygous():
        panel = _panel(_variant("rsX1", "X", 1000000, "G", "A", effect="A"))
        doc = _findings([("rsX1", 23, 1000000, "A", "A"), ("rsM1", 24, 3000000, "T", "T")], panel)
        f = doc["findings"][0]
        return (doc["provenance"]["inferred_sex"] == "male" and f["state"] == "detected"
                and f["call"]["zygosity"] == "hemizygous")
    attempt("R2A.char_x_male_hemizygous", char_x_male_hemizygous)

    # --- R2A.char_y_in_female_uninterpretable ---------------------------------
    def char_y_in_female_uninterpretable():
        import annotate
        import ancestry
        v = _variant("rsY1", "Y", 3000000, "T", "C")
        with tempfile.TemporaryDirectory() as d:
            raw = ancestry.parse_ancestry(_write_raw(d, [("rsY1", 24, 3000000, "T", "T")]))
        f = annotate.annotate_variant(v, raw, {}, "female")
        return (f["state"] == "covered_uninterpretable" and f["call"]["state"] == "uninterpretable"
                and f["call"]["zygosity"] == "unknown")
    attempt("R2A.char_y_in_female_uninterpretable", char_y_in_female_uninterpretable)

    # --- R2A.char_refalt_path_unchanged (P6/P7) --------------------------------
    def char_refalt_path_unchanged():
        want = {
            ("G", "G"): ("covered_reference", "called", "hom_ref"),
            ("A", "G"): ("detected", "called", "het"),
            ("A", "A"): ("detected", "called", "hom_alt"),
            ("C", "C"): ("covered_uninterpretable", "uninterpretable", "unknown"),
        }
        for (a1, a2), expected in want.items():
            f = _finding([("rs900002", 1, 2000, a1, a2)], _refalt_variant())
            if (f["state"], f["call"]["state"], f["call"]["zygosity"]) != expected:
                return False
        # unknown reference/alternate on the ref/alt path stays uninterpretable
        f = _finding([("rs900002", 1, 2000, "G", "A")], _variant("rs900002", "1", 2000, None, None))
        return f["state"] == "covered_uninterpretable"
    attempt("R2A.char_refalt_path_unchanged", char_refalt_path_unchanged)

    # --- R2A.char_palindromic_flag_caveat -------------------------------------
    def char_palindromic_flag_caveat():
        f = _finding([("rs900002", 1, 2000, "G", "A")], _refalt_variant(strand="ambiguous"))
        basis = f["confidence"]["annotation_mapping"]["basis"]
        return (f["call"]["strand"] == "ambiguous"
                and CAVEAT_REGISTRY["strand_ambiguous"] in _caveat_texts(f)
                and "curator-flagged strand-ambiguous site" in basis)
    attempt("R2A.char_palindromic_flag_caveat", char_palindromic_flag_caveat)

    # --- R2A.char_panel_without_build_field -----------------------------------
    def char_panel_without_build_field():
        panel = _panel(_effect_variant())
        if "genome_build" in panel:
            return False
        for build in ("37.1", None):
            doc = _findings([("rs900001", 1, 1000, "A", "G")], panel, build=build)
            if doc["provenance"]["genome_build"] != "GRCh37":
                return False
            if doc["findings"][0]["state"] != "detected":
                return False
        return True
    attempt("R2A.char_panel_without_build_field", char_panel_without_build_field)

    # --- R2A.char_adjust_zygosity_table ----------------------------------------
    # Written out literally (never by calling adjust_zygosity); pins the
    # hemizygous/homoplasmic handling for X, Y and MT exactly as it is.
    def char_adjust_zygosity_table():
        import annotate
        ident = {z: z for z in ZYGOSITIES}

        def const(value):
            return {z: value for z in ZYGOSITIES}

        table = {
            ("1", "male"): ident, ("1", "female"): ident, ("1", "unknown"): ident,
            ("X", "male"): const("hemizygous"), ("X", "female"): ident, ("X", "unknown"): ident,
            ("Y", "male"): const("hemizygous"), ("Y", "female"): const("unknown"),
            ("Y", "unknown"): const("unknown"),
            ("MT", "male"): const("homoplasmic"), ("MT", "female"): const("homoplasmic"),
            ("MT", "unknown"): const("homoplasmic"),
        }
        for (chrom, sex), row in table.items():
            for zyg in ZYGOSITIES:
                if annotate.adjust_zygosity(zyg, chrom, sex) != row[zyg]:
                    return False
        return len(table) * len(ZYGOSITIES) == 48
    attempt("R2A.char_adjust_zygosity_table", char_adjust_zygosity_table)

    # --- R2A.char_legacy_fixture_validates (schema runs) -----------------------
    def char_legacy_fixture_validates():
        jsonschema = _jsonschema()
        doc = _load(os.path.join(FIX, "findings.sample.json"))
        jsonschema.Draft202012Validator(_load(SCHEMA_PATH)).validate(doc)
        return doc["schema_version"] == "1.0.0"
    if _jsonschema() is None:
        _skip("R2A.char_legacy_fixture_validates", "jsonschema not installed")
    else:
        attempt("R2A.char_legacy_fixture_validates", char_legacy_fixture_validates)

    # --- A2: positive effect-allele behavior that must keep working -----------
    # (a lazy implementation that returns uninterpretable for every call fails
    # these three; they pass on the base and stay in the characterization commit)
    def effect_ref_ref_still_reference():
        f = _finding([("rs900001", 1, 1000, "G", "G")], _effect_variant())
        if _sig(f)[:3] != ("covered_reference", "called", "hom_ref"):
            return False
        # an indel entry has a closed I/D alphabet: I/I is reference when D is the effect
        ind = _variant("rs900003", "7", 3000, None, None, effect="D", assay="indel")
        g = _finding([("rs900003", 7, 3000, "I", "I")], ind)
        return _sig(g)[:3] == ("covered_reference", "called", "hom_ref")
    attempt("R2A.effect_ref_ref_still_reference", effect_ref_ref_still_reference)

    def effect_het_still_detected():
        for a1, a2 in (("A", "G"), ("G", "A")):
            f = _finding([("rs900001", 1, 1000, a1, a2)], _effect_variant())
            if _sig(f)[:3] != ("detected", "called", "het"):
                return False
        ind = _variant("rs900003", "7", 3000, None, None, effect="D", assay="indel")
        return _sig(_finding([("rs900003", 7, 3000, "I", "D")], ind))[:3] == ("detected", "called", "het")
    attempt("R2A.effect_het_still_detected", effect_het_still_detected)

    def effect_hom_still_detected():
        f = _finding([("rs900001", 1, 1000, "A", "A")], _effect_variant())
        if _sig(f)[:3] != ("detected", "called", "hom_alt"):
            return False
        ind = _variant("rs900003", "7", 3000, None, None, effect="D", assay="indel")
        return _sig(_finding([("rs900003", 7, 3000, "D", "D")], ind))[:3] == ("detected", "called", "hom_alt")
    attempt("R2A.effect_hom_still_detected", effect_hom_still_detected)

    # --- R2A.build_absent_still_annotates (Q5: proceed) ------------------------
    # Classified CHARACTERIZATION: the file-without-a-build-statement run already
    # exits 0 with the same states as the stated-build run on the base.
    def build_absent_still_annotates():
        rows = [("rs900001", 1, 1000, "A", "G"), ("rs900002", 1, 2000, "G", "G")]
        panel = _panel(_effect_variant(), _refalt_variant())
        states = {}
        with tempfile.TemporaryDirectory() as d:
            pp = os.path.join(d, "panel.json")
            with open(pp, "w") as fh:
                json.dump(panel, fh)
            for label, build in (("stated", "37.1"), ("absent", None)):
                raw = _write_raw(d, rows, build=build, name=f"{label}.txt")
                out = os.path.join(d, f"{label}.json")
                rc, _o, _e = _run_main([raw, pp, "-o", out, "--aliases", os.path.join(d, "none.json")])
                if rc != 0 or not os.path.exists(out):
                    return False
                states[label] = [(f["state"], f["call"].get("zygosity")) for f in _load(out)["findings"]]
        return states["stated"] == states["absent"] == [("detected", "het"), ("covered_reference", "hom_ref")]
    attempt("R2A.build_absent_still_annotates", build_absent_still_annotates)


def run(check):
    def attempt(name, fn):
        try:
            result = fn()
        except Exception:  # noqa: BLE001
            check(name, False)
            return
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
