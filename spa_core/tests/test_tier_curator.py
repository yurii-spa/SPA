"""Тесты tier_curator (Y4, ADR-055 «тир — динамический», первый шаг —
advisory-отчёт кураторов).

Ключевые положительные контроли fail-CLOSED:
* деградация (мёртвый фид / Tier-A BLOCK / TVL<floor / held без живого TVL)
  → DEMOTE_SIGNAL, не KEEP;
* стабильность с ПОЛНЫМ пакетом доказательств → PROMOTE_CANDIDATE
  (T2→T1 owner-gated);
* отсутствие данных → UNCHECKED, НЕ KEEP (молчание ≠ подтверждение);
* отсутствие Tier-A записи блокирует промоушен (нет оценки ≠ «чисто»);
* advisory-инвариант: отчёт никто не потребляет для смены тира, модуль не
  импортирует execution/kill/gates, curate() ничего не пишет.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.analytics import _apy_series
from spa_core.analytics import tier_curator as tc
from spa_core.risk.policy import RiskConfig

NOW = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)
ISO = NOW.isoformat()
SPA_CORE = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _fresh_series_cache():
    _apy_series.clear_cache()
    yield
    _apy_series.clear_cache()


def _orch_row(proto: str, tier: str = "T2", *, status: str = "ok",
              live: bool = True, tvl_source: str = "live",
              tvl: float = 30_000_000.0, apy: float = 4.0,
              error: str | None = None) -> dict:
    return {"protocol": proto, "tier": tier, "status": status,
            "live_data": live, "tvl_source": tvl_source,
            "tvl_usd": (tvl if tvl_source else None),
            "apy_pct": apy, "error": error}


def _write(data_dir: Path, *, orch_rows=None, status_adapters=None,
           positions=None, feed=None, tier_a=None, tier_b=None,
           series=None, ts: str = ISO) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    if orch_rows is not None:
        (data_dir / tc.ORCH_FILE).write_text(json.dumps(
            {"generated_at": ts, "adapters": orch_rows}), encoding="utf-8")
    if status_adapters is not None:
        (data_dir / tc.ADAPTER_STATUS_FILE).write_text(json.dumps(
            {"generated_at": ts, "adapters": status_adapters}),
            encoding="utf-8")
    if positions is not None or feed is not None:
        (data_dir / tc.POSITIONS_FILE).write_text(json.dumps(
            {"generated_at": ts, "positions": positions or {},
             "feed_coverage": feed or {}}), encoding="utf-8")
    if tier_a is not None:
        (data_dir / tc.TIER_A_FILE).write_text(json.dumps(
            {"generated_at": ts, "signals": tier_a, "protocols": tier_a}),
            encoding="utf-8")
    if tier_b is not None:
        (data_dir / tc.TIER_B_FILE).write_text(json.dumps(
            {"generated_at": ts, "signals": tier_b, "protocols": tier_b}),
            encoding="utf-8")
    if series is not None:
        (data_dir / "apy_series_daily.json").write_text(json.dumps(
            {"series": series}), encoding="utf-8")
    return data_dir


def _stable_series(proto: str, n: int = 30, apy: float = 4.0) -> dict:
    last = NOW.date()
    rows = [[(last - timedelta(days=n - 1 - i)).isoformat(), apy]
            for i in range(n)]
    return {proto: rows}


# ─── Демоут-сигналы (деградация → немедленно, fail-CLOSED) ───────────────────

def test_dead_feed_is_demote_signal(tmp_path):
    dd = _write(tmp_path, orch_rows=[
        _orch_row("morpho_blue", status="error", live=False,
                  tvl_source=None, tvl=0, apy=None, error="live_feed_unavailable")])
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["morpho_blue"]
    assert v["verdict"] == tc.VERDICT_DEMOTE
    assert any("feed_dead" in r for r in v["reasons"])


def test_tier_a_block_is_demote_signal(tmp_path):
    dd = _write(tmp_path,
                orch_rows=[_orch_row("euler_v2")],
                tier_a={"euler_v2": {"signal": "BLOCK", "score": 82.0,
                                     "reason": "oracle=score 82.0",
                                     "triggered_by": ["oracle"]}})
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["euler_v2"]
    assert v["verdict"] == tc.VERDICT_DEMOTE
    assert any("tier_a_block" in r for r in v["reasons"])


def test_held_without_live_tvl_is_demote_and_flagged(tmp_path):
    """Реальный кейс живой книги: morpho_steakhouse $40k при tvl_source=static."""
    dd = _write(tmp_path,
                status_adapters={"morpho_steakhouse": {"tier": 1, "active": True}},
                positions={"morpho_steakhouse": 40_000.0},
                feed={"tvl_sources": {"morpho_steakhouse": "static"},
                      "apy_sources": {"morpho_steakhouse": "live"}})
    rep = tc.curate(data_dir=dd, now=NOW)
    v = rep["verdicts"]["morpho_steakhouse"]
    assert v["verdict"] == tc.VERDICT_DEMOTE
    assert any("held_without_live_tvl" in r for r in v["reasons"])
    assert rep["summary"]["held_flagged"] == ["morpho_steakhouse"]


def test_live_tvl_below_floor_is_demote_signal(tmp_path):
    dd = _write(tmp_path, orch_rows=[_orch_row("pendle", tier="T3",
                                               tvl=3_000_000.0)])
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["pendle"]
    assert v["verdict"] == tc.VERDICT_DEMOTE
    assert any("tvl_below_floor" in r for r in v["reasons"])


def test_apy_outside_policy_bounds_is_demote_signal(tmp_path):
    dd = _write(tmp_path, orch_rows=[_orch_row("pendle", tier="T3", apy=45.0)])
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["pendle"]
    assert v["verdict"] == tc.VERDICT_DEMOTE
    assert any("apy_out_of_policy_bounds" in r for r in v["reasons"])


def test_stale_book_held_position_still_demotes(tmp_path):
    """Протухшая книга (5 дней) не отбеливает held-позицию: провенанс из
    протухшего feed_coverage не считается живым → DEMOTE (fail-CLOSED)."""
    old = (NOW - timedelta(days=5)).isoformat()
    dd = _write(tmp_path,
                positions={"maple": 20_000.0},
                feed={"tvl_sources": {"maple": "live"},
                      "apy_sources": {"maple": "live"}},
                ts=old)
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["maple"]
    assert v["verdict"] == tc.VERDICT_DEMOTE
    assert any("held_without_live_tvl" in r for r in v["reasons"])


# ─── Промоушен (только рекомендация, полный пакет доказательств) ─────────────

def _promotable(tmp_path, proto="yearn_v3", tier="T2"):
    return _write(
        tmp_path,
        orch_rows=[_orch_row(proto, tier=tier, tvl=30_000_000.0, apy=4.0)],
        tier_a={proto: {"signal": "OK", "score": 12.0,
                        "reason": "no_active_tier_a_signal",
                        "triggered_by": []}},
        tier_b={proto: {"composite_risk_0_100": 41.0}},
        series=_stable_series(proto))


def test_stable_t2_is_promote_candidate_owner_gated(tmp_path):
    dd = _promotable(tmp_path)
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["yearn_v3"]
    assert v["verdict"] == tc.VERDICT_PROMOTE
    assert v["target_tier"] == "T1"
    assert v["owner_gated"] is True  # промоушен в T1 owner-gated (ADR-055)


def test_stable_t3_targets_t2_not_owner_gated(tmp_path):
    dd = _promotable(tmp_path, proto="pendle", tier="T3")
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["pendle"]
    assert v["verdict"] == tc.VERDICT_PROMOTE
    assert v["target_tier"] == "T2"
    assert v["owner_gated"] is False


def test_missing_tier_a_entry_blocks_promotion(tmp_path):
    """Fail-CLOSED контроль: «нет Tier-A записи» ≠ «чисто». Тот же полный
    пакет, но без Tier-A оценки → KEEP, не PROMOTE_CANDIDATE."""
    proto = "yearn_v3"
    dd = _write(
        tmp_path,
        orch_rows=[_orch_row(proto, tvl=30_000_000.0, apy=4.0)],
        tier_b={proto: {"composite_risk_0_100": 41.0}},
        series=_stable_series(proto))
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"][proto]
    assert v["verdict"] == tc.VERDICT_KEEP
    assert any("tier_a_not_evaluated_fresh" in r for r in v["reasons"])


def test_tier_a_warn_blocks_promotion(tmp_path):
    dd = _promotable(tmp_path)
    doc = json.loads((dd / tc.TIER_A_FILE).read_text())
    doc["signals"]["yearn_v3"] = {"signal": "WARN", "score": 55.0,
                                  "reason": "x=score 55.0",
                                  "triggered_by": ["x"]}
    doc["protocols"] = doc["signals"]
    (dd / tc.TIER_A_FILE).write_text(json.dumps(doc))
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["yearn_v3"]
    assert v["verdict"] == tc.VERDICT_KEEP
    assert any("tier_a_not_clean" in r for r in v["reasons"])


def test_short_history_blocks_promotion(tmp_path):
    dd = _promotable(tmp_path)
    (dd / "apy_series_daily.json").write_text(json.dumps(
        {"series": _stable_series("yearn_v3", n=5)}))
    _apy_series.clear_cache()
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["yearn_v3"]
    assert v["verdict"] == tc.VERDICT_KEEP
    assert any("apy_history_short" in r for r in v["reasons"])


def test_unstable_apy_blocks_promotion(tmp_path):
    dd = _promotable(tmp_path)
    last = NOW.date()
    rows = [[(last - timedelta(days=29 - i)).isoformat(),
             2.0 if i % 2 else 9.0] for i in range(30)]
    (dd / "apy_series_daily.json").write_text(json.dumps(
        {"series": {"yearn_v3": rows}}))
    _apy_series.clear_cache()
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["yearn_v3"]
    assert v["verdict"] == tc.VERDICT_KEEP
    assert any("apy_unstable" in r for r in v["reasons"])


def test_t1_is_never_promote_candidate(tmp_path):
    dd = _promotable(tmp_path, proto="aave_v3", tier="T1")
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["aave_v3"]
    assert v["verdict"] == tc.VERDICT_KEEP
    assert any("already_T1" in r for r in v["reasons"])


# ─── UNCHECKED — не KEEP (положительный контроль fail-CLOSED) ────────────────

def test_no_evidence_is_unchecked_not_keep(tmp_path):
    """Протокол есть только в adapter_status со static-литералами: живого
    провенанса нет, Tier-A не оценивал → UNCHECKED. KEEP был бы fail-OPEN."""
    dd = _write(tmp_path, status_adapters={
        "sfrax": {"tier": 2, "active": True, "tvl_usd": 800_000_000.0,
                  "apy": 6.0}})
    v = tc.curate(data_dir=dd, now=NOW)["verdicts"]["sfrax"]
    assert v["verdict"] == tc.VERDICT_UNCHECKED
    assert v["verdict"] != tc.VERDICT_KEEP
    assert any("no_live_evidence" in r for r in v["reasons"])


def test_stale_orchestrator_downgrades_to_unchecked(tmp_path):
    """Свежая вчера, протухшая сегодня: та же строка оркестратора возрастом
    5 дней перестаёт быть доказательством → UNCHECKED (контроль в обе
    стороны: со свежим ts тот же протокол — KEEP)."""
    row = [_orch_row("euler_v2", tvl=8_000_000.0, apy=3.0)]
    fresh = tc.curate(data_dir=_write(tmp_path / "a", orch_rows=row),
                      now=NOW)["verdicts"]["euler_v2"]
    assert fresh["verdict"] == tc.VERDICT_KEEP
    old_ts = (NOW - timedelta(days=5)).isoformat()
    stale = tc.curate(data_dir=_write(tmp_path / "b", orch_rows=row, ts=old_ts),
                      now=NOW)["verdicts"]["euler_v2"]
    assert stale["verdict"] == tc.VERDICT_UNCHECKED


def test_empty_and_broken_data_dir_do_not_raise(tmp_path):
    rep = tc.curate(data_dir=tmp_path / "empty", now=NOW)
    assert rep["verdicts"] == {} and rep["summary"]["total"] == 0
    bad = tmp_path / "bad"
    bad.mkdir()
    for name in (tc.ORCH_FILE, tc.ADAPTER_STATUS_FILE, tc.POSITIONS_FILE,
                 tc.TIER_A_FILE, tc.TIER_B_FILE):
        (bad / name).write_text("{not json", encoding="utf-8")
    rep = tc.curate(data_dir=bad, now=NOW)
    assert rep["verdicts"] == {}


def test_summary_counts_are_consistent(tmp_path):
    dd = _promotable(tmp_path)
    _write(dd, orch_rows=None, status_adapters={
        "sfrax": {"tier": 2, "active": True}})
    # _write выше перезаписал только adapter_status; orch/tier_a/series целы
    rep = tc.curate(data_dir=dd, now=NOW)
    s = rep["summary"]
    assert s["total"] == len(rep["verdicts"])
    assert (s["keep"] + s["demote_signal"] + s["promote_candidate"]
            + s["unchecked"]) == s["total"]


# ─── Пороги — из RiskPolicy v1.0, не выдуманы (parity) ───────────────────────

def test_thresholds_match_riskconfig():
    cfg = RiskConfig()
    assert tc.TVL_FLOOR_USD == float(cfg.min_tvl_usd)
    assert tc.APY_MIN_PCT == float(cfg.min_apy_for_new_position)
    assert tc.APY_MAX_PCT == float(cfg.max_apy_for_new_position)
    from spa_core.analytics.signal_aggregator import (BLOCK_THRESHOLD,
                                                      WARN_THRESHOLD)
    rep_thr = tc.curate(data_dir=Path("/nonexistent"), now=NOW)["thresholds"]
    assert rep_thr["tvl_floor_usd"] == float(cfg.min_tvl_usd)
    assert rep_thr["tier_a_block"] == BLOCK_THRESHOLD
    assert rep_thr["tier_a_warn"] == WARN_THRESHOLD


# ─── Запись: только через write_report, атомарно; curate read-only ──────────

def test_curate_is_read_only(tmp_path):
    dd = _promotable(tmp_path)
    before = {p.name: p.stat().st_mtime_ns for p in dd.iterdir()}
    tc.curate(data_dir=dd, now=NOW)
    after = {p.name: p.stat().st_mtime_ns for p in dd.iterdir()}
    assert after == before
    assert not (dd / tc.REPORT_FILENAME).exists()


def test_write_report_writes_atomically_and_matches(tmp_path, monkeypatch):
    dd = _promotable(tmp_path)
    calls = []
    from spa_core.utils import atomic as atomic_mod
    real = atomic_mod.atomic_save

    def spy(data, path, indent=2):
        calls.append(str(path))
        return real(data, path, indent)

    monkeypatch.setattr(atomic_mod, "atomic_save", spy)
    doc = tc.write_report(data_dir=dd, now=NOW)
    assert calls == [str(dd / tc.REPORT_FILENAME)]
    on_disk = json.loads((dd / tc.REPORT_FILENAME).read_text(encoding="utf-8"))
    assert on_disk == doc
    assert doc["summary"]["promote_candidate"] == 1
    assert not list(dd.glob("*.tmp"))  # никаких хвостов временных файлов


def test_report_carries_advisory_note(tmp_path):
    doc = tc.curate(data_dir=tmp_path, now=NOW)
    note = doc["advisory_note"]
    assert "never changes tiers" in note
    assert "separate ADR" in note
    assert "owner-gated" in note


# ─── Advisory-инвариант на уровне исходников ─────────────────────────────────

def test_curator_never_imports_execution_or_gate_domains():
    text = (SPA_CORE / "analytics" / "tier_curator.py").read_text(
        encoding="utf-8")
    for forbidden in ("spa_core.execution", "kill_switch", "cycle_gates",
                      "pre_cutover_gate"):
        assert forbidden not in text, forbidden


def test_no_module_consumes_report_to_mutate_tiers():
    """Никто в runtime-коде не ЧИТАЕТ tier_curator_report.json и не импортирует
    curate() для смены тира: упоминания допустимы только в самом модуле
    (константа) и в cycle_runner (только write_report, писатель)."""
    allowed = {SPA_CORE / "analytics" / "tier_curator.py",
               SPA_CORE / "paper_trading" / "cycle_runner.py"}
    offenders = []
    for py in SPA_CORE.rglob("*.py"):
        if py.parts and "tests" in py.parts:
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        if "tier_curator" in text and py not in allowed:
            offenders.append(str(py))
    assert offenders == [], offenders
    # cycle_runner: только write_report, самого файла отчёта он не читает
    runner = (SPA_CORE / "paper_trading" / "cycle_runner.py").read_text(
        encoding="utf-8")
    assert "from spa_core.analytics.tier_curator import write_report" in runner
    assert "tier_curator_report.json" not in runner.replace(
        "data/tier_curator_report.json", "")  # упоминание только в комменте
    assert "import curate" not in runner


def test_cycle_hook_is_non_critical():
    """Хук в цикле обёрнут в try/except и на падении лишь предупреждает."""
    runner = (SPA_CORE / "paper_trading" / "cycle_runner.py").read_text(
        encoding="utf-8")
    m = re.search(
        r"try:\s*\n\s*from spa_core\.analytics\.tier_curator import "
        r"write_report", runner)
    assert m, "tier_curator import must live inside a try-block"
    assert "tier_curator report failed (non-critical)" in runner
