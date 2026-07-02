# Risk Disclosure — reusable block

> **Task:** COMPLIANCE-004. A **reusable risk-disclosure block** for any surface (docs, reports,
> dashboards, memos). Per `docs/06` E.15, risk disclosure and honest framing must remain visible on
> **every public surface**. Copy the block in §1 verbatim onto the surface; use §2 to tailor.
> **This is not legal advice** — see `docs/22_compliance_surface.md` / `docs/42` (counsel-gated).
> **Related:** `docs/37` (evidence levels L0–L6), `docs/06` (invariants).

## 1. Standard block (copy verbatim)

> **Risk disclosure.** SPA is at the **paper-trading stage**: figures shown are tracked on a virtual
> book, not live capital, unless explicitly labelled otherwise. **Nothing here is investment,
> financial, legal, or tax advice**, an offer, or a solicitation. **No return is guaranteed.** Past
> or simulated performance does not indicate future results. In live use, **capital is at risk,
> including the risk of total loss**. Every APY / performance figure is shown with its **evidence
> level (L0–L6)**, yield source, risk category, and last-verified date; a figure without a live
> evidence level is **not** an executed or observed result. Higher-yield strategies carry higher
> risk and are only used after the Yield Lab lifecycle and human approval. Any spread over the RWA
> floor is presented only where each point is explained by a specific, accepted, measurable risk;
> unexplained spread is refused, not marketed. Figures may be stale or estimated — unknown values are
> shown as "requires verification". **No external capital is accepted without legal review.**

## 2. Tailoring (per surface — do not weaken the block)

Optionally append only clarifying context; never remove or soften the language above.

- **Surface:** <page / report / memo / dashboard panel>
- **Live vs paper:** <this figure is PAPER / LIVE — label explicitly>
- **Evidence level of headline figure(s):** <L0–L6> · **source:** <feed/module> · **as-of:** <UTC>
- **Applicable extra caveats:** <e.g. depeg risk, funding-rate risk, smart-contract risk, capacity limits>

## 3. Placement rules

- Place the §1 block where it is **visible on the surface**, not buried.
- Do not present paper/backtest as live; do not present advertised APY as executable/observed
  (`docs/06` C.8).
- If any required field is unknown, write **"requires verification"** — never invent a number.
