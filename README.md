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
- **Links are code-generated.** Each finding points to dbSNP, ClinVar, gnomAD,
  OMIM, SNPedia, MedlinePlus, and GeneReviews so you can read more — the model
  never writes URLs.

## Repository layout

```
snp_insights/  the CLI package: __init__.py, __main__.py, cli.py
pyproject.toml packaging metadata (setuptools; console script snp-insights)
stage2/        ancestry.py (raw parser), annotate.py (deterministic annotator)
stage3/        run.py (IR + self-repair + template fallback; local model default)
tools/         evidence.py, build_panel.py, fetch_reference.py, validate_report.py,
               render_report.py, prompt.py, harness.py, caveats.py, references.py,
               llm.py, snpedia_to_tsv.py
scripts/       check_raw.py, guard.py, loop_check_clean.py, loop_mutations.py,
               validate_result_block.py
schema/        JSON Schemas: findings.json contract, report IR contract
data/          panel snapshots (annotations); targets for the ETL
fixtures/      synthetic raw file, findings, report IRs, candidate outputs
harness/       narrator candidate config and sample scorecard
DESIGN.md      design decisions, rationale, and known limitations
LICENSE        GNU GPL v3.0-or-later
```

## Requirements

- Python 3.12+
- `jsonschema` (optional) — enables JSON Schema validation passes. The semantic
  rule checks are pure standard library.
- [Ollama](https://ollama.com) (optional) — required only for Stage 3 with a
  local model, which is the default. Any OpenAI-compatible endpoint also works.

## Quickstart

### Install and run

```bash
python -m venv .venv && source .venv/bin/activate
pip install jsonschema   # optional but recommended
```

`python -m snp_insights <command>` works from any directory when the repository
is on `PYTHONPATH` or is the current directory. `pip install -e .` also installs a
`snp-insights` console script; the test suite does **not** exercise that script
(not verified here). Installing a wheel outside the repository is **not
supported** — the sub-tools live in `tools/`, `stage2/`, and `stage3/` outside the
package, so the CLI locates them relative to its own position in the repo.

```bash
python -m snp_insights --version     # snp-insights 0.1.0
python -m snp_insights --help        # lists every subcommand
```

The six subcommands are `fetch`, `build-panel`, `check-raw`, `annotate`,
`narrate`, and `run`. Each forwards the arguments after the subcommand to the
matching tool verbatim; `snp-insights <sub> --help` prints that tool's own help (for
`run`, its own usage).

### 1. Build a panel snapshot (ETL, network-free at runtime)

Curation lives in `data/targets.sample.json`; evidence is joined at build time:

```bash
python -m snp_insights build-panel --targets data/targets.sample.json \
    --clinvar fixtures/sources/clinvar.sample.tsv \
    --gnomad  fixtures/sources/gnomad.sample.vcf \
    -o data/panel.sample.json
```

Without `-o`, `build-panel` prints the panel JSON to stdout. Point `--clinvar` /
`--gnomad` at real dumps (plain or `.gz`) to rebuild the snapshot, and add
`--dbsnp-merge <RsMergeArch>` to record retired rsIDs so a file using an older
rsID still matches. A release-format targets file (one that declares
`result_type`) additionally needs `--curated-evidence data/targets.release-evidence.json`,
which gives each carrier entry its curated per-condition ClinVar record instead
of the aggregate row. Annotation then needs no network.

### 2. Annotate a raw file (Stage 2, local)

```bash
python -m snp_insights annotate fixtures/raw.sample.txt data/panel.sample.json \
    -o findings.json
```

### 3. Narrate a report (Stage 3)

Runs a **local** model by default — nothing leaves the machine. Add
`--template-only` to skip the model entirely and stay fully offline:

```bash
python -m snp_insights narrate findings.json --model qwen2.5:14b -o report.md
python -m snp_insights narrate findings.json --template-only -o report.md
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
refuses to run otherwise, printing exactly what would be transmitted and exiting
with code 2:

```bash
python -m snp_insights narrate findings.json --endpoint openrouter \
    --model qwen/qwen-... --accept-privacy-risk -o report.md
```

> **Privacy.** An online model cannot be private: the derived findings — which
> are health-relevant — must be transmitted and may be retained by the provider.
> The online path withholds raw alleles and the file fingerprint and routes only
> to zero-retention providers, but that is risk *reduction*, not privacy. Only
> the local (default) or template paths keep findings on your machine.

### 4. One command: `run`

`run RAW PANEL` annotates, then narrates, into an output directory:

```bash
python -m snp_insights run fixtures/raw.sample.txt data/panel.sample.json \
    --out-dir ./snp-insights-out --template-only
