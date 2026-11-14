# Release panel curation

Status: curated, 34 rows

This document defines how markers are chosen for the release panel
(`data/targets.release.json`) and how each decision is recorded so that it can be
checked offline. It contains the method, the fixed record tables and their rules.
It contains no data rows and makes no claim about any real marker; every
identifier in the examples is invented. The consistency suite is
`tests/test_release_panel.py` (run it with `python -B tests/test_release_panel.py`).
The suite runs the same checkers on invented fixtures, which prove that each rule
can fail, and on this document, which proves nothing while the tables are empty.

## Method

Goals, not quotas: about five everyday traits and about five health-related
markers, fewer when evidence or verification is insufficient. No particular
positive finding is required. A marker enters the panel only when every
criterion below is met from a captured public source; anything unresolved is
excluded and the exclusion keeps a row and a reason code. Two to three ranked
reserves per group are recorded but never placed in the targets file.

Every decision is a row in table T1. Health-related rows carry an additional
ClinVar pair row (T2), an inheritance row (T3) and an inventory row (T5);
trait rows carry evidence rows (T4). Rows are joined by rsID. In the targets
file, an included entry's `condition` equals that row's T1 `label used in
report` and its `gene` equals that row's T1 `gene`, exactly (case sensitive,
non-null; the T1 cell is the text left after the table parser strips
surrounding spaces, the same rule as the T2 `pair condition`). An entry has
exactly these keys: `rsid`, `gene`, `condition`, `category`, `result_type`,
`effect_allele`, `assayability` and `strand`; the evidence tier is derived by
the build and never written in the targets file, and placement fields come from
the dbSNP map supplied at build time. A checker error
in any table fails the suite, and a table that is absent, duplicated or
malformed is an error, never an empty result.

## Criteria

Every criterion must be satisfied from a captured primary source.

1. Identity: the rsID is current in dbSNP, with a GRCh37 chromosome, position
   and a single clear reference and alternate allele (`snp`), or an unambiguous
   `I` or `D` convention (`indel`).
2. Condition or trait mapping: the exact label the report will use is named in
   at least one primary source for that variant.
3. Effect allele and direction: the allele is written as the forward-strand
   GRCh37 letter (or `I` or `D`), the strand is stated, and the direction (which
   genotype raises or lowers the phenotype, or marks carrier status) is recorded.
4. Strand: palindromic sites (A/T and C/G) are excluded by default with reason
   code `palindromic`; the curator flag `strand-ambiguous` may only mark an
   excluded row.
5. Assayability is recorded (section Assayability). It is not a verified
   inclusion criterion unless a public array manifest is in the evidence pack.
6. Evidence threshold. Health-related entries: a ClinVar pair that is eligible
   under the ClinVar pair rule, plus one independent clinical source. Trait
   entries: replicated under the Replication rule.
7. Report safety: the entry can be reported without implying a diagnosis or an
   absolute risk, and its only honest wording is not a recommendation.
8. Not ancestry inference: ancestry-informative traits are excluded unless the
   owner decides otherwise.
9. Genericity: records contain public identifiers only (rsIDs, ClinVar ids,
   PMIDs, dates); no private paths, names or data.
10. Autosomal: the GRCh37 chromosome from the captured dbSNP record is `1` to
    `22` (rule AUTO-1).
11. Allele- and condition-specific clinical evidence for every health entry
    (the ClinVar pair rule).
12. Criterion 12, inheritance model for every health entry: the record cites an
    inheritance model, the meaning of one effect-allele copy and the meaning of
    two copies, each supported by at least one typed source that is not the
    ClinVar classification record itself (section Inheritance gate).

Criteria 4, 7 and 8 are curator judgments that no checker derives: the T1
`rationale` cell states the basis for each, the DATA review reassesses all three
independently for every row, and an ancestry exception cites an owner decision
id in the `limitations` cell.

## Source hierarchy

Tier P1 counts as primary: the dbSNP record (GRCh37 placement and merge
history) for identity; the ClinVar record (accession, review status,
submitters, condition, allele) for the clinical assertion; the GWAS Catalog
association row and the publication it points to for a trait association.
Tier P2 confirms but is never sufficient alone: curated clinical gene
resources, guideline or consensus statements, population frequency data, target
and disease summaries. Tier P3 is never sufficient: consumer-genomics sites,
encyclopedic pages and any source with redistribution limits. An entry needs P1
for criteria 1 to 3 and one independent P1 or P2 confirmation for criterion 6.

A guideline, review or clinical gene resource is the independent confirmation
of an otherwise eligible pair and the source of the inheritance model. It never
changes a ClinVar pair outcome.

## Result types

Each entry declares `category` (how evidence is derived) and `result_type` (how
the report words it). Exactly three pairs are allowed:

| result type | category | meaning |
|---|---|---|
| `trait` | `trait` | non-medical phenotype association; wording counts copies of the effect allele |
| `carrier_status` | `carrier` | autosomal recessive condition; one copy is worded as carrier status, two copies are never worded as affected; never a diagnosis |
| `risk_association` | `carrier` | susceptibility or dominant condition with incomplete penetrance; association wording that never says carrier |

Every other pair, a missing field, or a value outside these vocabularies
(including case variants) is rejected. The allowed pairs apply to every row of
table T1 whatever its decision (`included`, `reserve` or `excluded`), not only
to the entries placed in the targets file.

## Exclusion rule AUTO-1

The release panel is autosomal only. No marker whose GRCh37 chromosome from the
captured dbSNP record is X, Y, PAR or MT is included or kept as a reserve. For a
sex-chromosome or mitochondrial marker the same effect allele means different
things by sex or ploidy, the sex is inferred from the file, and the wording
contract (copies of the effect allele; carrier status) cannot state that
distinction without an interpretation this release does not make. The
hemizygous handling in the annotator stays and stays tested, but no release
entry exercises it. Such a row is recorded as excluded with reason code
`non-autosomal-out-of-scope`.

| token | verdict | row treatment |
|---|---|---|
| `1` to `22` (canonical decimal, no leading zero, no `chr` prefix) | autosomal | may be included, reserved or excluded for other reasons |
| `X`, `Y`, `PAR`, `MT` (exact upper case) | recognized non-autosomal | decision must be excluded with the code above |
| anything else (empty, `0`, `01`, `23` to `26`, `M`, `XY`, `chr1`, lower case, padded) | malformed | checker error for the whole table |

## ClinVar pair rule

The clinical assertion for a health entry is evaluated per (allele, condition)
pair: the allele is the entry's forward-strand GRCh37 effect allele and the
condition is the curated label. In table T2 the pair allele equals the T1
effect allele, and the T2 `pair condition` cell must equal the T1 `label used in
report` exactly (the cell text after the table parser strips surrounding spaces;
no case folding). The steps below run in order and are checked by the function
that computes the pair outcome from the considered-records cell.

### Considered set

All ClinVar VariationIDs that the frozen evidence pack associates with the
entry's rsID, for every assembly. Every id is listed in the record, whatever its
disposition, and the list must equal the pack inventory (table T5) as a set.

### Allele mapping

For each considered record the alternate allele is derived on the forward
GRCh37 strand from the captured genomic placement (position, reference,
alternate in VCF style) and cross-checked against the captured dbSNP placement.
A letter is never taken from coding-strand notation or from a display name.
No normalization is performed: a representation that is not left-anchored is
complex.

| record kind | requires (the dbSNP placement of the same rsID) | letter |
|---|---|---|
| single-nucleotide | dbSNP kind single-nucleotide; same chromosome, position and reference | the record's alternate letter |
| deletion (reference starts with alternate) | dbSNP deletion; same chromosome, position, reference and alternate, hence the same span | `D` |
| insertion (alternate starts with reference) | dbSNP insertion; same chromosome, position, reference and alternate, hence the same inserted sequence | `I` |
| anything else | none | `?` with a reason |

The reasons for `?` are a closed list: `no-grch37-placement`,
`position-or-ref-mismatch`, `kind-mismatch`, `span-mismatch`, `complex`,
`malformed`, `notation-only`. An ambiguous indel is rejected explicitly as `?`,
never matched silently.

### Qualifying record

A record qualifies for the pair when its mapped letter equals the effect
allele, its condition list contains the curated label by the alias-file
semantics, and its classification can be attributed to that condition (a
per-condition record or a single-condition record). A record whose
classification is shared by several conditions does not qualify (disposition
`other-condition`).

### No carry-over

Review stars, significance and conflict status are computed from qualifying
records only. Stars from a record for another allele or another condition are
never used. A record that does not qualify is listed with its disposition
(`other-allele`, `other-condition` or `unmapped`) and ignored. Supersession is
derived, never written.

### Significance groups

Case-insensitive prefix match on the ClinVar term, first hit wins, unknown terms
map to `AP`: `P` is pathogenic, likely pathogenic or a composite beginning with
pathogenic; `B` is benign or likely benign; `U` is uncertain significance; `RF`
is risk factor or risk allele; `AP` is association, protective, drug response,
affects, other or not provided; `CF` is an aggregate conflicting-classifications
term.

### Grammar G-1

The `considered records` cell of table T2 is `-` (empty) or items separated by
`;` with no spaces:

```
<VariationID>=<letter>/<disposition>/<group>/<stars>
9001001=A/match/P/2;9001002=C/other-allele/B/1;9001003=?/unmapped/AP/0
```

