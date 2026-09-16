"""Контроль пробы `journal_reader_census_reaches_http_routes` — в обе стороны.

Правило `.claude/rules/acceptance.md` §3: новая проба регистрируется только с
тестом, где она ЗЕЛЕНА на целом контуре и КРАСНА на каждом порванном звене — с
названным звеном, — и где она не проходит подстрокой (ADR-333).

Контур настоящий: строятся настоящие стенды, зовётся настоящая партия
(`http_probe_batch` → отдельные процессы → настоящие обработчики роутера
`tier1`). Живой `data/` не открывается: журнал и `tier1_verdict.json` стенда
пишет сама проба.

Три звена пробы, и каждое ломается ОТДЕЛЬНО:

1. каталог стенда доходит до чужого процесса (пин `SPA_DATA_DIR`);
2. модуль получает вердикт ПО МАРШРУТАМ, а не на целом модуле;
3. стенд ДОКАЗАННО дошёл до обработчика (проба пустого каталога).
"""
# FROZEN-DATE-OK: даты в стенде пробы — её собственный синтетический журнал,
# а не отметка свежести; ни одна проверка здесь не смотрит на стенные часы.
from __future__ import annotations

import unittest
from unittest import mock

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import run_identity_key_price as census

_NAME = "journal_reader_census_reaches_http_routes"


class ProbeIsRegistered(unittest.TestCase):

    def test_the_probe_answers_under_its_registered_name(self):
        self.assertIn(_NAME, ca.PROBES)
        self.assertIsNone(ca.validate_spec(_NAME))

    def test_an_argument_is_refused_out_loud(self):
        """Пофайловой формы у критерия нет: «у моего роутера чисто» — зелёный
        ответ на свой вопрос, выданный за нужный. Отказ обязан быть
        `unmeasured`, а не тихим игнорированием аргумента."""
        verdict, detail = ca.run_probe(f"{_NAME}:spa_core")
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не принимает аргумента", detail)


class GreenOnTheWholeContour(unittest.TestCase):

    def test_the_shipped_contour_satisfies_the_criterion(self):
        verdict, detail = ca.run_probe(_NAME)
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertIn("стенда достигли", detail)


class RedOnEachBrokenLink(unittest.TestCase):
    """Каждое звено рвётся ОТДЕЛЬНО, и проба называет ИМЕННО его."""

    def test_link_1_the_stand_dir_pin_removed_from_the_child_process(self):
        """Снятый пин `SPA_DATA_DIR` — это не «чуть хуже»: обработчики
        прочитали бы ЖИВОЙ каталог, а перепись доложила бы «нечувствителен к
        стенду». Процесс-зовущий отказывает fail-CLOSED, партия пуста."""
        real = census._run_http_probe

        def unpinned(stand_data, names, tree_root):
            with mock.patch.dict("os.environ", {}, clear=False):
                import os
                os.environ.pop("SPA_DATA_DIR", None)
                import subprocess
                import tempfile
                from pathlib import Path
                import json
                with tempfile.TemporaryDirectory() as tmp:
                    mods = Path(tmp) / "m.json"
                    mods.write_text(json.dumps(list(names)), encoding="utf-8")
                    out = Path(tmp) / "o.json"
                    env = dict(os.environ)
                    env.pop("SPA_DATA_DIR", None)
                    env["PYTHONPATH"] = str(tree_root)
                    proc = subprocess.run(
                        [__import__("sys").executable, "-m",
                         "spa_core.monitoring._http_reader_probe", str(mods), str(out)],
                        cwd=str(tree_root), env=env, capture_output=True)
                    if proc.returncode != 0:
                        return None, f"процесс-зовущий вышел кодом {proc.returncode}"
                    return json.loads(out.read_text(encoding="utf-8")), ""

        with mock.patch.object(census, "_run_http_probe", unpinned):
            verdict, detail = ca.run_probe(_NAME)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("звено 1", detail)
        self.assertIsNot(census._run_http_probe, unpinned, "подмена не снята")
        self.assertIs(census._run_http_probe, real)

    def test_link_2_the_verdict_goes_back_to_the_whole_module(self):
        """Вердикт на ЦЕЛОМ модуле — та самая гранулярность, при которой один
        шумный маршрут прятал десять соседей (замер на `rates_desk`)."""
        real = census.classify_http_reader

        def whole_module(module_name, probes):
            row = real(module_name, probes)
            row.pop("routes", None)
            return row

        with mock.patch.object(census, "classify_http_reader", whole_module):
            verdict, detail = ca.run_probe(_NAME)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("звено 2", detail)

    def test_link_3_the_empty_stand_probe_stops_proving_anything(self):
        """Без пробы пустого каталога «нечувствителен к стенду» становится
        утверждением о читателе, которого стенд не касался."""
        real = census.verdict_from_probes

        def blind(row, raw1, raw1_again, raw2, raw3, on_empty=census._NO_EMPTY_PROBE):
            return real(row, raw1, raw1_again, raw2, raw3)

        with mock.patch.object(census, "verdict_from_probes", blind):
            verdict, detail = ca.run_probe(_NAME)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("звено 3", detail)

    def test_a_crash_inside_the_contour_is_unmeasured_never_a_verdict(self):
        """«Не измерено» обязано быть отличимо и от `satisfied`, и от
        `not_satisfied` (инв. #17): упавший контур ничего не доказал."""
        def boom(*a, **k):
            raise RuntimeError("стенды не построились")

        with mock.patch.object(census, "build_stands", boom):
            verdict, detail = ca.run_probe(_NAME)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("RuntimeError", detail)


class VerdictDoesNotRideOnASubstring(unittest.TestCase):
    """ADR-333: вердикт обязан стоять на ИСХОДЕ, а не на совпадении текста."""

    def test_a_module_that_only_NAMES_its_routes_does_not_pass(self):
        """Модуль, у которого разбор маршрутов есть, но НИ ОДИН не доказал, что
        стенд до него дошёл, зелёным быть не может — даже когда в его ответах
        слова про маршруты и стенд присутствуют."""
        real = census.classify_http_reader

        def talks_but_proves_nothing(module_name, probes):
            row = real(module_name, probes)
            for value in (row.get("routes") or {}).values():
                value.pop("reaches_stand", None)
                value["reason"] = ("маршрут прочитал стенд, reaches_stand, "
                                   "стенда достигли — но это только слова")
            return row

        with mock.patch.object(census, "classify_http_reader", talks_but_proves_nothing):
            verdict, detail = ca.run_probe(_NAME)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("звено 3", detail)


if __name__ == "__main__":
    unittest.main()