```

- Writes four files into `--out-dir` (default `./snp-insights-out`, created if
  needed): `findings.json`, `report.md`, `report.ir.json`, and `report.run.json`.
- **Never overwrites** existing output without `--force`: it refuses with exit
  code 1 and writes nothing.
- Refuses an output path that is a **symlink** (dangling or not) even with
  `--force`, and refuses an `--out-dir` that exists as a file.
- `-o` / `--out` are refused here (exit code 2); the output location is
  `--out-dir`. Every other option is forwarded to `narrate` verbatim, and
  everything after a `--` token is forwarded without being interpreted by `run`.
- Files it creates are mode `0600` and a directory it creates is `0700`, so the
  health-relevant output stays private to your user.
- It prints one reminder line that `findings.json` is private health data.
- The online privacy gate is untouched: `run ... --endpoint openrouter` without
  `--accept-privacy-risk` exits with code 2 and makes no HTTP call.

### Validate and render an existing IR (optional)

```bash
python tools/validate_report.py findings.json report_ir.json
python tools/render_report.py  findings.json report_ir.json -o report.md
```

### Score narrator candidates (optional)

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

### Under the hood (script equivalents)

Each subcommand wraps a script that still runs directly, if you prefer:
`tools/fetch_reference.py`, `tools/build_panel.py`, `scripts/check_raw.py`,
`stage2/annotate.py`, and `stage3/run.py`. For example
`python stage3/run.py findings.json --template-only -o report.md`. The CLI adds
the sub-tools' directories to `sys.path` at call time and refuses to load a
sub-tool whose module resolves outside the repository.

## Design rules

The pipeline enforces seven hard rules in code (no invented numbers, three-state
reporting, evidence grades preserved, informational-not-prescriptive language,
contradictions flagged, standing caveats, and full claim traceability). See
[DESIGN.md](DESIGN.md#2-the-hard-rules-and-how-they-are-enforced) for the full
table and the enforcement mechanism.

## Inspect your own data file

`python -m snp_insights check-raw` (or `scripts/check_raw.py`) parses your
AncestryDNA file with the same code as the pipeline and self-checks the result —
format, chromosome labels, no-call rate, allele alphabet, duplicate IDs, inferred
sex, and the curated panel — so you can confirm it was read correctly before
doing anything with it.

```bash
python -m snp_insights check-raw /path/to/AncestryDNA.txt
python -m snp_insights check-raw /path/to/AncestryDNA.txt --json -o inspect.json
```

By default it reports panel **states only** and withholds the raw allele letters
(`--no-redact` to include them), and never prints genome-wide genotypes — just
aggregate counts and the curated panel. `--no-hash` omits the file fingerprint.
The command performs no network access.

## Fetching reference data

Annotation never touches the network. Reference data is fetched by a separate,
explicit step into a local cache (outside the repo):

```bash
# see exactly what would be fetched, no network
python -m snp_insights fetch --targets data/targets.carrier.json --dry-run

# fetch ONLY the records your targets need (default)
python -m snp_insights fetch \
    --targets data/targets.carrier.json \
    --targets data/targets.traits.json \
    --email you@example.com

# or download the complete official files (GiB-scale)
python -m snp_insights fetch --full --email you@example.com
```

`fetch` takes no raw-file argument (an unknown flag exits 2). The **small set =
the rsIDs in your targets files.** Add a variant to a targets file and re-run
fetch to pull just that record — there is nothing else to configure. Small mode
queries each source's API directly (dbSNP variation API, ClinVar E-utilities,
gnomAD GraphQL, SNPedia MediaWiki); each writes normalized files plus a
`manifest.json` (source, URL, date, sha256).

> **Privacy.** A small fetch tells each source *which variants you asked about*
> (an interest signal), but never your genotype. The User-Agent carries no
> identity (`--email` is optional). For a sensitive panel, use `--full` so
> nothing selective is revealed. Never derive the fetch list from your own file.
> See [DESIGN.md](DESIGN.md) D24.

Build a panel from the cache:

```bash
python -m snp_insights build-panel --targets data/targets.carrier.json \
    --cache ~/.cache/snp-insights -o data/panel.carrier.json
