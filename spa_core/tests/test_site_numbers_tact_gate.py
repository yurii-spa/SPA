#!/usr/bin/env python3
"""Гейт недельного такта витрины живёт в ПРОИЗВОДИТЕЛЕ, а не в `main`.

Заказ **G40 п. 1** приказа владельца «Portfolio CIO» — единственная находка
переписи гейтов такта ([ADR-415](../../docs/decisions/ADR-415-tact-gate-census-where-the-due-decision-lives.md)):
у `scripts/build_site_numbers.py` предикат `publication_due` звался только из
`main`, а производящая функция была открыта. Заказ велел находку ПОЧИНИТЬ, а не
перевыставить, и назвал приёмку: перепись переходит в `CLEAN`, `publication_due`
зовётся из `run`.

## Почему это не косметика

Пока звавший один — рука цикла на шаге (1е) — вреда нет, и ADR-415 сказал это
вслух. Вред приходит со ВТОРЫМ звавшим: ступень моста, позвав производителя
напрямую, опубликовала бы витрину мимо недельного такта, а повторив правило у
себя — завела бы его ВТОРУЮ копию. Копии расходятся молча, обе стороны при этом
выглядят исправно (класс ADR-220).

## Что здесь сторожится, и обе стороны у каждой проверки

1. **Где лежит решение** — вердиктом СОБСТВЕННОГО классификатора переписи, а не
   подстрокой; обратная сторона: тот же классификатор на сцене «гейт только в
   `main`» по-прежнему называет находку, иначе проверка была бы пустой.
2. **Что гейт работает у ЛЮБОГО звавшего** — внутри недели производитель не
   пишет ни байта, за неделей пишет; звавший при этом о неделе ничего не знает.
3. **Что второй копии правила нет** — рука (`main`) и производитель (`run`)
   отвечают ОДНОЙ строкой-причиной на один и тот же день.
4. **Что третий исход цел** — источник не прочитан ⇒ отказ целиком и код 2, а
   не половинчатая витрина (инв. #17).

Числа витрины (предмет №2 границы ADR-285) здесь не трогаются: живой
`landing/src/data/site_numbers.json` читается только на байты и обязан остаться
байт-в-байт тем же.
"""
# FROZEN-DATE-OK: injected-clock — якорь ANCHOR порождает ВСЕ даты сцен, и он же
# уходит аргументом в проверяемый код (`run(published_at=…)`, `publication_due(today=…)`):
# обе стороны пришпилены, сдвиг календаря вердикта не меняет. Сцены, где дата берётся
# у ЖИВОЙ витрины, читают её из самого файла и литерала не содержат вовсе.
from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "_bsn_tact", ROOT / "scripts" / "build_site_numbers.py")
bsn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bsn)

from spa_core.monitoring.tact_gate_census import (  # noqa: E402
    CLASS_CLI_ONLY, CLASS_IN_PRODUCER, _Walker, classify)

#: Якорь сцен. Literal ровно один, и всё остальное происходит от него.
ANCHOR = date.fromisoformat("2026-09-13")

PRODUCER = ROOT / "scripts" / "build_site_numbers.py"


def _gate_calls(source: str):
    walker = _Walker()
    walker.visit(ast.parse(source))
    return walker.gate_calls


class TheGateLivesInTheProducer(unittest.TestCase):
    """Приёмка заказа G40 п. 1, снятая ПРИБОРОМ переписи, а не глазами."""

    def test_the_census_classifier_calls_this_module_gated_in_its_producer(self):
        calls = _gate_calls(PRODUCER.read_text(encoding="utf-8"))
        self.assertTrue(calls, "предиката срока в модуле не нашлось вовсе")
        self.assertEqual(classify(calls), CLASS_IN_PRODUCER)

    def test_the_predicate_is_called_from_run_and_from_nowhere_else(self):
        """Второй копии правила нет: зов ровно один и он внутри `run`."""
        holders = sorted({enclosing for _, enclosing, _ in
                          _gate_calls(PRODUCER.read_text(encoding="utf-8"))})
        self.assertEqual(holders, ["run"])

    def test_the_same_classifier_still_finds_a_cli_only_gate(self):
        """Обратная сторона: утверждение выше не выполнено по построению.

        Классификатор обязан уметь сказать «находка» — иначе первая проверка
        зелена при ЛЮБОМ устройстве модуля и сторожит пустоту. Сцена — ровно
        то состояние, в котором находку нашёл ADR-415.
        """
        scene = (
            "def publication_due():\n"
            "    return True, 'да'\n"
            "def build():\n"
            "    return {}\n"
            "def main():\n"
            "    due, why = publication_due()\n"
            "    if not due:\n"
            "        return 0\n"
            "    return build()\n")
        self.assertEqual(classify(_gate_calls(scene)), CLASS_CLI_ONLY)


