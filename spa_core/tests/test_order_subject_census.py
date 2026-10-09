"""Батарея переписи предмета захвата — заказ G109 п. 2 (ADR-534).

# FROZEN-DATE-OK: injected-clock — все отметки сцен ПРОИСХОДЯТ от одного якоря
# `_NOW` (локальная привязка каждого теста), и он же передаётся аргументом в
# `run_census(now=...)` / `_stamp(...)` / `_lstart(...)`; стенных часов в файле
# нет ни одного вызова, а пересчёт часового пояса инъектируется параметром
# `mktime=`, то есть обе двери к ОС закрыты для того пути, который идёт тест.

Каждый тест — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: воспроизводит либо наблюдённый дефект
(переименование, которое начало имени не видит; ноль, ложный по построению;
каталог, объявленный координатой), либо названный третий исход. Контроли идут
ПАРАМИ: там, где прибор обязан молчать, стоит второй тест, где он обязан
краснеть, — иначе зелёный вердикт ничего не означает.
"""

from __future__ import annotations

import json
import subprocess
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import duplicate_subject_census as dsc
from spa_core.monitoring import order_subject_census as osc


def _now() -> datetime:
    """Якорь времени. ЛОКАЛЬНАЯ привязка: на импорте не вычисляется ничего."""
    return datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)


def _stamp(now: datetime, *, minutes_ago: float) -> str:
    return (now - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


#: Пересчёт пояса — ВХОД. Этот подставной `mktime` объявляет зону UTC ровно,
#: поэтому `_lstart` и он суть взаимно обратные функции по построению, и ни один
#: тест не зависит от того, в какой зоне стои́т машина (урок про pid и календарь
#: из `.claude/rules/deployment.md`, третий член того же семейства).
def _utc_mktime(parts) -> float:
    import calendar
    return calendar.timegm(parts)


def _lstart(now: datetime, *, minutes_ago: float) -> str:
    moment = now - timedelta(minutes=minutes_ago)
    return moment.strftime("%a %b %d %H:%M:%S %Y")


def _record(now: datetime, *, pid: int, start_minutes_ago: float,
            minutes_ago: float, summary: str, files=(), card: str = "inbox-standing",
            dropped=None, anchor: bool = True) -> dict:
    doc = {
        "ts": _stamp(now, minutes_ago=minutes_ago),
        "session": f"cycle-{pid}",
        "summary": summary,
        "files": list(files),
        "verified": "сцена",
        "card": card,
        "card_state": "claim",
    }
    if anchor:
        doc["session_pid"] = pid
        doc["session_pid_start"] = _lstart(now, minutes_ago=start_minutes_ago)
    if dropped is not None:
        doc["dropped"] = dropped
    return doc


def _journal(root: Path, records) -> Path:
    path = root / osc.JOURNAL_NAME
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                    encoding="utf-8")
    return path


