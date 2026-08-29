# FROZEN-DATE-OK: injected-clock — единственный якорь времени в файле это NOW,
# он передаётся в audit(now=NOW), а отметка книги ВЫЧИСЛЯЕТСЯ из него же
# (NOW.isoformat()). Обе стороны закреплены одним значением, календарь на
# вердикт не влияет; литерал здесь — сам якорь, а не отметка свежести.
"""Allocation Auditor: каждый тест — реальная поломка, а не гипотеза.

# LLM_FORBIDDEN

Все входы инъектируются в ``tmp_path``: тест НИКОГДА не читает живой ``data/``
(иначе вердикт решает состояние хоста, а не проверяемое поведение) и ничего
туда не пишет.

Половина набора сторожит не находки, а ТРЕТИЙ ИСХОД: «не измерено» обязано
оставаться «не измерено». Сторож, у которого два исхода вместо трёх, отвечает
«нарушений нет» на отсутствие данных — ровно тот класс fail-OPEN, ради которого
аудитор и написан.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.agents import allocation_auditor as aa
from spa_core.agents.allocation_auditor import (
    OK,
    UNCHECKED,
    VIOLATION,
    AllocationAuditor,
)
from spa_core.risk.policy import RiskConfig

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)   # часы инъектированы, календарь не влияет

_TIERS = {"alpha": "T1", "beta": "T2", "gamma": "T2", "delta": "T2"}
_CHAINS = {"alpha": "ethereum", "beta": "ethereum", "gamma": "ethereum", "delta": "base"}


def _book(tmp_path, positions: dict, capital: float = 100_000.0,
          apy: dict | None = None, name: str = "book.json"):
    doc = {
        "generated_at": NOW.isoformat(),   # из того же якоря, что и audit(now=NOW)
        "capital_usd": capital,
        "positions": positions,
    }
    if apy:
        doc["positions_detail"] = {p: {"usd": positions.get(p), "apy_pct": v}
                                   for p, v in apy.items()}
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _orch(tmp_path, rows: list, name: str = "orch.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"adapters": rows}), encoding="utf-8")
    return p


def _live_rows(protocols, tier_by=None):
    tier_by = tier_by or _TIERS
    return [{"protocol": p, "tier": tier_by.get(p, "T2"), "tvl_source": "live"}
            for p in protocols]


def _auditor(book, orch, tiers=None, chains=None):
    return AllocationAuditor(
        positions_path=book,
        orchestrator_path=orch,
        config=RiskConfig(),
        chain_map_provider=lambda: dict(chains if chains is not None else _CHAINS),
        tier_provider=lambda p: (tiers if tiers is not None else _TIERS).get(p),
    )


def _by_rule(res, rule_id):
    return [f for f in res.findings if f.rule_id == rule_id]


# ── находки ──────────────────────────────────────────────────────────────
def test_concentration_breach_detected(tmp_path):
    """T2 держит 25 % при потолке 20 % (CAP-02)."""
    book = _book(tmp_path, {"alpha": 30_000.0, "beta": 25_000.0})
    res = _auditor(book, _orch(tmp_path, _live_rows(["alpha", "beta"]))).audit(now=NOW)
    beta = [f for f in _by_rule(res, "CAP-02") if f.subject == "beta"]
    assert len(beta) == 1 and beta[0].verdict == VIOLATION
    assert beta[0].observed == pytest.approx(0.25) and beta[0].limit == pytest.approx(0.20)
    assert res.verdict == VIOLATION


def test_t1_at_its_cap_is_not_a_breach(tmp_path):
    """Ровно 40 % у T1 — потолок, а не превышение: границу проверяем отдельно."""
    book = _book(tmp_path, {"alpha": 40_000.0})
    res = _auditor(book, _orch(tmp_path, _live_rows(["alpha"]))).audit(now=NOW)
    assert [f.verdict for f in _by_rule(res, "CAP-01")] == [OK]


def test_t2_total_breach_detected(tmp_path):
    """Три T2 по 20 % = 60 % против совокупного потолка 50 % (CAP-04)."""
    book = _book(tmp_path, {"beta": 20_000.0, "gamma": 20_000.0, "delta": 20_000.0})
    res = _auditor(book, _orch(tmp_path, _live_rows(["beta", "gamma", "delta"]))).audit(now=NOW)
    t2 = _by_rule(res, "CAP-04")
    assert len(t2) == 1 and t2[0].verdict == VIOLATION
    assert t2[0].observed == pytest.approx(0.60)


def test_cash_floor_breach_detected(tmp_path):
    """Размещено 97 % — буфер 3 % против пола 5 % (CAP-08)."""
    book = _book(tmp_path, {"alpha": 39_000.0, "beta": 19_000.0,
                            "gamma": 19_000.0, "delta": 20_000.0})
    res = _auditor(book, _orch(tmp_path, _live_rows(_TIERS))).audit(now=NOW)
    cash = _by_rule(res, "CAP-08")
    assert len(cash) == 1 and cash[0].verdict == VIOLATION
    assert cash[0].observed == pytest.approx(0.03)


def test_protocol_count_breach_detected(tmp_path):
    """Девять профинансированных против потолка 8 (CAP-06, ALLOC-002)."""
    pos = {f"p{i}": 5_000.0 for i in range(9)}
    tiers = {p: "T2" for p in pos}
    chains = {p: "ethereum" for p in pos}
    res = _auditor(_book(tmp_path, pos), _orch(tmp_path, _live_rows(pos, tiers)),
                   tiers=tiers, chains=chains).audit(now=NOW)
    cnt = _by_rule(res, "CAP-06")
    assert len(cnt) == 1 and cnt[0].verdict == VIOLATION and cnt[0].observed == 9.0


def test_tier_disagreement_detected(tmp_path):
    """Живой случай 29.08: канон говорит T2, снимок оркестратора — T1.

    Потолок протокола зависит от того, кого читать (20 % против 40 %), и вместе
    с ним разъезжается совокупная доля T2 — в тот день на 15 пунктов.
    """
    book = _book(tmp_path, {"alpha": 20_000.0, "gamma": 15_000.0})
    orch = _orch(tmp_path, [
        {"protocol": "alpha", "tier": "T1", "tvl_source": "live"},
        {"protocol": "gamma", "tier": "T1", "tvl_source": "live"},   # канон: T2
    ])
    res = _auditor(book, orch).audit(now=NOW)
    bad = [f for f in _by_rule(res, "TIER-01") if f.verdict == VIOLATION]
    assert [f.subject for f in bad] == ["gamma"]
    assert "20%" in bad[0].detail and "40%" in bad[0].detail


def test_tvl_not_live_is_a_violation(tmp_path):
    """Пол $5M, пройденный на литерале, — не пройденный пол (ADR-053, ADM-07/08)."""
    book = _book(tmp_path, {"alpha": 20_000.0})
    orch = _orch(tmp_path, [{"protocol": "alpha", "tier": "T1", "tvl_source": "static"}])
    res = _auditor(book, orch).audit(now=NOW)
    tvl = _by_rule(res, "ADM-07/08")
    assert len(tvl) == 1 and tvl[0].verdict == VIOLATION and "static" in tvl[0].detail


def test_funded_but_class_blocked_protocol_is_a_violation(tmp_path, monkeypatch):
    """Advisory / gsm-заблокированный протокол держит капитал (ADM-05/06, дефект D3)."""
    from spa_core.allocator import allocator as alloc_mod
    monkeypatch.setattr(alloc_mod, "_adapter_class_gate",
                        lambda p: (False, "advisory") if p == "beta" else (True, None))
    book = _book(tmp_path, {"alpha": 20_000.0, "beta": 15_000.0})
    res = _auditor(book, _orch(tmp_path, _live_rows(["alpha", "beta"]))).audit(now=NOW)
    bad = [f for f in _by_rule(res, "ADM-05/06") if f.verdict == VIOLATION]
    assert [f.subject for f in bad] == ["beta"] and "advisory" in bad[0].detail


def test_below_median_concentration_detected(tmp_path):
    """Доходность ниже медианы при доле выше половины тир-потолка (ECON-10)."""
    pos = {"alpha": 20_000.0, "beta": 15_000.0, "gamma": 10_000.0}
    apy = {"alpha": 6.0, "beta": 3.0, "gamma": 5.0}     # медиана 5.0, beta ниже
    res = _auditor(_book(tmp_path, pos, apy=apy),
                   _orch(tmp_path, _live_rows(pos))).audit(now=NOW)
    bad = [f for f in _by_rule(res, "ECON-10") if f.verdict == VIOLATION]
    assert [f.subject for f in bad] == ["beta"]


def test_no_false_alarm_on_a_clean_book(tmp_path):
    """Обратный контроль: книга в правилах ⇒ ни одного нарушения и ни одного «не измерено»."""
    pos = {"alpha": 30_000.0, "beta": 15_000.0, "gamma": 15_000.0}
    apy = {"alpha": 5.0, "beta": 5.0, "gamma": 5.0}
    res = _auditor(_book(tmp_path, pos, apy=apy),
                   _orch(tmp_path, _live_rows(pos))).audit(now=NOW)
    assert res.counts[VIOLATION] == 0, [f.detail for f in res.findings if f.verdict != OK]
    assert res.counts[UNCHECKED] == 0, [f.detail for f in res.findings if f.verdict == UNCHECKED]
    assert res.verdict == OK


# ── третий исход: «не измерено» обязано выжить ───────────────────────────
def test_unknown_tier_is_unchecked_never_ok(tmp_path):
    """Тир неизвестен ⇒ потолок назвать нечем. Подстановка «по умолчанию T2» занижает."""
    book = _book(tmp_path, {"alpha": 30_000.0, "zeta": 15_000.0})
    res = _auditor(book, _orch(tmp_path, _live_rows(["alpha", "zeta"]))).audit(now=NOW)
    unk = [f for f in _by_rule(res, "CAP-01/02") if f.subject == "zeta"]
    assert len(unk) == 1 and unk[0].verdict == UNCHECKED
    # и совокупные доли тиров тоже не выдумываются
    assert all(f.verdict == UNCHECKED for f in _by_rule(res, "CAP-04"))
    assert res.verdict != OK


def test_unknown_chain_is_unchecked_not_assumed_ethereum(tmp_path):
    """Живой случай 29.08: у morpho_steakhouse нет цепочки в карте."""
    book = _book(tmp_path, {"alpha": 30_000.0, "beta": 15_000.0})
    res = _auditor(book, _orch(tmp_path, _live_rows(["alpha", "beta"])),
                   chains={"alpha": "ethereum"}).audit(now=NOW)
    ch = _by_rule(res, "CAP-13/14")
    assert len(ch) == 1 and ch[0].verdict == UNCHECKED and "beta" in ch[0].detail
    assert not _by_rule(res, "CAP-13"), "потолок цепочки не должен считаться на догадке"


def test_missing_book_is_unchecked_not_clean(tmp_path):
    res = _auditor(tmp_path / "нет.json", _orch(tmp_path, [])).audit(now=NOW)
    assert res.verdict == UNCHECKED and res.counts[VIOLATION] == 0
    assert res.counts[OK] == 0, "отсутствие книги не может дать ни одного OK"


def test_empty_book_is_not_a_clean_pass(tmp_path):
    """Ноль проверок — это не «нарушений нет»."""
    res = _auditor(_book(tmp_path, {}), _orch(tmp_path, [])).audit(now=NOW)
    assert res.verdict == UNCHECKED


def test_nonfinite_amount_is_unchecked_not_silently_dropped(tmp_path):
    """NaN в сумме позиции: молчаливый пропуск занизил бы все доли."""
    p = tmp_path / "nan.json"
    p.write_text('{"capital_usd": 100000.0, "positions": {"alpha": 30000.0, "beta": null}}',
                 encoding="utf-8")
    res = _auditor(p, _orch(tmp_path, _live_rows(["alpha"]))).audit(now=NOW)
    book_findings = [f for f in _by_rule(res, "BOOK") if f.subject == "beta"]
    assert len(book_findings) == 1 and book_findings[0].verdict == UNCHECKED
    assert res.verdict != OK


def test_unreadable_orchestrator_does_not_silently_pass_tvl(tmp_path):
    res = _auditor(_book(tmp_path, {"alpha": 30_000.0}), tmp_path / "нет-снимка.json").audit(now=NOW)
    assert all(f.verdict == UNCHECKED for f in _by_rule(res, "ADM-07/08"))
    assert all(f.verdict == UNCHECKED for f in _by_rule(res, "TIER-01"))
    assert res.verdict != OK


def test_zero_capital_refuses_instead_of_dividing(tmp_path):
    res = _auditor(_book(tmp_path, {"alpha": 1.0}, capital=0.0),
                   _orch(tmp_path, _live_rows(["alpha"]))).audit(now=NOW)
    assert res.verdict == UNCHECKED and res.counts[OK] == 0


# ── контракт наружу ──────────────────────────────────────────────────────
def test_exit_codes_distinguish_all_three_outcomes(tmp_path):
    """0 — в норме, 1 — не измерено, 2 — нарушение. «Не измерено» ≠ успех."""
    assert aa._EXIT[OK] == 0 and aa._EXIT[UNCHECKED] == 1 and aa._EXIT[VIOLATION] == 2


def test_artifact_is_written_atomically_and_reloads(tmp_path):
    pos = {"alpha": 30_000.0, "beta": 15_000.0, "gamma": 15_000.0}
    apy = {"alpha": 5.0, "beta": 5.0, "gamma": 5.0}
    auditor = _auditor(_book(tmp_path, pos, apy=apy), _orch(tmp_path, _live_rows(pos)))
    res = auditor.audit(now=NOW)
    out = auditor.save(res, tmp_path / "audit.json")
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["verdict"] == OK and doc["capital_usd"] == 100_000.0
    assert doc["generated_at"] == NOW.isoformat() == doc["book_as_of"]
    assert {"rule_id", "verdict", "subject", "detail"} <= set(doc["findings"][0])
    assert not list(tmp_path.glob("*.tmp")), "временный файл не убран за собой"


def test_auditor_never_imports_execution():
    """Read-only домен: инвариант 6.

    Проверяется РАЗБОРОМ импортов, а не поиском подстроки: этот модуль в своей
    же докстроке пишет «не импортирует ``spa_core/execution/``», и текстовый
    сторож покраснел бы на объяснении собственного правила. Сторож обязан
    отличать код от прозы.
    """
    import ast

    text = Path(aa.__file__).read_text(encoding="utf-8")
    modules = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    assert not [m for m in modules if m.startswith("spa_core.execution")], sorted(modules)
    assert "# LLM_FORBIDDEN" in text
