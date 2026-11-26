#!/usr/bin/env python3
"""Контроли прибора замера спроса на поля снимка (ADR-1117).

Прибор `scripts/snapshot_view_field_demand.py` отвечает на вопрос, которого не задавал
никто: КТО из `landing/src/**` обращается к полю дневного снимка. От его ответа зависит,
попадёт путь в переходник или будет объявлен в `NOT_IN_VIEW` — то есть прибор решает,
может ли страница напечатать «undefined» молча (авария ADR-373).

**Почему контроли идут ОБЕИМИ сторонами.** Мера, которая находит чтение всегда, бесполезна
так же, как мера, которая не находит его никогда. Поэтому у каждой дороги здесь две сцены:
одна, где поле ЧИТАЮТ, и соседняя, отличающаяся РОВНО этим, где не читают. Без второй
половины «нашёл» неотличимо от «отвечает так всегда» — дословный урок ADR-333 и
`.claude/rules/acceptance.md` п. 3.

**Сцены одноразовые.** Ни один тест не трогает ни живой `landing/`, ни живой снимок: каждая
сцена — свой каталог в `tempfile`, и предмет в ней назван явно.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "snapshot_view_field_demand.py"


def _load():
    spec = importlib.util.spec_from_file_location("snapshot_view_field_demand", TOOL)
    assert spec is not None and spec.loader is not None, f"прибор не ввозится: {TOOL}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load()

#: Снимок сцены: у книг есть ПОДВЕТКИ (чтобы раскрытие вычисляемого ключа было проверяемым),
#: и есть лист верхнего уровня.
SCENE_SNAPSHOT = {
    "real_track_days": 156,
    "paper_tracks": {
        "balanced": {"apy_pct": 4.39, "positions_count": 0, "reportable": False},
        "aggressive": {"apy_pct": 6.91, "positions_count": 0, "reportable": False},
    },
    "track_period": {"twr_pct": 2.02, "period": {"days_act": 157}},
}

#: Переходник сцены: несёт ТОЛЬКО `real_track_days`. Всё остальное — предмет вопроса.
SCENE_VIEW = """
import NUMBERS from '../data/site_numbers.json';
import RAW from '../data/track_snapshot.json';
export default {
  real_track_days: RAW.real_track_days,
};
"""


def build_scene(tmp: Path, page: str, *, view: str = SCENE_VIEW,
                snapshot: dict | None = None, extra: dict | None = None) -> Path:
    """Одноразовое дерево сайта: снимок, витрина, переходник и ОДНА страница."""
    root = tmp / "tree"
    (root / "landing" / "src" / "data").mkdir(parents=True)
    (root / "landing" / "src" / "lib").mkdir(parents=True)
    (root / "landing" / "src" / "pages").mkdir(parents=True)
    (root / "landing" / "src" / "data" / "track_snapshot.json").write_text(
        json.dumps(snapshot if snapshot is not None else SCENE_SNAPSHOT), encoding="utf-8")
    (root / "landing" / "src" / "data" / "site_numbers.json").write_text(
        json.dumps({"headline": {}, "track": {}}), encoding="utf-8")
    (root / "landing" / "src" / "lib" / "snapshot_view.js").write_text(view, encoding="utf-8")
    (root / "landing" / "src" / "pages" / "one.astro").write_text(page, encoding="utf-8")
    for rel, body in (extra or {}).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return root


def verdict(root: Path, path: str) -> str:
    return M.measure(root, want_view_shape=False)["verdict"][path]


IMPORT = "import snap from '../lib/snapshot_view.js';\n"


class FourRoadsAreFoundAndEachHasItsOppositeScene(unittest.TestCase):
    """Каждая объявленная дорога найдена — и на соседней сцене НЕ найдена."""

    def _pair(self, reading: str, silent: str, path: str, *, extra=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + reading, extra=extra)
            self.assertEqual(verdict(root, path), M.READ_VIEW,
                             f"дорога не найдена: {reading!r}")
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + silent, extra=extra)
            self.assertEqual(verdict(root, path), M.NOT_READ,
                             f"мера отвечает «читают» и там, где не читают: {silent!r}")

    def test_road_1_direct_chain(self):
        self._pair("const x = snap.track_period.twr_pct;\n",
                   "const x = snap.real_track_days;\n",
                   "/track_period/twr_pct")

    def test_road_2_alias(self):
        self._pair("const tp = snap.track_period;\nconst x = tp.twr_pct;\n",
                   "const tp = snap.real_track_days;\nconst x = tp;\n",
                   "/track_period/twr_pct")

    def test_road_2bis_guarded_alias_of_the_whole_value(self):
        """`const s = snap || {}` — идиома четырёх помощников `golive_label.js`."""
        self._pair("const s = snap || {};\nconst x = s.track_period.twr_pct;\n",
                   "const s = snap || {};\nconst x = s.real_track_days;\n",
                   "/track_period/twr_pct")

    def test_road_3_destructuring(self):
        self._pair("const { track_period } = snap;\nconst x = track_period.twr_pct;\n",
                   "const { real_track_days } = snap;\nconst x = real_track_days;\n",
                   "/track_period/twr_pct")

    def test_road_4_helper(self):
        helper = {"landing/src/lib/h.js":
                  "export function phrase(s) { return String(s.track_period.twr_pct); }\n"}
        silent = {"landing/src/lib/h.js":
                  "export function phrase(s) { return String(s.real_track_days); }\n"}
        imp = "import { phrase } from '../lib/h.js';\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + imp + "const x = phrase(snap);\n",
                               extra=helper)
            self.assertEqual(verdict(root, "/track_period/twr_pct"), M.READ_VIEW)
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + imp + "const x = phrase(snap);\n",
                               extra=silent)
            self.assertEqual(verdict(root, "/track_period/twr_pct"), M.NOT_READ)

    def test_the_helper_is_resolved_through_an_import_alias(self):
        """`import { phrase as p }` — псевдоним ввоза, а не имя определения."""
        helper = {"landing/src/lib/h.js":
                  "export function phrase(s) { return String(s.track_period.twr_pct); }\n"}
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(
                Path(tmp),
                IMPORT + "import { phrase as p } from '../lib/h.js';\nconst x = p(snap);\n",
                extra=helper)
            self.assertEqual(verdict(root, "/track_period/twr_pct"), M.READ_VIEW)

    def test_the_helper_argument_position_is_respected(self):
        """Снимок стои́т ВТОРЫМ аргументом — читается параметр №1, а не №0."""
        helper = {"landing/src/lib/h.js":
                  "export function phrase(ru, s) { return String(s.track_period.twr_pct); }\n"}
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(
                Path(tmp),
                IMPORT + "import { phrase } from '../lib/h.js';\n"
                         "const x = phrase(true, snap);\n", extra=helper)
            self.assertEqual(verdict(root, "/track_period/twr_pct"), M.READ_VIEW)


class ComputedKeyIsExpandedToEverySibling(unittest.TestCase):
    """Ключ вычисляется, поле названо ⇒ спрос у ВСЕХ соседей (fail-CLOSED)."""

    def test_a_computed_book_key_charges_both_books(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(
                Path(tmp),
                IMPORT + "const bk = snap.paper_tracks;\nconst v = bk[key].apy_pct;\n")
            got = M.measure(root, want_view_shape=False)
            self.assertEqual(got["verdict"]["/paper_tracks/balanced/apy_pct"], M.READ_VIEW)
            self.assertEqual(got["verdict"]["/paper_tracks/aggressive/apy_pct"], M.READ_VIEW)
            self.assertEqual(got["verdict"]["/paper_tracks/balanced/reportable"], M.NOT_READ,
                             "раскрытие ключа зачло СОСЕДНЕЕ ПОЛЕ — мера стала бесполезной")
            self.assertGreaterEqual(got["chains_with_computed_key"], 1)

    def test_a_subtree_taken_by_a_computed_key_keeps_its_alias(self):
        """`const pt = bk[key]` → чтения на `pt` приписываются обеим книгам."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(
                Path(tmp),
                IMPORT + "const bk = snap.paper_tracks;\nconst pt = bk[key];\n"
                         "const v = pt.reportable;\n")
            got = M.measure(root, want_view_shape=False)
            self.assertEqual(got["verdict"]["/paper_tracks/balanced/reportable"], M.READ_VIEW)
            self.assertEqual(got["verdict"]["/paper_tracks/aggressive/reportable"], M.READ_VIEW)

    def test_a_computed_index_into_a_leaf_costs_nothing(self):
        """Индекс в лист (или список) подветки не имеет — третий исход тут был бы шумом."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp),
                               IMPORT + "const d = snap.real_track_days;\nconst c = d[i];\n")
            got = M.measure(root, want_view_shape=False)
            self.assertEqual(got["unmeasured"], [],
                             f"лист объявлен НЕ ИЗМЕРЕННЫМ: {got['unmeasured']}")


class TheThirdOutcomeIsNeverSilent(unittest.TestCase):
    """«Не измерено» отличимо и от «читают», и от «не читает никто» (инв. #17)."""

    def test_a_value_handed_to_a_foreign_door_is_unmeasured_not_unread(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(
                Path(tmp),
                IMPORT + "const bk = snap.paper_tracks;\n"
                         "const s = JSON.stringify(bk);\n")
            got = M.measure(root, want_view_shape=False)
            self.assertTrue(any("целиком" in u for u in got["unmeasured"]),
                            f"утечка за чужую дверь не названа: {got['unmeasured']}")

    def test_an_unreadable_file_is_named_and_does_not_pass_as_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + "const x = snap.real_track_days;\n")
            (root / "landing" / "src" / "pages" / "bad.astro").write_bytes(b"\xff\xfe\x00bad")
            got = M.measure(root, want_view_shape=False)
            self.assertTrue(any("не прочитан" in u for u in got["unmeasured"]),
                            f"нечитаемый файл промолчал: {got['unmeasured']}")

    def test_a_tree_without_any_root_binding_refuses_instead_of_answering_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), "const x = 1;\n")
            with self.assertRaises(M.NotMeasured):
                M.measure(root, want_view_shape=False)

    def test_a_missing_snapshot_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + "const x = snap.real_track_days;\n")
            (root / "landing" / "src" / "data" / "track_snapshot.json").unlink()
            with self.assertRaises(M.NotMeasured):
                M.measure(root, want_view_shape=False)

    def test_a_broken_snapshot_refuses_instead_of_guessing_a_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + "const x = snap.real_track_days;\n")
            (root / "landing" / "src" / "data" / "track_snapshot.json").write_text("{не json")
            with self.assertRaises(M.NotMeasured):
                M.measure(root, want_view_shape=False)

    def test_the_view_shape_without_node_is_not_measured(self):
        """Отсутствие инструмента — третий исход, а не молчаливый зелёный (урок pyflakes)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + "const x = snap.real_track_days;\n")
            saved = M.shutil.which
            M.shutil.which = lambda _name: None
            try:
                with self.assertRaises(M.NotMeasured):
                    M.measure(root, want_view_shape=True)
            finally:
                M.shutil.which = saved


class TokensAndGuardsAreNotReaders(unittest.TestCase):
    """Мера идёт по ДОРОГЕ значения, а не по слову и не по проверке на пустоту."""

    def test_a_comment_naming_the_field_is_not_a_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(
                Path(tmp),
                IMPORT + "// snap.track_period.twr_pct — так было раньше\n"
                         "/* snap.track_period.twr_pct */\n"
                         "const x = snap.real_track_days;\n")
            self.assertEqual(verdict(root, "/track_period/twr_pct"), M.NOT_READ,
                             "комментарий зачтён за чтение — мера считает слова, не дороги")

    def test_a_same_named_binding_in_a_file_without_the_import_is_not_a_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + "const x = snap.real_track_days;\n",
                               extra={"landing/src/pages/two.astro":
                                      "const snap = other();\n"
                                      "const y = snap.track_period.twr_pct;\n"})
            self.assertEqual(verdict(root, "/track_period/twr_pct"), M.NOT_READ,
                             "одноимённая привязка ЧУЖОГО объекта зачтена за снимок")

    def test_a_null_guard_is_not_a_lost_road(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(
                Path(tmp),
                IMPORT + "const tp = (snap && snap.track_period) || {};\n"
                         "const x = tp.twr_pct;\n")
            got = M.measure(root, want_view_shape=False)
            self.assertEqual(got["verdict"]["/track_period/twr_pct"], M.READ_VIEW)
            self.assertEqual(got["unmeasured"], [],
                             f"null-guard объявлен потерянной дорогой: {got['unmeasured']}")

    def test_the_keyword_before_a_paren_is_not_a_callee(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(
                Path(tmp),
                IMPORT + "const tp = snap.track_period;\n"
                         "export function f() { return (tp && tp.twr_pct); }\n")
            got = M.measure(root, want_view_shape=False)
            self.assertFalse([u for u in got["unmeasured"] if "`return`" in u],
                             f"`return` принят за зов помощника: {got['unmeasured']}")

    def test_the_import_line_itself_is_not_an_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + "const x = snap.real_track_days;\n")
            got = M.measure(root, want_view_shape=False)
            self.assertEqual(got["unmeasured"], [],
                             f"строка ввоза прочитана как утечка: {got['unmeasured']}")

    def test_a_deep_read_charges_every_parent_on_the_way(self):
        """Чтение `/a/b/c` есть обращение и к `/a`, и к `/a/b` — иначе родитель «не читается»."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(
                Path(tmp), IMPORT + "const x = snap.track_period.period.days_act;\n")
            got = M.measure(root, want_view_shape=False)
            for path in ("/track_period", "/track_period/period",
                         "/track_period/period/days_act"):
                self.assertEqual(got["verdict"][path], M.READ_VIEW,
                                 f"родитель {path} не зачтён — переходник потерял бы его")

    def test_a_comparison_or_negation_is_not_a_lost_road(self):
        """`snap === null`, `!snap`, `snap ? a : b` — проверки значения, а не утечки."""
        for form in ("const a = snap === null;\n", "const a = !snap;\n",
                     "const a = snap ? 1 : 2;\n"):
            with tempfile.TemporaryDirectory() as tmp:
                root = build_scene(Path(tmp), IMPORT + form)
                got = M.measure(root, want_view_shape=False)
                self.assertEqual(got["unmeasured"], [],
                                 f"проверка {form!r} объявлена потерянной дорогой: "
                                 f"{got['unmeasured']}")

    def test_a_test_of_the_value_outside_a_declaration_is_not_a_lost_road(self):
        """Проверка значения ВНЕ объявления — последнее место, где правило guard-а и нужно.

        Внутри `const a = snap === null` дорогу закрывает рождение псевдонима, поэтому сцена
        обязана поставить проверку туда, где псевдонима нет вовсе: в условие. Без этой сцены
        снятие правила guard-а ВЫЖИВАЛО (первый мутационный прогон, M08) — то есть мера
        держалась на соседнем правиле, а не на своём.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(
                Path(tmp),
                IMPORT + "export function f() { if (snap === null) { return 1; } "
                         "return snap.real_track_days; }\n")
            got = M.measure(root, want_view_shape=False)
            self.assertEqual(got["unmeasured"], [],
                             f"проверка в условии объявлена потерянной дорогой: "
                             f"{got['unmeasured']}")

    def test_a_leaf_handed_to_an_unresolvable_callee_costs_nothing(self):
        """У листа подветок нет — спрашивать о них нечего, даже если зов не разрешён."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(
                Path(tmp),
                IMPORT + "const d = snap.real_track_days;\nconst s = чужая(d);\n")
            got = M.measure(root, want_view_shape=False)
            self.assertEqual(got["unmeasured"], [],
                             f"лист объявлен НЕ ИЗМЕРЕННЫМ: {got['unmeasured']}")

    def test_a_helper_calling_its_neighbour_in_the_same_file_is_resolved(self):
        """Зов разрешается по ПОЛНОМУ тексту файла, а не по срезу тела помощника."""
        helper = {"landing/src/lib/h.js":
                  "export function outer(s) { return inner(s); }\n"
                  "export function inner(s) { return String(s.track_period.twr_pct); }\n"}
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(
                Path(tmp),
                IMPORT + "import { outer } from '../lib/h.js';\nconst x = outer(snap);\n",
                extra=helper)
            got = M.measure(root, want_view_shape=False)
            self.assertEqual(got["verdict"]["/track_period/twr_pct"], M.READ_VIEW,
                             "сосед в том же файле не разрешён — срез тела пошёл в резолвинг")
            self.assertEqual(got["unmeasured"], [], got["unmeasured"])

    def test_a_subtree_inside_a_keyword_paren_is_not_a_callee(self):
        """`if (tp)` и `return (tp)` — не зовы; принять их за зов значит выдумать помощника."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(
                Path(tmp),
                IMPORT + "const tp = snap.track_period;\n"
                         "export function f() { if (tp) { return (tp); } return null; }\n")
            got = M.measure(root, want_view_shape=False)
            self.assertFalse([u for u in got["unmeasured"]
                              if "`if`" in u or "`return`" in u],
                             f"ключевое слово принято за зов помощника: {got['unmeasured']}")

    def test_the_raw_snapshot_reader_is_a_separate_kind(self):
        """Чтение НАПРЯМУЮ из снимка и чтение через переходник — разные вердикты."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(
                Path(tmp), IMPORT + "const x = snap.real_track_days;\n",
                extra={"landing/src/lib/p.js":
                       "import SNAP from '../data/track_snapshot.json';\n"
                       "export const t = SNAP.track_period.twr_pct;\n"})
            self.assertEqual(verdict(root, "/track_period/twr_pct"), M.READ_RAW)


