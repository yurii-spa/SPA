"""Сторож прибора «перепись входов журнала решений» (заказ CIO #539).

Каждый тест здесь — положительный контроль на РЕАЛЬНУЮ ошибку, а не украшение:

* ошибку ПЕРВОЙ РЕДАКЦИИ САМОГО ПРИБОРА (цикл #540): «вердикт потребителя
  изменился» было объявлено регрессией у четверых, а поимённый разбор показал
  рост ПОКРЫТИЯ. Тесты `coverage_grew` / `moved_without_coverage` /
  `no_coverage_counter_is_unmeasured` держат именно это различие;
* класс «не измерено, выданное за ответ» во всех трёх его направлениях —
  проверка ЗЕЛЕНЕЕТ, ИСЧЕЗАЕТ или уверенно СООБЩАЕТ дефект, которого нет;
* приём «структурный признак ≠ провенанс»: причина отсечения обязана быть
  названа МУТАЦИЕЙ, и у самой мутации обязан быть отрицательный контроль
  (`map_only`), иначе вторая дверь останется незамеченной.

Литеральных дат здесь нет намеренно, и это не косметика: субъект НЕ ИМЕЕТ
понятия свежести (ни окна, ни TTL, ни возраста), поэтому даты в фикстурах служат
только различимыми метками порядка и берутся относительно — календарь не может
сдвинуть ни один вердикт ниже.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring import decision_journal_coverage as djc


def _day(i: int) -> str:
    """Различимая метка дня. Значение не участвует ни в одном сравнении свежести."""
    return (date.today() - timedelta(days=30 - i)).isoformat()


# FROZEN-DATE-OK: injected-clock — якорь NOW передаётся субъекту аргументом
# `djc.measure(..., now=NOW)` / `djc.run(..., now=...)`, других обращений к часам
# у субъекта нет. Претензия здесь даже сильнее обычной: у прибора ВООБЩЕ НЕТ
# понятия свежести — ни окна, ни TTL, ни возраста, — и `now` служит только
# штампом `generated_at`. Сдвиг календаря не может изменить ни один вердикт
# ниже; метки дней в фикстурах берутся относительно (`_day`), а не литералом.
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _rec(i: int, *, current: dict, target: dict, evidenced: dict,
         unevidenced=()) -> dict:
    return {
        "cycle_date": _day(i),
        "generated_at": f"{_day(i)}T00:00:00+00:00",
        "current_positions": dict(current),
        "target_positions": dict(target),
        "apy_evidenced_pct": dict(evidenced),
        "apy_unevidenced": list(unevidenced),
        "capital_usd": 100000.0,
    }


class SplitGap(unittest.TestCase):
    """Щель «ранжировано → записано» обязана раскладываться ПО ПРИЧИНАМ."""

    def test_funding_and_evidence_are_counted_separately(self):
        gap = djc.split_gap(ranked_live={"a", "b", "c", "d"},
                            universe={"a", "b"}, written={"a"})
        self.assertEqual(gap["dropped_by_funding"], ["c", "d"])
        self.assertEqual(gap["dropped_by_evidence"], ["b"])
        self.assertEqual(gap["written_frac_of_ranked_live"], 0.25)

    def test_evidence_can_bind_alone(self):
        """Сцена нарушает ТОЛЬКО своё ограничение: книга полна, а эвиденса нет."""
        gap = djc.split_gap(ranked_live={"a", "b"}, universe={"a", "b"},
                            written={"a"})
        self.assertEqual(gap["dropped_by_funding"], [])
        self.assertEqual(gap["dropped_by_evidence"], ["b"])

    def test_empty_ranked_set_does_not_fabricate_a_ratio(self):
        gap = djc.split_gap(ranked_live=set(), universe=set(), written=set())
        self.assertIsNone(gap["written_frac_of_ranked_live"])


class NeverSeen(unittest.TestCase):
    """Инв. #16 — форма ответа расширена намеренно (ADR-344): `never_seen` теперь
    возвращает ПАРУ (ключи, молчавших строк). Прежняя проверка ключей цела дословно;
    добавлено второе число, без которого «не встречался ни разу» на журнале старой
    схемы верно ПО ПОСТРОЕНИЮ и неотличимо от находки о ключах (инвариант #17)."""

    def test_a_key_absent_from_every_day_is_named(self):
        rows = [_rec(1, current={"a": 1}, target={"a": 1}, evidenced={"a": 3.0}),
                _rec(2, current={"a": 1}, target={"b": 1},
                     evidenced={"a": 3.0, "b": 4.0})]
        self.assertEqual(djc.never_seen(rows, {"a", "b", "zz"}), (["zz"], 0))

    def test_a_key_seen_once_is_not_named(self):
        rows = [_rec(1, current={"a": 1}, target={}, evidenced={"a": 3.0})]
        self.assertEqual(djc.never_seen(rows, {"a"}), ([], 0))

    def test_a_row_without_the_field_is_counted_as_silent_not_as_evidence(self):
        """Строка старой схемы не свидетельствует — и это НАЗЫВАЕТСЯ числом."""
        rows = [_rec(1, current={"a": 1}, target={"a": 1}, evidenced={"a": 3.0})]
        del rows[0]["apy_evidenced_pct"]
        keys, silent = djc.never_seen(rows, {"a"})
        self.assertEqual((keys, silent), (["a"], 1),
                         "молчание строки записано в свидетельство против ключа")

    def test_an_empty_map_is_evidence_and_is_not_silence(self):
        """Пустая карта — ОТВЕТ писателя («сегодня наблюдённых нет»), а не пробел."""
        rows = [_rec(1, current={"a": 1}, target={"a": 1}, evidenced={})]
        self.assertEqual(djc.never_seen(rows, {"a"}), (["a"], 0))


class CriterionProbe(unittest.TestCase):
    """Население записи называется МУТАЦИЕЙ, и у мутации есть контроль.

    **Инвариант #16 — изменение намеренное, и вот основание.** До ADR-309
    писатель брал ``current ∪ target``, и здесь стояли три теста в обратную
    сторону: ``funded_set`` был НОРМОЙ, а «ключ попал в запись одной картой» —
    падением контроля. ADR-309 (ответ владельца 2026-09-10, Вариант Б) сделал
    карту ставок дверью ПО ЗАМЫСЛУ. Оставить прежние ожидания значило бы
    получить сторожа, который краснеет на верной доставке каждый цикл, —
    ровно тот класс, ради которого правило и написано.

    Утверждения не ослаблены: их столько же, каждое проверяется положительным
    контролем (узкий писатель обязан ронять новую пробу), и добавлена четвёртая
    проба на границу расширения (``priced_live``), которой раньше не было
    вовсе. Разбор — в ADR-309 и `docs/journal/2026-W37.md`.
    """

    BASE = dict(
        apy_pct={"held": 3.0, "tgt": 4.0, "unfunded": 9.0},
        apy_sources={"held": "live", "tgt": "live", "unfunded": "live"},
        current_positions={"held": 50000.0},
        target_positions={"tgt": 50000.0},
        capital_usd=100000.0,
    )

    def test_real_writer_says_the_population_is_the_full_live_set(self):
        out = djc.probe_criterion(unfunded_live="unfunded", funded_live="held",
                                  **self.BASE)
        self.assertEqual(out["verdict"], "full_live_set")
        self.assertEqual(out["probes"]["funding"]["verdict"], "does_not_bind")
        self.assertEqual(out["probes"]["map_widens"]["verdict"], "widens")
        self.assertEqual(out["probes"]["unpriced_live_stays_out"]["verdict"],
                         "stays_out")

    def test_evidence_binds_inside_the_book_and_does_not_go_silent(self):
        """Снятый провенанс обязан уводить ключ в apy_unevidenced, а не в никуда."""
        out = djc.probe_criterion(unfunded_live="unfunded", funded_live="held",
                                  **self.BASE)
        self.assertEqual(out["probes"]["evidence"]["verdict"], "binds_inside_book")

    def test_a_narrow_writer_is_caught_as_a_finding_not_as_normal(self):
        """Положительный контроль: писатель ДО ADR-309 обязан ронять пробу.

        Это тот же самый писатель, который раньше давал ``funded_set``. Теперь
        он даёт ``still_funded_set`` — находку, а не норму. Отсюда видно, что
        ожидание ПЕРЕВЁРНУТО, а не снято.
        """
        def book_only_writer(doc, *, apy_pct, apy_sources, current_positions,
                             target_positions, capital_usd, book_id=None):
            universe = sorted(set(current_positions) | set(target_positions))
            ev = {p for p, s in apy_sources.items() if s == "live"}
            return {
                "apy_evidenced_pct": {p: apy_pct[p] for p in universe
                                      if p in ev and apy_pct.get(p) is not None},
                "apy_unevidenced": sorted(p for p in universe if p not in ev),
            }

        out = djc.probe_criterion(unfunded_live="unfunded", funded_live="held",
                                  build=book_only_writer, **self.BASE)
        self.assertEqual(out["probes"]["map_widens"]["verdict"], "silent")
        self.assertEqual(out["probes"]["funding"]["verdict"], "binds")
        self.assertEqual(out["verdict"], "still_funded_set")

    def test_a_writer_admitting_a_rate_that_does_not_exist_is_caught(self):
        """Контроль на границу расширения: ключ БЕЗ числа в население не входит."""
        def unpriced_admitting_writer(doc, *, apy_pct, apy_sources,
                                      current_positions, target_positions,
                                      capital_usd, book_id=None):
            ev = {p for p, s in apy_sources.items() if s == "live"}
            return {"apy_evidenced_pct": {p: apy_pct.get(p) for p in ev},
                    "apy_unevidenced": []}

        out = djc.probe_criterion(unfunded_live="unfunded", funded_live="held",
                                  build=unpriced_admitting_writer, **self.BASE)
        self.assertEqual(out["probes"]["unpriced_live_stays_out"]["verdict"],
                         "UNPRICED_ADMITTED")
        self.assertEqual(out["verdict"], "unpriced_admitted")

    def test_no_probe_material_is_unmeasured_not_a_conclusion(self):
        out = djc.probe_criterion(unfunded_live=None, funded_live=None, **self.BASE)
        self.assertEqual(out["verdict"], "unmeasured")
        for name in ("funding", "evidence"):
            self.assertEqual(out["probes"][name]["verdict"], "unmeasured")
            self.assertTrue(out["probes"][name]["note"])

    def test_a_taken_probe_name_is_unmeasured_not_a_verdict(self):
        """Служебное имя пробы занято реальным ключом ⇒ мутация неотличима от факта."""
        base = dict(self.BASE)
        base["current_positions"] = dict(base["current_positions"])
        base["current_positions"]["__probe_map_only__"] = 1.0
        out = djc.probe_criterion(unfunded_live="unfunded", funded_live="held",
                                  **base)
        self.assertEqual(out["probes"]["map_widens"]["verdict"], "unmeasured")
        self.assertEqual(out["probes"]["unpriced_live_stays_out"]["verdict"],
                         "unmeasured")
        self.assertEqual(out["verdict"], "unmeasured")


class RecordUniverse(unittest.TestCase):
    """Население строки читается С НЕЁ САМОЙ, а не выводится копией правила.

    До ADR-309 здесь стояла вторая копия правила писателя
    (``current_positions ∪ target_positions``). Пока писатель брал книгу, копия
    совпадала с оригиналом и молчала; после расширения писателя она занижала бы
    население каждой новой строки и записывала разницу в `dropped_by_funding` —
    то есть докладывала бы отсечение, которого больше нет.
    """

    def test_the_population_is_what_the_record_itself_names(self):
        rec = {"apy_evidenced_pct": {"a": 1.0, "b": 2.0},
               "apy_unevidenced": ["c"],
               "current_positions": {"a": 10.0}, "target_positions": {}}
        self.assertEqual(djc.record_universe(rec), {"a", "b", "c"})

    def test_a_wide_record_is_not_narrowed_back_to_the_book(self):
        """Положительный контроль на саму правку: копия правила покраснеет."""
        rec = {"apy_evidenced_pct": {"a": 1.0, "outside": 9.0},
               "apy_unevidenced": [],
               "current_positions": {"a": 10.0}, "target_positions": {}}
        self.assertIn("outside", djc.record_universe(rec))

    def test_a_pre_ADR_309_line_still_names_its_own_book(self):
        """Строка старого писателя читается тем же правилом и не ломается."""
        rec = {"apy_evidenced_pct": {"held": 3.0}, "apy_unevidenced": ["tgt"],
               "current_positions": {"held": 10.0}, "target_positions": {"tgt": 5.0}}
        self.assertEqual(djc.record_universe(rec), {"held", "tgt"})

    def test_a_record_that_names_an_empty_population_is_an_answer(self):
        """«Писатель сказал: пусто» ≠ «полей нет» — второе падает на позиции."""
        named_empty = {"apy_evidenced_pct": {}, "apy_unevidenced": [],
                       "current_positions": {"a": 1.0}, "target_positions": {}}
        self.assertEqual(djc.record_universe(named_empty), set())
        old_schema = {"current_positions": {"a": 1.0}, "target_positions": {}}
        self.assertEqual(djc.record_universe(old_schema), {"a"})


class WidenJournal(unittest.TestCase):
    def test_widening_never_overwrites_a_recorded_rate(self):
        """Расширение — проба, и оно НЕ смеет подменять то, что писатель записал."""
        rows = [_rec(1, current={"a": 1}, target={}, evidenced={"a": 3.0})]
        wide = djc.widen_journal(rows, {"a": 99.0, "b": 7.0}, {"a", "b"})
        self.assertEqual(wide[0]["apy_evidenced_pct"]["a"], 3.0)
        self.assertEqual(wide[0]["apy_evidenced_pct"]["b"], 7.0)

    def test_the_source_rows_are_not_mutated(self):
        rows = [_rec(1, current={"a": 1}, target={}, evidenced={"a": 3.0})]
        djc.widen_journal(rows, {"b": 7.0}, {"b"})
        self.assertEqual(sorted(rows[0]["apy_evidenced_pct"]), ["a"])


class ReaderDirection(unittest.TestCase):
    """Ошибка ПЕРВОЙ РЕДАКЦИИ прибора: «изменился» ≠ «сломался».

    Первая редакция объявила четырёх потребителей сломанными по одному факту
    смены вердикта. Поимённый разбор показал, что у всех выросло ПОКРЫТИЕ —
    они не ломаются от полноты, а платят за её отсутствие. Различие живёт здесь.
    """

    def _probe(self, monkey, sandbox):
        readers = ({"module": "m", "probe": "p"},)
        orig = djc._reader_probe
        djc._reader_probe = monkey
        try:
            return djc.probe_readers([{"cycle_date": _day(1)}],
                                     [{"cycle_date": _day(1)}], sandbox,
                                     readers=readers)[0]
        finally:
            djc._reader_probe = orig

    def setUp(self):
        self.sbx = Path(tempfile.mkdtemp(prefix="spa_djc_test_"))
        self.addCleanup(shutil.rmtree, self.sbx, ignore_errors=True)

    def test_coverage_growth_is_paying_the_ceiling_not_a_regression(self):
        calls = iter([(5, {"v": 1}), (9, {"v": 2})])
        row = self._probe(lambda spec, root: next(calls), self.sbx)
        self.assertEqual(row["verdict"], djc.VERDICT_PAYS)
        self.assertEqual((row["coverage_base"], row["coverage_wide"]), (5, 9))

    def test_moving_without_coverage_growth_is_the_real_regression(self):
        calls = iter([(5, {"v": 1}), (5, {"v": 2})])
        row = self._probe(lambda spec, root: next(calls), self.sbx)
        self.assertEqual(row["verdict"], djc.VERDICT_MOVED)
        self.assertEqual(row["moved_keys"], ["v"])

    def test_shrinking_coverage_is_also_a_regression(self):
        calls = iter([(9, {"v": 1}), (5, {"v": 2})])
        row = self._probe(lambda spec, root: next(calls), self.sbx)
        self.assertEqual(row["verdict"], djc.VERDICT_MOVED)

    def test_no_coverage_counter_is_unmeasured_not_an_accusation(self):
        """Третье направление класса: уверенно сообщить дефект, которого нет.

        Потребитель без собственного счётчика покрытия сдвинул ответ. Назвать
        это регрессией значило бы ИЗГОТОВИТЬ находку из неизмеренного — тише
        красного теста и потому опаснее.
        """
        calls = iter([(None, {"v": 1}), (None, {"v": 2})])
        row = self._probe(lambda spec, root: next(calls), self.sbx)
        self.assertEqual(row["verdict"], djc.VERDICT_UNMEASURED)
        self.assertIn("покрытия", row["note"])

    def test_identical_answer_is_insensitive(self):
        calls = iter([(5, {"v": 1}), (5, {"v": 1})])
        row = self._probe(lambda spec, root: next(calls), self.sbx)
        self.assertEqual(row["verdict"], djc.VERDICT_INSENSITIVE)

    def test_a_reader_that_raises_is_unmeasured_with_a_named_reason(self):
        def boom(spec, root):
            raise RuntimeError("нет входа")
        row = self._probe(boom, self.sbx)
        self.assertEqual(row["verdict"], djc.VERDICT_UNMEASURED)
        self.assertIn("нет входа", row["note"])


class OwnCoverage(unittest.TestCase):
    def test_named_counters_are_read_from_the_reader_itself(self):
        self.assertEqual(djc._own_coverage({"population": {"scoreable": 12}}), 12)
        self.assertEqual(
            djc._own_coverage({"population": {"common_scored_days": 3}}), 3)

    def test_explainability_coverage_excludes_facts_with_no_value(self):
        doc = {"facts_total": 5,
               "books": [{"facts": [{"outcome": "ABSENT"}, {"outcome": "SPOKEN"}]}]}
        self.assertEqual(djc._own_coverage(doc), 4)

    def test_an_unnamed_counter_is_none_not_zero(self):
        """Ноль означал бы «покрытия нет», а верно «покрытие не измерено»."""
        self.assertIsNone(djc._own_coverage({"whatever": 7}))


class ReaderPopulationRatchet(unittest.TestCase):
    """Население потребителей закрыто ЗАМЕРОМ дерева, а не памятью автора.

    Новый модуль, начавший читать ``apy_evidenced_pct`` и не попавший в
    ``READERS``, означает потребителя, чья цена НЕ измеряется, — и молчал бы
    именно тот прибор, который написан против молчания.
    """

    KEY = "apy_evidenced_pct"

    #: Единственное исключение — САМ ПИСАТЕЛЬ поля. Он его не читает, он его
    #: производит, и мерить у него «цену расширения» было бы вопросом не к тому.
    #: Исключение названо поимённо и ДОКАЗЫВАЕТСЯ отдельным тестом ниже: иначе
    #: этот список стал бы обычной глушилкой, ради которой храповик и написан.
    WRITER = "spa_core.paper_trading.allocation_rationale"

    #: Второе исключение, добавлено циклом #541 (ADR-295) — и это НЕ ослабление
    #: храповика, а применение его же правила. Совпадение по имени ключа роли не
    #: различает: «читает `apy_evidenced_pct`» одинаково верно и про
    #: ПОТРЕБИТЕЛЯ (его ответ платит за потолок журнала), и про ПЕРТУРБАТОРА,
    #: который сам этот ключ в журнал и вписывает, чтобы построить контроль.
    #: Спрашивать у второго «во что тебе обойдётся расширение» — вопрос не к
    #: тому: расширение и есть его предмет, а прогон его внутри `probe_readers`
    #: вложил бы замер сам в себя (17.7 с × 2 в дневном мосте, замер #541).
    #: Исключение названо ПОИМЁННО и, как и WRITER выше, ДОКАЗЫВАЕТСЯ отдельным
    #: тестом — поведением, а не списком: перестань модуль пертурбировать ключ,
    #: и доказательство покраснеет.
    PERTURBER = "spa_core.monitoring.decision_record_verdict_sensitivity"

    #: Третье исключение, добавлено циклом #548 (ADR-309) — по тому же
    #: основанию, что PERTURBER, и с тем же доказательством поведением.
    #: `journal_population_backfill` не ПЛАТИТ за потолок журнала, он его
    #: закрывает: читает `apy_evidenced_pct` ровно затем, чтобы НЕ дописать
    #: поверх живого значения, и сам пишет соседний ключ. Спрашивать у него
    #: «во что тебе обойдётся расширение» — вопрос не к тому: расширение и
    #: есть его предмет.
    #:
    #: **Это не гашение красного теста, и обстоятельство тут сильнее обычного.**
    #: Храповик стоял красным четырьмя именами и был ПОЧИНЕН параллельной
    #: сессией в тот же день (ADR-308, коммит 80890d18a: четыре потребителя
    #: внесены в `READERS`). То есть на момент цикла #548 он ЗЕЛЁНЫЙ, и
    #: единственное имя, способное его покраснить, — то, которое цикл #548 сам
    #: и принёс. Внести свой модуль в `READERS` было бы неверно: `probe_readers`
    #: спрашивает у потребителя «во что тебе обойдётся расширение», а
    #: расширение — предмет этого модуля, и прогон вложил бы замер сам в себя
    #: (то же основание, что у PERTURBER).
    BACKFILLER = "spa_core.monitoring.journal_population_backfill"

    def test_the_backfiller_exclusion_really_backfills(self):
        """Исключение обязано БЫТЬ заполнителем, а не просто числиться им.

        Тот же порядок, что у двух исключений выше: имя в списке ничего не
        значит, пока не показано поведением. Здесь — что модуль СТРОИТ план
        дописывания и кладёт значения в СВОЙ ключ, оставляя `apy_evidenced_pct`
        нетронутым. Перестань он это делать — доказательство покраснеет.
        """
        from spa_core.monitoring import journal_population_backfill as jpb

        line = {"cycle_date": "2026-08-12", "apy_evidenced_pct": {"held": 3.0},
                "apy_unevidenced": []}
        out = jpb.plan_for_pairs([line], {"outside": {"2026-08-12": 7.5}},
                                 [{"forward_date": "2026-08-12",
                                   "protocol": "outside"}])
        self.assertEqual(out["plan"], {"2026-08-12": {"outside": 7.5}})
        fresh = jpb.corrected_lines([line], out["plan"])
        self.assertEqual(fresh[0]["apy_evidenced_pct"], {"held": 3.0})
        self.assertEqual(fresh[0][jpb.KEY_VALUES], {"outside": 7.5})

    def _production_modules_touching_the_key(self):
        root = Path(__file__).resolve().parents[2]
        found = set()
        for path in root.rglob("*.py"):
            rel = path.relative_to(root)
            if rel.parts[0] != "spa_core" or "tests" in rel.parts:
                continue
            if rel.name == "decision_journal_coverage.py":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                continue
            if self.KEY in text:
                found.add(".".join(rel.with_suffix("").parts))
        return found

    def test_the_only_exclusion_really_is_the_writer(self):
        """Исключение обязано БЫТЬ писателем, а не просто числиться им."""
        from spa_core.paper_trading import allocation_rationale

        self.assertTrue(hasattr(allocation_rationale, "build_history_record"))
        self.assertTrue(hasattr(allocation_rationale, "append_rationale_history"))

    def test_the_perturber_exclusion_really_perturbs(self):
        """Исключение обязано БЫТЬ пертурбатором, а не просто числиться им.

        Тот же порядок, что у ``test_the_only_exclusion_really_is_the_writer``:
        имя в списке ничего не значит, пока не показано поведением. Здесь —
        что модуль СТРОИТ журнал с изменённым ``apy_evidenced_pct`` (а не
        читает готовый), и потому вопрос «во что тебе обойдётся расширение»
        к нему не обращён.
        """
        import tempfile as _tf

        from spa_core.monitoring import decision_record_verdict_sensitivity as drvs

        self.assertTrue(hasattr(drvs, "capability_control"))
        rates = {"a": 3.0, "b": 3.0}

        def rec(i, cur, tgt, cost, turn):
            return {"schema": "shadow-hist-v2",
                    "cycle_date": (NOW + timedelta(days=i)).date().isoformat(),
                    "verdict": "HOLD", "current_positions": cur,
                    "target_positions": tgt, "apy_evidenced_pct": dict(rates),
                    "capital_usd": 100_000.0, "cost_usd": cost,
                    "turnover_usd": turn, "legs": [], "gates": {}}

        rows = [rec(0, {"a": 50_000.0}, {"b": 50_000.0}, 10.0, 50_000.0)]
        rows += [rec(i, {"b": 50_000.0}, {"b": 50_000.0}, 0.0, 0.0)
                 for i in range(1, 9)]
        with _tf.TemporaryDirectory() as td:
            sandbox = Path(td)
            drvs._write_journal(rows, sandbox / drvs.HISTORY_FILENAME)
            base = drvs._replay(sandbox, rows, "base")
            out = drvs.capability_control(sandbox, rows, base)
            # Пертурбация состоялась: контроль перевернул вердикт, а сделать это
            # он мог ТОЛЬКО вписав в журнал другие ставки по этому же ключу.
            self.assertTrue(out["fired"], out)
            self.assertEqual(out["outcome_after"], "miss")

    def test_the_population_is_not_empty(self):
        """Пустой замер зеленил бы храповик, ничего не измерив."""
        self.assertGreater(len(self._production_modules_touching_the_key()), 1)

    def test_every_production_reader_is_in_the_population(self):
        declared = {r["module"] for r in djc.READERS} | {self.WRITER,
                                                         self.PERTURBER,
                                                         self.BACKFILLER}
        missing = sorted(self._production_modules_touching_the_key() - declared)
        self.assertEqual(
            missing, [],
            f"читают {self.KEY}, но не измеряются прибором: {missing}")


class Measure(unittest.TestCase):
    """Третий исход обязателен на КАЖДОМ входе — молчание запрещено."""

    def setUp(self):
        self.ddir = Path(tempfile.mkdtemp(prefix="spa_djc_measure_"))
        self.addCleanup(shutil.rmtree, self.ddir, ignore_errors=True)

    def _journal(self, rows):
        (self.ddir / djc.HISTORY_FILENAME).write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    def test_missing_journal_is_unmeasured_not_a_clean_pass(self):
        doc = djc.measure(self.ddir, now=NOW)
        self.assertEqual(doc["status"], djc.STATUS_UNMEASURED)
        self.assertTrue(any("[НЕ ИЗМЕРЕНО]" in f for f in doc["findings"]))
        self.assertNotIn("gap", doc)

    def test_an_empty_ranked_set_is_a_finding_about_the_producer(self):
        self._journal([_rec(1, current={"a": 1}, target={}, evidenced={"a": 3.0})])
        doc = djc.measure(self.ddir, now=NOW,
                          ranked_producer_factory=lambda sbx: lambda: ({}, {}))
        self.assertEqual(doc["status"], djc.STATUS_UNMEASURED)
        self.assertTrue(any("ПРОИЗВОДИТЕЛЕ" in f for f in doc["findings"]))

    def test_a_failing_producer_is_unmeasured_with_a_named_reason(self):
        self._journal([_rec(1, current={"a": 1}, target={}, evidenced={"a": 3.0})])

        def boom(_sbx):
            def produce():
                raise RuntimeError("снимок пуст")
            return produce

        doc = djc.measure(self.ddir, now=NOW, ranked_producer_factory=boom)
        self.assertEqual(doc["status"], djc.STATUS_UNMEASURED)
        self.assertTrue(any("снимок пуст" in f for f in doc["findings"]))

    def test_a_nondeterministic_producer_stops_the_measurement(self):
        """Контроль на сам стенд: недетерминизм обесценил бы каждое число ниже."""
        self._journal([_rec(1, current={"a": 1}, target={}, evidenced={"a": 3.0})])
        seq = iter([({"a": 3.0}, {"a": "live"}), ({"a": 9.9}, {"a": "live"})])

        doc = djc.measure(self.ddir, now=NOW,
                          ranked_producer_factory=lambda sbx: lambda: next(seq))
        self.assertEqual(doc["determinism"], "DIVERGED")
        self.assertEqual(doc["status"], djc.STATUS_CRITICAL)
        self.assertNotIn("gap", doc)

    def test_the_ceiling_is_measured_end_to_end(self):
        rows = [_rec(i, current={"held": 50000.0}, target={"tgt": 50000.0},
                     evidenced={"held": 3.0, "tgt": 4.0}) for i in (1, 2)]
        self._journal(rows)
        ranked = {"held": 3.0, "tgt": 4.0, "far": 9.0, "away": 8.0}
        sources = {k: "live" for k in ranked}
        doc = djc.measure(
            self.ddir, now=NOW,
            ranked_producer_factory=lambda sbx: lambda: (dict(ranked), dict(sources)),
            readers=())
        self.assertEqual(doc["determinism"], "reproduced")
        self.assertEqual(doc["gap"]["ranked_live"], 4)
        self.assertEqual(doc["gap"]["written"], 2)
        self.assertEqual(doc["gap"]["dropped_by_funding"], ["away", "far"])
        self.assertEqual(doc["never_written"], ["away", "far"])
        # ADR-309: писатель, которого зовут пробы, теперь пишет весь живой набор
        # дня — а СТРОКИ этого журнала написаны узким писателем до правки.
        # Расхождение между `gap` (что в файле) и `criterion` (что писатель
        # делает сегодня) — не дефект замера, а само смешанное население, и
        # прибор обязан называть обе стороны, а не одну.
        self.assertEqual(doc["criterion"]["verdict"], "full_live_set")
        # пустое население потребителей — это НЕ измеренный ноль
        self.assertEqual(doc["status"], djc.STATUS_UNMEASURED)

    def test_a_regressing_reader_makes_the_whole_verdict_critical(self):
        rows = [_rec(i, current={"held": 50000.0}, target={"tgt": 50000.0},
                     evidenced={"held": 3.0, "tgt": 4.0}) for i in (1, 2)]
        self._journal(rows)
        ranked = {"held": 3.0, "tgt": 4.0, "far": 9.0}
        calls = iter([(5, {"v": 1}), (5, {"v": 2})])
        orig = djc._reader_probe
        djc._reader_probe = lambda spec, root: next(calls)
        try:
            doc = djc.measure(
                self.ddir, now=NOW,
                ranked_producer_factory=lambda sbx: lambda: (
                    dict(ranked), {k: "live" for k in ranked}),
                readers=({"module": "m", "probe": "p"},))
        finally:
            djc._reader_probe = orig
        self.assertEqual(doc["status"], djc.STATUS_CRITICAL)
        self.assertTrue(any(f.startswith("[CRITICAL]") for f in doc["findings"]))

    def test_readers_that_only_gain_coverage_do_not_make_it_critical_by_themselves(self):
        """Цена потолка — не поломка: одного роста покрытия мало для CRITICAL."""
        rows = [_rec(i, current={"held": 50000.0}, target={"tgt": 50000.0},
                     evidenced={"held": 3.0, "tgt": 4.0}) for i in (1, 2)]
        self._journal(rows)
        # доля записанного ВЫШЕ порога потолка, иначе CRITICAL придёт от щели
        ranked = {"held": 3.0, "tgt": 4.0, "far": 9.0}
        calls = iter([(5, {"v": 1}), (9, {"v": 2})])
        orig = djc._reader_probe
        djc._reader_probe = lambda spec, root: next(calls)
        try:
            doc = djc.measure(
                self.ddir, now=NOW,
                ranked_producer_factory=lambda sbx: lambda: (
                    dict(ranked), {"held": "live", "tgt": "live", "far": "live"}),
                readers=({"module": "m", "probe": "p"},))
        finally:
            djc._reader_probe = orig
        self.assertEqual([r["verdict"] for r in doc["readers"]], [djc.VERDICT_PAYS])
        self.assertFalse(any(f.startswith("[CRITICAL]") for f in doc["findings"]))


class AbsenceIsNamedNotZeroed(unittest.TestCase):
    """ADR-344 (инвариант #17): чего в строке НЕТ, то не становится нулём.

    Замер 11.09: в этом модуле было 10 мест класса «or-подстановка у писателя
    артефакта». Ниже — сцены ровно на те из них, где подстановка МЕНЯЛА вердикт.
    """

    def setUp(self):
        self.ddir = Path(tempfile.mkdtemp(prefix="spa_djc_absence_"))
        self.addCleanup(shutil.rmtree, self.ddir, ignore_errors=True)

    def _journal(self, rows):
        (self.ddir / djc.HISTORY_FILENAME).write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    def _ranked(self, keys):
        return lambda sbx: lambda: ({k: 5.0 for k in keys}, {k: "live" for k in keys})

    def test_a_last_row_without_the_field_makes_the_gap_unmeasured(self):
        """Ноль записанных сказал бы «писатель не записал НИЧЕГО» — а нет ПОЛЯ."""
        row = _rec(1, current={"a": 1}, target={"a": 1}, evidenced={"a": 3.0})
        del row["apy_evidenced_pct"]
        self._journal([row])
        doc = djc.measure(self.ddir, now=NOW, ranked_producer_factory=self._ranked(["a"]))
        self.assertEqual(doc["gap"].get("status"), "unmeasured")
        self.assertIn("apy_evidenced_pct", doc["gap"].get("reason", ""))
        self.assertTrue(any("[НЕ ИЗМЕРЕНО]" in f for f in doc["findings"]))
        self.assertNotIn("written_frac_of_ranked_live", doc["gap"])

    def test_an_empty_map_in_the_last_row_is_measured_zero_coverage(self):
        """Обратная сторона: пустая карта — ОТВЕТ, и щель обязана считаться."""
        self._journal([_rec(1, current={"a": 1}, target={"a": 1}, evidenced={})])
        doc = djc.measure(self.ddir, now=NOW, ranked_producer_factory=self._ranked(["a"]))
        self.assertNotEqual(doc["gap"].get("status"), "unmeasured")
        self.assertEqual(doc["gap"].get("written"), 0)

    def test_silent_rows_are_counted_beside_never_written(self):
        """Молчит СТАРАЯ строка (день 1), последняя — говорит: щель мерится, молчание считается."""
        silent = _rec(1, current={"a": 1}, target={"a": 1}, evidenced={"a": 3.0})
        del silent["apy_evidenced_pct"]
        row = _rec(2, current={"a": 1}, target={"a": 1}, evidenced={"a": 3.0})
        self._journal([silent, row])
        doc = djc.measure(self.ddir, now=NOW, ranked_producer_factory=self._ranked(["a"]))
        self.assertEqual(doc["never_written_rows_silent"], 1)

    def test_a_row_without_capital_names_the_substitution(self):
        """Капитал ноль вырождает каждую долю — подмена обязана быть НАЗВАНА."""
        from spa_core.paper_trading.engine import INITIAL_CAPITAL
        doc = {"findings": []}
        self.assertEqual(djc._capital_of({"capital_usd": 50_000.0}, doc), 50_000.0)
        self.assertEqual(doc["findings"], [])
        self.assertEqual(djc._capital_of({}, doc), float(INITIAL_CAPITAL))
        self.assertTrue(any("[НЕ ИЗМЕРЕНО]" in f and "капитал" in f
                            for f in doc["findings"]))

    def test_a_record_without_any_population_field_is_a_probe_failure(self):
        """Писатель обязан назвать население САМ: молчание — дефект, не пустая книга."""
        from spa_core.utils.errors import SPAError
        with self.assertRaises(SPAError) as got:
            djc.probe_criterion(apy_pct={"a": 5.0}, apy_sources={"a": "live"},
                                current_positions={"a": 1.0}, target_positions={"a": 1.0},
                                capital_usd=100_000.0,
                                unfunded_live=None, funded_live="a",
                                build=lambda doc, **kw: {"cycle_date": "2026-01-01"})
        self.assertEqual(got.exception.code, "PROBE_RECORD_WITHOUT_POPULATION")


class RunAdapter(unittest.TestCase):
    def test_unchecked_is_counted_separately_from_zero(self):
        root = Path(tempfile.mkdtemp(prefix="spa_djc_run_"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / "data").mkdir()
        doc = djc.run(root=str(root), write=False)
        self.assertEqual(doc["overall"], djc.STATUS_UNMEASURED)
        self.assertGreaterEqual(doc["counts"]["unchecked"], 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
