#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
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
from references import references_for  # noqa: E402
from ancestry import parse_ancestry  # noqa: E402

PIPELINE_VERSION = "0.1.0"
NO_CALL = "0"

# Letters an assayability class can report; anything else cannot be interpreted.
ALPHABET = {"snp": frozenset("ACGT"), "indel": frozenset("ID")}
# Letters the findings schema allows in call.allele1/allele2.
SCHEMA_ALLELES = frozenset("ACGTID")
SUPPORTED_BUILD = "GRCh37"
BUILD_REFUSED_MESSAGE = ("error: genome build refused: only GRCh37 is supported and the raw file's "
                         "stated build must match the panel build; no output was written")


class BuildRefused(Exception):
    """The raw file's build, or the panel's, is not the supported one.

    Deliberately carries no detail: the message is fixed so nothing from the
    user's file can reach an error stream.
    """


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


def release_rarity_class(variant, af):
    """Rarity for a release-format variant, from the effect allele's frequency.

    gnomad_af when the effect allele is the panel alternate allele; 1 - gnomad_af
    when it is the reference allele (a documented approximation when other rare
    alternates exist); "unknown" otherwise (another alternate, an indel I/D, or
    no frequency at all). Legacy variants use `rarity_class` on the raw value.
    """
    effect = variant.get("effect_allele")
    if af is None or not effect:
        return "unknown"
    if variant.get("assayability") == "indel" or effect in ("I", "D"):
        return "unknown"
    if effect == variant.get("alternate_allele"):
        return rarity_class(af)
    if effect == variant.get("reference_allele"):
        return rarity_class(1 - af)
    return "unknown"


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


def classify_effect(alleles, effect, ref, alt, assayability, alternate_alleles=None):
    """Return (zygosity, is_variant) for an entry curated by its effect allele.

    is_variant is None when the call cannot be interpreted: a letter outside the
    assayability alphabet, a letter outside the declared allele set, or no
    effect allele and no declared non-effect allele to call it reference by.
    Indels are biallelic (I/D), so their non-effect allele is the other letter
    and the sequence alternate list is ignored; for a SNP the declared set is
    {ref} plus every alternate allele (the singular `alt` plus the complete
    `alternate_alleles` list, so a present-but-empty list falls back to `alt`)
    plus the effect allele.
    """
    alphabet = ALPHABET.get(assayability, ALPHABET["snp"])
    if effect not in alphabet or any(a not in alphabet for a in alleles):
        return "unknown", None
    if assayability == "indel":
        declared = alphabet
        non_effect = alphabet - {effect}
    else:
        extra = [alternate_alleles] if isinstance(alternate_alleles, str) else list(alternate_alleles or ())
        declared = {a for a in (ref, alt) if a} | set(extra) | {effect}
        non_effect = declared - {effect}
        if non_effect and any(a not in declared for a in alleles):
            return "unknown", None
    if effect in alleles:
        return ("hom_alt" if alleles[0] == alleles[1] else "het"), True
    if non_effect and all(a in non_effect for a in alleles):
        return "hom_ref", False
    return "unknown", None


def uninterpretable_alleles(a1, a2):
    """The call's allele fields for an uninterpretable call: both letters, or neither.

    Raw letters outside the schema's allele enum are never echoed into the document.
    """
    if a1 in SCHEMA_ALLELES and a2 in SCHEMA_ALLELES:
        return {"allele1": a1, "allele2": a2}
    return {}


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


def build_basis_note(raw, panel_build=SUPPORTED_BUILD):
    """Say what was checked about the build: a stated match, or an assumption."""
    if raw["meta"].get("genome_build"):
        return f"file build {raw['meta']['genome_build']} matches panel build {panel_build}"
    return f"build not stated in file; assumed to match panel build {panel_build}"


def locate(variant, raw, merges=None, panel_build=SUPPORTED_BUILD):
    """Return (row, covered, mapping_level, basis)."""
    merges = merges or {}
    rsid, chrom, pos = variant["rsid"], variant["chromosome"], variant["position"]
    other_chromosome = []
    if rsid:
        canon = merges.get(rsid, rsid)
        row = raw["rows"].get(rsid) or raw.get("by_canon", {}).get(canon)
        if row and row["chromosome"] != chrom:
            # the same rsID on another chromosome is not this locus
            other_chromosome = ["rsID present in file on a different chromosome; not matched"]
        elif row:
            same_position = row["position"] == pos
            agreed = "rsID, chromosome and position" if same_position else "rsID and chromosome"
            basis = [f"{agreed} agree with dbSNP snapshot", build_basis_note(raw, panel_build)]
            if canon != rsid:
                basis = basis + [f"dbSNP merge map applied ({rsid}->{canon})"]
            if not same_position:
                return row, True, "medium", basis + ["position differs from snapshot"]
            return row, True, "high", basis
    if (chrom, pos) in raw["by_position"]:
        other = raw["by_position"][(chrom, pos)]
        return (raw["rows"][other], True, "medium",
                other_chromosome + ["matched by position; rsID absent from file"])
    return (None, False, "high",
            other_chromosome + ["panel locus (rsID+position) not present in file manifest"])


