# Release roadmap

## v0.3.0 — Test cleanup and biomarker panel expansion

**Status: shipped.** Released as v0.3.0 (merged to main in pull request #17, commit 97b1869, tagged v0.3.0). The panel version is 0.3.0. The package reported 0.2.0 at the tag; the post-release prep corrects it to 0.3.0.

### S0 — Stop test temporary-directory leaks (GitHub issue #14)

Fix test and build-loop scratch cleanup first. Close this stage with independent review before planning biomarker work or capturing public references.

- Give each run one owned temporary root, clean up test fixtures on normal exit and handled failures, and keep the history-guard fixtures isolated while reducing repeated repository copies.
- Add a regression check that detects a deliberately leaked directory. Verify that the full pipeline suite and full privacy guard leave zero new entries in a controlled system temp directory.
- Verify that an interrupted run leaves at most one project-owned temporary directory and that the next sweep identifies it. Document the sweep and its dry-run and explicit approval requirements for deletion. Existing leftovers are owner-managed.

### S1–S3 — Biomarker panel expansion

Approved scope. Evaluate these public markers under the existing [panel curation rules](panel-curation.md) and admit the pairs that meet every applicable gate. A documented exclusion is a valid outcome. Candidate rsIDs are starting points for evidence capture.

| Priority | Gene or locus | Candidate | Reported phenotype |
|---|---|---|---|
| Core | LPA | rs10455872, with rs3798220 evaluated separately | Circulating lipoprotein(a) |
| Core | ABCG8 | rs6544713 | LDL cholesterol |
| Core | GC | rs2282679 | Circulating 25-hydroxyvitamin D |
| Core | CYP2R1 | rs10741657 | Circulating 25-hydroxyvitamin D |
| Core | FUT2 | rs601338 | Total circulating vitamin B12 |
| Core | SCN10A | rs6795970 | ECG PR interval |
| Conditional | FADS1/FADS2 | rs174537 | Circulating arachidonic acid |
| Conditional | MTHFR | rs1801133 | Plasma total homocysteine |

- Evaluate **FADS1/FADS2** as one linked locus and document how the candidate meets the ancestry criterion before admission.
- Evaluate **MTHFR** under the trait rules for total homocysteine. This endpoint supersedes the health-marker scope for rs1801133 from the [v0.2.0 plan](loop-spec.md#v020-run-panel-expansion-decisions-log) for this release.
- Keep **FUT2** wording specific to total circulating B12 and document the evidence on the measured B12 fractions. Keep the other findings specific to their named study phenotypes as well.

Proposed stages

| Stage | Outcome |
|---|---|
| S1 — Evidence and curation | Capture and freeze public evidence. Check GRCh37 coordinates, effect allele, direction, comparison cohorts, independence, and array assayability. Document a disposition for each candidate and obtain owner approval before changing the panel. |
| S2 — Panel rebuild | Apply approved curation decisions, rebuild from pinned public inputs, and verify the resulting snapshot and release-panel tests. Record source provenance and the release version. |
| S3 — Report and release verification | Verify the findings and coverage states end to end with synthetic fixtures. Review wording against the exact phenotypes and run the release gates before the owner checkpoint. |

Baseline estimate is **11–16 builder and reviewer tickets**, with **3–5 for S0** and **8–11 for the panel expansion**. Recalculate the estimate after the stage tiers and paired reviews are set. The panel keeps the current result types and deterministic template report. The owner handles the private checkpoint and release tagging.

## v0.4.0 — Disease associations

**Status: prepared for the owner's release decision.** The disease-association contract and its checkers were added. No disease association met the contract (all four candidates were excluded, with the reasons recorded in docs/panel-curation.md), so the release panel is the unchanged nine-entry panel (seven health entries, two trait entries) at panel version 0.4.0, package version 0.4.0. The report template is unchanged and renders no disease section. The real-data checkpoint, merge, tag, publication and branch protection are owner-only.

Approved direction. Define and independently review a disease-association evidence and reporting contract before curating markers. The contract must cover protective and susceptibility findings, cohort and ancestry limitations, and wording that stays at the association level. Marker inclusion depends on the approved contract and source verification.

| Gene or locus | Starting candidate | Condition |
|---|---|---|
| CDKN2B-AS1 / 9p21 | rs10757278 | Coronary artery disease |
| PITX2 | rs2200733 | Atrial fibrillation |
| IL23R | rs11209026 | Crohn's disease |
| ABCG8 | rs4245791 | Gallstone disease |

For ABCG8, apply the existing default exclusion for the palindromic rs11887534 pair. The v0.3.0 LDL finding and v0.4.0 gallstone candidate require their own phenotype-specific evidence.

Estimate **9–13 builder and reviewer tickets**, including contract review and release verification. APOE, pharmacogenomics, and HLA-dependent findings remain separate potential projects.
