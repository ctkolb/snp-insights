# Release roadmap

## v0.3.0 — Biomarker panel expansion

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

Baseline estimate is **8–11 builder and reviewer tickets**. The paired review policy may change that estimate once the stage tiers are assigned. The panel keeps the current result types and deterministic template report. The owner handles the private checkpoint and release tagging.

## v0.4.0 — Disease associations

Approved direction. Define and independently review a disease-association evidence and reporting contract before curating markers. The contract must cover protective and susceptibility findings, cohort and ancestry limitations, and wording that stays at the association level. Marker inclusion depends on the approved contract and source verification.

| Gene or locus | Starting candidate | Condition |
|---|---|---|
| CDKN2B-AS1 / 9p21 | rs10757278 | Coronary artery disease |
| PITX2 | rs2200733 | Atrial fibrillation |
| IL23R | rs11209026 | Crohn's disease |
| ABCG8 | rs4245791 | Gallstone disease |

For ABCG8, apply the existing default exclusion for the palindromic rs11887534 pair. The v0.3.0 LDL finding and v0.4.0 gallstone candidate require their own phenotype-specific evidence.

Estimate **9–13 builder and reviewer tickets**, including contract review and release verification. APOE, pharmacogenomics, and HLA-dependent findings remain separate potential projects.
