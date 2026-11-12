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

AGENTS_CURRENT_STATE = """## Current state (v0.1.0 release run)

The release branch carries the reviewed v0.1.0 work: a curated three-entry health
panel (no trait entries), the template report, the owner-checkpoint procedure
(docs/owner-checkpoint.md) and the accepted-limits register
(docs/accepted-limits.md). The remaining steps are owner-only: the private
real-data checkpoint, repository branch protection, and the release tag.

The real-data checkpoint is owner-only, in a separate local environment. Keep
real DNA, findings, reports, private logs, and hashes outside all agent-accessible
repository, mailbox, export, and scratch trees. The owner may confirm local
completion without sharing results. Use synthetic fixtures in coding/review
sessions; reproduce failures synthetically before sharing them. Fetch public
references only from curated public targets, never personal coverage or genotypes.
Do not request private outputs for analysis."""

AGENTS_ROADMAP_ITEMS = (
    "2. **Curate a usable panel — DONE for v0.1.0** (three health entries, no "
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

README_STATUS = (
    "Release candidate v0.1.0. The pipeline runs end to end on synthetic "
    "fixtures: parse, annotate, a curated three-entry release panel, and a "
    "deterministic template report. The first real-file run is the owner's "
    "local checkpoint (docs/owner-checkpoint.md). Model narration (skeleton "
    "and full modes) and the online path exist but are not part of the "
    "verified v0.1.0 scope. Known gaps and accepted limits are listed in "
    "docs/accepted-limits.md and DESIGN.md."
)

REQUIREMENTS_PHRASE = ("Python 3.12 or 3.14 (the CI matrix); other 3.12+ "
                       "versions are expected to work.")

# (README key phrase, document, phrase that document must carry)
LIMITATION_KEYS = (
    ("about 0.02% of the genome", CHECKPOINT, "about 0.02% of the genome"),
    ("array presence of each marker is not verified", CURATION,
     "array presence not verified"),
    ("three health entries and no trait entries", CHECKPOINT,
     "three health entries"),
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
    for phrase in ("three health-related entries", "no trait entries",
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
    sec = _flat(_section(_read(README), "Known limitations (v0.1.0)")).lower()
    for phrase, doc, doc_phrase in LIMITATION_KEYS:
        _require("README limitation lacks " + phrase, phrase in sec)
        if doc is not None:
            _require("%s lacks %r" % (os.path.basename(doc), doc_phrase),
                     doc_phrase in _flat(_read(doc)))
    items = [l for l in _section(_read(README), "Known limitations (v0.1.0)")
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
    _require("pyproject version", meta["project"]["version"] == "0.1.0")
    import snp_insights
    _require("package version", snp_insights.__version__ == "0.1.0")
    flat = _flat(_read(README))
    _require("README version output", "snp-insights 0.1.0" in flat)
    _require("README release-candidate status", "Release candidate v0.1.0." in flat)
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
             re.search(r"^## Current state \(v0\.1\.0 release run\)$", text, re.M))
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
    _require("only the approved rows AL-014..AL-030 were appended",
             [l[2:8] for l in appended]
             == sorted(NEW_ROW_SHA256) + sorted(CLOSURE_ROWS))
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
    _require("rows are in order, 028..030 last",
             order == sorted(order) and order[-3:] == sorted(CLOSURE_ROWS))
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
    "How it works", "Why", "Requirements", "Known limitations (v0.1.0)",
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
    _require("decision section answers no for v0.1.0",
             "v0.1.0" in decision and "no" in decision.lower())
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
                   "even with `--force`",
                   "an `--out-dir` that exists as a file",
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
    attempt("R4B.version_0_1_0_consistent", _version_consistent)
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
