"""Побочные писатели цикла не трогают data/ дерева, когда песочница выставлена (ADR-849 §2).

Сторож `tracked_write_guard` ловит это кодом выхода СЕССИИ и только по git-tracked файлам; здесь — именованный
тест на ВСЕ файлы `data/` и `spa_core/data/` дерева, чтобы мутация любого из писателей краснела конкретным
тестом. Обратная сторона: журналы писателей обязаны появиться В ПЕСОЧНИЦЕ — иначе «ничего не записано» могло
бы значить «писатели не запускались».
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from spa_core.paper_trading import cycle_runner as cr
from types import SimpleNamespace

from spa_core.tests._measured_inputs import write_measured_red_flags  # ADR-531

# Тот же инертный цикл, что в tests/test_type_safety.py (двух адаптеров и фиксированной цели достаточно,
# чтобы прошли шаги, ведущие к побочным писателям).
_ADAPTERS = [
    {"protocol": "aave_v3", "tier": "T1", "apy_pct": 4.0, "tvl_usd": 2e8, "status": "ok"},
    {"protocol": "morpho_blue", "tier": "T2", "apy_pct": 5.0, "tvl_usd": 1e7, "status": "ok"},
]


class _FakeAllocator:
    def allocate(self):
        return SimpleNamespace(target_usd={"aave_v3": 40000.0, "morpho_blue": 18000.0}, expected_apy_pct=3.0,
                               model_used="risk_adjusted", strategy_loop_active=False)


def _orch_fn(adapters):
    return lambda data_dir: SimpleNamespace(adapters=adapters, status="ok")

_ROOT = Path(__file__).resolve().parents[1]
_WATCHED = (_ROOT / "data", _ROOT / "spa_core" / "data")
#: Журналы, которые цикл обязан написать в песочницу (замер трассировкой 28.10; подмножество — по одному
#: на каждый способ разрешения пути: от __file__, относительный, поиск вверх, атрибут класса, аргумент).
_EXPECTED_IN_SANDBOX = ("exit_liquidity_log.json", "liquidity_migration_log.json", "token_emission_log.json",
                        "aggregator_fee_log.json", "gap_monitor.json", "apy_milestone_log.json")


def _snapshot():
    snap = {}
    for root in _WATCHED:
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                p = Path(dirpath) / f
                try:
                    st = p.stat()
                except OSError:
                    continue
                snap[str(p)] = (st.st_mtime_ns, st.st_size)
    return snap


def _no_network(*_a, **_k):
    raise OSError("test: network closed")


def test_cycle_side_writers_write_only_into_the_sandbox(tmp_path, monkeypatch):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    monkeypatch.setenv("SPA_DATA_DIR", str(sandbox))
    # Шаг Tier-B (модули сигналов) цикл пропускает под SPA_ENV=ci: модули ходят в сеть и на CI зависают.
    # Здесь шаг ОБЯЗАН пройти — иначе тест не видит 15 писателей. Сеть закрыта: отказ мгновенный, а не ожидание.
    monkeypatch.delenv("SPA_ENV", raising=False)
    import socket
    monkeypatch.setattr(socket, "create_connection", _no_network)
    monkeypatch.setattr(socket, "getaddrinfo", _no_network)
    ddir = tmp_path / "cycle"
    ddir.mkdir()
    now = datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)
    write_measured_red_flags(ddir, now)
    before = _snapshot()
    cr.run_cycle(data_dir=ddir, now=now, orchestrator_fn=_orch_fn(_ADAPTERS), allocator=_FakeAllocator(),
                 risk_scorer_fn=lambda d: None, track_persister_fn=lambda d: None, write=True)
    after = _snapshot()
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert changed == [], f"цикл в песочнице изменил файлы дерева: {changed[:10]}"
    missing = [n for n in _EXPECTED_IN_SANDBOX if not (sandbox / n).exists()]
    assert missing == [], f"писатели не дошли до песочницы (не запускались?): {missing}"
