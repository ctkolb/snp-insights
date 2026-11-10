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


# Out-of-schema letters differ from the ones the earlier gates use (X, -, a).
SCHEMA_ALLELES = frozenset("ACGTID")


def _write_raw_lines(directory, header_lines, rows, name="raw.txt"):
    """Write a synthetic five-column file with exactly the given comment lines."""
    lines = list(header_lines) + ["rsid\tchromosome\tposition\tallele1\tallele2"]
    lines.extend("\t".join(str(c) for c in row) for row in rows)
    path = os.path.join(directory, name)
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def _run_fix_round(attempt):
    """Gates added in the 2A fix round: schema-valid uninterpretable calls (F1),
    stated-but-unrecognized builds (F2) and alphabet mutation guards (T1)."""
    import annotate
    import ancestry

    base_rows = [("rs900001", 1, 1000, "A", "G"), ("rs900002", 1, 2000, "G", "G")]
    base_panel = _panel(_effect_variant(), _refalt_variant())
    ind_d = _variant("rs900003", "7", 3000, None, None, effect="D", assay="indel")
    # letters never used by the earlier junk-letter gates, plus multi-character and empty
    junk_letters = ("Z", "N", "q", "AC", "", "ZZ9")

    def validates(doc):
        jsonschema = _jsonschema()
        if jsonschema is None:
            return None
        errors = list(jsonschema.Draft202012Validator(_load(SCHEMA_PATH)).iter_errors(doc))
        return errors

    # --- R2A.F1_uninterpretable_junk_letters_omit_alleles -----------------------
    def f1_uninterpretable_junk_letters_omit_alleles():
        pairs = [("X", "X"), ("A", "X"), ("X", "A"), ("a", "a"), ("-", "-")]
        pairs += [(j, j) for j in junk_letters] + [("A", j) for j in junk_letters] + [(j, "G") for j in junk_letters]
        for a1, a2 in pairs:
            f = _finding([("rs900001", 1, 1000, a1, a2)], _effect_variant())
            _require(f"{a1!r}/{a2!r}: uninterpretable, got {_sig(f)}", _uninterpretable(f))
            extra = sorted(set(f["call"]) - {"state", "zygosity", "strand"})
            _require(f"{a1!r}/{a2!r}: call carries no allele fields, found {extra}", not extra)
            _require(f"{a1!r}/{a2!r}: strand kept, got {f['call'].get('strand')!r}", f["call"].get("strand") == "forward")
        return True
    attempt("R2A.F1_uninterpretable_junk_letters_omit_alleles", f1_uninterpretable_junk_letters_omit_alleles)

    # --- R2A.F1_uninterpretable_junk_document_validates -------------------------
    def f1_uninterpretable_junk_document_validates():
        if _jsonschema() is None:
            _skip("R2A.F1_uninterpretable_junk_document_validates", "jsonschema not installed")
            return True
        for a1, a2 in (("X", "X"), ("A", "X"), ("a", "a"), ("AC", "AC"), ("", ""), ("Z", "N"), ("q", "G")):
            doc = _findings([("rs900001", 1, 1000, a1, a2), ("rs900002", 1, 2000, "G", "G")], base_panel)
            _require(f"{a1!r}/{a2!r}: finding is uninterpretable", _uninterpretable(doc["findings"][0]))
            errors = validates(doc)
            _require(f"{a1!r}/{a2!r}: document validates against schema 1.1.0, got "
                     f"{[e.message for e in errors][:2]}", not errors)
        return True
    attempt("R2A.F1_uninterpretable_junk_document_validates", f1_uninterpretable_junk_document_validates)

    # --- R2A.F1_junk_letters_not_echoed_in_document -----------------------------
    def f1_junk_letters_not_echoed_in_document():
        sentinel = "QZ7"
        for a1, a2 in ((sentinel, sentinel), ("A", sentinel)):
            doc = _findings([("rs900001", 1, 1000, a1, a2)], _panel(_effect_variant()))
            _require(f"{a1}/{a2}: finding is uninterpretable", _uninterpretable(doc["findings"][0]))
            _require(f"{a1}/{a2}: the raw letters appear nowhere in the document", sentinel not in json.dumps(doc))
        return True
    attempt("R2A.F1_junk_letters_not_echoed_in_document", f1_junk_letters_not_echoed_in_document)

    # --- R2A.F1_y_in_female_junk_letters_omit_alleles ---------------------------
    def f1_y_in_female_junk_letters_omit_alleles():
        v = _variant("rsY1", "Y", 3000000, "T", "C")
        for a1, a2 in (("Z", "Z"), ("T", "N"), ("AC", "T")):
            with tempfile.TemporaryDirectory() as d:
                raw = ancestry.parse_ancestry(_write_raw(d, [("rsY1", 24, 3000000, a1, a2)]))
            f = annotate.annotate_variant(v, raw, {}, "female")
            _require(f"{a1}/{a2}: Y call in an inferred female is uninterpretable, got {_sig(f)}", _uninterpretable(f))
            extra = sorted(set(f["call"]) - {"state", "zygosity", "strand"})
            _require(f"{a1}/{a2}: call carries no allele fields, found {extra}", not extra)
        return True
    attempt("R2A.F1_y_in_female_junk_letters_omit_alleles", f1_y_in_female_junk_letters_omit_alleles)

    # --- R2A.F1_valid_letters_uninterpretable_keep_alleles (characterization) ---
    def f1_valid_letters_uninterpretable_keep_alleles():
        for a1, a2 in (("C", "C"), ("C", "T"), ("A", "C"), ("I", "D"), ("D", "D")):
            f = _finding([("rs900001", 1, 1000, a1, a2)], _effect_variant())
            _require(f"{a1}/{a2}: uninterpretable, got {_sig(f)}", _uninterpretable(f))
            _require(f"{a1}/{a2}: alleles kept, got {f['call']}",
                     (f["call"].get("allele1"), f["call"].get("allele2")) == (a1, a2))
        f = _finding([("rs900003", 7, 3000, "A", "C")], ind_d)
        _require(f"SNP letters on an indel keep their alleles, got {f['call']}",
                 (f["call"].get("allele1"), f["call"].get("allele2")) == ("A", "C"))
        v = _variant("rsY1", "Y", 3000000, "T", "C")
        with tempfile.TemporaryDirectory() as d:
            raw = ancestry.parse_ancestry(_write_raw(d, [("rsY1", 24, 3000000, "T", "T")]))
        f = annotate.annotate_variant(v, raw, {}, "female")
        _require(f"Y call in a female with valid letters keeps its alleles, got {f['call']}",
                 (f["call"].get("allele1"), f["call"].get("allele2")) == ("T", "T"))
        f = _finding([("rs900001", 1, 1000, "A", "G")], _effect_variant())
        _require(f"a detected call keeps its alleles, got {f['call']}",
                 f["state"] == "detected" and (f["call"]["allele1"], f["call"]["allele2"]) == ("A", "G"))
        return True
    attempt("R2A.F1_valid_letters_uninterpretable_keep_alleles", f1_valid_letters_uninterpretable_keep_alleles)

    # --- R2A.F2_unrecognized_build_token_refused --------------------------------
    unrecognized = ("hg19", "GRCh37", "grch38", "hg38", "b37", "37.2", "99.9", "37.", "GRChSENTINEL9")

    def refused_run(header, token_note):
        """annotate.main and build_findings on a header; returns nothing, raises _Gate on a miss."""
        with tempfile.TemporaryDirectory() as d:
            raw = _write_raw_lines(d, header, base_rows)
            pp = _write_panel(d, base_panel)
            out = os.path.join(d, "findings.json")
            rc, so, se = _run_main([raw, pp, "-o", out, "--aliases", os.path.join(d, "none.json")])
            _require(f"{token_note}: annotate.main returns 2, got {rc}", rc == 2)
            _require(f"{token_note}: stderr is the fixed message, got {se!r}", se == BUILD_REFUSED_MESSAGE + "\n")
            _require(f"{token_note}: stdout is empty", so == "")
            _require(f"{token_note}: nothing is written", not os.path.exists(out))
            err = None
            try:
                annotate.build_findings(raw, base_panel, {})
            except Exception as exc:  # noqa: BLE001
                err = exc
            _require(f"{token_note}: build_findings raises BuildRefused, got {type(err).__name__}",
                     type(err).__name__ == "BuildRefused")

    def f2_unrecognized_build_token_refused():
        for token in unrecognized:
            refused_run(["#Data was collected using AncestryDNA array version: V2.0",
                         f"#using human reference build {token} coordinates."], f"build {token}")
        return True
    attempt("R2A.F2_unrecognized_build_token_refused", f2_unrecognized_build_token_refused)

    # --- R2A.F2_parser_surfaces_unrecognized_build ------------------------------
    def f2_parser_surfaces_unrecognized_build():
        with tempfile.TemporaryDirectory() as d:
            for token in ("hg19", "GRCh37"):
                raw = _write_raw_lines(d, [f"#using human reference build {token} coordinates."], base_rows)
                got = ancestry.parse_ancestry(raw)["meta"]["genome_build"]
                _require(f"build {token}: the parser reports a stated build, got {got!r}", got)
                _require(f"build {token}: it is neither GRCh37 nor GRCh38, got {got!r}", got not in ("GRCh37", "GRCh38"))
                _require(f"build {token}: the token is not carried into meta, got {got!r}", token not in str(got))
        return True
    attempt("R2A.F2_parser_surfaces_unrecognized_build", f2_parser_surfaces_unrecognized_build)

    # --- R2A.F2_phrase_case_insensitive -----------------------------------------
    def f2_phrase_case_insensitive():
        for header in ("#Using HUMAN Reference BUILD hg19 coordinates", "#using human  reference\tbuild hg19"):
            refused_run([header], f"header {header!r}")
        for header in ("#using Human Reference Build 37.1 coordinates", "#USING HUMAN REFERENCE BUILD 37"):
            doc = None
            with tempfile.TemporaryDirectory() as d:
                doc = annotate.build_findings(_write_raw_lines(d, [header], base_rows), base_panel, {})
            prov = doc["provenance"]
            _require(f"header {header!r}: input_build GRCh37, got {prov['input_build']!r}", prov["input_build"] == "GRCh37")
            _require(f"header {header!r}: basis file_statement, got {prov['build_basis']!r}",
                     prov["build_basis"] == "file_statement")
        return True
    attempt("R2A.F2_phrase_case_insensitive", f2_phrase_case_insensitive)

    # --- R2A.F2_unrecognized_build_is_not_overridden ----------------------------
    def f2_unrecognized_build_is_not_overridden():
        for first, second in (("hg19", "37.1"), ("37.1", "hg19")):
            refused_run([f"#using human reference build {first} coordinates.",
                         f"#again, human reference build {second} coordinates."], f"builds {first} then {second}")
        return True
    attempt("R2A.F2_unrecognized_build_is_not_overridden", f2_unrecognized_build_is_not_overridden)

    # --- R2A.F2_unrecognized_build_run_writes_no_files ---------------------------
    def f2_unrecognized_build_run_writes_no_files():
        from snp_insights import cli
        with tempfile.TemporaryDirectory() as d:
            raw = _write_raw_lines(d, ["#using human reference build hg19 coordinates."], base_rows)
            pp = _write_panel(d, base_panel)
            out_dir = os.path.join(d, "run-out")
            err, out = io.StringIO(), io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                rc = cli.main(["run", raw, pp, "--out-dir", out_dir, "--template-only"])
            _require(f"run returns non-zero, got {rc}", rc != 0)
            present = [n for n in cli._OUTPUT_NAMES if os.path.lexists(os.path.join(out_dir, n))]
            _require(f"none of the run's output names exists, found {present}", not present)
            _require("the unrecognized token is not echoed", "hg19" not in err.getvalue() + out.getvalue())
        return True
    attempt("R2A.F2_unrecognized_build_run_writes_no_files", f2_unrecognized_build_run_writes_no_files)

    # --- R2A.F2_recognized_and_absent_builds_unchanged (characterization) -------
    def f2_recognized_and_absent_builds_unchanged():
        for token in ("37", "37.1"):
            with tempfile.TemporaryDirectory() as d:
                raw = _write_raw_lines(d, [f"#using human reference build {token} coordinates."], base_rows)
                doc = annotate.build_findings(raw, base_panel, {})
            prov = doc["provenance"]
            _require(f"build {token}: GRCh37 from a file statement, got {(prov['input_build'], prov['build_basis'])}",
                     (prov["input_build"], prov["build_basis"]) == ("GRCh37", "file_statement"))
        with tempfile.TemporaryDirectory() as d:
            raw = _write_raw_lines(d, ["#using human reference build 38 coordinates."], base_rows)
            _require("a stated build 38 still parses as GRCh38", ancestry.parse_ancestry(raw)["meta"]["genome_build"] == "GRCh38")
            refused_run(["#using human reference build 38 coordinates."], "build 38")
            raw = _write_raw_lines(d, ["#no build statement here"], base_rows, name="none.txt")
            doc = annotate.build_findings(raw, base_panel, {})
            prov = doc["provenance"]
            _require(f"no statement: unknown / not_stated, got {(prov['input_build'], prov['build_basis'])}",
                     (prov["input_build"], prov["build_basis"]) == ("unknown", "not_stated"))
            _require("no statement: the parser reports none", ancestry.parse_ancestry(raw)["meta"]["genome_build"] is None)
        return True
    attempt("R2A.F2_recognized_and_absent_builds_unchanged", f2_recognized_and_absent_builds_unchanged)

    # --- R2A.F2_comment_lines_with_word_build_are_not_statements ----------------
    def f2_comment_lines_with_word_build_are_not_statements():
        headers = ["#this manifest was build 99 of the probe set",
                   "#rebuild hg19 pending, see notes",
                   "#reference build hg19 is not what this line states",
                   "#human reference build",
                   "#build   GRCh99 appears only in prose"]
        with tempfile.TemporaryDirectory() as d:
            for header in headers:
                raw = _write_raw_lines(d, [header], base_rows)
                got = ancestry.parse_ancestry(raw)["meta"]["genome_build"]
                _require(f"{header!r}: the parser reports no build, got {got!r}", got is None)
                doc = annotate.build_findings(raw, base_panel, {})
                prov = doc["provenance"]
                _require(f"{header!r}: unknown / not_stated, got {(prov['input_build'], prov['build_basis'])}",
                         (prov["input_build"], prov["build_basis"]) == ("unknown", "not_stated"))
        return True
    attempt("R2A.F2_comment_lines_with_word_build_are_not_statements", f2_comment_lines_with_word_build_are_not_statements)

    # --- R2A.T1_effect_known_nonset_unknown_junk_is_uninterpretable --------------
    def t1_effect_known_nonset_unknown_junk_is_uninterpretable():
        # effect A, no reference/alternate: the declared set is {A}, so only the
        # alphabet check can reject a junk letter next to the effect allele.
        nothing = _variant("rs900001", "1", 1000, None, None, effect="A")
        for junk in ("X", "Z", "N", "q", "AC", "", "9"):
            for a1, a2 in (("A", junk), (junk, "A"), (junk, junk)):
                f = _finding([("rs900001", 1, 1000, a1, a2)], nothing)
                _require(f"effect A, no ref/alt, {a1!r}/{a2!r}: uninterpretable, not detected/het, got {_sig(f)}",
                         _uninterpretable(f))
        f = _finding([("rs900001", 1, 1000, "A", "G")], nothing)
        _require(f"effect A, no ref/alt, A/G: still detected het, got {_sig(f)}",
                 f["state"] == "detected" and f["call"]["zygosity"] == "het")
        # only the reference is declared next to the effect allele: the alphabet still applies
        only_ref = _variant("rs900001", "1", 1000, "G", None, effect="A")
        for junk in ("X", "Z", "N", "q", "AC"):
            f = _finding([("rs900001", 1, 1000, "A", junk)], only_ref)
            _require(f"effect A, ref G, A/{junk!r}: uninterpretable, got {_sig(f)}", _uninterpretable(f))
        return True
    attempt("R2A.T1_effect_known_nonset_unknown_junk_is_uninterpretable",
            t1_effect_known_nonset_unknown_junk_is_uninterpretable)

    # --- R2A.T1_alphabet_is_exactly_the_assayability_letters ---------------------
    def t1_alphabet_is_exactly_the_assayability_letters():
        classify_effect = annotate.classify_effect
        _require("the SNP alphabet is exactly A, C, G, T", set(annotate.ALPHABET["snp"]) == set("ACGT"))
        _require("the indel alphabet is exactly I, D", set(annotate.ALPHABET["indel"]) == set("ID"))
        for junk in ("X", "Z", "N", "q", "AC", ""):
            got = classify_effect(["A", junk], "A", None, None, "snp")
            _require(f"snp, A/{junk!r}, no ref/alt: (unknown, None), got {got}", got == ("unknown", None))
            got = classify_effect([junk, junk], "A", "G", "A", "snp")
            _require(f"snp, {junk!r}/{junk!r}, ref G alt A: (unknown, None), got {got}", got == ("unknown", None))
            got = classify_effect(["D", junk], "D", None, None, "indel")
            _require(f"indel, D/{junk!r}: (unknown, None), got {got}", got == ("unknown", None))
        got = classify_effect(["A", "G"], "A", None, None, "snp")
        _require(f"snp, A/G, no ref/alt: (het, True), got {got}", got == ("het", True))
        return True
    attempt("R2A.T1_alphabet_is_exactly_the_assayability_letters", t1_alphabet_is_exactly_the_assayability_letters)