class TheFindingIsTheMissingFieldThatIsRead(unittest.TestCase):
    """Находка прибора = поле ЧИТАЮТ, а переходник его не несёт."""

    def test_a_read_field_absent_from_the_view_is_a_finding(self):
        if shutil.which("node") is None:
            self.fail("НЕ ИЗМЕРЕНО — нет `node`: форму переходника нечем снять")
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + "const x = snap.track_period.twr_pct;\n")
            got = M.measure(root, want_view_shape=True)
            self.assertIn("/track_period/twr_pct", got["findings"])

    def test_the_same_field_carried_by_the_view_is_not_a_finding(self):
        """Обратная сцена, отличающаяся РОВНО наличием поля в переходнике."""
        if shutil.which("node") is None:
            self.fail("НЕ ИЗМЕРЕНО — нет `node`: форму переходника нечем снять")
        view = SCENE_VIEW.replace(
            "  real_track_days: RAW.real_track_days,",
            "  real_track_days: RAW.real_track_days,\n  track_period: RAW.track_period,")
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + "const x = snap.track_period.twr_pct;\n",
                               view=view)
            got = M.measure(root, want_view_shape=True)
            self.assertEqual(got["findings"], [])


class TheDoorTheShapeGuardUsesFlipsWithTheWorld(unittest.TestCase):
    """`not_read_paths` — та самая дверь, которой сторож формы перемеряет свои причины."""

    def test_the_door_drops_a_path_as_soon_as_a_page_reads_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + "const x = snap.real_track_days;\n")
            self.assertIn("/track_period/twr_pct", M.not_read_paths(root))
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + "const x = snap.track_period.twr_pct;\n")
            self.assertNotIn("/track_period/twr_pct", M.not_read_paths(root),
                             "дверь держит путь в «никто не читает», когда его уже читают — "
                             "причина исключения стала бы прикрытием дефекта")

    def test_the_shape_guard_asks_this_door_and_not_a_substring(self):
        """Сторож формы ЗОВЁТ дверь — проверено разбором, а не поиском подстроки."""
        import ast

        guard = ROOT / "spa_core" / "tests" / "test_site_snapshot_view_shape.py"
        tree = ast.parse(guard.read_text(encoding="utf-8"))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("not_read_paths", called,
                      "сторож формы не зовёт дверь замера — его причины снова обещание")


