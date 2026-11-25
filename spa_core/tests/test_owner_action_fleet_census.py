"""Контроль прибора ADR-1103: инжест ответа ≠ состоявшееся действие.

Каждая проба — сцена на НАСТОЯЩЕМ приборе и одноразовом трекере; живой трекер
и живой флот не трогаются. Контроли идут В ОБЕ СТОРОНЫ: на целом контуре прибор
молчит, на каждом порванном звене — краснеет С НАЗВАННЫМ звеном.

Время здесь предметом не является: прибор не судит ни о какой свежести и часов
не спрашивает — литеральных дат в файле нет вовсе, поэтому и пометки
`FROZEN-DATE-OK` ему не нужно.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from unittest import mock
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPT = os.path.join(_REPO, "scripts", "owner_action_fleet_census.py")


def _load():
    """Прибор поднимается ПО ПУТИ — так же, как его позовёт шаг цикла."""
    spec = importlib.util.spec_from_file_location("_oafc_probe", _SCRIPT)
    assert spec and spec.loader, _SCRIPT
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


OAFC = _load()


CARD = """---
trackerStatus:
  type: owner-decision
title: "{title}"
status: {status}
priority: critical
---

## Что случилось и почему это важно

Агент `{label}` выключен. {ask}

## Что от тебя нужно

