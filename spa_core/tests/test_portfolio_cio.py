"""Portfolio CIO — 15 сценариев §37 задания владельца + отказы + детерминизм.

Каждый тест здесь — не «проверка функции», а ВОПРОС ВЛАДЕЛЬЦА, заданный кодом.
Пятнадцать сценариев взяты из §37 дословно; к ним добавлены отказы (то, что
модуль обязан НЕ считать) и детерминизм (§37 тест 15).

Время не участвует ни в одном тесте как окружение: снимок целиком — вход,
поэтому ни один тест не может покраснеть просто оттого, что сдвинулся календарь
(правило доставки, «время в тестах»).
"""
# FROZEN-DATE-OK: injected-clock — все даты здесь ВХОД, а не окружение: снимок
# несёт свой `generated_at`, а построитель отчёта получает `now=` из теста. Обе
# стороны сравнения закреплены одним якорем, поэтому сдвиг календаря не может
# изменить ни один вердикт (преференция №1 .claude/rules/deployment.md).
from __future__ import annotations

import json

from spa_core.allocator.portfolio_cio import (
    DEFER,
    KEEP,
    REBALANCE,
    CioParams,
    blended_apy_pp,
    conservative_expected_apy,
    decide,
    marginal_apy_pct,
    render_owner_section,
    save_snapshot,
    yield_gap_pp,
)
from spa_core.allocator.rebalance_economics import TriggerParams

CAPITAL = 100_000.0

#: Ровная, устойчивая история — «ставка держится», а не «спайк».
STEADY = [6.0, 6.05, 5.95, 6.0, 6.02, 5.98]


def _hist(level: float, n: int = 6) -> list:
    return [level] * n


def _base_kwargs(**over):
    kw = dict(
        current_positions={"aave_v3": 40_000.0, "morpho": 10_000.0},
        target_positions={"aave_v3": 25_000.0, "morpho": 25_000.0},
        displayed_apy_pct={"aave_v3": 3.0, "morpho": 8.0},
        apy_history={"aave_v3": _hist(3.0), "morpho": _hist(8.0)},
        apy_sources={"aave_v3": "live", "morpho": "live"},
        tvl_usd={"aave_v3": 500_000_000.0, "morpho": 500_000_000.0},
        tvl_evidenced={"aave_v3", "morpho"},
        chains={"aave_v3": "base", "morpho": "base"},
        capital_usd=CAPITAL,
    )
    kw.update(over)
    return kw


# ── Тест 1 — очевидно плохая текущая аллокация ───────────────────────────────

def test_1_obviously_bad_allocation_rebalances_but_not_wholesale():
    """40 % под 3 % против 6 % рядом ⇒ REBALANCE, но не «переложить все 40 %»."""
    d = decide(**_base_kwargs())
    assert d.decision == REBALANCE, d.reasons
    moved = sum(abs(float(leg["delta_usd"])) for leg in d.legs) / 2
    assert moved <= 20_000.0, "перекладываем не всё подряд, а до цели"
    assert d.yield_gap_pp > 0


# ── Тест 2 — кратковременный спайк ───────────────────────────────────────────

def test_2_transient_spike_does_not_move_capital():
    """3 % → 12 % на несколько замеров и обратно: преимущество неустойчиво ⇒ KEEP."""
    spike = [3.0, 3.0, 3.0, 3.0, 3.0, 12.0]
    d = decide(**_base_kwargs(
        displayed_apy_pct={"aave_v3": 3.0, "morpho": 12.0},
        apy_history={"aave_v3": _hist(3.0), "morpho": spike},
    ))
    assert d.decision == KEEP, d.reasons
    # Спайк не запрещён отдельным гейтом — он просто НЕ ЗАСЧИТАН: кредитуется
    # база ряда (3 %) плюс малая доля надбавки, а не витринные 12 %.
    credited = d.views["morpho"]["conservative_apy_pct"]
    assert credited < 4.0, credited


# ── Тест 3 — дорогой переход ─────────────────────────────────────────────────

def test_3_payback_longer_than_the_edge_lives_keeps():
    """Окупаемость 20 дней при ожидаемой жизни ставки 5 дней ⇒ KEEP."""
    d = decide(**_base_kwargs(
        expected_persistence_days={"morpho": 5.0},
        trigger_params=TriggerParams(max_payback_days=60.0),
        gas_multiplier=400.0,   # делаем переход дорогим, чтобы окупаемость выросла
    ))
    assert d.decision == KEEP, d.reasons
    assert any("дольше ожидаемой жизни" in r for r in d.reasons)


