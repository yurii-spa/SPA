#!/usr/bin/env python3
"""Девять ограничений §16 приказа владельца: объявлен ли потолок, доезжает ли он до гейта.

Критерий §16 `Risk` приказа владельца «Portfolio CIO»
(`inbox-task-portfolio-cio-dynamic-capital-alloc`), заказ G947 п. 1, цикл #1077.

Дословно §16 требует использовать СУЩЕСТВУЮЩУЮ каноническую Risk Policy
(«не создавать альтернативную», «Portfolio CIO не имеет права обходить Risk
Gate») и перечисляет ДЕВЯТЬ ограничений, которые риск обязан учитывать «как
минимум», а про отсутствующие — «вынести предложение отдельно».

Прибор НИЧЕГО НЕ ПРАВИТ: ни порога, ни политики, ни гейта. §16 просит
ПРЕДЛОЖЕНИЕ, а не правку (предмет №1 ADR-285), поэтому здесь только замер.

Что прибор меряет — и чем он НЕ является
------------------------------------------------------------------------------
У каждого из девяти ограничений спрашиваются ТРИ РАЗНЫХ вопроса, и ни один не
выводится из другого:

1. **Объявлен ли потолок** в каноническом ``RiskConfig``. Спрашивается у
   dataclass'а, а не у памяти автора: поля перечисляет ``dataclasses.fields``.
2. **Доезжает ли он до двери допуска** — ``RiskPolicy.check_new_position``.
   Мерится ДИФФЕРЕНЦИАЛЬНО: сцена прогоняется дважды, и род присваивается по
   СМЕНЕ вердикта, а не по чтению кода.
3. **Чей субъект связывает сработавший потолок** — тот, который называет
   владелец, или ПРОКСИ. Эта ось добавлена замером (ниже): у §16 первым пунктом
   стои́т «protocol concentration», а гейт ключует потолок строкой реестра
   адаптеров, то есть ВАULT'ом.

Почему ось субъекта ОТДЕЛЬНАЯ, а не исход рода
------------------------------------------------------------------------------
Род (``CHARGE_KINDS``) отвечает «шевелится ли вердикт». Субъект отвечает «о чём
был вердикт». Сложить их в один перечень значило бы заставить две оси нести
ОДИН бит (урок ADR-943): состояние «потолок исполняется безупречно, но не над
тем субъектом» по шкале рода выглядит как ЛУЧШИЙ исход ``charged_named`` — и
именно оно найдено этим циклом.

Словарь родов ВВЕЗЁН, а не перепечатан
------------------------------------------------------------------------------
``CHARGE_KINDS`` и ``UNMEASURED`` импортируются из §13
(``spa_core.analytics.transaction_economics``). Вторая копия словаря означала бы
две шкалы, расходящиеся молча, — тот же дефект, который §13 нашёл у цены.

Сцена обязана быть ПРИГОДНОЙ, и это проверяется ДО возмущения
------------------------------------------------------------------------------
Первый черновик этого прибора спросил про потолок цепи книгой, где одна Base-
позиция стояла 30 %, и получил отказ — но отказ дал потолок НА ПРОТОКОЛ (20 %),
а не потолок цепи. Сцена была спутана, и ответ вышел НЕВЕРНО В СТОРОНУ НАХОДКИ.
Поэтому базовая книга каждой сцены обязана быть ОДОБРЕНА до возмущения; не
одобрена ⇒ ``unmeasured`` с названной причиной, а не род.

Три исхода различимы (инв. #17)
------------------------------------------------------------------------------
измерено · измерено и равно «не заряжено» · НЕ ИЗМЕРЕНО с причиной. Дверь не
ввезена, словарь родов пуст, сцена непригодна — каждое даёт ``unmeasured`` и
ненулевой код возврата, а не «чисто».

Чего прибор НЕ доказывает
------------------------------------------------------------------------------
* Он спрашивает ДВЕРЬ ДОПУСКА (``check_new_position``) — ту, которую §16
  называет «Risk Gate». У политики есть ВТОРАЯ дверь
  (``check_portfolio_health``), и ограничение, отсутствующее у первой, может
  жить у второй; где это измерено, оно НАЗВАНО (``health_door``) и не
  выдаётся за отсутствие в системе.
* «Потолок доезжает» ≠ «порог верен». О ЗНАЧЕНИИ порога прибор не судит ничем:
  это предмет владельца.
* Отсутствие находки у ограничения не доказывает, что обойти его нельзя;
  доказательство одностороннее, сильная сторона у него отрицательная. Тот же
  порядок у соседа §49 (``spa_core/monitoring/policy_binding_census.py``),
  который отвечает на ДРУГОЙ вопрос — нарушала ли потолок РЕАЛЬНО стоявшая
  книга.
"""

from __future__ import annotations

import argparse
import dataclasses
import inspect
import json
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Словарь родов — ВВОЗ из §13. Своей копии здесь нет намеренно.
# ---------------------------------------------------------------------------
_KINDS_IMPORT_ERROR: Optional[str] = None
try:
    from .transaction_economics import CHARGE_KINDS, UNMEASURED
