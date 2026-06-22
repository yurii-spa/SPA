"""
Тесты DataTrust Validator.
- fail-closed: пустые данные → EXIT
- staleness check
- range validation
- divergence detection
- PIT filter
- batch validation
- LLM_FORBIDDEN
"""
import pytest
from datetime import datetime, timedelta
from pathlib import Path


@pytest.fixture
def project_root():
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def validator_module(project_root):
    import sys
    sys.path.insert(0, str(project_root))
    from spa_core.data_trust.validator import (
        DataTrustValidator, DataPoint, DataValidationResult
    )
    return {
        "DataTrustValidator": DataTrustValidator,
        "DataPoint": DataPoint,
        "DataValidationResult": DataValidationResult,
    }


@pytest.fixture
def validator(validator_module):
    return validator_module["DataTrustValidator"]()


@pytest.fixture
def fresh_apy_points(validator_module):
    now = datetime.utcnow()
    return [
        validator_module["DataPoint"](
            value=0.054, source="defillama", fetched_at=now - timedelta(minutes=10),
            asset="USDC", metric="apy"
        ),
        validator_module["DataPoint"](
            value=0.053, source="aave_subgraph", fetched_at=now - timedelta(minutes=5),
            asset="USDC", metric="apy"
        ),
    ]


class TestFailClosed:
    def test_empty_points_exit(self, validator):
        result = validator.validate([], metric="apy")
        assert result.signal == "exit"
        assert result.status.value == "missing"

    def test_no_fresh_points_exit(self, validator, validator_module):
        stale_time = datetime.utcnow() - timedelta(hours=10)
        points = [
            validator_module["DataPoint"](
                value=0.054, source="defillama", fetched_at=stale_time,
                asset="USDC", metric="apy"
            ),
            validator_module["DataPoint"](
                value=0.053, source="aave", fetched_at=stale_time,
                asset="USDC", metric="apy"
            ),
        ]
        result = validator.validate(points, metric="apy")
        assert result.signal == "exit"
        assert result.status.value == "stale"

    def test_out_of_range_exit(self, validator, validator_module):
        now = datetime.utcnow()
        points = [
            validator_module["DataPoint"](
                value=1.50,  # 150% APY — вне диапазона 0-50%
                source="bad_source", fetched_at=now,
                asset="USDC", metric="apy"
            ),
            validator_module["DataPoint"](
                value=1.51, source="bad_source2", fetched_at=now,
                asset="USDC", metric="apy"
            ),
        ]
        result = validator.validate(points, metric="apy")
        assert result.signal == "exit"
        assert result.status.value == "out_of_range"

    def test_should_exit_property(self, validator):
        result = validator.validate([], metric="apy")
        assert result.should_exit is True

    def test_single_source_insufficient_for_apy_exit(self, validator, validator_module):
        """apy требует min_sources=2 → 1 источник = exit"""
        now = datetime.utcnow()
        points = [
            validator_module["DataPoint"](
                value=0.054, source="only_one", fetched_at=now,
                asset="USDC", metric="apy"
            ),
        ]
        result = validator.validate(points, metric="apy")
        assert result.signal == "exit"
        assert result.status.value == "stale"


class TestValidData:
    def test_two_fresh_sources_valid(self, validator, fresh_apy_points):
        result = validator.validate(fresh_apy_points, metric="apy")
        assert result.signal == "ok"
        assert result.status.value == "valid"
        assert result.validated_value is not None
        assert 0.05 <= result.validated_value <= 0.06

    def test_median_aggregation_odd(self, validator, validator_module):
        """Медиана из нечётного числа элементов"""
        now = datetime.utcnow()
        points = [
            validator_module["DataPoint"](
                value=v, source=f"src{i}", fetched_at=now,
                asset="USDC", metric="apy"
            )
            for i, v in enumerate([0.050, 0.054, 0.058])
        ]
        result = validator.validate(points, metric="apy")
        assert result.validated_value == 0.054  # медиана из [0.050, 0.054, 0.058]

    def test_median_aggregation_even(self, validator, validator_module):
        """Медиана из чётного числа элементов"""
        now = datetime.utcnow()
        points = [
            validator_module["DataPoint"](
                value=v, source=f"src{i}", fetched_at=now,
                asset="USDC", metric="apy"
            )
            for i, v in enumerate([0.050, 0.060])
        ]
        result = validator.validate(points, metric="apy")
        assert abs(result.validated_value - 0.055) < 1e-9

    def test_single_source_ok_for_depeg(self, validator, validator_module):
        """depeg_pct: min_sources=1 → один источник достаточен"""
        now = datetime.utcnow()
        points = [
            validator_module["DataPoint"](
                value=0.001, source="onchain", fetched_at=now,
                asset="USDC", metric="depeg_pct"
            )
        ]
        result = validator.validate(points, metric="depeg_pct")
        assert result.signal == "ok"

    def test_single_source_ok_for_funding_rate(self, validator, validator_module):
        """funding_rate: min_sources=1"""
        now = datetime.utcnow()
        points = [
            validator_module["DataPoint"](
                value=0.01, source="binance", fetched_at=now,
                asset="ETH", metric="funding_rate"
            )
        ]
        result = validator.validate(points, metric="funding_rate")
        assert result.signal == "ok"

    def test_negative_funding_rate_valid(self, validator, validator_module):
        """funding_rate может быть отрицательным"""
        now = datetime.utcnow()
        points = [
            validator_module["DataPoint"](
                value=-0.05, source="binance", fetched_at=now,
                asset="ETH", metric="funding_rate"
            )
        ]
        result = validator.validate(points, metric="funding_rate")
        assert result.signal == "ok"
        assert result.validated_value == -0.05

    def test_sources_used_populated(self, validator, fresh_apy_points):
        result = validator.validate(fresh_apy_points, metric="apy")
        assert "defillama" in result.sources_used
        assert "aave_subgraph" in result.sources_used

    def test_staleness_seconds_populated(self, validator, fresh_apy_points):
        result = validator.validate(fresh_apy_points, metric="apy")
        assert result.staleness_seconds is not None
        assert result.staleness_seconds >= 0


