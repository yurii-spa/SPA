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

**23.10 (решение ARB): названность в реестре больше не освобождает — освобождает
ПОДТВЕРЖДЕНИЕ каждого скрипта** (`_unwired.research_tool_verdict`). Прежняя форма
допускала два неверных результата: (а) рабочий скрипт, упомянутый в реестре R&D
мимоходом или пишущий состояние в `data/`, снимался с учёта наравне с замером — так
числились «ручным R&D» `edge_compound_drawdown_memory` и `edge_exogenous_leading_switch`,
оба пишут в `data/`; (б) порог «вычет < половины» на ТЕКУЩЕМ дереве краснел от каждого
законного замера (доля росла с реестром, 69 из 134 на 23.10), то есть отвечал на вопрос
«сколько R&D-идей проверено», а не «расширили ли правило». Порог сохранён там, где он
различает два правила, — на восстановленной когорте 13.08
(`unwired_cohort_f6b87f139.json`), а текущий вычет подтверждается поимённо. Обоснование
и замер — `docs/journal/2026-W43.md`.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from spa_core.tests import _unwired
from spa_core.tests._unwired import (
    entrypoint_scripts,
    registry_named_scripts,
    registry_recorded_scripts,
    research_tool_verdict,
    scripts_without_caller,
    unwired_scripts,
)

_COHORT = pathlib.Path(__file__).resolve().parent / "unwired_cohort_f6b87f139.json"


def _fake_repo(tmp: pathlib.Path) -> pathlib.Path:
    """Крошечный репозиторий со всеми четырьмя случаями сразу."""
    (tmp / "scripts").mkdir(parents=True)
    (tmp / "launchd").mkdir()
    (tmp / "docs" / "journal").mkdir(parents=True)

    body = 'if __name__ == "__main__":\n    pass\n'
    # у R&D-замера назначение объявлено докстрингом — так устроены все 67 настоящих
    research = '"""Замер идеи #99: advisory backtest, [bt] L0."""\n' + body
    for name in ("alone.py", "wired.py", "journal_only.py"):
        (tmp / "scripts" / name).write_text(research, encoding="utf-8")
    (tmp / "scripts" / "measured.py").write_text(research, encoding="utf-8")

    # НАСТОЯЩАЯ проводка: обёртка зовёт wired.py
    (tmp / "scripts" / "run_it.sh").write_text(
        '#!/bin/bash\npython3 scripts/wired.py --once\n', encoding="utf-8")
    # летопись называет journal_only.py поимённо — и это НЕ проводка
    (tmp / "docs" / "journal" / "2026-W33.md").write_text(
        "цикл #999 доставил scripts/journal_only.py, 4 теста\n", encoding="utf-8")
    # реестр R&D: продукт measured.py — запись в нём
    # Запись несёт РЕЗУЛЬТАТ (вердикт): до 23.10 хватало строки с именем, и такая
    # фикстура не отличала замер от анонса — см. test_a_record_without_a_result_*.
    (tmp / "docs" / "DYNAMIC_LEVERAGE_GUARDIAN.md").write_text(
        "### Идея #99 — проверено scripts/measured.py\n\n"
        "**Вердикт #99.** Calmar 0.81 против 0.79 — улучшение в пределах шума.\n",
        encoding="utf-8")
    return tmp


def _add_script(root: pathlib.Path, name: str, source: str) -> None:
    (root / "scripts" / f"{name}.py").write_text(
        source + '\nif __name__ == "__main__":\n    pass\n', encoding="utf-8")


