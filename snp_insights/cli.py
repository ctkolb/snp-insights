# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Single-entrypoint `snp-insights` CLI.

Dispatches by hand on the first word of argv and forwards everything after the
subcommand verbatim to the sub-tool's ``main(list_of_args)``. The sub-tool
modules live outside this package (``tools/``, ``stage2/``, ``stage3/``,
``scripts/``); their directories are added to ``sys.path`` at call time so the
CLI works from any working directory with the repo root importable.

Privacy: the CLI never adds, removes, rewrites, or defaults ``--endpoint``,
``--model``, ``--accept-privacy-risk``, ``--send-alleles``, or
``--keep-input-hash``. ``fetch`` accepts no raw-file argument.
"""
import importlib
import os
import sys

from snp_insights import __version__

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

_SUBCOMMAND_MODULES = {
    "fetch": "fetch_reference",
    "build-panel": "build_panel",
    "check-raw": "check_raw",
    "annotate": "annotate",
    "narrate": "run",
}

_SUBCOMMAND_HELP = [
    ("fetch", "fetch reference data into the local cache"),
    ("build-panel", "build an enriched panel snapshot"),
    ("check-raw", "inspect a raw DNA file offline"),
    ("annotate", "annotate a raw file into findings.json"),
    ("narrate", "synthesize a report from findings.json"),
    ("run", "annotate then narrate (local by default)"),
]

_SUBCOMMANDS = tuple(name for name, _ in _SUBCOMMAND_HELP)

DEFAULT_OUT_DIR = "./snp-insights-out"
_OUTPUT_NAMES = ("findings.json", "report.md", "report.ir.json", "report.run.json")

_REMINDER = ("reminder: findings.json is private health data; it stays on this "
             "machine and is only sent to an online model if you opt in.")

_TOOL_DIRS = ("tools", "stage2", "stage3", "scripts")


class _UsageError(Exception):
    """A `run` command-line usage error (exit code 2)."""


def _ensure_tool_paths():
    for sub in _TOOL_DIRS:
        path = os.path.join(_ROOT, sub)
        if path not in sys.path:
            sys.path.insert(0, path)


def _tool_module(name):
    _ensure_tool_paths()
    return importlib.import_module(name)


def _usage():
    lines = ["usage: snp-insights <command> [options]", "", "commands:"]
    for name, desc in _SUBCOMMAND_HELP:
        lines.append("  %-12s %s" % (name, desc))
    lines.append("")
    lines.append("  --version    print the version and exit")
    return "\n".join(lines)


def _call(module, args):
    rc = module.main(list(args))
    return 0 if rc is None else rc


def _run_tool(sub, args):
    return _call(_tool_module(_SUBCOMMAND_MODULES[sub]), args)


def _parse_run(args):
    if len(args) < 2:
        raise _UsageError("run needs RAW and PANEL")
    raw, panel = args[0], args[1]
    if raw.startswith("-") or panel.startswith("-"):
        raise _UsageError("run needs RAW and PANEL before any flag")
    out_dir = None
    force = False
    forwarded = []
    rest = args[2:]
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok in ("-o", "--out") or tok.startswith("--out="):
            raise _UsageError("the output location is set by --out-dir, not -o/--out")
        if tok == "--out-dir":
            if i + 1 >= len(rest):
                raise _UsageError("--out-dir needs a value")
            out_dir = rest[i + 1]
            i += 2
            continue
        if tok.startswith("--out-dir="):
            out_dir = tok.split("=", 1)[1]
            i += 1
            continue
        if tok == "--force":
            force = True
            i += 1
            continue
        forwarded.append(tok)
        i += 1
    return raw, panel, (out_dir or DEFAULT_OUT_DIR), force, forwarded


def _run_pipeline(args):
    try:
        raw, panel, out_dir, force, forwarded = _parse_run(args)
    except _UsageError as exc:
        print("snp-insights run: " + str(exc), file=sys.stderr)
        print(_usage(), file=sys.stderr)
        return 2

    paths = {name: os.path.join(out_dir, name) for name in _OUTPUT_NAMES}
    if not force:
        existing = [p for p in paths.values() if os.path.exists(p)]
        if existing:
            print("snp-insights run: refusing to overwrite existing output in "
                  "%s (use --force):" % out_dir, file=sys.stderr)
            for p in existing:
                print("  " + p, file=sys.stderr)
            return 1

    os.makedirs(out_dir, exist_ok=True)
    print(_REMINDER, file=sys.stderr)

    findings = paths["findings.json"]
    rc = _call(_tool_module("annotate"), [raw, panel, "-o", findings])
    if rc != 0:
        return rc

    report = paths["report.md"]
    return _call(_tool_module("run"), [findings] + forwarded + ["-o", report])


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)
    if not argv:
        print(_usage())
        return 0
    first = argv[0]
    if first in ("-h", "--help"):
        print(_usage())
        return 0
    if first == "--version":
        print("snp-insights " + __version__)
        return 0
    if first in _SUBCOMMAND_MODULES:
        return _run_tool(first, argv[1:])
    if first == "run":
        return _run_pipeline(argv[1:])
    print("snp-insights: unknown command: %s" % first, file=sys.stderr)
    print(_usage(), file=sys.stderr)
    return 2