The VariationID is one or more digits and unique within the cell; the letter is
one of `A C G T I D ?`; the disposition is `match`, `other-allele`,
`other-condition` or `unmapped`; the group is `P B U RF AP CF`; the stars are
`0` to `4`. Cross-field errors have named codes: `letter-disp-mismatch` (the
letter is `?` if and only if the disposition is `unmapped`),
`match-letter-not-pair-allele`, `other-condition-letter`, `other-allele-letter`
(different from the pair allele and not `?`) and `letter-class-mismatch` (`I` or
`D` only with a pair allele of `I` or `D`, and the reverse for `A C G T`).

### Conflict

Let Q be the `match` items and G the set of their groups. The pair is in
conflict when `CF` is in G, or when at least two of `P`, `B`, `U` are in G.
`RF` and `AP` never create a conflict and never contribute stars to a result
based on `P`.

### Resolution

A conflict is resolved only by a qualifying ClinVar record of the same pair,
named in the `resolution` cell as the typed id `clinvar:vcv:<VariationID>`.
Rule R-RES: the resolution is valid when (a) the id is a `match` item, (b) its
group is `P`, (c) its stars are at least 3 (expert panel is 3, practice
guideline is 4), (d) the pair is in conflict, and (e) it is not contested: no
other `match` item of group `B` or `U` has stars at least equal to the
resolver's. A `CF` item never contests. The violations are checker errors, not
outcomes: `resolution-not-typed` (a bare number), `resolution-wrong-type` (any
other type, including a PubMed, GeneReviews or guideline id, or a different
ClinVar record type), `resolution-not-matched`, `resolution-not-p`,
`resolution-low-stars`, `resolution-without-conflict` and
`resolution-contested`. A guideline, review or chapter can never resolve a
ClinVar conflict; an unresolved conflict is excluded.

### Supporting group

The supporting group S is the only source of the pair's stars. For
`carrier_status` it is `P` when `P` is present, otherwise undefined. For
`risk_association` it is `P` when present, otherwise `RF` when present,
otherwise undefined (precedence `P` over `RF`). A resolved pair has the
resolver, group `P`, as S. Records outside S are listed and ignored: they never
raise or lower the stars. The pair's stars are the maximum within S. The table
lists every non-conflicting group set; every other non-empty set of the six
groups is a conflict.

| group set | carrier_status supporting group | risk_association supporting group |
|---|---|---|
| P | P | P |
| P, RF | P | P |
| P, AP | P | P |
| P, RF, AP | P | P |
| RF | - | RF |
| RF, AP | - | RF |
| AP | - | - |
| B | - | - |
| B, AP | - | - |
| U | - | - |
| U, AP | - | - |
| B, RF | - | RF |
| B, RF, AP | - | RF |
| U, RF | - | RF |
| U, RF, AP | - | RF |

### Pair outcome

Evaluated top-down, first hit wins:

| step | condition | outcome |
|---|---|---|
| 0 | the considered cell is `-` | `excluded:no-allele-condition-match` |
| 1 | the cell is not empty and every item has letter `?` | `excluded:allele-not-mappable` |
| 2 | Q is empty | `excluded:no-allele-condition-match` |
| 3 | conflict and resolution is `-` | `excluded:conflicting-evidence` |
| 4 | S is undefined | `excluded:ineligible-significance` |
| 5 | the stars of S are below 2 | `excluded:insufficient-review-status` |
| 6 | otherwise | `eligible` |

The cells `matched record ids` (the `match` items), `matched significance`
(the group of S, or `-`), `stars` (the stars of S, or `-`) and `pair outcome`
must equal the computed values. `matched review status` is informational text.
Any health entry kept as included or reserve requires `eligible`. Trait entries
do not use ClinVar for eligibility.

## Inheritance gate

Criterion 12 is checked per health entry with table T3. The closed vocabulary
of models:

| model | meaning | allowed result type |
|---|---|---|
| `AR` | autosomal recessive | `carrier_status` only |
| `AD-IP` | dominant with reduced penetrance, or a susceptibility allele | `risk_association` only |
| `SUSC` | susceptibility, modifier or complex | `risk_association` only |
| `AD` | dominant with high penetrance | none; excluded with `inheritance-out-of-scope` |
| `UNRESOLVED` | sources conflict or are missing | none; excluded with `inheritance-unresolved` |
| `n/a` | trait entries only | `trait` only |

Allowed combinations of model, result type and supporting group: `AR` with
`carrier_status` and `P`; `AD-IP` or `SUSC` with `risk_association` and `P` or
`RF`; `n/a` with `trait`. Every other combination is an error. Each health row
needs at least one inheritance source of type `genereviews`, `medgen`, `clingen`
or `pmid` (a ClinVar id alone never qualifies). For `AR` the one-copy meaning
contains the word carrier and the two-copy meaning is not empty. For `AD-IP`
and `SUSC` neither meaning contains the word carrier (whole-word match, any
case). Empty copy-meaning cells on a kept health row are errors.

## Assayability

The T1 columns `assayability_status` and `assayability_source` record whether
the marker's presence on the genotyping array was verified. The status is
`verified-from-public-manifest`, which requires a typed `manifest:<id>` source,
or `unknown-provisional`, which carries `-` as source and is not a verified
criterion. No public array manifest is in the evidence pack, so no entry may be
worded as being on the array in any tracked file. The owner's aggregate
coverage decision, with reserves as the remedy, decides whether the panel is
adequate; no per-marker coverage is ever shared.

## Replication

Trait entries need replicated evidence, evaluated by one function over table
T4. Constants: at least two independent groups, a significance threshold of
5e-8 (inclusive), and at most one functional group.

A row is dropped, in this order, with the first failing code:
`trait-mismatch` (the reported trait is not the label or an alias-file
equivalent), `allele-mismatch` (the row's effect allele is not the entry's),
`orientation-unverified` (palindromic and other rows need verified orientation),
`evidence-not-in-pack` (the orientation source is absent or not in the evidence
pack; a functional row also needs its publication in the pack),
`direction-missing`, `p-missing` or `p-malformed` (association rows only; a
functional row has no p-value). A `p-value` cell is a decimal string in
`(0, 1]`; a string that is nonzero as text but whose float value underflows to
`0.0` (for example `1e-400`) is rejected as `p-malformed`. Rows that pass are
direction-eligible. Two more
checks decide whether a row can form an independent group: `cohort-unknown` and
`evidence-not-in-pack` (the cohort source). Unknown independence, unverified
orientation or an unrecorded direction therefore never count. A publication
detail missing from the pack is never filled from memory.

Independent groups are derived, never written: rows with the same PMID, the
same cohort id, or a declared overlap in either direction form one cluster, and
each cluster is one group. A functional paper counts as at most one group, only
when at least one GWAS group is present (functional-only evidence is zero
groups), needs a distinct cohort and verified orientation, and never supplies
the p-value requirement.

| status | condition |
|---|---|
| `conflicting-evidence` | direction-eligible rows include both up and down |
| `no-counted-evidence` | zero groups |
| `single-study` | exactly one group |
| `not-significant` | two or more groups but no eligible association row with p at or below the threshold |
| `replicated` | two or more groups, all directions equal, and at least one eligible association row at or below the threshold |

An entry that is not `replicated` is excluded with `conflicting-evidence`,
`single-study` or `no-independent-confirmation`; the code `evidence-not-in-pack`
applies only when the status is `no-counted-evidence` and some rows were dropped
for unverified orientation, unknown cohort or missing evidence.
The `counted` cell of T4 is a claim the checker recomputes.

## Typed ids

Evidence is cited by typed id, `<type>:<id>`, separated by `;`. Types:
`dbsnp:rs<digits>`, `clinvar:vcv:<digits>`, `clinvar:rcv:RCV<digits>`,
`gwas:GCST<digits>`, `pmid:<digits>`, `genereviews:NBK<digits>`,
`medgen:<id>`, `clingen:<id>`, `manifest:<id>`. Dates are ISO calendar dates
(`YYYY-MM-DD`, UTC). An id without a type, with an unknown type, or an invalid
date is an error on any included or reserve row.

## Reason codes

Excluded rows carry exactly one code; included and reserve rows carry a dash.

- `conflicting-evidence`
- `single-study`
- `palindromic`
- `unclear-allele`
- `not-assayable` (repeat expansions and large indels only)
- `label-mismatch`
- `ancestry-informative`
- `owner-declined`
- `non-autosomal-out-of-scope`
- `allele-not-mappable`
- `no-allele-condition-match`
- `ineligible-significance`
- `insufficient-review-status`
- `inheritance-unresolved`
- `inheritance-out-of-scope`
- `no-independent-confirmation`
- `evidence-not-in-pack`
- `x-linked-out-of-scope` (retired; replaced by the autosomal code above)

## Tables

Each table below has a fixed header. A test parses them; a header that differs
by one character, a duplicated table, a ragged row or a missing table is an
error.

### T1 Decision table

