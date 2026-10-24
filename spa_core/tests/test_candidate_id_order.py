"""Порядок кандидатов — функция МНОЖЕСТВА, а не префикса ленты (ADR-799, заказ G798 п. 1).

Предмет: ``registry.all_candidate_ids``. Обходом этой функции читающая модель строит
``latest.candidates``, ``latest.rejections``, ``latest.stale_feeds`` и списки ``cio_view``,
то есть место в списке уезжает читателю. До ADR-799 порядок был порядком ПЕРВОГО
ПОЯВЛЕНИЯ в ленте, и замер цикла #921 (ADR-798) назвал цену этого выбора: на живой ленте
снятие САМОЙ СТАРОЙ записи не теряло НИЧЕГО (множество кандидатов то же, каждый лист тот
же), но первый кандидат переезжал с места 0 на место 48 — и строгая сверка полного ответа
ВЕРНО называла это изменением ответа. Наибольшее безопасное отрезание: **0 из 25 601** при
порядко-слепой мере **25 161**.

Четыре вопроса, и ни один не следует из другого:

1. порядок не зависит от префикса — ``OrderIsAFunctionOfTheSet``;
2. сцена ДЕЙСТВИТЕЛЬНО воспроизводит дефект (иначе п. 1 зелен вакуумно) — тот же класс
   проверяется прямо там же, через точную копию ПРЕЖНЕГО тела функции;
3. на НАСТОЯЩЕЙ читающей модели (``retention.measure``, то есть ``read.latest`` +
   ``read.cio_view``) отрезание стало РАЗРЕШЕНО, а с прежней проводкой — ОТКАЗАНО;
   это положительный контроль на живом приборе, а не на подобии;
4. гейт при этом НЕ ослаблен: отрезание, которое теряет кандидата, обязано ОТКАЗАТЬ —
   ``TheGateIsNotWeakened``.

# FROZEN-DATE-OK: injected-clock — якорь сцены ``ANCHOR`` литерал, от него же вычислены
# ВСЕ отметки строк и момент замера ``NOW``; момент приходит в проверяемый код
# аргументом (``retention.measure(..., NOW, ...)``, ``retention.view_answers(data, NOW)``).
# Ни одна сторона вердикта не читает стенные часы.
"""

from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional

from spa_core.monitoring import ledger_window_dependency_census as lwd
from spa_core.research_factory import contract, registry, retention
from spa_core.research_factory._common import ledger_for
from spa_core.utils.hash_ledger import HashLedger

ANCHOR = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
SPAN_DAYS = 6
#: Момент замера — сутки после последней строки сцены: всё описание старше такта
#: пересъёмки, поэтому «безопасно» не может достаться сцене тривиально.
NOW = ANCHOR + dt.timedelta(days=SPAN_DAYS, hours=2)

#: Порядок ПЕРВОГО ПОЯВЛЕНИЯ в ленте — намеренно НЕ алфавитный. Если бы он совпадал с
#: алфавитным, тест не отличил бы одно от другого и был бы зелен вакуумно.
CANDIDATES = ("b-cand", "a-cand", "c-cand")


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


def _described(entries: List[dict], cid: str, nonce: int, at: dt.datetime) -> None:
    """Полное описание кандидата одним тактом: снимок + свод + решение."""
    entries.append(_snapshot(cid, nonce, at))
    entries.append(_bundle(cid, nonce, at + dt.timedelta(seconds=10)))
    entries.append(_decision(cid, nonce, at + dt.timedelta(seconds=20)))