def _run_r58(attempt):
    """Ticket 2C (snp-REL-B-BUILD-r58): the complete dbSNP alternate list.
    ADD-ONLY. The list is read from the panel variant, never from memory."""
    def multi_variant(**kw):
        v = _variant("rs900001", "1", 1000, "T", "C", effect="A")
        v.update(kw)
        return v

    def classify_effect_multi_allelic():
        multi = multi_variant(alternate_alleles=["C", "A", "G"])
        f = _finding([("rs900001", 1, 1000, "G", "G")], multi)
        _require(f"G/G with the full alternate list is covered_reference, got {_sig(f)}",
                 (f["state"], f["call"]["zygosity"]) == ("covered_reference", "hom_ref"))
        f = _finding([("rs900001", 1, 1000, "A", "C")], multi)
        _require(f"A/C with the full alternate list is detected, got {_sig(f)}",
                 (f["state"], f["call"]["zygosity"]) == ("detected", "het"))
        legacy = multi_variant()
        f = _finding([("rs900001", 1, 1000, "G", "G")], legacy)
        _require(f"G/G without the list stays uninterpretable, got {_sig(f)}", _uninterpretable(f))
        partial = multi_variant(alternate_alleles=["C", "A"])
        f = _finding([("rs900001", 1, 1000, "G", "G")], partial)
        _require(f"G/G with a list that omits G stays uninterpretable, got {_sig(f)}", _uninterpretable(f))
        return True
    attempt("R2C.classify_effect_multi_allelic", classify_effect_multi_allelic)

    def classify_effect_indel_ignores_list():
        v = _variant("rs900003", "7", 3000, None, None, effect="D", assay="indel")
        v["alternate_alleles"] = ["T", "TT"]
        f = _finding([("rs900003", 7, 3000, "I", "I")], v)
        _require(f"I/I is covered_reference for an indel, got {_sig(f)}",
                 (f["state"], f["call"]["zygosity"]) == ("covered_reference", "hom_ref"))
        g = _finding([("rs900003", 7, 3000, "D", "D")], v)
        _require(f"D/D is detected, got {_sig(g)}", (g["state"], g["call"]["zygosity"]) == ("detected", "hom_alt"))
        return True
    attempt("R2C.classify_effect_indel_ignores_list", classify_effect_indel_ignores_list)

    def classify_effect_present_empty_falls_back():
        v = multi_variant(alternate_alleles=[])
        f = _finding([("rs900001", 1, 1000, "C", "C")], v)
        _require(f"C/C with a present-but-empty list falls back to the singular alt, got {_sig(f)}",
                 (f["state"], f["call"]["zygosity"]) == ("covered_reference", "hom_ref"))
        return True
    attempt("R2C.syn_classify_effect_present_empty_falls_back", classify_effect_present_empty_falls_back)


