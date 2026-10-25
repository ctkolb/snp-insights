# Build-loop spec: roadmap items 3, 4, 5

Status: APPROVED by the owner on 2026-10-24. COMPLETE: Stages 1 to 5 built, reviewed, and
closed on 2026-10-25 (see `docs/accepted-limits.md` for every accepted limit). Stage plan and decisions for the
adversarial build loop (builder, reviewer, owner). Companion to
[DESIGN.md](../DESIGN.md) and [AGENTS.md](../AGENTS.md). Invented names only;
no real data anywhere in this loop.

## Goal

1. **Item 5, trait matching precision:** match ClinVar and GWAS evidence to the
   *specific curated condition*, not just the rsID.
2. **Item 4, category-aware derivation:** targets carry `category`
   (`carrier` | `trait`) and the association tier is derived per category.
3. **Item 3, single entrypoint:** one `snp-insights` CLI (`fetch`,
   `build-panel`, `check-raw`, `annotate`, `narrate`, `run`) plus
   `pyproject.toml` and a version.

Out of scope for the whole loop: real-data validation (item 1), target
curation (item 2), full-dump ETL (item 6), model benchmarking (item 7), CI
changes (item 8), any change to Stage 3 prose rules or the privacy gate.

## Confirmed defect that motivates Stage 1

`build_panel.load_clinvar` keeps one record per rsID, last row wins, with no
phenotype awareness. A two-row input for one rsID (a thrombophilia record and a
drug-response record) returns the drug-response row if it is listed last. The
phenotype-aware selection exists only in `tools/fetch_reference.py`
(`_select_clinvar_summary`), and `_stars` / `review_stars`, `_sig_rank`,
`_norm_cond`, `_condition_matches` are duplicated or split across the two
files. `load_gwas` counts distinct studies per rsID and ignores the
`DISEASE/TRAIT` column.

## Global rules (every stage)

- Python 3.9+, **standard library only**. No new runtime dependencies.
  `jsonschema` stays optional.
- Offline. No new network call, write outside the declared outputs, or delete.
- Existing tests keep passing unchanged unless a spec decision below says
  otherwise. Never weaken or delete a test.
- `data/panel.sample.json` must still reproduce byte-for-byte from the README
  ETL command (`git diff --exit-code data/panel.sample.json` after rebuilding).
- Do not touch `data/targets.sample.json`, `data/panel.sample.json`,
  `schema/*`, `stage3/*`, or `tools/validate_report.py`,
  `tools/render_report.py` in any stage.
- Findings (`findings.json`) are unchanged: `category` is a **panel-only**
  field and must not appear in findings (the findings schema has
  `additionalProperties: false`).
- Test convention: `check(name, cond)` in `tests/test_pipeline.py`. Gate
  names start with the stage prefix (`S1.`, `S2.`, ...).
- American English. Generic fixtures. Commit trailer `Assisted-by:`.

---

## Stage 1: evidence module and condition-aware matching (STANDARD)

New file `tools/evidence.py` (stdlib only, no I/O except `load_aliases`).
Exact public names (gates import them):

