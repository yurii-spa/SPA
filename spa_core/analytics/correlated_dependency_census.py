#!/usr/bin/env python3
"""Десять общих зависимостей §17 приказа владельца: считает ли система три vault тремя ведрами.

Критерий §17 `Correlated risk` приказа владельца «Portfolio CIO»
(`inbox-task-portfolio-cio-dynamic-capital-alloc`), заказ G948 п. 1, цикл #1078.

Дословно §17: «Несколько vault не всегда означают диверсификацию. По
возможности учитывать общие зависимости: protocol · chain · oracle · curator ·
collateral · stablecoin · bridge · smart-contract implementation · reward token ·
liquidity venue. Если три vault зависят от одного и того же systemic component,
они не должны автоматически считаться тремя независимыми risk buckets.»

Прибор НИЧЕГО НЕ ПРАВИТ: ни порога, ни политики, ни гейта, ни аллокатора. §17
говорит «по возможности учитывать», то есть просит ПРЕДЛОЖЕНИЕ, а предложение
по risk-слою — предмет №1 ADR-285 и уходит карточкой владельцу.

Три вопроса, и ни один не выводится из другого
------------------------------------------------------------------------------
У каждой из десяти зависимостей спрашивается:

1. **Выразима ли она у двери вообще** (:data:`EXPRESS_KINDS`). Спрашивается у
   живых контрактов — подпись ``RiskPolicy.check_new_position``, поля
   ``Position``, ключи ``ADAPTER_METADATA``, списки ``spa_core.risk.risk_axes``, —
   а не у памяти автора.
2. **Есть ли в системе НАБЛЮДЁННОЕ число о ней** (:data:`OBSERVE_KINDS`).
   Захардкоженный в репозитории список имён наблюдением НЕ является: это
   ``declared_literal``. Различение дословно наследует ADR-053 («never stamp
   `live` on a constant»): список `PEG_PROTOCOLS` не становится замером от того,
   что по нему считают долю.
3. **Считаются ли два пула с общей зависимостью независимыми**
   (:data:`INDEPENDENCE_KINDS`). Мерится ДИФФЕРЕНЦИАЛЬНО на живой двери:
   сцена прогоняется дважды, род присваивается по СМЕНЕ вердикта.

Почему оси три, а не одна
------------------------------------------------------------------------------
Урок ADR-943: замкнув их в один перечень, две оси понесли бы ОДИН бит.
Состояние «зависимость выразима, число о ней есть, а два пула всё равно
считаются независимыми» по шкале выразимости выглядит как лучший исход — и
именно оно найдено у `protocol` (§16, ADR-959) и у `stablecoin` (этот цикл).

Ось ДВЕРИ отдельная — и это не украшение
------------------------------------------------------------------------------
У политики ДВЕ двери: допуска (``check_new_position``) и книги
(``check_portfolio_health``). Единственная машинерия, которая вообще сводит
общие зависимости в одно ведро, — четыре оси риска (``check_axis_compliance``:
credit · peg · duration · bridge), и живут они у ВТОРОЙ двери за умолчанием
``check_axes=False``. Поэтому «сведено в одно ведро у двери книги с включёнными
осями» и «сведено на ДЕНЕЖНОМ ПУТИ» — два РАЗНЫХ факта, и §17 спрашивает про
второй. Форма зова money-path меряется AST'ом места зова, а не чтением глазами
(:func:`money_path_axis_call_forms`).

Словари ВВЕЗЕНЫ, а не перепечатаны
------------------------------------------------------------------------------
``CHARGE_KINDS``/``UNMEASURED`` — из §13 (``transaction_economics``),
``SUBJECT_KINDS`` и ``family_population`` — из §16
(``risk_constraint_census``), списки зависимостей и матчер — из канона
``spa_core.risk.risk_axes``. Вторая копия словаря означала бы две шкалы,
расходящиеся молча.

Сцена обязана быть ПРИГОДНОЙ, и это проверяется ДО возмущения
------------------------------------------------------------------------------
Наследуется у §16 дословно: базовая книга каждой сцены обязана быть ОДОБРЕНА
до возмущения, иначе отказ даст ПОСТОРОННИЙ потолок и ответ выйдет неверно в
сторону находки. Первый черновик ЭТОГО прибора споткнулся о то же: сцена peg с
30 % в одном протоколе связала потолок концентрации T2, а не ось peg.

Три исхода различимы (инв. #17)
------------------------------------------------------------------------------
измерено · измерено и равно «сведено в одно ведро» · НЕ ИЗМЕРЕНО с названной
причиной. Отдельно назван третий исход, у §17 главный:
``pair_not_namable`` — карты зависимости в системе НЕТ, поэтому пару пулов,
делящих её, нельзя даже НАЗВАТЬ, не выдумав её. Это не «ведра независимы» и не
«ведро одно»; выдать его за любой из двух значило бы соврать в известную
сторону.

Чего прибор НЕ доказывает
------------------------------------------------------------------------------
* Он не судит о ЗНАЧЕНИИ ни одного порога — это предмет владельца.
* «Зависимость выразима» ≠ «зависимость верна»: карту ``ADAPTER_METADATA``
  прибор читает, а не проверяет на соответствие миру.
* Отсутствие находки у зависимости не доказывает, что обойти её нельзя;
  доказательство одностороннее, сильная сторона у него отрицательная.
* Население «сколько ключей реестра делят зависимость» считается по картам,
  которые В СИСТЕМЕ ЕСТЬ. Для шести зависимостей из десяти карты нет вовсе, и
  их население поэтому НЕ ИЗМЕРЕНО, а не ноль.
"""

from __future__ import annotations

import argparse
import ast
import collections
import dataclasses
import inspect
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Ввоз словарей. Своих копий здесь нет намеренно.
# ---------------------------------------------------------------------------
_VOCAB_IMPORT_ERROR: Optional[str] = None
try:
    from .transaction_economics import CHARGE_KINDS, UNMEASURED
