#!/usr/bin/env python3
"""Validate a Stage 3 report IR against its source findings.json.

Usage:
    python tools/validate_report.py <findings.json> <report_ir.json>

Enforces the non-negotiable rules mechanically, so they do not rely on the
narrator obeying a prompt:

  Rule 1  every number in claim text must appear in a cited field
  Rule 2  state-specific caveats are required per cited finding
  Rule 3  weak evidence grades forbid strong wording
  Rule 4  prescriptive / imperative language is rejected
  Rule 5  every contradiction in findings.json must be reported
  Rule 6  every section must carry the mandatory array-limits caveat
  Rule 7  every claim cites a resolvable finding_id + field_path, and every
          finding is either cited or explicitly omitted (no silent omissions)

Requires jsonschema for the structural (schema) pass; if it is not importable
the semantic rules still run and a warning is emitted.
"""
import hashlib
import json
import os
import re
import sys

from caveats import CAVEAT_REGISTRY, STATE_CAVEAT

STRONG_WORDS = ["definitive", "definitively", "confirmed", "proven", "guaranteed", "causes", "known to cause"]
PRESCRIPTIVE = [
    "recommend", "you should", "you must", "you need to", "start taking", "stop taking",
    "increase your dose", "decrease your dose", "should take", "should start", "should stop",
    "see your doctor", "consult your doctor", "get tested", "schedule a", "check with your",
]

# Semantic-fidelity lints: array genotyping is not sequencing, and a variant must
# not be described as present/detected unless its state is "detected".
GLOBAL_BANS = re.compile(r"\b(sequencing|sequenced|whole[- ]genome|whole[- ]exome)\b", re.I)
NOT_DETECTED_PAT = re.compile(r"\bvariant\b[^.]{0,60}(?<!not )(detected|present|found|carried)\b", re.I)
CARRIES_PAT = re.compile(r"\b(carries|has|harbors|harbours)\b[^.]{0,30}\bvariant\b", re.I)
UNMEASURED_PAT = re.compile(
    r"\b(not present|absent|negative|no variant|rules out|no evidence of|"
    r"does(?:n't| not) (?:have|carry)|do(?:n't| not) (?:have|carry)|free of|clear of)\b",
    re.I,
)
ABSOLUTE_PAT = re.compile(
    r"\b(will develop|you will|definitely|certainly|guaranteed|fatal|will cause|"
    r"your risk|100%)\b",
    re.I,
)


def semantic_violations(text, cited_findings):
    out = []
    if GLOBAL_BANS.search(text):
        out.append("uses 'sequencing'/'whole-genome' wording; this is array genotyping")
    if ABSOLUTE_PAT.search(text):
        out.append("uses overreaching/absolute language")
    for f in cited_findings:
        state = f.get("state")
        if state != "detected" and (NOT_DETECTED_PAT.search(text) or CARRIES_PAT.search(text)):
            out.append(f"implies the variant is present/detected but state is {state}")
            break
        if state in ("not_covered", "not_assayable") and UNMEASURED_PAT.search(text):
            out.append(f"implies absence/negativity but state is {state} (must say not measured)")
            break
    return out

ID_RE = re.compile(r"\b(?:rs\d+|f_[0-9a-f]+|c_[0-9a-f]+|cl_[0-9a-f]+|s_[0-9a-z_]+)\b", re.I)
GENE_RE = re.compile(r"\b[A-Z][A-Za-z]*\d[A-Za-z0-9]*\b")
NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def normalize_num(n):
    try:
        f = float(n)
    except ValueError:
        return n
    return str(int(f)) if f == int(f) else repr(f)


def numbers_in(text):
    t = ID_RE.sub(" ", text)
    t = GENE_RE.sub(" ", t).replace("GRCh37", " ").replace("GRCh38", " ")
    return [normalize_num(n) for n in NUM_RE.findall(t)]


def collect_numbers(value, out):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out.add(normalize_num(str(value)))
    elif isinstance(value, str):
        for n in NUM_RE.findall(value):
            out.add(normalize_num(n))
    elif isinstance(value, list):
        for v in value:
            collect_numbers(v, out)
    elif isinstance(value, dict):
        for v in value.values():
            collect_numbers(v, out)


def split_path(path):
    parts = []
    for chunk in path.split("."):
        m = re.match(r"^(\w+)((\[\d+\])*)$", chunk)
        if not m:
            parts.append(chunk)
            continue
        parts.append(m.group(1))
        for idx in re.findall(r"\[(\d+)\]", chunk):
            parts.append(int(idx))
    return parts


