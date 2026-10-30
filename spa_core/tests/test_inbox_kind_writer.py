"""Ось «род записи» имеет ПИСАТЕЛЯ, а три её исхода различимы (ADR-873).

Каждый тест здесь — положительный контроль настоящего замера #990/#991 на `origin/main`:

* из **1534** карточек трекера `intake_kind` несли **0** — у оси был читатель и не было
  писателя, поэтому `kind_unknown` равнялся `new_total` ПО ПОСТРОЕНИЮ (ложная ПОЛНОТА);
* запасной ключ `type` отвечал НЕ НА ТОТ вопрос: все 43 его значения — ТРЕКЕРНЫЙ тип, и
  четыре карточки `new` получали из него род `inbox`, которого им никто не объявлял;
* копий словаря рода было ТРИ, и расходились они ровно на третьем исходе — у писателей
  был `note`, у читателя (докстринг) «непонятно», и объявить «непонятно» не мог никто.

# FROZEN-DATE-OK: injected-clock — все сцены зовут triage(..., now=<якорь>), и возраст
# карточек считается от `created`, который сцена кладёт сама; стенных часов тест не видит.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.owner_queue import triage as T
from spa_core.owner_queue.queue import IntakeKindRefused, set_intake_kind

_NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
_REPO = Path(__file__).resolve().parents[2]


def _card(d: Path, name: str, fm: dict, body: str = "тело\n") -> Path:
    p = d / name
    lines = ["---"]
    for k, v in fm.items():
        lines.append(f"{k}: {v}")
    lines += ["---", "", body]
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _canonical(d: Path, name: str, status: str = "new", **extra) -> Path:
    """Карточка КАНОНИЧЕСКОГО вида: тип вложен в `trackerStatus`, как у всех 1490 живых."""
    p = d / name
    lines = ["---", "trackerStatus:", "  type: inbox", f'title: "{name}"', f"status: {status}",
             f"created: {_NOW.date().isoformat()}"]
    for k, v in extra.items():
        lines.append(f"{k}: {v}")
    lines += ["---", "", "тело", ""]
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


class KindReaderDistinguishesThreeOutcomes(unittest.TestCase):
    """Объявлен · объявлен вне словаря · НЕ объявлен — три разных числа (инв. #17)."""

    def setUp(self):
        import tempfile
        self.d = Path(tempfile.mkdtemp(prefix="spa_kind_"))

    def test_declared_kind_is_reported_and_is_not_unknown(self):
        _canonical(self.d, "inbox-a.md", intake_kind="idea")
        rep = T.triage(self.d, now=_NOW)
        self.assertEqual(rep["rows"][0]["kind"], "idea")
        self.assertEqual(rep["kind_unknown"], 0)
        self.assertEqual(rep["kind_declared"], 1)
        self.assertEqual(rep["kind_counts"]["idea"], 1)

    def test_unclear_is_a_DECLARED_kind_not_an_absence(self):
        """«Непонятно» — ответ разбора, а не его отсутствие.

        Свести их значило бы вернуть ровно тот обмен, против которого написан инв. #17:
        сессия, не сумевшая классифицировать, и сессия, до карточки не дошедшая, — разные
        состояния, и путать их нельзя ни в одну сторону.
        """
        _canonical(self.d, "inbox-a.md", intake_kind="unclear")
        _canonical(self.d, "inbox-b.md")
        rep = T.triage(self.d, now=_NOW)
        kinds = {r["card"]: r["kind"] for r in rep["rows"]}
        self.assertEqual(kinds["inbox-a.md"], "unclear")
        self.assertEqual(kinds["inbox-b.md"], T.KIND_UNDECLARED)
        self.assertEqual((rep["kind_declared"], rep["kind_unknown"]), (1, 1))

    def test_undeclared_kind_is_NOT_substituted(self):
        _canonical(self.d, "inbox-a.md")
        rep = T.triage(self.d, now=_NOW)
        self.assertEqual(rep["rows"][0]["kind"], T.KIND_UNDECLARED)
        self.assertEqual(rep["kind_declared"], 0)

    def test_value_outside_the_dictionary_is_its_own_outcome(self):
        _canonical(self.d, "inbox-a.md", intake_kind="важное")
        rep = T.triage(self.d, now=_NOW)
        self.assertEqual(rep["rows"][0]["kind"], T.KIND_INVALID)
        self.assertEqual((rep["kind_declared"], rep["kind_unknown"], rep["kind_invalid"]), (0, 0, 1))


class TrackerTypeIsNotARecordKind(unittest.TestCase):
    """Положительный контроль снятого запасного ключа: авария замера #991 дословно."""

    def setUp(self):
        import tempfile
        self.d = Path(tempfile.mkdtemp(prefix="spa_kind_"))

    def test_top_level_type_does_not_become_a_kind(self):
        """`type: inbox` — ответ на вопрос «какой это трекер», а не «какой это род записи».

        До ADR-873 читатель подставлял его, и четыре карточки `new` на origin/main несли
        род `inbox`. Подставленный род неотличим от объявленного ⇒ «не измерено» молча
        становилось «измерено».
        """
        _card(self.d, "inbox-a.md", {"type": "inbox", "status": "new",
                                     "title": "t", "created": "2026-10-01"})
        rep = T.triage(self.d, now=_NOW)
        self.assertEqual(rep["rows"][0]["kind"], T.KIND_UNDECLARED)
        self.assertEqual(rep["kind_unknown"], 1)

    def test_tracker_type_and_record_kind_can_disagree(self):
        """Оба поля рядом: трекерный тип НЕ перебивает объявленный род и наоборот."""
        _card(self.d, "inbox-a.md", {"type": "inbox", "intake_kind": "task",
                                     "status": "new", "title": "t", "created": "2026-10-01"})
        rep = T.triage(self.d, now=_NOW)
        self.assertEqual(rep["rows"][0]["kind"], "task")


class TheKindHasAWriter(unittest.TestCase):
    """Писатель есть, он отказывает на словарь и не трогает остальной файл."""

    def setUp(self):
        import tempfile
        self.d = Path(tempfile.mkdtemp(prefix="spa_kind_"))

    def test_writer_declares_a_kind_the_reader_then_sees(self):
        p = _canonical(self.d, "inbox-a.md")
        self.assertEqual(T.triage(self.d, now=_NOW)["kind_unknown"], 1)
        self.assertIsNone(set_intake_kind(p, "task"))
        rep = T.triage(self.d, now=_NOW)
        self.assertEqual((rep["kind_unknown"], rep["kind_counts"]["task"]), (0, 1))

    def test_writer_refuses_a_kind_outside_the_dictionary(self):
        p = _canonical(self.d, "inbox-a.md")
        with self.assertRaises(IntakeKindRefused):
            set_intake_kind(p, "важное")
        self.assertEqual(T.triage(self.d, now=_NOW)["rows"][0]["kind"], T.KIND_UNDECLARED)

    def test_writer_replaces_and_returns_the_previous_kind(self):
        p = _canonical(self.d, "inbox-a.md", intake_kind="idea")
        self.assertEqual(set_intake_kind(p, "task"), "idea")
        self.assertEqual(T.triage(self.d, now=_NOW)["rows"][0]["kind"], "task")
        self.assertEqual(p.read_text(encoding="utf-8").count("intake_kind:"), 1)

    def test_writer_keeps_the_rest_of_the_card_byte_for_byte(self):
        p = _canonical(self.d, "inbox-a.md", priority="high")
        before = p.read_text(encoding="utf-8")
        set_intake_kind(p, "note")
        after = p.read_text(encoding="utf-8")
        self.assertEqual([ln for ln in after.splitlines() if not ln.startswith("intake_kind:")],
                         before.splitlines())

    def test_the_cli_door_is_the_same_door(self):
        """Контроль ПРОВОДКИ: зовётся настоящий CLI, а не только функция."""
        p = _canonical(self.d, "inbox-a.md")
        r = subprocess.run([sys.executable, str(_REPO / "scripts" / "orchestrator_queue.py"),
                            "kind", str(p), "unclear"], capture_output=True, text=True, cwd=str(_REPO))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(T.triage(self.d, now=_NOW)["rows"][0]["kind"], "unclear")
        bad = subprocess.run([sys.executable, str(_REPO / "scripts" / "orchestrator_queue.py"),
                              "kind", str(p), "важное"], capture_output=True, text=True, cwd=str(_REPO))
        self.assertEqual(bad.returncode, 2, bad.stdout + bad.stderr)
        self.assertEqual(T.triage(self.d, now=_NOW)["rows"][0]["kind"], "unclear")


class OneDictionaryNotThree(unittest.TestCase):
    """Меню писателей — ПОДМНОЖЕСТВО словаря читателя, а не вторая его копия."""

    def test_owner_menus_are_derived_from_the_canonical_dictionary(self):
        from spa_core.studio_os.mission_intake import KINDS as MISSION
        from spa_core.telegram.inbox_intake import INTAKE_KIND_RU
        self.assertTrue(set(INTAKE_KIND_RU) <= set(T.KINDS_RU))
        self.assertTrue(set(MISSION) <= set(T.KINDS_RU))
        for k, ru in INTAKE_KIND_RU.items():
            self.assertEqual(ru, T.KINDS_RU[k])
        # Меню владельца «непонятно» не предлагает намеренно: это вердикт разбора, а не
        # слово владельца. Пропади эта разница — ось снова перестанет различать исходы.
        self.assertNotIn("unclear", INTAKE_KIND_RU)
        self.assertIn("unclear", T.KINDS_RU)

    def test_every_owner_label_is_writable_by_the_writer(self):
        """Словарь писателя не шире того, что примет дверь записи (иначе приём родит INVALID)."""
        import tempfile
        from spa_core.telegram.inbox_intake import INTAKE_KIND_RU
        d = Path(tempfile.mkdtemp(prefix="spa_kind_"))
        for k in INTAKE_KIND_RU:
            p = _canonical(d, f"inbox-{k}.md")
            set_intake_kind(p, k)
            self.assertEqual(T.declared_kind(T._fm(p.read_text(encoding="utf-8"))), k)


class TheSummaryLineNamesThreeOutcomes(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.d = Path(tempfile.mkdtemp(prefix="spa_kind_"))

    def test_summary_separates_declared_from_undeclared(self):
        _canonical(self.d, "inbox-a.md", intake_kind="task")
        _canonical(self.d, "inbox-b.md", intake_kind="unclear")
        _canonical(self.d, "inbox-c.md")
        line = T.summary_line(T.triage(self.d, now=_NOW))
        self.assertIn("род записи: объявлен 2", line)
        self.assertIn("задача 1", line)
        self.assertIn("непонятно 1", line)
        self.assertIn("НЕ ОБЪЯВЛЕН 1", line)

    def test_report_without_the_counters_is_NOT_MEASURED_not_zeroes(self):
        """Отчёт старой схемы (`inbox-triage/1`) не несёт счётчиков рода.

        Первая редакция строки читала `rep.get("kind_counts") or {}` и печатала «объявлен
        0» — пустота вместо отсутствия наблюдения, инв. #17 наизнанку в коде, написанном
        ПРОТИВ этого дефекта. Сторож `test_absent_observation_ratchet` поймал её на первом
        же прогоне (#991), и это положительный контроль на ту же форму.
        """
        _canonical(self.d, "inbox-a.md", intake_kind="task")
        old_schema = {k: v for k, v in T.triage(self.d, now=_NOW).items()
                      if k not in ("kind_counts", "kind_declared", "kind_unknown")}
        line = T.summary_line(old_schema)
        self.assertIn("род записи: НЕ ИЗМЕРЕН", line)
        self.assertNotIn("объявлен 0", line)

    def test_summary_names_the_out_of_dictionary_outcome_only_when_it_exists(self):
        _canonical(self.d, "inbox-a.md")
        self.assertNotIn("вне словаря", T.summary_line(T.triage(self.d, now=_NOW)))
        _canonical(self.d, "inbox-b.md", intake_kind="важное")
        self.assertIn("вне словаря 1", T.summary_line(T.triage(self.d, now=_NOW)))


if __name__ == "__main__":
    unittest.main()
