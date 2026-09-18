"""Где живёт решение «пора ли производить» — перепись гейтов такта.

Заказ **G39, п. 3** приказа владельца «Portfolio CIO» (хвост ADR-414).

## Вопрос, на который прибор отвечает

ADR-414 закрыл у ОДНОГО производителя класс ADR-220 («две копии одной мерки»):
гейт такта был сведён в одно место — внутрь ``run()``, — а ``main`` стал
делегировать. Заказ назвал остаток прямо: *«Сколько ещё производителей держат
свой ``--if-due`` отдельно от ``run`` — не мерено; это перепись, а не догадка»*.

Прибор отвечает на вопрос **«ГДЕ у производителя лежит решение о сроке»**, и
различает три положения:

* ``gate_in_producer`` — решение внутри производящей функции. Любой звавший
  (ступень моста, рука цикла, будущий третий) гейтится ОДНИМ правилом;
* ``gate_at_cli_only`` — решение только в ``main``. Производящая функция
  открыта, и **второй звавший обязан завести свою копию правила** — то самое
  расхождение, которое ADR-220 называет молчаливым;
* ``two_copies`` — решение и в ``main``, и в производящей функции. Копии уже
  две, и разойтись они могут в любую сторону.

## Почему «вторая копия» — не вкусовщина

Копия расходится молча: обе стороны выглядят исправно, потому что каждая честно
отвечает на свой вопрос. Замер ADR-414 показал соседний случай того же корня —
рука и ступень боролись за ОДИН недельный такт, и наблюдение объявило бы
исправную проводку молчащей. Там копий правила было две по факту проводки; здесь
переписывается, у скольких производителей такая вторая копия обязана появиться,
как только у них возникнет второй звавший.

## Правило населения объявлено, и его слепота ИЗМЕРЕНА, а не обещана

Гейт опознаётся ПО ИМЕНИ предиката (``…_due``/``is_due``/``should_run``), и это
гипотеза, а не вердикт: классификация по имени ошибается в обе стороны.

* **Ложное срабатывание** — предикат с подходящим именем, который сроком не
  управляет. Лечится тем, что в население входит не определение, а **вызов**,
  чьё значение решает, производить ли: одного имени мало.
* **Ложное отрицание** — гейт без имени-предиката (сравнение возраста прямо в
  теле производителя). Такой случай правилу имени не виден, поэтому его
  поверхность **считается отдельно** (``surface_outside_name_rule``): модуль
  пишет артефакт и держит константу периодичности, а названного предиката у
  него нет. Число не выдаётся за находку — оно называет, насколько узко
  правило имени, чтобы «не нашли» не читалось как «нет».

## Три исхода различимы (инв. #17) и учёт тождественен

Файл, который не разобрался, попадает в ``unreadable`` С ПРИЧИНОЙ, а не
пропускается: ``scanned == classified + unreadable`` закреплено тестом, и молча
уронить вход нельзя по построению. Не прочитан сам корень дерева ⇒ статус
``UNMEASURED`` и ненулевой код возврата: «не измерено» никогда не выдаётся за
«чисто».

## Чего перепись НЕ доказывает

* **Что ``gate_in_producer`` верен.** Прибор читает, ГДЕ лежит решение, а не
  правильно ли оно считает срок. Единственная копия может быть и неверной.
* **Что у ``gate_at_cli_only`` уже есть вред.** Вторая копия обязана появиться
  при втором звавшем; пока звавший один, расхождению неоткуда взяться. Это
  перепись поверхности, а не перечень аварий.
* **Что население полно.** См. выше: правило имени узко, ширина названа числом.
* **Что сам прибор в население входит.** Гейта такта у него нет — не по
  исключению, а потому что зов стоит секунды (цена названа в ADR-415).
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # запуск ПО ПУТИ, а не пакетом
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.monitoring.call_provenance import describe as provenance_line  # noqa: E402,E501
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = "tact_gate_census.json"
#: Какой МОДУЛЬ собрал документ (константа; на вопрос «кто позвал» отвечает
#: `invoked_by`, и это разные вопросы — ADR-412).
PRODUCER = "spa_core/monitoring/tact_gate_census.py"

#: Каталоги населения. `scripts/` и `spa_core/` — ровно те два дерева, из
#: которых в этом репозитории запускают производителей артефактов.
SCAN_DIRS = ("spa_core", "scripts")

#: Имя предиката срока. Токенами, а не подстрокой: подстрока «due» живёт в
#: `overdue_at`, `dues`, `residue` — и дала бы находку из слова.
_DUE_TOKENS = {"due"}
_GATE_NAMES = re.compile(r"^(is_due|should_run)$")

#: Константа периодичности — след такта у модуля БЕЗ названного предиката.
_TACT_CONST = re.compile(r"(TACT|_DAYS|_HOURS|_SECONDS|INTERVAL|PERIOD|SLO)")

#: Имя производящей функции, которое в этом репозитории объявлено формой вызова
#: ступени моста (`<модуль>.run(root=…)`). Нужно не для классификации, а чтобы
#: находка называла, ЧТО именно останется негейтированным.
_PRODUCER_FUNCS = ("run", "build", "measure", "generate")

CLASS_IN_PRODUCER = "gate_in_producer"
CLASS_CLI_ONLY = "gate_at_cli_only"
CLASS_TWO_RULES = "two_rules"
_FINDING_CLASSES = (CLASS_CLI_ONLY, CLASS_TWO_RULES)


class NotMeasured(RuntimeError):
    """Корень населения не прочитан — третий исход, а не пустая перепись."""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def is_gate_name(name: str) -> bool:
    """Имя ли это предиката срока — ПО ТОКЕНАМ, не по подстроке.

    `overdue_at` содержит «due» подстрокой и предикатом срока не является;
    `measurement_due`, `publication_due`, `reveal_due`, `_refresh_if_due` —
    являются. Токенизация по `_` закрывает класс, список исключений лечил бы
    поводы (урок #556).
    """
    if _GATE_NAMES.match(name):
        return True
    tokens = [t for t in name.split("_") if t]
    return bool(tokens) and tokens[-1] in _DUE_TOKENS


def _call_name(node: ast.Call) -> Optional[str]:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


class _Walker(ast.NodeVisitor):
    """Собирает вызовы предикатов срока вместе с ОХВАТЫВАЮЩЕЙ функцией.

    Охватывающая функция — координата ответа: «в `main`» и «в `run`» суть
    разные положения одного и того же вызова, и различить их можно только по
    ней. Модульный уровень записывается отдельным именем `<module>`: гейт,
    исполняемый на импорте, не принадлежит ни одной функции и делать вид, что
    принадлежит, нельзя.
    """

    def __init__(self) -> None:
        self.stack: List[str] = []
        self.gate_calls: List[Tuple[str, str, int]] = []   # (предикат, охват, строка)
        self.defined: List[str] = []
        self.func_names: List[str] = []

    def _enter(self, node) -> None:
        self.func_names.append(node.name)
        if is_gate_name(node.name):
            self.defined.append(node.name)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _enter          # noqa: N815
    visit_AsyncFunctionDef = _enter     # noqa: N815

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        name = _call_name(node)
        if name and is_gate_name(name):
            enclosing = self.stack[-1] if self.stack else "<module>"
            self.gate_calls.append((name, enclosing, node.lineno))
        self.generic_visit(node)


def classify(gate_calls: List[Tuple[str, str, int]]) -> Optional[str]:
    """Вердикт решает вопрос «ГЕЙТИРОВАН ЛИ ПРОИЗВОДИТЕЛЬ», а не число мест зова.

    Первая редакция считала находкой сам факт «предикат зовётся и из ``main``,
    и из производителя», и **первый же прогон показал, что это ложное
    срабатывание**: у ``ceo_agent_v2``/``strategy_agent_v2`` ``should_run`` —
    ОДНА чистая функция, ``run_ceo`` ею гейтится, а ``main --check`` зовёт её,
    чтобы ПОКАЗАТЬ вердикт. Две копии ПРАВИЛА и два ВЫЗОВА одного правила —
    разные вещи, и ADR-220 про первое. Ошибку нашёл замер, а не перечитывание.

    Поэтому:

    * гейт есть хоть у одной функции, кроме ``main`` ⇒ производитель гейтится
      любым звавшим — ``gate_in_producer``;
    * все вызовы гейта в ``main`` ⇒ производящая функция открыта, и второй
      звавший обязан завести свою копию — ``gate_at_cli_only``;
    * ``main`` и производитель судят о сроке РАЗНЫМИ предикатами ⇒ правил два,
      и разойтись они могут молча — ``two_rules``.
    """
    if not gate_calls:
        return None
    in_main = {name for name, enclosing, _ in gate_calls if enclosing == "main"}
    in_other = {name for name, enclosing, _ in gate_calls if enclosing != "main"}
    if not in_other:
        return CLASS_CLI_ONLY
    if in_main and not (in_main & in_other):
        return CLASS_TWO_RULES
    return CLASS_IN_PRODUCER


def _writes_artifact(tree: ast.AST) -> bool:
    """Пишет ли модуль артефакт — по вызову КАНОНИЧЕСКОГО писателя.

    Только ``atomic_save``: инв. #5 предписывает писать состояние им, поэтому
    он и есть признак производителя. Считать признаком любой ``write_text``
    значило бы записать в производители всякий модуль, который пишет отчёт в
    ``/tmp``, — поверхность раздулась бы и перестала что-либо ограничивать.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) == "atomic_save":
            return True
    return False


