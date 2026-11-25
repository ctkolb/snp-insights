#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Release documentation gates (R4B.*): README, AGENTS.md current state, the
accepted-limits register and the release status section.

Run standalone:  python -B tests/test_docs_release.py
Or as part of:   python tests/test_pipeline.py

Every gate is isolated (attempt()): a missing file, a missing phrase or any
exception fails only that one check, never the whole run. All inputs are the
tracked documents or the repository's synthetic fixtures; no real data is read.
The README commands are run through the real CLI against a synthetic raw file
with a temporary output directory outside the checkout.
"""
import contextlib
import hashlib
import io
import os
import re
import shlex
import sys
import tempfile
import tomllib
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("", "scripts"):
    _p = os.path.join(ROOT, _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

README = os.path.join(ROOT, "README.md")
AGENTS = os.path.join(ROOT, "AGENTS.md")
DOCS = os.path.join(ROOT, "docs")
LIMITS = os.path.join(DOCS, "accepted-limits.md")
RELEASE_DOC = os.path.join(DOCS, "release-v0.1.0.md")
CHECKPOINT = os.path.join(DOCS, "owner-checkpoint.md")
CURATION = os.path.join(DOCS, "panel-curation.md")
RAW_FIXTURE = os.path.join(ROOT, "fixtures", "raw.release.synthetic.txt")
GETTING_STARTED = os.path.join(DOCS, "getting-started.md")
REFERENCE_DATA = os.path.join(DOCS, "reference-data.md")
NEW_DOCS = (GETTING_STARTED, REFERENCE_DATA)
SOURCES_DIR = os.path.join(ROOT, "fixtures", "sources")
FETCH_TOOL = os.path.join(ROOT, "tools", "fetch_reference.py")
SAMPLE_PANEL = os.path.join(ROOT, "data", "panel.sample.json")
RELEASE_FIXTURES = (RAW_FIXTURE,
                    os.path.join(ROOT, "fixtures", "raw.release.synthetic.states.txt"))

# Pins computed on the base commit dbae23a (before ticket 4B).
LIMITS_BASE_BYTES = 6165
LIMITS_BASE_SHA256 = "a47fa1482c2758e842b8993179ef2c4a4695f4c41a30c831f3d67c51eae64565"
RELEASE_DOC_BASE_BYTES = 7325
RELEASE_DOC_BASE_SHA256 = "210f3984ed64f33a3946714bd794528aa0fc320da8fd38c1ca9774ecaddba1ad"

# sha256 of the existing register rows (one line each), AL-001..AL-013.
OLD_ROW_SHA256 = {
    "AL-001": "c3af101fddbdba246311a7e029a21aa2569a0aad6ffcabac47a18fa2876fb173",
    "AL-002": "65473dd36d289573542574b4db6fae18498e2c9d8565fea0919e8a883130cf97",
    "AL-003": "80933238d3da81af2b4fa59a6309e6c63dcf320030b5d44f33cb52de7750ddcb",
    "AL-004": "81bc3f4527db329cb1c0ff1443edf13dca3b9171e93d22cbe97e212ead517192",
    "AL-005": "f5d040fb4a28efede527455f6728063cdcac627359ec425d90012d5ec9e30854",
    "AL-006": "dff3f088b0e82533b55a4e98248d230660a35800b0d40a8c1c1d98beb11d2caf",
    "AL-007": "c6dfa7f58765e6ce2bdd28f3ff75377625fc5264463adb1bb11f3bd20378f1d7",
    "AL-008": "7b894fc3748d058592d7d6f250198f704184e64e24593121c61f5a377a683467",
    "AL-009": "7622775efa82886e85b4d78c9fc9f3f6a09bcfa0b6a08187de89f4b41c35e642",
    "AL-010": "7d1a90230d0f454faf6ac6d65abae5bc7d20278a8a7c106ad8cf42aaea68ec05",
    "AL-011": "2569552c81b322535bc05d33eb522b0c68190674f780479d1f726398018b31e8",
    "AL-012": "a0286df046ceda4dd3bdeadb9cb2f751b6c2343916872a8dbb85b4a820e480e1",
    "AL-013": "1e1b5fbd07cae9a0754309a090285193579e6c5c400d9021f0b9d5c361ec2266",
}

# sha256 of the owner-approved rows (decision D-4B-1), AL-014..AL-027.
NEW_ROW_SHA256 = {
    "AL-014": "58494aa6f39fc73651d214a1cd30d9a22dd755244bc62d83cea182010ed4f628",
    "AL-015": "faa6644ecd7960f7c307570ea74b65c782cca400ae7d849eb774e807db3b9294",
    "AL-016": "b61849adc8cd76d6c3c0755c53016b2eeeeef2eb0d2a47b12d0b2bca92ebe455",
    "AL-017": "41e76e26ffd58a6025f50903f8dc0e748a19f556fdbf8db65823e764a7ff87a8",
    "AL-018": "1619d3314e06b7ca66dd24e8b06d650994514a709a73dabfa27faf517ba46093",
    "AL-019": "4dacc2df91a9b61da79c9e5044e56dad8b16150bc7ca23af0044e5dcf4a99cac",
    "AL-020": "e36da288cdd85311c3ed1506c40e392c6bbbad571cd2e91a7a07c29fbf8a7467",
    "AL-021": "453c6cc9712c84e3aea62cada8e88ef2d2cfdd39fa8fb8986eb6b246b391c622",
    "AL-022": "eb083de2fbfa0d02228a9424cc5b4c59ca1e4916a09d621fed307433a8551f1f",
    "AL-023": "919ea45445f2e91e4b837d5dfa74849cfbec3489272feeefb0f5c30e124cf3ba",
    "AL-024": "64c09736c4ea2431e657e9506551b19160f8ff87aeb48cea281631a9cf87c8b7",
    "AL-025": "63b405b26ef6b3c9e42dec8e6f7d81a6040702dab2c43c21f8b96ea92cbf9b7f",
    "AL-026": "3f55e65d2674b9c623951d66e151c567e10f123dcd46d079b0d616f50b915572",
    "AL-027": "febfaee03490fa6dcdcf28a9771bf4805110a29b287af7a40cd51bac3305e20f",
}

AGENTS_CURRENT_STATE = """## Current state (v0.3.0 release run)

v0.3.0 is merged to main and tagged. It carries a curated nine-entry panel
(seven health entries, two trait entries), panel_version 0.3.0, the template
report, the owner-checkpoint procedure (docs/owner-checkpoint.md) and the
accepted-limits register (docs/accepted-limits.md). The package version is
0.3.0. The remaining steps are owner-only: the private real-data checkpoint
and repository branch protection.

The real-data checkpoint is owner-only, in a separate local environment. Keep
real DNA, findings, reports, private logs, and hashes outside all agent-accessible
repository, mailbox, export, and scratch trees. The owner may confirm local
completion without sharing results. Use synthetic fixtures in coding/review
sessions; reproduce failures synthetically before sharing them. Fetch public
references only from curated public targets, never personal coverage or genotypes.
Do not request private outputs for analysis."""

AGENTS_ROADMAP_ITEMS = (
    "2. **Curate a usable panel — DONE for v0.3.0** (seven health entries, two "
    "trait entries; see docs/panel-curation.md).",
    "9. **Docs polish — DONE for v0.1.0** (README release section, owner "
    "checkpoint, accepted limits).",
)

RELEASE_STATUS = """## Release status (recorded 2026-11-12)

