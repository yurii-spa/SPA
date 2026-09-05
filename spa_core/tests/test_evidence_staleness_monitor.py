#!/usr/bin/env python3
"""Потребитель лестницы ADR-167: сторож, который наконец СПРАШИВАЕТ канал.

Каждый тест здесь — положительный контроль на настоящую аварию, а не украшение
(`.claude/rules/deployment.md`, «проверка сторожа сторожей»).

Аварии, которые воспроизводятся:

* **05.09.2026, замер цикла #494.** `yields.llama.fi/pools` отдавал HTTP 200 с
  телом `GET,HEAD` (8 байт, `content-type: application/json`, `age: 856`).
  Генератор отработал верно: перенёс последнее наблюдение и СОХРАНИЛ
  `live_apy_as_of` на 06:00Z, а `last_updated` честно обновил на «сейчас».
  Сторож, который судит о свежести по `last_updated`, объявил бы 12-часовое
  значение свежим — и объявлял бы так хоть неделю.
* **04.08.2026.** Одна сетевая икота обнулила `live_apy` у 34 адаптеров разом.
  ADR-167 требует в этом случае ТРЕВОГУ, а не эвакуацию книги.
* **Класс «не измерено, выданное за ответ».** Нечитаемый вход обязан давать
  третий исход и НЕнулевой код, а не тихий `OK` (fail-OPEN тише красного).

Часы приходят ВХОДОМ (приём №1 правила): якорь `NOW` передаётся в `run(now=NOW)`,
а все отметки фикстур строятся от него же — обе стороны закреплены, календарь на
вердикт не влияет.
"""
# FROZEN-DATE-OK: injected-clock — якорь NOW передаётся аргументом в
# mon.run(now=NOW), а каждая отметка фикстуры производится от него же через
# _stamp() = (NOW - timedelta(...)).isoformat(). Литеральных дат помимо самого
# якоря в файле нет, поэтому сдвиг календаря вердикта не меняет.
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.governance import evidence_staleness as es
from spa_core.monitoring import evidence_staleness_monitor as mon

#: Якорь. Обе стороны сравнения закреплены — тест бессмертен.
NOW = dt.datetime(2030, 5, 17, 12, 0, tzinfo=dt.timezone.utc)

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _stamp(hours_ago: float) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat()


class _Sandbox:
    """Каталог data/ с книгой и статусом адаптеров."""

    def __init__(self, positions: dict, observed: dict, *, file_written_h: float = 0.0,
                 omit: tuple = ()):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        if "current_positions.json" not in omit:
            self._put("current_positions.json", {"positions": positions})
        if "adapter_status.json" not in omit:
            # `last_updated` — время ЗАПИСИ файла (при переносе обновляется на
            # «сейчас»); `live_apy_as_of` — время НАБЛЮДЕНИЯ. Расхождение этих
            # двух полей и есть форма аварии 05.09.
            self._put("adapter_status.json", {
                "generated_at": _stamp(file_written_h),
                "adapters": {
                    name: {
                        "live_apy": None if as_of is None else 4.2,
                        "live_apy_as_of": as_of,
                        "live_apy_fresh": False,
                        "last_updated": _stamp(file_written_h),
                    } for name, as_of in observed.items()
                },
            })

    def _put(self, name, doc):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

    def run(self):
        return mon.run(now=NOW, write=False, data_dir=self.dir)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._tmp.cleanup()


class TestObservationClockNotFileClock(unittest.TestCase):
    """Свежесть судится по НАБЛЮДЕНИЮ, а не по времени записи файла."""

    def test_todays_real_outage_shape_is_not_read_as_fresh(self):
        """Положительный контроль аварии 05.09: файл свежий, наблюдение — нет.

        Смысл контроля: сторож, взявший `last_updated` (обновляемый при каждом
        переносе), объявил бы книгу наблюдаемой сколь угодно долго после смерти
        фида. Здесь файл записан «только что», а наблюдению 40 ч.
        """
        with _Sandbox({"aave_v3": 5000.0, "maple": 20000.0},
                      {"aave_v3": _stamp(40.0), "maple": _stamp(40.0)},
                      file_written_h=0.0) as sb:
            r = sb.run()
        stages = {p["protocol"]: p["stage"] for p in r["protocols"]}
        self.assertEqual(stages, {"aave_v3": es.SOFT_STALE, "maple": es.SOFT_STALE},
                         "наблюдение 40 ч > 36 ч — свежим быть не может")
        self.assertNotEqual(r["overall"], mon.OK)

    def test_fresh_observation_in_a_stale_file_still_counts(self):
        """Обратная сторона: старый файл со свежим наблюдением — это FRESH."""
        with _Sandbox({"aave_v3": 5000.0},
                      {"aave_v3": _stamp(1.0)}, file_written_h=200.0) as sb:
            r = sb.run()
        self.assertEqual(r["protocols"][0]["stage"], es.FRESH)