def _repo(root: Path, paths) -> Path:
    """Одноразовый репозиторий с ВЕТКОЙ `origin/main` указанного состава.

    Имя ветки объявлено ВХОДОМ `git init -b` (третий член семейства
    «необъявленное окружение», `.claude/rules/deployment.md`): Apple Git даёт
    `main`, git на `ubuntu-latest` — `master`, и фикстура, назвавшая потом
    `origin/main`, была бы зелена здесь и красна там.
    """
    def git(*args):
        done = subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, text=True)
        assert done.returncode == 0, f"git {args}: {done.stderr}"
        return done
    subprocess.run(["git", "init", "-b", "main", str(root)],
                   capture_output=True, text=True, check=True)
    git("config", "user.email", "scene@example.invalid")
    git("config", "user.name", "scene")
    for rel in paths:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("содержимое\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "сцена")
    git("branch", "-f", "origin/main", "main")
    return root


# ───────────────────────────── предмет записи ─────────────────────────────

class TestSubjectOfARecord(unittest.TestCase):
    def test_order_of_the_series_is_read(self):
        found = osc.subjects_of({"summary": "цикл #816, ЗАКАЗ G109 п. 2 приказа"})
        self.assertEqual(found["orders"], {"109"})
        self.assertEqual(found["stages"], set())
        self.assertEqual(found["loose_only"], set())

    def test_parenthesised_form_is_read(self):
        found = osc.subjects_of({"summary": "цикл #590, ЗАКАЗ #590 (G7) приказа CIO"})
        self.assertEqual(found["orders"], {"7"})

    def test_a_stage_of_the_order_is_a_DIFFERENT_subject(self):
        """Омонимия: «гэп G1» — ЭТАП приказа, не заказ ряда. Порознь."""
        found = osc.subjects_of({"summary": "приказ владельца CIO, гэп G1 (наблюдаемость)"})
        self.assertEqual(found["stages"], {"1"})
        self.assertEqual(found["orders"], set(),
                         "этап приказа не имеет права стать заказом ряда")

    def test_a_bare_token_is_UNMEASURED_not_zero(self):
        """Токен без разбираемой формы — третий исход, а не ноль и не заказ."""
        found = osc.subjects_of({"summary": "живой остаток списка — G1 (расхождение фидов)"})
        self.assertEqual(found["orders"], set())
        self.assertEqual(found["loose_only"], {"1"})

    def test_subject_is_sought_in_declared_fields_only(self):
        found = osc.subjects_of({"summary": "", "verified": "заказ G42 закрыт",
                                 "card": "заказ G77"})
        self.assertEqual(found["orders"], {"42"},
                         "поле `card` предметом ряда не объявлено — читать его нельзя")


# ─────────────────────────── отрезок жизни сессии ─────────────────────────

class TestSessionIntervals(unittest.TestCase):
    def test_conversion_is_corroborated_by_every_session(self):
        now = _now()
        records = [_record(now, pid=11, start_minutes_ago=60, minutes_ago=50,
                           summary="заказ G1 п. 1"),
                   _record(now, pid=11, start_minutes_ago=60, minutes_ago=10,
                           summary="заказ G1 п. 1 доставлен")]
        out = osc.intervals_of(records, mktime=_utc_mktime)
        self.assertEqual(out["sessions"], 1)
        self.assertEqual(out["conversion_corroborated"], 1)
        self.assertEqual(out["conversion_refuted"], 0)
        span = next(iter(out["spans"].values()))
        self.assertEqual((span[1] - span[0]), timedelta(minutes=50),
                         "отрезок считается от СТАРТА процесса, не от первого объявления")

    def test_start_after_first_record_REFUTES_the_conversion_and_is_loud(self):
        """Процесс не может писать раньше, чем начался ⇒ отрезок НЕ ИЗМЕРЕН."""
        now = _now()
        records = [_record(now, pid=12, start_minutes_ago=-120, minutes_ago=10,
                           summary="заказ G2 п. 1")]
        out = osc.intervals_of(records, mktime=_utc_mktime)
        self.assertEqual(out["conversion_refuted"], 1)
        self.assertEqual(out["sessions"], 0, "подрезать отрезок молча запрещено")
        self.assertTrue(out["conversion_refuted_examples"])

    def test_unparsable_start_is_counted_separately_not_dropped(self):
        now = _now()
        record = _record(now, pid=13, start_minutes_ago=30, minutes_ago=10,
                         summary="заказ G3 п. 1")
        record["session_pid_start"] = "вчера вечером"
        out = osc.intervals_of([record], mktime=_utc_mktime)
        self.assertEqual(out["unparsed_start_count"], 1)
        self.assertEqual(out["sessions"], 1, "отрезок от первого объявления всё же есть")

    def test_a_label_without_an_anchor_is_NOT_an_identity(self):
        now = _now()
        out = osc.intervals_of([_record(now, pid=14, start_minutes_ago=30,
                                        minutes_ago=10, summary="заказ G4 п. 1",
                                        anchor=False)], mktime=_utc_mktime)
        self.assertEqual(out["sessions"], 0)
        self.assertEqual(out["records_without_anchor"], 1)

    def test_a_record_without_a_stamp_is_counted_separately(self):
        now = _now()
        record = _record(now, pid=15, start_minutes_ago=30, minutes_ago=10,
                         summary="заказ G5 п. 1")
        record["ts"] = "не отметка"
        out = osc.intervals_of([record], mktime=_utc_mktime)
        self.assertEqual(out["records_without_stamp"], 1)
        self.assertEqual(out["sessions"], 0)

    def test_lstart_parser_refuses_garbage(self):
        self.assertIsNone(osc.parse_lstart("", mktime=_utc_mktime))
        self.assertIsNone(osc.parse_lstart("2026-10-09T12:00:00Z", mktime=_utc_mktime))
        self.assertIsNotNone(osc.parse_lstart("Fri Oct  9 12:00:00 2026",
                                              mktime=_utc_mktime))


# ───────────────── ось B, форма 1: живое пересечение ──────────────────────

class TestLiveOverlap(unittest.TestCase):
    def test_two_sessions_alive_at_once_on_ONE_order_are_found(self):
        now = _now()
        records = [_record(now, pid=21, start_minutes_ago=90, minutes_ago=20,
                           summary="заказ G700 п. 1"),
                   _record(now, pid=22, start_minutes_ago=40, minutes_ago=5,
                           summary="заказ G700 п. 1")]
        out = osc.measure_population(records, None, mktime=_utc_mktime)
        self.assertEqual(out["live_overlap_count"], 1)
        self.assertFalse(out["live_overlap_zero_is_false_by_construction"])

    def test_two_sessions_on_DIFFERENT_orders_are_not_a_collision(self):
        """Контроль в обратную сторону: пересечение по ВРЕМЕНИ ещё не предмет."""
        now = _now()
        records = [_record(now, pid=23, start_minutes_ago=90, minutes_ago=20,
                           summary="заказ G700 п. 1"),
                   _record(now, pid=24, start_minutes_ago=40, minutes_ago=5,
                           summary="заказ G701 п. 1")]
        out = osc.measure_population(records, None, mktime=_utc_mktime)
        self.assertEqual(out["live_overlap_count"], 0)

    def test_a_zero_declares_itself_false_by_construction(self):
        """Ноль формы 1 публикуется ВМЕСТЕ со своим опровержением."""
        now = _now()
        records = [_record(now, pid=25, start_minutes_ago=90, minutes_ago=80,
                           summary="заказ G702 п. 1"),
                   _record(now, pid=26, start_minutes_ago=20, minutes_ago=5,
                           summary="заказ G702 п. 1")]
        out = osc.measure_population(records, None, mktime=_utc_mktime)
        self.assertEqual(out["live_overlap_count"], 0)
        self.assertTrue(out["live_overlap_zero_is_false_by_construction"])
        printed = "\n".join(osc.format_report(
            {"measured": True, "status": osc.STATUS_OPEN, "population": out,
             "door": None, "intersections_total": 0}))
        self.assertIn("ЛОЖЕН ПО ПОСТРОЕНИЮ", printed)


# ────────────── ось B, форма 2: недавно мёртвый предшественник ────────────

class TestRecentlyDeadPredecessor(unittest.TestCase):
    def test_population_depends_on_the_window_and_the_ladder_shows_it(self):
        now = _now()
        records = [_record(now, pid=31, start_minutes_ago=300, minutes_ago=290,
                           summary="заказ G710 п. 1"),
                   _record(now, pid=32, start_minutes_ago=50, minutes_ago=5,
                           summary="заказ G710 п. 1")]
        out = osc.measure_population(records, None, mktime=_utc_mktime,
                                     grace_ladder=(1.0, 6.0))
        self.assertEqual(out["recently_dead"]["1h"], 0,
                         "разрыв 4 ч в окно 1 ч не лезет")
        self.assertEqual(out["recently_dead"]["6h"], 1)

    def test_the_window_is_an_INPUT_not_a_constant(self):
        now = _now()
        records = [_record(now, pid=33, start_minutes_ago=300, minutes_ago=290,
                           summary="заказ G711 п. 1"),
                   _record(now, pid=34, start_minutes_ago=50, minutes_ago=5,
                           summary="заказ G711 п. 1")]
        wide = osc.measure_population(records, None, mktime=_utc_mktime,
                                      grace_ladder=(24.0,))
        self.assertEqual(wide["recently_dead"]["24h"], 1)
        self.assertEqual(list(wide["recently_dead"]), ["24h"],
                         "лестница целиком приходит входом")

    def test_the_door_grace_is_taken_FROM_THE_DOOR(self):
        door, reason = osc.load_door(Path(__file__).resolve().parents[2])
        self.assertIsNotNone(door, reason)
        self.assertEqual(osc.DOOR_GRACE_HOURS, door.DEFAULT_GRACE_HOURS,
                         "умолчание окна обязано быть тем же числом, которым судит дверь")
        self.assertIn(osc.DOOR_GRACE_HOURS, osc.GRACE_LADDER_HOURS)


# ───────── ось B, форма 3: преемство с недоставленным предшественником ────

class TestSuccessionWithUndeliveredPredecessor(unittest.TestCase):
    def _scene(self, holder: Path, *, declared, base_paths, dropped=None,
               summary_first="заказ G720 п. 1", summary_second="заказ G720 п. 1"):
        now = _now()
        repo = _repo(holder / "repo", base_paths)
        records = [
            _record(now, pid=41, start_minutes_ago=300, minutes_ago=290,
                    summary=summary_first,
                    files=[f"/tmp/spa_c41/{c}" for c in declared], dropped=dropped),
            _record(now, pid=42, start_minutes_ago=50, minutes_ago=5,
                    summary=summary_second),
        ]
        base = dsc.read_base_tree(repo, "origin/main")
        self.assertTrue(base["measured"], base.get("reason"))
        return osc.measure_population(records, base, mktime=_utc_mktime,
                                      retirement=dsc.retirement_door(repo, "origin/main"))

    def test_an_undelivered_predecessor_is_found(self):
        with TemporaryDirectory() as tmp:
            out = self._scene(Path(tmp),
                              declared=["spa_core/monitoring/gone_thing.py"],
                              base_paths=["spa_core/monitoring/unrelated.py"])
        self.assertEqual(out["succession_undelivered_count"], 1)
        self.assertEqual(out["lost_coordinates_total"], 1)

    def test_a_DELIVERED_predecessor_is_not_a_finding(self):
        with TemporaryDirectory() as tmp:
            out = self._scene(Path(tmp),
                              declared=["spa_core/monitoring/arrived.py"],
                              base_paths=["spa_core/monitoring/arrived.py"])
        self.assertEqual(out["succession_undelivered_count"], 0)

    def test_a_DECLARED_DROP_is_a_decision_not_a_loss(self):
        with TemporaryDirectory() as tmp:
            out = self._scene(
                Path(tmp), declared=["spa_core/monitoring/dropped_thing.py"],
                base_paths=["spa_core/monitoring/unrelated.py"],
                dropped=[{"path": "/tmp/spa_c41/spa_core/monitoring/dropped_thing.py",
                          "reason": "дублировал бы поднятый прибор"}])
        self.assertEqual(out["succession_undelivered_count"], 0)

    def test_a_declared_DIRECTORY_is_not_a_loss(self):
        """Замер 09.10: сессия на G91 объявила `docs/decisions`, и перепись
        звала КАТАЛОГ потерей — `ls-tree -r` перечисляет файлы."""
        with TemporaryDirectory() as tmp:
            out = self._scene(Path(tmp), declared=["docs/decisions"],
                              base_paths=["docs/decisions/ADR-001-a.md"])
        self.assertEqual(out["succession_undelivered_count"], 0)
        self.assertEqual(out["coordinates_declared_as_directory"], 1)

    def test_a_DELIVERED_RETIREMENT_is_not_a_loss(self):
        """Чем успешнее доставлено списание, тем больше оно похоже на потерю.

        Сцена: координата лежала на базе, объявлена сессией и УДАЛЕНА коммитом
        ПОЗЖЕ объявления. «На базе нет» здесь означает, что работа доехала.
        """
        now = _now()
        with TemporaryDirectory() as tmp:
            holder = Path(tmp)
            repo = _repo(holder / "repo", ["spa_core/monitoring/retired_thing.py",
                                           "spa_core/monitoring/unrelated.py"])

            def git(*args):
                done = subprocess.run(["git", "-C", str(repo), *args],
                                      capture_output=True, text=True)
                assert done.returncode == 0, done.stderr
            (repo / "spa_core/monitoring/retired_thing.py").unlink()
            git("add", "-A")
            git("commit", "-m", "списание обёртки доставлено")
            git("branch", "-f", "origin/main", "main")
            base = dsc.read_base_tree(repo, "origin/main")
            self.assertTrue(base["measured"], base.get("reason"))
            records = [
                _record(now, pid=47, start_minutes_ago=300, minutes_ago=290,
                        summary="заказ G725 п. 1",
                        files=["/tmp/spa_c47/spa_core/monitoring/retired_thing.py"]),
                _record(now, pid=48, start_minutes_ago=50, minutes_ago=5,
                        summary="заказ G725 п. 1"),
            ]
            without = osc.measure_population(records, base, mktime=_utc_mktime,
                                             retirement=None)
            withdoor = osc.measure_population(
                records, base, mktime=_utc_mktime,
                retirement=dsc.retirement_door(repo, "origin/main"))
        self.assertEqual(without["succession_undelivered_count"], 1,
                         "без двери списания координата честно считается потерей")
        self.assertEqual(withdoor["succession_undelivered_count"], 0,
                         "доставленное списание потерей не является")

    def test_prefix_kin_of_the_NEIGHBOUR_still_suppresses_a_rename(self):
        with TemporaryDirectory() as tmp:
            out = self._scene(
                Path(tmp), declared=["spa_core/tests/test_tracker_board_composition.py"],
                base_paths=["spa_core/tests/test_tracker_board_matches_cards.py"])
        self.assertEqual(out["succession_undelivered_count"], 0,
                         "родня соседа по НАЧАЛУ имени обязана действовать как раньше")

    def test_ONE_session_on_an_order_is_succession_of_nobody(self):
        now = _now()
        with TemporaryDirectory() as tmp:
            repo = _repo(Path(tmp) / "repo", ["spa_core/monitoring/unrelated.py"])
            base = dsc.read_base_tree(repo, "origin/main")
            out = osc.measure_population(
                [_record(now, pid=43, start_minutes_ago=90, minutes_ago=10,
                         summary="заказ G730 п. 1",
                         files=["/tmp/spa_c43/spa_core/monitoring/gone.py"])],
                base, mktime=_utc_mktime)
        self.assertEqual(out["succession_undelivered_count"], 0)

    def test_a_label_without_an_anchor_makes_no_SESSION_in_the_population(self):
        """Ярлык личностью не является и на уровне НАСЕЛЕНИЯ, не только отрезков.

        Иначе одна сессия под двумя ярлыками изготовила бы столкновение из
        формы записи (авария «сессия отказала сама себе», цикл #54).
        """
        now = _now()
        records = [_record(now, pid=49, start_minutes_ago=300, minutes_ago=290,
                           summary="заказ G735 п. 1", anchor=False),
                   _record(now, pid=50, start_minutes_ago=50, minutes_ago=5,
                           summary="заказ G735 п. 1", anchor=False)]
        out = osc.measure_population(records, None, mktime=_utc_mktime)
        self.assertEqual(out["records_with_order_without_identity"], 2)
        self.assertEqual(out["orders_with_two_or_more_sessions"], 0,
                         "два ярлыка без якоря двумя сессиями не являются")
        self.assertEqual(out["live_overlap_count"], 0)
        self.assertEqual(sum(out["recently_dead"].values()), 0)

    def test_an_unreadable_base_is_None_NOT_zero(self):
        now = _now()
        out = osc.measure_population(
            [_record(now, pid=44, start_minutes_ago=90, minutes_ago=10,
                     summary="заказ G740 п. 1")],
            None, mktime=_utc_mktime)
        self.assertIsNone(out["succession_undelivered_count"],
                          "непрочитанное дерево обязано быть третьим исходом")
        self.assertIsNone(out["lost_explained_by_set_kin"])
        self.assertIsNone(out["coordinates_declared_as_directory"])

    def test_a_coordinate_outside_any_tree_is_counted_separately(self):
        now = _now()
        with TemporaryDirectory() as tmp:
            repo = _repo(Path(tmp) / "repo", ["spa_core/monitoring/unrelated.py"])
            base = dsc.read_base_tree(repo, "origin/main")
            out = osc.measure_population(
                [_record(now, pid=45, start_minutes_ago=300, minutes_ago=290,
                         summary="заказ G750 п. 1", files=["нечто/без/дерева.py"]),
                 _record(now, pid=46, start_minutes_ago=50, minutes_ago=5,
                         summary="заказ G750 п. 1")],
                base, mktime=_utc_mktime)
        self.assertEqual(out["coordinates_unnormalisable"], 1)
        self.assertEqual(out["succession_undelivered_count"], 0)


# ──────────────── вторая дверь родни: НАБОР, а не НАЧАЛО ──────────────────

class TestSecondKinDoor(unittest.TestCase):
    """Каждый случай — ДОСЛОВНЫЙ замер 2026-10-09 на живом журнале."""

    def test_an_article_inserted_at_the_head_of_a_slug(self):
        declared = "docs/decisions/ADR-506-price-of-an-unmeasured-s49-criterion.md"
        delivered = "docs/decisions/ADR-506-the-price-of-an-unmeasured-s49-criterion.md"
        self.assertEqual(dsc.kin_of(declared, [delivered]), [],
                         "правило соседа этот случай не видит — это и есть предмет")
        best = osc.kin_by_token_set(declared, [delivered], 0.5)
        self.assertIsNotNone(best)
        self.assertEqual(best[1], delivered)
        self.assertGreater(best[0], 0.8)

    def test_a_token_dropped_from_the_head_of_a_name(self):
        declared = "spa_core/monitoring/test_step_time_census.py"
        delivered = "spa_core/monitoring/step_time_census.py"
        self.assertEqual(dsc.kin_of(declared, [delivered]), [])
        self.assertIsNotNone(osc.kin_by_token_set(declared, [delivered], 0.7))

    def test_a_token_replaced_in_the_middle(self):
        declared = "spa_core/monitoring/timeout_swallow_census.py"
        delivered = "spa_core/monitoring/timeout_door_census.py"
        self.assertEqual(dsc.kin_of(declared, [delivered]), [])
        self.assertIsNotNone(osc.kin_by_token_set(declared, [delivered], 0.5))

    def test_below_the_threshold_the_door_REFUSES(self):
        self.assertIsNone(osc.kin_by_token_set(
            "spa_core/monitoring/timeout_swallow_census.py",
            ["spa_core/monitoring/timeout_door_census.py"], 0.9))

    def test_another_directory_is_never_kin(self):
        self.assertIsNone(osc.kin_by_token_set(
            "spa_core/monitoring/thing.py", ["spa_core/tests/thing_two.py"], 0.1))

    def test_the_BEST_candidate_wins_not_the_first(self):
        best = osc.kin_by_token_set(
            "spa_core/monitoring/timeout_swallow_census.py",
            ["spa_core/monitoring/census_consumer_census.py",
             "spa_core/monitoring/timeout_door_census.py"], 0.2)
        self.assertEqual(best[1], "spa_core/monitoring/timeout_door_census.py")

    def test_the_ladder_of_thresholds_is_published_not_a_single_default(self):
        with TemporaryDirectory() as tmp:
            now = _now()
            repo = _repo(Path(tmp) / "repo",
                         ["docs/decisions/ADR-506-the-price-of-an-unmeasured-s49-criterion.md"])
            base = dsc.read_base_tree(repo, "origin/main")
            out = osc.measure_population(
                [_record(now, pid=51, start_minutes_ago=300, minutes_ago=290,
                         summary="заказ G760 п. 1",
                         files=["/tmp/spa_c51/docs/decisions/"
                                "ADR-506-price-of-an-unmeasured-s49-criterion.md"]),
                 _record(now, pid=52, start_minutes_ago=50, minutes_ago=5,
                         summary="заказ G760 п. 1")],
                base, mktime=_utc_mktime, set_kin_ladder=(0.3, 0.95))
        self.assertEqual(out["succession_undelivered_count"], 1,
                         "по правилу соседа координата по-прежнему «потеряна»")
        self.assertEqual(out["lost_explained_by_set_kin"], {"0.3": 1, "0.95": 0},
                         "зависимость от порога обязана быть видна числом")

    def test_the_neighbours_own_rule_is_NOT_touched(self):
        """Расширять `kin_of` соседа этой доставкой запрещено (инв. #16)."""
        self.assertEqual(dsc._KIN_TOKENS, 3)
        self.assertEqual(
            dsc.kin_of("spa_core/monitoring/timeout_swallow_census.py",
                       ["spa_core/monitoring/timeout_door_census.py"]), [])


class TestDirectoryProbe(unittest.TestCase):
    def test_a_directory_prefix_is_recognised(self):
        self.assertTrue(osc._is_directory("docs/decisions", ["docs/decisions/a.md"]))

    def test_a_file_is_not_a_directory(self):
        self.assertFalse(osc._is_directory("docs/decisions/a.md", ["docs/decisions/a.md"]))

    def test_a_name_that_merely_SHARES_A_PREFIX_is_not_a_directory(self):
        self.assertFalse(osc._is_directory("docs/dec", ["docs/decisions/a.md"]),
                         "`docs/dec` не каталог `docs/decisions` — сравнение по СЕГМЕНТУ")


# ───────────────────── ось A: видит ли дверь предмет ──────────────────────

class _FakeDoor:
    """Подставная дверь. `sees_order` — ВИДИТ ли она номер заказа в объявлении."""

    DEFAULT_GRACE_HOURS = 3.0

    def __init__(self, *, sees_order: bool, frozen_verdict: bool = False):
        self.sees_order = sees_order
        self.frozen_verdict = frozen_verdict

    def gather(self, card, *, log, tracker_dir, now, self_anchor, ps,
               shared_trees, repo_root, base_ref):
        entries = [json.loads(line) for line in
                   Path(log).read_text(encoding="utf-8").splitlines() if line.strip()]
        mine = [e for e in entries
                if str(e.get("card", "")).endswith(card)] if not self.frozen_verdict else entries
        claims = []
        for entry in mine:
            signal = entry["summary"] if self.sees_order else "поле card:"
            claims.append({"session": entry["session"], "signal": signal,
                           "state": "claimed", "active": True})
        return {"verdict": "claimed" if claims else "free", "grace_hours": 3.0,
                "card_status": "in-progress", "claims": claims}


class TestTheDoorAxis(unittest.TestCase):
    def test_the_REAL_door_does_not_see_the_order_number(self):
        """Главный ответ заказа G109 п. 2 — и он измерен ИСХОДОМ."""
        out = osc.measure_door(Path(__file__).resolve().parents[2], now=_now())
        self.assertTrue(out["measured"], out.get("reason"))
        self.assertFalse(out["door_sees_order"])
        self.assertTrue(out["control_moved_verdict"],
                        "без сдвига вердикта от подмены КАРТОЧКИ замер ничего не значит")
        self.assertEqual(out["subject_parameters"], ["card"])

    def test_a_door_that_DOES_see_the_order_is_reported_as_seeing(self):
        """Контроль в обратную сторону: прибор не отвечает «слепа» всегда."""
        out = osc.measure_door(Path("/не/важно"), door=_FakeDoor(sees_order=True),
                               now=_now())
        self.assertTrue(out["measured"], out.get("reason"))
        self.assertTrue(out["door_sees_order"])

    def test_a_door_whose_verdict_NEVER_MOVES_is_a_loud_third_outcome(self):
        """Сцена, не способная двигать вердикт, не есть «дверь слепа»."""
        out = osc.measure_door(Path("/не/важно"),
                               door=_FakeDoor(sees_order=False, frozen_verdict=True),
                               now=_now())
        self.assertFalse(out["measured"])
        self.assertIn("scene_cannot_move_verdict", out["reason"])
        self.assertFalse(out["control_moved_verdict"])
        self.assertIsNone(out["door_sees_order"],
                          "«не измерено» не имеет права выглядеть как «видит»")

    def test_a_missing_door_is_named_not_assumed(self):
        with TemporaryDirectory() as tmp:
            module, reason = osc.load_door(Path(tmp))
        self.assertIsNone(module)
        self.assertIn("двери нет", reason)

    def test_a_door_without_an_entry_is_named(self):
        class _NoEntry:
            pass
        out = osc.measure_door(Path("/не/важно"), door=_NoEntry(), now=_now())
        self.assertFalse(out["measured"])
        self.assertIn("gather", out["reason"])

    def test_the_decision_digest_ignores_the_ECHO_of_the_summary(self):
        """Проекция снимает решение, а не эхо: иначе номер «дошёл» бы сам собой."""
        left = osc._decision_digest({"verdict": "claimed", "grace_hours": 3.0,
                                     "card_status": "in-progress",
                                     "claims": [{"session": "c1", "signal": "поле card:",
                                                 "state": "claimed", "active": True}]})
        right = osc._decision_digest({"verdict": "claimed", "grace_hours": 3.0,
                                      "card_status": "in-progress", "summary_echo": "G901",
                                      "claims": [{"session": "c1", "signal": "поле card:",
                                                  "state": "claimed", "active": True}]})
        self.assertEqual(left, right)

    def test_the_digest_DOES_move_on_a_real_decision_change(self):
        left = osc._decision_digest({"verdict": "claimed", "claims": []})
        right = osc._decision_digest({"verdict": "free", "claims": []})
        self.assertNotEqual(left, right)


# ──────────────────────────── сборка и вердикт ────────────────────────────

class TestCensusAssembly(unittest.TestCase):
    def test_a_missing_journal_is_UNMEASURED_and_loud(self):
        with TemporaryDirectory() as tmp:
            report = osc.run_census(Path(tmp), repo_root=Path(tmp), now=_now())
        self.assertFalse(report["measured"])
        self.assertEqual(report["status"], osc.STATUS_UNMEASURED)
        self.assertIn("журнала нет", report["reason"])
        self.assertIsNone(report["population"])
        self.assertIsNone(report["door"])

    def test_the_report_SHAPE_is_constant_even_when_unmeasured(self):
        with TemporaryDirectory() as tmp:
            report = osc.run_census(Path(tmp), repo_root=Path(tmp), now=_now())
        for key in ("generated_at", "order", "measured", "status", "reason",
                    "base_ref", "door", "population", "journal"):
            self.assertIn(key, report,
                          "ключ обязан быть объявлен всегда: иначе «производитель уехал» "
                          "неотличимо от «в этот раз не считалось» (инв. #17)")

    def test_no_order_read_is_UNMEASURED_not_an_empty_population(self):
        now = _now()
        with TemporaryDirectory() as tmp:
            holder = Path(tmp)
            repo = _repo(holder / "repo", ["spa_core/monitoring/a.py"])
            _journal(holder, [_record(now, pid=61, start_minutes_ago=30,
                                      minutes_ago=10, summary="никакого заказа тут нет")])
            report = osc.run_census(holder, repo_root=repo, now=now)
        self.assertFalse(report["measured"])
        self.assertIn("не прочитано", report["reason"])
        self.assertEqual(report["population"]["orders_named"], 0)

    def test_an_unmeasured_door_keeps_the_class_from_closing(self):
        now = _now()
        with TemporaryDirectory() as tmp:
            holder = Path(tmp)
            repo = _repo(holder / "repo", ["spa_core/monitoring/a.py"])
            _journal(holder, [_record(now, pid=62, start_minutes_ago=30,
                                      minutes_ago=10, summary="заказ G770 п. 1")])
            report = osc.run_census(holder, repo_root=repo, now=now,
                                    door=_FakeDoor(sees_order=False,
                                                   frozen_verdict=True))
        self.assertFalse(report["measured"])
        self.assertIn("ось A не измерена", report["reason"])

    def test_the_class_closes_ONLY_when_the_door_sees_the_subject(self):
        now = _now()
        with TemporaryDirectory() as tmp:
            holder = Path(tmp)
            repo = _repo(holder / "repo", ["spa_core/monitoring/a.py"])
            _journal(holder, [_record(now, pid=63, start_minutes_ago=30,
                                      minutes_ago=10, summary="заказ G780 п. 1")])
            seeing = osc.run_census(holder, repo_root=repo, now=now,
                                    door=_FakeDoor(sees_order=True))
            blind = osc.run_census(holder, repo_root=repo, now=now,
                                   door=_FakeDoor(sees_order=False))
        self.assertEqual(seeing["status"], osc.STATUS_CLOSED)
        self.assertEqual(blind["status"], osc.STATUS_OPEN,
                         "слепая дверь класс не закрывает ни при каком населении")

    def test_an_unmeasured_third_form_makes_the_TOTAL_unmeasured_not_smaller(self):
        """`... or 0` здесь и был бы нарушением инв. #17: «не измерено»
        выдало бы себя за «измерено и равно нулю», и сумма занизилась бы МОЛЧА."""
        now = _now()
        with TemporaryDirectory() as tmp:
            holder = Path(tmp)
            _journal(holder, [_record(now, pid=65, start_minutes_ago=300,
                                      minutes_ago=290, summary="заказ G795 п. 1"),
                              _record(now, pid=66, start_minutes_ago=50,
                                      minutes_ago=5, summary="заказ G795 п. 1")])
            report = osc.run_census(holder, repo_root=holder / "нет-репо", now=now,
                                    door=_FakeDoor(sees_order=False))
        self.assertIsNone(report["intersections_total"])
        self.assertGreater(report["intersections_windowed"], 0,
                           "оконные формы измерены и обязаны быть названы отдельно")
        printed = "\n".join(osc.format_report(report))
        self.assertIn("пересечений всего НЕ ИЗМЕРЕНО", printed)

    def test_a_measured_third_form_gives_a_total(self):
        now = _now()
        with TemporaryDirectory() as tmp:
            holder = Path(tmp)
            repo = _repo(holder / "repo", ["spa_core/monitoring/a.py"])
            _journal(holder, [_record(now, pid=67, start_minutes_ago=300,
                                      minutes_ago=290, summary="заказ G796 п. 1"),
                              _record(now, pid=68, start_minutes_ago=50,
                                      minutes_ago=5, summary="заказ G796 п. 1")])
            report = osc.run_census(holder, repo_root=repo, now=now,
                                    door=_FakeDoor(sees_order=False))
        self.assertIsNotNone(report["intersections_total"])
        self.assertEqual(report["intersections_total"],
                         report["intersections_windowed"])

    def test_an_unreadable_base_keeps_the_class_OPEN_even_with_a_seeing_door(self):
        """fail-CLOSED: обрезанный клон тише красного теста — урок `pyflakes`."""
        now = _now()
        with TemporaryDirectory() as tmp:
            holder = Path(tmp)
            _journal(holder, [_record(now, pid=64, start_minutes_ago=30,
                                      minutes_ago=10, summary="заказ G790 п. 1")])
            report = osc.run_census(holder, repo_root=holder / "нет-репо", now=now,
                                    door=_FakeDoor(sees_order=True))
        self.assertFalse(report["base_ref"]["measured"])
        self.assertEqual(report["status"], osc.STATUS_OPEN)

    def test_the_artifact_is_written_even_on_the_third_outcome(self):
        with TemporaryDirectory() as tmp:
            holder = Path(tmp)
            (holder / "data").mkdir()
            result = osc.run(root=str(holder), now=_now())
            self.assertFalse(result["measured"])
            written = json.loads(
                (holder / "data" / osc.ARTIFACT_NAME).read_text("utf-8"))
        self.assertEqual(written["status"], osc.STATUS_UNMEASURED)
        self.assertTrue(written["reason"],
                        "«не измерено» без причины читателю ничего не говорит")

    def test_main_returns_two_when_unmeasured(self):
        with TemporaryDirectory() as tmp:
            code = osc.main(["--data-dir", tmp, "--repo-root", tmp])
        self.assertEqual(code, 2)

    def test_the_formatter_names_the_third_outcome_of_the_third_form(self):
        printed = "\n".join(osc.format_report({
            "measured": True, "status": osc.STATUS_OPEN, "intersections_total": 0,
            "door": {"measured": False, "reason": "дверь не загружена"},
            "population": {
                "orders_named": 1, "orders_with_two_or_more_sessions": 0,
                "live_overlap_count": 0, "live_overlap_zero_is_false_by_construction": True,
                "recently_dead": {"3h": 0}, "succession_undelivered_count": None,
                "succession_undelivered": None, "records_total": 1,
                "records_subject_not_named": 0, "records_token_in_unread_form": 0,
                "records_with_order_without_identity": 0,
                "coordinates_unnormalisable": 0,
                "coordinates_declared_as_directory": None,
                "stages_named": 0, "stage_numbers_colliding_with_orders": [],
                "intervals": {"sessions": 1, "conversion_corroborated": 1,
                              "conversion_refuted": 0, "unparsed_start_count": 0,
                              "records_without_anchor": 0}}}))
        self.assertIn("НЕ ИЗМЕРЕНО — дерево базового ref не прочитано; это НЕ ноль",
                      printed)
        self.assertIn("[ОСЬ A · ДВЕРЬ] НЕ ИЗМЕРЕНО", printed)


class TestWiringMeasuredByCallAndByOutcome(unittest.TestCase):
    """Проводка — ВЫЗОВ и ИСХОД, а не импорт.

    Зелёный храповик ненужных ввозов читателем НЕ является: один импорт ради
    чужого правила гасит его, а предмет остаётся без читателя (ADR-547). Поэтому
    здесь: ось «мост ЗОВЁТ `run`» мерится ФОРМОЙ ВЫЗОВА, а ось «шаг 0-офис
    печатает ЧИСЛА» — исходом на настоящем модуле.
    """

    def _root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def test_the_bridge_CALLS_run_not_merely_imports_it(self):
        import ast
        source = (self._root() / "spa_core" / "monitoring"
                  / "findings_bridge.py").read_text(encoding="utf-8")
        calls = [node for node in ast.walk(ast.parse(source))
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "run"
                 and isinstance(node.func.value, ast.Name)
                 and node.func.value.id == "order_subject_census"]
        self.assertTrue(calls, "ступень обязана ЗВАТЬ `order_subject_census.run`, "
                               "а не только ввозить модуль")

    def test_the_bridge_declares_the_artifact_and_the_module(self):
        from spa_core.monitoring import findings_bridge as fb
        self.assertIn("order_subject_census", fb.CENSUS_PRODUCT)
        self.assertEqual(fb.CENSUS_PRODUCT["order_subject_census"]["artifact"],
                         f"data/{osc.ARTIFACT_NAME}")

    def test_the_office_step_prints_NUMBERS_of_the_artifact(self):
        """Иначе артефакт читается ВХОЛОСТУЮ — находка без читателя в цикле."""
        import importlib.util
        path = self._root() / "scripts" / "consume_office_reports.py"
        spec = importlib.util.spec_from_file_location("_osc_office", str(path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIn(osc.ARTIFACT_NAME, module._PRODUCER)
        with TemporaryDirectory() as tmp:
            holder = Path(tmp)
            repo = _repo(holder / "repo", ["spa_core/monitoring/a.py"])
            now = _now()
            _journal(holder, [_record(now, pid=71, start_minutes_ago=30,
                                      minutes_ago=10, summary="заказ G800 п. 1")])
            report = osc.run_census(holder, repo_root=repo, now=now,
                                    door=_FakeDoor(sees_order=False))
        lines = module._summarize_json(f"data/{osc.ARTIFACT_NAME}", report)
        self.assertGreater(len(lines), 5)
        self.assertTrue(any("ОСЬ A" in line for line in lines),
                        "ветка обязана печатать ось A, а не только отметку возраста")


class TestNoSecondCopyOfTheNeighboursMeasure(unittest.TestCase):
    """Помощники берутся У СОСЕДА: второй экземпляр мерки расходится молча."""

    def test_the_census_reuses_the_neighbours_helpers(self):
        source = Path(osc.__file__).read_text(encoding="utf-8")
        for helper in ("dsc.load_journal", "dsc.anchor_of", "dsc.read_base_tree",
                       "dsc.normalise", "dsc.kin_of", "dsc._dropped_coordinates",
                       "dsc.retirement_door", "dsc._retirement_verdict"):
            self.assertIn(helper, source,
                          f"{helper} обязан вызываться у соседа, а не переписываться")

    def test_the_journal_name_is_the_neighbours_literal(self):
        self.assertEqual(osc.JOURNAL_NAME, dsc.JOURNAL_NAME)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
