# Security & privacy

This is the detailed companion to the short safety contract in
[`AGENTS.md`](../AGENTS.md). Read it when you are changing the safety layer,
not every session.

SNP Insights is a **local-first genetic tool**. The raw DNA file and the derived
`findings.json` are health-relevant personal data. The whole point of the design
is that they stay on the machine; every control here exists to keep that true
even when a human or an agent makes a mistake.

## 1. Threat model

What we defend against (personal-project scale, not enterprise):

| Threat | Example | Primary control |
|---|---|---|
| Accidental publication of personal data | raw DNA, `findings.json`, a `panel.*.json` built from a real file | `.gitignore` deny-all + guard allowlist + data-suffix guard |
| A stray force-add | `git add -f AncestryDNA.txt` long ago or now | guard allowlist (runs in hooks and CI) |
| Credential leak | `OPENROUTER_API_KEY` pasted into code or history | guard secret patterns + gitleaks |
| Machine-specific detail | a home path, hostname, or real page title in a commit | guard pattern scan + denylist |
| Owner-identifying term | a real name/city/handle in code or a commit message | hashed denylist (gitignored file + CI secret) |
| A guard quietly disabled | someone edits `.gitignore` to un-ignore output | guard `.gitignore` self-test |
| A skipped local hook | hooks not installed in a clone | CI jobs + branch protection |

What we explicitly do **not** defend against: a determined owner, a compromised
GitHub account, or a public zero-retention claim by a model provider. The
online narration path is a risk *reduction*, not a privacy guarantee.

## 2. Data classification

| Class | Examples | Where it lives | Tracked? |
|---|---|---|---|
| Application code/schema | `stage2/`, `stage3/`, `tools/`, `scripts/`, `schema/` | repo | yes |
| Synthetic fixtures | `fixtures/**` (invented rsIDs/genotypes) | repo | yes |
| Curation/inputs | `data/targets.*.json`, `data/condition_aliases.json`, `data/panel.sample.json` | repo | yes |
| **Real genetic data** | raw AncestryDNA `.txt`, `findings.json`, `report*.md/json` | working dir / local | **no** |
| **Derived panels** | `data/panel.carrier.json`, `data/panel.traits.json` | working dir | **no** |
| Reference cache | `~/.cache/snp-insights` | outside repo | **no** |
| Owner terms | `.sensitive-terms` | local, gitignored | **no** |
| Local config | `.env` | local, gitignored | **no** |

The **allowlist is authoritative** and lives in `scripts/guard.py`. `.gitignore`
is deny-by-default (`/*` then explicit re-includes), so a new file is ignored
until it is deliberately allowlisted.

## 3. The guard

`scripts/guard.py` — stdlib only, deterministic. It checks:

1. **allowlist** — every tracked path is application code/docs/template.
2. **data-suffix** — `.csv`, `.tsv`, `.vcf`, `.db`, `.sqlite`, `.pdf`, images,
   archives, and `.json` outside `fixtures/`, `data/`, `schema/`, `harness/`
   are refused.
3. **large-file** — tracked files over 1 MB are refused.
4. **secret/PII patterns** — private-key blocks, cloud/provider key shapes,
   `NAME=value` secret assignments, home paths, cloud-sync paths, internal hosts.
5. **denylist** — owner-specific terms, plain or `sha256:<hex>`.
6. **`.gitignore` self-test** — sensitive paths must be ignored, application
   paths must not be (and must exist/be tracked).
7. **history** — the current branch name and commit messages since `main`.

```bash
python scripts/guard.py --staged   # fast: staged files only (pre-commit)
python scripts/guard.py --all      # every tracked file (default)
python scripts/guard.py --full     # --all + self-test + history (pre-push/CI)
python scripts/guard.py --hash "some private term"   # print its sha256: digest
```

Exit status is nonzero on any finding. Findings print a path and line only —
**never** a matched secret or private term.

### Denylist model

