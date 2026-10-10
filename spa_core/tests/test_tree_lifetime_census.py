"""Батарея прибора срока годности объявления владения (заказ G112 п. 2, ADR-538).

**Почему здесь нет ни одной литеральной даты «из календаря».** Предмет прибора —
СРОКИ, поэтому фикстура с настоящей датой начала бы падать от того, что сдвинулся
календарь (`.claude/rules/deployment.md`, раздел про время). Все отметки построены от
ОДНОГО якоря сцены через `timedelta`, а момент, время загрузки, живость каталога и его
рождение переданы прибору ВХОДОМ. Якорь — не дата хоста, а константа сцены.

**Положительный контроль у КАЖДОГО вердикта в обе стороны.** Мало проверить, что прибор
называет 27 молчаливых потерь на живом хосте: такой тест зелен и на приборе, который
печатает «молчаливых потерь нет» всегда. Поэтому каждая сцена идёт парой — состояние,
в котором вердикт обязан прозвучать, и соседнее, в котором он обязан СМЕНИТЬСЯ.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import tree_lifetime_census as tlc

# FROZEN-DATE-OK: injected-clock — момент идёт параметром `now=`, время загрузки
# `boot_probe=`, живость каталога `exists=`, рождение `birth_probe=`, чтение объявления
# уборки `sweep_read=`; ВСЕ отметки сцены построены от якоря `ANCHOR` через `timedelta`,
# своих литеральных дат в файле нет. Претензия сверяется AST-сторожем
# `test_injected_clock_claim`, а не принимается на слово.

#: Якорь сцены. Не дата хоста и не «сегодня» — константа, от которой строятся ВСЕ
#: отметки сцены. Сдвиг календаря на вердикты этого файла не влияет по построению.
ANCHOR = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
TS = "%Y-%m-%dT%H:%M:%SZ"


def at(**kw) -> str:
    """Отметка сцены: якорь ± смещение. Литеральных дат в вызовах нет."""
    return (ANCHOR + timedelta(**kw)).strftime(TS)


class Scene:
    """Одноразовая сцена: каталог данных с журналом объявлений и журналом квитанций."""

    def __init__(self, tmp: str):
        self.data = Path(tmp) / "data"
        self.data.mkdir(parents=True, exist_ok=True)
        self.root = Path(tmp)

    def journal(self, rows) -> "Scene":
        (self.data / tlc.JOURNAL_NAME).write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8")
        return self

    def ledger(self, rows) -> "Scene":
        (self.data / tlc.REAP_LEDGER_NAME).write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8")
        return self

    def build(self, **kw):
        kw.setdefault("now", ANCHOR + timedelta(hours=300))
        kw.setdefault("boot_probe", lambda: (ANCHOR - timedelta(hours=1)).timestamp())
        kw.setdefault("exists", lambda p: False)
        kw.setdefault("birth_probe", lambda p: None)
        kw.setdefault("sweep_read", _missing_files)
        return tlc.build_report(self.root, data_dir=self.data, **kw)


def _missing_files(path):
    raise FileNotFoundError(path)


class PopulationFormTests(unittest.TestCase):
    """Население мерится ФОРМОЙ записи, а не именем пути."""

    def test_a_path_that_is_only_ever_a_file_is_not_a_tree(self):
        """Лог-файл в `/tmp` деревом НЕ является — иначе он искажает и счёт, и срок.

        Это не придирка: на живом журнале так попадал `/tmp/c542_full.log`.
        """
        journal = [
            # объявлен САМ путь — это файл, не дерево
            {"ts": at(hours=1), "files": ["/tmp/some_run.log"]},
            # объявлен путь СТРОГО ВНУТРИ — значит `/tmp/spa_tree` каталог
            {"ts": at(hours=2), "files": ["/tmp/spa_tree/spa_core/x.py"]},
        ]
        with TemporaryDirectory() as tmp:
            rep = Scene(tmp).journal(journal).ledger([]).build()
        trees = [r["tree"] for r in rep["survival"]]
        self.assertIn("/tmp/spa_tree", trees)
        self.assertNotIn("/tmp/some_run.log", trees,
                         "путь, встреченный только как объявленный ФАЙЛ, попал в "
                         "население деревьев — счёт и срок жизни искажены")

    def test_cwd_alone_makes_a_tree(self):
        """ОБРАТНЫЙ контроль к предыдущему: `cwd` по построению каталог.

        Без этой пары прошёл бы прибор, который считает деревом только то, внутри чего
        что-то лежало, и терял бы каждое дерево, объявившее лишь свой `cwd`.
        """
        with TemporaryDirectory() as tmp:
            rep = Scene(tmp).journal(
                [{"ts": at(hours=1), "cwd": "/private/tmp/spa_only_cwd"}]).ledger([]).build()
        self.assertEqual(["/tmp/spa_only_cwd"], [r["tree"] for r in rep["survival"]],
                         "дерево, объявившее только cwd, потеряно; и форма /private/tmp "
                         "обязана сводиться к /tmp — это ОДИН каталог")


class CauseOfEndTests(unittest.TestCase):
    """Причина конца дерева: четыре исхода, и они не склеиваются."""

    def _scene(self, tmp):
        journal = [
            {"ts": at(hours=1), "cwd": "/tmp/spa_alive"},
            {"ts": at(hours=2), "cwd": "/tmp/spa_reaped"},
            {"ts": at(hours=3), "cwd": "/tmp/spa_gone_silent"},
            {"ts": at(hours=-50), "cwd": "/tmp/spa_gone_preboot"},
        ]
        ledger = [{"ts": at(hours=20), "worktree": "/private/tmp/spa_reaped"}]
        return Scene(tmp).journal(journal).ledger(ledger)

    def test_four_causes_are_told_apart(self):
        with TemporaryDirectory() as tmp:
            rep = self._scene(tmp).build(exists=lambda p: p == "/tmp/spa_alive",
                                         birth_probe=lambda p: (ANCHOR + timedelta(hours=1)).timestamp())
        cause = {r["tree"]: r["cause"] for r in rep["survival"]}
        self.assertEqual(tlc.CAUSE_ALIVE, cause["/tmp/spa_alive"])
        self.assertEqual(tlc.CAUSE_REAPED, cause["/tmp/spa_reaped"])
        self.assertEqual(tlc.CAUSE_VANISHED_SILENT, cause["/tmp/spa_gone_silent"])
        self.assertEqual(tlc.CAUSE_VANISHED_BOOT, cause["/tmp/spa_gone_preboot"],
                         "дерево, объявленное ДО загрузки, обязано объясняться "
                         "перезагрузкой, а не числиться потерей без следа")

    def test_a_receipt_turns_a_silent_loss_into_a_measured_end(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на звено «квитанция»: добавь её — потеря исчезает.

        Без этой пары «потерь без следа 1» было бы утверждением о приборе, а не о
        хосте: тот же счёт выдал бы прибор, который квитанции не читает ВОВСЕ.
        """
        with TemporaryDirectory() as tmp:
            before = self._scene(tmp).build(exists=lambda p: False)
        with TemporaryDirectory() as tmp:
            scene = self._scene(tmp)
            scene.ledger([{"ts": at(hours=20), "worktree": "/private/tmp/spa_reaped"},
                          {"ts": at(hours=25), "worktree": "/tmp/spa_gone_silent"}])
            after = scene.build(exists=lambda p: False)
        # В обеих сценах `exists` отвечает «нет» всем, поэтому и `spa_alive` считается
        # исчезнувшим: двойка здесь ОЖИДАЕМА, и важна РАЗНОСТЬ, а не абсолют.
        self.assertEqual(2, before["silent_loss"]["trees"])
        self.assertEqual(1, after["silent_loss"]["trees"],
                         "квитанция не сняла дерево со счёта потерь без следа — счёт "
                         "не зависит от квитанций, то есть не про них")

    def test_boot_unmeasured_does_not_become_explained_by_boot(self):
        """Третий исход у двери загрузки: «не измерено» не есть «объяснено загрузкой».

        Прибор без времени загрузки не вправе ни оправдать исчезновение, ни умолчать:
        дерево остаётся потерей, а ПРИЧИНА называет, что перезагрузка НЕ ПРОВЕРЕНА.
        """
        with TemporaryDirectory() as tmp:
            rep = self._scene(tmp).build(boot_probe=lambda: None, exists=lambda p: False)
        causes = {r["tree"]: r["cause"] for r in rep["survival"]}
        self.assertEqual(tlc.CAUSE_VANISHED_SILENT, causes["/tmp/spa_gone_preboot"],
                         "без времени загрузки исчезновение объявлено объяснённым — "
                         "прибор оправдал потерю наблюдением, которого у него нет")
        row = next(r for r in rep["survival"] if r["tree"] == "/tmp/spa_gone_preboot")
        self.assertIn("НЕ ИЗМЕРЕНО", row["reason"])
        self.assertIsNotNone(rep["observation"]["boot_unmeasured_reason"])
        self.assertFalse(rep["silent_loss"]["measured"],
                         "такт в сутки посчитан без аптайма — делить было нечем")


