"""cio_shadow_replay.py — §38 ТЗ «Portfolio CIO»: исторический прогон трёх стратегий.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §38 «Historical replay»::

    Если доступна historical data SPA: прогнать новый allocator на прошлом
    периоде БЕЗ look-ahead bias. Минимум сравнить: Current Strategy vs
    Portfolio CIO Shadow Strategy — по Net APY · Realized Return · Gas · Fees ·
    Turnover · Risk Events · Max Concentration · False Rebalances · Missed
    Opportunities. Главная цель: не показать максимальный APY на бумаге, а
    показать улучшение risk-adjusted realized net return.

Ответ на «мерил ли кто-нибудь» — **НЕТ**, и имя при этом ЗАНЯТО
================================================================
В дереве есть модуль ``spa_core/paper_trading/historical_replay.py`` — ровно то
слово, которым назван критерий. Он отвечает на ДРУГОЙ вопрос: гоняет три
учебные стратегии (``equal_weight`` / ``best_apy`` / ``buy_and_hold_best``) по
``data/historical_apy.json``, у которого ``data_source: synthetic``. Замер 06.09
в живом дереве: **входного файла нет, выходного файла нет, вызывающих в проде
ноль** (единственный импорт — его собственный тест). Ни CIO-тени, ни стоимости,
ни оборота, ни концентрации, ни ложных перекладок в нём нет вовсе.

То есть по имени критерий §38 читается закрытым, а по существу не измерен ни
разу — тот же класс «одно имя — один объект», что `.claude/rules/adapters.md`
описывает для трёх разных `ADAPTER_REGISTRY`. Этот модуль тот, прежний, НЕ
трогает и не заменяет: он отвечает на вопрос §38, а не на вопрос про синтетику.

Три стратегии, и каждая названа — чтобы было видно, какое число чьё
==================================================================
Накопитель ADR-060 (``data/allocation_rationale_history.jsonl``) хранит за
каждый день ТРИ вещи сразу: книгу, какой она фактически была
(``current_positions``), книгу, какую предлагал тюнер (``target_positions``), и
наблюдённые ставки (``apy_evidenced_pct``). Отсюда ровно три прогоняемые руки:

``current``
    **Current Strategy** — книга, какой она БЫЛА. Не «стратегия» в смысле
    правила, а факт: её двигает живой аллокатор.

``cio_hold``
    **Portfolio CIO Shadow Strategy, как она РЕАЛЬНО работала.** Слой ADR-060 за
    все наблюдённые дни вынес ``HOLD`` — ни одного ``ACT``. Следовать ему
    буквально значит не совершить ни одной перекладки: книга остаётся такой,
    какой была в первый день окна. ТЗ прямо говорит, что это полноценное
    инвестиционное решение: «Решение DO NOTHING / KEEP … не должно считаться
    отсутствием работы».

``cio_opt``
    **Оптимум тюнера без гейтов** — каждый день книга приводится к
    ``target_positions``. Это НЕ то, что делал CIO; это мера того, чего стоят
    сами гейты: если оптимум лучше факта, гейты дороги, если хуже — гейты
    спасают.

Без look-ahead — и это не декларация, а свойство прогона
========================================================
Композиция каждого дня оценивается ставками СЛЕДУЮЩЕГО дня, одинаково у всех
трёх рук. Иначе рука ``cio_opt`` получила бы фору по построению: её состав
выбран из ставок ТОГО ЖЕ дня, то есть она «угадывала» бы победителя задним
числом. Сдвиг на день снимает это у всех сразу.

Популяция — общие дни, а не «у кого сколько нашлось»
=====================================================
Наблюдённые ставки покрывают лишь те протоколы, которых книга или цель
касались в этот день. Замороженная рука держит протоколы, из которых книга
давно ушла, — их цен в этот день нет. Поэтому руки покрыты РАЗНЫМ числом дней,
и складывать их итоги нельзя: это ровно ошибка «групповой срез принят за
приговор элементу». Сравнение считается на **общих** днях — тех, где сверены
ВСЕ руки; остальные дни называются вслух как ``UNCHECKED`` и не
интерполируются (тот же fail-CLOSED, что у ``_day_gain_usd``).

Ни один порог здесь не назначен
================================
Горизонт окупаемости и пыльный порог ноги — у ``TriggerParams.for_mode()``;
формула дневной выгоды и горизонт сверки — у ``shadow_trigger_eval``;
разбор ног и стоимость хода — у ``rebalance_economics``; компоненты стоимости —
у ``tier1.cost_model``; наблюдённый газ — у ``rebalance_cost_evidence``;
потолок концентрации — у ``RiskConfig``. Литералов решения в модуле нет.

Стоимость показывается ДВУМЯ колонками
=======================================
ADR-243 измерил, что заряжаемый газ — литерал, расходящийся с наблюдаемым в
сотни раз. Поэтому вывод, который держится только на заряженном газе, ничего
не стоит. Каждая рука считается ДВАЖДЫ: «заряжено» (как решает система
сегодня) и «наблюдено» (газ подставлен из живого наблюдения, проскальзывание
и мост остаются, потому что они — доли оборота, а не литерал за ногу). Находка
объявляется, только если она переживает ОБЕ колонки.

Чего этот модуль НЕ делает
==========================
Не двигает капитал, не трогает ``_move_cost_usd``, гейты, целевую функцию
тюнера, RiskPolicy и kill-switch. ADVISORY: он **называет** результат прогона.
Любая правка порогов по его итогам — money-path и решение владельца.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Callable

from spa_core.utils.observation import observed as observed_field
from spa_core.utils.observation import observed_number

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/cio_shadow_replay.json"

_UNCHECKED = "UNCHECKED"

#: Имена рук. Порядок фиксирован: отчёт читают глазами, и «current» первым —
#: это то, что происходит с деньгами сейчас.
ARM_CURRENT = "current"
ARM_CIO_HOLD = "cio_hold"
ARM_CIO_OPT = "cio_opt"
ARMS = (ARM_CURRENT, ARM_CIO_HOLD, ARM_CIO_OPT)

#: Колонки стоимости, в которых прогон обязан дойти до сравнения. ДВЕ, и это
#: не оформление: вывод, живущий только на ЗАРЯЖЕННОМ (литеральном) газе,
#: ADR-243 уже опроверг на этом самом прогоне — на наблюдённом газе число
#: ложных перекладок стало 9 из 13 вместо 12 из 13. Перечень ЗАКРЫТ, и его
#: спрашивают ОБА читателя: сборщик колонок в :func:`run` и вердикт критерия
#: §49. Разойдись они — вердикт требовал бы колонку, которой сборщик не делает.
COST_COLUMNS = ("charged", "observed")

#: Порог, ниже которого прогон САМ отказывается утверждать свой вывод. Дом у
#: него ОДИН, и сравнение с ним — ровно одно, в :func:`population_too_thin`
#: ниже (ADR-220); второй копии нет намеренно, и единственность сравнения
#: МЕРЯЕТСЯ AST, а не доверием к этому комментарию
#: (`spa_core/tests/test_s49_shadow_verification_probe.py`).
MIN_COMMON_DAYS_FOR_CLAIM = 10

#: Код той находки — для читателя-человека.
THIN_POPULATION_CODE = "thin_common_population"


def population_too_thin(common_scored_days: float) -> bool:
    """Узка ли популяция настолько, что прогон своего вывода НЕ утверждает.

    Дом правила ОДИН (ADR-220), и оба его читателя зовут эту функцию: находка
    `thin_common_population` для человека и вердикт критерия §49 для машины.

    Почему вердикт зовёт ПРЕДИКАТ, а не ищет находку в отчёте: отчёт, собранный
    версией прибора без этой находки, читался бы тогда как «вывод утверждаем» —
    fail-OPEN, то есть ровно тот дефект, который инв. #17 запрещает (отсутствие
    наблюдения выданное за благополучие). Предикат отвечает по ЧИСЛУ, которое в
    отчёте есть всегда.
    """
    return common_scored_days < MIN_COMMON_DAYS_FOR_CLAIM


#: Критерий §49 приказа владельца «Portfolio CIO», мерой которого модуль себя
#: объявляет. Якорь читается как НАЧАЛО строки (ADR-333): упоминание критерия
#: в середине текста есть ссылка на него, а не объявление себя его мерой.
#:
#: Критерий у владельца назван ОДНОЙ фразой и мерится ОДНИМ прибором — в
#: отличие от `Auditability`, где слов было два и населения разные (ADR-808).
CRITERION = (
    "§49 Shadow verification приказа владельца «Portfolio CIO» — дословно: "
    "«Проведены shadow/replay tests». Мера — ИСХОД прогона: сверены ли дни во "
    "ВСЕХ трёх руках, дошло ли сравнение до вердикта в ОБЕИХ колонках "
    "стоимости и не отказался ли прогон САМ утверждать свой вывод. Наличие "
    "файла отчёта мерой не является"
)

CRITERION_SATISFIED = "SATISFIED"
CRITERION_NOT_SATISFIED = "NOT_SATISFIED"
CRITERION_UNMEASURED = "UNMEASURED"


def _num(v: object) -> float | None:
    """Число или None. Строку-число принимаем, мусор — нет."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _positions(rec: dict, key: str) -> dict[str, float]:
    raw = rec.get(key) or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for proto, usd in raw.items():
        v = _num(usd)
        if v is not None and v > 0.0:
            out[str(proto)] = v
    return out


