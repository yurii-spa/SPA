"""Portfolio optimization objective — §15 приказа владельца «Portfolio CIO».

Предмет — дословный текст ТЗ владельца из якорной карточки
`inbox-task-portfolio-cio-dynamic-capital-alloc`:

    §15 «Optimizer должен приблизительно решать: MAXIMIZE Expected Net
    Portfolio Yield MINUS transaction cost · risk penalty · concentration
    penalty · uncertainty penalty · turnover penalty · liquidity penalty — при
    constraints действующей Risk Policy. Необходим deterministic calculation
    layer. LLM не должен быть источником финансовой математики.»

Заказ G946 п. 1 требует начинать ТЕМ ЖЕ видом замера, что §13/§14: у целевой
функции тюнера спросить ДИФФЕРЕНЦИАЛЬНО, какие из ШЕСТИ штрафов входят в неё
СВОИМ слагаемым, какие заряжены ЧУЖИМ числом, какие выразимы и не заряжены, а о
каких сказать нечем вовсе. Этот модуль и есть тот замер — прямое продолжение
§13 (:mod:`transaction_economics`) и §14 (:mod:`round_trip_economics`).

Отдельной строкой §15 требует, чтобы источником финансовой математики не был
LLM, и это ДРУГОЙ вопрос, задаваемый ОТДЕЛЬНО (ось 3): «формула детерминирована»
и «формулу охраняет сторож» — не одно утверждение, и зелёный ответ на первое
никогда не есть ответ на второе.

ПАРИТЕТ, А НЕ СВОЯ КОПИЯ
========================
Словарь родов (`CHARGE_KINDS`) и имя третьего исхода (`UNMEASURED`) ввезены из
:mod:`transaction_economics`, а не перепечатаны: прибор, носящий свою копию
мерки, отвечает о себе (урок ADR-913 — «сторож сравнивал свои константы САМ С
СОБОЙ», и ADR-937 — «объявление обязано нести СВОЙ контракт»). Расширение
словаря у соседа автоматически расширяет и этот замер.

РОД РЕШАЕТ СРАВНЕНИЕ СЛАГАЕМЫХ, А НЕ ЧТЕНИЕ ДОКСТРИНГА
=======================================================
Целевая функция тюнера (`AllocationTuner._score_allocation`) собрана из ТРЁХ
названных слагаемых, и у каждого своя дверь:

* `_weighted_apy(weights, adapter_data)` — средневзвешенная ставка;
* `_concentration_penalty(weights)` — HHI-подобный штраф;
* `_check_constraints(weights, adapter_data)` — штраф за нарушение потолков.

Поэтому род штрафа §15 решается ДВУМЯ измеренными фактами, а не мнением:

1. **ВЫРАЗИМ ЛИ** драйвер штрафа — есть ли у двери вход, которым о нём можно
   сказать. Перечень полей строки спрашивается у НАСТОЯЩЕГО загрузчика
   (`_load_adapter_data` на сцене-однодневке), а не у списка в этом файле:
   своя копия контракта разъехалась бы с живым молча.
2. **СДВИНУЛСЯ ЛИ** счёт, когда драйвер изменён, и — если сдвинулся — В КАКОМ
   ИЗ ТРЁХ СЛАГАЕМЫХ этот сдвиг лежит.

Отсюда род:

* `no_input_door` — драйвер НЕВЫРАЗИМ: входа у двери нет вовсе;
* `not_charged` — выразим и ИГНОРИРУЕТСЯ: счёт не шевельнулся;
* `charged_merged` — счёт сдвинулся, но сдвиг целиком лежит в слагаемом,
  которое этим штрафом НЕ ЯВЛЯЕТСЯ (заряжено чужим числом);
* `charged_named` — сдвиг лежит в слагаемом, которое и есть этот штраф.

Различие `charged_merged` / `charged_named` не украшение. Штраф, заряженный
чужим числом, меняется вместе с чужим порогом и исчезает там, где чужое
слагаемое молчит: риск, заряженный штрафом за нарушение ПОТОЛКА, внутри потолка
стоит РОВНО НОЛЬ — то есть разница между T1 и T2 бесплатна до самой границы.

ЧЕГО ПРИБОР НЕ ДЕЛАЕТ
=====================
`IS_ADVISORY = True`. Только ЧИТАЕТ и только СПРАШИВАЕТ: целевая функция,
веса, потолки, `TunerConstraints`, RiskPolicy, стоп-кран и живой трек
`data/equity_curve_daily.json` не тронуты ни строкой. Слагаемые зовутся как
ЧИСТЫЕ функции на ОБЪЯВЛЕННОЙ сцене. Капитал не двигается.

Требование §15 «зарядить шесть штрафов» ПРИБОРОМ НЕ ИСПОЛНЯЕТСЯ намеренно:
завести слагаемое — значит вписать в функцию, решающую о движении денег, число,
которого никто не наблюдал (предмет №1 границы ADR-285, и ровно тот дефект
ADR-243 на новом месте). Прибор называет, чего не хватает, и этим кончает
работу.

ЧИСЛА ЗДЕСЬ НЕ НАЗВАНЫ «APY» НАМЕРЕННО
=======================================
Счёт целевой функции измеряется в пунктах ставки, но числом «APY» не является:
это РАЗНОСТЬ счёта кандидата, а не доходность книги. Назвать его `apy_*` значило
бы совершить ровно тот дефект, который перепись §5 (:mod:`apy_name_census`)
ловит — одно имя на разные экономические показатели. Поэтому поля носят имена
`score_*` и `delta_pp`, и перепись родов о них молчит ПО ПРАВУ, а не по недосмотру.

Перемер руками::

    python3 -m spa_core.analytics.objective_penalties
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ENGINE = "objective_penalties_census"

#: Слой советательный: ни одно число отсюда не гейтит исполнение (инв. #9).
IS_ADVISORY = True

# ---------------------------------------------------------------------------
# ПАРИТЕТ со словарём родов §13 (ADR-956). Ввоз, а не копия.
# ---------------------------------------------------------------------------
try:
    from .transaction_economics import CHARGE_KINDS, UNMEASURED
    _KINDS_IMPORT_ERROR: Optional[str] = None
except BaseException as _exc:  # noqa: BLE001 — причина обязана быть названа
    CHARGE_KINDS = ()  # type: ignore[assignment]
    UNMEASURED = "unmeasured"
    _KINDS_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"

# ---------------------------------------------------------------------------
# ОБЪЯВЛЕННАЯ СЦЕНА. Книга и суммы объявлены здесь, а не взяты из живого трека:
# предмет замера — ПОВЕДЕНИЕ ЦЕЛЕВОЙ ФУНКЦИИ, и оно обязано быть воспроизводимым
# на любой машине в любой день (запрет `CLAUDE.md`: живой трек не трогать).
# ---------------------------------------------------------------------------

#: Ставка сцены — ОДНА на все протоколы. Равные ставки выбраны намеренно: любой
#: сдвиг счёта тогда происходит НЕ от доходности, и приписать его штрафу можно
#: без вычитания чужого эффекта.
SCENE_APY_PCT = 5.0

#: TVL сцены — заведомо выше порога политики, чтобы отбор (`_eligible_adapters`)
#: не срезал строки ДО целевой функции: иначе «штраф за ликвидность» мерился бы
#: у отбора, а вопрос §15 — про ЦЕЛЕВУЮ ФУНКЦИЮ.
SCENE_TVL_USD = 500_000_000.0

#: Протоколы сцены. Три — ровно `min_protocols`, поэтому базовая сцена не несёт
#: штрафа за недобор числа протоколов и сдвиги читаются чисто.
SCENE_PROTOCOLS: Tuple[str, ...] = ("aave_v3", "morpho_blue", "fluid_usdc")

#: Вес на протокол в базовой сцене. 0.15 × 3 = 0.45 — ПОД потолком T2 (0.50),
#: поэтому базовая сцена не нарушает ни одного constraint'а, и штраф за
#: нарушение потолков в ней равен нулю. Это и делает сцену пригодной: сдвиг,
#: появившийся от драйвера, не смешан с уже начисленным нарушением.
SCENE_WEIGHT = 0.15

#: Малый вес для сцены концентрации. Он ОБЯЗАН быть выше порога «активного»
#: протокола (`w > 0.01` у `_check_constraints`), иначе перекос сцены срезал бы
#: ЧИСЛО активных протоколов и начислил чужой штраф за недобор `min_protocols` —
#: ровно та ошибка, которой первая редакция этой сцены ответила неверно.
SCENE_SMALL_WEIGHT = 0.05

#: Цепь сцены — одна на все строки: сетевые потолки в базовой сцене молчат.
SCENE_CHAIN = "ethereum"

#: Тир базовой сцены. T1 выбран потому, что у T2 есть СВОЙ потолок (0.20) и
#: суммарный (0.50) — сцена на T2 начислила бы нарушение сама.
SCENE_TIER = "T1"

#: Допуск сравнения двух счётов. Счёт — float, и сравнивать его на равенство
#: нельзя; порог взят на несколько порядков ниже самого мелкого наблюдаемого
#: сдвига сцены (сотые доли пункта).
SCORE_EPS = 1e-9


def _penalty(key: str, owner_words: str, driver_field: Optional[str],
             driver: str, why: str,
             expect_summand: Optional[str] = None) -> Dict[str, Any]:
    """Объявление одного штрафа §15.

    `driver_field` — поле строки адаптера, которым драйвер выражается; `None`
    означает «такого поля в контракте двери нет», и это утверждение ПРОВЕРЯЕТСЯ
    у настоящего загрузчика, а не принимается на слово.

    `expect_summand` — имя слагаемого целевой функции, которое ЯВЛЯЕТСЯ этим
    штрафом (`None` — такого слагаемого у функции нет вовсе). Поле нужно, чтобы
    отличить `charged_named` от `charged_merged`: сдвиг, лёгший в ЧУЖОЕ
    слагаемое, зарядом этого штрафа не является.
    """
    return {"penalty": key, "owner_words": owner_words,
            "driver_field": driver_field, "driver": driver, "why": why,
            "expect_summand": expect_summand}


#: ШЕСТЬ штрафов §15 — дословный перечень владельца, в его порядке.
PENALTIES: Tuple[Dict[str, Any], ...] = (
    _penalty(
        "transaction_cost", "transaction cost",
        None, "current_allocation",
        why="цена хода выразима только относительно ТЕКУЩЕЙ раскладки: «сколько "
            "стоит перейти в кандидата» есть вопрос о ПАРЕ (откуда, куда). У "
            "двери вход только один — сам кандидат, поэтому сказать о цене "
            "нечем. Цена живёт у соседа (`rebalance_economics._move_cost_usd`), "
            "и его вердикт решает ACT/HOLD ПОСЛЕ того, как кандидат уже выбран "
            "как оптимальный: то есть выбор оптимума о цене не знает",
    ),
    _penalty(
        "risk_penalty", "risk penalty",
        "tier", "tier_downgrade",
        why="риск протокола выразим ярлыком тира, и тир до двери ДОХОДИТ — но "
            "своего слагаемого у риска нет ни одного. В ДОПУСТИМОЙ области "
            "(все потолки соблюдены) перевод всей книги из T1 в T2 не меняет "
            "счёт НИ НА СОТУЮ: тир шевелит счёт только тогда, когда потолок "
            "УЖЕ нарушен, и шевелит его ЧУЖИМ числом — штрафом за нарушение. "
            "То есть среди кандидатов, между которыми оптимизатор и выбирает, "
            "риск не стои́т ничего (ось `cap_violation` мерит обе стороны "
            "границы)",
        expect_summand=None,
    ),
    _penalty(
        "concentration_penalty", "concentration penalty",
        None, "concentrate_one_protocol",
        why="концентрация выразима самими ВЕСАМИ (отдельного поля строки ей не "
            "нужно) и у неё есть СВОЁ слагаемое — HHI-подобный "
            "`_concentration_penalty`. Единственный из шести",
        expect_summand="concentration_penalty",
    ),
    _penalty(
        "uncertainty_penalty", "uncertainty penalty",
        "apy_vol_30d_pp", "volatility_spike",
        why="неопределённость ставки выразима её разбросом, и такое число в "
            "системе ЕСТЬ (`adapter_health_scorecard`, секция §10/§11), но в "
            "контракт строки тюнера оно не входит: до целевой функции разброс "
            "не доезжает ни одним полем",
    ),
    _penalty(
        "turnover_penalty", "turnover penalty",
        None, "turnover_spent",
        why="оборот есть свойство ИСТОРИИ ходов, а не кандидата. У двери нет "
            "входа, которым можно сказать «на этой неделе уже оборачивали "
            "столько»; ограничитель оборота живёт у соседа "
            "(`rebalance_economics`, `week_turnover_ok`) и на выбор оптимума "
            "не влияет",
    ),
    _penalty(
        "liquidity_penalty", "liquidity penalty",
        "tvl_usd", "tvl_collapse",
        why="ликвидность выразима и ДОЕЗЖАЕТ до двери полем `tvl_usd` — и "
            "целевая функция его не читает ВОВСЕ. Порог политики срезает пулы "
            "НИЖЕ $5 млн у отбора (бинарно, до счёта), поэтому ВЫШЕ порога "
            "градиента нет никакого: пул на $5,1 млн и пул на $500 млн "
            "получают один и тот же счёт",
        expect_summand=None,
    ),
)

# ---------------------------------------------------------------------------
# Ось 3: инвариант #3 — КАКИЕ каталоги сторож инварианта вообще спрашивает.
# ---------------------------------------------------------------------------

#: Каталоги, названные ИНВАРИАНТОМ #3 дословно («LLM запрещён в risk /
#: execution / monitoring / kill компонентах»), плюс каталог, который §15
#: называет источником финансовой математики. Слово владельца → путь в дереве.
INVARIANT_DIRS: Tuple[Tuple[str, str, str], ...] = (
    ("risk", "spa_core/risk", "инв. #3 дословно"),
    ("execution", "spa_core/execution", "инв. #3 дословно"),
    ("monitoring", "spa_core/monitoring", "инв. #3 дословно"),
    ("kill", "spa_core/governance", "инв. #3 дословно: стоп-кран живёт здесь "
                                    "(`governance/kill_switch.py`)"),
    ("математика §15", "spa_core/tuner", "§15: «необходим deterministic "
                                         "calculation layer. LLM не должен быть "
                                         "источником финансовой математики» — "
                                         "целевая функция живёт здесь"),
)

#: Известный член класса, которым проверяется САМ сторож. Два текста, потому что
#: у сторожа две двери, и зелёный ответ одной ничего не говорит о другой.
_CONTROL_SDK = "import anthropic\n\n\ndef f():\n    return 1\n"
_CONTROL_LAUNCH = (
    "import subprocess\n\n\ndef f():\n"
    "    return subprocess.run(['claude', '-p', 'посчитай'])\n"
)


# ---------------------------------------------------------------------------
# Загрузка живых дверей. Отказ ввоза — ТРЕТИЙ ИСХОД с названной причиной.
# ---------------------------------------------------------------------------

def load_objective_door() -> Tuple[Any, Optional[str]]:
    """(экземпляр тюнера, причина-отказа). Дверь ввозится, а не копируется."""
    try:
        from spa_core.tuner.allocation_tuner import AllocationTuner
    except BaseException as exc:  # noqa: BLE001
        return None, (f"spa_core.tuner.allocation_tuner не ввезён "
                      f"({type(exc).__name__}: {exc}) — целевая функция НЕ ИЗМЕРЕНА")
    try:
        return AllocationTuner(), None
    except BaseException as exc:  # noqa: BLE001
        return None, (f"AllocationTuner() не создан ({type(exc).__name__}: {exc})"
                      " — целевая функция НЕ ИЗМЕРЕНА")


def measure_row_contract() -> Tuple[Optional[Tuple[str, ...]], Optional[str]]:
    """Поля строки адаптера — у НАСТОЯЩЕГО загрузчика, не у списка в этом файле.

    Своя копия контракта разъехалась бы с живой дверью молча, и тогда ответ
    «такого входа нет» означал бы лишь «я о нём не знаю» (ровно класс ADR-913).
    Сцена-однодневка пишется в свой временный каталог: живое `data/` не
    трогается ни чтением, ни записью.
    """
    try:
        from spa_core.tuner.allocation_tuner import _load_adapter_data
    except BaseException as exc:  # noqa: BLE001
        return None, (f"загрузчик строк не ввезён ({type(exc).__name__}: {exc})"
                      " — контракт строки НЕ ИЗМЕРЕН")

    tmp = tempfile.mkdtemp(prefix="spa_objective_contract_")
    try:
        snapshot = {"adapters": [
            {"protocol": pid, "status": "ok", "apy_pct": SCENE_APY_PCT,
             "tvl_usd": SCENE_TVL_USD, "tier": SCENE_TIER}
            for pid in SCENE_PROTOCOLS
        ]}
        (Path(tmp) / "adapter_orchestrator_status.json").write_text(
            json.dumps(snapshot), encoding="utf-8")
        rows = _load_adapter_data(Path(tmp))
    except BaseException as exc:  # noqa: BLE001
        return None, (f"загрузчик отказал на сцене ({type(exc).__name__}: {exc})"
                      " — контракт строки НЕ ИЗМЕРЕН")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not rows:
        return None, ("загрузчик не отдал ни одной строки на объявленной сцене "
                      "— контракт строки НЕ ИЗМЕРЕН (а не «полей нет»)")
    fields: set = set()
    for r in rows:
        if isinstance(r, dict):
            fields.update(str(k) for k in r)
    if not fields:
        return None, "строки загрузчика не несут ни одного поля — НЕ ИЗМЕРЕНО"
    return tuple(sorted(fields)), None


# ---------------------------------------------------------------------------
# Сцена и её возмущения.
# ---------------------------------------------------------------------------

def _scene_rows(tier: str = SCENE_TIER, tvl: float = SCENE_TVL_USD,
                apy: float = SCENE_APY_PCT,
                extra: Optional[Dict[str, Any]] = None) -> List[dict]:
    rows = []
    for pid in SCENE_PROTOCOLS:
        row = {"id": pid, "apy": apy, "tvl_usd": tvl, "tier": tier,
               "chain": SCENE_CHAIN}
        if extra:
            row.update(extra)
        rows.append(row)
    return rows


def _scene_weights() -> Dict[str, float]:
    return {pid: SCENE_WEIGHT for pid in SCENE_PROTOCOLS}


def _summands(tuner: Any, weights: Dict[str, float],
              rows: Sequence[dict]) -> Tuple[Optional[Dict[str, float]], Optional[str]]:
    """Три НАЗВАННЫХ слагаемых целевой функции плюс её итог.

    Слагаемые зовутся по отдельности затем, чтобы сдвиг счёта можно было
    ПРИПИСАТЬ, а не угадать: «счёт поехал» и «поехал вот этот штраф» — разные
    утверждения, и §15 спрашивает второе.
    """
    try:
        rows = [dict(r) for r in rows]
        apy = float(tuner._weighted_apy(weights, rows))
        conc = float(tuner._concentration_penalty(weights))
        valid, const = tuner._check_constraints(weights, rows)
        score = float(tuner._score_allocation(weights, rows))
    except BaseException as exc:  # noqa: BLE001
        return None, f"слагаемое не посчитано ({type(exc).__name__}: {exc})"
    return {"weighted_apy": apy, "concentration_penalty": conc,
            "constraint_penalty": float(const), "valid": 1.0 if valid else 0.0,
            "score": score}, None


def scene_unfit_reason(base: Dict[str, float]) -> Optional[str]:
    """Причина, по которой сцена НЕГОДНА для приписывания, либо `None`.

    Вынесена отдельной дверью по той же причине, что :func:`classify_shift`:
    пока проверка стояла внутри цикла, её ветка была НЕДОСТИЖИМА на боевой
    сцене (сцена годна), и мутант `if False` выживал — то есть отказ
    существовал на бумаге.

    Условий ДВА, и они разные. `valid=False` ловит грубый случай (сумма весов
    больше единицы). Приписывание же ломает ЛЮБОЙ уже начисленный штраф за
    нарушение потолков: сдвиг от драйвера сложился бы с ним, и «кому
    принадлежит разность» стало бы неразрешимо.
    """
    if base.get("valid") != 1.0:
        return ("базовая сцена недопустима (`valid=False`) — сдвиги на ней "
                "приписать было бы нечему (сцена негодна, а не штрафов нет)")
    pen = base.get("constraint_penalty", 0.0)
    if abs(pen) > SCORE_EPS:
        return (f"базовая сцена САМА несёт штраф за нарушение потолков "
                f"({pen:+.9f}) — сдвиг драйвера сложился бы с ним, и приписать "
                "разность было бы нечему (сцена негодна, а не штрафов нет)")
    return None


def classify_shift(own: Optional[str], shifted: Dict[str, float]) -> str:
    """РАЗЛИЧИТЕЛЬ `charged_named` / `charged_merged` — отдельной дверью.

    Вынесен из :func:`probe_penalties` намеренно. Пока условие стояло внутри
    цикла, его СТРОГОСТЬ не проверял никто: у единственного штрафа со своим
    суммандом сдвиг и так лежит ровно в нём, поэтому ослабление условия до
    «у штрафа объявлен сумманд» не меняло ни одного вердикта (мутант выживал
    ДВАЖДЫ — первый раз его не поймал и тест, который ПЕРЕСКАЗЫВАЛ условие
    вместо того, чтобы его ВЫЗВАТЬ; это та же ошибка, что «сторож сравнивает
    свои константы сам с собой»).

    Заряд именем требует ДВУХ фактов: у штрафа объявлен свой сумманд И сдвиг
    лежит РОВНО в нём. Сдвиг, растёкшийся в соседа, зарядом этого штрафа не
    является — его величина принадлежит соседнему порогу и исчезнет вместе с
    ним.
    """
    if own and own in shifted and len(shifted) == 1:
        return "charged_named"
    return "charged_merged"


def _perturb(driver: str) -> Tuple[Optional[Dict[str, float]], Optional[List[dict]], str]:
    """(веса, строки, причина-отказа) для возмущённой сцены драйвера.

    Драйвер, который НЕВЫРАЗИМ у двери, сцены не имеет вовсе — и это не отказ
    замера, а его ОТВЕТ: возвращается причина, по которой сцену построить не из
    чего.
    """
    if driver == "tier_downgrade":
        return _scene_weights(), _scene_rows(tier="T2"), ""
    if driver == "concentrate_one_protocol":
        # Тот же суммарный вес (0.45), та же доходность, то же ЧИСЛО активных
        # протоколов — меняется ТОЛЬКО неравномерность.
        #
        # ⚠️ Первая редакция сцены клала весь вес в ОДИН протокол, и замер
        # ответил `charged_merged` — неверно, и неверно В СТОРОНУ НАХОДКИ.
        # Схлопывание до одного протокола нарушает `min_protocols` (3), поэтому
        # вместе с концентрацией начислялся ЧУЖОЙ штраф за недобор числа
        # протоколов, и сдвиг переставал быть приписываемым. Ошибку нашёл сам
        # прибор (в `shifted_summands` лежало ДВА слагаемых вместо одного) —
        # это и есть причина, по которой ось печатает, КУДА лёг сдвиг, а не
        # только его величину.
        head = SCENE_WEIGHT * len(SCENE_PROTOCOLS) - 2 * SCENE_SMALL_WEIGHT
        weights = {SCENE_PROTOCOLS[0]: head}
        for pid in SCENE_PROTOCOLS[1:]:
            weights[pid] = SCENE_SMALL_WEIGHT
        return weights, _scene_rows(), ""
    if driver == "tvl_collapse":
        # Доллар вместо полумиллиарда: если у ликвидности есть хоть какой-то
        # градиент, он обязан быть виден ЗДЕСЬ.
        return _scene_weights(), _scene_rows(tvl=1.0), ""
    if driver == "volatility_spike":
        return _scene_weights(), _scene_rows(extra={"apy_vol_30d_pp": 99.0}), ""
    if driver == "current_allocation":
        return None, None, ("у двери нет входа «откуда идём»: подпись "
                            "_score_allocation(weights, adapter_data) несёт "
                            "только КАНДИДАТА")
    if driver == "turnover_spent":
        return None, None, ("у двери нет входа «сколько уже обернули»: подпись "
                            "_score_allocation(weights, adapter_data) об "
                            "истории ходов не знает")
    return None, None, f"драйвер {driver!r} не объявлен"


def probe_penalties(tuner: Any) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Род КАЖДОГО из шести штрафов — дифференциально, на живой двери."""
    terms: List[Dict[str, Any]] = []
    unmeasured: List[str] = []

    contract, contract_why = measure_row_contract()
    base, why = _summands(tuner, _scene_weights(), _scene_rows())
    if base is None:
        return [], [f"базовая сцена не посчитана: {why}"]
    # Годность сцены судит ЕДИНСТВЕННАЯ дверь: своя копия условия здесь
    # замаскировала бы порчу её ветки (мутант `if False` выживал дважды).
    unfit = scene_unfit_reason(base)
    if unfit:
        return [], [unfit]

    for spec in PENALTIES:
        rec: Dict[str, Any] = dict(spec)
        rec["score_base"] = round(base["score"], 9)
        field = spec["driver_field"]

        # ── выразимость: спрашивается у НАСТОЯЩЕГО контракта ────────────────
        if field is None:
            # Драйвер не является полем строки вовсе (цена/оборот/концентрация):
            # выразимость решает ПОДПИСЬ двери, и её проверяет `_perturb`.
            expressible: Optional[bool] = None
        elif contract is None:
            rec["charge_kind"] = UNMEASURED
            rec["unmeasured"] = contract_why
            unmeasured.append(f"{spec['penalty']}: {contract_why}")
            terms.append(rec)
            continue
        else:
            expressible = field in contract
            rec["field_in_contract"] = expressible
            rec["row_contract"] = list(contract)
            if not expressible:
                rec["charge_kind"] = "no_input_door"
                rec["evidence"] = (
                    f"поля {field!r} в контракте строки НЕТ "
                    f"(контракт: {', '.join(contract)})")
                terms.append(rec)
                continue

        weights, rows, no_door = _perturb(spec["driver"])
        if weights is None or rows is None:
            rec["charge_kind"] = "no_input_door"
            rec["evidence"] = no_door
            terms.append(rec)
            continue

        moved, why2 = _summands(tuner, weights, rows)
        if moved is None:
            rec["charge_kind"] = UNMEASURED
            rec["unmeasured"] = why2
            unmeasured.append(f"{spec['penalty']}: {why2}")
            terms.append(rec)
            continue

        delta_score = moved["score"] - base["score"]
        rec["score_perturbed"] = round(moved["score"], 9)
        rec["delta_pp"] = round(delta_score, 9)
        # Куда лёг сдвиг. Знаки: штраф ВЫЧИТАЕТСЯ из счёта, поэтому рост штрафа
        # есть падение счёта — сравниваем величины слагаемых напрямую.
        shifted = {name: round(moved[name] - base[name], 9)
                   for name in ("weighted_apy", "concentration_penalty",
                                "constraint_penalty")
                   if abs(moved[name] - base[name]) > SCORE_EPS}
        rec["shifted_summands"] = shifted

        if abs(delta_score) <= SCORE_EPS and not shifted:
            rec["charge_kind"] = "not_charged"
            rec["evidence"] = (
                f"драйвер {spec['driver']!r} выразим (поле {field!r} доезжает до "
                f"двери), и счёт НЕ ШЕВЕЛЬНУЛСЯ: {base['score']:.9f} → "
                f"{moved['score']:.9f}")
            terms.append(rec)
            continue

        own = spec["expect_summand"]
        rec["charge_kind"] = classify_shift(own, shifted)
        if rec["charge_kind"] == "charged_named":
            rec["evidence"] = (
                f"сдвиг лежит РОВНО в слагаемом {own!r} ({shifted[own]:+.9f}) — "
                f"у штрафа СВОЙ сумманд")
        else:
            # Значение рода НЕ переписывается здесь намеренно: оно пришло из
            # единственной двери `classify_shift`. Своя копия «charged_merged»
            # замаскировала бы любую порчу её ветки-отказа.
            rec["evidence"] = (
                f"счёт сдвинулся на {delta_score:+.9f}, но сдвиг лежит в "
                f"слагаемом(ых) {', '.join(sorted(shifted)) or '—'}, которое "
                f"этим штрафом НЕ является"
                + (f" (своего сумманда {own!r} у функции нет)" if own is None
                   else ""))
        terms.append(rec)

    return terms, unmeasured