| Name | Contract |
|---|---|
| `norm_cond(text)` | lowercase, non `[a-z0-9]` to space, collapse whitespace, strip; falsy input gives `""` |
| `load_aliases(path=None)` | JSON alias map; default `data/condition_aliases.json` relative to the repo; `{}` if the file is missing; keys starting with `_` ignored by consumers |
| `condition_matches(text, condition, aliases)` | True iff any variant of `condition` (the condition plus every member of its alias group, all passed through `norm_cond`) occurs in `norm_cond(text)` **at word boundaries**; False when `text` or `condition` is falsy. Alias group lookup normalizes both the key and the members |
| `review_stars(status)` | the current `build_panel.review_stars` semantics (4/3/2/1, 0 for empty or "no assertion criteria", `None` for unrecognized non-empty) |
| `sig_rank(sig)` | the current `fetch_reference._sig_rank`, unchanged |
| `select_clinvar(rows, condition, aliases)` | `rows` is a list of dicts with `sig`, `review`, `phenotype`. Rows with empty `sig` are never candidates. **Matched-first (decision D-M, amends D27):** if `condition` is truthy and at least one candidate row has `condition_matches(phenotype, condition, aliases)`, only the matched rows compete; otherwise all candidate rows compete. Within the competing rows, score = `sig_rank*100 + (review_stars(review) or 0)`; highest wins, **first row wins exact ties**. Returns the winning row dict or `None` |
| `clinvar_tier(significance, stars)` | the current `build_panel.assoc_from_clinvar` logic on those two values |
| `gwas_tier(n)` | the current `build_panel.assoc_from_gwas` |
| `count_matching_studies(pairs, condition, aliases)` | `pairs` is a list of `(study_id, trait_text)`; number of **distinct study ids** whose trait matches `condition`; when `condition` is falsy, the distinct study ids over all pairs |

Behavior changes:

- **B1.** `fetch_reference.py` and `build_panel.py` import these from
  `evidence`. The old private names (`_norm_cond`, `_condition_matches`,
  `_select_clinvar_summary`, `_stars`, `_sig_rank`,
  `build_panel.review_stars`, `assoc_from_clinvar`, `assoc_from_gwas`) may
  remain **only as aliases** (`name = evidence.x`) or thin wrappers so the
  existing tests still run. No second implementation may remain.
- **B2.** `build_panel.load_clinvar(path, release, conditions=None, aliases=None)`
  keeps **all** GRCh37 rows per rsID and picks one with
  `evidence.select_clinvar`, using `conditions[rsid]` (a `{rsid: condition}` map)
  when given. Return shape stays `{rsid: {significance, review_stars,
  review_status_text, source_version}}` and gains one key, `phenotype`
  (string, `""` when the column is absent). The panel's `clinvar` object keeps
  exactly its current four keys. Old files without a `PhenotypeList` column
  still load. `main()` passes the conditions from the targets file.
- **B3.** `fetch_reference.write_clinvar_tsv` writes an extra `PhenotypeList`
  column. `fetch_clinvar_summary` returns the chosen phenotype with the
  record; `fetch_clinvar_small` (API mode) has none and writes an empty cell.
  The cache TSV must round-trip through `build_panel.load_clinvar`.
- **B4.** `build_panel.load_gwas_studies(path, wanted)` returns
  `{rsid: [(study_id, trait_text), ...]}`, deduplicated on the pair, in file
  order, trait read from the `DISEASE/TRAIT` column (case-insensitive,
  `""` if absent), study id from the existing `GWAS_STUDY_COLS` fallback.
  `load_gwas` stays and returns the same `{rsid: distinct_study_count}` as today.
- **B5.** `build_panel.build(..., gwas=...)` accepts `{rsid: int}` (legacy, used
  as is) **or** `{rsid: [(study, trait)]}`, in which case the count is
  `count_matching_studies(pairs, target["condition"], aliases)`. `build()` gains
  `aliases=None`. `main()` uses the pairs form. Derivation **order is not
  changed in this stage**.
- **B7 (round 2).** Every text read in `build_panel` (`open_any`, plain and
  `.gz`) decodes with `utf-8-sig`, so a leading byte-order mark never corrupts
  the first header name. This covers ClinVar, GWAS, dbSNP TSV, gnomAD, merges,
  and SNPedia TSV.
- **B8 (round 2).** Free-text fields written to cache TSVs go through one helper
  in `fetch_reference` (`_tsv_field`) that replaces every tab, carriage return,
  and newline with a single space: the ClinVar writer (significance, review,
  phenotype) and the Open Targets GWAS writer (study id, trait). A hostile value
  can never change the number of rows or columns when read back.
