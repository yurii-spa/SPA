"""Сторож: перепись, которая ПИШЕТ артефакт, обязана его ОБЪЯВИТЬ.

Заказ **G810 п. 2** приказа владельца «Portfolio CIO» (хвост ADR-810) назвал
критерий §49 `Architecture` единственным `unbound` и причиной — отсутствие
ПРИВЯЗКИ артефакта в конституции. Замер цикла #934 нашёл причину этажом ниже:
привязывать было НЕЧЕГО. Модуль `cio_decision_owner_census` (доставлен #713,
ADR-490) объявлял `REPORT_REL = "data/cio_decision_owner.json"` и писал его
`atomic_save` — но **только из своего CLI**, а звавшего не было ни одного: 0 из
115 ступеней `findings_bridge` модуль не называли. За 27 дней файл не появился в
живом ``data/`` ни разу, и объявить такт у файла, который не появляется, значило
бы declared-ить срок годности у ничего.

## Почему этого НЕ МОГ увидеть ни один существующий сторож

Соседний сторож `test_declared_producer_is_reachable` держит сторону
**«объявлен ⇒ обязан быть достижим»** — и его собственный докстринг говорит,
откуда он берёт население: «здесь население берётся из манифеста». Множество
ОБЪЯВЛЕННЫХ путей и есть его знаменатель, поэтому писатель, не объявленный
НИГДЕ, невидим ему **ПО ПОСТРОЕНИЮ** — не по недосмотру и не по форме.

Этот сторож держит ОБРАТНУЮ сторону: **«пишет ⇒ обязан объявить»**. Население
берётся из ДЕРЕВА (кто пишет), а не из манифеста (кто объявлен), и ровно поэтому
две проверки не заменяют друг друга. Зелёный ответ одной на свой вопрос ответом
на другой не является (`.claude/rules/deployment.md`, «Четыре вопроса»).

## Мерка — AST, и направление ошибки ИЗМЕРЕНО в обе стороны

Подстрока вердикта не покупает (ADR-333): «пишет» — это **зов писателя, в
поддерево аргументов которого входит имя константы**, а не соседство слов в
файле. Первая, грубая редакция мерки (литеральная цель + упоминание) дала на том
же дереве **11** «находок», из которых настоящей была одна: остальные десять —
ВХОДЫ (`TRADES_REL`, `JOURNAL_REL`, `APY_HISTORY_REL`…), то есть пути, которые
модуль ЧИТАЕТ. Перепутать их значило бы требовать объявить своим продуктом чужой
файл.

Замер 25.10 на живом дереве, с контролями по обеим осям:

===================================== =====
переписей с литеральной целью записи   43
из них ПИШУТ и объявлены (контроль)    17
из них суть ВХОДЫ и исключены верно    10
**ПИШУТ и не объявлены НИГДЕ**         **1** ← `cio_decision_owner_census`
===================================== =====

Контроль «17 нашлись объявленными» существен: мерка, не находящая НИ ОДНОГО
объявленного писателя, нашла бы «одну находку» из собственной слепоты.

## Храповик без базы — и это замер, а не строгость ради строгости

Базы исключений здесь нет НАМЕРЕННО: после правки этого же цикла население
находок равно **нулю**, измеренному, а не объявленному. База со нулём населения
учила бы только одному — дописывать в неё (инв. #16, тот же порядок, что у
`frozen_date_baseline.json`). Второй такой писатель краснеет сразу.

Времени, pid и живого ``data/`` здесь нет: предмет — дерево исходников.
"""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: Каталог переписей. Предмет сторожа — приборы офиса, а не всё дерево: писатель
#: артефакта `data/` вне этого каталога (цикл, рукав, адаптер) объявляется своим
#: бегуном, и требовать от него записи в `produces` моста находок было бы
#: неверно. Граница названа вслух, а не подразумевается.
CENSUS_DIR = "spa_core/monitoring"

#: Имена, зов которых СОХРАНЯЕТ значение на диск. Перечень закрыт намеренно:
#: открытый («любой вызов, где встретилось имя константы») превратил бы чтение
#: в запись и вернул бы десять ложных находок грубой редакции.
WRITER_NAMES = frozenset({"atomic_save", "atomic_write", "write_text",
                          "dump", "safe_dump"})

#: Исходы (инв. #17). `unmeasured` — модуль не разобран; это НЕ «не пишет» и
#: НЕ «объявлен»: нечитаемый модуль и необъявленный писатель лечатся разным.
DECLARED = "declared"
UNDECLARED = "undeclared"
UNMEASURED = "unmeasured"


