"""Контроль пробы приёмки `absent_observation_class_closed` — в обе стороны.

Правило `.claude/rules/acceptance.md` §3: новая проба регистрируется ТОЛЬКО с
тестом, где она зелена на целом контуре и красна на КАЖДОМ порванном звене — с
названным звеном, — и где она не проходит подстрокой.

Стенд одноразовый: и дерево, и база инъектируются (`root=`, `baseline_path=`).
Обе двери к живой копии закрыты намеренно — иначе вердикт стенда зависел бы от
того, что правит соседняя сессия, и «красный» значил бы «кто-то рядом работает».

Дат в файле нет вовсе, и пометка об освобождении тоже не нужна: предмет пробы —
AST исходников, а не свежесть артефакта, и стенных часов она не спрашивает.
Первая редакция несла `FROZEN-DATE-OK: injected-clock` «на всякий случай», и
сторож притязаний (`test_injected_clock_claim`) справедливо покраснел: пометка
утверждала инъекцию, которой нет, потому что освобождать нечего.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import card_acceptance as ca
from spa_core.tests import _absent_observation as ao

#: Писатель артефакта с ОДНИМ членом класса: чтение наблюдения, ключ из словаря
#: наблюдений и падающий литерал справа от `or` — все три признака сразу.
_MEMBER = '''
from spa_core.utils.atomic import atomic_save


def write(doc, path):
    tvl = doc.get("tvl_usd") or 0.0
    atomic_save(path, {"tvl_usd": tvl})
'''

#: Тот же писатель БЕЗ подстановки. Нужен как обратный контроль: без него
#: «красный на члене» доказывал бы лишь, что файл вообще существует.
_CLEAN = '''
from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed


def write(doc, path):
    tvl = observed(doc, "tvl_usd", kind=(int, float))
    atomic_save(path, {"tvl_usd": tvl,
                       "tvl_unmeasured": tvl is None})
'''


def _stand(body: str) -> Path:
    """Одноразовое дерево с одним модулем в наблюдаемой области."""
    root = Path(tempfile.mkdtemp(prefix="spa_aoc_probe_"))
    pkg = root / "spa_core" / "monitoring"
    pkg.mkdir(parents=True)
    (pkg / "writer.py").write_text(body, encoding="utf-8")
    return root


def _baseline(places: list) -> Path:
    """База той же формы, что настоящая, с названными местами сигнала `or_falsy`."""
    path = Path(tempfile.mkdtemp(prefix="spa_aoc_base_")) / "baseline.json"
    path.write_text(json.dumps({
        "_comment": "x" * 220,
        "signals": {
            ao.SIGNAL_OR: {"_what": "y" * 50, "places": list(places)},
            ao.SIGNAL_EXCEPT: {"_what": "y" * 50, "places": []},
        }}, ensure_ascii=False), encoding="utf-8")
    return path


class TheStandIsRealBeforeAnythingIsClaimed(unittest.TestCase):
    """Предпосылка стенда — ИЗМЕРЕНА. Стенд, который не несёт члена класса,
    сделал бы все остальные тесты истинными по построению."""

    def test_the_member_stand_really_carries_one_member(self):
        root = _stand(_MEMBER)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        places = ao.places_of(ao.scan_tree(root), ao.SIGNAL_OR)
        self.assertEqual(len(places), 1, places)

    def test_the_clean_stand_carries_none(self):
        root = _stand(_CLEAN)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.assertEqual(ao.places_of(ao.scan_tree(root), ao.SIGNAL_OR), [])


class ProbeIsGreenOnTheWholeContour(unittest.TestCase):

    def test_clean_tree_and_empty_baseline_is_satisfied(self):
        root = _stand(_CLEAN)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        base = _baseline([])
        self.addCleanup(shutil.rmtree, base.parent, ignore_errors=True)
        got = ca.measure_absent_observation_class(root=root, baseline_path=base)
        self.assertTrue(got["measured"], got.get("reason"))
        self.assertEqual(got["new"], [])
        self.assertEqual(got["over_ceiling"], {})

    def test_the_live_tree_answers_satisfied_today(self):
        """Тот же вердикт, что печатает шаг 0-офис, — на ЖИВОМ дереве.

        Этот тест и есть приёмка карточки
        `inbox-hrapovik-invarianta-17-krasen-na-chistom`: он краснеет, как
        только класс снова вырастет, независимо от того, чей писатель его
        вырастил.
        """
        verdict, detail = ca.run_probe("absent_observation_class_closed")
        self.assertEqual(verdict, ca.SATISFIED, detail)


class EachBrokenLinkTurnsItRed(unittest.TestCase):
    """Каждое звено — своей сценой, и звено названо в имени теста."""

    def test_a_new_member_outside_the_baseline_is_not_satisfied(self):
        root = _stand(_MEMBER)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        base = _baseline([])
        self.addCleanup(shutil.rmtree, base.parent, ignore_errors=True)
        got = ca.measure_absent_observation_class(root=root, baseline_path=base)
        self.assertEqual(len(got["new"]), 1, got)

    def test_a_member_already_in_the_baseline_is_not_new(self):
        """Обратный контроль к предыдущему: разрешённое место красным не делает,
        иначе проба краснела бы на 148 местах, которые база несёт по решению."""
        root = _stand(_MEMBER)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        place = ao.places_of(ao.scan_tree(root), ao.SIGNAL_OR)[0]
        base = _baseline([place])
        self.addCleanup(shutil.rmtree, base.parent, ignore_errors=True)
        got = ca.measure_absent_observation_class(root=root, baseline_path=base)
        self.assertEqual(got["new"], [])

    def test_a_grown_baseline_is_not_satisfied_even_with_no_new_member(self):
        """Вторая половина критерия. Без неё первую можно было бы «выполнить»
        дописыванием в базу — ровно тем, что запрещает инв. #16."""
        from spa_core.tests import test_absent_observation_ratchet as ratchet
        root = _stand(_CLEAN)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        over = ratchet.CEILINGS[ao.SIGNAL_OR] + 1
        base = _baseline([f"spa_core/x{i}.py:1:{i:012x}#0" for i in range(over)])
        self.addCleanup(shutil.rmtree, base.parent, ignore_errors=True)
        got = ca.measure_absent_observation_class(root=root, baseline_path=base)
        self.assertEqual(got["new"], [], "стенд обязан быть чист по первой половине")
        self.assertIn(ao.SIGNAL_OR, got["over_ceiling"])

    def test_an_unreadable_baseline_is_unmeasured_not_a_verdict(self):
        """Третий исход. «Нечем мерить» не есть ни «класс закрыт», ни «открыт»."""
        root = _stand(_CLEAN)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        base = _baseline([])
        base.write_text("{ это не json", encoding="utf-8")
        self.addCleanup(shutil.rmtree, base.parent, ignore_errors=True)
        got = ca.measure_absent_observation_class(root=root, baseline_path=base)
        self.assertFalse(got["measured"])
        self.assertIn("замер не состоялся", got["reason"])

    def test_an_argument_is_refused_out_loud(self):
        """Пофайловой формы у критерия нет намеренно: «у меня чисто» при
        выросшем соседе — зелёный ответ на свой вопрос, выданный за нужный."""
        verdict, detail = ca.run_probe("absent_observation_class_closed:spa_core")
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не принимает аргумента", detail)


class VerdictDoesNotRideOnASubstring(unittest.TestCase):
    """Правило §3: проба НЕ проходит подстрокой."""

    def test_a_file_merely_naming_the_invariant_does_not_pass(self):
        """Файл, где слова про инвариант есть, а подстановка ЖИВА, обязан
        краснеть: иначе пробу закрывал бы комментарий."""
        root = _stand('''
# Инвариант #17: отсутствие наблюдения обязано быть представлено отдельным
# значением. `observed()` честнее подстановки. НЕ ИЗМЕРЕНО.
''' + _MEMBER)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        base = _baseline([])
        self.addCleanup(shutil.rmtree, base.parent, ignore_errors=True)
        got = ca.measure_absent_observation_class(root=root, baseline_path=base)
        self.assertEqual(len(got["new"]), 1, "проза о наблюдении зачлась за починку")

    def test_the_probe_is_registered_under_its_name(self):
        self.assertIn("absent_observation_class_closed", ca.PROBES)
        self.assertIsNone(ca.validate_spec("absent_observation_class_closed"))


if __name__ == "__main__":
    unittest.main()