{need}
"""


def _write_card(root, name, *, status, label,
                ask="Нужно включить агента.", need="Шаг 1 — включить его."):
    """`ask`/`need` — ОБЕ половины текста: просьба может жить в любой.

    Первая редакция сцены «карточка не просит включать» оставляла слово
    «включить» в неизменяемом хвосте шаблона и поэтому НЕ ОБЕСПЕЧИВАЛА свою
    предпосылку — дефект был у фикстуры, а не у прибора.
    """
    path = os.path.join(root, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(CARD.format(title=name, status=status, label=label,
                             ask=ask, need=need))
    return path


def _write_registry(root, rows, *, stamp="2026-11-25T11:32:02+00:00", name=None):
    """Отметка НЕСЁТСЯ по умолчанию — и это требование РАЗЛИЧИМОСТИ сцен.

    Пока реестр писался без `generated_at`, строка провенанса сама содержала
    «НЕ ИЗМЕРЕНО (поля нет)», и мутация «отчёт не называет НЕ ИЗМЕРЕНО»
    ВЫЖИВАЛА: утверждение проходило по ЧУЖОЙ строке. Сцена без отметки
    осталась — но ровно одна, и она про отметку.
    """
    path = os.path.join(root, name or "agent_registry.json")
    doc = {"agents": rows}
    if stamp is not None:
        doc["generated_at"] = stamp
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return path


class OwnerActionFleetCensus(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    # ── целый контур: действие СОСТОЯЛОСЬ ⇒ находок нет ──────────────────
    def test_label_present_in_the_live_fleet_is_not_a_finding(self):
        _write_card(self.root, "own-a.md", status="ingested",
                    label="com.spa.alpha")
        reg = _write_registry(self.root, [{"label": "com.spa.alpha",
                                           "retired": False}])
        res = OAFC.census(tracker_dir=self.root, registry_path=reg,
                          labels={"com.spa.alpha", "com.spa.other"})
        self.assertEqual(res["outcome"], "clean", res)
        self.assertEqual(res["pending"], [])
        self.assertEqual([r["label"] for r in res["acted"]], ["com.spa.alpha"])

    # ── порванное звено: ответ инжестирован, действие НЕ состоялось ──────
    def test_answered_card_whose_agent_is_absent_from_the_fleet_is_a_finding(self):
        _write_card(self.root, "own-b.md", status="ingested",
                    label="com.spa.beta")
        reg = _write_registry(self.root, [{"label": "com.spa.beta",
                                           "retired": False}])
        res = OAFC.census(tracker_dir=self.root, registry_path=reg,
                          labels={"com.spa.other"})
        self.assertEqual(res["outcome"], "findings", res)
        self.assertEqual([r["label"] for r in res["pending"]], ["com.spa.beta"])
        # Находка обязана НАЗВАТЬ карточку и её статус, иначе она не адрес.
        self.assertEqual(res["pending"][0]["cards"],
                         [{"card": "own-b.md", "status": "ingested"}])

    def test_owner_done_counts_as_answered_too(self):
        """`owner-done` ставит ТОЛЬКО владелец (инв. #14) — и это худший случай."""
        _write_card(self.root, "own-c.md", status="owner-done",
                    label="com.spa.gamma")
        reg = _write_registry(self.root, [{"label": "com.spa.gamma",
                                           "retired": False}])
        res = OAFC.census(tracker_dir=self.root, registry_path=reg,
                          labels={"com.spa.other"})
        self.assertEqual([r["label"] for r in res["pending"]], ["com.spa.gamma"])

    # ── карточка, по которой ответа ещё НЕТ, предметом не является ───────
    def test_a_card_still_waiting_for_the_owner_is_not_asked(self):
        _write_card(self.root, "own-d.md", status="needs-owner",
                    label="com.spa.delta")
        reg = _write_registry(self.root, [{"label": "com.spa.delta",
                                           "retired": False}])
        res = OAFC.census(tracker_dir=self.root, registry_path=reg,
                          labels={"com.spa.other"})
        # Ни одной карточки в форме ⇒ именно НЕ ИЗМЕРЕНО, а не «чисто».
        self.assertEqual(res["outcome"], "unmeasured", res)
        self.assertIn("ни одной карточки", res["reason"])

    # ── карточка без просьбы включить — тоже не предмет ──────────────────
    def test_a_card_that_does_not_ask_to_enable_is_not_asked(self):
        _write_card(self.root, "own-e.md", status="ingested",
                    label="com.spa.epsilon",
                    ask="Решение записано в ADR, трогать ничего не надо.",
                    need="Ничего — просто прочитай ADR.")
        reg = _write_registry(self.root, [{"label": "com.spa.epsilon",
                                           "retired": False}])
        res = OAFC.census(tracker_dir=self.root, registry_path=reg,
                          labels={"com.spa.other"})
        self.assertEqual(res["outcome"], "unmeasured", res)

    # ── retired: вопрос СНЯТ объявлением, не находка ─────────────────────
    def test_declared_retired_agent_is_not_a_finding(self):
        _write_card(self.root, "own-f.md", status="ingested",
                    label="com.spa.zeta")
        reg = _write_registry(self.root, [{"label": "com.spa.zeta",
                                           "retired": True}])
        res = OAFC.census(tracker_dir=self.root, registry_path=reg,
                          labels={"com.spa.other"})
        self.assertEqual(res["outcome"], "clean", res)
        self.assertEqual([r["label"] for r in res["retired"]], ["com.spa.zeta"])
        self.assertEqual(res["pending"], [])

    # ── третий исход #1: ярлыка нет НИ ГДЕ ⇒ НЕ ИЗМЕРЕНО, не находка ─────
    def test_label_in_neither_door_is_unmeasured_not_a_finding(self):
        _write_card(self.root, "own-g.md", status="ingested",
                    label="com.spa.eta")
        reg = _write_registry(self.root, [{"label": "com.spa.other",
                                           "retired": False}])
        res = OAFC.census(tracker_dir=self.root, registry_path=reg,
                          labels={"com.spa.other"})
        self.assertEqual(res["pending"], [], res)
        self.assertEqual([r["label"] for r in res["unmeasured_labels"]],
                         ["com.spa.eta"])
        self.assertIn("ни во флоте, ни в реестре",
                      res["unmeasured_labels"][0]["reason"])
        # «Не измерено» НЕ выдаётся за «чисто» кодом возврата 1/0 — исход
        # `clean`, но перечень непуст, и отчёт его НАЗЫВАЕТ. Утверждение идёт
        # по СВОЕЙ строке (та, что несёт и «НЕ ИЗМЕРЕНО», и слова про флот с
        # реестром): строка провенанса реестра тоже умеет печатать
        # «НЕ ИЗМЕРЕНО», и утверждать по ней значило бы зачесть ЧУЖУЮ строку.
        own = [ln for ln in OAFC.report_lines(res)
               if "НЕ ИЗМЕРЕНО" in ln and "ни во флоте, ни в реестре" in ln]
        self.assertTrue(own, OAFC.report_lines(res))
        self.assertIn("1 ярлык", own[0])

    # ── третий исход #2: реестра нет ⇒ отставку никто не объявлял ────────
    def test_missing_registry_keeps_an_absent_label_a_finding(self):
        """Отсутствие объявления НЕ ЕСТЬ объявление отставки — fail-CLOSED."""
        _write_card(self.root, "own-h.md", status="ingested",
                    label="com.spa.theta")
        res = OAFC.census(tracker_dir=self.root,
                          registry_path=os.path.join(self.root, "нет.json"),
                          labels={"com.spa.other"})
        self.assertEqual([r["label"] for r in res["pending"]], ["com.spa.theta"])

    # ── третий исход #3: дверь флота НЕ ОТВЕТИЛА ⇒ код 2, не ноль ────────
    def test_silent_fleet_door_is_unmeasured_and_never_a_clean_pass(self):
        _write_card(self.root, "own-i.md", status="ingested",
                    label="com.spa.iota")
        reg = _write_registry(self.root, [{"label": "com.spa.iota",
                                           "retired": False}])
        res = OAFC.census(tracker_dir=self.root, registry_path=reg, labels=None)
        self.assertEqual(res["outcome"], "unmeasured", res)
        self.assertIn("дверь флота не ответила", res["reason"])
        self.assertIsNone(res["fleet_size"])

    def test_an_unparsed_fleet_listing_is_the_silent_door_not_an_empty_set(self):
        """Пустое множество объявило бы находкой КАЖДОГО названного агента.

        Сцена на НАСТОЯЩЕЙ двери: `launchctl` отвечает кодом 0, но вывод не в
        том формате, о котором прибор знает. Честный ответ — `None`.
        """
        class _Proc:
            returncode = 0
            stdout = "PID\tStatus\tLabel\n"  # только заголовок, ни одной строки

        with mock.patch.object(OAFC.subprocess, "run",
                               return_value=_Proc()) as called:
            self.assertIsNone(OAFC.fleet_labels())
        self.assertEqual(called.call_args.args[0], ["launchctl", "list"])

    def test_a_nonzero_fleet_door_is_silent_too(self):
        """Сцена обязана РАЗЛИЧАТЬ: вывод полностью разбираемый.

        Первая редакция подавала при коде 1 строку без табуляций — такой вывод
        не разбирается и так, поэтому мутация «код возврата не спрашивается»
        ВЫЖИВАЛА: сцена её не различала. Теперь строка well-formed, и если код
        перестать спрашивать, дверь вернёт НЕПУСТОЕ множество и проба покраснеет.
        """
        class _Proc:
            returncode = 1
            stdout = "PID\tStatus\tLabel\n-\t0\tcom.spa.alpha\n"

        # Обратная половина той же сцены: тот же вывод при коде 0 РАЗБИРАЕТСЯ —
        # иначе «молчит из-за кода» не отличить от «молчит из-за формата».
        class _Ok(_Proc):
            returncode = 0

        with mock.patch.object(OAFC.subprocess, "run", return_value=_Ok()):
            self.assertEqual(OAFC.fleet_labels(), {"com.spa.alpha"})
        with mock.patch.object(OAFC.subprocess, "run", return_value=_Proc()):
            self.assertIsNone(OAFC.fleet_labels())

    def test_a_missing_launchctl_is_silent_rather_than_an_exception(self):
        with mock.patch.object(OAFC.subprocess, "run",
                               side_effect=FileNotFoundError("launchctl")):
            self.assertIsNone(OAFC.fleet_labels())

    # ── третий исход #4: трекер не прочитан ⇒ код 2 с причиной ───────────
    def test_unreadable_tracker_is_unmeasured_with_a_named_cause(self):
        res = OAFC.census(tracker_dir=os.path.join(self.root, "нет-такого"),
                          registry_path="нет", labels={"com.spa.other"})
        self.assertEqual(res["outcome"], "unmeasured", res)
        self.assertIn("трекер не прочитан", res["reason"])

    # ── выбор трекера ПЕЧАТАЕТСЯ (урок ADR-1080) ─────────────────────────
    def test_the_report_prints_which_tracker_answered(self):
        """Реестр лежит ВНЕ каталога трекера — иначе сцена не различает.

        Пока реестр писался внутрь `self.root`, строка его провенанса содержала
        путь трекера как префикс, и мутация «выбор трекера НЕ печатается»
        ВЫЖИВАЛА: утверждение проходило по строке реестра.
        """
        other = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(other, ignore_errors=True))
        _write_card(self.root, "own-j.md", status="ingested",
                    label="com.spa.kappa")
        reg = _write_registry(other, [{"label": "com.spa.kappa",
                                       "retired": False}])
        res = OAFC.census(tracker_dir=self.root, registry_path=reg,
                          labels={"com.spa.kappa"})
        lines = OAFC.report_lines(res)
        self.assertIn(self.root, lines[0])
        self.assertNotIn(self.root, "\n".join(lines[1:]))

    # ── коды возврата: три исхода различимы у CLI ───────────────────────
    def test_cli_exit_codes_separate_all_three_outcomes(self):
        _write_card(self.root, "own-k.md", status="ingested",
                    label="com.spa.lmbd")
        reg = _write_registry(self.root, [{"label": "com.spa.lmbd",
                                           "retired": False}])
        # Дверь подменяется ЕДИНСТВЕННЫМ установщиком с ГАРАНТИРОВАННЫМ
        # возвратом (`.claude/rules/deployment.md` § «СОСЕД ПО ПРОЦЕССУ»):
        # прямое присваивание атрибута модуля пережило бы сцену и навредило
        # бы СОСЕДУ по процессу, а не автору.
        argv = ["--tracker-dir", self.root, "--registry", reg]
        for door, expected in ((lambda: {"com.spa.lmbd"}, 0),
                               (lambda: {"com.spa.other"}, OAFC.FINDINGS_EXIT),
                               (lambda: None, OAFC.UNMEASURED_EXIT)):
            with mock.patch.object(OAFC, "fleet_labels", door):
                self.assertEqual(OAFC.main(argv), expected)
        # И дверь ВЕРНУЛАСЬ: сцена не оставила подмены соседу.
        self.assertIs(OAFC.fleet_labels.__module__, OAFC.__name__)

    # ── карточка, которую не удалось прочитать, НАЗЫВАЕТСЯ ──────────────
    def test_an_unreadable_card_is_named_not_skipped(self):
        _write_card(self.root, "own-l.md", status="ingested",
                    label="com.spa.mu")
        bad = os.path.join(self.root, "own-bad.md")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("x")
        os.chmod(bad, 0o000)
        self.addCleanup(lambda: os.chmod(bad, 0o600))
        reg = _write_registry(self.root, [{"label": "com.spa.mu",
                                           "retired": False}])
        res = OAFC.census(tracker_dir=self.root, registry_path=reg,
                          labels={"com.spa.mu"})
        if os.geteuid() == 0:  # pragma: no cover — под root права не держат
            self.skipTest("под root режим 000 не запрещает чтение — "
                          "предпосылка сцены НЕ ОБЕСПЕЧЕНА")
        self.assertEqual(len(res["cards_unread"]), 1, res)
        self.assertIn("own-bad.md", res["cards_unread"][0])

    # ── провенанс реестра ПЕЧАТАЕТСЯ (замороженная копия ≠ живая) ────────
    def test_the_report_prints_which_registry_answered(self):
        """Замер 25.11: worktree отдаёт реестр от 2026-07-17 (80 записей), прод — 99.

        Из замороженной копии находка о `decision_loop` ПРОПАДАЕТ (его там нет
        вовсе) и подменяется ложной о `governance_watcher`. Поэтому провенанс
        обязан быть НАПЕЧАТАН: молча ответить о чужой копии хуже ошибки.
        """
        _write_card(self.root, "own-m.md", status="ingested",
                    label="com.spa.nu")
        reg = os.path.join(self.root, "agent_registry.json")
        with open(reg, "w", encoding="utf-8") as fh:
            json.dump({"generated_at": "2026-07-17T01:51:49+00:00",
                       "agents": [{"label": "com.spa.nu", "retired": False}]}, fh)
        res = OAFC.census(tracker_dir=self.root, registry_path=reg,
                          labels={"com.spa.nu"})
        text = "\n".join(OAFC.report_lines(res))
        self.assertIn("2026-07-17T01:51:49+00:00", text)
        self.assertIn("записей 1", text)
        self.assertIn(reg, text)

    def test_an_unreadable_registry_is_named_in_the_provenance(self):
        """Непрочитанный реестр НАЗЫВАЕТСЯ, а не выглядит как «объявлений нет»."""
        _write_card(self.root, "own-n.md", status="ingested",
                    label="com.spa.xi")
        res = OAFC.census(tracker_dir=self.root,
                          registry_path=os.path.join(self.root, "нет.json"),
                          labels={"com.spa.other"})
        text = "\n".join(OAFC.report_lines(res))
        self.assertIn("НЕ ПРОЧИТАН", text)
        # И находка при этом ОСТАЁТСЯ (fail-CLOSED, п. 4 решения).
        self.assertEqual([r["label"] for r in res["pending"]], ["com.spa.xi"])

    def test_a_registry_without_a_stamp_says_unmeasured_not_blank(self):
        _write_card(self.root, "own-o.md", status="ingested",
                    label="com.spa.omi")
        reg = _write_registry(self.root, [{"label": "com.spa.omi",
                                           "retired": False}], stamp=None)
        res = OAFC.census(tracker_dir=self.root, registry_path=reg,
                          labels={"com.spa.omi"})
        self.assertIn("generated_at НЕ ИЗМЕРЕНО", "\n".join(OAFC.report_lines(res)))

    # ── прибор ТОЛЬКО читает ────────────────────────────────────────────
    def test_the_prober_never_writes_and_never_moves_a_card(self):
        src = open(_SCRIPT, encoding="utf-8").read()
        for forbidden in ("launchctl load", "launchctl bootstrap",
                          "set-status", "atomic_save", "open(path, \"w\")"):
            self.assertNotIn(forbidden, src,
                             f"прибор обязан только ЧИТАТЬ, найдено: {forbidden}")

    def test_the_fleet_door_is_single(self):
        """Второй зов launchctl в приборе = вторая дверь к живому состоянию."""
        src = open(_SCRIPT, encoding="utf-8").read()
        self.assertEqual(src.count('"launchctl"'), 1, "дверь обязана быть ОДНА")


if __name__ == "__main__":
    unittest.main()
