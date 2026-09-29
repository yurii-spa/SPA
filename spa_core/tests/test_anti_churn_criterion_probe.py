"""ADR-511 — критерий §49 `Anti-churn` приказа CIO получает МАШИННУЮ мерку.

Почему этот файл существует
---------------------------
Перепись прыжков книги (`spa_core/monitoring/book_oscillation_census.py`, цикл
#701) меряет критерий владельца «Система не прыгает между одинаковыми
opportunities» с сентября: её артефакт пишется ступенью моста в такте и свеж
(замер 29.09 — 4,7 ч при объявленном пределе 12 ч). А сводный замер §49
(`scripts/cio_acceptance_rollup.py`) про этот критерий отвечал

    «машинной пробы, объявившей себя мерой этого критерия, в реестре НЕТ —
     вердикт сегодня взять неоткуда»

потому что запись «этот прибор есть мера этого критерия» лежала ПРОЗОЙ в заметке
`architecture/manifest.json`, а сводку читает машина (ADR-504, ADR-506). Заказ
владельца: следующий `TRANSCRIPTION` — по образцу `Economics` (ADR-507),
`Persistence` (ADR-508) и `Risk` (ADR-510), ТОЖЕ по одному и со своим контролем в
обе стороны.

Что здесь закреплено, и в ОБЕ стороны
-------------------------------------
* проба `book_does_not_oscillate_between_opportunities` зелена на целом контуре и
  красна на КАЖДОМ порванном звене — с названным звеном;
* две породы возврата дают `not_satisfied` каждая сама по себе: возврат за два
  хода (гистерезис его ВИДЕЛ — вопрос величины порога) и возврат за три и более
  ходов (гистерезису его нечем увидеть — вопрос ПРЕДМЕТА сравнения);
* `WARNING` прибора (внутри окна от `now` тихо, но в истории возвраты есть)
  переносится в `not_satisfied`, а не в «выполнено»: критерий говорит о свойстве
  системы, а не о погоде на этой неделе;
* **хвост журнала разошёлся со стоящей книгой ⇒ `unmeasured`** — вопрос свежести
  адресован `current_positions.json`, а НЕ журналу ходов: ходы бывают не каждый
  день (замер 29.09 — последний 18 дн назад), и спрашивать возраст у журнала
  значило бы объявить спокойную неделю протухшей. Опасность здесь ОБРАТНАЯ
  вердикту `Risk`: ложь была бы ЗЕЛЁНОЙ — «возвратов от now нет» звучит одинаково
  у починенной системы, у замороженного канона `data/` и у книги, двигавшейся
  мимо записи;
* прибор, не объявивший себя мерой `§49 Anti-churn`, ⇒ `unmeasured`; и якорь
  читается как НАЧАЛО строки, а не как вхождение подстроки (ADR-333);
* неизвестный статус прибора ⇒ `unmeasured` (fail-CLOSED), а не `satisfied`;
* `data_dir` и `now` ДОХОДЯТ и до пробы, и до прибора — ОБЕ двери, а не одна
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

from spa_core.monitoring import book_oscillation_census as boc
from spa_core.monitoring import card_acceptance as ca
from spa_core.tests._freshness import now_utc

#: Имя пробы в реестре. Проверяется как ИМЯ (равенство), не как подстрока — ADR-333.
PROBE_NAME = "book_does_not_oscillate_between_opportunities"
#: Критерий §49, мерой которого проба себя объявляет.
CRITERION = "Anti-churn"

#: Книга сцены. Число одно на весь файл, состояния складываются в него.
CAPITAL = 100_000.0

#: Четыре состояния книги. Расхождения между ними на порядки выше порога
#: существенности (`min_leg_frac` × книга), поэтому «книга покинула состояние»
#: здесь факт сцены, а не следствие удачно подобранного числа.
STATE_A = {"aave_v3": 60_000.0, "compound_v3": 40_000.0}
STATE_B = {"aave_v3": 30_000.0, "compound_v3": 70_000.0}
STATE_C = {"aave_v3": 45_000.0, "compound_v3": 25_000.0, "maple": 30_000.0}
STATE_D = {"aave_v3": 20_000.0, "compound_v3": 20_000.0, "maple": 60_000.0}


class _ProbeBase(unittest.TestCase):
    """Одноразовый каталог: журнал ходов и книга, которая «стои́т сегодня»."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        # Якорь считается здесь, а не на импорте: анкер времени, вычисленный при
        # сборе тестов, краснеет от ДЛИТЕЛЬНОСТИ прогона (ADR-348).
        self.now = now_utc()
        # Окно разворота — колонка ВЛАДЕЛЬЦА, а не число сцены: сцена обязана
        # строиться от того же порога, которым судит живой путь. Колонка
        # недоступна ⇒ падать ГРОМКО: предпосылки нет, и судить не о чем.
        policy = boc.load_policy()
        if not policy["measured"]:
            self.fail(f"колонка порогов ADR-060 §3 недоступна: {policy['reason']} — "
                      f"предпосылка сцены НЕ ОБЕСПЕЧЕНА, и молчать об этом нельзя")
        self.window_days = policy["reversal_window_days"]

    # ── материал ────────────────────────────────────────────────────────────

    def _write(self, states: list, *, days_ago: list,
               book: dict | None = None, book_age_days: float = 0.0,
               write_book: bool = True) -> None:
        """Журнал ходов из цепочки состояний и книга, которая «стои́т сегодня».

        `states` — состояния книги ПО ПОРЯДКУ, начиная с исходного: цепочка из
        N состояний даёт N-1 ходов, и шов между соседними ходами сходится по
        построению (`to_allocation[i]` = `from_allocation[i+1]`). Псевдонимов
        ключей такая сцена не порождает — они предмет отдельного прибора.

        По умолчанию книга РАВНА последнему состоянию цепочки — то есть целый
        контур. Сцены расхождения задают `book` явно.
        """
        moves = []
        for i in range(len(states) - 1):
            moves.append({
                "trade_id": f"T{i + 1}",
                "ts": (self.now - timedelta(days=days_ago[i])).isoformat(),
                "capital": CAPITAL,
                "from_allocation": dict(states[i]),
                "to_allocation": dict(states[i + 1]),
            })
        (self.data_dir / "trades.json").write_text(json.dumps(moves), encoding="utf-8")
        if not write_book:
            return
        positions = dict(states[-1]) if book is None else dict(book)
        stamp = (self.now - timedelta(days=book_age_days)).isoformat()
        (self.data_dir / "current_positions.json").write_text(
            json.dumps({"generated_at": stamp, "positions": positions}),
            encoding="utf-8")

    # ── сцены ───────────────────────────────────────────────────────────────

    def scene_never_returns(self) -> None:
        """Книга шла вперёд и ни разу не вернулась: A → B → C → D."""
        self._write([STATE_A, STATE_B, STATE_C, STATE_D], days_ago=[5, 3, 1])

    def scene_return_seen_by_hysteresis(self) -> None:
        """Возврат за ДВА хода: A → B → A. Гистерезис его видел, ход состоялся."""
        self._write([STATE_A, STATE_B, STATE_A], days_ago=[5, 3])

    def scene_return_invisible_by_construction(self) -> None:
        """Возврат за ТРИ хода: A → B → C → A. Гистерезису нечем его увидеть."""
        self._write([STATE_A, STATE_B, STATE_C, STATE_A], days_ago=[5, 3, 1])

    def scene_return_only_in_history(self) -> None:
        """Тот же возврат за два хода, но оба конца старше окна от `now`.

        Внутри окна разворота от сегодня тихо — у прибора это `WARNING`.
        """
        old = self.window_days * 2
        self._write([STATE_A, STATE_B, STATE_A], days_ago=[old + 2, old])

    def scene_departure_too_far_apart(self) -> None:
        """Книга вернулась, но концы разнесены ШИРЕ окна разворота владельца.

        Политика такой возврат разворотом не считает, и претензии к нему у
        прибора нет — это `OK`, а не тихое замалчивание.
        """
        far = self.window_days * 3
        self._write([STATE_A, STATE_B, STATE_A], days_ago=[far + far, 0.0])

    def scene_no_journal(self) -> None:
        """Журнала ходов нет вовсе: переигрывать нечего."""
        (self.data_dir / "current_positions.json").write_text(
            json.dumps({"generated_at": self.now.isoformat(), "positions": {}}),
            encoding="utf-8")

    def scene_stale_standing_book(self) -> None:
        """Тот же чистый материал, но книга снята давно."""
        self._write([STATE_A, STATE_B, STATE_C, STATE_D], days_ago=[5, 3, 1],
                    book_age_days=ca.STANDING_BOOK_MAX_AGE_D + 1)

    def scene_book_moved_on(self) -> None:
        """Журнал кончается на D, а сегодня стои́т другая книга."""
        self._write([STATE_A, STATE_B, STATE_C, STATE_D], days_ago=[5, 3, 1],
                    book=STATE_B)

    # ── приборы ─────────────────────────────────────────────────────────────

    def census(self) -> dict:
        return boc.run_census(self.data_dir, now=self.now)

    def probe(self, **kw) -> tuple:
        kw.setdefault("data_dir", str(self.data_dir))
        kw.setdefault("now", self.now)
        return ca.PROBES[PROBE_NAME](None, **kw)


