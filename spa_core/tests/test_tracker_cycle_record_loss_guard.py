# -*- coding: utf-8 -*-
"""Запись ЦИКЛА не исчезает молча у двери доставки (цикл #858).

**Положительный контроль — настоящая авария, и она не одна.** Стоячий приказ
владельца `inbox-task-portfolio-cio-dynamic-capital-alloc` — тетрадь, в которую
каждый цикл дописывает запись о своей работе (190 записей, 1,22 МиБ на 13.10).

* `359ce9406` (08.10.2026) принёс свою копию приказа ПОВЕРХ УСТАРЕВШЕЙ и унёс
  8586 строк: записей было **205**, осталось **151** — **56 записей циклов**
  (#716…#806). Сообщение коммита о них не говорит ни слова: автор их не удалял,
  он их НЕ ВИДЕЛ. Замер 13.10, пять суток спустя: их не вернул никто.
* `af88d6bfc` (25.09.2026) тем же способом унёс **9** записей (#684…#690) — их
  вернул следующий цикл, и ровно поэтому класс остался незамеченным.

**Почему молчали три существующих сторожа.** Дело НЕ в мере: `ENTRY_HEADER_RE`
видит `## Цикл #716` как запись. Дело в ЧЛЕНСТВЕ — карточки были исключены из
охраняемых классов намеренно («Всё прочее (код, карточки, `_BOARD.md`) не
трогаем», замер #139), и `is_append_only_doc`/`is_rules_doc` для этого пути
ложны. Это закреплено ниже обеими сторонами: старые проверки на аварийной паре
байт МОЛЧАТ, новая — ОТКАЗЫВАЕТ.

**Почему членство не решается старой мерой.** Цена ошибки обеих мер измерена на
ОДНОЙ популяции (вся история трекера: 1302 карточки, 2133 перехода): мера общей
тетради (любой `##`) — **538 отказов**, запись цикла — **2**, и это ровно две
аварии выше. Полный замер живёт в ADR-714 и в комментарии сторожа; здесь
закреплён его механизм — на типовой переписке тела карточки старая мера
краснеет, новая молчит.

**Фикстуры.** Заголовки записей взяты ПОБАЙТОВО из истории обеих аварий, тела
записей синтетические и короткие: предмет сторожа — ЗАПИСЬ (её тождество —
номер цикла), а не тело, а настоящие редакции весят 1,8 и 0,95 МиБ. Это сказано
вслух, потому что тела в фикстуре НЕ воспроизводят аварию побайтово; номера
записей, их кратность и порядок — воспроизводят. `git show` в тестах не зовётся:
CI клонирует на глубину 1, а скип превратил бы «не измерено» в неотличимое от
«прошло» (`.claude/rules/deployment.md`).

Времени в тестах нет: сравнение чисто содержательное.
"""
import importlib.util
import unittest
from pathlib import Path

from spa_core.tests._pusher_wiring import assert_branch_reaches, branch_of, calls_of

_ROOT = Path(__file__).resolve().parents[2]
_FIX = Path(__file__).resolve().parent / "fixtures" / "cycle_record_loss"
_spec = importlib.util.spec_from_file_location(
    "_pusher_under_test", _ROOT / "push_to_github.py")
pusher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pusher)

ORDER = "nimbalyst-local/tracker/inbox-task-portfolio-cio-dynamic-capital-alloc.md"
SHA = "359ce9406aa"

#: Номера, которые унесла доставка 08.10 — замер по блобам истории, не список из головы.
LOST_359 = [716, 717, 720, 721, 722, 723, 724, 725, 726, 727, 728, 729, 730, 731,
            732, 733, 735, 736, 737, 738, 739, 740, 741, 742, 743, 748, 749, 750,
            751, 752, 753, 754, 755, 756, 758, 759, 760, 761, 762, 763, 767, 768,
            772, 774, 779, 781, 782, 783, 784, 785, 786, 789, 802, 804, 805, 806]


def fx(name: str) -> bytes:
    return (_FIX / name).read_bytes()


def card(*records: int, task: bool = True) -> bytes:
    """Карточка-тетрадь из перечисленных записей; тело записи зависит от номера."""
    out = [b"---\nstatus: in-progress\n---\n\n"]
    if task:
        out.append("## Задание\n\nтекст задания.\n\n".encode())
    for n in records:
        out.append(f"## Цикл #{n} (замер) — сделано\n\nтело записи #{n}.\n\n".encode())
    return b"".join(out)


