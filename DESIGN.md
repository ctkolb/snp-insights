# Design notes

This document records the design of SNP Insights: what it does, why it is built
this way, who made each decision, and where it is known to fall short. It is the
canonical companion to the [README](README.md). Decisions are attributed to
"User" or "Model" with the date they were agreed.

This is a research and curiosity tool. It is **not** medical advice, a
diagnostic device, or a clinical-grade genetic test.

---

## 1. Architecture and the privacy boundary

The pipeline has three stages:

| Stage | Runs | Input | Output |
|---|---|---|---|
| **Stage 1 — Ingest** | Local | Raw AncestryDNA `.txt` | Parsed genotypes (in memory) |
| **Stage 2 — Annotate** | Local | Raw file + panel snapshot | `findings.json` |
| **Stage 3 — Narrate** | Local by default (online opt-in) | `findings.json` | `report_ir.json` → `report.md` |

The **privacy boundary sits between Stage 2 and Stage 3**. Raw DNA never leaves
the machine. By default, `findings.json` does not leave either: Stage 3 runs a
**local** model (Ollama). An **online** model is available but opt-in only, and
requires an explicit acknowledgment flag (see D0).

Stage 3 is a four-step loop, each step enforced by code rather than by prompt:

```
findings.json ──▶ [model] ──▶ report_ir.json ──▶ validator ──▶ renderer ──▶ report.md
                             (claims + citations)   (the leash)    (deterministic)
```

The model authors **prose**. Facts, numbers, caveats, citations, and
contradictions are owned by code. If the model cannot produce a valid report
within the attempt budget, a deterministic **template** report (Option C) is
rendered instead, so a report is always produced.

### Privacy decision (revised: local by default)

Three options were considered:

| Option | Description | Trade-off |
|---|---|---|
| A | Runtime online | Best narration; `findings.json` transits vendor infrastructure |
| **B (selected)** | Runtime local (Ollama, Apple Silicon) | Zero external transmission; narrator quality depends on the local model |
| C | No LLM; template-render `findings.json` | Zero hallucination surface; less readable |

**Decision (User, 2026-10-20; revised same day):** **Option B is the default.**
An earlier decision selected A, but on review the user exposed the core issue:
an online model *cannot* be private — the derived, health-relevant findings
**must** be transmitted. Option A offers risk *reduction*, not privacy. Because
the architecture confines the model to narration (Stage 2 already did the
reasoning), a small local instruct model is sufficient, and the validator +
self-repair + template fallback absorb its weaknesses.

**Option A is retained only as an explicit opt-in**, guarded by D0.

---

## 2. The hard rules and how they are enforced

The rules are not instructions to the model; they are checks in
`tools/validate_report.py`. An IR that violates them cannot be rendered.

| Rule | Statement | Enforcement |
|---|---|---|
| **R1** | Confidence must be computed, never generated | Every number in claim text must appear in a cited field; otherwise rejected |
| **R2** | Three-state reporting (extended in D6) | State-specific caveats required per cited finding |
| **R3** | Evidence grades carry through | Only `established` evidence may use strong wording; every other tier forbids definitive/causal language |
| **R4** | Recommendations are informational, not prescriptive | Prescriptive phrase blocklist |
| **R5** | Contradictions get flagged | Every contradiction in `findings.json` must appear in the report |
| **R6** | Standing caveat required | Every section must carry the `array_limits` caveat |
| **R7** | Claim traceability | Every claim cites a resolvable `finding_id` + `field_path`; every finding is cited or explicitly omitted |

The validator is the **hallucination leash**: the model cannot invent a
percentage, drop a contradiction, omit a caveat, prescribe treatment, or make a
claim with no source.

Rule 2 also carries a **semantic-fidelity lint**: claim text must not describe a
variant as present/detected unless its state is `detected`, must not imply
absence for `not_covered`/`not_assayable`, and must not use sequencing
terminology (this is array genotyping). See D15.

---

## 3. Design decisions

### D0 — Privacy gate for the online path
**Decision (User, 2026-10-20).** The online endpoint is opt-in and refuses to
run without an explicit `--accept-privacy-risk` flag; without it, the runner
prints a warning enumerating exactly what would be transmitted and exits
non-zero. In addition, the online payload withholds the raw allele letters
(`call.allele1`/`allele2` → null) and the raw-file fingerprint
(`provenance.input_hash`), unless explicitly overridden. These are **reductions,
not privacy**: only a local model (B) or no model (C) keeps findings on the
machine.

