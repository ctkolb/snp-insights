# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Parse AncestryDNA raw data files (five-column TSV, GRCh37, forward strand).

Handles the conventions that break naive parsers:
  - numeric chromosomes: 23=X, 24=Y, 25=PAR, 26=MT
  - no-calls represented as "0"
  - alleles split across two columns
  - a repeated rsID keeps the last row; rsIDs whose repeated rows disagree are
    reported in "conflicting_rsids"
"""
import re

NUMERIC_CHROMOSOME = {"23": "X", "24": "Y", "25": "PAR", "26": "MT"}
BUILD_RE = re.compile(r"build\s+([0-9]+(?:\.[0-9]+)?)")
BUILD_MAP = {"37": "GRCh37", "37.1": "GRCh37", "38": "GRCh38"}


def normalize_chromosome(value):
    v = value.strip()
    return NUMERIC_CHROMOSOME.get(v, v)


def _identity(row):
    """What a repeated rsID row must agree on: locus and genotype, allele order aside."""
    return (row["chromosome"], row["position"], tuple(sorted((row["allele1"], row["allele2"]))))


def parse_ancestry(path):
    meta = {"array_version": None, "converter_version": None, "genome_build": None, "strand": "forward"}
    rows = {}
    by_position = {}
    conflicting = set()
    row_count = 0
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith("#"):
                if "array version:" in line:
                    meta["array_version"] = line.split("array version:", 1)[1].strip()
                elif "converter version:" in line:
                    meta["converter_version"] = line.split("converter version:", 1)[1].strip()
                m = BUILD_RE.search(line)
                if m:
                    meta["genome_build"] = BUILD_MAP.get(m.group(1), "GRCh" + m.group(1))
                continue
            parts = line.split("\t")
            if parts[0] == "rsid" or len(parts) < 5:
                continue
            rsid, chrom, pos, a1, a2 = (p.strip() for p in parts[:5])
            chrom = normalize_chromosome(chrom)
            try:
                pos = int(pos)
            except ValueError:
                continue
            row = {"rsid": rsid, "chromosome": chrom, "position": pos, "allele1": a1, "allele2": a2}
            earlier = rows.get(rsid)
            if earlier is not None and _identity(earlier) != _identity(row):
                conflicting.add(rsid)
            rows[rsid] = row
            by_position[(chrom, pos)] = rsid
            row_count += 1
    return {"meta": meta, "rows": rows, "by_position": by_position, "row_count": row_count,
            "conflicting_rsids": conflicting}