class TestFixturesReproduceTheMeasuredKinds(_ProbeBase):
    """Сначала — что сцены дают ИМЕННО те породы, о которых потом судит проба.

    Без этого шага «проба красна на порванном звене» ничего не доказывает:
    красной она может быть и на сцене, которая не воспроизводит вообще ничего.
    """

    def test_forward_only_scene_has_no_returns_at_all(self) -> None:
        self.scene_never_returns()
        report = self.census()
        self.assertEqual(boc.STATUS_OK, report["status"])
        self.assertEqual(0, report["counts"]["returns_total"])

    def test_two_move_return_is_the_kind_hysteresis_could_see(self) -> None:
        self.scene_return_seen_by_hysteresis()
        report = self.census()
        self.assertEqual(boc.STATUS_CRITICAL, report["status"])
        self.assertEqual(1, report["counts"]["visible_to_check"])
        self.assertEqual(0, report["counts"]["invisible_by_construction"])
        self.assertFalse(report["blind_spot_demonstrated"])

    def test_three_move_return_is_the_kind_hysteresis_cannot_see(self) -> None:
        """Ровно та порода, ради которой прибор написан: слепота по ПОСТРОЕНИЮ."""
        self.scene_return_invisible_by_construction()
        report = self.census()
        self.assertEqual(boc.STATUS_CRITICAL, report["status"])
        self.assertEqual(1, report["counts"]["invisible_by_construction"])
        self.assertEqual(0, report["counts"]["visible_to_check"])
        self.assertTrue(report["blind_spot_demonstrated"])

    def test_old_return_is_a_warning_not_a_critical(self) -> None:
        """Возврат есть, но внутри окна от `now` тихо — средняя порода прибора."""
        self.scene_return_only_in_history()
        report = self.census()
        self.assertEqual(boc.STATUS_WARNING, report["status"])
        self.assertEqual(1, report["counts"]["returns_within_window"])
        self.assertEqual(0, report["counts"]["recent_within_window_from_now"])

    def test_return_wider_than_the_owners_window_is_not_a_reversal(self) -> None:
        """Сцена доказывает, что `OK` бывает НЕ только от отсутствия возвратов."""
        self.scene_departure_too_far_apart()
        report = self.census()
        self.assertEqual(boc.STATUS_OK, report["status"])
        self.assertEqual(1, report["counts"]["returns_total"])
        self.assertEqual(0, report["counts"]["returns_within_window"])

    def test_stale_book_scene_is_green_for_the_instrument(self) -> None:
        """Прибор о возрасте стоящей книги не спрашивает — вопрос ПРОБЫ, не его.

        Без этой пары «протухшая книга ⇒ unmeasured» ничего не доказывало бы:
        красным мог бы быть сам прибор.
        """
        self.scene_stale_standing_book()
        self.assertEqual(boc.STATUS_OK, self.census()["status"])

    def test_moved_on_book_scene_is_green_for_the_instrument_too(self) -> None:
        self.scene_book_moved_on()
        self.assertEqual(boc.STATUS_OK, self.census()["status"])

    def test_the_instrument_publishes_the_tail_it_ends_on(self) -> None:
        self.scene_never_returns()
        present = self.census()["present"]
        self.assertEqual("T3", present["trade_id"])
        self.assertEqual(STATE_D, present["positions"])


