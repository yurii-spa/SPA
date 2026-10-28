"""Разовое разрешение CIO на пробный ход сверх ограничителей частоты (ADR-336).

Решение владельца 11.09 14:31Z (Telegram, `owner_choice: 1`, ADR-334): «советник
получает право ровно на ОДИН ход, чтобы появилось что оценивать; бюджеты не меняются».

Зачем. Взвод CIO (ADR-324/328) стоит на трёх условиях; третье — «окупается ли он»
(`net_bps_if_followed`) — не измеримо, пока нет ни одного вердикта ACT. За 37 дней их не
было: `week_turnover_ok` отказал на 24 из 24 существенных дней, но ни разу не был
ЕДИНСТВЕННЫМ блокиратором — рядом отказывали и другие ограничители. Поэтому разрешение
целится в ХОД, а не в один гейт.

Что снимает и что НЕТ
---------------------
Снимаются ТОЛЬКО ограничители частоты — колонка ADR-060 §3, защита от метания:
кулдаун, минимальный срок удержания, бюджет оборота хода и недели, надбавка за разворот.

Экономика хода обязана пройти сама — иначе «пробный ход» экономически плохого хода
только исказил бы замер «окупается ли CIO», ради которого разрешение и дано:
  * выигрыш ≥ БАЗОВОГО порога ``min_gain_pp`` (без надбавки за разворот — надбавка сама
    антиметание);
  * окупаемость в горизонте (``payback_within_horizon``);
  * цель целиком наблюдена (``target_fully_evidenced``).
RiskPolicy v1.0 не участвует и не ослабляется — цель уже прошла его гейт выше по циклу.
Пороги ``TriggerParams`` не меняются.

Расходуемость — без отдельного флага
------------------------------------
Признак расхода — САМА СДЕЛКА в журнале сделок с меткой ``cio_trial_grant``. Один
источник правды: разрешение не может «сброситься», а ход, прошедший по нему, отличим от
обычного и в оценке ``net_bps_if_followed``, и глазами в журнале решений.
Журнал не прочитан ⇒ расход НЕ измерен ⇒ разрешение не используется (fail-CLOSED):
иначе потерянный файл сделок выдал бы второе разрешение.

Разрешение живёт в КОДЕ, а не в ``data/``: синхронизация прода ``data/`` не возит
(`.claude/rules/deployment.md`, п. 4) — флаг оттуда до цикла не дошёл бы.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

#: Единственное разрешение. Снять — удалить. Второй ход — только новым решением владельца.
TRIAL_GRANT = {
    "adr": "ADR-334",
    "granted_at": "2026-09-11T14:31:50Z",
    "book": "conservative",
    "moves": 1,
    "source": "Telegram owner_choice: 1, карточка owner-decision-cio-ne-vzvoditsya-nikogda-byudzhet-oborota",
}

MARK = "cio_trial_grant"

#: Ограничители частоты — только их снимает разрешение.
FREQUENCY_GATES = frozenset({"cooldown_ok", "min_hold_ok", "move_turnover_ok",
                             "week_turnover_ok", "day_turnover_ok"})
# `day_turnover_ok` (ADR-357) внесён СОЗНАТЕЛЬНО и по роду, а не для зелени:
# дневной бюджет оборота — тот же ограничитель ЧАСТОТЫ, что недельный, который
# разрешение снимает с самого начала. Не внести его значило бы молча СУЗИТЬ
# разрешение владельца и вернуть ровно ту беду, ради которой оно выдано
# (ADR-228: `week_turnover_ok` отказывал 17 из 17 дней, и ACT не наступал никогда).
#
# А вот `max_trade_usd` → `move_amount_ok` сюда НЕ входит и не войдёт: это потолок
# РАЗМЕРА, а не частоты. Владелец добавил его 12.09 именно затем, чтобы сумма
# одного хода была ограничена всегда; снимать его разрешением значило бы отменить
# ответ владельца следующим же ходом. Незнакомый разрешению гейт ⇒ держать —
# правило ниже оставляет его в силе по построению.
#: Экономика и данные — обязаны пройти сами.
ECONOMIC_GATES = frozenset({"payback_within_horizon", "target_fully_evidenced"})

#: Что разрешение СНИМАЕТ: ограничители частоты + надбавка за разворот.
#: Полоса `gain_above_band` снимается не целиком — базовый порог ниже проверяется
#: отдельно: снимается ровно НАДБАВКА, и это разные утверждения.
WAIVED_GATES = frozenset(FREQUENCY_GATES | {"gain_above_band"})

#: Классы препятствий разрешению. Имена — часть контракта двери: по ним считает
#: перепись достижимости, и переименование = смена вопроса.
BLOCK_ECONOMIC = "economics_failed"      # экономика хода не прошла сама
BLOCK_BASE_GAIN = "below_base_gain"      # выигрыш ниже БАЗОВОГО порога
BLOCK_UNKNOWN = "unknown_gate"           # гейт, разрешению не названный ⇒ держать


def grant_blockers(failing, *, gain_pp, min_gain_pp):
    """Что мешает разрешению превратить ЭТОТ HOLD в пробный ход — ОДНА дверь правила.

    ``failing`` — имена отказавших гейтов (без ``has_legs``: «двигать нечего» это
    не препятствие разрешению, а отсутствие предмета).

    Возврат ``(blockers, unmeasured)`` — три исхода, различимые (инв. #17):

    * ``([], None)`` — по гейтам и выигрышу ничто не мешает;
    * ``([(класс, [гейты…]), …], None)`` — препятствия НАЗВАНЫ, в том же порядке,
      в котором их называет :func:`apply_trial_grant`;
    * ``(None, причина)`` — НЕ ИЗМЕРЕНО: входа нет, и «сработало бы» по нему не
      утверждается ни в одну сторону.

    Правило живёт здесь, а не двумя копиями: :func:`apply_trial_grant` решает им
    живой ход, перепись достижимости (``shadow_trigger_eval.trial_grant_reach``)
    им же судит историю. Две копии спорили бы о том же дне молча — обе печатают
    ответ, ни одна не печатает правило.
    """
    if gain_pp is None:
        return None, "выигрыш хода не измерен"
    if min_gain_pp is None:
        return None, "базовый порог выигрыша не измерен"
    names = sorted(str(g) for g in failing if str(g) != "has_legs")
    blockers = []
    econ = [g for g in names if g in ECONOMIC_GATES]
    if econ:
        blockers.append((BLOCK_ECONOMIC, econ))
    if float(gain_pp) < float(min_gain_pp) - 1e-9:
        blockers.append((BLOCK_BASE_GAIN, []))
    unknown = [g for g in names if g not in WAIVED_GATES and g not in ECONOMIC_GATES]
    if unknown:
        blockers.append((BLOCK_UNKNOWN, unknown))
    return blockers, None


def trial_moves_spent(data_dir, trades_filename: str = "trades.json") -> Tuple[Optional[int], str]:
    """Сколько ходов уже сделано по разрешению. ``(None, причина)`` — не измерено."""
    p = Path(data_dir) / trades_filename
    if not p.exists():
        return 0, "журнала сделок нет — книга без сделок, разрешение не расходовалось"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"журнал сделок не прочитан: {type(exc).__name__}"
    trades = doc if isinstance(doc, list) else (doc or {}).get("trades")
    if not isinstance(trades, list):
        return None, "журнал сделок не список — расход не измерен"
    n = sum(1 for t in trades if isinstance(t, dict) and t.get(MARK) == TRIAL_GRANT["adr"])
    return n, ""


def apply_trial_grant(decision, params, *, book_id: str, data_dir,
                      damper_reason: Optional[str] = None) -> Tuple[object, str]:
    """HOLD, упёршийся ТОЛЬКО в ограничители частоты при прошедшей экономике, → ACT (пробный).

    Возврат ``(решение, пояснение)``. Решение меняется НА МЕСТЕ только в этом случае;
    во всех остальных возвращается как было, с названной причиной.

    ``damper_reason`` — классификация хода демпфером ADR-168. Ход, который НЕ перетасовка
    (де-риск, первичное размещение, вложение кэша), проходит и без разрешения — расходовать
    на него единственный пробный ход значило бы сжечь его впустую. Замер 11.09: первая
    редакция сжигала разрешение на первичном размещении, и сквозной тест это поймал.
    """
    if str(book_id or "").lower() != TRIAL_GRANT["book"]:
        return decision, "разрешение выдано другой книге"
    from spa_core.paper_trading.cio_arming import NOT_A_RESHUFFLE
    if damper_reason in NOT_A_RESHUFFLE:
        return decision, f"ход не перетасовка ({damper_reason}) — разрешение не нужно и не расходуется"
    if getattr(decision, "decision", None) != "HOLD":
        return decision, "вердикт не HOLD — разрешение не нужно"
    gates = dict(getattr(decision, "gates", {}) or {})
    if not gates.get("has_legs"):
        return decision, "двигать нечего"

    spent, why = trial_moves_spent(data_dir)
    if spent is None:
        return decision, f"расход разрешения не измерен ⇒ не используется (fail-CLOSED): {why}"
    if spent >= int(TRIAL_GRANT["moves"]):
        return decision, "разрешение израсходовано"

    failing = sorted(k for k, v in gates.items() if not v)
    blockers, unmeasured = grant_blockers(
        failing,
        gain_pp=float(getattr(decision, "gain_pp", 0.0)),
        min_gain_pp=float(params.min_gain_pp),
    )
    if blockers is None:
        return decision, f"препятствия разрешению не измерены ⇒ держать: {unmeasured}"
    for kind, gate_names in blockers:
        if kind == BLOCK_ECONOMIC:
            return decision, f"экономика хода не прошла сама: {gate_names}"
        if kind == BLOCK_BASE_GAIN:
            return decision, (f"выигрыш {decision.gain_pp:.3f} пп ниже базового порога "
                              f"{params.min_gain_pp:.3f} пп — пробовать нечего")
        if kind == BLOCK_UNKNOWN:
            return decision, f"отказал неизвестный разрешению гейт: {gate_names} ⇒ держать"

    waived = [g for g in failing if g in WAIVED_GATES]
    decision.decision = "ACT"
    decision.gates[MARK] = True
    decision.reasons.append(
        f"{MARK}:{TRIAL_GRANT['adr']} — разовое разрешение владельца; сняты ограничители "
        f"частоты {waived} (включая надбавку за разворот), экономика прошла сама: выигрыш "
        f"{decision.gain_pp:.3f} пп ≥ {params.min_gain_pp:.3f} пп, окупаемость "
        f"{decision.payback_days} дн")
    return decision, f"ПРОБНЫЙ ХОД по {TRIAL_GRANT['adr']}: сняты {waived}"


def is_trial(cio_doc) -> bool:
    """Вердикт CIO этого цикла — пробный ход по разрешению?"""
    try:
        return bool(((cio_doc or {}).get("decision_shadow") or {}).get("gates", {}).get(MARK))
    except AttributeError:
        return False
