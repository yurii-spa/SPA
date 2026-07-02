# The honest 2026 stablecoin-yield landscape — whole-map synthesis

> Session-synthesis of **37 evaluated decisions** (see [`decision_index.md`](decision_index.md) for the
> per-candidate audit trail, [`underwriting_rubric.md`](underwriting_rubric.md) for the method, and
> [`non_ethena_ladder.md`](non_ethena_ladder.md) for the assembled book). Canonical mandate:
> [`adr/ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md). This doc is the human-readable map a
> DD analyst / AI tool reads to get the whole honest picture in one place. Real sourced data, 2026-07-03.

## The one principle
Judge **spread over the live RWA floor** (~3.4%, dynamic from `data/rwa_feed.py`), not absolute APY. Every
basis point of spread must be explained by a specific, **measurable, accepted** risk. Spread that is only
compensation for an **unbounded tail** (funding-flip, leverage, uninsured credit, governance-discretion) —
or is **token-emissions subsidy** — is **REFUSED**. Refusals are positive results: the edge is being the
one who honestly measures/underwrites the risk others misprice.

## The floor is a floor (definitively — the majors add no spread)
Every gov-T-bill tokenized product **IS** the floor, not a spread over it: **BlackRock BUIDL**, **Franklin
BENJI/FOBXX** (3.56%, cleanest print), **Ondo OUSG** (3.49%), **JPM MONY/JLTXX**, **Circle USYC**,
**Superstate USTB**. They earn the same SOFR/T-bill rate net of fee; the 2026 multi-chain / share-class /
new-entrant wave is **distribution & infrastructure, not yield**. Use them as the **cash-floor realizer**
(USYC/OUSG best for on-chain atomic redemption) — never as a spread source. `gov_tbill_at_floor`

## Where a real, BOUNDED non-Ethena spread exists (the ADVANCE rungs)
| Rung | Yield | Spread | Depth | Why bounded |
|---|---|---|---|---|
| **Fluid** plain USDC/USDT supply | ~4.3-5.5% | +0.9-2.1pp | **DEEP $1.01B** | organic lending, emissions ending → self-standing |
| **Morpho Steakhouse** curated vault | ~4.5-6.5% | +1.1-3.1pp | deep (Blue $6.8B) | overcollat curated over IMMUTABLE Blue markets (no gov-rug) |
| **Maple syrupUSDC** (Core) | ~4.7% | +1.3pp | ~$1.2B | on-chain overcollat 125-333%, zero defaults >$600M; cap borrower-concentration |
| **Aave V3** USDC | ~floor | ~0 | deepest | the anchor: safest lending = the floor (hold T-bills instead) |
> These are the deployable non-Ethena book — a diversified mix lands **~4.3-4.75%**, bounded, ~90-135bps
> over floor. Deep + honest, but NOT 8-12%.

## The 8-12% non-Ethena question — one standout, one watch
- **Maple High Yield Secured (~9-11%) — the standout** (`concentration_unverified_but_onchain_retrievable`):
  the ONE non-Ethena 8-12% whose loss-buffer (150-500% overcollat + margin calls) is **on-chain verifiable**
  → clears the opacity hold that stopped Centrifuge; recourse is dual (overcollat + legal claim on borrower).
  **One Proof-of-Reserves query (top-N borrower concentration) from ADVANCE-with-cap.**
- **Huma Finance (~10.5% Classic) — WATCH** (`onchain_first_loss_tranche_but_points_subsidized`): shares the
  on-chain first-loss trait, but headline is points-subsidized + originator cashflow partly off-chain.
- Everything else at 8-12% non-Ethena is either **dead/defaulted** (Goldfinch, TrueFi, Level), **opaque**
  (Centrifuge off-chain buffer, SCOPE/ACRED), or **realized-depeg** (Usual USD0++ governance-set floor).

## The 8-12% that's real but concentrated: Ethena
PT-sUSDe fixed-carry (~11.2%) is fully underwritten end-to-end — the fixed-to-maturity wrapper removes the
funding-flip tail; USDe solvency stress-validated (Oct-2025 $19B crash survived). BUT: **capacity-limited**
(~single-digit $M/maturity), and laddering Ethena PTs **concentrates** (~70% of all Pendle TVL is Ethena) —
diversify by *issuer*, not by adding more Ethena PTs. `fixed_carry_held_to_maturity_bounded` + `same_underlying_concentration_cap`

## Structural scarcities (mapped, not guessed)
- **Deep non-Ethena FIXED-RATE does not exist in 2026.** Frax FXB (real, ~$500K/series), Notional (dead
  ~$3M), Term Finance (thin, −74% from peak) — all capacity-thin. Only **Ethena PT** is deep.
- **Chain-hopping doesn't escape Ethena.** Base's "safe" yield is Ethena-collateralized; **Solana + Arbitrum**
  are the real non-Ethena cross-chain diversifiers (native-CCTP, Ethena-isolated) but thin / currently sub-floor.
- **The cleanest new stables route yield to integrators, not holders** (Agora AUSD, M0 wM) — their edge is
  *being an integrator* (off-code relationship, custody/legal), which is the RWA-Backstop thesis-#2 conclusion.

## The REFUSE archetypes (why yield ⟂ fundability)
The biggest headline yields draw the hardest NO: Resolv RLP (20-30%, first-loss leverage, tail FIRED −39%
depeg); options-income vaults (short-vol, gross≠net, 9/13 DOVs dead); Curve/Aerodrome LP (emissions, not
carry); Usual USD0++ (governance rewrote redemption → realized depeg); ETH/BTC basis (unbounded funding +
CEX). Reason-code taxonomy (~35 codes) in [`underwriting_rubric.md`](underwriting_rubric.md).

## The honest bottom line (the pick-two rule)
**You cannot have {8-12% · diversified · non-Ethena · at-scale} all at once.**
- Want **deep + bounded + non-Ethena** → ~4.3-4.75% (Fluid/Steakhouse/Maple-Core/floor). Real, fundable, honest.
- Want **8-12% non-Ethena** → Maple-HY (on-chain-underwritable, concentration-capped) — the only publicly
  underwritable one; or accept opacity/higher-risk credit.
- Want **8-12% deep** → Ethena (PT-sUSDe), capacity-limited and concentration-capped.

The **$10M/yr fundable edge is not a yield number** — it is the **measurement / underwriting role**: being the
desk that on-chain-verifies buffers, refuses tail-comp, and publicly proves its decisions
([`STRUCTURAL_DESK.md`](STRUCTURAL_DESK.md)). Scale/trust/relationships (custody, whitelisting, legal) are
off-code. This map is the product: **the decisions, honestly framed and independently checkable.**
