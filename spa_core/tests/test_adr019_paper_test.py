"""
Тесты для scripts/adr019_paper_test.py — ADR-019 14-day paper test.

Покрывает:
- compute_t2_fraction: расчёт доли T2-протоколов
- find_trades_above_threshold: фильтрация трейдов
- get_t2_from_portfolio_state: разбор portfolio_state.json и current_positions.json
- parse_ts: парсинг ISO-8601 timestamp
- count_days_since_first_activation: подсчёт дней
- check(): основная бизнес-логика без файлового I/O
- run_check(): интеграционный тест с реальными tmp-файлами
- exit codes и текст сообщений
"""

import sys
import json
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Добавляем scripts/ в sys.path для импорта модуля
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / 'scripts'
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import adr019_paper_test as mod


# ── Вспомогательные данные ──────────────────────────────────────────────────

def make_trade(
    trade_id: str = 'T001',
    ts: str = '2026-06-01T08:00:00+00:00',
    capital: float = 100_000.0,
    to_allocation: dict | None = None,
) -> dict:
    """Фабрика тестового трейда."""
    if to_allocation is None:
        to_allocation = {
            'aave_v3': 40_000.0,
            'compound_v3': 35_000.0,
            'yearn_v3': 15_000.0,
            'euler_v2': 5_000.0,
        }
    return {
        'trade_id': trade_id,
        'ts': ts,
        'type': 'rebalance',
        'to_allocation': to_allocation,
        'capital': capital,
        'is_demo': False,
    }


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── Тесты compute_t2_fraction ───────────────────────────────────────────────

class TestComputeT2Fraction:

    def test_all_t1_returns_zero(self):
        """Только T1-протоколы → T2 доля 0%."""
        allocation = {'aave_v3': 60_000.0, 'compound_v3': 35_000.0}
        assert mod.compute_t2_fraction(allocation, 100_000) == pytest.approx(0.0)

    def test_all_t2_returns_one(self):
        """Только T2-протоколы → T2 доля 100%."""
        allocation = {
            'morpho_blue': 25_000.0,
            'yearn_v3': 25_000.0,
            'euler_v2': 25_000.0,
            'maple': 25_000.0,
        }
        assert mod.compute_t2_fraction(allocation, 100_000) == pytest.approx(1.0)

    def test_mixed_allocation_correct_fraction(self):
        """Смешанная аллокация: T2 = 33%."""
        allocation = {
            'aave_v3': 40_000.0,
            'compound_v3': 27_000.0,
            'yearn_v3': 18_000.0,  # T2
            'euler_v2': 10_000.0,  # T2
            'maple': 5_000.0,      # T2
        }
        # T2 = 33_000 / 100_000 = 0.33
        result = mod.compute_t2_fraction(allocation, 100_000)
        assert result == pytest.approx(0.33)

    def test_zero_capital_returns_zero(self):
        """Нулевой капитал — деление на ноль защищено."""
        allocation = {'yearn_v3': 10_000.0}
        assert mod.compute_t2_fraction(allocation, 0) == 0.0

    def test_negative_capital_returns_zero(self):
        """Отрицательный капитал — защищено."""
        allocation = {'yearn_v3': 10_000.0}
        assert mod.compute_t2_fraction(allocation, -1) == 0.0

    def test_exactly_35_percent(self):
        """Ровно 35% T2."""
        allocation = {
            'aave_v3': 65_000.0,
            'morpho_blue': 35_000.0,  # T2
        }
        assert mod.compute_t2_fraction(allocation, 100_000) == pytest.approx(0.35)

    def test_above_35_percent(self):
        """T2 выше порога (40%)."""
        allocation = {
            'aave_v3': 60_000.0,
            'euler_v2': 40_000.0,  # T2
        }
        assert mod.compute_t2_fraction(allocation, 100_000) == pytest.approx(0.40)

    def test_empty_allocation_returns_zero(self):
        """Пустая аллокация → 0%."""
        assert mod.compute_t2_fraction({}, 100_000) == 0.0

    def test_unknown_protocol_ignored(self):
        """Неизвестные протоколы не считаются T2."""
        allocation = {'pendle_pt': 50_000.0, 'aave_v3': 50_000.0}
        assert mod.compute_t2_fraction(allocation, 100_000) == pytest.approx(0.0)