except Exception as _exc:  # pragma: no cover - ввоз меряется тестом
    CHARGE_KINDS = ()  # type: ignore[assignment]
    UNMEASURED = "unmeasured"
    _KINDS_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"


#: Род СУБЪЕКТА, которого связывает сработавший потолок. Ось ОТДЕЛЬНАЯ от рода
#: (см. шапку): «исполняется безупречно, но не над тем субъектом» по шкале рода
#: неотличимо от лучшего исхода.
SUBJECT_KINDS: Tuple[str, ...] = (
    "absent",   # связывать нечего: потолка нет
    "proxy",    # потолок связывает НЕ тот субъект, который назван владельцем
    "named",    # потолок связывает РОВНО названный субъект
)

#: Сцена замера. Книга ОБЪЯВЛЕНА здесь, а не взята из живого трека: предмет —
#: ПОВЕДЕНИЕ ГЕЙТА, оно обязано быть воспроизводимым на любой машине в любой
#: день. Живой трек (`data/equity_curve_daily.json`) не входит сюда ни одним
#: числом — запрет `CLAUDE.md`.
SCENE_CAPITAL_USD = 100_000.0
SCENE_TVL_USD = 200_000_000.0   # заведомо выше floor $5M: floor — предмет ДРУГОЙ оси
SCENE_APY = 5.0                 # внутри [1 %, 30 %]: границы APY — тоже другая ось

#: Пара ключей ОДНОГО протокола, на которой снимается ось субъекта. Выбрана
#: ЗАМЕРОМ реестра (:func:`family_population`), а не на глаз, и обе половины
#: проверяются на присутствие в живом `ADAPTER_REGISTRY`.
SCENE_FAMILY_TOKEN = "morpho"
SCENE_SAME_KEY = "morpho_blue"
SCENE_SIBLING_KEY = "morpho_steakhouse"


def _constraint(key: str, owner_words: str, ceiling_fields: Sequence[str],
                probe: str, why: str = "", health_door: str = "") -> Dict[str, Any]:
    return {
        "key": key,
        "owner_words": owner_words,
        "ceiling_fields": tuple(ceiling_fields),
        "probe": probe,
        "why": why,
        "health_door": health_door,
    }


#: ДЕВЯТЬ ограничений §16, слова владельца — дословно, в порядке приказа.
#: ``ceiling_fields`` — ПРЕТЕНЗИЯ о том, какое поле `RiskConfig` является
#: потолком этого ограничения; претензия СВЕРЯЕТСЯ с живым dataclass'ом
#: (:func:`measure_ceilings`), а не принимается на слово.
CONSTRAINTS: Tuple[Dict[str, Any], ...] = (
    _constraint(
        "protocol_concentration", "protocol concentration",
        ("max_concentration_t1", "max_concentration_t2", "max_single_protocol"),
        probe="protocol_subject",
        why="потолок объявлен и исполняется, но ключуется строкой реестра адаптеров",
    ),
    _constraint(
        "vault_concentration", "vault concentration", (),
        probe="vault_subject",
        why="своего потолка нет; де-факто исполняется потолком, объявленным как протокольный",
    ),
    _constraint(
        "tier_concentration", "Tier concentration",
        ("max_total_t2_allocation", "max_total_t3_allocation"),
        probe="tier_total",
    ),
    _constraint(
        "chain_concentration", "chain concentration",
        ("max_single_chain_allocation", "max_l2_total_allocation", "BASE_CHAIN_CAP"),
        probe="chain_total",
        why="два поля из трёх доезжают; BASE_CHAIN_CAP объявлен и у двери не читается",
    ),
    _constraint(
        "asset_concentration", "asset concentration", (),
        probe="signature_absent",
        why="`asset` есть у Position, но у двери допуска параметра нет",
    ),
    _constraint(
        "strategy_concentration", "strategy concentration", (),
        probe="signature_absent",
        why="понятия strategy нет ни у двери, ни у Position",
    ),
    _constraint(
        "liquidity", "liquidity", ("min_tvl_usd",),
        probe="liquidity_floor",
        why="floor на пул исполняется; ёмкость позиции (MP-209) warn-only и не блокирует",
    ),
    _constraint(
        "withdrawal_availability", "withdrawal availability", (),
        probe="signature_absent",
        health_door="check_duration_axis (exit_latency_map) — живёт у check_portfolio_health",
    ),
    _constraint(
        "correlated_dependencies", "correlated dependencies", (),
        probe="signature_absent",
        health_door="check_bridge_axis / check_peg_axis — живут у check_portfolio_health",
    ),
)


# ---------------------------------------------------------------------------
# Ввоз дверей. Дверь не ввезена ⇒ третий исход, а не подставленная заглушка.
# ---------------------------------------------------------------------------

