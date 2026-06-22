"""
Тесты RiskPolicy-HY Engine B (Carry/RS-003).

Покрытие:
  - fail-closed: любой None критического параметра → approved=False / should_exit=True
  - Лимиты: TVL, депег, funding_rate, аудиты, per-protocol cap, drawdown kill
  - RegimeGate: ENTER, EXIT, UNKNOWN, гистерезис
  - PendlePTAdapter: read-only, структура данных, LLM_FORBIDDEN
  - LLM_FORBIDDEN маркеры во всех модулях

Property: ни один валидный вход не может превысить лимиты.

Примечание по импорту PendlePTAdapter:
  Проект имеет ДВА адаптера с именем pendle_pt:
    - spa_core/adapters/pendle_pt.py  (MP-201 APY feed, Engine A)
    - adapters/pendle_pt.py           (Engine B HY adapter, этот проект)
  При загрузке spa_core импортируется spa_core.adapters, что может кешировать
  'adapters' namespace в сторону spa_core/adapters. Поэтому TestPendlePTAdapter
  использует явную загрузку через importlib (spec_from_file_location) —
  это надёжно и однозначно указывает на правильный файл.
"""
import sys
import importlib.util
import pytest
from pathlib import Path


@pytest.fixture
def project_root() -> Path:
    """Корень проекта SPA_Claude."""
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def policy_hy(project_root: Path):
    """Импортирует модули policy_hy из spa_core.risk."""
    sys.path.insert(0, str(project_root))
    from spa_core.risk.policy_hy import (
        evaluate_protocol,
        evaluate_exit,
        HY_LIMITS,
        HYRiskLimits,
        HY_POLICY_VERSION,
    )
    return {
        "evaluate_protocol": evaluate_protocol,
        "evaluate_exit": evaluate_exit,
        "HY_LIMITS": HY_LIMITS,
        "HYRiskLimits": HYRiskLimits,
        "HY_POLICY_VERSION": HY_POLICY_VERSION,
    }


@pytest.fixture
def regime_gate(project_root: Path):
    """Импортирует модули regime_gate из spa_core.risk."""
    sys.path.insert(0, str(project_root))
    from spa_core.risk.regime_gate import evaluate_regime, RegimeState
    return {
        "evaluate_regime": evaluate_regime,
        "RegimeState": RegimeState,
    }


# ─── Вспомогательные параметры: «хорошие» данные проходят политику ──────────

_GOOD = dict(
    protocol_name="PT-sUSDe",
    yield_apy=0.115,
    tvl_usd=850e6,
    depeg_pct=0.0015,
    funding_rate=0.085,
    audit_count=3,
    term_to_maturity_days=90,
    liquidity_usd=5e6,
    sleeve_allocation_pct=0.20,
    current_drawdown_pct=0.0,
)


class TestFailClosed:
    """
    Группа: fail-closed — отсутствие данных блокирует вход.
    Все тесты верифицируют: approved=False при любом None критического поля.
    """

    def test_missing_yield_apy_blocks(self, policy_hy):
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "yield_apy": None})
        assert result["approved"] is False
        assert any("FAIL_CLOSED" in v for v in result["violations"])

    def test_missing_tvl_blocks(self, policy_hy):
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "tvl_usd": None})
        assert result["approved"] is False
        assert any("FAIL_CLOSED" in v for v in result["violations"])

    def test_missing_depeg_blocks(self, policy_hy):
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "depeg_pct": None})
        assert result["approved"] is False
        assert any("FAIL_CLOSED" in v for v in result["violations"])

    def test_missing_funding_rate_blocks(self, policy_hy):
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "funding_rate": None})
        assert result["approved"] is False
        assert any("FAIL_CLOSED" in v for v in result["violations"])

    def test_missing_audit_count_blocks(self, policy_hy):
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "audit_count": None})
        assert result["approved"] is False
        assert any("FAIL_CLOSED" in v for v in result["violations"])

    def test_fail_reason_is_set(self, policy_hy):
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "yield_apy": None})
        assert result.get("fail_reason") == "fail_closed_missing_data"

    def test_exit_missing_depeg_exits(self, policy_hy):
        result = policy_hy["evaluate_exit"](depeg_pct=None, funding_rate=0.09)
        assert result["should_exit"] is True
        assert any("FAIL_CLOSED" in s for s in result["exit_signals"])

    def test_exit_missing_funding_exits(self, policy_hy):
        result = policy_hy["evaluate_exit"](depeg_pct=0.001, funding_rate=None)
        assert result["should_exit"] is True
        assert any("FAIL_CLOSED" in s for s in result["exit_signals"])

    def test_exit_both_missing_exits(self, policy_hy):
        result = policy_hy["evaluate_exit"](depeg_pct=None, funding_rate=None)
        assert result["should_exit"] is True