class _Stand(unittest.TestCase):
    """Сцена целиком во временном каталоге: живой сайт не пишется ни разу."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="spa_tact_"))
        self.shelf = self.d / "site_numbers.json"

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _publish_stub(self, when: date) -> bytes:
        self.shelf.write_text(json.dumps({"published_at": when.isoformat()}),
                              encoding="utf-8")
        return self.shelf.read_bytes()


class AnyCallerIsGatedByTheOneRule(_Stand):
    """Звавший о неделе ничего не знает — и всё равно ею гейтится."""

    def test_inside_the_week_the_producer_writes_not_a_single_byte(self):
        before = self._publish_stub(ANCHOR)
        outcome = bsn.run(published_at=(ANCHOR + timedelta(days=3)).isoformat(),
                          if_due=True, out=self.shelf)
        self.assertFalse(outcome["published"])
        self.assertIn("из 7", outcome["reason"])
        self.assertEqual(self.shelf.read_bytes(), before,
                         "витрина переписана раньше срока — такт держится не файлом")

    def test_after_the_week_the_producer_publishes(self):
        """Обратная сторона: гейт не залипает в «никогда»."""
        self._publish_stub(ANCHOR)
        when = (ANCHOR + timedelta(days=7)).isoformat()
        outcome = bsn.run(published_at=when, if_due=True, out=self.shelf)
        self.assertTrue(outcome["published"])
        self.assertEqual(json.loads(self.shelf.read_text(encoding="utf-8"))["published_at"],
                         when)

    def test_without_the_gate_the_caller_publishes_explicitly(self):
        """`if_due=False` — осознанная публикация, а не обход такта втихую."""
        self._publish_stub(ANCHOR)
        when = (ANCHOR + timedelta(days=1)).isoformat()
        outcome = bsn.run(published_at=when, if_due=False, out=self.shelf)
        self.assertTrue(outcome["published"])
        self.assertEqual(json.loads(self.shelf.read_text(encoding="utf-8"))["published_at"],
                         when)

    def test_a_dry_caller_gets_the_text_and_leaves_the_file_alone(self):
        """`write=False` — сцена CI (`--check`): сравнить, НЕ опубликовав.

        Найдено батареей мутаций: `write` пережил снятие условия молча, то есть
        сравнение в CI имело право переписать витрину. Числа витрины — предмет
        №2 границы, и двигать их проверкой нельзя.
        """
        before = self._publish_stub(ANCHOR)
        outcome = bsn.run(published_at=(ANCHOR + timedelta(days=7)).isoformat(),
                          if_due=True, write=False, out=self.shelf)
        self.assertTrue(outcome["published"], "такт прошёл, а витрина не собрана")
        self.assertIn("published_at", outcome["text"])
        self.assertEqual(self.shelf.read_bytes(), before,
                         "сравнение опубликовало витрину — байты записаны без спроса")

    def test_a_refused_tact_is_distinguishable_from_a_publication(self):
        """Инв. #17: «не публиковали» и «опубликовано» — разные исходы, не «пусто»."""
        self._publish_stub(ANCHOR)
        refused = bsn.run(published_at=(ANCHOR + timedelta(days=1)).isoformat(),
                          if_due=True, out=self.shelf)
        self.assertNotIn("doc", refused)
        self.assertTrue(refused["reason"])


class TheHandAndTheProducerAnswerWithOneRule(_Stand):
    """`main` делегирует: своей копии правила недели у руки цикла нет.

    Сцена — КОПИЯ живой витрины (та самая, которую зовёт шаг (1е) цикла), а
    `OUT` на время проверки указывает на копию. Это не удобство: под мутацией
    «гейт снят» проверка обязана ПАДАТЬ, а не публиковать живую витрину мимо
    недельного такта — числа витрины предмет №2 границы ADR-285, и тест не
    вправе их двигать даже доказывая свою правоту. Замерено: без подмены
    батарея мутаций переписала `landing/src/data/site_numbers.json`.

    День берётся из самой витрины (возраст 0 ⇒ не срок), поэтому сцена не
    зависит от календаря и литерала даты не содержит.
    """

    def setUp(self):
        super().setUp()
        self.live = bsn.OUT.read_bytes()
        self.shelf.write_bytes(self.live)
        self._out, bsn.OUT = bsn.OUT, self.shelf

    def tearDown(self):
        bsn.OUT = self._out
        super().tearDown()

    def test_the_cli_prints_the_reason_the_producer_returned(self):
        today = str(json.loads(self.shelf.read_text(encoding="utf-8"))["published_at"])

        outcome = bsn.run(published_at=today, if_due=True)
        self.assertFalse(outcome["published"], "витрина опубликована в день публикации")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = bsn.main(["--if-due", "--published-at", today])
        self.assertEqual(code, 0)
        self.assertIn(outcome["reason"], buf.getvalue())
        self.assertEqual(self.shelf.read_bytes(), self.live,
                         "витрина переписана раньше срока — рука обошла такт")
        self.assertEqual(self._out.read_bytes(), self.live,
                         "живой файл витрины тронут проверкой — предмет №2 границы")


class TheThirdOutcomeSurvivedTheMove(_Stand):
    """Отказ источника остаётся отказом ЦЕЛИКОМ и кодом 2 (инв. #17)."""

    def test_an_unreadable_source_refuses_inside_run(self):
        self._publish_stub(ANCHOR)
        original = bsn.SNAPSHOT
        bsn.SNAPSHOT = self.d / "нет-такого-снимка.json"
        try:
            with self.assertRaises(bsn.NotMeasured):
                bsn.run(published_at=(ANCHOR + timedelta(days=7)).isoformat(),
                        if_due=True, out=self.shelf)
        finally:
            bsn.SNAPSHOT = original

    def test_the_cli_turns_that_refusal_into_exit_two(self):
        original = bsn.SNAPSHOT
        bsn.SNAPSHOT = self.d / "нет-такого-снимка.json"
        try:
            self.assertEqual(bsn.main(["--check", "--published-at", ANCHOR.isoformat()]), 2)
        finally:
            bsn.SNAPSHOT = original


if __name__ == "__main__":
    unittest.main()
