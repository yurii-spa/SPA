"""spa_core/tests/_caller_record_gap.py — ступень с ТАКТОМ обязана называть ЗВАВШЕГО.

Заказ **G804 п. 3** приказа владельца «Portfolio CIO» (хвост ADR-804).

## Вопрос, на который прибор отвечает

ADR-411 (заказ G36 п. 1) и ADR-804 (заказ G801 п. 2) закрыли ОДИН класс у ДВУХ
ступеней по отдельности: ``generated_at`` — это ЧАСЫ, а не звавший, поэтому на
документе без записи о звавшем вопрос «эту отметку поставила СТУПЕНЬ или чья-то
РУКА» неизмерим ПО ПОСТРОЕНИЮ. Односторонность полная: отметка НЕ сменилась ⇒
ступень молчит (вывод верен); сменилась ⇒ **не известно НИЧЕГО**.

Вопрос встаёт не у всякой ступени, а ровно у той, у которой есть **ТАКТ**: срок
решает ФАЙЛ, артефакт внутри такта не переписывается, — и именно там «отметка
свежая» читают как «ступень работает». У ступени без такта каждый прогон пишет
заново, и подменить вывод о проводке отметка не может.

Поэтому прибор меряет ОДНО утверждение:

> **ступень, у которой есть такт, обязана нести измеренную запись о звавшем, и
> пропажа записи молчанием быть не вправе.**

## Почему мерка AST, а не подстрока — это ЗАМЕР, а не вкус

ADR-804 назвал девять ступеней класса ГРУБЫМ экраном (подстрока ``"invoked_by"``
в модуле, подстрока ``if_due``/``measurement_due`` для такта) и честно объявил
грубость вслух: «ошибаться он обязан в сторону находки; точный вердикт — работа
следующего цикла». Этот цикл перемерил обе оси разбором AST, и ответы по осям
РАЗНЫЕ:

* **ось записи — расхождений НОЛЬ** (15 против 15). Это «измерено и равно нулю»,
  а не «не измерено»: на сегодняшнем населении подстрока и разбор дают
  одинаковый вердикт у каждой ступени. Грубость мерки была свойством МЕТОДА, а
  не ошибкой вывода;
* **ось такта — ОДНО ложное срабатывание, и оно ошибается НЕ в сторону
  находки.** ``tact_gate_census`` содержит подстроки ``measurement_due`` и
  ``_refresh_if_due`` в ДОКСТРИНГЕ, потому что такты и есть его ПРЕДМЕТ
  (перепись гейтов такта, ADR-414/G39 п. 3), а такта у него нет и это сказано
  в коде вслух: «Гейта такта здесь нет, и это замер, а не поблажка». Грубый
  экран засчитал его в знаменатель И в числитель «уже несут запись», то есть
  приукрасил долю закрытых, а не нашёл лишнее.

Поэтому ось такта здесь — **параметр ``if_due`` в подписи функции**, а ось
записи — **ЗОВ ``call_provenance`` под ключом ``"invoked_by"``** (значение в
словарном литерале либо правая часть присваивания по ключу). Упоминание ключа
строкой вердикта не покупает (ADR-333), и объявление звавшего ПАРАМЕТРОМ — тоже:
переданный звавший есть утверждение ступени о себе.

## Три исхода различимы (инв. #17)

``carries`` · ``missing`` · ``no_tact`` · ``unmeasured``. Последнее — модуль,
которого нет на диске либо который не разбирается; это НЕ «запись отсутствует» и
НЕ ноль: ступень, пропавшая из дерева, и ступень без записи лечатся по-разному.
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass, field

#: Четыре исхода ступени. Перечень объявлен ЗДЕСЬ один раз и читается всеми
#: (храповик, проба приёмки): второй литеральный перечень тех же имён разошёлся
#: бы с первым молча — класс ADR-220. Исход, добавленный в `Census` и НЕ
#: дописанный сюда, из операнда выпадет, поэтому состав стережёт отдельный тест
#: рядом с храповиком.
OPERAND_BUCKETS: tuple[str, ...] = ("carries", "missing", "no_tact", "unmeasured")

#: Ключ, под которым запись о звавшем живёт в документе ступени.
RECORD_KEY = "invoked_by"

#: Имя параметра, которым ступень принимает решение о сроке.
TACT_PARAM = "if_due"

#: Имя прибора, дающего ИЗМЕРЕННУЮ запись о звавшем (ADR-411).
PROVENANCE_CALL = "call_provenance"


@dataclass(frozen=True)
class Stage:
    """Ступень и вердикт по ней. `reason` непуст ТОЛЬКО у `unmeasured`."""

    name: str
    module: str
    bucket: str
    reason: str | None = None


@dataclass
class Census:
    carries: tuple = ()
    missing: tuple = ()
    no_tact: tuple = ()
    unmeasured: tuple = ()
    stages_declared: int = 0

    def by_bucket(self) -> dict[str, tuple]:
        return {name: getattr(self, name) for name in OPERAND_BUCKETS}

    def names(self, bucket: str) -> tuple:
        return tuple(sorted(s.name for s in getattr(self, bucket)))


def _call_name(node: ast.AST) -> str | None:
    """Имя зовомого: `f(…)` → `f`, `m.f(…)` → `f`. Иначе `None`."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def analyse_source(src: str, *, module: str) -> tuple[str, str, str | None]:
    """`(ось такта, ось записи, причина «не измерено»)` по ОДНОМУ модулю.

    Оси намеренно считаются раздельно и возвращаются раздельно: слить их в один
    булев вердикт значило бы потерять ровно то различие, из-за которого грубый
    экран ADR-804 ошибся на `tact_gate_census` — у него подстрока такта есть, а
    такта нет.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:  # pragma: no cover — ловится сценой пробы
        return "unmeasured", "unmeasured", f"модуль не разбирается: {exc}"

    tact = "absent"
    record = "absent"
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            declared = [a.arg for a in
                        (*args.posonlyargs, *args.args, *args.kwonlyargs)]
            if TACT_PARAM in declared:
                tact = "in_signature"
        # запись под ключом в словарном литерале: {"invoked_by": call_provenance(…)}
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (isinstance(key, ast.Constant) and key.value == RECORD_KEY
                        and _call_name(value) == PROVENANCE_CALL):
                    record = "under_key"
        # запись присваиванием по ключу: doc["invoked_by"] = call_provenance(…)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value == RECORD_KEY
                        and _call_name(node.value) == PROVENANCE_CALL):
                    record = "under_key"
    return tact, record, None


def measure(*, registry: dict | None = None,
            read_source=None, root: str | pathlib.Path = ".") -> Census:
    """Перепись ступеней по ОДНОМУ реестру проводки.

    `registry` берётся у `findings_bridge.CENSUS_PRODUCT` — своей копии перечня
    ступеней здесь нет НАМЕРЕННО: второй перечень разошёлся бы с первым молча, и
    ступень, забытая в копии, выпала бы из переписи, не покраснев нигде
    (класс ADR-220). `read_source` — вход сцены: проба подменяет чтение, а не
    дерево, поэтому контроль в обе стороны не требует копии репозитория.
    """
    if registry is None:
        from spa_core.monitoring import findings_bridge  # noqa: PLC0415
        registry = findings_bridge.CENSUS_PRODUCT
    base = pathlib.Path(root)
    if read_source is None:
        def read_source(rel: str) -> str | None:
            path = base / rel
            try:
                return path.read_text(encoding="utf-8")
            except OSError:
                return None

    buckets: dict[str, list] = {name: [] for name in OPERAND_BUCKETS}
    for name in sorted(registry):
        module = (registry[name] or {}).get("module")
        if not module:
            buckets["unmeasured"].append(Stage(
                name, "", "unmeasured",
                "реестр не называет модуль ступени — читать нечего"))
            continue
        src = read_source(module)
        if src is None:
            buckets["unmeasured"].append(Stage(
                name, module, "unmeasured",
                f"модуль не прочитан: {module}"))
            continue
        tact, record, reason = analyse_source(src, module=module)
        if reason is not None:
            buckets["unmeasured"].append(Stage(name, module, "unmeasured", reason))
        elif tact != "in_signature":
            buckets["no_tact"].append(Stage(name, module, "no_tact"))
        elif record == "under_key":
            buckets["carries"].append(Stage(name, module, "carries"))
        else:
            buckets["missing"].append(Stage(name, module, "missing"))

    return Census(carries=tuple(buckets["carries"]), missing=tuple(buckets["missing"]),
                  no_tact=tuple(buckets["no_tact"]),
                  unmeasured=tuple(buckets["unmeasured"]),
                  stages_declared=len(registry))


def operand(census: Census) -> dict[str, int]:
    """Разложение операнда по исходам: `{имя исхода: сколько ступеней}`."""
    return {name: len(getattr(census, name)) for name in OPERAND_BUCKETS}


@dataclass
class Verdict:
    """Вердикт переписи: три исхода РАЗЛИЧИМЫ (инв. #17).

    * `unmeasured` непуст — у замера или у объявления нет предмета, и согласием
      это не печатается НИКОГДА;
    * `problems` непуст — класс ВЫРОС либо операнд разошёлся, и каждая строка
      НАЗЫВАЕТ ступень или ведро с НАПРАВЛЕНИЕМ;
    * оба пусты — сошлось.
    """

    measured: dict
    declared: dict | None = None
    declared_missing: tuple = ()
    unmeasured: str | None = None
    problems: list = field(default_factory=list)


def verdict(census: Census, baseline: dict) -> Verdict:
    """Сверка с объявлением — В ПРИБОРЕ, а не в храповике.

    Та же причина, что у `_fixture_schema_gap.operand_verdict`, и она ИЗМЕРЕНА
    (ADR-803): сверка, живущая только в храповике над ЖИВОЙ базой, аварию
    воспроизвести не может, не правя живую базу, — мутация такой сверки
    ВЫЖИВАЕТ. Прибор принимает объявление ВХОДОМ, поэтому порванное звено
    краснеет на собранной сцене.
    """
    measured = operand(census)
    if not isinstance(baseline, dict):
        return Verdict(measured, None, (), unmeasured=(
            f"объявление подано не документом, а `{type(baseline).__name__}` — "
            f"читать нечего"))
    if census.unmeasured:
        return Verdict(measured, baseline, (), unmeasured=(
            "ступени НЕ ИЗМЕРЕНЫ (" + ", ".join(
                f"{s.name}: {s.reason}" for s in census.unmeasured) + ")"))
    declared_missing = baseline.get("missing")
    if not isinstance(declared_missing, list):
        return Verdict(measured, baseline, (), unmeasured=(
            "в базе нет объявленного перечня `missing` списком — сверять не с чем"))
    declared_total = baseline.get("missing_total")
    if not isinstance(declared_total, int) or isinstance(declared_total, bool):
        return Verdict(measured, baseline, tuple(declared_missing), unmeasured=(
            "в базе нет объявленного итога `missing_total` числом — "
            "сверять не с чем"))
    if not census.stages_declared:
        return Verdict(measured, baseline, tuple(declared_missing), unmeasured=(
            "реестр проводки не объявляет ни одной ступени — предмета у замера "
            "нет, и нулём это не считается"))

    problems: list[str] = []
    # Объявление сверяется САМО С СОБОЙ: иначе остаётся честный выход
    # «перепечатал итог, перечень не тронул» (класс ADR-803).
    if len(declared_missing) != declared_total:
        problems.append(
            f"  ОБЪЯВЛЕНИЕ НЕ СОШЛОСЬ С СОБОЙ: `missing_total` {declared_total}, "
            f"а имён в `missing` {len(declared_missing)}")
    appeared = sorted(set(census.names("missing")) - set(declared_missing))
    for name in appeared:
        stage = next(s for s in census.missing if s.name == name)
        problems.append(
            f"  ПОЯВИЛАСЬ {name} ({stage.module}): у ступени есть такт "
            f"(параметр `{TACT_PARAM}`), а измеренной записи о звавшем "
            f"(зов `{PROVENANCE_CALL}` под ключом `{RECORD_KEY}`) нет")
    return Verdict(measured, baseline, tuple(declared_missing), problems=problems)
