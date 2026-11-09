# Release panel curation

Status: method-only

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
surrounding spaces, the same rule as the T2 `pair condition`). A checker error
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
error. The tables have no rows until the data ticket fills them.

### T1 Decision table

| rsID | gene | chrom (GRCh37) | label used in report | result type | category | effect allele (fwd, GRCh37) | direction/meaning | build/strand | assayability_status | assayability_source | sources (typed ids) | retrieved (UTC date) | rationale | limitations | decision | reason code |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

The `decision` is `included`, `excluded` or `reserve`. The `build/strand` cell
is `GRCh37/forward`, optionally followed by `;strand-ambiguous` on an excluded
palindromic row; an excluded row may carry `-`.

### T2 ClinVar pair table

One row per health-related rsID; trait rows do not appear.

| rsID | pair allele (fwd GRCh37) | pair condition | matched record ids | matched significance | matched review status | stars | considered records | resolution | pair outcome |
|---|---|---|---|---|---|---|---|---|---|

### T3 Inheritance table

| rsID | model | one-copy meaning | two-copy meaning | inheritance sources (typed ids) |
|---|---|---|---|---|

### T4 Trait evidence table

| rsID | row id | study accession | PMID | trait (reported) | effect allele (fwd, GRCh37) | orientation | orientation source | direction | p-value | sample ancestry | sample size | cohort id | cohort source | overlap with | counted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

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

The `pack file index id` cell holds the typed ids that identify the pack files
for the rsID; together they form the set of evidence ids the replication check
accepts.

## Reserves and goals

Two to three reserves per group are fully sourced rows with decision `reserve`.
They satisfy every inclusion criterion and are never in the targets file, so a
poor coverage outcome can be answered by swapping reserves in without learning
which markers were missing.

## Limitations

This record documents public-database evidence only.
For every marker, array presence is not verified: no public array manifest is in the evidence pack.
The report must never state that a marker is on the array.
Whether the panel is adequate is the owner's aggregate coverage judgment (counts only), with the reserves as the remedy. The pair rule trusts the captured placements and the
curated alias file; an unmapped record is listed but cannot be judged by the
checker, so a human reviewer reads every `?` item. Independence of cohorts is
conservative: when it cannot be shown from captured text, rows form one group.
Nothing here is medical advice, and no result is a diagnosis.

## Provenance block

Facts for the whole panel are recorded once, after the tables are filled.
Until then each value is a placeholder.

- Evidence pack ids: PLACEHOLDER
- Pack manifest sha256: PLACEHOLDER
- Retrieval dates (UTC, ISO): PLACEHOLDER
- Source release identifiers: PLACEHOLDER
