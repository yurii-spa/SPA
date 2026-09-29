"""ADR-510 — критерий §49 `Risk` приказа CIO получает МАШИННУЮ мерку.

Почему этот файл существует
---------------------------
Перепись связывающих потолков (`spa_core/monitoring/policy_binding_census.py`,
цикл #705) меряет критерий владельца «Risk Policy невозможно обойти» с сентября:
её артефакт пишется в такте и свеж (замер 29.09 — 3,1 ч при объявленном пределе
26 ч). А сводный замер §49 (`scripts/cio_acceptance_rollup.py`) про этот критерий
отвечал

    «машинной пробы, объявившей себя мерой этого критерия, в реестре НЕТ —
     вердикт сегодня взять неоткуда»

потому что запись «этот прибор есть мера этого критерия» лежала ПРОЗОЙ в заметке
`architecture/manifest.json`, а сводку читает машина (ADR-504, ADR-506). Заказ
владельца G96 п. 1: следующий `TRANSCRIPTION` — по образцу `Economics` (ADR-507) и
`Persistence` (ADR-508), ТОЖЕ по одному и со своим контролем в обе стороны.

Что здесь закреплено, и в ОБЕ стороны
-------------------------------------
* проба `risk_policy_unbypassable_in_executed_states` зелена на целом контуре и
  красна на КАЖДОМ порванном звене — с названным звеном;
* три породы вреда дают `not_satisfied` каждая сама по себе: нарушенный потолок,
  нарушенный потолок неизмеренного возраста и вердикт, ЗАВИСЯЩИЙ от того, какую
  копию ярлыка тира прочесть (потолок обходят ярлыком, а не доводом);
* `WARNING` прибора (сегодня чисто, но находка в истории и/или спор копий)
  переносится в `not_satisfied`, а не в «выполнено»: тишина не есть доказательство;
* **книга, стоящая сегодня, не та, которую перепись судила ⇒ `unmeasured`** —
  вопрос свежести адресован `current_positions.json`, а НЕ журналу ходов: ходы
  бывают не каждый день (замер 29.09 — последний 18 дн назад), и спрашивать
  возраст у журнала значило бы объявить спокойную неделю протухшей (урок ADR-508
  применён к другому предмету и дал ДРУГОЙ адрес);
* прибор, не объявивший себя мерой ``§49 `Risk` ``, ⇒ `unmeasured`; и якорь
  читается как НАЧАЛО строки, а не как вхождение подстроки (ADR-333);
* неизвестный статус прибора ⇒ `unmeasured` (fail-CLOSED), а не `satisfied`;
* `repo_root`, `data_dir` и `now` ДОХОДЯТ до пробы и до прибора — ВСЕ двери, а не
  одна («половина инъекции», `.claude/rules/deployment.md`);
* объявление `s49_criterion` указывает В НАСЕЛЕНИЕ §49, прочитанное из самой
  карточки приказа, а не мимо него.

Порядок контроля НЕ произволен: сначала доказывается, что фикстуры дают ИМЕННО те
породы (`TestFixturesReproduceTheMeasuredKinds`), и только потом — что проба на них
отвечает. Без первого шага «красно на порванном звене» тавтологично: красным может
быть что угодно, включая сцену, которая ничего не воспроизводит (требование G95 п. 1).

Часы — вход: якорь вычисляется ВНУТРИ теста (не на импорте — ADR-348) и подаётся и
в фикстуры, и в пробу. Литеральных дат в файле нет вовсе: дата коммита сцены с
историей тоже отсчитывается от якоря. Имя ветки одноразового репозитория объявлено
`git init -b` (`.claude/rules/deployment.md`, раздел про git-окружение). Сеть не
трогается, живое `data/` не читается: журналы пишутся в одноразовый каталог.
"""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import policy_binding_census as pbc
from spa_core.tests._freshness import now_utc

#: Имя пробы в реестре. Проверяется как ИМЯ (равенство), не как подстрока — ADR-333.
PROBE_NAME = "risk_policy_unbypassable_in_executed_states"
#: Критерий §49, мерой которого проба себя объявляет.
CRITERION = "Risk"

