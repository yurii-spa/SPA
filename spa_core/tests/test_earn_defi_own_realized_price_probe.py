"""Проба приёмки `earn_defi_own_realized_price_reconciles` (ADR-286 §6) — контроль в обе стороны.

Зелёная на целом контуре, красная на КАЖДОМ порванном звене с названным звеном, третий
исход — отдельно, и подстрокой не проходит (`.claude/rules/acceptance.md`, п. 3).

Часы — ВХОД: якорь `NOW` закреплён и передаётся пробе (`now=NOW`), все отметки базы считаются
от него же, поэтому календарь вердикт не двигает. Стенные часы при импорте не читаются вовсе
(первая редакция читала — поймал `test_no_import_time_clock_in_tests`, полный прогон 17.09).
"""
# FROZEN-DATE-OK: injected-clock — якорь NOW передаётся пробе аргументом now= в каждом вызове
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone


from spa_core.monitoring import card_acceptance as ca

PROBE = ca._probe_earn_defi_own_realized_price
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
DAYS = 400


def _day(ago: int, now: datetime = NOW) -> str:
    return (now - timedelta(days=ago)).date().isoformat()


def _ref_price(i: int) -> float:
    return 40_000.0 + 25.0 * i


def _build(tmp_path, *, own=True, own_days=DAYS, skew=None, copy=False, drop_own=(),
           own_newest_ago=1, signal_source="own_chain+fred", signal_rp="own",
           with_signal=True, with_ref=True, with_tables=True, now: datetime = NOW):
    """Собрать одноразовый `earn-defi` с базой движка. Возвращает корень."""
    root = tmp_path / "earn-defi"
    (root / "data").mkdir(parents=True)
    conn = sqlite3.connect(root / "data" / "earn_defi.db")
    if with_tables:
        conn.execute("CREATE TABLE market_data (date TEXT, source TEXT, metric TEXT, value REAL, "
                     "fetched_at_utc TEXT, PRIMARY KEY (date, source, metric))")
        conn.execute("CREATE TABLE signals (id INTEGER PRIMARY KEY, date TEXT, payload TEXT)")
        rows, own_series = [], {}
        for i in range(DAYS):
            d = _day(DAYS - i, now)  # самый свежий день — «вчера»
            rp, supply, mvrv = _ref_price(i), 19_900_000.0, 2.0
            if with_ref:
                rows += [(d, "coinmetrics", "CapMrktCurUSD", rp * mvrv * supply),
                         (d, "coinmetrics", "CapMVRVCur", mvrv),
                         (d, "coinmetrics", "SplyCur", supply)]
            ago = DAYS - i
            if own and i >= DAYS - own_days and ago >= own_newest_ago and ago not in drop_own:
                v = rp if copy else rp * 1.004  # независимый расчёт расходится на доли процента
                if skew and ago == skew[0]:
                    v = rp * (1.0 + skew[1] / 100.0)
                own_series[d] = v
                rows.append((d, "own_chain", "RealizedPriceUSD", v))
        conn.executemany("INSERT INTO market_data VALUES (?,?,?,?,'t')", rows)
        if with_signal:
            sd = max(own_series) if own_series else _day(1, now)
            rp_val = own_series.get(sd) if signal_rp == "own" else signal_rp
            payload = {"date": sd, "inputs": {"source": signal_source},
                       "signals": {"realized_price_usd": rp_val}}
            conn.execute("INSERT INTO signals(date, payload) VALUES (?,?)", (sd, json.dumps(payload)))
    conn.commit()
    conn.close()
    return str(root)


def test_whole_contour_is_satisfied(tmp_path):
    verdict, detail = PROBE(None, root=_build(tmp_path), now=NOW)
    assert verdict == ca.SATISFIED, detail
    assert "own_chain" in detail


# ── каждое порванное звено — красное и НАЗВАНО ───────────────────────────────

def test_link1_no_own_series(tmp_path):
    verdict, detail = PROBE(None, root=_build(tmp_path, own=False), now=NOW)
    assert verdict == ca.NOT_SATISFIED and "звено 1" in detail


def test_link2_too_few_common_days(tmp_path):
    verdict, detail = PROBE(None, root=_build(tmp_path, own_days=364), now=NOW)
    assert verdict == ca.NOT_SATISFIED and "звено 2" in detail and "364" in detail