class TestProbeTransfersTheVerdict(_ProbeBase):
    """Вердикт прибора доходит до критерия — и ни одна порода не теряется."""

    def test_a_book_that_never_returned_is_satisfied(self) -> None:
        self.scene_never_returns()
        verdict, why = self.probe()
        self.assertEqual(ca.SATISFIED, verdict)
        self.assertIn("не возвращалась", why)

    def test_return_seen_by_hysteresis_is_not_satisfied(self) -> None:
        """Гистерезис его ВИДЕЛ, и ход всё равно состоялся — вопрос величины порога."""
        self.scene_return_seen_by_hysteresis()
        verdict, why = self.probe()
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("видел и пропустил 1", why)

    def test_return_invisible_by_construction_is_not_satisfied(self) -> None:
        """Вопрос ПРЕДМЕТА сравнения, и проба называет его отдельным числом."""
        self.scene_return_invisible_by_construction()
        verdict, why = self.probe()
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("по построению 1", why)

    def test_warning_is_not_satisfied_because_quiet_week_is_not_proof(self) -> None:
        """Средняя порода прибора НЕ превращается в «выполнено».

        Критерий владельца говорит о свойстве СИСТЕМЫ («не прыгает»), а не о
        погоде на этой неделе; и проба обязана сказать вслух, что тишина
        сегодня — не «такого не бывало».
        """
        self.scene_return_only_in_history()
        verdict, why = self.probe()
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("только в истории", why)
        self.assertIn("НЕ «такого не бывало»", why)

    def test_a_return_wider_than_the_window_stays_satisfied(self) -> None:
        """Окно — колонка владельца, и проба её НЕ переигрывает своим числом."""
        self.scene_departure_too_far_apart()
        self.assertEqual(ca.SATISFIED, self.probe()[0])

    def test_the_probe_names_what_it_does_not_prove(self) -> None:
        """Односторонность доказательства названа в пояснении, а не только в теле."""
        self.scene_never_returns()
        why = self.probe()[1]
        self.assertIn("вне журнала", why)

    def test_the_thresholds_come_from_the_owners_column_not_from_the_probe(self) -> None:
        """Проба печатает ЧЬЁ окно применено — иначе число стало бы ничьим."""
        self.scene_never_returns()
        why = self.probe()[1]
        self.assertIn("TriggerParams владельца", why)
        self.assertIn(str(self.window_days), why)