def annotate_variant(variant, raw, merges=None, sex="unknown", panel_build=SUPPORTED_BUILD,
                     release_format=False):
    chrom, pos = variant["chromosome"], variant["position"]
    ref, alt = variant["reference_allele"], variant["alternate_allele"]
    row, covered, level, basis = locate(variant, raw, merges, panel_build)
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
    elif row["rsid"] in raw.get("conflicting_rsids", ()):
        # repeated rows for this rsID disagree: no one genotype can be reported
        basis = basis + ["conflicting duplicate rows for this rsID in the file"]
        state = "covered_uninterpretable"
        coverage = {"state": "covered", "source": manifest_source}
        call = {"state": "uninterpretable", "zygosity": "unknown", "strand": strand}
    elif is_no_call(row["allele1"], row["allele2"]):
        state = "covered_nocall"
        coverage = {"state": "covered", "source": manifest_source}
        call = {"state": "no_call", "zygosity": "unknown", "strand": strand}
    else:
        alleles = [row["allele1"], row["allele2"]]
        effect = variant.get("effect_allele")
        if effect:
            # Detection is keyed on the curated effect allele, not dbSNP's alt
            # (which is assembly-oriented and can be the common allele). Zygosity
            # is relative to the effect allele: hom_ref = no effect copies, and
            # only when every called allele is a declared non-effect allele.
            zygosity, is_variant = classify_effect(alleles, effect, ref, alt, variant["assayability"],
                                                   variant.get("alternate_alleles"))
        else:
            zygosity, is_variant = classify(alleles, ref, alt)
        coverage = {"state": "covered", "source": manifest_source}
        if chrom == "Y" and sex == "female":
            # a Y call in an inferred female is contradictory
            state = "covered_uninterpretable"
            call = {"state": "uninterpretable", **uninterpretable_alleles(row["allele1"], row["allele2"]),
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
                call = {"state": "uninterpretable", **uninterpretable_alleles(row["allele1"], row["allele2"]),
                        "zygosity": zygosity, "strand": strand}

    sig = (variant.get("clinvar") or {}).get("significance")
    af = variant.get("gnomad_af")
    # Release format (ticket 2E): a variant that carries result_type derives its
    # rarity from the effect allele's frequency; legacy variants keep today's
    # rarity (rarity_class of the raw gnomad_af).
    if "result_type" in variant:
        rc = release_rarity_class(variant, af)
    else:
        rc = rarity_class(af)
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

    finding = {
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
        "references": references_for(variant["rsid"], variant["gene"], variant["condition"],
                                     chrom, pos, ref, alt, variant["assayability"]),
    }
    # Release format (ticket 2D): copy the curated report fields the panel
    # variant carries. Absent in the panel -> absent in the finding (no null, no
    # default); legacy panels carry none of them, so their output is unchanged.
    if release_format:
        for key in ("result_type", "effect_allele", "cls"):
            value = variant.get(key)
            if value:
                finding[key] = value
    return finding


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


def check_builds(panel, raw):
    """Refuse (BuildRefused) unless the panel is GRCh37 and any stated file build matches it.

    Returns (panel_build, input_build, build_basis).
    """
    panel_build = panel.get("genome_build") or SUPPORTED_BUILD
    file_build = raw["meta"].get("genome_build")
    if panel_build != SUPPORTED_BUILD or (file_build and file_build != panel_build):
        raise BuildRefused()
    if file_build:
        return panel_build, file_build, "file_statement"
    return panel_build, "unknown", "not_stated"


def build_findings(raw_path, panel, aliases=None):
    merges = panel.get("merges", {}) or {}
    raw = parse_ancestry(raw_path)
    panel_build, input_build, build_basis = check_builds(panel, raw)
    raw["by_canon"] = {}
    for r in raw["rows"].values():
        raw["by_canon"].setdefault(merges.get(r["rsid"], r["rsid"]), r)
    sex = infer_sex(raw)
    # Ticket 2D: a panel is in release format when any variant carries
    # result_type. Release documents are schema_version 1.2.0 and copy the
    # curated report fields; legacy panels stay 1.1.0 and byte-identical.
    release_format = any("result_type" in v for v in panel["variants"])
    findings = [annotate_variant(v, raw, merges, sex, panel_build, release_format)
                for v in panel["variants"]]
    provenance = {
        "input_hash": sha256_file(raw_path),
        "array_version": raw["meta"].get("array_version") or "unknown",
        "converter_version": raw["meta"].get("converter_version"),
        "genome_build": panel_build,
        "input_build": input_build,
        "build_basis": build_basis,
        "strand": "forward",
        "inferred_sex": sex,
        "manifest_row_count": raw["row_count"],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pipeline_version": PIPELINE_VERSION,
        "annotation_snapshots": panel.get("sources", []),
    }
    return {
        "schema_version": "1.2.0" if release_format else "1.1.0",
        "provenance": provenance,
        "findings": findings,
        "contradictions": compute_contradictions(findings, aliases),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Annotate an AncestryDNA raw file into findings.json.")
    ap.add_argument("raw")
    ap.add_argument("panel")
    ap.add_argument("-o", "--out", help="output path (default: stdout)")
    ap.add_argument("--aliases", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "condition_aliases.json"))
    args = ap.parse_args(argv)

    with open(args.panel) as fh:
        panel = json.load(fh)
    try:
        doc = build_findings(args.raw, panel, load_aliases(args.aliases))
    except BuildRefused:
        print(BUILD_REFUSED_MESSAGE, file=sys.stderr)
        return 2
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
