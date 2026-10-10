"""Батарея прибора «почему освобождение не сняло ничего» — заказ G111 п. 2 (ADR-536).

Каждый тест — положительный контроль одного звена: порвать звено ⇒ тест краснеет с
НАЗВАННОЙ причиной. Третий исход проверяется отдельно и ДОСЛОВНО по сообщению: иначе
«не измерено» стало бы неотличимо от «прошло» — ровно тот дефект, против которого
прибор и написан.

**Сцена журнала берётся у СОСЕДА** (``test_foreign_done_cost._scene``): она пишет
записи НАСТОЯЩИМ писателем (``log_session_change.record``) и подменяет только ``ts``.
Второй экземпляр этой сцены разошёлся бы с писателем молча (ADR-220).

**Номер процесса здесь — КЛЮЧ, а не претензия о живости.** Прибор не спрашивает ОС ни
разу: личность ему нужна только чтобы отличить один захват от другого. Поэтому якорь
сцены строится из ``os.getpid()`` (жив на любом хосте по построению), а РАЗНЫЕ якоря
одного ярлыка получаются разным ``session_pid_start`` — то есть без литерального pid
вовсе (``.claude/rules/deployment.md``, личность процесса).
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from spa_core.monitoring import empty_release_causes as M
from spa_core.monitoring.claim_release_census import load_neighbours
from spa_core.tests.test_foreign_done_cost import NOW, STAMP, _scene

ROOT = Path(__file__).resolve().parents[2]

# Литеральной даты в этом файле НЕТ НИ ОДНОЙ, поэтому и пометки освобождения нет:
# якорь ввезён у соседней батареи (`test_foreign_done_cost.NOW`, пометка живёт ТАМ) и
# уезжает ВХОДОМ в обе стороны — от него выводятся и отметки записей сцены
# (`_scene(..., base=NOW)`), и отметка трейла (`_trail_line`), и он же подаётся отчёту
# (`build_report(..., now=NOW)`). Пометка, поставленная при нуле своих литералов, была
# бы освобождением от класса, в котором файл не состоит (замер #826: сторож претензии
# правильно назвал её НЕПОДТВЕРЖДЁННОЙ). Отдельно: прибор о СВЕЖЕСТИ не спрашивает
# вовсе — он сравнивает отметку с отметкой, — поэтому календарь ему безразличен по
# построению, а не по договорённости.
_CARD = "inbox-proba-prichin-pustogo-osvobozhdeniya"
_OTHER_CARD = "inbox-proba-sosednyaya-kartochka"
_WRITER = "cycle-proba"

_START_A = "тест: якорь A, личность живая по построению"
_START_B = "тест: якорь B — тот же ярлык, ДРУГОЙ старт"


def _anchored(minutes, state, *, session=_WRITER, card=_CARD, start=_START_A):
    """Запись с ЯКОРЕМ: номер свой (жив всегда), якорь различается стартом."""
    return {"session": session, "minutes": minutes, "card": card,
            "card_state": state, "pid": os.getpid(), "start": start}


def _labelled(minutes, state, *, session=_WRITER, card=_CARD):
    """Запись БЕЗ якоря: личность остаётся ЯРЛЫКОМ (`identity_of` → ('label', …))."""
    return {"session": session, "minutes": minutes, "card": card, "card_state": state}


def _tracker(tmp: Path, cards: dict) -> Path:
    """Каталог карточек сцены. ``cards``: имя → текст (или ``None`` — карточки нет."""
    tracker = tmp / "tracker"
    tracker.mkdir(parents=True, exist_ok=True)
    for name, text in cards.items():
        if text is None:
            continue
        (tracker / f"{name}.md").write_text(text, encoding="utf-8")
    return tracker


def _stamp(minutes: int) -> str:
    """Отметка записи, ПРОИСХОДЯЩАЯ от впрыснутого якоря ``NOW``.

    Форма — та же, что у единственного писателя журнала (``STAMP`` соседней
    батареи): разойтись с ней значило бы получить «метка времени не разобрана», то
    есть померить свою сцену вместо прибора.
    """
    return (NOW + timedelta(minutes=minutes)).strftime(STAMP)


def _trail_line(writer: str = _WRITER) -> str:
    """Запись трейла сцены. Отметка ПРОИСХОДИТ от впрыснутого якоря ``NOW``.

    Дата здесь предметом НЕ является — трейл сверяется по ЯРЛЫКУ, — но литерал
    всё равно был бы литералом: сторож претензии `injected-clock` меряет
    ПРОИСХОЖДЕНИЕ значения, а не его роль, и он прав, что меряет именно так.
    """
    return (f"{NOW.isoformat()} new -> in-progress · queue.set_status · {writer}")


def _card_text(*, claimed_by=None, trail=(), body="тело карточки\n") -> str:
    """Карточка сцены. Поля-свидетели ставятся ТОЧНО так, как их пишет очередь."""
    head = ["---", "title: \"проба\"", "status: in-progress"]
    if claimed_by is not None:
        head.append(f"claimed_by: {claimed_by}")
    if trail:
        head.append("status_trail:")
        head.extend(f"  - \"{entry}\"" for entry in trail)
    head.append("---")
    return "\n".join(head) + "\n\n" + body


def _report(rows, cards=None, **kw):
    """Отчёт прибора по одноразовой сцене: свой журнал и свой каталог карточек."""
    tmp = Path(tempfile.mkdtemp(prefix="erc_"))
    log = _scene(tmp, rows, base=NOW)
    tracker = _tracker(tmp, cards if cards is not None else {_CARD: _card_text()})
    return M.build_report(ROOT, now=NOW, journal_path=log, tracker_dir=tracker, **kw)


def _counts(report):
    return report["causes"]["counts"]


# ───────────────────────────── контракт: имена пришпилены ─────────────────────────────

class TestContractNames(unittest.TestCase):
    """Имена вердиктов и причин — ЛИТЕРАЛЫ здесь, а не сверка модуля с собой.

    Сверка `M.CAUSE_DRIFT == M.CAUSE_DRIFT` переименовалась бы вместе с модулем и
    промолчала (заказ G685 п. 4 — ровно эта слепота). Цена выбора названа: имя живёт
    в двух копиях, зато переименование краснеет.
    """

    def test_status_names_are_pinned(self):
        self.assertEqual(M.STATUS_NAMED, "CAUSES_NAMED")
        self.assertEqual(M.STATUS_PARTLY, "CAUSES_PARTLY_UNMEASURED")
        self.assertEqual(M.STATUS_NONE, "NO_EMPTY_RELEASES")
        self.assertEqual(M.STATUS_UNMEASURED, "UNMEASURED")

    def test_cause_names_are_pinned_and_the_dictionary_is_closed(self):
        self.assertEqual(M.CAUSE_DRIFT, "identity_drift")
        self.assertEqual(M.CAUSE_OFF_JOURNAL, "claimed_off_journal")
        self.assertEqual(M.CAUSE_NO_CLAIM, "no_claim_anywhere")
        self.assertEqual(M.CAUSE_UNMEASURED_MENTION, "unmeasured_mention_only")
        self.assertEqual(M.CAUSE_UNMEASURED_CARD, "unmeasured_card_unreadable")
        self.assertEqual(M.CAUSE_UNMEASURED_WRITER, "unmeasured_writer_unnamed")
        self.assertEqual(M.CAUSES, ("identity_drift", "claimed_off_journal",
                                    "no_claim_anywhere",
                                    "unmeasured_mention_only",
                                    "unmeasured_card_unreadable",
                                    "unmeasured_writer_unnamed"))

    def test_unmeasured_causes_are_exactly_the_three_that_cannot_choose(self):
        self.assertEqual(M.UNMEASURED_CAUSES, ("unmeasured_mention_only",
                                               "unmeasured_card_unreadable",
                                               "unmeasured_writer_unnamed"))

    def test_witness_fields_are_pinned_and_the_takeover_reason_is_excluded(self):
        self.assertEqual(M.WITNESS_FIELDS, ("claimed_by", "status_trail"))
        self.assertEqual(M.WITNESS_FIELD_EXCLUDED, "claim_takeover_reason")
        self.assertNotIn(M.WITNESS_FIELD_EXCLUDED, M.WITNESS_FIELDS)

    def test_artifact_name_and_order_are_pinned(self):
        self.assertEqual(M.ARTIFACT_NAME, "empty_release_causes.json")
        self.assertIn("G111 п. 2", M.ORDER)
        self.assertIn("ADR-536", M.ORDER)


# ──────────────────────── причина №1: ярлык потерял якорь ────────────────────────

class TestIdentityDrift(unittest.TestCase):

    def test_same_label_different_anchor_is_DRIFT_not_a_missing_claim(self):
        """Захват под якорем A, освобождение под якорем B: ярлык ОДИН."""
        report = _report([_anchored(0, "claim", start=_START_A),
                          _anchored(10, "done", start=_START_B)])
        self.assertEqual(_counts(report)[M.CAUSE_DRIFT], 1)
        self.assertEqual(_counts(report)[M.CAUSE_NO_CLAIM], 0)
        self.assertEqual(report["causes"]["drift_shape"], {"anchor→anchor": 1})

    def test_anchor_lost_between_claim_and_release_is_DRIFT(self):
        report = _report([_anchored(0, "claim"), _labelled(10, "done")])
        self.assertEqual(_counts(report)[M.CAUSE_DRIFT], 1)
        self.assertEqual(report["causes"]["drift_shape"], {"anchor→label": 1})

    def test_anchor_gained_between_claim_and_release_is_DRIFT(self):
        report = _report([_labelled(0, "claim"), _anchored(10, "done")])
        self.assertEqual(_counts(report)[M.CAUSE_DRIFT], 1)
        self.assertEqual(report["causes"]["drift_shape"], {"label→anchor": 1})

    def test_drift_is_answered_even_when_the_CARD_IS_UNREADABLE(self):
        """Шаг 1 отвечает ИЗ ЖУРНАЛА — порядок вопросов существен, и вот его контроль.

        Карточки на диске нет. Переставь шаги местами — и дрейф уехал бы в
        ``unmeasured_card_unreadable``, то есть пропал бы как причина.
        """
        report = _report([_anchored(0, "claim", start=_START_A),
                          _anchored(10, "done", start=_START_B)],
                         cards={_CARD: None})
        self.assertEqual(_counts(report)[M.CAUSE_DRIFT], 1)
        self.assertEqual(_counts(report)[M.CAUSE_UNMEASURED_CARD], 0)

    def test_drift_WINS_over_a_card_witness_and_that_is_the_declared_order(self):
        report = _report([_anchored(0, "claim", start=_START_A),
                          _anchored(10, "done", start=_START_B)],
                         cards={_CARD: _card_text(claimed_by=_WRITER)})
        self.assertEqual(_counts(report)[M.CAUSE_DRIFT], 1)
        self.assertEqual(_counts(report)[M.CAUSE_OFF_JOURNAL], 0)

    def test_a_claim_by_ANOTHER_label_is_not_drift(self):
        report = _report([_anchored(0, "claim", session="cycle-chuzhoi"),
                          _anchored(10, "done", start=_START_B)])
        self.assertEqual(_counts(report)[M.CAUSE_DRIFT], 0)

    def test_a_claim_on_ANOTHER_card_is_not_drift(self):
        report = _report([_anchored(0, "claim", card=_OTHER_CARD, start=_START_A),
                          _anchored(10, "done", start=_START_B)],
                         cards={_CARD: _card_text(), _OTHER_CARD: _card_text()})
        self.assertEqual(_counts(report)[M.CAUSE_DRIFT], 0)

    def test_a_claim_in_the_SAME_second_IS_drift_because_the_door_reads_ge(self):
        """Граница правила двери: ``done`` не РАНЬШЕ захвата ⇒ захват снимается.

        Отдельный тест именно на РАВЕНСТВО отметок: сдвинь сравнение с ``<=`` на
        ``<`` — и этот случай молча уехал бы в «захвата нет нигде», то есть правило
        разошлось бы с дверью на одну секунду и ровно там, где ошибается писатель.
        """
        report = _report([_anchored(0, "claim", start=_START_A),
                          _anchored(0, "done", start=_START_B)])
        self.assertEqual(_counts(report)[M.CAUSE_DRIFT], 1)
        self.assertEqual(_counts(report)[M.CAUSE_NO_CLAIM], 0)

    def test_a_LATER_claim_is_not_drift_because_the_rule_comes_from_the_DOOR(self):
        """Правило «снял бы» — ``>=`` у двери: захват ПОЗЖЕ освобождения не снимается."""
        report = _report([_anchored(0, "done", start=_START_B),
                          _anchored(10, "claim", start=_START_A)])
        self.assertEqual(_counts(report)[M.CAUSE_DRIFT], 0)


# ──────────────── причина №2: карточка взята НЕ ЧЕРЕЗ ЖУРНАЛ ────────────────

class TestClaimedOffJournal(unittest.TestCase):

    def test_claimed_by_in_the_card_is_a_witness(self):
        report = _report([_anchored(0, "done")],
                         cards={_CARD: _card_text(claimed_by=_WRITER)})
        self.assertEqual(_counts(report)[M.CAUSE_OFF_JOURNAL], 1)
        self.assertEqual(_counts(report)[M.CAUSE_NO_CLAIM], 0)

    def test_status_trail_in_the_card_is_a_witness(self):
        """Трейл НЕСЁТ писателя, и читается он СВОИМ читателем блока.

        Положительный контроль мёртвого свидетеля: плоский разбор соседа отдаёт
        ``status_trail`` пустой строкой, поэтому спрашивать поле у него значило бы
        объявить свидетеля, которого читатель не видит ВОВСЕ (замер 10.10: причина
        №2 вышла бы 2 вместо 7 на живом журнале).
        """
        trail = [_trail_line()]
        text = _card_text(trail=trail)
        report = _report([_anchored(0, "done")], cards={_CARD: text})
        self.assertEqual(_counts(report)[M.CAUSE_OFF_JOURNAL], 1)

    def test_the_flat_neighbour_parser_really_DOES_drop_the_trail(self):
        """Та же претензия, спрошенная У СОСЕДА: иначе «свой читатель нужен» — проза."""
        guard = load_neighbours(ROOT)["guard"]
        self.assertIsNotNone(guard, "сосед не загрузился — претензия НЕ ИЗМЕРЕНА")
        trail = [_trail_line()]
        text = _card_text(trail=trail)
        self.assertEqual(guard.frontmatter(text).get("status_trail"), "")
        self.assertEqual(M.trail_entries(text), trail)

    def test_the_TAKEOVER_REASON_is_not_a_witness(self):
        """Оно называет ПЕРЕБИТЫЕ сессии — взять его значило бы изготовить свидетеля.

        Исход при этом НЕ «захвата нет нигде», а ЧЕТВЁРТЫЙ: ярлык в карточке
        ВСТРЕЧАЕТСЯ (в поле, свидетелем не объявленном), и про него известно ровно
        то, что он встречается. Объявить такую строку отсутствием захвата значило бы
        подменить «не измерено» измерением — с другой стороны, чем завышение.
        """
        text = _card_text(claimed_by="cycle-drugoi", body="")
        text = text.replace("---\n\n", f"claim_takeover_reason: перебит {_WRITER}\n---\n\n")
        self.assertIn("claim_takeover_reason", text, "сцена не поставила поле — мерить нечего")
        report = _report([_anchored(0, "done")], cards={_CARD: text})
        self.assertEqual(_counts(report)[M.CAUSE_OFF_JOURNAL], 0,
                         "перебитая сессия объявлена свидетелем — свидетель ИЗГОТОВЛЕН")
        self.assertEqual(_counts(report)[M.CAUSE_UNMEASURED_MENTION], 1)
        self.assertEqual(_counts(report)[M.CAUSE_NO_CLAIM], 0)

    def test_another_writer_in_the_card_does_not_witness_for_me(self):
        report = _report([_anchored(0, "done")],
                         cards={_CARD: _card_text(claimed_by="cycle-drugoi")})
        self.assertEqual(_counts(report)[M.CAUSE_OFF_JOURNAL], 0)
        self.assertEqual(_counts(report)[M.CAUSE_NO_CLAIM], 1)


# ─────────── причина №3 и ЧЕТВЁРТЫЙ исход: проза свидетелем не является ───────────

class TestNoClaimAndBodyMention(unittest.TestCase):

    def test_a_readable_card_without_any_witness_is_NO_CLAIM_ANYWHERE(self):
        report = _report([_anchored(0, "done")], cards={_CARD: _card_text()})
        self.assertEqual(_counts(report)[M.CAUSE_NO_CLAIM], 1)
        self.assertEqual(_counts(report)[M.CAUSE_UNMEASURED_MENTION], 0)

    def test_a_label_only_in_the_BODY_is_NOT_MEASURED_not_a_cause(self):
        """Главная находка прибора: нестрогая проба завысила бы причину №2."""
        report = _report([_anchored(0, "done")],
                         cards={_CARD: _card_text(body=f"упоминание {_WRITER} в прозе\n")})
        self.assertEqual(_counts(report)[M.CAUSE_UNMEASURED_MENTION], 1)
        self.assertEqual(_counts(report)[M.CAUSE_OFF_JOURNAL], 0,
                         "упоминание в прозе объявлено захватом — это и есть завышение")
        self.assertEqual(_counts(report)[M.CAUSE_NO_CLAIM], 0,
                         "упоминание в прозе объявлено отсутствием захвата — та же подмена, наоборот")
        self.assertEqual(report["causes"]["mention_only_witnesses"], 1)

    def test_an_absent_card_is_NOT_MEASURED_not_no_claim(self):
        report = _report([_anchored(0, "done")], cards={_CARD: None})
        self.assertEqual(_counts(report)[M.CAUSE_UNMEASURED_CARD], 1)
        self.assertEqual(_counts(report)[M.CAUSE_NO_CLAIM], 0)

    def test_an_EMPTY_writer_label_is_NOT_drift_but_its_own_unmeasured_outcome(self):
        """Пустой ярлык личностью НЕ является — спросить у него нельзя ничего.

        Сцена: безымянное «освобождение» и захват того же безымянного вида на
        ДРУГОЙ карточке. Строгий ключ не совпадает (карточка другая), и пусти
        пустой ярлык в ключ ПО ЯРЛЫКУ — он совпал бы, и прибор объявил бы ДРЕЙФОМ
        совпадение ДВУХ РАЗНЫХ безымянных писателей, то есть ВЫДУМАЛ причину там,
        где честный ответ «писатель не назван».

        **Запись строится здесь, а не НАСТОЯЩИМ писателем, и это ИЗМЕРЕНО, а не
        предположено:** писатель пустой ярлык не пишет НИКОГДА — он подставляет
        личность окружения (проверено ниже тем же писателем). Значит исход
        защищает от строки журнала, которую написал НЕ писатель: правка рукой,
        другой инструмент, порча файла. Сказать «писатель так может» было бы
        неправдой, а не закрыть класс — оставить выдуманную причину достижимой.
        """
        real = _scene(Path(tempfile.mkdtemp(prefix="erc_")),
                      [{"session": "", "minutes": 0, "card": _CARD,
                        "card_state": "claim"}], base=NOW)
        written = json.loads(real.read_text(encoding="utf-8").splitlines()[0])
        self.assertTrue(written.get("session"),
                        "писатель ВСЁ-ТАКИ записал пустой ярлык — тогда сцену надо "
                        "строить им, а не руками")

        tmp = Path(tempfile.mkdtemp(prefix="erc_"))
        log = tmp / "session_changes.jsonl"
        log.write_text("\n".join(json.dumps(
            {"ts": stamp, "session": "", "summary": "строка НЕ от писателя",
             "card": card, "card_state": state}, ensure_ascii=False)
            for stamp, card, state in (
                (_stamp(0), _OTHER_CARD, "claim"),
                (_stamp(10), _CARD, "done"))) + "\n",
            encoding="utf-8")
        report = M.build_report(ROOT, now=NOW, journal_path=log,
                                tracker_dir=_tracker(tmp, {_CARD: _card_text(),
                                                           _OTHER_CARD: _card_text()}))
        self.assertEqual(_counts(report)[M.CAUSE_UNMEASURED_WRITER], 1)
        self.assertEqual(_counts(report)[M.CAUSE_DRIFT], 0,
                         "совпадение ДВУХ безымянных писателей объявлено дрейфом одного")
        self.assertEqual(_counts(report)[M.CAUSE_NO_CLAIM], 0)
        self.assertEqual(report["causes"]["by_writer_top"][0]["writer"], "<ярлык пуст>")

    def test_the_two_unmeasured_outcomes_are_counted_apart(self):
        report = _report([_anchored(0, "done", card=_CARD),
                          _anchored(5, "done", card=_OTHER_CARD)],
                         cards={_CARD: _card_text(body=f"проза про {_WRITER}\n"),
                                _OTHER_CARD: None})
        counts = _counts(report)
        self.assertEqual(counts[M.CAUSE_UNMEASURED_MENTION], 1)
        self.assertEqual(counts[M.CAUSE_UNMEASURED_CARD], 1)
        self.assertEqual(report["causes"]["unmeasured"], 2)


# ───────────────────────── арифметика долей и разбор по писателю ─────────────────────

class TestSharesAndWriters(unittest.TestCase):

    def test_a_release_that_DID_remove_its_own_claim_is_not_counted(self):
        report = _report([_anchored(0, "claim"), _anchored(10, "done")])
        self.assertEqual(report["causes"]["empty_releases"], 0)
        self.assertEqual(report["status"], M.STATUS_NONE)

    def test_counts_sum_to_the_population_and_shares_to_a_hundred(self):
        report = _report([_anchored(0, "done", card=_CARD),
                          _anchored(5, "done", card=_OTHER_CARD),
                          _anchored(0, "claim", card="inbox-proba-tretya", start=_START_A),
                          _anchored(9, "done", card="inbox-proba-tretya", start=_START_B)],
                         cards={_CARD: _card_text(claimed_by=_WRITER),
                                _OTHER_CARD: _card_text(),
                                "inbox-proba-tretya": _card_text()})
        causes = report["causes"]
        self.assertEqual(sum(causes["counts"].values()), causes["empty_releases"])
        self.assertEqual(causes["empty_releases"], 3)
        self.assertAlmostEqual(sum(causes["shares_pct"].values()), 100.0, places=1)

    def test_by_writer_splits_the_SAME_population_not_another_one(self):
        report = _report([_anchored(0, "done", session="cycle-aa", card=_CARD),
                          _anchored(5, "done", session="cycle-bb", card=_OTHER_CARD)],
                         cards={_CARD: _card_text(), _OTHER_CARD: _card_text()})
        causes = report["causes"]
        self.assertEqual(causes["writers_total"], 2)
        per_writer = sum(row["empty_releases"] for row in causes["by_writer_top"])
        self.assertEqual(per_writer, causes["empty_releases"])
        self.assertEqual({row["writer"] for row in causes["by_writer_top"]},
                         {"cycle-aa", "cycle-bb"})

    def test_writers_are_ranked_so_the_heaviest_is_nameable(self):
        rows = [_anchored(m, "done", session="cycle-many", card=f"inbox-proba-{m}")
                for m in range(3)]
        rows.append(_anchored(9, "done", session="cycle-one", card=_OTHER_CARD))
        cards = {f"inbox-proba-{m}": _card_text() for m in range(3)}
        cards[_OTHER_CARD] = _card_text()
        report = _report(rows, cards=cards)
        top = report["causes"]["by_writer_top"][0]
        self.assertEqual(top["writer"], "cycle-many")
        self.assertEqual(top["empty_releases"], 3)

    def test_examples_are_capped_so_the_artifact_stays_readable(self):
        rows = [_anchored(m, "done", card=f"inbox-proba-{m}") for m in range(8)]
        cards = {f"inbox-proba-{m}": _card_text() for m in range(8)}
        report = _report(rows, cards=cards)
        self.assertEqual(_counts(report)[M.CAUSE_NO_CLAIM], 8)
        self.assertEqual(len(report["causes"]["examples"][M.CAUSE_NO_CLAIM]), 5)


# ──────────────────────────── вердикт и код возврата ────────────────────────────

class TestVerdict(unittest.TestCase):

    def test_all_causes_named_is_CAUSES_NAMED_and_code_zero(self):
        report = _report([_anchored(0, "done")], cards={_CARD: _card_text()})
        self.assertEqual(report["status"], M.STATUS_NAMED)
        self.assertEqual(report["causes"]["unmeasured"], 0)
        self.assertEqual(M.exit_code_for(report), 0)

    def test_any_unmeasured_cause_is_PARTLY_and_code_one(self):
        report = _report([_anchored(0, "done")], cards={_CARD: None})
        self.assertEqual(report["status"], M.STATUS_PARTLY)
        self.assertEqual(M.exit_code_for(report), 1)

    def test_zero_empty_releases_is_a_MEASURED_ZERO_not_unmeasured(self):
        report = _report([_anchored(0, "claim"), _anchored(10, "done")])
        self.assertEqual(report["status"], M.STATUS_NONE)
        self.assertTrue(report["measured"])
        self.assertEqual(M.exit_code_for(report), 0)
        self.assertIn("ИЗМЕРЕННЫЙ НУЛЬ", "\n".join(M.format_report(report)))

    def test_unmeasured_report_is_code_two_and_overrides_everything(self):
        report = {"measured": False, "status": M.STATUS_UNMEASURED}
        self.assertEqual(M.exit_code_for(report), 2)


# ───────────────────────────────── третьи исходы ─────────────────────────────────

class TestThirdOutcomes(unittest.TestCase):

    def test_unreadable_journal_is_the_third_outcome(self):
        tmp = Path(tempfile.mkdtemp(prefix="erc_"))
        report = M.build_report(ROOT, now=NOW, journal_path=tmp / "net-takogo.jsonl",
                                tracker_dir=tmp)
        self.assertFalse(report["measured"])
        self.assertEqual(report["status"], M.STATUS_UNMEASURED)
        self.assertIn("журнал не прочитан", report["reason"])

    def test_no_releases_at_all_is_the_third_outcome_not_a_clean_zero(self):
        report = _report([_anchored(0, "claim")])
        self.assertFalse(report["measured"])
        self.assertIn("освобождений в журнале нет", report["reason"])
        self.assertEqual(M.exit_code_for(report), 2)

    def test_missing_neighbour_is_the_third_outcome_and_names_the_measure(self):
        report = M.build_report(ROOT, now=NOW,
                                neighbours={"missing": ["check_card_claim"],
                                            "guard": None, "sibling": None})
        self.assertFalse(report["measured"])
        self.assertIn("check_card_claim", report["reason"])
        self.assertIn("своего экземпляра у прибора нет намеренно", report["reason"])

    def test_shape_is_constant_in_the_third_outcome(self):
        tmp = Path(tempfile.mkdtemp(prefix="erc_"))
        report = M.build_report(ROOT, now=NOW, journal_path=tmp / "net.jsonl",
                                tracker_dir=tmp)
        for key in ("generated_at", "order", "measured", "status", "reason",
                    "applied", "population", "causes", "cross_check"):
            self.assertIn(key, report, f"ключ `{key}` исчез в третьем исходе")

    def test_third_outcome_line_says_WHAT_was_not_measured(self):
        tmp = Path(tempfile.mkdtemp(prefix="erc_"))
        report = M.build_report(ROOT, now=NOW, journal_path=tmp / "net.jsonl",
                                tracker_dir=tmp)
        line = "\n".join(M.format_report(report))
        self.assertIn("НЕ ИЗМЕРЕНО", line)
        self.assertIn("заказ G111 п. 2", line)


# ──────────────────────────── сверка состава с соседом ────────────────────────────

class TestCrossCheck(unittest.TestCase):

    def test_agreement_is_reported_as_composition_not_as_confirmation(self):
        report = _report([_anchored(0, "done")], cards={_CARD: _card_text()})
        checked = report["cross_check"]
        self.assertTrue(checked["agrees"])
        self.assertEqual(checked["neighbour_released_nothing"], 1)
        self.assertIn("подтверждением не является", checked["means"])

    def test_disagreement_is_NAMED_as_a_wiring_defect(self):
        checked = M.cross_check({"empty_releases": 7},
                                {"measured": True, "released_nothing": 9})
        self.assertFalse(checked["agrees"])
        self.assertIn("РАЗОШЁЛСЯ", checked["reason"])

    def test_unmeasured_neighbour_is_the_third_outcome_not_agreement(self):
        checked = M.cross_check({"empty_releases": 7},
                                {"measured": False, "reason": "нет освобождений"})
        self.assertIsNone(checked["agrees"])
        self.assertIsNone(checked["neighbour_released_nothing"])
        self.assertIn("сосед не измерил", checked["reason"])

    def test_the_REAL_neighbour_declares_the_field_the_instrument_reads(self):
        """Сторож переименования: поле соседа читается ПО ИМЕНИ, и имя — его."""
        from spa_core.monitoring import claim_release_census as NB
        tmp = Path(tempfile.mkdtemp(prefix="erc_"))
        log = _scene(tmp, [_anchored(0, "done")], base=NOW)
        kin = load_neighbours(ROOT)
        journal = NB.read_journal(log)
        pop = NB.split_population(journal["records"], guard=kin["guard"],
                                  sibling=kin["sibling"])
        writers = NB.measure_writers(pop["claims"], pop["releases"])
        self.assertIn("released_nothing", writers)
        self.assertIn("measured", writers)


# ──────────────────────────────── отрисовка отчёта ────────────────────────────────

class TestReport(unittest.TestCase):

    def test_every_cause_is_PRINTED_so_the_office_step_cannot_hide_one(self):
        report = _report([_anchored(0, "done", card=_CARD),
                          _anchored(5, "done", card=_OTHER_CARD)],
                         cards={_CARD: _card_text(body=f"проза {_WRITER}\n"),
                                _OTHER_CARD: None})
        text = "\n".join(M.format_report(report))
        for cause in M.CAUSES:
            self.assertIn(cause, text, f"причина `{cause}` не напечатана")
        self.assertIn("[НЕ ИЗМЕРЕНО]", text)
        self.assertIn("НЕ ДОКЛАДЫВАЕТ", text)

    def test_the_overstatement_of_the_loose_probe_is_printed_as_a_number(self):
        report = _report([_anchored(0, "done")],
                         cards={_CARD: _card_text(body=f"проза {_WRITER}\n")})
        text = "\n".join(M.format_report(report))
        self.assertIn("нестрогая проба", text)
        self.assertIn("считаются НЕИЗМЕРЕННЫМИ", text)

    def test_generated_at_comes_from_the_injected_clock(self):
        report = _report([_anchored(0, "done")], cards={_CARD: _card_text()})
        self.assertEqual(report["generated_at"],
                         NOW.isoformat().replace("+00:00", "Z"))

    def test_the_excluded_witness_field_is_named_in_the_output(self):
        report = _report([_anchored(0, "done")], cards={_CARD: _card_text()})
        text = "\n".join(M.format_report(report))
        self.assertIn("claim_takeover_reason", text)


# ───────────────────────────── артефакт и точка входа ─────────────────────────────

class TestArtifact(unittest.TestCase):

    def test_run_leaves_the_artifact_even_in_the_third_outcome(self):
        tmp = Path(tempfile.mkdtemp(prefix="erc_"))
        (tmp / "data").mkdir()
        (tmp / "spa_core").mkdir()
        out = M.run(root=str(tmp), now=NOW)
        self.assertFalse(out["measured"])
        written = tmp / "data" / M.ARTIFACT_NAME
        self.assertTrue(written.exists(),
                        "артефакт третьего исхода не записан — «не измерено» стало "
                        "неотличимо от «ступень не запускалась»")
        doc = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual(doc["status"], M.STATUS_UNMEASURED)
        self.assertIsNotNone(doc["reason"])

    def test_save_artifact_uses_the_declared_name(self):
        tmp = Path(tempfile.mkdtemp(prefix="erc_"))
        path = M.save_artifact({"status": M.STATUS_UNMEASURED}, tmp)
        self.assertEqual(path.name, "empty_release_causes.json")
        self.assertTrue(path.exists())

    def test_the_instrument_only_READS(self):
        self.assertFalse(_report([_anchored(0, "done")],
                                 cards={_CARD: _card_text()})["applied"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