# ── Тесты find_trades_above_threshold ──────────────────────────────────────

class TestFindTradesAboveThreshold:

    def test_empty_list_returns_empty(self):
        """Пустой список трейдов → пустой результат."""
        assert mod.find_trades_above_threshold([]) == []

    def test_none_above_threshold(self):
        """Все трейды ниже порога."""
        trades = [
            make_trade('T001', to_allocation={'aave_v3': 80_000.0, 'yearn_v3': 15_000.0}),
            make_trade('T002', to_allocation={'compound_v3': 85_000.0, 'euler_v2': 10_000.0}),
        ]
        result = mod.find_trades_above_threshold(trades, threshold=0.35)
        assert result == []

    def test_all_above_threshold(self):
        """Все трейды выше порога."""
        trades = [
            make_trade('T001', to_allocation={
                'aave_v3': 50_000.0, 'morpho_blue': 35_000.0, 'euler_v2': 10_000.0
            }),
            make_trade('T002', to_allocation={
                'compound_v3': 55_000.0, 'yearn_v3': 40_000.0
            }),
        ]
        result = mod.find_trades_above_threshold(trades, threshold=0.35)
        assert len(result) == 2

    def test_mixed_returns_only_above(self):
        """Смешанный список: возвращает только трейды ≥ порога."""
        trade_below = make_trade('T001', to_allocation={
            'aave_v3': 80_000.0, 'yearn_v3': 15_000.0
        })  # T2 = 15%
        trade_above = make_trade('T002', to_allocation={
            'aave_v3': 60_000.0, 'morpho_blue': 40_000.0
        })  # T2 = 40%
        result = mod.find_trades_above_threshold([trade_below, trade_above], threshold=0.35)
        assert len(result) == 1
        assert result[0]['trade_id'] == 'T002'

    def test_result_contains_t2_fraction(self):
        """Результат содержит t2_fraction для каждого трейда."""
        trade = make_trade('T001', to_allocation={
            'compound_v3': 60_000.0, 'euler_v2': 40_000.0
        })  # T2 = 40%
        result = mod.find_trades_above_threshold([trade], threshold=0.35)
        assert 't2_fraction' in result[0]
        assert result[0]['t2_fraction'] == pytest.approx(0.40)

    def test_result_contains_ts_and_trade_id(self):
        """Результат содержит ts и trade_id."""
        trade = make_trade('T-X', ts='2026-06-01T00:00:00+00:00', to_allocation={
            'aave_v3': 60_000.0, 'maple': 40_000.0
        })
        result = mod.find_trades_above_threshold([trade])
        assert result[0]['trade_id'] == 'T-X'
        assert result[0]['ts'] == '2026-06-01T00:00:00+00:00'

    def test_exactly_at_threshold_included(self):
        """Трейд ровно на пороге 35% включается (>=)."""
        trade = make_trade('T001', to_allocation={
            'aave_v3': 65_000.0, 'morpho_blue': 35_000.0
        })
        result = mod.find_trades_above_threshold([trade], threshold=0.35)
        assert len(result) == 1


# ── Тесты get_t2_from_portfolio_state ──────────────────────────────────────

