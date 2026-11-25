# Disease-association evidence and reporting contract

Status: approved contract for the v0.4.0 run (stage S1). It defines when a
published genome-wide association with a named disease may become a finding of
the new kind `disease_association`, how the evidence is recorded in
[panel-curation.md](panel-curation.md), and what the deterministic report may
and may not say about it. No marker is curated by this document; stage S2
records the curation, and stage S3 adds the production support (schema,
annotator, template, validator) only if at least one marker is included.

Every clause has a stable id (C-1 to C-54). A clause corrected by the
independent specification review of round r158 carries the marker
"(amended: R158-F<n>)" with the finding number. Each clause ends with an
**Enforcement** tag:

- **EXISTING**: a checker or test already enforces it (named);
- **NEW-CHECK**: an offline checker or test enforces it; the stage that adds it
  is named when it is not S1;
- **CODE**: a production change is needed (named file; stage S3);
- **CURATOR**: a judgment no checker derives; the T1 `rationale` states the
  basis and the review reassesses it;
- **REVIEW**: a review-time check.

The S1 checkers live in `tests/test_release_panel.py` (curation rules, on
invented fixtures) and `tests/test_docs_release.py` (this document's ids,
markers, pattern list, frames and state caveats).

## Owner decisions

The owner accepted every answer proposed in the S1 plan (2026-11-24). They are binding for
this contract; each clause that depends on one names it.

| id | decision | chosen answer |
|---|---|---|
| O-1 | shape of the new finding kind | a new pair (`disease`, `disease_association`); `risk_association` is not reused |
| O-2 | schema version | 1.3.0 for a findings document that carries a disease_association finding; every other document stays 1.2.0 |
| O-3 | stage order | S1 contract and checkers, S2 curation, owner triage, S3 production support (only if a marker is included), S4 rebuild and verification; the all-excluded branch skips S3 |
| O-4 | odds ratios in the report | not printed; recorded in curation only |
| O-5 | frequency screen | the v0.3.0 D-3 screen: record the spread, flag at 0.20, a flagged row is excluded unless the owner includes it with a decision id; the ancestry caveat is mandatory either way |
| O-6 | evidence bar | two independent groups, each with an association row at p at or below 5e-8 |
| O-7 | S2 survey | a survey precedes the S2 build |
| O-8 | all-excluded version policy | the release policy applies (panel_version 0.4.0 and package 0.4.0 at verification) even when the panel entries are unchanged; the owner decides whether to release |
| O-9 | `gnomad:` typed id | added |
| O-10 | model narration of disease claims | not allowed in this release; the claims are code-owned |
| O-11 | rare caveat at `low_frequency` | no; only `rare` and `ultra_rare`, as for ClinVar findings |
| O-12 | new reason codes | `proxy-only` and `ancestry-unrecorded` are added; `label-mismatch` is reused |
| O-13 | "protect" in report text | banned; the report says "lower odds" |
| O-14 | capture extras | GWAS rows for rs11887534 and the context rsIDs are captured after the owner confirms each; no ClinVar capture unless the owner asks |
| O-15 | study-record cap for coronary artery disease | the cap of 60 is a stop line; the decision is taken at capture with the printed counts; the full file is not used |

Facts this contract rests on (verified at the v0.3.0 base): the allowed
(category, result_type) pairs are (trait, trait), (carrier, carrier_status) and
(carrier, risk_association); the findings schema enumerates three result types
and schema versions 1.0.0, 1.1.0 and 1.2.0; the deterministic template renders
only the result types listed in `RESULT_TYPE_SECTIONS`; the build counts GWAS
studies by word-boundary containment (AL-035) while the T4 replication rule
uses equality.

## A. Scope

**C-1 Definition.** A *disease association* finding reports that one allele of
one named public variant (rsID, GRCh37, forward strand) is associated, in
published genome-wide association studies, with higher or lower odds of one
named disease, as a population-level statistical association. It is not a
diagnosis, a personal risk, a carrier status or a measurement. Enforcement:
CURATOR + REVIEW; the wording is pinned by C-37 to C-47.

**C-2 Relation to the existing result types.** Disease associations differ from
`carrier_status` and `risk_association` (both ClinVar-based, with an
inheritance model and the ClinVar pair rule) and from `trait` (a non-medical
phenotype). Their evidence is GWAS Catalog association rows for a disease
phenotype, evaluated by the Replication rule with the extra gates below;
ClinVar is context only (C-30). (owner decision O-1) Enforcement: CURATOR.

**C-3 New pair.** One new allowed pair: `category` = `disease`,
`result_type` = `disease_association` (owner decision O-1). Reusing
`risk_association` would send a GWAS-only finding through the ClinVar-pair and
inheritance checkers and into the section that holds the ClinVar
thrombophilia findings; a new category with the old result type would need a
second field to tell the two apart. The new pair is one row in the pair tables
of the build, the checkers, the template section map and the schema enum, and
the existing rule that no section mixes result types then separates the two
kinds. Until stage S3 the pair is accepted in curation table T1 only; the
targets file and the build still reject it. Enforcement: NEW-CHECK (S1: the
T1 pair checker accepts the pair and the targets-entry checker still rejects
it; every other pair stays rejected), CODE (tools/build_panel.py,
tools/evidence.py, stage3/run.py, schema/findings.schema.json).

**C-4 Smallest schema and template extension.** The findings document gains,
only for `result_type` = `disease_association`: (1) the `result_type` enum
value `disease_association`; (2) `association_direction`, enum
`susceptibility` | `protective`, required for a disease_association finding
and absent otherwise, the curated direction of the effect allele (C-13), never
derived from the user's genotype; (3) `evidence.ancestry_scope`, an array of
codes from the closed vocabulary of C-24 with at least one item, required for
a disease_association finding and absent otherwise. No effect-size field is
added (C-20). The report IR schema is unchanged (`ir_version` 1.0.0). The
caveat registry gains one id, `disease_ancestry` (C-27). Enforcement: CODE
(schema, stage2/annotate.py, stage3/run.py, tools/caveats.py,
tools/validate_report.py, tools/render_report.py), NEW-CHECK (S3).

