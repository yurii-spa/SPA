"""Положительные контроли пробы `owner_visibility_numbers_delivered` (ADR-489).

Критерий владельца — §49 приказа «Portfolio CIO»: «Owner видит current/optimal APY,
Yield Gap и recommendation». Замер #709 (ADR-488): журнал решений нёс все четыре
предмета своими полями, выдача слоя отображения оставляла ОДИН, три числа терялись
на последнем шаге. #710 их доставил — и проба обязана краснеть, если их уронят снова.

Проба без контроля в обе стороны — украшение (`.claude/rules/deployment.md`). Здесь
показано, что на ЦЕЛОМ контуре она зелёная, на КАЖДОМ порванном звене красная с
названным звеном, и что подстрокой она не проходит (ADR-333). Контур настоящий:
журнал решений → настоящий `build_books_brief` → настоящая перепись → ось чтения
поля настоящей поверхностью. Синтетические здесь только ДАННЫЕ и одноразовое дерево;
живое `data/` и живая поверхность не тронуты ни на байт.

# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — NOW передаётся в пробу параметром now=, а отметка
# `generated_at` каждой записи журнала выводится из того же NOW (см. `_record`), так
# что обе стороны сравнения возраста закреплены и тест бессмертен.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import owner_visibility_census as M
from spa_core.paper_trading import cio_brief

NOW = dt.datetime(2026, 9, 28, 6, 0, tzinfo=dt.timezone.utc)

#: Читающая поверхность владельца — форма, которую ось чтения признаёт чтением
#: поля: путь эндпоинта аргументом вызова + каждое поле взято через точку.
SURFACE = """---
// одноразовая поверхность владельца для контроля пробы
---
<script is:inline>
  async function tick(){
    var r = await jget('/api/live/books/brief');
    var br = (r.books||{}).conservative||{};
    show(br.current_apy_pp, br.optimal_apy_pp, br.yield_gap_pp, br.verdict);
  }
</script>
"""

#: Та же поверхность, но эндпоинт только УПОМЯНУТ (комментарий), не позван.
SURFACE_MENTION_ONLY = """---
// поверхность, которая про /api/live/books/brief только написала
---
<script is:inline>var x = 1;</script>
"""

#: Поверхность зовёт выдачу, но НИ ОДНОГО поля не читает — ровно состояние
#: `portfolio-summary.astro` до #710: прежние две оси зелены, числа не дошли.
SURFACE_NO_FIELDS = """---
// поверхность, которая зовёт выдачу и берёт из неё одну прозу
---
<script is:inline>
  async function tick(){
    var r = await jget('/api/live/books/brief');
    var br = (r.books||{}).conservative||{};
    show(br.why, br.why_now);
  }
