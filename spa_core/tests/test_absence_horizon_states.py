"""Сторож: «горизонта нет» — это ПЯТЬ состояний, а не одно (ADR-1054).

Каждая проверка воспроизводит НАСТОЯЩУЮ поломку (правило
`.claude/rules/deployment.md`, «проверка сторожа сторожей»):

* **живой замер 18.11, цикл #1193.** Прогон `ci-control` **44287563961** на
  `0f1aa36ba` принёс ЧЕТЫРЕ новых красных имени при НУЛЕ ушедших, и ДВА из них
  (`test_office_absent_artifact_producer_aware.py::Scenes::
  test_live_2026_09_08_producer_arrived_after_the_runner_last_ran` и
  `::test_third_outcome_closes_itself_on_the_next_run`) оказались регрессией
  ADR-1053, а не окружением: дифференциально — база `d33c7b473` **100 passed**,
  вершина `7dbd9704b` **2 failed**. Причина, которую печатал вердикт, —
  «`architecture/manifest.json`: нет `slo_hours`» — в той сцене была НЕВЕРНА:
  реестра там не было ни одного байта. Прежняя редакция двери утверждала в
  своей шапке дословно, что «отличить их друг от друга читателю не нужно —
  следующий шаг у всех трёх один: объявить горизонт». Опровергнуто: у
  состояния «реестра НЕТ» следующий шаг — положить реестр, а не вписать строку
  в файл, которого нет;
* **направление ошибки — опасное.** В бою то же состояние значит «манифест
  пропал», и сторож советовал бы править пропавший файл. Поэтому проверки ниже
  требуют не «какого-нибудь текста», а ИМЕННО измеренного состояния;
* **ничего не ослаблено** — все пять состояний остаются НАХОДКОЙ
  (`is_finding=True`), и обратный контроль на это стои́т отдельной пробой. Если
  различение превратится в глушилку, покраснеет именно она;
* **население двери измерено, а не предположено.** 18.11 батарей, реально
  зовущих дверь отсутствия, оказалось **5** (по грепу имени модуля — 9: четыре
  упоминают его, не вызывая ни разу), и горизонт объявляли 4 из 5. Пятая и
  была красной. Латентно-зелёных, то есть получающих находку по НЕ ТОЙ
  причине, — **НОЛЬ**; мерено поведением (обёртка над `aa.verdict`, перепись
  исходов по каждой батарее), а не чтением глазами.

Время — ВХОД (`.claude/rules/deployment.md`): ни одной стенной отметки, все
отметки сцены производятся от единственного якоря `NOW`.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import artifact_absence as aa

REPO = Path(__file__).resolve().parents[2]

#: Якорь сцены. От него производятся ВСЕ отметки — и mtime, и отчёт бегуна.
#: FROZEN-DATE-OK: injected-clock — якорь уходит параметром `now=` в
#: `aa.verdict`, а обе отметки сцены (mtime производителя через `os.utime`,
#: `run_started_at` отчёта бегуна) вычитаются от него же. Стенных часов не
#: спрашивает ни одна проба этого файла.
NOW = dt.datetime(2026, 11, 18, 12, 0, tzinfo=dt.timezone.utc)

#: Зазор, на котором отсрочка ЗАКОННА при объявленном горизонте: все сцены
#: стоя́т на дороге `ran < born`, и различает их ТОЛЬКО состояние горизонта.
BORN_H = 3.0
RUNNER_SILENT_H = 5.0
DECLARED_H = 192.0


def _stage_pair() -> tuple[str, str, str]:
    """Настоящая пара «ступень → модуль → артефакт» из живого реестра моста."""
    from spa_core.monitoring import findings_bridge as fb
    for stage, spec in fb.CENSUS_PRODUCT.items():
        return stage, spec["module"], spec["artifact"]
    raise AssertionError("реестр ступеней моста пуст — предпосылка НЕ ОБЕСПЕЧЕНА")


class _Scene(unittest.TestCase):
    """Одноразовое дерево на дороге отсрочки: код приехал ПОСЛЕ прогона."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="spa_horizon_states_"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.stage, self.module_rel, self.artifact_rel = _stage_pair()
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        p = self.root / self.module_rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# производитель\n", encoding="utf-8")
        born = (NOW - dt.timedelta(hours=BORN_H)).timestamp()
        os.utime(p, (born, born))
        (self.root / aa.RUNNER_REPORT_REL).write_text(json.dumps(
            {"run_started_at": (
                NOW - dt.timedelta(hours=RUNNER_SILENT_H)).isoformat()}),
            encoding="utf-8")

    def _registry(self, body) -> None:
        path = self.root / aa.MANIFEST_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body if isinstance(body, str) else json.dumps(body),
                        encoding="utf-8")

    def verdict(self, **kw):
        return aa.verdict(self.artifact_rel, root=str(self.root), now=NOW, **kw)

    def horizon(self):
        return aa.declared_horizon(self.artifact_rel, root=str(self.root))