def restore_union(current: bytes, older: bytes) -> bytes:
    """`current` + блоки записей, которые есть ТОЛЬКО в `older` (по номеру).

    Та же операция, которой цикл #858 возвращает записи, унесённые доставкой:
    восстановление ОБЪЕДИНЕНИЕМ, а не возвратом старой копии.
    """
    have = {int(x) for x in pusher.entry_headers(current, pusher.CYCLE_RECORD_RE)}
    heads = list(pusher.CYCLE_RECORD_RE.finditer(older))
    out = [current]
    for i, m in enumerate(heads):
        if int(m.group("id")) in have:
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(older)
        out.append(b"\n" + older[m.start():end].rstrip() + b"\n")
    return b"".join(out)


class Incident359ce9406(unittest.TestCase):
    """Доставка 08.10, унёсшая 56 записей приказа, обязана НЕ пройти."""

    BEFORE = fx("order_359ce9406_before.md")
    AFTER = fx("order_359ce9406_after.md")

    def test_fixtures_are_the_incident(self):
        """Предпосылка контроля: фикстуры несут ту самую потерю, число в число."""
        before = pusher.entry_headers(self.BEFORE, pusher.CYCLE_RECORD_RE)
        after = pusher.entry_headers(self.AFTER, pusher.CYCLE_RECORD_RE)
        self.assertEqual((len(before), len(after)), (205, 151))
        lost, renamed = pusher.classify_missing_entries(
            self.BEFORE, self.AFTER, pusher.CYCLE_RECORD_RE)
        self.assertEqual(sorted(int(x) for x in lost), LOST_359)
        self.assertEqual(renamed, [], "в этой аварии перенумерованных записей не было")

    def test_the_incident_is_refused_and_names_the_records(self):
        with self.assertRaises(pusher.CycleRecordLossRefused) as got:
            pusher.guard_cycle_record_loss(ORDER, self.BEFORE, self.AFTER, SHA)
        msg = str(got.exception)
        self.assertIn("стёр бы 56 запис", msg)
        for num in ("#716", "#717", "#720"):
            self.assertIn(num, msg, f"отказ не назвал пропавшую запись {num}")

    def test_refusal_carries_the_three_clues(self):
        """Что пропало · что появилось взамен · куда поехал объём."""
        with self.assertRaises(pusher.CycleRecordLossRefused) as got:
            pusher.guard_cycle_record_loss(ORDER, self.BEFORE, self.AFTER, SHA)
        msg = str(got.exception)
        self.assertIn("появилось взамен", msg)
        self.assertIn("#807", msg)          # запись, ради которой пуш и делался
        self.assertIn("НЕТТО к remote", msg)
        self.assertIn("-", msg.split("объём файла:")[1][:12])   # файл УСОХ

    def test_the_single_door_refuses_it_too(self):
        """Проверка существует не сама по себе, а у двери `guard_content_loss`."""
        with self.assertRaises(pusher.CycleRecordLossRefused):
            pusher.guard_content_loss(ORDER, self.BEFORE, self.AFTER, SHA)

    def test_the_three_older_guards_stay_silent_on_it(self):
        """Дыра была в ЧЛЕНСТВЕ, а не в мере: старые классы этот путь не видят.

        Если этот тест когда-нибудь покраснеет — значит карточку завели ещё в
        один класс, и тогда замер цены ошибки (538 отказов у меры общей тетради)
        надо перемерить, а не гасить.
        """
        self.assertFalse(pusher.is_append_only_doc(ORDER))
        self.assertFalse(pusher.is_rules_doc(ORDER))
        self.assertEqual(
            pusher.guard_entry_loss(ORDER, self.BEFORE, self.AFTER, SHA), "")
        self.assertEqual(
            pusher.guard_rules_section_loss(ORDER, self.BEFORE, self.AFTER, SHA), "")


