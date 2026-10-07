# ADR-641 · Oracle consumes all return sources; paper Portfolio of Sources; the 10–15 % research question (CAPITAL-SOURCES-01, wave C)

- **Status:** Accepted (paper only, recommendation only; real capital $0, no execution)
- **Date:** 2026-10-07
- **Author:** CAPITAL-SOURCES-01 session (owner directive «Trading Alpha Sleeve + Portfolio of Return Sources»)
- **Related:** ADR-554 (Oracle, its policy and immutable ledger), ADR-640 (Capital Sources contract, Trading Alpha
  sleeve, temporal admission), ADR-590 §4 (no annualised figure under 30 days), ADR-034/048 (−10 % HARD_KILL)

## Context

ADR-640 put every return source (DeFi books, Trading Alpha, market-neutral/basis, cash) on one contract. The
Oracle policy (ADR-554) still read only the DeFi sleeves and never saw Trading Alpha as a source; there was no
paper portfolio that combines sources and reports contribution, risk contribution, correlation and diversification;
and the owner's research question «can a diversified set of evidenced sources reach ≈10–15 % a year net?» had no
deterministic, typed answer.

## Decision

1. **No Oracle v2.** The multi-source logic is a pure module `spa_core/investment_cio/sources_portfolio.py` called
   from the existing `policy.recommend`. Its output is one additive field of the recommendation,
   `capital_sources_view` (schema `capital-sources-view/1`, `policy_version: multi-source-v1`). It is inside the
   recommendation hash, it never changes `recommended_weights`, `executes` is always False.
2. **Inputs are snapshotted.** `run.py` adds `sleeves_doc["capital_sources"]` (Trading Alpha sleeve from
   `evidence.db`, the Capital Sources registry, each source's daily return series, a BACKTEST view of the sleeve
   members) before the snapshot is saved — the view is rebuilt byte-for-byte from the snapshot. A failure there is
   recorded (`state: REFUSED` + reason); the Oracle's own recommendation still runs.
3. **Multi-source assessment (§11).** Per source: maturity from evidence DAYS (observation counts are not days),
   **NET return only** (a measured cumulative net, or the measured annualised REALIZED rate of a book that is net of
   its modelled costs; a figure labelled gross, or net above gross, is refused), drawdown measured, not STALE, no
   unknown cost component, the source's own blockers. A qualifying source gets a **cap**, not a weight:
   30–89 days → 20 %, ≥ 90 days → 50 % (ADR-554 caps, reused); **directional trading and leveraged loops ≤ 10 %**
   (new, uncalibrated v1 parameter). The statement reads «would qualify for up to X % PAPER allocation under current
   evidence» or «does not qualify: <blockers>». A source the contract keeps `allocatable=False` (Trading Alpha) stays
   out of the main weights even when it qualifies — moving it in is a separate ADR.
4. **Paper Portfolio of Sources (§10).** The weights the policy uses TODAY are the Oracle's own (its recommendation,
   else its `EVIDENCE_ONLY` alternative) and are validated against today's assessment — a non-zero weight on a source
   that does not qualify, or above its cap, is **refused**, never clipped. The NAV PATH is **causal**: on each past
   date the weight is the one decided then — the Oracle ledger's own recommendation (or EVIDENCE_ONLY alternative)
   where the ledger covers the date, else the cap ladder by EVIDENCED days on that date (0 below 30, 20 % to 89, 50 %
   from 90, gaps not counted), never above today's weight — and a weight decided on day D earns day D+1's return.
   The snapshot stores only the ledger's weight CHANGES inside the window. Applying today's weight from day 1 would be lookahead (found by the
   independent review). Reported: NAV, weights + `weight_path` (each change with its basis), cash, contribution, NET
   return, max drawdown; annualised return, volatility, Sharpe, Sortino only ≥ 30 CALENDAR days (annualisation on the
   calendar span, missing dates counted); risk contribution; diversification ratio/credit — 0 when the sources move
   as one, UNDEFINED on accrual-like series (daily σ < 1e-4 or < 10 distinct returns); correlation matrix with
   NOT_ENOUGH_HISTORY under 30 overlapping days. Volatility/Sharpe are on accrual returns (0 % mark-to-market) and
   carry that caveat.
5. **§12 frontier.** REALIZED_PAPER points (static-weight what-ifs of qualifying sources, cash ≥ 5 %, each flagged
   `within_policy_caps`; only non-dominated points are stored; more than 4 evidenced sources ⇒ the 10^k grid is not run
   and the answer is UNKNOWN), MIXED hypothetical points (REALIZED DeFi at most its cap + BACKTEST trading, labelled
   never-evidence/never-allocation, flagged against the 10 % trading cap, with a long-run ρ=1 drawdown bound from the
   members' OOS statistics) and the NOT_MEASURED sources. The **verdict reads only REALIZED_PAPER points within
   policy caps and with drawdown no worse than −10 %**; hypothetical hits are mentioned only if within caps. It may
   answer NO or UNKNOWN. No leverage or tail is ever added to reach a number.
6. **Paper boundary.** A registry claiming real capital ≠ 0, execution, a non-PAPER mode or a live flag on any source
   is refused as a whole (`state: REFUSED`), never partially used.
7. **Clock-free record.** The view's `as_of` is the recommendation DATE (not the run time), so the same evidence gives
   the same `recommendation_id` at any hour. A pruned/unreadable previous snapshot is recorded
   (`previous_sleeve_check: NOT_MEASURED`), never a silent skip of the reset/reseed comparison.

## Consequences (measured on a copy of production data, 2026-10-07)

- Conservative qualifies (106 days, NET 4.89 % annualised realized) with a 50 % cap; Balanced/Aggressive (6 days),
  Trading Alpha (6.75 days, 8 unknown cost components, no ROBUST member) and Market-Neutral/Basis (no evidence,
  inputs frozen) do not.
- The CAUSAL paper portfolio over 2026-06-22…2026-10-07 (108 calendar days, 106 observations, 2 missing dates):
  Conservative 0 % until 07-22, 20 % from 07-23, 50 % from 09-22 (from 10-05 per the Oracle ledger) — NET +0.26 %,
  0.87 % annualised, max drawdown −0.008 %; one risk source ⇒ diversification credit 0. (The first version applied
  today's 50 % from day 1 and reported +0.70 % / 2.45 % — lookahead, corrected.)
- Frontier verdict: **NO** — evidenced static weights reach at most 2.40 % annualised NET within caps (Conservative
  50 %, rest cash), 4.36 % outside caps (Conservative 90 %, 10 % cash). Hypothetical MIXED points within caps (trading
  ≤ 10 %) reach 5.6–8.8 % on the window with a long-run drawdown bound down to −3.6 %; above the cap they pass 10 %,
  but those are selection-biased backtest figures with bounds down to −18 % — not evidence.
- Every pair correlation is NOT_ENOUGH_HISTORY (≤ 7 overlapping days); the MIXED backtest estimate Trading-vs-
  Conservative is ≈ 0.00 (104 days, labelled never-allocation).
- Director OS / Telegram read this view through `investment_cio.read.capital_sources()` — one read, no duplicate
  computation (wave D).