def scene_entries(*, redescribe_on_day: Optional[int] = 3) -> List[dict]:
    """Сцена, воспроизводящая замер #921.

    День 0 — описание каждого кандидата в порядке :data:`CANDIDATES`. При
    ``redescribe_on_day`` описание повторяется ещё раз (другой отпечаток), поэтому снятие
    ПЕРВОГО снимка кандидата ``b-cand`` не теряет его из множества — меняется только
    порядок первого появления. ``redescribe_on_day=None`` даёт сцену, где описание ОДНО:
    там то же отрезание ТЕРЯЕТ кандидата, и гейт обязан отказать.
    """
    entries: List[dict] = []
    for index, cid in enumerate(CANDIDATES):
        _described(entries, cid, 0, ANCHOR + dt.timedelta(minutes=index))
    if redescribe_on_day is not None:
        day = ANCHOR + dt.timedelta(days=redescribe_on_day)
        for index, cid in enumerate(CANDIDATES):
            _described(entries, cid, 1, day + dt.timedelta(minutes=index))
    for day in range(SPAN_DAYS):
        entries.append(_run_row(day, ANCHOR + dt.timedelta(days=day, hours=1)))
    return entries


def build(root: Path, entries: List[dict], name: str) -> Path:
    data = Path(root) / name / "data"
    ordered = sorted(entries, key=lambda entry: (lwd._parse_at(entry["at"]), entry["kind"]))
    lwd.rechain(ordered, data)
    return data


def cut_prefix(src: Path, dst_root: Path, cut_rows: int, name: str) -> Path:
    """Сцена с СНЯТЫМ префиксом — ровно то, что делает ``retention._stage_scene``.

    Байты возятся дословно: отрезание снимает ведущие строки и не пересчитывает цепь,
    поэтому сравнение «до ↔ после» остаётся сравнением ответа, а не двух разных лент.
    """
    led = ledger_for(Path(src))
    data = Path(dst_root) / name / "data"
    (data / led.subdir).mkdir(parents=True, exist_ok=True)
    (data / led.anchors_subdir).mkdir(parents=True, exist_ok=True)
    lines = led.ledger_path().read_text(encoding="utf-8").splitlines(keepends=True)
    (data / led.subdir / led.ledger_name).write_text("".join(lines[cut_rows:]),
                                                     encoding="utf-8")
    (data / led.anchors_subdir / led.anchors_path().name).write_text(
        led.anchors_path().read_text(encoding="utf-8"), encoding="utf-8")
    return data


def first_appearance_order(ledger: HashLedger) -> list:
    """ТОЧНАЯ копия тела ``all_candidate_ids`` ДО ADR-799.

    Существует не как альтернатива, а как ПРИБОР: ею тест доказывает, что сцена
    действительно переставляет порядок первого появления. Без этого доказательства
    «порядок не изменился» не отличалось бы от «сцена ничего не проверяет».
    """
    seen: list = []
    for e in ledger.read_all():
        if e.get("kind") != "candidate_snapshot":
            continue
        cid = ((e.get("payload") or {}).get("candidate") or {}).get("candidate_id")
        if cid and cid not in seen:
            seen.append(cid)
    return seen


def rows_of(data: Path) -> int:
    return len(ledger_for(Path(data)).read_all())


#: Сколько ведущих строк снимает сцена. Первая строка ленты — снимок ``b-cand`` (он первый
#: в :data:`CANDIDATES`), поэтому ОДНОЙ строки достаточно, чтобы переставить порядок
#: первого появления, и этого же мало, чтобы потерять кандидата, пока описание повторено.
CUT_ROWS = 1