class TheLiveReplayOf1811(_Scene):
    """(A) Сцена БЕЗ реестра — дословно та, что дала два красных имени."""

    def test_an_absent_registry_is_named_as_absent(self):
        hz = self.horizon()
        self.assertEqual(
            hz.state, aa.HORIZON_NO_REGISTRY,
            f"состояние {hz.state!r}: реестра в дереве нет ни одного байта")
        self.assertIsNone(hz.hours)
        self.assertIn("НЕТ", hz.detail)

    def test_the_verdict_no_longer_blames_a_missing_slo_hours_line(self):
        """Корень аварии: причина называла строку в ОТСУТСТВУЮЩЕМ файле."""
        v = self.verdict()
        self.assertEqual(v.kind, aa.UNMEASURED_NO_HORIZON)
        self.assertEqual(v.horizon_state, aa.HORIZON_NO_REGISTRY,
                         "состояние входа обязано доехать ЗНАЧЕНИЕМ, а не "
                         "прозой: на нём стои́т следующий шаг читателя")
        self.assertNotIn(
            "нет `slo_hours`", v.reason,
            "вернулась причина, которая причиной не была: в этой сцене "
            "реестра нет ВОВСЕ, и строку в нём искать негде")
        self.assertIn(aa.MANIFEST_REL, v.reason)

    def test_the_next_step_points_at_the_registry_not_at_a_line(self):
        v = self.verdict()
        self.assertIn("Следующий шаг:", v.reason)
        self.assertIn("положить", v.reason,
                      "читателя снова отправили вписывать строку вместо того, "
                      "чтобы положить реестр")


class EachStateIsNamedByItsOwnValue(_Scene):
    """(B) Пять состояний различимы ЗНАЧЕНИЕМ (инв. #17), а не текстом."""

    def test_registry_unreadable(self):
        self._registry("{это не json")
        self.assertEqual(self.horizon().state, aa.HORIZON_REGISTRY_UNREADABLE)
        self.assertEqual(self.verdict().horizon_state,
                         aa.HORIZON_REGISTRY_UNREADABLE)

    def test_artifact_not_in_the_registry(self):
        self._registry({"artifacts": [{"path": "data/chuzhoi.json",
                                       "slo_hours": DECLARED_H}]})
        self.assertEqual(self.horizon().state,
                         aa.HORIZON_ARTIFACT_NOT_IN_REGISTRY)

    def test_entry_present_without_the_field(self):
        self._registry({"artifacts": [{"path": self.artifact_rel}]})
        hz = self.horizon()
        self.assertEqual(hz.state, aa.HORIZON_NO_SLO_HOURS)
        self.assertIn("`slo_hours`", hz.next_step,
                      "у ЭТОГО состояния следующий шаг как раз «вписать "
                      "строку» — и только у него")

    def test_a_value_that_is_not_a_positive_number(self):
        """Шесть негодных значений, и каждое — своё состояние, не «нет поля»."""
        for bad in (True, "192", 0, -1, None, [192]):
            with self.subTest(bad=bad):
                self._registry({"artifacts": [
                    {"path": self.artifact_rel, "slo_hours": bad}]})
                hz = self.horizon()
                self.assertEqual(hz.state, aa.HORIZON_BAD_VALUE,
                                 f"значение {bad!r} получило состояние "
                                 f"{hz.state!r}")
                self.assertIsNone(hz.hours)

    def test_a_declared_horizon_is_declared(self):
        self._registry({"artifacts": [{"path": self.artifact_rel,
                                       "slo_hours": DECLARED_H}]})
        hz = self.horizon()
        self.assertEqual(hz.state, aa.HORIZON_DECLARED)
        self.assertEqual(hz.hours, DECLARED_H)
        self.assertEqual(hz.next_step, "",
                         "у объявленного горизонта следующего шага нет — "
                         "непустая строка здесь звала бы действовать на "
                         "исправном состоянии")

    def test_the_caller_who_answers_none_is_its_own_state(self):
        """`horizon_of=` ответил `None` — реестр здесь не опрашивался вовсе."""
        self._registry({"artifacts": [{"path": self.artifact_rel,
                                       "slo_hours": DECLARED_H}]})
        v = self.verdict(horizon_of=lambda _rel: None)
        self.assertEqual(v.kind, aa.UNMEASURED_NO_HORIZON)
        self.assertEqual(v.horizon_state, aa.HORIZON_NOT_GIVEN_BY_CALLER,
                         "реестр в сцене ОБЪЯВЛЕН, и свалить ответ на него "
                         "значило бы утверждать о том, чего не спрашивали")
        self.assertIn("ВЫЗЫВАЮЩЕГО", v.reason)

    def test_all_the_values_are_distinct(self):
        """Семь имён — семь РАЗНЫХ строк: склейка вернула бы класс целиком."""
        values = [aa.HORIZON_DECLARED, aa.HORIZON_NO_REGISTRY,
                  aa.HORIZON_REGISTRY_UNREADABLE,
                  aa.HORIZON_ARTIFACT_NOT_IN_REGISTRY,
                  aa.HORIZON_NO_SLO_HOURS, aa.HORIZON_BAD_VALUE,
                  aa.HORIZON_NOT_GIVEN_BY_CALLER]
        self.assertEqual(len(set(values)), len(values))


