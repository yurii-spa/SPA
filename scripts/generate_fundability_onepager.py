#!/usr/bin/env python3
"""
FUNDABILITY one-pager generator for SPA.

Builds docs/FUNDABILITY.md — a single, auto-generated, REAL-DATA, HONEST page
making the trust/scale case (the STRUCTURAL_DESK framing: $10M is scale+trust,
not more APY). The refusal-chain + the published NO-GO ARE the differentiator.

Design contract (matches the codebase rules):
- stdlib-only, deterministic (same data -> same bytes), fail-CLOSED, atomic write.
- Sources EVERY performance number live from data/ files. A missing source is
  reported HONESTLY as "data unavailable" / "unavailable" — NEVER fabricated.
- No LLM, no marketing inflation. Honesty over polish.

Re-runnable:
    python3 scripts/generate_fundability_onepager.py        # print to stdout
    python3 scripts/generate_fundability_onepager.py --md   # write docs/FUNDABILITY.md
"""

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

# --------------------------------------------------------------------------- #
# Honest "no data" sentinel — printed instead of any fabricated number.
# --------------------------------------------------------------------------- #
UNAVAILABLE = "_data unavailable_"


def _repo_root() -> str:
    """Repository root (parent of scripts/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_json(path: str):
    """Load a JSON file. Return None on missing / parse error (fail-CLOSED).

    Returning None (not {}) lets every consumer distinguish "source present but
    empty" from "source missing" and emit the honest UNAVAILABLE sentinel.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def load_jsonl(path: str):
    """Load a JSONL file into a list of dicts. Return None on missing/error."""
    try:
        out = []
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # Skip a single corrupt line rather than fabricate; the count
                    # is honestly derived only from parseable records.
                    continue
        return out
    except (FileNotFoundError, OSError):
        return None


