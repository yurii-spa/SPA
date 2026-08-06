"""intraday_equity.py — 5-минутный сенсор живой просадки (ADR-068, мандат ADR-067).

Закрывает 24-часовое окно слепоты лестницы kill-switch: депег держимого стейбла
через час после цикла суточный расчёт не увидит до утра — сенсор видит за 5 минут.

Оценка (консервативная, только вниз, только из наблюдений):
    est = cash + Σ_p position_p × (1 + min(0, peg_deviation_p)/100)
Накопление yield не добавляется (~0.02%/сутки, ограниченная консервативная
ошибка). Трек НЕ трогается: intraday-бар живёт только в памяти вычисления.

Связка с лестницей — ТОЛЬКО существующие точки правды governance:
`evidenced_drawdown_pct` (общая формула обоих тиров) + `classify_drawdown_pct`
(единый классификатор границ). Ни одного нового порога здесь нет по построению;
пороги SOFT −5% / HARD −10% не меняются — меняется только частота измерения.

Fail-CLOSED в правильную для kill-пути сторону: опасность — сработать на
ВЫДУМАННЫХ данных. Протухшие входы ⇒ UNCHECKED, лестница не вызывается
(суточная проверка цикла остаётся страховкой). Непокрытая peg-мониторингом
позиция ⇒ марк не выдумывается (номинал + coverage=partial): недоизмерение
занижает просадку, не завышает — HARD по измеренной части легитимен.

HARD_KILL ⇒ activate (инъектируемо; в проде — KillSwitchChecker, тот же
механизм, что threat_reactor) + Tier-1 push существующим ключом `kill_switch`.
LLM_FORBIDDEN. Только stdlib. Время — вход (now=).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from spa_core.governance.kill_switch import (
    TIER_HARD_KILL,
    TIER_NONE,
    classify_drawdown_pct,
    evidenced_drawdown_pct,
)
from spa_core.monitoring.architecture_conformance import REPO_ROOT, _parse_iso

REPORT_REL = os.path.join("data", "intraday_equity.json")

PEG_MAX_AGE_MIN = 30.0      # peg_report старше — НЕ ИЗМЕРЕНО (peg_monitor ходит каждые 5м)
POSITIONS_MAX_AGE_H = 30.0  # позиции — якорь последнего цикла; старше = цикл пропал


def _load(rel: str, root: str):
    try:
        return json.load(open(os.path.join(root, rel)))
    except Exception:
        return None


def compute_estimate(positions_doc: dict | None,
                     peg_doc: dict | None,
                     curve_doc: dict | None,
                     now: dt.datetime) -> dict:
    """Чистая оценка + вердикт лестницы. Все входы — параметры (тестируемо)."""
    unchecked: list[dict] = []

    # ── свежесть входов (время — вход, не окружение) ─────────────────────────
    if positions_doc is None:
        unchecked.append({"input": "current_positions", "reason": "файл не прочитан"})
    else:
        ts = _parse_iso(positions_doc.get("generated_at"))
        if ts is None:
            unchecked.append({"input": "current_positions", "reason": "нет generated_at"})
        elif (now - ts).total_seconds() / 3600.0 > POSITIONS_MAX_AGE_H:
            unchecked.append({"input": "current_positions",
                              "reason": f"старше {POSITIONS_MAX_AGE_H}ч — цикл пропал, "
                                        f"якоря нет"})
    if peg_doc is None:
        unchecked.append({"input": "peg_report", "reason": "файл не прочитан"})
    else:
        ts = _parse_iso(peg_doc.get("generated_at"))
        if ts is None:
            unchecked.append({"input": "peg_report", "reason": "нет generated_at"})
        elif (now - ts).total_seconds() / 60.0 > PEG_MAX_AGE_MIN:
            unchecked.append({"input": "peg_report",
                              "reason": f"старше {PEG_MAX_AGE_MIN:.0f} мин — живым не считается"})
    daily = (curve_doc or {}).get("daily")
    if not isinstance(daily, list) or not daily:
        unchecked.append({"input": "equity_curve_daily", "reason": "кривая пуста/не прочитана"})

    if unchecked:
        return {"status": "UNCHECKED", "unchecked": unchecked,
                "tier": None, "drawdown_pct": None,
                "note": "лестница НЕ вызывалась — не измерено ≠ измерено-хорошее; "
                        "суточная проверка цикла остаётся страховкой"}

    # ── марк-дауны по живым peg-отклонениям ──────────────────────────────────
    positions = positions_doc.get("positions") or {}
    cash = float(positions_doc.get("cash_usd") or 0.0)
    dev_by_adapter: dict[str, float] = {}
    for st in (peg_doc.get("statuses") or []):
        aid = st.get("adapter_id")
        try:
            dev = float(st.get("deviation_pct"))
        except (TypeError, ValueError):
            continue
        if aid:
            dev_by_adapter[aid] = dev

    marks, uncovered = [], []
    est = cash
    for proto, usd in positions.items():
        usd = float(usd)
        dev = dev_by_adapter.get(proto)
        if dev is None:
            uncovered.append(proto)
            est += usd  # номинал: марк НЕ выдумывается (недоизмерение занижает DD)
            continue
        markdown = min(0.0, dev) / 100.0
        est += usd * (1.0 + markdown)
        if markdown < 0.0:
            marks.append({"protocol": proto, "position_usd": usd,
                          "deviation_pct": dev,
                          "markdown_usd": round(usd * markdown, 2)})

    # ── лестница: общая формула + единый классификатор (ноль новой логики) ──
    intraday_bar = {"date": now.date().isoformat(),
                    "close_equity": est, "source": "intraday_sensor"}
    dd = evidenced_drawdown_pct(list(daily) + [intraday_bar])
    tier, reason = classify_drawdown_pct(dd)

    return {"status": "OK",
            "equity_estimate_usd": round(est, 2),
            "cash_usd": round(cash, 2),
            "marks": marks,
            "coverage": ("full" if not uncovered else "partial"),
            "uncovered_positions": sorted(uncovered),
            "drawdown_pct": (round(dd, 4) if dd is not None else None),
            "tier": tier,
            "tier_reason": reason,
            "unchecked": [],
            "note": "оценка консервативная (без накопления yield, без марк-апов); "
                    "трек не изменяется"}


def _activate_prod(root: str, reason: str) -> bool:
    """Прод-активация: тот же механизм, что threat_reactor. Never raises."""
    try:
        from spa_core.governance.kill_switch import KillSwitchChecker
        KillSwitchChecker(data_dir=os.path.join(root, "data")).activate_kill_switch(reason)
        try:
            from spa_core.telegram import push_policy
            push_policy.push_critical(
                "kill_switch", "CRITICAL",
                "SPA Intraday Sensor — HARD KILL",
                reason, dedup_key=f"intraday:{reason[:80]}")
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001
        return False


def run(root: str = REPO_ROOT, now: dt.datetime | None = None,
        activate=None, write: bool = True) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    report = compute_estimate(
        _load("data/current_positions.json", root),
        _load("data/peg_report.json", root),
        _load("data/equity_curve_daily.json", root),
        now)
    report["generated_at"] = now.isoformat()
    report["adr"] = "ADR-068"

    if report.get("tier") == TIER_HARD_KILL:
        reason = (f"intraday drawdown {report['drawdown_pct']}% ≥ HARD: "
                  f"{report.get('tier_reason')} | est=${report['equity_estimate_usd']} "
                  f"| marks={report.get('marks')}")
        act = activate if activate is not None else _activate_prod
        report["kill_activated"] = bool(act(root, reason))

    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(report, os.path.join(root, REPORT_REL))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", "--once", action="store_true", dest="run")
    ap.add_argument("--root", default=REPO_ROOT)
    args = ap.parse_args(argv)
    if not args.run:
        ap.print_help()
        return 0
    r = run(root=args.root)
    dd = r.get("drawdown_pct")
    print(f"intraday_equity: {r['status']} | est=${r.get('equity_estimate_usd')} | "
          f"dd={dd}% | tier={r.get('tier')} | coverage={r.get('coverage')}")
    for u in r.get("unchecked", []):
        print(f"  [UNCHECKED] {u['input']}: {u['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
