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


COMPLETENESS_SCHEMA = 1


def analyze_completeness(root: str = REPO_ROOT,
                         now: dt.datetime | None = None) -> dict:
    """Полнота архива по ЗАКРЫТЫМ дням — вопрос, на который возраст не отвечает.

    Возрастной бюджет B2 сторожа архитектуры судит о `outcomes.jsonl` по mtime, и
    для ЭТОГО артефакта это не тот вопрос: он не снимок, а append-only архив, где
    день без evidenced-бара НЕ занимается сознательно (`append_daily_outcome`:
    «дату не занимаем, догоним позже»). Значит возрастной бюджет обязан терпеть
    сутки ожидания + такт производителя (31ч) — и ровно столько же он терпит
    настоящую ОСТАНОВКУ записи. Здесь спрашивается другое: есть ли строка за
    каждый закрытый день, у которого был evidenced-бар. Такая проверка молчит на
    исправном ожидании (сегодняшний день ещё не закрыт; день без evidenced-бара
    строки не ждёт — 07-19/07-27 fail-closed by design) и краснеет в первые же
    часы после настоящего сбоя записи. Обе проверки остаются: зелёный ответ на
    свой вопрос не есть ответ на нужный.

    Время — ВХОД (`now=`), а не окружение: от него зависит, какой день закрыт.

    Якорь — ПЕРВЫЙ день архива: до него производителя не было, и требовать от
    него июньские дни значило бы сочинить находку. Цена якоря названа вслух и не
    замаскирована: усечение архива с головы двигает якорь вперёд и такую дыру
    скрывает — append-only-файл этого делать не должен, но проверка полноты
    сама по себе от усечения не защищает (`archived_days` печатается, чтобы
    сжавшийся архив был виден глазом).

    Вердикты: `measured: False` — мерить не от чего (пустой архив / кривая не
    прочитана), НИКОГДА не «полно». Молчаливого «всё в порядке» здесь нет.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(dt.timezone.utc).date()
    base = {"schema": COMPLETENESS_SCHEMA, "today": today.isoformat()}

    have = sorted({str(r.get("date")) for r in load_outcomes(root) if r.get("date")})
    if not have:
        return {**base, "measured": False, "archived_days": 0,
                "reason": "архив исходов пуст или отсутствует — якоря нет, полноту "
                          "мерить не от чего (на вопрос «файл вообще есть?» отвечает "
                          "возрастной бюджет B2, и это его вопрос)"}

    curve = _load("data/equity_curve_daily.json", root)
    if not curve or not isinstance(curve.get("daily"), list):
        return {**base, "measured": False, "archived_days": len(have),
                "anchor_date": have[0],
                "reason": "equity_curve_daily не прочитан — какие дни ОБЯЗАНЫ иметь "
                          "строку, неизвестно; «нет источника правды» это не «полно»"}

    try:
        from spa_core.paper_trading.track_evidence import is_evidenced_bar
        evidenced = sorted({str(b.get("date")) for b in curve["daily"]
                            if isinstance(b, dict) and b.get("date")
                            and is_evidenced_bar(b, today=today)})
    except Exception as e:  # noqa: BLE001
        return {**base, "measured": False, "archived_days": len(have),
                "anchor_date": have[0],
                "reason": f"evidenced-бары не измерены: {e}"}

    anchor = have[0]
    today_s = today.isoformat()
    # Закрытый день — строго РАНЬШЕ сегодняшнего: сегодняшний ещё может быть
    # дописан своим же тактом, и требовать его — та самая ложная тревога, из-за
    # которой возрастной бюджет пришлось растягивать до 31ч.
    expected = [d for d in evidenced if anchor <= d < today_s]
    present = set(have)
    missing = [d for d in expected if d not in present]
    return {**base, "measured": True, "anchor_date": anchor,
            "archived_days": len(have), "expected_days": len(expected),
            "present_days": len(expected) - len(missing),
            "missing_days": missing, "complete": not missing,
            "reason": ("за каждый закрытый evidenced-день с якоря архива есть строка"
                       if not missing else
                       f"строк нет за {len(missing)} закрыт(ых) evidenced-дн(я/ей): "
                       + ", ".join(missing[:10])
                       + (" …" if len(missing) > 10 else ""))}


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