# ── Тест 4 — Candidate с 20 % APY ────────────────────────────────────────────

def test_4_candidate_outside_target_is_never_proposed():
    """Кандидат светит 20 %, но его нет в допущенной цели ⇒ CIO его не предлагает.

    Допуск решает RiskPolicy/тир-гейт ВЫШЕ по потоку. Если бы CIO мог дотянуться
    до протокола мимо цели, он бы обходил политику — ровно то, что §37 запрещает.
    """
    d = decide(**_base_kwargs(
        displayed_apy_pct={"aave_v3": 3.0, "morpho": 8.0, "candidate_x": 20.0},
        apy_history={"aave_v3": _hist(3.0), "morpho": _hist(8.0),
                     "candidate_x": _hist(20.0)},
        apy_sources={"aave_v3": "live", "morpho": "live", "candidate_x": "live"},
    ))
    assert all(leg["protocol"] != "candidate_x" for leg in d.legs)


# ── Тест 5 — обвал предельной доходности ─────────────────────────────────────

def test_5_marginal_yield_collapse_is_seen():
    """8 % в витрине при малом пуле — не 8 % на наши деньги."""
    small, _ = marginal_apy_pct(apy_pct=8.0, tvl_usd=10_000_000.0, size_usd=10_000_000.0)
    assert small == 4.0, small
    big, _ = marginal_apy_pct(apy_pct=8.0, tvl_usd=1_000_000_000.0, size_usd=10_000.0)
    assert 7.99 < big <= 8.0


def test_5b_collapse_makes_the_move_unattractive():
    """Тот же вход, но пул мелкий ⇒ разбавление съедает преимущество ⇒ KEEP."""
    d = decide(**_base_kwargs(tvl_usd={"aave_v3": 500_000_000.0, "morpho": 30_000.0}))
    assert d.decision == KEEP, d.reasons


# ── Тест 6 — корреляция / концентрация ───────────────────────────────────────

def test_6_cio_never_exceeds_the_target_it_was_given():
    """Ограничения концентрации живут в цели; CIO не имеет права её расширить."""
    target = {"aave_v3": 25_000.0, "morpho": 25_000.0}
    d = decide(**_base_kwargs(target_positions=target))
    for leg in d.legs:
        proto = leg["protocol"]
        assert float(target.get(proto, 0.0)) >= 0
        final = float(_base_kwargs()["current_positions"].get(proto, 0.0)) + float(leg["delta_usd"])
        assert final <= target.get(proto, 0.0) + 1e-6


# ── Тест 7 — свежий APY при протухшей ликвидности ────────────────────────────

def test_7_stale_liquidity_blocks_funding():
    """APY свежий, TVL не подтверждён ⇒ вход не финансируется (NO EXECUTION)."""
    d = decide(**_base_kwargs(tvl_evidenced={"aave_v3"}))
    assert d.decision == KEEP, d.reasons
    assert any("tvl_not_evidenced" in r for r in d.refusals), d.refusals


# ── Тесты 8 и 9 — режим газа ─────────────────────────────────────────────────

def test_8_high_gas_defers_instead_of_killing():
    """Сделка экономически хороша, но газ сейчас её съедает ⇒ DEFER, не KEEP.

    Разница принципиальная: DEFER обязан вернуться на пересчёт, KEEP — нет.
    """
    d = decide(**_base_kwargs(gas_multiplier=240.0))
    assert d.decision == DEFER, (d.decision, d.reasons)


def test_9_when_gas_falls_the_same_case_becomes_rebalance():
    """Та же возможность при упавшем газе ⇒ DEFER → REBALANCE."""
    expensive = decide(**_base_kwargs(gas_multiplier=240.0))
    cheap = decide(**_base_kwargs(gas_multiplier=1.0))
    assert expensive.decision == DEFER
    assert cheap.decision == REBALANCE


# ── Тест 10 — новые деньги ───────────────────────────────────────────────────

def test_10_new_capital_is_deployed_without_pointless_withdrawal():
    """+$10k кэша при недоборе в morpho: только ввод, ни одного лишнего вывода."""
    d = decide(**_base_kwargs(
        current_positions={"aave_v3": 40_000.0, "morpho": 10_000.0},
        target_positions={"aave_v3": 40_000.0, "morpho": 20_000.0},
    ))
    assert d.decision == REBALANCE, d.reasons
    assert all(float(leg["delta_usd"]) > 0 for leg in d.legs), d.legs


# ── Тест 11 — APY исчез до исполнения ────────────────────────────────────────

