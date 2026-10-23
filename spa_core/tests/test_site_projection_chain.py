#!/usr/bin/env python3
"""Проекция «снимок → витрина → страницы» проверяется по ИСХОДУ (ADR-373 / ADR-357 п. 5 / ADR-580).

Два вопроса, на которые прежние сторожа не отвечали:

1. **Каждое ли фактическое чтение страницы попадает в существующее поле?** В JavaScript
   отсутствующее поле — не ошибка, а ``undefined``; страница печатает слово «undefined» и
   собирается зелёной (авария ``positions_count``, ADR-373). Страницы разбираются по токенам
   (вложенные цепочки, ``?.``, ``['…']``, деструктуризация, псевдонимы, колбэки), а модули сайта
   (``lib/*.js``) ИСПОЛНЯЮТСЯ в node под записывающими прокси — видно ровно то, что они читают.
2. **Число витрины действительно взято оттуда, куда указывает ``source``?** Происхождение
   измеряется подменой: лист снимка заменяется уникальным значением, витрина пересобирается
   настоящим сборщиком — где подмена всплыла, оттуда и число. ``source`` обязан с этим
   согласоваться, значение опубликованной витрины — совпасть со значением снимка, из которого
   её собрали (снимок находится по хэшу, объявленному в самой витрине).

Каждая проверка имеет отрицательный контроль на НАСТОЯЩЕЙ форме аварии (а не на выдуманном
имени), и ни одна не проходит подстрокой. Третий исход (инв. #17): не измерено — красный тест
с причиной, не пропуск.
"""
from __future__ import annotations

import copy
import unittest

from spa_core.tests import _site_js_reads as jr
from spa_core.tests import _site_projection as sp


def _m():
    try:
        return sp.measure()
    except sp.NotMeasured as exc:
        raise AssertionError(f"НЕ ИЗМЕРЕНО — {exc}") from exc


def _probe_page(text: str, name: str = "__probe__.astro") -> "jr.Analysis":
    """Analyze a synthetic page placed among the real pages (imports resolve like a real page's)."""
    fake = sp.SRC.resolve() / "pages" / name
    return jr.analyze(sp.SRC.resolve(), files=[fake], sources={str(fake): text})


def _reads_problems(an):
    """Scenes executed for THIS analysis' calls (call ids are per analysis)."""
    m = _m()
    scs = sp.scenes(an.specs, sorted(an.closure), m.shelf, m.today_snap, m.const, m.bsn)
    return sp.check_reads(an, scs)