def load_policy() -> Tuple[Any, Any, Optional[str]]:
    """Вернуть (RiskPolicy-экземпляр, RiskConfig-класс, причина отказа)."""
    try:
        from spa_core.risk.policy import RiskPolicy, RiskConfig
    except Exception as exc:  # pragma: no cover
        return None, None, f"канон RiskPolicy не ввезён: {type(exc).__name__}: {exc}"
    try:
        return RiskPolicy(), RiskConfig, None
    except Exception as exc:  # pragma: no cover
        return None, RiskConfig, f"RiskPolicy() не построился: {type(exc).__name__}: {exc}"


def admission_parameters(policy: Any) -> Tuple[Tuple[str, ...], Optional[str]]:
    """Параметры двери ДОПУСКА. Спрашиваются у подписи, а не перепечатываются."""
    try:
        sig = inspect.signature(policy.check_new_position)
    except Exception as exc:  # pragma: no cover
        return (), f"подпись двери не прочитана: {type(exc).__name__}: {exc}"
    return tuple(sorted(p for p in sig.parameters if p != "self")), None


def state_fields() -> Tuple[Tuple[str, ...], Optional[str]]:
    """Поля строки книги (`Position`) — вторая половина того, что дверь ВИДИТ."""
    try:
        from spa_core.risk.policy import Position
        return tuple(f.name for f in dataclasses.fields(Position)), None
    except Exception as exc:  # pragma: no cover
        return (), f"контракт строки не прочитан: {type(exc).__name__}: {exc}"


def measure_ceilings(config_cls: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """Сверить претензию каждого ограничения о своём потолке с живым RiskConfig.

    Претензия, назвавшая поле, которого в dataclass'е НЕТ, — это дефект
    прибора, и он обязан быть НАЗВАН, а не округлён до «потолка нет».
    """
    if config_cls is None:
        return {}, "RiskConfig не ввезён"
    try:
        declared = {f.name for f in dataclasses.fields(config_cls)}
    except Exception as exc:  # pragma: no cover
        return {}, f"поля RiskConfig не прочитаны: {type(exc).__name__}: {exc}"

    out: Dict[str, Any] = {}
    for c in CONSTRAINTS:
        present = [f for f in c["ceiling_fields"] if f in declared]
        missing = [f for f in c["ceiling_fields"] if f not in declared]
        out[c["key"]] = {
            "claimed": list(c["ceiling_fields"]),
            "present": present,
            "phantom": missing,          # претензия назвала несуществующее поле
            "declared": bool(present),
        }
    return out, None


# ---------------------------------------------------------------------------
# Сцена и классификация. Базовая книга обязана быть ОДОБРЕНА до возмущения.
# ---------------------------------------------------------------------------

def _position(key: str, tier: str, usd: float, chain: str = "ethereum",
              asset: str = "USDC") -> Any:
    from spa_core.risk.policy import Position
    return Position(protocol_key=key, tier=tier, asset=asset, amount_usd=usd,
                    apy_at_open=SCENE_APY, current_apy=SCENE_APY, chain=chain)


def _book(rows: Sequence[Tuple[str, str, float, str]]) -> Any:
    from spa_core.risk.policy import PortfolioState
    return PortfolioState(
        total_capital_usd=SCENE_CAPITAL_USD,
        positions=[_position(k, t, u, ch) for (k, t, u, ch) in rows],
    )


def _ask(policy: Any, rows: Sequence[Tuple[str, str, float, str]],
         key: str, tier: str, usd: float, chain: str = "ethereum",
         tvl: float = SCENE_TVL_USD, apy: float = SCENE_APY,
         check_capacity: bool = False) -> Dict[str, Any]:
    """Один вопрос живой двери допуска."""
    try:
        res = policy.check_new_position(
            _book(rows), protocol_key=key, tier=tier, amount_usd=usd,
            current_apy=apy, tvl_usd=tvl, chain=chain,
            check_capacity=check_capacity,
        )
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "approved": bool(res.approved),
        "violations": [str(v) for v in (res.violations or [])],
        "warnings": [str(w) for w in (res.warnings or [])],
    }


def scene_unfit_reason(base: Dict[str, Any]) -> Optional[str]:
    """Пригодна ли сцена ДО возмущения. Непригодная сцена отвечает не о том.

    Это не украшение: первый черновик спросил про потолок цепи книгой, в
    которой связывал потолок на протокол, и ответ вышел неверно В СТОРОНУ
    НАХОДКИ.
    """
    if "error" in base:
        return f"базовый вопрос упал: {base['error']}"
    if not base.get("approved"):
        return ("базовая книга НЕ ОДОБРЕНА до возмущения — связывает посторонний "
                f"потолок: {base.get('violations')}")
    return None


def classify(base: Dict[str, Any], shifted: Dict[str, Any],
             markers: Sequence[str]) -> Tuple[str, Dict[str, Any]]:
    """Род по СМЕНЕ вердикта, а не по чтению кода.

    `markers` — слова, по которым узнаётся СВОЁ нарушение. Вердикт шевельнулся,
    а ни одно нарушение не названо своим ⇒ `charged_merged`: потолок сработал
    ЧУЖИМ сообщением, и отличить его от соседа нечем.
    """
    detail: Dict[str, Any] = {"base": base, "shifted": shifted}
    unfit = scene_unfit_reason(base)
    if unfit:
        return UNMEASURED, {**detail, "reason": unfit}
    if "error" in shifted:
        return UNMEASURED, {**detail, "reason": f"возмущённый вопрос упал: {shifted['error']}"}

    if shifted.get("approved"):
        return "not_charged", detail

    viol = shifted.get("violations") or []
    own = [v for v in viol if any(m.lower() in v.lower() for m in markers)]
    detail["own_violations"] = own
    return ("charged_named" if own else "charged_merged"), detail