def test_11_pretrade_revalidation_cancels_when_apy_disappears():
    """Рекомендация была; на свежем снимке APY упал ⇒ пересчёт отменяет переход."""
    before = decide(**_base_kwargs())
    assert before.decision == REBALANCE
    after = decide(**_base_kwargs(
        displayed_apy_pct={"aave_v3": 3.0, "morpho": 3.0},
        apy_history={"aave_v3": _hist(3.0), "morpho": _hist(3.0)},
    ))
    assert after.decision == KEEP, after.reasons


# ── Тест 12 — колебания APY ──────────────────────────────────────────────────

def test_12_oscillating_apys_produce_no_churn():
    """5.0/5.3 → 5.4/5.1 → 5.0/5.3: ни один шаг не двигает капитал."""
    for a, b in ((5.0, 5.3), (5.4, 5.1), (5.0, 5.3)):
        d = decide(**_base_kwargs(
            displayed_apy_pct={"aave_v3": a, "morpho": b},
            apy_history={"aave_v3": _hist(a), "morpho": _hist(b)},
        ))
        assert d.decision == KEEP, (a, b, d.reasons)


# ── Тест 13 — потолок концентрации ───────────────────────────────────────────

def test_13_concentration_cap_is_respected_because_target_carries_it():
    """Математический оптимум 70 %, потолок политики 25 % ⇒ работаем с 25 %."""
    d = decide(**_base_kwargs(
        target_positions={"aave_v3": 25_000.0, "morpho": 25_000.0},
        displayed_apy_pct={"aave_v3": 3.0, "morpho": 30.0},
        apy_history={"aave_v3": _hist(3.0), "morpho": _hist(30.0)},
    ))
    final_morpho = 10_000.0 + sum(
        float(leg["delta_usd"]) for leg in d.legs if leg["protocol"] == "morpho")
    assert final_morpho <= 25_000.0 + 1e-6


# ── Тест 14 — аварийный приоритет ────────────────────────────────────────────

def test_14_risk_action_outranks_yield_optimization():
    """Включён режим снижения риска ⇒ доходность не оптимизируем, что бы ни сулила."""
    d = decide(**_base_kwargs(derisk_active=True))
    assert d.decision == KEEP
    assert any("снижения риска" in r for r in d.reasons)


# ── Тест 15 — детерминизм ────────────────────────────────────────────────────

def test_15_hundred_runs_on_one_snapshot_are_identical():
    """100 прогонов на одном снимке дают побитово один и тот же вывод."""
    first = json.dumps(decide(**_base_kwargs()).to_dict(), sort_keys=True)
    for _ in range(99):
        assert json.dumps(decide(**_base_kwargs()).to_dict(), sort_keys=True) == first


# ── Отказы: то, что модуль обязан НЕ считать ─────────────────────────────────

def test_refusal_no_history_means_persistence_unmeasured():
    """Одна точка не отличает уровень от спайка ⇒ отказ, а не «сойдёт»."""
    v = conservative_expected_apy(protocol="x", displayed_apy_pct=9.0, history=[9.0])
    assert v.conservative_apy_pct is None
    assert any("persistence_unmeasured" in r for r in v.refusals)


def test_refusal_stale_source_earns_nothing():
    """APY не из живого фида ⇒ ожидаемый доход ноль, и причина названа."""
    v = conservative_expected_apy(
        protocol="x", displayed_apy_pct=6.5, history=_hist(6.5), apy_source="fallback_stale")
    assert v.conservative_apy_pct == 0.0
    assert any("apy_source_not_live" in r for r in v.refusals)


def test_refusal_tvl_literal_is_not_evidence():
    """TVL не подтверждён живым наблюдением ⇒ предельный APY не считается (ADR-053/064)."""
    val, why = marginal_apy_pct(apy_pct=8.0, tvl_usd=20_000_000.0,
                                size_usd=10_000.0, tvl_evidenced=False)
    assert val is None and why == "tvl_not_evidenced"


def test_unobserved_position_contributes_zero_not_a_guess():
    """Ненаблюдаемая позиция не приносит ожидаемой доходности — и не выдумывается."""
    got = blended_apy_pp({"a": 50_000.0, "b": 50_000.0}, {"a": 6.0, "b": None}, CAPITAL)
    assert got == 3.0


def test_yield_gap_is_optimal_minus_current():
    gap = yield_gap_pp(
        current_positions={"a": 40_000.0},
        target_positions={"b": 40_000.0},
        apy_pct={"a": 3.0, "b": 6.0},
        capital_usd=CAPITAL,
    )
    assert gap == 1.2