class EveryPageReadLandsOnARealField(unittest.TestCase):
    def test_the_reader_files_are_found_and_parsed(self):
        m = _m()
        self.assertGreaterEqual(len(sp.page_files()), 20, "читателей витрины меньше двадцати — разбор сломан")
        self.assertEqual(m.analysis.unparsed, [], m.analysis.unparsed)
        self.assertGreater(len(m.analysis.reads), 100)

    def test_every_read_resolves(self):
        m = _m()
        self.assertEqual(m.reads.problems, [], "\n".join(m.reads.problems))

    def test_nothing_escapes_the_reader(self):
        """Объект данных, ушедший туда, куда разбор не идёт, — третий исход, а не «чисто»."""
        m = _m()
        self.assertEqual(m.reads.unanalyzed, [], "\n".join(m.reads.unanalyzed))

    def test_every_call_into_the_site_modules_ran(self):
        m = _m()
        dead = [f"{s.module}::{s.name} ({s.site})" for s in m.analysis.specs
                if all((sc.out["specs"].get(str(s.id)) or {}).get("ok", 0) == 0 for sc in m.scenes)]
        self.assertEqual(dead, [], "вызовы, не исполнившиеся ни в одной сцене (НЕ ИЗМЕРЕНО): " + "; ".join(dead))

    # ── negative controls ────────────────────────────────────────────────────────────────────────
    def test_a_nested_shelf_field_a_lib_reads_disappearing_is_red(self):
        """`realized_rate.periodReturn` читает headline.period.period.start_date — его пропажа
        краснит, хотя функция вернула бы «не измерено» без падения."""
        m = _m()

        def cut(sh):
            per = ((sh.get("headline") or {}).get("period") or {}).get("period")
            if isinstance(per, dict):
                per.pop("start_date", None)
        scs = sp.scenes(m.analysis.specs, sorted(m.analysis.closure), m.shelf, m.today_snap, m.const, m.bsn,
                        shelf_mutator=cut)
        rc = sp.check_reads(m.analysis, scs)
        self.assertTrue(any("headline/period/period/start_date" in p and "realized_rate.js" in p
                            for p in rc.problems), rc.problems)

    def test_a_nested_view_field_a_page_reads_disappearing_is_red(self):
        """/packages читает `paperTracks[key].pre_fix_period.label_en` (переходник ← витрина)."""
        m = _m()

        def cut(sh):
            for b in (sh.get("books") or {}).values():
                if isinstance(b, dict) and isinstance(b.get("pre_fix_period"), dict):
                    b["pre_fix_period"].pop("label_en", None)
        scs = sp.scenes(m.analysis.specs, sorted(m.analysis.closure), m.shelf, m.today_snap, m.const, m.bsn,
                        shelf_mutator=cut)
        rc = sp.check_reads(m.analysis, scs)
        self.assertTrue(any("packages.astro" in p and "pre_fix_period/label_en" in p for p in rc.problems),
                        rc.problems)

    def test_a_lib_reading_a_missing_field_is_red(self):
        """Порча самого модуля: realized_rate читает `P.period.start_datex` — красный."""
        m = _m()
        rr = sp.SRC.resolve() / "lib" / "realized_rate.js"
        src = rr.read_text(encoding="utf-8")
        self.assertIn("P.period.start_date ||", src, "предпосылка контроля")
        out = sp.run_harness(m.shelf, m.today_snap, m.analysis.specs, sorted(m.analysis.closure),
                             overrides={str(rr): src.replace("P.period.start_date ||", "P.period.start_datex ||")})
        sc = sp.Scene("mutated", m.shelf, m.today_snap, out)
        rc = sp.check_reads(m.analysis, [sc, m.scenes[1]])
        self.assertTrue(any("start_datex" in p for p in rc.problems), rc.problems)

    def test_the_static_reader_follows_every_access_form(self):
        """Цепочка, `?.`, индекс-литерал, деструктуризация, псевдоним, колбэк, `(X || {}).k`, результат
        функции модуля — верные имена проходят, а испорченное в ЛЮБОЙ форме краснит."""
        good = """---
import snap from '../lib/snapshot_view.js';
import NUMBERS, { book } from '../lib/site_numbers.js';
import { totalReturnSinceStart } from '../lib/realized_rate.js';
const a = snap.paper_tracks.balanced.positions_count;
const b = snap?.paper_tracks?.['aggressive']?.evidence_split;
const { gates_passed, paper_tracks: { conservative: { dd_pct } } } = snap;
const P = NUMBERS.headline.period;
const s = P.period.start_date;
const rows = (NUMBERS.exposure || {}).rows || [];
const shares = rows.map((r) => r.share.value);
for (const [k, pt] of Object.entries(snap.paper_tracks)) { const x = pt.status; }
const split = (book('balanced') || {}).evidence_split || {};
const t = totalReturnSinceStart(false).text;
---
<p>{snap.as_of} {snap.paper_tracks.conservative.apy_pct}</p>
"""
        an = _probe_page(good)
        rc = _reads_problems(an)
        self.assertEqual([p for p in rc.problems if "__probe__" in p], [])
        self.assertEqual([u for u in rc.unanalyzed if "__probe__" in u], [])
        bad_forms = {   # form → (line, the misspelt read the problem must name)
            "chain": ("const a = snap.paper_tracks.balanced.positions_countt;", "positions_countt"),
            "optional+index": ("const b = snap?.paper_tracks?.['aggressive']?.evidence_splitt;", "evidence_splitt"),
            "destructure": ("const { gates_passedd } = snap;", "gates_passedd"),
            "nested destructure": ("const { paper_tracks: { conservative: { dd_pctt } } } = snap;", "dd_pctt"),
            "alias": ("const P = NUMBERS.headline.period; const s = P.period.start_datee;", "start_datee"),
            "callback": ("const xs = (NUMBERS.exposure || {}).rows.map((r) => r.share.valuee);", "valuee"),
            "entries": ("for (const [k, pt] of Object.entries(snap.paper_tracks)) { const x = pt.statuss; }",
                        "statuss"),
            "lib result": ("const split = (book('balanced') || {}).evidence_splitt;", "evidence_splitt"),
            "call result": ("const t = totalReturnSinceStart(false).textt;", "textt"),
            "template": (None, "apy_pctt"),
        }
        head = ("import snap from '../lib/snapshot_view.js';\n"
                "import NUMBERS, { book } from '../lib/site_numbers.js';\n"
                "import { totalReturnSinceStart } from '../lib/realized_rate.js';\n")
        for form, (line, needle) in bad_forms.items():
            if line is None:
                text = "---\n" + head + "---\n<p>{snap.paper_tracks.conservative.apy_pctt}</p>\n"
            else:
                text = "---\n" + head + line + "\n---\n<p></p>\n"
            rc = _reads_problems(_probe_page(text))
            hits = [p for p in rc.problems if "__probe__" in p]
            self.assertTrue(hits and all(needle in p for p in hits), f"форма «{form}» не поймана точно: {hits}")

    def test_the_original_accident_is_red(self):
        """Авария ADR-373 целиком: страница читает `paper_tracks.<книга>.positions_count`, а
        переходник этого поля не отдаёт (строка убрана из snapshot_view.js, модуль исполнен)."""
        m = _m()
        page = """---
import snap from '../lib/snapshot_view.js';
const n = (snap.paper_tracks || {}).balanced.positions_count;
---
<p>позиций: {n}</p>
"""
        an = _probe_page(page)
        view_src = sp.VIEW_MODULE.read_text(encoding="utf-8")
        line = [ln for ln in view_src.splitlines(True) if ln.strip().startswith("positions_count:")]
        self.assertEqual(len(line), 1, "предпосылка контроля")
        ov = {str(sp.VIEW_MODULE.resolve()): view_src.replace(line[0], "")}
        scs = [sp.Scene(n, sh, sn, sp.run_harness(sh, sn, an.specs, sorted(an.closure), overrides=ov))
               for n, sh, sn in (("published", m.shelf, m.today_snap),)]
        rc = sp.check_reads(an, scs)
        self.assertTrue(any("__probe__" in p and "positions_count" in p for p in rc.problems), rc.problems)
        # and with the real view the same page is clean — the red above is the field, not the probe
        self.assertEqual([p for p in _reads_problems(an).problems if "__probe__" in p], [])

    def test_a_read_is_not_a_substring(self):
        """Имя в комментарии, в строке, в тексте разметки — не чтение; чтение чужого объекта с тем же
        именем — не чтение витрины."""
        text = """---
import snap from '../lib/snapshot_view.js';
// snap.paper_tracks.balanced.no_such_field
const note = 'snap.no_such_field';
const other = { paper_tracks: {} };
const x = other.paper_tracks.no_such_field;
---
<p>snap.no_such_field — text, not code</p>
"""
        rc = _reads_problems(_probe_page(text))
        self.assertEqual([p for p in rc.problems if "__probe__" in p], [])

    def test_an_object_escaping_the_reader_is_named(self):
        """Ветвь переходника, ушедшая в объектный литерал, — UNANALYZED, а не тишина."""
        text = """---
import snap from '../lib/snapshot_view.js';
const box = { tracks: snap.paper_tracks };
---
"""
        rc = _reads_problems(_probe_page(text))
        self.assertTrue([u for u in rc.unanalyzed if "__probe__" in u], rc.unanalyzed)
        # (`snap.package_status` would NOT be named: it is a pass-through — the view subtree IS the snapshot
        # subtree in every scene, so no nested field can be lost between them; `_pass_through`)
        for markup in ("<Card rec={snap.paper_tracks.balanced} />", "<p>{snap.paper_tracks}</p>"):
            text = "---\nimport snap from '../lib/snapshot_view.js';\n---\n" + markup + "\n"
            rc = _reads_problems(_probe_page(text))
            self.assertTrue([u for u in rc.unanalyzed if "__probe__" in u], f"{markup}: {rc.unanalyzed}")
        # a scalar used whole is not an escape
        rc = _reads_problems(_probe_page("---\nimport snap from '../lib/snapshot_view.js';\n---\n"
                                         "<Card days={snap.real_track_days} />\n"))
        self.assertEqual([u for u in rc.unanalyzed if "__probe__" in u], [])