# ---------------------------------------------------------------------------
# Население семейств — замер реестра, а не список из головы.
# ---------------------------------------------------------------------------

def family_population() -> Tuple[Dict[str, List[str]], Optional[str]]:
    """Сколько ключей реестра делят ПЕРВЫЙ токен имени (кандидаты в семейство).

    ⚠️ Имя НЕ ЕСТЬ полномочие: совпадение токена — кандидат, а не доказательство
    родства. Доказательством здесь служит ДРУГОЕ — у risk-слоя карты семейства
    нет вовсе (:func:`family_map_exists`), поэтому гейт не мог бы связать
    протокол даже при верной карте имён.
    """
    try:
        from spa_core.adapters import ADAPTER_REGISTRY
    except Exception as exc:
        return {}, f"реестр адаптеров не ввезён: {type(exc).__name__}: {exc}"
    keys: List[str] = []
    for entry in ADAPTER_REGISTRY:
        keys.append(entry[0] if isinstance(entry, (tuple, list)) else str(entry))
    fams: Dict[str, List[str]] = {}
    for k in keys:
        fams.setdefault(str(k).split("_")[0], []).append(str(k))
    return {t: sorted(v) for t, v in sorted(fams.items()) if len(v) > 1}, None


def family_map_exists() -> Dict[str, Any]:
    """Есть ли у КАНОНИЧЕСКОЙ политики понятие семейства/эмитента протокола.

    Спрашивается у контракта (поля `Position` + параметры двери), а не грепом по
    тексту: греп нашёл бы слово в комментарии и ответил бы «есть» о том, чего
    дверь не видит.
    """
    fields, f_err = state_fields()
    tokens = ("issuer", "family", "parent", "protocol_group", "vault_of")
    hits = [f for f in fields if any(t in f.lower() for t in tokens)]
    return {
        "position_fields": list(fields),
        "family_like_fields": hits,
        "exists": bool(hits),
        "unmeasured_reason": f_err,
    }


# ---------------------------------------------------------------------------
# Пробы. Каждая — своя сцена, со своим положительным контролем.
# ---------------------------------------------------------------------------

def probe_protocol_subject(policy: Any) -> Dict[str, Any]:
    """Связывает ли потолок концентрации ПРОТОКОЛ — или строку реестра.

    Дифференциал с ВСТРОЕННЫМ положительным контролем: одни и те же деньги, тот
    же протокол, тот же тир, та же цепь — меняется ТОЛЬКО ключ.

    * тот же ключ (`morpho_blue`)        → контроль: потолок ОБЯЗАН сработать;
    * сосед того же протокола (`...steakhouse`) → предмет замера.

    Контроль здесь несущий: без него «одобрено» у соседа могло бы означать, что
    потолок не работает вообще, а не что он ключуется вautом.
    """
    out: Dict[str, Any] = {"family_token": SCENE_FAMILY_TOKEN}

    regs, err = family_population()
    if err:
        return {**out, "kind": UNMEASURED, "reason": err}
    present = set()
    for v in regs.values():
        present.update(v)
    missing = [k for k in (SCENE_SAME_KEY, SCENE_SIBLING_KEY) if k not in present]
    if missing:
        return {**out, "kind": UNMEASURED,
                "reason": f"ключи сцены отсутствуют в живом реестре: {missing}"}

    half = SCENE_CAPITAL_USD * 0.19
    rows = [(SCENE_SAME_KEY, "T2", half, "ethereum")]

    control = _ask(policy, rows, SCENE_SAME_KEY, "T2", half)
    subject = _ask(policy, rows, SCENE_SIBLING_KEY, "T2", half)
    out["control_same_key"] = control
    out["subject_sibling_key"] = subject

    if "error" in control or "error" in subject:
        return {**out, "kind": UNMEASURED, "reason": "вопрос двери упал"}

    if control.get("approved"):
        # Контроль не сработал ⇒ сцена не доказывает НИЧЕГО о субъекте.
        return {**out, "kind": UNMEASURED,
                "reason": ("контроль не сработал: потолок не связал даже ТОТ ЖЕ ключ, "
                           "значит сцена не о субъекте")}

    out["family_map"] = family_map_exists()
    if subject.get("approved"):
        out["kind"] = "charged_named"      # потолок РАБОТАЕТ…
        out["subject"] = "proxy"           # …но связывает ВАULT, не протокол
        out["finding"] = (
            f"те же ${half:,.0f}, тот же протокол «{SCENE_FAMILY_TOKEN}», тот же тир: "
            f"ключ {SCENE_SAME_KEY} ОТКАЗ, ключ {SCENE_SIBLING_KEY} ОДОБРЕН — "
            "потолок «protocol concentration» ключуется строкой реестра адаптеров"
        )
    else:
        out["kind"] = "charged_named"
        out["subject"] = "named"
        out["finding"] = "потолок связал и соседний ключ того же протокола"
    return out