def _literal_data_targets(tree: ast.Module) -> dict[str, str]:
    """Константы уровня модуля, чьё значение есть путь внутри ``data/``."""
    out: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not (isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            continue
        value = node.value.value
        if not (value.startswith("data/")
                and value.endswith((".json", ".jsonl"))):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                out[target.id] = value
    return out


def _names_reaching_writers(tree: ast.Module) -> set[str]:
    """Имена, попадающие в АРГУМЕНТЫ зова писателя.

    Поддерево аргументов обходится целиком: цель почти всегда приходит завёрнутой
    (``atomic_save(doc, os.path.join(root, REPORT_REL))``), и смотреть только на
    прямые аргументы значило бы не найти ни одного настоящего писателя.
    """
    reached: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "attr", None) or getattr(func, "id", None)
        if name not in WRITER_NAMES:
            continue
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            for inner in ast.walk(arg):
                if isinstance(inner, ast.Name):
                    reached.add(inner.id)
    return reached


def declared_artifacts(repo: Path) -> set[str]:
    """Пути, ОБЪЯВЛЕННЫЕ конституцией — ДВУМЯ независимыми записями.

    Обе читаются намеренно: `artifacts[].path` — запись про сам артефакт,
    `agents[].produces[].artifact` — запись про бегуна. Достаточно любой: предмет
    здесь «объявлен ли вообще», а паритет двух записей держит СВОЙ сторож.
    """
    manifest = json.loads((repo / "architecture" / "manifest.json")
                          .read_text(encoding="utf-8"))
    declared = {a["path"] for a in manifest.get("artifacts", [])
                if a.get("path")}
    for agent in manifest.get("agents", []):
        for produced in agent.get("produces", []) or []:
            if produced.get("artifact"):
                declared.add(produced["artifact"])
    return declared


def census_writers(repo: Path, *, census_dir: str = CENSUS_DIR) -> list[dict]:
    """Перепись: КТО пишет артефакт и объявлен ли он.

    ``repo`` — ВХОД, а не окружение: иначе положительный контроль не мог бы
    подать сторожу синтетическое дерево, и проверка отвечала бы на вопрос о
    СЕГОДНЯШНЕМ состоянии вместо вопроса о мерке
    (`.claude/rules/deployment.md`, § про инъекцию).
    """
    declared = declared_artifacts(repo)
    rows: list[dict] = []
    root = repo / census_dir
    for path in sorted(root.glob("*.py")):
        rel = path.relative_to(repo).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            rows.append({"module": rel, "constant": None, "artifact": None,
                         "outcome": UNMEASURED,
                         "why": f"{type(exc).__name__}: {exc}"})
            continue
        targets = _literal_data_targets(tree)
        if not targets:
            continue
        writes = _names_reaching_writers(tree)
        for constant, artifact in sorted(targets.items()):
            if constant not in writes:
                continue  # ВХОД, а не продукт — не предмет этого сторожа
            rows.append({
                "module": rel, "constant": constant, "artifact": artifact,
                "outcome": DECLARED if artifact in declared else UNDECLARED,
                "why": ("объявлен конституцией" if artifact in declared else
                        "модуль ПИШЕТ этот путь, и конституция его не объявляет "
                        "НИ ОДНОЙ записью — такт его входа взять неоткуда"),
            })
    return rows


class CensusWriterIsDeclared(unittest.TestCase):
    """Живое дерево: писателей без объявления быть не должно."""

    def test_no_census_writes_an_undeclared_artifact(self):
        rows = census_writers(REPO)
        orphans = [r for r in rows if r["outcome"] == UNDECLARED]
        self.assertEqual(
            [], orphans,
            "перепись пишет артефакт, которого конституция не объявляет: "
            + "; ".join(f"{r['module']} ({r['constant']} = {r['artifact']})"
                        for r in orphans))

    def test_the_measure_is_not_blind_positive_control_on_the_live_tree(self):
        """Сторож, не находящий НИ ОДНОГО писателя, зелен по собственной слепоте."""
        rows = census_writers(REPO)
        declared = [r for r in rows if r["outcome"] == DECLARED]
        self.assertGreaterEqual(
            len(declared), 10,
            "мерка не нашла объявленных писателей — она измеряет не то, что "
            f"заявляет (строк всего {len(rows)})")

    def test_the_subject_of_this_cycle_is_now_declared(self):
        """Повод сторожа — поимённо, иначе сцена потеряет предмет молча."""
        rows = census_writers(REPO)
        subject = [r for r in rows
                   if r["artifact"] == "data/cio_decision_owner.json"]
        self.assertEqual(
            1, len(subject),
            "писатель меры критерия §49 `Architecture` перестал находиться — "
            "предмет ADR-811 исчез, и сторож больше его не держит")
        self.assertEqual(DECLARED, subject[0]["outcome"])

    def test_nothing_is_unmeasured_on_the_live_tree(self):
        rows = census_writers(REPO)
        blind = [r for r in rows if r["outcome"] == UNMEASURED]
        self.assertEqual([], blind, f"модули не разобраны: {blind}")