except Exception as _exc:  # pragma: no cover - ввоз меряется тестом
    CHARGE_KINDS = ()  # type: ignore[assignment]
    UNMEASURED = "unmeasured"
    _VOCAB_IMPORT_ERROR = f"§13 CHARGE_KINDS: {type(_exc).__name__}: {_exc}"

_SUBJECT_IMPORT_ERROR: Optional[str] = None
try:
    from .risk_constraint_census import SUBJECT_KINDS, family_population
except Exception as _exc:  # pragma: no cover
    SUBJECT_KINDS = ()  # type: ignore[assignment]
    family_population = None  # type: ignore[assignment]
    _SUBJECT_IMPORT_ERROR = f"§16 SUBJECT_KINDS: {type(_exc).__name__}: {_exc}"


#: ГДЕ зависимость вообще может быть названа. Порядок — от сильного к слабому.
EXPRESS_KINDS: Tuple[str, ...] = (
    "door_input",      # параметр двери допуска: дверь видит зависимость напрямую
    "state_field",     # поле строки книги (`Position`), но НЕ параметр двери
    "name_substring",  # угадывается только из текста `protocol_key`
    "registry_only",   # есть в карте реестра, но ни дверь, ни книга её не несут
    "absent",          # не называется нигде
)

#: ЧТО является источником числа о зависимости. Литерал в репозитории
#: наблюдением НЕ является (ADR-053: «never stamp live on a constant»).
OBSERVE_KINDS: Tuple[str, ...] = (
    "observed",          # число/признак наблюдается на протокол (карта, фид)
    "declared_literal",  # только захардкоженный список/константа в коде
    "absent",            # ничего
)

#: СВОДЯТСЯ ли два пула с общей зависимостью в одно ведро. Главная ось §17.
INDEPENDENCE_KINDS: Tuple[str, ...] = (
    "bucketed_together",     # дверь сложила их в ОДНО ведро — то, что §17 просит
    "independence_assumed",  # дверь сочла их независимыми — то, что §17 запрещает
    "pair_not_namable",      # карты нет: пару, делящую зависимость, НЕЛЬЗЯ назвать
)

#: Какую ДВЕРЬ спросили. Ось отдельная: «сведено у книги с включёнными осями»
#: и «сведено на денежном пути» — РАЗНЫЕ факты (см. шапку).
DOORS: Tuple[str, ...] = (
    "admission",        # RiskPolicy.check_new_position
    "money_path",       # check_portfolio_health(state) — форма зова engine
    "book_axes_on",     # check_portfolio_health(state, check_axes=True)
)

#: Сцена. Книга ОБЪЯВЛЕНА здесь, а не взята из живого трека: предмет —
#: ПОВЕДЕНИЕ ДВЕРЕЙ, оно обязано быть воспроизводимым на любой машине в любой
#: день. Живой трек (`data/equity_curve_daily.json`) не входит сюда ни одним
#: числом — запрет `CLAUDE.md`.
SCENE_CAPITAL_USD = 100_000.0
SCENE_TVL_USD = 200_000_000.0   # заведомо выше floor $5M: floor — другая ось
SCENE_APY = 5.0                 # внутри [1 %, 30 %]: границы APY — другая ось

#: Место зова двери книги, которое прибор считает ДЕНЕЖНЫМ ПУТЁМ. Претензия
#: СВЕРЯЕТСЯ с деревом (:func:`money_path_axis_call_forms`): файла нет ⇒ третий
#: исход, а не «осей нет».
MONEY_PATH_FILES: Tuple[str, ...] = (
    "spa_core/paper_trading/engine.py",
)


def _dep(key: str, owner_words: str, express_claim: str, observe_claim: str,
         name_tokens: Sequence[str], probe: str, source: str = "",
         why: str = "") -> Dict[str, Any]:
    return {
        "key": key,
        "owner_words": owner_words,
        "express_claim": express_claim,
        "observe_claim": observe_claim,
        "name_tokens": tuple(name_tokens),
        "probe": probe,
        "source": source,
        "why": why,
    }


#: ДЕСЯТЬ зависимостей §17, слова владельца — дословно, в порядке приказа.
#: ``express_claim``/``observe_claim`` — ПРЕТЕНЗИИ, и каждая сверяется с живым
#: контрактом. Претензия, не подтверждённая замером, печатается как ДЕФЕКТ
#: ПРИБОРА (``phantom``), а не округляется до «зависимости нет».
DEPENDENCIES: Tuple[Dict[str, Any], ...] = (
    _dep("protocol", "protocol", "door_input", "observed",
         ("protocol_key",), probe="protocol_family",
         source="ADAPTER_REGISTRY / ADAPTER_METADATA",
         why="ключуется строкой реестра, то есть vault'ом (§16, ADR-959)"),
    _dep("chain", "chain", "door_input", "observed",
         ("chain",), probe="chain_shared",
         source="ADAPTER_METADATA['chain']",
         why="сводится в одно ведро: max_l2_total_allocation работает"),
    _dep("oracle", "oracle", "absent", "absent",
         ("oracle",), probe="not_namable",
         why="ни параметра, ни поля книги, ни ключа реестра"),
    _dep("curator", "curator", "absent", "absent",
         ("curator",), probe="not_namable",
         why="ни параметра, ни поля книги, ни ключа реестра"),
    _dep("collateral", "collateral", "absent", "absent",
         ("collateral",), probe="not_namable",
         why="credit-ось про КРЕДИТНЫЕ протоколы, а не про общий залог"),
    _dep("stablecoin", "stablecoin", "state_field", "observed",
         ("asset",), probe="peg_axis",
         source="ADAPTER_METADATA['asset'] + Position.asset (ось peg — ЛИТЕРАЛ)",
         why=("число о зависимости в системе ЕСТЬ, а политика его не читает ни разу; "
              "членство в оси peg решает литерал, и ось выключена на денежном пути")),
    _dep("bridge", "bridge", "name_substring", "declared_literal",
         ("bridge",), probe="bridge_axis",
         source="risk_axes.BRIDGE_PROTOCOLS (литерал)",
         why="ось есть, а ни один ключ реестра её списку не соответствует"),
    _dep("implementation", "smart-contract implementation", "absent", "absent",
         ("implementation",), probe="not_namable",
         why="ни параметра, ни поля книги, ни ключа реестра"),
    _dep("reward_token", "reward token", "absent", "absent",
         ("reward",), probe="not_namable",
         why="ни параметра, ни поля книги, ни ключа реестра"),
    _dep("liquidity_venue", "liquidity venue", "absent", "absent",
         ("venue",), probe="not_namable",
         why="ни параметра, ни поля книги, ни ключа реестра"),
)