Stages 1 to 4 of this plan are implemented on the release branch and independently
reviewed: the curation method and record (docs/panel-curation.md), the findings
contract extension (schema 1.2.0), the built release panel, the owner-checkpoint
procedure (docs/owner-checkpoint.md), and the readable template report. The accepted
limits are in docs/accepted-limits.md. Not yet done and owner-only: the private
real-data checkpoint, repository branch protection, hosted checks on the release
pull request, and the release tag; the existing v0.1.0 tag is preserved and not
replaced until the owner decides its disposition."""

RELEASE_AMENDMENT = (
    "Amendment (recorded 2026-11-12): the Definition of done asks for a small "
    "mixed panel. The v0.1.0 panel is health-only: no trait entry met the "
    "evidence bar, and counts are goals, not quotas (docs/accepted-limits.md "
    "AL-014). The release is complete with a health-only panel once the "
    "owner-only steps are done."
)

# Owner-approved closure rows (record: closure docs fixes after CODE-CLOSE r78).
CLOSURE_ROWS = {
    "AL-028": (
        "| AL-028 | REL | Tracked repository metadata contains the owner's "
        "identity: .github/CODEOWNERS (account handle) and .mailmap (name and "
        "address mapping, display only). Both predate this release. | LOW | "
        "CODEOWNERS needs the handle to work; .mailmap changes display only "
        "and cannot be removed from public history by editing it. | "
        "2026-11-12 | The owner wants anonymous history or a team owner in "
        "CODEOWNERS. |"
    ),
    "AL-029": (
        "| AL-029 | REL | No reserve entries exist for v0.1.0, so a "
        "coverage-poor outcome from the owner's private run has no reserve "
        "swap; the reserve rules in the curation method apply to later "
        "panels. | MEDIUM | No candidate met every criterion for a reserve. | "
        "2026-11-12 | The owner reports coverage-poor. |"
    ),
    "AL-030": (
        "| AL-030 | REL | The standing notice shown on model-written reports "
        "says \"external language model\" even when the model is local. "
        "Template-only reports carry a separate, accurate notice. | LOW | "
        "Conservative wording; model narration is outside the verified v0.1.0 "
        "scope (AL-016). | 2026-11-12 | Someone enables a local model and "
        "reads the notice as a statement about where the model runs. |"
    ),
}

CURATION_LIMITATIONS_SENTENCE = (
    "Whether the panel is adequate is the owner's aggregate coverage judgment "
    "(counts only). No reserves exist for v0.1.0, so a coverage-poor outcome "
    "has no reserve swap."
)
CURATION_LIMITATIONS_NEXT = "The pair rule trusts the captured placements and the"
CURATION_OLD_PHRASE = "with the reserves as the remedy"
CURATION_RESERVES_PARAGRAPH = (
    "For v0.1.0 no candidate remained that met every criterion for a reserve, "
    "so the record holds no reserve rows; the reserve rules above apply to "
    "later panels."
)

# The package, console script and pipeline version of this release (ticket B).
EXPECTED_VERSION = "0.3.0"

README_STATUS = (
    "Released as v0.3.0: panel version 0.3.0 and package version 0.3.0. "
    "The pipeline runs end to end on "
    "synthetic fixtures: parse, annotate, a curated nine-entry release "
    "panel, and a deterministic template report. The first real-file run is "
    "the owner's local checkpoint (docs/owner-checkpoint.md). Model "
    "narration (skeleton and full modes) and the online path exist but are "
    "not part of the verified scope. Known gaps and accepted limits are "
    "listed in docs/accepted-limits.md and DESIGN.md."
)

REQUIREMENTS_PHRASE = ("Python 3.12 or 3.14 (the CI matrix); other 3.12+ "
                       "versions are expected to work.")

# (README key phrase, document, phrase that document must carry)
LIMITATION_KEYS = (
    ("about 0.02% of the genome", CHECKPOINT, "about 0.02% of the genome"),
    ("array presence of each marker is not verified", CURATION,
     "array presence not verified"),
    ("seven health entries and two trait entries", CHECKPOINT,
     "seven health entries"),
    ("the panel is small and public", None, None),
    ("only template-only narration is verified", LIMITS,
     "Only template-only narration is verified"),
    ("confirmation by a clinical-grade test", CHECKPOINT,
     "confirmed by a clinical-grade test"),
    ("with no build statement is annotated against grch37 and the report says so",
     os.path.join(ROOT, "tools", "render_report.py"),
     "not stated in the file; assumed to match the panel"),
    ("x-linked and mitochondrial markers are excluded", CURATION,
     "autosomal only"),
    ("not independently verified", LIMITS, "not independently verifiable"),
)


class _Gate(AssertionError):
    pass


def _require(label, cond):
    if not cond:
        raise _Gate(label)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _flat(text):
    """Whitespace-normalized text, so wrapped prose matches a phrase."""
    return " ".join(text.split())


def _headings(text):
    """(line index, line) of every level-2 heading outside fenced blocks."""
    found, inside = [], False
    for i, line in enumerate(text.split("\n")):
        if line.strip().startswith("```"):
            inside = not inside
        elif not inside and line.startswith("## "):
            found.append((i, line))
    return found


def _section(text, heading):
    """Body of the level-2 section whose heading starts with `heading`."""
    lines = text.split("\n")
    marks = _headings(text)
    for n, (i, line) in enumerate(marks):
        if line[3:].startswith(heading):
            end = marks[n + 1][0] if n + 1 < len(marks) else len(lines)
            return "\n".join(lines[i + 1:end])
    _require("section %r not found" % heading, False)


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rows(text, ids):
    found = {}
    for line in text.split("\n"):
        m = re.match(r"\| (AL-\d{3}) \|", line)
        if m and m.group(1) in ids:
            found[m.group(1)] = line
    return found


def _cli(argv):
    """Run the real CLI in-process; returns (exit code, stdout, stderr)."""
    import snp_insights.cli as cli
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    return code, out.getvalue(), err.getvalue()


def _release_section():
    return _section(_read(README), "Release panel and your own file")


def _release_commands():
    """The `python -m snp_insights ...` lines of the README release section."""
    cmds = []
    for line in _release_section().split("\n"):
        s = line.strip()
        if s.startswith("python -m snp_insights "):
            cmds.append(shlex.split(s))
    return cmds


# ---------------------------------------------------------------- README gates

def _readme_release_panel_workflow():
    text = _read(README)
    flat = _flat(text)
    names = _h2(text)
    quick = names.index("Quickstart")
    rel = [i for i, n in enumerate(names)
           if n.startswith("Release panel and your own file")]
    _require("release section exists once", len(rel) == 1)
    _require("release section follows Quickstart", rel[0] > quick)
    _require("requirements phrase", REQUIREMENTS_PHRASE in flat)
    sec = _flat(_release_section())
    for phrase in ("seven health-related entries", "two trait entries",
                   "built reproducibly from public references",
                   "docs/panel-curation.md",
                   "data/targets.release-evidence.json",
                   "data/targets.release-panel.json",
                   "docs/owner-checkpoint.md",
                   "check-raw", "--no-hash", "--template-only", "--out-dir"):
        _require("release section lacks " + phrase, phrase in sec)
    low = sec.lower()
    for phrase in ("what was examined", "how many markers were measured",
                   "what each call state means",
                   "not measured means no information, not absence",
                   "evidence tiers", "limitations",
                   "never gives a diagnosis or a personal risk estimate"):
        _require("what-the-report-says lacks " + phrase, phrase in low)
    return True


def _readme_private_output_rule():
    sec = _flat(_release_section())
    for phrase in ("outside the repository", "shared or synced folder",
                   "any directory an agent tool can read",
                   "warns when `--out-dir` is inside the checkout",
                   "cannot see other locations"):
        _require("private-output rule lacks " + phrase, phrase in sec)
    _require("no online flag in the release section",
             "--accept-privacy-risk" not in sec and "--endpoint" not in sec)
    return True


def _readme_template_only_command():
    cmds = _release_commands()
    _require("exactly two commands", len(cmds) == 2)
    subs = [c[3] for c in cmds]
    _require("check-raw then run", subs == ["check-raw", "run"])
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as priv:
        _require("temp dir outside checkout",
                 not os.path.realpath(priv).startswith(os.path.realpath(ROOT) + os.sep))
        out_dir = os.path.join(priv, "out")
        results = []
        try:
            os.chdir(ROOT)
            for cmd in cmds:
                argv = []
                for tok in cmd[3:]:
                    if tok == "$PRIV/raw.txt":
                        tok = RAW_FIXTURE
                    elif tok.startswith("$PRIV/"):
                        tok = os.path.join(priv, tok[len("$PRIV/"):])
                    argv.append(tok)
                _require("unresolved placeholder in %r" % (cmd,),
                         not any("$" in a or "<" in a for a in argv))
                code, out, err = _cli(argv)
                results.append((argv, code, out, err))
        finally:
            os.chdir(cwd)
        argv0, code0, out0, _ = results[0]
        _require("check-raw exits 0", code0 == 0)
        _require("check-raw names the release panel",
                 "data/targets.release-panel.json" in cmds[0]
                 and "--no-hash" in cmds[0])
        _require("check-raw reports panel findings",
                 "Panel findings" in out0)
        argv1, code1, _, err1 = results[1]
        _require("run exits 0", code1 == 0)
        _require("run uses template-only", "--template-only" in cmds[1])
        _require("no inside-checkout warning", "WARNING" not in err1)
        for name in ("findings.json", "report.md", "report.ir.json",
                     "report.run.json"):
            _require("run wrote " + name,
                     os.path.isfile(os.path.join(out_dir, name)))
    return True


def _readme_limitations_list():
    sec = _flat(_section(_read(README), "Known limitations (v0.3.0)")).lower()
    for phrase, doc, doc_phrase in LIMITATION_KEYS:
        _require("README limitation lacks " + phrase, phrase in sec)
        if doc is not None:
            _require("%s lacks %r" % (os.path.basename(doc), doc_phrase),
                     doc_phrase in _flat(_read(doc)))
    items = [l for l in _section(_read(README), "Known limitations (v0.3.0)")
             .split("\n") if l.startswith("- ")]
    _require("one list item per limitation", len(items) >= len(LIMITATION_KEYS))
    return True


def _generic_text_problems(path):
    """Reasons a tracked document is not generic text (empty when clean)."""
    import guard
    emails = re.compile(r"[\w.+-]+@([\w-]+\.)+[\w-]+")
    british = re.compile(r"\b(colour|behaviour|favour|organis(?:e|ed|ing|ation)"
                         r"|analyse[sd]?|centre|licence|catalogue|grey)\b", re.I)
    text = _read(path)
    name = os.path.basename(path)
    problems = []
    for label, rx in guard.SECRET_PATTERNS:
        if rx.search(text):
            problems.append("%s: guard pattern %s" % (name, label))
    for m in emails.finditer(text):
        if not m.group(0).endswith("@example.com"):
            problems.append("%s: contact address %s" % (name, m.group(0)))
    if re.search(r"~[A-Za-z0-9_-]+/", text):
        problems.append("%s: tilde-home path" % name)
    hit = british.search(text)
    if hit:
        problems.append("%s: British spelling %s" % (name, hit))
    return problems


def _readme_no_real_paths_or_names():
    for path in (README, AGENTS, LIMITS, RELEASE_DOC, CHECKPOINT):
        problems = _generic_text_problems(path)
        _require("; ".join(problems), not problems)
    return True


def _version_consistent():
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        meta = tomllib.load(fh)
    _require("pyproject version", meta["project"]["version"] == EXPECTED_VERSION)
    import snp_insights
    _require("package version", snp_insights.__version__ == EXPECTED_VERSION)
    import json
    import snp_insights.cli as cli
    _require("pipeline version",
             cli._tool_module("annotate").PIPELINE_VERSION == EXPECTED_VERSION)
    # The version the annotator actually writes into findings.json, not only
    # the constant: run the real CLI on the synthetic fixture and release panel.
    with tempfile.TemporaryDirectory() as tmp:
        findings = os.path.join(tmp, "findings.json")
        panel = os.path.join(ROOT, "data", "targets.release-panel.json")
        code, _, _ = _cli(["annotate", RAW_FIXTURE, panel, "-o", findings])
        _require("synthetic annotation exits 0", code == 0)
        provenance = json.loads(_read(findings))["provenance"]
        _require("generated pipeline version",
                 provenance["pipeline_version"] == EXPECTED_VERSION)
    flat = _flat(_read(README))
    _require("README version output", "snp-insights %s" % EXPECTED_VERSION in flat)
    _require("getting-started version output",
             "snp-insights %s" % EXPECTED_VERSION in _flat(_read(GETTING_STARTED)))
    _require("README package-version status",
             "panel version 0.3.0 and package version %s" % EXPECTED_VERSION
             in flat)
    _require("README no longer calls itself a release candidate",
             "Release candidate" not in flat)
    return True


def _runtime_dependencies_empty():
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        meta = tomllib.load(fh)["project"]
    _require("dependencies empty", meta["dependencies"] == [])
    _require("only the schema extra",
             list(meta["optional-dependencies"]) == ["schema"]
             and meta["optional-dependencies"]["schema"] == ["jsonschema"])
    return True


def _readme_status_exact():
    status = _flat(_section(_read(README), "Status"))
    _require("status paragraph is exact", status == README_STATUS)
    return True


def _readme_testing_section_complete():
    sec = _section(_read(README), "Testing")
    listed = set(re.findall(r"`(tests/test_[a-z_]+\.py)`", sec))
    actual = sorted("tests/" + n for n in os.listdir(os.path.join(ROOT, "tests"))
                    if re.fullmatch(r"test_[a-z_]+\.py", n))
    _require("every test file is named", sorted(listed) == actual)
    flat = _flat(sec)
    _require("schema extra noted", "jsonschema" in flat)
    _require("standalone files noted",
             "test_release_panel.py" in flat.split("standalone")[-1]
             and "test_report_readability.py" in flat.split("standalone")[-1])
    return True


# ------------------------------------------------------------ AGENTS.md gates

def _agents_md_current_state():
    text = _read(AGENTS)
    _require("no NEXT STEP heading",
             not re.search(r"^## NEXT STEP", text, re.M))
    _require("old review paragraph gone",
             "Complete independent review of the initial CI/support stage"
             not in text)
    _require("Current state heading present",
             re.search(r"^## Current state \(v0\.3\.0 release run\)$", text, re.M))
    _require("current state block is exact", AGENTS_CURRENT_STATE in text)
    _require("current state precedes the roadmap",
             text.index("## Current state") < text.index("## Roadmap to beta"))
    roadmap = _section(text, "Roadmap to beta")
    for item in AGENTS_ROADMAP_ITEMS:
        _require("roadmap item missing: " + item[:30], _flat(item) in _flat(roadmap))
    _require("item 1 kept", "1. **Real-data validation** (after reviewed CI/local "
             "integration and release" in roadmap)
    _require("item 8 kept", "8. **Tests & CI — PRESENT.**" in roadmap)
    _require("old item 2 gone", "**Curate a usable panel.**" not in roadmap)
    _require("old item 9 gone", "**Docs polish.**" not in roadmap)
    return True


# ------------------------------------------------------------ register gates

def _accepted_limits_rows_append_only():
    raw = open(LIMITS, "rb").read()
    base = raw[:LIMITS_BASE_BYTES]
    _require("existing bytes unchanged (prefix)",
             hashlib.sha256(base).hexdigest() == LIMITS_BASE_SHA256)
    text = raw.decode("utf-8")
    old = _rows(text, set(OLD_ROW_SHA256))
    _require("AL-001..AL-013 all present", sorted(old) == sorted(OLD_ROW_SHA256))
    for rid, digest in OLD_ROW_SHA256.items():
        _require("%s changed" % rid, _sha(old[rid]) == digest)
    new = _rows(text, set(NEW_ROW_SHA256))
    _require("AL-014..AL-027 all present", sorted(new) == sorted(NEW_ROW_SHA256))
    for rid, digest in NEW_ROW_SHA256.items():
        _require("%s differs from the approved text" % rid, _sha(new[rid]) == digest)
    appended = raw[LIMITS_BASE_BYTES:].decode("utf-8").split("\n")
    appended = [l for l in appended if l.strip()]
    _require("only the approved rows AL-014..AL-052 were appended",
             [l[2:8] for l in appended]
             == sorted(NEW_ROW_SHA256) + sorted(CLOSURE_ROWS) + sorted(APPENDED_ROWS))
    return True


def _release_doc_status_section():
    raw = open(RELEASE_DOC, "rb").read()
    _require("existing bytes unchanged (prefix)",
             hashlib.sha256(raw[:RELEASE_DOC_BASE_BYTES]).hexdigest()
             == RELEASE_DOC_BASE_SHA256)
    text = raw.decode("utf-8")
    _require("one status heading",
             text.count("## Release status (recorded 2026-11-12)") == 1)
    _require("status section is exact", RELEASE_STATUS in text)
    tail = raw[RELEASE_DOC_BASE_BYTES:].decode("utf-8").strip()
    status = RELEASE_STATUS.strip()
    _require("tail starts with the status section", tail.startswith(status))
    _require("status section is followed only by the amendment",
             tail[len(status):].strip() == RELEASE_AMENDMENT)
    return True


# ------------------------------------------------- closure documentation gates

def _accepted_limits_rows_028_to_030_present():
    text = _read(LIMITS)
    found = _rows(text, set(CLOSURE_ROWS))
    _require("AL-028..AL-030 all present", sorted(found) == sorted(CLOSURE_ROWS))
    for rid, row in CLOSURE_ROWS.items():
        _require("%s differs from the approved text" % rid, found[rid] == row)
    _require("each closure row appears once",
             all(text.count(row) == 1 for row in CLOSURE_ROWS.values()))
    order = [l[2:8] for l in text.split("\n") if re.match(r"\| AL-\d{3} \|", l)]
    tail = len(APPENDED_ROWS)
    _require("rows are in order, 028..030 followed only by the appended rows",
             order == sorted(order) and order[-tail - 3:-tail] == sorted(CLOSURE_ROWS))
    return True


def _accepted_limits_existing_rows_unchanged_after_029():
    raw = open(LIMITS, "rb").read()
    _require("existing bytes unchanged (prefix)",
             hashlib.sha256(raw[:LIMITS_BASE_BYTES]).hexdigest()
             == LIMITS_BASE_SHA256)
    text = raw.decode("utf-8")
    pins = dict(OLD_ROW_SHA256)
    pins.update(NEW_ROW_SHA256)
    found = _rows(text, set(pins))
    _require("AL-001..AL-027 all present", sorted(found) == sorted(pins))
    for rid, digest in pins.items():
        _require("%s changed" % rid, _sha(found[rid]) == digest)
    return True


def _curation_limitations_no_reserves_sentence():
    text = _read(CURATION)
    limits = _flat(_section(text, "Limitations"))
    _require("new Limitations sentence present",
             CURATION_LIMITATIONS_SENTENCE in limits)
    _require("the rest of the line follows the new sentence unchanged",
             CURATION_LIMITATIONS_SENTENCE + " " + CURATION_LIMITATIONS_NEXT
             in limits)
    _require("old phrase gone from Limitations", CURATION_OLD_PHRASE not in limits)
    _require("old phrase gone from the record",
             CURATION_OLD_PHRASE not in _flat(text))
    _require("edit is below the Tables heading",
             text.index(CURATION_LIMITATIONS_SENTENCE.split(" (")[0])
             > text.index("\n## Tables\n"))
    return True


def _curation_reserves_section_states_none_exist():
    text = _read(CURATION)
    sec = _section(text, "Reserves and goals")
    _require("paragraph present once in the section",
             _flat(sec).count(CURATION_RESERVES_PARAGRAPH) == 1)
    paras = [p for p in re.split(r"\n\s*\n", sec) if p.strip()]
    _require("paragraph is the last in the section",
             _flat(paras[-1]) == CURATION_RESERVES_PARAGRAPH)
    _require("paragraph is not above the Tables heading",
             _flat(text).count(CURATION_RESERVES_PARAGRAPH) == 1
             and text.index("\n## Reserves and goals\n")
             > text.index("\n## Tables\n"))
    return True


def _release_doc_dod_amendment():
    text = _read(RELEASE_DOC)
    _require("amendment present once", text.count(RELEASE_AMENDMENT) == 1)
    status = text.index("## Release status (recorded 2026-11-12)")
    _require("amendment follows the Release status section",
             text.index(RELEASE_AMENDMENT) > status)
    _require("amendment is after the status section text",
             text.index(RELEASE_AMENDMENT) > text.index(
                 "replaced until the owner decides its disposition."))
    _require("amendment ends the document",
             text.rstrip("\n").endswith(RELEASE_AMENDMENT))
    return True


# ------------------------------------------------ getting-started gates (R5.*)

README_PATHS_HEADING = "Pick your path"
GS_HEADINGS = (
    "What this tool does and does not do", "Prerequisites",
    "Getting your raw file", "The pieces in plain words",
    "What each command reads and writes", "Reading the report", "Glossary",
    "Troubleshooting and exit codes", "Next steps",
)
RD_HEADINGS = (
    "Why reference data exists", "The sources",
    "Do you need to fetch anything", "What fetch writes",
    "Flags for fetch", "Flags for build-panel", "The synthetic samples",
    "Manual full-file downloads", "Release-format targets",
    "SNPedia (manual)",
)
README_KEEP_HEADINGS = (
    "How it works", "Why", "Requirements", "Known limitations (v0.3.0)",
    "Privacy & safety", "Status", "Contributing", "License", "Testing",
)
DOC_MAP_TARGETS = (
    "docs/getting-started.md", "docs/reference-data.md",
    "docs/owner-checkpoint.md", "docs/panel-curation.md",
    "docs/accepted-limits.md", "docs/security.md", "DESIGN.md",
)
GLOSSARY_TERMS = (
    "rsID", "genotype", "allele", "effect allele", "no-call", "genome build",
    "carrier", "ClinVar review stars", "allele frequency", "array",
    "panel", "tier",
)
PIECES = ("raw file", "targets file", "evidence file", "panel", "findings.json",
          "report.ir.json", "report.md", "targets.sample.json",
          "targets.carrier.json", "targets.traits.json", "targets.release")
SOURCE_NAMES = ("dbSNP", "ClinVar", "gnomAD", "GWAS Catalog", "Open Targets",
                "SNPedia", "OMIM", "MedlinePlus", "GeneReviews")
MANUAL_LINKS = (
    "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz",
    "https://ftp.ncbi.nlm.nih.gov/snp/latest_release/VCF/",
    "https://ftp.ncbi.nlm.nih.gov/snp/",
    "https://gnomad.broadinstitute.org/downloads",
    "https://www.ebi.ac.uk/gwas/docs/file-downloads",
)
# Sizes the docs may state: only figures already in the README, `fetch --help`
# or the code (no new numbers).
ALLOWED_SIZES = {"0.5 GB", "70 MB", "90 GB", "5 GB"}
SMALL_CACHE_NAMES = ("clinvar.tsv", "dbsnp.tsv", "gnomad.small.vcf", "gwas.tsv",
                     "manifest.json")
# Commands that are never run by the tests: they use the network or a private
# file (checked per command by _skip_reason).
OFFLINE_SUBS = ("check-raw", "annotate", "narrate", "run", "build-panel")


def _h2(text):
    return [line[3:] for _, line in _headings(text)]


def _fences(text):
    """(info string, lines) for every fenced block, in order."""
    blocks, info, buf = [], None, []
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            if info is None:
                info, buf = line.strip()[3:].strip(), []
            else:
                blocks.append((info, buf))
                info = None
        elif info is not None:
            buf.append(line)
    return blocks


def _unfenced(text):
    out, inside = [], False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            inside = not inside
        elif not inside:
            out.append(line)
    return "\n".join(out)


def _fenced_commands(text):
    """Logical `python -m snp_insights ...` lines (continuations joined)."""
    cmds = []
    for info, lines in _fences(text):
        if info == "report":
            continue
        joined, cur = [], ""
        for line in lines:
            if line.rstrip().endswith("\\"):
                cur += line.rstrip()[:-1] + " "
                continue
            joined.append(cur + line)
            cur = ""
        for line in joined:
            s = line.strip()
            if s.startswith("python -m snp_insights"):
                cmds.append(shlex.split(s))
    return cmds


def _skip_reason(argv):
    """Why a command is not run (network or private input), else None."""
    if argv and argv[0] == "fetch":
        return "network"
    if "--endpoint" in argv:
        return "online"
    for tok in argv:
        if any(m in tok for m in ("$", "<", ">", "~", "/path/to", "PRIV")):
            return "placeholder"
    return None


def _run_doc_commands(path, text=None):
    """Run every offline fenced command of a document in order, in a temp dir
    outside the checkout. Returns (results, skipped); each result is
    (argv, code, stdout, stderr, out_dir)."""
    text = _read(path) if text is None else text
    results, skipped = [], []
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        _require("temp dir outside checkout",
                 not os.path.realpath(tmp).startswith(os.path.realpath(ROOT) + os.sep))
        try:
            os.chdir(ROOT)
            for cmd in _fenced_commands(text):
                argv = [t.replace("$OUT", tmp) for t in cmd[3:]]
                reason = _skip_reason(argv)
                if reason is not None:
                    skipped.append((cmd, reason))
                    continue
                if argv and argv[0] == "run":
                    _require("run names --out-dir: %r" % (cmd,), "--out-dir" in argv)
                for flag in ("-o", "--out", "--out-dir"):
                    if flag in argv:
                        val = argv[argv.index(flag) + 1]
                        _require("%s outside the checkout in %r" % (flag, cmd),
                                 val.startswith(tmp))
                code, out, err = _cli(argv)
                results.append((argv, code, out, err, tmp))
                if argv[:1] == ["build-panel"] and "data/targets.sample.json" in argv:
                    outp = argv[argv.index("-o") + 1]
                    _require("sample build reproduces data/panel.sample.json",
                             open(outp, "rb").read() == open(SAMPLE_PANEL, "rb").read())
        finally:
            os.chdir(cwd)
    return results, skipped


def _help_flags(sub):
    code, out, _ = _cli([sub, "--help"])
    _require("%s --help exits 0" % sub, code == 0)
    return set(re.findall(r"--[a-z][a-z-]*", out)) - {"--help"}


def _slug(heading):
    s = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return s.replace(" ", "-")


def _link_problems(path):
    text = _unfenced(_read(path))
    base = os.path.dirname(path)
    problems = []
    for target in re.findall(r"\[[^\]]*\]\(([^)\s]+)\)", text):
        if re.match(r"(https?:|mailto:)", target):
            continue
        rel, _, frag = target.partition("#")
        dest = path if not rel else os.path.normpath(os.path.join(base, rel))
        if not os.path.isfile(dest) or not os.path.realpath(dest).startswith(
                os.path.realpath(ROOT) + os.sep):
            problems.append("%s: broken link %s" % (os.path.basename(path), target))
            continue
        if frag and dest.endswith(".md"):
            heads = [_slug(l.lstrip("#")) for l in _read(dest).split("\n")
                     if re.match(r"#{1,6} ", l)]
            if frag not in heads:
                problems.append("%s: missing anchor %s" % (os.path.basename(path), target))
    return problems


def _readme_pick_your_path():
    text = _read(README)
    names = _h2(text)
    _require("Pick your path section exists once", names.count(README_PATHS_HEADING) == 1)
    _require("Pick your path precedes Quickstart",
             names.index(README_PATHS_HEADING) < names.index("Quickstart"))
    _require("opening box kept before the paths",
             text.index("> **Not medical advice.**") < text.index("## " + README_PATHS_HEADING))
    sec = _flat(_section(text, README_PATHS_HEADING))
    for label in ("Path A", "Path B", "Path C"):
        _require("paths section lacks " + label, label in sec)
    for phrase in ("synthetic", "your own", "rebuild", "docs/getting-started.md",
                   "docs/reference-data.md", "no network"):
        _require("paths section lacks " + phrase, phrase in sec)
    _require("only three paths", "Path D" not in sec)
    return True


def _readme_links_new_docs():
    flat = _flat(_read(README))
    for target in NEW_DOCS:
        _require("%s exists" % os.path.basename(target), os.path.isfile(target))
        rel = os.path.relpath(target, ROOT)
        _require("README links " + rel, "](%s" % rel in flat)
    return True


def _readme_documentation_map():
    sec = _flat(_section(_read(README), "Documentation map"))
    for target in DOC_MAP_TARGETS:
        _require("map links " + target, "](%s" % target in sec)
        _require("map target exists " + target,
                 os.path.isfile(os.path.join(ROOT, target)))
    return True


def _readme_kept_sections_and_moved_content():
    text = _read(README)
    names = _h2(text)
    for name in README_KEEP_HEADINGS:
        _require("README lost section " + name, name in names)
    _require("Fetching section moved out", "Fetching reference data" not in names)
    _require("SNPedia heading moved out", "SNPedia (optional, manual)" not in text)
    flat = _flat(text)
    _require("manual links moved out", "ftp.ncbi.nlm.nih.gov/pub/clinvar" not in flat)
    ref = [n for n in names if n.startswith("Reference data")]
    _require("one Reference data pointer", len(ref) == 1)
    sec = _section(text, "Reference data")
    _require("pointer links reference-data.md", "](docs/reference-data.md" in sec)
    body = [l for l in sec.split("\n") if l.strip()]
    _require("pointer stays short (3 to 8 lines)", 3 <= len(body) <= 8)
    _require("narrator harness stays, two commands",
             text.count("python tools/harness.py") == 2)
    return True


def _readme_quickstart_a():
    text = _read(README)
    sec = _section(text, "Quickstart")
    flat = _flat(sec)
    _require("Quickstart A subsection", "### A." in sec and "### B." in sec)
    for phrase in ("python -m venv", "pip install jsonschema", "--version",
                   "fixtures/raw.release.synthetic.txt",
                   "data/targets.release-panel.json", "--template-only",
                   "outside", "synthetic", "findings.json", "report.md",
                   "report.ir.json", "report.run.json"):
        _require("Quickstart lacks " + phrase, phrase in flat)
    _require("Python version check shown", "--version" in flat and "3.12" in flat)
    _require("raw-file source named", "DNA data" in flat and "zip" in flat)
    _require("no fetch needed stated",
             "do not need to fetch" in flat.lower() or "no need to fetch" in flat.lower())
    return True


def _readme_quickstart_commands_run():
    text = _read(README)
    sec = "## Quickstart\n" + _section(text, "Quickstart")
    results, skipped = _run_doc_commands(README, sec)
    _require("Quickstart commands found", len(results) >= 2)
    runs = [r for r in results if r[0][:1] == ["run"]]
    _require("synthetic run present",
             any("fixtures/raw.release.synthetic.txt" in r[0]
                 and "data/targets.release-panel.json" in r[0]
                 and "--template-only" in r[0] for r in runs))
    for argv, code, _, err, _tmp in results:
        _require("exit 0 for %r (got %s)" % (argv, code), code == 0)
        _require("no inside-checkout warning for %r" % (argv,), "WARNING" not in err)
    for cmd, reason in skipped:
        _require("only private-file placeholders skipped in Quickstart: %r" % (cmd,),
                 reason == "placeholder")
    return True


def _new_docs_headings():
    for path, heads in ((GETTING_STARTED, GS_HEADINGS), (REFERENCE_DATA, RD_HEADINGS)):
        _require("%s exists" % os.path.basename(path), os.path.isfile(path))
        text = _read(path)
        _require("%s starts with a title" % os.path.basename(path),
                 text.startswith("# "))
        names = _h2(text)
        pos = -1
        for h in heads:
            idx = [i for i, n in enumerate(names) if n.startswith(h)]
            _require("%s lacks heading %r" % (os.path.basename(path), h), len(idx) == 1)
            _require("%s heading %r out of order" % (os.path.basename(path), h),
                     idx[0] > pos)
            pos = idx[0]
    return True


def _docs_relative_links_resolve():
    problems = []
    for path in (README,) + NEW_DOCS:
        _require("%s exists" % os.path.basename(path), os.path.isfile(path))
        problems += _link_problems(path)
    _require("; ".join(problems), not problems)
    return True


def _docs_offline_commands_run():
    seen = set()
    for path, minimum in ((GETTING_STARTED, 4), (REFERENCE_DATA, 1)):
        _require("%s exists" % os.path.basename(path), os.path.isfile(path))
        results, skipped = _run_doc_commands(path)
        name = os.path.basename(path)
        _require("%s: runnable commands found (>=%d)" % (name, minimum),
                 len(results) >= minimum)
        for argv, code, _, err, _tmp in results:
            _require("%s: exit 0 for %r (got %s)" % (name, argv, code), code == 0)
            _require("%s: no inside-checkout warning for %r" % (name, argv),
                     "WARNING" not in err)
            if path == GETTING_STARTED and argv:
                seen.add(argv[0])
        for cmd, reason in skipped:
            _require("%s: unexpected skip %r (%s)" % (name, cmd, reason),
                     reason in ("network", "online", "placeholder"))
    _require("getting-started runs check-raw, annotate, narrate and run: %s" % sorted(seen),
             {"check-raw", "annotate", "narrate", "run"} <= seen)
    return True


def _docs_flags_exist_in_help():
    helps = {sub: _help_flags(sub) for sub in ("build-panel", "fetch")}
    for path in NEW_DOCS:
        _require("%s exists" % os.path.basename(path), os.path.isfile(path))
        for cmd in _fenced_commands(_read(path)):
            if cmd[3:4] and cmd[3] in helps:
                for tok in cmd[4:]:
                    if tok.startswith("--"):
                        flag = tok.split("=", 1)[0]
                        _require("%s: %s is not a %s flag" % (
                            os.path.basename(path), flag, cmd[3]),
                            flag in helps[cmd[3]])
    ref = _read(REFERENCE_DATA)
    for sub, heading in (("fetch", "Flags for fetch"),
                         ("build-panel", "Flags for build-panel")):
        sec = _section(ref, heading)
        named = set(re.findall(r"`(--[a-z][a-z-]*)", sec))
        _require("%s table names only real flags: %s" % (
            sub, sorted(named - helps[sub])), named <= helps[sub])
        _require("%s table covers every flag: missing %s" % (
            sub, sorted(helps[sub] - named)), helps[sub] <= named)
    return True


def _reference_data_names_sources_fixtures_and_files():
    ref = _read(REFERENCE_DATA)
    flat = _flat(ref)
    sources = _flat(_section(ref, "The sources"))
    for name in SOURCE_NAMES:
        _require("sources section lacks " + name, name in sources)
    for phrase in ("verify the current terms", "not legal advice",
                   "CC BY-NC-SA 3.0", "link-only"):
        _require("terms line lacks " + phrase, phrase in flat)
    for fname in sorted(os.listdir(SOURCES_DIR)):
        _require("reference-data.md omits fixtures/sources/" + fname, fname in flat)
    _require("states fixtures are synthetic", "synthetic" in _flat(
        _section(ref, "The synthetic samples")))
    for url in MANUAL_LINKS:
        _require("manual link missing " + url, url in ref)
    return True


def _reference_data_cache_names_match_code():
    code = _read(FETCH_TOOL)
    for name in SMALL_CACHE_NAMES:
        _require("fetch_reference.py no longer writes %s" % name,
                 '"%s"' % name in code)
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    try:
        import fetch_reference
        full_names = [os.path.basename(u.split("?")[0])
                      for u in fetch_reference.FULL_URLS.values()]
    finally:
        sys.path.pop(0)
    sec = _flat(_section(_read(REFERENCE_DATA), "What fetch writes"))
    for name in SMALL_CACHE_NAMES + tuple(full_names):
        _require("cache section lacks " + name, name in sec)
    _require("states how build-panel --cache fills paths",
             "--cache" in sec and "unset" in sec)
    return True


def _new_docs_content_pins():
    gs = _read(GETTING_STARTED)
    flat = _flat(gs)
    pieces = _flat(_section(gs, "The pieces in plain words"))
    for term in PIECES:
        _require("pieces section lacks " + term, term in pieces)
    gloss = _section(gs, "Glossary")
    items = [l.lower() for l in gloss.split("\n") if l.startswith("- **")]
    for term in GLOSSARY_TERMS:
        _require("glossary lacks an entry for " + term,
                 any(i.startswith("- **%s:**" % term.lower())
                     or i.startswith("- **%s (" % term.lower()) for i in items))
    _require("glossary names GRCh37", "GRCh37" in gloss)
    cmds = _flat(_section(gs, "What each command reads and writes"))
    for sub in ("check-raw", "annotate", "narrate", "run", "fetch", "build-panel"):
        _require("commands section lacks " + sub, sub in cmds)
    _require("commands section states network use", "network" in cmds)
    trouble = _flat(_section(gs, "Troubleshooting and exit codes"))
    for phrase in ("python3", "--force", "--panel", "symlink", "exit code 1",
                   "exit code 2", "--accept-privacy-risk", "No module named"):
        _require("troubleshooting lacks " + phrase, phrase in trouble)
    for phrase in ("not medical advice", "not measured means no information"):
        _require("getting-started lacks " + phrase, phrase in flat.lower())
    ref = _read(REFERENCE_DATA)
    rflat = _flat(ref)
    for phrase in ("--curated-evidence data/targets.release-evidence.json",
                   "docs/panel-curation.md", "--yes", "never touches the network",
                   "data/targets.release-panel.json"):
        _require("reference-data lacks " + phrase, phrase in rflat)
    decision = _flat(_section(ref, "Do you need to fetch anything"))
    _require("decision section answers no for v%s" % EXPECTED_VERSION,
             "v" + EXPECTED_VERSION in decision and "no" in decision.lower())
    for path in NEW_DOCS:
        sizes = set(re.findall(r"\d+(?:\.\d+)? ?(?:GB|MB|GiB)\b", _read(path)))
        _require("%s: sizes beyond the known figures: %s" % (
            os.path.basename(path), sorted(sizes - ALLOWED_SIZES)),
            sizes <= ALLOWED_SIZES)
    return True


def _report_excerpts_are_real():
    report = []
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(ROOT)
            for i, fixture in enumerate(RELEASE_FIXTURES):
                out_dir = os.path.join(tmp, "o%d" % i)
                code, _, _ = _cli(["run", fixture, "data/targets.release-panel.json",
                                   "--out-dir", out_dir, "--template-only"])
                _require("fixture run exits 0: %s" % os.path.basename(fixture),
                         code == 0)
                report += _read(os.path.join(out_dir, "report.md")).split("\n")
        finally:
            os.chdir(cwd)
    for path in (README, GETTING_STARTED):
        _require("%s exists" % os.path.basename(path), os.path.isfile(path))
        blocks = [b for b in _fences(_read(path)) if b[0] == "report"]
        _require("%s has a report excerpt block" % os.path.basename(path), blocks)
        for _, lines in blocks:
            body = [l for l in lines if l.strip() and l.strip() != "..."]
            _require("%s: excerpt block is not empty" % os.path.basename(path), body)
            for line in body:
                _require("%s: excerpt line is not in a real report: %r" % (
                    os.path.basename(path), line), line in report)
    return True


def _new_docs_generic_text():
    problems = []
    for path in (README,) + NEW_DOCS:
        _require("%s exists" % os.path.basename(path), os.path.isfile(path))
        problems += _generic_text_problems(path)
        text = _read(path)
        bad = [c for c in text if 0x1F000 <= ord(c) <= 0x1FAFF
               or 0x2600 <= ord(c) <= 0x27BF or ord(c) == 0xFE0F]
        if bad:
            problems.append("%s: emoji %r" % (os.path.basename(path), bad[:3]))
        for m in re.finditer(r"(?:/Users|/home)/[A-Za-z0-9_.-]+", text):
            problems.append("%s: home path %s" % (os.path.basename(path), m.group(0)))
    _require("; ".join(problems), not problems)
    return True


# ------------------------------------------------- R5 fixes after review CODE r81

BUILD_PANEL_TOOL = os.path.join(ROOT, "tools", "build_panel.py")
HARNESS_TOOL = os.path.join(ROOT, "tools", "harness.py")
ALL_SUBS = ("check-raw", "annotate", "narrate", "run", "build-panel", "fetch")
FILE_NAME_RE = re.compile(r"`([A-Za-z0-9_.-]+\.(?:tsv|vcf|gz|bgz|zip|json))`")

# (flag, key words its description must contain), in the order of each table.
BUILD_PANEL_FLAG_ROWS = (
    ("--targets", ("targets",)),
    ("--clinvar", ("ClinVar", "variant_summary")),
    ("--gnomad", ("gnomAD", "VCF")),
    ("--dbsnp", ("dbSNP", "VCF", "coordinates")),
    ("--gwas", ("GWAS Catalog", "trait")),
    ("--snpedia", ("rsid", "magnitude")),
    ("--dbsnp-merge", ("RsMergeArch", "old rsID")),
    ("--curated-evidence", ("curated", "release-format")),
    ("--cache", ("fetch", "source paths")),
    ("--merge-direction", ("RsMergeArch", "high-to-low", "low-to-high")),
    ("--dbsnp-release", ("label", "dbSNP release")),
    ("--clinvar-release", ("label", "ClinVar release")),
    ("--gnomad-release", ("label", "gnomAD release")),
    ("--gwas-release", ("label", "GWAS Catalog release")),
    ("--snpedia-release", ("label", "SNPedia release")),
    ("--retrieved-at", ("retrieval time",)),
    ("--out", ("write the panel", "stdout")),
)
FETCH_FLAG_ROWS = (
    ("--targets", ("targets JSON", "small mode")),
    ("--full", ("complete files",)),
    ("--cache", ("cache directory", "~/.cache/snp-insights")),
    ("--email", ("NCBI", "SNP_INSIGHTS_EMAIL")),
    ("--accept-license", ("SNPedia license", "not downloaded")),
    ("--dry-run", ("plan",)),
    ("--no-gwas", ("skip the GWAS step",)),
    ("--gwas-mode", ("ot", "Open Targets", "full")),
    ("--clinvar-mode", ("summary", "api", "E-utilities")),
    ("--sizes", ("size",)),
    ("--yes", ("5 GB",)),
)
OLD_SYMLINK_SENTENCE = "will not write through a symlink, even with"


def _table_rows(section_text):
    """{first cell: description} for each `| cell | cell |` row; a repeated
    first cell is a gate failure."""
    rows = {}
    for line in section_text.split("\n"):
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if not line.startswith("|") or len(cells) != 2 or set(cells[0]) <= set("- "):
            continue
        if cells[0] in ("Flag", "What goes there", "Left unset", "What it does"):
            continue
        _require("table row repeated: %s" % cells[0], cells[0] not in rows)
        rows[cells[0]] = cells[1]
    return rows


def _flag_table_matches_pins(heading, pins):
    rows = _table_rows(_section(_read(REFERENCE_DATA), heading))
    expected = ["`%s`" % flag for flag, _ in pins]
    _require("%s table rows are %s, found %s" % (heading, expected, list(rows)),
             list(rows) == expected)
    for flag, words in pins:
        desc = rows["`%s`" % flag]
        for word in words:
            _require("%s row %s lacks %r" % (heading, flag, word), word in desc)
    return True


def _reference_data_cache_table_matches_code():
    """Per row, the cache-lookup table equals the resolve() calls in build_panel,
    and every file name in the document is one the code reads or writes."""
    code = _read(BUILD_PANEL_TOOL)
    resolved = {}
    for m in re.finditer(r"args\.(\w+) = resolve\(args\.\w+, ([^)]*)\)", code):
        flag = "--" + m.group(1).replace("_", "-")
        resolved[flag] = tuple(re.findall(r'"([^"]+)"', m.group(2)))
    _require("found the resolve() calls in build_panel.py: %s" % sorted(resolved),
             len(resolved) == 6)
    sec = _section(_read(REFERENCE_DATA), "What fetch writes")
    rows = _table_rows(sec)
    _require("cache table has one row per resolved flag: %s" % list(rows),
             sorted(rows) == sorted("`%s`" % f for f in resolved))
    for flag, names in resolved.items():
        listed = tuple(re.findall(r"`([^`]+)`", rows["`%s`" % flag]))
        listed = tuple(n for n in listed if FILE_NAME_RE.fullmatch("`%s`" % n))
        _require("cache table row %s lists %s but build_panel.py reads %s" % (
            flag, listed, names), listed == names)
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    try:
        import fetch_reference
        full_names = {os.path.basename(u.split("?")[0])
                      for u in fetch_reference.FULL_URLS.values()}
    finally:
        sys.path.pop(0)
    known = (set(SMALL_CACHE_NAMES) | full_names
             | {n for names in resolved.values() for n in names}
             | set(os.listdir(SOURCES_DIR)))
    for path in (REFERENCE_DATA, GETTING_STARTED, README):
        for name in FILE_NAME_RE.findall(_unfenced(_read(path))):
            if "/" in name or name in {"findings.json", "report.ir.json",
                                       "report.run.json", "panel.sample.json"}:
                continue
            _require("%s names a cache or source file the code does not use: %s" % (
                os.path.basename(path), name), name in known)
    return True


def _reference_data_flag_rows_match_flags():
    _flag_table_matches_pins("Flags for build-panel", BUILD_PANEL_FLAG_ROWS)
    _flag_table_matches_pins("Flags for fetch", FETCH_FLAG_ROWS)
    cache_rows = _table_rows(_section(_read(REFERENCE_DATA), "What fetch writes"))
    for flag, word in (("--clinvar", "variant_summary"), ("--dbsnp", "GCF_"),
                       ("--gnomad", "gnomad"), ("--gwas", "gwas"),
                       ("--snpedia", "snpedia"), ("--dbsnp-merge", "RsMergeArch")):
        _require("cache table row %s does not name a %s file" % (flag, word),
                 word.lower() in cache_rows["`%s`" % flag].lower())
    return True


def _readme_where_to_keep_files_pinned():
    text = _read(README)
    paras = [p for p in text.split("\n\n")
             if p.lstrip().startswith("**Where to keep your files.**")]
    _require("exactly one 'Where to keep your files' paragraph", len(paras) == 1)
    flat = _flat(paras[0])
    ordered = ("Keep the raw file and all outputs in a private directory outside "
               "the repository",
               "any shared or synced folder",
               "any directory an agent tool can read",
               "`run` warns when `--out-dir` is inside the checkout",
               "but cannot see other locations",
               "a synced folder",
               "so keeping to this rule is up to you")
    at = -1
    for phrase in ordered:
        found = flat.find(phrase)
        _require("private-output paragraph lacks %r" % phrase, found >= 0)
        _require("private-output paragraph has %r out of order" % phrase, found > at)
        at = found
    _require("the paragraph sits in the release section",
             "**Where to keep your files.**" in _release_section())
    return True


def _symlink_statements_text():
    """The three statements about a symlink (README, troubleshooting item,
    exit-code row), and the old sentence nowhere."""
    readme, gs = _read(README), _read(GETTING_STARTED)
    for path in (README,) + NEW_DOCS:
        _require("old symlink sentence still in %s" % os.path.basename(path),
                 OLD_SYMLINK_SENTENCE not in _flat(_read(path)))
    item = [p for p in _section(gs, "Troubleshooting and exit codes").split("\n- ")
            if p.lstrip("- ").startswith("**A refusal with exit code 1: symlink")]
    _require("one troubleshooting item on a symlink or file", len(item) == 1)
    flat = _flat(item[0])
    for phrase in ("refuses an output file that is a symlink",
                   "that is a symlink (exit code 1, even with `--force`)",
                   "an `--out-dir` that exists as a file (exit code 1)",
                   "A symlink used as `--out-dir` that points to a directory",
                   "is not refused",
                   "follows it and writes there",
                   "normal private directory",
                   "not a symlink",
                   "compares resolved paths",
                   "up to you"):
        _require("troubleshooting item lacks %r" % phrase, phrase in flat)
    rows = [l for l in gs.split("\n") if l.startswith("| 1 |")]
    _require("one exit-code-1 row", len(rows) == 1)
    _require("exit-code row qualifies the symlink: %r" % rows[0],
             "an output file that is a symlink" in rows[0]
             and rows[0].count("symlink") == 1)
    para = [b for b in readme.split("\n- ") if b.startswith("It **never overwrites**")]
    _require("one README bullet on overwriting", len(para) == 1)
    rflat = _flat(para[0])
    for phrase in ("refuses an output file that is a symlink",
                   "an `--out-dir` that is a file even with `--force`",
                   "A symlink used as `--out-dir` that points to a directory is "
                   "not refused",
                   "`run` follows it",
                   "normal private directory"):
        _require("README bullet lacks %r" % phrase, phrase in rflat)
    return True


def _symlink_statements_match_cli():
    """Each claim in the symlink statements, run through the real CLI in a
    temporary directory outside the checkout."""
    base = ["run", RAW_FIXTURE, "data/targets.release-panel.json", "--template-only"]
    names = ("findings.json", "report.md", "report.ir.json", "report.run.json")
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        _require("temp dir outside checkout",
                 not os.path.realpath(tmp).startswith(os.path.realpath(ROOT) + os.sep))
        try:
            os.chdir(ROOT)
            # an output file that is a symlink: refused, even with --force
            real = os.path.join(tmp, "b-out")
            os.makedirs(real)
            elsewhere = os.path.join(tmp, "elsewhere.json")
            os.symlink(elsewhere, os.path.join(real, "findings.json"))
            for extra in ([], ["--force"]):
                code, _, err = _cli(base + ["--out-dir", real] + extra)
                _require("output-file symlink %s: exit 1, got %s" % (extra, code),
                         code == 1 and "refusing to write through a symlink" in err)
                _require("nothing written through the symlink",
                         not os.path.lexists(elsewhere)
                         and os.listdir(real) == ["findings.json"])
            # an --out-dir that is a file: refused, even with --force
            afile = os.path.join(tmp, "c-file")
            with open(afile, "w") as fh:
                fh.write("x")
            for extra in ([], ["--force"]):
                code, _, err = _cli(base + ["--out-dir", afile] + extra)
                _require("out-dir file %s: exit 1, got %s" % (extra, code),
                         code == 1 and "is not a directory" in err)
                _require("file untouched", _read(afile) == "x")
            # a symlink used as --out-dir that points to a directory: followed
            target = os.path.join(tmp, "a-target")
            os.makedirs(target)
            link = os.path.join(tmp, "a-link")
            os.symlink(target, link)
            code, _, err = _cli(base + ["--out-dir", link])
            _require("directory symlink is followed (exit 0), got %s: %s" % (
                code, err[-200:]), code == 0)
            _require("files landed in the symlink's target: %s" % os.listdir(target),
                     sorted(os.listdir(target)) == sorted(names))
            # the inside-the-checkout warning compares resolved paths; a dangling
            # link into the checkout writes nothing (the run stops after it)
            ghost = os.path.join(ROOT, "zz-r5-absent-target")
            _require("ghost target is absent", not os.path.lexists(ghost))
            into = os.path.join(tmp, "d-link")
            os.symlink(ghost, into)
            code, _, err = _cli(base + ["--out-dir", into])
            _require("warning fires for a link into the checkout: %r" % err[:200],
                     "inside the repository checkout" in err)
            _require("nothing created in the checkout", not os.path.lexists(ghost))
        finally:
            os.chdir(cwd)
    return True


def _docs_flags_are_real():
    """Every `--flag` the README and the guides write, in prose or in a fenced
    block, is a real flag of the CLI or of tools/harness.py."""
    real = set()
    for sub in ALL_SUBS:
        real |= _help_flags(sub)
    real |= {"--version"}
    real |= set(re.findall(r'add_argument\("(--[a-z][a-z-]*)"', _read(HARNESS_TOOL)))
    for path in (README,) + NEW_DOCS:
        mentioned = set(re.findall(r"--[a-z][a-z-]*", _read(path)))
        _require("%s writes flags that do not exist: %s" % (
            os.path.basename(path), sorted(mentioned - real - {"--help"})),
            mentioned <= real | {"--help"})
    for path in (README,) + NEW_DOCS:
        for cmd in _fenced_commands(_read(path)):
            for tok in cmd[4:]:
                if tok.startswith("--template-"):
                    _require("%s: %r" % (os.path.basename(path), tok),
                             tok == "--template-only")
    return True


def _docs_fixture_paths_exist():
    """Every `fixtures/...` path the README and the guides write exists."""
    seen = 0
    for path in (README,) + NEW_DOCS:
        for token in re.findall(r"fixtures/[A-Za-z0-9_./-]*", _read(path)):
            token = token.rstrip(".,")
            seen += 1
            _require("%s points at a missing path: %s" % (
                os.path.basename(path), token),
                os.path.exists(os.path.join(ROOT, token)))
    _require("found fixture paths to check", seen >= 8)
    return True


# ---------------------------------------------------------------------- driver

# ------------------------------------------------- R6: what v0.1.0 verifies

# The two rows owner-approved on 2026-11-12 (ticket r85), appended after AL-030.
AL_031_ROW = (
    "| AL-031 | REL | The invented-number rule (R1) reads a gene-like "
    "symbol immediately followed by a period and a digit, for example "
    "\"BRCA1.2\", as the number 1.2 instead of stripping the symbol, so a"
    " claim containing such a token is rejected unless 1.2 appears in a"
    " cited field. Dotted array versions such as \"V2.0\" are read the "
    "same way on both sides, which fixed the real-file failure found by"
    " the owner's checkpoint. The effect is a false rejection (the "
    "report falls back to the template), never an accepted invented "
    "number. | LOW | Prose does not write a gene symbol directly "
    "followed by a period and a digit; the exception is needed for real"
    " array versions. Review finding R84-F1. | 2026-11-12 | A narrated "
    "claim or caveat uses a gene symbol followed by \".<digit>\". |"
)

AL_032_ROW = (
    "| AL-032 | REL | `run` refuses an output file that is a symlink "
    "and an `--out-dir` that is a file, but follows a symlink used as "
    "`--out-dir` that points to a directory and writes there. The "
    "inside-the-checkout warning compares resolved paths. The "
    "documentation tells users to use a normal private directory. | LOW"
    " | Found by review r81; fixing it is a code change outside the "
    "documentation tickets. | 2026-11-12 | A user points `--out-dir` at"
    " a symlink into a synced or agent-readable location. |"
)


# Owner-approved rows (decision D-7 on r103, ticket S3-B), appended after AL-032.
AL_033_ROW = (
    "| AL-033 | REL | The release panel has seven health-related "
    "entries (five carrier status, two risk association) and two trait "
    "entries (rs11591147, LDL cholesterol levels; rs10741657, "
    "25-hydroxyvitamin D levels). The second trait entry is new in "
    "panel version 0.3.0; the v0.2.0 panel had seven health-related "
    "entries and one trait entry. This row supersedes AL-014 for the "
    "release panel; AL-014 describes v0.1.0 and stays as recorded. "
    "| LOW | Goals are not quotas; evidence-first curation (owner "
    "decisions on r96 and r97). | 2026-11-14 | The panel changes. |"
)

AL_034_ROW = (
    "| AL-034 | REL | The release panel carries one retrieved_at per "
    "source, a capture file time, although its entries were captured "
    "on more than one date. In panel version 0.2.0 that time was "
    "2026-11-14T14:16:47Z, although the rows of three entries were "
    "captured on 2026-11-11 and those of five on 2026-11-14. In panel "
    "version 0.3.0 it is 2026-11-23T19:22:03Z, the file time of the "
    "supplement's 11-14914878-A-G gnomAD answer, although the rows of "
    "three entries were captured on 2026-11-11, those of five on "
    "2026-11-14 and those of one on 2026-11-23; the dbSNP, gnomAD and "
    "GWAS Catalog labels name the 2026-11-11, 2026-11-14 and 2026-11-23 "
    "captures. docs/panel-curation.md records the split, and the "
    "report prints the single time for every source. | LOW | Accepted "
    "with the rebuild plan (owner decision R-1 on r100); per-entry "
    "dates need a panel format change. | 2026-11-14 | The panel gains "
    "per-entry retrieval dates. |"
)

AL_035_ROW = (
    "| AL-035 | REL | The panel build counts GWAS studies by "
    "word-boundary containment of the curated label or an alias, while "
    "the T4 replication rule uses equality; for rs11591147 the build "
    "counts 34 studies where T4 counts 4 rows in 3 groups. The tier is "
    "the same (replicated). | LOW | Aligning the two rules is a tools "
    "change outside the S3 wording stage. | 2026-11-14 | A trait's tier "
    "differs between the build count and the T4 rule. |"
)

AL_036_ROW = (
    "| AL-036 | REL | The T4 grammar allows \"-\" in the orientation "
    "source cell, but the evidence-index check rejects it, so a row "
    "with an unverified orientation source cannot be recorded; seven "
    "PCSK9 (rs11591147) rows were left out of T4, with no effect on the "
    "replication result. | LOW | Found in S2 (r98); changing the "
    "checker is outside the S3 wording stage. | 2026-11-14 | A trait's "
    "replication depends on a row whose orientation source is not "
    "verified. |"
)

AL_037_ROW = (
    "| AL-037 | REL | Checker gaps in tests/test_release_panel.py: a "
    "trait T1 row needs no specific typed source id, and trait T5 "
    "VariationIDs are not cross-checked. | LOW | Found as surviving "
    "mutants in S2 (r98); closing them is a checker change outside the "
    "S3 wording stage. | 2026-11-14 | A trait row cites a wrong or "
    "missing source id. |"
)

AL_038_ROW = (
    "| AL-038 | REL | The full-mode and online model payload still "
    "carries a trait entry's ClinVar block from findings.json; the "
    "template report, its citations and the skeleton prompt leave it "
    "out. Model narration is outside the verified scope (AL-016). | LOW "
    "| Render-level suppression (owner decision D-2 on r103) leaves "
    "findings.json and the redaction in tools/prompt.py unchanged. | "
    "2026-11-14 | Someone enables full-mode or online narration for a "
    "panel with a trait entry. |"
)

AL_039_ROW = (
    "| AL-039 | REL | The mutation runner's Git-free copy takes its "
    "file list from a manifest written by git ls-files in the source "
    "tree, and the pipeline's full-tree fixture trusts that manifest "
    "when the copy has no .git. Nothing checks that the manifest "
    "covers every tracked file, so a manifest that silently misses a "
    "file no guard self-test requires would change the fixture without "
    "a failing check. | LOW | Found by review r121 (R121-F2). The "
    "runner writes the manifest verbatim from the Git index, the "
    "fixture fails loudly when the manifest is empty or lacks the "
    "pipeline suite, and the guard self-test fails loudly when a file "
    "it requires is missing. | 2026-11-16 | The runner's manifest "
    "writing changes, or a mutation in the guard, hook, or history "
    "area survives. |"
)

AL_040_ROW = (
    "| AL-040 | REL | In a Git-free checkout that holds a hand-written "
    "tracked-file manifest, an entry with \"..\" components or an "
    "absolute path is joined without normalization, so the full-tree "
    "fixture can read a file outside the checkout and write a copy "
    "outside its own temporary repository before it fails at the first "
    "Git step. | LOW | Found by review r121 (R121-F3). The runner "
    "cannot produce such a path, because git ls-files never lists one "
    "and the runner rewrites the manifest in its own temporary copy; a "
    "manifest in a Git-free checkout is trusted by design. | "
    "2026-11-16 | Someone writes a manifest by hand, or the manifest "
    "source changes. |"
)

AL_041_ROW = (
    "| AL-041 | TMP | A stale run root means only that its owning "
    "process ended. A child process it started can outlive it and "
    "keep writing into the root, so the sweep can list a root that "
    "is still in use. The docs tell the owner to confirm no process "
    "uses a root (for example `lsof +D PATH`) before any removal. | "
    "MEDIUM | Owner decision on R128-F3: documented, with a caution "
    "line in the sweep output; no marker or process-group redesign. "
    "| 2026-11-22 | A leftover root is removed while a process still "
    "uses it, or the owner wants process-group tracking. |"
)

AL_042_ROW = (
    "| AL-042 | TMP | Run-root markers are not authenticated: any "
    "process running as the same user can create a directory with a "
    "matching name and a made-up marker, and the sweep lists it as "
    "stale. The sweep only lists; removal needs the owner's explicit "
    "approval of exact names. | LOW | Owner decision on R128-F4: "
    "documented. | 2026-11-22 | The sweep gains a removal mode, or a "
    "marker is trusted for something beyond listing. |"
)

AL_043_ROW = (
    "| AL-043 | TMP | Removal binds to the opened directory and "
    "re-checks each directory right after opening it, but a process "
    "running as the same user can still rename a directory in the "
    "short window between that check and an individual removal, so "
    "the removal can reach an entry in the moved directory before "
    "the final refusal. | LOW | Owner decision on the S0 FIX round "
    "2: close the deterministic windows only; a portable containment "
    "design is out of scope. | 2026-11-22 | The helper runs where "
    "another user's or untrusted code shares the same account, or a "
    "portable containment primitive is available. |"
)

AL_044_ROW = (
    "| AL-044 | TMP | Cleanup of a run root walks nested directories "
    "recursively. Beyond a depth of roughly 700 on the reviewed "
    "host, `RecursionError` is caught and logged, cleanup returns "
    "False and a partially cleaned root stays (one root, listed by "
    "the sweep). Test and build-loop trees are far shallower. | LOW "
    "| Owner decision on R132-F1 (accepted rather than spend fix "
    "round 3). | 2026-11-22 | A test or tool builds trees of several "
    "hundred levels, or cleanup is reused for arbitrary trees. |"
)

AL_045_ROW = (
    "| AL-045 | TMP | A process ended by SIGKILL or `os._exit`, or "
    "killed before its handlers run, leaves exactly one run root; "
    "the next sweep lists it. A recorded pid that is later reused by "
    "another process can make a dead root show as live (the safe "
    "direction: it is not listed stale). | LOW | Bounded by design "
    "(at most one owned root per process, list-only sweep); no "
    "deletion code in S0. | 2026-11-22 | Leftover roots accumulate, "
    "or pid reuse hides a root for long. |"
)

AL_046_ROW = (
    "| AL-046 | TMP | The SIGTERM and SIGHUP handlers end the "
    "process through SystemExit, so a check that catches SystemExit "
    "can let a terminated run continue. Runs started under `nohup` "
    "(SIGHUP ignored) fail the SIGHUP hygiene checks by design. | "
    "LOW | Handler left unchanged; documented. | 2026-11-22 | A test "
    "or tool starts catching SystemExit around long work, or the "
    "hygiene suite is run under `nohup`. |"
)

AL_047_ROW = (
    "| AL-047 | TMP | The peak-bytes and tracked-file-copy gate "
    "(T-12) runs only when tests/test_tmp_hygiene.py runs directly, "
    "not inside the pipeline run. The metric is tracked-file copies "
    "(41 to 1, bound 14); the number of fixture directories (41) is "
    "recorded only and did not change. | LOW | Owner confirmed this "
    "reading of T-12 (accept all). | 2026-11-22 | The copy count "
    "regresses unnoticed in pipeline-only runs. |"
)

AL_048_ROW = (
    "| AL-048 | REL | A GWAS p-value whose value underflows to 0.0 "
    "as a float (for example 6e-22136 or 2e-456) is rejected as "
    "`p-malformed`, so the row can neither count as a group nor "
    "meet the significance requirement, even when it is the "
    "strongest row in the pack. In v0.3.0 this removed the UK "
    "Biobank Lp(a) rows for rs10455872 and rs3798220. | LOW | Owner "
    "decision T-4 (v0.3.0 S1 triage): the existing `p-malformed` "
    "rule stands; it can only exclude evidence, never add it. | "
    "2026-11-23 | A candidate's replication outcome depends on an "
    "underflowed row, or the rule is changed to parse such values. "
    "|"
)

AL_049_ROW = (
    "| AL-049 | REL | The report does not state the direction of a "
    "trait association (whether the effect allele goes with higher "
    "or lower values); the direction is recorded only in "
    "docs/panel-curation.md: in the T1 `direction/meaning` and "
    "`rationale` cells and in the T4 `direction` column. | LOW | "
    "Owner decision D-6 (v0.3.0 S1): no direction wording is added "
    "to the report template. | 2026-11-23 | The owner wants the "
    "report to state direction, or a reader takes a trait finding "
    "to mean higher or lower values. |"
)

AL_050_ROW = (
    "| AL-050 | REL | Curated trait labels can be shared by more than one "
    "candidate: rs6544713 and rs11591147 share \"LDL cholesterol levels\", "
    "and rs2282679 and rs10741657 share \"25-hydroxyvitamin D levels\". "
    "The release panel carries one entry per label, so it reports no "
    "same-label pair. If a panel carries two entries with one label, the "
    "findings document reports a mixed-evidence contradiction as-is when "
    "their evidence differs and none when it is equal; it never "
    "reconciles them. | LOW | Owner decision D-5 (v0.3.0 S1): "
    "same-label pairs are accepted; the behavior is pinned by the "
    "synthetic two-entry test V030S3.same_label_pair_pins_behavior. | "
    "2026-11-23 | A panel carries two entries with one label, or the "
    "contradiction rule changes. |"
)

AL_051_ROW = (
    "| AL-051 | REL | The findings schema keeps schema_version 1.2.0 "
    "after it gained the optional effect_allele_is_reference property "
    "(present and true only when the curated effect allele is the "
    "reference allele). The change is additive: the current schema "
    "accepts older 1.2.0 findings, but an older strict copy of the 1.2.0 "
    "schema (additionalProperties false) rejects a findings document "
    "that carries the property, although both say 1.2.0. | LOW | Owner "
    "decision on review finding R150-F1 (2026-11-24): document only; "
    "schema_version is not bumped. | 2026-11-24 | A consumer validates "
    "findings with an older copy of the schema, or the findings schema "
    "changes again. |"
)

AL_052_ROW = (
    "| AL-052 | REL | The narration guard G3 in stage3/run.py rejects any "
    "claim that contains the word 'reference' and cites a covered_reference "
    "finding whose reference genotype is not provable. It therefore also "
    "rejects the accurate sentence 'This call does not establish the "
    "reference genotype.' and the stage falls back to the deterministic "
    "template prose for that finding. The behavior is fail-safe: no false "
    "claim is emitted, only template wording. | LOW | Owner decision on "
    "review finding R153-F1 (2026-11-24): accepted; G3 is not changed. | "
    "2026-11-24 | narration quality for covered_reference findings "
    "matters, or G3 is next changed (the reviewer's idea: reject "
    "affirmative false reference-genotype assertions instead of every "
    "mention of 'reference'). |"
)

APPENDED_ROWS = {"AL-031": AL_031_ROW, "AL-032": AL_032_ROW,
                 "AL-033": AL_033_ROW,
                 "AL-034": AL_034_ROW,
                 "AL-035": AL_035_ROW,
                 "AL-036": AL_036_ROW,
                 "AL-037": AL_037_ROW,
                 "AL-038": AL_038_ROW,
                 "AL-039": AL_039_ROW,
                 "AL-040": AL_040_ROW,
                 "AL-041": AL_041_ROW,
                 "AL-042": AL_042_ROW,
                 "AL-043": AL_043_ROW,
                 "AL-044": AL_044_ROW,
                 "AL-045": AL_045_ROW,
                 "AL-046": AL_046_ROW,
                 "AL-047": AL_047_ROW,
                 "AL-048": AL_048_ROW,
                 "AL-049": AL_049_ROW,
                 "AL-050": AL_050_ROW,
                 "AL-051": AL_051_ROW,
                 "AL-052": AL_052_ROW}
NARRATION_NOT_VERIFIED = "not verified against a live model"
FAILURE_EXAMPLE = (
    "template IR failed validation (bug):",
    "  R1: s_summary/cl_summary_coverage: number '42' not found in any cited "
    "field (invented value?)",
)


def _readme_opening():
    text = _read(README)
    return _flat(text[:text.index("> **Not medical advice.**")])


def _r6_readme_opening_template_first():
    flat = _readme_opening()
    for phrase in ("fixed templates", "no language model", "optional narration",
                   NARRATION_NOT_VERIFIED):
        _require("README opening lacks %r" % phrase, phrase in flat)
    _require("README opening names narration before the template path",
             flat.index("fixed templates") < flat.index("optional narration"))
    _require("README opening still presents the local model as the default",
             "by default a **local** model" not in flat)
    return True


def _r6_pick_your_path_says_template_only_once():
    sec = _flat(_section(_read(README), README_PATHS_HEADING))
    for phrase in ("uses `--template-only`", "needs Ollama or a language model"):
        _require("Pick your path lacks %r" % phrase, phrase in sec)
    _require("the statement is made once", sec.count("uses `--template-only`") == 1)
    return True


def _r6_readme_how_it_works_marks_the_template_path():
    sec = _flat(_section(_read(README), "How it works"))
    _require("diagram footnote missing",
             "`--template-only` skips the `[LLM]` box" in sec)
    _require("Stage 3 still described as local by default without a caveat",
             "Stage 3 is local by default" not in sec)
    _require("How it works lacks the not-verified statement",
             NARRATION_NOT_VERIFIED in sec)
    return True


def _r6_getting_started_says_template_only_and_not_verified():
    text = _read(GETTING_STARTED)
    what = _flat(_section(text, "What this tool does and does not do"))
    for phrase in ("fixed templates", "no language model", "uses `--template-only`"):
        _require("what-it-does section lacks %r" % phrase, phrase in what)
    prereq = _flat(_section(text, "Prerequisites"))
    _require("prerequisites lack the not-verified statement",
             NARRATION_NOT_VERIFIED in prereq)
    _require("prerequisites do not say nothing needs Ollama",
             "Nothing in this guide needs it" in prereq)
    return True


def _r6_used_fallback_explained():
    sec = _flat(_section(_read(GETTING_STARTED), "Reading the report"))
    for phrase in ("report.run.json", '"used_fallback": true', "--template-only",
                   "does not mean that anything failed"):
        _require("Reading the report lacks %r" % phrase, phrase in sec)
    return True


def _template_failure_item():
    trouble = _section(_read(GETTING_STARTED), "Troubleshooting and exit codes")
    for item in re.split(r"\n(?=- \*\*)", trouble):
        if "template IR failed validation (bug)" in item:
            return item
    _require("troubleshooting has no item for the template validation message", False)


def _r6_template_failure_troubleshooting():
    item = _template_failure_item()
    flat = _flat(item)
    _require("the item is not headed by the message name",
             item.lstrip().startswith("- **`template IR failed validation (bug)`"))
    for phrase in ("template IR failed validation (bug)", "a bug in the tool",
                   "not in your file", "violation lines", "rule code", "exit code 1"):
        _require("template-failure item lacks %r" % phrase, phrase in flat)
    for sentence in re.split(r"(?<=[.!?])\s+", flat):
        for name in ("findings.json", "raw file", "report.md"):
            if name in sentence:
                _require("a sentence naming %s must forbid sharing it: %r" % (
                    name, sentence), "never" in sentence.lower())
    return True


def _r6_template_failure_example_is_real():
    item = _template_failure_item()
    blocks = [b for b in _fences(item) if b[0] == "text"]
    _require("template-failure item has a text example block", blocks)
    import textwrap
    shown = tuple(textwrap.dedent("\n".join(blocks[0][1])).split("\n"))
    _require("example is not the documented lines", shown == FAILURE_EXAMPLE)
    import snp_insights.cli as cli
    stage3 = cli._tool_module("run")
    real = stage3.template_ir

    def broken(findings, findings_hash):
        ir = real(findings, findings_hash)
        for sec in ir["sections"]:
            for claim in sec["claims"]:
                if claim["claim_id"] == "cl_summary_coverage":
                    claim["text"] = "The array covers 42% of the genome."
        return ir

    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(ROOT)
            stage3.template_ir = broken
            code, _, err = _cli(["run", RAW_FIXTURE, "data/targets.release-panel.json",
                                 "--out-dir", os.path.join(tmp, "o"), "--template-only"])
        finally:
            stage3.template_ir = real
            os.chdir(cwd)
    _require("deliberately broken template exits %s, want 1" % code, code == 1)
    lines = err.split("\n")
    for line in FAILURE_EXAMPLE:
        _require("real output lacks the documented line %r" % line, line in lines)
    return True


def _r6_accepted_limits_al031_al032_verbatim():
    text = _read(LIMITS)
    found = _rows(text, set(APPENDED_ROWS))
    _require("AL-031..AL-052 all present", sorted(found) == sorted(APPENDED_ROWS))
    for rid, row in APPENDED_ROWS.items():
        _require("%s differs from the approved text" % rid, found[rid] == row)
        _require("%s appears once" % rid, text.count(row) == 1)
    order = [l[2:8] for l in text.split("\n") if re.match(r"\| AL-\d{3} \|", l)]
    tail = len(APPENDED_ROWS)
    _require("AL-031 starts the appended rows, which end the register in order at AL-052",
             order == sorted(order) and order[-tail:] == sorted(APPENDED_ROWS)
             and order[-tail:][:2] == ["AL-031", "AL-032"])
    _require("AL-030 sits directly before AL-031", order[-tail - 1] == "AL-030")
    return True


# ------------------------------------- S3B: panel counts, multi-allelic, Rev 4

RELEASE_PANEL = os.path.join(ROOT, "data", "targets.release-panel.json")
LOOP_SPEC = os.path.join(DOCS, "loop-spec.md")
# Pins computed on the base commit 6f8c478 (before ticket S3-B); Rev 4 is appended.
LOOP_SPEC_BASE_BYTES = 37065
LOOP_SPEC_BASE_SHA256 = "866725cc1423704b7a1debe046c324dc33d60f7ca225ead5c9f14c1088502a95"
# Owner decision D-1 (r103): the Limitations panel sentence carries no count.
PANEL_LIMITATION = ("The release uses a small public panel; the Summary counts "
                    "its markers by kind.")
COUNT_WORD = (r"\b(no|zero|one|two|three|four|five|six|seven|eight|nine|ten|"
              r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
              r"eighteen|nineteen|twenty|\d+)")
MULTI_ALLELIC_NOTE = ("; multi-allelic site (dbSNP alternates {alts}): criteria 1 "
                      "and 4 are read for the reference/effect pair (D8)")


def _release_panel_variants():
    import json
    with open(RELEASE_PANEL, encoding="utf-8") as fh:
        return json.load(fh)["variants"]


def _panel_counts():
    """Entries in the release panel, by kind, as the docs must state them."""
    kinds = [v["result_type"] for v in _release_panel_variants()]
    counts = {
        "total": len(kinds),
        "carrier": kinds.count("carrier_status"),
        "risk": kinds.count("risk_association"),
        "trait": kinds.count("trait"),
    }
    counts["health"] = counts["carrier"] + counts["risk"]
    _require("panel has an entry of an unknown kind",
             counts["health"] + counts["trait"] == counts["total"])
    return counts


def _entries(n):
    return "entry" if n == 1 else "entries"


def _expected_count_phrases():
    """(document, phrase) pairs every count statement must match."""
    import snp_insights.cli as cli
    w = cli._tool_module("run").words
    c = _panel_counts()
    _require("release panel is empty", c["total"] > 0)
    h, t = w(c["health"]), w(c["trait"]) + " trait " + _entries(c["trait"])
    traits = ", ".join(v["rsid"] for v in _release_panel_variants()
                       if v["result_type"] == "trait")
    return (
        (CHECKPOINT, "This release has %s; no count cutoff is prescribed." % t),
        (CHECKPOINT, "%s health %s (%s carrier status, %s risk association) and %s."
         % (h, _entries(c["health"]), w(c["carrier"]), w(c["risk"]), t)),
        (README, "small public panel of %s health-related %s and %s,"
         % (h, _entries(c["health"]), t)),
        (README, "- The release panel has %s health %s and %s."
         % (h, _entries(c["health"]), t)),
        (README, "a curated %s-entry release panel" % w(c["total"])),
        (GETTING_STARTED, "panel has %s health %s and %s," % (h, _entries(c["health"]), t)),
        (REFERENCE_DATA, "The release panel has %s (%s)" % (t, traits)),
        (AGENTS, "a curated %s-entry panel (%s health %s, %s)"
         % (w(c["total"]), h, _entries(c["health"]), t)),
        (AGENTS, "(%s health %s, %s; see docs/panel-curation.md)"
         % (h, _entries(c["health"]), t)),
    )


def _s3b_docs_panel_counts_match_panel():
    phrases = _expected_count_phrases()
    import snp_insights.cli as cli
    w = cli._tool_module("run").words
    c = _panel_counts()
    want = {"health": w(c["health"]), "health-related": w(c["health"]),
            "trait": w(c["trait"])}
    for path, phrase in phrases:
        _require("%s lacks the panel count %r" % (os.path.basename(path), phrase),
                 phrase in _flat(_read(path)))
    stated = 0
    for path in sorted({p for p, _ in phrases}):
        flat = _flat(_read(path))
        for m in re.finditer(COUNT_WORD + r" (health|health-related|trait) entr(?:y|ies)\b",
                             flat, re.I):
            stated += 1
            _require("%s states %r; the panel has %s" % (
                os.path.basename(path), m.group(0), want[m.group(2).lower()]),
                m.group(1).lower() == want[m.group(2).lower()])
        for m in re.finditer(COUNT_WORD + r"-entry (?:health |release )?panel\b", flat, re.I):
            stated += 1
            _require("%s states %r; the panel has %s entries" % (
                os.path.basename(path), m.group(0), w(c["total"])),
                m.group(1).lower() == w(c["total"]))
    _require("no count statement checked", stated >= len(phrases))
    return True


def _s3b_limitation_panel_statement_count_free():
    import snp_insights.cli as cli
    limitations = cli._tool_module("caveats").LIMITATIONS
    _require("no limitations", limitations)
    panel = [i for i in limitations if "public panel" in i.lower()]
    _require("%d limitation items describe the panel" % len(panel), len(panel) == 1)
    _require("panel limitation is not the approved sentence: %r" % panel[0],
             panel[0] == PANEL_LIMITATION)
    for item in limitations:
        _require("limitation states an entry count: %r" % item,
                 not re.search(COUNT_WORD + r"(?: health(?:-related)?| trait)? entr|"
                               + COUNT_WORD + r"-entry", item, re.I))
        _require("limitation names a release version: %r" % item,
                 not re.search(r"\bv\d+\.\d+", item))
    return True


def _t1_rows():
    """(rsID, limitations cell, decision) of every T1 data row."""
    text = _read(CURATION)
    lines = text.split("\n")
    start = lines.index("### T1 Decision table")
    header = None
    rows = []
    for line in lines[start + 1:]:
        if line.startswith("### ") or line.startswith("## "):
            break
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if header is None:
            header = cells
            continue
        if set(line) <= set("|- "):
            continue
        _require("T1 row has %d cells" % len(cells), len(cells) == len(header))
        row = dict(zip(header, cells))
        rows.append((row["rsID"], row["limitations"], row["decision"]))
    _require("T1 has no data rows", rows)
    return rows


def _s3b_multi_allelic_rows_have_note():
    multi = {v["rsid"]: v["alternate_alleles"] for v in _release_panel_variants()
             if len(v.get("alternate_alleles") or []) > 1}
    _require("no multi-allelic entry in the release panel", multi)
    included = {rs: lim for rs, lim, dec in _t1_rows() if dec == "included"}
    for rsid, alts in sorted(multi.items()):
        _require("%s has no included T1 row" % rsid, rsid in included)
        note = MULTI_ALLELIC_NOTE.format(alts=", ".join(alts))
        _require("%s limitations lack the multi-allelic note %r" % (rsid, note),
                 included[rsid].endswith(note) and included[rsid].count(note) == 1)
    for rsid, lim in included.items():
        if rsid not in multi:
            _require("%s is not multi-allelic but carries the note" % rsid,
                     "(D8)" not in lim)
    return True


def _s3b_loop_spec_records_d8():
    raw = open(LOOP_SPEC, "rb").read()
    _require("existing bytes unchanged (prefix)",
             hashlib.sha256(raw[:LOOP_SPEC_BASE_BYTES]).hexdigest() == LOOP_SPEC_BASE_SHA256)
    tail = raw[LOOP_SPEC_BASE_BYTES:].decode("utf-8")
    _require("Rev 4 is appended after the last line", tail.startswith("\n### Rev 4 "))
    _require("one Rev 4 heading", raw.decode("utf-8").count("### Rev 4 ") == 1)
    flat = _flat(tail)
    for phrase in ("**D8 (pair reading", "criteria 1 and 4 apply to the reference/effect",
                   "multi-allelic", "T1 limitation note", "2026-11-13",
                   "**D9 (stage 2 capture", "STAGE=2",
                   "**D3 superseded", "bump to 0.2.0", "2026-11-14",
                   "r96", "r97", "r100", "r105"):
        _require("Rev 4 lacks %r" % phrase, phrase in flat)
    return True


# Version-independent method statements of the curation paragraph, kept verbatim
# (ticket r108, R107-F1).
CURATION_METHOD_SENTENCES = (
    "The health rows keep carrier or association wording only, and no entry "
    "states a diagnosis or an absolute risk.",
    "Effect alleles were re-derived from the complete dbSNP GRCh37 allele set in "
    "N0d; the curated condition is attributed through a per-condition ClinVar "
    "record (RCV) whose condition names the curated label by the alias-file "
    "semantics, and that record's significance and stars are used, never the VCV "
    "aggregate (D-54-3); the strict other-condition outcome applies when no RCV "
    "names it.",
    "The alias file was extended with three reviewed synonyms and two aliases that "
    "named a different, bleeding disorder were removed (D-54-2).",
    "Palindromic reference/effect pairs (A/T or C/G) are excluded by default with "
    "reason code `palindromic` (D-54-1).",
    "Whether the resulting panel is adequate is the owner's aggregate coverage "
    "judgment (counts only).",
)

# Owner decision R-a on r138: the pool paragraph is checked per panel version.
V020_GROWTH = (11, 34, 5, 6)  # candidates, T1 rows after v0.2.0, included, excluded
V030_POOL = ("rs10455872", "rs3798220", "rs6544713", "rs2282679", "rs10741657",
             "rs601338", "rs6795970", "rs174537", "rs1801133", "rs11887534")
V030_GROWTH = (10, 44, 1, 9)  # candidates, T1 rows after v0.3.0, included, excluded


def _t1_dicts():
    """Every T1 data row as a dict keyed by the header cells."""
    lines = _read(CURATION).split("\n")
    start = lines.index("### T1 Decision table")
    header, rows = None, []
    for line in lines[start + 1:]:
        if line.startswith("### ") or line.startswith("## "):
            break
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if header is None:
            header = cells
        elif not set(line) <= set("|- "):
            rows.append(dict(zip(header, cells)))
    _require("T1 has no data rows", rows)
    return rows


def _curation_release_paragraph():
    paras = [p for p in re.split(r"\n\s*\n", _section(_read(CURATION), "Limitations"))
             if "DRAFT rsIDs" in p]
    _require("%d Limitations paragraphs name the DRAFT pool" % len(paras), len(paras) == 1)
    _require("the pool paragraph is empty", paras[0].strip())
    return _flat(paras[0])


def _s3b_curation_release_paragraph_matches_tables():
    import json
    import snp_insights.cli as cli
    w = cli._tool_module("run").words
    para = _curation_release_paragraph()
    sentences = re.split(r"(?<=\.)\s+(?=[A-Z])", para)
    _require("the paragraph still says 'For this release'", "For this release" not in para)
    for sentence in CURATION_METHOD_SENTENCES:
        _require("method statement changed or missing: %r" % sentence[:40], sentence in para)
    _require("the paragraph does not end with the adequacy sentence",
             para.endswith(CURATION_METHOD_SENTENCES[-1]))
    draft = []
    for name in ("targets.carrier.json", "targets.traits.json"):
        with open(os.path.join(ROOT, "data", name), encoding="utf-8") as fh:
            draft += [v["rsid"] for v in json.load(fh)["variants"]]
    for phrase in ("the %d DRAFT rsIDs" % len(draft), "no marker was added",
                   "every trait row was excluded"):
        hits = [s for s in sentences if phrase.lower() in s.lower()]
        _require("the v0.1.0 statement %r is missing" % phrase, hits)
        for s in hits:
            _require("%r is not scoped to v0.1.0: %r" % (phrase, s), "v0.1.0" in s)
    rows = _t1_dicts()
    new = [r for r in rows if r["rsID"] not in draft]
    _require("T1 adds no candidate beyond the DRAFT pool", new)
    # Version split (owner decision R-a on r138): the v0.2.0 growth sentence keeps
    # its numbers and the v0.3.0 rows have their own sentence. The strict
    # no-reserve rule holds for every T1 row now that rs10741657 is `included`
    # (R141-F3, S2).
    v030 = [r for r in new if r["rsID"] in V030_POOL]
    v020 = [r for r in new if r["rsID"] not in V030_POOL]
    _require("T1 lacks a v0.3.0 pool row", sorted(r["rsID"] for r in v030) == sorted(V030_POOL))
    inc2 = [r for r in v020 if r["decision"] == "included"]
    exc2 = [r for r in v020 if r["decision"] == "excluded"]
    _require("v0.2.0 rows changed: %d rows, %d included, %d excluded" % (len(v020), len(inc2), len(exc2)),
             (len(v020), len(draft) + len(v020), len(inc2), len(exc2)) == V020_GROWTH)
    growth020 = ("For v0.2.0 the pool grew by %s candidates to %d T1 rows, "
                 "of which %s were included and %s excluded."
                 % (w(len(v020)), len(draft) + len(v020), w(len(inc2)), w(len(exc2))))
    _require("v0.2.0 pool growth must be stated exactly once from T1",
             [s for s in sentences if s.startswith("For v0.2.0 the pool grew by ")] == [growth020])
    inc3 = [r for r in v030 if r["decision"] == "included"]
    res3 = [r for r in v030 if r["decision"] == "reserve"]
    exc3 = [r for r in v030 if r["decision"] == "excluded"]
    _require("no reserve row may exist: %s" % [r["rsID"] for r in rows if r["decision"] == "reserve"],
             not res3 and not [r for r in rows if r["decision"] == "reserve"])
    _require("v0.3.0 rows changed: %d rows, %d included, %d excluded" % (len(v030), len(inc3), len(exc3)),
             (len(v030), len(rows), len(inc3), len(exc3)) == V030_GROWTH)
    growth030 = ("For v0.3.0 the pool grew by %s candidates to %d T1 rows, of which %s was included, "
                 "none is a reserve and %s were excluded."
                 % (w(len(v030)), len(rows), w(len(inc3)), w(len(exc3))))
    _require("v0.3.0 pool growth must be stated exactly once, as the whole sentence, from T1",
             [s for s in sentences if s.startswith("For v0.3.0 the pool grew by ")] == [growth030])
    _require("the paragraph names an rsID other than the added T1 candidates",
             set(re.findall(r"\brs\d+\b", para)) == {r["rsID"] for r in new})
    for r in new:
        named = [s for s in sentences if re.search(r"\b%s\b" % r["rsID"], s)]
        _require("%s is named in %d sentences" % (r["rsID"], len(named)), len(named) == 1)
        s = named[0]
        if r["decision"] == "included":
            _require("%s: sentence lacks `%s` (category `%s`)" % (
                r["rsID"], r["result type"], r["category"]),
                s.startswith("Included as `%s` (category `%s`)" % (r["result type"], r["category"])))
            if r["result type"] == "trait":
                for phrase in ("Replication rule", "T4", "not ancestry-informative",
                               "criterion 8"):
                    _require("%s: trait sentence lacks %r" % (r["rsID"], phrase), phrase in s)
        else:
            _require("%s: sentence lacks reason code `%s`" % (r["rsID"], r["reason code"]),
                     s.startswith("Excluded with reason code `%s`" % r["reason code"]))
    _require("v0.2.0 no-reserves statement is missing or inconsistent",
             [s for s in sentences if s.startswith("No reserves exist for v0.2.0")]
             == ["No reserves exist for v0.2.0 either: none of its rows is a `reserve`."])
    # Full sentence inventory (R151-F5): every sentence is a method statement, a v0.1.0
    # statement, one of the three exact growth/no-reserves sentences, or a decision sentence
    # naming T1 rsIDs; anything else (a paraphrase of growth or reserves) fails.
    exact = set(CURATION_METHOD_SENTENCES) | {
        growth020, growth030, "No reserves exist for v0.2.0 either: none of its rows is a `reserve`."}
    for s in sentences:
        known = (s in exact
                 or (s.startswith(("For the v0.1.0 curation ", "In the v0.1.0 curation "))
                     and "reserve" not in s.lower())
                 or (s.startswith(("Included as `", "Excluded with reason code `"))
                     and re.search(r"\brs\d+\b", s) and "reserve" not in s.lower()))
        _require("the release paragraph has an unaccounted sentence: %r" % s, known)
    return True


def _s3b_release_paragraph_gate_rejects_contradictions():
    """R141-F3: the release paragraph gate must reject a false extra growth
    sentence and a contradictory claim after the no-reserves prefix, for v0.2.0
    and for v0.3.0, and must compare the whole v0.3.0 sentence, not a substring."""
    para = _curation_release_paragraph()
    growth = "For v0.2.0 the pool grew by eleven"
    claim = "No reserves exist for v0.2.0 either: none of its rows is a `reserve`."
    growth3 = ("For v0.3.0 the pool grew by ten candidates to 44 T1 rows, of which one was "
               "included, none is a reserve and nine were excluded.")
    _require("the paragraph lacks the v0.2.0 or v0.3.0 growth or no-reserves statement",
             para.count(growth) == 1 and para.count(claim) == 1 and para.count(growth3) == 1)
    variants = {
        "extra false growth sentence": para.replace(
            growth, "For v0.2.0 the pool grew by twelve candidates to 35 T1 rows, "
            "of which six were included and six excluded. " + growth, 1),
        "reserve claim after the no-reserves prefix": para.replace(
            claim, "No reserves exist for v0.2.0 either: one of its rows is a `reserve`.", 1),
        "extra false v0.3.0 growth sentence": para.replace(
            growth3, "For v0.3.0 the pool grew by eleven candidates to 45 T1 rows, of which "
            "two were included, none is a reserve and nine were excluded. " + growth3, 1),
        "contradictory suffix on the v0.3.0 growth sentence": para.replace(
            growth3, growth3[:-1] + ", and one is a reserve.", 1),
        "false growth paraphrase without the canonical prefix": para.replace(
            CURATION_METHOD_SENTENCES[-1], "In v0.3.0 the pool added eleven candidates, and one "
            "is a reserve. " + CURATION_METHOD_SENTENCES[-1], 1),
        "extra unaccounted sentence": para.replace(
            CURATION_METHOD_SENTENCES[-1], "The pool is complete. " + CURATION_METHOD_SENTENCES[-1], 1),
    }
    accepted = []
    original = globals()["_curation_release_paragraph"]
    try:
        for name, changed in variants.items():
            globals()["_curation_release_paragraph"] = lambda changed=changed: changed
            try:
                _s3b_curation_release_paragraph_matches_tables()
            except AssertionError:
                continue
            accepted.append(name)
    finally:
        globals()["_curation_release_paragraph"] = original
    # The strict no-reserve rule covers every T1 row, also one outside the v0.3.0 pool, which
    # no growth count sees.
    rows = _t1_dicts()
    _require("the first T1 row is not a decided row", rows[0]["decision"] in ("included", "excluded"))
    reserve_rows = [dict(rows[0], decision="reserve")] + rows[1:]
    original_rows = globals()["_t1_dicts"]
    try:
        globals()["_t1_dicts"] = lambda: reserve_rows
        try:
            _s3b_curation_release_paragraph_matches_tables()
            accepted.append("a reserve row outside the v0.3.0 pool")
        except AssertionError:
            pass
    finally:
        globals()["_t1_dicts"] = original_rows
    _require("the release paragraph gate accepts: %s" % accepted, not accepted)
    return True


def _runner_copies_guard_selftest_files():
    from guard import SELFTEST_MUST_BE_TRACKED
    from loop_mutations import COPY_DIRS, COPY_FILES

    missing = sorted(path for path in SELFTEST_MUST_BE_TRACKED
                     if path not in COPY_FILES
                     and not any(path.startswith(directory + "/") for directory in COPY_DIRS))
    _require(f"runner copy inventory omits guard self-test files: {missing}", not missing)
    return True


# ------------------------------------- V030S3: v0.3.0 release-run wording

RELEASE_CLAIM_PATTERNS = (
    r"\b(?:has|have) been (?:released|published|tagged)\b",
    r"\b(?:is|was|are|were) (?:released|published|tagged)\b",
    r"\bRelease candidate\b",
    r"\bnow available\b",
)


def _v030s3_release_wording():
    readme = _flat(_read(README))
    getting = _flat(_read(GETTING_STARTED))
    checkpoint = _flat(_read(CHECKPOINT))
    status = _flat(_section(_read(README), "Status"))
    state = _flat(_section(_read(AGENTS), "Current state (v0.3.0 release run)"))
    facts = _flat(_section(_read(CHECKPOINT), "Current release facts"))
    _require("README release section names panel version 0.3.0",
             "panel version 0.3.0" in _flat(_release_section()))
    _require("getting-started names panel version 0.3.0", "panel version 0.3.0" in getting)
    _require("owner checkpoint names panel version 0.3.0", "panel version 0.3.0" in facts)
    _require("README states package version 0.3.0",
             "panel version 0.3.0 and package version 0.3.0" in status)
    _require("AGENTS states package version 0.3.0",
             "The package version is 0.3.0." in state)
    _require("the old v0.2.0 panel statement is gone from the owner checkpoint",
             "The v0.2.0 release panel" not in checkpoint)
    _require("the old v0.2.0 panel statement is gone from getting-started",
             "The v0.2.0 panel has" not in getting and "v0.2.0 release set" not in getting)
    _require("the old v0.2.0 panel statement is gone from the README",
             "v0.2.0 ships a small public panel" not in readme)
    for label, text in (("README Status", status), ("AGENTS current state", state),
                        ("owner checkpoint release facts", facts)):
        for pattern in RELEASE_CLAIM_PATTERNS:
            _require("%s claims a release, tag or publication (%s)" % (label, pattern),
                     re.search(pattern, text, re.I) is None)
        _require("%s does not leave release steps to the owner" % label,
                 "owner" in text.lower())
    return True


def _v030s3g_no_release_claim_in_release_docs():
    """Sol mutant r151-12: no release, tag or publication claim anywhere in the release
    docs, not only in their Status sections."""
    for path in (README, GETTING_STARTED, CHECKPOINT, AGENTS):
        text = _flat(_read(path))
        for pattern in RELEASE_CLAIM_PATTERNS:
            hit = re.search(pattern, text, re.I)
            _require("%s claims a release, tag or publication: %r" % (
                os.path.basename(path), hit.group(0) if hit else ""), hit is None)
    bad = _flat(_read(GETTING_STARTED)) + " The v0.3.0 package has been released."
    _require("the control claim is not detected",
             any(re.search(p, bad, re.I) for p in RELEASE_CLAIM_PATTERNS))
    return True


def _v030s3_accepted_limits_rows():
    text = _read(LIMITS)
    rows = _rows(text, {"AL-033", "AL-050"})
    _require("AL-033 still names the first trait label", "rs11591147" in rows["AL-033"])
    _require("AL-033 no longer calls the nine-entry panel the v0.2.0 panel",
             "The v0.2.0 release panel has" not in rows["AL-033"])
    _require("AL-033 says the second trait entry is new in 0.3.0",
             "new in panel version 0.3.0" in rows["AL-033"])
    _require("AL-050 names its pin", "V030S3.same_label_pair_pins_behavior" in rows["AL-050"])
    # AL-051 (R150-F1, document only): the row matches the schema it describes.
    rows51 = _rows(text, {"AL-051"})
    _require("AL-051 is missing", "AL-051" in rows51)
    import json
    with open(os.path.join(ROOT, "schema", "findings.schema.json"), encoding="utf-8") as fh:
        schema = json.load(fh)
    finding = schema["$defs"]["finding"]
    version = schema["properties"]["schema_version"]
    _require("AL-051 names schema_version 1.2.0, the schema does not",
             "schema_version 1.2.0" in rows51["AL-051"] and "1.2.0" in json.dumps(version))
    _require("AL-051 describes an optional property the schema does not have",
             "effect_allele_is_reference" in finding["properties"]
             and "effect_allele_is_reference" not in finding["required"]
             and finding.get("additionalProperties") is False)
    with open(os.path.join(ROOT, "tests", "test_release_panel.py"), encoding="utf-8") as fh:
        _require("the AL-050 pin does not exist in the release-panel tests",
                 'attempt("V030S3.same_label_pair_pins_behavior"' in fh.read())
    # AL-052 (R153-F1, accepted): the row names the finding and the guard file.
    rows52 = _rows(text, {"AL-052"})
    _require("AL-052 is missing", "AL-052" in rows52)
    _require("AL-052 does not name R153-F1", "R153-F1" in rows52["AL-052"])
    _require("AL-052 does not name stage3/run.py", "stage3/run.py" in rows52["AL-052"])
    return True


def _v030s3f_excerpt_reflects_equal_reference_sentence():
    flat = _flat(_read(GETTING_STARTED))
    old = ("Factor V Leiden thrombophilia (F5): both copies match the reference at this "
           "position; the effect allele was not found in the genotype.")
    new = ("Factor V Leiden thrombophilia (F5): no copy of the effect allele was found in "
           "the genotype at this position.")
    _require("getting-started still shows the false rs6025 sentence", old not in flat)
    _require("getting-started lacks the rs6025 sentence for effect allele = reference", new in flat)
    _require("the excerpt line does not cite effect_allele_is_reference",
             "effect_allele_is_reference]" in flat.split(new, 1)[1].split("\n")[0][:400]
             or "effect_allele_is_reference]" in flat.split(new, 1)[1][:400])
    return True



# ------------------------------------- v0.4.0 S1: disease-association contract (r159)

DISEASE_DOC = os.path.join(DOCS, "disease-associations.md")
_DA_TOOLS = os.path.join(ROOT, "tools")
if _DA_TOOLS not in sys.path:
    sys.path.append(_DA_TOOLS)  # caveats and validate_report: the production strings the pins compare
DA_CLAUSE_COUNT = 54
# clause -> the r158 specification-review findings that amended it (owner: fold F1..F8 into S1).
DA_MARKERS = {
    "C-5": ("F8",), "C-6": ("F1",), "C-7": ("F7",), "C-12": ("F7",), "C-15": ("F3",),
    "C-22": ("F5",), "C-23": ("F5",), "C-27": ("F4",), "C-29": ("F2", "F4"), "C-34": ("F6",),
    "C-40": ("F4",), "C-43": ("F2",), "C-46": ("F1",), "C-49": ("F7",), "C-53": ("F1",),
}
# r162: re-pinned for FP-06, FP-09 widened and FP-32, FP-33 added; was b6c120912d83b65582cccd1d34fbad931a0359c500784aadb3f9d0cfc444b51e.
DA_PATTERN_BLOCK_SHA256 = "5ccfaf1c8bdc34ab8ae3d1b4649c0ba50011b7122ae5e4396f7a0f94089df45a"
DA_PATTERN_COUNT = 33  # r162: was 31; FP-32 and FP-33 added (R160-F1, R161-09)
DA_ANCESTRY_CODES = ("european", "east-asian", "south-asian", "african", "hispanic-latino",
                     "middle-eastern", "oceanian", "mixed", "other")
DA_TIER_WORDS = ("established", "replicated", "single study", "conflicting", "unknown")
DA_STATES = ("detected", "covered_reference", "covered_nocall", "covered_uninterpretable",
             "not_covered", "not_assayable")
# The r158 review corpus (invented sentences): case, oracle, sentence. Cases 13, 14,
# 17, 18 and 19 were false negatives and case 36 a false positive of the draft list.
DA_CORPUS = (
    (1, 'reject', "You have Crohn's disease."),
    (2, 'reject', "You were diagnosed with Crohn's disease."),
    (3, 'reject', 'You are affected by this disease.'),
    (4, 'reject', "You may suffer from Crohn's disease."),
    (5, 'reject', "You are a patient with Crohn's disease."),
    (6, 'reject', "Your chance of Crohn's disease is elevated."),
    (7, 'reject', "You are at high risk of developing Crohn's disease."),
    (8, 'reject', "Your lifetime risk of Crohn's disease is 12 percent."),
    (9, 'reject', 'Penetrance is high for this variant.'),
    (10, 'reject', 'This result means you should start treatment.'),
    (11, 'reject', 'You should schedule colorectal screening.'),
    (12, 'reject', 'You should change your diet and lifestyle.'),
    (13, 'reject', 'Your LDL cholesterol is high.'),
    (14, 'reject', 'Your clinical result shows an abnormal marker.'),
    (15, 'reject', "This allele protects you from Crohn's disease."),
    (16, 'reject', "This variant causes Crohn's disease."),
    (17, 'reject', 'No follow-up is needed for this result.'),
    (18, 'reject', "You could develop Crohn's disease because of this result."),
    (19, 'reject', "You might develop Crohn's disease."),
    (20, 'reject', 'This is a disease-causing mutation.'),
    (21, 'reject', 'You should speak with a clinician about this finding.'),
    (22, 'reject', "This allele means you are resistant to Crohn's disease."),
    (23, 'reject', "This allele increases your risk of Crohn's disease."),
    (24, 'allow', "Crohn's disease (IL23R): one copy of the effect allele G was detected. Evidence tier: replicated, from the GWAS Catalog association count. In published studies of European ancestry, this allele was associated with higher odds of Crohn's disease. This is a statistical association at the population level; it is not a diagnosis of Crohn's disease and not an estimate of your own risk."),
    (25, 'allow', "Crohn's disease (IL23R): two copies of the effect allele G were detected. Evidence tier: replicated, from the GWAS Catalog association count. In published studies of European ancestry, this allele was associated with higher odds of Crohn's disease. This is a statistical association at the population level; it is not a diagnosis of Crohn's disease and not an estimate of your own risk."),
    (26, 'allow', "Crohn's disease (IL23R): one copy of the effect allele A was detected. Evidence tier: replicated, from the GWAS Catalog association count. In published studies of European ancestry, this allele was associated with lower odds of Crohn's disease. This is a statistical association at the population level; it is not a diagnosis of Crohn's disease and not an estimate of your own risk."),
    (27, 'allow', "Crohn's disease (IL23R): two copies of the effect allele A were detected. Evidence tier: replicated, from the GWAS Catalog association count. In published studies of European ancestry, this allele was associated with lower odds of Crohn's disease. This is a statistical association at the population level; it is not a diagnosis of Crohn's disease and not an estimate of your own risk."),
    (28, 'allow', "Crohn's disease (IL23R): this position is on the array, but the array returned no call, so no genotype is available."),
    (29, 'allow', "Crohn's disease (IL23R): this position was measured, but the call could not be interpreted, so no genotype is given."),
    (30, 'allow', "Crohn's disease (IL23R): this marker was not measured by this array. That gives no information about whether the effect allele is present."),
    (31, 'allow', "Crohn's disease (IL23R): this locus cannot be assessed from array data."),
    (32, 'allow', "Crohn's disease (IL23R): no copy of the effect allele was found in the genotype at this position."),
    (33, 'allow', 'Atrial fibrillation (PITX2): one copy of the effect allele T was detected. Evidence tier: replicated, from the GWAS Catalog association count. In published studies of European and East Asian ancestry, this allele was associated with higher odds of atrial fibrillation. This is a statistical association at the population level; it is not a diagnosis of atrial fibrillation and not an estimate of your own risk.'),
    (34, 'allow', 'Coronary artery disease (CDKN2B-AS1): one copy of the effect allele C was detected. Evidence tier: replicated, from the GWAS Catalog association count. In published studies of European ancestry, this allele was associated with lower odds of coronary artery disease. This is a statistical association at the population level; it is not a diagnosis of coronary artery disease and not an estimate of your own risk.'),
    (35, 'allow', 'This report was generated by fixed templates on this machine from structured findings; no language model was used to write it. It is a research and curiosity tool, not medical advice or a diagnostic test.'),
    (36, 'allow', 'Array-based genotyping covers a small fraction of the genome (~0.02%), is chip-dependent, and is not diagnostic grade.'),
    (37, 'allow', 'This report is not medical advice, and no result is a diagnosis.'),
    (38, 'allow', 'Atrial fibrillation (PITX2): one copy of the effect allele C was detected. Evidence tier: replicated, from the GWAS Catalog association count. In published studies of East Asian and South Asian ancestry, this allele was associated with higher odds of atrial fibrillation. This is a statistical association at the population level; it is not a diagnosis of atrial fibrillation and not an estimate of your own risk.'),
)
DA_CORPUS_CONDITIONS = ("Crohn's disease", "atrial fibrillation", "coronary artery disease")
# r162 (R161-10): each archived claim is bound to the one frame of its state and zygosity.
DA_FRAME_EXPECT = {24: "FR-01", 25: "FR-03", 26: "FR-02", 27: "FR-04", 28: "FR-07", 29: "FR-08",
                   30: "FR-09", 31: "FR-10", 32: "FR-06", 33: "FR-01", 34: "FR-02", 38: "FR-01"}


def _da_text():
    try:
        with open(DISEASE_DOC, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def _da_block(text, name):
    m = re.search(r"<!-- r11-%s:begin -->\n(.*?)<!-- r11-%s:end -->" % (name, name), text, re.S)
    return m.group(1) if m else ""


def _da_patterns(text):
    return [re.fullmatch(r"(FP-\d{2}) ([a-z-]+) (\S.*)", ln).groups()
            for ln in _da_block(text, "forbidden-patterns").splitlines() if ln.startswith("FP-")]


def _da_exemptions(text):
    return [re.fullmatch(r"(EX-\d{2}) (\S+) (\S.*)", ln).groups()
            for ln in _da_block(text, "exemptions").splitlines() if ln.startswith("EX-")]


def _da_quoted(text, name):
    m = re.search(r"`%s` = `([^`]+)`" % name, text)
    return m.group(1) if m else None


def _da_canon(text):
    """C-43 step 0 (R160-F1): NFKC, then one space for every whitespace run."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def _da_scan(text, doc, conditions=()):
    """C-43 procedure: canonical text (a non-ASCII letter is the error NONASCII), remove
    exemptions only as whole sentences, then rsIDs, gene symbols and build names, then
    every pattern (case-insensitive). Returns the ids of the errors found."""
    text = _da_canon(text)
    hits = ["NONASCII"] if any(ch.isalpha() and not ch.isascii() for ch in text) else []
    for _, _, ex in _da_exemptions(doc):
        for s in ([ex.replace("<condition>", c) for c in conditions] if "<condition>" in ex else [ex]):
            text = re.sub(r"(?:\A|(?<=[.!?] ))" + re.escape(s) + r"(?= |\Z)", " ", text)  # R161-04
    id_re, gene_re = _da_quoted(doc, "ID_RE"), _da_quoted(doc, "GENE_RE")
    _require("C-43 quotes ID_RE and GENE_RE", id_re and gene_re)
    t = re.sub(gene_re, " ", re.sub(id_re, " ", text, flags=re.I))
    t = t.replace("GRCh37", " ").replace("GRCh38", " ")
    return hits + [pid for pid, _, rx in _da_patterns(doc) if re.search(rx, t, re.I)]


