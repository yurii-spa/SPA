"""Восьмой вход CIO — книги + ёмкость (директива владельца 2026-08-31).

До этого входа chief_investment был слеп к трём книгам: семь его аналитиков —
протокольные, а Balanced/Aggressive ведут реальный трек с 23.08 (ADR-125).
Вливание — в СУЩЕСТВУЮЩИЙ контур через read_feed (прецедент газ-агента,
«не второй копией CIO»), карточка `inbox-sliv-aggressive-cio-obyazan-kurirovat-pr`.

Два теста здесь важнее остальных: (1) нарушение ёмкости НЕ поднимает постуру —
координатор warn-only по решению владельца 30.08, а постура ранга 3 включает
no_increase в directive.py, то есть утечка в постуру превратила бы предупреждение
в гейт через чёрный ход; (2) книги не раздувают n_analysts — покрытие считает
семь продукт-агентов, у книг нет артефакта-посредника.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json

from spa_core.investment_os.agents.chief_investment import ChiefInvestmentAgent
from spa_core.investment_os.harness import UNKNOWN


def _layout(tmp_path):
    """Прод-раскладка: data/ (книги) + data/investment_os/ (аналитики)."""
    data = tmp_path / "data"
    ios = data / "investment_os"
    ios.mkdir(parents=True)
    return data, ios


def _seed_analysts(ios, **artifacts):
    for name, payload in artifacts.items():
        (ios / f"{name}.json").write_text(json.dumps(payload))


def _seed_books(data, maple_each=2_000.0, tvl=1_000_000.0):
    (data / "current_positions.json").write_text(json.dumps(
        {"positions": {"maple": maple_each}}))
    (data / "hy_paper_trading.json").write_text(json.dumps(
        {"seed_equity": 100_000.0, "equity": 100_100.0, "start_date": "2026-08-23",
         "positions": [{"protocol": "maple", "notional_usd": maple_each}]}))
    (data / "lp_paper_trading.json").write_text(json.dumps(
        {"seed_equity": 100_000.0, "equity": 100_200.0, "start_date": "2026-08-23",
         "positions": [{"protocol": "maple", "notional_usd": maple_each}]}))
    (data / "adapter_orchestrator_status.json").write_text(json.dumps(
        {"adapters": [{"protocol": "maple", "tvl_usd": tvl}]}))


def test_books_section_reaches_the_house_view(tmp_path):
    data, ios = _layout(tmp_path)
    _seed_analysts(ios, market_regime={"combined_posture": "STABLE"})
    _seed_books(data)
    out = ChiefInvestmentAgent(data_dir=ios).analyze()
    books = out["house_view"]["books"]
    assert isinstance(books, dict)
    assert books["summary"]["books"]["balanced"]["equity"] == 100_100.0
    assert out["coverage"]["books_input"] == "available"


def test_capacity_violation_lands_in_risk_concerns(tmp_path):
    data, ios = _layout(tmp_path)
    _seed_analysts(ios, market_regime={"combined_posture": "STABLE"})
    # три книги по $4k в один пул с TVL $1M: кэп 1% = $10k, сумма $12k — нарушение
    _seed_books(data, maple_each=4_000.0)
    out = ChiefInvestmentAgent(data_dir=ios).analyze()
    violations = out["house_view"]["risk_concerns"]["cross_book_capacity"]
    assert violations and any("maple" in v for v in violations)


def test_capacity_violation_NEVER_raises_the_posture(tmp_path):
    """Сердце файла: warn-only решение владельца 30.08. Постура ранга 3 включает
    no_increase (directive.py) — утечка ёмкости в постуру сделала бы warn-only
    координатор гейтом через чёрный ход."""
    data, ios = _layout(tmp_path)
    _seed_analysts(ios, market_regime={"combined_posture": "STABLE"},
                   red_team={"posture": "NO_THREAT_OBSERVED"})
    _seed_books(data, maple_each=4_000.0)  # заведомое нарушение ёмкости
    out = ChiefInvestmentAgent(data_dir=ios).analyze()
    assert out["house_view"]["risk_concerns"]["cross_book_capacity"]  # нарушение видно
    assert out["house_view"]["overall_posture"] == "STABLE"           # постура не тронута


def test_books_do_not_inflate_analyst_coverage(tmp_path):
    data, ios = _layout(tmp_path)
    _seed_analysts(ios,
                   market_regime={"combined_posture": "STABLE"},
                   red_team={"posture": "NO_THREAT_OBSERVED"})
    _seed_books(data)
    out = ChiefInvestmentAgent(data_dir=ios).analyze()
    assert out["coverage"]["n_analysts"] == 2  # книги НЕ считаются аналитиком
    assert "books" not in out["coverage"]["available"]


def test_missing_book_files_degrade_to_unknown_not_crash(tmp_path):
    data, ios = _layout(tmp_path)
    _seed_analysts(ios, market_regime={"combined_posture": "STABLE"})
    # книг нет вовсе — collect_books_summary честно вернёт unavailable-книги,
    # coordinator вернёт пустой ok; вход остаётся available (пустота — честный ответ)
    out = ChiefInvestmentAgent(data_dir=ios).analyze()
    books = out["house_view"]["books"]
    assert isinstance(books, dict)
    assert books["summary"]["combined"]["books_available"] == 0
    assert out["house_view"]["risk_concerns"]["cross_book_capacity"] == []


def test_no_analysts_still_fail_closed_unknown(tmp_path):
    """Прежний fail-closed не размыт восьмым входом: ноль аналитиков → UNKNOWN,
    даже если книги читаются прекрасно."""
    data, ios = _layout(tmp_path)
    _seed_books(data)
    out = ChiefInvestmentAgent(data_dir=ios).analyze()
    assert out["status"] == UNKNOWN
