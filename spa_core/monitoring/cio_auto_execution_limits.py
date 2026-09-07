"""cio_auto_execution_limits.py — §41 ТЗ «Portfolio CIO»: какие из названных
владельцем ограничений auto-execution реально стоя́т на пути решения, и на какой
именно поверхности каждое из них связывает.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §41 «Auto-execution limits»::

    Если будет разрешен auto-execution, предусмотреть:
    max trade amount · max % portfolio per rebalance · max daily turnover ·
    allowed protocols · allowed vaults · allowed tiers · allowed chains ·
    allowed assets · minimum expected net gain · minimum confidence ·
    minimum persistence · maximum acceptable risk delta.
    Все policy-configurable.

Двенадцать величин названы ВЛАДЕЛЬЦЕМ, а не нами; порядок и формулировки — его.
И требований здесь ДВА, как и в §42: «ограничение есть» и «ограничение
**policy-configurable**». Их легко слить в один вопрос и ответить «лимиты есть» —
а это ответ не на то. Поэтому оси меряются по отдельности:

* **ось «применяется ли вообще»** — варьируется ВЕЛИЧИНА ВЛАДЕЛЬЦА на сцене
  (сумма сделки, доля оборота, тир, сеть, актив…), и смотрится, меняется ли
  вердикт поверхности. Меняется ⇒ величина спрашивается;
* **ось «policy-configurable»** — варьируется ОБЪЯВЛЕННОЕ ПОЛЕ ПОЛИТИКИ
  (``RiskConfig`` / ``TriggerParams``), и смотрится то же самое. Меняется ⇒
  у владельца есть ручка, а не литерал в коде.

Принадлежность поля к политике не объявляется модулем, а МЕРЯЕТСЯ:
``dataclasses.fields`` обоих контрактов (см. :func:`_declared_policy_fields`).

🪤 ЛОВУШКА, ради которой этот модуль вообще устроен так, а не проще
==================================================================
**Ограничение может связывать на ОДНОЙ поверхности решения и не связывать на
другой, и замер по одной из них даст ВЕРНЫЙ ответ на НЕ ТОТ вопрос.**

Замер 07.09 (цикл #509, карточка `inbox-41-priemki-tz-cio-auto-execution-limits`):
T3 суммарно 25 % проходит ``_apply_risk_policy_gate`` с НУЛЁМ нарушений, хотя
``RiskConfig.max_total_t3_allocation = 0.15`` объявлено (ADR-020). Вывод
«объявленное поле не связывает» был бы НЕВЕРЕН: поле читает аллокатор
(``_enforce_t3_total_cap``). Потолок связывает у того, кто ПРЕДЛАГАЕТ, а не у
того, кто ДОПУСКАЕТ. То же с сетями: гейт на смену ``chain`` не реагирует никак,
а у аллокатора есть ``SINGLE_CHAIN_CAP`` / ``L2_TOTAL_CAP`` / ``BASE_CHAIN_CAP``
(ADR-136).

Поэтому каждое ограничение меряется на ВСЕХ трёх поверхностях, через которые
проходит решение о движении денег, и отчёт НАЗЫВАЕТ, на какой оно связывает:

``allocator``
    что вообще предлагается — потолки ``StrategyAllocator`` (``_enforce_*``) и
    классовый гейт допуска ``_adapter_class_gate`` (ADR-061).
``economics``
    стои́т ли предложенный ход своих издержек — ``rebalance_economics.evaluate``
    с порогами ``TriggerParams`` (ADR-060 §3). Именно здесь живёт «переходить
    ли прямо сейчас».
``gate``
    допустима ли получившаяся книга — ``_apply_risk_policy_gate`` над
    ``RiskPolicy v1.0``.

Пять исходов на ограничение, и три средних — самостоятельные
============================================================
``BINDING``
    величина владельца спрашивается И порог, который её судит, — объявленное
    поле политики. Ровно то, что просит §41.
``LITERAL``
    величина спрашивается, вердикт от неё меняется, но повернуть порог владельцу
    нечем: число или признак зашиты в коде. Ограничение есть, ручки нет.
``DECLARED_INERT``
    поле политики объявлено, а величина на пути решения НЕ спрашивается. Самая
    опасная середина: в конфигурации ручка видна, и по ней легко заключить, что
    ограничение работает (аналог ``CONFLATED`` из §42).
``ABSENT``
    ни одна поверхность на величину не реагирует, и поля политики нет.
``UNCHECKED``
    измерить не удалось, причина названа. Не ноль и не скип.

Живой ``data/`` не читается и не пишется (кроме собственного отчёта)
===================================================================
Все пробы идут над сценами из литералов во ВРЕМЕННЫХ каталогах состояния.
Иначе вердикт отвечал бы на вопрос о сегодняшнем хосте, а не о коде. Проверено
отдельно: ``_adapter_class_gate`` и ``tier_map.tier_of`` читают ``ADAPTER_REGISTRY``
— КОНСТАНТУ КОДА, а не файл состояния, поэтому их ответы от каталога не зависят
(замер: те же ответы при пустом и при боевом ``data/``).

Положительный контроль — условие ВСЕГО отчёта, а не украшение
==============================================================
«Ограничение не сработало» ничего не значит, если на этой поверхности не
срабатывает НИЧЕГО — сломанная проба и отсутствующее ограничение выглядят
одинаково. Поэтому счёт читается, только если выполнены ОБА условия:

1. на здоровой сцене все три поверхности РАЗРЕШАЮТ ход (гейт одобряет,
   экономика говорит ``ACT``, потолки аллокатора не срезают) — иначе переход
   «разрешено → запрещено» показать нечем;
2. на КАЖДОЙ из трёх поверхностей хотя бы одно ограничение измерено ``BINDING`` —
   иначе «поверхность не реагирует» произносилось бы и в мире, где не работает
   сама проба.

Не выполнено — ``control.passed = False``, ``overall = UNCHECKED``, счёт по
ограничениям читать нельзя.

Что НЕ утверждается этим модулем
================================
* «Ограничения нет» ≠ «ограничения нет в дереве». ``spa_core/execution/router.py``
  несёт ``allowed_chains`` и ``blacklisted_protocols``, но read-only путь его НЕ
  импортирует по инварианту 6. «Ограничение есть в дереве» и «ограничение стои́т
  на пути решения» — разное, и меряется здесь второе.
* Покрытие ветвей. Модуль судит о ФУНКЦИЯХ пути решения, а не о том, доходит ли
  до каждой из них живой цикл в каждом случае. Известный пример — уже найденная
  и записанная слепота ``if name in seen_protocols: continue`` перед
  ``_adapter_class_gate`` (``data/pool_identity_collision.json``); второй раз она
  здесь не «находится».

ADVISORY. Ни один порог этим модулем не меняется и ни одно недостающее
ограничение не строится: дать auto-execution новый лимит — money-path и решение
владельца, а не строка замера.
"""

from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/cio_auto_execution_limits.json"

#: Исходы на ограничение.
BINDING = "BINDING"
LITERAL = "LITERAL"
DECLARED_INERT = "DECLARED_INERT"
ABSENT = "ABSENT"
UNCHECKED = "UNCHECKED"

#: Три поверхности решения, в порядке прохождения капитала.
SURFACES = ("allocator", "economics", "gate")

