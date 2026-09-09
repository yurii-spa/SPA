"""Сторож: у каждого объявленного продукта есть КОД, который его вычисляет.

Каждая проверка ниже воспроизводит НАСТОЯЩУЮ поломку (правило
`.claude/rules/deployment.md`, «проверка сторожа сторожей»):

* **сирота** — ADR-257 (07.09): измеритель построен, артефакт внесён в манифест
  ДВУМЯ записями, потребитель назван, 37 тестов зелёные — и ни одного вызова.
  Файл `data/cio_outcome_independence.json` не появился ни разу;
* **точка входа не сирота** — ложные находки ПЕРВОЙ редакции этого же прибора
  (`rules_watchdog`, `intraday_equity`): launchd зовёт модуль по имени, импортёр
  ему не нужен;
* **тестовый импортёр не спасает** — у сироты был зелёный собственный тест, и
  засчитать его значило бы назвать сегодняшний дефект здоровьем;
* **неоднозначное базовое имя** — `market_regime.json` живёт в двух каталогах, и
  привязка по базовому имени приписала писателя не тому артефакту;
* **объявление не гасит** — самый дешёвый способ убрать сегодняшнюю тревогу
  сторожей был дописать путь в `PRODUCES`; после этого `artifact_contract` даёт
  `unmeasured` («не нарушение»), а расхождение манифеста с кодом исчезает —
  измеритель при этом остаётся мёртвым;
* **обратная половина** — прибор, который умеет только находить, проходит и у
  того, кто находит ВСЕГДА: на настоящем дереве сирот обязано быть НОЛЬ, а
  снятие живого вызова обязано покраснить;
* **население не ведётся руками** — вопрос «его кто-нибудь зовёт?» флоту уже
  задавали, и оба существующих ответа промахнулись мимо сироты по НАСЕЛЕНИЮ, а
  не по форме: `test_unwired_scripts_ratchet` смотрит только в `scripts/`, а
  `test_cio_acceptance_guards_are_wired` — в `findings_bridge`, но по РУЧНОМУ
  списку `SUBJECTS` из четырёх имён («класс жив ровно до тех пор, пока каждый
  новый сторож не вписан СЮДА» — его собственный комментарий). Сторож, чьё
  население ведут руками, отказывает ровно тогда, когда кто-то забыл, — а забыть
  и есть тот дефект, ради которого он написан. Здесь население берётся из
  манифеста, и это закреплено сценой `test_it_subsumes_the_hand_written_list`.

Времени, pid и `data/` здесь нет: предмет — дерево исходников.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.tests import _orphan_producer as op

REPO = Path(__file__).resolve().parents[2]

_ARTIFACT = "data/cio_outcome_independence.json"
_BRIDGE = "spa_core.monitoring.findings_bridge"

_WRITER_SRC = (
    "from spa_core.utils.atomic import atomic_save\n"
    "REPORT_REL = 'data/thing.json'\n"
    "def run(root):\n"
    "    atomic_save({}, str(root + '/' + REPORT_REL))\n"
)
_MANIFEST = {"agents": [], "artifacts": [
    {"path": "data/thing.json", "status": "active", "producer": "com.spa.thing"}]}


def _synth(tmp: Path, files: dict[str, str]):
    """Дерево-сцена: пары «модуль → файл», как их принимает `measure`."""
    out = []
    for rel, src in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")
        out.append((rel[:-3].replace("/", "."), p))
    return out


def _verdict(rows, path=_ARTIFACT):
    return next(r["verdict"] for r in rows["rows"] if r["path"] == path)


class SyntheticScenes(unittest.TestCase):
    """Сцены, каждая из которых нарушает ТОЛЬКО своё ограничение."""

    def test_writer_nobody_imports_is_an_orphan(self):
        """ADR-257 дословно: писатель есть, точкой входа не является, не ввезён."""
        with TemporaryDirectory() as d:
            srcs = _synth(Path(d), {"spa_core/monitoring/thing.py": _WRITER_SRC})
            r = op.measure(Path(d), sources=srcs, entries=set(), manifest=_MANIFEST)
        self.assertEqual(_verdict(r, "data/thing.json"), op.ORPHAN)

    def test_entry_point_needs_no_importer(self):
        """Ложная находка первой редакции: launchd зовёт модуль ПО ИМЕНИ."""
        with TemporaryDirectory() as d:
            srcs = _synth(Path(d), {"spa_core/monitoring/thing.py": _WRITER_SRC})
            r = op.measure(Path(d), sources=srcs,
                           entries={"spa_core.monitoring.thing"}, manifest=_MANIFEST)
        self.assertEqual(_verdict(r, "data/thing.json"), op.REACHABLE)

    def test_production_importer_rescues(self):
        """Обратная половина: ввезённый не-тестовым кодом писатель сиротой НЕ является."""
        with TemporaryDirectory() as d:
            srcs = _synth(Path(d), {
                "spa_core/monitoring/thing.py": _WRITER_SRC,
                "spa_core/monitoring/caller.py":
                    "from spa_core.monitoring import thing\n"
                    "def go(root):\n    return thing.run(root)\n"})
            r = op.measure(Path(d), sources=srcs, entries=set(), manifest=_MANIFEST)
        self.assertEqual(_verdict(r, "data/thing.json"), op.REACHABLE)

    def test_test_only_importer_does_not_rescue(self):
        """Сердце проверки: у сироты ADR-257 импортёр БЫЛ — её собственный тест."""
        with TemporaryDirectory() as d:
            base = Path(d)
            srcs = _synth(base, {"spa_core/monitoring/thing.py": _WRITER_SRC})
            t = base / "spa_core/tests/test_thing.py"
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_text("from spa_core.monitoring import thing\n", encoding="utf-8")
            # тест в состав источников НЕ подаётся — ровно так его отбирает
            # `source_files`; сцена доказывает, что от его существования вердикт
            # не меняется.
            r = op.measure(base, sources=srcs, entries=set(), manifest=_MANIFEST)
        self.assertEqual(_verdict(r, "data/thing.json"), op.ORPHAN)

    def test_source_files_excludes_tests(self):
        """Отбор источников — предпосылка предыдущей сцены, поэтому проверяется отдельно."""
        with TemporaryDirectory() as d:
            base = Path(d)
            for rel in ("spa_core/monitoring/thing.py", "spa_core/tests/test_thing.py",
                        "scripts/tests/test_other.py", "scripts/tool.py"):
                p = base / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("x = 1\n", encoding="utf-8")
            names = {n for n, _ in op.source_files(base)}
        self.assertEqual(names, {"spa_core.monitoring.thing", "scripts.tool"})

    def test_ambiguous_basename_is_unmeasured_not_a_wrong_writer(self):
        """`market_regime.json` в двух каталогах: угадывать писателя ЗАПРЕЩЕНО.

        Сцена дословная: писатель называет ТОЛЬКО базовое имя (каталог собирается
        на лету), а манифест знает два артефакта с этим именем. Привязать писателя
        к одному из них значило бы приписать продукт дневного цикла аналитику —
        ошибка первой редакции замера. Верный ответ — третий исход у ОБОИХ.
        """
        man = {"agents": [], "artifacts": [
            {"path": "data/thing.json", "status": "active", "producer": "com.spa.a"},
            {"path": "data/sub/thing.json", "status": "active", "producer": "com.spa.b"}]}
        writer = ("from spa_core.utils.atomic import atomic_save\n"
                  "NAME = 'thing.json'\n"
                  "def run(d):\n"
                  "    atomic_save({}, str(d + '/' + NAME))\n")
        with TemporaryDirectory() as d:
            srcs = _synth(Path(d), {"spa_core/monitoring/thing.py": writer})
            r = op.measure(Path(d), sources=srcs, entries=set(), manifest=man)
        self.assertEqual(_verdict(r, "data/sub/thing.json"), op.UNMEASURED)
        self.assertEqual(_verdict(r, "data/thing.json"), op.UNMEASURED)
        self.assertEqual(op.orphans(r), [])

    def test_full_path_writer_is_judged_despite_a_same_named_sibling(self):
        """Обратная половина предыдущей: точное совпадение пути НЕ ослабляется соседом.

        Иначе «не измерено» стало бы способом уйти от вердикта — достаточно было бы
        завести в манифесте одноимённый артефакт в другом каталоге.
        """
        man = {"agents": [], "artifacts": [
            {"path": "data/thing.json", "status": "active", "producer": "com.spa.a"},
            {"path": "data/sub/thing.json", "status": "active", "producer": "com.spa.b"}]}
        with TemporaryDirectory() as d:
            srcs = _synth(Path(d), {"spa_core/monitoring/thing.py": _WRITER_SRC})
            r = op.measure(Path(d), sources=srcs, entries=set(), manifest=man)
        self.assertEqual(_verdict(r, "data/thing.json"), op.ORPHAN)
        self.assertEqual(_verdict(r, "data/sub/thing.json"), op.UNMEASURED)

    def test_no_literal_is_unmeasured_and_not_a_finding(self):
        """Семья `io_*`: `harness.py` пишет f-строкой, имени нет нигде. Третий исход."""
        harness = ("from spa_core.utils.atomic import atomic_save\n"
                   "def run(root, key):\n"
                   "    atomic_save({}, f'{root}/data/{key}.json')\n")
        with TemporaryDirectory() as d:
            srcs = _synth(Path(d), {"spa_core/monitoring/harness.py": harness})
            r = op.measure(Path(d), sources=srcs, entries=set(), manifest=_MANIFEST)
        self.assertEqual(_verdict(r, "data/thing.json"), op.UNMEASURED)
        self.assertEqual(op.orphans(r), [])

    def test_declaring_the_path_does_not_silence_the_verdict(self):
        """Самый дешёвый способ погасить тревогу — дописать строку в `PRODUCES`."""
        declared = ("PRODUCES = ('data/thing.json',)\n"
                    "def main():\n    return 0\n")
        with TemporaryDirectory() as d:
            srcs = _synth(Path(d), {
                "spa_core/monitoring/thing.py": _WRITER_SRC,
                "spa_core/monitoring/entry.py": declared})
            r = op.measure(Path(d), sources=srcs,
                           entries={"spa_core.monitoring.entry"}, manifest=_MANIFEST)
        self.assertEqual(_verdict(r, "data/thing.json"), op.ORPHAN)

    def test_one_live_writer_of_two_is_enough(self):
        """Вердикт — об АРТЕФАКТЕ: мёртвая вторая копия писателя его не хоронит."""
        with TemporaryDirectory() as d:
            srcs = _synth(Path(d), {
                "spa_core/monitoring/thing.py": _WRITER_SRC,
                "spa_core/monitoring/thing_old.py": _WRITER_SRC,
                "spa_core/monitoring/caller.py":
                    "from spa_core.monitoring import thing\n"
                    "def go(root):\n    return thing.run(root)\n"})
            r = op.measure(Path(d), sources=srcs, entries=set(), manifest=_MANIFEST)
        self.assertEqual(_verdict(r, "data/thing.json"), op.REACHABLE)

    def test_a_reader_is_not_a_writer(self):
        """Урок `artifact_io_scan`: поиск по вхождению назвал ЧИТАТЕЛЯ продюсером."""
        reader = ("import json\n"
                  "REPORT_REL = 'data/thing.json'\n"
                  "def load(root):\n"
                  "    return json.load(open(root + '/' + REPORT_REL))\n")
        with TemporaryDirectory() as d:
            srcs = _synth(Path(d), {"spa_core/monitoring/reader.py": reader})
            r = op.measure(Path(d), sources=srcs, entries=set(), manifest=_MANIFEST)
        self.assertEqual(_verdict(r, "data/thing.json"), op.UNMEASURED)

    def test_self_import_does_not_rescue(self):
        """Иначе сироту гасила бы ОДНА строка ввоза самого себя."""
        selfish = "from spa_core.monitoring import thing\n" + _WRITER_SRC
        with TemporaryDirectory() as d:
            srcs = _synth(Path(d), {"spa_core/monitoring/thing.py": selfish})
            r = op.measure(Path(d), sources=srcs, entries=set(), manifest=_MANIFEST)
        self.assertEqual(_verdict(r, "data/thing.json"), op.ORPHAN)

    def test_inactive_artifact_is_out_of_population(self):
        man = {"agents": [], "artifacts": [
            {"path": "data/thing.json", "status": "retired", "producer": "com.spa.thing"}]}
        with TemporaryDirectory() as d:
            srcs = _synth(Path(d), {"spa_core/monitoring/thing.py": _WRITER_SRC})
            r = op.measure(Path(d), sources=srcs, entries=set(), manifest=man)
        self.assertEqual(r["population"], 0)


class LiveTree(unittest.TestCase):
    """Вердикт о НАСТОЯЩЕМ дереве и положительный контроль на нём же."""

    @classmethod
    def setUpClass(cls):
        cls.report = op.measure(REPO)

    def test_population_is_not_empty(self):
        """Прибор, померивший ноль артефактов, сообщил бы «сирот нет» и был бы пуст."""
        self.assertGreater(self.report["population"], 20, self.report["counts"])
        self.assertGreater(self.report["counts"][op.REACHABLE], 10, self.report["counts"])
        self.assertGreater(self.report["entries"], 20)

    def test_no_declared_product_is_an_orphan(self):
        found = op.orphans(self.report)
        self.assertEqual(found, [], "объявленный продукт, который никто не вычисляет: "
                                    + "; ".join(f"{r['path']} ← {r['orphans']}" for r in found))

    def test_removing_the_live_call_turns_the_artifact_into_an_orphan(self):
        """Положительный контроль на настоящем дереве: снять вызов — покраснеть.

        Мутируется ПРОВОДКА, а не деталь: из моста находок убирается строка
        ввоза измерителя. Имя модуля сохраняется, чтобы состав точек входа
        остался тем же — меняется ровно одно, достижимость.
        """
        bridge = REPO / "spa_core/monitoring/findings_bridge.py"
        src = bridge.read_text(encoding="utf-8")
        needle = "    from spa_core.monitoring import cio_outcome_independence\n"
        self.assertIn(needle, src, "живого вызова нет — контроль мерил бы пустоту")
        with TemporaryDirectory() as d:
            mutated = Path(d) / "findings_bridge.py"
            mutated.write_text(src.replace(needle, "    pass\n", 1), encoding="utf-8")
            srcs = [(n, mutated if n == _BRIDGE else p) for n, p in op.source_files(REPO)]
            r = op.measure(REPO, sources=srcs)
        self.assertEqual(_verdict(r), op.ORPHAN)
        self.assertEqual([o["path"] for o in op.orphans(r)], [_ARTIFACT])

    def test_it_subsumes_the_hand_written_list(self):
        """Население из манифеста накрывает ручной список — и он ему не нужен.

        Мутируется ПРОВОДКА оптом: из моста снимаются ВСЕ строки ввоза
        измерителей. Ручной список `SUBJECTS` соседнего сторожа берётся у него же
        (второй копии не заводится — §3 ТЗ владельца), и каждый его артефакт
        обязан оказаться в сиротах. Замер 08.09: сирот при этом 20 против 4 в
        списке.
        """
        from spa_core.tests.test_cio_acceptance_guards_are_wired import SUBJECTS

        # Мутация обязана рвать ВСЕ пути до измерителя, а не один.
        #
        # Замер 09.09 (цикл #535), причина этой правки: у измерителя ДВЕ формы
        # ввоза и ДВА места. Мост зовёт `from spa_core.monitoring import X`, а
        # обязательный шаг 0-офис — `from spa_core.monitoring.X import
        # format_report`. Снимая только первую, мутация оставляла второй путь
        # живым, измеритель честно отвечал REACHABLE, и сцена краснела на
        # ПРАВИЛЬНО подключённом сторо́же. Так вышло на `target_stability` и на
        # соседе `shadow_blockade_attribution`: оба печатают отчёт своей
        # функцией, а те четверо из прежнего списка форматируются в шаге
        # 0-офис на месте — второй формы ввоза у них нет, и дефект спал.
        #
        # Это УСИЛЕНИЕ контроля, а не его ослабление (инв. #16): предмет
        # прежний, оба конца проводки теперь рвутся, и сцена по-прежнему
        # требует, чтобы КАЖДЫЙ артефакт ручного списка стал сиротой.
        _FORM_BRIDGE = r"^\s+from spa_core\.monitoring import \w+$"
        _FORM_OFFICE = r"^\s+from spa_core\.monitoring\.\w+ import [\w, ]+$"
        _OFFICE = "scripts.consume_office_reports"

        bridge = REPO / "spa_core/monitoring/findings_bridge.py"
        src = bridge.read_text(encoding="utf-8")
        mutated_src, n = re.subn(_FORM_BRIDGE, "    pass", src, flags=re.M)
        self.assertGreater(n, len(SUBJECTS), "ввозов измерителей меньше ручного списка — "
                                             "мутация мерила бы пустоту")
        with TemporaryDirectory() as d:
            mutated = Path(d) / "findings_bridge.py"
            mutated.write_text(mutated_src, encoding="utf-8")
            srcs = []
            office_cut = 0
            for n_, p_ in op.source_files(REPO):
                if n_ == _BRIDGE:
                    srcs.append((n_, mutated))
                elif n_ == _OFFICE:
                    cut, k = re.subn(_FORM_OFFICE, "        pass",
                                     p_.read_text(encoding="utf-8"), flags=re.M)
                    office_cut = k
                    mo = Path(d) / "office_reader.py"
                    mo.write_text(cut, encoding="utf-8")
                    srcs.append((n_, mo))
                else:
                    srcs.append((n_, p_))
            self.assertGreater(office_cut, 0,
                               "в шаге 0-офис не найдено ни одного ввоза второй формы — "
                               "мутация мерила бы пустоту вторым концом")
            r = op.measure(REPO, sources=srcs)
        found = {o["path"] for o in op.orphans(r)}
        missing = sorted(set(SUBJECTS.values()) - found)
        self.assertEqual(missing, [], "ручной список НЕ накрыт населением из манифеста")
        self.assertIn(_ARTIFACT, found)
        self.assertGreater(len(found), len(SUBJECTS))

    def test_the_artifact_of_adr_257_is_reachable_now(self):
        self.assertEqual(_verdict(self.report), op.REACHABLE)


if __name__ == "__main__":
    unittest.main()