class TestLimits:
    """
    Группа: проверка числовых лимитов RiskPolicy-HY.
    """

    def test_valid_protocol_approved(self, policy_hy):
        """Золотой путь: все данные в норме → approved=True."""
        result = policy_hy["evaluate_protocol"](**_GOOD)
        assert result["approved"] is True, (
            f"Should be approved. Violations: {result['violations']}"
        )

    def test_low_tvl_blocked(self, policy_hy):
        """TVL < $100M → blocked."""
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "tvl_usd": 50e6})
        assert result["approved"] is False
        assert any("TVL" in v for v in result["violations"])

    def test_tvl_at_floor_passes(self, policy_hy):
        """TVL = $100M → passes (граница включена)."""
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "tvl_usd": 100e6})
        assert result["approved"] is True

    def test_high_depeg_blocked(self, policy_hy):
        """Депег 0.5% ≥ 0.3% ENTER threshold → blocked."""
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "depeg_pct": 0.005})
        assert result["approved"] is False
        assert any("depeg" in v.lower() for v in result["violations"])

    def test_depeg_at_enter_threshold_blocked(self, policy_hy):
        """Депег = 0.3% (граница ENTER) → blocked (строгое <)."""
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "depeg_pct": 0.003})
        assert result["approved"] is False

    def test_depeg_just_below_enter_passes(self, policy_hy):
        """Депег 0.29% < 0.3% → passes."""
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "depeg_pct": 0.0029})
        assert result["approved"] is True

    def test_low_funding_rate_blocked(self, policy_hy):
        """funding_rate 3% ≤ 5% ENTER threshold → blocked."""
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "funding_rate": 0.03})
        assert result["approved"] is False

    def test_funding_rate_at_enter_threshold_blocked(self, policy_hy):
        """funding_rate = 5% (граница) → blocked (строгое >)."""
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "funding_rate": 0.05})
        assert result["approved"] is False

    def test_funding_rate_just_above_enter_passes(self, policy_hy):
        """funding_rate 5.1% > 5% → passes."""
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "funding_rate": 0.051})
        assert result["approved"] is True

    def test_too_few_audits_blocked(self, policy_hy):
        """audit_count=1 < min 2 → blocked."""
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "audit_count": 1})
        assert result["approved"] is False

    def test_two_audits_passes(self, policy_hy):
        """audit_count=2 = min → passes."""
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "audit_count": 2})
        assert result["approved"] is True

    def test_per_protocol_cap_enforced(self, policy_hy):
        """Property: allocation 30% > 25% cap → blocked."""
        result = policy_hy["evaluate_protocol"](
            **{**_GOOD, "sleeve_allocation_pct": 0.30}
        )
        assert result["approved"] is False

    def test_per_protocol_cap_at_limit_passes(self, policy_hy):
        """allocation = 25% (граница cap) → passes (строгое >)."""
        result = policy_hy["evaluate_protocol"](
            **{**_GOOD, "sleeve_allocation_pct": 0.25}
        )
        assert result["approved"] is True

    def test_drawdown_kill_enforced(self, policy_hy):
        """Property: drawdown −9% ≤ −8% kill → blocked."""
        result = policy_hy["evaluate_protocol"](
            **{**_GOOD, "current_drawdown_pct": -0.09}
        )
        assert result["approved"] is False

    def test_drawdown_at_kill_threshold_blocked(self, policy_hy):
        """drawdown = −8% (граница kill) → blocked (строгое <=)."""
        result = policy_hy["evaluate_protocol"](
            **{**_GOOD, "current_drawdown_pct": -0.08}
        )
        assert result["approved"] is False

    def test_drawdown_just_above_kill_passes(self, policy_hy):
        """drawdown −7.9% > −8% → passes."""
        result = policy_hy["evaluate_protocol"](
            **{**_GOOD, "current_drawdown_pct": -0.079}
        )
        assert result["approved"] is True

    def test_term_to_maturity_too_long_blocked(self, policy_hy):
        """term_to_maturity 200d > max 180d → blocked."""
        result = policy_hy["evaluate_protocol"](
            **{**_GOOD, "term_to_maturity_days": 200}
        )
        assert result["approved"] is False

    def test_term_to_maturity_at_max_passes(self, policy_hy):
        """term_to_maturity = 180d (граница) → passes (строгое >)."""
        result = policy_hy["evaluate_protocol"](
            **{**_GOOD, "term_to_maturity_days": 180}
        )
        assert result["approved"] is True

    def test_low_liquidity_blocked(self, policy_hy):
        """liquidity $100K < min $500K → blocked."""
        result = policy_hy["evaluate_protocol"](
            **{**_GOOD, "liquidity_usd": 100_000}
        )
        assert result["approved"] is False

    def test_policy_version_present(self, policy_hy):
        """policy_version должен присутствовать в ответе."""
        result = policy_hy["evaluate_protocol"](**_GOOD)
        assert "policy_version" in result
        assert result["policy_version"] == "hy_v1.0"

    def test_policy_version_on_blocked(self, policy_hy):
        """policy_version присутствует и при rejected."""
        result = policy_hy["evaluate_protocol"](**{**_GOOD, "tvl_usd": 1e6})
        assert result["policy_version"] == "hy_v1.0"

    def test_violations_list_empty_on_approved(self, policy_hy):
        """violations = [] при approved=True."""
        result = policy_hy["evaluate_protocol"](**_GOOD)
        assert result["violations"] == []

    def test_fail_reason_none_on_approved(self, policy_hy):
        """fail_reason = None при approved=True."""
        result = policy_hy["evaluate_protocol"](**_GOOD)
        assert result["fail_reason"] is None


