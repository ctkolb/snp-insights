#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Stage 4 gates: the single-entrypoint `snp-insights` CLI.

Run standalone:  python tests/test_cli.py
Or as part of:   python tests/test_pipeline.py

Every gate is isolated: a missing module, a missing function, or any exception
fails only that one check (via attempt()), never the whole run.
"""
import contextlib
import io
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("", "tools", "stage2", "stage3", "scripts", "tests"):
    _p = os.path.join(ROOT, _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

DATA = os.path.join(ROOT, "data")
FIX = os.path.join(ROOT, "fixtures")
RAW = os.path.join(FIX, "raw.sample.txt")
PANEL = os.path.join(DATA, "panel.sample.json")
DOC = os.path.join(ROOT, "docs", "owner-checkpoint.md")
RELEASE_PANEL = "data/targets.release-panel.json"
SUBCOMMANDS = ("fetch", "build-panel", "check-raw", "annotate", "narrate", "run")
OUTPUTS = ("findings.json", "report.md", "report.ir.json", "report.run.json")


def _cli():
    import snp_insights.cli as cli
    return cli


def _invoke(argv):
    """Run cli.main(argv), capturing streams and any argparse SystemExit."""
    cli = _cli()
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:  # argparse usage errors / --help
            value = exc.code
            if value is None:
                code = 0
            elif isinstance(value, int):
                code = value
            else:
                code = 1
    return code, out.getvalue(), err.getvalue()


def _patch_main(module_name, ret=0, record=None):
    import importlib
    mod = importlib.import_module(module_name)
    orig = mod.main

    def fake(argv):
        if record is not None:
            record.append(list(argv))
        return ret

    mod.main = fake
    return mod, orig


@contextlib.contextmanager
def _no_network():
    import urllib.request
    import llm
    orig_url, orig_chat = urllib.request.urlopen, llm.chat

    def boom(*a, **k):
        raise AssertionError("network call attempted")

    urllib.request.urlopen = boom
    llm.chat = boom
    try:
        yield
    finally:
        urllib.request.urlopen = orig_url
        llm.chat = orig_chat


def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _get_umask():
    current = os.umask(0)
    os.umask(current)
    return current


def _output_paths(d):
    return {name: os.path.join(d, name) for name in OUTPUTS}


class _ParseStop(Exception):
    """Raised after the real parser has validated a doc command's argv."""


def _parse_only(module, argv):
    """Run a sub-tool's real argparse parser without executing its body."""
    import argparse
    orig = argparse.ArgumentParser.parse_args
    captured = {}

    def fake(self, args=None, namespace=None):
        captured["ns"] = orig(self, args, namespace)
        raise _ParseStop()

    argparse.ArgumentParser.parse_args = fake
    try:
        module.main(argv)
    except _ParseStop:
        return captured.get("ns")
    finally:
        argparse.ArgumentParser.parse_args = orig
    return None


def _doc_text():
    with open(DOC, encoding="utf-8") as fh:
        return fh.read()


def _doc_commands():
    """Every `python -m snp_insights ...` command line in the checkpoint doc."""
    commands = []
    for line in _doc_text().splitlines():
        stripped = line.strip()
        for prefix in ("python3 -m snp_insights ", "python -m snp_insights "):
            if stripped.startswith(prefix):
                commands.append(stripped[len(prefix):])
                break
    return commands


def _run_capture(raw, panel, out_dir, extra=()):
    """Invoke `run` with the annotate/narrate tools stubbed out."""
    ma, oa = _patch_main("annotate", ret=0)
    mn, on = _patch_main("run", ret=0)
    try:
        return _invoke(["run", raw, panel, "--out-dir", out_dir] + list(extra))
    finally:
        ma.main, mn.main = oa, on


