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
sys.path.insert(0, ROOT)
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


class _Gate(AssertionError):
    pass


def _require(label, cond):
    """Fail the current gate at the first unmet condition, naming it."""
    if not cond:
        raise _Gate(label)


BUILD_REFUSED_MESSAGE = ("error: genome build refused: only GRCh37 is supported and the raw "
                         "file's stated build must match the panel build; no output was written")


def _write_panel(directory, panel, name="panel.json"):
    path = os.path.join(directory, name)
    with open(path, "w") as fh:
        json.dump(panel, fh)
    return path


def _sha256(path):
    import hashlib
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


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


def _uninterpretable(f):
    return (f["state"] == "covered_uninterpretable" and f["call"]["state"] == "uninterpretable"
            and f["call"]["zygosity"] == "unknown")


def _run_interpretation(attempt):
    from caveats import CAVEAT_REGISTRY, STATE_CAVEAT

    ind_d = _variant("rs900003", "7", 3000, None, None, effect="D", assay="indel")

    # --- R2A.effect_neither_allele_is_uninterpretable (P1) ---------------------
    def effect_neither_allele_is_uninterpretable():
        for a1, a2 in (("C", "C"), ("C", "T"), ("T", "T")):
            f = _finding([("rs900001", 1, 1000, a1, a2)], _effect_variant())
            _require(f"{a1}/{a2} on effect A (ref G alt A) is uninterpretable, got {_sig(f)}", _uninterpretable(f))
        # a stray third letter next to the effect allele is not detected either
        f = _finding([("rs900001", 1, 1000, "A", "C")], _effect_variant())
        _require(f"A/C is uninterpretable, got {_sig(f)}", _uninterpretable(f))
        return True
    attempt("R2A.effect_neither_allele_is_uninterpretable", effect_neither_allele_is_uninterpretable)

    # --- R2A.effect_junk_letter_is_uninterpretable (P2) ------------------------
    def effect_junk_letter_is_uninterpretable():
        for a1, a2 in (("X", "X"), ("A", "X"), ("-", "-"), ("a", "a")):
            f = _finding([("rs900001", 1, 1000, a1, a2)], _effect_variant())
            _require(f"{a1}/{a2} is uninterpretable, got {_sig(f)}", _uninterpretable(f))
        return True
    attempt("R2A.effect_junk_letter_is_uninterpretable", effect_junk_letter_is_uninterpretable)

    # --- R2A.effect_indel_letters_on_snp_uninterpretable (P3) ------------------
    def effect_indel_letters_on_snp_uninterpretable():
        for a1, a2 in (("I", "D"), ("I", "I"), ("D", "D")):
            f = _finding([("rs900001", 1, 1000, a1, a2)], _effect_variant())
            _require(f"{a1}/{a2} on a SNP is uninterpretable, got {_sig(f)}", _uninterpretable(f))
        return True
    attempt("R2A.effect_indel_letters_on_snp_uninterpretable", effect_indel_letters_on_snp_uninterpretable)

    # --- R2A.effect_snp_letters_on_indel_uninterpretable (P10) -----------------
    def effect_snp_letters_on_indel_uninterpretable():
        for a1, a2 in (("A", "A"), ("A", "C"), ("D", "A")):
            f = _finding([("rs900003", 7, 3000, a1, a2)], ind_d)
            _require(f"{a1}/{a2} on an indel is uninterpretable, got {_sig(f)}", _uninterpretable(f))
        return True
    attempt("R2A.effect_snp_letters_on_indel_uninterpretable", effect_snp_letters_on_indel_uninterpretable)

    # --- R2A.effect_unknown_nonset_cannot_assert_reference ---------------------
    def effect_unknown_nonset_cannot_assert_reference():
        # effect A with no known reference/alternate: the non-effect set is unknown
        nothing = _variant("rs900001", "1", 1000, None, None, effect="A")
        for a1, a2 in (("C", "C"), ("G", "G"), ("C", "G")):
            f = _finding([("rs900001", 1, 1000, a1, a2)], nothing)
            _require(f"{a1}/{a2} with unknown non-effect set is uninterpretable, got {_sig(f)}",
                     _uninterpretable(f))
        # the effect allele itself is still detected without a declared non-effect set
        f = _finding([("rs900001", 1, 1000, "A", "G")], nothing)
        _require(f"A/G is still detected, got {_sig(f)}", f["state"] == "detected")
        # only the effect allele declared (ref == effect, alt unknown): still no reference claim
        only_ref = _variant("rs900001", "1", 1000, "A", None, effect="A")
        f = _finding([("rs900001", 1, 1000, "C", "C")], only_ref)
        _require(f"C/C with only the effect declared is uninterpretable, got {_sig(f)}", _uninterpretable(f))
        return True
    attempt("R2A.effect_unknown_nonset_cannot_assert_reference", effect_unknown_nonset_cannot_assert_reference)

    # --- R2A.uninterpretable_caveat_present_and_validates ----------------------
    def uninterpretable_caveat_present_and_validates():
        panel = _panel(_effect_variant())
        doc = _findings([("rs900001", 1, 1000, "C", "C")], panel)
        f = doc["findings"][0]
        _require(f"state is covered_uninterpretable, got {f['state']}", f["state"] == "covered_uninterpretable")
        _require("the uninterpretable caveat text is on the finding",
                 CAVEAT_REGISTRY[STATE_CAVEAT["covered_uninterpretable"]] in f["caveats"])
        jsonschema = _jsonschema()
        if jsonschema is not None:
            jsonschema.Draft202012Validator(_load(SCHEMA_PATH)).validate(doc)
        return True
    attempt("R2A.uninterpretable_caveat_present_and_validates", uninterpretable_caveat_present_and_validates)

    # --- R2A.chromosome_mismatch_not_high ---------------------------------------
    def chromosome_mismatch_not_high():
        # the same rsID on another chromosome is not the panel locus
        f = _finding([("rs900001", 2, 1000, "A", "A")], _effect_variant())
        _require(f"rsID on another chromosome is not covered, got {_sig(f)}", f["state"] == "not_covered")
        _require("no call is made", f["call"] == {"state": "not_applicable"})
        # position fallback still applies, at medium confidence
        rows = [("rs900001", 2, 1000, "A", "A"), ("rs900777", 1, 1000, "G", "G")]
        g = _finding(rows, _effect_variant())
        level = g["confidence"]["annotation_mapping"]["level"]
        _require(f"the position fallback maps at medium, got {level}", level == "medium")
        _require("the basis says the match is by position",
                 g["confidence"]["annotation_mapping"]["basis"][-1].startswith("matched by position"))
        return True
    attempt("R2A.chromosome_mismatch_not_high", chromosome_mismatch_not_high)

    # --- R2A.duplicate_rsid_conflict_uninterpretable -----------------------------
    def duplicate_rsid_conflict_uninterpretable():
        for variant, rsid, pos, first, second in (
                (_effect_variant(), "rs900001", 1000, ("A", "A"), ("G", "G")),
                (_refalt_variant(), "rs900002", 2000, ("G", "G"), ("A", "A"))):
            rows = [(rsid, 1, pos, *first), (rsid, 1, pos, *second)]
            f = _finding(rows, variant)
            _require(f"conflicting duplicate rows are uninterpretable, got {_sig(f)}", _uninterpretable(f))
            _require("the uninterpretable caveat is present", CAVEAT_REGISTRY["uninterpretable"] in f["caveats"])
            _require("the basis names the conflict",
                     any("conflicting duplicate" in b for b in f["confidence"]["annotation_mapping"]["basis"]))
            # a different position on the repeated row is also a conflict
            moved = [(rsid, 1, pos, *first), (rsid, 1, pos + 5, *first)]
            g = _finding(moved, variant)
            _require(f"duplicate rows at different positions conflict, got {_sig(g)}", _uninterpretable(g))
        # identical and reordered duplicates agree, so they are not a conflict
        same = _finding([("rs900001", 1, 1000, "A", "G"), ("rs900001", 1, 1000, "G", "A")], _effect_variant())
        _require(f"reordered duplicate alleles still agree, got {_sig(same)}", _sig(same)[:3] == ("detected", "called", "het"))
        twice = _finding([("rs900001", 1, 1000, "A", "A")] * 2, _effect_variant())
        _require(f"identical duplicate rows still agree, got {_sig(twice)}", _sig(twice)[:3] == ("detected", "called", "hom_alt"))
        return True
    attempt("R2A.duplicate_rsid_conflict_uninterpretable", duplicate_rsid_conflict_uninterpretable)