**C-5 Schema version.** (amended: R158-F8) A findings document that carries a
disease_association finding has `schema_version` 1.3.0, and the schema enum
lists 1.3.0; a document without one keeps emitting 1.2.0, so the shipped
v0.3.0 behavior and its pins are unchanged (owner decision O-2). Version 1.3.0
keeps every condition of 1.2.0: the conditional requirement of
`provenance.input_build` and `provenance.build_basis` names 1.1.0, 1.2.0 and
1.3.0. Required tests (S3): the schema accepts a 1.3.0 document with the new
fields; rejects a disease_association finding without `association_direction`
or `evidence.ancestry_scope`; rejects `association_direction` on any other
result type; and rejects a 1.3.0 disease document that lacks
`provenance.input_build` or `provenance.build_basis`. Enforcement: CODE,
NEW-CHECK (S3).

**C-6 Deterministic template only.** (amended: R158-F1) Disease_association
claims are produced only by the fixed templates of C-29 and C-37, in every
narration mode (owner decision O-10). A disease finding, its call state, its
genotype and its claims are never sent to a model, in skeleton mode, in full
mode, through the local endpoint or through the online endpoint: the model
payload is built from the findings with every disease_association finding
removed, and after narration the code-owned disease section and claims are
restored verbatim. A model-returned claim that cites a disease finding is
rejected and replaced by the template text. When the remaining findings leave
nothing to narrate, no model is called. Required tests (S3, in
`tests/test_interpretation.py`):
`DA.skeleton_payload_has_no_disease_finding`,
`DA.full_payload_has_no_disease_finding`,
`DA.local_route_restores_code_owned_disease_claims`,
`DA.online_payload_has_no_disease_finding_or_state`,
`DA.model_claim_citing_disease_finding_rejected`. Each inspects the exact
payload handed to the model client and the returned report. Enforcement:
CODE (stage3/run.py `build_skeleton`, `skeleton_prompt`, `run_full`;
tools/prompt.py `build_messages`), NEW-CHECK (S3).

## B. Evidence gates beyond panel-curation.md

Every gate applies in addition to criteria 1 to 10 of
[panel-curation.md](panel-curation.md). Criteria 11 and 12 (ClinVar pair,
inheritance model) are replaced for disease entries by C-30 to C-32. A row
that fails a gate is excluded with the stated reason code. The exact cell
grammars and tokens are in the section "Disease associations" of
panel-curation.md.

**C-7 Exact phenotype match (no proxies).** (amended: R158-F7) A GWAS row counts
only when its reported trait equals the curated label or an alias-file member
after the normalizer (equality of normalized strings, never containment). An
EFO mapped trait never counts by itself. These never match unless an
owner-approved alias names them: a related disease, a subtype, a composite
("X or Y"), a symptom, a biomarker or measurement used as a proxy for the
disease (for example a lipid level for gallstone disease), a procedure, a
complication, an age-of-onset or severity phenotype, or a different disease
sharing a word. The v0.3.0 rs6544713 LDL evidence is a different phenotype
from gallstone disease and counts for nothing here. A row under the candidate's
own rsID whose reported phenotype is not the label or an approved synonym is
dropped `trait-mismatch`; when the candidate's own rsID has rows and every one
is dropped `trait-mismatch`, the entry is excluded `label-mismatch`. Evidence
at a linked rsID is C-12's case, never `label-mismatch`. Enforcement: EXISTING
(`trait-mismatch`, `check_trait_table`), NEW-CHECK (S1: equality for disease
rows, a composite row is not counted; `label-mismatch` needs rows under the
candidate rsID, all mismatched), CODE (C-8).

**C-8 Build counting uses equality for disease entries.** For `category` =
`disease` the build counts distinct study ids by equality of the normalized
reported trait with the label or an alias, not by the containment of AL-035,
and a test pins that the build's count equals the T4 recomputation; otherwise a
composite study could raise the tier above what T4 shows. Enforcement: CODE
(tools/evidence.py, tools/build_panel.py), NEW-CHECK (S3).

**C-9 Alias review for disease labels.** An alias for a disease label is a
synonym of the same disease (a spelling variant or the alternate registry
name), never a broader, narrower or related phenotype. Each alias used by a
counted row is justified in the T1 `rationale` cell as
`alias-review:<alias>=<one-line sameness reason>`. A new alias group changes
`data/condition_aliases.json`, whose hash is pinned in
`tests/test_release_panel.py` (`PINNED_HASHES`); the pin is re-set in the same
change with the reason recorded. Enforcement: NEW-CHECK (S1: every alias used
by a counted disease row has an `alias-review:` token), CURATOR, REVIEW.

**C-10 Effect allele and orientation.** The T1 effect allele is a forward-strand
GRCh37 letter taken from the captured dbSNP record; the strand is stated. The
effect allele is the allele the counted rows report (C-17): the curator never
inverts an odds ratio to turn a protective allele into a risk allele or the
reverse. Orientation is `verified` for a row only when the site is
non-palindromic, the row's allele letter is one of the two dbSNP forward
alleles, no counted row reports the complement letter, and the orientation
source is the typed id `dbsnp:rs<digits>`. Enforcement: EXISTING
(`allele-mismatch`, `orientation-unverified`, palindromic exclusion,
`check_effect_alleles`, `check_strand`), CURATOR (the strand statement).

**C-11 Frequency cross-check (recorded, not decisive).** For each counted row
that reports `risk_frequency`, the curator records in the T1 rationale whether
that frequency is consistent with the gnomAD v2.1.1 frequency of the same
letter in the matching continental group, or closer to the complement (a sign
of an unreported strand flip). A row whose frequency is closer to the
complement letter is not counted (orientation unverified). Enforcement:
CURATOR + REVIEW.