# ---------------------------------------------------------------------------
# Ввоз дверей. Дверь не ввезена ⇒ третий исход, а не подставленная заглушка.
# ---------------------------------------------------------------------------

def load_policy() -> Tuple[Any, Optional[str]]:
    """Вернуть (RiskPolicy-экземпляр, причина отказа)."""
    try:
        from spa_core.risk.policy import RiskPolicy
    except Exception as exc:  # pragma: no cover
        return None, f"канон RiskPolicy не ввезён: {type(exc).__name__}: {exc}"
    try:
        return RiskPolicy(), None
    except Exception as exc:  # pragma: no cover
        return None, f"RiskPolicy() не построился: {type(exc).__name__}: {exc}"


def load_axes() -> Tuple[Dict[str, Any], Optional[str]]:
    """Канонические списки осей риска + канонический матчер. ВВОЗ, не копия."""
    try:
        from spa_core.risk import risk_axes
    except Exception as exc:  # pragma: no cover
        return {}, f"risk_axes не ввезён: {type(exc).__name__}: {exc}"
    try:
        return {
            "PEG": list(risk_axes.PEG_PROTOCOLS),
            "BRIDGE": list(risk_axes.BRIDGE_PROTOCOLS),
            "CREDIT": list(risk_axes.CREDIT_PROTOCOLS),
            "DURATION": list(risk_axes.DURATION_DEFAULT_PROTOCOLS),
            # Матчер берётся у канона, а не переписывается: вторая копия
            # правила совпадения означала бы, что прибор мерит СВОЁ правило.
            "_matches": risk_axes._matches,
        }, None
    except Exception as exc:  # pragma: no cover
        return {}, f"списки осей не прочитаны: {type(exc).__name__}: {exc}"


def contracts() -> Tuple[Dict[str, Any], Optional[str]]:
    """ЧТО двери и книга вообще способны назвать. Спрашивается у контрактов."""
    out: Dict[str, Any] = {}
    try:
        from spa_core.risk.policy import Position, RiskPolicy
    except Exception as exc:  # pragma: no cover
        return {}, f"контракты не ввезены: {type(exc).__name__}: {exc}"
    try:
        sig = inspect.signature(RiskPolicy.check_new_position)
        out["admission_params"] = tuple(sorted(
            p for p in sig.parameters if p != "self"))
        sig2 = inspect.signature(RiskPolicy.check_portfolio_health)
        out["health_params"] = tuple(sorted(
            p for p in sig2.parameters if p != "self"))
        out["state_fields"] = tuple(f.name for f in dataclasses.fields(Position))
    except Exception as exc:  # pragma: no cover
        return {}, f"подписи не прочитаны: {type(exc).__name__}: {exc}"
    try:
        from spa_core.adapters.registry import ADAPTER_METADATA
        keys: set = set()
        for meta in ADAPTER_METADATA.values():
            keys |= set(meta or {})
        out["registry_fields"] = tuple(sorted(keys))
        out["registry_keys"] = tuple(ADAPTER_METADATA)
    except Exception as exc:  # pragma: no cover
        return {}, f"карта реестра не прочитана: {type(exc).__name__}: {exc}"
    return out, None


# ---------------------------------------------------------------------------
# Вопрос 1 — выразимость. Претензия СВЕРЯЕТСЯ, а не принимается на слово.
# ---------------------------------------------------------------------------

def policy_field_readers(field: str, root: Optional[Path] = None) -> Tuple[Optional[int], Optional[str]]:
    """Сколько раз канон политики ЧИТАЕТ поле книги. AST, не подстрока.

    «Поле объявлено» и «поле читают» — разные утверждения, и второе до сих
    пор никто не задавал: `Position.asset` объявлено, а обращений к нему в
    `spa_core/risk/policy.py` НОЛЬ (класс ADR-337 — объявлено и не читается).
    Файл не разобран ⇒ третий исход с причиной, а не ноль.
    """
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    path = base / "spa_core" / "risk" / "policy.py"
    if not path.exists():
        return None, f"канон политики не найден: {path}"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"канон политики не разобран: {type(exc).__name__}: {exc}"
    return sum(1 for n in ast.walk(tree)
               if isinstance(n, ast.Attribute) and n.attr == field), None


def measure_expressibility(dep: Dict[str, Any], con: Dict[str, Any],
                           axes: Dict[str, Any],
                           root: Optional[Path] = None) -> Dict[str, Any]:
    """Где зависимость называется НА САМОМ ДЕЛЕ — по живым контрактам.

    Род выводится замером и сверяется с претензией. Расхождение — находка о
    ПРИБОРЕ (``phantom``), и она печатается, а не глотается: §16 нашёл свой
    фантом ровно этим приёмом.
    """
    toks = [t.lower() for t in dep["name_tokens"]]

    def _hit(names: Sequence[str]) -> List[str]:
        return [n for n in names if any(t in n.lower() for t in toks)]

    in_door = _hit(con.get("admission_params", ()))
    in_state = _hit(con.get("state_fields", ()))
    in_registry = _hit(con.get("registry_fields", ()))
    in_axes = sorted(a for a in ("PEG", "BRIDGE", "CREDIT", "DURATION")
                     if a.lower() in toks or dep["key"].lower() == a.lower()
                     or (dep["key"] == "bridge" and a == "BRIDGE"))

    if in_door:
        kind = "door_input"
    elif in_state:
        kind = "state_field"
    elif in_axes:
        kind = "name_substring"
    elif in_registry:
        kind = "registry_only"
    else:
        kind = "absent"

    out = {
        "kind": kind,
        "claim": dep["express_claim"],
        "phantom": kind != dep["express_claim"],
        "door_params": in_door,
        "state_fields": in_state,
        "registry_fields": in_registry,
        "axes": in_axes,
    }
    # Поле книги объявлено — но ЧИТАЕТ ли его политика? Отдельное утверждение.
    if in_state:
        readers, rerr = policy_field_readers(in_state[0], root)
        out["state_field_readers"] = readers
        out["state_field_readers_unmeasured"] = rerr
        out["declared_not_read"] = (readers == 0) if readers is not None else None
    return out


