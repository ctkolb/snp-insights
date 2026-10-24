# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""ETL: build an enriched panel snapshot from curated targets + public sources.

Curation (which variants to report, and their gene/condition) lives in the
targets file. Coordinates/alleles come from dbSNP, evidence from ClinVar and
gnomAD, trait evidence from GWAS Catalog, and an optional SNPedia signal. All
joins happen at build time, so Stage 2 needs no network.

    python tools/build_panel.py \
        --targets data/targets.sample.json \
        --clinvar fixtures/sources/clinvar.sample.tsv \
        --gnomad  fixtures/sources/gnomad.sample.vcf \
        -o data/panel.sample.json

With --dbsnp, targets need not carry coordinates/alleles at all:

    python tools/build_panel.py --targets data/targets.traits.json \
        --dbsnp dbsnp.vcf.gz --gwas gwas.tsv --clinvar variant_summary.txt.gz \
        -o data/panel.traits.json

Association strength (option C) is taken from the target when given, otherwise
derived: ClinVar review stars for medical findings, GWAS study count for traits.

Real inputs (see README for current URLs):
    ClinVar  variant_summary.txt.gz          (GRCh37 rows)
    gnomAD   exomes/genomes VCF (GRCh37)
    dbSNP    GRCh37 VCF (GCF_000001405.25) or a normalized TSV
    dbSNP    RsMergeArch (old->new rsID map)
    GWAS     associations TSV
    SNPedia  rsid<TAB>magnitude
