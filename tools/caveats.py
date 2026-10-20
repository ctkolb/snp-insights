# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Single source of truth for caveat text.

The narrator selects caveat IDs; the renderer expands them here, so caveat
wording is never authored by the model.
"""

CAVEAT_REGISTRY = {
    "array_limits": "Array-based genotyping covers a small fraction of the genome (~0.02%), is chip-dependent, and is not diagnostic grade.",
    "not_covered": "This marker was not measured by the array; no genotype or confidence applies.",
    "no_call": "This position is on the array but genotyping did not return a call.",
    "not_assayable": "This locus cannot be assessed from SNP-array data.",
    "uninterpretable": "This position was measured, but the reported alleles do not match the known reference or alternate allele, so the genotype cannot be interpreted.",
    "strand_ambiguous": "Palindromic site: allele orientation cannot be resolved from array data alone.",
    "rare_ppv": "Rare heterozygous array calls have low positive predictive value and warrant clinical-grade confirmation.",
}

# finding.state -> required caveat id
STATE_CAVEAT = {
    "not_covered": "not_covered",
    "covered_nocall": "no_call",
    "covered_uninterpretable": "uninterpretable",
    "not_assayable": "not_assayable",
}

STANDING_NOTICE = (
    "This report was synthesized from a raw DNA file by an external language "
    "model from structured findings produced locally. It is a research and "
    "curiosity tool, not medical advice or a diagnostic test."
)
