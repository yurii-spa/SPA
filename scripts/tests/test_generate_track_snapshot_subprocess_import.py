"""`scripts/generate_track_snapshot.py` запущен ПО ПУТИ, как его реально запускает
`scripts/deploy_site_snapshot.py` (``subprocess.run([_PY, str(_GEN)])``) — ADR-148-класс.

Разбор простоя 2026-10-02…10-05 (см. `docs/rm_truth/A3_product.md` §4, `REVIEW_1.md` claim 3):
`_sleeve_paper_track()` и `_post_fix_track()` делали ленивый
``from spa_core.paper_trading.sleeve_book import ECONOMICS_MODEL`` без бутстрапа ``sys.path``.
Когда модуль зовут ПО ПУТИ, ``sys.path[0]`` — каталог `scripts/`, а не корень репозитория,
и импорт падает ``ModuleNotFoundError: No module named 'spa_core'`` — публикация снимка
стояла на месте три дня подряд, цикл при этом не красный (шаг non-fatal).

**Почему существующие тесты этого не ловили.** `test_track_snapshot_paper_tracks.py` грузит
модуль через ``importlib.util.spec_from_file_location`` В ТОМ ЖЕ процессе — он наследует
``sys.path`` тестового раннера, где корень репозитория уже есть (pytest добавляет его сам).
«По пути» воспроизводится только настоящим ПОДПРОЦЕССОМ, запущенным из каталога `scripts/`
БЕЗ унаследованного ``PYTHONPATH`` — ровно так, как это делает `deploy_site_snapshot.py` и
launchd. Это и есть положительный контроль: сними бутстрап — тест красный.

Фикстура одноразовая (`TemporaryDirectory`), `data/` репозитория не трогается
(`.claude/rules/deployment.md`). `spa_core` в одноразовое дерево не копируется (тяжело и
не нужно) — достаточно символической ссылки на существующий пакет, импорт её разрешает
штатно.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_REPO = Path(__file__).resolve().parents[2]
_GEN_SRC = _REPO / "scripts" / "generate_track_snapshot.py"
_SPA_CORE_SRC = _REPO / "spa_core"


def _build_disposable_tree(root: Path) -> Path:
    """Дерево: <root>/scripts/generate_track_snapshot.py (копия), <root>/spa_core (симлинк на
    настоящий пакет), <root>/data/*.json (минимальная честная фикстура),
    <root>/landing/src/data/ (каталог для OUT — `_atomic_write` его не создаёт сам)."""
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(_GEN_SRC, root / "scripts" / "generate_track_snapshot.py")
    os.symlink(_SPA_CORE_SRC, root / "spa_core", target_is_directory=True)

    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "golive_status.json").write_text(json.dumps({
        "real_track_days": 5, "total": 29, "passed": 27,
        "go_live_state": "gate_passed_owner_decision_pending",
        "evidenced_anchor": "2026-06-22", "min_track_days": 30,
    }), encoding="utf-8")
    (data / "equity_curve_daily.json").write_text(json.dumps({
        "bars": [
            {"date": "2026-06-22", "equity": 100000.0, "evidenced": True, "drawdown_pct": 0.0},
            {"date": "2026-06-23", "equity": 100050.0, "evidenced": True, "drawdown_pct": 0.0},
        ]
    }), encoding="utf-8")
    (data / "paper_trading_status.json").write_text(json.dumps({
        "current_equity": 100050.0,
    }), encoding="utf-8")
    def _history(experiment_id, n=30):
        # n = REPORTABLE_AFTER (канон `spa_core.defi_engine.package_status`): ровно на
        # пороге зрелости — ADR-580 C2 нулит apy_pct НИЖЕ него, а этот тест обязан
        # увидеть НАСТОЯЩЕЕ число, которое и доказывает, что импорт не свалился молча.
        return [
            {"date": f"2026-09-{i + 1:02d}", "equity": 100000.0 + i * 10.0,
             "positions_count": 1, "economics_model": "sleeve-econ-v2",
             "experiment_id": experiment_id}
            for i in range(n)
        ]
    (data / "hy_paper_trading.json").write_text(json.dumps({
        "equity": 100010.0,
        "daily_history": _history("balanced-fixed-carry-v1@2026-10-02"),
        "experiments": [{"experiment_id": "balanced-fixed-carry-v1@2026-10-02",
                         "status": "active"}],
    }), encoding="utf-8")
    (data / "lp_paper_trading.json").write_text(json.dumps({
        "equity": 100010.0,
        "daily_history": _history("aggressive-susde-loop-v1@2026-10-02"),
        "experiments": [{"experiment_id": "aggressive-susde-loop-v1@2026-10-02",
                         "status": "active"}],
    }), encoding="utf-8")

    (root / "landing" / "src" / "data").mkdir(parents=True, exist_ok=True)
    return root / "scripts" / "generate_track_snapshot.py"


class TestGeneratorSurvivesPathLaunch(unittest.TestCase):
    """Положительный контроль: реальный подпроцесс, реальный `sys.path[0]` каталога скрипта."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tree = Path(self._tmp.name)
        _build_disposable_tree(self.tree)
        self.scripts_dir = self.tree / "scripts"
        self.out = self.tree / "landing" / "src" / "data" / "track_snapshot.json"
        # Окружение БЕЗ унаследованного PYTHONPATH — launchd/`deploy_site_snapshot.py` его тоже
        # не передают. Унаследованный PYTHONPATH замаскировал бы ровно тот дефект, который
        # этот тест обязан ловить.
        self.env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

    def test_runs_by_path_without_module_not_found(self):
        r = subprocess.run(
            [sys.executable, "generate_track_snapshot.py"],
            cwd=str(self.scripts_dir), capture_output=True, text=True, timeout=60,
            env=self.env,
        )
        self.assertEqual(
            r.returncode, 0,
            f"генератор, запущенный ПО ПУТИ (как его зовёт deploy_site_snapshot.py), обязан "
            f"завершаться успехом; stderr:\n{r.stderr}",
        )
        self.assertNotIn(
            "ModuleNotFoundError", r.stderr,
            "ADR-148-класс: ленивый импорт spa_core без бутстрапа sys.path в подпроцессе, "
            "запущенном по пути — ровно дефект простоя 2026-10-02…10-05",
        )
        self.assertIn("track_snapshot.json regenerated", r.stdout)

    def test_sleeve_tracks_are_actually_computed_not_swallowed(self):
        """Не просто rc==0 — цифры рукавов (ради которых и падал импорт) обязаны дойти."""
        r = subprocess.run(
            [sys.executable, "generate_track_snapshot.py"],
            cwd=str(self.scripts_dir), capture_output=True, text=True, timeout=60,
            env=self.env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        snap = json.loads(self.out.read_text(encoding="utf-8"))
        balanced = snap["paper_tracks"]["balanced"]
        aggressive = snap["paper_tracks"]["aggressive"]
        self.assertEqual(balanced["status"], "paper_test_running")
        self.assertIsNotNone(balanced["apy_pct"], "импорт ECONOMICS_MODEL не удался молча")
        self.assertEqual(aggressive["status"], "paper_test_running")
        self.assertIsNotNone(aggressive["apy_pct"])

    def test_positive_control_the_old_import_site_was_the_cause(self):
        """Отрицательный контроль на сам контроль: без бутстрапа (старая форма) — красный.

        Подменяет в скопированном файле ТОЛЬКО бутстрап-строки на no-op, оставляя сам
        ленивый импорт нетронутым — это и была форма дефекта до починки.
        """
        target = self.scripts_dir / "generate_track_snapshot.py"
        src = target.read_text(encoding="utf-8")
        # RM-TRUTH-01 integration (ADR-580): the function-level bootstraps were replaced by ONE
        # module-level bootstrap right after ``ROOT`` — when W4 and W5 merged, a NEW lazy
        # ``from spa_core…`` in ``build_snapshot`` arrived without its own bootstrap and this very
        # file caught the regression. Per-function bootstraps re-open the class on every new
        # import; one per module closes it. The control therefore removes the module-level line
        # (and any function-level leftovers) and expects the original failure back.
        boot = 'if str(ROOT) not in sys.path:\n    sys.path.insert(0, str(ROOT))\n'
        self.assertEqual(src.count(boot), 1, "ожидался ровно один модульный бутстрап сразу после ROOT")
        patched = src.replace(boot, '').replace(
            '        if str(ROOT) not in sys.path:\n            sys.path.insert(0, str(ROOT))\n', '')
        self.assertNotEqual(src, patched, "бутстраповые строки не найдены — тест не отражает фикс")
        target.write_text(patched, encoding="utf-8")

        r = subprocess.run(
            [sys.executable, "generate_track_snapshot.py"],
            cwd=str(self.scripts_dir), capture_output=True, text=True, timeout=60,
            env=self.env,
        )
        self.assertNotEqual(r.returncode, 0, "без бутстрапа запуск по пути обязан падать")
        self.assertIn("ModuleNotFoundError", r.stderr)


if __name__ == "__main__":
    unittest.main()