class TestRegimeGate:
    """
    Группа: RegimeGate — ENTER/EXIT/UNKNOWN с гистерезисом.
    """

    def test_good_conditions_enter(self, regime_gate):
        """Хорошие условия (funding 8.5%, депег 0.15%) → ENTER."""
        result = regime_gate["evaluate_regime"](
            funding_rate=0.085,
            depeg_pct=0.0015,
            current_drawdown_pct=0.0,
        )
        assert result["state"] == regime_gate["RegimeState"].ENTER

    def test_low_funding_exit(self, regime_gate):
        """funding_rate 1% ≤ 2% EXIT threshold → EXIT."""
        result = regime_gate["evaluate_regime"](
            funding_rate=0.01,
            depeg_pct=0.0015,
        )
        assert result["state"] == regime_gate["RegimeState"].EXIT

    def test_funding_at_exit_threshold_exits(self, regime_gate):
        """funding_rate = 2% (граница EXIT) → EXIT."""
        result = regime_gate["evaluate_regime"](
            funding_rate=0.02,
            depeg_pct=0.0015,
        )
        assert result["state"] == regime_gate["RegimeState"].EXIT

    def test_high_depeg_exit(self, regime_gate):
        """Депег 0.8% ≥ 0.6% EXIT threshold → EXIT."""
        result = regime_gate["evaluate_regime"](
            funding_rate=0.085,
            depeg_pct=0.008,
        )
        assert result["state"] == regime_gate["RegimeState"].EXIT

    def test_depeg_at_exit_threshold_exits(self, regime_gate):
        """Депег = 0.6% (граница EXIT) → EXIT."""
        result = regime_gate["evaluate_regime"](
            funding_rate=0.085,
            depeg_pct=0.006,
        )
        assert result["state"] == regime_gate["RegimeState"].EXIT

    def test_missing_data_unknown(self, regime_gate):
        """Нет данных → UNKNOWN (fail-closed)."""
        result = regime_gate["evaluate_regime"](
            funding_rate=None,
            depeg_pct=None,
        )
        assert result["state"] == regime_gate["RegimeState"].UNKNOWN

    def test_missing_funding_only_unknown(self, regime_gate):
        """funding_rate=None → UNKNOWN."""
        result = regime_gate["evaluate_regime"](
            funding_rate=None,
            depeg_pct=0.001,
        )
        assert result["state"] == regime_gate["RegimeState"].UNKNOWN

    def test_missing_depeg_only_unknown(self, regime_gate):
        """depeg_pct=None → UNKNOWN."""
        result = regime_gate["evaluate_regime"](
            funding_rate=0.085,
            depeg_pct=None,
        )
        assert result["state"] == regime_gate["RegimeState"].UNKNOWN

    def test_hysteresis_enter_stays_enter(self, regime_gate):
        """
        Гистерезис: в ENTER, между порогами → остаёмся в ENTER.
        funding=3.5% (EXIT>2% OK, ENTER>5% NOT met) и депег=0.4% (EXIT<0.6% OK, ENTER<0.3% NOT met).
        """
        result = regime_gate["evaluate_regime"](
            funding_rate=0.035,   # > exit(2%) но < enter(5%)
            depeg_pct=0.004,      # < exit(0.6%) но >= enter(0.3%)
            current_state="ENTER",
        )
        assert result["state"] == regime_gate["RegimeState"].ENTER

    def test_hysteresis_no_state_exits(self, regime_gate):
        """
        Гистерезис: между порогами без current_state → EXIT (fail-closed).
        """
        result = regime_gate["evaluate_regime"](
            funding_rate=0.035,
            depeg_pct=0.004,
            current_state=None,
        )
        assert result["state"] == regime_gate["RegimeState"].EXIT

    def test_drawdown_kill_in_regime(self, regime_gate):
        """Drawdown kill −9% даже при хорошем фандинге → EXIT."""
        result = regime_gate["evaluate_regime"](
            funding_rate=0.085,
            depeg_pct=0.001,
            current_drawdown_pct=-0.09,
        )
        assert result["state"] == regime_gate["RegimeState"].EXIT

    def test_result_has_timestamp(self, regime_gate):
        """Результат всегда содержит timestamp."""
        result = regime_gate["evaluate_regime"](
            funding_rate=0.085,
            depeg_pct=0.001,
        )
        assert "timestamp" in result
        assert result["timestamp"].endswith("Z")

    def test_result_has_signals(self, regime_gate):
        """Результат содержит signals с входными данными."""
        result = regime_gate["evaluate_regime"](
            funding_rate=0.085,
            depeg_pct=0.001,
        )
        assert "signals" in result
        assert "funding_rate" in result["signals"]
        assert "depeg_pct" in result["signals"]

    def test_regime_state_is_str_comparable(self, regime_gate):
        """RegimeState.ENTER == 'ENTER' (str Enum)."""
        RS = regime_gate["RegimeState"]
        assert RS.ENTER == "ENTER"
        assert RS.EXIT == "EXIT"
        assert RS.UNKNOWN == "UNKNOWN"


