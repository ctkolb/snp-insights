# Accepted-limits register

One line per accepted known defect, declined second review, surviving mutation,
or narrowed scope. A stage does not close with an unrecorded limit. Owned by the
owner; kept current by the orchestrator during the build loop.

| ID | Stage | What was accepted | Severity | Why | Date | Would matter later if |
|---|---|---|---|---|---|---|
| AL-001 | all | `load_target_entries` dedupes by rsID across targets files (first wins), so an rsID listed under two conditions keeps one. Carried in, not fixed by this loop. | LOW | Out of scope for items 3 to 5; no current target file has duplicates. | 2026-10-24 | A curated rsID is listed as both a carrier and a trait target. |
| AL-002 | S1 | ClinVar `api` mode carries no phenotype, so ClinVar-based trait fallback is unavailable in that mode. | LOW | The E-utilities summary lacks the field; summary mode is the default. | 2026-10-24 | Someone uses `--clinvar-mode api` for traits that rely on ClinVar. |
| AL-003 | S1 | Condition aliases are hand-maintained; unlisted synonyms do not match. | LOW | Matching must stay deterministic and offline. | 2026-10-24 | A new target's GWAS labels use wording absent from `data/condition_aliases.json`. |
| AL-004 | S1 | `stage2/annotate.py` keeps its own copy of the alias loader and condition normalizer, without the value validation added to `tools/evidence.py`. A malformed alias group (a bare string) would be iterated per character when grouping contradictions. | LOW | `stage2/` is outside this loop's fence; a repo test now checks the shipped alias file is well-formed. | 2026-10-24 | The alias file is edited by hand and a bad value is committed without the test being run. |