def _compares_tact_const(tree: ast.AST) -> bool:
    """Есть ли СРАВНЕНИЕ с константой периодичности — след безымянного гейта.

    Одного объявления константы мало: ``MAX_AGE_HOURS`` может стоять в отчёте.
    Гейт обязан по ней ВЕТВИТЬСЯ, поэтому ищется узел сравнения, у которого
    одна из сторон — такая константа.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for side in [node.left, *node.comparators]:
            if isinstance(side, ast.Name) and side.id.isupper() \
                    and _TACT_CONST.search(side.id):
                return True
    return False


def population(root: Path) -> List[Path]:
    """Файлы населения: `spa_core/` и `scripts/`, без тестов и без себя.

    Тесты исключены не для удобства: тест не производитель артефакта, и его
    гейт ничего не решает о сроке продукта. Сам прибор исключён потому, что
    гейта такта у него нет — попади он в население, он был бы вне его и так.
    """
    if not root.is_dir():
        raise NotMeasured(f"корень дерева не прочитан: {root}")
    out: List[Path] = []
    for sub in SCAN_DIRS:
        base = root / sub
        if not base.is_dir():
            raise NotMeasured(f"каталог населения не прочитан: {base}")
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if "/tests/" in f"/{rel}" or path.name.startswith("test_"):
                continue
            out.append(path)
    if not out:
        raise NotMeasured(f"в дереве {root} не нашлось ни одного файла населения")
    return out


def measure(root: Path, *, now: Optional[dt.datetime] = None) -> dict:
    """Перепись: каждый файл населения ложится ровно в одну корзину."""
    root = Path(root)
    files = population(root)
    rows: List[dict] = []
    unreadable: List[dict] = []
    surface: List[str] = []
    no_gate = 0

    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except Exception as exc:  # noqa: BLE001
            unreadable.append({"module": rel, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        walker = _Walker()
        walker.visit(tree)
        verdict = classify(walker.gate_calls)
        if verdict is None:
            no_gate += 1
            if _writes_artifact(tree) and _compares_tact_const(tree):
                surface.append(rel)
            continue
        holders = sorted({enclosing for _, enclosing, _ in walker.gate_calls})
        rows.append({
            "module": rel,
            "verdict": verdict,
            "predicates": sorted({name for name, _, _ in walker.gate_calls}),
            "holders": holders,
            "lines": [line for _, _, line in walker.gate_calls],
            # Что именно останется негейтированным у второго звавшего: имена
            # производящих функций модуля, которые решения о сроке не несут.
            "ungated_producers": sorted(
                n for n in walker.func_names
                if n in _PRODUCER_FUNCS and n not in holders),
        })

    # ПОРЯДОК строк — утверждение, а не косметика. Отчёт усекается (`max_rows`),
    # а усечение режет ХВОСТ, значит голова обязана нести сильнейшее
    # свидетельство. Оставь порядок обхода дерева — и находка окажется в хвосте
    # именно потому, что `scripts/` идёт после `spa_core/`: живой контроль 18.09
    # показал ровно это, офис напечатал «только в CLI 1» и не назвал КОГО.
    rows.sort(key=lambda r: (r["verdict"] not in _FINDING_CLASSES, r["module"]))
    counts = {
        CLASS_IN_PRODUCER: sum(1 for r in rows if r["verdict"] == CLASS_IN_PRODUCER),
        CLASS_CLI_ONLY: sum(1 for r in rows if r["verdict"] == CLASS_CLI_ONLY),
        CLASS_TWO_RULES: sum(1 for r in rows if r["verdict"] == CLASS_TWO_RULES),
        "no_gate": no_gate,
        "unreadable": len(unreadable),
    }
    findings = [r for r in rows if r["verdict"] in _FINDING_CLASSES]
    return {
        "generated_at": (now or _utcnow()).isoformat(),
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=root),
        "status": "FINDING" if findings else "CLEAN",
        "question": "где у производителя лежит решение «пора ли производить»",
        "population_rule": (
            "spa_core/ + scripts/, без тестов; в население входит МОДУЛЬ, в котором "
            "есть ВЫЗОВ предиката срока (имя по токенам: …_due / is_due / should_run)"
        ),
        "scanned": len(files),
        "counts": counts,
        "rows": rows,
        "unreadable": unreadable,
        # Ширина слепоты правила имени — число, а не обещание.
        "surface_outside_name_rule": sorted(surface),
        "what_it_does_not_prove": [
            "что единственная копия гейта считает срок ВЕРНО — прибор читает место, не арифметику",
            "что у gate_at_cli_only уже есть вред: вторая копия обязана появиться при ВТОРОМ звавшем",
            "что население полно — правило имени узко, ширина названа surface_outside_name_rule",
        ],
    }


def report(doc: dict, *, max_rows: int = 20) -> List[str]:
    """Строки отчёта. Единственное место, где перепись превращается в текст."""
    status = str(doc.get("status"))
    if status == "UNMEASURED":
        return [f"НЕ ИЗМЕРЕНО — {observed(doc, 'reason', kind=str) or 'причина не записана'}"]
    counts = observed(doc, "counts", kind=dict) or {}
    scanned = doc.get("scanned")
    out = [
        f"где лежит решение о сроке (заказ G39 п. 3): {status} · "
        f"в производителе {counts.get(CLASS_IN_PRODUCER)} · "
        f"только в CLI {counts.get(CLASS_CLI_ONLY)} · "
        f"два правила {counts.get(CLASS_TWO_RULES)}",
        f"[ЗВАВШИЙ] {provenance_line(observed(doc, 'invoked_by', kind=dict))}",
        f"[УЧЁТ] осмотрено {scanned} = разобрано "
        f"{(counts.get(CLASS_IN_PRODUCER, 0) + counts.get(CLASS_CLI_ONLY, 0) + counts.get(CLASS_TWO_RULES, 0) + counts.get('no_gate', 0))}"
        f" + не разобрано {counts.get('unreadable')}",
    ]
    findings = [r for r in (doc.get("rows") or [])
                if r["verdict"] in _FINDING_CLASSES]
    for row in findings[:max_rows]:
        ungated = ", ".join(row["ungated_producers"]) or "—"
        out.append(
            f"[НАХОДКА] {row['module']}: {row['verdict']} · предикат "
            f"{', '.join(row['predicates'])} лежит в {', '.join(row['holders'])} · "
            f"без гейта остаётся: {ungated}")
    if len(findings) > max_rows:
        # Умолчание об укорочении и есть способ соврать усечением: читатель
        # прочёл бы перечень как полный.
        out.append(f"[…] показаны {max_rows} находки из {len(findings)}; "
                   f"полный перечень — в артефакте")
    surface = doc.get("surface_outside_name_rule") or []
    out.append(
        f"[ГРАНИЦА ПРАВИЛА ИМЕНИ] модулей с константой такта и записью артефакта, "
        f"но БЕЗ названного предиката: {len(surface)}"
        + (f" — {', '.join(surface[:5])}" if surface else ""))
    out.append("НЕ ДОКЛАДЫВАЕТ: верна ли арифметика срока у единственной копии; "
               "есть ли у gate_at_cli_only второй звавший СЕГОДНЯ")
    return out


def format_report(doc: dict, *, max_rows: int = 5) -> List[str]:
    """Отрисовка для шага 0-офис. Второй копии правила отрисовки здесь НЕТ:
    ветка офиса делегирует сюда, а эта функция — в ``report``."""
    lines = report(doc, max_rows=max_rows)
    if str(doc.get("status")) == "FINDING":
        lines[0] = f"⚠️ {lines[0]}"
    return lines


def run(root: str | Path = _ROOT, *, dest: Optional[Path] = None,
        data_dir: Optional[Path] = None, write: bool = True,
        now: Optional[dt.datetime] = None) -> dict:
    """Один прогон переписи для ступени моста.

    **Гейта такта здесь нет, и это замер, а не поблажка.** У соседей по семье
    (``list_identity_census``, ``python_reader_clock_doors``) зов поднимает
    подпроцессы и стоит минуты — там срок обязан решать ФАЙЛ. Здесь зов есть
    разбор AST в одном процессе и стоит секунды (ADR-415), поэтому недельный
    такт не купил бы ничего, а завёл бы ровно ту вторую копию правила, которую
    перепись и ищет.
    """
    root = Path(root)
    target = (Path(dest) if dest is not None
              else (Path(data_dir) if data_dir is not None else root / "data") / ARTIFACT)
    try:
        doc = measure(root, now=now)
    except NotMeasured as exc:
        doc = {
            "generated_at": (now or _utcnow()).isoformat(),
            "generated_by": PRODUCER,
            "invoked_by": call_provenance(tree_root=root),
            "status": "UNMEASURED",
            "reason": str(exc),
        }
    if write:
        atomic_save(doc, str(target))
    return {"measured": doc.get("status") != "UNMEASURED", "doc": doc,
            "artifact": str(target)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="перепись гейтов такта: где лежит решение о сроке (G39 п. 3)")
    ap.add_argument("--root", default=str(_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    outcome = run(Path(args.root),
                  dest=Path(args.out) if args.out else None,
                  write=not args.no_write)
    doc = outcome["doc"]
    for line in report(doc):
        print(line)
    return {"UNMEASURED": 2, "FINDING": 1}.get(str(doc.get("status")), 0)


if __name__ == "__main__":
    raise SystemExit(main())
