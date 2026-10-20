#!/usr/bin/env python3
"""Stage 3: synthesize a report from findings.json.

Default endpoint is a LOCAL Ollama model, so nothing leaves the machine:

    python stage3/run.py findings.json --model qwen2.5:14b-instruct -o report.md

The ONLINE path (OpenRouter) is opt-in and requires an explicit acknowledgment
flag; it warns about exactly what is transmitted:

    python stage3/run.py findings.json --endpoint openrouter \
        --model qwen/qwen-... --accept-privacy-risk -o report.md

Two narration modes:
  skeleton (default)  Code owns the structure, citations, caveats, and
                      contradiction text. The model only writes one sentence per
                      claim. Smaller, faster, far harder to violate the rules.
  full                The model authors the entire report IR. Higher ceiling,
                      more failure modes (use for strong models).

If the model fails, a deterministic template report (Option C) is rendered.
"""
import argparse
import copy
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "tools"))

import llm  # noqa: E402
import prompt  # noqa: E402
import validate_report  # noqa: E402
from caveats import STATE_CAVEAT  # noqa: E402
from render_report import render  # noqa: E402

SECTION_ORDER = [
    ("detected", "Detected variants"),
    ("covered_reference", "On the array, reference genotype"),
    ("covered_nocall", "On the array, no call"),
    ("covered_uninterpretable", "On the array, uninterpretable"),
    ("not_covered", "Not measured by this array"),
    ("not_assayable", "Not accessible to this assay"),
]

PRIVACY_WARNING = """\
You are about to send derived genetic findings to an ONLINE model (OpenRouter).
What leaves this machine: the contents of findings.json for the curated panel
only — including each variant's state (e.g. detected / not measured), zygosity,
and evidence — plus a hash binding, minus the raw allele letters and the raw
file fingerprint (both are withheld by default). The raw DNA file and all
unpaneled positions never leave. The request and response may be retained by the
model provider. Re-run with --accept-privacy-risk to acknowledge and proceed, or
omit --endpoint openrouter to use a local model.\
"""

SKELETON_SYSTEM = """\
You narrate structured genomic findings in plain English. You do not compute or
interpret anything; you turn supplied facts into one sentence per claim.

This is ARRAY GENOTYPING, not sequencing. Say "the array" or "genotyping"; never
say "sequencing", "sequenced", or "whole genome".

Rules:
- Return ONLY a JSON object mapping each claim_id to one sentence.
- Use only the facts given for that claim. Do not add findings, variants, or
  conditions that are not present.
- Do not use any digits (0-9); write numbers as words (e.g. "two-star").
- Follow the state exactly:
  * detected: the variant was detected. You may mention zygosity, gene,
    condition, and evidence.
  * covered_reference: this position is on the array and the reference genotype
    was observed. Do NOT say the variant is present or detected.
  * covered_nocall: this position is on the array but genotyping returned no call.
  * covered_uninterpretable: this position was measured but the alleles could not
    be interpreted. Do NOT say the variant was detected.
  * not_covered: this marker was not measured by the array. Do NOT say the
    variant is absent or that the person does not have it.
  * not_assayable: this locus cannot be assessed from array data.
- Do not give advice, recommendations, or instructions.
- Do not use definitive, confirmed, proven, guaranteed, or causal language.
"""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def required_caveats(findings_cited):
    keys = {"array_limits"}
    for f in findings_cited:
        if f["state"] in STATE_CAVEAT:
            keys.add(STATE_CAVEAT[f["state"]])
        if f.get("call", {}).get("strand") == "ambiguous":
            keys.add("strand_ambiguous")
        rarity = f.get("confidence", {}).get("array_reliability", {}).get("rarity_class")
        if rarity in ("rare", "ultra_rare") and f["state"] == "detected":
            keys.add("rare_ppv")
    return sorted(keys)


def template_ir(findings, findings_hash):
    """Deterministic Option-C report IR built from findings alone."""
    by_state = {}
    for f in findings["findings"]:
        by_state.setdefault(f["state"], []).append(f)

    sections = []
    for state, title in SECTION_ORDER:
        fs = by_state.get(state, [])
        if not fs:
            continue
        claims = []
        for f in fs:
            label = f.get("rsid") or f.get("gene") or "locus"
            gene = f.get("gene") or "unknown gene"
            claims.append({
                "claim_id": "cl_" + f["finding_id"][2:],
                "text": f"{label} ({gene}): state is {state}.",
                "citations": [{"finding_id": f["finding_id"], "field_path": "state"}],
            })
        sections.append({
            "section_id": "s_" + state,
            "title": title,
            "claims": claims,
            "caveat_ids": required_caveats(fs),
        })

    for c in findings.get("contradictions", []):
        cited = [f for f in findings["findings"] if f["finding_id"] in c["finding_ids"]]
        # The renderer prints the contradiction description from findings.json, so
        # this section carries no duplicate claim; it only signals reporting.
        sections.append({
            "section_id": "s_" + c["contradiction_id"],
            "title": "Contradictions",
            "claims": [],
            "caveat_ids": required_caveats(cited),
            "contradiction_ids": [c["contradiction_id"]],
        })

    return {
        "ir_version": "1.0.0",
        "report_id": "r_model",
        "findings_hash": findings_hash,
        "sections": sections,
        "omitted_findings": [],
    }