def _da_registry(text):
    """[(id, role, registry id, text)] from the C-43 disease registry block."""
    return [re.fullmatch(r"(RG-\d{2}) (caveat|notice|limitation) (\S+) (\S.*)", ln).groups()
            for ln in _da_block(text, "disease-registry").splitlines() if ln.startswith("RG-")]


def _da_report_errors(items, doc, conditions=()):
    """C-43 (R161-01, R161-09): items are (role, text). Only disease roles are checked:
    a disease claim must equal a C-29 frame (or the frame named by its role suffix), a
    disease caveat, notice or limitation must equal a registry text of that role, and
    all disease text passes the scan. Other result-type claims keep their own validation."""
    errors = []
    registry = {(role, s) for _, role, _, s in _da_registry(doc)}
    _require("disease registry parsed", registry)
    frames = {r["frame"]: _da_frame_re(r["text"], doc) for r in _da_frames(doc)}
    for role, text in items:
        if not role.startswith("disease-"):
            continue  # R161-01: existing carrier, ClinVar association and trait claims
        canon = _da_canon(text)
        kind, _, frame = role[len("disease-"):].partition(":")
        if kind == "claim":
            pool = [frames[frame]] if frame else list(frames.values())
            if not any(rx.fullmatch(canon) for rx in pool):
                errors.append("claim-not-a-frame: %r" % text[:60])
        elif (kind, canon) not in registry:
            errors.append("unregistered-%s: %r" % (kind, text[:60]))
        hits = _da_scan(text, doc, conditions)
        if hits:
            errors.append("forbidden %s: %r" % (hits, text[:60]))
    return errors