**C-12 LD proxies never substitute.** (amended: R158-F7) Evidence reported for a
different rsID in linkage disequilibrium with the candidate never counts for
the candidate, whatever the r-squared. A candidate with no T4 row under its own
rsID is excluded `proxy-only` when rows for linked rsIDs exist in the pack, and
`no-independent-confirmation` otherwise. A candidate that has rows under its own
rsID is never `proxy-only`: if all of them are phenotype mismatches it is
`label-mismatch` (C-7). Evidence recorded for the excluded palindromic ABCG8
rs11887534 cannot be borrowed for rs4245791, and the reverse. (owner decision
O-12) Enforcement: NEW-CHECK (S1: `proxy-only` and `label-mismatch` are
mutually exclusive by the rows under the candidate rsID), CURATOR.

**C-13 Direction and its vocabulary.** The T4 `direction` of a disease row is
`up` when the reported effect allele goes with higher odds of the disease (odds
ratio above one) and `down` when it goes with lower odds (odds ratio below
one). A row without an odds ratio or a usable direction is dropped
`direction-missing`. The entry's `association_direction` is `susceptibility`
when every counted direction is `up` and `protective` when every counted
direction is `down`; mixed directions are `conflicting-evidence` and the entry
is excluded. A row that reports a beta is a quantitative trait, a different
phenotype, and is dropped `trait-mismatch`. Enforcement: EXISTING (direction
rules, conflict status), NEW-CHECK (S1: the T1 `direction/meaning` cell follows
C-14 and its word equals the one derived from T4).

**C-14 T1 `direction/meaning` grammar for a disease row.** An included or
reserve disease row carries exactly one of

`susceptibility: each copy of the <X> allele is associated with higher odds of <label> in studies; association wording only`

`protective: each copy of the <X> allele is associated with lower odds of <label> in studies; association wording only`

where `<X>` is the T1 effect allele and `<label>` the T1 label, exactly (case
sensitive); an excluded row carries `not applicable`. Enforcement: NEW-CHECK
(S1).

**C-15 Minimum independent evidence groups and what counts as independent.**
(amended: R158-F3) An entry needs at least two independent groups, each with an
eligible association row at p at or below 5e-8, all counted directions equal,
and no functional-only evidence: functional evidence never counts toward a
disease association (owner decision O-6). Independent groups are derived by the
existing cluster rule (same PMID, same cohort id, or a declared overlap). In
addition, for disease rows:

1. rows of one consortium lineage are one cohort: the cohort id is the lineage
   id, so a later paper that re-analyzes earlier samples cannot make a second
   group;
2. a meta-analysis and any of its component cohorts overlap, declared in
   `overlap with` in both directions;
3. meta-analyses whose components are not listed in the captured source are not
   independent of each other: by default every meta-analysis row is clustered
   with every other meta-analysis row and with every consortium or biobank row.
   Only an `independence:` token whose typed sources are in the evidence pack
   and establish non-overlap separates such a pair; group names alone never do;
4. a discovery stage and the replication stage of the same publication are one
   group (same PMID, already derived);
5. every biobank-derived row is in the cohort of that biobank;
6. an unknown cohort never counts (existing `cohort-unknown`).

