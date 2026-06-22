"""
Тесты RiskPolicy-LP Engine C (RS-004).

Покрытие:
  - fail-closed: None критических параметров → approved=False
  - Все 10 лимитов enforced
  - IL calculation (in-range, out-of-range, zero-IL at entry)
  - Delta-neutral requirement
  - Adapter: read_state() структура, DataTrust-валидация, policy pass
  - Read-only barriers: sign/send/write
  - LLM_FORBIDDEN присутствует в обоих файлах

LLM_FORBIDDEN.
"""
# LLM_FORBIDDEN
import math
import pytest
from pathlib import Path


@pytest.fixture
def project_root():
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def lp_module(project_root):
    import sys
    sys.path.insert(0, str(project_root))
    from spa_core.risk.policy_lp import (
        evaluate_lp_position,
        estimate_il,
        LP_LIMITS,
        LPRiskLimits,
        LP_POLICY_VERSION,
    )
    return {
        "evaluate_lp_position": evaluate_lp_position,
        "estimate_il": estimate_il,
        "LP_LIMITS": LP_LIMITS,
        "LPRiskLimits": LPRiskLimits,
        "LP_POLICY_VERSION": LP_POLICY_VERSION,
    }


@pytest.fixture
def adapter_module(project_root):
    import sys
    sys.path.insert(0, str(project_root))
    from adapters.uniswap_v3_lp import UniswapV3LPAdapter
    return UniswapV3LPAdapter


# ─── Базовые параметры для "хорошей" позиции ─────────────────────────────────

GOOD_PARAMS = dict(
    pool_name="USDC_USDT",
    protocol="uniswap_v3",
    fee_apy_24h=0.062,
    pool_tvl_usd=180e6,
    il_current_pct=0.0002,
    audit_count=4,
    range_width_pct=0.001,
    fee_volatility_7d=0.12,
    liquidity_depth_usd=8e6,
    sleeve_allocation_pct=0.15,
    is_delta_neutral=True,
    current_drawdown_pct=0.0,
)


# ─────────────────────────────────────────────────────────────────────────────
class TestFailClosed:
    """Fail-closed: критические None → blocked немедленно."""

    def test_missing_fee_apy_blocked(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "fee_apy_24h": None})
        assert r["approved"] is False
        assert any("FAIL_CLOSED" in v for v in r["violations"])
        assert r["fail_reason"] == "fail_closed_missing_data"

    def test_missing_tvl_blocked(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "pool_tvl_usd": None})
        assert r["approved"] is False
        assert any("FAIL_CLOSED" in v for v in r["violations"])

    def test_missing_il_blocked(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "il_current_pct": None})
        assert r["approved"] is False
        assert any("FAIL_CLOSED" in v for v in r["violations"])

    def test_missing_audit_count_blocked(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "audit_count": None})
        assert r["approved"] is False
        assert any("FAIL_CLOSED" in v for v in r["violations"])

    def test_all_critical_missing_blocked(self, lp_module):
        r = lp_module["evaluate_lp_position"](
            **{
                **GOOD_PARAMS,
                "fee_apy_24h": None,
                "pool_tvl_usd": None,
                "il_current_pct": None,
                "audit_count": None,
            }
        )
        assert r["approved"] is False
        # Все 4 FAIL_CLOSED должны быть в violations
        fc = [v for v in r["violations"] if "FAIL_CLOSED" in v]
        assert len(fc) == 4


