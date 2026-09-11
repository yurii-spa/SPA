"""Ступень переписей: `run(root=…)` значит КОРЕНЬ ДЕРЕВА у ВСЕХ, а не у части.

Замер цикла #564. `findings_bridge` зовёт каждую перепись ступени одинаково —
`run(root=args.root)`, где `args.root` это корень дерева, — и каждая обязана
вывести каталог данных как `root / "data"`. Две из двенадцати этого не делали:
они принимали `root` как САМ каталог данных, поэтому читали пустоту и клали
свой артефакт **в корень репозитория**.

Знаки у двух носителей РАЗНЫЕ, и разница решает, почему проверка нужна:

* `rate_observation_census` — **громко**: документ приходил без ключа `pairs`,
  печать ступени падала `KeyError: 'pairs'`, ступень писала `skipped` с
  причиной, шаг 0-офис печатал «❌ НЕ ПРОЧИТАН … причина пропуска записана»;
* `journal_population_backfill` — **тихо**: исключения не было ни одного,
  ступень докладывала успех, артефакт молча уезжал в корень дерева, а шаг
  0-офис печатал «бегун ступень звал и о пропуске НЕ сообщил — файла всё
  равно нет». Улика была физической: файл лежал в корне рабочего дерева.

Fail-OPEN тише красного, поэтому опаснее. Проверка ниже меряет **поведение при
том зове, каким зовёт потребитель**, а не форму кода: «в теле есть слово
`data`» — признак структурный, и он на обоих носителях был ИСТИНЕН.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_BRIDGE = Path(__file__).resolve().parents[2] / "spa_core" / "monitoring" / "findings_bridge.py"

#: Зов ступени дословно: `from … import X` и следом `… = X.run(root=args.root)`.
#: Население берётся ИЗ ПОТРЕБИТЕЛЯ, а не из списка в голове автора: перепись,
#: добавленная завтра, попадает под проверку сама.
_CALL = re.compile(
    r"from spa_core\.monitoring import (\w+)\n\s+_\w+ = \1\.run\(root=args\.root\)")


def stage_censuses() -> list[str]:
    return sorted(set(_CALL.findall(_BRIDGE.read_text(encoding="utf-8"))))


class CensusStageRootContract(unittest.TestCase):

    def test_the_population_is_not_empty(self) -> None:
        """Ноль переписей = проверка ни о чём. Молчаливого «чисто» здесь нет."""
        names = stage_censuses()
        self.assertGreaterEqual(len(names), 10, (
            f"из {_BRIDGE.name} вычитано переписей: {len(names)} — форма зова "
            "изменилась, и проверка отвечает не на тот вопрос"))

    def test_every_stage_census_puts_its_artifact_under_root_data(self) -> None:
        """Артефакт обязан лечь в `<корень>/data`, а не в корень дерева."""
        misplaced: dict[str, list[str]] = {}
        unmeasured: dict[str, str] = {}
        measured = 0
        for name in stage_censuses():
            module = importlib.import_module(f"spa_core.monitoring.{name}")
            with TemporaryDirectory() as tmp:
                tree = Path(tmp)
                (tree / "data").mkdir()
                before = {p.name for p in tree.iterdir()}
                try:
                    module.run(root=str(tree))
                except Exception as exc:  # noqa: BLE001
                    unmeasured[name] = f"{type(exc).__name__}: {exc}"
                    continue
                strays = sorted(p.name for p in tree.iterdir()
                                if p.name not in before)
                measured += 1
                if strays:
                    misplaced[name] = strays
        self.assertEqual(misplaced, {}, (
            f"перепись положила артефакт в КОРЕНЬ дерева: {misplaced}. Шаг "
            "0-офис ищет его в `data/` и напечатает «❌ НЕ ПРОЧИТАН», а ступень "
            "при этом доложит успех — fail-OPEN. `run(root=…)` обязан выводить "
            "каталог как `root / \"data\"`; явный каталог передаётся `data_dir=`."))
        self.assertEqual(unmeasured, {}, (
            f"перепись не пережила зов потребителя на пустом дереве: "
            f"{unmeasured}. Это НЕ «чисто»: ступень запишет `skipped`, "
            "артефакта не будет, и шаг 0-офис скажет «НЕ ПРОЧИТАН»."))
        self.assertGreater(measured, 0, "не измерено ни одной переписи")

    def test_the_check_would_redden_on_the_defect_it_was_written_for(self) -> None:
        """Положительный контроль: воспроизводит дефект #564 дословно.

        Перепись, принимающая `root` как САМ каталог данных, обязана быть
        поймана. Проверка, никогда не видевшая настоящей поломки, — украшение,
        а эта поломка жила в двух модулях разом.
        """
        with TemporaryDirectory() as tmp:
            tree = Path(tmp)
            (tree / "data").mkdir()
            before = {p.name for p in tree.iterdir()}

            def broken_run(root: str) -> None:
                (Path(root) / "artifact.json").write_text("{}", encoding="utf-8")

            broken_run(str(tree))
            strays = sorted(p.name for p in tree.iterdir() if p.name not in before)
            self.assertEqual(strays, ["artifact.json"],
                             "мера не видит артефакта, легшего в корень — тогда "
                             "она не поймала бы и настоящий дефект")

    def test_an_explicit_data_dir_is_still_honoured(self) -> None:
        """Обратный контроль у обоих починенных: `--data-dir` не сломан."""
        for name in ("rate_observation_census", "journal_population_backfill"):
            with self.subTest(census=name), TemporaryDirectory() as tmp:
                module = importlib.import_module(f"spa_core.monitoring.{name}")
                elsewhere = Path(tmp) / "elsewhere"
                elsewhere.mkdir()
                module.run(data_dir=str(elsewhere))
                self.assertTrue(
                    (elsewhere / module.OUTPUT_FILENAME).exists(),
                    f"{name}: явный каталог данных перестал работать")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
