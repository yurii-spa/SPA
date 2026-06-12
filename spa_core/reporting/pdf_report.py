#!/usr/bin/env python3
"""MP-103: Investor PDF daily report generator.

Reads (all optional — missing file → graceful degradation, never raises):
  data/daily_report_{date}.json
  data/analytics_summary.json
  data/golive_status.json
  data/adapter_orchestrator_status.json
  data/paper_trading_status.json
  data/equity_curve_daily.json

Generates:
  data/reports/investor_report_{date}.pdf

Requires reportlab (pip3 install reportlab --break-system-packages).
Stdlib-only data-loading; reportlab used ONLY for PDF rendering.
All file writes are atomic (tmpfile + os.replace).

CLI::

    python3 -m spa_core.reporting.pdf_report               # today
    python3 -m spa_core.reporting.pdf_report 2026-06-10    # specific date
    python3 -m spa_core.reporting.pdf_report --latest      # latest daily_report_*.json
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("spa.pdf_report")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

BENCHMARK_APY_PCT = 5.0  # 5% per year benchmark


# ─── IO helpers (stdlib only, mirrors cycle_runner conventions) ──────────────


def _read_json(path: Path, default: Any) -> Any:
    """Read JSON defensively. Missing/corrupt file → default (never raises)."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("%s unreadable (%s) — using default", path.name, exc)
        return default


# ─── Pure data helpers ────────────────────────────────────────────────────────


def _period_return_pct(bars: list, n_days: int) -> float | None:
    """Compute compounded return for last n_days from equity bars.

    Returns None when there is insufficient data (< 2 bars or no values).
    """
    if not bars or len(bars) < 1:
        return None
    window = bars[-min(n_days, len(bars)):]
    if not window:
        return None
    # open_equity of the first bar in the window vs close of the last bar
    start = (
        window[0].get("open_equity")
        or window[0].get("close_equity")
        or window[0].get("equity")
    )
    end = window[-1].get("close_equity") or window[-1].get("equity")
    try:
        s = float(start)
        e = float(end)
        if s > 0 and e >= 0:
            return (e / s - 1.0) * 100.0
    except (TypeError, ValueError):
        pass
    return None


def _benchmark_return_pct(n_days: int) -> float:
    """Return n_days of 5% APY benchmark (compound)."""
    return ((1.0 + BENCHMARK_APY_PCT / 100.0) ** (n_days / 365.0) - 1.0) * 100.0


def _fmt_pct(val: float | None, ndigits: int = 4, plus: bool = True) -> str:
    """Format a percentage value, e.g. '+0.0086%' or '—'."""
    if val is None:
        return "—"  # em dash
    sign = "+" if plus and val >= 0 else ""
    return f"{sign}{val:.{ndigits}f}%"


def _fmt_usd(val: float | None, sign: bool = True) -> str:
    """Format a USD value, e.g. '$100,008.61'."""
    if val is None:
        return "—"
    if sign and val > 0:
        return f"+${val:,.2f}"
    elif sign and val < 0:
        return f"-${abs(val):,.2f}"
    return f"${val:,.2f}"


def _golive_checks(golive: dict) -> list[tuple[bool, str, str]]:
    """Return list of (passed, key, label) for the 6 GoLive criteria."""
    _labels = {
        "equity_curve_real": "Equity curve real (not demo)",
        "trades_real": "Real trades recorded (is_demo:false)",
        "status_real": "Status file real (is_demo:false)",
        "no_demo_data": "No demo data in any source file",
        "data_fresh_48h": "Data freshness < 48 hours",
        "cycle_runner_exists": "Cycle runner module present",
    }
    checks = golive.get("checks") if isinstance(golive, dict) else {}
    if not isinstance(checks, dict):
        checks = {}
    return [
        (bool(checks.get(key, False)), key, label)
        for key, label in _labels.items()
    ]


def _load_report_context(date_str: str, data_dir: Path) -> dict:
    """Load all JSON sources for the PDF. Every read is defensive (never raises)."""
    daily = _read_json(data_dir / f"daily_report_{date_str}.json", {})
    analytics = _read_json(data_dir / "analytics_summary.json", {})
    golive = _read_json(data_dir / "golive_status.json", {})
    orch = _read_json(data_dir / "adapter_orchestrator_status.json", {})
    status = _read_json(data_dir / "paper_trading_status.json", {})
    equity_doc = _read_json(data_dir / "equity_curve_daily.json", {})

    # Coerce missing/corrupt files to empty dicts
    return {
        "date_str": date_str,
        "daily": daily if isinstance(daily, dict) else {},
        "analytics": analytics if isinstance(analytics, dict) else {},
        "golive": golive if isinstance(golive, dict) else {},
        "orch": orch if isinstance(orch, dict) else {},
        "status": status if isinstance(status, dict) else {},
        "equity_doc": equity_doc if isinstance(equity_doc, dict) else {},
    }


