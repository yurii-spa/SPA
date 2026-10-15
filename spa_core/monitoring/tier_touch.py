"""Трогает ли исходник КАНОН ТИРА — вопрос к коду, а не к набору байт.

Написан по находке 2026-10-02 (карточка `inbox-storozh-tira-sudit-podstrokoi-i-krasen-n`,
замер цикла #755): сторож `test_tier_curator::test_no_module_consumes_report_to_mutate_tiers`
спрашивал «встречается ли строка `RiskConfig` в файле» и потому был КРАСЕН на
ВЕРНОМ состоянии тринадцать суток. В `spa_core/monitoring/card_acceptance.py`
слово `RiskConfig` стои́т дважды, и оба раза НЕ в коде (замер 15.10, цикл #875:
строка 1620 — докстрока о том, что из `RiskConfig` читает ДРУГОЙ прибор;
строка 1731 — текст сообщения в f-строке). Тиром ни то, ни другое не двигает.

**У подстроки две стороны, и вторая опаснее первой.** Ложный КРАСНЫЙ виден —
он и привёл сюда. Ложный ЗЕЛЁНЫЙ не виден никому: настоящий ввоз, записанный
иначе (`import spa_core.risk.policy`, псевдоним `as RC`, `getattr(m, "RiskConfig")`,
`importlib.import_module(...)`), подстрочным списком не ловится ВООБЩЕ. Поэтому
прибор мерит ПОЗИЦИЮ символа в разборе, а не его наличие в тексте:

| что считается прикосновением | `kind` |
|---|---|
| ввоз модуля канона или имени из него, включая псевдоним | `import` |
| голое имя канона в выражении | `name` |
| обращение к атрибуту с именем канона либо цепочка модуля | `attribute` |
| имя канона СТРОКОЙ в аргументе динамического доступа (`getattr`/`import_module`/…) | `dynamic` |

Прозой считается всё остальное: докстроки, сообщения, f-строки, перечисления
артефактов в комментариях. Это сужение, а не послабление — ни одна из четырёх
форм выше через прозу не записывается.

**Третий исход назван, а не подменён.** Неразбираемый исходник — это НЕ «чисто»:
`tier_touches` поднимает `TierTouchUnmeasured`, и вызывающий обязан решить сам
(инв. #17: «измерено», «измерено и равно нулю», «не измерено» различимы). Молча
вернуть пустой список значило бы отдать ложный зелёный за опечатку в файле.

Прибор НЕ решает, кому канон трогать можно: это правило живёт у сторожа и у
ADR-055/ADR-041 (ярлык тира меняется только ADR-ом). Здесь — только признак.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass

#: Имена канона тира: ими меняют тир, оценку риска или реестр, из которого тир читается.
#: Набор — ОБЪЕДИНЕНИЕ двух прежних списков сторожа (у моста находок был на одно имя
#: длиннее, чем у пробы приёмки). Объединение есть УСИЛЕНИЕ: замер 15.10 показал, что
#: ни один из двух разрешённых читателей ни одного из этих имён в коде не держит, поэтому
#: разных списков правило не требует, а два списка на одно правило — два места для него.
TIER_CANON_NAMES: tuple[str, ...] = (
    "PROTOCOL_RISK_SCORES",
    "ADAPTER_REGISTRY",
    "tier_map",
    "RiskConfig",
    "protocol_risk_map",
)

#: Модули канона — ДОТТЕД-ХВОСТЫ, а не полные пути: `risk.policy` совпадает и с
#: `spa_core.risk.policy`, и с относительной записью, и ни с чем случайным (хвост
#: сверяется по границе точки, а не подстрокой — `my_risk.policy` не совпадёт).
TIER_CANON_MODULES: tuple[str, ...] = (
    "risk.policy",
    "adapters.registry",
    "analytics.tier_curator",
)

#: Вызовы, чей СТРОКОВЫЙ аргумент есть обращение к имени, а не проза.
#: Список намеренно короткий: строка в аргументе ЛЮБОГО вызова была бы снова
#: подстрокой — сообщение `_log("из RiskConfig (N полей)")` стало бы нарушением.
DYNAMIC_ACCESS_CALLS: frozenset[str] = frozenset({
    "getattr", "setattr", "hasattr", "delattr",
    "import_module", "__import__", "eval", "exec",
})


class TierTouchUnmeasured(Exception):
    """Исходник не разобран ⇒ прикосновение НЕ ИЗМЕРЕНО (это не «чисто»)."""


@dataclass(frozen=True)
class Touch:
    """Одно прикосновение: ЧТО тронуто, КАКОЙ формой записи и в какой строке."""

    token: str
    kind: str
    line: int

    def __str__(self) -> str:                       # pragma: no cover - проза отчёта
        return f"{self.token} ({self.kind}, строка {self.line})"


def _dotted(node: ast.AST) -> str | None:
    """Собрать `a.b.c` из цепочки Attribute/Name. `None` — цепочка не из имён."""
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return ".".join(reversed(parts))


def _module_matches(dotted: str | None, modules: "tuple[str, ...]") -> str | None:
    """Хвост модуля, которому отвечает путь, либо `None`.

    Сверка по ГРАНИЦЕ ТОЧКИ: `risk.policy` совпадает с `spa_core.risk.policy`
    и с самим собой, но не с `my_risk.policy` — иначе вернулась бы подстрока.
    """
    if not dotted:
        return None
    for mod in modules:
        if dotted == mod or dotted.endswith("." + mod):
            return mod
    return None


def _callee_name(call: ast.Call) -> str:
    """Короткое имя вызываемого: `getattr` и `importlib.import_module` → `import_module`."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def tier_touches(
    source: str,
    *,
    names: "tuple[str, ...]" = TIER_CANON_NAMES,
    modules: "tuple[str, ...]" = TIER_CANON_MODULES,
) -> "list[Touch]":
    """Все прикосновения к канону тира В КОДЕ. Пустой список — прикосновений нет.

    `TierTouchUnmeasured` — исходник не разобран; вызывающий обязан назвать это
    третьим исходом, а не чистотой.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        raise TierTouchUnmeasured(f"исходник не разобран: {exc}") from exc

    found: list[Touch] = []
    name_set = set(names)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                hit = _module_matches(alias.name, modules)
                if hit:
                    found.append(Touch(hit, "import", node.lineno))
                # `import x.RiskConfig` невозможен, но `import a as RiskConfig` —
                # вполне: имя канона появляется в области видимости.
                if alias.asname in name_set:
                    found.append(Touch(alias.asname, "import", node.lineno))
        elif isinstance(node, ast.ImportFrom):
            hit = _module_matches(node.module, modules)
            if hit:
                found.append(Touch(hit, "import", node.lineno))
            for alias in node.names:
                # `from spa_core.risk import policy` — ввоз МОДУЛЯ, а не имени, и
                # дословного `risk.policy` в тексте при этом нет НИ РАЗУ: ровно
                # ложный зелёный прежнего подстрочного списка. Путь собирается
                # целиком, а не угадывается по последнему звену.
                full = f"{node.module}.{alias.name}" if node.module else alias.name
                hit = _module_matches(full, modules)
                if hit:
                    found.append(Touch(hit, "import", node.lineno))
                for token in (alias.name, alias.asname):
                    if token in name_set:
                        found.append(Touch(token, "import", node.lineno))
        elif isinstance(node, ast.Name):
            if node.id in name_set:
                found.append(Touch(node.id, "name", node.lineno))
        elif isinstance(node, ast.Attribute):
            if node.attr in name_set:
                found.append(Touch(node.attr, "attribute", node.lineno))
            hit = _module_matches(_dotted(node), modules)
            if hit:
                found.append(Touch(hit, "attribute", node.lineno))
        elif isinstance(node, ast.Call):
            if _callee_name(node) not in DYNAMIC_ACCESS_CALLS:
                continue
            args = list(node.args) + [kw.value for kw in node.keywords]
            for arg in args:
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                    continue
                if arg.value in name_set:
                    found.append(Touch(arg.value, "dynamic", arg.lineno))
                    continue
                hit = _module_matches(arg.value, modules)
                if hit:
                    found.append(Touch(hit, "dynamic", arg.lineno))

    # Порядок устойчив (строка, затем имя): отчёт сторожа не должен зависеть от
    # порядка обхода дерева, иначе текст падения меняется от версии к версии.
    uniq = {(t.token, t.kind, t.line): t for t in found}
    return [uniq[k] for k in sorted(uniq)]


def describe(path: str, touches: "list[Touch]") -> str:
    """Одна строка отчёта: ЧТО тронуто и где. Пустой список — «прикосновений нет»."""
    if not touches:
        return f"{path}: прикосновений к канону тира нет"
    return f"{path}: " + "; ".join(str(t) for t in touches)