# ---------------------------------------------------------------------------
# Вопрос 2 — наблюдение. Литерал наблюдением НЕ является.
# ---------------------------------------------------------------------------

def measure_observation(dep: Dict[str, Any], con: Dict[str, Any],
                        axes: Dict[str, Any]) -> Dict[str, Any]:
    """Есть ли НАБЛЮДЁННОЕ число о зависимости — или только литерал.

    ``observed`` присваивается, только когда признак лежит в карте реестра НА
    ПРОТОКОЛ (её наполняют адаптеры). Список имён в коде — ``declared_literal``:
    он не становится замером от того, что по нему считают долю.
    """
    toks = [t.lower() for t in dep["name_tokens"]]
    registry_fields = [f for f in con.get("registry_fields", ())
                       if any(t in f.lower() for t in toks)]
    # `protocol` наблюдается самим фактом ключа реестра: карту наполняют адаптеры.
    if dep["key"] == "protocol":
        registry_fields = list(registry_fields) or ["<ключ реестра>"]

    literal_lists = sorted(
        name for name in ("PEG", "BRIDGE", "CREDIT", "DURATION")
        if axes.get(name) and (name.lower() in toks
                               or (dep["key"] == "stablecoin" and name == "PEG")
                               or (dep["key"] == "bridge" and name == "BRIDGE")))

    if registry_fields:
        kind = "observed"
    elif literal_lists:
        kind = "declared_literal"
    else:
        kind = "absent"

    return {
        "kind": kind,
        "claim": dep["observe_claim"],
        "phantom": kind != dep["observe_claim"],
        "registry_fields": registry_fields,
        "literal_lists": literal_lists,
        "literal_members": {n: axes.get(n, []) for n in literal_lists},
    }


# ---------------------------------------------------------------------------
# Сцена и дифференциал. База ОБЯЗАНА быть одобрена ДО возмущения.
# ---------------------------------------------------------------------------

def _position(key: str, tier: str, usd: float, chain: str = "ethereum",
              asset: str = "USDC") -> Any:
    from spa_core.risk.policy import Position
    return Position(protocol_key=key, tier=tier, asset=asset, amount_usd=usd,
                    apy_at_open=SCENE_APY, current_apy=SCENE_APY, chain=chain)


def _book(rows: Sequence[Tuple[str, str, float, str, str]]) -> Any:
    from spa_core.risk.policy import PortfolioState
    return PortfolioState(
        total_capital_usd=SCENE_CAPITAL_USD,
        positions=[_position(k, t, u, ch, a) for (k, t, u, ch, a) in rows],
    )


def _ask_admission(policy: Any, rows: Sequence[Tuple[str, str, float, str, str]],
                   key: str, tier: str, usd: float,
                   chain: str = "ethereum") -> Dict[str, Any]:
    """Один вопрос живой двери ДОПУСКА."""
    try:
        res = policy.check_new_position(
            _book(rows), protocol_key=key, tier=tier, amount_usd=usd,
            current_apy=SCENE_APY, tvl_usd=SCENE_TVL_USD, chain=chain)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {"approved": bool(res.approved),
            "violations": [str(v) for v in (res.violations or [])],
            "warnings": [str(w) for w in (res.warnings or [])]}


def _ask_book(policy: Any, rows: Sequence[Tuple[str, str, float, str, str]],
              axes_on: bool) -> Dict[str, Any]:
    """Один вопрос живой двери КНИГИ.

    ``axes_on=False`` — РОВНО та форма зова, которой дверь зовут на денежном
    пути (``check_portfolio_health(state)``); форма сверена AST'ом
    (:func:`money_path_axis_call_forms`), а не взята из памяти.
    """
    kwargs = {"check_axes": True} if axes_on else {}
    try:
        res = policy.check_portfolio_health(_book(rows), **kwargs)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {"approved": bool(res.approved),
            "violations": [str(v) for v in (res.violations or [])],
            "warnings": [str(w) for w in (res.warnings or [])]}


def scene_unfit_reason(base: Dict[str, Any]) -> Optional[str]:
    """Пригодна ли сцена ДО возмущения. Непригодная отвечает НЕ О ТОМ.

    Наследуется у §16 дословно и уже сработало здесь: сцена peg с 30 % в одном
    протоколе связала потолок концентрации T2, а не ось peg, и ответ вышел
    неверно В СТОРОНУ НАХОДКИ.
    """
    if "error" in base:
        return f"базовый вопрос упал: {base['error']}"
    if not base.get("approved"):
        return ("базовая книга НЕ ОДОБРЕНА до возмущения — связывает посторонний "
                f"потолок: {base.get('violations')}")
    return None


def classify_independence(base: Dict[str, Any], shifted: Dict[str, Any],
                          markers: Sequence[str]) -> Tuple[str, Dict[str, Any]]:
    """Род §17 по СМЕНЕ вердикта, а не по чтению кода.

    `markers` — слова, по которым узнаётся СВОЁ нарушение. Вердикт шевельнулся,
    а ни одно нарушение не названо своим ⇒ это не «сведено в одно ведро»: сошёл
    посторонний потолок, и сцена непригодна.
    """
    detail: Dict[str, Any] = {"base": base, "shifted": shifted}
    unfit = scene_unfit_reason(base)
    if unfit:
        return UNMEASURED, {**detail, "reason": unfit}
    if "error" in shifted:
        return UNMEASURED, {**detail,
                            "reason": f"возмущённый вопрос упал: {shifted['error']}"}
    if shifted.get("approved"):
        return "independence_assumed", detail
    viol = shifted.get("violations") or []
    own = [v for v in viol if any(m.lower() in v.lower() for m in markers)]
    detail["own_violations"] = own
    if not own:
        return UNMEASURED, {
            **detail,
            "reason": ("вердикт шевельнулся, но ни одно нарушение не названо своим — "
                       f"связал посторонний потолок: {viol}"),
        }
    return "bucketed_together", detail


