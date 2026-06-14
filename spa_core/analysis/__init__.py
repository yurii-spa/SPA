"""
spa_core.analysis — market-level analytics (read-only, stdlib-only).

Modules:
    market_regime  — MarketRegimeDetector (4-class DeFi regime classifier)
"""
from .market_regime import MarketRegimeDetector

__all__ = ["MarketRegimeDetector"]