def _da_clauses(text):
    """{clause id: paragraph} for every bold clause line `**C-<n> ...`."""
    out, order = {}, []
    hits = list(re.finditer(r"^\*\*(C-\d+) ", text, re.M))
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        head = text.find("\n## ", m.start())
        end = min(end, head) if head != -1 else end
        order.append(m.group(1))
        out[m.group(1)] = text[m.start():end]
    return order, out


def _da_frames(text):
    rows = []
    for ln in text.splitlines():
        if ln.startswith("| FR-"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            rows.append(dict(zip(("frame", "state", "zygosity", "direction", "text", "caveats"), cells)))
    return rows


def _da_scope_words(text):
    words = {}
    for ln in text.splitlines():
        m = re.fullmatch(r"\| ([a-z-]+) \| ([A-Za-z ]+) \|", ln)
        if m and m.group(1) in DA_ANCESTRY_CODES:
            words[m.group(1)] = m.group(2)
    return words


def _da_frame_re(frame, text):
    w = "(?:%s)" % "|".join(re.escape(v) for v in _da_scope_words(text).values())
    rx = re.escape(frame)
    rx = rx.replace("<label>", r"[^():;.]+?").replace("<gene>", r"[A-Za-z0-9-]+").replace("<X>", "[ACGT]")
    rx = rx.replace("<tier>", "(?:%s)" % "|".join(DA_TIER_WORDS))
    rx = rx.replace("<scope>", r"%s(?:, %s)*(?: and %s)? ancestry" % (w, w, w))
    rx = rx.replace("<condition>", r"(?P<cond>[^.;]+?)", 1).replace("<condition>", r"(?P=cond)")
    return re.compile(rx)


def _da_doc_exists_and_clause_ids():
    text = _da_text()
    _require("docs/disease-associations.md exists and is not empty", text.strip())
    order, _ = _da_clauses(text)
    want = ["C-%d" % n for n in range(1, DA_CLAUSE_COUNT + 1)]
    _require("clause ids %s != C-1..C-%d in order, each once" % (order, DA_CLAUSE_COUNT), order == want)
    return True


def _da_r158_markers():
    text = _da_text()
    _, clauses = _da_clauses(text)
    _require("clauses parsed", clauses)
    for cid, body in clauses.items():
        got = tuple(sorted(set(re.findall(r"\(amended: R158-(F\d)\)", body)), key=lambda f: int(f[1:])))
        _require("%s markers %s != %s" % (cid, got, DA_MARKERS.get(cid, ())), got == DA_MARKERS.get(cid, ()))
    for n in range(1, 9):
        _require("marker R158-F%d present" % n, "(amended: R158-F%d)" % n in text)
    total = sum(len(v) for v in DA_MARKERS.values())
    _require("marker count", len(re.findall(r"\(amended: R158-F\d\)", text)) == total)
    return True


def _da_owner_decisions_recorded():
    text = _da_text()
    for n in range(1, 16):
        _require("O-%d row" % n, re.search(r"^\| O-%d \| .+ \| .+ \|$" % n, text, re.M))
    for word in ("Recommended", "recommended", "[DECISION", "Alternative", "DRAFT"):
        _require("draft phrasing %r removed" % word, word not in text)
    return True


def _da_pattern_block_exact():
    text = _da_text()
    block = _da_block(text, "forbidden-patterns")
    _require("pattern block present", block)
    digest = hashlib.sha256(block.encode("utf-8")).hexdigest()
    _require("pattern block sha256 %s != pin" % digest, digest == DA_PATTERN_BLOCK_SHA256)
    pats = _da_patterns(text)
    _require("pattern ids FP-01..FP-%02d" % DA_PATTERN_COUNT,
             [p[0] for p in pats] == ["FP-%02d" % n for n in range(1, DA_PATTERN_COUNT + 1)])
    for pid, _, rx in pats:
        re.compile(rx)
    return True


def _da_corpus_classified():
    text = _da_text()
    _require("38 corpus cases", len(DA_CORPUS) == 38)
    wrong = []
    for n, oracle, sentence in DA_CORPUS:
        hits = _da_scan(sentence, text, DA_CORPUS_CONDITIONS)
        if bool(hits) != (oracle == "reject"):
            wrong.append((n, oracle, hits))
    _require("corpus misclassified: %s" % wrong, not wrong)
    _require("23 reject, 15 allow", [o for _, o, _ in DA_CORPUS].count("reject") == 23)
    return True


def _da_examples_classified():
    text = _da_text()
    pats = dict((p[0], p[2]) for p in _da_patterns(text))
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")]
            for ln in text.splitlines() if re.match(r"\| FP-\d{2} \|", ln)]
    _require("one example row per pattern", sorted(r[0] for r in rows) == sorted(pats))
    for pid, bad, near in rows:
        _require("%s matches its rejected example" % pid, re.search(pats[pid], bad, re.I))
        _require("%s near-miss passes every pattern: %s" % (pid, _da_scan(near, text)), not _da_scan(near, text))
    return True