# ---------------------------------------------------------------------------
# Пробы независимости. Пару, делящую зависимость, НАЗЫВАЕТ карта системы.
# ---------------------------------------------------------------------------

def _registry_family_pair() -> Tuple[Optional[Tuple[str, str]], Optional[str]]:
    """Два ключа ОДНОГО протокольного семейства — замером реестра, не на глаз."""
    if family_population is None:
        return None, _SUBJECT_IMPORT_ERROR or "§16 family_population не ввезён"
    fams, err = family_population()
    if err:
        return None, f"население семейств не измерено: {err}"
    for token in sorted(fams):
        members = sorted(fams[token])
        if len(members) >= 2:
            return (members[0], members[1]), None
    return None, "в реестре нет ни одного семейства из двух ключей"


def probe_protocol_family(policy: Any, axes: Dict[str, Any]) -> Dict[str, Any]:
    """Два vault ОДНОГО протокола: одно ведро или два — с ВСТРОЕННЫМ контролем.

    Тир сцены — **T2**, и это не вкус: потолок T2 равен 20 %, поэтому 19 % + 19 %
    = 38 % порог ПЕРЕСЕКАЮТ, а под потолком T1 (40 %) те же 38 % его не
    пересекают и ответ «ведра независимы» вышел бы верным СЛУЧАЙНО. На этом
    ровно спотыкался §16 (проба ёмкости не пересекала порог, ADR-959).

    Контроль встроен в саму пробу: ТОТ ЖЕ ключ на ту же сумму обязан получить
    ОТКАЗ. Не получил ⇒ порог в этой сцене не пересекаем, и прибор отвечает
    НЕ ИЗМЕРЕНО, а не «независимы».
    """
    pair, err = _registry_family_pair()
    if err or pair is None:
        return {"kind": UNMEASURED, "reason": err, "door": "admission"}
    held, sibling = pair
    rows = [(held, "T2", 19_000.0, "ethereum", "USDC")]
    # Тир и доля ОТЧЁТА происходят от самой сцены. Ярлык рядом со сценой пережил
    # бы её подмену молча — мутация №5 цикла #1078 ровно это и доказала.
    tier = rows[0][1]
    exposure_pct = round(2 * rows[0][2] / SCENE_CAPITAL_USD * 100.0, 4)
    base = _ask_admission(policy, rows, sibling, tier, 1.0)
    control = _ask_admission(policy, rows, held, tier, rows[0][2])   # ТОТ ЖЕ ключ
    shifted = _ask_admission(policy, rows, sibling, tier, rows[0][2])  # СОСЕД

    out: Dict[str, Any] = {"door": "admission", "pair": [held, sibling],
                           "exposure_pct": exposure_pct, "tier": tier,
                           "control_same_key": control}
    unfit = scene_unfit_reason(base)
    if unfit:
        return {**out, "kind": UNMEASURED, "reason": unfit}
    if "error" in control:
        return {**out, "kind": UNMEASURED,
                "reason": f"контроль упал: {control['error']}"}
    if control.get("approved"):
        return {**out, "kind": UNMEASURED,
                "reason": ("КОНТРОЛЬ НЕ СРАБОТАЛ: тот же ключ на те же деньги "
                           "одобрен — порог в этой сцене не пересекаем, и "
                           "«ведра независимы» было бы верно случайно")}
    kind, detail = classify_independence(base, shifted,
                                         ("concentration", held, sibling))
    out.update(detail)
    out["scene_rows"] = [list(r) for r in rows]
    out["kind"] = kind
    return out


def probe_chain_shared(policy: Any, axes: Dict[str, Any]) -> Dict[str, Any]:
    """Четыре РАЗНЫХ протокола на одной цепи: одно ведро или четыре.

    Возмущается ТОЛЬКО ЯРЛЫК ЦЕПИ у новой позиции — книга, суммы, тиры и APY
    те же. Первый черновик вместо этого менял СОСТАВ книги (одна позиция против
    трёх) и получал отказ от `max_l2_total_allocation`, то есть от ведра
    КЛАССА L2, а не от ведра ЦЕПИ: ответ был бы верен случайно и о другом.
    """
    rows = [(k, "T1", 23_000.0, "ethereum", "USDC")
            for k in ("aave_usdc", "compound_usdc", "morpho_blue")]
    # база: та же книга, новая позиция на ДРУГОЙ цепи ⇒ зависимость не общая
    base = _ask_admission(policy, rows, "fluid_usdc", "T1", 23_000.0, chain="base")
    # возмущение: ровно та же сумма на ТОЙ ЖЕ цепи ⇒ зависимость общая
    shifted = _ask_admission(policy, rows, "fluid_usdc", "T1", 23_000.0,
                             chain="ethereum")
    kind, detail = classify_independence(base, shifted, ("Chain concentration",))
    return {"kind": kind, "door": "admission", "shared_chain": "ethereum",
            "exposure_pct": 92.0, **detail}