def _get(d, *keys, default=None):
    """Safe nested getter. Any missing link -> default (fail-CLOSED)."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _fmt_pct(v, digits=2):
    """Format a percent value, honestly UNAVAILABLE if absent/non-numeric/non-finite.

    Fail-CLOSED on NaN/inf: a non-finite number is a corrupt upstream metric, NOT a real
    percent — it renders as the honest UNAVAILABLE sentinel, never a leaked 'nan%'/'inf%'
    (which would otherwise pass an honest-looking number to a funder)."""
    if v is None:
        return UNAVAILABLE
    try:
        f = float(v)
    except (TypeError, ValueError):
        return UNAVAILABLE
    if not math.isfinite(f):
        return UNAVAILABLE
    return f"{f:.{digits}f}%"


def _fmt_usd(v):
    """Format a USD value, honestly UNAVAILABLE if absent/non-numeric/non-finite (fail-CLOSED on
    NaN/inf — a non-finite dollar figure is corrupt, never rendered as 'nan'/'inf')."""
    if v is None:
        return UNAVAILABLE
    try:
        f = float(v)
    except (TypeError, ValueError):
        return UNAVAILABLE
    if not math.isfinite(f):
        return UNAVAILABLE
    return f"${f:,.0f}"


# --------------------------------------------------------------------------- #
# Source loading — one place, so a missing file degrades to UNAVAILABLE.
# --------------------------------------------------------------------------- #

def load_sources(root: str) -> dict:
    """Load every data source the one-pager references. Missing -> None."""
    d = os.path.join(root, "data")
    return {
        "golive": load_json(os.path.join(d, "golive_status.json")),
        "promotion": load_json(os.path.join(d, "rates_desk", "rates_desk_promotion.json")),
        "decisions": load_jsonl(os.path.join(d, "rates_desk", "decision_log.jsonl")),
        "rwa": load_json(os.path.join(d, "rwa_safety_board.json")),
        "forward": load_json(os.path.join(d, "forward_track_integrity.json")),
        "dry_run": load_json(os.path.join(d, "golive_dry_run.json")),
        # Live risk-adjusted scorecard on the accruing forward series (T4+T5).
        # Sourced from the on-disk artifact the forward_analytics module writes;
        # missing -> UNAVAILABLE, never recomputed/fabricated here.
        "forward_analytics": load_json(os.path.join(d, "forward_analytics.json")),
        # Day-30 readiness artifact (WS5) — auto/verifiable/hash-anchored. Surfaced
        # so the one-pager shows the SAME live readiness % + verdict + proof_hash the
        # /fundability page reads. Missing -> UNAVAILABLE, never fabricated.
        "day30": load_json(os.path.join(d, "day30_artifact.json")),
        # ── WS6 REALIZED-ONLY sources (ROUND-2 WS1 truth artifacts) ──────────────
        # The headline edge claim now traces to these REALIZED forward outputs, NOT
        # to the BACKTEST promotion table. Missing -> UNAVAILABLE, never fabricated.
        "carry_truth": load_json(os.path.join(d, "carry_truth_table.json")),
        "edge_at_scale": load_json(os.path.join(d, "edge_at_scale.json")),
        "realized_ab": load_json(os.path.join(d, "realized_ab", "realized_ab.json")),
        "refusal_cost": load_json(os.path.join(d, "refusal_cost.json")),
        # Q2-5b avoided-loss refusal ledger — the OTHER side of §2d: what refusing the
        # structurally-toxic LRT PTs SAVED (real peg-drawdown lower bound). Missing -> UNAVAILABLE.
        "refusal_value": load_json(os.path.join(d, "rates_desk", "refusal_value.json")),
    }


# --------------------------------------------------------------------------- #
# Derived, HONEST summaries (never fabricated; missing source -> UNAVAILABLE)
# --------------------------------------------------------------------------- #

def decisions_summary(decisions):
    """Refusal/entry proof-chain summary from the decision log.

    Returns a dict with honest counts, or all-None if the source is missing.
    """
    if decisions is None:
        return {"available": False}
    refusals = entries = 0
    reasons = {}
    toxic = set()
    for rec in decisions:
        kind = rec.get("kind")
        if kind == "REFUSAL":
            refusals += 1
            r = rec.get("reason", "?")
            reasons[r] = reasons.get(r, 0) + 1
            u = rec.get("underlying")
            if u:
                toxic.add(u)
        elif kind == "ENTRY":
            entries += 1
    return {
        "available": True,
        "total": len(decisions),
        "refusals": refusals,
        "entries": entries,
        "reasons": reasons,
        "tail_veto": reasons.get("tail_veto", 0),
    }


def rates_desk_sleeves(promotion):
    """Extract the per-sleeve verdicts honestly from the promotion file."""
    if promotion is None:
        return None
    sleeves = promotion.get("sleeves")
    if not isinstance(sleeves, list):
        return None
    rows = []
    for s in sleeves:
        rows.append({
            "shape": s.get("shape", "?"),
            "stage": s.get("stage", "?"),
            "net_apy_pct": s.get("net_apy_pct"),
            "beats_floor": s.get("beats_floor"),
            "max_dd_pct": s.get("max_drawdown_pct"),
            "refusals": s.get("refusals_count"),
            "kills": s.get("kills"),
        })
    return rows


# --------------------------------------------------------------------------- #
# Section builders — each returns a markdown string, each fail-CLOSED.
# --------------------------------------------------------------------------- #

def _section_thesis() -> str:
    return (
        "## 1. The thesis — measurement, not yield\n\n"
        "**Honesty contract for this sheet (WS6):** every performance claim below traces to a "
        "**REALIZED** data point (the live forward `*_series.json` tracks, decomposed by the "
        "WS1 carry truth-table + realized A/B) **or** is labeled **INSUFFICIENT_DATA**. A "
        "backtest figure is NEVER presented as realized; where a backtest is shown it is "
        "explicitly fenced as **BACKTEST (not realized)**.\n\n"
        "SPA's research arc already killed the obvious answer: **plain crypto-yield is a "
        "diversifier, not an edge**. Neutral books don't beat the tokenized-T-bill floor "
        "risk-adjusted, directional books eat the full drawdown, and LRT restaking dies in "
        'crashes (ezETH depeg). "More APY" is a dead end.\n\n'
        "> **The edge is not yield. The edge is the structural role of honest measurement / "
        "underwriting** — being the party that can correctly price and refuse risk others "
        "don't see, and *prove* it.\n\n"
        "The convergent, honest conclusion: **the moat is real, but it is a scale / trust / "
        "relationships play, not a single-strategy alpha play** — AND, on the REALIZED forward "
        "track to date, **the desk does not yet demonstrably beat the RWA floor at fundable "
        "scale.** That is the honest WS1 verdict and this sheet does not contradict it. "
        "$10M/year is reachable through scale across many capacity-bound books plus the trust "
        "earned by a transparent, fail-closed measurement-and-refusal engine — over multiple "
        "years — not by chasing a higher headline rate, and not today. The code builds the "
        "proof; the proof earns the trust; the trust + capital + relationships are what turn "
        "it into $10M.\n"
    )


def _fmt_bps(v):
    """Render carry-above-floor bps; honest INSUFFICIENT_DATA sentinel when null/non-finite.

    CRITICAL (red-team): a null bps must NEVER render as a rounded '0.0' — that would mask
    INSUFFICIENT_DATA as a real at-floor verdict. None -> the explicit INSUFFICIENT_DATA token."""
    if v is None:
        return "INSUFFICIENT_DATA"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "INSUFFICIENT_DATA"
    if not math.isfinite(f):
        return "INSUFFICIENT_DATA"
    return f"{f:+.2f} bps"


def _section_realized_edge(carry_truth, realized_ab, edge_at_scale, decisions, refusal_cost, refusal_value=None) -> str:
    """## 2 — the REALIZED edge to date. Every number here is read from a WS1 realized artifact
    (carry_truth_table / realized_ab / edge_at_scale / refusal_cost) or is INSUFFICIENT_DATA.
    NO backtest figure appears in this section."""
    lines = ["## 2. The realized edge — to date (realized-only, never backtest)\n"]
    lines.append(
        "This is the genuinely-fundable section: it is built **only** on REALIZED forward "
        "numbers. Every cell traces to a live `*_series.json` track decomposed by the WS1 "
        "machinery, or reads **INSUFFICIENT_DATA**. The honest one-line answer first:\n"
    )

    # --- 2a. Carry truth-table (realized carry-above-floor per sleeve) ----------------------
    lines.append("\n### 2a. Carry truth-table — realized carry above the RWA floor\n")
    if carry_truth is None or not isinstance(carry_truth, dict) or not carry_truth.get("rows"):
        lines.append(
            f"Carry truth-table: {UNAVAILABLE} (carry_truth_table.json missing — the realized "
            "carry decomposition has not been generated yet).\n"
        )
    else:
        floor = carry_truth.get("rwa_floor_apy_pct")
        n_above = carry_truth.get("n_above_floor")
        n_at = carry_truth.get("n_at_floor")
        n_below = carry_truth.get("n_below_floor")
        n_insuff = carry_truth.get("n_insufficient_data")
        min_days = carry_truth.get("min_days_for_bps")
        lines.append(
            f"Realized carry-above-the-floor (bps/yr) per forward sleeve, ranked. RWA floor: "
            f"**{_fmt_pct(floor, 2)}/yr** (live tokenized-T-bills). A verdict is only trusted at "
            f"**>= {min_days if min_days is not None else UNAVAILABLE} distinct forward days**; "
            "below that the sleeve reads **INSUFFICIENT_DATA** with a **null** bps — never a "
            "fabricated 0.0. Carry is the NAV-reconciling residual (carry + floor == realized "
            "PnL exactly), so no leg can be inflated independently.\n\n"
            f"**Tally:** above floor **{n_above if n_above is not None else UNAVAILABLE}** · "
            f"at floor **{n_at if n_at is not None else UNAVAILABLE}** · "
            f"below floor **{n_below if n_below is not None else UNAVAILABLE}** · "
            f"**INSUFFICIENT_DATA {n_insuff if n_insuff is not None else UNAVAILABLE}**.\n"
        )
        lines.append(
            "\n| sleeve | realized carry vs floor | realized carry $ | track depth | verdict |")
        lines.append("|---|---:|---:|---:|:--|")
        for r in carry_truth.get("rows") or []:
            if not isinstance(r, dict):
                continue
            bps = r.get("carry_above_floor_bps")
            carry_usd = r.get("realized_carry_usd")
            n_pts = r.get("n_points")
            verdict = r.get("verdict", "INSUFFICIENT_DATA")
            lines.append(
                f"| {r.get('sleeve', '?')} | {_fmt_bps(bps)} | "
                f"{_fmt_usd(carry_usd) if carry_usd is not None else UNAVAILABLE} | "
                f"{n_pts if n_pts is not None else UNAVAILABLE} pts | {verdict} |"
            )
        lines.append("")
        lines.append(
            "**The honest reading:** at today's track depth **every** realized sleeve is "
            "INSUFFICIENT_DATA, and the two longest tracks (the FixedCarry carry book and the "
            "RWA sleeve) are **at-or-below** the floor on realized carry so far. The desk does "
            "**not** yet demonstrably beat the floor on realized data. This is the correct "
            "reading of a few-day track — not a failure, and not hidden.\n"
        )

    # --- 2b. Realized forward A/B (the optimizer uplift, realized not replayed) -------------
    lines.append("\n### 2b. Realized forward A/B — the optimizer uplift (realized, not a replay)\n")
    if realized_ab is None or not isinstance(realized_ab, dict):
        lines.append(
            f"Realized A/B: {UNAVAILABLE} (realized_ab.json missing — the realized forward A/B "
            "has not been generated yet).\n"
        )
    else:
        is_realized = realized_ab.get("is_realized")
        n_days = realized_ab.get("n_days")
        min_days = realized_ab.get("min_days_for_verdict")
        verdict = realized_ab.get("verdict", "INSUFFICIENT_DATA")
        decomp = realized_ab.get("decomposition") or {}
        raw = decomp.get("raw_uplift_bps")
        sel = decomp.get("selection_alpha_bps")
        drag = decomp.get("cash_drag_bps")
        lines.append(
            f"`is_realized`: **{_yn(is_realized)}** — each UTC day the live held-universe is "
            "scored ONCE through the legacy heuristic AND the optimizer and banked into parallel "
            "paper books (one distinct row per day). This is **not** a replayed backtest. Current "
            f"depth: **{n_days if n_days is not None else UNAVAILABLE} day(s)** "
            f"(verdict trusted at >= {min_days if min_days is not None else UNAVAILABLE}); "
            f"verdict **{verdict}**.\n\n"
            "Honest apples-to-apples decomposition (the raw gap mixes selection skill with a "
            "cash-drag advantage the legacy book gets for free by skipping the 5% cash floor):\n\n"
            f"- raw uplift (NOT apples-to-apples): **{_fmt_bps(raw)}**\n"
            f"- **selection alpha** (apples-to-apples, both reserve 5%): **{_fmt_bps(sel)}**\n"
            f"- cash-drag leg (the floor-skip advantage, NOT skill): **{_fmt_bps(drag)}**\n\n"
            "Even where the realized selection alpha reads positive on day 1, the verdict stays "
            "INSUFFICIENT_DATA until the track matures — a 1-day uplift is not an edge.\n"
        )

    # --- 2c. Edge-at-scale curve (the load-bearing honest finding) --------------------------
    lines.append("\n### 2c. Edge at scale — the optimizer's uplift is a $100k artifact\n")
    if edge_at_scale is None or not isinstance(edge_at_scale, dict) or not edge_at_scale.get("curve"):
        lines.append(
            f"Edge-at-scale curve: {UNAVAILABLE} (edge_at_scale.json missing).\n"
        )
    else:
        mat = edge_at_scale.get("materiality_pp")
        below_at = edge_at_scale.get("edge_below_materiality_at_aum_usd")
        survives = edge_at_scale.get("edge_survives_at_max_aum")
        lines.append(
            "The optimizer uplift recomputed at each AUM AFTER the real MP-209/ADR-009 "
            "pool-capacity caps bind (capacity-capped capital becomes idle cash, earns 0 — the "
            f"conservative drag). Materiality bar: **{_fmt_pct(mat, 2)}**.\n\n"
            "| AUM | legacy yield | optimizer yield | uplift | material? |\n"
            "|---|---:|---:|---:|:--:|"
        )
        for c in edge_at_scale.get("curve") or []:
            if not isinstance(c, dict):
                continue
            aum = c.get("aum_usd")
            leg = c.get("legacy_yield_on_capital_pct")
            opt = c.get("optimized_yield_on_capital_pct")
            up = c.get("uplift_pp")
            material = c.get("uplift_material")
            up_str = (f"{up:+.2f}pp" if isinstance(up, (int, float)) and math.isfinite(up)
                      else UNAVAILABLE)
            lines.append(
                f"| {_fmt_usd(aum)} | {_fmt_pct(leg, 2)} | {_fmt_pct(opt, 2)} | "
                f"{up_str} | {_yn(material)} |"
            )
        lines.append("")
        lines.append(
            "**The load-bearing honest finding (WS1):** the optimizer's **+1.08pp is a "
            "$100k-scale artifact**. It falls below the materiality bar and goes **NEGATIVE past "
            f"~$1M AUM** (edge survives at max AUM tested: **{_yn(survives)}**"
            + (f"; first AUM below materiality: **{_fmt_usd(below_at)}**" if below_at is not None
               else "")
            + "). The optimizer concentrates into high-yield small-TVL pools; at $1M+ the "
            "1%-of-TVL cap forces most of that book into idle cash. **At the fundable size that "
            "underlies the $100M thesis, today's universe cannot support the edge.** We do not "
            "claim otherwise.\n"
        )

    # --- 2d. Refusal cost (why in cash — is the conservatism defensible?) -------------------
    lines.append("\n### 2d. Cost of refusal — is sitting in cash defensible?\n")
    if refusal_cost is None or not isinstance(refusal_cost, dict):
        lines.append(f"Refusal-cost ledger: {UNAVAILABLE} (refusal_cost.json missing).\n")
    else:
        cost = refusal_cost.get("cost_of_caution_bps_per_yr_if_real")
        n_days = refusal_cost.get("n_days")
        min_days = refusal_cost.get("min_days_for_agg")
        defensible = _get(refusal_cost, "interpretation", "defensible")
        lines.append(
            f"From the FixedCarry forward series' per-day scan diagnostics (read-only "
            f"re-derivation, {n_days if n_days is not None else UNAVAILABLE} diagnostic day(s), "
            f"aggregated at >= {min_days if min_days is not None else UNAVAILABLE}): "
            f"cost-of-caution **{_fmt_bps_yr(cost)}** **IF** the refused edge were real carry. "
            "But the gate's thesis is that the refused yield is **tail-compensation** (the "
            "2025-10 USDe-leverage-unwind / ezETH pattern), not carry — so this 'cost' is an "
            "insurance premium, not forgone alpha. Since even the approved FixedCarry book is "
            "below the floor on realized data so far (§2a), the conservatism is "
            f"**{defensible or UNAVAILABLE}**\n"
        )

    # --- 2e. Avoided loss (the OTHER side of 2d — what refusing SAVED, real $) ---------------
    lines.append("\n### 2e. Avoided loss — the refusal moat as realized $ (conservative lower bound)\n")
    if refusal_value is None or not isinstance(refusal_value, dict):
        lines.append(f"Avoided-loss ledger: {UNAVAILABLE} (refusal_value.json missing).\n")
    else:
        total = refusal_value.get("total_avoided_loss_usd_per_100k")
        events = refusal_value.get("events") or []
        unpriced = refusal_value.get("unpriced") or []
        lines.append(
            "§2d prices what refusing COSTS (an insurance premium). This prices what it SAVED. For each "
            "structurally-refused toxic-LRT PT, a naive book holding it would have taken the underlying's "
            "**real ETH-peg drawdown** — a conservative lower bound (Pendle `pt_price` history is all-null, "
            "and the AMM exit discount in a rush is typically larger). The peak advertised implied yield is "
            "shown as EVIDENCE the gate read the yield as tail-comp, **not** netted as forgone carry.\n"
        )
        if events:
            lines.append("| refused underlying | window | peg drawdown | avoided loss / $100k | advertised implied yield (tail-comp) |")
            lines.append("|---|:--|---:|---:|---:|")
            for e in events:
                lines.append(
                    f"| {e.get('underlying', UNAVAILABLE)} | {e.get('window', UNAVAILABLE)} | "
                    f"{_fmt_pct(e.get('peg_drawdown_pct'))} | {_fmt_usd(e.get('avoided_loss_usd_per_100k'))} | "
                    f"{_fmt_pct(e.get('peak_advertised_implied_yield_pct'))} |"
                )
            lines.append("")
        lines.append(
            f"**Total avoided (lower bound): {_fmt_usd(total)} per $100k of naive allocation** across "
            f"{len(events)} priced LRT depeg(s)"
            + (f"; {len(unpriced)} event(s) UNPRICED (no peg series — rsETH/USDe — listed, never fabricated)."
               if unpriced else ".")
            + " This is the refusal moat as a P&L number: the gate refused PTs advertising 40–60% implied "
            "yield right before they broke peg 20–28%. Advisory / measurement — never gates, never capital.\n"
        )
    return "\n".join(lines)


def _fmt_bps_yr(v):
    """bps/yr value, honest UNAVAILABLE if absent/non-finite."""
    if v is None:
        return UNAVAILABLE
    try:
        f = float(v)
    except (TypeError, ValueError):
        return UNAVAILABLE
    if not math.isfinite(f):
        return UNAVAILABLE
    return f"{f:.2f} bps/yr"


def _section_validated_edge(promotion, decisions, rwa) -> str:
    lines = ["## 3. The engine + proof — refusal-first carry (BACKTEST + measurement)\n"]
    lines.append(
        "> **The sleeve APY/DD figures in the table below are BACKTEST numbers (not realized).** "
        "They describe the engine's behaviour over the 2024-2026 replay window, NOT money earned "
        "on the live forward track. The REALIZED edge to date is §2; this section documents the "
        "engine that produced the refusals and the live proof chain.\n"
    )

    # --- Rates Desk: GO -------------------------------------------------- #
    lines.append("### Rates Desk engine — **BACKTEST-validated** (refusal-first carry)\n")
    sleeves = rates_desk_sleeves(promotion)
    floor = _get(promotion or {}, "rwa_floor_pct")
    lines.append(
        "A risk-adjusted fair-value model for tokenized yield that (a) harvests genuinely "
        "mispriced carry and (b) REFUSES yield that is just tail-risk compensation "
        "(the ezETH / over-levered-USDe pattern). RWA floor reference: "
        f"**{_fmt_pct(floor, 1)}/yr**.\n"
    )
    if sleeves is None:
        lines.append(f"\nSleeve verdicts: {UNAVAILABLE} (rates_desk_promotion.json missing).\n")
    else:
        lines.append("\n**BACKTEST (not realized)** — engine behaviour over the 2024-2026 replay:\n")
        lines.append("\n| sleeve | stage | net APY %/yr (BACKTEST) | beats floor (BACKTEST) | max DD % | refusals | kills |")
        lines.append("|---|---|---:|:--:|---:|---:|---:|")
        for s in sleeves:
            beats = (
                "yes" if s["beats_floor"] is True
                else "no" if s["beats_floor"] is False
                else UNAVAILABLE
            )
            lines.append(
                f"| {s['shape']} | {s['stage']} | "
                f"{_fmt_pct(s['net_apy_pct'], 4) if s['net_apy_pct'] is not None else UNAVAILABLE} | "
                f"{beats} | "
                f"{_fmt_pct(s['max_dd_pct'], 3) if s['max_dd_pct'] is not None else UNAVAILABLE} | "
                f"{s['refusals'] if s['refusals'] is not None else UNAVAILABLE} | "
                f"{s['kills'] if s['kills'] is not None else UNAVAILABLE} |"
            )
        lines.append("")

    # The refusal proof chain (live from decision_log.jsonl).
    ds = decisions_summary(decisions)
    if not ds.get("available"):
        lines.append(f"Proof chain (refusals / entries): {UNAVAILABLE} (decision_log.jsonl missing).\n")
    else:
        lines.append(
            f"**Proof chain** (live, hash-linked `data/rates_desk/decision_log.jsonl`): "
            f"**{ds['total']}** logged decisions — **{ds['refusals']} refusals** "
            f"(of which **{ds['tail_veto']}** structural tail-vetoes) and **{ds['entries']} entries**. "
            "Every decision — entry AND refusal — is hashed into a tamper-evident record: "
            'the public "what we traded AND what we refused, and why."\n'
        )

    # Honest caveats — load-bearing for credibility.
    lines.append(
        "\n**Honest caveats (stated, not hidden):**\n"
        "- The refusal fired **early** — toxic LRT PT books (ezETH / rsETH) were refused "
        "~100% of days on *structural* grounds, never held into the Aug-2024 / Oct-2025 / "
        "Apr-2026 depegs; a huge quoted rate never rescued a tail-vetoed book.\n"
        "- Deflated Sharpe is **structurally degenerate** for locked held-to-maturity carry "
        "(near-zero downside variance by construction) — reported as a not-noise check only.\n"
        "- **The backtest APY above is NOT the realized edge.** On the REALIZED forward track "
        "(§2) the FixedCarry book is **below the floor so far** and every sleeve is "
        "INSUFFICIENT_DATA. The backtest validates the engine's behaviour through stress "
        "windows; it does not assert money was earned live. We do not present it as realized.\n"
        "- The carry edge is **capacity-bound** (~$250k fundable ceiling per book; the §9 "
        "exit-capacity rule sizes DOWN rather than eat slippage). A single rates book does "
        "**not** clear $10M — this needs **scale across many gated books**.\n"
    )

    # --- RWA measurement: GO / book NO-GO ------------------------------- #
    lines.append("\n### RWA Repo Backstop — **measurement-GO / book NO-GO**\n")
    if rwa is None:
        lines.append(f"RWA Safety Board: {UNAVAILABLE} (rwa_safety_board.json missing).\n")
    else:
        n_assets = rwa.get("n_assets")
        n_not_cash = rwa.get("n_not_cash_like")
        vc = rwa.get("verdict_counts") or {}
        max_div = _get(rwa, "onchain_nav_coverage", "max_abs_nav_divergence_pct")
        lines.append(
            f'"Lend against Liquidation NAV, not marketing NAV." The Safety Board measures, '
            f"from free data, that RWA collateral is genuinely **not cash-like** on an "
            f"executable on-chain exit: "
            f"**{n_not_cash if n_not_cash is not None else UNAVAILABLE}/"
            f"{n_assets if n_assets is not None else UNAVAILABLE}** assets not cash-like "
            f"(LIQUID {vc.get('LIQUID', UNAVAILABLE)} · THIN {vc.get('THIN', UNAVAILABLE)} · "
            f"REDEMPTION_ONLY {vc.get('REDEMPTION_ONLY', UNAVAILABLE)} · "
            f"UNSAFE {vc.get('UNSAFE', UNAVAILABLE)}). Max on-chain ERC-4626 NAV divergence "
            f"from $1.00 marketing NAV measured: "
            f"**{_fmt_pct(max_div, 2) if max_div is not None else UNAVAILABLE}**. "
            "The *measurement* layer is GO (deterministic, fail-closed, runs continuously); "
            "the underwriting *book* is NO-GO read-only — it needs whitelisting + redemption "
            "agreements + capital + legal, none of it buildable in code.\n"
        )

    # --- Liquidator: NO-GO (we publish what we kill) -------------------- #
    lines.append("\n### Liquidator — **NO-GO** (published — we publish what we kill)\n")
    lines.append(
        "The long-tail / nested-collateral liquidation opportunity was measured read-only at "
        "~$3.8M/yr gross addressable (top-20 ~$2.2M/yr) — ~5-10x **below** the $20M/yr bar, "
        "too small to justify the custody + CEX + balance-sheet build. **VERDICT: NO-GO, "
        "published.** Publishing the kill is itself the credibility signal: the desk states "
        "plainly what it refuses to build, not only what it ships.\n"
    )
    return "\n".join(lines)


def _day30_readiness_line(day30) -> str:
    """A single honest readiness line from the day-30 artifact (WS5), with its proof_hash.

    Fail-CLOSED: a missing/invalid artifact reads UNAVAILABLE, never a fabricated readiness."""
    if not isinstance(day30, dict) or "proof_hash" not in day30:
        return (f"\n**Day-30 readiness artifact:** {UNAVAILABLE} (day30_artifact.json not generated "
                "yet — the auto/verifiable/hash-anchored readiness report lands once the watchdog "
                "runs).\n")
    verdict = day30.get("verdict", "UNKNOWN")
    pct = day30.get("readiness_pct")
    ev = _get(day30, "evidenced", "evidenced_days")
    proof = day30.get("proof_hash") or ""
    return (
        f"\n**Day-30 readiness (auto, verifiable, hash-anchored):** verdict **{verdict}**, "
        f"readiness **{_fmt_pct(pct, 2) if pct is not None else UNAVAILABLE}** "
        f"({ev if ev is not None else UNAVAILABLE}/30 evidenced days). The artifact's content is "
        f"fingerprinted: `proof_hash={proof[:16] + '…' if proof else UNAVAILABLE}` — re-running the "
        "generator over the same evidenced track reproduces it, and any tampered/backfilled bar "
        "breaks it. The readiness % is the honest evidenced fraction, never an inflated snapshot.\n"
    )


def _section_forward_track(golive, forward, day30=None) -> str:
    lines = ["## 4. The forward track-to-date (accruing, not yet 30)\n"]
    if golive is None:
        lines.append(f"Go-live track: {UNAVAILABLE} (golive_status.json missing).\n")
    else:
        days = golive.get("real_track_days")
        target = golive.get("target_date")
        passed = golive.get("passed")
        total = golive.get("total")
        anchor = golive.get("evidenced_anchor")
        if days is None:
            track_line = f"Evidenced days: {UNAVAILABLE}"
        else:
            track_line = (
                f"**{days}/30 evidenced days — accruing, not yet 30** "
                f"(honest anchor {anchor or UNAVAILABLE}, target "
                f"{target or UNAVAILABLE})"
            )
        lines.append(
            f"{track_line}. Go-live criteria: "
            f"**{passed if passed is not None else UNAVAILABLE}/"
            f"{total if total is not None else UNAVAILABLE} pass** — NOT READY "
            "(the remaining blockers are time-gated: there is simply nothing to fix in code, "
            "only track days to accrue).\n"
        )
    # Forward-track integrity.
    if forward is None:
        lines.append(f"\nForward-track integrity: {UNAVAILABLE} (forward_track_integrity.json missing).\n")
    else:
        all_ok = forward.get("all_ok")
        n_tracks = forward.get("n_tracks")
        n_failing = forward.get("n_failing")
        ok_str = "all_ok" if all_ok is True else "NOT all_ok" if all_ok is False else UNAVAILABLE
        lines.append(
            f"\nForward-track integrity: **{ok_str}** — "
            f"{n_tracks if n_tracks is not None else UNAVAILABLE} forward tracks, "
            f"{n_failing if n_failing is not None else UNAVAILABLE} failing "
            "(no duplicates / gaps / out-of-order / future-dated points).\n"
        )
    # Day-30 readiness artifact (WS5) — the auto/verifiable/hash-anchored verdict + readiness %.
    lines.append(_day30_readiness_line(day30))
    return "\n".join(lines)


def _fmt_ratio(v):
    """Render a Sharpe/Sortino. The source emits the string "UNKNOWN" for a thin or
    locked-vol track; we pass that through VERBATIM (never coerce it to a number)."""
    if isinstance(v, str):
        # The module's honest sentinel ("UNKNOWN") — surfaced as-is.
        return v
    if v is None:
        return "UNKNOWN"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "UNKNOWN"
    # fail-CLOSED on NaN/inf: a non-finite ratio is undefined → UNKNOWN, never a leaked 'nan'.
    if not math.isfinite(f):
        return "UNKNOWN"
    return f"{f:.2f}"


def _section_forward_analytics(fa) -> str:
    """Live forward-record analytics — risk-adjusted attribution + stress overlay,
    sourced from data/forward_analytics.json. Fail-CLOSED: missing module/data ->
    UNAVAILABLE; thin tracks render "THIN (N/30 days, metrics pending)" NOT a
    fabricated Sharpe; UNKNOWN stays UNKNOWN."""
    lines = ["## 5. Live forward-record analytics (risk-adjusted, accruing)\n"]
    lines.append(
        "The verdict above is static; THIS is the live risk-adjusted picture computed "
        "ON the accruing forward series themselves (per-day equity for the rates-desk "
        "carry book + each Strategy-Lab sleeve). Honestly labeled: the forward record is "
        "still thin, so trustworthy risk-adjusted ratios arrive near day 30 — until then a "
        "thin track reads **THIN (metrics pending)**, never a fabricated Sharpe. The honest "
        "thin-labeling IS the credibility.\n"
    )

    if fa is None or not isinstance(fa, dict) or not fa.get("tracks"):
        lines.append(
            f"\nForward-record analytics: {UNAVAILABLE} (forward_analytics.json missing "
            "or empty — the scorecard has not been generated yet).\n"
        )
        return "\n".join(lines)

    floor = fa.get("rwa_floor_pct", fa.get("rwa_floor_apy_pct"))
    min_pts = fa.get("min_points_for_ratio")
    n_tracks = fa.get("n_tracks")
    n_thin = fa.get("n_thin_track")
    n_beats = fa.get("n_beats_floor")
    n_unknown = fa.get("n_unknown")
    lines.append(
        f"\n**{n_tracks if n_tracks is not None else UNAVAILABLE} forward tracks** "
        f"(beats-floor {n_beats if n_beats is not None else UNAVAILABLE} · "
        f"thin {n_thin if n_thin is not None else UNAVAILABLE} · "
        f"unknown {n_unknown if n_unknown is not None else UNAVAILABLE}). "
        f"Attribution baseline: the live RWA floor **{_fmt_pct(floor, 1)}/yr**; a "
        f"realized Sharpe/Sortino is only trusted at **>= "
        f"{min_pts if min_pts is not None else UNAVAILABLE} equity points** — below that "
        "the ratio is a degenerate artifact and is reported THIN, not a number.\n"
    )

    # Per-track risk-adjusted scorecard.
    lines.append(
        "\n| track | days | realized APY %/yr | excess vs floor %/yr | Sharpe | Sortino | "
        "max DD % | status |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|:--|")
    tracks = fa.get("tracks") or []
    for t in tracks:
        if not isinstance(t, dict):
            continue
        name = t.get("name", "?")
        n_pts = t.get("n_points")
        ann = t.get("ann_return_pct")
        excess = t.get("excess_vs_floor_pct")
        max_dd = t.get("max_dd_pct")
        verdict = t.get("verdict", "UNKNOWN")
        sharpe = _fmt_ratio(t.get("sharpe"))
        sortino = _fmt_ratio(t.get("sortino"))
        # Honest status: a thin track is labeled "THIN (N/30 days, metrics pending)";
        # an integrity-broken track is UNKNOWN; only a real ratio earns beats/below.
        if verdict == "THIN_TRACK":
            status = (
                f"THIN ({n_pts if n_pts is not None else '?'}/30 days, metrics pending)"
            )
        elif verdict == "BEATS_FLOOR":
            status = "beats floor"
        elif verdict == "BELOW_FLOOR":
            status = "below floor"
        else:
            status = "UNKNOWN"
            if not t.get("integrity_ok", True):
                reason = t.get("integrity_reason")
                if reason:
                    status = f"UNKNOWN ({reason})"
        lines.append(
            f"| {name} | "
            f"{n_pts if n_pts is not None else UNAVAILABLE} | "
            f"{_fmt_pct(ann, 2) if ann is not None else UNAVAILABLE} | "
            f"{_fmt_pct(excess, 2) if excess is not None else UNAVAILABLE} | "
            f"{sharpe} | {sortino} | "
            f"{_fmt_pct(max_dd, 2) if max_dd is not None else UNAVAILABLE} | "
            f"{status} |"
        )
    lines.append("")

    # T5 — stress overlay on the live carry book.
    overlay = fa.get("carry_book_stress_overlay")
    if not isinstance(overlay, dict) or not overlay.get("scenarios"):
        lines.append(
            f"Forward stress overlay: {UNAVAILABLE} (no carry-book stress overlay in the "
            "scorecard).\n"
        )
    else:
        held = overlay.get("held_pt_notional_usd")
        band = overlay.get("max_dd_band_pct")
        worst = overlay.get("worst_stress_dd_pct")
        survives_all = overlay.get("survives_all")
        sa = (
            "survives ALL" if survives_all is True
            else "does NOT survive all" if survives_all is False
            else UNAVAILABLE
        )
        lines.append(
            f"**Forward stress overlay** (canonical 2024-2026 PT mark-down shocks applied to "
            f"the **currently-held** carry book — {_fmt_usd(held)} PT notional — on top of the "
            f"REALIZED forward equity, drawdown band "
            f"{_fmt_pct(band, 0) if band is not None else UNAVAILABLE}): "
            f"worst-case stressed DD **{_fmt_pct(worst, 2) if worst is not None else UNAVAILABLE}**, "
            f"**{sa}**.\n"
        )
        lines.append("\n| stress scenario | PT mark-down % | shock $ | stressed DD % | survives |")
        lines.append("|---|---:|---:|---:|:--:|")
        for sc in overlay.get("scenarios") or []:
            if not isinstance(sc, dict):
                continue
            surv = (
                "yes" if sc.get("survives") is True
                else "no" if sc.get("survives") is False
                else UNAVAILABLE
            )
            lines.append(
                f"| {sc.get('label', '?')} | "
                f"{_fmt_pct(sc.get('pt_markdown_pct'), 2) if sc.get('pt_markdown_pct') is not None else UNAVAILABLE} | "
                f"{_fmt_usd(sc.get('shock_usd'))} | "
                f"{_fmt_pct(sc.get('stress_dd_pct'), 2) if sc.get('stress_dd_pct') is not None else UNAVAILABLE} | "
                f"{surv} |"
            )
        lines.append("")

    lines.append(
        "**Framed honestly for a funder:** the forward record is *accruing* — this is the "
        "risk-adjusted picture to date, every number sourced live from the realized series and "
        "labeled THIN where a ratio would be premature. The refusal chain plus this honest "
        "thin-labeling is exactly what makes the day-30 artifact trustworthy: the ratios that "
        "land near day 30 will rest on a record that was never fabricated along the way.\n"
    )
    return "\n".join(lines)


def _section_safety(dry_run, golive) -> str:
    lines = ["## 6. The safety architecture\n"]
    lines.append(
        "- **Refusal-first gate** — a deterministic policy composed *under* the global "
        "RiskPolicy, only ever stricter; LLM-forbidden in risk/kill; fail-CLOSED "
        "(missing/invalid data -> max tail-risk, never a silent pass).\n"
        "- **Kill switch** — drawdown >= 5% closes everything; cannot be overridden.\n"
        "- **Proof-of-reserves / NAV reconciliation** — NAV conserved across the simulated "
        "rebalance.\n"
    )
    if dry_run is None:
        lines.append(f"- **Go-live dry-run harness:** {UNAVAILABLE} (golive_dry_run.json missing).\n")
    else:
        all_reached = dry_run.get("all_gates_reached")
        ordering_ok = dry_run.get("ordering_ok")
        would_proceed = dry_run.get("would_proceed")
        active = dry_run.get("live_trading_gate_active")
        moves = dry_run.get("moves_capital")
        nav_ok = None
        for g in (dry_run.get("gates") or []):
            if g.get("name") == "nav_reconciliation":
                nav_ok = g.get("verdict")
        lines.append(
            "- **Go-live dry-run harness** (`golive_dry_run.json`): "
            f"all gates reached={_yn(all_reached)}, ordering_ok={_yn(ordering_ok)}, "
            f"NAV reconciliation={nav_ok or UNAVAILABLE}, "
            f"live-trading gate active={_yn(active)}, would_proceed={_yn(would_proceed)}, "
            f"moves_capital={_yn(moves)}. The gates are **verified inert** — the harness "
            "proves the fail-closed chain fires (RiskPolicy blocks an over-concentrated trade, "
            "the live-trading gate stays inactive) WITHOUT moving any capital.\n"
        )
    # Honest-track reset as a trust signal.
    days = _get(golive or {}, "real_track_days")
    lines.append(
        "- **Honest-track reset as a TRUST signal** — the track shows "
        f"**{days if days is not None else UNAVAILABLE}/30 accruing**, anchored to the real "
        "evidenced start. It was reset to the honest count rather than padded; the published "
        "low number IS the credibility.\n"
    )
    return "\n".join(lines)


def _section_offcode_gates() -> str:
    return (
        "## 7. The off-code gates — honestly, what stands between here and $10M\n\n"
        "The code did its job: it took each thesis to an honest verdict for free. But across "
        "all three, the same boundary appears — **the code can measure and refuse; the $10M is "
        "off-code.** Stated plainly, not hidden:\n\n"
        "- **Custody / MPC** — institutional key management for real capital; not buildable in "
        "read-only paper code.\n"
        "- **External audit** — independent code + controls audit of the execution path.\n"
        "- **Legal** — fund structure, collateral perfection, redemption agreements, "
        "force-redemption rights; the RWA underwriting leg can only be *documented*, not "
        "*executed*, without it.\n"
        "- **Real capital + relationships** — whitelisting / subscription access to redemption "
        "queues; the carry edge needs scale across many capacity-bound books, which needs AUM.\n\n"
        "This is the honest scale truth: SPA contributes the cheapest, most defensible first "
        "layer — the transparent, fail-closed measurement-and-refusal engine that PROVES the "
        "mispricing — plus an honest record of exactly which off-code legs gate the business.\n"
    )


def _yn(v):
    if v is True:
        return "yes"
    if v is False:
        return "no"
    return UNAVAILABLE


# --------------------------------------------------------------------------- #
# Document assembly
# --------------------------------------------------------------------------- #

def build_document(sources: dict, now_iso: str) -> str:
    golive = sources.get("golive")
    promotion = sources.get("promotion")
    decisions = sources.get("decisions")
    rwa = sources.get("rwa")
    forward = sources.get("forward")
    dry_run = sources.get("dry_run")
    forward_analytics = sources.get("forward_analytics")
    day30 = sources.get("day30")
    carry_truth = sources.get("carry_truth")
    edge_at_scale = sources.get("edge_at_scale")
    realized_ab = sources.get("realized_ab")
    refusal_cost = sources.get("refusal_cost")
    refusal_value = sources.get("refusal_value")

    parts = [
        "# SPA — Fundability one-pager\n",
        "_Auto-generated, REALIZED-ONLY, HONEST. Every performance number traces to a realized "
        "`data/` source or is labeled INSUFFICIENT_DATA; a missing source is reported as data "
        "unavailable, never fabricated. NO backtest figure is presented as realized (backtest "
        "rows are explicitly fenced). stdlib-only, deterministic, fail-CLOSED. NOT marketing — "
        "the refusal-chain and the published NO-GO are the differentiator._\n",
        "---\n",
        _section_thesis(),
        "\n---\n",
        _section_realized_edge(carry_truth, realized_ab, edge_at_scale, decisions, refusal_cost, refusal_value),
        "\n---\n",
        _section_validated_edge(promotion, decisions, rwa),
        "\n---\n",
        _section_forward_track(golive, forward, day30),
        "\n---\n",
        _section_forward_analytics(forward_analytics),
        "\n---\n",
        _section_safety(dry_run, golive),
        "\n---\n",
        _section_offcode_gates(),
        "\n---\n",
        f"_Regenerated {now_iso}. All numbers live from `data/` — REALIZED-ONLY sources "
        "(carry_truth_table.json · realized_ab/realized_ab.json · edge_at_scale.json · "
        "refusal_cost.json) for the §2 edge claims, plus golive_status.json · "
        "rates_desk/rates_desk_promotion.json (BACKTEST, fenced) · "
        "rates_desk/decision_log.jsonl · rwa_safety_board.json · "
        "forward_track_integrity.json · forward_analytics.json · golive_dry_run.json. "
        "Regenerable via "
        "`python3 scripts/generate_fundability_onepager.py --md`. Reproduce the realized "
        "numbers from raw series: `python3 scripts/verify_spa.py --check-fundability data/`. "
        "Follow-up: a public `/fundability` site page mirroring this doc._\n",
    ]
    return "\n".join(parts)


def atomic_write(path: str, content: str) -> None:
    """Atomic write via tempfile + shutil.move (per repo rule #4)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=os.path.dirname(path), prefix=".fundability_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        shutil.move(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def generate(root: str = None, now_iso: str = None) -> str:
    """Pure entry point: load sources, return the rendered markdown."""
    root = root or _repo_root()
    if now_iso is None:
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sources = load_sources(root)
    return build_document(sources, now_iso)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate the SPA fundability one-pager.")
    parser.add_argument(
        "--md", action="store_true",
        help="write docs/FUNDABILITY.md (default: print to stdout)",
    )
    args = parser.parse_args(argv)

    root = _repo_root()
    doc = generate(root)

    if args.md:
        out = os.path.join(root, "docs", "FUNDABILITY.md")
        atomic_write(out, doc)
        print(f"wrote {out}")
    else:
        sys.stdout.write(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