# ── Построение рук ────────────────────────────────────────────────────────────

def build_arms(records: list[dict]) -> dict[str, list[dict[str, float]]]:
    """Композиция каждой руки на каждый день истории.

    ``cio_hold`` заморожена НЕ потому, что «так решили», а потому, что слой
    ADR-060 вынес ``HOLD``: следовать вердикту буквально = не двигать книгу.
    Если бы в истории встретился ``ACT``, рука обязана была бы принять цель
    того дня — это и делает ветка ниже, а не литеральная заморозка.
    """
    current = [_positions(r, "current_positions") for r in records]
    target = [_positions(r, "target_positions") for r in records]

    hold: list[dict[str, float]] = []
    book = dict(current[0]) if current else {}
    for i, rec in enumerate(records):
        if i and str(rec.get("verdict") or "").upper() == "ACT":
            book = dict(target[i])
        hold.append(dict(book))
    return {ARM_CURRENT: current, ARM_CIO_HOLD: hold, ARM_CIO_OPT: target}


# ── Дневная доходность и стоимость ────────────────────────────────────────────

def score_days(books: list[dict[str, float]], records: list[dict], *,
               day_gain: Callable[[dict, dict], tuple[float | None, list]],
               ) -> tuple[list[float | None], set[str]]:
    """Выручка каждого дня по ставкам СЛЕДУЮЩЕГО дня. ``None`` = день не сверен.

    Формула выгоды берётся у производителя вердикта: книга — это набор
    положительных «дельт», и та же функция обязана считать обе стороны
    сравнения, иначе руки разойдутся по определению выгоды, а не по существу.
    """
    out: list[float | None] = []
    unpriced: set[str] = set()
    for i in range(len(records) - 1):
        gain, missing = day_gain(
            books[i], observed_field(records[i + 1], "apy_evidenced_pct", kind=dict) or {})
        if gain is None:
            unpriced.update(missing)
        out.append(gain)
    return out, unpriced