- **B9 (round 2).** `evidence.load_aliases` raises `ValueError` naming the key
  when a non-underscore group's value is not a list of strings. `condition_matches`
  and its helper, given an in-memory map with a bare-string value, treat it as a
  one-element list; other non-list values are ignored. Neither ever iterates a
  string character by character.
- **B6.** `data/condition_aliases.json` gains an alias group for every
  `condition` in `data/targets.traits.json`. Aliases are limited to spelling
  variants that GWAS labels plausibly use (for example color/colour,
  hair/hair-color phrasing, hyphen and space variants). No new biology, no
  rsID changes.

Ship gates (each is a named `check`):

- `S1.identity_*`: `fetch_reference` and `build_panel` expose the same function
  objects as `evidence` (identity, not equality) for `norm_cond`,
  `condition_matches`, `sig_rank`, `review_stars`.
- `S1.cond_*`: word boundary (`"g6pdx"` does not match `"g6pd"`); alias hit
  (`"Hemochromatosis type 1"` matches `"Hereditary hemochromatosis"` with the
  repo aliases); case and punctuation insensitive; falsy text or condition is
  False.
- `S1.select_*`: pathogenic beats drug response in either row order; matched
  phenotype beats unmatched at equal significance rank; stars break the
  remaining ties; first row wins an exact tie; empty-significance rows are
  skipped; empty list gives `None`.
- `S1.clinvar_rs6025_both_orders`: a two-row fixture (thrombophilia
  pathogenic, warfarin drug response) yields the thrombophilia record with the
  rows in **either** order; the same function without a condition still picks
  the pathogenic row.
- `S1.clinvar_old_format`: files without `PhenotypeList` and the existing messy
  fixture produce the same significance and stars as before this stage;
  GRCh38 rows are still skipped.
- `S1.clinvar_cache_roundtrip`: `write_clinvar_tsv` then `load_clinvar`
  preserves significance, review, and phenotype; the 2-tuple (no phenotype)
  form works.
- `S1.gwas_*`: `load_gwas` unchanged on `fixtures/sources/gwas.sample.tsv`;
  `load_gwas_studies` pairs and dedupe; with 2 coronary studies, 1 diabetes
  study, `count_matching_studies` gives 2 / 1 / 0 for coronary / diabetes /
  an unrelated trait, and 3 for `condition=None`.
- `S1.build_trait_match`: a trait target whose only GWAS pairs have a different
  trait ends `unknown`, not `single_study`; the legacy `int` form still works.
- `S1.aliases_cover_traits`: every `condition` in `data/targets.traits.json`
  has an alias group, and every one containing "color" has a "colour" variant.
- `S1.select_matched_first` (round 2): a matched `risk factor` row with
  practice-guideline review beats an unmatched `Pathogenic` row; a matched
  `drug response` row beats an unmatched `Pathogenic` row; with no matched row the
  highest significance rank wins as before; with a falsy condition nothing is
  "matched" and the old ranking applies; a matched row with empty `sig` is not a
  candidate and does not suppress unmatched rows. Both row orders.
- `S1.norm_cond_direct` (round 2): `norm_cond("  A-b!! c ")` is `"a b c"`,
  `norm_cond(None)` is `""`, and underscores and slashes become spaces. At least one
  assertion must fail if the punctuation substitution is removed from `norm_cond`.
- `S1.bom_*` (round 2): a BOM-prefixed GWAS TSV, ClinVar TSV, and dbSNP TSV load
  the same results as the BOM-free file; the same for a `.gz` BOM file.
- `S1.tsv_sanitize_*` (round 2): hostile phenotype, significance, review, trait,
  and study values containing tab, CR, and LF written through the writers read back
  with the same row count and column alignment, text whitespace-replaced.
