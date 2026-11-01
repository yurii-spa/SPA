"""Положительный контроль ПРОБЫ `ci_cause_axis_names_a_session_death` (ADR-892).

`.claude/rules/acceptance.md` §3: новая проба регистрируется только с тестом, где она
**зелена на целом контуре** и **красна на КАЖДОМ порванном звене** — с названным
звеном. Проба, никогда не видевшая настоящей поломки, есть украшение.

Поломка здесь настоящая и датированная: контрольный прогон 41318580149 (`9ebe92509`,
01.11) — первый со снятой осью причин — нёс обморок шарда 7 (pytest упал в своей же
отрисовке провала, `exit 3`), и отчёт сказал о нём «причина не опознана» про жертву и
«две записи одного прогона СПОРЯТ» про запись обморока. Оба утверждения неверны, а
смерти сессии не называл НИКТО.

Звенья настоящие: каждая сцена — ОДНОРАЗОВАЯ КОПИЯ обеих дверей (свод
`scripts/ci_control.py` и читатель `scripts/ci_control_verdict.py`) с ровно одной
снятой половиной, и проба гоняется на ней через свой параметр `repo_root`. Живое дерево
не трогается ни одной сценой; `spa_core` подставляется ссылкой — иначе копия не
ввезлась бы вовсе, и тест мерил бы свою сцену, а не пробу.

ТРЕТИЙ ИСХОД у пробы проверяется ОТДЕЛЬНО (инв. #17): дерево без свода обязано дать
`unmeasured`, а НЕ «не выполнено», иначе «двери нет» стало бы неотличимо от «дверь
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
_PROBE = PROBES["ci_cause_axis_names_a_session_death"]
_PRODUCER = Path("scripts") / "ci_control.py"
_READER = Path("scripts") / "ci_control_verdict.py"

#: Якорь звена «читатель называет обморок находкой» — ОДНА копия на обе сцены,
#: которые его рвут. Две копии разошлись бы с кодом порознь, и сцена молча
#: перестала бы рвать звено (`_Scene` на такой случай ОТКАЗЫВАЕТ).
_READER_DEATH_ANCHOR = '''            out.append(f"СЕССИЯ pytest УМЕРЛА внутренне у шард(ов) {who} "'''


class _Scene:
    """Одноразовое дерево с ОДНИМ порванным звеном. Живое дерево не трогается."""

    def __init__(self, test: unittest.TestCase, *, producer=None, reader=None,
                 drop_producer: bool = False):
        self.root = Path(tempfile.mkdtemp(prefix="spa_c1006_session_death_"))
        test.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        for rel, swap, drop in ((_PRODUCER, producer, drop_producer),
                                (_READER, reader, False)):
            if drop:
                continue
            src = (_REPO / rel).read_text(encoding="utf-8")
            # Шов бывает один (`(old, new)`) или несколько (`[(old, new), …]`):
            # сцена «только слова» рвёт ДВА звена одного файла сразу.
            swaps = [] if swap is None else (
                [swap] if isinstance(swap, tuple) and len(swap) == 2
                and isinstance(swap[0], str) else list(swap))
            for old, new in swaps:
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
        for token in ("шард 7 умер", "TypeError", "жертва названа поимённо",
                      "ложная находка «две записи спорят» снята"):
            self.assertIn(token, detail)

    def test_an_untouched_copy_is_green_too(self):
        """КОНТРОЛЬ ШУМА: копия без правок зелена — значит краснеет именно звено."""
        status, detail = _Scene(self).verdict()
        self.assertEqual(status, SATISFIED, detail)


class TheProbeIsRedOnEveryBrokenLink(unittest.TestCase):

    def test_red_when_the_producer_knows_no_session_death(self):
        """Звено: свод не собирает род обморока — дословное состояние `origin/main`."""
        status, detail = _Scene(self, producer=(
            '''            death = census.session_record
            if death is not None:''',
            '''            death = None
            if death is not None:''')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("РОДА «сессия умерла» у оси нет вовсе", detail)

    def test_red_when_the_victim_loses_its_name(self):
        """Звено: жертва обморока перестаёт называться поимённо."""
        status, detail = _Scene(self, producer=(
            '            victim_rows.append(nodeid)',
            '            pass')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("жертва обморока НЕ НАЗВАНА поимённо", detail)

    def test_red_when_the_session_record_is_counted_as_a_test(self):
        """Звено: запись обморока снова попадает в `record_only` — ЛОЖНЫЙ спор записей."""
        status, detail = _Scene(self, producer=(
            '''            for failure in census.failures:
                if failure.is_session_death:
                    continue
''',
            '''            for failure in census.failures:
''')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("record_only_n", detail)

    def test_red_when_the_victim_falls_into_the_defect_fork(self):
        """Звено: жертва обморока учтена как опознанный провал теста и попала в вилку."""
        status, detail = _Scene(self, producer=(
            '''            victim_rows.append(nodeid)
            continue''',
            '''            victim_rows.append(nodeid)
            attributed.append(next(iter(found.values())))
            continue''')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("ось разошлась со сценой", detail)

    def test_red_when_the_victim_row_carries_no_cause(self):
        """Звено: род назван в оси, а САМА строка жертвы причины не несёт."""
        status, detail = _Scene(self, producer=(
            '''            row["cause"] = {"session_death": True, "shard": shard,
                            "kind": death.get("kind"),
                            "skeleton": death.get("skeleton")}''',
            '            row["cause"] = None')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("САМА СТРОКА жертвы причины не несёт", detail)

    def test_red_when_the_roster_identity_is_not_declared(self):
        """Звено: перечень РОДОВ исхода атрибуции не сверяется с населением."""
        status, detail = _Scene(self, producer=(
            '        "roster": n + len(victim_rows) + len(unattributed) == len(failures),',
            '')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("перечня РОДОВ исхода атрибуции у оси нет", detail)

    def test_red_when_the_kind_is_guessed_instead_of_read(self):
        """Звено: род присваивается по ОТСУТСТВИЮ записи, а не по машинной метке."""
        status, detail = _Scene(self, producer=[
            ('        if jname is not None and jname in victims:',
             '        if jname is not None and (jname in victims or deaths):'),
            ('            shard = victims[jname]',
             '            shard = victims.get(jname, 7)'),
        ]).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("есть догадка", detail)

    def test_red_when_the_reader_does_not_print_the_death(self):
        """Звено: род есть в документе, а в ОТРИСОВАННЫХ строках читателя его нет."""
        status, detail = _Scene(self, producer=(
            '''        parts.append(f"СЕССИЯ УМЕРЛА внутренне у шард(ов) {who} "''',
            '''        parts.append(f"" ""''')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("в ОТРИСОВАННЫХ строках читателя обморока нет", detail)

    def test_red_when_the_reader_keeps_silent_about_the_death(self):
        """Звено: обморок не стал НАХОДКОЙ — молчание читается как «всё в порядке»."""
        status, detail = _Scene(self, reader=(
            _READER_DEATH_ANCHOR,
            '            out.append(f"про причины ничего {who} "')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("не стал НАХОДКОЙ читателя", detail)

    def test_red_when_a_healthy_run_is_accused_of_a_crash(self):
        """Звено: обморок объявляется там, где его не было (fail-OPEN наизнанку)."""
        status, detail = _Scene(self, producer=(
            '            death = census.session_record\n'
            '            if death is not None:',
            '            death = census.session_record or census.failures[0]\n'
            '            if death is not None:')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("обвинение в смерти сессии", detail)

    def test_red_when_the_two_states_share_one_wording(self):
        """Звено: «сессия умерла» и «записи об этом нет» получают ОДНИ слова."""
        status, detail = _Scene(self, reader=(
            '''            out.append(f"{axis['session_victims_n']} падени(й) помечены потоковой "''',
            '''            out.append(f"СЕССИЯ pytest УМЕРЛА обморок {axis['session_victims_n']} "''')
        ).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("ОДНИ слова", detail)

    def test_red_when_the_rendered_line_shares_one_wording(self):
        """Звено: ВТОРАЯ ветка `cause_line` повторяет слова первой.

        `cause_line` одна на `report.md` свода и на шаг 0-офис. Находка у читателя и
        ОТРИСОВАННАЯ строка — два разных места, и до замера мутаций ADR-892 второе не
        проверял никто: мутант №8 («метка без записи» получает слова самого обморока)
        ВЫЖИЛ.
        """
        old = ('        parts.append(f"ЖЕРТВ обморока '
               '{axis[\'session_victims_n\']}, а самой записи "')
        new = ('        parts.append(f"СЕССИЯ УМЕРЛА внутренне '
               '{axis[\'session_victims_n\']}, а записи "')
        status, detail = _Scene(self, producer=(old, new)).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("у двух состояний ОДНИ слова", detail)

    def test_red_when_the_axis_is_only_words(self):
        """ПОДСТРОКА (ADR-333): свод ПЕЧАТАЕТ нужные слова, не опознав обморока.

        Сцена рвёт ДВА звена одного файла сразу: род не собирается вовсе, а строка
        `cause_line` отдаёт дословно то, что проба ищет в отрисовке читателя. Проба,
        довольная словами, здесь позеленела бы; она обязана остаться КРАСНОЙ и назвать
        звено СТРУКТУРНОЕ, а не словесное.
        """
        status, detail = _Scene(self, producer=[
            ("""            death = census.session_record
            if death is not None:""",
             """            death = None
            if death is not None:"""),
            ("""    parts = [f"причины: опознано {axis.get('attributed')} из {pop}"]""",
             """    parts = [f"причины: опознано {axis.get('attributed')} из {pop}",
             "СЕССИЯ УМЕРЛА внутренне у шард(ов) 7 (TypeError: слова без замера)"]"""),
        ]).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("РОДА «сессия умерла» у оси нет вовсе", detail)


class TheProbeHasItsOwnThirdOutcome(unittest.TestCase):

    def test_unmeasured_when_the_producer_is_absent(self):
        status, detail = _Scene(self, drop_producer=True).verdict()
        self.assertEqual(status, UNMEASURED, detail)
        self.assertIn("ci_control.py", detail)

    def test_unmeasured_is_not_an_assertion_about_the_subject(self):
        """«Двери нет» и «дверь врёт» обязаны быть РАЗНЫМИ ответами, а не одним."""
        absent, _ = _Scene(self, drop_producer=True).verdict()
        broken, _ = _Scene(self, producer=(
            '''            death = census.session_record
            if death is not None:''',
            '''            death = None
            if death is not None:''')).verdict()
        self.assertNotEqual(absent, broken)


if __name__ == "__main__":
    unittest.main()