def move_costs(books: list[dict[str, float]], records: list[dict], *,
               legs_of: Callable[..., tuple[list[dict], float]],
               min_leg_frac: float, chains: dict[str, str],
               gas_of: Callable[[str], float | None],
               slippage_bps: float, bridge_bps: float) -> list[dict]:
    """Стоимость каждого перехода книги: газ за ногу + проскальзывание + мост.

    ``gas_of`` инъектируется, чтобы одна и та же арифметика дала обе колонки —
    заряженную и наблюдённую. Разбор ног и понятие оборота НЕ пишутся заново.
    """
    out: list[dict] = []
    for i in range(1, len(records)):
        capital = observed_number(records[i], "capital_usd")
        if capital is None or capital <= 0.0:
            # Доля ноги считается ОТ КАПИТАЛА: ноль вместо ненаписанного капитала
            # объявил бы каждую ногу несущественной (инвариант #17).
            continue
        legs, turnover = legs_of(books[i - 1], books[i], capital, min_leg_frac)
        if not legs:
            continue
        gas = 0.0
        touched: set[str] = set()
        for leg in legs:
            chain = str(chains.get(leg["protocol"], "blended")).lower()
            touched.add(chain)
            per_leg = gas_of(chain)
            if per_leg is not None:
                gas += per_leg
        slippage = turnover * (slippage_bps / 10_000.0)
        bridge = (turnover * (bridge_bps / 10_000.0)) if len(touched) > 1 else 0.0
        out.append({
            "day_index": i,
            "cycle_date": records[i].get("cycle_date"),
            "legs": legs,
            "turnover_usd": turnover,
            "gas_usd": gas,
            "fees_usd": slippage + bridge,
            "cost_usd": gas + slippage + bridge,
        })
    return out


# ── Девять метрик одной руки ──────────────────────────────────────────────────

def arm_metrics(daily: list[float | None], moves: list[dict], records: list[dict],
                books: list[dict[str, float]], common: list[int], *,
                concentration_cap: float | None) -> dict:
    """Метрики §38 на ОБЩЕЙ популяции дней. Пустая популяция ⇒ третий исход."""
    if not common:
        return {"scored_days": 0, "verdict": _UNCHECKED,
                "reason": "общих сверенных дней нет — сравнивать нечего"}

    gross = sum(v for v in (daily[i] for i in common) if v is not None)
    on_common = [m for m in moves if m["day_index"] in common]
    gas = sum(m["gas_usd"] for m in on_common)
    fees = sum(m["fees_usd"] for m in on_common)
    turnover = sum(m["turnover_usd"] for m in on_common)
    cost = gas + fees
    net = gross - cost

    # Знаменатель концентрации — КАПИТАЛ дня, а не развёрнутая книга: потолок
    # RiskPolicy меряется от капитала, и взять здесь другой знаменатель значило
    # бы сравнивать с порогом не то, что он ограничивает.
    max_conc = 0.0
    max_conc_day = None
    risk_events = 0
    for i in common:
        capital = observed_number(records[i], "capital_usd")
        if capital is None or capital <= 0.0 or not books[i]:
            continue
        share = max(books[i].values()) / capital
        if share > max_conc:
            max_conc, max_conc_day = share, records[i].get("cycle_date")
        if concentration_cap is not None and share > concentration_cap:
            risk_events += 1

    # `None` — капитал первого дня НЕ записан; это не «капитал ноль», и доли
    # ниже тогда не считаются вовсе (инвариант #17).
    capital0 = observed_number(records[common[0]], "capital_usd")
    days = len(common)
    out = {
        "scored_days": days,
        "gross_usd": round(gross, 4),
        "gas_usd": round(gas, 4),
        "fees_usd": round(fees, 4),
        "cost_usd": round(cost, 4),
        "realized_return_usd": round(net, 4),
        "turnover_usd": round(turnover, 2),
        "moves": len(on_common),
        "max_concentration": round(max_conc, 4),
        "max_concentration_day": max_conc_day,
        "risk_events": (risk_events if concentration_cap is not None else None),
    }
    if capital0 is not None and capital0 > 0.0:
        out["net_apy_pct"] = round(net / capital0 * 365.0 / days * 100.0, 4)
        out["gross_apy_pct"] = round(gross / capital0 * 365.0 / days * 100.0, 4)
        out["turnover_x_capital"] = round(turnover / capital0, 3)
    return out


def false_rebalances(moves: list[dict], records: list[dict], *,
                     day_gain: Callable[[dict, dict], tuple[float | None, list]],
                     horizon_days: int, max_payback_days: float | None) -> dict:
    """Перекладка, которая НЕ окупается за горизонт, — ложная.

    Порог берётся у демпфера (``max_payback_days``), а не назначается здесь:
    ложной перекладку делает не наше мнение, а тот самый срок, которым система
    сама разрешает ход. Отрицательная реализованная выгода — ложная всегда:
    окупаться нечему.
    """
    if max_payback_days is None:
        return {"verdict": _UNCHECKED,
                "reason": "горизонт окупаемости не прочитан — ложность не определена"}
    checked = 0
    unchecked = 0
    bad: list[dict] = []
    for m in moves:
        deltas = {leg["protocol"]: float(leg["delta_usd"]) for leg in m["legs"]}
        total = 0.0
        n = 0
        for frec in records[m["day_index"] + 1: m["day_index"] + 1 + horizon_days]:
            gain, _ = day_gain(
            deltas, observed_field(frec, "apy_evidenced_pct", kind=dict) or {})
            if gain is None:
                continue
            total += gain
            n += 1
        if n == 0:
            unchecked += 1
            continue
        checked += 1
        per_day = total / n
        payback = (m["cost_usd"] / per_day) if per_day > 0.0 else None
        if payback is None or payback > max_payback_days:
            bad.append({
                "cycle_date": m["cycle_date"],
                "turnover_usd": round(m["turnover_usd"], 2),
                "cost_usd": round(m["cost_usd"], 2),
                "realised_usd_per_day": round(per_day, 4),
                "payback_days": (round(payback, 1) if payback is not None else None),
                "forward_days_priced": n,
            })
    return {"checked": checked, "unchecked": unchecked, "false": len(bad),
            "max_payback_days": max_payback_days, "worst": bad[:5]}


