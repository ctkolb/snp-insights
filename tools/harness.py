#!/usr/bin/env python3
"""Golden harness: score narrator candidates on the fixtures.

Each candidate is a stored report IR (offline mode) or a live model call
(--live). Every candidate is validated with the same rule checks used in
production, and scored on parse success, refusals, rule violations, and finding
coverage. Use this to select the online narrator on evidence, not reputation.

Usage:
    python tools/harness.py --findings fixtures/findings.sample.json \
        [--config harness/candidates.json] [--live] [--runs N] [--json out.json] [-o scorecard.md]
"""
import argparse
import json
import os
import sys
from collections import Counter

import llm
import validate_report
from prompt import build_messages

REFUSAL_MARKERS = [
    "i can't", "i cannot", "i'm unable", "i am unable", "as an ai",
    "i must decline", "i'm sorry", "i am sorry", "i won't", "cannot assist",
    "unable to assist", "not able to provide",
]


def sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def call_live(candidate, messages, defaults):
    endpoint = candidate.get("endpoint", "openrouter")
    base, key, provider, headers = llm.resolve_endpoint(endpoint, base_url=candidate.get("base_url"))
    if endpoint == "openrouter" and not key:
        raise RuntimeError("no API key in env OPENROUTER_API_KEY")
    return llm.chat(base, key, candidate["model"], messages, temperature=0.0,
                    response_format={"type": "json_object"}, provider=provider,
                    extra_headers=headers)


def score_text(name, text, findings_path, findings):
    result = {"name": name, "parse_ok": False, "refusal": False, "valid": False,
              "violations": 0, "by_rule": {}, "missing_findings": 0, "note": ""}
    low = text.lower()
    if any(m in low for m in REFUSAL_MARKERS) and "{" not in text:
        result["refusal"] = True
        result["note"] = "looks like a refusal / no JSON"
        return result
    try:
        report = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        result["note"] = f"unparseable JSON: {exc}"
        return result
    result["parse_ok"] = True
    errors, _ = validate_report.check(findings_path, report, findings=findings)
    result["violations"] = len(errors)
    result["by_rule"] = dict(Counter(code for code, _ in errors))
    result["valid"] = not errors
    referenced, omitted = set(), {o.get("finding_id") for o in report.get("omitted_findings", [])}
    for sec in report.get("sections", []):
        for claim in sec.get("claims", []):
            for cit in claim.get("citations", []):
                referenced.add(cit.get("finding_id"))
    all_ids = {f["finding_id"] for f in findings["findings"]}
    result["missing_findings"] = len(all_ids - referenced - omitted)
    return result


def main():
    ap = argparse.ArgumentParser(description="Score narrator candidates.")
    ap.add_argument("--findings", default="fixtures/findings.sample.json")
    ap.add_argument("--config", default="harness/candidates.json")
    ap.add_argument("--live", action="store_true", help="call live models (requires API key env vars)")
    ap.add_argument("--runs", type=int, default=1, help="runs per live candidate (for stability)")
    ap.add_argument("--json", dest="json_out", help="write raw results as JSON")
    ap.add_argument("-o", "--out", help="write scorecard Markdown")
    args = ap.parse_args()

    with open(args.findings) as fh:
        findings = json.load(fh)
    findings_hash = sha256_file(args.findings)
    with open(args.config) as fh:
        config = json.load(fh)
    defaults = config.get("live_defaults", {"base_url_env": "OPENAI_BASE_URL", "api_key_env": "OPENAI_API_KEY"})
    messages = build_messages(findings, findings_hash)

    results = []
    for cand in config["candidates"]:
        name = cand["name"]
        if cand.get("live"):
            if not args.live:
                results.append({"name": name, "parse_ok": None, "refusal": None, "valid": None,
                                "violations": None, "by_rule": {}, "missing_findings": None,
                                "note": "live: skipped (pass --live)"})
                continue
            outputs = []
            for _ in range(args.runs):
                try:
                    outputs.append(call_live(cand, messages, defaults))
                except Exception as exc:  # noqa: BLE001 - report and continue
                    outputs.append(f"<error: {exc}>")
            runs = [score_text(name, o, args.findings, findings) for o in outputs]
            best = dict(runs[0])
            best["stability"] = "identical" if all(
                json.dumps(r, sort_keys=True) == json.dumps(runs[0], sort_keys=True) for r in runs
            ) else "variable"
            results.append(best)
            continue
        with open(cand["file"]) as fh:
            text = fh.read()
        results.append(score_text(name, text, args.findings, findings))

    def rank(r):
        return (r["valid"] is not True, r["parse_ok"] is None, r["parse_ok"] is False, r["violations"] or 0)

    ordered = sorted(results, key=rank)

    header = "| candidate | parse | refusal | valid | violations | by rule | missing | note |"
    sep = "|---|---|---|---|---|---|---|---|"
    lines = ["# Narrator scorecard", "", f"findings: `{args.findings}` hash `{findings_hash[:16]}...`", "", header, sep]
    for r in ordered:
        lines.append("| {name} | {parse} | {ref} | {valid} | {v} | {by} | {miss} | {note} |".format(
            name=r["name"],
            parse={True: "ok", False: "FAIL", None: "-"}[r["parse_ok"]],
            ref={True: "yes", False: "no", None: "-"}[r["refusal"]],
            valid={True: "PASS", False: "FAIL", None: "-"}[r["valid"]],
            v="-" if r["violations"] is None else r["violations"],
            by=json.dumps(r["by_rule"]) if r["by_rule"] else "",
            miss="-" if r["missing_findings"] is None else r["missing_findings"],
            note=r["note"],
        ))
    scorecard = "\n".join(lines) + "\n"

    if args.out:
        with open(args.out, "w") as fh:
            fh.write(scorecard)
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(scorecard)
    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump({"findings_hash": findings_hash, "results": ordered}, fh, indent=2)
        print(f"wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
