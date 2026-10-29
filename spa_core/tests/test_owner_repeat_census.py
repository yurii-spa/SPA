"""Повтор просьбы владельца — измеряемый сигнал шага 0a (ADR-860, цикл #977).

Каждый тест ниже — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ настоящей аварии 2026-10-29: в очереди стояли
37 карточек `new`, и все ПЯТЬ голосовых заданий владельца были одной просьбой — «проверь
дашборд», 15.10 · 16.10 · 16.10 · 17.10 · 24.10. Десять суток её не взял никто, а
прежняя мерка голода отвечала про неё НУЛЁМ: она спрашивает приоритет `critical` и
маркер ``## УКАЗАНИЕ ВЛАДЕЛЬЦА``, а голосовое задание рождается без того и без другого.
Тест `test_old_axis_is_blind_to_the_repeat` воспроизводит ровно эту слепоту — без него
новая ось была бы украшением (`.claude/rules/deployment.md`, «проверка сторожа сторожей»).
"""
# FROZEN-DATE-OK: injected-clock — AT это якорь сцены; КАЖДАЯ дата ниже выведена из него
# через day(days) и уезжает в настоящую меру аргументом `now=` (repeated_requests) либо
# полем `created` той же сцены. Стенных часов тест не спрашивает ни в одной ветке.
from __future__ import annotations

import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.analytics.telegram_daily_digest import TelegramDailyDigest
from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import owner_repeat_census as m

REPO = Path(__file__).resolve().parents[2]

#: Якорь сцены — день замера аварии.
AT = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def day(days: float) -> str:
    """Дата `YYYY-MM-DD`, отстоящая от якоря на `days` суток."""
    return (AT + timedelta(days=days)).date().isoformat()


def card(name: str, title: str, *, status: str = "new", source: str = "voice",
         created: str | None = None):
    return m._Card(name, title, status, source, created or day(-14))


#: Сцена аварии: пять просьб владельца одним текстом, 15.10…24.10.
def incident_cards():
    return [
        card("inbox-prover-dashbord-2.md", "проверь дашборд", created=day(-14)),
        card("inbox-prover-dashbord-3.md", "проверь дашборд", created=day(-13)),
        card("inbox-prover-dashbord-4.md", "проверь дашборд", created=day(-13)),
        card("inbox-prover-dashbord-5.md", "проверь дашборд", created=day(-12)),
        card("inbox-prover-dashbord-6.md", "проверь дашборд", created=day(-5)),
    ]


class TheIncidentIsMeasured(unittest.TestCase):
    """Авария 29.10: пять просьб обязаны стать ОДНОЙ находкой С ЧИСЛОМ."""

    def test_five_identical_requests_are_one_finding_with_a_number(self):
        groups = m.repeated_requests(incident_cards(), now=AT)
        self.assertEqual(len(groups), 1, "пять просьб одним текстом — одна группа")
        g = groups[0]
        self.assertEqual(g["count"], 5)
        self.assertEqual(g["first_created"], day(-14))
        self.assertEqual(g["last_created"], day(-5))
        self.assertEqual(g["span_days"], 9.0, "пролёт просьб — девять суток")
        self.assertEqual(g["age_days"], 14.5, "возраст старейшей считается от ЯКОРЯ")
        self.assertEqual(g["dates_unparsed"], 0)
        self.assertEqual(len(g["cards"]), 5)

    def test_the_rendered_line_carries_the_number_not_the_word(self):
        text = m.render(m.repeated_requests(incident_cards(), now=AT))
        self.assertIn("× 5", text, "повтор обязан быть НАЗВАН числом")
        self.assertIn("за 9 сут.", text)
        self.assertNotIn("НЕ ИЗМЕРЕН", text)

    def test_the_clock_is_an_input_not_the_wall(self):
        """Возраст меняется от ЧАСОВ, пролёт — нет. Иначе тест мерил бы календарь."""
        later = m.repeated_requests(incident_cards(), now=AT + timedelta(days=30))[0]
        now_ = m.repeated_requests(incident_cards(), now=AT)[0]
        self.assertEqual(later["span_days"], now_["span_days"])
        self.assertAlmostEqual(later["age_days"] - now_["age_days"], 30.0, places=6)


