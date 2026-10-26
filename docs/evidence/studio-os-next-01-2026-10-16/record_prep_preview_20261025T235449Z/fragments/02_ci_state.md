# Current CI state of `integ/studio-os-next-01-stab` (recorded 2026-10-26 from the CI evidence files of this branch)

| candidate | CI run | total | passed | failed | what failed |
|---|---|---|---|---|---|
| `a5724a102` (immediate predecessor) | 40234524248 | 135870 | 135148 | 3 | 2 known §49 producer-tick tests + 1 NEW timeout `test_list_identity_census…candidate_outside_is_a_finding` |
| `5499ceca4` (before the new timeout) | 40216933079 | 135848 | 135127 | 2 | 2 known §49 producer-tick tests |

- Comparison bases for the next candidate: **a5724a102 / 40234524248** and **5499ceca4 / 40216933079** (so the new timeout cannot disappear by a change of base).
- `62fe88b48` is the HISTORICAL base of this branch (run 39832458873). It is NOT the next comparison base.
- CI is RED; no green CI and no §49 NO_REGRESSION is claimed.
- The timeout fix in this package (`6879ce431`, test fixture only) is not yet measured by a full CI.