The real list is **never committed** (committing it would leak the terms it
protects). It comes from:

- `.sensitive-terms` (gitignored), one term per line; and/or
- the `SENSITIVE_TERMS` environment variable (newline-separated), set as a
  GitHub **repository secret** for CI.

Plain terms match case-insensitively. A `sha256:<hex>` entry matches a
lowercased whole word whose SHA-256 is `<hex>`, so the term itself never appears
in the list, the repo, or CI logs. Start from
[`../.sensitive-terms.example`](../.sensitive-terms.example).

## 4. Hooks (install once per clone)

Hooks are committed under `hooks/`, not `.git/hooks/`:

```bash
git config core.hooksPath hooks
```

- `hooks/pre-commit` — staged guard + `gitleaks protect --staged`.
- `hooks/pre-push` — `tests/test_pipeline.py`, `guard.py --full`, and
  `gitleaks detect` over history.

Both skip the external scanner gracefully if gitleaks is absent and warn that
CI remains the backstop. Hooks are a convenience; **CI and branch protection
are the enforcement.**

## 5. CI

`.github/workflows/ci.yml` runs three separate jobs on pushes and PRs to
`main`, all with `permissions: contents: read`:

1. `test` — `python tests/test_pipeline.py` on Python 3.9/3.12, plus actionlint.
2. `privacy-guard` — `guard.py --full` with `fetch-depth: 0`.
3. `secret-scan` — gitleaks over full history, run from a pinned release binary
   (`--redact` keeps values out of logs).

The `SENSITIVE_TERMS` repository secret is optional; the guard passes when it is
unset. Third-party actions are pinned to commit SHAs; Dependabot keeps the pins
current (see `.github/dependabot.yml`).

## 6. Audit matrix

Status as of the hardening pass. "Verified" = exercised by a canary (see §8).

| Control | Status | Location |
|---|---|---|
| `.gitignore` deny-by-default | present & verified | `.gitignore` |
| `.gitattributes` / `.editorconfig` | present | repo root |
| Fail-fast `.gitignore` self-test | present & verified | `scripts/guard.py` |
| Tracked-file allowlist | present & verified | `scripts/guard.py` |
| Data-suffix guard + fixture exception | present & verified | `scripts/guard.py` |
| Large-file guard | present & verified | `scripts/guard.py` |
| Secret/PII pattern scan | present & verified | `scripts/guard.py` |
| Hashed denylist (local + CI secret) | present & verified | `.sensitive-terms*`, CI |
| History / branch-name scan | present & verified | `scripts/guard.py` |
| Guard tests | present & verified | `tests/test_guard.py` |
| Committed hooks | present | `hooks/` |
| CI test / privacy / secret jobs | present | `.github/workflows/ci.yml` |
| Branch protection | **owner action needed** | `docs/branch-protection.md` |
| Native GitHub secret scanning | **deferred** (needs GHAS on private) | — |
| CodeQL / dependency-review | **deferred** (needs GHAS on private) | — |
| Author-email in history | **owner action needed** | `.mailmap` documents it |

## 7. Deliberate non-goals

Deferred for a solo personal project: SBOM, SLSA,
cosign, OpenSSF Scorecard, mandatory commit signing, multiple overlapping secret
scanners, DAST/fuzzers/full SAST suites, and any paid/GHAS-only feature. We also
do not add a second scanner in a category we already cover.

## 8. Verifying the layer

Every guard has been proven to fail on a throwaway branch, then pass after the
canary was removed: a dummy secret-shaped string, a denylist term, a
`sample.csv` outside fixtures, a `.gitignore` edit that un-ignores an output,
and a denylist term in a commit message. Full history has been scanned with
gitleaks and is clean.

## 9. If something leaks anyway

Deleting a file from the working tree does **not** remove it from history.
Rotate the credential first, then decide whether history must be rewritten —
only with the owner's explicit approval, and never as an automated step.
