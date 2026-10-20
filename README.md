# SNP Insights

Turn a raw consumer DNA file into readable, **traceable** genetic findings —
without handing your genome to a language model.

SNP Insights parses your raw AncestryDNA file locally, annotates a curated set of
variants against public reference data, and computes every coverage state and
confidence value deterministically. A language model narrates the result — by
default a **local** model, so nothing leaves your machine. Every sentence it
writes is mechanically checked against the structured findings before anything is
rendered.

> **Not medical advice.** This is a research and curiosity tool. It is not a
> diagnostic test, a clinical-grade genetic test, or a substitute for a
> qualified clinician or genetic counselor. See [DESIGN.md](DESIGN.md).

## Why

Consumer DNA files contain real, interesting information that the vendors never
interpret. Re-reading that file is *interpretation*, not new lab work — but
generative interpretation is exactly where hallucination sneaks in: invented
confidence percentages, "the gene is absent" for a marker that was never
measured, and 1-star evidence dressed up as certainty.

SNP Insights is built so those failure modes are **structurally impossible**
rather than discouraged.

## How it works

```
Stage 1  Ingest    (local)   raw AncestryDNA .txt  ─┐
Stage 2  Annotate  (local)   snapshot panel + raw  ─┴─▶ findings.json
                                                         │
                                      ── privacy boundary ──
                                                         │
Stage 3  Narrate   (local)   findings.json ─▶ [LLM] ─▶ report_ir.json
                                              │
                                       validator (the harness enforces 7 rules)
                                              ▼
                                        renderer ─▶ report.md
```

- **Stages 1–2 are fully local.** Raw DNA never leaves the machine.
- **Stage 3 is local by default.** An online model is opt-in only, behind an
  explicit risk-acknowledgment flag.
- **The model authors prose only.** Numbers, caveats, citations, and
  contradictions are owned by code.
- **Every claim cites a `finding_id` + `field_path`.** If it isn't in
  `findings.json`, it can't reach the report.

## Repository layout

```
schema/     JSON Schemas: findings.json contract, report IR contract
stage2/     ancestry.py (raw parser), annotate.py (deterministic annotator)
tools/      caveats.py, validate_report.py, render_report.py, prompt.py, harness.py
data/       panel snapshots (annotations); targets for the ETL
fixtures/   synthetic raw file, findings, report IRs, candidate outputs
harness/    narrator candidate config and sample scorecard
DESIGN.md   design decisions, rationale, and known limitations
LICENSE     GNU GPL v3.0-or-later
```

## Requirements

- Python 3.9+
- `jsonschema` (optional) — enables JSON Schema validation passes. The semantic
  rule checks are pure standard library.
