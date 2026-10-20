#!/usr/bin/env python3
"""Stage 2: deterministically annotate an AncestryDNA raw file into findings.json.

    python stage2/annotate.py <raw.txt> <panel.json> [-o findings.json]

AncestryDNA raw data never leaves this stage. All confidence values, coverage
states, and contradictions are computed here; the Stage 3 narrator only cites
the result.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from caveats import CAVEAT_REGISTRY  # noqa: E402
from ancestry import parse_ancestry  # noqa: E402

PIPELINE_VERSION = "0.1.0"
NO_CALL = "0"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def finding_id(rsid, gene, chrom, pos):
    base = rsid or f"{gene}:{chrom}:{pos}"
    return "f_" + hashlib.sha256(base.encode()).hexdigest()[:12]


def rarity_class(af):
    if af is None:
        return "unknown"
    if af >= 0.05:
        return "common"
    if af >= 0.01:
        return "low_frequency"
    if af >= 0.0001:
        return "rare"
    return "ultra_rare"


def classify(alleles, ref, alt):
    """Return (zygosity, is_variant). is_variant is None when uninterpretable."""
    if ref is None or alt is None:
        return "unknown", None
    s = set(alleles)
    if s == {ref}:
        return "hom_ref", False
    if s == {alt}:
        return "hom_alt", True
    if ref in s and alt in s:
        return "het", True
    return "unknown", None


def is_no_call(a1, a2):
    return a1 == NO_CALL or a2 == NO_CALL


def infer_sex(raw):
    """Infer sex from Y calls and X heterozygosity. Returns male/female/unknown."""
    y_calls = x_calls = x_het = 0
    for r in raw["rows"].values():
        a1, a2 = r["allele1"], r["allele2"]
        if a1 == NO_CALL or a2 == NO_CALL:
            continue
        if r["chromosome"] == "Y":
            y_calls += 1
        elif r["chromosome"] == "X":
            x_calls += 1
            if a1 != a2:
                x_het += 1
    if y_calls >= 1:
        return "male"
    if x_calls >= 20:
        return "female" if (x_het / x_calls) > 0.05 else "male"
    if x_calls > 0 and x_het > 0:
        return "female"
    return "unknown"


def adjust_zygosity(zygosity, chrom, sex):
    """X/Y are haploid in males; MT is haploid (homoplasmic)."""
    if chrom == "MT":
        return "homoplasmic"
    if chrom == "Y":
        return "hemizygous" if sex == "male" else "unknown"
    if chrom == "X" and sex == "male":
        return "hemizygous"
    return zygosity


def locate(variant, raw, merges=None):
    """Return (row, covered, mapping_level, basis)."""
    merges = merges or {}
    rsid, chrom, pos = variant["rsid"], variant["chromosome"], variant["position"]
    basis = ["rsID+position agree with dbSNP snapshot", "build GRCh37 match"]
    if rsid:
        canon = merges.get(rsid, rsid)
        row = raw["rows"].get(rsid) or raw.get("by_canon", {}).get(canon)
        if row:
            if canon != rsid:
                basis = basis + [f"dbSNP merge map applied ({rsid}->{canon})"]
            if row["position"] != pos:
                return row, True, "medium", basis + ["position differs from snapshot"]
            return row, True, "high", basis
    if (chrom, pos) in raw["by_position"]:
        other = raw["by_position"][(chrom, pos)]
        return raw["rows"][other], True, "medium", ["matched by position; rsID absent from file"]
    return None, False, "high", ["panel locus (rsID+position) not present in file manifest"]


def annotate_variant(variant, raw, merges=None, sex="unknown"):
    chrom, pos = variant["chromosome"], variant["position"]
    ref, alt = variant["reference_allele"], variant["alternate_allele"]
    row, covered, level, basis = locate(variant, raw, merges)
    manifest_source = "raw file manifest"
    if raw["meta"].get("array_version"):
        manifest_source = f"AncestryDNA {raw['meta']['array_version']} file manifest"

    strand = variant.get("strand", "forward")
    if strand == "ambiguous":
        basis = basis + ["curator-flagged strand-ambiguous site"]

    if variant["assayability"] == "not_assayable":
        state = "not_assayable"
        coverage = {"state": "covered" if covered else "not_covered", "source": manifest_source}
        call = {"state": "not_applicable"}
    elif not covered:
        state = "not_covered"
        coverage = {"state": "not_covered", "source": manifest_source}
        call = {"state": "not_applicable"}
    elif is_no_call(row["allele1"], row["allele2"]):
        state = "covered_nocall"
        coverage = {"state": "covered", "source": manifest_source}
        call = {"state": "no_call", "zygosity": "unknown", "strand": strand}
    else:
        zygosity, is_variant = classify([row["allele1"], row["allele2"]], ref, alt)
        coverage = {"state": "covered", "source": manifest_source}
        if chrom == "Y" and sex == "female":
            # a Y call in an inferred female is contradictory
            state = "covered_uninterpretable"
            call = {"state": "uninterpretable", "allele1": row["allele1"], "allele2": row["allele2"],
                    "zygosity": "unknown", "strand": strand}
        else:
            zygosity = adjust_zygosity(zygosity, chrom, sex)
            call = {"state": "called", "allele1": row["allele1"], "allele2": row["allele2"],
                    "zygosity": zygosity, "strand": strand}
            if is_variant is True:
                state = "detected"
            elif is_variant is False:
                state = "covered_reference"
            else:
                state = "covered_uninterpretable"  # measured, alleles match neither ref nor alt
                call["state"] = "uninterpretable"

    sig = (variant.get("clinvar") or {}).get("significance")
    rc = rarity_class(variant.get("gnomad_af"))
    ppv = None
    if (state == "detected" and call.get("zygosity") in ("het", "hom_alt")
            and sig in ("Pathogenic", "Likely pathogenic") and rc in ("rare", "ultra_rare")):
        ppv = CAVEAT_REGISTRY["rare_ppv"]

    caveat_keys = ["array_limits"]
    if state == "not_covered":
        caveat_keys.append("not_covered")
    if state == "covered_nocall":
        caveat_keys.append("no_call")
    if state == "covered_uninterpretable":
        caveat_keys.append("uninterpretable")
    if state == "not_assayable":
        caveat_keys.append("not_assayable")
    if strand == "ambiguous":
        caveat_keys.append("strand_ambiguous")
    if ppv:
        caveat_keys.append("rare_ppv")

    return {
        "finding_id": finding_id(variant["rsid"], variant["gene"], chrom, pos),
        "rsid": variant["rsid"],
        "probe_id": None,
        "chromosome": chrom,
        "position": pos,
        "gene": variant["gene"],
        "condition": variant["condition"],
        "assayability": variant["assayability"],
        "coverage": coverage,
        "call": call,
        "confidence": {
            "annotation_mapping": {"level": level, "basis": basis},
            "array_reliability": {"rarity_class": rc, "ppv_note": ppv},
        },
        "evidence": {
            "clinvar": variant.get("clinvar"),
            "snpedia": variant.get("snpedia"),
            "association": variant.get("association") or "none",
        },
        "state": state,
        "caveats": [CAVEAT_REGISTRY[k] for k in caveat_keys],
    }


def normalize_condition(condition, aliases):
    """Map a condition label to a canonical key for grouping."""
    if not condition:
        return None
    key = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", condition.strip().lower())).strip()
    for canonical, variants in aliases.items():
        if canonical.startswith("_"):
            continue
        norm_variants = {re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", v.lower())).strip() for v in variants}
        if key == canonical or key in norm_variants:
            return canonical
    return key


def load_aliases(path):
    if path and os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return {}


def compute_contradictions(findings, aliases=None):
    aliases = aliases or {}
    groups = {}
    display = {}
    for f in findings:
        key = normalize_condition(f["condition"], aliases)
        if key:
            groups.setdefault(key, []).append(f)
            display.setdefault(key, f["condition"])
    contradictions = []
    for key, fs in groups.items():
        if len(fs) < 2:
            continue
        stars = {(f["evidence"]["clinvar"] or {}).get("review_stars") for f in fs}
        assocs = {f["evidence"]["association"] for f in fs}
        sigs = {(f["evidence"]["clinvar"] or {}).get("significance") for f in fs}
        if len(stars) > 1 or len(assocs) > 1 or len(sigs) > 1:
            parts = []
            for f in fs:
                cv = f["evidence"]["clinvar"]
                if cv:
                    parts.append(f"{f['rsid']} carries a {cv['review_stars']}-star {cv['significance'].lower()} classification")
                else:
                    parts.append(f"{f['rsid']} has no ClinVar classification")
            contradictions.append({
                "contradiction_id": "c_" + hashlib.sha256(key.encode()).hexdigest()[:12],
                "finding_ids": [f["finding_id"] for f in fs],
                "kind": "overlapping_condition_mixed_evidence",
                "description": (f"Multiple variants are reported for the same condition ({display[key]}) with "
                                f"differing evidence: " + "; ".join(parts) + ". Both are reported as-is; they are not reconciled."),
            })
    return contradictions


def build_findings(raw_path, panel, aliases=None):
    merges = panel.get("merges", {}) or {}
    raw = parse_ancestry(raw_path)
    raw["by_canon"] = {}
    for r in raw["rows"].values():
        raw["by_canon"].setdefault(merges.get(r["rsid"], r["rsid"]), r)
    sex = infer_sex(raw)
    findings = [annotate_variant(v, raw, merges, sex) for v in panel["variants"]]
    provenance = {
        "input_hash": sha256_file(raw_path),
        "array_version": raw["meta"].get("array_version") or "unknown",
        "converter_version": raw["meta"].get("converter_version"),
        "genome_build": raw["meta"].get("genome_build") or "GRCh37",
        "strand": "forward",
        "inferred_sex": sex,
        "manifest_row_count": raw["row_count"],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pipeline_version": PIPELINE_VERSION,
        "annotation_snapshots": panel.get("sources", []),
    }
    return {
        "schema_version": "1.0.0",
        "provenance": provenance,
        "findings": findings,
        "contradictions": compute_contradictions(findings, aliases),
    }


def main():
    ap = argparse.ArgumentParser(description="Annotate an AncestryDNA raw file into findings.json.")
    ap.add_argument("raw")
    ap.add_argument("panel")
    ap.add_argument("-o", "--out", help="output path (default: stdout)")
    ap.add_argument("--aliases", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "condition_aliases.json"))
    args = ap.parse_args()

    with open(args.panel) as fh:
        panel = json.load(fh)
    doc = build_findings(args.raw, panel, load_aliases(args.aliases))
    text = json.dumps(doc, indent=2)

    try:
        import jsonschema
        schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "schema", "findings.schema.json")
        with open(schema_path) as fh:
            schema = json.load(fh)
        jsonschema.Draft202012Validator(schema).validate(doc)
        print("findings.json validates against schema", file=sys.stderr)
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: findings.json failed schema validation: {exc}", file=sys.stderr)

    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
