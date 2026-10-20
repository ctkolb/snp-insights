#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Render a validated report IR to Markdown.

Usage:
    python tools/render_report.py <findings.json> <report_ir.json> [-o out.md] [--force]

The renderer is deterministic and authors no prose of its own: claim text comes
from the IR, caveat text from the registry, and provenance/contradiction text
from findings.json. By default it refuses to render an IR that fails validation.
"""
import argparse
import json
import sys

from caveats import CAVEAT_REGISTRY, STANDING_NOTICE
import validate_report


def render(findings, report):
    p = findings["provenance"]
    contra_by_id = {c["contradiction_id"]: c for c in findings["contradictions"]}

    lines = ["# Genetic findings report", ""]
    lines += [f"> {STANDING_NOTICE}", ""]

    lines += ["## Provenance", ""]
    lines.append(f"- Input hash: `{p['input_hash']}`")
    lines.append(f"- Array: {p['array_version']} (converter {p.get('converter_version') or 'n/a'})")
    lines.append(f"- Build: {p['genome_build']}, strand: {p['strand']}")
    if p.get("inferred_sex"):
        lines.append(f"- Inferred sex: {p['inferred_sex']}")
    lines.append(f"- Manifest rows: {p['manifest_row_count']}")
    lines.append(f"- Pipeline: {p['pipeline_version']}, generated {p['generated_at']}")
    lines.append("- Annotation snapshots:")
    for s in p["annotation_snapshots"]:
        lines.append(f"  - {s['source']} {s['release']} ({s['license']}), retrieved {s['retrieved_at']}")
    lines.append("")

    for sec in report["sections"]:
        lines += [f"## {sec['title']}", ""]
        for claim in sec["claims"]:
            cites = " ".join(f"[{c['finding_id']} · {c['field_path']}]" for c in claim["citations"])
            lines.append(f"- {claim['text']} {cites}")
        if sec.get("contradiction_ids"):
            lines += ["", "**Contradictions reported (not reconciled):**"]
            for cid in sec["contradiction_ids"]:
                c = contra_by_id.get(cid)
                if c:
                    lines.append(f"> {c['description']} _({cid})_")
        lines += ["", "**Caveats**"]
        for cid in sec["caveat_ids"]:
            lines.append(f"- {CAVEAT_REGISTRY.get(cid, cid)}")
        lines.append("")

    omissions = report.get("omitted_findings", [])
    if omissions:
        lines += ["## Findings intentionally omitted", ""]
        for o in omissions:
            lines.append(f"- `{o['finding_id']}`: {o['reason']}")
        lines.append("")

    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Render a validated report IR to Markdown.")
    ap.add_argument("findings")
    ap.add_argument("report_ir")
    ap.add_argument("-o", "--out", help="output path (default: stdout)")
    ap.add_argument("--force", action="store_true", help="render even if validation fails")
    args = ap.parse_args()

    code = validate_report.main(["validate_report", args.findings, args.report_ir])
    if code != 0 and not args.force:
        print("Refusing to render: report IR failed validation.", file=sys.stderr)
        return 1

    with open(args.findings) as fh:
        findings = json.load(fh)
    with open(args.report_ir) as fh:
        report = json.load(fh)
    out = render(findings, report)

    if args.out:
        with open(args.out, "w") as fh:
            fh.write(out)
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