class TheCliNamesItsTreeAndItsOutcome(unittest.TestCase):
    """Выбор дерева ПЕЧАТАЕТСЯ, а исходы различимы кодом возврата."""

    def _run(self, *args, root=None):
        return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True,
                              text=True, timeout=600, cwd=str(root or ROOT))

    def test_a_named_unreadable_tree_is_code_two(self):
        out = self._run("--repo-root", "/нет/такого/дерева")
        self.assertEqual(out.returncode, 2)
        self.assertIn("НЕ ИЗМЕРЕНО", out.stderr)

    def test_a_named_tree_is_printed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + "const x = snap.real_track_days;\n")
            out = self._run("--repo-root", str(root), "--no-view-shape")
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("НАЗВАНО входом", out.stdout)

    def test_the_default_tree_is_printed_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + "const x = snap.real_track_days;\n")
            out = self._run("--no-view-shape", root=root)
            self.assertIn("УМОЛЧАНИЕ", out.stdout + out.stderr)

    def test_one_path_can_be_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + "const x = snap.track_period.twr_pct;\n")
            out = self._run("--repo-root", str(root), "--no-view-shape",
                            "--path", "/track_period/twr_pct")
            self.assertIn(M.READ_VIEW, out.stdout)

    def test_a_path_absent_from_the_snapshot_is_not_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + "const x = snap.real_track_days;\n")
            out = self._run("--repo-root", str(root), "--no-view-shape",
                            "--path", "/выдуманное_поле")
            self.assertEqual(out.returncode, 2)
            self.assertIn("НЕ ИЗМЕРЕНО", out.stderr)

    def test_a_finding_is_code_one(self):
        if shutil.which("node") is None:
            self.fail("НЕ ИЗМЕРЕНО — нет `node`")
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + "const x = snap.track_period.twr_pct;\n")
            out = self._run("--repo-root", str(root))
            self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
            self.assertIn("НАХОДКА", out.stdout)

    def test_the_json_form_carries_the_axes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_scene(Path(tmp), IMPORT + "const x = snap.real_track_days;\n")
            out = self._run("--repo-root", str(root), "--no-view-shape", "--json")
            got = json.loads(out.stdout)
            for key in ("verdict", "not_read", "unmeasured", "max_hops",
                        "chains_with_computed_key", "view_shape_measured"):
                self.assertIn(key, got, f"ось `{key}` в машинном выводе не объявлена")
            self.assertFalse(got["view_shape_measured"])