def _add_record(root: pathlib.Path, text: str) -> None:
    reg = root / "docs" / "DYNAMIC_LEVERAGE_GUARDIAN.md"
    reg.write_text(reg.read_text(encoding="utf-8") + "\n---\n\n" + text + "\n",
                   encoding="utf-8")


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
        """Синтетика: пустой реестр карантина не прощает никого.

        23.10: запись карантина засчитывается с РЕЗУЛЬТАТОМ — замером потребления
        (`measurement.measured`), как у настоящего реестра; до этого хватало одной
        команды возврата, и запись без замера прощала так же, как с ним.
        """
        (self.root / "attic" / "agents").mkdir(parents=True)
        reg = self.root / "attic" / "agents" / "QUARANTINE.json"
        reg.write_text(json.dumps({"quarantined": {"x": {
            "restore": "python3 scripts/alone.py restore x",
            "measurement": {"measured": True, "consumers": 0}}}}), encoding="utf-8")
        self.assertIn("alone", registry_recorded_scripts(self.root))
        reg.write_text(json.dumps({"quarantined": {"x": {
            "restore": "python3 scripts/alone.py restore x"}}}), encoding="utf-8")
        self.assertNotIn("alone", registry_recorded_scripts(self.root),
                         "запись карантина без замера снова освобождает")
        reg.write_text('{"quarantined": {}}', encoding="utf-8")
        self.assertNotIn("alone", registry_recorded_scripts(self.root))