| rsID | gene | chrom (GRCh37) | label used in report | result type | category | effect allele (fwd, GRCh37) | direction/meaning | build/strand | assayability_status | assayability_source | sources (typed ids) | retrieved (UTC date) | rationale | limitations | decision | reason code |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rs334 | HBB | 11 | Sickle cell disease | carrier_status | carrier | A | one copy: carrier of sickle cell trait; two copies: sickle cell disease | GRCh37/forward;strand-ambiguous | unknown-provisional | - | dbsnp:rs334;clinvar:vcv:15333;clinvar:rcv:RCV000016574;genereviews:NBK1377;medgen:C0002895;manifest:n0d-dbsnp-rs334;manifest:n0d-alleles | 2026-11-09 | strand: palindromic reference/effect pair T/A (N0d reference T, effect allele A), excluded per D-54-1; report-safety: carrier wording; not ancestry-informative; O-3: RCV000016574 (Hb SS disease) names the curated label through the alias "hb ss disease"; O-1: N0d alleles T>A,C,G, effect allele A | array presence not verified; palindromic site (reference/effect T/A), excluded by default | excluded | palindromic |
| rs33930165 | HBB | 11 | Hemoglobin C disease | carrier_status | carrier | T | one copy: carrier of hemoglobin C trait; two copies: hemoglobin C disease | GRCh37/forward | unknown-provisional | - | dbsnp:rs33930165;clinvar:vcv:15126;clinvar:rcv:RCV000016284;manifest:n0d-dbsnp-rs33930165;manifest:n0d-alleles | - | strand: non-palindromic C/T; report-safety: carrier wording; not ancestry-informative; O-3: RCV000016284 names the curated condition (HEMOGLOBIN C); D-54-3: the attributing record RCV000016284 has no assertion criteria (0 stars), so the pair is ineligible; the pair is eligible in neither the RCV nor the aggregate; O-4: no independent inheritance source names hemoglobin C disease, so the row is also inheritance-unresolved; O-1: N0d alleles C>A,G,T, effect allele T | array presence not verified; the attributing record carries no assertion criteria and no GeneReviews or MedGen inheritance source names hemoglobin C disease | excluded | inheritance-unresolved |
| rs113993960 | CFTR | 7 | Cystic fibrosis | carrier_status | carrier | D | one copy: carrier; two copies: cystic fibrosis | - | unknown-provisional | - | dbsnp:rs113993960;clinvar:vcv:7105;manifest:n0d-dbsnp-rs113993960;manifest:n0d-alleles | - | strand: deletion; report-safety: carrier wording; not ancestry-informative; the CFTR deletion record (7105) cannot be mapped to the dbSNP placement (position/ref differ by the left-shift); O-1: N0d reference TCTT with alternates T,TCTTCTT | array presence not verified; the ClinVar placement is not left-anchored against the dbSNP placement | excluded | allele-not-mappable |
| rs1800562 | HFE | 6 | Hereditary hemochromatosis | carrier_status | carrier | A | one copy: carrier of the C282Y allele; two copies: hereditary hemochromatosis | GRCh37/forward | unknown-provisional | - | dbsnp:rs1800562;clinvar:vcv:9;genereviews:NBK1440;medgen:C3469186;clinvar:rcv:RCV000000019;manifest:n0d-dbsnp-rs1800562;manifest:n0d-alleles | 2026-11-09 | strand: non-palindromic G/A; report-safety: carrier wording, no diagnosis; not ancestry-informative; O-3: RCV000000019 (Hemochromatosis type 1) names the curated label through the alias "hemochromatosis type 1"; D-54-3: the attributing record RCV000000019 is Pathogenic with multiple submitters (2 stars), not the one-star RCV000308358; O-1: N0d alleles G>A,T, effect allele A | array presence not verified; the record classification is shared across several conditions but an RCV names the curated one | included | - |
| rs1799945 | HFE | 6 | Hereditary hemochromatosis | carrier_status | carrier | G | one copy: carrier; two copies: hereditary hemochromatosis | GRCh37/forward;strand-ambiguous | unknown-provisional | - | dbsnp:rs1799945;clinvar:vcv:10;genereviews:NBK1440;medgen:C3469186;clinvar:rcv:RCV000394716;manifest:n0d-dbsnp-rs1799945;manifest:n0d-alleles | - | strand: palindromic reference/effect pair C/G (N0d reference C, effect allele G), excluded per D-54-1; report-safety: carrier wording; not ancestry-informative; O-3: RCV000394716 names the curated condition; D-54-3: the attributing record RCV000394716 is Pathogenic, low penetrance (1 star); O-1: N0d alleles C>G,T, effect allele G | array presence not verified; palindromic site (reference/effect C/G), excluded by default | excluded | palindromic |
| rs6025 | F5 | 1 | Factor V Leiden thrombophilia | risk_association | carrier | T | one copy: increased association; two copies: further increased association | GRCh37/forward | unknown-provisional | - | dbsnp:rs6025;clinvar:vcv:642;genereviews:NBK1368;clinvar:rcv:RCV000454249;manifest:n0d-dbsnp-rs6025;manifest:n0d-alleles | 2026-11-09 | strand: reference/effect pair T/T, not A/T or C/G, non-palindromic; report-safety: association wording without carrier; not ancestry-informative; O-3: RCV000454249 names the curated condition by alias (thrombophilia due to activated protein C resistance); D-54-3: the attributing record RCV000454249 is Pathogenic with multiple submitters (2 stars), not the expert-panel drug-response aggregate; O-1: N0d alleles T>C,A,G, effect allele T | array presence not verified; dominant reduced-penetrance association, never a diagnosis | included | - |
| rs1799963 | F2 | 11 | Prothrombin thrombophilia | risk_association | carrier | A | one copy: increased association; two copies: further increased association | GRCh37/forward | unknown-provisional | - | dbsnp:rs1799963;clinvar:vcv:13310;genereviews:NBK1148;clinvar:rcv:RCV005419865;manifest:n0d-dbsnp-rs1799963;manifest:n0d-alleles | 2026-11-09 | strand: non-palindromic G/A; report-safety: association wording without carrier; not ancestry-informative; O-3: RCV005419865 (Thrombophilia due to thrombin defect) names the curated label through the alias "thrombophilia due to thrombin defect"; the substring alias "prothrombin deficiency" that produced the wrong RCV000205022 (Congenital prothrombin deficiency, a different bleeding disorder) was removed per D-54-2; D-54-3: the attributing record RCV005419865 is Pathogenic with multiple submitters (2 stars); O-1: N0d reference G with alternate A, effect allele A | array presence not verified; dominant reduced-penetrance association, never a diagnosis | included | - |
| rs1050828 | G6PD | X | G6PD deficiency | carrier_status | carrier | - | not applicable | - | unknown-provisional | - | - | - | strand: n/a; report-safety: n/a; ancestry-informative: n/a; the dbSNP placement is chromosome X and the release panel is autosomal only (AUTO-1) | array presence not verified; sex-chromosome marker out of scope for this release | excluded | non-autosomal-out-of-scope |
| rs28929474 | SERPINA1 | 14 | Alpha-1 antitrypsin deficiency | carrier_status | carrier | T | one copy: carrier of the Z allele; two copies: alpha-1 antitrypsin deficiency | GRCh37/forward | unknown-provisional | - | dbsnp:rs28929474;clinvar:vcv:17967;genereviews:NBK1519;medgen:C0221757;clinvar:rcv:RCV000148877;manifest:n0d-dbsnp-rs28929474;manifest:n0d-alleles | 2026-11-09 | strand: non-palindromic C/T; report-safety: carrier wording, no diagnosis; not ancestry-informative; O-3: RCV000148877 names the curated condition; D-54-3: the attributing record RCV000148877 is Pathogenic/Likely pathogenic with multiple submitters (2 stars); D-54-4a: the inheritance sources conflict (GeneReviews NBK1519 states autosomal codominant, MedGen C0221757 states autosomal recessive), so the model is UNRESOLVED and the row is excluded inheritance-unresolved; O-1: N0d reference C with alternates A,G,T, so the effect allele T is an N0d alternate (the N0a single-alt column held only A) | array presence not verified; the inheritance sources disagree (NBK1519 codominant, C0221757 recessive), so the model is unresolved | excluded | inheritance-unresolved |
| rs12913832 | HERC2 | 15 | Eye color | trait | trait | - | not applicable | - | unknown-provisional | - | dbsnp:rs12913832 | - | strand: n/a; report-safety: association wording; ancestry-informative: eye color is a pigmentation trait strongly correlated with ancestry (GWAS rows for rs12913832 report eye color, skin cancer and retinal pigmentation), excluded | array presence not verified; ancestry-informative trait | excluded | ancestry-informative |
| rs1805007 | MC1R | 16 | Red hair | trait | trait | - | not applicable | - | unknown-provisional | - | dbsnp:rs1805007 | - | strand: n/a; report-safety: association wording; ancestry-informative: red hair is a pigmentation trait strongly correlated with ancestry (ClinVar RCV names red hair/fair skin), excluded | array presence not verified; ancestry-informative trait | excluded | ancestry-informative |
| rs1805008 | MC1R | 16 | Red hair | trait | trait | - | not applicable | - | unknown-provisional | - | dbsnp:rs1805008 | - | strand: n/a; report-safety: association wording; ancestry-informative: red hair is a pigmentation trait strongly correlated with ancestry (ClinVar RCV names red hair/fair skin), excluded | array presence not verified; ancestry-informative trait | excluded | ancestry-informative |
| rs17822931 | ABCC11 | 16 | Earwax type | trait | trait | - | not applicable | - | unknown-provisional | - | dbsnp:rs17822931 | - | strand: n/a; report-safety: association wording; not ancestry-informative (no captured source ties earwax type to ancestry); no GWAS association row in the pack reports the curated label, so there is no replicated evidence | array presence not verified; no replicated GWAS evidence for the curated label | excluded | no-independent-confirmation |
| rs4988235 | MCM6 | 2 | Lactose intolerance | trait | trait | - | not applicable | - | unknown-provisional | - | dbsnp:rs4988235 | - | strand: n/a; report-safety: association wording; not ancestry-informative (no captured source ties lactose intolerance to ancestry); no GWAS association row in the pack reports the curated label, so there is no replicated evidence | array presence not verified; no replicated GWAS evidence for the curated label | excluded | no-independent-confirmation |
| rs671 | ALDH2 | 12 | Alcohol flush reaction | trait | trait | - | not applicable | - | unknown-provisional | - | dbsnp:rs671 | - | strand: n/a; report-safety: association wording; not ancestry-informative (no captured source ties alcohol flushing to ancestry); the alcohol-flushing rows are a single publication, so the evidence is not replicated | array presence not verified; single-study flushing evidence | excluded | single-study |
| rs1229984 | ADH1B | 4 | Alcohol metabolism | trait | trait | - | not applicable | - | unknown-provisional | - | dbsnp:rs1229984 | - | strand: n/a; report-safety: association wording; not ancestry-informative (no captured source ties alcohol metabolism to ancestry); no GWAS association row in the pack reports the curated label, so there is no replicated evidence | array presence not verified; no replicated GWAS evidence for the curated label | excluded | no-independent-confirmation |
| rs762551 | CYP1A2 | 15 | Caffeine metabolism | trait | trait | - | not applicable | - | unknown-provisional | - | dbsnp:rs762551 | - | strand: n/a; report-safety: association wording; not ancestry-informative (no captured source ties caffeine metabolism to ancestry); the single GWAS association row reports a lipid trait, not caffeine metabolism | array presence not verified; no replicated GWAS evidence for the curated label | excluded | no-independent-confirmation |
| rs72921001 | OR2M7 | 11 | Cilantro taste perception | trait | trait | - | not applicable | - | unknown-provisional | - | dbsnp:rs72921001 | - | strand: n/a; report-safety: association wording; not ancestry-informative (no captured source ties cilantro taste perception to ancestry); the GWAS association page holds no rows for this rsID | array presence not verified; no GWAS evidence in the pack | excluded | no-independent-confirmation |
| rs1426654 | SLC24A5 | 15 | Skin pigmentation | trait | trait | - | not applicable | - | unknown-provisional | - | dbsnp:rs1426654 | - | strand: n/a; report-safety: association wording; ancestry-informative: skin pigmentation is a pigmentation trait strongly correlated with ancestry (GWAS rows report the label), excluded | array presence not verified; ancestry-informative trait | excluded | ancestry-informative |
| rs16891982 | SLC45A2 | 5 | Skin pigmentation | trait | trait | - | not applicable | - | unknown-provisional | - | dbsnp:rs16891982 | - | strand: n/a; report-safety: association wording; ancestry-informative: skin pigmentation is a pigmentation trait strongly correlated with ancestry (GWAS rows report the label), excluded | array presence not verified; ancestry-informative trait | excluded | ancestry-informative |
| rs1800407 | OCA2 | 15 | Eye color | trait | trait | - | not applicable | - | unknown-provisional | - | dbsnp:rs1800407 | - | strand: n/a; report-safety: association wording; ancestry-informative: eye color is a pigmentation trait strongly correlated with ancestry, excluded | array presence not verified; ancestry-informative trait | excluded | ancestry-informative |
| rs1042602 | TYR | 11 | Freckling | trait | trait | - | not applicable | - | unknown-provisional | - | dbsnp:rs1042602 | - | strand: n/a; report-safety: association wording; ancestry-informative: freckling is a pigmentation trait strongly correlated with ancestry, excluded | array presence not verified; ancestry-informative trait | excluded | ancestry-informative |
| rs6152 | AR | X | Male pattern baldness | trait | trait | - | not applicable | - | unknown-provisional | - | - | - | strand: n/a; report-safety: n/a; ancestry-informative: n/a; the dbSNP placement is chromosome X and the release panel is autosomal only (AUTO-1) | array presence not verified; sex-chromosome marker out of scope for this release | excluded | non-autosomal-out-of-scope |
| rs61752717 | MEFV | 16 | Familial Mediterranean fever | risk_association | carrier | C | model unresolved: no one-copy or two-copy meaning recorded | GRCh37/forward | unknown-provisional | - | dbsnp:rs61752717;clinvar:vcv:2538;clinvar:rcv:RCV000002647;medgen:C0031069 | 2026-11-14 | strand: non-palindromic T/C pair (dbSNP alts A, C, G; the A alt is palindromic and is the other-allele item VCV 97487); O-3: RCV000002647 (Familial Mediterranean fever) names the curated label exactly (alias not needed); D-54-3: the attributing record RCV000002647 is Pathogenic/Likely pathogenic with multiple submitters (2 stars); report-safety: no one-copy or two-copy wording can be fixed while the model is unresolved (a carrier wording would contradict the dominant submissions, an association wording needs a model source); ancestry: no captured source ties the marker to ancestry (curator judgment, not rule-checked); D8: criteria 1 and 4 read on the reference/effect pair; D-54-4a style: the one captured independent inheritance source, MedGen C0031069, lists both autosomal recessive and autosomal dominant inheritance, the separate concept C1851347 (autosomal dominant label) lists none, and the GeneReviews id NBK1227 (trait review citation in the VCV) has no captured text, so the model is UNRESOLVED | array presence not verified; multi-allelic site (D8): other alleles at the site are other-allele items and are not counted; the palindromic T>A alt (VCV 97487, uncertain significance) is not the effect allele; inheritance sources conflict (MedGen C0031069 lists autosomal recessive and autosomal dominant), so the model is unresolved | excluded | inheritance-unresolved |
| rs28940579 | MEFV | 16 | Familial Mediterranean fever | risk_association | carrier | G | model unresolved: no one-copy or two-copy meaning recorded | GRCh37/forward | unknown-provisional | - | dbsnp:rs28940579;clinvar:vcv:2540;clinvar:rcv:RCV000002649;medgen:C0031069 | 2026-11-14 | strand: non-palindromic A/G pair (dbSNP alts C, G, T; the T alt is palindromic and is the other-allele item VCV 2637664); O-3: RCV000002649 (Familial Mediterranean fever) names the curated label exactly (alias not needed); D-54-3: the attributing record RCV000002649 is Pathogenic/Likely pathogenic with multiple submitters (2 stars); report-safety: no one-copy or two-copy wording can be fixed while the model is unresolved (a carrier wording would contradict the dominant submissions, an association wording needs a model source); ancestry: no captured source ties the marker to ancestry (curator judgment, not rule-checked); D8: criteria 1 and 4 read on the reference/effect pair; D-54-4a style: the one captured independent inheritance source, MedGen C0031069, lists both autosomal recessive and autosomal dominant inheritance, the separate concept C1851347 (autosomal dominant label) lists none, and the GeneReviews id NBK1227 (trait review citation in the VCV) has no captured text, so the model is UNRESOLVED | array presence not verified; multi-allelic site (D8): other alleles at the site are other-allele items and are not counted; the palindromic A>T alt (VCV 2637664, uncertain significance) is not the effect allele; inheritance sources conflict (MedGen C0031069 lists autosomal recessive and autosomal dominant), so the model is unresolved | excluded | inheritance-unresolved |
| rs28940578 | MEFV | 16 | Familial Mediterranean fever | risk_association | carrier | T | model unresolved: no one-copy or two-copy meaning recorded | GRCh37/forward | unknown-provisional | - | dbsnp:rs28940578;clinvar:vcv:2539;clinvar:rcv:RCV000002648;medgen:C0031069 | 2026-11-14 | strand: non-palindromic C/T pair (dbSNP alt T only); O-3: RCV000002648 (Familial Mediterranean fever) names the curated label exactly (alias not needed); D-54-3: the attributing record RCV000002648 is Pathogenic/Likely pathogenic with multiple submitters (2 stars); report-safety: no one-copy or two-copy wording can be fixed while the model is unresolved (a carrier wording would contradict the dominant submissions, an association wording needs a model source); ancestry: no captured source ties the marker to ancestry (curator judgment, not rule-checked); D8: criteria 1 and 4 read on the reference/effect pair; D-54-4a style: the one captured independent inheritance source, MedGen C0031069, lists both autosomal recessive and autosomal dominant inheritance, the separate concept C1851347 (autosomal dominant label) lists none, and the GeneReviews id NBK1227 (trait review citation in the VCV) has no captured text, so the model is UNRESOLVED | array presence not verified; multi-allelic site (D8): other alleles at the site are other-allele items and are not counted; ClinVar also holds haplotype record VCV 2555 (c.[442G>C;2082G>A], no assertion criteria) that variant_summary does not list, so it is outside the pack inventory; inheritance sources conflict (MedGen C0031069 lists autosomal recessive and autosomal dominant), so the model is unresolved | excluded | inheritance-unresolved |
| rs104895097 | MEFV | 16 | Familial Mediterranean fever | risk_association | carrier | T | model unresolved: no one-copy or two-copy meaning recorded | GRCh37/forward | unknown-provisional | - | dbsnp:rs104895097;clinvar:vcv:2549;clinvar:rcv:RCV000002658;medgen:C0031069 | 2026-11-14 | strand: non-palindromic C/T pair (dbSNP alts A, G, T; the G alt is palindromic and has no ClinVar record in the pack); O-3: RCV000002658 (Familial Mediterranean fever) names the curated label exactly (alias not needed); D-54-3: the attributing record RCV000002658 is Pathogenic/Likely pathogenic with multiple submitters (2 stars); report-safety: no one-copy or two-copy wording can be fixed while the model is unresolved (a carrier wording would contradict the dominant submissions, an association wording needs a model source); ancestry: no captured source ties the marker to ancestry (curator judgment, not rule-checked); D8: criteria 1 and 4 read on the reference/effect pair; D-54-4a style: the one captured independent inheritance source, MedGen C0031069, lists both autosomal recessive and autosomal dominant inheritance, the separate concept C1851347 (autosomal dominant label) lists none, and the GeneReviews id NBK1227 (trait review citation in the VCV) has no captured text, so the model is UNRESOLVED | array presence not verified; multi-allelic site (D8): other alleles at the site are other-allele items and are not counted; inheritance sources conflict (MedGen C0031069 lists autosomal recessive and autosomal dominant), so the model is unresolved | excluded | inheritance-unresolved |
| rs28940580 | MEFV | 16 | Familial Mediterranean fever | risk_association | carrier | T | model unresolved: no one-copy or two-copy meaning recorded | GRCh37/forward | unknown-provisional | - | dbsnp:rs28940580;clinvar:vcv:2550;clinvar:rcv:RCV000002659;medgen:C0031069 | 2026-11-14 | strand: non-palindromic C/T pair (dbSNP alts A, G, T; the G alt is palindromic and is the other-allele item VCV 36507); O-3: RCV000002659 (Familial Mediterranean fever) names the curated label exactly (alias not needed); D-54-3: the attributing record RCV000002659 is Pathogenic with multiple submitters (2 stars); report-safety: no one-copy or two-copy wording can be fixed while the model is unresolved (a carrier wording would contradict the dominant submissions, an association wording needs a model source); ancestry: no captured source ties the marker to ancestry (curator judgment, not rule-checked); D8: criteria 1 and 4 read on the reference/effect pair; D-54-4a style: the one captured independent inheritance source, MedGen C0031069, lists both autosomal recessive and autosomal dominant inheritance, the separate concept C1851347 (autosomal dominant label) lists none, and the GeneReviews id NBK1227 (trait review citation in the VCV) has no captured text, so the model is UNRESOLVED | array presence not verified; multi-allelic site (D8): other alleles at the site are other-allele items and are not counted; the C>G (VCV 36507) and C>A (VCV 234365) alleles are also pathogenic classifications at this site and are not counted; inheritance sources conflict (MedGen C0031069 lists autosomal recessive and autosomal dominant), so the model is unresolved | excluded | inheritance-unresolved |
| rs104895085 | MEFV | 16 | Familial Mediterranean fever | risk_association | carrier | T | model unresolved: no one-copy or two-copy meaning recorded | GRCh37/forward | unknown-provisional | - | dbsnp:rs104895085;clinvar:vcv:2553;clinvar:rcv:RCV000002662;medgen:C0031069 | 2026-11-14 | strand: non-palindromic C/T pair (dbSNP alts A, G, T; the G alt is palindromic and has no ClinVar record in the pack); O-3: RCV000002662 (Familial Mediterranean fever) names the curated label exactly (alias not needed); D-54-3: the attributing record RCV000002662 is Pathogenic/Likely pathogenic with multiple submitters (2 stars); report-safety: no one-copy or two-copy wording can be fixed while the model is unresolved (a carrier wording would contradict the dominant submissions, an association wording needs a model source); ancestry: no captured source ties the marker to ancestry (curator judgment, not rule-checked); D8: criteria 1 and 4 read on the reference/effect pair; D-54-4a style: the one captured independent inheritance source, MedGen C0031069, lists both autosomal recessive and autosomal dominant inheritance, the separate concept C1851347 (autosomal dominant label) lists none, and the GeneReviews id NBK1227 (trait review citation in the VCV) has no captured text, so the model is UNRESOLVED | array presence not verified; multi-allelic site (D8): other alleles at the site are other-allele items and are not counted; inheritance sources conflict (MedGen C0031069 lists autosomal recessive and autosomal dominant), so the model is unresolved | excluded | inheritance-unresolved |
| rs1799807 | BCHE | 3 | Deficiency of butyrylcholinesterase | carrier_status | carrier | C | one copy: carrier; two copies: deficiency of butyrylcholinesterase | GRCh37/forward | unknown-provisional | - | dbsnp:rs1799807;clinvar:vcv:13215;clinvar:rcv:RCV000277104;medgen:C1283400 | 2026-11-14 | strand: non-palindromic T/C pair (dbSNP alts A, C; the A alt is palindromic and has no ClinVar record in the pack); report-safety: carrier wording, no diagnosis; the drug-response label "Postanesthetic apnea" (RCV000014102, no assertion criteria, 0 stars) is not used; not ancestry-informative (no captured source ties the marker to ancestry; curator judgment); O-3: RCV000277104 (Deficiency of butyrylcholinesterase) names the curated label exactly (alias not needed); D-54-3: the attributing record RCV000277104 is Pathogenic/Likely pathogenic with multiple submitters (2 stars), not the 0-star RCV000014102; D8: criteria 1 and 4 read on the reference/effect pair; inheritance: MedGen C1283400 lists autosomal recessive inheritance | array presence not verified; the clinical relevance of this concept is a drug response, which the report does not state; the record classification is shared across several conditions but an RCV names the curated one; the MedGen text defines the recessive model by two pathogenic alleles and does not itself state the one-copy carrier meaning | included | - |
| rs121908529 | AGXT | 2 | Primary hyperoxaluria, type I | carrier_status | carrier | A | one copy: carrier; two copies: primary hyperoxaluria, type I | GRCh37/forward | unknown-provisional | - | dbsnp:rs121908529;clinvar:vcv:40166;clinvar:rcv:RCV000032681;medgen:C0268164 | 2026-11-14 | strand: non-palindromic G/A pair (dbSNP alts A, C, T; the C alt is palindromic and is the other-allele item VCV 2710435); report-safety: carrier wording, no diagnosis; not ancestry-informative (no captured source ties the marker to ancestry; curator judgment); O-3: RCV000032681 (Primary hyperoxaluria, type I) names the curated label exactly (alias not needed); D-54-3: the attributing record RCV000032681 is Pathogenic/Likely pathogenic with multiple submitters (2 stars); D8: criteria 1 and 4 read on the reference/effect pair; inheritance: MedGen C0268164 lists autosomal recessive inheritance | array presence not verified; multi-allelic site (D8): the G>C allele (VCV 2710435) is also a pathogenic classification and is not counted; the MedGen text defines the recessive model by two pathogenic alleles and does not itself state the one-copy carrier meaning | included | - |
| rs185803104 | HOGA1 | 10 | Primary hyperoxaluria type 3 | carrier_status | carrier | T | one copy: carrier; two copies: primary hyperoxaluria type 3 | GRCh37/forward | unknown-provisional | - | dbsnp:rs185803104;clinvar:vcv:204285;clinvar:rcv:RCV000186492;medgen:C3150878 | 2026-11-14 | strand: non-palindromic G/T pair (dbSNP alt T only); report-safety: carrier wording, no diagnosis; not ancestry-informative (no captured source ties the marker to ancestry; curator judgment); O-3: RCV000186492 (Primary hyperoxaluria type 3) names the curated label exactly (alias not needed); D-54-3: the attributing record RCV000186492 is Pathogenic with multiple submitters (2 stars); D8: criteria 1 and 4 read on the reference/effect pair; inheritance: MedGen C3150878 lists autosomal recessive inheritance | array presence not verified; intronic splice-region change (c.700+5G>T), not a protein change; the MedGen text defines the recessive model by two pathogenic alleles and does not itself state the one-copy carrier meaning | included | - |
| rs180177314 | GRHPR | 9 | Primary hyperoxaluria, type II | carrier_status | carrier | A | one copy: carrier; two copies: primary hyperoxaluria, type II | GRCh37/forward | unknown-provisional | - | dbsnp:rs180177314;clinvar:vcv:204235;clinvar:rcv:RCV000186442;medgen:C0268165 | 2026-11-14 | strand: non-palindromic G/A pair (dbSNP alt A only); report-safety: carrier wording, no diagnosis; not ancestry-informative (no captured source ties the marker to ancestry; curator judgment); O-3: RCV000186442 (Primary hyperoxaluria, type II) names the curated label exactly (alias not needed); D-54-3: the attributing record RCV000186442 is Pathogenic/Likely pathogenic with multiple submitters (2 stars); D8: criteria 1 and 4 read on the reference/effect pair; inheritance: MedGen C0268165 lists autosomal recessive inheritance | array presence not verified; the MedGen text defines the recessive model by two pathogenic alleles and does not itself state the one-copy carrier meaning | included | - |
| rs11591147 | PCSK9 | 1 | LDL cholesterol levels | trait | trait | T | each copy of the T allele is associated with lower LDL cholesterol in studies; no more than association wording | GRCh37/forward | unknown-provisional | - | dbsnp:rs11591147;clinvar:vcv:2878;gwas:GCST000134;gwas:GCST006612;gwas:GCST90239659;gwas:GCST90827842;pmid:18193044;pmid:30275531;pmid:34887591;pmid:39091897 | 2026-11-14 | strand: non-palindromic G/T (dbSNP GRCh37 SPDI alleles G>A,T; reference G, effect T); report-safety: association wording, no diagnosis, no absolute risk, not a recommendation; not ancestry-informative (no captured source ties LDL cholesterol to ancestry; the T-allele frequency in the captured association rows ranges 0.007-0.033 and is not verified by ancestry; judged not ancestry-informative under criterion 8, owner decision P-4); replicated under the Replication rule: 3 independent groups, all direction down for the T allele, rows a14755030,a80057298,a101331236,a216839734; orientation: effect allele letter T or G equals a dbSNP forward allele and no row reports the complement letter A or C (source dbsnp:rs11591147); ClinVar VCV 2878 (Benign/Likely benign, 2 stars) is not used for trait eligibility; label alias-file groups: {"LDL cholesterol levels": ["low density lipoprotein cholesterol levels", "ldl cholesterol"]} | array presence not verified; study sample ancestry and size not captured (T4 cells hold -); cohort independence derived from PubMed abstract text only | included | - |

