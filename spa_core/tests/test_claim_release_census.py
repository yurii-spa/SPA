#!/usr/bin/env python3
"""Контроли прибора «кто и когда закрывает захват» — заказ **G88 п. 2** (ADR-498).

Каждый тест — ОДНО порванное звено с названным именем, либо положительный контроль,
воспроизводящий настоящую аварию:

* освобождение, адресованное ДЕРЖАТЕЛЮ, не снимает захват предшественника — хотя про
  карточку уже сказано «закрыта» (замер 02.10: 450 из 557 захватов);
* ОДНА сессия под ДВУМЯ ярлыками: по ярлыку захват остался бы вечным, по якорю он
  закрыт (ADR-498 — «считать ярлыки разными сессиями значило бы изготовить дефект из
  ФОРМЫ записи»);
* ``holder_unmeasured`` (якоря нет вовсе, как у ``cycle-74714``) **не** попадает в
  мёртвых: «нечем спросить» не есть «поймали» (инв. #17);
* цена лестницы при неизмеренной задержке — ``None``, а НЕ нуль: нуль читался бы как
  «срок ничего не стоит» (урок ``pyflakes``, `.claude/rules/deployment.md`).

Время и живость здесь — ВХОДЫ, а не окружение: якорь `_NOW` связывается с именем, из
него ПРОИСХОДЯТ все отметки записей (`_stamp`), и он же уезжает аргументом `now=` в
`build_report`; `ps=`/`cmd_probe=` подменяют обе двери к ОС. Ни календарь хоста, ни
чужой pid на вердикт здесь не влияют.
"""
# FROZEN-DATE-OK: injected-clock — якорь `_NOW` (datetime-литерал) связан с именем,
# все отметки записей происходят от него вычитанием (`_stamp`), и он же передаётся
# аргументом `now=` в `build_report`. Живость процесса инъектируется отдельно
# (`ps=`, `cmd_probe=`), поэтому обе двери к ОС для этого пути закрыты.
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from spa_core.monitoring import claim_release_census as crc

#: Якорь времени сцены. ВСЕ отметки записей происходят отсюда вычитанием, и он же
#: уезжает аргументом `now=` — поэтому календарь хоста на вердикт не влияет.
_NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)

#: Время старта процесса в форме `ps -o lstart=`. Литерал здесь — ВХОД сцены: он
#: одновременно лежит в записи и возвращается поддельным `ps`, поэтому «тот же
#: процесс» измеряется сверкой двух входов, а не вопросом к живой машине.
_LSTART = "Fri Oct  2 06:50:02 2026"