class TestExitGate:
    """
    Группа: evaluate_exit с гистерезисом.
    EXIT порог мягче ENTER порога.
    """

    def test_normal_conditions_no_exit(self, policy_hy):
        """Хорошие условия → should_exit=False."""
        result = policy_hy["evaluate_exit"](
            depeg_pct=0.001, funding_rate=0.085
        )
        assert result["should_exit"] is False
        assert result["exit_signals"] == []

    def test_depeg_between_thresholds_no_exit(self, policy_hy):
        """Депег 0.4% (между ENTER 0.3% и EXIT 0.6%) → no exit."""
        result = policy_hy["evaluate_exit"](
            depeg_pct=0.004, funding_rate=0.085
        )
        assert result["should_exit"] is False

    def test_funding_between_thresholds_no_exit(self, policy_hy):
        """funding 3.5% (между EXIT 2% и ENTER 5%) → no exit."""
        result = policy_hy["evaluate_exit"](
            depeg_pct=0.001, funding_rate=0.035
        )
        assert result["should_exit"] is False

    def test_exit_policy_version(self, policy_hy):
        """evaluate_exit возвращает policy_version."""
        result = policy_hy["evaluate_exit"](
            depeg_pct=0.001, funding_rate=0.085
        )
        assert result["policy_version"] == "hy_v1.0"