The `decision` is `included`, `excluded` or `reserve`. The `build/strand` cell
is `GRCh37/forward`, optionally followed by `;strand-ambiguous` on an excluded
palindromic row; an excluded row may carry `-`.

### T2 ClinVar pair table

One row per health-related rsID; trait rows do not appear.

| rsID | pair allele (fwd GRCh37) | pair condition | matched record ids | matched significance | matched review status | stars | considered records | resolution | pair outcome |
|---|---|---|---|---|---|---|---|---|---|
| rs334 | A | Sickle cell disease | 15333 | P | criteria provided, multiple submitters, no conflicts | 2 | 15175=G/other-allele/B/1;15333=A/match/P/2 | - | eligible |
| rs33930165 | T | Hemoglobin C disease | 15126 | P | no assertion criteria provided | 0 | 15126=T/match/P/0;15243=G/other-allele/U/1;869230=A/other-allele/P/0 | - | excluded:insufficient-review-status |
| rs113993960 | D | Cystic fibrosis | - | - | - | - | 7105=?/unmapped/AP/0 | - | excluded:allele-not-mappable |
| rs1800562 | A | Hereditary hemochromatosis | 9 | P | criteria provided, multiple submitters, no conflicts | 2 | 9=A/match/P/2 | - | eligible |
| rs1799945 | G | Hereditary hemochromatosis | 10 | P | criteria provided, single submitter | 1 | 10=G/match/P/1 | - | excluded:insufficient-review-status |
| rs6025 | T | Factor V Leiden thrombophilia | 642 | P | criteria provided, multiple submitters, no conflicts | 2 | 642=T/match/P/2;226007=C/other-allele/CF/1 | - | eligible |
| rs1799963 | A | Prothrombin thrombophilia | 13310 | P | criteria provided, multiple submitters, no conflicts | 2 | 13310=A/match/P/2 | - | eligible |
| rs1050828 | - | G6PD deficiency | - | - | - | - | - | - | excluded:no-allele-condition-match |
| rs28929474 | T | Alpha-1 antitrypsin deficiency | 17967 | P | criteria provided, multiple submitters, no conflicts | 2 | 17967=T/match/P/2;1492979=G/other-allele/P/1 | - | eligible |
| rs61752717 | C | Familial Mediterranean fever | 2538 | P | criteria provided, multiple submitters, no conflicts | 2 | 2538=C/match/P/2;97487=A/other-allele/U/1 | - | eligible |
| rs28940579 | G | Familial Mediterranean fever | 2540 | P | criteria provided, multiple submitters, no conflicts | 2 | 2540=G/match/P/2;2011491=C/other-allele/U/1;2637664=T/other-allele/U/1 | - | eligible |
| rs28940578 | T | Familial Mediterranean fever | 2539 | P | criteria provided, multiple submitters, no conflicts | 2 | 2539=T/match/P/2 | - | eligible |
| rs104895097 | T | Familial Mediterranean fever | 2549 | P | criteria provided, multiple submitters, no conflicts | 2 | 2549=T/match/P/2 | - | eligible |
| rs28940580 | T | Familial Mediterranean fever | 2550 | P | criteria provided, multiple submitters, no conflicts | 2 | 2550=T/match/P/2;36507=G/other-allele/P/2;234365=A/other-allele/P/2 | - | eligible |
| rs104895085 | T | Familial Mediterranean fever | 2553 | P | criteria provided, multiple submitters, no conflicts | 2 | 2553=T/match/P/2 | - | eligible |
| rs1799807 | C | Deficiency of butyrylcholinesterase | 13215 | P | criteria provided, multiple submitters, no conflicts | 2 | 13215=C/match/P/2 | - | eligible |
| rs121908529 | A | Primary hyperoxaluria, type I | 40166 | P | criteria provided, multiple submitters, no conflicts | 2 | 40166=A/match/P/2;2710435=C/other-allele/P/2 | - | eligible |
| rs185803104 | T | Primary hyperoxaluria type 3 | 204285 | P | criteria provided, multiple submitters, no conflicts | 2 | 204285=T/match/P/2 | - | eligible |
| rs180177314 | A | Primary hyperoxaluria, type II | 204235 | P | criteria provided, multiple submitters, no conflicts | 2 | 204235=A/match/P/2 | - | eligible |