class SurvivalKindTests(unittest.TestCase):
    """Род числа: точное рождение против нижней границы, и цензура названа."""

    def test_live_tree_age_is_marked_censored(self):
        with TemporaryDirectory() as tmp:
            rep = Scene(tmp).journal([{"ts": at(hours=1), "cwd": "/tmp/spa_alive"}]).ledger([]).build(
                exists=lambda p: True,
                birth_probe=lambda p: (ANCHOR + timedelta(hours=10)).timestamp(),
                now=ANCHOR + timedelta(hours=40))
        row = rep["survival"][0]
        self.assertEqual(30.0, row["survived_hours"])
        self.assertTrue(row["censored"], "возраст живого дерева выдан за срок жизни")
        self.assertFalse(row["birth_is_upper_bound"],
                         "st_birthtime есть ТОЧНОЕ рождение, границей его звать нельзя")

    def test_reaped_tree_lifetime_is_a_lower_bound(self):
        with TemporaryDirectory() as tmp:
            rep = Scene(tmp).journal([{"ts": at(hours=5), "cwd": "/tmp/spa_r"}]).ledger(
                [{"ts": at(hours=25), "worktree": "/tmp/spa_r"}]).build(exists=lambda p: False)
        row = rep["survival"][0]
        self.assertEqual(20.0, row["survived_hours"])
        self.assertFalse(row["censored"])
        self.assertTrue(row["birth_is_upper_bound"],
                        "рождение взято из первого ОБЪЯВЛЕНИЯ — дерево существовало "
                        "раньше, поэтому срок жизни есть нижняя граница")

    def test_live_tree_without_birth_is_unmeasured_not_zero(self):
        """Рождение не прочитано ⇒ `None`, а не ноль часов (инв. #17)."""
        with TemporaryDirectory() as tmp:
            rep = Scene(tmp).journal([{"ts": at(hours=1), "cwd": "/tmp/spa_alive"}]).ledger([]).build(
                exists=lambda p: True, birth_probe=lambda p: None)
        row = rep["survival"][0]
        self.assertFalse(row["measured"])
        self.assertIsNone(row["survived_hours"], "нечитаемое рождение дало ЧИСЛО")


