#!/usr/bin/env python3
"""ADR-089 п.1 — дневной срез блокировок риск-гейта коммитится в git.

Почему файл существует. `data/risk_policy_blocks.json` — кольцевой буфер на 100
записей, живущий ТОЛЬКО на рабочей машине (весь `data/*.json` в `.gitignore`).
Дневной отчёт при этом пишет владельцу «see risk_policy_blocks.json» — ссылка на
артефакт, которого нет ни у кого другого: ни у следующей сессии, ни в репозитории.
Решение владельца 15.08 (ADR-089 п.1, прецедент ADR-070.2 «канон трека коммитится
циклом»): цикл кладёт ДНЕВНОЙ СРЕЗ блокировок в git-tracked
`data/risk_blocks_daily/<YYYY-MM-DD>.json`.

Положительные контроли (каждый краснеет на коде ДО правки — функции нет):

1. срез содержит ТОЛЬКО записи за переданную дату (вчера/позавчера отброшены);
2. день без блокировок даёт ЧЕСТНЫЙ ПУСТОЙ срез — файл ЕСТЬ, `block_count: 0`
   (отсутствие файла неотличимо от «цикл не отработал» — это и есть дефект,
   который чинится);
3. повторный прогон идемпотентен (байт-в-байт тот же файл);
4. запись атомарна: падение сериализации не оставляет ни обрезанного файла,
   ни `*.tmp`-мусора — прежний срез цел;
5. дата — ВХОД функции, а не окружение (никакого `datetime.now()` внутри);
6. живой `run_cycle` в песочнице пишет срез и в день с блокировкой, и в чистый день.

Гермётичность: весь модуль работает против per-test `tmp_path`. Живой `data/`
не читается и не пишется (`allow_live_write=False`, явный НЕ-канонический
`data_dir` — интерлок чтит его дословно).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from spa_core.paper_trading import cycle_runner as _cr
from spa_core.paper_trading._cycle_io import RISK_BLOCKS_FILENAME
from spa_core.paper_trading import risk_gate as _rg

# Каталог среза — литерал в тесте НАРОЧНО: тест обязан краснеть на ОТСУТСТВИИ
# файла (реальный дефект), а не на отсутствии константы в модуле. Согласованность
# литерала с константой проверяет отдельный тест ниже.
RISK_BLOCKS_DAILY_DIRNAME = "risk_blocks_daily"

_DAY = "2026-08-15"
_PREV = "2026-08-14"


def _block(date: str, *, violation: str = "per_protocol_cap") -> dict:
    """Одна запись аудита в формате `_record_policy_block`."""
    return {
        "ts": f"{date}T08:00:00+00:00",
        "date": date,
        "source": "cycle_runner",
        "policy_version": "v1.0",
        "violations": [violation],
        "warnings": [],
        "blocked_target_usd": {"aave_v3": 90000.0},
        "held_positions_usd": {},
        "capital_usd": 100000.0,
    }


def _write_ring(ddir: Path, blocks: list[dict]) -> None:
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / RISK_BLOCKS_FILENAME).write_text(json.dumps(blocks), encoding="utf-8")


def _slice_path(ddir: Path, date: str) -> Path:
    return ddir / RISK_BLOCKS_DAILY_DIRNAME / f"{date}.json"


# ── 1. Срез = только сегодняшние записи ──────────────────────────────────────


def test_slice_contains_only_todays_records(tmp_path: Path) -> None:
    """Вчерашние блокировки в сегодняшний срез не попадают."""
    _write_ring(
        tmp_path,
        [
            _block(_PREV, violation="stale_yesterday"),
            _block(_DAY, violation="tvl_floor"),
            _block(_DAY, violation="cash_buffer"),
            _block("2026-08-13", violation="ancient"),
        ],
    )

    out = _rg.write_daily_block_slice(tmp_path, date=_DAY)

    doc = json.loads(Path(out).read_text(encoding="utf-8"))
    assert doc["date"] == _DAY
    assert doc["block_count"] == 2
    assert [b["date"] for b in doc["blocks"]] == [_DAY, _DAY]
    flat = [v for b in doc["blocks"] for v in b["violations"]]
    assert flat == ["tvl_floor", "cash_buffer"]
    assert "stale_yesterday" not in flat and "ancient" not in flat


def test_slice_path_is_the_committed_daily_dir(tmp_path: Path) -> None:
    """Файл ложится ровно в `data/risk_blocks_daily/<YYYY-MM-DD>.json`."""
    _write_ring(tmp_path, [_block(_DAY)])
    out = Path(_rg.write_daily_block_slice(tmp_path, date=_DAY))
    assert out == _slice_path(tmp_path, _DAY)
    assert out.parent.name == "risk_blocks_daily"


def test_dirname_constant_matches_the_committed_path() -> None:
    """Литерал теста и константа модуля обязаны совпадать (одно имя каталога)."""
    assert _rg.RISK_BLOCKS_DAILY_DIRNAME == RISK_BLOCKS_DAILY_DIRNAME


# ── 2. Пустой день — честный пустой срез, а не отсутствие файла ──────────────


def test_empty_day_writes_an_honest_empty_slice(tmp_path: Path) -> None:
    """День без блокировок ОБЯЗАН дать файл с `block_count: 0`.

    Отсутствие файла неотличимо от «цикл вообще не отработал» — именно это
    молчание чинит ADR-089 п.1.
    """
    _write_ring(tmp_path, [_block(_PREV)])

    out = Path(_rg.write_daily_block_slice(tmp_path, date=_DAY))

    assert out.exists(), "пустой день обязан оставить ФАЙЛ, а не пустоту"
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["date"] == _DAY
    assert doc["block_count"] == 0
    assert doc["blocks"] == []


def test_missing_ring_buffer_still_writes_empty_slice(tmp_path: Path) -> None:
    """Кольцевого буфера нет вовсе (первый день) → всё равно честный пустой срез."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    out = Path(_rg.write_daily_block_slice(tmp_path, date=_DAY))
    assert out.exists()
    assert json.loads(out.read_text(encoding="utf-8"))["block_count"] == 0


