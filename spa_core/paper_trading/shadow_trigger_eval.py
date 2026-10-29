"""Y3 (ADR-055/ADR-060 tooling): shadow-verdict vs fact reconciliation.

The yield-trigger SHADOW (``allocation_rationale.py``) says HOLD/ACT every cycle
without moving capital. Before the owner arms it, we need the honest question
answered: **had the verdicts been followed, would the book have earned more,
net of switching cost?** This module reads the append-only verdict history
(``data/allocation_rationale_history.jsonl``), replays every verdict against the
LIVE evidenced APYs of the FOLLOWING days, and writes
``data/shadow_trigger_evaluation.json``.

Method, in one paragraph. For each verdict on day *d* with a material proposed
move (current → target), the counterfactual benefit over the horizon is
``Σ_{f in next H observed days} Σ_p (target_p − current_p) · apy_p(f) / 100 / 365``
where ``apy_p(f)`` comes from the history line of day *f* — evidenced (live)
APYs only, never literals. Cost is the verdict's own recorded ``cost_usd``
(gas + slippage model from ``rebalance_economics``); when a material move has no
recorded cost, a CONSERVATIVE assumption of ``ASSUMED_COST_BPS_OF_TURNOVER`` bps
of turnover is charged and labelled as an assumption. An ACT is a **hit** if
net > 0; a material HOLD is a **hit** if net ≤ 0 (holding was right) and a
**miss** if the gated move would have paid. Trivial HOLDs (no material legs —
nothing to decide) are counted but excluded from the hit-rate denominator, so a
quiet market cannot inflate the score. Any day the counterfactual cannot be
priced (missing forward data, missing evidenced APY for a moved leg) is
UNCHECKED — reported, never guessed (invariant 2).

Deterministic, stdlib-only, read-only over everything except its own output.
Fail-open at the cycle boundary: the cycle hook wraps this in try/except.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import itertools
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.utils.observation import observed

from spa_core.paper_trading.allocation_rationale import (
    history_filename as _history_filename,
    run_identity as _run_identity,
)
from spa_core.paper_trading import cio_trial
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.shadow_trigger_eval")

HISTORY_FILENAME = "allocation_rationale_history.jsonl"
EVAL_FILENAME = "shadow_trigger_evaluation.json"
EVAL_VERSION = "shadow-eval-v1"

# ── Evaluation parameters (documented in the output; changing them is visible) ──
DEFAULT_HORIZON_DAYS = 7          # forward window a verdict is judged over
# Arming criteria set BY THE OWNER (ADR-067, 2026-08-06): ≥30 observed days,
# hit-rate ≥60%, net benefit > 0. The previous 7d/70% were the tool author's
# placeholder; the owner's bar is the binding one. The agent brings the table,
# arming stays an owner-gated step regardless of PASS.
MIN_OBSERVATION_DAYS = 30         # arming criterion (ADR-067)
MIN_EVALUATED_FOR_HIT_RATE = 5    # hit-rate is UNCHECKED below this sample size
MIN_HIT_RATE = 0.60               # arming criterion (ADR-067)
ASSUMED_COST_BPS_OF_TURNOVER = 15.0  # conservative gas+slippage assumption (vs ~8bps
#                                      slippage + gas in rebalance_economics) used ONLY
#                                      when a material move carries no recorded cost
MATERIAL_TURNOVER_USD = 100.0     # below this a "move" is noise, the HOLD is trivial


def load_history(data_dir: Path, book_id: Optional[str] = None) -> Tuple[List[dict], int]:
    """КАЖДЫЙ прогон журнала, упорядоченный по ``(cycle_date, generated_at)``.

    До [ADR-395] здесь жила ВТОРАЯ КОПИЯ правила замены строки писателя
    (``by_date[str(obj["cycle_date"])] = obj  # later line wins``), и это было
    хуже, чем дубль кода. Замер ``run_identity_key_price`` (заказ #602/G16)
    вынес вердикт читателям ИСХОДОМ, на стенде из настоящих строк: не менее
    **25 читателей из 108** схлопывали день САМИ, и среди них сам критерий
    взвода (``scripts.evaluate_shadow_trigger`` → ``collapses_to_last``).
    Починка одного писателя вернула бы прогон в ФАЙЛ и не вернула бы его
    КРИТЕРИЮ — а выглядела бы доставленной. Обоснование владельца, принятое
    как правило ([ADR-392] решение 3, вариант A): *«починка одного писателя —
    это работа, которая выглядит законченной и ничего не меняет, а такие
    починки опаснее, чем отсутствие починки»*.

    Идемпотентность файла СОХРАНЕНА и лишь сужена до своего предмета: при
    равной идентичности прогона (:func:`allocation_rationale.run_identity`)
    побеждает последняя строка — как и раньше. Прогон БЕЗ опознания получает
    идентичность своего НОМЕРА СТРОКИ: две неопознанные строки одного дня суть
    два прогона, потому что доказательства обратного нет (инв. #17).

    Порядок — ключом: ``generated_at`` есть ISO-8601, и лексикографический
    порядок на нём совпадает с хронологическим. Ключа нет ⇒ строка идёт перед
    опознанными строками своего дня в порядке файла; порядок ПОЛНЫЙ и не
    зависит от порядка обхода множеств (``PYTHONHASHSEED``).

    ``book_id`` reads that book's own ledger (:func:`allocation_rationale.
    history_filename` — the SAME routing the writer uses, so reader and writer
    can never drift apart on the filename rule). Unset / ``None`` /
    ``"conservative"`` keeps reading the original ``HISTORY_FILENAME``.

    Returns ``(records, unparseable_count)``. Never raises: a missing file is an
    empty history, a corrupt line is counted, not fatal.
    """
    path = Path(data_dir) / _history_filename(book_id)
    bad = 0
    if not path.exists():
        return [], 0
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log.warning("shadow history unreadable (%s)", exc)
        return [], 0
    # Ключ прогона → (порядок, запись). Побеждает последняя строка ТОГО ЖЕ
    # прогона; позиция при этом остаётся за первой его строкой, иначе повторная
    # запись прогона молча переставляла бы его в хвост дня.
    by_run: Dict[Tuple[str, str, int], dict] = {}
    first_slot: Dict[Tuple[str, str], Tuple[str, str, int]] = {}
    for idx, raw in enumerate(raw_lines):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            bad += 1
            continue
        if not isinstance(obj, dict) or not obj.get("cycle_date"):
            bad += 1
            continue
        date = str(obj["cycle_date"])
        key = _run_identity(obj)
        if key is None:
            by_run[(date, "", idx)] = obj      # неопознан ⇒ свой прогон
        else:
            slot = first_slot.get((date, key))
            if slot is None:
                slot = (date, key, idx)
                first_slot[(date, key)] = slot
            by_run[slot] = obj                 # тот же прогон — последняя строка
    return [by_run[k] for k in sorted(by_run)], bad


def _forward_days(history: List[dict], index: int) -> List[dict]:
    """Форвардные ДНИ для записи ``history[index]`` — по одной записи на ДАТУ.

    Горизонт судьи объявлен в ДНЯХ (``DEFAULT_HORIZON_DAYS`` = 7), и до
    [ADR-395] это держалось на том, что в журнале была ровно одна строка на
    день: ``forward[:horizon_days]`` брал 7 записей и они же были 7 датами.
    Как только день несёт несколько прогонов, та же строка означала бы
    «7 прогонов», то есть на дне из 36 прогонов горизонт схлопнулся бы в ОДИН
    день — молча, с понижением ``counterfactual`` до ``PARTIAL``. Это ровно тот
    класс, что [[hysteresis-may-count-runs-not-measurements]]: счёт по прогонам
    вместо счёта по измерениям.

    Представитель даты — ПОСЛЕДНИЙ её прогон, и выбор объявлен, а не случаен:
    от форвардного дня судья берёт ``apy_evidenced_pct``, то есть наблюдение
    дня, а самое позднее наблюдение дня — самое полное. ``history``
    отсортирована, поэтому «последний» здесь есть последний по ключу прогона.

    Свои же более поздние прогоны того же дня форвардным днём НЕ являются
    (``d > d0`` строго): иначе запись судилась бы ставкой, наблюдённой в её же
    сутки, и горизонт «7 дней вперёд» включал бы сегодня.
    """
    d0 = str(history[index].get("cycle_date"))
    last_of_date: Dict[str, dict] = {}
    for rec in history[index + 1:]:
        d = str(rec.get("cycle_date"))
        if d <= d0:
            continue
        last_of_date[d] = rec
    return [last_of_date[d] for d in sorted(last_of_date)]


def _load_equity_daily(data_dir: Path) -> Dict[str, dict]:
    """date → daily row from equity_curve_daily.json (book-APY cross-check)."""
    try:
        doc = json.loads((Path(data_dir) / "equity_curve_daily.json")
                         .read_text(encoding="utf-8"))
        return {str(r.get("date")): r for r in doc.get("daily", [])
                if isinstance(r, dict) and r.get("date")}
    except Exception as exc:  # noqa: BLE001 — cross-check only, never fatal
        log.warning("equity_curve_daily unavailable (%s) — cross-check UNCHECKED", exc)
        return {}


def _deltas(rec: dict) -> Dict[str, float]:
    cur = rec.get("current_positions") or {}
    tgt = rec.get("target_positions") or {}
    out: Dict[str, float] = {}
    for p in set(cur) | set(tgt):
        d = float(tgt.get(p, 0.0) or 0.0) - float(cur.get(p, 0.0) or 0.0)
        if abs(d) > 0.005:
            out[p] = d
    return out


def _turnover_usd(rec: dict, deltas: Dict[str, float]) -> float:
    t = rec.get("turnover_usd")
    if t is not None:
        try:
            return float(t)
        except (TypeError, ValueError):
            pass
    return sum(abs(v) for v in deltas.values()) / 2.0


def _day_gain_usd(deltas: Dict[str, float],
                  apy_map: Dict[str, float]) -> Tuple[Optional[float], List[str]]:
    """One forward day's counterfactual gain; None if any moved leg is unpriced.

    Fail-CLOSED per day: a day where one leg lacks an evidenced APY is UNCHECKED
    for the whole move — partial pricing would silently bias the answer toward
    whichever side happened to have data.
    """
    missing = sorted(p for p in deltas if apy_map.get(p) is None)
    if missing:
        return None, missing
    gain = 0.0
    for p, dv in deltas.items():
        gain += dv * float(apy_map[p]) / 100.0 / 365.0
    return gain, []


def _evaluate_verdict(rec: dict, forward: List[dict],
                      horizon_days: int) -> dict:
    """Judge one verdict against the live evidenced APYs of the following days."""
    verdict = str(rec.get("verdict") or "UNKNOWN").upper()
    deltas = _deltas(rec)
    turnover = _turnover_usd(rec, deltas)
    material = bool(deltas) and turnover >= MATERIAL_TURNOVER_USD

    out: dict = {
        "cycle_date": rec.get("cycle_date"),
        "verdict": verdict,
        "reasons": list(rec.get("reasons") or []),
        "material": material,
        "turnover_usd": round(turnover, 2),
        "gain_pp_claimed": rec.get("gain_pp"),
    }

    # A line with a held book but NO recorded target (e.g. reconstructed from a
    # log that never carried the proposed book) must not be read as "liquidate
    # everything" — that is a data hole, not a proposal. UNCHECKED, not a guess.
    if (rec.get("current_positions") or {}) and not (rec.get("target_positions") or {}):
        out.update({
            "outcome": "UNCHECKED",
            "counterfactual": "UNCHECKED",
            "unchecked_reason": "no_target_recorded",
            "trivial": False,
        })
        return out

    if not material:
        # Nothing was proposed — a HOLD here is trivially consistent, an ACT
        # here would be a contradiction worth surfacing.
        out.update({
            "outcome": "hit" if verdict == "HOLD" else "miss",
            "counterfactual": "TRIVIAL",
            "trivial": True,
            "net_usd": 0.0,
        })
        return out
    out["trivial"] = False

    # Cost: recorded by the trigger's own gas+slippage model; if absent on a
    # material move, charge the conservative assumption — never zero.
    #
    # "Цена измерена и равна нулю" и "цену не записали" — РАЗНЫЕ факты, и до
    # 2026-09-15 они шли одной веткой (`cost_rec > 0.0`): записанный ноль уводил
    # день в допущение, и бесплатный ход оценивался ДОРОЖЕ дешёвого. Замер
    # ADR-390 (`swap_existence_price`, находка `zero_price_is_read_as_absent_price`)
    # назвал цену этого слияния исходом: лучший счёт при нулевой цене $-183.66
    # против $80.75 при цене в ОДИН ЦЕНТ. Это инвариант #17 CLAUDE.md —
    # отсутствие наблюдения обязано иметь СВОЁ представление, и здесь оно у него
    # уже есть (`None`), поэтому различать надо по нему, а не по знаку.
    # Money-path, предмет №1 границы ADR-285: правка сделана по ЯВНОМУ ответу
    # владельца 2026-09-15 (ADR-392 решение 1, вариант 1; ADR-393). Разрешение
    # дано на ЭТУ ветку — соседние 19 координат того же класса (замер ADR-391)
    # не трогаются и лежат у владельца отдельной карточкой.
    cost_rec = rec.get("cost_usd")
    try:
        cost_rec = float(cost_rec) if cost_rec is not None else None
    except (TypeError, ValueError):
        cost_rec = None
    if cost_rec is not None:
        cost_used, cost_source = cost_rec, "recorded"
    else:
        cost_used = turnover * ASSUMED_COST_BPS_OF_TURNOVER / 10_000.0
        cost_source = f"assumption:{ASSUMED_COST_BPS_OF_TURNOVER:g}bps_of_turnover"
    out.update({"cost_usd_recorded": cost_rec, "cost_usd_used": round(cost_used, 2),
                "cost_source": cost_source})

    fw = forward[:horizon_days]
    checked = unchecked = 0
    benefit = 0.0
    missing_all: set = set()
    for frec in fw:
        # Поля нет и карта пуста дают ОДИН исход: все ноги неоценены, и день
        # уходит в UNCHECKED — вердикт не выносится ни в ту, ни в другую сторону.
        gain, missing = _day_gain_usd(
            deltas, observed(frec, "apy_evidenced_pct", kind=dict) or {})
        if gain is None:
            unchecked += 1
            missing_all.update(missing)
        else:
            checked += 1
            benefit += gain
    out.update({
        "forward_days_available": len(fw),
        "forward_days_checked": checked,
        "forward_days_unchecked": unchecked,
        "unpriced_protocols": sorted(missing_all),
    })

    if checked == 0:
        out.update({
            "counterfactual": "UNCHECKED",
            "unchecked_reason": ("no_forward_data" if not fw
                                 else "no_evidenced_apy_for_moved_legs"),
            "outcome": "UNCHECKED",
        })
        return out

    net = benefit - cost_used
    out.update({
        "counterfactual": "CHECKED" if (unchecked == 0 and len(fw) == horizon_days)
        else "PARTIAL",
        "benefit_usd_over_checked_days": round(benefit, 2),
        "net_usd": round(net, 2),
    })
    if verdict == "ACT":
        out["outcome"] = "hit" if net > 0 else "miss"
    elif verdict == "HOLD":
        # Holding was right unless the gated move would have paid its own cost.
        out["outcome"] = "miss" if net > 0 else "hit"
        out["missed_usd"] = round(net, 2) if net > 0 else 0.0
    else:
        out["outcome"] = "UNCHECKED"
        out["unchecked_reason"] = f"unknown_verdict:{verdict}"
    return out


# ── Which gate refused, and can arming EVER be reached? (ADR-060 §приёмка) ─────
# Каждый ложный гейт `rebalance_economics.explain_move` печатает СВОЮ строку
# причины. Отображение нужно потому, что история двухсхемная: строки
# ``shadow-hist-v1`` несут только ``reasons``, поле ``gates`` появилось лишь в
# ``shadow-hist-v2`` (30.08). Читать ТОЛЬКО ``gates`` значило бы объявить 24 из 30
# наблюдённых дней несуществующими; читать ТОЛЬКО ``reasons`` — понизить
# инструмент там, где есть точный. Поэтому: ``gates`` когда есть, вывод из
# ``reasons`` когда нет, и ИСТОЧНИК каждого дня называется в отчёте.
#
# Храповик на полноту отображения — `test_shadow_arming_blockade.py`: он зовёт
# настоящий `explain_move` и требует, чтобы у КАЖДОГО ключа `gates` был здесь
# префикс. Новый гейт без строки причины иначе молча считался бы пройденным на
# всей истории v1, то есть занижал бы ровно ту величину, ради которой блок написан.
GATE_BY_REASON_PREFIX = {
    "no_material_legs": "has_legs",
    "gain_below_band": "gain_above_band",
    "payback_too_long": "payback_within_horizon",
    "cooldown_active": "cooldown_ok",
    "positions_below_min_hold": "min_hold_ok",
    "move_turnover_over_budget": "move_turnover_ok",
    "move_amount_over_cap": "move_amount_ok",
    "week_turnover_over_budget": "week_turnover_ok",
    "day_turnover_over_budget": "day_turnover_ok",
    # Отдельная причина, а не вариант предыдущей: «дневной бюджет превышен» и
    # «сколько ушло сегодня, НЕ ИЗМЕРЕНО» — разные факты для того, кто читает
    # перепись отказов, и слить их значило бы записать отсутствие наблюдения
    # в отказы по бюджету (инв. #17, ADR-357).
    "day_turnover_unmeasured": "day_turnover_ok",
    "target_contains_unevidenced": "target_fully_evidenced",
}
#: Гейт, который не отказывает, а лишь ПОДНИМАЕТ планку (`required_gain_pp`), —
#: не отказ, и в перепись не идёт: он виден как `gain_below_band` тогда и только
#: тогда, когда действительно отказал.
_NON_GATE_REASON_PREFIXES = ("reversal_of_recent_move",)
_ALL_GATES = frozenset(GATE_BY_REASON_PREFIX.values())

BLOCKADE_UNREACHABLE = "UNREACHABLE_UNTIL_CHANGED"
# СНЯТ С УПОТРЕБЛЕНИЯ (цикл #877). Этот вердикт выдавался, когда ни один гейт
# не держал 100 % дней, и звучал как «ничего конкретного, набор переменный» —
# тогда как измеренная правда не менялась: ACT не был возможен ни на одном дне.
# Имя оставлено следом (на него ссылается ADR-228) и закреплено храповиком
# `test_retired_verdict_is_never_produced`: вернуть его = вернуть тихий ответ
# на громкий вопрос. Полный разбор — ADR настоящего цикла.
BLOCKADE_NO_SINGLE = "NO_SINGLE_BLOCKER"
BLOCKADE_ACCUMULATING = "ACCUMULATING"
BLOCKADE_NOT_BLOCKED = "NOT_BLOCKED"
BLOCKADE_UNMEASURED = "UNMEASURED"

# Достижимость РАЗРЕШЕНИЯ ВЛАДЕЛЬЦА на пробный ход (ADR-334) — вопрос, соседний
# с достижимостью взвода и НЕ тот же самый: взвод держат девять гейтов разом,
# а разрешение по построению снимает пять из них и надбавку за разворот. То, что
# «взвод недостижим», про разрешение не говорит НИЧЕГО, и обратно тоже.
REACH_BLOCKED = "UNREACHABLE_BY_GATES"
REACH_OPEN = "OPEN_BY_GATES"
REACH_MOOT = "NOT_BLOCKED"
REACH_UNMEASURED = "UNMEASURED"

# Глубина точного перебора минимального покрытия. Гейтов девять, поэтому до
# трёх проверяется исчерпывающе (≈130 сочетаний); живой замер 15.10 закрылся
# ДВУМЯ гейтами, то есть запас есть.
_COVER_EXACT_MAX_K = 3


def gate_state(rec: dict) -> Tuple[Optional[Dict[str, bool]], str]:
    """Состояние гейтов одной строки истории + ЧЕМ оно получено.

    Возвращает ``(None, "unmeasured")``, когда строка не несёт ни ``gates``, ни
    ``reasons``: «гейты прошли» из отсутствия записи НЕ выводится (иначе молчание
    строки читалось бы как согласие всех гейтов — ровно та подмена «не измерено»
    на «в порядке», против которой написан весь этот блок).
    """
    gates = rec.get("gates")
    if isinstance(gates, dict) and gates:
        return {str(k): bool(v) for k, v in gates.items()}, "gates"
    reasons = rec.get("reasons")
    if isinstance(reasons, list):
        state: Dict[str, bool] = {g: True for g in _ALL_GATES}
        for raw in reasons:
            text = str(raw)
            if text.startswith(_NON_GATE_REASON_PREFIXES):
                continue
            for prefix, gate in GATE_BY_REASON_PREFIX.items():
                if text.startswith(prefix):
                    state[gate] = False
        return state, "reasons"
    return None, "unmeasured"


def blockade_cover(material: List[dict], census_gates: List[str]) -> Tuple[List[str], bool]:
    """Наименьший НАБОР гейтов, чьи отказы покрывают КАЖДЫЙ существенный день.

    Это и есть мера, которую ADR-228 назвал покрытием. Его код считал другое —
    полосу «отказал на 100 % дней» у ОДНОГО гейта, — и разница между этими двумя
    величинами проявилась ровно тогда, когда доказательств стало больше: на
    замере 2026-09-05 (17 существенных дней) `week_turnover_ok` держал 17/17 и
    был назван; на замере 2026-10-15 (115 дней) лучший гейт стои́т на 93 %, ни
    один не держит 100 %, и прибор не назвал НИ ОДНОГО блокиратора при той же —
    даже более полной — тишине: ACT не случился ни разу из 115.

    Полоса 100 % убывает монотонно: каждый новый день может только разорвать её
    и никогда не создать. То есть мера, написанная ради громкого вердикта,
    глохла по мере накопления того самого доказательства, ради которого копилось
    окно. Покрытие так не ведёт себя: оно о дне, а не о гейте, и его полнота —
    это ровно «ни на одном дне ACT не был возможен».

    Точный минимум ищется перебором до ``_COVER_EXACT_MAX_K`` гейтов (на девяти
    гейтах это дёшево), дальше — жадно, и это объявляется флагом: приблизительное
    покрытие, выданное за минимальное, было бы той же подменой в миниатюре.
    """
    days = [row["state"] for row in material]
    if not days:
        return [], True

    def covers(combo: Tuple[str, ...]) -> bool:
        return all(any(not st.get(g, True) for g in combo) for st in days)

    gates = [g for g in census_gates
             if any(not st.get(g, True) for st in days)]
    for k in range(1, min(_COVER_EXACT_MAX_K, len(gates)) + 1):
        for combo in itertools.combinations(gates, k):
            if covers(combo):
                return sorted(combo), True

    remaining = list(range(len(days)))
    greedy: List[str] = []
    while remaining:
        best, best_hit = None, 0
        for g in gates:
            if g in greedy:
                continue
            hit = sum(1 for i in remaining if not days[i].get(g, True))
            if hit > best_hit:
                best, best_hit = g, hit
        if best is None:
            break                      # остаток дней не покрыт ничем
        greedy.append(best)
        remaining = [i for i in remaining if days[i].get(best, True)]
    return sorted(greedy), False


def trial_grant_reach(records: List[dict], *, grant: Optional[dict] = None,
                      min_gain_pp: Optional[float] = None,
                      acts: int = 0) -> dict:
    """Могло ли РАЗРЕШЕНИЕ ВЛАДЕЛЬЦА на пробный ход сработать хоть раз после выдачи.

    Вопрос, которого не задавал никто. Владелец ответил 11.09 (``ADR-334``,
    ``owner_choice: 1``): «советник получает право ровно на ОДИН ход, чтобы
    появилось что оценивать». Ответ дан затем, чтобы закрыть критерий №3 взвода
    (``net_bps_if_followed``), который без единого ACT не считается. Сорок семь
    дней спустя ACT по-прежнему ноль — и до этой переписи ни один сторож не
    отвечал на вопрос «а разрешение-то могло сработать?». «Ещё не случилось» и
    «не могло случиться ни в один день» читаются одинаково и означают разное:
    второе есть ответ владельцу, а не ожидание.

    Правило разрешения НЕ переписывается здесь: оно живёт одной дверью
    :func:`spa_core.paper_trading.cio_trial.grant_blockers`, которой тот же цикл
    судит живой ход. Вторая копия спорила бы с первой молча.

    **Единица счёта — ЗАПИСЬ вердикта, а не календарный день**, и это названо в
    самом отчёте: цикл в иной день прогоняется до пятнадцати раз, поэтому
    «записей» и «дат» — разные числа, и доля от записей взвешена частотой
    прогона. Обе величины печатаются рядом.

    Три исхода различимы (инв. #17):

    * ``UNREACHABLE_BY_GATES`` — измеренных записей после выдачи есть, и ни на
      одной разрешение сработать не могло; препятствия НАЗВАНЫ переписью;
    * ``OPEN_BY_GATES`` — есть запись, которой гейты и выигрыш не мешали. Это НЕ
      «разрешение сработало»: сработает ли оно, зависит ещё от входов, которых в
      этой истории нет (класс хода у демпфера ADR-168, книга, израсходованность),
      и о них отчёт молчит ВСЛУХ;
    * ``UNMEASURED`` — мерить было нечего либо состояние гейтов выведено из строк
      причин (вывод лосси по построению: строка вроде ``reversal_of_recent_move``
      гейта не называет), а по лосси-источнику «не мешало» не утверждается. В
      обратную сторону лосси-источник годится: НАЗВАННЫЙ отказ — положительное
      свидетельство.

    ADVISORY. Ничего не гейтит, ``ready_to_arm`` не трогает, ни одного порога не
    читает кроме базового ``min_gain_pp`` — и тот аргументом.
    """
    grant = dict(grant or cio_trial.TRIAL_GRANT)
    granted_at = str(grant.get("granted_at") or "")
    grant_date = granted_at[:10]

    buckets = {
        "after_grant": {"records": [], "dates": set(), "open_records": [],
                        "open_dates": set(), "blocked": 0, "unmeasured": 0},
        "before_grant": {"records": [], "dates": set(), "open_records": [],
                         "open_dates": set(), "blocked": 0, "unmeasured": 0},
    }
    blocker_counts: Dict[Tuple[str, str], int] = {}
    unmeasured_rows: List[dict] = []

    for rec in records:
        state, source = gate_state(rec)
        date = str(rec.get("cycle_date") or "")
        if state is None or not state.get("has_legs", True):
            continue          # нечего двигать ⇒ разрешению нечего снимать
        # Граница по ДАТЕ выдачи, и день выдачи отнесён к «до»: разрешение
        # пришло в 14:31Z, а время записи вердикта внутри дня здесь не
        # сохранено — отнести день выдачи к «после» значило бы утверждать
        # порядок, которого замер не видел.
        key = "after_grant" if (grant_date and date > grant_date) else "before_grant"
        b = buckets[key]
        b["records"].append(date)
        b["dates"].add(date)

        failing = [g for g, ok in state.items() if not ok and g != "has_legs"]
        # Выигрыш хода носит ДВА имени у одной величины: `gain_pp` в строке
        # истории и `gain_pp_claimed` в строке отчёта. Перепись годится для
        # обеих форм, и спрашиваются они ПООЧЕРЁДНО, а не подстановкой: имя, по
        # которому значения нет, обязано остаться отсутствием наблюдения.
        gain = observed(rec, "gain_pp", kind=(int, float))
        if gain is None:
            gain = observed(rec, "gain_pp_claimed", kind=(int, float))
        blockers, why = cio_trial.grant_blockers(
            failing, gain_pp=gain, min_gain_pp=min_gain_pp,
        )
        if blockers is None:
            b["unmeasured"] += 1
            unmeasured_rows.append({"date": date, "why": why, "source": source})
            continue
        if not blockers:
            if source != "gates":
                b["unmeasured"] += 1
                unmeasured_rows.append({
                    "date": date, "source": source,
                    "why": ("состояние гейтов выведено из строк причин (лосси) — "
                            "«не мешало» по такому источнику не утверждается")})
                continue
            b["open_records"].append(date)
            b["open_dates"].add(date)
            continue
        b["blocked"] += 1
        for kind, gate_names in blockers:
            for g in (gate_names or [""]):
                if key == "after_grant":
                    blocker_counts[(kind, g)] = blocker_counts.get((kind, g), 0) + 1

    after, before = buckets["after_grant"], buckets["before_grant"]
    n_after = len(after["records"])
    measured_after = n_after - after["unmeasured"]

    census = [
        {"class": kind, "gate": gate or None, "records": cnt,
         "pct_of_after": round(100.0 * cnt / n_after, 1) if n_after else None}
        for (kind, gate), cnt in sorted(blocker_counts.items(),
                                        key=lambda kv: (-kv[1], kv[0]))
    ]

    if acts:
        verdict = REACH_MOOT
        reason = ("оценивать есть что без разрешения: ACT в окне "
                  f"{acts} — вопрос «могло ли сработать разрешение» не стоит")
    elif not n_after:
        verdict = REACH_UNMEASURED
        reason = (f"существенных записей ПОСЛЕ выдачи ({grant_date}) в окне отчёта "
                  "нет ни одной — достижимость не мерена")
    elif not measured_after:
        verdict = REACH_UNMEASURED
        reason = (f"все {n_after} существенных записей после выдачи не измерены "
                  "(нет выигрыша либо лосси-источник состояния гейтов)")
    elif after["open_records"]:
        verdict = REACH_OPEN
        reason = (f"гейты и выигрыш не мешали на {len(after['open_records'])} из "
                  f"{n_after} существенных записей после выдачи "
                  f"({len(after['open_dates'])} дат) — тишина этих записей "
                  "правилом разрешения НЕ объяснена: остальные его входы "
                  "(класс хода у демпфера, книга, расход) эта история не несёт")
    else:
        top = census[0] if census else None
        named = (f"{top['gate'] or top['class']} — {top['records']} зап. "
                 f"({top['pct_of_after']} % записей после выдачи)"
                 if top else "препятствия не названы")
        verdict = REACH_BLOCKED
        reason = (f"разрешение владельца от {grant_date} не могло сработать НИ НА ОДНОЙ "
                  f"из {measured_after} измеренных существенных записей после выдачи "
                  f"({len(after['dates'])} дат); чаще всех стои́т {named}. До выдачи "
                  f"таких записей было {len(before['open_records'])} из "
                  f"{len(before['records'])} — предпосылка ответа владельца была верна "
                  "в день ответа и перестала быть верной после него")

    return {
        "verdict": verdict,
        "reason": reason,
        "grant": {k: grant.get(k) for k in ("adr", "granted_at", "book", "moves")},
        "unit": ("запись вердикта (цикл), а не календарный день — цикл в иной день "
                 "прогоняется многократно, и доля от записей взвешена частотой прогона"),
        "min_gain_pp": min_gain_pp,
        "after_grant": {
            "records": n_after, "dates": len(after["dates"]),
            "measured_records": measured_after,
            "open_by_gates_records": len(after["open_records"]),
            "open_by_gates_dates": sorted(after["open_dates"]),
            "blocked_records": after["blocked"],
            "unmeasured_records": after["unmeasured"],
        },
        "before_grant": {
            "records": len(before["records"]), "dates": len(before["dates"]),
            "open_by_gates_records": len(before["open_records"]),
            "open_by_gates_dates": sorted(before["open_dates"]),
            "blocked_records": before["blocked"],
            "unmeasured_records": before["unmeasured"],
        },
        "blocker_census": census,
        "unmeasured_sample": unmeasured_rows[:10],
    }


def arming_blockade(records: List[dict], *, observed_days: int, min_days: int,
                    acts_scored: int) -> dict:
    """Почему взвод недостижим — и достижим ли он вообще ожиданием.

    Вопрос, которого не было ни у одного сторожа. Критерий №3 мандата владельца
    (ADR-067, ``net_bps_if_followed > 0``) может быть закрыт ТОЛЬКО оценённым
    вердиктом ACT. Пока ACT нет, критерий стоит ``UNCHECKED`` со словом «yet» —
    и это читается как «ещё не набрали дней». Замер 2026-09-05 (цикл #487):
    окно ПОЛНО (30/30 дней), а ACT не было НИ РАЗУ, потому что гейт
    ``week_turnover_ok`` отказал на 17 из 17 существенных дней. Ожидание тут не
    поможет никогда — и разница между «ещё копим» и «недостижимо без решения»
    это единственное, ради чего блок существует.

    Мера — ПОКРЫТИЕ, а не «единственный виновник». Гейты отказывают пачками
    (на реальных 17 днях ни один не был единственным), поэтому «sole blocker»
    честно даёт нули и один сам по себе ничего не доказывает. Гейт, отказавший
    на 100 % существенных дней, — НЕОБХОДИМОЕ (не достаточное) условие любого
    будущего ACT: не сняв его, ACT получить нельзя, сняв — ещё не факт. Так и
    называется: ``necessary_blockers``.

    Ничего не гейтит, ``ready_to_arm`` не трогает: критерии взвода — мандат
    владельца, а этот блок только НАЗЫВАЕТ, почему они стоят.
    """
    material: List[dict] = []
    unmeasured_days: List[str] = []
    source_counts = {"gates": 0, "reasons": 0, "unmeasured": 0}
    agree_both = 0
    agree_ok = 0

    for rec in records:
        state, source = gate_state(rec)
        source_counts[source] += 1
        date = str(rec.get("cycle_date") or "")
        if state is None:
            unmeasured_days.append(date)
            continue
        # Своя цена ошибки у вывода из `reasons`: там, где есть ОБА источника,
        # они сверяются, и согласие печатается числом. Инструмент, чья точность
        # не измерена, подтверждать другой инструмент не вправе.
        if source == "gates" and isinstance(rec.get("reasons"), list):
            derived, _ = gate_state({"reasons": rec["reasons"]})
            if derived is not None:
                agree_both += 1
                if all(derived.get(k) == v for k, v in state.items()
                       if k in _ALL_GATES):
                    agree_ok += 1
        if not state.get("has_legs", True):
            continue          # тривиальный HOLD: решать было нечего
        material.append({"date": date, "state": state})

    census: Dict[str, Dict[str, int]] = {
        g: {"refused_days": 0, "sole_blocker_days": 0} for g in sorted(_ALL_GATES)
        if g != "has_legs"
    }
    for row in material:
        refused = [g for g, ok in row["state"].items()
                   if g != "has_legs" and not ok and g in census]
        for g in refused:
            census[g]["refused_days"] += 1
        if len(refused) == 1:
            census[refused[0]]["sole_blocker_days"] += 1

    n = len(material)
    necessary = [g for g, c in census.items() if n and c["refused_days"] == n]
    # День БЕЗ ни одного отказа — это день, на котором `evaluate` сказал бы ACT
    # (ACT требует ровно «все гейты true»). Поэтому «покрытие полно» и «ни на
    # одном дне ACT не был возможен» — одна и та же величина, и именно она
    # отвечает на вопрос «изменит ли что-нибудь ожидание».
    act_able = [row["date"] for row in material
                if not any(not ok for g, ok in row["state"].items()
                           if g != "has_legs" and g in census)]
    cover, cover_exact = blockade_cover(material, sorted(census))

    if acts_scored > 0:
        verdict = BLOCKADE_NOT_BLOCKED
        reason = ("оценённый ACT есть — вопрос «достижим ли взвод» не стоит: "
                  "критерий №3 может быть посчитан")
    elif observed_days < min_days:
        verdict = BLOCKADE_ACCUMULATING
        reason = (f"окно наблюдения ещё не полно ({observed_days}/{min_days} дн.) — "
                  "ожидание пока имеет смысл")
    elif unmeasured_days:
        verdict = BLOCKADE_UNMEASURED
        reason = (f"{len(unmeasured_days)} дн. истории не несут ни `gates`, ни "
                  "`reasons` — перепись отказов неполна, и «блокады нет» о них "
                  "не сказано")
    elif n == 0:
        verdict = BLOCKADE_UNMEASURED
        reason = ("окно полно, но существенных предложений в нём НЕ БЫЛО ни одного: "
                  "гейты не отказывали — им нечего было отказывать")
    elif act_able:
        # Третий исход, а не «блокада переменная»: на этих днях перепись отказов
        # НЕ объясняет тишину. Либо ACT был возможен и не оценён, либо состояние
        # гейтов у строки неполно (вывод из причин лосси по построению — строка
        # вроде `reversal_of_recent_move` гейта не называет). Сказать по ним
        # «блокирует переменный набор» значило бы выдать неизмеренное за ответ.
        verdict = BLOCKADE_UNMEASURED
        reason = (f"{len(act_able)} из {n} существенных дн. не несут НИ ОДНОГО "
                  f"отказа гейта (на таком дне ACT был бы возможен), а оценённого "
                  f"ACT нет: тишина этих дней НЕ объяснена переписью — "
                  f"{', '.join(act_able[:5])}")
    else:
        # Покрытие ПОЛНО: каждый существенный день отказан хотя бы одним гейтом,
        # то есть ACT не был возможен ни на одном. Ожидание этого не изменит —
        # и это верно независимо от того, держит ли КАКОЙ-ТО один гейт 100 %.
        verdict = BLOCKADE_UNREACHABLE
        named = (f"гейт(ы) {', '.join(necessary)} отказал(и) на всех {n} днях (100 %)"
                 if necessary else
                 f"ни один гейт не отказал на всех {n} днях, но набор "
                 f"{{{', '.join(cover)}}} покрывает их "
                 f"{'все' if cover_exact else 'все (покрытие жадное, не минимальное)'}")
        reason = (f"окно полно ({observed_days}/{min_days} дн.), ACT не было ни разу, "
                  f"и ни на одном из {n} существенных дней он не был ВОЗМОЖЕН: "
                  f"{named} — ожидание не изменит этого никогда, нужен ответ владельца")

    return {
        "verdict": verdict,
        "reason": reason,
        "material_days": n,
        # Единица счёта у всех `*_days` этого блока — ЗАПИСЬ вердикта, а не
        # календарная дата: цикл в иной день прогоняется до пятнадцати раз
        # (замер 28.10: 148 существенных записей на 69 датах, максимум 15 на
        # дате), поэтому доля «% существенных» взвешена частотой прогона, а не
        # календарём. Имена `*_days` оставлены — на них стоят читатели и
        # храповик, — но число дат печатается РЯДОМ: два разных числа под одним
        # именем были бы ровно той подменой, против которой написан блок.
        "material_dates": len({row["date"] for row in material}),
        "necessary_blockers": necessary,
        "blockade_cover": cover,
        "cover_is_minimal": cover_exact,
        "act_able_days": act_able,
        "gate_census": [
            {"gate": g,
             "refused_days": c["refused_days"],
             "refused_pct": round(100.0 * c["refused_days"] / n, 1) if n else None,
             "sole_blocker_days": c["sole_blocker_days"],
             "necessary_blocker": g in necessary}
            for g, c in sorted(census.items(),
                               key=lambda kv: (-kv[1]["refused_days"], kv[0]))
        ],
        "gate_state_source": source_counts,
        "unmeasured_days": unmeasured_days,
        "reason_deriver_agreement": {
            "days_with_both_sources": agree_both,
            "agreed": agree_ok,
            "note": ("вывод гейтов из строк причин сверен с полем `gates` там, где "
                     "есть оба; согласие ниже 100 % означает, что перепись по "
                     "старым строкам занижена — это НЕ повод ей верить молча"),
        },
    }


def live_trim_census(records: List[dict]) -> dict:
    """Что ЖИВОЙ шаг урезания (ADR-850) сделал на записанных днях.

    Три блока рядом (`arming_blockade`, `trial_grant_reach`,
    `admissible_size_reach`) отвечают на вопрос «что БЫЛО БЫ». Этот — на
    вопрос «что шаг СДЕЛАЛ», и он единственный умеет сказать, что проводка в
    проде молчит.

    Строка БЕЗ поля ``admissible_trim`` считается ОТДЕЛЬНЫМ числом
    (``records_without_field``): все строки, записанные до ADR-850, поля не
    несут, и зачесть их в «не урезано» значило бы выдать отсутствие наблюдения
    за наблюдение нуля (инв. #17). Перепись только ЧИТАЕТ.
    """
    if not isinstance(records, list):
        return {"unmeasured_reason": "история не список — перепись не измерена"}
    counts: Dict[str, int] = {}
    without = 0
    last_applied: Optional[dict] = None
    # Ось ЦЕНЫ трима: сколько стоило ОДНО И ТО ЖЕ предложение до и после
    # урезания. Четыре исхода раздельно, и `applied_without_block` — ровно
    # урок ADR-851: у записи, сделанной ДО появления этой цены, блока нет не
    # потому, что цена равна нулю, а потому что считать её было некому.
    cost_measured = 0
    cost_unmeasured = 0
    cost_applied_without_block = 0
    cost_no_subject = 0
    deltas: List[float] = []
    cost_last: Optional[dict] = None
    for rec in records:
        if not isinstance(rec, dict):
            continue
        trim = rec.get("admissible_trim")
        if not isinstance(trim, dict) or not trim:
            without += 1
            continue
        verdict = str(trim.get("verdict") or "UNMEASURED")
        counts[verdict] = counts.get(verdict, 0) + 1
        cost = trim.get("cost")
        if verdict != "TRIMMED_TO_ADMISSIBLE":
            # Двух книг нет ⇒ предмета нет. Это НЕ «цена равна нулю».
            cost_no_subject += 1
        elif not isinstance(cost, dict) or not cost:
            cost_applied_without_block += 1
        elif str(cost.get("kind")) == "measured":
            cost_measured += 1
            try:
                deltas.append(float(cost["delta_bps"]))
            except (KeyError, TypeError, ValueError):
                # Блок назвал себя измеренным, а числа не несёт — это НЕ ноль.
                cost_measured -= 1
                cost_unmeasured += 1
            else:
                cost_last = {
                    "date": rec.get("cycle_date"),
                    "full_bps": cost.get("full_bps"),
                    "final_bps": cost.get("final_bps"),
                    "delta_bps": cost.get("delta_bps"),
                    "full_usd": cost.get("full_usd"),
                    "final_usd": cost.get("final_usd"),
                    "full_legs": cost.get("full_legs"),
                    "final_legs": cost.get("final_legs"),
                    "chains_measured": cost.get("chains_measured"),
                }
        else:
            cost_unmeasured += 1
        if verdict == "TRIMMED_TO_ADMISSIBLE":
            last_applied = {
                "date": rec.get("cycle_date"),
                "k": trim.get("k"),
                "turnover_full_usd": trim.get("turnover_full_usd"),
                "turnover_final_usd": trim.get("turnover_final_usd",
                                               trim.get("turnover_cut_usd")),
                "admissible_usd": trim.get("admissible_usd"),
                "verdict_of_day": rec.get("verdict"),
            }
    ordered = sorted(deltas)
    median = None
    if ordered:
        mid = len(ordered) // 2
        median = (ordered[mid] if len(ordered) % 2
                  else round((ordered[mid - 1] + ordered[mid]) / 2.0, 4))
    return {
        "records": len([r for r in records if isinstance(r, dict)]),
        "records_without_field": without,
        "counts": counts,
        "last_applied": last_applied,
        "cost": {
            "measured": cost_measured,
            "unmeasured": cost_unmeasured,
            "applied_without_block": cost_applied_without_block,
            "no_subject": cost_no_subject,
            "delta_bps_min": (ordered[0] if ordered else None),
            "delta_bps_max": (ordered[-1] if ordered else None),
            "delta_bps_median": median,
            "last": cost_last,
            "note": ("цена трима мерится на ОДНОМ предложении одной моделью; "
                     "`applied_without_block` — запись старше этой цены, а не "
                     "её ноль (урок ADR-851); `no_subject` — урезания не было, "
                     "двух книг нет"),
        },
        "note": ("перепись ЧИТАЕТ запись живого шага и ничего не решает; строка без "
                 "поля — это «шаг не звали», а не «не урезано»"),
    }


def _criterion(name: str, threshold, actual, status: str, note: str = "") -> dict:
    c = {"criterion": name, "threshold": threshold, "actual": actual, "status": status}
    if note:
        c["note"] = note
    return c


def evaluate_window(
    data_dir: Path,
    *,
    window_days: Optional[int] = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    min_days: int = MIN_OBSERVATION_DAYS,
    min_hit_rate: float = MIN_HIT_RATE,
    write: bool = True,
    now: Optional[datetime] = None,
) -> dict:
    """Reconcile the shadow's verdict history with what live data then showed.

    Deterministic given the files on disk. Data holes surface as UNCHECKED with
    a reason — never as a made-up number. ``write=False`` computes without
    touching disk (beyond reads).

    ``now`` — часы прогона (заказ G33, п. 1). До этой правки единственная
    стенная отметка ``generated_at`` бралась у машины, и параметр закрыть её не
    мог: имя ``datetime`` связано на импорте, поэтому переписи оставалось
    только закреплять КЛАСС извне. ADR-406 насчитал таких дверей три, ADR-408
    измерил цену каждой — у этой она **нулевая** (значения всех прочих
    координат ответа под пином не изменились ни на дайджест), поэтому дверь
    закрывается здесь, у читателя, а не пином в приборе. Умолчание — настоящие
    часы: поведение дневного пути не меняется ни на шаг.

    Та же правка закрывает вторую дешёвую дверь — ``scripts.evaluate_shadow_trigger``:
    перепись приводит его ЧЕРЕЗ ЭТУ ЖЕ функцию (она импортирована в модуль
    обёртки и стои́т в ``_DATA_DIR_ENTRIES``), так что дверь у них общая.

    Третью дверь (``decision_audit_trail``) закрывать ЗАПРЕЩЕНО: там дрожь
    двух зовов и есть измеряемое свойство, и пин её вердикт переворачивает
    (ADR-408).
    """
    data_dir = Path(data_dir)
    history, bad_lines = load_history(data_dir)
    # Окно объявлено в ДНЯХ, а журнал с [ADR-395] несёт по нескольку прогонов на
    # день — резать его по ЗАПИСЯМ значило бы отвечать на другой вопрос («сколько
    # последних решений»), и на дне из 36 прогонов окно в 30 дней схлопнулось бы
    # в один день. Поэтому отбираются ДАТЫ, а потом все прогоны этих дат.
    if window_days is not None and window_days > 0:
        _all_dates = sorted({str(r.get("cycle_date")) for r in history
                             if r.get("cycle_date")})
        _keep_dates = set(_all_dates[-(window_days + horizon_days):])
        history = [r for r in history
                   if str(r.get("cycle_date")) in _keep_dates]
    equity = _load_equity_daily(data_dir)

    per_verdict: List[dict] = []
    for i, rec in enumerate(history):
        # Судится КАЖДЫЙ прогон (стёртый прогон дня возвращается критерию), а
        # форвардный горизонт остаётся в ДНЯХ — см. :func:`_forward_days`.
        row = _evaluate_verdict(rec, _forward_days(history, i), horizon_days)
        # Book-APY cross-check against the equity curve (context, not a gate).
        eq = equity.get(str(rec.get("cycle_date")))
        if eq is not None and eq.get("apy_today") is not None:
            row["book_apy_equity_pct"] = eq.get("apy_today")
        per_verdict.append(row)
    if window_days is not None and window_days > 0:
        _scored_dates = sorted({r.get("cycle_date") for r in per_verdict
                                if r.get("cycle_date")})
        _window_keep = set(_scored_dates[-window_days:])
        per_verdict = [r for r in per_verdict
                       if r.get("cycle_date") in _window_keep]

    observed_days = len({r["cycle_date"] for r in per_verdict if r.get("cycle_date")})
    acts = [r for r in per_verdict if r["verdict"] == "ACT"]
    holds = [r for r in per_verdict if r["verdict"] == "HOLD"]
    trivial = [r for r in per_verdict if r.get("trivial")]
    unchecked = [r for r in per_verdict if r["outcome"] == "UNCHECKED"]
    scored = [r for r in per_verdict
              if not r.get("trivial") and r["outcome"] in ("hit", "miss")]
    hits = [r for r in scored if r["outcome"] == "hit"]
    hit_rate = round(len(hits) / len(scored), 4) if scored else None

    acts_scored = [r for r in acts if r["outcome"] in ("hit", "miss")]
    net_usd_if_followed = round(sum(r.get("net_usd", 0.0) for r in acts_scored), 2)
    capital = None
    for rec in reversed(history):
        if rec.get("capital_usd"):
            capital = float(rec["capital_usd"])
            break
    net_bps_if_followed = (round(10_000.0 * net_usd_if_followed / capital, 2)
                           if capital else None)
    hold_missed_usd = round(sum(r.get("missed_usd", 0.0) for r in holds), 2)

    # ── Arming-readiness criteria (each PASS / FAIL / UNCHECKED; fail-closed:
    #    anything not PASS ⇒ NOT_READY). These are the thresholds the owner card
    #    will cite — change them only with the ADR that arms the trigger. ──
    criteria = [
        _criterion("observation_days", f">={min_days}", observed_days,
                   "PASS" if observed_days >= min_days else "FAIL"),
    ]
    if len(scored) < MIN_EVALUATED_FOR_HIT_RATE:
        criteria.append(_criterion(
            "hit_rate", f">={min_hit_rate}", hit_rate, "UNCHECKED",
            f"only {len(scored)} non-trivial verdict(s) scored — "
            f"need >={MIN_EVALUATED_FOR_HIT_RATE} for the rate to mean anything"))
    else:
        criteria.append(_criterion(
            "hit_rate", f">={min_hit_rate}", hit_rate,
            "PASS" if (hit_rate is not None and hit_rate >= min_hit_rate) else "FAIL"))
    if not acts_scored:
        criteria.append(_criterion(
            "net_bps_if_followed", ">0", net_bps_if_followed, "UNCHECKED",
            "no ACT verdict has been scored yet — nothing proves the trigger PAYS; "
            "an all-HOLD window can satisfy hit-rate while leaving this unknown"))
    else:
        criteria.append(_criterion(
            "net_bps_if_followed", ">0", net_bps_if_followed,
            "PASS" if (net_bps_if_followed is not None
                       and net_bps_if_followed > 0) else "FAIL"))

    ready = all(c["status"] == "PASS" for c in criteria)

    # Перепись отказов считается по ТЕМ ЖЕ дням, что и вердикты: окно уже
    # обрезано выше, и брать для неё всю историю значило бы ответить на другой
    # вопрос («когда-нибудь») вместо заданного («в оценённом окне»).
    _window_dates = {r.get("cycle_date") for r in per_verdict}
    _window_history = [rec for rec in history
                       if rec.get("cycle_date") in _window_dates]
    blockade = arming_blockade(
        _window_history,
        observed_days=observed_days, min_days=min_days,
        acts_scored=len(acts_scored),
    )
    # Базовый порог выигрыша берётся у ЖИВОГО контракта порогов, а не литералом:
    # литерал здесь разошёлся бы с тем, чем разрешение судит живой ход, и
    # разошёлся бы молча. Колонка — та же, в которой работает бумажная книга.
    from spa_core.allocator.rebalance_economics import TriggerParams

    reach = trial_grant_reach(
        _window_history,
        min_gain_pp=float(TriggerParams.for_mode("paper").min_gain_pp),
        acts=len(acts),
    )
    # Третий соседний вопрос, и опять НЕ тот же самый. Два блока выше спрашивают
    # про СНЯТИЕ стен (какой набор гейтов держит день; что освободится, если гейт
    # принудительно пройдёт). Этот — про УРЕЗАНИЕ хода до потолка, который НИКТО
    # не снимает: оценка идёт с другой стороны (нижняя граница вместо потолка),
    # и прохождение здесь есть доказательство достижимости, а не её оценка.
    from spa_core.paper_trading.admissible_size import admissible_size_reach

    admissible = admissible_size_reach(
        _window_history,
        params=TriggerParams.for_mode("paper"),
        acts=len(acts),
    )
    # Четвёртый вопрос, и он про ПРОВОДКУ, а не про достижимость: три блока выше
    # спрашивают, ЧТО БЫЛО БЫ, этот — что живой шаг ADR-850 на записанных днях
    # СДЕЛАЛ. Прибор без читателя сирота (ADR-843), поэтому у живого урезания
    # есть перепись, и её печатают оба читателя артефакта.
    live_trim = live_trim_census(_window_history)
    # Пятый вопрос, и опять НЕ тот же: четыре блока выше спрашивают про РАЗМЕР
    # урезанного хода и про его цену, этот — про его ФОРМУ. ADR-853 вывел из
    # механизма («газ за ногу, а число ног с k не падает»), что урезание с
    # МЕНЬШИМ числом ног дешевле при том же размере, и честно оставил это
    # РАССУЖДЕНИЕМ. Здесь оно становится замером, и население у него другое по
    # построению: урезаемым является любое записанное предложение выше потолка,
    # а не только то, до которого дошла живая проводка (там население — ОДНА
    # запись). ADVISORY: допустимость книги подмножества НЕ утверждается.
    from spa_core.paper_trading.admissible_trim import _chain_map
    from spa_core.paper_trading.trim_shape import trim_shape_census

    _chains_for_shape, _chains_measured = _chain_map(data_dir)
    trim_shape = trim_shape_census(
        _window_history,
        params=TriggerParams.for_mode("paper"),
        chains=_chains_for_shape,
        chains_measured=_chains_measured)
    # Шестой вопрос, и он НЕ тот же: пять блоков выше спрашивают, что было бы и
    # чего бы это стоило, а этот — ПУСТИТ ЛИ полученную книгу риск-политика.
    # ADR-854 измерил размер приза формы «подмножество» и сам назвал, что
    # допустимость её книги не спрашивали; ADR-850 привёл контрпример (потолок
    # на ГРУППУ угол бокса не сохраняет) и честно оставил его рассуждением.
    # Здесь он становится замером. ADVISORY: спрошена дверь КНИГИ
    # (`check_portfolio_health`), живая дверь дня на истории невоспроизводима —
    # снимка адаптеров запись не несёт, и это НАЗВАНО, а не умолчано.
    from spa_core.paper_trading.trim_admissibility import (
        tier_map, trim_admissibility_census)

    _tiers_for_shape, _tiers_measured = tier_map(data_dir)
    trim_admissibility = trim_admissibility_census(
        _window_history,
        params=TriggerParams.for_mode("paper"),
        tiers=_tiers_for_shape,
        tiers_measured=_tiers_measured,
        chains=_chains_for_shape,
        chains_measured=_chains_measured)
    # Седьмой вопрос, и он НЕ тот же: шесть блоков выше спрашивают, что было бы,
    # чего бы это стоило и пустит ли это дверь, а этот — есть ли ДОПУСТИМАЯ
    # книга ЛУЧШЕ той, которую выбрал жадный спред. ADR-855 назвал жадный спред
    # НИЖНЕЙ границей, а не оптимумом, и честно оставил это РАССУЖДЕНИЕМ (жадное
    # правило про потолки не спрашивает вовсе). Здесь оно становится замером.
    # ADVISORY: найденное есть НИЖНЯЯ граница оптимума, а не оптимум, — две
    # причины названы в докстринге прибора и повторены в самой переписи.
    from spa_core.paper_trading.trim_optimum import trim_optimum_census

    trim_optimum = trim_optimum_census(
        _window_history,
        params=TriggerParams.for_mode("paper"),
        tiers=_tiers_for_shape,
        tiers_measured=_tiers_measured,
        chains=_chains_for_shape,
        chains_measured=_chains_measured)

    # Девятый вопрос, и он НЕ тот же: восемь блоков выше спрашивают, что было
    # бы, чего бы это стоило, пустит ли это дверь и есть ли книга ЛУЧШЕ жадной,
    # а этот — ОПТИМАЛЕН ЛИ САМ КРАЙ ОТРЕЗКА размеров. ADR-859 брал наибольший
    # допустимый размер и честно назвал это ПРИЧИНОЙ 2 своей нижней границы
    # («монотонность окупаемости по размеру не доказана»). Здесь она становится
    # замером. ADVISORY: ПРИЧИНА 1 (раскладка фиксирована спредом) остаётся
    # открытой, и это сказано в самой переписи.
    from spa_core.paper_trading.trim_size_edge import trim_size_edge_census

    trim_size_edge = trim_size_edge_census(
        _window_history,
        params=TriggerParams.for_mode("paper"),
        tiers=_tiers_for_shape,
        tiers_measured=_tiers_measured,
        chains=_chains_for_shape,
        chains_measured=_chains_measured)

    doc = {
        "generated_at": None,  # filled below; kept out of the hash-relevant zone
        "version": EVAL_VERSION,
        "mode": "ADVISORY",
        "note": ("Y3 tooling (ADR-055/ADR-060): reconciles shadow verdicts with "
                 "subsequent live data. ADVISORY ONLY — arming the trigger is a "
                 "separate owner-gated step (pre_cutover_gate + ADR)."),
        "status": "READY" if ready else "NOT_READY",
        "ready_to_arm": ready,
        "observation_days": observed_days,
        "counts": {
            "act": len(acts), "hold": len(holds),
            "trivial_hold": len([r for r in trivial if r["verdict"] == "HOLD"]),
            "scored": len(scored), "unchecked": len(unchecked),
            "corrupt_history_lines": bad_lines,
        },
        "hit_rate": hit_rate,
        "net_usd_if_followed": net_usd_if_followed,
        "net_bps_if_followed": net_bps_if_followed,
        "hold_missed_usd_total": hold_missed_usd,
        "criteria": criteria,
        # НЕ критерий и не гейт: `ready_to_arm` выше считается ровно по мандату
        # владельца и этим блоком не меняется. Блок отвечает на соседний вопрос —
        # «достижим ли взвод ожиданием» — который до цикла #487 не задавал никто.
        "arming_blockade": blockade,
        # Соседний вопрос и НЕ тот же самый: разрешение владельца на пробный ход
        # (ADR-334) снимает пять гейтов из девяти, поэтому «взвод недостижим» о
        # нём не говорит ничего. Тоже не критерий и не гейт.
        "trial_grant_reach": reach,
        # Не критерий и не гейт — третий соседний вопрос: прошёл бы ход, УРЕЗАННЫЙ
        # до допустимого размера (ADR-848). Снятие стены даёт потолок, урезание —
        # нижнюю границу; из потолка достижимость не следует, из границы следует.
        "admissible_size_reach": admissible,
        # Проводка живого урезания (ADR-850): что шаг 2e'' сделал на записанных
        # днях. Не критерий и не гейт; отвечает на вопрос, которого у трёх
        # блоков выше нет вовсе — работает ли проводка в проде.
        "live_trim_census": live_trim,
        # Форма урезания (ADR-854). Не критерий и не гейт: `ready_to_arm`
        # считается ровно по мандату владельца и этим блоком не меняется.
        # Отвечает на вопрос, которого у четырёх блоков выше нет вовсе —
        # стоит ли формы урезания РАЗЛИЧАТЬ, и на каком населении это измерено.
        "trim_shape_census": trim_shape,
        "trim_admissibility_census": trim_admissibility,
        # Приз ограниченного поиска (ADR-859). Не критерий и не гейт:
        # `ready_to_arm` считается ровно по мандату владельца и этим блоком не
        # меняется. Отвечает на вопрос, которого у шести блоков выше нет вовсе —
        # НАСКОЛЬКО жадный спред хуже допустимого оптимума.
        "trim_optimum_census": trim_optimum,
        # Цена ПРИЧИНЫ 2 нижней границы (ADR-861). Не критерий и не гейт:
        # `ready_to_arm` считается ровно по мандату владельца и этим блоком не
        # меняется. Отвечает на вопрос, которого у семи блоков выше нет вовсе —
        # ОПТИМАЛЕН ли наибольший допустимый размер хода внутри подмножества.
        "trim_size_edge_census": trim_size_edge,
        "params": {
            "horizon_days": horizon_days,
            "min_observation_days": min_days,
            "min_hit_rate": min_hit_rate,
            "min_scored_for_hit_rate": MIN_EVALUATED_FOR_HIT_RATE,
            "assumed_cost_bps_of_turnover": ASSUMED_COST_BPS_OF_TURNOVER,
            "material_turnover_usd": MATERIAL_TURNOVER_USD,
        },
        "assumptions": [
            "forward APY per protocol comes from the accumulator's own evidenced "
            "(live-sourced) daily maps; a day with an unpriced moved leg is "
            "UNCHECKED, never interpolated",
            "cost = the verdict's recorded gas+slippage estimate; a material move "
            f"without one is charged {ASSUMED_COST_BPS_OF_TURNOVER:g} bps of "
            "turnover (conservative assumption, labelled per verdict)",
            "trivial HOLDs (no material proposal) are excluded from hit-rate so a "
            "quiet market cannot inflate the score",
        ],
        "per_verdict": per_verdict,
    }
    # Полный ISO с временем: date-only метка читалась сторожем B2 как «полночь»
    # и рождала ложный WARN свежести каждую ночь 02:00–06:00 (2026-08-07).
    # `is not None`, а не `or`: подстановка по ложности спутала бы «часы не
    # переданы» с любым falsy-значением и сама была бы членом класса инв. #17.
    doc["generated_at"] = (now if now is not None
                           else datetime.now(timezone.utc)).isoformat()
    if write:
        atomic_save(doc, str(data_dir / EVAL_FILENAME))
    return doc


def scored_days(data_dir: Path, **kwargs) -> Optional[set]:
    """Дни, входящие в знаменатель ``hit_rate`` — ОДНО определение на всех читателей.

    Знаменатель определяет этот модуль, поэтому и правило отбора живёт здесь, а не
    переписывается у каждого потребителя: два определения спорили бы о том же дне, и
    спор был бы молчаливым (обе стороны печатают число, ни одна — правило).

    ``None`` = «не измерено»: любой отказ канонического расчёта возвращает именно его,
    а НЕ пустое множество — пустое читалось бы как «оценённых дней нет».
    """
    try:
        report = evaluate_window(Path(data_dir), write=False, **kwargs)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        log.warning("знаменатель hit_rate не измерен: %s", exc)
        return None
    rows = report.get("per_verdict")
    if not isinstance(rows, list):
        return None
    return {str(r.get("cycle_date")) for r in rows
            if not r.get("trivial") and r.get("outcome") in ("hit", "miss")}


def format_blockade(blockade: Optional[dict]) -> List[str]:
    """Строки про достижимость взвода — общие для CLI и шага 0-офис.

    Отсутствие блока — ТРЕТИЙ исход, а не «блокады нет»: отчёт старого образца
    молчал бы ровно так же, как здоровый, и молчание читалось бы согласием.
    """
    if not isinstance(blockade, dict):
        return ["Достижимость взвода: ⚠️ НЕ ИЗМЕРЕНА — в отчёте нет блока "
                "`arming_blockade` (отчёт старого образца)"]
    mark = "🔴" if blockade.get("verdict") == BLOCKADE_UNREACHABLE else "•"
    out = [f"Достижимость взвода: {mark} {blockade.get('verdict')} — "
           f"{blockade.get('reason')}"]
    for row in (blockade.get("gate_census") or []):
        if not row.get("refused_days"):
            continue
        in_cover = row["gate"] in (blockade.get("blockade_cover") or [])
        flag = (" ← НЕОБХОДИМЫЙ" if row.get("necessary_blocker")
                else " ← В ПОКРЫТИИ" if in_cover else "")
        out.append(
            f"  отказ {row['gate']}: {row['refused_days']} дн. "
            f"({row['refused_pct']} % существенных), единственной причиной "
            f"{row['sole_blocker_days']} дн.{flag}")
    cover = blockade.get("blockade_cover")
    if cover:
        exact = blockade.get("cover_is_minimal")
        out.append(
            f"  покрытие тишины: {{{', '.join(cover)}}} — "
            f"{'минимальный набор' if exact else 'жадный набор (минимальность НЕ доказана)'}, "
            f"его отказы объясняют КАЖДЫЙ из {blockade.get('material_days')} "
            "существенных дней")
    act_able = blockade.get("act_able_days")
    if act_able:
        out.append(
            f"  ⚠️ НЕ ОБЪЯСНЕНО дней: {len(act_able)} — отказа гейта на них нет "
            f"вовсе, а ACT не оценён ({', '.join(act_able[:5])})")
    src_counts = blockade.get("gate_state_source") or {}
    if src_counts.get("reasons"):
        agree = blockade.get("reason_deriver_agreement") or {}
        out.append(
            f"  источник состояния гейтов: поле `gates` {src_counts.get('gates', 0)} дн. · "
            f"вывод из строк причин {src_counts['reasons']} дн. "
            f"(сверено на {agree.get('days_with_both_sources')} общих дн., "
            f"сошлось {agree.get('agreed')})")
    if src_counts.get("unmeasured"):
        out.append(f"  ⚠️ НЕ ИЗМЕРЕНО дней: {src_counts['unmeasured']} — "
                   "перепись отказов по ним не велась")
    return out


def format_trial_reach(reach: Optional[dict]) -> List[str]:
    """Строки про достижимость разрешения на пробный ход — CLI и шаг 0-офис.

    Отсутствие блока — ТРЕТИЙ исход: отчёт старого образца молчит ровно так же,
    как отчёт, в котором разрешение достижимо, и молчание читалось бы согласием.
    """
    if not isinstance(reach, dict):
        return ["Достижимость пробного хода: ⚠️ НЕ ИЗМЕРЕНА — в отчёте нет блока "
                "`trial_grant_reach` (отчёт старого образца)"]
    mark = "🔴" if reach.get("verdict") == REACH_BLOCKED else "•"
    grant = reach.get("grant") or {}
    after = reach.get("after_grant") or {}
    before = reach.get("before_grant") or {}
    out = [f"Достижимость пробного хода ({grant.get('adr')}): {mark} "
           f"{reach.get('verdict')} — {reach.get('reason')}",
           f"  после выдачи: записей {after.get('records')} "
           f"({after.get('dates')} дат) · измерено {after.get('measured_records')} · "
           f"разрешение сработало бы на {after.get('open_by_gates_records')} · "
           f"не измерено {after.get('unmeasured_records')}",
           f"  до выдачи для сравнения: {before.get('open_by_gates_records')} из "
           f"{before.get('records')} записей разрешение сработало бы"]
    for row in (reach.get("blocker_census") or [])[:5]:
        out.append(f"  мешает {row.get('gate') or row.get('class')}: "
                   f"{row.get('records')} зап. ({row.get('pct_of_after')} % после выдачи)")
    # Инв. #17: у образца НЕ ИЗМЕРЕННЫХ записей три исхода, а не два. `or []`
    # склеивал «поля нет вовсе» с «не измеренных нет», то есть делал молчание
    # отчёта СТАРОГО образца похожим на чистый замер — ровно в блоке, который
    # для этого и написан (ADR-846 объявил `_READ_SCHEMA` именно против этого).
    sample = observed(reach, "unmeasured_sample", kind=list)
    if sample is None:
        out.append("  ⚠️ образец НЕ ИЗМЕРЕННЫХ записей в отчёте не назван вовсе "
                   "(`unmeasured_sample`) — «не измеренных нет» отсюда сказать "
                   "нельзя")
    elif sample:
        out.append(f"  ⚠️ НЕ ИЗМЕРЕНО записей (образец {len(sample)}): "
                   + "; ".join(f"{r.get('date')} — {r.get('why')}" for r in sample[:2]))
    out.append("  ADVISORY: перепись только ЧИТАЕТ — ни разрешения, ни порога, ни "
               "вердикта она не меняет")
    return out


def format_summary(doc: dict) -> str:
    """Human-readable stdout summary (RU — owner-facing)."""
    lines = [
        "── Оценка теневого триггера (Y3, ADR-060) ─────────────────────",
        f"Статус: {doc['status']}  (готов к включению: "
        f"{'да' if doc.get('ready_to_arm') else 'нет'})",
        f"Дней наблюдения: {doc.get('observation_days')}",
        "Вердикты: ACT={act}  HOLD={hold} (из них тривиальных: {trivial_hold})  "
        "оценено: {scored}  UNCHECKED: {unchecked}".format(**doc.get("counts", {})),
        f"Hit-rate: {doc.get('hit_rate')}",
        f"Если бы следовали ACT: {doc.get('net_usd_if_followed')} USD "
        f"({doc.get('net_bps_if_followed')} bps капитала), net затрат",
        f"Упущено на HOLD суммарно: {doc.get('hold_missed_usd_total')} USD",
        "Критерии включения:",
    ]
    for c in doc.get("criteria", []):
        note = f" — {c['note']}" if c.get("note") else ""
        lines.append(f"  [{c['status']:>9}] {c['criterion']} {c['threshold']} "
                     f"(факт: {c['actual']}){note}")
    lines.extend(format_blockade(doc.get("arming_blockade")))
    lines.extend(format_trial_reach(doc.get("trial_grant_reach")))
    from spa_core.paper_trading.admissible_size import format_admissible_reach

    lines.extend(format_admissible_reach(doc.get("admissible_size_reach")))
    from spa_core.paper_trading.admissible_trim import (
        format_live_trim, format_live_trim_cost)

    lines.extend(format_live_trim(doc.get("live_trim_census")))
    # ADR-853: «чего это стоило» — отдельный вопрос с отдельными исходами
    # (шаг мог сработать, а цена остаться неизмеренной), поэтому и печать своя.
    lines.extend(format_live_trim_cost(doc.get("live_trim_census")))
    # ADR-854: «стоит ли формы различать» — третий вопрос с третьими исходами
    # (цена живого трима может быть не записана, а формы при этом сравнены на
    # всей истории), поэтому и печать своя.
    from spa_core.paper_trading.trim_shape import format_trim_shape

    lines.extend(format_trim_shape(doc.get("trim_shape_census")))
    # ADR-855: «пустит ли книгу формы политика» — четвёртый вопрос с четвёртыми
    # исходами (формы могут быть сравнены, а реестр тиров не прочитан, и
    # наоборот), поэтому и печать своя.
    from spa_core.paper_trading.trim_admissibility import (
        format_trim_admissibility)

    lines.extend(format_trim_admissibility(doc.get("trim_admissibility_census")))
    # ADR-859: «есть ли допустимая книга ЛУЧШЕ жадной» — пятый вопрос с пятыми
    # исходами (допустимость может быть измерена, а приз нет — ног больше
    # потолка перебора, — и наоборот), поэтому и печать своя.
    from spa_core.paper_trading.trim_optimum import format_trim_optimum

    lines.extend(format_trim_optimum(doc.get("trim_optimum_census")))

    from spa_core.paper_trading.trim_size_edge import format_trim_size_edge

    lines.extend(format_trim_size_edge(doc.get("trim_size_edge_census")))
    lines.append("Включение — отдельное owner-решение (pre_cutover_gate + ADR); "
                 "этот отчёт капитал не двигает.")
    return "\n".join(lines)