def _peg_rows(axes: Dict[str, Any]) -> Tuple[Optional[List[Any]], Optional[str]]:
    """ТРИ пула, делящие peg-зависимость, — именами из КАНОНИЧЕСКОГО списка.

    §17 говорит «если ТРИ vault зависят от одного systemic component». Доли
    выбраны так, чтобы каждая была НИЖЕ своего потолка концентрации (10 % < 20 %
    T2), а сумма — выше предела оси peg (30 % > 10 %): иначе отказ дал бы
    потолок концентрации, и ответ вышел бы неверно в сторону находки.
    """
    peg = axes.get("PEG") or []
    if len(peg) < 3:
        return None, f"канонический список PEG_PROTOCOLS короче трёх: {peg}"
    rows = [(f"{peg[i]}_vault", "T2", 10_000.0, "ethereum", "USDC")
            for i in range(3)]
    rows.append(("aave_usdc", "T1", 35_000.0, "ethereum", "USDC"))
    return rows, None


def probe_peg_axis(policy: Any, axes: Dict[str, Any]) -> Dict[str, Any]:
    """Stablecoin-зависимость: три пула, одна peg-зависимость, ДВЕ формы зова.

    Дифференциал здесь не «книга против книги», а **форма зова против формы
    зова на одной и той же книге**: как дверь зовут на денежном пути
    (``check_portfolio_health(state)``) против того же зова с включёнными осями.
    Род §17 присваивается по ДЕНЕЖНОМУ ПУТИ — он и есть предмет вопроса.
    """
    rows, err = _peg_rows(axes)
    if err or rows is None:
        return {"kind": UNMEASURED, "reason": err, "door": "money_path"}
    money = _ask_book(policy, rows, axes_on=False)
    with_axes = _ask_book(policy, rows, axes_on=True)
    out: Dict[str, Any] = {"door": "money_path", "pool_count": 3,
                           "exposure_pct": 30.0,
                           "money_path": money, "book_axes_on": with_axes}
    unfit = scene_unfit_reason(money)
    if unfit:
        # База НЕ одобрена денежным зовом ⇒ сцена спутана. Это НЕ находка.
        return {**out, "kind": UNMEASURED, "reason": unfit}
    kind, detail = classify_independence(money, with_axes, ("PEG", "peg"))
    # `classify` сравнил ФОРМЫ ЗОВА: шевельнулось ⇒ ось сводит ведро, но
    # сводит она его ТОЛЬКО во второй форме. Род денежного пути — обратный.
    out["axes_on_kind"] = kind
    out["axes_on_detail"] = {k: v for k, v in detail.items()
                             if k not in ("base", "shifted")}
    if kind == "bucketed_together":
        out["kind"] = "independence_assumed"
        out["reason"] = ("ось сводит ведро только при `check_axes=True`; "
                         "денежный путь зовёт дверь без него")
    elif kind == UNMEASURED:
        out["kind"] = UNMEASURED
        out["reason"] = detail.get("reason")
    else:
        # Вердикт не шевельнулся ни в одной форме ⇒ ведро не сводится нигде.
        out["kind"] = "independence_assumed"
        out["reason"] = "вердикт не шевельнулся ни в одной форме зова"
    return out


def probe_bridge_axis(policy: Any, axes: Dict[str, Any]) -> Dict[str, Any]:
    """Bridge-зависимость: ось есть, а делящую её пару назвать НЕЧЕМ.

    Третий исход здесь — не украшение. Ось ``check_bridge_axis`` существует и
    считает долю по списку ``BRIDGE_PROTOCOLS``, но ни один ключ живого реестра
    этому списку не соответствует: пулов, делящих bridge-зависимость, книга
    держать не может, и «ведра независимы» было бы ответом о выдуманной книге.
    """
    bridge = axes.get("BRIDGE") or []
    matcher = axes.get("_matches")
    con, err = contracts()
    if err:
        return {"kind": UNMEASURED, "reason": err, "door": "money_path"}
    if not bridge:
        return {"kind": UNMEASURED, "door": "money_path",
                "reason": "канонический список BRIDGE_PROTOCOLS пуст"}
    if matcher is None:
        return {"kind": UNMEASURED, "door": "money_path",
                "reason": "канонический матчер risk_axes не ввезён"}
    matched = [k for k in con.get("registry_keys", ()) if matcher(k, bridge)]
    if len(matched) < 2:
        return {"kind": "pair_not_namable", "door": "money_path",
                "list": bridge, "registry_matched": matched,
                "reason": ("ось bridge существует, но ключей реестра, делящих её, "
                           f"меньше двух: {matched or 'ни одного'} — пару, делящую "
                           "зависимость, нельзя назвать, не выдумав её")}
    rows = [(matched[0], "T2", 6_000.0, "ethereum", "USDC"),
            (matched[1], "T2", 6_000.0, "ethereum", "USDC"),
            ("aave_usdc", "T1", 35_000.0, "ethereum", "USDC")]
    money = _ask_book(policy, rows, axes_on=False)
    with_axes = _ask_book(policy, rows, axes_on=True)
    unfit = scene_unfit_reason(money)
    if unfit:
        return {"kind": UNMEASURED, "door": "money_path", "reason": unfit,
                "money_path": money}
    kind, detail = classify_independence(money, with_axes, ("BRIDGE", "bridge"))
    out = {"door": "money_path", "pair": matched[:2],
           "money_path": money, "book_axes_on": with_axes, "axes_on_kind": kind}
    out["kind"] = ("independence_assumed" if kind == "bucketed_together"
                   else (UNMEASURED if kind == UNMEASURED else "independence_assumed"))
    if kind == UNMEASURED:
        out["reason"] = detail.get("reason")
    return out


