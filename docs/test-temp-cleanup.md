# Test and build-loop temporary directories

Test runs and build-loop tools write scratch repositories, copies and fixtures
to the temp directory. This page describes how those runs keep that space clean,
how to find anything a run left behind, and how leftovers are removed.

## The owned run root

`tests/test_pipeline.py`, `tests/test_tmp_hygiene.py` and
`scripts/loop_mutations.py` call `runtmp.activate()` from `scripts/runtmp.py`
when they start. It creates one directory, `snp-insights-run-<8 characters>`,
in the temp directory, with a marker file `.snp-insights-run.json` (schema,
tool, process id, user id, UTC creation time, random token). It then points
`TMPDIR` and Python's `tempfile` module at that directory, so every temporary
file and directory the run creates, including those of child processes that
inherit the environment, lands inside it.

The root is removed when the process ends: on a normal exit, after an
exception, on Ctrl-C, and on SIGTERM and SIGHUP. Removal is guarded. The
helper removes only the directory it created, checked by name, location,
device and inode, owner, and a marker that still names the same process, user
and token. Only the creating process removes it. The removal is bound to the
directory that passed those checks: it works through directory handles that
never follow a symbolic link, so a directory swapped in at the same path is
left alone, and it changes permissions only on directories inside the tree
being removed. It never changes the parent: if the parent is not writable,
the root stays in place. If anything does not match, the directory is left in
place and the run prints `runtmp: refusing ...`.

SIGKILL and `os._exit` cannot be caught. Each such run leaves exactly one
`snp-insights-run-*` directory behind.

The remaining test modules adopt the run root in a later change; until then,
running one of them on its own (outside `tests/test_pipeline.py`) can still
leave entries in the temp directory.

## Finding leftovers: the sweep

```bash
python -B scripts/tmp_sweep.py
python -B scripts/tmp_sweep.py --parent <dir> --json
```

The sweep reads only the top level of the temp directory (or `--parent`). It
never changes or removes anything. It classifies every `snp-insights-run-*`
entry:

| State | Meaning | Eligible for removal |
|---|---|---|
| `live` | Valid marker; the process is still running, or cannot be checked | No |
| `stale` | Valid marker; the process has ended | Yes, through the procedure below |
| `invalid` | Name matches, but it is a symbolic link, a plain file, another user's directory, or the marker is missing or malformed | No; inspect by hand |

A process id can be reused by an unrelated process, so a stale root may show
as `live`. That error is in the safe direction: the root is never listed as
eligible while its id is in use.

Entries left by earlier test runs (other `snp-insights-*`, `r2e-*` and
`loop-mut-*` names) are counted on one line and never listed as eligible.
They are owner-managed. `--show-legacy` prints their names without changing
anything. `--fail-on-stale` exits 3 when any stale root is listed.

## Measuring leaks: the audit

```bash
mkdir <empty dir>
python -B scripts/tmp_audit.py run --parent <empty dir> -- python3 -B tests/test_pipeline.py
```

The audit runs the command with `TMPDIR` set to the given parent and compares
the parent's top level before and after. It prints one `new: NAME` line per
new entry and a final `AUDIT {...}` summary, and exits 1 when anything new
remains. `--interrupt-after SECONDS --signal KILL|TERM|INT|HUP` checks
interrupted runs, and `--max-new 1` accepts the single root a SIGKILL leaves.
Use a dedicated empty directory, never the shared system temp directory. A
`--json` report path inside that directory is rejected (exit 64), because a
report written there would not be counted.

Run on its own, `tests/test_tmp_hygiene.py` also measures
`tests/test_guard.py`: entries left behind (0 expected), peak live bytes, and
how many times the suite copies a tracked file into a full fixture. That copy
count is the metric: it fell from 41 to 1 when the full fixtures started from
one shared template, and the check fails above 14. The number of fixture
directories the suite builds is recorded only; it did not change.

## Known limits

- A `stale` root means only that the process that created it has ended. A
  child process it started can outlive it (for example after SIGKILL) and keep
  writing into the root. Before removing any root, confirm that no process
  still uses it, for example by listing open files under it (`lsof +D PATH`).
- Markers are not authenticated. Any process running as you can write a
  directory with a matching name and a made-up marker, and the sweep will
  list it like a real one. The sweep only lists; any removal needs the owner's
  explicit approval of exact names, as described below.
- Removal checks each directory again right after opening it, but another
  process running as you can still rename a directory in the short window
  between that check and an individual removal; this remaining race is
  accepted and not closed.

## Removing leftovers (manual, owner only)

Nothing in this repository deletes leftovers, and agents never remove them.
The owner follows these steps:

1. Run the sweep and save its output as the dry-run list.
2. Read the exact paths listed as `stale`, and confirm that no process still
   uses any of them (see Known limits).
3. Approve, in writing, the exact names to remove. An approval covers only
   those names and that run of the sweep.
4. Remove exactly those paths yourself, or approve one exact command that
   names each path.
5. Run the sweep again and confirm that the approved names are gone and
   nothing else changed.

Never remove a `live` or `invalid` entry, an entry that is not listed, or
anything matched by a wildcard. Legacy entries from earlier runs follow the
same rule: the owner decides on exact names.