class TheOldAxisIsBlind(unittest.TestCase):
    """Без этого контроля новая ось — украшение: надо показать, что прежняя молчала."""

    def test_old_axis_is_blind_to_the_repeat(self):
        guard = _load_guard()
        found = guard.starving_owner_orders(incident_cards(), now=AT)
        self.assertEqual(found, [], "прежняя мерка (critical + маркер приказа) этих "
                                    "пяти просьб не видит ПО ПОСТРОЕНИЮ — это авария, "
                                    "а не особенность")
        self.assertTrue(m.repeated_requests(incident_cards(), now=AT),
                        "новая ось обязана видеть то, что прежняя пропустила")


class EveryLinkIsRead(unittest.TestCase):
    """Порви одно звено меры — и сцена обязана покраснеть именно на нём."""

    def test_source_is_read_agent_cards_are_out_of_the_population(self):
        """`source: nimbalyst` — канал находок агентов (замер: 258 штук `new`)."""
        cards = [card("a.md", "проверь дашборд"),
                 card("b.md", "проверь дашборд", source="nimbalyst")]
        self.assertEqual(m.repeated_requests(cards, now=AT), [],
                         "агентская карточка не имеет права стать просьбой владельца")

    def test_status_is_read_a_taken_card_is_not_a_repeat(self):
        cards = [card("a.md", "проверь дашборд"),
                 card("b.md", "проверь дашборд", status="in-progress")]
        self.assertEqual(m.repeated_requests(cards, now=AT), [])

    def test_a_single_request_is_measured_zero_not_a_finding(self):
        groups = m.repeated_requests([card("a.md", "проверь дашборд")], now=AT)
        self.assertEqual(groups, [])
        self.assertEqual(m.verdict_kind(groups), m.MEASURED_ZERO)

    def test_telegram_is_an_owner_channel_too(self):
        cards = [card("a.md", "проверь телеграм", source="telegram"),
                 card("b.md", "проверь телеграм", source="telegram")]
        self.assertEqual(len(m.repeated_requests(cards, now=AT)), 1)


class NormalisationIsNamed(unittest.TestCase):
    """Мера ловит ДОСЛОВНЫЙ повтор — ни больше (это сказано), ни меньше."""

    def test_case_spaces_and_edge_punctuation_collapse(self):
        self.assertEqual(m.normalise_request("  Проверь   ДАШБОРД.  "),
                         m.normalise_request("проверь дашборд"))

    def test_inner_punctuation_is_a_different_request(self):
        self.assertNotEqual(m.normalise_request("проверь, дашборд"),
                            m.normalise_request("проверь дашборд"))

    def test_a_paraphrase_is_not_caught_and_that_is_declared(self):
        """Цена названа в докстринге модуля: семантику мера не притязает."""
        cards = [card("a.md", "проверь дашборд"), card("b.md", "посмотри дашборд")]
        self.assertEqual(m.repeated_requests(cards, now=AT), [],
                         "занижение честнее, чем сведение разных просьб в одну")

    def test_an_empty_title_leaves_the_population(self):
        self.assertIsNone(m.normalise_request("   ...   "))
        cards = [card("a.md", "  "), card("b.md", "")]
        self.assertEqual(m.repeated_requests(cards, now=AT), [])


class ThreeOutcomesAreDistinguishable(unittest.TestCase):
    """Инв. #17: «не измерено» не имеет права выглядеть как «повторов нет»."""

    def test_none_is_unmeasured_and_an_empty_list_is_a_measured_zero(self):
        self.assertEqual(m.verdict_kind(None), m.UNMEASURED)
        self.assertEqual(m.verdict_kind([]), m.MEASURED_ZERO)
        self.assertEqual(m.verdict_kind(m.repeated_requests(incident_cards(), now=AT)),
                         m.REPEATED)

    def test_the_three_renders_are_three_different_texts(self):
        texts = {m.render(None, unmeasured_reason="очередь не прочитана"),
                 m.render([]),
                 m.render(m.repeated_requests(incident_cards(), now=AT))}
        self.assertEqual(len(texts), 3)
        self.assertIn("НЕ ИЗМЕРЕН", m.render(None))
        self.assertNotIn("НЕ ИЗМЕРЕН", m.render([]))

    def test_an_unparsable_date_gives_no_span_not_a_zero_span(self):
        cards = [card("a.md", "проверь дашборд", created="не-дата"),
                 card("b.md", "проверь дашборд", created="тоже-не-дата")]
        g = m.repeated_requests(cards, now=AT)[0]
        self.assertEqual(g["count"], 2)
        self.assertIsNone(g["span_days"], "ноль суток оправдывал бы простой")
        self.assertIsNone(g["age_days"])
        self.assertEqual(g["dates_unparsed"], 2)
        self.assertIn("НЕ ИЗМЕРЕН", m.render(m.repeated_requests(cards, now=AT)))

    def test_one_parsable_date_of_two_still_gives_no_span(self):
        cards = [card("a.md", "проверь дашборд", created=day(-14)),
                 card("b.md", "проверь дашборд", created="не-дата")]
        g = m.repeated_requests(cards, now=AT)[0]
        self.assertIsNone(g["span_days"], "пролёт нужен ДВА разобранных края")
        self.assertEqual(g["age_days"], 14.5, "возраст старейшей измерим и по одной дате")
        self.assertEqual(g["dates_unparsed"], 1)