class TheFixIsNotASilencer(_Scene):
    """(C) Обратный контроль: различение НЕ ослабило ни одного исхода."""

    def test_every_undeclared_state_stays_a_finding(self):
        scenes = {
            aa.HORIZON_NO_REGISTRY: None,
            aa.HORIZON_REGISTRY_UNREADABLE: "{не json",
            aa.HORIZON_ARTIFACT_NOT_IN_REGISTRY: {
                "artifacts": [{"path": "data/chuzhoi.json", "slo_hours": 1}]},
            aa.HORIZON_NO_SLO_HOURS: {
                "artifacts": [{"path": self.artifact_rel}]},
            aa.HORIZON_BAD_VALUE: {
                "artifacts": [{"path": self.artifact_rel, "slo_hours": 0}]},
        }
        for expected, body in scenes.items():
            with self.subTest(state=expected):
                shutil.rmtree(self.root / "architecture", ignore_errors=True)
                if body is not None:
                    self._registry(body)
                v = self.verdict()
                self.assertEqual(v.horizon_state, expected)
                self.assertEqual(v.kind, aa.UNMEASURED_NO_HORIZON)
                self.assertTrue(
                    v.is_finding,
                    f"состояние {expected} перестало быть находкой — "
                    f"различение стало глушилкой")
                self.assertIn(aa.UNMEASURED, v.reason)

    def test_a_declared_horizon_still_defers_and_still_expires(self):
        """Обе законные дороги целы: внутри горизонта и за его пределом."""
        self._registry({"artifacts": [{"path": self.artifact_rel,
                                       "slo_hours": DECLARED_H}]})
        self.assertEqual(self.verdict().kind, aa.NOT_YET)
        self._registry({"artifacts": [
            {"path": self.artifact_rel,
             "slo_hours": RUNNER_SILENT_H / 2.0}]})
        v = self.verdict()
        self.assertEqual(v.kind, aa.DEFERRAL_OUTLIVED_THE_RUNNER)
        self.assertTrue(v.is_finding)


class TheDoorIsOneAndItRunsOnTheLiveRegistry(unittest.TestCase):
    """(D) Не вакуумно: тонкая дверь и боевой реестр отвечают согласованно."""

    def test_the_hours_only_door_has_no_parser_of_its_own(self):
        """`declared_horizon_hours` — проекция, а не вторая копия разбора."""
        _stage, _module, artifact = _stage_pair()
        root = str(REPO)
        self.assertEqual(aa.declared_horizon_hours(artifact, root=root),
                         aa.declared_horizon(artifact, root=root).hours)

    def test_the_live_registry_declares_this_artifact(self):
        _stage, _module, artifact = _stage_pair()
        hz = aa.declared_horizon(artifact, root=str(REPO))
        self.assertEqual(
            hz.state, aa.HORIZON_DECLARED,
            f"у живого артефакта {artifact} состояние {hz.state!r} — дверь "
            f"отвечает «не объявлен» на объявленном")
        self.assertGreater(hz.hours, 0)

    def test_the_disproven_claim_did_not_come_back(self):
        """Снятое утверждение не вернулось — проверка узкая, про ОДНУ фразу.

        Вернись оно — вернётся и совет искать строку в файле, которого нет,
        а код при этом останется исправным: расхождение будет НЕВИДИМЫМ.
        """
        text = io.open(REPO / "spa_core" / "monitoring" / "artifact_absence.py",
                       encoding="utf-8").read()
        claim = "Отличить их друг от друга читателю не"
        head = text.split("def declared_horizon", 1)[0]
        self.assertNotIn(
            claim, head,
            "утверждение «различать состояния читателю не нужно» вернулось в "
            "шапку модуля, а замер 18.11 его опроверг")


if __name__ == "__main__":                                    # pragma: no cover
    unittest.main()