# ---------------------------------------------------------------------------
# skeleton mode
# ---------------------------------------------------------------------------

def _state_claims(ir):
    for sec in ir["sections"]:
        if sec["section_id"].startswith("s_c_"):
            continue
        for cl in sec["claims"]:
            yield cl


def build_skeleton(findings, findings_hash):
    """Return (skeleton with blank texts, fallback_text by claim_id)."""
    ir = template_ir(findings, findings_hash)
    fallback = {}
    for cl in _state_claims(ir):
        fallback[cl["claim_id"]] = cl["text"]
        cl["text"] = ""
    return ir, fallback


def skeleton_prompt(findings, ir, findings_hash):
    by_id = {f["finding_id"]: f for f in findings["findings"]}
    items = []
    for cl in _state_claims(ir):
        fid = cl["citations"][0]["finding_id"]
        f = by_id[fid]
        items.append({
            "claim_id": cl["claim_id"],
            "rsid": f.get("rsid"),
            "gene": f.get("gene"),
            "condition": f.get("condition"),
            "state": f["state"],
            "zygosity": f.get("call", {}).get("zygosity"),
            "clinvar": f.get("evidence", {}).get("clinvar"),
            "association": f.get("evidence", {}).get("association"),
        })
    user = "\n".join([
        "Write one plain-English sentence for each claim below.",
        "Return ONLY a JSON object mapping claim_id to sentence.",
        "No digits. Use only the supplied facts. No advice.",
        "",
        json.dumps({"claims": items}, separators=(",", ":")),
    ])
    return [{"role": "system", "content": SKELETON_SYSTEM},
            {"role": "user", "content": user}]