def test_link2_one_day_over_threshold_is_named(tmp_path):
    verdict, detail = PROBE(None, root=_build(tmp_path, skew=(100, 3.5)), now=NOW)
    assert verdict == ca.NOT_SATISFIED and "звено 2" in detail
    assert _day(100) in detail and "1 из 365" in detail


def test_link2_just_under_threshold_passes(tmp_path):
    verdict, detail = PROBE(None, root=_build(tmp_path, skew=(100, 2.9)), now=NOW)
    assert verdict == ca.SATISFIED, detail


def test_link2_holes_in_window(tmp_path):
    root = _build(tmp_path, drop_own=tuple(range(50, 60)))
    verdict, detail = PROBE(None, root=root, now=NOW)
    assert verdict == ca.NOT_SATISFIED and "дыр" in detail


def test_link2_copy_of_the_reference_is_not_a_calculation(tmp_path):
    verdict, detail = PROBE(None, root=_build(tmp_path, copy=True), now=NOW)
    assert verdict == ca.NOT_SATISFIED and "копия" in detail


def test_link3_stale_series(tmp_path):
    verdict, detail = PROBE(None, root=_build(tmp_path, own_newest_ago=10), now=NOW)
    assert verdict == ca.NOT_SATISFIED and "звено 3" in detail


def test_link4_engine_still_reads_the_vendor(tmp_path):
    root = _build(tmp_path, signal_source="coinmetrics+fred")
    verdict, detail = PROBE(None, root=root, now=NOW)
    assert verdict == ca.NOT_SATISFIED and "звено 4" in detail and "coinmetrics" in detail


def test_link4_source_name_does_not_pass_by_substring(tmp_path):
    root = _build(tmp_path, signal_source="not_own_chain_really+fred")
    verdict, detail = PROBE(None, root=root, now=NOW)
    assert verdict == ca.NOT_SATISFIED and "звено 4" in detail


def test_link4_label_without_the_number_is_not_wiring(tmp_path):
    root = _build(tmp_path, signal_rp=12345.0)
    verdict, detail = PROBE(None, root=root, now=NOW)
    assert verdict == ca.NOT_SATISFIED and "звено 4" in detail and "12345" in detail


def test_link4_no_signal_records(tmp_path):
    verdict, detail = PROBE(None, root=_build(tmp_path, with_signal=False), now=NOW)
    assert verdict == ca.NOT_SATISFIED and "звено 4" in detail


# ── третий исход: «не измерено» — не «выполнено» и не «не выполнено» ─────────

def test_unmeasured_when_repo_absent(tmp_path):
    verdict, detail = PROBE(None, root=str(tmp_path / "nowhere"), now=NOW)
    assert verdict == ca.UNMEASURED and "не измерен" in detail


def test_unmeasured_when_db_absent(tmp_path):
    (tmp_path / "earn-defi").mkdir()
    verdict, _ = PROBE(None, root=str(tmp_path / "earn-defi"), now=NOW)
    assert verdict == ca.UNMEASURED


def test_unmeasured_when_tables_absent(tmp_path):
    verdict, detail = PROBE(None, root=_build(tmp_path, with_tables=False), now=NOW)
    assert verdict == ca.UNMEASURED and "не прочиталась" in detail


def test_unmeasured_when_no_reference_to_compare_with(tmp_path):
    verdict, detail = PROBE(None, root=_build(tmp_path, with_ref=False), now=NOW)
    assert verdict == ca.UNMEASURED and "эталона нет" in detail


# ── проводка: проба достижима ПО ИМЕНИ через реестр, а не только как функция ──

def test_registered_and_reachable_through_the_registry(tmp_path, monkeypatch):
    spec = "earn_defi_own_realized_price_reconciles"
    assert ca.validate_spec(spec) is None
    # через реестр `now=` не передать — проба спросит настоящие часы; стенд строится от них же,
    # и читаются они ВНУТРИ теста, а не при импорте
    monkeypatch.setenv("EARN_DEFI_ROOT", _build(tmp_path, now=datetime.now(timezone.utc)))
    verdict, detail = ca.run_probe(spec)
    assert verdict == ca.SATISFIED, detail
    monkeypatch.setenv("EARN_DEFI_ROOT", str(tmp_path / "nowhere"))
    assert ca.run_probe(spec)[0] == ca.UNMEASURED


def test_probe_never_writes_to_the_engine_db(tmp_path):
    root = _build(tmp_path)
    db = os.path.join(root, "data", "earn_defi.db")
    before = open(db, "rb").read()
    PROBE(None, root=root, now=NOW)
    assert open(db, "rb").read() == before