### D1 — Structured confidence, no aggregate number
**Decision (Model proposed, User approved, 2026-10-20).** Confidence is emitted
as a structured object of *named* sub-scores (`annotation_mapping`,
`array_reliability`), never a single percentage. A lone "82% confidence" invites
false precision and can be relabeled by the narrator. Every number must carry a
machine-readable label and a field path, and the validator checks the value
against the cited field.

### D2 — Orthogonal coverage and call axes
**Decision (Model proposed, User approved, 2026-10-20).** "Is this position on
the chip?" (coverage) and "did we get a call?" (call) are independent. Collapsing
them loses cases. The derived report states are:

| State | Meaning |
|---|---|
| `detected` | Called; genotype shows the variant |
| `covered_reference` | Called; homozygous reference at this position |
| `covered_nocall` | On chip; genotyping returned `0 0` |
| `covered_uninterpretable` | Measured; alleles match neither reference nor alternate (see D6) |
| `not_covered` | Position absent from the array manifest |
| `not_assayable` | Locus no SNP array can call (repeat expansions, CNVs) |

`not_covered` is **not** evidence of absence — absence from the array is not
absence of the variant.

### D3 — Strand ambiguity is a curator flag, not an allele rule
**Decision (Model proposed, User approved, 2026-10-20).** A site is marked
`strand: ambiguous` when a curator flags it in the panel, not automatically
because its alleles are palindromic. AncestryDNA reports the forward strand and
the panel carries forward-strand reference/alternate alleles, so orientation is
normally resolvable; a pure palindromic rule over-flags (e.g. both rs1799945 and
rs1333049 are C/G but only rs1333049 is curator-flagged).

### D4 — Deterministic annotation; no runtime fetch
**Decision (User chose snapshot, Model recommended, 2026-10-20).** Annotation
data is a **build-time versioned snapshot** (`data/panel*.json`), not a live
runtime fetch. This keeps Stage 2 genuinely local, makes runs reproducible and
offline-capable, and avoids leaking genotypes through annotation queries. Any
lookup queries by rsID/position only, never by the user's genotype.

### D5 — v1 annotation sources
**Decision (User, 2026-10-20).** v1 uses the minimal useful triad, all
free/public:

- **dbSNP** — rsID↔position reconciliation, merge map (public domain)
- **ClinVar** — clinical significance and 0–4 review stars (public domain)
- **gnomAD** — allele frequency, which drives `rarity_class` (free, Broad)

Deferred: ClinGen, CPIC/PharmGKB, GWAS Catalog. License constraints:
**SNPedia** is CC BY-NC-SA 3.0 (non-commercial) and must be isolated in its own
layer; **OMIM** forbids redistribution and is excluded (link-only at most).

### D6 — Fourth call state: `uninterpretable`
**Decision (User approved, 2026-10-20).** A called position whose alleles match
neither the reference nor the alternate allele (e.g. a covered indel reported as
`I`/`D` against base reference/alternate) is `covered_uninterpretable` with
`call.state = "uninterpretable"`. Previously it fell through to
`covered_nocall`, which was semantically wrong.

### D7 — Report IR + validator + deterministic renderer
**Decision (Model proposed, User approved, 2026-10-20).** The model emits a
structured IR (claims, each with `finding_id` + `field_path` citations), which is
validated then rendered deterministically. This is Option A for prose and Option
C for guarantees.

### D8 — Contradictions computed deterministically
**Decision (Model proposed, User approved, 2026-10-20).** Stage 2 detects
contradictions (grouped by identical `condition` string with differing evidence
grades) and emits explicit objects; the narrator reports them and never
reconciles them.

### D9 — Caveats are a registry, not model text
**Decision (Model, 2026-10-20).** Caveat wording lives in `tools/caveats.py`.
The model selects caveat IDs; the renderer expands them. The model can neither
write nor drop caveat text.

### D10 — No imputation
**Decision (User, 2026-10-20).** Imputed/proxy genotypes are out of scope; only
directly genotyped positions are reported.

### D11 — Stable finding IDs
**Decision (Model, 2026-10-20).** `finding_id` is deterministic:
`f_` + first 12 hex of `sha256(rsID)` (or `gene:chrom:pos` when no rsID), so IDs
are reproducible across runs.

### D12 — External-LLM notice
**Decision (Model, 2026-10-20).** Every rendered report carries a standing
notice that it was synthesized by an external model from local findings, so a
shared report discloses its provenance.

### D13 — Self-repair loop and template fallback
**Decision (User, 2026-10-20).** The runner re-prompts the model with the
validator's specific violations for up to N attempts (default 3). If no attempt
validates, a deterministic template report (Option C) is rendered, so a report is
always produced — and never an unvalidated one.

