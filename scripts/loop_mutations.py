#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Mutation check for the build loop. Pure standard library, offline.

Copies the repo's code and tests into a temp directory, applies ONE deliberate
bug at a time, and runs the test suites. A mutation is KILLED when it makes a
check fail that passes on the unmutated copy; it SURVIVES otherwise. Surviving
mutations mean the tests do not pin that behavior.

The unmutated copy is run first as a baseline because the copy has no .git
directory, so a guard self-test always fails there. Only NEW failures count.
Your working tree is never modified; the temp directory is removed at the end.

    python scripts/loop_mutations.py            # run all mutations, exit 1 on any survivor
    python scripts/loop_mutations.py --list     # print the mutation names
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
E_ = "tools/evidence.py"
B = "tools/build_panel.py"
C = "snp_insights/cli.py"
P = "pyproject.toml"
I_ = "snp_insights/__init__.py"
F = "tools/fetch_reference.py"
SUITES = ("tests/test_evidence.py", "tests/test_category.py", "tests/test_cli.py", "tests/test_pipeline.py")
COPY_DIRS = ("tools", "tests", "data", "fixtures", "stage2", "stage3", "schema", "scripts", "snp_insights")
COPY_FILES = ("pyproject.toml", "README.md")

# (name, file, text to find, replacement). Each is a single plausible bug.
MUTATIONS = [
 ("matched-first removed",E_,"        if matched:\n            candidates = matched","        if False:\n            candidates = matched"),
 ("no fallback when nothing matches",E_,"        if matched:\n            candidates = matched","        candidates = matched"),
 ("ties last-wins",E_,"score > best_score","score >= best_score"),
 ("stars ignored",E_,"+ (review_stars(r.get(\"review\")) or 0)","+ 0"),
 ("word boundary -> substring",E_,"return re.search(r\"(?<![a-z0-9])\" + re.escape(needle) + r\"(?![a-z0-9])\", haystack) is not None","return needle in haystack"),
 ("empty sig is candidate",E_,"        if not sig:\n            continue\n        candidates.append(r)","        candidates.append(dict(r, sig=sig or 'x'))"),
 ("norm_cond no punctuation strip",E_,"re.sub(r\"[^a-z0-9 ]\", \" \", (text or \"\").lower())","(text or \"\").lower()"),
 ("load_aliases no validation",E_,"if not isinstance(value, list) or not all(isinstance(m, str) for m in value):","if False:"),
 ("string alias iterated",E_,"        return [value]\n    if isinstance(value, list)","        return list(value)\n    if isinstance(value, list)"),
 ("BOM plain",B,"return open(path, encoding=\"utf-8-sig\")","return open(path, encoding=\"utf-8\")"),
 ("BOM gz",B,"encoding=\"utf-8-sig\")\n    return open","encoding=\"utf-8\")\n    return open"),
 ("clinvar writer unsanitized phenotype",F,"{_tsv_field(phenotype)}","{phenotype}"),
 ("clinvar writer unsanitized sig",F,"{_tsv_field(sig)}","{sig}"),
 ("clinvar writer unsanitized review",F,"{_tsv_field(review)}","{review}"),
 ("OT writer unsanitized trait",F,"{_tsv_field(trait)}","{trait}"),
 ("OT writer unsanitized study",F,"{_tsv_field(sid)}","{sid}"),
 ("alias member lookup removed (reviewer)",E_,"if c == norm_key or c in norm_members:","if c == norm_key:"),
 ("alias key not added to variants",E_,"variants |= {norm_key} | norm_members","variants |= norm_members"),
 ("alias members not added to variants",E_,"variants |= {norm_key} | norm_members","variants |= {norm_key}"),
 ("underscore keys not skipped in variants",E_,'        if key.startswith("_"):\n            continue\n        norm_key','        norm_key'),
 ("alias key not normalized",E_,"norm_key = norm_cond(key)","norm_key = key"),
 ("alias members not normalized",E_,"norm_members = {norm_cond(m) for m in _alias_members(members)}","norm_members = set(_alias_members(members))"),
 ("non-str alias entries kept",E_,"return [m for m in value if isinstance(m, str)]","return list(value)"),
 ("count: study without id counted",E_,"        if not study_id:\n            continue\n","        study_id = study_id or trait\n"),
 ("count: not distinct ids",E_,"ids = set()","ids = []"),
 ("count: falsy condition -> 0",E_,"if not condition or condition_matches","if condition and condition_matches"),
 ("gwas_tier threshold 2->3",E_,"n >= 2","n >= 3"),
 ("review_stars: guideline 4->3",E_,'if "practice guideline" in s:\n        return 4','if "practice guideline" in s:\n        return 3'),
 ("sig_rank: risk factor 3->5",E_,'if "risk factor" in s or "risk allele" in s:\n        return 3','if "risk factor" in s or "risk allele" in s:\n        return 5'),
 ("sig_rank: conflicting 2->0",E_,'if "conflicting" in s:\n        return 2','if "conflicting" in s:\n        return 0'),
 ("sig_rank: drop protective",E_,'or "protective" in s',''),
 ("load_clinvar GRCh38 not skipped",B,'if assembly and not assembly.startswith("GRCh37"):','if False:'),
 ("load_gwas_studies no dedupe",B,"if pair not in seen[rsid]:","if True:"),
 ("load_gwas_studies trait ignored",B,'trait = _col(row, idx, "DISEASE/TRAIT")','trait = ""'),
    # --- Stage 2: category-aware derivation ---
    ("S2 trait: ClinVar overrides GWAS", E_, "        if n >= 1:\n            return gwas_tier(n)", "        if n >= 1 and not cv_tier:\n            return gwas_tier(n)"),
    ("S2 trait: one study not enough", E_, "        if n >= 1:\n            return gwas_tier(n)", "        if n >= 2:\n            return gwas_tier(n)"),
    ("S2 trait: fallback ignores cv_matched", E_, "        if cv and cv_matched:", "        if cv:"),
    ("S2 trait: matched 0-star returns None", E_, "        if cv and cv_matched:\n            return cv_tier or \"unknown\"", "        if cv and cv_matched:\n            return cv_tier"),
    ("S2 carrier: falls back to GWAS", E_, "        return cv_tier or \"unknown\"\n    if category == \"trait\":", "        return cv_tier or gwas_tier(n) or \"unknown\"\n    if category == \"trait\":"),
    ("S2 carrier: returns None not unknown", E_, "        return cv_tier or \"unknown\"\n    if category == \"trait\":", "        return cv_tier\n    if category == \"trait\":"),
    ("S2 legacy: order swapped", E_, "    return cv_tier or gwas_tier(n) or \"unknown\"", "    return gwas_tier(n) or cv_tier or \"unknown\""),
    ("S2 gwas_n None crashes", E_, "    n = gwas_n or 0", "    n = gwas_n"),
    ("S2 cv None crashes", E_, "cv_tier = clinvar_tier(cv.get(\"significance\"), cv.get(\"review_stars\")) if cv else None", "cv_tier = clinvar_tier(cv.get(\"significance\"), cv.get(\"review_stars\"))"),
    ("S2 validation skipped when association set", B, "category not in (\"carrier\", \"trait\"):\n            label", "category not in (\"carrier\", \"trait\") and not t.get(\"association\"):\n            label"),
    ("S2 validation case-insensitive", B, "if category is not None and category not in (\"carrier\", \"trait\"):", "if category is not None and str(category).lower() not in (\"carrier\", \"trait\"):"),
    ("S2 validation accepts empty string", B, "if category is not None and category not in", "if category and category not in"),
    ("S2 error does not name the target", B, "label = t.get(\"rsid\") or t.get(\"gene\")", "label = \"target\""),
    ("S2 cv_matched always true", B, "cv_matched = bool(cv and", "cv_matched = bool(True or cv and"),
    ("S2 legacy warning removed", B, "            if category is None:\n                print(", "            if False:\n                print("),
    ("S2 main returns 0 on invalid category", B, "        print(exc, file=sys.stderr)\n        return 1", "        print(exc, file=sys.stderr)\n        return 0"),
    ("S2 category not passed through", B, "        v = dict(t)\n", "        v = {k: x for k, x in t.items() if k != \"category\"}\n"),
    # --- Stage 4: single entrypoint ---
    ("S4 run injects --accept-privacy-risk", C, '[findings] + forwarded + ["-o", report]', '[findings, "--accept-privacy-risk"] + forwarded + ["-o", report]'),
    ("S4 run drops forwarded args", C, '[findings] + forwarded + ["-o", report]', '[findings, "-o", report]'),
    ("S4 run reorders forwarded args", C, '[findings] + forwarded + ["-o", report]', '[findings, "-o", report] + forwarded'),
    ("S4 run swaps raw and panel", C, '[raw, panel, "-o", findings]', '[panel, raw, "-o", findings]'),
    ("S4 run allows -o/--out", C, 'if tok in ("-o", "--out") or tok.startswith("--out="):', 'if False:'),
    ("S4 run allows --out=x", C, 'if tok in ("-o", "--out") or tok.startswith("--out="):', 'if tok in ("-o", "--out"):'),
    ("S4 no-clobber disabled", C, "    if not force:", "    if False:"),
    ("S4 no-clobber checks findings only", C, "existing = [p for p in paths.values() if os.path.lexists(p)]", 'existing = [p for p in [paths["findings.json"]] if os.path.lexists(p)]'),
    ("S4 symlink refusal removed", C, "        if os.path.islink(p):", "        if False:"),
    ("S4 symlink refusal skipped with --force", C, "        if os.path.islink(p):", "        if os.path.islink(p) and not force:"),
    ("S4 out-dir-is-file check removed", C, "    if os.path.exists(out_dir) and not os.path.isdir(out_dir):", "    if False:"),
    ("S4 makedirs error not caught", C, "    except OSError as exc:\n        print(\"snp-insights run: cannot create", "    except KeyError as exc:\n        print(\"snp-insights run: cannot create"),
    ("S4 run help not handled", C, '    if "-h" in args or "--help" in args:', "    if False:"),
    ("S4 run help exits 2", C, "        print(_run_usage())\n        return 0", "        print(_run_usage())\n        return 2"),
    ("S4 --force ignored", C, "            force = True\n", "            force = False\n"),
    ("S4 --out-dir= unsupported", C, 'if tok.startswith("--out-dir="):', 'if False:'),
    ("S4 default out dir changed", C, 'DEFAULT_OUT_DIR = "./snp-insights-out"', 'DEFAULT_OUT_DIR = "."'),
    ("S4 annotate failure swallowed", C, "    if rc != 0:\n        return rc", "    if rc != 0:\n        pass"),
    ("S4 exit code swallowed", C, "return 0 if rc is None else rc", "return 0"),
    ("S4 unknown command exits 0", C, '    print(_usage(), file=sys.stderr)\n    return 2', '    print(_usage(), file=sys.stderr)\n    return 0'),
    ("S4 version text changed", C, 'print("snp-insights " + __version__)', 'print("snp-insights v" + __version__)'),
    ("S4 reminder removed", C, "    print(_REMINDER, file=sys.stderr)", "    pass"),
    ("S4 help omits check-raw", C, '    ("check-raw", "inspect a raw DNA file offline"),\n', ''),
    ("S4 fetch mapped to build_panel", C, '"fetch": "fetch_reference"', '"fetch": "build_panel"'),
    ("S4 injects flag into every subcommand", C, "rc = module.main(list(args))", 'rc = module.main(list(args) + ["--accept-privacy-risk"])'),
    ("S4 pyproject version mismatch", P, 'version = "0.1.0"', 'version = "0.1.1"'),
    ("S4 pyproject gains a dependency", P, "dependencies = []", 'dependencies = ["requests"]'),
    ("S4 console script target wrong", P, 'snp_insights.cli:main', 'snp_insights.cli:run'),
    ("S4 __version__ changed", I_, '__version__ = "0.1.0"', '__version__ = "0.2.0"'),
    ("S4 build_panel stdout print removed (AL-007)", B, "    else:\n        print(text)\n    return 0", "    return 0"),
    ("S4 umask not applied", C, "old_umask = os.umask(0o077)", "old_umask = os.umask(0o022)"),
    ("S4 umask group-readable", C, "old_umask = os.umask(0o077)", "old_umask = os.umask(0o027)"),
    ("S4 umask not restored", C, "        os.umask(old_umask)", "        pass"),
    ("S4 repo dirs not front-loaded", C, "        while path in sys.path:\n            sys.path.remove(path)\n        sys.path.insert(0, path)", "        if path not in sys.path:\n            sys.path.insert(0, path)"),
    ("S4 sys.modules integrity check skipped", C, "    bad = _integrity_error()\n    if bad is not None:\n        raise bad", "    bad = None\n    if bad is not None:\n        raise bad"),
    ("S4 post-import location check removed", C, "    if not path or not _within_root(path):\n        raise _ToolIntegrityError", "    if False:\n        raise _ToolIntegrityError"),
    ("S4 run integrity check before outputs removed", C, "    bad = _integrity_error()\n    if bad is not None:\n        print(_integrity_message(bad), file=sys.stderr)\n        return 1", "    pass"),
    ("S4 integrity refusal exits 0", C, "        print(_integrity_message(exc), file=sys.stderr)\n        return 1\n    return _call(module, args)", "        print(_integrity_message(exc), file=sys.stderr)\n        return 0\n    return _call(module, args)"),
    ("S4 within-root prefix without separator", C, "real.startswith(root + os.sep)", "real.startswith(root)"),
    ("S4 within-root uses abspath not realpath", C, "    real = os.path.realpath(path)", "    real = os.path.abspath(path)"),
    ("S4 -- tail placed after -o wrong", C, '[findings] + forwarded + ["-o", report] + ["--"] + after', '[findings] + forwarded + ["--"] + after + ["-o", report]'),
    ("S4 -- separator dropped", C, '["-o", report] + ["--"] + after', '["-o", report] + after'),
    ("S4 -- tail interpreted by run", C, '    if "--" in args:', "    if False:"),
]