class EveryShelfFigureComesFromWhereItSays(unittest.TestCase):
    def test_every_figure_has_a_measured_origin_and_agrees_with_it(self):
        m = _m()
        rebuilt = sp.build_from(m.bsn, m.snap, m.const, m.shelf["published_at"])
        problems = sp.check_shelf_provenance(m.shelf, m.snap, m.const, m.origins, rebuilt)
        self.assertEqual(problems, [], f"входы витрины: {m.shelf_inputs}\n" + "\n".join(problems))
        self.assertGreaterEqual(len(sp.figures(m.shelf)), 40)

    def test_the_origin_is_measured_not_read_off_the_source_text(self):
        """Карта происхождения снята подменой: у NAV якоря — anchor_equity, у ставки книги — paper_tracks,
        у порога — конституция; source сам по себе в карту не входит."""
        m = _m()
        self.assertEqual(m.origins[("headline", "anchor_nav")], [("snapshot", ("anchor_equity",))])
        self.assertEqual(m.origins[("books", "conservative", "apy")],
                         [("snapshot", ("paper_tracks", "conservative", "apy_pct"))])
        self.assertEqual(m.origins[("thresholds", "kill_switch_hard")],
                         [("constitution", ("kill_switch", "hard_kill_pct"))])
        # a rate published as null below maturity still has its origin (unlocked scene)
        self.assertEqual(m.origins[("books", "balanced", "apy")],
                         [("snapshot", ("paper_tracks", "balanced", "apy_pct"))])

    def _problems(self, mutate):
        m = _m()
        shelf = copy.deepcopy(m.shelf)
        mutate(shelf)
        rebuilt = sp.build_from(m.bsn, m.snap, m.const, m.shelf["published_at"])
        return sp.check_shelf_provenance(shelf, m.snap, m.const, m.origins, rebuilt)

    def test_a_source_naming_the_wrong_path_is_red(self):
        def wrong(sh):
            sh["headline"]["anchor_nav"]["source"] = ("landing/src/data/track_snapshot.json → track_return_pct "
                                                      "(NAV at the close of the anchor bar)")
        pr = self._problems(wrong)
        self.assertTrue(any(p.startswith("headline/anchor_nav") and "путь не тот" in p for p in pr), pr)

    def test_a_source_naming_the_wrong_file_is_red(self):
        def wrong(sh):
            sh["headline"]["nav"]["source"] = "constitution.json"
        pr = self._problems(wrong)
        self.assertTrue(any(p.startswith("headline/nav") and "не называет снимок" in p for p in pr), pr)

    def test_a_value_that_does_not_match_its_origin_is_red(self):
        def wrong(sh):
            sh["headline"]["nav"]["value"] = sh["headline"]["nav"]["value"] + 1.0
        pr = self._problems(wrong)
        self.assertTrue(any(p.startswith("headline/nav") and "значение витрины" in p for p in pr), pr)

    def test_a_false_equality_claim_is_red(self):
        def wrong(sh):
            sh["headline"]["apy"]["source"] = sh["headline"]["apy"]["source"].replace(
                "track_period.annualised_equivalent_pct", "track_period.twr_pct")
        pr = self._problems(wrong)
        self.assertTrue(any(p.startswith("headline/apy") and "track_period.twr_pct" in p for p in pr), pr)

    def test_a_backtest_labelled_as_measurement_is_red(self):
        def wrong(sh):
            sh["packages"]["conservative"]["apy"]["kind"] = "замер"
        pr = self._problems(wrong)
        self.assertTrue(any(p.startswith("packages/conservative/apy") and "бэктест" in p for p in pr), pr)

    def test_an_immature_rate_with_a_number_is_red(self):
        def wrong(sh):
            sh["books"]["balanced"]["apy"]["value"] = 2.48
        pr = self._problems(wrong)
        self.assertTrue(any(p.startswith("books/balanced/apy") for p in pr), pr)


if __name__ == "__main__":
    unittest.main()