class TestEachExcusedScriptIsConfirmed(unittest.TestCase):
    """Отрицательные контроли решения ARB 23.10: каждый остаётся под надзором.

    Все — на синтетическом дереве и через настоящую точку входа `unwired_scripts`,
    а не через деталь: мутировать надо проводку правила (урок #144).
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = _fake_repo(pathlib.Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def _watched(self, name: str) -> None:
        self.assertIn(name, scripts_without_caller(self.root),
                      "предпосылка: у скрипта не должно быть вызывающего")
        self.assertIn(name, unwired_scripts(self.root),
                      f"{name} снят с учёта: {research_tool_verdict(name, self.root)}")

    def test_the_positive_control_is_excused(self):
        """Обратная сторона: подтверждённый замер вычитается — иначе правило немо."""
        v = research_tool_verdict("measured", self.root)
        self.assertTrue(v["confirmed"], v)
        self.assertNotIn("measured", unwired_scripts(self.root))

    def test_a_foreign_working_script_named_in_the_rnd_registry_stays_watched(self):
        """Рабочий скрипт, упомянутый в записи R&D с вердиктом, — не замер."""
        _add_script(self.root, "nightly_sync",
                    '"""Ночная синхронизация ленты в общий снимок."""\nimport json\n')
        _add_record(self.root, "### Идея #100 — опиралась на scripts/nightly_sync.py\n\n"
                               "**Вердикт #100.** Отрицательный.")
        self._watched("nightly_sync")
        self.assertIn("nightly_sync", registry_named_scripts(self.root),
                      "предпосылка: прежнее правило его бы освободило")

    def test_a_mention_only_in_the_journal_stays_watched(self):
        """Полный путь + результат, но в летописи, а не в реестре."""
        (self.root / "docs" / "journal" / "2026-W43.md").write_text(
            "### цикл #1000 — scripts/journal_only.py\n\n**Вердикт.** Подтверждено.\n",
            encoding="utf-8")
        self._watched("journal_only")
        self.assertFalse(research_tool_verdict("journal_only", self.root)["confirmed"])

    def test_a_record_without_a_result_stays_watched(self):
        """Путь в реестре есть, вердикта в записи нет — это анонс, а не продукт замера."""
        _add_script(self.root, "announced", '"""Замер идеи #101, advisory backtest."""\n')
        _add_record(self.root, "### Идея #101 — скрипт scripts/announced.py\n\n"
                               "Гипотеза: стоп по возрасту просадки. Прогон запланирован.")
        self._watched("announced")
        self.assertIn("запись реестра без результата",
                      research_tool_verdict("announced", self.root)["reasons"])

    def test_a_bare_name_without_the_full_path_stays_watched(self):
        """`bare.py` без `scripts/` — упоминание имени, не запись о скрипте."""
        _add_script(self.root, "bare", '"""Замер идеи #102, advisory backtest."""\n')
        _add_record(self.root, "### Идея #102 — bare.py\n\n**Вердикт #102.** Нейтрально.")
        self._watched("bare")

    def test_any_docs_file_other_than_the_registries_stays_inadmissible(self):
        """Подмена правила на «любое упоминание в docs/»: та же запись вне реестра не освобождает."""
        _add_script(self.root, "elsewhere", '"""Замер идеи #103, advisory backtest."""\n')
        (self.root / "docs" / "OTHER_RND_NOTES.md").write_text(
            "### Идея #103 — scripts/elsewhere.py\n\n**Вердикт #103.** Подтверждено.\n",
            encoding="utf-8")
        self._watched("elsewhere")

    def test_a_production_component_writing_data_stays_watched(self):
        """Пишет в `data/` — производственный компонент, сколько бы вердиктов о нём ни было."""
        _add_script(self.root, "state_writer",
                    '"""Замер идеи #104, advisory backtest."""\n'
                    'import json, pathlib\n'
                    'OUT = pathlib.Path(__file__).parent.parent / "data" / "x.json"\n'
                    'def main():\n    OUT.write_text(json.dumps({}))\n')
        _add_script(self.root, "default_writer",
                    '"""Замер идеи #105, advisory backtest."""\n'
                    'import argparse, json\n'
                    'def main():\n'
                    '    ap = argparse.ArgumentParser()\n'
                    '    ap.add_argument("--json", default="data/edge_y.json")\n'
                    '    a = ap.parse_args()\n'
                    '    with open(a.json, "w") as fh:\n        json.dump({}, fh)\n')
        for name, n in (("state_writer", 104), ("default_writer", 105)):
            _add_record(self.root, f"### Идея #{n} — scripts/{name}.py\n\n**Вердикт #{n}.** Да.")
        for name in ("state_writer", "default_writer"):
            with self.subTest(name=name):
                self._watched(name)

    def test_reading_data_and_writing_elsewhere_is_still_research(self):
        """Обратная сторона: ЧИТАТЬ `data/` и писать в `--json` без умолчания — замер."""
        _add_script(self.root, "reader",
                    '"""Замер идеи #106, advisory backtest."""\n'
                    'import argparse, json, pathlib\n'
                    'PANEL = pathlib.Path("data") / "aggressive_lab"\n'
                    'def main():\n'
                    '    ap = argparse.ArgumentParser()\n'
                    '    ap.add_argument("--json", type=pathlib.Path, default=None)\n'
                    '    a = ap.parse_args()\n'
                    '    rows = (PANEL / "x.json").read_text()\n'
                    '    if a.json:\n        a.json.write_text(rows)\n')
        _add_record(self.root, "### Идея #106 — scripts/reader.py\n\n**Вердикт #106.** Нет.")
        self.assertNotIn("reader", unwired_scripts(self.root),
                         research_tool_verdict("reader", self.root))

    def test_a_production_component_importing_the_money_path_stays_watched(self):
        """Импорт денежного пути — производственный компонент, не ручной замер."""
        _add_script(self.root, "money_touch",
                    '"""Замер идеи #107, advisory backtest."""\n'
                    'from spa_core.risk.policy import RiskPolicy\n')
        _add_record(self.root, "### Идея #107 — scripts/money_touch.py\n\n**Вердикт #107.** Да.")
        self._watched("money_touch")

    def test_a_script_without_a_declared_research_purpose_stays_watched(self):
        """Нет докстринга, объявляющего замер, — назначение не подтверждено."""
        _add_script(self.root, "silent", "import json\n")
        _add_record(self.root, "### Идея #108 — scripts/silent.py\n\n**Вердикт #108.** Да.")
        self._watched("silent")


