# Local corrected release candidate `4a326236b` — targeted checks (NOT a full CI; not published)

- Built in a fresh tree from published `6ca0ce2a8`; ported ONLY the two `Resolver` hunks of `34e5bc85a` (`git apply`
  of those hunks, unchanged): `self._assigns = {}` and the per-function assignment-list cache in `Resolver.enter`.
  Whole-census memoization (third hunk) and integ's later scanner changes NOT ported. Detection rules, baseline,
  pytest limits (180 s) untouched. Delta from `6ca0ce2a8`: 1 path (+16/−6). Full composition vs `main`: 24 paths
  (`RELEASE_MANIFEST_v4.txt`).
- Targeted file on the candidate (`SPA_ENV=ci`, timeout 180 s kept): **45 passed, 4 failed in 124 s** (wall 135.8 s);
  heaviest tests ≈ 9.6–9.9 s each (base CI: 140–165 s). The 4 failures are EXACTLY the four IDs already failed on the base
  CI 40328594274 (`test_real_tree_matches_the_frozen_baseline`, `test_an_intact_baseline_passes`,
  `test_removing_an_unresolved_identity_reduces_the_debt`, `test_the_unchanged_census_is_green`); the 9 new IDs of
  the release CI pass here. Expectations not changed.
- Exact parent `37e06e185`: ONE baseline verdict (original scanner, single traversal, timeout plugin off for the
  measurement only): «вырос на 28», 101 s. The candidate's 28 subjects are the IDENTICAL set (28/28).
- Report equivalence: reused ARB's control (`arb_provenance_timing_20261027.json`): same release tree, original
  100.725 s vs Resolver-only 9.365 s, 85 rows, byte-identical sorted JSON, sha256 14c8ae4c…f7df8.
- Resolver control: one function entered twice with different inherited values → only the assignment list
  (`target`, `other`) is cached once; resolved values follow the current input (`refs/remotes/origin/main` vs
  `refs/heads/feature`).
- Ratchets on the candidate: unused imports, LLM lint, absent observation, frozen date — 92 passed; pyflakes clean.
- Not done (by instruction): publication of `4a326236b`, any full CI. A whole-system verdict remains unestablished; the
  release-CI comparison base stays approximate (`d0c3c59ed`, one commit before the exact parent).