class TestMassBlindness(unittest.TestCase):
    """04.08: ослепли все разом ⇒ тревога, а НЕ эвакуация книги."""

    def test_mass_blindness_raises_alarm_and_moves_no_capital(self):
        with _Sandbox({"aave_v3": 5000.0, "maple": 20000.0, "compound_v3": 40000.0},
                      {"aave_v3": _stamp(50.0), "maple": _stamp(60.0),
                       "compound_v3": _stamp(400.0)}) as sb:
            r = sb.run()
        self.assertEqual(r["action"], es.ACTION_MASS_BLINDNESS)
        self.assertEqual(r["overall"], mon.CRITICAL)
        self.assertEqual(mon.exit_code(r), 2)
        self.assertEqual(r["to_derisk"], [],
                         "массовая слепота НЕ требует сокращения — это наша поломка")

    def test_one_fresh_protocol_is_enough_to_disprove_mass_blindness(self):
        """Мутация проверки: один свежий ⇒ это уже не массовая слепота."""
        with _Sandbox({"aave_v3": 5000.0, "compound_v3": 40000.0},
                      {"aave_v3": _stamp(1.0), "compound_v3": _stamp(400.0)}) as sb:
            r = sb.run()
        self.assertNotEqual(r["action"], es.ACTION_MASS_BLINDNESS)
        self.assertEqual(r["action"], es.ACTION_DERISK)


class TestDeriskIsNamedNotExecuted(unittest.TestCase):
    """Сторож НАЗЫВАЕТ. Исполнение — money-path, owner-gated."""

    def test_hard_stale_is_named_with_protocol_age_and_sum(self):
        """Пункт 4 карточки: назвать протокол, возраст наблюдения и сумму."""
        with _Sandbox({"aave_v3": 5000.0, "compound_v3": 40000.0},
                      {"aave_v3": _stamp(1.0), "compound_v3": _stamp(400.0)}) as sb:
            r = sb.run()
        self.assertEqual(r["action"], es.ACTION_DERISK)
        self.assertEqual(mon.exit_code(r), 2)
        named = r["to_derisk"]
        self.assertEqual([x["protocol"] for x in named], ["compound_v3"])
        self.assertEqual(named[0]["held_usd"], 40000.0)
        self.assertGreater(named[0]["age_hours"], es.HARD_STALE_H)
        self.assertIn("168", named[0]["reason"])

    def test_report_carries_no_allocation_authority(self):
        """Отчёт не содержит ни весов, ни целей — двигать капитал ему нечем.

        Смысл контроля: если однажды сюда добавят целевые веса, money-path
        уедет мимо owner-gate — а решение о нём владельцем ещё не принято
        (карточка `agent-derisk-po-slepote-podklyuchit-k-rebalansu`, backlog).
        """
        with _Sandbox({"compound_v3": 40000.0, "aave_v3": 5000.0},
                      {"compound_v3": _stamp(400.0), "aave_v3": _stamp(1.0)}) as sb:
            r = sb.run()
        forbidden = {"target_weights", "target_usd", "target_allocation",
                     "weights", "trades", "orders", "rebalance"}
        self.assertEqual(forbidden & set(r), set())


class TestMoneyWithoutAnObservationClock(unittest.TestCase):
    """UNKNOWN_AGE: деньги, которых лестница не видит ПО ПОСТРОЕНИЮ."""

    def test_unknown_age_money_is_named_and_never_derisked(self):
        """Замер 05.09: `fluid_usdc` — $20 000, `live_apy_as_of: null`.

        Сокращать по незнанию возраста — угадывание, поэтому в де-риск такой
        ключ не попадает. Но молчать о нём нельзя: после подключения money-path
        эти деньги останутся невидимы, и это надо ЗНАТЬ заранее.
        """
        with _Sandbox({"fluid_usdc": 20000.0, "aave_v3": 5000.0},
                      {"fluid_usdc": None, "aave_v3": _stamp(1.0)}) as sb:
            r = sb.run()
        stages = {p["protocol"]: p["stage"] for p in r["protocols"]}
        self.assertEqual(stages["fluid_usdc"], es.UNKNOWN_AGE)
        self.assertEqual(r["counts"]["unknown_age"], 1)
        self.assertEqual(r["usd"]["unknown_age"], 20000.0)
        self.assertNotIn("fluid_usdc", [x["protocol"] for x in r["to_derisk"]])
        self.assertEqual(r["overall"], mon.WARN, "названо, но тревогой не является")

    def test_a_protocol_absent_from_adapter_status_is_unknown_not_fresh(self):
        """Молчание о времени не есть свежесть."""
        with _Sandbox({"ghost": 1000.0, "aave_v3": 5000.0},
                      {"aave_v3": _stamp(1.0)}) as sb:
            r = sb.run()
        stages = {p["protocol"]: p["stage"] for p in r["protocols"]}
        self.assertEqual(stages["ghost"], es.UNKNOWN_AGE)