# ── Owner-экран и аудит ──────────────────────────────────────────────────────

def test_owner_section_hides_internals_and_shows_the_nine_things():
    """§36: на основном экране нет JSON, хэшей и путей — только смысл."""
    text = render_owner_section(decide(**_base_kwargs()), capital_usd=CAPITAL)
    assert "Разрыв" in text and "Решение" in text
    for forbidden in ("{", "}", "policy_hash", "spa_core/", ".json"):
        assert forbidden not in text, forbidden


def test_snapshot_is_written_atomically_with_injected_time(tmp_path):
    """Время — вход: снимок воспроизводим, тест не зависит от календаря."""
    path = tmp_path / "cio.json"
    save_snapshot(decide(**_base_kwargs()), str(path),
                  generated_at="2026-08-15T00:00:00+00:00")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["generated_at"] == "2026-08-15T00:00:00+00:00"
    assert doc["is_advisory"] is True
    assert doc["decision"] in (KEEP, REBALANCE, DEFER)


def test_module_is_advisory_and_touches_no_execution_path():
    """Слой не имеет права быть money-path (инв. 6/9)."""
    import spa_core.allocator.portfolio_cio as cio

    assert cio.IS_ADVISORY is True
    src = open(cio.__file__, encoding="utf-8").read()
    assert "spa_core.execution" not in src


def test_params_are_not_riskpolicy_thresholds():
    """Ручки CIO не содержат ни одного потолка политики (инв. 1)."""
    fields = set(CioParams().__dataclass_fields__)
    for forbidden in ("tvl_floor", "per_protocol_cap", "t2_total_cap", "min_cash_pct"):
        assert forbidden not in fields


# ── Регресс: дефект, найденный мутацией собственного теста ───────────────────

def test_rising_rate_is_not_punished_as_instability():
    """Монотонно растущая ставка кредитуется почти полностью, а не обнуляется.

    Положительный контроль на РЕАЛЬНЫЙ дефект первой редакции: она множила на
    устойчивость весь APY, а доля «времени на текущем уровне» у растущего ряда
    всегда 1/N — поэтому 8.3 % превращались в 1.16 %. База не исчезает оттого,
    что рынок пошёл вверх.
    """
    v = conservative_expected_apy(
        protocol="x", displayed_apy_pct=8.3,
        history=[7.8, 7.9, 8.0, 8.1, 8.2, 8.3])
    assert v.conservative_apy_pct is not None
    assert v.conservative_apy_pct > 7.5, v.conservative_apy_pct


def test_sawtooth_is_credited_near_its_base_not_its_peak():
    """Пила 8/2/8/2: кредитуем середину ряда, а не верхушку."""
    v = conservative_expected_apy(
        protocol="x", displayed_apy_pct=8.0, history=[8, 2, 8, 2, 8, 2])
    assert 2.0 < v.conservative_apy_pct < 5.0, v.conservative_apy_pct


# ── §34: секция в дневном отчёте ─────────────────────────────────────────────

def _write(tmp_path, name, doc):
    (tmp_path / name).write_text(json.dumps(doc), encoding="utf-8")


def _cio_doc(**over):
    doc = {
        "is_advisory": True,
        "decision": REBALANCE,
        "generated_at": "2026-08-15T00:00:00+00:00",
        "current_expected_apy_pp": 4.1,
        "optimal_expected_apy_pp": 5.3,
        "yield_gap_pp": 1.2,
        "switching_cost_usd": 42.0,
        "payback_days": 9.0,
        "reasons": ["выгода окупается"],
    }
    doc.update(over)
    return doc


def test_report_section_appears_when_snapshot_is_fresh(tmp_path):
    from datetime import datetime, timezone

    from spa_core.reporting.daily_telegram_report import build_report_data, format_daily_message

    _write(tmp_path, "portfolio_cio.json", _cio_doc())
    now = datetime(2026, 8, 15, 6, 0, tzinfo=timezone.utc)
    data = build_report_data("2026-08-15", data_dir=tmp_path, now=now)
    assert data["portfolio_cio"]["decision"] == REBALANCE
    text = format_daily_message(data)
    assert "Portfolio CIO" in text and "ПЕРЕКЛАДЫВАЕМ" in text


