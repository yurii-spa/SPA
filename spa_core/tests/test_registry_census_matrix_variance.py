"""Приёмка ADR-1012: матрица ДВУХ объявленных входов переписи «реестр → бегун».

Заказ G1001 п. 1 (а) = ADR-1011 § 7 (а). ADR-1010 закрыл первый вход наблюдения (протокол),
ADR-1011 — второй (предел модуля). Оба ответа сняты, держа ВТОРОЙ вход неподвижным: предел
мерили при одном `aave_v3`, протокол — при одном пределе 3 с. И это не придирка к форме: тот же
замер ADR-1010 показал, что предмет `silent` протокол-ЗАВИСИМ (117…129), то есть сосед двигает
САМО НАСЕЛЕНИЕ, по которому меряется второй вход.

Смешанный зов прибор ОТКАЗЫВАЛ (ADR-1011 § 6), и отказ был ВЕРЕН: наблюдения легли бы в словарь
с ОДНИМ ключом, а молчаливый выбор «главного» входа снова мерил бы необъявленное. Матрица
отменяет не отказ, а ОДНОКЛЮЧЕВОЙ словарь — клетка несёт оба входа сразу (`cell_key`), и ответ
печатается ПО ОСЯМ.

Что держит эта батарея — по одному утверждению на класс:

* **ключ клетки несёт ОБА входа, и его неоднозначность есть ОТКАЗ** (разделитель внутри имени
  протокола), а не угаданный разбор: угадай прибор — срез отвечал бы о ЧУЖОЙ клетке;
* **предел в ключе печатает ЕДИНСТВЕННАЯ дверь** `timeout_key`: своя форма дала бы `3` и `3.0`
  двумя клетками ОДНОГО предела, то есть «наблюдений 2» из одного наблюдения;
* **матрица обязана быть ПОЛНОЙ**: у рваной срез одного протокола сравнивал бы два предела, а
  соседнего — три, и «инвариантно» первого описывало бы ДРУГОЕ население;
* **один столбец матрицей не является** — порог тот же `VARIANCE_MIN`, одна дверь на все входы;
* **НЕСУЩЕЕ: живость оси ГАТИТ «инвариантно» у КАЖДОЙ СТОРОНЫ, а не у оси целиком.** В настоящем
  замере по оси протоколов `runner_status` различается, а три оси ADR-1009 — нет, и именно их
  «инвариантно» и нуждается в доказательстве, что вход доходит до решения. ADR-1010 напечатал
  его над живым контролем — но контролем НЕНАЗВАННЫМ: живость доказывали соседние стороны того
  же наблюдения, и не скажи они ничего, то же «инвариантно» вышло бы над мёртвой проводкой;
* **внешний контроль зачитывается ТОЛЬКО своей оси** (`AXIS_KNOB_INPUT`): принять контроль
  предела за доказательство живости протокола значило бы зачесть одной оси контроль другой;
* **сравнение ПОИМЁННОЕ**, счёт — следствие (урок шестнадцати литералов «~3,3 %» при треке 5,3 %);
* **ядро сравнения ОДНО** на все три ответа (`_compare_across_values`): третья копия отвечала бы
  на свой вопрос — ровно тот класс, который прибор ловит у чужого кода;
* **неизмеренная сторона НЕ даёт оси права сказать «инвариантно» по остальным** (fail-CLOSED);
* **одиночные ответы в матричном зове НЕ выбирают клетку молча** — они называют, что ответ об
  одном входе принадлежит СРЕЗУ при названном значении соседа.

У каждого утверждения контроль в ОБЕ стороны: сцена, где прибор обязан сказать «да», и сцена,
где он обязан сказать «нет» с НАЗВАННОЙ причиной. Сверх разборных сцен стои́т СКВОЗНОЙ живой
зов: НАСТОЯЩИЙ бегун одноразового дерева зовётся по всем клеткам матрицы, и дерево устроено так,
что РАЗЛИЧИЕ существует по КАЖДОЙ из двух осей — проверка, никогда не видевшая настоящего
различия, была бы украшением (`.claude/rules/deployment.md`, § «Проверка сторожа сторожей»).
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CENSUS_PATH = ROOT / "scripts" / "registry_runner_write_census.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rrwc = _load(CENSUS_PATH, "spa_registry_runner_write_census_matrix")

_INVARIANT, _VARIES, _UNMEASURED = rrwc.PROTOCOL_VERDICTS
_KB_LIVE, _KB_DEAD, _KB_UNMEASURED = rrwc.KNOB_VERDICTS
_BY_DIFF, _BY_KNOB, _UNPROVEN = rrwc.AXIS_LIVENESS
_T_IN_P, _P_IN_T = rrwc.MATRIX_AXES
#: Слова бегуна берутся из ОБЪЯВЛЕНИЯ прибора — сцена не имеет права стать третьим местом, где
#: они живут (тот же довод, что в батареях ADR-1009/1010/1011).
_FOREIGN_TEXT = [k for k, v in rrwc.RUNNER_UNCHECKED_MARKERS.items()
                 if v == "ENTERED_RAISED_FOREIGN"][0]
_NO_ENTRY_TEXT = [k for k, v in rrwc.RUNNER_UNCHECKED_MARKERS.items()
                  if v == "NO_ENTRY_BOUND"][0]

SCENE_TIMEOUT = 2.5

RUNNER_STUB = f'''
_ENTRY_METHODS = ("analyze", "score", "run")

MODULE_TIMEOUT = {SCENE_TIMEOUT}


class _ModuleAdapter:
    def run(self, protocol, context):
        raw = self._invoke(None, context)
        if raw is UNCHECKED:
            return None, "unchecked", "{_NO_ENTRY_TEXT}"
        try:
            return 1.0, "ok", ""
        except Exception as exc:
            return None, "unchecked", (
                "{_FOREIGN_TEXT} %s; raised %s" % ("x", exc))


class SignalAggregator:
    def __init__(self, data_dir=None, module_timeout=MODULE_TIMEOUT):
        self.data_dir = data_dir
        self.module_timeout = module_timeout

    def _run_module(self, module_info, protocol, context):
        try:
            return self._bounded(module_info, protocol, context)
        except FuturesTimeout:
            self._record(module_info["module"], "timeout")
            return None, False
'''

MOD_SRC = """
    import json


    def analyze(context):
        positions = context.get("positions") or []
        head = positions[0]
        with open("out.json", "w") as fh:
            json.dump(head, fh)
        return head
