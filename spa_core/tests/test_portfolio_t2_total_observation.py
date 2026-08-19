"""Наблюдение за суммарным потолком T2 на КНИГЕ (`check_portfolio_health`).

Что закреплено — ровно три вещи, ни одной больше:

1. **Нарушение НАЗЫВАЕТСЯ.** Книга с долей T2 выше `max_total_t2_allocation`
   (50 %, RiskPolicy v1.0) больше не проходит портфельную проверку молча:
   в `warnings` появляется `T2_TOTAL_WARN` с измеренной долей и потолком.
   До 2026-08-19 отчёт был пуст полностью (замер карточки
   `agent-t2-total-cap-ne-proveryaetsya-na-portfele.md`: `approved=True`,
   `violations=[]`, `warnings=[]` при 60 % в T2).
2. **Поведение с деньгами НЕ ИЗМЕНИЛОСЬ.** Наблюдение живёт в `warnings`, а не
   в `violations`. Это не косметика: `violations` на портфельном пути дают
   `approved=False`, а `PaperTradingEngine.manage_risk` на неодобренном
   здоровье закрывает ВСЕ позиции. Наблюдение, ставшее violation, означало бы
   принудительную продажу книги — money-path, только через ADR и владельца.
3. **Ложных срабатываний нет.** Книга ровно на потолке (50 %) и книга под ним
   остаются без этого предупреждения: `>` строгое, как и на пути входа.

Тест офлайновый и детерминированный: ни `data/`, ни сети, ни живого реестра.
Свежести здесь нет вообще, поэтому нет и дат — ни литеральных, ни вычисленных.
"""
from __future__ import annotations

import pytest

from spa_core.risk.policy import Position, PortfolioState, RiskConfig, RiskPolicy

CAP = 100_000.0
CFG = RiskConfig()
MARK = "t2_total_warn"


def _pos(key: str, tier: str, pct: float, chain: str = "ethereum") -> Position:
    amount = CAP * pct
    return Position(
        protocol_key=key,
        tier=tier,
        asset="USDC",
        amount_usd=amount,
        apy_at_open=5.0,
        current_apy=5.0,
        unrealized_pnl_usd=0.0,
        days_held=30.0,
        chain=chain,
    )


def _book(*positions: Position) -> PortfolioState:
    return PortfolioState(total_capital_usd=CAP, positions=list(positions))


def _health(state: PortfolioState):
    # capacity/axes требуют внешних карт и warn-only — на вердикт не влияют.
    return RiskPolicy().check_portfolio_health(state, check_capacity=False)


def _t2_warnings(result) -> list[str]:
    return [w for w in result.warnings if MARK in w.lower()]


def _breached_book() -> PortfolioState:
    """Книга карточки: T1 35 % + три T2 по 20 % → 60 % в T2 при потолке 50 %."""
    return _book(
        _pos("aave_v3", "T1", 0.35),
        _pos("morpho_blue", "T2", 0.20),
        _pos("euler_v2", "T2", 0.20),
        _pos("pendle", "T2", 0.20),
    )


# ── Сторона 1: нарушение названо ────────────────────────────────────────────

def test_breached_book_is_named_in_warnings():
    """60 % в T2 → предупреждение с долей и потолком. Откат → тест красный."""
    book = _breached_book()
    assert book.t2_allocation_pct() == pytest.approx(0.60)

    hits = _t2_warnings(_health(book))
    assert hits, (
        "Наблюдение за суммарным T2 на книге исчезло: книга 60 % в T2 снова "
        "проходит портфельную проверку молча (regression карточки "
        "agent-t2-total-cap-ne-proveryaetsya-na-portfele.md)."
    )
    text = hits[0].lower()
    assert "60.0%" in text, hits          # измеренная доля названа
    assert "50.0%" in text, hits          # потолок назван
    assert "not a gate" in text, hits     # и то, что это НЕ гейт, — тоже


def test_breach_by_tier_demotion_without_any_trade_is_named():
    """Сценарий ADR-055: тир динамический, книга нарушает потолок БЕЗ сделки.

    Путь входа такую книгу не увидит никогда — он проверяет приращение.
    """
    before = _book(
        _pos("aave_v3", "T1", 0.40),
        _pos("spark_susds", "T1", 0.35),
        _pos("morpho_blue", "T2", 0.20),
    )
    assert not _t2_warnings(_health(before))

    # Куратор демоутит уже удерживаемый spark_susds T1 → T2. Ни одной сделки.
    after = _book(
        _pos("aave_v3", "T1", 0.40),
        _pos("spark_susds", "T2", 0.35),
        _pos("morpho_blue", "T2", 0.20),
    )
    assert after.t2_allocation_pct() == pytest.approx(0.55)
    assert _t2_warnings(_health(after)), "демоушен тира прошёл незамеченным"


# ── Сторона 2: поведение с деньгами не изменилось ───────────────────────────

def test_naming_does_not_gate_and_does_not_force_selling():
    """Нарушенная книга по-прежнему `approved=True` с пустыми violations.

    Если эта проверка когда-нибудь станет violation — это принудительное
    закрытие всех позиций в `manage_risk`. Такое изменение допустимо только
    вместе с ADR и решением владельца, и тест обязан это остановить.
    """
    health = _health(_breached_book())
    assert health.approved is True, (
        "Суммарный T2 на книге стал гейтом — это ИЗМЕНЕНИЕ money-path "
        "(violations → approved=False → manage_risk закрывает все позиции). "
        "Нужен ADR и решение владельца, а не правка теста."
    )
    assert health.violations == []
    assert not any(MARK in v.lower() for v in health.violations)


def test_thresholds_untouched():
    """Пороги и версия политики не сдвинуты этой правкой."""
    assert CFG.max_total_t2_allocation == 0.50
    assert CFG.version == "v1.0"


# ── Сторона 3: без ложных срабатываний ──────────────────────────────────────

def test_book_exactly_at_cap_stays_quiet():
    """Ровно 50 % — не нарушение (`>` строгое, как и на входе)."""
    book = _book(
        _pos("aave_v3", "T1", 0.35),
        _pos("morpho_blue", "T2", 0.20),
        _pos("euler_v2", "T2", 0.20),
        _pos("pendle", "T2", 0.10),
    )
    assert book.t2_allocation_pct() == pytest.approx(0.50)
    assert not _t2_warnings(_health(book))


def test_book_below_cap_and_empty_book_stay_quiet():
    """Книга под потолком и пустая книга — тишина."""
    below = _book(_pos("aave_v3", "T1", 0.45), _pos("morpho_blue", "T2", 0.20))
    assert not _t2_warnings(_health(below))
    assert not _t2_warnings(_health(_book()))


def test_all_t1_book_stays_quiet():
    """Книга целиком в T1 (95 % задеплоено) не должна порождать T2-предупреждение."""
    book = _book(_pos("aave_v3", "T1", 0.40), _pos("spark_susds", "T1", 0.40),
                 _pos("compound_v3", "T1", 0.15))
    assert book.t2_allocation_pct() == pytest.approx(0.0)
    assert not _t2_warnings(_health(book))