#: Капитал сцены. Не порог и ничего не решает — все доли ниже выводятся из него
#: же, поэтому число можно менять, не меняя смысла ни одной пробы.
_SCENE_CAPITAL_USD = 100_000.0

#: Множитель капитала для пробы «та же ДОЛЯ, другая СУММА». Отвечает на вопрос
#: владельца про `max trade amount` — он назвал СУММУ, а не долю.
_SCALE_FACTOR = 100.0

#: Файл аллокатора — источник для разбора происхождения его потолков.
_ALLOCATOR_REL = "spa_core/allocator/allocator.py"


# ─────────────────────── что вообще объявлено политикой ─────────────────────

def _declared_policy_fields() -> dict[str, set[str]]:
    """Поля ДВУХ объявленных контрактов политики — измерением, не списком.

    ``RiskConfig`` (``spa_core/risk/policy.py``, RiskPolicy v1.0) и
    ``TriggerParams`` (``rebalance_economics``, ADR-060 §3) — единственные два
    места, где порог является ОБЪЯВЛЕННЫМ решением владельца, а не числом в
    коде. Список полей берётся из ``dataclasses.fields``: перечислить их руками
    значило бы, что отчёт устареет молча при первом же новом поле.
    """
    out: dict[str, set[str]] = {"RiskConfig": set(), "TriggerParams": set()}
    try:
        from spa_core.risk.policy import RiskConfig
        out["RiskConfig"] = {f.name for f in dataclasses.fields(RiskConfig)}
    except Exception:  # noqa: BLE001 — нечитаемый контракт = пустое множество
        pass
    try:
        from spa_core.allocator.rebalance_economics import TriggerParams
        out["TriggerParams"] = {f.name for f in dataclasses.fields(TriggerParams)}
    except Exception:  # noqa: BLE001
        pass
    return out


def _allocator_cap_origin(root: str) -> dict[str, str | None]:
    """Потолок аллокатора → имя поля политики, из которого он взят (или ``None``).

    Разбор дерева, а не поиск подстроки. Нужен потому, что «ручка повернулась»
    ещё не означает «ручка владельца»: атрибут класса мог бы нести литерал, и
    тогда её поворот в пробе доказывал бы только то, что проба умеет писать в
    атрибут. Здесь измеряется ПРОИСХОЖДЕНИЕ значения:
    ``_POLICY_CONFIG.max_total_t2_allocation`` и
    ``getattr(_POLICY_CONFIG, "max_total_t3_allocation", 0.15)`` — оба дают имя
    поля; голый литерал не даёт ничего.

    ⚠️ Неразобранный файл — **не пустой ответ**, а отсутствие измерения, и
    отвечает за это :func:`_allocator_source_error`. Первая редакция возвращала
    здесь ``{}``, и это был fail-OPEN в сторону ЛОЖНОЙ НАХОДКИ: без имён полей
    пробы аллокатора теряли ``policy_field``, и `allowed tiers` вместе с
    `allowed chains` молча съезжали с ``BINDING`` на ``LITERAL`` — то есть отчёт
    объявлял бы «порог зашит в коде» про потолки, которые как раз читаются из
    ``RiskConfig``. Поймано на прогоне с ``root``, где лежит только ``data/``
    (мост зовёт ``run(root=args.root)``, и такой корень возможен).
    """
    out: dict[str, str | None] = {}
    try:
        tree = ast.parse((Path(root) / _ALLOCATOR_REL).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return out

    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        for node in cls.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name, value = node.target.id, node.value
            elif (isinstance(node, ast.Assign) and len(node.targets) == 1
                  and isinstance(node.targets[0], ast.Name)):
                name, value = node.targets[0].id, node.value
            else:
                continue
            if value is None or not name.isupper():
                continue
            out[name] = _policy_field_in(value)
    return out


def _allocator_source_error(root: str) -> str:
    """Причина, по которой источник аллокатора не прочитан, либо пустая строка.

    Отдельный вопрос отдельным измерением: «в файле нет полей политики» и «файла
    нет» — разные ответы, и слить их значило бы выдать несостоявшийся замер за
    находку.
    """
    path = Path(root) / _ALLOCATOR_REL
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return (f"источник аллокатора не разобран ({path}): "
                f"{type(exc).__name__}: {exc}")
    return ""


def _policy_field_in(node: ast.AST) -> str | None:
    """Имя поля ``_POLICY_CONFIG``, встреченное в выражении, либо ``None``."""
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Attribute)
                and isinstance(sub.value, ast.Name)
                and sub.value.id == "_POLICY_CONFIG"):
            return sub.attr
        if (isinstance(sub, ast.Call)
                and getattr(sub.func, "id", None) == "getattr"
                and len(sub.args) >= 2
                and getattr(sub.args[0], "id", None) == "_POLICY_CONFIG"
                and isinstance(sub.args[1], ast.Constant)
                and isinstance(sub.args[1].value, str)):
            return sub.args[1].value
    return None


# ───────────────────────────── поверхность: gate ────────────────────────────

def _gate_adapters(spec: list[dict]) -> list[dict]:
    """Снимок оркестратора для сцены. TVL всегда живой и с запасом над полом:
    иначе вердикт решала бы ADR-053-заморозка, а не измеряемое ограничение."""
    from spa_core.risk.policy import RiskConfig
    floor = float(RiskConfig().min_tvl_usd)
    out = []
    for s in spec:
        out.append({
            "protocol": s["protocol"],
            "apy_pct": s.get("apy_pct", 6.0),
            "tvl_usd": floor * 20.0,
            "tier": s.get("tier", "T1"),
            "chain": s.get("chain", "ethereum"),
            "asset": s.get("asset", "USDC"),
            "pool_id": s.get("pool_id", s["protocol"]),
            "apy_source": "live",
            "tvl_source": "live",
        })
    return out


def _gate_verdict(target: dict[str, float], spec: list[dict], *,
                  capital_usd: float = _SCENE_CAPITAL_USD,
                  held: dict[str, float] | None = None) -> str:
    """Вердикт гейта как СРАВНИМАЯ строка: допуск + книга, которую он пропустил.

    Судить по тексту нарушений нельзя — он несёт числа сцены и «изменился» бы от
    любого шевеления величины. Судится то, что решает деньги: одобрено ли и
    сколько куда в итоге ушло (гейт умеет срезать, не отказывая).
    """
    from spa_core.paper_trading.risk_gate import _apply_risk_policy_gate
    with tempfile.TemporaryDirectory(prefix="cio_ael_gate_") as tmp:
        res = _apply_risk_policy_gate(
            dict(target), capital_usd, _gate_adapters(spec),
            ddir=Path(tmp), current_positions=dict(held or {}),
        )
    book = {k: round(float(v), 2) for k, v in sorted((res.get("target_usd") or {}).items())}
    return f"approved={bool(res.get('approved'))}|err={res.get('error') is not None}|book={book}"


