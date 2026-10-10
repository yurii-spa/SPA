"""Батарея прибора «цена ветви освобождения по КАРТОЧКЕ» — заказ G111 п. 1 (ADR-685).

Каждый тест — положительный контроль одного звена: порвать звено ⇒ тест краснеет с
НАЗВАННОЙ причиной. Третий исход проверяется отдельно и ДОСЛОВНО по сообщению: иначе
«не измерено» стало бы неотличимо от «прошло» — ровно тот дефект, против которого
прибор и написан.

Личность процесса здесь не литерал: ``os.getpid()`` жив на любом хосте всегда, а чужую
живую личность ось C берёт у ``live_other_anchor`` либо получает АРГУМЕНТОМ в
герметичных сценах (``.claude/rules/deployment.md``, личность процесса).
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring import foreign_done_cost as M

ROOT = Path(__file__).resolve().parents[2]

# FROZEN-DATE-OK: injected-clock — литерал ниже есть ЯКОРЬ, и он уезжает ВХОДОМ: от него
# выводятся отметки записей сцены (`_scene(..., base=NOW)`) и он же подаётся отчёту
# (`build_report(..., now=NOW)`, `M.run(..., now=NOW)`). Обе стороны закреплены от ОДНОГО
# якоря, поэтому сдвиг календаря не меняет вердикт ни одного теста файла. Отдельно: ось B
# прибора о свежести не спрашивает ВОВСЕ — она сравнивает отметку с отметкой, — поэтому
# календарь ей безразличен по построению, а не по договорённости.
#: Момент-якорь сцен и отчёта.
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

#: Форма отметки ЕДИНСТВЕННОГО писателя журнала (``log_session_change``): секундная
#: точность. Разойтись с ней значило бы получить «метка времени не разобрана», то есть
#: померить свою сцену вместо прибора.
STAMP = "%Y-%m-%dT%H:%M:%SZ"

_CARD = "inbox-proba-tsenyi-chuzhogo-done"
_OTHER_CARD = "inbox-proba-sosednyaya-kartochka"


def _holder(pid=None, label=None):
    """Личность сцены, живая ПО ПОСТРОЕНИЮ (свой номер), а не литеральный pid."""
    pid = os.getpid() if pid is None else pid
    return {"pid": pid, "label": label or f"pid{pid}",
            "start": "тест: личность, живая по построению"}


def _scene(tmp: Path, rows, *, base: datetime = NOW) -> Path:
    """Журнал сцены, написанный НАСТОЯЩИМ писателем; часы подменены ПОСЛЕ записи.

    Форма записи берётся у единственного писателя (``log_session_change.record``) —
    того же, чьи записи читает прибор, — поэтому разойтись с ней сцена не может ни по
    одному полю. Переписывается РОВНО одно поле: ``ts``. Так сделано потому, что
    писатель часов не принимает вовсе, а сцена развилки обязана ставить события в
    НАЗВАННОМ порядке: «захват → чужой `done` → своё `done`» и обратный ему порядок
    различаются только временем, и выжидать настоящие секунды значило бы поставить
    вердикт теста в зависимость от скорости хоста.
    """
    guard = M._load_guard(ROOT)
    announcer = guard.load_announcer()
    log = tmp / "session_changes.jsonl"
    log.touch()
    for row in rows:
        process = None
        if row.get("pid") is not None:
            process = ({"session_pid": row["pid"],
                        "session_pid_start": row.get("start", "тест: живая личность")},
                       "личность сцены, живая по построению")
        announcer.record(row.get("summary", "сцена прибора"), [], "сцена",
                         card=row.get("card", ""), card_state=row.get("card_state", ""),
                         log=str(log), session=row["session"], process=process)
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    assert len(records) == len(rows), "писатель оставил не столько записей, сколько сцена"
    for record, row in zip(records, rows):
        record["ts"] = (base + timedelta(minutes=row["minutes"])).strftime(STAMP)
    log.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                   encoding="utf-8")
    return log


def _report(log: Path, **kw):
    """Отчёт прибора по журналу сцены. Ось C подаётся ВХОДОМ — она мерится отдельно."""
    kw.setdefault("door", {"measured": False, "reason": "ось C подана входом (контроль)"})
    return M.build_report(ROOT, now=NOW, journal_path=log, **kw)


class _Door:
    """Дверь-двойник: ``main`` отдаёт назначенный вердикт, писатель — настоящий."""

    def __init__(self, verdicts, *, self_claims=None, drop_verdict=False):
        self.verdicts = list(verdicts)
        self.self_claims = self_claims or []
        self.drop_verdict = drop_verdict
        self.real = M._load_guard(ROOT)

    def load_announcer(self):
        return self.real.load_announcer()

    def main(self, argv):
        verdict = self.verdicts.pop(0)
        report = {"self_claims": self.self_claims}
        if not self.drop_verdict:
            report["verdict"] = verdict
        print(json.dumps(report, ensure_ascii=False))
        return 0 if verdict == "free" else 1


class TestContractNames(unittest.TestCase):
    """Имена КОНТРАКТА пришпилены ДОСЛОВНО, а не сверяются сами с собой.

    Вердикт, исходы осей и имена ветвей читают манифест, шаг 0-офис, ADR и журнал
    цикла — то есть это ВНЕШНИЙ контракт, а не внутренняя подробность. Сравнение
    `report["status"] == M.STATUS_STRIPS_LIVE` переименование переживает молча
    (строка сверяется САМА С СОБОЙ), поэтому здесь стоят литералы.
    """

    def test_status_names_are_pinned(self):
        self.assertEqual(M.STATUS_STRIPS_LIVE, "CARD_BRANCH_STRIPS_LIVE_WORK")
        self.assertEqual(M.STATUS_NOT_WITNESSED, "CARD_BRANCH_HARM_NOT_WITNESSED")
        self.assertEqual(M.STATUS_UNMEASURED, "UNMEASURED")

    def test_outcome_names_are_pinned_and_the_dictionary_is_closed(self):
        self.assertEqual(M.WITNESSED_WORKING, "witnessed_working")
        self.assertEqual(M.WITNESSED_ALIVE, "witnessed_alive")
        self.assertEqual(M.NO_EVIDENCE, "no_evidence")
        self.assertEqual(M.OUTCOMES, ("witnessed_working", "witnessed_alive",
                                      "no_evidence"))

    def test_branch_and_door_names_are_pinned(self):
        self.assertEqual(M.BRANCH_HOLDER, "release_by_holder")
        self.assertEqual(M.BRANCH_CARD, "release_by_card")
        self.assertEqual(M.BRANCHES, ("release_by_holder", "release_by_card"))
        self.assertEqual(M.DOOR_PROTECTS, "protects_live_holder")
        self.assertEqual(M.DOOR_HANDS_OVER, "hands_card_to_stranger")

    def test_artifact_name_and_order_are_pinned(self):
        self.assertEqual(M.ARTIFACT_NAME, "foreign_done_cost.json")
        self.assertTrue(M.ORDER.startswith("G111 п. 1 (ADR-536)"), M.ORDER)
        self.assertEqual(M.CENSUS_MODULE, "spa_core.monitoring.claim_release_census")


# ───────────────────────── ось B: перепроигрывание журнала ─────────────────────────

class TestHarmReplay(unittest.TestCase):
    """Чей открытый захват снял бы чужой `done` — и что известно о его жизни."""

    def test_holder_that_kept_working_is_WITNESSED_harm(self):
        holder = _holder()
        with tempfile.TemporaryDirectory() as tmp:
            log = _scene(Path(tmp), [
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "claim", "minutes": 0},
                {"session": "pid777001", "card": _CARD, "card_state": "done",
                 "minutes": 10},
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "done", "minutes": 20},
            ])
            report = _report(log)
        harm = report["harm"]
        self.assertTrue(harm["measured"], harm.get("reason"))
        self.assertEqual(harm["affected_claims"], 1)
        self.assertEqual(harm["by_outcome"][M.WITNESSED_WORKING], 1)
        self.assertEqual(harm["witnessed_harm"], 1)
        self.assertEqual(report["status"], M.STATUS_STRIPS_LIVE)
        self.assertEqual(M.exit_code_for(report), 1)

    def test_silence_after_the_foreign_done_is_NO_EVIDENCE_not_death(self):
        """Та же сцена БЕЗ последней записи: единственное отличие — свидетельство."""
        holder = _holder()
        with tempfile.TemporaryDirectory() as tmp:
            log = _scene(Path(tmp), [
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "claim", "minutes": 0},
                {"session": "pid777001", "card": _CARD, "card_state": "done",
                 "minutes": 10},
            ])
            report = _report(log)
        harm = report["harm"]
        self.assertEqual(harm["affected_claims"], 1)
        self.assertEqual(harm["by_outcome"][M.NO_EVIDENCE], 1)
        self.assertEqual(harm["witnessed_harm"], 0,
                         "молчание после чужого `done` зачтено как смерть держателя")
        self.assertEqual(report["status"], M.STATUS_NOT_WITNESSED)
        self.assertEqual(M.exit_code_for(report), 0)
        self.assertIn("молчание", harm["means"])

    def test_alive_elsewhere_is_its_own_outcome_not_merged_with_working(self):
        holder = _holder()
        with tempfile.TemporaryDirectory() as tmp:
            log = _scene(Path(tmp), [
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "claim", "minutes": 0},
                {"session": "pid777001", "card": _CARD, "card_state": "done",
                 "minutes": 10},
                # запись БЕЗ карточки: держатель жив, но про эту работу не сказал
                {"session": holder["label"], "pid": holder["pid"], "minutes": 20},
            ])
            report = _report(log)
        harm = report["harm"]
        self.assertEqual(harm["by_outcome"][M.WITNESSED_ALIVE], 1)
        self.assertEqual(harm["by_outcome"][M.WITNESSED_WORKING], 0,
                         "«жив» склеено с «работал дальше» — это два разных исхода")
        self.assertEqual(harm["witnessed_harm"], 1)

    def test_own_done_BEFORE_the_foreign_one_is_not_affected(self):
        holder = _holder()
        with tempfile.TemporaryDirectory() as tmp:
            log = _scene(Path(tmp), [
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "claim", "minutes": 0},
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "done", "minutes": 5},
                {"session": "pid777001", "card": _CARD, "card_state": "done",
                 "minutes": 10},
            ])
            report = _report(log)
        self.assertEqual(report["harm"]["affected_claims"], 0,
                         "снятый своим `done` захват зачтён в пострадавшие")
        self.assertTrue(report["measured"],
                        "ноль задетых захватов — ИЗМЕРЕННЫЙ нуль, а не «не измерено»")
        self.assertEqual(report["status"], M.STATUS_NOT_WITNESSED)
        self.assertEqual(M.exit_code_for(report), 0)

    def test_a_claim_taken_AFTER_the_foreign_done_is_not_affected(self):
        holder = _holder()
        with tempfile.TemporaryDirectory() as tmp:
            log = _scene(Path(tmp), [
                {"session": "pid777001", "card": _CARD, "card_state": "done",
                 "minutes": 0},
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "claim", "minutes": 10},
            ])
            report = _report(log)
        self.assertEqual(report["harm"]["affected_claims"], 0,
                         "`done` раньше захвата снял бы повторное взятие — "
                         "это противоречит правилу двери")

    def test_foreign_done_on_ANOTHER_card_strips_nothing(self):
        holder = _holder()
        with tempfile.TemporaryDirectory() as tmp:
            log = _scene(Path(tmp), [
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "claim", "minutes": 0},
                {"session": "pid777001", "card": _OTHER_CARD, "card_state": "done",
                 "minutes": 10},
            ])
            report = _report(log)
        self.assertEqual(report["harm"]["affected_claims"], 0,
                         "освобождение по ДРУГОЙ карточке зачтено этой")

    def test_a_claim_is_counted_ONCE_by_its_FIRST_foreign_done(self):
        holder = _holder()
        with tempfile.TemporaryDirectory() as tmp:
            log = _scene(Path(tmp), [
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "claim", "minutes": 0},
                {"session": "pid777001", "card": _CARD, "card_state": "done",
                 "minutes": 10},
                {"session": "pid777002", "card": _CARD, "card_state": "done",
                 "minutes": 20},
            ])
            report = _report(log)
        harm = report["harm"]
        self.assertEqual(harm["affected_claims"], 1, "один захват посчитан дважды")
        self.assertEqual(harm["foreign_done_hits"], 2)
        self.assertEqual(harm["foreign_dones_that_would_strip"], 2)
        first = harm["examples"][M.NO_EVIDENCE][0]
        self.assertEqual(first["foreign_done_at"],
                         (NOW + timedelta(minutes=10)).strftime(STAMP),
                         "захват отнесён не к ПЕРВОМУ задевшему его освобождению")

    def test_same_second_is_affected_and_counted_separately(self):
        """Равенство отметок — край правила двери (`>=`), и он НАЗВАН отдельно."""
        holder = _holder()
        with tempfile.TemporaryDirectory() as tmp:
            log = _scene(Path(tmp), [
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "claim", "minutes": 0},
                {"session": "pid777001", "card": _CARD, "card_state": "done",
                 "minutes": 0},
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "done", "minutes": 20},
            ])
            report = _report(log)
        harm = report["harm"]
        self.assertEqual(harm["affected_claims"], 1)
        self.assertEqual(harm["witnessed_in_the_same_second"], 1)
        self.assertEqual(harm["witnessed_strictly_after_claim"], 0)

    def test_identity_is_an_ANCHOR_and_the_substitution_share_is_named(self):
        """Личность по якорю и по ярлыку считаются отдельно (урок ADR-498)."""
        holder = _holder()
        with tempfile.TemporaryDirectory() as tmp:
            log = _scene(Path(tmp), [
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "claim", "minutes": 0},
                {"session": "pid777003", "card": _OTHER_CARD, "card_state": "claim",
                 "minutes": 1},
                {"session": "pid777001", "card": _CARD, "card_state": "done",
                 "minutes": 10},
                {"session": "pid777001", "card": _OTHER_CARD, "card_state": "done",
                 "minutes": 11},
            ])
            report = _report(log)
        harm = report["harm"]
        self.assertEqual(harm["affected_claims"], 2)
        self.assertEqual(harm["identity_from"], {"anchor": 1, "label": 1})

    def test_examples_are_capped_so_the_artifact_stays_readable(self):
        """Примеров не больше пяти на исход: артефакт читает ЧЕЛОВЕК в шаге 0-офис.

        Без потолка перепись выгрузила бы в отчёт сотни записей — то же, что
        `assertIn` на целом файле (921 КБ с одного падения), только каждый такт.
        """
        holder = _holder()
        rows = []
        for n in range(7):
            rows.append({"session": f"pid77710{n}", "pid": 900000 + n,
                         "card": f"{_CARD}-{n}", "card_state": "claim",
                         "minutes": n})
        for n in range(7):
            rows.append({"session": holder["label"], "card": f"{_CARD}-{n}",
                         "card_state": "done", "minutes": 30 + n})
        with tempfile.TemporaryDirectory() as tmp:
            report = _report(_scene(Path(tmp), rows))
        harm = report["harm"]
        self.assertEqual(harm["affected_claims"], 7)
        self.assertEqual(len(harm["examples"][M.NO_EVIDENCE]), 5,
                         "потолок примеров снят — отчёт растёт без границы")

    def test_no_releases_is_the_third_outcome_not_a_clean_zero(self):
        holder = _holder()
        with tempfile.TemporaryDirectory() as tmp:
            log = _scene(Path(tmp), [
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "claim", "minutes": 0},
            ])
            report = _report(log)
        self.assertFalse(report["measured"])
        self.assertFalse(report["harm"]["measured"])
        self.assertIn("освобождений в журнале нет", report["reason"])
        self.assertEqual(M.exit_code_for(report), 2)

    def test_no_claims_is_the_third_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = _scene(Path(tmp), [
                {"session": "pid777001", "minutes": 0},
            ])
            report = _report(log)
        self.assertFalse(report["measured"])
        self.assertIn("захватов в журнале нет", report["reason"])
        self.assertIsNone(report["harm"])
        self.assertEqual(M.exit_code_for(report), 2)

    def test_unreadable_journal_is_the_third_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = _report(Path(tmp) / "нет-такого-журнала.jsonl")
        self.assertFalse(report["measured"])
        self.assertIn("журнал не прочитан", report["reason"])
        self.assertIsNone(report["population"])
        self.assertEqual(M.exit_code_for(report), 2)


# ───────────────── ось A: польза ветви — числом СОСЕДА, не своим ─────────────────

class TestBenefitFromNeighbour(unittest.TestCase):

    class _Census:
        """Сосед-двойник: отдаёт назначенный отчёт и помнит, что его спросили."""

        JOURNAL_REL = "data/session_changes.jsonl"

        def __init__(self, doc):
            self.doc = doc
            self.asked = 0

        def build_report(self, root, **kw):
            self.asked += 1
            return self.doc

    def test_benefit_is_taken_from_the_neighbour_not_computed_here(self):
        census = self._Census({"measured": True, "status": "RELEASE_ADDRESSED_TO_HOLDER",
                               "open_claims": {
                                   "card_declared_done_by_another_identity": 4242}})
        out = M.measure_benefit(ROOT, census=census)
        self.assertEqual(census.asked, 1, "у соседа не спросили вовсе")
        self.assertTrue(out["measured"])
        self.assertEqual(out["useful_claims"], 4242)

    def test_unmeasured_neighbour_leaves_benefit_None_not_zero(self):
        census = self._Census({"measured": False, "status": "UNMEASURED",
                               "reason": "журнала нет (двойник)"})
        out = M.measure_benefit(ROOT, census=census)
        self.assertFalse(out["measured"])
        self.assertIsNone(out["useful_claims"], "нуль читался бы как «ветвь бесполезна»")
        self.assertIn("НЕ ИЗМЕРИЛ", out["reason"])

    def test_renamed_neighbour_field_is_the_third_outcome(self):
        census = self._Census({"measured": True, "status": "RELEASE_ADDRESSED_TO_HOLDER",
                               "open_claims": {"card_done_elsewhere": 7}})
        out = M.measure_benefit(ROOT, census=census)
        self.assertFalse(out["measured"])
        self.assertIsNone(out["useful_claims"])
        self.assertIn("card_declared_done_by_another_identity", out["reason"])

    def test_real_neighbour_declares_the_field_the_instrument_reads(self):
        """Претензия «поле есть у соседа» проверяется У СОСЕДА, а не на доверии."""
        census = M.load_census()
        with tempfile.TemporaryDirectory() as tmp:
            holder = _holder()
            log = _scene(Path(tmp), [
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "claim", "minutes": 0},
                {"session": "pid777001", "card": _CARD, "card_state": "done",
                 "minutes": 10},
            ])
            doc = census.build_report(ROOT, now=NOW, journal_path=log)
        self.assertTrue(doc["measured"], doc.get("reason"))
        self.assertIn("card_declared_done_by_another_identity", doc["open_claims"])


class TestCrossCheck(unittest.TestCase):
    """Сверка СОСТАВА: расхождение приборов обязано быть названо."""

    def test_agreement_is_reported_as_composition_not_as_confirmation(self):
        out = M.cross_check({"measured": True, "useful_claims": 5},
                            {"measured": True, "never_closed_by_holder": 5})
        self.assertTrue(out["measured"])
        self.assertTrue(out["agrees"])
        self.assertIsNone(out["reason"])

    def test_disagreement_is_named(self):
        out = M.cross_check({"measured": True, "useful_claims": 5},
                            {"measured": True, "never_closed_by_holder": 4})
        self.assertFalse(out["agrees"])
        self.assertIn("РАСХОЖДЕНИЕ состава", out["reason"])

    def test_either_side_unmeasured_is_the_third_outcome(self):
        for benefit, harm, needle in (
                ({"measured": False}, {"measured": True, "never_closed_by_holder": 1},
                 "польза не измерена"),
                ({"measured": True, "useful_claims": 1}, {"measured": False},
                 "вред не измерен")):
            out = M.cross_check(benefit, harm)
            self.assertFalse(out["measured"])
            self.assertIsNone(out["agrees"])
            self.assertIn(needle, out["reason"])

    def test_both_instruments_agree_on_a_scene_with_both_kinds_of_victim(self):
        """Сверка состава ЧЕРЕЗ НАСТОЯЩЕГО соседа: один полезный захват, один вредный.

        Живой журнал дерева предпосылкой НЕ берётся намеренно: в worktree и в CI его
        нет по построению, и тест судил бы о том, повезло ли хосту (ADR-479, дверь
        «глубина клона»). Сцена несёт оба населения сразу, поэтому расхождение
        приборов краснело бы ЗДЕСЬ, а не только на рабочем Маке.
        """
        holder, worker = _holder(), _holder(pid=os.getppid())
        with tempfile.TemporaryDirectory() as tmp:
            log = _scene(Path(tmp), [
                # полезная сторона: держатель своё `done` не объявлял НИКОГДА
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "claim", "minutes": 0},
                # вредная сторона: держатель объявил своё `done` ПОЗЖЕ чужого
                {"session": worker["label"], "pid": worker["pid"], "card": _OTHER_CARD,
                 "card_state": "claim", "minutes": 1},
                {"session": "pid777001", "card": _CARD, "card_state": "done",
                 "minutes": 10},
                {"session": "pid777001", "card": _OTHER_CARD, "card_state": "done",
                 "minutes": 11},
                {"session": worker["label"], "pid": worker["pid"], "card": _OTHER_CARD,
                 "card_state": "done", "minutes": 20},
            ])
            report = _report(log)
        harm, check = report["harm"], report["cross_check"]
        self.assertEqual(harm["affected_claims"], 2)
        self.assertEqual(harm["by_outcome"][M.WITNESSED_WORKING], 1)
        self.assertEqual(harm["by_outcome"][M.NO_EVIDENCE], 1)
        self.assertTrue(check["measured"], check.get("reason"))
        self.assertTrue(check["agrees"], check.get("reason"))
        self.assertEqual(check["neighbour_useful"], 1)
        self.assertEqual(check["replay_never_closed"], 1)


# ─────────────── ось C: что делает НАСТОЯЩАЯ дверь с живым держателем ───────────────

class TestDoor(unittest.TestCase):

    def test_real_door_hands_the_card_to_a_stranger_under_the_card_branch(self):
        out = M.measure_door(ROOT)
        self.assertTrue(out["measured"], out.get("reason"))
        self.assertEqual(out["verdict_without_done"], "claimed")
        self.assertEqual(out["by_branch"][M.BRANCH_HOLDER]["outcome"], M.DOOR_PROTECTS)
        self.assertEqual(out["by_branch"][M.BRANCH_CARD]["outcome"], M.DOOR_HANDS_OVER)
        self.assertEqual(out["by_branch"][M.BRANCH_CARD]["verdict"], "free")

    def test_unmeasured_holder_identity_refuses_LOUDLY(self):
        out = M.measure_door(ROOT, holder={"measured": False, "pid": 1,
                                           "reason": "`ps` не отработал (контроль)"})
        self.assertFalse(out["measured"])
        self.assertIn("НЕ ИЗМЕРЕНА", out["reason"])
        self.assertEqual(out["by_branch"], {})

    def test_stranger_equal_to_the_holder_is_refused(self):
        holder = {"measured": True, "pid": os.getpid(), "start": "живая по построению"}
        out = M.measure_door(ROOT, holder=holder, stranger_pid=os.getpid())
        self.assertFalse(out["measured"])
        self.assertIn("неразличимы", out["reason"])

    def test_equal_verdicts_on_both_branches_are_the_third_outcome(self):
        door = _Door(["claimed", "claimed", "claimed"])
        out = M.measure_door(ROOT, guard_loader=lambda root: door,
                             holder=_doorholder())
        self.assertFalse(out["measured"])
        self.assertIn("НЕ РАЗЛИЧАЕТ", out["reason"])

    def test_base_scene_must_SEE_the_live_holder(self):
        door = _Door(["free", "free", "claimed"])
        out = M.measure_door(ROOT, guard_loader=lambda root: door,
                             holder=_doorholder())
        self.assertFalse(out["measured"])
        self.assertIn("базовый вердикт сцены `free`", out["reason"])

    def test_self_claim_scene_is_refused(self):
        door = _Door(["claimed", "claimed", "free"], self_claims=["pid1"])
        out = M.measure_door(ROOT, guard_loader=lambda root: door,
                             holder=_doorholder())
        self.assertFalse(out["measured"])
        self.assertIn("как МОЙ", out["reason"])

    def test_missing_verdict_is_the_third_outcome(self):
        door = _Door(["claimed", "claimed", "free"], drop_verdict=True)
        out = M.measure_door(ROOT, guard_loader=lambda root: door,
                             holder=_doorholder())
        self.assertFalse(out["measured"])
        self.assertIn("вердикт не произведён", out["reason"])

    def test_broken_scene_is_named_not_swallowed(self):
        def explode(root):
            raise RuntimeError("сцена не собралась (контроль)")
        out = M.measure_door(ROOT, guard_loader=explode, holder=_doorholder())
        self.assertFalse(out["measured"])
        self.assertIn("сцена пробы не отработала", out["reason"])


def _doorholder():
    """Чужая живая личность для герметичных сцен оси C — АРГУМЕНТОМ, не литералом."""
    return {"measured": True, "pid": os.getppid(),
            "start": "тест: личность родителя, живая по построению"}


# ───────────────────────────── отчёт и ступень моста ─────────────────────────────

class TestReport(unittest.TestCase):

    def test_shape_is_constant_in_the_third_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = _report(Path(tmp) / "нет.jsonl")
        for key in ("generated_at", "order", "measured", "status", "reason", "applied",
                    "population", "benefit", "harm", "cross_check", "door"):
            self.assertIn(key, report, f"ключ {key} исчез в третьем исходе")
        self.assertEqual(report["status"], M.STATUS_UNMEASURED)
        self.assertFalse(report["applied"], "прибор обязан оставаться читателем")

    def test_generated_at_comes_from_the_injected_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = _report(Path(tmp) / "нет.jsonl")
        self.assertEqual(report["generated_at"], "2026-01-02T03:04:05Z")

    def test_format_names_the_third_outcome_verbatim(self):
        lines = M.format_report({"measured": False, "reason": "журнал не прочитан (контроль)"})
        self.assertEqual(len(lines), 1)
        self.assertIn("НЕ ИЗМЕРЕНО", lines[0])
        self.assertIn("журнал не прочитан (контроль)", lines[0])

    def test_format_prints_every_axis_and_the_advisory_tail(self):
        holder = _holder()
        with tempfile.TemporaryDirectory() as tmp:
            log = _scene(Path(tmp), [
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "claim", "minutes": 0},
                {"session": "pid777001", "card": _CARD, "card_state": "done",
                 "minutes": 10},
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "done", "minutes": 20},
            ])
            report = _report(log, door={"measured": True,
                                        "verdict_without_done": "claimed",
                                        "holder": {"pid": 4242, "measured": True},
                                        "stranger_label": "pid4243",
                                        "one_holder_scene": "оговорка сцены",
                                        "by_branch": {
                                            M.BRANCH_HOLDER: {"verdict": "claimed",
                                                              "exit_code": 1,
                                                              "outcome": M.DOOR_PROTECTS},
                                            M.BRANCH_CARD: {"verdict": "free",
                                                            "exit_code": 0,
                                                            "outcome": M.DOOR_HANDS_OVER}}})
        text = "\n".join(M.format_report(report))
        for needle in ("[ОСЬ A]", "[ОСЬ B]", "[ОСЬ C]", "[СВЕРКА]", "ВЫВОД:",
                       "НЕ ДОКЛАДЫВАЕТ:", "ADVISORY:", M.DOOR_HANDS_OVER):
            self.assertTrue(needle in text, f"в отчёте нет {needle!r}")

    def test_absent_neighbour_measures_are_the_third_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = M.build_report(Path(tmp), now=NOW,
                                    neighbours={"guard": None, "sibling": None,
                                                "missing": ["check_card_claim"]})
        self.assertFalse(report["measured"])
        self.assertIn("check_card_claim", report["reason"])
        self.assertEqual(M.exit_code_for(report), 2)

    def test_absent_census_module_is_the_third_outcome(self):
        """Имя соседа читается в момент вызова — иначе в эту ветвь не попасть сценой."""
        was = M.CENSUS_MODULE
        M.CENSUS_MODULE = "spa_core.monitoring.нет_такого_соседа"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                report = M.build_report(Path(tmp), now=NOW,
                                        journal_path=Path(tmp) / "нет.jsonl")
        finally:
            M.CENSUS_MODULE = was
        self.assertFalse(report["measured"])
        self.assertIn("не ввезён", report["reason"])
        self.assertIsNone(report["population"])
        self.assertEqual(M.exit_code_for(report), 2)


class TestRun(unittest.TestCase):
    """Ступень моста: артефакт оставляется ВСЕГДА, включая третий исход."""

    def test_run_writes_the_artifact_even_when_unmeasured(self):
        with tempfile.TemporaryDirectory() as tmp:
            scene = Path(tmp)
            (scene / "data").mkdir()
            out = M.run(str(scene), now=NOW)
            path = scene / "data" / M.ARTIFACT_NAME
            self.assertTrue(path.is_file(), "артефакт не оставлен — "
                                            "«не измерено» не доедет до шага 0-офис")
            doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(doc["order"], M.ORDER)
        self.assertEqual(doc["generated_at"], "2026-01-02T03:04:05Z")
        self.assertEqual(bool(out["measured"]), bool(doc["measured"]))

    def test_unwritable_data_dir_is_named_not_swallowed(self):
        """«Каталога нет» проверкой НЕ является: атомарная запись создаёт его сама."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data").write_text("не каталог", encoding="utf-8")
            out = M.run(str(Path(tmp)), now=NOW)
        self.assertIn("artifact_not_written", out["doc"])

    def test_run_measures_a_whole_scene_tree_end_to_end(self):
        """Ступень на ОДНОРАЗОВОМ дереве: соседи, журнал и дверь — всё настоящее.

        Своё дерево предпосылкой не берётся: живого журнала в worktree и в CI нет по
        построению, и тест судил бы о везении хоста. Здесь дерево собирается целиком,
        поэтому вердикт `measured` — утверждение о приборе, а не о рабочем Маке.
        """
        holder = _holder()
        with tempfile.TemporaryDirectory() as tmp:
            scene = Path(tmp)
            (scene / "scripts").mkdir()
            for name in ("check_card_claim.py", "check_undelivered_work.py",
                         "log_session_change.py"):
                (scene / "scripts" / name).write_text(
                    (ROOT / "scripts" / name).read_text(encoding="utf-8"),
                    encoding="utf-8")
            data = scene / "data"
            data.mkdir()
            _scene(data, [
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "claim", "minutes": 0},
                {"session": "pid777001", "card": _CARD, "card_state": "done",
                 "minutes": 10},
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "done", "minutes": 20},
            ])
            out = M.run(str(scene), now=NOW)
            doc = json.loads((data / M.ARTIFACT_NAME).read_text(encoding="utf-8"))
        self.assertTrue(out["measured"], doc.get("reason"))
        self.assertEqual(doc["status"], M.STATUS_STRIPS_LIVE)
        self.assertEqual(doc["harm"]["by_outcome"][M.WITNESSED_WORKING], 1)
        self.assertTrue(doc["door"]["measured"], doc["door"].get("reason"))
        self.assertEqual(doc["door"]["by_branch"][M.BRANCH_CARD]["outcome"],
                         M.DOOR_HANDS_OVER)


