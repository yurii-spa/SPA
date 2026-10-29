"""ДОПУСТИМОСТЬ книги формы урезания — СПРОШЕНА, а не выведена (ADR-855).

Что здесь нового по сравнению с соседями
----------------------------------------
Пять блоков уже спрашивают про урезанный ход, и ни один не спрашивает, пустит
ли полученную книгу риск-политика:

====================================  ========================================
``admissible_size_reach`` (ADR-848)   прошёл бы ход, УРЕЗАННЫЙ до потолка
``admissible_trim`` (ADR-850)         живая проводка: цель урезается до потолка
``…_trim.cost_of_the_trim`` (ADR-853) сколько стоит ОДНО предложение до/после
``trim_shape`` (ADR-854)              дешевле ли урезание ДРУГОЙ формы
**этот модуль**                       **пустит ли КНИГУ формы RiskPolicy**
====================================  ========================================

ADR-854 измерил РАЗМЕР ПРИЗА формы «подмножество по спреду» на 103
предложениях (медиана окупаемости 150.52 → 65.17 дн., в горизонт 30 дн.
укладываются 9 → 19) и сам назвал, чего замер не даёт:

    «допустима ли книга подмножества (RiskPolicy не спрашивали; потолок на
    ГРУППУ угол бокса не сохраняет)»

Основание у этой оговорки было: ADR-850 привёл контрпример на двух ключах T2
при потолке тира 50 % — стоящая (30, 10), цель (10, 30), обе книги по 40 %, а
жадная пара «купить B раньше, чем продан A» даёт (30, 30) = 60 %. Угол бокса
не есть точка отрезка, и сумма по ГРУППЕ у него вправе превысить обе границы.
Но контрпример — это РАССУЖДЕНИЕ о возможности, а не замер населения: сколько
записанных предложений действительно дают недопустимую книгу, не знал никто, и
приз ADR-854 держался на этом незаданном вопросе.

Этот модуль задаёт его той же дверью, которой книгу судит сама политика.

Какую дверь мы спрашиваем — и какую НЕ можем
--------------------------------------------
Спрашиваем ``RiskPolicy.check_portfolio_health`` — дверь, судящую КНИГУ
(ADR-134: охват расширен до тех же порогов, что у входной проверки, —
концентрация на протокол, суммы тиров T2/T3, суммарный L2, концентрация на
сеть, буфер кэша, коридор удерживаемой ставки).

НЕ спрашиваем ``risk_gate._apply_risk_policy_gate`` — живую дверь шага 2e'',
и это НАЗВАННАЯ цена, а не молчание: той двери нужен снимок адаптеров дня
(``tvl_source``, живой TVL, APY фида), а запись истории предложений его не
несёт ВОВСЕ. Воспроизвести живой вердикт на истории нельзя; подставить пустой
снимок значило бы судить другую книгу (без живого TVL гейт режет цель до
удерживаемого), то есть ответить на свой вопрос вместо нужного.

Что из этого следует для чтения чисел:

* **ДЕЛЬТА между формами** честна полностью: обе книги судит одна дверь с
  одними входами, просадка у обеих ноль (журнал истории pnl не несёт), цены
  стейблов не предъявлены ни одной, ёмкость и пол TVL уходят в warnings
  (инв. #17: «не предъявлено» ≠ «пройдено») — значит РАЗЛИЧИЕ вердиктов
  объясняется только РАСКЛАДКОЙ, то есть формой;
* **абсолютный вердикт** есть вердикт двери книги, а не вердикт дня: ярлыки
  тиров взяты из СЕГОДНЯШНЕГО реестра (исторического ярлыка запись не несёт),
  и день мог судить тот же протокол другим тиром.

Тир неизвестен ⇒ ``unmeasured``, и НИКОГДА не «T2»
--------------------------------------------------
Без ярлыка тира ни потолок на протокол (40 % T1 против 20 % T2), ни сумма
группы не определены. Подставить второй тир здесь означало бы вернуть ровно
тот дефект, который снят ADR-359: сомнение, трактованное в пользу сделки.
Поэтому запись с незнакомым ключом уходит в самостоятельный исход с НАЗВАННЫМ
ключом, а не в «допустимо» и не в «недопустимо».

Наследство против вины формы — и наследство у формы ДВА КОНЦА
------------------------------------------------------------
Нарушение, которое дверь называет у КОНЦА отрезка, формой не вызвано. Концов
ДВА, и считать наследством только один из них — ошибка, измеренная в этом же
цикле: первый прогон сверял форму со СТОЯЩЕЙ книгой и объявил «виной формы»
все 12 отказов интерполяции, в том числе восемь по потолку концентрации на
протокол. Но точка отрезка между двумя книгами не способна превысить обе
границы ни по одному ЛИНЕЙНОМУ потолку — значит превышение пришло из ЦЕЛИ
(предложений, отказанных дверью, в истории 15). Сверка с одним концом
записала чужое нарушение в цену формы.

Поэтому виной формы считается нарушение, которого нет НИ У ОДНОГО из концов, а
у каждой формы печатаются три числа: «отказано» · «отказано нарушением, какого
нет ни у одного конца» · «отказано только наследством». Третье есть дрейф
стоящей книги либо недопустимое предложение аллокатора, и к форме оно не
относится.

**Сверять наследство ТЕКСТОМ нарушения нельзя** — вторая ошибка того же
прогона. Дверь печатает в текст ЧИСЛО («Concentration breach: morpho_steakhouse
at 21.2% > 20.0%»), и у конца отрезка то же нарушение того же протокола несёт
ДРУГОЙ процент. Сравнение строк объявило восемь таких наследств виной формы, то
есть утверждало, что точка отрезка превышает ЛИНЕЙНЫЙ потолок, которого не
превышают оба конца, — арифметически невозможное. Сверять надо ПРЕДМЕТ
нарушения: пару «правило + на чём именно» (``violation_key``). Неопознанный
текст предметом получает СЕБЯ ЦЕЛИКОМ — тогда два разных нарушения не сольются
в одно молча.

Потолок числа протоколов дверь книги НЕ спрашивает
--------------------------------------------------
``RiskConfig.max_protocols`` (ALLOC-002, ≤ 8 профинансированных позиций)
читают аллокатор и ``policy_enforcer``, а ``check_portfolio_health`` — нет.
Поэтому число профинансированных позиций здесь ИЗМЕРЯЕТСЯ и печатается рядом
с объявленным потолком, но вердиктом НЕ становится: своя копия порога спорила
бы с его настоящими читателями молча. Это замер разрыва, а не новый гейт.

Сам потолок берётся у ТОГО ЖЕ объекта политики, который даёт вердикт
(``declared_funded_cap`` → ``RiskPolicy().config``), а не у отдельного
экземпляра конфига и не у литерала: два источника одного порога разошлись бы
молча. Не прочитан ⇒ ``None``, и счётчики превышения тоже ``None`` — ноль
прочитался бы как «превышений нет».

ADVISORY. Ни одного порога не меняет, цель дня не трогает, капитал не двигает,
RiskPolicy не правит ни строкой (только ЗОВЁТ её), живой трек не пишет.
Только ЧИТАЕТ записанную историю предложений.

LLM запрещён. Только stdlib. Детерминированно: одни входы — один ответ.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("spa.paper_trading.trim_admissibility")

_EPS = 1e-9

#: Исходы вопроса «допустима ли книга формы» на ОДНОЙ записи. Пять, и каждый —
#: ЗНАЧЕНИЕ (инв. #17 CLAUDE.md), а не пустое поле.
ADM_MEASURED = "measured"
ADM_UNMEASURED = "unmeasured"
ADM_NO_SUBJECT = "no_subject"            # оборот внутри потолка ⇒ урезать нечего
ADM_NO_ALTERNATIVE = "no_alternative"    # формы-соседки не существует
ADM_TIER_UNKNOWN = "tier_unknown"        # ярлык тира не прочитан ⇒ потолки не определены

#: Правила двери книги, названные СВОИМ ключом. Текст нарушения приходит из
#: ``policy.check_portfolio_health`` английской строкой; группировать её по
#: первым двум словам (так делал черновой замер) значило бы завести СВОЙ
#: словарь правил рядом с настоящим. Здесь — явная таблица префиксов, и всё,
#: что ей не опознано, уходит в ``other`` С ТЕКСТОМ, а не теряется.
_RULE_PREFIXES: Tuple[Tuple[str, str], ...] = (
    ("Concentration breach:", "protocol_concentration"),
    ("Total T2 allocation", "t2_group_cap"),
    ("Total T3 allocation", "t3_group_cap"),
    ("Total L2 allocation", "l2_group_cap"),
    ("Chain concentration on", "chain_concentration"),
    ("Cash buffer", "cash_buffer"),
    ("Held APY", "held_apy_corridor"),
    ("Held TVL", "held_tvl_floor"),
    ("KILL SWITCH", "kill_switch"),
    ("SOFT DE-RISK", "kill_switch"),
    ("DEPEG", "depeg"),
)

RULE_OTHER = "other"


def rule_of_violation(text: str) -> str:
    """Ключ правила по тексту нарушения; неопознанное — ``other``, не молчание."""
    s = str(text or "")
    for prefix, rule in _RULE_PREFIXES:
        if s.startswith(prefix):
            return rule
    return RULE_OTHER


def violation_key(text: str) -> Tuple[str, str]:
    """ПРЕДМЕТ нарушения: ``(правило, на чём именно)``. Без чисел из текста.

    Нужно затем, чтобы «то же нарушение того же протокола» у конца отрезка и у
    формы совпало: дверь печатает в текст процент, и строки у них РАЗНЫЕ при
    одном предмете. Сверка строк ровно на этом объявила наследство виной формы.

    Предмет не разобран ⇒ им становится ВЕСЬ текст: два разных нарушения не
    имеют права слиться в одно молча (это было бы «не измерено» как ответ).
    """
    s = str(text or "")
    rule = rule_of_violation(s)
    if rule == "protocol_concentration":
        tail = s.split(":", 1)[1].strip() if ":" in s else ""
        subject = tail.split(" at ", 1)[0].strip()
    elif rule == "chain_concentration":
        tail = s.split(" on ", 1)[1].strip() if " on " in s else ""
        subject = tail.split(" ", 1)[0].strip()
    elif rule in ("held_apy_corridor", "held_tvl_floor"):
        parts = s.split()
        subject = parts[2] if len(parts) > 2 else ""
    elif rule in ("t2_group_cap", "t3_group_cap", "l2_group_cap",
                  "cash_buffer", "kill_switch", "depeg"):
        subject = ""                       # правило само себе предмет
    else:
        return RULE_OTHER, s
    return (rule, subject) if subject or rule not in (
        "protocol_concentration", "chain_concentration",
        "held_apy_corridor", "held_tvl_floor") else (RULE_OTHER, s)


def tier_map(ddir) -> Tuple[Dict[str, str], bool]:
    """Карта «протокол → тир» — тем же реестром и тем же разбором, что у гейта.

    Возврат ``(карта, измерена ли)``. Разбор значения — канон
    ``risk.policy.tier_from_registry``: рядом жили четыре копии правила, и две
    считали T3 вторым тиром, а строку ``"T1"`` — не первым. Своя копия разбора
    здесь повторила бы эту ошибку на новом приборе.

    Ключ, которого в реестре нет или чей тир не узнан, в карту НЕ попадает —
    и вызывающий обязан различить это от «тир известен» (``ADM_TIER_UNKNOWN``).
    """
    if ddir is None:
        return {}, False
    import json
    from pathlib import Path

    from spa_core.risk.policy import tier_from_registry
    try:
        raw = json.loads((Path(ddir) / "adapter_registry.json").read_text("utf-8"))
    except Exception:  # noqa: BLE001 — реестра нет ⇒ сказать об этом, а не угадать
        return {}, False
    out: Dict[str, str] = {}
    for name, entry in ((raw or {}).get("adapters") or {}).items():
        if not isinstance(entry, dict):
            continue
        tier = tier_from_registry(entry.get("tier"))
        if tier is not None:
            out[str(name)] = tier
    return out, True


def declared_funded_cap() -> Optional[int]:
    """Потолок числа профинансированных позиций — у ТОГО ЖЕ объекта политики.

    Спрашивается у ``RiskPolicy().config``, а не у литерала рядом и не у
    отдельного экземпляра конфига: вердикт книги даёт тот же объект, и два
    источника одного порога разошлись бы молча.

    ``None`` — НЕ ИЗМЕРЕНО, и это не ноль: ноль прочитался бы как «потолок
    равен нулю», а пустое поле — как «превышений нет» (инв. #17).
    """
    from spa_core.risk.policy import RiskPolicy
    try:
        return int(RiskPolicy().config.max_protocols)
    except Exception as exc:  # noqa: BLE001 — потолок не прочитан ⇒ не ноль
        log.warning("max_protocols не прочитан (%s) — потолок НЕ ИЗМЕРЕН", exc)
        return None


def book_verdict(book: Dict[str, float],
                 apy_pct: Dict[str, float],
                 capital_usd: float,
                 *,
                 tiers: Dict[str, str],
                 chains: Dict[str, str]) -> Tuple[Optional[dict], List[str]]:
    """Вердикт двери КНИГИ о ``book``. Возврат ``(вердикт, ключи без тира)``.

    ``вердикт is None`` ⇔ список ключей без тира НЕ пуст: потолки на такой
    книге не определены, и это самостоятельный исход, а не отказ и не проход.

    Просадка здесь ноль по построению (журнал истории pnl не несёт), цены
    стейблов не предъявлены, карта TVL не предъявлена — всё три одинаково у
    ОБЕИХ форм, поэтому различие вердиктов объясняется раскладкой. Названо в
    докстринге модуля; молчать об этом нельзя.
    """
    from spa_core.risk.policy import PortfolioState, Position, RiskPolicy

    positions: List[Position] = []
    unknown: List[str] = []
    for proto, amount in sorted((book or {}).items()):
        tier = (tiers or {}).get(str(proto))
        if tier is None:
            unknown.append(str(proto))
            continue
        apy = float((apy_pct or {}).get(str(proto), 0.0) or 0.0)
        positions.append(Position(
            protocol_key=str(proto), tier=tier, asset="USDC",
            amount_usd=float(amount or 0.0),
            apy_at_open=apy, current_apy=apy,
            unrealized_pnl_usd=0.0, days_held=0.0,
            chain=str((chains or {}).get(str(proto)) or "ethereum")))
    if unknown:
        return None, sorted(set(unknown))
    state = PortfolioState(total_capital_usd=float(capital_usd),
                           positions=positions)
    result = RiskPolicy().check_portfolio_health(state)
    return ({"approved": bool(result.approved),
             "violations": [str(v) for v in result.violations],
             "required_response": str(result.required_response),
             "funded": len(positions)},
            [])


def compare_trim_admissibility(current: Dict[str, float],
                               target: Dict[str, float],
                               apy_pct: Dict[str, float],
                               *,
                               capital_usd: float,
                               params,
                               tiers: Dict[str, str],
                               chains: Dict[str, str],
                               chains_measured: bool) -> dict:
    """Четыре вердикта на ОДНОЙ записи: стоящая книга · предложение · обе формы.

    Стоящая книга и предложение судятся не для красоты: без них «форма даёт
    недопустимую книгу» нечем отличить от «день уже стоял вне политики».
    """
    from spa_core.paper_trading.trim_shape import (
        SHAPE_MEASURED, SHAPE_NO_ALTERNATIVE, SHAPE_NO_SUBJECT,
        compare_trim_shapes, shapes_of_proposal)

    out: dict = {}
    shapes = shapes_of_proposal(current, target, apy_pct,
                                capital_usd=capital_usd, params=params)
    kind = str(shapes.get("kind"))
    if kind == SHAPE_NO_SUBJECT:
        return {"kind": ADM_NO_SUBJECT, "why": shapes.get("why")}
    if kind == SHAPE_NO_ALTERNATIVE:
        return {"kind": ADM_NO_ALTERNATIVE, "why": shapes.get("why")}
    if kind != SHAPE_MEASURED:
        return {"kind": ADM_UNMEASURED,
                "why": f"книги форм не построены: {shapes.get('why')}"}

    capital = float(shapes["capital_usd"])
    cur = shapes["current"]
    books = {"standing": cur,
             "proposal": shapes["proposal"],
             "interpolated": shapes["book_interpolated"],
             "subset": shapes["book_subset"]}
    verdicts: Dict[str, dict] = {}
    for name, book in books.items():
        verdict, unknown = book_verdict(book, apy_pct, capital,
                                        tiers=tiers, chains=chains)
        if verdict is None:
            return {"kind": ADM_TIER_UNKNOWN,
                    "unknown_tier_keys": unknown,
                    "why": (f"ярлык тира не прочитан для {', '.join(unknown)} "
                            f"(книга «{name}») — потолок на протокол и сумма "
                            "группы не определены; второй тир НЕ подставляется "
                            "(ADR-359)")}
        verdicts[name] = verdict

    # Наследство мерится по ОБОИМ концам отрезка, а не по одному: нарушение,
    # которое дверь называет у ЦЕЛИ, форма не изобрела — она его донесла.
    ends = {violation_key(v) for v in verdicts["standing"]["violations"]}
    ends |= {violation_key(v) for v in verdicts["proposal"]["violations"]}
    for name in ("interpolated", "subset"):
        fresh = [v for v in verdicts[name]["violations"]
                 if violation_key(v) not in ends]
        verdicts[name]["new_violations"] = fresh
        verdicts[name]["new_rules"] = sorted({rule_of_violation(v) for v in fresh})
        verdicts[name]["inherited_violations"] = [
            v for v in verdicts[name]["violations"]
            if violation_key(v) in ends]

    # Экономика форм берётся у СВОЕЙ двери (ADR-854), а не считается здесь
    # заново: приз и допустимость — два разных вопроса об одной книге, и две
    # копии одной формулы разошлись бы молча.
    econ = compare_trim_shapes(current, target, apy_pct,
                              capital_usd=capital_usd, params=params,
                              chains=chains, chains_measured=chains_measured)
    out.update({
        "kind": ADM_MEASURED,
        "verdicts": verdicts,
        "funded": {name: verdicts[name]["funded"] for name in books},
        "funded_ends_max": max(len(books["standing"]), len(books["proposal"])),
        "payback_interpolated": (econ.get("interpolated") or {}).get("payback_days"),
        "payback_subset": (econ.get("subset") or {}).get("payback_days"),
        "economics_kind": str(econ.get("kind")),
        "why": (f"стоящая книга {'ДА' if verdicts['standing']['approved'] else 'НЕТ'} · "
                f"предложение {'ДА' if verdicts['proposal']['approved'] else 'НЕТ'} · "
                f"интерполяция {'ДА' if verdicts['interpolated']['approved'] else 'НЕТ'} · "
                f"подмножество {'ДА' if verdicts['subset']['approved'] else 'НЕТ'}"),
    })
    return out


#: Исходы переписи. Третий — самостоятельное значение (урок ADR-851).
CENSUS_MEASURED = "measured"
CENSUS_MEASURED_ZERO = "measured_zero"
CENSUS_UNMEASURED = "unmeasured"


def trim_admissibility_census(records: List[dict], *, params,
                              tiers: Dict[str, str],
                              tiers_measured: bool,
                              chains: Dict[str, str],
                              chains_measured: bool) -> dict:
    """Допустимость обеих форм на ВСЕЙ записанной истории предложений.

    Население то же, что у ADR-854 по построению (любое записанное предложение
    выше потолка размера), и это условие сравнимости: приз считается на ТОЙ ЖЕ
    основе — «обе окупаемости определены», — а затем ещё раз на её
    ДОПУСТИМОЙ части. Две разные основы дали бы два несравнимых числа.

    Перепись только ЧИТАЕТ и ничего не чинит.
    """
    from spa_core.paper_trading.trim_shape import _median, _proposal_of

    if not isinstance(records, list):
        return {"kind": CENSUS_UNMEASURED,
                "why": "история не список — допустимость форм не измерена"}
    if not tiers_measured:
        return {"kind": CENSUS_UNMEASURED,
                "why": ("реестр адаптеров не прочитан — ярлыков тира нет, и ни один "
                        "потолок концентрации на книге не определён; второй тир НЕ "
                        "подставляется (ADR-359)")}
    rows: List[dict] = []
    outcomes: Dict[str, int] = {}
    unknown_keys: Dict[str, int] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        proposal, source = _proposal_of(rec)
        one = compare_trim_admissibility(
            rec.get("current_positions") or {},
            proposal,
            rec.get("apy_evidenced_pct") or {},
            capital_usd=rec.get("capital_usd") or 0.0,
            params=params, tiers=tiers, chains=chains,
            chains_measured=chains_measured)
        kind = str(one.get("kind"))
        outcomes[kind] = outcomes.get(kind, 0) + 1
        if kind == ADM_TIER_UNKNOWN:
            for key in one.get("unknown_tier_keys") or []:
                unknown_keys[str(key)] = unknown_keys.get(str(key), 0) + 1
        if kind == ADM_MEASURED:
            one["date"] = rec.get("cycle_date")
            one["proposal_source"] = source
            rows.append(one)
    if not rows:
        return {"kind": (CENSUS_MEASURED_ZERO if outcomes else CENSUS_UNMEASURED),
                "outcomes": outcomes,
                "unknown_tier_keys": unknown_keys,
                "records": len([r for r in records if isinstance(r, dict)]),
                "why": ("урезаемых предложений в истории не нашлось — это ЗАМЕР нуля"
                        if outcomes else
                        "ни одной разобранной записи — допустимость форм не измерена")}

    def _ok(row: dict, name: str) -> bool:
        return bool(((row.get("verdicts") or {}).get(name) or {}).get("approved"))

    both_ok = sum(1 for r in rows if _ok(r, "interpolated") and _ok(r, "subset"))
    only_i = sum(1 for r in rows if _ok(r, "interpolated") and not _ok(r, "subset"))
    only_s = sum(1 for r in rows if _ok(r, "subset") and not _ok(r, "interpolated"))
    neither = sum(1 for r in rows
                  if not _ok(r, "interpolated") and not _ok(r, "subset"))
    causes: Dict[str, Dict[str, int]] = {"interpolated": {}, "subset": {}}
    shape_caused = {"interpolated": 0, "subset": 0}
    inherited_only = {"interpolated": 0, "subset": 0}
    # Образцы ТЕКСТОВ, вменённых форме. Печатаются затем, что число правила не
    # отличает структурное превышение от границы с точностью до цента: замер
    # #973 — у интерполяции все три вины формы читаются «Total T2 allocation
    # 50.0% exceeds limit 50.0%», то есть дверь сравнивает float СТРОГО, а
    # округление книги до цента лежит на самом потолке. Свести это в допуск
    # значило бы завести СВОЙ порог рядом с настоящим.
    shape_caused_samples: Dict[str, List[str]] = {"interpolated": [], "subset": []}
    other_samples: List[str] = []
    for row in rows:
        for name in ("interpolated", "subset"):
            v = (row.get("verdicts") or {}).get(name) or {}
            if v.get("approved"):
                continue
            fresh = list(v.get("new_violations") or [])
            if fresh:
                shape_caused[name] += 1
                for text in fresh:
                    rule = rule_of_violation(text)
                    causes[name][rule] = causes[name].get(rule, 0) + 1
                    if len(shape_caused_samples[name]) < 3:
                        shape_caused_samples[name].append(text)
                    if rule == RULE_OTHER and len(other_samples) < 5:
                        other_samples.append(text)
            else:
                inherited_only[name] += 1

    horizon = float(getattr(params, "max_payback_days", 0.0) or 0.0)
    comparable = [r for r in rows
                  if r.get("payback_interpolated") is not None
                  and r.get("payback_subset") is not None]
    adm_subset = [r for r in comparable if _ok(r, "subset")]
    adm_interp = [r for r in comparable if _ok(r, "interpolated")]
    cap_funded = declared_funded_cap()
    over_cap = {name: (None if cap_funded is None else
                       sum(1 for r in rows
                           if int((r.get("funded") or {}).get(name) or 0) > cap_funded))
                for name in ("interpolated", "subset")}
    above_ends = {name: sum(1 for r in rows
                            if int((r.get("funded") or {}).get(name) or 0)
                            > int(r.get("funded_ends_max") or 0))
                  for name in ("interpolated", "subset")}
    return {
        "kind": CENSUS_MEASURED,
        "records": len([r for r in records if isinstance(r, dict)]),
        "outcomes": outcomes,
        "unknown_tier_keys": unknown_keys,
        "population": len(rows),
        "dates": len({r.get("date") for r in rows}),
        "verdicts": {"both_admissible": both_ok,
                     "only_interpolated": only_i,
                     "only_subset": only_s,
                     "neither": neither},
        "refused": {"interpolated": only_s + neither,
                    "subset": only_i + neither},
        "shape_caused": shape_caused,
        "inherited_only": inherited_only,
        "causes": causes,
        "shape_caused_samples": shape_caused_samples,
        "causes_other_samples": other_samples,
        "ends": {"standing_refused": sum(1 for r in rows if not _ok(r, "standing")),
                 "proposal_refused": sum(1 for r in rows if not _ok(r, "proposal"))},
        "prize": {
            "horizon_days": horizon,
            "comparable": len(comparable),
            "median_subset_all": _median([float(r["payback_subset"])
                                          for r in comparable]),
            "within_horizon_subset_all": sum(
                1 for r in comparable
                if float(r["payback_subset"]) <= horizon + _EPS),
            "admissible_subset": len(adm_subset),
            "median_subset_admissible": _median([float(r["payback_subset"])
                                                 for r in adm_subset]),
            "within_horizon_subset_admissible": sum(
                1 for r in adm_subset
                if float(r["payback_subset"]) <= horizon + _EPS),
            "median_interpolated_on_subset_admissible": _median(
                [float(r["payback_interpolated"]) for r in adm_subset]),
            "admissible_interpolated": len(adm_interp),
            "within_horizon_interpolated_admissible": sum(
                1 for r in adm_interp
                if float(r["payback_interpolated"]) <= horizon + _EPS),
        },
        "funded_count": {
            "cap_declared": cap_funded,
            "asked_by_the_book_door": False,
            "over_cap": over_cap,
            "above_both_ends": above_ends,
        },
        "last": rows[-1],
        "tiers_measured": bool(tiers_measured),
        "chains_measured": bool(chains_measured),
        "note": ("вердикт спрошен у двери КНИГИ (`check_portfolio_health`, "
                 "ADR-134), НЕ у живой двери шага (`_apply_risk_policy_gate`): "
                 "снимка адаптеров дня история не несёт, и воспроизвести живой "
                 "вердикт на ней нельзя. Дельта между формами честна полностью "
                 "(одна дверь, одни входы, просадка ноль у обеих); абсолютный "
                 "вердикт несёт цену — ярлыки тиров из СЕГОДНЯШНЕГО реестра"),
    }


def trim_admissibility_outcome(census: Optional[dict]) -> Tuple[str, str]:
    """Дверь чтения переписи допустимости — ОДНА на всех читателей.

    Почему дверь, а не ``census["kind"]`` у каждого читателя: ровно на этом
    ADR-851 развёл «блока не звали» и «блок сработал ноль раз». Возврат
    ``(исход, причина)``; причина НАЗЫВАЕТСЯ всегда.
    """
    if not isinstance(census, dict) or not census:
        return CENSUS_UNMEASURED, ("блока допустимости форм в артефакте нет — "
                                   "запись СТАРШЕ прибора, а не его ноль "
                                   "(урок ADR-851)")
    kind = str(census.get("kind") or "")
    if kind == CENSUS_MEASURED:
        return CENSUS_MEASURED, (f"допустимость спрошена на "
                                 f"{census.get('population')} предложени(и/ях)")
    if kind == CENSUS_MEASURED_ZERO:
        return CENSUS_MEASURED_ZERO, str(census.get("why")
                                         or "урезаемых предложений не нашлось")
    if kind == CENSUS_UNMEASURED:
        return CENSUS_UNMEASURED, str(census.get("why") or "причина не названа")
    return CENSUS_UNMEASURED, f"исход переписи допустимости не разобран ({kind!r})"


def format_trim_admissibility(census: Optional[dict]) -> List[str]:
    """Печать переписи допустимости — своя, а не строка внутри печати ФОРМЫ.

    Вопросы разные и исходы у них НЕ совпадают: форма может быть сравнена, а
    допустимость — нет (реестр не прочитан), и наоборот. Слить их в одну
    печать значило бы, что ответ на один вопрос меняет чтение другого.
    """
    kind, why = trim_admissibility_outcome(census)
    head = ("допустимость формы (ADR-855, ADVISORY — дверь КНИГИ, "
            "не живой гейт дня):")
    if kind != CENSUS_MEASURED:
        return [head, f"  [{kind}] {why}"]
    doc: dict = census if isinstance(census, dict) else {}
    v = doc.get("verdicts") or {}
    ref = doc.get("refused") or {}
    sc = doc.get("shape_caused") or {}
    inh = doc.get("inherited_only") or {}
    causes = doc.get("causes") or {}
    ends = doc.get("ends") or {}
    prize = doc.get("prize") or {}
    fc = doc.get("funded_count") or {}
    last = doc.get("last") or {}
    lines = [
        head,
        f"  население {doc.get('population')} предложени(й) / "
        f"{doc.get('dates')} дат (записей просмотрено "
        f"{doc.get('records')}); исходы {doc.get('outcomes')}",
        f"  вердикт двери книги: допустимы ОБЕ {v.get('both_admissible')} · "
        f"только интерполяция {v.get('only_interpolated')} · только "
        f"подмножество {v.get('only_subset')} · НИ ОДНА {v.get('neither')}",
        f"  отказано: подмножеству {ref.get('subset')} (вина ФОРМЫ — нарушение "
        f"не у одного из концов — {sc.get('subset')}; только наследство "
        f"{inh.get('subset')}) · интерполяции {ref.get('interpolated')} "
        f"(вина формы {sc.get('interpolated')}; только наследство "
        f"{inh.get('interpolated')})",
        f"  чем именно (только вина формы): подмножество {causes.get('subset')} · "
        f"интерполяция {causes.get('interpolated')}",
        f"  образцы вменённого форме (текст с ЧИСЛОМ — видно, структурное это "
        f"превышение или граница с точностью до цента): подмножество "
        f"{(doc.get('shape_caused_samples') or {}).get('subset')} · интерполяция "
        f"{(doc.get('shape_caused_samples') or {}).get('interpolated')}",
        f"  концы отрезка: стоящая книга отказана {ends.get('standing_refused')} · "
        f"предложение отказано {ends.get('proposal_refused')} — их нарушения "
        f"формой НЕ вызваны, наследство мерится по ОБОИМ концам",
        f"  ПРИЗ на той же основе, что у ADR-854 (сравнимы "
        f"{prize.get('comparable')}): медиана подмножества "
        f"{prize.get('median_subset_all')} дн., в горизонт "
        f"{prize.get('horizon_days')} дн. укладываются "
        f"{prize.get('within_horizon_subset_all')}",
        f"  ПРИЗ на ДОПУСТИМОЙ части ({prize.get('admissible_subset')} из "
        f"{prize.get('comparable')}): медиана подмножества "
        f"{prize.get('median_subset_admissible')} дн. (интерполяция на тех же "
        f"записях {prize.get('median_interpolated_on_subset_admissible')} дн.), "
        f"в горизонт укладываются "
        f"{prize.get('within_horizon_subset_admissible')}",
        f"  профинансированных позиций: потолок объявлен "
        f"{fc.get('cap_declared')} (ALLOC-002), дверь книги его НЕ спрашивает; "
        f"выше потолка {fc.get('over_cap')}; выше ОБОИХ концов отрезка "
        f"{fc.get('above_both_ends')}",
    ]
    if doc.get("causes_other_samples"):
        lines.append("  неопознанные тексты нарушений (НЕ потеряны): "
                     + " | ".join(doc["causes_other_samples"]))
    if doc.get("unknown_tier_keys"):
        lines.append(f"  ключи без ярлыка тира: {census['unknown_tier_keys']} — "
                     "записи с ними НЕ судились ни в одну сторону")
    if last:
        lv = last.get("verdicts") or {}
        lines.append(
            f"  последнее: {last.get('date')} — интерполяция "
            f"{'ДА' if (lv.get('interpolated') or {}).get('approved') else 'НЕТ'}, "
            f"подмножество "
            f"{'ДА' if (lv.get('subset') or {}).get('approved') else 'НЕТ'}"
            + (f"; подмножеству мешает "
               f"{(lv.get('subset') or {}).get('new_violations')}"
               if not (lv.get("subset") or {}).get("approved") else ""))
    if not doc.get("chains_measured"):
        lines.append("  карта сетей НЕ прочитана — потолки на сеть и суммарный "
                     "L2 судились при подстановке `ethereum` всем ключам")
    lines.append("  НЕ ДОКЛАДЫВАЕТ: вердикт ЖИВОЙ двери дня (снимка адаптеров "
                 "история не несёт) · исторический ярлык тира (взят сегодняшний) "
                 "· пол TVL и ёмкость (не предъявлены — у двери это warnings, "
                 "инв. #17) · предложил ли бы аллокатор эту книгу · исход хода")
    return lines