def _with_risk_config(**overrides: Any) -> Any:
    """Контекст, в котором ``RiskPolicy()`` строится на изменённой политике.

    Гейт зовёт ``RiskPolicy()`` без аргументов, поэтому единственная дверь к его
    порогам — модульное имя ``RiskConfig``. Подменяется фабрика, а не значения
    полей: подмена значений на замороженном dataclass'е тихо не сработала бы, и
    проба объявила бы «ручка мёртвая», измерив собственную ошибку.
    """
    import contextlib
    import spa_core.risk.policy as pol

    @contextlib.contextmanager
    def _ctx():
        original = pol.RiskConfig
        patched = dataclasses.replace(original(), **overrides)
        pol.RiskConfig = lambda: patched   # noqa: E731
        try:
            yield
        finally:
            pol.RiskConfig = original
    return _ctx()


# ────────────────────────── поверхность: economics ──────────────────────────

def _econ_scene(**over: Any) -> dict:
    """Здоровая сцена «переложить десятую часть капитала в вдвое лучший пул».

    Ни одна доля здесь ничего не решает: проба смотрит на ПЕРЕХОД ``ACT``↔``HOLD``,
    а не на конкретное число. Возраст позиций и давность последнего хода поданы
    ЯВНО и с большим запасом — без них сцена не доставала бы до ``min_hold_days``
    и ``act_cooldown_days``, и «не изменил вердикт» было бы выдано за «ручка
    мёртвая» (предупреждение карточки #509).
    """
    cap = _SCENE_CAPITAL_USD
    scene: dict[str, Any] = {
        "current_positions": {"aave_v3": 0.40 * cap, "pendle": 0.10 * cap},
        "target_positions": {"aave_v3": 0.30 * cap, "pendle": 0.20 * cap},
        "apy_pct": {"aave_v3": 2.0, "pendle": 12.0},
        "evidenced": {"aave_v3", "pendle"},
        "chains": {"aave_v3": "ethereum", "pendle": "ethereum"},
        "capital_usd": cap,
        "days_since_last_act": 99.0,
        "position_age_days": {"aave_v3": 99.0, "pendle": 99.0},
        "turnover_last_week_usd": 0.0,
        "tvl_evidenced": {"aave_v3", "pendle"},
    }
    scene.update(over)
    return scene


def _econ_verdict(scene: dict, params: Any = None) -> str:
    """``ACT`` или ``HOLD`` — то самое «переходить ли прямо сейчас»."""
    from spa_core.allocator import rebalance_economics as economics
    kwargs = dict(scene)
    if params is not None:
        kwargs["params"] = params
    return str(economics.evaluate(**kwargs).decision)


def _trigger_params(**overrides: Any) -> Any:
    from spa_core.allocator.rebalance_economics import TriggerParams
    return TriggerParams(**overrides)


# ────────────────────────── поверхность: allocator ──────────────────────────

def _allocator() -> Any:
    """Аллокатор на ПУСТЫХ временных путях: живое состояние не участвует."""
    from spa_core.allocator.allocator import StrategyAllocator
    tmp = Path(tempfile.mkdtemp(prefix="cio_ael_alloc_"))
    (tmp / "status.json").write_text("{}", encoding="utf-8")
    (tmp / "registry.json").write_text("{}", encoding="utf-8")
    return StrategyAllocator(
        status_path=tmp / "status.json", registry_path=tmp / "registry.json",
        strategy_loop_enabled=False, live_apy_provider=False,
    )


def _alloc_weights_verdict(fn_name: str, weights: dict[str, float],
                           **caps: float) -> str:
    """Раскладка ПОСЛЕ потолка аллокатора, при желании — с повёрнутой ручкой.

    ``caps`` ставятся атрибутом ЭКЗЕМПЛЯРА: атрибут класса вычислен из
    ``_POLICY_CONFIG`` в момент импорта, и позднее изменение поля политики до
    него уже не доходит. Что повёрнутая ручка — ручка ВЛАДЕЛЬЦА, а не литерал,
    отвечает отдельным измерением :func:`_allocator_cap_origin`.
    """
    alloc = _allocator()
    for name, value in caps.items():
        setattr(alloc, name, value)
    out = getattr(alloc, fn_name)(dict(weights))
    result = out[0] if isinstance(out, tuple) else out
    return json.dumps({k: round(float(v), 6) for k, v in sorted(result.items())},
                      ensure_ascii=False)


def _t3_probe_keys() -> list[str]:
    """Ключи, которые КАНОНИЧЕСКАЯ карта тиров считает T3, — найденные, не вшитые.

    ``_enforce_t3_total_cap`` классифицирует через ``tier_map.tier_of``, а не
    через переданные строки тиров, поэтому имена для пробы надо ДОБЫТЬ. Не
    нашлось ⇒ пусто ⇒ ``UNCHECKED`` с названной причиной: судить о потолке T3
    по ключу, который картой в T3 не считается, значит мерить свою выдумку.

    Ключей нужно ДВА, и это не придирка. Предмет §41 здесь — потолок на ТИР
    ЦЕЛИКОМ (``max_total_t3_allocation`` = 15 %), а не потолок на протокол
    (20 %). Положи 25 % в ОДИН пул — и гейт откажет по концентрации, то есть
    ответит про совсем другое ограничение, а замер запишет этот отказ в актив
    суммарному потолку, которого у гейта нет. Ровно так первая редакция этой
    пробы и ошиблась; поймал её тест ``test_t3_total_cap_passes_the_gate_untouched``.
    Поэтому 25 % раскладываются на два пула по 15 % и 10 % — каждый НИЖЕ
    потолка на протокол, а сумма ВЫШЕ потолка на тир.
    """
    try:
        from spa_core.adapters.tier_map import tier_of
        from spa_core.adapters import ADAPTER_REGISTRY
    except Exception:  # noqa: BLE001
        return []
    out: list[str] = []
    for entry in ADAPTER_REGISTRY:
        try:
            name = str(entry[0])
        except Exception:  # noqa: BLE001
            continue
        if str(tier_of(name) or "").upper() == "T3" and name not in out:
            out.append(name)
    return out


# ─────────────────────────────── контроль ───────────────────────────────────

def _healthy_baselines() -> dict:
    """Три здоровых вердикта — точка отсчёта для КАЖДОЙ пробы ниже."""
    spec = [{"protocol": "aave_v3", "tier": "T1", "apy_pct": 4.0},
            {"protocol": "pendle", "tier": "T2", "apy_pct": 8.0}]
    target = {"aave_v3": 0.30 * _SCENE_CAPITAL_USD, "pendle": 0.15 * _SCENE_CAPITAL_USD}
    return {
        "gate": _gate_verdict(target, spec),
        "gate_spec": spec,
        "gate_target": target,
        "economics": _econ_verdict(_econ_scene()),
        "allocator_chain": _alloc_weights_verdict(
            "_enforce_chain_caps", {"aave_v3": 0.40, "pendle": 0.20}),
    }


def _control_ok(baseline: dict) -> tuple[bool, str]:
    """Разрешает ли здоровая сцена ход на ВСЕХ трёх поверхностях."""
    if not baseline["gate"].startswith("approved=True|err=False"):
        return False, ("здоровая сцена не одобрена гейтом "
                       f"({baseline['gate']}) — перехода «разрешено → запрещено» "
                       "показать нечем")
    if baseline["economics"] != "ACT":
        return False, ("здоровая сцена не даёт ACT у экономики "
                       f"({baseline['economics']}) — переход показать нечем")
    untouched = json.dumps({"aave_v3": 0.4, "pendle": 0.2}, ensure_ascii=False)
    if baseline["allocator_chain"] != untouched:
        return False, ("здоровая раскладка уже срезается сетевыми потолками "
                       f"({baseline['allocator_chain']}) — переход показать нечем")
    return True, ""