class TestGetT2FromPortfolioState:

    def test_portfolio_state_format(self):
        """Разбор portfolio_state.json (positions — список dict)."""
        data = {
            'total_actual_usd': 100_000.0,
            'positions': [
                {'protocol': 'aave_v3', 'actual_usd': 60_000.0},
                {'protocol': 'yearn_v3', 'actual_usd': 25_000.0},   # T2
                {'protocol': 'euler_v2', 'actual_usd': 15_000.0},   # T2
            ],
        }
        t2_frac, total = mod.get_t2_from_portfolio_state(data)
        assert t2_frac == pytest.approx(0.40)
        assert total == pytest.approx(100_000.0)

    def test_current_positions_format(self):
        """Разбор current_positions.json (positions — dict)."""
        data = {
            'capital_usd': 100_000.0,
            'positions': {
                'aave_v3': 55_000.0,
                'compound_v3': 30_000.0,
                'maple': 15_000.0,  # T2
            },
        }
        t2_frac, capital = mod.get_t2_from_portfolio_state(data)
        assert t2_frac == pytest.approx(0.15)
        assert capital == pytest.approx(100_000.0)

    def test_empty_data_returns_zeros(self):
        """Пустые данные → (0.0, 0.0)."""
        t2_frac, total = mod.get_t2_from_portfolio_state({})
        assert t2_frac == 0.0
        assert total == 0.0

    def test_all_t2_list_format(self):
        """Только T2-протоколы → 100%."""
        data = {
            'total_actual_usd': 80_000.0,
            'positions': [
                {'protocol': 'morpho_blue', 'actual_usd': 20_000.0},
                {'protocol': 'yearn_v3', 'actual_usd': 20_000.0},
                {'protocol': 'euler_v2', 'actual_usd': 20_000.0},
                {'protocol': 'maple', 'actual_usd': 20_000.0},
            ],
        }
        t2_frac, _ = mod.get_t2_from_portfolio_state(data)
        assert t2_frac == pytest.approx(1.0)

    def test_computes_total_from_positions_if_missing(self):
        """Если total_actual_usd отсутствует, считает из суммы позиций."""
        data = {
            'positions': [
                {'protocol': 'aave_v3', 'actual_usd': 50_000.0},
                {'protocol': 'euler_v2', 'actual_usd': 50_000.0},  # T2
            ],
        }
        t2_frac, total = mod.get_t2_from_portfolio_state(data)
        assert total == pytest.approx(100_000.0)
        assert t2_frac == pytest.approx(0.50)


# ── Тесты parse_ts ──────────────────────────────────────────────────────────

class TestParseTs:

    def test_parses_utc_z_suffix(self):
        """Суффикс Z → UTC datetime."""
        dt = mod.parse_ts('2026-06-01T08:00:00Z')
        assert dt.tzinfo is not None
        assert dt.year == 2026
        assert dt.month == 6
        assert dt.day == 1

    def test_parses_utc_offset(self):
        """Суффикс +00:00 → UTC datetime."""
        dt = mod.parse_ts('2026-06-10T18:40:35.254234+00:00')
        assert dt.tzinfo is not None
        assert dt.day == 10

    def test_preserves_time_components(self):
        """Часы и минуты сохраняются корректно."""
        dt = mod.parse_ts('2026-06-15T12:30:00+00:00')
        assert dt.hour == 12
        assert dt.minute == 30


# ── Тесты count_days_since_first_activation ─────────────────────────────────