# ─────────────────────────────────────────────────────────────────────────────
class TestLimits:
    """Каждый из 10 лимитов проверяется независимо."""

    def test_valid_position_approved(self, lp_module):
        r = lp_module["evaluate_lp_position"](**GOOD_PARAMS)
        assert r["approved"] is True, f"Violations: {r['violations']}"

    def test_policy_version_present(self, lp_module):
        r = lp_module["evaluate_lp_position"](**GOOD_PARAMS)
        assert r["policy_version"] == lp_module["LP_POLICY_VERSION"]
        assert r["policy_version"] == "lp_v1.0"

    # 1. TVL floor
    def test_low_tvl_blocked(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "pool_tvl_usd": 30e6})
        assert r["approved"] is False
        assert any("TVL" in v for v in r["violations"])

    def test_tvl_at_minimum_passes(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "pool_tvl_usd": 50e6})
        assert r["approved"] is True

    # 2. Min audits
    def test_insufficient_audits_blocked(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "audit_count": 1})
        assert r["approved"] is False
        assert any("audits" in v for v in r["violations"])

    def test_audits_at_minimum_passes(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "audit_count": 2})
        assert r["approved"] is True

    # 3. Fee APY floor
    def test_low_fee_apy_blocked(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "fee_apy_24h": 0.01})
        assert r["approved"] is False
        assert any("fee_apy_24h" in v for v in r["violations"])

    def test_fee_apy_at_minimum_passes(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "fee_apy_24h": 0.03})
        assert r["approved"] is True

    # 4. Fee volatility ceiling
    def test_high_fee_volatility_blocked(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "fee_volatility_7d": 0.50})
        assert r["approved"] is False
        assert any("fee_volatility_7d" in v for v in r["violations"])

    def test_fee_volatility_none_skipped(self, lp_module):
        """fee_volatility_7d=None не блокирует (не критический параметр)."""
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "fee_volatility_7d": None})
        assert r["approved"] is True

    # 5. Per-pool allocation cap
    def test_over_pool_cap_blocked(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "sleeve_allocation_pct": 0.25})
        assert r["approved"] is False
        assert any("allocation" in v for v in r["violations"])

    def test_at_pool_cap_passes(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "sleeve_allocation_pct": 0.20})
        assert r["approved"] is True

    # 6. Cash buffer
    def test_cash_buffer_too_low_blocked(self, lp_module):
        # sleeve=0.90 → cash=0.10 < 15% min
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "sleeve_allocation_pct": 0.90})
        assert r["approved"] is False
        assert any("cash buffer" in v for v in r["violations"])

    def test_cash_buffer_at_minimum_passes(self, lp_module):
        # sleeve=0.85 → cash=0.15 == 15% min; используем кастомные лимиты
        # с per_pool_cap=0.90 чтобы изолировать проверку cash buffer
        custom_limits = lp_module["LPRiskLimits"](per_pool_cap=0.90)
        r = lp_module["evaluate_lp_position"](
            **{**GOOD_PARAMS, "sleeve_allocation_pct": 0.85},
            limits=custom_limits,
        )
        assert r["approved"] is True

    # 7. IL drawdown kill
    def test_il_drawdown_kill_enforced(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "current_drawdown_pct": -0.13})
        assert r["approved"] is False
        assert any("drawdown" in v.lower() for v in r["violations"])

    def test_il_drawdown_at_kill_enforced(self, lp_module):
        """Ровно на пороге −12% → kill."""
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "current_drawdown_pct": -0.12})
        assert r["approved"] is False

    def test_drawdown_below_kill_passes(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "current_drawdown_pct": -0.05})
        assert r["approved"] is True

    # 8. Range width
    def test_wide_range_blocked(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "range_width_pct": 1.5})
        assert r["approved"] is False
        assert any("range_width" in v for v in r["violations"])

    def test_range_width_none_skipped(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "range_width_pct": None})
        assert r["approved"] is True

    # 9. Delta neutral
    def test_non_delta_neutral_blocked(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "is_delta_neutral": False})
        assert r["approved"] is False
        assert any("delta-neutral" in v for v in r["violations"])

    def test_delta_neutral_none_skipped(self, lp_module):
        """is_delta_neutral=None → не блокирует."""
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "is_delta_neutral": None})
        assert r["approved"] is True

    # 10. Liquidity depth
    def test_low_liquidity_depth_blocked(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "liquidity_depth_usd": 500_000})
        assert r["approved"] is False
        assert any("liquidity depth" in v for v in r["violations"])

    def test_liquidity_depth_none_skipped(self, lp_module):
        r = lp_module["evaluate_lp_position"](**{**GOOD_PARAMS, "liquidity_depth_usd": None})
        assert r["approved"] is True