### T3 Inheritance table

| rsID | model | one-copy meaning | two-copy meaning | inheritance sources (typed ids) |
|---|---|---|---|---|
| rs334 | AR | one copy: carrier of sickle cell trait | two copies: sickle cell disease | genereviews:NBK1377;medgen:C0002895 |
| rs33930165 | UNRESOLVED | - | - | - |
| rs113993960 | AR | one copy: carrier | two copies: cystic fibrosis | genereviews:NBK1250;medgen:C0010674 |
| rs1800562 | AR | one copy: carrier | two copies: hereditary hemochromatosis | genereviews:NBK1440;medgen:C3469186 |
| rs1799945 | AR | one copy: carrier | two copies: hereditary hemochromatosis | genereviews:NBK1440;medgen:C3469186 |
| rs6025 | AD-IP | one copy: increased association | two copies: further increased association | genereviews:NBK1368 |
| rs1799963 | AD-IP | one copy: increased association | two copies: further increased association | genereviews:NBK1148 |
| rs28929474 | UNRESOLVED | - | - | genereviews:NBK1519;medgen:C0221757 |
| rs61752717 | UNRESOLVED | - | - | medgen:C0031069 |
| rs28940579 | UNRESOLVED | - | - | medgen:C0031069 |
| rs28940578 | UNRESOLVED | - | - | medgen:C0031069 |
| rs104895097 | UNRESOLVED | - | - | medgen:C0031069 |
| rs28940580 | UNRESOLVED | - | - | medgen:C0031069 |
| rs104895085 | UNRESOLVED | - | - | medgen:C0031069 |
| rs1799807 | AR | one copy: carrier | two copies: deficiency of butyrylcholinesterase | medgen:C1283400 |
| rs121908529 | AR | one copy: carrier | two copies: primary hyperoxaluria, type I | medgen:C0268164 |
| rs185803104 | AR | one copy: carrier | two copies: primary hyperoxaluria type 3 | medgen:C3150878 |
| rs180177314 | AR | one copy: carrier | two copies: primary hyperoxaluria, type II | medgen:C0268165 |