### D14 — Run audit artifact
**Decision (User, 2026-10-20).** Every run writes `report.md`, `report.ir.json`,
and `report.run.json`, the last recording endpoint, model, attempts used,
per-attempt violation codes, the fallback flag, payload-reduction flags, and the
findings hash.

### D15 — Skeleton narration mode (default)
**Decision (User, 2026-10-20).** Stage 3 has two modes. In `skeleton` (default),
**code owns the report structure** — sections, citations, caveat selection, and
contradiction reporting — and the model writes only one sentence per claim. In
`full`, the model authors the entire IR.

Rationale: benchmarking showed the full-IR task is both slow and error-prone for
small local models — `ministral-3:8b` took 2m24s and produced 10 R1 and 9 R7
violations. Skeleton mode reduced this to ~20s with zero violations, because
omission is structurally impossible and no numbers are needed. A per-claim
fallback replaces any sentence that still violates the rules with the
deterministic template sentence.

Benchmark (`fixtures/findings.generated.json`, same validator):

| model | mode | wall | violations | prose claims |
|---|---|---|---|---|
| ministral-3:8b | full | 144s | 19 | n/a (fell back) |
| ministral-3:8b | skeleton | ~20s | 0 | 10/10 |
| qwen2.5:14b | skeleton | ~42s | 0 | 10/10 |

This added the Rule 2 semantic-fidelity lint (D15): the 8B model described array
genotyping as "sequencing" and called an uninterpretable call "detected" — errors
no number/grade check catches.

### D16 — Condition normalization for contradictions
**Decision (User, 2026-10-20).** Contradiction grouping maps condition labels to
a canonical key via `data/condition_aliases.json` before comparing, so
"Haemochromatosis" and "Hereditary hemochromatosis" are treated as the same
condition. This keeps contradiction detection deterministic while tolerating
common label variants.

### D17 — Test suite
**Decision (User, 2026-10-20).** A dependency-free test runner
(`tests/test_pipeline.py`) covers the parser, annotator states, condition
normalization, messy-input ETL, semantic lints, and an end-to-end validator
accept/reject. Run with `python tests/test_pipeline.py`.

### D18 — dbSNP merge map
**Decision (User, 2026-10-20).** The ETL can ingest dbSNP RsMergeArch
(`--dbsnp-merge`) into the panel's `merges` map. Stage 2 canonicalizes both panel
and file rsIDs through it, so a retired rsID on either side matches its current
form; applications are recorded in `annotation_mapping.basis`.

### D19 — Sex-chromosome handling
**Decision (User, 2026-10-20).** Stage 2 infers sex from the file (Y calls and X
heterozygosity) and records it in `provenance.inferred_sex`. Zygosity is adjusted
accordingly: X and Y calls are `hemizygous` in inferred males, MT calls are
`homoplasmic`, PAR uses the array's chromosome-25 label, and a Y call in an
inferred female is `covered_uninterpretable`.

### D20 — Code-generated reference links
**Decision (User, 2026-10-20).** Each finding carries `references` — external
links generated by code from the finding's identifiers (dbSNP, ClinVar, SNPedia,
gnomAD, OMIM, MedlinePlus Genetics, GeneReviews). The narrator never writes URLs,
so a link cannot be hallucinated, and the report points readers to authoritative
sources instead of interpreting variants itself. gnomAD links are omitted for
indels and loci without a simple SNP representation. The renderer adds a
**Read more** list per section from these, not from the model.

### D21 — Evidence-strength tiers
**Decision (User, 2026-10-20).** The `association` field is a five-tier ladder,
not a binary:

| Tier | Meaning |
|---|---|
| `established` | Guidelines / expert consensus / strong replication |
| `replicated` | Multiple independent studies agree; no consensus yet |
| `single_study` | One study only |
| `conflicting` | Studies disagree |
| `none` | Assessed; no known link |
| `unknown` | Not assessed (no source data) |

Only `established` permits strong (definitive/causal) wording; Rule 3 blocks it
for every other tier. Under option C, defaults are derived from sources: ClinVar
review stars map to tiers for carrier/medical findings, and GWAS Catalog study
counts drive the trait default, with SNPedia as an optional secondary signal.
Curators may override any value.

### D22 — Reference sources and coordinate sourcing
**Decision (User, 2026-10-20).** The ETL can fill coordinates/alleles from dbSNP
(`--dbsnp`, a GRCh37 VCF or a normalized TSV, streamed and filtered to the
target rsIDs), derive trait association tiers from the GWAS Catalog (`--gwas`),
and attach an optional SNPedia magnitude (`--snpedia`, kept isolated for its
non-commercial license). Targets may therefore carry only `rsid`, `gene`,
`condition`, and `assayability`, removing any hand-coded coordinates. Draft
starter target sets are provided for carrier screening and traits.

