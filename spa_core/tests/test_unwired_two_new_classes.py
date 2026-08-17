"""Два новых вычитаемых класса храповика: цена каждого ИЗМЕРЕНА и закреплена (#248).

Класс, выведенный из-под храповика без замера, — это не класс, а поблажка: ровно так база
превращается в мусорный список. Прецедент замера — R&D-реестр (#214): «весь `docs/` считать
проводкой» сняло бы с учёта 62 подопечных из 88, и потому засчитан ровно ОДИН документ.

Здесь то же самое сделано для двух классов, открывшихся при разборе семи сирот:

1. **команда обязательного протокола цикла** (`protocol_commanded_scripts`) — цена **2 из 61**;
2. **генератор, чей продукт импортирует живой код** (`generated_artifact_scripts`) — **1 из 61**.

У каждого теста ниже есть отрицательное плечо: правило обязано НЕ засчитывать соседнюю,
внешне похожую форму (упоминание вместо команды; одностороннюю ссылку вместо встречной).
Без такого плеча правило нельзя отличить от «считать всё подряд».
"""
from __future__ import annotations

import unittest
from pathlib import Path

from spa_core.tests._unwired import (entrypoint_scripts, generated_artifact_scripts,
                                     protocol_commanded_scripts, protocol_executor,
                                     scripts_without_caller, unwired_scripts)

_ROOT = Path(__file__).resolve().parents[2]
_PROTOCOL = _ROOT / "docs" / "ORCHESTRATOR_PROTOCOL.md"


class TestProtocolCommandClass(unittest.TestCase):
    """«Команду протокола исполняет агент» — это цепочка, а не доверие документу."""

    def test_the_protocol_has_a_WIRED_executor(self):
        """Ключевое условие: без исполнителя класс не вычитается ВОВСЕ (fail-CLOSED).

        Цепочка на 15.08: `launchd/com.spa.orchestrator.plist` → `scripts/agent_orchestrator.sh`
        → строка запроса «Исполни ПОЛНОСТЬЮ docs/ORCHESTRATOR_PROTOCOL.md за один цикл».
        Исполнитель называет протокол В КОДЕ, а не в комментарии, и сам запускается launchd.
        """
        ex = protocol_executor()
        self.assertIsNotNone(ex, "исполнителя протокола нет — класс обязан отключиться")
        self.assertEqual(ex.name, "agent_orchestrator.sh")
        plist = (_ROOT / "launchd" / "com.spa.orchestrator.plist").read_text(encoding="utf-8")
        self.assertIn("agent_orchestrator.sh", plist,
                      "исполнитель протокола сам должен быть подключён launchd")

    def test_the_price_of_the_rule_is_three_of_the_watched_set(self):
        """Цена правила на живом дереве: ровно 3 имени (замер 17.08; было 2 — замер 15.08).

        Шесть остальных «командных» скриптов протокола (`check_undelivered_work`,
        `orchestrator_queue`, …) и без правила подключены обычным вызовом — их правило не
        спасает, и в цену они не входят. Считаем только тех, у кого вызывающего НЕТ.

        **Почему цена выросла на единицу (17.08, карточка
        `inbox-dva-predpisannyh-progona-ryadom-drug-druga-morya`).** В §3.4 протокола добавлена
        команда `python3 scripts/measure_acceptance_contention.py` — замер того, морят ли два
        предписанных прогона друг друга. Замер по устройству запускается руками на КОНКРЕТНОЙ
        машине (ответ от машины зависит: Mac Mini 14.08 — `starves`, Linux-контейнер 17.08 —
        `scales`), поэтому постоянного вызывающего у него нет и быть не может — ровно тот же
        случай, что `adr_number` и `reap_stale_worktrees`.

        Число здесь ПЕРЕСЧИТАНО, а не подогнано: правило не менялось ни на букву, изменился
        живой вход. Обратная сторона — соседний `test_a_mere_MENTION_in_the_protocol_is_not_a_command`:
        имя, названное в протоколе прозой, в этот список по-прежнему не попадает.
        """
        raw = set(scripts_without_caller())
        freed = sorted(protocol_commanded_scripts() & raw)
        self.assertEqual(
            freed,
            ["adr_number", "measure_acceptance_contention", "reap_stale_worktrees"],
            "цена правила изменилась — пересчитай и запиши новый замер, "
            "а не подгоняй правило под удобный ответ")

    def test_a_mere_MENTION_in_the_protocol_is_not_a_command(self):
        """Отрицательное плечо: `smoke` назван в протоколе прозой и остаётся сиротой.

        Именно эту подмену («имя в документе = проводка») цикл #228 снимал три раза подряд;
        вернуть её здесь означало бы обнулить ту работу.
        """
        text = _PROTOCOL.read_text(encoding="utf-8")
        self.assertIn("smoke", text, "фикстура устарела: в протоколе больше нет прозаического имени")
        self.assertNotIn("smoke", protocol_commanded_scripts())
        self.assertIn("smoke", set(unwired_scripts()),
                      "упоминание прозой начало считаться вызовом")

    def test_the_commanded_scripts_really_exist(self):
        known = {p.stem for p in entrypoint_scripts()}
        self.assertTrue(protocol_commanded_scripts() <= known)