### T4 Trait evidence table

| rsID | row id | study accession | PMID | trait (reported) | effect allele (fwd, GRCh37) | orientation | orientation source | direction | p-value | sample ancestry | sample size | cohort id | cohort source | overlap with | counted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rs11591147 | a14755030 | GCST000134 | 18193044 | LDL cholesterol | T | verified | dbsnp:rs11591147 | down | 2e-44 | - | - | dgi-fusion-sardinia | pmid:18193044 | - | yes |
| rs11591147 | a14981271 | GCST002898 | 25961943 | LDL cholesterol | G | verified | dbsnp:rs11591147 | up | 2e-92 | - | - | engage-consortium | pmid:25961943 | - | no:allele-mismatch |
| rs11591147 | a35811859 | GCST007141 | 29507422 | Low density lipoprotein cholesterol levels | G | verified | dbsnp:rs11591147 | up | 6e-70 | - | - | kaiser-permanente | pmid:29507422 | a35811864;a35811869;a80057298;a101329191;a101331236 | no:allele-mismatch |
| rs11591147 | a35811864 | GCST007141 | 29507422 | Low density lipoprotein cholesterol levels | G | verified | dbsnp:rs11591147 | up | 2e-12 | - | - | kaiser-permanente | pmid:29507422 | a35811859;a35811869;a80057298;a101329191;a101331236 | no:allele-mismatch |
| rs11591147 | a35811869 | GCST007141 | 29507422 | Low density lipoprotein cholesterol levels | G | verified | dbsnp:rs11591147 | up | 3e-12 | - | - | kaiser-permanente | pmid:29507422 | a35811859;a35811864;a80057298;a101329191;a101331236 | no:allele-mismatch |
| rs11591147 | a80057298 | GCST006612 | 30275531 | LDL cholesterol | T | verified | dbsnp:rs11591147 | down | 3e-257 | - | - | million-veteran-program | pmid:30275531 | a35811859;a35811864;a35811869;a101329191;a101331236 | yes |
| rs11591147 | a47293835 | GCST008077 | 30698716 | LDL cholesterol levels | T | verified | dbsnp:rs11591147 | down | 7e-52 | - | - | unknown | pmid:30698716 | - | no:cohort-unknown |
| rs11591147 | a47294023 | GCST008077 | 30698716 | LDL cholesterol levels | T | verified | dbsnp:rs11591147 | down | 9e-50 | - | - | unknown | pmid:30698716 | - | no:cohort-unknown |
| rs11591147 | a47738023 | GCST008676 | 30926973 | LDL cholesterol levels | T | verified | dbsnp:rs11591147 | down | 1e-51 | - | - | unknown | pmid:30926973 | - | no:cohort-unknown |
| rs11591147 | a56273805 | GCST010245 | 32203549 | LDL cholesterol levels | G | verified | dbsnp:rs11591147 | up | 2e-421 | - | - | uk-biobank | pmid:32203549 | - | no:allele-mismatch |
| rs11591147 | a93377763 | GCST90019512 | 33462484 | Low density lipoprotein cholesterol levels | T | verified | dbsnp:rs11591147 | down | 9e-591 | - | - | uk-biobank | pmid:33462484 | - | no:p-malformed |
| rs11591147 | a93518615 | GCST90018961 | 34594039 | LDL cholesterol | T | verified | dbsnp:rs11591147 | down | 2e-335 | - | - | biobank-japan | pmid:34594039 | - | no:p-malformed |
| rs11591147 | a101329191 | GCST90239658 | 34887591 | Low density lipoprotein cholesterol levels | T | verified | dbsnp:rs11591147 | down | 7e-1039 | - | - | global-lipids-genetics-consortium | pmid:34887591 | a35811859;a35811864;a35811869;a80057298;a101331236 | no:p-malformed |
| rs11591147 | a101331236 | GCST90239659 | 34887591 | Low density lipoprotein cholesterol levels | T | verified | dbsnp:rs11591147 | down | 3e-38 | - | - | global-lipids-genetics-consortium | pmid:34887591 | a35811859;a35811864;a35811869;a80057298;a101329191 | yes |
| rs11591147 | a96224439 | GCST90092883 | 35213538 | LDL cholesterol levels | G | verified | dbsnp:rs11591147 | up | 2e-83 | - | - | uk-biobank | pmid:35213538 | - | no:allele-mismatch |
| rs11591147 | a216839734 | GCST90827842 | 39091897 | LDL cholesterol levels | T | verified | dbsnp:rs11591147 | down | 6e-81 | - | - | uk-biobank | pmid:39091897 | - | yes |