class IncidentAf88d6bfc(unittest.TestCase):
    """Второй случай класса (25.09, 9 записей) — тот же отказ, другая авария."""

    BEFORE = fx("order_af88d6bfc_before.md")
    AFTER = fx("order_af88d6bfc_after.md")

    def test_fixtures_are_the_incident(self):
        lost, _ = pusher.classify_missing_entries(
            self.BEFORE, self.AFTER, pusher.CYCLE_RECORD_RE)
        self.assertEqual(len(lost), 9)
        self.assertEqual(min(int(x) for x in lost), 684)

    def test_the_incident_is_refused(self):
        with self.assertRaises(pusher.CycleRecordLossRefused) as got:
            pusher.guard_content_loss(ORDER, self.BEFORE, self.AFTER, SHA)
        self.assertIn("стёр бы 9 запис", str(got.exception))

    def test_a_naive_revert_is_refused_and_it_is_RIGHT(self):
        """Починка «вернуть старую копию» сама стирает запись — и сторож это ловит.

        Это ЗАМЕР, а не рассуждение: доставка 25.09 не только унесла девять
        записей, но и добавила свою — **#697**. Поэтому «запушить версию ДО
        аварии» теряет #697, то есть повторяет аварию в обратную сторону, и отказ
        здесь ВЕРЕН. Урок — восстанавливать ОБЪЕДИНЕНИЕМ, а не возвратом; ровно
        так цикл #858 возвращает 56 записей, унесённых 08.10.
        """
        with self.assertRaises(pusher.CycleRecordLossRefused) as got:
            pusher.guard_content_loss(ORDER, self.AFTER, self.BEFORE, SHA)
        self.assertIn("#697", str(got.exception))

    def test_restoration_by_union_passes(self):
        """А объединение сторож не мешает делать: ни один номер не пропал."""
        union = restore_union(self.AFTER, self.BEFORE)
        kept = {int(x) for x in pusher.entry_headers(union, pusher.CYCLE_RECORD_RE)}
        self.assertTrue({684, 697} <= kept, "объединение обязано нести обе стороны")
        self.assertEqual(pusher.guard_content_loss(ORDER, self.AFTER, union, SHA), "")


class WhyTheOldMeasureWasRejected(unittest.TestCase):
    """Механизм замера цены ошибки: на типовой карточке мера-`##` краснеет.

    Полный замер — в ADR-714 (2133 перехода: 538 отказов против 2). Здесь
    закреплено, ПОЧЕМУ так получается: тело карточки штатно переписывают.
    """

    OLD = ("---\nstatus: new\n---\n\n## Что измерено\n\nбыло.\n\n"
           "## Что сделать\n\nшаг 1.\n\n## Как понять, что готово\n\nстрока.\n").encode()
    NEW = ("---\nstatus: in-progress\n---\n\n## Что измерено\n\nбыло.\n\n"
           "## Что делать (переписано)\n\nшаг 1 и 2.\n").encode()

    def test_the_append_only_measure_would_refuse_a_normal_card_rewrite(self):
        lost, _ = pusher.classify_missing_entries(
            self.OLD, self.NEW, pusher.ENTRY_HEADER_RE)
        self.assertTrue(lost, "мера общей тетради обязана видеть здесь потерю — "
                              "иначе замер 538 отказов необъясним")

    def test_the_cycle_record_measure_stays_silent_on_it(self):
        self.assertEqual(
            pusher.guard_cycle_record_loss(
                "nimbalyst-local/tracker/inbox-ordinary.md", self.OLD, self.NEW, SHA), "")

    def test_identity_is_the_number_not_the_header_text(self):
        """Заголовок записи переписывают (дата, ADR, заказ) — это НЕ потеря."""
        before = card(857, 858)
        after = before.replace(
            "## Цикл #858 (замер) — сделано".encode(),
            "## ЦИКЛ #858 (2026-10-13, ADR-714): заказ закрыт".encode())
        self.assertEqual(pusher.guard_cycle_record_loss(ORDER, before, after, SHA), "")