def resolve(root, path):
    cur = root
    for part in split_path(path):
        if isinstance(part, int):
            if not isinstance(cur, list) or part >= len(cur):
                raise KeyError(path)
            cur = cur[part]
        else:
            if not isinstance(cur, dict) or part not in cur:
                raise KeyError(path)
            cur = cur[part]
    return cur


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def check(findings_path, report, findings=None):
    """Return (errors, warnings) for a report IR against findings.json.

    findings may be passed in to avoid re-reading; findings_path is still used
    for the hash binding.
    """
    if findings is None:
        with open(findings_path) as fh:
            findings = json.load(fh)

    errors, warnings = [], []

    def err(code, msg):
        errors.append((code, msg))

    try:
        import jsonschema
        schema_path = os.path.join(os.path.dirname(__file__), "..", "schema", "report_ir.schema.json")
        with open(schema_path) as fh:
            schema = json.load(fh)
        for e in jsonschema.Draft202012Validator(schema).iter_errors(report):
            err("schema", f"{list(e.path)}: {e.message}")
    except ImportError:
        warnings.append(("schema", "jsonschema not installed; structural checks skipped"))

    findings_by_id = {f["finding_id"]: f for f in findings["findings"]}
    contradiction_ids = {c["contradiction_id"] for c in findings["contradictions"]}

    want = sha256_file(findings_path)
    if report.get("findings_hash") != want:
        err("hash", f"findings_hash {report.get('findings_hash')!r} != sha256({findings_path}) {want}")

    referenced = set()
    reported_contradictions = set()

    for section in report.get("sections", []):
        sid = section.get("section_id", "?")
        caveat_ids = set(section.get("caveat_ids", []))
        if "array_limits" not in caveat_ids:
            err("R6", f"section {sid}: missing required caveat_id 'array_limits'")
        for cvid in caveat_ids:
            if cvid not in CAVEAT_REGISTRY:
                err("R6", f"section {sid}: unknown caveat_id {cvid!r}")
        reported_contradictions |= set(section.get("contradiction_ids", []))

        for claim in section.get("claims", []):
            cid = claim.get("claim_id", "?")
            text = claim.get("text", "")
            citations = claim.get("citations", [])
            if not citations:
                err("R7", f"{sid}/{cid}: claim has no citations")
            allowed = set()
            cited_objs = []
            for cit in citations:
                fid = cit.get("finding_id")
                fpath = cit.get("field_path", "")
                if fid == "provenance":
                    root = findings["provenance"]
                elif fid in findings_by_id:
                    root = findings_by_id[fid]
                    referenced.add(fid)
                else:
                    err("R7", f"{sid}/{cid}: citation references unknown finding_id {fid!r}")
                    continue
                try:
                    val = resolve(root, fpath)
                except KeyError:
                    err("R7", f"{sid}/{cid}: field_path {fpath!r} does not resolve in {fid}")
                    continue
                collect_numbers(val, allowed)

                fobj = findings_by_id.get(fid)
                if not fobj:
                    continue
                cited_objs.append(fobj)
                state = fobj.get("state")
                req = STATE_CAVEAT.get(state)
                if req and req not in caveat_ids:
                    err("R2", f"{sid}/{cid}: finding {fid} state={state} requires caveat_id {req!r} in section {sid}")
                if fobj.get("call", {}).get("strand") == "ambiguous" and "strand_ambiguous" not in caveat_ids:
                    err("R2", f"{sid}/{cid}: finding {fid} strand ambiguous requires caveat_id 'strand_ambiguous'")
                rarity = fobj.get("confidence", {}).get("array_reliability", {}).get("rarity_class")
                if rarity in ("rare", "ultra_rare") and state == "detected" and "rare_ppv" not in caveat_ids:
                    err("R2", f"{sid}/{cid}: rare finding {fid} requires caveat_id 'rare_ppv'")
                clin = fobj.get("evidence", {}).get("clinvar") or {}
                stars = clin.get("review_stars")
                assoc = fobj.get("evidence", {}).get("association")
                if (stars is not None and stars <= 1) or assoc == "single_study":
                    low = text.lower()
                    for w in STRONG_WORDS:
                        if w in low:
                            err("R3", f"{sid}/{cid}: strong wording {w!r} on weak evidence (finding {fid}: stars={stars}, assoc={assoc})")

            for n in numbers_in(text):
                if n not in allowed:
                    err("R1", f"{sid}/{cid}: number {n!r} not found in any cited field (invented value?)")
            low = text.lower()
            for p in PRESCRIPTIVE:
                if p in low:
                    err("R4", f"{sid}/{cid}: prescriptive language {p!r}")
            for problem in semantic_violations(text, cited_objs):
                err("R2", f"{sid}/{cid}: {problem}")

    for cid in sorted(contradiction_ids - reported_contradictions):
        err("R5", f"contradiction {cid} not reported in any section")

    omitted = {o["finding_id"] for o in report.get("omitted_findings", [])}
    all_ids = set(findings_by_id)
    for fid in sorted(all_ids - referenced - omitted):
        err("R7", f"finding {fid} is neither cited nor listed in omitted_findings")
    for fid in sorted(referenced & omitted):
        err("R7", f"finding {fid} is both cited and omitted")
    for fid in sorted(omitted - all_ids):
        err("R7", f"omitted_findings references unknown finding {fid}")

    return errors, warnings


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    findings_path, report_path = argv[1], argv[2]
    with open(report_path) as fh:
        report = json.load(fh)

    errors, warnings = check(findings_path, report)
    for code, msg in warnings:
        print(f"[warn] {code}: {msg}")
    if not errors:
        print(f"OK: {report_path} satisfies all rules against {findings_path}")
        return 0
    print(f"FAIL: {len(errors)} violation(s)")
    for code, msg in errors:
        print(f"  [{code}] {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