def missed_opportunities(daily: dict[str, list[float | None]], moves_opt: list[dict],
                         common: list[int], *, band_pp_of: Callable[[int], float | None],
                         records: list[dict]) -> dict:
    """Дни, в которые НЕсделанный ход тюнера окупился бы вперёд.

    Пропущенной возможность делает не превосходство оптимума по ставке, а
    превосходство ПОСЛЕ его собственной стоимости: ход, который лучше на
    величину меньше собственной цены, — не возможность, а расход.
    """
    if not common:
        return {"verdict": _UNCHECKED, "reason": "общих сверенных дней нет"}
    cost_by_day = {m["day_index"]: m["cost_usd"] for m in moves_opt}
    missed: list[dict] = []
    for i in common:
        cur = daily[ARM_CURRENT][i]
        opt = daily[ARM_CIO_OPT][i]
        if cur is None or opt is None:
            continue
        edge = opt - cur
        cost = cost_by_day.get(i, 0.0)
        capital = observed_number(records[i], "capital_usd")
        band_pp = band_pp_of(i)
        band_usd_per_day = ((band_pp / 100.0 * capital / 365.0)
                            if (band_pp is not None and capital is not None
                                and capital > 0.0) else 0.0)
        if edge - cost > band_usd_per_day:
            missed.append({
                "cycle_date": records[i].get("cycle_date"),
                "edge_usd_per_day": round(edge, 4),
                "cost_usd": round(cost, 2),
                "band_usd_per_day": round(band_usd_per_day, 4),
            })
    return {"checked": len(common), "missed": len(missed), "worst": missed[:5]}


# ── Прогон ────────────────────────────────────────────────────────────────────