class RemainingWindowTests(unittest.TestCase):
    """«Сколько осталось» — третий исход, и каждая причина обязана быть измерена."""

    def _rows(self, longest, uptime):
        return [{"tree": "/tmp/spa_x", "measured": True, "cause": tlc.CAUSE_REAPED,
                 "survived_hours": longest, "censored": False}], uptime

    def test_never_returns_a_number(self):
        rows, uptime = self._rows(260.0, 261.0)
        out = tlc.remaining_window(rows, {"measured": True, "outcome": "mechanism_absent"}, uptime)
        self.assertFalse(out["measured"])
        self.assertIsNone(out["hours"], "остаток назван числом — ровно то, что заказ запретил")

    def test_all_three_reasons_are_named_on_the_live_shape(self):
        rows, uptime = self._rows(260.0, 261.0)
        out = tlc.remaining_window(rows, {"measured": True, "outcome": "mechanism_absent"}, uptime)
        named = {r["reason"] for r in out["blocking_reasons"]}
        self.assertEqual({tlc.REASON_CEILING, tlc.REASON_NO_TIMER, tlc.REASON_SELECTION}, named)
        self.assertTrue(all(r["measured"] for r in out["blocking_reasons"]))

    def test_ceiling_reason_disappears_when_observation_outlives_uptime(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на звено «потолок»: причина обязана УЙТИ.

        Без этой пары `ceiling_is_uptime` был бы вечной строкой, а не замером: тот же
        набор причин выдал бы прибор, который приписывает потолок всегда.
        """
        rows, _ = self._rows(10.0, 1000.0)
        out = tlc.remaining_window(rows, {"measured": True, "outcome": "mechanism_absent"}, 1000.0)
        self.assertNotIn(tlc.REASON_CEILING, {r["reason"] for r in out["blocking_reasons"]},
                         "наблюдение далеко от аптайма, а потолок всё равно назван")

    def test_declared_sweep_removes_the_timer_reason(self):
        """ОБРАТНЫЙ контроль на звено «порог»: объявленная уборка снимает причину."""
        rows, uptime = self._rows(10.0, 1000.0)
        out = tlc.remaining_window(
            rows, {"measured": True, "outcome": "declared",
                   "declarations": ["/etc/periodic.conf: daily_clean_tmps_enable=\"YES\""]}, uptime)
        self.assertNotIn(tlc.REASON_NO_TIMER, {r["reason"] for r in out["blocking_reasons"]})

    def test_selection_reason_disappears_without_complete_observations(self):
        """ОБРАТНЫЙ контроль на звено «отбор»: нет полных наблюдений — нет причины."""
        out = tlc.remaining_window([], {"measured": True, "outcome": "declared",
                                        "declarations": ["x"]}, 1000.0)
        self.assertEqual([], out["blocking_reasons"])
        self.assertIn("НЕ ВЫНЕСЕН", out["says"],
                      "пустой список причин прочитан как зелень — «причин нет» и "
                      "«остаток назван» склеены")

    def test_unreadable_sweep_reason_is_itself_marked_unmeasured(self):
        rows, uptime = self._rows(10.0, 1000.0)
        out = tlc.remaining_window(rows, {"measured": False, "outcome": "unmeasured",
                                          "reason": "права"}, uptime)
        timer = next(r for r in out["blocking_reasons"] if r["reason"] == tlc.REASON_NO_TIMER)
        self.assertFalse(timer["measured"],
                         "причина, которая сама не измерена, выдана за измеренную")


class SweepDoorTests(unittest.TestCase):
    """Дверь объявления системной уборки: четыре исхода, ни один не склеен."""

    def test_mechanism_absent_is_not_absent(self):
        out = tlc.tmp_sweep_declared(("/nope/a.conf", "/nope/b.conf"), read=_missing_files)
        self.assertEqual("mechanism_absent", out["outcome"])
        self.assertTrue(out["measured"])
        self.assertIn("не знает", out["reason"],
                      "«механизма нет» выдано за «уборки нет» — слепота прибора "
                      "объявлена свойством хоста")

    def test_absent_requires_the_files_to_be_read(self):
        out = tlc.tmp_sweep_declared(("/x.conf",), read=lambda p: "# пусто\n")
        self.assertEqual("absent", out["outcome"])
        self.assertTrue(out["measured"])

    def test_declared_is_read_not_guessed(self):
        out = tlc.tmp_sweep_declared(
            ("/x.conf",), read=lambda p: f'{tlc.TMP_SWEEP_KEY}="YES"\n')
        self.assertEqual("declared", out["outcome"])
        self.assertEqual(1, len(out["declarations"]))

    def test_permission_error_is_unmeasured(self):
        def _denied(path):
            raise PermissionError(path)
        out = tlc.tmp_sweep_declared(("/x.conf",), read=_denied)
        self.assertEqual("unmeasured", out["outcome"])
        self.assertFalse(out["measured"],
                         "нечитаемый файл выдан за измерение — fail-OPEN внутри "
                         "fail-CLOSED прибора")


class ReceiptClockDoorTests(unittest.TestCase):
    """Сжатая форма отметки СЧИТАЕТСЯ, а не глотается (класс ADR-682)."""

    def test_compact_stamp_is_counted_and_named(self):
        with TemporaryDirectory() as tmp:
            rep = Scene(tmp).journal([{"ts": at(hours=1), "cwd": "/tmp/spa_a"}]).ledger([
                {"ts": at(hours=5), "worktree": "/tmp/spa_a"},
                {"ts": "20260814T162600Z", "worktree": "/tmp/spa_b"},
            ]).build(exists=lambda p: False)
        self.assertEqual(1, rep["population"]["receipts_unparsed"])
        self.assertIn("ADR-682", rep["population"]["receipts_unparsed_says"])

    def test_an_unparsed_receipt_does_not_silently_become_a_reaped_end(self):
        """Квитанция с нечитаемой отметкой НЕ вправе оправдать конец дерева."""
        with TemporaryDirectory() as tmp:
            rep = Scene(tmp).journal([{"ts": at(hours=1), "cwd": "/tmp/spa_b"}]).ledger(
                [{"ts": "20260814T162600Z", "worktree": "/tmp/spa_b"}]).build(exists=lambda p: False)
        row = next(r for r in rep["survival"] if r["tree"] == "/tmp/spa_b")
        self.assertNotEqual(tlc.CAUSE_REAPED, row["cause"],
                           "неразобранная квитанция сошла за измеренное снятие")


class ThirdOutcomeTests(unittest.TestCase):
    """Отсутствие наблюдения — отдельное значение и ненулевой код (инв. #17)."""

    def test_no_journal_is_unmeasured_not_empty_success(self):
        with TemporaryDirectory() as tmp:
            scene = Scene(tmp)
            rep = scene.build()
        self.assertFalse(rep["measured"])
        self.assertEqual(tlc.STATUS_UNMEASURED, rep["status"])
        self.assertEqual(2, tlc.exit_code_for(rep), "замера нет, а код возврата не 2")
        self.assertIn("НЕ ИЗМЕРЕНО", tlc.format_report(rep)[0])

    def test_declared_fields_are_present_even_unmeasured(self):
        """Объявленное поле обязано быть ВИДНО читателю и в третьем исходе.

        Урок ADR-686: поле, которого читатель не видит, — мёртвый свидетель. Шаг
        0-офис сверяет объявленный перечень с документом и на пропущенных ключах
        докладывал бы «СХЕМА РАЗОШЛАСЬ» ровно тогда, когда прибор отвечает честно.
        Измерено ИСХОДОМ (так и было поймано живым прогоном офиса), а не рассуждением.
        """
        with TemporaryDirectory() as tmp:
            rep = Scene(tmp).build()
        for field in ("population", "observation", "survival",
                      "remaining_window", "silent_loss"):
            self.assertIn(field, rep,
                          f"объявленное поле {field} в третьем исходе ОТСУТСТВУЕТ — "
                          f"читатель его не видит, схема расходится на верном поведении")
            self.assertIsNone(rep[field],
                              f"{field} в третьем исходе подставлен пустым значением "
                              f"вместо None — «не измерено» слилось с «измерено и пусто»")

    def test_broken_journal_lines_are_counted(self):
        with TemporaryDirectory() as tmp:
            scene = Scene(tmp)
            (scene.data / tlc.JOURNAL_NAME).write_text(
                json.dumps({"ts": at(hours=1), "cwd": "/tmp/spa_a"}) + "\n{не json\n",
                encoding="utf-8")
            scene.ledger([])
            rep = scene.build(exists=lambda p: False)
        self.assertIn("битых строк", rep["population"]["journal_note"] or "")

    def test_exit_code_is_a_finding_while_losses_or_unnamed_remainder_stand(self):
        with TemporaryDirectory() as tmp:
            rep = Scene(tmp).journal([{"ts": at(hours=1), "cwd": "/tmp/spa_gone"}]).ledger(
                []).build(exists=lambda p: False)
        self.assertEqual(1, tlc.exit_code_for(rep),
                         "потеря без следа не покраснела — находка выдана за зелень")

    def test_applied_is_false_and_the_report_says_so(self):
        with TemporaryDirectory() as tmp:
            rep = Scene(tmp).journal([{"ts": at(hours=1), "cwd": "/tmp/spa_a"}]).ledger([]).build(
                exists=lambda p: False)
        self.assertFalse(rep["applied"])
        self.assertTrue(any("ADVISORY" in line for line in tlc.format_report(rep)))


class HeadlineArithmeticTests(unittest.TestCase):
    """Заголовочные числа пришпилены ЗНАЧЕНИЕМ, а не наличием ключа.

    Найдено мутационной переписью: мутанты в самой арифметике такта и в выборе
    первого объявления ВЫЖИВАЛИ — батарея проверяла, что поле есть, а не что оно
    посчитано. Число, которого никто не пришпилил, может молча стать другим.
    """

    def test_per_day_rate_is_pinned_by_value(self):
        """Такт в сутки — ГЛАВНОЕ число G688 п. 4; его арифметика закреплена."""
        rows = [{"tree": f"/tmp/spa_{i}", "cause": tlc.CAUSE_VANISHED_SILENT}
                for i in range(6)]
        out = tlc.silent_loss_rate(rows, 48.0)      # 6 деревьев за 2 суток
        self.assertTrue(out["measured"])
        self.assertEqual(6, out["trees"])
        self.assertEqual(3.0, out["per_day"],
                         "такт в сутки посчитан не как деревья/(часы/24) — главное "
                         "число заказа поехало молча")
        self.assertTrue(out["is_lower_bound"],
                        "направление ошибки не названо: 27 читалось бы как точное")

    def test_zero_uptime_is_unmeasured_not_a_rate(self):
        """Делить на ноль нечем ⇒ третий исход, а не бесконечность и не ноль."""
        rows = [{"tree": "/tmp/spa_x", "cause": tlc.CAUSE_VANISHED_SILENT}]
        for uptime in (0.0, -5.0, None):
            with self.subTest(uptime=uptime):
                out = tlc.silent_loss_rate(rows, uptime)
                self.assertFalse(out["measured"])
                self.assertIsNone(out["per_day"], "такт посчитан без окна")
                self.assertEqual(1, out["trees"],
                                 "счёт деревьев потерян вместе с тактом — это два "
                                 "РАЗНЫХ наблюдения")

    def test_the_earliest_announcement_wins_not_the_latest(self):
        """Рождение берётся у ПЕРВОГО объявления: иначе срок жизни занижается.

        Мутант, меняющий `<` на `>=` в выборе первого упоминания, брал бы ПОСЛЕДНЕЕ
        объявление и давал бы срок жизни короче настоящего у КАЖДОГО снятого дерева.
        """
        journal = [
            {"ts": at(hours=30), "cwd": "/tmp/spa_two"},   # позже
            {"ts": at(hours=4), "cwd": "/tmp/spa_two"},    # РАНЬШЕ — это и есть рождение
        ]
        with TemporaryDirectory() as tmp:
            rep = Scene(tmp).journal(journal).ledger(
                [{"ts": at(hours=44), "worktree": "/tmp/spa_two"}]).build(exists=lambda p: False)
        row = rep["survival"][0]
        self.assertEqual(at(hours=4), row["first_announced"],
                         "взято НЕ первое объявление — рождение позже настоящего")
        self.assertEqual(40.0, row["survived_hours"],
                         "срок жизни занижен: отсчёт пошёл от последнего объявления")


class RenderTests(unittest.TestCase):
    """Отрисовка — одной копией по уже прочитанному документу (урок ADR-683)."""

    def test_render_names_the_headline_numbers(self):
        with TemporaryDirectory() as tmp:
            rep = Scene(tmp).journal([
                {"ts": at(hours=1), "cwd": "/tmp/spa_gone"},
                {"ts": at(hours=2), "cwd": "/tmp/spa_alive"},
            ]).ledger([]).build(
                exists=lambda p: p == "/tmp/spa_alive",
                birth_probe=lambda p: (ANCHOR + timedelta(hours=2)).timestamp())
        text = "\n".join(tlc.format_report(rep))
        self.assertIn("ТАКТ МОЛЧАЛИВОЙ ПОТЕРИ", text)
        self.assertIn("СКОЛЬКО ОСТАЛОСЬ: НЕ ИЗМЕРИМО", text)
        self.assertIn("НЕ ДОКЛАДЫВАЕТ", text,
                      "прибор не сказал, чего он НЕ меряет — читатель примет умолчание "
                      "за полноту")

    def test_render_does_not_claim_a_rate_it_could_not_divide(self):
        with TemporaryDirectory() as tmp:
            rep = Scene(tmp).journal([{"ts": at(hours=1), "cwd": "/tmp/spa_gone"}]).ledger(
                []).build(boot_probe=lambda: None, exists=lambda p: False)
        text = "\n".join(tlc.format_report(rep))
        self.assertIn("такт молчаливой потери: НЕ ИЗМЕРЕН", text)
        self.assertNotIn("/сутки", text, "такт в сутки напечатан без аптайма")


class ArtifactTests(unittest.TestCase):
    """Артефакт оставляется ВСЕГДА, включая третий исход."""

    def test_unmeasured_report_is_still_written(self):
        with TemporaryDirectory() as tmp:
            scene = Scene(tmp)
            rep = scene.build()
            tlc.save_artifact(rep, scene.data)
            doc = json.loads((scene.data / tlc.ARTIFACT_NAME).read_text(encoding="utf-8"))
        self.assertFalse(doc["measured"],
                         "третий исход не доехал до артефакта — отсутствие файла стало "
                         "неотличимо от «ступень не запускалась»")
        self.assertIn("generated_at", doc,
                      "артефакт без отметки делает объявленный такт прозой")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
