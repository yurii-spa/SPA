# 22 — Compliance Surface (map + gap catalogue)

> **Task:** COMPLIANCE-001. Maps the **existing** `spa_core/compliance/` module and catalogues
> disclosure / external-capital / advisory-vs-managed **gaps as questions for counsel** — this is
> **not legal advice**. **No external capital may be accepted without a legal review** (`docs/06`
> E.18; `docs/adr/ADR-YL-006`; `docs/42` external-capital readiness).
> **Related:** `docs/06` (invariants), `docs/45` (compliance-surface map, if present),
> `docs/42` (external-capital readiness), `docs/43` (dangerous-strategies catalogue),
> `docs/templates/risk_disclosure.md` (COMPLIANCE-004), `docs/37` (evidence levels).

## 1. What exists today — `spa_core/compliance/`

A **read-only / advisory** reporting module. Per its own docstring it **never** modifies allocator,
risk, execution, or cycle state — it consumes daily-cycle JSON state + the SHA-256 audit hash chain
and emits compliance artifacts under `data/`. Pure stdlib, atomic writes, LLM FORBIDDEN.

| Component | Role (as built) | Emits |
|---|---|---|
| `audit_report_generator.py` | Institutional audit report — identity, governance, risk controls, paper-trading track record, current positions, recent-events log, cryptographic integrity of the audit hash chain, system health. Each section computed defensively (missing/corrupt input → error/unknown marker, not an abort). | `data/compliance_report.json`, `data/compliance_report.md` |
| `monthly_statement.py` | Period (monthly/weekly) statement — opening/closing NAV, period return $ and %, annualized figure, strategy mix, risk-events attestation. First partial period `2026-06-10..2026-06-21`. | `data/statements/<period>.json` |
| `__init__.py` | Package docstring stating the read-only / advisory / stdlib / atomic / LLM-FORBIDDEN contract; `__all__ = ["audit_report_generator", "monthly_statement"]`. | — |

**What this module is:** internal reporting / attestation over the paper track (audit report +
period statements). **What it is not:** it is **not** a legal/regulatory compliance engine, KYC/AML,
investor-onboarding, or disclosure-management system. Those do not exist in code today.

## 2. Coverage vs. what a managed offering would need

| Area | Covered by existing module? | Note |
|---|---|---|
| Internal audit report / attestation | **Yes** (`audit_report_generator.py`) | Advisory, over paper track |
| Period NAV / return statements | **Yes** (`monthly_statement.py`) | Advisory, paper only |
| Cryptographic integrity / audit trail | **Yes** (hash-chain integrity section) | Reuses audit signer |
| Public risk disclosure surface | **Partial** — invariant requires it (`docs/06` E.15); template = COMPLIANCE-004 | Not owned by this module |
| Advisory-vs-managed classification | **No** — not addressed in code | See gaps §3 |
| External-capital onboarding (KYC/AML, agreements) | **No** | Legal-review-gated; `docs/42` |
| Jurisdictional / regulatory registration | **No** | Counsel question §3 |

## 3. Gap catalogue — questions for counsel (NOT legal advice)

These are **open questions to route to legal counsel** before any external-capital or managed
posture. They are catalogued here, not answered here.

### 3a. Disclosure gaps
- Is the current public framing (paper-stage, evidence-levelled APY, refusal log) sufficient
  disclosure for the audience it reaches today? What mandatory disclosures are missing?
- Does presenting a paper track record publicly (even clearly labelled non-live) create any
  representation/marketing obligations? What legend must accompany every performance number?
- Is the standard risk disclosure (`docs/templates/risk_disclosure.md`) required on **every** public
  surface, and does its language meet counsel's bar?

### 3b. External-capital gaps
- What is the minimum legal structure (entity, agreements, custody, jurisdiction) required **before
  accepting any external capital**? *(Invariant: none accepted without legal review — `docs/06` E.18.)*
- KYC / AML / investor-eligibility (accredited/qualified) obligations by jurisdiction?
- Custody model for external capital — the code is **non-custodial, human-in-the-loop** (ADR-YL-005);
  does a managed offering change the custody/regulatory picture?

### 3c. Advisory-vs-managed gaps
- Where is the line between **decision-support / advisory** (current posture, L0/L1) and a **managed
  product**, and which regulatory regime attaches to each?
- Do the BTC/ETH modules (**decision-support, not auto-trading** — ADR-YL-007) or the Capital
  Allocation agent's recommendations cross into "advice" as a regulated activity?
- Does publishing an allocation *recommendation* (PORT-002) differ, legally, from *managing* an
  allocation?

## 4. Standing constraints (do not violate)

- **No external capital without legal review** (`docs/06` E.18). This doc does not relax that.
- Compliance code stays **read-only / advisory / stdlib / atomic / LLM-FORBIDDEN** (module contract).
- **Risk disclosure and honest framing remain visible on every public surface** (`docs/06` E.15);
  every APY carries an evidence level L0–L6 (`docs/37`).
- This document is a **map + question list**, not legal advice; counsel must review before any
  external-capital or managed step.
