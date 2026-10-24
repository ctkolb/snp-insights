#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Stage 2 gates: category-aware association derivation and validation.

Run standalone:  python tests/test_category.py
Or as part of:   python tests/test_pipeline.py

Every gate is isolated: a missing module, a missing function, or any exception
fails only that one check (via attempt()), never the whole run.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "stage2"))

DATA = os.path.join(ROOT, "data")
FIX = os.path.join(ROOT, "fixtures")
PANEL_CLINVAR_KEYS = {"significance", "review_stars", "review_status_text", "source_version"}
TARGET_KEYS = {
    "carrier": {"rsid", "gene", "condition", "assayability", "cls", "effect_allele"},
    "trait": {"rsid", "gene", "condition", "assayability"},
}
# effect_allele is curated per variant, so it is allowed but not required.
TARGET_REQUIRED = {
    "carrier": {"rsid", "gene", "condition", "assayability", "cls"},
    "trait": {"rsid", "gene", "condition", "assayability"},
}


def _load(path):
    with open(path) as fh:
        return json.load(fh)


def _mods():
    import build_panel
    import evidence
    return evidence, build_panel


def _capture_stderr(fn):
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        result = fn()
    return result, buf.getvalue()


# D-B table, written out literally (never by calling derive_association).
_STARS = {4: "established", 3: "established", 2: "replicated", 1: "single_study"}


def _cv_tier(cv):
    if cv is None:
        return None
    if "conflicting" in (cv.get("significance") or "").lower():
        return "conflicting"
    return _STARS.get(cv.get("review_stars"))


def _gwas_tier(n):
    if not n:
        return None
    return "replicated" if n >= 2 else "single_study"


def _expected(category, cv, gwas_n, cv_matched):
    ct = _cv_tier(cv)
    n = gwas_n or 0
    if category is None:
        return ct or _gwas_tier(n) or "unknown"
    if category == "carrier":
        return ct or "unknown"
    if category == "trait":
        if n >= 1:
            return _gwas_tier(n)
        if cv is not None and cv_matched:
            return ct or "unknown"
        return "unknown"
    raise AssertionError("unexpected category in test helper")


def _clinvar_record(significance, stars, phenotype=""):
    return {"significance": significance, "review_stars": stars,
            "review_status_text": "", "source_version": "ClinVar test",
            "phenotype": phenotype}


def _target(rsid, **extra):
    t = {"rsid": rsid, "gene": "G", "condition": "Condition", "assayability": "snp"}
    t.update(extra)
    return t


def _build(targets, clinvar=None, gwas=None, aliases=None):
    evidence, build_panel = _mods()
    return build_panel.build({"variants": targets}, sources=[], clinvar=clinvar or {},
                             gwas=gwas or {}, aliases=aliases)


