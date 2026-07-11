# SPA / earn-defi — one-pager for a track-record auditor / accountant

*Hand this to an auditor to arrange attestation of the paper track when it completes (~2026-07-21). Focus:
what to attest, the exact numbers, and how to reproduce them independently. Reproduction detail lives in
`docs/DD_PACK.md` + `scripts/verify_spa.py` — this page is the engagement summary, not a repeat of them.*

---

## What we're asking you to attest
A **paper-trading track record** (virtual capital, **not** client money): that the reported returns,
drawdowns and evidenced days are **real, unaltered, and reproducible from the underlying data** — so we can
truthfully tell prospects "independently verified track," not "trust us."

## The subject matter (exact, as-built)
- **Instrument:** a deterministic daily paper-trading cycle over whitelisted DeFi protocols (virtual
  $100,000 USDC). No real capital, no client funds.
- **Evidenced window:** anchor **2026-06-22**, target **30 evidenced days ≈ 2026-07-21**. Currently
  **20 / 30** evidenced days.
- **Equity:** $100,150.66 (anchor) → **$100,379.50** (latest evidenced). Drawdown to date < 0.3%.
- **Every number carries an evidence level (L0–L6);** paper is never presented as realized; the
  tail/drawdown is always shown next to any return. No fabricated APY/positions.

## How you reproduce it independently (no trust in us)
- A **standalone, zero-dependency verifier** (`scripts/verify_spa.py`) re-derives the decision log +
  equity track from the raw published files and checks a **hash-chain** (tamper-evident); it can
  **re-derive each decision from its own published numbers** (`--replay`) and **replay a frozen,
  checksummed data snapshot fully offline** (`--offline`). Any altered byte fails closed.
- A one-command **data-room** (`scripts/build_dataroom.py`) bundles the verifier + the raw proof files +
  the reproduce commands. Full detail: `docs/DD_PACK.md`.

## Suggested attestation scope (you refine)
1. The equity curve + drawdown for the evidenced window tie to the underlying daily records.
2. The evidenced-day count is honest (no backfilled / demo days counted; anchor 2026-06-22 onward only).
3. The verifier reproduces the published track head from the raw files (tamper-evidence holds).
4. Clear statement that this is a **paper/simulated** track (no client capital), not audited financial
   statements of a fund.

## Questions for you
1. What **engagement type** fits a paper/simulated track attestation in your practice (agreed-upon
   procedures? an ISAE-3000-style report? a simpler verification letter)?
2. What do you need from us to attest, and what will your report be able to **say** (and not say)?
3. **Timing:** we hit 30 evidenced days ≈ 2026-07-21 — can we schedule the engagement to start then?
4. If we later run **real** capital, what changes for a future audited (non-paper) track?
5. Any wording constraints on how we may present your attestation to prospects?

## Honest framing (so scope is clear up front)
Paper only, no client money today; reproducibility is built-in (verifier + hash-chain + offline snapshot);
we want an attestation of **what the data shows**, described accurately as a simulated track — nothing more.

*Companion: `docs/DD_PACK.md` (reproduce recipe), `scripts/verify_spa.py` (`--replay` / `--offline`),
`docs/FUNDABILITY.md` (honest fundability sheet). Legal counterpart: `docs/LAWYER_ONE_PAGER.md`.*
