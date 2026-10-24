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
| AL-005 | S1 | Review round 2 used 35 tool calls against a cap of 20. The result block failed the cap check; the report was accepted anyway because the reviewed commit, clean tree, and findings were verified independently. | LOW | Re-running would cost another review for no new information. | 2026-10-24 | A reviewer repeatedly ignores the cap; then tighten the prompt or switch reviewers. |
| AL-006 | S2 | Two equivalent mutants survive: `if cv and cv_matched:` to `if cv_matched:` and dropping `t.get("condition")` from the `cv_matched` expression. Both are redundant guards (`cv_matched` already implies a ClinVar record, and `condition_matches` returns False for a falsy condition), so no test can distinguish them. | LOW | Equivalent behavior; removing the redundancy is not worth a review round. | 2026-10-24 | Someone changes `condition_matches` to return True for a falsy condition, or `cv_matched` stops implying `cv`. |
| AL-007 | S2 | `build_panel.main()` stdout mode (no `-o`) has no test: removing `print(text)` is not caught. The behavior is older than this loop. | LOW | Unrelated to category logic; covered instead by a required gate in Stage 4 (`S4.build_panel_stdout_mode`). | 2026-10-24 | Stage 4 closes without that gate, or `build-panel` is changed to default to a file. |