def parse_object(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.startswith("json"):
            t = t[4:]
        t = t.strip()
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def merge_prose(ir, fallback, prose):
    used = fell_back = 0
    for cl in _state_claims(ir):
        cid = cl["claim_id"]
        text = prose.get(cid) if isinstance(prose, dict) else None
        if isinstance(text, str) and text.strip():
            cl["text"] = text.strip()
            used += 1
        else:
            cl["text"] = fallback[cid]
            fell_back += 1
    return used, fell_back


def revert_invalid(ir, fallback, errors):
    bad = set()
    for _, msg in errors:
        for cid in fallback:
            if cid in msg:
                bad.add(cid)
    for cl in _state_claims(ir):
        if cl["claim_id"] in bad:
            cl["text"] = fallback[cl["claim_id"]]
    return len(bad)


def parse_and_check(text, findings_path, findings):
    try:
        report = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        return None, [("json", f"unparseable JSON: {exc}")]
    errors, _ = validate_report.check(findings_path, report, findings=findings)
    return report, errors


def run_skeleton(findings, findings_path, findings_hash, args, chat_kwargs):
    base_ir, fallback = build_skeleton(findings, findings_hash)
    messages = skeleton_prompt(findings, base_ir, findings_hash)
    attempts_used = 0
    attempt_violations = []
    prose_used = fell_back = 0
    accepted = None

    for _ in range(args.attempts):
        attempts_used += 1
        candidate = copy.deepcopy(base_ir)
        try:
            raw = llm.chat(messages=messages, **chat_kwargs)
        except Exception as exc:  # noqa: BLE001
            attempt_violations.append([f"request: {exc}"])
            break
        prose = parse_object(raw)
        prose_used, fell_back = merge_prose(candidate, fallback, prose)
        errors, _ = validate_report.check(findings_path, candidate, findings=findings)
        attempt_violations.append([c for c, _ in errors])
        if not errors:
            accepted = candidate
            break
        reverted = revert_invalid(candidate, fallback, errors)
        errors, _ = validate_report.check(findings_path, candidate, findings=findings)
        attempt_violations.append([c for c, _ in errors])
        if not errors:
            accepted = candidate
            break
        attempt_violations[-1].append(f"reverted:{reverted}")

    if accepted is None:
        accepted = template_ir(findings, findings_hash)
        errors, _ = validate_report.check(findings_path, accepted, findings=findings)
        if errors:
            raise SystemExit("template IR failed validation (bug)")
        return accepted, attempts_used, attempt_violations, True, 0, len(fallback)
    return accepted, attempts_used, attempt_violations, False, prose_used, fell_back


def main():
    ap = argparse.ArgumentParser(description="Synthesize a report from findings.json.")
    ap.add_argument("findings")
    ap.add_argument("--endpoint", choices=["ollama", "openrouter"], default="ollama")
    ap.add_argument("--model", default="qwen2.5:14b")
    ap.add_argument("--mode", choices=["skeleton", "full"], default="skeleton")
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("-o", "--out", default="report.md")
    ap.add_argument("--template-only", action="store_true", help="skip the model; render the deterministic template")
    ap.add_argument("--print-payload", action="store_true", help="print the user payload and exit")
    ap.add_argument("--accept-privacy-risk", action="store_true")
    ap.add_argument("--send-alleles", action="store_true", help="online: include raw alleles (not recommended)")
    ap.add_argument("--keep-input-hash", action="store_true", help="online: include the raw file hash (not recommended)")
    args = ap.parse_args()

    with open(args.findings) as fh:
        findings = json.load(fh)
    findings_hash = sha256_file(args.findings)

    online = args.endpoint == "openrouter"
    redact_alleles = online and not args.send_alleles
    omit_input_hash = online and not args.keep_input_hash

    if args.print_payload:
        if args.mode == "skeleton":
            ir, _ = build_skeleton(findings, findings_hash)
            msgs = skeleton_prompt(findings, ir, findings_hash)
        else:
            msgs = prompt.build_messages(findings, findings_hash,
                                         redact_alleles=redact_alleles, omit_input_hash=omit_input_hash)
        sys.stdout.write(msgs[1]["content"] + "\n")
        return 0

    if online and not args.accept_privacy_risk:
        print(PRIVACY_WARNING, file=sys.stderr)
        return 2

    prose_used = fell_back = 0
    if args.template_only:
        report = template_ir(findings, findings_hash)
        errors, _ = validate_report.check(args.findings, report, findings=findings)
        if errors:
            print("template IR failed validation (bug):", file=sys.stderr)
            return 1
        attempts_used, attempt_violations, used_fallback = 0, [], True
    else:
        base, key, provider, headers = llm.resolve_endpoint(args.endpoint)
        if args.endpoint == "openrouter" and not key:
            print("error: OPENROUTER_API_KEY is not set", file=sys.stderr)
            return 2
        chat_kwargs = dict(base_url=base, api_key=key, model=args.model,
                           temperature=0.0, response_format={"type": "json_object"},
                           provider=provider, extra_headers=headers, seed=args.seed)

        if args.mode == "skeleton":
            report, attempts_used, attempt_violations, used_fallback, prose_used, fell_back = \
                run_skeleton(findings, args.findings, findings_hash, args, chat_kwargs)
        else:
            messages = prompt.build_messages(findings, findings_hash,
                                             redact_alleles=redact_alleles, omit_input_hash=omit_input_hash)
            report, attempts_used, attempt_violations, used_fallback = \
                run_full(findings, args.findings, findings_hash, args, messages, chat_kwargs)

    markdown = render(findings, report)
    base_out = os.path.splitext(args.out)[0]
    ir_path = base_out + ".ir.json"
    run_path = base_out + ".run.json"
    with open(args.out, "w") as fh:
        fh.write(markdown)
    with open(ir_path, "w") as fh:
        json.dump(report, fh, indent=2)
    audit = {
        "endpoint": args.endpoint,
        "model": args.model if not args.template_only else None,
        "mode": args.mode,
        "findings_hash": findings_hash,
        "input_hash": findings.get("provenance", {}).get("input_hash"),
        "attempts_used": attempts_used,
        "attempt_violations": attempt_violations,
        "used_fallback": used_fallback,
        "prose_claims": prose_used,
        "fallback_claims": fell_back,
        "payload": {"redact_alleles": redact_alleles, "omit_input_hash": omit_input_hash},
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(run_path, "w") as fh:
        json.dump(audit, fh, indent=2)

    if used_fallback:
        mode = "template (Option C)"
    else:
        mode = f"{args.mode}:{args.model} in {attempts_used} attempt(s)" + \
               (f", {fell_back} claim(s) fell back" if fell_back else "")
    print(f"wrote {args.out}, {ir_path}, {run_path}  [{mode}]")
    return 0


def run_full(findings, findings_path, findings_hash, args, messages, chat_kwargs):
    attempts_used = 0
    attempt_violations = []
    report = None
    for _ in range(args.attempts):
        attempts_used += 1
        try:
            raw = llm.chat(messages=messages, **chat_kwargs)
        except Exception as exc:  # noqa: BLE001
            attempt_violations.append([f"request: {exc}"])
            break
        candidate, errors = parse_and_check(raw, findings_path, findings)
        attempt_violations.append([c for c, _ in errors])
        if candidate is not None and not errors:
            report = candidate
            break
        messages = messages + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": prompt.repair_message(errors)},
        ]
    if report is None:
        report = template_ir(findings, findings_hash)
        errors, _ = validate_report.check(findings_path, report, findings=findings)
        if errors:
            raise SystemExit("template IR failed validation (bug)")
        return report, attempts_used, attempt_violations, True
    return report, attempts_used, attempt_violations, False


if __name__ == "__main__":
    sys.exit(main())
