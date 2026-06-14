"""Reporting Agent — ежедневный P&L Telegram + monthly text report (MP-305).

КОНСТИТУЦИОННЫЙ ИНВАРИАНТ: LLM SDK ЗАПРЕЩЁН (stdlib only).
Числа берутся ТОЛЬКО из реальных data/ JSON-файлов, не генерируются.

Источники данных (все fail-safe):
  data/portfolio_track.json       → equity_today, equity_yesterday
  data/analytics_summary.json     → avg_apy_7d
  data/adapter_orchestrator_status.json → active_count
  data/sentinel_status.json       → alert_class

Публичный API:
  collect_pnl_data(data_dir)           → dict с P&L полями
  validate_report_numbers(data)        → (ok: bool, errors: list[str])
  format_daily_report(data)            → str для Telegram
  send_daily_report_telegram(data_dir, dry_run) → dict (с "report_text")
  generate_monthly_pdf_report(data_dir, output_dir) → str | None
  run_reporting_cycle(data_dir, dry_run) → dict статуса

Stdlib only. Atomic writes (tmp + os.replace). No LLM imports.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("spa.agents.reporting_agent")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# Physical validation bounds
_EQUITY_MIN = 0.0
_EQUITY_MAX = 10_000_000.0
_PNL_PCT_MIN = -50.0
_PNL_PCT_MAX = 50.0
_APY_MIN = 0.0
_APY_MAX = 100.0
_ADAPTERS_MIN = 0
_ADAPTERS_MAX = 100


# ─── IO helpers ───────────────────────────────────────────────────────────────


def _read_json(path: Path, default):
    """Defensive JSON reader — missing/corrupt file returns default, never raises."""
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("_read_json %s unreadable (%s) — using default", p.name, exc)
        return default


def _atomic_write_json(path: Path, obj) -> None:
    """Atomic write: tmpfile in same dir + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, str(path))
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        finally:
            raise


def _safe_float(val, default: float = 0.0) -> Optional[float]:
    """Convert to float safely; return None (not default) if val is None."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ─── collect_pnl_data ─────────────────────────────────────────────────────────


def collect_pnl_data(data_dir: Optional[Path] = None) -> dict:
    """Collect P&L data from real JSON files in data_dir.

    Reads from:
      portfolio_track.json       → equity_today, equity_yesterday (last 2 entries)
      analytics_summary.json     → avg_apy_7d
      adapter_orchestrator_status.json → active_count (adapters with status "ok")
      sentinel_status.json       → alert_class

    Returns
    -------
    dict with keys:
        equity_today     : float | None
        equity_yesterday : float | None
        daily_pnl_usd    : float | None
        daily_pnl_pct    : float | None
        avg_apy_7d       : float | None
        active_adapters  : int | None
        alert_class      : str | None
        data_complete    : bool  (False if any required source file is missing)
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    data_complete = True

    # ── portfolio_track.json ──────────────────────────────────────────────────
    equity_today: Optional[float] = None
    equity_yesterday: Optional[float] = None
    daily_pnl_usd: Optional[float] = None
    daily_pnl_pct: Optional[float] = None

    pt_path = ddir / "portfolio_track.json"
    if not pt_path.exists():
        data_complete = False
    else:
        pt = _read_json(pt_path, None)
        entries: list = []
        if isinstance(pt, list):
            entries = [e for e in pt if isinstance(e, dict)]
        elif isinstance(pt, dict):
            raw = pt.get("entries") or []
            entries = [e for e in raw if isinstance(e, dict)]

        if len(entries) >= 2:
            last = entries[-1]
            prev = entries[-2]
            equity_today = _safe_float(last.get("equity_usd"))
            equity_yesterday = _safe_float(prev.get("equity_usd"))
            if equity_today is not None and equity_yesterday is not None:
                daily_pnl_usd = round(equity_today - equity_yesterday, 4)
                if equity_yesterday != 0:
                    daily_pnl_pct = round(
                        (equity_today - equity_yesterday) / equity_yesterday * 100, 6
                    )
        elif len(entries) == 1:
            equity_today = _safe_float(entries[0].get("equity_usd"))
        else:
            data_complete = False

    # ── analytics_summary.json ────────────────────────────────────────────────
    avg_apy_7d: Optional[float] = None
    an_path = ddir / "analytics_summary.json"
    if not an_path.exists():
        data_complete = False
    else:
        an = _read_json(an_path, {})
        if isinstance(an, dict):
            raw_apy = an.get("avg_apy_7d")
            if raw_apy is None:
                # Fallback: look inside "metrics" sub-dict
                metrics = an.get("metrics") or {}
                raw_apy = metrics.get("avg_apy_7d")
            avg_apy_7d = _safe_float(raw_apy)

    # ── adapter_orchestrator_status.json ──────────────────────────────────────
    active_adapters: Optional[int] = None
    orch_path = ddir / "adapter_orchestrator_status.json"
    if not orch_path.exists():
        data_complete = False
    else:
        orch = _read_json(orch_path, {})
        if isinstance(orch, dict):
            adapters = orch.get("adapters") or []
            active_adapters = sum(
                1 for a in adapters
                if isinstance(a, dict) and str(a.get("status", "")).lower() == "ok"
            )

    # ── sentinel_status.json ──────────────────────────────────────────────────
    alert_class: Optional[str] = None
    sent_path = ddir / "sentinel_status.json"
    if not sent_path.exists():
        data_complete = False
    else:
        sent = _read_json(sent_path, {})
        if isinstance(sent, dict):
            alert_class = sent.get("alert_class")

    return {
        "equity_today": equity_today,
        "equity_yesterday": equity_yesterday,
        "daily_pnl_usd": daily_pnl_usd,
        "daily_pnl_pct": daily_pnl_pct,
        "avg_apy_7d": avg_apy_7d,
        "active_adapters": active_adapters,
        "alert_class": alert_class,
        "data_complete": data_complete,
    }