class TestWiring(unittest.TestCase):
    """Проводка: ступень моста · манифест · поимённая ветка шага 0-офис."""

    @staticmethod
    def _has(text, needle):
        """Вхождение БЕЗ выгрузки файла в отчёт: `assertIn` печатает весь текст."""
        return needle in text

    def _require(self, text, needle, where):
        self.assertTrue(self._has(text, needle), f"{where}: не найдено {needle!r}")

    def test_bridge_stage_calls_the_instrument(self):
        text = (ROOT / "spa_core" / "monitoring" / "findings_bridge.py").read_text(
            encoding="utf-8")
        for needle in ("from spa_core.monitoring import foreign_done_cost",
                       "foreign_done_cost.run(root=args.root)",
                       f"data/{M.ARTIFACT_NAME}"):
            self._require(text, needle, "ступень моста")

    def test_manifest_declares_artifact_with_an_slo(self):
        manifest = json.loads((ROOT / "architecture" / "manifest.json").read_text(
            encoding="utf-8"))
        rows = [row for row in manifest["artifacts"]
                if row.get("path") == f"data/{M.ARTIFACT_NAME}"]
        self.assertEqual(len(rows), 1, "артефакт объявлен не ровно один раз")
        self.assertEqual(rows[0]["producer"], "com.spa.decision_loop")
        self.assertTrue(float(rows[0]["slo_hours"]) > 0)

    def test_office_step_has_a_named_branch_and_both_registry_lines(self):
        text = (ROOT / "scripts" / "consume_office_reports.py").read_text(
            encoding="utf-8")
        for needle in (f'elif name == "{M.ARTIFACT_NAME}":',
                       "from spa_core.monitoring.foreign_done_cost import format_report",
                       f'"{M.ARTIFACT_NAME}": (',
                       f'"{M.ARTIFACT_NAME}":\n'
                       '        "spa_core/monitoring/foreign_done_cost.py"'):
            self._require(text, needle, "шаг 0-офис")

    def test_the_office_step_really_PRINTS_the_instrument_numbers(self):
        """Проводка измеряется ИСХОДОМ, а не упоминанием имени в тексте файла.

        Вхождение строки говорит лишь «имя написано»; напечатает ли шаг 0-офис числа
        прибора, отвечает только ВЫЗОВ его отрисовки (`_summarize_json`) — ровно та
        разница, на которой ADR-683 нашёл артефакт, читаемый ВХОЛОСТУЮ.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_cor_fdc", str(ROOT / "scripts" / "consume_office_reports.py"))
        office = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(office)
        holder = _holder()
        with tempfile.TemporaryDirectory() as tmp:
            log = _scene(Path(tmp), [
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "claim", "minutes": 0},
                {"session": "pid777001", "card": _CARD, "card_state": "done",
                 "minutes": 10},
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "done", "minutes": 20},
            ])
            report = _report(log)
        text = "\n".join(office._summarize_json(f"data/{M.ARTIFACT_NAME}", report,
                                                now=NOW, root=str(ROOT)))
        for needle in ("[ОСЬ A]", "[ОСЬ B]", "[СВЕРКА]", M.STATUS_STRIPS_LIVE):
            self.assertTrue(needle in text, f"шаг 0-офис не напечатал {needle!r}")

    def test_declared_read_schema_matches_the_producer(self):
        """Перечень полей объявлен У ПРОИЗВОДИТЕЛЯ, а не придуман (урок ADR-683)."""
        text = (ROOT / "scripts" / "consume_office_reports.py").read_text(
            encoding="utf-8")
        self._require(text, f'"{M.ARTIFACT_NAME}": (', "реестр схемы")
        start = text.index(f'"{M.ARTIFACT_NAME}": (')
        declared = text[start:text.index(")", start)]
        with tempfile.TemporaryDirectory() as tmp:
            report = _report(Path(tmp) / "нет.jsonl")
        for field in ("status", "measured", "order", "applied", "population",
                      "benefit", "harm", "cross_check", "door"):
            self.assertTrue(f'"{field}"' in declared, f"поле {field} не объявлено")
            self.assertTrue(field in report, f"производитель поля {field} не несёт")


class TestWhatTheMutationRunFound(unittest.TestCase):
    """Звенья, которые мутационный замер назвал НЕПРОВЕРЕННЫМИ (цикл #825).

    Прогон цикла #824 (453 мутанта, убито 310) оставил 143 выживших, и разобраны они
    механически, по ИСХОДУ у батареи: 58 сверяются САМИ С СОБОЙ (тест берёт константу
    из модуля, поэтому мутант меняет обе стороны сравнения и покраснеть не может по
    построению), 12 эта мерка не разбирает (не константы верхнего уровня), а у 73
    проверки не было ВОВСЕ. Из этих 73 вред неодинаков, и тесты ниже закрывают ровно
    тот подкласс, где строка есть ИМЯ, по которому читает ЧИТАТЕЛЬ, а не проза:
    ключи образцов вреда, счётчики населения, поле статуса соседа, нормализация
    отметки и — отдельно — строки ТРЕТЬЕГО ИСХОДА отрисовки.

    Проза отчёта (61 выживший) намеренно НЕ пришпиливается дословно: её мутант ломает
    читаемость, а не вердикт, и держать 61 литерал в двух копиях значило бы заводить
    второе место для текста. Это сказано вслух и вынесено заказом, а не умолчано.
    """

    def _witnessed_scene(self, tmp: Path):
        """Сцена, где держатель объявил своё `done` ПОЗЖЕ чужого (вред засвидетельствован)."""
        holder = _holder()
        return _scene(tmp, [
            {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
             "card_state": "claim", "minutes": 0},
            {"session": "pid777001", "card": _CARD, "card_state": "done", "minutes": 10},
            {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
             "card_state": "done", "minutes": 20},
        ])

    def test_sample_rows_name_every_key_their_reader_reads(self):
        """Образец вреда читают ГЛАЗАМИ по именам полей — переименуй поле, и читатель ослепнет.

        Ключи перечислены здесь ЛИТЕРАЛАМИ намеренно: взять их из модуля значило бы
        сверить его с самим собой (ровно класс 58 выживших, которых убить нельзя).
        """
        with tempfile.TemporaryDirectory() as tmp:
            report = _report(self._witnessed_scene(Path(tmp)))
        sample = report["harm"]["examples"][M.WITNESSED_WORKING][0]
        self.assertEqual(set(sample), {"card", "identity_from", "claimed_at",
                                       "foreign_done_at", "evidence_at", "gap_hours"},
                         "состав полей образца изменился — читатель образца ослеп")
        self.assertEqual(sample["card"], _CARD)
        self.assertEqual(sample["gap_hours"], 0.17,
                         "разрыв «захват → чужой `done`» (10 мин) посчитан не в часах")

    def test_sample_stamps_are_normalised_to_Z_not_plus_offset(self):
        """Отметка образца обязана быть в форме ЕДИНСТВЕННОГО писателя журнала (`…Z`).

        Мутант, снявший нормализацию `+00:00` → `Z`, не менял ни одного вердикта: форма
        отметки читается только человеком и читателем-сверщиком, и до этого теста её не
        проверял никто.
        """
        with tempfile.TemporaryDirectory() as tmp:
            report = _report(self._witnessed_scene(Path(tmp)))
        sample = report["harm"]["examples"][M.WITNESSED_WORKING][0]
        for field in ("claimed_at", "foreign_done_at", "evidence_at"):
            stamp = sample[field]
            self.assertTrue(stamp.endswith("Z"), f"{field}: отметка не в форме писателя")
            self.assertNotIn("+00:00", stamp, f"{field}: смещение осталось сырым")

    def test_population_names_both_unparsed_counters(self):
        """Две двери «запись не вошла в население» обязаны называться по-своему.

        Склей их — и «записей без карточки» станет неотличимо от «отметка не разобрана»,
        то есть третий исход населения потеряет причину. Числа здесь измеренные: одна
        запись сцены написана БЕЗ карточки, отметки все разобраны.
        """
        holder = _holder()
        with tempfile.TemporaryDirectory() as tmp:
            log = _scene(Path(tmp), [
                {"session": holder["label"], "pid": holder["pid"], "card": _CARD,
                 "card_state": "claim", "minutes": 0},
                {"session": "pid777001", "card": _CARD, "card_state": "done",
                 "minutes": 10},
                {"session": holder["label"], "pid": holder["pid"], "minutes": 15,
                 "summary": "запись без карточки (контроль населения)"},
            ])
            report = _report(log)
        population = report["population"]
        self.assertEqual(population["records_without_card"], 1)
        self.assertEqual(population["records_with_card_unparsed_ts"], 0)

    def test_benefit_carries_the_neighbour_status_field(self):
        """Статус СОСЕДА ездит отдельным полем: это его вердикт, а не наш.

        Поле печатается в оси A рядом с числом пользы, и без него число нельзя отличить
        от числа, произведённого здесь (запрет ADR-220 на второй экземпляр мерки).
        """
        census = TestBenefitFromNeighbour._Census(
            {"measured": True, "status": "RELEASE_ADDRESSED_TO_HOLDER",
             "open_claims": {"card_declared_done_by_another_identity": 11}})
        out = M.measure_benefit(ROOT, census=census)
        self.assertEqual(out["neighbour_status"], "RELEASE_ADDRESSED_TO_HOLDER")
        self.assertEqual(out["useful_claims"], 11)
        self.assertEqual(out["neighbour"], M.CENSUS_MODULE)
        # Состав полей ЦЕЛИКОМ: объявление ключа в начале `measure_benefit` иначе не
        # имеет читателя вовсе (значение ему всё равно присваивается ниже), и мутант,
        # переименовавший ключ ОБЪЯВЛЕНИЯ, оставлял в отчёте лишнее поле молча.
        self.assertEqual(set(out), {"measured", "reason", "useful_claims",
                                    "neighbour_status", "neighbour"},
                         "в оси A появилось или исчезло поле — отчёт читают по именам")

    def test_format_names_the_third_outcome_of_EVERY_axis_verbatim(self):
        """У КАЖДОЙ оси свой третий исход, и в отчёте он обязан быть НАЗВАН.

        Выживший мутант снимал приставку оси у строки «НЕ ИЗМЕРЕНО» — и строка
        оставалась правдой, но переставала говорить, КАКАЯ ось не измерена. Батарея
        проверяла третий исход только у отчёта ЦЕЛИКОМ (`measured=False`), то есть у
        одной из четырёх дорог.
        """
        with tempfile.TemporaryDirectory() as tmp:
            report = _report(self._witnessed_scene(Path(tmp)))
        report["benefit"] = {"measured": False, "reason": "сосед не прочитан (контроль)"}
        report["cross_check"] = {"measured": False, "reason": "сверять нечем (контроль)"}
        report["door"] = {"measured": False, "reason": "дверь не открыта (контроль)"}
        text = "\n".join(M.format_report(report))
        for needle in ("[ОСЬ A] НЕ ИЗМЕРЕНО — сосед не прочитан (контроль)",
                       "[СВЕРКА] НЕ ИЗМЕРЕНО — сверять нечем (контроль)",
                       "[ОСЬ C] НЕ ИЗМЕРЕНО — дверь не открыта (контроль)"):
            self.assertTrue(needle in text,
                            f"третий исход оси не назван дословно: {needle!r}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