def probe_vault_subject(policy: Any, protocol_probe: Dict[str, Any]) -> Dict[str, Any]:
    """Оборотная сторона той же монеты: ВАULT-концентрация исполняется БЕЗ объявления.

    Своего потолка у `vault concentration` в `RiskConfig` нет ни одного, а
    де-факто связывается именно vault — тем полем, которое объявлено
    протокольным. Род берётся у того же дифференциала (одна сцена — один
    замер), а не снимается второй раз.
    """
    kind = protocol_probe.get("kind")
    subj = protocol_probe.get("subject")
    if kind == UNMEASURED:
        return {"kind": UNMEASURED, "reason": protocol_probe.get("reason")}
    if subj == "proxy":
        return {
            "kind": "charged_named",
            "subject": "named",
            "declared": False,
            "finding": ("исполняется БЕЗ объявления: потолок, объявленный как "
                        "протокольный, связывает vault — ярлык и предмет РАЗОШЛИСЬ"),
        }
    return {"kind": "not_charged", "subject": "absent",
            "finding": "потолок связал протокол, отдельного ограничения на vault нет"}


def probe_tier_total(policy: Any) -> Dict[str, Any]:
    """Доезжает ли СУММАРНЫЙ потолок тира (T2 50 %, ADR-019)."""
    # Книга: два T2-ключа по 19 % = 38 % T2, каждый под потолком на протокол.
    rows = [("morpho_blue", "T2", 19_000.0, "ethereum"),
            ("pendle", "T2", 19_000.0, "ethereum")]
    base = _ask(policy, rows, "euler_v2", "T2", 5_000.0)        # 43 % T2 — под 50 %
    shifted = _ask(policy, rows, "euler_v2", "T2", 15_000.0)    # 53 % T2 — НАД 50 %
    kind, detail = classify(base, shifted, markers=("Total T2 allocation",))
    return {"kind": kind, "subject": "named" if kind == "charged_named" else "absent",
            **detail}


def probe_chain_total(policy: Any) -> Dict[str, Any]:
    """Цепь: доезжает ли single-chain потолок — и доезжает ли BASE_CHAIN_CAP.

    ДВА вопроса, и они РАЗНЫЕ: у ограничения «chain concentration» объявлено
    ТРИ поля, и одно из трёх у двери не читается. Склеить их значило бы выдать
    «потолок цепи исполняется» за ответ про все три.
    """
    out: Dict[str, Any] = {}

    # (1) single-chain 90 %: книга 85 % ethereum по РАЗНЫМ ключам (чтобы не
    #     связал потолок на протокол), сдвиг до 95 %.
    #
    #     Тир у всех строк T1 НАМЕРЕННО, и сумма сдвига ровно 10 000: первая
    #     редакция сцены взяла T2 и 11 000, и тогда отказ давали СУММАРНЫЙ
    #     потолок T2 (55 % > 50 %) и кэш-буфер (4 % < 5 %), а не потолок цепи.
    #     Сцена отвечала не о том, и ответ шёл В СТОРОНУ НАХОДКИ.
    rows = [("aave_v3", "T1", 35_000.0, "ethereum"),
            ("compound_v3", "T1", 35_000.0, "ethereum"),
            ("euler_v2", "T1", 15_000.0, "ethereum")]
    base = _ask(policy, rows, "yearn_v3", "T1", 5_000.0)      # 90 % — ровно потолок
    shifted = _ask(policy, rows, "yearn_v3", "T1", 10_000.0)  # 95 % — над потолком
    kind, detail = classify(base, shifted, markers=("Chain concentration", "single-chain"))
    out["single_chain"] = {"kind": kind, **detail}

    # (2) BASE_CHAIN_CAP 20 %: Base размазан по разным ключам (каждый под
    #     потолком на протокол), сумма Base 30 % — над 20 %, под L2 50 %.
    b_rows = [("aave_v3_base", "T2", 15_000.0, "base")]
    b_base = _ask(policy, b_rows, "morpho_blue_base", "T2", 4_000.0)   # Base 19 %
    b_shift = _ask(policy, b_rows, "morpho_blue_base", "T2", 15_000.0)  # Base 30 %
    b_kind, b_detail = classify(b_base, b_shift, markers=("BASE_CHAIN_CAP", "Base chain"))
    out["base_chain_cap"] = {"kind": b_kind, **b_detail}

    out["kind"] = kind
    out["subject"] = "named" if kind == "charged_named" else "absent"
    # Вложенная находка обязана дойти до ВЕРДИКТА, иначе род верхнего уровня её
    # ПРЯЧЕТ: `BASE_CHAIN_CAP` объявлен и у двери не читается, а top-level род
    # ограничения при этом `charged_named` — ровно то состояние, когда две оси
    # несут один бит (ADR-943).
    out["sub_findings"] = [{
        "field": "BASE_CHAIN_CAP", "kind": b_kind,
        "note": "объявлен в RiskConfig; policy.py не читает его ни одной строкой",
    }]
    # Причина НЕ ИЗМЕРЕНО обязана доноситься НАВЕРХ. Первая редакция держала её
    # только во вложенной пробе, и сводка печатала «unmeasured: None» — то есть
    # третий исход был объявлен БЕЗ названной причины (инв. #17 требует причину).
    if kind == UNMEASURED:
        out["reason"] = f"single-chain: {detail.get('reason')}"
    out["split_finding"] = (
        f"single-chain {kind} · BASE_CHAIN_CAP {b_kind} — "
        "объявлены три поля, доезжают не все"
    )
    return out