The curator records, for every pair of counted groups of an included or reserve
entry, `independence:<cohort-a>|<cohort-b>=<typed id>[,<typed id>...] (<basis>)`
in the T1 rationale; each typed id cites the pack record that establishes the
disjointness. Status `not-significant` (two or more groups but fewer than two
with a significant row) maps to `no-independent-confirmation`. Enforcement:
EXISTING (cluster derivation), NEW-CHECK (S1: the second significant group, the
meta-analysis default, the token's presence and its typed sources), CURATOR +
REVIEW (lineage ids, overlap, the basis of disjointness).

**C-16 Significance.** The threshold stays 5e-8 inclusive; `p-missing` and
`p-malformed` (including AL-048, a value that underflows to zero) stand.
Enforcement: EXISTING.

**C-17 Where the effect allele comes from.** The curated effect allele is the
allele reported by the counted rows; rows that report the other allele are
`no:allele-mismatch` and are never re-expressed. Enforcement: EXISTING.

**C-18 Replication status and exclusion codes.** The Replication vocabulary
stands: `single-study` for one group, `no-independent-confirmation` for two or
more groups that fail C-15's second significant group, `conflicting-evidence`
for mixed directions, `evidence-not-in-pack` when rows were dropped for
unverified orientation, unknown cohort or missing pack evidence,
`ancestry-unrecorded` (C-25), and `label-mismatch` (C-7). Enforcement: EXISTING
+ NEW-CHECK (S1).

**C-19 Publication detail missing from the pack is never filled from memory.**
Every sample size, ancestry and cohort statement cites the pack record it came
from. Enforcement: EXISTING (`evidence-not-in-pack`), REVIEW.

**C-20 Effect-size recording.** Odds ratio and interval are captured, never
computed: for the strongest counted row (lowest p) of each counted group the
curator records `or:<row id>=<value> (<low>-<high>)` in the T1 rationale, as
published, per copy of the effect allele. A ratio on the wrong side of one for
the row's direction is an error, and the value lies within its interval. A row
that reports a per-genotype or recessive-model ratio is recorded but not
counted. The report prints no odds ratio and no interval (owner decision O-4);
if the owner later wants them, the sentence is fixed: `In the cited study the
odds ratio per copy was <value> (<low> to <high>); this is a relative measure
from a study population and not an estimate of your own risk.` Enforcement:
NEW-CHECK (S1: an `or:` token per counted group, side and interval), CURATOR.

**C-21 No absolute, lifetime or conditional risk.** Absolute risk, lifetime
risk, penetrance, relative risk against an unstated baseline, number needed to
screen and any combination with other markers are outside this contract
(C-54). Enforcement: REVIEW + the forbidden-pattern scan (C-43).

## C. Population and cohort limits

**C-22 Record the stage, ancestry and size of every counted row.** (amended: R158-F5) Each T4 disease row is tied to the study stage that produced its
association: `discovery`, `replication`, or `combined` (an association reported
for the joint analysis of both stages). The `sample ancestry` cell is
`<stage>:<code>[+<code>...]` with codes from C-24, and the `sample size` cell is
`<stage>:<cases>/<controls>` when the record gives both, else
`<stage>:n=<total>`; the stage is the same in both cells. Ancestry and size come
from that stage's fields of the study record in the frozen pack
(`discovery_ancestry` and `initial_sample_size` for discovery;
`replication_ancestry` and `replication_sample_size` for replication; both for
combined). Replication-stage ancestry is never merged into a discovery row's
cell: it is evidence only through a captured association row of that
replication stage. A row whose ancestry or size for its stage is not in the
pack (`-` in either cell) is not counted and is dropped `ancestry-unrecorded`.
Enforcement: NEW-CHECK (S1: grammar, stage equality across the two cells, the
drop), CURATOR (the stage of each row).

**C-23 Ancestry scope.** (amended: R158-F5) The ancestry scope of an entry is the
set of codes of the counted association rows at p at or below 5e-8, each taken
from that row's own stage cell (C-22). It is recorded in the T1 `limitations`
cell as `ancestry-scope:<code>[,<code>...]` in the order of C-24 and copied to
the finding as `evidence.ancestry_scope`. Enforcement: NEW-CHECK (S1: the token
equals the derived set; codes from the vocabulary).

**C-24 Closed ancestry vocabulary.** `european`, `east-asian`, `south-asian`,
`african`, `hispanic-latino`, `middle-eastern`, `oceanian`, `mixed`, `other`.
A study ancestry text that does not map is `other` and its text is recorded in
the rationale. The vocabulary describes study samples; the report never states
or infers the user's ancestry. Enforcement: NEW-CHECK (S1), CURATOR.

**C-25 When a finding is caveated, and when it is withheld.**
1. One ancestry in the scope: included with the ancestry caveat (C-27).
2. Two or more ancestries with equal direction: included; the claim names the
   scope (C-39).
3. Counted rows disagree in direction: excluded `conflicting-evidence`.
4. A row whose ancestry or size is not recorded is not counted; if fewer than
   the required groups remain because of such rows, the entry is excluded
   `ancestry-unrecorded` (owner decision O-12).
5. The allele-frequency screen flags the entry (C-26): excluded unless the
   owner includes it with a decision id cited in `limitations`; the caveat of
   C-27 is mandatory either way (owner decision O-5).
Enforcement: NEW-CHECK (S1: 1 to 4), EXISTING pattern for 5 (decision ids),
CURATOR.

**C-26 Allele-frequency context.** As in v0.3.0 D-3, the gnomAD v2.1.1 frequency
of the effect allele is recorded per continental group (afr, amr, asj, eas,
fin, nfe, sas where covered, with the 500-allele floor stated) and the spread is
recorded in the T1 rationale as `af-spread:<number> over <group>[,<group>...]`;
the flag threshold is 0.20 (owner decision O-5). The screen is a recorded
number, not an ancestry inference by the report. The effect allele's rarity
class is shown as a finding field and C-35 applies when it is `rare` or
`ultra_rare`. Enforcement: NEW-CHECK (S1: token present and parseable on an
included or reserve row), EXISTING (rarity derivation).

**C-27 Required ancestry caveat.** (amended: R158-F4) New caveat id
`disease_ancestry`, fixed text: "The studies behind this association sampled
people of the ancestries named in the finding. The association may not apply in
the same way to people of other ancestries, and this report does not infer your
ancestry." Every disease_association finding carries it in every call state
(C-29), and every disease section carries it. Enforcement: CODE
(tools/caveats.py, stage3/run.py `required_caveats`), NEW-CHECK (S1: every C-29
state lists it; S3: every disease section has it).

## D. Assayability and call states

**C-28 Assayability stays provisional.** `assayability_status` is
`unknown-provisional` with source `-` unless a public array manifest is in the
pack. No tracked file says a marker is on the array. Enforcement: EXISTING
(`check_assayability`, docs scan).

**C-29 Call states for a disease_association finding.** (amended: R158-F2)
(amended: R158-F4) Every state has one exact claim frame (two for
covered_reference, chosen by whether both reference copies are provable, as in
the existing A7 and G-1 rules) and a fixed caveat list. No frame says or implies
anything about disease status, protection or absence of risk. Every state
carries `array_limits` and `disease_ancestry`; `rare_ppv` is added under C-35.
Placeholders: `<label>` the T1 label, `<gene>` the gene symbol, `<X>` the
effect allele letter, `<tier>` one of the tier words (established, replicated,
single study, conflicting, unknown), `<scope>` the scope words of C-39,
`<condition>` the finding's condition text.

| frame | state | zygosity | direction | exact claim text | required caveats |
|---|---|---|---|---|---|
| FR-01 | detected | het | susceptibility | <label> (<gene>): one copy of the effect allele <X> was detected. Evidence tier: <tier>, from the GWAS Catalog association count. In published studies of <scope>, this allele was associated with higher odds of <condition>. This is a statistical association at the population level; it is not a diagnosis of <condition> and not an estimate of your own risk. | array_limits;disease_ancestry |
| FR-02 | detected | het | protective | <label> (<gene>): one copy of the effect allele <X> was detected. Evidence tier: <tier>, from the GWAS Catalog association count. In published studies of <scope>, this allele was associated with lower odds of <condition>. This is a statistical association at the population level; it is not a diagnosis of <condition> and not an estimate of your own risk. | array_limits;disease_ancestry |
| FR-03 | detected | hom_alt | susceptibility | <label> (<gene>): two copies of the effect allele <X> were detected. Evidence tier: <tier>, from the GWAS Catalog association count. In published studies of <scope>, this allele was associated with higher odds of <condition>. This is a statistical association at the population level; it is not a diagnosis of <condition> and not an estimate of your own risk. | array_limits;disease_ancestry |
| FR-04 | detected | hom_alt | protective | <label> (<gene>): two copies of the effect allele <X> were detected. Evidence tier: <tier>, from the GWAS Catalog association count. In published studies of <scope>, this allele was associated with lower odds of <condition>. This is a statistical association at the population level; it is not a diagnosis of <condition> and not an estimate of your own risk. | array_limits;disease_ancestry |
| FR-05 | covered_reference | provable | any | <label> (<gene>): both copies match the reference at this position; the effect allele was not found in the genotype. | array_limits;disease_ancestry |
| FR-06 | covered_reference | not provable | any | <label> (<gene>): no copy of the effect allele was found in the genotype at this position. | array_limits;disease_ancestry |
| FR-07 | covered_nocall | - | any | <label> (<gene>): this position is on the array, but the array returned no call, so no genotype is available. | array_limits;disease_ancestry;no_call |
| FR-08 | covered_uninterpretable | - | any | <label> (<gene>): this position was measured, but the call could not be interpreted, so no genotype is given. | array_limits;disease_ancestry;uninterpretable |
| FR-09 | not_covered | - | any | <label> (<gene>): this marker was not measured by this array. That gives no information about whether the effect allele is present. | array_limits;disease_ancestry;not_covered |
| FR-10 | not_assayable | - | any | <label> (<gene>): this locus cannot be assessed from array data. | array_limits;disease_ancestry;not_assayable |

A missing, no-call or uncallable marker never changes the section or the counts
of the other findings, and the Summary counts it under "not measured" or
"returned no call or an uninterpretable result" exactly as today. For a
protective entry a covered_reference or not_covered result never reads as
susceptibility, and for a susceptibility entry it never reads as protection or
low risk (C-43, C-45). Enforcement: EXISTING (A7 sentences, rule R10),
NEW-CHECK (S1: frames and caveat lists pinned; S3: state-by-state fixtures for
both directions).

**C-30 ClinVar is context, never the tier.** A disease entry's tier comes from
the GWAS count only (`_tier_clinvar` returns none for `disease_association`).
A ClinVar record for the same rsID is listed in T5 as context; a record for the
same allele whose classification conflicts in direction with the curated
direction is recorded in the rationale and treated as `conflicting-evidence`
unless the curator shows it concerns a different condition. ClinVar is not
required for inclusion. Enforcement: CODE (stage3/run.py `_tier_clinvar`,
tools/evidence.py `derive_association`), NEW-CHECK (S3), CURATOR.

**C-31 T2 is not used for disease rows; T3 is.** A disease row has no T2 row. A
kept disease row has a T3 row with model `SUSC`, a one-copy and a two-copy
meaning in the closed association wording (`one copy: higher association with
<label>` and `two copies: further higher association with <label>` for
susceptibility; `lower` in place of `higher` for protective; neither contains
the word carrier), and at least one inheritance source of type `pmid`,
`genereviews`, `medgen` or `clingen`. The allowed-combination table of the
Inheritance gate gains one line: `SUSC` with `disease_association` and no
supporting group (`-`). Enforcement: NEW-CHECK (S1), EXISTING (copy-meaning
rules).

**C-32 The inheritance model is not a claim.** `SUSC` records only that the
literature treats the association as a complex susceptibility locus. The report
never states a model, a penetrance or a recurrence. Enforcement: REVIEW, C-43.

**C-33 Strand-ambiguous and palindromic markers.** Palindromic pairs (A/T, C/G)
are excluded `palindromic` with the flag `strand-ambiguous` on the excluded row;
no exception path is added. A multi-allelic site is read on the
reference/effect pair (D8). Enforcement: EXISTING.

**C-34 No silent omission.** (amended: R158-F6) The template and the validator
refuse, never skip, a finding whose `result_type` has no report section: an
unknown `result_type` raises an error before a report is written. The
all-findings citation of the Summary section does not count as a section for
this rule. Required tests (S3): `DA.unknown_result_type_raises` (template and
validator each raise on a findings document with an invented result type) and
`DA.every_known_result_type_has_a_section` (every result type in the schema
enum maps to a section, and a finding of each type appears in that section, not
only in the Summary citation). An intentional omission is allowed only for a
documented known type with an explicit reason in `omitted_findings`. This
lands before any disease entry is in a panel (S3 precedes the S4 rebuild).
Enforcement: CODE (stage3/run.py, tools/validate_report.py), NEW-CHECK (S3).

**C-35 Rare effect alleles.** When the entry's rarity class is `rare` or
`ultra_rare`, the finding gets the existing `rare_ppv` caveat even without a
ClinVar P record; `low_frequency` does not trigger it (owner decision O-11).
Enforcement: CODE (stage2/annotate.py), NEW-CHECK (S3).

**C-36 No dose claim.** Two copies are worded only as in FR-03 and FR-04; no
statement says the second copy has a larger, smaller or multiplicative effect.
Enforcement: NEW-CHECK (S1: frames pinned; S3: rendered text).

## E. Wording rules for the deterministic template

**C-37 Closed sentence frames.** A detected disease_association claim is the
core sentence, the evidence clause, the direction sentence and the association
sentence, in that order, joined by single spaces, exactly as frames FR-01 to
FR-04 of C-29. The association sentence is
`This is a statistical association at the population level; it is not a diagnosis of <condition> and not an estimate of your own risk.`
Numbers are words (rule R1). Enforcement: NEW-CHECK (S1: frames pinned in this
document; S3: rendered strings), CODE.

**C-38 Protective and susceptibility phrasing.** The stems `protect` and
`susceptib` appear only in curation records and schema values; the report says
"lower odds" for a protective allele and "higher odds" for a susceptibility
allele. A protective allele is never worded as protecting, preventing or
reducing the user's risk, and its absence is never worded as a risk (owner
decision O-13). Enforcement: NEW-CHECK (C-43 patterns FP-14 and FP-16).