def _run_r58_char(attempt):
    """Ticket 2C C0: today's classify_effect on legacy panels (no alternate list)."""
    import annotate

    def classify_effect_legacy_declared_set():
        cases = [
            ((["A", "G"], "A", "G", "A", "snp"), ("het", True)),
            ((["G", "G"], "A", "G", "A", "snp"), ("hom_ref", False)),
            ((["A", "A"], "A", "G", "A", "snp"), ("hom_alt", True)),
            ((["A", "C"], "A", "G", "A", "snp"), ("unknown", None)),
            ((["C", "C"], "A", "G", "A", "snp"), ("unknown", None)),
            ((["D", "D"], "D", None, None, "indel"), ("hom_alt", True)),
            ((["I", "I"], "D", None, None, "indel"), ("hom_ref", False)),
        ]
        return all(annotate.classify_effect(*args) == want for args, want in cases)
    attempt("R2C.char_classify_effect_legacy_declared_set", classify_effect_legacy_declared_set)


# Ticket 2D C0 (add-only): golden canonical hashes of today's legacy findings
# output. generated_at is dropped (it is wall-clock); everything else is pinned,
# so any change to legacy output (a new field, a version bump, an altered value)
# changes the hash and fails the characterization gate.
R61_LEGACY_FIXTURE_HASH = "e86cddca2c9fdaa9a3f4474d0c4f41a432090e21e161cebc9089ba2e2e578200"
R61_LEGACY_INLINE_HASH = "8f30f3abc644383be9631091fee365ca8a36bed500840df9284d70251589d78d"