def _da_exemptions_exact():
    import caveats
    text = _da_text()
    _, clauses = _da_clauses(text)
    assoc = re.search(r"`(This is a statistical association[^`]+)`", clauses.get("C-37", ""))
    c42 = re.search(r"`(Disease associations come from[^`]+)`", clauses.get("C-42", ""))
    _require("C-37 and C-42 quote their sentences", assoc and c42)
    want = ([("association-sentence", assoc.group(1)), ("TEMPLATE_NOTICE", caveats.TEMPLATE_NOTICE)]
            + [("LIMITATIONS", s) for s in caveats.LIMITATIONS]
            + [("C-42-line", c42.group(1)), ("array_limits", caveats.CAVEAT_REGISTRY["array_limits"])])
    got = [(k, s) for _, k, s in _da_exemptions(text)]
    _require("exemption block %s != production strings" % got, got == want)
    _require("ids EX-01..", [e[0] for e in _da_exemptions(text)] == ["EX-%02d" % n for n in range(1, len(want) + 1)])
    return True


def _da_exemption_adjacency():
    text = _da_text()
    exs = _da_exemptions(text)
    _require("exemptions parsed", exs)
    for eid, _, ex in exs:
        s = ex.replace("<condition>", "Crohn's disease")
        _require("%s alone passes" % eid, not _da_scan(s, text, ("Crohn's disease",)))
        for extra, pid in ((" You have Crohn's disease.", "FP-02"), (" Your odds are higher.", "FP-06")):
            _require("%s next to forbidden text fails" % eid, pid in _da_scan(s + extra, text, ("Crohn's disease",)))
            _require("%s after forbidden text fails" % eid, pid in _da_scan(extra.strip() + " " + s, text, ("Crohn's disease",)))
    for partial in ("is not diagnostic grade.", "and no result is a diagnosis.",
                    "This report is not medical advice, and no result is a diagnosis of you.",
                    "it is not a diagnosis of Crohn's disease and not an estimate of your own risk."):
        _require("partial exemption %r is scanned" % partial, _da_scan(partial, text, ("Crohn's disease",)))
    _require("ID_RE quoted exactly", _da_quoted(text, "ID_RE") == __import__("validate_report").ID_RE.pattern)
    _require("GENE_RE quoted exactly", _da_quoted(text, "GENE_RE") == __import__("validate_report").GENE_RE.pattern)
    return True


