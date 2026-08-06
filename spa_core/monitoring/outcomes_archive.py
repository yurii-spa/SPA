"""outcomes_archive.py — правая половина hit-rate офиса (ADR-066 Ф4 / очередь ADR-067).

Архив вердиктов (что офис ГОВОРИЛ по дням) уже пишется; этот модуль копит
вторую половину пары — что ВЫШЛО на самом деле: append-only
`data/investment_os/outcomes.jsonl`, одна строка на календарный день:

    {"date", "equity_close", "daily_return_pct", "positions", "cash_usd",
     "apy_evidenced_pct", "posture_office", "sources"}

Правила честности:
  - строка дня пишется ОДИН раз (идемпотентно по date) и только из
    наблюдённых файлов; недостающее поле пишется null с именем причины в
    sources — никогда не выдумывается;
  - equity — только evidenced-бар кривой за этот день (фильтр трека);
  - постура — из архива вердиктов chief за этот день (если он молчал — null,
    и это видно);
  - пишет decision_loop (6ч, 4 шанса в день догнать) — money-path
    (cycle_runner) не тронут.

Потребитель — loop_retro.analyze_outcomes: сопоставляет постуру дня d с
форвардной доходностью d+1..d+H и снимает вечные UNCHECKED hit-rate'а,
как только пар набирается достаточно. LLM_FORBIDDEN. stdlib. Время — вход.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import json
import os

from spa_core.monitoring.architecture_conformance import REPO_ROOT

OUTCOMES_REL = os.path.join("data", "investment_os", "outcomes.jsonl")


def _load(rel: str, root: str):
    try:
        return json.load(open(os.path.join(root, rel)))
    except Exception:
        return None


def load_outcomes(root: str = REPO_ROOT) -> list[dict]:
    path = os.path.join(root, OUTCOMES_REL)
    out: list[dict] = []
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return out


def build_outcome_line(root: str, day: str) -> dict:
    """Строка исхода за календарный день `day` — только из наблюдённого."""
    sources: dict[str, str] = {}

    equity_close = daily_return = None
    curve = _load("data/equity_curve_daily.json", root)
    if curve and isinstance(curve.get("daily"), list):
        try:
            from spa_core.paper_trading.track_evidence import is_evidenced_bar
            bars = [b for b in curve["daily"]
                    if isinstance(b, dict) and str(b.get("date")) == day]
            ev = [b for b in bars if is_evidenced_bar(b)]
            if ev:
                equity_close = float(ev[-1].get("close_equity") or ev[-1].get("equity"))
                dr = ev[-1].get("daily_return_pct")
                daily_return = float(dr) if dr is not None else None
                sources["equity"] = "equity_curve_daily:evidenced"
            elif bars:
                sources["equity"] = "бар дня не evidenced — не считается"
            else:
                sources["equity"] = "бара за день нет"
        except Exception as e:  # noqa: BLE001
            sources["equity"] = f"кривая не разобрана: {e}"
    else:
        sources["equity"] = "equity_curve_daily не прочитан"

    positions = cash = None
    pos = _load("data/current_positions.json", root)
    if pos and str(pos.get("generated_at", ""))[:10] == day:
        positions = {k: round(float(v), 2) for k, v in (pos.get("positions") or {}).items()}
        cash = float(pos.get("cash_usd") or 0.0)
        sources["positions"] = "current_positions (тот же день)"
    else:
        sources["positions"] = "current_positions не за этот день — не приписываем"

    apy = None
    hist_path = os.path.join(root, "data", "allocation_rationale_history.jsonl")
    if os.path.exists(hist_path):
        try:
            with open(hist_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(rec.get("cycle_date")) == day and rec.get("apy_evidenced_pct"):
                        apy = rec["apy_evidenced_pct"]
            sources["apy"] = ("rationale_history (evidenced)" if apy
                              else "строки за день нет")
        except Exception as e:  # noqa: BLE001
            sources["apy"] = f"history не разобрана: {e}"
    else:
        sources["apy"] = "rationale_history отсутствует"

    posture = None
    vpath = os.path.join(root, "data", "investment_os", "chief_investment_verdicts.jsonl")
    if os.path.exists(vpath):
        try:
            with open(vpath, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(rec.get("date")) == day and rec.get("posture"):
                        posture = rec["posture"]
            sources["posture"] = ("chief_verdicts" if posture
                                  else "вердикта за день нет")
        except Exception as e:  # noqa: BLE001
            sources["posture"] = f"verdicts не разобраны: {e}"
    else:
        sources["posture"] = "архив вердиктов отсутствует"

    return {"schema": 1, "date": day, "equity_close": equity_close,
            "daily_return_pct": daily_return, "positions": positions,
            "cash_usd": cash, "apy_evidenced_pct": apy,
            "posture_office": posture, "sources": sources}


def append_daily_outcome(root: str = REPO_ROOT,
                         now: dt.datetime | None = None) -> dict:
    """Дописать строку за СЕГОДНЯ, если её ещё нет. Идемпотентно по дате.

    Возвращает {"appended": bool, "date": ..., "line"| "reason"}.
    День без evidenced-equity НЕ пишется (пустая строка исхода бессмысленна и
    навсегда заняла бы дату) — decision_loop дозапишет позже тем же днём.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    day = now.date().isoformat()
    existing = {str(r.get("date")) for r in load_outcomes(root)}
    if day in existing:
        return {"appended": False, "date": day, "reason": "уже записан"}
    line = build_outcome_line(root, day)
    if line["equity_close"] is None:
        return {"appended": False, "date": day,
                "reason": f"нет evidenced-equity за день ({line['sources'].get('equity')}) — "
                          f"дату не занимаем, догоним позже"}
    path = os.path.join(root, OUTCOMES_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return {"appended": True, "date": day, "line": line}
