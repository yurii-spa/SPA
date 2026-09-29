"""rebalance_cost_evidence.py — стоимость перекладки ЗАРЯЖАЕТСЯ литералом, а наблюдается живьём.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §49 «Acceptance criteria» → «**Costs.** Gas, fees, slippage
accounted for in decision». Тело ТЗ ставит тот же вопрос словами: решение о
перекладке обязано учитывать «стоимость ребалансировки … и стоимость последующего
выхода», а «DO NOTHING / KEEP является полноценным инвестиционным решением».

Ответ на «учитывается ли» — **ДА, но ровно ОДНИМ гейтом**
========================================================
Стоимость входит в вердикт через ``payback_within_horizon`` и больше нигде::

    cost_usd     = _move_cost_usd(legs, turnover, chains)      # газ + слиппедж + мост
    payback_days = 365 · cost_pp / gain_pp
    payback_ok   = payback_days <= p.max_payback_days

Второй гейт того же слоя — ``gain_above_band`` — сравнивает с полосой **ВАЛОВУЮ**
выгоду (``gain_pp >= required``), из которой стоимость НЕ вычтена. То есть
удорожание перекладки не сужает полосу выгоды; оно способно только удлинить срок
окупаемости. Это утверждение закреплено положительным контролем
(``test_cost_moves_only_the_payback_gate``), а не взято из докстринга: мутация,
делающая ``gain_pp`` функцией стоимости, красит тест.

Ответ на «а верны ли сами числа» — их НИКТО никогда не сверял
============================================================
Все три компоненты стоимости — литералы из ``spa_core/backtesting/tier1/cost_model``:

=================  ==========================================  ============
компонента         откуда берётся                              провенанс
=================  ==========================================  ============
газ                ``GAS_USD_PER_POSITION_CHANGE[chain]``      **литерал**
слиппедж           ``SLIPPAGE_BPS_STABLE`` = 8 bps оборота     **литерал**
мост               ``BRIDGE_BPS`` = 5 bps оборота              **литерал**
=================  ==========================================  ============

И одновременно в этом же дереве **живёт наблюдение газа — в ТОЙ ЖЕ единице**, в
которой решение его тратит. ``spa_core/monitoring/gas_price_agent`` (ADR-183,
агент ``com.spa.gas_price_agent``, такт 1800 с) опрашивает публичные ``eth_gasPrice``
с кворумом, берёт спот ETH/USD и пишет ``usd_per_leg`` — доллары за одну ногу.
Ровно то, что заряжает ``GAS_USD_PER_POSITION_CHANGE``.

**Их не сравнивал ни один сторож.** Это тот же класс, что ADR-053 («TVL-floor
проверяется ТОЛЬКО живым TVL») и ADR-242 («литеральный TVL знаменателем не
является»), и тот же класс, что «измеритель построен, до потребителя не доехал»:
источник есть, потребителя у него нет.

Замер 06.09 — расхождение в 311 раз, и оно БОЛЬШЕ зазора, которым решается гейт
==============================================================================
Живой записанный вердикт (``data/allocation_rationale.json``, 06:00:09Z), книга
$100 000, оборот $47 105:

===============  ==========  ============  ==============
компонента       заряжено    наблюдено     во сколько раз
===============  ==========  ============  ==============
газ (6 ног)      $60.15      $0.19         **×311**
слиппедж 8 bps   $37.68      — (см. ниже)  —
мост 5 bps       $23.55      —             —
**итого**        **$121.39** **$61.43**    ×0.51
===============  ==========  ============  ==============

Поногово: ``ethereum`` заряжается $12.00 при наблюдённых $0.0380 (×316),
``base`` — $0.15 при $0.0038 (×40), ``optimism`` — $0.25 при $0.0006 (×397).

**Почему это не «мелочь в пользу осторожности».** Зазор, которым сегодня решается
гейт, — ``max_payback_days / payback_days`` = 30.00 / 23.11 = **×1.298**: стоимость
может вырасти в 1.3 раза, и вердикт перевернётся. Ошибка же измерена в **×2.0** по
полной стоимости (и ×311 по своей компоненте) — то есть ошибка БОЛЬШЕ зазора,
которым принимается решение. Сегодняшний вердикт от подстановки не меняется
(23.11 → 11.70 дн., гейт проходит и так), но существует **полоса ложного отказа**:
при заряженном сроке окупаемости от **30.00 до 59.28 дней** решение говорит HOLD
на стоимости, которой цепь не берёт. Направление ошибки — в сторону
неподвижности книги, то есть ровно в ту, на которую жалуется §2 ТЗ («почти 40 %
капитала продолжает находиться в Aave V3 под 2.7 %»).

Чего этот модуль НЕ делает
==========================
**Не чинит стоимость.** Подставить наблюдённый газ в ``_move_cost_usd`` — money-path:
это изменит ``payback_days``, то есть гейт, который решает, двигать ли капитал.
Модуль ADVISORY: он **называет** расхождение и его размер, а решение — владельца.
Ни один порог здесь не назначен: все читаются из своих домов (``TriggerParams``,
``cost_model``, ``gas_price_agent``, манифест). Запасных литералов нет намеренно —
порог, не прочитанный из своего дома, это «не измерено», а не число.

Слиппедж: сверка есть, но это МОДЕЛЬ против КОНСТАНТЫ, а не наблюдение
======================================================================
``liquidity_depth_analyzer`` считает ``slippage_bps = k·(amount/TVL)·10⁴``, и TVL
там наблюдён. Но коэффициент ``k`` (0.5/2.0) — такой же литерал, как и сами 8 bps.
Поэтому сверка слиппеджа даёт **допущение**, а не измерение, и severity выше
``WARN`` она не поднимает НИКОГДА: выдать модель за наблюдение значило бы
совершить ровно ту подмену, ради которой написан этот модуль. Замер 06.09:
модель даёт $46.20 против заряженных $37.68 (+22.6 % на своей компоненте, +7.0 %
на полной стоимости) — и почти вся разница приходит из одной ноги (``pendle``,
17.73 bps при TVL $21.4 млн).

Третий исход
============
``UNCHECKED`` — самостоятельный вердикт с названной причиной, и он ВЫШЕ
``CRITICAL``. Наступает, когда сверять нечем: нет записанного вердикта, спот
ETH/USD не ``live``, у сети нет ни одного ``live``-чтения газа, карта сетей
недоступна. Отсутствие наблюдения — не «ноль расхождения» и не пропуск: это
третий исход с причиной (порядок ``.claude/rules/deployment.md``).

Самопроверка разложения
=======================
Разложение стоимости на три компоненты сверяется с ``_move_cost_usd`` — тем самым
кодом, которым цикл её и посчитал. Разошлись ⇒ ``UNCHECKED``: формула стоимости
изменилась, и мы больше не знаем, что именно раскладываем. Второго определения
стоимости в этом файле нет намеренно.

stdlib · детерминирован при инъектированных часах и чтении · atomic_save · LLM
здесь запрещён.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import json
import math
import os
from typing import Any, Callable

from spa_core.utils.observation import observed, observed_number

from spa_core.utils.atomic import atomic_save

# Компоненты стоимости берутся из ТОГО ЖЕ дома, из которого их берёт решение.
# Своей копии чисел здесь нет: разойдись они, отчёт стал бы неотличим от
# прочитавшего настоящую модель, а расхождение росло бы молча.
from spa_core.backtesting.tier1.cost_model import (
    GAS_USD_PER_POSITION_CHANGE,
    SLIPPAGE_BPS_STABLE,
    BRIDGE_BPS,
)
# Формула стоимости — ОДНА, та самая, которой посчитал цикл. Используется как
# самопроверка разложения (см. докстринг), а не пересчитывается заново.
from spa_core.allocator.rebalance_economics import _move_cost_usd, TriggerParams
# Наблюдение газа: единица `usd_per_leg` и её множитель живут у производителя.
from spa_core.monitoring.gas_price_agent import GAS_LIMIT_PER_LEG
# Модель слиппеджа не дублируется — она в дереве уже есть.
from spa_core.paper_trading.liquidity_depth_analyzer import (
    _compute_slippage_bps,
    _get_liquidity_tier,
    _slippage_k,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/rebalance_cost_evidence.json"

#: Артефакт наблюдения газа. Свежесть судится по SLO его ПРОИЗВОДИТЕЛЯ (манифест),
#: а не по числу, выдуманному здесь.
GAS_ARTIFACT_REL = "data/gas_price_history.json"

_LIVE = "live"

#: Записанный вердикт цикла — материал, О КОТОРОМ судит этот прибор. Его свежесть
#: спрашивается на ЗЕЛЁНОМ пути вердикта критерия (см. :func:`_criterion_block`).
VERDICT_ARTIFACT_REL = "data/allocation_rationale.json"


# ── чей мерой объявлен этот прибор ───────────────────────────────────────────

#: Критерий §49 ТЗ «Portfolio CIO», мерой которого объявлен ЭТОТ прибор.
#: Проба `card_acceptance` сверяет объявление ПО ЯКОРЮ («§49 Costs»), а не
#: подстрокой: подстрока «Costs» совпала бы с любой заметкой о стоимости
#: (ADR-333).
CRITERION = ("§49 Costs — «Gas, fees, slippage accounted for in decision» "
             "(+ тело ТЗ: решение обязано учитывать «стоимость ребалансировки "
             "… и стоимость последующего выхода»)")

CRITERION_SATISFIED = "SATISFIED"
CRITERION_NOT_SATISFIED = "NOT_SATISFIED"
CRITERION_UNMEASURED = "UNMEASURED"

#: Ось находки: каким УТВЕРЖДЕНИЕМ она отвечает на вопрос критерия.
#:
#: `found`       — утверждение СУЩЕСТВОВАНИЯ: ошибка стоимости БОЛЬШЕ зазора,
#:                 которым решается гейт. Неполнота материала рядом его не
#:                 отменяет.
#: `compared`    — сравнение состоялось, и ошибка уложилась в зазор решения.
#:                 Вердикта не двигает: порог здесь не подобран, а взят по
#:                 ПРИНЦИПУ — «больше зазора, которым принимается решение», — и
#:                 всё, что внутри зазора, решение не переворачивает. Сам прибор
#:                 разводит эти два случая разной тяжестью (`CRITICAL` против
#:                 `WARN`) именно поэтому.
#: `unobserved`  — сравнение не состоялось: наблюдать было нечем. Третий исход.
#: `assumption`  — сравнивалась МОДЕЛЬ, а не наблюдение. Вердикта критерия не
#:                 двигает ни в какую сторону: поднять допущение до находки
#:                 значило бы выдать модель за измерение — ровно та подмена,
#:                 против которой написан этот модуль (и по которой слиппедж
#:                 никогда не поднимается выше `WARN`).
#: `context`     — факт об устройстве решения, а не наблюдение дня.
AXIS_FOUND = "found"
AXIS_COMPARED = "compared"
AXIS_UNOBSERVED = "unobserved"
AXIS_ASSUMPTION = "assumption"
AXIS_CONTEXT = "context"

#: Вид находки → ось. Перечень ЗАКРЫТ: вид, которого здесь нет, обрывает вердикт
#: критерия третьим исходом с названным именем вида. Классифицировать новый вид
#: молча значило бы решить за автора, существование это или его отсутствие.
#:
#: Таблица живёт У ПРИБОРА, а не у пробы: виды порождает он, и вторая копия
#: таблицы рядом с пробой разъехалась бы с ними молча.
FINDING_AXIS = {
    "cost_error_exceeds_the_deciding_margin": AXIS_FOUND,
    "cost_error_within_the_deciding_margin": AXIS_COMPARED,
    "observed_gas_flips_the_gate": AXIS_FOUND,
    "observed_gas_is_stale": AXIS_UNOBSERVED,
    "tvl_snapshot_unavailable": AXIS_UNOBSERVED,
    "modelled_slippage_above_the_flat_charge": AXIS_ASSUMPTION,
    "cost_enters_only_the_payback_gate": AXIS_CONTEXT,
    "all_three_cost_components_are_literals": AXIS_CONTEXT,
}


def _num(v: object) -> float | None:
    """Число или None. bool числом НЕ считается."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _parse_ts(value: object) -> dt.datetime | None:
    """ISO-отметка в aware-datetime; мусор ⇒ None (а не сегодняшняя дата)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def declared_slo_hours(root: str, read: Callable[[str], Any],
                       rel: str) -> tuple[float | None, str]:
    """SLO свежести артефакта — из ДОМА, где конституция его объявила.

    Порог свежести этот модуль себе не назначает: у артефакта есть паспорт, и
    судить его собственный производитель уже обязался. Дома нет ⇒ ``None``, и
    свежесть тогда НЕ судится вовсе (возраст всё равно печатается) — выдумать
    здесь «24 часа» значило бы завести второй, никем не принятый порог.

    **Домов у манифеста ДВА, и спрашивать надо оба (находка цикла #730).**
    Прежняя редакция искала объявление только среди верхнеуровневых
    ``artifacts[]`` и на ненайденное честно отвечала «в манифесте нет записи».
    Ответ был верен по букве и ложен по существу: этот манифест объявляет сроки
    годности ТАКЖЕ в паспорте производителя (``agents[].produces[]``), и у
    ``data/gas_price_history.json`` объявление живёт ИМЕННО там — **1,5 ч**.
    Поэтому свежесть наблюдения газа не судилась НИ РАЗУ за всё время жизни
    прибора: замер 29.09 на живом дереве — чтение по ``ethereum`` возрастом
    **29,66 ч** при объявленных 1,5 ч, и находка ``observed_gas_is_stale`` не
    рождалась никогда. Сторожа это не ловили потому, что фикстура клала SLO в
    ТОТ дом, куда смотрел код, — тест отвечал на свой вопрос, а не на нужный.

    **Расхождение двух домов — ТРЕТИЙ ИСХОД, а не выбор одного.** Два разных
    числа под одним артефактом означают, что срок годности не объявлен, а
    оспорен; взять любое из них значило бы решить спор конституции молча.
    """
    path = os.path.join(root, "architecture", "manifest.json")
    homes: list[tuple[str, float]] = []
    def _entries(doc: dict, key: str) -> list:
        """Список под ключом. Ключа НЕТ — дома нет вовсе, и это не поломка.

        А вот ключ НЕ ТОГО ТИПА — поломка конституции, и она обязана дойти до
        читателя третьим исходом, а не превратиться в пустой перебор: «этот дом
        пуст» и «этот дом не разобран» чинятся разным (инвариант #17).
        """
        rows = doc.get(key)
        if rows is None:
            return []
        if not isinstance(rows, list):
            raise TypeError(f"`{key}` в манифесте не список, а "
                            f"{type(rows).__name__}")
        return rows

    try:
        manifest = read(path)
        for art in _entries(manifest, "artifacts"):
            if isinstance(art, dict) and art.get("path") == rel:
                slo = _num(art.get("slo_hours"))
                if slo is not None:
                    homes.append((f"artifacts[{rel}].slo_hours", slo))
        for agent in _entries(manifest, "agents"):
            if not isinstance(agent, dict):
                continue
            for made in _entries(agent, "produces"):
                if isinstance(made, dict) and made.get("artifact") == rel:
                    slo = _num(made.get("slo_hours"))
                    if slo is not None:
                        # Имя агента — `label`: так его зовут launchd и сам
                        # манифест. Провенанс без имени производителя не
                        # провенанс, а указание «где-то в агентах»; отсутствие
                        # имени НАЗЫВАЕТСЯ, а не подменяется пустой строкой.
                        who = agent.get("label")
                        who = who if isinstance(who, str) and who.strip() \
                            else "агент без `label`"
                        homes.append(
                            (f"agents[{who}].produces[{rel}].slo_hours", slo))
    except Exception as exc:  # noqa: BLE001 — отсутствие дома = третий исход
        return None, f"манифест не прочитан ({path}): {exc}"

    if not homes:
        return None, (f"в манифесте нет записи о сроке годности {rel} — ни в "
                      f"artifacts[], ни в agents[].produces[]")
    values = {v for _, v in homes}
    if len(values) > 1:
        named = "; ".join(f"{where}={v}" for where, v in homes)
        return None, (f"срок годности {rel} объявлен РАЗНЫМ в {len(homes)} местах "
                      f"({named}) — он не объявлен, а оспорен, и выбрать одно "
                      f"число молча значило бы решить спор конституции за неё")
    slo = homes[0][1]
    return slo, "манифест: " + "; ".join(f"{where}={v}" for where, v in homes)


def gas_slo_hours(root: str, read: Callable[[str], Any]) -> tuple[float | None, str]:
    """SLO свежести наблюдения газа. Тонкая обёртка над :func:`declared_slo_hours`.

    Имя оставлено: на него ссылаются сторожа и провенанс в отчёте. Второй копии
    разбора манифеста здесь НЕТ намеренно — одно правило, одно место.
    """
    return declared_slo_hours(root, read, GAS_ARTIFACT_REL)


def observed_gas_usd_per_leg(gas_doc: dict, *, now: dt.datetime) -> dict:
    """Наблюдённый газ по сетям в ДОЛЛАРАХ ЗА НОГУ — единице, которую тратит решение.

    Множитель ``gwei · 1e-9 · GAS_LIMIT_PER_LEG · eth_usd`` — тот же, которым его
    считает сам производитель (``gas_price_agent.build_snapshot``); своей копии
    формулы здесь нет.

    Берётся ПОСЛЕДНЕЕ чтение с ``source == "live"``, а не последняя строка истории:
    у ``gas_price_agent`` отказ источников даёт честный ``unchecked``, и считать
    его чтением значило бы вернуть ровно тот fallback-литерал, которого агент
    избегает (ADR-183 §1). Спот ETH/USD не ``live`` ⇒ не измерено НИЧЕГО: без него
    gwei в доллары не переводится.
    """
    raw_eth = gas_doc.get("eth_usd")
    eth: dict = raw_eth if isinstance(raw_eth, dict) else {}
    eth_usd = _num(eth.get("usd"))
    if eth.get("source") != _LIVE or eth_usd is None or eth_usd <= 0:
        return {"measured": False,
                "reason": f"спот ETH/USD не live (source={eth.get('source')!r}) — "
                          f"gwei в доллары не переводится",
                "eth_usd": eth_usd, "chains": {}}

    out: dict[str, dict] = {}
    for chain, rows in (observed(gas_doc, "history", kind=dict) or {}).items():
        if not isinstance(rows, list):
            continue
        live = [r for r in rows
                if isinstance(r, dict) and r.get("source") == _LIVE
                and _num(r.get("gwei")) is not None]
        if not live:
            out[str(chain)] = {"measured": False,
                               "reason": "ни одного live-чтения в истории"}
            continue
        last = live[-1]
        gwei = _num(last.get("gwei"))
        if gwei is None:                      # отфильтровано выше; страховка типа
            continue
        ts = _parse_ts(last.get("ts"))
        out[str(chain)] = {
            "measured": True,
            "gwei": gwei,
            "usd_per_leg": gwei * 1e-9 * GAS_LIMIT_PER_LEG * eth_usd,
            "observed_at": last.get("ts"),
            "age_hours": (round((now - ts).total_seconds() / 3600.0, 2)
                          if ts is not None else None),
            "sources_ok": last.get("sources_ok"),
        }
    return {"measured": True, "reason": None, "eth_usd": eth_usd,
            "gas_limit_per_leg": GAS_LIMIT_PER_LEG, "chains": out}


def charged_components(legs: list[dict], turnover_usd: float,
                       chains: dict[str, str]) -> dict:
    """Разложение ЗАРЯЖЕННОЙ стоимости на газ / слиппедж / мост.

    Сумма компонент сверяется с :func:`_move_cost_usd` — тем самым кодом, которым
    её посчитал цикл. Расхождение означает, что формула стоимости изменилась, а
    это разложение говорит уже не о ней (см. ``consistent``).
    """
    gas_by_leg: list[dict] = []
    gas = 0.0
    touched: set[str] = set()
    for leg in legs:
        proto = str(leg.get("protocol"))
        declared = chains.get(proto)
        chain = str(declared or "blended").lower()
        unit = float(GAS_USD_PER_POSITION_CHANGE.get(
            chain, GAS_USD_PER_POSITION_CHANGE.get("blended", 0.0)))
        gas += unit
        touched.add(chain)
        gas_by_leg.append({
            "protocol": proto,
            "chain": chain,
            "chain_provenance": "registry" if declared else "default:blended",
            "delta_usd": _num(leg.get("delta_usd")),
            "charged_usd": unit,
        })
    slippage = turnover_usd * (SLIPPAGE_BPS_STABLE / 10_000.0)
    bridge = (turnover_usd * (BRIDGE_BPS / 10_000.0)) if len(touched) > 1 else 0.0
    total = gas + slippage + bridge
    canonical = _move_cost_usd(legs, turnover_usd, chains)
    return {
        "gas_usd": gas,
        "slippage_usd": slippage,
        "bridge_usd": bridge,
        "total_usd": total,
        "canonical_total_usd": canonical,
        "consistent": abs(total - canonical) <= 1e-6,
        "chains_touched": sorted(touched),
        "gas_by_leg": gas_by_leg,
        "slippage_bps_charged": SLIPPAGE_BPS_STABLE,
        "bridge_bps_charged": BRIDGE_BPS,
    }


def modelled_slippage_usd(legs: list[dict], tvl: dict[str, float | None],
                          tvl_source: dict[str, str | None]) -> dict:
    """Слиппедж по модели дерева над НАБЛЮДЁННЫМ TVL.

    Это **допущение**, а не измерение: наблюдён здесь только TVL, а коэффициент
    ``k`` — такой же литерал, как и сверяемые 8 bps. Ключ с не-``live`` TVL не
    моделируется вовсе (порядок ADR-053: литеральный TVL знаменателем не является).
    """
    per_leg: list[dict] = []
    total = 0.0
    unmeasured_usd = 0.0
    for leg in legs:
        proto = str(leg.get("protocol"))
        delta = observed_number(leg, "delta_usd")
        if delta is None:
            # Нога без суммы перестановки: ноль сделал бы её бесплатной и увёл
            # бы из «не измерено» в «измерено и ничего не стоит».
            unmeasured_usd += 0.0
            per_leg.append({"protocol": proto, "usd": None,
                            "unmeasured": "нет delta_usd"})
            continue
        amount = abs(float(delta))
        pool_tvl = _num(tvl.get(proto))
        src = tvl_source.get(proto)
        if src != _LIVE or pool_tvl is None or pool_tvl <= 0:
            unmeasured_usd += amount
            per_leg.append({"protocol": proto, "amount_usd": amount, "measured": False,
                            "tvl_source": src,
                            "reason": "TVL не наблюдён (live) — знаменателя нет"})
            continue
        # `live_data` этой функцией не используется (тир берётся из её карты
        # PROTOCOL_LIQUIDITY_TIER) — передаём пустую, чтобы не заводить второй
        # источник тира рядом с её собственным.
        k = _slippage_k(_get_liquidity_tier(proto, {}))
        bps = _compute_slippage_bps(amount, pool_tvl, k)
        usd = amount * bps / 10_000.0
        total += usd
        per_leg.append({"protocol": proto, "amount_usd": amount, "measured": True,
                        "tvl_usd": pool_tvl, "tvl_source": src, "k": k,
                        "slippage_bps": round(bps, 4), "slippage_usd": round(usd, 4)})
    return {"total_usd": total, "unmeasured_usd": unmeasured_usd, "per_leg": per_leg,
            "provenance": "assumption:model_over_observed_tvl"}


def _criterion_block(findings: list[dict], unchecked: list[str],
                     substitution: dict | None, *,
                     verdict_freshness: dict) -> dict:
    """Вердикт КРИТЕРИЯ §49 `Costs` — и почему он НЕ есть поле ``overall``.

    ``overall`` — лестница ТЯЖЕСТИ для здоровья артефакта, и третий исход стои́т
    в ней ВЫШЕ ``CRITICAL`` намеренно (``test_unchecked_outranks_critical``):
    иначе «не измерено» тонет в находках. Для ЗДОРОВЬЯ это верно.

    Для вердикта критерия тот же порядок был бы ложью в другую сторону.
    Доказательство здесь ОДНОСТОРОННЕЕ: находка расхождения есть утверждение
    СУЩЕСТВОВАНИЯ («заряжено ×N от наблюдённого при зазоре гейта ×M»), и то, что
    рядом чего-то не прочитали, её не отменяет; а «расхождений нет» есть
    утверждение обо ВСЁМ и рушится от любой неполноты. Перенести ``overall`` в
    вердикт критерия значило бы спрятать измеренное красное за «не измерено» —
    инвариант #17 наизнанку (урок цикла #729, ADR-512).

    Поэтому читаются НАХОДКИ ПО ОСИ (:data:`FINDING_AXIS`), а не одно сводное
    слово, и порядок разрешения такой:

    1. вид находки не объявлен осью ⇒ третий исход с именем вида;
    2. есть находка оси ``found`` ⇒ ``NOT_SATISFIED`` — независимо от неполноты;
    3. иначе есть ``unchecked`` или находка оси ``unobserved`` ⇒ третий исход;
    4. иначе ЗЕЛЁНЫЙ путь, и только на нём спрашивается законность: свеж ли
       ЗАПИСАННЫЙ ВЕРДИКТ, о котором всё это сказано. «Расхождений нет» про
       вердикт трёхнедельной давности — тишина мёртвого дерева, а не ответ.

    Зазор назван вслух полем ``unjudged``: прибор умеет измерить отношение
    заряженного газа к наблюдённому и на тихом дне (перекладка не предложена ⇒
    ``payback_days`` нет ⇒ зазора гейта нет ⇒ находка не рождается). Порога «во
    сколько раз уже много» БЕЗ зазора гейта владелец не объявлял, и назначить
    его здесь значило бы завести порог вне его дома — поэтому число печатается,
    а вердикта из него не выходит.
    """
    found: list[str] = []
    unobserved: list[str] = []
    assumption: list[str] = []
    compared: list[str] = []
    for f in findings:
        kind = str(f.get("kind"))
        axis = FINDING_AXIS.get(kind)
        if axis is None:
            return {"criterion": CRITERION, "status": CRITERION_UNMEASURED,
                    "reason": (f"у находки {kind!r} не объявлена ось "
                               f"(`FINDING_AXIS`) — отнести её к существованию "
                               f"или к его отсутствию молча нельзя"),
                    "found": [], "unobserved": [], "assumption": [],
                    "compared": [], "unjudged": None}
        if axis == AXIS_FOUND:
            found.append(kind)
        elif axis == AXIS_UNOBSERVED:
            unobserved.append(kind)
        elif axis == AXIS_ASSUMPTION:
            assumption.append(kind)
        elif axis == AXIS_COMPARED:
            compared.append(kind)

    unjudged = None
    if isinstance(substitution, dict):
        ratio = substitution.get("gas_ratio_charged_over_observed")
        if ratio is not None and substitution.get("gate_flip_margin") is None:
            unjudged = {
                "gas_ratio_charged_over_observed": ratio,
                "reason": ("зазор гейта не определён (перекладка не предложена "
                           "либо `payback_days` не записан) — сравнивать ошибку "
                           "не с чем; порога «во сколько раз уже много» вне "
                           "зазора гейта владелец не объявлял"),
            }

    base = {"criterion": CRITERION, "found": sorted(set(found)),
            "unobserved": sorted(set(unobserved)),
            "assumption": sorted(set(assumption)),
            "compared": sorted(set(compared)), "unjudged": unjudged}

    if found:
        return dict(base, status=CRITERION_NOT_SATISFIED,
                    reason=("стоимость, которой решение пользуется, разошлась с "
                            "наблюдённой: " + ", ".join(sorted(set(found)))
                            + " — находка существования, и неполнота материала "
                              "рядом её не отменяет"))
    if unchecked or unobserved:
        why = list(unchecked) + [f"находка {k}" for k in sorted(set(unobserved))]
        return dict(base, status=CRITERION_UNMEASURED,
                    reason=("сравнить заряженную стоимость с наблюдённой было "
                            "нечем: " + "; ".join(why)))

    slo = verdict_freshness.get("slo_hours")
    age = verdict_freshness.get("age_hours")
    if slo is None:
        return dict(base, status=CRITERION_UNMEASURED,
                    reason=(f"дом срока годности записанного вердикта не назван "
                            f"({verdict_freshness.get('slo_provenance')}) — "
                            f"«расхождений нет» отсюда было бы сказано о вердикте "
                            f"любого возраста"))
    if age is None:
        return dict(base, status=CRITERION_UNMEASURED,
                    reason=(f"возраст записанного вердикта НЕ ИЗМЕРЕН (отметка "
                            f"{verdict_freshness.get('stamp')!r} не разобрана) — "
                            f"отличить живое дерево от замороженного канона "
                            f"`data/` нечем"))
    if age > slo:
        return dict(base, status=CRITERION_UNMEASURED,
                    reason=(f"записанный вердикт протух: снят "
                            f"{verdict_freshness.get('stamp')} — {age} ч назад при "
                            f"объявленном пределе {slo} ч; «расхождений нет» — "
                            f"тишина мёртвого дерева, а не ответ о системе"))
    return dict(base, status=CRITERION_SATISFIED,
                reason=(f"стоимость входит в записанный вердикт, и заряженное "
                        f"сошлось с наблюдённым: находок расхождения 0, "
                        f"непрочитанного 0, вердикт снят {age} ч назад при "
                        f"пределе {slo} ч"))


def run(
    root: str = REPO_ROOT,
    *,
    write: bool = True,
    data_dir: str | None = None,
    now: dt.datetime | None = None,
    reader: Callable[[str], Any] | None = None,
) -> dict:
    """Замер на ЗАПИСАННОМ вердикте. Часы и чтение — ВХОДЫ, чтобы тест был бессмертен."""
    now = now or dt.datetime.now(dt.timezone.utc)
    read = reader or _read_json
    ddir = data_dir or os.path.join(root, "data")

    findings: list[dict] = []
    unchecked: list[str] = []

    # ── вердикт, который цикл РЕАЛЬНО записал ────────────────────────────────
    rat_path = os.path.join(ddir, "allocation_rationale.json")
    verdict: dict | None = None
    verdict_at: str | None = None
    capital_usd: float | None = None
    try:
        doc = read(rat_path)
        shadow = doc.get("decision_shadow")
        if not isinstance(shadow, dict):
            raise ValueError("в отчёте нет `decision_shadow`")
        verdict = shadow
        verdict_at = doc.get("generated_at")
        capital_usd = _num(doc.get("capital_usd"))
    except Exception as exc:  # noqa: BLE001
        unchecked.append(f"записанный вердикт не прочитан ({rat_path}): {exc}")

    # ── карта сетей: ТОТ ЖЕ источник, что у настоящего вызывающего ───────────
    # `allocation_rationale` строит её из adapter_registry.json. Взять другой
    # источник значило бы мерить не ту стоимость, которую заряжали.
    chains: dict[str, str] = {}
    reg_path = os.path.join(ddir, "adapter_registry.json")
    try:
        reg = read(reg_path)
        for name, entry in (reg.get("adapters") or {}).items():
            if isinstance(entry, dict) and entry.get("chain"):
                chains[str(name)] = str(entry["chain"]).strip().lower()
    except Exception as exc:  # noqa: BLE001
        unchecked.append(f"карта сетей не прочитана ({reg_path}): {exc}")

    # ── наблюдённый TVL (для сверки слиппеджа) ───────────────────────────────
    tvl: dict[str, float | None] = {}
    tvl_source: dict[str, str | None] = {}
    orch_path = os.path.join(ddir, "adapter_orchestrator_status.json")
    try:
        orch = read(orch_path)
        for a in orch.get("adapters") or []:
            if isinstance(a, dict) and a.get("protocol"):
                tvl[str(a["protocol"])] = _num(a.get("tvl_usd"))
                tvl_source[str(a["protocol"])] = a.get("tvl_source")
    except Exception as exc:  # noqa: BLE001 — сверка слиппеджа выродится, вердикт нет
        findings.append({"severity": "WARN", "kind": "tvl_snapshot_unavailable",
                         "message": f"снимок оркестратора не прочитан ({orch_path}): "
                                    f"{exc} — сверка слиппеджа не делается"})

    # ── наблюдённый газ ──────────────────────────────────────────────────────
    gas_path = os.path.join(ddir, "gas_price_history.json")
    observed = {"measured": False, "reason": None, "chains": {}}
    try:
        observed = observed_gas_usd_per_leg(read(gas_path), now=now)
        if not observed["measured"]:
            unchecked.append(f"наблюдение газа непригодно: {observed['reason']}")
    except Exception as exc:  # noqa: BLE001
        unchecked.append(f"наблюдение газа не прочитано ({gas_path}): {exc}")

    slo_hours, slo_provenance = gas_slo_hours(root, read)

    # Свежесть ЗАПИСАННОГО ВЕРДИКТА — материала, о котором судит этот прибор.
    # Спрашивается только на зелёном пути вердикта критерия; здесь она МЕРИТСЯ,
    # а решение о ней принимает `_criterion_block`.
    verdict_slo, verdict_slo_prov = declared_slo_hours(root, read,
                                                       VERDICT_ARTIFACT_REL)
    verdict_ts = _parse_ts(verdict_at)
    verdict_freshness = {
        "stamp": verdict_at,
        "age_hours": (round((now - verdict_ts).total_seconds() / 3600.0, 2)
                      if verdict_ts is not None else None),
        "slo_hours": verdict_slo,
        "slo_provenance": verdict_slo_prov,
    }

    # ── пороги решения: из СВОЕГО дома, запасных литералов нет ───────────────
    max_payback_days: float | None = None
    params_provenance = ""
    try:
        p = TriggerParams.for_mode()
        max_payback_days = float(p.max_payback_days)
        params_provenance = (f"TriggerParams.for_mode() → mode={p.mode} "
                             f"max_payback_days={max_payback_days}")
    except Exception as exc:  # noqa: BLE001
        unchecked.append(f"пороги демпфера не прочитаны из своего дома: {exc}")

    charged: dict | None = None
    substitution: dict | None = None
    slippage_check: dict | None = None

    if verdict is not None:
        legs = [l for l in (verdict.get("legs") or []) if isinstance(l, dict)]
        # `None` — оборот НЕ записан; ноль означал бы «день ничего не двигал».
        turnover = observed_number(verdict, "turnover_usd")
        payback_days = _num(verdict.get("payback_days"))
        raw_gates = verdict.get("gates")
        gates: dict = raw_gates if isinstance(raw_gates, dict) else {}

        if not legs:
            unchecked.append("в записанном вердикте нет ног — раскладывать нечего "
                             "(цикл не предлагал перекладки)")
        elif turnover is None:
            # Слиппедж и мост считаются ОТ оборота: ноль вместо ненаписанного
            # объявил бы их нулевыми, то есть перекладку дешевле, чем она есть.
            unchecked.append("в записанном вердикте нет `turnover_usd` — "
                             "слиппедж и мост посчитать не от чего")
        else:
            charged = charged_components(legs, turnover, chains)
            if not charged["consistent"]:
                unchecked.append(
                    f"разложение стоимости разошлось с `_move_cost_usd` "
                    f"(${charged['total_usd']:.6f} против "
                    f"${charged['canonical_total_usd']:.6f}) — формула изменилась, "
                    f"и это разложение говорит уже не о ней")

            # Подстановка наблюдённого газа в ЗАРЯЖЕННУЮ стоимость.
            if observed.get("measured") and charged["consistent"]:
                obs_gas = 0.0
                covered = 0.0
                missing: list[str] = []
                stale: list[str] = []
                for row in charged["gas_by_leg"]:
                    ch = observed["chains"].get(row["chain"]) or {}
                    if not ch.get("measured"):
                        missing.append(f"{row['protocol']} ({row['chain']}): "
                                       f"{ch.get('reason') or 'сети нет в наблюдении'}")
                        continue
                    obs_gas += float(ch["usd_per_leg"])
                    covered += float(row["charged_usd"])
                    age = ch.get("age_hours")
                    if slo_hours is not None and age is not None and age > slo_hours:
                        stale.append(f"{row['chain']}: чтение {age} ч назад при SLO "
                                     f"{slo_hours} ч")
                if missing:
                    unchecked.extend(missing)
                if stale:
                    findings.append({
                        "severity": "WARN", "kind": "observed_gas_is_stale",
                        "message": ("наблюдение газа старше SLO своего производителя: "
                                    + "; ".join(sorted(set(stale)))),
                    })

                if not missing and covered > 0:
                    total_obs = (charged["total_usd"] - charged["gas_usd"] + obs_gas)
                    ratio = total_obs / charged["total_usd"] if charged["total_usd"] else None
                    payback_obs = (payback_days * ratio
                                   if payback_days is not None and ratio is not None
                                   else None)
                    gate_now = bool(gates.get("payback_within_horizon"))
                    gate_after = (payback_obs <= max_payback_days
                                  if (payback_obs is not None
                                      and max_payback_days is not None) else None)
                    # Зазор гейта: во сколько раз стоимость может вырасти до переворота.
                    margin = (max_payback_days / payback_days
                              if (payback_days and payback_days > 0
                                  and max_payback_days is not None) else None)
                    # Полоса, в которой заряженная стоимость отказывает, а
                    # наблюдённая — разрешает (существует, пока ratio < 1).
                    band = None
                    if (max_payback_days is not None and ratio is not None
                            and 0 < ratio < 1):
                        band = [round(max_payback_days, 2),
                                round(max_payback_days / ratio, 2)]
                    substitution = {
                        "gas_usd_charged": round(charged["gas_usd"], 4),
                        "gas_usd_observed": round(obs_gas, 6),
                        "gas_ratio_charged_over_observed": (
                            round(charged["gas_usd"] / obs_gas, 1) if obs_gas > 0 else None),
                        "total_usd_charged": round(charged["total_usd"], 2),
                        "total_usd_on_observed_gas": round(total_obs, 2),
                        "cost_ratio_observed_over_charged": (
                            round(ratio, 4) if ratio is not None else None),
                        "payback_days_charged": payback_days,
                        "payback_days_on_observed_gas": (
                            round(payback_obs, 2) if payback_obs is not None else None),
                        "max_payback_days": max_payback_days,
                        "gate_flip_margin": round(margin, 4) if margin else None,
                        "payback_gate_now": gate_now,
                        "payback_gate_on_observed_gas": gate_after,
                        "verdict_would_flip": (gate_after is not None
                                               and gate_after != gate_now),
                        "false_refusal_band_days": band,
                    }

                    # Находка — по ПРИНЦИПУ, а не по подобранному порогу: ошибка
                    # стоимости больше зазора, которым решается гейт.
                    if ratio is not None and margin is not None and ratio > 0:
                        error_mag = abs(math.log(ratio))
                        margin_mag = abs(math.log(margin))
                        if error_mag > margin_mag:
                            findings.append({
                                "severity": "CRITICAL",
                                "kind": "cost_error_exceeds_the_deciding_margin",
                                "message": (
                                    f"заряженный газ ${charged['gas_usd']:,.2f} против "
                                    f"наблюдённого ${obs_gas:.4f} "
                                    f"(×{charged['gas_usd'] / obs_gas:,.0f} при obs>0); "
                                    f"полная стоимость ×"
                                    f"{ratio:.4f}, тогда как зазор гейта "
                                    f"payback_within_horizon — всего ×{margin:.4f}. "
                                    f"Ошибка стоимости БОЛЬШЕ зазора, которым "
                                    f"принимается решение"
                                    + (f"; полоса ложного отказа: заряженный payback "
                                       f"от {band[0]} до {band[1]} дн." if band else "")
                                ),
                            })
                        else:
                            findings.append({
                                "severity": "WARN",
                                "kind": "cost_error_within_the_deciding_margin",
                                "message": (
                                    f"стоимость на наблюдённом газе ×{ratio:.4f} при "
                                    f"зазоре гейта ×{margin:.4f} — расхождение есть, "
                                    f"но сегодня оно меньше зазора"),
                            })
                    if substitution["verdict_would_flip"]:
                        findings.append({
                            "severity": "CRITICAL",
                            "kind": "observed_gas_flips_the_gate",
                            "message": (
                                f"подстановка наблюдённого газа ПЕРЕВОРАЧИВАЕТ гейт "
                                f"payback_within_horizon: {gate_now} → {gate_after} "
                                f"({payback_days} → "
                                f"{substitution['payback_days_on_observed_gas']} дн. "
                                f"при горизонте {max_payback_days})"),
                        })

            if tvl:
                slippage_check = modelled_slippage_usd(legs, tvl, tvl_source)
                charged_slip = charged["slippage_usd"]
                modelled = slippage_check["total_usd"]
                slippage_check["charged_usd"] = round(charged_slip, 4)
                slippage_check["ratio_modelled_over_charged"] = (
                    round(modelled / charged_slip, 4) if charged_slip > 0 else None)
                if slippage_check["unmeasured_usd"] > 0:
                    unchecked.append(
                        f"слиппедж не моделируется на ${slippage_check['unmeasured_usd']:,.0f} "
                        f"оборота: TVL там не наблюдён")
                elif charged_slip > 0 and modelled > charged_slip:
                    # НИКОГДА не CRITICAL: наблюдён здесь только TVL, коэффициент k —
                    # литерал. Поднять допущение до критики значило бы выдать модель
                    # за измерение — ровно та подмена, против которой этот модуль.
                    findings.append({
                        "severity": "WARN",
                        "kind": "modelled_slippage_above_the_flat_charge",
                        "message": (
                            f"модель дерева над наблюдённым TVL даёт слиппедж "
                            f"${modelled:,.2f} против заряженных плоских "
                            f"${charged_slip:,.2f} "
                            f"(×{modelled / charged_slip:.3f}) — ДОПУЩЕНИЕ, а не "
                            f"измерение: коэффициент k литерален так же, как и "
                            f"{SLIPPAGE_BPS_STABLE} bps"),
                    })

    # Находка-факт: она не зависит от снимка. Стоимость входит в вердикт ровно
    # одним гейтом, и полоса выгоды сравнивается с ВАЛОВОЙ выгодой.
    findings.append({
        "severity": "INFO",
        "kind": "cost_enters_only_the_payback_gate",
        "message": (
            "стоимость входит в вердикт ТОЛЬКО через `payback_within_horizon`; "
            "`gain_above_band` сравнивает с полосой ВАЛОВУЮ выгоду, из которой "
            "стоимость не вычтена — удорожание перекладки полосу выгоды не сужает"),
    })
    findings.append({
        "severity": "INFO",
        "kind": "all_three_cost_components_are_literals",
        "message": (
            f"все три компоненты заряжаются литералами `cost_model`: газ "
            f"{sorted(set(GAS_USD_PER_POSITION_CHANGE.values()))} $/нога по сетям, "
            f"слиппедж {SLIPPAGE_BPS_STABLE} bps оборота, мост {BRIDGE_BPS} bps"),
    })

    counts = {"critical": 0, "warn": 0, "info": 0, "unchecked": len(unchecked)}
    for f in findings:
        counts[str(f["severity"]).lower()] = counts.get(str(f["severity"]).lower(), 0) + 1

    if counts["unchecked"]:
        overall = "UNCHECKED"
    elif counts["critical"]:
        overall = "CRITICAL"
    elif counts["warn"]:
        overall = "WARN"
    elif counts["info"]:
        overall = "INFO"
    else:
        overall = "OK"

    report = {
        "generated_at": now.isoformat(),
        "overall": overall,
        "counts": counts,
        "verdict_generated_at": verdict_at,
        "capital_usd": capital_usd,
        "charged": charged,
        "observed_gas": observed,
        "substitution": substitution,
        "slippage_check": slippage_check,
        "provenance": {
            "params": params_provenance,
            "gas_slo": slo_provenance,
            "gas_unit": (f"gwei · 1e-9 · GAS_LIMIT_PER_LEG={GAS_LIMIT_PER_LEG} · "
                         f"eth_usd — множитель производителя (ADR-183)"),
            "chains": f"data/adapter_registry.json — тот же источник, что у "
                      f"allocation_rationale (настоящий вызывающий)",
        },
        "findings": findings,
        "unchecked": unchecked,
        "verdict_freshness": verdict_freshness,
        "criterion": _criterion_block(findings, unchecked, substitution,
                                      verdict_freshness=verdict_freshness),
        "note": (
            "ADVISORY. Отвечает на §49 «Costs» ТЗ «Portfolio CIO» (gas, fees, slippage "
            "accounted for in decision). Капитал по этому вердикту НЕ двигается: "
            "`_move_cost_usd`, `TriggerParams`, RiskPolicy и kill-switch не трогаются — "
            "подстановка наблюдённого газа в решение это money-path и решение "
            "владельца. Сверка газа — НАБЛЮДЕНИЕ против литерала (одна единица, "
            "`usd_per_leg`); сверка слиппеджа — МОДЕЛЬ над наблюдённым TVL против "
            "литерала, то есть допущение, и выше WARN она не поднимается никогда."
        ),
    }
    if write:
        atomic_save(report, os.path.join(root, REPORT_REL))
    return report


def _main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args(argv)

    rep = run(root=args.root, write=not args.no_save, data_dir=args.data_dir)
    c = rep["counts"]
    print(f"rebalance_cost_evidence: {rep['overall']} (critical={c['critical']} "
          f"warn={c['warn']} info={c['info']} unchecked={c['unchecked']})")
    ch = rep["charged"]
    if ch:
        print(f"   заряжено ${ch['total_usd']:,.2f} = газ ${ch['gas_usd']:,.2f} + "
              f"слиппедж ${ch['slippage_usd']:,.2f} + мост ${ch['bridge_usd']:,.2f}"
              f"  (сошлось с _move_cost_usd: {ch['consistent']})")
    s = rep["substitution"]
    if s:
        print(f"   газ: заряжено ${s['gas_usd_charged']:,.2f} против наблюдённых "
              f"${s['gas_usd_observed']:.4f} (×{s['gas_ratio_charged_over_observed']:,})")
        print(f"   полная стоимость ${s['total_usd_charged']:,.2f} → "
              f"${s['total_usd_on_observed_gas']:,.2f} (×"
              f"{s['cost_ratio_observed_over_charged']}); payback "
              f"{s['payback_days_charged']} → {s['payback_days_on_observed_gas']} дн. "
              f"при горизонте {s['max_payback_days']}")
        print(f"   зазор гейта ×{s['gate_flip_margin']}; вердикт переворачивается: "
              f"{s['verdict_would_flip']}")
        if s["false_refusal_band_days"]:
            print(f"   полоса ложного отказа: заряженный payback от "
                  f"{s['false_refusal_band_days'][0]} до "
                  f"{s['false_refusal_band_days'][1]} дн.")
    for f in rep["findings"]:
        if f["severity"] in ("CRITICAL", "WARN"):
            print(f"   [{f['severity']}] {f['message']}")
    for u in rep["unchecked"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")
    return {"OK": 0, "INFO": 0, "WARN": 1, "CRITICAL": 1, "UNCHECKED": 2}[rep["overall"]]


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(_main())
