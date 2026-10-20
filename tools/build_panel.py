#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""ETL: build an enriched panel snapshot from curated targets + public sources.

    python tools/build_panel.py \
        --targets data/targets.sample.json \
        --clinvar fixtures/sources/clinvar.sample.tsv \
        --gnomad  fixtures/sources/gnomad.sample.vcf \
        -o data/panel.sample.json

Curation (which variants to report, their gene/condition/alleles) lives in the
targets file. Evidence (ClinVar significance + review stars, gnomAD frequency)
is joined in here, at build time, so Stage 2 needs no network. Source files may
be plain or gzip-compressed.

Column and INFO field names are matched case-insensitively and with several
aliases, to tolerate differences between ClinVar releases and gnomAD files.

Real inputs:
    ClinVar  https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz
    gnomAD   https://gnomad.broadinstitute.org/downloads (VCF, GRCh37)
"""
import argparse
import gzip
import json
import sys


def open_any(path):
    return gzip.open(path, "rt") if path.endswith(".gz") else open(path)


def norm(name):
    return name.strip().lower()


def review_stars(status):
    """Map a ClinVar review-status string to the 0-4 star scale."""
    s = (status or "").lower()
    if "practice guideline" in s:
        return 4
    if "expert panel" in s:
        return 3
    if "multiple submitters" in s and "no conflict" in s:
        return 2
    if "conflicting" in s:
        return 1
    if "single submitter" in s:
        return 1
    if "no assertion criteria" in s or not s:
        return 0
    return None


def _col(row, idx, *names):
    for n in names:
        i = idx.get(norm(n))
        if i is not None and i < len(row):
            return row[i]
    return ""


def load_clinvar(path, release):
    out = {}
    with open_any(path) as fh:
        header = fh.readline().rstrip("\n").lstrip("#").split("\t")
        idx = {norm(name): i for i, name in enumerate(header)}
        for line in fh:
            if not line.strip() or line.startswith("#"):
                continue
            row = line.rstrip("\n").split("\t")
            rs = _col(row, idx, "RS# (dbSNP)", "RS#(dbSNP)", "RS#")
            if not rs or rs in ("-1", "."):
                continue
            rsid = rs if rs.startswith("rs") else f"rs{rs}"
            assembly = _col(row, idx, "Assembly")
            if assembly and not assembly.startswith("GRCh37"):
                continue
            status = _col(row, idx, "ReviewStatus", "Review Status")
            out[rsid] = {
                "significance": _col(row, idx, "ClinicalSignificance", "Clinical Significance"),
                "review_stars": review_stars(status),
                "review_status_text": status,
                "source_version": f"ClinVar {release}",
                "position": _col(row, idx, "Start"),
                "ref": _col(row, idx, "ReferenceAllele", "ReferenceAlleleVCF"),
                "alt": _col(row, idx, "AlternateAllele", "AlternateAlleleVCF"),
            }
    return out


def parse_af(info):
    for kv in info.split(";"):
        if kv.startswith("AF=") or kv.startswith("AF:"):
            val = kv.split("=", 1)[-1] if "=" in kv else kv.split(":", 1)[-1]
            val = val.split(",")[0]
            try:
                return float(val)
            except ValueError:
                return None
    return None


def load_gnomad(path):
    out = {}
    with open_any(path) as fh:
        for line in fh:
            if line.startswith("##") or line.startswith("#CHROM"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 8:
                continue
            pos, vid, alt, info = parts[1], parts[2], parts[4], parts[7]
            if vid in (".", "") or alt in (".", ""):
                continue
            out[vid] = {"af": parse_af(info), "position": pos}
    return out


def load_merges(path, direction="high-to-low"):
    """Parse dbSNP RsMergeArch into {old_rsid: new_rsid}.

    RsMergeArch is tab-delimited with rsHigh then rsLow. The common dbSNP
    convention is that the retired (higher) rsID was merged into the surviving
    (lower) one, i.e. rsHigh -> rsLow; verify against your build and use
    --merge-direction to override if needed.
    """
    merges = {}
    with open_any(path) as fh:
        for line in fh:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            a, b = parts[0].strip(), parts[1].strip()
            try:
                a, b = int(a), int(b)
            except ValueError:
                continue
            old, new = (a, b) if direction == "high-to-low" else (b, a)
            merges[f"rs{old}"] = f"rs{new}"
    return merges


def build(targets, clinvar, gnomad, sources, merges=None):
    variants = []
    for t in targets["variants"]:
        v = dict(t)
        rsid = t.get("rsid")
        cv = clinvar.get(rsid) if rsid else None
        v["gnomad_af"] = gnomad.get(rsid, {}).get("af") if rsid else None
        v["clinvar"] = (
            {k: cv[k] for k in ("significance", "review_stars", "review_status_text", "source_version")}
            if cv else None
        )
        v["snpedia"] = None
        variants.append(v)
    return {
        "panel_version": targets.get("panel_version", "0.1.0"),
        "genome_build": targets.get("genome_build", "GRCh37"),
        "strand": targets.get("strand", "forward"),
        "sources": sources,
        "merges": merges or {},
        "variants": variants,
    }


def main():
    ap = argparse.ArgumentParser(description="Build an enriched panel snapshot.")
    ap.add_argument("--targets", required=True)
    ap.add_argument("--clinvar")
    ap.add_argument("--gnomad")
    ap.add_argument("--dbsnp-merge", help="dbSNP RsMergeArch file (old->new rsID map)")
    ap.add_argument("--merge-direction", choices=["high-to-low", "low-to-high"], default="high-to-low")
    ap.add_argument("--dbsnp-release", default="b156")
    ap.add_argument("--clinvar-release", default="2026-09")
    ap.add_argument("--gnomad-release", default="v4.0")
    ap.add_argument("--retrieved-at", default="2026-10-01T00:00:00Z")
    ap.add_argument("-o", "--out", help="output path (default: stdout)")
    args = ap.parse_args()

    with open(args.targets) as fh:
        targets = json.load(fh)
    clinvar = load_clinvar(args.clinvar, args.clinvar_release) if args.clinvar else {}
    gnomad = load_gnomad(args.gnomad) if args.gnomad else {}
    merges = load_merges(args.dbsnp_merge, args.merge_direction) if args.dbsnp_merge else {}

    sources = [
        {"source": "dbSNP", "release": args.dbsnp_release, "retrieved_at": args.retrieved_at, "license": "public domain (NCBI)"},
    ]
    if args.dbsnp_merge:
        sources.append({"source": "dbSNP RsMergeArch", "release": args.dbsnp_release, "retrieved_at": args.retrieved_at, "license": "public domain (NCBI)"})
    sources += [
        {"source": "ClinVar", "release": args.clinvar_release, "retrieved_at": args.retrieved_at, "license": "public domain (NCBI)"},
        {"source": "gnomAD", "release": args.gnomad_release, "retrieved_at": args.retrieved_at, "license": "free (Broad)"},
    ]
    panel = build(targets, clinvar, gnomad, sources, merges)
    text = json.dumps(panel, indent=2)

    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