def probe_liquidity_floor(policy: Any) -> Dict[str, Any]:
    """Ликвидность: floor на пул доезжает; ёмкость позиции — warn-only.

    Два РАЗНЫХ вопроса, и §16 просит второй: «liquidity» как способность выйти,
    а не как «пул крупнее $5 млн».
    """
    out: Dict[str, Any] = {}
    rows: List[Tuple[str, str, float, str]] = []

    base = _ask(policy, rows, "morpho_blue", "T2", 10_000.0, tvl=SCENE_TVL_USD)
    shifted = _ask(policy, rows, "morpho_blue", "T2", 10_000.0, tvl=1_000_000.0)
    kind, detail = classify(base, shifted, markers=("TVL",))
    out["tvl_floor"] = {"kind": kind, **detail}

    # Ёмкость позиции (MP-209). ДОСТИЖИМОСТЬ порога мерится ДО сцены: род
    # нельзя печатать у порога, которого сцена не пересекает (иначе ноль есть
    # свойство сцены, а не системы). Первая редакция этой пробы спросила
    # 10 000 при TVL 6 млн — 0,17 % против порога 1 %, то есть НЕ ПЕРЕСЕКЛА, и
    # «not_charged» вышел верным СЛУЧАЙНО.
    out["capacity"] = probe_capacity_reachable(policy, rows)

    out["kind"] = kind
    out["subject"] = "proxy" if kind == "charged_named" else "absent"
    out["sub_findings"] = [{
        "field": "capacity (MP-209)", "kind": out["capacity"].get("kind"),
        "note": out["capacity"].get("reason") or "warn-only, не блокирует",
    }]
    if kind == UNMEASURED:
        out["reason"] = f"tvl_floor: {detail.get('reason')}"
    out["split_finding"] = (
        f"floor пула {kind} · ёмкость позиции {out['capacity'].get('kind')} — "
        "floor отвечает «пул крупный», а не «мы сможем выйти»"
    )
    return out


def probe_capacity_reachable(policy: Any,
                             rows: Sequence[Tuple[str, str, float, str]]) -> Dict[str, Any]:
    """Достижим ли вообще порог ёмкости под ОСТАЛЬНЫМИ объявленными потолками.

    Порог ёмкости — доля TVL пула (`effective_max_pct`). Чтобы его пересечь,
    позиция обязана быть больше `порог × TVL`; одновременно TVL обязан быть не
    ниже floor'а, а позиция — не выше потолка концентрации. Эти три
    объявленных числа могут не иметь ОБЩЕГО решения, и тогда ограничение не
    «не заряжено», а НЕДОСТИЖИМО — род печатать нельзя (инв. #17).

    Числа берутся у НАСТОЯЩИХ производителей (`effective_max_pct`,
    `RiskConfig`), ни одно не перепечатано.
    """
    try:
        from spa_core.risk.capacity_limits import effective_max_pct
        from spa_core.risk.policy import RiskConfig
    except Exception as exc:
        return {"kind": UNMEASURED,
                "reason": f"производитель порога ёмкости не ввезён: {type(exc).__name__}: {exc}"}
    cfg = RiskConfig()
    try:
        pct = float(effective_max_pct(SCENE_SAME_KEY, "T1", cfg.min_tvl_usd))
    except Exception as exc:
        return {"kind": UNMEASURED,
                "reason": f"порог ёмкости не прочитан: {type(exc).__name__}: {exc}"}

    need_usd = cfg.min_tvl_usd * pct               # минимум, чтобы ПЕРЕСЕЧЬ ёмкость
    allowed_usd = SCENE_CAPITAL_USD * cfg.max_concentration_t1   # максимум по концентрации
    facts = {
        "capacity_pct_of_tvl": pct,
        "tvl_floor_usd": cfg.min_tvl_usd,
        "min_position_to_cross_usd": need_usd,
        "max_position_by_concentration_usd": allowed_usd,
        "scene_capital_usd": SCENE_CAPITAL_USD,
        "warn_only_declared": "MP-209 / ADR-009",
    }
    if need_usd > allowed_usd:
        # Капитал, при котором порог становится достижим: C·cap_T1 > floor·pct
        becomes_at = need_usd / cfg.max_concentration_t1
        return {
            "kind": UNMEASURED,
            "reason": (
                f"порог ёмкости НЕДОСТИЖИМ под объявленными потолками: пересечь его "
                f"требует позиции ≥ ${need_usd:,.0f} ({pct:.0%} от floor TVL "
                f"${cfg.min_tvl_usd:,.0f}), а потолок концентрации T1 на книге "
                f"${SCENE_CAPITAL_USD:,.0f} разрешает максимум ${allowed_usd:,.0f}"
            ),
            "becomes_reachable_at_capital_usd": becomes_at,
            **facts,
        }

    base = _ask(policy, rows, SCENE_SAME_KEY, "T1", need_usd * 0.5,
                tvl=cfg.min_tvl_usd * 1.1, check_capacity=True)
    shifted = _ask(policy, rows, SCENE_SAME_KEY, "T1", need_usd * 1.5,
                   tvl=cfg.min_tvl_usd * 1.1, check_capacity=True)
    kind, detail = classify(base, shifted, markers=("CAPACITY",))
    return {"kind": kind, **detail, **facts}


