"""SPA Stress Testing module (MP-112).

Historical DeFi crisis scenarios for portfolio stress testing.
Stdlib only. No IO — pure simulation functions.
"""
from .stress_engine import (
    SCENARIOS,
    StressScenario,
    StressResult,
    run_stress_test,
    run_all_scenarios,
    generate_stress_report,
)

__all__ = [
    "SCENARIOS",
    "StressScenario",
    "StressResult",
    "run_stress_test",
    "run_all_scenarios",
    "generate_stress_report",
]
