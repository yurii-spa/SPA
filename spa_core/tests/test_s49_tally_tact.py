"""Контроль прибора «такт сводки §49» (`spa_core/monitoring/s49_tally_tact.py`).

Каждый тест здесь — положительный контроль на КОНКРЕТНЫЙ способ соврать, а не
проверка, что функция что-то вернула. Заказ G93 п. 3 прямо запрещает механическое
объявление такта, поэтому первая половина набора — про вычисление такта-пола из
входов, а вторая — про разницу «импорт» / «зов», на которой храповик проводки
замолчал при живой дыре.

# FROZEN-DATE-OK: injected-clock — часы входом: единственный литерал даты здесь
# `_ANCHOR`, и он передаётся приборам аргументом `now=`; отметки артефактов
# считаются ОТ него, поэтому календарь на вердикт не влияет.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.monitoring import s49_tally_tact as stt  # noqa: E402
from spa_core.monitoring.card_acceptance import (  # noqa: E402
    NOT_SATISFIED,
    SATISFIED,
    UNMEASURED,
)

#: Единственный литерал даты набора. Передаётся приборам аргументом `now=`.
_ANCHOR = dt.datetime(2026, 10, 3, 6, 0, 0, tzinfo=dt.timezone.utc)


def _manifest(artifacts) -> dict:
    return {"artifacts": list(artifacts)}


def _art(path, slo, note):
    entry = {"path": path, "status": "active", "notes": note}
    if slo is not None:
        entry["slo_hours"] = slo
    return entry


def _note(criterion):
    """Каноническая форма привязки, которую разбирает сосед `s49_criterion_price`."""
    return f"Мера критерия §49 `{criterion}` приказа «Portfolio CIO»."


class _FakeRollup:
    """Подменная сводка. Отдаёт ровно то, что велено, и считает свои зовы."""

    class Unmeasured(Exception):
        pass

    def __init__(self, rows=None, raises=None, population=None):
        self.rows = rows or []
        self.raises = raises
        self.population = population
        self.calls = []

    def measure(self, repo_root, **kw):
        self.calls.append((repo_root, kw))
        if self.raises:
            raise self.Unmeasured(self.raises)
        counts = {SATISFIED: 0, NOT_SATISFIED: 0, UNMEASURED: 0}
        for row in self.rows:
            counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
        return {"population": (self.population if self.population is not None
                               else len(self.rows)),
                "rows": self.rows, "counts": counts}


def _rows(*pairs):
    return [{"criterion": c, "probe": f"probe_{i}", "verdict": v}
            for i, (c, v) in enumerate(pairs)]


class _Tree:
    """Одноразовое дерево: манифест + каталог данных + модули ступеней.

    Стенд снимает ТОТ, КТО ЕГО СОЗДАЛ (ADR-546): иначе прибор бросает свой стенд,
    и это уже стоило системе 87 ГБ и остановки записи.
    """

    def __init__(self, manifest, stage_sources=None, data_files=None):
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_stt_")
        self.root = Path(self._tmp.name)
        (self.root / "architecture").mkdir(parents=True)
        (self.root / "architecture" / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        self.data = self.root / "data"
        self.data.mkdir()
        for name, payload in (data_files or {}).items():
            path = self.data / name
            path.write_text(payload if isinstance(payload, str)
                            else json.dumps(payload, ensure_ascii=False),
                            encoding="utf-8")
        self.stages = {}
        for stage, (rel, source) in (stage_sources or {}).items():
            if source is not None:
                target = self.root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding="utf-8")
            self.stages[stage] = {"module": rel,
                                  "artifact": f"data/{stage}.json"}

    def close(self):
        self._tmp.cleanup()


# ───────────────────────────── такт-пол ─────────────────────────────

class TestTactFloor(unittest.TestCase):
    """Такт ВЫЧИСЛЯЕТСЯ из входов вердикта. Заказ запрещает его выбирать."""

    def test_floor_is_the_SHORTEST_slo_among_the_bindings(self):
        """Пол ставит самый быстрый вход: сводка врёт с его протуханием.

        Взять максимум или первый попавшийся значило бы объявить сводку свежей
        ещё долго после того, как её вход сменился.
        """
        tree = _Tree(_manifest([
            _art("data/a.json", 26, _note("Risk")),
            _art("data/b.json", 7, _note("Costs")),
            _art("data/c.json", 12, _note("Economics"))]))
        self.addCleanup(tree.close)
        out = stt.tact_floor(["Risk", "Costs", "Economics"], repo_root=str(tree.root))
        self.assertEqual(out["floor_hours"], 7.0)
        self.assertEqual(out["floor_set_by"], "Costs")
        self.assertEqual(out["floor_input"], "data/b.json")

    def test_a_criterion_without_a_binding_is_UNBOUND_and_does_not_lower_the_floor(self):
        """Критерий без привязки — третий исход, а не нулевой срок.

        Прочитать «привязки нет» как «срок 0 ч» значило бы требовать такта,
        которого не требует ни один вход, и находка стала бы тем громче, чем
        хуже конституция описана.
        """
        tree = _Tree(_manifest([_art("data/b.json", 7, _note("Costs"))]))
        self.addCleanup(tree.close)
        out = stt.tact_floor(["Costs", "Auditability"], repo_root=str(tree.root))
        self.assertEqual(out["floor_hours"], 7.0)
        states = {r["criterion"]: r["state"] for r in out["rows"]}
        self.assertEqual(states["Auditability"], stt.TACT_UNBOUND)
        self.assertEqual(out["counts"][stt.TACT_UNBOUND], 1)
        self.assertIn("НИ ОДИН артефакт",
                      next(r["why"] for r in out["rows"]
                           if r["criterion"] == "Auditability"))

    def test_a_binding_without_slo_hours_is_its_OWN_outcome(self):
        """«Привязка есть, срока нет» ≠ «привязки нет» ≠ «срок такой-то».

        Чинятся они разным: первое — дописать поле у живого артефакта, второе —
        решить, какой артефакт есть мера. Слить их значило бы повторить инв. #17.
        """
        tree = _Tree(_manifest([
            _art("data/b.json", 7, _note("Costs")),
            _art("data/d.json", None, _note("Determinism"))]))
        self.addCleanup(tree.close)
        out = stt.tact_floor(["Costs", "Determinism"], repo_root=str(tree.root))
        row = next(r for r in out["rows"] if r["criterion"] == "Determinism")
        self.assertEqual(row["state"], stt.TACT_BOUND_WITHOUT_SLO)
        self.assertIsNone(row["slo_hours"])
        self.assertEqual(row["artifact"], "data/d.json")
        self.assertEqual(out["floor_hours"], 7.0)

    def test_a_boolean_slo_is_NOT_a_number(self):
        """`True` в питоне есть `int`, и пол в один час взялся бы из ниоткуда.

        Ловушка не выдумана: `isinstance(True, int)` истинно, и `min()` принял бы
        её молча — пол стал бы 1 ч, то есть недостижимым ни для одного бегуна.
        """
        tree = _Tree(_manifest([
            _art("data/b.json", 7, _note("Costs")),
            _art("data/e.json", True, _note("Risk"))]))
        self.addCleanup(tree.close)
        out = stt.tact_floor(["Costs", "Risk"], repo_root=str(tree.root))
        self.assertEqual(out["floor_hours"], 7.0)
        self.assertEqual(
            next(r["state"] for r in out["rows"] if r["criterion"] == "Risk"),
            stt.TACT_BOUND_WITHOUT_SLO)

    def test_several_bindings_of_one_criterion_resolve_to_the_FASTEST(self):
        """Два входа у критерия: протухание наступает по быстрейшему из них."""
        tree = _Tree(_manifest([
            _art("data/b.json", 26, _note("Costs")),
            _art("data/f.json", 7, _note("Costs"))]))
        self.addCleanup(tree.close)
        out = stt.tact_floor(["Costs"], repo_root=str(tree.root))
        self.assertEqual(out["floor_hours"], 7.0)
        self.assertEqual(out["floor_input"], "data/f.json")

    def test_no_numeric_binding_at_all_REFUSES(self):
        """Пола нет вовсе ⇒ отказ. «Пол не измерен» не есть «пол любой»."""
        tree = _Tree(_manifest([_art("data/d.json", None, _note("Determinism"))]))
        self.addCleanup(tree.close)
        with self.assertRaises(stt.Unmeasured) as ctx:
            stt.tact_floor(["Determinism"], repo_root=str(tree.root))
        self.assertIn("пола нет вовсе", str(ctx.exception))

    def test_an_unreadable_manifest_REFUSES_instead_of_guessing(self):
        """Конституция не прочитана ⇒ про такт не сказано ничего."""
        tmp = tempfile.TemporaryDirectory(prefix="spa_stt_")
        self.addCleanup(tmp.cleanup)
        with self.assertRaises(stt.Unmeasured):
            stt.tact_floor(["Costs"], repo_root=tmp.name)


# ───────────────────────── импорт ≠ зов ─────────────────────────

class TestSummaryCallState(unittest.TestCase):
    """Главная находка заказа: храповик проводки считает проводкой ЛЮБУЮ ссылку."""

    def test_import_with_a_call_is_a_CALLER(self):
        state, why = stt.summary_call_state(
            "import cio_acceptance_rollup as rollup\n"
            "def f(x):\n    return rollup.measure(x)\n")
        self.assertEqual(state, stt.CALLS)
        self.assertIn("rollup.measure", why)

    def test_import_WITHOUT_a_call_is_imports_only(self):
        """Тот самый случай: ступень ввозит сводку ради чужого правила.

        Храповик `test_unwired_scripts_ratchet` от такой строки зеленеет, и
        сирота числится подключённой при живой дыре. Здесь это НАЗВАНО.
        """
        state, why = stt.summary_call_state(
            "def f():\n    import cio_acceptance_rollup as rollup\n"
            "    return rollup.CARD_REL\n")
        self.assertEqual(state, stt.IMPORTS_ONLY)
        self.assertIn("Импорт не есть", why)

    def test_from_import_of_the_entry_counts_as_a_call(self):
        """Форма импорта ЗНАЧИМА: `from x import measure` зовётся без точки.

        Считать зовом только `alias.measure` значило бы объявить такую ступень
        «импортирующей и не зовущей» — ложная находка ровно той же природы.
        """
        state, why = stt.summary_call_state(
            "from cio_acceptance_rollup import measure\n"
            "def f(x):\n    return measure(x)\n")
        self.assertEqual(state, stt.CALLS)
        self.assertIn("measure", why)

    def test_from_import_WITHOUT_the_call_is_imports_only(self):
        state, _ = stt.summary_call_state(
            "from cio_acceptance_rollup import measure\n"
            "HANDLERS = {'s49': None}\n")
        self.assertEqual(state, stt.IMPORTS_ONLY)

    def test_the_same_method_name_on_ANOTHER_object_is_not_a_call(self):
        """`other.measure()` рядом с ввезённой сводкой — не зов сводки."""
        state, _ = stt.summary_call_state(
            "import cio_acceptance_rollup as rollup\n"
            "import other\n"
            "def f(x):\n    return other.measure(x)\n")
        self.assertEqual(state, stt.IMPORTS_ONLY)

    def test_a_call_of_a_NON_entry_attribute_is_not_a_call_of_the_summary(self):
        """Зов `rollup.parse_population()` сводки не снимает — объявлены входы."""
        state, _ = stt.summary_call_state(
            "import cio_acceptance_rollup as rollup\n"
            "def f():\n    return rollup.parse_population()\n")
        self.assertEqual(state, stt.IMPORTS_ONLY)

    def test_a_namesake_module_does_not_count(self):
        """Подстрочная коллизия: `..._v2` есть другой модуль.

        Ровно этим врал прежний сканер проводки (цикл #255), и повторить его
        ошибку здесь значило бы объявить зовущим того, кто сводки не видел.
        """
        state, _ = stt.summary_call_state(
            "import cio_acceptance_rollup_v2 as rollup\n"
            "def f(x):\n    return rollup.measure(x)\n")
        self.assertEqual(state, stt.NO_REFERENCE)

    def test_prose_is_not_wiring(self):
        """Докстринг и комментарий вызова не содержат. AST их не видит — и это
        проверяется, а не предполагается."""
        state, _ = stt.summary_call_state(
            '"""Сводка cio_acceptance_rollup.measure() тут только упомянута."""\n'
            "# import cio_acceptance_rollup as rollup\n"
            "X = 1\n")
        self.assertEqual(state, stt.NO_REFERENCE)

    def test_a_broken_source_is_UNREADABLE_not_unreferenced(self):
        """Разобрать не вышло ⇒ третий исход. «Не прочитан» ≠ «ссылки нет»."""
        state, why = stt.summary_call_state("def f(:\n")
        self.assertEqual(state, stt.SOURCE_UNREADABLE)
        self.assertIn("не разобран", why)


# ─────────────────── доходит ли вердикт до читателя ───────────────────

class TestArtifactState(unittest.TestCase):
    """Вопрос у носителя ОДИН: доходит ли ТАЛЛИ до читателя, а не до вывода.

    Первая редакция этого класса спрашивала у артефакта, встречаются ли в нём ОБА
    слова `satisfied` и `not_satisfied`, — и мутация `and`→`or` в ней ВЫЖИЛА.
    Разбор показал не дыру сцены, а дефект мерки: так прибор судил бы о СХЕМЕ
    носителя по СЕГОДНЯШНИМ значениям, и артефакт, у которого в этот день все
    критерии выполнены, объявил бы «вердикта не несущим».
    """

    def _file(self, payload):
        tmp = tempfile.TemporaryDirectory(prefix="spa_stt_")
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "art.json"
        path.write_text(payload if isinstance(payload, str)
                        else json.dumps(payload, ensure_ascii=False),
                        encoding="utf-8")
        return path

    def test_an_absent_artifact_is_its_OWN_outcome(self):
        """Объявлен и ни разу не произведён ≠ «таллии не несёт».

        Первое чинится пуском производителя, второе — правкой его схемы.
        """
        tmp = tempfile.TemporaryDirectory(prefix="spa_stt_")
        self.addCleanup(tmp.cleanup)
        state, why = stt._artifact_state(Path(tmp.name) / "nope.json", ["Costs"])
        self.assertEqual(state, stt.ARTIFACT_ABSENT)
        self.assertIn("нет", why)

    def test_an_unreadable_artifact_is_UNREADABLE(self):
        state, _ = stt._artifact_state(self._file("{не json"), ["Costs"])
        self.assertEqual(state, stt.ARTIFACT_UNREADABLE)

    def test_a_declared_COUNT_over_the_vocabulary_is_a_tally(self):
        """Таллии — то, что можно ПРОЧЕСТЬ, а не вывести из чужих строк."""
        state, why = stt._artifact_state(self._file(
            {"tally": {SATISFIED: 0, NOT_SATISFIED: 10, UNMEASURED: 3},
             "rows": [{"criterion": "Costs"}]}), ["Costs"])
        self.assertEqual(state, stt.CARRIES_TALLY)
        self.assertIn("счёт", why)

    def test_per_row_verdicts_WITHOUT_a_count_are_not_a_tally(self):
        """Ровно так устроен сосед: построчные вердикты есть, счёта нет.

        Сложить их самому значило бы завести ВТОРУЮ копию мерки — та самая
        форма, которой расходятся числа молча (ADR-220).
        """
        state, why = stt._artifact_state(self._file(
            {"rows": [{"criterion": "Costs", "probe_verdict": SATISFIED},
                      {"criterion": "Risk", "probe_verdict": NOT_SATISFIED}]}),
            ["Costs", "Risk"])
        self.assertEqual(state, stt.CARRIES_VERDICTS_ONLY)
        self.assertIn("ВТОРУЮ копию", why)

    def test_a_day_when_EVERY_criterion_is_satisfied_is_still_a_tally(self):
        """Та самая мутация, пережившая первую редакцию.

        Значение сегодня одно — это свойство МИРА, а не схемы носителя; судить о
        схеме по нему значило бы печатать находку тем громче, чем лучше дела.
        """
        state, _ = stt._artifact_state(self._file(
            {"tally": {SATISFIED: 13, NOT_SATISFIED: 0},
             "rows": [{"criterion": "Costs", "verdict": SATISFIED}]}), ["Costs"])
        self.assertEqual(state, stt.CARRIES_TALLY)

    def test_ONE_vocabulary_key_is_not_a_count(self):
        """Один ключ словаря может быть чужим совпадением имени, а не счётом."""
        state, _ = stt._artifact_state(self._file(
            {"criterion": "Costs", UNMEASURED: 2}), ["Costs"])
        self.assertEqual(state, stt.CARRIES_VERDICTS_ONLY)

    def test_a_vocabulary_key_with_a_NON_number_is_not_a_count(self):
        """`{"satisfied": "да"}` счётом не является — счёт есть число."""
        state, _ = stt._artifact_state(self._file(
            {"criterion": "Costs", SATISFIED: "да", NOT_SATISFIED: "нет"}),
            ["Costs"])
        self.assertEqual(state, stt.CARRIES_VERDICTS_ONLY)

    def test_a_boolean_count_is_not_a_count(self):
        """`True` есть `int`, и два флага сошли бы за счёт по населению."""
        state, _ = stt._artifact_state(self._file(
            {"criterion": "Costs", SATISFIED: True, NOT_SATISFIED: False}),
            ["Costs"])
        self.assertEqual(state, stt.CARRIES_VERDICTS_ONLY)

    def test_an_artifact_that_names_no_criterion_is_its_own_outcome(self):
        """«Про §49 ничего» ≠ «про §49 не всё»: чинится это разным."""
        state, why = stt._artifact_state(self._file(
            {"status": "OK", "counts": {"answered": 3}}), ["Costs", "Risk"])
        self.assertEqual(state, stt.NAMES_NO_CRITERION)
        self.assertIn("не называет", why)

    def test_a_FIELD_NAME_from_the_vocabulary_is_not_a_verdict_value(self):
        """Имя поля `unmeasured` у чужого счёта вердиктом не является.

        **Утверждается ПРИЧИНА, а не только исход** — и это не придирка: у двух
        последних ветвей исход ОДИН (`carries_verdicts_only`), поэтому тест,
        спрашивающий лишь исход, переживал мутацию «искать словарь подстрокой по
        тексту документа». Положительный контроль, не умеющий отличить свою
        аварию от соседней, зелен при любом ответе (находка #758).
        """
        state, why = stt._artifact_state(self._file(
            {"criterion": "Costs", "counts": {UNMEASURED: "много"}}), ["Costs"])
        self.assertEqual(state, stt.CARRIES_VERDICTS_ONLY)
        self.assertIn("ни одного значения из словаря", why)
        self.assertNotIn("ВТОРУЮ копию", why)

    def test_PROSE_containing_a_verdict_word_is_not_a_verdict(self):
        """Свободный текст со словом словаря внутри — не вердикт.

        Найдено мутацией «искать словарь подстрокой», которая пережила ДВА
        контроля причины: в обеих их сценах мутация ничего не меняла, потому что
        до строки-листа доходят только ЗНАЧЕНИЯ, а слово стояло ключом. Разница
        достижима ровно здесь — у поля-пояснения, где слово словаря есть часть
        фразы. Вердикт есть РАВЕНСТВО значению словаря, а не вхождение в него.
        """
        state, why = stt._artifact_state(self._file(
            {"rows": [{"criterion": "Costs",
                       "detail": f"наблюдение {UNMEASURED} по этому входу"}]}),
            ["Costs"])
        self.assertEqual(state, stt.CARRIES_VERDICTS_ONLY)
        self.assertIn("ни одного значения из словаря", why)

    def test_a_row_verdict_names_the_SECOND_COPY_reason_specifically(self):
        """Обратная сторона предыдущего: причина у настоящих вердиктов СВОЯ.

        Без этой половины утверждение «причина названа верно» было бы
        односторонним: достаточно было бы печатать одну и ту же причину всегда.
        """
        state, why = stt._artifact_state(self._file(
            {"rows": [{"criterion": "Costs", "verdict": NOT_SATISFIED}]}),
            ["Costs"])
        self.assertEqual(state, stt.CARRIES_VERDICTS_ONLY)
        self.assertIn("ВТОРУЮ копию", why)
        self.assertNotIn("ни одного значения из словаря", why)


# ─────────────────────────── население зовущих ───────────────────────────

_CALLING = ("import cio_acceptance_rollup as rollup\n"
            "def run(x):\n    return rollup.measure(x)\n")
_IMPORTING = ("def run():\n    import cio_acceptance_rollup as rollup\n"
              "    return rollup.CARD_REL\n")
_SILENT = "def run():\n    return 1\n"


class TestCallers(unittest.TestCase):

    def _tree(self, **kw):
        tree = _Tree(**kw)
        self.addCleanup(tree.close)
        return tree

    def test_only_stages_that_REFERENCE_the_summary_become_rows(self):
        """Население — ссылающиеся ступени. Молчащая ступень не находка."""
        tree = self._tree(
            manifest=_manifest([_art("data/caller.json", 192, "—")]),
            stage_sources={"caller": ("spa_core/monitoring/caller.py", _CALLING),
                           "silent": ("spa_core/monitoring/silent.py", _SILENT)})
        out = stt.callers(str(tree.root), data_dir=str(tree.data),
                          criteria=["Costs"], stages=tree.stages,
                          manifest=_manifest([_art("data/caller.json", 192, "—")]))
        self.assertEqual([r["stage"] for r in out["rows"]], ["caller"])
        self.assertEqual([r["stage"] for r in out["calling"]], ["caller"])

    def test_the_tact_of_a_caller_is_read_BY_ARTIFACT_PATH_from_the_manifest(self):
        """Такт берётся у артефакта, а не у имени ступени: имена расходятся."""
        man = _manifest([_art("data/caller.json", 192, "—")])
        tree = self._tree(
            manifest=man,
            stage_sources={"caller": ("spa_core/monitoring/caller.py", _CALLING)})
        out = stt.callers(str(tree.root), data_dir=str(tree.data),
                          criteria=["Costs"], stages=tree.stages, manifest=man)
        self.assertEqual(out["rows"][0]["slo_hours"], 192)

    def test_an_importing_stage_lands_in_imports_only_not_in_calling(self):
        man = _manifest([_art("data/importer.json", 12, "—")])
        tree = self._tree(
            manifest=man,
            stage_sources={"importer": ("spa_core/monitoring/importer.py",
                                        _IMPORTING)})
        out = stt.callers(str(tree.root), data_dir=str(tree.data),
                          criteria=["Costs"], stages=tree.stages, manifest=man)
        self.assertEqual(out["calling"], [])
        self.assertEqual([r["stage"] for r in out["imports_only"]], ["importer"])

    def test_a_stage_whose_module_is_MISSING_is_named_not_skipped(self):
        """Модуля ступени нет в дереве ⇒ строка с причиной.

        Пропустить её молча значило бы объявить состав ступеней меньше, чем он
        объявлен, и «зовущих ноль» стало бы недостижимым утверждением.
        """
        man = _manifest([_art("data/ghost.json", 12, "—")])
        tree = self._tree(manifest=man,
                          stage_sources={"ghost": ("spa_core/monitoring/ghost.py",
                                                   None)})
        out = stt.callers(str(tree.root), data_dir=str(tree.data),
                          criteria=["Costs"], stages=tree.stages, manifest=man)
        self.assertEqual(out["rows"][0]["state"], stt.SOURCE_UNREADABLE)
        self.assertIn("ghost.py", out["rows"][0]["why"])

    def test_an_unreadable_manifest_REFUSES_the_caller_census(self):
        """Такты зовущих не прочитаны ⇒ НЕ ИЗМЕРЕНО, а не «тактов нет».

        Пустой список тактов прочёлся бы как «ни у кого срока не объявлено», то
        есть как находка — тем громче, чем хуже прочитано дерево.
        """
        tmp = tempfile.TemporaryDirectory(prefix="spa_stt_")
        self.addCleanup(tmp.cleanup)
        with self.assertRaises(stt.Unmeasured) as ctx:
            stt.callers(tmp.name, data_dir=tmp.name, criteria=["Costs"],
                        stages={"x": {"module": "nope.py", "artifact": "data/x.json"}},
                        manifest=None)
        self.assertIn("такты зовущих", str(ctx.exception))

    def test_the_DEFAULT_population_is_the_declared_bridge_composition(self):
        """Умолчание населения — объявленный состав ступеней, а не пустота.

        Положительный контроль на проводку самого населения: подстановка
        `stages=` молчаливо скрыла бы, что по умолчанию прибор не смотрит никуда.
        """
        from spa_core.monitoring import findings_bridge as fb
        man = json.loads((_REPO / "architecture" / "manifest.json")
                         .read_text(encoding="utf-8"))
        out = stt.callers(str(_REPO), data_dir=str(_REPO / "data"),
                          criteria=["Costs"], manifest=man)
        named = {r["stage"] for r in out["rows"]}
        self.assertTrue(named, "по умолчанию население зовущих оказалось пустым")
        self.assertTrue(named <= set(fb.CENSUS_PRODUCT),
                        f"в населении имена вне состава ступеней: "
                        f"{named - set(fb.CENSUS_PRODUCT)}")


# ─────────────────────────── сводный замер ───────────────────────────

_BINDINGS = [_art("data/fast.json", 7, _note("Costs")),
             _art("data/slow.json", 26, _note("Risk"))]


class TestMeasure(unittest.TestCase):

    def _tree(self, stage_sources=None, artifacts=None, data_files=None):
        tree = _Tree(manifest=_manifest(artifacts if artifacts is not None
                                        else _BINDINGS),
                     stage_sources=stage_sources, data_files=data_files)
        self.addCleanup(tree.close)
        return tree

    def _measure(self, tree, rollup, **kw):
        return stt.measure(str(tree.root), data_dir=str(tree.data),
                           rollup=rollup, stages=tree.stages, now=_ANCHOR,
                           clock=kw.pop("clock", lambda: 0.0), **kw)

    def test_the_injected_summary_REALLY_reaches_the_measurement(self):
        """Положительный контроль самой подмены.

        Без него весь класс ниже был бы зелёным по построению: прибор мерил бы
        настоящую сводку, а тест думал, что подменил её (урок ADR-505).
        """
        fake = _FakeRollup(rows=_rows(("Costs", SATISFIED)))
        tree = self._tree(stage_sources={
            "caller": ("spa_core/monitoring/caller.py", _CALLING)},
            artifacts=_BINDINGS + [_art("data/caller.json", 7, "—")])
        doc = self._measure(tree, fake)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(doc["tally"]["satisfied"], 1)

    def test_a_refusing_summary_REFUSES_the_whole_measurement(self):
        """Сводки нет ⇒ таллии нет. Выдумать её нечем и не из чего."""
        tree = self._tree()
        with self.assertRaises(stt.Unmeasured) as ctx:
            self._measure(tree, _FakeRollup(raises="карточка не найдена"))
        self.assertIn("карточка не найдена", str(ctx.exception))

    def test_the_tally_is_carried_VERBATIM_from_the_summary(self):
        """Прибор не пересчитывает вердикты — он их ПЕРЕНОСИТ.

        Второй счёт разошёлся бы с первым молча (ADR-220), а сводка здесь —
        единственный источник вердикта.
        """
        rows = _rows(("Costs", NOT_SATISFIED), ("Risk", NOT_SATISFIED),
                     ("Auditability", UNMEASURED))
        tree = self._tree()
        doc = self._measure(tree, _FakeRollup(rows=rows, population=13))
        self.assertEqual(doc["tally"], {"satisfied": 0, "not_satisfied": 2,
                                        "unmeasured": 1})
        self.assertEqual(doc["population"], 13)
        self.assertEqual([r["criterion"] for r in doc["tally_rows"]],
                         ["Costs", "Risk", "Auditability"])

    def test_a_missing_count_key_is_None_not_zero(self):
        """Ключа счёта нет ⇒ `None`. Ноль здесь был бы утверждением (инв. #17)."""
        class _Bare(_FakeRollup):
            def measure(self, repo_root, **kw):
                return {"population": 1, "rows": _rows(("Costs", NOT_SATISFIED)),
                        "counts": {NOT_SATISFIED: 1}}
        tree = self._tree()
        doc = self._measure(tree, _Bare())
        self.assertIsNone(doc["tally"]["satisfied"])
        self.assertEqual(doc["tally"]["not_satisfied"], 1)

    def test_the_cost_of_the_run_is_MEASURED_by_the_injected_clock(self):
        """Стоимость — замер, а не оценка; часы при этом ВХОД, а не стенные."""
        ticks = iter([100.0, 161.5])
        tree = self._tree()
        doc = self._measure(tree, _FakeRollup(rows=_rows(("Costs", SATISFIED))),
                            clock=lambda: next(ticks))
        self.assertEqual(doc["tally_cost_s"], 61.5)

    def test_a_caller_inside_the_floor_is_floor_served(self):
        tree = self._tree(
            stage_sources={"caller": ("spa_core/monitoring/caller.py", _CALLING)},
            artifacts=_BINDINGS + [_art("data/caller.json", 7, "—")],
            data_files={"caller.json": {
                "tally": {SATISFIED: 1, NOT_SATISFIED: 1},
                "rows": [{"criterion": "Costs"}, {"criterion": "Risk"}]}})
        doc = self._measure(tree, _FakeRollup(rows=_rows(("Costs", SATISFIED),
                                                         ("Risk", NOT_SATISFIED))))
        self.assertEqual(doc["verdict"], stt.FLOOR_SERVED)
        self.assertIsNone(doc["gap_ratio"])
        self.assertEqual(doc["fastest_caller"], "caller")
        self.assertEqual(doc["findings"], 0)

    def test_a_caller_slower_than_the_floor_is_named_WITH_THE_RATIO(self):
        """«Зовут» и «зовут в такте» — разные ответы, и разница есть число."""
        tree = self._tree(
            stage_sources={"caller": ("spa_core/monitoring/caller.py", _CALLING)},
            artifacts=_BINDINGS + [_art("data/caller.json", 192, "—")])
        doc = self._measure(tree, _FakeRollup(rows=_rows(("Costs", SATISFIED))))
        self.assertEqual(doc["verdict"], stt.CALLERS_SLOWER_THAN_FLOOR)
        self.assertEqual(doc["gap_ratio"], round(192 / 7.0, 2))
        self.assertGreaterEqual(doc["findings"], 1)

    def test_nobody_calling_is_its_own_verdict(self):
        tree = self._tree(stage_sources={
            "silent": ("spa_core/monitoring/silent.py", _SILENT)})
        doc = self._measure(tree, _FakeRollup(rows=_rows(("Costs", SATISFIED))))
        self.assertEqual(doc["verdict"], stt.NO_CALLER_AT_ALL)
        self.assertEqual(doc["callers_calling"], [])

    def test_callers_without_a_declared_tact_REFUSE_rather_than_pass(self):
        """Зовут, а такт не объявлен ⇒ НЕ ИЗМЕРЕНО, а не «такт в порядке».

        Это fail-OPEN с обратным знаком: отсутствие поля прочлось бы как
        отсутствие проблемы.
        """
        tree = self._tree(
            stage_sources={"caller": ("spa_core/monitoring/caller.py", _CALLING)},
            artifacts=_BINDINGS + [_art("data/caller.json", None, "—")])
        with self.assertRaises(stt.Unmeasured) as ctx:
            self._measure(tree, _FakeRollup(rows=_rows(("Costs", SATISFIED))))
        self.assertIn("НЕ ИЗМЕРЕН", str(ctx.exception))

    def test_an_importing_stage_is_counted_as_a_FINDING(self):
        """Импортирующая и не зовущая ступень — находка, а не нейтральный факт."""
        tree = self._tree(
            stage_sources={"caller": ("spa_core/monitoring/caller.py", _CALLING),
                           "importer": ("spa_core/monitoring/importer.py",
                                        _IMPORTING)},
            artifacts=_BINDINGS + [_art("data/caller.json", 7, "—"),
                                   _art("data/importer.json", 7, "—")],
            data_files={"caller.json": {
                "tally": {SATISFIED: 1, NOT_SATISFIED: 1},
                "rows": [{"criterion": "Costs"}, {"criterion": "Risk"}]}})
        doc = self._measure(tree, _FakeRollup(rows=_rows(("Costs", SATISFIED),
                                                         ("Risk", NOT_SATISFIED))))
        self.assertEqual(doc["verdict"], stt.FLOOR_SERVED)
        self.assertEqual(doc["callers_imports_only"], ["importer"])
        self.assertEqual(doc["findings"], 1)

    def test_the_floor_row_set_is_carried_so_the_number_can_be_checked(self):
        """Пол без оснований — то же перепечатанное число, против которого правило."""
        tree = self._tree()
        doc = self._measure(tree, _FakeRollup(rows=_rows(("Costs", SATISFIED),
                                                         ("Risk", SATISFIED))))
        self.assertEqual(doc["tact_floor_hours"], 7.0)
        self.assertEqual(doc["tact_floor_set_by"], "Costs")
        self.assertEqual(doc["tact_floor_counts"][stt.TACT_BOUND], 2)
        self.assertEqual({r["criterion"] for r in doc["tact_rows"]},
                         {"Costs", "Risk"})


# ─────────────────────────── такт ступени ───────────────────────────

class TestRun(unittest.TestCase):

    def _stand(self):
        tmp = tempfile.TemporaryDirectory(prefix="spa_stt_")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "architecture").mkdir(parents=True)
        (root / "architecture" / "manifest.json").write_text(
            json.dumps(_manifest(_BINDINGS), ensure_ascii=False), encoding="utf-8")
        (root / "data").mkdir()
        return root

    def test_inside_the_tact_nothing_is_measured_and_nothing_is_written(self):
        """«Не мерили» и «измерено» — РАЗНЫЕ исходы, и первый не пишет файла."""
        root = self._stand()
        target = root / "data" / stt.ARTIFACT
        target.write_text(json.dumps(
            {"status": "OK", "generated_at": (_ANCHOR - dt.timedelta(hours=1)).isoformat()}),
            encoding="utf-8")
        before = target.read_text(encoding="utf-8")
        out = stt.run(root, now=_ANCHOR)
        self.assertFalse(out["measured"])
        self.assertIn("из", out["reason"])
        self.assertEqual(target.read_text(encoding="utf-8"), before)

    def test_past_the_tact_the_artifact_is_written_with_a_stamp(self):
        root = self._stand()
        out = stt.run(root, now=_ANCHOR, rollup=_FakeRollup(
            rows=_rows(("Costs", SATISFIED))), stages={},
            clock=lambda: 0.0)
        self.assertTrue(out["measured"])
        doc = json.loads((root / "data" / stt.ARTIFACT).read_text(encoding="utf-8"))
        self.assertEqual(doc["status"], "OK")
        self.assertEqual(doc["generated_at"], _ANCHOR.isoformat())

    def test_a_REFUSAL_is_stamped_too(self):
        """Отказ без отметки сделал бы такт нечитаемым НАВСЕГДА.

        `measurement_due` на непрочитанной отметке честно отвечает «мерим», и
        дорогая ступень пошла бы каждый тик моста до конца времён.
        """
        root = self._stand()
        out = stt.run(root, now=_ANCHOR,
                      rollup=_FakeRollup(raises="карточки нет"), stages={})
        doc = out["doc"]
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertEqual(doc["generated_at"], _ANCHOR.isoformat())
        self.assertIn("карточки нет", doc["reason"])

    def test_the_gate_is_SHORTER_than_the_floor_it_measures(self):
        """Гейт не имеет права быть причиной устаревания вердикта.

        Замер 03.10 дал пол 7 ч; гейт объявлен 6 ч. Если однажды пол опустится
        ниже гейта, прибор скажет это САМ своей находкой про свой же артефакт —
        но тихо совпасть они не должны.
        """
        self.assertLess(stt.MEASUREMENT_TACT_DAYS * 24.0, 7.0)


# ─────────────────────────── отрисовка ───────────────────────────

class TestReport(unittest.TestCase):

    def test_a_refusal_says_that_NOTHING_is_claimed(self):
        lines = stt.report({"status": "UNMEASURED", "reason": "манифест не прочитан"})
        self.assertIn("НЕ ИЗМЕРЕНО", lines[0])
        self.assertTrue(any("НЕ СКАЗАНО НИЧЕГО" in line for line in lines))

    def test_an_absent_tally_prints_as_NOT_MEASURED_not_as_zero(self):
        """Ноль в отчёте читался бы как «ни один критерий не выполнен»."""
        lines = stt.report({"status": "OK", "population": 13,
                            "tally": {"satisfied": None, "not_satisfied": 10,
                                      "unmeasured": 3},
                            "tact_floor_hours": 7, "verdict": stt.FLOOR_SERVED})
        self.assertIn("ВЫПОЛНЕНО НЕ ИЗМЕРЕНО", lines[0])

    def test_an_absent_floor_prints_as_NOT_MEASURED(self):
        lines = stt.report({"status": "OK", "population": 13,
                            "tally": {"satisfied": 0, "not_satisfied": 10,
                                      "unmeasured": 3},
                            "tact_floor_hours": None,
                            "verdict": stt.NO_CALLER_AT_ALL})
        self.assertTrue(any("такт-пол НЕ ИЗМЕРЕН" in line for line in lines))

    def test_the_gap_ratio_is_printed_when_there_is_one(self):
        lines = stt.report({"status": "OK", "population": 13,
                            "tally": {"satisfied": 0, "not_satisfied": 10,
                                      "unmeasured": 3},
                            "tact_floor_hours": 7, "gap_ratio": 27.43,
                            "fastest_caller": "acceptance_tree_capability",
                            "verdict": stt.CALLERS_SLOWER_THAN_FLOOR})
        self.assertTrue(any("27.43" in line for line in lines))

    def test_format_report_names_the_decision_and_delegates(self):
        doc = {"status": "OK", "population": 13,
               "tally": {"satisfied": 0, "not_satisfied": 10, "unmeasured": 3},
               "tact_floor_hours": 7, "verdict": stt.FLOOR_SERVED}
        lines = stt.format_report(doc)
        self.assertIn("ADR-547", lines[0])
        self.assertEqual(len(lines), len(stt.report(doc, max_rows=10)) + 1)

    def test_the_blindness_is_named_in_the_report_itself(self):
        """Слепота, названная только в докстринге, до читателя не доходит."""
        lines = stt.report({"status": "OK", "population": 13,
                            "tally": {"satisfied": 0, "not_satisfied": 10,
                                      "unmeasured": 3},
                            "tact_floor_hours": 7, "verdict": stt.FLOOR_SERVED})
        self.assertTrue(any("НЕ ДОКЛАДЫВАЕТ" in line for line in lines))
        self.assertTrue(any("ADVISORY" in line for line in lines))


# ─────────────────────────── проводка ───────────────────────────

class TestWiring(unittest.TestCase):
    """Написать прибор и не позвать его — то же, что не написать."""

    def test_the_stage_is_declared_in_the_bridge_composition(self):
        from spa_core.monitoring import findings_bridge as fb
        self.assertIn("s49_tally_tact", fb.CENSUS_STAGE)
        self.assertEqual(fb.CENSUS_PRODUCT["s49_tally_tact"],
                         {"module": "spa_core/monitoring/s49_tally_tact.py",
                          "artifact": "data/s49_tally_tact.json"})

    def test_the_artifact_is_declared_in_the_manifest_with_a_producer_and_an_slo(self):
        man = json.loads((_REPO / "architecture" / "manifest.json")
                         .read_text(encoding="utf-8"))
        entry = next(a for a in man["artifacts"]
                     if a.get("path") == "data/s49_tally_tact.json")
        self.assertEqual(entry["producer"], "com.spa.decision_loop")
        self.assertEqual(entry["status"], "active")
        self.assertIsInstance(entry["slo_hours"], int)

    def test_the_declared_slo_EXCEEDS_the_gate_plus_a_runner_period(self):
        """SLO — не вкус: гейт 6 ч + период бегуна, иначе артефакт краснеет
        по построению (ровно дефект, измеренный ADR-506 на сроке 7 ч)."""
        man = json.loads((_REPO / "architecture" / "manifest.json")
                         .read_text(encoding="utf-8"))
        entry = next(a for a in man["artifacts"]
                     if a.get("path") == "data/s49_tally_tact.json")
        self.assertGreater(entry["slo_hours"],
                           stt.MEASUREMENT_TACT_DAYS * 24.0 + 7.0)

    def test_the_office_step_has_a_NAMED_branch_for_the_artifact(self):
        source = (_REPO / "scripts" / "consume_office_reports.py").read_text(
            encoding="utf-8")
        self.assertIn('elif name == "s49_tally_tact.json":', source)
        self.assertIn("from spa_core.monitoring.s49_tally_tact import format_report",
                      source)

    def test_the_office_step_schema_requires_the_floor_and_the_verdict(self):
        """ТАЛЛИ без такта-пола и без вердикта о зовущих — половина ответа."""
        sys.path.insert(0, str(_REPO / "scripts"))
        import consume_office_reports as office  # noqa: PLC0415
        schema = office._READ_SCHEMA["s49_tally_tact.json"]
        for field in ("status", "tally", "tact_floor_hours", "verdict",
                      "callers_calling"):
            self.assertIn(field, schema)


if __name__ == "__main__":
    unittest.main()
