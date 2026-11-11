# Owner checkpoint: a real-file run you keep to yourself

This is the procedure for the owner's private checkpoint of the v0.1.0 release:
one local run of the pipeline against the owner's own raw AncestryDNA file, with
the output read locally and nothing shared. Every path below is a placeholder;
use your own private values and never paste real ones into a tracked file.

Nothing here is medical advice, and no result is a diagnosis.

## Prerequisites (one time)

- A private directory outside every agent-accessible tree. It must not be the
  repository, the mailbox, a review export, a scratch tree, a cloud-sync folder,
  or any path mounted into an agent session. In the commands below this
  directory is written `$PRIV`; create it with mode `700` (`chmod 700 "$PRIV"`).
- A clean clone or export of the approved release commit, outside those trees.
  You may use the same checkout but never point `--out-dir` into it.
- Python 3.12 or 3.14 (`python3 --version`). No network is needed for either
  command below.
- A copy of the raw file under `$PRIV`; never copy it into the checkout.

## Commands

Record the commit id (only the id, nothing else):

```
cd <clone-of-release-commit>
git rev-parse HEAD
```

Inspect the file first: offline, alleles redacted, no file hash. The release
panel is named explicitly, because `check-raw` defaults to the sample panel:

```
python3 -m snp_insights check-raw "$PRIV/raw.txt" --panel data/targets.release-panel.json --no-hash
```

Run the pipeline: no model, no network, template-only narration:

```
python3 -m snp_insights run "$PRIV/raw.txt" data/targets.release-panel.json --out-dir "$PRIV/out-<commit>" --template-only
```

Read the result locally (never move or copy it out of `$PRIV`):

```
less "$PRIV/out-<commit>/report.md"
```

## What the four output files are

`run` writes four files into `--out-dir` (created if needed):

- `findings.json` — structured findings and health-relevant data. It always
  contains the raw-file SHA-256 in `provenance.input_hash`; `--keep-input-hash`
  does not remove it from this file. In template-only/local runs, `report.md`
  also includes the input hash, and `report.run.json` records it.
  `report.ir.json` contains the findings-file hash.
- `report.md` — the human-readable report.
- `report.ir.json` — the report's intermediate representation.
- `report.run.json` — the run audit record.

A directory the run creates is mode `0700`; the four files are mode `0600`, so
the output stays private to your user. `run` never overwrites existing output
without `--force`. All four files contain private health-relevant data.

## No-sharing rule

Send the orchestrator one line and nothing more: the commit id, the phrase
"report generated and inspected locally", and one outcome word: `ok`,
`coverage-poor`, or `defect-suspected`.

No report text, rsIDs, genotypes, hashes, states, or counts. Do not share the
raw file, `findings.json`, any `report.*` file, run logs, or a coverage list.
If you suspect a defect, reproduce it with a synthetic file of the same shape
for your own diagnosis. Do not share the reproduction; report only the
one-line outcome above. A reproduction built only from invented data is not
private data; you may offer it if you choose, but it is never required and
never derived from the real run.

## Aggregate adequacy rule

Whether the panel is adequate is the owner's aggregate judgment from counts only.
This release has no trait entries, so a trait-count cutoff cannot distinguish
coverage in v0.1.0. Consider the aggregate measured health-entry count and other
locally observed aggregate coverage totals, then choose the outcome yourself.
Do not share per-marker coverage.

## Current release facts

The v0.1.0 release panel has three health entries (risk or carrier) and no trait
entries. No reserves exist for v0.1.0, so a coverage-poor outcome is reported
and decided by the owner; no reserve swap is possible in this release. If you
report `coverage-poor`, that is the recorded outcome, not a failure of the run.
