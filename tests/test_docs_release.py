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


def _section(text, heading):
    """Body of the level-2 section whose heading starts with `heading`."""
    lines = text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if start is None:
            if line.startswith("## ") and line[3:].startswith(heading):
                start = i + 1
        elif line.startswith("## "):
            return "\n".join(lines[start:i])
    _require("section %r not found" % heading, start is not None)
    return "\n".join(lines[start:])


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rows(text, ids):
    found = {}
    for line in text.split("\n"):
        m = re.match(r"\| (AL-\d{3}) \|", line)
        if m and m.group(1) in ids:
            found[m.group(1)] = line
    return found


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
    heads = [l for l in text.split("\n") if l.startswith("## ")]
    names = [h[3:] for h in heads]
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
    import snp_insights.cli as cli
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
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    try:
                        code = cli.main(argv)
                    except SystemExit as exc:
                        code = exc.code if isinstance(exc.code, int) else 1
                results.append((argv, code, out.getvalue(), err.getvalue()))
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


def _readme_no_real_paths_or_names():
    import guard
    emails = re.compile(r"[\w.+-]+@([\w-]+\.)+[\w-]+")
    british = re.compile(r"\b(colour|behaviour|favour|organis(?:e|ed|ing|ation)"
                         r"|analyse[sd]?|centre|licence|catalogue|grey)\b", re.I)
    for path in (README, AGENTS, LIMITS, RELEASE_DOC, CHECKPOINT):
        text = _read(path)
        name = os.path.basename(path)
        for label, rx in guard.SECRET_PATTERNS:
            _require("%s: guard pattern %s" % (name, label), not rx.search(text))
        for m in emails.finditer(text):
            _require("%s: contact address %s" % (name, m.group(0)),
                     m.group(0).endswith("@example.com"))
        _require("%s: tilde-home path" % name,
                 not re.search(r"~[A-Za-z0-9_-]+/", text))
        _require("%s: British spelling %s" % (name, british.search(text)),
                 not british.search(text))
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
    listed = re.findall(r"^- `(tests/test_[a-z_]+\.py)`", sec, re.M)
    actual = sorted("tests/" + n for n in os.listdir(os.path.join(ROOT, "tests"))
                    if re.fullmatch(r"test_[a-z_]+\.py", n))
    _require("every test file is listed once", sorted(listed) == actual)
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
