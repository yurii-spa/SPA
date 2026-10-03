# ADR-548 · Three paper portfolios — owner gate applied, epic closed

- **Status:** ACCEPTED (owner decision 2026-10-03, interactive session)
- **Date:** 2026-10-03
- **Decides:** the consolidated package `docs/owner_packages/2026-10-02-three-portfolios-closeout.md`
  (card `owner-decision-tri-bumazhnyh-portfelya-rabotayut-ostalo`, now `owner-done`)
- **Related:** ADR-533 (three paper portfolios), ADR-537 (status colour is not a risk grade),
  ADR-532 (tier census; packages A–D still with the owner), ADR-146 (agent may set owner-done with evidence)

## Decision

The owner approved all ten items, with clarifications. They were applied in one commit:

| # | Item | Applied as |
|---|---|---|
| 1 | Aggressive is described by its current mechanism | Concentrated stablecoin lending plus a simulated sUSDe/PYUSD loop on Morpho Blue; paper only; real capital refused. Aggressive Lab is linked only as the *earlier research*. The wording is «no reportable result yet», never «no result». The evidence level stays **L2** under `docs/37`: the current version has days, not an L3 paper period, and was not raised for the interface |
| 2 | Meta descriptions | `/packages`, `/strategies`, the three strategy pages and `/faq` describe three paper portfolios with different mechanics; research targets are not results |
| 3 | FAQ fund wording | «minimum investment» → «Can I invest today?»; «SPA Family Fund» header replaced; «How do I apply? … KYC … investor agreement» → «Is there an application process? No»; «When it opens, terms will be published» → only after a separate go-live decision and legal review; «How are my funds protected?» → «How is the book protected?»; the "Entry through conversation — no public minimums" answer on the three strategy pages → «No deposits are accepted» |
| 4 | Fees | One text on the three strategy pages, `/faq` and `/fees`. The illustrative future fee model on `/fees` (management fee, HWM, «No Lock-Up», worked example; origin `28c6cb594`, 2026-06-21) is removed: no future fee model is published now |
| 5 | Early access | «30-day paper report — when the current portfolio version reaches 30 valid days»; not an investment offer, no yield promise, no go-live promise |
| 6 | 6a | 6/12/20 % appear only as labelled research targets, nav included (the RU nav printed untranslated «up to»). The «≤3/≤10/≤25 % drawdown» text left the bands. The advisory loss budget the defi_engine measures moved to its own field `loss_budget_pct`, which is not printed as a band. The parity test now reads it there and also asserts that the band carries no budget. Unused `strategy_config.target_apy` (6/5/15, no reader) was deleted |
| 7 | Stop reference | Balanced −8 % and Aggressive −25 % are measured from the **current experiment's** peak (`strategy_mandates.stop_reference`). The reference is derived from the book file itself: the experiment's recorded initial equity, its own rows, and the equity now. The legacy `peak_equity` is still written as before and never rewritten. The version boundary is recorded in `state.stop_reference`. No active experiment ⇒ the stricter legacy peak, named. Thresholds unchanged. Public text: «from the current version's peak … a stop trigger, not a maximum-loss guarantee» |
| 8 | 8b | Hero = three paper portfolios. Conservative's measured result comes from live data; Balanced/Aggressive «accumulating»; no real capital; no 20 % in the hero |
| 9 | Calculator kept | Scenario block separate and labelled; rate from `tier_bands` (no 0.20); its assumptions now say «no reportable result yet» |
| 10 | Tier labels | Labels come from the canonical registry only. A protocol whose **identity** is unresolved (`susde` ↔ `ethena_susde`, ADR-532 package A) shows «tier unresolved» / «тир не определён» instead of a tier. A copy disagreeing with the canonical registry does not change what is shown (that is the tier census's finding). The RU tail reads «нехеджированная направленная книга». The ~50 % historical tail is named as the earlier Aggressive Lab book, separate from the current loop and from the stop |

## Found while applying (fixed, same commit)

- **The owner gate could not honour this card's own approval.** `_parse_approves` received the YAML
  flow form `[a, b]` as one string, so the first and last entries were «[a» and «b]» and matched
  nothing. Under an `owner-done` card, `index.astro` and `tier_bands.json` stayed GATED. The brackets
  are now stripped, with two new parametrised cases; reverse control: 2 failed without the fix.
- `/strategies` hero said «Same deterministic risk engine. Same non-overridable gates», which
  contradicts the strategy pages: Balanced/Aggressive are outside RiskPolicy. It is rewritten.
- `/snapshot` growth step: «Early-access to get in the day it validates» became a description of the
  current mechanism.

## Tests changed on purpose (invariant #16)

- `test_package_status.py::test_composition_is_measured_from_registry_labels_of_held_positions`:
  the `susde → T3` assertion became `susde → unresolved` (item 10). The T3 label path is now pinned on
  `extra_finance_base`, an undisputed T3 key.
- `test_defi_engine.py::test_runtime_budget_mirror_equals_the_published_page`: parity moved from the
  band text to `loss_budget_pct` (item 6a), plus a new assertion that no budget is back in the band.
- `test_paper_cycles.py::test_book_kill_unwinds_an_open_loop`: the deep drawdown is simulated on the
  current experiment's peak (item 7). Inflating only the legacy peak no longer moves the stop, by
  design. The assertion is unchanged.

## Not changed

- RiskPolicy v1.0 and its thresholds; the Conservative two-tier kill switch; the sleeve stop
  thresholds; real capital = 0.
- ADR-532 packages A (tier labels), B (Conservative 3 % budget binding), C (RTMR) and D, which wait
  for their own decisions.

## Delivery evidence (2026-10-03)

| Step | Evidence |
|---|---|
| Commits | `a2e210f7`: 31 files, all ten items. `8864def1`: three leftovers found by the live check — the /faq KYC contact block, «identity verification before first deposit» on two strategy pages, and the /packages evidence chip overflowing 390 px |
| Gate | `safe_site_push.py` with `Owner-Approved: owner-decision-tri-bumazhnyh-portfelya-rabotayut-ostalo` (card owner-done, ADR-146): CLEAN |
| Production | code-sync `a2e210f75c66` at 12:07:47Z; apiserver restarted; `deployment_acceptance` ok; the public API serves the new read model (Balanced «tier unresolved: susde») |
| Site | CDP after JS, 10 pages × 375/390/430/1280 × EN/RU: **80/80**, no overflow or clipping, no forbidden pattern |
| Stops | reference reproduced from the book files: Balanced −0.108 % from 99 568.80 (legacy 100 496.02 kept), Aggressive −0.123 % from 100 260.76 (legacy 100 607.21 kept); thresholds unchanged |
| Tests | reverse controls 5 / 1 / 2 red without the fixes; 131 affected files: 7 932 passed, 0 failed; follow-up 128 passed; landing build 120 pages rc 0 |

## Known remaining debts (named, not hidden)

- «Who it's for» audience blurbs on the strategy pages (e.g. «Family offices and individual allocators…») remain. They were not in the approved package, read as product positioning, and are left for a future wording pass, not changed silently.
- The `invest@earn-defi.com` contact address is kept: changing a mail address can break routing.
- ADR-532 packages A–D (tier labels incl. the `susde`/`ethena_susde` identity, Conservative 3 % budget binding, RTMR, delta-neutral check) are with the owner.

