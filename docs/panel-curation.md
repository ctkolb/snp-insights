# Release panel curation

Status: curated, 44 rows

This document defines how markers are chosen for the release panel
(`data/targets.release.json`) and how each decision is recorded so that it can be
checked offline. It contains the method, the fixed record tables and their rules.
Its tables hold the curated rows for real public markers; every identifier in
the method examples is invented. The consistency suite is
`tests/test_release_panel.py` (run it with `python -B tests/test_release_panel.py`).
The suite runs the same checkers on invented fixtures, which prove that each rule
can fail, and on this document's tables.

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

The disease-association contract ([disease-associations.md](disease-associations.md),
C-3) defines one more pair for table T1 only:

| result type | category | meaning |
|---|---|---|
| `disease_association` | `disease` | GWAS association of one allele with higher or lower odds of one named disease; population-level association wording only, never a diagnosis, a personal risk or carrier wording |

A T1 row may carry this pair now. The targets file and the build still reject it
until the production support of stage S3 lands; the section Disease
associations below holds its rules.

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
`RF`; `n/a` with `trait`; `SUSC` with `disease_association` and no
supporting group (`-`; contract C-31). Every other combination is an error. Each health row
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
`medgen:<id>`, `clingen:<id>`, `manifest:<id>`, and
`gnomad:<chrom>-<pos>-<ref>-<alt>` (grammar `[0-9XY]+-\d+-[ACGT]+-[ACGT]+`
after the prefix; the gnomAD answer behind a recorded allele frequency,
contract C-50). Dates are ISO calendar dates
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
- `proxy-only` (disease rows: the candidate has no T4 row under its own rsID,
  and the pack holds rows only for rsIDs linked to it; never used when any row
  exists under the candidate rsID, which is `label-mismatch` when every such
  row reports a different phenotype; contract C-12, C-49)
- `ancestry-unrecorded` (disease rows: the rows that would count lack a
  recorded ancestry or sample size for their stage, so fewer than the required
  groups remain; contract C-25, C-49)
- `x-linked-out-of-scope` (retired; replaced by the autosomal code above)

## Disease associations

Rows of the pair `disease_association` / `disease` follow the contract in
[disease-associations.md](disease-associations.md) (clauses C-1 to C-54). Its
curation rules use the existing tables T1, T3, T4 and T5 (no new table, no new
column); `tests/test_release_panel.py` checks each rule below on invented
fixtures.

Phenotype: a T4 row counts only when its reported trait equals the label or an
alias-file member after normalization; containment never counts, so a
composite such as "X or Y" is dropped `trait-mismatch` (C-7).

Evidence groups: an entry needs two independent groups, each holding a counted
association row with p at or below 5e-8; a functional row never counts and
is dropped `functional-not-counted` (C-15). Disease cohort ids start with a
kind prefix: `meta-` (a meta-analysis),
`consortium-` (one consortium lineage), `biobank-` (one biobank) or `study-`
(any other cohort). By default every `meta-` row is clustered with every other
`meta-`, `consortium-` and `biobank-` row; only an `independence:` token for
that cohort pair separates them. A status of `not-significant` maps to
`no-independent-confirmation`.

Stage, ancestry and size (C-22): the `sample ancestry` cell is
`<stage>:<code>[+<code>...]` and the `sample size` cell is
`<stage>:<cases>/<controls>` or `<stage>:n=<total>`, where `<stage>` is
`discovery`, `replication` or `combined` and is the same in both cells, and
each code is from the closed vocabulary `european`, `east-asian`,
`south-asian`, `african`, `hispanic-latino`, `middle-eastern`, `oceanian`,
`mixed`, `other`. A row with `-` in either cell is dropped
`ancestry-unrecorded`; when fewer than two significant groups remain because of
such rows, the entry is excluded `ancestry-unrecorded`.

T1 `direction/meaning` of an included or reserve disease row is exactly
`susceptibility: each copy of the <X> allele is associated with higher odds of <label> in studies; association wording only`
or
`protective: each copy of the <X> allele is associated with lower odds of <label> in studies; association wording only`,
with the T1 effect allele and label; the word equals the direction of the
counted rows (`up` is susceptibility, `down` is protective).

Tokens on an included or reserve disease row, each a `; `-separated item:

- rationale `independence:<cohort-a>|<cohort-b>=<typed id>[,<typed id>...] (<basis>)`,
  one for every pair of counted groups; each typed id is in the evidence pack;
- rationale `or:<row id>=<value> (<low>-<high>)` for the strongest counted row
  (lowest p) of every counted group; the value is above one for `up` and below
  one for `down`, and lies within its interval;
- rationale `af-spread:<number> over <group>[,<group>...]`, a number from 0 to 1
  over two or more of `afr`, `amr`, `asj`, `eas`, `fin`, `nfe`, `sas`;
- rationale `alias-review:<alias>=<sameness reason>` for every alias a counted
  row used;
- limitations `ancestry-scope:<code>[,<code>...]`, in vocabulary order, equal to
  the codes of the counted rows at p at or below 5e-8.

T3: a kept disease row has model `SUSC`, the copy meanings
`one copy: higher association with <label>` and
`two copies: further higher association with <label>` (`lower` for a
protective row), and a `pmid`, `genereviews`, `medgen` or `clingen` source. A
disease row has no T2 row.

Exclusions: `label-mismatch` needs at least one T4 row under the candidate
rsID, every one dropped `trait-mismatch`; `proxy-only` needs none (C-12, C-49).
A disease label matching a forbidden report pattern of contract C-43, other
than through the word "disease", is an error (C-44).

