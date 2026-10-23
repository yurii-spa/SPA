"""Правило «запись в реестре R&D = проводка» — и его границы.

Карточка `inbox-hrapovik-nepodklyuchennyh-skriptov-ne-ot` (цикл #192 оставил храповик
КРАСНЫМ осознанно): у сторожа не было способа отличить два вида скриптов без
вызывающего — «доставлен и мёртв» (ради чего он заведён) и «исследовательский замер,
который запускают руками» (26 штук, 25 внесены в базу задним числом). Пока различия
нет, каждый новый R&D-замер упирается в выбор: соврать базе или держать CI красным.

**Почему правило узкое.** Карточка рекомендовала считать проводкой любое упоминание
в `docs/`. Замер 13.08 это отверг: имя хотя бы одного из 88 скриптов без вызывающего
встречается где-нибудь в `docs/` у 62 из них, а у пяти единственное упоминание — в
`docs/journal/`, то есть в летописи, которая называет поимённо всё доставленное.
Правило «любой docs/» сняло бы с учёта две трети подопечных — это не различение
классов, а отключение сторожа. Засчитывается ТОЛЬКО реестр R&D-идей.

Каждая проверка ниже — на синтетическом дереве (корень — вход функции, а не окружение),
поэтому у каждой есть честная мутация: убери правило — проверка покраснеет поимённо.
"""
from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from spa_core.tests import _unwired
from spa_core.tests._unwired import (
    entrypoint_scripts,
    registry_recorded_scripts,
    scripts_without_caller,
    unwired_scripts,
)


def _fake_repo(tmp: pathlib.Path) -> pathlib.Path:
    """Крошечный репозиторий со всеми четырьмя случаями сразу."""
    (tmp / "scripts").mkdir(parents=True)
    (tmp / "launchd").mkdir()
    (tmp / "docs" / "journal").mkdir(parents=True)

    body = 'if __name__ == "__main__":\n    pass\n'
    for name in ("alone.py", "wired.py", "journal_only.py", "measured.py"):
        (tmp / "scripts" / name).write_text(body, encoding="utf-8")

    # НАСТОЯЩАЯ проводка: обёртка зовёт wired.py
    (tmp / "scripts" / "run_it.sh").write_text(
        '#!/bin/bash\npython3 scripts/wired.py --once\n', encoding="utf-8")
    # летопись называет journal_only.py поимённо — и это НЕ проводка
    (tmp / "docs" / "journal" / "2026-W33.md").write_text(
        "цикл #999 доставил scripts/journal_only.py, 4 теста\n", encoding="utf-8")
    # реестр R&D: продукт measured.py — запись в нём
    (tmp / "docs" / "DYNAMIC_LEVERAGE_GUARDIAN.md").write_text(
        "### Идея #99 — проверено scripts/measured.py: Calmar 0.81 против 0.79\n",
        encoding="utf-8")
    return tmp


