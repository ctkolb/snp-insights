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
7. **history** — the branch name and the commit messages of an explicit range
   (default `main..HEAD`); see [History scan](#history-scan).

```bash
python scripts/guard.py --staged   # fast: staged files only (pre-commit)
python scripts/guard.py --all      # every tracked file (default)
python scripts/guard.py --full     # --all + self-test + history (pre-push/CI)
python scripts/guard.py --hash "some private term"   # print its sha256: digest
```

Exit status is nonzero on any finding. Findings print a path and line only —
**never** a matched secret or private term.

### History scan

`--full` scans the branch name and the commit messages of a range. The range is
`refs/heads/main..HEAD` by default; the options below are accepted only with an
explicit `--full`, and any other combination (including `--all`, `--staged`,
`--hash` or no mode) is a usage error:

```bash
python scripts/guard.py --full --history-base <40-hex commit>   # scan <commit>..HEAD
python scripts/guard.py --full --history-branch <name>          # detached HEAD only
```

- `--history-base` takes exactly 40 lowercase hex digits (no abbreviation or
  revision expression). It is resolved once to a commit (an annotated tag is
  peeled), must be an ancestor of `HEAD`, and the range is then bound to commit
  IDs, so a moving branch cannot change it mid-run. An empty range passes and is
  reported as `selected=0`; it is never evidence of coverage.
- On an attached `HEAD` the branch name is read from the full symbolic ref
  (exactly `refs/heads/` stripped). A detached `HEAD` has no name: pass
  `--history-branch` (a caller assertion, validated as a legal branch name and
  used only as text) or the scan reports `history-context` and an incomplete
  receipt. The messages are still scanned. Supplying it on an attached `HEAD`
  is a usage error.
- Every full run prints a receipt:
  `guard: history selected=N scanned=M complete=yes|no`. `N` is the number of
  commits in the range, `M` the number whose message was fully read and scanned.
  `complete=yes` requires every Git step to succeed and `M == N`. Content
  findings still fail the run even when the receipt is complete; `unknown` or
  `no` never proves a clean history.
- Git failures (not a repository, unborn `HEAD`, shallow clone, missing or
  non-ancestor base, unreadable object, timeout, undecodable text, an
  inherited-environment refusal) are `history-git` findings and exit 1, never a
  clean empty result. Messages are decoded strictly; Git is called with
  replacement objects and signature display disabled, without a shell, with a
  10 second limit per call. Exit 2 is a usage error.
- Diagnostics use fixed text and counts. They do not echo branch names, commit
  messages, arguments, Git's stderr, paths or tracebacks, and argument errors
  print fixed usage text only. This covers the local guard. Hosted runner logs
  (checkout output, environment and argument echoes) are outside the guard's
  control.
- `PATH` and the `git` executable it selects are trusted host inputs. The guard
  resolves `git` once at startup and uses that executable for every history
  call; it makes no claim of resistance to a hostile `PATH`.
- The final re-check detects `HEAD` or the default base moving during the scan,
  but it is not a lock: a move away and back, or a concurrent edit, can escape
  it. Audited runs should have a single writer. Offline means the tests use
  local paths only; the managed sandbox has network capability and does not
  enforce it, and nothing here claims stronger isolation.
- Inherited `GIT_*` environment. The history scan classifies every inherited
  `GIT_*` name and never prints a name or value: `GIT_PREFIX`, `GIT_EXEC_PATH`
  and 22 enumerated names that cannot change what a history read sees are
  ignored (`GIT_EDITOR`, `GIT_SEQUENCE_EDITOR`, `GIT_TEMPLATE_DIR`, `GIT_PAGER`,
  `GIT_PAGER_IN_USE`, `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_AUTHOR_DATE`,
  `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL`, `GIT_COMMITTER_DATE`, `GIT_SSH`,
  `GIT_SSH_COMMAND`, `GIT_ASKPASS`, `GIT_EXTERNAL_DIFF`, `GIT_DIFF_OPTS`,
  `GIT_TRACE`, `GIT_TRACE_SETUP`, `GIT_TRACE_PACKET`, `GIT_TRACE2`,
  `GIT_TRACE2_EVENT`, `GIT_TRACE2_PERF`; exact names, no wildcard); `GIT_DIR` and
  `GIT_WORK_TREE` must resolve to the repository found from the current
  directory and are then dropped; five names are accepted only with their fixed
  value (`GIT_OPTIONAL_LOCKS=0`, `GIT_TERMINAL_PROMPT=0`, `GIT_CONFIG_NOSYSTEM=1`,
  `GIT_CONFIG_SYSTEM=/dev/null`, `GIT_CONFIG_GLOBAL=/dev/null`); every other
  `GIT_*` name is refused with `history-git` ("inherited Git environment not
  permitted"). That includes `GIT_CONFIG_PARAMETERS`, which `git -c key=value
  push` sets, and any name not listed above, including names added by future Git
  versions until each is reviewed. Ignoring a name here does not sanitize or
  change the outer push. Git calls run with a copy of the environment without any
  `GIT_*` name.

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

The history scan in `guard.py --full` accepts the environment Git gives a hook
(`GIT_PREFIX`, `GIT_EXEC_PATH`, and `GIT_DIR` / `GIT_WORK_TREE` when they name
this repository), ignores the enumerated names listed in the inherited `GIT_*`
item above, and refuses any other inherited `GIT_*` variable with a generic
message. `git -c key=value push` sets `GIT_CONFIG_PARAMETERS`, so repeat the
push without `-c`. Do not work around a refusal with `--no-verify`.

A push from a detached `HEAD` is refused (no branch context); push from an
attached branch. The hook runs `tests/test_pipeline.py` before the guard, so
those steps still see an inherited environment the guard has not yet
validated; this is a documented residual, not an accepted limit.

## 5. CI

`.github/workflows/ci.yml` runs three separate jobs on pushes and PRs to
`main`, all with `permissions: contents: read`:

1. `test` — `python tests/test_pipeline.py` on Python 3.12/3.14, plus actionlint.
2. `privacy-guard` — `guard.py --full` on the exact event commit with
   `fetch-depth: 0`. A small fixed dispatch in the workflow reads the runner's
   event JSON as data and passes `--history-base` (a push's `before`, or a pull
   request's base commit) and `--history-branch` (`main`, or the pull request's
   head ref) as argv. It refuses new, deleted, forced or zero-`before` pushes, a
   stale or inconsistent pull-request merge commit, and any other event.
3. `secret-scan` — gitleaks over full history, run from a pinned release binary
   (`--redact` keeps values out of logs).

The `SENSITIVE_TERMS` repository secret is optional; the guard passes when it is
unset. Third-party actions are pinned to commit SHAs; Dependabot keeps the pins
current (see `.github/dependabot.yml`).

### CI trust assumptions

- **Same-repository pull requests are trusted with `SENSITIVE_TERMS`.** This
  repository is solo-owned and the secret holds `sha256:`-hashed terms only.
  Workflow and guard code in a same-repository pull request can read the secret
  during the `privacy-guard` job, and the owner accepts that. Revisit this
  before anyone else gets push access.
- **Fork pull requests do not receive the secret.** The built-in patterns and the
  synthetic denylist tests still run, but owner terms are not checked there; that
  is a known coverage gap, closed by running the guard locally before merge.
- The workflow does not use `pull_request_target` or `workflow_run`, and no
  secret is added or made conditional on the event.
- Considered and rejected: providing the secret only on `push` to `main`. It
  would keep it away from pull-request code but delay owner-term findings until
  after merge.

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
| History / branch-name scan | present; tested offline, hosted runs not yet observed | `scripts/guard.py` |
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