def _r61_canonical_hash(doc):
    import hashlib
    d = json.loads(json.dumps(doc))
    d["provenance"].pop("generated_at", None)
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()


def _run_r61_char(attempt):
    """Ticket 2D C0 (ADD-ONLY). CHARACTERIZATION: legacy panels (no result_type
    anywhere) must produce findings byte-identical to today's output. Passes on
    the base commit and must keep passing unmodified after the 2D change."""
    def legacy_panel_findings_unchanged():
        import annotate
        cases = []
        fixture_panel = _load(os.path.join(ROOT, "data", "panel.sample.json"))
        aliases = annotate.load_aliases(os.path.join(ROOT, "data", "condition_aliases.json"))
        cases.append(("fixture panel",
                      annotate.build_findings(os.path.join(FIX, "raw.sample.txt"), fixture_panel, aliases),
                      R61_LEGACY_FIXTURE_HASH))
        # an inline legacy panel carries cls and effect_allele but no result_type:
        # none of the three 2D fields may leak into the legacy finding.
        inline_panel = _panel(_effect_variant(), _refalt_variant())
        inline_rows = [("rs900001", 1, 1000, "A", "G"), ("rs900002", 1, 2000, "A", "A")]
        cases.append(("inline legacy panel", _findings(inline_rows, inline_panel), R61_LEGACY_INLINE_HASH))
        for label, doc, want in cases:
            got = _r61_canonical_hash(doc)
            _require(f"{label}: legacy findings hash changed, got {got}, want {want}", got == want)
            _require(f"{label}: schema_version is 1.1.0, got {doc['schema_version']!r}",
                     doc["schema_version"] == "1.1.0")
            for f in doc["findings"]:
                for key in ("result_type", "effect_allele", "cls"):
                    _require(f"{label}: legacy finding {f['finding_id']} must not carry {key}", key not in f)
        return True
    attempt("R2D.legacy_panel_findings_unchanged", legacy_panel_findings_unchanged)