# ─── validate_report_numbers ──────────────────────────────────────────────────


def validate_report_numbers(data: dict) -> tuple:
    """Validate that report numbers are within physically plausible bounds.

    Checks:
      equity_today     : 0 < x < 10_000_000
      daily_pnl_pct    : -50% ≤ x ≤ +50%
      avg_apy_7d       : 0% ≤ x ≤ 100%
      active_adapters  : 0 ≤ x ≤ 100

    None values are treated as invalid (data_complete=False case).

    Returns
    -------
    (ok: bool, errors: list[str])
    """
    errors: list[str] = []

    # equity_today
    eq = data.get("equity_today")
    if eq is None:
        errors.append("equity_today is None — data incomplete")
    elif not (_EQUITY_MIN < eq < _EQUITY_MAX):
        errors.append(
            f"equity_today={eq} out of range ({_EQUITY_MIN}, {_EQUITY_MAX})"
        )

    # daily_pnl_pct
    pnl = data.get("daily_pnl_pct")
    if pnl is None:
        errors.append("daily_pnl_pct is None — data incomplete")
    elif not (_PNL_PCT_MIN <= pnl <= _PNL_PCT_MAX):
        errors.append(
            f"daily_pnl_pct={pnl}% out of range [{_PNL_PCT_MIN}%, {_PNL_PCT_MAX}%]"
        )

    # avg_apy_7d
    apy = data.get("avg_apy_7d")
    if apy is None:
        errors.append("avg_apy_7d is None — data incomplete")
    elif not (_APY_MIN <= apy <= _APY_MAX):
        errors.append(
            f"avg_apy_7d={apy}% out of range [{_APY_MIN}%, {_APY_MAX}%]"
        )

    # active_adapters
    adap = data.get("active_adapters")
    if adap is None:
        errors.append("active_adapters is None — data incomplete")
    elif not (_ADAPTERS_MIN <= adap <= _ADAPTERS_MAX):
        errors.append(
            f"active_adapters={adap} out of range [{_ADAPTERS_MIN}, {_ADAPTERS_MAX}]"
        )

    return (len(errors) == 0, errors)


# ─── format_daily_report ──────────────────────────────────────────────────────