#: Книга сцены. Число одно на весь файл, доли считаются от него.
CAPITAL = 100_000.0
#: Ключи, тир которых ВСЕ пять копий ярлыка называют одинаково (замер 29.09).
AGREED_T1 = "aave_v3"
AGREED_T1_OTHER = "compound_v3"
#: Ключ, копии которого СПОРЯТ о тире (`ADAPTER_METADATA` зовёт его T1,
#: реестр — T2). Это не выдумка сцены, а живое состояние репозитория, ради
#: которого прибор и написан.
DISPUTED = "morpho_steakhouse"
#: Ключа нет ни в одной копии — тир не назван никем.
UNNAMED = "нет-такого-протокола"

#: Имя ветки одноразового репозитория. Объявляется ЯВНО: `init.defaultBranch`
#: хоста дал бы `main` на Маке и `master` на `ubuntu-latest`.
SCENE_BRANCH = "main"


class _ProbeBase(unittest.TestCase):
    """Одноразовые каталоги: журнал ходов, стоящая книга и (по нужде) история."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        self._root = TemporaryDirectory()
        self.addCleanup(self._root.cleanup)
        # Дерево БЕЗ истории по умолчанию: поверхностный/не-git корень — честный
        # третий исход прибора, и сцена с историей заводится отдельно.
        self.repo_root = Path(self._root.name)
        # Якорь считается здесь, а не на импорте: анкер времени, вычисленный при
        # сборе тестов, краснеет от ДЛИТЕЛЬНОСТИ прогона (ADR-348).
        self.now = now_utc()

    # ── материал ────────────────────────────────────────────────────────────

    def _move(self, allocation: dict, *, days_ago: int, trade_id: str) -> dict:
        return {"trade_id": trade_id,
                "ts": (self.now - timedelta(days=days_ago)).isoformat(),
                "capital": CAPITAL,
                "to_allocation": dict(allocation)}

    def _write(self, allocations: list, *, book: dict | None = None,
               book_age_days: float = 0.0, write_book: bool = True) -> None:
        """Журнал ходов и книга, которая «стои́т сегодня».

        По умолчанию книга РАВНА последнему исполненному состоянию — то есть
        целый контур. Сцены расхождения задают `book` явно.
        """
        moves = [self._move(a, days_ago=len(allocations) - i, trade_id=f"T{i + 1}")
                 for i, a in enumerate(allocations)]
        (self.data_dir / "trades.json").write_text(json.dumps(moves), encoding="utf-8")
        if not write_book:
            return
        positions = dict(allocations[-1]) if book is None else dict(book)
        stamp = (self.now - timedelta(days=book_age_days)).isoformat()
        (self.data_dir / "current_positions.json").write_text(
            json.dumps({"generated_at": stamp, "positions": positions}),
            encoding="utf-8")

    def _root_with_history(self) -> Path:
        """Дерево, у которого дата рождения порога ИЗМЕРИМА.

        Нужно ровно для одной пары: тот же нарушенный потолок читается как
        `violation`, когда история есть, и как `violation_rule_birth_unmeasured`,
        когда её нет. Дата коммита отсчитывается от якоря теста, а не вписана.
        """
        root = Path(TemporaryDirectory().name)
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(root)],
                                               capture_output=True))
        (root / "spa_core" / "risk").mkdir(parents=True)
        (root / "spa_core" / "risk" / "policy.py").write_text(
            "\n".join(f"{field} = 0.0" for field in pbc.THRESHOLD_FIELDS),
            encoding="utf-8")
        born = (self.now - timedelta(days=200)).isoformat()
        env = dict(os.environ, GIT_AUTHOR_DATE=born, GIT_COMMITTER_DATE=born,
                   GIT_AUTHOR_NAME="scene", GIT_AUTHOR_EMAIL="scene@example.invalid",
                   GIT_COMMITTER_NAME="scene",
                   GIT_COMMITTER_EMAIL="scene@example.invalid")
        for args in (["git", "init", "-b", SCENE_BRANCH], ["git", "add", "-A"],
                     ["git", "commit", "-m", "policy"]):
            done = subprocess.run(args, cwd=str(root), capture_output=True,
                                  text=True, env=env)
            if done.returncode != 0:
                self.fail(f"сцену с историей собрать не удалось ({' '.join(args)}): "
                          f"{(done.stderr or '').strip()[:200]} — предпосылка НЕ "
                          f"ОБЕСПЕЧЕНА, и молчать об этом нельзя")
        return root

    # ── сцены ───────────────────────────────────────────────────────────────

    def scene_clean(self) -> None:
        """Книга внутри всех потолков, ярлыки не спорят."""
        self._write([{AGREED_T1: 30_000.0, AGREED_T1_OTHER: 30_000.0}])

    def scene_over_concentration(self) -> None:
        """60 % книги в одном протоколе при потолке T1 40 %."""
        self._write([{AGREED_T1: 60_000.0}])

    def scene_label_dependent(self) -> None:
        """30 % у спорного ключа: внутри потолка T1, вдвое сверх потолка T2.

        Именно здесь «нарушен ли потолок» НЕ ОПРЕДЕЛЁН — и это порода, ради
        которой прибор написан: потолок обходят ярлыком, а не доводом.
        """
        self._write([{DISPUTED: 30_000.0, AGREED_T1: 20_000.0}])

    def scene_dispute_only_in_registry(self) -> None:
        """Сегодня чисто, но копии ярлыка спорят — у прибора это `WARNING`."""
        self._write([{DISPUTED: 10_000.0, AGREED_T1: 10_000.0}])

    def scene_tier_unnamed(self) -> None:
        """Тир не назван ни одной копией: потолок выбрать нечем."""
        self._write([{UNNAMED: 10_000.0}])

    def scene_no_journal(self) -> None:
        """Журнала ходов нет вовсе: переигрывать нечего."""
        (self.data_dir / "current_positions.json").write_text(
            json.dumps({"generated_at": self.now.isoformat(), "positions": {}}),
            encoding="utf-8")

    def scene_stale_standing_book(self) -> None:
        """Тот же чистый материал, но книга снята давно."""
        self._write([{AGREED_T1: 30_000.0, AGREED_T1_OTHER: 30_000.0}],
                    book_age_days=ca.STANDING_BOOK_MAX_AGE_D + 1)

    def scene_book_moved_on(self) -> None:
        """Перепись судит T1, а сегодня стои́т другая книга."""
        self._write([{AGREED_T1: 30_000.0, AGREED_T1_OTHER: 30_000.0}],
                    book={AGREED_T1: 30_000.0, DISPUTED: 30_000.0})

    def scene_book_same_keys_other_money(self) -> None:
        """Ключи те же, суммы разъехались — это ДРУГАЯ книга."""
        self._write([{AGREED_T1: 30_000.0, AGREED_T1_OTHER: 30_000.0}],
                    book={AGREED_T1: 45_000.0, AGREED_T1_OTHER: 15_000.0})

    def scene_clean_after_an_earlier_move(self) -> None:
        """Два исполненных состояния; сегодня стои́т ПОСЛЕДНЕЕ.

        Сцена существует затем, чтобы «настоящее» нельзя было взять первым
        попавшимся ходом: состав первого и последнего РАЗНЫЙ.
        """
        self._write([{AGREED_T1: 20_000.0},
                     {AGREED_T1: 30_000.0, AGREED_T1_OTHER: 30_000.0}])

    def scene_book_written_in_another_shape(self) -> None:
        """Та же книга, записанная иначе: нулевая нога и лишний знак после запятой."""
        self._write([{AGREED_T1: 30_000.0, AGREED_T1_OTHER: 30_000.0}],
                    book={AGREED_T1: 30_000.004, AGREED_T1_OTHER: 30_000.0,
                          DISPUTED: 0.0})

    def scene_no_standing_book(self) -> None:
        """Журнал есть, книги сегодняшнего дня нет."""
        self._write([{AGREED_T1: 30_000.0}], write_book=False)

    # ── приборы ─────────────────────────────────────────────────────────────

    def census(self, **kw) -> dict:
        root = kw.pop("root", self.repo_root)
        return pbc.run_census(root, self.data_dir, now=kw.pop("now", self.now), **kw)

    def probe(self, **kw):
        root = kw.pop("repo_root", self.repo_root)
        data = kw.pop("data_dir", self.data_dir)
        return ca._probe_risk_policy_unbypassable_in_executed_states(
            None, now=kw.pop("now", self.now), data_dir=str(data),
            repo_root=str(root), **kw)


class TestFixturesReproduceTheMeasuredKinds(_ProbeBase):
    """Сначала — что фикстуры дают ИМЕННО те породы. Иначе контроль ниже тавтологичен."""

    def test_clean_scene_is_ok_for_the_instrument(self) -> None:
        self.scene_clean()
        report = self.census()
        self.assertEqual(pbc.STATUS_OK, report["status"])
        self.assertEqual({"clean": 1}, report["counts"])

    def test_over_concentration_without_history_is_birth_unmeasured(self) -> None:
        """Порог нарушен, но существовал ли он в тот день — НЕ ИЗМЕРЕНО.

        Это не придирка к сцене: именно так прибор обязан читать дерево без
        истории, и смешать это с «нарушения не было» значило бы вернуть тот
        подлог, против которого он написан.
        """
        self.scene_over_concentration()
        report = self.census()
        self.assertEqual(pbc.STATUS_CRITICAL, report["status"])
        self.assertEqual("violation_rule_birth_unmeasured",
                         report["present"]["outcome"])

    def test_the_same_state_with_history_is_a_plain_violation(self) -> None:
        """Предпосылка контроля проводки `repo_root`: история МЕНЯЕТ породу."""
        self.scene_over_concentration()
        report = self.census(root=self._root_with_history())
        self.assertEqual("violation", report["present"]["outcome"])
        self.assertEqual(1, report["counts"].get("violation"))

    def test_label_dependent_scene_is_undetermined(self) -> None:
        self.scene_label_dependent()
        report = self.census()
        self.assertEqual("undetermined", report["present"]["outcome"])
        self.assertEqual(pbc.STATUS_CRITICAL, report["status"])
        self.assertIn(DISPUTED, report["label_disagreement"])

    def test_dispute_without_a_bad_state_is_only_a_warning(self) -> None:
        self.scene_dispute_only_in_registry()
        report = self.census()
        self.assertEqual("clean", report["present"]["outcome"])
        self.assertEqual(pbc.STATUS_WARNING, report["status"])
        self.assertIn(DISPUTED, report["label_disagreement"])

    def test_unnamed_tier_scene_is_unmeasured_for_the_instrument(self) -> None:
        self.scene_tier_unnamed()
        report = self.census()
        self.assertEqual("unmeasured", report["present"]["outcome"])
        self.assertEqual([UNNAMED], report["tier_unknown"])

    def test_stale_book_scene_is_green_for_the_instrument(self) -> None:
        """Предпосылка положительного контроля на СВОЙ вопрос пробы.

        Без этого утверждения тест «протухшая книга ⇒ unmeasured» ничего не
        стои́т: он был бы зелен и в случае, когда прибор на таком материале сам
        отказывает. Прибор про `current_positions.json` не знает ВООБЩЕ — и
        именно поэтому вопрос задаёт проба.
        """
        self.scene_stale_standing_book()
        self.assertEqual(pbc.STATUS_OK, self.census()["status"])

    def test_moved_on_book_scene_is_green_for_the_instrument_too(self) -> None:
        self.scene_book_moved_on()
        self.assertEqual(pbc.STATUS_OK, self.census()["status"])

    def test_the_instrument_publishes_the_composition_it_judged(self) -> None:
        """Состав настоящего состояния — ПОЛЕ отчёта, а не догадка читателя."""
        self.scene_clean()
        self.assertEqual({AGREED_T1: 30_000.0, AGREED_T1_OTHER: 30_000.0},
                         self.census()["present"]["positions"])


class TestProbeTransfersTheVerdict(_ProbeBase):
    """Целый контур: вердикт прибора доходит до вердикта критерия без своих порогов."""

    def test_clean_book_is_satisfied(self) -> None:
        self.scene_clean()
        verdict, detail = self.probe()
        self.assertEqual(ca.SATISFIED, verdict)
        self.assertIn("не нарушало потолка", detail)

    def test_the_judged_state_is_the_LAST_one_not_the_first(self) -> None:
        """«Настоящее» — последнее исполненное состояние, а не первое.

        Взять первый ход вердикт бы не изменило только на одноходовой сцене;
        здесь состав первого и последнего разный, и подмена стала бы отказом
        «сегодня стои́т другая книга» на исправном контуре.
        """
        self.scene_clean_after_an_earlier_move()
        self.assertEqual(ca.SATISFIED, self.probe()[0])

    def test_the_standing_book_is_normalised_by_the_instruments_own_rule(self) -> None:
        """Что считать позицией — правило ПРИБОРА, и второй его копии здесь нет.

        Нулевая нога и лишний знак после запятой книгу не меняют: обе стороны
        проходят ту же нормализацию, которой прибор пользовался, когда судил.
        Сравнение «как записано» объявило бы ту же книгу другой.
        """
        self.scene_book_written_in_another_shape()
        self.assertEqual(ca.SATISFIED, self.probe()[0])

    def test_violation_is_not_satisfied(self) -> None:
        self.scene_over_concentration()
        verdict, detail = self.probe(repo_root=self._root_with_history())
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("нарушений 1", detail)

    def test_violation_of_unmeasured_age_is_also_not_satisfied(self) -> None:
        """Порода мягче, вердикт тот же: «не знаю, был ли потолок» — не «чисто»."""
        self.scene_over_concentration()
        verdict, detail = self.probe()
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("нарушен-но-срок-потолка-не-измерен 1", detail)

    def test_label_dependent_state_is_not_satisfied(self) -> None:
        """Ни строки риск-логики не тронуто, а потолок уже не определён."""
        self.scene_label_dependent()
        verdict, detail = self.probe()
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("зависит от копии ярлыка у 1", detail)
        self.assertIn(DISPUTED, detail)

    def test_warning_is_not_satisfied_because_silence_is_not_proof(self) -> None:
        self.scene_dispute_only_in_registry()
        verdict, detail = self.probe()
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("НЕ «такого не бывало»", detail)

    def test_unnamed_tier_is_not_satisfied_not_clean(self) -> None:
        self.scene_tier_unnamed()
        verdict, detail = self.probe()
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("тир неизвестен у 1", detail)

    def test_the_probe_names_what_it_does_not_prove(self) -> None:
        """Односторонность доказательства обязана быть НАЗВАНА в каждом вердикте."""
        for scene in (self.scene_clean, self.scene_dispute_only_in_registry):
            with self.subTest(scene=scene.__name__):
                scene()
                detail = self.probe()[1]
                self.assertIn("доказательство одностороннее", detail)
                self.assertIn("третий исход состояний", detail)
                # Чьи пороги решили вердикт — тоже названо: своих у пробы нет.
                self.assertIn("потолки из RiskConfig", detail)


class TestEveryBrokenLinkIsUnmeasuredNotAVerdict(_ProbeBase):
    """Каждое порванное звено — с названным звеном, и ни одно не даёт `satisfied`."""

    def test_missing_journal_is_unmeasured(self) -> None:
        self.scene_no_journal()
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("trades.json не найден", detail)

    def test_missing_standing_book_is_unmeasured(self) -> None:
        self.scene_no_standing_book()
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не прочитана", detail)
        self.assertIn(ca.STANDING_BOOK_FILE, detail)

    def test_stale_standing_book_is_unmeasured_although_the_instrument_says_ok(self) -> None:
        self.scene_stale_standing_book()
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("стоящая книга протухла", detail)

    def test_standing_book_without_a_stamp_is_unmeasured(self) -> None:
        self.scene_clean()
        path = self.data_dir / ca.STANDING_BOOK_FILE
        doc = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps({"positions": doc["positions"]}), encoding="utf-8")
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        # Фраза проверяется ИМЕННО этой ветки: общая часть трёх пояснений
        # («НЕ ИЗМЕРЕН») не различала бы снятый вопрос от нечитаемой даты.
        self.assertIn("нет отметки `generated_at`", detail)

    def test_standing_book_stamp_that_is_not_a_date_is_unmeasured(self) -> None:
        self.scene_clean()
        path = self.data_dir / ca.STANDING_BOOK_FILE
        doc = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps({**doc, "generated_at": "не-дата"}), encoding="utf-8")
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не разобрана как дата", detail)

    def test_a_book_that_moved_on_is_unmeasured_never_satisfied(self) -> None:
        """Самый дорогой контроль: иначе `satisfied` относилось бы к чужой книге."""
        self.scene_book_moved_on()
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("сегодня стои́т ДРУГАЯ книга", detail)
        self.assertIn(DISPUTED, detail)

    def test_same_keys_with_other_money_is_also_a_different_book(self) -> None:
        """Совпадения ИМЁН мало: доли решают, нарушен ли потолок."""
        self.scene_book_same_keys_other_money()
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("разошлись суммой", detail)
        self.assertIn(AGREED_T1, detail)

    def test_report_without_the_judged_composition_is_unmeasured(self) -> None:
        self.scene_clean()
        real = pbc.run_census

        def stripped(*a, **kw):
            report = real(*a, **kw)
            report["present"] = {k: v for k, v in report["present"].items()
                                 if k != "positions"}
            return report

        with patch.object(pbc, "run_census", stripped):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не назвала СОСТАВ", detail)

    def test_report_without_counts_is_unmeasured_not_six_zeroes(self) -> None:
        self.scene_clean()
        real = pbc.run_census

        def stripped(*a, **kw):
            report = real(*a, **kw)
            report.pop("counts")
            return report

        with patch.object(pbc, "run_census", stripped):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("сводки `counts`", detail)

    def test_report_that_declares_itself_unmeasured_is_unmeasured(self) -> None:
        self.scene_clean()
        real = pbc.run_census

        def refused(*a, **kw):
            return {**real(*a, **kw), "measured": False, "reason": "дверь закрыта"}

        with patch.object(pbc, "run_census", refused):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("отказалась мерить", detail)
        self.assertIn("дверь закрыта", detail)

    def test_instrument_that_does_not_declare_this_criterion_is_unmeasured(self) -> None:
        self.scene_clean()
        with patch.object(pbc, "CRITERION", "§49 Anti-churn — чужой критерий"):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не объявляет себя мерой", detail)

    def test_the_anchor_is_read_as_a_prefix_not_as_a_substring(self) -> None:
        """ADR-333: объявление, где якорь стои́т где-то внутри, не есть привязка."""
        self.scene_clean()
        with patch.object(pbc, "CRITERION",
                          "перепись потолков; рядом упомянут §49 `Risk`"):
            self.assertEqual(ca.UNMEASURED, self.probe()[0])

    def test_instrument_without_a_declaration_at_all_is_unmeasured(self) -> None:
        self.scene_clean()
        with patch.object(pbc, "CRITERION", None):
            self.assertEqual(ca.UNMEASURED, self.probe()[0])

    def test_unknown_instrument_status_is_unmeasured_fail_closed(self) -> None:
        self.scene_clean()
        real = pbc.run_census

        def weird(*a, **kw):
            return {**real(*a, **kw), "status": "ЧТО-ТО НОВОЕ"}

        with patch.object(pbc, "run_census", weird):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не переносится в вердикт", detail)

    def test_instrument_that_raises_is_unmeasured_with_the_cause_named(self) -> None:
        self.scene_clean()

        def boom(*a, **kw):
            raise RuntimeError("дверь закрыта")

        with patch.object(pbc, "run_census", boom):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("RuntimeError", detail)
        self.assertIn("дверь закрыта", detail)

    def test_instrument_that_cannot_be_imported_is_unmeasured(self) -> None:
        self.scene_clean()
        with patch.object(ca, "POLICY_BINDING_MODULE",
                          "spa_core.monitoring.нет_такого_модуля"):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не загружена", detail)


class TestTreeAndClockAreInputsNotEnvironment(_ProbeBase):
    """ВСЕ двери к окружению закрыты, а не одна («половина инъекции»)."""

    def test_the_registry_declares_both_tree_inputs(self) -> None:
        self.assertEqual(("repo_root", "data_dir"), ca.probe_tree_inputs(PROBE_NAME))

    def test_data_dir_reaches_the_probes_own_question(self) -> None:
        """Отказ пробы НАЗЫВАЕТ наш путь, а не путь своего дерева."""
        self.scene_no_standing_book()
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn(str(self.data_dir), detail)

    def test_data_dir_reaches_the_instrument_too_not_only_the_guard(self) -> None:
        """Вторая дверь того же входа: каталог доходит и до ПРИБОРА.

        Проба задаёт свой вопрос `current_positions.json`, а перепись читает
        журнал ходов. Закрыть одну дверь и оставить другую — ровно «половина
        инъекции»: проба отвечала бы о нашем каталоге, а прибор внутри неё — о
        `data/` своего дерева, и вердикт о чужом материале выдавался бы за
        вердикт о нашем.
        """
        self.scene_clean()
        self.assertEqual(ca.SATISFIED, self.probe()[0])
        with TemporaryDirectory() as other:
            verdict, detail = self.probe(data_dir=other)
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("trades.json не найден", detail)

    def test_repo_root_reaches_the_instrument_not_only_the_probe(self) -> None:
        """Дерево решает, ИЗМЕРИМ ли возраст потолка, — и это видно в пояснении.

        Вердикт критерия здесь измениться НЕ МОЖЕТ по построению: обе породы
        переносятся в `not_satisfied`. Поэтому контроль стои́т на ПОЯСНЕНИИ —
        молчаливая подстановка своего дерева сделала бы числа в нём неверными,
        не тронув вердикта. Ровно та половина инъекции, из-за которой класс и
        написан.
        """
        self.scene_over_concentration()
        blind = self.probe()[1]
        with_history = self.probe(repo_root=self._root_with_history())[1]
        self.assertIn("нарушен-но-срок-потолка-не-измерен 1", blind)
        self.assertIn("нарушений 1", with_history)
        self.assertNotEqual(blind, with_history)

    def test_clock_reaches_the_instrument_too_not_only_the_probe(self) -> None:
        """Часы доходят и ДО прибора — измерено по его отметке, а не по наличию входа.

        Вердикт переписи от часов не зависит НИ В ОДНОЙ ветви: породу состояния
        решают доли книги и дата рождения потолка, и это сказано здесь вслух,
        чтобы никто не искал в контроле того, чего в предмете нет. Зависит от
        часов ОТМЕТКА отчёта — то самое `generated_at`, которое уходит в артефакт
        и по которому потом судят о его свежести. Уронить сюда стенные часы —
        ровно «половина инъекции»: вердикт цел, а возраст артефакта соврал.

        Мера — ИСХОД (отметка в отчёте), а не наличие параметра у вызова: «есть
        ли аргумент» отвечает на свой вопрос, а не на нужный
        (`.claude/rules/deployment.md`).
        """
        self.scene_clean()
        seen: list = []
        real = pbc.run_census

        def spy(*a, **kw):
            report = real(*a, **kw)
            seen.append(report)
            return report

        with patch.object(pbc, "run_census", spy):
            self.assertEqual(ca.SATISFIED, self.probe()[0])
        self.assertEqual(1, len(seen), "перепись не была позвана ни разу")
        self.assertEqual(self.now.isoformat(), seen[0]["generated_at"])

    def test_clock_reaches_the_probes_own_freshness_question(self) -> None:
        """Сдвиг часов вперёд переводит свежую книгу в протухшую — вердикт МЕНЯЕТСЯ."""
        self.scene_clean()
        self.assertEqual(ca.SATISFIED, self.probe()[0])
        later = self.probe(now=self.now + timedelta(days=ca.STANDING_BOOK_MAX_AGE_D + 1))
        self.assertEqual(ca.UNMEASURED, later[0])
        self.assertIn("протухла", later[1])


class TestTheDeclarationItself(_ProbeBase):
    """Привязка объявлена ПОЛЕМ и указывает в население §49, а не мимо него."""

    def test_the_probe_is_registered_under_its_name(self) -> None:
        self.assertIn(PROBE_NAME, ca.PROBES)
        self.assertIs(ca.PROBES[PROBE_NAME],
                      ca._probe_risk_policy_unbypassable_in_executed_states)

    def test_the_probe_declares_the_criterion_in_a_field(self) -> None:
        self.assertEqual(
            CRITERION,
            ca._probe_risk_policy_unbypassable_in_executed_states.s49_criterion)

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
        self.scene_clean()
        other = "§49 `Risk` — подменённое объявление"
        with patch.object(pbc, "CRITERION", other):
            self.assertEqual(other, self.census()["criterion"])
            # Каталога нет ⇒ ступень отказывает ДО прогона и ничего не пишет:
            # отказная дверь доклада проверяется, не трогая ни одного файла.
            refusal = pbc.run(root=str(self.repo_root),
                              data_dir=str(self.data_dir / "нет-такого-каталога"),
                              now=self.now)
        self.assertFalse(refusal["measured"])
        self.assertEqual(other, refusal["doc"]["criterion"])

    def test_the_criterion_name_exists_in_the_live_order(self) -> None:
        """Объявление указывает В §49 карточки приказа, а не мимо населения.

        Население читается из САМОЙ карточки приказа тем же разбором, которым его
        читает сводка, — не из списка рядом. Карточки в дереве нет ⇒ падать ГРОМКО:
        «сверить не с чем» никогда не выдаётся за «сверено».
        """
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        spec = importlib.util.spec_from_file_location(
            "_rollup_for_risk_probe",
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