"""
import argparse
import gzip
import json
import os
import sys
from collections import defaultdict

import evidence


def open_any(path):
    # utf-8-sig strips a leading byte-order mark so the first header name is
    # never corrupted; it is a no-op for files without a BOM.
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8-sig")
    return open(path, encoding="utf-8-sig")


def norm(name):
    return name.strip().lower()


def normalize_chromosome(value):
    v = (value or "").strip()
    if v.lower().startswith("chr"):
        v = v[3:]
    return {"23": "X", "24": "Y", "25": "PAR", "26": "MT", "M": "MT"}.get(v, v)


# Star/significance/condition logic lives in tools/evidence.py. The public names
# are the same objects there, so identity holds across the modules.
review_stars = evidence.review_stars
norm_cond = evidence.norm_cond
condition_matches = evidence.condition_matches
sig_rank = evidence.sig_rank


def _col(row, idx, *names):
    for n in names:
        i = idx.get(norm(n))
        if i is not None and i < len(row):
            return row[i]
    return ""


def load_clinvar(path, release, conditions=None, aliases=None):
    """Return {rsid: {significance, review_stars, review_status_text,
    source_version, phenotype}}.

    Keeps every GRCh37 row per rsID and picks one with evidence.select_clinvar,
    using conditions[rsid] (a {rsid: condition} map) when given. Old files with
    no PhenotypeList column still load (phenotype "").
    """
    if aliases is None:
        aliases = evidence.load_aliases()
    conditions = conditions or {}
    rows_by_rsid = defaultdict(list)
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
            rows_by_rsid[rsid].append({
                "sig": _col(row, idx, "ClinicalSignificance", "Clinical Significance"),
                "review": status,
                "phenotype": _col(row, idx, "PhenotypeList"),
            })
    out = {}
    for rsid, rows in rows_by_rsid.items():
        best = evidence.select_clinvar(rows, conditions.get(rsid), aliases)
        if not best:
            continue
        out[rsid] = {
            "significance": best["sig"],
            "review_stars": evidence.review_stars(best["review"]),
            "review_status_text": best["review"],
            "source_version": f"ClinVar {release}",
            "phenotype": best.get("phenotype") or "",
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
            vid, alt = parts[2], parts[4]
            if vid in (".", "") or alt in (".", ""):
                continue
            out[vid] = {"af": parse_af(parts[7])}
    return out


def load_merges(path, direction="high-to-low"):
    """Parse dbSNP RsMergeArch into {old_rsid: new_rsid}."""
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


def load_dbsnp(path, wanted):
    """Return {rsid: {chromosome, position, reference_allele, alternate_allele}}.

    Accepts a dbSNP VCF (GRCh37) or a normalized TSV. Only rsIDs in `wanted`
    are retained, so a multi-GB VCF can be streamed cheaply.
    """
    out = {}
    vcf = ".vcf" in path
    with open_any(path) as fh:
        first = fh.readline()
        if vcf:
            for line in _vcf_lines(first, fh):
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 5:
                    continue
                chrom, pos, ids, ref, alt = parts[0], parts[1], parts[2], parts[3], parts[4]
                if ids in (".", ""):
                    continue
                for rid in ids.split(";"):
                    if rid in wanted:
                        out[rid] = {"chromosome": normalize_chromosome(chrom), "position": int(pos),
                                    "reference_allele": ref, "alternate_allele": alt.split(",")[0]}
        else:
            header = first.rstrip("\n").lstrip("#").split("\t")
            idx = {norm(n): i for i, n in enumerate(header)}
            for line in fh:
                if not line.strip() or line.startswith("#"):
                    continue
                row = line.rstrip("\n").split("\t")
                rsid = _col(row, idx, "rsid", "rs#", "id")
                if not rsid or (wanted and rsid not in wanted):
                    continue
                pos = _col(row, idx, "position", "pos")
                out[rsid] = {
                    "chromosome": normalize_chromosome(_col(row, idx, "chromosome", "chrom", "chr")),
                    "position": int(pos) if pos.isdigit() else None,
                    "reference_allele": _col(row, idx, "reference_allele", "ref"),
                    "alternate_allele": _col(row, idx, "alternate_allele", "alt"),
                }
    return out


def _vcf_lines(first, fh):
    if first.startswith("#"):
        yield from fh
    else:
        yield first
        yield from fh


GWAS_SNP_COLS = ("SNPS", "SNP", "SNP_ID_CURRENT", "SNP_ID")
GWAS_STUDY_COLS = ("PUBMEDID", "STUDY ACCESSION", "STUDY_ID")


def load_gwas(path, wanted):
    """Return {rsid: distinct_study_count} from a GWAS Catalog associations TSV."""
    studies = defaultdict(set)
    with open_any(path) as fh:
        header = fh.readline().rstrip("\n").lstrip("#").split("\t")
        idx = {norm(n): i for i, n in enumerate(header)}
        for rownum, line in enumerate(fh):
            if not line.strip():
                continue
            row = line.rstrip("\n").split("\t")
            snps = _col(row, idx, *GWAS_SNP_COLS)
            if not snps:
                continue
            study = _col(row, idx, *GWAS_STUDY_COLS) or f"row{rownum}"
            for rsid in (s.strip() for s in snps.replace(";", " ").replace(" x ", " ").split()):
                if rsid and (not wanted or rsid in wanted):
                    studies[rsid].add(study)
    return {rsid: len(s) for rsid, s in studies.items()}


def load_gwas_studies(path, wanted):
    """Return {rsid: [(study_id, trait_text), ...]}.

    Deduplicated on the pair, in file order. The trait comes from the
    DISEASE/TRAIT column (case-insensitive; "" when absent); the study id uses
    the existing GWAS_STUDY_COLS fallback.
    """
    out = {}
    seen = defaultdict(set)
    with open_any(path) as fh:
        header = fh.readline().rstrip("\n").lstrip("#").split("\t")
        idx = {norm(n): i for i, n in enumerate(header)}
        for rownum, line in enumerate(fh):
            if not line.strip():
                continue
            row = line.rstrip("\n").split("\t")
            snps = _col(row, idx, *GWAS_SNP_COLS)
            if not snps:
                continue
            study = _col(row, idx, *GWAS_STUDY_COLS) or f"row{rownum}"
            trait = _col(row, idx, "DISEASE/TRAIT")
            for rsid in (s.strip() for s in snps.replace(";", " ").replace(" x ", " ").split()):
                if rsid and (not wanted or rsid in wanted):
                    pair = (study, trait)
                    if pair not in seen[rsid]:
                        seen[rsid].add(pair)
                        out.setdefault(rsid, []).append(pair)
    return out


def load_snpedia(path):
    """Return {rsid: {"magnitude": m}}. Accepts TSV (rsid<TAB>magnitude) or JSON."""
    out = {}
    if path.endswith(".json"):
        with open(path) as fh:
            obj = json.load(fh)
        for rsid, val in obj.items():
            if rsid.startswith("_"):
                continue
            mag = val.get("magnitude") if isinstance(val, dict) else val
            out[rsid] = {"magnitude": mag}
        return out
    with open_any(path) as fh:
        for line in fh:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            try:
                mag = int(float(parts[1]))
            except ValueError:
                continue
            out[parts[0].strip()] = {"magnitude": mag}
    return out


def assoc_from_clinvar(cv):
    """Thin wrapper over evidence.clinvar_tier taking a ClinVar record dict."""
    if not cv:
        return None
    return evidence.clinvar_tier(cv.get("significance"), cv.get("review_stars"))


def assoc_from_gwas(n):
    """Thin wrapper over evidence.gwas_tier."""
    return evidence.gwas_tier(n)


def build(targets, sources, clinvar=None, gnomad=None, dbsnp=None, gwas=None, snpedia=None, merges=None, aliases=None):
    clinvar = clinvar or {}
    gnomad = gnomad or {}
    gwas = gwas or {}
    snpedia = snpedia or {}
    merges = merges or {}
    variants = []
    for t in targets["variants"]:
        v = dict(t)
        rsid = t.get("rsid")
        canon = merges.get(rsid, rsid) if rsid else None

        if dbsnp is not None:
            rec = dbsnp.get(rsid) or (dbsnp.get(canon) if canon else None)
            v["chromosome"] = rec["chromosome"] if rec else None
            v["position"] = rec["position"] if rec else None
            v["reference_allele"] = rec["reference_allele"] if rec else None
            v["alternate_allele"] = rec["alternate_allele"] if rec else None

        cv = clinvar.get(rsid) if rsid else None
        v["gnomad_af"] = gnomad.get(rsid, {}).get("af") if rsid else None
        v["clinvar"] = (
            {k: cv[k] for k in ("significance", "review_stars", "review_status_text", "source_version")}
            if cv else None
        )
        v["snpedia"] = snpedia.get(rsid) if (rsid and snpedia) else None

        effect = v.get("effect_allele")
        ref, alt = v.get("reference_allele"), v.get("alternate_allele")
        if effect and effect not in ("I", "D") and ref and alt and effect not in (ref, alt):
            print(f"  warning: {rsid}: effect_allele {effect!r} not in ref/alt ({ref}/{alt}); "
                  f"possible strand mismatch", file=sys.stderr)

        assoc = t.get("association")
        if not assoc:
            # gwas is either {rsid: int} (legacy, used as is) or
            # {rsid: [(study, trait)]}; the pair form counts matching studies.
            g = gwas.get(rsid) if rsid else None
            if isinstance(g, list):
                n = evidence.count_matching_studies(g, t.get("condition"), aliases)
            else:
                n = g
            # 'none' means assessed with no known link; 'unknown' means not assessed.
            assoc = assoc_from_clinvar(v["clinvar"]) or assoc_from_gwas(n) or "unknown"
        v["association"] = assoc
        variants.append(v)

    return {
        "panel_version": targets.get("panel_version", "0.1.0"),
        "genome_build": targets.get("genome_build", "GRCh37"),
        "strand": targets.get("strand", "forward"),
        "sources": sources,
        "merges": merges,
        "variants": variants,
    }


def main():
    ap = argparse.ArgumentParser(description="Build an enriched panel snapshot.")
    ap.add_argument("--targets", required=True)
    ap.add_argument("--clinvar")
    ap.add_argument("--gnomad")
    ap.add_argument("--dbsnp", help="dbSNP VCF (GRCh37) or normalized TSV; fills coordinates/alleles")
    ap.add_argument("--gwas", help="GWAS Catalog associations TSV; drives trait association tier")
    ap.add_argument("--snpedia", help="rsid<TAB>magnitude, or JSON; optional")
    ap.add_argument("--dbsnp-merge", help="dbSNP RsMergeArch file (old->new rsID map)")
    ap.add_argument("--cache", help="directory from fetch_reference.py; fills unset source paths")
    ap.add_argument("--merge-direction", choices=["high-to-low", "low-to-high"], default="high-to-low")
    ap.add_argument("--dbsnp-release", default="b156")
    ap.add_argument("--clinvar-release", default="2026-09")
    ap.add_argument("--gnomad-release", default="v4.0")
    ap.add_argument("--gwas-release", default="2026-10")
    ap.add_argument("--snpedia-release", default="2026-10")
    ap.add_argument("--retrieved-at", default="2026-10-01T00:00:00Z")
    ap.add_argument("-o", "--out", help="output path (default: stdout)")
    args = ap.parse_args()

    with open(args.targets) as fh:
        targets = json.load(fh)

    if args.cache:
        def resolve(explicit, *names):
            if explicit:
                return explicit
            for n in names:
                p = os.path.join(args.cache, n)
                if os.path.exists(p):
                    return p
            return None
        args.clinvar = resolve(args.clinvar, "clinvar.tsv", "variant_summary.txt.gz")
        args.dbsnp = resolve(args.dbsnp, "dbsnp.tsv", "GCF_000001405.25.gz")
        args.gnomad = resolve(args.gnomad, "gnomad.small.vcf", "gnomad.exomes.r2.1.1.sites.vcf.bgz")
        args.gwas = resolve(args.gwas, "gwas.tsv", "gwas-catalog-download-associations-alt-full.tsv")
        args.snpedia = resolve(args.snpedia, "snpedia.tsv")
        args.dbsnp_merge = resolve(args.dbsnp_merge, "RsMergeArch.bcp.gz")

    merges = load_merges(args.dbsnp_merge, args.merge_direction) if args.dbsnp_merge else {}
    wanted = {v["rsid"] for v in targets["variants"] if v.get("rsid")} | set(merges.values())
    aliases = evidence.load_aliases()
    conditions = {v["rsid"]: v.get("condition") for v in targets["variants"] if v.get("rsid")}

    clinvar = load_clinvar(args.clinvar, args.clinvar_release,
                           conditions=conditions, aliases=aliases) if args.clinvar else {}
    gnomad = load_gnomad(args.gnomad) if args.gnomad else {}
    dbsnp = load_dbsnp(args.dbsnp, wanted) if args.dbsnp else None
    gwas = load_gwas_studies(args.gwas, wanted) if args.gwas else {}
    snpedia = load_snpedia(args.snpedia) if args.snpedia else {}

    def snap(source, release, license_):
        return {"source": source, "release": release, "retrieved_at": args.retrieved_at, "license": license_}

    sources = [snap("dbSNP", args.dbsnp_release, "public domain (NCBI)")]
    if args.dbsnp_merge:
        sources.append(snap("dbSNP RsMergeArch", args.dbsnp_release, "public domain (NCBI)"))
    sources.append(snap("ClinVar", args.clinvar_release, "public domain (NCBI)"))
    sources.append(snap("gnomAD", args.gnomad_release, "free (Broad)"))
    if args.gwas:
        sources.append(snap("GWAS Catalog", args.gwas_release, "free (EMBL-EBI)"))
    if args.snpedia:
        sources.append(snap("SNPedia", args.snpedia_release, "CC BY-NC-SA 3.0"))

    panel = build(targets, sources, clinvar=clinvar, gnomad=gnomad, dbsnp=dbsnp,
                  gwas=gwas, snpedia=snpedia, merges=merges, aliases=aliases)
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
