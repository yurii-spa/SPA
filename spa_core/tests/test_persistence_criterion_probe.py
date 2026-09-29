"""ADR-508 — критерий §49 `Persistence` приказа CIO получает МАШИННУЮ мерку.

Почему этот файл существует
---------------------------
Перепись сроков жизни преимущества (`spa_core/monitoring/gain_persistence_census.py`,
цикл #702) меряет критерий владельца «Transient APY spikes не вызывают ненужные
trades» с сентября: её артефакт пишется в такте и свеж (замер 29.09 — 1,5 ч при
объявленном пределе 12 ч). А сводный замер §49 (`scripts/cio_acceptance_rollup.py`)
про этот критерий отвечал

    «машинной пробы, объявившей себя мерой этого критерия, в реестре НЕТ —
     вердикт сегодня взять неоткуда»

потому что запись «этот прибор есть мера этого критерия» лежала ПРОЗОЙ в заметке
`architecture/manifest.json`, а сводку читает машина (ADR-504, ADR-506). Заказ
владельца G95 п. 1: следующий `TRANSCRIPTION` — по образцу `Economics` (ADR-507) и
ТОЖЕ по одному, каждый со своим контролем в обе стороны.

Что здесь закреплено, и в ОБЕ стороны
-------------------------------------
* проба `persistence_advantage_outlives_horizon` зелена на целом контуре и красна
  на КАЖДОМ порванном звене — с названным звеном;
* обе породы вреда (`died_before_min_hold`, `died_within_payback_horizon`) — каждая
  сама по себе даёт `not_satisfied`;
* `WARNING` прибора (находка есть, но старше горизонта владельца) переносится в
  `not_satisfied`, а не в «выполнено»: тишина не есть доказательство;
* **ни один ход не измерим ⇒ `unmeasured`, НИКОГДА не `satisfied`** — «находок нет»
  и «мерить было нечем» обязаны быть различимы (инвариант #17);
* протухший ряд наблюдённых ставок ⇒ `unmeasured`, хотя прибор на том же материале
  говорит `OK`: это положительный контроль на СВОЙ вопрос пробы, и без него
  девятидневный ряд выдавал бы `satisfied` о «сегодня»;
* пропавшая колонка порогов ADR-060 §3 ⇒ `unmeasured`, а не подставленное умолчание;
* прибор, не объявивший себя мерой `§49 Persistence`, ⇒ `unmeasured`; и якорь
  читается как НАЧАЛО строки, а не как вхождение подстроки (ADR-333);
* неизвестный статус прибора ⇒ `unmeasured` (fail-CLOSED), а не `satisfied`;
* `data_dir` и `now` ДОХОДЯТ до пробы и до прибора — обе двери, а не одна
  («половина инъекции», `.claude/rules/deployment.md`);
* объявление `s49_criterion` указывает В НАСЕЛЕНИЕ §49, прочитанное из самой
  карточки приказа, а не мимо него.

Порядок контроля НЕ произволен: сначала доказывается, что фикстуры дают ИМЕННО те
породы (`TestFixturesReproduceTheMeasuredKinds`), и только потом — что проба на них
отвечает. Без первого шага «красно на порванном звене» тавтологично: красным может
быть что угодно, включая сцену, которая ничего не воспроизводит (требование G95 п. 1).

Часы — вход: якорь вычисляется ВНУТРИ теста (не на импорте — ADR-348) и подаётся и
в фикстуры, и в пробу. Литеральных дат в файле нет вовсе. Сеть не трогается, живое
`data/` не читается: журналы пишутся в одноразовый каталог.
"""
from __future__ import annotations

import json
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import gain_persistence_census as gpc
from spa_core.tests._freshness import now_utc

#: Имя пробы в реестре. Проверяется как ИМЯ (равенство), не как подстрока — ADR-333.
PROBE_NAME = "persistence_advantage_outlives_horizon"
#: Критерий §49, мерой которого проба себя объявляет.
CRITERION = "Persistence"
#: Модуль, из которого `load_policy` берёт колонку порогов владельца. Порвать эту
#: дверь — единственный способ проверить, что проба НЕ подставляет своё умолчание.
POLICY_MODULE = "spa_core.allocator.rebalance_economics"

