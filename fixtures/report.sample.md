# Genetic findings report

> This report was synthesized from a raw DNA file by an external language model from structured findings produced locally. It is a research and curiosity tool, not medical advice or a diagnostic test.

## Provenance

- Input hash: `0000000000000000000000000000000000000000000000000000000000000000`
- Array: AncestryDNA V2.0 (converter V1.0)
- Build: GRCh37, strand: forward
- Manifest rows: 677420
- Pipeline: 0.1.0, generated 2026-10-20T00:00:00Z
- Annotation snapshots:
  - dbSNP b156 (public domain (NCBI)), retrieved 2026-10-01T00:00:00Z
  - ClinVar 2026-09 (public domain (NCBI)), retrieved 2026-10-01T00:00:00Z
  - gnomAD v4.0 (free (Broad)), retrieved 2026-10-01T00:00:00Z

## Detected variants

- rs4988235 is heterozygous and carries an established association. [f_000000000001 · call.zygosity] [f_000000000001 · evidence.association]
- rs1800562 is reported as Pathogenic with a 2-star ClinVar review status. [f_000000000006 · evidence.clinvar.review_stars] [f_000000000006 · evidence.clinvar.significance]
- rs1799945 is reported with a conflicting interpretation at a 1-star review status. [f_000000000007 · evidence.clinvar.review_stars] [f_000000000007 · evidence.clinvar.significance]
- These two HFE findings concern the same condition with different evidence strengths; both are reported and are not reconciled. [f_000000000006 · evidence.association] [f_000000000007 · evidence.association]
- rs1333049 is heterozygous at a palindromic C/G site, so allele orientation is ambiguous. [f_000000000008 · call.strand] [f_000000000008 · call.zygosity]
- rs121918897 is a rare heterozygous call classified as Likely pathogenic. [f_000000000009 · confidence.array_reliability.rarity_class] [f_000000000009 · evidence.clinvar.significance]

**Contradictions reported (not reconciled):**
> Two HFE variants are reported for the same condition (hereditary hemochromatosis) with different evidence strengths: rs1800562 has 2-star pathogenic classification, while rs1799945 has a 1-star conflicting interpretation. Both are reported as-is; they are not reconciled. _(c_000000000001)_

**Caveats**
- Array-based genotyping covers a small fraction of the genome (~0.02%), is chip-dependent, and is not diagnostic grade.
- Palindromic site: allele orientation cannot be resolved from array data alone.
- Rare heterozygous array calls have low positive predictive value and warrant clinical-grade confirmation.

## On the array, no variant detected, or no call

- rs6025 is on the array and shows the reference genotype; the Pathogenic 3-star variant is not present. [f_000000000002 · call.state] [f_000000000002 · call.zygosity] [f_000000000002 · evidence.clinvar.review_stars]
- rs429358 is on the array but returned no call. [f_000000000003 · call.state]

**Caveats**
- Array-based genotyping covers a small fraction of the genome (~0.02%), is chip-dependent, and is not diagnostic grade.
- This position is on the array but genotyping did not return a call.

## Not measured by this array

- rs80357906 in BRCA1 was not measured by the array, so no genotype or confidence applies. [f_000000000004 · coverage.state]

**Caveats**
- Array-based genotyping covers a small fraction of the genome (~0.02%), is chip-dependent, and is not diagnostic grade.
- This marker was not measured by the array; no genotype or confidence applies.

## Not accessible to this assay

- HTT CAG repeat expansions cannot be assessed from this kind of array data. [f_000000000005 · state]

**Caveats**
- Array-based genotyping covers a small fraction of the genome (~0.02%), is chip-dependent, and is not diagnostic grade.
- This locus cannot be assessed from SNP-array data.

