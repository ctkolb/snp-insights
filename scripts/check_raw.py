#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Inspect a real AncestryDNA raw file offline, with self-checks.

Run this yourself and read the output before sharing anything. It uses the same
parser and annotator as the pipeline (stage2/), so what you see here is exactly
what the pipeline sees.

    python scripts/check_raw.py /path/to/AncestryDNA.txt
    python scripts/check_raw.py /path/to/AncestryDNA.txt --json -o inspect.json

Privacy: by default the panel section reports STATES only and withholds the raw
allele letters (--no-redact to include them). The script never prints your
genome-wide genotypes, only aggregate counts and the curated panel. --no-hash
omits the file fingerprint. Nothing is uploaded by this script.
"""
import argparse
import hashlib
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "stage2"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import ancestry  # noqa: E402
import annotate  # noqa: E402

VALID_CHROM = {str(i) for i in range(1, 27)} | {"X", "Y", "PAR", "MT"}
VALID_NUC = set("ACGTID")


def structural_scan(path):
    """Stream the file and collect aggregate, non-identifying statistics."""
    s = {
        "comment_lines": 0, "header_seen": False, "row_count": 0,
        "malformed_rows": 0, "bad_position": 0,
        "no_calls": 0, "indels": 0, "het": 0,
        "chrom_counts": Counter(), "unknown_alleles": Counter(), "bad_chromosomes": Counter(),
        "duplicate_rsids": 0, "duplicate_positions": 0,
    }
    seen_rsid, seen_pos = set(), set()
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith("#"):
                s["comment_lines"] += 1
                continue
            parts = line.split("\t")
            if parts[0] == "rsid":
                s["header_seen"] = True
                continue
            if len(parts) < 5:
                s["malformed_rows"] += 1
                continue
            rsid, chrom, pos, a1, a2 = (p.strip() for p in parts[:5])
            s["row_count"] += 1
            s["chrom_counts"][chrom] += 1
            if chrom not in VALID_CHROM:
                s["bad_chromosomes"][chrom] += 1
            try:
                int(pos)
            except ValueError:
                s["bad_position"] += 1
            no_call = a1 == "0" or a2 == "0"
            if no_call:
                s["no_calls"] += 1
            else:
                if a1 != a2:
                    s["het"] += 1
                if a1 in ("I", "D") or a2 in ("I", "D"):
                    s["indels"] += 1
            for a in (a1, a2):
                if a not in VALID_NUC and a != "0":
                    s["unknown_alleles"][a] += 1
            if rsid:
                if rsid in seen_rsid:
                    s["duplicate_rsids"] += 1
                seen_rsid.add(rsid)
            key = (chrom, pos)
            if key in seen_pos:
                s["duplicate_positions"] += 1
            seen_pos.add(key)
    return s


def format_report(s, raw, findings, findings_ok, schema_msg, redact, show_hash, file_hash):
    out = []
    out.append("SNP Insights — raw file inspection")
    out.append("=" * 40)
    m = raw["meta"]
    out.append(f"array version     : {m.get('array_version')}")
    out.append(f"converter version : {m.get('converter_version')}")
    out.append(f"genome build      : {m.get('genome_build')}")
    out.append(f"strand            : {m.get('strand')}")
    out.append(f"inferred sex      : {raw.get('sex', 'n/a')}")
    if show_hash:
        out.append(f"file sha256       : {file_hash}")
    out.append("")

    out.append("Structural self-checks")
    out.append("-" * 40)
    rate = (s["no_calls"] / s["row_count"] * 100) if s["row_count"] else 0
    chrom_sum = sum(s["chrom_counts"].values())
    checks = [
        ("header row present", s["header_seen"], True),
        ("all rows have 5 columns", s["malformed_rows"] == 0, f"{s['malformed_rows']} malformed"),
        ("all positions numeric", s["bad_position"] == 0, f"{s['bad_position']} bad"),
        ("chromosomes recognized", not s["bad_chromosomes"], f"unexpected: {dict(s['bad_chromosomes'])}"),
        ("alleles in A/C/G/T/I/D/0", not s["unknown_alleles"], f"unexpected: {dict(s['unknown_alleles'])}"),
        ("no-call rate sane (<5%)", rate < 5, f"{rate:.2f}%"),
        ("chromosome counts sum to row total", chrom_sum == s["row_count"], f"{chrom_sum} vs {s['row_count']}"),
        ("build is GRCh37", m.get("genome_build") == "GRCh37", m.get("genome_build")),
    ]
    for name, ok, detail in checks:
        out.append(f"  [{'PASS' if ok else 'WARN'}] {name}: {detail}")
    out.append(f"  [info] rows: {s['row_count']}, comment lines: {s['comment_lines']}")
    out.append(f"  [info] het rate: {s['het'] / s['row_count'] * 100:.2f}%, indels (I/D): {s['indels']}")
    out.append(f"  [info] duplicate rsIDs: {s['duplicate_rsids']}, duplicate positions: {s['duplicate_positions']}")
    out.append("")

    out.append("Chromosome distribution")
    out.append("-" * 40)
    for chrom in sorted(s["chrom_counts"], key=lambda c: (len(c), c)):
        n = s["chrom_counts"][chrom]
        norm = ancestry.normalize_chromosome(chrom)
        out.append(f"  {chrom:>3} -> {norm:<4} {n}")
    out.append("")

    sex = raw.get("sex", "unknown")
    out.append("Sex inference")
    out.append("-" * 40)
    out.append(f"  inferred: {sex}")
    out.append(f"  Y calls: {s['chrom_counts'].get('24', 0)}, X calls: {s['chrom_counts'].get('23', 0)} (numeric labels)")
    out.append("")

    if findings is not None:
        out.append("Panel findings (curated variants)")
        out.append("-" * 40)
        for f in findings["findings"]:
            call = f["call"]
            zyg = call.get("zygosity", "-")
            allele = ""
            if not redact and call.get("allele1"):
                allele = f" [{call.get('allele1')}/{call.get('allele2')}]"
            cv = f["evidence"].get("clinvar")
            cv_s = f" ClinVar {cv['review_stars']}★ {cv['significance']}" if cv else ""
            out.append(f"  {f['state']:<22} {str(f['rsid'] or f['gene']):<14} {f['gene'] or '':<10} "
                       f"zyg={zyg:<11}{allele}{cv_s}")
        for c in findings.get("contradictions", []):
            out.append(f"  CONTRADICTION {c['contradiction_id']}: {c['description']}")
        out.append("")
        out.append(f"  findings schema: {schema_msg}")
    out.append("")
    out.append("End of inspection.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Inspect an AncestryDNA raw file offline.")
    ap.add_argument("raw")
    ap.add_argument("--panel", default=os.path.join(ROOT, "data", "panel.sample.json"))
    ap.add_argument("--aliases", default=os.path.join(ROOT, "data", "condition_aliases.json"))
    ap.add_argument("--no-redact", action="store_true", help="include raw allele letters in panel findings")
    ap.add_argument("--no-hash", action="store_true", help="omit the file sha256")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("-o", "--out")
    args = ap.parse_args(argv)

    if not os.path.exists(args.raw):
        print(f"error: no such file: {args.raw}", file=sys.stderr)
        return 2

    s = structural_scan(args.raw)
    raw = ancestry.parse_ancestry(args.raw)
    raw["sex"] = annotate.infer_sex(raw)
    file_hash = hashlib.sha256(open(args.raw, "rb").read()).hexdigest()

    findings = None
    findings_ok = None
    schema_msg = "not checked (no panel)"
    if args.panel and os.path.exists(args.panel):
        with open(args.panel) as fh:
            panel = json.load(fh)
        findings = annotate.build_findings(args.raw, panel, annotate.load_aliases(args.aliases))
        try:
            import jsonschema
            with open(os.path.join(ROOT, "schema", "findings.schema.json")) as fh:
                schema = json.load(fh)
            jsonschema.Draft202012Validator(schema).validate(findings)
            findings_ok, schema_msg = True, "valid"
        except ImportError:
            findings_ok, schema_msg = None, "not checked (jsonschema not installed)"
        except Exception as exc:  # noqa: BLE001
            findings_ok, schema_msg = False, f"INVALID: {exc}"

    if args.json:
        payload = {
            "meta": raw["meta"],
            "inferred_sex": raw["sex"],
            "structural": {k: (dict(v) if isinstance(v, Counter) else v) for k, v in s.items()},
            "findings_schema": schema_msg,
            "findings": None,
        }
        if args.json and findings is not None:
            disp = json.loads(json.dumps(findings))
            if not args.no_hash:
                disp["provenance"]["input_hash"] = file_hash
            else:
                disp["provenance"].pop("input_hash", None)
            if not args.no_redact:
                for f in disp["findings"]:
                    f["call"].pop("allele1", None)
                    f["call"].pop("allele2", None)
            payload["findings"] = disp
        text = json.dumps(payload, indent=2)
    else:
        text = format_report(s, raw, findings, findings_ok, schema_msg,
                             redact=not args.no_redact, show_hash=not args.no_hash, file_hash=file_hash)

    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
