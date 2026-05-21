# spa_core/backtesting/
# Backtesting engine v0.9 for SPA strategy replay.
#
# Usage:
#   from backtesting.data_loader import generate_synthetic_history
#   from backtesting.engine import BacktestEngine
#
#   history = generate_synthetic_history(days=90)
#   result = BacktestEngine().run(history)
#   print(result.metrics)
