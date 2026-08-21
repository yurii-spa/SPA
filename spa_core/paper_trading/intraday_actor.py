"""spa_core/paper_trading/intraday_actor.py — DERISK рукавов B/C между циклами (ADR-114).

ADR-104 сделал СЛЕЖЕНИЕ непрерывным, но двигать книги умел только суточный цикл —
между циклами движение вниз лишь запрещало наращивание, а сброс риска ждал утра.
Этот актор закрывает разрыв ADR-055 (DERISK всегда быстро) для рукавов B/C.

Границы (не нарушаются этим модулем):

  * ОСНОВНАЯ paper-книга (`current_positions.json`) НЕ трогается — домен
    `cycle_runner` с его гейтами; актор работает только с книгами рукавов
    (`hy_paper_trading.json`, `lp_paper_trading.json`).
  * Триггер — РОВНО постура ``MOVEMENT_DERISK`` директивы (движение, пойманное
    непрерывными сенсорами ADR-104). Суточный house-view RED триггером не
    является: на него отвечает штатный цикл (ACT редко) — обратный контроль
    в тестах.
  * Действие — только ВНИЗ (закрыть позиции). Открывать/наращивать актор не
    умеет по построению; направление «вверх» остаётся за циклом под RiskPolicy.
  * Equity закрытием НЕ меняется: внутридневное начисление было бы изобретённой
    ценой (начисляет только цикл по живому APY; пустая книга начисляет ноль
    сама — ADR-103).
  * Идемпотентность = анти-шторм: пустая книга ⇒ no-op без записи.
  * Fail-safe раздельно: нечитаемая директива ⇒ нейтраль ⇒ no-op; нечитаемый
    рукав ⇒ пропущен С ПРИЧИНОЙ, сосед обрабатывается; никогда не бросает.

LLM_FORBIDDEN · stdlib only · атомарная запись (tmp + os.replace).

CLI:  python3 -m spa_core.paper_trading.intraday_actor [--dry-run] [--json]
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

#: Книги рукавов, которыми актор ВПРАВЕ управлять. Основной книги здесь нет
#: и быть не может (см. границы в докстринге).
SLEEVE_FILES = {
    "B": "hy_paper_trading.json",
    "C": "lp_paper_trading.json",
}

#: Единственная постура-триггер (ADR-114): движение, пойманное непрерывными
#: сенсорами. Список закрыт намеренно — «RED из суточного house-view» сюда
#: добавлять нельзя, иначе актор начнёт дублировать суточный цикл.
_TRIGGER_POSTURE = "MOVEMENT_DERISK"


def _load(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except Exception:  # noqa: BLE001 — нечитаемый рукав = пропуск с причиной
        return None


def _save(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def run_intraday_actor(data_dir: Optional[str | Path] = None, *,
                       now: Optional[_dt.datetime] = None,
                       dry_run: bool = False) -> dict:
    """Один проход актора. Никогда не бросает; возвращает отчёт.

    Отчёт: {"triggered", "reason", "sleeves": {name: {...}}, "ran_at", "dry_run"}.
    """
    base = Path(data_dir) if data_dir is not None else _PROJECT_ROOT / "data"
    now = now or _dt.datetime.now(_dt.timezone.utc)
    report: dict = {"triggered": False, "reason": "", "sleeves": {},
                    "ran_at": now.isoformat(), "dry_run": bool(dry_run),
                    "LLM_FORBIDDEN": True}

    try:
        from spa_core.investment_os.directive import load_directive
        directive = load_directive(base, now=now)
    except Exception as exc:  # noqa: BLE001 — нечитаемая директива ⇒ нейтраль
        report["reason"] = f"directive unreadable ({type(exc).__name__}) — no action"
        return report

    if (directive.get("posture") or "") != _TRIGGER_POSTURE:
        report["reason"] = (f"no intraday movement (posture="
                            f"{directive.get('posture')!r}) — sleeves untouched")
        return report

    report["triggered"] = True
    report["reason"] = directive.get("reason") or "movement derisk"

    for sleeve, fname in SLEEVE_FILES.items():
        path = base / fname
        entry: dict = {"file": fname}
        doc = _load(path)
        if doc is None:
            # Нечитаемый/отсутствующий рукав — пропуск С ПРИЧИНОЙ, не падение:
            # один битый файл не должен лишать защиты соседний рукав.
            entry["action"] = "skipped"
            entry["why"] = ("book missing" if not path.exists()
                            else "book unreadable")
            report["sleeves"][sleeve] = entry
            continue
        positions = doc.get("positions") or []
        if not positions:
            # Идемпотентность = анти-шторм: закрывать нечего — записи нет.
            entry["action"] = "noop"
            entry["why"] = "book already empty"
            report["sleeves"][sleeve] = entry
            continue
        closed = [{"protocol": p.get("protocol"),
                   "notional_usd": p.get("notional_usd")}
                  for p in positions if isinstance(p, dict)]
        entry["action"] = "would_close" if dry_run else "closed"
        entry["closed"] = closed
        entry["count"] = len(closed)
        if not dry_run:
            doc["positions"] = []
            doc.setdefault("intraday_actions", []).append({
                "ts": now.isoformat(),
                "action": "derisk_close_all",
                "reason": report["reason"],
                "closed": closed,
                # ADR-114: equity намеренно НЕ трогаем — внутридневное
                # начисление было бы изобретённой ценой.
            })
            doc["LLM_FORBIDDEN"] = True
            try:
                _save(path, doc)
            except Exception as exc:  # noqa: BLE001 — запись не удалась = названо
                entry["action"] = "write_failed"
                entry["why"] = str(exc)[:120]
        report["sleeves"][sleeve] = entry

    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m spa_core.paper_trading.intraday_actor",
        description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args(argv)

    report = run_intraday_actor(args.data_dir, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(("TRIGGERED: " if report["triggered"] else "quiet: ") + report["reason"])
        for sleeve, e in report["sleeves"].items():
            print(f"  [{sleeve}] {e.get('action')}"
                  + (f" ×{e.get('count')}" if e.get("count") else "")
                  + (f" ({e.get('why')})" if e.get("why") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