class TestEveryBrokenLinkIsUnmeasuredNotAVerdict(_ProbeBase):
    """Каждое порванное звено — «НЕ ИЗМЕРЕНО» с НАЗВАННОЙ причиной, не вердикт."""

    def test_missing_journal_is_unmeasured(self) -> None:
        self.scene_no_journal()
        verdict, why = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("журнал ходов не найден", why)

    def test_missing_standing_book_is_unmeasured(self) -> None:
        self._write([STATE_A, STATE_B, STATE_C, STATE_D], days_ago=[5, 3, 1],
                    write_book=False)
        verdict, why = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не прочитана", why)

    def test_stale_standing_book_is_unmeasured_although_instrument_says_ok(self) -> None:
        """Прибор зелен (выше доказано), а проба отказывает — звено её, не его."""
        self.scene_stale_standing_book()
        verdict, why = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("протухла", why)
        self.assertIn("тишиной мёртвого дерева", why)

    def test_standing_book_without_a_stamp_is_unmeasured(self) -> None:
        self.scene_never_returns()
        (self.data_dir / "current_positions.json").write_text(
            json.dumps({"positions": STATE_D}), encoding="utf-8")
        verdict, why = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("generated_at", why)

    def test_standing_book_stamp_that_is_not_a_date_is_unmeasured(self) -> None:
        self.scene_never_returns()
        (self.data_dir / "current_positions.json").write_text(
            json.dumps({"generated_at": "позавчера", "positions": STATE_D}),
            encoding="utf-8")
        verdict, why = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не разобрана как дата", why)

    def test_a_book_that_moved_on_is_unmeasured_never_satisfied(self) -> None:
        """Ходы мимо записи — ровно тот случай, когда «возвратов нет» ЛОЖНО-ЗЕЛЕНО."""
        self.scene_book_moved_on()
        verdict, why = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("неполноту", why)

    def test_same_keys_with_other_money_is_also_a_different_book(self) -> None:
        """Совпадения ИМЁН мало: сверяются суммы, иначе дверь закрыта наполовину."""
        moved = dict(STATE_D)
        moved["maple"] = moved["maple"] + CAPITAL / 4
        self._write([STATE_A, STATE_B, STATE_C, STATE_D], days_ago=[5, 3, 1],
                    book=moved)
        verdict, why = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("разошлись суммой", why)

    def test_money_below_materiality_is_not_a_different_book(self) -> None:
        """Обратная сторона той же двери: порог существенности — правило ПРИБОРА.

        Копейка, добавленная в книгу, не делает её другой; иначе проба отказывала
        бы каждый день на ровном месте и приучила бы себя игнорировать.
        """
        self.scene_never_returns()
        crumb = dict(STATE_D)
        crumb["морковка"] = 1.0
        (self.data_dir / "current_positions.json").write_text(
            json.dumps({"generated_at": self.now.isoformat(), "positions": crumb}),
            encoding="utf-8")
        self.assertEqual(ca.SATISFIED, self.probe()[0])

    def test_report_without_the_tail_composition_is_unmeasured(self) -> None:
        self.scene_never_returns()
        real = boc.run_census

        def without_present(*a, **kw):
            doc = real(*a, **kw)
            doc.pop("present", None)
            return doc

        with patch.object(boc, "run_census", without_present):
            verdict, why = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("СОСТАВ", why)

    def test_report_without_materiality_is_unmeasured(self) -> None:
        """Без порога прибора привести чужую книгу к его виду НЕЧЕМ."""
        self.scene_never_returns()
        real = boc.run_census

        def without_threshold(*a, **kw):
            doc = real(*a, **kw)
            doc.pop("materiality_usd", None)
            return doc

        with patch.object(boc, "run_census", without_threshold):
            verdict, why = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("порог существенности", why)

    def test_report_without_counts_is_unmeasured_not_six_zeroes(self) -> None:
        self.scene_never_returns()
        real = boc.run_census

        def without_counts(*a, **kw):
            doc = real(*a, **kw)
            doc.pop("counts", None)
            return doc

        with patch.object(boc, "run_census", without_counts):
            verdict, why = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("НЕ ИЗМЕРЕНО за измеренный ноль", why)

    def test_report_that_declares_itself_unmeasured_is_unmeasured(self) -> None:
        """Третий исход прибора переносится ЦЕЛИКОМ, вместе с его причиной."""
        self.scene_never_returns()
        reason = "колонка порогов ADR-060 §3 недоступна — сцена третьего исхода"
        with patch.object(boc, "run_census",
                          lambda *a, **kw: {"measured": False, "reason": reason}):
            verdict, why = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn(reason, why)

    def test_instrument_that_does_not_declare_this_criterion_is_unmeasured(self) -> None:
        self.scene_never_returns()
        with patch.object(boc, "CRITERION", "§49 Costs — чужой критерий"):
            verdict, why = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не объявляет себя мерой", why)

    def test_the_anchor_is_read_as_a_prefix_not_as_a_substring(self) -> None:
        """Якорь — НАЧАЛО строки. Подстрока совпала бы с любой заметкой (ADR-333)."""
        self.scene_never_returns()
        with patch.object(boc, "CRITERION",
                          "заметка про демпфер частоты, см. §49 Anti-churn"):
            self.assertEqual(ca.UNMEASURED, self.probe()[0])

    def test_instrument_without_a_declaration_at_all_is_unmeasured(self) -> None:
        self.scene_never_returns()
        with patch.object(boc, "CRITERION", ""):
            self.assertEqual(ca.UNMEASURED, self.probe()[0])

    def test_unknown_instrument_status_is_unmeasured_fail_closed(self) -> None:
        """Статус, которого проба не знает, — отказ, а НЕ «выполнено»."""
        self.scene_never_returns()
        real = boc.run_census

        def odd_status(*a, **kw):
            doc = real(*a, **kw)
            doc["status"] = "НЕВИДАННЫЙ"
            return doc

        with patch.object(boc, "run_census", odd_status):
            verdict, why = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не переносится", why)

    def test_instrument_that_raises_is_unmeasured_with_the_cause_named(self) -> None:
        self.scene_never_returns()

        def boom(*a, **kw):
            raise RuntimeError("журнал развалился под прибором")

        with patch.object(boc, "run_census", boom):
            verdict, why = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("журнал развалился под прибором", why)

    def test_instrument_that_cannot_be_imported_is_unmeasured(self) -> None:
        """Отсутствие ПРИБОРА — третий исход, а не ноль находок (урок `pyflakes`)."""
        self.scene_never_returns()
        with patch.object(ca, "BOOK_OSCILLATION_MODULE", "нет.такого.модуля"):
            verdict, why = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не загружена", why)