class OrderIsAFunctionOfTheSet(unittest.TestCase):
    """Порядок обязан зависеть от МНОЖЕСТВА кандидатов и ни от чего больше."""

    def test_order_is_sorted_and_the_scene_really_reorders_first_appearance(self):
        with TemporaryDirectory() as tmp:
            full = build(Path(tmp), scene_entries(), "full")
            cut = cut_prefix(full, Path(tmp), CUT_ROWS, "cut")
            led_full, led_cut = ledger_for(full), ledger_for(cut)

            # (2) сцена воспроизводит дефект: прежний порядок ПЕРЕСТАВЛЕН...
            was_full = first_appearance_order(led_full)
            was_cut = first_appearance_order(led_cut)
            self.assertEqual(was_full, list(CANDIDATES), "сцена собралась не тем порядком")
            self.assertNotEqual(was_full, was_cut,
                                "префикс не переставил порядок первого появления — сцена "
                                "не проверяет предмет, и зелёный тест ничего не значит")
            # ...а множество при этом ТО ЖЕ: иначе отказ гейта был бы ВЕРЕН, и лечить
            # было бы нечего.
            self.assertEqual(set(was_full), set(was_cut))
            self.assertEqual(rows_of(cut), rows_of(full) - CUT_ROWS)

            # (1) предмет: порядок — функция множества.
            self.assertEqual(registry.all_candidate_ids(led_full), sorted(CANDIDATES))
            self.assertEqual(registry.all_candidate_ids(led_cut),
                             registry.all_candidate_ids(led_full),
                             "порядок всё ещё зависит от префикса ленты")

    def test_order_does_not_depend_on_the_order_rows_were_written(self):
        """Та же сцена, записанная в ОБРАТНОМ порядке суток, обязана дать тот же список.

        Это второй, независимый вопрос: п. 1 снимает зависимость от СНЯТОГО префикса, этот
        — от порядка, в котором кандидатов вообще увидели. Один и тот же состав ленты,
        два разных порядка записи, один ответ.
        """
        with TemporaryDirectory() as tmp:
            forward = build(Path(tmp), scene_entries(), "forward")
            entries = scene_entries()
            backward = build(Path(tmp), list(reversed(entries)), "backward")
            self.assertEqual(registry.all_candidate_ids(ledger_for(forward)),
                             registry.all_candidate_ids(ledger_for(backward)))


class TheReadingModelNoLongerRefusesTheCut(unittest.TestCase):
    """Положительный контроль на НАСТОЯЩЕМ приборе: ``retention.measure``.

    Вопрос один и тот же, проводка — разная, и ответы ОБЯЗАНЫ быть противоположными.
    """

    def test_cut_is_permitted_with_the_set_order_and_refused_with_first_appearance(self):
        with TemporaryDirectory() as tmp:
            data = build(Path(tmp), scene_entries(), "scene")

            permitted = retention.measure(data, CUT_ROWS, NOW)
            self.assertTrue(permitted["measured"], permitted)
            self.assertTrue(permitted["safe"],
                            f"отрезание всё ещё отказано: {permitted.get('differs')}")
            self.assertEqual(permitted["differs"], [], permitted)
            self.assertEqual(permitted["shape"], "canonical",
                             "разрешение выдано НЕ строгой сверкой — это другое "
                             "утверждение")

            # Прежняя проводка на ТОЙ ЖЕ сцене обязана ОТКАЗАТЬ: иначе тест выше зелен не
            # потому, что порядок вылечен, а потому, что сцена ничего не меряет.
            restore = registry.all_candidate_ids
            registry.all_candidate_ids = first_appearance_order
            try:
                refused = retention.measure(data, CUT_ROWS, NOW)
            finally:
                registry.all_candidate_ids = restore
            self.assertTrue(refused["measured"], refused)
            self.assertFalse(refused["safe"],
                             "с ПРЕЖНИМ порядком отрезание оказалось безопасным — значит "
                             "сцена не воспроизводит замер #921")
            self.assertTrue(refused["differs"], refused)

    def test_the_strict_and_the_order_blind_measures_now_agree(self):
        """Строгая и порядко-слепая меры обязаны СОЙТИСЬ на этой сцене.

        Именно их расхождение (0 против 25 161 на живой ленте) и было предметом ADR-799.
        Диагностическая мера остаётся диагностической — здесь она ЧИТАЕТСЯ, а не получает
        право разрешать.
        """
        with TemporaryDirectory() as tmp:
            data = build(Path(tmp), scene_entries(), "scene")
            strict = retention.measure(data, CUT_ROWS, NOW)
            blind = retention.measure(data, CUT_ROWS, NOW,
                                      shape=retention.canonical_ignoring_list_order)
            self.assertTrue(blind["measured"] and strict["measured"], (strict, blind))
            self.assertEqual(strict["safe"], blind["safe"],
                             "строгая мера и порядко-слепая всё ещё отвечают по-разному — "
                             "значит порядок остался частью ответа")


