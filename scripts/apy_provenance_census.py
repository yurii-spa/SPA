#!/usr/bin/env python3
"""Перепись провенанса оси APY: кто из опрашиваемых адаптеров может отдать ставку, НЕ снятую в этом вызове.

Остаток приказа владельца «Portfolio CIO» (`inbox-task-portfolio-cio-dynamic-capital-alloc`),
пункт 2 карточки `inbox-tsikl-schitaet-pokrytie-fidov-100-zhivym` (29.08): «адаптер, чьё число
пришло из статической записи, обязан считаться `static`, а не `live`; показатель "100 % живое"
должен уметь быть неполным».

## Почему прибор понадобился

У оси TVL контракт провенанса есть с ADR-053: `YieldInfo.tvl_source` объявляет «live» ТОЛЬКО
про число, снятое в ЭТОМ вызове, и правило названо в докстринге дословно — *never stamp "live"
on a constant*. У оси APY контракта НЕ БЫЛО ВООБЩЕ, и дальше по цепочке «живость» ставки
назначалась догадкой трижды:

1. `adapter_orchestrator._run_one_adapter` — `live_data = True` по ОДНОМУ факту «вернулось
   число» (вопрос о происхождении не задан);
2. `allocator._load_adapters` на пути снимка — `"apy_source": "live"` БЕЗУСЛОВНО, с
   комментарием «live by construction»;
3. `scripts/capital_observability_census.py` считает наблюдением объявленный провенанс — и
   на оси APY читает ровно тот штамп, который поставлен догадкой. Поэтому его «100 %» по этой
   оси не может упасть НИКОГДА: зелёный ответ сторожа на СВОЙ вопрос.

Замер 12.10, ради которого прибор и написан: все пять протоколов, держащих капитал
($95 000 из $100 000), приходят в аллокатор путём СНИМКА — то есть тем путём, где провенанс
ставки не спрашивают. В двери 11 адаптеров, и до ADR-706 провенанс объявлял НИ ОДИН (0 из 11);
один из них (`fluid_fusdc`, $20 000 книги) по построению способен подставить вместо наблюдения
классовую постоянную `SPIKE_NORM_PCT = 9.0`: при `raw > SPIKE_THRESHOLD_PCT (15 %)` наружу
уходит 9.0, и ни один потребитель отличить это от наблюдения не мог. Постоянная лежит внутри
полосы допуска RiskPolicy (1…30 %), поэтому гейт её пропускает.

Замер ПОСЛЕ правки: объявляют 1 · только живое 10 · МОГУТ ПОДСТАВИТЬ 0 · НЕ ИЗМЕРЕНО 0.
Объявляющих меньше, чем адаптеров, НАМЕРЕННО: «не объявил» и «объявил постоянной» суть
разные болезни, и прибор отвечает на вопрос «может ли постоянная доехать МОЛЧА», а не
«объявили ли все».

## Что прибор СПРАШИВАЕТ (и чего не спрашивает)

Вопрос один: **объявляет ли адаптер провенанс ставки, и если НЕ объявляет — может ли до
`YieldInfo.apy` доехать зафиксированная в коде постоянная?**

* `declared` — у вызова `YieldInfo(...)` передан `apy_source=`. Значение выражения прибор
  ПРИ ЭТОМ НЕ разбирает: верность объявления — предмет теста самого адаптера, а не этой
  переписи. Оговорка названа, потому что без неё «declared» читалось бы как «провенанс верен».
* `live_only` — объявления нет, но постоянная до поля доехать не может: значение приходит
  из результата вызова (фид), и ни одно имя на пути не разрешается в числовой литерал.
* `can_substitute` — объявления нет И постоянная доехать МОЖЕТ. Это находка: литерал
  ранжирует капитал под ярлыком наблюдения.
* `unmeasured` — объявления нет и выражение РАЗОБРАТЬ НЕ УДАЛОСЬ (третий исход, инв. #17):
  ни «чисто», ни «находка». Код возврата 2, причина названа поимённо.

### Две названные НЕДОМЕРКИ, и у каждой есть ВЕЛИЧИНА

Оговорка без числа верна в обе стороны сразу, поэтому обе считаются:

* **Литерал-умолчание внутри чтения** — `best.get("apy", 0.0)`. Формально до поля доезжает
  литерал, но доезжает он ТОЛЬКО когда фид ответил и ключа в ответе нет; к тому же ноль
  виден дальше (`status="partial"`). Прибор это **не** считает подстановкой, а считает
  ОТДЕЛЬНЫМ числом (`literal_default`), чтобы недомерка имела величину.
* **Шаги разрешения** — предел `max_steps` (умолчание 3) объявлен ВХОДОМ. Достигнутый
  предел уходит в `unmeasured` с причиной, а не в «постоянной нет» (иначе предел обхода
  отдавал бы тот же ответ, что «не нашёл» — класс ADR-703).

## Две поверхности, и решающая только первая

| поверхность | кто в ней | почему |
|---|---|---|
| **дверь** (решающая) | `POLLED_ADAPTERS` оркестратора | ровно здесь провенанс не спрашивают, и ровно отсюда приходит капитал книги |
| наблюдение (справочно) | все классы `spa_core/adapters/*.py` с `get_yield_info` | адаптер попадает в дверь решением цикла, а не свойством кода |

Код возврата: 0 — в двери находок нет · 1 — находки названы · 2 — НЕ ИЗМЕРЕНО.

Только stdlib. Прибор ЧИТАЕТ код и ничего не чинит и не запускает: вызвать адаптер значило бы
пойти в сеть, а вопрос «что МОЖЕТ доехать» живым вызовом не отвечается в принципе — один
прогон показывает одну ветку.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS_DIR = ROOT / "spa_core" / "adapters"

#: Предел шагов разрешения значения (имя → RHS → возврат метода того же модуля).
#: ВХОД, а не константа: замер прибором на другом пределе — отдельное утверждение.
DEFAULT_MAX_STEPS = 3

#: Потолок справочной поверхности: сколько классов ВНЕ двери способны подставить
#: постоянную без объявления. Замер 2026-10-12 (ADR-706) ПОСЛЕ правки двери: **2**
#: (`PendlePTSusdeAdapter`, `PendlePTUsdcAdapter` — оба возвращают литерал `0.0`
#: при разворачивании PT ближе 30 дней до погашения; оба советательные и в дверь
#: не входят). Потолок может только УБЫВАТЬ; поднимать его, чтобы погасить
#: падение, запрещено (инв. #16) — объявлять провенанс.
OBSERVED_SURFACE_CEILING = 2


# ── разбор исходника адаптера ────────────────────────────────────────────────


def _module_level_numbers(tree: ast.Module) -> set[str]:
    """Имена модульного уровня, чьё значение — числовой литерал."""
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if isinstance(value, ast.Constant) and isinstance(value.value, (int, float)) \
                    and not isinstance(value.value, bool):
                for t in targets:
                    if isinstance(t, ast.Name):
                        out.add(t.id)
    return out


def _class_level_numbers(cls: ast.ClassDef) -> set[str]:
    """Атрибуты класса, чьё значение — числовой литерал (постоянная адаптера)."""
    out: set[str] = set()
    for node in cls.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if isinstance(value, ast.Constant) and isinstance(value.value, (int, float)) \
                    and not isinstance(value.value, bool):
                for t in targets:
                    if isinstance(t, ast.Name):
                        out.add(t.id)
            # `SPIKE_NORM_PCT: float = 9.0` — то же самое через AnnAssign.
    return out


def _methods(cls: ast.ClassDef) -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


def _yield_info_call(fn: ast.FunctionDef) -> Optional[ast.Call]:
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name == "YieldInfo":
                return node
    return None


def _kw(call: ast.Call, name: str) -> Optional[ast.expr]:
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _local_assignments(fn: ast.FunctionDef) -> dict[str, list[ast.expr]]:
    """Локальные привязки функции: имя → все выражения, которыми оно связывается.

    Распаковка кортежа учитывается: `a, b = self.m()` связывает оба имени с
    вызовом (какой элемент — прибор не различает НАМЕРЕННО: обе половины
    происходят из одного источника, и для вопроса «может ли доехать постоянная»
    различие элемента ответа не меняет).
    """
    out: dict[str, list[ast.expr]] = {}
    for node in ast.walk(fn):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names: list[str] = []
            for t in targets:
                if isinstance(t, ast.Name):
                    names.append(t.id)
                elif isinstance(t, (ast.Tuple, ast.List)):
                    names.extend(e.id for e in t.elts if isinstance(e, ast.Name))
            for n in names:
                out.setdefault(n, []).append(value)
    return out


def _returns(fn: ast.FunctionDef) -> list[ast.expr]:
    out: list[ast.expr] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and node.value is not None:
            out.append(node.value)
    return out


def _flatten(expr: ast.expr) -> list[ast.expr]:
    """Разложить выражение на ветви-кандидаты (тернарник, кортеж, bool-ор)."""
    if isinstance(expr, ast.IfExp):
        return _flatten(expr.body) + _flatten(expr.orelse)
    if isinstance(expr, ast.Tuple):
        parts: list[ast.expr] = []
        for e in expr.elts:
            parts.extend(_flatten(e))
        return parts
    if isinstance(expr, ast.BoolOp):
        parts = []
        for e in expr.values:
            parts.extend(_flatten(e))
        return parts
    if isinstance(expr, ast.BinOp):
        # `x / 100.0` — литерал в АРИФМЕТИКЕ есть МАСШТАБ, а не источник значения:
        # считать делитель подстановкой значило бы обвинить перевод процентов в
        # доли у каждого честного адаптера (замер первой редакции: 3 ложных из 3).
        # Поэтому из операндов берутся НЕ-литералы; если литералы ОБА — выражение
        # целиком и есть постоянная (`4.1 / 100.0`), и оно возвращается как она.
        _ops = [e for e in (expr.left, expr.right) if not isinstance(e, ast.Constant)]
        if not _ops:
            return [expr]
        return [x for e in _ops for x in _flatten(e)]
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) \
            and expr.func.id in ("float", "round", "abs") and expr.args:
        # ТОЛЬКО первый аргумент. `round(x, 8)` — второй есть ТОЧНОСТЬ, и считать
        # её источником значения значило бы обвинить pendle в подстановке «8 %»
        # (ровно эта ложная находка и была в первой редакции).
        return _flatten(expr.args[0])
    return [expr]


def _literal_default_in_get(expr: ast.expr) -> bool:
    """`<...>.get("apy", 0.0)` — литерал-умолчание внутри чтения (своё число)."""
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Attribute)
        and expr.func.attr == "get"
        and len(expr.args) >= 2
        and isinstance(expr.args[1], ast.Constant)
        and isinstance(expr.args[1].value, (int, float))
        and not isinstance(expr.args[1].value, bool)
    )


def _get_default_repr(expr: ast.expr) -> str:
    """Литерал-умолчание из `.get(key, <литерал>)` — для печати."""
    assert isinstance(expr, ast.Call) and isinstance(expr.args[1], ast.Constant)
    return repr(expr.args[1].value)


class _Resolver:
    """Разрешает значение, доезжающее до `YieldInfo.apy`, в пределах ОДНОГО модуля."""

    def __init__(self, tree: ast.Module, cls: ast.ClassDef, max_steps: int) -> None:
        self.tree = tree
        self.cls = cls
        self.max_steps = max_steps
        self.module_nums = _module_level_numbers(tree)
        self.class_nums = _class_level_numbers(cls)
        self.methods = _methods(cls)

    def classify(self, expr: ast.expr, fn: ast.FunctionDef) -> tuple[str, list[str]]:
        """→ (вердикт, причины/имена). Вердикт: constant | live | unmeasured."""
        verdict = "live"
        notes: list[str] = []
        constants: list[str] = []
        literal_defaults: list[str] = []
        unmeasured: list[str] = []

        seen: set[int] = set()

        def walk(e: ast.expr, fn: ast.FunctionDef | None, steps: int) -> None:
            if id(e) in seen:
                return
            seen.add(id(e))
            if steps > self.max_steps:
                unmeasured.append(
                    "предел шагов {} достигнут на {}".format(
                        self.max_steps, ast.dump(e)[:60]))
                return
            for branch in _flatten(e):
                if isinstance(branch, ast.Constant):
                    if isinstance(branch.value, (int, float)) and not isinstance(branch.value, bool):
                        # Литерал ПРЯМО в выражении поля — та же подстановка.
                        constants.append("литерал {!r}".format(branch.value))
                    continue
                if _literal_default_in_get(branch):
                    literal_defaults.append(
                        "умолчание {} внутри .get()".format(_get_default_repr(branch)))
                    continue
                if isinstance(branch, ast.Attribute):
                    if isinstance(branch.value, ast.Name) and branch.value.id == "self":
                        if branch.attr in self.class_nums:
                            constants.append("self.{}".format(branch.attr))
                        # атрибут-не-постоянная (напр. self._data_dir) — не ставка.
                        continue
                    # Поле ЧУЖОГО объекта (`best.implied_apy`) — чтение значения,
                    # добытого вызовом. НАЗВАННАЯ недомерка: постоянная чужого
                    # класса (`Other.CONST`) этим правилом не ловится; в двери
                    # таких сегодня нет, а родовое правило требовало бы разбора
                    # второго модуля — отдельное утверждение, не это.
                    continue
                if isinstance(branch, ast.Name):
                    if branch.id in self.module_nums:
                        constants.append("модульная {}".format(branch.id))
                        continue
                    if fn is not None:
                        binds = _local_assignments(fn).get(branch.id)
                        if binds:
                            for b in binds:
                                walk(b, fn, steps + 1)
                            continue
                    unmeasured.append("имя {} не разрешено".format(branch.id))
                    continue
                if isinstance(branch, ast.Call):
                    f = branch.func
                    # self.<method>() — шаг ВНУТРЬ метода того же класса.
                    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                            and f.value.id == "self" and f.attr in self.methods:
                        callee = self.methods[f.attr]
                        rets = _returns(callee)
                        if not rets:
                            unmeasured.append("метод self.{} без return".format(f.attr))
                            continue
                        for r in rets:
                            walk(r, callee, steps + 1)
                        continue
                    # любой другой вызов — это дверь наружу (фид/помощник другого
                    # модуля): постоянной ЭТОГО модуля оттуда не приходит.
                    continue
                if isinstance(branch, ast.Subscript):
                    # `pool["apy"]` — чтение результата вызова, не постоянная.
                    continue
                if isinstance(branch, ast.Compare) or isinstance(branch, ast.UnaryOp):
                    continue
                unmeasured.append("форма {} не разобрана".format(type(branch).__name__))

        walk(expr, fn, 0)

        # ПОРЯДОК СУЩЕСТВЕНЕН. Найденная постоянная есть ДОКАЗАТЕЛЬСТВО, и
        # неразобранная соседняя ветвь его не отменяет: «не смог разобрать ветвь Б»
        # никак не делает ветвь А менее постоянной. Обратный порядок (первая
        # редакция) прятал fluid_fusdc в «НЕ ИЗМЕРЕНО», хотя `self.SPIKE_NORM_PCT`
        # был найден. Зато нехватка доказательства ПРИ неразобранных ветвях в
        # «чисто» не превращается — там третий исход обязателен.
        if constants:
            verdict = "constant"
            notes = sorted(set(constants))
            if unmeasured:
                notes = notes + ["НЕ РАЗОБРАНО рядом: " + "; ".join(sorted(set(unmeasured)))]
        elif unmeasured:
            verdict = "unmeasured"
            notes = sorted(set(unmeasured))
        else:
            verdict = "live"
            notes = sorted(set(literal_defaults))
        return verdict, notes


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def measure_adapter(path: Path, class_name: str, max_steps: int = DEFAULT_MAX_STEPS) -> dict:
    """Вердикт по ОДНОМУ классу адаптера. Нечитаемый файл ⇒ `unmeasured`."""
    row: dict[str, Any] = {
        # Путь печатается относительно корня, КОГДА он под корнем: одноразовая
        # сцена теста лежит в /tmp, и `relative_to` на ней бросает — печать не
        # имеет права ронять замер.
        "module": _display_path(path),
        "class": class_name,
        "verdict": "unmeasured",
        "notes": [],
        "literal_defaults": [],
    }
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (OSError, SyntaxError) as exc:
        row["notes"] = ["исходник не разобран: {}: {}".format(type(exc).__name__, exc)]
        return row

    cls = next((n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == class_name), None)
    if cls is None:
        row["notes"] = ["класс {} не найден в модуле".format(class_name)]
        return row
    fn = _methods(cls).get("get_yield_info")
    if fn is None:
        row["notes"] = ["get_yield_info не определён в классе (наследован?)"]
        return row
    call = _yield_info_call(fn)
    if call is None:
        row["notes"] = ["вызов YieldInfo(...) в get_yield_info не найден"]
        return row

    declared = _kw(call, "apy_source")
    if declared is not None:
        row["verdict"] = "declared"
        row["notes"] = ["apy_source объявлен выражением {}".format(
            type(declared).__name__)]
        return row

    apy = _kw(call, "apy")
    if apy is None:
        row["notes"] = ["apy= не передан в YieldInfo (позиционно?)"]
        return row

    resolver = _Resolver(tree, cls, max_steps)
    verdict, notes = resolver.classify(apy, fn)
    if verdict == "constant":
        row["verdict"] = "can_substitute"
        row["notes"] = notes
    elif verdict == "live":
        row["verdict"] = "live_only"
        row["literal_defaults"] = notes
    else:
        row["verdict"] = "unmeasured"
        row["notes"] = notes
    return row


# ── поверхности ──────────────────────────────────────────────────────────────


def door_targets() -> tuple[list[tuple[Path, str]], Optional[str]]:
    """Опрашиваемый набор оркестратора: (модуль, класс). Вторым — причина отказа."""
    try:
        sys.path.insert(0, str(ROOT))
        from spa_core.orchestrator.adapter_orchestrator import POLLED_ADAPTERS  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 — дверь не прочитана: третий исход
        return [], "POLLED_ADAPTERS не прочитан: {}: {}".format(type(exc).__name__, exc)
    out: list[tuple[Path, str]] = []
    for _, _, cls in POLLED_ADAPTERS:
        mod = sys.modules.get(cls.__module__)
        f = getattr(mod, "__file__", None)
        if not f:
            return out, "модуль класса {} не имеет __file__".format(cls.__name__)
        out.append((Path(f), cls.__name__))
    return out, None


def observed_targets() -> list[tuple[Path, str]]:
    """Справочная поверхность: все классы adapters/*.py с собственным get_yield_info."""
    out: list[tuple[Path, str]] = []
    for path in sorted(ADAPTERS_DIR.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and "get_yield_info" in _methods(node):
                out.append((path, node.name))
    return out


def measure(max_steps: int = DEFAULT_MAX_STEPS) -> dict:
    door, door_refused = door_targets()
    rows = [measure_adapter(p, c, max_steps) for p, c in door]
    obs_rows = [measure_adapter(p, c, max_steps) for p, c in observed_targets()]

    def tally(rs: list[dict]) -> dict:
        return {
            "population": len(rs),
            "declared": sum(1 for r in rs if r["verdict"] == "declared"),
            "live_only": sum(1 for r in rs if r["verdict"] == "live_only"),
            "can_substitute": sum(1 for r in rs if r["verdict"] == "can_substitute"),
            "unmeasured": sum(1 for r in rs if r["verdict"] == "unmeasured"),
            "literal_defaults": sum(1 for r in rs if r["literal_defaults"]),
        }

    return {
        "max_steps": max_steps,
        "door_refused": door_refused,
        "door": tally(rows),
        "door_rows": rows,
        "observed": tally(obs_rows),
        "observed_rows": obs_rows,
    }


def _print(report: dict) -> int:
    door = report["door"]
    if report["door_refused"]:
        print("НЕ ИЗМЕРЕНО: {}".format(report["door_refused"]))
        return 2
    print("Провенанс оси APY — дверь оркестратора ({} адаптеров, шагов разрешения {}):".format(
        door["population"], report["max_steps"]))
    print("  объявляют провенанс: {} · только живое: {} · МОГУТ ПОДСТАВИТЬ: {} · НЕ ИЗМЕРЕНО: {}".format(
        door["declared"], door["live_only"], door["can_substitute"], door["unmeasured"]))
    print("  литерал-умолчание внутри чтения (своя недомерка): {}".format(
        door["literal_defaults"]))
    for r in report["door_rows"]:
        if r["verdict"] in ("can_substitute", "unmeasured"):
            print("  [{}] {} ({}): {}".format(
                r["verdict"].upper(), r["class"], r["module"], "; ".join(r["notes"])))
    obs = report["observed"]
    print("Справочная поверхность (все классы adapters/* с get_yield_info): {} · "
          "объявляют {} · могут подставить {} · НЕ ИЗМЕРЕНО {}".format(
              obs["population"], obs["declared"], obs["can_substitute"], obs["unmeasured"]))

    if door["unmeasured"]:
        print("ВЕРДИКТ: НЕ ИЗМЕРЕНО — {} адаптер(ов) в двери не разобраны".format(
            door["unmeasured"]))
        return 2
    if door["can_substitute"]:
        print("ВЕРДИКТ: НАХОДКИ — постоянная может ранжировать капитал под ярлыком наблюдения")
        return 1
    print("ВЕРДИКТ: в двери находок нет (каждый адаптер либо объявляет провенанс, "
          "либо постоянную до поля не допускает)")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS,
                    help="предел шагов разрешения значения (ВХОД прибора)")
    ap.add_argument("--json", action="store_true", help="печатать замер как JSON")
    args = ap.parse_args(argv)
    report = measure(max_steps=args.max_steps)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        if report["door_refused"] or report["door"]["unmeasured"]:
            return 2
        return 1 if report["door"]["can_substitute"] else 0
    return _print(report)


if __name__ == "__main__":
    raise SystemExit(main())