def probe_boundary_is_free(tuner: Any) -> Dict[str, Any]:
    """Сколько стоит риск ВНУТРИ потолка — отдельный вопрос, и он решающий.

    Штраф, заряженный чужим числом, исчезает там, где чужое слагаемое молчит.
    Базовая сцена держит T2-сумму ПОД потолком, поэтому ответ «ноль» здесь
    означает: до самой границы разница между T1 и T2 бесплатна.
    """
    out: Dict[str, Any] = {}
    inside_t1, why1 = _summands(tuner, _scene_weights(), _scene_rows(tier="T1"))
    inside_t2, why2 = _summands(tuner, _scene_weights(), _scene_rows(tier="T2"))
    if inside_t1 is None or inside_t2 is None:
        out["unmeasured"] = why1 or why2
        return out
    out["t2_total_in_scene"] = round(SCENE_WEIGHT * len(SCENE_PROTOCOLS), 9)
    out["score_t1"] = round(inside_t1["score"], 9)
    out["score_t2"] = round(inside_t2["score"], 9)
    out["delta_pp"] = round(inside_t2["score"] - inside_t1["score"], 9)
    out["risk_inside_the_cap_is_free"] = abs(out["delta_pp"]) <= SCORE_EPS
    return out


def probe_cap_violation(tuner: Any) -> Dict[str, Any]:
    """ВТОРАЯ сторона границы: чем тир шевелит счёт, когда потолок УЖЕ нарушен.

    Ось нужна, чтобы утверждение о риске было полным. Сказать только «внутри
    потолка риск бесплатен» значило бы умолчать, что снаружи он всё-таки
    что-то весит; сказать только «снаружи весит» — выдать штраф за нарушение
    потолка за штраф за риск. Поэтому мерятся ОБЕ стороны, и печатается, в
    каком слагаемом лежит сдвиг.
    """
    out: Dict[str, Any] = {}
    # Вес, при котором T2-сумма (0.90) ПРЕВЫШАЕТ потолок T2 (0.50): тогда и
    # только тогда штраф за нарушение оживает.
    heavy = {pid: 0.30 for pid in SCENE_PROTOCOLS}
    t1, why1 = _summands(tuner, heavy, _scene_rows(tier="T1"))
    t2, why2 = _summands(tuner, heavy, _scene_rows(tier="T2"))
    if t1 is None or t2 is None:
        out["unmeasured"] = why1 or why2
        return out
    out["t2_total_in_scene"] = round(sum(heavy.values()), 9)
    out["score_t1"] = round(t1["score"], 9)
    out["score_t2"] = round(t2["score"], 9)
    out["delta_pp"] = round(t2["score"] - t1["score"], 9)
    shifted = {name: round(t2[name] - t1[name], 9)
               for name in ("weighted_apy", "concentration_penalty",
                            "constraint_penalty")
               if abs(t2[name] - t1[name]) > SCORE_EPS}
    out["shifted_summands"] = shifted
    out["moves_only_the_constraint_number"] = (
        list(shifted) == ["constraint_penalty"])
    return out