def format_daily_report(data: dict) -> str:
    """Format P&L data as a Telegram-ready string.

    Format:
        📊 SPA Daily Report — {date}
        💼 Equity: ${equity:.0f} ({pnl_pct:+.2f}%)
        📈 P&L today: ${pnl_usd:+.0f}
        ⚡ Avg APY (7d): {apy:.1f}%
        🔌 Active adapters: {n}
        🚨 Alert: {class}

    Appends ⚠️ Incomplete data line if data_complete=False.
    """
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    equity = data.get("equity_today")
    pnl_pct = data.get("daily_pnl_pct")
    pnl_usd = data.get("daily_pnl_usd")
    apy = data.get("avg_apy_7d")
    adapters = data.get("active_adapters")
    alert = data.get("alert_class") or "UNKNOWN"
    data_complete = data.get("data_complete", False)

    # Format each field with safe fallbacks
    equity_str = f"${equity:,.0f}" if equity is not None else "N/A"
    pnl_pct_str = f"{pnl_pct:+.2f}%" if pnl_pct is not None else "N/A"
    pnl_usd_str = f"${pnl_usd:+,.0f}" if pnl_usd is not None else "N/A"
    apy_str = f"{apy:.1f}%" if apy is not None else "N/A"
    adapters_str = str(adapters) if adapters is not None else "N/A"

    lines = [
        f"📊 SPA Daily Report — {date_str}",
        f"💼 Equity: {equity_str} ({pnl_pct_str})",
        f"📈 P&L today: {pnl_usd_str}",
        f"⚡ Avg APY (7d): {apy_str}",
        f"🔌 Active adapters: {adapters_str}",
        f"🚨 Alert: {alert}",
    ]

    if not data_complete:
        lines.append("⚠️ Incomplete data")

    return "\n".join(lines)


# ─── send_daily_report_telegram ───────────────────────────────────────────────