def run(root: str | None = None, *, now: dt.datetime | None = None,
        read: Callable[[str], Any] = _read_json, write: bool = True) -> dict:
    """Собрать отчёт. ``now`` инъектируется — иных обращений к часам здесь нет."""
    root = root or REPO_ROOT
    now = now or dt.datetime.now(dt.timezone.utc)
    ddir = os.path.join(root, "data")

    findings: list[dict] = []
    unchecked: list[str] = []
    provenance: dict[str, str] = {}

    # Инструменты. Их отсутствие — САМОСТОЯТЕЛЬНЫЙ третий исход: «нечем
    # прогнать» не имеет права выглядеть как «разницы нет».
    try:
        from spa_core.paper_trading import shadow_trigger_eval as _ste
        day_gain = _ste._day_gain_usd
        horizon_days = int(_ste.DEFAULT_HORIZON_DAYS)
        load_history = _ste.load_history
        provenance["gain_formula"] = ("spa_core.paper_trading.shadow_trigger_eval."
                                      "_day_gain_usd / DEFAULT_HORIZON_DAYS")
    except Exception as exc:  # noqa: BLE001
        return _report(root, now, overall=_UNCHECKED, arms={}, findings=[],
                       unchecked=[f"формулу выгоды взять неоткуда: {exc}"],
                       population={}, comparison={}, false_reb={}, missed={},
                       provenance=provenance, write=write)

    try:
        from spa_core.allocator.rebalance_economics import _legs, TriggerParams
        from spa_core.backtesting.tier1.cost_model import (
            GAS_USD_PER_POSITION_CHANGE, SLIPPAGE_BPS_STABLE, BRIDGE_BPS)
        params = TriggerParams.for_mode()
        provenance["cost_model"] = ("spa_core.allocator.rebalance_economics._legs + "
                                    "spa_core.backtesting.tier1.cost_model")
        provenance["params"] = (f"TriggerParams.for_mode() → mode={params.mode} "
                                f"max_payback_days={params.max_payback_days} "
                                f"min_leg_frac={params.min_leg_frac}")
    except Exception as exc:  # noqa: BLE001
        return _report(root, now, overall=_UNCHECKED, arms={}, findings=[],
                       unchecked=[f"модель стоимости взять неоткуда: {exc}"],
                       population={}, comparison={}, false_reb={}, missed={},
                       provenance=provenance, write=write)

    try:
        records, bad_lines = load_history(Path(ddir))
    except Exception as exc:  # noqa: BLE001
        return _report(root, now, overall=_UNCHECKED, arms={}, findings=[],
                       unchecked=[f"история вердиктов нечитаема: {exc}"],
                       population={}, comparison={}, false_reb={}, missed={},
                       provenance=provenance, write=write)

    if len(records) < 2:
        return _report(root, now, overall=_UNCHECKED, arms={}, findings=[],
                       unchecked=["истории меньше двух дней — прогонять нечего"],
                       population={"days_observed": len(records)}, comparison={},
                       false_reb={}, missed={}, provenance=provenance, write=write)

    # Карта сетей — ТОТ ЖЕ источник, что у настоящего вызывающего.
    chains: dict[str, str] = {}
    reg = read(os.path.join(ddir, "adapter_registry.json"))
    if isinstance(reg, dict):
        for name, entry in (reg.get("adapters") or {}).items():
            if isinstance(entry, dict) and entry.get("chain"):
                chains[str(name)] = str(entry["chain"]).strip().lower()
    if not chains:
        unchecked.append("карта сетей не прочитана — газ считается по умолчанию "
                         "`blended` для каждой ноги")

    # Потолок концентрации — у RiskConfig. Тир протокола здесь не разрешается,
    # поэтому берётся САМЫЙ ШИРОКИЙ потолок: превышение самого широкого есть
    # превышение любого, а обратное неверно — так счёт событий не завышается.
    concentration_cap = None
    try:
        from spa_core.risk.policy import RiskConfig
        concentration_cap = float(RiskConfig().max_concentration_t1)
        provenance["concentration_cap"] = (
            f"RiskConfig().max_concentration_t1={concentration_cap} "
            f"(самый широкий потолок; знаменатель — капитал дня)")
    except Exception as exc:  # noqa: BLE001
        unchecked.append(f"потолок концентрации не прочитан ({exc}) — "
                         f"risk_events не считается")

    # Наблюдённый газ (ADR-243). Его отсутствие не валит прогон — оно снимает
    # ВТОРУЮ колонку и объявляется вслух.
    observed_gas: dict[str, dict] = {}
    try:
        from spa_core.monitoring.rebalance_cost_evidence import observed_gas_usd_per_leg
        obs = observed_gas_usd_per_leg(read(os.path.join(ddir, "gas_price_history.json")),
                                       now=now)
        if obs.get("measured"):
            observed_gas = obs.get("chains") or {}
            provenance["observed_gas"] = ("spa_core.monitoring.rebalance_cost_evidence."
                                          "observed_gas_usd_per_leg (ADR-243)")
        else:
            unchecked.append(f"наблюдённого газа нет ({obs.get('reason')}) — "
                             f"колонка «наблюдено» не считается")
    except Exception as exc:  # noqa: BLE001
        unchecked.append(f"наблюдённый газ не прочитан ({exc}) — "
                         f"колонка «наблюдено» не считается")

    def charged_gas(chain: str) -> float:
        return float(GAS_USD_PER_POSITION_CHANGE.get(
            chain, GAS_USD_PER_POSITION_CHANGE.get("blended", 0.0)))

    def observed_or_charged_gas(chain: str) -> float:
        row = observed_field(observed_gas, chain, kind=dict) or {}
        if row.get("measured"):
            per_leg = observed_number(row, "usd_per_leg")
            if per_leg is None:
                # Помечено «измерено», а числа нет: объявлять газ бесплатным
                # нельзя — берётся заряженная ставка, как при неизмеренном.
                return charged_gas(chain)
            return float(per_leg)
        return charged_gas(chain)

    # ── Прогон трёх рук ──────────────────────────────────────────────────────
    books = build_arms(records)
    daily: dict[str, list[float | None]] = {}
    unpriced: dict[str, list[str]] = {}
    for arm in ARMS:
        d, miss = score_days(books[arm], records, day_gain=day_gain)
        daily[arm] = d
        unpriced[arm] = sorted(miss)

    common = [i for i in range(len(records) - 1)
              if all(daily[arm][i] is not None for arm in ARMS)]

    # Имена колонок берутся из ОДНОГО перечня (`COST_COLUMNS`), а не набираются
    # здесь второй раз: вердикт критерия §49 ниже спрашивает ровно этот перечень,
    # и разойдись они — он требовал бы колонку, которой сборщик не делает, либо
    # пропускал бы ту, которую делает. Отсутствие цены за колонку — KeyError,
    # то есть ГРОМКИЙ отказ, а не молчаливый пропуск.
    gas_of_column = {"charged": charged_gas, "observed": observed_or_charged_gas}
    columns: dict[str, dict] = {}
    for column in COST_COLUMNS:
        gas_of = gas_of_column[column]
        if column == "observed" and not observed_gas:
            continue
        moves = {arm: move_costs(books[arm], records, legs_of=_legs,
                                 min_leg_frac=params.min_leg_frac, chains=chains,
                                 gas_of=gas_of, slippage_bps=SLIPPAGE_BPS_STABLE,
                                 bridge_bps=BRIDGE_BPS)
                 for arm in ARMS}
        arms_out = {arm: arm_metrics(daily[arm], moves[arm], records, books[arm],
                                     common, concentration_cap=concentration_cap)
                    for arm in ARMS}
        columns[column] = {
            "arms": arms_out,
            "false_rebalances": false_rebalances(
                moves[ARM_CURRENT], records, day_gain=day_gain,
                horizon_days=horizon_days,
                max_payback_days=float(params.max_payback_days)),
            "missed_opportunities": missed_opportunities(
                daily, moves[ARM_CIO_OPT], common,
                band_pp_of=lambda i: _num(records[i].get("required_gain_pp")),
                records=records),
        }

    population = {
        "days_observed": len(records),
        "day_pairs": len(records) - 1,
        "common_scored_days": len(common),
        "common_dates": [records[i].get("cycle_date") for i in common],
        "scored_per_arm": {arm: sum(1 for v in daily[arm] if v is not None)
                           for arm in ARMS},
        "unpriced_per_arm": unpriced,
        "unparseable_history_lines": bad_lines,
        "horizon_days": horizon_days,
        "verdicts": _verdict_counts(records),
    }

    if not common:
        unchecked.append("ни одного дня, сверенного во ВСЕХ трёх руках: у "
                         "замороженной руки нет цен на протоколы, из которых "
                         "книга ушла — интерполировать их запрещено")
        return _report(root, now, overall=_UNCHECKED, arms={}, findings=findings,
                       unchecked=unchecked, population=population,
                       comparison={}, false_reb={}, missed={},
                       provenance=provenance, write=write)

    # ── Находки: только то, что переживает ОБЕ колонки стоимости ─────────────
    comparison = _compare(columns)
    findings.extend(_findings(columns, comparison, population))

    counts_critical = any(f["severity"] == "CRITICAL" for f in findings)
    counts_warn = any(f["severity"] == "WARN" for f in findings)
    overall = ("CRITICAL" if counts_critical else
               "WARN" if counts_warn else "OK")

    return _report(root, now, overall=overall, arms=columns, findings=findings,
                   unchecked=unchecked, population=population,
                   comparison=comparison,
                   false_reb=columns["charged"]["false_rebalances"],
                   missed=columns["charged"]["missed_opportunities"],
                   provenance=provenance, write=write)