if __name__ == "__main__":
    unittest.main()


class TheAcceptanceProbeHasControlsBothWays(unittest.TestCase):
    """Проба приёмки `snapshot_view_exclusions_are_measured` (ADR-1117, `.claude/rules/acceptance.md` п. 3).

    Зелёная на целом контуре и КРАСНАЯ на каждом порванном звене — с названным
    звеном. Сцены одноразовые: копируется `landing/src` и два файла механизма,
    живое дерево не трогается ни одним тестом.
    """

    @staticmethod
    def _probe():
        from spa_core.monitoring.card_acceptance import PROBES
        return PROBES["snapshot_view_exclusions_are_measured"]

    @staticmethod
    def _contour(tmp: Path) -> Path:
        """Одноразовая копия контура: сайт + прибор + сторож формы."""
        root = tmp / "tree"
        shutil.copytree(ROOT / "landing" / "src", root / "landing" / "src")
        (root / "scripts").mkdir(parents=True)
        (root / "spa_core" / "tests").mkdir(parents=True)
        shutil.copy2(TOOL, root / "scripts" / TOOL.name)
        shutil.copy2(ROOT / "spa_core" / "tests" / "test_site_snapshot_view_shape.py",
                     root / "spa_core" / "tests" / "test_site_snapshot_view_shape.py")
        return root

    def _verdict(self, root: Path, arg=None):
        return self._probe()(arg, repo_root=str(root))

    def test_the_whole_contour_is_satisfied(self):
        if shutil.which("node") is None:
            self.fail("НЕ ИЗМЕРЕНО — нет `node`: форму переходника нечем снять")
        with tempfile.TemporaryDirectory() as tmp:
            state, why = self._verdict(self._contour(Path(tmp)))
            self.assertEqual(state, "satisfied", why)

    def test_without_the_prober_the_criterion_is_not_satisfied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._contour(Path(tmp))
            (root / "scripts" / TOOL.name).unlink()
            state, why = self._verdict(root)
            self.assertEqual(state, "not_satisfied", why)
            self.assertIn("замера спроса", why)

    def test_without_the_door_the_criterion_is_not_satisfied(self):
        """Прибор есть, двери `not_read_paths` нет — звено названо по имени."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._contour(Path(tmp))
            tool = root / "scripts" / TOOL.name
            tool.write_text(tool.read_text(encoding="utf-8").replace(
                "def not_read_paths(", "def _retired_not_read_paths("), encoding="utf-8")
            state, why = self._verdict(root)
            self.assertEqual(state, "not_satisfied", why)
            self.assertIn("not_read_paths", why)

    def test_a_door_that_always_answers_unread_is_rejected(self):
        """Мерка, отвечающая «не читает» ВСЕГДА, зачла бы любую выдумку за причину."""
        if shutil.which("node") is None:
            self.fail("НЕ ИЗМЕРЕНО — нет `node`")
        with tempfile.TemporaryDirectory() as tmp:
            root = self._contour(Path(tmp))
            tool = root / "scripts" / TOOL.name
            tool.write_text(
                tool.read_text(encoding="utf-8").replace(
                    '    return set(measure(root, want_view_shape=want_view_shape)["not_read"])',
                    '    doc = json.loads((Path(root) / SNAPSHOT_REL).read_text("utf-8"))\n'
                    '    return document_paths(doc)'),
                encoding="utf-8")
            state, why = self._verdict(root)
            self.assertEqual(state, "not_satisfied", why)
            self.assertIn("ЧИТАЮТ", why)

    def test_a_page_that_starts_reading_a_declared_path_breaks_the_criterion(self):
        """Обратная сцена: причина «не читает никто» перестаёт быть правдой."""
        if shutil.which("node") is None:
            self.fail("НЕ ИЗМЕРЕНО — нет `node`")
        with tempfile.TemporaryDirectory() as tmp:
            root = self._contour(Path(tmp))
            (root / "landing" / "src" / "pages" / "greedy.astro").write_text(
                "---\nimport snap from '../lib/snapshot_view.js';\n"
                "const x = snap.track_period.twr_pct;\n---\n<p>{x}</p>\n", encoding="utf-8")
            state, why = self._verdict(root)
            self.assertEqual(state, "not_satisfied", why)
            self.assertIn("/track_period/twr_pct", why)

    def test_a_field_absent_from_both_the_view_and_the_base_breaks_the_criterion(self):
        if shutil.which("node") is None:
            self.fail("НЕ ИЗМЕРЕНО — нет `node`")
        with tempfile.TemporaryDirectory() as tmp:
            root = self._contour(Path(tmp))
            snap_file = root / "landing" / "src" / "data" / "track_snapshot.json"
            doc = json.loads(snap_file.read_text(encoding="utf-8"))
            doc["совершенно_новое_поле"] = 1
            snap_file.write_text(json.dumps(doc), encoding="utf-8")
            state, why = self._verdict(root)
            self.assertEqual(state, "not_satisfied", why)
            self.assertIn("undefined", why)

    def test_an_exclusion_without_a_reason_breaks_the_criterion(self):
        if shutil.which("node") is None:
            self.fail("НЕ ИЗМЕРЕНО — нет `node`")
        with tempfile.TemporaryDirectory() as tmp:
            root = self._contour(Path(tmp))
            guard = root / "spa_core" / "tests" / "test_site_snapshot_view_shape.py"
            guard.write_text(guard.read_text(encoding="utf-8").replace(
                '"/anchor_equity": R_UNREAD,', '"/anchor_equity": "",'), encoding="utf-8")
            state, why = self._verdict(root)
            self.assertEqual(state, "not_satisfied", why)
            self.assertIn("без причины", why)

    def test_reasons_that_stop_citing_the_measurement_break_the_criterion(self):
        if shutil.which("node") is None:
            self.fail("НЕ ИЗМЕРЕНО — нет `node`")
        with tempfile.TemporaryDirectory() as tmp:
            root = self._contour(Path(tmp))
            guard = root / "spa_core" / "tests" / "test_site_snapshot_view_shape.py"
            guard.write_text(guard.read_text(encoding="utf-8").replace(
                "snapshot_view_field_demand.py", "так решили"), encoding="utf-8")
            state, why = self._verdict(root)
            self.assertEqual(state, "not_satisfied", why)
            self.assertIn("на словах", why)

    def test_a_tree_without_the_site_is_not_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._contour(Path(tmp))
            shutil.rmtree(root / "landing")
            state, why = self._verdict(root)
            self.assertEqual(state, "unmeasured", why)
            self.assertIn("не развёрнут", why)

    def test_a_tree_without_the_shape_guard_is_not_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._contour(Path(tmp))
            (root / "spa_core" / "tests" / "test_site_snapshot_view_shape.py").unlink()
            state, why = self._verdict(root)
            self.assertEqual(state, "unmeasured", why)
            self.assertIn("сторожа формы нет", why)

    def test_an_argument_is_refused_rather_than_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, why = self._verdict(self._contour(Path(tmp)), arg="какой-то/путь.md")
            self.assertEqual(state, "unmeasured", why)

    def test_the_probe_is_registered_under_its_name(self):
        from spa_core.monitoring.card_acceptance import PROBES
        self.assertIn("snapshot_view_exclusions_are_measured", PROBES)