def _load_pendle_pt_cls(project_root: Path):
    """
    Явная загрузка PendlePTAdapter из adapters/pendle_pt.py (Engine B).

    Использует importlib.util.spec_from_file_location вместо sys.path-импорта
    чтобы избежать коллизии с spa_core/adapters/pendle_pt.py (MP-201 Engine A).
    spa_core/__init__.py импортирует spa_core.adapters при первом обращении
    к spa_core, что может кешировать 'adapters' namespace в sys.modules,
    указывая на spa_core/adapters/ вместо top-level adapters/.
    """
    target = project_root / "adapters" / "pendle_pt.py"
    spec = importlib.util.spec_from_file_location(
        "adapters_engine_b.pendle_pt", str(target)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.PendlePTAdapter


class TestPendlePTAdapter:
    """
    Группа: PendlePTAdapter (S1.2) — read-only, структура, LLM_FORBIDDEN.

    Импорт выполняется явно через importlib.util.spec_from_file_location
    для избежания коллизии с spa_core/adapters/pendle_pt.py (Engine A).
    """

    def test_read_state_returns_dict(self, project_root):
        PendlePTAdapter = _load_pendle_pt_cls(project_root)
        adapter = PendlePTAdapter("PT-sUSDe-MAR2025")
        state = adapter.read_state()
        assert isinstance(state, dict)

    def test_read_state_has_required_fields(self, project_root):
        """read_state() возвращает все поля нужные RiskPolicy-HY."""
        PendlePTAdapter = _load_pendle_pt_cls(project_root)
        adapter = PendlePTAdapter("PT-sUSDe-MAR2025")
        state = adapter.read_state()
        required = [
            "yield_apy", "tvl_usd", "depeg_pct", "funding_rate",
            "audit_count", "term_to_maturity_days", "liquidity_usd",
            "validated", "adapter", "market_id", "read_at", "data_source",
        ]
        for field in required:
            assert field in state, f"Missing field: {field}"

    def test_read_state_validated_true(self, project_root):
        """Mock данные проходят внутреннюю валидацию."""
        PendlePTAdapter = _load_pendle_pt_cls(project_root)
        adapter = PendlePTAdapter("PT-sUSDe-MAR2025")
        state = adapter.read_state()
        assert state["validated"] is True

    def test_read_only_sign_forbidden(self, project_root):
        """sign() → NotImplementedError."""
        PendlePTAdapter = _load_pendle_pt_cls(project_root)
        adapter = PendlePTAdapter()
        with pytest.raises(NotImplementedError):
            adapter.sign("tx")

    def test_read_only_send_forbidden(self, project_root):
        """send() → NotImplementedError."""
        PendlePTAdapter = _load_pendle_pt_cls(project_root)
        adapter = PendlePTAdapter()
        with pytest.raises(NotImplementedError):
            adapter.send("tx")

    def test_read_only_write_forbidden(self, project_root):
        """write() → NotImplementedError."""
        PendlePTAdapter = _load_pendle_pt_cls(project_root)
        adapter = PendlePTAdapter()
        with pytest.raises(NotImplementedError):
            adapter.write({"data": 1})

    def test_unsupported_market_raises(self, project_root):
        """Неизвестный market_id → ValueError."""
        PendlePTAdapter = _load_pendle_pt_cls(project_root)
        with pytest.raises(ValueError):
            PendlePTAdapter("UNKNOWN-MARKET")

    def test_second_supported_market(self, project_root):
        """PT-USDe-SEP2025 тоже должен работать."""
        PendlePTAdapter = _load_pendle_pt_cls(project_root)
        adapter = PendlePTAdapter("PT-USDe-SEP2025")
        state = adapter.read_state()
        assert state["market_id"] == "PT-USDe-SEP2025"

    def test_adapter_passes_policy(self, project_root, policy_hy):
        """
        Данные адаптера проходят RiskPolicy-HY.
        Mock данные должны быть в зоне ENTER.
        """
        PendlePTAdapter = _load_pendle_pt_cls(project_root)
        adapter = PendlePTAdapter()
        state = adapter.read_state()

        result = policy_hy["evaluate_protocol"](
            protocol_name=state["market_id"],
            yield_apy=state["yield_apy"],
            tvl_usd=state["tvl_usd"],
            depeg_pct=state["depeg_pct"],
            funding_rate=state["funding_rate"],
            audit_count=state["audit_count"],
            term_to_maturity_days=state["term_to_maturity_days"],
            liquidity_usd=state["liquidity_usd"],
            sleeve_allocation_pct=0.20,
        )
        assert result["approved"] is True, (
            f"Adapter mock data should pass policy. "
            f"Violations: {result['violations']}"
        )

    def test_adapter_data_source_is_set(self, project_root):
        """data_source присутствует в ответе."""
        PendlePTAdapter = _load_pendle_pt_cls(project_root)
        state = PendlePTAdapter().read_state()
        assert "data_source" in state
        assert state["data_source"] in ("mock", "cache", "pendle_api+defillama")

    def test_llm_forbidden_in_adapter(self, project_root):
        """Маркер LLM_FORBIDDEN должен присутствовать в файле адаптера."""
        adapter_file = project_root / "adapters" / "pendle_pt.py"
        content = adapter_file.read_text()
        assert "LLM_FORBIDDEN" in content


class TestLLMForbidden:
    """
    Группа: LLM_FORBIDDEN маркеры во всех модулях Engine B.
    Критично для compliance — LLM запрещён в risk/execution/monitoring.
    """

    def test_policy_hy_llm_forbidden(self, project_root):
        content = (
            project_root / "spa_core" / "risk" / "policy_hy.py"
        ).read_text()
        assert "LLM_FORBIDDEN" in content

    def test_regime_gate_llm_forbidden(self, project_root):
        content = (
            project_root / "spa_core" / "risk" / "regime_gate.py"
        ).read_text()
        assert "LLM_FORBIDDEN" in content

    def test_pendle_adapter_llm_forbidden(self, project_root):
        content = (
            project_root / "adapters" / "pendle_pt.py"
        ).read_text()
        assert "LLM_FORBIDDEN" in content