# ────────────────────────────── сами пробы ──────────────────────────────────
#
# Каждая проба возвращает список записей вида::
#
#     {"surface", "axis", "changed", "detail", ["policy_field", "declared_in"]}
#
# ``axis="quantity"`` — варьировали ВЕЛИЧИНУ ВЛАДЕЛЬЦА;
# ``axis="threshold"`` — варьировали ОБЪЯВЛЕННОЕ ПОЛЕ ПОЛИТИКИ.

def _rec(surface: str, axis: str, changed: bool, detail: str,
         policy_field: str | None = None, declared_in: str | None = None,
         gap: str | None = None) -> dict:
    """Одна запись пробы.

    ``gap`` — то, ради чего этот модуль вообще устроен сложнее одной таблицы:
    строка, называющая, чего именно ЭТА поверхность про ЭТУ величину НЕ делает,
    даже когда про соседнюю величину она отвечает исправно. Без неё
    «ограничение связывает» и «ограничение связывает наполовину» слились бы в
    один зелёный ответ, а разница между ними — та самая, ради которой владелец
    перечислил двенадцать величин, а не написал «поставьте лимиты».
    """
    out = {"surface": surface, "axis": axis, "changed": bool(changed),
           "detail": detail}
    if policy_field:
        out["policy_field"] = policy_field
        out["declared_in"] = declared_in or ""
    if gap:
        out["gap"] = gap
    return out


def _probe_max_trade_amount(base: dict, fields: dict, origins: dict) -> list[dict]:
    """Сумма сделки: та же ДОЛЯ капитала, в ``_SCALE_FACTOR`` раз больше денег.

    Владелец назвал СУММУ (`max trade amount`), а не долю. Если хоть где-то
    стои́т абсолютный потолок в долларах, книга, увеличенная целиком, перестанет
    проходить — доли-то не изменились.
    """
    k = _SCALE_FACTOR
    scaled = {kk: v * k for kk, v in base["gate_target"].items()}
    gate_scaled = _gate_verdict(scaled, base["gate_spec"],
                                capital_usd=_SCENE_CAPITAL_USD * k)
    econ_scene = _econ_scene(
        current_positions={p: v * k for p, v in _econ_scene()["current_positions"].items()},
        target_positions={p: v * k for p, v in _econ_scene()["target_positions"].items()},
        capital_usd=_SCENE_CAPITAL_USD * k,
    )
    econ_scaled = _econ_verdict(econ_scene)
    usd_fields = sorted(n for n in fields["RiskConfig"] | fields["TriggerParams"]
                        if n.endswith("_usd"))
    return [
        _rec("gate", "quantity",
             not gate_scaled.startswith("approved=True"),
             f"нога ×{k:g} (${scaled['aave_v3']:,.0f} вместо "
             f"${base['gate_target']['aave_v3']:,.0f}) при той же доле: {gate_scaled}"),
        _rec("economics", "quantity", econ_scaled != base["economics"],
             f"ход ×{k:g} (${0.10 * _SCENE_CAPITAL_USD * k:,.0f}) при той же "
             f"доле 10 %: {econ_scaled}"),
        _rec("economics", "threshold", False,
             "полей политики, выраженных в долларах и относящихся к РАЗМЕРУ "
             f"СДЕЛКИ, не объявлено; всё, что в долларах вообще: {usd_fields} "
             "(это порог TVL пула, а не сделки)"),
    ]


def _probe_pct_per_rebalance(base: dict, fields: dict, origins: dict) -> list[dict]:
    """Доля капитала за один ребаланс."""
    big = _econ_scene(
        current_positions={"aave_v3": 0.40 * _SCENE_CAPITAL_USD, "pendle": 0.10 * _SCENE_CAPITAL_USD},
        target_positions={"aave_v3": 0.05 * _SCENE_CAPITAL_USD, "pendle": 0.45 * _SCENE_CAPITAL_USD},
    )
    v_big = _econ_verdict(big)
    v_dial = _econ_verdict(_econ_scene(), _trigger_params(max_turnover_per_move=0.01))
    return [
        _rec("economics", "quantity", v_big != base["economics"],
             f"оборот 10 % → 35 % капитала: {base['economics']} → {v_big}"),
        _rec("economics", "threshold", v_dial != base["economics"],
             f"max_turnover_per_move 0.15 → 0.01: {base['economics']} → {v_dial}",
             "max_turnover_per_move", "TriggerParams"),
        _rec("gate", "quantity", False,
             "гейт судит КНИГУ, а не ход: понятия оборота у него нет "
             "(в сигнатуре `_apply_risk_policy_gate` нет ни одного входа о размере хода)"),
    ]


def _probe_daily_turnover(base: dict, fields: dict, origins: dict) -> list[dict]:
    """Дневной оборот — и чем он у нас НЕ является.

    Владелец назвал ДНЕВНОЕ окно. У ``evaluate`` вход про уже совершённый оборот
    ровно один — ``turnover_last_week_usd``, и он недельный. Проба честно
    показывает: сумма, уже прокрученная СЕГОДНЯ, не спрашивается ничем — вход,
    в который её можно было бы подать, отсутствует.
    """
    import inspect
    from spa_core.allocator.rebalance_economics import evaluate
    params = set(inspect.signature(evaluate).parameters)
    daily_inputs = sorted(p for p in params if "day" in p or "daily" in p)
    turnover_inputs = sorted(p for p in params if "turnover" in p)
    week_dial = _econ_verdict(_econ_scene(), _trigger_params(max_turnover_per_week=0.01))
    daily_fields = sorted(n for n in fields["RiskConfig"] | fields["TriggerParams"]
                          if "daily" in n and "turnover" in n)
    return [
        _rec("economics", "quantity", False,
             f"входа «оборот за СЕГОДНЯ» у evaluate нет: про оборот принимается "
             f"{turnover_inputs}, про сутки — {daily_inputs} (это давность хода "
             "и возраст позиций, а не сумма оборота за день)"),
        _rec("economics", "threshold", bool(daily_fields),
             f"поля политики про ДНЕВНОЙ оборот: {daily_fields or 'нет'}; "
             f"ближайшее объявленное — max_turnover_per_week (НЕДЕЛЬНОЕ окно), "
             f"и оно связывает: {base['economics']} → {week_dial}"),
    ]