"""


class Scene:
    """Разборная сцена: бегун с объявленным пределом + модули, чьи наблюдения задаёт тест.

    Наблюдения здесь ГОТОВЫЕ: предмет этой батареи — КАК прибор складывает клетки в ответ, а не
    как он их добывает (это предмет ADR-1008…1011 и сквозного зова ниже).
    """

    def __init__(self, modules=("m_one", "m_two")):
        self.tmp = tempfile.TemporaryDirectory(prefix="rrwc_matrix_scene_")
        self.root = Path(self.tmp.name)
        pkg = self.root / "spa_core" / "analytics"
        pkg.mkdir(parents=True)
        (pkg / "signal_aggregator.py").write_text(
            textwrap.dedent(RUNNER_STUB).lstrip("\n")
            + f"\n\nDEFAULT_PROTOCOLS = {list(_PROTOCOLS)!r}\n", encoding="utf-8")
        self.src = textwrap.dedent(MOD_SRC).lstrip("\n")
        self.modules = list(modules)
        for m in self.modules:
            (pkg / f"{m}.py").write_text(self.src, encoding="utf-8")

    def close(self):
        self.tmp.cleanup()

    def _line(self, needle: str) -> int:
        for i, line in enumerate(self.src.splitlines(), 1):
            if needle in line:
                return i
        raise AssertionError(f"в сцене нет строки с `{needle}`")

    def verdicts(self):
        return [rrwc.ModuleVerdict(
            module=m, tier="B", path=f"spa_core/analytics/{m}.py", registry_class=None,
            runner_target="module", entry="analyze", verdict="WRITE_REACHABLE",
            writes=[rrwc.WriteSite(func="analyze", line=self._line("json.dump(head, fh)"),
                                   form="json.dump")],
            reads_context_data_dir=False, data_dir_door="NONE") for m in self.modules]

    def census(self):
        mods = self.verdicts()
        runner = rrwc.RunnerSide(entry_methods=("analyze", "score", "run"), passes_data_dir=False,
                                 runner_path="spa_core/analytics/signal_aggregator.py")
        exposure = {}
        for axis, declared in rrwc.OBSERVED_AXES.items():
            rule = declared[1]
            if rule == "exposed":
                exposure[axis] = sum(1 for m in mods if rrwc._exposed_under_sandbox(runner, m))
            elif rule.startswith("door:"):
                door = rule.split(":", 1)[1]
                exposure[axis] = sum(1 for m in mods if m.data_dir_door == door)
            else:  # pragma: no cover — объявление оси, которого сцена не знает
                raise AssertionError(f"сцена не знает правила оси `{axis}`: {rule}")
        return rrwc.Census(root=str(self.root), runner=runner, modules=mods,
                           counts={"WRITE_REACHABLE": len(mods)}, exposure=exposure,
                           blind_subset=None, code=1)

    def obs(self, rows):
        """rows = [(модуль, статус)] — одна клетка матрицы."""
        per_module, statuses = [], {}
        for module, status in rows:
            statuses[status] = statuses.get(status, 0) + 1
            per_module.append({"module": module, "status": status,
                               "detail": _FOREIGN_TEXT + " a" if status == "unchecked" else "",
                               "seconds": 0.001, "lines": [self._line("head = positions[0]")],
                               "written": {"runner_dir": [], "tree_data": [], "cwd_data": []}})
        return {"repo": str(self.root) + "_copy", "protocol": "?", "timeout": SCENE_TIMEOUT,
                "modules": len(rows), "statuses": statuses, "baskets": {}, "writers": [],
                "per_module": per_module, "elsewhere_in_tree": [], "parity": {},
                "observer_returncode": 0, "observer_stderr_tail": ""}

    def ask(self, by_cell, knob=None):
        return rrwc.matrix_variance(self.root, self.census(), by_cell, knob)


_PROTOCOLS = ("p_one", "p_two")
_T_LOW, _T_HIGH = 1.0, 9.0


def _knob(verdict):
    """Готовый ответ контроля — чтобы сцены сравнения не платили за подпроцесс."""
    base = {"verdict": verdict, "expected_status": "timeout", "sides": {}, "sleep_s": 0.3,
            "below_s": 0.05, "above_s": 2.0, "dead_reason": None, "unmeasured_reason": None}
    if verdict == _KB_DEAD:
        base["dead_reason"] = "предел на решение бегуна НЕ ВЛИЯЕТ так, как объявлено"
    elif verdict == _KB_UNMEASURED:
        base["unmeasured_reason"] = "сцена контроля не отдала результата"
    return base


def _square(scene, rows_of):
    """Полная матрица 2×2: `rows_of(протокол, предел)` отдаёт строки наблюдения клетки."""
    return {rrwc.cell_key(p, t): scene.obs(rows_of(p, t))
            for p in _PROTOCOLS for t in (_T_LOW, _T_HIGH)}


def _side(mx, name, axis):
    assert name in mx["sides"], sorted(mx["sides"])
    return mx["sides"][name][axis]


# ───────────── ключ клетки: ОБА входа одной дверью ─────────────

class TestTheCellKeyCarriesBothInputs(unittest.TestCase):
    def test_round_trip(self):
        key = rrwc.cell_key("aave_v3", 3.0)
        self.assertEqual(rrwc.split_cell_key(key), ("aave_v3", rrwc.timeout_key(3.0)))

    def test_the_timeout_part_is_made_by_the_single_door(self):
        """`3` и `3.0` — ОДИН предел. Своя форма записи дала бы две клетки одного предела, то
        есть «наблюдений 2» из одного наблюдения, и различие сравнивалось бы с самим собой."""
        self.assertEqual(rrwc.cell_key("p", 3), rrwc.cell_key("p", 3.0))
        self.assertTrue(rrwc.cell_key("p", 3).endswith(rrwc.timeout_key(3)))

    def test_a_protocol_carrying_the_separator_is_a_REFUSAL(self):
        """Угаданный разбор заставил бы срез отвечать о ЧУЖОЙ клетке — ровно тот молчаливый
        выбор, от которого отказывался ADR-1011 § 6."""
        with self.assertRaises(rrwc.NotMeasured) as ctx:
            rrwc.cell_key(f"aa{rrwc.MATRIX_CELL_SEP}ve", 3.0)
        self.assertIn(rrwc.MATRIX_CELL_SEP, str(ctx.exception))

    def test_an_empty_protocol_is_a_REFUSAL(self):
        with self.assertRaises(rrwc.NotMeasured):
            rrwc.cell_key("   ", 3.0)

    def test_a_key_without_the_separator_is_a_REFUSAL(self):
        with self.assertRaises(rrwc.NotMeasured):
            rrwc.split_cell_key("aave_v3")

    def test_a_key_whose_tail_is_not_a_timeout_is_a_REFUSAL(self):
        with self.assertRaises(rrwc.NotMeasured) as ctx:
            rrwc.split_cell_key(f"aave_v3{rrwc.MATRIX_CELL_SEP}fast")
        self.assertIn("fast", str(ctx.exception))

    def test_a_key_without_a_protocol_is_a_REFUSAL(self):
        with self.assertRaises(rrwc.NotMeasured):
            rrwc.split_cell_key(f"{rrwc.MATRIX_CELL_SEP}3.0")


# ───────────── матрица обязана быть ПОЛНОЙ и не из одного столбца ─────────────

class TestTheMatrixMustBeWholeAndTwoSided(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def tearDown(self):
        self.s.close()

    def _same(self, p, t):
        return [(m, "ok") for m in self.s.modules]

    def test_a_full_square_does_answer(self):
        mx = self.s.ask(_square(self.s, self._same), _knob(_KB_LIVE))
        self.assertEqual(mx["cells"], 4)
        self.assertEqual(mx["protocols"], sorted(_PROTOCOLS))
        self.assertEqual(mx["axes"][_T_IN_P]["verdict"], _INVARIANT)

    def test_a_RAGGED_matrix_is_UNMEASURED_with_the_hole_NAMED(self):
        """У рваной матрицы срез одного протокола сравнивал бы меньше значений, чем у соседнего,
        и «инвариантно» первого описывало бы ДРУГОЕ население."""
        cells = _square(self.s, self._same)
        missing = rrwc.cell_key(_PROTOCOLS[1], _T_HIGH)
        cells.pop(missing)
        mx = self.s.ask(cells, _knob(_KB_LIVE))
        self.assertEqual(mx["verdict"], _UNMEASURED)
        self.assertIn("РВАНАЯ", mx["unmeasured_reason"])
        self.assertIn(missing, mx["unmeasured_reason"])
        self.assertEqual(mx["axes"], {})

    def test_an_unparsable_cell_key_is_UNMEASURED(self):
        cells = _square(self.s, self._same)
        cells["protocol_without_a_timeout"] = cells[rrwc.cell_key(_PROTOCOLS[0], _T_LOW)]
        mx = self.s.ask(cells, _knob(_KB_LIVE))
        self.assertEqual(mx["verdict"], _UNMEASURED)
        self.assertIn("protocol_without_a_timeout", mx["unmeasured_reason"])

    def test_one_protocol_is_NOT_a_matrix(self):
        cells = {rrwc.cell_key(_PROTOCOLS[0], t): self.s.obs(self._same(None, t))
                 for t in (_T_LOW, _T_HIGH)}
        mx = self.s.ask(cells, _knob(_KB_LIVE))
        self.assertEqual(mx["verdict"], _UNMEASURED)
        self.assertIn("протоколов", mx["unmeasured_reason"])
        self.assertIn(str(rrwc.VARIANCE_MIN), mx["unmeasured_reason"])

    def test_one_timeout_is_NOT_a_matrix(self):
        cells = {rrwc.cell_key(p, _T_LOW): self.s.obs(self._same(p, None)) for p in _PROTOCOLS}
        mx = self.s.ask(cells, _knob(_KB_LIVE))
        self.assertEqual(mx["verdict"], _UNMEASURED)
        self.assertIn("пределов", mx["unmeasured_reason"])

    def test_no_cells_at_all_has_its_OWN_reason(self):
        mx = self.s.ask(None, _knob(_KB_LIVE))
        self.assertEqual(mx["verdict"], _UNMEASURED)
        self.assertIn("--protocols", mx["unmeasured_reason"])
        self.assertIn("--timeouts", mx["unmeasured_reason"])

    def test_the_threshold_is_the_SAME_single_door(self):
        """Порог принадлежит ВОПРОСУ «различается ли», а не входу и не матрице: вторая копия
        числа была бы ровно тем дефектом, который прибор и ловит."""
        self.assertEqual(rrwc.VARIANCE_MIN, rrwc.PROTOCOL_VARIANCE_MIN)
        src = CENSUS_PATH.read_text(encoding="utf-8")
        self.assertEqual(src.count("VARIANCE_MIN = PROTOCOL_VARIANCE_MIN"), 1)
        # и матрица меряет ТЕМ ЖЕ порогом, а не своей копией числа
        matrix = src.split("def matrix_variance(")[1].split("\ndef ")[0]
        self.assertIn("VARIANCE_MIN", matrix)
        self.assertNotIn(f"< {rrwc.VARIANCE_MIN}", matrix)


# ───────────── НЕСУЩЕЕ: живость оси гатит «инвариантно» у КАЖДОЙ СТОРОНЫ ─────────────

class TestInvarianceOfASideMustEarnItsPrint(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def tearDown(self):
        self.s.close()

    def _all_same(self, p, t):
        return [(m, "ok") for m in self.s.modules]

    def _protocol_moves(self, p, t):
        """Статус зависит ТОЛЬКО от протокола — различие по оси протоколов, и только по ней."""
        return [(self.s.modules[0], "ok" if p == _PROTOCOLS[0] else "dormant")] + \
               [(m, "ok") for m in self.s.modules[1:]]

    def test_identical_sides_with_a_LIVE_knob_are_INVARIANT_on_the_timeout_axis(self):
        mx = self.s.ask(_square(self.s, self._all_same), _knob(_KB_LIVE))
        self.assertEqual(mx["axes"][_T_IN_P]["liveness"], _BY_KNOB)
        self.assertEqual(mx["axes"][_T_IN_P]["verdict"], _INVARIANT)
        self.assertEqual(_side(mx, "runner_status", _T_IN_P)["verdict"], _INVARIANT)

    def test_the_SAME_data_with_a_DEAD_knob_is_UNMEASURED(self):
        """Положительный контроль теста выше, и это несущая половина решения: наблюдения те же
        до байта, различается РОВНО ответ контроля входа."""
        mx = self.s.ask(_square(self.s, self._all_same), _knob(_KB_DEAD))
        self.assertEqual(mx["axes"][_T_IN_P]["liveness"], _UNPROVEN)
        self.assertEqual(mx["axes"][_T_IN_P]["verdict"], _UNMEASURED)
        self.assertEqual(_side(mx, "runner_status", _T_IN_P)["verdict"], _UNMEASURED)
        self.assertIn("живость оси НЕ ДОКАЗАНА",
                      _side(mx, "runner_status", _T_IN_P)["unmeasured_reason"])

    def test_an_UNMEASURED_knob_is_also_UNMEASURED_not_invariant(self):
        mx = self.s.ask(_square(self.s, self._all_same), _knob(_KB_UNMEASURED))
        self.assertEqual(mx["axes"][_T_IN_P]["verdict"], _UNMEASURED)

    def test_no_knob_at_all_is_UNMEASURED_with_its_own_reason(self):
        mx = self.s.ask(_square(self.s, self._all_same), None)
        self.assertEqual(mx["axes"][_T_IN_P]["verdict"], _UNMEASURED)
        self.assertIn("контроль входа не запускался",
                      mx["axes"][_T_IN_P]["unmeasured_reason"])

    def test_the_PROTOCOL_axis_does_NOT_get_to_use_the_timeout_knob(self):
        """Зачесть одной оси контроль ДРУГОЙ — тот же дефект, что сверить свою константу с
        собой: у протокола внешнего контроля прибор не имеет вовсе, и это сказано вслух."""
        mx = self.s.ask(_square(self.s, self._all_same), _knob(_KB_LIVE))
        self.assertEqual(mx["axes"][_P_IN_T]["liveness"], _UNPROVEN)
        self.assertEqual(mx["axes"][_P_IN_T]["verdict"], _UNMEASURED)
        self.assertIn("внешнего контроля у этого входа",
                      mx["axes"][_P_IN_T]["liveness_reason"])
        self.assertEqual(rrwc.AXIS_KNOB_INPUT.get(_P_IN_T), None)

    def test_a_DIFFERING_side_proves_the_axis_live_and_EARNS_the_others_INVARIANT(self):
        """Ровно форма настоящего замера ADR-1010: по оси протоколов `runner_status` различается,
        а оси ADR-1009 — нет. Живость входа доказывают СОСЕДНИЕ стороны того же наблюдения, и
        ADR-1010 напечатал «инвариантно» над этим контролем, НЕ НАЗВАВ его."""
        mx = self.s.ask(_square(self.s, self._protocol_moves), _knob(_KB_UNMEASURED))
        axis = mx["axes"][_P_IN_T]
        self.assertEqual(axis["liveness"], _BY_DIFF)
        self.assertIn("runner_status", axis["liveness_reason"])
        self.assertEqual(axis["verdict"], _VARIES)
        self.assertEqual(_side(mx, "runner_status", _P_IN_T)["verdict"], _VARIES)
        # и вот ЭТО — заработанная инвариантность соседней стороны: контроль у неё есть, и он
        # назван, хотя собственного различия у неё нет ни одного.
        self.assertEqual(_side(mx, "unentered:door_unresolved", _P_IN_T)["verdict"], _INVARIANT)

    def test_without_that_differing_side_the_SAME_neighbours_become_UNMEASURED(self):
        """Обратная сторона теста выше: уберите различие — и «инвариантно» соседей исчезает,
        потому что доказывать живость входа становится нечем. Наблюдения различаются РОВНО
        статусом одного модуля."""
        mx = self.s.ask(_square(self.s, self._all_same), _knob(_KB_UNMEASURED))
        self.assertEqual(mx["axes"][_P_IN_T]["liveness"], _UNPROVEN)
        self.assertEqual(_side(mx, "unentered:door_unresolved", _P_IN_T)["verdict"], _UNMEASURED)

    def test_a_difference_does_not_need_the_knob_at_all(self):
        """Названное различие само и есть доказательство, что вход доходит до решения."""
        mx = self.s.ask(_square(self.s, self._protocol_moves), None)
        self.assertEqual(mx["axes"][_P_IN_T]["verdict"], _VARIES)


# ───────────── ПОИМЁННО, а не по счётам ─────────────

class TestNamesNotCounts(unittest.TestCase):
    def setUp(self):
        self.s = Scene(modules=("m_one", "m_two", "m_three"))

    def tearDown(self):
        self.s.close()

    def test_equal_counts_with_DIFFERENT_modules_is_VARIES(self):
        """Счёта равны у всех клеток, а модули разные. Сравнение счётов дало бы «инвариантно» —
        ровно зелёный ответ сторожа на СВОЙ вопрос (шестнадцать литералов «~3,3 %»)."""
        def rows(p, t):
            quiet = self.s.modules[0] if p == _PROTOCOLS[0] else self.s.modules[1]
            return [(m, "dormant" if m == quiet else "ok") for m in self.s.modules]
        mx = self.s.ask(_square(self.s, rows), _knob(_KB_LIVE))
        side = _side(mx, "runner_status", _P_IN_T)
        self.assertEqual(side["verdict"], _VARIES)
        for fixed in side["slices_varying"]:
            s = side["slices"][fixed]
            self.assertEqual(set(s["subject"].values()), {len(self.s.modules)})
            self.assertTrue(s["differences"][rrwc._PD_DIFFERS])
            self.assertIn(self.s.modules[0],
                          [e["module"] for e in s["differences"][rrwc._PD_DIFFERS]])

    def test_a_subject_that_MOVES_is_named_as_a_move(self):
        """`silent` — сторона, у которой двигается САМО НАСЕЛЕНИЕ (так и было в ADR-1010:
        12 модулей входят в предмет под одними протоколами и не входят под другими)."""
        def rows(p, t):
            # «вошёл и промолчал» у модуля есть только под ВТОРЫМ протоколом
            return [(m, "ok" if (p == _PROTOCOLS[1] or m != self.s.modules[0]) else "unchecked")
                    for m in self.s.modules]
        mx = self.s.ask(_square(self.s, rows), _knob(_KB_LIVE))
        moved = [e["module"] for fixed in _side(mx, "silent", _P_IN_T)["slices_varying"]
                 for e in _side(mx, "silent", _P_IN_T)["slices"][fixed]
                 ["differences"][rrwc._PD_MOVED]]
        self.assertIn(self.s.modules[0], moved)


# ───────────── fail-CLOSED: неизмеренная сторона не покупает «инвариантно» ─────────────

class TestAnUnmeasuredSideClosesTheAxis(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self._saved = rrwc.PROTOCOL_SIDES

    def tearDown(self):
        rrwc.PROTOCOL_SIDES = self._saved
        self.s.close()

    def test_a_side_that_does_not_parse_names_the_CELL_and_closes_the_axis(self):
        rrwc.PROTOCOL_SIDES = ("runner_status", "side_the_instrument_does_not_know")
        mx = self.s.ask(_square(self.s, lambda p, t: [(m, "ok") for m in self.s.modules]),
                        _knob(_KB_LIVE))
        for axis in rrwc.MATRIX_AXES:
            self.assertEqual(mx["axes"][axis]["verdict"], _UNMEASURED, axis)
            reason = mx["axes"][axis]["unmeasured_reason"]
            self.assertIn("клетка `", reason)
            self.assertIn("side_the_instrument_does_not_know", reason)
        # и соседняя сторона, которая РАЗОБРАЛАСЬ, своего ответа не теряет
        self.assertEqual(_side(mx, "runner_status", _T_IN_P)["verdict"], _INVARIANT)


# ───────────── одно ядро, одни двери ─────────────

class TestOneCoreOneDoor(unittest.TestCase):
    def setUp(self):
        self.src = CENSUS_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.src)

    def _calls_in(self, func_name):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                return {c.func.id for c in ast.walk(node)
                        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        raise AssertionError(f"в приборе нет функции `{func_name}`")

    def test_all_THREE_answers_call_the_same_core(self):
        for owner in ("protocol_variance", "timeout_variance", "matrix_variance"):
            self.assertIn("_compare_across_values", self._calls_in(owner), owner)

    def test_there_is_still_no_second_comparison_core(self):
        names = [n.name for n in ast.walk(self.tree)
                 if isinstance(n, ast.FunctionDef) and "_compare_across" in n.name]
        self.assertEqual(names, ["_compare_across_values"], names)

    def test_the_cell_key_is_the_only_place_that_joins_the_two_inputs(self):
        """Сложение ключа руками мимо двери вернуло бы `3` и `3.0` двумя клетками. Сторож
        намеренно ГРУБЫЙ: ошибаться обязан в сторону находки."""
        names = [n.name for n in ast.walk(self.tree)
                 if isinstance(n, ast.FunctionDef) and n.name in ("cell_key", "split_cell_key")]
        self.assertEqual(sorted(names), ["cell_key", "split_cell_key"])
        self.assertEqual(self._calls_in("cell_key"), {"str", "NotMeasured", "timeout_key"})

    def test_declared_is_parsed_by_ONE_door_for_both_calls(self):
        """`declared` читается `_parse_timeouts`, и зовут её ОБА зова — одиночный и матричный.
        Вторая копия разбора дала бы `declared` два разных значения в одном приборе."""
        self.assertEqual(self.src.count("def _parse_timeouts("), 1)
        main_calls = [c for c in ast.walk([n for n in ast.walk(self.tree)
                                           if isinstance(n, ast.FunctionDef)
                                           and n.name == "main"][0])
                      if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                      and c.func.id == "_parse_timeouts"]
        self.assertEqual(len(main_calls), 2, len(main_calls))

    def test_the_axes_are_declared_once_and_read_from_the_declaration(self):
        self.assertEqual(len(rrwc.MATRIX_AXES), 2)
        self.assertIn("for axis in MATRIX_AXES", self.src)


# ───────────── одиночные ответы в матричном зове не выбирают клетку молча ─────────────

class TestSingleInputAnswersDoNotPICKACellSilently(unittest.TestCase):
    def test_both_single_answers_name_the_matrix_instead_of_a_cell(self):
        pv = rrwc.protocol_variance(ROOT, None, None,
                                    absent_reason=rrwc._MATRIX_ABSENT_REASON)
        tv = rrwc.timeout_variance(ROOT, None, None, None,
                                   absent_reason=rrwc._MATRIX_ABSENT_REASON)
        for res in (pv, tv):
            self.assertEqual(res["verdict"], _UNMEASURED)
            self.assertIn("МАТРИЦЕЙ", res["unmeasured_reason"])
            self.assertIn("slices", res["unmeasured_reason"])

    def test_without_the_matrix_they_keep_their_OWN_reason(self):
        """Контроль предпосылки теста выше: без матричного зова причина ДРУГАЯ. Совпади они —
        тест выше не мерил бы ничего."""
        pv = rrwc.protocol_variance(ROOT, None, None)
        self.assertIn("--observe", pv["unmeasured_reason"])
        self.assertNotIn("МАТРИЦЕЙ", pv["unmeasured_reason"])


# ───────────── охват ответа печатается ПРИ ЛЮБОМ вердикте ─────────────

class TestTheMatrixSaysWhatItIsAnAnswerAbout(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def tearDown(self):
        self.s.close()

    def _mx(self, timeouts, knob=_KB_LIVE):
        cells = {rrwc.cell_key(p, t): self.s.obs([(m, "ok") for m in self.s.modules])
                 for p in _PROTOCOLS for t in timeouts}
        return self.s.ask(cells, _knob(knob))

    def test_the_declared_limit_INSIDE_the_observed_set_is_said_aloud(self):
        mx = self._mx((SCENE_TIMEOUT, _T_HIGH))
        self.assertEqual(mx["declared_timeout"], SCENE_TIMEOUT)
        self.assertIs(mx["declared_timeout_observed"], True)
        self.assertIn("СРЕДИ наблюдённых", "\n".join(rrwc.render_matrix_variance(mx)))

    def test_the_declared_limit_OUTSIDE_the_observed_set_is_said_aloud_too(self):
        """Ответ принадлежит наблюдённым пределам, а не тому, которым бегун живёт. Молчание тут
        выдало бы ответ о чужих пределах за ответ о дереве."""
        mx = self._mx((_T_LOW, _T_HIGH))
        self.assertIs(mx["declared_timeout_observed"], False)
        self.assertIn("среди наблюдённых ЕГО НЕТ", "\n".join(rrwc.render_matrix_variance(mx)))

    def test_declared_protocols_not_observed_are_NAMED(self):
        mx = self._mx((_T_LOW, _T_HIGH))
        self.assertEqual(mx["declared_protocols"], list(_PROTOCOLS))
        self.assertEqual(mx["declared_protocols_not_observed"], [])
        self.assertEqual(mx["observed_protocols_not_declared"], [])

    def test_a_runner_without_the_protocol_declaration_closes_the_matrix(self):
        """Перечень читается У БЕГУНА: без объявления нельзя сказать, о каких входах ответ."""
        runner = self.s.root / "spa_core" / "analytics" / "signal_aggregator.py"
        runner.write_text(runner.read_text(encoding="utf-8").replace(
            "DEFAULT_PROTOCOLS = ", "OTHER_NAME = "), encoding="utf-8")
        mx = self._mx((_T_LOW, _T_HIGH))
        self.assertEqual(mx["verdict"], _UNMEASURED)
        self.assertIn("объявление бегуна не прочитано", mx["unmeasured_reason"])

    def test_render_of_a_VARIES_axis_names_the_axis_liveness_and_the_slice(self):
        def rows(p, t):
            return [(self.s.modules[0], "ok" if p == _PROTOCOLS[0] else "dormant")] + \
                   [(m, "ok") for m in self.s.modules[1:]]
        text = "\n".join(rrwc.render_matrix_variance(
            self.s.ask(_square(self.s, rows), _knob(_KB_LIVE))))
        self.assertIn(_BY_DIFF, text)
        self.assertIn("runner_status", text)
        self.assertIn("LABEL_DIFFERS", text)

    def test_render_of_an_UNMEASURED_matrix_prints_its_reason(self):
        text = "\n".join(rrwc.render_matrix_variance(self.s.ask(None, _knob(_KB_LIVE))))
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertIn("--protocols", text)


# ───────────── предел — вход НАБЛЮДЕНИЯ, и спрашивается только при нём ─────────────

class TestTheLimitIsAskedOnlyWhenObserving(unittest.TestCase):
    """Находка цикла #1134, попутная матрице (и нашла её не глазами, а соседняя батарея).

    ADR-1011 убрал у прибора умолчание-литерал предела — верно. Но читался предел БЕЗУСЛОВНО, до
    всякого наблюдения, и дерево без объявления `MODULE_TIMEOUT` получало код 2 даже на чисто
    СТАТИЧЕСКИЙ вопрос, которому предел не нужен ни для чего: «НЕ ИЗМЕРЕНО» печаталось о том,
    чего не спрашивали. Красным это держало `test_main_prints_three_outcomes_and_returns_the_code`
    в `test_registry_runner_write_census.py` — то есть у находки был ЧИТАТЕЛЬ, и он молчал
    ровно один цикл.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rrwc_no_limit_")
        root = Path(self.tmp.name)
        pkg = root / "spa_core" / "analytics"
        pkg.mkdir(parents=True)
        # бегун БЕЗ объявления предела — всё прочее на месте
        (pkg / "signal_aggregator.py").write_text(textwrap.dedent('''
            _ENTRY_METHODS = ("analyze", "score", "run")


            class SignalAggregator:
                pass
            ''').lstrip("\n"), encoding="utf-8")
        (pkg / "_module_registry.py").write_text(
            'TIER_A_MODULES = [{"module": "m_one", "tier": "A"}]' + chr(10),
            encoding="utf-8")
        (pkg / "m_one.py").write_text(textwrap.dedent('''
            import json


            def analyze(context):
                with open("out.json", "w") as fh:
                    json.dump(1, fh)
            ''').lstrip("\n"), encoding="utf-8")
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *extra):
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = rrwc.main(["--repo-root", str(self.root), *extra])
        return code, buf.getvalue(), err.getvalue()

    def test_a_static_question_is_ANSWERED_without_any_declared_limit(self):
        code, out, err = self._run()
        self.assertIn(code, (0, 1), out)
        self.assertNotIn(rrwc.RUNNER_TIMEOUT_NAME, out)
        self.assertNotIn("предел не назван", err)

    def test_but_an_OBSERVING_question_still_refuses_with_the_named_reason(self):
        """Положительный контроль теста выше: ослабления нет — как только предел становится
        нужен, его отсутствие остаётся НЕ ИЗМЕРЕНО с названной причиной."""
        code, out, _ = self._run("--observe", str(self.root))
        self.assertEqual(code, 2)
        self.assertIn(rrwc.RUNNER_TIMEOUT_NAME, out)