**C-39 Ancestry words in the claim.** The claim names the scope (C-23) only with
these words, in vocabulary order; two codes are joined by " and ", three or more
by ", " with " and " before the last, followed by " ancestry":

| code | report words |
|---|---|
| european | European |
| east-asian | East Asian |
| south-asian | South Asian |
| african | African |
| hispanic-latino | Hispanic or Latino |
| middle-eastern | Middle Eastern |
| oceanian | Oceanian |
| mixed | mixed |
| other | other |

The claim never says the user belongs to a group. Enforcement: NEW-CHECK (S1:
the table equals the vocabulary; S3: rendered scope).

**C-40 Required caveats per finding.** (amended: R158-F4) Every disease finding
carries `array_limits` and `disease_ancestry` in every call state, plus the
state caveat of C-29 and `rare_ppv` where C-35 applies; `strand_ambiguous`
cannot occur (excluded). Enforcement: EXISTING (`required_caveats` pattern),
NEW-CHECK (S1: C-29 caveat lists; S3: rendered sections).

**C-41 Section.** A new section "Health-related: disease associations"
(`s_disease_associations`) follows "Health-related: associations" and precedes
"Traits". It contains only disease_association findings and is omitted when
the panel has none. The Summary counts the type like the others. No sentence is
added about the absence of disease markers. Enforcement: CODE, NEW-CHECK (S3).

