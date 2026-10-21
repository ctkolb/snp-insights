# Branch protection for `main`

These settings are the enforcement layer: hooks and CI can be skipped, but a
protected `main` cannot. Rulesets and classic branch protection are **free on
all plans**, including private personal repos. No GHAS/Enterprise feature is
used.

Run the commands below yourself — the agent never changes remote settings. They
use the owner's authenticated `gh` CLI.

## Required checks

All four CI check-run names must be required — not just tests:

- `test (py3.9)`
- `test (py3.12)`
- `privacy guard`
- `secret scan`

## Option A — ruleset (recommended)

Save this as `/tmp/protect-main.json`:

```json
{
  "name": "protect-main",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["refs/heads/main"], "exclude": [] } },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      } },
    { "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          { "context": "test (py3.9)" },
          { "context": "test (py3.12)" },
          { "context": "privacy guard" },
          { "context": "secret scan" }
        ]
      } }
  ]
}
```

Apply it:

```bash
gh api -X POST repos/ctkolb/snp-insights/rulesets --input /tmp/protect-main.json
```

`required_approving_review_count: 0` is correct for a solo maintainer: a PR is
required, but no second human is. `strict_required_status_checks_policy: true`
means the branch must be up to date with `main` before merging.

## Option B — classic branch protection (fallback)

```bash
gh api -X PUT repos/ctkolb/snp-insights/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["test (py3.9)", "test (py3.12)", "privacy guard", "secret scan"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": { "required_approving_review_count": 0 },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

## Verify

```bash
# ruleset:
gh api repos/ctkolb/snp-insights/rulesets \
  --jq '.[] | {name, enforcement, includes: .conditions.ref_name.include}'

# classic:
gh api repos/ctkolb/snp-insights/branches/main/protection \
  --jq '{strict: .required_status_checks.strict,
         checks: .required_status_checks.contexts,
         reviews: .required_pull_request_reviews.required_approving_review_count,
         force: .allow_force_pushes.enabled,
         deletions: .allow_deletions.enabled}'
```

## Prove it actually blocks a merge

Never test guard changes directly on `main`. On a throwaway branch:

```bash
git switch -c protect-selftest
printf 'this will fail the tests\n' >> README.md   # or break a guard
git commit -am "selftest: intentionally failing check"
git push -u origin protect-selftest
gh pr create --base main --head protect-selftest --fill
# Confirm GitHub reports the failing required check and disables "Merge".
# Then close the PR and delete the branch; do not merge.
gh pr close protect-selftest --delete-branch
```

Expected: the **Merge** button is blocked until every required check is green.
If it is not, the check name does not match a CI job — fix the names before
relying on this.
