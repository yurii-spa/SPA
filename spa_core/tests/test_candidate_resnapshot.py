"""Положительные контроли ПЕРЕСЪЁМКИ описания кандидата (ADR-798, заказ G797 п. 1).

Каждый тест — ВОПРОС, на который система обязана отвечать ПО-РАЗНОМУ в двух сценах:
«зелёный на одной сцене» не доказывает ничего (`.claude/rules/acceptance.md`, п. 3).
Сцены — настоящие строки ленты, прочитанные НАСТОЯЩЕЙ читающей моделью
(`research_factory.read.latest` / `.cio_view` через `retention.view_answers`), а не её
подобием: предмет правки — ОТВЕТ модели и РАЗРЕШЕНИЕ резать, и заглушка отвечала бы на
другой вопрос.

Два утверждения, которые обязаны держаться ОДНОВРЕМЕННО, и ни одно не следует из другого:

1. пересъёмка НЕ меняет ответ (иначе лекарство врёт) —
   `test_resnapshot_does_not_change_any_declared_view`, и отрицательный контроль
   `test_a_resnapshot_that_refreshes_generated_at_DOES_change_the_answer` показывает, что
   этот тест СПОСОБЕН покраснеть;
2. пересъёмка ОТКРЫВАЕТ окно усечения (иначе лекарства нет) —
   `test_resnapshot_opens_the_truncation_window`, и
   `test_description_alone_does_not_open_the_window_while_history_accumulates` показывает,
   что открывает его не она одна: рецепт из ADR-795/797 состоит из ЧЕТЫРЁХ писателей, и
   трое здешних без четвёртого (уплотнение) окна не дают.

# FROZEN-DATE-OK: injected-clock — якорь сцены ``ANCHOR`` литерал, и от него же вычислены
# ВСЕ отметки строк; момент замера приходит в код аргументом (``resnapshot(..., now=NOW)``,
# ``retention.largest_safe_cut(..., NOW)``, ``history.compact(..., now=NOW)``). Ни одна
# сторона вердикта не читает стенные часы.
"""

from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional

from spa_core.monitoring import ledger_resnapshot_price_census as price
from spa_core.monitoring import ledger_window_dependency_census as lwd
from spa_core.research_factory import contract, history, registry, resnapshot, retention
from spa_core.research_factory import run as run_mod
from spa_core.research_factory._common import ledger_for

ANCHOR = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
SPAN_DAYS = 6
#: Момент замера: сутки после последней строки сцены, то есть ВСЁ описание кандидата
#: старше такта пересъёмки, и резать по возрасту нельзя ничего.
NOW = ANCHOR + dt.timedelta(days=SPAN_DAYS, hours=2)
CANDIDATES = ("cand0", "cand1", "cand2")