def probe_invariant_guard(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Ось 3 (§15, «LLM не должен быть источником финансовой математики»).

    Вопрос ЗАДАЁТСЯ СТОРОЖУ, а не списку в его исходнике: в каждый названный
    каталог подсаживается ИЗВЕСТНЫЙ ЧЛЕН класса (обе двери — импорт SDK и запуск
    бинаря подпроцессом), и сторож спрашивается, видит ли он его. Прочитать
    `SCAN_DIRS_DEFAULT` глазами значило бы поверить списку; положительный
    контроль отвечает о ПОВЕДЕНИИ.

    Сцена пишется в свой временный каталог — ни одно дерево проекта не
    трогается.
    """
    rep: Dict[str, Any] = {}
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    rep["repo_root"] = str(root)

    import importlib.util
    lint_path = root / "scripts" / "lint_llm_forbidden.py"
    if not lint_path.exists():
        rep["unmeasured"] = f"сторожа нет по пути {lint_path} — ось НЕ ИЗМЕРЕНА"
        return rep
    try:
        spec = importlib.util.spec_from_file_location(
            "_spa_lint_llm_forbidden_probe", lint_path)
        if spec is None or spec.loader is None:
            rep["unmeasured"] = f"{lint_path} не загружается как модуль — НЕ ИЗМЕРЕНО"
            return rep
        lint = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lint)
    except BaseException as exc:  # noqa: BLE001
        rep["unmeasured"] = (f"сторож не ввезён ({type(exc).__name__}: {exc})"
                             " — ось НЕ ИЗМЕРЕНА")
        return rep

    asked = tuple(getattr(lint, "SCAN_DIRS_DEFAULT", ()) or ())
    rep["guard_asks_about"] = list(asked)
    door2 = getattr(lint, "find_llm_subprocess_launches", None)
    rep["launch_door_importable"] = door2 is not None

    rows: List[Dict[str, Any]] = []
    blind: List[str] = []
    for word, rel, why in INVARIANT_DIRS:
        rec: Dict[str, Any] = {"owner_word": word, "dir": rel, "why_named": why,
                               "dir_exists": (root / rel).is_dir(),
                               "in_scan_list": rel in asked}
        tmp = tempfile.mkdtemp(prefix="spa_inv3_control_")
        try:
            for d in list(asked) + [rel]:
                os.makedirs(os.path.join(tmp, d), exist_ok=True)
            planted = os.path.join(tmp, rel)
            with open(os.path.join(planted, "planted_sdk.py"), "w",
                      encoding="utf-8") as fh:
                fh.write(_CONTROL_SDK)
            with open(os.path.join(planted, "planted_launch.py"), "w",
                      encoding="utf-8") as fh:
                fh.write(_CONTROL_LAUNCH)
            _, v1 = lint.run_lint(tmp)
            _, v2, un2 = lint.run_launch_lint(tmp)
            rec["sdk_door_sees_control"] = bool(v1)
            rec["launch_door_sees_control"] = bool(v2)
            if un2:
                rec["launch_door_unmeasured"] = un2
        except BaseException as exc:  # noqa: BLE001
            rec["unmeasured"] = f"{type(exc).__name__}: {exc}"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        seen = bool(rec.get("sdk_door_sees_control")) or \
            bool(rec.get("launch_door_sees_control"))
        rec["control_seen"] = seen
        if not seen and "unmeasured" not in rec:
            blind.append(rel)
        rows.append(rec)

    rep["directories"] = rows
    rep["blind_to"] = blind
    return rep


# ---------------------------------------------------------------------------
# Сборка отчёта.
# ---------------------------------------------------------------------------

def measure(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Отчёт переписи §15. `data_dir` принимается для единообразия секций.

    Живое `data/` этим прибором НЕ ЧИТАЕТСЯ: предмет — поведение целевой
    функции на ОБЪЯВЛЕННОЙ сцене, и подмешать туда снимок дня значило бы
    сделать ответ свойством дня, а не функции.
    """
    rep: Dict[str, Any] = {"status": "OK", "engine": ENGINE,
                           "is_advisory": IS_ADVISORY}
    # Вход принят и НЕ ИСПОЛЬЗОВАН — это объявление, а не недосмотр: секции
    # отчёта зовутся с одной подписью, а предмет этого замера есть поведение
    # функции на объявленной сцене. Печатается, чтобы читатель отчёта видел,
    # что снимок дня в ответ не подмешан.
    rep["data_dir_read"] = False
    rep["data_dir_given"] = str(data_dir) if data_dir else None
    unmeasured: List[str] = []

    if _KINDS_IMPORT_ERROR or not CHARGE_KINDS:
        rep["status"] = "SKIPPED"
        rep["verdict"] = "UNMEASURED"
        rep["unmeasured"] = [
            "словарь родов §13 не ввезён "
            f"({_KINDS_IMPORT_ERROR or 'CHARGE_KINDS пуст'}) — мерить род "
            "своей копией значило бы отвечать о себе"]
        rep["reason"] = rep["unmeasured"][0]
        rep["headline"] = "НЕ ИЗМЕРЕНО: мерка не ввезена"
        return rep

    rep["charge_kinds"] = list(CHARGE_KINDS)
    rep["penalties_declared"] = len(PENALTIES)

    tuner, why = load_objective_door()
    if tuner is None:
        rep["status"] = "SKIPPED"
        rep["verdict"] = "UNMEASURED"
        rep["unmeasured"] = [why]
        rep["reason"] = why
        rep["headline"] = "НЕ ИЗМЕРЕНО: целевая функция не ввезена"
        rep["invariant_guard"] = probe_invariant_guard()
        return rep

    terms, term_unmeasured = probe_penalties(tuner)
    unmeasured.extend(term_unmeasured)
    rep["terms"] = terms
    rep["cap_boundary"] = probe_boundary_is_free(tuner)
    rep["cap_violation"] = probe_cap_violation(tuner)
    rep["invariant_guard"] = probe_invariant_guard()

    by_kind: Dict[str, List[str]] = {}
    for t in terms:
        by_kind.setdefault(t.get("charge_kind", UNMEASURED), []).append(t["penalty"])
    rep["counts"] = {k: len(by_kind.get(k, [])) for k in
                     tuple(CHARGE_KINDS) + (UNMEASURED,)}

    findings: List[str] = []
    named_list = by_kind.get("charged_named", [])
    named = len(named_list)
    if named < len(PENALTIES):
        findings.append(
            f"СВОЁ слагаемое есть у {named} из {len(PENALTIES)} штрафов §15: "
            + (", ".join(named_list) if named_list else "ни у одного"))
    if by_kind.get("not_charged"):
        findings.append(
            "выразимо и ИГНОРИРУЕТСЯ (вход доезжает до двери, счёт не "
            "шевелится): " + ", ".join(by_kind["not_charged"]))
    if by_kind.get("charged_merged"):
        findings.append(
            "заряжено ЧУЖИМ числом: " + ", ".join(by_kind["charged_merged"]))
    if by_kind.get("no_input_door"):
        findings.append(
            "сказать НЕЧЕМ (входа у двери нет вовсе): "
            + ", ".join(by_kind["no_input_door"]))

    cap = rep["cap_boundary"]
    viol = rep["cap_violation"]
    if cap.get("risk_inside_the_cap_is_free"):
        msg = ("риск ВНУТРИ потолка бесплатен: при T2-сумме "
               f"{cap.get('t2_total_in_scene')} (под потолком) сдвиг T1→T2 равен "
               f"{cap.get('delta_pp')} — разница тиров стои́т ноль до самой границы")
        if viol.get("moves_only_the_constraint_number"):
            msg += (f"; за границей (T2-сумма {viol.get('t2_total_in_scene')}) "
                    f"сдвиг {viol.get('delta_pp')} лежит ТОЛЬКО в "
                    "`constraint_penalty`, то есть это штраф за нарушение "
                    "потолка, а не за риск")
        findings.append(msg)

    guard = rep["invariant_guard"]
    if guard.get("unmeasured"):
        unmeasured.append(f"ось инв. #3: {guard['unmeasured']}")
    elif guard.get("blind_to"):
        findings.append(
            "сторож инв. #3 СЛЕП к каталогам (известный член класса подсажен и "
            "НЕ УВИДЕН): " + ", ".join(guard["blind_to"]))

    rep["findings"] = findings
    if unmeasured:
        rep["unmeasured"] = unmeasured
    rep["headline"] = (
        f"штрафов §15 {len(PENALTIES)} · своё слагаемое у {named} · "
        f"заряжено чужим числом {rep['counts'].get('charged_merged', 0)} · "
        f"выразимо и игнорируется {rep['counts'].get('not_charged', 0)} · "
        f"сказать нечем {rep['counts'].get('no_input_door', 0)} · "
        f"не измерено {rep['counts'].get(UNMEASURED, 0)}")
    return rep


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Перепись шести штрафов §15 целевой функции тюнера.")
    ap.add_argument("--data-dir", default=None,
                    help="принимается для единообразия; прибор живое data/ не читает")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rep = measure(Path(args.data_dir) if args.data_dir else None)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0 if rep.get("status") == "OK" else 2

    print(f"§15 Portfolio optimization objective — {rep.get('headline')}")
    for t in rep.get("terms", []):
        print(f"  [{t.get('charge_kind')}] {t['penalty']} «{t['owner_words']}»")
        if t.get("evidence"):
            print(f"      {t['evidence']}")
        if t.get("unmeasured"):
            print(f"      НЕ ИЗМЕРЕНО: {t['unmeasured']}")
    cap = rep.get("cap_boundary") or {}
    if cap:
        print(f"  потолок: T1 {cap.get('score_t1')} против T2 {cap.get('score_t2')}"
              f" (сдвиг {cap.get('delta_pp')})")
    guard = rep.get("invariant_guard") or {}
    print(f"  инв. #3: сторож спрашивает {guard.get('guard_asks_about')}")
    for d in guard.get("directories", []):
        mark = "ВИДИТ" if d.get("control_seen") else "СЛЕП"
        print(f"      [{mark}] {d['owner_word']:14s} {d['dir']}")
    for f in rep.get("findings", []):
        print(f"  НАХОДКА: {f}")
    for u in rep.get("unmeasured", []):
        print(f"  НЕ ИЗМЕРЕНО: {u}")
    return 0 if rep.get("status") == "OK" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
