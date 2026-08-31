# FROZEN-DATE-OK: синтетическая история — обе стороны сравнения запинены датами
# фикстуры; логика скрипта часы не читает.
"""`scripts/guardian_backtest.py --real` — прогон оверлея на РЕАЛЬНЫХ книгах (phase D prep).

До 2026-08-31 скрипт умел только фикстурный ростер — и потому pendle_pt_levered
(якорь турнирного слива, 50%) не был покрыт guardian-оверлеем ни разу. Эти тесты
пинят новый режим: реальный каталог читается, канонический guardian-модуль
используется (а не устаревшие локальные копии), пустой каталог — громкий отказ
кодом 2, а не пустая таблица, читающаяся как «книг нет».

У скрипта раньше не было НИ ОДНОГО теста — это первые.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "guardian_backtest", _REPO_ROOT / "scripts" / "guardian_backtest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_book(root: Path, sid: str, equities: list[float], phase: str = "backtest") -> None:
    d = root / sid
    d.mkdir(parents=True)
    lines = []
    for i, eq in enumerate(equities):
        lines.append(json.dumps({
            "date": f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}",
            "equity_usd": eq, "phase": phase,
        }))
    (d / "realized_series.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_real_mode_loads_books_from_the_given_dir(tmp_path):
    mod = _load_script()
    # 60 дней с настоящей просадкой в середине — guardian есть что резать
    eq = [100000.0 * (1.0 + 0.001 * i) for i in range(30)]
    eq += [eq[-1] * (1.0 - 0.02 * (i + 1)) for i in range(10)]
    eq += [eq[-1] * (1.0 + 0.002 * i) for i in range(20)]
    _seed_book(tmp_path, "synthetic_levered", eq)
    out = io.StringIO()
    with redirect_stdout(out):
        rc = mod.main(["--real", str(tmp_path)])
    text = out.getvalue()
    assert rc == 0
    assert "synthetic_levered" in text
    assert "REAL books from" in text
    assert str(tmp_path) in text


def test_real_mode_empty_dir_refuses_loudly_not_an_empty_table(tmp_path):
    """Worktree'вский data/aggressive_lab пуст ПО ПОСТРОЕНИЮ — пустая таблица
    читалась бы как «книг нет», что неправда. Отказ кодом 2, причина в stderr."""
    mod = _load_script()
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = mod.main(["--real", str(tmp_path)])
    assert rc == 2
    assert "no books found" in err.getvalue()


def test_real_mode_uses_the_canonical_guardian_module():
    """Проводка по ФОРМЕ вызова: real-ветка обязана звать
    spa_core.strategy_lab.aggressive_lab.guardian, а не локальные копии —
    те предшествуют канону и не знают min_vol/roundtrip_cost."""
    src = (_REPO_ROOT / "scripts" / "guardian_backtest.py").read_text(encoding="utf-8")
    assert "from spa_core.strategy_lab.aggressive_lab import guardian as g" in src
    assert "g.apply_guardian_drawdown" in src
    assert "g.apply_guardian_vol" in src


def test_fixture_mode_still_works_without_args(tmp_path, monkeypatch):
    """Фикстурный режим не сломан: без аргументов печатается прежняя таблица
    (её числа опубликованы в docs/DYNAMIC_LEVERAGE_GUARDIAN.md)."""
    mod = _load_script()
    out = io.StringIO()
    with redirect_stdout(out):
        rc = mod.main([])
    text = out.getvalue()
    assert rc == 0
    assert "susde_dn" in text
    assert "leverage_loop" in text
    # суффикс параметров — только в real-режиме: фикстурная таблица байт-стабильна
    assert "[dd(" not in text.split("OUT-OF-SAMPLE")[0]
