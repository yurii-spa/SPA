"""Положительный контроль ПРОБЫ `ci_red_cause_axis_names_the_cause` (ADR-891).

`.claude/rules/acceptance.md` §3: новая проба регистрируется только с тестом, где она
**зелена на целом контуре** и **красна на КАЖДОМ порванном звене** — с названным
звеном. Проба, никогда не видевшая настоящей поломки, есть украшение.

Звенья здесь настоящие: каждая сцена — ОДНОРАЗОВАЯ КОПИЯ обеих дверей доставки оси
(свод `scripts/ci_control.py` и читатель вердикта `scripts/ci_control_verdict.py`) с
ровно одной снятой половиной, и проба гоняется на ней через свой параметр `repo_root`.
Живое дерево не трогается ни одной сценой: правка идёт в копию, а `spa_core`
подставляется ссылкой — иначе копия не ввезлась бы вовсе и проба ответила бы
`unmeasured`, то есть тест мерил бы свою сцену, а не пробу.

**Подстрокой проба не проходит (ADR-333).** Отдельная сцена печатает читателю ровно те
слова, которые проба ищет в отрисованных строках, НЕ опознав ни одной причины: такая
сцена обязана остаться КРАСНОЙ. Проба, довольная словами, мерила бы свой же словарь.

ТРЕТИЙ ИСХОД у пробы проверяется ОТДЕЛЬНО (инв. #17): дерево без свода обязано дать
`unmeasured`, а НЕ «не выполнено» — иначе «двери нет» стало бы неотличимо от «дверь
врёт», и починка выбиралась бы вслепую.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring.card_acceptance import (NOT_SATISFIED, PROBES, SATISFIED,
                                                 UNMEASURED)

_REPO = Path(__file__).resolve().parent.parent.parent
_PROBE = PROBES["ci_red_cause_axis_names_the_cause"]
_PRODUCER = Path("scripts") / "ci_control.py"
_READER = Path("scripts") / "ci_control_verdict.py"

#: Якорь звена «читатель ПЕЧАТАЕТ ось» — ОДНА копия на обе сцены, которые его рвут.
#: Две копии разошлись бы с кодом порознь, и сцена молча перестала бы рвать звено
#: (`_Scene` на такой случай ОТКАЗЫВАЕТ: предпосылка не обеспечена).
_READER_PRINT_ANCHOR = '''    out.append("   " + ("ось причин НЕ ИЗМЕРЕНА: переписи красного в документе нет "
                        "ВОВСЕ — у оси нет носителя"
                        if not isinstance(cen, dict)
                        else _load_cause_line()(cen.get("cause_axis"))))'''


class _Scene:
    """Одноразовое дерево с ОДНИМ порванным звеном. Живое дерево не трогается."""

    def __init__(self, test: unittest.TestCase, *, producer=None, reader=None,
                 drop_producer: bool = False):
        self.root = Path(tempfile.mkdtemp(prefix="spa_c1005_cause_axis_"))
        test.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        for rel, swap, drop in ((_PRODUCER, producer, drop_producer),
                                (_READER, reader, False)):
            if drop:
                continue
            src = (_REPO / rel).read_text(encoding="utf-8")
            if swap is not None:
                old, new = swap
                assert src.count(old) == 1, (
                    f"якорь звена в {rel} найден не ровно один раз ({src.count(old)}): "
                    f"сцена НЕ ОБЕСПЕЧЕНА, и судить по ней о пробе нельзя")
                src = src.replace(old, new, 1)
            (self.root / rel).write_text(src, encoding="utf-8")
        os.symlink(_REPO / "spa_core", self.root / "spa_core")

    def verdict(self):
        return _PROBE(None, repo_root=str(self.root))


class TheProbeIsGreenOnTheWholeContour(unittest.TestCase):
    """Целый контур — ЖИВОЕ дерево, а не копия: зелёный на копии не есть зелёный здесь."""

    def test_the_real_tree_satisfies_the_probe(self):
        status, detail = _PROBE(None)
        self.assertEqual(status, SATISFIED, detail)
        for token in ("опознано 3 из 3", "НЕ МЕНЬШЕ 2 и НЕ БОЛЬШЕ 3",
                      "названо поимённо"):
            self.assertIn(token, detail)

    def test_an_untouched_copy_is_green_too(self):
        """КОНТРОЛЬ ШУМА: копия без правок зелена — значит краснеет именно звено."""
        status, detail = _Scene(self).verdict()
        self.assertEqual(status, SATISFIED, detail)


class TheProbeIsRedOnEveryBrokenLink(unittest.TestCase):

    def test_red_when_the_producer_records_no_axis_at_all(self):
        """Звено: свод не кладёт в отчёт блок `cause_axis` — состояние `origin/main`."""
        status, detail = _Scene(self, producer=(
            "                  cause_axis=axis)", "                  )")).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("не несёт блока `cause_axis`", detail)

    def test_red_when_the_producer_leaves_the_rows_bare(self):
        """Звено: ось снята, а САМИ строки падений причины не несут."""
        status, detail = _Scene(self, producer=(
            '        row["cause"] = _cause_of(failure)',
            '        row.pop("cause", None)')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("строки падений причины не несут", detail)

    def test_red_when_a_missing_record_is_served_as_measured(self):
        """Звено: записи нет, а ось отвечает «измерено» — fail-OPEN, худший исход."""
        status, detail = _Scene(self, producer=(
            '    if not read_ok and failures:', '    if False:')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("вместо третьего исхода", detail)

    def test_red_when_an_unrecorded_failure_loses_its_name(self):
        """Звено: падение без записи перестаёт называться поимённо."""
        status, detail = _Scene(self, producer=(
            '            unattributed.append(nodeid if isinstance(nodeid, str) '
            'else repr(nodeid))', '            pass')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("НЕ НАЗВАНО поимённо", detail)

    def test_red_when_the_fork_edges_are_swapped(self):
        """Звено: края вилки дефектов перепутаны — «не меньше» стало «не больше»."""
        status, detail = _Scene(self, producer=(
            '        "fork": {"population": fork.population, "lower": fork.lower,'
            ' "upper": fork.upper,',
            '        "fork": {"population": fork.population, "lower": fork.upper,'
            ' "upper": fork.lower,')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("вилка дефектов разошлась со сценой", detail)

    def test_red_when_the_reader_does_not_print_the_axis(self):
        """Звено: ось есть в документе, а в ОТРИСОВАННЫХ строках читателя её нет."""
        status, detail = _Scene(self, reader=(_READER_PRINT_ANCHOR, '    pass')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("в ОТРИСОВАННЫХ строках читателя нет", detail)

    def test_red_when_the_reader_keeps_silent_about_an_unmeasured_axis(self):
        """Звено: ось НЕ измерена, а находки у читателя нет — молчание читается как «всё в порядке»."""
        status, detail = _Scene(self, reader=(
            '            out.append(f"ПРИЧИНА {named} падени(й) НЕ ИЗМЕРЕНА: "',
            '            out.append("") or out.pop() or out.append(f"'
            'про причины ничего: "')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("НАХОДКИ у читателя нет", detail)

    def test_red_when_the_two_third_outcomes_share_one_reason(self):
        """Звено: «свод старше оси» и «записи не было» получают ОДНУ причину."""
        status, detail = _Scene(self, reader=(
            '''            why = ((axis or {}).get("why") if isinstance(axis, dict)
                   else "блока `cause_axis` в отчёте нет вовсе — свод старше ADR-891")''',
            '            why = "причина не измерена"')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("ОДНА на два разных состояния", detail)

    def test_red_when_the_axis_is_only_words(self):
        """ПОДСТРОКА (ADR-333): читатель печатает нужные слова, ничего не опознав."""
        fake = ('    out.append("   причины: опознано 3 из 3; типы: AssertionError 2; '
                'дефектов НЕ МЕНЬШЕ 2 и НЕ БОЛЬШЕ 3")')
        status, detail = _Scene(self, producer=(
            "                  cause_axis=axis)", "                  )"),
            reader=(_READER_PRINT_ANCHOR, fake)).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("не несёт блока `cause_axis`", detail)


class TheProbeHasItsOwnThirdOutcome(unittest.TestCase):

    def test_unmeasured_when_the_producer_is_absent(self):
        status, detail = _Scene(self, drop_producer=True).verdict()
        self.assertEqual(status, UNMEASURED, detail)
        self.assertIn("ci_control.py", detail)

    def test_unmeasured_is_not_an_assertion_about_the_subject(self):
        """«Двери нет» и «дверь врёт» обязаны быть РАЗНЫМИ ответами, а не одним."""
        absent, _ = _Scene(self, drop_producer=True).verdict()
        broken, _ = _Scene(self, producer=(
            "                  cause_axis=axis)", "                  )")).verdict()
        self.assertNotEqual(absent, broken)


if __name__ == "__main__":
    unittest.main()