def test_stale_snapshot_is_dropped_not_shown_as_todays_advice(tmp_path):
    """Протухшая рекомендация опаснее отсутствующей — владелец примет её за свежую."""
    from datetime import datetime, timezone

    from spa_core.reporting.daily_telegram_report import build_report_data, format_daily_message

    _write(tmp_path, "portfolio_cio.json", _cio_doc(generated_at="2026-08-01T00:00:00+00:00"))
    now = datetime(2026, 8, 15, 6, 0, tzinfo=timezone.utc)
    data = build_report_data("2026-08-15", data_dir=tmp_path, now=now)
    assert data["portfolio_cio"] is None
    assert "Portfolio CIO" not in format_daily_message(data)


def test_missing_snapshot_does_not_break_the_rest_of_the_report(tmp_path):
    """Нет снимка — отчёт остаётся ровно таким, каким был до этой работы."""
    from datetime import datetime, timezone

    from spa_core.reporting.daily_telegram_report import build_report_data, format_daily_message

    now = datetime(2026, 8, 15, 6, 0, tzinfo=timezone.utc)
    data = build_report_data("2026-08-15", data_dir=tmp_path, now=now)
    assert data["portfolio_cio"] is None
    assert isinstance(format_daily_message(data), str)


def test_non_advisory_snapshot_is_refused(tmp_path):
    """Снимок без метки advisory в отчёт не попадает: чужой формат ≠ наш вывод."""
    from datetime import datetime, timezone

    from spa_core.reporting.daily_telegram_report import build_report_data

    _write(tmp_path, "portfolio_cio.json", _cio_doc(is_advisory=False))
    now = datetime(2026, 8, 15, 6, 0, tzinfo=timezone.utc)
    assert build_report_data("2026-08-15", data_dir=tmp_path, now=now)["portfolio_cio"] is None


# ── Step 2h: снимок производит ЦИКЛ, а не человек ────────────────────────────
#
# Скрипт `portfolio_cio_shadow.py` остаётся ручным инструментом замера (реестр R&D
# #53), а ежедневный снимок для отчёта обязан появляться сам — иначе секция в
# отчёте живёт ровно до тех пор, пока кто-то помнит запустить команду.

def _cycle_sandbox(tmp_path, monkeypatch=None):
    """Тот же песочный запуск цикла, что и у среза блокировок — без живых фидов."""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from spa_core.paper_trading import cycle_runner as cr

    now = datetime(2026, 8, 15, 6, 0, tzinfo=timezone.utc)

    def orch(*_a, **_k):
        adapters = [
            {"protocol": "aave_v3", "id": "aave_v3", "apy_pct": 4.0, "tvl_usd": 1e8,
             "tvl_source": "live", "tier": "T1", "status": "ok"},
            {"protocol": "compound_v3", "id": "compound_v3", "apy_pct": 4.2, "tvl_usd": 1e8,
             "tvl_source": "live", "tier": "T2", "status": "ok"},
        ]
        return SimpleNamespace(adapters=adapters, status="ok", data_freshness="live")

    class _Alloc:
        def allocate(self):
            target = {"aave_v3": 30_000.0, "compound_v3": 20_000.0}
            return SimpleNamespace(
                target_usd=dict(target),
                target_weights={p: v / 100_000.0 for p, v in target.items()},
                expected_apy_pct=4.0, model_used="risk_adjusted",
                strategy_loop_active=False,
            )

    ddir = tmp_path / "data"
    result = cr.run_cycle(
        data_dir=str(ddir), now=now, orchestrator_fn=orch, allocator=_Alloc(),
        risk_scorer_fn=lambda d: None, track_persister_fn=lambda d: None,
        write=True, allow_live_write=False,
    )
    return ddir, result


def test_cycle_produces_the_cio_snapshot_itself(tmp_path):
    """После цикла снимок есть, он advisory и несёт время цикла, а не «сейчас»."""
    ddir, _ = _cycle_sandbox(tmp_path)
    snap = ddir / "portfolio_cio.json"
    assert snap.exists(), "снимок обязан появляться сам, а не по памяти человека"
    doc = json.loads(snap.read_text(encoding="utf-8"))
    assert doc["is_advisory"] is True
    assert doc["decision"] in (KEEP, REBALANCE, DEFER)
    assert doc["generated_at"].startswith("2026-08-15")


def test_broken_cio_never_breaks_the_cycle(tmp_path, monkeypatch):
    """Слой отчётности не имеет права уронить цикл, который кормит трек."""
    import spa_core.allocator.portfolio_cio as cio

    def boom(**_k):
        raise RuntimeError("CIO упал намеренно")

    monkeypatch.setattr(cio, "decide", boom)
    ddir, result = _cycle_sandbox(tmp_path)
    assert result is not None, "цикл обязан пережить падение advisory-слоя"
    assert not (ddir / "portfolio_cio.json").exists()
