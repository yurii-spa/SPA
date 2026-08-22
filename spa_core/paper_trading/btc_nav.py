"""spa_core/paper_trading/btc_nav.py — paper-NAV трек BTC/USDT-движка (ADR-118).

Мандат: Q1-решение владельца 22.08 («запустить paper NAV трекинг BTC/USDT-движка;
трек-рекорд — единственный актив, который нельзя купить или ускорить») поверх
вердикта бэктест-фазы (research/btc_cycle: чемпион v0.1, k=0.7–0.8, дальнейшие
итерации правил остановлены; единственная чистая валидация — живой paper-трек).

Двухслойная граница (инвариант #4, stdlib-only runtime):

  * ДВИЖОК (pandas, checkonchain+FRED) живёт в research-слое и ПРОИЗВОДИТ файл
    ``data/btc_cycle/target_share.json`` — сегодняшняя целевая доля BTC (k уже
    применён), цена и происхождение входов. Этот модуль движок НЕ импортирует.
  * ЭТОТ модуль — stdlib-бухгалтер: читает сигнал fail-closed и ведёт paper-книгу
    ``data/btc_paper_trading.json`` (ОТДЕЛЬНЫЙ виртуальный NAV в USDT; капитал
    не двигается; IS_ADVISORY — инвариант #9). Стоп-кран общего портфеля не
    задет ПО ПОСТРОЕНИЮ: книга не входит в equity_curve_daily / основную книгу.

Fail-CLOSED, ничего не выдумывается:

  * нет сигнала / сигнал протух / цена неположительна → в книгу пишется GAP
    с причиной (один на день), NAV НЕ пересчитывается по выдуманной цене;
  * идемпотентность по дню сигнала: повторный тик того же ``as_of`` — no-op;
  * атомарная запись (tmp + os.replace); модуль никогда не бросает.

LLM_FORBIDDEN · stdlib only.

CLI:  python3 -m spa_core.paper_trading.btc_nav [--dry-run] [--json]
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

SIGNAL_FILE = "btc_cycle/target_share.json"
BOOK_FILE = "btc_paper_trading.json"

#: Виртуальный сид отдельного NAV (USDT). Число видно в книге и меняется только
#: решением владельца; на живой капитал не влияет ничем.
SEED_EQUITY_USDT = 25_000.0

#: Сигнал старше этого — протух: движок обязан пересчитываться ежедневно,
#: 30ч = суточный такт + буфер на сдвиг расписания (та же логика, что SLO флота).
MAX_SIGNAL_AGE_H = 30.0

#: Ребаланс регистрируется решением только при сдвиге доли крупнее этого
#: (анти-шум журнала; сама доля приводится к цели в любом случае).
DECISION_EPS = 0.005


def _load(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except Exception:  # noqa: BLE001 — нечитаемое = отсутствующее (fail-closed выше)
        return None


def _save(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _new_book(now: _dt.datetime) -> dict:
    return {
        "engine": "BTC/USDT cycle ladder v0.1 (research producer)",
        "start_date": now.date().isoformat(),
        "seed_equity_usdt": SEED_EQUITY_USDT,
        "equity_usdt": SEED_EQUITY_USDT,
        "peak_equity_usdt": SEED_EQUITY_USDT,
        "drawdown_pct": 0.0,
        "btc_units": 0.0,
        "usdt_cash": SEED_EQUITY_USDT,
        "target_share": None,
        "daily_history": [],
        "decisions": [],
        "gaps": [],
        "note": ("Отдельный paper-NAV BTC-движка (ADR-118). Виртуальный капитал, "
                 "IS_ADVISORY, вне основной книги и вне kill-switch общего NAV "
                 "по построению. Издержки ребаланса НЕ моделируются (названо честно; "
                 "k-масштаб уже применён продюсером)."),
        "IS_ADVISORY": True,
        "LLM_FORBIDDEN": True,
    }


def _signal_ok(sig: Optional[dict], now: _dt.datetime) -> tuple[bool, str]:
    """Годен ли сигнал продюсера. (ok, причина-если-нет)."""
    if sig is None:
        return False, "no signal (producer has not written target_share.json — engine v0.1 absent?)"
    try:
        gen = _dt.datetime.fromisoformat(str(sig.get("generated_at", "")))
        if gen.tzinfo is None:
            gen = gen.replace(tzinfo=_dt.timezone.utc)
    except Exception:  # noqa: BLE001
        return False, "signal has no readable generated_at"
    age_h = (now - gen).total_seconds() / 3600.0
    if age_h > MAX_SIGNAL_AGE_H:
        return False, f"signal stale ({age_h:.1f}h > {MAX_SIGNAL_AGE_H:g}h)"
    try:
        w = float(sig["target_share_w"])
        p = float(sig["btc_price_usd"])
    except Exception:  # noqa: BLE001
        return False, "signal lacks target_share_w / btc_price_usd"
    if not (0.0 <= w <= 1.0):
        return False, f"target_share_w out of [0,1]: {w}"
    if not (p > 0.0):
        return False, f"btc_price_usd not positive: {p}"
    return True, ""


def run_btc_nav_tick(data_dir: Optional[str | Path] = None, *,
                     now: Optional[_dt.datetime] = None,
                     dry_run: bool = False) -> dict:
    """Один дневной тик бухгалтера. Никогда не бросает; возвращает отчёт."""
    base = Path(data_dir) if data_dir is not None else _PROJECT_ROOT / "data"
    now = now or _dt.datetime.now(_dt.timezone.utc)
    today = now.date().isoformat()
    report: dict = {"as_of": today, "action": "", "reason": "",
                    "ran_at": now.isoformat(), "dry_run": bool(dry_run),
                    "IS_ADVISORY": True, "LLM_FORBIDDEN": True}

    book_path = base / BOOK_FILE
    book = _load(book_path) or _new_book(now)

    sig = _load(base / SIGNAL_FILE)
    ok, why = _signal_ok(sig, now)
    if not ok:
        report["action"] = "gap"
        report["reason"] = why
        # Один GAP на день, не шторм: повторный тик того же дня — no-op.
        if not any(g.get("date") == today for g in book.get("gaps", [])):
            book.setdefault("gaps", []).append({"date": today, "reason": why})
            if not dry_run:
                try:
                    _save(book_path, book)
                except Exception as exc:  # noqa: BLE001
                    report["reason"] += f" (и книга не записалась: {exc})"
        return report

    sig_day = str(sig.get("as_of") or today)
    if any(h.get("date") == sig_day for h in book.get("daily_history", [])):
        report["action"] = "noop"
        report["reason"] = f"day {sig_day} already booked (idempotent)"
        return report

    price = float(sig["btc_price_usd"])
    w = float(sig["target_share_w"])

    # NAV по СЕГОДНЯШНЕЙ цене из вчерашних позиций; затем ребаланс к целевой доле.
    nav = book["btc_units"] * price + book["usdt_cash"]
    prev_share = (book["btc_units"] * price / nav) if nav > 0 else 0.0
    # РЕШЕНИЕ = смена ЦЕЛИ движка, а не ежедневное приведение дрейфа к той же
    # цели (дрейф — механика цены; писать его решением = шум в журнале каждый день).
    prev_target = book.get("target_share")
    new_btc_units = w * nav / price
    new_usdt = (1.0 - w) * nav

    entry = {"date": sig_day, "nav_usdt": round(nav, 2), "btc_price_usd": price,
             "target_share": w, "regime": sig.get("regime"),
             "engine_version": sig.get("engine_version")}
    report["action"] = "would_book" if dry_run else "booked"
    report["nav_usdt"] = round(nav, 2)
    report["target_share"] = w

    if dry_run:
        return report

    book["btc_units"] = new_btc_units
    book["usdt_cash"] = new_usdt
    book["equity_usdt"] = nav
    book["target_share"] = w
    if nav > book.get("peak_equity_usdt", 0.0):
        book["peak_equity_usdt"] = nav
    peak = book["peak_equity_usdt"] or 1.0
    book["drawdown_pct"] = round(max(0.0, (peak - nav) / peak * 100.0), 4)
    book.setdefault("daily_history", []).append(entry)
    if prev_target is None or abs(w - float(prev_target)) > DECISION_EPS:
        book.setdefault("decisions", []).append({
            "date": sig_day, "from_share": round(prev_share, 4),
            "to_share": w, "btc_price_usd": price,
            "reason": sig.get("regime") or "target moved",
        })
    try:
        _save(book_path, book)
    except Exception as exc:  # noqa: BLE001 — запись не удалась = названо
        report["action"] = "write_failed"
        report["reason"] = str(exc)[:160]
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m spa_core.paper_trading.btc_nav",
        description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args(argv)
    report = run_btc_nav_tick(args.data_dir, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"btc_nav: {report['action']}"
              + (f" nav={report.get('nav_usdt')}" if report.get("nav_usdt") else "")
              + (f" w={report.get('target_share')}" if report.get("target_share") is not None else "")
              + (f" ({report['reason']})" if report.get("reason") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