def _probe_allowed_protocols(base: dict, fields: dict, origins: dict) -> list[dict]:
    """Допуск протокола: класс адаптера (ADR-061) против незнакомого имени."""
    from spa_core.allocator.allocator import _adapter_class_gate
    from spa_core.adapters import ADAPTER_REGISTRY

    refused = [(str(e[0]), _adapter_class_gate(str(e[0]))[1])
               for e in ADAPTER_REGISTRY
               if not _adapter_class_gate(str(e[0]))[0]]
    unknown_allowed, unknown_reason = _adapter_class_gate("zzz_protocol_that_does_not_exist")

    spec = [{"protocol": "zzz_protocol_that_does_not_exist", "tier": "T1", "apy_pct": 4.0},
            {"protocol": "pendle", "tier": "T2", "apy_pct": 8.0}]
    target = {"zzz_protocol_that_does_not_exist": 0.30 * _SCENE_CAPITAL_USD,
              "pendle": 0.15 * _SCENE_CAPITAL_USD}
    gate_unknown = _gate_verdict(target, spec)
    return [
        _rec("allocator", "quantity", bool(refused),
             f"_adapter_class_gate (ADR-061) ОТКАЗЫВАЕТ {len(refused)} из "
             f"{len(ADAPTER_REGISTRY)} ключей реестра, напр. "
             f"{[f'{n} ({r})' for n, r in refused[:3]]}"),
        _rec("allocator", "quantity", not unknown_allowed,
             f"незнакомое имя протокола: allowed={unknown_allowed} "
             f"reason={unknown_reason!r} — списка разрешённых нет, отказ идёт от "
             "ОБЪЯВЛЕННОГО КЛАССА адаптера, поэтому имени вне реестра отказать нечем"),
        _rec("allocator", "threshold", False,
             "признак допуска — атрибут класса адаптера (IS_ADVISORY / "
             "RESEARCH_ONLY / is_gsm_compliant), а не поле RiskConfig или "
             "TriggerParams: повернуть его владельцу нечем"),
        _rec("gate", "quantity", not gate_unknown.startswith("approved=True"),
             f"незнакомый протокол на 30 % книги у гейта: {gate_unknown}"),
    ]


def _probe_allowed_vaults(base: dict, fields: dict, origins: dict) -> list[dict]:
    """Допуск конкретного волта: тождество по адресу пула, а не по имени."""
    spec = [dict(s, pool_id=f"0xDEADBEEF{i}") for i, s in enumerate(base["gate_spec"])]
    changed = _gate_verdict(base["gate_target"], spec)
    vault_fields = sorted(n for n in fields["RiskConfig"] | fields["TriggerParams"]
                          if any(w in n for w in ("vault", "pool", "address")))
    return [
        _rec("gate", "quantity", changed != base["gate"],
             f"подмена pool_id обоих пулов на чужие адреса: вердикт "
             f"{'изменился' if changed != base['gate'] else 'НЕ изменился'} "
             "— гейт волт не спрашивает"),
        _rec("gate", "threshold", bool(vault_fields),
             f"поля политики про волт/пул/адрес: {vault_fields or 'нет'}"),
    ]


def _probe_allowed_tiers(base: dict, fields: dict, origins: dict) -> list[dict]:
    """Тир: и то, что гейт молча выдаёт неизвестному тиру потолок T2."""
    recs: list[dict] = []
    spec_t9 = [dict(base["gate_spec"][0], tier="T9"), base["gate_spec"][1]]
    v_t9 = _gate_verdict(base["gate_target"], spec_t9)
    recs.append(_rec("gate", "quantity", v_t9 != base["gate"],
                     f"тир T1 → T9 на той же книге: {v_t9}"))

    with _with_risk_config(max_concentration_t1=0.10):
        v_dial = _gate_verdict(base["gate_target"], base["gate_spec"])
    recs.append(_rec("gate", "threshold", v_dial != base["gate"],
                     f"max_concentration_t1 0.40 → 0.10: {v_dial}",
                     "max_concentration_t1", "RiskConfig"))

    t3_keys = _t3_probe_keys()
    if len(t3_keys) < 2:
        recs.append(_rec("allocator", "quantity", False,
                         f"НЕ ИЗМЕРЕНО: канонический tier_map назвал ключей T3 "
                         f"{len(t3_keys)}, а суммарный потолок тира требует "
                         "двух — на одном пуле его не отличить от потолка на "
                         "протокол"))
        return recs

    #: 15 % + 10 %: каждый НИЖЕ потолка на протокол (20 %), сумма ВЫШЕ потолка
    #: на тир (15 %). Только такая раскладка спрашивает про суммарный потолок.
    a, b = t3_keys[0], t3_keys[1]
    weights = {a: 0.15, b: 0.10, "aave_v3": 0.40}
    untouched = json.dumps({k: round(v, 6) for k, v in sorted(weights.items())},
                           ensure_ascii=False)
    at_default = _alloc_weights_verdict("_enforce_t3_total_cap", weights)
    at_wide = _alloc_weights_verdict("_enforce_t3_total_cap", weights, T3_TOTAL_CAP=0.30)
    origin = origins.get("T3_TOTAL_CAP")
    recs.append(_rec("allocator", "quantity", at_default != untouched,
                     f"T3 суммарно 25 % (`{a}` 15 % + `{b}` 10 %, каждый ниже "
                     f"потолка на протокол): {at_default}"))
    recs.append(_rec("allocator", "threshold", at_wide != at_default,
                     f"T3_TOTAL_CAP 0.15 → 0.30: {at_wide}; происхождение потолка "
                     f"по разбору дерева — {origin or 'ЛИТЕРАЛ'}",
                     origin if origin in fields["RiskConfig"] else None,
                     "RiskConfig" if origin in fields["RiskConfig"] else None))

    spec_t3 = [{"protocol": a, "tier": "T3", "apy_pct": 4.0},
               {"protocol": b, "tier": "T3", "apy_pct": 5.0},
               base["gate_spec"][1]]
    tgt_t3 = {a: 0.15 * _SCENE_CAPITAL_USD, b: 0.10 * _SCENE_CAPITAL_USD,
              "pendle": 0.15 * _SCENE_CAPITAL_USD}
    v_gate_t3 = _gate_verdict(tgt_t3, spec_t3)
    recs.append(_rec("gate", "quantity", not v_gate_t3.startswith("approved=True"),
                     f"та же T3-сумма 25 % у ГЕЙТА: {v_gate_t3}",
                     gap=("суммарный потолок тира — гейт применяет потолок НА "
                          "ПРОТОКОЛ, а объявленный RiskConfig."
                          "max_total_t3_allocation = 15 % читает только "
                          "аллокатор: T3 суммарно 25 % проходит гейт с нулём "
                          "нарушений")))
    recs.append(_rec("gate", "quantity", v_t9 != base["gate"],
                     f"неизвестный тир T9 у гейта: {v_t9}",
                     gap=("незнакомый тир не отвергается, а МОЛЧА получает "
                          "потолок T2 = 20 %: «тир вне списка» и «тир T2» "
                          "неотличимы")))
    return recs


def _probe_allowed_chains(base: dict, fields: dict, origins: dict) -> list[dict]:
    """Сеть: у гейта нет, у аллокатора три потолка (ADR-136/ADR-025)."""
    spec_base = [dict(s, chain="base") for s in base["gate_spec"]]
    v_gate = _gate_verdict(base["gate_target"], spec_base)

    weights = {"aave_v3": 0.40, "moonwell_base": 0.40}
    at_default = _alloc_weights_verdict("_enforce_chain_caps", weights)
    at_wide = _alloc_weights_verdict("_enforce_chain_caps", weights, BASE_CHAIN_CAP=0.90)
    origin = origins.get("BASE_CHAIN_CAP")
    return [
        _rec("gate", "quantity", v_gate != base["gate"],
             f"обе позиции переведены в сеть base: {v_gate}",
             gap=("сеть у гейта не судится вовсе — ни один из трёх объявленных "
                  "сетевых потолков (max_single_chain_allocation, "
                  "max_l2_total_allocation, BASE_CHAIN_CAP) на этой поверхности "
                  "не применяется")),
        _rec("allocator", "quantity",
             at_default != json.dumps({k: round(v, 6) for k, v in sorted(weights.items())},
                                      ensure_ascii=False),
             f"40 % в сети base у аллокатора: {at_default}"),
        _rec("allocator", "threshold", at_wide != at_default,
             f"BASE_CHAIN_CAP 0.20 → 0.90: {at_wide}; происхождение потолка по "
             f"разбору дерева — {origin or 'ЛИТЕРАЛ'}",
             origin if origin in fields["RiskConfig"] else None,
             "RiskConfig" if origin in fields["RiskConfig"] else None),
    ]