class MergeIsFailClosed(unittest.TestCase):
    """«В другом дереве эту карточку закрыли» просьбу владельца не отменяет."""

    def test_a_group_seen_only_on_the_ref_survives(self):
        ref = m.repeated_requests(incident_cards(), now=AT, source="origin/main")
        merged = m.merge_groups([], ref)
        self.assertEqual([g["count"] for g in merged], [5])
        self.assertEqual(merged[0]["source"], "origin/main")

    def test_the_louder_copy_wins(self):
        tree = m.repeated_requests(incident_cards()[:2], now=AT, source="дерево")
        ref = m.repeated_requests(incident_cards(), now=AT, source="origin/main")
        merged = m.merge_groups(tree, ref)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["count"], 5)
        self.assertEqual(merged[0]["source"], "origin/main")

    def test_the_louder_copy_wins_the_other_way_round_too(self):
        tree = m.repeated_requests(incident_cards(), now=AT, source="дерево")
        ref = m.repeated_requests(incident_cards()[:2], now=AT, source="origin/main")
        merged = m.merge_groups(tree, ref)
        self.assertEqual(merged[0]["count"], 5)
        self.assertEqual(merged[0]["source"], "дерево")


class TheExemplarDistinguishes(unittest.TestCase):
    """Эталон, на котором стоит проба приёмки, обязан различать два исхода."""

    def test_drive_exemplar_gives_two_different_kinds(self):
        drive = m.drive_exemplar(now=AT)
        self.assertEqual(drive["kind"], m.DRIVE_DISTINGUISHES)
        self.assertEqual(drive["scene_repeated"]["outcome"], m.REPEATED)
        self.assertEqual(drive["scene_single"]["outcome"], m.MEASURED_ZERO)

    def test_the_noise_in_the_exemplar_really_is_excluded(self):
        """Сцена-одиночка несёт шум ТРЁХ видов, и ни один не должен стать повтором."""
        drive = m.drive_exemplar(now=AT)
        self.assertEqual(drive["scene_single"]["groups"], [])
        self.assertEqual(len(drive["scene_repeated"]["groups"]), 1)
        self.assertEqual(drive["scene_repeated"]["groups"][0]["count"], 2)


