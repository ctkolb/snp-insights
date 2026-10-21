# AGENTS.md

Guidance for working in this repo. See also the global agent rules (never push;
never work on `main`; commit locally when warranted). Project design and known
limitations live in [DESIGN.md](DESIGN.md); usage lives in [README.md](README.md).

## What this is

SNP Insights turns a raw AncestryDNA file into readable, **traceable** genetic
findings. Stages 1–2 (parse + annotate) are local; Stage 3 (narration) is local
by default (Ollama) and online only behind an explicit flag. The model writes
prose only — code owns numbers, citations, caveats, and contradictions.

## Conventions & environment

- **Python**: run tests with `python tests/test_pipeline.py` (no framework, no
  deps). `jsonschema` is optional (enables schema-validation passes).
- **Commit** coherent changesets with descriptive messages; **never push**; if on
  `main`, branch first. Current working branch: `add-gpl3-license`.
- **Ollama** binds IPv4 only; the client uses `http://127.0.0.1:11434/v1`.
- Reference cache default: `~/.cache/snp-insights` (gitignored, outside the repo).
- Generated artifacts `fixtures/*.generated.*` are gitignored — don't commit them.
- Tests are offline; live API calls are not part of the suite (run manually).

## Layout

```
stage2/   ancestry.py (parser), annotate.py (deterministic annotator)
stage3/   run.py (IR + self-repair + template fallback; local model default)
tools/    build_panel.py (ETL), fetch_reference.py, validate_report.py,
          render_report.py, prompt.py, harness.py, caveats.py, references.py,
          llm.py, snpedia_to_tsv.py
scripts/  check_raw.py (inspect a real file offline + self-checks)
schema/   findings.schema.json, report_ir.schema.json
data/     targets.*.json (curation), panel.*.json (snapshots), condition_aliases.json
fixtures/ synthetic raw/findings/report/source fixtures
```

## Status (what works)

- Stages 1–2, panel ETL, Stage 3 (skeleton + full modes, self-repair, template
  fallback, `run.json` audit) all work against fixtures.
- Live-verified reference sources: **dbSNP** (variation API), **ClinVar**
  (`variant_summary` phenotype-aware and E-utilities), **gnomAD** (GraphQL),
  **GWAS via Open Targets** (per-rsID) and the GWAS Catalog full-file filter.
- **SNPedia**: cannot be auto-fetched (bot WAF); user-supplied file only, with
  `tools/snpedia_to_tsv.py` to convert a manual download.
- 87 tests passing; `data/panel.sample.json` reproduces exactly from the ETL.

## NEXT STEP (do this first, next session)

Run the **full local pipeline on the real AncestryDNA file** with a fetched
carrier panel — the first real end-to-end report. Nothing here is sent online.

```bash
# 1. fetch reference data for the carrier targets (small mode; ClinVar summary
#    is phenotype-aware ~0.5 GB; GWAS via Open Targets needs no download)
python tools/fetch_reference.py --targets data/targets.carrier.json \
    --gwas-mode ot --cache ~/.cache/snp-insights

# 2. build the carrier panel from the cache
python tools/build_panel.py --targets data/targets.carrier.json \
    --cache ~/.cache/snp-insights -o data/panel.carrier.json

# 3. see which targets the array actually covers
python scripts/check_raw.py /path/to/AncestryDNA.txt --panel data/panel.carrier.json

# 4. annotate locally, then narrate locally (no network)
python stage2/annotate.py /path/to/AncestryDNA.txt data/panel.carrier.json -o findings.json
python stage3/run.py findings.json --model qwen2.5:14b -o report.md
```

Watch for: parser errors on the live APIs at real panel size; `effect_allele`
strand-mismatch warnings from `build_panel`; any `not_covered` targets that
suggest the panel/target set needs adjusting. Paste the output back for analysis.

## Roadmap to beta

Definition of beta: a user can clone the repo, fetch/build a panel, run the
pipeline end-to-end on their own file, and get a validated, traceable report
locally, with tests green and a single documented entrypoint.

Priority order (rough):

1. **Real-data validation** (the NEXT STEP above). Shake out live parsers at
   panel scale; fix anything that breaks; confirm states look right.
2. **Curate a usable panel.** Review `data/targets.carrier.json` and
   `data/targets.traits.json` (currently DRAFT): verify rsID↔condition, fill
   `effect_allele`, drop shaky entries, grow to ~20 carrier / ~30 traits.
3. **Single entrypoint CLI** (e.g. `snp-insights run <raw>` and `... fetch`,
   `... build-panel`) so the multi-script flow becomes one tool. Add
   `pyproject.toml`, a console script, and a version.
4. **Category-aware association derivation.** Add a `category`
   (`carrier` | `trait`) to targets and steer derivation: carriers prefer
   ClinVar; traits prefer GWAS. Today a weak/conflicting ClinVar record can
   override a strong GWAS trait signal (e.g. `rs1805007`).
5. **Trait matching precision.** GWAS/ClinVar matching is currently per-rsID,
   not per rsID+trait; use `traitFromSource`/`PhenotypeList` + the condition
   aliases to match the specific trait. Expand `data/condition_aliases.json`.
6. **Full-dump ETL paths.** The small-set/API paths are validated; exercise the
   real full files (dbSNP VCF, gnomAD VCF, RsMergeArch) at least once.
7. **Stage 3 model choice.** Benchmark local models (qwen2.5:14b, others) on
   skeleton mode with a golden set; pick and document the default. Consider
   stronger models via `--endpoint openrouter` for those who opt in.
8. **Tests & CI.** Add an integration test (stage2 → stage3 template on
   fixtures); add a GitHub Actions workflow running `tests/test_pipeline.py`;
   consider a hygiene check.
9. **Docs polish.** Troubleshooting (Ollama not running, API 429s, WAF), the
   manual SNPedia flow, and an explicit "not medical advice" reminder in the
   report and README.
10. **Packaging/release.** License already set (GPL-3.0-or-later). Tag a beta,
    write a changelog, sanity-check the privacy story for the opt-in online path.

## Known gotchas

- dbSNP ref/alt is assembly-oriented; the risk allele is the curated
  `effect_allele`, not dbSNP's alt (see `rs6025`).
- ClinVar `esearch` can return unrelated variants; selection filters by gene.
- gnomAD/Open Targets use GRCh38 internally; dbSNP small-set uses GRCh37
  coordinates for the panel.
- The online path is opt-in and requires `--accept-privacy-risk`; it withholds
  raw alleles and the file hash by default.
- SNPedia is CC BY-NC-SA 3.0 (non-commercial) and is never redistributed.