def probe_signature_absent(policy: Any, constraint: Dict[str, Any],
                           params: Sequence[str], fields: Sequence[str]) -> Dict[str, Any]:
    """Ограничение, субъект которого дверь НЕВЫРАЗИМА.

    Род присваивается не «ничего не нашли глазами», а ЗАМЕРОМ подписи двери и
    контракта строки: субъекта нет ни среди параметров, ни среди полей книги ⇒
    наступление ограничения НЕВЫРАЗИМО, и это `no_input_door`.
    """
    token = constraint["key"].split("_")[0]
    in_params = [p for p in params if token in p.lower()]
    in_fields = [f for f in fields if token in f.lower()]
    out = {
        "token": token,
        "in_door_params": in_params,
        "in_position_fields": in_fields,
        "health_door": constraint.get("health_door") or None,
    }
    if in_params:
        return {**out, "kind": "not_charged", "subject": "absent",
                "reason": "субъект у двери ВЫРАЗИМ, но потолка нет — требует своей сцены"}
    if in_fields:
        return {**out, "kind": "no_input_door", "subject": "absent",
                "reason": ("у СТОЯЩЕЙ книги субъект выразим, у ВХОДЯЩЕЙ позиции — нет: "
                           "дверь не знает, что именно заводят")}
    return {**out, "kind": "no_input_door", "subject": "absent",
            "reason": "субъекта нет ни у двери, ни у строки книги"}


# ---------------------------------------------------------------------------
# Сборка
# ---------------------------------------------------------------------------

def measure() -> Dict[str, Any]:
    rep: Dict[str, Any] = {
        "section": "§16 Risk",
        "order_card": "inbox-task-portfolio-cio-dynamic-capital-alloc",
        "doors_touched": "ЧИТАЕТ. Ни политика, ни пороги, ни гейт не правятся",
        "charge_kinds": list(CHARGE_KINDS),
        "subject_kinds": list(SUBJECT_KINDS),
        "constraints": {},
        "unmeasured": [],
    }

    if _KINDS_IMPORT_ERROR or not CHARGE_KINDS:
        rep["unmeasured"].append(
            f"словарь родов §13 не ввезён ({_KINDS_IMPORT_ERROR or 'CHARGE_KINDS пуст'}) — "
            "мерить род НЕЧЕМ"
        )
        return rep

    policy, config_cls, perr = load_policy()
    if perr or policy is None:
        rep["unmeasured"].append(perr or "дверь допуска не ввезена")
        return rep

    params, sig_err = admission_parameters(policy)
    fields, fld_err = state_fields()
    rep["admission_door"] = "RiskPolicy.check_new_position"
    rep["admission_params"] = list(params)
    rep["position_fields"] = list(fields)
    if sig_err:
        rep["unmeasured"].append(sig_err)
    if fld_err:
        rep["unmeasured"].append(fld_err)

    ceilings, c_err = measure_ceilings(config_cls)
    if c_err:
        rep["unmeasured"].append(c_err)

    fams, f_err = family_population()
    rep["registry_families"] = fams
    rep["registry_family_keys"] = sum(len(v) for v in fams.values())
    if f_err:
        rep["unmeasured"].append(f_err)

    proto = probe_protocol_subject(policy)

    for c in CONSTRAINTS:
        key, probe = c["key"], c["probe"]
        if probe == "protocol_subject":
            res = proto
        elif probe == "vault_subject":
            res = probe_vault_subject(policy, proto)
        elif probe == "tier_total":
            res = probe_tier_total(policy)
        elif probe == "chain_total":
            res = probe_chain_total(policy)
        elif probe == "liquidity_floor":
            res = probe_liquidity_floor(policy)
        elif probe == "signature_absent":
            res = probe_signature_absent(policy, c, params, fields)
        else:  # pragma: no cover
            res = {"kind": UNMEASURED, "reason": f"проба {probe!r} не зарегистрирована"}

        ceil = ceilings.get(key, {})
        if ceil.get("phantom"):
            rep["unmeasured"].append(
                f"{key}: претензия назвала поле(я) {ceil['phantom']}, которых в "
                "RiskConfig НЕТ — дефект прибора, а не «потолка нет»"
            )

        entry = {
            "owner_words": c["owner_words"],
            "ceiling_declared": ceil.get("declared"),
            "ceiling_fields_present": ceil.get("present", []),
            "kind": res.get("kind"),
            "subject": res.get("subject"),
            "why": c["why"] or None,
            "health_door": c.get("health_door") or None,
            "detail": res,
        }
        rep["constraints"][key] = entry
        if res.get("kind") == UNMEASURED:
            rep["unmeasured"].append(f"{key}: {res.get('reason')}")

    # Сводка по родам — счёт с НАЗВАННЫМИ членами, иначе его нечем перемерить.
    tally: Dict[str, List[str]] = {}
    for key, e in rep["constraints"].items():
        tally.setdefault(str(e["kind"]), []).append(key)
    rep["tally"] = {k: sorted(v) for k, v in sorted(tally.items())}
    subj: Dict[str, List[str]] = {}
    for key, e in rep["constraints"].items():
        subj.setdefault(str(e["subject"]), []).append(key)
    rep["subject_tally"] = {k: sorted(v) for k, v in sorted(subj.items())}
    rep["declared_not_reaching"] = sorted(
        k for k, e in rep["constraints"].items()
        if e["ceiling_declared"] and e["kind"] in ("not_charged", "no_input_door")
    )
    # Находки ПОЛЕЙ (а не ограничений целиком): объявленный порог, который до
    # двери не доезжает, хотя род ограничения в целом `charged_named`.
    subs: List[Dict[str, Any]] = []
    for key, e in rep["constraints"].items():
        for sf in (e["detail"].get("sub_findings") or []):
            if sf.get("kind") in ("not_charged", "no_input_door", UNMEASURED):
                subs.append({"constraint": key, **sf})
    rep["field_findings"] = subs
    return rep