class TheMeasureItself(unittest.TestCase):
    """Контроль в ОБЕ стороны на синтетическом дереве (`.claude/rules/acceptance.md`, п. 3).

    Сцена — настоящий сторож на подложном дереве: предмет здесь МЕРКА, а не
    сегодняшнее состояние репозитория.
    """

    def _tree(self, module_src: str, *, declared: list[str]) -> Path:
        import tempfile
        root = Path(tempfile.mkdtemp(prefix="c934_measure_"))
        (root / "architecture").mkdir()
        (root / "architecture" / "manifest.json").write_text(json.dumps(
            {"artifacts": [{"path": p} for p in declared], "agents": []}),
            encoding="utf-8")
        mod = root / CENSUS_DIR
        mod.mkdir(parents=True)
        (mod / "subject.py").write_text(module_src, encoding="utf-8")
        return root

    WRITES = ('REPORT_REL = "data/subject.json"\n'
              'def run(root):\n'
              '    atomic_save({}, os.path.join(root, REPORT_REL))\n')

    def test_a_writer_nobody_declared_is_a_finding(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: ровно авария ADR-811."""
        rows = census_writers(self._tree(self.WRITES, declared=[]))
        self.assertEqual([UNDECLARED], [r["outcome"] for r in rows])
        self.assertIn("такт его входа взять неоткуда", rows[0]["why"])

    def test_the_same_writer_declared_is_not_a_finding(self):
        """ОБРАТНАЯ СТОРОНА: иначе сторож находит ВСЕГДА и ничего не меряет."""
        rows = census_writers(
            self._tree(self.WRITES, declared=["data/subject.json"]))
        self.assertEqual([DECLARED], [r["outcome"] for r in rows])

    def test_declaration_by_the_runner_record_alone_counts(self):
        """Вторая независимая запись конституции — тоже объявление."""
        root = self._tree(self.WRITES, declared=[])
        man = root / "architecture" / "manifest.json"
        man.write_text(json.dumps({"artifacts": [], "agents": [
            {"label": "com.spa.decision_loop",
             "produces": [{"artifact": "data/subject.json", "slo_hours": 7}]}]}),
            encoding="utf-8")
        self.assertEqual([DECLARED],
                         [r["outcome"] for r in census_writers(root)])

    def test_a_path_the_module_only_READS_is_not_its_product(self):
        """Десять ложных находок грубой редакции — этот класс."""
        reads = ('TRADES_REL = "data/trades.json"\n'
                 'def run(root):\n'
                 '    return json.loads(open(os.path.join(root, TRADES_REL)).read())\n')
        self.assertEqual([], census_writers(self._tree(reads, declared=[])))

    def test_mentioning_the_writer_in_prose_buys_no_verdict(self):
        """ADR-333: подстрока рядом с константой не есть зов писателя."""
        prose = ('REPORT_REL = "data/subject.json"\n'
                 '"""Этот модуль НЕ пишет: про atomic_save здесь только сказано."""\n'
                 'NOTE = "atomic_save(REPORT_REL) — так делать нельзя"\n')
        self.assertEqual([], census_writers(self._tree(prose, declared=[])))

    def test_a_module_that_does_not_parse_is_the_THIRD_outcome(self):
        """Не «не пишет» и не «объявлен»: нечитаемый модуль лечится другим."""
        rows = census_writers(self._tree("def run(:\n", declared=[]))
        self.assertEqual([UNMEASURED], [r["outcome"] for r in rows])
        self.assertIn("SyntaxError", rows[0]["why"])

    def test_the_target_wrapped_in_a_join_is_still_found(self):
        """Цель приходит завёрнутой почти всегда — прямой аргумент редкость."""
        nested = ('REPORT_REL = "data/subject.json"\n'
                  'def run(root):\n'
                  '    atomic_save({}, str(Path(os.path.join(root, REPORT_REL))))\n')
        self.assertEqual([UNDECLARED],
                         [r["outcome"] for r in census_writers(
                             self._tree(nested, declared=[]))])


if __name__ == "__main__":
    unittest.main()