def probe_not_namable(policy: Any, axes: Dict[str, Any],
                      dep: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Карты зависимости в системе НЕТ — пару назвать нечем.

    Это НЕ «ведра независимы»: выдать отсутствие карты за измеренную
    независимость значило бы соврать в известную сторону. Претензия об
    отсутствии СВЕРЯЕТСЯ замером выразимости (:func:`measure_expressibility`):
    если зависимость хоть где-то называется, род ``pair_not_namable`` — дефект
    ПРИБОРА, и он печатается.
    """
    return {"kind": "pair_not_namable", "door": "admission",
            "reason": ("карты зависимости в системе нет: ни параметра двери, ни "
                       "поля книги, ни ключа карты реестра, ни оси риска")}


PROBES: Dict[str, Any] = {
    "protocol_family": probe_protocol_family,
    "chain_shared": probe_chain_shared,
    "peg_axis": probe_peg_axis,
    "bridge_axis": probe_bridge_axis,
    "not_namable": probe_not_namable,
}


# ---------------------------------------------------------------------------
# Форма зова двери книги на ДЕНЕЖНОМ ПУТИ — AST, а не чтение глазами.
# ---------------------------------------------------------------------------

def money_path_axis_call_forms(root: Optional[Path] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """С какими ключевыми аргументами денежный путь зовёт дверь книги.

    Меряется AST'ом: подстрока ``check_axes`` в файле сказала бы лишь, что слово
    где-то есть, а вопрос — передано ли оно ИМЕННО В ЭТОМ зове. Файла нет ⇒
    третий исход с названной причиной, а не «осей нет».
    """
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    out: List[Dict[str, Any]] = []
    missing: List[str] = []
    for rel in MONEY_PATH_FILES:
        path = base / rel
        if not path.exists():
            missing.append(str(rel))
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return [], f"{rel}: не разобран: {type(exc).__name__}: {exc}"
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute)
                    and fn.attr == "check_portfolio_health"):
                continue
            kw = sorted(k.arg for k in node.keywords if k.arg)
            axes_on = any(
                k.arg == "check_axes"
                and isinstance(k.value, ast.Constant)
                and k.value.value is True
                for k in node.keywords)
            out.append({"file": rel, "line": node.lineno, "keywords": kw,
                        "axes_on": axes_on})
    if missing and not out:
        return [], f"объявленные места зова не найдены: {', '.join(missing)}"
    if missing:
        return out, f"часть объявленных мест не найдена: {', '.join(missing)}"
    if not out:
        return [], ("в объявленных местах нет ни одного зова "
                    "`check_portfolio_health` — претензия о денежном пути не подтверждена")
    return out, None


# ---------------------------------------------------------------------------
# Население: сколько ключей реестра ДЕЛЯТ зависимость. Карты нет ⇒ не измерено.
# ---------------------------------------------------------------------------

def shared_population() -> Tuple[Dict[str, Any], Optional[str]]:
    """Сколько ключей делят каждую зависимость — по картам, которые ЕСТЬ.

    Шесть зависимостей из десяти карты не имеют вовсе, и их население поэтому
    НЕ ИЗМЕРЕНО, а не ноль (инв. #17).
    """
    out: Dict[str, Any] = {}
    con, err = contracts()
    if err:
        return {}, err
    if family_population is not None:
        fams, ferr = family_population()
        if ferr:
            out["protocol"] = {"unmeasured": ferr}
        else:
            shared = {t: sorted(v) for t, v in fams.items() if len(v) > 1}
            # `family_population` возвращает ТОЛЬКО семейства из двух и более
            # ключей, поэтому сумма по ней есть население СЕМЕЙСТВ, а не
            # реестра. Размер реестра спрашивается у реестра — ярлык обязан
            # называть ровно то, что посчитано.
            try:
                from spa_core.adapters import ADAPTER_REGISTRY
                registry_size: Any = len(ADAPTER_REGISTRY)
            except Exception as exc:  # pragma: no cover
                registry_size = f"НЕ ИЗМЕРЕНО: {type(exc).__name__}: {exc}"
            out["protocol"] = {
                "multi_member_families": {t: len(v) for t, v in sorted(shared.items())},
                "keys_in_multi_member_families": sum(len(v) for v in shared.values()),
                "adapter_registry_size": registry_size,
            }
    else:
        out["protocol"] = {"unmeasured": _SUBJECT_IMPORT_ERROR}
    try:
        from spa_core.adapters.registry import ADAPTER_METADATA
        for axis, field in (("chain", "chain"), ("stablecoin", "asset")):
            counts = collections.Counter(
                (m or {}).get(field) for m in ADAPTER_METADATA.values())
            out[axis] = {"by_value": dict(sorted(
                counts.items(), key=lambda kv: (-kv[1], str(kv[0])))),
                "registry_size": len(ADAPTER_METADATA)}
    except Exception as exc:  # pragma: no cover
        return out, f"карта реестра не прочитана: {type(exc).__name__}: {exc}"
    for dep in DEPENDENCIES:
        out.setdefault(dep["key"], {
            "unmeasured": "карты зависимости в системе нет — население не ноль, а НЕ ИЗМЕРЕНО",
        })
    return out, None


# ---------------------------------------------------------------------------
# Сводка
# ---------------------------------------------------------------------------

def census(root: Optional[Path] = None) -> Dict[str, Any]:
    """Полный замер §17. Падение прибора — НЕ находка (класс ADR-897 п. 2)."""
    report: Dict[str, Any] = {
        "section": "§17 Correlated risk",
        "order": "G948 п. 1",
        "vocab": {
            "EXPRESS_KINDS": list(EXPRESS_KINDS),
            "OBSERVE_KINDS": list(OBSERVE_KINDS),
            "INDEPENDENCE_KINDS": list(INDEPENDENCE_KINDS),
            "DOORS": list(DOORS),
            "CHARGE_KINDS": list(CHARGE_KINDS),
            "SUBJECT_KINDS": list(SUBJECT_KINDS),
        },
        "unmeasured_reasons": [],
        "dependencies": {},
    }
    if _VOCAB_IMPORT_ERROR:
        report["unmeasured_reasons"].append(_VOCAB_IMPORT_ERROR)
    if _SUBJECT_IMPORT_ERROR:
        report["unmeasured_reasons"].append(_SUBJECT_IMPORT_ERROR)
    if not CHARGE_KINDS:
        report["unmeasured_reasons"].append(
            "словарь родов §13 пуст — шкала не ввезена")

    policy, perr = load_policy()
    axes, aerr = load_axes()
    con, cerr = contracts()
    for e in (perr, aerr, cerr):
        if e:
            report["unmeasured_reasons"].append(e)

    calls, call_err = money_path_axis_call_forms(root)
    report["money_path_calls"] = calls
    if call_err:
        report["unmeasured_reasons"].append(f"форма зова денежного пути: {call_err}")
    report["money_path_axes_on"] = (
        None if call_err and not calls else all(c["axes_on"] for c in calls) if calls else None)

    pop, perr2 = shared_population()
    report["population"] = pop
    if perr2:
        report["unmeasured_reasons"].append(f"население: {perr2}")

    for dep in DEPENDENCIES:
        row: Dict[str, Any] = {"owner_words": dep["owner_words"],
                               "why": dep["why"], "source": dep["source"]}
        if policy is None or not con:
            row["express"] = {"kind": UNMEASURED}
            row["observe"] = {"kind": UNMEASURED}
            row["independence"] = {"kind": UNMEASURED,
                                   "reason": perr or cerr or "двери не ввезены"}
            report["dependencies"][dep["key"]] = row
            continue
        row["express"] = measure_expressibility(dep, con, axes, root)
        row["observe"] = measure_observation(dep, con, axes)
        probe = PROBES.get(dep["probe"])
        if probe is None:
            row["independence"] = {"kind": UNMEASURED,
                                   "reason": f"пробы {dep['probe']!r} нет в реестре"}
        else:
            try:
                row["independence"] = (probe(policy, axes, dep)
                                       if dep["probe"] == "not_namable"
                                       else probe(policy, axes))
            except Exception as exc:
                row["independence"] = {
                    "kind": UNMEASURED,
                    "reason": f"проба упала: {type(exc).__name__}: {exc}"}
        # Претензия «назвать нечем» СВЕРЯЕТСЯ с замером выразимости.
        if (row["independence"].get("kind") == "pair_not_namable"
                and row["express"]["kind"] != "absent"
                and dep["probe"] == "not_namable"):
            row["independence"]["phantom"] = (
                "зависимость называется у "
                f"{row['express']['kind']} — «назвать нечем» есть дефект прибора")
        report["dependencies"][dep["key"]] = row

    kinds = collections.Counter(
        r["independence"].get("kind") for r in report["dependencies"].values())
    report["totals"] = {
        "bucketed_together": kinds.get("bucketed_together", 0),
        "independence_assumed": kinds.get("independence_assumed", 0),
        "pair_not_namable": kinds.get("pair_not_namable", 0),
        "unmeasured": kinds.get(UNMEASURED, 0),
    }
    report["phantoms"] = sorted(
        k for k, r in report["dependencies"].items()
        if r.get("express", {}).get("phantom")
        or r.get("observe", {}).get("phantom")
        or r.get("independence", {}).get("phantom"))
    return report


def verdict_code(report: Dict[str, Any]) -> int:
    """0 — измерено и находок нет · 1 — НАХОДКА · 2 — НЕ ИЗМЕРЕНО.

    Разведение существенно: падение прибора, прочитанное как находка, — класс
    ADR-897 п. 2, и §16 на него уже наступал.
    """
    if report.get("unmeasured_reasons") or report["totals"]["unmeasured"]:
        return 2
    if (report["totals"]["independence_assumed"]
            or report["totals"]["pair_not_namable"]
            or report.get("phantoms")
            or report.get("money_path_axes_on") is False):
        return 1
    return 0


def render(report: Dict[str, Any]) -> str:
    t = report["totals"]
    lines = [
        "§17 ТЗ владельца «Correlated risk» — десять общих зависимостей "
        "(прибор ЧИТАЕТ, ничего не правит)",
        "",
        f"{'зависимость':<30} {'выразима':<15} {'наблюдение':<17} "
        f"{'ведра':<22} дверь",
    ]
    for dep in DEPENDENCIES:
        r = report["dependencies"][dep["key"]]
        ind = r["independence"]
        lines.append(f"{dep['owner_words']:<30} {r['express']['kind']:<15} "
                     f"{r['observe']['kind']:<17} {ind.get('kind',''):<22} "
                     f"{ind.get('door','')}")
    lines += [
        "",
        f"Итог: сведено в одно ведро {t['bucketed_together']} · "
        f"СЧИТАЮТСЯ НЕЗАВИСИМЫМИ {t['independence_assumed']} · "
        f"пару назвать нечем {t['pair_not_namable']} · "
        f"НЕ ИЗМЕРЕНО {t['unmeasured']}",
    ]
    calls = report.get("money_path_calls") or []
    if calls:
        lines.append("")
        lines.append("Форма зова двери КНИГИ на денежном пути (AST места зова):")
        for c in calls:
            flag = "оси ВКЛЮЧЕНЫ" if c["axes_on"] else "оси ВЫКЛЮЧЕНЫ (умолчание)"
            lines.append(f"  {c['file']}:{c['line']}  kwargs={c['keywords'] or '—'}  → {flag}")
    if report.get("phantoms"):
        lines.append("")
        lines.append("ДЕФЕКТЫ ПРИБОРА (претензия не подтверждена замером): "
                     + ", ".join(report["phantoms"]))
    if report.get("unmeasured_reasons"):
        lines.append("")
        lines.append("НЕ ИЗМЕРЕНО:")
        for r in report["unmeasured_reasons"]:
            lines.append(f"  - {r}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Перепись десяти общих зависимостей §17 (ЧИТАЕТ, не правит)")
    ap.add_argument("--json", action="store_true", help="печатать замер как JSON")
    ap.add_argument("--repo-root", default=None,
                    help="дерево, у которого спрашивать форму зова денежного пути "
                         "(умолчание — дерево этого модуля; выбор ПЕЧАТАЕТСЯ)")
    args = ap.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root else None
    if args.repo_root:
        print(f"дерево НАЗВАНО: {root}", file=sys.stderr)
    else:
        print(f"дерево по умолчанию: {Path(__file__).resolve().parents[2]}",
              file=sys.stderr)
    try:
        report = census(root)
    except Exception as exc:  # падение прибора — код 2, НЕ находка
        print(f"НЕ ИЗМЕРЕНО: прибор упал: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str)
          if args.json else render(report))
    return verdict_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
