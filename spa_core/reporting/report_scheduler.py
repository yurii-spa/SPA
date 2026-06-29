"""
SPA Report Scheduler — loads JSON data files and generates the PDF report.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("spa.reports")


def generate_latest_report(data_dir: str, output_dir: str) -> str:
    """
    Load all JSON data files from data_dir and generate the PDF report.

    Looks for (in order of preference):
      - status.json          → portfolio + positions
      - portfolio.json       → portfolio (fallback)
      - positions.json       → positions (fallback)
      - risk_alerts.json     → risk alerts
      - backtest_results.json → backtest metrics

    Parameters
    ----------
    data_dir : str
        Directory containing the JSON data files.
    output_dir : str
        Directory where the PDF will be saved.

    Returns
    -------
    str
        Absolute path to the generated PDF file.
    """
    from reporting.pdf_generator import generate_report

    data_path   = Path(data_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).isoformat()

    # ── Portfolio + Positions ─────────────────────────────────────────────
    portfolio: dict = {}
    positions: list = []

    status_file = data_path / "status.json"
    if status_file.exists():
        try:
            status = json.loads(status_file.read_text())
            portfolio = status.get("portfolio", {}) or {}
            positions = status.get("positions", []) or []
            log.info(f"Loaded portfolio from status.json")
        except Exception as e:
            log.warning(f"Could not read status.json: {e}")
    else:
        # Fallback: separate files
        for fname, target in [("portfolio.json", "portfolio"), ("positions.json", "positions")]:
            fpath = data_path / fname
            if fpath.exists():
                try:
                    payload = json.loads(fpath.read_text())
                    if target == "portfolio":
                        portfolio = payload
                    else:
                        positions = payload if isinstance(payload, list) else []
                except Exception as e:
                    log.warning(f"Could not read {fname}: {e}")

    # ── Risk Alerts ───────────────────────────────────────────────────────
    risk_alerts: dict = {"count": 0, "status": "ok", "alerts": []}
    risk_file = data_path / "risk_alerts.json"
    if risk_file.exists():
        try:
            risk_alerts = json.loads(risk_file.read_text())
        except Exception as e:
            log.warning(f"Could not read risk_alerts.json: {e}")

    # ── Backtest Metrics ──────────────────────────────────────────────────
    backtest_metrics: dict = {}
    bt_file = data_path / "backtest_results.json"
    if bt_file.exists():
        try:
            bt_raw = json.loads(bt_file.read_text())
            # metrics may be nested under "metrics" key
            raw_metrics = bt_raw.get("metrics", bt_raw)
            backtest_metrics = {
                "total_return_pct":  raw_metrics.get("total_return_pct", 0),
                "sharpe":            raw_metrics.get("sharpe_ratio", raw_metrics.get("sharpe", 0)),
                "max_drawdown_pct":  raw_metrics.get("max_drawdown_pct", 0),
            }
        except Exception as e:
            log.warning(f"Could not read backtest_results.json: {e}")

    # ── Build data dict ───────────────────────────────────────────────────
    report_data = {
        "portfolio":        portfolio,
        "positions":        positions,
        "risk_alerts":      risk_alerts,
        "backtest_metrics": backtest_metrics,
        "generated_at":     generated_at,
    }

    # ── Output filename: spa_report_YYYYMMDD_HHMM.pdf ────────────────────
    now = datetime.now(timezone.utc)
    filename  = f"spa_report_{now.strftime('%Y%m%d_%H%M')}.pdf"
    pdf_path  = str(output_path / filename)

    result = generate_report(report_data, pdf_path)
    log.info(f"PDF report generated: {result}")

    # ── Write latest_report.json metadata ────────────────────────────────
    from datetime import date
    go_live = date(2026, 7, 15)
    days_rem = max((go_live - date.today()).days, 0)
    meta = {
        "generated_at":  generated_at,
        "pdf_filename":  filename,
        "report_date":   now.strftime("%Y-%m-%d"),
        "go_live_date":  "2026-07-15",
        "days_remaining": days_rem,
        "status":        "ON TRACK" if days_rem > 0 else "READY",
    }
    meta_path = output_path / "latest_report.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    log.info(f"Metadata written: {meta_path}")

    return result
