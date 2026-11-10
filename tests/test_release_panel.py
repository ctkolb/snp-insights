#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Release-panel curation gates (R1B.*): the offline consistency suite for
docs/panel-curation.md and data/targets.release.json.

Run standalone:  python -B tests/test_release_panel.py
Or as part of:   python tests/test_pipeline.py

Every gate is isolated: a missing file, a missing function, or any exception
fails only that one check (via attempt()), never the whole run. All inputs for
the self-tests are invented; no real data is read.

Three families of ids:
  R1B.syn_*   self-contained: the pure checkers run on invented fixtures and
              prove that each rule can fail.
  real-file   the same checkers run on the real document and targets file;
              each prints rows_checked=<n> so a green run on zero rows is
              never read as coverage.
  R1B.char_*  characterization of files this work must not touch.
"""
import datetime
import hashlib
import itertools
import json
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

DATA = os.path.join(ROOT, "data")
DOC_REL = "docs/panel-curation.md"
TARGETS_REL = "data/targets.release.json"
DOC_PATH = os.path.join(ROOT, *DOC_REL.split("/"))
TARGETS_PATH = os.path.join(ROOT, *TARGETS_REL.split("/"))
ALIASES_PATH = os.path.join(DATA, "condition_aliases.json")

# sha256 of the files this ticket must not touch (pinned on the base commit).
PINNED_HASHES = {
    "targets.carrier.json": "e9e7453a440ce51609b350b62a2f321c12374286355178edd3a52b47698c4f10",
    "targets.traits.json": "aabf84bfc412144214fc8f4f09eac8983a4ebaec0095c9cd2c9b16f6735fa6ce",
    "targets.sample.json": "0f1ae6151508f8bafeb3c64986d5f59c4cd0704f4ee6a859d795fe97047a93ad",
    "condition_aliases.json": "8335a74dfae716acd420e525e03289b8fb1c339ba87088b645605850ac32e7f2",
}

# --- rule constants (single source of truth for the checkers) ----------------
AUTOSOMES = tuple(str(n) for n in range(1, 23))
NON_AUTOSOMAL_NAMES = ("X", "Y", "PAR", "MT")
CATEGORIES = ("carrier", "trait")
RESULT_TYPES = ("trait", "carrier_status", "risk_association")
VALID_PAIRS = (("trait", "trait"), ("carrier", "carrier_status"), ("carrier", "risk_association"))
TARGETS_ALLOWED_KEYS = frozenset(("rsid", "gene", "condition", "category", "result_type",
                                  "effect_allele", "assayability", "strand"))
DECISIONS = ("included", "excluded", "reserve")
REASON_CODES = (
    "conflicting-evidence", "single-study", "palindromic", "unclear-allele", "not-assayable",
    "label-mismatch", "ancestry-informative", "owner-declined", "non-autosomal-out-of-scope",
    "allele-not-mappable", "no-allele-condition-match", "ineligible-significance",
    "insufficient-review-status", "inheritance-unresolved", "inheritance-out-of-scope",
    "no-independent-confirmation", "evidence-not-in-pack",
)
RETIRED_REASON_CODES = ("x-linked-out-of-scope",)
ASSAY_STATUSES = ("verified-from-public-manifest", "unknown-provisional")
MODELS = ("AR", "AD-IP", "SUSC", "AD", "UNRESOLVED", "n/a")
MODEL_RESULT_TYPES = {"AR": "carrier_status", "AD-IP": "risk_association",
                      "SUSC": "risk_association", "n/a": "trait"}
INHERITANCE_OK = {("AR", "carrier_status", "P"), ("AD-IP", "risk_association", "P"),
                  ("AD-IP", "risk_association", "RF"), ("SUSC", "risk_association", "P"),
                  ("SUSC", "risk_association", "RF"), ("n/a", "trait", "-")}
HEALTH_SOURCE_TYPES = ("genereviews", "medgen", "clingen", "pmid")
GROUPS = ("P", "B", "U", "RF", "AP", "CF")
DISPOSITIONS = ("match", "other-allele", "other-condition", "unmapped")
UNRESOLVED_MARKERS = ("to verify", "TBD", "TODO", "FIXME", "unverified-source")
P_THRESHOLD = 5e-8
MIN_GROUPS = 2
FN_GROUP_CAP = 1

T1_HEADER = ["rsID", "gene", "chrom (GRCh37)", "label used in report", "result type", "category",
             "effect allele (fwd, GRCh37)", "direction/meaning", "build/strand",
             "assayability_status", "assayability_source", "sources (typed ids)",
             "retrieved (UTC date)", "rationale", "limitations", "decision", "reason code"]
T2_HEADER = ["rsID", "pair allele (fwd GRCh37)", "pair condition", "matched record ids",
             "matched significance", "matched review status", "stars", "considered records",
             "resolution", "pair outcome"]
T3_HEADER = ["rsID", "model", "one-copy meaning", "two-copy meaning",
             "inheritance sources (typed ids)"]
T4_HEADER = ["rsID", "row id", "study accession", "PMID", "trait (reported)",
             "effect allele (fwd, GRCh37)", "orientation", "orientation source", "direction",
             "p-value", "sample ancestry", "sample size", "cohort id", "cohort source",
             "overlap with", "counted"]
T5_HEADER = ["rsID", "ClinVar VariationIDs in pack (all assemblies)", "pack file index id"]
TABLE_HEADERS = {"T1": T1_HEADER, "T2": T2_HEADER, "T3": T3_HEADER, "T4": T4_HEADER,
                 "T5": T5_HEADER}
GROUP_TABLE_HEADER = ["group set", "carrier_status supporting group",
                      "risk_association supporting group"]

DOC_REQUIRED_HEADINGS = (
    "Method", "Criteria", "Source hierarchy", "Exclusion rule AUTO-1", "Considered set",
    "Allele mapping", "Qualifying record", "No carry-over", "Resolution", "Supporting group",
    "Inheritance gate", "Assayability", "Replication", "Typed ids", "Reason codes", "Tables",
    "Limitations", "Provenance block",
)
OUTCOME_STRINGS = (
    "excluded:allele-not-mappable", "excluded:no-allele-condition-match",
    "excluded:conflicting-evidence", "excluded:ineligible-significance",
    "excluded:insufficient-review-status", "eligible",
)
RESOLUTION_CODES = ("resolution-not-typed", "resolution-wrong-type", "resolution-not-matched",
                    "resolution-not-p", "resolution-low-stars", "resolution-without-conflict",
                    "resolution-contested")
SHORT = {
    "rsid": "rsID", "gene": "gene", "chrom": "chrom (GRCh37)", "label": "label used in report",
    "rt": "result type", "cat": "category", "allele": "effect allele (fwd, GRCh37)",
    "meaning": "direction/meaning", "bs": "build/strand", "astat": "assayability_status",
    "asrc": "assayability_source", "src": "sources (typed ids)", "date": "retrieved (UTC date)",
    "why": "rationale", "lim": "limitations", "dec": "decision", "code": "reason code",
}


def _require(message, cond):
    if not cond:
        raise AssertionError(message)


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        digest.update(fh.read())
    return digest.hexdigest()


def _run_characterization(attempt):
    def char_draft_files_unchanged():
        for name, want in sorted(PINNED_HASHES.items()):
            path = os.path.join(DATA, name)
            _require(f"data/{name} missing", os.path.exists(path))
            got = _sha256_file(path)
            _require(f"data/{name} changed: sha256 {got} != pinned {want}", got == want)
        return True
    attempt("R1B.char_draft_files_unchanged", char_draft_files_unchanged)

    def char_guard_allows_release_targets_name():
        import guard
        found = guard.check_allowlist(["data/targets.release.json"])
        _require(f"guard refuses data/targets.release.json: {found}", found == [])
        return True
    attempt("R1B.char_guard_allows_release_targets_name", char_guard_allows_release_targets_name)


# =============================================================================
# Checkers. Each check_<name> takes parsed tables and returns a Result: an error
# list that also carries rows_checked. Errors start with a stable code.
# =============================================================================
class Result(list):
    rows_checked = 0


def _result(errors, rows_checked):
    res = Result(errors)
    res.rows_checked = rows_checked
    return res


def _live(rows, *decisions):
    return [r for r in rows if r.get("decision") in decisions]


# --- table parser (fails closed) ---------------------------------------------
class TableError(ValueError):
    pass


_SEP_CELL = re.compile(r"^:?-{3,}:?$")


def _split_row(line):
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|") and len(s) >= 2):
        raise TableError(f"not a table row: {s[:40]!r}")
    return [c.strip() for c in s[1:-1].split("|")]


def _parse_block(block):
    header = _split_row(block[0])
    if len(block) < 2:
        raise TableError("table has no separator row")
    sep = _split_row(block[1])
    if len(sep) != len(header) or not all(_SEP_CELL.match(c) for c in sep):
        raise TableError("separator row is malformed")
    if len(set(header)) != len(header):
        raise TableError("duplicate column name in header")
    rows = []
    for line in block[2:]:
        cells = _split_row(line)
        if len(cells) != len(header):
            raise TableError(f"ragged row: {len(cells)} cells for {len(header)} columns")
        if all(_SEP_CELL.match(c) for c in cells):
            raise TableError("repeated separator row")
        rows.append(dict(zip(header, cells)))
    return {"header": header, "rows": rows}


def parse_tables(text):
    """Every markdown table outside code fences; raises TableError on any defect."""
    lines = text.splitlines()
    tables, i, fenced = [], 0, False
    while i < len(lines):
        stripped = lines[i].lstrip()
        if stripped.startswith("```"):
            fenced = not fenced
            i += 1
        elif not fenced and stripped.startswith("|"):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block.append(lines[i])
                i += 1
            tables.append(_parse_block(block))
        else:
            i += 1
    return tables


def find_table(tables, header):
    hits = [t for t in tables if t["header"] == list(header)]
    if len(hits) != 1:
        raise TableError(f"table with header starting {header[0]!r}...{header[-1]!r}: "
                         f"found {len(hits)}, expected exactly 1")
    return hits[0]


def doc_tables(text):
    tables = parse_tables(text)
    return {name: find_table(tables, header)["rows"] for name, header in TABLE_HEADERS.items()}


def read_doc():
    _require(f"{DOC_REL} missing", os.path.exists(DOC_PATH))
    with open(DOC_PATH, encoding="utf-8") as fh:
        return fh.read()


def read_targets():
    _require(f"{TARGETS_REL} missing", os.path.exists(TARGETS_PATH))
    with open(TARGETS_PATH, encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except ValueError as exc:
            raise AssertionError(f"{TARGETS_REL} is not valid JSON: {exc}")


def sections(text):
    """[(level, title, body)] for every markdown heading outside code fences; the body
    runs to the next heading of the same or a higher level."""
    lines, heads, fenced = text.splitlines(), [], False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        m = None if fenced else re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2)))
    out = []
    for idx, (i, level, title) in enumerate(heads):
        end = len(lines)
        for j, lvl, _ in heads[idx + 1:]:
            if lvl <= level:
                end = j
                break
        out.append((level, title, "\n".join(lines[i + 1:end])))
    return out


def section_body(text, title):
    for _, t, body in sections(text):
        if t == title:
            return body
    return None


def _word(text, word):
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(word) + r"(?![A-Za-z0-9])", text) is not None


# --- chromosome rule AUTO-1 -------------------------------------------------
def chrom_class(token):
    if isinstance(token, str) and token in AUTOSOMES:
        return "autosomal"
    if isinstance(token, str) and token in NON_AUTOSOMAL_NAMES:
        return "non_autosomal"
    return "malformed"


def check_chromosomes(t1_rows, entries):
    errors = []
    for r in t1_rows:
        rs, cls, dec = r.get("rsID"), chrom_class(r.get("chrom (GRCh37)")), r.get("decision")
        if cls == "malformed":
            errors.append(f"chrom-malformed: {rs} chromosome cell {r.get('chrom (GRCh37)')!r}")
        elif cls == "non_autosomal":
            if dec in ("included", "reserve"):
                errors.append(f"non-autosomal-kept: {rs} is {dec} on {r.get('chrom (GRCh37)')}")
            elif dec == "excluded" and r.get("reason code") != "non-autosomal-out-of-scope":
                errors.append(f"non-autosomal-code: {rs} excluded with code {r.get('reason code')!r}")
    for e in entries:
        if "chromosome" in e and chrom_class(e["chromosome"]) != "autosomal":
            errors.append(f"entry-chrom-not-autosomal: {e.get('rsid')} chromosome {e['chromosome']!r}")
    return _result(errors, len(t1_rows) + len(entries))


# --- pair table (category x result type) --------------------------------------
def pair_ok(category, result_type):
    return (category, result_type) in VALID_PAIRS


def check_pairs(entries):
    errors = []
    for e in entries:
        if not pair_ok(e.get("category"), e.get("result_type")):
            errors.append(f"pair-invalid: {e.get('rsid')} ({e.get('category')!r}, {e.get('result_type')!r})")
    return _result(errors, len(entries))


def check_t1_pairs(t1_rows):
    errors = []
    for r in t1_rows:
        if not pair_ok(r.get("category"), r.get("result type")):
            errors.append(f"pair-invalid: {r.get('rsID')} ({r.get('category')!r}, {r.get('result type')!r})")
    return _result(errors, len(t1_rows))


# --- typed ids, provenance -----------------------------------------------------
_TYPED_RES = {
    "dbsnp": r"rs\d+", "clinvar": r"(?:vcv:\d+|rcv:RCV\d+)", "gwas": r"GCST\d+", "pmid": r"\d+",
    "genereviews": r"NBK\d+", "medgen": r"[A-Za-z0-9]+", "clingen": r"[A-Za-z0-9_.-]+",
    "manifest": r"[A-Za-z0-9._-]+",
}


def typed_id_ok(value):
    m = re.fullmatch(r"([a-z]+):(.+)", value or "")
    return bool(m) and m.group(1) in _TYPED_RES and re.fullmatch(_TYPED_RES[m.group(1)], m.group(2)) is not None


def split_ids(cell):
    return [] if cell in ("-", "") else [p.strip() for p in cell.split(";")]


def date_ok(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def check_provenance(t1_rows):
    errors, rows = [], _live(t1_rows, "included", "reserve")
    for r in rows:
        rs = r["rsID"]
        if not date_ok(r["retrieved (UTC date)"]):
            errors.append(f"date-invalid: {rs} {r['retrieved (UTC date)']!r}")
        ids = split_ids(r["sources (typed ids)"])
        if not ids:
            errors.append(f"sources-missing: {rs}")
        for i in ids:
            if not typed_id_ok(i):
                errors.append(f"typed-id-invalid: {rs} {i!r}")
    return _result(errors, len(rows))


# --- decisions, reasons, duplicates, bijection -----------------------------------
def check_decisions(t1_rows):
    errors = []
    for r in t1_rows:
        dec, code, rs = r["decision"], r["reason code"], r["rsID"]
        if dec not in DECISIONS:
            errors.append(f"decision-invalid: {rs} {dec!r}")
        elif dec == "excluded":
            if code in ("-", ""):
                errors.append(f"reason-missing: {rs}")
            elif code in RETIRED_REASON_CODES:
                errors.append(f"reason-retired: {rs} {code!r}")
            elif code not in REASON_CODES:
                errors.append(f"reason-unknown: {rs} {code!r}")
        elif code != "-":
            errors.append(f"reason-on-kept-row: {rs} {dec} carries {code!r}")
    return _result(errors, len(t1_rows))


def check_unique_rsids(t1_rows, entries):
    errors = []
    for label, ids in (("t1", [r["rsID"] for r in t1_rows]), ("targets", [e.get("rsid") for e in entries])):
        seen, dups = set(), set()
        for i in ids:
            (dups if i in seen else seen).add(i)
        errors.extend(f"duplicate-rsid: {i} repeated in {label}" for i in sorted(dups, key=str))
    return _result(errors, len(t1_rows) + len(entries))


def check_bijection(t1_rows, entries):
    included = {r["rsID"] for r in _live(t1_rows, "included")}
    targets = {e.get("rsid") for e in entries}
    errors = [f"entry-without-row: {i}" for i in sorted(targets - included, key=str)]
    errors += [f"row-without-entry: {i}" for i in sorted(included - targets, key=str)]
    return _result(errors, len(included) + len(targets))


def check_reserves_not_in_targets(t1_rows, entries):
    targets = {e.get("rsid") for e in entries}
    reserves = _live(t1_rows, "reserve")
    errors = [f"reserve-in-targets: {r['rsID']}" for r in reserves if r["rsID"] in targets]
    return _result(errors, len(reserves))


# --- alleles, build, strand ----------------------------------------------------------
def allele_ok(allele, kind):
    if kind == "snp":
        return allele in ("A", "C", "G", "T")
    if kind == "indel":
        return allele in ("I", "D")
    return allele in ("A", "C", "G", "T", "I", "D")


def check_effect_alleles(t1_rows, entries):
    errors, by_id = [], {e.get("rsid"): e for e in entries}
    for e in entries:
        if e.get("assayability") not in ("snp", "indel"):
            errors.append(f"kind-invalid: {e.get('rsid')} assayability {e.get('assayability')!r}")
        elif not allele_ok(e.get("effect_allele"), e["assayability"]):
            errors.append(f"allele-invalid: {e.get('rsid')} {e.get('effect_allele')!r} for {e['assayability']}")
    for r in t1_rows:
        rs, a, dec = r["rsID"], r["effect allele (fwd, GRCh37)"], r["decision"]
        if dec == "excluded" and a == "-":
            continue
        entry = by_id.get(rs)
        kind = entry.get("assayability") if (entry and dec == "included") else None
        if not allele_ok(a, kind):
            errors.append(f"allele-invalid: {rs} T1 cell {a!r}")
        elif dec == "included" and entry is not None and a != entry.get("effect_allele"):
            errors.append(f"allele-differs: {rs} T1 {a!r} != targets {entry.get('effect_allele')!r}")
    return _result(errors, len(t1_rows) + len(entries))


def check_build(header, t1_rows):
    errors = []
    if header.get("genome_build") != "GRCh37":
        errors.append(f"build-header: genome_build {header.get('genome_build')!r}")
    if header.get("strand") != "forward":
        errors.append(f"strand-header: strand {header.get('strand')!r}")
    for r in t1_rows:
        cell = r["build/strand"]
        base, _, flag = cell.partition(";")
        if r["decision"] == "excluded" and cell == "-":
            continue
        if base != "GRCh37/forward" or flag not in ("", "strand-ambiguous"):
            errors.append(f"build-cell: {r['rsID']} {cell!r}")
    return _result(errors, len(t1_rows))


def check_strand(t1_rows, entries):
    errors = []
    for r in t1_rows:
        flagged = r["build/strand"].partition(";")[2] == "strand-ambiguous"
        if flagged and r["decision"] in ("included", "reserve"):
            errors.append(f"ambiguous-kept: {r['rsID']} is {r['decision']} and strand-ambiguous")
        elif flagged and r["decision"] == "excluded" and r["reason code"] != "palindromic":
            errors.append(f"ambiguous-code: {r['rsID']} excluded with {r['reason code']!r}, not palindromic")
    for e in entries:
        if "strand" in e and e["strand"] != "forward":
            errors.append(f"entry-strand: {e.get('rsid')} strand {e['strand']!r}")
    return _result(errors, len(t1_rows) + len(entries))


def check_targets_shape(obj):
    errors = []
    if not isinstance(obj, dict):
        return _result(["shape: top level is not an object"], 0)
    if not isinstance(obj.get("_note"), str):
        errors.append("shape: _note missing")
    if obj.get("panel_version") != "0.1.0":
        errors.append(f"shape: panel_version {obj.get('panel_version')!r}")
    variants = obj.get("variants")
    if not isinstance(variants, list):
        return _result(errors + ["shape: variants is not a list"], 0)
    for i, v in enumerate(variants):
        if not isinstance(v, dict):
            errors.append(f"shape: variants[{i}] is not an object")
            continue
        for key in sorted(set(v) - TARGETS_ALLOWED_KEYS):
            errors.append(f"shape: variants[{i}] unknown key {key}")
        missing = [k for k in ("rsid", "category", "result_type", "effect_allele", "assayability") if k not in v]
        if missing:
            errors.append(f"shape: variants[{i}] lacks {missing}")
        if not re.fullmatch(r"rs\d+", str(v.get("rsid"))):
            errors.append(f"shape: variants[{i}] rsid {v.get('rsid')!r}")
    return _result(errors, len(variants))


def _marker_re(marker):
    body = re.escape(marker).replace(r"\ ", r"\s+")
    return re.compile(r"(?<![A-Za-z0-9-])" + body + r"(?![A-Za-z0-9-])", re.I)


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def check_no_unresolved_markers(t1_rows, entries):
    errors, rows = [], _live(t1_rows, "included", "reserve")
    scans = [(f"row {r['rsID']}", s) for r in rows for s in r.values()]
    scans += [(f"entry {e.get('rsid')}", s) for e in entries for s in _strings(e)]
    for where, text in scans:
        for marker in UNRESOLVED_MARKERS:
            if _marker_re(marker).search(text):
                errors.append(f"unresolved-marker: {where} contains {marker!r}")
    return _result(errors, len(rows) + len(entries))


def check_assayability(t1_rows):
    errors = []
    for r in t1_rows:
        rs, st, src = r["rsID"], r["assayability_status"], r["assayability_source"]
        if st not in ASSAY_STATUSES:
            errors.append(f"assay-status: {rs} {st!r}")
        elif st == "verified-from-public-manifest" and not (src.startswith("manifest:") and typed_id_ok(src)):
            errors.append(f"assay-source-missing: {rs} verified without a typed manifest id ({src!r})")
        elif st == "unknown-provisional" and src != "-":
            errors.append(f"assay-source-unexpected: {rs} unknown-provisional carries {src!r}")
    return _result(errors, len(t1_rows))


# --- ClinVar pair rule (G-1, R-RES, supporting group) ------------------------------
_ITEM_RE = re.compile(r"(\d+)=([ACGTID?])/(match|other-allele|other-condition|unmapped)/(P|B|U|RF|AP|CF)/([0-4])")


def significance_group(term):
    t = (term or "").strip().lower()
    if t.startswith("conflicting"):
        return "CF"
    if t.startswith("pathogenic") or t.startswith("likely pathogenic"):
        return "P"
    if t.startswith("benign") or t.startswith("likely benign"):
        return "B"
    if t.startswith("uncertain significance"):
        return "U"
    if t.startswith("risk factor") or t.startswith("risk allele"):
        return "RF"
    return "AP"


def parse_considered(cell, pair_allele):
    """Grammar G-1. Returns (items, errors); '-' parses to an empty list."""
    if cell == "-":
        return [], []
    if pair_allele not in ("A", "C", "G", "T", "I", "D"):
        return [], [f"pair-allele-invalid: {pair_allele!r}"]
    items, errors, seen = [], [], set()
    for raw in cell.split(";"):
        m = _ITEM_RE.fullmatch(raw)
        if not m:
            errors.append(f"item-malformed: {raw!r}")
            continue
        vid, letter, disp, grp, stars = m.groups()
        if vid in seen:
            errors.append(f"duplicate-vid: {vid}")
        seen.add(vid)
        if (letter == "?") != (disp == "unmapped"):
            errors.append(f"letter-disp-mismatch: {vid}")
        if disp == "match" and letter != pair_allele:
            errors.append(f"match-letter-not-pair-allele: {vid}")
        if disp == "other-condition" and letter != pair_allele:
            errors.append(f"other-condition-letter: {vid}")
        if disp == "other-allele" and (letter == pair_allele or letter == "?"):
            errors.append(f"other-allele-letter: {vid}")
        if (letter in ("I", "D") and pair_allele not in ("I", "D")) or \
                (letter in ("A", "C", "G", "T") and pair_allele not in ("A", "C", "G", "T")):
            errors.append(f"letter-class-mismatch: {vid}")
        items.append({"vid": vid, "letter": letter, "disp": disp, "grp": grp, "stars": int(stars)})
    return items, errors


def in_conflict(matched):
    g = {i["grp"] for i in matched}
    return "CF" in g or len(g & {"P", "B", "U"}) >= 2


def check_resolution(items, resolution):
    """Rule R-RES: the error list for a resolution cell (empty when valid or '-')."""
    if resolution == "-":
        return []
    m = re.fullmatch(r"clinvar:vcv:(\d+)", resolution)
    if not m:
        return ["resolution-wrong-type" if ":" in resolution else "resolution-not-typed"]
    matched = [i for i in items if i["disp"] == "match"]
    pick = next((i for i in matched if i["vid"] == m.group(1)), None)
    if pick is None:
        return ["resolution-not-matched"]
    if pick["grp"] != "P":
        return ["resolution-not-p"]
    if pick["stars"] < 3:
        return ["resolution-low-stars"]
    if not in_conflict(matched):
        return ["resolution-without-conflict"]
    if any(o["grp"] in ("B", "U") and o["stars"] >= pick["stars"] for o in matched if o is not pick):
        return ["resolution-contested"]
    return []


def supporting_group(groups, result_type):
    if "P" in groups:
        return "P"
    if result_type == "risk_association" and "RF" in groups:
        return "RF"
    return None


def evaluate_pair(row, result_type):
    """Returns (outcome, group, stars, errors); any grammar or R-RES error returns only errors."""
    if result_type not in ("carrier_status", "risk_association"):
        return None, None, None, [f"result-type: {result_type!r} has no ClinVar pair"]
    items, errors = parse_considered(row["considered records"], row["pair allele (fwd GRCh37)"])
    errors = errors + ([] if errors else check_resolution(items, row["resolution"]))
    if errors:
        return None, None, None, errors
    resolution = row["resolution"]
    matched = [i for i in items if i["disp"] == "match"]
    if not items:
        return "excluded:no-allele-condition-match", None, None, []
    if all(i["letter"] == "?" for i in items):
        return "excluded:allele-not-mappable", None, None, []
    if not matched:
        return "excluded:no-allele-condition-match", None, None, []
    if in_conflict(matched) and resolution == "-":
        return "excluded:conflicting-evidence", None, None, []
    if resolution != "-":
        pick = next(i for i in matched if i["vid"] == resolution.rsplit(":", 1)[1])
        group, stars = "P", pick["stars"]
    else:
        group = supporting_group({i["grp"] for i in matched}, result_type)
        if group is None:
            return "excluded:ineligible-significance", None, None, []
        stars = max(i["stars"] for i in matched if i["grp"] == group)
    if stars < 2:
        return "excluded:insufficient-review-status", group, stars, []
    return "eligible", group, stars, []


def check_pair_row(row, result_type, effect_allele=None):
    outcome, group, stars, errors = evaluate_pair(row, result_type)
    errors = list(errors)
    if errors:
        return errors
    items, _ = parse_considered(row["considered records"], row["pair allele (fwd GRCh37)"])
    ids = ";".join(i["vid"] for i in items if i["disp"] == "match") or "-"
    if row["matched record ids"] != ids:
        errors.append(f"row-matched-ids: {row['rsID']} claims {row['matched record ids']!r}, computed {ids!r}")
    if row["matched significance"] != (group or "-"):
        errors.append(f"row-significance: {row['rsID']} claims {row['matched significance']!r}, computed {group or '-'!r}")
    if row["stars"] != (str(stars) if stars is not None else "-"):
        errors.append(f"row-stars: {row['rsID']} claims {row['stars']!r}, computed {stars!r}")
    if row["pair outcome"] != outcome:
        errors.append(f"row-outcome: {row['rsID']} claims {row['pair outcome']!r}, computed {outcome!r}")
    if effect_allele is not None and row["pair allele (fwd GRCh37)"] != effect_allele:
        errors.append(f"pair-allele-differs: {row['rsID']} pair {row['pair allele (fwd GRCh37)']!r} != T1 {effect_allele!r}")
    return errors


def _inventory_ids(cell):
    return set(split_ids(cell))


def check_clinvar_table(t1_rows, t2_rows, t5_rows):
    errors, t1 = [], {r["rsID"]: r for r in t1_rows}
    inv = {r["rsID"]: r for r in t5_rows}
    seen = set()
    for row in t2_rows:
        rs = row["rsID"]
        if rs in seen:
            errors.append(f"t2-duplicate-rsid: {rs}")
        seen.add(rs)
    for row in t2_rows:
        rs = row["rsID"]
        base = t1.get(rs)
        if base is None:
            errors.append(f"t2-without-t1: {rs}")
            continue
        errors += check_pair_row(row, base["result type"], base["effect allele (fwd, GRCh37)"])
        if row["pair condition"] != base["label used in report"]:
            errors.append(f"pair-condition-differs: {rs} T2 {row['pair condition']!r} != T1 {base['label used in report']!r}")
        items, _ = parse_considered(row["considered records"], row["pair allele (fwd GRCh37)"])
        if rs not in inv:
            errors.append(f"inventory-missing: {rs} has no T5 row")
        elif {i["vid"] for i in items} != _inventory_ids(inv[rs]["ClinVar VariationIDs in pack (all assemblies)"]):
            errors.append(f"inventory-mismatch: {rs} considered ids differ from the pack inventory")
    return _result(errors, len(t2_rows))


# --- inheritance gate ----------------------------------------------------------------
def inheritance_ok(model, result_type, group):
    return (model, result_type, group) in INHERITANCE_OK


def check_inheritance_table(t1_rows, t3_rows):
    errors, t1 = [], {r["rsID"]: r for r in t1_rows}
    for row in t3_rows:
        rs, model = row["rsID"], row["model"]
        base = t1.get(rs)
        if base is None:
            errors.append(f"t3-without-t1: {rs}")
            continue
        if model not in MODELS:
            errors.append(f"model-invalid: {rs} {model!r}")
            continue
        kept = base["decision"] in ("included", "reserve")
        if model in ("UNRESOLVED", "AD"):
            want = "inheritance-unresolved" if model == "UNRESOLVED" else "inheritance-out-of-scope"
            if kept:
                errors.append(f"model-not-keepable: {rs} {model} is {base['decision']}")
            elif base["reason code"] != want:
                errors.append(f"model-reason: {rs} {model} needs code {want}, has {base['reason code']!r}")
            continue
        if kept and MODEL_RESULT_TYPES[model] != base["result type"]:
            errors.append(f"model-result-type: {rs} {model} cannot carry {base['result type']!r}")
        ids = split_ids(row["inheritance sources (typed ids)"])
        bad = [i for i in ids if not typed_id_ok(i)]
        errors.extend(f"source-untyped: {rs} {i!r}" for i in bad)
        if kept and model != "n/a":
            if not any(i.split(":")[0] in HEALTH_SOURCE_TYPES for i in ids if typed_id_ok(i)):
                errors.append(f"source-not-independent: {rs} has no genereviews, medgen, clingen or pmid source")
            one, two = row["one-copy meaning"], row["two-copy meaning"]
            if one in ("", "-") or two in ("", "-"):
                errors.append(f"copy-cell-empty: {rs}")
            if model == "AR" and not _word(one.lower(), "carrier"):
                errors.append(f"ar-one-copy-not-carrier: {rs}")
            if model in ("AD-IP", "SUSC") and (_word(one.lower(), "carrier") or _word(two.lower(), "carrier")):
                errors.append(f"carrier-word-on-{model}: {rs}")
    return _result(errors, len(t3_rows))


def check_health_rows(t1_rows, t2_rows, t3_rows):
    errors, t2 = [], {r["rsID"]: r for r in t2_rows}
    t3 = {r["rsID"]: r for r in t3_rows}
    rows = [r for r in _live(t1_rows, "included", "reserve") if r["category"] == "carrier"]
    for r in rows:
        rs, rt = r["rsID"], r["result type"]
        pair = t2.get(rs)
        if pair is None:
            errors.append(f"health-without-t2: {rs}")
            continue
        if pair["pair condition"] != r["label used in report"]:
            errors.append(f"health-pair-condition-differs: {rs} T2 {pair['pair condition']!r} != T1 {r['label used in report']!r}")
        if pair["pair allele (fwd GRCh37)"] != r["effect allele (fwd, GRCh37)"]:
            errors.append(f"health-pair-allele-differs: {rs} T2 {pair['pair allele (fwd GRCh37)']!r} != T1 {r['effect allele (fwd, GRCh37)']!r}")
        outcome, group, _, errs = evaluate_pair(pair, rt)
        if errs:
            errors.append(f"health-t2-invalid: {rs} {errs[0]}")
        elif outcome != "eligible":
            errors.append(f"health-not-eligible: {rs} computes {outcome}")
        else:
            model = t3.get(rs, {}).get("model")
            if rs not in t3:
                errors.append(f"health-without-t3: {rs}")
            elif not inheritance_ok(model, rt, group):
                errors.append(f"health-inheritance: {rs} ({model}, {rt}, {group}) is not allowed")
    return _result(errors, len(rows))


# --- allele mapping ------------------------------------------------------------------
def _placement_valid(p):
    if not isinstance(p, dict):
        return False
    return all(isinstance(p.get(k), str) and p.get(k) for k in ("chrom", "ref", "alt")) and \
        isinstance(p.get("pos"), int) and re.fullmatch(r"[ACGT]+", p["ref"]) is not None and \
        re.fullmatch(r"[ACGT]+", p["alt"]) is not None


def placement_kind(p):
    ref, alt = p["ref"], p["alt"]
    if len(ref) == 1 and len(alt) == 1:
        return "snv"
    if len(ref) > len(alt) >= 1 and ref.startswith(alt):
        return "deletion"
    if len(alt) > len(ref) >= 1 and alt.startswith(ref):
        return "insertion"
    return "complex"


def map_placement(rec, dbsnp):
    """(letter, reason): the forward GRCh37 letter of a ClinVar record against the dbSNP placement."""
    if isinstance(rec, dict) and "chrom" not in rec and rec.get("notation"):
        return "?", "notation-only"
    if not rec or not dbsnp:
        return "?", "no-grch37-placement"
    if not (_placement_valid(rec) and _placement_valid(dbsnp)):
        return "?", "malformed"
    kind = placement_kind(rec)
    if kind == "complex":
        return "?", "complex"
    if kind != placement_kind(dbsnp):
        return "?", "kind-mismatch"
    if (rec["chrom"], rec["pos"], rec["ref"]) != (dbsnp["chrom"], dbsnp["pos"], dbsnp["ref"]):
        return "?", "position-or-ref-mismatch"
    if kind == "snv":
        return rec["alt"], None
    if rec["alt"] != dbsnp["alt"]:
        return "?", "span-mismatch"
    return ("D" if kind == "deletion" else "I"), None


# --- replication (T4) ------------------------------------------------------------------
def trait_matches(reported, label, aliases):
    import evidence
    return evidence.norm_cond(reported) in evidence._condition_variants(label, aliases)


def _parse_p(cell):
    if cell == "-":
        return None, "p-missing"
    if not re.fullmatch(r"(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", cell):
        return None, "p-malformed"
    value = float(cell)
    return (value, None) if 0 < value <= 1 else (None, "p-malformed")


def row_kind(row):
    if re.fullmatch(r"GCST\d+", row["study accession"]):
        return "gwas"
    if row["study accession"] == "-" and re.fullmatch(r"\d+", row["PMID"]):
        return "functional"
    return None


def evaluate_replication(rows, effect_allele, label, aliases, pack_ids):
    """Returns (status, groups, per_row_drop_code). One implementation for fixtures and the real file."""
    drops, info = {}, {}
    for r in rows:
        rid, kind, p, code = r["row id"], row_kind(r), None, None
        if kind is None:
            code = "malformed-row"
        elif not trait_matches(r["trait (reported)"], label, aliases):
            code = "trait-mismatch"
        elif r["effect allele (fwd, GRCh37)"] != effect_allele:
            code = "allele-mismatch"
        elif r["orientation"] != "verified":
            code = "orientation-unverified"
        elif r["orientation source"] not in pack_ids or (kind == "functional" and f"pmid:{r['PMID']}" not in pack_ids):
            code = "evidence-not-in-pack"
        elif r["direction"] not in ("up", "down"):
            code = "direction-missing"
        elif kind == "gwas":
            p, code = _parse_p(r["p-value"])
        elif r["p-value"] != "-":
            code = "p-malformed"
        direction_eligible = code is None
        if code is None:
            if not re.fullmatch(r"[a-z0-9-]+", r["cohort id"]) or r["cohort id"] == "unknown":
                code = "cohort-unknown"
            elif r["cohort source"] not in pack_ids:
                code = "evidence-not-in-pack"
        drops[rid] = code
        info[rid] = {"kind": kind, "p": p, "dir": r["direction"], "row": r, "dir_ok": direction_eligible}
    eligible = [rid for rid, c in drops.items() if c is None]
    parent = {rid: rid for rid in eligible}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for a, b in itertools.combinations(eligible, 2):
        ra, rb = info[a]["row"], info[b]["row"]
        linked = (ra["PMID"] != "-" and ra["PMID"] == rb["PMID"]) or ra["cohort id"] == rb["cohort id"] \
            or b in split_ids(ra["overlap with"]) or a in split_ids(rb["overlap with"])
        if linked:
            union(a, b)
    clusters = {}
    for rid in eligible:
        clusters.setdefault(find(rid), []).append(rid)
    gwas_groups = sorted(sorted(c) for c in clusters.values() if any(info[r]["kind"] == "gwas" for r in c))
    fn_groups = sorted(sorted(c) for c in clusters.values() if all(info[r]["kind"] == "functional" for r in c))
    groups = gwas_groups + (fn_groups[:FN_GROUP_CAP] if gwas_groups else [])
    directions = {i["dir"] for i in info.values() if i["dir_ok"]}
    if {"up", "down"} <= directions:
        status = "conflicting-evidence"
    elif not groups:
        status = "no-counted-evidence"
    elif len(groups) < MIN_GROUPS:
        status = "single-study"
    elif not any(info[r]["kind"] == "gwas" and info[r]["p"] is not None and info[r]["p"] <= P_THRESHOLD
                 for r in eligible):
        status = "not-significant"
    else:
        status = "replicated"
    return status, groups, drops


def replication_exclusion_code(status, drops):
    if status == "replicated":
        return None
    if status in ("conflicting-evidence", "single-study"):
        return status
    if status == "not-significant":
        return "no-independent-confirmation"
    soft = ("orientation-unverified", "cohort-unknown", "evidence-not-in-pack")
    return "evidence-not-in-pack" if any(c in soft for c in drops.values()) else "no-independent-confirmation"


def check_t4_cells(rows):
    errors, ids = [], [r["row id"] for r in rows]
    for rid in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"row-id-duplicate: {rid}")
    for r in rows:
        rid = r["row id"]
        if r["orientation"] not in ("verified", "unverified"):
            errors.append(f"t4-orientation: {rid} {r['orientation']!r}")
        if r["direction"] not in ("up", "down", "-"):
            errors.append(f"t4-direction: {rid} {r['direction']!r}")
        for col in ("orientation source", "cohort source"):
            if r[col] != "-" and not typed_id_ok(r[col]):
                errors.append(f"t4-source: {rid} {col} {r[col]!r}")
        if not (r["cohort id"] == "unknown" or re.fullmatch(r"[a-z0-9-]+", r["cohort id"])):
            errors.append(f"t4-cohort: {rid} {r['cohort id']!r}")
        for o in split_ids(r["overlap with"]):
            if o not in ids:
                errors.append(f"t4-overlap: {rid} names unknown row {o!r}")
        if not (r["counted"] == "yes" or re.fullmatch(r"no:[a-z-]+", r["counted"])):
            errors.append(f"t4-counted: {rid} {r['counted']!r}")
    return errors


def check_trait_table(t1_rows, t4_rows, aliases, pack_ids):
    errors, t1 = [], {r["rsID"]: r for r in t1_rows}
    errors += check_t4_cells(t4_rows)
    by_rs = {}
    for r in t4_rows:
        by_rs.setdefault(r["rsID"], []).append(r)
    for rs in by_rs:
        if rs not in t1:
            errors.append(f"t4-without-t1: {rs}")
    live = [r for r in _live(t1_rows, "included", "reserve") if r["result type"] == "trait"]
    for base in t1_rows:
        rows = by_rs.get(base["rsID"], [])
        if not rows:
            continue
        status, _, drops = evaluate_replication(rows, base["effect allele (fwd, GRCh37)"],
                                                base["label used in report"], aliases, pack_ids)
        for r in rows:
            want = "yes" if drops[r["row id"]] is None else f"no:{drops[r['row id']]}"
            if r["counted"] != want:
                errors.append(f"t4-counted-claim: {r['row id']} claims {r['counted']!r}, computed {want!r}")
        if base in live and status != "replicated":
            errors.append(f"trait-not-replicated: {base['rsID']} is {status}")
    for base in live:
        if not by_rs.get(base["rsID"]):
            errors.append(f"trait-without-t4: {base['rsID']} has no evidence rows")
    return _result(errors, len(t4_rows) + len(live))


# --- document-level checks ------------------------------------------------------------------
def check_header_exact(tables, header):
    try:
        find_table(tables, header)
    except TableError as exc:
        return [f"header: {exc}"]
    return []


def check_status_line(text, n_rows):
    lines = [ln for ln in text.splitlines() if ln.startswith("Status:")]
    if len(lines) != 1:
        return [f"status: expected exactly one Status line, found {len(lines)}"]
    line = lines[0]
    if n_rows == 0:
        return [] if line == "Status: method-only" else [f"status: zero rows but {line!r}"]
    m = re.fullmatch(r"Status: curated, (\d+) rows", line)
    if not m:
        return [f"status: {n_rows} rows but {line!r}"]
    return [] if int(m.group(1)) == n_rows else [f"status: line says {m.group(1)} rows, table has {n_rows}"]


def check_rule_paragraph(text, title, words):
    body = section_body(text, title)
    if body is None:
        return [f"rule: heading {title!r} missing"]
    return [f"rule: {title!r} lacks the word {w!r}" for w in words if not _word(body, w)]


def check_reason_code_list(text):
    body = section_body(text, "Reason codes")
    if body is None:
        return ["reason-codes: heading 'Reason codes' missing"]
    listed = set(re.findall(r"`([a-z0-9-]+)`", body)) - set(RETIRED_REASON_CODES)
    errors = [f"reason-codes: doc lacks {c!r}" for c in REASON_CODES if c not in listed]
    errors += [f"reason-codes: doc lists unknown {c!r}" for c in sorted(listed - set(REASON_CODES))]
    for line in body.splitlines():
        for old in RETIRED_REASON_CODES:
            if old in line and "retired" not in line.lower():
                errors.append(f"reason-codes: retired code {old!r} is not marked retired")
    return errors


def check_unknown_provisional_disclosed(t1_rows, text):
    if not any(r["assayability_status"] == "unknown-provisional" for r in t1_rows):
        return []
    body = section_body(text, "Limitations")
    if body is None:
        return ["disclosure: Limitations section missing"]
    return [f"disclosure: Limitations lacks {p!r}" for p in ("array presence", "not verified", "aggregate coverage")
            if p not in body]


def check_provenance_block(text, n_rows):
    if n_rows == 0:
        return []
    body = section_body(text, "Provenance block")
    if body is None:
        return ["provenance-block: section missing"]
    errors = []
    if "PLACEHOLDER" in body:
        errors.append("provenance-block: placeholders remain")
    if not re.search(r"\b[0-9a-f]{64}\b", body):
        errors.append("provenance-block: no sha256 value")
    if not re.search(r"\b\d{4}-\d{2}-\d{2}\b", body):
        errors.append("provenance-block: no ISO date")
    return errors


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def check_wording_generic(text):
    import guard
    errors = [f"wording: line {line} looks like {name}" for line, name in guard.scan_text_for_secrets(text)]
    if _EMAIL_RE.search(text):
        errors.append("wording: contains an email address")
    plain, hashed = guard.load_denylist(ROOT)
    errors += [f"wording: line {line} has an owner-specific term"
               for line, _ in guard.scan_text_for_denylist(text, plain, hashed)]
    return errors


# Independent literal oracle for the supporting-group table (15 non-conflicting group sets).
# Each key is a group set; the value is (carrier_status S, risk_association S); None = undefined.
ORACLE_NONCONFLICT = {
    frozenset({"P"}): ("P", "P"), frozenset({"P", "RF"}): ("P", "P"),
    frozenset({"P", "AP"}): ("P", "P"), frozenset({"P", "RF", "AP"}): ("P", "P"),
    frozenset({"RF"}): (None, "RF"), frozenset({"RF", "AP"}): (None, "RF"),
    frozenset({"AP"}): (None, None),
    frozenset({"B"}): (None, None), frozenset({"B", "AP"}): (None, None),
    frozenset({"U"}): (None, None), frozenset({"U", "AP"}): (None, None),
    frozenset({"B", "RF"}): (None, "RF"), frozenset({"B", "RF", "AP"}): (None, "RF"),
    frozenset({"U", "RF"}): (None, "RF"), frozenset({"U", "RF", "AP"}): (None, "RF"),
}


def check_required_headings(text):
    titles = {t for _, t, _ in sections(text)}
    return [f"headings: {h!r} missing" for h in DOC_REQUIRED_HEADINGS if h not in titles]


# Full-clause pins for rules whose polarity matters. Phrases are compared after
# collapsing whitespace (the document wraps lines) and ignoring case.
REPORT_SAFETY_PRESENT = (
    "the entry can be reported without implying a diagnosis or an absolute risk, "
    "and its only honest wording is not a recommendation",
)
REPORT_SAFETY_ABSENT = ("cannot be reported", "can not be reported", "wording is a recommendation")
FUNCTIONAL_RULE_PRESENT = ("only when at least one gwas group is present",)
PAIR_CONDITION_RULE_PRESENT = (
    "the t2 `pair condition` cell must equal the t1 `label used in report` exactly",
)
EVIDENCE_NOT_IN_PACK_PRESENT = (
    "the code `evidence-not-in-pack` applies only when the status is `no-counted-evidence`",
)
TARGETS_KEYS_RULE_PRESENT = (
    "an entry has exactly these keys",
    "the evidence tier is derived by the build and never written in the targets file",
    "placement fields come from the dbsnp map supplied at build time",
)
CURATOR_JUDGMENTS_PRESENT = (
    "are curator judgments that no checker derives",
    "the t1 `rationale` cell states the basis for each",
    "the data review reassesses all three independently for every row",
    "an ancestry exception cites an owner decision id in the `limitations` cell",
)


def _flat(text):
    return " ".join(text.split()).lower()


def check_doc_clause(text, title, present, absent=()):
    """Errors unless section `title` holds every phrase in `present`; a phrase in `absent`
    is an error anywhere in the whole document (title None checks only `absent`)."""
    errors = []
    if title is not None:
        body = section_body(text, title)
        if body is None:
            return [f"clause: heading {title!r} missing"]
        flat = _flat(body)
        errors += [f"clause: {title!r} lacks {p!r}" for p in present if p.lower() not in flat]
    whole = _flat(text)
    errors += [f"clause: document contains {a!r}" for a in absent if a.lower() in whole]
    return errors


def check_row_matches_entries(t1_rows, entries):
    by_id, errors = {e.get("rsid"): e for e in entries}, []
    rows = _live(t1_rows, "included")
    for r in rows:
        e = by_id.get(r["rsID"])
        if e is None:
            continue
        for cell, key in (
                ("result type", "result_type"),
                ("category", "category"),
                ("effect allele (fwd, GRCh37)", "effect_allele"),
                ("label used in report", "condition"),
                ("gene", "gene"),
        ):
            if r[cell] != e.get(key):
                errors.append(f"row-field-differs: {r['rsID']} {cell} {r[cell]!r} != targets {e.get(key)!r}")
    return _result(errors, len(rows))


# =============================================================================
# Invented fixtures (rsIDs rs9000001.., VariationIDs 9001001..; nothing real).
# =============================================================================
def _t1(**kw):
    base = {
        "rsID": "rs9000001", "gene": "GENEA", "chrom (GRCh37)": "1",
        "label used in report": "Example trait", "result type": "trait", "category": "trait",
        "effect allele (fwd, GRCh37)": "A",
        "direction/meaning": "more copies of the effect allele, higher level",
        "build/strand": "GRCh37/forward", "assayability_status": "unknown-provisional",
        "assayability_source": "-", "sources (typed ids)": "dbsnp:rs9000001;gwas:GCST9003001",
        "retrieved (UTC date)": "2026-01-31", "rationale": "invented rationale",
        "limitations": "invented limitation", "decision": "included", "reason code": "-",
    }
    for k, v in kw.items():
        base[SHORT[k]] = v
    return base


def _t2(rs, allele, considered, ids, sig, stars, outcome, resolution="-", cond="Example condition one"):
    return {"rsID": rs, "pair allele (fwd GRCh37)": allele, "pair condition": cond,
            "matched record ids": ids, "matched significance": sig,
            "matched review status": "free text", "stars": stars, "considered records": considered,
            "resolution": resolution, "pair outcome": outcome}


def _t3(rs, model, one, two, sources):
    return {"rsID": rs, "model": model, "one-copy meaning": one, "two-copy meaning": two,
            "inheritance sources (typed ids)": sources}


def _t4(rid, acc, pmid, allele, orient, osrc, direction, p, cohort, csrc, overlap="-",
        counted="yes", rs="rs9000001", trait="Example trait"):
    return {"rsID": rs, "row id": rid, "study accession": acc, "PMID": pmid, "trait (reported)": trait,
            "effect allele (fwd, GRCh37)": allele, "orientation": orient, "orientation source": osrc,
            "direction": direction, "p-value": p, "sample ancestry": "invented", "sample size": "1000",
            "cohort id": cohort, "cohort source": csrc, "overlap with": overlap, "counted": counted}


def _t5(rs, ids, index):
    return {"rsID": rs, "ClinVar VariationIDs in pack (all assemblies)": ids, "pack file index id": index}


def _gwas(rid, n, cohort, p, allele="A", direction="up", rs="rs9000001", trait="Example trait", **kw):
    return _t4(rid, f"GCST{n}", n, allele, kw.pop("orient", "verified"), kw.pop("osrc", f"pmid:{n}"),
               direction, p, cohort, kw.pop("csrc", f"gwas:GCST{n}"), rs=rs, trait=trait, **kw)


def _pack_ids(t4_rows):
    ids = set()
    for r in t4_rows:
        ids.update(i for i in (r["orientation source"], r["cohort source"], f"pmid:{r['PMID']}") if i != "-")
    return ids


def good_world():
    t4 = [_gwas("r1a", "9003001", "cohort-a", "3e-9"), _gwas("r1b", "9003002", "cohort-b", "1e-6"),
          _gwas("r4a", "9003011", "cohort-c", "2e-9", allele="C", rs="rs9000004", trait="Example trait two"),
          _gwas("r4b", "9003012", "cohort-d", "1e-7", allele="C", rs="rs9000004", trait="Example trait two")]
    return {
        "header": {"genome_build": "GRCh37", "strand": "forward"},
        "t1": [
            _t1(),
            _t1(rsid="rs9000002", gene="GENEB", chrom="7", label="Example condition one", rt="carrier_status",
                cat="carrier", allele="G", src="dbsnp:rs9000002;clinvar:vcv:9001001;genereviews:NBK900001"),
            _t1(rsid="rs9000003", gene="GENEC", chrom="22", label="Example condition two", rt="risk_association",
                cat="carrier", allele="D", src="dbsnp:rs9000003;clinvar:vcv:9001101;pmid:9004001"),
            _t1(rsid="rs9000004", chrom="5", label="Example trait two", allele="C", dec="reserve",
                src="dbsnp:rs9000004;gwas:GCST9003011"),
            _t1(rsid="rs9000005", chrom="X", label="Example condition three", rt="carrier_status", cat="carrier",
                allele="-", bs="-", src="-", date="-", dec="excluded", code="non-autosomal-out-of-scope"),
        ],
        "entries": [
            {"rsid": "rs9000001", "gene": "GENEA", "condition": "Example trait",
             "assayability": "snp", "effect_allele": "A", "category": "trait", "result_type": "trait"},
            {"rsid": "rs9000002", "gene": "GENEB", "condition": "Example condition one",
             "assayability": "snp", "effect_allele": "G", "category": "carrier", "result_type": "carrier_status"},
            {"rsid": "rs9000003", "gene": "GENEC", "condition": "Example condition two",
             "assayability": "indel", "effect_allele": "D", "category": "carrier", "result_type": "risk_association"},
        ],
        "t2": [
            _t2("rs9000002", "G", "9001001=G/match/P/2;9001002=A/other-allele/B/1", "9001001", "P", "2", "eligible"),
            _t2("rs9000003", "D", "9001101=D/match/RF/2", "9001101", "RF", "2", "eligible",
                cond="Example condition two"),
        ],
        "t3": [
            _t3("rs9000002", "AR", "one copy: carrier of the invented condition", "two copies: invented wording",
                "genereviews:NBK900001"),
            _t3("rs9000003", "AD-IP", "one copy: increased association", "two copies: further increased association",
                "pmid:9004001"),
        ],
        "t4": t4,
        "t5": [_t5("rs9000002", "9001001;9001002", "manifest:idx-1"), _t5("rs9000003", "9001101", "manifest:idx-1")],
        "aliases": {},
        "pack_ids": _pack_ids(t4),
    }


def _row(w, rs):
    return next(r for r in w["t1"] if r["rsID"] == rs)


def _clean(res, label):
    _require(f"{label}: unexpected errors {list(res)}", not res)


def _has(res, code, label):
    _require(f"{label}: expected an error containing {code!r}, got {list(res)}", any(code in e for e in res))


def _syn(attempt, name, check, rejects):
    """Register R1B.syn_<name>_accepts and one R1B.syn_<name>_rejects_<defect> per defect."""
    def accepts():
        res = check(good_world())
        _clean(res, name)
        _require(f"{name}: accepting fixture checked {res.rows_checked} rows", res.rows_checked >= 1)
        return True
    attempt(f"R1B.syn_{name}_accepts", accepts)
    for defect, mutate, code in rejects:
        def rejecting(mutate=mutate, code=code, defect=defect):
            w = good_world()
            mutate(w)
            _has(check(w), code, f"{name}/{defect}")
            return True
        attempt(f"R1B.syn_{name}_rejects_{defect}", rejecting)


def _set_row(rs, **kw):
    def mutate(w):
        _row(w, rs).update({SHORT[k]: v for k, v in kw.items()})
    return mutate


def _set_entry(rs, **kw):
    def mutate(w):
        next(e for e in w["entries"] if e["rsid"] == rs).update(kw)
    return mutate


def _both(*mutators):
    def mutate(w):
        for m in mutators:
            m(w)
    return mutate


# =============================================================================
# Invariant checkers on invented fixtures (r41 section 4.2).
# =============================================================================
def _run_invariants(attempt):
    _syn(attempt, "bijection", lambda w: check_bijection(w["t1"], w["entries"]), [
        ("entry_without_row", lambda w: w["t1"].remove(_row(w, "rs9000001")), "entry-without-row"),
        ("row_without_entry", lambda w: w["entries"].pop(0), "row-without-entry"),
        ("same_count_different_ids", _set_entry("rs9000001", rsid="rs9000099"), "entry-without-row"),
    ])
    _syn(attempt, "unique_rsids", lambda w: check_unique_rsids(w["t1"], w["entries"]), [
        ("duplicate_in_t1", lambda w: w["t1"].append(dict(_row(w, "rs9000004"))), "duplicate-rsid"),
        ("duplicate_in_targets", lambda w: w["entries"].append(dict(w["entries"][0])), "duplicate-rsid"),
        ("included_and_excluded", lambda w: w["t1"].append(_t1(dec="excluded", code="single-study")),
         "duplicate-rsid"),
    ])
    _syn(attempt, "decisions", lambda w: check_decisions(w["t1"]), [
        ("excluded_without_reason", _set_row("rs9000005", code="-"), "reason-missing"),
        ("excluded_unknown_code", _set_row("rs9000005", code="made-up-code"), "reason-unknown"),
        ("included_with_code", _set_row("rs9000001", code="single-study"), "reason-on-kept-row"),
        ("decision_outside_vocabulary", _set_row("rs9000001", dec="maybe"), "decision-invalid"),
        ("retired_x_linked_code", _set_row("rs9000005", code="x-linked-out-of-scope"), "reason-retired"),
    ])
    _syn(attempt, "provenance", lambda w: check_provenance(w["t1"]), [
        ("date_month_13", _set_row("rs9000001", date="2026-13-01"), "date-invalid"),
        ("date_slashes", _set_row("rs9000001", date="31/01/2026"), "date-invalid"),
        ("date_empty", _set_row("rs9000001", date=""), "date-invalid"),
        ("id_without_type", _set_row("rs9000001", src="rs9000001"), "typed-id-invalid"),
        ("id_unknown_type", _set_row("rs9000001", src="foo:123"), "typed-id-invalid"),
        ("no_id", _set_row("rs9000001", src="-"), "sources-missing"),
        ("reserve_undated", _set_row("rs9000004", date="-"), "date-invalid"),
    ])
    _syn(attempt, "reserves_not_in_targets", lambda w: check_reserves_not_in_targets(w["t1"], w["entries"]), [
        ("reserve_in_targets", lambda w: w["entries"].append(
            {"rsid": "rs9000004", "assayability": "snp", "effect_allele": "C", "category": "trait",
             "result_type": "trait"}), "reserve-in-targets"),
    ])
    _syn(attempt, "effect_alleles", lambda w: check_effect_alleles(w["t1"], w["entries"]), [
        ("snp_with_indel_letter", _both(_set_entry("rs9000001", effect_allele="D"), _set_row("rs9000001", allele="D")),
         "allele-invalid"),
        ("indel_with_snp_letter", _both(_set_entry("rs9000003", effect_allele="A"), _set_row("rs9000003", allele="A")),
         "allele-invalid"),
        ("letter_n", _both(_set_entry("rs9000001", effect_allele="N"), _set_row("rs9000001", allele="N")),
         "allele-invalid"),
        ("two_letters", _both(_set_entry("rs9000001", effect_allele="AG"), _set_row("rs9000001", allele="AG")),
         "allele-invalid"),
        ("empty", _both(_set_entry("rs9000001", effect_allele=""), _set_row("rs9000001", allele="")),
         "allele-invalid"),
        ("t1_differs_from_targets", _set_row("rs9000002", allele="C"), "allele-differs"),
        ("reserve_bad_letter", _set_row("rs9000004", allele="N"), "allele-invalid"),
    ])
    _syn(attempt, "build", lambda w: check_build(w["header"], w["t1"]), [
        ("header_grch38", lambda w: w["header"].update(genome_build="GRCh38"), "build-header"),
        ("header_reverse_strand", lambda w: w["header"].update(strand="reverse"), "strand-header"),
        ("row_grch38", _set_row("rs9000001", bs="GRCh38/forward"), "build-cell"),
        ("header_key_missing", lambda w: w["header"].pop("genome_build"), "build-header"),
        ("strand_key_missing", lambda w: w["header"].pop("strand"), "strand-header"),
    ])
    _syn(attempt, "strand", lambda w: check_strand(w["t1"], w["entries"]), [
        ("included_flagged", _set_row("rs9000001", bs="GRCh37/forward;strand-ambiguous"), "ambiguous-kept"),
        ("reserve_flagged", _set_row("rs9000004", bs="GRCh37/forward;strand-ambiguous"), "ambiguous-kept"),
        ("excluded_flag_without_palindromic", _set_row("rs9000005", bs="GRCh37/forward;strand-ambiguous"),
         "ambiguous-code"),
        ("entry_strand_ambiguous", _set_entry("rs9000001", strand="ambiguous"), "entry-strand"),
    ])

    def strand_excluded_palindromic_ok():
        w = good_world()
        _set_row("rs9000005", bs="GRCh37/forward;strand-ambiguous", code="palindromic")(w)
        _clean(check_strand(w["t1"], w["entries"]), "strand/excluded-palindromic")
        return True
    attempt("R1B.syn_strand_accepts_excluded_palindromic_flag", strand_excluded_palindromic_ok)

    _syn(attempt, "chromosomes", lambda w: check_chromosomes(w["t1"], w["entries"]), [
        ("reserve_on_mt", _set_row("rs9000004", chrom="MT"), "non-autosomal-kept"),
        ("malformed_token", _set_row("rs9000001", chrom="chr1"), "chrom-malformed"),
        ("entry_on_x", _set_entry("rs9000001", chromosome="X"), "entry-chrom-not-autosomal"),
    ])
    _syn(attempt, "pairs", lambda w: check_pairs(w["entries"]), [
        ("trait_with_carrier_status", _set_entry("rs9000001", result_type="carrier_status"), "pair-invalid"),
        ("carrier_with_trait", _set_entry("rs9000002", result_type="trait"), "pair-invalid"),
    ])
    _syn(attempt, "unresolved_markers", lambda w: check_no_unresolved_markers(w["t1"], w["entries"]), [
        ("marker_in_entry", _set_entry("rs9000002", condition="Example condition TBD"), "unresolved-marker"),
        ("marker_in_included_row", _set_row("rs9000001", why="to verify later"), "unresolved-marker"),
        ("marker_in_reserve_row", _set_row("rs9000004", lim="TODO"), "unresolved-marker"),
        ("marker_unverified_source", _set_row("rs9000001", src="unverified-source"), "unresolved-marker"),
        ("marker_case_insensitive", _set_row("rs9000001", why="Fixme soon"), "unresolved-marker"),
    ])

    def unresolved_whole_token_only():
        w = good_world()
        _set_row("rs9000001", why="tbdx and to verified and unverified-sources and FIXMEs")(w)
        _set_row("rs9000005", why="to verify")(w)
        _clean(check_no_unresolved_markers(w["t1"], w["entries"]), "markers/whole-token")
        return True
    attempt("R1B.syn_unresolved_markers_whole_token_and_excluded_allowed", unresolved_whole_token_only)

    _syn(attempt, "health_rows", lambda w: check_health_rows(w["t1"], w["t2"], w["t3"]), [
        ("included_without_t2", lambda w: w["t2"].pop(0), "health-without-t2"),
        ("t2_excluded", lambda w: w["t2"][0].update(
            {"considered records": "9001001=G/match/P/2;9001002=G/match/B/1"}), "health-not-eligible"),
        ("t2_group_model_mismatch", lambda w: w["t3"][0].update({"model": "AD-IP"}), "health-inheritance"),
        ("reserve_without_t2", lambda w: w["t1"].append(
            _t1(rsid="rs9000006", dec="reserve", rt="carrier_status", cat="carrier", allele="G")), "health-without-t2"),
        ("included_without_t3", lambda w: w["t3"].pop(0), "health-without-t3"),
    ])

    def health_rows_require_eligible_pair():
        for defect, mutate, code in (
                ("no T2 row", lambda w: w["t2"].pop(0), "health-without-t2"),
                ("excluded T2", lambda w: w["t2"][0].update(
                    {"considered records": "9001001=G/match/B/2"}), "health-not-eligible"),
                ("model mismatch", lambda w: w["t3"][1].update({"model": "AR"}), "health-inheritance")):
            w = good_world()
            mutate(w)
            _has(check_health_rows(w["t1"], w["t2"], w["t3"]), code, f"health/{defect}")
        return True
    attempt("R1B.syn_health_rows_require_eligible_pair", health_rows_require_eligible_pair)

    _syn(attempt, "row_matches_targets", lambda w: check_row_matches_entries(w["t1"], w["entries"]), [
        ("result_type_differs", _set_row("rs9000002", rt="risk_association"), "row-field-differs"),
        ("category_differs", _set_row("rs9000001", cat="carrier"), "row-field-differs"),
        ("allele_differs", _set_row("rs9000003", allele="I"), "row-field-differs"),
    ])
    _syn(attempt, "targets_shape", lambda w: check_targets_shape(
        {"_note": "x", "panel_version": "0.1.0", "genome_build": "GRCh37", "strand": "forward",
         "variants": w["entries"]}), [
        ("entry_missing_field", lambda w: w["entries"][0].pop("effect_allele"), "shape"),
        ("entry_bad_rsid", _set_entry("rs9000001", rsid="9000001"), "shape"),
    ])

    def targets_shape_top_level():
        base = {"_note": "x", "panel_version": "0.1.0", "variants": []}
        _clean(check_targets_shape(base), "shape/empty")
        for defect, obj in (("not an object", []), ("wrong version", dict(base, panel_version="0.2.0")),
                            ("variants not a list", dict(base, variants={})), ("no note", {"panel_version": "0.1.0", "variants": []})):
            _has(check_targets_shape(obj), "shape", f"shape/{defect}")
        return True
    attempt("R1B.syn_targets_shape_top_level", targets_shape_top_level)

    # --- AUTO-1 (r39 1.5) -----------------------------------------------------
    def chrom_token_truth_table():
        for n in range(1, 23):
            _require(f"{n} must be autosomal", chrom_class(str(n)) == "autosomal")
        for tok in ("X", "Y", "PAR", "MT"):
            _require(f"{tok} must be non_autosomal", chrom_class(tok) == "non_autosomal")
        for tok in ("23", "24", "25", "26", "0", "01", "M", "XY", "chr1", "x", " 1", "1 ", None, "", 1, "MT "):
            _require(f"{tok!r} must be malformed", chrom_class(tok) == "malformed")
        return True
    attempt("R1B.chrom_token_truth_table", chrom_token_truth_table)

    def autosomal_only_included_and_reserve():
        for tok in ("X", "Y", "PAR", "MT"):
            for dec in ("included", "reserve"):
                res = check_chromosomes([_t1(chrom=tok, dec=dec)], [])
                _has(res, "non-autosomal-kept", f"{tok}/{dec}")
        res = check_chromosomes([_t1(chrom="7")], [])
        _clean(res, "chrom 7")
        _require("chrom 7 checked no rows", res.rows_checked >= 1)
        return True
    attempt("R1B.autosomal_only_included_and_reserve", autosomal_only_included_and_reserve)

    def non_autosomal_rows_excluded_with_code():
        ok = check_chromosomes([_t1(chrom="X", dec="excluded", code="non-autosomal-out-of-scope")], [])
        _clean(ok, "X excluded with code")
        for code in ("single-study", "-", "x-linked-out-of-scope"):
            _has(check_chromosomes([_t1(chrom="Y", dec="excluded", code=code)], []), "non-autosomal-code",
                 f"code {code!r}")
        return True
    attempt("R1B.non_autosomal_rows_excluded_with_code", non_autosomal_rows_excluded_with_code)

    def malformed_chrom_is_error():
        for tok in ("23", "0", "01", "M", "XY", "chr1", "x", " 1", "", None):
            for dec, code in (("included", "-"), ("excluded", "non-autosomal-out-of-scope")):
                res = check_chromosomes([_t1(rsid="rs9000042", chrom=tok, dec=dec, code=code)], [])
                _has(res, "chrom-malformed", f"{tok!r}/{dec}")
                _has(res, "rs9000042", f"{tok!r}/{dec} names the row")
        return True
    attempt("R1B.malformed_chrom_is_error", malformed_chrom_is_error)

    # --- pair table (r31 2.5) ----------------------------------------------------------
    def pair_table_accepts_exactly_three():
        values_c = ["carrier", "trait", None, "", "Carrier", "CARRIER", "other"]
        values_r = ["trait", "carrier_status", "risk_association", None, "", "Trait", "carrier", "other"]
        accepted = {(c, r) for c in values_c for r in values_r if pair_ok(c, r)}
        want = {("trait", "trait"), ("carrier", "carrier_status"), ("carrier", "risk_association")}
        _require(f"accepted pairs {sorted(accepted, key=str)}", accepted == want)
        _require("expected exactly three accepted pairs", len(accepted) == 3)
        return True
    attempt("R1B.pair_table_accepts_exactly_three", pair_table_accepts_exactly_three)

    def pair_table_rejects_every_other_pair():
        rejects = [("trait", "carrier_status"), ("trait", "risk_association"), ("carrier", "trait"),
                   (None, "trait"), ("", "trait"), ("trait", None), ("carrier", ""), ("Trait", "trait"),
                   ("carrier", "Carrier_Status"), ("other", "trait"), ("trait", "other")]
        entries = [{"rsid": f"rs90001{i:02d}", "category": c, "result_type": r} for i, (c, r) in enumerate(rejects)]
        res = check_pairs(entries)
        for e in entries:
            _has(res, e["rsid"], f"pair {e['category']!r}/{e['result_type']!r}")
        _require("one error per rejected pair", len(res) == len(rejects))
        return True
    attempt("R1B.pair_table_rejects_every_other_pair", pair_table_rejects_every_other_pair)

    # --- table parser --------------------------------------------------------------------
    def table_parser_fails_closed():
        good = "| a | b |\n|---|---|\n| 1 | 2 |\n"
        tables = parse_tables(good)
        _require("well-formed table not parsed", tables == [{"header": ["a", "b"], "rows": [{"a": "1", "b": "2"}]}])
        zero = parse_tables("| a | b |\n|---|---|\n")
        _require("zero-row table must parse with no rows", zero[0]["rows"] == [])
        bad = {
            "wrong separator": "| a | b |\n| x | y |\n| 1 | 2 |\n",
            "separator width": "| a | b |\n|---|\n| 1 | 2 |\n",
            "duplicate header": "| a | a |\n|---|---|\n| 1 | 2 |\n",
            "ragged row": "| a | b |\n|---|---|\n| 1 |\n",
            "no separator": "| a | b |\n",
            "repeated separator": "| a | b |\n|---|---|\n| 1 | 2 |\n|---|---|\n",
        }
        for name, text in bad.items():
            try:
                got = parse_tables(text)
            except TableError:
                continue
            raise AssertionError(f"{name}: returned {got!r} instead of raising")
        try:
            find_table(parse_tables(good), ["a", "c"])
        except TableError:
            pass
        else:
            raise AssertionError("a missing table must raise, not return an empty row list")
        try:
            find_table(parse_tables(good + "\n" + good), ["a", "b"])
        except TableError:
            pass
        else:
            raise AssertionError("a duplicated table must raise")
        fenced = parse_tables("```\n| a | b |\n| junk\n```\n" + good)
        _require("tables inside code fences must be ignored", len(fenced) == 1)
        return True
    attempt("R1B.table_parser_fails_closed", table_parser_fails_closed)

    # --- assayability (alternative A) ---------------------------------------------------------
    _syn(attempt, "assayability", lambda w: check_assayability(w["t1"]), [
        ("status_outside_vocabulary", _set_row("rs9000001", astat="verified"), "assay-status"),
        ("verified_without_source", _set_row("rs9000001", astat="verified-from-public-manifest"),
         "assay-source-missing"),
        ("verified_with_untyped_source", _set_row("rs9000001", astat="verified-from-public-manifest", asrc="m-1"),
         "assay-source-missing"),
        ("provisional_with_source", _set_row("rs9000001", asrc="manifest:m-1"), "assay-source-unexpected"),
    ])

    def assayability_status_valid():
        w = good_world()
        _set_row("rs9000001", astat="verified-from-public-manifest", asrc="manifest:m-1")(w)
        _clean(check_assayability(w["t1"]), "verified with a manifest id")
        for st in ASSAY_STATUSES:
            _require(f"{st} must be in the vocabulary", st in ASSAY_STATUSES)
        _has(check_assayability([_t1(astat="")]), "assay-status", "empty status")
        return True
    attempt("R1B.assayability_status_valid", assayability_status_valid)

    def verified_assayability_requires_manifest_source():
        for src in ("-", "", "pmid:1", "manifest:"):
            _has(check_assayability([_t1(astat="verified-from-public-manifest", asrc=src)]),
                 "assay-source-missing", f"verified/{src!r}")
        _has(check_assayability([_t1(astat="unknown-provisional", asrc="manifest:m-1")]),
             "assay-source-unexpected", "provisional with source")
        return True
    attempt("R1B.verified_assayability_requires_manifest_source", verified_assayability_requires_manifest_source)

    def unknown_provisional_disclosed_in_doc():
        full = "# Limitations\n\narray presence is not verified; adequacy is the owner's aggregate coverage decision.\n"
        rows = [_t1()]
        _clean(check_unknown_provisional_disclosed(rows, full), "disclosed")
        for missing in ("array presence", "not verified", "aggregate coverage"):
            _has(check_unknown_provisional_disclosed(rows, full.replace(missing, "x")), "disclosure", missing)
        _has(check_unknown_provisional_disclosed(rows, "# Other\n\ntext\n"), "disclosure", "no section")
        verified = [_t1(astat="verified-from-public-manifest", asrc="manifest:m-1")]
        _clean(check_unknown_provisional_disclosed(verified, "# Other\n"), "all verified needs no disclosure")
        return True
    attempt("R1B.unknown_provisional_disclosed_in_doc", unknown_provisional_disclosed_in_doc)


# =============================================================================
# ClinVar pair rule: grammar G-1, rule R-RES, supporting group (r41 sections 1-2).
# =============================================================================
def _pair(considered, resolution="-", allele="A"):
    return {"rsID": "rs9000001", "pair allele (fwd GRCh37)": allele, "considered records": considered,
            "resolution": resolution}


def _cell(*specs, base=9002001, letter="A"):
    return ";".join(f"{base + i}={letter}/match/{s}" for i, s in enumerate(specs))


def _expect(considered, rt, outcome, group=None, stars=None, resolution="-", allele="A"):
    got = evaluate_pair(_pair(considered, resolution, allele), rt)
    _require(f"{considered!r} {rt} res={resolution!r}: expected {(outcome, group, stars)}, "
             f"got {got[:3]} errors {got[3]}", got == (outcome, group, stars, []))


def _errors_of(considered, resolution="-", allele="A", rt="carrier_status"):
    return evaluate_pair(_pair(considered, resolution, allele), rt)[3]


def _claim(considered, outcome, ids="-", sig="-", stars="-", resolution="-", allele="A", rs="rs9000001"):
    return _t2(rs, allele, considered, ids, sig, stars, outcome, resolution)


def _run_clinvar(attempt):
    def grammar_accepts():
        items, errs = parse_considered("9001001=A/match/P/2;9001002=C/other-allele/B/1;9001003=?/unmapped/AP/0", "A")
        _require(f"valid cell reported {errs}", not errs)
        _require("expected three items", [i["vid"] for i in items] == ["9001001", "9001002", "9001003"])
        _require("only the first item is a match", [i["vid"] for i in items if i["disp"] == "match"] == ["9001001"])
        _require("'-' must parse to no items", parse_considered("-", "A") == ([], []))
        outcome = evaluate_pair(_pair("9001001=A/match/P/2;9001002=C/other-allele/B/1;9001003=?/unmapped/AP/0"),
                                "carrier_status")
        _require(f"accepted row evaluates to {outcome}", outcome == ("eligible", "P", 2, []))
        return True
    attempt("R1B.syn_clinvar_grammar_accepts", grammar_accepts)

    def grammar_rejects():
        cases = [
            ("9001001=A/bogus/P/2", "A", "item-malformed"), ("9001001=N/match/P/2", "A", "item-malformed"),
            ("9001001=A/match/P/5", "A", "item-malformed"), ("9001001=A/match/P", "A", "item-malformed"),
            ("x=A/match/P/2", "A", "item-malformed"),
            ("9001001=A/match/P/2;9001001=A/match/B/1", "A", "duplicate-vid"),
            ("9001001=A/match/P/2; 9001002=A/match/B/1", "A", "item-malformed"),
            ("9001001=?/match/P/2", "A", "letter-disp-mismatch"),
            ("9001001=A/unmapped/P/2", "A", "letter-disp-mismatch"),
            ("9001001=C/match/P/2", "A", "match-letter-not-pair-allele"),
            ("9001001=C/other-condition/P/2", "A", "other-condition-letter"),
            ("9001001=A/other-allele/P/2", "A", "other-allele-letter"),
            ("9001001=D/other-allele/P/2", "A", "letter-class-mismatch"),
            ("9001001=A/other-allele/P/2", "D", "letter-class-mismatch"),
        ]
        for cell, allele, code in cases:
            _has(parse_considered(cell, allele)[1], code, f"{cell!r} (pair allele {allele})")
            _has(_errors_of(cell, allele=allele), code, f"evaluate_pair on {cell!r}")
        return True
    attempt("R1B.syn_clinvar_grammar_rejects", grammar_rejects)

    def p3_beats_b1():
        cell = "9001011=A/match/P/3;9001012=A/match/B/1;9001013=A/match/P/2"
        _expect(cell, "carrier_status", "eligible", "P", 3, resolution="clinvar:vcv:9001011")
        res = check_pair_row(_claim(cell, "eligible", "9001011;9001012;9001013", "P", "2", "clinvar:vcv:9001011"),
                             "carrier_status")
        _has(res, "row-stars", "claimed stars 2")
        res = check_pair_row(_claim(cell, "eligible", "9001011;9001012;9001013", "P", "3", "clinvar:vcv:9001011"),
                             "carrier_status")
        _clean(res, "resolver stars 3")
        return True
    attempt("R1B.syn_clinvar_resolver_p3_beats_b1", p3_beats_b1)

    def b4_vs_p3_unresolvable():
        cell = "9001021=A/match/P/3;9001022=A/match/B/4"
        _expect(cell, "carrier_status", "excluded:conflicting-evidence")
        _has(check_pair_row(_claim(cell, "eligible", "9001021;9001022", "P", "3"), "carrier_status"),
             "row-outcome", "claimed eligible")
        return True
    attempt("R1B.syn_clinvar_b4_vs_p3_unresolvable", b4_vs_p3_unresolvable)

    def b4_vs_p3_contested():
        _has(_errors_of("9001021=A/match/P/3;9001022=A/match/B/4", "clinvar:vcv:9001021"),
             "resolution-contested", "B/4 contests P/3")
        return True
    attempt("R1B.syn_clinvar_b4_vs_p3_resolver_contested", b4_vs_p3_contested)

    def p4_beats_b3():
        _expect("9001031=A/match/P/4;9001032=A/match/B/3", "carrier_status", "eligible", "P", 4,
                resolution="clinvar:vcv:9001031")
        return True
    attempt("R1B.syn_clinvar_p4_beats_b3", p4_beats_b3)

    def unresolved_conflict():
        cell = "9001041=A/match/P/2;9001042=A/match/B/1"
        _expect(cell, "carrier_status", "excluded:conflicting-evidence")
        _has(_errors_of(cell, "clinvar:vcv:9001041"), "resolution-low-stars", "P/2 resolver")
        return True
    attempt("R1B.syn_clinvar_unresolved_conflict", unresolved_conflict)

    def cf_alone_and_resolved():
        _expect("9001051=A/match/CF/2", "carrier_status", "excluded:conflicting-evidence")
        _expect("9001051=A/match/CF/2;9001052=A/match/P/3", "carrier_status", "eligible", "P", 3,
                resolution="clinvar:vcv:9001052")
        return True
    attempt("R1B.syn_clinvar_cf_alone_and_resolved", cf_alone_and_resolved)

    def resolution_invalid_forms():
        cell = "9001061=A/match/P/3;9001062=A/match/B/1"
        cell_other = cell + ";9001063=C/other-allele/P/4"
        forms = [("9001061", cell, "resolution-not-typed"), ("pmid:9001099", cell, "resolution-wrong-type"),
                 ("genereviews:NBK000000", cell, "resolution-wrong-type"),
                 ("clinvar:vcv:9001099", cell, "resolution-not-matched"),
                 ("clinvar:vcv:9001062", cell, "resolution-not-p"),
                 ("clinvar:vcv:9001063", cell_other, "resolution-not-matched"),
                 ("clinvar:rcv:9001061", cell, "resolution-wrong-type")]
        for resolution, considered, code in forms:
            _has(_errors_of(considered, resolution), code, f"resolution {resolution!r}")
        _expect(cell, "carrier_status", "eligible", "P", 3, resolution="clinvar:vcv:9001061")
        return True
    attempt("R1B.syn_clinvar_resolution_invalid_forms", resolution_invalid_forms)

    def resolution_without_conflict():
        _has(_errors_of("9001071=A/match/P/3", "clinvar:vcv:9001071"), "resolution-without-conflict", "single record")
        return True
    attempt("R1B.syn_clinvar_resolution_without_conflict", resolution_without_conflict)

    def stars_not_carried():
        cases = [("9001081=C/other-allele/P/3", "excluded:no-allele-condition-match"),
                 ("9001082=A/other-condition/P/3", "excluded:no-allele-condition-match"),
                 ("9001083=?/unmapped/P/3", "excluded:allele-not-mappable"),
                 ("-", "excluded:no-allele-condition-match")]
        for cell, outcome in cases:
            _expect(cell, "carrier_status", outcome)
            _has(check_pair_row(_claim(cell, "eligible", "-", "P", "3"), "carrier_status"), "row-outcome",
                 f"claimed eligible for {cell!r}")
        return True
    attempt("R1B.syn_clinvar_stars_not_carried", stars_not_carried)

    def row_consistency():
        cell = "9001091=A/match/P/2;9001092=C/other-allele/B/1"
        good = _claim(cell, "eligible", "9001091", "P", "2")
        _clean(check_pair_row(good, "carrier_status", "A"), "consistent row")
        for col, bad, code in (("matched record ids", "9001091;9001092", "row-matched-ids"),
                               ("matched significance", "RF", "row-significance"),
                               ("stars", "3", "row-stars"), ("pair outcome", "excluded:conflicting-evidence", "row-outcome")):
            row = dict(good)
            row[col] = bad
            _has(check_pair_row(row, "carrier_status", "A"), code, f"{col} differs")
        _has(check_pair_row(good, "carrier_status", "G"), "pair-allele-differs", "pair allele differs from T1")
        return True
    attempt("R1B.syn_clinvar_row_consistency", row_consistency)

    named = [
        ("p1_ap3_cs", "carrier_status", ("P/1", "AP/3"), ("excluded:insufficient-review-status", "P", 1)),
        ("p2_ap3_cs", "carrier_status", ("P/2", "AP/3"), ("eligible", "P", 2)),
        ("rf1_ap3_cs", "carrier_status", ("RF/1", "AP/3"), ("excluded:ineligible-significance", None, None)),
        ("p2_rf3_cs", "carrier_status", ("P/2", "RF/3"), ("eligible", "P", 2)),
        ("p1_ap3_ra", "risk_association", ("P/1", "AP/3"), ("excluded:insufficient-review-status", "P", 1)),
        ("p2_ap3_ra", "risk_association", ("P/2", "AP/3"), ("eligible", "P", 2)),
        ("rf1_ap3_ra", "risk_association", ("RF/1", "AP/3"), ("excluded:insufficient-review-status", "RF", 1)),
        ("rf2_ap3_ra", "risk_association", ("RF/2", "AP/3"), ("eligible", "RF", 2)),
        ("p1_rf3_ra", "risk_association", ("P/1", "RF/3"), ("excluded:insufficient-review-status", "P", 1)),
        ("p2_rf1_ra", "risk_association", ("P/2", "RF/1"), ("eligible", "P", 2)),
    ]
    for name, rt, specs, want in named:
        def named_row(rt=rt, specs=specs, want=want):
            _expect(_cell(*specs), rt, *want)
            return True
        attempt(f"R1B.syn_clinvar_{name}", named_row)

    def p2_p3_same_group():
        for rt in ("carrier_status", "risk_association"):
            _expect(_cell("P/2", "P/3"), rt, "eligible", "P", 3)
        return True
    attempt("R1B.syn_clinvar_p2_p3_same_group", p2_p3_same_group)

    def b_u_only():
        for spec in ("B/3", "U/3", "AP/4"):
            for rt in ("carrier_status", "risk_association"):
                _expect(_cell(spec), rt, "excluded:ineligible-significance")
        return True
    attempt("R1B.syn_clinvar_b_u_only", b_u_only)

    def empty_inventory():
        t1 = [_t1(rsid="rs9000002", label="Example condition one", rt="carrier_status", cat="carrier", allele="A")]
        row = _claim("-", "excluded:no-allele-condition-match", rs="rs9000002")
        _clean(check_clinvar_table(t1, [row], [_t5("rs9000002", "-", "manifest:idx-1")]), "empty inventory")
        for rt in ("carrier_status", "risk_association"):
            _expect("-", rt, "excluded:no-allele-condition-match")
        _has(check_clinvar_table(t1, [row], [_t5("rs9000002", "9001099", "manifest:idx-1")]),
             "inventory-mismatch", "'-' against a non-empty inventory")
        return True
    attempt("R1B.syn_clinvar_empty_inventory", empty_inventory)

    def group_matrix():
        subsets = [frozenset(c) for n in range(1, 7) for c in itertools.combinations(GROUPS, n)]
        _require(f"expected 63 non-empty subsets, got {len(subsets)}", len(subsets) == 63)
        conflicts = [s for s in subsets if s not in ORACLE_NONCONFLICT]
        _require(f"expected 15 non-conflicting and 48 conflicting sets, got {len(conflicts)} conflicts",
                 len(ORACLE_NONCONFLICT) == 15 and len(conflicts) == 48)
        count = 0
        for groups in subsets:
            for idx, rt in enumerate(("carrier_status", "risk_association")):
                for stars in range(4):
                    supporting = ORACLE_NONCONFLICT.get(groups, (None, None))[idx]
                    specs = [f"{g}/{stars if (supporting is None or g == supporting) else 4}" for g in sorted(groups)]
                    got = evaluate_pair(_pair(_cell(*specs, base=9002100)), rt)
                    if groups not in ORACLE_NONCONFLICT:
                        want = ("excluded:conflicting-evidence", None, None, [])
                    elif supporting is None:
                        want = ("excluded:ineligible-significance", None, None, [])
                    elif stars < 2:
                        want = ("excluded:insufficient-review-status", supporting, stars, [])
                    else:
                        want = ("eligible", supporting, stars, [])
                    _require(f"matrix {sorted(groups)} {rt} stars {stars}: expected {want}, got {got}", got == want)
                    count += 1
        _require(f"matrix ran {count} assertions, expected 504", count == 504)
        print(f"  group_matrix assertions={count}")
        return True
    attempt("R1B.syn_clinvar_group_matrix", group_matrix)

    # --- r39 ids that stand --------------------------------------------------------------
    def same_rsid_other_allele():
        _expect("9000011=A/match/P/2;9000012=C/other-allele/B/1", "carrier_status", "eligible", "P", 2)
        return True
    attempt("R1B.clinvar_pair_same_rsid_other_allele", same_rsid_other_allele)

    def not_carried_across_alleles():
        _expect("9000021=C/other-allele/P/3", "carrier_status", "excluded:no-allele-condition-match")
        _has(check_pair_row(_claim("9000021=C/other-allele/P/3", "eligible", "-", "P", "3"), "carrier_status"),
             "row-outcome", "eligible with stars 3")
        return True
    attempt("R1B.clinvar_stars_not_carried_across_alleles", not_carried_across_alleles)

    def not_carried_across_conditions():
        _expect("9000031=A/other-condition/P/3", "carrier_status", "excluded:no-allele-condition-match")
        _has(check_pair_row(_claim("9000031=A/other-condition/P/3", "eligible", "-", "P", "3"), "carrier_status"),
             "row-outcome", "eligible with stars 3")
        return True
    attempt("R1B.clinvar_stars_not_carried_across_conditions", not_carried_across_conditions)

    def pair_conflict_excluded():
        cell = "9000041=A/match/P/2;9000042=A/match/B/1"
        _expect(cell, "carrier_status", "excluded:conflicting-evidence")
        _has(check_pair_row(_claim(cell, "eligible", "9000041;9000042", "P", "2"), "carrier_status"),
             "row-outcome", "claimed eligible")
        return True
    attempt("R1B.clinvar_pair_conflict_excluded", pair_conflict_excluded)

    def class_groups_truth_table():
        terms = ["pathogenic", "Likely pathogenic", "Pathogenic/Likely pathogenic", "Benign", "Likely benign",
                 "Uncertain significance", "risk factor", "association", "protective", "drug response",
                 "Conflicting classifications of pathogenicity", "an unknown term"]
        want = ["P", "P", "P", "B", "B", "U", "RF", "AP", "AP", "AP", "CF", "AP"]
        got = [significance_group(t) for t in terms]
        _require(f"groups {got} != {want}", got == want)
        return True
    attempt("R1B.clinvar_class_groups_truth_table", class_groups_truth_table)

    def considered_equals_inventory():
        t1 = [_t1(rsid="rs9000002", label="Example condition one", rt="carrier_status", cat="carrier", allele="A")]
        row = _claim("9000051=A/match/P/2;9000052=C/other-allele/B/1", "eligible", "9000051", "P", "2", rs="rs9000002")
        _clean(check_clinvar_table(t1, [row], [_t5("rs9000002", "9000051;9000052", "manifest:idx-1")]), "equal")
        _has(check_clinvar_table(t1, [row], [_t5("rs9000002", "9000051;9000052;9000053", "manifest:idx-1")]),
             "inventory-mismatch", "inventory has an extra id")
        _has(check_clinvar_table(t1, [row], [_t5("rs9000002", "9000051", "manifest:idx-1")]),
             "inventory-mismatch", "considered has an extra id")
        _has(check_clinvar_table(t1, [row], []), "inventory-missing", "no T5 row")
        return True
    attempt("R1B.clinvar_considered_equals_pack_inventory", considered_equals_inventory)

    def pair_allele_equals_effect_allele():
        t1 = [_t1(rsid="rs9000002", rt="carrier_status", cat="carrier", allele="G")]
        row = _claim("9000051=A/match/P/2", "eligible", "9000051", "P", "2", rs="rs9000002")
        _has(check_clinvar_table(t1, [row], [_t5("rs9000002", "9000051", "manifest:idx-1")]),
             "pair-allele-differs", "T2 allele A vs T1 allele G")
        _has(check_clinvar_table([_t1(rsid="rs9000002")], [row], [_t5("rs9000002", "9000051", "x")]),
             "result-type", "a trait row has no ClinVar pair")
        return True
    attempt("R1B.clinvar_pair_allele_equals_effect_allele", pair_allele_equals_effect_allele)

    # --- allele mapping (r41 2.4) ---------------------------------------------------------------
    def allele_mapping_truth_table():
        snv = {"chrom": "1", "pos": 100, "ref": "G", "alt": "A"}
        dele = {"chrom": "7", "pos": 200, "ref": "TCTT", "alt": "T"}
        ins = {"chrom": "3", "pos": 300, "ref": "G", "alt": "GAC"}
        cases = [
            ("snv match", dict(snv), snv, ("A", None)),
            ("snv other alt letter", dict(snv, alt="C"), snv, ("C", None)),
            ("snv pos mismatch", dict(snv, pos=101), snv, ("?", "position-or-ref-mismatch")),
            ("snv ref mismatch", dict(snv, ref="C"), snv, ("?", "position-or-ref-mismatch")),
            ("snv chrom mismatch", dict(snv, chrom="2"), snv, ("?", "position-or-ref-mismatch")),
            ("deletion match", dict(dele), dele, ("D", None)),
            ("deletion span differs", dict(dele, alt="TC"), dele, ("?", "span-mismatch")),
            ("deletion ref differs", dict(dele, ref="TCTTAA"), dele, ("?", "position-or-ref-mismatch")),
            ("insertion vs deletion", {"chrom": "7", "pos": 200, "ref": "T", "alt": "TA"}, dele, ("?", "kind-mismatch")),
            ("snv vs deletion", dict(snv), dele, ("?", "kind-mismatch")),
            ("insertion match", dict(ins), ins, ("I", None)),
            ("insertion other sequence", dict(ins, alt="GTT"), ins, ("?", "span-mismatch")),
            ("mnv", {"chrom": "1", "pos": 100, "ref": "AC", "alt": "GT"}, snv, ("?", "complex")),
            ("non-anchored deletion", {"chrom": "7", "pos": 200, "ref": "TCT", "alt": "CT"}, dele, ("?", "complex")),
            ("comma alt", dict(snv, alt="A,G"), snv, ("?", "malformed")),
            ("empty alt", dict(snv, alt=""), snv, ("?", "malformed")),
            ("lower case alt", dict(snv, alt="a"), snv, ("?", "malformed")),
            ("non-ACGT letter", dict(snv, alt="N"), snv, ("?", "malformed")),
            ("dbsnp malformed", dict(snv), dict(snv, ref=""), ("?", "malformed")),
            ("no record placement", None, snv, ("?", "no-grch37-placement")),
            ("no dbsnp placement", dict(snv), None, ("?", "no-grch37-placement")),
            ("notation only", {"notation": "c.100G>A"}, snv, ("?", "notation-only")),
        ]
        for name, rec, db, want in cases:
            got = map_placement(rec, db)
            _require(f"{name}: expected {want}, got {got}", got == want)
        return True
    attempt("R1B.syn_allele_mapping_truth_table", allele_mapping_truth_table)


# =============================================================================
# Inheritance gate (r39 3.3).
# =============================================================================
def _run_inheritance(attempt):
    def gate_truth_table():
        want = {("AR", "carrier_status", "P"), ("AD-IP", "risk_association", "P"), ("AD-IP", "risk_association", "RF"),
                ("SUSC", "risk_association", "P"), ("SUSC", "risk_association", "RF"), ("n/a", "trait", "-")}
        models = ["AR", "AD-IP", "SUSC", "AD", "UNRESOLVED", "n/a"]
        got = {(m, r, g) for m in models for r in ("trait", "carrier_status", "risk_association")
               for g in ("P", "B", "U", "RF", "AP", "CF", "-") if inheritance_ok(m, r, g)}
        _require(f"passing cells {sorted(got)} != {sorted(want)}", got == want)
        return True
    attempt("R1B.inheritance_gate_truth_table", gate_truth_table)

    def carrier_status_requires_ar_and_p_pair():
        w = good_world()
        w["t3"][0]["model"] = "AD-IP"
        _has(check_health_rows(w["t1"], w["t2"], w["t3"]), "health-inheritance", "AD-IP on carrier_status")
        for considered in ("9001001=G/match/RF/2", "9001001=G/match/AP/3"):
            w = good_world()
            w["t2"][0]["considered records"] = considered
            _has(check_health_rows(w["t1"], w["t2"], w["t3"]), "health-not-eligible", considered)
        return True
    attempt("R1B.carrier_status_requires_ar_and_p_pair", carrier_status_requires_ar_and_p_pair)

    def risk_association_never_says_carrier():
        for model in ("AD-IP", "SUSC"):
            for cell in ("one-copy meaning", "two-copy meaning"):
                w = good_world()
                w["t3"][1].update({"model": model, cell: "this makes you a Carrier"})
                _has(check_inheritance_table(w["t1"], w["t3"]), f"carrier-word-on-{model}", f"{model}/{cell}")
        w = good_world()
        w["t3"][1].update({"one-copy meaning": "noncarriers and subcarrier are different words",
                           "two-copy meaning": "carriers"})
        _clean(check_inheritance_table(w["t1"], w["t3"]), "carrier inside another word")
        w = good_world()
        w["t3"][0]["one-copy meaning"] = "one copy: not named"
        _has(check_inheritance_table(w["t1"], w["t3"]), "ar-one-copy-not-carrier", "AR without the word")
        return True
    attempt("R1B.risk_association_never_says_carrier", risk_association_never_says_carrier)

    def unresolved_or_out_of_scope_model_excluded():
        for model, code in (("UNRESOLVED", "inheritance-unresolved"), ("AD", "inheritance-out-of-scope")):
            w = good_world()
            w["t3"][0]["model"] = model
            _has(check_inheritance_table(w["t1"], w["t3"]), "model-not-keepable", f"{model} included")
            _set_row("rs9000002", dec="excluded", code=code)(w)
            _clean(check_inheritance_table(w["t1"], w["t3"]), f"{model} excluded with {code}")
            _set_row("rs9000002", dec="reserve", code="-")(w)
            _has(check_inheritance_table(w["t1"], w["t3"]), "model-not-keepable", f"{model} reserve")
            _set_row("rs9000002", dec="excluded", code="single-study")(w)
            _has(check_inheritance_table(w["t1"], w["t3"]), "model-reason", f"{model} wrong code")
        return True
    attempt("R1B.unresolved_or_out_of_scope_model_excluded", unresolved_or_out_of_scope_model_excluded)

    def sources_typed_and_nonclinvar():
        for src, code in (("clinvar:vcv:9001001", "source-not-independent"), ("clinvar:rcv:RCV900001", "source-not-independent"),
                          ("foo:123", "source-untyped"), ("NBK900001", "source-untyped"), ("-", "source-not-independent")):
            w = good_world()
            w["t3"][0]["inheritance sources (typed ids)"] = src
            _has(check_inheritance_table(w["t1"], w["t3"]), code, f"sources {src!r}")
        w = good_world()
        w["t3"][0]["inheritance sources (typed ids)"] = "clinvar:vcv:9001001;medgen:C9000001"
        _clean(check_inheritance_table(w["t1"], w["t3"]), "clinvar plus an independent source")
        return True
    attempt("R1B.inheritance_sources_typed_and_nonclinvar", sources_typed_and_nonclinvar)

    def copy_meaning_cells_present():
        for cell in ("one-copy meaning", "two-copy meaning"):
            for empty in ("", "-"):
                w = good_world()
                w["t3"][0][cell] = empty
                _has(check_inheritance_table(w["t1"], w["t3"]), "copy-cell-empty", f"{cell}={empty!r}")
        return True
    attempt("R1B.copy_meaning_cells_present", copy_meaning_cells_present)

    def t3_rows_match_t1_result_type():
        w = good_world()
        _set_row("rs9000002", rt="risk_association")(w)
        _has(check_inheritance_table(w["t1"], w["t3"]), "model-result-type", "AR on risk_association")
        w = good_world()
        _set_row("rs9000003", rt="carrier_status")(w)
        _has(check_inheritance_table(w["t1"], w["t3"]), "model-result-type", "AD-IP on carrier_status")
        w = good_world()
        w["t3"][0]["model"] = "bogus"
        _has(check_inheritance_table(w["t1"], w["t3"]), "model-invalid", "unknown model")
        w = good_world()
        w["t3"].append(_t3("rs9000077", "AR", "carrier", "x", "pmid:1"))
        _has(check_inheritance_table(w["t1"], w["t3"]), "t3-without-t1", "T3 row without a decision row")
        return True
    attempt("R1B.t3_rows_match_t1_result_type", t3_rows_match_t1_result_type)


# =============================================================================
# Replication evaluator (r41 3.3). One implementation serves fixtures and the real file.
# =============================================================================
def _rep(rows, allele="A", label="Example trait", aliases=None, pack=None):
    return evaluate_replication(rows, allele, label, aliases or {}, _pack_ids(rows) if pack is None else pack)


def _base_rows(pa="9003101", pb="9003102", ca="cohort-a", cb="cohort-b", p1="3e-9", p2="1e-6"):
    return [_gwas("a", pa, ca, p1), _gwas("b", pb, cb, p2)]


def _functional(rid="f", pmid="9003199", cohort="cohort-f", direction="up"):
    return _t4(rid, "-", pmid, "A", "verified", f"pmid:{pmid}", direction, "-", cohort, f"pmid:{pmid}")


def _run_replication(attempt):
    def case(name, fn):
        attempt(f"R1B.syn_replication_{name}", fn)

    def baseline():
        status, groups, drops = _rep(_base_rows())
        _require(f"baseline {status} {groups} {drops}", status == "replicated" and len(groups) == 2
                 and all(c is None for c in drops.values()))
        return True
    case("baseline_replicated", baseline)

    def p_boundary():
        for p1, p2, want in (("5e-8", "1e-6", "replicated"), ("5.1e-8", "1e-6", "not-significant"),
                             ("1e-7", "1e-6", "not-significant"), ("4.9e-8", "0.5", "replicated")):
            got = _rep(_base_rows(p1=p1, p2=p2))[0]
            _require(f"p {p1}/{p2}: expected {want}, got {got}", got == want)
        return True
    case("p_boundary", p_boundary)

    def all_p_above():
        rows = _base_rows(p1="1e-6", p2="1e-5")
        _require("expected not-significant", _rep(rows)[0] == "not-significant")
        res = check_trait_table([_t1()], rows, {}, _pack_ids(rows))
        _has(res, "trait-not-replicated", "included claim")
        return True
    case("two_groups_all_p_above", all_p_above)

    def drop_case(mutate, code, status="single-study"):
        rows = _base_rows()
        mutate(rows[1])
        got_status, _, drops = _rep(rows)
        _require(f"expected row b dropped as {code} and {status}, got {drops} {got_status}",
                 drops["b"] == code and got_status == status)
        return True
    case("wrong_allele", lambda: drop_case(lambda r: r.update({"effect allele (fwd, GRCh37)": "G"}), "allele-mismatch"))
    case("missing_p", lambda: drop_case(lambda r: r.update({"p-value": "-"}), "p-missing"))
    case("missing_direction", lambda: drop_case(lambda r: r.update({"direction": "-"}), "direction-missing"))
    case("orientation_unverified", lambda: drop_case(lambda r: r.update({"orientation": "unverified"}),
                                                     "orientation-unverified"))
    case("trait_mismatch", lambda: drop_case(lambda r: r.update({"trait (reported)": "Other thing"}), "trait-mismatch"))
    case("p_malformed", lambda: drop_case(lambda r: r.update({"p-value": "<1e-9"}), "p-malformed"))

    def source_not_in_pack():
        rows = _base_rows()
        pack = _pack_ids(rows) - {"gwas:GCST9003102"}
        status, _, drops = _rep(rows, pack=pack)
        _require(f"expected evidence-not-in-pack, got {drops} {status}", drops["b"] == "evidence-not-in-pack"
                 and status == "single-study")
        status, _, drops = _rep(rows, pack=_pack_ids(rows) - {"pmid:9003102"})
        _require(f"orientation source outside the pack: {drops}", drops["b"] == "evidence-not-in-pack")
        return True
    case("source_not_in_pack", source_not_in_pack)

    def clustered(rows):
        status, groups, _ = _rep(rows)
        _require(f"expected one cluster and single-study, got {status} {groups}", status == "single-study"
                 and len(groups) == 1 and groups[0] == ["a", "b"])
        return True
    case("shared_cohort", lambda: clustered(_base_rows(cb="cohort-a")))
    case("declared_overlap", lambda: clustered([_base_rows()[0], dict(_base_rows()[1], **{"overlap with": "a"})]))
    case("declared_overlap_reverse", lambda: clustered([dict(_base_rows()[0], **{"overlap with": "b"}), _base_rows()[1]]))

    def same_pmid():
        rows = _base_rows()
        rows[1]["PMID"] = "9003101"
        return clustered(rows)
    case("same_pmid", same_pmid)

    def opposing():
        rows = _base_rows()
        rows[1]["direction"] = "down"
        _require("expected conflicting-evidence", _rep(rows)[0] == "conflicting-evidence")
        return True
    case("opposing_direction", opposing)

    def unknown_cohort():
        rows = _base_rows(ca="unknown", cb="unknown")
        status, groups, drops = _rep(rows)
        _require(f"unknown cohorts must not form a group: {status} {groups}",
                 status == "no-counted-evidence" and groups == [] and set(drops.values()) == {"cohort-unknown"})
        code = replication_exclusion_code(status, drops)
        _require(f"exclusion code {code!r}", code == "evidence-not-in-pack")
        _require("no soft drop must give no-independent-confirmation",
                 replication_exclusion_code("no-counted-evidence", {"a": "trait-mismatch"}) == "no-independent-confirmation")
        return True
    case("unknown_cohort", unknown_cohort)

    def exclusion_codes():
        want = {"single-study": "single-study", "conflicting-evidence": "conflicting-evidence",
                "not-significant": "no-independent-confirmation", "replicated": None}
        for status, code in want.items():
            _require(f"{status}: {replication_exclusion_code(status, {})!r} != {code!r}",
                     replication_exclusion_code(status, {}) == code)
        return True
    case("exclusion_codes", exclusion_codes)

    def alias_match():
        rows = _base_rows()
        rows[1]["trait (reported)"] = "Example phenotype"
        aliases = {"example trait": ["example phenotype"]}
        _require("alias must match", _rep(rows, aliases=aliases)[0] == "replicated")
        _require("without the alias file it must not match", _rep(rows)[0] == "single-study")
        rows[1]["trait (reported)"] = "Example trait measurement"
        _require("a longer reported trait is not an exact match", _rep(rows, aliases=aliases)[2]["b"] == "trait-mismatch")
        return True
    case("alias_match", alias_match)

    def functional_ok():
        rows = [_gwas("a", "9003101", "cohort-a", "2e-9"), _functional()]
        status, groups, drops = _rep(rows)
        _require(f"expected replicated, got {status} {groups} {drops}", status == "replicated" and len(groups) == 2)
        return True
    case("functional_ok", functional_ok)

    def functional_needs_gwas_p():
        rows = [_gwas("a", "9003101", "cohort-a", "1e-6"), _functional()]
        _require("expected not-significant", _rep(rows)[0] == "not-significant")
        status, groups, drops = _rep([_functional()])
        _require(f"functional alone must be zero groups and no-counted-evidence, got {status} {groups}",
                 status == "no-counted-evidence" and groups == [])
        bad = dict(_functional(), **{"p-value": "3e-9"})
        _require("a functional row may not carry a p-value", _rep([_gwas("a", "9003101", "cohort-a", "1e-6"), bad])[2]["f"] == "p-malformed")
        return True
    case("functional_needs_gwas_p", functional_needs_gwas_p)

    def functional_same_pmid():
        rows = [_gwas("a", "9003101", "cohort-a", "2e-9"), _functional(pmid="9003101")]
        status, groups, _ = _rep(rows)
        _require(f"same PMID must be one cluster: {status} {groups}", status == "single-study" and len(groups) == 1)
        return True
    case("functional_same_pmid", functional_same_pmid)

    def functional_conditions():
        a = _gwas("a", "9003101", "cohort-a", "2e-9")
        _require("functional pmid outside the pack must be dropped",
                 _rep([a, _functional()], pack=_pack_ids([a]))[2]["f"] == "evidence-not-in-pack")
        _require("functional cohort equal to the GWAS cohort is one cluster",
                 _rep([a, _functional(cohort="cohort-a")])[0] == "single-study")
        _require("functional direction against the GWAS rows is a conflict",
                 _rep([a, _functional(direction="down")])[0] == "conflicting-evidence")
        _require("two functional papers count as one group (cap)",
                 len(_rep([a, _functional(), _functional("g", "9003198", "cohort-g")])[1]) == 2)
        return True
    case("functional_conditions", functional_conditions)

    def counted_claim_checked():
        rows = _base_rows()
        rows[1]["effect allele (fwd, GRCh37)"] = "G"
        rows[0]["counted"] = "yes"
        rows[1]["counted"] = "yes"
        _has(check_trait_table([_t1()], rows, {}, _pack_ids(rows)), "t4-counted-claim", "yes for a dropped row")
        ok = _base_rows()
        _clean(check_trait_table([_t1()], ok, {}, _pack_ids(ok)), "honest claims")
        ok[1]["counted"] = "no:allele-mismatch"
        _has(check_trait_table([_t1()], ok, {}, _pack_ids(ok)), "t4-counted-claim", "no for a counted row")
        return True
    case("counted_claim_checked", counted_claim_checked)

    def table_cases():
        _has(check_trait_table([_t1()], [], {}, set()), "trait-without-t4", "no rows")
        rows = [_base_rows()[0]]
        _has(check_trait_table([_t1()], rows, {}, _pack_ids(rows)), "trait-not-replicated", "single study")
        ok = _base_rows()
        res = check_trait_table([_t1()], ok, {}, _pack_ids(ok))
        _clean(res, "replicated trait")
        _require("rows_checked must count the rows", res.rows_checked >= 1)
        _has(check_trait_table([_t1()], ok + [_gwas("z", "9003299", "cohort-z", "1e-9", rs="rs9000099")], {},
                               _pack_ids(ok)), "t4-without-t1", "orphan T4 row")
        bad = _base_rows()
        bad[0]["orientation"] = "maybe"
        _has(check_trait_table([_t1()], bad, {}, _pack_ids(bad)), "t4-orientation", "orientation vocabulary")
        return True
    case("table_cases", table_cases)


# =============================================================================
# Document-level checkers on invented text, then on the real document.
# =============================================================================
def check_group_table(tables):
    try:
        rows = find_table(tables, GROUP_TABLE_HEADER)["rows"]
    except TableError as exc:
        return [f"group-table: {exc}"]
    got, errors = {}, []

    def cell(value):
        return None if value == "-" else value

    for r in rows:
        key = frozenset(g.strip() for g in r["group set"].split(","))
        if key in got:
            errors.append(f"group-table: duplicate row {sorted(key)}")
        got[key] = (cell(r["carrier_status supporting group"]), cell(r["risk_association supporting group"]))
    errors += [f"group-table: row {sorted(k)} missing" for k in ORACLE_NONCONFLICT if k not in got]
    errors += [f"group-table: unexpected row {sorted(k)}" for k in got if k not in ORACLE_NONCONFLICT]
    errors += [f"group-table: row {sorted(k)} says {got[k]}, rule says {v}"
               for k, v in ORACLE_NONCONFLICT.items() if k in got and got[k] != v]
    return errors


def _table_md(header, rows=()):
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def _group_table_md(oracle=None):
    oracle = ORACLE_NONCONFLICT if oracle is None else oracle
    rows = [(", ".join(sorted(k)), v[0] or "-", v[1] or "-") for k, v in oracle.items()]
    return _table_md(GROUP_TABLE_HEADER, rows)


def _run_doc_helpers(attempt):
    def header_exact_rejects_variants():
        header = T1_HEADER
        _clean(check_header_exact(parse_tables(_table_md(header)), header), "exact header")
        variants = {
            "one character": [h.replace("rsID", "rsId") for h in header],
            "prefix only": header[:-1],
            "extra column": header + ["extra"],
            "reordered": [header[1], header[0]] + header[2:],
            "whitespace": [h + " " if i == 3 else h for i, h in enumerate(header)],
        }
        for name, bad in variants.items():
            if name == "whitespace":
                continue  # cells are stripped by the parser; equal headers are equal
            _has(check_header_exact(parse_tables(_table_md(bad)), header), "header", name)
        _has(check_header_exact([], header), "header", "no tables")
        _has(check_header_exact(parse_tables(_table_md(header) + "\n" + _table_md(header)), header), "header",
             "duplicated table")
        for name, hdr in TABLE_HEADERS.items():
            _require(f"{name} header has duplicate columns", len(set(hdr)) == len(hdr))
        return True
    attempt("R1B.syn_header_exact_rejects_variants", header_exact_rejects_variants)

    def required_headings():
        text = "\n".join(f"## {h}\n\nbody\n" for h in DOC_REQUIRED_HEADINGS)
        _clean(check_required_headings(text), "all headings")
        for h in DOC_REQUIRED_HEADINGS:
            _has(check_required_headings(text.replace(f"## {h}\n", f"## {h} extra\n")), h, f"renamed {h}")
        _has(check_required_headings("```\n## Method\n```\n"), "Method", "heading inside a code fence")
        return True
    attempt("R1B.syn_required_headings", required_headings)

    def status_line():
        _clean(check_status_line("Status: method-only\n", 0), "method-only, zero rows")
        _clean(check_status_line("Status: curated, 3 rows\n", 3), "curated, three rows")
        for text, n, why in (("Status: method-only\n", 2, "method-only with rows"),
                             ("Status: curated, 3 rows\n", 0, "curated with no rows"),
                             ("Status: curated, 3 rows\n", 4, "count differs"),
                             ("", 0, "no status line"),
                             ("Status: method-only\nStatus: method-only\n", 0, "two status lines"),
                             ("Status: draft\n", 0, "unknown status")):
            _has(check_status_line(text, n), "status", why)
        return True
    attempt("R1B.syn_status_line_matches_row_count", status_line)

    def rule_paragraph():
        words = ["autosomal", "X", "Y", "PAR", "MT", "hemizygous"]
        body = "## Exclusion rule AUTO-1\n\nautosomal only; X, Y, PAR and MT are out; hemizygous handling is not used.\n\n## Next\n\nother\n"
        _clean(check_rule_paragraph(body, "Exclusion rule AUTO-1", words), "complete paragraph")
        for w in words:
            _has(check_rule_paragraph(body.replace(w, "zz"), "Exclusion rule AUTO-1", words), w, f"missing {w}")
        _has(check_rule_paragraph("## Other\n", "Exclusion rule AUTO-1", words), "missing", "no heading")
        _has(check_rule_paragraph(body.replace("hemizygous", "zz") + "\nhemizygous\n", "Exclusion rule AUTO-1", words),
             "hemizygous", "the word lies outside the paragraph")
        return True
    attempt("R1B.syn_rule_paragraph_words", rule_paragraph)

    def reason_codes():
        good = "## Reason codes\n\n" + "\n".join(f"- `{c}`" for c in REASON_CODES) + \
               "\n- `x-linked-out-of-scope` (retired)\n"
        _clean(check_reason_code_list(good), "complete list")
        _has(check_reason_code_list(good.replace("- `single-study`\n", "")), "single-study", "code missing")
        _has(check_reason_code_list(good + "- `made-up-code`\n"), "made-up-code", "extra code")
        _has(check_reason_code_list(good.replace(" (retired)", "")), "retired", "retired code unmarked")
        _has(check_reason_code_list("## Other\n"), "Reason codes", "no section")
        return True
    attempt("R1B.syn_reason_code_list_matches_checker", reason_codes)

    def wording_generic():
        _clean(check_wording_generic("Plain text about rs9000001 and a curation method.\n"), "clean text")
        home = "/Us" + "ers/" + "someone/notes"
        mail = "someone" + "@" + "example" + ".org"
        _has(check_wording_generic(f"see {home}\n"), "wording", "home path")
        _has(check_wording_generic(f"write to {mail}\n"), "email", "email address")
        return True
    attempt("R1B.syn_wording_generic", wording_generic)

    def provenance_block():
        sha = "0123456789abcdef" * 4
        good = f"## Provenance block\n\npack manifest sha256 {sha} retrieved 2026-01-31\n"
        _clean(check_provenance_block(good, 3), "complete block")
        _clean(check_provenance_block("## Provenance block\n\nPLACEHOLDER\n", 0), "placeholders are fine with no rows")
        _has(check_provenance_block("## Other\n", 3), "section missing", "no section")
        _has(check_provenance_block(good + "PLACEHOLDER\n", 3), "placeholders", "placeholder left")
        _has(check_provenance_block(good.replace(sha, "abc"), 3), "sha256", "no hash")
        _has(check_provenance_block(good.replace("2026-01-31", "soon"), 3), "ISO date", "no date")
        return True
    attempt("R1B.syn_provenance_block_required_when_rows_present", provenance_block)

    def group_table():
        _clean(check_group_table(parse_tables(_group_table_md())), "table equal to the rule")
        _require("the rule table must have 15 rows", len(ORACLE_NONCONFLICT) == 15)
        short = dict(ORACLE_NONCONFLICT)
        short.pop(frozenset({"P"}))
        _has(check_group_table(parse_tables(_group_table_md(short))), "missing", "row removed")
        wrong = dict(ORACLE_NONCONFLICT)
        wrong[frozenset({"RF"})] = ("RF", "RF")
        _has(check_group_table(parse_tables(_group_table_md(wrong))), "rule says", "cell changed")
        extra = dict(ORACLE_NONCONFLICT)
        extra[frozenset({"P", "B"})] = ("P", "P")
        _has(check_group_table(parse_tables(_group_table_md(extra))), "unexpected", "conflict set listed")
        _has(check_group_table([]), "group-table", "no table")
        return True
    attempt("R1B.syn_group_table_matches_rule", group_table)


# =============================================================================
# Doc-content gates (FAILING until docs/panel-curation.md exists).
# =============================================================================
def _doc_and_tables():
    text = read_doc()
    try:
        return text, parse_tables(text)
    except TableError as exc:
        raise AssertionError(f"{DOC_REL}: {exc}")


def _run_doc(attempt):
    def no_errors(errors):
        _require("; ".join(errors), not errors)
        return True

    def doc_has_required_sections():
        return no_errors(check_required_headings(read_doc()))
    attempt("R1B.doc_has_required_sections", doc_has_required_sections)

    for rid, table in (("decision", "T1"), ("clinvar", "T2"), ("inheritance", "T3"), ("trait", "T4"),
                       ("inventory", "T5")):
        def header_exact(table=table):
            _, tables = _doc_and_tables()
            return no_errors(check_header_exact(tables, TABLE_HEADERS[table]))
        attempt(f"R1B.{rid}_table_header_exact", header_exact)

    def autosome_rule_recorded():
        words = ["autosomal", "X", "Y", "PAR", "MT", "hemizygous", "non-autosomal-out-of-scope"]
        return no_errors(check_rule_paragraph(read_doc(), "Exclusion rule AUTO-1", words))
    attempt("R1B.autosome_rule_recorded", autosome_rule_recorded)

    def clinvar_rule_recorded():
        text, tables = _doc_and_tables()
        errors = [f"heading {h!r} missing" for h in ("Considered set", "Allele mapping", "Qualifying record",
                                                      "No carry-over", "Resolution", "Supporting group")
                  if section_body(text, h) is None]
        errors += [f"{DOC_REL} does not mention {s!r}" for s in ("G-1", "R-RES") + OUTCOME_STRINGS + RESOLUTION_CODES
                   if s not in text]
        return no_errors(errors + check_group_table(tables))
    attempt("R1B.clinvar_rule_recorded", clinvar_rule_recorded)

    def inheritance_rule_recorded():
        return no_errors(check_rule_paragraph(read_doc(), "Inheritance gate", ["Criterion 12"] + list(MODELS)))
    attempt("R1B.inheritance_rule_recorded", inheritance_rule_recorded)

    def replication_rule_recorded():
        words = ["5e-8", "independent", "orientation", "direction", "cohort", "functional", "replicated",
                 "single-study", "conflicting-evidence", "not-significant", "no-counted-evidence"]
        return no_errors(check_rule_paragraph(read_doc(), "Replication", words))
    attempt("R1B.replication_rule_recorded", replication_rule_recorded)

    def assayability_rule_recorded():
        words = list(ASSAY_STATUSES) + ["array", "verified"]
        return no_errors(check_rule_paragraph(read_doc(), "Assayability", words))
    attempt("R1B.assayability_rule_recorded", assayability_rule_recorded)

    def limitations_section_present():
        text = read_doc()
        body = section_body(text, "Limitations")
        errors = [] if body and body.strip() else ["Limitations section missing or empty"]
        errors += [f"Limitations lacks {p!r}" for p in ("array presence", "not verified", "aggregate coverage")
                   if body is not None and p not in body]
        return no_errors(errors)
    attempt("R1B.limitations_section_present", limitations_section_present)

    def status_line_matches_row_count():
        text, tables = _doc_and_tables()
        return no_errors(check_status_line(text, len(find_table(tables, T1_HEADER)["rows"])))
    attempt("R1B.status_line_matches_row_count", status_line_matches_row_count)

    def wording_generic():
        errors = check_wording_generic(read_doc())
        if os.path.exists(TARGETS_PATH):
            with open(TARGETS_PATH, encoding="utf-8") as fh:
                errors += check_wording_generic(fh.read())
        return no_errors(errors)
    attempt("R1B.wording_generic", wording_generic)

    def reason_code_list_matches_checker():
        return no_errors(check_reason_code_list(read_doc()))
    attempt("R1B.reason_code_list_matches_checker", reason_code_list_matches_checker)


# =============================================================================
# Real-file gates: the same checkers on the real document and targets file. Each
# prints rows_checked; zero is expected until the data ticket and means vacuous.
# =============================================================================
def _real_world():
    missing = [f"{rel} missing" for rel, path in ((DOC_REL, DOC_PATH), (TARGETS_REL, TARGETS_PATH))
               if not os.path.exists(path)]
    _require("; ".join(missing), not missing)
    text = read_doc()
    try:
        tables = doc_tables(text)
    except TableError as exc:
        raise AssertionError(f"{DOC_REL}: {exc}")
    return text, tables, read_targets()


def _entries(targets):
    variants = targets.get("variants") if isinstance(targets, dict) else None
    return variants if isinstance(variants, list) else []


def pack_ids_from_inventory(t5_rows):
    ids = set()
    for r in t5_rows:
        ids.update(i for i in split_ids(r["pack file index id"]) if typed_id_ok(i))
    return ids


def _real(attempt, name, fn):
    def body():
        text, t, targets = _real_world()
        res = fn(text, t, targets)
        print(f"  rows_checked={res.rows_checked} {name}")
        _require(f"{name}: " + "; ".join(res), not res)
        return True
    attempt(name, body)


def _run_real(attempt):
    def aliases():
        import evidence
        return evidence.load_aliases(ALIASES_PATH)

    def assay(text, t, targets):
        res = check_assayability(t["T1"])
        return _result(list(res) + check_unknown_provisional_disclosed(t["T1"], text), res.rows_checked)

    def prov_block(text, t, targets):
        return _result(check_provenance_block(text, len(t["T1"])), len(t["T1"]))

    real = [
        ("R1B.release_targets_shape_valid", lambda x, t, g: check_targets_shape(g)),
        ("R1B.targets_pairs_valid", lambda x, t, g: check_pairs(_entries(g))),
        ("R1B.category_and_result_type_valid", lambda x, t, g: check_pairs(_entries(g))),
        ("R1B.no_duplicate_rsid", lambda x, t, g: check_unique_rsids(t["T1"], _entries(g))),
        ("R1B.targets_bijection_with_included_rows", lambda x, t, g: check_bijection(t["T1"], _entries(g))),
        ("R1B.doc_row_matches_targets_fields", lambda x, t, g: check_row_matches_entries(t["T1"], _entries(g))),
        ("R1B.reserves_not_in_targets", lambda x, t, g: check_reserves_not_in_targets(t["T1"], _entries(g))),
        ("R1B.genome_build_grch37", lambda x, t, g: check_build(g if isinstance(g, dict) else {}, t["T1"])),
        ("R1B.effect_allele_valid", lambda x, t, g: check_effect_alleles(t["T1"], _entries(g))),
        ("R1B.strand_ambiguous_flagged_or_absent", lambda x, t, g: check_strand(t["T1"], _entries(g))),
        ("R1B.every_exclusion_has_reason", lambda x, t, g: check_decisions(t["T1"])),
        ("R1B.included_have_typed_ids_and_date", lambda x, t, g: check_provenance(t["T1"])),
        ("R1B.included_health_rows_have_eligible_pair", lambda x, t, g: check_health_rows(t["T1"], t["T2"], t["T3"])),
        ("R1B.provenance_block_required_when_rows_present", prov_block),
        ("R1B.real_chromosomes_autosomal", lambda x, t, g: check_chromosomes(t["T1"], _entries(g))),
        ("R1B.no_unresolved_marker_in_targets", lambda x, t, g: check_no_unresolved_markers(t["T1"], _entries(g))),
        ("R1B.included_trait_rows_have_replication",
         lambda x, t, g: check_trait_table(t["T1"], t["T4"], aliases(), pack_ids_from_inventory(t["T5"]))),
        ("R1B.real_clinvar_table_valid", lambda x, t, g: check_clinvar_table(t["T1"], t["T2"], t["T5"])),
        ("R1B.real_inheritance_table_valid", lambda x, t, g: check_inheritance_table(t["T1"], t["T3"])),
        ("R1B.real_assayability_valid", assay),
        ("R1B.real_t1_pairs_valid", lambda x, t, g: check_t1_pairs(t["T1"])),
    ]
    for name, fn in real:
        _real(attempt, name, fn)


# =============================================================================
# Fix round r44: cross-table joins, document clauses, evaluator rule, boundaries.
# =============================================================================
def _run_fix_round(attempt):
    # --- joins (D-43-2) ---------------------------------------------------------
    def pair_condition_cases(check, code):
        for idx in (0, 1):
            for value in ("Entirely unrelated condition", "example condition one", "Example condition one.", "", "-"):
                w = good_world()
                w["t2"][idx]["pair condition"] = value
                rs = w["t2"][idx]["rsID"]
                _has(check(w), f"{code}: {rs}", f"T2 row {idx}, {value!r}")

    def clinvar_pair_condition_equals_label():
        w = good_world()
        _clean(check_clinvar_table(w["t1"], w["t2"], w["t5"]), "good world, clinvar table")
        pair_condition_cases(lambda w: check_clinvar_table(w["t1"], w["t2"], w["t5"]), "pair-condition-differs")
        return True
    attempt("R1B.syn_t2_pair_condition_equals_t1_label", clinvar_pair_condition_equals_label)

    def health_pair_condition_equals_label():
        w = good_world()
        _clean(check_health_rows(w["t1"], w["t2"], w["t3"]), "good world, health rows")
        pair_condition_cases(lambda w: check_health_rows(w["t1"], w["t2"], w["t3"]), "health-pair-condition-differs")
        return True
    attempt("R1B.syn_health_pair_condition_equals_t1_label", health_pair_condition_equals_label)

    def health_pair_allele_equals_effect_allele():
        w = good_world()
        w["t2"][0].update({"pair allele (fwd GRCh37)": "A", "considered records": "9001001=A/match/P/2"})
        _has(check_health_rows(w["t1"], w["t2"], w["t3"]), "health-pair-allele-differs: rs9000002",
             "T2 allele A vs T1 allele G")
        return True
    attempt("R1B.syn_health_pair_allele_equals_effect_allele", health_pair_allele_equals_effect_allele)

    def t2_row_needs_t1_row():
        w = good_world()
        w["t2"].append(_t2("rs9000077", "G", "9001001=G/match/P/2", "9001001", "P", "2", "eligible"))
        _has(check_clinvar_table(w["t1"], w["t2"], w["t5"]), "t2-without-t1: rs9000077", "orphan T2 row")
        return True
    attempt("R1B.syn_t2_row_needs_t1_row", t2_row_needs_t1_row)

    # --- document clauses (D-43-1, D-43-3) ----------------------------------------
    def doc_clause_checker():
        good = ("## Criteria\n\n7. Report safety: the entry can be reported without implying a diagnosis or\n"
                "   an absolute risk, and its only honest wording is not a\n   recommendation.\n\n## Next\n\nother\n")
        _clean(check_doc_clause(good, "Criteria", REPORT_SAFETY_PRESENT, REPORT_SAFETY_ABSENT), "wrapped clause")
        _clean(check_doc_clause(good.replace("can be", "CAN BE"), "Criteria", REPORT_SAFETY_PRESENT,
                                REPORT_SAFETY_ABSENT), "case is ignored")
        for why, text in (
                ("inverted can/cannot", good.replace("entry can be", "entry cannot be")),
                ("spaced inversion", good.replace("entry can be", "entry can not be")),
                ("second half inverted", good.replace("is not a\n   recommendation", "is a\n   recommendation")),
                ("second half dropped", good.replace(", and its only honest wording is not a\n   recommendation", "")),
                ("clause absent", good.replace("7. Report safety", "7. Report safety (see below)").replace(
                    "can be reported", "is reported")),
                ("clause in another section", good.replace("## Criteria", "## Elsewhere")),
        ):
            _has(check_doc_clause(text, "Criteria", REPORT_SAFETY_PRESENT, REPORT_SAFETY_ABSENT), "clause", why)
        _has(check_doc_clause(good + "\n## Other\n\nit cannot be reported so\n", "Criteria", REPORT_SAFETY_PRESENT,
                              REPORT_SAFETY_ABSENT), "document contains", "inverted phrase in another section")
        _has(check_doc_clause(good.replace("## Criteria", "## Criteria extra"), "Criteria", REPORT_SAFETY_PRESENT),
             "heading", "missing heading")
        return True
    attempt("R1B.syn_doc_clause_checker", doc_clause_checker)

    def doc_report_safety_clause():
        errors = check_doc_clause(read_doc(), "Criteria", REPORT_SAFETY_PRESENT, REPORT_SAFETY_ABSENT)
        _require("; ".join(errors), not errors)
        return True
    attempt("R1B.doc_report_safety_clause", doc_report_safety_clause)

    def doc_functional_group_rule():
        errors = check_doc_clause(read_doc(), "Replication", FUNCTIONAL_RULE_PRESENT)
        _require("; ".join(errors), not errors)
        return True
    attempt("R1B.doc_functional_group_rule", doc_functional_group_rule)

    def doc_pair_condition_rule():
        errors = check_doc_clause(read_doc(), "ClinVar pair rule", PAIR_CONDITION_RULE_PRESENT)
        _require("; ".join(errors), not errors)
        return True
    attempt("R1B.doc_pair_condition_rule", doc_pair_condition_rule)

    # --- evaluator rule (D-43-3) ---------------------------------------------------
    def functional_only_is_zero_groups():
        for rows in ([_functional()], [_functional(), _functional("g", "9003198", "cohort-g")]):
            status, groups, drops = _rep(rows)
            _require(f"functional-only evidence must be zero groups, got {status} {groups}",
                     status == "no-counted-evidence" and groups == [])
            _require("functional-only evidence must have no other exclusion reason than no-independent-confirmation",
                     replication_exclusion_code(status, drops) == "no-independent-confirmation")
        status, _, _ = _rep([_functional(), _functional("g", "9003198", "cohort-g", direction="down")])
        _require(f"opposing functional rows are a conflict, got {status}", status == "conflicting-evidence")
        a = _gwas("a", "9003101", "cohort-a", "2e-9")
        status, groups, _ = _rep([a, _functional()])
        _require(f"one gwas group plus a functional group is replicated, got {status} {groups}",
                 status == "replicated" and len(groups) == 2)
        return True
    attempt("R1B.syn_replication_functional_only_is_zero_groups", functional_only_is_zero_groups)

    # --- boundaries (D-43-4) -------------------------------------------------------
    def alleles_accept_t():
        for letter in "ACGT":
            _require(f"{letter} must be a valid SNP allele", allele_ok(letter, "snp"))
            _require(f"{letter} must be valid with no kind", allele_ok(letter, None))
            _require(f"{letter} must not be a valid indel allele", not allele_ok(letter, "indel"))
            items, errors = parse_considered(f"9001001={letter}/match/P/2", letter)
            _require(f"considered item {letter}: {errors}", not errors and items[0]["letter"] == letter)
            rec = {"chrom": "1", "pos": 100, "ref": "C" if letter != "C" else "G", "alt": letter}
            _require(f"placement alt {letter}", map_placement(rec, dict(rec)) == (letter, None))
        w = good_world()
        _both(_set_entry("rs9000001", effect_allele="T"), _set_row("rs9000001", allele="T"))(w)
        _clean(check_effect_alleles(w["t1"], w["entries"]), "effect allele T")
        w = good_world()
        _set_row("rs9000001", allele="T")(w)
        _has(check_effect_alleles(w["t1"], w["entries"]), "allele-differs", "T1 T against targets A")
        return True
    attempt("R1B.syn_alleles_accept_t", alleles_accept_t)

    def p_value_bounds():
        # r41 3.2: p-value is a decimal in (0,1] or '-'; <= 0, > 1 and non-numeric are p-malformed.
        for cell, want in (("1", 1.0), ("1.0", 1.0), ("0.5", 0.5), ("5e-8", 5e-8), ("1e-300", 1e-300),
                           ("1.000000000000000000000000000000e-300", 1e-300), ("0." + "0" * 40 + "1", 1e-41),
                           (".5", 0.5)):
            got = _parse_p(cell)
            _require(f"p {cell!r}: expected {(want, None)}, got {got}", got == (want, None))
        for cell in ("0", "0.0", "1.0000001", "2", "1e1", "-0.5", "-1e-5", "NA", "<1e-8", "", "1e-5x", "e-5",
                     "1e-400"):
            got = _parse_p(cell)
            _require(f"p {cell!r}: expected p-malformed, got {got}", got == (None, "p-malformed"))
        _require("a dash is p-missing", _parse_p("-") == (None, "p-missing"))
        _require("p exactly 1 is an eligible, non-significant row",
                 _rep(_base_rows(p1="1", p2="1e-6"))[0] == "not-significant")
        _require("a very small p counts", _rep(_base_rows(p1="1e-300", p2="1"))[0] == "replicated")
        return True
    attempt("R1B.syn_p_value_bounds", p_value_bounds)

    def source_dates_calendar():
        for good in ("2024-02-29", "2000-02-29", "2023-12-31", "2024-01-15", "2025-06-30", "2024-12-31"):
            _require(f"{good} must be a valid date", date_ok(good))
            w = good_world()
            _set_row("rs9000001", date=good)(w)
            _clean(check_provenance(w["t1"]), f"retrieved {good}")
        for bad in ("2023-02-29", "2100-02-29", "2023-04-31", "2024-13-01", "2024-00-10", "2024-1-5", "24-01-01",
                    "2024-02-30", ""):
            _require(f"{bad!r} must be an invalid date", not date_ok(bad))
            w = good_world()
            _set_row("rs9000001", date=bad)(w)
            _has(check_provenance(w["t1"]), "date-invalid", f"retrieved {bad!r}")
        return True
    attempt("R1B.syn_source_dates_calendar", source_dates_calendar)

    # --- r45 fix round (D-44-1..D-44-4) -----------------------------------------
    _syn(attempt, "t1_pairs", lambda w: check_t1_pairs(w["t1"]), [
        ("excluded_bad_pair", _set_row("rs9000005", cat="trait", rt="carrier_status"), "pair-invalid"),
        ("reserve_bad_pair", _set_row("rs9000004", cat="carrier", rt="trait"), "pair-invalid"),
    ])

    def t1_pairs_all_decisions():
        for dec in DECISIONS:
            code = "-" if dec != "excluded" else "single-study"
            for cat, rt in VALID_PAIRS:
                row = _t1(rsid="rs9000041", cat=cat, rt=rt, dec=dec, code=code)
                _clean(check_t1_pairs([row]), f"{dec} {cat}/{rt}")
            for cat, rt in (("trait", "carrier_status"), ("carrier", "trait")):
                row = _t1(rsid="rs9000042", cat=cat, rt=rt, dec=dec, code=code)
                _has(check_t1_pairs([row]), "pair-invalid: rs9000042", f"{dec} {cat}/{rt}")
        return True
    attempt("R1B.syn_t1_pairs_all_decisions", t1_pairs_all_decisions)

    _syn(attempt, "t2_unique_rsid", lambda w: check_clinvar_table(w["t1"], w["t2"], w["t5"]), [
        ("duplicate_t2_rsid", lambda w: w["t2"].append(dict(w["t2"][0])), "t2-duplicate-rsid"),
    ])

    def doc_evidence_not_in_pack_clause():
        errors = check_doc_clause(read_doc(), "Replication", EVIDENCE_NOT_IN_PACK_PRESENT)
        _require("; ".join(errors), not errors)
        return True
    attempt("R1B.doc_evidence_not_in_pack_clause", doc_evidence_not_in_pack_clause)


# =============================================================================
# Fix round r47 (D-46-1..D-46-3): the targets condition/gene join, the wording
# checker's denylist root, and three cross-table survivor gaps.
# =============================================================================
def _entry_of(w, rs):
    return next(e for e in w["entries"] if e["rsid"] == rs)


def _set_entry_value(rs, key, value):
    def mutate(w):
        _entry_of(w, rs)[key] = value
    return mutate


def _del_entry_key(rs, key):
    def mutate(w):
        del _entry_of(w, rs)[key]
    return mutate


def _populated_t1_text():
    """The real document with its empty T1 table filled from the invented world."""
    w = good_world()
    rows = [[r[c] for c in T1_HEADER] for r in w["t1"]]
    text = read_doc().replace(_table_md(T1_HEADER), _table_md(T1_HEADER, rows))
    return text, w


def _run_r47(attempt):
    # --- D-46-1: the targets condition and gene join to T1 --------------------
    rejects = []
    for kind, rs in (("carrier", "rs9000002"), ("trait", "rs9000001")):
        for key, unrelated in (("condition", "Unrelated condition value"), ("gene", "UNRELATEDGENE")):
            rejects.append((f"{kind}_{key}_mismatch", _set_entry_value(rs, key, unrelated), "row-field-differs"))
            rejects.append((f"{kind}_{key}_missing", _del_entry_key(rs, key), "row-field-differs"))
            rejects.append((f"{kind}_{key}_null", _set_entry_value(rs, key, None), "row-field-differs"))
    _syn(attempt, "row_matches_targets_label_and_gene",
         lambda w: check_row_matches_entries(w["t1"], w["entries"]), rejects)

    def populated_target_condition_mismatch():
        text, w = _populated_t1_text()
        t1 = doc_tables(text)["T1"]
        _clean(check_row_matches_entries(t1, w["entries"]), "populated good world")
        _entry_of(w, "rs9000002")["condition"] = "Unrelated invented condition"
        _has(check_row_matches_entries(t1, w["entries"]), "row-field-differs",
             "real-file gate: wrong target condition")
        return True
    attempt("R1B.syn_row_matches_targets_populated_real_file_condition",
            populated_target_condition_mismatch)

    # --- D-46-2: the wording checker reads the suite's own root ----------------
    def wording_denylist_uses_copy_root():
        import guard
        old_root, old_cwd = guard._ROOT, os.getcwd()
        outer = tempfile.mkdtemp(prefix="r47-outside-")
        inner = tempfile.mkdtemp(prefix="r47-inner-")
        try:
            for root in (outer, inner):
                with open(os.path.join(root, ".sensitive-terms"), "w", encoding="utf-8") as fh:
                    fh.write("zzqtermzz\n")
            guard._ROOT = None
            os.chdir(outer)
            errors = check_wording_generic("zzqtermzz\n")
            _require(f"a cwd denylist must not reach the suite root: {errors}",
                     not any("owner-specific" in e for e in errors))
            plain, hashed = guard.load_denylist(inner)
            _require("an explicit-root denylist must still be detected by guard",
                     any("denylist" in label for _, label in guard.scan_text_for_denylist("zzqtermzz", plain, hashed)))
        finally:
            os.chdir(old_cwd)
            guard._ROOT = old_root
            shutil.rmtree(outer, ignore_errors=True)
            shutil.rmtree(inner, ignore_errors=True)
        return True
    attempt("R1B.syn_wording_denylist_uses_copy_root", wording_denylist_uses_copy_root)

    # --- D-46-3: three non-equivalent survivors --------------------------------
    def clinvar_inventory_ids_differ_same_size():
        t1 = [_t1(rsid="rs9000002", label="Example condition one", rt="carrier_status", cat="carrier", allele="A")]
        row = _claim("9001001=A/match/P/2;9001002=C/other-allele/B/1", "eligible", "9001001", "P", "2", rs="rs9000002")
        _clean(check_clinvar_table(t1, [row], [_t5("rs9000002", "9001001;9001002", "manifest:idx-1")]),
               "inventory sets equal")
        _has(check_clinvar_table(t1, [row], [_t5("rs9000002", "9001001;9001099", "manifest:idx-1")]),
             "inventory-mismatch", "same size, different ids")
        return True
    attempt("R1B.syn_clinvar_inventory_ids_differ_same_size", clinvar_inventory_ids_differ_same_size)

    def replication_t_allele_is_mismatch():
        row = _gwas("a", "9009301", "cohort-a", "1e-9", allele="T")
        status, _, drops = _rep([row], allele="A")
        _require(f"a T allele against effect allele A must drop as allele-mismatch, got {drops} {status}",
                 drops["a"] == "allele-mismatch")
        return True
    attempt("R1B.syn_replication_t_allele_is_mismatch", replication_t_allele_is_mismatch)

    def susc_rejects_wrong_result_type():
        w = good_world()
        w["t3"][1]["model"] = "SUSC"
        _set_row("rs9000003", rt="carrier_status")(w)
        _has(check_inheritance_table(w["t1"], w["t3"]), "model-result-type", "SUSC on carrier_status")
        return True
    attempt("R1B.syn_inheritance_susc_rejects_wrong_result_type", susc_rejects_wrong_result_type)


# =============================================================================
# Fix round r50 (D-49-1, D-49-2): the targets key allowlist and the curator
# judgments sentence.
# =============================================================================
def _target_entry(**kw):
    base = {"rsid": "rs9000001", "gene": "GENEA", "condition": "Example trait",
            "category": "trait", "result_type": "trait", "effect_allele": "A",
            "assayability": "snp", "strand": "forward"}
    base.update(kw)
    return base


def _targets_obj(*entries):
    return {"_note": "invented", "panel_version": "0.1.0", "genome_build": "GRCh37",
            "strand": "forward", "variants": list(entries)}


def _run_r50(attempt):
    # --- D-49-1: the targets entry key allowlist ------------------------------
    def targets_shape_accepts_exact_eight_keys():
        res = check_targets_shape(_targets_obj(_target_entry()))
        _clean(res, "all eight allowed keys")
        _require("an accepted entry must be counted", res.rows_checked == 1)
        return True
    attempt("R1B.syn_targets_shape_accepts_exact_eight_keys", targets_shape_accepts_exact_eight_keys)

    def targets_shape_accepts_required_plus_gene_condition():
        entry = {k: v for k, v in _target_entry().items()
                 if k in ("rsid", "category", "result_type", "effect_allele", "assayability", "gene", "condition")}
        res = check_targets_shape(_targets_obj(entry))
        _clean(res, "required keys plus gene and condition")
        _require("an accepted entry must be counted", res.rows_checked == 1)
        return True
    attempt("R1B.syn_targets_shape_accepts_required_plus_gene_condition",
            targets_shape_accepts_required_plus_gene_condition)

    for forbidden in ("association", "clinvar", "snpedia", "gnomad_af", "chromosome",
                      "position", "reference_allele", "alternate_allele", "cls", "zz_extra"):
        def rejects_unknown(forbidden=forbidden):
            res = check_targets_shape(_targets_obj(_target_entry(**{forbidden: "invented"})))
            _has(res, f"unknown key {forbidden}", f"forbidden key {forbidden!r}")
            return True
        attempt(f"R1B.syn_targets_shape_rejects_unknown_{forbidden}", rejects_unknown)

    def targets_shape_sorts_unknown_keys():
        res = check_targets_shape(_targets_obj(_target_entry(zz_extra="x", association="y")))
        codes = [e for e in res if "unknown key" in e]
        _require(f"one error per unknown key: {codes}", len(codes) == 2)
        _require(f"unknown keys must be sorted: {codes}", codes == [
            "shape: variants[0] unknown key association", "shape: variants[0] unknown key zz_extra"])
        return True
    attempt("R1B.syn_targets_shape_sorts_unknown_keys", targets_shape_sorts_unknown_keys)

    def targets_shape_real_empty_targets_still_valid():
        _clean(check_targets_shape(read_targets()), "empty data/targets.release.json")
        return True
    attempt("R1B.syn_targets_shape_real_empty_targets_still_valid", targets_shape_real_empty_targets_still_valid)

    # --- D-49-2: the curator-judgment sentence --------------------------------
    def doc_targets_key_rule():
        errors = check_doc_clause(read_doc(), "Method", TARGETS_KEYS_RULE_PRESENT)
        _require("; ".join(errors), not errors)
        return True
    attempt("R1B.doc_targets_key_rule", doc_targets_key_rule)

    def doc_curator_judgments():
        errors = check_doc_clause(read_doc(), "Criteria", CURATOR_JUDGMENTS_PRESENT)
        _require("; ".join(errors), not errors)
        return True
    attempt("R1B.doc_curator_judgments", doc_curator_judgments)


# =============================================================================
# Ticket 1B-B (snp-REL-B-BUILD-r51): the release data-completeness section.
# ADD-ONLY: a new section appended after the 1B-A sections; no existing line is
# edited. The pool is the 23 DRAFT rsIDs of data/targets.carrier.json and
# data/targets.traits.json (read-only), in ticket order.
# =============================================================================
POOL_RSIDS = (
    "rs334", "rs33930165", "rs113993960", "rs1800562", "rs1799945", "rs6025",
    "rs1799963", "rs1050828", "rs28929474", "rs12913832", "rs1805007", "rs1805008",
    "rs17822931", "rs4988235", "rs671", "rs1229984", "rs762551", "rs72921001",
    "rs1426654", "rs16891982", "rs1800407", "rs1042602", "rs6152",
)
NON_AUTOSOMAL_POOL = ("rs1050828", "rs6152")
GOAL_BOUND = 6
RESERVE_BOUND = 3
METHOD_HASH_1BA = "5d975e62ab8e4888594651735196b3d06208d2e57671289f902b621abdb4e1df"
PACK_IDS = ("N0a", "N0b", "N0c", "N0d")


def _method_sections_text(text):
    """The method sections: lines before the first exact `## Tables` heading,
    with Status: lines dropped, joined by single newlines (ticket 1B-B C0)."""
    pre = []
    for line in text.split("\n"):
        if line == "## Tables":
            break
        pre.append(line)
    return "\n".join(ln for ln in pre if not ln.startswith("Status:"))


def _pool_t1(text):
    """T1 rows restricted to the pool; a missing/extra/duplicate rsID raises a
    named error so the C1 run fails on the not-yet-filled tables."""
    t1 = doc_tables(text)["T1"]
    ids = [r["rsID"] for r in t1]
    missing = [rs for rs in POOL_RSIDS if rs not in ids]
    extra = [rs for rs in ids if rs not in POOL_RSIDS]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    _require("T1 missing pool rows: " + ", ".join(missing), not missing)
    _require("T1 has non-pool rows: " + ", ".join(sorted(extra)), not extra)
    _require("T1 duplicate rows: " + ", ".join(dups), not dups)
    return t1


# --- pure checkers (r52): each returns a list of error strings, empty when the
# gate holds. They take parsed rows or document text so invented fixtures can
# exercise the logic without the real pack (ticket r52, O-6).
def check_1bb_pool_rows_complete(t1_rows):
    errors = []
    ids = [r["rsID"] for r in t1_rows]
    missing = [rs for rs in POOL_RSIDS if rs not in ids]
    extra = [rs for rs in ids if rs not in POOL_RSIDS]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    if missing:
        errors.append("missing pool rows: " + ", ".join(missing))
    if extra:
        errors.append("non-pool rows: " + ", ".join(sorted(extra)))
    if dups:
        errors.append("duplicate rows: " + ", ".join(dups))
    if len(ids) != len(POOL_RSIDS):
        errors.append(f"expected one T1 row per pool rsID, got {len(ids)}")
    return errors


def check_1bb_non_autosomal_excluded(t1_rows):
    errors, by = [], {r["rsID"]: r for r in t1_rows}
    for rs in NON_AUTOSOMAL_POOL:
        if rs not in by:
            errors.append(f"missing row {rs}")
            continue
        row = by[rs]
        if row["decision"] != "excluded":
            errors.append(f"{rs} decision {row['decision']!r}, expected excluded")
        if row["reason code"] != "non-autosomal-out-of-scope":
            errors.append(f"{rs} reason code {row['reason code']!r}, expected non-autosomal-out-of-scope")
    return errors


def check_1bb_included_count_within_goal(t1_rows):
    errors = []
    for group in CATEGORIES:
        n = len([r for r in _live(t1_rows, "included") if r["category"] == group])
        if n > GOAL_BOUND:
            errors.append(f"{group} has {n} included rows, bound is {GOAL_BOUND}")
    return errors


def check_1bb_reserves_per_group_bound(t1_rows):
    errors = []
    for group in CATEGORIES:
        n = len([r for r in _live(t1_rows, "reserve") if r["category"] == group])
        if n > RESERVE_BOUND:
            errors.append(f"{group} has {n} reserve rows, bound is 0..{RESERVE_BOUND}")
    return errors


def check_1bb_provenance_block(text):
    body = section_body(text, "Provenance block")
    if body is None:
        return ["Provenance block section missing"]
    errors = [f"Provenance block does not name {tok}" for tok in PACK_IDS if tok not in body]
    if re.search(r"\b[0-9a-f]{64}\b", body) is None:
        errors.append("Provenance block has no 64-hex sha256")
    if re.search(r"\b\d{4}-\d{2}-\d{2}\b", body) is None:
        errors.append("Provenance block has no ISO date")
    if "PLACEHOLDER" in body:
        errors.append("Provenance block still has PLACEHOLDER")
    return errors


def check_1bb_included_has_evidence_rows(t1_rows, t2_rows, t3_rows, t4_rows):
    t2_rs = {r["rsID"] for r in t2_rows}
    t3_rs = {r["rsID"] for r in t3_rows}
    t4_rs = {r["rsID"] for r in t4_rows}
    errors = []
    for r in _live(t1_rows, "included", "reserve"):
        rs, cat = r["rsID"], r["category"]
        if cat == "carrier":
            if rs not in t2_rs:
                errors.append(f"{rs} health {r['decision']} has no T2 row")
            if rs not in t3_rs:
                errors.append(f"{rs} health {r['decision']} has no T3 row")
        elif cat == "trait":
            if rs not in t4_rs:
                errors.append(f"{rs} trait {r['decision']} has no T4 row")
    return errors


def check_1bb_evidence_index_ids(t1_rows, t2_rows, t3_rows, t4_rows, t5_rows):
    pack_index = {r["rsID"]: set(split_ids(r["pack file index id"])) for r in t5_rows}
    bad = []

    def check(rs, ids):
        for i in ids:
            if not typed_id_ok(i):
                bad.append(f"{rs}: malformed typed id {i!r}")
            elif i not in pack_index.get(rs, set()):
                bad.append(f"{rs}: {i} is not in the T5 pack file index id cell")

    for r in t1_rows:
        check(r["rsID"], split_ids(r["sources (typed ids)"]))
    for r in t2_rows:
        if r["resolution"] != "-":
            check(r["rsID"], [r["resolution"]])
    for r in t3_rows:
        check(r["rsID"], split_ids(r["inheritance sources (typed ids)"]))
    for r in t4_rows:
        check(r["rsID"], [r["orientation source"], r["cohort source"]])
    return bad


def check_1bb_method_sections_hash(text):
    digest = hashlib.sha256(_method_sections_text(text).encode("utf-8")).hexdigest()
    if digest == METHOD_HASH_1BA:
        return []
    return [f"method sections changed: sha256 {digest} != {METHOD_HASH_1BA}"]


def _run_1b_b_char(attempt):
    def method_sections_unchanged_since_1ba():
        errors = check_1bb_method_sections_hash(read_doc())
        _require("; ".join(errors), not errors)
        return True
    attempt("R1B.char_method_sections_unchanged_since_1BA", method_sections_unchanged_since_1ba)


def _run_1b_b(attempt):
    """Ticket 1B-B data-completeness gates on the real document; each runs the
    same pure checker the invented fixtures below exercise (ticket r52, O-6)."""
    def gate(name, fn):
        def body():
            text = read_doc()
            tables = doc_tables(text)
            errors = fn(text, tables)
            _require(name + ": " + "; ".join(errors), not errors)
            return True
        attempt(name, body)

    gate("R1B.pool_rows_complete", lambda x, t: check_1bb_pool_rows_complete(t["T1"]))
    gate("R1B.draft_non_autosomal_candidates_excluded",
         lambda x, t: check_1bb_non_autosomal_excluded(t["T1"]))
    gate("R1B.included_count_within_goal", lambda x, t: check_1bb_included_count_within_goal(t["T1"]))
    gate("R1B.reserves_per_group_bound", lambda x, t: check_1bb_reserves_per_group_bound(t["T1"]))
    gate("R1B.provenance_block_complete", lambda x, t: check_1bb_provenance_block(x))
    gate("R1B.every_included_has_t2_t3_or_t4_row",
         lambda x, t: check_1bb_included_has_evidence_rows(t["T1"], t["T2"], t["T3"], t["T4"]))
    gate("R1B.evidence_index_ids_resolvable",
         lambda x, t: check_1bb_evidence_index_ids(t["T1"], t["T2"], t["T3"], t["T4"], t["T5"]))


# --- invented fixtures for the 1B-B gates (ticket r52, O-6). Each family proves
# the pure checker accepts a valid invented document and rejects a named bad
# state; no pack data is read (the method-hash positive is the real document).
def _1bb_syn_t1(rs, **kw):
    base = {"rsID": rs, "gene": "GENEZ", "chrom (GRCh37)": "1",
            "label used in report": "Invented label", "result type": "trait", "category": "trait",
            "effect allele (fwd, GRCh37)": "-", "direction/meaning": "not applicable",
            "build/strand": "-", "assayability_status": "unknown-provisional",
            "assayability_source": "-", "sources (typed ids)": f"dbsnp:{rs}",
            "retrieved (UTC date)": "2026-11-09", "rationale": "invented",
            "limitations": "invented", "decision": "excluded",
            "reason code": "no-independent-confirmation"}
    base.update(kw)
    return base


def _1bb_syn_pool_t1():
    rows = []
    for rs in POOL_RSIDS:
        if rs in NON_AUTOSOMAL_POOL:
            rows.append(_1bb_syn_t1(rs, **{"chrom (GRCh37)": "X", "sources (typed ids)": "-",
                                           "decision": "excluded",
                                           "reason code": "non-autosomal-out-of-scope"}))
        else:
            rows.append(_1bb_syn_t1(rs))
    return rows


def _1bb_syn_doc(t1=(), t2=(), t3=(), t4=(), t5=(), prov=None,
                 method=("## Method", "", "invented method text", "")):
    def tbl(header, rows):
        return _table_md(header, [[r[c] for c in header] for r in rows])
    parts = list(method) + ["## Tables", "",
                            tbl(T1_HEADER, t1), tbl(T2_HEADER, t2), tbl(T3_HEADER, t3),
                            tbl(T4_HEADER, t4), tbl(T5_HEADER, t5),
                            "## Provenance block", ""]
    if prov is None:
        prov = ["- Evidence pack ids: " + " ".join(PACK_IDS),
                "- Pack manifest sha256: " + "a" * 64,
                "- Retrieval dates (UTC, ISO): 2026-11-09"]
    parts += list(prov)
    return "\n".join(parts) + "\n"


def _run_1b_b_syn(attempt):
    def run(name, fn):
        attempt(f"R1B.syn_1bb_{name}", fn)

    def pool_accepts():
        _require("pool positive fixture must pass",
                 not check_1bb_pool_rows_complete(_1bb_syn_pool_t1()))
        return True
    run("pool_rows_complete_accepts", pool_accepts)

    def pool_rejects_missing():
        _has(check_1bb_pool_rows_complete(_1bb_syn_pool_t1()[:-1]), "missing pool rows", "pool")
        return True
    run("pool_rows_complete_rejects_missing", pool_rejects_missing)

    def pool_rejects_extra():
        _has(check_1bb_pool_rows_complete(_1bb_syn_pool_t1() + [_1bb_syn_t1("rs9009999")]),
             "non-pool rows", "pool")
        return True
    run("pool_rows_complete_rejects_extra", pool_rejects_extra)

    def pool_rejects_duplicate():
        _has(check_1bb_pool_rows_complete(_1bb_syn_pool_t1() + [_1bb_syn_t1(POOL_RSIDS[0])]),
             "duplicate rows", "pool")
        return True
    run("pool_rows_complete_rejects_duplicate", pool_rejects_duplicate)

    def nonaut_accepts():
        _require("non-autosomal positive fixture",
                 not check_1bb_non_autosomal_excluded(_1bb_syn_pool_t1()))
        return True
    run("non_autosomal_accepts", nonaut_accepts)

    def nonaut_rejects_kept():
        rows = _1bb_syn_pool_t1()
        next(r for r in rows if r["rsID"] == NON_AUTOSOMAL_POOL[0]).update(
            {"decision": "included", "reason code": "-"})
        _has(check_1bb_non_autosomal_excluded(rows), "expected excluded", "non-autosomal")
        return True
    run("non_autosomal_rejects_kept", nonaut_rejects_kept)

    def nonaut_rejects_wrong_code():
        rows = _1bb_syn_pool_t1()
        next(r for r in rows if r["rsID"] == NON_AUTOSOMAL_POOL[0])["reason code"] = "ancestry-informative"
        _has(check_1bb_non_autosomal_excluded(rows), "expected non-autosomal-out-of-scope",
             "non-autosomal")
        return True
    run("non_autosomal_rejects_wrong_code", nonaut_rejects_wrong_code)

    def _included_rows(n):
        return [_1bb_syn_t1(f"rs90000{i:02d}", category="carrier", result_type="carrier_status",
                            decision="included", **{"reason code": "-"}) for i in range(n)]

    def _reserve_rows(n):
        return [_1bb_syn_t1(f"rs90001{i:02d}", category="carrier", result_type="carrier_status",
                            decision="reserve", **{"reason code": "-"}) for i in range(n)]

    def goal_accepts():
        _require("goal positive fixture",
                 not check_1bb_included_count_within_goal(_included_rows(GOAL_BOUND)))
        return True
    run("included_count_accepts_bound", goal_accepts)

    def goal_rejects_over():
        _has(check_1bb_included_count_within_goal(_included_rows(GOAL_BOUND + 1)),
             f"bound is {GOAL_BOUND}", "goal")
        return True
    run("included_count_rejects_over_bound", goal_rejects_over)

    def reserves_accepts():
        _require("reserve positive fixture",
                 not check_1bb_reserves_per_group_bound(_reserve_rows(RESERVE_BOUND)))
        return True
    run("reserves_accepts_bound", reserves_accepts)

    def reserves_rejects_over():
        _has(check_1bb_reserves_per_group_bound(_reserve_rows(RESERVE_BOUND + 1)),
             f"0..{RESERVE_BOUND}", "reserve")
        return True
    run("reserves_rejects_over_bound", reserves_rejects_over)

    def prov_accepts():
        _require("provenance positive fixture", not check_1bb_provenance_block(_1bb_syn_doc()))
        return True
    run("provenance_accepts", prov_accepts)

    def prov_rejects_missing_pack():
        prov = ["- Evidence pack ids: " + " ".join(PACK_IDS[:-1]),
                "- sha256 " + "a" * 64, "- date 2026-11-09"]
        _has(check_1bb_provenance_block(_1bb_syn_doc(prov=prov)), "does not name", "provenance")
        return True
    run("provenance_rejects_missing_pack", prov_rejects_missing_pack)

    def prov_rejects_no_sha():
        prov = ["- Evidence pack ids: " + " ".join(PACK_IDS), "- date 2026-11-09"]
        _has(check_1bb_provenance_block(_1bb_syn_doc(prov=prov)), "no 64-hex sha256", "provenance")
        return True
    run("provenance_rejects_no_sha", prov_rejects_no_sha)

    def prov_rejects_no_date():
        prov = ["- Evidence pack ids: " + " ".join(PACK_IDS), "- sha256 " + "a" * 64]
        _has(check_1bb_provenance_block(_1bb_syn_doc(prov=prov)), "no ISO date", "provenance")
        return True
    run("provenance_rejects_no_date", prov_rejects_no_date)

    def prov_rejects_placeholder():
        prov = ["- Evidence pack ids: " + " ".join(PACK_IDS), "PLACEHOLDER"]
        _has(check_1bb_provenance_block(_1bb_syn_doc(prov=prov)), "PLACEHOLDER", "provenance")
        return True
    run("provenance_rejects_placeholder", prov_rejects_placeholder)

    def evidence_accepts():
        t1 = [_1bb_syn_t1("rs9000001", category="carrier", result_type="carrier_status",
                          decision="included", **{"reason code": "-"})]
        t2 = [_t2("rs9000001", "A", "9001001=A/match/P/2", "9001001", "P", "2", "eligible")]
        t3 = [_t3("rs9000001", "AR", "one copy: carrier", "two copies: invented",
                  "genereviews:NBK900001")]
        _require("evidence positive fixture",
                 not check_1bb_included_has_evidence_rows(t1, t2, t3, []))
        return True
    run("included_has_evidence_accepts", evidence_accepts)

    def evidence_rejects_no_t2():
        t1 = [_1bb_syn_t1("rs9000001", category="carrier", result_type="carrier_status",
                          decision="included", **{"reason code": "-"})]
        t3 = [_t3("rs9000001", "AR", "one copy: carrier", "two copies: invented",
                  "genereviews:NBK900001")]
        _has(check_1bb_included_has_evidence_rows(t1, [], t3, []), "has no T2 row", "evidence")
        return True
    run("included_has_evidence_rejects_no_t2", evidence_rejects_no_t2)

    def evidence_rejects_no_t3():
        t1 = [_1bb_syn_t1("rs9000001", category="carrier", result_type="carrier_status",
                          decision="included", **{"reason code": "-"})]
        t2 = [_t2("rs9000001", "A", "9001001=A/match/P/2", "9001001", "P", "2", "eligible")]
        _has(check_1bb_included_has_evidence_rows(t1, t2, [], []), "has no T3 row", "evidence")
        return True
    run("included_has_evidence_rejects_no_t3", evidence_rejects_no_t3)

    def evidence_rejects_no_t4():
        t1 = [_1bb_syn_t1("rs9000001", category="trait", decision="included",
                          **{"reason code": "-"})]
        _has(check_1bb_included_has_evidence_rows(t1, [], [], []), "has no T4 row", "evidence")
        return True
    run("included_has_evidence_rejects_no_t4", evidence_rejects_no_t4)

    def ids_accept():
        t1 = [_1bb_syn_t1("rs9000001", **{"sources (typed ids)": "dbsnp:rs9000001"})]
        t5 = [_t5("rs9000001", "-", "dbsnp:rs9000001")]
        _require("ids positive fixture", not check_1bb_evidence_index_ids(t1, [], [], [], t5))
        return True
    run("evidence_ids_accepts", ids_accept)

    def ids_reject_absent():
        t1 = [_1bb_syn_t1("rs9000001", **{"sources (typed ids)": "dbsnp:rs9000001"})]
        t5 = [_t5("rs9000001", "-", "dbsnp:rs9009999")]
        _has(check_1bb_evidence_index_ids(t1, [], [], [], t5),
             "is not in the T5 pack file index id cell", "ids")
        return True
    run("evidence_ids_rejects_absent", ids_reject_absent)

    def ids_reject_malformed():
        t1 = [_1bb_syn_t1("rs9000001", **{"sources (typed ids)": "notatypedid"})]
        t5 = [_t5("rs9000001", "-", "dbsnp:rs9000001")]
        _has(check_1bb_evidence_index_ids(t1, [], [], [], t5), "malformed typed id", "ids")
        return True
    run("evidence_ids_rejects_malformed", ids_reject_malformed)

    def method_accepts_real():
        _require("method positive fixture (the real document)",
                 not check_1bb_method_sections_hash(read_doc()))
        return True
    run("method_sections_hash_accepts_real", method_accepts_real)

    def method_rejects_changed():
        text = _1bb_syn_doc(method=("## Method", "", "an invented rewritten method", ""))
        _has(check_1bb_method_sections_hash(text), "method sections changed", "method")
        return True
    run("method_sections_hash_rejects_changed", method_rejects_changed)


def _run_1b_b_r55(attempt):
    """Ticket r55 (D-54-1..4): the attributing-RCV stars rule and the alias-file
    synonyms. The considered-records grammar is VCV-scoped and carries no
    RCV-stars column, so the checker cannot see RCV-level stars independently;
    the T2 `stars` cell is checked against the stars recorded for the attributing
    item (the only place the checker can see them)."""

    def t2_stars_must_not_exceed_attributing_record():
        cell = "9001001=A/match/P/2"
        good = _claim(cell, "eligible", "9001001", "P", "2")
        _clean(check_pair_row(good, "carrier_status", "A"), "stars equal the attributing record")
        over = _claim(cell, "eligible", "9001001", "P", "3")
        _has(check_pair_row(over, "carrier_status", "A"), "row-stars",
             "T2 stars exceed the attributing record")
        return True
    attempt("R1B.syn_1bb_r55_t2_stars_must_not_exceed_attributing_record",
            t2_stars_must_not_exceed_attributing_record)

    def attributing_record_below_two_stars():
        _expect("9001001=A/match/P/1", "carrier_status", "excluded:insufficient-review-status", "P", 1)
        _expect("9001001=A/match/P/0", "carrier_status", "excluded:insufficient-review-status", "P", 0)
        _expect("9001001=A/match/P/2", "carrier_status", "eligible", "P", 2)
        return True
    attempt("R1B.syn_1bb_r55_attributing_record_below_two_stars",
            attributing_record_below_two_stars)

    def alias_matcher_new_synonyms():
        import evidence
        aliases = evidence.load_aliases(ALIASES_PATH)
        for text, label in (("Hb SS disease", "sickle cell disease"),
                            ("Hemochromatosis type 1", "hereditary hemochromatosis"),
                            ("Thrombophilia due to thrombin defect", "prothrombin thrombophilia")):
            _require(f"{text!r} must match {label!r}",
                     evidence.condition_matches(text, label, aliases))
        for text in ("Congenital prothrombin deficiency", "prothrombin deficiency",
                     "factor ii deficiency"):
            _require(f"{text!r} must not match 'prothrombin thrombophilia'",
                     not evidence.condition_matches(text, "prothrombin thrombophilia", aliases))
        return True
    attempt("R1B.syn_1bb_r55_alias_matcher_synonyms", alias_matcher_new_synonyms)

    def real_health_rows_cite_attributing_rcv():
        text = read_doc()
        by = {r["rsID"]: r for r in doc_tables(text)["T1"]}
        want = {"rs334": "clinvar:rcv:RCV000016574",
                "rs1800562": "clinvar:rcv:RCV000000019",
                "rs1799963": "clinvar:rcv:RCV005419865"}
        absent = ("clinvar:rcv:RCV000205022", "clinvar:rcv:RCV000308358")
        for rs, rid in want.items():
            ids = split_ids(by[rs]["sources (typed ids)"])
            _require(f"{rs} must cite {rid}, has {ids}", rid in ids)
        for rs in ("rs1799963", "rs1800562"):
            ids = split_ids(by[rs]["sources (typed ids)"])
            _require(f"{rs} must not cite a wrong-attribution RCV, has {ids}",
                     not any(a in ids for a in absent))
        return True
    attempt("R1B.r55_health_rows_cite_attributing_rcv", real_health_rows_cite_attributing_rcv)


def run(check):
    def attempt(name, fn):
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001
            print(f"  detail {name}: {type(exc).__name__}: {exc}")
            check(name, False)
            return
        if not result:
            print(f"  detail {name}: gate returned false")
        check(name, bool(result))

    _run_characterization(attempt)
    _run_invariants(attempt)
    _run_clinvar(attempt)
    _run_inheritance(attempt)
    _run_replication(attempt)
    _run_doc_helpers(attempt)
    _run_doc(attempt)
    _run_fix_round(attempt)
    _run_r47(attempt)
    _run_r50(attempt)
    _run_real(attempt)
    _run_1b_b_char(attempt)
    _run_1b_b(attempt)
    _run_1b_b_syn(attempt)
    _run_1b_b_r55(attempt)


def main():
    passed, failed = [], []

    def check(name, cond):
        (passed if cond else failed).append(name)

    run(check)
    for name in passed:
        print(f"  ok   {name}")
    for name in failed:
        print(f"  FAIL {name}")
    print(f"\n{len(passed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