class TestClockAndDirAreInputsNotEnvironment(_ProbeBase):
    """Обе двери к окружению закрыты — и у пробы, и у ПРИБОРА («половина инъекции»)."""

    def test_the_registry_declares_the_data_dir_input(self) -> None:
        """Дерево прибору не нужно: он судит журнал, а не код — и `repo_root` не
        объявлен НАМЕРЕННО. Вход, не доходящий ни до чего, был бы дверью-обманкой.
        """
        import inspect
        params = inspect.signature(ca.PROBES[PROBE_NAME]).parameters
        self.assertIn("data_dir", params)
        self.assertIn("now", params)
        self.assertNotIn("repo_root", params)

    def test_data_dir_reaches_the_instrument_not_only_the_guard(self) -> None:
        """Каталог доходит до ПРИБОРА: чужой каталог меняет вердикт, а не только
        ответ сторожа свежести."""
        self.scene_never_returns()
        other = TemporaryDirectory()
        self.addCleanup(other.cleanup)
        verdict, why = self.probe(data_dir=other.name)
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn(other.name, why)

    def test_clock_reaches_the_instrument_too_not_only_the_probe(self) -> None:
        """Часы доходят до прибора: тот же материал меняет породу от `now`.

        Сцена — свежий возврат. Сдвинув часы вперёд за окно разворота, тот же
        журнал обязан стать `WARNING` вместо `CRITICAL`. Стенные часы внутри
        прибора этого сдвига не заметили бы.
        """
        self.scene_return_seen_by_hysteresis()
        fresh = self.census()
        self.assertEqual(boc.STATUS_CRITICAL, fresh["status"])
        later = self.now + timedelta(days=self.window_days * 2)
        aged = boc.run_census(self.data_dir, now=later)
        self.assertEqual(boc.STATUS_WARNING, aged["status"])

    def test_clock_reaches_the_instrument_THROUGH_THE_PROBE(self) -> None:
        """Мало, чтобы часы доходили до прибора: они обязаны доходить ЧЕРЕЗ пробу.

        Найдено мутацией этого цикла. Соседний тест гоняет прибор НАПРЯМУЮ и
        поэтому зелен и тогда, когда проба часы прибору не передаёт вовсе, —
        ровно «половина инъекции» (`.claude/rules/deployment.md`): у прибора
        аргумент есть, по проводке он не идёт, и вердикт решают стенные часы.

        Контроль поэтому на ИСХОД пробы. Сцена — возврат, оба конца которого
        давно позади стенных часов. Часы, поданные В МОМЕНТ последнего хода,
        обязаны дать «возврат ВНУТРИ окна от now»; стенные (мутант) дадут «только
        в истории». Вердикт у обоих один, и именно поэтому сверяется ПРИЧИНА:
        мутация здесь меняет не цвет, а то, о каком дне речь.
        """
        self.scene_return_only_in_history()
        at_the_move = self.now - timedelta(days=self.window_days * 2)
        verdict, why = self.probe(now=at_the_move)
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("внутри окна разворота от now таких возвратов 1", why)
        self.assertNotIn("только в истории", why)

    def test_clock_reaches_the_probes_own_freshness_question(self) -> None:
        """Часы доходят и до вопроса о возрасте стоящей книги, а не только до прибора."""
        self.scene_never_returns()
        self.assertEqual(ca.SATISFIED, self.probe()[0])
        later = self.now + timedelta(days=ca.STANDING_BOOK_MAX_AGE_D + 2)
        verdict, why = self.probe(now=later)
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("протухла", why)