def fresh(tmp):
    for d in COPY_DIRS:
        dest = os.path.join(tmp, d)
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(os.path.join(ROOT, d), dest, ignore=shutil.ignore_patterns("__pycache__"))
    for f in COPY_FILES:
        shutil.copy(os.path.join(ROOT, f), os.path.join(tmp, f))


def failing_checks(tmp):
    out = set()
    for suite in SUITES:
        proc = subprocess.run([sys.executable, suite], cwd=tmp, capture_output=True, text=True)
        lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip().startswith("FAIL")]
        out |= set(lines)
        if proc.returncode != 0 and not lines:
            out.add("CRASH " + suite)
    return out


def main():
    if "--list" in sys.argv[1:]:
        for name, _, _, _ in MUTATIONS:
            print(name)
        return 0
    tmp = tempfile.mkdtemp(prefix="loop-mut-")
    survivors = []
    try:
        fresh(tmp)
        base = failing_checks(tmp)
        print("baseline failing checks in the temp copy (ignored): %s" % (sorted(base) or "none"))
        for name, rel, old, new in MUTATIONS:
            fresh(tmp)
            path = os.path.join(tmp, rel)
            with open(path) as fh:
                text = fh.read()
            if old not in text:
                print("PATTERN MISSING (counts as a survivor): " + name)
                survivors.append(name)
                continue
            with open(path, "w") as fh:
                fh.write(text.replace(old, new, 1))
            new_fails = failing_checks(tmp) - base
            if new_fails:
                print("KILLED   %s  <- %s" % (name, sorted(new_fails)[0][:60]))
            else:
                print("SURVIVED %s" % name)
                survivors.append(name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("survivors: %d of %d" % (len(survivors), len(MUTATIONS)))
    for name in survivors:
        print("  - " + name)
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