class TheGateIsNotWeakened(unittest.TestCase):
    """Обратный контроль: сортировка не вправе прятать ПОТЕРЮ кандидата."""

    def test_a_cut_that_loses_a_candidates_only_description_is_still_refused(self):
        with TemporaryDirectory() as tmp:
            # описание ОДНО (повтора нет) ⇒ снятие первой строки стирает ``b-cand``
            data = build(Path(tmp), scene_entries(redescribe_on_day=None), "single")
            verdict = retention.measure(data, CUT_ROWS, NOW)
            self.assertTrue(verdict["measured"], verdict)
            self.assertFalse(verdict["safe"],
                             "кандидат потерял единственное описание, а гейт разрешил "
                             "резать — сортировка спрятала потерю")
            self.assertTrue(verdict["differs"], verdict)

    def test_the_lost_candidate_is_named_by_the_set_itself(self):
        """Потеря видна и прямо на множестве — не только через ответ вида."""
        with TemporaryDirectory() as tmp:
            full = build(Path(tmp), scene_entries(redescribe_on_day=None), "single")
            cut = cut_prefix(full, Path(tmp), CUT_ROWS, "single_cut")
            before = set(registry.all_candidate_ids(ledger_for(full)))
            after = set(registry.all_candidate_ids(ledger_for(cut)))
            self.assertEqual(before - after, {CANDIDATES[0]})


class TheOrderClaimIsNotProseOnly(unittest.TestCase):
    """Утверждение о порядке обязано держаться КОДОМ, а не только абзацем в docstring."""

    def test_no_reader_of_all_candidate_ids_re_sorts_or_re_orders_the_list(self):
        """Ни один читатель не вправе вернуть порядку зависимость от префикса.

        Проверяется ровно одно: функция отдаёт отсортированный список (``sorted``), и это
        видно в её собственном теле, а не в соседнем документе. AST, не подстрока: текст
        «sorted» в комментарии притязанием не является.
        """
        import ast
        import inspect

        source = inspect.getsource(registry.all_candidate_ids)
        tree = ast.parse(source.strip())
        returns = [node for node in ast.walk(tree) if isinstance(node, ast.Return)]
        self.assertEqual(len(returns), 1, "у функции стало больше одного выхода — "
                                          "притязание о порядке надо перемерить")
        value = returns[0].value
        if not isinstance(value, ast.Call):
            self.fail(f"выход функции — не вызов: {ast.dump(returns[0])}")
        self.assertEqual(getattr(value.func, "id", None), "sorted",
                         "возвращается не отсортированный список — порядок снова "
                         "зависит от порядка обхода ленты")


def scene_with_decisions_today() -> List[dict]:
    """Та же сцена плюс решение по каждому кандидату в ПОСЛЕДНИЕ сутки.

    Нужна затем, что ``read._sherlock_block`` кладёт в ``decisions_today`` только решения
    с датой прогона, а дата прогона берётся из последней строки ``run`` ленты. Без свежих
    решений список пуст, и сцена молчала бы о предмете.
    """
    entries = scene_entries()
    last = ANCHOR + dt.timedelta(days=SPAN_DAYS - 1, hours=1)
    for index, cid in enumerate(CANDIDATES):
        entries.append(_decision(cid, 2, last + dt.timedelta(minutes=index)))
    return entries


def first_decision_appearance_order(data: Path) -> list:
    """Порядок ПЕРВОГО появления кандидата среди строк ``admission_decision``.

    Это в точности порядок вставки словаря ``latest_by_candidate`` в
    ``read._sherlock_block`` ДО ADR-799. Прибор чувствительности, не альтернатива.
    """
    seen: list = []
    for entry in ledger_for(Path(data)).read_all():
        if entry.get("kind") != "admission_decision":
            continue
        cid = (entry.get("payload") or {}).get("candidate_id")
        if cid and cid not in seen:
            seen.append(cid)
    return seen


#: Сколько ведущих строк снимает сцена решений: все строки дня 0 у ``b-cand`` (снимок,
#: свод, решение) — иначе первое появление кандидата среди РЕШЕНИЙ не переедет.
CUT_ROWS_DECISIONS = 3