#: Ставка покинутого источника. Постоянна во всех сценах: меняется ТОЛЬКО ставка
#: цели, поэтому знак преимущества задаётся ровно одним числом сцены.
SOURCE_RATE = 4.0
#: Ставка цели, пока преимущество живо, и после того, как оно умерло.
TARGET_RATE_ALIVE = 8.0
TARGET_RATE_DEAD = 2.0


class _ProbeBase(unittest.TestCase):
    """Одноразовый каталог с журналом ходов и рядом ставок. Часы — вход."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        # Якорь считается здесь, а не на импорте: анкер времени, вычисленный при
        # сборе тестов, краснеет от ДЛИТЕЛЬНОСТИ прогона (ADR-348).
        self.now = now_utc()

    # ── материал ────────────────────────────────────────────────────────────

    def _day(self, days_ago: int) -> str:
        return (self.now - timedelta(days=days_ago)).date().isoformat()

    def _move(self, days_ago: int, *, trade_id: str = "T1") -> dict:
        """Ход: $30 000 уходят из источника в цель. Ноги в обе стороны — предмет есть."""
        return {"trade_id": trade_id,
                "ts": (self.now - timedelta(days=days_ago)).isoformat(),
                "from_allocation": {"aave_v3": 50_000.0},
                "to_allocation": {"aave_v3": 20_000.0, "morpho_blue": 30_000.0}}

    def _not_a_transfer(self, days_ago: int) -> dict:
        """Ход только со входом: денег он ниоткуда не забирает, преимущества у него нет."""
        return {"trade_id": "T1",
                "ts": (self.now - timedelta(days=days_ago)).isoformat(),
                "from_allocation": {},
                "to_allocation": {"aave_v3": 50_000.0}}

    def _series(self, *, first: int, last: int, alive_while: int | None) -> dict:
        """Ряд ставок за дни `first`..`last` назад.

        `alive_while` — последний день (в «днях назад»), когда ставка цели ещё
        высока; дальше она падает, и преимущество умирает. `None` — не падает
        никогда.
        """
        source, target = [], []
        for n in range(first, last - 1, -1):
            day = self._day(n)
            source.append([day, SOURCE_RATE])
            dead = alive_while is not None and n < alive_while
            target.append([day, TARGET_RATE_DEAD if dead else TARGET_RATE_ALIVE])
        return {"aave_v3": source, "morpho_blue": target}

    def _write(self, moves: list, series: dict | None) -> None:
        (self.data_dir / "trades.json").write_text(
            json.dumps(moves), encoding="utf-8")
        if series is not None:
            (self.data_dir / "apy_series_daily.json").write_text(
                json.dumps({"series": series}), encoding="utf-8")

    # ── сцены ───────────────────────────────────────────────────────────────

    def scene_outlived(self) -> None:
        """Преимущество не умирало ни дня и пережило горизонт владельца."""
        self._write([self._move(40)],
                    self._series(first=41, last=1, alive_while=None))

    def scene_died_before_min_hold(self) -> None:
        """Преимущество кончилось на следующий день — раньше минимального удержания."""
        self._write([self._move(5)],
                    self._series(first=6, last=1, alive_while=5))

    def scene_died_within_payback(self) -> None:
        """Преимущество жило 5 дн.: дольше удержания, но внутри срока окупаемости."""
        self._write([self._move(25)],
                    self._series(first=26, last=1, alive_while=20))

    def scene_died_outside_horizon(self) -> None:
        """Тот же вред, но ход старше горизонта владельца: у прибора это `WARNING`."""
        self._write([self._move(40)],
                    self._series(first=41, last=1, alive_while=40))

    def scene_negative_at_move(self) -> None:
        """Преимущества не было уже в день хода: ставка цели ниже источника сразу."""
        self._write([self._move(5)],
                    self._series(first=6, last=1, alive_while=6))

    def scene_nothing_measurable(self) -> None:
        """Ход есть, но он ничего не переносит: находок нет, и мерить было нечего."""
        self._write([self._not_a_transfer(5)],
                    {"aave_v3": [[self._day(n), SOURCE_RATE] for n in (6, 5, 4, 3, 2, 1)]})

    def scene_no_series(self) -> None:
        """Журнал ходов есть, ряда наблюдённых ставок нет вовсе."""
        self._write([self._move(40)], None)

    def scene_stale_series(self) -> None:
        """Материал тот же, что в `scene_outlived`, но ряд кончается 9 дн. назад."""
        self._write([self._move(40)],
                    self._series(first=41, last=9, alive_while=None))

    def scene_at_horizon_edge(self) -> None:
        """Вред 29 дн. назад; ряд доведён до сегодня, чтобы сдвиг часов был законен."""
        self._write([self._move(29)],
                    self._series(first=31, last=0, alive_while=29))

    # ── приборы ─────────────────────────────────────────────────────────────

    def census(self, **kw) -> dict:
        return gpc.run_census(self.data_dir, now=kw.pop("now", self.now), **kw)

    def probe(self, **kw):
        return ca._probe_persistence_advantage_outlives_horizon(
            None, now=kw.pop("now", self.now), data_dir=str(self.data_dir), **kw)


class TestFixturesReproduceTheMeasuredKinds(_ProbeBase):
    """Сначала — что фикстуры дают ИМЕННО те породы. Иначе контроль ниже тавтологичен."""

    def _only(self) -> dict:
        report = self.census()
        self.assertTrue(report["measured"], report.get("reason"))
        self.assertEqual(1, len(report["items"]), report["items"])
        return report

    def test_outlived_scene_produces_the_outlived_kind_and_status_ok(self) -> None:
        self.scene_outlived()
        report = self._only()
        self.assertEqual(gpc.SPECIES_OUTLIVED, report["items"][0]["species"])
        self.assertEqual(gpc.STATUS_OK, report["status"])

    def test_died_before_min_hold_scene_produces_that_kind_and_is_fresh(self) -> None:
        self.scene_died_before_min_hold()
        report = self._only()
        item = report["items"][0]
        self.assertEqual(gpc.SPECIES_BEFORE_HOLD, item["species"])
        self.assertEqual(0, item["advantage_days"])
        # Свежесть — часть предпосылки: без неё сцена дала бы WARNING, а не CRITICAL,
        # и «красно на этом звене» относилось бы к другой породе.
        self.assertEqual(1, report["counts"]["recent_dead_within_horizon"])
        self.assertEqual(gpc.STATUS_CRITICAL, report["status"])

    def test_died_within_payback_scene_lives_longer_than_min_hold(self) -> None:
        self.scene_died_within_payback()
        report = self._only()
        item = report["items"][0]
        self.assertEqual(gpc.SPECIES_WITHIN_PAYBACK, item["species"])
        # Именно ЭТО отличает породу от соседней: срок больше минимального
        # удержания владельца и меньше срока окупаемости.
        self.assertGreaterEqual(item["advantage_days"], report["policy"]["min_hold_days"])
        self.assertLess(item["advantage_days"], report["policy"]["max_payback_days"])
        self.assertEqual(gpc.STATUS_CRITICAL, report["status"])

    def test_outside_horizon_scene_is_the_same_harm_but_warning(self) -> None:
        self.scene_died_outside_horizon()
        report = self._only()
        self.assertEqual(gpc.SPECIES_BEFORE_HOLD, report["items"][0]["species"])
        self.assertEqual(0, report["counts"]["recent_dead_within_horizon"])
        self.assertEqual(gpc.STATUS_WARNING, report["status"])

    def test_negative_at_move_scene_is_counted_as_such(self) -> None:
        self.scene_negative_at_move()
        report = self._only()
        self.assertLess(report["items"][0]["advantage_at_move_pp"], 0)
        self.assertEqual(1, report["counts"]["advantage_negative_at_move"])

    def test_nothing_measurable_scene_refuses_to_measure(self) -> None:
        self.scene_nothing_measurable()
        report = self.census()
        # Прибор отказывается, и это НЕ «находок нет».
        self.assertFalse(report["measured"])
        self.assertEqual(gpc.STATUS_UNMEASURED, report["status"])

    def test_stale_series_scene_is_green_for_the_instrument(self) -> None:
        """Предпосылка положительного контроля на СВОЙ вопрос пробы.

        Без этого утверждения тест «протухший ряд ⇒ unmeasured» ничего не стои́т:
        он был бы зелен и в случае, когда прибор на таком материале сам отказывает.
        """
        self.scene_stale_series()
        report = self._only()
        self.assertEqual(gpc.SPECIES_OUTLIVED, report["items"][0]["species"])
        self.assertEqual(gpc.STATUS_OK, report["status"])
        self.assertEqual(self._day(9), report["series"]["last_day"])

    def test_horizon_edge_scene_is_fresh_now_and_stale_two_days_later(self) -> None:
        """Предпосылка контроля проводки часов ДО прибора.

        Сцена подобрана так, что сдвиг часов на два дня переводит ход через
        горизонт владельца, а ряд при этом остаётся в пределах свежести — иначе
        сработал бы вопрос пробы, и о проводке часов до ПРИБОРА тест не сказал бы
        ничего.
        """
        self.scene_at_horizon_edge()
        self.assertEqual(1, self.census()["counts"]["recent_dead_within_horizon"])
        later = self.census(now=self.now + timedelta(days=2))
        self.assertEqual(0, later["counts"]["recent_dead_within_horizon"])
        self.assertEqual(gpc.STATUS_WARNING, later["status"])


class TestProbeTransfersTheVerdict(_ProbeBase):
    """Целый контур: вердикт прибора доходит до вердикта критерия без своих порогов."""

    def test_outlived_is_satisfied(self) -> None:
        self.scene_outlived()
        verdict, detail = self.probe()
        self.assertEqual(ca.SATISFIED, verdict)
        self.assertIn("пережил горизонт", detail)

    def test_died_before_min_hold_is_not_satisfied(self) -> None:
        self.scene_died_before_min_hold()
        verdict, detail = self.probe()
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("УМЕРЛО раньше горизонта", detail)

    def test_died_within_payback_is_not_satisfied(self) -> None:
        self.scene_died_within_payback()
        self.assertEqual(ca.NOT_SATISFIED, self.probe()[0])

    def test_warning_is_not_satisfied_because_silence_is_not_proof(self) -> None:
        """Находка старше горизонта — всё равно «не выполнен».

        Соблазн прочесть `WARNING` как «сегодня чисто» и есть тот дефект, ради
        которого прибор печатает замер отдельно от вердикта.
        """
        self.scene_died_outside_horizon()
        verdict, detail = self.probe()
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("только в истории", detail)

    def test_the_probe_names_the_blind_spots_it_does_not_judge(self) -> None:
        """Числа третьего исхода и невоспроизводимость §-теста 2 обязаны быть НАЗВАНЫ."""
        self.scene_died_before_min_hold()
        detail = self.probe()[1]
        self.assertIn("третий исход ходов", detail)
        self.assertIn("§-тест 2", detail)
        # Горизонты владельца тоже названы: у пробы своих чисел нет ни одного,
        # и читатель обязан видеть, ЧЬИ пороги решили вердикт.
        self.assertIn("горизонты владельца", detail)


class TestEveryBrokenLinkIsUnmeasuredNotAVerdict(_ProbeBase):
    """Каждое порванное звено — с названным звеном, и ни одно не даёт `satisfied`."""

    def test_missing_series_is_unmeasured(self) -> None:
        self.scene_no_series()
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("ряд наблюдённых ставок не найден", detail)

    def test_nothing_measurable_is_unmeasured_never_satisfied(self) -> None:
        """«Находок нет» и «мерить нечем» различимы — инвариант #17.

        Это самый дорогой из контролей: именно здесь ложное `satisfied` закрыло бы
        критерий владельца ничем.
        """
        self.scene_nothing_measurable()
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("НЕ ИЗМЕРЕН", detail)

    def test_stale_series_is_unmeasured_although_the_instrument_says_ok(self) -> None:
        self.scene_stale_series()
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("протух", detail)
        self.assertIn(self._day(9), detail)

    def test_series_last_day_that_is_not_a_date_is_unmeasured(self) -> None:
        self.scene_outlived()
        real = gpc.run_census

        def broken(*a, **kw):
            report = real(*a, **kw)
            report["series"] = {**report["series"], "last_day": "не-дата"}
            return report

        with patch.object(gpc, "run_census", broken):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не разобран как дата", detail)

    def test_series_without_a_last_day_is_unmeasured(self) -> None:
        self.scene_outlived()
        real = gpc.run_census

        def broken(*a, **kw):
            report = real(*a, **kw)
            report["series"] = {k: v for k, v in report["series"].items()
                                if k != "last_day"}
            return report

        with patch.object(gpc, "run_census", broken):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        # Фраза проверяется ИМЕННО этой ветки. Общая часть двух пояснений
        # («возраст материала НЕ ИЗМЕРЕН») не различала бы снятый вопрос от
        # нечитаемой даты — мутация выживала на ней и была права.
        self.assertIn("нет последнего дня", detail)

    def test_missing_owner_policy_column_is_unmeasured_not_a_default(self) -> None:
        """Пороги владельца недоступны ⇒ отказ. Подставленное умолчание было бы
        ответом на свой вопрос вместо нужного (§22 приказа: «Не hardcode»)."""
        self.scene_outlived()
        import sys
        with patch.dict(sys.modules, {POLICY_MODULE: None}):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("колонка порогов", detail)

    def test_instrument_that_does_not_declare_this_criterion_is_unmeasured(self) -> None:
        self.scene_outlived()
        with patch.object(gpc, "CRITERION", "§49 Anti-churn — чужой критерий"):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не объявляет себя мерой", detail)

    def test_the_anchor_is_read_as_a_prefix_not_as_a_substring(self) -> None:
        """ADR-333: объявление, где якорь стои́т где-то внутри, не есть привязка."""
        self.scene_outlived()
        with patch.object(gpc, "CRITERION",
                          "перепись прыжков; рядом упомянут §49 Persistence"):
            self.assertEqual(ca.UNMEASURED, self.probe()[0])

    def test_instrument_without_a_declaration_at_all_is_unmeasured(self) -> None:
        self.scene_outlived()
        with patch.object(gpc, "CRITERION", None):
            self.assertEqual(ca.UNMEASURED, self.probe()[0])

    def test_unknown_instrument_status_is_unmeasured_fail_closed(self) -> None:
        self.scene_outlived()
        real = gpc.run_census

        def weird(*a, **kw):
            return {**real(*a, **kw), "status": "ЧТО-ТО НОВОЕ"}

        with patch.object(gpc, "run_census", weird):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не переносится в вердикт", detail)

    def test_instrument_that_raises_is_unmeasured_with_the_cause_named(self) -> None:
        self.scene_outlived()

        def boom(*a, **kw):
            raise RuntimeError("дверь закрыта")

        with patch.object(gpc, "run_census", boom):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("RuntimeError", detail)
        self.assertIn("дверь закрыта", detail)

    def test_instrument_that_cannot_be_imported_is_unmeasured(self) -> None:
        self.scene_outlived()
        with patch.object(ca, "GAIN_PERSISTENCE_MODULE",
                          "spa_core.monitoring.нет_такого_модуля"):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не загружена", detail)


class TestTreeAndClockAreInputsNotEnvironment(_ProbeBase):
    """Обе двери к окружению закрыты, а не одна («половина инъекции»)."""

    def test_the_registry_declares_data_dir_as_an_input(self) -> None:
        self.assertIn("data_dir", ca.probe_tree_inputs(PROBE_NAME))

    def test_data_dir_reaches_the_instrument(self) -> None:
        """Пустой каталог ⇒ отказ, НАЗЫВАЮЩИЙ наш путь.

        Если бы вход не доходил, проба прочитала бы `data/` своего дерева и
        ответила бы о ЧУЖОМ материале — вердикт об одном дереве, выданный за
        вердикт о другом.
        """
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn(str(self.data_dir), detail)

    def test_clock_reaches_the_probes_own_freshness_question(self) -> None:
        """Сдвиг часов вперёд переводит свежий ряд в протухший — вердикт МЕНЯЕТСЯ."""
        self.scene_outlived()
        self.assertEqual(ca.SATISFIED, self.probe()[0])
        verdict, detail = self.probe(now=self.now + timedelta(days=10))
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("протух", detail)

    def test_clock_reaches_the_instrument_too_not_only_the_guard(self) -> None:
        """Часы доходят и ДО прибора: сдвиг переводит ход через горизонт владельца.

        Вердикт критерия здесь измениться НЕ МОЖЕТ по построению — и `CRITICAL`, и
        `WARNING` переносятся в `not_satisfied`, потому что «умерло» от часов не
        зависит. Поэтому контроль стои́т на ПОЯСНЕНИИ: в нём печатается число
        ходов внутри горизонта, и именно его читает владелец. Молчаливая
        подстановка стенных часов сделала бы это число неверным, не тронув
        вердикта, — ровно та половина инъекции, из-за которой класс и написан.
        """
        self.scene_at_horizon_edge()
        fresh = self.probe()[1]
        later = self.probe(now=self.now + timedelta(days=2))[1]
        self.assertIn("внутри горизонта владельца от now таких ходов 1", fresh)
        self.assertIn("только в истории", later)
        self.assertNotEqual(fresh, later)


class TestTheDeclarationItself(_ProbeBase):
    """Привязка объявлена ПОЛЕМ и указывает в население §49, а не мимо него."""

    def test_the_probe_is_registered_under_its_name(self) -> None:
        self.assertIn(PROBE_NAME, ca.PROBES)
        self.assertIs(ca.PROBES[PROBE_NAME],
                      ca._probe_persistence_advantage_outlives_horizon)

    def test_the_probe_declares_the_criterion_in_a_field(self) -> None:
        self.assertEqual(
            CRITERION,
            ca._probe_persistence_advantage_outlives_horizon.s49_criterion)

    def test_the_declaration_is_visible_through_the_registry_reader(self) -> None:
        """Читатель реестра возвращает СПИСОК: столкновение объявлений он не прячет.

        Поэтому утверждение здесь — «ровно одна проба и ровно эта», а не «имя
        совпало»: вторая проба, объявившая тот же критерий, обязана покраснеть.
        """
        self.assertEqual([PROBE_NAME],
                         ca.probes_by_s49_criterion().get(CRITERION))

    def test_the_report_derives_its_declaration_from_the_constant(self) -> None:
        """У строки объявления ОДНО место: доклад ПРОИСХОДИТ от константы.

        Проверяется происхождением, а не тождеством объектов: `assertIs` на строку
        доказательством не является — компилятор склеивает равные константы, и
        раздвоённый литерал прошёл бы такую проверку молча (измерено мутацией
        M14 этого цикла). Поэтому константа ПОДМЕНЯЕТСЯ, и доклад обязан
        последовать за ней; своя копия в докладе за подменой не пойдёт.
        """
        self.scene_outlived()
        other = "§49 Persistence — подменённое объявление"
        with patch.object(gpc, "CRITERION", other):
            self.assertEqual(other, self.census()["criterion"])

    def test_the_criterion_name_exists_in_the_live_order(self) -> None:
        """Объявление указывает В §49 карточки приказа, а не мимо населения.

        Население читается из САМОЙ карточки приказа тем же разбором, которым его
        читает сводка, — не из списка рядом. Карточки в дереве нет ⇒ падать ГРОМКО:
        «сверить не с чем» никогда не выдаётся за «сверено».
        """
        import importlib.util
        import os
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        spec = importlib.util.spec_from_file_location(
            "_rollup_for_persistence_probe",
            os.path.join(root, "scripts", "cio_acceptance_rollup.py"))
        if spec is None or spec.loader is None:
            self.fail("разбор §49 не загружен — население НЕ ИЗМЕРЕНО")
        rollup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rollup)
        card = os.path.join(root, rollup.CARD_REL)
        if not os.path.isfile(card):
            self.fail(f"карточка приказа {rollup.CARD_REL} отсутствует — сверить "
                      f"объявление НЕ С ЧЕМ; это не «чисто»")
        with open(card, encoding="utf-8") as fh:
            names = rollup.parse_s49_criteria(fh.read())
        self.assertIn(CRITERION, names)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