- [Ollama](https://ollama.com) (optional) — required only for Stage 3 with a
  local model, which is the default. Any OpenAI-compatible endpoint also works.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install jsonschema   # optional but recommended
```

### 1. Build a panel snapshot (ETL, network-free at runtime)

Curation lives in `data/targets.sample.json`; evidence is joined at build time:

```bash
python tools/build_panel.py --targets data/targets.sample.json \
    --clinvar fixtures/sources/clinvar.sample.tsv \
    --gnomad  fixtures/sources/gnomad.sample.vcf \
    -o data/panel.sample.json
```

Point `--clinvar` / `--gnomad` at real dumps (plain or `.gz`) to rebuild the
snapshot, and add `--dbsnp-merge <RsMergeArch>` to record retired rsIDs so a file
using an older rsID still matches. Stage 2 then needs no network.

### 2. Annotate a raw file (Stage 2, local)

```bash
python stage2/annotate.py fixtures/raw.sample.txt data/panel.sample.json \
    -o findings.json
```

### 3. Synthesize a report (Stage 3)

Runs a **local** model by default — nothing leaves the machine:

```bash
python stage3/run.py findings.json --model qwen2.5:14b -o report.md
```

Two narration modes: `--mode skeleton` (default) has code own the structure,
citations, caveats, and contradiction text — the model writes only one sentence
per claim. `--mode full` has the model author the entire report IR (higher
ceiling, more failure modes; use for strong models).

It writes `report.md`, `report.ir.json`, and `report.run.json`. The model's output
is validated; on failure it is re-prompted with the specific violations (up to
`--attempts`, default 3), and if it still fails, a deterministic template report
is rendered instead.

An **online** model is opt-in and requires an explicit acknowledgment flag. It
refuses to run otherwise, printing exactly what would be transmitted:

```bash
python stage3/run.py findings.json --endpoint openrouter \
    --model qwen/qwen-... --accept-privacy-risk -o report.md
```

> **Privacy.** An online model cannot be private: the derived findings — which
> are health-relevant — must be transmitted and may be retained by the provider.
> The online path withholds raw alleles and the file fingerprint and routes only
> to zero-retention providers, but that is risk *reduction*, not privacy. Only
> the local (default) or template paths keep findings on your machine.

To validate and render an IR you already have:

```bash
python tools/validate_report.py findings.json report_ir.json
python tools/render_report.py  findings.json report_ir.json -o report.md
```

### 4. Score narrator candidates

```bash
# offline: stored candidate outputs
python tools/harness.py --findings fixtures/findings.sample.json \
    --config harness/candidates.json -o scorecard.md

# live: local Ollama by default; add OpenRouter candidates to the config
python tools/harness.py --findings fixtures/findings.sample.json --live
```

Any OpenAI-compatible endpoint works; Ollama (`http://localhost:11434/v1`) and
OpenRouter (`https://openrouter.ai/api/v1`) are preconfigured. OpenRouter model
IDs are namespaced (e.g. `qwen/qwen-...`) and require `OPENROUTER_API_KEY`.

## Design rules

The pipeline enforces seven hard rules in code (no invented numbers, three-state
reporting, evidence grades preserved, informational-not-prescriptive language,
contradictions flagged, standing caveats, and full claim traceability). See
[DESIGN.md](DESIGN.md#2-the-hard-rules-and-how-they-are-enforced) for the full
table and the enforcement mechanism.

## Inspect your own data file

`scripts/check_raw.py` parses your AncestryDNA file with the same code as the
pipeline and self-checks the result — format, chromosome labels, no-call rate,
allele alphabet, duplicate IDs, inferred sex, and the curated panel — so you can
confirm it was read correctly before doing anything with it.

```bash
python scripts/check_raw.py /path/to/AncestryDNA.txt
python scripts/check_raw.py /path/to/AncestryDNA.txt --json -o inspect.json
```

By default it reports panel **states only** and withholds the raw allele letters
(`--no-redact` to include them), and never prints genome-wide genotypes — just
aggregate counts and the curated panel. `--no-hash` omits the file fingerprint.
The script performs no network access.

## Testing

No dependencies required:

```bash
python tests/test_pipeline.py
```

It covers the AncestryDNA parser, the deterministic annotator, condition
normalization and contradiction grouping, ETL robustness against messy
ClinVar/gnomAD inputs, the semantic-fidelity lints, and an end-to-end validator
accept/reject.

## Status

Early / research. Stages 1–2, the panel ETL, and the Stage 3 runner (local model
by default, with self-repair, template fallback, and an audit artifact) work
end-to-end against fixtures. The ETL has only been tested against synthetic
source files, and Stage 3 has been exercised against the template path and
fixtures, not yet against a live model. Known gaps are tracked in
[DESIGN.md](DESIGN.md#4-design-limitations-and-known-gaps).

## Contributing

Issues and pull requests are welcome. Please read [DESIGN.md](DESIGN.md) first —
decisions and non-goals are recorded there, and changes that affect the hard
rules should update it.

## License

Licensed under the **GNU General Public License, version 3 or later**
(`GPL-3.0-or-later`). See [`LICENSE`](LICENSE) for the full text.

You are free to use, study, share, and modify this software. If you
distribute it, or a work based on it, you must pass on the same freedoms
and make the corresponding source available under the same license.

This program is distributed in the hope that it will be useful, but
**without any warranty**; without even the implied warranty of
merchantability or fitness for a particular purpose.