def _da_state_frames_and_caveats():
    import caveats
    text = _da_text()
    rows = _da_frames(text)
    _require("frames FR-01..FR-10", [r["frame"] for r in rows] == ["FR-%02d" % n for n in range(1, 11)])
    _require("every state has a frame", sorted({r["state"] for r in rows}) == sorted(DA_STATES))
    for r in rows:
        cav = r["caveats"].split(";")
        _require("%s carries array_limits and disease_ancestry" % r["frame"],
                 cav[:2] == ["array_limits", "disease_ancestry"])
        want = caveats.STATE_CAVEAT.get(r["state"])
        _require("%s state caveat %s" % (r["frame"], cav[2:]), cav[2:] == ([want] if want else []))
        _require("%s frame starts with label and gene" % r["frame"], r["text"].startswith("<label> (<gene>): "))
        copies = {"het": "one copy of the effect allele <X> was detected",
                  "hom_alt": "two copies of the effect allele <X> were detected"}
        if r["zygosity"] in copies:  # R161-10: the frame text is bound to its zygosity column
            other = copies["hom_alt" if r["zygosity"] == "het" else "het"]
            _require("%s says %s" % (r["frame"], r["zygosity"]),
                     copies[r["zygosity"]] in r["text"] and other not in r["text"])
        detected = r["state"] == "detected"
        word = {"susceptibility": "higher odds of", "protective": "lower odds of"}.get(r["direction"])
        _require("%s direction words" % r["frame"],
                 (r["text"].count("higher odds of") + r["text"].count("lower odds of")) == (1 if detected else 0)
                 and (not detected or word in r["text"]))
        sample = (r["text"].replace("<label>", "Example disease").replace("<gene>", "GENE1")
                  .replace("<X>", "A").replace("<tier>", "replicated").replace("<scope>", "European ancestry")
                  .replace("<condition>", "example disease"))
        _require("%s passes the scan: %s" % (r["frame"], _da_scan(sample, text, ("example disease",))),
                 not _da_scan(sample, text, ("example disease",)))
        _require("%s matches its own regex" % r["frame"], _da_frame_re(r["text"], text).fullmatch(sample))
    regs = [_da_frame_re(r["text"], text) for r in rows]
    for n, oracle, sentence in DA_CORPUS:
        hits = [rows[i]["frame"] for i, rx in enumerate(regs) if rx.fullmatch(sentence)]
        if 24 <= n <= 34 or n == 38:
            _require("corpus claim %d matches exactly one frame: %s" % (n, hits), len(hits) == 1)
            _require("corpus claim %d matches its own frame %s, got %s" % (n, DA_FRAME_EXPECT[n], hits),
                     hits == [DA_FRAME_EXPECT[n]])  # R161-10
        elif oracle == "reject":
            _require("corpus case %d matches no frame" % n, not hits)
    return True