def render(rep: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("§16 «Risk» — девять ограничений приказа владельца")
    lines.append("=" * 72)
    door = rep.get("admission_door")
    if door:
        lines.append(f"дверь допуска: {door}")
        lines.append(f"её параметры:  {', '.join(rep.get('admission_params', []))}")
    lines.append("")
    lines.append(f"{'ограничение':<26} {'потолок':<9} {'род':<15} субъект")
    lines.append("-" * 72)
    for key, e in rep.get("constraints", {}).items():
        dec = "объявлен" if e["ceiling_declared"] else "НЕТ"
        lines.append(f"{key:<26} {dec:<9} {str(e['kind']):<15} {e['subject']}")
    lines.append("")
    for k, members in rep.get("tally", {}).items():
        lines.append(f"  род {k}: {len(members)} — {', '.join(members)}")
    for k, members in rep.get("subject_tally", {}).items():
        lines.append(f"  субъект {k}: {len(members)} — {', '.join(members)}")
    dnr = rep.get("declared_not_reaching") or []
    if dnr:
        lines.append("")
        lines.append(f"⚠️ объявлен и НЕ доезжает до двери допуска: {', '.join(dnr)}")
    ff = rep.get("field_findings") or []
    if ff:
        lines.append("")
        lines.append(f"⚠️ находки ПОЛЕЙ внутри ограничений ({len(ff)}):")
        for sf in ff:
            lines.append(f"  · {sf['constraint']} / {sf['field']}: {sf['kind']}")
            lines.append(f"      {sf['note']}")
    fams = rep.get("registry_families") or {}
    if fams:
        lines.append("")
        lines.append(f"семейств-кандидатов в реестре: {len(fams)}, "
                     f"ключей в них {rep.get('registry_family_keys')}")
        for t, v in list(fams.items())[:6]:
            lines.append(f"    {t}: {len(v)} — {', '.join(v)}")
    um = rep.get("unmeasured") or []
    lines.append("")
    if um:
        lines.append(f"НЕ ИЗМЕРЕНО ({len(um)}):")
        for u in um:
            lines.append(f"  · {u}")
    else:
        lines.append("НЕ ИЗМЕРЕНО: ничего — все девять получили род замером")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§16 Risk: перепись девяти ограничений на живой двери допуска. "
                    "ТОЛЬКО ЧИТАЕТ — политику, пороги и гейт не правит.")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(argv)

    try:
        rep = measure()
        out = (json.dumps(rep, ensure_ascii=False, indent=2, default=str)
               if args.json else render(rep))
    except Exception as exc:  # noqa: BLE001
        # Код 1 объявлен НАХОДКОЙ, а необработанное исключение Python даёт тот же
        # код 1 — то есть падение прибора читалось бы как находка о системе.
        # Три исхода обязаны быть различимы (инв. #17), поэтому падение = 2.
        print(f"НЕ ИЗМЕРЕНО: прибор упал — {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2
    print(out)

    if rep.get("unmeasured"):
        return 2                      # НЕ ИЗМЕРЕНО — третий исход, инв. #17
    if rep.get("declared_not_reaching") or rep.get("field_findings"):
        return 1                      # находка: потолок объявлен и не доезжает
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