def _iso(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _snapshot(cid: str, nonce: int, at: dt.datetime) -> dict:
    return {"kind": "candidate_snapshot",
            "key": ["candidate_snapshot", cid, f"{cid}-{nonce}"],
            "payload": {"candidate": {"candidate_id": cid, "domain": "D",
                                      "admission_state": None},
                        "fingerprint": f"{cid}-{nonce}"},
            "at": _iso(at)}


def _bundle(cid: str, nonce: int, at: dt.datetime) -> dict:
    return {"kind": "evidence_bundle", "key": ["evidence_bundle", cid, f"dig-{cid}-{nonce}"],
            "payload": {"candidate_id": cid, "evidence_digest": f"dig-{cid}-{nonce}",
                        "generated_at": _iso(at), "blocking_gaps": [], "conflicts": [],
                        "stale_evidence": [], "grades": {}, "paper_mode": None},
            "at": _iso(at)}


def _decision(cid: str, nonce: int, at: dt.datetime) -> dict:
    return {"kind": "admission_decision",
            "key": ["admission_decision", cid, f"dec-{cid}-{nonce}"],
            "payload": {"candidate_id": cid, "decision_id": f"dec-{cid}-{nonce}",
                        "bundle_digest": f"dig-{cid}-{nonce}", "generated_at": _iso(at),
                        "decision": "HOLD", "failed_gates": [], "unknowns": [],
                        "required_next_evidence": [], "evidence_ceiling": None,
                        "paper_mode": None, "rationale": "scene"},
            "at": _iso(at)}


def _run_row(nonce: int, at: dt.datetime) -> dict:
    return {"kind": "run", "key": ["run", f"r{nonce}"],
            "payload": {"generated_at": _iso(at), "denominators": {"scanned": 3}},
            "at": _iso(at)}


def _transition(cid: str, frm: Optional[str], to: str, reason: str, at: dt.datetime) -> dict:
    return {"kind": "transition", "key": ["transition", cid, None, to, _iso(at)],
            "payload": {"candidate_id": cid, "from_state": frm, "gate_ref": None,
                        "reason": reason, "to_state": to},
            "at": _iso(at)}


def scene_entries(*, with_transitions: bool = False) -> List[dict]:
    """Шесть суток ленты.

    Описание кандидата (снимок/свод/решение) записано ОДИН раз, в самые первые сутки, —
    ровно состояние живой ленты 24.10 (у 31 кандидата из 100 единственный
    ``candidate_snapshot`` со дня посева). Свежими остаются только строки ``run``,
    которые ничего о кандидате не утверждают: без них усечение было бы безопасно
    тривиально, потому что резать было бы нечего.
    """
    entries: List[dict] = []
    for day in range(SPAN_DAYS):
        at = ANCHOR + dt.timedelta(days=day)
        if day == 0:
            for index, cid in enumerate(CANDIDATES):
                base = at + dt.timedelta(minutes=index)
                entries.append(_snapshot(cid, day, base))
                entries.append(_bundle(cid, day, base + dt.timedelta(seconds=10)))
                entries.append(_decision(cid, day, base + dt.timedelta(seconds=20)))
            if with_transitions:
                for index, cid in enumerate(CANDIDATES):
                    entries.append(_transition(cid, None, contract.DISCOVERED,
                                               f"reason-{cid}",
                                               at + dt.timedelta(minutes=30 + index)))
        entries.append(_run_row(day, at + dt.timedelta(hours=1)))
    return entries


def build(root: Path, entries: List[dict], name: str = "scene") -> Path:
    data = Path(root) / name / "data"
    ordered = sorted(entries, key=lambda entry: (lwd._parse_at(entry["at"]), entry["kind"]))
    lwd.rechain(ordered, data)
    return data


def answers(data: Path) -> dict:
    """Полный ответ ОБОИХ объявленных читающих видов. Третий исход — громкий отказ."""
    doc, unmeasured = retention.view_answers(data, NOW)
    assert not unmeasured, f"НЕ ИЗМЕРЕНО: {unmeasured}"
    return doc


def raw_answers(data: Path) -> dict:
    """То же, но СЫРЫМИ отображениями — чтобы назвать РАСХОЖДЕНИЕ, а не только факт его.

    Виды берутся из того же объявления, которым их знает ``retention`` (а оно — у прибора
    цены разбора): своей копии перечня здесь нет, иначе тест охранял бы ответ, которого
    никто не читает.
    """
    from spa_core.monitoring import ledger_parse_census as census
    out = {}
    for member in retention.declared_views():
        fn, reason = census.resolve_view(member)
        assert fn is not None, f"НЕ ИЗМЕРЕНО: {member.id}: {reason}"
        out[member.id] = member.invoke(fn, Path(data), NOW) if member.invoke else fn(Path(data))
    return out


def leaf_paths_that_differ(left, right, path: str = "") -> List[str]:
    """Пути ЛИСТЬЕВ, разошедшихся между двумя ответами. Пустой список = ответ тот же."""
    if isinstance(left, dict) and isinstance(right, dict):
        out: List[str] = []
        for key in sorted(set(left) | set(right), key=repr):
            out += leaf_paths_that_differ(left.get(key), right.get(key), f"{path}.{key}")
        return out
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [f"{path}[len]"]
        out = []
        for index, (a, b) in enumerate(zip(left, right)):
            out += leaf_paths_that_differ(a, b, f"{path}[{index}]")
        return out
    return [] if left == right else [path or "."]


#: ЕДИНСТВЕННЫЙ лист ответа, которому пересъёмка вправе изменить значение: это хеш
#: ГОЛОВЫ ленты, то есть личность ФАЙЛА, а не утверждение о кандидате. Любая дописка
#: меняет его по построению — включая строку уплотнения ADR-795, — и усечению он при этом
#: безразличен: отрезание снимает ПРЕФИКС, а голова остаётся той же записью с тем же
#: хешем (``retention._stage_scene`` возит байты дословно). Вычет назван ОДНИМ листом и
#: подпёрт отрицательным контролем: подделка отметки наблюдения меняет ДРУГИЕ листья и
#: обязана краснеть.
LEDGER_IDENTITY_LEAVES = (".research_factory.ledger_head_hash",
                          ".research_factory.cio_view.ledger_head_hash")


class ResnapshotIsNeutral(unittest.TestCase):
    """Пересъёмка не вправе менять ответ — и тест обязан уметь это ОПРОВЕРГНУТЬ."""

    def test_resnapshot_does_not_change_any_declared_view(self):
        with TemporaryDirectory() as tmp:
            data = build(Path(tmp), scene_entries())
            before, before_raw = answers(data), raw_answers(data)
            report = resnapshot.resnapshot(data, now=NOW)
            self.assertEqual(len(report[resnapshot.OUTCOME_WRITTEN]),
                             len(CANDIDATES) * len(resnapshot.RESNAPSHOT_KINDS),
                             report)
            self.assertEqual(report[resnapshot.OUTCOME_ABSENT], [], report)
            drift = leaf_paths_that_differ(before_raw, raw_answers(data))
            self.assertEqual(sorted(drift), sorted(LEDGER_IDENTITY_LEAVES),
                             "пересъёмка изменила ответ читающей модели")
            self.assertNotEqual(before, answers(data),
                                "хеш головы ленты не изменился от дописки — вычет листа "
                                "перестал быть вычетом ОДНОГО листа, и его надо перемерить")

    def test_a_resnapshot_that_refreshes_generated_at_DOES_change_the_answer(self):
        """Отрицательный контроль: сверка ответа СПОСОБНА покраснеть.

        Воспроизводит именно тот соблазн, от которого писатель отказывается: обновить
        внутри payload отметку наблюдения. ``read._sherlock_block`` считает «решения за
        сегодня» по ``payload['generated_at']``, поэтому такая пересъёмка объявила бы
        вчерашние решения сегодняшними.
        """
        with TemporaryDirectory() as tmp:
            data = build(Path(tmp), scene_entries())
            before_raw = raw_answers(data)
            ledger = ledger_for(data)
            at = resnapshot.iso(NOW)
            for (kind, cid), entry in sorted(resnapshot.newest_rows(ledger).items()):
                if kind != "admission_decision":
                    continue
                payload = dict(entry["payload"])
                payload["generated_at"] = at          # ← единственное отличие от писателя
                ledger.append_idempotent(kind, resnapshot.resnapshot_key(kind, cid, at),
                                         payload, at)
            drift = leaf_paths_that_differ(before_raw, raw_answers(data))
            self.assertNotEqual([p for p in drift if p not in LEDGER_IDENTITY_LEAVES], [],
                                "подделка отметки наблюдения прошла незамеченной — сверка "
                                "ответа ничего не охраняет, и вычет листа её ослепил")


class ResnapshotOpensTheWindow(unittest.TestCase):
    """Лекарство обязано лечить: до пересъёмки резать нельзя НИЧЕГО, после — можно."""

    def test_resnapshot_opens_the_truncation_window(self):
        with TemporaryDirectory() as tmp:
            data = build(Path(tmp), scene_entries())
            before = retention.largest_safe_cut(data, NOW)
            self.assertEqual(before["largest_safe_cut_rows"], 0,
                             f"сцена не воспроизводит предмет ADR-797: {before}")
            resnapshot.resnapshot(data, now=NOW)
            after = retention.largest_safe_cut(data, NOW)
            self.assertGreater(after["largest_safe_cut_rows"], 0,
                              f"пересъёмка окна не открыла: {after}")

    def test_description_alone_does_not_open_the_window_as_wide_as_the_compaction_does(self):
        """Трое писателей — не четверо: история переходов продолжает держать ответ.

        Это не оговорка, а ЗАМЕР состава рецепта: ``read._rejection_reasons`` обходит
        ВСЕ ``transition`` кандидата, поэтому отрезание старых переходов меняет ответ,
        сколько бы описание ни переснимали. И обратно: с четвёртым писателем
        (``history.compact``) окно на той же сцене ШИРЕ.

        **Намеренная правка утверждения, цикл #922 (ADR-799, инв. #16.)** До ADR-799 тест
        требовал у трёх писателей РОВНО ``0``, и это было верно по ДВУМ причинам сразу:
        история переходов держала ответ И список кандидатов переставлялся префиксом.
        Вторую причину ADR-799 снял в источнике (``registry.all_candidate_ids`` отдаёт
        порядок как функцию множества), и ``0`` стало ``9`` — замер, а не регресс: предмет
        теста («трое ≠ четверо») измеряется теперь РАЗНИЦЕЙ окон, которая и есть вклад
        уплотнения, а не нулём, в который до сих пор складывались оба вклада. Замер
        2026-10-24 на этой сцене: трое — **9 из 27**, четверо — **17 из 30**. Погасить
        падение подстановкой ``9`` вместо ``0`` было бы тем самым запрещённым ослаблением:
        литерал закрепил бы случайное число сцены, а не утверждение о рецепте.
        """
        with TemporaryDirectory() as tmp:
            data = build(Path(tmp), scene_entries(with_transitions=True))
            resnapshot.resnapshot(data, now=NOW)
            three = retention.largest_safe_cut(data, NOW)
            self.assertLess(three["largest_safe_cut_rows"], three["rows"],
                            f"трое писателей открыли ленту ЦЕЛИКОМ — история переходов "
                            f"перестала держать ответ: {three}")
            history.compact(data, now=NOW)
            four = retention.largest_safe_cut(data, NOW)
            self.assertGreater(four["largest_safe_cut_rows"],
                               three["largest_safe_cut_rows"],
                               f"четвёртый писатель окна НЕ расширил — вклад уплотнения "
                               f"равен нулю: трое {three}, четверо {four}")


class TheRowIsDistinguishableAndHonest(unittest.TestCase):

    def test_payload_is_byte_identical_and_the_key_names_the_resnapshot(self):
        with TemporaryDirectory() as tmp:
            data = build(Path(tmp), scene_entries())
            ledger = ledger_for(data)
            original = {k: dict(e) for k, e in resnapshot.newest_rows(ledger).items()}
            resnapshot.resnapshot(data, now=NOW)
            fresh = resnapshot.newest_rows(ledger_for(data))
            for slot, entry in sorted(fresh.items()):
                self.assertTrue(resnapshot.is_resnapshot(entry),
                                f"{slot}: свежайшая запись не опознаётся как пересъёмка")
                self.assertEqual(contract.digest(entry["payload"]),
                                 contract.digest(original[slot]["payload"]),
                                 f"{slot}: содержимое записи изменилось")
                self.assertEqual(entry["at"], resnapshot.iso(NOW))
                self.assertNotEqual(entry["at"], original[slot]["at"])

    def test_an_observation_is_not_mistaken_for_a_resnapshot(self):
        with TemporaryDirectory() as tmp:
            data = build(Path(tmp), scene_entries())
            for entry in ledger_for(data).read_all():
                self.assertFalse(resnapshot.is_resnapshot(entry), entry.get("key"))


class ThreeOutcomesAreDistinguishable(unittest.TestCase):
    """Инв. #17 у писателя: записано · уже свежо · переснять НЕЧЕГО · ключ столкнулся."""

    def test_a_kind_the_candidate_never_had_is_named_absent_not_silently_skipped(self):
        entries = [e for e in scene_entries()
                   if not (e["kind"] == "evidence_bundle"
                           and e["key"][1] == CANDIDATES[0])]
        with TemporaryDirectory() as tmp:
            data = build(Path(tmp), entries)
            report = resnapshot.resnapshot(data, now=NOW)
            self.assertEqual(report[resnapshot.OUTCOME_ABSENT],
                             [{"candidate_id": CANDIDATES[0], "kind": "evidence_bundle"}],
                             report)
            self.assertEqual(len(report[resnapshot.OUTCOME_WRITTEN]),
                             len(CANDIDATES) * len(resnapshot.RESNAPSHOT_KINDS) - 1,
                             report)

    def test_a_fresh_row_is_already_current_not_rewritten(self):
        with TemporaryDirectory() as tmp:
            data = build(Path(tmp), scene_entries())
            early = ANCHOR + dt.timedelta(hours=3)   # сутки такта ещё не прошли
            report = resnapshot.resnapshot(data, now=early)
            self.assertEqual(report[resnapshot.OUTCOME_WRITTEN], [], report)
            self.assertEqual(len(report[resnapshot.OUTCOME_CURRENT]),
                             len(CANDIDATES) * len(resnapshot.RESNAPSHOT_KINDS), report)

    def test_a_concurrent_writer_in_the_same_second_is_a_key_collision_not_written(self):
        """Четвёртый исход достижим ГОНКОЙ, и только ею.

        Повторный ПОСЛЕДОВАТЕЛЬНЫЙ зов столкновения не даёт: после первого прохода
        свежайшая запись вида — уже пересъёмка, и писатель честно отвечает «уже свежо»
        (``test_a_second_sequential_call_is_already_current``). Столкнуться ключи могут
        только когда состояние ленты, ПРОЧИТАННОЕ писателем, успело устареть, — и
        подменяется здесь именно чтение состояния, а не предикат такта: подменив
        предикат, тест судил бы о своей подмене.
        """
        with TemporaryDirectory() as tmp:
            data = build(Path(tmp), scene_entries())
            stale = resnapshot.newest_rows(ledger_for(data))
            first = resnapshot.resnapshot(data, now=NOW)      # «чужой» писатель успел
            original = resnapshot.newest_rows
            resnapshot.newest_rows = lambda *a, **k: stale    # наш прочёл ленту ДО него
            try:
                second = resnapshot.resnapshot(data, now=NOW)
            finally:
                resnapshot.newest_rows = original
            self.assertEqual(second[resnapshot.OUTCOME_WRITTEN], [], second)
            self.assertEqual(second[resnapshot.OUTCOME_CURRENT], [], second)
            self.assertEqual(len(second[resnapshot.OUTCOME_COLLIDED]),
                             len(first[resnapshot.OUTCOME_WRITTEN]), second)

    def test_a_second_sequential_call_is_already_current(self):
        with TemporaryDirectory() as tmp:
            data = build(Path(tmp), scene_entries())
            resnapshot.resnapshot(data, now=NOW)
            second = resnapshot.resnapshot(data, now=NOW)
            self.assertEqual(second[resnapshot.OUTCOME_WRITTEN], [], second)
            self.assertEqual(second[resnapshot.OUTCOME_COLLIDED], [], second)
            self.assertEqual(len(second[resnapshot.OUTCOME_CURRENT]),
                             len(CANDIDATES) * len(resnapshot.RESNAPSHOT_KINDS), second)

    def test_an_unparsable_stamp_is_re_recorded_not_declared_fresh_forever(self):
        """Неразборная отметка обязана звать пересъёмку, а не выдавать строку за свежую.

        Замер судит ПРЕДИКАТ, а не сцену, и причина названа: сцену с такой строкой
        собрать нечем — сборщик ленты сортирует строки по разобранной отметке и падает
        на ``None`` ещё до записи. То есть строка с битой датой в ленту попасть может
        только от писателя, который её туда положил сам; предикат отвечает на вопрос
        «что делать, если она там уже есть», и это ровно то, что здесь измерено.
        """
        fresh = {"at": _iso(ANCHOR + dt.timedelta(hours=2))}
        old = {"at": _iso(ANCHOR - dt.timedelta(days=5))}
        broken = {"at": "не дата"}
        moment = ANCHOR + dt.timedelta(hours=3)
        self.assertFalse(resnapshot._is_due(fresh, moment, 1))
        self.assertTrue(resnapshot._is_due(old, moment, 1))
        self.assertTrue(resnapshot._is_due(broken, moment, 1),
                        "строка с битой датой объявлена свежей — она не переснимется НИКОГДА")
        self.assertFalse(resnapshot._is_due(None, moment, 1),
                         "отсутствие записи не есть повод переснимать — переснимать НЕЧЕГО, "
                         "и это отдельный исход (absent)")


class TheWriterBuildsThePricedRecipe(unittest.TestCase):
    """«Одно имя — один объект»: состав у писателя и у прибора цены обязан быть ОДИН."""

    def test_kinds_match_the_recipe_whose_window_was_measured(self):
        self.assertEqual(resnapshot.RESNAPSHOT_KINDS, resnapshot.declared_kinds())

    def test_the_priced_recipe_is_the_one_with_the_compaction_row(self):
        recipes = [r for r in price.RECIPES if r.compaction]
        self.assertEqual(len(recipes), 1, "рецепт с уплотнением не один — состав неоднозначен")
        self.assertEqual(tuple(recipes[0].newest_kinds), resnapshot.RESNAPSHOT_KINDS)

    def test_the_tact_is_not_longer_than_the_compaction_tact(self):
        self.assertLessEqual(resnapshot.TACT_DAYS, history.COMPACTION_TACT_DAYS)


def scene_with_one_freshly_observed_candidate() -> List[dict]:
    """Та же сцена, но у ``cand1`` есть ВТОРОЙ, свежий снимок — наблюдение внутри такта.

    Это живое состояние 24.10 в миниатюре: 62 кандидата из 100 были наблюдены дневным
    прогоном и пересъёмки не требуют, 38 — переснимаются. Пересъёмки ложатся в КОНЕЦ
    ленты, свежее наблюдение остаётся на своём месте, и порядок уцелевших снимков после
    отрезания префикса перестаёт быть порядком их открытия.
    """
    entries = scene_entries()
    entries.append(_snapshot(CANDIDATES[1], 99, NOW - dt.timedelta(hours=2)))
    return entries


def _first_appearance_order(ledger) -> list:
    """Тело ``registry.all_candidate_ids`` ДО ADR-799 — прибор, а не альтернатива.

    Нужен затем, чтобы утверждения ниже имели ЧУВСТВИТЕЛЬНОСТЬ: «порядок не изменился»
    без доказательства, что прежняя проводка его меняла, не отличалось бы от «сцена
    ничего не проверяет».
    """
    seen: list = []
    for entry in ledger.read_all():
        if entry.get("kind") != "candidate_snapshot":
            continue
        cid = ((entry.get("payload") or {}).get("candidate") or {}).get("candidate_id")
        if cid and cid not in seen:
            seen.append(cid)
    return seen


class TheOrderDiagnosisIsNotAPermission(unittest.TestCase):
    """Замер цикла #921 и его СНЯТИЕ циклом #922 — на одной и той же сцене.

    **Намеренная правка трёх утверждений, цикл #922 (ADR-799, инв. #16).** Класс был
    написан #921, когда мешал ПОРЯДОК списка кандидатов, и его тесты требовали у двух мер
    ПРОТИВОПОЛОЖНЫХ вердиктов на этой сцене. ADR-799 снял причину в источнике, поэтому
    требовать расхождения здесь стало требованием воспроизвести УСТРАНЁННЫЙ дефект —
    такой тест краснел бы не на регрессе, а на лекарстве. Утверждения переписаны на то,
    что на этой сцене ИЗМЕРЕНО сегодня, и каждое несёт свой контроль:

    * две меры СОШЛИСЬ — и прежняя проводка, подставленная тут же, их снова разводит;
    * ``shape`` в отчёте по-прежнему называет, ЧЕМ мерено (это утверждение не тронуто: им
      убита мутация ADR-798, зашивавшая ``"canonical"``);
    * вопросы двух мер остались РАЗНЫМИ — и это проверяется на самих функциях, а не на
      ленте: после ADR-799 отрезание ленты списков не переставляет, поэтому сцены,
      различающей две меры, сегодня не существует, и строить её имитацией значило бы
      подпирать правду подделкой.
    """

    def _scene(self, tmp) -> Path:
        data = build(Path(tmp), scene_with_one_freshly_observed_candidate())
        resnapshot.resnapshot(data, now=NOW)
        return data

    def test_the_two_measures_now_agree_on_the_scene_that_separated_them(self):
        """Замер #921 на этой сцене: строгая **0**, порядко-слепая **>0**. Сегодня — равны.

        Это и есть предмет ADR-799 в миниатюре (на живой ленте то же число: 0 → 25 161).
        """
        with TemporaryDirectory() as tmp:
            data = self._scene(tmp)
            strict = retention.largest_safe_cut(data, NOW)
            blind = retention.largest_safe_cut(
                data, NOW, shape=retention.canonical_ignoring_list_order)
            self.assertGreater(strict["largest_safe_cut_rows"], 0,
                               f"строгая мера снова не даёт резать ничего: {strict}")
            self.assertEqual(strict["largest_safe_cut_rows"],
                             blind["largest_safe_cut_rows"],
                             f"меры разошлись — порядок опять часть ответа: строго "
                             f"{strict}, слепо {blind}")
            self.assertEqual(strict["shape"], "canonical")
            self.assertEqual(blind["shape"], "canonical_ignoring_list_order")

            # Контроль: сцена ДЕЙСТВИТЕЛЬНО та, на которой прежняя проводка разводила меры.
            restore = registry.all_candidate_ids
            registry.all_candidate_ids = _first_appearance_order
            try:
                was = retention.largest_safe_cut(data, NOW)
            finally:
                registry.all_candidate_ids = restore
            self.assertEqual(was["largest_safe_cut_rows"], 0,
                             f"с ПРЕЖНИМ порядком строгая мера не отказывает — сцена не "
                             f"воспроизводит замер #921, и согласие мер выше ничего не "
                             f"значит: {was}")

    def test_the_cut_keeps_the_candidate_list_whole_and_in_place(self):
        """ЗАМЕР, а не вывод: после разрешённого отрезания список тот же — и по составу,
        и по порядку. До ADR-799 состав совпадал, а порядок — нет, и именно это отличие
        отказывало в отрезании."""
        with TemporaryDirectory() as tmp:
            data = self._scene(tmp)
            before = raw_answers(data)
            strict = retention.largest_safe_cut(data, NOW)
            self.assertGreater(strict["largest_safe_cut_rows"], 0, strict)
            import shutil
            import tempfile as tf
            scene = Path(tf.mkdtemp(prefix="order_"))
            try:
                retention._stage_scene(data, scene, strict["largest_safe_cut_rows"])
                after = raw_answers(scene / "data")
                ids_before = [c["candidate_id"]
                              for c in before["research_factory"]["candidates"]]
                ids_after = [c["candidate_id"]
                             for c in after["research_factory"]["candidates"]]
                self.assertEqual(set(ids_before), set(ids_after),
                                 "кандидат ПОТЕРЯН — это уже не про порядок")
                self.assertEqual(ids_before, ids_after,
                                 "список переставлен отрезанием — ADR-799 не держится")
                # Контроль чувствительности: прежняя проводка на ТОМ ЖЕ отрезании
                # переставляет список, то есть сравнение выше СПОСОБНО покраснеть.
                restore = registry.all_candidate_ids
                registry.all_candidate_ids = _first_appearance_order
                try:
                    was_before = _first_appearance_order(ledger_for(data))
                    was_after = _first_appearance_order(ledger_for(scene / "data"))
                finally:
                    registry.all_candidate_ids = restore
                self.assertEqual(set(was_before), set(was_after))
                self.assertNotEqual(was_before, was_after,
                                    "прежний порядок тоже не менялся — сцена не та")
            finally:
                shutil.rmtree(scene, ignore_errors=True)

    def test_the_measure_report_names_the_shape_it_measured_with(self):
        """Иначе «безопасно» строгое неотличимо от «безопасно, если закрыть глаза на порядок».

        Утверждение несущее, а не косметическое: дыру нашёл мутационный прогон ADR-798
        (выжила мутация, зашившая ``"canonical"``), и убивает её именно сверка ИМЕНИ меры
        в отчёте.

        Вторая половина теста держит то, ради чего поле вообще нужно: две меры задают
        РАЗНЫЕ вопросы. После ADR-799 на ленте этого больше не видно (отрезание списков
        не переставляет), поэтому вопрос спрашивается у самих функций — там, где он и
        живёт, и где ответ не зависит от того, повезло ли сегодняшней сцене.
        """
        with TemporaryDirectory() as tmp:
            data = self._scene(tmp)
            strict = retention.measure(data, 1, NOW)
            blind = retention.measure(data, 1, NOW,
                                      shape=retention.canonical_ignoring_list_order)
            self.assertEqual(strict["shape"], "canonical")
            self.assertEqual(blind["shape"], "canonical_ignoring_list_order")

        straight, reversed_ = ["a", "b"], ["b", "a"]
        self.assertNotEqual(retention.canonical(straight), retention.canonical(reversed_),
                            "строгая мера перестала видеть порядок списка — она больше "
                            "не строгая")
        self.assertEqual(retention.canonical_ignoring_list_order(straight),
                         retention.canonical_ignoring_list_order(reversed_),
                         "порядко-слепая мера порядок всё ещё видит — она не слепая")

    def test_cut_never_consults_the_order_blind_shape(self):
        """Диагностика, протёкшая в гейт, разрешила бы резать по более узкому вопросу."""
        import ast
        source = Path(retention.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        callers = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                name = None
                if isinstance(inner, ast.Name):
                    name = inner.id
                elif isinstance(inner, ast.Attribute):
                    name = inner.attr
                if name == "canonical_ignoring_list_order":
                    callers.add(node.name)
        callers.discard("canonical_ignoring_list_order")   # собственная рекурсия
        self.assertEqual(callers, {"main"},
                         "порядко-слепую меру зовёт не только CLI — она перестала быть "
                         f"диагностикой: {sorted(callers)}")


class TheDailyRunCallsTheWriter(unittest.TestCase):
    """Писатель без зова — это ADR-790: «написан и не позван»."""

    def test_run_once_calls_resnapshot_next_to_compaction(self):
        source = Path(run_mod.__file__).read_text(encoding="utf-8")
        self.assertIn("resnapshot.resnapshot(", source,
                      "дневной прогон не зовёт пересъёмку — рецепт снова построен на четверть")

    def test_resnapshot_does_not_make_registry_upsert_write_a_duplicate(self):
        """Пересъёмка не вправе ломать идемпотентность наблюдателя.

        ``registry.upsert`` судит по ОТПЕЧАТКУ свежайшего снимка, а не по ключу, поэтому
        после пересъёмки то же наблюдение обязано остаться no-op'ом.
        """
        with TemporaryDirectory() as tmp:
            data = build(Path(tmp), scene_entries())
            # НАСТОЯЩЕЕ наблюдение, с отпечатком, который считает сам наблюдатель:
            # отпечаток сцены был бы литералом, и тест судил бы о подделке.
            observed = {"candidate_id": "cand9", "domain": "D", "admission_state": None,
                        "instrument": "X"}
            registry.upsert(data, dict(observed), ANCHOR)
            resnapshot.resnapshot(data, now=NOW)
            rows_before = len(ledger_for(data).read_all())
            registry.upsert(data, dict(observed), NOW)
            self.assertEqual(len(ledger_for(data).read_all()), rows_before,
                             "наблюдение того же состояния записалось заново")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
