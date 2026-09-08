"""Перепись вердикт-данных + третий исход у ПОТРЕБИТЕЛЯ (ADR-266, заказ #528).

Две половины, и вторая — та, ради которой заказ и написан.

ПОЛОВИНА I — прибор. `_severity_verdict_census` перечисляет присвоения
`severity` у сторожа архитектуры и меряет у каждого достижимость третьего
исхода. Контроли переворачивают вердикт ПОИМЁННО, и один из них —
воспроизведение настоящей аварии цикла #525.

ПОЛОВИНА II — вывод, к которому прибор привёл. Единственный `tick_blind`-сайт
(`B3:no_consumption`) чинить в СТОРОЖЕ оказалось нечем: третий исход у него
есть, он живёт в гистерезисе моста (`REQUIRED_SIGHTINGS`). Дефект — в том, ЧЕМ
этот гистерезис считает: наблюдением был ПРОГОН МОСТА, а не ЗАМЕР, и один замер
засчитывался столько раз, сколько мост успевал прочитать файл отчёта.

Часы инъектируются (`now=`), номера процессов не участвуют.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import findings_bridge as fb
from spa_core.tests import _severity_verdict_census as cen

# FROZEN-DATE-OK: injected-clock — якорь, от него производны ОБЕ отметки сцены,
# и обе уходят параметрами (`now=` моста, `generated_at` отчёта-источника).
NOW = dt.datetime(2030, 3, 4, 9, 0, tzinfo=dt.timezone.utc)

SUBJECT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "monitoring", "architecture_conformance.py")


# ── ПОЛОВИНА I — прибор ──────────────────────────────────────────────────────

class CensusPopulation(unittest.TestCase):
    """Население мерится ФОРМОЙ вызова фабрики, а не текстом строк."""

    def test_subject_parses_and_population_is_not_empty(self):
        rows = cen.census(SUBJECT)
        self.assertGreater(len(rows), 10, "перепись пуста — прибор смотрит не туда")
        self.assertTrue(all(r.severity in ("WARN", "CRITICAL") for r in rows),
                        [r for r in rows if r.severity not in ("WARN", "CRITICAL")])

    def test_every_site_is_resolved(self):
        """Третий исход самой переписи: неразобранного быть не должно.

        `UNRESOLVED` тут — не «промолчим», а громкое падение: «не измерено»,
        выданное за «в порядке», — ровно тот дефект, ради которого прибор написан.
        """
        unresolved = [r for r in cen.census(SUBJECT) if r.outcome == cen.UNRESOLVED]
        self.assertEqual(unresolved, [], f"неразобранные сайты: {unresolved}")

    def test_unparsable_file_is_loud_not_silent(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "broken.py")
            open(bad, "w").write("def f(:\n")
            rows = cen.census(bad)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].outcome, cen.UNRESOLVED)
        self.assertIn("не разобран", rows[0].why)

    def test_non_literal_severity_is_unresolved_not_assumed(self):
        """severity из переменной — класс находки не назвать, значит НЕ измерено."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "m.py")
            open(p, "w").write(
                "def go(sev, data, ts_of):\n"
                "    out = []\n"
                "    if ts_of('a') is None:\n"
                "        out.append(_finding('X:y:1', 'B9', sev, 'strong', 'm'))\n"
                "    return out\n")
            rows = cen.census(p)
        self.assertEqual([r.outcome for r in rows], [cen.UNRESOLVED])