**C-42 Report notices.** The `LIMITATIONS` list gains one fixed line, rendered
only when a disease_association finding is present, so a report without one is
byte-identical to today's:
`Disease associations come from published population studies; they do not describe your own risk, and the studies sampled the ancestries named in each finding.`
The tier definitions are unchanged. Enforcement: CODE (tools/caveats.py,
tools/render_report.py), NEW-CHECK (S3).

**C-43 What a report never says for a disease_association.** (amended: R158-F2) The list below is exact, not illustrative. Validator rule R11 applies
it, case-insensitively, to every claim, caveat text, notice and limitation of a
report that carries a disease_association finding; the list is a data constant
in tools/validate_report.py (S3) and must equal this block.

Procedure:
1. Before scanning, remove only exact instances of the fixed association
   sentence (with the finding's `<condition>`), `TEMPLATE_NOTICE`, each fixed
   `LIMITATIONS` sentence (including the C-42 line), and the exact
   `array_limits` caveat text, as listed in the exemption block. Nothing else is
   removed; a sentence that differs by one character is scanned in full.
2. Remove rsIDs and gene symbols with the validator's existing expressions
   `ID_RE` = `\b(?:rs\d+|f_[0-9a-f]+|c_[0-9a-f]+|cl_[0-9a-f]+|s_[0-9a-z_]+)\b`
   and `GENE_RE` = `\b[A-Z][A-Za-z]*\d[A-Za-z0-9]*\b(?!\.\d)`, and the tokens
   `GRCh37` and `GRCh38`, so that a symbol such as IL23R does not trip the
   digit pattern.
3. Scan all remaining text with every pattern; any match is an error.
4. Each disease claim must also equal one of the exact frames of C-29 (FR-01 to
   FR-10); no other claim text is permitted.
Tests show that appending forbidden text next to an exempt sentence still
fails.

<!-- r11-forbidden-patterns:begin -->
```text
FP-01 diagnosis-status \bdiagnos
FP-02 diagnosis-status \byou (?:have|had)\b
FP-03 diagnosis-status \byou (?:are|were) (?:diagnosed|affected|ill|sick)\b
FP-04 diagnosis-status \bsuffer
FP-05 diagnosis-status \bpatients?\b
FP-06 personal-risk \byour (?:own )?(?:risk|chance|odds|likelihood|probability)\b
FP-07 personal-risk \bat (?:(?:a )?(?:high|higher|increased|elevated|low|lower|reduced|greater|some) )?risk\b
FP-08 personal-risk \brisk (?:of|for) (?:developing|getting)\b
FP-09 personal-risk \b(?:will|would|could|might|may|can|likely to|going to) (?:develop|get|contract)\b
FP-10 personal-risk \b(?:lifetime|absolute|penetran)
FP-11 personal-risk \bpercent|%
FP-12 personal-risk \d
FP-13 personal-risk \b(?:times|fold)\b
FP-14 personal-risk \b(?:predispos|susceptib)
FP-15 personal-risk \b(?:increases?|raises?|lowers?|reduces?|decreases?) your\b
FP-16 protection \b(?:protect|immun|resist|prevent)
FP-17 protection \bsafe\b
FP-18 causation \b(?:caus|determin)
FP-19 causation \b(?:gene for|risk genes?)\b
FP-20 causation \bbad\b
FP-21 causation \bmutation
FP-22 medical-advice \b(?:treat|therap|medicat|drug|statin|surg|screen|monitor|colonoscop|diet|lifestyle|exercise|supplement)
FP-23 medical-advice \b(?:doctor|physician|clinician|nurse|specialist|counsel)
FP-24 medical-advice \b(?:speak with|talk to|consult|follow[- ]?up|check-?up|appointment)
FP-25 medical-advice \bneed(?:s|ed)?\b
FP-26 medical-advice \b(?:recommend|you should|you must|you need to|start taking|stop taking|should (?:take|start|stop|see|get|schedule|ask|change|consider|avoid)|see your|get tested|schedule a|check with your)
FP-27 personal-clinical \byour (?:\w+ )?(?:cholesterol|ldl|hdl|lipids?|blood|glucose|sugar|pressure|ecg|ekg|heart|bowel|gallbladder|labs?|tests?|scans?|biopsy|symptoms?|levels?|results?|markers?|clinical|medical|health|body)\b
FP-28 personal-clinical \babnormal
FP-29 inheritance-family \b(?:carrier|hereditary|inherit|family history|relatives)
FP-30 method-overreach \b(?:polygenic|risk score|sequencing|sequenced|whole[- ]genome|whole[- ]exome)
FP-31 method-overreach \b(?:definitely|definitive|certainly|guaranteed|proven|fatal|you will)\b
```
<!-- r11-forbidden-patterns:end -->

Each pattern has one rejected example (the pattern matches it) and one allowed
near-miss (no pattern matches it):

| pattern | rejected example | allowed near-miss |
|---|---|---|
| FP-01 | The result was diagnosed by the array. | The result was described by the array. |
| FP-02 | You have this condition. | The array has this position. |
| FP-03 | You are affected by this condition. | The position is covered by this array. |
| FP-04 | You suffer from this condition. | The sample came from this study. |
| FP-05 | Patients with this allele were studied. | People with this allele were studied. |
| FP-06 | Your odds of the condition are higher. | The studies reported higher odds of the condition. |
| FP-07 | The allele puts you at higher risk. | The allele was associated with higher odds. |
| FP-08 | The allele raises the risk of developing the condition. | The allele was reported in the studies of the condition. |
| FP-09 | You may develop the condition. | The studies may not apply in the same way. |
| FP-10 | The lifetime odds are higher. | The studied odds are higher. |
| FP-11 | The odds were higher by ten percent. | The odds were higher in the studies. |
| FP-12 | The odds were higher by 2 units. | The odds were higher by two units. |
| FP-13 | The odds were three times higher. | The odds were higher in three studies. |
| FP-14 | The allele marks susceptibility. | The allele marks an association. |
| FP-15 | The allele increases your odds. | The allele was associated with higher odds. |
| FP-16 | The allele protects against the condition. | The allele was associated with lower odds of the condition. |
| FP-17 | The allele is safe. | The allele is common. |
| FP-18 | The allele causes the condition. | The allele was associated with the condition. |
| FP-19 | This is a gene for the condition. | This gene was studied for the condition. |
| FP-20 | This is a bad allele. | This is a studied allele. |
| FP-21 | This mutation was found. | This allele was found. |
| FP-22 | Treatment options exist for the condition. | Published studies exist for the condition. |
| FP-23 | Ask a doctor about the condition. | Read the studies about the condition. |
| FP-24 | A follow-up is advised for the condition. | A study is cited for the condition. |
| FP-25 | Nothing more is needed for this result. | Nothing more is shown for this result. |
| FP-26 | We recommend a second array. | We report a second array. |
| FP-27 | Your blood values are high. | The studied values are high. |
| FP-28 | The result is abnormal. | The result is uninterpreted. |
| FP-29 | The allele is hereditary. | The allele is common. |
| FP-30 | The polygenic odds are higher. | The studied odds are higher. |
| FP-31 | The finding is definitive. | The finding is an association. |

Exemption block (exact strings; removed only where they occur whole):

<!-- r11-exemptions:begin -->
```text
EX-01 association-sentence This is a statistical association at the population level; it is not a diagnosis of <condition> and not an estimate of your own risk.
EX-02 TEMPLATE_NOTICE This report was generated by fixed templates on this machine from structured findings; no language model was used to write it. It is a research and curiosity tool, not medical advice or a diagnostic test.
EX-03 LIMITATIONS The array covers about 0.02% of the genome.
EX-04 LIMITATIONS Genotypes are reported on the forward-strand against build GRCh37.
EX-05 LIMITATIONS The release uses a small public panel; the Summary counts its markers by kind.
EX-06 LIMITATIONS This report is not medical advice, and no result is a diagnosis.
EX-07 LIMITATIONS A rare array call should be confirmed by a clinical-grade test.
EX-08 LIMITATIONS Only template-only narration is verified in this release.
EX-09 LIMITATIONS No marker's presence on the array was verified, because no public array manifest is available.
EX-10 LIMITATIONS Whether the panel covers enough is the owner's aggregate judgment.
EX-11 C-42-line Disease associations come from published population studies; they do not describe your own risk, and the studies sampled the ancestries named in each finding.
EX-12 array_limits Array-based genotyping covers a small fraction of the genome (~0.02%), is chip-dependent, and is not diagnostic grade.
```
<!-- r11-exemptions:end -->

The exemption strings EX-02 to EX-10 and EX-12 equal the production constants
in tools/caveats.py, and a test pins that equality. The other fixed caveat
texts (`disease_ancestry`, `no_call`, `uninterpretable`, `not_covered`,
`not_assayable`, `rare_ppv`) are not exempt and pass the scan as written. The
review corpus of round r158 (38 sentences: 23 to reject, 15 to allow) is
classified as its oracle says, including the mandatory `array_limits` caveat
and the five sentences the illustrative draft missed (a personal LDL claim, a
personal clinical claim, a follow-up statement, and two conditional-risk
statements). Enforcement: CODE (tools/validate_report.py R11), NEW-CHECK (S1:
list pinned, corpus and examples classified, exemption adjacency; S3: the
production constant equals the block).

**C-44 Condition names.** A curated disease label that matches any pattern of
C-43, other than through the word "disease", is a checker error: the label is
never a loophole. Enforcement: NEW-CHECK (S1: disease T1 labels scanned).

**C-45 Direction words are required.** A detected disease claim contains exactly
one of "higher odds of" or "lower odds of", the one that matches
`association_direction`; a claim for any other state contains neither.
Enforcement: NEW-CHECK (S1: frames; S3: rendered claims).

**C-46 Interaction with the narration guards.** (amended: R158-F1) Under C-6
disease findings and claims never reach a model in any mode or route, so the
narration guards G-1 to G-3 never see them; AL-052 is unchanged. The
covered_reference disease frames follow the A7 wording (FR-05, FR-06), so the
sentence "This call does not establish the reference genotype." is not used. If
a later release enables model narration for disease findings, R11 applies to
model text too and the narration needs its own contract and review. The tests
named in C-6 prove the routing. Enforcement: CODE, NEW-CHECK (S3).

**C-47 Numbers.** Claim text spells numbers as words (rule R1); a disease claim
contains no digit outside an rsID or gene symbol (FP-12 after step 2 of C-43).
Enforcement: EXISTING (R1), NEW-CHECK (S1: pattern; S3: rendered claims).

## F. Disposition vocabulary, reason codes, sources

**C-48 Decisions.** Unchanged: `included`, `excluded`, `reserve`. A disease row
may be `reserve` only if it meets every inclusion criterion. Enforcement:
EXISTING.

**C-49 Reason codes.** (amended: R158-F7) The closed list gains two codes
(owner decision O-12):
- `proxy-only`: the candidate has no T4 row under its own rsID, and the pack
  holds rows only for rsIDs linked to it;
- `ancestry-unrecorded`: the rows that would count lack a recorded ancestry or
  sample size for their stage, so fewer than the required groups remain.
`label-mismatch` is reused for a candidate whose own-rsID rows all report a
phenotype that is not the label or an approved synonym. The two are exclusive:
a candidate with any row under its own rsID is never `proxy-only`. Other codes
used: `palindromic`, `conflicting-evidence`, `single-study`,
`no-independent-confirmation`, `evidence-not-in-pack`, `ancestry-informative`,
`owner-declined`. `inheritance-*` and the ClinVar codes do not apply to disease
rows. Enforcement: EXISTING (`check_reason_code_list`), NEW-CHECK (S1).

**C-50 Typed public source records.** Each row cites the typed ids of the
public records used: `dbsnp:rs<digits>`, `gwas:GCST<digits>`, `pmid:<digits>`,
optional `clinvar:vcv:<digits>` (context), `genereviews`, `medgen` or `clingen`
for an inheritance source, `manifest:<id>` only for a public array manifest, and
the new `gnomad:<chrom>-<pos>-<ref>-<alt>` for the gnomAD answers behind C-26,
grammar `gnomad:` plus `[0-9XY]+-\d+-[ACGT]+-[ACGT]+` (owner decision O-9).
Enforcement: EXISTING (typed-id checkers), NEW-CHECK (S1: the new type).

**C-51 Evidence recorded for every scoped marker, including exclusions.** Every
scoped marker has a T1 row with the rsID, gene, GRCh37 chromosome, label,
`result type` = `disease_association`, `category` = `disease`, the effect allele
(or `-` when no counted row names one), direction/meaning (C-14) or
`not applicable` for an excluded row, `GRCh37/forward` (with
`;strand-ambiguous` on an excluded palindromic row), assayability status, typed
sources, retrieved date, rationale (strand statement; report-safety; ancestry
statement; `af-spread:`; `or:` tokens; `independence:` tokens; `alias-review:`
tokens; the replication status first), limitations (including
`ancestry-scope:`), decision and reason code. The tokens are required on
included and reserve rows; an excluded row needs its reason code and typed
sources. Enforcement: EXISTING (T1 shape), NEW-CHECK (S1).

**C-52 The all-excluded outcome (V6).** An all-excluded release is valid when
every candidate has a T1 row with decision `excluded`, one reason code and
typed sources; no disease entry is in `data/targets.release.json`; the T1
status line counts the rows; the Limitations paragraph says that no disease
association met this contract; the contract, the new reason codes and the
template changes (tested with invented fixtures) still ship; the existing nine
entries are byte-identical; and the version policy of owner decision O-8
applies. The release itself is the owner's decision. Scope pin: the four
candidates rs10757278, rs2200733, rs11209026 and rs4245791 each have a disease
T1 row with a decision, the existing rs11887534 record has a T1 row with a
decision, and the included disease rows and the disease entries of the targets
file are the same set. A panel without a disease entry renders no disease
section and no sentence about disease markers. Enforcement: NEW-CHECK (S1:
scope pin and an all-excluded fixture; S2: applied to the real tables; S3:
rendering), EXISTING (bijection).

## G. Privacy

**C-53 No change to the local-only default.** (amended: R158-F1) The contract
adds no network behavior, no data transmission and no new place where a
genotype can be written. The online narrator stays opt-in and gated, and under
C-6 it never receives a disease finding, its call state or its claims. The new
finding fields are curated public values; none is derived from the user's file,
and the report never infers the user's ancestry. Evidence capture sends only
rsIDs, study accessions, PubMed ids and genomic coordinates of public variants;
no genotype, file hash or personal value is ever sent. Tests stay offline; the
guard and the safety layer are unchanged. Enforcement: EXISTING (guard),
NEW-CHECK (S3, the C-6 tests), REVIEW.

## H. Not covered

**C-54 This contract does not cover:** APOE and any APOE-genotype finding;
pharmacogenomics and drug response; HLA and any HLA-dependent finding;
polygenic or aggregate scores and any combination of markers (compound
genotypes, haplotypes, epistasis, the rs11887534 plus rs4245791 pair as one
finding); monogenic and carrier findings (existing categories); sex-chromosome,
mitochondrial and pseudo-autosomal markers (AUTO-1); ancestry or relatedness
inference; absolute, lifetime or age-specific risk, penetrance, recurrence;
diagnosis, screening, treatment, lifestyle or family-planning advice; any claim
from the user's family history or laboratory or clinical values;
cancer-susceptibility genes evaluated through ClinVar; evidence from
candidate-gene studies, eQTL or functional experiments, preprints or
unpublished data, and from any source that is not a public GWAS Catalog record
with its publication in the pack; model narration of disease claims;
per-user ancestry-specific interpretation; non-GRCh37 coordinates.

## Definition of done map

- V1 (contract approved, reviewed and recorded before any marker is curated):
  this document, the specification review of round r158 and its corrections.
- V2 (traceable disposition and typed sources for every scoped marker): C-7 to
  C-33, C-48 to C-52, in the existing tables T1, T3, T4 and T5.
- V3 (included entries meet the rules; reproducible rebuild): C-8, C-15, C-52.
- V4 (synthetic end-to-end runs cover the wording and the missing states): C-29,
  C-34, C-37 to C-47.
- V6 (documented all-excluded outcome): C-52.