def _probe_allowed_assets(base: dict, fields: dict, origins: dict) -> list[dict]:
    """Актив пула (подтверждение ADR-247, а не новая находка)."""
    spec = [dict(base["gate_spec"][0], asset="WBTC"),
            dict(base["gate_spec"][1], asset="DOGE")]
    v = _gate_verdict(base["gate_target"], spec)
    asset_fields = sorted(n for n in fields["RiskConfig"] | fields["TriggerParams"]
                          if "asset" in n or "collateral" in n)
    return [
        _rec("gate", "quantity", v != base["gate"],
             f"актив обоих пулов USDC → WBTC/DOGE: вердикт "
             f"{'изменился' if v != base['gate'] else 'НЕ изменился'} "
             "(подтверждает ADR-247: актив не спрашивается)"),
        _rec("gate", "threshold", bool(asset_fields),
             f"поля политики про актив: {asset_fields or 'нет'}"),
    ]


def _probe_min_net_gain(base: dict, fields: dict, origins: dict) -> list[dict]:
    """Минимальная ожидаемая ЧИСТАЯ выгода — и где в ней «чистая»."""
    weak = _econ_scene(apy_pct={"aave_v3": 2.0, "pendle": 2.4})
    v_weak = _econ_verdict(weak)
    v_dial = _econ_verdict(_econ_scene(), _trigger_params(min_gain_pp=9.0))
    v_cost = _econ_verdict(_econ_scene(), _trigger_params(max_payback_days=0.001))
    return [
        _rec("economics", "quantity", v_weak != base["economics"],
             f"выгода хода 1.00 пп → 0.04 пп: {base['economics']} → {v_weak}"),
        _rec("economics", "threshold", v_dial != base["economics"],
             f"min_gain_pp 0.50 → 9.00: {base['economics']} → {v_dial}",
             "min_gain_pp", "TriggerParams"),
        _rec("economics", "threshold", v_cost != base["economics"],
             f"издержки входят ОТДЕЛЬНЫМ порогом окупаемости, а не вычетом из "
             f"полосы выгоды: max_payback_days 30 → 0.001 даёт "
             f"{base['economics']} → {v_cost}. Полоса `min_gain_pp` сравнивается "
             "с ВАЛОВОЙ прибавкой APY — «чистой» её делает второй порог",
             "max_payback_days", "TriggerParams"),
    ]


def _probe_min_confidence(base: dict, fields: dict, origins: dict) -> list[dict]:
    """Минимальная уверенность = доказанность числа (ADR-061/ADR-060)."""
    from spa_core.allocator import allocator as alloc_mod
    v_unev = _econ_verdict(_econ_scene(evidenced={"aave_v3"}))
    coverage_literals = {
        n: getattr(alloc_mod, n, None)
        for n in ("_EVIDENCE_MIN_COVERAGE", "_EVIDENCE_MIN_COVERAGE_FRACTION",
                  "_EVIDENCE_MAX_AGE_H")
    }
    declared = sorted(n for n in fields["RiskConfig"] | fields["TriggerParams"]
                      if "confidence" in n or "evidence" in n)
    return [
        _rec("economics", "quantity", v_unev != base["economics"],
             f"цель без доказанного числа: {base['economics']} → {v_unev}"),
        _rec("economics", "threshold", False,
             f"порог доказанности — МОДУЛЬНЫЕ ЛИТЕРАЛЫ аллокатора "
             f"{coverage_literals}, не поле политики; всё, что политикой "
             f"объявлено со словом confidence/evidence: {declared} "
             "(var_confidence — про доверительный интервал VaR, не про допуск хода)"),
    ]


def _probe_min_persistence(base: dict, fields: dict, origins: dict) -> list[dict]:
    """Устойчивость ПРЕИМУЩЕСТВА во времени — не путать с возрастом позиции."""
    import inspect
    from spa_core.allocator.rebalance_economics import evaluate
    params = set(inspect.signature(evaluate).parameters)
    time_inputs = sorted(p for p in params
                         if "days" in p or "age" in p or "since" in p)
    v_hold = _econ_verdict(_econ_scene(), _trigger_params(min_hold_days=999))
    persist_fields = sorted(n for n in fields["RiskConfig"] | fields["TriggerParams"]
                            if "persist" in n or "duration" in n)
    return [
        _rec("economics", "quantity", False,
             f"входа «сколько ДЕРЖИТСЯ преимущество целевого пула» у evaluate "
             f"нет: про время принимается {time_inputs} — это возраст НАШЕЙ "
             "позиции и давность НАШЕГО хода, а не длительность выгоды "
             "(подтверждает ADR-248)"),
        _rec("economics", "threshold", bool(persist_fields),
             f"поля политики про устойчивость: {persist_fields or 'нет'}; "
             f"ближайшее по звучанию min_hold_days связывает "
             f"({base['economics']} → {v_hold}), но отвечает на другой вопрос — "
             "как давно ЛЕЖИТ наша позиция",
             "min_hold_days" if persist_fields else None,
             "TriggerParams" if persist_fields else None),
    ]


def _probe_max_risk_delta(base: dict, fields: dict, origins: dict) -> list[dict]:
    """Максимальный прирост риска: уровень судится, ИЗМЕНЕНИЕ — нет."""
    riskier = _econ_scene(
        chains={"aave_v3": "ethereum", "pendle": "base"},
        apy_pct={"aave_v3": 2.0, "pendle": 12.0},
    )
    v_riskier = _econ_verdict(riskier)
    delta_fields = sorted(n for n in fields["RiskConfig"] | fields["TriggerParams"]
                          if "delta" in n or "risk_increase" in n)
    spec_up = [base["gate_spec"][0], dict(base["gate_spec"][1], tier="T2")]
    v_gate_up = _gate_verdict(base["gate_target"], spec_up,
                              held={"aave_v3": 0.30 * _SCENE_CAPITAL_USD})
    return [
        _rec("economics", "quantity", v_riskier != base["economics"],
             f"цель переносится в сеть base при той же доходности: "
             f"{base['economics']} → {v_riskier} — прирост риска хода в "
             "экономике не участвует"),
        _rec("gate", "quantity", v_gate_up != base["gate"],
             f"та же книга при УЖЕ ДЕРЖИМОЙ позиции (то есть ход есть, а "
             f"уровень тот же): {v_gate_up} — гейт судит УРОВЕНЬ книги, "
             "разницу «было → стало» он не считает"),
        _rec("gate", "threshold", bool(delta_fields),
             f"поля политики про приращение риска: {delta_fields or 'нет'}; "
             "объявленные потолки (концентрация, тир, сеть) ограничивают "
             "УРОВЕНЬ, а не ДЕЛЬТУ"),
    ]