class CensusControls(unittest.TestCase):
    """Контроли: вердикт обязан переворачиваться, и только у своего сайта."""

    def _outcomes(self, src_text):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "subject.py")
            open(p, "w", encoding="utf-8").write(src_text)
            return {r.key: r.outcome for r in cen.census(p)}

    def setUp(self):
        self.src = open(SUBJECT, encoding="utf-8").read()
        self.base = {r.key: r.outcome for r in cen.census(SUBJECT)}

    def test_baseline_has_exactly_one_tick_blind(self):
        """Замер, на котором стоит ADR-266. Меняется состав — падает здесь."""
        blind = sorted(k for k, v in self.base.items() if v == cen.TICK_BLIND)
        self.assertEqual(blind, ["B3:no_consumption"], self.base)

    def test_removing_the_525_fix_flips_b2_missing_to_blind(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на настоящей аварии (цикл #525).

        Снимаем ранний выход `if absence.not_yet: … continue` — тот самый третий
        исход, который #525 добавил. Прибор ОБЯЗАН это заметить, иначе он не
        меряет ничего.
        """
        broken = self.src.replace("            if absence.not_yet:",
                                  "            if False:", 1)
        self.assertNotEqual(broken, self.src, "контроль не применился")
        got = self._outcomes(broken)
        self.assertEqual(got["B2:missing"], cen.TICK_BLIND)
        changed = {k for k in got if got[k] != self.base.get(k)}
        self.assertEqual(changed, {"B2:missing"}, "контроль задел соседей")

    def test_site_that_starts_reading_a_tick_door_leaves_by_nature(self):
        """`BY_NATURE` ВЫВОДИТСЯ, а не назначается: B6 начинает читать ts_of."""
        broken = self.src.replace(
            "            if over or added:",
            "            if (over or added) and ts_of(MANIFEST_REL) is not None:", 1)
        self.assertNotEqual(broken, self.src, "контроль не применился")
        got = self._outcomes(broken)
        self.assertEqual(self.base["B6:curation_drift"], cen.BY_NATURE)
        self.assertEqual(got["B6:curation_drift"], cen.TICK_BLIND)

    def test_asking_the_tick_turns_blind_into_aware(self):
        """Обратный контроль: сайт лечится сверкой с тактом — и прибор это видит."""
        fixed = self.src.replace(
            "            if ts is None:\n                findings.append(_finding(\n"
            '                    f"B3:no_consumption:{path}"',
            "            if ts is None and float(budget) >= 0:\n"
            "                findings.append(_finding(\n"
            '                    f"B3:no_consumption:{path}"', 1)
        self.assertNotEqual(fixed, self.src, "контроль не применился")
        self.assertEqual(self._outcomes(fixed)["B3:no_consumption"], cen.TICK_AWARE)

    def test_verdict_factory_is_the_only_producer_of_severity(self):
        """Ограничение прибора названо И проверено: `severity` мимо фабрики —
        для переписи невидим. Если такой путь заведут, тест обязан упасть."""
        import ast
        tree = ast.parse(self.src)
        outside = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for k in node.keys:
                if isinstance(k, ast.Constant) and k.value == "severity":
                    outside.append(node.lineno)
        # Единственное разрешённое место — тело самой фабрики.
        factory = next(n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef)
                       and n.name == cen.VERDICT_FACTORY)
        span = range(factory.lineno, factory.end_lineno + 1)
        self.assertEqual([ln for ln in outside if ln not in span], [],
                         "вердикт собран мимо фабрики — перепись его не видит")


# ── ПОЛОВИНА II — третий исход у потребителя ─────────────────────────────────

def _conf_report(root, stamp, keys, severity="WARN"):
    """Отчёт сторожа архитектуры с названным ЗАМЕРОМ (`generated_at`)."""
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    doc = {"generated_at": stamp.isoformat(), "overall": "WARN",
           "findings": [{"key": k, "severity": severity, "message": f"м {k}"}
                        for k in keys]}
    json.dump(doc, open(os.path.join(root, "data",
                                     "architecture_conformance.json"), "w"))


class SightingIsAMeasurement(unittest.TestCase):
    """`REQUIRED_SIGHTINGS` обязан считать ЗАМЕРЫ, а не прогоны моста."""

    KEY = "B3:no_consumption:data/investment_os/quant.json"

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = self.dir.name
        self.addCleanup(self.dir.cleanup)
        self.created: list = []

    def _run(self, now):
        return fb.run_bridge(
            root=self.root, now=now,
            create=lambda root, f: self.created.append(f["key"]) or f"card-{f['key']}",
            close=lambda root, card: True,
            notify=lambda root, card: True,
            deliver=lambda *a, **k: {"delivered": []},
            retract=lambda root, card: True,
            deliver_answers=lambda *a, **k: {"delivered": []})

    def test_two_bridge_runs_on_one_measurement_do_not_make_a_card(self):
        """ГЛАВНАЯ СЦЕНА, воспроизводящая измеренный контур.

        Сторож ходит раз в 6ч, мост — из `decision_loop` (6ч) И из дневного
        цикла, то есть два прогона моста регулярно приходятся на ОДИН замер.
        Порог из двух наблюдений не смеет браться без повторного замера.
        """
        _conf_report(self.root, NOW, [self.KEY])
        self._run(NOW + dt.timedelta(minutes=5))
        self._run(NOW + dt.timedelta(hours=2))          # тот же файл отчёта
        self.assertEqual(self.created, [],
                         "карточка родилась на ОДНОМ замере — гистерезис мнимый")

    def test_second_measurement_does_make_a_card(self):
        """Обратная сторона: сторож НЕ стал зеленее.

        Находка, ПЕРЕЖИВШАЯ повторный замер, обязана дойти до карточки — иначе
        починка превратилась бы в глушилку очереди.
        """
        _conf_report(self.root, NOW, [self.KEY])
        self._run(NOW + dt.timedelta(minutes=5))
        _conf_report(self.root, NOW + dt.timedelta(hours=6), [self.KEY])
        self._run(NOW + dt.timedelta(hours=6, minutes=5))
        self.assertEqual(self.created, [self.KEY])

    def test_resighting_is_named_not_silent(self):
        """«Не засчитано» обязано ЗВУЧАТЬ: молчание неотличимо от «в порядке»."""
        _conf_report(self.root, NOW, [self.KEY])
        self._run(NOW + dt.timedelta(minutes=5))
        r = self._run(NOW + dt.timedelta(hours=2))
        self.assertIn(self.KEY, r["resighted_same_measurement"])
        self.assertEqual(r["measurement_unidentified"], [])

    def test_critical_still_bypasses_hysteresis(self):
        """CRITICAL не ждёт второго замера — это правило моста, и оно цело."""
        _conf_report(self.root, NOW, [self.KEY], severity="CRITICAL")
        self._run(NOW + dt.timedelta(minutes=5))
        self.assertEqual(self.created, [self.KEY])

    def test_source_without_a_stamp_counts_as_before_and_is_named(self):
        """Замер не опознан ⇒ считаем по-старому И НАЗЫВАЕМ.

        Fail-CLOSED здесь именно так: не засчитать — значит не родить карточку
        НИКОГДА («irreversible UNCHECKED starves the queue»).
        """
        os.makedirs(os.path.join(self.root, "data"), exist_ok=True)
        json.dump({"overall": "WARN",                      # без generated_at
                   "findings": [{"key": self.KEY, "severity": "WARN", "message": "м"}]},
                  open(os.path.join(self.root, "data",
                                    "architecture_conformance.json"), "w"))
        self._run(NOW + dt.timedelta(minutes=5))
        r = self._run(NOW + dt.timedelta(hours=2))
        self.assertEqual(self.created, [self.KEY])
        self.assertIn(self.KEY, r["measurement_unidentified"])

    def test_recurrence_starts_counting_measurements_afresh(self):
        """Рецидив: закрытая находка вернулась в ТОМ ЖЕ замере, что была последним
        наблюдением до закрытия, — и обязана считаться заново, а не молчать."""
        _conf_report(self.root, NOW, [self.KEY])
        self._run(NOW + dt.timedelta(minutes=5))
        _conf_report(self.root, NOW + dt.timedelta(hours=6), [self.KEY])
        self._run(NOW + dt.timedelta(hours=6, minutes=5))
        self.assertEqual(self.created, [self.KEY])
        state = json.load(open(os.path.join(self.root, fb.STATE_REL)))
        entry = state["findings"][self.KEY]
        entry.update(status="closed", card=None)
        json.dump(state, open(os.path.join(self.root, fb.STATE_REL), "w"))
        # тот же самый замер, что был последним до закрытия
        self._run(NOW + dt.timedelta(hours=7))
        state = json.load(open(os.path.join(self.root, fb.STATE_REL)))
        self.assertEqual(state["findings"][self.KEY]["seen_count"], 1,
                         "рецидив не начал счёт заново — наблюдение потеряно")


class DelegationToTheConsumerIsPinned(unittest.TestCase):
    """Почему `B3:no_consumption` остаётся `tick_blind` и это НЕ замолчано.

    Перепись меряет ОДИН модуль. У этого сайта третий исход существует, но живёт
    он этажом ниже — в гистерезисе моста. Такая передача обязана быть не словом
    в комментарии, а закреплённым фактом: если гистерезис исчезнет, третьего
    исхода у сайта не останется НИГДЕ, и падать должно здесь.
    """

    def test_hysteresis_exists_and_requires_more_than_one_sighting(self):
        self.assertGreaterEqual(
            fb.REQUIRED_SIGHTINGS, 2,
            "гистерезис моста — единственный третий исход B3:no_consumption; "
            "снят он — сайт остался без третьего исхода вовсе (ADR-266)")


if __name__ == "__main__":                                   # pragma: no cover
    unittest.main()