def _da_scope_vocabulary():
    words = _da_scope_words(_da_text())
    _require("scope words %s" % words, tuple(words) == DA_ANCESTRY_CODES)
    return True


def _da_panel_curation_records_contract():
    text = open(CURATION, encoding="utf-8").read()
    flat = _flat(text)
    for phrase in ("| `disease_association` | `disease` |", "## Disease associations",
                   "(disease-associations.md)", "`SUSC` with `disease_association` and no supporting group",
                   "`gnomad:<chrom>-<pos>-<ref>-<alt>`", "- `proxy-only` (disease rows:",
                   "- `ancestry-unrecorded` (disease rows:", "never used when any row exists under the candidate rsID",
                   "`independence:<cohort-a>|<cohort-b>=<typed id>[,<typed id>...] (<basis>)`",
                   "`or:<row id>=<value> (<low>-<high>)`", "`af-spread:<number> over <group>[,<group>...]`",
                   "`alias-review:<alias>=<sameness reason>`", "`ancestry-scope:<code>[,<code>...]`",
                   "`<stage>:<code>[+<code>...]`", "`functional-not-counted`",
                   "The targets file and the build still reject it"):
        _require("panel-curation lacks %r" % phrase, _flat(phrase) in flat)
    return True


def _da_loop_spec_s1_record():
    text = open(LOOP_SPEC, encoding="utf-8").read()
    head = "## v0.4.0 run: S1 disease-association contract (decisions log)"
    _require("one S1 decisions heading", text.count(head) == 1)
    tail = _flat(text[text.index(head):])
    for phrase in ["feat/v0.4.0-disease-associations", "debf910", "2026-11-24", "R158", "S3"] + \
            ["**O-%d" % n for n in range(1, 16)] + ["F%d" % n for n in range(1, 9)]:
        _require("S1 record lacks %r" % phrase, phrase in tail)
    return True



# ------------------------------------- v0.4.0 S1 FIX r162: r160/r161 review regressions

DA_FIX_MARKERS = {  # clause -> the r160/r161 findings that amended it (owner dispositions, 2026-11-24)
    "C-10": ("R161-02",), "C-12": ("R160-F2", "R161-05"), "C-13": ("R161-06",), "C-20": ("R161-08",),
    "C-25": ("R161-03", "R161-06"), "C-26": ("R161-03",), "C-29": ("R161-10",),
    "C-43": ("R160-F1", "R161-01", "R161-04", "R161-09"), "C-49": ("R160-F2", "R161-05"),
    "C-50": ("R161-02",), "C-52": ("R161-07",),
}
DA_C43_SCOPE = ("Apply FP-01 through FP-33 to each disease-association claim and to the caveats, notices "
                "and limitations used for disease-association reporting. Existing result-type claims and "
                "legacy Summary claims retain their existing validation and exact template wording. A report "
                "that mixes result types must pass with the existing carrier-status, ClinVar association and "
                "trait wording intact, and must fail if prohibited wording is introduced in the disease claim "
                "or its associated text.")