def _release_panel():
    """A panel in release format: at least one variant carries result_type.

    Both variants carry cls and effect_allele; the two result_type values differ
    so a per-variant copy is distinguishable from a constant.
    """
    carrier = _variant("rs900001", "1", 1000, "G", "A", effect="A")
    carrier["category"] = "carrier"
    carrier["result_type"] = "carrier_status"
    trait = _variant("rs900002", "1", 2000, "G", "A")
    trait["category"] = "trait"
    trait["result_type"] = "trait"
    trait["effect_allele"] = "A"
    return _panel(carrier, trait)


def _run_r61(attempt):
    """Ticket 2D: findings carry result_type / effect_allele / cls in release
    format only, and the schema accepts 1.2.0. FAILING on the base commit."""
    def finding_carries_result_type():
        doc = _findings([("rs900001", 1, 1000, "A", "G"), ("rs900002", 1, 2000, "A", "A")],
                        _release_panel())
        by = {f["rsid"]: f for f in doc["findings"]}
        _require(f"carrier finding carries result_type carrier_status, got {by['rs900001'].get('result_type')!r}",
                 by["rs900001"].get("result_type") == "carrier_status")
        _require(f"trait finding carries result_type trait, got {by['rs900002'].get('result_type')!r}",
                 by["rs900002"].get("result_type") == "trait")
        # a release-format panel variant that omits result_type stays absent (no default)
        only = _variant("rs900001", "1", 1000, "G", "A", effect="A")
        only["category"] = "trait"
        marker = _variant("rs900002", "1", 2000, "G", "A")
        marker["result_type"] = "trait"
        doc2 = _findings([("rs900001", 1, 1000, "A", "G"), ("rs900002", 1, 2000, "A", "A")],
                         _panel(only, marker))
        f0 = doc2["findings"][0]
        _require("a panel variant without result_type yields a finding without the key",
                 "result_type" not in f0)
        return True
    attempt("R2D.finding_carries_result_type", finding_carries_result_type)

    def finding_carries_effect_allele():
        doc = _findings([("rs900001", 1, 1000, "A", "G"), ("rs900002", 1, 2000, "A", "A")],
                        _release_panel())
        by = {f["rsid"]: f for f in doc["findings"]}
        _require(f"carrier finding carries effect_allele A, got {by['rs900001'].get('effect_allele')!r}",
                 by["rs900001"].get("effect_allele") == "A")
        _require(f"trait finding carries effect_allele A, got {by['rs900002'].get('effect_allele')!r}",
                 by["rs900002"].get("effect_allele") == "A")
        # a release-format variant without effect_allele stays absent
        noeffect = _variant("rs900001", "1", 1000, "G", "A")
        noeffect["result_type"] = "carrier_status"
        marker = _variant("rs900002", "1", 2000, "G", "A")
        marker["result_type"] = "trait"
        doc2 = _findings([("rs900001", 1, 1000, "A", "G")], _panel(noeffect, marker))
        _require("a panel variant without effect_allele yields a finding without the key",
                 "effect_allele" not in doc2["findings"][0])
        # legacy panel (no result_type anywhere): effect_allele is not copied
        legacy = _findings([("rs900001", 1, 1000, "A", "G")], _panel(_effect_variant()))
        _require("a legacy panel finding carries no effect_allele",
                 "effect_allele" not in legacy["findings"][0])
        return True
    attempt("R2D.finding_carries_effect_allele", finding_carries_effect_allele)

    def finding_carries_cls_when_present():
        doc = _findings([("rs900001", 1, 1000, "A", "G")], _release_panel())
        _require(f"release finding carries cls risk, got {doc['findings'][0].get('cls')!r}",
                 doc["findings"][0].get("cls") == "risk")
        nocl = _variant("rs900001", "1", 1000, "G", "A", effect="A")
        nocl.pop("cls", None)
        nocl["result_type"] = "carrier_status"
        marker = _variant("rs900002", "1", 2000, "G", "A")
        marker["result_type"] = "trait"
        doc2 = _findings([("rs900001", 1, 1000, "A", "G")], _panel(nocl, marker))
        _require("a panel variant without cls yields a finding without the key",
                 "cls" not in doc2["findings"][0])
        legacy = _findings([("rs900001", 1, 1000, "A", "G")], _panel(_effect_variant()))
        _require("a legacy panel finding carries no cls", "cls" not in legacy["findings"][0])
        return True
    attempt("R2D.finding_carries_cls_when_present", finding_carries_cls_when_present)

    def schema_version_rule():
        legacy = _findings([("rs900001", 1, 1000, "A", "G")], _panel(_effect_variant()))
        _require(f"a legacy panel emits 1.1.0, got {legacy['schema_version']!r}",
                 legacy["schema_version"] == "1.1.0")
        rel = _findings([("rs900001", 1, 1000, "A", "G")], _release_panel())
        _require(f"a release panel emits 1.2.0, got {rel['schema_version']!r}",
                 rel["schema_version"] == "1.2.0")
        marker = _variant("rs900002", "1", 2000, "G", "A")
        marker["result_type"] = "trait"
        mixed = _findings([("rs900001", 1, 1000, "A", "G")], _panel(_effect_variant(), marker))
        _require(f"one result_type anywhere makes the document 1.2.0, got {mixed['schema_version']!r}",
                 mixed["schema_version"] == "1.2.0")
        return True
    attempt("R2D.schema_version_rule", schema_version_rule)

    def no_category_key_still_absent():
        def no_key(obj):
            if isinstance(obj, dict):
                return "category" not in obj and all(no_key(v) for v in obj.values())
            if isinstance(obj, list):
                return all(no_key(v) for v in obj)
            return True
        rel = _findings([("rs900001", 1, 1000, "A", "G"), ("rs900002", 1, 2000, "A", "A")],
                        _release_panel())
        _require("release findings carry no category key anywhere", no_key(rel))
        legacy = _findings([("rs900001", 1, 1000, "A", "G")], _panel(_effect_variant()))
        _require("legacy findings carry no category key anywhere", no_key(legacy))
        return True
    attempt("R2D.no_category_key_still_absent", no_category_key_still_absent)

    def schema_accepts_new_fields():
        import jsonschema
        validator = jsonschema.Draft202012Validator(_load(SCHEMA_PATH))
        doc = _findings([("rs900001", 1, 1000, "A", "G"), ("rs900002", 1, 2000, "A", "A")],
                        _release_panel())
        _require(f"the generated document is 1.2.0, got {doc['schema_version']!r}",
                 doc["schema_version"] == "1.2.0")
        _require("the finding carries result_type", doc["findings"][0].get("result_type") == "carrier_status")
        _require("the finding carries effect_allele", doc["findings"][0].get("effect_allele") == "A")
        _require("the finding carries cls", doc["findings"][0].get("cls") == "risk")
        errors = list(validator.iter_errors(doc))
        _require(f"a valid 1.2.0 document validates, got {[e.message for e in errors][:2]}", not errors)
        return True
    if _jsonschema() is None:
        _skip("R2D.schema_accepts_new_fields", "jsonschema not installed")
    else:
        attempt("R2D.schema_accepts_new_fields", schema_accepts_new_fields)

    def schema_rejects_unknown_result_type():
        import copy
        import jsonschema
        validator = jsonschema.Draft202012Validator(_load(SCHEMA_PATH))
        good = _findings([("rs900001", 1, 1000, "A", "G")], _release_panel())
        good["schema_version"] = "1.2.0"
        good["findings"][0]["result_type"] = "carrier_status"
        good["findings"][0]["effect_allele"] = "A"
        good["findings"][0]["cls"] = "risk"
        errors = list(validator.iter_errors(good))
        _require(f"positive control: a 1.2.0 document with known fields validates, got "
                 f"{[e.message for e in errors][:2]}", not errors)
        bad = copy.deepcopy(good)
        bad["findings"][0]["result_type"] = "carrier"
        _require("an out-of-vocabulary result_type is rejected", bool(list(validator.iter_errors(bad))))
        return True
    if _jsonschema() is None:
        _skip("R2D.schema_rejects_unknown_result_type", "jsonschema not installed")
    else:
        attempt("R2D.schema_rejects_unknown_result_type", schema_rejects_unknown_result_type)

    def findings_validate_all_fixtures():
        import jsonschema
        validator = jsonschema.Draft202012Validator(_load(SCHEMA_PATH))
        found = []
        for name in sorted(os.listdir(FIX)):
            if not name.endswith(".json"):
                continue
            try:
                obj = _load(os.path.join(FIX, name))
            except (OSError, ValueError):
                continue
            if isinstance(obj, dict) and "schema_version" in obj and "findings" in obj:
                found.append((name, obj))
        _require("at least one findings fixture is present", found)
        for name, obj in found:
            errors = list(validator.iter_errors(obj))
            _require(f"findings fixture {name} validates, got {[e.message for e in errors][:2]}", not errors)
        legacy = _findings([("rs900001", 1, 1000, "A", "G")], _panel(_effect_variant()))
        rel = _findings([("rs900001", 1, 1000, "A", "G")], _release_panel())
        _require("a generated legacy document validates", not list(validator.iter_errors(legacy)))
        _require(f"a generated release document is 1.2.0, got {rel['schema_version']!r}",
                 rel["schema_version"] == "1.2.0")
        _require("a generated release document validates", not list(validator.iter_errors(rel)))
        return True
    if _jsonschema() is None:
        _skip("R2D.findings_validate_all_fixtures", "jsonschema not installed")
    else:
        attempt("R2D.findings_validate_all_fixtures", findings_validate_all_fixtures)

    def report_validator_unaffected():
        import validate_report
        good = validate_report.check(os.path.join(FIX, "findings.sample.json"),
                                     _load(os.path.join(FIX, "report.sample.json")))
        _require(f"the sample report still validates, got {good}", not good[0])
        bad = validate_report.check(os.path.join(FIX, "findings.sample.json"),
                                    _load(os.path.join(FIX, "report.bad.json")))
        _require("the bad report is still rejected", bool(bad[0]))
        return True
    attempt("R2D.report_validator_unaffected", report_validator_unaffected)


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

    _run_r58_char(attempt)
    _run_r58(attempt)

    _run_r61_char(attempt)
    _run_r61(attempt)

    _run_characterization(attempt)
    _run_interpretation(attempt)
    _run_build(attempt)
    _run_fix_round(attempt)


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