Cell grammar: `orientation` is `verified` or `unverified`; `direction` is `up`,
`down` or `-`; `orientation source` and `cohort source` are typed ids or `-`;
`cohort id` is lower-case letters, digits and hyphens, or `unknown`;
`overlap with` is `-` or row ids separated by `;`; `counted` is `yes` or
`no:<drop code>`. The row kind is derived: a `GCST` accession is an association
row; `-` with a PMID is a functional row.

### T5 Pack inventory table

Copied by the curator from the frozen pack index; ids are public identifiers.

| rsID | ClinVar VariationIDs in pack (all assemblies) | pack file index id |
|---|---|---|
| rs334 | 15175;15333 | dbsnp:rs334;clinvar:vcv:15175;clinvar:vcv:15333;clinvar:rcv:RCV000016574;genereviews:NBK1377;medgen:C0002895;manifest:n0d-dbsnp-rs334;manifest:n0d-alleles |
| rs33930165 | 15126;15243;869230 | dbsnp:rs33930165;clinvar:vcv:15126;clinvar:vcv:15243;clinvar:vcv:869230;clinvar:rcv:RCV000016284;manifest:n0d-dbsnp-rs33930165;manifest:n0d-alleles |
| rs113993960 | 7105 | dbsnp:rs113993960;clinvar:vcv:7105;genereviews:NBK1250;medgen:C0010674;manifest:n0d-dbsnp-rs113993960;manifest:n0d-alleles |
| rs1800562 | 9 | dbsnp:rs1800562;clinvar:vcv:9;genereviews:NBK1440;medgen:C3469186;clinvar:rcv:RCV000000019;manifest:n0d-dbsnp-rs1800562;manifest:n0d-alleles |
| rs1799945 | 10 | dbsnp:rs1799945;clinvar:vcv:10;genereviews:NBK1440;medgen:C3469186;clinvar:rcv:RCV000394716;manifest:n0d-dbsnp-rs1799945;manifest:n0d-alleles |
| rs6025 | 642;226007 | dbsnp:rs6025;clinvar:vcv:642;clinvar:vcv:226007;genereviews:NBK1368;clinvar:rcv:RCV000454249;manifest:n0d-dbsnp-rs6025;manifest:n0d-alleles |
| rs1799963 | 13310 | dbsnp:rs1799963;clinvar:vcv:13310;genereviews:NBK1148;clinvar:rcv:RCV005419865;manifest:n0d-dbsnp-rs1799963;manifest:n0d-alleles |
| rs1050828 | - | dbsnp:rs1050828;manifest:n0d-dbsnp-rs1050828;manifest:n0d-alleles |
| rs28929474 | 17967;1492979 | dbsnp:rs28929474;clinvar:vcv:17967;clinvar:vcv:1492979;genereviews:NBK1519;medgen:C0221757;clinvar:rcv:RCV000148877;manifest:n0d-dbsnp-rs28929474;manifest:n0d-alleles |
| rs12913832 | 4745 | dbsnp:rs12913832;clinvar:vcv:4745;manifest:n0d-dbsnp-rs12913832;manifest:n0d-alleles |
| rs1805007 | 14312 | dbsnp:rs1805007;clinvar:vcv:14312;manifest:n0d-dbsnp-rs1805007;manifest:n0d-alleles |
| rs1805008 | 14310 | dbsnp:rs1805008;clinvar:vcv:14310;manifest:n0d-dbsnp-rs1805008;manifest:n0d-alleles |
| rs17822931 | 3558 | dbsnp:rs17822931;clinvar:vcv:3558;manifest:n0d-dbsnp-rs17822931;manifest:n0d-alleles |
| rs4988235 | 7685 | dbsnp:rs4988235;clinvar:vcv:7685;manifest:n0d-dbsnp-rs4988235;manifest:n0d-alleles |
| rs671 | 18390 | dbsnp:rs671;clinvar:vcv:18390;manifest:n0d-dbsnp-rs671;manifest:n0d-alleles |
| rs1229984 | 18182 | dbsnp:rs1229984;clinvar:vcv:18182;manifest:n0d-dbsnp-rs1229984;manifest:n0d-alleles |
| rs762551 | 511079 | dbsnp:rs762551;clinvar:vcv:511079;manifest:n0d-dbsnp-rs762551;manifest:n0d-alleles |
| rs72921001 | - | dbsnp:rs72921001;manifest:n0d-dbsnp-rs72921001;manifest:n0d-alleles |
| rs1426654 | 1487;263273 | dbsnp:rs1426654;clinvar:vcv:1487;clinvar:vcv:263273;manifest:n0d-dbsnp-rs1426654;manifest:n0d-alleles |
| rs16891982 | 4505;197829 | dbsnp:rs16891982;clinvar:vcv:4505;clinvar:vcv:197829;manifest:n0d-dbsnp-rs16891982;manifest:n0d-alleles |
| rs1800407 | 963 | dbsnp:rs1800407;clinvar:vcv:963;manifest:n0d-dbsnp-rs1800407;manifest:n0d-alleles |
| rs1042602 | 3778 | dbsnp:rs1042602;clinvar:vcv:3778;manifest:n0d-dbsnp-rs1042602;manifest:n0d-alleles |
| rs6152 | - | dbsnp:rs6152;manifest:n0d-dbsnp-rs6152;manifest:n0d-alleles |
| rs61752717 | 2538;97487 | dbsnp:rs61752717;clinvar:vcv:2538;clinvar:vcv:97487;clinvar:rcv:RCV000002647;medgen:C0031069 |
| rs28940579 | 2540;2011491;2637664 | dbsnp:rs28940579;clinvar:vcv:2011491;clinvar:vcv:2540;clinvar:vcv:2637664;clinvar:rcv:RCV000002649;medgen:C0031069 |
| rs28940578 | 2539 | dbsnp:rs28940578;clinvar:vcv:2539;clinvar:rcv:RCV000002648;medgen:C0031069 |
| rs104895097 | 2549 | dbsnp:rs104895097;clinvar:vcv:2549;clinvar:rcv:RCV000002658;medgen:C0031069 |
| rs28940580 | 2550;36507;234365 | dbsnp:rs28940580;clinvar:vcv:2550;clinvar:vcv:36507;clinvar:vcv:234365;clinvar:rcv:RCV000002659;medgen:C0031069 |
| rs104895085 | 2553 | dbsnp:rs104895085;clinvar:vcv:2553;clinvar:rcv:RCV000002662;medgen:C0031069 |
| rs1799807 | 13215 | dbsnp:rs1799807;clinvar:vcv:13215;clinvar:rcv:RCV000277104;medgen:C1283400 |
| rs121908529 | 40166;2710435 | dbsnp:rs121908529;clinvar:vcv:40166;clinvar:vcv:2710435;clinvar:rcv:RCV000032681;medgen:C0268164 |
| rs185803104 | 204285 | dbsnp:rs185803104;clinvar:vcv:204285;clinvar:rcv:RCV000186492;medgen:C3150878 |
| rs180177314 | 204235 | dbsnp:rs180177314;clinvar:vcv:204235;clinvar:rcv:RCV000186442;medgen:C0268165 |
| rs11591147 | 2878 | clinvar:vcv:2878;dbsnp:rs11591147;gwas:GCST000134;gwas:GCST002898;gwas:GCST006612;gwas:GCST007141;gwas:GCST008077;gwas:GCST008676;gwas:GCST010245;gwas:GCST90018961;gwas:GCST90019512;gwas:GCST90092883;gwas:GCST90239658;gwas:GCST90239659;gwas:GCST90827842;pmid:18193044;pmid:25961943;pmid:29507422;pmid:30275531;pmid:30698716;pmid:30926973;pmid:32203549;pmid:33462484;pmid:34594039;pmid:34887591;pmid:35213538;pmid:39091897 |