DA_C52_ALL_EXCLUDED = ("In the all-excluded outcome no production code, schema or template change ships; only "
                       "the contract document and the S1 checkers ship, with the documented exclusions, the "
                       "unchanged nine-entry panel and the O-8 version policy. S3 is not run.")
DA_REASSURANCE_CASES = (
    "Nothing to worry about.", "There is nothing to worry about.", "No need to worry about this result.",
    "You do not need to worry.", "Don't worry about this result.", "This result is reassuring.",
    "No follow-up is needed for this result.", "No further testing is required.",
    "No follow up needed.", "You are fine.", "Your chances could be higher.",
    "You could end up with Crohn's disease.",
)
DA_CONFUSABLE_CASES = ("You hаve Crohn's disease.", "You were diаgnosed.", "Your rіsk is higher.",
                       "You have Crohn's disease.", "Ｙou have Crohn's disease.")


def _da_fix_r160_r161_markers():
    text = _da_text()
    _, clauses = _da_clauses(text)
    _require("clauses parsed", clauses)
    for cid, body in clauses.items():
        got = tuple(sorted(set(re.findall(r"\(amended: (R16[01]-(?:F\d|\d\d))\)", body))))
        _require("%s markers %s != %s" % (cid, got, DA_FIX_MARKERS.get(cid, ())),
                 got == tuple(sorted(DA_FIX_MARKERS.get(cid, ()))))
    return True


def _da_fix_s01_scope_sentence():
    _, clauses = _da_clauses(_da_text())
    _require("C-43 states the R161-01 scope", _flat(DA_C43_SCOPE) in _flat(clauses.get("C-43", "")))
    return True


def _da_fix_lf1_reassurance_and_confusables():
    text = _da_text()
    for case in DA_REASSURANCE_CASES + DA_CONFUSABLE_CASES:
        _require("rejected: %r" % case, _da_scan(case, text, ("Crohn's disease",)))
    return True


def _da_fix_s04_glued_exemptions_scanned():
    text = _da_text()
    exs = {eid: s for eid, _, s in _da_exemptions(text)}
    _require("exemptions parsed", exs)
    assoc = exs["EX-01"].replace("<condition>", "Example disease")
    for s in (exs["EX-12"], assoc, exs["EX-06"], exs["EX-02"]):
        _require("standalone exemption passes", not _da_scan(s, text, ("Example disease",)))
        for variant in ("X" + s, s + "X", "Note:" + s, s[:-1] + " today."):
            _require("glued exemption is scanned: %r" % variant[:50], _da_scan(variant, text, ("Example disease",)))
    return True


def _da_fix_s10_frame_swap_rejected():
    global _da_text
    real = _da_text
    doc = real()
    swapped = doc.replace("one copy of the effect allele <X> was detected", "\x00ONE\x00") \
        .replace("two copies of the effect allele <X> were detected", "one copy of the effect allele <X> was detected") \
        .replace("\x00ONE\x00", "two copies of the effect allele <X> were detected")
    _require("swap changed the frames", swapped != doc)
    _da_text = lambda: swapped
    try:
        try:
            _da_state_frames_and_caveats()
        except _Gate:
            return True
        _require("a one-copy/two-copy frame swap is rejected by the frame gate", False)
    finally:
        _da_text = real
    return True


def _da_fix_s07_c52_sentence():
    _, clauses = _da_clauses(_da_text())
    body = _flat(clauses.get("C-52", ""))
    _require("C-52 states the amended all-excluded outcome", _flat(DA_C52_ALL_EXCLUDED) in body)
    _require("C-52 no longer ships template changes in the all-excluded outcome",
             "the template changes (tested with invented fixtures) still ship" not in body)
    return True


def _da_fix_loop_spec_dispositions():
    text = open(LOOP_SPEC, encoding="utf-8").read()
    head = "## v0.4.0 run: S1 disease-association contract (decisions log)"
    _require("S1 heading", head in text)
    tail = _flat(text[text.index(head):])
    for d in ["**S-%02d" % n for n in range(1, 11)] + ["**L-F1", "**L-F2", "**C-52 amendment"]:
        _require("S1 record lacks %r" % d, d in tail)
    return True



DA_MIXED_OTHER = (
    ("carrier-claim", "Example carrier condition (GENE2): one copy of the effect allele T was detected (carrier "
                      "status for example carrier condition; one copy is not the condition itself)."),
    ("association-claim", "Example thrombophilia (GENE4): one copy of the effect allele A was detected. This is an "
                          "association with example thrombophilia; this report does not diagnose the condition."),
    ("trait-claim", "Example trait (GENE3): one copy of the effect allele C was detected. Evidence tier: "
                    "replicated, from the GWAS Catalog association count. This is a statistical association with "
                    "example trait in published studies; it is not a measurement of example trait and not a "
                    "diagnosis."),
)


def _da_mixed_items(doc):
    import caveats
    claim = next(s for n, _, s in DA_CORPUS if n == 24)
    reg = {rid: s for _, _, rid, s in _da_registry(doc)}
    return list(DA_MIXED_OTHER) + [
        ("disease-claim:FR-01", claim), ("disease-caveat", reg["array_limits"]),
        ("disease-caveat", reg["disease_ancestry"]), ("disease-notice", caveats.TEMPLATE_NOTICE),
        ("disease-limitation", reg["C-42-line"])]


def _da_fix_registry_pinned():
    import caveats
    text = _da_text()
    _, clauses = _da_clauses(text)
    c27 = re.search(r'"(The studies behind this association[^"]+)"', clauses.get("C-27", ""))
    c42 = re.search(r"`(Disease associations come from[^`]+)`", clauses.get("C-42", ""))
    _require("C-27 and C-42 quote their texts", c27 and c42)
    want = ([("caveat", "array_limits", caveats.CAVEAT_REGISTRY["array_limits"]),
             ("caveat", "disease_ancestry", " ".join(c27.group(1).split()))]
            + [("caveat", k, caveats.CAVEAT_REGISTRY[k])
               for k in ("no_call", "uninterpretable", "not_covered", "not_assayable", "rare_ppv")]
            + [("notice", "TEMPLATE_NOTICE", caveats.TEMPLATE_NOTICE)]
            + [("limitation", "LIMITATIONS", s) for s in caveats.LIMITATIONS]
            + [("limitation", "C-42-line", c42.group(1))])
    got = [(role, rid, s) for _, role, rid, s in _da_registry(text)]
    _require("registry block %s != production strings" % got, got == want)
    _require("ids RG-01..", [r[0] for r in _da_registry(text)] == ["RG-%02d" % n for n in range(1, len(want) + 1)])
    for role, rid, s in want:
        _require("registered %s passes the report check" % rid,
                 not _da_report_errors([("disease-" + role, s)], text))
    return True


def _da_fix_mixed_report():
    text = _da_text()
    items = _da_mixed_items(text)
    errs = _da_report_errors(items, text, ("Crohn's disease",))
    _require("mixed report passes with legacy wording intact: %s" % errs, not errs)
    _require("the legacy carrier claim alone would trip FP-29", "FP-29" in _da_scan(DA_MIXED_OTHER[0][1], text))
    bad = [list(items) for _ in range(4)]
    bad[0][3] = ("disease-claim:FR-01", items[3][1] + " You have Crohn's disease.")
    bad[1][5] = ("disease-caveat", items[5][1] + " Nothing to worry about.")
    bad[2][4] = ("disease-caveat", "This result is limited to the cited studies.")
    bad[3][3] = ("disease-claim:FR-01", items[3][1].replace("one copy", "two copies").replace("was detected",
                                                                                         "were detected"))
    for i, b in enumerate(bad):
        _require("mixed report variant %d fails" % i, _da_report_errors(b, text, ("Crohn's disease",)))
    return True


def _da_fix_r160_cases_rejected_as_report_text():
    text = _da_text()
    _require("notice 'Nothing to worry about.' rejected",
             _da_report_errors([("disease-notice", "Nothing to worry about.")], text))
    _require("claim with a Cyrillic letter rejected",
             _da_report_errors([("disease-claim", "You hаve Crohn's disease.")], text))
    _require("Cyrillic letter reported as NONASCII", "NONASCII" in _da_scan("You hаve Crohn's disease.", text))
    return True


def _da_fix_lf1_compatibility_forms():
    """C-43 step 0: NFKC maps compatibility forms to the characters the patterns read."""
    text = _da_text()
    _require("full-width percent read as %", "FP-11" in _da_scan("The odds rose by ten \uff05.", text))
    _require("full-width letters read as Latin", "FP-02" in _da_scan("\uff39\uff4fu have the condition.", text))
    _require("no-break space collapsed", "FP-02" in _da_scan("You\u00a0have the condition.", text))
    _require("a registered caveat passes after canonicalization",
             not _da_scan("Rare array calls can be inaccurate;  a rare result should be confirmed by a "
                          "clinical-grade test.", text))
    return True


def _da_with_doc(doc, fn):
    global _da_text
    real = _da_text
    _da_text = lambda: doc
    try:
        fn()
    except _Gate:
        return False
    finally:
        _da_text = real
    return True


def _da_fix_frame_bindings_independent():
    doc = _da_text()
    rows = {r["frame"]: r for r in _da_frames(doc)}
    # (a) zygosity column changed, text unchanged: only the zygosity binding sees it.
    a = doc.replace("| FR-01 | detected | het |", "| FR-01 | detected | hom_alt |", 1)
    _require("column edit applied", a != doc)
    _require("zygosity column bound to the frame text", not _da_with_doc(a, _da_state_frames_and_caveats))
    # (b) FR-01 and FR-03 rows trade ids: each row stays self-consistent, the claim binding fails.
    l1 = next(ln for ln in doc.splitlines() if ln.startswith("| FR-01 |"))
    l3 = next(ln for ln in doc.splitlines() if ln.startswith("| FR-03 |"))
    b = doc.replace(l1, "\x00").replace(l3, l1.replace("| FR-01 |", "| FR-03 |")).replace(
        "\x00", l3.replace("| FR-03 |", "| FR-01 |"))
    _require("row trade applied", b != doc and rows)
    _require("archived claims bound to their frame ids", not _da_with_doc(b, _da_state_frames_and_caveats))
    for sentence, frame in (("Example disease (GENE1): both copies match the reference at this position; the "
                             "effect allele was not found in the genotype.", "FR-05"),
                            ("Example disease (GENE1): no copy of the effect allele was found in the genotype at "
                             "this position.", "FR-06")):
        hits = [f for f, r in rows.items() if _da_frame_re(r["text"], doc).fullmatch(sentence)]
        _require("reference claim matches %s only: %s" % (frame, hits), hits == [frame])
    return True


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

    attempt("R4B.readme_mentions_release_panel_workflow", _readme_release_panel_workflow)
    attempt("R4B.readme_names_private_output_location_rule", _readme_private_output_rule)
    attempt("R4B.readme_template_only_command", _readme_template_only_command)
    attempt("R4B.readme_limitations_list", _readme_limitations_list)
    attempt("R4B.readme_no_real_paths_or_names", _readme_no_real_paths_or_names)
    attempt("R4B.version_consistent", _version_consistent)
    attempt("R4B.runtime_dependencies_empty", _runtime_dependencies_empty)
    attempt("R4B.readme_status_exact", _readme_status_exact)
    attempt("R4B.readme_testing_section_complete", _readme_testing_section_complete)
    attempt("R4B.agents_md_current_state", _agents_md_current_state)
    attempt("R4B.accepted_limits_rows_append_only", _accepted_limits_rows_append_only)
    attempt("R4B.release_doc_status_section", _release_doc_status_section)
    attempt("R4B.accepted_limits_rows_028_to_030_present",
            _accepted_limits_rows_028_to_030_present)
    attempt("R4B.accepted_limits_existing_rows_unchanged_after_029",
            _accepted_limits_existing_rows_unchanged_after_029)
    attempt("R4B.curation_limitations_no_reserves_sentence",
            _curation_limitations_no_reserves_sentence)
    attempt("R4B.curation_reserves_section_states_none_exist",
            _curation_reserves_section_states_none_exist)
    attempt("R4B.release_doc_dod_amendment", _release_doc_dod_amendment)

    attempt("R5.readme_pick_your_path_names_three_paths", _readme_pick_your_path)
    attempt("R5.readme_links_new_docs_and_they_exist", _readme_links_new_docs)
    attempt("R5.readme_documentation_map", _readme_documentation_map)
    attempt("R5.readme_keeps_sections_and_moves_reference_content",
            _readme_kept_sections_and_moved_content)
    attempt("R5.readme_quickstart_a_content", _readme_quickstart_a)
    attempt("R5.readme_quickstart_commands_run", _readme_quickstart_commands_run)
    attempt("R5.new_docs_have_required_headings", _new_docs_headings)
    attempt("R5.relative_links_resolve", _docs_relative_links_resolve)
    attempt("R5.new_docs_offline_commands_run", _docs_offline_commands_run)
    attempt("R5.new_docs_flags_exist_in_help", _docs_flags_exist_in_help)
    attempt("R5.reference_data_names_sources_fixtures_and_links",
            _reference_data_names_sources_fixtures_and_files)
    attempt("R5.reference_data_cache_names_match_code",
            _reference_data_cache_names_match_code)
    attempt("R5.new_docs_content_pins", _new_docs_content_pins)
    attempt("R5.report_excerpts_are_real", _report_excerpts_are_real)
    attempt("R5.docs_are_generic_text", _new_docs_generic_text)
    attempt("R5.reference_data_cache_table_matches_code",
            _reference_data_cache_table_matches_code)
    attempt("R5.reference_data_flag_rows_match_flags",
            _reference_data_flag_rows_match_flags)
    attempt("R5.readme_where_to_keep_files_pinned", _readme_where_to_keep_files_pinned)
    attempt("R5.symlink_statements_text", _symlink_statements_text)
    attempt("R5.symlink_statements_match_cli", _symlink_statements_match_cli)
    attempt("R5.docs_flags_are_real_flags", _docs_flags_are_real)
    attempt("R5.docs_fixture_paths_exist", _docs_fixture_paths_exist)
    attempt("R6.readme_opening_states_template_path_first", _r6_readme_opening_template_first)
    attempt("R6.pick_your_path_says_template_only_once", _r6_pick_your_path_says_template_only_once)
    attempt("R6.readme_how_it_works_marks_the_template_path", _r6_readme_how_it_works_marks_the_template_path)
    attempt("R6.getting_started_says_template_only_and_not_verified",
            _r6_getting_started_says_template_only_and_not_verified)
    attempt("R6.getting_started_explains_used_fallback", _r6_used_fallback_explained)
    attempt("R6.getting_started_template_failure_troubleshooting", _r6_template_failure_troubleshooting)
    attempt("R6.template_failure_example_is_real", _r6_template_failure_example_is_real)
    attempt("R6.accepted_limits_al031_al032_verbatim", _r6_accepted_limits_al031_al032_verbatim)
    attempt("S3B.docs_panel_counts_match_panel", _s3b_docs_panel_counts_match_panel)
    attempt("S3B.limitation_panel_statement_count_free",
            _s3b_limitation_panel_statement_count_free)
    attempt("S3B.multi_allelic_rows_have_note", _s3b_multi_allelic_rows_have_note)
    attempt("S3B.loop_spec_records_d8", _s3b_loop_spec_records_d8)
    attempt("S3B.curation_release_paragraph_matches_tables",
            _s3b_curation_release_paragraph_matches_tables)
    attempt("S3B.release_paragraph_gate_rejects_contradictions",
            _s3b_release_paragraph_gate_rejects_contradictions)
    attempt("L.runner_copies_guard_selftest_files", _runner_copies_guard_selftest_files)
    attempt("V030S3.release_wording", _v030s3_release_wording)
    attempt("V030S3.accepted_limits_rows", _v030s3_accepted_limits_rows)
    attempt("V030S3F.docs_excerpt_reflects_equal_reference_sentence",
            _v030s3f_excerpt_reflects_equal_reference_sentence)
    attempt("V030S3G.no_release_claim_in_release_docs", _v030s3g_no_release_claim_in_release_docs)
    attempt("DA.doc_exists_and_clause_ids", _da_doc_exists_and_clause_ids)
    attempt("DA.r158_markers_on_amended_clauses", _da_r158_markers)
    attempt("DA.owner_decisions_recorded", _da_owner_decisions_recorded)
    attempt("DA.forbidden_pattern_block_exact", _da_pattern_block_exact)
    attempt("DA.r158_corpus_classified_by_oracle", _da_corpus_classified)
    attempt("DA.pattern_examples_classified", _da_examples_classified)
    attempt("DA.exemptions_equal_production_strings", _da_exemptions_exact)
    attempt("DA.exemptions_exact_and_adjacency_scanned", _da_exemption_adjacency)
    attempt("DA.state_frames_and_caveats", _da_state_frames_and_caveats)
    attempt("DA.scope_words_equal_vocabulary", _da_scope_vocabulary)
    attempt("DA.panel_curation_records_contract", _da_panel_curation_records_contract)
    attempt("DA.loop_spec_records_s1_decisions", _da_loop_spec_s1_record)
    attempt("DA.fix_r160_r161_markers_on_amended_clauses", _da_fix_r160_r161_markers)
    attempt("DA.fix_s01_c43_scope_sentence", _da_fix_s01_scope_sentence)
    attempt("DA.fix_lf1_reassurance_and_confusables_rejected", _da_fix_lf1_reassurance_and_confusables)
    attempt("DA.fix_s04_glued_exemptions_scanned", _da_fix_s04_glued_exemptions_scanned)
    attempt("DA.fix_s10_frame_swap_rejected", _da_fix_s10_frame_swap_rejected)
    attempt("DA.fix_s07_c52_all_excluded_sentence", _da_fix_s07_c52_sentence)
    attempt("DA.fix_loop_spec_records_dispositions", _da_fix_loop_spec_dispositions)
    attempt("DA.fix_s09_registry_pinned_and_passes", _da_fix_registry_pinned)
    attempt("DA.fix_s01_mixed_report_template_text", _da_fix_mixed_report)
    attempt("DA.fix_lf1_r160_cases_rejected_as_report_text", _da_fix_r160_cases_rejected_as_report_text)
    attempt("DA.fix_s10_frame_bindings_independent", _da_fix_frame_bindings_independent)
    attempt("DA.fix_lf1_compatibility_forms_normalized", _da_fix_lf1_compatibility_forms)


def main():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    import runtmp
    runtmp.activate(tool="test_docs_release")
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