#: Двенадцать величин §41 в порядке ТЗ: ключ · дословная формулировка владельца ·
#: что величина ограничивает · проба.
OWNER_LIMITS: tuple[tuple[str, str, str, Callable], ...] = (
    ("max_trade_amount", "max trade amount",
     "абсолютный размер одной сделки в долларах", _probe_max_trade_amount),
    ("max_pct_per_rebalance", "max % portfolio per rebalance",
     "доля капитала, перекладываемая за один ход", _probe_pct_per_rebalance),
    ("max_daily_turnover", "max daily turnover",
     "суммарный оборот за сутки", _probe_daily_turnover),
    ("allowed_protocols", "allowed protocols",
     "какие протоколы вообще допущены к капиталу", _probe_allowed_protocols),
    ("allowed_vaults", "allowed vaults",
     "какие конкретные волты/пулы допущены", _probe_allowed_vaults),
    ("allowed_tiers", "allowed tiers",
     "какие тиры риска допущены и в каком объёме", _probe_allowed_tiers),
    ("allowed_chains", "allowed chains",
     "в каких сетях разрешено держать капитал", _probe_allowed_chains),
    ("allowed_assets", "allowed assets",
     "в каких активах разрешено держать капитал", _probe_allowed_assets),
    ("min_expected_net_gain", "minimum expected net gain",
     "минимальная ожидаемая чистая выгода хода", _probe_min_net_gain),
    ("min_confidence", "minimum confidence",
     "минимальная уверенность в числах, на которых принят ход", _probe_min_confidence),
    ("min_persistence", "minimum persistence",
     "минимальная устойчивость преимущества во времени", _probe_min_persistence),
    ("max_risk_delta", "maximum acceptable risk delta",
     "максимально допустимый прирост риска за ход", _probe_max_risk_delta),
)


# ──────────────────────────── сборка вердикта ───────────────────────────────

def _classify(records: list[dict]) -> tuple[str, str]:
    """Исход ограничения по его записям. Порядок вопросов — как в docstring.

    Сначала «спрашивается ли величина» (ось quantity), потом «есть ли ручка»
    (ось threshold, и ручкой считается ТОЛЬКО поле объявленного контракта —
    ``policy_field`` проставляется пробой лишь после сверки с
    ``dataclasses.fields``).
    """
    applies = [r for r in records if r["axis"] == "quantity" and r["changed"]]
    dials = [r for r in records if r["axis"] == "threshold" and r["changed"]
             and r.get("policy_field")]
    declared = [r for r in records if r["axis"] == "threshold" and r.get("policy_field")]

    if applies and dials:
        where = sorted({r["surface"] for r in applies})
        knobs = sorted({f"{r['declared_in']}.{r['policy_field']}" for r in dials})
        return BINDING, (f"связывает у {', '.join(where)}; ручка владельца: "
                         f"{', '.join(knobs)}")
    if applies and not dials:
        where = sorted({r["surface"] for r in applies})
        return LITERAL, (f"величина спрашивается у {', '.join(where)}, но ни одно "
                         "объявленное поле политики её порог не поворачивает — "
                         "порог зашит в коде")
    if not applies and declared:
        knobs = sorted({f"{r['declared_in']}.{r['policy_field']}" for r in declared})
        return DECLARED_INERT, (f"поле политики объявлено ({', '.join(knobs)}), но "
                                "величина владельца ни на одной поверхности "
                                "решения не спрашивается")
    return ABSENT, ("ни одна поверхность решения на эту величину не реагирует, и "
                    "поля политики для неё не объявлено")


def _binding_surfaces(results: list[dict]) -> set[str]:
    """Поверхности, на которых ХОТЬ ЧТО-ТО доказанно связывает.

    Второе условие положительного контроля: без него «поверхность не
    отреагировала» произносилось бы и в мире, где сломана сама проба.
    """
    out: set[str] = set()
    for res in results:
        if res["outcome"] != BINDING:
            continue
        for rec in res["records"]:
            if rec["axis"] == "quantity" and rec["changed"]:
                out.add(rec["surface"])
    return out