class TestDivergence:
    def test_divergent_sources_alarm(self, validator, validator_module):
        now = datetime.utcnow()
        points = [
            validator_module["DataPoint"](
                value=0.054, source="src1", fetched_at=now,
                asset="USDC", metric="apy"
            ),
            validator_module["DataPoint"](
                value=0.090,  # 67% расхождение > 20% threshold
                source="src2", fetched_at=now,
                asset="USDC", metric="apy"
            ),
        ]
        result = validator.validate(points, metric="apy")
        assert result.status.value == "divergent"
        assert result.signal == "alarm"
        assert result.divergence_pct is not None
        assert result.divergence_pct > 0.20

    def test_close_sources_valid(self, validator, validator_module):
        now = datetime.utcnow()
        points = [
            validator_module["DataPoint"](
                value=0.054, source="src1", fetched_at=now,
                asset="USDC", metric="apy"
            ),
            validator_module["DataPoint"](
                value=0.055,  # 1.8% расхождение < 20%
                source="src2", fetched_at=now,
                asset="USDC", metric="apy"
            ),
        ]
        result = validator.validate(points, metric="apy")
        assert result.signal == "ok"

    def test_divergent_is_alarm_not_exit(self, validator, validator_module):
        """Расхождение источников — alarm, не exit (данные сомнительны, но не критично)"""
        now = datetime.utcnow()
        points = [
            validator_module["DataPoint"](
                value=0.054, source="src1", fetched_at=now,
                asset="USDC", metric="apy"
            ),
            validator_module["DataPoint"](
                value=0.200, source="src2", fetched_at=now,
                asset="USDC", metric="apy"
            ),
        ]
        result = validator.validate(points, metric="apy")
        assert result.signal == "alarm"
        # divergent: should_exit = True (status != VALID)
        assert result.should_exit is True

    def test_divergence_pct_calculation(self, validator, validator_module):
        """Проверяем точность расчёта divergence_pct"""
        now = datetime.utcnow()
        points = [
            validator_module["DataPoint"](
                value=0.100, source="src1", fetched_at=now,
                asset="USDC", metric="apy"
            ),
            validator_module["DataPoint"](
                value=0.150, source="src2", fetched_at=now,
                asset="USDC", metric="apy"
            ),
        ]
        result = validator.validate(points, metric="apy")
        # (0.15 - 0.10) / 0.10 = 0.50
        assert result.divergence_pct is not None
        assert abs(result.divergence_pct - 0.50) < 0.001


class TestStaleness:
    def test_partially_stale_uses_fresh(self, validator, validator_module):
        """Один источник свежий, один устаревший — используем свежий если min_sources=1"""
        now = datetime.utcnow()
        stale_time = now - timedelta(hours=10)
        points = [
            validator_module["DataPoint"](
                value=0.054, source="fresh_src", fetched_at=now - timedelta(minutes=5),
                asset="USDC", metric="depeg_pct"  # min_sources=1
            ),
            validator_module["DataPoint"](
                value=0.053, source="stale_src", fetched_at=stale_time,
                asset="USDC", metric="depeg_pct"
            ),
        ]
        result = validator.validate(points, metric="depeg_pct")
        assert result.signal == "ok"
        assert "fresh_src" in result.sources_used
        assert "stale_src" not in result.sources_used

    def test_staleness_reported_in_seconds(self, validator, validator_module):
        now = datetime.utcnow()
        stale_time = now - timedelta(hours=10)
        points = [
            validator_module["DataPoint"](
                value=0.054, source="src1", fetched_at=stale_time,
                asset="USDC", metric="apy"
            ),
        ]
        result = validator.validate(points, metric="apy")
        assert result.staleness_seconds is not None
        assert result.staleness_seconds > 36000  # > 10 часов в секундах