class Boundaries(unittest.TestCase):
    """Где сторож обязан молчать, где кричать и где сказать «не измерено»."""

    def test_only_tracker_cards_are_watched(self):
        before, after = card(1, 2), card(1)
        for path in ("docs/STATE.md", "push_to_github.py",
                     "nimbalyst-local/tracker/notes.txt", "docs/journal/2026-W42.md"):
            self.assertEqual(
                pusher.guard_cycle_record_loss(path, before, after, SHA), "",
                f"{path} не карточка трекера, а сторож о нём что-то сказал")
        with self.assertRaises(pusher.CycleRecordLossRefused):
            pusher.guard_cycle_record_loss(
                "nimbalyst-local/tracker/inbox-x.md", before, after, SHA)

    def test_membership_is_decided_by_content_not_by_a_list_of_names(self):
        """Карточка-ЗАДАНИЕ записей не имеет ⇒ сторож молчит по построению."""
        plain_before = ("---\nstatus: new\n---\n\n## Задание\n\nтекст.\n").encode()
        plain_after = ("---\nstatus: done\n---\n\n## Задание\n\nтекст.\n\n"
                       "## Итог\n\nготово.\n").encode()
        self.assertEqual(
            pusher.guard_cycle_record_loss(
                "nimbalyst-local/tracker/inbox-plain.md", plain_before, plain_after,
                SHA), "")

    def test_a_new_card_on_remote_has_nothing_to_lose(self):
        self.assertEqual(
            pusher.guard_cycle_record_loss(ORDER, None, card(1), None), "")

    def test_appending_a_record_is_not_a_loss(self):
        self.assertEqual(
            pusher.guard_cycle_record_loss(ORDER, card(857), card(857, 858), SHA), "")

    def test_unread_remote_is_refusal_when_our_copy_proves_a_notebook(self):
        """Файл на remote ЕСТЬ, тело не прочитано, наша копия — тетрадь ⇒ ОТКАЗ."""
        with self.assertRaises(pusher.CycleRecordLossRefused) as got:
            pusher.guard_cycle_record_loss(ORDER, None, card(857, 858), SHA)
        self.assertIn("НЕ ПРОЧИТАНО", str(got.exception))

    def test_unread_remote_without_records_is_the_named_third_outcome(self):
        """Единственный слепой угол класса — НАЗВАН, а не выдан за «чисто» (инв. #17).

        Ни молчания, ни отказа: тетрадь это или карточка-задание — сказать нечем,
        и сторож обязан это произнести.
        """
        note = pusher.guard_cycle_record_loss(
            "nimbalyst-local/tracker/inbox-plain.md", None,
            ("---\nstatus: new\n---\n\n## Задание\n\nтекст.\n").encode(), SHA)
        self.assertIn("НЕ ИЗМЕРЕНА", note)
        self.assertIn("не «чисто»", note)
        self.assertNotEqual(note, "")

    def test_allow_overwrite_is_the_conscious_door(self):
        self.assertEqual(
            pusher.guard_cycle_record_loss(ORDER, card(1, 2), card(1), SHA,
                                           allow_overwrite=True), "")

    def test_renumbering_with_identical_body_is_a_note_not_a_refusal(self):
        before = card(857)
        after = before.replace(b"#857 (", b"#859 (").replace(
            "тело записи #857.".encode(), "тело записи #857.".encode())
        note = pusher.guard_cycle_record_loss(ORDER, before, after, SHA)
        self.assertIn("перенумеровано", note)
        self.assertIn("#857", note)
        self.assertIn("#859", note)

    def test_multiplicity_matters(self):
        """Две записи с одним номером и одна уцелевшая — это потеря."""
        with self.assertRaises(pusher.CycleRecordLossRefused):
            pusher.guard_cycle_record_loss(ORDER, card(858, 858), card(858), SHA)


class Wiring(unittest.TestCase):
    """Сторож существует не в коде, а У ДВЕРИ: ветка → дверь → проверка."""

    def test_the_door_reaches_the_new_guard(self):
        self.assertIn("guard_cycle_record_loss",
                      calls_of("guard_content_loss"),
                      "дверь не зовёт проверку записей цикла")

    def test_both_branches_reach_it(self):
        for state in ("DIVERGENCE_SAFE", "DIVERGENCE_UNMEASURED"):
            assert_branch_reaches(branch_of(state), "guard_cycle_record_loss",
                                  f"ветка {state}")

    def test_the_unmeasured_branch_counts_cards_as_watched(self):
        """`watched` решает, пойдёт ли ветка без базы читать remote вообще.

        Проверка — ФОРМОЙ ВЫЗОВА в тексте ветки: 08.10 именно эта ветка и могла
        промолчать, потому что карточка в `watched` не входила.
        """
        branch = branch_of("DIVERGENCE_UNMEASURED")
        self.assertIn("is_tracker_card(repo_path)", branch,
                      "ветка «база не измерена» не считает карточку охраняемой — "
                      "проверка до неё не дойдёт")


if __name__ == "__main__":
    unittest.main()