def _load_guard():
    spec = importlib.util.spec_from_file_location(
        "_starvation_under_test", REPO / "scripts" / "check_owner_order_starvation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_cards(where: Path, titles, *, source="voice", status="new"):
    where.mkdir(parents=True, exist_ok=True)
    for i, title in enumerate(titles, 1):
        (where / f"inbox-scene-{i}.md").write_text(
            "---\ntrackerStatus:\n  type: inbox\n"
            f"title: \"{title}\"\nstatus: {status}\nsource: {source}\n"
            f"created: {day(-14)}\n---\n\nтело\n", encoding="utf-8")


class Step0aNamesTheRepeat(unittest.TestCase):
    """Проводка: НАСТОЯЩИЙ шаг 0a на одноразовом трекере, а не моя копия его словаря."""

    def _run(self, titles, tmp: Path, as_json=True):
        _write_cards(tmp / "tracker", titles)
        argv = ["--tracker-dir", str(tmp / "tracker"), "--ref", "", "--no-write"]
        if as_json:
            argv.append("--json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _load_guard().main(argv)
        return rc, buf.getvalue()

    def test_the_repeat_changes_the_verdict_of_the_real_step(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            rc_rep, out_rep = self._run(["проверь дашборд", "проверь дашборд"],
                                        Path(d) / "a")
            rc_one, out_one = self._run(["проверь дашборд"], Path(d) / "b")
        self.assertEqual(rc_rep, 3, "повтор обязан давать код НАХОДКИ")
        self.assertEqual(rc_one, 0, "одиночная просьба находкой не является")
        doc_rep, doc_one = json.loads(out_rep), json.loads(out_one)
        # Спрашивается ПРИСУТСТВИЕ ключа и его значение, а не слова печати: текст,
        # собранный из того же числа, подтверждал бы сам себя (ADR-333).
        for key in ("repeated_groups", "repeated_cards", "repeat_groups"):
            self.assertIn(key, doc_rep)
            self.assertIn(key, doc_one)
        self.assertEqual(doc_rep["repeated_cards"], 2)
        self.assertEqual(doc_rep["repeated_groups"], 1)
        self.assertEqual(doc_one["repeated_cards"], 0)
        self.assertEqual(doc_one["repeated_groups"], 0)

    def test_the_human_text_of_the_real_step_names_the_number(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            rc, out = self._run(["проверь дашборд", "проверь дашборд"],
                                Path(d) / "a", as_json=False)
        self.assertEqual(rc, 3)
        self.assertIn("× 2", out)
        self.assertIn("ВЛАДЕЛЕЦ ПОВТОРИЛ", out)

    def test_an_agent_channel_scene_leaves_the_step_clean(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d) / "a"
            _write_cards(tmp / "tracker", ["находка переписи", "находка переписи"],
                         source="nimbalyst")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = _load_guard().main(["--tracker-dir", str(tmp / "tracker"),
                                         "--ref", "", "--no-write", "--json"])
        self.assertEqual(rc, 0, "две одинаковые карточки АГЕНТА повтором владельца не являются")
        self.assertEqual(json.loads(buf.getvalue())["repeated_cards"], 0)


class TheReportCarriesTheAxis(unittest.TestCase):
    """Отчёт читает владелец через дайджест — ось обязана доехать до него."""

    def test_build_report_without_the_axis_says_unmeasured_not_zero(self):
        guard = _load_guard()
        doc = guard.build_report([], 24.0, AT)
        self.assertIsNone(doc["repeated_groups"], "вызывающий, не знающий оси, обязан "
                                                  "получить третий исход, а не ноль")
        self.assertIsNone(doc["repeat_groups"])

    def test_build_report_with_the_axis_carries_both_numbers(self):
        guard = _load_guard()
        groups = m.repeated_requests(incident_cards(), now=AT)
        doc = guard.build_report([], 24.0, AT, repeat_groups=groups)
        self.assertEqual(doc["repeated_groups"], 1)
        self.assertEqual(doc["repeated_cards"], 5)

    def test_the_digest_names_the_repeat_to_the_owner(self):
        groups = m.repeated_requests(incident_cards(), now=AT)
        lines = TelegramDailyDigest()._starvation_repeat_lines(
            {"repeat_groups": groups, "repeats_unmeasured": None})
        joined = "\n".join(lines)
        self.assertIn("групп 1", joined)
        self.assertIn("карточек 5", joined)

    def test_the_digest_distinguishes_three_outcomes(self):
        d = TelegramDailyDigest()
        absent = "\n".join(d._starvation_repeat_lines({}))
        zero = "\n".join(d._starvation_repeat_lines({"repeat_groups": []}))
        partial = "\n".join(d._starvation_repeat_lines(
            {"repeat_groups": [], "repeats_unmeasured": "очередь на `origin/main` не прочитана"}))
        self.assertIn("НЕ ИЗМЕРЕН", absent)
        self.assertNotIn("НЕ ИЗМЕРЕН", zero)
        self.assertIn("НЕ ПОЛНОСТЬЮ", partial)
        self.assertEqual(len({absent, zero, partial}), 3)

    def test_an_old_report_without_the_key_is_not_read_as_a_zero(self):
        """Отчёт мог написать прежний сторож, который оси не знал."""
        lines = TelegramDailyDigest()._starvation_repeat_lines(
            {"generated_at": AT.isoformat(), "findings": []})
        self.assertTrue(any("НЕ ИЗМЕРЕН" in ln for ln in lines))


class TheEarnedReleaseLeavesARecord(unittest.TestCase):
    """Авария того же цикла: освобождение выдавалось и НЕ ЗАПИСЫВАЛОСЬ (ADR-860, замер 3).

    `carried_to` был параметром вызова и только им: исполнитель условие проверял,
    сторож читает ЗАПИСЬ во фронтматтере — и записи не делал никто. Законно сведённый
    носитель оставался «закрытым без критерия приёмки» навсегда.
    """

    def _scene(self, tmp: Path):
        tracker = tmp / "nimbalyst-local" / "tracker"
        tracker.mkdir(parents=True)
        target = tracker / "inbox-anchor.md"
        target.write_text("---\ntrackerStatus:\n  type: inbox\ntitle: якорь\n"
                          "status: new\n---\n\nтело\n", encoding="utf-8")
        carrier = tracker / "inbox-carrier.md"
        carrier.write_text("---\ntrackerStatus:\n  type: inbox\ntitle: носитель\n"
                           "status: new\nsource: voice\n---\n\nтело\n", encoding="utf-8")
        return carrier, target

    def test_the_record_is_written_and_is_repo_relative(self):
        import tempfile
        from spa_core.owner_queue.queue import carried_release, set_status
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            carrier, target = self._scene(tmp)
            set_status(carrier, "done", carried_to=target, repo_root=tmp)
            text = carrier.read_text(encoding="utf-8")
            head = text.split("---")[1]
            self.assertIn("carried_to: nimbalyst-local/tracker/inbox-anchor.md", head,
                          "запись обязана быть от КОРНЯ РЕПО: абсолютный путь worktree "
                          "на origin не значит ничего")
            self.assertNotIn(str(tmp), head, "абсолютный путь дерева в карточку не едет")
            # Та же дверь, которой судит сторож, обязана прочитать запись.
            resolved, why = carried_release("nimbalyst-local/tracker/inbox-anchor.md",
                                            carrier, repo_root=tmp)
            self.assertIsNotNone(resolved, why)

    def test_a_closure_without_a_carry_writes_no_record(self):
        """Контроль в обратную сторону: запись не появляется сама по себе."""
        import tempfile
        from spa_core.owner_queue.queue import set_status
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            carrier, _ = self._scene(tmp)
            # Критерий у карточки объявлен, иначе переход откажет по ДРУГОЙ причине и
            # тест отвечал бы не на свой вопрос.
            carrier.write_text(carrier.read_text(encoding="utf-8").replace(
                "source: voice\n", "source: voice\nacceptance_probe: problem_absent\n"),
                encoding="utf-8")
            set_status(carrier, "in-progress", repo_root=tmp)
            self.assertNotIn("carried_to:", carrier.read_text(encoding="utf-8"))

    def test_an_existing_record_is_replaced_not_duplicated(self):
        import tempfile
        from spa_core.owner_queue.queue import set_status
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            carrier, target = self._scene(tmp)
            carrier.write_text(carrier.read_text(encoding="utf-8").replace(
                "source: voice\n", "source: voice\ncarried_to: nimbalyst-local/tracker/stale.md\n"),
                encoding="utf-8")
            set_status(carrier, "done", carried_to=target, repo_root=tmp)
            text = carrier.read_text(encoding="utf-8")
            self.assertEqual(text.count("carried_to:"), 1)
            self.assertIn("inbox-anchor.md", text)
            self.assertNotIn("stale.md", text)

    def test_a_refused_carry_writes_nothing_at_all(self):
        """Отказ обязан оставить карточку нетронутой — иначе запись врала бы."""
        import tempfile
        from spa_core.owner_queue.queue import (AcceptanceCriterionMissing,
                                                set_status)
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            carrier, _ = self._scene(tmp)
            before = carrier.read_text(encoding="utf-8")
            with self.assertRaises(AcceptanceCriterionMissing):
                set_status(carrier, "done",
                           carried_to=tmp / "nimbalyst-local/tracker/net-takogo.md",
                           repo_root=tmp)
            self.assertEqual(carrier.read_text(encoding="utf-8"), before)


class TheProbeIsRegistered(unittest.TestCase):
    """Критерий приёмки карточки обязан существовать в реестре и быть вызываемым."""

    def test_the_probe_is_in_the_registry(self):
        self.assertIn("owner_repeat_named_by_the_hunger_step", ca.PROBES)

    def test_the_probe_reaches_a_verdict_and_never_invents_one(self):
        verdict, detail = ca.PROBES["owner_repeat_named_by_the_hunger_step"](None)
        self.assertIn(verdict, (ca.SATISFIED, ca.NOT_SATISFIED, ca.UNMEASURED))
        self.assertTrue(detail.strip(), "вердикт без причины неотличим от молчания")


if __name__ == "__main__":
    unittest.main()
