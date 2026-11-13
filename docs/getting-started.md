# Getting started

This page is for someone who has never run SNP Insights. It explains what the tool
does, what you need, how to get your raw file, what each file and command is, how
to read the report, and what to do when something goes wrong. Short sentences,
plain words; every term is defined in the [Glossary](#glossary).

Run every command in this page from the repository root (the folder that holds
`README.md`).

## What this tool does and does not do

SNP Insights reads the raw DNA file that AncestryDNA lets you download. It checks a
short, curated list of markers (called a panel) against public reference
data, and writes a plain-language report. Everything that matters is computed by
code on your computer: which markers were measured, what you carry, how strong the
published evidence is, and which links to show.

In v0.1.0 the report is written by fixed templates, with no language model. That is
the verified path, it needs no network, and every command in this guide that writes
a report uses `--template-only`. An optional narration step can have a language model phrase the
sentences instead (a local model through Ollama by default, or an opt-in online
model). It is built and tested against fixtures but is not verified against a live
model in v0.1.0, and the model may only phrase sentences about results that code
has already computed.

It does **not** diagnose anything, give a personal risk estimate, or replace a
clinician or genetic counselor. A consumer DNA chip measures a tiny part of the
genome (about 0.02%), and a rare result on a chip can be wrong. This is a research
and curiosity tool, not medical advice. The v0.1.0 panel has three health entries
and no trait entries, so most of what you might wonder about is not covered.

## Prerequisites

- **Python 3.12 or 3.14.** Other 3.12+ versions are expected to work. Check with
  `python3 --version`.
- **git** and a terminal.
- **`jsonschema`** (optional). It turns on extra JSON Schema checks. Nothing else
  needs it.
- **Ollama** (optional). Only for narration by a local language model, which is
  not verified against a live model in v0.1.0. Nothing in this guide needs it. The
  verified mode is `--template-only`, which uses no model.

Set up a clean environment inside your copy of the repository:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install jsonschema   # optional
python -m snp_insights --version
```

The last command prints `snp-insights 0.1.0`. Inside the virtual environment,
`python` and `python3` mean the same thing. Outside it, many systems have only
`python3`.

## Getting your raw file

Ancestry lets you download your raw data from your own account. The steps on the
site change over time; this is the summary the project owner recorded, and this
repository does not check it. Open your DNA test, go to its Settings, and choose
the DNA data download. Ancestry prepares a zip file that holds one `.txt` file.

- Save the zip in a **private directory outside the repository**, then unzip it
  there. Never unzip into the repository.
- Your raw file is **private health data.** Keep it, and everything made from it,
  out of the repository, out of shared or synced folders, and out of any directory
  an agent tool can read. See [owner-checkpoint.md](owner-checkpoint.md).

What the file looks like (this example is the synthetic fixture
`fixtures/raw.release.synthetic.txt`, not a real person):

```text
#Invented synthetic raw data for release-panel end-to-end tests; not a real person.
#Data was collected using AncestryDNA array version: TESTARRAY-1
#Data is formatted using AncestryDNA converter version: TESTCONVERTER-1
#Genetic data is provided below as five TAB delimited columns.
#using human reference build 37.1 coordinates.
rsid	chromosome	position	allele1	allele2
rs1800562	6	26093141	A	G
```

- **Comment lines** start with `#`. They name the array version, the converter
  version and the genome build.
- Then one **header row** and one **data row per marker**, in five tab-separated
  columns: `rsid`, `chromosome`, `position`, `allele1`, `allele2`.
- Chromosomes 23, 24, 25 and 26 mean X, Y, PAR and MT. A `0` allele is a no-call.
- The build line `human reference build 37.1` means GRCh37. A file that says
  build 38 is refused. A file that states no build is annotated as GRCh37, and the
  report says so.
- A real file has many more rows than the fixture. This repository does not record
  a size; `check-raw` prints the row count of your file.

Before you do anything else, look at what the tool sees. This command reads the
file offline, hides the allele letters and leaves out the file hash (it uses the
synthetic fixture here; use your own path for a real file):

```bash
python -m snp_insights check-raw fixtures/raw.release.synthetic.txt --panel data/targets.release-panel.json --no-hash
```

## The pieces in plain words

| Name | What it is | Who creates it | Private? |
| --- | --- | --- | --- |
| **raw file** | The `.txt` you download from Ancestry. Marker names and your letters. | You, from your Ancestry account. | **Yes.** |
| **targets file** | The curated list of markers to report on: rsID, gene, condition, effect allele. No evidence yet. | People who curate the panel (this repository). | No. |
| **evidence file** | A curated file of ClinVar records for the release targets: `data/targets.release-evidence.json`. | The curators. | No. |
| **panel** (a snapshot) | A targets file joined with reference data: positions, alleles, evidence, frequencies, and the source and date of each. It is what `annotate` reads. | `build-panel`. | No. |
| **findings.json** | Your raw file compared with the panel: one record per marker with its state, your call and its evidence. | `annotate`. | **Yes.** |
| **report IR** (`report.ir.json`) | The report's intermediate form: the structure and every cited claim. | `narrate`. | **Yes.** |
| **report.md** | The report you read. | `narrate`. | **Yes.** |
| **run record** (`report.run.json`) | An audit record of how the report was made. | `narrate`. | **Yes.** |

Names can mislead. Three kinds of file sit in `data/`:

- `data/targets.sample.json` is a **test and teaching sample**, and `data/panel.sample.json`
  is its built panel. `check-raw` uses that sample panel unless you name another.
- `data/targets.carrier.json` and `data/targets.traits.json` are **draft starter
  sets**. They are not reviewed and are not for reports.
- The **v0.1.0 release set**: `data/targets.release.json` (the curated targets),
  `data/targets.release-evidence.json` (the evidence file) and
  `data/targets.release-panel.json`. Despite its name, the last one is a built
  **panel**, not a targets file. It is the file you give to `check-raw` and `run`.

## What each command reads and writes

| Command | Reads | Writes | Uses the network? |
| --- | --- | --- | --- |
| `check-raw` | Your raw file, and a panel (`--panel`). | The inspection to the screen, or to `-o`. | No. |
| `annotate` | Your raw file and a panel. | `findings.json` (`-o`, or the screen). | No. |
| `narrate` | `findings.json`. | `report.md`, `report.ir.json` and `report.run.json`, named after `-o`. | No with `--template-only`. A local model is on your own machine. Yes only with `--endpoint openrouter` after you accept the privacy risk. |
| `run` | Your raw file and a panel. | Four files in `--out-dir`: `findings.json`, `report.md`, `report.ir.json`, `report.run.json`. | Same as `narrate`. |
| `build-panel` | Targets and reference files. | A panel. | No. |
| `fetch` | Targets files. | A cache of reference files. | **Yes.** |

`fetch` and `build-panel` are for building panels; see [reference-data.md](reference-data.md).
For v0.1.0 you never need them. `annotate`, `check-raw` and `run` with
`--template-only` make no network call at all.

Here are the four commands you will use, on the synthetic fixture. The output goes
to a temporary directory outside the repository, so `run` does not warn:

```bash
OUT=$(mktemp -d)
python -m snp_insights annotate fixtures/raw.release.synthetic.txt data/targets.release-panel.json -o "$OUT/findings.json"
python -m snp_insights narrate "$OUT/findings.json" --template-only -o "$OUT/report.md"
python -m snp_insights run fixtures/raw.release.synthetic.txt data/targets.release-panel.json --out-dir "$OUT/run" --template-only
```

`narrate` writes its three files next to the `-o` path. `run` does both steps and
writes all four files. It never overwrites existing output unless you add
`--force`.

## Reading the report

The template report has these parts, in order:

- **Provenance:** the input hash, the array, the build, and the date and source of
  every reference snapshot.
- **Summary:** how many markers were examined and measured, then caveats and
  "Read more" links to public records.
- **Health-related: carrier status** and **Health-related: associations:** one
  line per marker.
- **Evidence and sources:** what each evidence tier means.
- **Limitations:** what this report cannot tell you.

The text in square brackets after a claim, such as `[f_065a9790e8ec · state]`,
names the finding and the field in `findings.json` the claim comes from. A claim
with no source cannot appear. These are short excerpts of a real run on the
synthetic fixture (`...` marks skipped lines). Its genotypes are invented:

```report
## Summary
- one carrier status marker was examined: one was measured, zero were not measured, and zero returned no call or an uninterpretable result. [f_065a9790e8ec · state]
...
- Prothrombin thrombophilia (F2): two copies of the effect allele A were detected. Evidence tier: replicated, from ClinVar's review level: ClinVar lists this record as Pathogenic with two review stars (criteria provided, multiple submitters, no conflicts); this is a review level, not a count of independent studies. This is an association with Prothrombin thrombophilia; this report does not diagnose the condition. [f_b7dae4647a6b · state] [f_b7dae4647a6b · call.zygosity] [f_b7dae4647a6b · result_type] [f_b7dae4647a6b · effect_allele] [f_b7dae4647a6b · condition] [f_b7dae4647a6b · evidence.association] [f_b7dae4647a6b · evidence.clinvar.significance] [f_b7dae4647a6b · evidence.clinvar.review_stars] [f_b7dae4647a6b · evidence.clinvar.review_status_text]
...
- Factor V Leiden thrombophilia (F5): both copies match the reference at this position; the effect allele was not found in the genotype. [f_bfc3a4f653bb · state] [f_bfc3a4f653bb · condition] [f_bfc3a4f653bb · rsid] [f_bfc3a4f653bb · gene] [f_bfc3a4f653bb · effect_allele]
```

**Call states.** Each marker ends in one of these:

- **Detected,** or **matches the reference:** the array measured the position and
  gave a usable genotype.
- **No call:** the position is on the array, but it returned no result.
- **Uninterpretable:** it was measured, but the letters match neither known allele.
- **Not measured:** the array does not include the marker. This gives no
  information about whether you carry the allele. **Not measured means no
  information, not absence.**

This is how the report words the last case, from the second synthetic fixture,
`fixtures/raw.release.synthetic.states.txt`:

```report
- Factor V Leiden thrombophilia (F5): this marker was not measured by this array. That gives no information about whether the effect allele is present. [f_bfc3a4f653bb · state] [f_bfc3a4f653bb · condition] [f_bfc3a4f653bb · rsid] [f_bfc3a4f653bb · gene] [f_bfc3a4f653bb · effect_allele]
```

**Evidence tiers** come from the public record, not from your result:
**established** (ClinVar review with three or four stars), **replicated** (two
stars, or two or more matching GWAS Catalog studies), **single study** (one star
or one study), **conflicting**, and **unknown**. A tier is a review level, not a
count of independent studies.

The report never gives a diagnosis or a personal risk estimate.

**The run record.** `report.run.json` records how the report was made. On a
`--template-only` run it shows `"model": null`, `"attempts_used": 0` and
`"used_fallback": true`. That last value only means the template path produced the
report, as you asked. It does not mean that anything failed. Outside
`--template-only`, the same value means a model's output could not be used, so the
template report was written instead.

## Glossary

- **SNP:** a single-letter difference in DNA that people can have. Pronounced "snip".
- **rsID:** the name of a known variant, such as `rs6025`. The number is assigned
  by dbSNP.
- **genotype:** the two letters you carry at one position, one from each parent.
- **allele:** one version of a variant. You have two alleles at each position.
- **effect allele:** the allele a panel entry is about, the one the evidence links
  to the condition.
- **no-call:** the chip could not read the position. A raw file shows it as `0`.
  It means "unknown", not "normal".
- **genome build (GRCh37):** the version of the human reference sequence that
  positions refer to. This project uses GRCh37, and `annotate` refuses a file whose
  stated build differs from the panel.
- **carrier:** a person with one copy of a variant that causes a condition only
  when two copies are present. One copy is not the condition itself.
- **ClinVar review stars:** how well reviewed a ClinVar record is, from zero to
  four stars. They are a review level, not a count of studies.
- **allele frequency:** the share of people in a reference group who carry an
  allele. gnomAD supplies it.
- **array:** the chip that measures a fixed list of markers in your sample. It is
  not a full sequence of your genome.
- **panel:** the curated markers plus the reference data joined to them, saved as a
  snapshot file.
- **tier:** the evidence tier: established, replicated, single study, conflicting
  or unknown.

## Troubleshooting and exit codes

Most refusals leave your files untouched. These were checked by running them
against the synthetic fixture, unless the line says it was read from the code.

- **`python: command not found`, or an old Python.** Use `python3`, and check
  `python3 --version` for 3.12 or newer. `pyproject.toml` requires Python 3.12 or
  newer. The code does not check the version at run time, so an older Python can
  fail with an error that does not mention the version (read from the code; not
  run on an old Python).
- **`No module named snp_insights`.** You are outside the repository. Change to
  the repository root, or put it on `PYTHONPATH`.
- **A refusal with exit code 1: output already exists.** `run` never overwrites.
  It prints the files in the way and writes nothing. Pick a new `--out-dir`, or add
  `--force` if you mean to replace them.
- **A refusal with exit code 1: symlink or file.** `run` refuses an output file
  that is a symlink (exit code 1, even with `--force`) and an `--out-dir` that
  exists as a file (exit code 1). A symlink used as `--out-dir` that points to a
  directory is not refused: `run` follows it and writes there. Use a normal
  private directory as `--out-dir`, not a symlink. The inside-the-checkout warning
  below compares resolved paths, so it also fires for a symlink that points into
  the checkout, but keeping the output where you think it is is up to you.
- **A refusal with exit code 2: wrong options.** `run` refuses `-o` and `--out`;
  use `--out-dir`. `narrate` or `run` with `--endpoint openrouter` and without
  `--accept-privacy-risk` prints what would be sent and stops: nothing is sent.
  With `run`, `findings.json` is already in `--out-dir` at that point. `fetch`
  without `--targets` or `--full`, an unknown flag, and `check-raw` on a missing
  file also exit with code 2.
- **`check-raw` shows the wrong panel.** It defaults to the sample panel, not the
  release panel. Pass `--panel data/targets.release-panel.json`.
- **`WARNING: the output directory is inside the repository checkout`.** `run`
  still works, but the private output now sits in your checkout. Choose a
  directory outside the repository.
- **`template IR failed validation (bug)`.** With `--template-only`, `run` and
  `narrate` build the report from fixed templates and check it against the same
  rules as a model's report before anything is rendered. This message means the
  tool's own template report failed that self-check. It is a bug in the tool, not
  in your file. No report is written and the command stops with exit code 1 (`run` has
  already written the findings file). In v0.1.0 the message is followed by one
  violation line per problem, each starting with a rule code, then ids, numbers or
  words from the check. This example comes from a deliberately broken test report,
  not from a real file:

  ```text
  template IR failed validation (bug):
    R1: s_summary/cl_summary_coverage: number '42' not found in any cited field (invented value?)
  ```

  At most 20 lines are shown, then `... and N more`. The lines never contain your
  genotypes. To report the bug, copy only the violation lines, or only the rule
  codes, and never the findings file, the report or your raw file. Look at each
  line first and leave out anything that is a file path. If you can, reproduce it
  with a synthetic file and share that instead.
- **No `jsonschema`.** Nothing breaks; it only turns on extra checks.

| Exit code | Meaning |
| --- | --- |
| 0 | Success. |
| 1 | A refusal: existing output, an output file that is a symlink, an `--out-dir` that is a file, a failed integrity check of the tool files, a template report that fails its own check, or a `--full` download over the 5 GB limit without `--yes`. |
| 2 | A usage error or the privacy gate: bad or missing options, `-o` with `run`, an online endpoint without `--accept-privacy-risk`. |

## Next steps

- Run your own file with the shipped release panel: the README section
  [Release panel and your own file](../README.md#release-panel-and-your-own-file),
  and the private procedure in [owner-checkpoint.md](owner-checkpoint.md).
- Learn where the knowledge comes from, or rebuild the panel:
  [reference-data.md](reference-data.md) and [panel-curation.md](panel-curation.md).
- Know the limits: [accepted-limits.md](accepted-limits.md) and the README
  section Known limitations.
- Understand the privacy design: [security.md](security.md) and
  [DESIGN.md](../DESIGN.md).
- Contribute: [CONTRIBUTING.md](../CONTRIBUTING.md).
