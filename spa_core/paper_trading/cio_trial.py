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
                             "week_turnover_ok"})
#: Экономика и данные — обязаны пройти сами.
ECONOMIC_GATES = frozenset({"payback_within_horizon", "target_fully_evidenced"})


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
    failing_econ = [g for g in failing if g in ECONOMIC_GATES]
    if failing_econ:
        return decision, f"экономика хода не прошла сама: {failing_econ}"
    base_gain_ok = float(getattr(decision, "gain_pp", 0.0)) >= float(params.min_gain_pp) - 1e-9
    if not base_gain_ok:
        return decision, (f"выигрыш {decision.gain_pp:.3f} пп ниже базового порога "
                          f"{params.min_gain_pp:.3f} пп — пробовать нечего")
    unknown = [g for g in failing if g not in FREQUENCY_GATES | {"gain_above_band"}]
    if unknown:
        return decision, f"отказал неизвестный разрешению гейт: {unknown} ⇒ держать"

    waived = [g for g in failing if g in FREQUENCY_GATES or g == "gain_above_band"]
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