class TestTheRuleOnTheRealRepo(unittest.TestCase):
    """То же самое, но на настоящем дереве — синтетика не заменяет факта."""

    def test_edge_exposure_depth_is_excused_by_its_registry_record(self):
        """Скрипт из #192: вызывающего нет и не будет, замер в реестре есть."""
        self.assertIn("edge_exposure_depth", scripts_without_caller(),
                      "у R&D-замера вызывающего быть не должно — измерение изменилось")
        self.assertIn("edge_exposure_depth", registry_recorded_scripts())
        self.assertNotIn("edge_exposure_depth", unwired_scripts())

    def test_the_carve_out_did_not_swallow_the_watch(self):
        """Правило обязано СУЖАТЬ класс, а не отменять сторожа — поимённо.

        23.10: прежняя форма («вычет < половины ТЕКУЩЕГО сырого замера») краснела от
        каждого законного R&D-замера и при этом пропускала рабочий скрипт, если долю
        не перевешивало. Теперь каждый вычтенный скрипт обязан быть подтверждён, и
        полный путь проверяется здесь НЕЗАВИСИМО от разбора записи — чтением файла
        реестра закрытого списка. Половинный порог живёт на когорте 13.08 (ниже).
        """
        raw, watched = set(scripts_without_caller()), set(unwired_scripts())
        self.assertTrue(watched, "храповик остался без единого подопечного")
        texts = [(_unwired._ROOT / rel).read_text(encoding="utf-8")
                 for rel in _unwired._PRODUCT_REGISTRIES]
        excused = sorted(raw - watched)
        self.assertTrue(excused, "вычет пуст — проверка ниже ничего не значит")
        for name in excused:
            with self.subTest(name=name):
                self.assertTrue(any(f"scripts/{name}.py" in t for t in texts),
                                f"{name}: полного пути нет ни в одном реестре закрытого списка")
                v = research_tool_verdict(name)
                self.assertTrue(v["confirmed"], f"{name}: вычтен без подтверждения: {v}")
                self.assertTrue(any(r["result"] for r in v["records"]), v)
        unconfirmed = (registry_named_scripts() & raw) - registry_recorded_scripts()
        self.assertTrue(unconfirmed <= watched,
                        f"неподтверждённые ушли из-под надзора: {sorted(unconfirmed - watched)}")

    def test_the_former_data_writers_no_longer_write_data_by_default(self):
        """Замер 23.10: два «R&D» по старому правилу писали в `data/` (файлы без читателя) — правило
        подтверждения их НЕ подтверждало. Исправлен ДЕФЕКТ, а не база: оба пишут результат только в
        явно заданный --json. Теперь подтверждаются по всем признакам; класс «пишет в data/ ⇒ под
        надзором» держат синтетические контроли TestEachExcusedScriptIsConfirmed."""
        watched = set(unwired_scripts())
        for name in ("edge_compound_drawdown_memory", "edge_exogenous_leading_switch"):
            with self.subTest(name=name):
                v = research_tool_verdict(name)
                self.assertFalse(any(r.startswith("пишет в data/") for r in v["reasons"]), v)
                self.assertTrue(v["confirmed"], v)
                self.assertNotIn(name, watched)

    def test_the_historical_cohort_keeps_the_half_rule(self):
        """Порог «вычет < половины» — на когорте, где он ИЗМЕРЕН (13.08, f6b87f139).

        Когорта восстановлена прибором того же коммита на его дереве (`git archive`),
        числа сходятся с журналом W33: 88 без вызывающего, 34 по реестру, 62 по
        «любому docs/», у пяти — только журнал. На ней порог различает два правила:
        узкое укладывается, «любой docs/» — нет. Подмена правила на «любое упоминание»
        здесь и видна.
        """
        c = json.loads(_COHORT.read_text(encoding="utf-8"))
        self.assertEqual(c["commit"], "f6b87f1399501fd60a06426a1f9adf3076c68f8b")
        raw = set(c["raw_without_caller"])
        narrow = set(c["excused_by_registry_rule"])
        wide = set(c["excused_by_any_docs_rule"])
        journal = set(c["journal_only"])
        self.assertEqual((len(raw), len(narrow), len(wide), len(journal)), (88, 34, 62, 5))
        self.assertTrue(narrow <= wide <= raw, "когорта внутренне противоречива")
        self.assertTrue(journal <= wide - narrow,
                        "журнал не может быть доказательством узкого правила")
        self.assertLess(len(narrow), len(raw) / 2, "узкое правило 13.08 забрало половину")
        self.assertGreaterEqual(len(wide), len(raw) / 2,
                                "порог больше не отличает «любой docs/» от реестра")
        self.assertEqual(c["baseline_at_commit"]["before"] - c["baseline_at_commit"]["after"],
                         len(narrow) - 1, "33 из базы + edge_exposure_depth вне базы")
        self.assertIn("edge_exposure_depth", narrow)

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