def send_daily_report_telegram(
    data_dir: Optional[Path] = None,
    dry_run: bool = False,
) -> dict:
    """Collect, validate, format and (optionally) send daily report.

    Parameters
    ----------
    data_dir : data directory (default: <repo>/data).
    dry_run  : True (default) → do NOT send to Telegram, return dict only.

    Returns
    -------
    dict with keys:
        report_text   : str  — formatted report text
        data_complete : bool
        validation_ok : bool
        validation_errors : list[str]
        sent          : bool  — True if sent (or dry_run=True and logged)
        dry_run       : bool
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR

    pnl_data = collect_pnl_data(ddir)
    val_ok, val_errors = validate_report_numbers(pnl_data)
    report_text = format_daily_report(pnl_data)

    sent = False
    if dry_run:
        log.info("send_daily_report_telegram [DRY RUN]:\n%s", report_text)
        sent = True  # dry_run counts as "would be sent"
    else:
        try:
            from spa_core.alerts import telegram_client  # noqa: PLC0415
            sent = bool(telegram_client.send_message(report_text))
        except Exception as exc:
            log.warning("telegram send failed (%s)", exc)
            sent = False

    result = {
        "report_text": report_text,
        "data_complete": pnl_data.get("data_complete", False),
        "validation_ok": val_ok,
        "validation_errors": val_errors,
        "sent": sent,
        "dry_run": dry_run,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Write reporting_status.json atomically
    try:
        _atomic_write_json(ddir / "reporting_status.json", result)
    except Exception as exc:
        log.warning("reporting_status.json write failed (%s)", exc)

    return result


# ─── generate_monthly_pdf_report ──────────────────────────────────────────────


def generate_monthly_pdf_report(
    data_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> Optional[str]:
    """Generate a monthly plain-text report (only on day == 1).

    Reads portfolio_track.json for the last 30 days of entries.
    Writes data/reports/spa_monthly_{year}_{month}.txt (plain text, no PDF library).

    Parameters
    ----------
    data_dir   : data directory (default: <repo>/data).
    output_dir : output directory for the .txt file (default: data_dir/reports).

    Returns
    -------
    str — absolute path to the generated .txt file, or None if today is not day 1
          or generation fails.
    """
    now = datetime.now(timezone.utc)
    if now.day != 1:
        return None

    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    out_dir = Path(output_dir) if output_dir is not None else ddir / "reports"

    year = now.year
    month = now.month
    filename = f"spa_monthly_{year}_{month:02d}.txt"
    out_path = out_dir / filename

    try:
        # Load last 30 days from portfolio_track.json
        pt = _read_json(ddir / "portfolio_track.json", None)
        entries: list = []
        if isinstance(pt, list):
            entries = [e for e in pt if isinstance(e, dict)]
        elif isinstance(pt, dict):
            raw = pt.get("entries") or []
            entries = [e for e in raw if isinstance(e, dict)]

        last_30 = entries[-30:] if len(entries) > 30 else entries
        n_entries = len(last_30)

        first_eq = _safe_float(last_30[0].get("equity_usd")) if last_30 else None
        last_eq = _safe_float(last_30[-1].get("equity_usd")) if last_30 else None

        if first_eq and last_eq and first_eq > 0:
            monthly_return_pct = round((last_eq - first_eq) / first_eq * 100, 4)
            monthly_pnl_usd = round(last_eq - first_eq, 2)
        else:
            monthly_return_pct = None
            monthly_pnl_usd = None

        # Build report text
        lines = [
            f"SPA Monthly Report — {year}-{month:02d}",
            f"Generated: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            "",
            f"Period: {n_entries} days of data",
        ]
        if last_eq is not None:
            lines.append(f"Final Equity: ${last_eq:,.2f}")
        if first_eq is not None:
            lines.append(f"Starting Equity: ${first_eq:,.2f}")
        if monthly_pnl_usd is not None:
            sign = "+" if monthly_pnl_usd >= 0 else ""
            lines.append(f"Monthly P&L: {sign}${monthly_pnl_usd:,.2f}")
        if monthly_return_pct is not None:
            sign = "+" if monthly_return_pct >= 0 else ""
            lines.append(f"Monthly Return: {sign}{monthly_return_pct:.4f}%")

        lines += [
            "",
            "--- Daily Equity ---",
        ]
        for entry in last_30:
            d = entry.get("date", "?")
            eq = _safe_float(entry.get("equity_usd"))
            eq_str = f"${eq:,.2f}" if eq is not None else "N/A"
            lines.append(f"  {d}: {eq_str}")

        content = "\n".join(lines) + "\n"

        # Write atomically
        out_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(out_dir), prefix=f".{filename}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, str(out_path))
        except Exception:
            try:
                if os.path.exists(tmp_name):
                    os.remove(tmp_name)
            finally:
                raise

        log.info("Monthly report written: %s", out_path)
        return str(out_path)

    except Exception as exc:
        log.warning("generate_monthly_pdf_report failed (%s)", exc)
        return None


# ─── run_reporting_cycle ──────────────────────────────────────────────────────


def run_reporting_cycle(
    data_dir: Optional[Path] = None,
    dry_run: bool = False,
) -> dict:
    """Main entry point for the reporting cycle.

    1. generate_monthly_pdf_report() — if today is day 1
    2. send_daily_report_telegram(dry_run=dry_run)

    Parameters
    ----------
    data_dir : data directory (default: <repo>/data).
    dry_run  : True (default) → no real Telegram sends.

    Returns
    -------
    dict with keys: daily_sent, monthly_generated, errors
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    errors: list[str] = []
    monthly_path: Optional[str] = None
    daily_result: Optional[dict] = None

    # Step 1: Monthly report (only on day 1)
    try:
        monthly_path = generate_monthly_pdf_report(data_dir=ddir)
    except Exception as exc:
        msg = f"monthly_report failed: {exc}"
        log.warning(msg)
        errors.append(msg)

    # Step 2: Daily report (always)
    try:
        daily_result = send_daily_report_telegram(data_dir=ddir, dry_run=dry_run)
    except Exception as exc:
        msg = f"daily_report failed: {exc}"
        log.warning(msg)
        errors.append(msg)
        daily_result = None

    return {
        "daily_sent": bool(daily_result and daily_result.get("sent")),
        "monthly_generated": monthly_path,
        "errors": errors,
    }
