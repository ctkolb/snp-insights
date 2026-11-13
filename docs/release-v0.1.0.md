# v0.1.0 — first useful personal report

Planning draft for owner approval. This is a new release run, not a continuation
of the completed stages in `loop-spec.md`.

## Current decision — 2026-11-07 (CI-DEC-01)

Initial CI/support stage uses Python >=3.12, CI Python 3.12 and 3.14 on
ubuntu-24.04. Existing tests, optional schema validation, workflow lint,
privacy/security jobs, and committed hooks are retained. Historical loop
decisions remain historical. Integration and release transition require separate
reviewed gates. Version remains 0.1.0; runtime dependencies remain empty and the
schema extra remains optional.

This initial stage is limited to the support floor, matrix, and matching active
guidance. The floor assertion is revised in a tests-only regression commit before
the support change. Candidate checks and independent review precede separately
authorized local integration and release-branch transition. The complete release
plan is deferred until after that transition; the proposed scope below is retained
as planning context, not an implementation dispatch.

The existing annotated `v0.1.0` tag remains untouched. Its disposition is pending
before release closure planning; no tag creation, replacement, or publication is
authorized. Actual remote protection and hosted checks remain NOT_CHECKED until
owner evidence. See `branch-protection.md` for the owner coordination boundary.

## Objective and agreed preferences

Produce a useful, traceable report from an owner's AncestryDNA text file using
local code, starting with deterministic template narration. Aim for approximately
five everyday traits and five carrier/health-related markers. Fewer are acceptable
when evidence or array coverage is insufficient; counts are goals, not quotas.
Do not require any particular positive finding for success.

Builder: GPT-6.1 Sol. Independent reviewer: DeepSeek V4.1 flash.
Use the current acoding skills with manual owner routing.

## Privacy boundary

Remote models must never see the real DNA file, derived findings, reports,
private logs, hashes, or other private artifacts. Only local code and Ollama may
read those inputs. Real data and outputs must remain outside directories mounted
or otherwise accessible to remote agent sessions, including repository, mailbox,
review exports, and scratch trees. Gitignore alone is insufficient.

The owner performs the real-data run in a separate local environment. Coding and
review sessions use synthetic data only. The owner can confirm local completion
without supplying results. Reproduce failures synthetically before sharing them;
do not request private outputs for debugging. Public-reference fetching uses
curated public targets, never personal genotypes or coverage-derived target lists.

## Proposed stages

1. Prepare and independently review the release contract and panel selection.
   Audit existing draft targets and relevant interpretation paths. Verify each
   included rsID, condition or trait, effect allele and direction, build, strand,
   assayability, and evidence using primary sources. Record source identifiers,
   retrieval dates, rationale, and limitations in generic project records.
   Distinguish disease associations from carrier status; do not label every
   health-related variant a recessive carrier result. Exclude unresolved entries.
2. Build the small mixed panel and verify the template pipeline on synthetic
   inputs. Exercise public-reference fetch/build paths in a separately authorized
   network-enabled environment with no private data. Keep automated tests offline.
   Cover effect-allele interpretation, unsupported calls, missing coverage,
   no-calls, build/strand mismatches, and evidence matching. Fix blockers within
   this release's scope. Independently review consequential interpretation changes.
3. Provide an early owner checkpoint: exact local commands for inspection and
   `run --template-only`, using private outputs outside agent-accessible trees.
   Do not delay this checkpoint for optional narration or cosmetic improvements.
   If array coverage is poor, revise the public starter panel without exposing
   personal coverage details to remote agents; otherwise explicitly accept limits.
4. Finish readable reporting and operational documentation. Explain what was
   examined, coverage and call states, evidence, sources, and limitations. Keep
   traits and health-related results distinct. Verify that the report helps a
   reader understand results rather than only displaying internal state names.
   Preserve traceability and validation requirements. Record accepted limits and
   the owner's local success confirmation without private details.

The builder proposes exact stages, file fences, tests, and review spend before
implementation; the owner approves that plan. Proposed interpretation stages are
HIGH risk. Unrelated documentation may be LOW. Do not bundle HIGH stages.

## Definition of done

- A documented, verified small mixed panel can be built reproducibly from public
  reference inputs; unresolved targets are excluded and exclusions explained.
- Synthetic end-to-end template reports validate and preserve correct coverage,
  allele interpretation, caveats, and citations. Missing markers never imply
  absence of a condition; evidence does not imply diagnosis or absolute risk.
- The owner confirms successful local generation and inspection of a report from
  the real file. Until then, distinguish implementation completion from pending
  real-data validation and do not declare the release complete.
- `python tests/test_pipeline.py` and `python scripts/guard.py --full` pass in
  the approved execution environment. Preserve CI parity and disclose checks
  that need Git metadata or unavailable dependencies rather than claiming parity.
- README documents the mixed-panel workflow, private output locations, template
  operation, and remaining limitations. Version declarations remain consistent
  at `0.1.0` (already declared in the package).
- Finish at reviewed local commits. Remind the owner to create the `v0.1.0` tag
  on the approved release commit, after checking existing tags. No agent tags,
  pushes, opens PRs, or publishes releases.

## Exclusions and process notes

No broad panel expansion, polygenic scores, ancestry inference, diagnosis,
medical recommendations, model benchmarking, full-dump ETL validation, packaging
overhaul, or unrelated security cleanup. No weakening guards or changing the
safety layer without explicit owner approval. Preserve unrelated working edits.

Use this document for release scope and approved plan/decision additions, and
`accepted-limits.md` for accepted limits. Keep operational handoffs and tickets
in the configured external mailbox. The old `orchestrator-prompt.md` is historical
context; its worktree review recipes do not supersede current acoding isolation
and export rules. Existing report validation uses an older result-block format;
check compatibility with current role reports and ticket tooling work if needed.

Open process details for the orchestrator: confirm builder effort, review/session
budget, execution isolation, report-validator compatibility, and public-reference
network procedure before the steps that depend on them. Do not assume these have
already been provisioned or approved.

## Release status (recorded 2026-11-12)

Stages 1 to 4 of this plan are implemented on the release branch and independently
reviewed: the curation method and record (docs/panel-curation.md), the findings
contract extension (schema 1.2.0), the built release panel, the owner-checkpoint
procedure (docs/owner-checkpoint.md), and the readable template report. The accepted
limits are in docs/accepted-limits.md. Not yet done and owner-only: the private
real-data checkpoint, repository branch protection, hosted checks on the release
pull request, and the release tag; the existing v0.1.0 tag is preserved and not
replaced until the owner decides its disposition.

Amendment (recorded 2026-11-12): the Definition of done asks for a small mixed panel. The v0.1.0 panel is health-only: no trait entry met the evidence bar, and counts are goals, not quotas (docs/accepted-limits.md AL-014). The release is complete with a health-only panel once the owner-only steps are done.