def _build_doc(rows, panel, build):
    return _findings(rows, panel, build=build)


def _run_build(attempt):
    rows = [("rs900001", 1, 1000, "A", "G"), ("rs900002", 1, 2000, "G", "G")]
    panel = _panel(_effect_variant(), _refalt_variant())
    old_literal = "build GRCh37 match"
    stated_text = "file build GRCh37 matches panel build GRCh37"
    absent_text = "build not stated in file; assumed to match panel build GRCh37"

    def rsid_basis(doc):
        return [f["confidence"]["annotation_mapping"]["basis"] for f in doc["findings"]
                if f["rsid"] and f["confidence"]["annotation_mapping"]["basis"][0] != "matched by position; rsID absent from file"]

    def refusal(raw_rows, build, the_panel, extra_check=None):
        """Run annotate.main on a refused input; returns (rc, stdout, stderr, out_path, dir_listing)."""
        with tempfile.TemporaryDirectory() as d:
            raw = _write_raw(d, raw_rows, build=build)
            pp = _write_panel(d, the_panel)
            out = os.path.join(d, "findings.json")
            rc, so, se = _run_main([raw, pp, "-o", out, "--aliases", os.path.join(d, "none.json")])
            return rc, so, se, os.path.exists(out)

    # --- R2A.build_mismatch_refused_exit_nonzero --------------------------------
    def build_mismatch_refused_exit_nonzero():
        import annotate
        rc, so, se, wrote = refusal(rows, "38", panel)
        _require(f"annotate.main returns 2, got {rc}", rc == 2)
        _require(f"stderr equals the fixed message exactly, got {se!r}", se == BUILD_REFUSED_MESSAGE + "\n")
        err = None
        with tempfile.TemporaryDirectory() as d:
            try:
                annotate.build_findings(_write_raw(d, rows, build="38"), panel, {})
            except Exception as exc:  # noqa: BLE001
                err = exc
        _require("build_findings raises", err is not None)
        _require(f"it raises the dedicated refusal exception, got {type(err).__name__}",
                 type(err).__name__ == "BuildRefused")
        return True
    attempt("R2A.build_mismatch_refused_exit_nonzero", build_mismatch_refused_exit_nonzero)

    # --- R2A.build_mismatch_writes_no_output ------------------------------------
    def build_mismatch_writes_no_output():
        with tempfile.TemporaryDirectory() as d:
            raw = _write_raw(d, rows, build="38")
            pp = _write_panel(d, panel)
            none = os.path.join(d, "none.json")
            absent_out = os.path.join(d, "absent.json")
            rc, _so, _se = _run_main([raw, pp, "-o", absent_out, "--aliases", none])
            _require(f"a refusal exits non-zero, got {rc}", rc != 0)
            _require("-o PATH stays absent", not os.path.exists(absent_out))
            kept = os.path.join(d, "kept.json")
            with open(kept, "w") as fh:
                fh.write('{"pre": "existing"}\n')
            before = _sha256(kept)
            rc, _so, _se = _run_main([raw, pp, "-o", kept, "--aliases", none])
            _require(f"a refusal onto an existing PATH exits non-zero, got {rc}", rc != 0)
            _require("a pre-existing PATH is byte-identical (sha256 before == after)", _sha256(kept) == before)
            rc, so, _se = _run_main([raw, pp, "--aliases", none])
            _require(f"a refusal without -o exits non-zero, got {rc}", rc != 0)
            _require(f"stdout is empty without -o, got {len(so)} bytes", so == "")
        return True
    attempt("R2A.build_mismatch_writes_no_output", build_mismatch_writes_no_output)

    # --- R2A.build_mismatch_run_writes_no_files ---------------------------------
    def build_mismatch_run_writes_no_files():
        from snp_insights import cli
        with tempfile.TemporaryDirectory() as d:
            raw = _write_raw(d, rows, build="38")
            pp = _write_panel(d, panel)
            out_dir = os.path.join(d, "run-out")
            err, out = io.StringIO(), io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                rc = cli.main(["run", raw, pp, "--out-dir", out_dir, "--template-only"])
            _require(f"run returns non-zero, got {rc}", rc != 0)
            present = [n for n in cli._OUTPUT_NAMES if os.path.lexists(os.path.join(out_dir, n))]
            _require(f"none of the run's output names exists, found {present}", not present)
        return True
    attempt("R2A.build_mismatch_run_writes_no_files", build_mismatch_run_writes_no_files)

    # --- R2A.panel_build_not_grch37_refused --------------------------------------
    def panel_build_not_grch37_refused():
        bad = _panel(_effect_variant(), _refalt_variant(), genome_build="GRCh38")
        for label, build in (("stated 37.1", "37.1"), ("not stated", None), ("stated 38", "38")):
            rc, so, se, wrote = refusal(rows, build, bad)
            _require(f"panel GRCh38 with raw {label} exits 2, got {rc}", rc == 2)
            _require(f"panel GRCh38 with raw {label} prints the fixed message, got {se!r}",
                     se == BUILD_REFUSED_MESSAGE + "\n")
            _require(f"panel GRCh38 with raw {label} writes nothing", not wrote and so == "")
        return True
    attempt("R2A.panel_build_not_grch37_refused", panel_build_not_grch37_refused)

    # --- R2A.build_match_records_state -------------------------------------------
    def build_match_records_state():
        for build in ("37.1", "37"):
            doc = _build_doc(rows, panel, build)
            prov = doc["provenance"]
            _require(f"build {build}: genome_build is the panel build", prov["genome_build"] == "GRCh37")
            _require(f"build {build}: input_build is GRCh37, got {prov.get('input_build')!r}",
                     prov.get("input_build") == "GRCh37")
            _require(f"build {build}: build_basis is file_statement, got {prov.get('build_basis')!r}",
                     prov.get("build_basis") == "file_statement")
            bases = rsid_basis(doc)
            _require("every finding is rsID-located", len(bases) == len(doc["findings"]))
            for basis in bases:
                _require(f"build {build}: basis states the stated match, got {basis}", stated_text in basis)
                _require(f"build {build}: the old literal is gone, got {basis}", old_literal not in basis)
        return True
    attempt("R2A.build_match_records_state", build_match_records_state)

    # --- R2A.build_absent_provenance_unknown --------------------------------------
    def build_absent_provenance_unknown():
        doc = _build_doc(rows, panel, None)
        prov = doc["provenance"]
        _require(f"input_build is unknown, got {prov.get('input_build')!r}", prov.get("input_build") == "unknown")
        _require(f"build_basis is not_stated, got {prov.get('build_basis')!r}", prov.get("build_basis") == "not_stated")
        _require("genome_build stays the panel build", prov["genome_build"] == "GRCh37")

        def observed_grch37(node):
            if isinstance(node, dict):
                return any((k == "input_build" and v == "GRCh37") or observed_grch37(v) for k, v in node.items())
            if isinstance(node, list):
                return any(observed_grch37(v) for v in node)
            return False
        _require("input_build is not GRCh37 anywhere in the document", not observed_grch37(doc))
        return True
    attempt("R2A.build_absent_provenance_unknown", build_absent_provenance_unknown)

    # --- R2A.build_absent_basis_states_assumption ----------------------------------
    def build_absent_basis_states_assumption():
        doc = _build_doc(rows, panel, None)
        bases = rsid_basis(doc)
        _require("every finding is rsID-located", len(bases) == len(doc["findings"]))
        for basis in bases:
            _require(f"basis states the assumption, got {basis}", absent_text in basis)
            _require(f"no basis claims the file build matched, got {basis}",
                     old_literal not in basis and stated_text not in basis)
        return True
    attempt("R2A.build_absent_basis_states_assumption", build_absent_basis_states_assumption)

    # --- R2A.findings_schema_valid -------------------------------------------------
    def findings_schema_valid():
        jsonschema = _jsonschema()
        validator = jsonschema.Draft202012Validator(_load(SCHEMA_PATH)) if jsonschema else None
        for label, build, want_input, want_basis in (("stated", "37.1", "GRCh37", "file_statement"),
                                                      ("absent", None, "unknown", "not_stated")):
            doc = _build_doc(rows, panel, build)
            prov = doc["provenance"]
            _require(f"{label}: schema_version is 1.1.0, got {doc['schema_version']!r}", doc["schema_version"] == "1.1.0")
            _require(f"{label}: input_build is {want_input}, got {prov.get('input_build')!r}",
                     prov.get("input_build") == want_input)
            _require(f"{label}: build_basis is {want_basis}, got {prov.get('build_basis')!r}",
                     prov.get("build_basis") == want_basis)
            _require(f"{label}: genome_build is GRCh37", prov["genome_build"] == "GRCh37")
            if validator is not None:
                validator.validate(doc)
        return True
    attempt("R2A.findings_schema_valid", findings_schema_valid)

    # --- R2A.schema_file_declares_build_fields (runs without jsonschema) -------------
    def schema_file_declares_build_fields():
        schema = _load(SCHEMA_PATH)
        props = schema["$defs"]["provenance"]["properties"]
        _require("provenance declares input_build and build_basis", "input_build" in props and "build_basis" in props)
        _require("the version enum is exactly 1.0.0 and 1.1.0",
                 schema["properties"]["schema_version"] == {"enum": ["1.0.0", "1.1.0"]})
        conds = [c for c in schema.get("allOf", []) if "1.1.0" in json.dumps(c.get("if", {}))]
        _require("one conditional keys on 1.1.0", len(conds) == 1)
        then = json.dumps(conds[0].get("then", {}))
        _require("the 1.1.0 branch requires input_build and build_basis",
                 "input_build" in then and "build_basis" in then)
        return True
    attempt("R2A.schema_file_declares_build_fields", schema_file_declares_build_fields)

    # --- R2A.schema_enforces_build_fields (schema runs only) ---------------------------
    def schema_enforces_build_fields():
        jsonschema = _jsonschema()
        validator = jsonschema.Draft202012Validator(_load(SCHEMA_PATH))

        def rejected(doc):
            return bool(list(validator.iter_errors(doc)))

        import copy
        good = _build_doc(rows, panel, "37.1")
        _require(f"the generated document is 1.1.0, got {good['schema_version']!r}", good["schema_version"] == "1.1.0")
        _require("the generated document carries input_build and build_basis",
                 "input_build" in good["provenance"] and "build_basis" in good["provenance"])
        _require("positive control: a valid 1.1.0 document validates", not rejected(good))
        for field in ("input_build", "build_basis"):
            doc = copy.deepcopy(good)
            del doc["provenance"][field]
            _require(f"a 1.1.0 document without {field} is rejected", rejected(doc))
        for field, bad in (("input_build", "GRCh38"), ("input_build", ""), ("build_basis", "guessed"),
                           ("build_basis", "")):
            doc = copy.deepcopy(good)
            doc["provenance"][field] = bad
            _require(f"{field} = {bad!r} is rejected", rejected(doc))
        legacy = copy.deepcopy(good)
        legacy["schema_version"] = "1.0.0"
        del legacy["provenance"]["input_build"]
        del legacy["provenance"]["build_basis"]
        _require("a 1.0.0 document missing both fields is still accepted", not rejected(legacy))
        return True
    if _jsonschema() is None:
        _skip("R2A.schema_enforces_build_fields", "jsonschema not installed")
    else:
        attempt("R2A.schema_enforces_build_fields", schema_enforces_build_fields)

    # --- R2A.error_messages_do_not_echo_data (INV-09) -----------------------------------
    def error_messages_do_not_echo_data():
        from snp_insights import cli
        sentinels = ["rs77777777", "99.9", "GRCh99", "GRChSENTINEL", "sentinel_raw_name", "Zq"]
        sentinel_rows = [("rs77777777", 1, 1000, "A", "G")]
        for label, build, the_panel in (("file build", "99.9", panel),
                                        ("panel build", "37.1", _panel(_effect_variant(), genome_build="GRChSENTINEL"))):
            with tempfile.TemporaryDirectory() as d:
                raw = _write_raw(d, sentinel_rows, build=build, name="sentinel_raw_name.txt")
                pp = _write_panel(d, the_panel, name="sentinel_panel_name.json")
                digest = _sha256(raw)
                rc, so, se = _run_main([raw, pp, "-o", os.path.join(d, "o.json")])
                _require(f"{label}: refusal exits 2, got {rc}", rc == 2)
                _require(f"{label}: stderr is exactly the fixed message, got {se!r}", se == BUILD_REFUSED_MESSAGE + "\n")
                _require(f"{label}: stdout is empty", so == "")
                err, out = io.StringIO(), io.StringIO()
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                    cli.main(["run", raw, pp, "--out-dir", os.path.join(d, "run-out"), "--template-only"])
                seen = err.getvalue() + out.getvalue() + se + so
                for needle in sentinels + [digest, raw, pp, os.path.basename(raw), os.path.basename(pp)]:
                    _require(f"{label}: output does not echo {needle[:12]!r}", needle not in seen)
        return True
    attempt("R2A.error_messages_do_not_echo_data", error_messages_do_not_echo_data)


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
    _run_interpretation(attempt)
    _run_build(attempt)


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