class TheSherlockDecisionListIsOrderedByTheSetToo(unittest.TestCase):
    """Второй носитель того же класса, найденный ЗАМЕРОМ, а не чтением кода.

    Цикл #922: после сортировки ``all_candidate_ids`` наибольшее безопасное отрезание
    живой ленты сдвинулось **0 → 1 251 из 25 601**, и отказ на 1 252-й записи держал
    ровно этот список: 234 разошедшихся листа, ВСЕ внутри
    ``latest.sherlock.decisions_today[*]``, при неизменной длине и неизменном составе
    решений. ``latest_by_candidate`` наполняется обходом ленты, поэтому его порядок
    вставки был порядком ленты.
    """

    def _answers(self, data: Path) -> dict:
        from spa_core.research_factory import read as read_mod
        return read_mod.latest(Path(data))

    def test_decisions_today_is_ordered_by_candidate_id_and_survives_the_cut(self):
        with TemporaryDirectory() as tmp:
            full = build(Path(tmp), scene_with_decisions_today(), "full")
            cut = cut_prefix(full, Path(tmp), CUT_ROWS_DECISIONS, "cut")

            before = self._answers(full)["sherlock"]["decisions_today"]
            after = self._answers(cut)["sherlock"]["decisions_today"]
            ids_before = [row["candidate_id"] for row in before]
            ids_after = [row["candidate_id"] for row in after]

            self.assertEqual(ids_before, sorted(CANDIDATES),
                             "список решений строится не по множеству кандидатов")
            self.assertEqual(ids_before, ids_after,
                             "отрезание переставило список решений — ADR-799 не доехал "
                             "до второго носителя")
            self.assertEqual(before, after, "решения разошлись не только порядком")

            # Контроль: сцена ДЕЙСТВИТЕЛЬНО переставляет порядок ленты — иначе равенство
            # выше ничего не проверяет.
            was_before = first_decision_appearance_order(full)
            was_after = first_decision_appearance_order(cut)
            self.assertEqual(was_before, list(CANDIDATES), "сцена собралась не тем порядком")
            self.assertNotEqual(was_before, was_after,
                                "префикс не переставил порядок появления решений — сцена "
                                "не проверяет предмет")
            self.assertEqual(set(was_before), set(was_after),
                             "решение ПОТЕРЯНО, а не передвинуто — это другой вопрос")

    def test_the_whole_declared_answer_is_identical_after_that_cut(self):
        """Не только список: ПОЛНЫЙ ответ обоих объявленных видов обязан совпасть.

        Это то же утверждение, которое даёт разрешение резать, — поэтому проверяется той
        же мерой (``retention.canonical``), а не глазами по одному полю.
        """
        with TemporaryDirectory() as tmp:
            data = build(Path(tmp), scene_with_decisions_today(), "scene")
            verdict = retention.measure(data, CUT_ROWS_DECISIONS, NOW)
            self.assertTrue(verdict["measured"], verdict)
            self.assertTrue(verdict["safe"],
                            f"отрезание отказано: {verdict.get('differs')}")
            self.assertEqual(verdict["shape"], "canonical")


class TheSceneUsesTheRealContract(unittest.TestCase):
    """Сцена обязана говорить на языке контракта, иначе она проверяет свою выдумку."""

    def test_every_kind_of_the_scene_is_named_by_a_declaration(self):
        """Ни одного выдуманного вида записи.

        Перечней видов в репозитории ДВА, и это замер, а не предпочтение: ``LEDGER_KINDS``
        описывает первую редакцию ленты, а ``evidence_bundle``/``admission_decision``
        объявлены рядом — у прибора срока хранения (``retention.DIAGNOSED_KINDS``). Тест
        сверяется с ОБОИМИ и своей копии перечня не держит.
        """
        declared = set(contract.LEDGER_KINDS) | set(retention.DIAGNOSED_KINDS)
        kinds = {entry["kind"] for entry in scene_entries()}
        self.assertIn("candidate_snapshot", kinds)
        self.assertTrue(kinds <= declared,
                        f"сцена несёт вид, которого не объявил никто: "
                        f"{sorted(kinds - declared)}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