def _verdict_counts(records: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for rec in records:
        key = str(rec.get("verdict") or "UNKNOWN").upper()
        out[key] = out.get(key, 0) + 1
    return out


def _compare(columns: dict[str, dict]) -> dict:
    """Насколько тень обошла факт — в каждой колонке стоимости отдельно."""
    out: dict[str, dict] = {}
    for column, block in columns.items():
        cur = block["arms"].get(ARM_CURRENT) or {}
        hold = block["arms"].get(ARM_CIO_HOLD) or {}
        opt = block["arms"].get(ARM_CIO_OPT) or {}
        if not all(a.get("net_apy_pct") is not None for a in (cur, hold, opt)):
            out[column] = {"verdict": _UNCHECKED,
                           "reason": "чистая доходность руки не посчитана"}
            continue
        out[column] = {
            "net_apy_pct": {ARM_CURRENT: cur["net_apy_pct"],
                            ARM_CIO_HOLD: hold["net_apy_pct"],
                            ARM_CIO_OPT: opt["net_apy_pct"]},
            "gross_apy_pct": {ARM_CURRENT: cur["gross_apy_pct"],
                              ARM_CIO_HOLD: hold["gross_apy_pct"],
                              ARM_CIO_OPT: opt["gross_apy_pct"]},
            "hold_minus_current_pp": round(
                hold["net_apy_pct"] - cur["net_apy_pct"], 4),
            "opt_minus_current_pp": round(
                opt["net_apy_pct"] - cur["net_apy_pct"], 4),
            # Разница ВАЛОВОЙ доходности отвечает на другой вопрос: выиграла
            # тень выбором ставок или тем, что не платила за ход.
            "gross_spread_pp": round(
                max(cur["gross_apy_pct"], hold["gross_apy_pct"], opt["gross_apy_pct"])
                - min(cur["gross_apy_pct"], hold["gross_apy_pct"], opt["gross_apy_pct"]), 4),
            "best_net_arm": max((cur, ARM_CURRENT), (hold, ARM_CIO_HOLD),
                                (opt, ARM_CIO_OPT),
                                key=lambda pair: pair[0]["net_apy_pct"])[1],
        }
    return out


def _findings(columns: dict[str, dict], comparison: dict, population: dict) -> list[dict]:
    findings: list[dict] = []
    charged = comparison.get("charged") or {}
    if charged.get("verdict") == _UNCHECKED:
        return findings

    # Находка объявляется, только если она держится в ОБЕИХ колонках: вывод,
    # живущий лишь на заряженном газе, ADR-243 уже опроверг.
    observed = comparison.get("observed")
    both = [c for c in (charged, observed) if isinstance(c, dict)
            and c.get("verdict") != _UNCHECKED]

    if all(c["hold_minus_current_pp"] > 0.0 for c in both):
        worst = min(c["hold_minus_current_pp"] for c in both)
        best = max(c["hold_minus_current_pp"] for c in both)
        cur_cost = (columns["charged"]["arms"][ARM_CURRENT].get("cost_usd"))
        cur_gross = (columns["charged"]["arms"][ARM_CURRENT].get("gross_usd"))
        findings.append({
            "severity": "CRITICAL",
            "code": "hold_beats_the_live_book",
            "message": (
                f"на {population['common_scored_days']} общих сверенных дн. "
                f"НЕсделанная перекладка обошла живую книгу по чистой доходности "
                f"на {worst}…{best} пп годовых (обе колонки стоимости); валовые "
                f"доходности рук расходятся лишь на "
                f"{charged.get('gross_spread_pp')} пп — разница создана НЕ "
                f"выбором ставок, а платой за оборот (${cur_cost} стоимости "
                f"против ${cur_gross} валовой выручки)"),
        })
    if all(c["opt_minus_current_pp"] < 0.0 for c in both) and both:
        findings.append({
            "severity": "WARN",
            "code": "chasing_the_optimum_is_worse",
            "message": (
                "погоня за оптимумом тюнера КАЖДЫЙ день хуже фактической книги "
                "в обеих колонках стоимости — гейты ADR-060 здесь спасают "
                "деньги, а не стоят их"),
        })

    fr = (observed_field(columns["charged"], "false_rebalances", kind=dict) or {})
    fr_obs = (observed_field(observed_field(columns, "observed", kind=dict) or {},
                             "false_rebalances", kind=dict) or {})
    if fr.get("checked") and fr.get("false"):
        tail = ""
        if fr_obs.get("checked"):
            tail = (f"; на НАБЛЮДЁННОМ газе — {fr_obs['false']} из "
                    f"{fr_obs['checked']}")
        findings.append({
            "severity": "CRITICAL",
            "code": "false_rebalances_dominate",
            "message": (
                f"{fr['false']} из {fr['checked']} проверяемых перекладок живой "
                f"книги НЕ окупаются за {fr['max_payback_days']} дн. — срок, "
                f"которым система сама разрешает ход{tail}; не сверено "
                f"{fr.get('unchecked')} (нет цен вперёд)"),
        })

    mo = (columns["charged"]["missed_opportunities"] or {})
    if mo.get("missed"):
        findings.append({
            "severity": "WARN",
            "code": "missed_opportunities",
            "message": (f"{mo['missed']} из {mo['checked']} общих дн. несделанный "
                        f"ход тюнера окупился бы вперёд сверх полосы гейта"),
        })

    if population_too_thin(population["common_scored_days"]):
        findings.append({
            "severity": "WARN",
            "code": THIN_POPULATION_CODE,
            "message": (
                f"общих сверенных дней {population['common_scored_days']} из "
                f"{population['day_pairs']} — прогон снят на узкой популяции, и "
                f"улучшение risk-adjusted return на ней НЕ утверждается: "
                f"наблюдённые ставки покрывают только протоколы, которых книга "
                f"или цель касались в этот день"),
        })
    return findings


def _why_unread(doc: dict) -> str:
    """Что сам отчёт говорит о НЕПРОЧИТАННОМ. Три исхода, и `or []` схлопнул бы два.

    «Раздела `unchecked` в отчёте нет» и «отчёт назвал непрочитанного ноль» —
    РАЗНЫЕ положения дел и чинятся разным (инв. #17): первое означает, что
    отчёт собран не этим прибором или устаревшей его версией, второе — что
    прибор прошёл всё и молчать ему не о чем.
    """
    unread = observed_field(doc, "unchecked", kind=list)
    if unread is None:
        return "раздела `unchecked` в отчёте нет — причина НЕ ИЗМЕРЕНА"
    if not unread:
        return "отчёт не называет непрочитанного ни одной строкой"
    return "; ".join(str(item) for item in unread)


def criterion_verdict(doc: dict) -> dict:
    """Вердикт о критерии §49 `Shadow verification` — по уже снятому отчёту.

    Правило вычисления живёт ЗДЕСЬ, у производителя чисел, и второй его копии
    нет (ADR-220): читатель (`card_acceptance`) вердикт ПЕРЕНОСИТ, а не считает
    заново.

    Дословные слова владельца — «**Проведены shadow/replay tests**». Вопрос
    поэтому о ПРОВЕДЁННОСТИ, а не о том, кто победил: находки
    `hold_beats_the_live_book` и `false_rebalances_dominate` говорят о
    СОДЕРЖАНИИ §38 и есть money-path — решение владельца, а не вердикт этого
    критерия. Прогон, нашедший, что живая книга проигрывает тени, проведён; он
    и обязан считаться проведённым.

    **Переносится НЕ `overall`.** `overall` этого модуля есть лестница ТЯЖЕСТИ
    находок (`CRITICAL` > `WARN` > `OK`), и живой замер 25.10 даёт на нём
    `CRITICAL` именно потому, что прогон СОСТОЯЛСЯ и нашёл дефект. Переносить
    такую лестницу в вердикт критерия значило бы объявить невыполненным
    критерий, который как раз выполняется, — вопрос соседний, ответ обратный.

    Своего порога у вердикта нет ни одного: узость популяции судит
    :func:`population_too_thin` — тот же предикат, которым прогон рождает свою
    находку `thin_common_population`. Порог живёт в ОДНОМ месте
    (:data:`MIN_COMMON_DAYS_FOR_CLAIM`), и второго сравнения с ним здесь нет.

    Четыре вопроса, и каждый обязан дойти до «да», чтобы прогон считался
    проведённым:

    1. сверенных во ВСЕХ трёх руках дней хотя бы один;
    2. сравнение дошло до вердикта в ОБЕИХ колонках стоимости
       (:data:`COST_COLUMNS`) — одноколоночный вывод ADR-243 опроверг на этом
       же прогоне;
    3. у каждой из трёх рук в каждой колонке есть читаемая чистая ставка —
       иначе сравнения «Current против CIO Shadow» не было, что бы ни стояло
       в графе вердикта;
    4. популяция не узка по мерке самого прогона — то есть прогон не отзывает
       свой вывод сам.

    Три исхода разведены (инв. #17):

    * `SATISFIED` — все четыре «да»: прогон проведён, и вывод его утверждаем;
    * `NOT_SATISFIED` — прогон состоялся, но САМ отказался утверждать вывод:
      популяция узка, и это ИЗМЕРЕНО числами и адресами (сколько дней, из
      скольких пар, у каких протоколов нет цен вперёд);
    * `UNMEASURED` — раздела `population` нет / числа в нём не читаются /
      **сверенных дней НОЛЬ** / колонки стоимости нет или её вердикт
      `UNCHECKED` / перечень находок не прочитан. Ноль сверенных дней не
      «чисто»: «тень сверена с фактом» при нуле сверенных дней верно ПО
      ПОСТРОЕНИЮ и ответом на вопрос владельца не является.
    """
    pop = observed_field(doc, "population", kind=dict)
    if pop is None:
        return {"status": CRITERION_UNMEASURED,
                "reason": ("в отчёте нет раздела `population` — судить о "
                           "проведённости прогона нечем, и это НЕ «сверенных "
                           "дней ноль»")}
    days = observed_number(pop, "common_scored_days")
    pairs = observed_number(pop, "day_pairs")
    missing = [name for name, value in (("common_scored_days", days),
                                        ("day_pairs", pairs)) if value is None]
    if missing:
        return {"status": CRITERION_UNMEASURED,
                "reason": (f"в `population` не читаются числа "
                           f"{', '.join(missing)} — сверенных дней или их "
                           f"знаменателя НЕТ ({_why_unread(doc)})")}
    if days <= 0:
        return {"status": CRITERION_UNMEASURED,
                "reason": (f"ни одного дня, сверенного во ВСЕХ трёх руках "
                           f"(из {pairs:.0f} пар) — прогон НЕ СОСТОЯЛСЯ: «тень "
                           f"сверена с фактом» при нуле сверенных дней верно "
                           f"ПО ПОСТРОЕНИЮ и ответом не является "
                           f"({_why_unread(doc)})"),
                "common_scored_days": days, "day_pairs": pairs}

    comparison = observed_field(doc, "comparison", kind=dict)
    if comparison is None:
        return {"status": CRITERION_UNMEASURED,
                "reason": (f"сверенных дней {days:.0f}, а раздела `comparison` "
                           f"в отчёте НЕТ — сравнения рук не было, и «дней "
                           f"сверено» само по себе сравнением не является "
                           f"({_why_unread(doc)})"),
                "common_scored_days": days, "day_pairs": pairs}
    for column in COST_COLUMNS:
        block = observed_field(comparison, column, kind=dict)
        if block is None:
            return {"status": CRITERION_UNMEASURED,
                    "reason": (f"колонки стоимости «{column}» в сравнении НЕТ: "
                               f"прогон дошёл до вердикта не во всех "
                               f"{len(COST_COLUMNS)} колонках, а вывод, живущий "
                               f"лишь на одной, ADR-243 опроверг на этом же "
                               f"прогоне ({_why_unread(doc)})"),
                    "common_scored_days": days, "day_pairs": pairs}
        if block.get("verdict") == _UNCHECKED:
            return {"status": CRITERION_UNMEASURED,
                    "reason": (f"в колонке «{column}» сравнение НЕ ВЫНЕСЕНО: "
                               f"{block.get('reason') or 'причина не названа'}"),
                    "common_scored_days": days, "day_pairs": pairs}
        rates = observed_field(block, "net_apy_pct", kind=dict)
        if rates is None:
            return {"status": CRITERION_UNMEASURED,
                    "reason": (f"в колонке «{column}» нет раздела `net_apy_pct` — "
                               f"чем сравнивали руки, НЕ ИЗМЕРЕНО"),
                    "common_scored_days": days, "day_pairs": pairs}
        blank = [arm for arm in ARMS if observed_number(rates, arm) is None]
        if blank:
            return {"status": CRITERION_UNMEASURED,
                    "reason": (f"в колонке «{column}» чистая ставка не читается у "
                               f"рук {', '.join(blank)} — сравнения «Current "
                               f"против CIO Shadow» НЕ БЫЛО, что бы ни стояло в "
                               f"графе вердикта"),
                    "common_scored_days": days, "day_pairs": pairs}

    if population_too_thin(days):
        starved = observed_field(pop, "unpriced_per_arm", kind=dict)
        if starved is None:
            where = ("у каких протоколов нет цен вперёд — НЕ ИЗМЕРЕНО: раздела "
                     "`unpriced_per_arm` в отчёте нет")
        else:
            names = sorted({str(name) for arm in ARMS
                            for name in (observed_field(starved, arm, kind=list)
                                         or [])})
            where = ("цен вперёд нет у протоколов: " + ", ".join(names)
                     if names else
                     "протоколов без цен вперёд отчёт не называет ни одного — "
                     "узость популяции сложилась иначе")
        return {"status": CRITERION_NOT_SATISFIED,
                "reason": (f"прогон СОСТОЯЛСЯ, но сам отказался утверждать свой "
                           f"вывод: сверенных во всех трёх руках дней "
                           f"{days:.0f} из {pairs:.0f} пар при объявленном "
                           f"пороге {MIN_COMMON_DAYS_FOR_CLAIM} — «проведены "
                           f"shadow/replay tests» на популяции, с которой сам "
                           f"прогон улучшение НЕ утверждает, ответом не "
                           f"является. {where}"),
                "common_scored_days": days, "day_pairs": pairs}
    return {"status": CRITERION_SATISFIED,
            "reason": (f"прогон проведён и утверждаем: сверенных во всех трёх "
                       f"руках дней {days:.0f} из {pairs:.0f} пар (порог "
                       f"{MIN_COMMON_DAYS_FOR_CLAIM}), сравнение вынесено в "
                       f"обеих колонках стоимости "
                       f"({', '.join(COST_COLUMNS)}), и прогон сам свой вывод "
                       f"не отзывал"),
            "common_scored_days": days, "day_pairs": pairs}


def _report(root: str, now: dt.datetime, *, overall: str, arms: dict,
            findings: list[dict], unchecked: list[str], population: dict,
            comparison: dict, false_reb: dict, missed: dict,
            provenance: dict, write: bool) -> dict:
    doc = {
        "generated_at": now.isoformat(),
        "overall": overall,
        "counts": {
            "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
            "warn": sum(1 for f in findings if f["severity"] == "WARN"),
            "info": sum(1 for f in findings if f["severity"] == "INFO"),
            "unchecked": len(unchecked),
        },
        "population": population,
        "columns": arms,
        "comparison": comparison,
        "false_rebalances": false_reb,
        "missed_opportunities": missed,
        "provenance": provenance,
        "findings": findings,
        "unchecked": unchecked,
        "advisory": ("ADVISORY: прогон НИЧЕГО не двигает — ни `_move_cost_usd`, "
                     "ни гейты, ни целевую функцию тюнера. Любая правка по его "
                     "итогам меняет решение о движении капитала, это money-path "
                     "и решение владельца"),
    }
    # Вердикт критерия §49 живёт в САМОМ артефакте, а не выводится читателем из
    # чисел: иначе у правила появилась бы вторая копия на стороне `card_acceptance`
    # (ADR-220/808). Строка стои́т в `_report`, а не в `run`, потому что ранних
    # выходов у прогона семь — и каждый обязан отдать вердикт, а не молчание.
    doc["criterion"] = criterion_verdict(doc)
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    doc = run(root=args.root, write=not args.no_write)
    c = doc["counts"]
    print(f"cio_shadow_replay: {doc['overall']} (critical={c['critical']} "
          f"warn={c['warn']} info={c['info']} unchecked={c['unchecked']})")
    pop = doc["population"]
    if pop:
        print(f"  популяция: наблюдено {pop.get('days_observed')} дн., общих "
              f"сверенных {pop.get('common_scored_days')} из {pop.get('day_pairs')}")
    for column, block in (doc["comparison"] or {}).items():
        if block.get("verdict") == _UNCHECKED:
            print(f"  [{column}] НЕ ИЗМЕРЕНО — {block.get('reason')}")
            continue
        net = block["net_apy_pct"]
        print(f"  [{column}] чистая APY: current {net[ARM_CURRENT]} % · "
              f"cio_hold {net[ARM_CIO_HOLD]} % · cio_opt {net[ARM_CIO_OPT]} % "
              f"⇒ лучшая рука {block['best_net_arm']}")
    for f in doc["findings"]:
        print(f"  [{f['severity']}] {f['message']}")
    for u in doc["unchecked"]:
        print(f"  [НЕ ИЗМЕРЕНО] {u}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
