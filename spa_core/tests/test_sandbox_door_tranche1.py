"""ADR-1000 (цикл #1119) — транш 1 раскатки двери песочницы (ADR-999 § 3.2): 49 точек входа
с достижимым умолчанием каталога данных у руки получают `refuse_if_sandbox_leaks` после
`parse_args` (или после разрешения умолчания) и ДО первой записи.

Что меряется — ИСХОД, не структура (ADR-333):

* **Сцена A (каждая точка входа, НАСТОЯЩАЯ дверь):** маркер `SPA_SANDBOX=1` + каталог в
  прод-дереве (прод — одноразовый каталог, `DEFAULT_LIVE_ROOT` подменён) ⇒ процесс выходит
  кодом 2, причина в stderr названа, в прод-`data/` не появилось НИ ОДНОГО файла. Точка
  входа исполняется так, как её зовёт рука — через `__main__` (`runpy`), а не вызовом
  функции по имени: иначе дверь, определённая в файле, но не позванная с пути от входа
  («половина инъекции», ADR-932), прошла бы проверку.
* **Сцена B (каждая):** маркера нет + прод-каталог ⇒ дверь молчит, и точка входа отдала ей
  РОВНО ТОТ путь, что назван флагом, и СВОЁ имя (`who`). Боевой путь не меняется.
* **Сцена C (каждая):** маркер + чужой каталог ⇒ дверь молчит (правильно сконфигурированная
  песочница проходит).
* **Сцена D (шесть точек с умолчанием-fallback):** флаг не назван ⇒ дверь получила
  РАЗРЕШЁННОЕ умолчание, а не `None` («ничего» судить нельзя — инв. #17).
* **Перепись (исход заказа G988 п. 1а):** `sandbox_data_dir_census` читает у всех 49 `DOOR`
  (дверь достигается от входа), у читателей `uncalled == 0` и рука/промпт `== 0`.
* **Отрицательный контроль:** та же точка входа с закомментированной строкой двери — не `DOOR`.

Сцены B/C/D ловят дверь спаем, который зовёт НАСТОЯЩУЮ `refuse_if_sandbox_leaks` и затем
останавливает точку входа (`_DoorReached`, потомок `BaseException` — `except Exception` его не
глотает): прогонять тяжёлую работу 49 программ ради «дверь не сработала» не нужно и нельзя
(сеть, git, минуты).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import runpy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (путь, род флага: root → корень, data → каталог данных, out → каталог вывода; флаг; доп. argv; fallback-умолчание)
TRANCHE = [
    ("scripts/adr_number.py", "root", "--root", ["next"], False),
    ("scripts/build_acceptance_tree.py", "root", "--repo-root", [], False),
    ("scripts/build_dd_snapshot.py", "out", "--out-dir", [], True),
    ("scripts/check_owner_order_starvation.py", "data", "--data-dir", [], True),
    ("scripts/edge_lst_yield_persistence.py", "data", "--data-dir", [], False),
    ("scripts/edge_pt_fixed_vs_float.py", "data", "--data-dir", [], False),
    ("scripts/edge_pt_term_structure.py", "data", "--data-dir", [], False),
    ("scripts/edge_tuw_unsmooth.py", "data", "--data-dir", [], False),
    ("scripts/edge_weekday_loss_gate.py", "data", "--data-dir", [], False),
    ("scripts/fix_fabricated_evidence.py", "data", "--data-dir", [], False),
    ("scripts/git_path_coordinate_census.py", "root", "--root", [], True),
    ("scripts/measure_pin_placement_effect.py", "data", "--data-dir", [], False),
    ("scripts/mutation_gate.py", "root", "--repo-root", [], True),
    ("scripts/reap_stale_worktrees.py", "root", "--root", [], True),
    ("scripts/refresh_no_regression_census.py", "root", "--repo-root", [], False),
    ("scripts/run_backtest_real.py", "data", "--data-dir", [], False),
    ("scripts/seed_test_fixtures.py", "out", "--out-dir", [], False),
    ("scripts/unfinished_work_census.py", "root", "--repo-root", [], False),
    ("spa_core/monitoring/absent_path_probe.py", "root", "--root", [], False),
    ("spa_core/monitoring/agent_health_monitor.py", "data", "--data-dir", [], False),
    ("spa_core/monitoring/card_delivery.py", "root", "--root", [], False),
    ("spa_core/monitoring/cio_auto_execution_limits.py", "root", "--root", [], False),
    ("spa_core/monitoring/competitive_watch.py", "data", "--data-dir", [], False),
    ("spa_core/monitoring/copy_independence_probe.py", "root", "--root", [], False),
    ("spa_core/monitoring/findings_bridge_c125.py", "root", "--root", [], False),
    ("spa_core/monitoring/intraday_equity.py", "root", "--root", [], False),
    ("spa_core/monitoring/orphan_sweep.py", "root", "--repo-root", [], False),
    ("spa_core/monitoring/outcomes_archive.py", "root", "--root", [], False),
    ("spa_core/monitoring/problem_store.py", "data", "--data-dir", [], False),
    ("spa_core/analytics/counterfactual_tracking_census.py", "root", "--root", [], False),
    ("spa_core/analytics/decision_expiry_census.py", "root", "--root", [], False),
    ("spa_core/analytics/emergency_mode_census.py", "root", "--root", [], False),
    ("spa_core/analytics/error_class_census.py", "root", "--root", [], False),
    ("spa_core/analytics/gas_optimization_engine.py", "data", "--data-dir", [], False),
    ("spa_core/analytics/monthly_performance_report.py", "data", "--data-dir", [], False),
    ("spa_core/analytics/portfolio_kpi_census.py", "root", "--root", [], False),
    ("spa_core/analytics/portfolio_optimizer.py", "data", "--data-dir", [], True),
    ("spa_core/analytics/portfolio_snapshot_diff.py", "data", "--data-dir", [], False),
    ("spa_core/analytics/pre_trade_check_census.py", "root", "--root", [], False),
    ("spa_core/analytics/protocol_concentration_risk.py", "data", "--data-dir", [], False),
    ("spa_core/analytics/protocol_data_audit.py", "data", "--data-dir", [], False),
    ("spa_core/analytics/protocol_defi_position_size_optimizer.py", "data", "--data-dir", [], False),
    ("spa_core/analytics/rebalance_optimizer.py", "data", "--data-dir", [], False),
    ("spa_core/analytics/shadow_mode_census.py", "root", "--root", [], False),
    ("spa_core/analytics/stablecoin_exposure_report.py", "data", "--data-dir", [], False),
    ("spa_core/analytics/stablecoin_yield_optimizer.py", "data", "--data-dir", [], False),
    ("spa_core/analytics/strategy_benchmark_tracker.py", "data", "--data-dir", [], False),
    ("spa_core/analytics/yield_attribution_tracker.py", "data", "--data-dir", [], False),
]
# 49 в переписи минус `spa_core/analytics/cycle_health_monitor.py`: модуль поднимает ImportError
# на ПЕРВОЙ строке (DEPRECATED → spa_core.monitoring.cycle_health_monitor) — его argparse не исполняется
# ни при каком вызове, точкой входа он не является; перепись этого не различает (ADR-1000 § 4).
assert len(TRANCHE) == 48, len(TRANCHE)
assert len({t[0] for t in TRANCHE}) == 48

# у семи переписей (`*_census`) есть И `--root`, И `--data-dir`: дверь судит названный `--data-dir`,
# иначе — `--root` (ADR-1000 § 3); для них сцена B ждёт корень, потому что `--data-dir` не назван.
_ENV_KEYS = ("SPA_SANDBOX", "SPA_STAMP_TREE")

#: Единственная слепая точка входа переписи без вызывающего, НЕ вошедшая в транш, и почему — см. ниже.
DEAD_MODULE = "spa_core/analytics/cycle_health_monitor.py"


def _raises_at_module_top(path: Path) -> bool:
    """Первая исполняемая инструкция модуля — `raise` (мёртвый модуль, его main недостижим)."""
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant))]
    return bool(body) and isinstance(body[0], ast.Raise)


def _same_or_within(path: Path, target: Path) -> bool:
    """Судимый путь — названный ИЛИ его потомок (orphan_sweep судит файл артефакта под корнем)."""
    p, t = path.resolve(), target.resolve()
    return p == t or t in p.parents


class _DoorReached(BaseException):
    """Дверь позвана и промолчала — точка входа останавливается ЗДЕСЬ (до тяжёлой работы)."""

    def __init__(self, path, who):
        super().__init__(who)
        self.path, self.who = path, who


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses ищут модуль класса в sys.modules
    spec.loader.exec_module(mod)
    return mod


class _Scene(unittest.TestCase):
    """Одноразовый прод + чужая песочница; `DEFAULT_LIVE_ROOT` подменён на время теста."""

    def setUp(self):
        from spa_core.utils import live_paths
        self.lp = live_paths
        self._tmp = tempfile.TemporaryDirectory(prefix="sdt1_")
        self.prod = Path(self._tmp.name) / "prod"
        (self.prod / "data").mkdir(parents=True)
        self.other = Path(self._tmp.name) / "other"
        (self.other / "data").mkdir(parents=True)
        self._saved_root = live_paths.DEFAULT_LIVE_ROOT
        live_paths.DEFAULT_LIVE_ROOT = self.prod
        self._env = {k: os.environ.get(k) for k in _ENV_KEYS}
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        self._argv, self._path = sys.argv, list(sys.path)
        self._cwd = os.getcwd()
        # рука зовёт `python3 scripts/x.py` из корня репозитория: тот же sys.path, тот же cwd
        for p in (str(ROOT / "scripts"), str(ROOT)):
            if p not in sys.path:
                sys.path.insert(0, p)
        os.chdir(self.other)

    def tearDown(self):
        os.chdir(self._cwd)
        sys.argv, sys.path[:] = self._argv, self._path
        self.lp.DEFAULT_LIVE_ROOT = self._saved_root
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    # ── исполнение точки входа так, как её зовёт рука ──
    def _run(self, rel: str, argv: list[str]):
        file = ROOT / rel
        sys.argv = [str(file), *argv]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            runpy.run_path(str(file), run_name="__main__")
        return out.getvalue(), err.getvalue()

    def _target(self, kind: str, base: Path) -> Path:
        return base if kind == "root" else base / "data"

    def _snapshot(self, base: Path):
        return sorted(str(p.relative_to(base)) for p in base.rglob("*"))

    @contextlib.contextmanager
    def _spy(self):
        """Настоящая дверь + остановка сразу за ней; записывает (путь, who)."""
        real = self.lp.refuse_if_sandbox_leaks
        seen: list[tuple] = []

        def spy(path, *, who, code=2):
            real(path, who=who, code=code)
            seen.append((path, who))
            raise _DoorReached(path, who)

        self.lp.refuse_if_sandbox_leaks = spy
        try:
            yield seen
        finally:
            self.lp.refuse_if_sandbox_leaks = real


def _scene_a(rel, kind, flag, extra, _fb):
    def test(self):
        os.environ["SPA_SANDBOX"] = "1"
        before = self._snapshot(self.prod)
        err = ""
        with self.assertRaises(SystemExit) as cm:
            try:
                _, err = self._run(rel, [flag, str(self._target(kind, self.prod)), *extra])
            except SystemExit as exc:
                err = getattr(exc, "_err", "") or err
                raise
        self.assertEqual(cm.exception.code, 2, f"{rel}: код выхода {cm.exception.code!r}")
        self.assertEqual(self._snapshot(self.prod), before,
                         f"{rel}: отказ обязан идти ДО первой записи — в прод появились файлы")
    return test


def _scene_a_err(rel, kind, flag, extra, _fb):
    """Та же сцена A, но проверяется ТЕКСТ отказа: argparse тоже выходит кодом 2 — без имени
    двери и без имени точки входа код 2 ничего бы не доказывал."""
    def test(self):
        os.environ["SPA_SANDBOX"] = "1"
        file = ROOT / rel
        sys.argv = [str(file), flag, str(self._target(kind, self.prod)), *extra]
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit):
                runpy.run_path(str(file), run_name="__main__")
        text = err.getvalue()
        self.assertIn("ОТКАЗ (код 2)", text, f"{rel}: stderr без отказа двери: {text[-400:]!r}")
        self.assertIn("маркер песочницы", text)
        self.assertIn(f"{Path(rel).stem}:", text, "отказ обязан назвать САМУ точку входа (who)")
    return test


def _scene_b(rel, kind, flag, extra, _fb):
    def test(self):
        target = self._target(kind, self.prod)
        with self._spy() as seen:
            with self.assertRaises(_DoorReached):
                self._run(rel, [flag, str(target), *extra])
        self.assertEqual(len(seen), 1, f"{rel}: дверь позвана {len(seen)} раз")
        path, who = seen[0]
        self.assertTrue(_same_or_within(Path(path), target),
                        f"{rel}: двери отдан не названный флагом путь: {path!r}")
        self.assertEqual(who, Path(rel).stem)
    return test


def _scene_c(rel, kind, flag, extra, _fb):
    def test(self):
        os.environ["SPA_SANDBOX"] = "1"
        target = self._target(kind, self.other)
        with self._spy() as seen:
            with self.assertRaises(_DoorReached):
                self._run(rel, [flag, str(target), *extra])
        self.assertTrue(_same_or_within(Path(seen[0][0]), target), seen[0][0])
    return test


def _scene_d(rel, kind, flag, extra, _fb):
    def test(self):
        with self._spy() as seen:
            with self.assertRaises(_DoorReached):
                self._run(rel, list(extra))
        self.assertEqual(len(seen), 1)
        self.assertIsNotNone(seen[0][0], f"{rel}: двери отдан None — умолчание не разрешено до двери")
        self.assertTrue(str(seen[0][0]), f"{rel}: двери отдан пустой путь")
    return test


class TestSceneA_MarkerAndProdRefuses(_Scene):
    """A: маркер + прод-каталог ⇒ код 2 и ни одного файла в прод-`data/`."""


class TestSceneA_RefusalIsNamed(_Scene):
    """A′: отказ называет дверь и точку входа (не argparse-выход)."""


class TestSceneB_NoMarkerProdPasses(_Scene):
    """B: без маркера дверь молчит; точке входа отдан путь флага и своё имя."""


class TestSceneC_MarkerForeignPasses(_Scene):
    """C: маркер + чужой каталог ⇒ дверь молчит."""


class TestSceneD_FallbackIsResolvedBeforeTheDoor(_Scene):
    """D: флаг не назван ⇒ дверь судит РАЗРЕШЁННОЕ умолчание, не None."""


for _rel, _kind, _flag, _extra, _fb in TRANCHE:
    _stem = Path(_rel).stem
    setattr(TestSceneA_MarkerAndProdRefuses, f"test_{_stem}", _scene_a(_rel, _kind, _flag, _extra, _fb))
    setattr(TestSceneA_RefusalIsNamed, f"test_{_stem}", _scene_a_err(_rel, _kind, _flag, _extra, _fb))
    setattr(TestSceneB_NoMarkerProdPasses, f"test_{_stem}", _scene_b(_rel, _kind, _flag, _extra, _fb))
    setattr(TestSceneC_MarkerForeignPasses, f"test_{_stem}", _scene_c(_rel, _kind, _flag, _extra, _fb))
    if _fb:
        setattr(TestSceneD_FallbackIsResolvedBeforeTheDoor, f"test_{_stem}",
                _scene_d(_rel, _kind, _flag, _extra, _fb))


class TestTheDoorItself(_Scene):
    """Семантика ЕДИНСТВЕННОЙ двери — один раз, на настоящей `live_paths`."""

    def test_marker_and_prod_is_a_named_reason_and_exit_2(self):
        os.environ["SPA_SANDBOX"] = "1"
        self.assertIsNotNone(self.lp.sandbox_leak_reason(self.prod / "data", who="x"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            self.lp.refuse_if_sandbox_leaks(self.prod / "data", who="probe_x")
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("probe_x: ОТКАЗ (код 2)", err.getvalue())

    def test_marker_and_foreign_is_silent(self):
        os.environ["SPA_SANDBOX"] = "1"
        self.assertIsNone(self.lp.sandbox_leak_reason(self.other / "data", who="x"))
        self.lp.refuse_if_sandbox_leaks(self.other, who="x")  # не поднимает

    def test_no_marker_and_prod_is_silent(self):
        self.assertIsNone(self.lp.sandbox_leak_reason(self.prod, who="x"))
        self.lp.refuse_if_sandbox_leaks(self.prod / "data", who="x")

    def test_a_child_of_prod_is_refused_and_probe_tree_marker_counts(self):
        os.environ["SPA_STAMP_TREE"] = str(self.other)
        nested = self.prod / "sub"
        nested.mkdir()
        self.assertIsNotNone(self.lp.sandbox_leak_reason(nested, who="x"))

    def test_none_is_a_type_error_not_a_pass(self):
        os.environ["SPA_SANDBOX"] = "1"
        with self.assertRaises(TypeError):
            self.lp.sandbox_leak_reason(None, who="x")
        os.environ.pop("SPA_SANDBOX")
        with self.assertRaises(TypeError):  # и без маркера: «ничего» не судится никогда
            self.lp.refuse_if_sandbox_leaks(None, who="x")

    def test_the_door_is_the_shared_one_not_a_copy(self):
        """Подмена `assert_not_prod_realpath` меняет ответ ⇒ своей копии сравнения нет."""
        real = self.lp.assert_not_prod_realpath

        def fake(path, *, who):
            raise self.lp.SandboxLeakError(f"{who}: подменённая дверь")

        self.lp.assert_not_prod_realpath = fake
        try:
            self.assertEqual(self.lp.sandbox_leak_reason(self.other, who="y"), "y: подменённая дверь")
        finally:
            self.lp.assert_not_prod_realpath = real

    def test_exit_code_is_a_parameter(self):
        os.environ["SPA_SANDBOX"] = "1"
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            self.lp.refuse_if_sandbox_leaks(self.prod, who="x", code=7)
        self.assertEqual(cm.exception.code, 7)


class TestTheCensusReadsTheTranche(unittest.TestCase):
    """Исход заказа G988 п. 1а: перепись читает у всех 49 `DOOR`; у читателей `uncalled == 0`."""

    @classmethod
    def setUpClass(cls):
        cls.census = _load(ROOT / "scripts" / "sandbox_data_dir_census.py", "sdt1_census")
        cls.callers = _load(ROOT / "scripts" / "sandbox_data_dir_callers.py", "sdt1_callers")
        cls.c = cls.census.measure(ROOT)

    def test_every_tranche_entry_is_door_reached_from_the_entry_point(self):
        by_path = {e.path: e for e in self.c.entries}
        missing = [rel for rel, *_ in TRANCHE if rel not in by_path]
        self.assertEqual(missing, [], "точка входа транша не попала в перепись")
        not_door = [(rel, by_path[rel].verdict, by_path[rel].door_unreached)
                    for rel, *_ in TRANCHE if by_path[rel].verdict != "DOOR"]
        self.assertEqual(not_door, [])
        unreached = [rel for rel, *_ in TRANCHE if by_path[rel].door_unreached]
        self.assertEqual(unreached, [], "дверь есть в файле, но от входа не достигается (ADR-932)")
        self.assertTrue(all("refuse_if_sandbox_leaks" in by_path[rel].doors for rel, *_ in TRANCHE))

    def test_no_entry_point_with_a_hand_reachable_default_remains(self):
        cc = self.callers.measure(ROOT, census=self.c)
        self.assertEqual(cc.code, 1 if cc.counts.get("DEFAULT_RELIED") else 0,
                         cc.unmeasured_reason)
        # Остаток `UNCALLED` — РОВНО один названный мёртвый модуль: его первая инструкция —
        # `raise ImportError` (DEPRECATED), argparse под ним не исполняется ни при каком вызове,
        # и ставить туда дверь значило бы судить код, который не запускается. Перепись этого
        # не различает (ADR-1000 § 4, § 6а). Любой ДРУГОЙ остаток — красный.
        uncalled = sorted(r.path for r in cc.readers if r.verdict == "UNCALLED")
        self.assertEqual(uncalled, [DEAD_MODULE], uncalled)
        self.assertTrue(_raises_at_module_top(ROOT / DEAD_MODULE),
                        f"{DEAD_MODULE} больше не мёртв — дверь ему теперь положена (транш 2)")
        self.assertEqual(cc.exposure["uncalled"], 1)
        self.assertEqual(cc.exposure["relied_by_prompt_or_hand"], 0)
        self.assertEqual(cc.exposure["relied_other"], 0)
        # остаток — ТОЛЬКО реестр (ADR-999 § 6в, не этой дверью)
        rest = [r.path for r in cc.readers if r.verdict == "DEFAULT_RELIED"
                and any(c.kind != "registry" for c in r.relying)]
        self.assertEqual(rest, [])

    def test_the_wiring_line_commented_out_is_not_door(self):
        """Отрицательный контроль: без строки двери та же точка входа — `MARKER_BLIND`."""
        rel = "scripts/edge_tuw_unsmooth.py"
        src = (ROOT / rel).read_text(encoding="utf-8")
        line = next(l for l in src.splitlines() if l.strip().startswith("refuse_if_sandbox_leaks("))
        self.assertEqual(src.count(line), 1)
        with tempfile.TemporaryDirectory(prefix="sdt1_neg_") as tmp:
            repo = Path(tmp)
            (repo / "scripts").mkdir()
            (repo / "scripts" / "edge_tuw_unsmooth.py").write_text(
                src.replace(line, "    # " + line.strip()), encoding="utf-8")
            c = self.census.measure(repo, dirs=("scripts",))
            e = next(x for x in c.entries if x.path == rel)
            self.assertEqual(e.verdict, "MARKER_BLIND", e)
            self.assertNotIn("refuse_if_sandbox_leaks", e.doors)
            # а с живой строкой — DOOR (контроль контроля)
            (repo / "scripts" / "edge_tuw_unsmooth.py").write_text(src, encoding="utf-8")
            e2 = next(x for x in self.census.measure(repo, dirs=("scripts",)).entries if x.path == rel)
            self.assertEqual(e2.verdict, "DOOR")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


#: Скрипты (11), у которых до ADR-1000 корня репозитория на `sys.path` НЕ БЫЛО: рука зовёт их ПО ПУТИ
#: (`python3 scripts/x.py`), и `sys.path[0]` — каталог скрипта, а не репозиторий. Без страховки
#: сам ИМПОРТ двери падал бы `ModuleNotFoundError: spa_core` — то есть дверь ломала бы скрипт,
#: не защищая его (урок `com.spa.source_discovery`, ADR-148).
GUARDED_SCRIPTS = [
    ("scripts/adr_number.py", "--root"),
    ("scripts/fix_fabricated_evidence.py", "--data-dir"),
    ("scripts/reap_stale_worktrees.py", "--root"),
    ("scripts/edge_lst_yield_persistence.py", "--data-dir"),
    ("scripts/edge_pt_fixed_vs_float.py", "--data-dir"),
    ("scripts/edge_pt_term_structure.py", "--data-dir"),
    ("scripts/edge_tuw_unsmooth.py", "--data-dir"),
    ("scripts/edge_weekday_loss_gate.py", "--data-dir"),
    ("scripts/git_path_coordinate_census.py", "--root"),
    ("scripts/mutation_gate.py", "--repo-root"),
    ("scripts/seed_test_fixtures.py", "--out-dir"),
]


class TestScriptsCalledByPathCanImportTheDoor(unittest.TestCase):
    """Отдельный процесс, cwd — ЧУЖОЙ каталог, `PYTHONPATH` пуст: так зовёт рука.

    Проверяется только одно: импорт двери не падает. Дальше скрипт делает своё (на пустом
    каталоге — честный отказ «не измерено» или пустой отчёт), и это здесь не предмет.
    """

    def _run(self, rel: str, flag: str, extra=()):
        import subprocess
        with tempfile.TemporaryDirectory(prefix="sdt1_path_") as tmp:
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", *_ENV_KEYS)}
            env["SPA_SANDBOX"] = "1"  # маркер стоит, каталог чужой ⇒ дверь обязана быть ПРОЙДЕНА, не обрушена
            # правильно сконфигурированная песочница называет и живой корень (C8(b), ADR-580): иначе
            # ПРЕЖНЯЯ дверь `live_root` у трекера (`owner_queue.queue`, на импорте) отказала бы раньше нашей
            env["SPA_LIVE_ROOT"] = tmp
            env["SPA_DATA_DIR"] = os.path.join(tmp, "data")
            proc = subprocess.run([sys.executable, str(ROOT / rel), flag, tmp, *extra], cwd=tmp, env=env,
                                  capture_output=True, text=True, timeout=120)
        return proc

    def test_no_tranche_script_dies_on_importing_the_door(self):
        """ВСЕ 18 скриптов транша, не только страхованные: `grep sys.path` обманул дважды
        (`adr_number`, `reap_stale_worktrees` кладут на путь `scripts/`, а не корень)."""
        scripts = [(rel, flag) for rel, kind, flag, *_ in TRANCHE if rel.startswith("scripts/")]
        self.assertEqual(len(scripts), 18)
        for rel, flag in scripts:
            with self.subTest(rel):
                proc = self._run(rel, flag, ["next"] if rel.endswith("adr_number.py") else [])
                self.assertNotIn("No module named 'spa_core'", proc.stderr,
                                 f"{rel}: дверь ломает скрипт вместо того, чтобы его защищать:\n{proc.stderr[-600:]}")
                self.assertNotIn("ОТКАЗ (код 2)", proc.stderr, "чужой каталог под маркером проходит")
                for frame in ("in refuse_if_sandbox_leaks", "in sandbox_leak_reason"):
                    self.assertNotIn(frame, proc.stderr, f"{rel}: трассировка из самой двери:\n{proc.stderr[-600:]}")

    def test_the_guard_is_what_makes_the_import_work(self):
        """Положительный контроль: тот же скрипт БЕЗ страховки, позванный по пути из чужого
        каталога, импортировать `spa_core` не может — иначе страховка была бы украшением."""
        import subprocess
        rel = "scripts/edge_tuw_unsmooth.py"
        src = (ROOT / rel).read_text(encoding="utf-8")
        marker = "if _SPA_REPO_ROOT not in sys.path:\n    sys.path.insert(0, _SPA_REPO_ROOT)\n"
        self.assertEqual(src.count(marker), 1)
        with tempfile.TemporaryDirectory(prefix="sdt1_ctl_") as tmp:
            scripts = Path(tmp) / "repo" / "scripts"
            scripts.mkdir(parents=True)
            (scripts / "edge_tuw_unsmooth.py").write_text(src.replace(marker, ""), encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", *_ENV_KEYS)}
            env["SPA_SANDBOX"] = "1"
            proc = subprocess.run([sys.executable, str(scripts / "edge_tuw_unsmooth.py"), "--data-dir", tmp],
                                  cwd=tmp, env=env, capture_output=True, text=True, timeout=120)
        self.assertIn("No module named 'spa_core'", proc.stderr, proc.stderr[-400:])


#: Семь переписей несут ОБА флага — `--root` и `--data-dir`; пишут они в `data_dir`, когда он назван.
#: Дверь судит названный `--data-dir`, иначе `--root` (ADR-1000 § 3): судить только корень значило бы
#: пропустить `--root <песочница> --data-dir <прод>` и отказать `--root <прод> --data-dir <песочница>`.
DUAL_FLAG_CENSUSES = [rel for rel, kind, flag, *_ in TRANCHE
                      if rel.endswith("_census.py") and rel.startswith("spa_core/analytics/") and flag == "--root"]
assert len(DUAL_FLAG_CENSUSES) == 7, DUAL_FLAG_CENSUSES


def _scene_e(rel):
    """E: маркер + `--root <чужой>` + `--data-dir <прод>` ⇒ отказ (пишут в data_dir)."""
    def test(self):
        os.environ["SPA_SANDBOX"] = "1"
        err = io.StringIO()
        file = ROOT / rel
        sys.argv = [str(file), "--root", str(self.other), "--data-dir", str(self.prod / "data")]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                runpy.run_path(str(file), run_name="__main__")
        self.assertEqual(cm.exception.code, 2)
        self.assertIn(f"{Path(rel).stem}: ОТКАЗ (код 2)", err.getvalue())
    return test


def _scene_f(rel):
    """F: маркер + `--root <прод>` + `--data-dir <чужой>` ⇒ дверь судит data_dir и молчит."""
    def test(self):
        os.environ["SPA_SANDBOX"] = "1"
        with self._spy() as seen:
            with self.assertRaises(_DoorReached):
                self._run(rel, ["--root", str(self.prod), "--data-dir", str(self.other / "data")])
        self.assertTrue(_same_or_within(Path(seen[0][0]), self.other / "data"), seen[0][0])
    return test


class TestSceneE_CensusDataDirInProdRefuses(_Scene):
    """E: у переписей судится названный `--data-dir`, а не только `--root`."""


class TestSceneF_CensusDataDirOutsideProdPasses(_Scene):
    """F: прод-корень только ЧИТАЕТСЯ, пишется в чужой `--data-dir` ⇒ проходит."""


for _rel in DUAL_FLAG_CENSUSES:
    setattr(TestSceneE_CensusDataDirInProdRefuses, f"test_{Path(_rel).stem}", _scene_e(_rel))
    setattr(TestSceneF_CensusDataDirOutsideProdPasses, f"test_{Path(_rel).stem}", _scene_f(_rel))