Scope (C-52): the candidates rs10757278, rs2200733, rs11209026 and rs4245791
each have a disease T1 row with a decision, and the existing rs11887534 row has
a decision; included disease rows and disease entries of the targets file are
the same set. An all-excluded outcome is valid.

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
| rs1800562 | HFE | 6 | Hereditary hemochromatosis | carrier_status | carrier | A | one copy: carrier of the C282Y allele; two copies: hereditary hemochromatosis | GRCh37/forward | unknown-provisional | - | dbsnp:rs1800562;clinvar:vcv:9;genereviews:NBK1440;medgen:C3469186;clinvar:rcv:RCV000000019;manifest:n0d-dbsnp-rs1800562;manifest:n0d-alleles | 2026-11-09 | strand: non-palindromic G/A; report-safety: carrier wording, no diagnosis; not ancestry-informative; O-3: RCV000000019 (Hemochromatosis type 1) names the curated label through the alias "hemochromatosis type 1"; D-54-3: the attributing record RCV000000019 is Pathogenic with multiple submitters (2 stars), not the one-star RCV000308358; O-1: N0d alleles G>A,T, effect allele A | array presence not verified; the record classification is shared across several conditions but an RCV names the curated one; multi-allelic site (dbSNP alternates A, T): criteria 1 and 4 are read for the reference/effect pair (D8) | included | - |
| rs1799945 | HFE | 6 | Hereditary hemochromatosis | carrier_status | carrier | G | one copy: carrier; two copies: hereditary hemochromatosis | GRCh37/forward;strand-ambiguous | unknown-provisional | - | dbsnp:rs1799945;clinvar:vcv:10;genereviews:NBK1440;medgen:C3469186;clinvar:rcv:RCV000394716;manifest:n0d-dbsnp-rs1799945;manifest:n0d-alleles | - | strand: palindromic reference/effect pair C/G (N0d reference C, effect allele G), excluded per D-54-1; report-safety: carrier wording; not ancestry-informative; O-3: RCV000394716 names the curated condition; D-54-3: the attributing record RCV000394716 is Pathogenic, low penetrance (1 star); O-1: N0d alleles C>G,T, effect allele G | array presence not verified; palindromic site (reference/effect C/G), excluded by default | excluded | palindromic |
| rs6025 | F5 | 1 | Factor V Leiden thrombophilia | risk_association | carrier | T | one copy: increased association; two copies: further increased association | GRCh37/forward | unknown-provisional | - | dbsnp:rs6025;clinvar:vcv:642;genereviews:NBK1368;clinvar:rcv:RCV000454249;manifest:n0d-dbsnp-rs6025;manifest:n0d-alleles | 2026-11-09 | strand: reference/effect pair T/T, not A/T or C/G, non-palindromic; report-safety: association wording without carrier; not ancestry-informative; O-3: RCV000454249 names the curated condition by alias (thrombophilia due to activated protein C resistance); D-54-3: the attributing record RCV000454249 is Pathogenic with multiple submitters (2 stars), not the expert-panel drug-response aggregate; O-1: N0d alleles T>C,A,G, effect allele T | array presence not verified; dominant reduced-penetrance association, never a diagnosis; multi-allelic site (dbSNP alternates C, A, G): criteria 1 and 4 are read for the reference/effect pair (D8) | included | - |
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
| rs1799807 | BCHE | 3 | Deficiency of butyrylcholinesterase | carrier_status | carrier | C | one copy: carrier; two copies: deficiency of butyrylcholinesterase | GRCh37/forward | unknown-provisional | - | dbsnp:rs1799807;clinvar:vcv:13215;clinvar:rcv:RCV000277104;medgen:C1283400 | 2026-11-14 | strand: non-palindromic T/C pair (dbSNP alts A, C; the A alt is palindromic and has no ClinVar record in the pack); report-safety: carrier wording, no diagnosis; the drug-response label "Postanesthetic apnea" (RCV000014102, no assertion criteria, 0 stars) is not used; not ancestry-informative (no captured source ties the marker to ancestry; curator judgment); O-3: RCV000277104 (Deficiency of butyrylcholinesterase) names the curated label exactly (alias not needed); D-54-3: the attributing record RCV000277104 is Pathogenic/Likely pathogenic with multiple submitters (2 stars), not the 0-star RCV000014102; D8: criteria 1 and 4 read on the reference/effect pair; inheritance: MedGen C1283400 lists autosomal recessive inheritance | array presence not verified; the clinical relevance of this concept is a drug response, which the report does not state; the record classification is shared across several conditions but an RCV names the curated one; the MedGen text defines the recessive model by two pathogenic alleles and does not itself state the one-copy carrier meaning; multi-allelic site (dbSNP alternates A, C): criteria 1 and 4 are read for the reference/effect pair (D8) | included | - |
| rs121908529 | AGXT | 2 | Primary hyperoxaluria, type I | carrier_status | carrier | A | one copy: carrier; two copies: primary hyperoxaluria, type I | GRCh37/forward | unknown-provisional | - | dbsnp:rs121908529;clinvar:vcv:40166;clinvar:rcv:RCV000032681;medgen:C0268164 | 2026-11-14 | strand: non-palindromic G/A pair (dbSNP alts A, C, T; the C alt is palindromic and is the other-allele item VCV 2710435); report-safety: carrier wording, no diagnosis; not ancestry-informative (no captured source ties the marker to ancestry; curator judgment); O-3: RCV000032681 (Primary hyperoxaluria, type I) names the curated label exactly (alias not needed); D-54-3: the attributing record RCV000032681 is Pathogenic/Likely pathogenic with multiple submitters (2 stars); D8: criteria 1 and 4 read on the reference/effect pair; inheritance: MedGen C0268164 lists autosomal recessive inheritance | array presence not verified; multi-allelic site (D8): the G>C allele (VCV 2710435) is also a pathogenic classification and is not counted; the MedGen text defines the recessive model by two pathogenic alleles and does not itself state the one-copy carrier meaning; multi-allelic site (dbSNP alternates A, C, T): criteria 1 and 4 are read for the reference/effect pair (D8) | included | - |
| rs185803104 | HOGA1 | 10 | Primary hyperoxaluria type 3 | carrier_status | carrier | T | one copy: carrier; two copies: primary hyperoxaluria type 3 | GRCh37/forward | unknown-provisional | - | dbsnp:rs185803104;clinvar:vcv:204285;clinvar:rcv:RCV000186492;medgen:C3150878 | 2026-11-14 | strand: non-palindromic G/T pair (dbSNP alt T only); report-safety: carrier wording, no diagnosis; not ancestry-informative (no captured source ties the marker to ancestry; curator judgment); O-3: RCV000186492 (Primary hyperoxaluria type 3) names the curated label exactly (alias not needed); D-54-3: the attributing record RCV000186492 is Pathogenic with multiple submitters (2 stars); D8: criteria 1 and 4 read on the reference/effect pair; inheritance: MedGen C3150878 lists autosomal recessive inheritance | array presence not verified; intronic splice-region change (c.700+5G>T), not a protein change; the MedGen text defines the recessive model by two pathogenic alleles and does not itself state the one-copy carrier meaning | included | - |
| rs180177314 | GRHPR | 9 | Primary hyperoxaluria, type II | carrier_status | carrier | A | one copy: carrier; two copies: primary hyperoxaluria, type II | GRCh37/forward | unknown-provisional | - | dbsnp:rs180177314;clinvar:vcv:204235;clinvar:rcv:RCV000186442;medgen:C0268165 | 2026-11-14 | strand: non-palindromic G/A pair (dbSNP alt A only); report-safety: carrier wording, no diagnosis; not ancestry-informative (no captured source ties the marker to ancestry; curator judgment); O-3: RCV000186442 (Primary hyperoxaluria, type II) names the curated label exactly (alias not needed); D-54-3: the attributing record RCV000186442 is Pathogenic/Likely pathogenic with multiple submitters (2 stars); D8: criteria 1 and 4 read on the reference/effect pair; inheritance: MedGen C0268165 lists autosomal recessive inheritance | array presence not verified; the MedGen text defines the recessive model by two pathogenic alleles and does not itself state the one-copy carrier meaning | included | - |
| rs11591147 | PCSK9 | 1 | LDL cholesterol levels | trait | trait | T | each copy of the T allele is associated with lower LDL cholesterol in studies; no more than association wording | GRCh37/forward | unknown-provisional | - | dbsnp:rs11591147;clinvar:vcv:2878;gwas:GCST000134;gwas:GCST006612;gwas:GCST90239659;gwas:GCST90827842;pmid:18193044;pmid:30275531;pmid:34887591;pmid:39091897 | 2026-11-14 | strand: non-palindromic G/T (dbSNP GRCh37 SPDI alleles G>A,T; reference G, effect T); report-safety: association wording, no diagnosis, no absolute risk, not a recommendation; not ancestry-informative (no captured source ties LDL cholesterol to ancestry; the T-allele frequency in the captured association rows ranges 0.007-0.033 and is not verified by ancestry; judged not ancestry-informative under criterion 8, owner decision P-4); replicated under the Replication rule: 3 independent groups, all direction down for the T allele, rows a14755030,a80057298,a101331236,a216839734; orientation: effect allele letter T or G equals a dbSNP forward allele and no row reports the complement letter A or C (source dbsnp:rs11591147); ClinVar VCV 2878 (Benign/Likely benign, 2 stars) is not used for trait eligibility; label alias-file groups: {"LDL cholesterol levels": ["low density lipoprotein cholesterol levels", "ldl cholesterol"]} | array presence not verified; study sample ancestry and size not captured (T4 cells hold -); cohort independence derived from PubMed abstract text only; multi-allelic site (dbSNP alternates A, T): criteria 1 and 4 are read for the reference/effect pair (D8) | included | - |
| rs10455872 | LPA | 6 | Lipoprotein(a) levels | trait | trait | G | not applicable | GRCh37/forward | unknown-provisional | - | dbsnp:rs10455872;gwas:GCST011087;gwas:GCST001218;gwas:GCST012232;gwas:GCST90453146;pmid:33115273;pmid:21900290;pmid:33730874;pmid:39972214 | 2026-11-23 | strand: non-palindromic A/G (dbSNP NC_000006.11 6:161010118 A>G; gene LPA minus, gene-strand T>C); evidence effect allele G, higher Lp(a) (rows a64204762, a19037; A lowers it, a80642320); report-safety: association wording, no diagnosis; D-3: gnomAD v2.1.1 G frequency 0.001 (eas) to 0.070 (nfe), spread 0.070, below the 0.20 threshold, not flagged (genome only, sas not covered); replication: single-study, one counted group (a19037, nhs-hpfs-diabetes, p 5e-39); a64204762 (UK Biobank, p 6e-22136) is p-malformed because the value underflows (AL-048); a80642320 reports allele A and names no cohort; a214359134 is LPA protein, a different trait | array presence not verified; one counted study group (a19037, nhs-hpfs-diabetes): PMID 21900290 pools two prospective type 2 diabetes cohorts, the Nurses' Health Study and the Health Professionals Follow-Up Study, in one study, with 1,450 European participants in the Catalog row; the strongest rows cannot count because their p-values underflow (AL-048) | excluded | single-study |
| rs3798220 | LPA | 6 | Lipoprotein(a) levels | trait | trait | C | not applicable | GRCh37/forward | unknown-provisional | - | dbsnp:rs3798220;gwas:GCST90019513;pmid:33462484 | 2026-11-23 | strand: non-palindromic T/C (dbSNP NC_000006.11 6:160961137 T>C; gene LPA minus, gene-strand A>G); evidence effect allele C, higher Lp(a) (a87278698); report-safety: association wording; D-3: gnomAD v2.1.1 C frequency 0.002 (asj) to 0.277 (amr), spread 0.275, at or above the 0.20 threshold, flagged; replication: no counted group, the only Lp(a) row in the pack is UK Biobank with p 2e-456, which underflows and is p-malformed (AL-048); the other seven association records for this rsID are other phenotypes (apolipoprotein B, LDL cholesterol, total cholesterol, triglycerides, VLDL cholesteryl ester, a protein level ratio and coronary heart disease); the replication code is given first and the screen flag is recorded here (owner decision T-3) | array presence not verified; single row, single cohort, underflowing p-value; flagged by the ancestry screen | excluded | no-independent-confirmation |
| rs6544713 | ABCG8 | 2 | LDL cholesterol levels | trait | trait | T | not applicable | GRCh37/forward | unknown-provisional | - | dbsnp:rs6544713;gwas:GCST008676;gwas:GCST000287;gwas:GCST008037;gwas:GCST008045;pmid:30926973;pmid:19060906;pmid:31217584 | 2026-11-23 | strand: the effect allele T is the reference allele and the other observed allele is C (dbSNP NC_000002.11 2:44073881 T>A,C; non-palindromic T/C, the palindromic alt A is absent in gnomAD); evidence effect allele T, higher LDL (a47738071, a12280); report-safety: LDL finding only, association wording, no gallstone wording; D-3: gnomAD v2.1.1 T frequency 0.004 (eas) to 0.319 (nfe), spread 0.314, at or above the 0.20 threshold, flagged; replication: no counted group, both T rows name no cohort in the captured abstracts (cohort-unknown) and the PAGE rows report allele ?; the replication code is given first and the screen flag is recorded here (owner decision T-3) | array presence not verified; flagged by the ancestry screen; cohorts of the two usable rows not named in captured text; shares the label with rs11591147 (D-5) | excluded | evidence-not-in-pack |
| rs2282679 | GC | 4 | 25-hydroxyvitamin D levels | trait | trait | T | not applicable | GRCh37/forward | unknown-provisional | - | dbsnp:rs2282679;gwas:GCST005782;gwas:GCST005366;gwas:GCST000664;gwas:GCST90020244;gwas:GCST90837321;gwas:GCST001560;gwas:GCST000697;pmid:29325163;pmid:29343764;pmid:20418485;pmid:34308111;pmid:42509370;pmid:22673963;pmid:20541252 | 2026-11-23 | strand: pair T/G non-palindromic (dbSNP NC_000004.11 4:72608383 T>A,C,G; alts A, C absent in gnomAD; gene GC minus); evidence effect allele T, higher 25(OH)D (a30522242, a30522310); report-safety: circulating 25(OH)D only, not intake, supplement response or insufficiency; D-3: gnomAD v2.1.1 T frequency 0.712 (nfe) to 0.914 (afr), spread 0.202 over afr, amr, eas, fin and nfe, at or above the 0.20 threshold, flagged (borderline, genome only); replication: single-study, the only counted group is TRANSCEN-D (29325163), whose text declares the SUNLIGHT European sample as a component (overlaps 29343764); a30522325 has no direction in the pack (direction-missing); rows with allele C (a15179, complement of G), G (insufficiency, pregnancy) or ? do not count; the replication code is given first and the screen flag is recorded here (owner decision T-3) | array presence not verified; flagged by the ancestry screen; one counted group; shares the label with rs10741657 (D-5) | excluded | single-study |
| rs10741657 | CYP2R1 | 11 | 25-hydroxyvitamin D levels | trait | trait | A | each copy of the A allele is associated with higher 25-hydroxyvitamin D levels in studies; no more than association wording | GRCh37/forward | unknown-provisional | - | dbsnp:rs10741657;gwas:GCST005367;gwas:GCST005366;gwas:GCST005782;gwas:GCST012014;gwas:GCST000697;pmid:29343764;pmid:29325163;pmid:33382404;pmid:20541252 | 2026-11-23 | included by owner decision T-1; promoted to `included` in S2 together with the targets entry and panel rebuild; strand: A/G non-palindromic (raw dbSNP record NC_000011.9 11:14914878 A>C,G; gene CYP2R1 minus, gene-strand T>G, T>C; the pack's placements.tsv row for this rsID names an alternate scaffold and is not used); report-safety: circulating 25-hydroxyvitamin D only, association wording, no intake, supplement or deficiency wording; D-3: gnomAD v2.1.1 genome answer for 11-14914878-A-G in the v0.3.0 supplement (the A>C allele is not found and counts as zero), A frequency 0.265 (afr) to 0.427 (fin), spread 0.162 over afr, amr, eas, fin and nfe, below the 0.20 threshold, not flagged (asj has 288 alleles, below the 500-allele floor; sas not covered); replication: replicated under the Replication rule, 2 independent groups, a27362261 (sunlight, p 2e-46) and a64666345 (finnish-health-2011, p 3e-11), both up for the A allele; a30522333 (transcend, declared overlap with SUNLIGHT) has no direction in the pack (direction-missing); a27438761 (intake interaction) and a15417 (insufficiency) are different traits; label alias-file groups: {"25-hydroxyvitamin D levels": ["serum 25-hydroxyvitamin d levels", "vitamin d levels"]} | array presence not verified; the counted evidence covers European-ancestry samples (SUNLIGHT) and a Finnish sample (Finnish Health 2011), so results may not transfer to other populations; possible overlap of the Finnish Health 2011 cohort with SUNLIGHT (whose study records list Finland) is neither shown nor ruled out by captured text and is accepted by owner decision T-1 (D-4a); if the two overlap, the evidence is a single study; multi-allelic site (dbSNP alternates C, G): criteria 1 and 4 are read for the reference/effect pair (D8) | included | - |
| rs601338 | FUT2 | 19 | Total vitamin B12 levels | trait | trait | - | not applicable | GRCh37/forward | unknown-provisional | - | dbsnp:rs601338;gwas:GCST90475776;pmid:39024449 | 2026-11-23 | strand: non-palindromic G/A (dbSNP NC_000019.9 19:49206674 G>A; gene FUT2 plus); no evidence effect allele for the label; report-safety: association wording; D-3: gnomAD v2.1.1 A frequency 0.002 (eas) to 0.497 (afr), spread 0.495, at or above the 0.20 threshold, flagged; replication: no row for total B12 levels or any B12 fraction exists among the 205 rows for this rsID; the only B12 row is a PheCode B12 deficiency anemia (a228361273), a disease phenotype, dropped trait-mismatch; the replication code is given first and the screen flag is recorded here (owner decision T-3) | array presence not verified; no evidence in the pack for the label; flagged by the ancestry screen | excluded | no-independent-confirmation |
| rs6795970 | SCN10A | 3 | ECG PR interval | trait | trait | A | not applicable | GRCh37/forward | unknown-provisional | - | dbsnp:rs6795970;gwas:GCST008042;gwas:GCST000561;gwas:GCST000564;pmid:31217584;pmid:20062063;pmid:20062061 | 2026-11-23 | strand: A/G non-palindromic (dbSNP NC_000003.11 3:38766675 A>G,T; alt T palindromic with ref A, absent in gnomAD; gene SCN10A minus, gene-strand T>C); evidence effect allele A, longer PR interval (a14399, a14396); report-safety: PR interval only, no arrhythmia wording; D-3: gnomAD v2.1.1 A frequency 0.089 (afr) to 0.455 (fin), spread 0.366, at or above the 0.20 threshold, flagged; replication: no counted group, the only row with the reported trait PR interval (a47265313, PAGE) reports allele ? and does not match the label text; the A rows are reported as Electrocardiographic traits, a string the same study also uses for QRS duration, so it is not aliased (owner decision T-5) and both rows name no cohort; the replication code is given first and the screen flag is recorded here (owner decision T-3) | array presence not verified; flagged by the ancestry screen; no row with the label and a known allele | excluded | no-independent-confirmation |
| rs174537 | MYRF | 11 | Arachidonic acid levels | trait | trait | T | not applicable | GRCh37/forward | unknown-provisional | - | dbsnp:rs174537;gwas:GCST90060580;gwas:GCST90277304;pmid:34503513;pmid:37907536 | 2026-11-23 | strand: G/T non-palindromic (dbSNP NC_000011.9 11:61552680 G>C,T; alt C palindromic with ref G, absent in gnomAD); gene cell: dbSNP annotates MYRF and the GWAS rows map MYRF and TMEM258; no captured record names FADS1 or FADS2, so the roadmap's gene pair is not used (owner decision T-6); evidence effect allele T, lower 20:4-containing lipid species (all rows down); report-safety: association wording; D-3: gnomAD v2.1.1 T frequency 0.081 (afr) to 0.604 (amr), spread 0.523, at or above the 0.20 threshold, flagged; replication: no row names arachidonic acid; the rows are phospholipid, glyceride and cholesteryl-ester species with a 20:4 chain, plus one free fatty acid (20:4) row (allele C, South Asian cohort); the replication code is given first and the screen flag is recorded here (owner decision T-3) | array presence not verified; the roadmap names this locus FADS1/FADS2 but captured annotations name MYRF; strongly ancestry-differentiated | excluded | no-independent-confirmation |
| rs1801133 | MTHFR | 1 | Plasma total homocysteine | trait | trait | A | not applicable | GRCh37/forward | unknown-provisional | - | dbsnp:rs1801133;gwas:GCST90429184;gwas:GCST90319530;gwas:GCST002087;gwas:GCST000367;gwas:GCST90090974;gwas:GCST009171;gwas:GCST007578;pmid:38626723;pmid:37479695;pmid:23824729;pmid:20031578;pmid:34707639;pmid:23696881;pmid:30339177 | 2026-11-23 | strand: G/A non-palindromic (dbSNP NC_000001.10 1:11856378 G>A,C,T; alt C palindromic with ref G, absent in gnomAD; gene MTHFR minus; the 677T name is the gene-strand letter for forward A); evidence effect allele A, higher homocysteine (rows a134087602, a129422187, a34417, a14036); report-safety: association wording, no folate or supplement wording; D-3: gnomAD v2.1.1 A frequency 0.109 (afr) to 0.502 (amr), spread 0.393, at or above the 0.20 threshold, flagged; replication: replicated by three groups (korea4k, stromics, wghs), all up; wghs is the Women's Genome Health Study named in PMID 20031578 (13,974 white women; the 840-person PROCARDIS replication sample is in the same row); the 44,147-participant European meta-analysis row (a34417) names no component cohort in captured text; excluded ancestry-informative under criterion 8 (owner decision T-2) | array presence not verified; the counted groups are Korean, Han Chinese ischemic stroke patients and white women of European ancestry, so results may not transfer to other populations; the measured form (total) of the counted rows is not stated in captured text; flagged by the ancestry screen | excluded | ancestry-informative |
| rs11887534 | ABCG8 | 2 | LDL cholesterol levels | trait | trait | - | not applicable | GRCh37/forward;strand-ambiguous | unknown-provisional | - | dbsnp:rs11887534 | 2026-11-23 | strand: G/C palindromic reference/effect pair (dbSNP NC_000002.11 2:44066247 G>A,C; alt C is the common alt), excluded per the palindromic rule (D-54-1); identity-only record (D-1), no GWAS rows were captured; report-safety: n/a; D-3: gnomAD v2.1.1 C frequency 0.013 (eas) to 0.098 (amr), spread 0.085, below the 0.20 threshold, not flagged | array presence not verified; palindromic site (reference/effect G/C), excluded by default | excluded | palindromic |

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
| rs10455872 | a64204762 | GCST011087 | 33115273 | Lipoprotein (a) levels | G | verified | dbsnp:rs10455872 | up | 6e-22136 | White British (UK) | 293274 (+replication) | uk-biobank | pmid:33115273 | - | no:p-malformed |
| rs10455872 | a19037 | GCST001218 | 21900290 | Lp (a) levels | G | verified | dbsnp:rs10455872 | up | 5e-39 | European, type 2 diabetes cohorts | 1450 | nhs-hpfs-diabetes | pmid:21900290 | - | yes |
| rs10455872 | a80642320 | GCST012232 | 33730874 | Lipoprotein (a) levels | A | verified | dbsnp:rs10455872 | down | 4e-19380 | European+African+Asian (UK) | 348591+ | unknown | pmid:33730874 | - | no:allele-mismatch |
| rs10455872 | a214359134 | GCST90453146 | 39972214 | LPA protein levels | ? | unverified | dbsnp:rs10455872 | up | 2e-120 | - | - | unknown | pmid:39972214 | - | no:trait-mismatch |
| rs3798220 | a87278698 | GCST90019513 | 33462484 | Lipoprotein (a) levels | C | verified | dbsnp:rs3798220 | up | 2e-456 | European+African+South Asian (UK) | 272573+ | uk-biobank | pmid:33462484 | - | no:p-malformed |
| rs6544713 | a47738071 | GCST008676 | 30926973 | LDL cholesterol levels | T | verified | dbsnp:rs6544713 | up | 3e-24 | multi-ancestry | up to 82522 European | unknown | pmid:30926973 | - | no:cohort-unknown |
| rs6544713 | a12280 | GCST000287 | 19060906 | LDL cholesterol | T | verified | dbsnp:rs6544713 | up | 2e-20 | European | 19840 | unknown | pmid:19060906 | - | no:cohort-unknown |
| rs6544713 | a47264660 | GCST008037 | 31217584 | Low density lipoprotein cholesterol levels | ? | unverified | dbsnp:rs6544713 | down | 2e-14 | non-European (PAGE) | - | page | pmid:31217584 | - | no:allele-mismatch |
| rs6544713 | a47266158 | GCST008045 | 31217584 | Total cholesterol levels | ? | unverified | dbsnp:rs6544713 | down | 1e-12 | non-European (PAGE) | - | page | pmid:31217584 | - | no:trait-mismatch |
| rs2282679 | a30522242 | GCST005782 | 29325163 | Serum 25-Hydroxyvitamin D levels | T | verified | dbsnp:rs2282679 | up | 4e-63 | African+Hispanic+European | 28150 | transcend | pmid:29325163 | a27438753 | yes |
| rs2282679 | a30522325 | GCST005782 | 29325163 | Serum 25-Hydroxyvitamin D levels | T | verified | dbsnp:rs2282679 | - | 4e-62 | African+Hispanic+European | 28150 | transcend | pmid:29325163 | a27438753 | no:direction-missing |
| rs2282679 | a30522310 | GCST005782 | 29325163 | Serum 25-Hydroxyvitamin D levels | T | verified | dbsnp:rs2282679 | up | 1e-6 | African+Hispanic+European | 28150 | transcend | pmid:29325163 | a27438753 | yes |
| rs2282679 | a27438753 | GCST005366 | 29343764 | Vitamin D levels (dietary vitamin D intake interaction) | T | verified | dbsnp:rs2282679 | - | 1e-187 | European | 39868+2113 | sunlight | pmid:29343764 | a30522242;a30522325;a30522310 | no:trait-mismatch |
| rs2282679 | a15179 | GCST000664 | 20418485 | Vitamin D levels | C | unverified | dbsnp:rs2282679 | down | 2e-49 | European | 4501+2221 | unknown | pmid:20418485 | - | no:allele-mismatch |
| rs2282679 | a90525434 | GCST90020244 | 34308111 | Vitamin D insufficiency | G | verified | dbsnp:rs2282679 | up | 1e-200 | European | 175977 | uk-biobank | pmid:34308111 | - | no:trait-mismatch |
| rs2282679 | a222905244 | GCST90837321 | 42509370 | 25-hydroxyvitamin D (D2+D3) in pregnancy | G | verified | dbsnp:rs2282679 | down | 3e-38 | Chinese (pregnancy) | 53285+25214 | unknown | pmid:42509370 | - | no:trait-mismatch |
| rs2282679 | a21734 | GCST001560 | 22673963 | Vitamin D levels | ? | unverified | dbsnp:rs2282679 | - | 2e-14 | European asthmatic children | 1416 | unknown | pmid:22673963 | - | no:allele-mismatch |
| rs2282679 | a15415 | GCST000697 | 20541252 | Vitamin D insufficiency | ? | unverified | dbsnp:rs2282679 | - | 2e-109 | European | 16125+17871 | unknown | pmid:20541252 | - | no:trait-mismatch |
| rs10741657 | a27362261 | GCST005367 | 29343764 | Vitamin D levels | A | verified | dbsnp:rs10741657 | up | 2e-46 | European discovery, European or unknown-ancestry replication | 79366+42757 | sunlight | pmid:29343764 | a30522333 | yes |
| rs10741657 | a27438761 | GCST005366 | 29343764 | Vitamin D levels (dietary vitamin D intake interaction) | A | verified | dbsnp:rs10741657 | - | 2e-38 | European | 39868+2113 | sunlight | pmid:29343764 | - | no:trait-mismatch |
| rs10741657 | a30522333 | GCST005782 | 29325163 | Serum 25-Hydroxyvitamin D levels | A | verified | dbsnp:rs10741657 | - | 2e-6 | African+Hispanic+European | 28150 | transcend | pmid:29325163 | a27362261;a27438761 | no:direction-missing |
| rs10741657 | a64666345 | GCST012014 | 33382404 | Serum 25-Hydroxyvitamin D levels | A | verified | dbsnp:rs10741657 | up | 3e-11 | Finnish | 3339 | finnish-health-2011 | pmid:33382404 | - | yes |
| rs10741657 | a15417 | GCST000697 | 20541252 | Vitamin D insufficiency | ? | unverified | dbsnp:rs10741657 | - | 3e-20 | European | 16125+17871 | unknown | pmid:20541252 | - | no:trait-mismatch |
| rs601338 | a228361273 | GCST90475776 | 39024449 | Other vitamin B12 deficiency anemia (PheCode 281.12) | G | verified | dbsnp:rs601338 | up | 5e-34 | multi-ancestry (US veterans) | 442192 | million-veteran-program | pmid:39024449 | - | no:trait-mismatch |
| rs6795970 | a47265313 | GCST008042 | 31217584 | PR interval | ? | unverified | dbsnp:rs6795970 | down | 1e-46 | non-European (PAGE) | - | page | pmid:31217584 | - | no:trait-mismatch |
| rs6795970 | a14399 | GCST000561 | 20062063 | Electrocardiographic traits | A | verified | dbsnp:rs6795970 | up | 1e-58 | European (Iceland) | 12670+10352 | unknown | pmid:20062063 | - | no:trait-mismatch |
| rs6795970 | a14396 | GCST000564 | 20062061 | Electrocardiographic traits | A | verified | dbsnp:rs6795970 | up | 3e-15 | Indian Asian + European | 6543+11613 | unknown | pmid:20062061 | - | no:trait-mismatch |
| rs174537 | a94377554 | GCST90060580 | 34503513 | Fatty acid(20:4)_[M-H]1- levels | C | unverified | dbsnp:rs174537 | down | 3e-20 | Pakistani (South Asian) | 5662 | promis | pmid:34503513 | - | no:trait-mismatch |
| rs174537 | a118833149 | GCST90277304 | 37907536 | Phosphatidylcholine (18:0_20:4) levels | T | verified | dbsnp:rs174537 | down | 1e-386 | Finnish | 7174 | unknown | pmid:37907536 | - | no:trait-mismatch |
| rs1801133 | a134087602 | GCST90429184 | 38626723 | Homocysteine levels | A | verified | dbsnp:rs1801133 | up | 2e-21 | Korean | 1804 | korea4k | pmid:38626723 | - | yes |
| rs1801133 | a129422187 | GCST90319530 | 37479695 | Homocysteine levels | A | verified | dbsnp:rs1801133 | up | 6e-69 | Han Chinese ischemic stroke patients | 9947+294 | stromics | pmid:37479695 | - | yes |
| rs1801133 | a34417 | GCST002087 | 23824729 | Homocysteine levels | A | verified | dbsnp:rs1801133 | up | 4e-104 | European | 44147 | unknown | pmid:23824729 | - | no:cohort-unknown |
| rs1801133 | a14036 | GCST000367 | 20031578 | Homocysteine levels | A | verified | dbsnp:rs1801133 | up | 8e-35 | European (white women) | 13974+840 | wghs | pmid:20031578 | - | yes |
| rs1801133 | a93405495 | GCST90090974 | 34707639 | Homocysteine levels | T | unverified | dbsnp:rs1801133 | up | 1e-120 | Han Chinese | 5175+688 | unknown | pmid:34707639 | - | no:allele-mismatch |
| rs1801133 | a49910257 | GCST009171 | 23696881 | Homocysteine levels | ? | unverified | dbsnp:rs1801133 | - | 2e-11 | European (Italy) | 1208 | inchianti | pmid:23696881 | - | no:allele-mismatch |
| rs1801133 | a35667363 | GCST007578 | 30339177 | Plasma homocysteine levels | ? | unverified | dbsnp:rs1801133 | up | 1e-19 | Irish | 2232 | unknown | pmid:30339177 | - | no:allele-mismatch |

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
| rs10455872 | - | dbsnp:rs10455872;gwas:GCST011087;pmid:33115273;gwas:GCST001218;pmid:21900290;gwas:GCST012232;pmid:33730874;gwas:GCST90453146;pmid:39972214 |
| rs3798220 | - | dbsnp:rs3798220;gwas:GCST90019513;pmid:33462484 |
| rs6544713 | - | dbsnp:rs6544713;gwas:GCST008676;pmid:30926973;gwas:GCST000287;pmid:19060906;gwas:GCST008037;pmid:31217584;gwas:GCST008045 |
| rs2282679 | - | dbsnp:rs2282679;gwas:GCST005782;pmid:29325163;gwas:GCST005366;pmid:29343764;gwas:GCST000664;pmid:20418485;gwas:GCST90020244;pmid:34308111;gwas:GCST90837321;pmid:42509370;gwas:GCST001560;pmid:22673963;gwas:GCST000697;pmid:20541252 |
| rs10741657 | - | dbsnp:rs10741657;gwas:GCST005367;pmid:29343764;gwas:GCST005366;gwas:GCST005782;pmid:29325163;gwas:GCST012014;pmid:33382404;gwas:GCST000697;pmid:20541252 |
| rs601338 | - | dbsnp:rs601338;gwas:GCST90475776;pmid:39024449 |
| rs6795970 | - | dbsnp:rs6795970;gwas:GCST008042;pmid:31217584;gwas:GCST000561;pmid:20062063;gwas:GCST000564;pmid:20062061 |
| rs174537 | - | dbsnp:rs174537;gwas:GCST90060580;pmid:34503513;gwas:GCST90277304;pmid:37907536 |
| rs1801133 | - | dbsnp:rs1801133;gwas:GCST90429184;pmid:38626723;gwas:GCST90319530;pmid:37479695;gwas:GCST002087;pmid:23824729;gwas:GCST000367;pmid:20031578;gwas:GCST90090974;pmid:34707639;gwas:GCST009171;pmid:23696881;gwas:GCST007578;pmid:30339177 |
| rs11887534 | - | dbsnp:rs11887534 |

The `pack file index id` cell holds the typed ids that identify the pack files
for the rsID; together they form the set of evidence ids the replication check
accepts.

## Reserves and goals

Two to three reserves per group are fully sourced rows with decision `reserve`.
They satisfy every inclusion criterion and are never in the targets file, so a
poor coverage outcome can be answered by swapping reserves in without learning
which markers were missing.

Reserves recorded for v0.2.0:

- Health group: none. Every health-candidate row in the pool is either included or excluded above; no further row reaches every inclusion criterion.
- Trait group: none. No pool trait row has replicated, orientation-verified evidence under the curated label, so none is a fully sourced reserve.

For v0.3.0 no `reserve` row remains: rs10741657 (CYP2R1, trait group) was a staged inclusion (owner decision T-1) and is now `included` with its targets entry. The CYP2R1 build input is derived from eligible main-effect rows only, so no intake-interaction or other-trait accession (such as GCST005366) is in the build input, and a test covers the one-publication case; the `vitamin d levels` alias stays (owner decision on review finding R141-F2).

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

For the v0.1.0 curation the pool was the 23 DRAFT rsIDs of `data/targets.carrier.json` and `data/targets.traits.json`; no marker was added. The health rows keep carrier or association wording only, and no entry states a diagnosis or an absolute risk. Effect alleles were re-derived from the complete dbSNP GRCh37 allele set in N0d; the curated condition is attributed through a per-condition ClinVar record (RCV) whose condition names the curated label by the alias-file semantics, and that record's significance and stars are used, never the VCV aggregate (D-54-3); the strict other-condition outcome applies when no RCV names it. The alias file was extended with three reviewed synonyms and two aliases that named a different, bleeding disorder were removed (D-54-2). Palindromic reference/effect pairs (A/T or C/G) are excluded by default with reason code `palindromic` (D-54-1). In the v0.1.0 curation every trait row was excluded: each pigmentation trait is ancestry-informative, and no other trait has a replicated, orientation-verified association under the curated label. For v0.2.0 the pool grew by eleven candidates to 34 T1 rows, of which five were included and six excluded. Included as `carrier_status` (category `carrier`): rs1799807 (BCHE), rs121908529 (AGXT), rs185803104 (HOGA1) and rs180177314 (GRHPR). Included as `trait` (category `trait`): rs11591147 (PCSK9); the inclusion rests on the Replication rule rows in T4 (three independent groups), and the marker is judged not ancestry-informative under criterion 8. Excluded with reason code `inheritance-unresolved`: rs61752717, rs28940579, rs28940578, rs104895097, rs28940580 and rs104895085 (MEFV). No reserves exist for v0.2.0 either: none of its rows is a `reserve`. For v0.3.0 the pool grew by ten candidates to 44 T1 rows, of which one was included, none is a reserve and nine were excluded. Included as `trait` (category `trait`): rs10741657 (CYP2R1), by owner decision T-1; the inclusion rests on the Replication rule rows in T4 (two independent groups), and the marker is judged not ancestry-informative under criterion 8 (spread 0.162, below the 0.20 threshold). Excluded with reason code `single-study`: rs10455872 (LPA) and rs2282679 (GC). Excluded with reason code `no-independent-confirmation`: rs3798220 (LPA), rs601338 (FUT2), rs6795970 (SCN10A) and rs174537 (MYRF). Excluded with reason code `evidence-not-in-pack`: rs6544713 (ABCG8). Excluded with reason code `ancestry-informative`: rs1801133 (MTHFR). Excluded with reason code `palindromic`: rs11887534 (ABCG8). Whether the resulting panel is adequate is the owner's aggregate coverage judgment (counts only).

## Provenance block

Facts for the whole panel, recorded once for each evidence pack.

- Evidence pack ids: N0a (netpack-N0-review), N0b (netpack-N0b-review), N0c (netpack-N0c-review), N0d (netpack-N0d-review)
- Pack manifest sha256: N0a 0f14e7ae0e18b3ccbaf8914c951033aa4d2742a0e394b5e2857ee99fed15e908; N0b 13e94d7a39f38b148e821cc4ed692bb4b75fcb90f5445ffe05d37f63d34069dd; N0c bc47ad43c6a2ad1b3622df65a17a93a0335455485fe951d8e3d75a88148c4b48; N0d 2a69bcfbbabb2b10da5882f2c914ca62528352783e1f7aaf6b6dcad75b1dbb77
- Retrieval dates (UTC, ISO): 2026-11-09; v0.2.0 pack 2026-11-14; v0.3.0 pack 2026-11-23
- v0.2.0 evidence pack: evidence/v0.2.0 (outside the repository), frozen manifest MANIFEST.sha256 sha256 0966f825ba9dcb7a9eb01761bd1f77c731ceca70a05dbb9d1ca47425ff04c4f0 (62 entries); captured 2026-11-14 (UTC); used for the five v0.2.0 candidates
- v0.3.0 evidence pack: evidence/v0.3.0 (outside the repository), frozen manifest MANIFEST.sha256 sha256 a67ffeea8f69210b9e79816a5e4b357f052a62a7b82e563e88825725dd704882 (121 entries); captured 2026-11-23T02:52:26Z to 2026-11-23T03:21:33Z (UTC; frozen 2026-11-22 at the owner's -05:00 offset); dbSNP variation-API records, GWAS Catalog REST v2 association pages and study records, gnomAD v2.1.1 GraphQL answers and one PubMed abstract batch; the GWAS Catalog release was not recorded; no public array manifest was found; used for the ten v0.3.0 rows
- v0.3.0 supplement: evidence/v0.3.0-supp1 (outside the repository), MANIFEST.sha256 sha256 945768a5ffa75ea9906c895eff18d7125d0bf46bbcb409d8fccd913270719567 (2 entries): gnomAD v2.1.1 answers for 11-14914878-A-G (sha256 207e51d597bd10f6054b70fe6b00c0bbf5ed85630dec04782afdf7eafac4fb25) and 11-14914878-A-C (sha256 4fb38a733d7e6f1b61444803ec5f9a8266004115c963e1b80aacb4cd8df77e2e, "Variant not found"), used for the rs10741657 ancestry screen
- v0.3.0 pack defect: the derived file placements.tsv gives rs10741657 on an alternate scaffold, and gnomad-variant-ids.tsv follows it; the T1 row uses the raw dbSNP record (NC_000011.9) and takes no value from either derived file; the pack is not edited
- v0.3.0 panel rebuild (S2): the ninth entry rs10741657 was added to the release panel from the packs above, with the eight v0.2.0 entries unchanged; the build inputs, cache assembly, capture times and pack digests are recorded under "Release panel build"
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

The v0.1.0 build had three entries (pack N1). The v0.2.0 build had eight: the
three v0.1.0 entries (rs1800562, rs1799963, rs6025) reuse the N1 cache rows
unchanged, and the five new entries (rs1799807, rs121908529, rs185803104,
rs180177314, rs11591147) take their data from the v0.2.0 evidence pack. The
three v0.1.0 entries are identical to the v0.1.0 panel. The v0.3.0 build has
nine entries: the eight v0.2.0 entries, unchanged and in their order, and
rs10741657 (CYP2R1), appended as the ninth entry from the v0.3.0 packs.

- Evidence packs: N1 (public-reference request list approved 2026-11-11; the pack stays outside the repository) for the three v0.1.0 entries; the v0.2.0 evidence pack (`evidence/v0.2.0`, outside the repository) for the five v0.2.0 entries; the v0.3.0 evidence pack (`evidence/v0.3.0`) and its supplement (`evidence/v0.3.0-supp1`), both outside the repository, for rs10741657
- Pack manifest sha256: N1 63a702401febcb722ef9795e0a27ab2dc26ad3aaedf04c3e9f9dba721865cab0; v0.2.0 0966f825ba9dcb7a9eb01761bd1f77c731ceca70a05dbb9d1ca47425ff04c4f0; v0.3.0 a67ffeea8f69210b9e79816a5e4b357f052a62a7b82e563e88825725dd704882 (121 of 121 entries verified before the build); v0.3.0 supplement 945768a5ffa75ea9906c895eff18d7125d0bf46bbcb409d8fccd913270719567 (2 of 2 entries verified)
- Capture time (UTC, ISO): N1 2026-11-11T19:57:14Z; v0.2.0 dbSNP records 2026-11-14T04:43:29Z, GWAS Catalog associations 2026-11-14T04:50:49Z, ClinVar variant_summary 2026-11-14T00:30:32Z, gnomAD and Open Targets answers 2026-11-14T14:16:36Z to 2026-11-14T14:16:47Z (from file times, converted with the owner's -06:00 offset; the owner confirms); v0.3.0 pack 2026-11-23T02:52:26Z to 2026-11-23T03:21:33Z; v0.3.0 supplement gnomAD answers 2026-11-23T19:21:46Z (11-14914878-A-C) and 2026-11-23T19:22:03Z (11-14914878-A-G), from file times at the owner's -06:00 offset (the supplement has no capture log). The build `--retrieved-at` is the latest capture time among the inputs, the supplement file time of the A-G answer, 2026-11-23T19:22:03Z.
- Built from commit 8a6dc1bbb3743e04d7d1b4a8cdd8a9077240749e (tools and alias file unchanged) with the data edits of this change: the ninth targets entry and `panel_version` 0.3.0 in the three data files
- Sources for the five v0.2.0 entries: dbSNP placements parsed from the pack's variation-API records with the repo's own parser (`fetch_dbsnp_small`); ClinVar from the pack's `variant_summary.txt.gz` (carrier entries use the curated evidence file instead); gnomAD allele frequency of the effect allele, genome frequency else exome frequency, from the captured answers (rs180177314 has an exome frequency only); Open Targets GWAS rows for the four carriers exactly as captured (rs1799807 8 rows, rs185803104 2 rows, rs121908529 and rs180177314 returned none and are recorded as absent); for rs11591147, rows from the pack's GWAS Catalog REST associations, one row per accession and reported trait (741 rows), because the captured Open Targets answer (25 rows) matches no LDL-level trait
- Sources for rs10741657 (ninth entry): dbSNP placement parsed with the repo's own parser (`fetch_dbsnp_small`) from the raw dbSNP record in the v0.3.0 pack (NC_000011.9 11:14914878, reference A, alternates C and G; the derived placements.tsv row is not used); no ClinVar record is used (the entry is a trait entry with no curated evidence entry, and `data/targets.release-evidence.json` takes no entry for it, only the version); gnomAD genome frequency 0.6375207349751181 of the `11-14914878-A-G` answer in the v0.3.0 supplement, stored as `gnomad_af` (this is the frequency of G; the A>C allele is not found in gnomAD and no value is invented for it, so the annotator derives the frequency of the effect allele A as one minus that value, 0.3625 (19985 of 31348 alleles are G; the other 11363 are counted as A), which assumes that the C allele is absent from gnomAD); GWAS rows from the eligible main-effect T4 rows only (`counted` is `yes`): GCST005367 "Vitamin D levels" and GCST012014 "Serum 25-Hydroxyvitamin D levels". The intake-interaction accession GCST005366 (same publication as GCST005367), GCST005782 (no direction) and GCST000697 (insufficiency) are not in the build input (owner decision on review finding R141-F2)
- Cache assembly (offline, no network): dbSNP, gnomAD and GWAS rows of the three v0.1.0 entries are copied from the N1 cache without change; the rows of the five v0.2.0 entries are copied from the v0.2.0 cache without change (dbSNP rows compared, gnomAD and GWAS lines unchanged, `variant_summary.txt.gz` read from the v0.2.0 pack); the rs10741657 rows are appended as described above
- Source labels in the panel name every capture date: dbSNP "variation-api-2026-11-11 (3 entries), 2026-11-14 (5 entries) and 2026-11-23 (1 entry)"; ClinVar "variant_summary-2026-11-14"; gnomAD "graphql-2026-11-11 (3 entries), 2026-11-14 (5 entries) and 2026-11-23 (1 entry)"; GWAS Catalog "opentargets-2026-11-11 (3 entries); opentargets-2026-11-14 (4 carriers); gwas-catalog-rest-2026-11-14 (rs11591147); gwas-catalog-rest-2026-11-23 (rs10741657)"
- Build command (run from that export, no network; `<CACHE>` is the assembled cache directory):

```
python3.12 -B tools/build_panel.py --targets data/targets.release.json \
  --curated-evidence data/targets.release-evidence.json --cache <CACHE> \
  --retrieved-at 2026-11-23T19:22:03Z \
  --dbsnp-release "variation-api-2026-11-11 (3 entries), 2026-11-14 (5 entries) and 2026-11-23 (1 entry)" \
  --clinvar-release "variant_summary-2026-11-14" \
  --gnomad-release "graphql-2026-11-11 (3 entries), 2026-11-14 (5 entries) and 2026-11-23 (1 entry)" \
  --gwas-release "opentargets-2026-11-11 (3 entries); opentargets-2026-11-14 (4 carriers); gwas-catalog-rest-2026-11-14 (rs11591147); gwas-catalog-rest-2026-11-23 (rs10741657)" \
  -o data/targets.release-panel.json
```

- Determinism: two builds from the same cache were byte-identical (`cmp`), and the first eight entries equal the v0.2.0 entries field for field. The test suite rebuilds the panel twice from a cache reconstructed from in-repository data (the panel's coordinates and frequencies and the main-effect T4 rows) and requires both builds to equal the committed file.
- Panel file sha256: 379f050163dc37430b6e493b20749958a058c8df48124606951f6b10a0bcaa0e