def _no_category_key(obj):
    if isinstance(obj, dict):
        if "category" in obj:
            return False
        return all(_no_category_key(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_no_category_key(v) for v in obj)
    return True


def run(check):
    def attempt(name, fn):
        try:
            result = fn()
        except Exception:  # noqa: BLE001
            check(name, False)
            return
        check(name, bool(result))

    # --- S2.derive_grid -------------------------------------------------
    def s2_derive_grid():
        evidence, build_panel = _mods()
        cvs = {
            "none": None,
            "zero_path": _clinvar_record("Pathogenic", 0),
            "one_conflict": _clinvar_record("Conflicting interpretations of pathogenicity", 1),
            "two_path": _clinvar_record("Pathogenic", 2),
            "three_path": _clinvar_record("Pathogenic", 3),
        }
        for cv in cvs.values():
            for n in (None, 0, 1, 2, 5):
                for matched in (False, True):
                    for category in (None, "carrier", "trait"):
                        got = evidence.derive_association(category, cv, n, matched)
                        if got != _expected(category, cv, n, matched):
                            return False
                        if category is None:
                            legacy = (build_panel.assoc_from_clinvar(cv)
                                      or build_panel.assoc_from_gwas(n) or "unknown")
                            if got != legacy:
                                return False
        return True
    attempt("S2.derive_grid", s2_derive_grid)

    # --- S2.carrier_* ---------------------------------------------------
    def s2_carrier_conflicting():
        evidence, _ = _mods()
        cv = _clinvar_record("Conflicting interpretations of pathogenicity", 1)
        return evidence.derive_association("carrier", cv, 5, False) == "conflicting"
    attempt("S2.carrier_conflicting", s2_carrier_conflicting)

    def s2_carrier_zero_unknown():
        evidence, _ = _mods()
        cv = _clinvar_record("Pathogenic", 0)
        return evidence.derive_association("carrier", cv, 5, True) == "unknown"
    attempt("S2.carrier_zero_unknown", s2_carrier_zero_unknown)

    def s2_carrier_established():
        evidence, _ = _mods()
        cv = _clinvar_record("Pathogenic", 3)
        return evidence.derive_association("carrier", cv, 0, True) == "established"
    attempt("S2.carrier_established", s2_carrier_established)

    # --- S2.trait_gwas_wins ---------------------------------------------
    def s2_trait_gwas_wins():
        evidence, _ = _mods()
        conflicting = _clinvar_record("Conflicting interpretations of pathogenicity", 1)
        if evidence.derive_association("trait", conflicting, 2, False) != "replicated":
            return False
        if evidence.derive_association("trait", conflicting, 2, True) != "replicated":
            return False
        if evidence.derive_association("trait", conflicting, 1, False) != "single_study":
            return False
        return True
    attempt("S2.trait_gwas_wins", s2_trait_gwas_wins)

    # --- S2.trait_clinvar_fallback --------------------------------------
    def s2_trait_clinvar_fallback():
        evidence, _ = _mods()
        cv = _clinvar_record("Pathogenic", 3)
        if evidence.derive_association("trait", cv, 0, False) != "unknown":
            return False
        if evidence.derive_association("trait", cv, 0, True) != "established":
            return False
        return True
    attempt("S2.trait_clinvar_fallback", s2_trait_clinvar_fallback)

    # --- S2.explicit_wins -----------------------------------------------
    def s2_explicit_wins():
        cv = _clinvar_record("Pathogenic", 3)
        for cat in ("carrier", "trait", None):
            panel = _build([_target("rs1", category=cat, association="none")],
                           clinvar={"rs1": cv}, gwas={"rs1": 5})
            if panel["variants"][0]["association"] != "none":
                return False
        return True
    attempt("S2.explicit_wins", s2_explicit_wins)

    # --- S2.legacy_unchanged --------------------------------------------
    def s2_legacy_unchanged():
        out = os.path.join(tempfile.mkdtemp(), "p.json")
        cmd = [sys.executable, os.path.join(ROOT, "tools", "build_panel.py"),
               "--targets", os.path.join(DATA, "targets.sample.json"),
               "--clinvar", os.path.join(FIX, "sources", "clinvar.sample.tsv"),
               "--gnomad", os.path.join(FIX, "sources", "gnomad.sample.vcf"),
               "-o", out]
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if proc.returncode != 0:
            return False
        got = {v["rsid"]: v["association"] for v in _load(out)["variants"]}
        want = {v["rsid"]: v["association"]
                for v in _load(os.path.join(DATA, "panel.sample.json"))["variants"]}
        if got != want:
            return False
        panel, err = _capture_stderr(
            lambda: _build([_target("rsX", condition="Condition")], gwas={"rsX": 2}))
        if panel["variants"][0]["association"] != "replicated":
            return False
        return err.count("rsX") == 1 and "warning" in err
    attempt("S2.legacy_unchanged", s2_legacy_unchanged)

    # --- S2.invalid_category --------------------------------------------
    def s2_invalid_category():
        for bad in ("Carrier", "other", 5, []):
            try:
                _build([_target("rsBAD", category=bad)])
            except ValueError as exc:
                if "rsBAD" not in str(exc):
                    return False
                continue
            except Exception:  # noqa: BLE001
                return False
            return False
        return True
    attempt("S2.invalid_category", s2_invalid_category)

    def s2_invalid_category_even_with_association():
        try:
            _build([_target("rsBAD", category="other", association="established")])
        except ValueError as exc:
            return "rsBAD" in str(exc)
        except Exception:  # noqa: BLE001
            return False
        return False
    attempt("S2.invalid_category_even_with_association",
            s2_invalid_category_even_with_association)

    def s2_null_category_is_none():
        _, build_panel = _mods()
        panel, err = _capture_stderr(
            lambda: _build([_target("rsX", category=None, condition="Condition")],
                           gwas={"rsX": 1}))
        legacy = build_panel.assoc_from_gwas(1)
        return panel["variants"][0]["association"] == legacy and err.count("rsX") == 1
    attempt("S2.null_category_is_none", s2_null_category_is_none)

    # --- S2.main_exit1_no_file ------------------------------------------
    def s2_main_exit1_no_file():
        d = tempfile.mkdtemp()
        tp = os.path.join(d, "targets.json")
        op = os.path.join(d, "out.json")
        with open(tp, "w") as fh:
            json.dump({"variants": [{"rsid": "rsBAD", "gene": "G", "condition": "Condition",
                                     "assayability": "snp", "category": "nope"}]}, fh)
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_panel.py"),
                               "--targets", tp, "-o", op],
                              cwd=ROOT, capture_output=True, text=True)
        return (proc.returncode == 1 and "rsBAD" in proc.stderr and not os.path.exists(op))
    attempt("S2.main_exit1_no_file", s2_main_exit1_no_file)

    # --- warning gates --------------------------------------------------
    def s2_no_warning_with_explicit_association():
        panel, err = _capture_stderr(
            lambda: _build([_target("rsX", category=None, association="established")]))
        return panel["variants"][0]["association"] == "established" and "rsX" not in err
    attempt("S2.no_warning_with_explicit_association", s2_no_warning_with_explicit_association)

    def s2_warning_once_per_variant():
        _, err = _capture_stderr(lambda: _build(
            [_target("rsA", condition="Condition"), _target("rsB", condition="Condition")],
            gwas={"rsA": 2, "rsB": 2}))
        return err.count("rsA") == 1 and err.count("rsB") == 1
    attempt("S2.warning_once_per_variant", s2_warning_once_per_variant)

    # --- S2.panel_* / category passthrough ------------------------------
    def s2_panel_clinvar_four_keys():
        cv = _clinvar_record("Pathogenic", 3, "Condition")
        panel = _build([_target("rs1", category="carrier", condition="Condition")],
                       clinvar={"rs1": cv})
        return set(panel["variants"][0]["clinvar"].keys()) == PANEL_CLINVAR_KEYS
    attempt("S2.panel_clinvar_four_keys", s2_panel_clinvar_four_keys)

    def s2_category_passthrough():
        panel = _build([_target("rs1", category="trait", condition="Condition")],
                       gwas={"rs1": 1})
        return panel["variants"][0].get("category") == "trait"
    attempt("S2.category_passthrough", s2_category_passthrough)

    # --- S2.findings_no_category ----------------------------------------
    def s2_findings_no_category():
        import annotate
        panel = {
            "panel_version": "0.1.0", "genome_build": "GRCh37", "strand": "forward",
            "sources": [], "merges": {},
            "variants": [
                {"rsid": "rs6025", "chromosome": "1", "position": 169519049, "gene": "F5",
                 "condition": "Factor V Leiden thrombophilia", "assayability": "snp",
                 "reference_allele": "G", "alternate_allele": "A", "category": "carrier",
                 "association": "established", "gnomad_af": 0.01, "snpedia": None,
                 "clinvar": _clinvar_record("Pathogenic", 3)},
            ],
        }
        doc = annotate.build_findings(os.path.join(FIX, "raw.sample.txt"), panel, {})
        if not _no_category_key(doc):
            return False
        try:
            import jsonschema
        except ImportError:
            return True
        schema = _load(os.path.join(ROOT, "schema", "findings.schema.json"))
        try:
            jsonschema.Draft202012Validator(schema).validate(doc)
        except Exception:  # noqa: BLE001
            return False
        return True
    attempt("S2.findings_no_category", s2_findings_no_category)

    # --- S2.targets_categories ------------------------------------------
    def s2_targets_categories():
        # Inline literal expectations only; no git and no history, so a shallow
        # CI checkout (depth 1) passes.
        carrier = _load(os.path.join(DATA, "targets.carrier.json"))["variants"]
        traits = _load(os.path.join(DATA, "targets.traits.json"))["variants"]
        if len(carrier) != 9 or len(traits) != 14:
            return False
        if any(v.get("category") != "carrier" for v in carrier):
            return False
        if any(v.get("category") != "trait" for v in traits):
            return False
        for kind, variants in (("carrier", carrier), ("trait", traits)):
            allowed = TARGET_KEYS[kind]
            required = TARGET_REQUIRED[kind]
            for v in variants:
                keys = set(v) - {"category"}
                if not (keys <= allowed and required <= keys):
                    return False
        return True
    attempt("S2.targets_categories", s2_targets_categories)

    # --- S2.build_cv_matched_wiring -------------------------------------
    def s2_build_cv_matched_wiring():
        def assoc(category, phenotype, aliases=None):
            cv = {"significance": "Pathogenic", "review_stars": 3,
                  "review_status_text": "x", "source_version": "t", "phenotype": phenotype}
            panel = _build([_target("rs1", condition="Eye color", category=category)],
                           clinvar={"rs1": cv}, aliases=aliases)
            return panel["variants"][0]["association"]
        if assoc("trait", "Unrelated disease") != "unknown":
            return False
        if assoc("trait", "Eye color") != "established":
            return False
        if assoc("trait", "iris pigmentation", {"eye color": ["iris pigmentation"]}) != "established":
            return False
        if assoc("trait", "") != "unknown":
            return False
        if assoc("carrier", "Unrelated disease") != "established":
            return False
        return True
    attempt("S2.build_cv_matched_wiring", s2_build_cv_matched_wiring)

    # --- S2.panel_sample_reproduces -------------------------------------
    def s2_panel_sample_reproduces():
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
    attempt("S2.panel_sample_reproduces", s2_panel_sample_reproduces)


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