class TestTheDeclarationItself(_ProbeBase):
    """Привязка объявлена ПОЛЕМ и указывает в население §49, а не мимо него."""

    def test_the_probe_is_registered_under_its_name(self) -> None:
        self.assertIn(PROBE_NAME, ca.PROBES)
        self.assertIs(ca.PROBES[PROBE_NAME],
                      ca._probe_book_does_not_oscillate_between_opportunities)

    def test_the_probe_declares_the_criterion_in_a_field(self) -> None:
        self.assertEqual(
            CRITERION,
            ca._probe_book_does_not_oscillate_between_opportunities.s49_criterion)

    def test_the_declaration_is_visible_through_the_registry_reader(self) -> None:
        """Читатель реестра возвращает СПИСОК: столкновение объявлений он не прячет."""
        self.assertEqual([PROBE_NAME],
                         ca.probes_by_s49_criterion().get(CRITERION))

    def test_the_report_derives_its_declaration_from_the_constant(self) -> None:
        """У строки объявления ОДНО место: доклад ПРОИСХОДИТ от константы.

        Проверяется происхождением, а не тождеством объектов: `assertIs` на
        строку доказательством не является — компилятор склеивает равные
        константы, и раздвоённый литерал прошёл бы такую проверку молча
        (измерено мутацией цикла #726). Обе двери доклада — измеренная и
        отказная — обязаны последовать за подменой.
        """
        self.scene_never_returns()
        other = "§49 Anti-churn — подменённое объявление"
        with patch.object(boc, "CRITERION", other):
            self.assertEqual(other, self.census()["criterion"])
            refusal = boc.run_census(self.data_dir / "нет-такого-каталога",
                                     now=self.now)
        self.assertFalse(refusal["measured"])
        self.assertEqual(other, refusal["criterion"])

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
            "_rollup_for_anti_churn_probe",
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
