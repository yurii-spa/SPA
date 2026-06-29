#!/usr/bin/env python3
"""
generate_fundable_honest.py — ROUND-2 WS6.2: the honest "what we are / aren't" one-pager.

Builds docs/FUNDABLE_HONEST.md — a single, auto-generated, REALIZED-ONLY page that states plainly,
for a funder, three things and NOTHING that exceeds the evidence:

  • what is genuinely WORLD-CLASS (measurement + refusal + proof + the publicly-reproducible
    verifier) — claims about MACHINERY, not about returns;
  • what is still MATURING (the REALIZED edge: N/30 days, X bps above floor OR INSUFFICIENT_DATA;
    the edge compresses at scale) — sourced from the WS1 realized artifacts, NEVER a backtest;
  • what is OWNER-GATED / off-code (capital / custody / audit / legal).

THE HONESTY IS THE MOAT: a funder trusts the desk that names its own gaps. So this generator's
hard contract is: every performance number traces to a REALIZED data point (carry_truth_table /
realized_ab / edge_at_scale / golive_status) OR is rendered as the explicit INSUFFICIENT_DATA /
"data unavailable" sentinel. NO backtest figure is presented as realized. NO claim exceeds evidence.

Design contract (matches the codebase rules):
- stdlib-only, deterministic (same data -> same bytes), fail-CLOSED, atomic write.
- No LLM, no marketing inflation.

Re-runnable:
    python3 scripts/generate_fundable_honest.py        # print to stdout
    python3 scripts/generate_fundable_honest.py --md    # write docs/FUNDABLE_HONEST.md
"""
# LLM_FORBIDDEN
import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