class TestPIT:
    def test_pit_filters_future_data(self, validator, validator_module):
        """PIT: данные после as_of отфильтровываются"""
        pit = datetime(2026, 6, 10, 12, 0)
        points = [
            validator_module["DataPoint"](
                value=0.054, source="src1",
                fetched_at=datetime(2026, 6, 10, 10, 0),  # до PIT — OK
                asset="USDC", metric="apy"
            ),
            validator_module["DataPoint"](
                value=0.060, source="src2",
                fetched_at=datetime(2026, 6, 10, 14, 0),  # после PIT — ОТФИЛЬТРОВАНО
                asset="USDC", metric="apy"
            ),
        ]
        # С PIT: только 1 источник (src1), min_sources=2 → exit
        result = validator.validate(points, metric="apy", as_of=pit)
        assert result.should_exit is True

    def test_all_before_pit_valid(self, validator, validator_module):
        """Все данные до PIT — должны пройти"""
        pit = datetime(2026, 6, 10, 15, 0)
        points = [
            validator_module["DataPoint"](
                value=0.054, source="src1",
                fetched_at=datetime(2026, 6, 10, 10, 0),  # за 5ч до PIT
                asset="USDC", metric="apy"
            ),
            validator_module["DataPoint"](
                value=0.055, source="src2",
                fetched_at=datetime(2026, 6, 10, 11, 0),  # за 4ч до PIT
                asset="USDC", metric="apy"
            ),
        ]
        result = validator.validate(points, metric="apy", as_of=pit)
        assert result.signal == "ok"

    def test_pit_no_data_at_all(self, validator, validator_module):
        """Все точки после PIT → missing → exit"""
        pit = datetime(2026, 6, 10, 8, 0)
        points = [
            validator_module["DataPoint"](
                value=0.054, source="src1",
                fetched_at=datetime(2026, 6, 10, 12, 0),  # после PIT
                asset="USDC", metric="apy"
            ),
        ]
        result = validator.validate(points, metric="apy", as_of=pit)
        assert result.status.value == "missing"
        assert result.signal == "exit"

    def test_pit_boundary_inclusive(self, validator, validator_module):
        """PIT граница включительна: fetched_at == as_of → включается"""
        pit = datetime(2026, 6, 10, 12, 0)
        points = [
            validator_module["DataPoint"](
                value=0.054, source="src1",
                fetched_at=pit,  # ровно на границе PIT
                asset="USDC", metric="depeg_pct"  # min_sources=1
            ),
        ]
        result = validator.validate(points, metric="depeg_pct", as_of=pit)
        assert result.signal == "ok"


class TestBatch:
    def test_batch_any_exit_detected(self, validator, validator_module):
        now = datetime.utcnow()
        data = {
            "apy": [
                validator_module["DataPoint"](
                    value=0.054, source="src1", fetched_at=now,
                    asset="USDC", metric="apy"
                ),
                validator_module["DataPoint"](
                    value=0.055, source="src2", fetched_at=now,
                    asset="USDC", metric="apy"
                ),
            ],
            "tvl_usd": [],  # пустые → exit
        }
        results = validator.validate_batch(data)
        assert validator.any_should_exit(results) is True

    def test_batch_all_valid(self, validator, validator_module):
        now = datetime.utcnow()
        data = {
            "apy": [
                validator_module["DataPoint"](
                    value=0.054, source="src1", fetched_at=now,
                    asset="USDC", metric="apy"
                ),
                validator_module["DataPoint"](
                    value=0.055, source="src2", fetched_at=now,
                    asset="USDC", metric="apy"
                ),
            ],
            "depeg_pct": [
                validator_module["DataPoint"](
                    value=0.001, source="src1", fetched_at=now,
                    asset="USDC", metric="depeg_pct"
                ),
            ],
        }
        results = validator.validate_batch(data)
        assert not validator.any_should_exit(results)

    def test_batch_returns_all_metrics(self, validator, validator_module):
        now = datetime.utcnow()
        data = {
            "apy": [
                validator_module["DataPoint"](
                    value=0.054, source="src1", fetched_at=now,
                    asset="USDC", metric="apy"
                ),
                validator_module["DataPoint"](
                    value=0.055, source="src2", fetched_at=now,
                    asset="USDC", metric="apy"
                ),
            ],
            "depeg_pct": [],
        }
        results = validator.validate_batch(data)
        assert "apy" in results
        assert "depeg_pct" in results

    def test_batch_empty_dict(self, validator):
        results = validator.validate_batch({})
        assert not validator.any_should_exit(results)  # нет метрик → нечего проверять


