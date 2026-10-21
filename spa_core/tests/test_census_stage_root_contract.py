"""Ступень переписей: `run(root=…)` значит КОРЕНЬ ДЕРЕВА у ВСЕХ, а не у части.

Замер цикла #564. `findings_bridge` зовёт каждую перепись ступени одинаково —
`run(root=args.root)`, где `args.root` это корень дерева, — и каждая обязана
вывести каталог данных как `root / "data"`. Две из двенадцати этого не делали:
они принимали `root` как САМ каталог данных, поэтому читали пустоту и клали
свой артефакт **в корень репозитория**.

Знаки у двух носителей РАЗНЫЕ, и разница решает, почему проверка нужна:

* `rate_observation_census` — **громко**: документ приходил без ключа `pairs`,
  печать ступени падала `KeyError: 'pairs'`, ступень писала `skipped` с
  причиной, шаг 0-офис печатал «❌ НЕ ПРОЧИТАН … причина пропуска записана»;
* `journal_population_backfill` — **тихо**: исключения не было ни одного,
  ступень докладывала успех, артефакт молча уезжал в корень дерева, а шаг
  0-офис печатал «бегун ступень звал и о пропуске НЕ сообщил — файла всё
  равно нет». Улика была физической: файл лежал в корне рабочего дерева.

Fail-OPEN тише красного, поэтому опаснее. Проверка ниже меряет **поведение при
том зове, каким зовёт потребитель**, а не форму кода: «в теле есть слово
`data`» — признак структурный, и он на обоих носителях был ИСТИНЕН.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import importlib
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_BRIDGE = Path(__file__).resolve().parents[2] / "spa_core" / "monitoring" / "findings_bridge.py"

#: Зов ступени дословно: `from … import X` и следом `… = X.run(root=args.root)`.
#: Население берётся ИЗ ПОТРЕБИТЕЛЯ, а не из списка в голове автора: перепись,
#: добавленная завтра, попадает под проверку сама.
#:
#: **Поправка цикла #565 (заказ #564).** В первой редакции приёмник записи стоял
#: как `_\w+` — с ОБЯЗАТЕЛЬНЫМ ведущим подчёркиванием. Это свойство того, как
#: назвал переменные автор четырёх последних переписей (`_ulc`, `_lps`, `_sms`,
#: `_drri`), а НЕ свойство зова: соседние сорок зовутся дословно так же и пишут
#: в `rrep`, `trep`, `crep`, `afd`. Под храповиком оказались **12 из 42**, и
#: обещание «завтрашняя перепись попадает под проверку сама» держалось на том,
#: угадает ли завтрашний автор соглашение об имени переменной. Ведущее
#: подчёркивание снято; полнота населения закреплена отдельной проверкой ниже —
#: иначе сужение формы зова снова прошло бы молча.
_CALL = re.compile(
    r"from spa_core\.monitoring import (\w+)\n\s+\w+\s*=\s*\1\.run\(root=args\.root\)")

#: Независимый вывод того же населения: имя модуля берётся из строки зова
#: `X.run(root=args.root)` БЕЗ оглядки на предшествующий импорт и на имя
#: приёмника. Две дороги к одному числу — единственный способ заметить, что
#: форма зова сузилась: счётчик, выведенный одной формой, о своей слепоте
#: сказать не может.
_CALL_INDEPENDENT = re.compile(r"\b(\w+)\.run\(root=args\.root\)")


def _bridge_import_names(src: str) -> dict[str, str]:
    """Локальное имя в мосте → имя модуля `spa_core.monitoring.*`, как его импортировали.

    Нужна потому, что `X` в `X.run(root=args.root)` — это ИМЯ ПЕРЕМЕННОЙ, а не модуля:
    мост пишет `from spa_core.monitoring import acceptance_tree_capability as _atc`, и
    прежний вывод импортировал несуществующий `spa_core.monitoring._atc` — сторож падал
    `ModuleNotFoundError` до первой проверки (контрольный прогон №13–14). Импорты
    читаются по всему файлу, включая тела функций: мост импортирует переписи внутри
    шагов.
    """
    names: dict[str, str] = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module == "spa_core.monitoring":
            for a in node.names:
                names[a.asname or a.name] = a.name
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.asname and a.name.startswith("spa_core.monitoring."):
                    names[a.asname] = a.name.rsplit(".", 1)[1]
    return names


#: Нет литерального значения у аргумента зова — воспроизвести зов потребителя нельзя.
_NOT_LITERAL = object()


def stage_calls() -> dict[str, list[dict]]:
    """Зовы ступени по РАЗБОРУ AST: модуль → список наборов дополнительных аргументов.

    Зов ступени — любой `X.run(...)` с `root=args.root`. Регулярная форма
    `X.run(root=args.root)` (прежний вывод) теряла зовы с дополнительными аргументами —
    замер 2026-10-22: `artifact_stamp_clock_doors.run(root=args.root, if_due=True,
    sandbox=True)` и `_ldu.run(root=args.root, if_due=True)` (ledger_day_unit_census)
    вне проверки. `X` — переменная: разрешается по импортам самого моста.
    """
    src = _BRIDGE.read_text(encoding="utf-8")
    imported = _bridge_import_names(src)
    out: dict[str, list[dict]] = {}
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run" and isinstance(node.func.value, ast.Name)):
            continue
        kws = {k.arg: k.value for k in node.keywords if k.arg}
        if "root" not in kws or ast.unparse(kws["root"]) != "args.root" or node.args:
            continue
        extra = {}
        for k, v in kws.items():
            if k == "root":
                continue
            try:
                extra[k] = ast.literal_eval(v)
            except ValueError:
                extra[k] = _NOT_LITERAL
        name = imported.get(node.func.value.id, node.func.value.id)
        if extra not in out.setdefault(name, []):
            out[name].append(extra)
    return out


def stage_censuses() -> list[str]:
    """Население ступени = ВСЕ, кого она зовёт `….run(root=args.root[, …])` — по AST.

    Замер #565: импорт-соседство теряло население тремя способами; полное население
    тогда — 45. Имя перед `.run` разрешается в модуль по импортам моста (псевдоним
    `as _atc` — не модуль); имя без импорта остаётся как есть и, если это не модуль,
    громко падает на импорте.
    """
    return sorted(stage_calls())


def stage_censuses_by_import_adjacency() -> list[str]:
    """Прежняя форма вывода — оставлена как ПОДМНОЖЕСТВО под перекрёстной сверкой."""
    return sorted(set(_CALL.findall(_BRIDGE.read_text(encoding="utf-8"))))


class CensusStageRootContract(unittest.TestCase):

    def test_the_population_is_not_empty(self) -> None:
        """Ноль переписей = проверка ни о чём. Молчаливого «чисто» здесь нет."""
        names = stage_censuses()
        self.assertGreaterEqual(len(names), 10, (
            f"из {_BRIDGE.name} вычитано переписей: {len(names)} — форма зова "
            "изменилась, и проверка отвечает не на тот вопрос"))

    def test_the_population_matches_an_independent_derivation(self) -> None:
        """Полнота населения, выведенная ВТОРОЙ дорогой (находка цикла #565).

        Порог «не меньше десяти» прошлой редакции был зелёным при **12 из 42**:
        форма зова требовала ведущего подчёркивания в имени приёмника, и тридцать
        переписей, зовущихся ДОСЛОВНО так же, лежали вне храповика. Нижняя граница
        о такой слепоте сказать не может — она истинна и на подмножестве.

        Поэтому то же население выводится независимо: по строке `X.run(root=args.root)`
        без оглядки на импорт и на имя приёмника. Расхождение = форма зова сузилась.
        """
        population = set(stage_censuses())
        adjacency = set(stage_censuses_by_import_adjacency())
        self.assertEqual(
            adjacency - population, set(), (
                "импорт-соседство нашло перепись, которой нет в полном "
                f"населении: {sorted(adjacency - population)} — одна из двух "
                "форм разошлась с зовом, и какая именно, надо разобрать"))
        self.assertGreaterEqual(len(population), 45, (
            f"население ступени: {len(population)} — форма зова сузилась; "
            "храповик молча стал охранять подмножество. Замер #565: 45"))
        self.assertLess(len(adjacency), len(population), (
            "импорт-соседство внезапно покрыло ВСЁ население — либо ступень "
            "переписана, либо сузилась независимая форма. Замер #565: 12 из 45, "
            "и на этой разнице стои́т смысл перекрёстной сверки"))

    def test_every_member_resolves_to_an_existing_module(self) -> None:
        """Полнота населения: ни одного неразрешённого имени — неизвестный импорт КРАСНЫЙ, а не пропуск.

        Имя перед `.run(root=args.root)` — переменная. Псевдоним моста (`acceptance_tree_capability
        as _atc` и соседи) обязан разрешиться в настоящий модуль; имя, не ставшее модулем,
        есть неизвестный импорт, и проверка о нём говорит громко, а не сужает население.
        """
        src = _BRIDGE.read_text(encoding="utf-8")
        raw = set(_CALL_INDEPENDENT.findall(src))
        imported = _bridge_import_names(src)
        aliases = {n: imported[n] for n in raw if n in imported and imported[n] != n}
        self.assertIn("_atc", aliases, "псевдоним _atc обязан быть найден и разрешён")
        self.assertEqual(aliases["_atc"], "acceptance_tree_capability")
        monitoring = _BRIDGE.parent
        population = set(stage_censuses())
        unresolved = sorted(n for n in population if not (monitoring / f"{n}.py").is_file())
        self.assertEqual(unresolved, [], f"неизвестный импорт в населении ступени: {unresolved}")
        regex_form = {imported.get(n, n) for n in raw}
        self.assertEqual(regex_form - population, set(),
                         "разбор AST обязан покрыть всё, что видит регулярная форма")
        for extra_kw in ("artifact_stamp_clock_doors", "ledger_day_unit_census"):
            self.assertIn(extra_kw, population, f"зов с доп. аргументами потерян: {extra_kw}")
        non_literal = {n: c for n, cs in stage_calls().items() for c in cs
                       if any(v is _NOT_LITERAL for v in c.values())}
        self.assertEqual(non_literal, {}, f"зов потребителя не воспроизвести: {non_literal}")

    def test_every_stage_census_puts_its_artifact_under_root_data(self) -> None:
        """Артефакт обязан лечь в `<корень>/data`, а не в корень дерева."""
        misplaced: dict[str, list[str]] = {}
        unmeasured: dict[str, str] = {}
        measured = 0
        for name, calls in sorted(stage_calls().items()):
            module = importlib.import_module(f"spa_core.monitoring.{name}")
            for extra in calls:            # зов — так, как его делает потребитель (те же аргументы)
                label = name if not extra else f"{name}{sorted(extra.items())}"
                with TemporaryDirectory() as tmp:
                    tree = Path(tmp)
                    (tree / "data").mkdir()
                    before = {p.name for p in tree.iterdir()}
                    try:
                        module.run(root=str(tree), **extra)
                    except Exception as exc:  # noqa: BLE001
                        unmeasured[label] = f"{type(exc).__name__}: {exc}"
                        continue
                    strays = sorted(p.name for p in tree.iterdir()
                                    if p.name not in before)
                    measured += 1
                    if strays:
                        misplaced[label] = strays
        self.assertEqual(misplaced, {}, (
            f"перепись положила артефакт в КОРЕНЬ дерева: {misplaced}. Шаг "
            "0-офис ищет его в `data/` и напечатает «❌ НЕ ПРОЧИТАН», а ступень "
            "при этом доложит успех — fail-OPEN. `run(root=…)` обязан выводить "
            "каталог как `root / \"data\"`; явный каталог передаётся `data_dir=`."))
        self.assertEqual(unmeasured, {}, (
            f"перепись не пережила зов потребителя на пустом дереве: "
            f"{unmeasured}. Это НЕ «чисто»: ступень запишет `skipped`, "
            "артефакта не будет, и шаг 0-офис скажет «НЕ ПРОЧИТАН»."))
        self.assertGreater(measured, 0, "не измерено ни одной переписи")

    def test_the_check_would_redden_on_the_defect_it_was_written_for(self) -> None:
        """Положительный контроль: воспроизводит дефект #564 дословно.

        Перепись, принимающая `root` как САМ каталог данных, обязана быть
        поймана. Проверка, никогда не видевшая настоящей поломки, — украшение,
        а эта поломка жила в двух модулях разом.
        """
        with TemporaryDirectory() as tmp:
            tree = Path(tmp)
            (tree / "data").mkdir()
            before = {p.name for p in tree.iterdir()}

            def broken_run(root: str) -> None:
                (Path(root) / "artifact.json").write_text("{}", encoding="utf-8")

            broken_run(str(tree))
            strays = sorted(p.name for p in tree.iterdir() if p.name not in before)
            self.assertEqual(strays, ["artifact.json"],
                             "мера не видит артефакта, легшего в корень — тогда "
                             "она не поймала бы и настоящий дефект")

    def test_an_explicit_data_dir_is_still_honoured(self) -> None:
        """Обратный контроль у обоих починенных: `--data-dir` не сломан."""
        for name in ("rate_observation_census", "journal_population_backfill"):
            with self.subTest(census=name), TemporaryDirectory() as tmp:
                module = importlib.import_module(f"spa_core.monitoring.{name}")
                elsewhere = Path(tmp) / "elsewhere"
                elsewhere.mkdir()
                module.run(data_dir=str(elsewhere))
                self.assertTrue(
                    (elsewhere / module.OUTPUT_FILENAME).exists(),
                    f"{name}: явный каталог данных перестал работать")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