def run(check):
    def attempt(name, fn):
        try:
            result = fn()
        except Exception:  # noqa: BLE001
            check(name, False)
            return
        check(name, bool(result))

    # --- S4.help_lists_all ----------------------------------------------
    def s4_help_lists_all():
        for argv in (["--help"], ["-h"], []):
            code, out, _ = _invoke(argv)
            if code != 0:
                return False
            if not all(sub in out for sub in SUBCOMMANDS):
                return False
        return True
    attempt("S4.help_lists_all", s4_help_lists_all)

    # --- S4.version ------------------------------------------------------
    def s4_version():
        import snp_insights
        code, out, _ = _invoke(["--version"])
        return code == 0 and out.strip() == "snp-insights " + snp_insights.__version__
    attempt("S4.version", s4_version)

    # --- S4.unknown_subcommand_exit2 ------------------------------------
    def s4_unknown_subcommand_exit2():
        code, _, _ = _invoke(["definitely-not-a-command"])
        return code == 2
    attempt("S4.unknown_subcommand_exit2", s4_unknown_subcommand_exit2)

    # --- S4.exit_code_propagation ---------------------------------------
    def s4_exit_code_propagation():
        mod, orig = _patch_main("fetch_reference", ret=3)
        try:
            code, _, _ = _invoke(["fetch", "--dry-run"])
        finally:
            mod.main = orig
        return code == 3
    attempt("S4.exit_code_propagation", s4_exit_code_propagation)

    # --- S4.forward_verbatim (all six) ----------------------------------
    def s4_forward_verbatim():
        cases = {
            "fetch": ("fetch_reference",
                      ["--targets", "data/targets.carrier.json", "--dry-run"]),
            "build-panel": ("build_panel", ["--targets", "t.json", "-o", "p.json"]),
            "check-raw": ("check_raw", ["raw.txt", "--no-hash"]),
            "annotate": ("annotate", ["raw.txt", "panel.json", "-o", "f.json"]),
            "narrate": ("run", ["findings.json", "--model", "m", "-o", "report.md"]),
        }
        for sub, (modname, args) in cases.items():
            record = []
            mod, orig = _patch_main(modname, ret=0, record=record)
            try:
                code, _, _ = _invoke([sub] + args)
            finally:
                mod.main = orig
            if code != 0 or record != [args]:
                return False
        return True
    attempt("S4.forward_verbatim", s4_forward_verbatim)

    def s4_forward_verbatim_run():
        d = tempfile.mkdtemp()
        annot, narr = [], []
        ma, oa = _patch_main("annotate", ret=0, record=annot)
        mn, on = _patch_main("run", ret=0, record=narr)
        try:
            code, _, _ = _invoke(["run", "RAW.txt", "PANEL.json", "--out-dir", d,
                                  "--model", "x", "--accept-privacy-risk"])
        finally:
            ma.main, mn.main = oa, on
        want_annot = ["RAW.txt", "PANEL.json", "-o", os.path.join(d, "findings.json")]
        want_narr = [os.path.join(d, "findings.json"), "--model", "x",
                     "--accept-privacy-risk", "-o", os.path.join(d, "report.md")]
        return code == 0 and annot == [want_annot] and narr == [want_narr]
    attempt("S4.forward_verbatim_run", s4_forward_verbatim_run)

    def s4_run_reminder():
        d = tempfile.mkdtemp()
        ma, oa = _patch_main("annotate", ret=0)
        mn, on = _patch_main("run", ret=0)
        try:
            code, _, err = _invoke(["run", RAW, PANEL, "--out-dir", d])
        finally:
            ma.main, mn.main = oa, on
        low = err.lower()
        return code == 0 and "findings.json" in err and "private" in low and "local" in low
    attempt("S4.run_reminder", s4_run_reminder)

    # --- S4.fetch_rejects_raw -------------------------------------------
    def s4_fetch_rejects_raw():
        for argv in (["fetch", "--raw", "x"], ["fetch", "x.txt"]):
            code, _, _ = _invoke(argv)
            if code != 2:
                return False
        return True
    attempt("S4.fetch_rejects_raw", s4_fetch_rejects_raw)

    def s4_fetch_dry_run_no_network():
        with _no_network():
            code, out, _ = _invoke(
                ["fetch", "--targets", os.path.join(DATA, "targets.carrier.json"),
                 "--dry-run"])
        return code == 0 and "rsid" in out.lower()
    attempt("S4.fetch_dry_run_no_network", s4_fetch_dry_run_no_network)

    # --- S4.gate_passthrough (three cases) ------------------------------
    def s4_gate_passthrough_refused():
        d = tempfile.mkdtemp()
        with _no_network():
            code, _, err = _invoke(["run", RAW, PANEL, "--endpoint", "openrouter",
                                    "--out-dir", d])
        if code != 2:
            return False
        if "privacy" not in err.lower() and "risk" not in err.lower():
            return False
        return not os.path.exists(os.path.join(d, "report.md"))
    attempt("S4.gate_passthrough_refused", s4_gate_passthrough_refused)

    def s4_gate_passthrough_accepted():
        d = tempfile.mkdtemp()
        annot, narr = [], []
        ma, oa = _patch_main("annotate", ret=0, record=annot)
        mn, on = _patch_main("run", ret=0, record=narr)
        try:
            code, _, _ = _invoke(["run", RAW, PANEL, "--out-dir", d,
                                  "--endpoint", "openrouter", "--model", "m",
                                  "--accept-privacy-risk"])
        finally:
            ma.main, mn.main = oa, on
        if code != 0 or not narr:
            return False
        argv = narr[0]
        if argv.count("--accept-privacy-risk") != 1:
            return False
        i = argv.index("--endpoint")
        j = argv.index("--model")
        return argv[i:i + 2] == ["--endpoint", "openrouter"] and argv[j:j + 2] == ["--model", "m"]
    attempt("S4.gate_passthrough_accepted", s4_gate_passthrough_accepted)

    def s4_gate_passthrough_never_injected():
        d = tempfile.mkdtemp()
        saved = dict(os.environ)
        os.environ["SNP_INSIGHTS_ACCEPT_PRIVACY_RISK"] = "1"
        os.environ["SNP_INSIGHTS_AUTO_ACCEPT"] = "yes"
        narr = []
        ma, oa = _patch_main("annotate", ret=0)
        mn, on = _patch_main("run", ret=0, record=narr)
        try:
            code, _, _ = _invoke(["run", RAW, PANEL, "--out-dir", d])
        finally:
            ma.main, mn.main = oa, on
            os.environ.clear()
            os.environ.update(saved)
        if code != 0 or not narr:
            return False
        argv = narr[0]
        return all(flag not in argv for flag in
                   ("--accept-privacy-risk", "--send-alleles", "--keep-input-hash"))
    attempt("S4.gate_passthrough_never_injected", s4_gate_passthrough_never_injected)

    # --- S4.run_refuses_out_flag ----------------------------------------
    def s4_run_refuses_out_flag():
        annot, narr = [], []
        ma, oa = _patch_main("annotate", ret=0, record=annot)
        mn, on = _patch_main("run", ret=0, record=narr)
        try:
            for flag in ("-o", "--out", "--out=x"):
                d = tempfile.mkdtemp()
                code, _, _ = _invoke(["run", RAW, PANEL, flag, "--out-dir", d])
                if code != 2:
                    return False
                if os.listdir(d):
                    return False
        finally:
            ma.main, mn.main = oa, on
        return annot == [] and narr == []
    attempt("S4.run_refuses_out_flag", s4_run_refuses_out_flag)

    # --- S4.run_annotate_failure_stops ----------------------------------
    def s4_run_annotate_failure_stops():
        d = tempfile.mkdtemp()
        missing = os.path.join(d, "missing.txt")
        annot, narr = [], []
        ma, oa = _patch_main("annotate", ret=7, record=annot)
        mn, on = _patch_main("run", ret=0, record=narr)
        try:
            code, _, _ = _invoke(["run", missing, PANEL, "--out-dir", d])
        finally:
            ma.main, mn.main = oa, on
        if code != 7 or narr != []:
            return False
        return all(not os.path.exists(p) for p in _output_paths(d).values())
    attempt("S4.run_annotate_failure_stops", s4_run_annotate_failure_stops)

    # --- S4.run_end_to_end ----------------------------------------------
    def s4_run_end_to_end():
        d = tempfile.mkdtemp()
        with _no_network():
            code, _, _ = _invoke(["run", RAW, PANEL, "--out-dir", d])
        if code != 0:
            return False
        paths = _output_paths(d)
        if not all(os.path.exists(p) for p in paths.values()):
            return False
        return os.path.getsize(paths["report.md"]) > 0
    attempt("S4.run_end_to_end", s4_run_end_to_end)

    # --- S4.run_no_clobber ----------------------------------------------
    def s4_run_no_clobber():
        d = tempfile.mkdtemp()
        with _no_network():
            first, _, _ = _invoke(["run", RAW, PANEL, "--out-dir", d])
        paths = _output_paths(d)
        before = {n: _read_bytes(p) for n, p in paths.items()}
        with _no_network():
            second, _, _ = _invoke(["run", RAW, PANEL, "--out-dir", d])
        after = {n: _read_bytes(p) for n, p in paths.items()}
        return first == 0 and second != 0 and before == after
    attempt("S4.run_no_clobber", s4_run_no_clobber)

    def s4_run_no_clobber_one_file():
        d = tempfile.mkdtemp()
        sentinel = os.path.join(d, "report.ir.json")
        with open(sentinel, "wb") as fh:
            fh.write(b"sentinel")
        with _no_network():
            code, _, _ = _invoke(["run", RAW, PANEL, "--out-dir", d])
        paths = _output_paths(d)
        if code == 0:
            return False
        if _read_bytes(sentinel) != b"sentinel":
            return False
        others = [p for n, p in paths.items() if n != "report.ir.json"]
        return all(not os.path.exists(p) for p in others)
    attempt("S4.run_no_clobber_one_file", s4_run_no_clobber_one_file)

    def s4_run_force_overwrites():
        d = tempfile.mkdtemp()
        with _no_network():
            _invoke(["run", RAW, PANEL, "--out-dir", d])
        report = os.path.join(d, "report.md")
        with open(report, "wb") as fh:
            fh.write(b"SENTINEL")
        with _no_network():
            code, _, _ = _invoke(["run", RAW, PANEL, "--force", "--out-dir", d])
        return code == 0 and _read_bytes(report) != b"SENTINEL" and os.path.getsize(report) > 0
    attempt("S4.run_force_overwrites", s4_run_force_overwrites)

    def s4_run_no_clobber_symlink():
        for name in OUTPUTS:
            for dangling in (True, False):
                for force in (False, True):
                    d = tempfile.mkdtemp()
                    target_dir = tempfile.mkdtemp()
                    target = os.path.join(target_dir, "outside.out")
                    if not dangling:
                        with open(target, "wb") as fh:
                            fh.write(b"SENTINEL")
                    os.symlink(target, os.path.join(d, name))
                    argv = ["run", RAW, PANEL, "--out-dir", d]
                    if force:
                        argv.append("--force")
                    argv.append("--template-only")
                    code, _, err = _invoke(argv)
                    if code != 1 or name not in err:
                        return False
                    if dangling:
                        if os.path.exists(target):
                            return False
                    elif _read_bytes(target) != b"SENTINEL":
                        return False
                    if os.listdir(d) != [name]:
                        return False
        return True
    attempt("S4.run_no_clobber_symlink", s4_run_no_clobber_symlink)

    def s4_run_out_dir_is_file():
        d = tempfile.mkdtemp()
        f = os.path.join(d, "afile")
        with open(f, "wb") as fh:
            fh.write(b"x")
        code, _, err = _invoke(["run", RAW, PANEL, "--out-dir", f, "--template-only"])
        if code != 1 or "afile" not in err or "Traceback" in err:
            return False
        return os.listdir(d) == ["afile"]
    attempt("S4.run_out_dir_is_file", s4_run_out_dir_is_file)

    def s4_run_out_dir_equals_form():
        d = tempfile.mkdtemp()
        with _no_network():
            code, _, _ = _invoke(["run", RAW, PANEL, "--out-dir=" + d, "--template-only"])
        if code != 0:
            return False
        return all(os.path.exists(os.path.join(d, n)) for n in OUTPUTS)
    attempt("S4.run_out_dir_equals_form", s4_run_out_dir_equals_form)

    def s4_run_default_out_dir():
        d = tempfile.mkdtemp()
        old = os.getcwd()
        try:
            os.chdir(d)
            with _no_network():
                code, _, _ = _invoke(["run", RAW, PANEL, "--template-only"])
            out = os.path.join(d, "snp-insights-out")
            return code == 0 and all(os.path.exists(os.path.join(out, n)) for n in OUTPUTS)
        finally:
            os.chdir(old)
    attempt("S4.run_default_out_dir", s4_run_default_out_dir)

    def s4_run_help():
        for argv in (["run", "-h"], ["run", "--help"], ["run", RAW, PANEL, "--help"]):
            annot, narr = [], []
            ma, oa = _patch_main("annotate", ret=0, record=annot)
            mn, on = _patch_main("run", ret=0, record=narr)
            try:
                code, out, _ = _invoke(argv)
            finally:
                ma.main, mn.main = oa, on
            if code != 0 or "--out-dir" not in out or "--force" not in out:
                return False
            if "narrate" not in out or annot != [] or narr != []:
                return False
        return True
    attempt("S4.run_help", s4_run_help)

    def s4_run_private_modes():
        orig = os.umask(0o022)
        try:
            d = tempfile.mkdtemp()
            out = os.path.join(d, "created")
            with _no_network():
                code, _, _ = _invoke(["run", RAW, PANEL, "--out-dir", out,
                                      "--template-only"])
            if code != 0 or (os.stat(out).st_mode & 0o777) != 0o700:
                return False
            for name in OUTPUTS:
                if (os.stat(os.path.join(out, name)).st_mode & 0o777) != 0o600:
                    return False

            d2 = tempfile.mkdtemp()
            pre = os.path.join(d2, "preexisting")
            os.mkdir(pre)
            os.chmod(pre, 0o755)
            with _no_network():
                code2, _, _ = _invoke(["run", RAW, PANEL, "--out-dir", pre,
                                       "--template-only"])
            if code2 != 0 or (os.stat(pre).st_mode & 0o777) != 0o755:
                return False

            d3 = tempfile.mkdtemp()
            ma, oa = _patch_main("annotate", ret=7)
            try:
                code3, _, _ = _invoke(["run", RAW, PANEL, "--out-dir",
                                       os.path.join(d3, "o")])
            finally:
                ma.main = oa
            if code3 != 7 or _get_umask() != 0o022:
                return False

            d4 = tempfile.mkdtemp()
            try:
                cli = _cli()
                with contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()):
                    cli.main(["run", os.path.join(d4, "missing.txt"), PANEL,
                              "--out-dir", os.path.join(d4, "o")])
            except BaseException:  # noqa: BLE001
                pass
            return _get_umask() == 0o022
        finally:
            os.umask(orig)
    attempt("S4.run_private_modes", s4_run_private_modes)

    def s4_tool_integrity_sys_modules():
        import types
        decoy_dir = tempfile.mkdtemp()
        decoy_file = os.path.join(decoy_dir, "run.py")
        with open(decoy_file, "w") as fh:
            fh.write("def main(argv=None):\n    raise AssertionError('decoy ran')\n")
        decoy = types.ModuleType("run")
        decoy.__file__ = decoy_file
        decoy.main = lambda argv=None: (_ for _ in ()).throw(
            AssertionError("decoy ran"))
        saved = sys.modules.get("run")
        sys.modules["run"] = decoy
        try:
            code, _, err = _invoke(["narrate", "findings.json"])
            if code != 1 or "run" not in err or decoy_file not in err:
                return False
            parent = tempfile.mkdtemp()
            out = os.path.join(parent, "created")
            code2, _, err2 = _invoke(["run", RAW, PANEL, "--out-dir", out,
                                      "--template-only"])
            if code2 != 1 or "run" not in err2:
                return False
            if os.path.exists(out) or os.listdir(parent):
                return False
        finally:
            if saved is not None:
                sys.modules["run"] = saved
            else:
                sys.modules.pop("run", None)
        return True
    attempt("S4.tool_integrity_sys_modules", s4_tool_integrity_sys_modules)

    def s4_tool_integrity_path_order():
        decoy_dir = tempfile.mkdtemp()
        with open(os.path.join(decoy_dir, "run.py"), "w") as fh:
            fh.write("raise RuntimeError('decoy run imported')\n")
        saved = sys.modules.pop("run", None)
        sys.path.insert(0, decoy_dir)
        try:
            d = tempfile.mkdtemp()
            with _no_network():
                code, _, _ = _invoke(["run", RAW, PANEL, "--out-dir", d,
                                      "--template-only"])
            if code != 0:
                return False
            return all(os.path.exists(os.path.join(d, n)) for n in OUTPUTS)
        finally:
            try:
                sys.path.remove(decoy_dir)
            except ValueError:
                pass
            sys.modules.pop("run", None)
            if saved is not None:
                sys.modules["run"] = saved
    attempt("S4.tool_integrity_path_order", s4_tool_integrity_path_order)

    def s4_tool_integrity_inner_module():
        import importlib
        import types
        for name in ("llm", "validate_report"):
            importlib.import_module(name)  # cache the real module first
            decoy_dir = tempfile.mkdtemp()
            decoy_file = os.path.join(decoy_dir, name + ".py")
            with open(decoy_file, "w") as fh:
                fh.write("raise AssertionError('decoy %s used')\n" % name)
            decoy = types.ModuleType(name)
            decoy.__file__ = decoy_file
            saved = sys.modules.get(name)
            annot, narr = [], []
            ma, oa = _patch_main("annotate", ret=0, record=annot)
            mn, on = _patch_main("run", ret=0, record=narr)
            sys.modules[name] = decoy
            try:
                code, _, err = _invoke(["narrate", "findings.json"])
                if code != 1 or name not in err or decoy_file not in err:
                    return False
                parent = tempfile.mkdtemp()
                out = os.path.join(parent, "created")
                code2, _, err2 = _invoke(["run", RAW, PANEL, "--out-dir", out,
                                          "--template-only"])
                if code2 != 1 or name not in err2 or os.path.exists(out):
                    return False
                if annot or narr:
                    return False
            finally:
                ma.main, mn.main = oa, on
                if saved is not None:
                    sys.modules[name] = saved
                else:
                    sys.modules.pop(name, None)
        return True
    attempt("S4.tool_integrity_inner_module", s4_tool_integrity_inner_module)

    def s4_within_root_unit():
        cli = _cli()
        base = os.path.realpath(tempfile.mkdtemp())
        root = os.path.join(base, "root")
        os.mkdir(root)
        outside = os.path.join(base, "outside")
        os.mkdir(outside)
        under = os.path.join(root, "tools", "x.py")
        os.makedirs(os.path.dirname(under))
        with open(under, "w"):
            pass
        sibling = os.path.join(base, "root-evil")
        os.mkdir(sibling)
        sibling_file = os.path.join(sibling, "run.py")
        with open(sibling_file, "w"):
            pass
        os.symlink(outside, os.path.join(root, "link"))
        escaped = os.path.join(root, "..", "outside", "x.py")
        saved = cli._ROOT
        cli._ROOT = root
        try:
            return (cli._within_root(under) is True
                    and cli._within_root(root) is True
                    and cli._within_root(sibling_file) is False
                    and cli._within_root(os.path.join(root, "link", "x.py")) is False
                    and cli._within_root(escaped) is False)
        finally:
            cli._ROOT = saved
    attempt("S4.within_root_unit", s4_within_root_unit)

    def s4_run_double_dash():
        d = tempfile.mkdtemp()
        annot, narr = [], []
        ma, oa = _patch_main("annotate", ret=0, record=annot)
        mn, on = _patch_main("run", ret=0, record=narr)
        try:
            code, _, _ = _invoke(["run", "RAW.txt", "PANEL.json", "--out-dir", d,
                                  "--", "--out-dir", "foo", "--model", "m"])
        finally:
            ma.main, mn.main = oa, on
        want_annot = ["RAW.txt", "PANEL.json", "-o", os.path.join(d, "findings.json")]
        want_narr = [os.path.join(d, "findings.json"), "-o",
                     os.path.join(d, "report.md"), "--", "--out-dir", "foo",
                     "--model", "m"]
        if code != 0 or annot != [want_annot] or narr != [want_narr]:
            return False

        d2 = tempfile.mkdtemp()
        annot2, narr2 = [], []
        ma, oa = _patch_main("annotate", ret=0, record=annot2)
        mn, on = _patch_main("run", ret=0, record=narr2)
        try:
            code2, _, _ = _invoke(["run", "RAW.txt", "PANEL.json", "--out-dir", d2,
                                   "--model", "x", "--", "-o", "ignored"])
        finally:
            ma.main, mn.main = oa, on
        want_narr2 = [os.path.join(d2, "findings.json"), "--model", "x",
                      "-o", os.path.join(d2, "report.md"), "--", "-o", "ignored"]
        return code2 == 0 and narr2 == [want_narr2]
    attempt("S4.run_double_dash", s4_run_double_dash)

    # --- S4.cwd_independent ---------------------------------------------
    def s4_cwd_independent():
        d = tempfile.mkdtemp()
        env = dict(os.environ)
        env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run([sys.executable, "-m", "snp_insights", "--version"],
                              cwd=d, capture_output=True, text=True, env=env)
        return proc.returncode == 0 and proc.stdout.strip() == "snp-insights 0.1.0"
    attempt("S4.cwd_independent", s4_cwd_independent)

    # --- S4.build_panel_stdout_mode -------------------------------------
    def s4_build_panel_stdout_mode():
        import build_panel
        common = ["--targets", os.path.join(DATA, "targets.sample.json"),
                  "--clinvar", os.path.join(FIX, "sources", "clinvar.sample.tsv"),
                  "--gnomad", os.path.join(FIX, "sources", "gnomad.sample.vcf")]
        out_path = os.path.join(tempfile.mkdtemp(), "panel.json")
        buf_file = io.StringIO()
        with contextlib.redirect_stdout(buf_file):
            rc_file = build_panel.main(common + ["-o", out_path])
        if rc_file != 0:
            return False
        written = _read_bytes(out_path).decode()
        buf_stdout = io.StringIO()
        with contextlib.redirect_stdout(buf_stdout):
            rc_stdout = build_panel.main(list(common))
        if rc_stdout != 0:
            return False
        if buf_stdout.getvalue() != written:
            return False
        code, cli_out, _ = _invoke(["build-panel"] + common)
        return code == 0 and cli_out == written
    attempt("S4.build_panel_stdout_mode", s4_build_panel_stdout_mode)

    # --- S4.pyproject_consistent ----------------------------------------
    def s4_pyproject_consistent():
        import importlib
        import snp_insights
        path = os.path.join(ROOT, "pyproject.toml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        checks = [
            'name = "snp-insights"',
            'version = "%s"' % snp_insights.__version__,
            'requires-python = ">=3.12"',
            "dependencies = []",
            "GPL-3.0-or-later",
            'snp-insights = "snp_insights.cli:main"',
            "setuptools",
            'packages = ["snp_insights"]',
            'schema = ["jsonschema"]',
        ]
        if not all(c in text for c in checks):
            return False
        mod = importlib.import_module("snp_insights.cli")
        if not callable(getattr(mod, "main", None)):
            return False
        try:
            import tomllib
        except ImportError:
            return True
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        proj = data.get("project", {})
        if proj.get("name") != "snp-insights":
            return False
        if proj.get("version") != snp_insights.__version__:
            return False
        if proj.get("dependencies") != []:
            return False
        target = proj.get("scripts", {}).get("snp-insights", "")
        modname, _, attr = target.partition(":")
        m = importlib.import_module(modname)
        return callable(getattr(m, attr, None))
    attempt("S4.pyproject_consistent", s4_pyproject_consistent)

    # --- S4.no_data_in_package ------------------------------------------
    def s4_no_data_in_package():
        import guard
        root = os.path.join(ROOT, "snp_insights")
        if not os.path.isfile(os.path.join(root, "cli.py")):
            return False
        suffixes = guard.DATA_SUFFIXES
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                if name.endswith(".pyc"):
                    continue
                low = name.lower()
                if any(low.endswith(s) for s in suffixes):
                    return False
        return True
    attempt("S4.no_data_in_package", s4_no_data_in_package)

    # --- R3A characterization: current run/check-raw behavior --------------
    def r3a_run_still_refuses_overwrite():
        d = tempfile.mkdtemp()
        with _no_network():
            first, _, _ = _invoke(["run", RAW, PANEL, "--out-dir", d,
                                   "--template-only"])
        paths = _output_paths(d)
        before = {n: _read_bytes(p) for n, p in paths.items()}
        with _no_network():
            second, _, err = _invoke(["run", RAW, PANEL, "--out-dir", d,
                                      "--template-only"])
        after = {n: _read_bytes(p) for n, p in paths.items()}
        return (first == 0 and second == 1 and before == after
                and "overwrite" in err.lower())
    attempt("R3A.run_still_refuses_overwrite", r3a_run_still_refuses_overwrite)

    def r3a_run_modes_0600_0700():
        orig = os.umask(0o022)
        try:
            d = tempfile.mkdtemp()
            out = os.path.join(d, "created")
            with _no_network():
                code, _, _ = _invoke(["run", RAW, PANEL, "--out-dir", out,
                                      "--template-only"])
            if code != 0 or (os.stat(out).st_mode & 0o777) != 0o700:
                return False
            return all((os.stat(os.path.join(out, n)).st_mode & 0o777) == 0o600
                       for n in OUTPUTS)
        finally:
            os.umask(orig)
    attempt("R3A.run_modes_0600_0700", r3a_run_modes_0600_0700)

    def r3a_check_raw_redacts_by_default():
        import re as _re
        import check_raw
        raw = os.path.join(FIX, "raw.sample.txt")
        redacted, shown = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(redacted):
            rc1 = check_raw.main([raw, "--panel", PANEL, "--no-hash"])
        with contextlib.redirect_stdout(shown):
            rc2 = check_raw.main([raw, "--panel", PANEL, "--no-hash",
                                  "--no-redact"])
        allele = _re.compile(r"\[[ACGTID]/[ACGTID]\]")
        return (rc1 == 0 and rc2 == 0
                and not allele.search(redacted.getvalue())
                and bool(allele.search(shown.getvalue())))
    attempt("R3A.check_raw_redacts_by_default", r3a_check_raw_redacts_by_default)

    # --- R3A: the inside-repo --out-dir warning -------------------------
    def r3a_warn_out_dir_inside_repo():
        cli = _cli()
        d = tempfile.mkdtemp()
        out = os.path.join(d, "out")
        saved = cli._within_root
        cli._within_root = lambda p: True
        try:
            code, _, err = _run_capture(RAW, PANEL, out, ["--template-only"])
        finally:
            cli._within_root = saved
        return code == 0 and "inside the repository" in err.lower()
    attempt("R3A.warn_out_dir_inside_repo", r3a_warn_out_dir_inside_repo)

    def r3a_no_warn_out_dir_outside_repo():
        d = tempfile.mkdtemp()
        out = os.path.join(d, "out")
        code, _, err = _run_capture(RAW, PANEL, out, ["--template-only"])
        return code == 0 and "inside the repository" not in err.lower()
    attempt("R3A.no_warn_out_dir_outside_repo", r3a_no_warn_out_dir_outside_repo)

    def r3a_warn_symlinked_path_into_repo():
        cli = _cli()
        d = tempfile.mkdtemp()
        link = os.path.join(d, "link-into-repo")
        os.symlink(os.path.realpath(cli._ROOT), link)
        code, _, err = _run_capture(RAW, PANEL, link, ["--template-only"])
        return code == 0 and "inside the repository" in err.lower()
    attempt("R3A.warn_symlinked_path_into_repo", r3a_warn_symlinked_path_into_repo)

    def r3a_warning_does_not_echo_file_content():
        cli = _cli()
        d = tempfile.mkdtemp()
        raw = os.path.join(d, "PRIVRAWSENTINEL.txt")
        out = os.path.join(d, "out")
        saved = cli._within_root
        cli._within_root = lambda p: True
        try:
            code, _, err = _run_capture(raw, PANEL, out, ["--template-only"])
        finally:
            cli._within_root = saved
        return (code == 0 and "inside the repository" in err.lower()
                and "PRIVRAWSENTINEL" not in err)
    attempt("R3A.warning_does_not_echo_file_content",
            r3a_warning_does_not_echo_file_content)

    # --- R3A: the owner-checkpoint document -----------------------------
    def r3a_checkpoint_doc_commands_parse():
        import shlex
        cli = _cli()
        commands = _doc_commands()
        if not commands:
            return False
        run_line = None
        for cmd in commands:
            try:
                argv = shlex.split(cmd)
            except ValueError:
                return False
            if not argv:
                return False
            sub = argv[0]
            if sub == "run":
                run_line = cmd
                try:
                    cli._parse_run(argv[1:])
                except cli._UsageError:
                    return False
            elif sub in cli._SUBCOMMAND_MODULES:
                try:
                    module = cli._tool_module(cli._SUBCOMMAND_MODULES[sub])
                    ns = _parse_only(module, argv[1:])
                except SystemExit:
                    return False
                if ns is None:
                    return False
            else:
                return False
        if run_line is None:
            return False
        return "--template-only" in run_line and "--out-dir" in run_line
    attempt("R3A.checkpoint_doc_commands_parse", r3a_checkpoint_doc_commands_parse)

    def r3a_checkpoint_doc_has_no_real_paths():
        import guard
        text = _doc_text()
        for _name, rx in guard.SECRET_PATTERNS:
            if rx.search(text):
                return False
        return "/Users/" not in text and "/home/" not in text
    attempt("R3A.checkpoint_doc_has_no_real_paths",
            r3a_checkpoint_doc_has_no_real_paths)

    def r3a_checkpoint_doc_states_no_sharing_rule():
        low = _doc_text().lower()
        return ("no-sharing rule" in low and "no report text" in low
                and "rsids" in low and "hashes" in low)
    attempt("R3A.checkpoint_doc_states_no_sharing_rule",
            r3a_checkpoint_doc_states_no_sharing_rule)

    def r3a_checkpoint_doc_states_aggregate_adequacy_rule():
        low = _doc_text().lower()
        return "aggregate judgment" in low and "counts only" in low
    attempt("R3A.checkpoint_doc_states_aggregate_adequacy_rule",
            r3a_checkpoint_doc_states_aggregate_adequacy_rule)

    def r3a_checkpoint_doc_names_release_panel():
        return RELEASE_PANEL in _doc_text()
    attempt("R3A.checkpoint_doc_names_release_panel",
            r3a_checkpoint_doc_names_release_panel)

    # --- R3A: owner-checkpoint document accuracy (r71) -------------------
    RELEASE_RAW = os.path.join(FIX, "raw.release.synthetic.txt")
    RELEASE_PANEL_ABS = os.path.join(ROOT, RELEASE_PANEL)

    def _doc_flat():
        return " ".join(_doc_text().lower().split())

    def _release_raw_hash():
        import hashlib
        with open(RELEASE_RAW, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    def _synthetic_release_run(out_dir):
        env = dict(os.environ)
        env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, "-B", "-m", "snp_insights", "run", RELEASE_RAW,
             RELEASE_PANEL_ABS, "--out-dir", out_dir, "--template-only"],
            cwd=out_dir, capture_output=True, text=True, env=env)

    def r3a_checkpoint_doc_hash_statement():
        flat = _doc_flat()
        if ("always contains the raw-file sha-256 in `provenance.input_hash`"
                not in flat):
            return False
        if "`--keep-input-hash` does not remove it from this file" not in flat:
            return False
        if "--no-hash" not in _doc_text():
            return False
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out")
            proc = _synthetic_release_run(out)
            if proc.returncode != 0:
                return False
            with open(os.path.join(out, "findings.json"), encoding="utf-8") as fh:
                findings = fh.read()
        return _release_raw_hash() in findings
    attempt("R3A.checkpoint_doc_hash_statement", r3a_checkpoint_doc_hash_statement)

    def r3a_checkpoint_doc_output_file_descriptions():
        flat = _doc_flat()
        raw_hash = _release_raw_hash()
        raw_path = os.path.realpath(RELEASE_RAW)
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out")
            proc = _synthetic_release_run(out)
            if proc.returncode != 0:
                return False
            texts = {}
            for name in OUTPUTS:
                with open(os.path.join(out, name), encoding="utf-8") as fh:
                    texts[name] = fh.read()
        if raw_hash not in texts["findings.json"]:
            return False
        if raw_hash not in texts["report.md"]:
            return False
        if raw_hash not in texts["report.run.json"]:
            return False
        if raw_hash in texts["report.ir.json"]:
            return False
        if '"allele1"' not in texts["findings.json"]:
            return False
        for name in ("report.md", "report.ir.json", "report.run.json"):
            if '"allele1"' in texts[name]:
                return False
        for name in OUTPUTS:
            if raw_path in texts[name] or RELEASE_RAW in texts[name]:
                return False
        required = (
            "always contains the raw-file sha-256 in `provenance.input_hash`",
            "does not remove it from this file",
            "`report.md` also includes the input hash",
            "`report.run.json` records it",
            "`report.ir.json` contains the findings-file hash",
            "all four files contain private health-relevant data",
        )
        return all(phrase in flat for phrase in required)
    attempt("R3A.checkpoint_doc_output_file_descriptions",
            r3a_checkpoint_doc_output_file_descriptions)

    def r3a_checkpoint_doc_adequacy_no_trait_cutoff():
        flat = _doc_flat()
        if "measured trait entries" in flat:
            return False
        if "aggregate judgment" not in flat or "counts only" not in flat:
            return False
        return "trait-count cutoff cannot distinguish" in flat
    attempt("R3A.checkpoint_doc_adequacy_no_trait_cutoff",
            r3a_checkpoint_doc_adequacy_no_trait_cutoff)

    def r3a_checkpoint_doc_no_sharing_one_line():
        flat = _doc_flat()
        if "one line and nothing more" not in flat:
            return False
        if "do not share the reproduction" not in flat:
            return False
        if "not private data" not in flat or "never required" not in flat:
            return False
        for bad in ("plus the complete report",
                    "share only that synthetic reproduction"):
            if bad in flat:
                return False
        return True
    attempt("R3A.checkpoint_doc_no_sharing_one_line",
            r3a_checkpoint_doc_no_sharing_one_line)


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