def _stamp(hours_ago: float) -> str:
    """Отметка времени, ПРОИСХОДЯЩАЯ от якоря сцены."""
    return (_NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(card, state, *, hours_ago, label="cycle-1", pid=None, start=_LSTART):
    row = {"ts": _stamp(hours_ago), "session": label, "summary": "s",
           "files": [], "verified": "v", "card": card, "card_state": state}
    if pid is not None:
        row["session_pid"] = pid
        row["session_pid_start"] = start
    return row


def _ps_dead(pid):
    """`ps -p <pid>` — процесса нет (rc=1). Это ИЗМЕРЕННАЯ смерть держателя."""
    return 1, ""


def _ps_alive(pid):
    """`ps -p <pid>` — процесс жив и это ТОТ ЖЕ процесс (старт совпадает с записью)."""
    return 0, _LSTART


def _ps_broken(pid):
    """`ps` не отработал (rc=127) — живость НЕ ИЗМЕРЕНА, а не «мёртв»."""
    return 127, ""


def _cmd_session(pid):
    """Команда процесса: сессия, а не таймер (`sleep` отвергается шагом 0a)."""
    return 0, "/usr/bin/claude -p orchestrator"


class _Scene(unittest.TestCase):
    """Общая сцена: одноразовое дерево с журналом и настоящими соседями."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="crc_scene_")
        self.root = Path(self.tmp)
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        # Соседи грузятся из НАСТОЯЩЕГО дерева: правило освобождения и живость
        # держателя обязаны быть теми же, что в проде (ADR-220 — второй экземпляр
        # мерки расходится с первым молча).
        self.kin = crc.load_neighbours(ROOT)
        self.assertEqual(self.kin["missing"], [],
                         "соседние мерки не загрузились — сцена недостоверна")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _journal(self, rows):
        path = self.root / "data" / "session_changes.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                        encoding="utf-8")
        return path

    def _report(self, rows, *, ps=_ps_dead, cmd_probe=_cmd_session):
        return crc.build_report(self.root, now=_NOW, journal_path=self._journal(rows),
                                ps=ps, cmd_probe=cmd_probe, neighbours=self.kin)


class TestReleaseAddressee(_Scene):
    """Положительный контроль настоящей аварии: освобождение адресовано ДЕРЖАТЕЛЮ."""

    def test_claim_stays_open_though_the_card_was_declared_done_by_another(self):
        rows = [
            _record("card-a", "claim", hours_ago=100, label="cycle-1", pid=4001),
            # Работу доделала ДРУГАЯ сессия и объявила карточку закрытой.
            _record("card-a", "done", hours_ago=50, label="cycle-2", pid=4002),
        ]
        report = self._report(rows)
        self.assertTrue(report["measured"], report.get("reason"))
        self.assertEqual(report["status"], crc.STATUS_TO_HOLDER)
        self.assertEqual(report["open_claims"]["open_claims"], 1)
        self.assertEqual(report["open_claims"]["card_declared_done_by_another_identity"], 1)
        self.assertEqual(report["open_claims"]["card_never_declared_done"], 0)
        self.assertEqual(crc.exit_code_for(report), 1,
                         "захват, открытый при закрытой карточке, — находка, а не норма")

    def test_release_by_the_same_identity_does_close_the_claim(self):
        """Порванное звено: та же личность ⇒ захват закрыт, вердикт поворачивается."""
        rows = [
            _record("card-a", "claim", hours_ago=100, label="cycle-1", pid=4001),
            _record("card-a", "done", hours_ago=99, label="cycle-1", pid=4001),
        ]
        report = self._report(rows)
        self.assertTrue(report["measured"], report.get("reason"))
        self.assertEqual(report["status"], crc.STATUS_TO_CARD)
        self.assertEqual(crc.exit_code_for(report), 0)

    def test_verdict_is_not_chosen_by_substring(self):
        """Вердикт выводится из ПОЛЯ замера, а не из совпадения текста (ADR-333)."""
        rows = [
            _record("RELEASE_ADDRESSED_TO_CARD", "claim", hours_ago=100,
                    label="cycle-1", pid=4001),
            _record("RELEASE_ADDRESSED_TO_CARD", "done", hours_ago=50,
                    label="cycle-2", pid=4002),
        ]
        report = self._report(rows)
        self.assertEqual(report["status"], crc.STATUS_TO_HOLDER,
                         "имя карточки, совпадающее с вердиктом, вердикта не назначает")


class TestIdentityIsAnchorNotLabel(_Scene):
    """ADR-498: ярлык у одной сессии бывает не один, и это не её раздвоение."""

    def test_one_session_two_labels_one_anchor_closes_its_own_claim(self):
        rows = [
            _record("card-a", "claim", hours_ago=10, label="pid32079", pid=4001),
            # Тот же ЯКОРЬ (pid+старт), другой ЯРЛЫК — это ОДНА сессия.
            _record("card-a", "done", hours_ago=9, label="pid37690", pid=4001),
        ]
        report = self._report(rows)
        self.assertTrue(report["measured"], report.get("reason"))
        self.assertEqual(report["status"], crc.STATUS_TO_CARD,
                         "по ЯКОРЮ это одна сессия: захват закрыт, а не вечен")
        self.assertEqual(report["latency"]["closed_pairs"], 1)
        self.assertEqual(report["open_claims"]["open_claims"], 0)

    def test_label_fallback_is_named_not_hidden(self):
        """Якоря нет ⇒ личность по ярлыку, и доля подмены ОБЪЯВЛЕНА в отчёте."""
        rows = [
            _record("card-a", "claim", hours_ago=10, label="cycle-7"),
            _record("card-a", "done", hours_ago=9, label="cycle-7"),
        ]
        report = self._report(rows)
        self.assertEqual(report["writers"]["identity_from"]["label"], 1)
        self.assertEqual(report["writers"]["identity_from"]["anchor"], 0)


class TestWriterAxis(_Scene):
    """Ось A: вопрос у ПИСАТЕЛЯ, а не по имени поля."""

    def test_a_release_without_a_prior_claim_released_nothing(self):
        rows = [
            _record("card-a", "claim", hours_ago=100, label="cycle-1", pid=4001),
            _record("card-b", "done", hours_ago=50, label="cycle-9", pid=4009),
        ]
        report = self._report(rows)
        writers = report["writers"]
        self.assertEqual(writers["releases_total"], 1)
        self.assertEqual(writers["released_own_prior_claim"], 0)
        self.assertEqual(writers["released_nothing"], 1)

    def test_a_release_before_its_own_claim_does_not_count_as_released(self):
        """Порядок во времени существенен: `done` РАНЬШЕ захвата его не снимает."""
        rows = [
            _record("card-a", "done", hours_ago=100, label="cycle-1", pid=4001),
            _record("card-a", "claim", hours_ago=50, label="cycle-1", pid=4001),
        ]
        report = self._report(rows)
        self.assertEqual(report["writers"]["released_nothing"], 1)
        self.assertEqual(report["open_claims"]["open_claims"], 1)


class TestHolderLivenessHasThreeOutcomes(_Scene):
    """Ось C: жив · измеренно мёртв · НЕ ИЗМЕРЕН — и третий не сливается со вторым."""

    def _one_open_claim(self, *, pid, ps):
        rows = [_record("card-a", "claim", hours_ago=100, label="cycle-1", pid=pid)]
        return self._report(rows, ps=ps)

    def test_dead_holder_is_measured_dead(self):
        report = self._one_open_claim(pid=4001, ps=_ps_dead)
        self.assertEqual(report["open_claims"]["by_holder"][crc.HOLDER_DEAD], 1)
        self.assertEqual(report["open_claims"]["by_holder"][crc.HOLDER_UNMEASURED], 0)

    def test_live_holder_is_not_dead(self):
        report = self._one_open_claim(pid=4001, ps=_ps_alive)
        self.assertEqual(report["open_claims"]["by_holder"][crc.HOLDER_ALIVE], 1)
        self.assertEqual(report["open_claims"]["by_holder"][crc.HOLDER_DEAD], 0)

    def test_no_anchor_at_all_is_unmeasured_not_dead(self):
        """`cycle-74714` без pid: активность НЕ ИЗМЕРЕНА — обвинять нечем (инв. #17)."""
        rows = [_record("card-a", "claim", hours_ago=100, label="cycle-74714")]
        report = self._report(rows, ps=_ps_dead)
        by_holder = report["open_claims"]["by_holder"]
        self.assertEqual(by_holder[crc.HOLDER_UNMEASURED], 1)
        self.assertEqual(by_holder[crc.HOLDER_DEAD], 0,
                         "«нечем спросить» выдано за «поймали» — ровно тот fail-OPEN, "
                         "против которого написан инвариант #17")

    def test_broken_ps_is_unmeasured_not_dead(self):
        report = self._one_open_claim(pid=4001, ps=_ps_broken)
        by_holder = report["open_claims"]["by_holder"]
        self.assertEqual(by_holder[crc.HOLDER_UNMEASURED], 1)
        self.assertEqual(by_holder[crc.HOLDER_DEAD], 0)


class TestExpiryLadderIsTwoSided(_Scene):
    """Ось D: четыре числа на ступени, и срок прибор НЕ называет."""

    def test_dead_holder_older_than_the_ttl_would_close(self):
        rows = [_record("card-a", "claim", hours_ago=100, label="cycle-1", pid=4001)]
        report = self._report(rows, ps=_ps_dead)
        steps = {s["ttl_hours"]: s for s in report["expiry_ladder"]["ladder"]}
        self.assertEqual(steps[72]["all_open"]["would_close_dead_holder"], 1)
        self.assertEqual(steps[168]["all_open"]["would_close_dead_holder"], 0,
                         "захват моложе срока закрыться не может")

    def test_a_live_holder_appears_as_a_COST_not_as_a_benefit(self):
        rows = [_record("card-a", "claim", hours_ago=100, label="cycle-1", pid=4001)]
        report = self._report(rows, ps=_ps_alive)
        step = {s["ttl_hours"]: s for s in report["expiry_ladder"]["ladder"]}[72]
        self.assertEqual(step["all_open"]["would_evict_live_holder"], 1)
        self.assertEqual(step["all_open"]["would_close_dead_holder"], 0,
                         "выгнанный ЖИВОЙ держатель, зачтённый как польза, и есть "
                         "односторонняя лестница — то, что заказ запретил")

    def test_the_narrow_population_excludes_claims_whose_card_was_closed(self):
        """Срок — лекарство ТОЛЬКО для узкого населения; остальным он маскировка.

        Сцена намеренно АСИММЕТРИЧНА (два захвата с закрытой карточкой против одного
        без): при равных долях перевёрнутый отбор дал бы ТО ЖЕ число, и мутация
        `not r[...]` → `r[...]` выжила бы — она и выжила в первом прогоне."""
        rows = [
            _record("card-a", "claim", hours_ago=100, label="cycle-1", pid=4001),
            _record("card-a", "done", hours_ago=50, label="cycle-2", pid=4002),
            _record("card-b", "claim", hours_ago=100, label="cycle-3", pid=4003),
            _record("card-b", "done", hours_ago=50, label="cycle-4", pid=4004),
            # Единственный, чью карточку не объявлял закрытой никто.
            _record("card-c", "claim", hours_ago=100, label="cycle-5", pid=4005),
        ]
        report = self._report(rows, ps=_ps_dead)
        ladder = report["expiry_ladder"]
        self.assertEqual(report["open_claims"]["card_declared_done_by_another_identity"], 2)
        self.assertEqual(ladder["narrow_population"], 1,
                         "card-a и card-b закрыты другой личностью ⇒ в узкое население "
                         "не идут; перевёрнутый отбор дал бы 2")
        step = {s["ttl_hours"]: s for s in ladder["ladder"]}[72]
        self.assertEqual(step["all_open"]["would_close_dead_holder"], 3)
        self.assertEqual(step["card_never_declared_done"]["would_close_dead_holder"], 1,
                         "по узкому населению срок закрыл бы РОВНО card-c")

    def test_cost_is_None_when_latency_is_unmeasured(self):
        """Порванное звено: закрытых пар ноль ⇒ цена `None`, а НЕ нуль."""
        rows = [_record("card-a", "claim", hours_ago=100, label="cycle-1", pid=4001)]
        report = self._report(rows, ps=_ps_dead)
        self.assertFalse(report["latency"]["measured"])
        for step in report["expiry_ladder"]["ladder"]:
            self.assertIsNone(step["would_have_cut_self_closing_work"],
                              "нуль здесь читался бы как «срок ничего не стоит» — "
                              "это подмена «не измерено» числом")

    def test_cost_counts_self_closing_work_longer_than_the_ttl(self):
        rows = [
            # Закрылась сама через 80 ч — срок 72 ч оборвал бы её, срок 168 ч нет.
            _record("card-a", "claim", hours_ago=100, label="cycle-1", pid=4001),
            _record("card-a", "done", hours_ago=20, label="cycle-1", pid=4001),
            _record("card-b", "claim", hours_ago=200, label="cycle-3", pid=4003),
        ]
        report = self._report(rows, ps=_ps_dead)
        steps = {s["ttl_hours"]: s for s in report["expiry_ladder"]["ladder"]}
        self.assertEqual(steps[72]["would_have_cut_self_closing_work"], 1)
        self.assertEqual(steps[168]["would_have_cut_self_closing_work"], 0)

    def test_the_instrument_refuses_to_name_a_ttl(self):
        rows = [_record("card-a", "claim", hours_ago=100, label="cycle-1", pid=4001)]
        report = self._report(rows, ps=_ps_dead)
        self.assertIn("НЕ называет", report["expiry_ladder"]["refuses_to_name_a_ttl"])
        self.assertFalse(report["applied"], "прибор только ЧИТАЕТ")


class TestThirdOutcome(_Scene):
    """«Не измерено» — отдельный исход с названной причиной и кодом 2 (инв. #17)."""

    def test_missing_journal_is_unmeasured(self):
        report = crc.build_report(self.root, now=_NOW,
                                  journal_path=self.root / "data" / "absent.jsonl",
                                  ps=_ps_dead, cmd_probe=_cmd_session,
                                  neighbours=self.kin)
        self.assertFalse(report["measured"])
        self.assertEqual(report["status"], crc.STATUS_UNMEASURED)
        self.assertIn("журнал не прочитан", report["reason"])
        self.assertEqual(crc.exit_code_for(report), 2)

    def test_zero_claims_is_unmeasured_not_clean(self):
        """«Все захваты закрыты» при нуле захватов верно ПО ПОСТРОЕНИЮ — это fail-OPEN."""
        report = self._report([{"ts": _stamp(1), "session": "cycle-1", "summary": "s",
                                "files": [], "verified": "v"}])
        self.assertFalse(report["measured"])
        self.assertIn("ПО ПОСТРОЕНИЮ", report["reason"])
        self.assertEqual(crc.exit_code_for(report), 2)
        self.assertEqual(report["population"]["claims"], 0,
                         "население объявлено ДАЖЕ в третьем исходе")

    def test_zero_OPEN_claims_is_a_MEASURED_zero_not_unmeasured(self):
        """Положительный контроль дефекта, найденного этой же батареей.

        Первая редакция прибора на нуле НЕЗАКРЫТЫХ захватов отвечала `UNMEASURED` —
        то есть склеивала второй и третий исходы инварианта #17 («измерено и равно
        нулю» против «не измерено»), и здоровый контур докладывал бы «не измерено».
        Третий исход законен только на нуле ЗАХВАТОВ (там мерить нечего по
        построению) — и он проверяется отдельным тестом выше."""
        rows = [
            _record("card-a", "claim", hours_ago=10, label="cycle-1", pid=4001),
            _record("card-a", "done", hours_ago=9, label="cycle-1", pid=4001),
        ]
        report = self._report(rows)
        self.assertTrue(report["measured"], report.get("reason"))
        self.assertEqual(report["status"], crc.STATUS_TO_CARD)
        self.assertEqual(report["open_claims"]["open_claims"], 0)
        self.assertIsNone(report["open_claims"]["age_hours"],
                          "возраст у пустого множества — `None`, а не нуль: нуль читался "
                          "бы как «захват взят только что»")
        self.assertEqual(crc.exit_code_for(report), 0)
        # И лестница при этом ОБЪЯВЛЕНА, а не пропала: ноль на каждой ступени.
        step = {s["ttl_hours"]: s for s in report["expiry_ladder"]["ladder"]}[24]
        self.assertEqual(step["all_open"]["would_close_dead_holder"], 0)

    def test_missing_neighbours_is_unmeasured(self):
        """Порванное звено: без соседей своего экземпляра мерки у прибора нет."""
        report = crc.build_report(self.root, now=_NOW,
                                  journal_path=self._journal([]),
                                  neighbours={"guard": None, "sibling": None,
                                              "missing": ["check_card_claim"]})
        self.assertFalse(report["measured"])
        self.assertIn("check_card_claim", report["reason"])
        self.assertEqual(crc.exit_code_for(report), 2)

    def test_broken_lines_are_counted_not_swallowed(self):
        path = self.root / "data" / "session_changes.jsonl"
        path.write_text(json.dumps(_record("card-a", "claim", hours_ago=100,
                                           label="cycle-1", pid=4001)) + "\n"
                        + "{не json\n", encoding="utf-8")
        report = crc.build_report(self.root, now=_NOW, journal_path=path,
                                  ps=_ps_dead, cmd_probe=_cmd_session,
                                  neighbours=self.kin)
        self.assertEqual(report["population"]["broken_lines"], 1)

    def test_record_with_unparsed_ts_is_counted_separately(self):
        rows = [_record("card-a", "claim", hours_ago=100, label="cycle-1", pid=4001)]
        rows.append({"ts": "не дата", "session": "cycle-2", "summary": "s",
                     "files": [], "verified": "v", "card": "card-b",
                     "card_state": "claim"})
        report = self._report(rows)
        self.assertEqual(report["population"]["records_with_card_unparsed_ts"], 1)
        self.assertEqual(report["population"]["claims"], 1,
                         "запись без разобранной отметки в захваты не идёт")


class TestReportShapeIsConstant(_Scene):
    """Форма отчёта постоянна: шаг 0-офис обязан отличать «не вычислено» от отсутствия."""

    _KEYS = ("generated_at", "order", "measured", "status", "reason", "applied",
             "population", "writers", "latency", "open_claims", "expiry_ladder")

    def test_all_keys_declared_on_the_measured_path(self):
        rows = [
            _record("card-a", "claim", hours_ago=100, label="cycle-1", pid=4001),
            _record("card-a", "done", hours_ago=50, label="cycle-2", pid=4002),
        ]
        report = self._report(rows)
        for key in self._KEYS:
            self.assertIn(key, report)

    def test_all_keys_declared_on_the_unmeasured_path(self):
        report = crc.build_report(self.root, now=_NOW,
                                  journal_path=self.root / "data" / "absent.jsonl",
                                  ps=_ps_dead, cmd_probe=_cmd_session,
                                  neighbours=self.kin)
        for key in self._KEYS:
            self.assertIn(key, report)

    def test_format_report_speaks_on_the_unmeasured_path(self):
        report = crc.build_report(self.root, now=_NOW,
                                  journal_path=self.root / "data" / "absent.jsonl",
                                  ps=_ps_dead, cmd_probe=_cmd_session,
                                  neighbours=self.kin)
        lines = crc.format_report(report)
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in line for line in lines))

    def test_format_report_names_both_sides_of_the_ladder(self):
        rows = [
            _record("card-a", "claim", hours_ago=100, label="cycle-1", pid=4001),
            _record("card-a", "done", hours_ago=50, label="cycle-2", pid=4002),
        ]
        lines = crc.format_report(self._report(rows))
        text = "\n".join(lines)
        self.assertIn("выгнал бы ЖИВОГО", text)
        self.assertIn("оборвал бы работу", text)
        self.assertIn("ADVISORY", text)

    def test_artifact_is_written_even_when_unmeasured(self):
        report = crc.build_report(self.root, now=_NOW,
                                  journal_path=self.root / "data" / "absent.jsonl",
                                  ps=_ps_dead, cmd_probe=_cmd_session,
                                  neighbours=self.kin)
        path = crc.save_artifact(report, self.root / "data")
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertFalse(saved["measured"])
        self.assertEqual(Path(path).name, crc.ARTIFACT_NAME)


class TestGuardReallyKeysReleasesByLabel(unittest.TestCase):
    """Положительный контроль ПОСЫЛКИ находки: правило освобождения у сторожа —
    по личности писателя. Меряется ИСХОДОМ настоящего сторожа, а не чтением кода."""

    def test_releases_by_session_is_keyed_by_the_writer_not_by_the_card(self):
        kin = crc.load_neighbours(ROOT)
        self.assertEqual(kin["missing"], [])
        guard, sibling = kin["guard"], kin["sibling"]
        entries = [
            {"ts": _stamp(10), "session": "cycle-1", "card": "card-a",
             "card_state": "claim"},
            {"ts": _stamp(5), "session": "cycle-2", "card": "card-a",
             "card_state": "done"},
        ]
        released = guard.releases_by_session(entries, sibling._parse_ts)
        self.assertIn("cycle-2", released)
        self.assertNotIn("cycle-1", released,
                         "если бы освобождение адресовалось КАРТОЧКЕ, захват cycle-1 "
                         "был бы снят — находка прибора держится на этом исходе")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
