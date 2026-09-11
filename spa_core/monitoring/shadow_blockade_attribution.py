"""spa_core/monitoring/shadow_blockade_attribution.py — ЧТО именно держит
SHADOW-замер ADR-060 закрытым: дырка, которую крутит владелец, или предложение,
которое тень сама делает каждый день (заказ карточки CIO, гэп G5).

`shadow_trigger_eval.arming_blockade` (цикл #487) ответил на вопрос, которого ни
у кого не было: взвод НЕДОСТИЖИМ ожиданием, и назвал ``necessary_blockers`` —
гейты, отказавшие на 100 % существенных дней. Мера верная и честная: не сняв
такой гейт, ACT получить нельзя. Но из неё читается вывод, которого в ней нет.

**Замер с хоста 2026-09-09 (34 записи истории, `origin/main` 4a077cde0).**
Блокада называет `week_turnover_ok` (21 из 21 дня, 100 %) и говорит «нужен ответ
владельца». `week_turnover_ok` — это ДЫРКА: недельный бюджет оборота
(``max_turnover_per_week`` = 25 % капитала), число, которое владелец может
поднять. Но условие гейта — ``(оборот_за_неделю + ход) / капитал ≤ 25 %``, и у
него ДВА слагаемых с РАЗНЫМ происхождением:

* ``оборот_за_неделю`` приходит из ЖИВОЙ книги (``trades.json``) — это чужая
  история, тень её не производила;
* ``ход`` — собственное предложение тени в этот день.

Разложение по слагаемым переворачивает адресата. Замер по 21 существенному дню:

* **на 11 днях связывает СОБСТВЕННЫЙ ход тени** — он один, без всякой чужой
  истории, больше ВСЕГО недельного бюджета;
* на 5 днях связывает история живой книги;
* на 5 днях самодостаточны обе стороны (``joint``);
* на **11 из 21** дня живой оборот был ровно **$0** — крутить бюджет там не от
  чего вовсе;
* медиана предложенного хода — **35 % капитала**, максимум 60 %, при потолке на
  один ход 15 %: **19 из 21** дня ход превышает потолок на ход, **15 из 21** —
  весь недельный бюджет.

То есть поднять недельный бюджет так, чтобы блокада снялась, значит разрешить
перекладывать 35–60 % книги ЕЖЕДНЕВНО — отменить анти-чёрн целиком, а не
настроить его. Дырка названа верно как НЕОБХОДИМОЕ условие и неверно как АДРЕС
починки.

**Причина лежит выше по течению и меряется отдельно: цель неустойчива.** Дневной
переворот самой цели (one-sided, доля капитала) — медиана **20 %**, максимум
**50 %**; якорь в $40 тыс. перескакивает `aave_v3` ↔ `compound_v3` через день
(03.09 aave_v3 40k → 04.09 compound_v3 40k → 05.09 aave_v3 40k). Анти-чёрн не
может пропустить такую цель ни при каком бюджете — и это ответ на второй вопрос
ТЗ CIO («экономически оправдано ли переходить прямо сейчас»), которого блокада
не даёт.

**Что делает этот модуль.** Берёт ТУ ЖЕ перепись (`arming_blockade`), те же
состояния гейтов (`gate_state`) и то же правило существенности — второго
определения здесь нет намеренно — и добавляет ОДИН вопрос: у каждого отказа
назвать ПРОВЕНАНС связывающего входа.

Три ловушки, названные заранее и разобранные замером, а не фразой:

1. **«Гейт отказал» ≠ «его вход и есть причина».** У `week_turnover_ok` два
   слагаемых, и связывает то, которое само по себе выносит за бюджет. Если ни
   одно само по себе не выносит — исход ``joint``, а не выбор в пользу удобного.
2. **Реконструкция чужого входа — сама прибор, и у неё своя цена ошибки.**
   ``оборот_за_неделю`` в строке истории НЕ ЗАПИСАН (замер: ни одного поля на 34
   строки), поэтому он восстанавливается из ``trades.json`` — ТЕМ ЖЕ
   ``_history_from_trades``, которым его считал писатель. Там, где состояние
   гейта известно, реконструкция СВЕРЯЕТСЯ с ним (21 из 21), и согласие
   печатается числом; ниже порога ⇒ ``UNMEASURED``, а не молчаливое доверие.

   **И сразу оговорка о СИЛЕ этого согласия, потому что молчать о ней значило бы
   украсить прибор.** Недельный гейт на всём окне отказал 21 раз из 21 — то есть
   население сверки одностороннее, и согласие «21/21» подтверждает лишь, что
   реконструкция не выдумывает ПРОХОД там, где был отказ. Разделяющую силу даёт
   не оно, а контроль заглядывания вперёд ниже: **на 10 из 21 дня** снятие
   верхней границы окна меняет атрибуцию. Именно это число, а не согласие,
   доказывает, что поправка нужна.

   Ловушка здесь измерена на себе: первая редакция модуля брала
   ``_history_from_trades`` как есть и на 6 августа получала живой оборот
   $599,868 вместо настоящих $0 — окно у писателя ограничено только СНИЗУ. В
   проде это безвредно (``now`` всегда настоящее, и ни один вызывающий не
   передаёт ``now=`` вовсе), но ретроспективный прогон через него смотрит в
   будущее. Верхняя граница поставлена НА ВХОДЕ — одно определение недели
   сохранено, заглядывание закрыто.
3. **«Не измерено» — третий исход, не «прошло».** День без ``gates`` и без
   ``reasons`` не считается пройденным; день, чей провенанс не разрешён,
   попадает в ``unresolved`` и НАЗЫВАЕТСЯ. Перевес неразрешённого над
   разрешённым у названного блокера ⇒ ``UNMEASURED`` с причиной.

**ADVISORY.** Ничего не гейтит и капитал не двигает: ни пороги ``TriggerParams``,
ни ``ready_to_arm``, ни RiskPolicy здесь не трогаются. Модуль только НАЗЫВАЕТ,
куда смотреть; подъём бюджета или починка цели — money-path и решение владельца.
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.utils.observation import observed, observed_number

from spa_core.paper_trading.shadow_trigger_eval import (
    _ALL_GATES,
    arming_blockade,
    gate_state,
    load_history,
)

log = logging.getLogger("spa.monitoring.shadow_blockade_attribution")

VERSION = "shadow-blockade-attribution-v1"

#: Провенанс ВХОДА гейта: чьё решение он отражает.
OWN = "own"            # только собственное предложение тени этого дня
IMPORTED = "imported"  # только история ЖИВОЙ книги (тень её не производила)
MIXED = "mixed"        # оба слагаемых — связывающее выясняется замером за день

#: Карта провенанса по гейтам `rebalance_economics.explain_move`.
#:
#: Полнота держится храповиком (`test_shadow_blockade_attribution.py`): у каждого
#: ключа `_ALL_GATES` здесь обязана быть строка. Новый гейт без провенанса иначе
#: молча выпал бы из атрибуции — то есть занижал бы ровно ту величину, ради
#: которой модуль написан.
GATE_PROVENANCE: Dict[str, str] = {
    "has_legs": OWN,
    "gain_above_band": OWN,
    "payback_within_horizon": OWN,
    "move_turnover_ok": OWN,
    "target_fully_evidenced": OWN,
    "cooldown_ok": IMPORTED,      # days_since_last_act — из trades.json живой книги
    "min_hold_ok": IMPORTED,      # position_age_days — оттуда же
    "week_turnover_ok": MIXED,    # (оборот живой книги за неделю) + (свой ход)
}

STATUS_OK = "OK"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

CAUSE_OWN = "own_proposal"      # связывает СВОЁ предложение тени
CAUSE_IMPORTED = "live_history"  # связывает история живой книги
CAUSE_JOINT = "joint"
CAUSE_UNMEASURED = "unmeasured"

#: Ниже этой доли согласия реконструкция чужого входа не признаётся пригодной.
#: Не «похоже на правду», а измеренная доля совпадений с известным состоянием.
MIN_RECONSTRUCTION_AGREEMENT = 0.9

TRADES_FILENAME = "trades.json"
OUTPUT_FILENAME = "shadow_blockade_attribution.json"


def _load_trades(data_dir: Path) -> Tuple[Optional[List[dict]], str]:
    """Журнал ходов живой книги. ``None`` — читать нечем, и это НАЗЫВАЕТСЯ."""
    path = Path(data_dir) / TRADES_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"{TRADES_FILENAME} отсутствует"
    except Exception as exc:  # noqa: BLE001 — None ⇒ UNMEASURED, не догадка
        return None, f"{TRADES_FILENAME} нечитаем ({exc})"
    trades = raw if isinstance(raw, list) else raw.get("trades")
    if not isinstance(trades, list):
        return None, f"{TRADES_FILENAME} не несёт списка ходов"
    return trades, ""


def _day_end(cycle_date: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(f"{cycle_date}T23:59:59+00:00")
    except Exception:  # noqa: BLE001
        return None


def _parse_trade_ts(trade: dict) -> Optional[datetime]:
    raw = trade.get("ts")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _live_turnover_at(trades: List[dict], when: datetime,
                      *, bounded: bool = True) -> Optional[float]:
    """Недельный оборот живой книги на момент ``when``.

    Правило окна берётся у ``_history_from_trades`` — ТЕМ ЖЕ кодом, которым его
    считал писатель вердикта. Своя копия правила была бы вторым определением
    (ровно тот дрейф, из-за которого «книга ↔ реестр» врали три месяца).

    **Но у писателя окно ограничено только СНИЗУ** (``ts >= week_ago``, верхней
    границы нет). В проде это безвредно: ``now`` там всегда настоящее, будущих
    ходов в журнале не бывает — ни один вызывающий ``write_shadow_rationale``
    не передаёт ``now=`` вовсе (замер 2026-09-09). Но параметр ``now`` тут есть,
    и ретроспективный прогон через него ЗАГЛЯДЫВАЕТ ВПЕРЁД: спросив «каков был
    недельный оборот 6 августа», получаешь сумму, включающую весь сентябрь
    ($599,868 против настоящих $0 — первая редакция этого модуля на том и
    попалась).

    Поэтому верхняя граница ставится ЗДЕСЬ, на ВХОДЕ, а не переписыванием
    правила: журнал урезается до ходов, случившихся не позже ``when``. Одно
    определение недели сохраняется, заглядывание закрыто.

    ``bounded=False`` воспроизводит незакрытое окно — им меряется, на скольких
    днях заглядывание вперёд меняло бы ответ (положительный контроль).
    """
    from spa_core.paper_trading.allocation_rationale import _history_from_trades

    window = trades if not bounded else [
        t for t in trades
        if (ts := _parse_trade_ts(t)) is not None and ts <= when
    ]
    turnover = observed_number(_history_from_trades(window, when),
                               "turnover_last_week_usd")
    # `None` — счётчик оборота поля не дал; ноль оборота у него же означает
    # «сделок в окне не было». Ниже по коду `live_usd is None` УЖЕ отдельная
    # ветка причины, поэтому отсутствие доезжает до вердикта как отсутствие.
    return turnover


def _one_sided(prev: Dict[str, float], cur: Dict[str, float]) -> float:
    """Насколько цель переставили: сумма только ПРИРОСТОВ (как `turnover`)."""
    keys = set(prev) | set(cur)
    return sum(max(0.0, float(cur.get(k, 0.0) or 0.0) - float(prev.get(k, 0.0) or 0.0))
               for k in keys)


def _median_move_pct(doc: dict) -> str:
    """Медианный предложенный ход словами. ``None`` не выдаётся за число."""
    med = ((doc.get("target_instability") or {})
           .get("proposed_move_frac") or {}).get("median")
    return "не измерено" if med is None else f"{med:.0%}"


def _resolve_week_gate(live_usd: float, move_usd: float, budget_usd: float) -> str:
    """Какое слагаемое СВЯЗЫВАЕТ отказ недельного бюджета.

    Вопрос не «что больше», а «что само по себе уже выносит за бюджет»: если
    хватает одного слагаемого, второе на исход не влияет вовсе.
    """
    live_alone = live_usd > budget_usd
    move_alone = move_usd > budget_usd
    if live_alone and move_alone:
        return CAUSE_JOINT      # обе стороны самодостаточны — ни одна не «та самая»
    if live_alone:
        return CAUSE_IMPORTED
    if move_alone:
        return CAUSE_OWN
    if live_usd + move_usd > budget_usd:
        return CAUSE_JOINT      # выносит только сумма
    return ""                   # гейт не должен был отказать — расхождение


def attribute(
    data_dir: Path,
    *,
    now: Optional[datetime] = None,
    params=None,
    book_id: Optional[str] = None,
) -> dict:
    """Разложить блокаду взвода по провенансу связывающего входа.

    ``now`` — вход, а не окружение: обе стороны замера закрепляются вызывающим
    (правило `.claude/rules/deployment.md` про время в тестах).
    """
    now = now or datetime.now(timezone.utc)
    if params is None:
        from spa_core.allocator.rebalance_economics import TriggerParams
        params = TriggerParams.for_mode()

    doc: dict = {
        "generated_at": now.isoformat(),
        "version": VERSION,
        "mode": "ADVISORY",
        "note": ("Заказ G5 карточки CIO. НИЧЕГО не гейтит: пороги TriggerParams, "
                 "ready_to_arm и RiskPolicy не трогаются. Модуль называет, КУДА "
                 "смотреть, — подъём бюджета или починка цели решаются владельцем."),
        "status": STATUS_UNMEASURED,
        "findings": [],
        # Все объявленные шагу 0-офис ключи заводятся СРАЗУ. Ранний выход по
        # третьему исходу иначе оставлял бы артефакт без части схемы, и сверка
        # схемы краснела бы на ЧЕСТНОМ «не измерено» — то есть наказывала бы
        # ровно за тот исход, ради которого она нужна.
        "named_blockers": [],
        "binding_cause": CAUSE_UNMEASURED,
        "material_days": 0,
        "gate_attribution": [],
        "target_instability": {},
        "lookahead_control": {"days_attribution_would_flip": None, "dates": []},
        "unmeasured_days": [],
    }

    records, bad_lines = load_history(Path(data_dir), book_id)
    doc["corrupt_history_lines"] = bad_lines
    if not records:
        doc["unmeasured_reason"] = "история вердиктов пуста — раскладывать нечего"
        return doc

    blockade = arming_blockade(
        records,
        observed_days=len(records),
        min_days=0,
        acts_scored=0,
    )
    named = list(blockade.get("necessary_blockers") or [])
    doc["blockade_verdict"] = blockade.get("verdict")
    doc["named_blockers"] = named
    doc["material_days"] = int(blockade.get("material_days") or 0)

    trades, trades_why = _load_trades(Path(data_dir))

    # ── проход по дням: провенанс каждого отказа ───────────────────────────
    per_gate: Dict[str, Dict[str, int]] = {
        g: {"refused_days": 0, CAUSE_OWN: 0, CAUSE_IMPORTED: 0,
            CAUSE_JOINT: 0, "unresolved": 0}
        for g in sorted(_ALL_GATES) if g != "has_legs"
    }
    unmeasured_days: List[str] = []
    recon_checked = 0
    recon_agreed = 0
    churn: List[float] = []
    lookahead_flips: List[str] = []
    move_fracs: List[float] = []
    prev_target: Optional[Dict[str, float]] = None
    days: List[dict] = []

    for rec in records:
        date = str(rec.get("cycle_date") or "")
        capital = observed_number(rec, "capital_usd")
        if capital is None or capital <= 0.0:
            # Прежде здесь стояло `or 0.0) or 1.0`: строка без капитала считалась
            # ПО ОДНОМУ ДОЛЛАРУ, и каждая доля дня — оборот, метание, бюджет —
            # получалась в сотни раз больше настоящей, оставаясь на вид числом.
            # День без капитала мерить нечем (инвариант #17).
            unmeasured_days.append(date)
            continue
        target = {str(k): float(v or 0.0)
                  for k, v in (observed(rec, "target_positions", kind=dict) or {}).items()}
        if prev_target is not None:
            churn.append(_one_sided(prev_target, target) / capital)
        prev_target = target

        state, source = gate_state(rec)
        if state is None:
            unmeasured_days.append(date)
            continue
        if not state.get("has_legs", True):
            continue                      # тривиальный HOLD — решать было нечего

        move_usd = observed_number(rec, "turnover_usd")
        if move_usd is None:
            # «Оборота нет» и «оборот не записан» — разные вещи: первое говорит,
            # что день ничего не двигал, второе не говорит ничего.
            unmeasured_days.append(date)
            continue
        move_fracs.append(move_usd / capital)
        budget_usd = float(params.max_turnover_per_week) * capital

        live_usd: Optional[float] = None
        live_unbounded: Optional[float] = None
        when = _day_end(date)
        if trades is not None and when is not None:
            live_usd = _live_turnover_at(trades, when)
            live_unbounded = _live_turnover_at(trades, when, bounded=False)
            if _resolve_week_gate(live_usd, move_usd, budget_usd) != \
                    _resolve_week_gate(live_unbounded, move_usd, budget_usd):
                lookahead_flips.append(date)

        row = {"date": date, "gate_source": source, "move_usd": round(move_usd, 2),
               "move_frac": round(move_usd / capital, 6),
               "week_budget_usd": round(budget_usd, 2),
               "live_week_turnover_usd": (None if live_usd is None
                                          else round(live_usd, 2)),
               "live_week_turnover_unbounded_usd": (None if live_unbounded is None
                                                    else round(live_unbounded, 2)),
               "refused": {}}

        for gate, ok in state.items():
            if gate == "has_legs" or gate not in per_gate or ok:
                continue
            per_gate[gate]["refused_days"] += 1
            prov = GATE_PROVENANCE.get(gate)
            if prov in (OWN, IMPORTED):
                cause = CAUSE_OWN if prov == OWN else CAUSE_IMPORTED
            elif live_usd is None:
                cause = ""            # чужое слагаемое не восстановлено
            else:
                cause = _resolve_week_gate(live_usd, move_usd, budget_usd)
            if cause:
                per_gate[gate][cause] += 1
            else:
                per_gate[gate]["unresolved"] += 1
            row["refused"][gate] = cause or "unresolved"

        # Своя цена ошибки у реконструкции: там, где недельный гейт ИЗВЕСТЕН,
        # предсказание по восстановленному обороту сверяется с ним.
        if live_usd is not None and "week_turnover_ok" in state:
            recon_checked += 1
            predicted_ok = (live_usd + move_usd) <= budget_usd + 1e-6
            if predicted_ok == bool(state["week_turnover_ok"]):
                recon_agreed += 1
        days.append(row)

    doc["lookahead_control"] = {
        "days_attribution_would_flip": len(lookahead_flips),
        "dates": lookahead_flips,
        "note": ("окно недельного оборота у писателя ограничено только снизу; "
                 "ретроспективный прогон через него заглядывает вперёд. Здесь "
                 "верхняя граница поставлена на входе, а это число говорит, на "
                 "скольких днях без неё атрибуция была бы другой — то есть "
                 "поправка не косметическая, и её величина ИЗМЕРЕНА"),
    }
    doc["unmeasured_days"] = unmeasured_days
    doc["gate_attribution"] = [
        {"gate": g, "provenance": GATE_PROVENANCE.get(g, "?"), **counts}
        for g, counts in sorted(per_gate.items(),
                                key=lambda kv: -kv[1]["refused_days"])
    ]
    agreement = (recon_agreed / recon_checked) if recon_checked else None
    doc["reconstruction_agreement"] = {
        "days_with_known_gate": recon_checked,
        "agreed": recon_agreed,
        "rate": None if agreement is None else round(agreement, 4),
        "min_required": MIN_RECONSTRUCTION_AGREEMENT,
        "note": ("недельный оборот в строке истории НЕ записан — он восстановлен "
                 "из trades.json тем же _history_from_trades, которым его считал "
                 "писатель; согласие ниже порога ⇒ UNMEASURED, а не доверие"),
    }

    per_move_cap = float(params.max_turnover_per_move)
    per_week_cap = float(params.max_turnover_per_week)
    doc["target_instability"] = {
        "day_over_day_churn_frac": {
            "median": round(statistics.median(churn), 6) if churn else None,
            "max": round(max(churn), 6) if churn else None,
            "n": len(churn),
        },
        "proposed_move_frac": {
            "median": round(statistics.median(move_fracs), 6) if move_fracs else None,
            "max": round(max(move_fracs), 6) if move_fracs else None,
            "n": len(move_fracs),
        },
        "days_move_over_per_move_cap": sum(1 for m in move_fracs if m > per_move_cap),
        "days_move_over_week_budget": sum(1 for m in move_fracs if m > per_week_cap),
        "per_move_cap": per_move_cap,
        "per_week_cap": per_week_cap,
    }
    doc["days"] = days

    # ── головной вердикт ───────────────────────────────────────────────────
    if trades is None:
        doc["status"] = STATUS_UNMEASURED
        doc["unmeasured_reason"] = (
            f"чужое слагаемое недельного гейта не восстановить: {trades_why}")
        return doc
    if not doc["material_days"]:
        doc["status"] = STATUS_UNMEASURED
        doc["unmeasured_reason"] = "существенных дней нет — блокады не было"
        return doc
    if agreement is not None and agreement < MIN_RECONSTRUCTION_AGREEMENT:
        doc["status"] = STATUS_UNMEASURED
        doc["unmeasured_reason"] = (
            f"реконструкция недельного оборота согласуется с известным состоянием "
            f"лишь на {recon_agreed} из {recon_checked} дн. "
            f"({agreement:.0%} < {MIN_RECONSTRUCTION_AGREEMENT:.0%}) — "
            f"атрибуции по ней верить нельзя")
        return doc

    causes: List[str] = []
    for gate in named:
        counts = per_gate.get(gate)
        if counts is None:
            continue
        resolved = counts[CAUSE_OWN] + counts[CAUSE_IMPORTED] + counts[CAUSE_JOINT]
        if counts["unresolved"] > resolved:
            doc["status"] = STATUS_UNMEASURED
            doc["unmeasured_reason"] = (
                f"у названного блокера `{gate}` провенанс не разрешён на "
                f"{counts['unresolved']} дн. против {resolved} разрешённых")
            return doc
        cause = max((CAUSE_OWN, CAUSE_IMPORTED, CAUSE_JOINT), key=lambda c: counts[c])
        causes.append(cause)
        if cause == CAUSE_OWN:
            doc["findings"].append(
                f"[CRITICAL] блокада называет `{gate}` и адресует владельцу дырку "
                f"(недельный бюджет {per_week_cap:.0%} капитала), но связывает его "
                f"СОБСТВЕННЫЙ ход тени на {counts[CAUSE_OWN]} из "
                f"{counts['refused_days']} дн.: один ход сам по себе больше ВСЕГО "
                f"недельного бюджета. История живой книги связывает лишь на "
                f"{counts[CAUSE_IMPORTED]} дн. Поднять бюджет до снятия блокады "
                f"значит разрешить перекладывать медиану "
                f"{_median_move_pct(doc)} "
                f"книги ЕЖЕДНЕВНО — отменить анти-чёрн, а не настроить его")

    doc["binding_cause"] = (
        CAUSE_UNMEASURED if not causes
        else (causes[0] if len(set(causes)) == 1 else CAUSE_JOINT))

    med_churn = doc["target_instability"]["day_over_day_churn_frac"]["median"]
    if med_churn is not None and med_churn > per_move_cap:
        doc["findings"].append(
            f"[CRITICAL] причина выше по течению: сама ЦЕЛЬ переставляется на "
            f"медиану {med_churn:.0%} капитала в день (максимум "
            f"{doc['target_instability']['day_over_day_churn_frac']['max']:.0%}) "
            f"при потолке на один ход {per_move_cap:.0%}. Анти-чёрн не пропустит "
            f"такую цель ни при каком бюджете — блокада снимается починкой цели, "
            f"а не дыркой")

    doc["status"] = STATUS_CRITICAL if doc["findings"] else STATUS_OK
    return doc


def format_report(doc: dict) -> List[str]:
    """Строки для шага 0-офис. Молчать о UNMEASURED запрещено."""
    out: List[str] = []
    status = doc.get("status")
    ti = doc.get("target_instability") or {}
    churn = (ti.get("day_over_day_churn_frac") or {}).get("median")
    move = (ti.get("proposed_move_frac") or {}).get("median")
    head = (f"атрибуция блокады взвода (G5): {status} · существенных дней "
            f"{doc.get('material_days')} · названо блокером "
            f"{', '.join(doc.get('named_blockers') or []) or '—'}")
    out.append(head)
    if status == STATUS_UNMEASURED:
        out.append(f"   [НЕ ИЗМЕРЕНО] {doc.get('unmeasured_reason', 'причина не названа')}")
        return out
    if doc.get("binding_cause"):
        out.append(f"   связывает: {doc['binding_cause']}")
    if churn is not None and move is not None:
        out.append(f"   цель переставляется медиана {churn:.0%}/день · "
                   f"предложенный ход медиана {move:.0%} капитала "
                   f"(потолок на ход {ti.get('per_move_cap', 0):.0%}, "
                   f"недельный {ti.get('per_week_cap', 0):.0%})")
    for f in doc.get("findings") or []:
        out.append(f"   {f}")
    if doc.get("unmeasured_days"):
        out.append(f"   [НЕ ИЗМЕРЕНО] дней без состояния гейтов: "
                   f"{len(doc['unmeasured_days'])}")
    out.append("   ADVISORY: пороги TriggerParams и ready_to_arm НЕ трогаются — "
               "подъём бюджета и починка цели решаются владельцем")
    return out


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True) -> dict:
    """Форма, которую ждёт ступень переписей `findings_bridge` и шаг 0-офис.

    ``overall`` / ``counts`` / ``findings`` — тот же словарь, что у соседей по
    ступени, чтобы читатель не заводил под этот артефакт особую ветку.
    ``now`` инъектируется: иных обращений к часам здесь нет.
    """
    from spa_core.utils.atomic import atomic_save

    root = root or str(Path(__file__).resolve().parents[2])
    data_dir = Path(root) / "data"
    doc = attribute(data_dir, now=now)

    findings = list(doc.get("findings") or [])
    doc["overall"] = doc["status"]
    doc["counts"] = {
        "critical": sum(1 for f in findings if f.startswith("[CRITICAL]")),
        "warn": 0,
        "info": 0,
        # «не измерено» считается ОТДЕЛЬНО и не растворяется в нулях: иначе
        # молчание прибора стало бы неотличимо от чистого прогона.
        "unchecked": (1 if doc["status"] == STATUS_UNMEASURED else 0)
                     + len(observed(doc, "unmeasured_days", kind=list) or []),
    }
    if write:
        atomic_save(doc, str(data_dir / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    from spa_core.utils.atomic import atomic_save

    ap = argparse.ArgumentParser(description="атрибуция блокады взвода SHADOW (ADR-060 G5)")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else (
        Path(__file__).resolve().parents[2] / "data")
    doc = attribute(data_dir)
    for line in format_report(doc):
        print(line)
    if not args.no_write:
        atomic_save(doc, str(Path(data_dir) / OUTPUT_FILENAME))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