def run(root: str = REPO_ROOT, *, write: bool = True,
        now: dt.datetime | None = None) -> dict:
    """Замер §41. Живой ``data/`` не читается и не пишется (кроме отчёта)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    fields = _declared_policy_fields()
    origins = _allocator_cap_origin(root)

    # Источник потолков обязан быть ПРОЧИТАН до всякого счёта: без него ось
    # «policy-configurable» отвечает «нет» на КАЖДЫЙ потолок аллокатора, и это
    # неотличимо от честной находки «порог зашит в коде».
    control_reason = _allocator_source_error(root)
    baseline: dict[str, Any] = {}
    if not control_reason:
        try:
            baseline = _healthy_baselines()
        except Exception as exc:  # noqa: BLE001
            control_reason = (f"здоровая сцена не построена: "
                              f"{type(exc).__name__}: {exc}")

    control_ok = False
    if not control_reason:
        control_ok, control_reason = _control_ok(baseline)

    results: list[dict] = []
    for key, wording, constrains, probe in OWNER_LIMITS:
        entry: dict[str, Any] = {
            "limit": key, "owner_wording": wording, "constrains": constrains,
        }
        if not control_ok:
            entry.update({"outcome": UNCHECKED, "detail": "",
                          "unchecked_reason": control_reason, "records": []})
            results.append(entry)
            continue
        try:
            records = probe(baseline, fields, origins)
        except Exception as exc:  # noqa: BLE001 — упавшая проба это UNCHECKED
            entry.update({"outcome": UNCHECKED, "detail": "", "records": [],
                          "unchecked_reason": f"{type(exc).__name__}: {exc}"})
            results.append(entry)
            continue
        outcome, detail = _classify(records)
        entry.update({"outcome": outcome, "detail": detail, "records": records,
                      "unchecked_reason": "",
                      "surfaces_binding": sorted(
                          {r["surface"] for r in records
                           if r["axis"] == "quantity" and r["changed"]}),
                      "gaps": [{"surface": r["surface"], "gap": r["gap"]}
                               for r in records if r.get("gap")]})
        results.append(entry)

    if control_ok:
        reacting = _binding_surfaces(results)
        missing = [s for s in SURFACES if s not in reacting]
        if missing:
            control_ok = False
            control_reason = (
                f"ни одно ограничение не измерено BINDING на поверхност(и/ях) "
                f"{', '.join(missing)} — «поверхность не реагирует» здесь "
                f"неотличимо от «проба сломана»; счёт читать нельзя")
            for entry in results:
                entry.update({"outcome": UNCHECKED,
                              "unchecked_reason": control_reason})

    findings, unchecked = _findings(results, control_ok, control_reason, baseline)
    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "warn": sum(1 for f in findings if f["severity"] == "WARN"),
        "info": sum(1 for f in findings if f["severity"] == "INFO"),
        "unchecked": len(unchecked),
    }
    overall = ("UNCHECKED" if not control_ok
               else "CRITICAL" if counts["critical"]
               else "WARN" if counts["warn"]
               else "UNCHECKED" if counts["unchecked"]
               else "OK")
    tally = {o: sum(1 for r in results if r["outcome"] == o)
             for o in (BINDING, LITERAL, DECLARED_INERT, ABSENT, UNCHECKED)}

    doc = {
        "generated_at": now.isoformat(),
        "overall": overall,
        "counts": counts,
        "owner_criterion": (
            "§41 ТЗ «Portfolio CIO»: при разрешённом auto-execution обязательны "
            "max trade amount · max % portfolio per rebalance · max daily "
            "turnover · allowed protocols · allowed vaults · allowed tiers · "
            "allowed chains · allowed assets · minimum expected net gain · "
            "minimum confidence · minimum persistence · maximum acceptable "
            "risk delta — ВСЕ policy-configurable"),
        "limits_total": len(OWNER_LIMITS),
        "tally": tally,
        "surfaces": list(SURFACES),
        "control": {"passed": control_ok, "reason": control_reason,
                    "healthy_baseline": {k: v for k, v in baseline.items()
                                         if k in ("gate", "economics",
                                                  "allocator_chain")},
                    "surfaces_with_a_binding_limit": sorted(
                        _binding_surfaces(results)) if control_ok else []},
        "declared_policy_fields": {k: sorted(v) for k, v in fields.items()},
        "allocator_cap_origin": {k: v for k, v in sorted(origins.items())
                                 if k.endswith("_CAP") or k.endswith("_USD")},
        "limits": results,
        "findings": findings,
        "unchecked": unchecked,
        "advisory": (
            "ADVISORY: ни один порог этим модулем не меняется и ни одно "
            "недостающее ограничение не строится — дать auto-execution новый "
            "лимит это money-path и решение владельца"),
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _measured(result: dict) -> str:
    """Что именно проба СДЕЛАЛА и что увидела — в самой находке.

    Вывод «ограничения нет» без описания опыта нечем ни проверить, ни оспорить,
    и через месяц он читается как мнение. Поэтому детали проб едут в текст
    находки, а не остаются только в JSON.
    """
    return "; ".join(r["detail"] for r in result.get("records") or [])


def _findings(results: list[dict], control_ok: bool, control_reason: str,
              baseline: dict) -> tuple[list[dict], list[str]]:
    findings: list[dict] = []
    unchecked: list[str] = []

    if not control_ok:
        unchecked.append(
            f"положительный контроль не пройден — {control_reason}; счёт по "
            f"ограничениям §41 читать нельзя")
        return findings, unchecked

    by = {o: [r for r in results if r["outcome"] == o]
          for o in (BINDING, LITERAL, DECLARED_INERT, ABSENT, UNCHECKED)}

    for r in by[DECLARED_INERT]:
        findings.append({
            "severity": "CRITICAL",
            "code": f"declared_inert:{r['limit']}",
            "message": (
                f"«{r['owner_wording']}»: {r['detail']}. В конфигурации ручка "
                f"видна, и по ней читается, что ограничение работает — а "
                f"величина, которую она должна судить, на пути решения не "
                f"спрашивается"),
        })
    for r in by[ABSENT]:
        findings.append({
            "severity": "WARN",
            "code": f"absent:{r['limit']}",
            "message": (f"«{r['owner_wording']}» ({r['constrains']}): "
                        f"{r['detail']}. Измерено: {_measured(r)}"),
        })
    for r in by[LITERAL]:
        findings.append({
            "severity": "WARN",
            "code": f"literal:{r['limit']}",
            "message": (
                f"«{r['owner_wording']}»: {r['detail']}. Второе требование §41 "
                f"(«все policy-configurable») для него НЕ выполнено: чтобы "
                f"изменить порог, нужен коммит, а не решение владельца. "
                f"Измерено: {_measured(r)}"),
        })

    # Полусвязанные ограничения — главный предмет этого замера. Ограничение,
    # которое связывает у того, кто ПРЕДЛАГАЕТ, и молчит у того, кто ДОПУСКАЕТ,
    # в сводке «есть/нет» неотличимо от полностью работающего; а разница ровно в
    # том, что цель, пришедшая не от нашего аллокатора, последней двери не
    # встретит.
    for r in results:
        for gap in r.get("gaps") or []:
            findings.append({
                "severity": "WARN",
                "code": f"surface_gap:{r['limit']}:{gap['surface']}",
                "message": (
                    f"«{r['owner_wording']}» на поверхности `{gap['surface']}` "
                    f"выполнено НЕ ПОЛНОСТЬЮ: {gap['gap']}. Ограничение при "
                    f"этом связывает у {', '.join(r.get('surfaces_binding') or []) or '—'} "
                    f"— замер по одной поверхности назвал бы его либо целиком "
                    f"рабочим, либо целиком отсутствующим, и оба ответа были бы "
                    f"неверны"),
            })
    for r in by[UNCHECKED]:
        unchecked.append(f"«{r['owner_wording']}»: {r['unchecked_reason']}")

    covered = len(by[BINDING])
    findings.append({
        "severity": ("CRITICAL" if by[DECLARED_INERT]
                     else "WARN" if covered < len(OWNER_LIMITS) else "INFO"),
        "code": "coverage",
        "message": (
            f"из {len(OWNER_LIMITS)} названных владельцем ограничений §41 "
            f"выполнены ОБА требования («есть» + «policy-configurable») у "
            f"{covered}; порог зашит в коде у {len(by[LITERAL])}; объявлены, но "
            f"не спрашиваются у {len(by[DECLARED_INERT])}; отсутствуют у "
            f"{len(by[ABSENT])}; не измерены у {len(by[UNCHECKED])}"),
    })

    split = [r for r in by[BINDING] + by[LITERAL]
             if len(r.get("surfaces_binding") or []) == 1]
    if split:
        findings.append({
            "severity": "INFO",
            "code": "one_surface_only",
            "message": (
                "ограничения, которые связывают ровно на ОДНОЙ поверхности "
                "решения (замер по любой другой объявил бы их отсутствующими): "
                + "; ".join(f"«{r['owner_wording']}» → "
                            f"{r['surfaces_binding'][0]}" for r in split)),
        })

    if by[BINDING]:
        findings.append({
            "severity": "INFO",
            "code": "limits_that_exist",
            "message": ("ограничения, у которых есть и применение, и ручка "
                        "владельца: "
                        + ", ".join(f"«{r['owner_wording']}» ({r['detail']})"
                                    for r in by[BINDING])),
        })
    return findings, unchecked


def _main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    doc = run(root=args.root, write=not args.no_write)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0
    c = doc["counts"]
    print(f"cio_auto_execution_limits: {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"unchecked={c['unchecked']})")
    if not doc["control"]["passed"]:
        print(f"  [НЕ ИЗМЕРЕНО] положительный контроль не пройден — "
              f"{doc['control']['reason']}")
        return 0
    for r in doc["limits"]:
        where = ", ".join(r.get("surfaces_binding") or []) or "—"
        print(f"  {r['outcome']:15s} «{r['owner_wording']}» [{where}] — "
              f"{r['detail'] or r['unchecked_reason']}")
    for f in doc["findings"]:
        print(f"  [{f['severity']}] {f['message']}")
    for u in doc["unchecked"]:
        print(f"  [НЕ ИЗМЕРЕНО] {u}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