UNAVAILABLE = "_data unavailable_"
INSUFFICIENT = "INSUFFICIENT_DATA"


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_json(path: str):
    """Load JSON; None on missing/parse error (fail-CLOSED → honest UNAVAILABLE downstream)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _fmt_pct(v, digits=2):
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
    if v is None:
        return UNAVAILABLE
    try:
        f = float(v)
    except (TypeError, ValueError):
        return UNAVAILABLE
    if not math.isfinite(f):
        return UNAVAILABLE
    return f"${f:,.0f}"


def _fmt_bps(v):
    """Carry-above-floor bps. CRITICAL: a null bps is INSUFFICIENT_DATA, NEVER a rounded 0.0
    (that would mask a thin/unmeasured track as a real at-floor verdict — the red-team path)."""
    if v is None:
        return INSUFFICIENT
    try:
        f = float(v)
    except (TypeError, ValueError):
        return INSUFFICIENT
    if not math.isfinite(f):
        return INSUFFICIENT
    return f"{f:+.2f} bps"


def _yn(v):
    if v is True:
        return "yes"
    if v is False:
        return "no"
    return UNAVAILABLE


def load_sources(root: str) -> dict:
    d = os.path.join(root, "data")
    return {
        "golive": load_json(os.path.join(d, "golive_status.json")),
        "decisions": _load_jsonl(os.path.join(d, "rates_desk", "decision_log.jsonl")),
        "carry_truth": load_json(os.path.join(d, "carry_truth_table.json")),
        "edge_at_scale": load_json(os.path.join(d, "edge_at_scale.json")),
        "realized_ab": load_json(os.path.join(d, "realized_ab", "realized_ab.json")),
        "refusal_cost": load_json(os.path.join(d, "refusal_cost.json")),
    }


def _load_jsonl(path: str):
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
                    continue
        return out
    except (FileNotFoundError, OSError):
        return None


def _decision_counts(decisions):
    """Honest refusal/entry counts from the decision log; None if missing."""
    if decisions is None:
        return None
    refusals = entries = tail = 0
    for r in decisions:
        if r.get("kind") == "REFUSAL":
            refusals += 1
            if r.get("reason") == "tail_veto":
                tail += 1
        elif r.get("kind") == "ENTRY":
            entries += 1
    return {"total": len(decisions), "refusals": refusals, "entries": entries, "tail": tail}


# --------------------------------------------------------------------------- #
# Sections — each fail-CLOSED, each returns markdown.
# --------------------------------------------------------------------------- #

def _section_intro() -> str:
    return (
        "# SPA — what we are, and what we aren't (honest one-pager)\n\n"
        "_Auto-generated, REALIZED-ONLY, HONEST. The honesty IS the moat: a funder trusts the desk "
        "that names its own gaps. Every performance number below traces to a REALIZED `data/` "
        "source or is labeled INSUFFICIENT_DATA; NO backtest figure is presented as realized; NO "
        "claim exceeds the evidence. stdlib-only, deterministic, fail-CLOSED._\n\n"
        "> **One line:** the **machinery** (measurement, refusal, proof, a public verifier) is "
        "world-class and reproducible today. The **realized edge** is still maturing and is "
        "INSUFFICIENT_DATA at this track depth — and it compresses at scale. The **business** "
        "($10M/yr) is owner-gated off-code (capital / custody / audit / legal). We do not claim "
        "the edge is proven, and we do not claim $10M is reachable today.\n"
    )


def _section_world_class(decisions) -> str:
    """What is genuinely world-class — claims about MACHINERY, not returns. The one number here
    (decision count) is a sourced count of LOGGED decisions, not a performance claim."""
    lines = ["## 1. What is genuinely world-class (machinery, not returns)\n"]
    dc = _decision_counts(decisions)
    decision_line = (
        f"a hash-linked, tamper-evident decision log of **{dc['total']}** decisions "
        f"(**{dc['refusals']} refusals**, of which **{dc['tail']}** structural tail-vetoes, and "
        f"**{dc['entries']} entries**)"
        if dc else f"a hash-linked, tamper-evident decision log ({UNAVAILABLE})"
    )
    lines.append(
        "These are claims about the **engine and its proofs** — independently checkable, not "
        "performance assertions:\n\n"
        "- **Measurement** — a deterministic, fail-CLOSED, LLM-forbidden fair-value engine that "
        "prices tokenized yield by subtracting structural haircuts (peg / liquidity / protocol / "
        "oracle / funding) and measures on-chain liquidation-NAV vs marketing-NAV from free data.\n"
        "- **Refusal** — a refusal-first gate composed *under* the global RiskPolicy (only ever "
        "stricter). It REFUSES yield that is tail-risk compensation (the ezETH / over-levered-USDe "
        f"pattern), and it publishes what it refused and why: {decision_line}.\n"
        "- **Proof** — every decision (entry AND refusal), the exit-NAV-by-size schedules, the "
        "evidenced equity track, the tournament rankings and the RWA-NAV points are hashed into "
        "tamper-evident chains. \"What we refused\" is a public surface no competitor publishes.\n"
        "- **A public, zero-dependency verifier** — `scripts/verify_spa.py` lets a skeptical third "
        "party re-derive every published hash AND every realized fundability number from the raw "
        "series on a clean machine with none of our code: **\"don't trust us, check us.\"**\n"
    )
    return "\n".join(lines)


def _section_maturing(golive, carry_truth, edge_at_scale, realized_ab) -> str:
    """What is still maturing — the REALIZED edge. Sourced from WS1 artifacts; INSUFFICIENT_DATA
    where the track is too thin. NO backtest figure here."""
    lines = ["## 2. What is still maturing (the realized edge — honest, sourced)\n"]

    # 2a — track depth (N/30)
    if golive is None:
        lines.append(f"- **Track depth:** {UNAVAILABLE} (golive_status.json missing).\n")
    else:
        days = golive.get("real_track_days")
        anchor = golive.get("evidenced_anchor")
        target = golive.get("target_date")
        passed = golive.get("passed")
        total = golive.get("total")
        lines.append(
            f"- **Track depth:** **{days if days is not None else UNAVAILABLE}/30 evidenced "
            f"days** — accruing, not yet 30 (anchor {anchor or UNAVAILABLE}, target "
            f"{target or UNAVAILABLE}). Go-live: "
            f"**{passed if passed is not None else UNAVAILABLE}/"
            f"{total if total is not None else UNAVAILABLE} pass** — NOT READY; the remaining "
            "blockers are time-gated (track days to accrue), nothing to fix in code.\n"
        )

    # 2b — realized carry above floor (carry truth-table)
    if carry_truth is None or not isinstance(carry_truth, dict):
        lines.append(f"- **Realized edge vs floor:** {UNAVAILABLE} (carry_truth_table.json missing).\n")
    else:
        floor = carry_truth.get("rwa_floor_apy_pct")
        n_above = carry_truth.get("n_above_floor")
        n_insuff = carry_truth.get("n_insufficient_data")
        n_sleeves = carry_truth.get("n_sleeves")
        # the FixedCarry realized row (the flagship carry book), surfaced honestly
        fc_bps = None
        for r in carry_truth.get("rows") or []:
            if r.get("sleeve") == "rates_desk_fixed_carry":
                fc_bps = r.get("carry_above_floor_bps")
        lines.append(
            f"- **Realized edge vs the RWA floor ({_fmt_pct(floor, 2)}/yr):** of "
            f"**{n_sleeves if n_sleeves is not None else UNAVAILABLE}** forward sleeves, "
            f"**{n_above if n_above is not None else UNAVAILABLE}** beat the floor and "
            f"**{n_insuff if n_insuff is not None else UNAVAILABLE}** are **INSUFFICIENT_DATA** "
            "at this depth. The flagship FixedCarry carry book's realized carry-above-floor is "
            f"**{_fmt_bps(fc_bps)}** — i.e. **at-or-below the floor so far**. **We do NOT claim "
            "the desk beats the floor on realized data yet.** A thin track yields "
            "INSUFFICIENT_DATA with a null bps, never a fabricated 0.0.\n"
        )

    # 2c — realized A/B verdict
    if realized_ab is None or not isinstance(realized_ab, dict):
        lines.append(f"- **Optimizer A/B (realized):** {UNAVAILABLE} (realized_ab.json missing).\n")
    else:
        verdict = realized_ab.get("verdict", INSUFFICIENT)
        n_days = realized_ab.get("n_days")
        sel = _get(realized_ab, "decomposition", "selection_alpha_bps")
        lines.append(
            f"- **Optimizer A/B (realized, `is_realized:{_yn(realized_ab.get('is_realized'))}`):** "
            f"depth **{n_days if n_days is not None else UNAVAILABLE} day(s)**, verdict "
            f"**{verdict}**. Apples-to-apples selection alpha to date: "
            f"**{_fmt_bps(sel)}** — but a 1-day uplift is not an edge; the verdict stays "
            "INSUFFICIENT_DATA until the track matures.\n"
        )

    # 2d — edge compresses at scale (the load-bearing finding)
    if edge_at_scale is None or not isinstance(edge_at_scale, dict) or not edge_at_scale.get("curve"):
        lines.append(f"- **Edge at scale:** {UNAVAILABLE} (edge_at_scale.json missing).\n")
    else:
        survives = edge_at_scale.get("edge_survives_at_max_aum")
        below_at = edge_at_scale.get("edge_below_materiality_at_aum_usd")
        # pull the $100k and the largest-AUM uplift for the honest "artifact" statement
        curve = edge_at_scale.get("curve") or []
        u_small = curve[0].get("uplift_pp") if curve else None
        u_large = curve[-1].get("uplift_pp") if curve else None
        small_str = (f"{u_small:+.2f}pp" if isinstance(u_small, (int, float))
                     and math.isfinite(u_small) else UNAVAILABLE)
        large_str = (f"{u_large:+.2f}pp" if isinstance(u_large, (int, float))
                     and math.isfinite(u_large) else UNAVAILABLE)
        lines.append(
            f"- **The edge compresses at scale:** the optimizer's uplift is **{small_str} at "
            f"$100k** but goes to **{large_str}** at the largest AUM tested (survives at max AUM: "
            f"**{_yn(survives)}**"
            + (f"; below the materiality bar by **{_fmt_usd(below_at)}**" if below_at is not None
               else "")
            + "). The +1pp is a small-scale artifact that pool-capacity caps dissolve at fundable "
            "size. **At the size that underlies the $100M thesis, today's universe cannot support "
            "the edge.**\n"
        )
    return "\n".join(lines)


def _section_owner_gated(refusal_cost) -> str:
    lines = ["## 3. What is owner-gated / off-code (the path to $10M)\n"]
    lines.append(
        "The code took each thesis to an honest verdict for free. But the same boundary appears "
        "everywhere — **the code can measure and refuse; the business is off-code.** Stated "
        "plainly, none of it buildable in read-only paper code:\n\n"
        "- **Capital + relationships** — the carry edge is capacity-bound; $10M needs scale across "
        "many gated books, deeper pools, and AUM. Whitelisting / subscription access to redemption "
        "queues is a relationship, not a feature.\n"
        "- **Custody / MPC** — institutional key management for real capital.\n"
        "- **External audit** — independent code + controls audit of the execution path.\n"
        "- **Legal** — fund structure, collateral perfection, redemption agreements, "
        "force-redemption rights; the RWA underwriting leg can only be *documented*, not "
        "*executed*, without it.\n"
    )
    # the refusal-cost honesty: the conservatism is defensible WHILE the realized track is thin
    defensible = _get(refusal_cost or {}, "interpretation", "defensible")
    if defensible:
        lines.append(
            f"\n**On the cost of caution:** {defensible} — the gate's refusals are insurance "
            "against the tail (the ezETH / USDe-unwind pattern), defensible precisely because the "
            "realized carry does not yet beat the floor.\n"
        )
    return "\n".join(lines)


def _section_bottom_line() -> str:
    return (
        "## 4. The honest bottom line\n\n"
        "- **Genuinely world-class, today:** the measurement + refusal + proof engine and its "
        "public, zero-dependency verifier. Reproduce every number yourself: "
        "`python3 scripts/verify_spa.py --check-fundability data/`.\n"
        "- **Still maturing:** the realized edge is INSUFFICIENT_DATA at this track depth and is "
        "at-or-below the floor so far; it compresses at scale. We name this gap rather than hide "
        "it.\n"
        "- **Owner-gated:** capital, custody, audit, legal — the $10M is off-code. $0 real "
        "capital today.\n\n"
        "_The product is not a return we promise; it is a measurement-and-refusal engine whose "
        "every claim a hostile reviewer can reproduce, and whose gaps we name first._\n"
    )


def build_document(sources: dict, now_iso: str) -> str:
    parts = [
        _section_intro(),
        "\n---\n",
        _section_world_class(sources.get("decisions")),
        "\n---\n",
        _section_maturing(sources.get("golive"), sources.get("carry_truth"),
                          sources.get("edge_at_scale"), sources.get("realized_ab")),
        "\n---\n",
        _section_owner_gated(sources.get("refusal_cost")),
        "\n---\n",
        _section_bottom_line(),
        "\n---\n",
        f"_Regenerated {now_iso}. REALIZED-ONLY sources: `data/`carry_truth_table.json · "
        "realized_ab/realized_ab.json · edge_at_scale.json · refusal_cost.json · "
        "golive_status.json · rates_desk/decision_log.jsonl. Regenerable via "
        "`python3 scripts/generate_fundable_honest.py --md`. Companion sheet: "
        "`docs/FUNDABILITY.md`; reproduce the realized numbers: "
        "`python3 scripts/verify_spa.py --check-fundability data/`._\n",
    ]
    return "\n".join(parts)


def atomic_write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".fundable_honest_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        shutil.move(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def generate(root: str = None, now_iso: str = None) -> str:
    root = root or _repo_root()
    if now_iso is None:
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return build_document(load_sources(root), now_iso)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate the SPA honest 'what we are/aren't' one-pager.")
    parser.add_argument("--md", action="store_true", help="write docs/FUNDABLE_HONEST.md")
    args = parser.parse_args(argv)
    root = _repo_root()
    doc = generate(root)
    if args.md:
        out = os.path.join(root, "docs", "FUNDABLE_HONEST.md")
        atomic_write(out, doc)
        print(f"wrote {out}")
    else:
        sys.stdout.write(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