- `S1.alias_*` (round 2): the shipped `data/condition_aliases.json` loads and every
  non-underscore value is a list of strings; a string value in a file passed to
  `load_aliases` raises `ValueError` naming the key; with the map `{"a": "eye"}`:
  `condition_matches("y", "a", m)` is False (no per-character matching; the old
  code returned True), `condition_matches("y", "e", {"A": "eye"})` is False, and
  `condition_matches("an eye test", "a", m)` is True (a string is one alias).
  `condition_matches("e", "e", {"A": "eye"})` is True, because a condition always
  matches itself (an earlier draft of this gate asserted False; that was a spec
  error).
- `S1.panel_sample_reproduces`: the README ETL command regenerates
  `data/panel.sample.json` identically.
- `S1.no_network`: importing `evidence` and `build_panel` opens no socket (check
  that neither module imports `urllib`, `http`, `socket`, `requests`).

Fence: do **not** add `category`, change the derivation order, touch
`annotate.py`, schema, guard, stage3, or targets curation, or create
`pyproject.toml` or any new package directory.

---

## Stage 2: category-aware derivation (STANDARD)

Decisions:

- **D-A.** Targets may carry `category`: `"carrier"` or `"trait"`. Any other
  value, or a non-string, makes `build()` raise `ValueError` naming the rsID;
  `main()` prints it and exits 1 **without writing the output file**.
- **D-B.** Derivation lives in `evidence.derive_association(category, cv,
  gwas_n, cv_matched)` where `cv` is the chosen ClinVar record or `None`,
  `gwas_n` the matching GWAS study count, `cv_matched` whether the ClinVar
  phenotype matches the curated condition (False if the phenotype is empty).
  `cv_tier = clinvar_tier(cv.significance, cv.review_stars)` (None when `cv` is
  None).
  - `carrier`: `cv_tier` or `"unknown"`. GWAS is ignored.
  - `trait`: if `gwas_n >= 1` then `gwas_tier(gwas_n)`; else if `cv` and
    `cv_matched` then `cv_tier` or `"unknown"`; else `"unknown"`. ClinVar
    never overrides GWAS evidence for a trait.
  - `None` (no category): the legacy rule, `cv_tier` or `gwas_tier(gwas_n)` or
    `"unknown"`, and a warning on stderr naming the rsID.
  - An explicit `association` on the target always wins, in every category.
- **D-C.** `category` passes through to the panel variant (as every target key
  does) and is **not** copied into findings. Schema unchanged.
- **D-D.** `data/targets.carrier.json` gets `category: "carrier"` on all 9
  variants and `data/targets.traits.json` gets `category: "trait"` on all 14.
  Nothing else in those files changes. `targets.sample.json` is untouched.

Ship gates:

- `S2.carrier_*`: conflicting 1-star ClinVar with 5 GWAS studies gives
  `conflicting`; 0-star ClinVar with strong GWAS gives `unknown`; 3-star
  pathogenic gives `established`.
- `S2.trait_gwas_wins`: 2 matching GWAS studies plus an unmatched conflicting
  ClinVar gives `replicated`; the same with a **matched** conflicting ClinVar
  also gives `replicated`; 1 matching study gives `single_study`.
- `S2.trait_clinvar_fallback`: 0 matching studies and an unmatched pathogenic
  3-star ClinVar gives `unknown`; with a matched one gives `established`.
- `S2.explicit_wins`: explicit `association` beats derivation for carrier,
  trait, and no category.
- `S2.legacy_unchanged`: with no category, every association in the repo's
  sample-fixture panels is identical to the pre-stage result, and a warning is
  printed once per such variant.
- `S2.invalid_category`: `"Carrier"`, `"other"`, `5`, `[]` each raise
  `ValueError` mentioning the rsID; `main()` exits 1 and creates no file.
- `S2.findings_no_category`: annotating with a panel that has categories
  yields findings with no `category` key anywhere, and (if `jsonschema` is
  installed) they validate against the schema.