# ─── PDF builder (reportlab) ─────────────────────────────────────────────────


def _build_pdf(ctx: dict, output_path: Path) -> None:  # noqa: C901 (long but linear)
    """Build the investor PDF from context dict to output_path.

    Raises ImportError if reportlab is not installed.
    Raises any reportlab exception on rendering failure.
    """
    # Local imports — reportlab is an optional dependency for the runtime cycle;
    # import it only here so the rest of the module stays pure stdlib.
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    date_str = ctx["date_str"]
    daily = ctx["daily"]
    analytics = ctx["analytics"]
    golive = ctx["golive"]
    orch = ctx["orch"]
    status = ctx["status"]
    equity_doc = ctx["equity_doc"]

    # ── Color palette ────────────────────────────────────────────────────────
    NAVY = colors.HexColor("#1a2744")
    TEAL = colors.HexColor("#1a7a7a")
    LIGHT_BLUE = colors.HexColor("#e8f4f8")
    LIGHT_BLUE2 = colors.HexColor("#f0f8fc")
    LIGHT_GRAY = colors.HexColor("#f5f5f5")
    MID_GRAY = colors.HexColor("#dddddd")
    DIM_GRAY = colors.HexColor("#cccccc")
    DARK_GRAY = colors.HexColor("#333333")
    LABEL_GRAY = colors.HexColor("#666666")
    GREEN = colors.HexColor("#1a7a3a")
    RED = colors.HexColor("#c0392b")
    GOLD = colors.HexColor("#c9a227")
    PALE_YELLOW = colors.HexColor("#fffde7")
    ALICE_BLUE = colors.HexColor("#d0e8f0")
    WHITE = colors.white

    # ── Style helpers ────────────────────────────────────────────────────────
    def _s(name, **kw) -> ParagraphStyle:
        return ParagraphStyle(name, **kw)

    s_hdr_title = _s("hdr_title", fontName="Helvetica-Bold", fontSize=20,
                     textColor=WHITE, alignment=TA_CENTER, leading=26, spaceAfter=2)
    s_hdr_sub = _s("hdr_sub", fontName="Helvetica", fontSize=11,
                   textColor=colors.HexColor("#a0c4d8"),
                   alignment=TA_CENTER, leading=14, spaceAfter=1)
    s_hdr_tag = _s("hdr_tag", fontName="Helvetica-Bold", fontSize=9,
                   textColor=GOLD, alignment=TA_CENTER, leading=12)
    s_section = _s("section", fontName="Helvetica-Bold", fontSize=12,
                   textColor=NAVY, spaceBefore=10, spaceAfter=4, leading=16)
    s_metric_val = _s("metric_val", fontName="Helvetica-Bold", fontSize=18,
                      textColor=NAVY, alignment=TA_CENTER, leading=22)
    s_metric_pos = _s("metric_pos", fontName="Helvetica-Bold", fontSize=16,
                      textColor=GREEN, alignment=TA_CENTER, leading=20)
    s_metric_neg = _s("metric_neg", fontName="Helvetica-Bold", fontSize=16,
                      textColor=RED, alignment=TA_CENTER, leading=20)
    s_metric_lbl = _s("metric_lbl", fontName="Helvetica", fontSize=8,
                      textColor=LABEL_GRAY, alignment=TA_CENTER, leading=10)
    s_tbl_hdr = _s("tbl_hdr", fontName="Helvetica-Bold", fontSize=9,
                   textColor=WHITE, alignment=TA_CENTER, leading=12)
    s_tbl_bold = _s("tbl_bold", fontName="Helvetica-Bold", fontSize=9,
                    textColor=DARK_GRAY, alignment=TA_LEFT, leading=12)
    s_tbl_ctr = _s("tbl_ctr", fontName="Helvetica", fontSize=9,
                   textColor=DARK_GRAY, alignment=TA_CENTER, leading=12)
    s_tbl_left = _s("tbl_left", fontName="Helvetica", fontSize=9,
                    textColor=DARK_GRAY, alignment=TA_LEFT, leading=12)
    s_pass = _s("pass", fontName="Helvetica-Bold", fontSize=9,
                textColor=GREEN, alignment=TA_CENTER, leading=12)
    s_fail = _s("fail", fontName="Helvetica-Bold", fontSize=9,
                textColor=RED, alignment=TA_CENTER, leading=12)
    s_footer = _s("footer", fontName="Helvetica", fontSize=7,
                  textColor=colors.HexColor("#999999"), alignment=TA_CENTER, leading=10)
    s_disclaimer = _s("disclaimer", fontName="Helvetica-Oblique", fontSize=8,
                      textColor=colors.HexColor("#888888"), alignment=TA_CENTER, leading=11)

    # ── Document ─────────────────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2.0 * cm, rightMargin=2.0 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title=f"SPA Investor Report {date_str}",
        author="SPA — Smart Passive Aggregator",
        subject="Paper Trading Daily Report",
    )
    pw = A4[0] - 4.0 * cm  # usable page width

    story = []

    # ══════════════════════════════════════════════════════════════════════════
    # HEADER
    # ══════════════════════════════════════════════════════════════════════════
    hdr_rows = [
        [Paragraph("SPA — Smart Passive Aggregator", s_hdr_title)],
        [Paragraph(f"Daily Report &nbsp; {date_str}", s_hdr_sub)],
        [Paragraph("PAPER TRADING &nbsp;|&nbsp; CONFIDENTIAL", s_hdr_tag)],
    ]
    hdr_tbl = Table(hdr_rows, colWidths=[pw])
    hdr_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("TOPPADDING", (0, 0), (-1, 0), 14),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 14),
        ("TOPPADDING", (0, 1), (-1, 1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 2), (-1, 2), 3),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(hdr_tbl)
    story.append(Spacer(1, 0.35 * cm))

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — KEY METRICS
    # ══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("KEY METRICS", s_section))
    story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=5))

    equity = daily.get("equity_usd") or status.get("current_equity")
    pnl_usd = daily.get("daily_pnl_usd")
    pnl_pct = daily.get("daily_pnl_pct")
    total_return = daily.get("total_return_pct")

    eq_str = f"${float(equity):,.2f}" if isinstance(equity, (int, float)) else "—"

    if isinstance(pnl_usd, (int, float)):
        sgn = "+" if float(pnl_usd) >= 0 else ""
        pnl_str = f"{sgn}${abs(float(pnl_usd)):,.2f}"
        if isinstance(pnl_pct, (int, float)):
            sgn2 = "+" if float(pnl_pct) >= 0 else ""
            pnl_str += f"<br/>({sgn2}{float(pnl_pct):.4f}%)"
    else:
        pnl_str = "—"

    if isinstance(total_return, (int, float)):
        sgn = "+" if float(total_return) >= 0 else ""
        tr_str = f"{sgn}{float(total_return):.4f}%"
    else:
        tr_str = "—"

    checks_dict = golive.get("checks") if isinstance(golive, dict) else {}
    if not isinstance(checks_dict, dict):
        checks_dict = {}
    passed_n = sum(1 for v in checks_dict.values() if v)
    total_n = max(len(checks_dict), 6)
    is_ready = bool(golive.get("ready", False)) if isinstance(golive, dict) else False
    golive_str = "READY" if is_ready else f"PRE-LIVE {passed_n}/{total_n}"

    # Style selection for P&L
    pnl_style = s_metric_pos if isinstance(pnl_usd, (int, float)) and float(pnl_usd) >= 0 else s_metric_neg
    tr_style = s_metric_pos if isinstance(total_return, (int, float)) and float(total_return) >= 0 else s_metric_neg

    km_data = [
        [
            Paragraph(eq_str, s_metric_val),
            Paragraph(pnl_str, pnl_style),
            Paragraph(tr_str, tr_style),
            Paragraph(golive_str, s_metric_val),
        ],
        [
            Paragraph("Total Equity", s_metric_lbl),
            Paragraph("P&amp;L Today", s_metric_lbl),
            Paragraph("Total Return", s_metric_lbl),
            Paragraph("Go-Live Status", s_metric_lbl),
        ],
    ]
    cw = pw / 4
    km_tbl = Table(km_data, colWidths=[cw] * 4)
    km_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BLUE),
        ("BACKGROUND", (0, 1), (-1, 1), ALICE_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#a0c4d8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#a0c4d8")),
        ("TOPPADDING", (0, 0), (-1, 0), 12),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 1), (-1, 1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(km_tbl)
    story.append(Spacer(1, 0.35 * cm))

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — PERFORMANCE BY PERIOD
    # ══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("PERFORMANCE BY PERIOD", s_section))
    story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=5))

    bars = [b for b in (equity_doc.get("daily") or []) if isinstance(b, dict)]

    def _period_row(label: str, n_days: int, ret: float | None) -> list:
        bench = _benchmark_return_pct(n_days)
        if ret is None:
            return [
                Paragraph(label, s_tbl_bold),
                Paragraph("—", s_tbl_ctr),
                Paragraph("—", s_tbl_ctr),
            ]
        alpha = ret - bench
        alpha_str = _fmt_pct(alpha, plus=True) + " alpha"
        return [
            Paragraph(label, s_tbl_bold),
            Paragraph(_fmt_pct(ret, plus=True), s_tbl_ctr),
            Paragraph(alpha_str, s_tbl_ctr),
        ]

    # Today: last bar's daily_return_pct
    today_ret: float | None = None
    if bars:
        lb = bars[-1]
        dr = lb.get("daily_return_pct")
        if isinstance(dr, (int, float)):
            today_ret = float(dr)
        elif lb.get("close_equity") and lb.get("open_equity"):
            c, o = float(lb["close_equity"]), float(lb["open_equity"])
            today_ret = (c / o - 1) * 100 if o > 0 else 0.0
    elif isinstance(pnl_pct, (int, float)):
        today_ret = float(pnl_pct)

    week_ret = _period_return_pct(bars, 7)
    month_ret = _period_return_pct(bars, 30)

    # All-time return
    all_time_ret: float | None = None
    if isinstance(equity_doc.get("summary"), dict):
        all_time_ret = equity_doc["summary"].get("total_return_pct")
        if isinstance(all_time_ret, (int, float)):
            all_time_ret = float(all_time_ret)
        else:
            all_time_ret = None
    if all_time_ret is None and isinstance(total_return, (int, float)):
        all_time_ret = float(total_return)
    n_all = max(len(bars), 1)

    perf_data = [
        [Paragraph("Period", s_tbl_hdr),
         Paragraph("Return", s_tbl_hdr),
         Paragraph(f"vs Benchmark ({BENCHMARK_APY_PCT:.0f}% APY)", s_tbl_hdr)],
        _period_row("Today", 1, today_ret),
        _period_row("7 Days", 7, week_ret),
        _period_row("30 Days", 30, month_ret),
        _period_row("All Time", n_all, all_time_ret),
    ]
    perf_tbl = Table(perf_data,
                     colWidths=[pw * 0.22, pw * 0.28, pw * 0.50])
    perf_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("BOX", (0, 0), (-1, -1), 0.5, DIM_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, MID_GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(perf_tbl)
    story.append(Spacer(1, 0.35 * cm))

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 3 — PORTFOLIO ALLOCATION
    # ══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("PORTFOLIO ALLOCATION", s_section))
    story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=5))

    # Build APY / tier maps from orchestrator snapshot
    apy_map: dict[str, float] = {}
    tier_map: dict[str, str] = {}
    for a in (orch.get("adapters") or []):
        if isinstance(a, dict):
            prot = str(a.get("protocol", "")).strip().lower()
            if prot:
                apy_val = a.get("apy_pct")
                apy_map[prot] = float(apy_val) if isinstance(apy_val, (int, float)) else 0.0
                tier_map[prot] = str(a.get("tier", "—"))

    # Positions: prefer latest equity bar, fall back to status
    pos_dict: dict[str, float] = {}
    if bars:
        pos_dict = bars[-1].get("positions") or {}
    if not pos_dict:
        pos_dict = status.get("current_positions") or {}
    pos_dict = {k: float(v) for k, v in pos_dict.items()
                if isinstance(v, (int, float)) and float(v) > 0}

    capital_val = (
        float(status.get("current_equity") or equity or 100_000.0)
        if not isinstance(equity, (int, float))
        else float(equity or 100_000.0)
    )
    deployed = sum(pos_dict.values())
    cash_usd = float(status.get("cash_usd") or max(capital_val - deployed, 0.0))

    alloc_hdr = [
        Paragraph("Protocol", s_tbl_hdr),
        Paragraph("Tier", s_tbl_hdr),
        Paragraph("Allocation", s_tbl_hdr),
        Paragraph("Weight %", s_tbl_hdr),
        Paragraph("APY %", s_tbl_hdr),
    ]
    alloc_rows = [alloc_hdr]

    for prot_key, pusd in sorted(pos_dict.items(), key=lambda kv: -kv[1]):
        weight = (pusd / capital_val * 100) if capital_val > 0 else 0.0
        tier = tier_map.get(prot_key.lower(), "—")
        apy = apy_map.get(prot_key.lower())
        apy_str = f"{apy:.2f}%" if apy is not None else "—"
        display = prot_key.replace("_", " ").title()
        alloc_rows.append([
            Paragraph(display, s_tbl_left),
            Paragraph(tier, s_tbl_ctr),
            Paragraph(f"${pusd:,.0f}", s_tbl_ctr),
            Paragraph(f"{weight:.1f}%", s_tbl_ctr),
            Paragraph(apy_str, s_tbl_ctr),
        ])

    # Cash row
    cash_w = (cash_usd / capital_val * 100) if capital_val > 0 else 0.0
    alloc_rows.append([
        Paragraph("Cash (Buffer)", s_tbl_left),
        Paragraph("—", s_tbl_ctr),
        Paragraph(f"${cash_usd:,.0f}", s_tbl_ctr),
        Paragraph(f"{cash_w:.1f}%", s_tbl_ctr),
        Paragraph("—", s_tbl_ctr),
    ])

    alloc_tbl = Table(alloc_rows,
                      colWidths=[pw * 0.28, pw * 0.10, pw * 0.20, pw * 0.20, pw * 0.22])
    alloc_style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("BACKGROUND", (0, -1), (-1, -1), PALE_YELLOW),
        ("BOX", (0, 0), (-1, -1), 0.5, DIM_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, MID_GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    alloc_tbl.setStyle(TableStyle(alloc_style))
    story.append(alloc_tbl)
    story.append(Spacer(1, 0.35 * cm))

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 4 — RISK METRICS
    # ══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("RISK METRICS", s_section))
    story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=5))

    m = analytics.get("metrics") or {}
    sharpe = m.get("sharpe")
    calmar = m.get("calmar")
    dd_info = m.get("drawdown") if isinstance(m.get("drawdown"), dict) else {}
    max_dd = dd_info.get("max_drawdown_pct")
    vol_info = m.get("volatility") if isinstance(m.get("volatility"), dict) else {}
    vol_ann = vol_info.get("annualized_vol")

    def _fmt_metric(val: Any, suffix: str = "", ndigits: int = 2, neg_prefix: bool = False) -> str:
        if val is None or (isinstance(val, float) and val != val):
            return "—"
        v = float(val)
        s = f"{v:.{ndigits}f}{suffix}"
        if neg_prefix and v > 0:
            return f"-{s}"
        return s

    risk_data = [
        [
            Paragraph("Sharpe Ratio", s_tbl_bold),
            Paragraph(_fmt_metric(sharpe), s_tbl_ctr),
            Paragraph("Max Drawdown", s_tbl_bold),
            Paragraph(_fmt_metric(max_dd, suffix="%", neg_prefix=True), s_tbl_ctr),
        ],
        [
            Paragraph("Volatility (ann.)", s_tbl_bold),
            Paragraph(_fmt_metric(vol_ann, suffix="%"), s_tbl_ctr),
            Paragraph("Calmar Ratio", s_tbl_bold),
            Paragraph(_fmt_metric(calmar), s_tbl_ctr),
        ],
    ]
    risk_tbl = Table(risk_data, colWidths=[cw] * 4)
    risk_tbl.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT_BLUE, LIGHT_BLUE2]),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#a0c4d8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c0d8e8")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(risk_tbl)
    story.append(Spacer(1, 0.35 * cm))

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 5 — GO-LIVE PROGRESS
    # ══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("GO-LIVE PROGRESS", s_section))
    story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=5))

    checks_list = _golive_checks(golive)
    n_passed = sum(1 for c in checks_list if c[0])
    if is_ready:
        gl_summary = f"Status: READY — all {n_passed}/6 criteria passed"
    else:
        gl_summary = f"Status: PRE-LIVE — {n_passed}/6 criteria met"
    story.append(Paragraph(gl_summary, s_tbl_bold))
    story.append(Spacer(1, 0.15 * cm))

    gl_hdr = [
        Paragraph("Status", s_tbl_hdr),
        Paragraph("Criterion", s_tbl_hdr),
        Paragraph("Description", s_tbl_hdr),
    ]
    gl_rows = [gl_hdr]
    for passed, key, label in checks_list:
        status_p = Paragraph("PASS", s_pass) if passed else Paragraph("FAIL", s_fail)
        gl_rows.append([status_p, Paragraph(key, s_tbl_left), Paragraph(label, s_tbl_left)])

    # Blockers row
    blockers = golive.get("blockers") if isinstance(golive, dict) else None
    if isinstance(blockers, list) and blockers:
        gl_rows.append([
            Paragraph("", s_tbl_left),
            Paragraph("Blockers:", s_tbl_bold),
            Paragraph("; ".join(str(b) for b in blockers), s_tbl_left),
        ])

    gl_tbl = Table(gl_rows, colWidths=[pw * 0.12, pw * 0.28, pw * 0.60])
    gl_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("BOX", (0, 0), (-1, -1), 0.5, DIM_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, MID_GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(gl_tbl)
    story.append(Spacer(1, 0.5 * cm))

    # ══════════════════════════════════════════════════════════════════════════
    # FOOTER
    # ══════════════════════════════════════════════════════════════════════════
    story.append(HRFlowable(width="100%", thickness=0.5, color=DIM_GRAY, spaceAfter=5))
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    story.append(Paragraph(f"Generated: {now_str}", s_footer))
    story.append(Spacer(1, 0.1 * cm))
    story.append(Paragraph(
        "SPA — Smart Passive Aggregator &nbsp;|&nbsp; "
        "Paper Trading Only &nbsp;|&nbsp; Not Financial Advice",
        s_disclaimer,
    ))

    doc.build(story)


# ─── Public API ──────────────────────────────────────────────────────────────


def generate_pdf_report(
    date_str: str | None = None,
    data_dir: str | os.PathLike | None = None,
) -> str:
    """Generate investor PDF report for the given date.

    Parameters
    ----------
    date_str : ``"YYYY-MM-DD"``; default = today (UTC).
    data_dir : directory with data/*.json (default ``<repo>/data``).

    Returns
    -------
    str — absolute path to the generated PDF file.

    Raises
    ------
    ValueError  — malformed ``date_str``
    ImportError — reportlab not installed
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR

    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    else:
        # Validate early — the date goes into a file name
        datetime.strptime(date_str, "%Y-%m-%d")

    ctx = _load_report_context(date_str, ddir)

    reports_dir = ddir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    out_name = f"investor_report_{date_str}.pdf"
    out_path = reports_dir / out_name

    # Atomic write: build into a temp file, then rename
    fd, tmp_str = tempfile.mkstemp(
        dir=str(reports_dir), prefix=f".{out_name}.", suffix=".tmp"
    )
    os.close(fd)
    try:
        _build_pdf(ctx, Path(tmp_str))
        os.replace(tmp_str, str(out_path))
    except Exception:
        try:
            if os.path.exists(tmp_str):
                os.remove(tmp_str)
        finally:
            raise

    log.info("Investor PDF report generated: %s", out_path)
    return str(out_path.resolve())


def generate_latest_report(data_dir: str | os.PathLike | None = None) -> str:
    """Find the latest ``daily_report_*.json`` and generate a PDF for that date.

    Returns
    -------
    str — absolute path to the generated PDF file.

    Raises
    ------
    FileNotFoundError — no ``daily_report_*.json`` exists in ``data_dir``
    ValueError        — filename doesn't match expected pattern
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    pattern = str(ddir / "daily_report_*.json")
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(
            f"No daily_report_*.json found in {ddir}"
        )
    latest = Path(matches[-1])
    m = re.search(r"daily_report_(\d{4}-\d{2}-\d{2})\.json$", latest.name)
    if not m:
        raise ValueError(f"Cannot parse date from filename: {latest.name}")
    return generate_pdf_report(m.group(1), data_dir=ddir)


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pdf_report",
        description="Generate SPA investor PDF report.",
    )
    parser.add_argument(
        "date", nargs="?", default=None, help="YYYY-MM-DD (default: today)"
    )
    parser.add_argument("--data-dir", default=None, help="override data directory")
    parser.add_argument(
        "--latest", action="store_true",
        help="use the latest available daily_report_*.json"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        if args.latest:
            pdf_path = generate_latest_report(data_dir=args.data_dir)
        else:
            pdf_path = generate_pdf_report(args.date, data_dir=args.data_dir)
        print(f"PDF generated: {pdf_path}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}")
        log.exception("PDF generation failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