# ─────────────────────────────────────────────────────────────────────────────
class TestILCalculation:
    """estimate_il: математика CLMM IL."""

    def test_zero_il_at_entry_price(self, lp_module):
        """Нет IL когда current_price == entry_price."""
        r = lp_module["estimate_il"](
            current_price=1.0, entry_price=1.0,
            range_lower=0.999, range_upper=1.001,
        )
        assert r["il_pct"] == pytest.approx(0.0, abs=1e-9)
        assert r["in_range"] is True

    def test_in_range_small_il_stablecoin(self, lp_module):
        """Стейбл-пара: малое отклонение → IL < 1%."""
        r = lp_module["estimate_il"](
            current_price=1.0005, entry_price=1.0,
            range_lower=0.999, range_upper=1.001,
        )
        assert r["in_range"] is True
        assert 0.0 <= r["il_pct"] < 0.01

    def test_out_of_range_upper_detected(self, lp_module):
        r = lp_module["estimate_il"](
            current_price=1.01, entry_price=1.0,
            range_lower=0.999, range_upper=1.005,
        )
        assert r["out_of_range_upper"] is True
        assert r["in_range"] is False
        assert r["out_of_range_lower"] is False

    def test_out_of_range_lower_detected(self, lp_module):
        r = lp_module["estimate_il"](
            current_price=0.98, entry_price=1.0,
            range_lower=0.999, range_upper=1.001,
        )
        assert r["out_of_range_lower"] is True
        assert r["in_range"] is False
        assert r["out_of_range_upper"] is False

    def test_il_non_negative_always(self, lp_module):
        """IL всегда >= 0 при любых ценах."""
        for price in [0.98, 0.999, 1.0, 1.001, 1.01, 1.05]:
            r = lp_module["estimate_il"](
                current_price=price, entry_price=1.0,
                range_lower=0.998, range_upper=1.002,
            )
            assert r["il_pct"] >= 0.0, f"Negative IL at price={price}"

    def test_return_fields_present(self, lp_module):
        r = lp_module["estimate_il"](
            current_price=1.0, entry_price=1.0,
            range_lower=0.99, range_upper=1.01,
        )
        for field in ["il_pct", "in_range", "out_of_range_lower",
                      "out_of_range_upper", "current_price", "entry_price", "range"]:
            assert field in r, f"Missing field: {field}"

    def test_symmetric_range_stablecoin_il_very_low(self, lp_module):
        """USDC/USDT tight диапазон — IL практически нулевой."""
        r = lp_module["estimate_il"](
            current_price=1.0001, entry_price=1.0,
            range_lower=0.9990, range_upper=1.0010,
        )
        assert r["in_range"] is True
        assert r["il_pct"] < 0.0001  # < 0.01%