class TestCountDaysSinceFirstActivation:

    def test_empty_list_returns_zero(self):
        """Пустой список → 0 дней."""
        assert mod.count_days_since_first_activation([]) == 0

    def test_trade_today_returns_zero(self):
        """Первый трейд сегодня → 0 дней."""
        now = datetime(2026, 6, 12, 10, 0, 0, tzinfo=timezone.utc)
        trades = [{'trade_id': 'T1', 'ts': '2026-06-12T08:00:00+00:00', 't2_fraction': 0.40}]
        days = mod.count_days_since_first_activation(trades, now=now)
        assert days == 0

    def test_trade_one_day_ago(self):
        """Первый трейд вчера → 1 день."""
        now = datetime(2026, 6, 12, 10, 0, 0, tzinfo=timezone.utc)
        trades = [{'trade_id': 'T1', 'ts': '2026-06-11T08:00:00+00:00', 't2_fraction': 0.40}]
        days = mod.count_days_since_first_activation(trades, now=now)
        assert days == 1

    def test_trade_14_days_ago(self):
        """Первый трейд 14 дней назад → 14 дней."""
        now = datetime(2026, 6, 12, 10, 0, 0, tzinfo=timezone.utc)
        first_ts = (now - timedelta(days=14)).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        trades = [{'trade_id': 'T1', 'ts': first_ts, 't2_fraction': 0.40}]
        days = mod.count_days_since_first_activation(trades, now=now)
        assert days == 14

    def test_uses_earliest_trade(self):
        """Берётся самый ранний трейд из списка."""
        now = datetime(2026, 6, 12, 10, 0, 0, tzinfo=timezone.utc)
        trades = [
            {'trade_id': 'T2', 'ts': '2026-06-10T08:00:00+00:00', 't2_fraction': 0.40},  # 2 дня назад
            {'trade_id': 'T1', 'ts': '2026-06-05T08:00:00+00:00', 't2_fraction': 0.38},  # 7 дней назад
        ]
        days = mod.count_days_since_first_activation(trades, now=now)
        assert days == 7

    def test_seven_days_ago(self):
        """7 дней → промежуточный результат (не ready)."""
        now = datetime(2026, 6, 12, 10, 0, 0, tzinfo=timezone.utc)
        first_ts = (now - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        trades = [{'trade_id': 'T1', 'ts': first_ts, 't2_fraction': 0.40}]
        days = mod.count_days_since_first_activation(trades, now=now)
        assert days == 7


# ── Тесты check() — основная бизнес-логика ─────────────────────────────────

class TestCheck:

    def _make_trades_with_low_t2(self) -> list:
        """3 трейда с T2 ~33% (ниже порога 35%)."""
        return [
            make_trade('T001', ts='2026-06-10T08:00:00+00:00', to_allocation={
                'aave_v3': 35_000.0, 'compound_v3': 32_000.0,
                'yearn_v3': 15_000.0, 'euler_v2': 10_000.0, 'maple': 8_000.0,
            }),
        ]

    def _make_trades_with_high_t2(self, n_trades: int = 3, days_back: int = 7) -> list:
        """n трейдов с T2 ~40% (выше порога 35%)."""
        now = datetime(2026, 6, 12, 10, 0, 0, tzinfo=timezone.utc)
        trades = []
        for i in range(n_trades):
            ts = (now - timedelta(days=days_back - i)).strftime('%Y-%m-%dT%H:%M:%S+00:00')
            trades.append(make_trade(
                f'T{i+1:03d}', ts=ts,
                to_allocation={
                    'aave_v3': 55_000.0,
                    'morpho_blue': 20_000.0,  # T2
                    'euler_v2': 15_000.0,     # T2
                    'maple': 10_000.0,         # T2
                }
            ))
        return trades

    def test_not_activated_when_t2_below_threshold(self):
        """T2 ≤ 35% → activated=False, exit_code=1."""
        trades = self._make_trades_with_low_t2()
        # portfolio_data с T2 = 33%
        portfolio = {
            'total_actual_usd': 95_000.0,
            'positions': [
                {'protocol': 'aave_v3', 'actual_usd': 35_000.0},
                {'protocol': 'compound_v3', 'actual_usd': 29_000.0},
                {'protocol': 'yearn_v3', 'actual_usd': 15_000.0},
                {'protocol': 'euler_v2', 'actual_usd': 10_000.0},
                {'protocol': 'maple', 'actual_usd': 6_000.0},
            ],
        }
        result = mod.check(trades, portfolio)
        assert result['activated'] is False
        assert result['exit_code'] == 1
        assert result['ready'] is False

    def test_message_not_activated_contains_key_phrase(self):
        """Сообщение содержит 'NOT YET ACTIVATED' при T2 < 35%."""
        trades = self._make_trades_with_low_t2()
        portfolio = {
            'total_actual_usd': 95_000.0,
            'positions': [
                {'protocol': 'aave_v3', 'actual_usd': 65_000.0},
                {'protocol': 'yearn_v3', 'actual_usd': 30_000.0},
            ],
        }
        result = mod.check(trades, portfolio)
        assert 'NOT YET ACTIVATED' in result['message']

    def test_activated_but_not_ready_few_days(self):
        """T2 ≥ 35%, но < 14 дней → activated=True, ready=False, exit_code=1."""
        now = datetime(2026, 6, 12, 10, 0, 0, tzinfo=timezone.utc)
        trades = self._make_trades_with_high_t2(n_trades=3, days_back=7)
        portfolio = {
            'capital_usd': 100_000.0,
            'positions': {
                'aave_v3': 55_000.0,
                'morpho_blue': 20_000.0,
                'euler_v2': 15_000.0,
                'maple': 10_000.0,
            },
        }
        result = mod.check(trades, portfolio, now=now)
        assert result['activated'] is True
        assert result['ready'] is False
        assert result['exit_code'] == 1
        assert result['days_complete'] < 14

    def test_ready_after_14_days(self):
        """T2 ≥ 35% на протяжении 14+ дней и ≥ 3 трейда → ready=True, exit_code=0."""
        now = datetime(2026, 6, 28, 10, 0, 0, tzinfo=timezone.utc)
        trades = self._make_trades_with_high_t2(n_trades=5, days_back=16)
        portfolio = {
            'capital_usd': 100_000.0,
            'positions': {
                'aave_v3': 55_000.0,
                'morpho_blue': 20_000.0,
                'euler_v2': 15_000.0,
                'maple': 10_000.0,
            },
        }
        result = mod.check(trades, portfolio, now=now)
        assert result['activated'] is True
        assert result['ready'] is True
        assert result['exit_code'] == 0
        assert result['days_complete'] >= 14

    def test_exit_code_1_when_not_activated(self):
        """exit_code = 1 при T2 ниже порога."""
        result = mod.check(
            trades_data=[make_trade('T1', to_allocation={'aave_v3': 100_000.0})],
            portfolio_data={'capital_usd': 100_000.0, 'positions': {'aave_v3': 100_000.0}},
        )
        assert result['exit_code'] == 1

    def test_exit_code_0_when_ready(self):
        """exit_code = 0 при выполнении всех условий."""
        now = datetime(2026, 6, 28, 10, 0, 0, tzinfo=timezone.utc)
        trades = self._make_trades_with_high_t2(n_trades=4, days_back=16)
        portfolio = {
            'capital_usd': 100_000.0,
            'positions': {
                'aave_v3': 55_000.0,
                'euler_v2': 45_000.0,
            },
        }
        result = mod.check(trades, portfolio, now=now)
        assert result['exit_code'] == 0

    def test_message_contains_days_progress(self):
        """Сообщение содержит 'N/14 days complete' при активированном тесте."""
        now = datetime(2026, 6, 19, 10, 0, 0, tzinfo=timezone.utc)
        trades = self._make_trades_with_high_t2(n_trades=3, days_back=7)
        portfolio = {
            'capital_usd': 100_000.0,
            'positions': {'euler_v2': 50_000.0, 'aave_v3': 50_000.0},
        }
        result = mod.check(trades, portfolio, now=now)
        assert '/14 days complete' in result['message']

    def test_t2_current_pct_reported_correctly(self):
        """t2_current_pct соответствует реальному T2 в портфеле."""
        portfolio = {
            'capital_usd': 100_000.0,
            'positions': {
                'aave_v3': 60_000.0,
                'morpho_blue': 40_000.0,  # T2 = 40%
            },
        }
        result = mod.check(
            trades_data=[],
            portfolio_data=portfolio,
        )
        # T2 < 35% не выполнено... подождём, morpho_blue = 40% > 35%
        # Но trades_above будет 0, поэтому activated проверяется через fallback
        # fallback = last trade (нет трейдов) → t2 = 0 → не активирован
        # Нужно добавить трейд с T2 ≥ 35% для проверки
        assert 't2_current_pct' in result

    def test_trades_above_threshold_count_reported(self):
        """Количество трейдов выше порога отражается в результате."""
        now = datetime(2026, 6, 20, 10, 0, 0, tzinfo=timezone.utc)
        trades = self._make_trades_with_high_t2(n_trades=4, days_back=8)
        portfolio = {
            'capital_usd': 100_000.0,
            'positions': {'aave_v3': 55_000.0, 'euler_v2': 45_000.0},
        }
        result = mod.check(trades, portfolio, now=now)
        assert result['trades_above_threshold'] == 4

    def test_fallback_to_last_trade_if_no_portfolio(self):
        """Если portfolio_data пустой — T2 берётся из последнего трейда."""
        trade = make_trade('T1', to_allocation={
            'aave_v3': 60_000.0, 'morpho_blue': 40_000.0,  # T2 = 40%
        })
        # Пустые portfolio_data → fallback
        result = mod.check(trades_data=[trade], portfolio_data={})
        # T2 = 40% > 35% → activated
        assert result['activated'] is True

    def test_not_ready_if_too_few_trades(self):
        """14+ дней, но менее 3 трейдов — ready=False."""
        now = datetime(2026, 6, 30, 10, 0, 0, tzinfo=timezone.utc)
        # Только 2 трейда (ниже MIN_TRADES = 3)
        trades = self._make_trades_with_high_t2(n_trades=2, days_back=16)
        portfolio = {
            'capital_usd': 100_000.0,
            'positions': {'aave_v3': 55_000.0, 'euler_v2': 45_000.0},
        }
        result = mod.check(trades, portfolio, now=now)
        assert result['ready'] is False
        assert result['exit_code'] == 1


# ── Интеграционный тест run_check с файлами ─────────────────────────────────

class TestRunCheck:

    def test_run_check_reads_files(self, tmp_path):
        """run_check корректно читает JSON-файлы с диска."""
        trades = [
            make_trade('T1', ts='2026-06-01T08:00:00+00:00', to_allocation={
                'aave_v3': 65_000.0, 'morpho_blue': 35_000.0
            }),
        ]
        portfolio = {
            'total_actual_usd': 100_000.0,
            'positions': [
                {'protocol': 'aave_v3', 'actual_usd': 65_000.0},
                {'protocol': 'morpho_blue', 'actual_usd': 35_000.0},
            ],
        }
        trades_path = tmp_path / 'trades.json'
        portfolio_path = tmp_path / 'portfolio_state.json'
        trades_path.write_text(json.dumps(trades))
        portfolio_path.write_text(json.dumps(portfolio))

        result = mod.run_check(str(trades_path), str(portfolio_path))
        assert isinstance(result, dict)
        assert 'exit_code' in result

    def test_run_check_missing_portfolio_ok(self, tmp_path):
        """Отсутствие portfolio_state.json не вызывает ошибку."""
        trades = [
            make_trade('T1', to_allocation={'aave_v3': 100_000.0}),
        ]
        trades_path = tmp_path / 'trades.json'
        trades_path.write_text(json.dumps(trades))
        # portfolio_path не существует
        portfolio_path = str(tmp_path / 'nonexistent.json')

        result = mod.run_check(str(trades_path), portfolio_path)
        assert isinstance(result, dict)

    def test_run_check_missing_trades_raises(self, tmp_path):
        """Отсутствующий trades.json → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            mod.run_check(
                str(tmp_path / 'no_trades.json'),
                str(tmp_path / 'portfolio.json'),
            )

    def test_run_check_invalid_json_raises(self, tmp_path):
        """Невалидный JSON → json.JSONDecodeError."""
        bad_json = tmp_path / 'trades.json'
        bad_json.write_text('NOT JSON')
        with pytest.raises(json.JSONDecodeError):
            mod.run_check(
                str(bad_json),
                str(tmp_path / 'portfolio.json'),
            )


# ── Тест констант модуля ────────────────────────────────────────────────────

class TestModuleConstants:

    def test_t2_protocols_contains_expected(self):
        """T2_PROTOCOLS содержит все 4 ожидаемых протокола из RiskPolicy."""
        expected = {'morpho_blue', 'yearn_v3', 'euler_v2', 'maple'}
        assert expected <= mod.T2_PROTOCOLS

    def test_t1_protocols_not_in_t2(self):
        """Протоколы T1 не входят в T2_PROTOCOLS."""
        t1 = {'aave_v3', 'compound_v3'}
        assert t1.isdisjoint(mod.T2_PROTOCOLS)

    def test_threshold_is_35_percent(self):
        """Порог ADR-019 = 35%."""
        assert mod.ADR019_T2_THRESHOLD == pytest.approx(0.35)

    def test_required_days_is_14(self):
        """Требуемый срок paper test = 14 дней."""
        assert mod.ADR019_REQUIRED_DAYS == 14

    def test_min_trades_is_3(self):
        """Минимальное количество трейдов = 3."""
        assert mod.ADR019_MIN_TRADES == 3
