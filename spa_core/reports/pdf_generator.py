"""
SPA Investor Report — auto-generated PDF.
One page, professional layout, suitable for sharing with potential investors.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, date
from typing import Any

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT


# ── Brand colours ────────────────────────────────────────────────────────────
NAVY      = colors.HexColor("#1A3A5C")
BLUE      = colors.HexColor("#2980B9")
LIGHT_ROW = colors.HexColor("#EAF2FB")
WHITE     = colors.white
GREEN     = colors.HexColor("#27AE60")
RED       = colors.HexColor("#E74C3C")
AMBER     = colors.HexColor("#E67E22")
LIGHT_GREY = colors.HexColor("#F5F7FA")
MID_GREY  = colors.HexColor("#BDC3C7")

GO_LIVE_DATE = date(2026, 7, 15)
START_DATE   = date(2026, 5, 20)


def _safe(d: dict, *keys, default="N/A", fmt: str | None = None) -> str:
    """Safely traverse nested dict keys; format if fmt given."""
    val = d
    for k in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(k)
        if val is None:
            return default
    if fmt:
        try:
            return fmt.format(val)
        except Exception:
            return str(val)
    return str(val)


def _fmt_usd(v, decimals=0) -> str:
    try:
        v = float(v)
        sign = "+" if v > 0 else ""
        if decimals:
            return f"{sign}${v:,.{decimals}f}"
        return f"{sign}${v:,.0f}"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_pct(v, decimals=2) -> str:
    try:
        return f"{float(v):.{decimals}f}%"
    except (TypeError, ValueError):
        return "N/A"


def _days_remaining() -> int:
    today = date.today()
    delta = (GO_LIVE_DATE - today).days
    return max(delta, 0)


def _days_running() -> int:
    today = date.today()
    return max((today - START_DATE).days, 1)


def generate_report(data: dict, output_path: str) -> str:
    """
    Generate a single-page investor-style PDF report.

    Parameters
    ----------
    data : dict
        Keys expected:
          portfolio         – dict with total_capital_usd, total_pnl_usd,
                              total_pnl_pct, current_apy
          positions         – list of dicts: protocol, tier, amount_usd,
                              current_apy, unrealized_pnl_usd
          risk_alerts       – dict with count, status, alerts list
          backtest_metrics  – dict with total_return_pct, sharpe, max_drawdown_pct
          generated_at      – ISO-8601 string
    output_path : str
        Full file path for the output PDF.

    Returns
    -------
    str
        Same as output_path on success.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    portfolio   = data.get("portfolio", {}) or {}
    positions   = data.get("positions", []) or []
    risk_data   = data.get("risk_alerts", {}) or {}
    backtest    = data.get("backtest_metrics", {}) or {}
    gen_at_raw  = data.get("generated_at", datetime.now(timezone.utc).isoformat())

    try:
        gen_dt = datetime.fromisoformat(gen_at_raw.replace("Z", "+00:00"))
        gen_str = gen_dt.strftime("%Y-%m-%d %H:%M UTC")
        report_date = gen_dt.strftime("%Y-%m-%d")
    except Exception:
        gen_str = str(gen_at_raw)[:16]
        report_date = str(gen_at_raw)[:10]

    # ── Document ─────────────────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.40 * inch,
    )

    styles = getSampleStyleSheet()

    def ps(name, **kw) -> ParagraphStyle:
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    S = {
        "header_title": ps("HT", fontSize=16, textColor=WHITE,
                           fontName="Helvetica-Bold", leading=20),
        "header_sub":   ps("HS", fontSize=8.5, textColor=colors.HexColor("#A8C8E8"),
                           fontName="Helvetica", leading=11),
        "header_date":  ps("HD", fontSize=9, textColor=WHITE,
                           fontName="Helvetica", alignment=TA_RIGHT, leading=11),
        "kpi_label":    ps("KL", fontSize=7.5, textColor=colors.HexColor("#7F8C8D"),
                           fontName="Helvetica", leading=10),
        "kpi_value":    ps("KV", fontSize=14, textColor=NAVY,
                           fontName="Helvetica-Bold", leading=17),
        "section":      ps("SEC", fontSize=8, textColor=WHITE,
                           fontName="Helvetica-Bold", leading=10),
        "cell":         ps("CELL", fontSize=8.5, textColor=NAVY,
                           fontName="Helvetica", leading=11),
        "cell_bold":    ps("CELLB", fontSize=8.5, textColor=NAVY,
                           fontName="Helvetica-Bold", leading=11),
        "cell_green":   ps("CG", fontSize=8.5, textColor=GREEN,
                           fontName="Helvetica-Bold", leading=11),
        "cell_red":     ps("CR", fontSize=8.5, textColor=RED,
                           fontName="Helvetica-Bold", leading=11),
        "footer":       ps("FT", fontSize=6.5, textColor=colors.HexColor("#95A5A6"),
                           fontName="Helvetica", alignment=TA_CENTER, leading=9),
        "footer_link":  ps("FTL", fontSize=7, textColor=BLUE,
                           fontName="Helvetica-Bold", alignment=TA_CENTER, leading=10),
    }

    story = []
    PAGE_W = letter[0] - 1.10 * inch  # usable width

    # ─────────────────────────────────────────────────────────────────────────
    # HEADER BANNER
    # ─────────────────────────────────────────────────────────────────────────
    header_data = [[
        Paragraph("SPA — Smart Passive Aggregator", S["header_title"]),
        Paragraph(f"{report_date}", S["header_date"]),
    ], [
        Paragraph("Paper Trading Report &nbsp;·&nbsp; v0.14 &nbsp;·&nbsp; Policy v1.0",
                  S["header_sub"]),
        Paragraph(f"Generated {gen_str}", S["header_date"]),
    ]]
    hdr_table = Table(header_data, colWidths=[PAGE_W * 0.72, PAGE_W * 0.28])
    hdr_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING",   (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 7),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [NAVY, NAVY]),
    ]))
    story.append(hdr_table)
    story.append(Spacer(1, 6))

    # ─────────────────────────────────────────────────────────────────────────
    # KPI ROW
    # ─────────────────────────────────────────────────────────────────────────
    capital    = portfolio.get("total_capital_usd", 100_000)
    pnl_usd    = portfolio.get("total_pnl_usd", 0)
    pnl_pct    = portfolio.get("total_pnl_pct", 0)
    apy        = portfolio.get("current_apy")
    days_run   = _days_running()
    total_days = (GO_LIVE_DATE - START_DATE).days

    apy_str = f"{float(apy):.2f}%" if apy is not None else "N/A"

    def kpi_cell(label: str, value: str):
        return [Paragraph(label, S["kpi_label"]), Paragraph(value, S["kpi_value"])]

    kpi_table = Table(
        [[
            kpi_cell("CAPITAL", f"${float(capital):,.0f}" if capital else "N/A"),
            kpi_cell("PnL", _fmt_usd(pnl_usd, 0)),
            kpi_cell("EST. APY", apy_str),
            kpi_cell("DAYS RUNNING", f"{days_run} of {total_days}"),
        ]],
        colWidths=[PAGE_W / 4] * 4,
    )
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), LIGHT_GREY),
        ("BOX",          (0, 0), (-1, -1), 0.5, MID_GREY),
        ("LINEAFTER",    (0, 0), (2, 0),   0.5, MID_GREY),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING",   (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 7),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 7))

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION HEADER helper
    # ─────────────────────────────────────────────────────────────────────────
    def section_header(title: str):
        t = Table([[Paragraph(title, S["section"])]],
                  colWidths=[PAGE_W])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), BLUE),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    # ─────────────────────────────────────────────────────────────────────────
    # POSITIONS
    # ─────────────────────────────────────────────────────────────────────────
    story.append(section_header("POSITIONS"))

    pos_header = ["Protocol", "Tier", "Amount", "APY", "PnL"]
    pos_rows = [pos_header]
    if positions:
        for pos in positions:
            protocol = pos.get("protocol", pos.get("protocol_key", "N/A"))
            tier     = pos.get("tier", "N/A")
            amount   = pos.get("amount_usd")
            apy_p    = pos.get("current_apy")
            pnl_p    = pos.get("unrealized_pnl_usd", pos.get("pnl_usd"))
            pos_rows.append([
                Paragraph(str(protocol), S["cell"]),
                Paragraph(str(tier), S["cell"]),
                Paragraph(f"${float(amount):,.0f}" if amount is not None else "N/A", S["cell"]),
                Paragraph(f"{float(apy_p):.2f}%" if apy_p is not None else "N/A", S["cell"]),
                Paragraph(_fmt_usd(pnl_p, 2) if pnl_p is not None else "N/A",
                          S["cell_green"] if pnl_p and float(pnl_p) >= 0 else S["cell_red"]),
            ])
    else:
        pos_rows.append([
            Paragraph("No open positions", S["cell"]),
            "", "", "", "",
        ])

    col_w = [PAGE_W * r for r in [0.36, 0.10, 0.18, 0.18, 0.18]]
    pos_table = Table(pos_rows, colWidths=col_w)
    pos_style = [
        ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 7),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 7),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LIGHT_ROW]),
        ("LINEBELOW",     (0, 0), (-1, -1), 0.3, MID_GREY),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]
    pos_table.setStyle(TableStyle(pos_style))
    story.append(pos_table)
    story.append(Spacer(1, 7))

    # ─────────────────────────────────────────────────────────────────────────
    # RISK STATUS
    # ─────────────────────────────────────────────────────────────────────────
    story.append(section_header("RISK STATUS"))

    alert_count  = risk_data.get("count", 0)
    risk_status  = (risk_data.get("status") or "ok").lower()
    drawdown_pct = portfolio.get("total_drawdown_pct", 0) or 0
    var_pct      = portfolio.get("var_pct", 0) or 0

    if risk_status == "ok" or alert_count == 0:
        health_sym  = Paragraph("<font color='#27AE60'>&#10003;</font> Portfolio health OK", S["cell_green"])
        alert_sym   = Paragraph("<font color='#27AE60'>&#10003;</font> No active alerts", S["cell_green"])
    elif risk_status == "warning":
        health_sym  = Paragraph("<font color='#E67E22'>&#9651;</font> Warnings present", S["cell"])
        alert_sym   = Paragraph(f"<font color='#E67E22'>&#9651;</font> {alert_count} alert(s)", S["cell"])
    else:
        health_sym  = Paragraph("<font color='#E74C3C'>&#10007;</font> Risk violations!", S["cell_red"])
        alert_sym   = Paragraph(f"<font color='#E74C3C'>&#10007;</font> {alert_count} critical alert(s)", S["cell_red"])

    dd_str  = f"Drawdown: {abs(float(drawdown_pct)):.1f}%"
    var_str = f"VaR (95%, 7d): {abs(float(var_pct)):.2f}%"

    risk_table = Table(
        [[health_sym,
          Paragraph(dd_str, S["cell"]),
          alert_sym,
          Paragraph(var_str, S["cell"])]],
        colWidths=[PAGE_W * r for r in [0.30, 0.20, 0.30, 0.20]],
    )
    risk_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_GREY),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEAFTER",     (0, 0), (2, 0), 0.5, MID_GREY),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(risk_table)
    story.append(Spacer(1, 7))

    # ─────────────────────────────────────────────────────────────────────────
    # BACKTEST
    # ─────────────────────────────────────────────────────────────────────────
    story.append(section_header("BACKTEST (90d synthetic)"))

    bt_return = backtest.get("total_return_pct", backtest.get("total_return", "N/A"))
    bt_sharpe = backtest.get("sharpe", backtest.get("sharpe_ratio", "N/A"))
    bt_dd     = backtest.get("max_drawdown_pct", "N/A")

    try:
        bt_return_str = f"+{float(bt_return):.2f}%"
    except (TypeError, ValueError):
        bt_return_str = "N/A"
    try:
        bt_sharpe_str = f"{float(bt_sharpe):.2f}"
    except (TypeError, ValueError):
        bt_sharpe_str = "N/A"
    try:
        bt_dd_str = f"{float(bt_dd):.1f}%"
    except (TypeError, ValueError):
        bt_dd_str = "N/A"

    bt_table = Table(
        [[
            Paragraph(f"Return: <b>{bt_return_str}</b>", S["cell"]),
            Paragraph(f"Sharpe: <b>{bt_sharpe_str}</b>", S["cell"]),
            Paragraph(f"Max DD: <b>{bt_dd_str}</b>", S["cell"]),
        ]],
        colWidths=[PAGE_W / 3] * 3,
    )
    bt_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_GREY),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEAFTER",     (0, 0), (1, 0), 0.5, MID_GREY),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(bt_table)
    story.append(Spacer(1, 7))

    # ─────────────────────────────────────────────────────────────────────────
    # GO-LIVE TIMER
    # ─────────────────────────────────────────────────────────────────────────
    story.append(section_header("GO-LIVE TIMER"))

    days_rem   = _days_remaining()
    status_str = "ON TRACK" if days_rem > 0 else "READY"
    status_col = S["cell_green"] if days_rem >= 0 else S["cell_red"]

    gl_table = Table(
        [[
            Paragraph(f"Started: {START_DATE.strftime('%Y-%m-%d')}", S["cell"]),
            Paragraph(f"Target: {GO_LIVE_DATE.strftime('%Y-%m-%d')}", S["cell"]),
            Paragraph(f"{days_rem} days remaining", S["cell_bold"]),
            Paragraph(f"Status: <b>{status_str}</b>", status_col),
        ]],
        colWidths=[PAGE_W * r for r in [0.25, 0.25, 0.25, 0.25]],
    )
    gl_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_GREY),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEAFTER",     (0, 0), (2, 0), 0.5, MID_GREY),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(gl_table)
    story.append(Spacer(1, 8))

    # ─────────────────────────────────────────────────────────────────────────
    # FOOTER
    # ─────────────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width=PAGE_W, thickness=0.5, color=MID_GREY))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Dashboard: <a href='https://yurii-spa.github.io/SPA/'>"
        "https://yurii-spa.github.io/SPA/</a>",
        S["footer_link"],
    ))
    story.append(Spacer(1, 2))
    story.append(Paragraph(
        "CONFIDENTIAL — Paper Trading Only — Not Financial Advice",
        S["footer"],
    ))

    # ── Build ────────────────────────────────────────────────────────────────
    doc.build(story)
    return output_path
