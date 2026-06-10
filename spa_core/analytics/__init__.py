# analytics package
#
# MP-104 core metrics (stdlib-only, read-only). Relative imports so the
# package works both as ``spa_core.analytics`` and as top-level ``analytics``
# (legacy tests insert spa_core/ itself onto sys.path).
from .benchmark import compare_to_benchmark
from .calmar import calculate_calmar
from .concentration import calculate_concentration
from .drawdown import calculate_max_drawdown
from .sharpe import calculate_sharpe
from .streak import calculate_streaks
from .volatility import calculate_volatility

__all__ = [
    "calculate_sharpe",
    "calculate_max_drawdown",
    "calculate_volatility",
    "compare_to_benchmark",
    "calculate_streaks",
    "calculate_calmar",
    "calculate_concentration",
]
