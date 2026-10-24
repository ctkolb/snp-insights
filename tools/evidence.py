# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Shared evidence logic: condition normalization/matching, ClinVar selection,
and association-tier derivation.

Pure functions plus one JSON read (`load_aliases`); no network and no other I/O.
Both `tools/fetch_reference.py` and `tools/build_panel.py` import from here so a
single implementation owns each decision.
"""
import json
import os
import re

_ALIASES_DEFAULT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "condition_aliases.json"
)

CLINVAR_TIER = {4: "established", 3: "established", 2: "replicated", 1: "single_study"}


def norm_cond(text):
    """Lowercase, replace non [a-z0-9] with a space, collapse, strip."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())).strip()


def load_aliases(path=None):
    """Return the alias map; {} when the file is missing.

    Raises ValueError naming the key when a non-underscore group is not a list
    of strings, so a malformed hand-edited file fails loudly instead of being
    iterated character by character.
    """
    p = path or _ALIASES_DEFAULT
    if os.path.exists(p):
        with open(p) as fh:
            data = json.load(fh)
        for key, value in data.items():
            if key.startswith("_"):
                continue
            if not isinstance(value, list) or not all(isinstance(m, str) for m in value):
                raise ValueError(f"alias group {key!r} must be a list of strings")
        return data
    return {}


def _contains_word(haystack, needle):
    if not needle:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", haystack) is not None


def _alias_members(value):
    """Normalize a group value to a list of members without iterating a string.

    A bare string is treated as a one-element list; any other non-list value is
    ignored. Non-string entries are dropped.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [m for m in value if isinstance(m, str)]
    return []


def _condition_variants(condition, aliases):
    c = norm_cond(condition)
    variants = {c}
    for key, members in (aliases or {}).items():
        if key.startswith("_"):
            continue
        norm_key = norm_cond(key)
        norm_members = {norm_cond(m) for m in _alias_members(members)}
        if c == norm_key or c in norm_members:
            variants |= {norm_key} | norm_members
    return {v for v in variants if v}


def condition_matches(text, condition, aliases):
    """True iff any variant of `condition` occurs in `text` at a word boundary."""
    if not text or not condition:
        return False
    haystack = norm_cond(text)
    return any(_contains_word(haystack, v) for v in _condition_variants(condition, aliases))


def review_stars(status):
    """Map a ClinVar review-status string to the 0-4 star scale (None if unknown)."""
    s = (status or "").lower()
    if "practice guideline" in s:
        return 4
    if "expert panel" in s:
        return 3
    if "multiple submitters" in s and "no conflict" in s:
        return 2
    if "conflicting" in s:
        return 1
    if "single submitter" in s:
        return 1
    if "no assertion criteria" in s or not s:
        return 0
    return None


def sig_rank(sig):
    """Rank a ClinVar significance by disease relevance (not clinical confidence)."""
    s = (sig or "").lower()
    if "drug response" in s or "benign" in s or "protective" in s or s.strip() == "association":
        return 0
    if "pathogenic" in s and "conflicting" not in s:
        return 4
    if "risk factor" in s or "risk allele" in s:
        return 3
    if "conflicting" in s:
        return 2
    return 1


def select_clinvar(rows, condition, aliases):
    """Pick the ClinVar row most relevant to the curated condition.

    rows: [{'sig','review','phenotype'}]. Rows with empty sig are never
    candidates. Matched-first (D-M): when `condition` is truthy and at least one
    candidate's phenotype matches it, only the matched rows compete; otherwise
    all candidates compete. Within the competing rows the score is
    sig_rank*100 + (review_stars or 0); highest wins, first row wins exact ties.
    Returns the winning row dict or None.
    """
    candidates = []
    for r in rows or []:
        sig = (r.get("sig") or "").strip()
        if not sig:
            continue
        candidates.append(r)
    if condition:
        matched = [r for r in candidates if condition_matches(r.get("phenotype"), condition, aliases)]
        if matched:
            candidates = matched
    best, best_score = None, None
    for r in candidates:
        score = sig_rank(r["sig"]) * 100 + (review_stars(r.get("review")) or 0)
        if best_score is None or score > best_score:
            best_score, best = score, r
    return best


def clinvar_tier(significance, stars):
    """ClinVar association tier from a significance string and star count."""
    if "conflicting" in (significance or "").lower():
        return "conflicting"
    return CLINVAR_TIER.get(stars)


def gwas_tier(n):
    """GWAS association tier from a matching-study count."""
    if not n:
        return None
    return "replicated" if n >= 2 else "single_study"


def count_matching_studies(pairs, condition, aliases):
    """Distinct study ids whose trait matches `condition`.

    pairs: [(study_id, trait_text)]. When `condition` is falsy, count every
    distinct study id regardless of trait.
    """
    ids = set()
    for pair in pairs or []:
        study_id, trait = pair[0], pair[1]
        if not study_id:
            continue
        if not condition or condition_matches(trait, condition, aliases):
            ids.add(study_id)
    return len(ids)