```

`--dbsnp` fills coordinates/alleles; association tiers are derived from ClinVar
(carrier) and GWAS (traits). Targets may also set **`effect_allele`** — the
allele associated with the condition — because dbSNP's alt is not always the
risk allele; detection keys on it when present. In small mode ClinVar is fetched
from `variant_summary` (~0.5 GB, downloaded once) so the record is matched to the
curated condition; `--clinvar-mode api` uses the lighter E-utilities instead
(no phenotype). GWAS tiers are derived **per-rsID via Open Targets**
(`--gwas-mode ot`, default — no large download); `--gwas-mode full` downloads the
GWAS Catalog zip (~70 MB) and filters it instead; `--no-gwas` skips GWAS.
**SNPedia is not auto-fetched** (its site blocks programmatic access) — supply a
`rsid<TAB>magnitude` file to `build_panel --snpedia`. `--sizes` HEADs the
full-file URLs to report actual download sizes, and `--full` refuses to pull more
than 5 GB without `--yes` (dbSNP + gnomAD alone are ~90 GB). Full-file landing
pages, if you prefer manual downloads:

- **ClinVar** `variant_summary.txt.gz` — <https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz>
- **dbSNP** GRCh37 VCF `GCF_000001405.25.gz` (large) — <https://ftp.ncbi.nlm.nih.gov/snp/latest_release/VCF/>
- **dbSNP** `RsMergeArch` — <https://ftp.ncbi.nlm.nih.gov/snp/>
- **gnomAD** VCF, GRCh37 — <https://gnomad.broadinstitute.org/downloads>
- **GWAS Catalog** associations TSV — <https://www.ebi.ac.uk/gwas/docs/file-downloads>

Terms (verify the current terms of each source; not legal advice):
**ClinVar/dbSNP** public domain (NCBI; identify yourself, be polite) ·
**gnomAD** free, some datasets carry extra terms · **GWAS Catalog** free
(EMBL-EBI) · **SNPedia** CC BY-NC-SA 3.0 — non-commercial; user-supplied file
only, not auto-fetched · **OMIM** not downloaded (link-only).

### SNPedia (optional, manual)

SNPedia adds a *noteworthiness* score (magnitude) for variants — including many
traits that ClinVar and GWAS don't cover. Its site blocks automated downloads, so
it is **not auto-fetched**. To include it:

```bash
# 1. download SNPedia's data in a browser (its site's Download page)
# 2. convert it to our format (MediaWiki XML export or JSON dump):
python tools/snpedia_to_tsv.py snpedia_dump.xml -o snpedia.tsv
# 3. build with it:
python -m snp_insights build-panel --targets data/targets.traits.json \
    --snpedia snpedia.tsv -o data/panel.traits.json
```

The converter accepts a MediaWiki XML export, a JSON map of title→wikitext, or an
already-correct `rsid<TAB>magnitude` TSV and passes it through. SNPedia is
**CC BY-NC-SA 3.0** (non-commercial); don't redistribute it.

`data/targets.carrier.json` and `data/targets.traits.json` are **draft** starter
sets — verify the rsID↔condition/trait pairings and trim them. Then
`python -m snp_insights check-raw --panel <panel> <raw>` shows which targets your
array actually covers.

## Testing

No dependencies required:

```bash
python tests/test_pipeline.py
```

This runs the core suite plus the staged gates it hooks in. The test files are:

- `tests/test_pipeline.py` — parser, annotator, condition normalization and
  contradiction grouping, ETL robustness, semantic lints, and an end-to-end
  validator accept/reject; it also calls the guard, evidence, category, and CLI suites below.
- `tests/test_evidence.py` — the shared evidence module (condition matching,
  ClinVar selection, tiers).
- `tests/test_category.py` — category-aware association derivation.
- `tests/test_cli.py` — the `snp-insights` CLI (dispatch, `run`, privacy gate,
  tool-module integrity).
- `tests/test_guard.py` — the privacy/publication guard and its self-tests.
- `tests/test_result_block.py` — the build-loop result-block validator (run separately;
  `test_pipeline.py` does not call it).

Each file also runs standalone, e.g. `python tests/test_cli.py`.

## Privacy & safety

- **Never stored or sent:** the raw DNA file, parsed genotypes, `findings.json`,
  and any `panel.*.json` built from a real file are never transmitted and never
  committed. Annotation (Stage 2) is offline; the default narrator (Stage 3) is
  a local model. Only the opt-in online endpoint transmits derived findings, and
  it withholds raw alleles and the file fingerprint.
- **Never committed:** credentials, local config, home paths, generated panels,
  and owner-specific terms — enforced by a deny-by-default `.gitignore`, a
  tracked-file allowlist, and `scripts/guard.py`. CI runs the guard and a
  full-history secret scan; committed hooks mirror them locally.

```bash
git config core.hooksPath hooks     # enable the committed hooks (once)
python scripts/guard.py --full      # privacy/publication guard
```

See [docs/security.md](docs/security.md) for the threat model and control
inventory, and [SECURITY.md](SECURITY.md) to report an issue.

## Status

Early / research. Stages 1–2, the panel ETL, and the Stage 3 runner (local model
by default, with self-repair, template fallback, and an audit artifact) work
end-to-end against fixtures. A single `python -m snp_insights` entrypoint wraps
the whole flow (and `run` chains annotate → narrate), with category-aware
association derivation and condition-aware matching. The ETL has only been tested
against synthetic source files, and Stage 3 has been exercised against the
template path and fixtures, not yet against a live model. Known gaps are tracked
in [DESIGN.md](DESIGN.md#4-design-limitations-and-known-gaps).

## Contributing

Issues and pull requests are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md)
for setup and the required checks, and [DESIGN.md](DESIGN.md) first —
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
