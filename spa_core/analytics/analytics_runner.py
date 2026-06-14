"""Post-cycle analytics runner (MP-104).

Reads ``data/equity_curve_daily.json`` (the real cycle_runner track record),
computes the 7 core metrics — Sharpe, max drawdown, volatility, benchmark
comparison, win/loss streaks, Calmar, concentration — and atomically writes
``data/analytics_summary.json``.

Safety / scope
==============
* STRICTLY READ-ONLY analytics over paper-trading JSON. No capital, no
  network, no execution-domain imports, no LLM. Stdlib only.
* Fail-safe per metric: an exception inside any metric module is logged as
  WARNING, recorded under ``errors`` and the PARTIAL summary is still
  written — the caller (cycle_runner post-cycle hook) never crashes.
* Atomic write: tmpfile + os.replace.

Run manually::

    python3 -m spa_core.analytics.analytics_runner
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .benchmark import compare_to_benchmark
from .calmar import calculate_calmar
from .concentration import calculate_concentration
from .drawdown import calculate_max_drawdown
from .sharpe import calculate_sharpe
from .streak import calculate_streaks
from .volatility import calculate_volatility

log = logging.getLogger("spa.analytics_runner")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

EQUITY_FILENAME = "equity_curve_daily.json"
SUMMARY_FILENAME = "analytics_summary.json"

BENCHMARK_APY = 0.05  # simple-deposit benchmark (5% APY)
RISK_FREE_RATE = 0.05


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Write JSON atomically: tmpfile in the same dir + os.replace (rename)."""
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
        os.replace(tmp_name, path)
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        finally:
            raise


def _extract_series(doc: dict) -> tuple[list[str], list[float], dict[str, float]]:
    """(dates, equity, last-bar allocation) from an equity_curve_daily doc.

    Equity per bar: flat ``equity`` field with ``close_equity`` fallback.
    Bars without a usable equity value are skipped (dates stay aligned).
    """
    dates: list[str] = []
    equity: list[float] = []
    allocation: dict[str, float] = {}
    for bar in doc.get("daily") or []:
        if not isinstance(bar, dict):
            continue
        v = bar.get("equity", bar.get("close_equity"))
        if not isinstance(v, (int, float)):
            continue
        dates.append(str(bar.get("date", "")))
        equity.append(float(v))
        positions = bar.get("positions")
        if isinstance(positions, dict):
            allocation = {
                str(p): float(w)
                for p, w in positions.items()
                if isinstance(w, (int, float))
            }
    return dates, equity, allocation


def _daily_returns(equity: list[float]) -> list[float]:
    """Fractional day-over-day returns; pairs with a non-positive base are skipped."""
    out: list[float] = []
    for prev, cur in zip(equity, equity[1:]):
        if prev > 0:
            out.append(cur / prev - 1.0)
    return out


def run_post_cycle_analytics(
    data_dir: str | os.PathLike | None = None,
    *,
    now: datetime | None = None,
    write: bool = True,
) -> dict:
    """Compute all MP-104 metrics and write ``data/analytics_summary.json``.

    Never raises for a per-metric failure: each metric is wrapped, a failure
    is logged as WARNING, set to ``None`` in ``metrics`` and appended to
    ``errors`` — the (possibly partial) summary is always written.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    now_dt = now or datetime.now(timezone.utc)

    try:
        doc = json.loads((ddir / EQUITY_FILENAME).read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            doc = {}
    except (OSError, ValueError) as exc:
        log.warning("%s unreadable (%s) — empty analytics", EQUITY_FILENAME, exc)
        doc = {}

    dates, equity, allocation = _extract_series(doc)
    returns = _daily_returns(equity)
    pnl = [cur - prev for prev, cur in zip(equity, equity[1:])]

    metrics: dict[str, Any] = {}
    errors: list[str] = []

    def _safe(name: str, fn: Callable[[], Any]) -> None:
        try:
            metrics[name] = fn()
        except Exception as exc:  # noqa: BLE001 — partial summary by design
            log.warning("analytics metric %r failed: %s", name, exc)
            metrics[name] = None
            errors.append(f"{name}: {type(exc).__name__}: {exc}")

    _safe("sharpe", lambda: calculate_sharpe(returns, RISK_FREE_RATE))
    _safe("drawdown", lambda: calculate_max_drawdown(equity, dates))
    _safe("volatility", lambda: calculate_volatility(returns))
    _safe(
        "benchmark",
        lambda: compare_to_benchmark(equity, dates, BENCHMARK_APY),
    )
    _safe("streaks", lambda: calculate_streaks(pnl))

    def _calmar() -> float:
        bench = metrics.get("benchmark") or {}
        dd = metrics.get("drawdown") or {}
        total_return_pct = float(bench.get("spa_total_return", 0.0))
        days = max(1, len(equity) - 1)
        annualized = total_return_pct * 365.0 / days
        return calculate_calmar(annualized, float(dd.get("max_drawdown_pct", 0.0)))

    _safe("calmar", _calmar)
    _safe("concentration", lambda: calculate_concentration(allocation))

    summary = {
        "generated_at": now_dt.isoformat(),
        "source": "analytics_runner",
        "is_demo": bool(doc.get("is_demo", False)),
        "num_days": len(equity),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "metrics": metrics,
        "errors": errors,
    }
    if write:
        _atomic_write_json(ddir / SUMMARY_FILENAME, summary)
    return summary


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    summary = run_post_cycle_analytics()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not summary["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