class TestGeneratedArtifactClass(unittest.TestCase):
    """«Продукт скрипта исполняется, даже когда его вход мёртв» — обе стороны обязательны."""

    def test_the_measured_case_is_the_tier_b_markup(self):
        self.assertIn("audit_tier_c_wiring_feasibility", generated_artifact_scripts())

    def test_the_price_of_the_rule_is_one_of_the_watched_set(self):
        """Одностороннее «скрипт назвал модуль» дало бы 6 из 61, встречное требование — 1.

        Пять лишних — не генераторы: `verify_infrastructure`, `preflight_day1`,
        `checkpoint_deliver`, `lint_kanban_usage`, `analytics_conformance` просто УПОМИНАЮТ
        чужой живой модуль. Их артефакты о них не знают, поэтому встречная сторона их срезает.
        """
        watched = set(unwired_scripts())
        false_positives = {"verify_infrastructure", "preflight_day1", "checkpoint_deliver",
                           "lint_kanban_usage", "analytics_conformance"}
        self.assertEqual(false_positives & generated_artifact_scripts(), set(),
                         "правило снова засчитывает одностороннее упоминание")
        self.assertTrue(false_positives <= watched,
                        "фикстура устарела: эти скрипты больше не под храповиком")

    #: Все продукты генератора `audit_tier_c_wiring_feasibility`. Список ЯВНЫЙ:
    #: появится третий артефакт — мутация ниже перестанет быть полной, и тест
    #: обязан покраснеть на этом факте, а не молча ослабнуть.
    _MARKUP_ARTIFACTS = ("_protocol_key_coverage.py", "_tier_c_key_coverage.py")

    def test_the_generator_has_exactly_the_artifacts_we_think_it_has(self):
        """Положительный контроль к фикстуре мутации: продуктов ровно два.

        Пока продукт был один, «убрать встречную ссылку» и «убрать её у
        артефакта X» совпадали. С двумя продуктами это разные действия, и
        неполная мутация тихо доказывала бы не то, что заявлено.
        """
        tool = (_ROOT / "scripts" / "audit_tier_c_wiring_feasibility.py").read_text(
            encoding="utf-8")
        analytics = _ROOT / "spa_core" / "analytics"
        found = sorted(p.name for p in analytics.glob("_*key_coverage.py")
                       if "audit_tier_c_wiring_feasibility" in
                       p.read_text(encoding="utf-8"))
        self.assertEqual(found, sorted(self._MARKUP_ARTIFACTS),
                         "набор продуктов генератора изменился — обнови мутацию, "
                         "а не ослабляй правило")
        for name in self._MARKUP_ARTIFACTS:
            self.assertIn(name, tool, "генератор не называет свой продукт в коде")

    def test_both_sides_are_required(self):
        """Мутация: убери встречное упоминание — и генератор возвращается в сироты.

        Проверяется на КОПИИ дерева, живой файл не трогается.

        **НАМЕРЕННОЕ изменение фикстуры (инв. #16, цикл #143, запись в журнале
        `docs/journal/2026-W34.md`).** Мутация чистила встречную ссылку у ОДНОГО
        артефакта (`_protocol_key_coverage.py`) — этого хватало ровно до тех пор,
        пока продукт у генератора был один. С появлением второго
        (`_tier_c_key_coverage.py`, разметка Tier-C) неполная мутация оставляла
        вторую встречную ссылку живой, и тест краснел на СВОЕЙ неполноте, а не
        на правиле. Правило не тронуто ни на букву; мутация доведена до полной,
        а её полнота закреплена соседним тестом
        `test_the_generator_has_exactly_the_artifacts_we_think_it_has`.
        """
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            dst = Path(td) / "tree"
            for d in ("scripts", "spa_core", "launchd", ".github", "docs"):
                src = _ROOT / d
                if src.exists():
                    shutil.copytree(src, dst / d, symlinks=True,
                                    ignore=shutil.ignore_patterns("__pycache__"))
            self.assertIn("audit_tier_c_wiring_feasibility", generated_artifact_scripts(dst))

            for name in self._MARKUP_ARTIFACTS:
                art = dst / "spa_core" / "analytics" / name
                art.write_text(art.read_text(encoding="utf-8")
                               .replace("audit_tier_c_wiring_feasibility", "какой-то-скрипт"),
                               encoding="utf-8")
            self.assertNotIn("audit_tier_c_wiring_feasibility", generated_artifact_scripts(dst),
                             "правилу хватило ОДНОЙ стороны — значит это снова просто упоминание")

    def test_removing_only_one_back_reference_is_NOT_enough_anymore(self):
        """Обратное плечо той же правки: неполная мутация обязана НЕ орфанить.

        Это и есть доказательство, что мутация была расширена по делу, а не
        «чтобы стало зелено»: одна оставшаяся встречная ссылка держит генератор
        подключённым — ровно так правило и устроено.
        """
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            dst = Path(td) / "tree"
            for d in ("scripts", "spa_core", "launchd", ".github", "docs"):
                src = _ROOT / d
                if src.exists():
                    shutil.copytree(src, dst / d, symlinks=True,
                                    ignore=shutil.ignore_patterns("__pycache__"))
            art = dst / "spa_core" / "analytics" / "_protocol_key_coverage.py"
            art.write_text(art.read_text(encoding="utf-8")
                           .replace("audit_tier_c_wiring_feasibility", "какой-то-скрипт"),
                           encoding="utf-8")
            self.assertIn("audit_tier_c_wiring_feasibility", generated_artifact_scripts(dst),
                          "второй продукт перестал держать встречную сторону")

    def test_the_artifact_must_be_imported_by_LIVE_code(self):
        """Третье условие: продукт, который никто не импортирует, ничего не доказывает."""
        src = (_ROOT / "spa_core" / "analytics" / "signal_aggregator.py").read_text(encoding="utf-8")
        self.assertIn("from spa_core.analytics._protocol_key_coverage import", src)


if __name__ == "__main__":
    unittest.main()