### D23 — Separate reference-fetch step
**Decision (User, 2026-10-20).** Reference data is downloaded by
`tools/fetch_reference.py` into a local cache (default `~/.cache/snp-insights`),
never committed and never fetched during Stage 2. Default mode is *small*: it
reads the targets' rsIDs and pulls only those records via each source's API;
`--full` downloads the complete official files instead. A `manifest.json` records
source/URL/date/sha256 for provenance. SNPedia (non-commercial) requires
`--accept-license`; OMIM is never downloaded. Full downloads are HEAD-size-checked
and refuse >5 GB without `--yes`; measured sizes: ClinVar 0.46 GB, dbSNP 28 GB,
gnomAD exomes 63 GB, GWAS zip 73 MB, RsMergeArch 0.15 GB (~92 GB total).

### D24 — Reference-fetch metadata exposure
**Decision (Model, 2026-10-20).** Small-set fetching tells each source (NCBI,
Broad, EBI, SNPedia) *which variants were requested*, plus IP/timestamp/UA — an
**interest signal, not a genotype**. The User-Agent carries no identity by
default (`--email` is optional). Two guardrails: (1) the fetch list is taken from
the curated targets and **must never be derived from the user's genotype or
file**, which would turn metadata leakage into genotype leakage; (2) for a
sensitive panel, `--full` (download everything) removes the selective signal at
the cost of bandwidth. The local narration path adds no further external party;
only the opt-in online LLM does.

### D25 — Trait association: GWAS full-filter and the `unknown` tier
**Decision (User, 2026-10-20).** GWAS Catalog has no per-rsID API wired, so small
mode downloads its full associations file (~70 MB zip) once and filters to
the target rsIDs (`--no-gwas` opts out). The association ladder gains `unknown`
(not assessed) so a curated trait with no source data is not mislabeled `none`
(which means "assessed, no known link"). `fetch_reference.py --sizes` HEADs the
full URLs to report actual download sizes.

---

## 4. Design limitations and known gaps

### Data and biology
- **Array coverage.** Consumer arrays genotype ~0.02% of the genome, are
  chip-dependent, and are not diagnostic grade. Absence is not negation.
- **No per-call quality metric.** AncestryDNA provides no probe-intensity or
  quality score, so call state is binary (called / no-call); no call-quality
  sub-score is possible.
- **Rare-variant PPV collapse.** Array sensitivity/specificity exceed 99% for
  common variants, but positive predictive value falls sharply for rare
  pathogenic heterozygous calls (Weedon et al., *BMJ* 2021: ~16% confirmed). A
  detected rare pathogenic variant must be flagged for clinical-grade
  confirmation, not acted on.
- **Structurally unmeasurable loci.** Repeat expansions (e.g. HTT, FMR1) and
  copy-number variants cannot be called from SNP-array data.
- **No phasing.** Heterozygous vs homozygous is available; compound
  heterozygosity and phase are not, which limits recessive reasoning.
- **Sex chromosomes.** Sex is *inferred* from Y calls and X heterozygosity — a
  heuristic that may misinfer when X/Y data is sparse. In inferred males, X and Y
  calls are reported `hemizygous`; MT is `homoplasmic`; PAR is represented by the
  array's chromosome-25 rows. A Y call in an inferred female is marked
  `covered_uninterpretable`. The inferred sex is recorded in
  `provenance.inferred_sex`.
- **Strand.** Palindromic sites remain a silent-error risk; curated flagging is
  conservative, not exhaustive.

### Pipeline
- **Uninterpretable semantics.** `covered_uninterpretable` correctly separates
  "measured but unreadable" from "not measured", but tri-allelic sites and
  strand-flip ambiguity are not distinguishable within it.
- **Contradiction grouping** normalizes condition labels via a small alias file
  (`data/condition_aliases.json`) so differently-worded labels for the same
  condition are compared; synonyms not in that file are still not matched.
- **dbSNP merges** are applied when an RsMergeArch file is supplied to the ETL
  (`--dbsnp-merge`); without it, matching falls back to position. The
  `rsHigh -> rsLow` direction is the common convention and is assumed (override
  with `--merge-direction`); verify against your dbSNP build.
- **Marker counts vary by source** (community reports differ from vendor
  statements); the manifest is always derived from the user's file, never
  hardcoded.