# ───────────── СКВОЗНОЙ ЖИВОЙ ЗОВ: настоящий бегун по всем клеткам ─────────────

LIVE_RUNNER = '''
import importlib
import threading


class FuturesTimeout(Exception):
    pass


_ENTRY_METHODS = ("analyze", "score", "run")

MODULE_TIMEOUT = 2.0

DEFAULT_PROTOCOLS = ["p_fast", "p_raise"]


class SignalAggregator:
    def __init__(self, data_dir=None, module_timeout=MODULE_TIMEOUT):
        self.data_dir = data_dir
        self.module_timeout = module_timeout
        self._log = []

    def _record(self, module, status, detail=""):
        self._log.append({"module": module, "status": status, "detail": detail})

    def _call(self, info, protocol, context, box, done):
        try:
            mod = importlib.import_module("spa_core.analytics." + info["module"])
            box["r"] = mod.analyze(protocol, context)
        except Exception as exc:
            box["exc"] = exc
        done.set()

    def _run_module(self, info, protocol, context):
        done, box = threading.Event(), {}
        threading.Thread(target=self._call,
                         args=(info, protocol, context, box, done), daemon=True).start()
        try:
            if not done.wait(self.module_timeout):
                raise FuturesTimeout("module exceeded")
        except FuturesTimeout:
            self._record(info["module"], "timeout")
            return None, False
        if "exc" in box:
            self._record(info["module"], "failed", str(box["exc"]))
            return None, False
        self._record(info["module"], "ok")
        return box.get("r"), True
'''