- `S2.targets_categories`: all variants in both targets files have a valid
  category; counts are 9 and 14; each variant's keys are the previous key set
  (carrier: `rsid, gene, condition, assayability, cls` plus `effect_allele` where
  present, which is 6 of 9 variants; trait: `rsid, gene, condition, assayability`)
  plus `category`, checked against inline
  literal expectations. **The test must not call git or read history**: the CI
  test job uses a shallow checkout (an earlier draft said "versus the base
  commit"; that was a spec error).
- `S2.build_cv_matched_wiring` (round 2): through `build()` itself (not
  `derive_association` directly), for a `trait` target with 0 matching GWAS
  studies: a ClinVar record whose phenotype does NOT match the condition gives
  `unknown`; one whose phenotype matches (by the condition itself and by an alias)
  gives the ClinVar tier (for example `established` for 3-star pathogenic); a
  record with an empty phenotype gives `unknown`.
- `S2.panel_sample_reproduces`: unchanged.

Fence: no CLI, no `pyproject.toml`, no guard change, no curation changes, no
changes to ClinVar or GWAS parsing beyond what is needed to feed the new
function.

---

## Stage 3: allow the packaging paths in the guard (HIGH, security boundary)

Smallest possible change so Stage 4 can be committed. **Additive only.**

- Add `pyproject.toml` to `ALLOW_EXACT` and `snp_insights/` to `ALLOW_PREFIX`
  in `scripts/guard.py`.
- Add `!/pyproject.toml` and `!/snp_insights/` to `.gitignore`.
- Update the guard's gitignore self-test expectations so those two paths are
  treated as application paths that must not be ignored.
- Do **not** remove or loosen any rule, pattern, size limit, suffix list, or
  exemption. `snp_insights/` is **not** added to `DATA_ALLOWED_PREFIX`.
- Do **not** create `pyproject.toml` or `snp_insights/` yet.

Ship gates (in `tests/test_guard.py`):

- `S3.allows_pyproject` / `S3.allows_package_py`: allowed.
- `S3.refuses_data_in_package`: `snp_insights/x.csv`, `.json`, `.zip`, `.vcf`
  still refused (data-suffix guard).
- `S3.still_refuses_other_root`: `notes.txt`, `data.csv`, `report.md` at the
  root still refused; `snp_insights/.env` still refused (env guard).
- `S3.secret_scan_covers_package`: a decoy secret in `snp_insights/cli.py`
  is flagged.
- `S3.gitignore_selftest`: passes, and fails if either new path is removed
  from `.gitignore` (mutation, performed on a temp copy).
- `S3.additive_only`: reviewer and owner confirm by diff that no existing rule
  line was removed or relaxed.

Round 2 (after review; decisions made by the owner on 2026-10-24: fix only what
Stage 3 introduced; the pre-existing gaps are AL-008 and AL-009):

- **R3-fix.** In `check_gitignore_selftest`, the new `SELFTEST_MUST_NOT_BE_IGNORED`
  loop treats `git check-ignore` exit status 0 as "ignored" (a finding, as today),
  1 as "not ignored" (fine), and **any other status as a finding** whose detail
  says the check itself failed with that status. Verified cause: when
  `snp_insights` is a symlink, `git check-ignore` exits 128 ("beyond a symbolic
  link") and the loop silently passed. The existing loops are not changed.
- `S3.selftest_checkignore_error`: with `guard.repo_root` monkeypatched to a temp
  git repo whose `snp_insights` is a symlink (and whose `.gitignore` is the real
  one), `check_gitignore_selftest()` reports a finding naming
  `snp_insights/cli.py`; with a normal directory it reports none for these paths.
- `S3.gitignore_package_ignores`: in a temp repo with the real `.gitignore`
  (create the files and directories so directory-only patterns apply), these are
  ignored: `snp_insights/.env`, `snp_insights/.env.local`,
  `snp_insights/.sensitive-terms`, `snp_insights/x.pyc` (directly in the package
  root, not inside `__pycache__`), `snp_insights/__pycache__` (the directory),
  `snp_insights/y.private`, `snp_insights/z.local`, and
  `snp_insights/a.generated.json`. Must fail if `!/snp_insights/.sensitive-terms`,
  `!/snp_insights/*.pyc`, or `!/snp_insights/__pycache__/` is appended to the end
  of the copied `.gitignore` (later rules win).

---

## Stage 4: single entrypoint (STANDARD, privacy pass-through scrutiny)

Layout: `snp_insights/__init__.py` (`__version__ = "0.1.0"`),
`snp_insights/__main__.py`, `snp_insights/cli.py`, root `pyproject.toml`. Works
from any working directory via `python -m snp_insights` with the repo on
`PYTHONPATH` or the current directory at the repo root, and via
`pip install -e .` (console script `snp-insights`). Wheel installation outside
the repo is **not supported** (the tools live outside the package); document it.

Decisions:

- **D-E.** Subcommands: `fetch` (`tools/fetch_reference.py`), `build-panel`
  (`tools/build_panel.py`), `check-raw` (`scripts/check_raw.py`), `annotate`
  (`stage2/annotate.py`), `narrate` (`stage3/run.py`), `run`. `--version`
  prints `snp-insights 0.1.0`. Each existing `main()` gains an optional
  `argv=None` parameter passed to `parse_args(argv)`; direct script use is
  unchanged. Sub-tool arguments are forwarded **verbatim**.
- **D-F.** `run RAW PANEL [--out-dir DIR] [--force] [narrate args...]` =
  annotate, then narrate. Output files go in `DIR` (default
  `./snp-insights-out`, created if needed): `findings.json`, `report.md`,
  `report.ir.json`, `report.run.json`. Existing output files are **never
  overwritten** without `--force`: it refuses, exits non-zero, and writes
  nothing. Unknown trailing arguments go to `narrate` verbatim.
- **D-G.** Privacy invariants: `fetch` accepts no raw-file argument (an
  unknown flag exits 2); `run` never adds, removes, or rewrites `--endpoint`,
  `--model`, or `--accept-privacy-risk`; with the default (local) endpoint the
  only network target is localhost; `--endpoint openrouter` without
  `--accept-privacy-risk` exits non-zero with zero HTTP calls.
- **D-H.** `pyproject.toml`: `name = "snp-insights"`, `version` equals
  `snp_insights.__version__`, `requires-python = ">=3.9"`, `dependencies = []`,
  optional extra `schema = ["jsonschema"]`, license `GPL-3.0-or-later`, console
  script `snp-insights = "snp_insights.cli:main"`, build backend `setuptools`.
- **D-I.** The CLI exit code is the sub-tool's exit code. An unknown
  subcommand exits 2. `--help` exits 0 and lists every subcommand.

Ship gates:

- `S4.help_lists_all`, `S4.version`, `S4.unknown_subcommand_exit2`.
- `S4.forward_verbatim`: with each sub-tool's `main` monkeypatched to record
  `argv`, every subcommand receives exactly the user's arguments.
- `S4.fetch_rejects_raw`: `fetch --raw x` and `fetch x.txt` exit 2;
  `fetch --targets <t> --dry-run` makes zero network calls (patch
  `urllib.request.urlopen` to raise).
- `S4.run_end_to_end`: on `fixtures/raw.sample.txt` and
  `data/panel.sample.json` with the model client patched to fail, the four
  output files exist (template fallback), and `urlopen` is never called by
  annotate.
- `S4.run_no_clobber`: second run in the same dir exits non-zero and leaves
  every file byte-identical; `--force` overwrites.
- `S4.gate_passthrough`: `run ... --endpoint openrouter` without the flag exits
  non-zero, zero HTTP calls; with the flag, the forwarded argv contains it
  exactly once and the endpoint and model verbatim; the CLI never injects it.
- `S4.cwd_independent`: runs from a temp working directory.
- `S4.exit_code_propagation`: a sub-tool returning 3 gives CLI exit 3.
- `S4.pyproject_consistent`: version matches `__version__`, console script
  target resolves to a callable, `dependencies` is empty.
- `S4.no_data_in_package`: no tracked file under `snp_insights/` has a
  data-bearing suffix.
- `S4.build_panel_stdout_mode` (accepted limit AL-007): `build_panel.main` with
  no `-o` prints the panel JSON to stdout and exits 0 (also through the
  `build-panel` subcommand); the printed JSON equals the file written with `-o`.
  Once it exists, add its mutation (remove `print(text)`) to
  `scripts/loop_mutations.py`.

Clarifications decided after reading the five tool `main()` functions
(orchestrator decisions, 2026-10-24):

- **D-J.** Dispatch is by hand on the first word of `argv`, not through argparse
  subparsers (REMAINDER handling is unreliable there). Everything after the
  subcommand is forwarded verbatim as a list. `snp-insights`, `snp-insights -h`,
  and `--help` print usage listing every subcommand (exit 0); `--version` prints
  the version (exit 0); `snp-insights <sub> --help` is forwarded to that tool and
  prints the tool's own help. `cli.main(argv=None)` returns an int exit code,
  lets argparse's `SystemExit` propagate for usage errors, and `__main__` does
  `sys.exit(main())`. Sub-tool modules are imported at call time and invoked as
  `module.main(list_of_args)` so tests can patch `module.main`.
- **D-K.** Each existing tool's `main()` gains `argv=None` and calls
  `parse_args(argv)`; that signature change is the only edit allowed in
  `tools/fetch_reference.py`, `tools/build_panel.py`, `scripts/check_raw.py`,
  `stage2/annotate.py`, and `stage3/run.py`. Direct script use stays identical.
- **D-L.** `run RAW PANEL [--out-dir DIR | --out-dir=DIR] [--force] [narrate
  args...]`: the two positionals before any flag are RAW and PANEL; `--out-dir` and
  `--force` are consumed by `run`; everything else is forwarded verbatim to
  `narrate`, **except** that `-o`, `--out`, and `--out=...` are refused (exit 2,
  message says the output location is set by `--out-dir`). `run` calls annotate as
  `RAW PANEL -o DIR/findings.json`, then narrate as `DIR/findings.json <forwarded
  args> -o DIR/report.md`. If annotate fails, narrate is not run and the annotate
  exit code is returned. The no-clobber check happens BEFORE annotate runs and
  covers all four output names (`findings.json`, `report.md`, `report.ir.json`,
  `report.run.json`). `run` prints one reminder line that `findings.json` is
  private health data and stays local, and never prints genotypes.
- **D-M2.** The privacy gate in `stage3/run.py` returns exit code 2 when the online
  endpoint is used without `--accept-privacy-risk`; the CLI propagates it
  unchanged.
- **D-N.** `pyproject.toml` uses the `setuptools` backend with
  `[tool.setuptools] packages = ["snp_insights"]`. Tests must not run `pip` or
  need `tomllib` (absent before Python 3.11): check `pyproject.toml` with plain
  text or regex parsing, and use `tomllib` only if importable.

Round 2 decisions (found by the orchestrator's own smoke test of `run`, 2026-10-24):

- **D-O.** `run` treats any output path that **exists as a symlink** (including a
  dangling one) as existing: the no-clobber check uses `os.path.lexists`, and a
  symlinked output path is refused **even with `--force`** (exit 1, nothing
  written, message names the path). Verified defect: a dangling symlink at
  `report.md` made `run` write through the link to a location outside the output
  directory, with no `--force`.
- **D-P.** If `--out-dir` exists as a file, or the directory cannot be created,
  `run` prints a one-line error to stderr and returns 1, with no traceback and no
  output written.
- **D-Q.** `snp-insights run -h` and `run --help` print `run`'s own usage
  (positionals RAW and PANEL, `--out-dir`, `--force`, the note that other options
  go to `narrate`, and that `-o/--out` is refused) and exit 0. Previously this
  exited 2 with "run needs RAW and PANEL".
- Gates: `S4.run_no_clobber_symlink` (dangling symlink and valid symlink at each
  of the four names: refused, target never created, exit 1, also with `--force`),
  `S4.run_out_dir_is_file`, `S4.run_out_dir_equals_form` (`--out-dir=DIR`),
  `S4.run_default_out_dir` (no `--out-dir`: files land in `./snp-insights-out`
  relative to the working directory), `S4.run_help`.

Round 3 decisions (after the Stage 4 review; ratings are the orchestrator's,
verified by reproduction, 2026-10-24):

- **D-R (private outputs).** `run` sets `os.umask(0o077)` for its whole duration
  and restores the previous umask in a `finally`. Files it creates are mode 0600
  and an output directory it creates is 0700. An output directory that already
  exists keeps its mode. Verified: with umask 022 the four outputs, including
  `findings.json`, were created 0644 (health data readable by other local users).
  Other subcommands are unchanged.
- **D-S (tool-module integrity).** The CLI loads its sub-tools only from this
  repository. (1) `_ensure_tool_paths` puts the four repo directories at the
  FRONT of `sys.path` even if they are already present further back. (2) Before
  importing, if any module whose top-level name equals the name of a `.py` file in
  those four directories is already in `sys.modules` with a `__file__` outside the
  repository root, the CLI refuses (exit 1, message names the module and its
  file) and runs nothing. (3) After importing a tool module, its `__file__` must
  be inside the repository root, else the same refusal. Verified: a decoy `run.py`
  earlier on `PYTHONPATH`, or a decoy `run` already in `sys.modules`, was executed
  instead of `stage3/run.py` (after `findings.json` had been written). The
  attacker model needs control of the process environment, so the orchestrator
  rates this MEDIUM (the reviewer rated it CRITICAL); the fix is small.
- **D-T (`--` separator).** In `run`, everything from the first `--` token on is
  forwarded verbatim and never interpreted by `run` (so `-- --out-dir foo` does
  not change the output directory). The CLI's own `-o <report>` goes immediately
  BEFORE the `--`, so narrate receives `[findings, <args before --> , -o, <report>,
  --, <args after -->]`.
- Gates: `S4.run_private_modes` (umask 022 in the test, restored afterward; the
  four files are 0600 and a created out-dir is 0700; a pre-existing out-dir keeps
  its mode; `run` leaves the process umask unchanged even when it fails),
  `S4.tool_integrity_sys_modules` (a decoy module named `run` in `sys.modules`
  makes `run` and `narrate` refuse with exit 1 and call nothing),
  `S4.tool_integrity_path_order` (a decoy directory placed before the repo
  directories on `sys.path` is not used: the real tool runs),
  `S4.run_double_dash`.

Fence: no change to Stage 3 rules, the gate itself, `validate_report`, schema,
or the guard. No packaging of `tools/` or `stage*/` into a wheel.

---

## Stage 5: documentation close-out (LOW, no reviewer)

README quickstart uses the CLI; `DESIGN.md` gains decisions D29 to D33 (evidence
module, condition-aware matching, category derivation, CLI, packaging limit) and
removes the now-fixed limitations (GWAS per-rsID only, ClinVar last-row);
`AGENTS.md` roadmap and status updated; `docs/accepted-limits.md` finalized.
Free checks only: tests, guard, doc link check by the owner.

---

## Known limits carried into the loop (not fixed here)

- `fetch_reference.load_target_entries` dedupes by rsID, first file wins, so an
  rsID listed in two targets files with different conditions keeps one.
- ClinVar `api` mode has no phenotype, so trait fallback from ClinVar is
  unavailable in that mode (carrier derivation is unaffected).
- Alias files remain hand-maintained; unlisted synonyms do not match.