class TestTheRuleOnASyntheticRepo(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = _fake_repo(pathlib.Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def test_the_raw_measurement_forgives_nothing(self):
        """`scripts_without_caller` отвечает на свой вопрос — «его кто-то ЗОВЁТ?».

        Реестр здесь не прощает: у measured.py вызывающего нет, и сырое измерение
        обязано это сказать. Иначе различить два вида будет нечем.
        """
        self.assertEqual(
            scripts_without_caller(self.root),
            ["alone", "journal_only", "measured"])

    def test_a_registry_record_counts_as_wiring(self):
        """measured.py уходит из-под храповика — его продукт доставлен в реестр."""
        self.assertNotIn("measured", unwired_scripts(self.root))
        self.assertEqual(registry_recorded_scripts(self.root), {"measured"})

    def test_a_mention_in_the_journal_does_NOT_count(self):
        """Летопись называет всё доставленное — доказательством она не является."""
        self.assertIn("journal_only", unwired_scripts(self.root))

    def test_a_script_nobody_calls_and_nobody_measured_stays_watched(self):
        """Тот самый класс, ради которого храповик заведён."""
        self.assertIn("alone", unwired_scripts(self.root))

    def test_a_real_caller_is_still_seen(self):
        """Положительный контроль детектора: настоящий вызов из обёртки виден."""
        self.assertNotIn("wired", scripts_without_caller(self.root))
        self.assertNotIn("wired", unwired_scripts(self.root))

    def test_mutation_without_the_registry_the_measured_script_reddens(self):
        """Мутация: нет реестра — measured.py снова объявлен мёртвым.

        Это и есть доказательство, что зелёный храповик держится ИМЕННО правилом,
        а не тем, что скрипт где-то случайно упомянут.
        """
        (self.root / "docs" / "DYNAMIC_LEVERAGE_GUARDIAN.md").unlink()
        self.assertIn("measured", unwired_scripts(self.root))


    def test_a_quarantine_record_counts_only_when_it_names_the_script(self):
        """Синтетика: пустой реестр карантина не прощает никого."""
        (self.root / "attic" / "agents").mkdir(parents=True)
        (self.root / "attic" / "agents" / "QUARANTINE.json").write_text(
            '{"quarantined": {"x": {"restore": "python3 scripts/alone.py restore x"}}}',
            encoding="utf-8")
        self.assertIn("alone", registry_recorded_scripts(self.root))
        (self.root / "attic" / "agents" / "QUARANTINE.json").write_text(
            '{"quarantined": {}}', encoding="utf-8")
        self.assertNotIn("alone", registry_recorded_scripts(self.root))


class TestTheCarveOutAuditOnASyntheticRepo(unittest.TestCase):
    """Контроли аудита вычета (ADR-792) — на синтетическом дереве, в ОБЕ стороны.

    Проверка на настоящем дереве (`test_the_carve_out_did_not_swallow_the_watch`)
    отвечает про СЕГОДНЯШНЕЕ состояние и мутации не допускает: правило там не
    расширишь, не расширив его всем. Поэтому каждая нога аудита доказывается
    здесь дважды — целый контур зелен, порванное звено НАЗВАНО и красно.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = _fake_repo(pathlib.Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def test_the_intact_contour_is_green_on_every_leg(self):
        """Положительный контроль: на целом правиле все три ноги держатся."""
        got = _unwired.carve_out_audit(self.root)
        self.assertTrue(got["measured"], got.get("reason"))
        self.assertEqual(got["excused"], ["measured"])
        self.assertEqual(got["watched"], ["alone", "journal_only"])
        self.assertEqual(got["rejected_rule_excused"], ["journal_only", "measured"])
        self.assertEqual(got["narrowed"], ["journal_only"])
        self.assertEqual(got["journal_only"], ["journal_only"])
        self.assertEqual(got["journal_only_excused"], [])

    def test_mutation_the_journal_becomes_evidence_reddens_its_own_leg(self):
        """Звено 2: летопись внесена в реестры-продукты ⇒ прощает летопись.

        Это ровно то расширение, которое замер 13.08 отверг, и нога про
        летопись обязана назвать его поимённо.
        """
        widened = _unwired._PRODUCT_REGISTRIES + (
            pathlib.Path("docs") / "journal" / "2026-W33.md",)
        with mock.patch.object(_unwired, "_PRODUCT_REGISTRIES", widened):
            got = _unwired.carve_out_audit(self.root)
        self.assertTrue(got["measured"], got.get("reason"))
        self.assertEqual(got["journal_only_excused"], ["journal_only"])

    def test_mutation_the_rule_widened_to_all_of_docs_collapses_the_gap(self):
        """Звено 1: правило расширено до «любого упоминания в docs/» ⇒ разрыв пуст.

        Расширение изображено не подменой функции, а честным путём: все файлы
        `docs/` объявлены реестрами-продуктами. Тогда действующее правило
        прощает РОВНО то же, что отвергнутое, — и нога про разрыв краснеет.
        """
        every_doc = tuple(sorted(
            p.relative_to(self.root) for p in (self.root / "docs").rglob("*")
            if p.is_file()))
        with mock.patch.object(_unwired, "_PRODUCT_REGISTRIES", every_doc):
            got = _unwired.carve_out_audit(self.root)
        self.assertTrue(got["measured"], got.get("reason"))
        self.assertEqual(got["narrowed"], [],
                         "правило расширено до всего docs/, а разрыв не схлопнулся — "
                         "значит нога про разрыв меряет что-то другое")
        self.assertEqual(got["excused"], got["rejected_rule_excused"])

    def test_without_docs_the_audit_refuses_loudly(self):
        """Третий исход (инв. #17): `docs/` нет ⇒ НЕ ИЗМЕРЕНО с причиной.

        Не «правило цело» и не «правило расширено»: отвергнутое правило мерить
        нечем, а молчание сделало бы вердикт fail-OPEN.
        """
        shutil.rmtree(self.root / "docs")
        got = _unwired.carve_out_audit(self.root)
        self.assertFalse(got["measured"])
        self.assertIn("docs", got["reason"])

    def test_an_empty_docs_tree_is_also_not_measured(self):
        """Каталог есть, читаемых файлов нет — тот же третий исход.

        Пустой `docs/` дал бы `rejected_rule_excused` пустым, то есть разрыв
        «непуст» стал бы недостижим — вердикт обязан быть отказом, а не красным
        по ложной причине.
        """
        for p in (self.root / "docs").rglob("*"):
            if p.is_file():
                p.unlink()
        got = _unwired.carve_out_audit(self.root)
        self.assertFalse(got["measured"])
        self.assertIn("не прочитан ни один файл", got["reason"])

    def test_without_entrypoints_the_audit_refuses_loudly(self):
        """Нет точек входа ⇒ НЕ ИЗМЕРЕНО: пустое население зеленит всё молча."""
        for p in (self.root / "scripts").glob("*.py"):
            p.unlink()
        got = _unwired.carve_out_audit(self.root)
        self.assertFalse(got["measured"])
        self.assertIn("точек входа", got["reason"])

    def test_the_audit_does_not_keep_a_second_copy_of_the_rule(self):
        """`excused`/`watched` аудита — ровно то же, что считает само правило.

        Вторая копия правила разошлась бы с первой молча, и аудит судил бы о
        своём правиле, а не о действующем.
        """
        got = _unwired.carve_out_audit(self.root)
        self.assertEqual(set(got["excused"]),
                         registry_recorded_scripts(self.root) & set(got["raw"]))
        self.assertEqual(got["watched"], unwired_scripts(self.root))

    def test_the_complaint_distinguishes_all_three_outcomes(self):
        """ЖАЛОБА сторожа различает три исхода — и это закреплено синтетикой.

        Найдено МУТАЦИЕЙ (прогон №1, ADR-792): на настоящем дереве вердикт
        сегодня `OK`, поэтому «строго `OK`» и «`OK` ЛИБО `unmeasured`»
        неотличимы, и fail-OPEN инв. #17 въехал бы молча. Воспроизвести
        «настоящее дерево неизмеримо» нельзя — зато само РАЗЛИЧЕНИЕ живёт в
        `carve_out_complaint`, и вот оно, в три стороны.
        """
        ok = _unwired.carve_out_audit(self.root)
        self.assertIsNone(_unwired.carve_out_complaint(ok))

        widened = _unwired._PRODUCT_REGISTRIES + (
            pathlib.Path("docs") / "journal" / "2026-W33.md",)
        with mock.patch.object(_unwired, "_PRODUCT_REGISTRIES", widened):
            broken = _unwired.carve_out_audit(self.root)
        complaint = _unwired.carve_out_complaint(broken)
        self.assertIsNotNone(complaint)
        self.assertNotIn("НЕ ИЗМЕРЕН", complaint,
                         "поломка правила подана как «не измерено» — два разных "
                         "исхода схлопнулись")

        shutil.rmtree(self.root / "docs")
        unmeasured = _unwired.carve_out_audit(self.root)
        complaint = _unwired.carve_out_complaint(unmeasured)
        self.assertIsNotNone(complaint, "«не измерено» зачтено за зелёное (инв. #17)")
        self.assertIn("НЕ ИЗМЕРЕН", complaint)

    def test_joining_the_docs_does_not_invent_a_mention(self):
        """Контроль решения о СКЛЕЙКЕ: упоминание не возникает на шве.

        Аудит склеивает тексты `docs/` через `\n` (замер: 68.8 с пофайлово
        против 39 с склейкой). Если шов однажды начнёт давать совпадение,
        отвергнутое правило станет шире самого себя, и разрыв схлопнется по
        причине, не имеющей отношения к правилу.
        """
        (self.root / "docs" / "a_tail.md").write_text("хвост scripts/al", encoding="utf-8")
        (self.root / "docs" / "b_head.md").write_text("one.py голова", encoding="utf-8")
        got = _unwired.carve_out_audit(self.root)
        self.assertNotIn("alone", got["rejected_rule_excused"],
                         "шов склейки выдумал упоминание, которого нет ни в одном файле")


class TestTheRuleOnTheRealRepo(unittest.TestCase):
    """То же самое, но на настоящем дереве — синтетика не заменяет факта."""

    def test_edge_exposure_depth_is_excused_by_its_registry_record(self):
        """Скрипт из #192: вызывающего нет и не будет, замер в реестре есть."""
        self.assertIn("edge_exposure_depth", scripts_without_caller(),
                      "у R&D-замера вызывающего быть не должно — измерение изменилось")
        self.assertIn("edge_exposure_depth", registry_recorded_scripts())
        self.assertNotIn("edge_exposure_depth", unwired_scripts())

    def test_the_carve_out_did_not_swallow_the_watch(self):
        """Правило обязано СУЖАТЬ класс, а не отменять сторожа.

        **ADR-792: эта проверка ИЗМЕНЕНА намеренно, и вот основание** (инв. #16
        требует обоснования в теле изменения и записи в журнал — запись есть в
        `docs/journal/2026-W43.md`, цикл #914).

        До 23.10 здесь стоял порог на ДОЛЮ: `len(raw - watched) < len(raw) / 2`.
        Он краснел на чистой вершине с 02.10 (63 из 127), и четыре карточки
        подряд называли его красным, не трогая. Замер цикла #914 ОДНИМ прибором
        по трём деревьям (`carve_out_audit`, числа выписаны в её докстринге):
        доля вычета 38.6 % → 45.8 % → 51.8 %, а население ПОД сторожем
        54 → 64 → 66 и разрыв с отвергнутым правилом 27 → 35 → 42. То есть
        вычет не «съедал» сторожа ни разу: он рос вместе с R&D-классом, а
        сторож рос вместе с ним.

        Доля и была подменой предмета. Предмет сторожа назван в его же
        докстринге — «значит правило расширили до любого упоминания в `docs/`»;
        доля же двигается от ЛЮБОГО изменения населения, в том числе от удачи
        (подключили сироту ⇒ `raw` упал ⇒ доля вычета выросла). Три исхода были
        схлопнуты в один: правило расширили · класс вырос · сторож цел.

        Теперь спрашивается ровно предмет, тремя утверждениями О ПРАВИЛЕ — ни
        одно из них не сдвигается ни новым R&D-замером, ни подключением старого
        скрипта:

        1. **упоминание в `docs/` само по себе не прощает НИКОГО** — разрыв с
           отвергнутым правилом непуст (`narrowed`);
        2. **летопись не прощает** — скрипт, чьё единственное упоминание в
           `docs/journal/`, остаётся под сторожем (замер 13.08: таких было
           пять, сегодня два);
        3. **у сторожа есть подопечные** — иначе его вердикт ничего не значит.

        Четвёртый исход назван: `measured=False` — это НЕ «правило цело» и НЕ
        «правило расширено», а громкий отказ с причиной (инв. #17).
        """
        complaint = _unwired.carve_out_complaint(_unwired.carve_out_audit())
        self.assertIsNone(complaint, complaint)

    def test_only_the_registry_is_admissible_evidence(self):
        """Ни один файл `docs/` кроме реестра не участвует в решении.

        Проверка структурная: путь-исключение ровно один и он — реестр R&D.
        Расширение до каталога `docs/` обязано быть решением, а не правкой строки.
        """
        self.assertEqual(_unwired._RND_REGISTRY,
                         pathlib.Path("docs") / "DYNAMIC_LEVERAGE_GUARDIAN.md")
        self.assertTrue((_unwired._ROOT / _unwired._RND_REGISTRY).exists(),
                        "реестр R&D исчез — правило судит по несуществующему файлу")

    def test_the_product_registries_are_a_closed_list(self):
        """ADR-342: второй реестр-продукт — карантин агентов; список закрыт.

        Добавить сюда файл, чтобы погасить храповик, — ровно то, что сторож запрещает.
        Каждый реестр обязан существовать: правило, судящее по несуществующему файлу,
        молча перестало бы прощать — или, хуже, начало бы прощать не то.
        """
        self.assertEqual(_unwired._PRODUCT_REGISTRIES, (
            pathlib.Path("docs") / "DYNAMIC_LEVERAGE_GUARDIAN.md",
            pathlib.Path("attic") / "agents" / "QUARANTINE.json"))
        for rel in _unwired._PRODUCT_REGISTRIES:
            self.assertTrue((_unwired._ROOT / rel).exists(), f"реестр-продукт исчез: {rel}")

    def test_the_quarantine_registry_excuses_only_its_own_instrument(self):
        """Замер 11.09: реестр карантина называет ровно один скрипт — сам инструмент."""
        text = (_unwired._ROOT / _unwired._QUARANTINE_REGISTRY).read_text(encoding="utf-8")
        named = {m.stem for m in entrypoint_scripts()
                 if _unwired.wiring_patterns(m.stem)["file"].search(text)
                 or _unwired.wiring_patterns(m.stem)["module"].search(text)}
        self.assertEqual(named, {"agent_quarantine"})
        self.assertIn("agent_quarantine", registry_recorded_scripts())

    def test_entrypoints_are_still_found(self):
        """Общий предохранитель: пустой список входов сделал бы всё выше зелёным."""
        self.assertGreater(len(entrypoint_scripts()), 100)


if __name__ == "__main__":
    unittest.main()