#: Модуль, который СПИТ: его статус решает ПРЕДЕЛ (ось `timeout_within_protocol`).
LIVE_MOD_SLOW = '''
import time


def analyze(protocol, context):
    time.sleep(0.30)
    return 1.0
'''

#: Модуль, который падает под ОДНИМ протоколом: его статус решает ПРОТОКОЛ (ось
#: `protocol_within_timeout`). Два различия НЕЗАВИСИМЫ — иначе одна сцена отвечала бы об обеих
#: осях сразу, и «различие нашлось» не говорило бы, по какой из них.
LIVE_MOD_PROTO = '''
def analyze(protocol, context):
    if protocol == "p_raise":
        raise RuntimeError("this protocol is refused by the module")
    return 2.0
'''

LIVE_REGISTRY = '''
TIER_A_MODULES = [
    {"module": "m_slow", "tier": "A"},
    {"module": "m_proto", "tier": "A"},
]
'''


class TestTheMatrixOnARealRunner(unittest.TestCase):
    """Сквозной зов: НАСТОЯЩИЙ бегун одноразового дерева зовётся по всем четырём клеткам.

    Дерево устроено так, что различие СУЩЕСТВУЕТ по КАЖДОЙ из двух осей и различия НЕЗАВИСИМЫ:
    проверка, никогда не видевшая настоящего различия, была бы украшением.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rrwc_matrix_live_")
        root = Path(self.tmp.name)
        pkg = root / "spa_core" / "analytics"
        pkg.mkdir(parents=True)
        (root / "spa_core" / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        for rel, src in (("signal_aggregator.py", LIVE_RUNNER),
                         ("_module_registry.py", LIVE_REGISTRY),
                         ("m_slow.py", LIVE_MOD_SLOW),
                         ("m_proto.py", LIVE_MOD_PROTO)):
            (pkg / rel).write_text(textwrap.dedent(src).lstrip("\n"), encoding="utf-8")
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *extra):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = rrwc.main(["--repo-root", str(self.root), "--observe", str(self.root),
                              "--json", *extra])
        return code, json.loads(buf.getvalue())

    def test_the_mixed_call_is_MEASURED_and_both_axes_answer(self):
        """ADR-1011 § 6 отказывал этому зову, и отказ был верен для словаря с ОДНИМ ключом.
        Теперь ключ несёт оба входа, и отказ снят ОСОЗНАННО (инв. #16: обоснование — здесь,
        запись — в журнале W46 цикла #1134)."""
        code, doc = self._run("--protocols", "all", "--timeouts", "declared,0.05")
        self.assertIn(code, (0, 1), doc.get("unmeasured_reason"))
        mx = doc["matrix_variance"]
        self.assertEqual(mx["cells"], 4, mx.get("unmeasured_reason"))
        self.assertEqual(mx["protocols"], ["p_fast", "p_raise"])
        # ось ПРЕДЕЛА: спящий модуль пересекает 0.05 с и не пересекает 2.0 с
        t_side = _side(mx, "runner_status", _T_IN_P)
        self.assertEqual(t_side["verdict"], _VARIES)
        self.assertEqual(sorted(t_side["slices_varying"]), ["p_fast", "p_raise"])
        self.assertIn("m_slow", [e["module"] for f in t_side["slices_varying"]
                                 for e in t_side["slices"][f]["differences"][rrwc._PD_DIFFERS]])
        # ось ПРОТОКОЛА: падающий модуль различается под тем же пределом
        p_side = _side(mx, "runner_status", _P_IN_T)
        self.assertEqual(p_side["verdict"], _VARIES)
        self.assertIn("m_proto", [e["module"] for f in p_side["slices_varying"]
                                  for e in p_side["slices"][f]["differences"][rrwc._PD_DIFFERS]])
        # различия НЕЗАВИСИМЫ: каждая ось назвала СВОЙ модуль, и не чужой
        self.assertNotIn("m_proto", [e["module"] for f in t_side["slices_varying"]
                                     for e in t_side["slices"][f]
                                     ["differences"][rrwc._PD_DIFFERS]])

    def test_in_matrix_mode_the_single_answers_NAME_the_matrix_instead_of_a_cell(self):
        """Выжившая мутация M14 (цикл #1134): проводка не проверялась ничем. Утверждение про
        `absent_reason` стояло у самой функции, а `main` мог молча передать ей первую клетку —
        и обе сцены ответили бы одинаково. Разбора без РАЗЛИЧАЮЩЕЙ сцены не бывает: здесь зов
        идёт через `main`, то есть судится ПРОВОДКА, а не умение функции."""
        code, doc = self._run("--protocols", "all", "--timeouts", "declared,0.05")
        self.assertIn(code, (0, 1), doc.get("unmeasured_reason"))
        for key in ("protocol_variance", "timeout_variance"):
            self.assertEqual(doc[key]["verdict"], _UNMEASURED, key)
            self.assertIn("МАТРИЦЕЙ", doc[key]["unmeasured_reason"], key)
        # и наблюдения одиночных ключей в документ НЕ попадают — выбирать нечего
        self.assertNotIn("observations", doc)
        self.assertNotIn("observations_by_timeout", doc)
        self.assertEqual(len(doc["observations_by_cell"]), 4)

    def test_the_single_input_calls_still_work_on_the_same_tree(self):
        """Контроль предпосылки: матричный зов не сломал одиночные — на ТОМ ЖЕ дереве ответ о
        пределе снимается прежним путём и находит ТОТ ЖЕ модуль."""
        code, doc = self._run("--timeouts", "declared,0.05", "--protocol", "p_fast")
        self.assertIn(code, (0, 1), doc.get("unmeasured_reason"))
        tv = doc["timeout_variance"]
        self.assertEqual(tv["sides"]["runner_status"]["verdict"], _VARIES)
        self.assertEqual(doc["matrix_variance"]["verdict"], _UNMEASURED)
        self.assertIn("--protocols", doc["matrix_variance"]["unmeasured_reason"])


if __name__ == "__main__":
    unittest.main()
