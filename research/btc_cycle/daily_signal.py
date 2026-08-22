"""research/btc_cycle/daily_signal.py — продюсер дневного сигнала BTC-движка (ADR-118).

Research-слой (pandas РАЗРЕШЁН здесь — это НЕ spa_core-рантайм; инвариант #4 цел).
Обязанность: раз в день посчитать целевую долю BTC чемпионом v0.1 (k применить
здесь же) и атомарно записать data/btc_cycle/target_share.json. Бухгалтер книги
(spa_core.paper_trading.btc_nav, stdlib) читает ТОЛЬКО этот файл fail-closed.

ЧЕСТНАЯ ГРАНИЦА СЕГОДНЯ: канонический чемпион v0.1 (backtest.py), датасеты и
fetch-логика (checkonchain + FRED) в репозитории ОТСУТСТВУЮТ (см. README —
«главная потеря»; запрошены у владельца 22.08). До их появления продюсер
НИЧЕГО не пишет и честно говорит NO_ENGINE — выдуманный сигнал хуже дыры:
бухгалтер запишет gap, и трек останется доказуемым.

Подключение движка (когда владелец передаст файлы):
  1) backtest.py владельца → research/btc_cycle/engine_v01.py (как есть, без правок);
  2) сюда — fetch сегодняшних входов + вызов лестницы на СЕГОДНЯ + запись сигнала;
  3) k (0.7 по вердикту) применяется здесь и пишется в сигнал явно.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]


def main() -> int:
    try:
        sys.path.insert(0, str(_HERE))
        import engine_v01  # noqa: F401 — канонический чемпион владельца
    except ImportError:
        print("btc_cycle daily_signal: NO_ENGINE — research/btc_cycle/engine_v01.py "
              "отсутствует (ждём backtest.py v0.1 от владельца). Сигнал НЕ записан, "
              "бухгалтер честно запишет gap.", file=sys.stderr)
        return 0  # записанная дыра = успешный тик (fail-closed, не авария агента)
    # Движок есть — но проводка ещё не написана (следующий шаг после передачи
    # файлов). Не выдумываем: скажем вслух и выйдем нулём.
    print("btc_cycle daily_signal: engine_v01 найден, но проводка fetch→ladder→signal "
          "ещё не подключена — см. ADR-118, шаг 2.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
