"""Tests for the real paper-trading cycle runner (SPA-V409).

The orchestrator and allocator are injected as in-process fakes so the suite is
fully deterministic and hits no network / no real adapters.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from spa_core.paper_trading import cycle_runner as cr


# ─── Fakes ────────────────────────────────────────────────────────────────────


def _fake_orch_result(apy_map, status="ok"):
    # aave_v3 is the T1 anchor (как в реальном снимке оркестратора); остальные T2.
    adapters = [
        {
            "protocol": p,
            "apy_pct": a,
            "tvl_usd": 1e7,
            "tvl_source": "live",
            "tier": "T1" if p == "aave_v3" else "T2",
            "status": "ok",
        }
        for p, a in apy_map.items()
    ]
    return SimpleNamespace(adapters=adapters, status=status, data_freshness="live")


def _orch_fn(apy_map, status="ok"):
    def _fn(data_dir):
        return _fake_orch_result(apy_map, status=status)

    return _fn


class _FakeAllocator:
    def __init__(self, target_usd, model="risk_adjusted", strategy_loop=False):
        self._target = target_usd
        self._model = model
        self._loop = strategy_loop

    def allocate(self):
        return SimpleNamespace(
            target_usd=dict(self._target),
            target_weights={p: v / 100_000 for p, v in self._target.items()},
            expected_apy_pct=3.0,
            model_used=self._model,
            strategy_loop_active=self._loop,
        )


def _run(tmp_path, apy_map, target_usd, *, now=None, status="ok", **kw):
    now = now or datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)
    return cr.run_cycle(
        data_dir=tmp_path,
        now=now,
        orchestrator_fn=_orch_fn(apy_map, status=status),
        allocator=_FakeAllocator(target_usd, **kw),
        # MP-012: no-op risk scorer — these tests stay network-free; the regen
        # step itself is covered in test_risk_scores_regen.py.
        risk_scorer_fn=lambda d: None,
        # MP-109: no-op track persister — sync/backup covered in
        # test_track_persistence.py; keeps these tests off iCloud/home dirs.
        track_persister_fn=lambda d: None,
    )


def _cio_says(monkeypatch, decision: str, reasons=()):
    """Объявить вердикт CIO во входах сцены (ADR-324, взвод CIO 11.09).

    С 11.09 перетасовку консервативной книги решает вердикт CIO. Сцены ниже,
    предмет которых — УЧЁТ сделки (доллары хода, номер сделки) или само решение,
    обязаны объявлять вердикт явно: иначе их вердикт решала бы экономика CIO на
    синтетической фикстуре, где у целей нет наблюдённых ставок, — не их предмет.
    Настоящая логика `cio_arming.trade_allowed` при этом ИСПОЛНЯЕТСЯ целиком
    (исключения де-риска и размещения, проводка); подменяется только вердикт.
    """
    from spa_core.paper_trading import cio_arming
    monkeypatch.setattr(cio_arming, "cio_verdict",
                        lambda doc: (decision, list(reasons)))


def _load(tmp_path, name):
    p = tmp_path / name
    return json.loads(p.read_text()) if p.exists() else None


APY = {"aave_v3": 4.0, "morpho_blue": 5.0, "yearn_v3": 3.0, "maple": 4.7}
# RiskPolicy-compliant target (MP-005): T1 aave 40% (== cap), T2 total 34% < 35%.
TARGET = {"aave_v3": 40000.0, "morpho_blue": 20000.0, "yearn_v3": 14000.0}


# ─── Core loop ──────────────────────────────────────────────────────────────


def test_full_cycle_writes_trade(tmp_path):
    res = _run(tmp_path, APY, TARGET)
    assert res.status == "ok"
    assert res.traded is True
    trades = _load(tmp_path, "trades.json")
    assert len(trades) == 1
    assert trades[0]["trade_id"] == "T001"
    assert trades[0]["type"] == "rebalance"
    assert trades[0]["reason"] == "orchestrator_cycle"
    assert trades[0]["to_allocation"]["aave_v3"] == 40000.0


def test_trade_records_delta_abs_not_none(tmp_path):
    # Regression: every trade record had delta_abs missing → r.get("delta_abs")
    # was None for all rows, so real rebalance $ size (for txn cost / slippage)
    # was never captured. delta_abs must be a NUMBER, never None.
    res = _run(tmp_path, APY, TARGET)
    assert res.traded is True
    trades = _load(tmp_path, "trades.json")
    t = trades[0]
    assert t["delta_abs"] is not None
    assert isinstance(t["delta_abs"], (int, float))
    # First-ever cycle deploys the full book from cash → real turnover > 0.
    assert t["delta_abs"] > 0
    # ИЗМЕНЕНО 2026-08-30 (инв. 16, обоснование — здесь и в журнале W35).
    # Прежняя строка утверждала `delta_abs == diff_usd / 2` ИМЕННО в этой
    # фикстуре, которая двумя строками выше объявлена как «первый цикл
    # разворачивает всю книгу ИЗ КЭША» — то есть ход односторонний. L1
    # считается по ключам ПРОТОКОЛОВ, у кэша ключа нет, продающей ноги не
    # возникает, и деление пополам занижает оборот ровно вдвое. Тест
    # закреплял дефект в единственной фикстуре, где тот проявляется.
    # Тождество `L1/2` для ДВУСТОРОННЕЙ перекладки не отменено и проверяется
    # соседним test_delta_abs_equals_real_dollars_moved — он зелёный.
    from spa_core.governance.churn_damper import one_sided_turnover
    assert t["delta_abs"] == pytest.approx(
        round(one_sided_turnover(t["from_allocation"], t["to_allocation"]), 2))
    assert t["delta_abs"] == pytest.approx(t["diff_usd"]), (
        "первый цикл разворачивает книгу из кэша: одна нога, оборот равен L1")


def test_delta_abs_equals_real_dollars_moved(tmp_path, monkeypatch):
    # ИЗМЕНЁН НАМЕРЕННО 11.09 (инв. №16): предмет — учёт долларов хода, а не решение.
    # С взводом CIO (ADR-324) перетасовку разрешает его вердикт; сцена объявляет его
    # явно, все утверждения про delta_abs сохранены дословно.
    _cio_says(monkeypatch, "ACT")
    # Establish positions == TARGET, then a real swap on the next cycle.
    _run(tmp_path, APY, TARGET)
    changed = {"aave_v3": 40000.0, "maple": 20000.0, "yearn_v3": 14000.0}
    # ИЗМЕНЕНО НАМЕРЕННО (инв. №16, ADR-339): демпфер теперь судит по часам ЦИКЛА. Раньше
    # он брал настенные часы, и перекладка «через 24 ч после размещения» в июне-2026
    # выглядела для него ходом трёхмесячной давности — блокировать ему было нечего.
    # По честным часам такой ход демпфер правильно держит (удержание 72 ч, недельный
    # бюджет выбран размещением). Предмет этого теста — не частота, поэтому ход
    # перенесён за пределы обоих окон: через 9 дней. Утверждения не тронуты.
    res = _run(
        tmp_path,
        APY,
        changed,
        now=datetime(2026, 6, 19, 8, 0, tzinfo=timezone.utc),
    )
    assert res.traded is True
    trades = _load(tmp_path, "trades.json")
    t = trades[-1]
    # Compute expected real $ moved directly from the from/to books recorded.
    frm = t["from_allocation"]
    to = t["to_allocation"]
    keys = set(frm) | set(to)
    l1 = sum(abs(to.get(k, 0.0) - frm.get(k, 0.0)) for k in keys)
    assert t["delta_abs"] is not None
    assert t["delta_abs"] == pytest.approx(round(l1 / 2.0, 2))
    assert t["delta_abs"] > 0
    # to_allocation is the compliant book (≤8 protocols), consistent w/ ALLOC-002.
    assert len(t["to_allocation"]) <= 8


def test_idempotent_no_trade_when_allocation_unchanged(tmp_path):
    # First cycle establishes positions == target.
    _run(tmp_path, APY, TARGET)
    # Second cycle next day, same target → no new trade.
    res2 = _run(
        tmp_path, APY, TARGET, now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc)
    )
    assert res2.traded is False
    trades = _load(tmp_path, "trades.json")
    assert len(trades) == 1  # still just the first trade


def test_equity_accrues_daily_yield(tmp_path):
    # ADR-298 (инвариант #16 — изменение НАМЕРЕННОЕ, решение владельца ADR-286 §1):
    # издержка перекладки теперь СПИСЫВАЕТСЯ в кривую. Первый цикл разворачивает
    # $100k из кэша в пулы, и это стоит денег: до правки день закрывался ровно на
    # начисленный доход, потому что за собственные ходы книга не платила НИКОГДА.
    # Проверяется не новое число, а РАВЕНСТВО: close = open + доход − издержка,
    # плюс положительный контроль «издержка > 0 на дне развёртывания».
    res = _run(tmp_path, APY, TARGET)
    # Expected: Σ pos * apy / 100 / 365.
    expected = sum(TARGET[p] * APY[p] / 100 / 365 for p in TARGET)
    assert res.daily_yield_usd == pytest.approx(expected, abs=1e-3)
    bar = _load(tmp_path, "equity_curve_daily.json")["daily"][-1]
    assert bar["cost_usd"] > 0, "развёртывание $100k из кэша обязано стоить денег"
    assert res.current_equity == pytest.approx(
        100_000 + expected - bar["cost_usd"], abs=1e-2)


def test_equity_curve_updated(tmp_path):
    _run(tmp_path, APY, TARGET)
    eq = _load(tmp_path, "equity_curve_daily.json")
    assert eq["is_demo"] is False
    assert eq["source"] == "cycle_runner"
    assert len(eq["daily"]) == 1
    bar = eq["daily"][0]
    # prompt-mandated flat fields present.
    assert bar["date"] == "2026-06-10"
    assert "equity" in bar and "apy_today" in bar and "daily_return_pct" in bar
    assert bar["equity"] == bar["close_equity"]


def test_status_is_not_demo(tmp_path):
    _run(tmp_path, APY, TARGET)
    st = _load(tmp_path, "paper_trading_status.json")
    assert st["is_demo"] is False
    assert st["paper_start_date"] == "2026-06-10"
    assert st["strategy_loop_active"] is False
    assert st["last_allocation_model"] == "risk_adjusted"
    assert st["current_positions"]["aave_v3"] == 40000.0


def test_current_positions_written(tmp_path):
    _run(tmp_path, APY, TARGET)
    pos = _load(tmp_path, "current_positions.json")
    assert pos["is_demo"] is False
    # Positions stored at COST BASIS (stable; no re-marking across cycles).
    assert pos["deployed_usd"] == pytest.approx(74000.0, abs=1e-6)
    assert pos["cash_usd"] == pytest.approx(26000.0, abs=1e-6)
    assert pos["positions"]["morpho_blue"] == 20000.0
    # Сведение NAV (proof-of-reserves). ADR-298 (инвариант #16): у тождества появилось
    # ТРЕТЬЕ слагаемое — издержки перекладок. Прежняя форма верна только там, где ходы
    # бесплатны; после списания издержек она обязана сломаться, иначе деньги за ход не
    # ушли ниоткуда.
    assert (pos["deployed_usd"] + pos["cash_usd"] + pos["accrued_yield_usd"]
            - pos["costs_paid_usd"]) == pytest.approx(pos["current_equity_usd"], abs=0.05)
    assert pos["costs_paid_usd"] > 0, "развёртывание книги обязано стоить денег"
    assert pos["net_pnl_usd"] == pytest.approx(
        pos["accrued_yield_usd"] - pos["costs_paid_usd"], abs=0.01)


# ─── Ring buffers ─────────────────────────────────────────────────────────────


def test_ring_buffer_trades_max_500(tmp_path):
    # Seed 500 existing trades, then a cycle that trades → should cap at 500.
    seed = [{"trade_id": f"T{i:03d}", "type": "rebalance"} for i in range(1, 501)]
    (tmp_path / "trades.json").write_text(json.dumps(seed))
    # The two equity bars are new (2026-08-21, ADR-105; invariant #16 — deliberate,
    # noted in docs/journal/2026-W34.md). They change nothing about what this test
    # CHECKS — the trades ring buffer — and only make the sandbox coherent: 500
    # recorded trades beside a book that has never closed a single day is a state
    # that cannot arise except by corruption, and the daily-loss gate now stops
    # the cycle when it sees it. Two bars is the least that makes the book
    # measurable; their values are irrelevant to the assertions below.
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps({
        "source": "cycle_runner",
        "daily": [
            {"date": "2026-06-08", "open_equity": 100_000.0,
             "close_equity": 100_000.0, "daily_return_pct": 0.0, "evidenced": True},
            {"date": "2026-06-09", "open_equity": 100_000.0,
             "close_equity": 100_000.0, "daily_return_pct": 0.0, "evidenced": True},
        ],
    }))
    res = _run(tmp_path, APY, TARGET)
    assert res.traded is True
    trades = _load(tmp_path, "trades.json")
    assert len(trades) == 500
    assert trades[-1]["trade_id"] == "T501"  # newest kept
    assert trades[0]["trade_id"] == "T002"   # oldest dropped


def test_trade_id_increments_from_existing(tmp_path):
    (tmp_path / "trades.json").write_text(
        json.dumps([{"trade_id": "T007", "type": "rebalance"}])
    )
    res = _run(tmp_path, APY, TARGET)
    assert res.trade_id == "T008"


def test_equity_curve_ring_buffer_365(tmp_path):
    # Pre-fill with 365 dummy bars; one more cycle keeps it at 365.
    # Dates must be strictly monotonic to avoid EB-05 data-corruption halt.
    from datetime import date, timedelta
    _start = date(2025, 6, 10)
    daily = [
        {
            "date": (_start + timedelta(days=i)).isoformat(),
            "open_equity": 100000.0,
            "close_equity": 100000.0,
            "daily_return_pct": 0.0,
        }
        for i in range(365)
    ]
    (tmp_path / "equity_curve_daily.json").write_text(
        json.dumps({"source": "cycle_runner", "daily": daily, "summary": {}})
    )
    _run(tmp_path, APY, TARGET)
    eq = _load(tmp_path, "equity_curve_daily.json")
    assert len(eq["daily"]) == 365
    assert eq["daily"][-1]["date"] == "2026-06-10"


# ─── No-live-data path ────────────────────────────────────────────────────────


def test_graceful_when_orchestrator_returns_no_live_data(tmp_path):
    res = cr.run_cycle(
        data_dir=tmp_path,
        now=datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc),
        orchestrator_fn=_orch_fn({}, status="no_live_data"),
        allocator=_FakeAllocator(TARGET),
        risk_scorer_fn=lambda d: None,
        # MP-109: no-op track persister — sync/backup covered in
        # test_track_persistence.py; keeps these tests off iCloud/home dirs.
        track_persister_fn=lambda d: None,
    )
    assert res.status == "skipped_no_live_data"
    assert res.traded is False
    assert res.daily_yield_usd == 0.0
    # No trade written, but status doc still produced honestly.
    assert _load(tmp_path, "trades.json") is None
    st = _load(tmp_path, "paper_trading_status.json")
    assert st["last_cycle_status"] == "skipped_no_live_data"
    assert any("no_live_data" in n for n in st["notes"])


def test_no_live_data_when_status_ok_but_no_apy(tmp_path):
    # status "ok" but adapters carry no usable APY → still treated as no live data.
    res = cr.run_cycle(
        data_dir=tmp_path,
        now=datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc),
        orchestrator_fn=_orch_fn({}, status="ok"),
        allocator=_FakeAllocator(TARGET),
        risk_scorer_fn=lambda d: None,
        # MP-109: no-op track persister — sync/backup covered in
        # test_track_persistence.py; keeps these tests off iCloud/home dirs.
        track_persister_fn=lambda d: None,
    )
    assert res.status == "skipped_no_live_data"


# ─── Idempotency / multi-day behaviour ────────────────────────────────────────


def test_same_day_rerun_does_not_double_accrue(tmp_path):
    res1 = _run(tmp_path, APY, TARGET)
    # Re-run same calendar day (later timestamp) → equity bar recomputed, not compounded.
    res2 = _run(
        tmp_path, APY, TARGET, now=datetime(2026, 6, 10, 20, 0, tzinfo=timezone.utc)
    )
    eq = _load(tmp_path, "equity_curve_daily.json")
    assert len(eq["daily"]) == 1  # still one bar for 2026-06-10
    # ADR-298: повторный прогон того же дня ПЕРЕСЧИТЫВАЕТ доход (это ставка за сутки,
    # второй прогон не добавляет вторых суток), а издержку НАКАПЛИВАЕТ: деньги за ход
    # уже потрачены. Второй прогон книгу не двигает, поэтому добавляет ноль — и день
    # закрывается ровно там же, где закрыл первый.
    #
    # Первая редакция этой правки теряла издержку первого прогона (кривая возвращалась
    # к «бесплатной» и день закрывался на $63.70 выше, чем книга реально стоила) —
    # ровно этот тест её и поймал.
    assert res2.current_equity == pytest.approx(res1.current_equity, abs=1e-6)
    _bar = eq["daily"][-1]
    assert _bar["cost_usd"] > 0, "издержка первого прогона обязана пережить пересчёт дня"
    assert res2.current_equity == pytest.approx(
        100_000 + res2.daily_yield_usd - _bar["cost_usd"], abs=1e-2)


def test_two_days_compound(tmp_path):
    res1 = _run(tmp_path, APY, TARGET)
    res2 = _run(
        tmp_path, APY, TARGET, now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc)
    )
    eq = _load(tmp_path, "equity_curve_daily.json")
    assert len(eq["daily"]) == 2
    assert res2.current_equity > res1.current_equity  # second day adds more yield
    assert eq["summary"]["num_days"] == 2


def test_days_running_counts_from_paper_start(tmp_path):
    res = _run(
        tmp_path, APY, TARGET, now=datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)
    )
    # PAPER_START_DATE = 2026-06-10; now = 2026-06-10 → day 1.
    assert res.days_running == 1


# ─── Allocation diff threshold ────────────────────────────────────────────────


def test_small_allocation_drift_under_threshold_no_trade(tmp_path):
    _run(tmp_path, APY, TARGET)  # positions = TARGET
    # Drift one pool by a tiny amount (< 1% of capital total L1 distance);
    # yearn stays well under its T2 cap so the policy gate keeps approving.
    drifted = {**TARGET, "yearn_v3": TARGET["yearn_v3"] + 150.0}  # L1 = 150 < $200 threshold
    res = _run(
        tmp_path,
        APY,
        drifted,
        now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc),
    )
    assert res.traded is False


def test_large_allocation_change_triggers_trade(tmp_path, monkeypatch):
    """Крупная перетасовка проходит, когда CIO говорит «действовать».

    ИЗМЕНЁН НАМЕРЕННО 11.09 (инв. №16), причина — решение владельца (ADR-324):
    перетасовку консервативной книги решает вердикт CIO, а не одно лишь «ход больше
    порога». Прежнее утверждение «крупный ход ⇒ сделка» больше не есть правило, и
    сохранить его значило бы закрепить поведение, которое владелец отменил.
    Проверка не ослаблена, а разведена на ДВЕ стороны: этот тест — «CIO: да ⇒
    сделка», соседний — «CIO: нет ⇒ сделки нет». Без второго первый был бы
    украшением: он прошёл бы и при снятой проводке вердикта.
    """
    _cio_says(monkeypatch, "ACT")
    _run(tmp_path, APY, TARGET)
    changed = {"aave_v3": 40000.0, "maple": 20000.0, "yearn_v3": 14000.0}  # big swap
    # ИЗМЕНЕНО НАМЕРЕННО (инв. №16, ADR-339): демпфер теперь судит по часам ЦИКЛА. Раньше
    # он брал настенные часы, и перекладка «через 24 ч после размещения» в июне-2026
    # выглядела для него ходом трёхмесячной давности — блокировать ему было нечего.
    # По честным часам такой ход демпфер правильно держит (удержание 72 ч, недельный
    # бюджет выбран размещением). Предмет этого теста — не частота, поэтому ход
    # перенесён за пределы обоих окон: через 9 дней. Утверждения не тронуты.
    res = _run(
        tmp_path,
        APY,
        changed,
        now=datetime(2026, 6, 19, 8, 0, tzinfo=timezone.utc),
    )
    assert res.traded is True
    trades = _load(tmp_path, "trades.json")
    assert len(trades) == 2


def test_large_reshuffle_is_held_when_cio_says_hold(tmp_path, monkeypatch):
    """Обратная сторона: CIO сказал «держать» ⇒ та же перетасовка НЕ проходит."""
    _cio_says(monkeypatch, "HOLD", ["payback_too_long:43.6d"])
    first = _run(tmp_path, APY, TARGET)
    assert first.traded is True, "первичное размещение не перетасовка — CIO его не судит"
    changed = {"aave_v3": 40000.0, "maple": 20000.0, "yearn_v3": 14000.0}
    res = _run(tmp_path, APY, changed,
               now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc))
    assert res.traded is False, "CIO сказал держать, а книга перетасована"
    assert len(_load(tmp_path, "trades.json")) == 1
    assert any("cio_armed: HOLD" in n for n in (res.notes or [])), res.notes


def test_derisk_passes_even_when_cio_says_hold(tmp_path, monkeypatch):
    """Стоп-кран не стоит в очереди за экономикой: сокращение проходит при «держать»."""
    _cio_says(monkeypatch, "HOLD", ["cooldown_active"])
    _run(tmp_path, APY, TARGET)
    cut = {"aave_v3": 30000.0, "morpho_blue": 20000.0, "yearn_v3": 14000.0}
    res = _run(tmp_path, APY, cut, now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc))
    assert res.traded is True, "сокращение позиции задержано вердиктом CIO"


# ─── Dry-run & summary integrity ──────────────────────────────────────────────


def test_dry_run_writes_nothing(tmp_path):
    cr.run_cycle(
        data_dir=tmp_path,
        now=datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc),
        orchestrator_fn=_orch_fn(APY),
        allocator=_FakeAllocator(TARGET),
        write=False,
    )
    assert _load(tmp_path, "trades.json") is None
    assert _load(tmp_path, "equity_curve_daily.json") is None
    assert _load(tmp_path, "paper_trading_status.json") is None


def test_summary_has_golive_compatible_num_days(tmp_path):
    # readiness_checker C005 reads summary.num_days — must remain present.
    _run(tmp_path, APY, TARGET)
    _run(tmp_path, APY, TARGET, now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc))
    eq = _load(tmp_path, "equity_curve_daily.json")
    assert "summary" in eq and "num_days" in eq["summary"]
    assert eq["summary"]["num_days"] == 2
    assert eq["summary"]["positive_days"] >= 1


def test_demo_curve_archived_and_real_curve_starts_at_capital(tmp_path):
    # Simulate a pre-existing DEMO equity curve (source != cycle_runner).
    demo = {
        "source": "equity_curve",
        "is_demo": True,
        "summary": {"num_days": 8, "end_equity": 98815.79},
        "daily": [{"date": "2026-05-22", "open_equity": 99000.0, "close_equity": 98815.79}],
    }
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps(demo))
    res = _run(tmp_path, APY, TARGET)
    # Real curve starts fresh from capital, not the demo's 98,815.79.
    # ADR-298 (инвариант #16 — изменение НАМЕРЕННОЕ, решение владельца ADR-286 §1):
    # издержка перекладки теперь СПИСЫВАЕТСЯ в кривую. Первый цикл разворачивает
    # $100k из кэша в пулы, и это стоит денег: до правки день закрывался ровно на
    # начисленный доход, потому что за собственные ходы книга не платила НИКОГДА.
    # Проверяется не новое число, а РАВЕНСТВО: close = open + доход − издержка,
    # плюс положительный контроль «издержка > 0 на дне развёртывания».
    expected_yield = sum(TARGET[p] * APY[p] / 100 / 365 for p in TARGET)
    _bar = _load(tmp_path, "equity_curve_daily.json")["daily"][-1]
    assert res.current_equity == pytest.approx(
        100_000 + expected_yield - _bar["cost_usd"], abs=1e-2)
    eq = _load(tmp_path, "equity_curve_daily.json")
    assert eq["source"] == "cycle_runner"
    assert eq["is_demo"] is False
    assert len(eq["daily"]) == 1
    # Demo file preserved for audit.
    backup = _load(tmp_path, "equity_curve_daily.demo_backup.json")
    assert backup["is_demo"] is True


def test_strategy_loop_flag_propagates(tmp_path):
    # ADR-033: strategy_loop_active only propagates when mode="active" in
    # strategy_config.json; default (file absent) = "shadow" → forced False.
    import json as _json
    (tmp_path / "strategy_config.json").write_text(
        _json.dumps({"strategy_loop_mode": "active"})
    )
    res = _run(tmp_path, APY, TARGET, strategy_loop=True)
    assert res.strategy_loop_active is True
    st = _load(tmp_path, "paper_trading_status.json")
    assert st["strategy_loop_active"] is True
    trades = _load(tmp_path, "trades.json")
    assert trades[0]["strategy_loop_active"] is True


# ─── ALLOC-002 oscillation regression (P0) ──────────────────────────────────


# An over-diversified target (24 protocols) — what StrategyAllocator natively
# emits because policy.py caps per-protocol concentration but NOT the protocol
# *count*. Before the ALLOC-002 oscillation fix, the rebalance diff compared the
# persisted ≤8 book against this fresh 24-book every cycle → a phantom ~$122K
# rebalance, then a post-hoc collapse to ≤8 → endless 24↔8 churn.
#
# The book is built with real T1 anchors (so the RiskPolicy gate APPROVES it,
# matching production where the gate let the 24-book through) plus many small
# T2 satellites that push the protocol *count* past the policy_enforcer cap.
_OVERDIV_T1 = {
    "aave_v3": 30_000.0,
    "compound_v3": 20_000.0,
    "spark_susds": 10_000.0,
}  # T1 = 60% → satisfies t1_min (55%)
_OVERDIV_T2 = {f"proto_t2_{i:02d}": 1_500.0 for i in range(21)}  # 21 × $1.5k = $31.5k
_OVERDIV_TARGET = {**_OVERDIV_T1, **_OVERDIV_T2}  # 24 protocols, ~91.5% deployed
_OVERDIV_APY = {p: 4.0 + (i % 5) * 0.1 for i, p in enumerate(_OVERDIV_TARGET)}


def _l1(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    return sum(abs(float(a.get(k, 0.0)) - float(b.get(k, 0.0))) for k in keys)


def _overdiv_orch_fn(apy_map):
    """Orchestrator fake that tiers the over-diversified universe correctly so
    the RiskPolicy gate APPROVES the 24-book (mirrors production, where the gate
    let the over-diversified target through before ALLOC-002 collapsed it)."""
    def _fn(data_dir):
        adapters = [
            {
                "protocol": p,
                "apy_pct": apy_map[p],
                "tvl_usd": 5e8,
                "tvl_source": "live",
                "tier": "T1" if p in _OVERDIV_T1 else "T2",
                "chain": "ethereum:{}".format(p),
                "status": "ok",
            }
            for p in apy_map
        ]
        return SimpleNamespace(adapters=adapters, status="ok", data_freshness="live")

    return _fn


def _run_overdiv(tmp_path, *, now):
    return cr.run_cycle(
        data_dir=tmp_path,
        now=now,
        orchestrator_fn=_overdiv_orch_fn(_OVERDIV_APY),
        allocator=_FakeAllocator(_OVERDIV_TARGET),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,
    )


def test_alloc002_no_oscillation_stable_allocation(tmp_path):
    """Two consecutive cycles on identical market data must converge to a
    STABLE ≤8-protocol book with near-zero turnover on the 2nd run.

    Regression for the ALLOC-002 allocation oscillation: the raw allocator
    target is collapsed to a deterministic policy-compliant book BEFORE the
    rebalance diff, so an unchanged market produces ~zero phantom turnover.
    """
    now = datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc)

    # Run 1 — converge from no prior book.
    res1 = _run_overdiv(tmp_path, now=now)
    assert res1.status == "ok"
    pos1 = _load(tmp_path, "current_positions.json")["positions"]
    # Count cap enforced natively in the cycle output (≤ policy max of 8).
    assert len(pos1) <= 8, f"run1 persisted {len(pos1)} protocols, expected ≤8"

    # Run 2 — identical market data, one day later.
    res2 = _run_overdiv(
        tmp_path, now=datetime(2026, 6, 12, 8, 0, tzinfo=timezone.utc)
    )
    assert res2.status == "ok"
    pos2 = _load(tmp_path, "current_positions.json")["positions"]
    assert len(pos2) <= 8, f"run2 persisted {len(pos2)} protocols, expected ≤8"

    # Stable SET: the kept ≤8 protocols are identical across cycles (deterministic
    # selection — no flip-flopping which 8 are kept).
    assert set(pos1) == set(pos2), (
        f"protocol set flipped between cycles: {set(pos1)} != {set(pos2)}"
    )

    # Near-zero turnover on the 2nd cycle (no phantom ~$122K rebalance). Allow a
    # small band for rounding; the pre-fix value was ~$122,073.
    turnover2 = _l1(pos1, pos2)
    assert turnover2 < 200.0, (
        f"2nd-cycle turnover ${turnover2:,.2f} — oscillation NOT eliminated"
    )
    assert res2.traded is False, "2nd cycle should not trade on unchanged market"


def test_alloc002_compliant_book_passes_enforcer(tmp_path):
    """The converged book must satisfy the policy_enforcer (≤8 count + caps)."""
    from spa_core.risk.policy_enforcer import validate_positions

    res = _run_overdiv(
        tmp_path, now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc)
    )
    assert res.status == "ok"
    doc = _load(tmp_path, "current_positions.json")
    pos = doc["positions"]
    cap = float(doc.get("capital_usd", 100_000.0))
    cash = cap - sum(pos.values())
    check = validate_positions(positions=pos, capital_usd=cap, cash_usd=cash)
    assert check.passed, (
        "converged book violates enforcer: "
        + str([v.rule for v in check.violations])
    )
    assert len(pos) <= 8


def test_the_damper_really_blocks_a_reshuffle_one_day_after_the_last_move(tmp_path, monkeypatch):
    """ADR-339: ПЕРВЫЙ тест уровня цикла, где демпфер действительно блокирует.

    До ADR-339 демпфер брал настенные часы, и в сценах, живущих в июне-2026, он не
    блокировал НИКОГДА — защита от метания на уровне цикла не проверялась вовсе.
    CIO здесь говорит «действовать», чтобы отказ был ТОЛЬКО демпфера.
    """
    _cio_says(monkeypatch, "ACT")
    _run(tmp_path, APY, TARGET)
    swap = {"aave_v3": 40000.0, "maple": 20000.0, "yearn_v3": 14000.0}
    res = _run(tmp_path, APY, swap, now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc))
    assert res.traded is False, "демпфер пропустил перекладку через сутки после хода"
    assert any("churn_damper" in n for n in (res.notes or [])), res.notes
    later = _run(tmp_path, APY, swap, now=datetime(2026, 6, 19, 8, 0, tzinfo=timezone.utc))
    assert later.traded is True, "за пределами окон демпфер обязан пропустить"


def test_the_cio_measures_the_last_move_on_the_cycle_clock(tmp_path):
    """ADR-339: история CIO (кулдаун, возраст позиций) — по часам цикла, не по настенным.

    Настенные часы в июне-2026 давали «последний ход 90+ дней назад», и ограничители
    частоты CIO были так же пусты, как у демпфера.
    """
    import json as _json
    _run(tmp_path, APY, TARGET)
    swap = {"aave_v3": 40000.0, "maple": 20000.0, "yearn_v3": 14000.0}
    _run(tmp_path, APY, swap, now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc))
    doc = _json.loads((tmp_path / "allocation_rationale.json").read_text(encoding="utf-8"))
    since = (doc.get("history") or {}).get("days_since_last_move")
    assert since is not None and since < 2.0, f"CIO видит последний ход {since} дн назад"