The `pack file index id` cell holds the typed ids that identify the pack files
for the rsID; together they form the set of evidence ids the replication check
accepts.

## Reserves and goals

Two to three reserves per group are fully sourced rows with decision `reserve`.
They satisfy every inclusion criterion and are never in the targets file, so a
poor coverage outcome can be answered by swapping reserves in without learning
which markers were missing.

Reserves recorded for this release:

- Health group: none. Every health-candidate row in the pool is either included or excluded above; no further row reaches every inclusion criterion.
- Trait group: none. No pool trait row has replicated, orientation-verified evidence under the curated label, so none is a fully sourced reserve.

For v0.1.0 no candidate remained that met every criterion for a reserve, so the record holds no reserve rows; the reserve rules above apply to later panels.

## Limitations

This record documents public-database evidence only.
For every marker, array presence is not verified: no public array manifest is in the evidence pack.
The report must never state that a marker is on the array.
Whether the panel is adequate is the owner's aggregate coverage judgment (counts only). No reserves exist for v0.1.0, so a coverage-poor outcome has no reserve swap. The pair rule trusts the captured placements and the
curated alias file; an unmapped record is listed but cannot be judged by the
checker, so a human reviewer reads every `?` item. Independence of cohorts is
conservative: when it cannot be shown from captured text, rows form one group.
Nothing here is medical advice, and no result is a diagnosis.

For this release the pool is the 23 DRAFT rsIDs of `data/targets.carrier.json` and `data/targets.traits.json`; no marker was added. The health rows keep carrier or association wording only, and no entry states a diagnosis or an absolute risk. Effect alleles were re-derived from the complete dbSNP GRCh37 allele set in N0d; the curated condition is attributed through a per-condition ClinVar record (RCV) whose condition names the curated label by the alias-file semantics, and that record's significance and stars are used, never the VCV aggregate (D-54-3); the strict other-condition outcome applies when no RCV names it. The alias file was extended with three reviewed synonyms and two aliases that named a different, bleeding disorder were removed (D-54-2). Palindromic reference/effect pairs (A/T or C/G) are excluded by default with reason code `palindromic` (D-54-1). Every trait row was excluded: each pigmentation trait is ancestry-informative, and no other trait has a replicated, orientation-verified association under the curated label. Whether the resulting panel is adequate is the owner's aggregate coverage judgment (counts only).

## Provenance block

Facts for the whole panel are recorded once, after the tables are filled.
Until then each value is a placeholder.

- Evidence pack ids: N0a (netpack-N0-review), N0b (netpack-N0b-review), N0c (netpack-N0c-review), N0d (netpack-N0d-review)
- Pack manifest sha256: N0a 0f14e7ae0e18b3ccbaf8914c951033aa4d2742a0e394b5e2857ee99fed15e908; N0b 13e94d7a39f38b148e821cc4ed692bb4b75fcb90f5445ffe05d37f63d34069dd; N0c bc47ad43c6a2ad1b3622df65a17a93a0335455485fe951d8e3d75a88148c4b48; N0d 2a69bcfbbabb2b10da5882f2c914ca62528352783e1f7aaf6b6dcad75b1dbb77
- Retrieval dates (UTC, ISO): 2026-11-09; v0.2.0 pack 2026-11-14
- v0.2.0 evidence pack: evidence/v0.2.0 (outside the repository), frozen manifest MANIFEST.sha256 sha256 0966f825ba9dcb7a9eb01761bd1f77c731ceca70a05dbb9d1ca47425ff04c4f0 (62 entries); captured 2026-11-14 (UTC); used for the five v0.2.0 candidates
- Source release identifiers: dbSNP GRCh37 placements and full refsnp allele sets (N0d), ClinVar variant_summary + VCV/RCV records, GWAS Catalog associations and study records, GeneReviews chapters and MedGen concepts, all captured 2026-11-09

## Curated evidence file

`data/targets.release-evidence.json` mirrors, for each included carrier target,
the attributing per-condition ClinVar record (RCV) already cited in that row's
T1 sources and T5 index: the curated condition label, the RCV id, that RCV's
classification text and review status exactly as captured, and its star count.
The release build reads it with `--curated-evidence`, uses that record in place
of the `variant_summary` aggregate for the entry's ClinVar block, and never
marks a trait target's ClinVar evidence matched. A release-format targets file
with a carrier entry refuses to build without the flag.

## Release panel build

The release panel is the reproducible build of the curated targets
`data/targets.release.json` against frozen public-evidence packs, committed
byte-for-byte as `data/targets.release-panel.json`. The file is a built
artifact, not a hand-edited curation record; its `targets.*`-style name is a
documented limitation (it shares the curated-targets naming pattern only).

The v0.1.0 build had three entries (pack N1). The v0.2.0 build has eight: the
three v0.1.0 entries (rs1800562, rs1799963, rs6025) reuse the N1 cache rows
unchanged, and the five new entries (rs1799807, rs121908529, rs185803104,
rs180177314, rs11591147) take their data from the v0.2.0 evidence pack. The
three v0.1.0 entries are identical to the v0.1.0 panel.

- Evidence packs: N1 (public-reference request list approved 2026-11-11; the pack stays outside the repository) for the three v0.1.0 entries; the v0.2.0 evidence pack (`evidence/v0.2.0`, outside the repository) for the five new entries
- Pack manifest sha256: N1 63a702401febcb722ef9795e0a27ab2dc26ad3aaedf04c3e9f9dba721865cab0; v0.2.0 0966f825ba9dcb7a9eb01761bd1f77c731ceca70a05dbb9d1ca47425ff04c4f0
- Capture time (UTC, ISO): N1 2026-11-11T19:57:14Z; v0.2.0 dbSNP records 2026-11-14T04:43:29Z, GWAS Catalog associations 2026-11-14T04:50:49Z, ClinVar variant_summary 2026-11-14T00:30:32Z, gnomAD and Open Targets answers 2026-11-14T14:16:36Z to 2026-11-14T14:16:47Z (from file times, converted with the owner's -06:00 offset; the owner confirms). The build `--retrieved-at` is the latest, 2026-11-14T14:16:47Z.
- Built from the clean export of commit: b087a2c71cee8adc2baf2b06f3268ce3b7ca8254 with the `panel_version` edit of this change (tools and alias file unchanged)
- Sources for the five new entries: dbSNP placements parsed from the pack's variation-API records with the repo's own parser (`fetch_dbsnp_small`); ClinVar from the pack's `variant_summary.txt.gz` (carrier entries use the curated evidence file instead); gnomAD allele frequency of the effect allele, genome frequency else exome frequency, from the captured answers (rs180177314 has an exome frequency only); Open Targets GWAS rows for the four carriers exactly as captured (rs1799807 8 rows, rs185803104 2 rows, rs121908529 and rs180177314 returned none and are recorded as absent); for rs11591147, rows from the pack's GWAS Catalog REST associations, one row per accession and reported trait (741 rows), because the captured Open Targets answer (25 rows) matches no LDL-level trait
- Cache assembly (offline, no network): dbSNP, gnomAD and GWAS rows of the three v0.1.0 entries are copied from the N1 cache without change; the other rows are appended as described above
- Source labels in the panel name both capture dates: dbSNP "variation-api-2026-11-11 (3 entries) and 2026-11-14 (5 entries)"; ClinVar "variant_summary-2026-11-14"; gnomAD "graphql-2026-11-11 (3 entries) and 2026-11-14 (5 entries)"; GWAS Catalog "opentargets-2026-11-11 (3 entries); opentargets-2026-11-14 (4 carriers); gwas-catalog-rest-2026-11-14 (rs11591147)"
- Build command (run from that export, no network; `<CACHE>` is the assembled cache directory):

```
python3.12 -B tools/build_panel.py --targets data/targets.release.json \
  --curated-evidence data/targets.release-evidence.json --cache <CACHE> \
  --retrieved-at 2026-11-14T14:16:47Z \
  --dbsnp-release "variation-api-2026-11-11 (3 entries) and 2026-11-14 (5 entries)" \
  --clinvar-release "variant_summary-2026-11-14" \
  --gnomad-release "graphql-2026-11-11 (3 entries) and 2026-11-14 (5 entries)" \
  --gwas-release "opentargets-2026-11-11 (3 entries); opentargets-2026-11-14 (4 carriers); gwas-catalog-rest-2026-11-14 (rs11591147)" \
  -o data/targets.release-panel.json
```

- Determinism: two builds from the same cache were byte-identical (`cmp`).
- Panel file sha256: 7acfdde8e216a97e2d245c324af9a2f588b3578a5b3bf3bd32f025a94469c6d7