- **Evidence wording** is enforced by regex lints (phrase blocklist plus
  semantic-fidelity construction checks), not a full grammar — good enough to
  catch "1-star → confirmed", sequencing terminology, and presence/absence
  framing errors, but not exhaustive.
- **Annotation ETL** (`tools/build_panel.py`) joins curated targets with dbSNP,
  ClinVar, gnomAD, and GWAS Catalog (and optional SNPedia) into a panel snapshot;
  it is implemented and idempotent. It is tested against synthetic fixtures
  including messy inputs; parsing the full real dumps end to end is still
  untested. Starter target sets for carrier/traits are drafts and need review.

- **Reference links** are built from rsID/gene/condition and may resolve to
  search pages or gene-level pages rather than the exact variant; their targets
  and availability are outside the project's control.

- **Reference fetching** (`tools/fetch_reference.py`) is implemented but has not
  been exercised against the live APIs; endpoints/response shapes may need
  adjustment.
- **GWAS association tiers** count distinct studies per rsID, not per rsID+trait,
  and ignore sample size and p-value; treat trait tiers as rough. GWAS absence
  yields `unknown`, not `none`.

### Model and privacy
- **Refusals and hedging.** Health/genetics content can trigger refusals or
  softening of evidence; the harness scores this.
- **Non-determinism.** Unless temperature is 0 and the provider is stable, the
  same `findings.json` yields different prose. Golden-output comparison is
  planned.
- **Provider retention on OpenRouter** varies per routed upstream and may change
  or be disabled without notice; the runner requests only zero-retention,
  no-data-collection providers, but this is contractual and unverifiable. It
  applies only to the opt-in online path; the default local path transmits
  nothing.
- **Local model quality.** The default local narrator may be less fluent and need
  more repair attempts; the template fallback (D13) guarantees a valid report but
  with reduced readability.
- **The returned report is also sensitive** and may be logged by the vendor.
- **Re-identification.** Sharing a report discloses health inference even
  without raw DNA.
- **Regulatory.** Consumer-genomic disease interpretation sits near FDA/FTC
  health-claim lines; "research tool" framing is not a legal shield.

---

## 5. Decision log

| ID | Decision | Owner | Date |
|---|---|---|---|
| D0 | Privacy: local model by default; online opt-in requires an explicit risk-acknowledgment flag | User | 2026-10-20 |
| D1 | Structured confidence, no aggregate number | Model / User | 2026-10-20 |
| D2 | Orthogonal coverage/call axes | Model / User | 2026-10-20 |
| D3 | Strand ambiguity is a curator flag | Model / User | 2026-10-20 |
| D4 | Build-time snapshot, no runtime fetch | User / Model | 2026-10-20 |
| D5 | v1 sources: dbSNP + ClinVar + gnomAD | User | 2026-10-20 |
| D6 | Fourth call state `uninterpretable` | User | 2026-10-20 |
| D7 | Report IR + validator + renderer | Model / User | 2026-10-20 |
| D8 | Deterministic contradiction detection | Model / User | 2026-10-20 |
| D9 | Caveat registry, not model text | Model | 2026-10-20 |
| D10 | No imputation | User | 2026-10-20 |
| D11 | Stable deterministic finding IDs | Model | 2026-10-20 |
| D12 | External-LLM notice in every report | Model | 2026-10-20 |
| D13 | Self-repair loop + Option-C template fallback | User | 2026-10-20 |
| D14 | Run audit artifact (`report.run.json`) | User | 2026-10-20 |
| D15 | Skeleton narration mode (default): code owns structure, model writes sentences | User | 2026-10-20 |
| D16 | Condition normalization (alias file) for contradiction grouping | User | 2026-10-20 |
| D17 | Dependency-free test suite (`tests/test_pipeline.py`) | User | 2026-10-20 |
| D18 | dbSNP merge map (RsMergeArch) applied in Stage 2 | User | 2026-10-20 |
| D19 | Sex-chromosome handling (inferred sex, hemizygous/homoplasmic) | User | 2026-10-20 |
| D20 | Code-generated reference links per finding | User | 2026-10-20 |
| D21 | Five-tier evidence-strength ladder (adds `replicated`) | User | 2026-10-20 |
| D22 | dbSNP coordinate sourcing + GWAS/SNPedia sources | User | 2026-10-20 |
| D23 | Separate `fetch_reference.py` small-by-default cache step | User | 2026-10-20 |
| D24 | Reference-fetch metadata exposure + guardrails | Model | 2026-10-20 |
| D25 | GWAS full-filter in small mode + `unknown` association tier | User | 2026-10-20 |