# ─────────────────────────────────────────────────────────────────────────────
class TestAdapter:
    """UniswapV3LPAdapter: структура, валидация, policy pass."""

    def test_read_state_returns_dict(self, adapter_module):
        adapter = adapter_module("USDC_USDT_001")
        state = adapter.read_state()
        assert isinstance(state, dict)

    def test_required_fields_present(self, adapter_module):
        state = adapter_module("USDC_USDT_001").read_state()
        required = [
            "fee_apy_24h", "pool_tvl_usd", "il_current_pct",
            "range_width_pct", "fee_volatility_7d", "liquidity_depth_usd",
            "is_delta_neutral", "audit_count", "validated",
            "adapter", "pool_id", "read_at", "data_source",
        ]
        for f in required:
            assert f in state, f"Missing field: {f}"

    def test_validated_true_for_mock(self, adapter_module):
        state = adapter_module("USDC_USDT_001").read_state()
        assert state["validated"] is True

    def test_adapter_name(self, adapter_module):
        state = adapter_module("USDC_USDT_001").read_state()
        assert state["adapter"] == "UniswapV3LPAdapter"

    def test_mock_passes_policy(self, adapter_module, lp_module):
        """Mock-данные адаптера должны проходить RiskPolicy-LP."""
        state = adapter_module("USDC_USDT_001").read_state()
        r = lp_module["evaluate_lp_position"](
            pool_name=state["pool_id"],
            protocol="uniswap_v3",
            fee_apy_24h=state["fee_apy_24h"],
            pool_tvl_usd=state["pool_tvl_usd"],
            il_current_pct=state["il_current_pct"],
            audit_count=state["audit_count"],
            range_width_pct=state["range_width_pct"],
            fee_volatility_7d=state["fee_volatility_7d"],
            liquidity_depth_usd=state["liquidity_depth_usd"],
            sleeve_allocation_pct=0.15,
            is_delta_neutral=state["is_delta_neutral"],
        )
        assert r["approved"] is True, f"Mock failed policy: {r['violations']}"

    def test_base_pool_supported(self, adapter_module):
        adapter = adapter_module("USDC_USDT_BASE_001")
        state = adapter.read_state()
        assert state["pool_id"] == "USDC_USDT_BASE_001"

    def test_unsupported_pool_raises_value_error(self, adapter_module):
        with pytest.raises(ValueError, match="Unsupported pool"):
            adapter_module("UNKNOWN_POOL_XYZ")

    def test_read_only_sign_raises(self, adapter_module):
        adapter = adapter_module()
        with pytest.raises(NotImplementedError, match="READ-ONLY"):
            adapter.sign("tx")

    def test_read_only_send_raises(self, adapter_module):
        adapter = adapter_module()
        with pytest.raises(NotImplementedError, match="READ-ONLY"):
            adapter.send("tx")

    def test_read_only_write_raises(self, adapter_module):
        adapter = adapter_module()
        with pytest.raises(NotImplementedError, match="READ-ONLY"):
            adapter.write("data")


# ─────────────────────────────────────────────────────────────────────────────
class TestLLMForbidden:
    """LLM_FORBIDDEN присутствует в коде и нет AI-библиотек."""

    def test_policy_lp_has_llm_forbidden_marker(self, project_root):
        content = (project_root / "spa_core" / "risk" / "policy_lp.py").read_text()
        assert "LLM_FORBIDDEN" in content

    def test_adapter_has_llm_forbidden_marker(self, project_root):
        content = (project_root / "adapters" / "uniswap_v3_lp.py").read_text()
        assert "LLM_FORBIDDEN" in content

    def test_policy_no_ai_imports(self, project_root):
        # "llm" исключён: само слово входит в LLM_FORBIDDEN маркер.
        # Проверяем конкретные AI-библиотеки.
        content = (project_root / "spa_core" / "risk" / "policy_lp.py").read_text().lower()
        for term in ["openai", "anthropic", "gpt", "langchain", "import anthropic",
                     "import openai", "from openai", "from anthropic"]:
            assert term not in content, f"Found banned AI library: {term!r}"

    def test_adapter_no_ai_imports(self, project_root):
        content = (project_root / "adapters" / "uniswap_v3_lp.py").read_text().lower()
        for term in ["openai", "anthropic", "gpt", "langchain", "import anthropic",
                     "import openai", "from openai", "from anthropic"]:
            assert term not in content, f"Found banned AI library: {term!r}"

    def test_policy_stdlib_only(self, project_root):
        """Только stdlib — никаких внешних зависимостей."""
        import ast
        content = (project_root / "spa_core" / "risk" / "policy_lp.py").read_text()
        tree = ast.parse(content)
        stdlib_modules = {"dataclasses", "typing", "pathlib", "json", "math"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [n.name for n in node.names] if isinstance(node, ast.Import) \
                    else [node.module] if node.module else []
                for name in names:
                    root = (name or "").split(".")[0]
                    assert root in stdlib_modules or root == "", \
                        f"Non-stdlib import found: {name!r}"

    def test_policy_version_is_lp_v1_0(self, lp_module):
        assert lp_module["LP_POLICY_VERSION"] == "lp_v1.0"

    def test_limits_singleton_immutable(self, lp_module):
        """LPRiskLimits заморожен — нельзя изменить значения."""
        limits = lp_module["LP_LIMITS"]
        with pytest.raises((AttributeError, TypeError)):
            limits.per_pool_cap = 0.99