class TestThirdOutcome(unittest.TestCase):
    """«Не измерено» — самостоятельный исход, а не тихий OK."""

    def test_missing_inputs_are_unchecked_with_a_named_reason(self):
        with _Sandbox({}, {}, omit=("current_positions.json", "adapter_status.json")) as sb:
            r = sb.run()
        self.assertEqual(r["overall"], mon.UNCHECKED)
        self.assertEqual(mon.exit_code(r), 2, "молчаливый ноль здесь и есть дефект")
        self.assertTrue(r["unchecked"])
        self.assertTrue(all(isinstance(x, str) and x.strip() for x in r["unchecked"]))

    def test_unparseable_input_is_unchecked_not_ok(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "current_positions.json"), "w") as fh:
                fh.write("{это не json")
            with open(os.path.join(d, "adapter_status.json"), "w") as fh:
                json.dump([], fh)
            r = mon.run(now=NOW, write=False, data_dir=d)
        self.assertEqual(r["overall"], mon.UNCHECKED)
        self.assertEqual(mon.exit_code(r), 2)

    def test_empty_book_is_unchecked_not_ok(self):
        """Пустая книга — «мерить нечего», а не «всё свежо» (прецедент ADR-226)."""
        with _Sandbox({}, {"aave_v3": _stamp(1.0)}) as sb:
            r = sb.run()
        self.assertEqual(r["overall"], mon.UNCHECKED)
        self.assertEqual(mon.exit_code(r), 2)

    def test_a_healthy_book_really_does_pass(self):
        """Обратная сторона: сторож, который не умеет сказать OK, бесполезен."""
        with _Sandbox({"aave_v3": 5000.0, "maple": 20000.0},
                      {"aave_v3": _stamp(2.0), "maple": _stamp(3.0)}) as sb:
            r = sb.run()
        self.assertEqual(r["overall"], mon.OK)
        self.assertEqual(mon.exit_code(r), 0)
        self.assertEqual(r["action"], es.ACTION_NONE)


class TestTheChannelIsActuallyWired(unittest.TestCase):
    """Дефект, который эта работа закрывает: канал был построен и НЕ подключён.

    Проверяется ПРОВОДКА, а не наличие модуля: до цикла #494 сам
    `governance/evidence_staleness.py` существовал, был покрыт 22 тестами и
    имел НОЛЬ вызовов вне них. Тест на «модуль импортируется» такой дефект
    не увидел бы — он и не видел его неделю.
    """

    def test_findings_bridge_declares_and_calls_the_monitor(self):
        from spa_core.monitoring import findings_bridge
        self.assertIn("data/evidence_staleness.json", findings_bridge.PRODUCES)
        src = open(os.path.join(_REPO, "spa_core/monitoring/findings_bridge.py"),
                   encoding="utf-8").read()
        self.assertIn("evidence_staleness_monitor.run(", src,
                      "объявить продукт мало — его должен кто-то ВЫЗЫВАТЬ")

    def test_manifest_declares_the_artifact_for_the_orchestrator(self):
        man = json.load(open(os.path.join(_REPO, "architecture/manifest.json"),
                             encoding="utf-8"))
        rows = [a for a in man["artifacts"]
                if a.get("path") == "data/evidence_staleness.json"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "active")
        self.assertIn("orchestrator_protocol", rows[0]["consumers"],
                      "без потребителя обязательный шаг его не прочитает")

    def test_the_producing_agent_declares_it_too(self):
        """Артефакт должен быть в `produces` того агента, который его пишет."""
        man = json.load(open(os.path.join(_REPO, "architecture/manifest.json"),
                             encoding="utf-8"))
        agent = next(a for a in man["agents"] if a["label"] == "com.spa.decision_loop")
        self.assertIn("data/evidence_staleness.json",
                      [p["artifact"] for p in agent["produces"]])

    def test_office_step_knows_how_to_read_it(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_cor", os.path.join(_REPO, "scripts/consume_office_reports.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertIn("evidence_staleness.json", m._READ_SCHEMA)
        self.assertEqual(m._PRODUCER["evidence_staleness.json"],
                         "spa_core/monitoring/evidence_staleness_monitor.py")


class TestLadderAgreesWithGovernance(unittest.TestCase):
    """Пороги не заводятся здесь заново — они ЧИТАЮТСЯ из governance."""

    def test_report_quotes_the_governance_ladder(self):
        with _Sandbox({"aave_v3": 5000.0}, {"aave_v3": _stamp(1.0)}) as sb:
            r = sb.run()
        self.assertEqual(r["ladder"]["soft_stale_h"], es.SOFT_STALE_H)
        self.assertEqual(r["ladder"]["hard_stale_h"], es.HARD_STALE_H)

    def test_monitor_defines_no_threshold_of_its_own(self):
        """Копия порога здесь = лестница расходится молча (урок ADR-167)."""
        src = open(os.path.join(_REPO,
                   "spa_core/monitoring/evidence_staleness_monitor.py"),
                   encoding="utf-8").read()
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("#"))
        body = code.split('"""', 2)[-1]
        for lit in ("36.0", "168.0", "= 36", "= 168"):
            self.assertNotIn(lit, body,
                             f"порог {lit} обязан жить только в governance")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
