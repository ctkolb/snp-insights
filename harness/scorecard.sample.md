# Narrator scorecard

findings: `fixtures/findings.sample.json` hash `ca883b30dda9d195...`

| candidate | parse | refusal | valid | violations | by rule | missing | note |
|---|---|---|---|---|---|---|---|
| narrator_good | ok | no | PASS | 0 |  | 0 |  |
| narrator_sloppy | ok | no | FAIL | 15 | {"hash": 1, "R1": 1, "R3": 1, "R4": 3, "R2": 1, "R7": 7, "R5": 1} | 6 |  |
| narrator_refusal | FAIL | yes | FAIL | 0 |  | 0 | looks like a refusal / no JSON |
| live_candidate_example | - | - | - | - |  | - | live: skipped (pass --live) |
