# Security policy

## Reporting a vulnerability

Please report security or privacy issues **privately**, not in a public issue.
Use GitHub's private vulnerability reporting (Security → Report a vulnerability)
on this repository, or contact the maintainer through their GitHub profile.

Include steps to reproduce and the affected file or command. You should get an
initial response within about a week; this is a volunteer personal project.

## Scope and priorities

The most important thing to protect is **genetic data**. In-scope concerns:

- Any path that could send the raw DNA file, `findings.json`, or a derived
  `panel.*.json` off the machine without the explicit online opt-in flag.
- Any way a secret, credential, home path, or owner-identifying term could reach
  the repository or its history past `scripts/guard.py` and the CI checks.
- Parser or narrator behavior on untrusted input (a crafted raw file, a hostile
  reference response, or model output) that leads to code execution or data
  exfiltration.

Not in scope: interpreting your genetics, and the inherent disclosure of the
online narration path (it is documented and opt-in).

## What this project never does

- It never auto-uploads your raw file.
- It never fetches reference data as part of Stage 2 (annotation is offline).
- It never commits real data or credentials; the guard and CI enforce this.
