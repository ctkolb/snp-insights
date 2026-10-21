# Contributing

Thanks for considering a contribution. This is a small, careful project —
correctness and the privacy boundary matter more than speed.

## Setup

```bash
git clone https://github.com/ctkolb/snp-insights.git
cd snp-insights
git config core.hooksPath hooks     # enable the committed hooks (once)
python -m venv .venv && source .venv/bin/activate
pip install jsonschema              # optional; enables schema-validation passes
```

## Required checks before you push

```bash
python tests/test_pipeline.py       # tests (includes the guard tests)
python scripts/guard.py --full      # privacy/publication guard
```

If you have [gitleaks](https://github.com/gitleaks/gitleaks) installed, the
hooks also run it. CI runs all of the above plus a full-history secret scan; a
pull request cannot merge until every job is green (see
[`docs/branch-protection.md`](docs/branch-protection.md)).

## The allowlist / denylist model

- **Allowlist.** Every tracked path must be application code, docs, schema, or a
  template — enforced by `scripts/guard.py`. Real data files (`*.csv`, `*.vcf`,
  `*.db`, `*.pdf`, images, archives) are refused outside `fixtures/`.
- **Denylist.** Owner-specific private terms are matched from a **gitignored**
  `.sensitive-terms` file or the `SENSITIVE_TERMS` environment variable — never
  from a tracked file. Do not add real private values to code, docs, tests,
  examples, comments, or commit messages; use invented names.
- Never weaken a guard to make a commit pass. Fix the input, or propose a rule
  change deliberately, with the maintainer's agreement.

See [`docs/security.md`](docs/security.md) for the threat model and details.

## Commit hygiene

- Branch off `main`; never commit on `main` directly.
- Inspect `git status` and `git diff`; stage only intended files.
- Write descriptive messages. Do not include personal data in a message.
- Never push, force-push, or change remote state on the maintainer's behalf.

## AI assistance

If you use an AI assistant, you are responsible for the result. Disclose it with
a trailer in your commit message:

```
Assisted-by: <tool or model name>
```

Review generated code as if you wrote it: it must be correct, licensed, and
free of private data.

## License headers

Every new source file starts with:

```
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
```

Contributions are accepted under `GPL-3.0-or-later` (inbound = outbound).