# ── 3. Идемпотентность ───────────────────────────────────────────────────────


def test_repeat_run_is_idempotent(tmp_path: Path) -> None:
    """Повторный прогон на тех же входах даёт БАЙТ-В-БАЙТ тот же срез."""
    _write_ring(tmp_path, [_block(_PREV), _block(_DAY)])

    first = Path(_rg.write_daily_block_slice(tmp_path, date=_DAY)).read_bytes()
    second = Path(_rg.write_daily_block_slice(tmp_path, date=_DAY)).read_bytes()
    third = Path(_rg.write_daily_block_slice(tmp_path, date=_DAY)).read_bytes()

    assert first == second == third
    # и никакого мусора рядом
    assert sorted(p.name for p in _slice_path(tmp_path, _DAY).parent.iterdir()) == [
        f"{_DAY}.json"
    ]


# ── 4. Атомарность записи ────────────────────────────────────────────────────


def test_write_is_atomic_failure_leaves_previous_slice_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Падение посреди записи не рвёт прежний срез и не сорит `*.tmp`.

    Положительный контроль на инвариант 5 (`atomic_save`: tmp в той же
    директории + `os.replace`). Прямой `open(..., "w")` этот тест провалит:
    файл окажется обрезанным, а мусор — на диске.
    """
    _write_ring(tmp_path, [_block(_DAY)])
    good = Path(_rg.write_daily_block_slice(tmp_path, date=_DAY))
    before = good.read_bytes()

    from spa_core.utils import atomic as _atomic

    def _boom(*_a, **_kw):
        raise RuntimeError("сериализация упала посреди записи")

    monkeypatch.setattr(_atomic.json, "dump", _boom)

    with pytest.raises(RuntimeError):
        _rg.write_daily_block_slice(tmp_path, date=_DAY)

    assert good.read_bytes() == before, "прежний срез обязан остаться целым"
    leftovers = [p.name for p in good.parent.iterdir() if p.name != good.name]
    assert leftovers == [], f"остался мусор от прерванной записи: {leftovers}"


# ── 5. Время — ВХОД функции, а не окружение ──────────────────────────────────


def test_date_is_an_input_not_the_wall_clock(tmp_path: Path) -> None:
    """Срез строится по ПЕРЕДАННОЙ дате — календарь на результат не влияет.

    Тест бессмертен по построению: и записи, и дата зафиксированы (правило
    «время — вход, а не окружение», `.claude/rules/deployment.md`).
    """
    _write_ring(tmp_path, [_block("2019-01-01"), _block(_DAY)])

    out = Path(_rg.write_daily_block_slice(tmp_path, date="2019-01-01"))

    assert out.name == "2019-01-01.json"
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["block_count"] == 1
    assert doc["blocks"][0]["date"] == "2019-01-01"


def test_blocks_may_be_passed_in_directly(tmp_path: Path) -> None:
    """Записи тоже можно передать входом (без чтения кольцевого буфера)."""
    _write_ring(tmp_path, [_block(_DAY, violation="from_disk")])

    out = Path(
        _rg.write_daily_block_slice(
            tmp_path, date=_DAY, blocks=[_block(_DAY, violation="from_arg")]
        )
    )

    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["block_count"] == 1
    assert doc["blocks"][0]["violations"] == ["from_arg"]


# ── 6. Живой цикл: срез появляется и в «плохой», и в чистый день ─────────────

_NOW = datetime(2026, 8, 15, 8, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _stub_the_owner_alert(monkeypatch: pytest.MonkeyPatch):
    """Сетевой транспорт тревоги — заглушка (как в test_cycle_nav_determinism)."""
    from spa_core.telegram import push_policy

    monkeypatch.setattr(push_policy, "_send", lambda text: True)


def _orch(data_dir):  # noqa: ANN001 — сигнатура orchestrator_fn
    adapters = [
        {
            "protocol": "aave_v3",
            "id": "aave_v3",
            "apy_pct": 4.0,
            "tvl_usd": 1e8,
            "tvl_source": "live",
            "tier": "T1",
            "status": "ok",
        },
        {
            "protocol": "compound_v3",
            "id": "compound_v3",
            "apy_pct": 4.2,
            "tvl_usd": 1e8,
            "tvl_source": "live",
            "tier": "T2",
            "status": "ok",
        },
    ]
    return SimpleNamespace(adapters=adapters, status="ok", data_freshness="live")


def _allocator(target_usd: dict[str, float]):
    class _Alloc:
        def allocate(self):  # noqa: D401 — фейк
            return SimpleNamespace(
                target_usd=dict(target_usd),
                target_weights={p: v / 100_000.0 for p, v in target_usd.items()},
                expected_apy_pct=4.0,
                model_used="risk_adjusted",
                strategy_loop_active=False,
            )

    return _Alloc()


def _run(ddir: Path, target: dict[str, float]):
    return _cr.run_cycle(
        data_dir=str(ddir),
        now=_NOW,
        orchestrator_fn=_orch,
        allocator=_allocator(target),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,
        write=True,
        allow_live_write=False,
    )


def test_cycle_writes_daily_slice_when_gate_blocks(tmp_path: Path) -> None:
    """Гейт блокирует (per-protocol cap 40% нарушен) → срез содержит запись."""
    ddir = tmp_path / "data"
    result = _run(ddir, {"aave_v3": 90_000.0})

    assert result.policy_approved is False, "фикстура должна ловить блокировку гейта"
    out = _slice_path(ddir, _NOW.strftime("%Y-%m-%d"))
    assert out.exists(), "цикл обязан положить дневной срез рядом с кольцевым буфером"
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["block_count"] >= 1
    assert all(b["date"] == _NOW.strftime("%Y-%m-%d") for b in doc["blocks"])


def test_cycle_writes_empty_slice_on_a_clean_day(tmp_path: Path) -> None:
    """Гейт ничего не заблокировал → срез ВСЁ РАВНО есть, честно пустой."""
    ddir = tmp_path / "data"
    result = _run(ddir, {"aave_v3": 30_000.0, "compound_v3": 15_000.0})

    assert result.policy_approved is True, "фикстура должна проходить гейт"
    out = _slice_path(ddir, _NOW.strftime("%Y-%m-%d"))
    assert out.exists(), "чистый день обязан оставить пустой срез, а не пустоту"
    assert json.loads(out.read_text(encoding="utf-8"))["block_count"] == 0