class TestStalenessModule:
    def test_staleness_fresh(self, project_root):
        import sys
        sys.path.insert(0, str(project_root))
        from spa_core.data_trust.staleness import check_staleness
        now = datetime.utcnow()
        ts = (now - timedelta(minutes=5)).isoformat()
        result = check_staleness(ts, max_seconds=3600)
        assert result["ok"] is True
        assert result["stale"] is False

    def test_staleness_stale(self, project_root):
        import sys
        sys.path.insert(0, str(project_root))
        from spa_core.data_trust.staleness import check_staleness
        now = datetime.utcnow()
        ts = (now - timedelta(hours=5)).isoformat()
        result = check_staleness(ts, max_seconds=3600)
        assert result["ok"] is False
        assert result["stale"] is True

    def test_staleness_missing_ts(self, project_root):
        import sys
        sys.path.insert(0, str(project_root))
        from spa_core.data_trust.staleness import check_staleness
        result = check_staleness(None)
        assert result["ok"] is False
        assert result["reason"] == "missing_timestamp"

    def test_staleness_invalid_ts(self, project_root):
        import sys
        sys.path.insert(0, str(project_root))
        from spa_core.data_trust.staleness import check_staleness
        result = check_staleness("not-a-date")
        assert result["ok"] is False
        assert result["reason"] == "invalid_timestamp"

    def test_check_all_stale(self, project_root):
        import sys
        sys.path.insert(0, str(project_root))
        from spa_core.data_trust.staleness import check_all_stale
        now = datetime.utcnow()
        timestamps = {
            "defillama": (now - timedelta(minutes=10)).isoformat(),
            "aave": None,
        }
        result = check_all_stale(timestamps, max_seconds=3600)
        assert result["defillama"]["ok"] is True
        assert result["aave"]["ok"] is False

    def test_staleness_pit(self, project_root):
        """PIT в staleness: проверяем свежесть относительно указанной точки"""
        import sys
        sys.path.insert(0, str(project_root))
        from spa_core.data_trust.staleness import check_staleness
        pit = datetime(2026, 6, 10, 12, 0)
        ts = datetime(2026, 6, 10, 10, 0).isoformat()  # за 2 часа до PIT
        result = check_staleness(ts, max_seconds=3600, as_of=pit)
        # 2 часа > 1 час → stale
        assert result["stale"] is True

    def test_staleness_with_z_suffix(self, project_root):
        """ISO timestamp с суффиксом Z должен парситься"""
        import sys
        sys.path.insert(0, str(project_root))
        from spa_core.data_trust.staleness import check_staleness
        now = datetime.utcnow()
        ts = (now - timedelta(minutes=5)).isoformat() + "Z"
        result = check_staleness(ts, max_seconds=3600)
        assert result["ok"] is True


class TestLLMForbidden:
    def test_validator_llm_forbidden(self, project_root):
        content = (project_root / "spa_core" / "data_trust" / "validator.py").read_text()
        assert "LLM_FORBIDDEN" in content

    def test_staleness_llm_forbidden(self, project_root):
        content = (project_root / "spa_core" / "data_trust" / "staleness.py").read_text()
        assert "LLM_FORBIDDEN" in content

    def test_no_llm_imports_validator(self, project_root):
        content = (project_root / "spa_core" / "data_trust" / "validator.py").read_text()
        forbidden = ["openai", "anthropic", "claude", "gpt", "langchain"]
        for term in forbidden:
            assert term not in content.lower(), f"Forbidden term '{term}' in validator.py"

    def test_no_llm_imports_staleness(self, project_root):
        content = (project_root / "spa_core" / "data_trust" / "staleness.py").read_text()
        forbidden = ["openai", "anthropic", "claude", "gpt", "langchain"]
        for term in forbidden:
            assert term not in content.lower(), f"Forbidden term '{term}' in staleness.py"

    def test_stdlib_only_validator(self, project_root):
        """Только stdlib — никаких внешних зависимостей"""
        content = (project_root / "spa_core" / "data_trust" / "validator.py").read_text()
        forbidden_imports = ["import requests", "import httpx", "import aiohttp",
                             "import numpy", "import pandas"]
        for imp in forbidden_imports:
            assert imp not in content, f"Non-stdlib import '{imp}' found in validator.py"