</script>
"""


def _record(book: str, *, hours_ago: float = 1.0, **over) -> dict:
    """Запись журнала решений схемы `shadow-hist-v2`.

    Отметка времени выводится из NOW, а не литерал: возраст записи — часть
    вопроса пробы, и закреплять надо ОБЕ стороны сравнения.
    """
    rec = {
        "schema": "shadow-hist-v2",
        "book_id": book,
        "decision_id": f"adr060-shadow-{book}",
        "cycle_date": "2026-09-27",
        "generated_at": (NOW - dt.timedelta(hours=hours_ago)).isoformat(),
        "policy_version": "v1.1",
        "mode": "paper",
        "verdict": "HOLD",
        "book_apy_pp": 4.11137,
        "target_apy_pp": 3.691339,
        "gain_pp": -0.420031,
        "required_gain_pp": 0.5,
        "capital_usd": 100000.0,
        "current_positions": {"aave_v3": 40000.0},
        "target_positions": {"aave_v3": 40000.0},
        "legs": [],
        "reasons": ["gain_below_band"],
        "gates": {"gain_above_band": False},
        "warnings_count": 0,
    }
    rec.update(over)
    return rec


class _Contour:
    """Одноразовый контур: свой каталог данных + своё дерево с поверхностью."""

    def __init__(self, *, records=None, surface: str | None = SURFACE,
                 hours_ago: float = 1.0):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        for book in M.BOOKS:
            over = (records or {}).get(book, {})
            rec = _record(book, hours_ago=hours_ago, **over)
            name = ("allocation_rationale_history.jsonl" if book == "conservative"
                    else f"allocation_rationale_history_{book}.jsonl")
            (self.data / name).write_text(json.dumps(rec, ensure_ascii=False) + "\n",
                                         encoding="utf-8")
        pages = self.root / "landing" / "src" / "pages" / "admin"
        pages.mkdir(parents=True)
        if surface is not None:
            (pages / "surface.astro").write_text(surface, encoding="utf-8")

    def verdict(self):
        return ca._probe_owner_visibility_numbers_delivered(
            None, now=NOW, data_dir=str(self.data), repo_root=str(self.root))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False


class Registered(unittest.TestCase):
    def test_probe_is_registered_under_the_declared_name(self):
        """Имя объявлено карточкой ДО работы — реестр обязан его знать.

        До #710 карточка приказа несла `acceptance_probe:
        owner_visibility_numbers_delivered`, которого в реестре не было, и шаг
        0-офис честно печатал «измерять нечем»: критерий не был бы измерен
        НИКОГДА, а выглядело это как «нечем проверить сегодня».
        """
        self.assertIn("owner_visibility_numbers_delivered", ca.PROBES)
        self.assertIsNone(ca.validate_spec("owner_visibility_numbers_delivered"))


class WholeContourIsGreen(unittest.TestCase):
    def test_all_twelve_subjects_reach_the_owner(self):
        with _Contour() as c:
            verdict, detail = c.verdict()
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertIn("12 из 12", detail)


class EachBrokenLinkIsRed(unittest.TestCase):
    """Каждое звено рвётся отдельно, и звено НАЗЫВАЕТСЯ в пояснении."""

    def test_link_display_layer_drops_a_field(self):
        """Звено: выдача перестала нести поле — исходная поломка #709."""
        kept = tuple(pair for pair in cio_brief.OWNER_NUMBER_FIELDS
                     if pair[0] != "current_apy_pp")
        with _Contour() as c, mock.patch.object(
                cio_brief, "OWNER_NUMBER_FIELDS", kept):
            verdict, detail = c.verdict()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("НЕ доставлено", detail)

    def test_link_surface_stops_reading_the_field(self):
        """Звено: поле в выдаче есть, поверхность его не берёт.

        Ровно состояние `portfolio-summary.astro` до #710. Обе прежние оси
        переписи здесь ЗЕЛЕНЫ (выдача несёт поле, читатель у эндпоинта есть),
        и без третьей оси проба объявила бы критерий выполненным.
        """
        with _Contour(surface=SURFACE_NO_FIELDS) as c:
            verdict, detail = c.verdict()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("НЕ читает", detail)
        self.assertIn("current_apy_pp", detail)

    def test_link_surface_stops_calling_the_endpoint(self):
        """Звено: путь эндпоинта упомянут, но не позван."""
        with _Contour(surface=SURFACE_MENTION_ONLY) as c:
            verdict, detail = c.verdict()
        self.assertIn(verdict, (ca.NOT_SATISFIED, ca.UNMEASURED), detail)
        self.assertNotEqual(verdict, ca.SATISFIED, detail)

    def test_link_journal_does_not_record_the_subject(self):
        """Звено: журнал не несёт предмет — это НЕ находка, а «не измерено».

        Запись схемы `shadow-hist-v1` таких полей не несёт вовсе. Выдать это за
        «владелец видит» нельзя, но и за «уронили поле» тоже: разные починки.
        """
        holes = {b: {"book_apy_pp": None} for b in M.BOOKS}
        with _Contour(records=holes) as c:
            verdict, detail = c.verdict()
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("НЕ записаны журналом", detail)

    def test_link_journal_record_is_stale(self):
        """Звено: запись протухла — замороженный канон не есть наблюдение."""
        with _Contour(hours_ago=ca.OWNER_VISIBILITY_MAX_AGE_H + 2.0) as c:
            verdict, detail = c.verdict()
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("протух", detail)

    def test_link_tree_carries_no_surface_at_all(self):
        """Звено: в дереве поверхностей нет вовсе — третий исход, не находка.

        Так отвечает прод-дерево: `landing/` туда не синхронизируется
        (ADR-152). «Дерева без страницы» и «страница перестала звать выдачу» —
        разные ответы, и склеить их значило бы производить карточки на
        исправную проводку.
        """
        with _Contour(surface=None) as c:
            verdict, detail = c.verdict()
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("населения у оси нет", detail)


class TheCensusStatusAgreesWithTheProbe(unittest.TestCase):
    """Шаг 0-офис печатает СТАТУС переписи, карточка меряется ПРОБОЙ.

    Два ответа на один вопрос — сами по себе дефект: карточка сказала бы «не
    выполнен», а офис в том же такте напечатал бы `OK`, и читатель поверил бы
    тому, что попалось первым. Поэтому ось чтения поля обязана входить и в
    статус переписи, а не только в вердикт пробы. Мутация «снять ось из
    статуса» без этого контроля выживала: проба ловила её собственной ветвью.
    """

    def _census(self, contour):
        return M.run_census(contour.data, now=NOW, repo_root=contour.root)

    def test_status_is_ok_on_the_whole_contour(self):
        with _Contour() as c:
            report = self._census(c)
        self.assertEqual(report["status"], M.STATUS_OK, report.get("reason"))
        self.assertEqual(report["delivered_but_not_rendered"], 0)
        self.assertEqual(report["delivered_as_field"], report["subjects_total"])

    def test_status_is_critical_when_the_surface_reads_no_field(self):
        with _Contour(surface=SURFACE_NO_FIELDS) as c:
            report = self._census(c)
        self.assertEqual(report["status"], M.STATUS_CRITICAL)
        self.assertEqual(report["delivered_but_not_rendered"], 4)
        #: Прежние две оси при этом ЗЕЛЕНЫ — в том и находка #710.
        self.assertEqual(report["recorded_but_not_delivered"], 0)
        self.assertEqual(report["delivered_as_field"], report["subjects_total"])
        self.assertTrue(report["surfaces"]["callers"])

    def test_report_names_the_unrendered_field_by_name(self):
        with _Contour(surface=SURFACE_NO_FIELDS) as c:
            lines = M.format_report(self._census(c))
        body = "\n".join(lines)
        self.assertIn("НЕ ЧИТАЕТСЯ", body)
        self.assertIn("current_apy_pp", body)


class DoesNotPassBySubstring(unittest.TestCase):
    """ADR-333: зачёт — равенство ЗНАЧЕНИЙ в поле, а не найденная подстрока."""

    def test_number_printed_only_inside_prose_is_not_a_pass(self):
        """Выдача печатает числа прозой и не несёт ни одного поля ⇒ красная.

        Это дословно `prose_only` замера #709: Yield Gap выживал подстрокой
        `gain_below_band:0.230pp<0.500pp` — и зачётом не является, потому что
        число там живёт лишь пока гейт не пройден.
        """
        def prose_only(rec):
            return {"numbers_unit": cio_brief.OWNER_NUMBER_UNIT,
                    "numbers_evidenced": False, "numbers_missing": [],
                    "prose": (f"ставка {rec.get('book_apy_pp'):.4f} пп, оптимум "
                              f"{rec.get('target_apy_pp'):.4f} пп, зазор "
                              f"{rec.get('gain_pp'):.4f} пп")}
        with _Contour() as c, mock.patch.object(
                cio_brief, "_owner_numbers", prose_only):
            verdict, detail = c.verdict()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)

    def test_field_name_only_mentioned_is_not_a_read(self):
        """Имя поля внутри фразы — не чтение поля."""
        surface = SURFACE_NO_FIELDS.replace(
            "// поверхность, которая зовёт выдачу и берёт из неё одну прозу",
            "// здесь когда-то читались current_apy_pp optimal_apy_pp yield_gap_pp verdict")
        with _Contour(surface=surface) as c:
            verdict, detail = c.verdict()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)

    def test_the_name_inside_a_one_line_brace_block_is_not_a_read(self):
        """Ось обязана ошибаться в сторону НАХОДКИ, а не оправдания.

        Первая редакция формы чтения принимала «имя где угодно внутри
        однострочных фигурных скобок» — и фраза `{ // читали current_apy_pp }`
        объявлялась чтением. Это ошибка в сторону ОПРАВДАНИЯ: ложная тревога
        стоит перечитывания файла, ложное «дошло» стоило бы трёх месяцев.
        """
        surface = SURFACE_NO_FIELDS.replace(
            "show(br.why, br.why_now);",
            "{ /* когда-то тут читали current_apy_pp optimal_apy_pp "
            "yield_gap_pp verdict */ }")
        with _Contour(surface=surface) as c:
            verdict, detail = c.verdict()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("current_apy_pp", detail)

    def test_destructuring_and_shorthand_ARE_reads(self):
        """Обратная сторона: сузив форму, нельзя потерять настоящее чтение."""
        surface = """<script is:inline>
  async function tick(){
    var r = await jget('/api/live/books/brief');
    var br = (r.books||{}).conservative||{};
    var {current_apy_pp, optimal_apy_pp} = br;
    show({yield_gap_pp: br.yield_gap_pp}, br['verdict']);
  }
</script>
"""
        with _Contour(surface=surface) as c:
            verdict, detail = c.verdict()
        self.assertEqual(verdict, ca.SATISFIED, detail)


class FailsClosedNotOpen(unittest.TestCase):
    def test_a_census_that_cannot_run_is_unmeasured_never_satisfied(self):
        """Упавшая перепись — «не измерено», а не разрешение закрыть карточку."""
        with _Contour() as c, mock.patch.object(
                M, "run_census", side_effect=RuntimeError("дверь закрыта")):
            verdict, detail = c.verdict()
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("перепись упала", detail)

    def test_run_probe_by_name_reaches_the_same_implementation(self):
        """Зов по ИМЕНИ (как из шага 0-офис) не обходит вердикт пробы."""
        verdict, detail = ca.run_probe("owner_visibility_numbers_delivered")
        self.assertIn(verdict, (ca.SATISFIED, ca.NOT_SATISFIED, ca.UNMEASURED))
        self.assertTrue(detail)


class TheAxisLivesOutsideItsOwnPopulation(unittest.TestCase):
    def test_docs_are_not_code_surfaces(self):
        """`docs/` упоминать путь может, читателем выдачи быть не может.

        Если `docs` попадёт в `CODE_SURFACE_DIRS`, третий исход «в дереве нет
        поверхностей» исчезнет: упоминания в документах есть в любом дереве, и
        прод-дерево снова стало бы выглядеть находкой.
        """
        self.assertNotIn("docs", M.CODE_SURFACE_DIRS)
        for rel in M.CODE_SURFACE_DIRS:
            self.assertIn(rel, M.SURFACE_DIRS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
